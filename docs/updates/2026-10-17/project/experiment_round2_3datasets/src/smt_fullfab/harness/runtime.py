"""Public run state machine and controlled business gateway.

Only this trusted process owns Store and FullFabEnvironment. Model output is
data. It never receives an environment, SQLite connection or filesystem path.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import time
import uuid

from ..plan_delta import SCHEMA as DELTA_SCHEMA, STATE_SCHEMA, anchor_hashes, compile_plan_delta, DeltaError
from ..B_delta_assembly import DeltaAssembly, SCHEMA as ASSEMBLY_SCHEMA
from ..environment import FullFabEnvironment
from .contracts import (PROTOCOL, ROOT, SEMANTIC_COVERAGE, HarnessError, digest, encode, encode_model_schema,
                        fingerprint, number, require, strict_json, validate_action, validate_config, within_cap)
from .facts import FactReader, build_facts, changes, reconstruct
from .factory import capture, prepare, restore
from .store import Store


def identity(prefix):
    return prefix + ":" + uuid.uuid4().hex[:24]


def leaves(value, path=()):
    if type(value) is dict and value:
        for key, val in value.items():
            yield from leaves(val, (*path, key))
    elif type(value) is list and value:
        for i, val in enumerate(value):
            yield from leaves(val, (*path, i))
    else:
        yield list(path), deepcopy(value)


def field_sources(base, delta, compiled):
    """Exact paths, plus declared order/disposition. No choice is inferred."""
    result = []
    for key in delta["plan_header"]:
        for tail, value in leaves(compiled[key]):
            result.append({"plan_path": [key, *tail], "source": "delta", "source_path": ["plan_header", key, *tail], "value_sha256": digest(value)})
    for i, task in enumerate(compiled["tasks"]):
        matches = [(kind, j) for kind in ("replace", "add") for j, row in enumerate(delta["tasks"][kind]) if row["id"] == task["id"]]
        if matches:
            kind, j = matches[0]
            source, path = "delta", ["tasks", kind, j]
        else:
            j = next(j for j, row in enumerate(base["tasks"]) if row["id"] == task["id"])
            source, path = "base", ["tasks", j]
        for tail, value in leaves(task):
            result.append({"plan_path": ["tasks", i, *tail], "source": source,
                           "source_path": [*path, *tail], "value_sha256": digest(value)})
    kept = delta["holds"]["keep"]
    retained = set(kept["ids"]) if kept["mode"] == "ids" else {"h:" + str(i) for i in range(len(base["holds"]))} - set(kept["ids"])
    origins = []
    for i, hold in enumerate(base["holds"]):
        ref = "h:" + str(i)
        if ref in retained:
            origins.append(("base", ["holds", i]))
        else:
            for j, item in enumerate(delta["holds"]["replace"]):
                if item["ref"] == ref:
                    origins.append(("delta", ["holds", "replace", j, "hold"]))
    origins.extend(("delta", ["holds", "add", i]) for i in range(len(delta["holds"]["add"])))
    for i, (source, path) in enumerate(origins):
        for tail, value in leaves(compiled["holds"][i]):
            result.append({"plan_path": ["holds", i, *tail], "source": source,
                           "source_path": [*path, *tail], "value_sha256": digest(value)})
    return result


class Runtime:
    @classmethod
    def start_new(cls, directory, config, *, experiment_id, mode="replay", fault=None, initial=None, admission=None):
        config = validate_config(config)
        require(mode in ("replay", "model", "policy"), "mode", "Explicit execution mode required")
        if initial is None:
            env = FullFabEnvironment(seed=config["seed"], window_seconds=config["window_seconds"])
            start = env.t
        else:
            env = restore(initial["state"], initial["trace"])
            start = env.t
            require(env.horizon - start == config["window_seconds"], "branch_window", "Branch duration must match registered horizon")
        require(len(env.physical) == 913, "scope", "Full 913-machine responsibility required")
        run_id = identity("run")
        now = time.time()
        fp = fingerprint()
        if mode == "model":
            from .experiment import validate_admission
            validate_admission(admission, fp, config, initial)
        store = Store(directory, create=True, fault=fault)
        manifest = {"schema": "harness-run-manifest-v1", "run_id": run_id, "experiment_id": experiment_id,
                    "created_epoch": now, "deadline_epoch": now + config["limits"]["wall_seconds"],
                    "config": config, "mode": mode, "fingerprint": fp, "admission": admission,
                    "initial_state_sha256": digest(capture(env)), "initial_trace_sha256": digest(env.trace),
                    "start_time": start, "end_time": env.horizon, "period_anchor": start,
                    "parent": None if initial is None else initial["parent"],
                    "prefix_events": 0 if initial is None else len(env.trace),
                    "token_hard_cap": False,
                    "token_policy": "Conservative pre-call reservation; CLI has no verified exact token cap. Reported usage may exceed one reservation; then stop.",
                    "monetary_cost": None}
        with store.transaction():
            store.record("manifest", "run", manifest)
            state_ref = store.put(capture(env))
            store.set_meta("head", {"revision": 0, "state_ref": state_ref, "phase": "INIT", "context_ref": None,
                                    "time": env.t, "segment": 1, "stop_reason": None,
                                    "zero_progress": 0, "previous_zero_signature": None,
                                    "same_error_count": 0, "previous_error_signature": None,
                                    "same_read_count": 0, "previous_read_signature": None, "first_read_result_ref": None})
            store.physical(env.trace)
            store.event("run_started", {"manifest_ref": store.ref("manifest", "run"), "fence": store.token})
        path = store.path / "manifest.json"
        with path.open("xb") as stream:
            stream.write(encode(manifest) + b"\n")
            stream.flush()
            import os
            os.fsync(stream.fileno())
        runtime = cls(store, manifest, env)
        try:
            if mode == "model":
                from .experiment import register_run
                register_run(runtime)
            runtime.observe()
        except BaseException:
            runtime.close()
            raise
        return runtime

    @classmethod
    def resume_run(cls, directory, *, expected_manifest=None, fault=None):
        store = Store(directory, fault=fault)
        try:
            manifest = store.read("manifest", "run")
            require(digest(strict_json((store.path / "manifest.json").read_bytes())) == digest(manifest), "manifest_changed", "Manifest projection differs")
            if expected_manifest is not None:
                require(digest(manifest) == expected_manifest, "manifest_changed", "Requested manifest differs")
            from .amendment import validate_runtime_source
            validate_runtime_source(manifest, fingerprint())
            proof = store.verify()
            head = store.meta("head")
            require(head["phase"] != "CLOSED", "closed_run", "Sealed runs cannot resume")
            env = restore(store.get(head["state_ref"]), store.trace())
            runtime = cls(store, manifest, env)
            with store.transaction():
                head["segment"] += 1
                store.set_meta("head", head)
                store.event("resumed", {"proof": proof, "segment": head["segment"], "state_ref": head["state_ref"],
                                        "budget": runtime.usage(), "no_model_request_sent": True})
            # A durable response can be parsed/processed again; sent-without-result
            # stays UNKNOWN. No new call is issued by resume itself.
            runtime.reconcile()
            store.export_trace()
            return runtime
        except BaseException:
            store.close()
            raise

    @classmethod
    def fork_scenario(cls, parent_directory, directory, config, *, experiment_id, mode="replay"):
        # A fork is a NEW account and model history, with an exact common private
        # state and complete prehistory. Never use this to reset a resumed run.
        parent = Store(parent_directory)
        try:
            parent.verify()
            manifest = parent.read("manifest", "run")
            require(manifest["fingerprint"] == fingerprint(), "fingerprint_changed", "Parent physical/protocol version differs")
            state = parent.get(parent.meta("head")["state_ref"])
            initial = {"state": state, "trace": parent.trace(),
                       "parent": {"run_id": manifest["run_id"], "manifest_sha256": digest(manifest),
                                  "state_sha256": digest(state), "trace_sha256": digest(parent.trace()),
                                  "memory_inheritance": "none", "pending_plan_policy": "explicit_disposition_by_new_arm"}}
            return cls.start_new(directory, config, experiment_id=experiment_id, mode=mode, initial=initial)
        finally:
            parent.close()

    def __init__(self, store, manifest, env):
        self.store, self.manifest, self.env = store, manifest, env
        self.config = manifest["config"]
        self.reader = None

    @property
    def head(self):
        return self.store.meta("head")

    def close(self):
        self.store.close()

    def _publish(self, value, kind):
        ref = identity("artifact")
        self.store.record("public", ref, {"kind": kind, "object_ref": self.store.put(value), "run_id": self.manifest["run_id"]})
        return ref

    def observe(self):
        head = self.head
        require(head["time"] < self.manifest["end_time"], "window_complete", "No new observation after terminal")
        if head["context_ref"] is not None:
            return self.context()
        problem = self.env.problem(plan_seconds=self.config["plan_seconds"], lookahead_depth=self.config["lookahead_depth"])
        base = deepcopy(self.env.plan) if self.env.plan is not None else {
            "version": "uncommitted:" + self.manifest["run_id"], "created_at": self.env.t,
            "valid_until": self.env.horizon, "freeze_until": self.env.t,
            "reason": "No previously accepted production decisions", "scope": list(problem["scope"]), "tasks": [], "holds": []}
        state = {"schema": STATE_SCHEMA, "time": self.env.t, "observation_end": self.env.horizon,
                 "base_plan_version": base["version"], "dispatched_task_ids": [t["id"] for t in base["tasks"] if (base["version"], t["id"]) in self.env.executed_tasks]}
        context_ref = identity("context")
        facts = build_facts(problem, base)
        reconstruct(facts)
        previous = self.store.meta("last_context")
        with self.store.transaction(revision=head["revision"]):
            context = {"context_ref": context_ref, "run_id": self.manifest["run_id"], "episode_id": identity("episode"),
                       "state_revision": head["revision"], "time": self.env.t, "problem": problem,
                       "base_plan": base, "execution_state": state, "source_sha256": self.manifest["fingerprint"]["sha256"],
                       "facts": facts, "trigger": deepcopy(self.env.last_stop), "previous_context_ref": previous,
                       "problem_ref": self._publish(problem, "problem"), "base_plan_ref": self._publish(base, "base_plan"),
                       "facts_ref": self._publish(facts, "facts")}
            self.store.record("contexts", context_ref, context)
            head.update(context_ref=context_ref, phase="OBSERVED")
            self.store.set_meta("head", head)
            self.store.set_meta("last_context", context_ref)
            self.store.event("observed", {"context_ref": context_ref, "revision": head["revision"], "problem_sha256": digest(problem), "base_sha256": digest(base)})
        self.reader = FactReader(context_ref, facts)
        return self.context()

    def context(self, ref=None):
        ref = ref or self.head["context_ref"]
        context = self.store.read("contexts", ref)
        require(context is not None, "unknown_context", str(ref))
        facts = context["facts"]
        reader = FactReader(ref, facts)
        pending = set(t["id"] for t in context["base_plan"]["tasks"]) - set(context["execution_state"]["dispatched_task_ids"])
        return {"protocol_version": PROTOCOL, "context_ref": ref, "state_revision": context["state_revision"],
                "time": context["time"], "window_end": self.manifest["end_time"],
                "scope": context["problem"]["scope"], "base_plan_ref": context["base_plan_ref"],
                "base_header": {k: v for k, v in context["base_plan"].items() if k not in ("tasks", "holds")},
                "base_task_count": len(context["base_plan"]["tasks"]), "pending_base_task_ids": [t["id"] for t in context["base_plan"]["tasks"] if t["id"] in pending],
                "dispatched_task_ids": context["execution_state"]["dispatched_task_ids"],
                "base_hold_count": len(context["base_plan"]["holds"]),
                "problem_ref": context["problem_ref"], "facts_ref": context["facts_ref"],
                "catalogs": {kind: {"count": len(keys), "first_cursor": reader.cursor(kind, 0)} for kind, keys in facts["catalogs"].items()},
                "trigger": context["trigger"], "notes": self.store.read("notes", "current", {"version": 0, "text": ""}),
                "candidates": [{"candidate_ref": k, "summary": c["summary"]} for k, c in self.store.rows("candidates") if c["context_ref"] == ref],
                "drafts": [{"proposal_ref": k, "version": d["version"], "proposal_id": d["proposal_id"]} for k, d in self.store.rows("drafts") if d["context_ref"] == ref],
                "resource_usage": self.usage(), "semantic_coverage": SEMANTIC_COVERAGE}

    def usage(self):
        attempts = [a for _, a in self.store.rows("attempts")]
        actual = [a for a in attempts if a["channel"] == "codex" and a["status"] not in ("reserved", "not_sent")]
        known = [a for a in actual if a.get("usage") is not None]
        return {"actual_model_attempts": len(actual), "offline_outputs": sum(a["channel"] == "replay" for a in attempts),
                "input_tokens": sum(a["usage"]["input_tokens"] for a in known),
                "cached_input_tokens": sum(a["usage"].get("cached_input_tokens", 0) for a in known),
                "output_tokens": sum(a["usage"]["output_tokens"] for a in known),
                "unknown_usage": sum(a.get("usage") is None for a in actual),
                "reserved_tokens": sum(a["reserved_tokens"] for a in attempts if a["status"] in ("reserved", "started", "unknown")),
                "model_seconds": sum(a.get("duration_seconds", 0) for a in actual),
                "pending_attempts": sum(a["status"] in ("reserved", "started", "unknown") for a in attempts),
                "elapsed_wall_seconds": time.time() - self.manifest["created_epoch"], "cost_usd": None}

    def wall_budget(self):
        from .wall_budget import effective_budget
        return effective_budget(self.manifest, dict(self.store.rows('control_source_revisions')))

    def check_admission(self, *, actual=False, reserve=0):
        budget = self.wall_budget()
        head, limits = self.head, budget['limits']
        require(head["phase"] not in ("STOPPED", "CLOSED", "AUDITING"), "stopped", str(head["stop_reason"]))
        require(not (self.store.path / "stop_requested.json").exists(), "user_stop", "Stop requested")
        require(time.time() + limits["cleanup_seconds"] < budget['effective_deadline_epoch'], "wall_budget", "Cleanup margin reached")
        size = sum(p.stat().st_size for p in self.store.path.rglob("*") if p.is_file())
        require(size < limits["storage_bytes"] * .95, "storage_budget", "Evidence storage reserve reached")
        if actual:
            from .amendment import validate_runtime_source
            validate_runtime_source(self.manifest, fingerprint())
            usage = self.usage()
            require(self.manifest["mode"] == "model", "model_not_authorized", "Run was registered offline")
            from .recovery import current_recoveries
            recoveries = current_recoveries(self)
            require(usage["unknown_usage"] == len(recoveries) and usage["pending_attempts"] == 0, "unknown_attempt", "Reconcile all in-flight results before a new request")
            require(all(time.time() >= r["not_before_epoch"] for r in recoveries.values()), "recovery_cooldown", "Cooldown has not expired")
            require(within_cap(usage["actual_model_attempts"] + 1, limits["attempts"]), "attempt_budget", "Attempt cap reached")
            require(within_cap(usage["input_tokens"] + usage["output_tokens"] + usage["reserved_tokens"] + reserve, limits["tokens"]), "token_budget", "Conservative reservation does not fit")
            timeout = self.config["model"]["timeout_seconds"]
            require(usage["model_seconds"] + timeout <= limits["model_seconds"] and time.time() + timeout + limits["cleanup_seconds"] < budget['effective_deadline_epoch'], "time_budget", "Call plus cleanup cannot fit")
            from .experiment import check_experiment_budget
            check_experiment_budget(self, reserve, budget=budget)

    def reserve_attempt(self, prompt, schema, *, channel="codex"):
        actual = channel == "codex"
        reserve = max(self.config["limits"]["token_reserve_per_call"], len(prompt.encode()) + 16384) if actual else 0
        self.check_admission(actual=actual, reserve=reserve)
        require(len(prompt) <= self.config["limits"]["context_chars"], "context_capacity", "Prompt exceeds declared capacity")
        attempt_id = identity("attempt")
        with self.store.transaction():
            attempt = {"attempt_id": attempt_id, "index": len(self.store.rows("attempts")), "channel": channel,
                       "context_ref": self.head["context_ref"], "status": "reserved", "reserved_tokens": reserve,
                       "prompt_ref": self.store.put_bytes(prompt.encode()), "schema_ref": self.store.put_bytes(encode_model_schema(schema)),
                       "reserved_epoch": time.time(), "usage": None, "duration_seconds": 0}
            self.store.record("attempts", attempt_id, attempt)
            self.store.event("attempt_reserved", attempt)
        return attempt_id

    def mark_started(self, attempt_id):
        with self.store.transaction():
            attempt = self.store.read("attempts", attempt_id)
            require(attempt["status"] == "reserved", "attempt_state", "Cannot send twice")
            attempt.update(status="started", started_epoch=time.time())
            self.store.record("attempts", attempt_id, attempt, replace=True)
            self.store.event("attempt_started", attempt)

    def save_response(self, attempt_id, raw, *, usage, duration_seconds, transport=None):
        require(type(raw) is bytes and number(duration_seconds) and duration_seconds >= 0, "response", "Exact raw response and nonnegative elapsed time required")
        if usage is not None:
            require(type(usage) is dict and all(type(usage.get(k)) is int and usage[k] >= 0 for k in ("input_tokens", "output_tokens")), "usage", "Unknown usage is null, never zero-filled")
            require(type(usage.get("cached_input_tokens", 0)) is int and 0 <= usage.get("cached_input_tokens", 0) <= usage["input_tokens"], "usage", "Cache is a subset of input")
        with self.store.transaction():
            attempt = self.store.read("attempts", attempt_id)
            require(attempt["status"] in ("started", "unknown"), "attempt_state", "Response already settled or never sent")
            attempt.update(status="responded", raw_ref=self.store.put_bytes(raw), usage=usage,
                           duration_seconds=duration_seconds, transport=transport, finished_epoch=time.time())
            self.store.record("attempts", attempt_id, attempt, replace=True)
            self.store.event("response_saved", attempt)
        self.store.fault("after_response_saved")

    def record_output(self, action, *, channel="replay"):
        require(channel in ("replay", "policy"), "offline_channel", "Actual models must use the transport")
        require(self.manifest["mode"] != "model", "model_provenance", "Cannot inject offline output into a real model run")
        raw = encode(action) if not isinstance(action, bytes) else action
        attempt = self.reserve_attempt("Deterministic offline input; no model invocation", {}, channel=channel)
        self.mark_started(attempt)
        self.save_response(attempt, raw, usage={"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0}, duration_seconds=0,
                           transport={"kind": channel, "actual_model_call": False})
        return self.process(attempt)

    def _bound_context(self, action):
        ref = action["context_ref"]
        context = self.store.read("contexts", ref)
        require(context is not None, "unknown_context", ref)
        require(self.head["context_ref"] == ref and context["state_revision"] == self.head["revision"], "stale_context", "Context cannot be silently rebased")
        return context

    def _compile(self, action, attempt, context, *, delta=None, draft=None):
        delta = deepcopy(action["delta"] if delta is None else delta)
        require(type(delta) is dict, "delta_schema", "Complete delta object required")
        anchors = anchor_hashes(context["base_plan"], context["problem"], context["execution_state"], source_sha256=context["source_sha256"])
        if "schema" not in delta:
            delta["schema"] = DELTA_SCHEMA
        if "anchors" not in delta:
            delta["anchors"] = anchors
        compiled = compile_plan_delta(context["base_plan"], context["problem"], context["execution_state"], delta, source_sha256=context["source_sha256"])
        # Private preparation validates physical input without publishing events.
        try:
            prepare(self.env, compiled["plan"])
        except ValueError as exc:
            raise HarnessError("physical_precheck", str(exc)) from exc
        ref = identity("candidate")
        plan = compiled["plan"]
        summary = {"task_count": len(plan["tasks"]), "hold_count": len(plan["holds"]),
                   "valid_until": plan["valid_until"], "freeze_until": plan["freeze_until"],
                   "added": compiled["evidence"]["added_task_ids"], "replaced": compiled["evidence"]["replaced_task_ids"],
                   "cancelled": compiled["evidence"]["cancelled_task_ids"], "plan_sha256": digest(plan),
                   "check": "static_compiler_and_current_physical_commit_preparation",
                   "dynamic_feasibility": "not_certified", "semantic_coverage": "partial"}
        candidate = {"candidate_ref": ref, "context_ref": context["context_ref"], "revision": context["state_revision"],
                     "attempt_id": attempt["attempt_id"], "attempt_index": attempt["index"], "raw_ref": attempt["raw_ref"],
                     "decision_owner": "model" if self.config["arm"] in ("B", "C") else "frozen_policy",
                     "transformation_kind": "explicit_delta_compilation", "delta": delta, "draft": draft,
                     "compiled": compiled, "field_sources": field_sources(context["base_plan"], delta, plan), "summary": summary,
                     "plan_ref": self._publish(plan, "candidate_plan")}
        self.store.record("candidates", ref, candidate)
        self.store.event("candidate_checked", {"candidate_ref": ref, "candidate_sha256": digest(candidate), "attempt_id": attempt["attempt_id"]})
        return {"status": "candidate_checked", "candidate_ref": ref, "plan_ref": candidate["plan_ref"], "summary": summary,
                "protocol_stage": "proposal_complete_awaiting_explicit_selection",
                "draft_required": False,
                "selection_rule": "If this is your intended plan, a later model output must explicitly apply_candidate with its exact reference. No further drafting/finalization is required; all alternative candidates remain selectable."}

    def _draft(self, ref):
        draft = self.store.read("drafts", ref)
        require(draft is not None, "unknown_proposal", ref)
        assembly = DeltaAssembly(draft["proposal_id"], draft["anchors"])
        for chunk in draft["chunks"]:
            response = assembly.submit(chunk["assembly_action"])
            require(response["status"] == "chunk_accepted", "draft_corrupt", ref)
        return draft, assembly

    def _execute(self, action, attempt):
        tool = validate_action(action, self.config["arm"])
        if attempt["channel"] == "codex" and tool in ("begin_proposal", "write_notes"):
            require(not any(c["context_ref"] == self.head["context_ref"] for _, c in self.store.rows("candidates")),
                    "candidate_stage", "Checked candidates exist: explicitly select, inspect or propose an alternative. Selection may include a memory note.")
        if tool == "read_artifact":
            public = self.store.read("public", action["artifact_ref"])
            require(public is not None and public["run_id"] == self.manifest["run_id"], "private_or_cross_run", "Only registered public artifacts may be read")
            value = self.store.get(public["object_ref"])
            require(type(action["path"]) is list and all(type(x) in (str, int) for x in action["path"]), "artifact_path", "Exact JSON path required")
            try:
                for key in action["path"]:
                    value = value[key]
            except (KeyError, IndexError, TypeError):
                raise HarnessError("artifact_path", "No such exact path") from None
            fmt, offset, count = action["format"], action["offset"], action["count"]
            require(fmt in ("value", "page", "text") and type(offset) is int and type(count) is int and offset >= 0 and count >= 0, "artifact_slice", "Explicit nonnegative slice required")
            if fmt == "value":
                require(offset == 0 and count == 0, "artifact_slice", "Value uses zero offset/count")
                return {"status": "ok", "value": value, "object_ref": public["object_ref"]}
            value = encode(value).decode() if fmt == "text" else value
            require(isinstance(value, (list, str)) and offset <= len(value) and count > 0, "artifact_slice", "Page requires array, text requires serialized value")
            return {"status": "ok", "value": value[offset:offset + count], "total": len(value), "offset": offset,
                    "next_offset": offset + count if offset + count < len(value) else None, "object_ref": public["object_ref"]}
        if tool == "get_context":
            if attempt["channel"] == "codex":
                require(action.get("since_context_ref") is not None and action["since_context_ref"] != action["context_ref"],
                        "redundant_context_read", "Current context is already in the prompt; only a change-set query against an earlier context is a model action")
            result = self.context(action["context_ref"])
            if action.get("since_context_ref") is not None:
                before = self.store.read("contexts", action["since_context_ref"])
                current = self.store.read("contexts", action["context_ref"])
                require(before is not None and before["state_revision"] <= current["state_revision"], "change_gap", "Unknown or future context")
                delta = changes(before["facts"], current["facts"])
                result["changes_ref"] = self._publish(delta, "changes")
                result["change_pages"] = delta["page_count"]
            return {"status": "ok", "context": result}
        context = self._bound_context(action)
        require(attempt["context_ref"] == context["context_ref"], "attempt_context", "Output is bound to another prompt context")
        if tool == "read_entities":
            require(type(action["queries"]) is list and 1 <= len(action["queries"]) <= 32, "queries", "1..32 queries required")
            if self.reader is None or self.reader.context_ref != context["context_ref"]:
                self.reader = FactReader(context["context_ref"], context["facts"])
            results = []
            for query in action["queries"]:
                try:
                    results.append(self.reader.read(query))
                except HarnessError as exc:
                    results.append(exc.response())
            return {"status": "ok", "context_ref": context["context_ref"], "results": results}
        if tool == "write_notes":
            old = self.store.read("notes", "current", {"version": 0, "text": ""})
            require(type(action["text"]) is str and len(action["text"]) <= 8000, "notes_size", "Notes are limited to 8000 characters")
            require(type(action["expected_version"]) is int and action["expected_version"] == old["version"], "notes_version", "Stale notes")
            notes = {"version": old["version"] + 1, "text": action["text"], "authority": "model_notes_only"}
            self.store.record("notes", "current", notes, replace=True)
            return {"status": "ok", "notes": notes}
        if tool == "propose_delta":
            return self._compile(action, attempt, context)
        if tool in ("begin_proposal", "begin_alternative_proposal"):
            if tool == "begin_alternative_proposal":
                reviewed = self.store.read("candidates", action["reviewed_candidate_ref"])
                require(reviewed is not None and reviewed["context_ref"] == context["context_ref"],
                        "alternative_candidate", "Explicitly identify a current candidate you reviewed")
                require(type(action["reason"]) is str and 0 < len(action["reason"]) <= 8000,
                        "alternative_reason", "State your reason for another large proposal")
            require(not any(d["proposal_id"] == action["proposal_id"] for _, d in self.store.rows("drafts")), "proposal_identity", "Proposal ID already exists")
            anchors = anchor_hashes(context["base_plan"], context["problem"], context["execution_state"], source_sha256=context["source_sha256"])
            ref = identity("proposal")
            draft = {"proposal_id": action["proposal_id"], "context_ref": context["context_ref"], "anchors": anchors, "version": 0, "chunks": [], "sealed": False}
            if tool == "begin_alternative_proposal":
                draft["alternative_intent"] = {k: action[k] for k in ("reviewed_candidate_ref", "reason")}
            self.store.record("drafts", ref, draft)
            return {"status": "proposal_opened", "proposal_ref": ref, "version": 0, "technical_schema": DELTA_SCHEMA, "technical_anchors": anchors,
                    "chunk_protocol": "append_proposal uses expected_version and unique chunk_id. set_fields paths: [schema], [anchors], [plan_header], [order_policy], [tasks,keep,mode], [holds,keep,mode]. append_arrays paths: [tasks,keep,ids], [tasks,cancel_ids], [tasks,replace], [tasks,add], their holds counterparts, [machine_orders]. Declare empty arrays. finalize_proposal checks the complete draft; then a later apply_candidate explicitly selects."}
        if tool in ("append_proposal", "finalize_proposal"):
            draft, assembly = self._draft(action["proposal_ref"])
            require(draft["context_ref"] == context["context_ref"], "stale_proposal", "Draft cannot cross context")
            if tool == "append_proposal":
                comparable = {k: action[k] for k in ("chunk_id", "set_fields", "append_arrays")}
                old = next((c for c in draft["chunks"] if c["business_chunk"]["chunk_id"] == action["chunk_id"]), None)
                if old:
                    require(old["business_chunk"] == comparable, "chunk_conflict", "Same chunk ID has different content")
                    return old["response"]
            require(not draft["sealed"] and type(action["expected_version"]) is int and action["expected_version"] == draft["version"], "proposal_version", "Sealed or stale draft")
            envelope = {"schema": ASSEMBLY_SCHEMA, "draft_id": draft["proposal_id"], "anchors": draft["anchors"], "previous_state_sha256": assembly.state_sha256}
            if tool == "append_proposal":
                envelope.update(action="chunk", sequence=draft["version"], chunk_id=action["chunk_id"],
                                set_fields=action["set_fields"], append_arrays=action["append_arrays"])
                response = assembly.submit(envelope)
                require(response["status"] == "chunk_accepted", "chunk_rejected", str(response))
                response = {"status": "chunk_accepted", "proposal_ref": action["proposal_ref"], "version": draft["version"] + 1}
                draft["chunks"].append({"business_chunk": comparable, "assembly_action": envelope, "attempt_id": attempt["attempt_id"], "raw_ref": attempt["raw_ref"], "response": response})
                draft["version"] += 1
                self.store.record("drafts", action["proposal_ref"], draft, replace=True)
                return response
            envelope["action"] = "seal"
            response = assembly.submit(envelope)
            require(response["status"] == "sealed_delta", "proposal_incomplete", str(response))
            result = self._compile(action, attempt, context, delta=response["delta"], draft=deepcopy(draft))
            draft["sealed"] = True
            self.store.record("drafts", action["proposal_ref"], draft, replace=True)
            return result
        if tool in ("construct_candidate", "optimize_candidate"):
            from .adapters import classical_candidate
            return classical_candidate(self, action, attempt, context)
        require(tool == "apply_candidate", "action_schema", "Unsupported action")
        candidate = self.store.read("candidates", action["candidate_ref"])
        require(candidate is not None, "unknown_candidate", "Exact checked candidate required")
        require(candidate["context_ref"] == context["context_ref"] and candidate["revision"] == self.head["revision"], "stale_candidate", "Candidate state changed")
        require(candidate["attempt_index"] < attempt["index"] and candidate["attempt_id"] != attempt["attempt_id"], "apply_order", "Selection must be a later independent output")
        plan = candidate["compiled"]["plan"]
        prepared = prepare(self.env, plan)
        commit_id = identity("commit")
        state_ref = self.store.put(capture(prepared))
        head = self.head
        receipt = {"status": "accepted", "commit_id": commit_id, "candidate_ref": action["candidate_ref"],
                   "selection_attempt_id": attempt["attempt_id"], "selection_raw_ref": attempt["raw_ref"],
                   "request_id": action["request_id"], "expected_revision": head["revision"], "actual_revision": head["revision"] + 1,
                   "plan_sha256": digest(plan), "state_ref": state_ref, "time": prepared.t,
                   "trace_start": len(self.env.trace), "trace_end": len(prepared.trace)}
        if "selection_note" in action:
            # Optional notes cannot invalidate a valid production selection.
            note = action["selection_note"]
            if type(note) is str and len(note) <= 8000:
                old = self.store.read("notes", "current", {"version": 0})
                self.store.record("notes", "current", {"version": old["version"] + 1, "text": note,
                                  "authority": "model_notes_only", "attempt_id": attempt["attempt_id"]}, replace=True)
                receipt["selection_note_status"] = "saved"
            else:
                receipt["selection_note_status"] = "rejected_invalid_note_commit_unaffected"
        self.store.fault("before_commit_acceptance")
        self.store.physical(prepared.trace[len(self.env.trace):])
        self.store.record("commits", commit_id, receipt)
        self.store.event("commit_accepted", receipt)
        head.update(revision=head["revision"] + 1, state_ref=state_ref, phase="COMMITTED", context_ref=None)
        self.store.set_meta("head", head)
        return receipt

    def process(self, attempt_id):
        attempt = self.store.read("attempts", attempt_id)
        require(attempt is not None, "unknown_attempt", attempt_id)
        if attempt["status"] == "processed":
            return self.store.get(attempt["response_ref"])
        require(attempt["status"] == "responded", "attempt_state", "No durable model response")
        raw = self.store.bytes(attempt["raw_ref"])
        if attempt["channel"] == "codex":
            transport = attempt.get("transport") or {}
            require(attempt.get("usage") is not None and transport.get("returncode") == 0
                    and transport.get("channel_valid") is True, "unverified_response", "Unverified transport response cannot make production decisions")
            from .amendment import validate_runtime_source
            validate_runtime_source(self.manifest, fingerprint())
        # Algorithm execution owns a separately committed resource attempt so a
        # business rejection or process death cannot erase its consumption.
        parsed = None
        try:
            parsed = strict_json(raw)
            if type(parsed) is dict and set(parsed) == {"action"}:
                parsed = parsed["action"]
            validate_action(parsed, self.config["arm"])
            if parsed["tool"] in ("construct_candidate", "optimize_candidate") and not self.store.ref("requests", parsed["request_id"]):
                from .adapters import execute_classical
                execute_classical(self, parsed, attempt)
        except (HarnessError, ValueError, KeyError, TypeError):
            pass  # The regular action path retains its structured rejection.
        before = self.head
        with self.store.transaction(revision=before["revision"]):
            action = None
            self.store.db.execute("SAVEPOINT business_action")
            try:
                action = strict_json(raw)
                if type(action) is dict and set(action) == {"action"}:
                    action = action["action"]
                validate_action(action, self.config["arm"])
                request_id = action.get("request_id")
                previous = self.store.read("requests", request_id) if request_id else None
                if previous:
                    require(previous["payload_sha256"] == digest(action), "request_conflict", "Same request ID, different payload")
                    result = previous["response"]
                else:
                    require(before["phase"] not in ("STOPPED", "CLOSED", "AUDITING"), "stopped", str(before["stop_reason"]))
                    result = self._execute(action, attempt)
            except (HarnessError, DeltaError, ValueError, KeyError, TypeError, IndexError) as exc:
                self.store.db.execute("ROLLBACK TO business_action")
                if isinstance(exc, HarnessError):
                    result = exc.response()
                else:
                    result = {"status": "rejected", "error": {"code": getattr(exc, "code", "malformed_action"), "detail": str(exc)}}
            self.store.db.execute("RELEASE business_action")
            if type(action) is dict and type(action.get("request_id")) is str and not self.store.ref("requests", action["request_id"]):
                self.store.record("requests", action["request_id"], {"payload_sha256": digest(action), "attempt_id": attempt_id, "response": result})
            head = self.head
            if result["status"] == "ok" and action["tool"] in ("get_context", "read_entities", "read_artifact"):
                # Compare exact requests, not volatile cost fields in their answers.
                # Different pages/projections and a changed physical revision are
                # distinct reads. Processing the same durable attempt twice exits
                # above and therefore cannot increment this counter.
                signature = digest({"revision": head["revision"], "action": action})
                if head["previous_read_signature"] == signature:
                    head["same_read_count"] += 1
                else:
                    head["same_read_count"] = 1
                    head["first_read_result_ref"] = self._publish(result, "read_result")
                head["previous_read_signature"] = signature
                result = {**result, "protocol_progress": {
                    "repeated_reads": head["same_read_count"], "limit": self.config["limits"]["same_read_limit"],
                    "first_result_ref": head["first_read_result_ref"], "action_sha256": digest(action),
                    "status": "repeated_read" if head["same_read_count"] > 1 else "new_read",
                    "detail": "Identical consecutive reads at this revision count toward the frozen stop limit; original result remains readable."}}
            else:
                head.update(same_read_count=0, previous_read_signature=None, first_read_result_ref=None)
            attempt.update(status="processed", response_ref=self.store.put(result), processed_epoch=time.time())
            self.store.record("attempts", attempt_id, attempt, replace=True)
            self.store.event("action_processed", {"attempt_id": attempt_id, "raw_ref": attempt["raw_ref"], "response_ref": attempt["response_ref"]})
            if result["status"] == "rejected":
                signature = digest({"revision": head["revision"], "error": result["error"]})
                head["same_error_count"] = head["same_error_count"] + 1 if head["previous_error_signature"] == signature else 1
                head["previous_error_signature"] = signature
            else:
                head["same_error_count"], head["previous_error_signature"] = 0, None
            if head["same_error_count"] >= self.config["limits"]["same_error_limit"]:
                head.update(phase="STOPPED", stop_reason="repeated_identical_error")
                self.store.event("stopped", {"reason": head["stop_reason"], "time": head["time"]})
            elif head["same_read_count"] >= self.config["limits"]["same_read_limit"]:
                head.update(phase="STOPPED", stop_reason="repeated_identical_read")
                self.store.event("stopped", {"reason": head["stop_reason"], "time": head["time"],
                                             "action_sha256": digest(action), "first_result_ref": head["first_read_result_ref"]})
            self.store.set_meta("head", head)
        self.store.fault("after_action_committed")
        after = self.head
        if after["state_ref"] != before["state_ref"]:
            self.env = restore(self.store.get(after["state_ref"]), self.store.trace())
        self.store.export_trace()
        if result["status"] == "accepted":
            self.store.fault("after_commit_before_receipt")
        return result

    def advance(self):
        head = self.head
        require(head["phase"] == "COMMITTED", "advance_phase", "Only a confirmed explicit commit can advance")
        self.check_admission()
        prepared = deepcopy(self.env)
        start, n = prepared.t, len(prepared.trace)
        anchor, period = self.manifest["period_anchor"], self.config["period_seconds"]
        boundary = min(prepared.horizon, anchor + (math.floor((prepared.t - anchor) / period) + 1) * period)
        stop = prepared.advance_plan(boundary)
        self.store.fault("after_physical_compute")
        batch = prepared.trace[n:]
        physical = set(prepared.physical)
        feedback = {"commit_accepted": True, "from": start, "to": prepared.t, "advanced_seconds": prepared.t - start,
                    "dispatch_count_delta": sum(e["kind"] == "dispatch" and e["machine"] in physical for e in batch),
                    "completed_operations_delta": sum(e["kind"] == "operation_complete" and prepared.jobs[e["job"]]["machine"] in physical for e in batch),
                    "completed_lots_delta": sum(e["kind"] == "lot_complete" for e in batch),
                    "stop_reason": deepcopy(stop), "event_start": n, "event_end": len(prepared.trace)}
        state_ref = self.store.put(capture(prepared))
        signature = digest({"stop": stop, "plan": {k: v for k, v in prepared.plan.items() if k not in ("version", "reason", "created_at")}})
        if prepared.t == start:
            head["zero_progress"] = head["zero_progress"] + 1 if head["previous_zero_signature"] == signature else 1
            head["previous_zero_signature"] = signature
        else:
            head["zero_progress"], head["previous_zero_signature"] = 0, None
        with self.store.transaction(revision=head["revision"]):
            self.store.physical(batch)
            self.store.fault("during_physical_persist")
            self.store.event("execution_batch", {**feedback, "before_state_ref": head["state_ref"], "after_state_ref": state_ref})
            self.store.record("feedback", str(head["revision"]), feedback)
            head.update(revision=head["revision"] + 1, state_ref=state_ref, time=prepared.t, context_ref=None,
                        phase="AUDITING" if prepared.finished else "INIT")
            self.store.set_meta("head", head)
        self.store.fault("after_physical_persist")
        self.env = prepared
        self.store.export_trace()
        if head["zero_progress"] >= self.config["limits"]["zero_progress_limit"]:
            self.stop("production_no_progress")
        elif not prepared.finished:
            self.observe()
        return feedback

    def stop(self, reason):
        with self.store.transaction():
            head = self.head
            require(head["phase"] != "CLOSED", "closed_run", "Cannot change sealed run")
            head.update(phase="STOPPED", stop_reason=reason)
            self.store.set_meta("head", head)
            self.store.event("stopped", {"reason": reason, "time": head["time"], "budget": self.usage(), "state_ref": head["state_ref"]})
        self.store.export_trace()

    def reconcile(self):
        for key, attempt in self.store.rows("attempts"):
            if attempt["status"] == "responded":
                if attempt["channel"] == "codex" and (not (attempt.get("transport") or {}).get("channel_valid") or attempt.get("usage") is None):
                    if not self.manifest.get("admission"):
                        self.stop("unverified_model_response")
                        continue
                    from .recovery import current_recoveries, schedule_recovery
                    from .experiment import experiment_lock
                    with experiment_lock(self.manifest["admission"]):
                        rows = current_recoveries(self)
                        recovery = rows.get(key)
                        if recovery is None and self.head["phase"] not in ("STOPPED", "CLOSED"):
                            recovery = schedule_recovery(self, key)
                        if recovery is None:
                            self.stop("unverified_model_response")
                else:
                    self.process(key)
            elif attempt["status"] == "started":
                with self.store.transaction():
                    attempt["status"] = "unknown"
                    attempt["duration_seconds"] = max(attempt.get("duration_seconds", 0), time.time() - attempt["started_epoch"])
                    self.store.record("attempts", key, attempt, replace=True)
                    self.store.event("attempt_unknown", attempt)
                self.stop("unknown_model_result_or_usage")
            elif attempt["status"] == "reserved":
                with self.store.transaction():
                    attempt["status"] = "not_sent"
                    attempt["reserved_tokens"] = 0
                    self.store.record("attempts", key, attempt, replace=True)
                    self.store.event("reservation_not_sent", attempt)
        if self.head["phase"] == "INIT":
            self.observe()
