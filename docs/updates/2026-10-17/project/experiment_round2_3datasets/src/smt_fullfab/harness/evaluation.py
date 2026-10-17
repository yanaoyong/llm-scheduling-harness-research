"""Independent, read-only evidence validation.

Does not import Runtime, factory, compiler, constructor or model transport.
Decisions are rebuilt from raw fields; physical and opportunity checks use the
existing independent event checkers, never production commit/advance functions.
"""
from copy import deepcopy
import math
import os
from pathlib import Path
import time
import zlib

from ..audit import audit_trace
from .contracts import ROOT, SEMANTIC_COVERAGE, digest, encode, require, sha_bytes, strict_json, within_cap
from .store import fsync_dir


def seal_evidence(runtime):
    store = runtime.store
    require(runtime.head["phase"] in ("STOPPED", "AUDITING"), "seal_phase", "Stop or reach the window before sealing")
    require(not (store.path / "evidence_manifest.json").exists(), "already_sealed", "Evidence cannot be overwritten")
    store.verify()
    store.export_trace()
    with store.transaction():
        store.event("evidence_sealed", {"head": runtime.head, "usage": runtime.usage(), "sealed_epoch": time.time()})
        head = runtime.head
        head["phase"] = "CLOSED"
        store.set_meta("head", head)
    events = [dict(row) for row in store.db.execute("SELECT * FROM events ORDER BY seq")]
    records = {}
    for row in store.db.execute("SELECT namespace,key,ref FROM records ORDER BY namespace,key"):
        records.setdefault(row[0], {})[row[1]] = row[2]
    physical = [row[0] for row in store.db.execute("SELECT object_ref FROM physical ORDER BY seq")]
    objects = sorted(p.stem for p in (store.path / "objects").glob("*.z"))
    for ref in objects:
        store.bytes(ref)
    evidence = {"schema": "harness-evidence-manifest-v1", "run_id": runtime.manifest["run_id"],
                "manifest_ref": store.ref("manifest", "run"), "head": runtime.head,
                "events": events, "records": records, "physical": physical, "objects": objects,
                "trace_sha256": sha_bytes((store.path / "exports/trace.jsonl").read_bytes()),
                "fixed_ledger_scope": "exact_attempt_records_and_all_original_events_within_this_manifest",
                "semantic_coverage": SEMANTIC_COVERAGE, "sealed_epoch": time.time()}
    raw = encode(evidence)
    with (store.path / "evidence_manifest.json").open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    fsync_dir(store.path)
    return sha_bytes(raw)


class Evidence:
    def __init__(self, directory, expected_sha256):
        self.path = Path(directory)
        raw = (self.path / "evidence_manifest.json").read_bytes()
        require(sha_bytes(raw) == expected_sha256, "evidence_manifest_hash", "Evidence boundary differs")
        self.sha256 = expected_sha256
        self.value = strict_json(raw)
        self.allowed = set(self.value["objects"])
        self.cache = {}
        self.manifest = self.get(self.value["manifest_ref"])

    def raw(self, ref):
        require(ref in self.allowed, "unsealed_object", str(ref))
        raw = zlib.decompress((self.path / "objects" / (ref + ".z")).read_bytes())
        require(sha_bytes(raw) == ref, "object_corrupt", ref)
        return raw

    def get(self, ref):
        if ref not in self.cache:
            self.cache[ref] = strict_json(self.raw(ref))
        return deepcopy(self.cache[ref])

    def rows(self, namespace):
        return {key: self.get(ref) for key, ref in self.value["records"].get(namespace, {}).items()}


