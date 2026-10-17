"""Codex CLI channel. Every attempt is durable; bounded recovery is explicit."""
from copy import deepcopy
from dataclasses import dataclass
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from ..model_process_guard import run_guarded
from ..model_transport import BASE_INSTRUCTIONS, DISABLED_FEATURES, summarize_events
from .presentation import pack
from .contracts import ROOT, digest, encode, encode_model_schema, require, sha_bytes, strict_json


def obj(fields):
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


def array(value):
    return {"type": "array", "items": value}


def response_schema(arm="B", *, comparison_context_refs=None, candidate_refs=None, has_open_draft=None, planning_reviews=False):
    text, integer, number = {"type": "string"}, {"type": "integer"}, {"type": "number"}
    kind = lambda value: {"type": "string", "enum": [value]}
    header = obj({"version": text, "created_at": number, "valid_until": number, "freeze_until": number, "reason": text, "scope": array(integer)})
    task = obj({"id": text, "machine": integer, "lot_ids": array(text), "steps": array(integer), "visits": array(integer), "operation_ids": array(text), "not_before": number})
    hold = obj({"machine": integer, "until": number, "reason": text, "after_task_id": {"type": ["string", "null"]}})
    patch = lambda item, modes: obj({"keep": obj({"mode": {"type": "string", "enum": modes}, "ids": array(text)}), "cancel_ids": array(text), "replace": array(item), "add": array(item)})
    holds = patch(hold, ["ids", "all_except"])
    holds["properties"]["replace"] = array(obj({"ref": text, "hold": hold}))
    delta = obj({"plan_header": header, "order_policy": kind("preserve_base_machine_order_unless_explicit"),
                 "tasks": patch(task, ["ids", "all_pending_except"]), "holds": holds,
                 "machine_orders": array(obj({"machine": integer, "task_ids": array(text)}))})
    common = lambda tool: {"tool": kind(tool), "context_ref": text, "request_id": text}
    queries = {"anyOf": [obj({"kind": {"type": "string", "enum": ["machines", "operations", "tasks", "holds"]}, "ids": array(text)}),
                          obj({"kind": {"type": "string", "enum": ["machines", "operations", "tasks", "holds"]}, "cursor": text, "count": integer})]}
    queries["anyOf"] += [obj({**variant["properties"], "fields": array(text)}) for variant in list(queries["anyOf"])]
    filtered = {"kind": {"type": "string", "enum": ["machines", "operations", "tasks", "holds"]},
                "cursor": {"type": ["string", "null"]}, "count": integer,
                "where": array(obj({"field": text, "op": {"type": "string", "enum": ["eq", "contains"]},
                                     "value": {"anyOf": [text, number, {"type": "boolean"}, {"type": "null"}]}}))}
    queries["anyOf"] += [obj(filtered), obj({**filtered, "fields": array(text)})]
    actions = [obj({**common("propose_delta"), "delta": delta}),
               obj({**common("apply_candidate"), "candidate_ref": text}),
               obj({"tool": kind("get_context"), "context_ref": text}),
               obj({"tool": kind("get_context"), "context_ref": text, "since_context_ref": text}),
               obj({"tool": kind("read_entities"), "context_ref": text, "queries": array(queries)}),
               obj({"tool": kind("read_artifact"), "artifact_ref": text,
                    "path": array({"anyOf": [text, integer]}), "format": {"type": "string", "enum": ["value", "page", "text"]}, "offset": integer, "count": integer}),
               obj({**common("write_notes"), "text": text, "expected_version": integer})]
    anchors = obj({key: text for key in ("base_plan_sha256", "problem_sha256", "state_sha256", "source_sha256")})
    chunk_value = {"anyOf": [text, header, anchors]}
    chunk_items = {"anyOf": [text, task, hold, obj({"ref": text, "hold": hold}), obj({"machine": integer, "task_ids": array(text)})]}
    actions += [obj({**common("begin_proposal"), "proposal_id": text}),
                obj({**common("begin_alternative_proposal"), "proposal_id": text, "reviewed_candidate_ref": text, "reason": text}),
                obj({**common("append_proposal"), "proposal_ref": text, "expected_version": integer,
                     "chunk_id": text, "set_fields": array(obj({"path": array(text), "value": chunk_value})),
                     "append_arrays": array(obj({"path": array(text), "items": array(chunk_items)}))}),
                obj({**common("finalize_proposal"), "proposal_ref": text, "expected_version": integer})]
    if arm != "B":
        params = obj({"seed": integer, "weights": obj({k: number for k in ("tardiness", "completion", "flow", "setup")}),
                      "max_slots_per_machine": integer, "plan_version": text, "valid_until": number, "freeze_until": number})
        actions += [obj({**common("construct_candidate"), "algorithm_id": kind("constructive-gain-rate-v1"), "parameters": params, "budget_seconds": number}),
                    obj({**common("optimize_candidate"), "algorithm_id": kind("cp-global-explicit-baseline-v1"), "candidate_ref": text, "parameters": params, "budget_seconds": number})]
    if comparison_context_refs is not None:
        # Model prompts already contain the current context. Do not offer a
        # second delivery of that same observation as a model action. Meaningful
        # change-set queries against earlier owned contexts remain available.
        actions = [a for a in actions if a["properties"]["tool"]["enum"] != ["get_context"]]
        if comparison_context_refs:
            actions.append(obj({"tool": kind("get_context"), "context_ref": text,
                                "since_context_ref": {"type": "string", "enum": list(comparison_context_refs)}}))
    if candidate_refs is not None:
        # State-aware protocol, never a candidate ranking or default selection.
        hidden = {"begin_proposal", "write_notes"} if candidate_refs else {"apply_candidate", "begin_alternative_proposal"}
        if has_open_draft is False:
            hidden |= {"append_proposal", "finalize_proposal"}
        actions = [a for a in actions if a["properties"]["tool"]["enum"][0] not in hidden]
        for action in actions:
            tool = action["properties"]["tool"]["enum"][0]
            if tool == "apply_candidate":
                action["properties"]["candidate_ref"] = {"type": "string", "enum": list(candidate_refs)}
            elif tool == "begin_alternative_proposal":
                action["properties"]["reviewed_candidate_ref"] = {"type": "string", "enum": list(candidate_refs)}
    # Optional memory rides the model's explicit selection, never another call.
    for action in list(actions):
        if action["properties"]["tool"]["enum"] == ["apply_candidate"]:
            actions.append(obj({**action["properties"], "selection_note": text}))
    if planning_reviews:
        review = obj({'machine':integer,'disposition':{'type':'string','enum':['planned','deferred','insufficient_information']},
                      'reason':text,'revisit_at':{'type':['number','null']}})
        for action in list(actions):
            if action['properties']['tool']['enum']==['apply_candidate']:
                actions.append(obj({**action['properties'],'machine_reviews':array(review)}))
    descriptions = {
        "propose_delta": "Submit a complete small revision in ONE action. A candidate_checked result completes checking; no draft or finalize step is needed. Select it with a later apply_candidate if it matches your intent.",
        "apply_candidate": "Explicitly choose an exact checked candidate. This is the commit step after successful propose_delta or finalize_proposal. The host never selects for you.",
        "begin_proposal": "Open a NEW multi-call draft only when your delta is too large for one propose_delta. This does NOT complete or apply an already checked candidate.",
        "begin_alternative_proposal": "Only if you deliberately want a DIFFERENT large plan, identify the candidate you reviewed and explain why you need an alternative. This opens a new empty draft; it is never needed to apply an existing checked candidate. Existing candidates stay available.",
        "finalize_proposal": "Check an existing multi-call draft after all chunks. Not needed after propose_delta returned candidate_checked.",
    }
    for action in actions:
        tool = action["properties"]["tool"]["enum"][0]
        if tool in descriptions:
            action["description"] = descriptions[tool]
    # The wire envelope is required because Structured Outputs requires an
    # object root. It contains exactly one business action, never an action list.
    return obj({"action": {"anyOf": actions}})


