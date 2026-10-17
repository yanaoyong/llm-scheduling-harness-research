"""Finite-window, cross-family batch job-shop CP-SAT shared by arms A and C.

This module proposes explicit future assignments. It never dispatches, advances
the simulator, calls a model, or fills a missing plan. See optimizer.md for the
restricted candidate pool, integer rounding and nominal prediction boundaries.
"""
from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import json
import math
import time

from ortools.sat.python import cp_model


MODEL_VERSION = "fullfab-batch-slots-cross-family-v1"
DEFAULT_WEIGHTS = {"completion": 3600, "flow": 1, "tardiness": 4, "setup": 1}


def _number(value, name, *, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite numeric")
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be nonnegative")
    return value


def _ceil(value):
    return int(math.ceil(value - 1e-9))


def _normalise(problem):
    now = _number(problem["time"], "time")
    end = _number(problem["horizon_end"], "horizon_end")
    horizon = math.floor(end - now + 1e-9)
    if not 1 <= horizon <= 28 * 86400:
        raise ValueError("nominal planning horizon must be 1 second..28 days")
    machines = {}
    for source in problem["machines"]:
        m = dict(source)
        mid = m["machine"]
        if type(mid) is not int or mid in machines:
            raise ValueError("machine identifiers must be unique integers")
        m.setdefault("current_setup", "")
        m.setdefault("min_left", 0)
        m.setdefault("min_setup", "")
        m.setdefault("cascading", False)
        if type(m["min_left"]) is not int or m["min_left"] < 0:
            raise ValueError("min_left must be a nonnegative integer")
        m["available"] = min(horizon, max(0, _ceil(_number(m.get("available_at", now), "available_at") - now)))
        m["downtimes"] = []
        for a, b in m.get("unavailable_intervals", []):
            _number(a, "downtime start"); _number(b, "downtime end")
            if b <= a:
                raise ValueError("downtime interval must have positive length")
            if b > now:
                m["downtimes"].append((max(0, math.floor(a - now)), _ceil(b - now)))
        machines[mid] = m
    operations = {}
    for source in problem["operations"]:
        o = dict(source)
        oid = o["operation_id"]
        if not isinstance(oid, str) or not oid or oid in operations:
            raise ValueError("operation_id must be a unique nonempty string")
        if not isinstance(o["lot_id"], str):
            raise ValueError("lot_id must be a string")
        o.setdefault("predecessor_ids", [])
        o.setdefault("setup", "")
        o.setdefault("setup_time", None)
        o.setdefault("transport_seconds", 0)
        o.setdefault("batch_min", 1)
        o.setdefault("batch_max", 1)
        o.setdefault("priority", 1)
        o.setdefault("due", end)
        o.setdefault("remaining_work_seconds", 0)
        o.setdefault("release_time", now)
        o.setdefault("visit", 1)
        if any(type(o[k]) is not int or o[k] < 1 for k in ("batch_min", "batch_max")) or o["batch_min"] > o["batch_max"]:
            raise ValueError("invalid batch bounds")
        _number(o["priority"], "priority", nonnegative=True)
        o["priority_coefficient"] = max(1, _ceil(o["priority"]))
        o["release"] = max(0, _ceil(_number(o["release_time"], "release_time") - now))
        o["due_relative"] = math.floor(_number(o["due"], "due") - now)
        o["remaining"] = _ceil(_number(o["remaining_work_seconds"], "remaining_work_seconds", nonnegative=True))
        o["transport"] = _ceil(_number(o["transport_seconds"], "transport_seconds", nonnegative=True))
        if o["setup_time"] is not None:
            o["setup_time"] = _ceil(_number(o["setup_time"], "setup_time", nonnegative=True))
        mids = sorted(set(o["eligible_machines"]))
        if any(mid not in machines for mid in mids):
            raise ValueError("unknown eligible machine")
        if any(machines[mid]["family"] != o["family"] for mid in mids):
            raise ValueError("operation and eligible machine family disagree")
        o["eligible_machines"] = mids
        o["times"] = {}
        for mid in mids:
            specific = o.get("machine_times", {}).get(str(mid), o.get("machine_times", {}).get(mid, {}))
            process = specific.get("processing_seconds", o.get("processing_seconds"))
            occupation = specific.get("occupation_seconds", o.get("occupation_seconds", process))
            process = _ceil(_number(process, "processing_seconds", nonnegative=True))
            occupation = _ceil(_number(occupation, "occupation_seconds", nonnegative=True))
            if process < 1 or occupation < 1:
                raise ValueError("production duration/cadence must be positive")
            if not machines[mid]["cascading"] and occupation < process:
                raise ValueError("noncascading machine occupation cannot be shorter than processing")
            o["times"][mid] = (process, occupation)
        # Processing/transport compatibility is deliberately stricter than the
        # simulator's part+step key. Different timing inputs are never averaged.
        o["compatibility"] = json.dumps([
            o["family"], o.get("batch_key", [o["lot_id"], o["step"]]),
            o["setup"], o["setup_time"], o["batch_min"], o["batch_max"],
            o["transport"], o.get("processing_seconds"), o.get("occupation_seconds"),
        ], sort_keys=True)
        operations[oid] = o
    children = defaultdict(list)
    incoming = {oid: len(o["predecessor_ids"]) for oid, o in operations.items()}
    for oid, o in operations.items():
        if len(set(o["predecessor_ids"])) != len(o["predecessor_ids"]):
            raise ValueError("duplicate predecessor")
        for parent in o["predecessor_ids"]:
            if parent not in operations:
                raise ValueError(f"missing predecessor {parent}; encode already finished work in release_time")
            children[parent].append(oid)
        if o.get("same_machine_as") is not None and o["same_machine_as"] not in operations:
            raise ValueError("same_machine_as must name an included operation")
    ready = deque(sorted(oid for oid, degree in incoming.items() if degree == 0))
    seen = 0
    while ready:
        oid = ready.popleft(); seen += 1
        for child in children[oid]:
            incoming[child] -= 1
            if incoming[child] == 0:
                ready.append(child)
    if seen != len(operations):
        raise ValueError("operation predecessor graph is cyclic")
    return now, horizon, machines, operations


def _candidate_batches(operations):
    """Deterministic restricted batch columns; every eligible lot is considered.

    Single-lot jobs are complete. Batch jobs use min/max-size sliding windows
    under four transparent classical orders, separately per eligible machine.
    No candidate or lot is silently cut off because of a pool-size limit.
    """
    groups = defaultdict(list)
    for o in operations.values():
        groups[o["compatibility"]].append(o)
    pool = {}
    for members in groups.values():
        by_machine = defaultdict(list)
        for o in members:
            for mid in o["eligible_machines"]:
                by_machine[(mid, o["times"][mid])].append(o)
        for (mid, durations), compatible in sorted(by_machine.items()):
            minimum, maximum = compatible[0]["batch_min"], compatible[0]["batch_max"]
            keys = (
                lambda o: (o["due"], -o["priority"], o["operation_id"]),
                lambda o: (o["release_time"], o["operation_id"]),
                lambda o: (-o["priority"], o["due"], o["operation_id"]),
                lambda o: (o["due"] - o["remaining"], -o["priority"], o["operation_id"]),
            )
            for key in keys:
                ordered = sorted(compatible, key=key)
                for size in sorted({minimum, min(maximum, len(ordered))}):
                    if size < minimum:
                        continue
                    for offset in range(len(ordered) - size + 1):
                        batch = ordered[offset:offset + size]
                        if len({o["lot_id"] for o in batch}) != len(batch):
                            continue
                        ids = tuple(sorted(o["operation_id"] for o in batch))
                        entry = pool.setdefault(ids, {"operation_ids": ids, "machines": {}, "representative": batch[0]})
                        entry["machines"][mid] = durations
    return [pool[ids] for ids in sorted(pool)]


def solve_plan(problem, *, time_limit_seconds=1.0, seed=11, weights=None,
               max_slots_per_machine=8, max_assignment_variables=250000,
               plan_version=1, freeze_until=None, deterministic_limit=None,
               use_incumbent=True, incumbent_max_seconds=1.0,
               incumbent_rule="gain_rate"):
    """Return an explicit nominal plan plus solver/candidate/coverage evidence.

    All times in input/output are absolute seconds. Internal seconds are integer
    offsets from ``problem['time']``. Missing operations stay unplanned. UNKNOWN,
    INFEASIBLE and size refusal never invoke another scheduling policy.
    """
    started = time.perf_counter()
    _number(time_limit_seconds, "time_limit_seconds")
    if not 0.01 <= time_limit_seconds <= 60:
        raise ValueError("time_limit_seconds must be 0.01..60")
    if type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError("seed must be a nonnegative int32")
    if type(max_slots_per_machine) is not int or not 1 <= max_slots_per_machine <= 128:
        raise ValueError("max_slots_per_machine must be 1..128")
    if type(max_assignment_variables) is not int or not 1 <= max_assignment_variables <= 1000000:
        raise ValueError("max_assignment_variables must be 1..1000000")
    if deterministic_limit is not None:
        _number(deterministic_limit, "deterministic_limit", nonnegative=True)
        if deterministic_limit <= 0:
            raise ValueError("deterministic_limit must be positive")
    objective_weights = dict(DEFAULT_WEIGHTS)
    if weights:
        if set(weights) - set(objective_weights):
            raise ValueError("unknown objective weight")
        objective_weights.update(weights)
    if any(type(v) is not int or not 0 <= v <= 100000 for v in objective_weights.values()):
        raise ValueError("weights must be integers 0..100000")
    if not any(objective_weights.values()):
        raise ValueError("at least one objective weight must be positive")
    now, horizon, machines, operations = _normalise(problem)
    freeze = now if freeze_until is None else _number(freeze_until, "freeze_until")
    if not now <= freeze <= now + horizon:
        raise ValueError("freeze_until must lie in planning window")
    # Starts belong to the window; already-started work may finish after it.
    # A separate end bound prevents short observation windows from excluding
    # every long operation and artificially favouring short processing jobs.
    transitions = problem.get("setup_transitions", [])
    if isinstance(transitions, dict):
        setup_map = {(old, new): _ceil(_number(seconds, "setup seconds", nonnegative=True))
                     for old, targets in transitions.items() for new, seconds in targets.items()}
    else:
        setup_map = {(row["old"], row["new"]): _ceil(_number(row["seconds"], "setup seconds", nonnegative=True)) for row in transitions}
    max_setup_seconds = max([0, *setup_map.values(), *(o["setup_time"] or 0 for o in operations.values())])
    longest_task = max([1, *(max(process + o["transport"], occupation) + max_setup_seconds
                             for o in operations.values() for process, occupation in o["times"].values())])
    end_bound = horizon + longest_task
    pool = _candidate_batches(operations)
    candidates_by_machine = defaultdict(list)
    for index, batch in enumerate(pool):
        for mid in batch["machines"]:
            candidates_by_machine[mid].append(index)
    # Slots beyond the number of distinct reachable operation members can never
    # be used. No machine, family, operation, or candidate is rank-truncated.
    slot_counts = {
        mid: min(max_slots_per_machine, len({oid for b in ids for oid in pool[b]["operation_ids"]}))
        for mid, ids in candidates_by_machine.items()
    }
    assignment_count = sum(slot_counts[mid] * len(ids) for mid, ids in candidates_by_machine.items())
    pool_evidence = [{"operations": list(b["operation_ids"]), "machines": sorted(b["machines"])} for b in pool]
    evidence = {
        "model": MODEL_VERSION, "global_optimality_claim": False,
        "objective_scope": "restricted nominal window and batch-column pool only",
        "parameters": {"time_limit_seconds": time_limit_seconds, "seed": seed,
                       "weights": objective_weights, "max_slots_per_machine": max_slots_per_machine,
                       "max_assignment_variables": max_assignment_variables,
                       "num_search_workers": 1, "deterministic_limit": deterministic_limit,
                       "use_incumbent": use_incumbent, "incumbent_max_seconds": incumbent_max_seconds,
                       "incumbent_rule": incumbent_rule},
        "problem_sha256": hashlib.sha256(json.dumps(problem, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "candidate_pool_sha256": hashlib.sha256(json.dumps(pool_evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "candidate_batches": len(pool), "assignment_variables": assignment_count,
        "machine_ids_considered": sorted(machines), "operation_count": len(operations),
        "start_window_end": now + horizon, "completion_bound": now + end_bound,
        "limitations": ["nominal expected durations; unknown failures/sampling/rework require replanning",
                        "restricted min/max batch columns under EDD/FIFO/priority/slack orders",
                        "finite ordered slots per machine; unplanned work must trigger coverage handling",
                        "objective is a weighted operation progress/flow/tardiness surrogate",
                        "piece-count PM is not predicted; common executor must revalidate and replan",
                        "CQT is enforced only if explicit latest_start is supplied",
                        "frozen future commitments must be supplied in frozen_tasks"],
    }

    def result(status, tasks, **extra):
        selected = {oid for task in tasks for oid in task["operation_ids"]}
        reasons = {}
        in_pool = {oid for b in pool for oid in b["operation_ids"]}
        for oid, o in operations.items():
            if oid not in selected:
                reasons[oid] = ("no_eligible_machine" if not o["eligible_machines"] else
                                "no_compatible_minimum_batch" if oid not in in_pool else
                                "no_solver_solution" if status not in ("OPTIMAL", "FEASIBLE") else
                                "window_slot_or_objective_choice")
        assigned = {task["machine"] for task in tasks}
        holds = [{"machine": mid, "until": now + horizon,
                  "reason": "unplanned_eligible_operations" if candidates_by_machine[mid] else "no_candidate_batch"}
                 for mid in sorted(machines) if mid not in assigned]
        final_tasks = {task["machine"]: task for task in sorted(tasks, key=lambda t: t["sequence"])}
        holds.extend({"machine": mid, "after_task_id": task["id"], "until": now + horizon,
                      "reason": "explicit wait after finite optimized sequence; unplanned work requires next revision"}
                     for mid, task in sorted(final_tasks.items()))
        plan = {"version": str(plan_version), "scope": sorted(machines), "created_at": now, "valid_until": now + horizon,
                "freeze_until": freeze, "reason": "rolling_window_optimization", "tasks": tasks, "holds": holds}
        return {**evidence, "solver_status": status, "objective": None, "best_bound": None,
                "solve_wall_seconds": 0.0, "plan": plan, "tasks": tasks,
                "unplanned_operations": reasons, "planned_operations": len(selected),
                "wall_seconds": time.perf_counter() - started, **extra}

    incumbent = None
    if use_incumbent:
        from .incumbent import build_incumbent
        candidate = build_incumbent(problem, weights=objective_weights,
                                    max_slots_per_machine=max_slots_per_machine,
                                    plan_version=plan_version, freeze_until=freeze,
                                    max_wall_seconds=incumbent_max_seconds, rule=incumbent_rule)
        evidence["classical_incumbent"] = candidate
        if candidate["status"] == "FEASIBLE_HEURISTIC" and candidate["tasks"]:
            incumbent = candidate

    def retain_incumbent(cp_status, **extra):
        if incumbent is None:
            return result(cp_status, [], **extra)
        top_level = {key: value for key, value in extra.items() if key != "best_bound"}
        answer = result("FEASIBLE_HEURISTIC", incumbent["tasks"],
                        objective=incumbent["objective"], best_bound=None,
                        selected_source="classical_incumbent", nominal_audit=incumbent["nominal_audit"],
                        cp_sat={"status": cp_status, **extra}, **top_level)
        # A local CP bound, if available, is evidence of that solve only. The
        # heuristic status must never appear to carry an optimality certificate.
        answer["best_bound"] = None
        answer["unplanned_operations"] = incumbent["unplanned_operations"]
        return answer

    if assignment_count > max_assignment_variables:
        return retain_incumbent("MODEL_SIZE_LIMIT", failure_reason="assignment-variable cap exceeded; no CP solve")

    model = cp_model.CpModel()
    op_vars = {}
    choices_by_op = defaultdict(list)
    choices_by_op_machine = defaultdict(list)
    slot_vars = {}
    terms = []
    for oid, o in operations.items():
        present = model.new_bool_var("op_" + oid)
        start = model.new_int_var(0, horizon, "start_" + oid)
        end = model.new_int_var(0, end_bound, "end_" + oid)
        model.add(start >= o["release"]).only_enforce_if(present)
        model.add(start < horizon).only_enforce_if(present)
        model.add(start == horizon).only_enforce_if(present.Not())
        model.add(end == end_bound).only_enforce_if(present.Not())
        if "latest_start" in o:
            model.add(start <= math.floor(_number(o["latest_start"], "latest_start") - now)).only_enforce_if(present)
        op_vars[oid] = (present, start, end)
        tardy_max = max(0, end_bound + o["remaining"] - o["due_relative"])
        tardy = model.new_int_var(0, tardy_max, "tardy_" + oid)
        model.add_max_equality(tardy, [0, end + o["remaining"] - o["due_relative"]])
        priority = o["priority_coefficient"]
        terms.extend([objective_weights["completion"] * priority * present,
                      -objective_weights["flow"] * priority * end,
                      -objective_weights["tardiness"] * priority * tardy])
    for oid, o in operations.items():
        present, start, _ = op_vars[oid]
        for predecessor in o["predecessor_ids"]:
            pp, _, pe = op_vars[predecessor]
            model.add(present <= pp)
            model.add(start >= pe).only_enforce_if(present)

    min_runs = problem.get("min_runs", {})
    if any(type(v) is not int or v < 0 for v in min_runs.values()):
        raise ValueError("min_runs values must be nonnegative integers")

    for mid in sorted(machines):
        m = machines[mid]
        candidate_ids = candidates_by_machine[mid]
        if not candidate_ids:
            continue
        setup_labels = sorted({"", m["current_setup"], m["min_setup"]} |
                              {pool[b]["representative"]["setup"] for b in candidate_ids})
        setup_index = {label: index for index, label in enumerate(setup_labels)}
        kinds = sorted({(pool[b]["representative"]["setup"], pool[b]["representative"]["setup_time"])
                        for b in candidate_ids}, key=lambda x: (x[0], -1 if x[1] is None else x[1]))
        kind_index = {kind: index + 1 for index, kind in enumerate(kinds)}
        table = []
        for before, label in enumerate(setup_labels):
            table.append((before, 0, before, 0, 0))
            for (new, override), kind in kind_index.items():
                seconds = 0 if not new or label == new else (override if override is not None else setup_map.get((label, new), setup_map.get(("", new), 0)))
                table.append((before, kind, setup_index[new], seconds, min_runs.get(new, 0)))
        max_setup = max(row[3] for row in table)
        max_min = max([m["min_left"], *min_runs.values(), 0])
        before_setup = model.new_constant(setup_index[m["current_setup"]])
        before_lock = model.new_constant(setup_index[m["min_setup"]])
        before_remaining = model.new_constant(m["min_left"])
        before_end = model.new_constant(m["available"])
        before_present = None
        process_intervals = []
        for index, absolute_end in enumerate(m.get("processing_until", [])):
            remaining = min(end_bound, max(0, _ceil(_number(absolute_end, "processing_until") - now)))
            if remaining:
                process_intervals.append(model.new_fixed_size_interval_var(0, remaining, f"inprocess_{mid}_{index}"))
        for position in range(slot_counts[mid]):
            label = f"m{mid}s{position}"
            present = model.new_bool_var(label + "_present")
            if before_present is not None:
                model.add(present <= before_present)
            start = model.new_int_var(0, end_bound, label + "_start")
            model.add(start < horizon).only_enforce_if(present)
            occupied_end = model.new_int_var(0, end_bound, label + "_free")
            process_end = model.new_int_var(0, end_bound, label + "_processed")
            lot_end = model.new_int_var(0, end_bound, label + "_lot_ready")
            process = model.new_int_var(0, end_bound, label + "_process")
            occupation = model.new_int_var(0, end_bound, label + "_occupation")
            transport = model.new_int_var(0, end_bound, label + "_transport")
            batch_count = model.new_int_var(0, max(len(pool[b]["operation_ids"]) for b in candidate_ids), label + "_count")
            kind = model.new_int_var(0, len(kinds), label + "_kind")
            after_setup = model.new_int_var(0, len(setup_labels) - 1, label + "_setup")
            setup = model.new_int_var(0, max_setup, label + "_setup_seconds")
            new_min = model.new_int_var(0, max_min, label + "_new_min")
            effective_before = model.new_int_var(0, len(setup_labels) - 1, label + "_effective_setup")
            resets = []
            for di, (a, b) in enumerate(m["downtimes"]):
                pre = model.new_bool_var(f"{label}_pre{di}")
                post = model.new_bool_var(f"{label}_post{di}")
                # Nominal process cannot cross known downtime. The live DES is
                # preempt/resume; this planning restriction is conservative.
                model.add(process_end <= a).only_enforce_if(pre)
                model.add(start >= b).only_enforce_if(post)
                model.add_bool_or([pre, post, present.Not()])
                crossed = model.new_bool_var(f"{label}_crossed{di}")
                old_before = model.new_bool_var(f"{label}_old_before{di}")
                model.add(before_end <= a).only_enforce_if(old_before)
                model.add(before_end > a).only_enforce_if(old_before.Not())
                model.add_bool_and([old_before, post, present]).only_enforce_if(crossed)
                model.add_bool_or([old_before.Not(), post.Not(), present.Not(), crossed])
                # Make post exact: it also determines whether setup was reset.
                model.add(start < b).only_enforce_if(post.Not())
                resets.append(crossed)
            if resets:
                reset = model.new_bool_var(label + "_reset")
                model.add_max_equality(reset, resets)
                model.add(effective_before == setup_index[""]).only_enforce_if(reset)
                model.add(effective_before == before_setup).only_enforce_if(reset.Not())
            else:
                model.add(effective_before == before_setup)
            model.add_allowed_assignments([effective_before, kind, after_setup, setup, new_min], table)
            ys = []
            values = {"process": [], "occupation": [], "transport": [], "count": [], "kind": []}
            for bi in candidate_ids:
                batch = pool[bi]; representative = batch["representative"]
                y = model.new_bool_var(f"{label}_b{bi}")
                ys.append((bi, y))
                p, occ = batch["machines"][mid]
                values["process"].append(p * y)
                values["occupation"].append(occ * y)
                values["transport"].append(representative["transport"] * y)
                values["count"].append(len(batch["operation_ids"]) * y)
                values["kind"].append(kind_index[(representative["setup"], representative["setup_time"])] * y)
                for oid in batch["operation_ids"]:
                    choices_by_op[oid].append(y)
                    choices_by_op_machine[oid, mid].append(y)
                    model.add(op_vars[oid][1] == start).only_enforce_if(y)
                    model.add(op_vars[oid][2] == lot_end).only_enforce_if(y)
            model.add(sum(y for _, y in ys) == present)
            for variable, key in ((process, "process"), (occupation, "occupation"), (transport, "transport"), (batch_count, "count"), (kind, "kind")):
                model.add(variable == sum(values[key]))
            model.add(start >= before_end)
            model.add(start == before_end).only_enforce_if(present.Not())
            model.add(process_end == start + setup + process)
            model.add(occupied_end == start + setup + occupation)
            model.add(lot_end == process_end + transport)
            duration = model.new_int_var(0, end_bound, label + "_processing_duration")
            model.add(duration == setup + process)
            process_intervals.append(model.new_optional_interval_var(start, duration, process_end, present, label + "_interval"))
            locked = model.new_bool_var(label + "_locked")
            model.add(before_remaining > 0).only_enforce_if(locked)
            model.add(before_remaining == 0).only_enforce_if(locked.Not())
            model.add(after_setup == before_lock).only_enforce_if([locked, present])
            setup_positive = model.new_bool_var(label + "_setup_positive")
            model.add(setup > 0).only_enforce_if(setup_positive)
            model.add(setup == 0).only_enforce_if(setup_positive.Not())
            trigger = model.new_bool_var(label + "_trigger_min")
            model.add_bool_and([setup_positive, locked.Not()]).only_enforce_if(trigger)
            model.add_bool_or([setup_positive.Not(), locked, trigger])
            added = model.new_int_var(0, max_min, label + "_added_min")
            model.add(added == new_min).only_enforce_if(trigger)
            model.add(added == 0).only_enforce_if(trigger.Not())
            after_remaining = model.new_int_var(0, max_min, label + "_remaining_min")
            model.add_max_equality(after_remaining, [0, before_remaining + added - batch_count])
            after_lock = model.new_int_var(0, len(setup_labels) - 1, label + "_min_setup")
            model.add(after_lock == after_setup).only_enforce_if(trigger)
            model.add(after_lock == before_lock).only_enforce_if(trigger.Not())
            terms.append(-objective_weights["setup"] * setup)
            slot_vars[mid, position] = {"choices": ys, "start": start, "end": lot_end,
                                        "process_end": process_end, "occupied_end": occupied_end, "setup": setup}
            before_setup, before_lock, before_remaining = after_setup, after_lock, after_remaining
            before_end, before_present = occupied_end, present
        model.add_cumulative(process_intervals, [1] * len(process_intervals), 2 if m["cascading"] else 1)

    for oid, o in operations.items():
        model.add(sum(choices_by_op[oid]) == op_vars[oid][0])
        if o.get("same_machine_as") is not None:
            other = o["same_machine_as"]
            for mid in machines:
                model.add(sum(choices_by_op_machine[oid, mid]) <= sum(choices_by_op_machine[other, mid]))
    frozen = problem.get("frozen_tasks", [])
    for task in frozen:
        ids = tuple(sorted(task["operation_ids"]))
        target = next((bi for bi, batch in enumerate(pool) if batch["operation_ids"] == ids), None)
        if target is None or task["machine"] not in pool[target]["machines"]:
            raise ValueError("frozen task batch absent from candidate pool; retain prior plan or supply compatible pool")
        choices = []
        for (mid, _), variables in slot_vars.items():
            if mid != task["machine"]:
                continue
            for bi, y in variables["choices"]:
                if bi == target:
                    model.add(variables["start"] == _ceil(task.get("start", task.get("not_before")) - now)).only_enforce_if(y)
                    choices.append(y)
        model.add(sum(choices) == 1)
    model.maximize(sum(terms))
    if incumbent is not None:
        incumbent_tasks = {(task["machine"], task["sequence"]): task for task in incumbent["tasks"]}
        by_operation = {oid: task for task in incumbent["tasks"] for oid in task["operation_ids"]}
        for oid, (present, start, end) in op_vars.items():
            task = by_operation.get(oid)
            model.add_hint(present, int(task is not None))
            model.add_hint(start, int(round(task["start"] - now)) if task else horizon)
            model.add_hint(end, int(round(task["end"] - now)) if task else end_bound)
        machine_tail = {mid: machines[mid]["available"] for mid in machines}
        for (mid, position), variables in slot_vars.items():
            task = incumbent_tasks.get((mid, position))
            for bi, y in variables["choices"]:
                model.add_hint(y, int(task is not None and tuple(task["operation_ids"]) == pool[bi]["operation_ids"]))
            if task:
                for key in ("start", "end", "process_end", "occupied_end"):
                    field = "occupied_until" if key == "occupied_end" else key
                    model.add_hint(variables[key], int(round(task[field] - now)))
                model.add_hint(variables["setup"], task["setup_seconds"])
                machine_tail[mid] = int(round(task["occupied_until"] - now))
            else:
                for key in ("start", "end", "process_end", "occupied_end"):
                    model.add_hint(variables[key], machine_tail[mid])
                model.add_hint(variables["setup"], 0)
        model.add(sum(terms) >= int(incumbent["objective"]))
    invalid = model.validate()
    if invalid:
        return retain_incumbent("MODEL_INVALID", failure_reason=invalid, build_wall_seconds=time.perf_counter() - started)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = seed
    if deterministic_limit is not None:
        solver.parameters.max_deterministic_time = deterministic_limit
    build_seconds = time.perf_counter() - started
    status = solver.solve(model)
    feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    tasks = []
    if feasible:
        for (mid, position), variables in slot_vars.items():
            for bi, y in variables["choices"]:
                if not solver.value(y):
                    continue
                batch = pool[bi]
                ops = [operations[oid] for oid in batch["operation_ids"]]
                start = now + solver.value(variables["start"])
                end = now + solver.value(variables["end"])
                tasks.append({"id": f"p{plan_version}-m{mid}-s{position}", "machine": mid,
                              "decision_source": "cp_sat",
                              "operation_ids": list(batch["operation_ids"]),
                              "lot_ids": [o["lot_id"] for o in ops], "steps": [o["step"] for o in ops],
                              "visits": [o["visit"] for o in ops], "start": start, "not_before": start,
                              "end": end, "expected_end": end, "sequence": position,
                              "process_end": now + solver.value(variables["process_end"]),
                              "occupied_until": now + solver.value(variables["occupied_end"]),
                              "setup_seconds": solver.value(variables["setup"]),
                              "start_conditions": {"lot_predecessors_complete": True, "recheck_eligibility": True}})
        op_to_task = {oid: task["id"] for task in tasks for oid in task["operation_ids"]}
        for task in tasks:
            task["predecessor_task_ids"] = sorted({op_to_task[p] for oid in task["operation_ids"] for p in operations[oid]["predecessor_ids"]})
    response = solver.response_proto
    if not feasible:
        return retain_incumbent(solver.status_name(status),
                                best_bound=solver.best_objective_bound if status != cp_model.MODEL_INVALID else None,
                                solve_wall_seconds=solver.wall_time, build_wall_seconds=build_seconds,
                                deterministic_time=response.deterministic_time,
                                branches=solver.num_branches, conflicts=solver.num_conflicts,
                                model_variables=len(model.proto.variables), model_constraints=len(model.proto.constraints))
    return result(solver.status_name(status), tasks,
                  selected_source="cp_sat", cp_sat={"status": solver.status_name(status)},
                  objective=solver.objective_value if feasible else None,
                  best_bound=solver.best_objective_bound if status != cp_model.MODEL_INVALID else None,
                  objective_is_maximization=True, solve_wall_seconds=solver.wall_time,
                  build_wall_seconds=build_seconds, deterministic_time=response.deterministic_time,
                  branches=solver.num_branches, conflicts=solver.num_conflicts,
                  model_variables=len(model.proto.variables), model_constraints=len(model.proto.constraints))