def rebuild_delta_plan(base, delta, state):
    """Independent interpretation of recorded explicit declarations only."""
    parts = delta["tasks"]
    pending = [t for t in base["tasks"] if t["id"] not in state["dispatched_task_ids"]]
    ids = set(parts["keep"]["ids"])
    keep = ids if parts["keep"]["mode"] == "ids" else {t["id"] for t in pending} - ids
    replacements = {t["id"]: t for t in parts["replace"]}
    require(keep | set(replacements) | set(parts["cancel_ids"]) == {t["id"] for t in pending}, "source_partition", "Task disposition incomplete")
    require(not keep & (set(replacements) | set(parts["cancel_ids"])), "source_partition", "Task dispositions overlap")
    tasks = [deepcopy(t if t["id"] in keep else replacements[t["id"]]) for t in pending if t["id"] in keep or t["id"] in replacements]
    tasks += deepcopy(parts["add"])
    by_id = {t["id"]: t for t in tasks}
    orders = {o["machine"]: iter(o["task_ids"]) for o in delta["machine_orders"]}
    tasks = [deepcopy(by_id[next(orders[t["machine"]])]) if t["machine"] in orders else t for t in tasks]
    parts = delta["holds"]
    ids = set(parts["keep"]["ids"])
    keep = ids if parts["keep"]["mode"] == "ids" else {"h:" + str(i) for i in range(len(base["holds"]))} - ids
    replacements = {h["ref"]: h["hold"] for h in parts["replace"]}
    require(keep | set(replacements) | set(parts["cancel_ids"]) == {"h:" + str(i) for i in range(len(base["holds"]))}, "source_partition", "Hold disposition incomplete")
    holds = []
    for i, hold in enumerate(base["holds"]):
        ref = "h:" + str(i)
        if ref in keep:
            holds.append(deepcopy(hold))
        elif ref in replacements:
            holds.append(deepcopy(replacements[ref]))
    holds += deepcopy(parts["add"])
    return {**deepcopy(delta["plan_header"]), "tasks": tasks, "holds": holds}


def raw_delta(evidence, candidate, attempts):
    attempt = attempts[candidate["attempt_id"]]
    action = strict_json(evidence.raw(attempt["raw_ref"]))
    if type(action) is dict and set(action) == {"action"}:
        action = action["action"]
    if candidate.get("draft") is None:
        require(action["tool"] == "propose_delta", "source_action", "Candidate lacks original proposal")
        delta = deepcopy(action["delta"])
    else:
        require(action["tool"] == "finalize_proposal", "source_action", "Candidate lacks original finalization")
        delta = {}
        for chunk in candidate["draft"]["chunks"]:
            original = strict_json(evidence.raw(attempts[chunk["attempt_id"]]["raw_ref"]))
            if type(original) is dict and set(original) == {"action"}:
                original = original["action"]
            require(original["tool"] == "append_proposal" and all(original[k] == chunk["business_chunk"][k] for k in ("chunk_id", "set_fields", "append_arrays")), "chunk_source", "Chunk differs from raw output")
            for entry in original["set_fields"]:
                cur = delta
                for key in entry["path"][:-1]:
                    cur = cur.setdefault(key, {})
                require(entry["path"][-1] not in cur, "chunk_source", "Conflicting field declaration")
                cur[entry["path"][-1]] = deepcopy(entry["value"])
            for entry in original["append_arrays"]:
                cur = delta
                for key in entry["path"][:-1]:
                    cur = cur.setdefault(key, {})
                cur.setdefault(entry["path"][-1], []).extend(deepcopy(entry["items"]))
    for key in ("schema", "anchors"):
        if key not in delta:
            delta[key] = candidate["delta"][key]
    require(digest(delta) == digest(candidate["delta"]), "delta_source", "Compiled input differs from raw production decisions")
    return delta


def _at(value, path):
    for key in path:
        value = value[key]
    return value


