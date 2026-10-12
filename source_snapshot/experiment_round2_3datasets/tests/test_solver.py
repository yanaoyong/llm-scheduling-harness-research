import itertools
import unittest
from src.fjsp.solver import solve


def small_problem():
    return {"schema_version": "fjsp-1", "instance_id": "hand-check", "machines": [0, 1],
            "jobs": [
                {"id": 0, "operations": [
                    {"id": "j0o0", "job": 0, "index": 0, "alternatives": [{"machine": 0, "duration": 3}, {"machine": 1, "duration": 2}]},
                    {"id": "j0o1", "job": 0, "index": 1, "alternatives": [{"machine": 0, "duration": 2}]}]},
                {"id": 1, "operations": [
                    {"id": "j1o0", "job": 1, "index": 0, "alternatives": [{"machine": 0, "duration": 2}]},
                    {"id": "j1o1", "job": 1, "index": 1, "alternatives": [{"machine": 1, "duration": 3}]}]}]}


class SolverTests(unittest.TestCase):
    def test_hand_lower_bound_attained(self):
        # j1 requires 2+3 = 5 time units. j0: M1 [0,2], M0 [2,4],
        # j1: M0 [0,2], M1 [2,5] attains this universal lower bound.
        from src.fjsp.validator import validate
        p = small_problem()
        r = solve(p, time_limit=2)
        self.assertEqual(r["solver_status"], "OPTIMAL")
        self.assertEqual(r["objective"], 5)
        self.assertEqual(r["best_bound"], 5)
        self.assertTrue(validate(p, r["schedule"])["valid"])

    def test_machine_dependent_duration(self):
        p = small_problem()
        for j in p["jobs"]:
            for op in j["operations"]:
                for alt in op["alternatives"]:
                    if alt["machine"] == 1:
                        alt["duration"] *= 10
        from src.fjsp.validator import validate
        r = solve(p, time_limit=2)
        self.assertTrue(validate(p, r["schedule"])["valid"])
        self.assertGreaterEqual(r["objective"], 32)

    def test_unbounded_or_parallel_budget_rejected(self):
        for kwargs in [{"time_limit": 0}, {"time_limit": float("nan")}, {"workers": 8}, {"seed": -1}]:
            with self.assertRaises(ValueError):
                solve(small_problem(), **kwargs)


if __name__ == "__main__":
    unittest.main()
