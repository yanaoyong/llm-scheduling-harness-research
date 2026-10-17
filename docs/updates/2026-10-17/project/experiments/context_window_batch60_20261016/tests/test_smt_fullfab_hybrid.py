"""Synthetic contracts only: no model, CP search, or factory performance run."""
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab.hybrid import (EVENT, PERIODIC, HybridSchedule,
                                    configuration, solve_hybrid_plan)
from src.smt_fullfab.incumbent import build_incumbent, validate_nominal_plan
from src.smt_fullfab import runner
from tests.test_smt_fullfab_optimizer import machine, operation, problem


class HybridPlanTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # Event construction must not even construct a CP model.
        for target in ("CpModel", "CpSolver"):
            self.stack.enter_context(patch("src.smt_fullfab.optimizer.cp_model." + target,
                                           side_effect=AssertionError("CP forbidden in hybrid synthetic tests")))
        self.config = configuration(constructor_seconds=0.25)

    def event(self, source, **kwargs):
        result = solve_hybrid_plan(source, mode=EVENT, config=self.config, **kwargs)
        self.assertEqual(result["solver_status"], "FEASIBLE_HEURISTIC", result)
        self.assertEqual(result["cp_sat"]["status"], "NOT_RUN_BY_POLICY")
        self.assertEqual(result["solver_calls"], 0)
        self.assertEqual(result["solver_requested_seconds"], 0)
        self.assertEqual(result["solve_wall_seconds"], 0)
        self.assertTrue(result["nominal_audit"]["valid"])
        self.assertTrue(validate_nominal_plan(source, result["plan"])["valid"])
        self.assertIsNone(result["best_bound"])
        self.assertGreater(result["classical_construction_wall_seconds"], 0)
        return result

    def test_cross_family_batch_future_binding_and_all_machine_scope(self):
        source = problem([machine(1), machine(2), machine(3, "G"), machine(913, "idle")], [
            operation("a", eligible_machines=[1, 2], transport_seconds=2),
            operation("waiting", mid=3, family="G", batch_min=2, batch_max=2),
            operation("later", mid=3, family="G", lot_id="a", step=2,
                      predecessor_ids=["a"], batch_min=2, batch_max=2),
            operation("back", eligible_machines=[1, 2], lot_id="a", step=3,
                      predecessor_ids=["later"], same_machine_as="a"),
        ])
        before = deepcopy(source)
        result = self.event(source, plan_version="hybrid-test")
        self.assertEqual(before, source)
        self.assertEqual(result["plan"]["scope"], [1, 2, 3, 913])
        tasks = {oid: task for task in result["tasks"] for oid in task["operation_ids"]}
        self.assertEqual(set(tasks), {"a", "waiting", "later", "back"})
        self.assertGreaterEqual(tasks["later"]["start"], tasks["a"]["end"])
        self.assertGreaterEqual(tasks["back"]["start"], tasks["later"]["end"])
        self.assertEqual(tasks["a"]["machine"], tasks["back"]["machine"])
        self.assertEqual(tasks["waiting"]["id"], tasks["later"]["id"])
        self.assertEqual(result["hybrid_configuration"]["event_total_slots_per_machine"], 8)

    def test_setup_minrun_and_known_down_window_survive_wrapper(self):
        source = problem([machine(1, current_setup="A", min_left=2, min_setup="A",
                                  unavailable_intervals=[[7, 12]])], [
            operation("a1", setup="A"), operation("a2", setup="A"),
            operation("b", setup="B", priority=100),
        ], setup_transitions={"": {"A": 2, "B": 3}, "A": {"B": 4}}, min_runs={"A": 2})
        tasks = self.event(source)["tasks"]
        self.assertEqual({tasks[0]["operation_ids"][0], tasks[1]["operation_ids"][0]}, {"a1", "a2"})
        self.assertEqual(tasks[1]["start"], 12)
        self.assertEqual(tasks[1]["setup_seconds"], 2)
        self.assertEqual(tasks[2]["setup_seconds"], 4)

    def test_cascading_active_slots_and_fractional_epoch(self):
        epoch = 1603.1013031725258
        source = problem([machine(1, available_at=epoch, cascading=True,
                                  processing_until=[epoch+10, epoch+20])], [
            operation("a", release_time=epoch, processing_seconds=10, occupation_seconds=3),
            operation("b", release_time=epoch, processing_seconds=10, occupation_seconds=3),
            operation("c", release_time=epoch, processing_seconds=10, occupation_seconds=3),
        ])
        source.update(time=epoch, horizon_end=epoch+100)
        tasks = self.event(source)["tasks"]
        self.assertGreaterEqual(tasks[0]["start"], epoch+10)
        self.assertGreaterEqual(tasks[1]["start"], epoch+20)
        self.assertGreaterEqual(tasks[2]["start"], tasks[1]["occupied_until"])

    def test_explicit_construction_limit_preserves_unplanned_evidence(self):
        self.config = configuration(constructor_seconds=0.25, max_candidate_evaluations=1)
        source = problem([machine(1)], [operation("a"), operation("b")])
        result = self.event(source)
        self.assertEqual(result["stop_reason"], "construction_budget")
        self.assertLess(result["planned_operations"], result["operation_count"])
        self.assertIn("construction_budget", result["unplanned_operations"].values())
        self.assertEqual(result["budgets"]["max_candidate_evaluations"], 1)

    def test_no_feasible_batch_is_failure_and_does_not_invent_dispatch(self):
        source = problem([machine(1)], [operation("alone", batch_min=2, batch_max=2)])
        result = solve_hybrid_plan(source, mode=EVENT, config=self.config)
        self.assertEqual(result["solver_status"], "NO_PLAN")
        self.assertEqual(result["tasks"], [])
        self.assertIn("alone", result["unplanned_operations"])

    def test_nominal_failure_is_never_replaced_by_another_algorithm(self):
        source = problem([machine(1)], [operation("a")])
        bad = build_incumbent(source, max_wall_seconds=0.25)
        bad["nominal_audit"] = {"valid": False, "errors": ["injected arithmetic violation"]}
        with patch("src.smt_fullfab.hybrid.build_incumbent", return_value=bad), \
             patch("src.smt_fullfab.hybrid.solve_decomposed_plan") as other:
            result = solve_hybrid_plan(source, mode=EVENT, config=self.config)
        self.assertEqual(result["solver_status"], "INVALID_NOMINAL_PLAN")
        self.assertEqual(result["nominal_audit"]["errors"], ["injected arithmetic violation"])
        other.assert_not_called()

    def test_periodic_failure_and_exception_have_no_event_fallback(self):
        source = problem([machine(1)], [operation("a")])
        failed = {"solver_status": "BUDGET_TOO_SMALL", "family_solves": [], "plan": None}
        with patch("src.smt_fullfab.hybrid.solve_decomposed_plan", return_value=failed), \
             patch("src.smt_fullfab.hybrid.build_incumbent") as other:
            result = solve_hybrid_plan(source, mode=PERIODIC, config=self.config, time_limit_seconds=2)
            self.assertEqual(result["solver_status"], "BUDGET_TOO_SMALL")
            other.assert_not_called()
        with patch("src.smt_fullfab.hybrid.solve_decomposed_plan", side_effect=AssertionError("nominal failed")), \
             patch("src.smt_fullfab.hybrid.build_incumbent") as other:
            with self.assertRaisesRegex(AssertionError, "nominal failed"):
                solve_hybrid_plan(source, mode=PERIODIC, config=self.config, time_limit_seconds=2)
            other.assert_not_called()

    def test_explicit_cp_request_contract(self):
        source = problem([machine(1)], [operation("a")])
        with self.assertRaisesRegex(ValueError, "exactly zero"):
            solve_hybrid_plan(source, mode=EVENT, config=self.config, time_limit_seconds=2)
        with self.assertRaisesRegex(ValueError, "registered cap"):
            solve_hybrid_plan(source, mode=PERIODIC, config=self.config, time_limit_seconds=3)


