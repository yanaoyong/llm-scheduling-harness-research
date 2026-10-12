"""Shared A/C construction contracts; synthetic data, no CP or model calls."""
from contextlib import ExitStack
from copy import deepcopy
import unittest
from unittest.mock import patch

from src.smt_fullfab.constructive_tool import (
    MAX_CANDIDATE_EVALUATIONS, MODEL_VERSION, solve_constructive_plan,
)
from src.smt_fullfab.hybrid import EVENT, configuration, solve_hybrid_plan
from src.smt_fullfab.incumbent import build_incumbent, validate_nominal_plan
from tests.test_smt_fullfab_optimizer import machine, operation, problem


def cross_family_fixture():
    return problem([machine(1), machine(2), machine(3, "G"), machine(913, "idle")], [
        operation("a", eligible_machines=[1, 2], transport_seconds=2),
        operation("waiting", mid=3, family="G", batch_min=2, batch_max=2),
        operation("later", mid=3, family="G", lot_id="a", step=2,
                  predecessor_ids=["a"], batch_min=2, batch_max=2),
        operation("back", eligible_machines=[1, 2], lot_id="a", step=3,
                  predecessor_ids=["later"], same_machine_as="a"),
    ])


class ConstructiveToolTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target in ("CpModel", "CpSolver"):
            self.stack.enter_context(patch("src.smt_fullfab.optimizer.cp_model." + target,
                                           side_effect=AssertionError("No CP in construction tests")))

    def solve(self, source, **kwargs):
        result = solve_constructive_plan(source, time_limit_seconds=0.25, **kwargs)
        self.assertEqual(result["solver_status"], "FEASIBLE_HEURISTIC", result)
        self.assertEqual(result["model"], MODEL_VERSION)
        self.assertIsInstance(result["model"], str)
        self.assertEqual(result["selected_source"], "classical_incumbent")
        self.assertEqual(result["cp_sat"]["status"], "NOT_RUN_BY_POLICY")
        self.assertEqual(result["cp_sat"]["calls"], 0)
        self.assertEqual(result["solver_calls"], 0)
        self.assertEqual(result["solver_requested_seconds"], 0)
        self.assertEqual(result["solve_wall_seconds"], 0)
        self.assertIsNone(result["best_bound"])
        self.assertFalse(result["global_optimality"])
        self.assertFalse(result["global_optimality_claim"])
        self.assertTrue(result["nominal_audit"]["valid"])
        self.assertTrue(validate_nominal_plan(source, result["plan"])["valid"])
        return result

    def test_public_api_keeps_cross_family_batch_future_binding_and_full_scope(self):
        source = cross_family_fixture()
        before = deepcopy(source)
        result = self.solve(source, plan_version="tool-plan")
        self.assertEqual(source, before)
        self.assertEqual(result["plan"]["version"], "tool-plan")
        self.assertEqual(result["plan"]["scope"], [1, 2, 3, 913])
        self.assertEqual(result["machine_ids_considered"], [1, 2, 3, 913])
        selected = {oid: task for task in result["tasks"] for oid in task["operation_ids"]}
        self.assertEqual(set(selected), {"a", "waiting", "later", "back"})
        self.assertGreaterEqual(selected["later"]["start"], selected["a"]["end"])
        self.assertGreaterEqual(selected["back"]["start"], selected["later"]["end"])
        self.assertEqual(selected["back"]["machine"], selected["a"]["machine"])
        self.assertEqual(selected["later"]["id"], selected["waiting"]["id"])
        self.assertTrue(any(hold["machine"] == 913 for hold in result["plan"]["holds"]))

    def test_public_plan_and_hybrid_actions_match_previous_event_constructor(self):
        epoch = 1603.1013031725258
        cascading = problem([machine(1, available_at=epoch, cascading=True,
                                     processing_until=[epoch+10, epoch+20])], [
            operation(oid, release_time=epoch, processing_seconds=10, occupation_seconds=3)
            for oid in ("a", "b", "c")])
        cascading.update(time=epoch, horizon_end=epoch+100)
        setup = problem([machine(1, current_setup="A", min_left=2, min_setup="A",
                                 unavailable_intervals=[[7, 12]])], [
            operation("a1", setup="A"), operation("a2", setup="A"),
            operation("b", setup="B", priority=100),
        ], setup_transitions={"": {"A": 2, "B": 3}, "A": {"B": 4}}, min_runs={"A": 2})
        limited = problem([machine(1)], [operation(str(i)) for i in range(10)])
        cfg = configuration(constructor_seconds=0.25)
        for source in (cross_family_fixture(), setup, cascading, limited):
            with self.subTest(operations=[o["operation_id"] for o in source["operations"]]):
                # This is the exact pre-extraction EVENT construction contract.
                previous = build_incumbent(source, weights=None, max_slots_per_machine=8,
                                           plan_version="equivalence", rule="gain_rate",
                                           max_wall_seconds=0.25, max_candidate_evaluations=250000)
                current = self.solve(source, plan_version="equivalence")
                self.assertEqual(current["plan"], previous["plan"])
                for key in ("tasks", "unplanned_operations", "nominal_audit", "objective", "stop_reason"):
                    self.assertEqual(current[key], previous[key], key)
                expected_hybrid = deepcopy(previous["plan"])
                expected_hybrid["hybrid_mode"] = EVENT
                expected_hybrid["reason"] = "explicit hybrid " + EVENT
                hybrid = solve_hybrid_plan(source, mode=EVENT, config=cfg, plan_version="equivalence")
                self.assertEqual(hybrid["plan"], expected_hybrid)
                self.assertEqual(hybrid["tasks"], previous["tasks"])
                self.assertEqual(hybrid["unplanned_operations"], previous["unplanned_operations"])
                self.assertEqual(hybrid["objective"], previous["objective"])

    def test_seed_is_recorded_but_does_not_change_nontruncated_plan(self):
        source = cross_family_fixture()
        first = self.solve(source, seed=0)
        second = self.solve(source, seed=2**31-1)
        self.assertEqual(first["plan"], second["plan"])
        self.assertIsNone(first["stop_reason"])
        self.assertEqual(first["parameters"]["seed"], 0)
        self.assertEqual(second["parameters"]["seed"], 2**31-1)
        self.assertFalse(first["seed_semantics"]["used"])
        self.assertEqual(first["seed_semantics"]["meaning"], "not_used_by_deterministic_constructor")
        self.assertIn("wall-clock truncation", first["seed_semantics"]["qualification"])

    def test_caps_weights_and_construction_cost_are_explicit(self):
        source = problem([machine(1)], [operation("a"), operation("b")])
        with patch("src.smt_fullfab.constructive_tool.build_incumbent", wraps=build_incumbent) as build:
            result = self.solve(source, max_slots_per_machine=1, weights={"setup": 7})
        self.assertEqual(build.call_count, 1)
        self.assertEqual(build.call_args.kwargs["max_wall_seconds"], 0.25)
        self.assertEqual(build.call_args.kwargs["max_slots_per_machine"], 1)
        self.assertEqual(build.call_args.kwargs["max_candidate_evaluations"], MAX_CANDIDATE_EVALUATIONS)
        self.assertEqual(result["constructor_budget_seconds"], 0.25)
        self.assertGreater(result["classical_construction_wall_seconds"], 0)
        self.assertGreaterEqual(result["wall_seconds"], result["classical_construction_wall_seconds"])
        self.assertIn("independent nominal validation", result["construction_cost_scope"])
        self.assertIn("not interruptible", result["construction_limit_scope"])
        self.assertEqual(result["parameters"]["weights"]["setup"], 7)
        self.assertEqual(result["budgets"]["max_candidate_evaluations"], MAX_CANDIDATE_EVALUATIONS)
        selected = {oid for task in result["tasks"] for oid in task["operation_ids"]}
        self.assertEqual(selected | set(result["unplanned_operations"]), {"a", "b"})
        self.assertEqual(len(result["tasks"]), 1)

    def test_hybrid_retains_its_registered_candidate_cap(self):
        cfg = configuration(constructor_seconds=0.25, max_candidate_evaluations=1)
        source = problem([machine(1)], [operation("a"), operation("b")])
        previous = build_incumbent(source, max_slots_per_machine=8, max_wall_seconds=0.25,
                                   max_candidate_evaluations=1)
        result = solve_hybrid_plan(source, mode=EVENT, config=cfg)
        self.assertEqual(result["tasks"], previous["tasks"])
        self.assertEqual(result["unplanned_operations"], previous["unplanned_operations"])
        self.assertEqual(result["stop_reason"], "construction_budget")
        self.assertEqual(result["parameters"]["max_candidate_evaluations"], 1)

    def test_invalid_caps_seed_or_weights_rejected_before_construction(self):
        source = problem([machine(1)], [operation("a")])
        cases = [
            {"time_limit_seconds": value} for value in (True, False, 0, -1, 60.01, float("nan"), float("inf"), "1")
        ] + [
            {"max_slots_per_machine": value} for value in (True, 0, -1, 129, 1.5, "4")
        ] + [
            {"seed": value} for value in (True, -1, 2**31, 1.5, "11")
        ] + [
            {"weights": value} for value in (False, 3, [], {"unknown": 1}, {"setup": True}, {"flow": -1})
        ]
        with patch("src.smt_fullfab.constructive_tool.build_incumbent") as build:
            for change in cases:
                with self.subTest(change=change), self.assertRaises(ValueError):
                    solve_constructive_plan(source, **change)
            build.assert_not_called()

    def test_independent_nominal_failure_is_visible_without_fallback(self):
        source = problem([machine(1)], [operation("a")])
        with patch("src.smt_fullfab.incumbent.validate_nominal_plan", return_value={
            "valid": False, "errors": ["synthetic independent checker failure"], "checked_tasks": 1,
        }), patch("src.smt_fullfab.hybrid.solve_decomposed_plan") as cp:
            result = solve_constructive_plan(source, 0.25)
        self.assertEqual(result["solver_status"], "INVALID_HEURISTIC")
        self.assertEqual(result["nominal_audit"]["errors"], ["synthetic independent checker failure"])
        self.assertIsNone(result["objective"])
        self.assertEqual(len(result["tasks"]), 1)  # Preserve failed candidate for inspection.
        cp.assert_not_called()

    def test_missing_or_false_nominal_audit_cannot_claim_feasible(self):
        source = problem([machine(1)], [operation("a")])
        candidate = build_incumbent(source, max_wall_seconds=0.25)
        for audit in (None, {"valid": False, "errors": ["injected"]}):
            bad = deepcopy(candidate)
            if audit is None:
                del bad["nominal_audit"]
            else:
                bad["nominal_audit"] = audit
            with self.subTest(audit=audit), patch("src.smt_fullfab.constructive_tool.build_incumbent", return_value=bad):
                result = solve_constructive_plan(source, 0.25)
            self.assertEqual(result["solver_status"], "INVALID_NOMINAL_PLAN")
            self.assertEqual(result["tasks"], candidate["tasks"])

    def test_constructor_exception_is_not_replaced(self):
        source = problem([machine(1)], [operation("a")])
        with patch("src.smt_fullfab.constructive_tool.build_incumbent", side_effect=RuntimeError("constructor failure")) as build:
            with self.assertRaisesRegex(RuntimeError, "constructor failure"):
                solve_constructive_plan(source, 0.25)
            self.assertEqual(build.call_count, 1)

    def test_no_feasible_batch_preserves_unplanned_no_plan_and_explicit_hold(self):
        source = problem([machine(1)], [operation("alone", batch_min=2, batch_max=2)])
        result = solve_constructive_plan(source, 0.25)
        self.assertEqual(result["solver_status"], "NO_PLAN")
        self.assertEqual(result["tasks"], [])
        self.assertEqual(set(result["unplanned_operations"]), {"alone"})
        self.assertEqual(result["plan"]["scope"], [1])
        self.assertEqual(result["plan"]["holds"][0]["machine"], 1)
        self.assertIsNone(result["best_bound"])

    def test_frozen_commitments_refusal_keeps_all_demand_explicit(self):
        source = problem([machine(1)], [operation("a")], frozen_tasks=[{"id": "retained"}])
        result = solve_constructive_plan(source, 0.25)
        self.assertEqual(result["solver_status"], "NOT_BUILT_FROZEN_COMMITMENTS")
        self.assertIsNone(result["plan"])
        self.assertEqual(result["tasks"], [])
        self.assertEqual(set(result["unplanned_operations"]), {"a"})
        self.assertEqual(result["solver_calls"], 0)

    def test_empty_input_can_have_valid_explicit_idle_plan(self):
        source = problem([machine(1)], [])
        result = self.solve(source)
        self.assertEqual(result["operation_count"], 0)
        self.assertEqual(result["planned_operations"], 0)
        self.assertEqual(result["unplanned_operations"], {})
        self.assertEqual(result["plan"]["scope"], [1])


if __name__ == "__main__":
    unittest.main()
