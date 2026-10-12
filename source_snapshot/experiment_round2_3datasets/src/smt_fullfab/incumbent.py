"""Explicit classical finite-window list-scheduling incumbent and nominal audit.

Only A/C may call this module. It produces whole future plans; the executor has
no access to its choices and performs no fallback. The independent audit below
recomputes feasibility from the input rather than trusting CP-SAT status.
"""
from __future__ import annotations

from collections import defaultdict
import heapq
import math
import time


def _inputs(problem, weights):
    from .optimizer import DEFAULT_WEIGHTS, _normalise, _ceil, _number
    now, horizon, machines, operations = _normalise(problem)
    selected_weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    if set(selected_weights) != set(DEFAULT_WEIGHTS) or any(type(v) is not int or not 0 <= v <= 100000 for v in selected_weights.values()):
        raise ValueError("invalid incumbent objective weights")
    transitions = problem.get("setup_transitions", [])
    if isinstance(transitions, dict):
        setup_map = {(old, new): _ceil(_number(seconds, "setup", nonnegative=True))
                     for old, choices in transitions.items() for new, seconds in choices.items()}
    else:
        setup_map = {(row["old"], row["new"]): _ceil(_number(row["seconds"], "setup", nonnegative=True)) for row in transitions}
    max_setup = max([0, *setup_map.values(), *(o["setup_time"] or 0 for o in operations.values())])
    bound = horizon + max([1, *(max(p + o["transport"], occ) + max_setup
                               for o in operations.values() for p, occ in o["times"].values())])
    return now, horizon, machines, operations, setup_map, selected_weights, bound


def _setup_seconds(old, operation, transitions):
    new = operation["setup"]
    if not new or old == new:
        return 0
    override = operation["setup_time"]
    return override if override is not None else transitions.get((old, new), transitions.get(("", new), 0))


def nominal_objective(problem, tasks, weights=None):
    now, _, _, operations, _, selected_weights, bound = _inputs(problem, weights)
    chosen = {oid: task for task in tasks for oid in task["operation_ids"]}
    total = 0
    for oid, operation in operations.items():
        end = int(round(chosen[oid]["end"] - now)) if oid in chosen else bound
        tardiness = max(0, end + operation["remaining"] - operation["due_relative"])
        total += operation["priority_coefficient"] * (
            selected_weights["completion"] * int(oid in chosen)
            - selected_weights["flow"] * end - selected_weights["tardiness"] * tardiness)
    return total - selected_weights["setup"] * sum(task["setup_seconds"] for task in tasks)


