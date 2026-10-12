import copy
import unittest

from src.smt_fullfab.audit import audit_plan_sources, audit_trace, audit_opportunity_coverage, _combinations


def trace_fixture():
    step = {"step": 1, "family": "G", "name": "process", "batch_min": 1, "batch_max": 1,
            "batching": False, "processing": {"type": "constant", "c": 10},
            "cadence": {"type": "constant", "c": 10}, "setup": "", "setup_time": None,
            "sampling_percent": 100, "rework_percent": 0, "rework_step": "", "dedicate_for": None,
            "transport": {"type": "constant", "c": 0}}
    lot = {"id": "x", "name": "x", "part": "p", "route": "r", "priority": 10,
           "pieces": 25, "release": -100, "due": 5, "step": 0, "initial": True}
    manifest = {"version": "smt-adapter-v2", "seed": 701, "horizon": 20,
                "controlled_machine_ids": [0], "initial_wip": 1, "physical_machines": 1,
                "virtual_delay_resources": 0, "routes": {"r": [step]},
                "machines": [{"id": 0, "family": "G", "group": "production", "load": 0,
                              "unload": 0, "cascading": False}], "lots": [lot], "setups": [],
                "min_runs": {}, "calendars": {}, "piece_pm": {}, "data_hashes": {}}
    task = {"id": "t1", "machine": 0, "lot_ids": ["x"], "steps": [1], "visits": [1], "not_before": 0}
    plan = {"version": "v1", "created_at": 0, "valid_until": 20, "freeze_until": 0,
            "reason": "fixture", "scope": [0], "tasks": [task], "holds": []}
    es = []
    def emit(t, kind, **kw):
        es.append({"seq": len(es), "time": t, "kind": kind, **kw})
    emit(0, "initial", manifest=manifest)
    emit(0, "release", lot="x")
    emit(0, "ready", lot="x", step=1, visit=1)
    emit(0, "plan_committed", plan=plan)
    emit(0, "dispatch", machine=0, lots=["x"], steps=[1], visits=[1], job=0, owner="plan",
         plan_version="v1", plan_task_id="t1", setup_before="", setup_after="", setup_seconds=0,
         processing_seconds=10, cadence_seconds=10, transport_seconds=0, piece_pm=[],
         machine_ready=10, process_end=10, lot_end=10, min_runs_left=0)
    emit(0, "time_advance", to=10)
    emit(10, "operation_complete", job=0, lot="x", step=1)
    emit(10, "lot_complete", lot="x")
    emit(10, "time_advance", to=20)
    emit(20, "terminal", lot_statuses={"x": "done"}, metrics={})
    return es


def renumber(events):
    for i, e in enumerate(events):
        e["seq"] = i
    return events


