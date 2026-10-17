"""Frozen P5 registration and shared cumulative accounts; no scheduling code."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import fcntl
import json
from pathlib import Path
import sqlite3
import time
import zlib

from .contracts import digest, encode, require, sha_bytes, strict_json, within_cap

CAPS = {
    "micro": {"attempts": 100, "tokens": 2_000_000, "model_seconds": 3600, "wall_seconds": 7200},
    "B3600": {"attempts": 250, "tokens": 6_000_000, "model_seconds": 10800, "wall_seconds": 14400},
    "combined": {"attempts": 350, "tokens": 8_000_000, "model_seconds": 14400, "wall_seconds": 21600},
}
CONTINUATION_CAPS = {
    **CAPS,
    "micro": {**CAPS["micro"], "tokens": 6_000_000},
    "combined": {**CAPS["combined"], "tokens": 20_000_000},
}


UNCAPPED_MODEL_CAPS = {group: {**cap, "attempts": None, "tokens": None}
                  for group, cap in CONTINUATION_CAPS.items()}
BOUNDED_TIME_CAPS = {**UNCAPPED_MODEL_CAPS,
                     "micro": {**UNCAPPED_MODEL_CAPS["micro"], "model_seconds": 5400},
                     "combined": {**UNCAPPED_MODEL_CAPS["combined"], "model_seconds": 16200}}

PRESENTATION_TIME_CAPS = {**BOUNDED_TIME_CAPS,
    "micro": {**BOUNDED_TIME_CAPS["micro"], "model_seconds": 7200, "wall_seconds": 10800},
    "combined": {**BOUNDED_TIME_CAPS["combined"], "model_seconds": 18000, "wall_seconds": 25200}}
PRESENTATION_EXECUTION_ORDER = [f"micro-{i:02d}" for i in [8, 11, *range(12, 21), *range(1, 8), 9, 10]]

# User-authorized bounded recovery, distinct from hidden CLI/stream retries.
RECOVERY_POLICY = {"max_retries_per_request": 2, "cooldown_seconds": [60, 180],
                   "max_failures_per_cohort": 5,
                   "allowed_failure_kinds": ["capacity", "connection", "stream_disconnect"],
                   "unknown_usage": "retain_unknown", "full_B_requires_zero_unknown": True}


def checked_file(reference):
    raw = Path(reference["path"]).read_bytes()
    require(sha_bytes(raw) == reference["sha256"], "carry_evidence", "Frozen dependency changed: " + reference["path"])
    return strict_json(raw)


def continuation_authorization(reference):
    grant = checked_file(reference)
    if grant.get("schema") == "harness-B-network-restart-authorization-v1":
        from .B_network_restart import validate_grant
        return validate_grant(grant)
    if grant.get("schema") == "harness-B-model-switch-authorization-v1":
        from .B_model_switch import validate_grant
        return validate_grant(grant)
    if grant.get("schema") in ("harness-model-switch-authorization-v1", "harness-model-switch-authorization-v2"):
        from .model_switch import validate_grant
        return validate_grant(grant)
    old = grant["schema"] == "harness-user-continuation-20261014-v1" and grant["caps"] == CONTINUATION_CAPS
    new = (grant["schema"] in ("harness-user-continuation-20261014-v2", "harness-user-continuation-20261014-v3", "harness-user-continuation-20261014-v4") and grant["caps"] == UNCAPPED_MODEL_CAPS and
           grant.get("unknown_usage_policy") == "freeze_new_calls" and grant.get("automatic_retries") == 0 and
           "max_attempts_per_fragment" in grant and grant["max_attempts_per_fragment"] is None)
    time_extension = grant["schema"] in ("harness-user-continuation-20261014-v6", "harness-user-continuation-20261014-v7")
    extended_caps = PRESENTATION_TIME_CAPS if grant["schema"].endswith("-v7") else BOUNDED_TIME_CAPS
    bounded = (grant["schema"] in ("harness-user-continuation-20261014-v5", "harness-user-continuation-20261014-v6", "harness-user-continuation-20261014-v7") and grant["caps"] == (extended_caps if time_extension else UNCAPPED_MODEL_CAPS) and
               grant.get("unknown_usage_policy") == "bounded_terminated_failures" and grant.get("automatic_retries") == 0 and
               grant.get("recovery_policy") == RECOVERY_POLICY and
               "max_attempts_per_fragment" in grant and grant["max_attempts_per_fragment"] is None)
    require((old or new or bounded) and grant["full_B_new_run_limit"] == 1 and
            grant["same_twenty_fragments"] is True and grant["retain_failures_and_costs"] is True,
            "continuation_grant", "Continuation must match the explicit user grant")
    exceptions = grant.get("historical_unknown_exceptions", [])
    if grant["schema"] in ("harness-user-continuation-20261014-v3", "harness-user-continuation-20261014-v4", "harness-user-continuation-20261014-v5", "harness-user-continuation-20261014-v6", "harness-user-continuation-20261014-v7"):
        expected_count = 3 if bounded else 2 if grant["schema"].endswith("-v4") else 1
        require(type(exceptions) is list and len(exceptions) == expected_count, "unknown_exception", "Only the explicitly authorized historical exceptions are allowed")
        for item in exceptions:
            require(type(item) is dict and set(item) == {"run_id", "attempt_id", "attempt_record_sha256", "original_registration", "boundary",
                             "events_sha256", "group", "unreported_usage", "retry_original", "preserve_failure", "scope"} and
                item["group"] == "micro" and item["unreported_usage"] is None and item["retry_original"] is False and
                item["preserve_failure"] is True and item["scope"] == "new_cohorts_only",
                "unknown_exception", "Exception cannot erase cost, replay the request or authorize new unknowns")
            require(all(type(item[k]) is str and bool(item[k]) for k in ("run_id", "attempt_id", "attempt_record_sha256", "events_sha256")),
                "unknown_exception", "Exact immutable attempt identity required")
        require(len({(e["run_id"], e["attempt_id"]) for e in exceptions}) == expected_count,
                "unknown_exception", "Duplicate exceptions cannot replace retained history")
        if expected_count >= 2:
            predecessor = checked_file(grant["supersedes_authorization"])
            require(predecessor["schema"] == ("harness-user-continuation-20261014-v6" if grant["schema"].endswith("-v7") else "harness-user-continuation-20261014-v5" if time_extension else "harness-user-continuation-20261014-v4" if bounded else "harness-user-continuation-20261014-v3"),
                    "unknown_exception", "The second exception must extend the original exact grant")
            predecessor = continuation_authorization(grant["supersedes_authorization"])
            require((exceptions if time_extension else exceptions[:-1]) == predecessor["historical_unknown_exceptions"],
                    "unknown_exception", "Previously authorized failures and bindings must be retained unchanged")
    else:
        require(not exceptions, "unknown_exception", "Older grants contain no unknown-usage exception")
    if grant["schema"] == "harness-user-continuation-20261014-v7":
        require(grant.get("micro_execution_order") == PRESENTATION_EXECUTION_ORDER,
                "execution_order", "Validate difficult cases, continue unfinished cases, then complete same-version evidence")
    return grant


def historical_exceptions(value):
    return continuation_authorization(value["authorization"]).get("historical_unknown_exceptions", []) if "authorization" in value else []


def resource_status(value, usage):
    """A historical exception changes admission only, never the cost ledger."""
    # Validation proves every allowed identity occurs exactly once in closed
    # predecessor evidence; a count by itself can never authorize an exception.
    diagnostic_unknown = diagnostic_account_unknowns(value)
    if value.get("schema") in ("harness-model-switch-registration-v1", "harness-B-model-switch-registration-v1", "harness-B-network-restart-registration-v1"):
        prior, _, _ = sealed_prior(value)
        from .recovery import cohort_recoveries
        recovered = cohort_recoveries(value)
        counts = {g:sum(len(rows) for group,rows in recovered.values() if group==g) for g in ("micro","B3600")}
        counts["combined"] = sum(counts.values())
        return {"authorized_historical_unknown_usage":{g:prior[g]["unknown_usage"] for g in prior},
                "authorized_bounded_unknown_usage":counts,
                "authorized_diagnostic_unknown_usage":diagnostic_unknown,
                "unexempt_unknown_usage":{g:usage[g]["unknown_usage"]-prior[g]["unknown_usage"]-counts[g]-diagnostic_unknown[g] for g in usage},
                "cumulative_cost_closed":usage["combined"]["unknown_usage"]==0,
                "reported_tokens_are_lower_bound":usage["combined"]["unknown_usage"]!=0}
    carried_recoveries = {}
    sealed_prior(value, recovered=carried_recoveries)
    exceptions = historical_exceptions(value)
    allowed = {g: sum(e["group"] == g for e in exceptions) for g in ("micro", "B3600")}
    allowed["combined"] = sum(allowed.values())
    from .recovery import cohort_recoveries
    recovered = cohort_recoveries(value)
    recoveries = {g: sum(len(ids) for group, ids in recovered.values() if group == g) for g in ("micro", "B3600")}
    recoveries["combined"] = sum(recoveries.values())
    prior_recoveries = {g: sum(r["group"] == g for r in carried_recoveries.values()) for g in ("micro", "B3600")}
    prior_recoveries["combined"] = sum(prior_recoveries.values())
    return {"authorized_historical_unknown_usage": allowed,
            "authorized_bounded_unknown_usage": recoveries,
            "authorized_prior_bounded_unknown_usage": prior_recoveries,
            "authorized_diagnostic_unknown_usage":diagnostic_unknown,
            "unexempt_unknown_usage": {g: usage[g]["unknown_usage"] - allowed[g] - recoveries[g] - prior_recoveries[g] - diagnostic_unknown[g] for g in usage},
            "cumulative_cost_closed": usage["combined"]["unknown_usage"] == 0,
            "reported_tokens_are_lower_bound": usage["combined"]["unknown_usage"] != 0,
            "historical_unknown_exceptions": exceptions}


def diagnostic_account_unknowns(reg):
    """Only process-proven closed diagnostics may use the existing exception."""
    from .recovery import LiveEvidence, policy_for
    from .transport_requalification import diagnostic_usage, validate_records
    result = {g:0 for g in ("micro","B3600","combined")}
    if reg.get("schema") != "harness-B-network-restart-registration-v1":
        return result  # Older registrations cannot authorize this B-only revision.
    for _,group,_,directory,_ in account_records(Path(reg['experiment_directory'])):
        view = LiveEvidence(directory)
        if view.rows('transport_requalifications'):
            validate_records(view,reg,policy_for(view.manifest['admission']))
            result[group] += diagnostic_usage(view,reg)['unknown_usage']
    result['combined'] = sum(result.values())
    return result


@contextmanager
def experiment_lock(admission):
    root = Path(admission["experiment_directory"])
    with (root / "writer.lock").open("a+b") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            require(False, "experiment_busy", "Another real model call owns the shared account")
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


_registration_scope = ContextVar('harness_registration_scope', default=None)


@contextmanager
def registration_validation_scope():
    """Share static proof only during synchronous request preparation.

    Live usage, pending requests, cooldowns and network state are not cached.
    The caller must leave this scope before executing a remote request.
    """
    token = None
    if _registration_scope.get() is None:
        token = _registration_scope.set({})
    try:
        yield
    finally:
        if token is not None:
            _registration_scope.reset(token)


def registration(admission):
    """Reuse fully validated ancestors within one synchronous validation only.

    The registration bytes are checked even on a hit. The scope is discarded
    on success or failure, so subsequent admissions inspect dependencies again.
    """
    scope = _registration_scope.get()
    token = None
    if scope is None:
        scope = {}
        token = _registration_scope.set(scope)
    try:
        root = Path(admission['experiment_directory']).resolve()
        raw = (root / 'experiment.json').read_bytes()
        require(sha_bytes(raw) == admission['experiment_sha256'], 'registration_changed', 'Frozen experiment differs')
        key = (str(root), admission['experiment_sha256'])
        if key in scope:
            return deepcopy(scope[key])
        value = _registration(admission)
        scope[key] = deepcopy(value)
        return value
    finally:
        if token is not None:
            _registration_scope.reset(token)


def _registration(admission):
    root = Path(admission["experiment_directory"])
    raw = (root / "experiment.json").read_bytes()
    require(sha_bytes(raw) == admission["experiment_sha256"], "registration_changed", "Frozen experiment differs")
    value = strict_json(raw)
    if value.get("schema") == "harness-B-network-restart-registration-v1":
        from .B_network_restart import validate_registration
        return validate_registration(value, root)
    if value.get("schema") == "harness-B-model-switch-registration-v1":
        from .B_model_switch import validate_registration
        return validate_registration(value, root)
    if value.get("schema") == "harness-model-switch-registration-v1":
        from .model_switch import validate_registration
        validate_registration(value, root)
        from .amendment import amendment_for
        amendment_for(value)  # Validate any separate, explicitly authorized control revision.
        return value
    require(value["full_B_new_run_limit"] == 1, "experiment_caps", "Only one fresh B run is authorized")
    if value.get("schema") in ("harness-p5-registration-v2", "harness-p5-registration-v3", "harness-p5-registration-v4", "harness-p5-registration-v5", "harness-p5-registration-v6", "harness-p5-registration-v7", "harness-p5-registration-v8", "harness-p5-registration-v9"):
        grant = continuation_authorization(value["authorization"])
        if value["schema"] in ("harness-p5-registration-v7", "harness-p5-registration-v8", "harness-p5-registration-v9"):
            require(Path(value["experiment_directory"]).resolve() == root.resolve() and value["recovery_policy"] == grant["recovery_policy"],
                    "recovery_policy", "Shared recovery account or policy changed")
        require(value["caps"] == grant["caps"] and
                ((value["schema"] in ("harness-p5-registration-v4", "harness-p5-registration-v5", "harness-p5-registration-v6", "harness-p5-registration-v7", "harness-p5-registration-v8", "harness-p5-registration-v9")) == (grant["caps"] in (UNCAPPED_MODEL_CAPS, BOUNDED_TIME_CAPS, PRESENTATION_TIME_CAPS))) and
                ((value["schema"] == "harness-p5-registration-v5") == (grant["schema"] == "harness-user-continuation-20261014-v3")) and
                ((value["schema"] == "harness-p5-registration-v6") == (grant["schema"] == "harness-user-continuation-20261014-v4")) and
                ((value["schema"] == "harness-p5-registration-v7") == (grant["schema"] == "harness-user-continuation-20261014-v5")) and
                ((value["schema"] == "harness-p5-registration-v8") == (grant["schema"] == "harness-user-continuation-20261014-v6")) and
                ((value["schema"] == "harness-p5-registration-v9") == (grant["schema"] == "harness-user-continuation-20261014-v7")) and
                (value["schema"] in ("harness-p5-registration-v3", "harness-p5-registration-v4", "harness-p5-registration-v5", "harness-p5-registration-v6", "harness-p5-registration-v7", "harness-p5-registration-v8", "harness-p5-registration-v9") or value["prior_cost_evidence"] == grant["prior_cost_evidence"]),
                "experiment_caps", "Registration differs from the user continuation grant")
    else:
        require(value["caps"] == CAPS and "prior_cost_evidence" not in value,
                "experiment_caps", "Original registration cannot extend caps or chain accounts")
    if value.get("schema") == "harness-p5-registration-v9":
        require(value.get("execution_order") == PRESENTATION_EXECUTION_ORDER,
                "execution_order", "Frozen execution order changed")
    return value


def sealed_prior(value, *, recovered=None):
    """Recompute every retained closed cohort once; no omitted ancestor or reset.

    Aggregation is accounting only: previous failed gates never become successful
    samples in a new cohort. Closed intervals add without offline repair gaps.
    """
    if value.get("schema") == "harness-B-network-restart-registration-v1":
        from .B_network_restart import carried_costs
        return carried_costs(value)
    if value.get("schema") == "harness-B-model-switch-registration-v1":
        from .B_model_switch import carried_costs
        return carried_costs(value)
    if value.get("schema") == "harness-model-switch-registration-v1":
        from .model_switch import carried_costs
        return carried_costs(value)
    if "prior_cost_evidence" not in value:
        require("authorization" not in value, "carry_ancestor_missing", "Continuation cannot omit its predecessor ledger")
        return empty_usage(), 0, set()
    recovered = {} if recovered is None else recovered
    seen, cohorts, dependencies = set(), set(), set()
    exceptions = {(e["run_id"], e["attempt_id"]): e for e in historical_exceptions(value)}
    used_exceptions = set()
    def key(ref): return (str(Path(ref["path"]).resolve()), ref["sha256"])
    def visit(ref):
        identity = key(ref)
        require(identity not in seen, "carry_duplicate", "Repeated or cyclic cost dependency")
        seen.add(identity)
        snapshot = checked_file(ref)
        if snapshot.get("schema") == "harness-prior-cost-aggregate-v2":
            total, starts, ids = empty_usage(), 0, set()
            require(snapshot["cohorts"], "carry_chain", "An aggregate cannot erase prior costs")
            for child in snapshot["cohorts"]:
                usage, count, child_ids = visit(child)
                require(not ids & child_ids, "carry_duplicate", "Run occurs in multiple cohorts")
                ids.update(child_ids); starts += count
                for group in total:
                    for field in total[group]: total[group][field] += usage[group][field]
            require(total == snapshot["cumulative_usage"] and starts == snapshot["full_B_starts_used"],
                    "carry_totals", "Aggregated raw costs differ")
            return total, starts, ids
        cohort = key(snapshot["original_registration"])
        require(cohort not in cohorts, "carry_duplicate", "Registration counted more than once")
        cohorts.add(cohort)
        usage, starts, ids, dependency = _closed_cohort(snapshot, exceptions, used_exceptions, recovered)
        if dependency: dependencies.add(key(dependency))
        return usage, starts, ids
    result = visit(value["prior_cost_evidence"])
    if "authorization" in value:
        dependencies.add(key(continuation_authorization(value["authorization"])["prior_cost_evidence"]))
    require(dependencies <= seen, "carry_ancestor_missing", "A predecessor's prior costs were omitted")
    require(used_exceptions == set(exceptions), "unknown_exception", "Authorized historical attempt is missing from carried evidence")
    return result


def _closed_cohort(snapshot, exceptions=None, used_exceptions=None, recovered=None):
    recovered = {} if recovered is None else recovered
    exceptions = exceptions or {}
    used_exceptions = used_exceptions if used_exceptions is not None else set()
    results = empty_usage()
    from .evaluation import Evidence, audit_cost
    previous = checked_file(snapshot["original_registration"])
    require((previous.get("schema") == "harness-p5-registration-v1" and "prior_cost_evidence" not in previous and previous["caps"] == CAPS) or
            (previous.get("schema") in ("harness-p5-registration-v2", "harness-p5-registration-v3") and previous["caps"] == CONTINUATION_CAPS) or
            (previous.get("schema") in ("harness-p5-registration-v4", "harness-p5-registration-v5", "harness-p5-registration-v6", "harness-p5-registration-v7") and previous["caps"] == UNCAPPED_MODEL_CAPS) or
            (previous.get("schema") == "harness-p5-registration-v8" and previous["caps"] == BOUNDED_TIME_CAPS) or
            (previous.get("schema") == "harness-p5-registration-v9" and previous["caps"] == PRESENTATION_TIME_CAPS),
            "carry_chain", "Unsupported or inconsistent predecessor registration")
    root = Path(snapshot["original_registration"]["path"]).parent
    registration({"experiment_directory": str(root), "experiment_sha256": snapshot["original_registration"]["sha256"]})
    records = account_records(root)
    from .recovery import cohort_recoveries
    shared_recoveries = cohort_recoveries(previous)
    by_case = {r[0]: r for r in records}
    expected = snapshot["sealed_runs"]
    require(len(expected) == len(records) == len({r["run_id"] for r in expected}) and
            {r["case_id"] for r in expected} == set(by_case), "carry_runs", "Prior account added, omitted or duplicated a run")
    clocks, ids = {}, set()
    for row in expected:
        case, group, run_id, directory, created = by_case[row["case_id"]]
        require(run_id == row["run_id"] and group == previous["cases"][case]["group"], "carry_identity", case)
        require(Path(row["boundary"]["path"]).resolve() == Path(directory).resolve() / "evidence_manifest.json" and
                Path(row["closure"]["path"]).resolve() == Path(directory).resolve() / "audit_closure.json", "carry_path", case)
        checked_file(row["boundary"])
        closure = checked_file(row["closure"])
        evidence = Evidence(directory, row["boundary"]["sha256"])
        require(evidence.manifest["run_id"] == run_id and evidence.manifest["created_epoch"] == created and
                evidence.value["head"]["phase"] == "CLOSED" and closure["evidence_sha256"] == evidence.sha256,
                "carry_identity", "Predecessor must be closed with a matching audit boundary")
        require(evidence.manifest["admission"]["experiment_sha256"] == snapshot["original_registration"]["sha256"],
                "carry_identity", "Run belongs to a different original registration")
        cost = audit_cost(evidence)
        require(cost == row["costs"] and cost["pending_attempts"] == 0,
                "carry_unknown", "Prior costs differ or are unsettled")
        unknown = [a for a in evidence.rows("attempts").values()
                   if a["channel"] == "codex" and a["status"] not in ("reserved", "not_sent") and a.get("usage") is None]
        require(len(unknown) == cost["unknown_usage"], "carry_unknown", "Unknown count differs from exact records")
        from .recovery import validate_recoveries
        bounded_proofs = validate_recoveries(evidence)
        require(bounded_proofs == shared_recoveries.get(run_id, (group, {}))[1],
                "carry_live_change", "Sealed recovery proofs differ from the shared closed account")
        for attempt in unknown:
            identity = (run_id, attempt["attempt_id"])
            if identity not in exceptions and attempt["attempt_id"] in bounded_proofs:
                require(identity not in recovered, "carry_duplicate", "Bounded failure counted twice")
                recovered[identity] = {"group": group, "proof": bounded_proofs[attempt["attempt_id"]], "boundary": row["boundary"]}
                continue
            require(identity in exceptions and identity not in used_exceptions, "carry_unknown", "No exception for this exact historical unknown")
            item = exceptions[identity]
            require(item["original_registration"] == snapshot["original_registration"] and item["boundary"] == row["boundary"] and
                    item["attempt_record_sha256"] == evidence.value["records"]["attempts"][attempt["attempt_id"]] and
                    item["events_sha256"] == attempt["transport"]["events_ref"] and item["group"] == group and
                    attempt["status"] == "responded" and cost["valid"] is False and row.get("accepted") is False,
                    "unknown_exception_binding", "Historical failure/attempt/evidence must match the authorization exactly")
            validate_closed_unknown(evidence, attempt)
            used_exceptions.add(identity)
        # A late mutation to the live ledger must not hide unsealed consumption.
        db = sqlite3.connect(f"file:{Path(directory) / 'events.sqlite3'}?mode=ro", uri=True)
        try:
            live = dict(db.execute("SELECT key,ref FROM records WHERE namespace='attempts'"))
            require(live == evidence.value["records"].get("attempts", {}), "carry_live_change", "Prior attempts changed after seal")
        finally:
            db.close()
        meter = results[group]
        meter["attempts"] += cost["actual_attempts"]
        meter["tokens"] += cost["total_reported_tokens"]
        meter["model_seconds"] += cost["model_seconds"]
        meter["unknown_usage"] += cost["unknown_usage"]
        ended = closure["completed_epoch"]
        first, last = clocks.get(group, (created, ended))
        clocks[group] = min(first, created), max(last, ended)
        ids.add(run_id)
    finish_usage(results, clocks)
    full_starts = sum(r[1] == "B3600" for r in records)
    require(results == snapshot["cumulative_usage"] and full_starts == snapshot["full_B_starts_used"],
            "carry_totals", "Recomputed prior usage differs from the sealed carry record")
    return results, full_starts, ids, previous.get("prior_cost_evidence")


def validate_closed_unknown(evidence, attempt, *, allow_guarded_timeout=None):
    """Verify this failed process ended; absence of telemetry is NOT zero usage."""
    transport = attempt["transport"]
    if transport["timed_out"] and allow_guarded_timeout is None:
        from .recovery import policy_for
        policy = policy_for(evidence.manifest.get("admission"))
        allow_guarded_timeout = bool(policy and 'guarded_timeout' in policy['allowed_failure_kinds'])
    guarded_timeout = transport["timed_out"] and allow_guarded_timeout is True
    events = [strict_json(line) for line in evidence.raw(transport["events_ref"]).splitlines() if line.strip()]
    require(not any(e.get("type") == "turn.completed" for e in events) and
            (any(e.get("type") == "turn.failed" for e in events) or guarded_timeout) and transport["channel_valid"] is False and
            transport["automatic_retries"] == 0 and not transport["native_tool_events"],
            "unknown_exception_transport", "Only the retained terminated failed request is exempt")
    require(not any(e.get("type") in ("item.started", "item.completed", "item.updated") and
                    e.get("item", {}).get("type") not in ("agent_message", "reasoning", "error") for e in events),
            "unknown_exception_transport", "Historical request used an unauthorized native tool")
    guard = evidence.get(transport["guard_ref"])
    originals = transport["original_guard_files"]
    require(originals == guard["files_sha256"], "unknown_exception_guard", "Guard originals differ")
    docs = {name: strict_json(evidence.raw(ref)) for name, ref in originals.items() if name.endswith(".json")}
    spec, receipt, waited = (docs[name] for name in ("spec.json", "receipt.json", "parent_observed.json"))
    if transport["timed_out"]:
        require(guarded_timeout and guard['timed_out'] is True and receipt['timed_out'] is True and
                receipt['stop_reason'] == 'deadline' and receipt['owner_eof'] is False and
                receipt['group_term_sent'] is True and receipt['final_group_signal'] == 9 and
                waited['observed_monotonic_seconds'] >= spec['deadline_monotonic_seconds'] and
                not any(e.get('item', {}).get('type') == 'agent_message' for e in events),
                'unknown_exception_guard', 'Only authorized deadline termination without an answer may continue')
    require(spec["call_id"] == receipt["call_id"] == attempt["attempt_id"] and spec["argv"] == evidence.get(transport["command_ref"]) and
            transport["original_input_files"] == spec["input_files_sha256"] and
            spec["input_files_sha256"]["prompt.txt"] == attempt["prompt_ref"] and
            spec["input_files_sha256"]["schema.json"] == attempt["schema_ref"],
            "unknown_exception_guard", "Process identity or input differs")
    require(receipt["output_files_sha256"]["events.jsonl"] == transport["events_ref"] and
            receipt["output_files_sha256"]["final.txt"] is None and evidence.raw(attempt["raw_ref"]) == b"" and
            receipt["command_returncode"] == transport["returncode"] != 0 and guard["lifecycle_complete"] is True and
            waited["wait_completed"] is True and
            waited["observed_monotonic_seconds"] - spec["begun_monotonic_seconds"] == attempt["duration_seconds"] == guard["parent_wait_wall_seconds"],
            "unknown_exception_guard", "Failed process lifecycle or duration is not closed")


def account_records(root):
    path = Path(root) / "account.sqlite3"
    if not path.exists():
        return []
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return db.execute("SELECT case_id,group_name,run_id,directory,created FROM runs").fetchall()
    finally:
        db.close()


def empty_usage():
    return {g: {"attempts": 0, "tokens": 0, "model_seconds": 0, "wall_seconds": 0, "unknown_usage": 0,
                "reserved_tokens": 0, "pending": 0} for g in CAPS}


def finish_usage(results, clocks):
    for group, (start, end) in clocks.items():
        results[group]["wall_seconds"] = end - start
    for key in results["combined"]:
        results["combined"][key] = results["micro"][key] + results["B3600"][key]


def validate_admission(admission, fingerprint, config, initial):
    from . import capacity_pilot
    if capacity_pilot.is_pilot(admission):
        return capacity_pilot.validate_admission(admission, fingerprint, config, initial)
    require(type(admission) is dict, "P5_admission", "Real execution requires frozen G0-G4 admission")
    reg = registration(admission)
    sealed_prior(reg)
    grant = continuation_authorization(reg["authorization"]) if "authorization" in reg else {}
    require(config["unknown_usage_policy"] == grant.get("unknown_usage_policy", "freeze_new_calls"),
            "recovery_policy", "Run policy must match the frozen user authorization")
    from .amendment import registered_source
    gates = registered_source(reg, fingerprint)
    require(all(gates["gates"][g] == "pass" for g in ("G0", "G1", "G2", "G3", "G4")), "engineering_gate", "All G0-G4 must pass")
    require(gates["fingerprint_sha256"] == fingerprint["sha256"], "gate_version", "Tests were for a different source version")
    group, case = admission["group"], admission["case_id"]
    require(group in ("micro", "B3600"), "experiment_group", group)
    entry = reg["cases"][case]
    require(entry["group"] == group and entry["config_sha256"] == digest(config), "case_config", "Unregistered configuration")
    require(entry["initial_state_sha256"] == (digest(initial["state"]) if initial else None), "case_initial", "Unregistered initial state")
    if initial is not None:
        require(entry["initial_trace_sha256"] == digest(initial["trace"]), "case_initial", "Unregistered physical prefix")
    require(config["arm"] == "B", "P5_arm", "P5 authorizes B only")
    if group == "B3600":
        gate_path = Path(admission["experiment_directory"]) / "micro_gate.json"
        require(gate_path.exists() and strict_json(gate_path.read_bytes())["pass"], "micro_gate", "No passing registered microbenchmark gate")
        from .amendment import validate_advisory_B_gate
        validate_advisory_B_gate(reg, strict_json(gate_path.read_bytes()))
        require(initial is None and config["window_seconds"] == 3600, "cold_start", "One cold B hour only")
    for field in reg["caps"][group]:
        limit, cap = config["limits"][field], reg["caps"][group][field]
        require(cap is None or (limit is not None and limit <= cap), "case_budget", "Run cap exceeds its phase")
    require(admission["cli_sha256"] == reg["cli_sha256"] and admission["cli_binary"] == reg["cli_binary"], "cli_freeze", "CLI differs from preregistration")


def register_run(runtime):
    from . import capacity_pilot
    if capacity_pilot.is_pilot(runtime.manifest.get('admission')):
        return capacity_pilot.register_run(runtime)
    admission = runtime.manifest["admission"]
    with experiment_lock(admission):
        reg = registration(admission)
        _, prior_full_starts, prior_ids = sealed_prior(reg)
        require(runtime.manifest["run_id"] not in prior_ids, "carry_duplicate", "Run identity already consumed")
        root = Path(admission["experiment_directory"])
        db = sqlite3.connect(root / "account.sqlite3")
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("CREATE TABLE IF NOT EXISTS runs(case_id TEXT PRIMARY KEY, group_name TEXT, run_id TEXT UNIQUE, directory TEXT, created REAL)")
            with db:
                require(db.execute("SELECT 1 FROM runs WHERE case_id=?", (admission["case_id"],)).fetchone() is None,
                        "case_already_started", "No second new run or replacement fragment")
                if admission["group"] == "B3600":
                    require(prior_full_starts + db.execute("SELECT COUNT(*) FROM runs WHERE group_name='B3600'").fetchone()[0] < reg["full_B_new_run_limit"], "full_run_quota", "The one fresh B run has already started")
                db.execute("INSERT INTO runs VALUES(?,?,?,?,?)", (admission["case_id"], admission["group"], runtime.manifest["run_id"], str(runtime.store.path), runtime.manifest["created_epoch"]))
        finally:
            db.close()


def cumulative_usage(admission):
    root = Path(admission["experiment_directory"])
    reg = registration(admission)
    prior, _, prior_ids = sealed_prior(reg)
    records = account_records(root)
    results = empty_usage()
    clocks = {}
    for case, group, run_id, directory, created in records:
        require(run_id not in prior_ids, "carry_duplicate", "Run identity appears in both cohorts")
        directory = Path(directory)
        run = sqlite3.connect(f"file:{directory / 'events.sqlite3'}?mode=ro", uri=True)
        def get(ref):
            raw = zlib.decompress((directory / "objects" / (ref + ".z")).read_bytes())
            require(sha_bytes(raw) == ref, "account_evidence", "Corrupt account object")
            return strict_json(raw)
        manifest_ref = run.execute("SELECT ref FROM records WHERE namespace='manifest' AND key='run'").fetchone()[0]
        require(get(manifest_ref)["run_id"] == run_id, "account_identity", "Registered run was replaced")
        attempts = [get(row[0]) for row in run.execute("SELECT ref FROM records WHERE namespace='attempts'")]
        run.close()
        meter = results[group]
        for a in attempts:
            if a["channel"] != "codex" or a["status"] == "not_sent":
                continue
            if a["status"] in ("reserved", "started", "unknown"):
                meter["pending"] += 1
                meter["reserved_tokens"] += a["reserved_tokens"]
            if a["status"] == "reserved":
                continue
            meter["attempts"] += 1
            meter["unknown_usage"] += a.get("usage") is None
            if a.get("usage") is not None:
                meter["tokens"] += a["usage"]["input_tokens"] + a["usage"]["output_tokens"]
            meter["model_seconds"] += a["duration_seconds"]
        from .recovery import LiveEvidence
        from .transport_requalification import diagnostic_usage
        diagnostic = diagnostic_usage(LiveEvidence(directory),reg)
        for key in ("attempts","tokens","model_seconds","unknown_usage"):
            meter[key] += diagnostic[key]
        closure = directory / "audit_closure.json"
        ended = strict_json(closure.read_bytes())["completed_epoch"] if closure.exists() else time.time()
        first, last = clocks.get(group, (created, ended))
        clocks[group] = (min(first, created), max(last, ended))
    finish_usage(results, clocks)
    for group in results:
        for key in results[group]:
            results[group][key] += prior[group][key]
    return results


def check_experiment_budget(runtime, reserve, *, budget=None):
    from . import capacity_pilot
    if capacity_pilot.is_pilot(runtime.manifest.get('admission')):
        return capacity_pilot.check_budget(runtime)
    admission = runtime.manifest["admission"]
    usage = cumulative_usage(admission)
    reg = registration(admission)
    from .wall_budget import shared_caps
    caps = shared_caps(reg, budget if budget is not None else runtime.wall_budget())
    status = resource_status(reg, usage)
    timeout = runtime.config["model"]["timeout_seconds"]
    cleanup = runtime.config["limits"]["cleanup_seconds"]
    from .recovery import LiveEvidence
    from .transport_requalification import diagnostic_usage
    diagnostic = diagnostic_usage(LiveEvidence(runtime.store.path),reg)
    if diagnostic['attempts']:
        local = runtime.usage()
        local_limits = (budget if budget is not None else runtime.wall_budget())['limits']
        require(within_cap(local['actual_model_attempts']+diagnostic['attempts']+1,local_limits['attempts']) and
                within_cap(local['input_tokens']+local['output_tokens']+diagnostic['tokens']+reserve,local_limits['tokens']) and
                local['model_seconds']+diagnostic['model_seconds']+timeout<=local_limits['model_seconds'],
                'experiment_budget','Business and diagnostic calls share the original run limits')
    for group in (admission["group"], "combined"):
        current, cap = usage[group], caps[group]
        require(status["unexempt_unknown_usage"][group] == 0 and current["pending"] == 0, "experiment_unknown", "Shared account has an unsettled attempt")
        require(within_cap(current["attempts"] + 1, cap["attempts"]) and within_cap(current["tokens"] + reserve, cap["tokens"]), "experiment_budget", "Shared attempts/tokens exhausted")
        require(current["model_seconds"] + timeout <= cap["model_seconds"] and current["wall_seconds"] + timeout + cleanup < cap["wall_seconds"], "experiment_time", "Shared call plus cleanup cannot fit")
    return usage
