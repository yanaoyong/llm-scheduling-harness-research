"""Bounded synthetic decomposition tests; never invokes the model channel."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from src.smt_fullfab.decomposition import solve_decomposed_plan
from tests.test_smt_fullfab_optimizer import machine, operation, problem


class FullFabDecompositionTests(unittest.TestCase):
    def solve(self, source, **kwargs):
        result = solve_decomposed_plan(source, time_limit_seconds=0.6,
                                       max_slots_per_machine=3, **kwargs)
        self.assertEqual(result["solver_status"], "FEASIBLE", result)
        return result

    def test_cross_family_and_reentrant_machine_reservations(self):
        source = problem([machine(1), machine(2, "G"), machine(913, "unused")], [
            operation("a1", transport_seconds=3),
            operation("a2", mid=2, family="G", lot_id="a1", step=2,
                      predecessor_ids=["a1"], transport_seconds=4),
            operation("a3", lot_id="a1", step=3, predecessor_ids=["a2"]),
            operation("b1"),
        ])
        before = deepcopy(source)
        result = self.solve(source)
        self.assertEqual(source, before)
        self.assertEqual(result["plan"]["scope"], [1, 2, 913])
        tasks = {oid: task for task in result["tasks"] for oid in task["operation_ids"]}
        self.assertEqual(set(tasks), {"a1", "a2", "a3", "b1"})
        self.assertGreaterEqual(tasks["a2"]["start"], tasks["a1"]["end"])
        self.assertGreaterEqual(tasks["a3"]["start"], tasks["a2"]["end"])
        self.assertGreaterEqual(tasks["a3"]["start"], tasks["b1"]["occupied_until"])
        self.assertEqual(tasks["a2"]["predecessor_task_ids"], [tasks["a1"]["id"]])
        self.assertEqual(len({task["id"] for task in result["tasks"]}), 4)
        self.assertLessEqual(result["solver_requested_seconds"], 0.6 + 1e-9)
        self.assertIsNone(result["best_bound"])

    def test_earlier_unplanned_batch_member_can_join_later_wave(self):
        source = problem([machine(1), machine(2, "G")], [
            operation("waiting", mid=2, family="G", batch_min=2, batch_max=2),
            operation("upstream"),
            operation("later", mid=2, family="G", predecessor_ids=["upstream"],
                      lot_id="upstream", batch_min=2, batch_max=2),
        ])
        result = self.solve(source)
        self.assertEqual(result["unplanned_operations"], {})
        batch = next(task for task in result["tasks"] if task["machine"] == 2)
        self.assertEqual(set(batch["operation_ids"]), {"waiting", "later"})

    def test_no_upstream_plan_cannot_create_a_downstream_task(self):
        source = problem([machine(1), machine(2, "G")], [
            operation("blocked", batch_min=2, batch_max=2),
            operation("successor", mid=2, family="G", predecessor_ids=["blocked"]),
            operation("independent", mid=2, family="G", batch_key=["other", 1]),
        ])
        result = self.solve(source)
        ids = {oid for task in result["tasks"] for oid in task["operation_ids"]}
        self.assertEqual(ids, {"independent"})
        self.assertEqual(result["unplanned_operations"]["successor"], "upstream_operation_not_planned")

    def test_machine_setup_and_minrun_carried_between_waves(self):
        source = problem([machine(1), machine(2, "G")], [
            operation("a", setup="A"),
            operation("g", mid=2, family="G", predecessor_ids=["a"]),
            operation("b", setup="B", predecessor_ids=["g"]),
        ], setup_transitions={"": {"A": 1, "B": 1}, "A": {"B": 7}}, min_runs={"A": 2})
        result = self.solve(source)
        self.assertIn("b", result["unplanned_operations"])
        final = next(call for call in result["family_solves"] if call["wave"] == 2)
        self.assertEqual(final["problem"]["machines"][0]["current_setup"], "A")
        self.assertEqual(final["problem"]["machines"][0]["min_left"], 1)

    def test_future_binding_uses_upstream_selected_machine(self):
        source = problem([machine(1), machine(2)], [
            operation("a", eligible_machines=[1, 2]),
            operation("b", eligible_machines=[1, 2], predecessor_ids=["a"], same_machine_as="a"),
        ])
        result = self.solve(source)
        self.assertEqual(len(result["tasks"]), 2)
        self.assertEqual(result["tasks"][0]["machine"], result["tasks"][1]["machine"])

    def test_local_unknown_is_retained_without_rule_fallback(self):
        source = problem([machine(1)], [operation("a")])
        failed = {"solver_status": "UNKNOWN", "solve_wall_seconds": 0.01,
                  "tasks": [], "unplanned_operations": {"a": "no_solver_solution"}}
        with patch("src.smt_fullfab.decomposition.solve_plan", return_value=failed) as solve:
            result = solve_decomposed_plan(source, time_limit_seconds=0.2)
        self.assertEqual(solve.call_count, 1)
        self.assertEqual(result["solver_status"], "NO_PLAN")
        self.assertEqual(result["decomposition_status"], "PARTIAL_SOLVER_FAILURE")
        self.assertEqual(result["tasks"], [])
        self.assertEqual(result["family_failures"][0]["status"], "UNKNOWN")

    def test_budget_too_small_refuses_all_calls_and_keeps_all_work(self):
        source = problem([machine(1), machine(2, "G")], [operation("a"), operation("b", mid=2, family="G")])
        result = solve_decomposed_plan(source, time_limit_seconds=0.01)
        self.assertEqual(result["solver_status"], "BUDGET_TOO_SMALL")
        self.assertEqual(result["solver_calls"], 0)
        self.assertEqual(set(result["unplanned_operations"]), {"a", "b"})

    def test_downstream_load_is_visible_coordination_input(self):
        source = problem([machine(1), machine(2, "G")], [
            operation("a", remaining_work_seconds=1),
            operation("b", mid=2, family="G", predecessor_ids=["a"],
                      processing_seconds=20, occupation_seconds=20),
        ])
        result = self.solve(source, load_pressure_factor=2)
        first = next(row for row in result["coordination"] if row["operation_id"] == "a")
        self.assertEqual(first["downstream_load_seconds"], 20)
        self.assertEqual(first["adjusted_remaining_work_seconds"], 41)

    def test_frozen_future_tasks_fail_closed(self):
        source = problem([machine(1)], [operation("a")],
                         frozen_tasks=[{"operation_ids": ["a"], "machine": 1, "start": 0}])
        with self.assertRaisesRegex(ValueError, "frozen_tasks"):
            self.solve(source)

    def test_fractional_epoch_across_waves_has_identical_machine_endpoints(self):
        from src.smt_fullfab.incumbent import build_incumbent
        epoch = 1603.1013031725258
        source = problem([machine(1), machine(2, "G")], [
            operation("long", release_time=epoch+3237, processing_seconds=5413,
                      occupation_seconds=5413),
            operation("upstream", mid=2, family="G", release_time=epoch),
            operation("next", predecessor_ids=["upstream"], release_time=epoch,
                      processing_seconds=5413, occupation_seconds=5413),
        ])
        source.update(time=epoch, horizon_end=epoch+14400)

        def seed_only(problem, **kwargs):
            candidate = build_incumbent(problem, max_slots_per_machine=3,
                                        plan_version=kwargs["plan_version"], max_wall_seconds=0.25)
            return {**candidate, "solver_status": candidate["status"],
                    "solve_wall_seconds": 0, "cp_sat": {"status": "NOT_RUN_TEST"}}

        with patch("src.smt_fullfab.decomposition.solve_plan", side_effect=seed_only):
            result = solve_decomposed_plan(source, time_limit_seconds=0.1, max_slots_per_machine=3)
        tasks = sorted((task for task in result["tasks"] if task["machine"] == 1), key=lambda task: task["sequence"])
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0]["process_end"], tasks[1]["start"])
        self.assertTrue(result["nominal_audit"]["valid"])


if __name__ == "__main__":
    unittest.main()