PROTOCOL_TEXT = """Scheduling Harness v1.10. You decide every production task, machine, batch member,
machine order, not_before, plan validity/freeze and finite wait. Minimize priority-weighted
cumulative tardiness while considering throughput, ready waiting and unplanned work.
Use only this run's public observations. Simulation is paused during your thinking.
The context below is already the current public observation. A redundant get_context
action is not offered: only change-set queries against earlier contexts, when such
contexts exist, use get_context with since_context_ref. Read additional exact facts
with read_entities or read_artifact as needed. You are continuing the same task across calls. interaction_history
contains your own earlier actions and exact readable result references. Use those
results; request additional facts only when needed. Identical consecutive reads stop
at the configured same_read_limit. This control never chooses a production action.
One response contains exactly one action. propose_delta atomically checks a COMPLETE
delta and returns a candidate; a LATER response must explicitly apply_candidate with its
exact reference. No default selection or automatic plan repair exists.
For a small revision use propose_delta directly. candidate_checked means
the proposal is COMPLETE and checked: there is no remaining drafting/finalization step.
If a checked candidate expresses your intended plan, explicitly apply its exact
reference in your next response. You may instead inspect facts or propose a different
plan when you have a concrete reason; the host does not choose a candidate for you.
begin_proposal starts a separate NEW large draft; it is not the next step after
propose_delta. Do not reconstruct an already checked plan through chunking.
Once checked candidates exist, separate write_notes and an unqualified begin_proposal
are not offered. To remember something, include optional selection_note in your
apply_candidate action; this records your own text without another model round.
You can still query, propose a different complete delta, or explicitly open a large
ALTERNATIVE with begin_alternative_proposal (reviewed_candidate_ref and reason).
That does not remove or select any existing candidate. All checked candidates remain
available; the candidate_ref enum lists them without ranking or a default.
Queries are read-only. Every base pending task and hold needs explicit keep/cancel/replace disposition;
all_pending_except/all_except mean exactly the declared set complement. Explicit IDs of
cancelled/replaced entries must be the keep exceptions. Old dispatched tasks are excluded.
Added tasks and moved tasks require complete affected-machine orders. Empty arrays must be
declared. Headers must have full scope and new version; not_before is never clamped.
Every retained non-frozen pending task must have not_before >= current time. A past
start needs your explicit replacement or cancellation, including keep exceptions;
pending_start_validation reports these source facts without choosing a correction.
Each task needs explicit id, machine, lot_ids, steps, visits, operation_ids, not_before.
Holds need machine, finite until, reason, and after_task_id (null = unconditional).
An expired hold or an invalidated task must be explicitly replaced/cancelled. Frozen
commitments cannot be changed. Commit acceptance and production progress are different.
Private future RNG, CQT history and missing bindings are not facts you can infer.
read_entities accepts exact IDs (strings) or a catalog cursor with count <=512, returning
full fields in source order. Mixed valid/missing IDs return the valid requested entities
unchanged plus explicit missing_entities and status partial; absence from this context's
catalog does not establish completion or any hidden factory fact. You can instead specify where (1..16 AND predicates) with
cursor:null for its first page. Each predicate explicitly names a public field, op eq
or contains, and scalar value. For example, eligible_machines contains your chosen
machine and conditional eq false filters that exact set; you choose whether to use
these predicates. No filtering or ranking is implicit. Returned next_cursor is bound
to the same predicates, context and kind. Small counts and requested fields keep
results readable. read_artifact uses an exact JSON path: value uses offset=count=0;
page uses an array and positive count; text returns serialized JSON characters. Full facts,
base plan, candidate and tool feedback remain readable by their public artifact references.
Large results include exact source-order samples, object keys and array lengths, plus
concrete paged read actions. These are explicitly incomplete previews, never the full
result. Use their next_read paths/counts instead of reading the entire large object
again. Your history includes earlier small results and bounded large-result previews.
Notes are only your text memory, not authoritative factory state. They do not change plans.
Only when a delta is too large for one response, begin_proposal opens a multi-call
draft and returns chunk instructions. finalize_proposal is only for such drafts.
Public observations may use a lossless table: _record_table=lossless-v1,
columns contains field paths, each row contains the matching values in that exact order,
and constants contains [field_path, shared_value] pairs for every row. Combine those
paths to recover each original object. record_count and row order are unchanged;
no entity, value, absent field, null, number, or qualification is removed or ranked.
For heterogeneous fields, _record_table=lossless-v2 uses layouts (lists of field paths)
and rows [layout_index, values]; pair values with that layout and add constants to
recover that row. Fields absent from its layout/constants remain absent, not null.
A _literal_object wrapper is an escaped original object represented as [key,value] pairs.
Read table rows directly; table encoding alone is not a reason to re-read an artifact.
Original feedback remains available at result_ref. A history entry with result_inline_at
last_tool_feedback refers to the complete latest feedback already in this same prompt.
Return JSON {\"action\": {the one action}}. Technical anchors are bound by context_ref.
"""