def audit_provenance(evidence, trace):
    records = evidence.value["records"]
    attempts, candidates, contexts, commits = (evidence.rows(k) for k in ("attempts", "candidates", "contexts", "commits"))
    arm = evidence.manifest["config"]["arm"]
    committed_events = [e for e in trace[evidence.manifest["prefix_events"]:] if e["kind"] == "plan_committed"]
    ordered_commits = sorted(commits.values(), key=lambda c: c["trace_start"])
    require(len(committed_events) == len(ordered_commits), "commit_count", "Commit receipts and physical plan acceptances differ")
    algorithm_decisions = 0
    previous_plan = None
    prefix = trace[:evidence.manifest["prefix_events"]]
    for event in prefix:
        if event["kind"] == "plan_committed":
            previous_plan = event["plan"]
    for event, commit in zip(committed_events, ordered_commits):
        candidate = candidates[commit["candidate_ref"]]
        selection = attempts[commit["selection_attempt_id"]]
        proposal = attempts[candidate["attempt_id"]]
        raw = strict_json(evidence.raw(selection["raw_ref"]))
        if type(raw) is dict and set(raw) == {"action"}:
            raw = raw["action"]
        require(raw["tool"] == "apply_candidate" and raw["candidate_ref"] == commit["candidate_ref"]
                and raw["context_ref"] == candidate["context_ref"], "apply_source", "No exact explicit raw selection")
        require(selection["index"] > proposal["index"] and selection["attempt_id"] != proposal["attempt_id"], "apply_order", "Same-output check/apply")
        require(commit["expected_revision"] == candidate["revision"] and commit["actual_revision"] == candidate["revision"] + 1,
                "stale_commit", "Commit accepted stale candidate")
        if evidence.manifest["mode"] == "model" and arm in ("B", "C"):
            require(selection["channel"] == proposal["channel"] == "codex", "model_source", "Real model run contains injected decision")
        context = contexts[candidate["context_ref"]]
        base = context["base_plan"]
        require(previous_plan is None or digest(base) == digest(previous_plan), "base_source", "Base differs from prior accepted plan")
        if candidate["transformation_kind"] == "explicit_delta_compilation":
            delta = raw_delta(evidence, candidate, attempts)
            anchors = {"base_plan_sha256": digest(base), "problem_sha256": digest(context["problem"]),
                       "state_sha256": digest(context["execution_state"]), "source_sha256": context["source_sha256"]}
            require(delta["anchors"] == anchors, "anchors", "Raw proposal context binding differs")
            reconstructed = rebuild_delta_plan(base, delta, context["execution_state"])
            def leaf_paths(value, prefix=()):
                if isinstance(value, dict) and value:
                    return [p for k, v in value.items() for p in leaf_paths(v, (*prefix, k))]
                if isinstance(value, list) and value:
                    return [p for k, v in enumerate(value) for p in leaf_paths(v, (*prefix, k))]
                return [prefix]
            expected_paths = set(leaf_paths(reconstructed)) - {("tasks",), ("holds",)}
            actual_paths = [tuple(f["plan_path"]) for f in candidate["field_sources"]]
            require(len(actual_paths) == len(set(actual_paths)) and set(actual_paths) == expected_paths,
                    "field_source_coverage", "Every declared production leaf must have exactly one source")
            for field in candidate["field_sources"]:
                source = delta if field["source"] == "delta" else base
                value = _at(source, field["source_path"])
                require(digest(value) == field["value_sha256"] == digest(_at(reconstructed, field["plan_path"])), "field_source", "Field trace differs")
        else:
            algorithm_decisions += len(candidate["compiled"]["plan"]["tasks"])
            require(arm != "B", "B_algorithm_decision", "B used an algorithm")
            tool_result = evidence.get(candidate["algorithm_result_ref"])
            algorithm_attempt = evidence.rows("classical_attempts")[candidate["attempt_id"]]
            tool_request = evidence.get(algorithm_attempt["request_ref"])
            raw_request = strict_json(evidence.raw(proposal["raw_ref"]))
            if type(raw_request) is dict and set(raw_request) == {"action"}:
                raw_request = raw_request["action"]
            require(raw_request["algorithm_id"] == tool_request["algorithm_id"] == algorithm_attempt["algorithm_id"]
                    and raw_request["parameters"] == tool_request["parameters"] and raw_request["budget_seconds"] == tool_request["budget_seconds"],
                    "algorithm_source", "Tool invocation differs from explicit output")
            require(algorithm_attempt["result_ref"] == candidate["algorithm_result_ref"] and algorithm_attempt["status"] == "finished"
                    and tool_request["problem"] == context["problem"], "algorithm_source", "Algorithm result has no bound completed invocation")
            reconstructed = tool_result["plan"]
            require(candidate["decision_owner"] == "algorithm", "algorithm_owner", "Algorithm result misattributed")
        require(digest(reconstructed) == digest(candidate["compiled"]["plan"]) == digest(event["plan"]) == commit["plan_sha256"],
                "plan_source", "Accepted production plan differs from independent raw reconstruction")
        require(trace[commit["trace_start"]] == event and commit["trace_end"] == commit["trace_start"] + 1, "commit_events", "Commit trace boundary differs")
        previous_plan = event["plan"]
    return {"valid": True, "commits": len(ordered_commits), "algorithm_production_tasks": algorithm_decisions,
            "B_algorithm_calls": len(evidence.rows("classical_attempts")) if arm == "B" else None,
            "independence": "raw JSON reconstruction; production compiler and commit functions not called"}


