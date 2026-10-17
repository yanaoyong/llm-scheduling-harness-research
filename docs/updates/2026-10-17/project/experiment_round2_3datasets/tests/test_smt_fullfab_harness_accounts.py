"""Shared-budget, field provenance and preregistered fragment controls, no model."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest

from src.smt_fullfab.harness.contracts import ROOT, HarnessError, default_config, digest, encode, fingerprint, sha_bytes
from src.smt_fullfab.harness.experiment import CAPS, cumulative_usage, check_experiment_budget, experiment_lock
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.evaluation import audit_run, seal_evidence, Evidence, audit_provenance
from src.smt_fullfab.harness.legacy import load_fragment, public_delta
from tests.test_smt_fullfab_harness import wait_delta, propose, apply


class AccountTests(unittest.TestCase):
    def test_T01_snapshot_marker_preserves_original_gap_trigger(self):
        fixture = load_fragment(ROOT / "runs/smt_fullfab_stage2/B_1701_1h_delta_v14__candidate_paths_001/plan_00001")
        trace = fixture["initial"]["trace"]
        self.assertEqual(trace[-1]["kind"], "snapshot_loaded")
        trigger = fixture["initial"]["state"]["last_stop"]
        self.assertEqual(trigger["reason"], "uncovered_demand")
        self.assertEqual(trigger["machines"], trace[-2]["machines"])
        folder = Path(tempfile.mkdtemp(prefix="offline-first-fragment-"))
        cfg = default_config(seconds=3600-fixture["initial"]["state"]["t"])
        runtime = Runtime.start_new(folder / "run", cfg, experiment_id="offline-restored-trigger", initial=fixture["initial"])
        try:
            self.assertEqual(runtime.context()["trigger"], trigger)
            result = propose(runtime, public_delta(fixture))
            candidate = runtime.store.read("candidates", result["candidate_ref"])
            self.assertEqual(candidate["compiled"]["plan"], fixture["old_compiled"]["plan"])
            apply(runtime, result["candidate_ref"])
            runtime.advance()
            runtime.stop("registered_fragment_accepted")
            sha = seal_evidence(runtime)
            report = audit_run(folder / "run", expected_sha256=sha, scope="accepted_fragment")
            self.assertTrue(report["valid"], report["errors"])
        finally:
            runtime.close()

    def test_T12_wire_contract_exposes_change_sets_and_projection(self):
        from src.smt_fullfab.harness.transport import response_schema
        schema = response_schema()
        actions = schema["properties"]["action"]["anyOf"]
        contexts = [v for v in actions if v["properties"]["tool"]["enum"] == ["get_context"]]
        self.assertTrue(any("since_context_ref" in v["properties"] for v in contexts))
        read = next(v for v in actions if v["properties"]["tool"]["enum"] == ["read_entities"])
        variants = read["properties"]["queries"]["items"]["anyOf"]
        self.assertTrue(any({"fields", "ids"} <= set(v["properties"]) for v in variants))
        self.assertTrue(any({"fields", "cursor", "count"} <= set(v["properties"]) for v in variants))

    def test_T23_independent_cost_raw_counters_and_process_clock(self):
        from src.smt_fullfab.harness.evaluation import audit_cost
        class SimulatedEvidence:
            def __init__(self):
                self.objects = {}
                self.manifest = {"config": default_config(), "created_epoch": 0}
                self.manifest["deadline_epoch"] = self.manifest["config"]["limits"]["wall_seconds"]
                self.value = {"sealed_epoch": 8}
                self.attempts = {}
            def put(self, value):
                raw = value if isinstance(value, bytes) else encode(value)
                ref = sha_bytes(raw); self.objects[ref] = raw; return ref
            def get(self, ref): return json.loads(self.objects[ref])
            def raw(self, ref): return self.objects[ref]
            def rows(self, kind): return self.attempts if kind == "attempts" else {}
        e = SimulatedEvidence()
        prompt, schema = e.put(b"simulation only"), e.put({})
        final, argv = e.put(b"{}"), e.put(["offline-test-not-executed"])
        events = e.put(encode({"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20, "cached_input_tokens": 30}}) + b"\n")
        inputs = {"prompt.txt": prompt, "schema.json": schema}
        spec = e.put({"call_id": "simulated", "argv": e.get(argv), "input_files_sha256": inputs, "begun_monotonic_seconds": 10})
        receipt = e.put({"call_id": "simulated", "output_files_sha256": {"events.jsonl": events, "final.txt": final}, "command_returncode": 0})
        waited = e.put({"observed_monotonic_seconds": 15, "wait_completed": True})
        originals = {"spec.json": spec, "receipt.json": receipt, "parent_observed.json": waited}
        guard = e.put({"files_sha256": originals, "parent_wait_wall_seconds": 5})
        e.attempts["simulated"] = {"attempt_id": "simulated", "channel": "codex", "status": "processed", "prompt_ref": prompt, "schema_ref": schema,
                                    "raw_ref": final, "usage": {"input_tokens": 100, "output_tokens": 20, "cached_input_tokens": 30}, "duration_seconds": 5,
                                    "transport": {"events_ref": events, "guard_ref": guard, "original_guard_files": originals, "original_input_files": inputs, "command_ref": argv, "returncode": 0}}
        self.assertEqual(audit_cost(e)["total_reported_tokens"], 120)
        e.attempts["simulated"]["duration_seconds"] = 0
        with self.assertRaisesRegex(HarnessError, "guard_duration"): audit_cost(e)
        e.attempts["simulated"]["duration_seconds"] = 5
        e.attempts["simulated"]["usage"]["cached_input_tokens"] = 0
        with self.assertRaisesRegex(HarnessError, "usage_source"): audit_cost(e)

    def test_shared_account_reservations_unknown_and_no_second_case(self):
        root = Path(tempfile.mkdtemp(prefix="offline-account-test-"))
        # Synthetic engineering grant for testing the ledger itself. This is
        # deliberately separate from the actual experiment admission report.
        fp = fingerprint()
        proof = root / "synthetic_test_grant.json"
        proof.write_bytes(encode({"gates": {g: "pass" for g in ("G0", "G1", "G2", "G3", "G4")}, "fingerprint_sha256": fp["sha256"], "test_only": True}))
        config = default_config(seconds=60)
        config["limits"].update(CAPS["micro"])
        entry = {"group": "micro", "config_sha256": digest(config), "initial_state_sha256": None}
        reg = {"caps": CAPS, "full_B_new_run_limit": 1, "fingerprint_sha256": fp["sha256"], "engineering_report": str(proof),
               "engineering_report_sha256": sha_bytes(proof.read_bytes()), "cases": {"one": entry, "two": entry},
               "cli_binary": "/never/invoked", "cli_sha256": "not-a-real-cli"}
        (root / "experiment.json").write_bytes(encode(reg))
        admission = {"experiment_directory": str(root), "experiment_sha256": digest(reg), "group": "micro", "case_id": "one", "cli_binary": "/never/invoked", "cli_sha256": "not-a-real-cli"}
        first = Runtime.start_new(root / "one", config, experiment_id="offline-ledger-negative-control", mode="model", admission=admission)
        try:
            second = Runtime.start_new(root / "two", config, experiment_id="offline-ledger-negative-control", mode="model", admission={**admission, "case_id": "two"})
            try:
                self.assertEqual(cumulative_usage(admission)["micro"]["attempts"], 0)
                with experiment_lock(admission):
                    with self.assertRaisesRegex(HarnessError, "experiment_busy"):
                        with experiment_lock(admission): pass
                aid = first.reserve_attempt("test reservation only, never launched", {})
                with self.assertRaisesRegex(HarnessError, "experiment_unknown"):
                    second.reserve_attempt("must not reserve concurrently", {})
                self.assertEqual(cumulative_usage(admission)["micro"]["pending"], 1)
                first.close()
                first = Runtime.resume_run(root / "one")
                self.assertEqual(first.store.read("attempts", aid)["status"], "not_sent")
                self.assertEqual(cumulative_usage(admission)["micro"]["pending"], 0)
                with self.assertRaisesRegex(HarnessError, "case_already_started"):
                    Runtime.start_new(root / "replacement", config, experiment_id="illegal-replacement", mode="model", admission=admission)
            finally:
                second.close()
        finally:
            first.close()

    def test_saved_fragment_prefix_audit_does_not_claim_full_window(self):
        folder = Path(tempfile.mkdtemp(prefix="offline-fragment-audit-"))
        fixture = load_fragment(ROOT / "runs/smt_fullfab_stage2/B_1701_1h_delta_v14__candidate_paths_001/plan_00002")
        config = default_config(seconds=3600-fixture["initial"]["state"]["t"])
        config["initialization"] = "registered_saved_state"
        runtime = Runtime.start_new(folder / "run", config, experiment_id="offline-prefix-audit", initial=fixture["initial"])
        try:
            result = propose(runtime, public_delta(fixture))
            apply(runtime, result["candidate_ref"])
            runtime.advance()
            runtime.stop("registered_fragment_accepted")
            sha = seal_evidence(runtime)
            report = audit_run(folder / "run", expected_sha256=sha, scope="accepted_fragment")
            self.assertTrue(report["valid"], report["errors"])
            self.assertTrue(report["physical_prefix_checks"])
            self.assertFalse(report["physical_validity"])
            self.assertEqual(report["execution_window"], "fail")
            evidence = Evidence(folder / "run", sha)
            trace = [evidence.get(ref) for ref in evidence.value["physical"]]
            # Omit one mapping inside a candidate: independent coverage catches it.
            ref = next(iter(evidence.value["records"]["candidates"].values()))
            candidate = evidence.get(ref)
            candidate["field_sources"].pop()
            evidence.cache[ref] = candidate
            with self.assertRaisesRegex(HarnessError, "field_source_coverage"):
                audit_provenance(evidence, trace)
        finally:
            runtime.close()

    def test_T05_cross_page_batch_is_validated_as_complete_group(self):
        # The same compiler used at the gateway receives the union of two exact
        # pages. Page-local legality never substitutes for whole-batch legality.
        from tests.test_smt_fullfab_plan_delta import PlanDeltaTests
        from src.smt_fullfab.harness.facts import FactReader, build_facts
        fixture = PlanDeltaTests()
        fixture.setUp()
        facts = build_facts(fixture.problem, fixture.base)
        reader = FactReader("cross-page", facts)
        first = reader.read({"kind": "operations", "cursor": reader.cursor("operations", 1), "count": 1})
        second = reader.read({"kind": "operations", "cursor": first["next_cursor"], "count": 1})
        self.assertEqual([first["entities"][0]["value"]["operation_id"], second["entities"][0]["value"]["operation_id"]], ["op-z", "op-c"])
        fixture.test_batch_membership_is_explicit_and_constraints_only_reject()
        fixture.problem["operations"][2]["eligible_machines"] = [1, 2]
        fixture.problem["operations"][2]["batch_key"] = ["incompatible-product", 1, "recipe"]
        fixture.bind()
        fixture.reject("batch")

    def test_T20_each_frozen_identity_rejects_a_matching_projection(self):
        root = Path(tempfile.mkdtemp(prefix="offline-version-conflicts-"))
        runtime = Runtime.start_new(root / "run", default_config(seconds=60), experiment_id="offline-version-rejection")
        original = deepcopy(runtime.manifest)
        try:
            for field in ("files", "data", "protocol"):
                changed = deepcopy(original)
                if field == "protocol": changed["fingerprint"][field] = "other-protocol"
                else:
                    key = next(iter(changed["fingerprint"][field]))
                    changed["fingerprint"][field][key] = "0" * 64
                with runtime.store.transaction(): runtime.store.record("manifest", "run", changed, replace=True)
                (root / "run/manifest.json").write_bytes(encode(changed))
                runtime.close()
                with self.assertRaisesRegex(HarnessError, "fingerprint_changed"):
                    Runtime.resume_run(root / "run")
                from src.smt_fullfab.harness.store import Store
                store = Store(root / "run")
                with store.transaction(): store.record("manifest", "run", original, replace=True)
                store.close()
                (root / "run/manifest.json").write_bytes(encode(original))
                runtime = Runtime.resume_run(root / "run")
        finally:
            runtime.close()


if __name__ == "__main__": unittest.main()