class HybridScheduleTests(unittest.TestCase):
    def test_event_commits_cannot_postpone_absolute_periodic_deadline(self):
        schedule = HybridSchedule(configuration())
        self.assertEqual(schedule.request(0, 60), (PERIODIC, 2))
        self.assertEqual(schedule.snapshot()["next_full_at"], 0)  # solving/reserving is not committing
        schedule.committed(0, PERIODIC)
        for now in (1, 100, 1039.2, 1799, 1799.999):
            self.assertEqual(schedule.request(now, 0), (EVENT, 0))
            schedule.committed(now, EVENT)
            self.assertEqual(schedule.advance_until(now, 3600), 1800)
        self.assertEqual(schedule.request(1800, 58), (PERIODIC, 2))
        schedule.committed(1800, PERIODIC)
        self.assertEqual(schedule.advance_until(1800, 3600), 3600)

    def test_due_period_cannot_fall_back_when_budget_is_exhausted(self):
        schedule = HybridSchedule(configuration())
        schedule.committed(0, PERIODIC)
        state = schedule.snapshot()
        with self.assertRaisesRegex(RuntimeError, "budget exhausted"):
            schedule.request(1800, 0)
        self.assertEqual(schedule.snapshot(), state)
        with self.assertRaisesRegex(ValueError, "due policy"):
            schedule.committed(1800, EVENT)

    def test_roundtrip_requires_identical_planning_and_construction_limits(self):
        cfg = configuration()
        schedule = HybridSchedule(cfg)
        schedule.committed(0, PERIODIC)
        schedule.committed(1730, EVENT)
        restored = HybridSchedule(cfg, state=json.loads(json.dumps(schedule.snapshot())))
        self.assertEqual(restored.request(1800, 0.5), (PERIODIC, 0.5))
        for change in ({"max_slots": 5}, {"lookahead_depth": 3}, {"constructor_seconds": 6},
                       {"max_candidate_evaluations": 250001}, {"period_seconds": 1801},
                       {"solver_seconds": 3}, {"plan_seconds": 7200}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "configuration differs"):
                HybridSchedule(configuration(**change), state=schedule.snapshot())

    def test_checkpoint_cannot_invent_or_move_periodic_clock(self):
        schedule = HybridSchedule(configuration())
        schedule.committed(0, PERIODIC)
        bad = schedule.snapshot()
        bad["next_full_at"] = 3600
        with self.assertRaisesRegex(ValueError, "clock is inconsistent"):
            HybridSchedule(configuration(), state=bad)
        with self.assertRaisesRegex(ValueError, "budget"):
            schedule.request(1, -1)


