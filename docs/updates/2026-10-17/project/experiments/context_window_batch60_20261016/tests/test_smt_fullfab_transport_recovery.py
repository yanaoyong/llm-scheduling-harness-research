"""Completed-call recovery tests: synthetic evidence only, never launch Codex."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.smt_fullfab import budget
from src.smt_fullfab.model_transport import (
    ModelConfig, PROMPT_CHARACTER_LIMIT, _finish_details, _sha, call_model,
    summarize_events,
)


class CompletedTransportRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="smt_fullfab_transport_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.enterContext(patch.object(budget, "ROOT", self.root))
        self.run = self.root / "runs/smt_fullfab_stage2/B_recovery_fixture/model_000"
        self.run.mkdir(parents=True)
        self.ledger = budget.BudgetLedger(self.root / "smt_fullfab_ledger.jsonl")
        self.ledger.approve(json.loads(budget.APPROVAL.read_text()))
        self.config = ModelConfig(
            ledger_path=str(self.ledger.path), phase="stage2_probe",
            grant_id="smt-fullfab-stage2-probe-v1", timeout_seconds=180,
            authorization_context={"purpose": "B", "arm": "B", "scenario": 1701,
                                   "window_seconds": 3600},
        )
        self.prompt = "只使用这份观察；请返回 JSON。\n"
        self.schema = {"type": "object", "properties": {"patch": {"type": "array"}}}
        schema_text = json.dumps(self.schema, ensure_ascii=False, indent=2) + "\n"
        self.fingerprint = _sha(self.prompt + "\n" + schema_text + "\n" +
                                json.dumps(asdict(self.config), sort_keys=True))
        self.metadata = {
            "request_fingerprint": self.fingerprint, "model": self.config.model,
            "timeout_seconds": self.config.timeout_seconds,
            "reasoning_effort": self.config.reasoning_effort,
            "prompt_characters": len(self.prompt),
            "prompt_character_limit": PROMPT_CHARACTER_LIMIT,
            "authorization_context": self.config.authorization_context,
        }
        self.call_id = self.ledger.reserve(
            phase=self.config.phase, run_id=str(self.run),
            grant_id=self.config.grant_id, metadata=self.metadata,
        )
        self.started = "2026-10-09T00:00:00+00:00"
        self.write("request.json", {
            "call_id": self.call_id, "started_at": self.started,
            "request_fingerprint": self.fingerprint, "config": asdict(self.config),
        })
        (self.run / "prompt.txt").write_text(self.prompt, encoding="utf-8")
        (self.run / "schema.json").write_text(schema_text, encoding="utf-8")
        (self.run / "attempt.claim").write_text(self.fingerprint + "\n", encoding="utf-8")
        self.events = [
            {"type": "thread.started", "thread_id": "synthetic-thread"},
            {"type": "turn.completed", "usage": {
                "input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 3,
            }},
        ]
        (self.run / "events.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in self.events), encoding="utf-8",
        )
        self.output = {"patch": [], "reason": "合成测试"}
        self.write("final.txt", self.output)
        self.result = {
            "call_id": self.call_id, "status": "success", "failure_reason": None,
            "request_fingerprint": self.fingerprint, "started_at": self.started,
            "finished_at": "2026-10-09T00:00:02.125000+00:00",
            "config": asdict(self.config), "cli_version": "synthetic",
            "returncode": 0, "timed_out": False, "launch_error": None,
            "duration_seconds": 2.125, "model_elapsed_seconds": 2.125,
            "pure_model_seconds": None, "backend_http_requests": None,
            "model_calls": 1, "automatic_retries": 0, "cost_usd": None,
            "prompt_characters": len(self.prompt), "prompt_character_limit": PROMPT_CHARACTER_LIMIT,
            "server_output_token_limit": None, "cost_status": "unknown",
            "output": self.output, "decode_error": None,
            "malformed_event_lines": [], **summarize_events(self.events),
        }
        self.write("result.json", self.result)
        self.cli_probe = self.enterContext(patch(
            "src.smt_fullfab.model_transport.subprocess.run",
            side_effect=AssertionError("Replay must not probe or invoke the CLI"),
        ))
        self.cli_launch = self.enterContext(patch(
            "src.smt_fullfab.model_transport.subprocess.Popen",
            side_effect=AssertionError("Replay must not launch a model"),
        ))

    def write(self, name, value):
        (self.run / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def rows(self):
        return [json.loads(line) for line in self.ledger.path.read_text().splitlines()]

    def replace_rows(self, rows):
        # Deliberate evidence corruption is confined to this test's temp ledger.
        self.ledger.path.write_text("".join(json.dumps(row) + "\n" for row in rows))

    def replay(self, **kwargs):
        return call_model(self.prompt, self.schema, self.run, self.config, resume=True, **kwargs)

    def assert_rejected_without_mutation(self, exception=ValueError):
        before = self.ledger.path.read_bytes()
        with self.assertRaises(exception):
            self.replay()
        self.assertEqual(before, self.ledger.path.read_bytes())
        self.cli_probe.assert_not_called()
        self.cli_launch.assert_not_called()

    def test_missing_finish_is_reconciled_once_with_original_output_usage_and_files(self):
        saved = {path.name: path.read_bytes() for path in self.run.iterdir()}
        ledger_before = self.ledger.path.read_bytes()
        self.assertEqual(self.ledger.summary()["pending"], [self.call_id])
        replayed = self.replay()
        self.assertEqual(replayed, self.result)
        self.assertIsNone(replayed["usage"]["reasoning_output_tokens"])
        self.assertEqual(saved, {path.name: path.read_bytes() for path in self.run.iterdir()})
        self.assertTrue(self.ledger.path.read_bytes().startswith(ledger_before))
        finishes = [row for row in self.rows() if row["event"] == "finish"]
        self.assertEqual(len(finishes), 1)
        self.assertEqual(finishes[0]["status"], "success")
        self.assertEqual(finishes[0]["details"], _finish_details(self.result, self.run / "result.json"))
        ledger_after = self.ledger.path.read_bytes()
        self.assertEqual(self.replay(), self.result)
        self.assertEqual(ledger_after, self.ledger.path.read_bytes())
        summary = self.ledger.summary()
        self.assertEqual(summary["attempts"], 1)
        self.assertEqual(summary["pending"], [])
        self.assertEqual(summary["reported_input_output_tokens"], 13)
        self.assertEqual(summary["model_active_seconds"], 2.125)
        self.cli_probe.assert_not_called()
        self.cli_launch.assert_not_called()

    def test_matching_existing_finish_is_read_only(self):
        self.ledger.finish(self.call_id, "success", _finish_details(self.result, self.run / "result.json"))
        before = self.ledger.path.read_bytes()
        self.assertEqual(self.replay(), self.result)
        self.assertEqual(before, self.ledger.path.read_bytes())

    def test_concurrent_recovery_finishes_exactly_once(self):
        barrier = threading.Barrier(2)
        original_finish = budget.BudgetLedger.finish

        def synchronized_finish(ledger, *args, **kwargs):
            barrier.wait(timeout=5)
            return original_finish(ledger, *args, **kwargs)

        with patch.object(budget.BudgetLedger, "finish", synchronized_finish):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: self.replay(), range(2)))
        self.assertEqual(results, [self.result, self.result])
        self.assertEqual(sum(row["event"] == "finish" for row in self.rows()), 1)
        self.assertEqual(sum(row["event"] == "reserve" for row in self.rows()), 1)

    def test_fresh_code_path_finish_crash_replays_without_second_launch(self):
        self.ledger.finish(self.call_id, "success", _finish_details(self.result, self.run / "result.json"))
        fresh = self.run.parent / "model_001"
        events = self.events
        output = self.output

        class FakeChild:
            returncode = 0

            def __init__(self, *args, **kwargs):
                self.stdout = kwargs["stdout"]

            def communicate(self, prompt, timeout):
                self.stdout.write("".join(json.dumps(event) + "\n" for event in events))
                self.stdout.flush()
                (fresh / "final.txt").write_text(json.dumps(output), encoding="utf-8")

        with patch("src.smt_fullfab.model_transport.build_command", return_value=["never-executed"]), \
             patch("src.smt_fullfab.model_transport.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="fake")) as probe, \
             patch("src.smt_fullfab.model_transport.subprocess.Popen", side_effect=FakeChild) as launch, \
             patch.object(budget.BudgetLedger, "finish", side_effect=RuntimeError("synthetic crash after result rename")):
            with self.assertRaisesRegex(RuntimeError, "synthetic crash"):
                call_model(self.prompt, self.schema, fresh, self.config)
            self.assertEqual(probe.call_count, 1)
            self.assertEqual(launch.call_count, 1)
        result_bytes = (fresh / "result.json").read_bytes()
        old = json.loads(result_bytes)
        self.assertEqual(self.ledger.summary()["pending"], [old["call_id"]])
        replayed = call_model(self.prompt, self.schema, fresh, self.config, resume=True)
        self.assertEqual(replayed, old)
        self.assertEqual(result_bytes, (fresh / "result.json").read_bytes())
        self.assertEqual(self.ledger.summary()["pending"], [])
        self.assertEqual(self.ledger.summary()["attempts"], 2)
        self.cli_probe.assert_not_called()
        self.cli_launch.assert_not_called()

    def test_conflicting_finish_is_never_overwritten_or_duplicated(self):
        original_rows = self.rows()
        details = _finish_details(self.result, self.run / "result.json")
        variants = [
            {"status": "failed", "details": details},
            {"status": "success", "details": {**details, "duration_seconds": 0}},
            {"status": "success", "details": {**details, "usage": {"input_tokens": 99}}},
            {"status": "success", "details": {**details, "result_path": "/another/result.json"}},
        ]
        for variant in variants:
            with self.subTest(variant=variant):
                self.replace_rows(original_rows + [{"event": "finish", "call_id": self.call_id, **variant}])
                self.assert_rejected_without_mutation()
        finish = {"event": "finish", "call_id": self.call_id, "status": "success", "details": details}
        self.replace_rows(original_rows + [finish, finish])
        self.assert_rejected_without_mutation()

    def test_reservation_identity_and_full_metadata_must_match(self):
        original_rows = self.rows()
        reserve = original_rows[-1]
        variants = [
            {**reserve, "run_id": str(self.run.parent / "model_other")},
            {**reserve, "phase": "formal"},
            {**reserve, "grant_id": "different-grant"},
        ]
        for key, value in {
            "request_fingerprint": "wrong", "model": "different-model", "timeout_seconds": 179,
            "reasoning_effort": "high", "prompt_characters": 1, "prompt_character_limit": 1,
            "authorization_context": {"purpose": "C"},
        }.items():
            variants.append({**reserve, "metadata": {**self.metadata, key: value}})
        # Legacy incomplete reservation evidence must not be silently upgraded.
        variants.append({**reserve, "metadata": {k: v for k, v in self.metadata.items() if k != "reasoning_effort"}})
        for variant in variants:
            with self.subTest(variant=variant):
                self.replace_rows(original_rows[:-1] + [variant])
                self.assert_rejected_without_mutation()

    def test_missing_duplicate_or_wrong_call_reservation_is_rejected(self):
        original_rows = self.rows()
        for rows in (original_rows[:-1], original_rows + [original_rows[-1]],
                     original_rows[:-1] + [{**original_rows[-1], "call_id": "another-call"}]):
            with self.subTest(rows=rows):
                self.replace_rows(rows)
                self.assert_rejected_without_mutation()

    def test_request_and_result_identity_must_both_match(self):
        originals = {name: json.loads((self.run / name).read_text()) for name in ("request.json", "result.json")}
        for name in originals:
            for key, value in {
                "request_fingerprint": "wrong", "call_id": "another-call",
                "started_at": "2026-10-09T00:01:00+00:00",
                "config": {**asdict(self.config), "reasoning_effort": "high"},
            }.items():
                with self.subTest(name=name, key=key):
                    self.write(name, {**originals[name], key: value})
                    self.assert_rejected_without_mutation()
                    self.write(name, originals[name])

    def test_saved_prompt_schema_claim_or_missing_evidence_is_rejected(self):
        for name in ("request.json", "prompt.txt", "schema.json", "attempt.claim", "events.jsonl"):
            with self.subTest(name=name, condition="missing"):
                path = self.run / name
                before = path.read_bytes()
                path.unlink()
                self.assert_rejected_without_mutation()
                path.write_bytes(before)
            if name in ("prompt.txt", "schema.json", "attempt.claim"):
                with self.subTest(name=name, condition="changed"):
                    path.write_bytes(before + b" ")
                    self.assert_rejected_without_mutation()
                    path.write_bytes(before)

    def test_caller_prompt_schema_or_config_change_cannot_reuse_result(self):
        before = self.ledger.path.read_bytes()
        for args in (
            (self.prompt + "changed", self.schema, self.config),
            (self.prompt, {"type": "string"}, self.config),
            (self.prompt, self.schema, replace(self.config, timeout_seconds=179)),
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                call_model(args[0], args[1], self.run, args[2], resume=True)
            self.assertEqual(before, self.ledger.path.read_bytes())

    def test_result_usage_output_or_terminal_facts_cannot_change(self):
        variants = {
            "usage": {**self.result["usage"], "output_tokens": 99},
            "output": {"patch": [{"invented": True}]},
            "status": "failed", "failure_reason": "invented-failure",
            "finished_at": "2026-10-08T00:00:00+00:00",
            "duration_seconds": -1, "model_elapsed_seconds": 3,
            "model_calls": True, "automatic_retries": False,
            "timed_out": 0, "cost_usd": 0,
            "returncode": False, "launch_error": 1,
            "completed_turns": 2, "malformed_event_lines": ["invented"],
        }
        for key, value in variants.items():
            with self.subTest(key=key):
                self.write("result.json", {**self.result, key: value})
                self.assert_rejected_without_mutation()
        self.write("result.json", self.result)
        self.write("final.txt", {"patch": [{"changed": True}]})
        self.assert_rejected_without_mutation()

    def test_timeout_completion_preserves_unknown_usage_and_failure(self):
        (self.run / "events.jsonl").write_text("")
        (self.run / "final.txt").unlink()
        timeout = {
            **self.result, **summarize_events([]), "status": "timeout",
            "failure_reason": "model_call_timeout", "timed_out": True,
            "returncode": -15, "output": None, "decode_error": "No final message file",
        }
        self.write("result.json", timeout)
        before = (self.run / "result.json").read_bytes()
        self.assertEqual(self.replay(), timeout)
        self.assertEqual(before, (self.run / "result.json").read_bytes())
        finish = self.rows()[-1]
        self.assertEqual(finish["status"], "timeout")
        self.assertEqual(finish["details"]["usage"], timeout["usage"])
        self.assertTrue(all(value is None for value in finish["details"]["usage"].values()))
        self.assertEqual(self.ledger.summary()["unknown_completed"], [self.call_id])

    def test_pending_or_temporary_result_is_not_terminal_and_never_retried(self):
        (self.run / "result.json").rename(self.run / "result.json.tmp")
        self.assert_rejected_without_mutation(FileNotFoundError)
        self.assertEqual(self.ledger.summary()["pending"], [self.call_id])
        self.assertEqual(sum(row["event"] == "finish" for row in self.rows()), 0)
        absent = self.run.parent / "nonexistent"
        with self.assertRaises(FileNotFoundError):
            call_model(self.prompt, self.schema, absent, self.config, resume=True)
        self.assertFalse(absent.exists())

    def test_existing_result_requires_explicit_resume(self):
        before = self.ledger.path.read_bytes()
        with self.assertRaises(FileExistsError):
            call_model(self.prompt, self.schema, self.run, self.config)
        self.assertEqual(before, self.ledger.path.read_bytes())


if __name__ == "__main__":
    unittest.main()
