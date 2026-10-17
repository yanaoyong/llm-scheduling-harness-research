"""Synthetic bounded tests; no simulation background rule or model channel."""
import copy
import unittest

from src.smt_fullfab.optimizer import solve_plan


def machine(mid, family="F", **kwargs):
    return {"machine": mid, "family": family, "available_at": 0,
            "current_setup": "", **kwargs}


def operation(oid, mid=1, family="F", **kwargs):
    return {"operation_id": oid, "lot_id": oid, "step": 1, "visit": 1,
            "family": family, "eligible_machines": [mid], "release_time": 0,
            "processing_seconds": 5, "occupation_seconds": 5,
            "transport_seconds": 0, "batch_key": ["product", 1],
            "batch_min": 1, "batch_max": 1, "setup": "",
            "priority": 1, "due": 80, "remaining_work_seconds": 0,
            "predecessor_ids": [], **kwargs}


def problem(machines, operations, horizon=100, **kwargs):
    return {"time": 0, "horizon_end": horizon,
            "machines": machines, "operations": operations, **kwargs}


class FullFabOptimizerTests(unittest.TestCase):
    def solve(self, p, **kwargs):
        result = solve_plan(p, time_limit_seconds=0.25, max_slots_per_machine=4, **kwargs)
        self.assertIn(result["solver_status"], ("OPTIMAL", "FEASIBLE"), result)
        return result

    def test_cross_family_future_precedence_transport_and_all_machines(self):
        p = problem([machine(1, "F"), machine(2, "G"), machine(913, "idle")], [
            operation("a1", transport_seconds=3, remaining_work_seconds=5),
            operation("a2", mid=2, family="G", lot_id="a1", step=2,
                      predecessor_ids=["a1"]),
            operation("b", mid=2, family="G", release_time=12),
        ])
        before = copy.deepcopy(p)
        result = self.solve(p)
        self.assertEqual(p, before)
        self.assertEqual(result["machine_ids_considered"], [1, 2, 913])
        tasks = {oid: task for task in result["tasks"] for oid in task["operation_ids"]}
        self.assertEqual(set(tasks), {"a1", "a2", "b"})
        self.assertGreaterEqual(tasks["a2"]["start"], tasks["a1"]["end"])
        self.assertEqual(tasks["a1"]["end"] - tasks["a1"]["start"], 8)
        self.assertGreaterEqual(tasks["b"]["start"], 12)
        self.assertEqual(tasks["a2"]["predecessor_task_ids"], [tasks["a1"]["id"]])
        self.assertEqual([hold for hold in result["plan"]["holds"] if "after_task_id" not in hold], [{"machine": 913, "until": 100,
                                                     "reason": "no_candidate_batch"}])

    def test_batch_members_selected_once_and_minimum_not_faked(self):
        operations = [operation(str(i), batch_min=2, batch_max=3) for i in range(5)]
        result = self.solve(problem([machine(1), machine(2)], operations))
        ids = [oid for task in result["tasks"] for oid in task["operation_ids"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 5)
        self.assertTrue(all(2 <= len(task["lot_ids"]) <= 3 for task in result["tasks"]))
        insufficient = self.solve(problem([machine(1)], [operation("alone", batch_min=2, batch_max=3)]))
        self.assertEqual(insufficient["tasks"], [])
        self.assertEqual(insufficient["unplanned_operations"], {"alone": "no_compatible_minimum_batch"})

    def test_downstream_work_changes_upstream_order(self):
        # Current F operations have identical durations/priority/due. The
        # downstream G work differs; a current-action-only model cannot use it.
        p = problem([machine(1), machine(2, "G")], [
            operation("a1"), operation("b1"),
            operation("a2", mid=2, family="G", lot_id="a1", step=2,
                      predecessor_ids=["a1"], processing_seconds=20, occupation_seconds=20),
            operation("b2", mid=2, family="G", lot_id="b1", step=2,
                      predecessor_ids=["b1"], processing_seconds=1, occupation_seconds=1),
        ])
        result = self.solve(p)
        upstream = sorted((task for task in result["tasks"] if task["machine"] == 1),
                          key=lambda task: task["sequence"])
        self.assertEqual([task["operation_ids"] for task in upstream], [["b1"], ["a1"]])

    def test_sequence_dependent_setup_and_initial_minrun(self):
        p = problem([machine(1, current_setup="A", min_left=2, min_setup="A")], [
            operation("a1", setup="A"), operation("a2", setup="A"),
            operation("b", setup="B", priority=100),
        ], setup_transitions=[{"old": "A", "new": "B", "seconds": 7}],
                    min_runs={"A": 2, "B": 1})
        result = self.solve(p)
        ordered = sorted(result["tasks"], key=lambda task: task["sequence"])
        self.assertEqual({ordered[0]["lot_ids"][0], ordered[1]["lot_ids"][0]}, {"a1", "a2"})
        self.assertEqual(ordered[2]["lot_ids"], ["b"])
        self.assertEqual([task["setup_seconds"] for task in ordered], [0, 0, 7])

    def test_new_setup_minrun_cannot_switch_early(self):
        p = problem([machine(1)], [operation("a", setup="A", priority=100),
                                   operation("b", setup="B")],
                    setup_transitions={"": {"A": 1, "B": 1}, "A": {"B": 1}, "B": {"A": 1}},
                    min_runs={"A": 2, "B": 1})
        result = self.solve(p)
        if result["planned_operations"] == 2:
            self.assertEqual(result["tasks"][0]["lot_ids"], ["b"])
        else:
            self.assertEqual(result["tasks"][0]["lot_ids"], ["a"])

    def test_known_downtime_resets_setup_and_blocks_process(self):
        p = problem([machine(1, current_setup="A", unavailable_intervals=[[6, 12]])], [
            operation("before", setup="A", latest_start=0),
            operation("after", setup="A", release_time=12),
        ], setup_transitions={"": {"A": 3}})
        result = self.solve(p)
        tasks = {task["lot_ids"][0]: task for task in result["tasks"]}
        self.assertEqual(tasks["before"]["start"], 0)
        self.assertEqual(tasks["before"]["setup_seconds"], 0)
        self.assertGreaterEqual(tasks["after"]["start"], 12)
        self.assertEqual(tasks["after"]["setup_seconds"], 3)

    def test_cascading_cadence_and_two_slot_capacity(self):
        p = problem([machine(1, cascading=True)], [
            operation(str(i), processing_seconds=10, occupation_seconds=3) for i in range(3)
        ])
        result = self.solve(p)
        tasks = sorted(result["tasks"], key=lambda task: task["start"])
        self.assertEqual(len(tasks), 3)
        self.assertGreaterEqual(tasks[1]["start"], tasks[0]["occupied_until"])
        self.assertGreaterEqual(tasks[2]["start"], tasks[0]["process_end"])
        self.assertLess(tasks[1]["start"], tasks[0]["process_end"])

    def test_existing_inprocess_occupies_cascading_slot(self):
        p = problem([machine(1, cascading=True, processing_until=[20, 30])],
                    [operation("a", processing_seconds=10, occupation_seconds=3)])
        result = self.solve(p)
        self.assertGreaterEqual(result["tasks"][0]["start"], 20)

    def test_future_machine_dedication(self):
        p = problem([machine(1), machine(2)], [
            operation("first", eligible_machines=[1, 2]),
            operation("second", eligible_machines=[1, 2], predecessor_ids=["first"],
                      lot_id="first", step=2, same_machine_as="first"),
        ])
        result = self.solve(p)
        self.assertEqual(len(result["tasks"]), 2)
        self.assertEqual(result["tasks"][0]["machine"], result["tasks"][1]["machine"])

    def test_frozen_task_and_exact_lot_step_visit_evidence(self):
        p = problem([machine(1)], [operation("a", visit=3), operation("b")],
                    frozen_tasks=[{"operation_ids": ["a"], "machine": 1, "start": 25}])
        result = self.solve(p, plan_version=9, freeze_until=30)
        task = next(task for task in result["tasks"] if task["operation_ids"] == ["a"])
        self.assertEqual(task["start"], 25)
        self.assertEqual(task["visits"], [3])
        self.assertEqual(result["plan"]["version"], "9")
        self.assertEqual(result["plan"]["scope"], [1])
        self.assertEqual(result["plan"]["freeze_until"], 30)

    def test_size_refusal_and_infeasible_have_no_background_plan(self):
        p = problem([machine(1)], [operation("a"), operation("b")])
        result = solve_plan(p, max_assignment_variables=1, use_incumbent=False)
        self.assertEqual(result["solver_status"], "MODEL_SIZE_LIMIT")
        self.assertEqual(result["tasks"], [])
        self.assertEqual(set(result["unplanned_operations"]), {"a", "b"})
        p["frozen_tasks"] = [{"operation_ids": ["a"], "machine": 1, "start": 101}]
        result = solve_plan(p, time_limit_seconds=0.1)
        self.assertEqual(result["solver_status"], "INFEASIBLE")
        self.assertEqual(result["tasks"], [])
        self.assertFalse(result["global_optimality_claim"])

    def test_cycle_invalid_machine_and_missing_predecessor_rejected(self):
        with self.assertRaisesRegex(ValueError, "cyclic"):
            self.solve(problem([machine(1)], [operation("a", predecessor_ids=["b"]),
                                              operation("b", predecessor_ids=["a"])]))
        with self.assertRaisesRegex(ValueError, "unknown eligible"):
            self.solve(problem([machine(1)], [operation("a", mid=2)]))
        with self.assertRaisesRegex(ValueError, "missing predecessor"):
            self.solve(problem([machine(1)], [operation("a", predecessor_ids=["missing"])]))

    def test_fractional_time_rounding_is_conservative(self):
        p = problem([machine(1)], [operation("a", processing_seconds=2.2,
                                                    occupation_seconds=2.2, release_time=0.1)])
        result = self.solve(p)
        self.assertGreaterEqual(result["tasks"][0]["start"], 1)
        self.assertEqual(result["tasks"][0]["end"] - result["tasks"][0]["start"], 3)

    def test_long_processing_can_start_and_remain_wip_at_window_end(self):
        p = problem([machine(1)], [operation("long", processing_seconds=60,
                                            occupation_seconds=60)], horizon=10)
        result = self.solve(p)
        self.assertEqual(result["tasks"][0]["start"], 0)
        self.assertEqual(result["tasks"][0]["end"], 60)
        self.assertEqual(result["plan"]["valid_until"], 10)
        self.assertEqual(result["unplanned_operations"], {})

    def test_start_at_exclusive_window_end_is_not_planned(self):
        p = problem([machine(1)], [operation("later", release_time=10)], horizon=10)
        result = self.solve(p)
        self.assertEqual(result["tasks"], [])
        self.assertIn("later", result["unplanned_operations"])


if __name__ == "__main__":
    unittest.main()
