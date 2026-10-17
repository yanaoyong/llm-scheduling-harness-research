"""Scoped validation must retain raw-proof checks and detect later mutations."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from src.smt_fullfab.harness.contracts import ROOT, HarnessError, digest, encode, strict_json
from src.smt_fullfab.harness.experiment import registration
from src.smt_fullfab.harness.recovery import cohort_recoveries
from tests import test_smt_fullfab_harness_bounded_recovery as fixtures


class RecoveryValidationTests(unittest.TestCase):
    def fixture(self):
        fixture = fixtures.BoundedRecoveryTests(
            methodName="test_T21_cooldown_is_interruptible_and_tamper_is_rejected")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        runtime = fixture.new()
        fixture.invoke(runtime)
        return fixture, runtime

    def test_T23_real_cohort_keeps_all_exact_recovery_identities(self):
        root = ROOT / "artifacts/harness_p5_sol_feedback_release"
        reg = strict_json((root / "experiment.json").read_bytes())
        proof = strict_json((ROOT / "artifacts/harness_astra_B_transition/recovery_carry.json").read_bytes())
        with patch("src.smt_fullfab.harness.experiment.registration", wraps=registration) as checked:
            result = cohort_recoveries(reg)
        rows = [{"run_id": run_id, "attempt_id": aid, "recovery_sha256": digest(row)}
                for run_id, (_, records) in result.items() for aid, row in records.items()]
        self.assertEqual(sorted(rows, key=lambda r:(r["run_id"], r["attempt_id"])), proof["recoveries"])
        # One cohort validation plus the independent guarded-timeout proof.
        selected = [c for c in checked.call_args_list
                    if Path(c.args[0]["experiment_directory"]).resolve() == root]
        self.assertLessEqual(len(selected), 2)
        self.assertEqual(len(result), 21)
        self.assertEqual(len(rows), 5)

    def test_T23_next_invocation_detects_changed_registration(self):
        fixture, runtime = self.fixture()
        self.assertEqual(len(cohort_recoveries(fixture.reg)[runtime.manifest["run_id"]][1]), 1)
        changed = deepcopy(fixture.reg)
        changed["full_B_new_run_limit"] = 2
        (fixture.root / "experiment.json").write_bytes(encode(changed))
        with self.assertRaisesRegex(HarnessError, "registration_changed"):
            cohort_recoveries(fixture.reg)

    def test_T21_next_invocation_checks_changed_persisted_cooldown(self):
        fixture, runtime = self.fixture()
        cohort_recoveries(fixture.reg)
        aid, row = runtime.store.rows("transport_recoveries")[0]
        row["not_before_epoch"] -= 1
        with runtime.store.transaction():
            runtime.store.record("transport_recoveries", aid, row, replace=True)
        with self.assertRaisesRegex(HarnessError, "recovery_cooldown"):
            cohort_recoveries(fixture.reg)

    def test_T23_later_run_is_not_hidden_by_a_cohort_cache(self):
        fixture, first = self.fixture()
        initial = cohort_recoveries(fixture.reg)
        self.assertEqual(sum(len(rows) for _, rows in initial.values()), 1)
        second = fixture.new()
        fixture.cool()
        fixture.invoke(second)
        later = cohort_recoveries(fixture.reg)
        self.assertEqual(sum(len(rows) for _, rows in later.values()), 2)
        self.assertIn(first.manifest["run_id"], later)
        self.assertIn(second.manifest["run_id"], later)

    def test_T23_shared_policy_cannot_validate_another_root(self):
        fixture, runtime = self.fixture()
        changed = deepcopy(runtime.manifest)
        changed["admission"]["experiment_directory"] = str(fixture.root / "another-account")
        with runtime.store.transaction():
            runtime.store.record("manifest", "run", changed, replace=True)
        with self.assertRaisesRegex(HarnessError, "recovery_identity"):
            cohort_recoveries(fixture.reg)


if __name__ == "__main__":
    unittest.main()
