"""Bounded transport recovery with durable proofs, never business-action replay.

The CLI itself still makes exactly one attempt. Only a terminated failed process
with no final output/native action may get a new attempt after a persisted delay.
Missing token telemetry stays missing in both live accounts and sealed audits.
"""
from pathlib import Path
import sqlite3
import time
import zlib

from .contracts import HarnessError, digest, require, sha_bytes, strict_json, within_cap


class LiveEvidence:
    """Read-only object view; also usable while the owner holds its SQLite lock."""
    def __init__(self, directory):
        self.path = Path(directory)
        with sqlite3.connect(f"file:{self.path / 'events.sqlite3'}?mode=ro", uri=True) as db:
            self.records = {}
            for namespace, key, ref in db.execute("SELECT namespace,key,ref FROM records"):
                self.records.setdefault(namespace, {})[key] = ref
        self.manifest = self.get(self.records["manifest"]["run"])

    def raw(self, ref):
        raw = zlib.decompress((self.path / "objects" / (ref + ".z")).read_bytes())
        require(sha_bytes(raw) == ref, "recovery_evidence", "Corrupt object")
        return raw

    def get(self, ref):
        return strict_json(self.raw(ref))

    def rows(self, namespace):
        return {k: self.get(ref) for k, ref in self.records.get(namespace, {}).items()}


def policy_for(admission):
    from .experiment import registration, continuation_authorization
    if not admission:
        return None
    reg = registration(admission)
    if reg.get("schema") not in ("harness-p5-registration-v7", "harness-p5-registration-v8", "harness-p5-registration-v9", "harness-model-switch-registration-v1", "harness-B-model-switch-registration-v1", "harness-B-network-restart-registration-v1"):
        return None
    from .amendment import effective_policy
    return effective_policy(reg, continuation_authorization(reg["authorization"])["recovery_policy"])


def failure_kind(evidence, attempt):
    from .experiment import validate_closed_unknown
    require(attempt["channel"] == "codex" and attempt["status"] == "responded" and attempt["usage"] is None,
            "recovery_ineligible", "Only terminated unprocessed failures with missing telemetry qualify")
    validate_closed_unknown(evidence, attempt)
    transport = attempt["transport"]
    if transport["timed_out"]:
        # The validator proves explicit authorization, complete process cleanup,
        # no native action, no retained answer, and deadline (not ownership loss).
        return "guarded_timeout"
    events = [strict_json(line) for line in evidence.raw(transport["events_ref"]).splitlines() if line.strip()]
    require(not any(e.get("item", {}).get("type") == "agent_message" for e in events),
            "recovery_ineligible", "A retained model answer must be reconciled, not regenerated")
    errors = [e["error"]["message"] for e in events if e.get("type") == "turn.failed"]
    require(len(errors) == 1, "recovery_ineligible", "One explicit terminal failure required")
    message = errors[0]
    if message == "Selected model is at capacity. Please try a different model.":
        return "capacity"
    if message == "Connection failed: error sending request":
        return "connection"
    if message == "stream disconnected before completion: Transport error: network error: error decoding response body":
        return "stream_disconnect"
    from .transport_error_alias import MESSAGE, authorize_alias
    if message == MESSAGE:
        return authorize_alias(evidence, attempt)
    raise HarnessError("recovery_ineligible", "Unregistered error; no automatic continuation")


def validate_recoveries(evidence):
    """Recompute every exception from original process evidence and timestamps."""
    records = evidence.rows("transport_recoveries")
    if not records:
        return {}
    admission = evidence.manifest.get("admission")
    policy = policy_for(admission)
    require(policy is not None and evidence.manifest["config"]["unknown_usage_policy"] == "bounded_terminated_failures",
            "recovery_authorization", "No bounded recovery grant")
    from .experiment import registration
    reg = registration(admission)
    return _validate_recovery_records(evidence, records, policy, reg)


def _validate_recovery_records(evidence, records, policy, reg):
    """Check each original proof using this call's already validated cohort.

    The caller must validate registration and policy first. Nothing is cached
    between calls: changed registrations, records and costs remain observable.
    """
    from .amendment import policy_for_record
    admission = evidence.manifest.get("admission") or {}
    require(admission.get("experiment_sha256") == digest(reg)
            and Path(admission.get("experiment_directory", "")).resolve()
            == Path(reg["experiment_directory"]).resolve()
            and evidence.manifest["config"]["unknown_usage_policy"] == "bounded_terminated_failures",
            "recovery_identity", "Recovery evidence differs from the validated cohort")
    attempts = sorted((a for a in evidence.rows("attempts").values()
                       if a["channel"] == "codex" and a["status"] != "not_sent"), key=lambda a: a["index"])
    require(set(records) <= {a["attempt_id"] for a in attempts}, "recovery_evidence", "Exception has no attempt")
    from .transport_requalification import validate_records, QUIET_SECONDS
    requalified = validate_records(evidence, reg, policy)
    current_policy = policy
    result, ordinals = {}, set()
    for index, attempt in enumerate(attempts):
        aid = attempt["attempt_id"]
        if aid not in records:
            continue
        row = records[aid]
        policy = policy_for_record(reg, current_policy, aid, row)
        previous = result.get(attempts[index-1]["attempt_id"]) if index else None
        ordinal = previous["request_failure_ordinal"] + 1 if previous and previous["attempt_id"] not in requalified else 1
        closed = requalified.get(aid)
        require((ordinal <= policy["max_retries_per_request"] or (closed is not None and ordinal == 3)) and row["request_failure_ordinal"] == ordinal,
                "recovery_limit", "Consecutive failure allowance exceeded or reset")
        require(row["attempt_id"] == aid and row["business_action_replayed"] is False and
                row["attempt_sha256"] == digest(attempt) and row["context_ref"] == attempt["context_ref"] and
                row["failure_kind"] == failure_kind(evidence, attempt) and row["usage"] is None and
                row["policy_sha256"] == digest(policy), "recovery_evidence", "Recovery differs from original failure/policy")
        require(row.get("closed_for_requalification") == (digest(closed) if closed else None),
                "recovery_requalification", "Closed burst must bind its explicit transition")
        require(row["not_before_epoch"] == attempt["finished_epoch"] + (QUIET_SECONDS if closed else policy["cooldown_seconds"][ordinal-1]),
                "recovery_cooldown", "Persisted cooldown changed")
        require(type(row["cohort_failure_ordinal"]) is int and row["cohort_failure_ordinal"] >= 1 and
                within_cap(row["cohort_failure_ordinal"], policy["max_failures_per_cohort"]) and
                row["cohort_failure_ordinal"] not in ordinals, "recovery_limit", "Invalid or duplicated cohort allowance")
        ordinals.add(row["cohort_failure_ordinal"])
        if index + 1 < len(attempts):
            require(attempts[index+1]["reserved_epoch"] >= row["not_before_epoch"],
                    "recovery_cooldown", "New attempt started before the cooldown expired")
        result[aid] = row
    return result


