"""Independent file-only attribution: model evidence -> plan -> trace.

No controller, environment, optimizer, solver, or model transport is imported.
An accurately preserved failed run can pass this evidence audit without being a
successful scheduling run. Missing links produce partial, never certification.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

from .constructor_audit import audit_constructor_ledger, audit_constructor_evidence

VERSION = "smt-fullfab-controller-evidence-audit-v1"
MACHINE_FIELDS = ["machine", "available_at", "current_setup", "min_left", "min_setup", "cascading", "processing_until", "unavailable_intervals"]
TYPE_FIELDS = ["batch_key", "processing_seconds", "occupation_seconds", "transport_seconds", "batch_min", "batch_max", "setup", "setup_time", "terminal"]
OP_FIELDS = ["operation_id", "type_index", "release_time", "predecessor_ids", "priority", "due", "remaining_work_seconds", "eligible_override", "optional_same_machine_as"]
MACHINE_FIELDS_V2 = MACHINE_FIELDS + ["source_index", "machine_extras_index"]
OP_FIELDS_V2 = OP_FIELDS[:8] + ["source_index", "lot_id", "step", "visit", "waiting_since", "operation_extras_index"]
PROBLEM_MIRRORS = ("time", "horizon_end", "scope", "setup_transitions", "min_runs")
V2_IDENTITY = "lot_id, step and visit are explicit columns; operation_id is never parsed"
V2_DICTIONARY_SEMANTICS = "extras.values restores every unencoded field; extras.absent removes missing encoded fields; source_index restores original array order"
SOLVERS = {"global": ("src.smt_fullfab.optimizer", "solve_plan", "fullfab-batch-slots-cross-family-v1"),
           "decomposed": ("src.smt_fullfab.decomposition", "solve_decomposed_plan", "fullfab-family-frontier-cpsat-v1")}
FEASIBLE_STATUSES = {"OPTIMAL", "FEASIBLE", "FEASIBLE_HEURISTIC"}
FEEDBACK_FIELDS = ("solver_status", "objective", "best_bound", "planned_operations", "wall_seconds", "limitations",
                   "global_optimality_claim", "selected_source", "cp_sat", "decomposition_status", "heuristic_families")


def _heuristic_errors(solved, method):
    """Check disclosed provenance, not mathematical feasibility of the plan."""
    if solved.get("solver_status") != "FEASIBLE_HEURISTIC":
        return []
    errors = []
    if solved.get("global_optimality_claim") is not False or solved.get("best_bound") is not None:
        errors.append("heuristic result improperly claims a global bound/optimality")
    if solved.get("nominal_audit", {}).get("valid") is not True:
        errors.append("heuristic result lacks saved nominal feasibility evidence")
    if method == "global":
        if solved.get("selected_source") != "classical_incumbent" or not solved.get("cp_sat", {}).get("status"):
            errors.append("heuristic result lacks explicit incumbent/CP outcome provenance")
        incumbent = solved.get("classical_incumbent", {})
        if incumbent.get("status") != "FEASIBLE_HEURISTIC" or incumbent.get("tasks") != solved.get("plan", {}).get("tasks"):
            errors.append("heuristic plan is not the saved incumbent task sequence")
    elif method == "decomposed":
        local = [row for row in solved.get("family_solves", []) if row.get("response", {}).get("solver_status") == "FEASIBLE_HEURISTIC"]
        expected = [{"wave": row["wave"], "family": row["family"], "cp_sat_status": row["response"].get("cp_sat", {}).get("status")} for row in local]
        if not local or solved.get("heuristic_families") != expected:
            errors.append("decomposed heuristic family disclosure differs from saved local solves")
        for row in local:
            errors.extend("local " + message for message in _heuristic_errors(row["response"], "global"))
    return errors


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _record_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _audit_ledger_admission(ledger, approval):
    """Replay effective authorizations at reservation time, without importing budget."""
    errors, missing, admissions = [], [], {}
    consumed, pending, categories, tokens, unknown, active = 0, {}, Counter(), 0, {}, 0.0
    amendment, waiver_count, approval_seen, solver_used = None, 0, False, Counter()
    research, research_count, registrations, solver_by_registration = None, 0, {}, Counter()
    run_active, run_attempts, run_tokens, run_unknown = Counter(), Counter(), Counter(), {}
    pending_solver, call_registration, previously_used_paths = {}, {}, set()
    recovery_mappings, recovery_closures, recovery_finalizations, call_paths = {}, {}, {}, {}
    def check(ok, message):
        if not ok:
            errors.append(message)
    for row_index, row in enumerate(ledger):
        event = row.get("event")
        if event == "approval":
            approval_seen = row.get("approval") == approval
        elif event == "scoped_limit_waiver":
            waiver_count += 1
            candidate = row.get("amendment", {})
            before = len(errors)
            check(approval_seen, "scoped waiver precedes original approval")
            check(waiver_count == 1, "duplicate scoped waiver cannot reset accounting")
            check(set(candidate) == {"amendment_id", "budget_id", "authorization", "approval_text", "allowed_purpose", "waived_limits", "scenario", "window_seconds"}, "scoped waiver schema differs from narrow approval")
            check(isinstance(candidate.get("amendment_id"), str) and bool(candidate.get("amendment_id", "").strip()) and candidate.get("amendment_id") != approval.get("budget_id"), "invalid scoped amendment identity")
            check(candidate.get("budget_id") == approval.get("budget_id") == "smt-fullfab-stage2-probe-v1", "scoped waiver budget identity mismatch")
            check(candidate.get("authorization") == "approved_by_user" and candidate.get("approval_text") == "豁免次数与用量限制", "scoped waiver lacks exact explicit user approval")
            check(candidate.get("allowed_purpose") == "C", "scoped waiver may only authorize C")
            limits = candidate.get("waived_limits")
            check(isinstance(limits, list) and len(limits) == 3 and set(limits) == {"attempt_count", "reported_tokens", "unknown_usage_admission"}, "scoped waiver changed nonwaived gates")
            check(type(candidate.get("scenario")) is int and candidate.get("scenario") == approval.get("scenario") == 1701 and
                  type(candidate.get("window_seconds")) is int and candidate.get("window_seconds") == approval.get("window_seconds") == 3600, "scoped waiver changed scenario/window")
            check(all(approval.get(key) == value for key, value in {"per_call_timeout_seconds": 180, "total_active_wall_seconds": 2700, "max_solver_requested_seconds_per_arm": 60}.items()), "scoped waiver changed nonwaived time/solver budget")
            check(row.get("original_approval_sha256") == _record_digest(approval), "scoped waiver original approval anchor mismatch")
            check(row.get("unknown_finishes_at_approval") == unknown, "scoped waiver unknown completion evidence anchor mismatch")
            if len(errors) == before:
                amendment = candidate
        elif event == "research_limit_waiver":
            research_count += 1
            candidate = row.get("amendment", {})
            before = len(errors)
            fields = {"amendment_id", "budget_id", "authorization", "approval_text", "allowed_purposes", "waived_limits", "model",
                      "reasoning_effort", "per_call_timeout_seconds", "allowed_stage2_window_seconds", "formal_requires_preregistration"}
            check(approval_seen and research_count == 1, "research waiver must follow approval and cannot reset history")
            check(set(candidate) == fields, "research waiver schema mismatch")
            check(isinstance(candidate.get("amendment_id"), str) and bool(candidate.get("amendment_id", "").strip()) and candidate.get("amendment_id") != approval.get("budget_id"), "research amendment identity invalid")
            check(candidate.get("budget_id") == approval.get("budget_id") == "smt-fullfab-stage2-probe-v1", "research waiver changed study budget identity")
            check(candidate.get("authorization") == "approved_by_user" and candidate.get("approval_text") == "记得将调用次数与额度放开", "research waiver lacks latest explicit user approval")
            check(candidate.get("allowed_purposes") == ["B", "C"] and candidate.get("waived_limits") == ["attempt_count", "reported_tokens", "unknown_usage_admission", "total_active_wall_seconds"], "research waiver has undeclared scope/gates")
            check(candidate.get("model") == "gpt-6-astra" and candidate.get("reasoning_effort") == "medium" and candidate.get("per_call_timeout_seconds") == 180, "research waiver changed retained model/timeout")
            check(candidate.get("allowed_stage2_window_seconds") == [3600, 28800, 86400] and candidate.get("formal_requires_preregistration") is True, "research waiver bypasses stage/formal gate")
            check(row.get("original_approval_sha256") == _record_digest(approval) and row.get("prefix_record_count") == row_index and
                  row.get("prior_ledger_sha256") == _record_digest(ledger[:row_index]), "research waiver prior immutable ledger anchor mismatch")
            if len(errors) == before:
                research = candidate
        elif event == "stage_run_registered":
            r = row.get("registration", {})
            before = len(errors)
            fields = {"registration_id", "amendment_id", "budget_id", "run_id", "arm", "scenario", "window_seconds", "solver_seconds",
                      "wall_seconds", "max_log_bytes", "phase", "formal"}
            check(research is not None, "stage registration precedes research waiver")
            check(set(r) == fields, "stage registration schema mismatch")
            check(r.get("registration_id") == _record_digest({k:v for k,v in r.items() if k != "registration_id"}), "stage registration hash mismatch")
            if research:
                check(r.get("amendment_id") == research["amendment_id"] and r.get("budget_id") == research["budget_id"], "stage registration authority mismatch")
            path = Path(r.get("run_id", "/"))
            expected_parent = "smt_fullfab_development" if r.get("arm") == "A" else "smt_fullfab_stage2"
            check(path.is_absolute() and path == path.resolve() and path.parent.name == expected_parent and path.parent.parent.name == "runs", "stage registration path outside new namespace")
            check(r.get("arm") in ("A", "B", "C") and type(r.get("scenario")) is int and r["scenario"] >= 0 and type(r.get("window_seconds")) is int and r["window_seconds"] in (3600, 28800, 86400), "stage registration arm/scenario/window invalid")
            check(r.get("phase") == "stage2_research" and r.get("formal") is False, "stage registration bypasses formal preregistration")
            check(type(r.get("wall_seconds")) in (int, float) and math.isfinite(r["wall_seconds"]) and r["wall_seconds"] > 0 and
                  type(r.get("max_log_bytes")) is int and r["max_log_bytes"] > 0, "stage registration lacks finite wall/log bounds")
            seconds = r.get("solver_seconds")
            check(type(seconds) in (int, float) and math.isfinite(seconds) and ((r.get("arm") == "B" and seconds == 0) or (r.get("arm") in ("A", "C") and seconds > 0)), "stage registration solver allowance invalid")
            check(str(path) not in registrations and str(path) not in previously_used_paths, "stage registration duplicates or retroactively resets a used run")
            if len(errors) == before:
                registrations[str(path)] = r
        elif event == "recovery_segment_registered":
            m = row.get("mapping", {}); parent = m.get("parent_run_id"); segment = m.get("segment_run_id")
            original = registrations.get(parent); before = len(errors)
            check(original is not None and original.get("arm") == "B", "recovery mapping lacks prior original B registration")
            check(not pending and not pending_solver, "recovery mapping admitted with unresolved attempt")
            check(m.get("recovery_segment_id") == _record_digest({k:v for k,v in m.items() if k != "recovery_segment_id"}), "recovery mapping identity hash mismatch")
            prior = [value for value in recovery_mappings.values() if value.get("parent_run_id") == parent]
            check(not prior, "later recovery segment requires a new certified accepted-prefix chain; unsupported in v1")
            check(segment not in registrations and segment not in recovery_mappings and segment not in previously_used_paths,
                  "recovery mapping duplicates or retroactively relabels an existing path")
            check(m.get("segment_index") == len(prior) + 1 and isinstance(parent, str) and
                  segment == str(Path(parent).with_name(Path(parent).name + f"__recovery_{len(prior)+1:03d}")), "recovery segment sibling sequence mismatch")
            check(all(value["segment_run_id"] in recovery_closures for value in prior), "recovery mapping precedes prior segment closure")
            if original:
                rid = original["registration_id"]
                check(m.get("original_registration") == original and all(m.get(k) == original[k] for k in ("registration_id", "amendment_id", "budget_id", "phase")),
                      "recovery mapping changes original allowance/authority")
                inherited = m.get("inherited", {})
                for key, expected in (("model_attempts", run_attempts[rid]), ("reported_input_output_tokens", run_tokens[rid]),
                                      ("unknown_usage_call_ids", run_unknown.get(rid, [])), ("model_active_seconds", run_active[rid])):
                    check(inherited.get(key) == expected, "recovery inherited prior account mismatch: " + key)
                wall, logs = inherited.get("runner_wall_seconds"), inherited.get("log_bytes")
                check(type(wall) in (int, float) and math.isfinite(wall) and wall >= run_active[rid] and type(logs) is int and logs >= 0,
                      "recovery inherited wall/log evidence invalid")
                if type(wall) in (int, float) and type(logs) is int:
                    expected_remaining = {"runner_wall_seconds": max(0., original["wall_seconds"] - wall),
                        "model_active_seconds": max(0., original["wall_seconds"] - run_active[rid]), "log_bytes": max(0, original["max_log_bytes"] - logs)}
                    check(m.get("remaining") == expected_remaining, "recovery remaining resources reset original account")
                if prior:
                    last = max(prior, key=lambda value: value["segment_index"])
                    c = recovery_closures.get(last["segment_run_id"], {})
                    check(wall == last["inherited"]["runner_wall_seconds"] + c.get("segment_wall_seconds", -1), "recovery omitted previous segment wall time")
            if len(errors) == before:
                recovery_mappings[segment] = m
        elif event == "recovery_segment_finished":
            c = row.get("completion", {}); segment = c.get("segment_run_id"); m = recovery_mappings.get(segment)
            before = len(errors)
            check(m is not None and segment not in recovery_closures, "recovery finish lacks unique preceding mapping")
            check(not pending and not pending_solver, "recovery closes with unresolved attempt")
            check(c.get("finish_id") == _record_digest({k:v for k,v in c.items() if k != "finish_id"}), "recovery finish identity hash mismatch")
            if m:
                check(all(c.get(k) == m[k] for k in ("parent_run_id", "recovery_segment_id", "registration_id")), "recovery finish changes inherited identity")
                ids = [cid for cid, path in call_paths.items() if path == segment]
                check(c.get("segment_model_call_ids") == ids, "recovery close omits/invents model attempts")
                wall = c.get("segment_wall_seconds")
                active_here = sum(r.get("details", {}).get("duration_seconds", 0) for r in ledger[:row_index] if r.get("event") == "finish" and r.get("call_id") in ids)
                reported_active = c.get("segment_model_active_seconds")
                check(type(reported_active) in (int,float) and math.isclose(reported_active, active_here, rel_tol=0, abs_tol=1e-9)
                      and type(wall) in (int, float) and wall + 1e-9 >= active_here,
                      "recovery close omits model activity or wall time")
            if len(errors) == before:
                recovery_closures[segment] = c
        elif event == "recovery_segment_finalized":
            f = row.get("finalization", {}); segment = f.get("segment_run_id"); c = recovery_closures.get(segment); m = recovery_mappings.get(segment)
            before = len(errors)
            check(c is not None and m is not None and segment not in recovery_finalizations, "final recovery closure lacks unique earlier result finish")
            check(f.get("finalization_id") == _record_digest({k:v for k,v in f.items() if k != "finalization_id"}), "recovery finalization identity hash mismatch")
            if c and m:
                check(f.get("finish_id") == c["finish_id"] and f.get("result_sha256") == c["result_sha256"] and
                      all(f.get(k) == m[k] for k in ("parent_run_id", "registration_id", "recovery_segment_id")), "recovery finalization changes inherited result/identity")
                wall, total, logs = f.get("segment_final_wall_seconds"), f.get("cumulative_final_wall_seconds"), f.get("cumulative_log_bytes_including_acceptance")
                check(type(wall) in (int,float) and math.isfinite(wall) and wall >= c["segment_wall_seconds"] and
                      total == m["inherited"]["runner_wall_seconds"] + wall, "recovery finalization omits independent audit wall time")
                check(type(logs) is int and logs >= m["inherited"]["log_bytes"] + c["segment_log_bytes"], "recovery finalization omits prior log evidence")
                if type(total) in (int,float) and type(logs) is int:
                    overrun = total > m["original_registration"]["wall_seconds"] or logs > m["original_registration"]["max_log_bytes"] or c.get("resource_overrun") is True
                    check(f.get("resource_overrun") is overrun and (not f.get("accepted") or not overrun), "over-budget final recovery cannot be accepted")
            if len(errors) == before:recovery_finalizations[segment] = f
        elif event == "reserve":
            check(approval_seen, "model reservation precedes original approval")
            metadata = row.get("metadata", {})
            context = metadata.get("authorization_context") or {}
            purpose = context.get("purpose")
            if purpose is None:
                legacy = Path(row["run_id"])
                if legacy.name == "channel_probe_v1":
                    purpose = "channel_probe"
                elif legacy.parent.name == "B_1701_1h_probe_v1":
                    purpose = "B"
                else:
                    missing.append("unclassified reservation purpose: " + row["call_id"])
            attempt_parent = str(Path(row["run_id"]).resolve().parent)
            recovery = recovery_mappings.get(attempt_parent)
            registered = registrations.get(recovery["parent_run_id"] if recovery else attempt_parent) if research and purpose in ("B", "C") else None
            waived = bool(registered or (amendment and purpose == "C" and not research))
            check(not pending, "new model admitted with an unresolved previous attempt")
            if research and purpose in ("B", "C"):
                check(registered is not None, "research model admission lacks preceding run registration")
                check(not pending_solver, "research model admitted with unresolved solver attempt")
                if registered:
                    rid = registered["registration_id"]
                    check(row.get("registration_id") == rid and row.get("amendment_id") == research["amendment_id"], "research reservation identity differs from registration")
                    check(row.get("phase") == registered["phase"] and purpose == registered["arm"] and context.get("arm") == purpose and
                          context.get("scenario") == registered["scenario"] and context.get("window_seconds") == registered["window_seconds"], "research reservation differs from registered scenario/window/phase")
                    check(metadata.get("model") == research["model"] and metadata.get("reasoning_effort") == research["reasoning_effort"], "research reservation changed model/reasoning effort")
                    timeout = metadata.get("timeout_seconds")
                    check(type(timeout) in (int, float) and math.isfinite(timeout) and 1 <= timeout <= min(180, registered["wall_seconds"] - run_active[rid]), "research timeout exceeds per-call/registered-run time")
                    expected_run = {"attempts": run_attempts[rid], "reported_input_output_tokens": run_tokens[rid], "unknown_completed": run_unknown.get(rid, []), "pending": [], "model_active_seconds": run_active[rid]}
                    check(all(row.get("run_account_before", {}).get(k) == v for k,v in expected_run.items()), "research run_account_before changes prior run consumption")
                    if recovery:
                        check(attempt_parent not in recovery_closures, "model admitted after recovery segment was closed")
                        check(row.get("recovery_segment_id") == recovery["recovery_segment_id"] and row.get("parent_run_id") == recovery["parent_run_id"],
                              "recovery reservation differs from preceding segment mapping")
                        resource = row.get("recovery_resources_before", {})
                        check(resource.get("parent_run_id") == recovery["parent_run_id"] and resource.get("registration_id") == rid,
                              "recovery reservation resource account identity mismatch")
                        check(resource.get("runner_wall_seconds") == recovery["inherited"]["runner_wall_seconds"] and
                              resource.get("remaining_runner_wall_seconds") == recovery["remaining"]["runner_wall_seconds"] and
                              resource.get("remaining_model_active_seconds") == max(0., registered["wall_seconds"] - run_active[rid]),
                              "recovery reservation changes prior resource consumption")
                        active_here = sum(r.get("details", {}).get("duration_seconds", 0) for r in ledger[:row_index] if r.get("event") == "finish" and call_paths.get(r.get("call_id")) == attempt_parent)
                        check(type(timeout) in (int,float) and timeout <= recovery["remaining"]["runner_wall_seconds"] - active_here + 1e-9,
                              "recovery timeout exceeds inherited end-to-end wall allowance")
                        check(type(resource.get("log_bytes")) is int and resource["log_bytes"] >= recovery["inherited"]["log_bytes"] and
                              resource.get("remaining_log_bytes") == max(0, registered["max_log_bytes"] - resource["log_bytes"]) and resource["remaining_log_bytes"] > 0,
                              "recovery reservation omits/exceeds cumulative log allowance")
                    else:
                        check(not any(m["parent_run_id"] == attempt_parent for m in recovery_mappings.values()), "sealed parent admitted a direct new attempt")
                        check(row.get("recovery_segment_id") is None, "recovery identity used before effective mapping")
                    call_registration[row["call_id"]] = rid
            elif not waived:
                check(row.get("amendment_id") is None, "reservation uses absent, premature or wrong-scope amendment")
                check(consumed < approval["max_model_attempts"], "attempt admitted after global cap")
                if purpose in approval.get("allocation", {}):
                    check(categories[purpose] < approval["allocation"][purpose], "attempt admitted after cumulative category cap: " + purpose)
                if "observed_input_output_token_admission_limit" in approval:
                    check(tokens < approval["observed_input_output_token_admission_limit"], "model admitted after observed token limit")
                if "max_completed_unknown_usage" in approval:
                    check(len(unknown) < approval["max_completed_unknown_usage"], "model admitted after unknown-usage stop rule")
            else:
                check(row.get("amendment_id") == amendment["amendment_id"], "C reservation lacks effective amendment identity")
                check(row.get("phase") == "stage2_probe" and type(context.get("scenario")) is int and context["scenario"] == 1701, "C waiver reservation outside scenario/stage")
                check(metadata.get("model") == approval["model"], "C waiver changed approved model")
                timeout = metadata.get("timeout_seconds")
                check(type(timeout) in (int, float) and math.isfinite(timeout) and 1 <= timeout <= min(180, 2700 - active), "C waiver timeout exceeds remaining active/per-call budget")
            if not registered and purpose in ("B", "C") and context:
                check(context.get("arm") == purpose and context.get("window_seconds") == approval["window_seconds"], "reservation purpose/arm/window outside approved scope")
            if not registered and "total_active_wall_seconds" in approval:
                check(active < approval["total_active_wall_seconds"], "model admitted after active-wall admission cap")
            account = row.get("account_before")
            if account is not None:
                expected = {"attempts": consumed, "reported_input_output_tokens": tokens, "unknown_completed": list(unknown), "pending": list(pending), "model_active_seconds": active}
                check(all(account.get(key) == value for key, value in expected.items()), "reservation account_before changed historical consumption")
            admissions[row["call_id"]] = {"purpose": purpose, "waiver_applied": waived, "amendment_id": amendment["amendment_id"] if waived and amendment else None,
                                           "active_seconds_before": active, "timeout_seconds": metadata.get("timeout_seconds"),
                                           "solver_requested_seconds_before_by_arm": dict(solver_used)}
            if registered:
                rid = registered["registration_id"]
                admissions[row["call_id"]].update(amendment_id=research["amendment_id"], waiver_scope="registered_research", registration=registered,
                    run_active_seconds_before=run_active[rid], run_solver_requested_seconds_before=solver_by_registration[rid])
                run_attempts[rid] += 1
            consumed += 1
            categories[purpose] += 1
            pending[row["call_id"]] = row
            call_paths[row["call_id"]] = attempt_parent
            previously_used_paths.add(str(Path(row["run_id"]).resolve().parent))
        elif event == "finish":
            check(row["call_id"] in pending, "model finish lacks a preceding pending reservation")
            pending.pop(row["call_id"], None)
            usage = row.get("details", {}).get("usage", {})
            if all(type(usage.get(key)) is int and usage[key] >= 0 for key in ("input_tokens", "output_tokens")):
                tokens += usage["input_tokens"] + usage["output_tokens"]
                if row["call_id"] in call_registration:run_tokens[call_registration[row["call_id"]]] += usage["input_tokens"] + usage["output_tokens"]
            else:
                unknown[row["call_id"]] = _record_digest(row)
                if row["call_id"] in call_registration:run_unknown.setdefault(call_registration[row["call_id"]], []).append(row["call_id"])
            duration = row.get("details", {}).get("duration_seconds", 0)
            if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
                errors.append("invalid model active duration")
            else:
                active += duration
                if row["call_id"] in call_registration:run_active[call_registration[row["call_id"]]] += duration
        elif event == "solver_reserve":
            check(approval_seen, "solver reservation precedes original approval")
            seconds, purpose = row.get("requested_seconds"), row.get("arm")
            if purpose not in ("A", "C") or type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
                errors.append("invalid solver reservation scope/budget")
            else:
                registered = registrations.get(str(Path(row.get("run_id", "/")).resolve()))
                if research:
                    check(registered is not None, "research solver reservation lacks preceding run registration")
                if registered:
                    rid = registered["registration_id"]
                    check(not pending and not pending_solver, "registered solver admitted with unresolved prior attempt")
                    check(row.get("registration_id") == rid and row.get("amendment_id") == registered["amendment_id"] and purpose == registered["arm"], "solver registration authority mismatch")
                    solver_by_registration[rid] += seconds
                    check(solver_by_registration[rid] <= registered["solver_seconds"] + 1e-9, "solver exceeds unchanged registered run allowance")
                else:
                    check(row.get("registration_id") is None, "solver registration used before it was approved")
                    solver_used[purpose] += seconds
                    check(solver_used[purpose] <= approval.get("max_solver_requested_seconds_per_arm", 0) + 1e-9, "solver reservation exceeds cumulative unchanged arm budget")
                pending_solver[row["call_id"]] = row
                previously_used_paths.add(str(Path(row.get("run_id", "/")).resolve()))
        elif event == "solver_finish":
            check(row["call_id"] in pending_solver, "solver finish lacks preceding pending reservation")
            pending_solver.pop(row["call_id"], None)
    return {"errors": errors, "missing_evidence": missing, "admissions": admissions, "effective_amendment": amendment,
            "effective_research_amendment": research, "registered_runs": registrations,
            "recovery_mappings": recovery_mappings, "recovery_closures": recovery_closures,
            "recovery_finalizations": recovery_finalizations,
            "model_active_seconds": active, "unknown_usage_call_ids": list(unknown)}


def _schema_errors(value, schema, path="output"):
    errors = []
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    checks = {"null": value is None, "boolean": type(value) is bool, "integer": type(value) is int,
              "number": type(value) in (int, float), "string": isinstance(value, str),
              "array": isinstance(value, list), "object": isinstance(value, dict)}
    if types and not any(checks.get(t, False) for t in types):
        return [path + ": schema type mismatch"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(path + ": enum mismatch")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        errors += [path + ": missing " + key for key in schema.get("required", []) if key not in value]
        if schema.get("additionalProperties") is False:
            errors += [path + ": unexpected " + key for key in value if key not in props]
        for key in value.keys() & props.keys():
            errors += _schema_errors(value[key], props[key], path + "." + key)
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errors += _schema_errors(item, schema["items"], f"{path}[{i}]")
    return errors


def _sections(prompt):
    sections = {}
    for name, raw in re.findall(r"\n([A-Z][A-Z_]+)\n([^\n]+)", prompt):
        try:
            sections[name] = json.loads(raw)
        except json.JSONDecodeError:
            pass
    return sections


def _literal_prompt_constants(path):
    """Read literal source strings with AST; never execute/import frozen code."""
    values = {}
    def string(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return string(node.left) + string(node.right)
        raise ValueError("not a literal string expression")
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = string(node.value)
            except ValueError:
                pass
    return values


def _strict_prompt_sections(prompt, prefix):
    if not prompt.startswith(prefix):
        raise ValueError("model instructions differ from frozen controller prompt")
    suffix, position, result = prompt[len(prefix):], 0, {}
    while position < len(suffix):
        match = re.match(r"\n([A-Z][A-Z_]+)\n", suffix[position:])
        if not match:
            raise ValueError("unstructured or unaccounted text in model decision input")
        name = match.group(1)
        position += match.end()
        value, consumed = json.JSONDecoder().raw_decode(suffix[position:])
        if name in result:
            raise ValueError("duplicate model input section")
        result[name] = value
        position += consumed
    return result


def _crop(raw, horizon, scope):
    """Independent literal reconstruction of disclosed observation clipping."""
    plan = json.loads(json.dumps(raw))
    plan["version"] = str(plan["version"])
    plan["scope"] = sorted(scope)
    plan["prediction_horizon_end"] = plan["valid_until"]
    plan["valid_until"] = min(plan["valid_until"], horizon)
    plan["freeze_until"] = min(plan["freeze_until"], plan["valid_until"])
    cut_machines, excluded, kept = set(), [], []
    for task in plan["tasks"]:
        if task["machine"] in cut_machines or task["not_before"] >= plan["valid_until"]:
            cut_machines.add(task["machine"])
            excluded.append(task)
        else:
            kept.append(task)
    plan["unobserved_future_task_ids"] = [task["id"] for task in excluded]
    plan["tasks"] = kept
    kept_ids = {task["id"] for task in kept}
    for hold in plan.get("holds", []):
        hold["until"] = min(hold["until"], plan["valid_until"])
        if hold.get("after_task_id") is not None and hold["after_task_id"] not in kept_ids:
            before = [task for task in kept if task["machine"] == hold["machine"]]
            if before:
                hold["after_task_id"] = before[-1]["id"]
            else:
                hold.pop("after_task_id")
    for mid in sorted(cut_machines):
        before = [task for task in kept if task["machine"] == mid]
        after = before[-1]["id"] if before else None
        existing = next((hold for hold in plan["holds"] if hold["machine"] == mid and hold.get("after_task_id") == after), None)
        if existing:
            existing["until"] = plan["valid_until"]
        else:
            hold = {"machine": mid, "until": plan["valid_until"], "reason": "submitted next planned start lies beyond observation endpoint"}
            if after is not None:
                hold["after_task_id"] = after
            plan["holds"].append(hold)
    merged = {}
    for hold in plan.get("holds", []):
        key = (hold["machine"], hold.get("after_task_id"))
        if key not in merged:
            merged[key] = hold
        else:
            merged[key]["until"] = max(merged[key]["until"], hold["until"])
            merged[key]["reason"] = "union of equivalent projected explicit waits"
    plan["holds"] = list(merged.values())
    plan["observation_projection"] = "ordered-machine-prefix-and-equivalent-waits-v1"
    return plan


def _restore_record(encoded, extras, required):
    if not isinstance(extras, dict) or set(extras) != {"values", "absent"}:
        raise ValueError("extras entry must contain exactly values/absent")
    values, absent = extras["values"], extras["absent"]
    if not isinstance(values, dict) or not isinstance(absent, list) or not all(isinstance(key, str) for key in absent):
        raise ValueError("invalid extras values/absent types")
    if len(set(absent)) != len(absent) or not set(absent) <= set(encoded) or set(absent) & set(required):
        raise ValueError("extras absent list hides required or unencoded fields")
    if set(values) & set(encoded):
        raise ValueError("extras values overwrite encoded source fields")
    # Deleted source values are represented by null, never by unaccounted advice.
    if any(encoded[key] is not None for key in absent):
        raise ValueError("absent source fields have non-null encoded values")
    return {**{key: value for key, value in encoded.items() if key not in absent}, **values}


def _decode_pages_v2(manifest, pages):
    """Independent full-field decoder; no interface/controller code is imported."""
    if manifest.get("machine_fields") != MACHINE_FIELDS_V2 or manifest.get("operation_fields") != OP_FIELDS_V2 or manifest.get("type_fields") != TYPE_FIELDS:
        raise ValueError("v2 compact field schema mismatch")
    if manifest.get("eligible_override_sentinel") != "all_family_machines" or manifest.get("operation_identity") != V2_IDENTITY or manifest.get("dictionary_semantics") != V2_DICTIONARY_SEMANTICS:
        raise ValueError("v2 declared identity/eligibility/dictionary semantics mismatch")
    allowed = {"schema", "problem_metadata", "source_problem_sha256", "machine_fields", "type_fields", "operation_fields", "operation_identity",
               "eligible_override_sentinel", "dictionary_semantics", "machine_count", "operation_count", "page_count", "observation_end", *PROBLEM_MIRRORS}
    if set(manifest) - allowed:
        raise ValueError("v2 manifest contains undeclared non-source metadata")
    metadata = manifest.get("problem_metadata")
    if not isinstance(metadata, dict) or {"machines", "operations"} & metadata.keys():
        raise ValueError("v2 complete problem_metadata missing or contains entity arrays")
    for key in PROBLEM_MIRRORS:
        if (key in metadata) != (key in manifest) or (key in metadata and _record_digest(manifest[key]) != _record_digest(metadata[key])):
            raise ValueError("v2 metadata mirror differs: " + key)
    machine_records, operation_records, family_dictionaries, used = {}, {}, {}, {}
    def item(table, index):
        if not isinstance(table, list) or type(index) is not int or not 0 <= index < len(table):
            raise ValueError("invalid v2 dictionary index")
        return table[index]
    for page in pages:
        if not isinstance(page, list):
            raise ValueError("v2 page must be a group list")
        for group in page:
            if not isinstance(group, dict) or set(group) != {"family", "machines", "types", "operations", "machine_extras", "operation_extras"}:
                raise ValueError("v2 group contains missing or undeclared fields")
            family = group["family"]
            tables = {key: value for key, value in group.items() if key != "operations"}
            if family in family_dictionaries and _record_digest(tables) != _record_digest(family_dictionaries[family]):
                raise ValueError("v2 repeated family dictionaries differ across pages")
            family_dictionaries[family] = tables
            used.setdefault(family, {"types": set(), "machine_extras": set(), "operation_extras": set()})
            mids = sorted(row[0] for row in group["machines"])
            local_indices = set()
            for row in group["machines"]:
                if not isinstance(row, list) or len(row) != len(MACHINE_FIELDS_V2):
                    raise ValueError("v2 machine row length differs from declared schema")
                source_index, extra_index = row[-2:]
                if type(source_index) is not int or source_index < 0 or source_index in local_indices:
                    raise ValueError("invalid or duplicated v2 machine source index in group")
                local_indices.add(source_index)
                encoded = {**dict(zip(MACHINE_FIELDS, row[:8])), "family": family}
                restored = _restore_record(encoded, item(group["machine_extras"], extra_index), {"machine", "family"})
                used[family]["machine_extras"].add(extra_index)
                if source_index in machine_records and _record_digest(machine_records[source_index]) != _record_digest(restored):
                    raise ValueError("v2 repeated source machine has different fields")
                machine_records[source_index] = restored
            for row in group["operations"]:
                if not isinstance(row, list) or len(row) != len(OP_FIELDS_V2):
                    raise ValueError("v2 operation row length differs from declared schema")
                source_index, extra_index = row[8], row[13]
                if type(source_index) is not int or source_index < 0 or source_index in operation_records:
                    raise ValueError("invalid or duplicated v2 operation source index")
                values = item(group["types"], row[1])
                if not isinstance(values, list) or len(values) != len(TYPE_FIELDS):
                    raise ValueError("v2 operation type row length mismatch")
                encoded = {"operation_id": row[0], "release_time": row[2], "predecessor_ids": row[3],
                           "priority": row[4], "due": row[5], "remaining_work_seconds": row[6],
                           "eligible_machines": mids if row[7] == "all_family_machines" else row[7],
                           "lot_id": row[9], "step": row[10], "visit": row[11], "waiting_since": row[12],
                           "family": family, **dict(zip(TYPE_FIELDS, values))}
                operation_records[source_index] = _restore_record(encoded, item(group["operation_extras"], extra_index), {"operation_id", "family"})
                used[family]["types"].add(row[1])
                used[family]["operation_extras"].add(extra_index)
    for family, tables in family_dictionaries.items():
        for key in ("types", "machine_extras", "operation_extras"):
            if used[family][key] != set(range(len(tables[key]))):
                raise ValueError("v2 dictionary contains unused or unrepresented source content: " + key)
    for records, count_key in ((machine_records, "machine_count"), (operation_records, "operation_count")):
        count = manifest.get(count_key)
        if type(count) is not int or set(records) != set(range(count)):
            raise ValueError("v2 source indices do not preserve the complete original array: " + count_key)
    if manifest.get("page_count") != len(pages):
        raise ValueError("v2 page count mismatch")
    return {**metadata, "machines": [machine_records[i] for i in range(len(machine_records))],
            "operations": [operation_records[i] for i in range(len(operation_records))]}


def _page_fidelity(problem, manifest, pages):
    schema = manifest.get("schema")
    errors = _verify_pages(problem, manifest, pages)
    report = {"schema": schema, "declared_representation_consistent": not errors,
              "full_problem_lossless_certified": schema == "fullfab-compact-paging-v2" and not errors}
    if schema == "fullfab-compact-paging-v1":
        machine_encoded = set(MACHINE_FIELDS) | {"family"}
        operation_encoded = set(TYPE_FIELDS) | {"operation_id", "release_time", "predecessor_ids", "priority", "due", "remaining_work_seconds", "eligible_machines", "same_machine_as", "family"}
        report["legacy_v1_limitations"] = {
            "unrepresented_problem_fields": sorted(set(problem) - set(PROBLEM_MIRRORS) - {"machines", "operations"}),
            "unrepresented_machine_fields": sorted({key for row in problem["machines"] for key in row if key not in machine_encoded}),
            "unrepresented_or_implicitly_encoded_operation_fields": sorted({key for row in problem["operations"] for key in row if key not in operation_encoded}),
            "presence_and_original_global_array_order_certified": False,
            "interpretation": "v1 audit checks declared core fields and saved model evidence only; it cannot certify a lossless full-problem representation"}
    return report


def _verify_pages(problem, manifest, pages):
    if manifest.get("schema") == "fullfab-compact-paging-v2":
        try:
            decoded = _decode_pages_v2(manifest, pages)
            errors = []
            if _record_digest(decoded) != _record_digest(problem):
                errors.append("v2 pages do not reconstruct every original problem field/presence/array order")
            if manifest.get("source_problem_sha256") != _record_digest(problem):
                errors.append("v2 source problem hash differs from saved complete problem")
            return errors
        except (KeyError, TypeError, IndexError, ValueError) as exc:
            return ["invalid lossless v2 pages: " + str(exc)]
    if manifest.get("schema") != "fullfab-compact-paging-v1":
        return ["unsupported compact paging schema"]
    errors, seen, represented_machines = [], [], set()
    if manifest.get("machine_fields") != MACHINE_FIELDS or manifest.get("type_fields") != TYPE_FIELDS or manifest.get("operation_fields") != OP_FIELDS:
        return ["compact field schema differs from the declared v1 core representation"]
    ops = {op["operation_id"]: op for op in problem["operations"]}
    machines = {m["machine"]: m for m in problem["machines"]}
    for page in pages:
        for group in page:
            mids = sorted(mid for mid, machine in machines.items() if machine["family"] == group["family"])
            expected_machines = [[m.get(key) for key in MACHINE_FIELDS] for m in problem["machines"] if m["family"] == group["family"]]
            if group["machines"] != expected_machines:
                errors.append("page machine state differs from full problem")
            represented_machines.update(mids)
            for row in group["operations"]:
                oid = row[0]
                seen.append(oid)
                if oid not in ops:
                    errors.append("page contains unknown operation")
                    continue
                op = ops[oid]
                expected = [oid, row[1], op["release_time"], op["predecessor_ids"], op["priority"], op["due"],
                            op["remaining_work_seconds"], None if sorted(op["eligible_machines"]) == mids else op["eligible_machines"]]
                if op.get("same_machine_as") is not None:
                    expected.append(op["same_machine_as"])
                if row != expected or op["family"] != group["family"]:
                    errors.append("page operation differs from full problem")
                if group["types"][row[1]] != [op[key] for key in TYPE_FIELDS]:
                    errors.append("page operation timing/batch/setup type differs from full problem")
    if Counter(seen) != Counter(ops.keys()):
        errors.append("pages omit or duplicate full-problem operations")
    if represented_machines != set(machines):
        errors.append("pages omit full-problem machine families")
    if manifest.get("operation_count") != len(ops) or manifest.get("page_count") != len(pages):
        errors.append("page manifest counts differ from evidence")
    for key in ("scope", "setup_transitions", "min_runs", "time", "horizon_end"):
        if manifest.get(key) != problem.get(key):
            errors.append("page manifest differs from problem: " + key)
    return errors


def audit_controller(run_dir, ledger_path=None):
    run = Path(run_dir).resolve()
    errors, missing, warnings, hashes = [], [], [], {}

    def check(ok, message):
        if not ok and len(errors) < 200:
            errors.append(message)

    def read(path, *, optional=False, lines=False):
        path = Path(path)
        if not path.exists():
            if not optional:
                missing.append(str(path))
            return None
        try:
            hashes[str(path.relative_to(run)) if path.is_relative_to(run) else str(path)] = sha_file(path)
            text = path.read_text()
            return [json.loads(line) for line in text.splitlines() if line.strip()] if lines else json.loads(text)
        except (ValueError, OSError) as exc:
            check(False, f"cannot parse {path.name}: {type(exc).__name__}")
            return None

    cfg = read(run / "config.json") or {}
    result = read(run / "result.json")
    arm = cfg.get("arm")
    check(arm in ("B", "C"), "controller audit requires an evaluated B/C run")
    if result is not None:
        check(result.get("identity") == digest(cfg), "result identity differs from saved config")
        check(result.get("config") == cfg, "result config differs from saved config")
    provenance = read(run / "provenance.json")
    prompt_constants = {}
    if provenance:
        for relative, expected in provenance.get("source_sha256", {}).items():
            path = run / "source_snapshot" / relative
            if not path.exists():
                missing.append(str(path))
            else:
                check(sha_file(path) == expected, "source snapshot hash mismatch: " + relative)
        for name in ("controller.py", "interface.py", "model_transport.py", "budget.py"):
            if "src/smt_fullfab/" + name not in provenance.get("source_sha256", {}):
                missing.append("source snapshot inventory: " + name)
        source = run / "source_snapshot/src/smt_fullfab/controller.py"
        if source.exists():
            try:
                prompt_constants = _literal_prompt_constants(source)
            except (ValueError, SyntaxError):
                missing.append("parseable frozen controller prompt constants")
    if cfg.get("enable_constructive") is True:
        for name in ("constructive_tool.py", "incumbent.py"):
            if "src/smt_fullfab/" + name not in (provenance or {}).get("source_sha256", {}):
                missing.append("source snapshot inventory: " + name)
    trace = read(run / "trace.jsonl", lines=True) or []
    commits = [e for e in trace if e.get("kind") == "plan_committed"]
    trace_manifest = trace[0].get("manifest", {}) if trace else {}
    if ledger_path is None:
        ledger_path = run.parents[2] / "progress/smt_fullfab/model_ledger.jsonl"
    ledger = read(ledger_path, lines=True) or []
    reserves = {row["call_id"]: row for row in ledger if row.get("event") == "reserve"}
    finishes = {row["call_id"]: row for row in ledger if row.get("event") == "finish"}
    check(len(reserves) == sum(row.get("event") == "reserve" for row in ledger), "duplicate model reservation identity")
    check(len(finishes) == sum(row.get("event") == "finish" for row in ledger), "duplicate model completion identity")
    approvals = [row["approval"] for row in ledger if row.get("event") == "approval" and row["approval"].get("budget_id") == cfg.get("budget_id")]
    approval = approvals[0] if len(approvals) == 1 else None
    check(len(approvals) == 1, "no unique approved ledger grant for this run")
    budget_replay = _audit_ledger_admission(ledger, approval) if approval else {"admissions": {}, "errors": [], "missing_evidence": []}
    constructor_replay = audit_constructor_ledger(ledger)
    budget_replay["constructor_replay"] = constructor_replay
    for cid, fields in constructor_replay["model_admissions"].items():
        if cid in budget_replay["admissions"]:
            budget_replay["admissions"][cid].update(fields)
    errors.extend(constructor_replay["errors"])
    errors.extend(budget_replay["errors"])
    missing.extend(budget_replay["missing_evidence"])
    run_registration = budget_replay.get("registered_runs", {}).get(str(run))
    if cfg.get("enable_constructive") is True:
        check(arm == "C" and run_registration is not None, "constructive requires a preceding research C registration")
    if approval:
        check(approval.get("authorization") == "approved_by_user", "ledger grant was not explicitly approved")
        if run_registration:
            check(read(run / "resource_registration.json") == run_registration, "saved resource registration differs from prior ledger registration")
            for ckey, rkey in (("arm", "arm"), ("seconds", "window_seconds"), ("seed", "scenario"), ("wall_seconds", "wall_seconds"), ("max_log_bytes", "max_log_bytes"), ("amendment_id", "amendment_id")):
                check(cfg.get(ckey) == run_registration[rkey], "run config differs from immutable registration: " + ckey)
            check(run_registration["solver_seconds"] == (cfg.get("solver_budget_seconds") if arm == "C" else 0), "run solver allowance differs from immutable registration")
            check(trace_manifest.get("seed") == run_registration["scenario"] and trace_manifest.get("horizon") == run_registration["window_seconds"],
                  "actual trace scenario/window differs from run registration")
        else:
            check(cfg.get("seconds") == approval.get("window_seconds"), "run window exceeds/differs from approved stage")
        own_ids = [call_id for call_id, row in reserves.items() if Path(row["run_id"]).resolve().is_relative_to(run)]
        effective = budget_replay.get("effective_amendment")
        unlimited = bool(arm == "C" and effective and cfg.get("amendment_id") == effective["amendment_id"] and
                         all(budget_replay["admissions"].get(call_id, {}).get("waiver_applied") for call_id in own_ids))
        if run_registration:
            unlimited = bool(cfg.get("amendment_id") == run_registration["amendment_id"] and all(
                budget_replay["admissions"].get(call_id, {}).get("registration", {}).get("registration_id") == run_registration["registration_id"] for call_id in own_ids))
        check((cfg.get("max_calls") is None and unlimited) or
              (type(cfg.get("max_calls")) is int and cfg["max_calls"] > 0 and (unlimited or cfg["max_calls"] <= approval.get("allocation", {}).get(arm, 0))),
              "per-run attempts exceed approved arm allocation without a preceding scoped waiver")
        if own_ids and any(budget_replay["admissions"].get(call_id, {}).get("waiver_applied") for call_id in own_ids):
            check(unlimited, "run config amendment differs from its effective reservation authority")
    links = read(run / "controller_decisions.jsonl", optional=True, lines=True) or []
    by_model = {}
    for link in links:
        index = link.get("model_index")
        check(index not in by_model, "duplicate controller model linkage index")
        by_model[index] = link
    models, model_directories = {}, {}
    for directory in sorted(run.glob("model_*")):
        if not directory.is_dir() or not re.fullmatch(r"model_\d+", directory.name):
            continue
        index = int(directory.name.split("_")[1])
        model_directories[index] = directory
        request = read(directory / "request.json")
        model = read(directory / "result.json")
        events = read(directory / "events.jsonl", lines=True)
        schema = read(directory / "schema.json")
        prompt_path, final_path = directory / "prompt.txt", directory / "final.txt"
        if not prompt_path.exists():
            missing.append(str(prompt_path))
        prompt = prompt_path.read_text() if prompt_path.exists() else ""
        if prompt_path.exists():
            hashes[str(prompt_path.relative_to(run))] = sha_file(prompt_path)
        if request is None or model is None or schema is None or events is None:
            continue
        parsed_sections = _sections(prompt)
        prompt_name = "C_CONSTRUCTIVE_PROMPT" if cfg.get("enable_constructive") is True else str(arm) + "_PROMPT"
        prefix = prompt_constants.get(prompt_name)
        if prefix is None:
            missing.append("literal frozen " + prompt_name)
        else:
            try:
                parsed_sections = _strict_prompt_sections(prompt, prefix)
                allowed = {"SCHEMA_AND_LIMITS", "PAGE"} if arm == "B" else {"STATE_DIRECTORY", "OWN_HISTORY", "LIMITS"}
                check(all(name in allowed or (arm == "B" and name.startswith("YOUR_")) for name in parsed_sections), f"model {index}: undeclared input section")
            except (ValueError, json.JSONDecodeError) as exc:
                check(False, f"model {index}: {exc}")
        models[index] = {"result": model, "request": request, "prompt": prompt, "sections": parsed_sections}
        call_id = model.get("call_id")
        check(call_id == request.get("call_id") and call_id in reserves, f"model {index}: call ID lacks matching request/reservation")
        config = request.get("config", {})
        check(config == model.get("config"), f"model {index}: request/result config mismatch")
        expected = hashlib.sha256((prompt + "\n" + json.dumps(schema, ensure_ascii=False, indent=2) + "\n" + "\n" + json.dumps(config, sort_keys=True)).encode()).hexdigest()
        check(model.get("request_fingerprint") == expected == request.get("request_fingerprint"), f"model {index}: prompt/schema/config fingerprint mismatch")
        if approval:
            check(config.get("model") == approval["model"] and config.get("reasoning_effort") == approval["reasoning_effort"], f"model {index}: unapproved model/config change")
            check(config.get("grant_id") == approval["budget_id"], f"model {index}: wrong budget grant")
            check(config.get("timeout_seconds", 0) <= approval["per_call_timeout_seconds"], f"model {index}: timeout exceeds approval")
        if call_id in reserves:
            reserve = reserves[call_id]
            check(Path(reserve["run_id"]).resolve() == directory, f"model {index}: reservation points to another model attempt")
            check(reserve.get("metadata", {}).get("request_fingerprint") == expected, f"model {index}: reservation fingerprint mismatch")
            admission = budget_replay["admissions"].get(call_id, {})
            if admission.get("waiver_applied"):
                check(config.get("timeout_seconds") == admission.get("timeout_seconds"), f"model {index}: actual timeout differs from scoped reservation")
                context = config.get("authorization_context", {})
                check(context == reserve.get("metadata", {}).get("authorization_context"), f"model {index}: actual authorization context differs from scoped reservation")
                if admission.get("waiver_scope") == "registered_research":
                    check(config.get("phase") == admission["registration"]["phase"], f"model {index}: actual phase differs from research registration")
                if arm == "C":
                    limits = parsed_sections.get("LIMITS")
                    expected_limits = {"responses": None if cfg.get("max_calls") is None else cfg["max_calls"] - index,
                                       "solver_seconds": approval["max_solver_requested_seconds_per_arm"] - admission["solver_requested_seconds_before_by_arm"].get(arm, 0),
                                       "model_active_seconds_remaining": approval["total_active_wall_seconds"] - admission["active_seconds_before"]}
                    if admission.get("waiver_scope") == "registered_research":
                        expected_limits.update(solver_seconds=admission["registration"]["solver_seconds"] - admission["run_solver_requested_seconds_before"],
                            model_active_seconds_remaining=admission["registration"]["wall_seconds"] - admission["run_active_seconds_before"])
                    if "per_request_solver_seconds" in (limits or {}) or admission.get("waiver_scope") == "registered_research":
                        expected_limits["per_request_solver_seconds"] = min(60, expected_limits["solver_seconds"])
                    if cfg.get("enable_constructive") is True:
                        expected_limits["model_active_seconds_remaining"] -= admission.get("constructor_active_seconds_before", 0)
                        expected_limits.update(per_request_constructor_seconds=min(5., max(0., expected_limits["model_active_seconds_remaining"])),
                            constructor_requested_seconds=admission.get("constructor_requested_seconds_before", 0),
                            constructor_active_seconds=admission.get("constructor_active_seconds_before", 0), constructor_evaluation_cap=250000)
                    check(limits == expected_limits, f"model {index}: C prompt LIMITS differ from prior applicable ledger consumption")
        if call_id not in finishes:
            missing.append(f"ledger finish for {call_id}")
        else:
            finish = finishes[call_id]
            check(finish["status"] == model.get("status"), f"model {index}: ledger/model status mismatch")
            check(finish.get("details", {}).get("usage") == model.get("usage"), f"model {index}: token usage differs from ledger")
            check(finish.get("details", {}).get("duration_seconds") == model.get("duration_seconds"), f"model {index}: duration differs from ledger")
        native = [e.get("item", {}) for e in events if e.get("type") in ("item.started", "item.updated", "item.completed") and e.get("item", {}).get("type") not in {"agent_message", "reasoning", "error"}]
        completed = [e for e in events if e.get("type") == "turn.completed"]
        check(model.get("native_tool_events") == native, f"model {index}: native tool evidence differs from summary")
        usages = [e["usage"] for e in completed if isinstance(e.get("usage"), dict)]
        for key in ("input_tokens", "cached_input_tokens", "output_tokens", "cache_write_input_tokens", "reasoning_output_tokens"):
            actual_usage = sum(u[key] for u in usages) if usages and all(type(u.get(key)) in (int, float) for u in usages) else None
            check(model.get("usage", {}).get(key) == actual_usage, f"model {index}: {key} differs from raw completed-turn events")
        if model.get("status") == "success":
            check(not native and len(completed) == 1 and not model.get("timed_out"), f"model {index}: successful call violates isolation/completion contract")
            final = read(final_path)
            check(final == model.get("output"), f"model {index}: saved final JSON differs from decoded model output")
            errors.extend(f"model {index}: {error}" for error in _schema_errors(model.get("output"), schema))
        if index in by_model:
            link = by_model[index]
            check(link.get("call_id") == call_id, f"model {index}: controller linkage points to another call")
            check(link.get("response_sha256") == digest(model.get("output")), f"model {index}: controller response hash mismatch")
            check(link.get("status") == model.get("status"), f"model {index}: controller linkage status mismatch")
        if model.get("cost_usd") is not None:
            warnings.append(f"model {index}: non-null monetary cost requires separate billing source verification")

    call_ids = [models[i]["result"]["call_id"] for i in sorted(models)]
    check(len(call_ids) == len(set(call_ids)), "call identity reused across model directories")
    # Verify inputs even for failed attempts before any plan was committed.
    # Legacy failed probes can bind a page by exact saved content without
    # pretending that an accepted plan has an absent decision linkage.
    page_sets, page_fidelity = {}, []
    for manifest_path in sorted(run.glob("page_manifest_*.json")):
        try:
            plan_index = int(manifest_path.stem.rsplit("_", 1)[1])
            pm = read(manifest_path)
            problem = read(run / f"problem_{plan_index:03d}.json")
            if pm is None or problem is None:
                continue
            pages = [read(run / f"page_{plan_index:03d}_{i:02d}.json") for i in range(pm["page_count"])]
            if any(page is None for page in pages):
                continue
            check(pm.get("observation_end") == trace_manifest.get("horizon"), f"plan {plan_index}: page observation endpoint differs from trace")
            if "page_chars" in cfg:
                check(type(cfg["page_chars"]) is int and 10000 <= cfg["page_chars"] <= 90000 and
                      all(len(json.dumps(page, separators=(",", ":"), allow_nan=False)) <= cfg["page_chars"] for page in pages),
                      f"plan {plan_index}: saved page exceeds declared character limit")
            errors.extend(f"plan {plan_index}: {message}" for message in _verify_pages(problem, pm, pages))
            fidelity = {"plan_index": plan_index, **_page_fidelity(problem, pm, pages)}
            page_fidelity.append(fidelity)
            if pm.get("schema") == "fullfab-compact-paging-v1":
                warnings.append(f"plan {plan_index}: legacy compact v1 omits full-problem metadata/presence; passed evidence does not certify lossless input")
            page_sets[plan_index] = (pm, problem, pages)
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            check(False, f"malformed saved observation pages: {type(exc).__name__}")
    for index, model in sorted(models.items()):
        sections = model["sections"]
        prior = [models[j]["result"].get("output") for j in sorted(models) if j < index]
        own_tasks = [task for output in prior if isinstance(output, dict) for task in output.get("tasks", [])]
        own_holds = [hold for output in prior if isinstance(output, dict) for hold in output.get("holds", [])]
        if arm == "B":
            metadata, page = sections.get("SCHEMA_AND_LIMITS", {}), sections.get("PAGE")
            page_index = metadata.get("page_index")
            matches = [(pindex, pm, problem, pages) for pindex, (pm, problem, pages) in page_sets.items()
                       if type(page_index) is int and 0 <= page_index < len(pages) and pages[page_index] == page
                       and all(metadata.get(key) == value for key, value in pm.items())]
            check(bool(matches), f"model {index}: B prompt state is not an exact saved full-fab page")
            for name, records in sections.items():
                if name.startswith("YOUR_"):
                    check(isinstance(records, list) and all(record in own_tasks or record in own_holds for record in records),
                          f"model {index}: B own-history input contains unchosen/external advice")
            if matches:
                expected_keys = set(matches[0][1]) | {"page_index", "last_page", "remaining_model_responses"}
                check(set(metadata) == expected_keys, f"model {index}: B input contains undeclared schema/limit metadata")
                check(metadata.get("remaining_model_responses") == (None if cfg.get("max_calls") is None else cfg["max_calls"] - index),
                      f"model {index}: B response allowance differs from run config and completed attempts")
        elif arm == "C":
            summary = sections.get("STATE_DIRECTORY", {})
            matches = []
            for pindex, (pm, problem, pages) in page_sets.items():
                expected = {"time": problem["time"], "horizon_end": problem["horizon_end"], "observation_end": trace_manifest.get("horizon"),
                            "machines": len(problem["machines"]), "operations": len(problem["operations"]), "pages": len(pages),
                            "family_counts": [{"family": group["family"], "machines": len(group["machines"]), "operations": len(group["operations"])} for page in pages for group in page],
                            "methods_available": ["global", cfg.get("solver_method_available", "decomposed")] + (["constructive"] if cfg.get("enable_constructive") is True else [])}
                if pm.get("schema") == "fullfab-compact-paging-v2":
                    expected["problem_metadata"] = {key: value for key, value in problem.items() if key not in ("machines", "operations")}
                if summary == expected:
                    matches.append(pindex)
            check(bool(matches), f"model {index}: C state directory differs from saved full-fab observation")
            own_history = sections.get("OWN_HISTORY", [])
            check(isinstance(own_history, list), f"model {index}: C own-history is not a list")
            if isinstance(own_history, list):
                for entry in own_history:
                    check(isinstance(entry, dict) and entry.get("decision") in prior, f"model {index}: C history contains a decision not made by its prior model calls")
                    if isinstance(entry, dict) and entry.get("decision", {}).get("action") == "read_page":
                        page_index = entry["decision"].get("index")
                        faithful = any(type(page_index) is int and 0 <= page_index < len(page_sets[pindex][2]) and
                                       entry.get("page") == page_sets[pindex][2][page_index] and entry.get("schema") == page_sets[pindex][0]
                                       for pindex in matches)
                        check(faithful, f"model {index}: C page/schema feedback omits or alters complete observation metadata")
    if result:
        check(result.get("model_calls") == len(model_directories), "run model count omits/invents an attempt directory")
        check(result.get("model_call_ids") == call_ids, "run model call IDs differ from durable attempts")
        check(result.get("plans_committed") == len(commits), "run plan count differs from trace")
    own_reserves = [row for row in reserves.values() if Path(row["run_id"]).resolve().is_relative_to(run)]
    check(len(own_reserves) == len(model_directories), "attempt directories and budget reservations differ")
    if commits and not links:
        missing.append("controller_decisions.jsonl required to bind accepted plans to exact model rounds")

    constructor_report = audit_constructor_evidence(run, cfg, models, ledger, read)
    errors.extend(constructor_report["errors"])
    missing.extend(constructor_report["missing_evidence"])
    if cfg.get("enable_constructive") is True:
        check(bool(page_fidelity) and all(row["full_problem_lossless_certified"] for row in page_fidelity), "constructive controller requires lossless v2 observations")
    checked_plans, solver_request_count, plan_attributions = 0, 0, []
    solver_requests = sorted(run.glob("solver_request_*.json"))
    solver_files = sorted(run.glob("solver_[0-9]*.json"))
    if arm == "B":
        check(not solver_requests and not solver_files, "B contains solver request/result evidence")
        check(not any(row.get("event") == "solver_reserve" and Path(row.get("run_id", "/")).resolve() == run for row in ledger), "B consumed solver budget")
        if result:
            check(result.get("solver_calls") == 0 and result.get("solver_requested_seconds") == 0, "B reports solver use")
    commit_links = read(run / "plan_commits.jsonl", optional=True, lines=True) or []
    solver_metadata = read(run / "solver_evidence.jsonl", optional=True, lines=True) or []
    solver_reserves = {row["call_id"]: row for row in ledger if row.get("event") == "solver_reserve"}
    solver_finishes = {row["call_id"]: row for row in ledger if row.get("event") == "solver_finish"}
    check(len(solver_reserves) == sum(row.get("event") == "solver_reserve" for row in ledger), "duplicate solver reservation identity")
    check(len(solver_finishes) == sum(row.get("event") == "solver_finish" for row in ledger), "duplicate solver finish identity")
    own_solver_reserves = [row for row in solver_reserves.values() if Path(row.get("run_id", "/")).resolve() == run]
    # Every CP invocation, including failed/unselected attempts, needs exactly
    # one preceding reservation, one immutable model request and one outcome.
    # Without this bijection a closed extra reservation or a dropped request in
    # an uncommitted plan could escape the per-request checks below.
    request_records = [(path, read(path)) for path in solver_requests]
    expected_solver_ids = Counter(row["call_id"] for row in own_solver_reserves)
    request_ids, outcome_ids, request_model_ids = [], [], []
    for path, record in request_records:
        if not isinstance(record, dict):
            continue
        sid = record.get("solver_call_id")
        check(isinstance(sid, str) and bool(sid), "solver request lacks a unique string call identity")
        if isinstance(sid, str):
            request_ids.append(sid)
        model_id = record.get("call_id")
        check(isinstance(model_id, str) and bool(model_id), "solver request lacks explicit model call identity")
        if isinstance(model_id, str):
            request_model_ids.append(model_id)
        suffix = path.stem.rsplit("_", 1)[-1]
        check(suffix.isdigit() and type(record.get("solver_index")) is int and record.get("solver_index") == int(suffix),
              "solver request index differs from its immutable file identity")
    for record in solver_metadata:
        sid = record.get("solver_call_id")
        check(isinstance(sid, str) and bool(sid), "solver outcome lacks a unique string call identity")
        if isinstance(sid, str):
            outcome_ids.append(sid)
    check(len(solver_requests) == len(own_solver_reserves) and Counter(request_ids) == expected_solver_ids,
          "solver requests do not correspond one-to-one with own durable reservations")
    check(len(solver_metadata) == len(own_solver_reserves) and Counter(outcome_ids) == expected_solver_ids,
          "solver outcomes do not correspond one-to-one with own durable reservations")
    check(len(request_model_ids) == len(set(request_model_ids)), "one model solve action was used for repeated CP invocations")
    expected_result_names = {f"solver_{record['solver_index'] + 1:03d}.json" for record in solver_metadata
                             if record.get("status") == "success" and type(record.get("solver_index")) is int}
    check({path.name for path in solver_files} == expected_result_names,
          "solver result files do not match successful invocation outcomes")
    if result and arm == "C":
        check(result.get("solver_calls") == len(own_solver_reserves), "C reported solver count differs from durable reservations")
        check(result.get("solver_requested_seconds") == sum(row["requested_seconds"] for row in own_solver_reserves), "C reported solver budget differs from durable reservations")
    if approval and "max_solver_requested_seconds_per_arm" in approval:
        used_solver = sum(row["requested_seconds"] for row in solver_reserves.values() if row.get("arm") == arm and not row.get("registration_id"))
        check(used_solver <= approval["max_solver_requested_seconds_per_arm"] + 1e-6, "cumulative arm solver reservation exceeds grant")
    for metadata in solver_metadata:
        sid = metadata.get("solver_call_id")
        if sid not in solver_reserves or sid not in solver_finishes:
            missing.append(f"solver {metadata.get('solver_index')}: reservation/finish identity")
            continue
        reservation, finish = solver_reserves[sid], solver_finishes[sid]
        check(reservation.get("arm") == arm and Path(reservation["run_id"]).resolve() == run, "solver ledger reservation belongs to another arm/run")
        check(reservation.get("requested_seconds") == metadata.get("requested_seconds"), "solver requested seconds differ from ledger")
        check(finish.get("status") == metadata.get("status"), "solver status differs from ledger")
    # Failed or unselected solver attempts still have provenance and cost; do
    # not hide them merely because no final plan was ever committed.
    for path in solver_requests:
        request = read(path)
        if request is None:
            continue
        solver_index = int(path.stem.rsplit("_", 1)[1])
        model_index, plan_index = request.get("model_index"), request.get("plan_index")
        if model_index not in models or type(plan_index) is not int:
            missing.append(f"solver {solver_index}: request/model/plan linkage")
            continue
        try:
            model = models[model_index]["result"]
            response = model.get("output")
            check(model.get("status") == "success" and response.get("action") == "solve", "solver request did not originate in a successful model solve action")
            check(request.get("call_id") == model["call_id"] and request.get("response") == response, "solver request differs from exact model choice")
            problem = read(run / f"problem_{plan_index:03d}.json")
            if problem is None:
                continue
            expected_parameters = {"time_limit_seconds": response["seconds"], "seed": response["seed"], "weights": response["weights"],
                                   "max_slots_per_machine": response["slots"], "plan_version": cfg["run_id"] + ":" + str(plan_index)}
            check(request.get("parameters") == expected_parameters and request.get("problem_sha256") == digest(problem),
                  "solver request parameters/problem differ from chosen observed solve")
            meta = [m for m in solver_metadata if m.get("solver_index") == solver_index]
            if len(meta) != 1:
                missing.append(f"solver {solver_index}: exactly one attempt outcome evidence")
                continue
            outcome = meta[0]
            for key in ("solver_call_id", "solver_index", "actual_solver_module", "actual_solver_function", "method", "requested_seconds"):
                if key not in request:
                    missing.append(f"solver {solver_index}: solver_request {key} linkage")
                else:
                    check(request[key] == outcome.get(key), "solver request/outcome linkage differs: " + key)
            check(outcome.get("model_index") == model_index and outcome.get("call_id") == model["call_id"] and outcome.get("plan_index") == plan_index,
                  "solver attempt outcome differs from model/plan identity")
            check(outcome.get("requested_seconds") == response["seconds"] and outcome.get("method") == response["method"], "solver attempt method/budget differs from model choice")
            if outcome.get("status") == "success":
                solved = read(run / f"solver_{solver_index + 1:03d}.json")
                if solved is None:
                    continue
                module, function, version = SOLVERS[response["method"]]
                check(solved.get("model") == version and solved.get("requested_method") == response["method"], "saved solver result is not the chosen shared solver method")
                check(outcome.get("actual_solver_module") == module and outcome.get("actual_solver_function") == function, "solver attempt used a different implementation")
                check(outcome.get("solver_result_sha256") == digest(solved), "solver attempt result hash mismatch")
                errors.extend(f"solver {solver_index}: {message}" for message in _heuristic_errors(solved, response["method"]))
                finish = solver_finishes.get(outcome.get("solver_call_id"), {})
                check(finish.get("details", {}).get("solver_status") == solved.get("solver_status") and
                      finish.get("details", {}).get("wall_seconds") == solved.get("wall_seconds"), "solver ledger outcome differs from saved result")
            elif outcome.get("status") == "failed":
                check(bool(outcome.get("error")), "failed solver outcome has no preserved failure reason")
            else:
                missing.append(f"solver {solver_index}: terminal solver attempt outcome")
        except (KeyError, TypeError, ValueError) as exc:
            check(False, f"solver {solver_index}: malformed evidence ({type(exc).__name__})")

    for plan_index, commit in enumerate(commits):
        try:
            problem = read(run / f"problem_{plan_index:03d}.json")
            page_manifest = read(run / f"page_manifest_{plan_index:03d}.json")
            raw = read(run / f"raw_plan_{plan_index:03d}.json")
            if problem is None or page_manifest is None or raw is None:
                continue
            pages = [read(run / f"page_{plan_index:03d}_{i:02d}.json") for i in range(page_manifest["page_count"])]
            if any(page is None for page in pages):
                continue
            errors.extend(f"plan {plan_index}: {message}" for message in _verify_pages(problem, page_manifest, pages))
            decisions = sorted((link for link in links if link.get("plan_index") == plan_index), key=lambda x: x["model_index"])
            for link in decisions:
                check(link.get("input_problem_sha256") == digest(problem), f"plan {plan_index}: decision linked to another problem")
            if not decisions:
                missing.append(f"plan {plan_index}: no model decision links")
                continue
            source_call, source_candidate, source_solver = None, None, None
            if arm == "B":
                staged, holds, reason = [], [], ""
                check(len(decisions) == len(pages), f"plan {plan_index}: B did not explicitly receive all full-fab pages")
                for page_index, page in enumerate(pages):
                    matched = [link for link in decisions if link.get("page_index") == page_index]
                    check(len(matched) == 1, f"plan {plan_index} page {page_index}: missing/duplicate model binding")
                    if len(matched) != 1 or matched[0]["model_index"] not in models:
                        continue
                    model = models[matched[0]["model_index"]]
                    response = model["result"].get("output")
                    check(model["result"].get("status") == "success", "accepted B patch from unsuccessful model call")
                    patch = read(run / f"patch_{plan_index:03d}_{page_index:02d}.json")
                    check(patch == response, f"plan {plan_index} page {page_index}: patch differs from exact model output")
                    if patch is None:
                        continue
                    check(model["sections"].get("PAGE") == page, f"plan {plan_index} page {page_index}: model was shown different state")
                    metadata = model["sections"].get("SCHEMA_AND_LIMITS", {})
                    check(metadata.get("page_index") == page_index and metadata.get("last_page") == (page_index == len(pages) - 1), "B page position in prompt differs from applied patch")
                    for key, value in page_manifest.items():
                        check(metadata.get(key) == value, "B prompt schema/limit differs from saved page manifest: " + key)
                    allowed = {row[0] for group in page for row in group["operations"]}
                    check(all(oid in allowed for task in patch["tasks"] for oid in task["operations"]), "B patch chooses unobserved operations outside its page")
                    check(patch["commit"] == (page_index == len(pages) - 1), "B lacks final explicit commit or committed before observing all pages")
                    for name, records in model["sections"].items():
                        if name.startswith("YOUR_") and isinstance(records, list):
                            check(all(record in staged or record in holds for record in records), "B supplied own-history context contains a task/hold not previously chosen by B")
                    staged.extend(patch["tasks"])
                    holds.extend(patch["holds"])
                    reason = patch["reason"]
                    source_call = model["result"]["call_id"]
                sequence = [(task["machine"], task["sequence"]) for task in staged]
                check(all(type(t["sequence"]) is int for t in staged) and len(sequence) == len(set(sequence)), "B lacks unique explicit integer machine sequence")
                ordered = sorted(staged, key=lambda task: (task["machine"], task["sequence"]))
                operations = {o["operation_id"]: o for o in problem["operations"]}
                tasks = []
                for i, task in enumerate(ordered):
                    selected = [operations[oid] for oid in task["operations"]]
                    tasks.append({"id": str(i), "machine": task["machine"], "lot_ids": [o["lot_id"] for o in selected],
                                  "steps": [o["step"] for o in selected], "visits": [o["visit"] for o in selected],
                                  "operation_ids": task["operations"], "not_before": task["start"]})
                decoded_holds = []
                for hold in holds:
                    decoded = {key: value for key, value in hold.items() if key != "after_sequence"}
                    if hold.get("after_sequence") is not None:
                        indices = [i for i, task in enumerate(ordered) if task["machine"] == hold["machine"] and task["sequence"] == hold["after_sequence"]]
                        check(len(indices) == 1, "B conditional hold has no unique explicitly chosen machine sequence")
                        if len(indices) == 1:
                            decoded["after_task_id"] = str(indices[0])
                    decoded_holds.append(decoded)
                expected_raw = {"version": cfg["run_id"] + ":" + str(plan_index), "created_at": problem["time"],
                                "valid_until": problem["horizon_end"], "freeze_until": problem["time"],
                                "reason": reason, "scope": problem["scope"], "tasks": tasks, "holds": decoded_holds}
                check(raw == expected_raw, f"plan {plan_index}: B raw plan is not an exact deterministic decoding of model choices")
            elif arm == "C":
                history = read(run / f"controller_history_{plan_index:03d}.json")
                if history is None:
                    continue
                check(len(history) == len(decisions), "C saved history omits a model decision, including explicit apply")
                candidates = []
                for offset, link in enumerate(decisions):
                    model_index = link["model_index"]
                    if model_index not in models or offset >= len(history):
                        continue
                    model = models[model_index]
                    response = model["result"].get("output")
                    check(model["result"].get("status") == "success", "C used an unsuccessful model response")
                    check(history[offset].get("decision") == response, "C history decision differs from exact model output")
                    check(model["sections"].get("OWN_HISTORY") == history[:offset], "C model was shown different own decision/solver history")
                    if response["action"] == "read_page":
                        check(history[offset].get("page") == pages[response["index"]], "C page feedback differs from full-fab page")
                        check(history[offset].get("schema") == page_manifest, "C page feedback schema differs from saved complete observation metadata")
                    elif response["action"] == "solve" and response.get("method") == "constructive":
                        candidate = constructor_report["candidates"].get(model_index)
                        if candidate is None:
                            missing.append(f"C model {model_index}: exact constructor candidate evidence")
                            candidates.append((None, None))
                        else:
                            check(candidate["plan_index"] == plan_index, "constructor candidate belongs to another plan")
                            candidates.append((candidate["solved"] if candidate["valid"] else None, None))
                    elif response["action"] == "solve":
                        matches = []
                        for path in solver_requests:
                            request = read(path)
                            if request and request.get("model_index") == model_index:
                                matches.append((path, request))
                        if len(matches) != 1:
                            missing.append(f"C model {model_index}: exact solver_request linkage")
                            continue
                        path, request = matches[0]
                        solver_index = int(path.stem.rsplit("_", 1)[1])
                        solver_request_count += 1
                        check(request.get("response") == response and request.get("call_id") == model["result"]["call_id"], "C solve request differs from chosen model action")
                        check(request.get("problem_sha256") == digest(problem), "C solver used a different observed problem")
                        parameters = {"time_limit_seconds": response["seconds"], "seed": response["seed"], "weights": response["weights"],
                                      "max_slots_per_machine": response["slots"], "plan_version": cfg["run_id"] + ":" + str(plan_index)}
                        check(request.get("parameters") == parameters, "C solver parameters differ from model choices")
                        solved = read(run / f"solver_{solver_index + 1:03d}.json")
                        if solved is None:
                            continue
                        check(response["method"] in SOLVERS, "C requested unknown solver method")
                        module, function, version = SOLVERS[response["method"]]
                        check(solved.get("requested_method") == response["method"] and solved.get("model") == version, "C requested method differs from executed shared solver model")
                        meta = [m for m in solver_metadata if m.get("solver_index") == solver_index]
                        if len(meta) != 1:
                            missing.append(f"solver {solver_index}: solver_evidence linkage")
                        else:
                            m = meta[0]
                            check(m.get("actual_solver_module") == module and m.get("actual_solver_function") == function, "C solver implementation differs from model-selected method")
                            check(m.get("solver_result_sha256") == digest(solved), "C solver evidence hash differs from saved candidate")
                            check(m.get("model_index") == model_index and m.get("call_id") == model["result"]["call_id"] and m.get("plan_index") == plan_index,
                                  "solver evidence is not linked to this model decision/plan")
                            check(m.get("method") == response["method"] and m.get("requested_seconds") == response["seconds"], "solver evidence differs from chosen method/budget")
                        valid = solved.get("solver_status") in FEASIBLE_STATUSES
                        candidates.append((solved if valid else None, solver_index))
                        feedback = history[offset].get("result", {})
                        for key in FEEDBACK_FIELDS:
                            check(feedback.get(key) == solved.get(key), "C solver feedback differs from saved solver: " + key)
                        check(feedback.get("candidate_index") == len(candidates) - 1 and feedback.get("valid_candidate") == valid, "C candidate index/status feedback differs from saved solver")
                        check(feedback.get("plan_sha256") == digest(solved["plan"]), "C inspected candidate hash differs from actual candidate")
                        check(feedback.get("tasks_preview") == solved["plan"]["tasks"][:12], "C inspected task preview differs from actual candidate")
                        check(feedback.get("task_count") == len(solved["plan"]["tasks"]) and feedback.get("unplanned_operations_count") == len(solved.get("unplanned_operations", {})), "C candidate coverage feedback differs from saved solver")
                    elif response["action"] == "apply":
                        candidate = response["index"]
                        check(offset == len(decisions) - 1, "C apply was not final decision for this plan")
                        check(type(candidate) is int and 0 <= candidate < len(candidates), "C applied missing/uninspected candidate")
                        if type(candidate) is int and 0 <= candidate < len(candidates):
                            chosen, source_solver = candidates[candidate]
                            check(chosen is not None, "C applied infeasible/failed candidate")
                            if chosen:
                                check(raw == chosen["plan"], "C raw plan differs from explicitly selected candidate")
                            check(history[offset].get("applied_candidate") == candidate and history[offset].get("plan_sha256") == digest(raw), "C explicit apply history differs from raw plan")
                            source_candidate = candidate
                            source_call = model["result"]["call_id"]
                check(source_call is not None, "C plan has no explicit model apply")
            expected_commit = _crop(raw, trace_manifest["horizon"], trace_manifest["controlled_machine_ids"])
            check(commit["plan"] == expected_commit, f"plan {plan_index}: trace commitment differs from disclosed raw plan clipping")
            linked_commit = [item for item in commit_links if item.get("plan_index") == plan_index]
            if len(linked_commit) != 1:
                missing.append(f"plan {plan_index}: plan_commits.jsonl exact commit linkage")
            else:
                item = linked_commit[0]
                check(item.get("model_call_id") == source_call, "plan commit was not attributed to final explicit model commit/apply")
                check(item.get("raw_plan_sha256") == digest(raw) and item.get("committed_plan_sha256") == digest(commit["plan"]), "plan commit hash mismatch")
                if arm == "C":
                    # These redundant fields were not emitted by the original
                    # controller. The complete explicit apply chain above is
                    # sufficient; if present, they must agree with that chain.
                    for key, inferred in (("source_candidate_index", source_candidate), ("source_solver_index", source_solver)):
                        if key in item:
                            check(item[key] == inferred, "C commit candidate/solver attribution mismatch")
            plan_attributions.append({"plan_index": plan_index, "model_call_id": source_call,
                                      "source_candidate_index": source_candidate, "source_solver_index": source_solver,
                                      "raw_plan_sha256": digest(raw), "committed_plan_sha256": digest(commit["plan"])})
            checked_plans += 1
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            check(False, f"plan {plan_index}: malformed controller evidence ({type(exc).__name__}: {exc})")

    if result and result.get("status") == "success":
        check(bool(result.get("full_window_completed")) and bool(trace) and trace[-1].get("kind") == "terminal", "run claims success without a complete terminal trace")
    if any(path.name.startswith("solver_") for path in solver_requests) and not solver_metadata:
        missing.append("solver_evidence.jsonl for executed solver attempts")
    status = "failed" if errors else "partial" if missing else "passed"
    return {"audit_version": VERSION, "audit_status": status, "valid": status == "passed",
            "errors": errors, "missing_evidence": sorted(set(missing)), "warnings": warnings,
            "arm": arm, "run_status": result.get("status") if result else "unfinished",
            "successful_full_window": bool(status == "passed" and result and result.get("status") == "success" and result.get("full_window_completed")),
            "model_attempt_directories": len(model_directories), "completed_model_records": len(models),
            "committed_plans": len(commits), "attribution_checked_plans": checked_plans,
            "model_call_ids": call_ids, "controller_decision_links": len(links),
            "checked_solver_requests_for_committed_plans": solver_request_count,
            "checked_constructor_attempts": constructor_report["attempts"],
            "reconstructed_plan_attributions": plan_attributions,
            "budget_admission_replay": budget_replay,
            "page_representation_audits": page_fidelity,
            "all_saved_problem_pages_lossless_certified": bool(page_fidelity) and all(row["full_problem_lossless_certified"] for row in page_fidelity),
            "monetary_cost_certified": False, "physics_and_opportunity_replay_required_separately": True,
            "evidence_sha256": hashes,
            "scope": "independent saved-evidence attribution, not a successful-production or official-simulator-equivalence certificate"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    parser.add_argument("--ledger")
    args = parser.parse_args()
    result = audit_controller(args.run_dir, args.ledger)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