class AuditTests(unittest.TestCase):
    def test_end_to_end_independent_physical_replay(self):
        result = audit_trace(trace_fixture())
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["metrics"]["weighted_tardy_lot_seconds"], 5)
        self.assertTrue(result["plan_source_audit"]["actual_dispatch_provenance_complete"])
        self.assertFalse(result["official_simulator_equivalence_certified"])
        self.assertTrue(result["plan_source_audit"]["absence_of_unreported_legal_demand_certified"])
        self.assertEqual(result["opportunity_audit"]["family_opportunities"]["G"]["singleton_immediate_dispatches"], 1)

    def test_untraced_production_fallback_is_rejected(self):
        es = trace_fixture()
        es[4]["owner"] = "environment"
        self.assertFalse(audit_trace(es)["valid"])

    def test_success_flag_cannot_authenticate_missing_plan(self):
        es = trace_fixture()
        es[4]["plan_version"] = "uncommitted"
        es[-1]["success"] = True
        self.assertFalse(audit_trace(es)["valid"])

    def test_exact_steps_and_visits_are_checked(self):
        for key in ("steps", "visits"):
            es = trace_fixture()
            es[4][key] = [2]
            self.assertFalse(audit_plan_sources(es)["valid"])

    def test_start_condition_is_checked(self):
        es = trace_fixture()
        es[3]["plan"]["tasks"][0]["not_before"] = 1
        self.assertFalse(audit_plan_sources(es)["valid"])

    def test_latest_start_is_checked(self):
        es = trace_fixture()
        es[4]["time"] = 1
        es[3]["plan"]["tasks"][0]["latest_start"] = 0
        self.assertFalse(audit_plan_sources(es)["valid"])

    def test_duplicate_task_and_nonfull_scope_rejected(self):
        es = trace_fixture()
        es[3]["plan"]["tasks"] *= 2
        self.assertFalse(audit_plan_sources(es)["valid"])
        es = trace_fixture()
        es[3]["plan"]["scope"] = []
        self.assertFalse(audit_plan_sources(es)["valid"])

    def test_frozen_task_cannot_disappear_on_revision(self):
        es = trace_fixture()
        es[3]["plan"]["freeze_until"] = 5
        new = copy.deepcopy(es[3])
        new["plan"].update(version="v2", tasks=[])
        es.insert(4, new)
        result = audit_plan_sources(renumber(es))
        self.assertFalse(result["valid"])
        self.assertTrue(any("frozen task" in e for e in result["errors"]))

    def test_exact_frozen_task_can_retain_past_not_before(self):
        es = trace_fixture()[:4]
        es[3]["plan"]["freeze_until"] = 5
        revision = copy.deepcopy(es[3])
        revision["time"] = 2
        revision["plan"].update(version="v2", created_at=2, freeze_until=5)
        es.append(revision)
        result = audit_plan_sources(renumber(es))
        self.assertTrue(result["valid"], result["errors"])
        es[3]["plan"]["freeze_until"] = 1
        self.assertFalse(audit_plan_sources(es)["valid"])

    def test_physical_violation_detected_despite_exact_plan_source(self):
        es = trace_fixture()
        es[4]["processing_seconds"] = 100
        self.assertTrue(audit_plan_sources(es)["valid"])
        result = audit_trace(es)
        self.assertFalse(result["valid"])
        self.assertTrue(any("processing sample" in e for e in result["errors"]))

    def test_missing_terminal_is_not_certified(self):
        self.assertFalse(audit_trace(trace_fixture()[:-1])["valid"])

    def test_snapshot_with_complete_prefix_can_be_replayed(self):
        es = trace_fixture()
        es.insert(6, {"kind": "snapshot_loaded", "time": 2, "prefix_event_count": 6, "snapshot_sha256": "a" * 64})
        result = audit_trace(renumber(es))
        self.assertTrue(result["valid"], result["errors"])

    def test_snapshot_without_prefix_is_rejected(self):
        es = trace_fixture()
        es.insert(6, {"kind": "snapshot_loaded", "time": 2, "prefix_event_count": 100, "snapshot_sha256": "a" * 64})
        result = audit_trace(renumber(es))
        self.assertFalse(result["valid"])

    def test_combination_count_excludes_insufficient_batches(self):
        candidates = [{"batch_key": ["p", 1], "batch_min": 5, "batch_max": 6} for _ in range(5)]
        candidates += [{"batch_key": ["q", 1], "batch_min": 5, "batch_max": 6} for _ in range(4)]
        self.assertEqual(_combinations({"candidates": candidates})[0], 1)

    def _waiting_trace(self, *, hold=None, pending=False):
        es = trace_fixture()[:4]
        es[3]["plan"]["tasks"] = es[3]["plan"]["tasks"] if pending else []
        if hold is not None:
            es[3]["plan"]["holds"] = [{"machine": 0, "until": hold, "reason": "explicit wait"}]
        es.extend([{"kind": "time_advance", "time": 0, "to": 20},
                   {"kind": "terminal", "time": 20, "lot_statuses": {"x": "waiting"}, "metrics": {}}])
        return renumber(es)

    def test_singleton_legal_demand_cannot_be_silently_skipped(self):
        result = audit_trace(self._waiting_trace())
        self.assertFalse(result["valid"])
        self.assertTrue(any("unplanned legal demand" in error for error in result["errors"]))

    def test_explicit_hold_is_intentional_wait_not_uncovered_demand(self):
        result = audit_trace(self._waiting_trace(hold=20))
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["metrics"]["terminal_wip_lots"], 1)
        self.assertEqual(result["opportunity_audit"]["ready_wait_without_current_plan_lot_seconds"], 20)

    def test_clock_jump_cannot_hide_expired_hold(self):
        result = audit_opportunity_coverage(self._waiting_trace(hold=10))
        self.assertFalse(result["valid"])
        self.assertTrue(any("at 10" in error for error in result["errors"]))

    def test_executable_plan_task_cannot_be_left_unexecuted(self):
        result = audit_opportunity_coverage(self._waiting_trace(pending=True))
        self.assertFalse(result["valid"])
        self.assertTrue(any("executable submitted task" in error for error in result["errors"]))

    def test_clock_changes_require_explicit_advance_evidence(self):
        es = renumber([e for e in trace_fixture() if e["kind"] != "time_advance"])
        result = audit_trace(es)
        self.assertFalse(result["valid"])
        self.assertTrue(any("without declared time_advance" in error for error in result["errors"]))

    def test_forged_reported_coverage_gap_is_rejected(self):
        es = self._waiting_trace(hold=20)
        es.insert(3, {"kind": "coverage_gap", "time": 0, "machines": [], "plan_version": None})
        result = audit_opportunity_coverage(renumber(es))
        self.assertFalse(result["valid"])
        self.assertTrue(any("reported coverage gap differs" in error for error in result["errors"]))

    def test_conditional_hold_does_not_block_submitted_task(self):
        es = trace_fixture()
        es[3]["plan"]["holds"] = [{"machine": 0, "until": 20, "reason": "after sequence", "after_task_id": "t1"}]
        result = audit_trace(es)
        self.assertTrue(result["valid"], result["errors"])

    def test_conditional_hold_cannot_hide_unexecuted_task(self):
        es = self._waiting_trace(pending=True)
        es[3]["plan"]["holds"] = [{"machine": 0, "until": 20, "reason": "after sequence", "after_task_id": "t1"}]
        result = audit_trace(es)
        self.assertFalse(result["valid"])
        self.assertTrue(any("executable submitted task" in e for e in result["errors"]))

    def test_unstarted_unknown_lot_cannot_mask_demand(self):
        es = self._waiting_trace(pending=True)
        es[3]["plan"]["tasks"][0]["lot_ids"] = ["invented"]
        self.assertFalse(audit_plan_sources(es)["valid"])


if __name__ == "__main__":
    unittest.main()
