"""Recovery execution control with synthetic physical/model stubs only."""
from contextlib import ExitStack
from copy import deepcopy
import dataclasses
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab import budget, controller_resume as resume
from src.smt_fullfab.controller_audit import _sections
from src.smt_fullfab.controller_recovery import prepare_B_recovery, _inventory
from src.smt_fullfab.environment import digest, write_new
from src.smt_fullfab.model_transport import ModelConfig, PROMPT_CHARACTER_LIMIT
from tests.test_smt_fullfab_page_recovery import make_fixture


class SyntheticPhysicalState:
    """Snapshot/clock stub: no factory, dispatch algorithm or physical claim."""
    problem_value = None
    instances = []
    reject_commit = False

    @classmethod
    def from_snapshot(cls, path, *, trace_path):
        value = json.loads(Path(path).read_text())
        env = cls()
        env.state = deepcopy(value["state"])
        env.t, env.horizon, env.finished = 0, 3600, False
        env.physical, env.data_dir = {0}, Path("synthetic-no-data")
        env.trace_path = Path(trace_path)
        env.state["trace"].append({"kind": "snapshot_loaded", "snapshot_sha256": value["state_sha256"]})
        env.trace_path.write_text("".join(json.dumps(row) + "\n" for row in env.state["trace"]))
        env.commits, env.advances = [], []
        cls.instances.append(env)
        return env

    def problem(self, *, plan_seconds, lookahead_depth):
        assert (plan_seconds, lookahead_depth) == (14400, 2)
        value = deepcopy(self.problem_value)
        if self.t:
            value["time"], value["horizon_end"] = self.t, self.t + plan_seconds
        return value

    def snapshot(self, path):
        state = {**deepcopy(self.state), "t": self.t, "finished": self.finished}
        write_new(path, {"state": state, "state_sha256": digest(state)})

    def commit_plan(self, plan):
        if self.reject_commit:
            raise ValueError("synthetic physical commit rejection")
        self.commits.append(deepcopy(plan))

    def advance_plan(self, target):
        self.advances.append(target)
        self.t = target
        self.finished = self.t >= self.horizon


class ControllerResumeTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        temp = self.stack.enter_context(tempfile.TemporaryDirectory(prefix="smt_fullfab_resume_test_"))
        self.root = Path(temp).resolve()
        outputs = [{"tasks": [{"machine": 0, "operations": [f"lot{i}:1:1"], "start": 0, "sequence": i}],
                    "holds": [], "commit": False, "reason": "saved explicit model choice"} for i in range(15)]
        outputs[14]["tasks"][0]["operations"] = ["lot0:1:1"]  # Wrong prior-page identity, never repaired by code.
        self.parent, self.ledger_path = make_fixture(self.root, page_count=18, outputs=outputs)
        terminal = json.loads((self.parent / "result.json").read_text())
        terminal["wall_seconds"] = 20  # Includes all fifteen synthetic one-second calls.
        (self.parent / "result.json").write_text(json.dumps(terminal))
        # Complete the synthetic transport config without changing any decisions.
        ledger_rows = [json.loads(line) for line in self.ledger_path.read_text().splitlines()]
        for directory in self.parent.glob("model_*"):
            request = json.loads((directory / "request.json").read_text())
            request["config"] = dataclasses.asdict(ModelConfig(**request["config"], ledger_path=str(self.ledger_path)))
            schema_text = json.dumps(json.loads((directory / "schema.json").read_text()), ensure_ascii=False, indent=2) + "\n"
            fp = hashlib.sha256(((directory / "prompt.txt").read_text() + "\n" + schema_text + "\n" +
                                 json.dumps(request["config"], sort_keys=True)).encode()).hexdigest()
            request["request_fingerprint"] = fp
            (directory / "request.json").write_text(json.dumps(request))
            model = json.loads((directory / "result.json").read_text())
            model.update(config=request["config"], request_fingerprint=fp)
            (directory / "result.json").write_text(json.dumps(model))
            (directory / "attempt.claim").write_text(fp + "\n")
            for row in ledger_rows:
                if row.get("event") == "reserve" and row["call_id"] == request["call_id"]:
                    row["metadata"]["request_fingerprint"] = fp
        self.ledger_path.write_text("".join(json.dumps(row) + "\n" for row in ledger_rows))
        self.package_path = self.root / "prepared.json"
        with patch("src.smt_fullfab.controller_recovery._verify_cold_checkpoint", return_value={"valid": True, "simulation_seconds": 0}):
            self.package = prepare_B_recovery(self.parent, self.package_path, self.ledger_path)
        self.assertEqual(self.package["status"], "prepared", self.package.get("errors"))
        self.assertEqual(self.package["next_page"], 14)
        self.stack.enter_context(patch.object(budget, "ROOT", self.root))
        self.stack.enter_context(patch.object(resume, "ROOT", self.root))
        self.compatibility = self.stack.enter_context(patch.object(resume, "_verify_runtime_compatibility"))
        self.segment = self.parent.with_name(self.parent.name + "__recovery_001")
        self.protocol_path = self.root / "protocol.json"
        self.protocol = {"schema": "smt-fullfab-B-recovery-protocol-v1", "parent_run_id": str(self.parent),
                         "segment_run_id": str(self.segment), "package_identity_sha256": self.package["package_sha256"],
                         "recovery_package_sha256": resume.sha_file(self.package_path), "model": "gpt-6-astra",
                         "reasoning_effort": "medium", "per_call_timeout_seconds": 180,
                         "plan_seconds": 14400, "lookahead_depth": 2, "period_seconds": 1800,
                         "wall_seconds": 7200, "max_log_bytes": 1000000, "max_calls": None, "max_reported_tokens": None,
                         "max_revisions_per_page": 1, "max_revisions_per_plan": 3}
        write_new(self.protocol_path, self.protocol)
        self.stack.enter_context(patch.object(resume, "FullFabEnvironment", SyntheticPhysicalState))
        SyntheticPhysicalState.problem_value = json.loads((self.parent / "problem_000.json").read_text())
        SyntheticPhysicalState.instances = []
        SyntheticPhysicalState.reject_commit = False
        self.stack.enter_context(patch.object(resume, "source_snapshot", return_value={"synthetic_unit_stub": True}))
        self.physical_audit = self.stack.enter_context(patch.object(resume, "audit_trace", return_value={"valid": True, "metrics": {}}))
        self.source_audit = self.stack.enter_context(patch.object(resume, "_audit_completed_segment", return_value={"valid": True, "successful_full_window": True, "errors": []}))
        self.calls, self.response_override = [], None
        self.model_status = "success"
        self.transport = self.stack.enter_context(patch.object(resume, "call_model", side_effect=self.fake_model))
        self.stack.enter_context(patch("src.smt_fullfab.model_transport.subprocess.Popen", side_effect=AssertionError("no real model")))
        self.stack.enter_context(patch("src.smt_fullfab.optimizer.cp_model.CpModel", side_effect=AssertionError("no CP")))
        self.stack.enter_context(patch("src.smt_fullfab.optimizer.cp_model.CpSolver", side_effect=AssertionError("no CP")))

    def fake_model(self, prompt, schema, directory, config):
        sections = _sections(prompt)
        index = sections["SCHEMA_AND_LIMITS"]["page_index"]
        value = {"tasks": [{"machine": group["machines"][0][0], "operations": [row[0]],
                            "sequence": row[8], "start": sections["SCHEMA_AND_LIMITS"]["problem_metadata"]["time"]}
                           for group in sections["PAGE"] for row in group["operations"]],
                 "holds": [], "commit": sections["SCHEMA_AND_LIMITS"]["last_page"], "reason": "new explicit synthetic choice"}
        if self.response_override:
            value = self.response_override(index, deepcopy(value), sections)
        directory = Path(directory)
        directory.mkdir()
        ledger = budget.BudgetLedger(self.ledger_path)
        fingerprint = hashlib.sha256(prompt.encode()).hexdigest()
        cid = ledger.reserve(phase=config.phase, run_id=str(directory), grant_id=config.grant_id,
                             metadata={"model": config.model, "reasoning_effort": config.reasoning_effort,
                                       "timeout_seconds": config.timeout_seconds, "authorization_context": config.authorization_context,
                                       "request_fingerprint": fingerprint, "prompt_characters": len(prompt),
                                       "prompt_character_limit": PROMPT_CHARACTER_LIMIT})
        result = {"call_id": cid, "status": self.model_status, "output": value,
                  "failure_reason": None if self.model_status == "success" else "model_call_timeout",
                  "usage": {"input_tokens": 2, "output_tokens": 3} if self.model_status == "success" else
                           {"input_tokens": None, "output_tokens": None}, "duration_seconds": 0.000001}
        write_new(directory / "result.json", result)
        ledger.finish(cid, self.model_status, {"usage": result["usage"], "duration_seconds": result["duration_seconds"]})
        self.calls.append({"index": index, "directory": directory, "config": config, "sections": sections, "result": result})
        return result

    def execute(self, **kwargs):
        return resume.run(self.package_path, self.segment.name, ledger_path=self.ledger_path,
                          protocol_path=self.protocol_path, **kwargs)

    def rows(self, name):
        path = self.segment / name
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_reuses_fourteen_pages_revision_then_rolls_without_original_calls(self):
        before = _inventory(self.parent)
        result = self.execute()
        self.assertEqual(result["status"], "success", result)
        self.assertEqual([row["index"] for row in self.calls], [14, 15, 16, 17, 0])
        self.assertEqual([row["directory"].name for row in self.calls], [f"model_{i:03d}" for i in range(15, 20)])
        self.assertEqual(result["model_calls"], 5)
        self.assertEqual(result["simulation_seconds"], 3600)
        self.assertEqual(result["plans_committed"], 2)
        self.assertEqual(_inventory(self.parent), before)
        self.assertEqual(json.loads((self.parent / "result.json").read_text())["status"], "failed")
        feedback = self.calls[0]["sections"][resume.FEEDBACK_SECTION]
        self.assertEqual(feedback["rejected_output"]["tasks"][0]["operations"], ["lot0:1:1"])
        self.assertEqual(feedback["revision_scope"], "replace_this_page_only")
        self.assertTrue(any("outside" in error for error in feedback["validation_errors"]))
        self.assertNotIn(resume.FEEDBACK_SECTION, self.calls[1]["sections"])
        accepted = self.rows("page_accepted.jsonl")
        self.assertEqual(sum(row["source_parent"] for row in accepted), 14)
        self.assertEqual(len(self.rows("plan_commits.jsonl")[0]["source_page_call_ids"]), 18)
        env = SyntheticPhysicalState.instances[0]
        self.assertEqual(env.advances, [1800, 3600])
        self.assertEqual(len(env.commits[0]["tasks"]), 18)
        mapping = json.loads((self.segment / "recovery_mapping.json").read_text())
        self.assertEqual(mapping["inherited"]["model_attempts"], 15)
        self.assertEqual(result["cumulative_model_account"]["attempts"], 20)
        self.assertEqual(result["registration_id"], self.package["original_registration"]["registration_id"])
        self.assertTrue(result["acceptance"]["accepted"])
        self.assertIsNone(result["resource_finalization_error"])
        self.assertEqual(budget.BudgetLedger(self.ledger_path).summary(str(self.segment))["runner_wall_seconds"],
                         result["acceptance"]["cumulative_final_wall_seconds"])
        self.assertEqual(result["acceptance"]["cumulative_log_bytes_including_acceptance"],
                         mapping["inherited"]["log_bytes"] + resume._directory_bytes(self.segment))
        with self.assertRaises(FileExistsError):
            self.execute()
        self.assertEqual(len(self.calls), 5)

    def test_original_failed_page_gets_one_revision_only_and_never_code_repair(self):
        self.response_override = lambda index, value, sections: {**value, "tasks": [{**value["tasks"][0], "operations": ["lot0:1:1"]}]}
        result = self.execute()
        self.assertEqual(result["status"], "failed")
        self.assertIn("revision limit", result["failure"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result["plans_committed"], 0)
        self.assertEqual(result["simulation_seconds"], 0)
        self.assertEqual(self.rows("recovery_decisions.jsonl")[0]["revision_number"], 1)
        self.assertEqual(self.rows("page_rejected.jsonl")[0]["cumulative_staged_sha256"], self.package["staged_sha256"])
        self.assertEqual(list(self.segment.glob("patch_*.json")), [])
        self.assertTrue((self.segment / "result.json").exists())
        self.assertTrue((self.segment / "checkpoint.json").exists())
        self.assertTrue(list(self.segment.glob("recovery_state_*.json")))

    def test_new_page_may_have_one_initial_attempt_and_one_counted_revision(self):
        seen = set()
        def fail_once(index, value, sections):
            if index == 15 and index not in seen:
                seen.add(index)
                value["tasks"][0]["operations"] = ["lot0:1:1"]
            return value
        self.response_override = fail_once
        result = self.execute()
        self.assertEqual(result["status"], "success", result)
        first = [row for row in self.rows("recovery_decisions.jsonl") if row["plan_index"] == 0]
        self.assertEqual([row["page_index"] for row in first], [14, 15, 15, 16, 17])
        self.assertEqual([row["revision"] for row in first], [True, False, True, False, False])
        self.assertFalse(first[1]["accepted"])
        self.assertTrue(first[2]["accepted"])

    def test_three_revision_plan_cap_includes_original_page_revision(self):
        seen = set()
        def fail_new_once(index, value, sections):
            if index in (15, 16, 17) and index not in seen:
                seen.add(index)
                value["tasks"][0]["operations"] = ["lot0:1:1"]
            return value
        self.response_override = fail_new_once
        result = self.execute()
        self.assertEqual(result["status"], "failed")
        self.assertIn("revision limit", result["failure"])
        self.assertEqual([row["index"] for row in self.calls], [14, 15, 15, 16, 16, 17])
        self.assertEqual(result["plans_committed"], 0)

    def test_final_page_requires_explicit_commit(self):
        self.response_override = lambda index, value, sections: {**value, "commit": False}
        result = self.execute()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["plans_committed"], 0)
        self.assertEqual(self.rows("plan_commits.jsonl"), [])
        self.assertTrue(any("final page lacks explicit commit" in row["validation_errors"] for row in self.rows("page_rejected.jsonl")))

    def test_physical_commit_rejection_preserves_candidate_and_failure(self):
        SyntheticPhysicalState.reject_commit = True
        result = self.execute()
        self.assertEqual(result["status"], "failed")
        self.assertIn("physical commit rejection", result["failure"])
        self.assertTrue((self.segment / "raw_plan_000.json").exists())
        self.assertEqual(self.rows("plan_commits.jsonl"), [])
        self.assertEqual(result["model_calls"], 4)

    def test_existing_pending_segment_is_refused_without_any_new_call(self):
        self.segment.mkdir()
        write_new(self.segment / "incomplete.json", {"pending": True})
        with self.assertRaises(FileExistsError):
            self.execute()
        self.transport.assert_not_called()

    def test_package_parent_or_ledger_tampering_prevents_registration(self):
        originals = {self.package_path: self.package_path.read_bytes(), self.ledger_path: self.ledger_path.read_bytes(),
                     self.parent / "checkpoint.json": (self.parent / "checkpoint.json").read_bytes()}
        for path in originals:
            with self.subTest(path=path):
                if path == self.package_path:
                    value = json.loads(originals[path]); value["next_page"] = 13
                    path.write_text(json.dumps(value))
                else:
                    path.write_bytes(originals[path].replace(b"0", b"1", 1))
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    self.execute()
                self.assertFalse(self.segment.exists())
                path.write_bytes(originals[path])
        self.transport.assert_not_called()

    def test_protocol_cannot_change_budget_or_revision_cap(self):
        for key, value in (("wall_seconds", 9000), ("max_revisions_per_page", 2),
                           ("max_revisions_per_plan", 4), ("recovery_package_sha256", "wrong")):
            with self.subTest(key=key):
                self.protocol_path.write_text(json.dumps({**self.protocol, key: value}))
                with self.assertRaisesRegex(ValueError, "protocol differs"):
                    self.execute()
                self.assertFalse(self.segment.exists())
        self.transport.assert_not_called()

    def test_frozen_prompt_parser_never_executes_source(self):
        path = self.parent / "source_snapshot/src/smt_fullfab/controller.py"
        schema, _ = resume.frozen_B_contract(self.parent)
        path.write_text("BASE='safe'\nB_PROMPT=BASE + ' text'\nB_SCHEMA=" + repr(schema) + "\nraise RuntimeError('must not execute')\n")
        self.assertEqual(resume.frozen_B_contract(self.parent), (schema, "safe text"))
        path.write_text("B_PROMPT=__import__('os').getcwd()\nB_SCHEMA=" + repr(schema))
        with self.assertRaisesRegex(ValueError, "safe literal"):
            resume.frozen_B_contract(self.parent)

    def test_restore_exception_still_writes_failure_checkpoint_and_progress(self):
        with patch.object(SyntheticPhysicalState, "from_snapshot", side_effect=ValueError("dependency hash mismatch")):
            result = self.execute()
        self.assertEqual(result["status"], "failed")
        self.assertIn("dependency hash mismatch", result["failure"])
        self.assertEqual((self.segment / "checkpoint.json").read_bytes(), (self.parent / "checkpoint.json").read_bytes())
        self.assertTrue(list(self.segment.glob("recovery_state_*.json")))
        self.transport.assert_not_called()

    def test_independent_audit_failure_cannot_pass_acceptance(self):
        self.source_audit.return_value = {"valid": False, "errors": ["synthetic provenance failure"]}
        result = self.execute()
        self.assertEqual(result["physical_result_status"], "success")
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["acceptance"]["accepted"])
        self.assertEqual(json.loads((self.segment / "result.json").read_text())["status"], "success")

    def test_final_audit_log_overrun_disqualifies_an_otherwise_valid_run(self):
        def oversized_audit(out, ledger_path):
            (out / "synthetic_audit_payload.bin").write_bytes(b"x" * 1000001)
            return {"valid": True, "successful_full_window": True, "errors": []}
        self.source_audit.side_effect = oversized_audit
        result = self.execute()
        self.assertTrue(result["acceptance"]["resource_overrun"])
        self.assertFalse(result["acceptance"]["accepted"])
        self.assertEqual(result["status"], "failed")

    def test_transport_timeout_is_charged_with_unknown_usage_and_not_retried(self):
        self.model_status = "timeout"
        result = self.execute()
        self.assertEqual(result["status"], "failed")
        self.assertIn("model_channel:model_call_timeout", result["failure"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result["model_calls"], 1)
        self.assertIn(self.calls[0]["result"]["call_id"], result["cumulative_model_account"]["unknown_completed"])
        self.assertEqual(result["plans_committed"], 0)
        self.assertFalse(self.rows("recovery_decisions.jsonl")[0]["accepted"])

    def test_completed_transport_exception_cannot_refund_ledger_attempt(self):
        def interrupted_after_completion(*args):
            self.fake_model(*args)
            raise RuntimeError("synthetic failure after persisted transport completion")
        self.transport.side_effect = interrupted_after_completion
        result = self.execute()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["model_calls"], 1)
        self.assertEqual(result["model_call_ids"], [self.calls[0]["result"]["call_id"]])
        self.assertEqual(result["cumulative_model_account"]["attempts"], 16)
        self.assertEqual(result["plans_committed"], 0)
        with self.assertRaises(FileExistsError):
            self.execute()

    def test_inherited_model_wall_exhaustion_stops_before_any_call(self):
        original = budget.BudgetLedger.summary
        def exhausted(ledger, run_id=None):
            account = original(ledger, run_id)
            account["model_active_seconds"] = 7199.5
            return account
        with patch.object(budget.BudgetLedger, "summary", exhausted):
            result = self.execute()
        self.assertIn("inherited cumulative runner/model wall", result["failure"])
        self.assertEqual(result["model_calls"], 0)
        self.transport.assert_not_called()

    def test_inherited_log_cap_is_checked_before_model_admission(self):
        def large_snapshot(out):
            (out / "synthetic_large_source.bin").write_bytes(b"x" * 1000000)
            return {"synthetic_unit_stub": True}
        with patch.object(resume, "source_snapshot", side_effect=large_snapshot):
            result = self.execute()
        self.assertIn("inherited cumulative log", result["failure"])
        self.assertEqual(result["model_calls"], 0)
        self.transport.assert_not_called()

    def test_post_audit_wall_is_accounted_and_can_disqualify_completion(self):
        clock = [100.0]
        def monotonic():
            clock[0] += 0.01
            return clock[0]
        def slow_audit(out, ledger_path):
            clock[0] += 7200
            return {"valid": True, "successful_full_window": True, "errors": []}
        self.source_audit.side_effect = slow_audit
        with patch.object(resume.time, "monotonic", side_effect=monotonic):
            result = self.execute()
        self.assertEqual(result["physical_result_status"], "success")
        self.assertTrue(result["acceptance"]["resource_overrun"])
        self.assertFalse(result["acceptance"]["accepted"])
        self.assertEqual(result["status"], "failed")
        account = budget.BudgetLedger(self.ledger_path).summary(str(self.segment))
        self.assertEqual(account["runner_wall_seconds"], result["acceptance"]["cumulative_final_wall_seconds"])

    def test_finalization_error_is_visible_and_never_claims_returned_success(self):
        with patch.object(budget.BudgetLedger, "report_recovery_segment_finalization", side_effect=ValueError("synthetic finalization rejection")):
            result = self.execute()
        self.assertEqual(result["status"], "failed")
        self.assertIn("synthetic finalization rejection", result["resource_finalization_error"])
        self.assertTrue((self.segment / "resource_finalization_error.json").exists())


if __name__ == "__main__":
    unittest.main()
