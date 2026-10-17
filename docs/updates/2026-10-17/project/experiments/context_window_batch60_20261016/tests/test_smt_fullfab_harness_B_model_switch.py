"""Astra B-only admission must preserve scores, histories, budgets and source."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab.harness.contracts import ROOT, HarnessError, digest, encode, fingerprint, sha_bytes, strict_json
from src.smt_fullfab.harness.B_model_switch import carried_costs, probe_cost, validate_registration
from src.smt_fullfab.harness.experiment import checked_file


class BModelSwitchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="offline-astra-B-switch-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        source = ROOT / "artifacts/harness_astra_B_transition"
        self.reg = strict_json((source / "registration_draft.json").read_bytes())
        oldroot = Path(self.reg["experiment_directory"])
        self.usage = deepcopy(self.reg["carried_usage_at_registration"])
        self.reg["experiment_directory"] = str(self.root)
        self.grant = checked_file(self.reg["authorization"])
        self.grant["experiment_directory"] = str(self.root)
        self.gate = checked_file(self.reg["entry_gate"])
        self.cfg = strict_json((oldroot / "B3600.config.json").read_bytes())
        # This fixture exercises the already frozen first Astra registration.
        # Later authorized network controls must not become that old source.
        frozen = strict_json((oldroot / "experiment.json").read_bytes())
        self.fp = checked_file({"path": frozen["engineering_report"], "sha256": frozen["engineering_report_sha256"]})["fingerprint"]
        proof = self.root / "test-only-proof.json"
        proof.write_bytes(encode({"all_pass": True, "source_unchanged": True, "remote_model_calls": 0, "fingerprint_sha256": self.fp["sha256"]}))
        self.report = {"fingerprint": self.fp, "fingerprint_sha256": self.fp["sha256"],
                       "gates": {g: "pass" for g in ("G0", "G1", "G2", "G3", "G4")}, "test_evidence": self.ref(proof)}
        self.reg["fingerprint_sha256"] = self.fp["sha256"]
        self.sync()

    def ref(self, path):
        return {"path": str(path), "sha256": sha_bytes(path.read_bytes())}

    def sync(self):
        (self.root / "authorization.json").write_bytes(encode(self.grant))
        self.reg["authorization"] = self.ref(self.root / "authorization.json")
        self.gate["authorization"] = self.reg["authorization"]
        (self.root / "micro_gate.json").write_bytes(encode(self.gate))
        self.reg["entry_gate"] = self.ref(self.root / "micro_gate.json")
        (self.root / "B3600.config.json").write_bytes(encode(self.cfg))
        (self.root / "engineering.json").write_bytes(encode(self.report))
        self.reg["engineering_report"] = str(self.root / "engineering.json")
        self.reg["engineering_report_sha256"] = sha_bytes((self.root / "engineering.json").read_bytes())

    def validate(self):
        with patch("src.smt_fullfab.harness.B_model_switch.carried_costs", return_value=(self.usage, 1, {"closed-prior-B"})):
            return validate_registration(self.reg, self.root)

    def test_T20_only_requested_Astra_B_is_admitted(self):
        self.assertEqual(self.validate(), self.reg)
        self.reg["model"]["name"] = "gpt-6.1-sol"
        with self.assertRaisesRegex(HarnessError, "B_registration"):
            self.validate()

    def test_T20_model_switch_cannot_change_seed_physics_or_limits(self):
        for key, value in (("seed", 99), ("window_seconds", 7200), ("fallback", "implicit")):
            with self.subTest(key=key):
                original = self.cfg[key]
                self.cfg[key] = value
                self.reg["cases"]["B3600"]["config_sha256"] = digest(self.cfg)
                self.sync()
                with self.assertRaises(HarnessError): self.validate()
                self.cfg[key] = original
        self.cfg["limits"]["wall_seconds"] += 1
        self.reg["cases"]["B3600"]["config_sha256"] = digest(self.cfg)
        self.sync()
        with self.assertRaisesRegex(HarnessError, "B_case"): self.validate()

    def test_T22_no_omitted_fragment_or_cross_model_relabeling(self):
        original = deepcopy(self.gate)
        self.gate["cases"].pop("micro-20")
        self.sync()
        with self.assertRaisesRegex(HarnessError, "B_entry"): self.validate()
        self.gate = original
        self.gate["prior_micro_scores_are_target_model_scores"] = True
        self.sync()
        with self.assertRaisesRegex(HarnessError, "B_entry"): self.validate()

    def test_T23_only_one_additional_B_without_quota_reset(self):
        for quota in (1, 3):
            with self.subTest(quota=quota):
                self.reg["full_B_new_run_limit"] = self.grant["full_B_new_run_limit"] = quota
                self.sync()
                with self.assertRaisesRegex(HarnessError, "B_budget"): self.validate()

    def test_T23_exception_counter_and_cost_carry_cannot_be_reset(self):
        self.grant["prior_exception_count"] = 0
        self.sync()
        with self.assertRaisesRegex(HarnessError, "B_budget"): self.validate()
        self.grant["prior_exception_count"] = 12
        self.reg["carried_usage_at_registration"]["combined"]["tokens"] = 0
        self.sync()
        with self.assertRaisesRegex(HarnessError, "B_budget"): self.validate()

    def test_T20_physical_or_prompt_source_change_is_rejected(self):
        fp = self.report["fingerprint"]
        fp["files"]["src/smt_fullfab/harness/transport.py"] = "0" * 64
        fp["sha256"] = digest({k:v for k,v in fp.items() if k != "sha256"})
        self.reg["fingerprint_sha256"] = fp["sha256"]
        self.sync()
        with self.assertRaisesRegex(HarnessError, "B_source"): self.validate()

    def test_T23_probe_and_all_80_prior_runs_are_charged_once(self):
        usage, starts, identities = carried_costs(self.reg)
        self.assertEqual(usage, self.usage)
        self.assertEqual((starts, len(identities)), (1, 81))
        self.assertEqual((usage["combined"]["attempts"], usage["combined"]["tokens"], usage["combined"]["unknown_usage"]), (335, 11572814, 23))

    def test_T23_probe_success_requires_raw_usage_and_terminal_evidence(self):
        reference = self.reg["successful_probe"]
        original = checked_file(reference)
        bad = {**original, "channel_success": False}
        def read(ref): return bad if ref == reference else checked_file(ref)
        with patch("src.smt_fullfab.harness.experiment.checked_file", side_effect=read):
            with self.assertRaisesRegex(HarnessError, "B_probe"): probe_cost(reference)


if __name__ == "__main__":
    unittest.main()
