"""Keep classical and model-requested construction costs distinct in status."""
import unittest
from src.smt_fullfab.status import reported_compute_resources


class ComputeCostTests(unittest.TestCase):
    def test_classical_construction_is_preserved_without_fabricating_tool_count(self):
        r=reported_compute_resources({'classical_construction_wall_seconds':266.975,
            'planner_wall_seconds':320.148, 'planner_calls':211,
            'classical_event_calls':205, 'solver_calls':6,
            'actual_cp_solve_seconds':11.618})
        self.assertEqual(r['classical_construction_wall_seconds'],266.975)
        self.assertEqual(r['planner_wall_seconds'],320.148)
        self.assertEqual(r['classical_event_calls'],205)
        self.assertEqual(r['solver_calls'],6)
        self.assertIsNone(r['constructor_calls'])
        self.assertIsNone(r['constructor_active_seconds'])

    def test_separately_recorded_tool_costs_stay_separate(self):
        r=reported_compute_resources({'constructor_calls':46,
            'constructor_requested_seconds':230,'constructor_active_seconds':58.72,
            'solver_calls':0})
        self.assertEqual(r['constructor_calls'],46)
        self.assertEqual(r['constructor_active_seconds'],58.72)
        self.assertEqual(r['solver_calls'],0)
        self.assertIsNone(r['classical_construction_wall_seconds'])

    def test_missing_measurements_are_unknown_not_zero(self):
        self.assertTrue(all(v is None for v in reported_compute_resources({}).values()))


if __name__=='__main__': unittest.main()