def audit_cost(evidence):
    attempts = evidence.rows("attempts")
    actual = [a for a in attempts.values() if a["channel"] == "codex" and a["status"] not in ("reserved", "not_sent")]
    unknown = [a for a in actual if a.get("usage") is None]
    known = [a for a in actual if a.get("usage") is not None]
    admission = evidence.manifest.get("admission")
    if admission:
        from .network import for_admission
        binding = for_admission(admission)
        if binding:
            for attempt in actual:
                if attempt['status'] in ('started','unknown'):
                    continue  # unresolved attempts remain invalid below
                ref = (attempt.get('transport') or {}).get('original_input_files', {}).get('network.json')
                expected_binding = binding
                if binding.get('mode') == 'user_managed_host_network' and (
                        evidence.manifest['run_id'] != binding['run_id'] or
                        attempt['index']+1 < binding['first_actual_call']):
                    expected_binding = binding['original_binding']
                require(ref is not None and evidence.get(ref) == expected_binding,
                        'network_source', 'Actual call lacks its frozen supervised route input')
    for attempt in known:
        transport = attempt.get("transport")
        require(transport and "events_ref" in transport, "usage_source", "Actual usage requires original channel events")
        events = [strict_json(line) for line in evidence.raw(transport["events_ref"]).splitlines() if line.strip()]
        completions = [e for e in events if e.get("type") == "turn.completed"]
        require(len(completions) == 1 and all(completions[0]["usage"][k] == attempt["usage"][k] for k in ("input_tokens", "output_tokens")), "usage_source", "Usage differs from raw completion")
        require(not any(e.get("type") in ("item.started", "item.completed", "item.updated") and e.get("item", {}).get("type") not in ("agent_message", "reasoning", "error") for e in events), "native_tool", "Model used forbidden native tools")
        guard = evidence.get(transport["guard_ref"])
        originals = transport["original_guard_files"]
        require(originals == guard["files_sha256"], "guard_source", "Guard summary is not bound to its original files")
        docs = {name: strict_json(evidence.raw(ref)) for name, ref in originals.items() if name.endswith(".json")}
        spec, receipt, waited = (docs[name] for name in ("spec.json", "receipt.json", "parent_observed.json"))
        require(spec["call_id"] == receipt["call_id"] == attempt["attempt_id"] and spec["argv"] == evidence.get(transport["command_ref"]), "guard_source", "Original supervised call differs")
        require(transport["original_input_files"] == spec["input_files_sha256"] and spec["input_files_sha256"]["prompt.txt"] == attempt["prompt_ref"]
                and spec["input_files_sha256"]["schema.json"] == attempt["schema_ref"], "guard_inputs", "Original prompt/schema/metadata differs")
        final_sha = receipt["output_files_sha256"]["final.txt"]
        require(receipt["output_files_sha256"]["events.jsonl"] == transport["events_ref"]
                and (final_sha == attempt["raw_ref"] or (final_sha is None and evidence.raw(attempt["raw_ref"]) == b"")), "guard_outputs", "Original output hashes differ")
        duration = waited["observed_monotonic_seconds"] - spec["begun_monotonic_seconds"]
        require(duration >= 0 and duration == attempt["duration_seconds"] == guard["parent_wait_wall_seconds"]
                and waited["wait_completed"] is True and receipt["command_returncode"] == transport["returncode"], "guard_duration", "Model activity is not reconciled to original process timestamps")
        require(completions[0]["usage"].get("cached_input_tokens", 0) == attempt["usage"].get("cached_input_tokens", 0), "usage_source", "Cached input differs from original telemetry")
    inputs = sum(a["usage"]["input_tokens"] for a in known)
    outputs = sum(a["usage"]["output_tokens"] for a in known)
    model_seconds = sum(a["duration_seconds"] for a in actual)
    from .wall_budget import effective_budget
    budget = effective_budget(evidence.manifest, evidence.rows('control_source_revisions'))
    limits = budget['limits']
    elapsed = evidence.value["sealed_epoch"] - evidence.manifest["created_epoch"]
    pending = [a for a in attempts.values() if a["status"] in ("reserved", "started", "unknown")]
    classical = list(evidence.rows("classical_attempts").values())
    classical_unknown = sum(a["status"] in ("started", "unknown") for a in classical)
    classical_seconds = sum(a.get("duration_seconds", 0) for a in classical)
    from .transport_requalification import diagnostic_usage, validate_records
    if evidence.rows('transport_requalifications'):
        from .experiment import registration
        from .recovery import policy_for
        validate_records(evidence,registration(admission),policy_for(admission))
    diagnostic = diagnostic_usage(evidence)
    valid = not unknown and not diagnostic['unknown_usage'] and not pending and not classical_unknown and len(classical) <= limits["classical_requests"] and classical_seconds <= limits["classical_seconds"] and within_cap(len(actual)+diagnostic['attempts'], limits["attempts"]) and within_cap(inputs+outputs+diagnostic['tokens'], limits["tokens"]) and model_seconds+diagnostic['model_seconds'] <= limits["model_seconds"] and elapsed <= limits["wall_seconds"]
    result = {"valid": valid, "actual_attempts": len(actual), "input_tokens": inputs, "output_tokens": outputs,
            "cached_input_tokens": sum(a["usage"].get("cached_input_tokens", 0) for a in known),
            "total_reported_tokens": inputs + outputs, "unknown_usage": len(unknown), "pending_attempts": len(pending),
            "model_seconds": model_seconds, "experiment_through_seal_wall_seconds": elapsed,
            "classical_attempts": len(classical), "classical_unknown": classical_unknown, "classical_seconds": classical_seconds,
            "monetary_cost": None, "token_hard_cap": False}
    if diagnostic['attempts']:
        result.update(associated_diagnostics=diagnostic,
                      accounted_actual_attempts=len(actual)+diagnostic['attempts'],
                      accounted_reported_tokens=inputs+outputs+diagnostic['tokens'],
                      accounted_model_seconds=model_seconds+diagnostic['model_seconds'],
                      accounted_unknown_usage=len(unknown)+diagnostic['unknown_usage'],
                      diagnostic_wall_seconds_added=0)
    if budget['wall_extension_seconds']:
        result.update(original_wall_limit_seconds=budget['original_wall_seconds'],
                      approved_wall_extension_seconds=budget['wall_extension_seconds'],
                      effective_wall_limit_seconds=limits['wall_seconds'],
                      original_wall_limit_exceeded=elapsed > budget['original_wall_seconds'])
    if budget.get('model_extension_seconds'):
        result.update(original_model_limit_seconds=budget['original_model_seconds'],
                      approved_model_extension_seconds=budget['model_extension_seconds'],
                      effective_model_limit_seconds=limits['model_seconds'],
                      original_model_limit_exceeded=model_seconds > budget['original_model_seconds'])
    return result