def validate_nominal_plan(problem, plan, *, max_slots_per_machine=None,
                          require_candidate_pool=True):
    """Recompute nominal hard constraints; no solver status or builder state.

    This checks declared expected timing, not realized stochastic feasibility.
    The event/source audit remains necessary after simulation execution.
    """
    now, horizon, machines, operations, transitions, _, _ = _inputs(problem, None)
    from .optimizer import _candidate_batches
    allowed_batches = ({(tuple(batch["operation_ids"]), mid)
                        for batch in _candidate_batches(operations) for mid in batch["machines"]}
                       if require_candidate_pool else None)
    errors = []
    tasks_by_machine = defaultdict(list)
    selected = {}
    for task in plan["tasks"]:
        if task["machine"] not in machines:
            errors.append("unknown machine"); continue
        tasks_by_machine[task["machine"]].append(task)
        for oid in task["operation_ids"]:
            if oid not in operations or oid in selected:
                errors.append("unknown or repeated operation: " + oid)
            selected[oid] = task
    if sorted(plan.get("scope", [])) != sorted(machines):
        errors.append("scope differs from all input machines")
    for mid, tasks in tasks_by_machine.items():
        machine = machines[mid]
        previous_end = now + machine["available"]
        previous_setup = machine["current_setup"]
        min_left = machine["min_left"]
        min_setup = machine["min_setup"]
        # The shared nominal CP model rounds current remaining processing up
        # to an integer offset too. Keep a single now+offset representation for
        # endpoint identity; never compare independently accumulated floats.
        processing = [(now, now + math.ceil(end - now - 1e-9))
                      for end in machine.get("processing_until", []) if end > now]
        if max_slots_per_machine is not None and len(tasks) > max_slots_per_machine:
            errors.append(f"machine {mid} slot limit")
        ordered = sorted(tasks, key=lambda task: task["sequence"])
        if [task["sequence"] for task in ordered] != list(range(len(ordered))):
            errors.append(f"machine {mid} noncontiguous sequence")
        for task in ordered:
            ids = task["operation_ids"]
            if not ids or any(oid not in operations for oid in ids):
                errors.append("empty/unknown batch"); continue
            batch = [operations[oid] for oid in ids]
            first = batch[0]
            if allowed_batches is not None and (tuple(ids), mid) not in allowed_batches:
                errors.append("batch absent from shared CP candidate pool")
            start = task["start"]
            relative_start = int(round(start - now))
            if abs((start - now) - relative_start) > 1e-8:
                errors.append("planned start is not on the nominal integer time grid")
            if task.get("not_before") != start or task.get("expected_end") != task["end"]:
                errors.append("timing aliases disagree")
            if not now <= start < now + horizon or start + 1e-8 < previous_end:
                errors.append("start outside window or machine tail")
            if any(mid not in operation["eligible_machines"] for operation in batch):
                errors.append("ineligible machine"); continue
            if len({operation["lot_id"] for operation in batch}) != len(batch):
                errors.append("same lot twice in batch")
            if not first["batch_min"] <= len(batch) <= first["batch_max"]:
                errors.append("batch size")
            if any(operation["compatibility"] != first["compatibility"] or operation["times"][mid] != first["times"][mid] for operation in batch):
                errors.append("batch compatibility")
            if task["lot_ids"] != [operation["lot_id"] for operation in batch] or task["steps"] != [operation["step"] for operation in batch] or task["visits"] != [operation["visit"] for operation in batch]:
                errors.append("declared lot/step/visit differs from operations")
            old = previous_setup
            if any(previous_end <= now + a and start >= now + b for a, b in machine["downtimes"]):
                old = ""
            if not first["setup"] or old == first["setup"]:
                setup = 0
            elif first["setup_time"] is not None:
                setup = first["setup_time"]
            else:
                setup = transitions.get((old, first["setup"]), transitions.get(("", first["setup"]), 0))
            p, occupation = first["times"][mid]
            expected_process_end = now + (relative_start + setup + p)
            expected_free = now + (relative_start + setup + occupation)
            expected_lot_end = now + (relative_start + setup + p + first["transport"])
            if any(abs(task[key] - value) > 1e-8 for key, value in
                   (("setup_seconds", setup), ("process_end", expected_process_end),
                    ("occupied_until", expected_free), ("end", expected_lot_end))):
                errors.append("processing/setup/cadence/transport arithmetic")
            if any(start < now + b and expected_process_end > now + a for a, b in machine["downtimes"]):
                errors.append("known downtime overlap")
            if min_left and first["setup"] != min_setup:
                errors.append("minimum-run setup lock")
            if setup > 0 and min_left == 0 and first["setup"] in problem.get("min_runs", {}):
                min_left = problem["min_runs"][first["setup"]]
                min_setup = first["setup"]
            min_left = max(0, min_left - len(batch))
            for operation in batch:
                if start + 1e-8 < now + operation["release"]:
                    errors.append("release time")
                if "latest_start" in operation and start > math.floor(operation["latest_start"] - now) + now:
                    errors.append("latest start")
                for predecessor in operation["predecessor_ids"]:
                    if predecessor not in selected or start + 1e-8 < selected[predecessor]["end"]:
                        errors.append("cross-family precedence")
                dedication = operation.get("same_machine_as")
                if dedication is not None and (dedication not in selected or selected[dedication]["machine"] != mid):
                    errors.append("future machine dedication")
            processing.append((now + relative_start, expected_process_end))
            previous_end, previous_setup = expected_free, first["setup"]
        changes = []
        for start, end in processing:
            changes.extend([(start, 1), (end, -1)])
        count = 0
        for _, delta in sorted(changes):
            count += delta
            if count > (2 if machine["cascading"] else 1):
                errors.append("processing slot capacity"); break
    for frozen in problem.get("frozen_tasks", []):
        matching = [task for task in plan["tasks"] if set(task["operation_ids"]) == set(frozen["operation_ids"])]
        if len(matching) != 1 or matching[0]["machine"] != frozen["machine"] or matching[0]["start"] != frozen.get("start", frozen.get("not_before")):
            errors.append("frozen commitment")
    return {"valid": not errors, "errors": sorted(set(errors)), "checked_tasks": len(plan["tasks"]),
            "checked_operations": len(selected), "scope": "nominal input constraints only"}


