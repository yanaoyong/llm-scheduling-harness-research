import copy
import math
import unittest

from src.smt_fullfab.metrics import compute_metrics, weighted_tardy_seconds


def metric_events():
    lots = [
        {"id": "old", "release": -100, "due": -5, "priority": 10, "pieces": 25, "part": "p"},
        {"id": "done", "release": 0, "due": 4, "priority": 20, "pieces": 25, "part": "p"},
        {"id": "new", "release": 6, "due": 8, "priority": 30, "pieces": 25, "part": "q"},
        {"id": "future", "release": 15, "due": 20, "priority": 10, "pieces": 25, "part": "q"}]
    events = [{"kind": "initial", "time": 0, "manifest": {"lots": lots, "machines": [], "routes": {}, "horizon": 10}},
              {"kind": "release", "time": 0, "lot": "old"},
              {"kind": "release", "time": 0, "lot": "done"},
              {"kind": "release", "time": 6, "lot": "new"},
              {"kind": "lot_complete", "time": 7, "lot": "done"},
              {"kind": "terminal", "time": 10}]
    return events


class MetricsTests(unittest.TestCase):
    def test_completed_and_unfinished_both_count(self):
        result = compute_metrics(metric_events(), include_lot_details=True)
        # old 10*1 + completed (7-4)*2 + new (10-8)*3 = 22.
        self.assertEqual(result["weighted_tardy_lot_seconds"], 22)
        self.assertEqual(result["weighted_tardy_seconds_completed_contribution"], 6)
        self.assertEqual(result["weighted_tardy_seconds_unfinished_contribution"], 16)
        self.assertEqual(result["throughput_lots"], 1)
        self.assertEqual(result["initial_window_wip_lots"], 2)
        self.assertEqual(result["released_in_window_lots"], 1)
        self.assertEqual(result["terminal_wip_lots"], 2)
        self.assertTrue(result["lot_conservation_valid"])
        self.assertEqual(result["normalization_population_weight"], 6)
        self.assertEqual(result["exogenous_weighted_exposure_seconds"], 42)
        self.assertEqual(result["window_start_already_tardy_wip_lots"], 1)

    def test_old_overdue_debt_not_recharged(self):
        self.assertEqual(weighted_tardy_seconds(release=-100, due=-20, completion=None,
                         window_start=10, window_end=20, weight=2), 20)

    def test_observation_subwindow_uses_history(self):
        result = compute_metrics(metric_events(), window_start=5, window_end=10)
        self.assertEqual(result["weighted_tardy_lot_seconds"], 5 + 4 + 6)
        self.assertEqual(result["initial_window_wip_lots"], 2)
        self.assertEqual(result["window_start_already_tardy_wip_lots"], 2)

    def test_no_completions_is_not_zero_tardiness(self):
        es = [e for e in metric_events() if e["kind"] != "lot_complete"]
        result = compute_metrics(es)
        self.assertEqual(result["weighted_tardy_lot_seconds"], 28)
        self.assertEqual(result["throughput_lots"], 0)
        self.assertIsNone(result["mean_cycle_seconds_completed"])
        self.assertIsNone(result["completion_groups"]["part"]["p"]["ontime_fraction_completed_only"])

    def test_missing_priority_rejected(self):
        with self.assertRaisesRegex(ValueError, "unmapped priority"):
            compute_metrics(metric_events(), priority_weights={10: 1})

    def test_nonfinite_or_nonpositive_weights_rejected(self):
        for bad in (0, -1, math.nan, math.inf, True):
            with self.assertRaises(ValueError):
                weighted_tardy_seconds(release=0, due=0, completion=None, window_start=0, window_end=10, weight=bad)

    def test_unobserved_horizon_not_extrapolated(self):
        with self.assertRaisesRegex(ValueError, "observed event history"):
            compute_metrics(metric_events(), window_end=11)

    def test_duplicate_completion_rejected(self):
        events = metric_events()
        events.insert(-1, copy.deepcopy(events[-2]))
        with self.assertRaisesRegex(ValueError, "duplicate completion"):
            compute_metrics(events)

    def test_partial_trace_reported_partial(self):
        events = metric_events()[:-1]
        result = compute_metrics(events)
        self.assertEqual(result["window_end"], 7)
        self.assertFalse(result["completed_declared_window"])


if __name__ == "__main__":
    unittest.main()