def audit_physical_prefix(trace, observed_end, weights):
    """Independent prefix checks with an explicit physical accounting cutoff.

    Plan validity and opportunity rules use the ORIGINAL declared horizon.
    Only the low-level physical checker uses the observed cutoff for due events.
    No terminal is invented: its absence remains in the returned errors.
    """
    from ..audit import audit_plan_sources, audit_opportunity_coverage, PHYSICAL_KINDS
    from ..metrics import compute_metrics
    from src.smt.audit import audit_trace as physical_replay
    source = audit_plan_sources(trace)
    opportunity = audit_opportunity_coverage(trace)
    projected = []
    decision = 0
    controls = set(trace[0]["manifest"]["controlled_machine_ids"])
    for original in trace:
        if original["kind"] not in PHYSICAL_KINDS:
            continue
        event = deepcopy(original)
        if event["kind"] == "initial":
            event["manifest"]["horizon"] = observed_end
        if event["kind"] == "dispatch" and event["machine"] in controls:
            projected.append({"seq": len(projected), "time": event["time"], "kind": "action", "decision": decision,
                              "action": {"dispatches": [{"machine": event["machine"], "lot_ids": event["lots"]}], "wait_seconds": 0}})
            decision += 1
            event["owner"] = "controller"
        event["seq"] = len(projected)
        projected.append(event)
    physical = physical_replay(projected, ROOT / "data/smt/SMT2020_LVHM")
    errors = source["errors"] + ["opportunity: " + e for e in opportunity["errors"]] + ["physical: " + e for e in physical["errors"]]
    return {"valid": not errors, "errors": errors, "plan_source_audit": source,
            "opportunity_audit": opportunity, "physical_replay": physical,
            "physical_projection_sha256": digest(projected), "observed_cutoff": observed_end,
            "metrics": compute_metrics(trace, window_start=0, priority_weights=weights)}