def build_incumbent(problem, *, weights=None, max_slots_per_machine=8,
                    plan_version=1, freeze_until=None, rule="gain_rate",
                    max_wall_seconds=1.0, max_candidate_evaluations=250000):
    """Construct an explicitly attributed multi-step classical candidate plan."""
    from .optimizer import _candidate_batches, _ceil
    started = time.perf_counter()
    now, horizon, machines, operations, transitions, selected_weights, end_bound = _inputs(problem, weights)
    if rule not in ("gain_rate", "slack", "priority"):
        raise ValueError("incumbent rule must be gain_rate, slack, or priority")
    if not 0 < max_wall_seconds <= 60 or type(max_candidate_evaluations) is not int or max_candidate_evaluations < 1:
        raise ValueError("invalid incumbent build budget")
    if type(max_slots_per_machine) is not int or not 1 <= max_slots_per_machine <= 128:
        raise ValueError("max_slots_per_machine must be 1..128")
    freeze = now if freeze_until is None else freeze_until
    if not now <= freeze <= now + horizon:
        raise ValueError("invalid freeze_until")
    base = {"model": "classical-fullfab-precedence-list-incumbent-v1", "source": "classical_incumbent",
            "rule": rule, "global_optimality_claim": False}
    if problem.get("frozen_tasks"):
        return {**base, "status": "NOT_BUILT_FROZEN_COMMITMENTS", "plan": None,
                "wall_seconds": time.perf_counter() - started, "objective": None}
    pool = _candidate_batches(operations)
    state = {}
    for mid, machine in machines.items():
        state[mid] = {"tail": now + machine["available"], "setup": machine["current_setup"],
                      "min_left": machine["min_left"], "min_setup": machine["min_setup"],
                      "active_ends": list(machine.get("processing_until", [])), "count": 0, "generation": 0}
    selected = {}
    tasks = []
    ready_batches = set()
    machine_batches = defaultdict(set)
    waiting_on = defaultdict(set)
    heap = []
    evaluations = 0
    stopped = None
    serial = 0

    def ready(batch):
        for oid in batch["operation_ids"]:
            operation = operations[oid]
            if oid in selected or not all(parent in selected for parent in operation["predecessor_ids"]):
                return False
            if operation.get("same_machine_as") is not None and operation["same_machine_as"] not in selected:
                return False
        return True

    def proposal(bi, mid):
        nonlocal evaluations
        evaluations += 1
        batch = pool[bi]
        if not ready(batch) or state[mid]["count"] >= max_slots_per_machine:
            return None
        members = [operations[oid] for oid in batch["operation_ids"]]
        for operation in members:
            source = operation.get("same_machine_as")
            if source is not None and selected[source]["machine"] != mid:
                return None
        current = state[mid]
        first = members[0]
        if current["min_left"] > 0 and current["min_setup"] != first["setup"]:
            return None
        release = max([now + operation["release"] for operation in members] +
                      [selected[parent]["end"] for operation in members for parent in operation["predecessor_ids"]])
        start = max(current["tail"], release)
        active = sorted(end for end in current["active_ends"] if end > start)
        capacity = 2 if machines[mid]["cascading"] else 1
        if len(active) >= capacity:
            start = max(start, active[-capacity])
        p, occupation = batch["machines"][mid]
        # Only rightward shifts occur. Each shift crosses a finite known outage.
        while True:
            start_relative = _ceil(start - now)
            start = now + start_relative
            if start_relative >= horizon:
                return None
            old = current["setup"]
            if any(current["tail"] <= now + a and start >= now + b for a, b in machines[mid]["downtimes"]):
                old = ""
            setup = _setup_seconds(old, first, transitions)
            process_end = now + (start_relative + setup + p)
            overlap = next(((a, b) for a, b in sorted(machines[mid]["downtimes"])
                            if start < now + b and process_end > now + a), None)
            if overlap is None:
                break
            start = now + overlap[1]
        if any("latest_start" in operation and start > now + math.floor(operation["latest_start"] - now) for operation in members):
            return None
        lot_end = now + (start_relative + setup + p + first["transport"])
        free = now + (start_relative + setup + occupation)
        gain = -selected_weights["setup"] * setup
        for operation in members:
            before_tardy = max(0, end_bound + operation["remaining"] - operation["due_relative"])
            after_tardy = max(0, lot_end - now + operation["remaining"] - operation["due_relative"])
            gain += operation["priority_coefficient"] * (selected_weights["completion"] +
                    selected_weights["flow"] * (end_bound - (lot_end - now)) +
                    selected_weights["tardiness"] * (before_tardy - after_tardy))
        if gain < 0:
            return None
        priority = sum(operation["priority_coefficient"] for operation in members)
        slack = min(operation["due"] - lot_end - operation["remaining"] for operation in members)
        if rule == "gain_rate":
            key = (-gain / max(1, free - current["tail"]), start, -priority, slack, bi, mid)
        elif rule == "slack":
            key = (slack, -priority, start, -gain, bi, mid)
        else:
            key = (-priority, slack, start, -gain, bi, mid)
        return key, {"start": start, "not_before": start, "end": lot_end, "expected_end": lot_end,
                     "process_end": process_end, "occupied_until": free, "setup_seconds": setup}

    def push(bi, mid):
        nonlocal serial, stopped
        if evaluations >= max_candidate_evaluations or time.perf_counter() - started >= max_wall_seconds:
            stopped = "construction_budget"
            return
        candidate = proposal(bi, mid)
        if candidate is not None:
            key, timing = candidate
            serial += 1
            heapq.heappush(heap, (key, serial, bi, mid, state[mid]["generation"], timing))

    def activate(bi):
        if bi in ready_batches or not ready(pool[bi]):
            return
        ready_batches.add(bi)
        for mid in pool[bi]["machines"]:
            machine_batches[mid].add(bi)
            push(bi, mid)

    for bi, batch in enumerate(pool):
        for oid in batch["operation_ids"]:
            for predecessor in operations[oid]["predecessor_ids"]:
                waiting_on[predecessor].add(bi)
            if operations[oid].get("same_machine_as") is not None:
                waiting_on[operations[oid]["same_machine_as"]].add(bi)
        activate(bi)
    while heap:
        if time.perf_counter() - started >= max_wall_seconds:
            stopped = "construction_budget"; break
        _, _, bi, mid, generation, timing = heapq.heappop(heap)
        if generation != state[mid]["generation"] or not ready(pool[bi]):
            continue
        batch = pool[bi]
        members = [operations[oid] for oid in batch["operation_ids"]]
        task = {"id": f"p{plan_version}-m{mid}-s{state[mid]['count']}", "machine": mid,
                "sequence": state[mid]["count"], "operation_ids": list(batch["operation_ids"]),
                "lot_ids": [operation["lot_id"] for operation in members],
                "steps": [operation["step"] for operation in members],
                "visits": [operation["visit"] for operation in members],
                "predecessor_task_ids": sorted({selected[parent]["id"] for operation in members for parent in operation["predecessor_ids"]}),
                "start_conditions": {"lot_predecessors_complete": True, "recheck_eligibility": True},
                "decision_source": "classical_incumbent", **timing}
        tasks.append(task)
        for oid in batch["operation_ids"]:
            selected[oid] = task
        current = state[mid]
        setup = members[0]["setup"]
        if timing["setup_seconds"] > 0 and current["min_left"] == 0 and setup in problem.get("min_runs", {}):
            current["min_left"] = problem["min_runs"][setup]
            current["min_setup"] = setup
        current["min_left"] = max(0, current["min_left"] - len(members))
        current["setup"] = setup
        current["tail"] = timing["occupied_until"]
        current["active_ends"] = [end for end in current["active_ends"] if end > current["tail"]] + [timing["process_end"]]
        current["count"] += 1
        current["generation"] += 1
        for candidate_id in sorted(machine_batches[mid]):
            push(candidate_id, mid)
        for oid in batch["operation_ids"]:
            for candidate_id in sorted(waiting_on[oid]):
                activate(candidate_id)
    tasks.sort(key=lambda task: (task["machine"], task["sequence"]))
    assigned = {task["machine"] for task in tasks}
    unplanned = {oid: ("upstream_not_planned" if any(p not in selected for p in operation["predecessor_ids"])
                       else "construction_budget" if stopped else "batch_window_slot_or_rule_choice")
                 for oid, operation in operations.items() if oid not in selected}
    plan = {"version": str(plan_version), "scope": sorted(machines), "created_at": now,
            "valid_until": now + horizon, "freeze_until": freeze,
            "reason": "explicit classical finite-window incumbent", "tasks": tasks,
            "holds": [{"machine": mid, "until": now + horizon,
                       "reason": "classical incumbent has no feasible candidate within registered window/slots; inspect unplanned"}
                      for mid in sorted(machines) if mid not in assigned]}
    final_tasks = {task["machine"]: task for task in sorted(tasks, key=lambda t: t["sequence"])}
    plan["holds"].extend({"machine": mid, "after_task_id": task["id"], "until": now + horizon,
                          "reason": "explicit wait after finite classical sequence; unplanned work requires next revision"}
                         for mid, task in sorted(final_tasks.items()))
    audit = validate_nominal_plan(problem, plan, max_slots_per_machine=max_slots_per_machine)
    return {**base, "status": "FEASIBLE_HEURISTIC" if audit["valid"] else "INVALID_HEURISTIC",
            "plan": plan, "tasks": tasks, "objective": nominal_objective(problem, tasks, weights) if audit["valid"] else None,
            "unplanned_operations": unplanned, "nominal_audit": audit,
            "candidate_evaluations": evaluations, "stop_reason": stopped,
            "wall_seconds": time.perf_counter() - started,
            "budgets": {"max_wall_seconds": max_wall_seconds, "max_candidate_evaluations": max_candidate_evaluations},
            "limitations": ["deterministic constructive incumbent, not a CP-SAT proof",
                            "restricted batch pool and nominal physical semantics of the shared model"]}
