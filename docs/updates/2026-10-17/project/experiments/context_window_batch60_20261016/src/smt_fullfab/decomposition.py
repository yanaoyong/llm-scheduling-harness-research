"""Budgeted family CP-SAT with global precedence-frontier coordination.

The classical controller owns every assignment. Each wave commits nominal
upstream completions and machine tails before exposing successors. No solver
failure is replaced by a rule, and every local input/response remains evidence.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
import time

from src.smt_fullfab.optimizer import _normalise, solve_plan


VERSION = "fullfab-family-frontier-cpsat-v1"


def _hash(value):
    value = json.loads(json.dumps(value))
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _structure(operations):
    by_id = {o["operation_id"]: o for o in operations}
    depths = {}
    successors = defaultdict(list)
    for oid, operation in by_id.items():
        for parent in operation.get("predecessor_ids", []):
            successors[parent].append(oid)

    def depth(oid):
        if oid not in depths:
            depths[oid] = max((depth(p) + 1 for p in by_id[oid].get("predecessor_ids", [])), default=0)
        return depths[oid]

    for oid in by_id:
        depth(oid)
    return by_id, depths, successors


def solve_decomposed_plan(problem, *, time_limit_seconds=10.0, seed=11,
                          weights=None, max_slots_per_machine=4,
                          max_assignment_variables=250000, plan_version=1,
                          freeze_until=None, load_pressure_factor=1.0,
                          max_rounds=None, minimum_family_seconds=0.01,
                          use_incumbent=True, incumbent_max_seconds=1.0,
                          incumbent_rule="gain_rate"):
    """Plan all families in global precedence waves with a cumulative solve cap.

    ``time_limit_seconds`` caps the SUM of requested CP-SAT seconds, rather than
    each family call. Construction and evidence copying are separately measured
    in wall_seconds and need an external runner timeout. A ``FEASIBLE`` result
    may contain explicitly recorded local failures and uncovered work: inspect
    decomposition_status/unplanned_operations/family_failures, not only status.
    """
    started = time.perf_counter()
    now, horizon, normal_machines, normal_operations = _normalise(problem)
    if (isinstance(time_limit_seconds, bool) or not isinstance(time_limit_seconds, (int, float))
            or not math.isfinite(time_limit_seconds) or not 0.01 <= time_limit_seconds <= 3600):
        raise ValueError("cumulative time_limit_seconds must be 0.01..3600")
    if not isinstance(load_pressure_factor, (int, float)) or isinstance(load_pressure_factor, bool) or not math.isfinite(load_pressure_factor) or not 0 <= load_pressure_factor <= 10:
        raise ValueError("load_pressure_factor must be finite 0..10")
    if not isinstance(minimum_family_seconds, (int, float)) or not 0.01 <= minimum_family_seconds <= 60:
        raise ValueError("minimum_family_seconds must be 0.01..60")
    if type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError("seed must be nonnegative int32")
    if type(max_slots_per_machine) is not int or not 1 <= max_slots_per_machine <= 128:
        raise ValueError("max_slots_per_machine must be 1..128")
    if problem.get("frozen_tasks"):
        # A pre-frozen future task may depend on waves not planned yet. Do not
        # release or move it by accidentally excluding it from a family shard.
        raise ValueError("decomposition v1 requires no unstarted frozen_tasks; retain the existing plan until the freeze ends")
    freeze = now if freeze_until is None else freeze_until
    if not now <= freeze <= now + horizon:
        raise ValueError("freeze_until must lie within the planning window")
    by_id, depths, successors = _structure(problem["operations"])
    natural_rounds = max(depths.values(), default=-1) + 1
    if max_rounds is None:
        max_rounds = natural_rounds
    elif type(max_rounds) is not int or max_rounds < 1:
        raise ValueError("max_rounds must be a positive integer")
    rounds = min(max_rounds, natural_rounds)
    family_machines = defaultdict(list)
    current_machines = {}
    for machine in problem["machines"]:
        current_machines[machine["machine"]] = deepcopy(machine)
        family_machines[machine["family"]].append(machine["machine"])
    call_operations = defaultdict(list)
    for oid, operation in by_id.items():
        if depths[oid] < rounds:
            call_operations[depths[oid], operation["family"]].append(oid)
    call_weights = {}
    for key, ids in call_operations.items():
        estimate = sum(len(by_id[oid]["eligible_machines"]) for oid in ids) * max_slots_per_machine
        call_weights[key] = math.sqrt(max(1, estimate))
    minimum_total = len(call_weights) * minimum_family_seconds
    allocations = {}
    if minimum_total <= time_limit_seconds + 1e-9:
        extras = max(0.0, time_limit_seconds - minimum_total)
        denominator = sum(call_weights.values()) or 1
        allocations = {key: min(60.0, minimum_family_seconds + extras * weight / denominator)
                       for key, weight in call_weights.items()}

    # Workload pressure is computed from the complete disclosed lookahead, not
    # from another arm or future stochastic outcomes. Batched work uses nominal
    # full-batch processing demand only as a coordination proxy.
    family_work = defaultdict(float)
    for oid, operation in normal_operations.items():
        durations = [timing[0] for timing in operation["times"].values()]
        if durations:
            family_work[operation["family"]] += min(durations) / operation["batch_max"]
    family_load = {family: work / max(1, len(family_machines[family]))
                   for family, work in family_work.items()}
    descendant_families = {}

    def following_families(oid):
        if oid not in descendant_families:
            families = set()
            for child in successors[oid]:
                families.add(by_id[child]["family"])
                families.update(following_families(child))
            descendant_families[oid] = families
        return descendant_families[oid]

    selected_operations = {}
    merged_tasks = []
    machine_sequence = defaultdict(int)
    family_solves = []
    failures = []
    family_considered = set()
    requested_seconds = 0.0
    actual_solve_seconds = 0.0
    local_unplanned = {}
    coordination = []
    heuristic_families = []

    if allocations:
        for wave in range(rounds):
            # Bottleneck-first order is explicit and deterministic. Families in
            # one wave have disjoint machines and no within-wave precedences;
            # calls remain serial to preserve the registered resource budget.
            families = sorted({family for level, family in call_weights if level == wave},
                              key=lambda family: (-family_load.get(family, 0), family))
            for family in families:
                frontier = []
                for oid, operation in by_id.items():
                    if operation["family"] != family or oid in selected_operations or depths[oid] > wave:
                        continue
                    parents = operation.get("predecessor_ids", [])
                    if not all(parent in selected_operations for parent in parents):
                        continue
                    source_binding = operation.get("same_machine_as")
                    if source_binding is not None and source_binding not in selected_operations:
                        continue
                    proposal = deepcopy(operation)
                    predecessor_end = max((selected_operations[parent]["end"] for parent in parents), default=now)
                    proposal["release_time"] = max(operation.get("release_time", now), predecessor_end)
                    proposal["predecessor_ids"] = []
                    if source_binding is not None:
                        bound_machine = selected_operations[source_binding]["machine"]
                        proposal["eligible_machines"] = [mid for mid in proposal["eligible_machines"] if mid == bound_machine]
                        proposal.pop("same_machine_as")
                    pressure = sum(family_load.get(f, 0) for f in following_families(oid) if f != family)
                    proposal["remaining_work_seconds"] = operation.get("remaining_work_seconds", 0) + load_pressure_factor * pressure
                    frontier.append(proposal)
                    coordination.append({"wave": wave, "operation_id": oid,
                                         "upstream_operation_ids": list(parents),
                                         "coordinated_release_time": proposal["release_time"],
                                         "downstream_load_seconds": pressure,
                                         "adjusted_remaining_work_seconds": proposal["remaining_work_seconds"]})
                family_considered.add(family)
                if not frontier:
                    continue
                subproblem = {"time": now, "horizon_end": now + horizon,
                              "machines": [deepcopy(current_machines[mid]) for mid in sorted(family_machines[family])],
                              "operations": frontier,
                              "setup_transitions": deepcopy(problem.get("setup_transitions", [])),
                              "min_runs": deepcopy(problem.get("min_runs", {}))}
                requested = allocations[wave, family]
                requested_seconds += requested
                result = solve_plan(subproblem, time_limit_seconds=requested, seed=seed,
                                    weights=weights, max_slots_per_machine=max_slots_per_machine,
                                    max_assignment_variables=max_assignment_variables,
                                    plan_version=f"{plan_version}-w{wave}-{_hash(family)[:8]}",
                                    freeze_until=now, use_incumbent=use_incumbent,
                                    incumbent_max_seconds=incumbent_max_seconds,
                                    incumbent_rule=incumbent_rule)
                actual_solve_seconds += result["solve_wall_seconds"]
                family_solves.append({"wave": wave, "family": family,
                                      "requested_seconds": requested,
                                      "problem": subproblem, "response": result})
                local_unplanned.update(result["unplanned_operations"])
                if result["solver_status"] == "FEASIBLE_HEURISTIC":
                    heuristic_families.append({"wave": wave, "family": family,
                                               "cp_sat_status": result["cp_sat"]["status"]})
                if result["solver_status"] not in ("OPTIMAL", "FEASIBLE", "FEASIBLE_HEURISTIC"):
                    failures.append({"wave": wave, "family": family,
                                     "status": result["solver_status"],
                                     "operation_ids": [o["operation_id"] for o in frontier]})
                    continue
                by_machine_tasks = defaultdict(list)
                for task in result["tasks"]:
                    by_machine_tasks[task["machine"]].append(deepcopy(task))
                for mid, tasks in by_machine_tasks.items():
                    machine = current_machines[mid]
                    old_processing = list(machine.get("processing_until", []))
                    for task in sorted(tasks, key=lambda t: t["sequence"]):
                        task["sequence"] = machine_sequence[mid]
                        machine_sequence[mid] += 1
                        task["id"] = f"p{plan_version}-m{mid}-s{task['sequence']}"
                        task["predecessor_task_ids"] = sorted({selected_operations[parent]["id"]
                            for oid in task["operation_ids"] for parent in by_id[oid].get("predecessor_ids", [])})
                        for oid in task["operation_ids"]:
                            selected_operations[oid] = task
                            local_unplanned.pop(oid, None)
                        merged_tasks.append(task)
                        representative = by_id[task["operation_ids"][0]]
                        setup = representative.get("setup", "")
                        remaining = machine.get("min_left", 0)
                        if task["setup_seconds"] > 0 and remaining == 0:
                            remaining = problem.get("min_runs", {}).get(setup, 0)
                            if setup in problem.get("min_runs", {}):
                                machine["min_setup"] = setup
                        machine["min_left"] = max(0, remaining - len(task["lot_ids"]))
                        machine["current_setup"] = setup
                        machine["available_at"] = task["occupied_until"]
                        old_processing.append(task["process_end"])
                    # These are still-active reservations at the machine tail,
                    # not an assumption that the original machine was idle.
                    machine["processing_until"] = [end for end in old_processing if end > machine["available_at"]]
                    machine["unavailable_intervals"] = [interval for interval in machine.get("unavailable_intervals", [])
                                                         if interval[1] > machine["available_at"]]

    # Independently enforce the cross-shard invariants before returning a plan.
    for oid, task in selected_operations.items():
        for parent in by_id[oid].get("predecessor_ids", []):
            if parent not in selected_operations or task["start"] + 1e-8 < selected_operations[parent]["end"]:
                raise AssertionError("decomposition generated an upstream precedence violation")
    merged_tasks.sort(key=lambda task: (task["machine"], task["sequence"]))
    unplanned = {}
    for oid, operation in by_id.items():
        if oid in selected_operations:
            continue
        parents = operation.get("predecessor_ids", [])
        if not allocations and call_weights:
            reason = "cumulative_budget_below_registered_family_minimum"
        elif depths[oid] >= rounds:
            reason = "explicit_wave_limit"
        elif not all(parent in selected_operations for parent in parents):
            reason = "upstream_operation_not_planned"
        else:
            reason = local_unplanned.get(oid, "binding_or_frontier_not_planned")
        unplanned[oid] = reason
    assigned_machines = {task["machine"] for task in merged_tasks}
    holds = [{"machine": mid, "until": now + horizon,
              "reason": "decomposition_no_assignment; inspect unplanned_operations and family_failures"}
             for mid in sorted(current_machines) if mid not in assigned_machines]
    final_tasks = {task["machine"]: task for task in sorted(merged_tasks, key=lambda t: t["sequence"])}
    holds.extend({"machine": mid, "after_task_id": task["id"], "until": now + horizon,
                  "reason": "explicit wait after finite decomposed sequence; unplanned work requires next revision"}
                 for mid, task in sorted(final_tasks.items()))
    plan = {"version": str(plan_version), "scope": sorted(current_machines), "created_at": now,
            "valid_until": now + horizon, "freeze_until": freeze,
            "reason": "global_precedence_family_decomposition", "tasks": merged_tasks, "holds": holds}
    from .incumbent import validate_nominal_plan
    nominal_audit = validate_nominal_plan(problem, plan,
                                         max_slots_per_machine=max_slots_per_machine * max(1, rounds),
                                         require_candidate_pool=False)
    # The decomposed pool is the documented union of per-frontier columns, not
    # the original joint-model pool. Hard batching/resources/precedence are
    # independently rechecked here; each local pool remains in family_solves.
    if not nominal_audit["valid"]:
        raise AssertionError("merged nominal plan invalid: " + "; ".join(nominal_audit["errors"]))
    if not allocations and call_weights:
        status = "BUDGET_TOO_SMALL"
    elif merged_tasks or not by_id:
        status = "FEASIBLE_HEURISTIC" if heuristic_families else "FEASIBLE"
    else:
        status = "NO_PLAN"
    return {"model": VERSION, "solver_status": status,
            "decomposition_status": "PARTIAL_SOLVER_FAILURE" if failures else
                                    "PARTIAL_COVERAGE" if unplanned else "ALL_INCLUDED_OPERATIONS_PLANNED",
            "objective": None, "best_bound": None, "global_optimality_claim": False,
            "objective_scope": "local CP-SAT bounds do not combine to a global bound",
            "plan": plan, "tasks": merged_tasks, "unplanned_operations": unplanned,
            "nominal_audit": nominal_audit,
            "planned_operations": len(selected_operations), "operation_count": len(by_id),
            "machine_ids_considered": sorted(current_machines),
            "family_ids_considered": sorted(family_considered),
            "family_load_seconds": dict(family_load), "coordination": coordination,
            "family_solves": family_solves, "family_failures": failures,
            "heuristic_families": heuristic_families,
            "solver_calls": len(family_solves), "solver_requested_seconds": requested_seconds,
            "solve_wall_seconds": actual_solve_seconds, "wall_seconds": time.perf_counter() - started,
            "problem_sha256": _hash(problem),
            "parameters": {"time_limit_seconds": time_limit_seconds, "seed": seed,
                           "weights": weights, "max_slots_per_machine_per_wave": max_slots_per_machine,
                           "max_assignment_variables_per_family": max_assignment_variables,
                           "load_pressure_factor": load_pressure_factor, "max_rounds": max_rounds,
                           "minimum_family_seconds": minimum_family_seconds, "num_search_workers": 1,
                           "use_incumbent": use_incumbent, "incumbent_max_seconds": incumbent_max_seconds,
                           "incumbent_rule": incumbent_rule},
            "limitations": ["family plans append after committed machine tails; idle gaps are not backfilled",
                            "downstream workload is a coordination proxy, not an exact joint optimum",
                            "local CP UNKNOWN/size refusal is disclosed; an independently checked classical incumbent may supply a candidate; all omissions remain visible",
                            "batch-column, nominal-time, piece-PM and CQT limits of shared optimizer apply",
                            "unstarted frozen future tasks require retaining the previous plan"]}