class SyntheticEnvironment:
    """Tiny runner-control stub; never invokes a factory or physical simulator."""
    instances = []
    fail_commit = False

    def __init__(self, *, seed, window_seconds, trace_path):
        self.seed, self.horizon, self.t = seed, window_seconds, 0
        self.physical = {1}
        self.finished = False
        self.data_dir = Path("synthetic-no-factory-input")
        self.trace_path = Path(trace_path)
        self.trace_path.write_text('{}\n')
        self.commits, self.advance_targets = [], []
        self.instances.append(self)

    @classmethod
    def from_snapshot(cls, path, *, trace_path):
        saved = json.loads(Path(path).read_text())
        env = cls(seed=saved["seed"], window_seconds=saved["horizon"], trace_path=trace_path)
        env.t = saved["time"]
        return env

    def problem(self, *, plan_seconds, lookahead_depth):
        source = problem([machine(1, available_at=self.t)], [operation("a", release_time=self.t)])
        source.update(time=self.t, horizon_end=self.t+plan_seconds, lookahead_depth=lookahead_depth)
        return source

    def commit_plan(self, plan):
        if self.fail_commit:
            raise ValueError("synthetic commit rejected")
        self.commits.append(deepcopy(plan))

    def advance_plan(self, until):
        self.advance_targets.append(until)
        if until == self.t:
            return {"reason": "synthetic decision"}
        future = [x for x in (100, 1799, 1801, self.horizon) if x > self.t]
        self.t = min(until, min(future))
        self.finished = self.t >= self.horizon
        return {"reason": "synthetic event"}

    def snapshot(self, path):
        Path(path).write_text(json.dumps({"seed": self.seed, "horizon": self.horizon, "time": self.t}))


class HybridRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        SyntheticEnvironment.instances = []
        SyntheticEnvironment.fail_commit = False
        self.stack.enter_context(patch.object(runner, "ROOT", self.root))
        self.stack.enter_context(patch.object(runner, "FullFabEnvironment", SyntheticEnvironment))
        self.stack.enter_context(patch.object(runner, "source_snapshot", return_value={"synthetic_test_only": True}))
        self.audit = self.stack.enter_context(patch.object(runner, "audit_trace", return_value={"valid": True, "metrics": {}}))
        self.stack.enter_context(patch("src.smt_fullfab.optimizer.cp_model.CpSolver",
                                      side_effect=AssertionError("no CP in runner control tests")))
        self.periodic = self.stack.enter_context(patch("src.smt_fullfab.hybrid.solve_decomposed_plan",
                                                       side_effect=self.fake_periodic))

    @staticmethod
    def fake_periodic(source, **kwargs):
        # Test stub for routing/accounting, never performance evidence.
        candidate = build_incumbent(source, max_wall_seconds=0.25, plan_version=kwargs["plan_version"])
        return {**candidate, "solver_status": candidate["status"], "family_solves": [],
                "solver_calls": 0, "solve_wall_seconds": 0,
                "solver_requested_seconds": kwargs["time_limit_seconds"]}

    def run_case(self, name, **kwargs):
        args = dict(arm="A", run_id=name, seconds=3600, solver_method="hybrid",
                    solver_seconds=2, solver_budget_seconds=4, period_seconds=1800,
                    max_slots=4, lookahead_depth=2, constructor_seconds=0.25, max_plans=20)
        args.update(kwargs)
        with redirect_stdout(io.StringIO()):
            result = runner.run(**args)
        return result, self.root/"runs/smt_fullfab_development"/name

    def inherited_checkpoint(self, *, now=1799, consumed=2, include_hybrid=True):
        folder = self.root/"parent"
        folder.mkdir()
        checkpoint = folder/"checkpoint.json"
        checkpoint.write_text(json.dumps({"time": now, "seed": 1701, "horizon": 3600}))
        cfg = configuration(constructor_seconds=0.25)
        schedule = HybridSchedule(cfg)
        schedule.committed(0, PERIODIC)
        schedule.committed(100, EVENT)
        resource = {"arm": "A", "solver_budget_seconds": 4,
                    "cumulative_solver_requested_seconds": consumed,
                    "cumulative_classical_construction_wall_seconds": 7,
                    "cumulative_planner_calls": 5, "cumulative_runner_wall_seconds": 9,
                    "log_bytes_in_earlier_runs": 0,
                    "hybrid_resource_limits": {"runner_wall_seconds": 180, "max_plans": 20,
                                               "max_log_bytes": 536870912},
                    "solver_method": "hybrid" if include_hybrid else "decomposed"}
        if include_hybrid:
            resource["hybrid_state"] = schedule.snapshot()
        (folder/"checkpoint_resources.json").write_text(json.dumps(resource))
        return checkpoint

    def test_runner_hits_1800_despite_events_and_accounts_zero_cp_construction(self):
        result, out = self.run_case("synthetic_complete")
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(result["solver_calls"], 2)
        self.assertEqual(result["classical_event_calls"], 3)
        self.assertEqual(result["planner_calls"], 5)
        self.assertEqual(result["solver_requested_seconds"], 4)
        self.assertEqual([call.args[0]["time"] for call in self.periodic.call_args_list], [0, 1800])
        self.assertGreater(result["classical_construction_wall_seconds"], 0)
        records = [json.loads(s) for s in (out/"resources.jsonl").read_text().splitlines()]
        event_reserves = [r for r in records if r["event"] == "solver_reserve" and r["planner_mode"] == EVENT]
        self.assertEqual(len(event_reserves), 3)
        self.assertTrue(all(r["requested_seconds"] == 0 and r["constructor_seconds_limit"] == 0.25 for r in event_reserves))
        self.assertEqual(self.audit.call_args.kwargs["verify_data_dir"], Path("synthetic-no-factory-input"))

    def test_resume_preserves_spent_cp_and_constructor_costs(self):
        checkpoint = self.inherited_checkpoint()
        result, out = self.run_case("synthetic_resume", snapshot_path=str(checkpoint))
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(result["solver_requested_seconds"], 2)
        saved = json.loads((out/"checkpoint_resources.json").read_text())
        self.assertEqual(saved["cumulative_solver_requested_seconds"], 4)
        self.assertEqual(saved["cumulative_planner_calls"], 5+result["planner_calls"])
        self.assertGreaterEqual(saved["cumulative_runner_wall_seconds"], 9)
        self.assertAlmostEqual(saved["cumulative_classical_construction_wall_seconds"],
                               7+result["classical_construction_wall_seconds"])
        self.assertEqual([call.args[0]["time"] for call in self.periodic.call_args_list], [1800])

    def test_resume_exhaustion_at_period_is_failure_not_event_fallback(self):
        checkpoint = self.inherited_checkpoint(consumed=4)
        result, out = self.run_case("synthetic_exhausted", snapshot_path=str(checkpoint))
        self.assertEqual(result["status"], "failed")
        self.assertIn("budget exhausted", result["failure"])
        self.assertEqual(result["simulation_seconds"], 1800)
        self.assertEqual(result["solver_calls"], 0)
        self.assertEqual(result["classical_event_calls"], 1)
        self.periodic.assert_not_called()
        saved = json.loads((out/"checkpoint_resources.json").read_text())
        self.assertEqual(saved["cumulative_solver_requested_seconds"], 4)
        self.assertEqual(saved["hybrid_state"]["next_full_at"], 1800)

    def test_resume_cannot_reset_plan_wall_or_log_admission_limits(self):
        checkpoint = self.inherited_checkpoint()
        resource_path = checkpoint.with_name("checkpoint_resources.json")
        original = json.loads(resource_path.read_text())
        cases = (("cumulative_planner_calls", 20, "plan count cap"),
                 ("cumulative_runner_wall_seconds", 180, "wall budget"),
                 ("log_bytes_in_earlier_runs", 536870912, "log admission cap"))
        for index, (field, value, error) in enumerate(cases):
            with self.subTest(field=field):
                resource_path.write_text(json.dumps({**original, field: value}))
                result, _ = self.run_case("synthetic_counter_"+str(index), snapshot_path=str(checkpoint))
                self.assertIn(error, result["failure"])
                self.assertEqual(result["planner_calls"], 0)
                self.assertEqual(result["solver_requested_seconds"], 0)
        self.periodic.assert_not_called()

    def test_resume_cannot_raise_registered_resource_limits(self):
        checkpoint = self.inherited_checkpoint()
        for index, change in enumerate(({"wall_seconds": 181}, {"max_plans": 21},
                                        {"max_log_bytes": 536870913}, {"solver_budget_seconds": 5})):
            with self.subTest(change=change):
                result, _ = self.run_case("synthetic_limit_"+str(index), snapshot_path=str(checkpoint), **change)
                self.assertIn("differs" if "solver_budget_seconds" in change else "limits differ", result["failure"])
                self.assertEqual(result["planner_calls"], 0)
        self.periodic.assert_not_called()

    def test_legacy_checkpoint_is_not_assumed_to_have_hybrid_history(self):
        checkpoint = self.inherited_checkpoint(include_hybrid=False)
        result, out = self.run_case("synthetic_legacy", snapshot_path=str(checkpoint))
        self.assertIn("never infer", result["failure"])
        self.periodic.assert_not_called()
        self.assertEqual(result["planner_calls"], 0)
        saved = json.loads((out/"checkpoint_resources.json").read_text())
        self.assertEqual(saved["cumulative_solver_requested_seconds"], 2)
        self.assertIsNone(saved["hybrid_state"])

    def test_changed_constructor_or_planning_limits_are_rejected_on_resume(self):
        checkpoint = self.inherited_checkpoint()
        for index, change in enumerate(({"constructor_seconds": 0.5}, {"max_slots": 5},
                                        {"lookahead_depth": 3}, {"max_candidate_evaluations": 1})):
            with self.subTest(change=change):
                result, _ = self.run_case("synthetic_changed_"+str(index), snapshot_path=str(checkpoint), **change)
                self.assertIn("configuration differs", result["failure"])
                self.assertEqual(result["planner_calls"], 0)
        self.periodic.assert_not_called()

    def test_commit_rejection_does_not_move_clock_or_refund_reserved_cp(self):
        SyntheticEnvironment.fail_commit = True
        result, out = self.run_case("synthetic_reject")
        self.assertIn("commit rejected", result["failure"])
        self.assertEqual(result["plans"], 0)
        saved = json.loads((out/"checkpoint_resources.json").read_text())
        self.assertEqual(saved["cumulative_solver_requested_seconds"], 2)
        self.assertEqual(saved["hybrid_state"]["next_full_at"], 0)
        self.assertIsNone(saved["hybrid_state"]["last_commit_time"])

    def test_constructor_exception_is_recorded_and_not_hidden_by_another_call(self):
        with patch("src.smt_fullfab.hybrid.build_incumbent", side_effect=AssertionError("constructor nominal failed")):
            result, out = self.run_case("synthetic_constructor_exception")
        self.assertEqual(result["status"], "failed")
        self.assertIn("constructor nominal failed", result["failure"])
        self.assertEqual(result["solver_calls"], 1)
        self.assertEqual(result["classical_event_calls"], 1)
        self.assertIsNone(result["classical_construction_wall_seconds"])
        evidence = json.loads((out/"solver_exception_00001.json").read_text())
        self.assertEqual(evidence["requested_seconds_consumed"], 0)
        self.assertEqual(evidence["solve_wall_seconds"], 0)
        self.assertIsNone(evidence["classical_construction_wall_seconds"])
        self.assertEqual(self.periodic.call_count, 1)

    def test_independent_audit_failure_is_still_a_failed_run(self):
        self.audit.return_value = {"valid": False, "metrics": {}, "errors": ["synthetic provenance violation"]}
        result, out = self.run_case("synthetic_audit_failure")
        self.assertEqual(result["failure"], "independent_audit_failed")
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["audit_valid"])
        self.assertEqual(json.loads((out/"audit.json").read_text())["errors"], ["synthetic provenance violation"])


if __name__ == "__main__":
    unittest.main()
