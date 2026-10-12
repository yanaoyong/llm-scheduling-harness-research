import copy
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.problem import load_instance, parse_instance, InstanceError
from src.validator import validate_schedule
from src.dispatch import build_schedule, DispatchError


class ProblemValidatorTests(unittest.TestCase):
    def setUp(self):
        self.instance = load_instance(ROOT / "data/smoke.lp")
        self.actions = [
            dict(id="1:1:1:10", machine=1, maintenance=["pm_counter", "pm_time"]),
            dict(id="1:1:2:10", machine=1, maintenance=[]),
            dict(id="2:2:1:10", machine=1, maintenance=["pm_counter", "pm_time"]),
        ]
        # Independent, manually calculated fixture: initial setup [0,2],
        # processing [2,5],[5,7], two PMs+setup 5+2+1, last [15,19].
        self.schedule = dict(operations=[
            dict(id="1:1:1:10", machine=1, start=2, end=5, maintenance=["pm_counter", "pm_time"]),
            dict(id="1:1:2:10", machine=1, start=5, end=7, maintenance=[]),
            dict(id="2:2:1:10", machine=1, start=15, end=19, maintenance=["pm_counter", "pm_time"]),
        ])

    def codes(self, schedule=None, instance=None):
        return {v["code"] for v in validate_schedule(instance or self.instance, schedule or self.schedule)["violations"]}

    def test_hand_calculated_valid_and_objective(self):
        result = validate_schedule(self.instance, self.schedule)
        self.assertTrue(result["feasible"], result)
        self.assertEqual(result["objective"], dict(makespan=19, setup_violations=1))
        self.assertEqual(result["machines"][0]["effective_setups"], ["su_a", "su_a", "su_b"])

    def test_dispatch_matches_hand_calculation(self):
        actual = build_schedule(self.instance, self.actions)
        for expected, produced in zip(self.schedule["operations"], actual["operations"]):
            self.assertEqual(expected, {key: produced[key] for key in expected})
        self.assertTrue(validate_schedule(self.instance, actual)["feasible"])

    def test_wafer_unit_does_not_scale_processing(self):
        self.assertEqual(self.instance["operations"][0]["duration"], 3)
        self.assertEqual(self.instance["operations"][0]["wafers"], 2)

    def test_missing_duplicate_unknown(self):
        s = copy.deepcopy(self.schedule)
        s["operations"].pop()
        s["operations"].append(copy.deepcopy(s["operations"][0]))
        s["operations"].append(dict(id="unknown"))
        self.assertTrue({"missing_operation", "duplicate_operation", "unknown_operation"} <= self.codes(s))

    def test_machine_eligibility(self):
        self.schedule["operations"][0]["machine"] = 99
        self.assertIn("machine_eligibility", self.codes())

    def test_integer_nonnegative_and_duration(self):
        self.schedule["operations"][0]["start"] = -1
        self.assertTrue({"nonnegative_time", "processing_duration"} <= self.codes())
        self.schedule["operations"][0]["start"] = 1.0
        self.assertIn("integer_time", self.codes())
        self.schedule["operations"][0]["start"] = True
        self.assertIn("integer_time", self.codes())

    def test_release_and_initial_setup(self):
        self.schedule["operations"][0].update(start=0, end=3)
        self.assertTrue({"release_setup", "initial_setup_time"} <= self.codes())

    def test_lot_precedence_and_overlap(self):
        self.schedule["operations"][1].update(start=4, end=6)
        self.assertTrue({"lot_precedence", "machine_overlap"} <= self.codes())

    def test_initial_pm_and_unknown_pm(self):
        self.schedule["operations"][0]["maintenance"] = ["not_pm"]
        self.assertTrue({"initial_maintenance", "maintenance_unknown"} <= self.codes())

    def test_pm_minimum_and_maximum(self):
        s = copy.deepcopy(self.schedule)
        s["operations"][1]["maintenance"] = ["pm_counter"]
        self.assertIn("maintenance_min", self.codes(s))
        s = copy.deepcopy(self.schedule)
        s["operations"][2]["maintenance"] = []
        self.assertIn("maintenance_max", self.codes(s))

    def test_time_pm_measures_processing_not_elapsed_time(self):
        self.schedule["operations"][1].update(start=500, end=502)
        self.schedule["operations"][2].update(start=510, end=514)
        result = validate_schedule(self.instance, self.schedule)
        self.assertTrue(result["feasible"], result)

    def test_transition_sums_multiple_pm_and_setup(self):
        self.schedule["operations"][2].update(start=14, end=18)
        self.assertIn("machine_transition_time", self.codes())

    def test_last_pm_segment_exempt_from_minimum(self):
        self.assertTrue(validate_schedule(self.instance, self.schedule)["feasible"])
        segments = validate_schedule(self.instance, self.schedule)["machines"][0]["pm_segments"]
        self.assertTrue(any(s["event"] == "pm_counter" and s["load"] == 2 and s["final"] for s in segments))

    def test_metadata_is_not_trusted(self):
        self.schedule["objective"] = dict(makespan=0, setup_violations=0)
        self.schedule["operations"][2]["maintenance_duration"] = 0
        self.assertEqual(validate_schedule(self.instance, self.schedule)["objective"]["makespan"], 19)

    def test_dispatch_never_repairs_agent_decisions(self):
        cases = []
        a = copy.deepcopy(self.actions); a[0]["maintenance"] = []; cases.append((a, "initial_maintenance"))
        a = copy.deepcopy(self.actions); a[0], a[1] = a[1], a[0]; cases.append((a, "not_ready"))
        a = copy.deepcopy(self.actions); a[2]["maintenance"] = []; cases.append((a, "maintenance_max"))
        a = copy.deepcopy(self.actions); a[1]["maintenance"] = ["pm_counter"]; cases.append((a, "maintenance_too_early"))
        a = copy.deepcopy(self.actions); a[0]["machine"] = 8; cases.append((a, "invalid_machine"))
        a = copy.deepcopy(self.actions); a.append(a[0]); cases.append((a, "duplicate_operation"))
        cases.append((self.actions[:1], "incomplete"))
        for actions, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(DispatchError) as ctx:
                    build_schedule(self.instance, actions)
                self.assertEqual(ctx.exception.feedback["code"], code)

    def test_public_corpus_parses_and_identity_preserves_product(self):
        paths = sorted((ROOT / "vendor/FJSP-SMT2020/PADL-2023/instances").glob("*.lp"))
        self.assertGreaterEqual(len(paths), 11)
        for path in paths:
            instance = load_instance(path)
            self.assertEqual(len(instance["operations"]), len({o["id"] for o in instance["operations"]}))
        small = load_instance(paths[0])
        self.assertEqual(len(small["operations"]), 10)
        self.assertIn("1:3:16:10", {o["id"] for o in small["operations"]})
        self.assertIn("1:4:16:10", {o["id"] for o in small["operations"]})

    def test_unsupported_fact_and_projection_rejected(self):
        with self.assertRaises(InstanceError):
            parse_instance("x(1).")
        text = (ROOT / "data/smoke.lp").read_text().replace("wip(2,2,1,10,2,1,100)", "wip(1,2,1,10,3,1,100)")
        with self.assertRaises(InstanceError):
            parse_instance(text)

    def test_source_singleton_initial_setup_quirk(self):
        # Source does not force setup after the route predecessor. A machine
        # singleton that is not the lot's first operation lacks initial setup
        # lower bound; preserve that behavior rather than strengthen the model.
        text = """
        wip(1,1,1,10,1,0,100).
        product(1,1,a,g,1,wafer,0,0,0).
        product(1,2,a,h,1,wafer,0,0,su).
        tool(a,g,1,0,0,0). tool(a,h,1,0,0,0).
        pm(pmg,g,counter_based,10,1,0). pm(pmh,h,counter_based,10,1,0).
        setup_change(h,su,10,1).
        """
        instance = parse_instance(text)
        schedule = dict(operations=[
            dict(id="1:1:1:10", machine=1, start=0, end=1, maintenance=["pmg"]),
            dict(id="1:1:2:10", machine=1, start=1, end=2, maintenance=["pmh"]),
        ])
        self.assertTrue(validate_schedule(instance, schedule)["feasible"])
        actions = [{"id": r["id"], "machine": r["machine"], "maintenance": r["maintenance"]}
                   for r in schedule["operations"]]
        produced = build_schedule(instance, actions)
        self.assertEqual([r["start"] for r in produced["operations"]], [0, 1])


if __name__ == "__main__":
    unittest.main()
