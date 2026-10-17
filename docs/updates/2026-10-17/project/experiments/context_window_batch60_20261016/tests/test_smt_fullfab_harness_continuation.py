"""Continuation controls: real prior evidence is read only; no model requests."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from src.smt_fullfab.harness.contracts import ROOT, HarnessError, default_config, digest, encode, fingerprint, sha_bytes, strict_json
from src.smt_fullfab.harness.experiment import (CAPS, CONTINUATION_CAPS, registration, cumulative_usage,
                                              check_experiment_budget, sealed_prior)
from src.smt_fullfab.harness.evaluation import Evidence, audit_cost, audit_run, seal_evidence
from src.smt_fullfab.harness.runtime import Runtime


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="offline-continuation-"))
        self.prior = ROOT / "artifacts/harness_v1_1_offline/prior_cost_evidence.json"

    def reference(self, path):
        return {"path": str(path), "sha256": sha_bytes(path.read_bytes())}

    def grant_and_registration(self, prior=None):
        grant = {"schema": "harness-user-continuation-20261014-v1", "caps": CONTINUATION_CAPS,
                 "full_B_new_run_limit": 1, "same_twenty_fragments": True, "retain_failures_and_costs": True,
                 "prior_cost_evidence": self.reference(prior or self.prior), "test_only": True}
        grant_path = self.root / "synthetic_grant.json"
        grant_path.write_bytes(encode(grant))
        fp = fingerprint()
        proof = self.root / "synthetic_engineering.json"
        proof.write_bytes(encode({"gates": {g: "pass" for g in ("G0", "G1", "G2", "G3", "G4")}, "fingerprint_sha256": fp["sha256"], "test_only": True}))
        cfg = default_config(seconds=60)
        cfg["limits"].update(CONTINUATION_CAPS["micro"])
        full = default_config()
        value = {"schema": "harness-p5-registration-v2", "caps": CONTINUATION_CAPS, "full_B_new_run_limit": 1,
                 "authorization": self.reference(grant_path), "prior_cost_evidence": grant["prior_cost_evidence"],
                 "fingerprint_sha256": fp["sha256"], "engineering_report": str(proof), "engineering_report_sha256": sha_bytes(proof.read_bytes()),
                 "cases": {"new": {"group": "micro", "config_sha256": digest(cfg), "initial_state_sha256": None},
                           "B3600": {"group": "B3600", "config_sha256": digest(full), "initial_state_sha256": None}},
                 "cli_binary": "/never/invoked", "cli_sha256": "offline-only"}
        (self.root / "experiment.json").write_bytes(encode(value))
        admission = {"experiment_directory": str(self.root), "experiment_sha256": digest(value), "case_id": "new", "group": "micro", "cli_binary": "/never/invoked", "cli_sha256": "offline-only"}
        return value, admission, cfg

    def test_T23_prior_failed_actual_costs_retained_and_new_reservation_not_reset(self):
        value, admission, cfg = self.grant_and_registration()
        prior, starts, ids = sealed_prior(value)
        self.assertEqual((prior["micro"]["attempts"], prior["micro"]["tokens"], starts, len(ids)), (21, 854879, 0, 3))
        self.assertEqual(cumulative_usage(admission), prior)  # no empty new DB required
        runtime = Runtime.start_new(self.root / "new", cfg, experiment_id="offline-carry", mode="model", admission=admission)
        try:
            self.assertEqual(cumulative_usage(admission)["micro"]["attempts"], 21)
            with self.assertRaisesRegex(HarnessError, "experiment_budget"):
                check_experiment_budget(runtime, 6_000_000 - 854879 + 1)
            check_experiment_budget(runtime, 100_000)
            aid = runtime.reserve_attempt("offline reservation, never sent", {})
            self.assertEqual(cumulative_usage(admission)["micro"]["pending"], 1)
            with self.assertRaisesRegex(HarnessError, "experiment_unknown"):
                check_experiment_budget(runtime, 100_000)
            runtime.close()
            runtime = Runtime.resume_run(self.root / "new")
            self.assertEqual(runtime.store.read("attempts", aid)["status"], "not_sent")
            runtime.stop("offline-control-complete")
            sha = seal_evidence(runtime)
            audit_run(runtime.store.path, expected_sha256=sha, output_dir=runtime.store.path / "audit")
            usage = cumulative_usage(admission)
            self.assertEqual(usage["micro"]["attempts"], 21)
            self.assertEqual(usage["micro"]["tokens"], 854879)
            self.assertEqual(usage["micro"]["pending"], 0)
            closure = strict_json((runtime.store.path / "audit_closure.json").read_bytes())
            self.assertEqual(usage["micro"]["wall_seconds"], prior["micro"]["wall_seconds"] + closure["completed_epoch"] - runtime.manifest["created_epoch"])
            self.assertLess(usage["micro"]["wall_seconds"], prior["micro"]["wall_seconds"] + 120)
        finally:
            runtime.close()

    def test_T23_no_summary_discount_duplicate_omission_chain_or_changed_grant(self):
        original = strict_json(self.prior.read_bytes())
        for mode in ("discount", "duplicate", "omission", "wrong_boundary", "wrong_closure"):
            snap = deepcopy(original)
            if mode == "discount": snap["cumulative_usage"]["micro"]["tokens"] -= 1
            elif mode == "duplicate": snap["sealed_runs"].append(snap["sealed_runs"][0])
            elif mode == "omission": snap["sealed_runs"].pop()
            elif mode == "wrong_boundary": snap["sealed_runs"][0]["boundary"]["sha256"] = "0" * 64
            elif mode == "wrong_closure": snap["sealed_runs"][0]["closure"]["sha256"] = "0" * 64
            path = self.root / (mode + ".json")
            path.write_bytes(encode(snap))
            with self.assertRaises(HarnessError, msg=mode): sealed_prior({"prior_cost_evidence": self.reference(path)})
        value, admission, _ = self.grant_and_registration()
        changed = deepcopy(value)
        changed["caps"]["B3600"]["tokens"] += 1
        (self.root / "experiment.json").write_bytes(encode(changed))
        with self.assertRaisesRegex(HarnessError, "experiment_caps"):
            registration({**admission, "experiment_sha256": digest(changed)})
        (self.root / "synthetic_grant.json").write_bytes(b"{}")
        with self.assertRaisesRegex(HarnessError, "carry_evidence"):
            registration({**admission, "experiment_sha256": digest(changed)})
        nested = deepcopy(original)
        old_reg = strict_json(Path(nested["original_registration"]["path"]).read_bytes())
        old_reg["prior_cost_evidence"] = self.reference(self.prior)
        path = self.root / "nested-registration.json"
        path.write_bytes(encode(old_reg))
        nested["original_registration"] = self.reference(path)
        path = self.root / "nested.json"
        path.write_bytes(encode(nested))
        with self.assertRaisesRegex(HarnessError, "carry_chain"):
            sealed_prior({"prior_cost_evidence": self.reference(path)})

    def test_T23_single_B_quota_survives_a_failed_sealed_predecessor(self):
        # A real persistent B account is consumed, stopped and sealed without
        # sending any request. Even its failed physical audit cannot refund it.
        old = self.root / "old"
        old.mkdir()
        fp, cfg = fingerprint(), default_config()
        proof = old / "synthetic_engineering.json"
        proof.write_bytes(encode({"gates": {g: "pass" for g in ("G0", "G1", "G2", "G3", "G4")}, "fingerprint_sha256": fp["sha256"], "test_only": True}))
        reg = {"schema": "harness-p5-registration-v1", "caps": CAPS, "full_B_new_run_limit": 1,
               "fingerprint_sha256": fp["sha256"], "engineering_report": str(proof), "engineering_report_sha256": sha_bytes(proof.read_bytes()),
               "cases": {"B3600": {"group": "B3600", "config_sha256": digest(cfg), "initial_state_sha256": None}},
               "cli_binary": "/never/invoked", "cli_sha256": "offline-only"}
        (old / "experiment.json").write_bytes(encode(reg))
        (old / "micro_gate.json").write_bytes(encode({"pass": True, "test_only": True}))
        adm = {"experiment_directory": str(old), "experiment_sha256": digest(reg), "case_id": "B3600", "group": "B3600", "cli_binary": "/never/invoked", "cli_sha256": "offline-only"}
        runtime = Runtime.start_new(old / "B3600", cfg, experiment_id="offline-B-quota", mode="model", admission=adm)
        try:
            runtime.stop("offline-zero-call-failed-B")
            sha = seal_evidence(runtime)
            report = audit_run(runtime.store.path, expected_sha256=sha, output_dir=runtime.store.path / "audit")
            self.assertFalse(report["valid"])
            row = {"case_id": "B3600", "run_id": runtime.manifest["run_id"], "boundary": self.reference(runtime.store.path / "evidence_manifest.json"),
                   "closure": self.reference(runtime.store.path / "audit_closure.json"), "costs": audit_cost(Evidence(runtime.store.path, sha))}
        finally:
            runtime.close()
        snap = {"original_registration": self.reference(old / "experiment.json"), "sealed_runs": [row], "cumulative_usage": cumulative_usage(adm), "full_B_starts_used": 1}
        path = self.root / "synthetic_prior.json"
        path.write_bytes(encode(snap))
        value, admission, _ = self.grant_and_registration(path)
        self.assertEqual(sealed_prior(value)[1], 1)
        (self.root / "micro_gate.json").write_bytes(encode({"pass": True, "test_only": True}))
        with self.assertRaisesRegex(HarnessError, "full_run_quota"):
            Runtime.start_new(self.root / "illegal-second-B", cfg, experiment_id="offline-rejected-B", mode="model",
                              admission={**admission, "case_id": "B3600", "group": "B3600"})

    def test_T01_twenty_original_tasks_and_full_initial_bytes_cannot_be_substituted(self):
        import zlib
        from src.smt_fullfab.harness.p5 import validate_same_cohort
        snapshot = strict_json(self.prior.read_bytes())
        old_path = Path(snapshot["original_registration"]["path"])
        previous = strict_json(old_path.read_bytes())
        prep = {"cases": deepcopy(previous["cases"]), "prior_cost_evidence": self.reference(self.prior)}
        for case, row in prep["cases"].items():
            if row["group"] == "micro":
                name = case + ".initial.json.z"
                (self.root / name).write_bytes((old_path.parent / name).read_bytes())
        validate_same_cohort(self.root, prep)
        prep["cases"]["micro-01"]["task"] += " changed"
        with self.assertRaisesRegex(HarnessError, "same_cohort"):
            validate_same_cohort(self.root, prep)
        prep["cases"]["micro-01"]["task"] = previous["cases"]["micro-01"]["task"]
        path = self.root / "micro-01.initial.json.z"
        initial = strict_json(zlib.decompress(path.read_bytes()))
        initial["trace"].pop()
        path.write_bytes(zlib.compress(encode(initial)))
        with self.assertRaisesRegex(HarnessError, "same_cohort"):
            validate_same_cohort(self.root, prep)


if __name__ == "__main__": unittest.main()
