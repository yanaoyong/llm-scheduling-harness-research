"""Explicit full-factory plans: absolute-period CP and event-time construction.

This module neither advances a simulator nor cancels submitted tasks. A caller
must reserve resources before solving and acknowledge a successful commit.
"""
from __future__ import annotations

from copy import deepcopy
import math
import time

from .decomposition import solve_decomposed_plan
from .incumbent import build_incumbent
from .constructive_tool import _solve_constructive_plan

VERSION = "fullfab-hybrid-v1"
PERIODIC = "periodic_cp"
EVENT = "event_classical"


def configuration(*, period_seconds=1800, plan_seconds=14400,
                  lookahead_depth=2, max_slots=4, solver_seconds=2,
                  constructor_seconds=5, max_candidate_evaluations=250000):
    for name, value in (("period_seconds", period_seconds), ("plan_seconds", plan_seconds),
                        ("solver_seconds", solver_seconds), ("constructor_seconds", constructor_seconds)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(name + " must be positive finite")
    if constructor_seconds > 60 or not 0.01 <= solver_seconds <= 3600:
        raise ValueError("hybrid construction/CP request limit outside supported bounds")
    for name, value in (("lookahead_depth", lookahead_depth), ("max_slots", max_slots),
                        ("max_candidate_evaluations", max_candidate_evaluations)):
        if type(value) is not int or value < 1:
            raise ValueError(name + " must be a positive integer")
    if max_slots * lookahead_depth > 128:
        raise ValueError("event total slots must not exceed 128")
    return {"period_seconds": period_seconds, "plan_seconds": plan_seconds,
            "lookahead_depth": lookahead_depth, "max_slots_per_wave": max_slots,
            "event_total_slots_per_machine": max_slots * lookahead_depth,
            "periodic_cp_request_seconds": solver_seconds,
            "constructor_seconds": constructor_seconds,
            "max_candidate_evaluations": max_candidate_evaluations,
            "anchor_time": 0, "incumbent_rule": "gain_rate"}


class HybridSchedule:
    """Serializable absolute clock; event commits never move the full deadline."""

    def __init__(self, config, *, state=None):
        self.config = deepcopy(config)
        expected = configuration(period_seconds=config["period_seconds"],
                                 plan_seconds=config["plan_seconds"],
                                 lookahead_depth=config["lookahead_depth"],
                                 max_slots=config["max_slots_per_wave"],
                                 solver_seconds=config["periodic_cp_request_seconds"],
                                 constructor_seconds=config["constructor_seconds"],
                                 max_candidate_evaluations=config["max_candidate_evaluations"])
        if config != expected:
            raise ValueError("hybrid configuration is not canonical")
        self.next_full_at = 0
        self.last_commit_time = None
        self.last_periodic_commit_time = None
        if state is not None:
            if state.get("schema") != VERSION or state.get("configuration") != config:
                raise ValueError("hybrid checkpoint configuration differs")
            self.next_full_at = state["next_full_at"]
            self.last_commit_time = state["last_commit_time"]
            self.last_periodic_commit_time = state["last_periodic_commit_time"]
            self._validate_state()

    def _validate_state(self):
        for value in (self.next_full_at, self.last_commit_time, self.last_periodic_commit_time):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not math.isfinite(value) or value < 0):
                raise ValueError("invalid hybrid checkpoint time")
        if self.last_periodic_commit_time is None:
            if self.next_full_at != 0 or self.last_commit_time is not None:
                raise ValueError("hybrid checkpoint lacks its first periodic commit")
        elif (self.last_commit_time is None or self.last_commit_time < self.last_periodic_commit_time
              or self.next_full_at != self._next_boundary(self.last_periodic_commit_time)
              or self.last_commit_time >= self.next_full_at):
            raise ValueError("hybrid checkpoint clock is inconsistent")

    def _next_boundary(self, now):
        period = self.config["period_seconds"]
        return (math.floor(now / period) + 1) * period

    def mode(self, now):
        if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now) or now < 0:
            raise ValueError("invalid hybrid current time")
        if self.last_commit_time is not None and now < self.last_commit_time:
            raise ValueError("hybrid clock cannot move backwards")
        return PERIODIC if now >= self.next_full_at else EVENT

    def request(self, now, remaining_cp_seconds):
        if (isinstance(remaining_cp_seconds, bool) or not isinstance(remaining_cp_seconds, (int, float))
                or not math.isfinite(remaining_cp_seconds) or remaining_cp_seconds < -1e-9):
            raise ValueError("invalid inherited cumulative CP budget")
        mode = self.mode(now)
        if mode == PERIODIC:
            if remaining_cp_seconds < 0.05:
                raise RuntimeError("solver cumulative budget exhausted at required hybrid periodic optimization")
            return mode, min(remaining_cp_seconds, self.config["periodic_cp_request_seconds"])
        return mode, 0.0

    def committed(self, now, mode):
        """Call only after the executor has accepted the new explicit plan."""
        if mode != self.mode(now):
            raise ValueError("hybrid commit mode differs from the due policy")
        if mode == PERIODIC:
            self.last_periodic_commit_time = now
            self.next_full_at = self._next_boundary(now)
        self.last_commit_time = now

    def advance_until(self, now, horizon):
        if self.next_full_at <= now:
            raise ValueError("required periodic plan has not been committed")
        return min(horizon, self.next_full_at)

    def snapshot(self):
        return {"schema": VERSION, "configuration": deepcopy(self.config),
                "next_full_at": self.next_full_at, "last_commit_time": self.last_commit_time,
                "last_periodic_commit_time": self.last_periodic_commit_time}


