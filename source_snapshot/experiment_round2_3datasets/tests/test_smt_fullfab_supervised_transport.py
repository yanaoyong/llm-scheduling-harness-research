"""Fake guard/ledger tests only: never invoke a CLI or touch a real ledger."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import json
import hashlib
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

from src.smt_fullfab import model_transport as original
from src.smt_fullfab import model_transport_supervised as transport
from src.smt_fullfab.model_process_guard import GuardError


class FakeLedger:
    def __init__(self):
        self.rows = []

    def reserve(self, **record):
        self.rows.append({"event": "reserve", "call_id": "fake-call", **record})
        return "fake-call"

    def finish(self, call_id, status, details):
        self.rows.append({"event": "finish", "call_id": call_id, "status": status, "details": details})

    @contextmanager
    def _locked(self):
        yield self.rows


class SupervisedTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="supervised_transport_fake_")
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name).resolve() / "model_000"
        self.ledger = FakeLedger()
        self.enterContext(patch.object(transport, "BudgetLedger", return_value=self.ledger))
        self.enterContext(patch.object(transport, "_disabled_skills", return_value=[]))
        self.enterContext(patch.object(original, "_disabled_skills", return_value=[]))
        self.no_process = self.enterContext(patch.object(transport.subprocess, "Popen", side_effect=AssertionError("No real subprocess in fake tests")))
        self.no_probe = self.enterContext(patch.object(transport.subprocess, "run", side_effect=AssertionError("No version probe")))
        self.config = transport.ModelConfig(timeout_seconds=180, ledger_path=str(self.run.parent / "unused_ledger"))
        self.prompt = "只用当前观察。\n"
        self.schema = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}
        self.output = {"a": 3}
        self.events = [{"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 3}}]
        self.guard_result = {"schema": "smt-model-process-guard-v1", "lifecycle_complete": True,
                             "command_returncode": 0, "timed_out": False, "launch_error": None,
                             "synthetic_evidence_only": True}
        self.guard = self.enterContext(patch.object(transport, "run_guarded", side_effect=self.fake_guard))

    def fake_guard(self, command, *, run_dir, timeout_seconds, env, call_id, request_fingerprint):
        self.assertEqual(call_id, "fake-call")
        self.assertEqual(timeout_seconds, 180)
        self.assertEqual(command, original.build_command(self.run, original.ModelConfig(**asdict(self.config))))
        self.assertEqual(json.loads((run_dir / "request.json").read_text())["request_fingerprint"], request_fingerprint)
        self.assertEqual((run_dir / "attempt.claim").read_text(), request_fingerprint + "\n")
        self.assertEqual((run_dir / "prompt.txt").read_text(), self.prompt)
        self.assertEqual((run_dir / "schema.json").read_text(), json.dumps(self.schema, ensure_ascii=False, indent=2) + "\n")
        (run_dir / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in self.events))
        (run_dir / "stderr.log").write_bytes(b"")
        (run_dir / "final.txt").write_text(json.dumps(self.output))
        self.guard_result['output_files_sha256'] = {
            name: hashlib.sha256((run_dir / name).read_bytes()).hexdigest()
            for name in ('events.jsonl', 'stderr.log', 'final.txt')}
        return self.guard_result.copy()

    def call(self, **kwargs):
        return transport.call_model(self.prompt, self.schema, self.run, self.config, **kwargs)

    def test_command_config_fingerprint_and_finish_equal_original_contract(self):
        with patch.object(transport.time, "monotonic", side_effect=[100.0, 102.125]):
            result = self.call()
        schema_text = json.dumps(self.schema, ensure_ascii=False, indent=2) + "\n"
        fingerprint = original._sha(self.prompt + "\n" + schema_text + "\n" + json.dumps(asdict(self.config), sort_keys=True))
        self.assertEqual(result["request_fingerprint"], fingerprint)
        self.assertEqual(result["duration_seconds"], 2.125)
        self.assertEqual(result["model_elapsed_seconds"], 2.125)
        self.assertIsNone(result["cli_version"])
        self.assertEqual(result["automatic_retries"], 0)
        self.assertEqual(result["output"], self.output)
        self.assertEqual(self.ledger.rows[1]["details"], original._finish_details(result, self.run / "result.json"))
        self.assertEqual(self.ledger.rows[0]["metadata"], {
            "request_fingerprint": fingerprint, "model": self.config.model,
            "timeout_seconds": self.config.timeout_seconds, "reasoning_effort": self.config.reasoning_effort,
            "prompt_characters": len(self.prompt), "prompt_character_limit": original.PROMPT_CHARACTER_LIMIT,
            "authorization_context": self.config.authorization_context})
        self.assertFalse(any("env" in path.name for path in self.run.rglob("*")))
        self.no_probe.assert_not_called()
        self.no_process.assert_not_called()

    def test_guard_unknown_preserves_reserve_and_has_no_result_or_finish(self):
        self.guard.side_effect = GuardError("receipt unavailable")
        with self.assertRaisesRegex(GuardError, "receipt unavailable"):
            self.call()
        self.assertEqual([row["event"] for row in self.ledger.rows], ["reserve"])
        self.assertTrue((self.run / "request.json").is_file())
        self.assertFalse((self.run / "result.json").exists())
        with self.assertRaises(FileNotFoundError):
            self.call(resume=True)
        with self.assertRaises(FileExistsError):
            self.call()
        self.assertEqual(self.guard.call_count, 1)

    def test_original_invalid_usage_is_failed_without_coercing_bool_to_known(self):
        self.events[0]["usage"]["input_tokens"] = True
        result = self.call()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_reason"], "invalid_usage_evidence")
        self.assertIsNone(result["usage"]["input_tokens"])
        self.assertEqual(result["usage_validation_errors"], original.summarize_events(self.events)["usage_validation_errors"])

    def test_original_unknown_usage_preserved(self):
        self.events[0]["usage"] = None
        result = self.call()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["usage_status"], "unknown")
        self.assertIsNone(result["usage"]["input_tokens"])

    def test_original_timeout_precedence_preserved(self):
        self.guard_result.update(command_returncode=-9, timed_out=True)
        result = self.call()
        self.assertEqual((result["status"], result["failure_reason"]), ("timeout", "model_call_timeout"))
        self.assertEqual(self.ledger.rows[-1]["status"], "timeout")

    def test_original_native_tools_failure_preserved(self):
        self.events.append({"type": "item.completed", "item": {"type": "shell_command"}})
        result = self.call()
        self.assertEqual(result["failure_reason"], "native_tool_isolation_violation")

    def test_completed_replay_verifies_lifecycle_before_reconciling_exact_finish(self):
        result = self.call()
        self.ledger.rows.pop()
        with patch.object(transport, "verify_lifecycle", return_value=self.guard_result.copy()) as verify:
            self.assertEqual(self.call(resume=True), result)
            self.assertEqual(self.call(resume=True), result)
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(self.guard.call_count, 1)
        self.assertEqual([row["event"] for row in self.ledger.rows], ["reserve", "finish"])
        self.assertEqual(self.ledger.rows[-1]["details"], original._finish_details(result, self.run / "result.json"))

    def test_invalid_lifecycle_never_completes_pending_ledger(self):
        self.call()
        self.ledger.rows.pop()
        with patch.object(transport, "verify_lifecycle", side_effect=GuardError("original receipt changed")):
            with self.assertRaises(GuardError):
                self.call(resume=True)
        self.assertEqual([row["event"] for row in self.ledger.rows], ["reserve"])
        self.assertEqual(self.guard.call_count, 1)

    def test_old_unsupervised_result_is_not_accepted_as_new_protocol(self):
        result = self.call()
        result.pop("process_guard")
        (self.run / "result.json").write_text(json.dumps(result))
        self.ledger.rows.pop()
        with patch.object(transport, "verify_lifecycle", return_value=self.guard_result.copy()):
            with self.assertRaises(ValueError):
                self.call(resume=True)
        self.assertEqual([row["event"] for row in self.ledger.rows], ["reserve"])

    def test_timeout_cap_and_prompt_cap_before_reservation(self):
        for value in (True, 180.1, 240, float("inf")):
            # A simple attribute namespace is unnecessary: ModelConfig's original
            # <=300 validation already rejects infinity before our new admission.
            with self.subTest(value=value), self.assertRaises(ValueError):
                cfg = transport.ModelConfig(timeout_seconds=value)
                transport.call_model(self.prompt, self.schema, self.run, cfg)
        with self.assertRaises(transport.PromptTooLarge):
            transport.call_model("x" * (transport.PROMPT_CHARACTER_LIMIT + 1), self.schema, self.run, self.config)
        self.assertEqual(self.ledger.rows, [])
        self.guard.assert_not_called()

    def assert_original_pending(self):
        self.assertEqual([row['event'] for row in self.ledger.rows], ['reserve'])

    def test_events_replaced_after_guard_return_rejected_before_result_and_finish(self):
        def replace(*args, **kwargs):
            result = self.fake_guard(*args, **kwargs)
            (self.run / 'events.jsonl').write_text('{"type":"turn.completed","usage":{"input_tokens":999,"output_tokens":1}}\n')
            return result
        self.guard.side_effect = replace
        with self.assertRaisesRegex(ValueError, 'original verified bytes'):
            self.call()
        self.assertFalse((self.run / 'result.json').exists())
        self.assert_original_pending()

    def test_semantically_equal_final_raw_replacement_rejected(self):
        def replace(*args, **kwargs):
            result = self.fake_guard(*args, **kwargs)
            (self.run / 'final.txt').write_text(' { "a" : 3 }\n')
            return result
        self.guard.side_effect = replace
        with self.assertRaisesRegex(ValueError, 'original verified bytes'):
            self.call()
        self.assertFalse((self.run / 'result.json').exists())
        self.assert_original_pending()

    def test_original_stderr_anchor_also_required(self):
        def replace(*args, **kwargs):
            result = self.fake_guard(*args, **kwargs)
            (self.run / 'stderr.log').write_bytes(b'late replacement')
            return result
        self.guard.side_effect = replace
        with self.assertRaisesRegex(ValueError, 'stderr.log'):
            self.call()
        self.assert_original_pending()

    def test_late_replacement_after_same_fd_read_still_fails_before_publication(self):
        original_read = transport._read_guarded_outputs
        captured = {}
        def replace(*args, **kwargs):
            raw = original_read(*args, **kwargs)
            captured.update(raw)
            (self.run / 'final.txt').write_text('{"a":777}')
            return raw
        with patch.object(transport, '_read_guarded_outputs', side_effect=replace):
            with self.assertRaisesRegex(ValueError, 'original verified bytes'):
                self.call()
        self.assertEqual(json.loads(captured['final.txt']), self.output)
        self.assertFalse((self.run / 'result.json').exists())
        self.assert_original_pending()

    def test_events_replaced_after_result_write_never_finish_new_usage(self):
        original_write = transport._write_json
        def replace(path, value):
            original_write(path, value)
            if path.name == 'result.json':
                (self.run / 'events.jsonl').write_text('{"type":"turn.completed","usage":{"input_tokens":999,"output_tokens":1}}\n')
        with patch.object(transport, '_write_json', side_effect=replace):
            with self.assertRaisesRegex(ValueError, 'original verified bytes'):
                self.call()
        saved = json.loads((self.run / 'result.json').read_text())
        self.assertEqual(saved['usage']['input_tokens'], 10)
        self.assertEqual(saved['output'], self.output)
        self.assert_original_pending()

    def test_replay_replacement_after_guard_verification_never_reconciles_finish(self):
        self.call()
        self.ledger.rows.pop()
        def replace(*args, **kwargs):
            (self.run / 'final.txt').write_text('{"a":777}')
            return self.guard_result.copy()
        with patch.object(transport, 'verify_lifecycle', side_effect=replace):
            with self.assertRaisesRegex(ValueError, 'original verified bytes'):
                self.call(resume=True)
        self.assert_original_pending()
        self.assertEqual(self.guard.call_count, 1)

    def test_replay_late_fence_before_finish_checks_original_events(self):
        self.call()
        self.ledger.rows.pop()
        original_read = transport._read_guarded_outputs
        def replace(*args, **kwargs):
            raw = original_read(*args, **kwargs)
            (self.run / 'events.jsonl').write_text('\n')
            return raw
        with patch.object(transport, 'verify_lifecycle', return_value=self.guard_result.copy()), \
                patch.object(transport, '_read_guarded_outputs', side_effect=replace):
            with self.assertRaisesRegex(ValueError, 'original verified bytes'):
                self.call(resume=True)
        self.assert_original_pending()

    def test_late_change_after_finish_is_reported_without_rewriting_original_finish(self):
        original_finish = self.ledger.finish
        def replace(call_id, status, details):
            original_finish(call_id, status, details)
            (self.run / 'final.txt').write_text('{"a":999}')
        with patch.object(self.ledger, 'finish', side_effect=replace):
            with self.assertRaisesRegex(ValueError, 'original verified bytes'):
                self.call()
        self.assertEqual([row['event'] for row in self.ledger.rows], ['reserve', 'finish'])
        self.assertEqual(self.ledger.rows[-1]['details']['usage']['input_tokens'], 10)
        self.assertEqual(json.loads((self.run / 'result.json').read_text())['output'], self.output)

    def test_parse_original_event_bytes_preserves_old_newline_and_malformed_behavior(self):
        raw = b'{"type":"turn.completed","usage":null}\r\n\xffbad\r\n\r\n'
        path = self.run.parent / 'old-events.jsonl'
        path.write_bytes(raw)
        self.assertEqual(transport._events_from_original_bytes(raw), original.read_events(path))


@unittest.skipUnless(os.name == 'posix', 'POSIX guard only')
class SyntheticSupervisedTransportCompositionTests(unittest.TestCase):
    """Real owner-pipe guard + benign Python command, fake ledger; no model."""
    def test_synthetic_command_stdin_raw_outputs_guard_and_finish_end_to_end(self):
        from src.smt_fullfab.model_process_guard import verify_lifecycle
        with tempfile.TemporaryDirectory(prefix='synthetic_supervised_composition_') as temp:
            run = Path(temp).resolve() / 'model_000'
            ledger = FakeLedger()
            prompt = '合成输入，只验证 stdin 原字节。\r\n'
            output = {'synthetic': True, 'input_sha256': hashlib.sha256(prompt.encode('utf-8')).hexdigest()}
            program = ("import sys,json,hashlib;from pathlib import Path;"
                       "raw=sys.stdin.buffer.read();"
                       f"Path({str(run / 'final.txt')!r}).write_bytes(json.dumps({{'synthetic':True,'input_sha256':hashlib.sha256(raw).hexdigest()}},separators=(',',':')).encode('utf-8'));"
                       "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':3,'output_tokens':5}}))")
            command = [sys.executable, '-c', program]
            cfg = transport.ModelConfig(timeout_seconds=5, ledger_path=str(Path(temp) / 'never-created-ledger'))
            schema = {'type': 'object', 'properties': {'synthetic': {'type': 'boolean'}, 'input_sha256': {'type': 'string'}}}
            with patch.object(transport, 'BudgetLedger', return_value=ledger), \
                    patch.object(transport, '_disabled_skills', return_value=[]), \
                    patch.object(transport, 'build_command', return_value=command):
                result = transport.call_model(prompt, schema, run, cfg)
            self.assertEqual(result['status'], 'success')
            self.assertEqual(result['output'], output)
            self.assertEqual(result['usage']['input_tokens'], 3)
            self.assertEqual(result['usage']['output_tokens'], 5)
            self.assertGreater(result['duration_seconds'], 0)
            self.assertEqual([r['event'] for r in ledger.rows], ['reserve', 'finish'])
            self.assertEqual(ledger.rows[-1]['details'], original._finish_details(result, run / 'result.json'))
            bound = verify_lifecycle(run, expected_command=command, expected_timeout=5,
                                     expected_call_id='fake-call', expected_fingerprint=result['request_fingerprint'],
                                     expected_evidence=result['process_guard'])
            self.assertEqual(bound['command_returncode'], 0)
            self.assertEqual((run / 'prompt.txt').read_bytes(), prompt.encode('utf-8'))
            for name in ('events.jsonl', 'stderr.log', 'final.txt'):
                self.assertEqual(bound['output_files_sha256'][name], hashlib.sha256((run / name).read_bytes()).hexdigest())
            self.assertFalse(Path(cfg.ledger_path).exists())


if __name__ == "__main__":
    unittest.main()