def audit_run(directory, *, expected_sha256, output_dir=None, scope="full_window"):
    require(scope in ("full_window", "accepted_fragment"), "audit_scope", "Explicit registered audit scope required")
    started = time.perf_counter()
    errors = []
    integrity, provenance, physics, cost = False, None, None, None
    evidence = None
    recovery_exception = None
    try:
        evidence = Evidence(directory, expected_sha256)
        for ref in evidence.allowed:
            evidence.raw(ref)
        previous = None
        for seq, event in enumerate(evidence.value["events"], 1):
            core = {k: v for k, v in event.items() if k != "sha256"}
            require(event["seq"] == seq and event["previous"] == previous and digest(core) == event["sha256"], "event_chain", "Workflow event discontinuity")
            evidence.get(event["payload_ref"])
            previous = event["sha256"]
        require(evidence.value["events"][-1]["kind"] == "evidence_sealed", "missing_seal", "No final seal event")
        from .amendment import validate_continuation
        validate_continuation(evidence)
        trace = [evidence.get(ref) for ref in evidence.value["physical"]]
        require(all(e["seq"] == i for i, e in enumerate(trace)), "trace_sequence", "Physical events are discontinuous")
        require(sha_bytes(b"".join(encode(e) + b"\n" for e in trace)) == evidence.value["trace_sha256"], "trace_hash", "Trace export differs")
        state = evidence.get(evidence.value["head"]["state_ref"])
        require(state["t"] == evidence.value["head"]["time"], "state_clock", "Head clock differs from state")
        require(trace[-1]["time"] == state["t"], "state_clock", "Last physical event differs from durable clock")
        require(digest(trace[:evidence.manifest["prefix_events"]]) == evidence.manifest["initial_trace_sha256"]
                if evidence.manifest["prefix_events"] else True, "initial_trace", "Inherited prehistory changed")
        last_plan = next((e["plan"] for e in reversed(trace) if e["kind"] == "plan_committed"), None)
        require(last_plan == state["plan"], "snapshot_plan", "Durable state differs from last accepted plan")
        statuses = {lot["id"]: "unreleased" for lot in trace[0]["manifest"]["lots"]}
        for event in trace:
            kind = event["kind"]
            if kind in ("release", "ready", "skip", "operation_complete", "lot_complete"):
                statuses[event["lot"]] = {"release": "released", "ready": "waiting", "skip": "transition", "operation_complete": "transition", "lot_complete": "done"}[kind]
            elif kind == "dispatch":
                for lot in event["lots"]:
                    statuses[lot] = "processing"
        require(statuses == {lot: value["status"] for lot, value in state["lots"].items()}, "snapshot_inventory", "Durable inventory differs from independently replayed events")
        integrity = True
        try:
            provenance = audit_provenance(evidence, trace)
        except Exception as exc:
            errors.append("provenance: " + str(exc))
        weights = {int(k): v for k, v in evidence.manifest["config"]["priority_weights"].items()}
        if scope == "accepted_fragment" and not state["finished"]:
            physics = audit_physical_prefix(trace, state["t"], weights)
        else:
            physics = audit_trace(trace, verify_data_dir=ROOT / "data/smt/SMT2020_LVHM", window_start=evidence.manifest["start_time"], priority_weights=weights)
        prefix_checks = scope == "accepted_fragment" and physics["errors"] == ["physical: missing terminal event"]
        if not physics["valid"] and not prefix_checks:
            errors.extend(physics["errors"])
        try:
            cost = audit_cost(evidence)
            if not cost["valid"]:
                # Operational completion may use the user's bounded MICRO
                # exception. Accounting remains invalid/unclosed, never zero.
                # Full B keeps its original zero-unknown acceptance requirement.
                from .recovery import validate_recoveries
                covered = validate_recoveries(evidence)
                limits = evidence.manifest["config"]["limits"]
                admission = evidence.manifest.get("admission") or {}
                exception_ok = (scope == "accepted_fragment" and admission.get("group") == "micro" and
                                len(covered) == cost["unknown_usage"] > 0 and not cost["pending_attempts"] and
                                not cost["classical_unknown"] and cost["classical_attempts"] <= limits["classical_requests"] and
                                cost["classical_seconds"] <= limits["classical_seconds"] and
                                within_cap(cost["actual_attempts"], limits["attempts"]) and within_cap(cost["total_reported_tokens"], limits["tokens"]) and
                                cost["model_seconds"] <= limits["model_seconds"] and cost["experiment_through_seal_wall_seconds"] <= limits["wall_seconds"])
                if exception_ok:
                    recovery_exception = {"authorized_for_fragment_completion": True, "attempt_ids": sorted(covered),
                                          "cost_closed": False, "unknown_usage": cost["unknown_usage"], "reported_tokens_are_lower_bound": True}
                else:
                    errors.append("cost: unknown, unsettled or out-of-budget attempt")
        except Exception as exc:
            errors.append("cost: " + str(exc))
        terminal = bool(trace and trace[-1]["kind"] == "terminal" and trace[-1]["time"] == evidence.manifest["end_time"] and state["finished"])
        fragment = (scope == "accepted_fragment" and evidence.manifest["parent"] is not None
                    and len(evidence.rows("commits")) == 1 and evidence.value["head"]["stop_reason"] == "registered_fragment_accepted")
        if not terminal and not fragment:
            errors.append("execution_window: missing terminal at registered end")
    except Exception as exc:
        errors.append("integrity: " + str(exc))
        terminal = False
        fragment = False
    config = evidence.manifest["config"] if evidence else {}
    result = {"schema": "harness-acceptance-v1", "evidence_sha256": expected_sha256,
              "run_id": evidence.manifest["run_id"] if evidence else None,
              "valid": bool(not errors and integrity and (terminal or fragment) and provenance and physics and cost), "errors": errors,
              "audit_scope": scope, "fragment_acceptance": bool(fragment),
              "physical_audit_cut": {"observed_end": evidence.value["head"]["time"], "registered_end": evidence.manifest["end_time"],
                                     "view_horizon_is_observed_cut": scope == "accepted_fragment", "invented_terminal_events": 0} if evidence else None,
              "execution_window": "pass" if terminal else "fail", "evidence_integrity": "pass" if integrity else "fail",
              "decision_provenance": provenance, "physical_validity": bool(physics and physics["valid"]),
              "physical_prefix_checks": bool(physics and (physics["valid"] or (scope == "accepted_fragment" and physics["errors"] == ["physical: missing terminal event"]))),
              "physical_full_window_errors": physics["errors"] if physics else None,
              "opportunity_coverage": physics.get("opportunity_audit") if physics else None,
              "semantic_coverage": SEMANTIC_COVERAGE, "cost_accounting": cost,
              "bounded_recovery_exception": recovery_exception,
              "metrics": physics.get("metrics") if physics else None,
              "quality_evaluation": "not_evaluated_no_paired_experiment",
              "latency_evaluation": "offline_paused_simulation_only",
              "recovery_validation": "requires_separate_T15_T21_T27_T28_report",
              "mode": evidence.manifest["mode"] if evidence else None,
              "G5": "not_evaluated_requires_registered_microbenchmark_and_fresh_B_3600",
              "auditor_sha256": sha_bytes(Path(__file__).read_bytes()), "audit_seconds": time.perf_counter() - started}
    if cost and evidence:
        # The first mandatory audit closes the experiment clock. Later independent
        # re-audits recompute every check, but cannot charge months of elapsed time
        # or an unrelated shared ledger to this already sealed experiment.
        closure_path = Path(directory) / "audit_closure.json"
        if closure_path.exists():
            closure = strict_json(closure_path.read_bytes())
            require(closure["evidence_sha256"] == expected_sha256, "audit_closure", "Closure belongs to different evidence")
        else:
            closure = {"schema": "harness-audit-closure-v1", "evidence_sha256": expected_sha256,
                       "completed_epoch": time.time(), "auditor_sha256": result["auditor_sha256"]}
            with closure_path.open("xb") as stream:
                stream.write(encode(closure))
                stream.flush()
                os.fsync(stream.fileno())
            fsync_dir(closure_path.parent)
        cost["experiment_plus_audit_wall_seconds"] = closure["completed_epoch"] - evidence.manifest["created_epoch"]
        if cost["experiment_plus_audit_wall_seconds"] > cost.get('effective_wall_limit_seconds', config['limits']['wall_seconds']):
            cost["valid"] = result["valid"] = False
            result["errors"].append("cost: mandatory audit exceeded total wall cap")
    if output_dir is not None:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=False)
        (out / "acceptance.json").write_bytes(encode(result) + b"\n")
        status = {k: result[k] for k in ("run_id", "evidence_sha256", "valid", "execution_window", "physical_validity", "semantic_coverage", "quality_evaluation", "latency_evaluation")}
        (out / "STATUS.json").write_bytes(encode(status) + b"\n")
        (out / "report.md").write_text("# Harness 运行验收\n\n" + f"运行：{result['run_id']}\n\n工程检查：{'通过' if result['valid'] else '未通过'}。证据：`{expected_sha256}`。\n\n语义覆盖 partial；质量比较和在线能力未验收。\n\n" + "\n".join("- " + e for e in errors) + "\n", encoding="utf-8")
    return result