def solve_hybrid_plan(problem, *, mode, config, time_limit_seconds=0,
                      seed=11, weights=None, plan_version=1):
    """Return a full explicit candidate, not an executor fallback or delta.

    Future C may explicitly select this API; its caller still owns reservation,
    state persistence and plan application. B must not call this optimizer.
    """
    started = time.perf_counter()
    HybridSchedule(config)  # Validate before invoking either algorithm.
    if mode == PERIODIC:
        if not 0.01 <= time_limit_seconds <= config["periodic_cp_request_seconds"]:
            raise ValueError("periodic CP request exceeds the registered cap")
        result = solve_decomposed_plan(problem, time_limit_seconds=time_limit_seconds,
                                       seed=seed, weights=weights,
                                       max_slots_per_machine=config["max_slots_per_wave"],
                                       plan_version=plan_version)
        construction_wall = sum(call["response"].get("classical_incumbent", {}).get("wall_seconds", 0)
                                for call in result.get("family_solves", []))
    elif mode == EVENT:
        if time_limit_seconds != 0:
            raise ValueError("event construction must reserve exactly zero CP seconds")
        result = _solve_constructive_plan(
            problem, time_limit_seconds=config["constructor_seconds"], seed=seed, weights=weights,
            max_slots_per_machine=config["event_total_slots_per_machine"], plan_version=plan_version,
            max_candidate_evaluations=config["max_candidate_evaluations"], builder=build_incumbent)
        construction_wall = result["classical_construction_wall_seconds"]
    else:
        raise ValueError("unknown hybrid mode")
    if result["solver_status"] in ("OPTIMAL", "FEASIBLE", "FEASIBLE_HEURISTIC"):
        if not result.get("nominal_audit", {}).get("valid"):
            # Keep the failed candidate/evidence; never switch algorithms here.
            result["solver_status"] = "INVALID_NOMINAL_PLAN"
    result.update(hybrid_version=VERSION, hybrid_mode=mode,
                  hybrid_configuration=deepcopy(config),
                  cp_requested_seconds_reserved=time_limit_seconds,
                  classical_construction_wall_seconds=construction_wall,
                  construction_cost_scope="incumbent construction including its independent nominal validation",
                  constructor_budget_seconds=config["constructor_seconds"] if mode == EVENT else None,
                  wall_seconds=time.perf_counter() - started)
    if result.get("plan") is not None:
        result["plan"]["hybrid_mode"] = mode
        result["plan"]["reason"] = "explicit hybrid " + mode
    return result