def compact_feedback(value, reference, *, budget=14000):
    """Bounded public-result presentation, retaining every original byte by ref.

    Samples follow source order and never score/filter/choose production data.
    Every preview carries its exact path, coverage and executable continuation.
    """
    sections, omitted = [], 0
    def add(section):
        nonlocal omitted
        if len(encode(sections + [section])) <= budget:
            sections.append(section)
            return True
        omitted += 1
        return False
    def read(path, fmt, offset, count):
        return {"tool": "read_artifact", "artifact_ref": reference, "path": path,
                "format": fmt, "offset": offset, "count": count}
    def walk(node, path, depth):
        nonlocal omitted
        if depth > 4 or len(sections) >= 40:
            omitted += 1; return
        if isinstance(node, dict):
            keys = list(node)
            scalars = {}
            for key in keys:
                if not isinstance(node[key], (dict, list)) and len(encode(node[key])) <= 512 and len(encode(scalars)) < 1500:
                    scalars[key] = node[key]
            if not add({"path": path, "type": "object", "keys": keys[:32], "total_keys": len(keys),
                        "keys_complete": len(keys) <= 32, "scalar_fields": scalars,
                        "scalar_fields_complete": len(scalars) == sum(not isinstance(v, (dict, list)) for v in node.values())}):
                return
            for key in keys[:16]:
                if isinstance(node[key], (dict, list)) or (isinstance(node[key], str) and len(encode(node[key])) > 512):
                    walk(node[key], path + [key], depth + 1)
            omitted += max(0, len(keys) - 16)
        elif isinstance(node, list):
            sample = []
            for entry in node[:3]:
                if len(encode(entry)) > 3000 or len(encode(sample + [entry])) > 6000: break
                sample.append(entry)
            average = max(1, sum(len(encode(v)) for v in node[:8]) // max(1, min(8, len(node))))
            count = max(1, min(16, 10000 // average))
            section = {"path": path, "type": "array", "total": len(node), "shown_offset": 0,
                       "shown_count": len(sample), "shown_values": sample, "complete": len(sample) == len(node),
                       "next_read": read(path, "page", len(sample), count) if len(sample) < len(node) else None}
            if not add(section):
                section.update(shown_count=0, shown_values=[], complete=not node,
                               next_read=read(path, "page", 0, count) if node else None)
                if not add(section): return
            if node and isinstance(node[0], dict): walk(node[0], path + [0], depth + 1)
        elif isinstance(node, str):
            add({"path": path, "type": "string", "characters": len(node), "prefix": node[:512],
                 "complete": len(node) <= 512, "read_text": read(path, "text", 0, 4000)})
    walk(value, [], 0)
    return {"inline": False, "status": value.get("status") if isinstance(value, dict) else "ok",
            "full_feedback_ref": reference, "serialized_bytes": len(encode(value)), "preview_complete": False,
            "sections": sections, "omitted_sections": omitted,
            "protocol_progress": value.get("protocol_progress") if isinstance(value, dict) else None,
            "reason": "Original result is complete at full_feedback_ref; previews are partial exact source-order values. Continue with the listed paged read, not another whole-object fetch."}


def interaction_history(runtime, attempts):
    """Persist exact model-owned outputs and public results, never private state.

    Only a bounded tail is inline. The full chronological index and every raw
    output/result remain reachable through the same public artifact gateway.
    Cached entries keep references stable across a crash or a subsequent prompt.
    """
    entries = []
    with runtime.store.transaction():
        for attempt_id, attempt in attempts:
            if attempt["status"] != "processed":
                continue
            entry = runtime.store.read("interaction_entries", attempt_id)
            if entry is None:
                raw_bytes = runtime.store.bytes(attempt["raw_ref"])
                try:
                    raw, raw_encoding = raw_bytes.decode("utf-8"), "utf-8"
                except UnicodeDecodeError:
                    raw, raw_encoding = base64.b64encode(raw_bytes).decode("ascii"), "base64"
                try:
                    action = strict_json(raw) if raw_encoding == "utf-8" else None
                    if type(action) is dict and set(action) == {"action"}:
                        action = action["action"]
                except ValueError:
                    action = None
                result = runtime.store.get(attempt["response_ref"])
                entry = {"attempt_id": attempt_id, "context_ref": attempt["context_ref"],
                         "raw_output_ref": runtime._publish(raw, "own_model_output"),
                         "raw_output_encoding": raw_encoding,
                         "raw_output_sha256": attempt["raw_ref"],
                         "result_ref": runtime._publish(result, "own_tool_result"),
                         "status": result["status"],
                         "tool": action.get("tool") if type(action) is dict else None,
                         "action": action if action is not None and len(encode(action)) <= 6000 else {"inline": False}}
                presentation = pack(result)
                if len(encode(presentation)) <= 60000:
                    entry["result"] = presentation
                else:
                    entry["result_preview"] = compact_feedback(result, entry["result_ref"], budget=3500)
                runtime.store.record("interaction_entries", attempt_id, entry)
            entries.append(entry)
        full_ref = runtime._publish(entries, "own_interaction_history")
    tail = entries[-8:]
    # The latest result is shown once, in last_tool_feedback. References and
    # full public history retain the exact original result as before.
    if tail and attempts and tail[-1]["attempt_id"] == attempts[-1][0] and "response_ref" in attempts[-1][1]:
        latest = dict(tail[-1]); latest.pop("result", None); latest.pop("result_preview", None)
        latest["result_inline_at"] = "last_tool_feedback"; tail[-1] = latest
    while tail and len(encode(tail)) > 64000: tail = tail[1:]
    return {"count": len(entries), "inline_start_index": len(entries) - len(tail),
            "entries": tail, "full_history_ref": full_ref,
            "same_read_limit": runtime.config["limits"]["same_read_limit"]}


def pending_start_validation(base, pending, now, base_plan_ref):
    """Public literal time checks, source order; never generate a correction."""
    rows = [{"task_id": t["id"], "not_before": t["not_before"], "current_time": now,
             "original_path": ["tasks", i]}
            for i, t in enumerate(base["tasks"])
            if t["id"] in pending and t["not_before"] < now and
            not (now < base["freeze_until"] and t["not_before"] < base["freeze_until"])]
    return {"constraint": "retained_nonfrozen_not_before_gte_current_time",
            "status": "explicit_revision_required" if rows else "no_past_pending_starts",
            "count": len(rows), "rows": rows[:64], "omitted": max(0, len(rows) - 64),
            "base_plan_ref": base_plan_ref, "order": "original_source_order", "corrections": None}


def prompt(runtime, *, task=None):
    if runtime.config.get("capacity_experiment"):
        from .capacity_prompt import runtime_prompt
        return runtime_prompt(runtime, task=task)
    context = runtime.context()
    full = runtime.store.read("contexts", context["context_ref"])
    # Source-order family catalog; no scores, top-k or candidate selection.
    families = {}
    for machine in full["problem"]["machines"]:
        families.setdefault(machine["family"], {"machines": [], "operations": 0})["machines"].append(machine["machine"])
    for op in full["problem"]["operations"]:
        families[op["family"]]["operations"] += 1
    context["families"] = families
    pending = set(context["pending_base_task_ids"])
    context["pending_tasks"] = [t for t in full["base_plan"]["tasks"] if t["id"] in pending]
    context["pending_start_validation"] = pending_start_validation(full["base_plan"], pending, context["time"], context["base_plan_ref"])
    # Inline exact pertinent facts, with explicit omitted counts and full access.
    operation_ids = {oid for t in context["pending_tasks"] for oid in t["operation_ids"]}
    gap_machines = {m["machine"] for m in (context.get("trigger") or {}).get("machines", [])}
    related = [op for op in full["problem"]["operations"] if op["operation_id"] in operation_ids or gap_machines.intersection(op["eligible_machines"])]
    context["pertinent_operations"] = related[:48]
    context["pertinent_operations_total"] = len(related)
    context["pertinent_operations_omitted"] = len(related) - len(context["pertinent_operations"])
    context["base_holds"] = full["base_plan"]["holds"] if len(encode(full["base_plan"]["holds"])) <= 18000 else {"inline": False, "count": context["base_hold_count"], "artifact_ref": context["base_plan_ref"], "path": ["holds"]}
    attempts = runtime.store.rows("attempts")
    history = interaction_history(runtime, attempts)
    feedback = None
    if attempts:
        attempt = attempts[-1][1]
        if "response_ref" in attempt:
            feedback = runtime.store.get(attempt["response_ref"])
            presentation = pack(feedback)
            if len(encode(presentation)) > 60000:
                entry = runtime.store.read("interaction_entries", attempt["attempt_id"])
                feedback = compact_feedback(feedback, entry["result_ref"])
            else:
                feedback = presentation
    for key in ("pending_tasks", "pertinent_operations", "base_holds"):
        context[key] = pack(context[key])
    frame = {"context": context, "interaction_history": history, "last_tool_feedback": feedback, "task": task}
    from .fact_memory import INSTRUCTIONS, prompt_variants
    cap = runtime.config["limits"]["context_chars"]
    base_chars = len(PROTOCOL_TEXT + "\n" + encode(frame).decode())
    for candidate in prompt_variants(runtime, attempts, frame, base_chars):
        rendered = fit_prompt(candidate, PROTOCOL_TEXT + INSTRUCTIONS, cap)
        if rendered is not None:
            return rendered
    rendered = fit_prompt(frame, PROTOCOL_TEXT, cap)
    require(rendered is not None, "context_capacity", "Essential context cannot fit")
    return rendered


def fit_prompt(frame, prefix, cap):
    """Fit a copy using presentation-only fallbacks; return None if impossible."""
    frame = deepcopy(frame)
    context, history = frame["context"], frame["interaction_history"]
    render = lambda: prefix + "\n" + encode(frame).decode()
    rendered = render()
    if len(rendered) > cap:
        # Unrequested partial previews yield to requested facts and commitments.
        context["pertinent_operations"] = []
        context["pertinent_operations_omitted"] = context["pertinent_operations_total"]
        rendered = render()
        if len(rendered) > cap:
            context["pending_tasks"] = {"inline": False, "count": len(context["pending_base_task_ids"]),
                                        "artifact_ref": context["base_plan_ref"], "path": ["tasks"]}
            rendered = render()
        while len(rendered) > cap and history["entries"]:
            history["entries"] = history["entries"][1:]
            history["inline_start_index"] += 1
            rendered = render()
    if len(rendered) > cap:
        context["trigger"] = pack(context["trigger"])
        rendered = render()
    return rendered if len(rendered) <= cap else None



def command(directory, *, binary, model, effort, catalog=None, context_window=None, auto_compact=None):
    settings = ['approval_policy="never"', 'web_search="disabled"', 'project_doc_max_bytes=0',
                'mcp_servers={}', 'history.persistence="none"',
                'tools.update_plan.enabled=false', 'tools.experimental_request_user_input.enabled=false',
                'skills.include_instructions=false', 'skills.bundled.enabled=false',
                'model_provider="harness-openai"',
                'include_environment_context=false', 'include_apps_instructions=false',
                'include_collaboration_mode_instructions=false',
                'model_providers.harness-openai.name="OpenAI via existing Codex login, no retries"',
                'model_providers.harness-openai.base_url="https://chatgpt.com/backend-api/codex"',
                'model_providers.harness-openai.wire_api="responses"',
                'model_providers.harness-openai.requires_openai_auth=true',
                'model_providers.harness-openai.request_max_retries=0',
                'model_providers.harness-openai.stream_max_retries=0',
                'model_providers.harness-openai.supports_websockets=false',
                'shell_environment_policy.inherit="none"', 'model_reasoning_effort=' + json.dumps(effort),
                'model_instructions_file=' + json.dumps(str(directory / "system-instructions.txt")),
                'log_dir=' + json.dumps(str(directory / "logs")), 'sqlite_home=' + json.dumps(str(directory / "state"))]
    settings += ['features.' + name + '=false' for name in DISABLED_FEATURES]
    settings += ['features.skip_host_skill_discovery=true']
    settings += ['features.multi_agent_v2={enabled=false,max_concurrent_threads_per_session=1,wait_agent_enabled=false}']
    if context_window is not None:
        settings.extend(["model_context_window=" + str(context_window), "model_auto_compact_token_limit=" + str(auto_compact)])
    if catalog is not None:
        settings.append('model_catalog_json=' + json.dumps(str(catalog)))
    paths = [p.parent.resolve() for root in (Path.home() / ".codex/skills", Path.home() / ".agents/skills") if root.exists() for p in root.rglob("SKILL.md")]
    settings.append('skills.config=[' + ','.join('{path=' + json.dumps(str(p)) + ',enabled=false}' for p in paths) + ']')
    argv = [binary, "exec", "--json", "--ephemeral", "--ignore-user-config", "--ignore-rules",
            "--skip-git-repo-check", "--sandbox", "read-only", "--color", "never", "--model", model,
            "--cd", str(directory / "isolated-cwd"), "--output-schema", str(directory / "schema.json"),
            "--output-last-message", str(directory / "final.txt")]
    for value in settings:
        argv.extend(["-c", value])
    return argv + ["-"]


def call(runtime, *, task=None):
    from . import capacity_pilot
    if capacity_pilot.is_pilot(getattr(runtime, 'manifest', {}).get('admission')):
        capacity_pilot.check_budget(runtime)
        return _call(runtime, task=task)
    from .offline_isolation import reject_model_calls
    reject_model_calls()
    from .experiment import experiment_lock
    require(runtime.manifest.get("admission") is not None, "P5_admission", "Frozen registration required")
    with experiment_lock(runtime.manifest["admission"]):
        from .recovery import wait_for_cooldown
        wait_for_cooldown(runtime)
        return _call(runtime, task=task)


def _prepare_request(runtime, *, task=None):
    from . import capacity_pilot
    if capacity_pilot.is_pilot(getattr(runtime, 'manifest', {}).get('admission')):
        return capacity_pilot.prepare_request(runtime, task=task)
    from .offline_isolation import reject_model_calls
    reject_model_calls()
    from .experiment import registration_validation_scope
    with registration_validation_scope():
        return _prepare_request_in_scope(runtime, task=task)


def _prepare_request_in_scope(runtime, *, task=None):
    from .offline_isolation import reject_model_calls
    reject_model_calls()
    require(runtime.manifest.get("admission") is not None, "P5_admission", "Real calls require a frozen passing G0-G4 admission and experiment budget")
    from .network import for_admission
    network = for_admission(runtime.manifest["admission"], live=True)
    text = prompt(runtime, task=task)
    previous_contexts = [ref for ref, _ in runtime.store.rows("contexts") if ref != runtime.head["context_ref"]]
    current = runtime.head["context_ref"]
    candidates = [ref for ref, c in runtime.store.rows("candidates") if c["context_ref"] == current]
    open_draft = any(d["context_ref"] == current and not d["sealed"] for _, d in runtime.store.rows("drafts"))
    schema = response_schema(runtime.config["arm"], comparison_context_refs=previous_contexts,
                             candidate_refs=candidates, has_open_draft=open_draft,
                             planning_reviews=bool(runtime.config.get('capacity_experiment')))
    attempt_id = runtime.reserve_attempt(text, schema)
    return network, text, schema, attempt_id


def _call(runtime, *, task=None):
    # The proof scope has ended before any files are staged or RPC is started.
    from .network import apply_environment
    network, text, schema, attempt_id = _prepare_request(runtime, task=task)
    directory = runtime.store.path / "model" / attempt_id.replace(":", "-")
    directory.mkdir(parents=True, exist_ok=False)
    for name in ("isolated-cwd", "logs", "state"):
        (directory / name).mkdir()
    binary = runtime.manifest["admission"]["cli_binary"]
    require(sha_bytes(Path(binary).read_bytes()) == runtime.manifest["admission"]["cli_sha256"], "cli_changed", "Frozen CLI changed")
    cfg = runtime.config["model"]
    catalog_source = Path(runtime.manifest["admission"]["model_catalog"])
    catalog_raw = catalog_source.read_bytes()
    require(sha_bytes(catalog_raw) == runtime.manifest["admission"]["model_catalog_sha256"], "catalog_changed", "Frozen model metadata changed")
    capacity = runtime.config.get("capacity_experiment") or {}
    argv = command(directory, binary=binary, model=cfg["name"], effort=cfg["reasoning_effort"], catalog=directory / "model-catalog.json",
                   context_window=capacity.get("model_context_window"), auto_compact=capacity.get("model_auto_compact_token_limit"))
    schema_raw = encode_model_schema(schema)
    fingerprint = digest({"prompt": text, "schema": schema, "schema_wire_sha256": sha_bytes(schema_raw), "argv": argv, "catalog_sha256": sha_bytes(catalog_raw), **({"transport_binding": network} if network else {})})
    if network:
        with (directory / "network.json").open("xb") as stream:
            stream.write(encode(network)); stream.flush(); os.fsync(stream.fileno())
    for name, raw in {"prompt.txt": text.encode(), "schema.json": schema_raw,
                      "model-catalog.json": catalog_raw,
                      "system-instructions.txt": BASE_INSTRUCTIONS.encode(),
                      "command.json": encode({"argv": argv, "cwd": str(directory / "isolated-cwd"), "stdin": "prompt.txt"}),
                      "request.json": encode({"call_id": attempt_id, "request_fingerprint": fingerprint}),
                      "attempt.claim": (fingerprint + "\n").encode()}.items():
        with (directory / name).open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    environment = os.environ.copy()
    environment["RUST_LOG"] = "warn,reqwest::connect=debug,hyper_util::client::legacy::connect::http=debug"
    for key in list(environment):
        if key.startswith("CODEX_") and key != "CODEX_HOME":
            environment.pop(key)
    environment = apply_environment(environment, network)
    runtime.mark_started(attempt_id)
    started = time.monotonic()
    from ..model_process_guard import INPUT_FILES, OUTPUT_FILES
    io_spec = {"cwd": str(directory / "isolated-cwd"), "stdin": str(directory / "prompt.txt"),
               "stdout": str(directory / "events.jsonl"), "stderr": str(directory / "stderr.log"),
               "inputs": {name: str(directory / name) for name in (*INPUT_FILES, "model-catalog.json", *(("network.json",) if network else ()))},
               "outputs": {name: str(directory / name) for name in OUTPUT_FILES}}
    try:
        guarded = run_guarded(argv, run_dir=directory, timeout_seconds=cfg["timeout_seconds"], env=environment,
                              call_id=attempt_id, request_fingerprint=fingerprint, io_spec=io_spec)
    except BaseException:
        # Ownership loss or guard interruption is not proof of no execution.
        # Durable started state remains; recovery freezes new calls.
        raise
    events_raw = (directory / "events.jsonl").read_bytes()
    events = []
    malformed = False
    for line in events_raw.splitlines():
        try:
            if line.strip():
                events.append(strict_json(line))
        except ValueError:
            malformed = True
    summary = summarize_events(events)
    usage = summary["usage"] if all(type(summary["usage"].get(k)) is int for k in ("input_tokens", "output_tokens")) else None
    if usage is not None:
        usage = {k: usage[k] for k in ("input_tokens", "cached_input_tokens", "output_tokens")}
    final = (directory / "final.txt").read_bytes() if (directory / "final.txt").exists() else b""
    transport = {"events_ref": runtime.store.put_bytes(events_raw), "stderr_ref": runtime.store.put_bytes((directory / "stderr.log").read_bytes()),
                 "guard_ref": runtime.store.put(guarded), "command_ref": runtime.store.put(argv), "returncode": guarded["command_returncode"],
                 "original_guard_files": {name: runtime.store.put_bytes((directory / "process_guard" / name).read_bytes()) for name in guarded["files_sha256"]},
                 "original_input_files": {name: runtime.store.put_bytes(Path(path).read_bytes()) for name, path in io_spec["inputs"].items()},
                 "timed_out": guarded["timed_out"], "native_tool_events": summary["native_tool_events"], "automatic_retries": 0,
                 "channel_valid": bool(usage is not None and not malformed and not summary["native_tool_events"] and guarded["command_returncode"] == 0 and summary["completed_turns"] == 1)}
    runtime.save_response(attempt_id, final, usage=usage, duration_seconds=guarded["parent_wait_wall_seconds"], transport=transport)
    if usage is None or malformed or summary["native_tool_events"] or guarded["command_returncode"] != 0 or summary["completed_turns"] != 1:
        from .recovery import schedule_recovery
        recovery = schedule_recovery(runtime, attempt_id)
        if recovery is not None:
            return {"status": "transport_cooldown", "attempt_id": attempt_id, "recovery": recovery}
        runtime.stop("model_transport_or_unknown_usage")
        return {"status": "stopped", "attempt_id": attempt_id, "transport": transport}
    return runtime.process(attempt_id)