def microbenchmark_gate(fragments, *, metrics=None):
    metrics = metrics or {'n_min':20, 'median_max':3, 'p95_max':5, 'enforcement':'hard'}
    require(metrics.get('enforcement', 'hard') in ('hard', 'advisory'), 'micro_metrics', 'Unknown count policy')
    counts = sorted(row["attempts"] for row in fragments)
    n = len(counts)
    median = (counts[n // 2] if n % 2 else (counts[n // 2 - 1] + counts[n // 2]) / 2) if n else None
    p95 = counts[math.ceil(.95 * n) - 1] if n else None
    complete = n >= metrics['n_min'] and all(row['accepted'] and not row.get('not_completed', False) for row in fragments)
    efficiency = bool(complete and median <= metrics['median_max'] and p95 <= metrics['p95_max'])
    advisory = metrics.get('enforcement', 'hard') == 'advisory'
    if advisory and not complete:
        median = p95 = None  # Unstarted/failed rows stay in the denominator, not completion statistics.
    return {"n": n, "median": median, "p95_nearest_rank": p95,
            "complete": complete, "correctness_pass": complete,
            "call_count_enforcement": 'advisory' if advisory else 'hard',
            "efficiency_target_pass": efficiency if complete else None,
            "warnings": ['call_count_efficiency_target_exceeded'] if advisory and complete and not efficiency else [],
            "pass": complete and (advisory or efficiency),
            "failed_fragment_ids": [row["id"] for row in fragments if not row["accepted"]]}
