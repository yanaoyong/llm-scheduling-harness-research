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



# Exact original constructor ledger and its pure constants/helpers.
MODULE='src.smt_fullfab.constructive_tool'
FUNCTION='solve_constructive_plan'
MODEL='fullfab-constructive-tool-v1'
VERSION='fullfab-C-explicit-constructive-v1'
FEEDBACK_FIELDS=('solver_status','objective','best_bound','planned_operations','wall_seconds','limitations',
                 'global_optimality_claim','selected_source','cp_sat','decomposition_status','heuristic_families')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def finite(value,minimum=0):
    return type(value) in (int,float) and math.isfinite(value) and value>=minimum


def audit_constructor_ledger(rows):
    """Replay constructor authority/accounting in order, supplementing base audit."""
    errors=[];pending={};seen=set();register={};starts={};ends={};model_run={}
    model_active=Counter();constructor_active=Counter();requested=Counter();counts=Counter()
    model_admissions={};constructor_admissions={};sources=set();research=None
    def check(ok,message):
        if not ok:errors.append(message)
    for row in rows:
        event=row.get('event');cid=row.get('call_id')
        if event=='research_limit_waiver':research=row.get('amendment')
        elif event=='stage_run_registered':
            r=row['registration'];register[r['registration_id']]=r
        elif event in ('reserve','solver_reserve','constructor_reserve'):
            check(cid not in seen,'duplicate identity across model/CP/constructor calls');seen.add(cid)
            if event=='constructor_reserve' or any(kind=='constructor_reserve' for kind in pending.values()):
                check(not pending,'admission while model/CP/constructor call is pending')
            pending[cid]=event;starts[cid]=row
            rid=row.get('registration_id');r=register.get(rid)
            if event=='reserve':
                model_run[cid]=rid
                model_admissions[cid]={'constructor_active_seconds_before':constructor_active[rid],
                    'constructor_requested_seconds_before':requested[rid],
                    'active_execution_seconds_before':model_active[rid]+constructor_active[rid]}
                if r and constructor_active[rid]:
                    timeout=row.get('metadata',{}).get('timeout_seconds')
                    check(finite(timeout,1) and timeout<=min(180,r['wall_seconds']-model_active[rid]-constructor_active[rid])+1e-9,
                          'model timeout ignores consumed constructor wall')
            elif event=='constructor_reserve':
                meta=row.get('metadata',{});source=meta.get('model_call_id');source_row=starts.get(source,{})
                sec=row.get('requested_seconds')
                check(research is not None and r is not None and r.get('arm')=='C' and row.get('arm')=='C',
                      'constructor lacks preceding research C registration')
                if r:
                    check(row.get('run_id')==r['run_id'] and row.get('amendment_id')==r['amendment_id'], 'constructor registration identity differs')
                    check(finite(sec) and 0<sec<=5 and sec<=r['wall_seconds']-model_active[rid]-constructor_active[rid]+1e-9,
                          'constructor request exceeds soft or registered wall cap')
                check(meta.get('actual_constructor_module')==MODULE and meta.get('actual_constructor_function')==FUNCTION and meta.get('method')=='constructive',
                      'constructor implementation differs from shared A tool')
                check(type(meta.get('max_candidate_evaluations')) is int and meta['max_candidate_evaluations']==250000 and
                      type(meta.get('max_slots_per_machine')) is int and 1<=meta['max_slots_per_machine']<=8,
                      'constructor candidate/slot bounds differ')
                check(source_row.get('event')=='reserve' and source_row.get('registration_id')==rid and
                      ends.get(source,{}).get('status')=='success', 'constructor source is not a prior completed model call in same run')
                check(source not in sources,'constructor automatically retries/reuses one model choice');sources.add(source)
                if r and type(meta.get('model_index')) is int:
                    check(source_row.get('run_id')==str(Path(r['run_id'])/f"model_{meta['model_index']:03d}"),'constructor model index differs from ledger')
                else:check(False,'constructor model index is missing')
                check(type(meta.get('plan_index')) is int and meta['plan_index']>=0,'constructor plan index invalid')
                for field,value in (('constructor_calls',counts[rid]),('constructor_requested_seconds',requested[rid]),
                    ('constructor_active_seconds',constructor_active[rid]),('active_execution_seconds',model_active[rid]+constructor_active[rid])):
                    check(row.get('run_account_before',{}).get(field)==value,'constructor prior account differs: '+field)
                constructor_admissions[cid]={'registration':r,'model_active_seconds_before':model_active[rid],
                    'constructor_active_seconds_before':constructor_active[rid],'constructor_requested_seconds_before':requested[rid]}
                counts[rid]+=1
                if finite(sec):requested[rid]+=sec
        elif event in ('finish','solver_finish','constructor_finish'):
            expected={'finish':'reserve','solver_finish':'solver_reserve','constructor_finish':'constructor_reserve'}[event]
            if event=='constructor_finish':check(pending.get(cid)==expected and cid not in ends,'constructor finish lacks unique preceding reservation')
            pending.pop(cid,None);ends[cid]=row
            rid=starts.get(cid,{}).get('registration_id');duration=row.get('details',{}).get('duration_seconds')
            if event=='finish' and finite(duration):model_active[rid]+=duration
            if event=='constructor_finish':
                check(finite(duration),'constructor finish loses measured outer duration')
                check(row.get('status') in ('success','failed'),'constructor finish lacks terminal status')
                details=row.get('details',{});sha=details.get('constructor_result_sha256')
                check(isinstance(sha,str) and len(sha)==64 and all(c in '0123456789abcdef' for c in sha),'constructor finish lacks result hash')
                if finite(duration):constructor_active[rid]+=duration
    return {'errors':errors,'model_admissions':model_admissions,'constructor_admissions':constructor_admissions,
            'constructor_active_seconds_by_registration':dict(constructor_active),
            'constructor_requested_seconds_by_registration':dict(requested),
            'pending_constructor_calls':[cid for cid,kind in pending.items() if kind=='constructor_reserve']}


