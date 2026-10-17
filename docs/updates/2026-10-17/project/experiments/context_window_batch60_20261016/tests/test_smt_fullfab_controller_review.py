"""Independent regression review: no model or optimizer calls.

Short physical simulations compare original submitted plans to observation-window
projections. They are unit tests, never evaluated B/C scheduling evidence.
"""
import unittest
from unittest.mock import patch

from src.smt_fullfab.controller_audit import _crop
from src.smt_fullfab.environment import FullFabEnvironment
from src.smt_fullfab.runner import crop_plan


class ControllerReviewTests(unittest.TestCase):
    def _compare_physical_execution(self, starts, initial_hold=False):
        original = FullFabEnvironment(seed=1701, window_seconds=80)
        projected = FullFabEnvironment(seed=1701, window_seconds=20)
        lids = original.eligible(9)[:len(starts)]
        self.assertEqual(len(lids), len(starts))
        tasks = []
        for i, (lid, start) in enumerate(zip(lids, starts)):
            lot = original.lots[lid]
            step = lot["step"] + 1
            tasks.append({"id": str(i), "machine": 9, "lot_ids": [lid], "steps": [step],
                          "visits": [lot["visits"][str(step)]], "not_before": start})
        holds = [{"machine": mid, "until": 80, "reason": "fixture explicit wait"} for mid in sorted(original.physical) if mid != 9]
        holds.append({"machine": 9, "until": 80, "reason": "fixture tail wait", "after_task_id": tasks[-1]["id"]})
        if initial_hold:
            holds.append({"machine": 9, "until": 5, "reason": "fixture initial wait"})
        plan = {"version": "test-plan", "created_at": 0, "valid_until": 80, "freeze_until": 0,
                "reason": "synthetic order preservation test", "scope": sorted(original.physical), "tasks": tasks, "holds": holds}
        clipped = crop_plan(plan, projected)
        self.assertEqual(clipped, _crop(plan, projected.horizon, projected.physical))
        original.commit_plan(plan)
        projected.commit_plan(clipped)
        original.advance_plan(until=20)
        projected.advance_plan(until=20)
        def dispatches(env):
            return [{k: e[k] for k in ("time", "machine", "lots", "steps", "visits")}
                    for e in env.trace if e["kind"] == "dispatch" and e["machine"] in env.physical]
        self.assertEqual(dispatches(original), dispatches(projected))
        self.assertEqual(original.t, 20)
        self.assertEqual(projected.t, 20)
        return clipped, dispatches(projected)

    def test_nonmonotone_start_lower_bounds_preserve_head_of_line_wait(self):
        clipped, dispatched = self._compare_physical_execution([40, 5])
        self.assertEqual(clipped["tasks"], [])
        self.assertEqual(dispatched, [])
        self.assertEqual(clipped["unobserved_future_task_ids"], ["0", "1"])

    def test_keep_prefix_and_wait_after_it_without_reassigning_work(self):
        clipped, dispatched = self._compare_physical_execution([0, 40, 5])
        self.assertEqual([task["id"] for task in clipped["tasks"]], ["0"])
        self.assertEqual(len(dispatched), 1)
        hold = next(hold for hold in clipped["holds"] if hold["machine"] == 9)
        self.assertEqual(hold["after_task_id"], "0")
        self.assertEqual(hold["until"], 20)

    def test_collapsed_initial_and_tail_holds_merge_without_new_dispatch(self):
        clipped, dispatched = self._compare_physical_execution([40, 5], initial_hold=True)
        self.assertEqual(dispatched, [])
        holds = [hold for hold in clipped["holds"] if hold["machine"] == 9]
        self.assertEqual(len(holds), 1)
        self.assertEqual(holds[0]["until"], 20)

    def test_stage2_rejects_unapproved_window_before_environment_or_model(self):
        from src.smt_fullfab import controller
        with patch.object(controller, "FullFabEnvironment", side_effect=AssertionError("must reject before environment")), \
             patch.object(controller.BudgetLedger, "research_limit_waiver", return_value=None):
            with self.assertRaisesRegex(ValueError, "approved arm/window"):
                controller.run("B", "unit_test_must_never_be_created", seconds=604800)


if __name__ == "__main__":
    unittest.main()
