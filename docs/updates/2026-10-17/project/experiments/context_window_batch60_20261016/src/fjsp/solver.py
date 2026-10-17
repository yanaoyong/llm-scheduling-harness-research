"""Classical optional-interval CP-SAT FJSP model shared by A and C.

Independent implementation of the model in Google's flexible_job_shop_sat.py:
one optional fixed-duration interval per eligible machine, exactly one option,
job precedences, per-machine NoOverlap, minimize maximum job completion.
No benchmark answer or schedule is used in construction or search.
"""
from __future__ import annotations

import math
import time
from ortools.sat.python import cp_model


SEARCHES = {name: getattr(cp_model, name) for name in (
    "AUTOMATIC_SEARCH", "FIXED_SEARCH", "PORTFOLIO_SEARCH")}


def solve(problem, time_limit=30, seed=11, workers=1, *,
          search_branching="AUTOMATIC_SEARCH", randomize_search=False):
    if not math.isfinite(time_limit) or not 0 < time_limit <= 300:
        raise ValueError("time_limit must be in (0,300]")
    if type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError("seed must be a nonnegative int32")
    if workers != 1:
        raise ValueError("This experiment requires exactly one solver worker")
    if search_branching not in SEARCHES or type(randomize_search) is not bool:
        raise ValueError("Unsupported solver option")
    t0 = time.monotonic()
    ops = [op for job in problem["jobs"] for op in job["operations"]]
    if not ops or len({op["id"] for op in ops}) != len(ops):
        raise ValueError("Empty or duplicate operations")
    horizon = sum(max(a["duration"] for a in op["alternatives"]) for op in ops)
    model = cp_model.CpModel()
    by_machine = {m: [] for m in problem["machines"]}
    starts, ends, choices = {}, {}, {}
    for op in ops:
        oid = op["id"]
        starts[oid] = model.new_int_var(0, horizon, "s_" + oid)
        ends[oid] = model.new_int_var(0, horizon, "e_" + oid)
        options = []
        for alt in op["alternatives"]:
            machine, duration = alt["machine"], alt["duration"]
            if machine not in by_machine or type(duration) is not int or duration <= 0:
                raise ValueError("Invalid eligible machine or duration")
            active = model.new_bool_var(f"use_{oid}_{machine}")
            interval = model.new_optional_fixed_size_interval_var(
                starts[oid], duration, active, f"i_{oid}_{machine}")
            model.add(ends[oid] == starts[oid] + duration).only_enforce_if(active)
            by_machine[machine].append(interval)
            options.append((active, machine))
        model.add_exactly_one([active for active, _ in options])
        choices[oid] = options
    for job in problem["jobs"]:
        for prev, nxt in zip(job["operations"], job["operations"][1:]):
            model.add(ends[prev["id"]] <= starts[nxt["id"]])
    for intervals in by_machine.values():
        model.add_no_overlap(intervals)
    makespan = model.new_int_var(0, horizon, "makespan")
    model.add_max_equality(makespan, [ends[j["operations"][-1]["id"]] for j in problem["jobs"]])
    model.minimize(makespan)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = seed
    solver.parameters.search_branching = SEARCHES[search_branching]
    solver.parameters.randomize_search = randomize_search

    class Observer(cp_model.CpSolverSolutionCallback):
        def __init__(self):
            super().__init__()
            self.solutions = []

        def on_solution_callback(self):
            self.solutions.append({"solver_seconds": self.wall_time,
                                   "objective": self.objective_value,
                                   "best_bound": self.best_objective_bound})

    observer = Observer()
    status = solver.solve(model, observer)
    feasible = status in (cp_model.FEASIBLE, cp_model.OPTIMAL)
    schedule = {"operations": [
        {"id": op["id"], "machine": next(m for active, m in choices[op["id"]] if solver.value(active)),
         "start": solver.value(starts[op["id"]]), "end": solver.value(ends[op["id"]])}
        for op in ops]} if feasible else None
    return {
        "schedule": schedule, "solver_status": solver.status_name(status),
        "objective": int(solver.objective_value) if feasible else None,
        "best_bound": float(solver.best_objective_bound),
        "wall_seconds": time.monotonic() - t0,
        "solver_seconds": solver.wall_time,
        "parameters": {"time_limit": time_limit, "seed": seed, "workers": workers,
                       "search_branching": search_branching, "randomize_search": randomize_search},
        "solutions": observer.solutions,
        "first_witness_solver_seconds": observer.solutions[0]["solver_seconds"] if observer.solutions else None,
        "response_stats": solver.response_stats(),
        "time_limit_reached": status == cp_model.FEASIBLE or status == cp_model.UNKNOWN,
    }
