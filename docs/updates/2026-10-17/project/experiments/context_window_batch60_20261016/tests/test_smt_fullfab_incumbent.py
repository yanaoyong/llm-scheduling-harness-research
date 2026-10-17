"""Independent nominal checks of the explicit classical feasible incumbent."""
from copy import deepcopy
import unittest

from src.smt_fullfab.incumbent import build_incumbent, validate_nominal_plan, nominal_objective
from src.smt_fullfab.optimizer import solve_plan
from tests.test_smt_fullfab_optimizer import machine, operation, problem


class FullFabIncumbentTests(unittest.TestCase):
    def build(self, source, **kwargs):
        result = build_incumbent(source, max_wall_seconds=0.25, **kwargs)
        self.assertEqual(result["status"], "FEASIBLE_HEURISTIC", result)
        self.assertTrue(validate_nominal_plan(source, result["plan"])["valid"])
        return result

    def test_future_cross_family_binding_and_window_end_wip(self):
        source = problem([machine(1), machine(2), machine(3, "G")], [
            operation("a", eligible_machines=[1, 2], transport_seconds=2),
            operation("b", mid=3, family="G", predecessor_ids=["a"], lot_id="a", step=2),
            operation("c", eligible_machines=[1, 2], predecessor_ids=["b"],
                      same_machine_as="a", lot_id="a", step=3,
                      processing_seconds=50, occupation_seconds=50),
        ], horizon=20)
        before = deepcopy(source)
        result = self.build(source)
        self.assertEqual(source, before)
        tasks = {oid: task for task in result["tasks"] for oid in task["operation_ids"]}
        self.assertEqual(set(tasks), {"a", "b", "c"})
        self.assertGreaterEqual(tasks["b"]["start"], tasks["a"]["end"])
        self.assertGreaterEqual(tasks["c"]["start"], tasks["b"]["end"])
        self.assertEqual(tasks["a"]["machine"], tasks["c"]["machine"])
        self.assertGreater(tasks["c"]["end"], 20)

    def test_compatible_batch_waits_for_unplanned_upstream(self):
        source = problem([machine(1), machine(2, "G")], [
            operation("a"), operation("waiting", mid=2, family="G", batch_min=2, batch_max=2),
            operation("future", mid=2, family="G", predecessor_ids=["a"], batch_min=2, batch_max=2),
        ])
        result = self.build(source)
        task = next(task for task in result["tasks"] if task["machine"] == 2)
        self.assertEqual(set(task["operation_ids"]), {"waiting", "future"})
        self.assertGreaterEqual(task["start"], 5)

    def test_setup_minrun_and_known_downtime(self):
        source = problem([machine(1, current_setup="A", min_left=2, min_setup="A",
                                  unavailable_intervals=[[7, 12]])], [
            operation("a1", setup="A"), operation("a2", setup="A"),
            operation("b", setup="B", priority=100),
        ], setup_transitions={"": {"A": 2, "B": 3}, "A": {"B": 4}}, min_runs={"A": 2})
        result = self.build(source)
        tasks = sorted(result["tasks"], key=lambda task: task["sequence"])
        self.assertEqual({tasks[0]["operation_ids"][0], tasks[1]["operation_ids"][0]}, {"a1", "a2"})
        self.assertEqual(tasks[1]["start"], 12)
        self.assertEqual(tasks[1]["setup_seconds"], 2)
        self.assertEqual(tasks[2]["setup_seconds"], 4)

    def test_cascading_existing_occupancy_is_not_erased(self):
        source = problem([machine(1, cascading=True, processing_until=[10, 20])], [
            operation("a", processing_seconds=10, occupation_seconds=3),
            operation("b", processing_seconds=10, occupation_seconds=3),
        ])
        result = self.build(source)
        tasks = sorted(result["tasks"], key=lambda task: task["sequence"])
        self.assertGreaterEqual(tasks[0]["start"], 10)
        self.assertGreaterEqual(tasks[1]["start"], 20)

    def test_independent_checker_rejects_precedence_and_arithmetic_tampering(self):
        source = problem([machine(1), machine(2, "G")], [
            operation("a"), operation("b", mid=2, family="G", predecessor_ids=["a"]),
        ])
        result = self.build(source)
        plan = deepcopy(result["plan"])
        downstream = next(task for task in plan["tasks"] if task["machine"] == 2)
        downstream["start"] = downstream["not_before"] = 0
        downstream["end"] = downstream["expected_end"] = 5
        downstream["process_end"] = downstream["occupied_until"] = 5
        self.assertIn("cross-family precedence", validate_nominal_plan(source, plan)["errors"])
        plan = deepcopy(result["plan"])
        plan["tasks"][0]["setup_seconds"] = 100
        self.assertIn("processing/setup/cadence/transport arithmetic", validate_nominal_plan(source, plan)["errors"])

    def test_model_size_refusal_retains_attributed_classical_solution(self):
        source = problem([machine(1)], [operation("a"), operation("b")])
        result = solve_plan(source, max_assignment_variables=1, incumbent_max_seconds=0.25)
        self.assertEqual(result["solver_status"], "FEASIBLE_HEURISTIC")
        self.assertEqual(result["selected_source"], "classical_incumbent")
        self.assertEqual(result["cp_sat"]["status"], "MODEL_SIZE_LIMIT")
        self.assertIsNone(result["best_bound"])
        self.assertEqual(len(result["tasks"]), 2)
        self.assertTrue(result["nominal_audit"]["valid"])

    def test_cp_sat_hint_cannot_worsen_incumbent_objective(self):
        source = problem([machine(1)], [operation("a"), operation("b", priority=10)])
        result = solve_plan(source, time_limit_seconds=0.25, incumbent_max_seconds=0.25)
        self.assertIn(result["solver_status"], ("OPTIMAL", "FEASIBLE", "FEASIBLE_HEURISTIC"))
        self.assertGreaterEqual(result["objective"], result["classical_incumbent"]["objective"])
        self.assertEqual(result["objective"], nominal_objective(source, result["tasks"]))
        self.assertTrue(validate_nominal_plan(source, result["plan"])["valid"])

    def test_terminal_wait_is_conditional_not_an_initial_machine_block(self):
        source = problem([machine(1), machine(2, "unused")], [operation("a")])
        result = self.build(source)
        holds = {hold["machine"]: hold for hold in result["plan"]["holds"]}
        self.assertEqual(holds[1]["after_task_id"], result["tasks"][0]["id"])
        self.assertNotIn("after_task_id", holds[2])

    def test_latest_start_prevents_late_heuristic_dispatch(self):
        source = problem([machine(1, available_at=20)], [operation("a", latest_start=10)])
        result = self.build(source)
        self.assertEqual(result["tasks"], [])
        self.assertIn("a", result["unplanned_operations"])

    def test_fractional_current_time_remains_integer_relative_in_hint(self):
        source = problem([machine(1, available_at=0.3)], [operation("a", release_time=0.3,
                                                  processing_seconds=2.2, occupation_seconds=2.2)])
        source["time"] = 0.3
        source["horizon_end"] = 10.3
        result = solve_plan(source, time_limit_seconds=0.25)
        self.assertIn(result["solver_status"], ("OPTIMAL", "FEASIBLE", "FEASIBLE_HEURISTIC"))
        self.assertEqual(result["objective"], nominal_objective(source, result["tasks"]))
        self.assertTrue(validate_nominal_plan(source, result["plan"])["valid"])

    def test_nominal_capacity_still_rejects_a_real_integer_overlap(self):
        source = problem([machine(1, cascading=True)], [
            operation(str(index), processing_seconds=10, occupation_seconds=3) for index in range(3)
        ])
        result = self.build(source)
        plan = deepcopy(result["plan"])
        third = sorted(plan["tasks"], key=lambda task: task["sequence"])[2]
        third.update(start=6, not_before=6, process_end=16, occupied_until=9,
                     end=16, expected_end=16)
        checked = validate_nominal_plan(source, plan)
        self.assertFalse(checked["valid"])
        self.assertIn("processing slot capacity", checked["errors"])


if __name__ == "__main__":
    unittest.main()
