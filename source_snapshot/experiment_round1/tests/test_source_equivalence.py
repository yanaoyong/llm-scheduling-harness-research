"""Black-box equivalence tests against the unchanged upstream ASP program.

The production validator has no dependency on this solver. These tests fix all
assignments, maintenance decisions and start times in the original program and
compare its SAT answer and weak-constraint cost with the independent checker.
Only the handmade smoke fixture and development instance01 are used.
"""
import copy
import itertools
import json
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.problem import load_instance, parse_instance
from src.validator import validate_schedule

BINARY = ROOT / "vendor/clingo-dl/build/clingo-dl"
ENCODING = ROOT / "vendor/FJSP-SMT2020/PADL-2023/encoding_msw.lp"
OUTPUT = ROOT / "runs/development/validator_equivalence"


def source_result(instance, schedule, instance_path, case):
    directory = OUTPUT / case
    directory.mkdir(parents=True, exist_ok=True)
    operations = {o["id"]: o for o in instance["operations"]}
    lines = ["% All decisions and start times are fixed; this is a checker test.",
             "#show use_setup/2.", "#show assign_setup/3."]
    for row in schedule["operations"]:
        op = operations[row["id"]]
        identity = ",".join(str(op[k]) for k in ("lot", "product", "step", "priority"))
        term = f"({identity})"
        lines.append(f":- not mach_assign({identity},{op['group']},{row['machine']}).")
        for pm in instance["maintenance"]:
            if pm["group"] == op["group"]:
                atom = f"assign({pm['name']},{op['group']},{term})"
                lines.append(f":- {'not ' if pm['name'] in row['maintenance'] else ''}{atom}.")
        lines.append(f"&diff{{{term} - 0}} <= {row['start']}.")
        lines.append(f"&diff{{0 - {term}}} <= {-row['start']}.")
    fixed = directory / "fixed.lp"
    fixed.write_text("\n".join(lines) + "\n")
    command = [str(BINARY), str(ENCODING), str(instance_path), str(fixed),
               "--const", "flex=1", "--outf=2", "--models=0", "--time-limit=5"]
    raw = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=10)
    (directory / "command.json").write_text(json.dumps({"argv": command, "cwd": str(ROOT)}, indent=2) + "\n")
    (directory / "solver.json").write_text(raw.stdout)
    (directory / "solver.stderr.log").write_text(raw.stderr)
    result = json.loads(raw.stdout)
    witnesses = [w for call in result.get("Call", []) for w in call.get("Witnesses", [])]
    if result.get("Result") not in {"SATISFIABLE", "OPTIMUM FOUND", "UNSATISFIABLE"}:
        raise AssertionError(f"Unexpected source result: {result.get('Result')}; {raw.stderr}")
    validation = validate_schedule(instance, schedule)
    summary = dict(case=case, source_result=result["Result"], source_sat=bool(witnesses),
                   source_cost=witnesses[-1].get("Costs", [0])[0] if witnesses else None,
                   independent_feasible=validation["feasible"], independent_objective=validation["objective"],
                   validator_violations=validation["violations"])
    (directory / "schedule.json").write_text(json.dumps(schedule, indent=2) + "\n")
    (directory / "comparison.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


@unittest.skipUnless(BINARY.is_file(), "Build the upstream native solver to run cross-checks")
class SourceEquivalenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUTPUT.mkdir(parents=True, exist_ok=True)

    def assert_equivalent(self, summary):
        self.assertEqual(summary["source_sat"], summary["independent_feasible"], summary)
        if summary["source_sat"]:
            self.assertEqual(summary["source_cost"], summary["independent_objective"]["setup_violations"], summary)

    def test_all_smoke_topological_orders_and_maintenance_assignments(self):
        path = ROOT / "data/smoke.lp"
        instance = load_instance(path)
        events = [p["name"] for p in instance["maintenance"]]
        ids = [o["id"] for o in instance["operations"]]
        durations = {o["id"]: o["duration"] for o in instance["operations"]}
        orders = [order for order in itertools.permutations(ids) if order.index("1:1:1:10") < order.index("1:1:2:10")]
        summaries = []
        for order_number, order in enumerate(orders):
            for mask in range(1 << (len(order) * len(events))):
                # Ample idle gaps isolate PM/setup semantic checks from timing.
                # The decisions are exhaustively enumerated by this test only;
                # no such enumeration is available to either production Agent.
                schedule = dict(operations=[dict(id=oid, machine=1, start=100 * (i + 1),
                    end=100 * (i + 1) + durations[oid],
                    maintenance=[event for j, event in enumerate(events) if mask & (1 << (i * len(events) + j))])
                    for i, oid in enumerate(order)])
                case = f"exhaustive-order{order_number}-pm{mask:02d}"
                with self.subTest(case=case):
                    summary = source_result(instance, schedule, path, case)
                    summaries.append(summary)
                    self.assert_equivalent(summary)
        (OUTPUT / "exhaustive-summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
        self.assertEqual(len(summaries), 192)
        self.assertGreater(sum(s["source_sat"] for s in summaries), 0)

    def test_time_boundaries_and_idle_intervals(self):
        path = ROOT / "data/smoke.lp"
        instance = load_instance(path)
        base = dict(operations=[
            dict(id="1:1:1:10", machine=1, start=2, end=5, maintenance=["pm_counter", "pm_time"]),
            dict(id="1:1:2:10", machine=1, start=5, end=7, maintenance=[]),
            dict(id="2:2:1:10", machine=1, start=15, end=19, maintenance=["pm_counter", "pm_time"]),
        ])
        cases = [("exact-time-boundaries", base)]
        for index, start in [(0, 1), (1, 4), (2, 14)]:
            schedule = copy.deepcopy(base)
            row = schedule["operations"][index]
            duration = row["end"] - row["start"]
            row.update(start=start, end=start + duration)
            cases.append((f"time-boundary-minus-one-{index}", schedule))
        schedule = copy.deepcopy(base)
        schedule["operations"][1].update(start=500, end=502)
        schedule["operations"][2].update(start=510, end=514)
        cases.append(("idle-does-not-count-as-time-PM", schedule))
        for case, schedule in cases:
            with self.subTest(case=case):
                self.assert_equivalent(source_result(instance, schedule, path, case))

    def test_initial_setup_singleton_source_exception(self):
        text = """
        wip(1,1,1,10,1,0,100).
        product(1,1,a,g,1,wafer,0,0,0).
        product(1,2,a,h,1,wafer,0,0,su).
        tool(a,g,1,0,0,0). tool(a,h,1,0,0,0).
        pm(pmg,g,counter_based,10,1,0). pm(pmh,h,counter_based,10,1,0).
        setup_change(h,su,10,1).
        """
        path = OUTPUT / "singleton-fixture.lp"
        path.write_text(text)
        instance = parse_instance(text)
        schedule = dict(operations=[
            dict(id="1:1:1:10", machine=1, start=0, end=1, maintenance=["pmg"]),
            dict(id="1:1:2:10", machine=1, start=1, end=2, maintenance=["pmh"]),
        ])
        self.assert_equivalent(source_result(instance, schedule, path, "singleton-initial-setup"))

    def test_existing_development_native_witnesses(self):
        # Reuse every real recorded development witness, not only the optimum.
        raw_path = ROOT / "runs/dev_native01.json"
        if not raw_path.exists():
            self.skipTest("No saved development witness history yet")
        try:
            from src.classical import witness_schedule
        except ModuleNotFoundError:
            self.skipTest("Use experiment .venv for clingo witness conversion")
        instance_path = ROOT / "vendor/FJSP-SMT2020/PADL-2023/instances/instance01.lp"
        instance = load_instance(instance_path)
        raw = json.loads(raw_path.read_text())
        witnesses = [w for call in raw.get("Call", []) for w in call.get("Witnesses", [])]
        self.assertGreater(len(witnesses), 0)
        summaries = []
        for index, witness in enumerate(witnesses):
            result = validate_schedule(instance, witness_schedule(witness, instance_path))
            self.assertTrue(result["feasible"], (index, result))
            self.assertEqual(witness.get("Costs", [0])[0], result["objective"]["setup_violations"])
            summaries.append(dict(witness=index, objective=result["objective"], feasible=result["feasible"]))
        (OUTPUT / "development01-witnesses.json").write_text(json.dumps(summaries, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main()