def cohort_recoveries(reg):
    from .experiment import account_records, continuation_authorization, registration
    if reg.get("schema") not in ("harness-p5-registration-v7", "harness-p5-registration-v8", "harness-p5-registration-v9", "harness-model-switch-registration-v1", "harness-B-network-restart-registration-v1"):
        return {}
    # Validate the cohort once before checking all of its runs. Re-entering
    # registration for every run recursively revalidates the same ancestors.
    # This is scoped to this invocation, never reused for a later admission.
    reg = registration({"experiment_directory": reg["experiment_directory"],
                        "experiment_sha256": digest(reg)})
    from .amendment import effective_policy
    policy = effective_policy(reg, continuation_authorization(reg["authorization"])["recovery_policy"])
    result, ordinals = {}, []
    for case, group, run_id, directory, _ in account_records(reg["experiment_directory"]):
        view = LiveEvidence(directory)
        require(view.manifest["run_id"] == run_id and view.manifest["admission"]["experiment_sha256"] == digest(reg),
                "recovery_identity", "Recovery belongs to another run or registration")
        records = view.rows("transport_recoveries")
        rows = _validate_recovery_records(view, records, policy, reg) if records else {}
        ordinals.extend(r["cohort_failure_ordinal"] for r in rows.values())
        result[run_id] = (group, rows)
    from .model_switch import carried_recovery_count
    offset = carried_recovery_count(reg)
    require(sorted(ordinals) == list(range(offset+1, offset+len(ordinals)+1)) and within_cap(offset+len(ordinals), policy["max_failures_per_cohort"]),
            "recovery_limit", "Shared failure allowance omitted, duplicated or exceeded")
    return result


def schedule_recovery(runtime, attempt_id):
    """Caller owns the experiment lock; immutable decision survives a restart."""
    from .experiment import registration
    if runtime.config["unknown_usage_policy"] != "bounded_terminated_failures":
        return None
    policy = policy_for(runtime.manifest["admission"])
    if policy is None:
        return None
    view = LiveEvidence(runtime.store.path)
    existing = validate_recoveries(view)
    if attempt_id in existing:
        return existing[attempt_id]
    attempts = sorted((a for a in view.rows("attempts").values()
                       if a["channel"] == "codex" and a["status"] != "not_sent"), key=lambda a: a["index"])
    require(attempts and attempts[-1]["attempt_id"] == attempt_id, "recovery_order", "Only the latest failure may continue")
    attempt = attempts[-1]
    try:
        kind = failure_kind(view, attempt)
    except (HarnessError, KeyError, TypeError, ValueError):
        return None
    previous = existing.get(attempts[-2]["attempt_id"]) if len(attempts) > 1 else None
    reg = registration(runtime.manifest["admission"])
    from .transport_requalification import validate_records
    requalified = validate_records(view, reg, policy)
    ordinal = previous["request_failure_ordinal"] + 1 if previous and previous["attempt_id"] not in requalified else 1
    from .model_switch import carried_recovery_count
    used = carried_recovery_count(reg) + sum(len(rows) for _, rows in cohort_recoveries(reg).values())
    if ordinal > policy["max_retries_per_request"] or not within_cap(used + 1, policy["max_failures_per_cohort"]):
        return None
    row = {"attempt_id": attempt_id, "attempt_sha256": digest(attempt), "context_ref": attempt["context_ref"],
           "failure_kind": kind, "request_failure_ordinal": ordinal, "cohort_failure_ordinal": used + 1,
           "not_before_epoch": attempt["finished_epoch"] + policy["cooldown_seconds"][ordinal-1],
           "policy_sha256": digest(policy), "usage": None, "business_action_replayed": False}
    with runtime.store.transaction():
        runtime.store.record("transport_recoveries", attempt_id, row)
        runtime.store.event("transport_recovery_scheduled", row)
    return row


def current_recoveries(runtime):
    return validate_recoveries(LiveEvidence(runtime.store.path))


def wait_for_cooldown(runtime):
    """Interruptible host wait; wall-clock budgets include the entire cooldown."""
    rows = current_recoveries(runtime)
    not_before = max((r["not_before_epoch"] for r in rows.values()), default=0)
    while time.time() < not_before:
        runtime.check_admission()
        time.sleep(min(1, max(0, not_before-time.time())))
