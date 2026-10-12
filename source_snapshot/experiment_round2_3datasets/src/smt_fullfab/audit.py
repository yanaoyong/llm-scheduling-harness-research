"""Plan-source audit plus independent physical replay and historical diagnostics.

No simulator/controller import is used. Old physical audit is deliberately reused
as a separately implemented event checker, after source validation and a clearly
labelled projection. It does not prove parity with AutoSched or upstream software.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
import hashlib
import json
import math
from pathlib import Path

from .metrics import compute_metrics, read_events

AUDIT_VERSION = "smt-fullfab-independent-plan-audit-v3"
PHYSICAL_KINDS = {"initial", "release", "ready", "skip", "dispatch", "downtime",
                  "operation_complete", "rework", "lot_complete", "terminal"}
CONTROL_KINDS = {"plan_committed", "coverage_gap", "plan_invalidated", "time_advance",
                 "decision_opportunity", "action", "plan_exhausted", "snapshot_loaded"}


def _number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def audit_plan_sources(source):
    """Prove exact source of every actual production dispatch from submitted plans.

    Declared control-domain coverage and actual dispatch provenance are different
    from proof of absence of omitted opportunities; that latter claim is withheld.
    """
    events = read_events(source)
    errors, plans, active, done, pending = [], {}, None, set(), defaultdict(list)
    dispatches, virtual, gaps, opportunity_records = [], [], [], []

    def check(ok, message):
        if not ok and len(errors) < 200:
            errors.append(message)

    if not events or events[0].get("kind") != "initial":
        return {"valid": False, "errors": ["missing initial manifest"], "audit_version": AUDIT_VERSION}
    manifest = events[0]["manifest"]
    machines = {m["id"]: m for m in manifest["machines"]}
    manifest_lots = {lot["id"]: lot for lot in manifest["lots"]}
    production = {mid for mid, m in machines.items() if m["group"] != "Delay_32"}
    declared = set(manifest["controlled_machine_ids"])
    check(declared == production, "declared controller domain does not exactly equal all production machines")
    previous = events[0]["time"]
    for index, event in enumerate(events):
        t, kind = event.get("time"), event.get("kind")
        check(event.get("seq") == index, f"{index}: sequence gap")
        if not _number(t):
            check(False, f"{index}: invalid time")
            continue
        check(t >= previous, f"{index}: time reversed")
        previous = t
        check(kind in PHYSICAL_KINDS | CONTROL_KINDS, f"{index}: unknown or unsupported event {kind}")
        try:
            if kind == "plan_committed":
                plan = event["plan"]
                version = plan["version"]
                check(isinstance(version, (str, int)) and not isinstance(version, bool), f"{index}: invalid version")
                check(version not in plans, f"{index}: duplicate plan version")
                for key in ("created_at", "valid_until", "freeze_until"):
                    check(_number(plan[key]), f"{index}: invalid {key}")
                check(plan["created_at"] == t, f"{index}: commit time differs from creation time")
                check(t <= plan["freeze_until"] <= plan["valid_until"] <= manifest["horizon"] and t < plan["valid_until"], f"{index}: invalid plan/freeze interval")
                check(sorted(plan["scope"]) == sorted(production), f"{index}: plan scope does not explicitly include every production machine")
                check(isinstance(plan["reason"], str) and bool(plan["reason"].strip()), f"{index}: missing revision reason")
                tasks, new_pending = {}, defaultdict(list)
                identities = set()
                for task in plan["tasks"]:
                    tid, mid = task["id"], task["machine"]
                    check(isinstance(tid, (str, int)) and not isinstance(tid, bool), f"{index}: invalid task id")
                    check(tid not in tasks, f"{index}: duplicate task id")
                    check(mid in production, f"{index}: planned non-production/unknown machine")
                    check(bool(task["lot_ids"]) and len(set(task["lot_ids"])) == len(task["lot_ids"]), f"{index}: empty/duplicate task lots")
                    check(len(task["steps"]) == len(task["lot_ids"]) == len(task["visits"]), f"{index}: task operation arity")
                    planned_steps = []
                    for lid, step, visit in zip(task["lot_ids"], task["steps"], task["visits"]):
                        check(lid in manifest_lots, f"{index}: planned unknown lot")
                        check(type(step) is int and type(visit) is int and step > 0 and visit > 0, f"{index}: invalid planned step/visit")
                        if lid in manifest_lots and type(step) is int:
                            route = manifest["routes"][manifest_lots[lid]["route"]]
                            check(1 <= step <= len(route), f"{index}: planned step outside route")
                            if 1 <= step <= len(route):
                                s = route[step - 1]
                                planned_steps.append((manifest_lots[lid]["part"], s))
                                check(mid in machines and s["family"] == machines[mid]["family"], f"{index}: planned unqualified machine")
                    if planned_steps:
                        part, first = planned_steps[0]
                        check(first["batch_min"] <= len(task["lot_ids"]) <= first["batch_max"], f"{index}: planned batch outside bounds")
                        check(all((p, s["step"], s["name"]) == (part, first["step"], first["name"]) for p, s in planned_steps), f"{index}: planned incompatible batch")
                    check(_number(task["not_before"]), f"{index}: invalid not_before")
                    frozen_carry = bool(active is not None and t < plans[active]["freeze_until"] and
                                        tid in pending[mid] and plans[active]["task_map"][tid] == task and
                                        task["not_before"] < plans[active]["freeze_until"])
                    check((t <= task["not_before"] or frozen_carry) and task["not_before"] <= plan["valid_until"],
                          f"{index}: task outside plan validity or not an exact frozen carry")
                    if task.get("latest_start") is not None:
                        check(_number(task["latest_start"]) and task["latest_start"] >= task["not_before"], f"{index}: invalid latest_start")
                    if task.get("expected_start") is not None:
                        check(_number(task["expected_start"]) and task["expected_start"] >= task["not_before"], f"{index}: invalid expected_start")
                    for identity in zip(task["lot_ids"], task["steps"], task["visits"]):
                        check(identity not in identities, f"{index}: duplicate planned lot operation")
                        identities.add(identity)
                    tasks[tid] = task
                    new_pending[mid].append(tid)
                if active is not None:
                    old = plans[active]
                    frozen_by_machine = defaultdict(list)
                    for mid, tids in pending.items():
                        for tid in tids:
                            task = old["task_map"][tid]
                            planned_start = task["not_before"]
                            if planned_start < old["freeze_until"] and t < old["freeze_until"]:
                                frozen_by_machine[mid].append(tid)
                                check(tid in tasks and tasks[tid] == task, f"{index}: changed or dropped frozen task {tid}")
                    if frozen_by_machine:
                        check(plan["freeze_until"] >= old["freeze_until"],
                              f"{index}: shortened prior freeze interval with pending frozen tasks")
                    for mid, frozen_ids in frozen_by_machine.items():
                        check([tid for tid in new_pending[mid] if tid in frozen_ids] == frozen_ids,
                              f"{index}: reordered frozen tasks")
                holds = plan.get("holds", [])
                hold_keys = set()
                for hold in holds:
                    check(hold["machine"] in production, f"{index}: hold non-production machine")
                    hold_key = (hold["machine"], hold.get("after_task_id"))
                    check(hold_key not in hold_keys, f"{index}: duplicate hold activation condition")
                    check(_number(hold["until"]) and t < hold["until"] <= plan["valid_until"], f"{index}: invalid hold interval")
                    check(bool(hold.get("reason")), f"{index}: hold missing reason")
                    if hold.get("after_task_id") is not None:
                        task = tasks.get(hold["after_task_id"])
                        check(task is not None and task["machine"] == hold["machine"], f"{index}: conditional hold refers to no task on its machine")
                    hold_keys.add(hold_key)
                plans[version] = {**plan, "task_map": tasks}
                active, pending = version, new_pending
            elif kind == "dispatch":
                mid = event["machine"]
                check(mid in machines, f"{index}: unknown dispatch machine")
                if mid not in production:
                    check(event.get("owner") == "environment", f"{index}: virtual process has controller ownership")
                    virtual.append(event)
                    continue
                dispatches.append(event)
                check(event.get("owner") == "plan", f"{index}: production dispatch missing plan ownership")
                version, tid = event.get("plan_version"), event.get("plan_task_id")
                check(version in plans, f"{index}: missing committed source plan")
                check(version == active, f"{index}: dispatch references superseded plan")
                if version not in plans:
                    continue
                plan = plans[version]
                check(tid in plan["task_map"], f"{index}: missing source task")
                if tid not in plan["task_map"]:
                    continue
                task = plan["task_map"][tid]
                check((version, tid) not in done, f"{index}: task dispatched twice")
                check(bool(pending[mid]) and pending[mid][0] == tid, f"{index}: machine task order changed")
                for trace_key, task_key in (("machine", "machine"), ("lots", "lot_ids"), ("steps", "steps"), ("visits", "visits")):
                    check(event[trace_key] == task[task_key], f"{index}: dispatch differs from plan {task_key}")
                check(plan["created_at"] <= t <= plan["valid_until"], f"{index}: dispatch outside plan interval")
                check(t >= task["not_before"], f"{index}: dispatch before start condition")
                if task.get("latest_start") is not None:
                    check(t <= task["latest_start"], f"{index}: dispatch after latest_start")
                for hold in plan.get("holds", []):
                    hold_active = hold.get("after_task_id") is None or ((version, hold["after_task_id"]) in done and not pending[hold["machine"]])
                    check(hold["machine"] != mid or not hold_active or t >= hold["until"], f"{index}: dispatch during explicit hold")
                done.add((version, tid))
                if tid in pending[mid]:
                    pending[mid].remove(tid)
            elif kind == "coverage_gap":
                gaps.append(event)
            elif kind == "decision_opportunity":
                opportunity_records.append(event)
            elif kind == "snapshot_loaded":
                check(events[0]["time"] == 0 and event.get("prefix_event_count") == index,
                      f"{index}: snapshot lacks complete prehistory prefix")
                sha = event.get("snapshot_sha256", "")
                check(isinstance(sha, str) and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha),
                      f"{index}: invalid snapshot state hash")
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            check(False, f"{index}: malformed plan/trace: {exc}")
    return {"valid": not errors, "errors": errors, "audit_version": AUDIT_VERSION,
            "production_machine_count": len(production), "declared_control_machine_count": len(declared),
            "declared_full_factory_domain": declared == production,
            "production_dispatches": len(dispatches), "virtual_process_dispatches": len(virtual),
            "production_machines_with_dispatch": len({e["machine"] for e in dispatches}),
            "plans_committed": len(plans), "coverage_gap_events": len(gaps),
            "coverage_gap_details": gaps, "decision_opportunity_events": len(opportunity_records),
            "explicit_hold_count": sum(len(plan.get("holds", [])) for plan in plans.values()),
            "actual_dispatch_provenance_complete": bool(dispatches) and not errors,
            "absence_of_unreported_legal_demand_certified": False,
            "scope": "exact production dispatch provenance and declared responsibility; legal-demand completeness requires additional independent opportunity replay"}


def audit_opportunity_coverage(source):
    """Rebuild legal demand at every declared clock advance independently.

    There is no environment import and no use of reported candidate counts. The
    source-bound physical checker separately verifies all consumed event values.
    Explicit pending tasks/holds count as an intentional plan, even when waiting
    for a future target. Unplanned lots and choice counts remain visible.
    """
    events = read_events(source)
    if not events or events[0].get("kind") != "initial":
        return {"valid": False, "errors": ["opportunity replay missing initial manifest"]}
    manifest = events[0]["manifest"]
    machines = {m["id"]: m for m in manifest["machines"]}
    production = {mid for mid, m in machines.items() if m["group"] != "Delay_32"}
    production_families = {machines[mid]["family"] for mid in production}
    lots = {lot["id"]: dict(lot, dedication={}) for lot in manifest["lots"]}
    waiting, ready = defaultdict(set), {}
    ms = {mid: {"ready": 0, "down": 0, "setup": "", "min_left": 0, "min_setup": ""} for mid in machines}
    jobs, machine_jobs = {}, defaultdict(set)
    pending, plan, holds = defaultdict(list), None, {}
    executed_tasks = set()
    errors, family = [], defaultdict(Counter)
    advances, advance_seconds, intervals_checked, maximum_combinations = 0, 0.0, 0, 0
    permitted_until, previous = events[0]["time"], events[0]["time"]
    ever_ready_ops, ever_planned_ops, reported_gaps = set(), set(), []
    completed_lots = set()
    unplanned_since, unplanned_wait = {}, 0.0

    def check(ok, message):
        if not ok and len(errors) < 200:
            errors.append(message)

    def step_for(lid, step):
        return manifest["routes"][lots[lid]["route"]][step - 1]

    def planned_ops():
        return {identity for tasks in pending.values() for task in tasks
                for identity in zip(task["lot_ids"], task["steps"], task["visits"])}

    def hold_until(mid, t):
        active_holds = [hold["until"] for hold in holds.get(mid, []) if hold.get("after_task_id") is None or
                        ((plan["version"], hold["after_task_id"]) in executed_tasks and not pending[mid])]
        return max(active_holds, default=t)

    def sync_unplanned(t):
        nonlocal unplanned_wait
        covered = planned_ops()
        active = {(lid, value["step"], value["visit"]) for lid, value in ready.items()
                  if value["family"] in production_families}
        needed = active - covered
        for identity in list(unplanned_since):
            if identity not in needed:
                unplanned_wait += max(0, t - unplanned_since.pop(identity))
        for identity in needed:
            unplanned_since.setdefault(identity, t)

    def candidates(mid, t):
        m, state = machines[mid], ms[mid]
        # Discard physically freed slots at the current observed event time;
        # hypothetical later boundaries must not mutate the replay into future.
        machine_jobs[mid] = {jid for jid in machine_jobs[mid] if jobs[jid]["process_end"] > previous}
        if max(state["ready"], state["down"]) > t:
            return {}, 0, 0
        if sum(jobs[jid]["process_end"] > t for jid in machine_jobs[mid]) >= (2 if m["cascading"] else 1):
            return {}, 0, 0
        groups = defaultdict(list)
        for lid in waiting[m["family"]]:
            value = ready[lid]
            s = step_for(lid, value["step"])
            if lots[lid]["dedication"].get(str(value["step"]), mid) != mid:
                continue
            if state["min_left"] > 0 and state["min_setup"] != s["setup"]:
                continue
            groups[(lots[lid]["part"], s["step"], s["name"])].append(lid)
        count = sum(len(g) for g in groups.values())
        combinations = 0
        for group in groups.values():
            s = step_for(group[0], ready[group[0]]["step"])
            combinations += sum(math.comb(len(group), size) for size in range(s["batch_min"], min(s["batch_max"], len(group)) + 1))
        return groups, count, combinations

    def dispatch_opportunity(mid, t):
        nonlocal maximum_combinations
        groups, count, combinations = candidates(mid, t)
        stats = family[machines[mid]["family"]]
        stats["actual_dispatch_checks"] += 1
        stats["candidate_lot_memberships_at_dispatch"] += count
        stats["legal_machine_batch_combinations_at_dispatch"] += combinations
        stats["singleton_immediate_dispatches"] += combinations == 1
        stats["multiple_choice_immediate_dispatches"] += combinations > 1
        maximum_combinations = max(maximum_combinations, combinations)
        processing, setups = set(), set()
        for group in groups.values():
            s = step_for(group[0], ready[group[0]]["step"])
            if len(group) < s["batch_min"]:
                continue
            d = s["processing"]
            processing.add(d.get("c", d.get("m", d.get("mean"))) + machines[mid]["load"] + machines[mid]["unload"])
            setup = 0
            if s["setup"] and s["setup"] != ms[mid]["setup"]:
                setup = s["setup_time"]
                if setup is None:
                    table = {(x["old"], x["new"]): x["seconds"] for x in manifest["setups"]}
                    setup = table.get((ms[mid]["setup"], s["setup"]), table.get(("", s["setup"]), 0))
            setups.add(setup)
        stats["dispatch_checks_with_processing_variation"] += len(processing) > 1
        stats["dispatch_checks_with_setup_variation"] += len(setups) > 1
        stats["dispatch_checks_with_nonzero_setup_option"] += any(x > 0 for x in setups)
        check(combinations > 0, f"time {t}: production dispatch on machine {mid} had no independent legal batch")

    for index, event in enumerate(events):
        try:
            t, kind = event["time"], event["kind"]
            check(t >= previous, f"{index}: opportunity time reversed")
            if t > previous:
                check(t <= permitted_until + 1e-6, f"{index}: clock changed without declared time_advance coverage")
            previous = t
            if kind == "ready":
                lid = event["lot"]
                s = step_for(lid, event["step"])
                ready[lid] = {"step": event["step"], "visit": event["visit"], "family": s["family"], "since": t}
                waiting[s["family"]].add(lid)
                if s["family"] in production_families:
                    ever_ready_ops.add((lid, event["step"], event["visit"]))
                sync_unplanned(t)
            elif kind == "plan_committed":
                plan = event["plan"]
                pending = defaultdict(list)
                for task in plan["tasks"]:
                    pending[task["machine"]].append(task)
                    ever_planned_ops.update(zip(task["lot_ids"], task["steps"], task["visits"]))
                    for lid, step in zip(task["lot_ids"], task["steps"]):
                        check(lots[lid]["dedication"].get(str(step), task["machine"]) == task["machine"],
                              f"{index}: plan violates independently reconstructed historical binding")
                holds = defaultdict(list)
                for hold in plan.get("holds", []):
                    holds[hold["machine"]].append(hold)
                sync_unplanned(t)
            elif kind == "dispatch":
                mid, jid = event["machine"], event["job"]
                if mid in production:
                    dispatch_opportunity(mid, t)
                    pending[mid] = [task for task in pending[mid] if task["id"] != event.get("plan_task_id")]
                    executed_tasks.add((event.get("plan_version"), event.get("plan_task_id")))
                s = step_for(event["lots"][0], event["steps"][0])
                if event["setup_seconds"] > 0 and s["setup"] in manifest["min_runs"] and ms[mid]["min_left"] == 0:
                    ms[mid]["min_left"] = manifest["min_runs"][s["setup"]]
                    ms[mid]["min_setup"] = s["setup"]
                ms[mid]["min_left"] = max(0, ms[mid]["min_left"] - len(event["lots"]))
                ms[mid].update(ready=event["machine_ready"], setup=event["setup_after"])
                jobs[jid] = {"process_end": event["process_end"], "machine": mid}
                machine_jobs[mid].add(jid)
                for lid, step in zip(event["lots"], event["steps"]):
                    value = ready.pop(lid)
                    waiting[value["family"]].remove(lid)
                    dedicated = step_for(lid, step)["dedicate_for"]
                    if dedicated is not None:
                        lots[lid]["dedication"][str(dedicated)] = mid
                sync_unplanned(t)
            elif kind == "downtime":
                mid = event["machine"]
                ms[mid].update(ready=event["machine_ready"], down=event["blocked_until"], setup="")
                for jid in event["affected_jobs"]:
                    jobs[jid]["process_end"] += event["duration"]
            elif kind == "coverage_gap":
                expected = []
                for mid in sorted(production):
                    active = plan is not None and t <= plan["valid_until"]
                    if active and (pending[mid] or hold_until(mid, t) > t):
                        continue
                    _, count, combinations = candidates(mid, t)
                    if combinations:
                        expected.append({"machine": mid, "family": machines[mid]["family"], "candidate_count": count})
                check(event.get("machines") == expected, f"{index}: reported coverage gap differs from independently reconstructed legal demand")
                reported_gaps.append({"time": t, "independent_machine_count": len(expected)})
            elif kind == "time_advance":
                target = event["to"]
                check(_number(target) and t < target <= manifest["horizon"], f"{index}: invalid time_advance target")
                check(t >= permitted_until - 1e-6, f"{index}: overlapping or unfinished time_advance interval")
                permitted_until = target
                advances += 1
                advance_seconds += target - t
                boundaries = {t}
                # A fabricated large jump must not skip machine release, slot
                # release, task start condition, plan expiry, or hold expiry.
                for mid in production:
                    boundaries.update(x for x in (ms[mid]["ready"], ms[mid]["down"], hold_until(mid, t)) if t < x < target)
                    boundaries.update(jobs[jid]["process_end"] for jid in machine_jobs[mid] if t < jobs[jid]["process_end"] < target)
                    # Only the submitted head task may execute. Crossing its
                    # not_before can make it executable without a physical event.
                    if pending[mid] and t < pending[mid][0]["not_before"] < target:
                        boundaries.add(pending[mid][0]["not_before"])
                if plan and t < plan["valid_until"] < target:
                    boundaries.add(plan["valid_until"])
                for at in sorted(boundaries):
                    intervals_checked += 1
                    for mid in sorted(production):
                        groups, count, combinations = candidates(mid, at)
                        stats = family[machines[mid]["family"]]
                        stats["clock_boundary_machine_checks"] += 1
                        if not combinations:
                            continue
                        stats["legal_demand_clock_checks"] += 1
                        active = plan is not None and at < plan["valid_until"]
                        planned = active and bool(pending[mid])
                        held = active and hold_until(mid, at) > at
                        stats["explicit_pending_task_clock_checks"] += bool(planned)
                        stats["explicit_hold_clock_checks"] += bool(held)
                        check(planned or held,
                              f"{index}: unplanned legal demand on machine {mid} at {at} while advancing to {target}; candidates={count}, combinations={combinations}")
                        if planned and not held:
                            task = pending[mid][0]
                            eligible_lots = {lid for group in groups.values() for lid in group}
                            exact_ready = all(lid in ready and ready[lid]["step"] == step and ready[lid]["visit"] == visit
                                              for lid, step, visit in zip(task["lot_ids"], task["steps"], task["visits"]))
                            executable = exact_ready and set(task["lot_ids"]) <= eligible_lots and task["not_before"] <= at
                            check(not executable, f"{index}: executable submitted task {task['id']} on machine {mid} not run before clock advance at {at}")
                            obsolete = any(lid in completed_lots or
                                           (lid in ready and (ready[lid]["step"] > step or
                                            (ready[lid]["step"] == step and ready[lid]["visit"] > visit)))
                                           for lid, step, visit in zip(task["lot_ids"], task["steps"], task["visits"]))
                            check(not obsolete, f"{index}: obsolete pending task masks uncovered legal demand on machine {mid}")
            elif kind == "lot_complete":
                completed_lots.add(event["lot"])
            elif kind == "terminal":
                check(t <= permitted_until + 1e-6, f"{index}: terminal without complete clock advance declaration")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            check(False, f"{index}: malformed opportunity evidence: {exc}")
    end = events[-1]["time"]
    unplanned_wait += sum(max(0, end - since) for since in unplanned_since.values())
    current = {(lid, value["step"], value["visit"]) for lid, value in ready.items() if value["family"] in production_families}
    for name in sorted(production_families):
        family[name]["production_machine_count"] = sum(machines[mid]["family"] == name for mid in production)
    return {"valid": not errors, "errors": errors, "audit_version": "smt-fullfab-opportunity-audit-v2",
            "time_advance_events": advances, "automatic_simulation_advance_seconds": advance_seconds,
            "clock_boundary_sweeps": intervals_checked,
            "physical_event_values_require_independent_replay": True,
            "unreported_uncovered_legal_demand_absent": not errors,
            "family_opportunities": {name: dict(stats) for name, stats in sorted(family.items())},
            "max_immediate_machine_batch_combinations_at_dispatch": maximum_combinations,
            "reported_coverage_gaps_rechecked": reported_gaps,
            "production_ready_operation_visits": len(ever_ready_ops),
            "ready_operation_visits_never_in_any_plan": len(ever_ready_ops - ever_planned_ops),
            "terminal_ready_operation_visits_never_in_any_plan": len(current - ever_planned_ops),
            "terminal_ready_unplanned_operation_visits": [list(identity) for identity in sorted(unplanned_since)],
            "ready_wait_without_current_plan_lot_seconds": unplanned_wait,
            "max_terminal_unplanned_ready_seconds": max((end - since for since in unplanned_since.values()), default=0),
            "count_interpretation": "dispatch-time legal choices and clock-boundary sweeps are descriptive repeated observations, not independent statistical samples or model decisions"}


def audit_trace(source, verify_data_dir=None, *, window_start=0, priority_weights=None):
    events = read_events(source)
    provenance = audit_plan_sources(events)
    if not events or events[0].get("kind") != "initial":
        return provenance
    errors = list(provenance["errors"])
    opportunities = audit_opportunity_coverage(events)
    errors.extend("opportunity: " + x for x in opportunities["errors"])
    snapshot_root = any(e.get("kind") == "snapshot_loaded" and
                        (events[0]["time"] != 0 or e.get("prefix_event_count") != index)
                        for index, e in enumerate(events))
    physical, metrics = None, None
    if snapshot_root:
        errors.append("snapshot root requires validated prehistory; no cold-start substitution allowed")
    else:
        # This synthetic action is only an adapter for the old physical checker.
        # Its source is independently checked above and never claimed as a model act.
        projected, decision = [], 0
        for event in events:
            if event["kind"] not in PHYSICAL_KINDS:
                continue
            e = copy.deepcopy(event)
            if e["kind"] == "dispatch" and e["machine"] in events[0]["manifest"]["controlled_machine_ids"]:
                projected.append({"seq": len(projected), "time": e["time"], "kind": "action", "decision": decision,
                                  "action": {"dispatches": [{"machine": e["machine"], "lot_ids": e["lots"]}], "wait_seconds": 0}})
                decision += 1
                e["owner"] = "controller"
            if e["kind"] == "terminal":
                e["metrics"] = {}
            e["seq"] = len(projected)
            projected.append(e)
        try:
            from src.smt.audit import audit_trace as physical_replay
            physical = physical_replay(projected, verify_data_dir)
            errors.extend("physical: " + x for x in physical["errors"])
        except (KeyError, ValueError, TypeError, IndexError) as exc:
            errors.append(f"physical replay malformed trace: {exc}")
        try:
            metrics = compute_metrics(events, window_start=window_start, priority_weights=priority_weights)
        except (KeyError, ValueError, TypeError, IndexError) as exc:
            errors.append(f"metric reconstruction: {exc}")
    provenance["absence_of_unreported_legal_demand_certified"] = bool(not errors and physical and physical["valid"] and opportunities["valid"])
    provenance["scope"] = "exact production dispatch provenance, full declared responsibility, and independent legal-demand checks at every declared clock advance"
    return {"valid": not errors, "errors": errors, "audit_version": AUDIT_VERSION,
            "event_count": len(events), "plan_source_audit": provenance,
            "opportunity_audit": opportunities, "physical_replay": physical, "metrics": metrics,
            "verified_input_hashes": bool(physical and physical.get("verified_input_hashes")),
            "official_simulator_equivalence_certified": False}


def _hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _combinations(machine):
    groups = defaultdict(list)
    for candidate in machine["candidates"]:
        groups[tuple(candidate["batch_key"])].append(candidate)
    counts = []
    for group in groups.values():
        low, high = group[0]["batch_min"], group[0]["batch_max"]
        if any((c["batch_min"], c["batch_max"]) != (low, high) for c in group):
            raise ValueError("inconsistent batch bounds in saved candidate group")
        counts.append({"batch_key": group[0]["batch_key"], "candidate_lots": len(group),
                       "batch_min": low, "batch_max": high,
                       "immediate_combinations": sum(math.comb(len(group), size) for size in range(low, min(high, len(group)) + 1))})
    return sum(row["immediate_combinations"] for row in counts), counts


def review_history(root, output_dir):
    """Read old states/actions/traces and write only to the new history namespace."""
    root, output = Path(root).resolve(), Path(output_dir).resolve()
    if output != root / "artifacts/smt_fullfab_history":
        raise ValueError("history output must be artifacts/smt_fullfab_history; old outputs are protected")
    phase = root / "runs/acceptance_smt_v1"
    hashes, rows, runs, observed_actions = {}, [], [], {}
    for run in sorted(phase.iterdir()):
        if not run.is_dir() or not (run / "result.json").exists():
            continue
        result = json.loads((run / "result.json").read_text())
        raw_events = read_events(run / "trace.jsonl")
        action_events = [{"time": e["time"], "decision": e["decision"], "action": e["action"]}
                         for e in raw_events if e["kind"] == "action"]
        observed_actions[(result["scenario"], result["arm"], result["repeat"])] = action_events
        manifest = raw_events[0]["manifest"]
        machines = {m["id"]: m for m in manifest["machines"]}
        production = {mid for mid, m in machines.items() if m["group"] != "Delay_32"}
        actual = [e for e in raw_events if e["kind"] == "dispatch" and e["machine"] in production]
        controlled = [e for e in actual if e["machine"] in manifest["controlled_machine_ids"]]
        runs.append({"run": run.name, "scenario": result["scenario"], "arm": result["arm"], "repeat": result["repeat"],
                     "reported_status": result["status"], "physical_machines": len(production),
                     "controlled_machine_ids": manifest["controlled_machine_ids"],
                     "horizon_seconds": manifest["horizon"], "decision_events": len(action_events),
                     "production_dispatches": len(actual), "controlled_production_dispatches": len(controlled),
                     "background_production_dispatches": len(actual) - len(controlled),
                     "controlled_dispatch_fraction": len(controlled) / len(actual) if actual else None})
        for path in [run / "result.json", run / "trace.jsonl", *sorted(run.glob("state_*.json")), *sorted(run.glob("action_*.json"))]:
            hashes[str(path.relative_to(root))] = _hash(path)
        for state_path in sorted(run.glob("state_*.json")):
            state = json.loads(state_path.read_text())
            for machine in state["machines"]:
                candidates = machine["candidates"]
                combinations, groups = _combinations(machine)
                rows.append({"run": run.name, "scenario": result["scenario"], "arm": result["arm"], "repeat": result["repeat"],
                             "state_file": str(state_path.relative_to(root)), "decision": state["decision_count"],
                             "time": state["time"], "machine": machine["machine"], "ready_now": machine["ready_now"],
                             "candidate_lots": len(candidates), "immediate_combinations": combinations,
                             "unique_expected_processing_seconds": sorted({c["expected_processing_seconds"] for c in candidates}),
                             "unique_setup_seconds": sorted({c["setup_seconds"] for c in candidates}),
                             "priority_values": sorted({c["priority"] for c in candidates}),
                             "due_values_count": len({c["due"] for c in candidates}), "groups": groups})
    pairs = []
    for scenario, arm, repeat in sorted(observed_actions):
        if arm != "A":
            continue
        left, right = observed_actions[(scenario, "A", repeat)], observed_actions.get((scenario, "C", repeat))
        pairs.append({"scenario": scenario, "repeat": repeat, "A_run": f"smt{scenario}_A_r{repeat}",
                      "C_run": f"smt{scenario}_C_r{repeat}", "exact_action_time_sequence_equal": left == right,
                      "action_count_A": len(left), "action_count_C": len(right) if right is not None else None})
    nonempty = [r for r in rows if r["candidate_lots"]]
    final801 = []
    for run in runs:
        if run["scenario"] != 801:
            continue
        batch_rows = [r for r in rows if r["run"] == run["run"] and r["machine"] == 790 and r["candidate_lots"]]
        if batch_rows:
            final801.append(max(batch_rows, key=lambda row: row["decision"]))
    summary = {
        "review_version": "historical-local-design-review-v1", "source_phase": "acceptance_smt_v1",
        "run_count": len(runs), "state_machine_observations": len(rows),
        "nonempty_candidate_observations": len(nonempty),
        "all_nonempty_observations_equal_expected_processing_within_machine_state": all(len(r["unique_expected_processing_seconds"]) == 1 for r in nonempty),
        "all_recorded_candidate_setup_seconds_zero": all(r["unique_setup_seconds"] == [0] for r in nonempty),
        "initial_observations": [{k: r[k] for k in ("run", "machine", "candidate_lots", "immediate_combinations")} for r in rows if r["decision"] == 0],
        "scenario801_final_batch_observations": [{k: r[k] for k in ("run", "decision", "time", "candidate_lots", "immediate_combinations")} for r in final801],
        "paired_A_C": pairs, "paired_A_C_all_identical": all(p["exact_action_time_sequence_equal"] for p in pairs),
        "runs": runs, "candidate_observations": rows,
        "limits": ["Claims apply only to saved legal-candidate observations in these 27 old local runs.",
                   "Combination counts enumerate immediate batches, not wait/future sequencing decisions.",
                   "Observed A/C action equality does not prove C has no value in other designs.",
                   "This diagnostic re-read does not replace complete physical replay or authenticate model ownership."]}
    output.mkdir(parents=True, exist_ok=True)
    (output / "historical_review.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    (output / "input_sha256.json").write_text(json.dumps(hashes, ensure_ascii=False, indent=2) + "\n")
    return {k: v for k, v in summary.items() if k not in ("candidate_observations", "runs", "initial_observations")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    history = sub.add_parser("history")
    history.add_argument("--root", default=".")
    trace = sub.add_parser("trace")
    trace.add_argument("path")
    trace.add_argument("--verify-data-dir")
    args = parser.parse_args()
    if args.command == "history":
        result = review_history(args.root, Path(args.root) / "artifacts/smt_fullfab_history")
    else:
        result = audit_trace(args.path, args.verify_data_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if args.command == "history" or result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
