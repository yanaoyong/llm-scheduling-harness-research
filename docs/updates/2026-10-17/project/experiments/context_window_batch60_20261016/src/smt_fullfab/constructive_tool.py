"""Shared explicit classical candidate tool for A and future C integration.

This API does not reserve resources, apply plans, advance the simulator or repair
an executor decision. B must not call it. C runtime admission remains separate.
"""
from __future__ import annotations

import math
import time

from .incumbent import build_incumbent


MODEL_VERSION = "fullfab-constructive-tool-v1"
MAX_CANDIDATE_EVALUATIONS = 250000
CONSTRUCTION_COST_SCOPE = "incumbent construction including its independent nominal validation"


def _solve_constructive_plan(problem, *, time_limit_seconds, seed, weights,
                             max_slots_per_machine, plan_version,
                             max_candidate_evaluations, builder):
    """Single implementation; hybrid retains its registered evaluation cap.

    The internal builder argument keeps hybrid's existing construction boundary
    injectable for failure tests. Both production entry points pass exactly the
    shared build_incumbent function; it is not a public algorithm selector.
    """
    started = time.perf_counter()
    if (type(time_limit_seconds) not in (int, float) or not math.isfinite(time_limit_seconds)
            or not 0 < time_limit_seconds <= 60):
        raise ValueError("construction time_limit_seconds must be finite and in (0, 60]")
    if type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError("seed must be a nonnegative int32")
    if type(max_slots_per_machine) is not int or not 1 <= max_slots_per_machine <= 128:
        raise ValueError("max_slots_per_machine must be 1..128")
    if type(max_candidate_evaluations) is not int or max_candidate_evaluations < 1:
        raise ValueError("max_candidate_evaluations must be a positive integer")
    if weights is not None and not isinstance(weights, dict):
        raise ValueError("weights must be a dictionary or None")
    from .optimizer import DEFAULT_WEIGHTS
    selected_weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    if (set(selected_weights) != set(DEFAULT_WEIGHTS)
            or any(type(v) is not int or not 0 <= v <= 100000 for v in selected_weights.values())):
        raise ValueError("weights must use the shared objective names and integer values 0..100000")

    candidate = builder(problem, weights=weights,
                        max_slots_per_machine=max_slots_per_machine,
                        plan_version=plan_version, rule="gain_rate",
                        max_wall_seconds=time_limit_seconds,
                        max_candidate_evaluations=max_candidate_evaluations)
    tasks = candidate.get("tasks", [])
    status = candidate["status"]
    if status == "FEASIBLE_HEURISTIC" and not tasks and problem["operations"]:
        status = "NO_PLAN"
    if status == "FEASIBLE_HEURISTIC" and not candidate.get("nominal_audit", {}).get("valid"):
        status = "INVALID_NOMINAL_PLAN"
    result = {
        **candidate, "model": MODEL_VERSION, "incumbent_model": candidate["model"],
        "solver_status": status, "selected_source": "classical_incumbent",
        "best_bound": None, "global_optimality": False, "global_optimality_claim": False,
        "cp_sat": {"status": "NOT_RUN_BY_POLICY", "requested_seconds": 0,
                   "calls": 0, "wall_seconds": 0, "best_bound": None},
        "solver_calls": 0, "solver_requested_seconds": 0, "solve_wall_seconds": 0,
        "tasks": tasks, "planned_operations": sum(len(t["operation_ids"]) for t in tasks),
        "operation_count": len(problem["operations"]),
        "machine_ids_considered": sorted(m["machine"] for m in problem["machines"]),
        "unplanned_operations": candidate.get("unplanned_operations", {
            operation["operation_id"]: "plan_not_built:" + candidate["status"]
            for operation in problem["operations"]}),
        "parameters": {"time_limit_seconds": time_limit_seconds, "seed": seed,
                       "weights": selected_weights, "max_slots_per_machine": max_slots_per_machine,
                       "max_candidate_evaluations": max_candidate_evaluations, "rule": "gain_rate"},
        "seed_semantics": {"used": False, "meaning": "not_used_by_deterministic_constructor",
                           "qualification": "wall-clock truncation may change the constructed prefix"},
        "constructor_budget_seconds": time_limit_seconds,
        "classical_construction_wall_seconds": candidate["wall_seconds"],
        "construction_cost_scope": CONSTRUCTION_COST_SCOPE,
        "construction_limit_scope": (
            "soft wall checks during candidate expansion; preprocessing and independent nominal "
            "validation are measured but not interruptible; an external total wall deadline is required"),
        "wall_seconds": time.perf_counter() - started,
    }
    return result


def solve_constructive_plan(problem, time_limit_seconds=5.0, seed=11, weights=None,
                            max_slots_per_machine=8, plan_version=1):
    """Construct a complete explicit future candidate, with honest partial coverage.

    time_limit_seconds is a soft construction budget, not CP time. The fixed
    250000 candidate-evaluation cap is reported separately. Every successful
    result is FEASIBLE_HEURISTIC with the original independent nominal audit;
    failures and unplanned operations remain visible. No fallback is attempted.
    seed is accepted for the common A/C tool contract and recorded, but the
    deterministic gain-rate constructor does not consume random numbers.

    This function alone does not expose a C action or authorize model use.
    """
    return _solve_constructive_plan(
        problem, time_limit_seconds=time_limit_seconds, seed=seed, weights=weights,
        max_slots_per_machine=max_slots_per_machine, plan_version=plan_version,
        max_candidate_evaluations=MAX_CANDIDATE_EVALUATIONS, builder=build_incumbent,
    )
