"""Additional real process-death, timeout, fork and resource negative controls."""
from copy import deepcopy
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab.harness.contracts import ROOT, HarnessError, default_config, encode
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.adapters import frozen_policy_action
from tests.test_smt_fullfab_harness import wait_delta, one_task, propose, apply


class PersistentFaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="harness-process-tests-"))
        cls.template = cls.root / "template"
        config = default_config(seconds=1800)
        config["period_seconds"] = 60
        r = Runtime.start_new(cls.template, config, experiment_id="offline-process-faults")
        r.close()

    def setUp(self):
        self.path = self.root / self._testMethodName
        shutil.copytree(self.template, self.path)
        self.r = Runtime.resume_run(self.path)

    def tearDown(self):
        self.r.close()

    def child_exit(self, point, operation, data=None):
        self.r.close()
        payload = self.path / "child_action.json"
        payload.write_bytes(encode(data))
        code = """import os,sys,json
from src.smt_fullfab.harness.runtime import Runtime
r=Runtime.resume_run(sys.argv[1])
def fault(point):
    if point == sys.argv[2]: os._exit(73)
r.store.fault=fault
if sys.argv[3] == 'advance': r.advance()
else: r.record_output(json.load(open(sys.argv[4])))
raise RuntimeError('fault point not reached')
"""
        done = subprocess.run([sys.executable, "-c", code, str(self.path), point, operation, str(payload)], cwd=ROOT, capture_output=True)
        self.assertEqual(done.returncode, 73, done.stderr.decode())
        self.r = Runtime.resume_run(self.path)

    def test_T16_actual_process_exit_after_durable_response(self):
        action = {"tool": "propose_delta", "request_id": "child", "context_ref": self.r.head["context_ref"], "delta": wait_delta(self.r, tasks=[one_task(self.r)])}
        self.child_exit("after_response_saved", "action", action)
        self.assertEqual(len(self.r.store.rows("attempts")), 1)
        candidate = self.r.store.rows("candidates")[0][0]
        apply(self.r, candidate)
        self.assertGreater(self.r.advance()["dispatch_count_delta"], 0)

    def test_T17_actual_process_exit_after_acceptance(self):
        candidate = propose(self.r, wait_delta(self.r, tasks=[one_task(self.r)]))["candidate_ref"]
        action = {"tool": "apply_candidate", "request_id": "child", "context_ref": self.r.head["context_ref"], "candidate_ref": candidate}
        self.child_exit("after_commit_before_receipt", "action", action)
        self.assertEqual(self.r.record_output(action)["status"], "accepted")
        self.assertEqual(len(self.r.store.rows("commits")), 1)
        self.assertEqual(self.r.advance()["dispatch_count_delta"], 1)

    def test_T18_actual_process_exit_mid_transaction_and_export(self):
        candidate = propose(self.r, wait_delta(self.r, tasks=[one_task(self.r)]))["candidate_ref"]
        apply(self.r, candidate)
        start = self.r.head["state_ref"]
        self.child_exit("during_physical_persist", "advance")
        self.assertEqual(self.r.head["state_ref"], start)
        self.child_exit("during_trace_export", "advance")
        events = self.r.store.trace()
        self.assertEqual([e["seq"] for e in events], list(range(len(events))))
        self.assertEqual(sum(e["kind"] == "dispatch" and e.get("plan_task_id") == "fixture-w1387" for e in events), 1)
        self.assertEqual(self.r.env.t, 60)

    def test_T03_readding_dispatched_operation_is_rejected(self):
        task = one_task(self.r)
        apply(self.r, propose(self.r, wait_delta(self.r, tasks=[task]))["candidate_ref"])
        self.r.advance()
        task["id"] = "reuse-dispatched"
        task["not_before"] = 60
        result = propose(self.r, wait_delta(self.r, version="reused", tasks=[task]), "second")
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(len(self.r.store.rows("commits")), 1)

    def test_T22_repeated_zero_progress_ignores_version_renaming(self):
        for i in range(3):
            delta = wait_delta(self.r, version="renamed-" + str(i))
            delta["holds"]["add"] = []
            apply(self.r, propose(self.r, delta, "p" + str(i))["candidate_ref"], "a" + str(i))
            self.r.advance()
        self.assertEqual(self.r.head["phase"], "STOPPED")
        self.assertEqual(self.r.head["stop_reason"], "production_no_progress")

    def test_T28_repeated_same_error_stops_without_new_output(self):
        for i in range(3):
            result = self.r.record_output({"tool": "not-an-authorized-tool"})
            self.assertEqual(result["status"], "rejected")
        self.assertEqual(self.r.head["stop_reason"], "repeated_identical_error")
        count = len(self.r.store.rows("attempts"))
        with self.assertRaisesRegex(HarnessError, "stopped"):
            self.r.record_output({"tool": "get_context", "context_ref": self.r.head["context_ref"]})
        self.assertEqual(len(self.r.store.rows("attempts")), count)

    def test_T26_real_timeout_no_result_and_unknown_no_reexecution(self):
        self.r.close()
        self.path = self.root / "classical-timeout"
        self.r = Runtime.start_new(self.path, default_config("C-fixed", seconds=60), experiment_id="offline-timeout", mode="policy")
        real_run = subprocess.run
        def timeout_worker(*args, **kwargs):
            # Replace only the worker program with a real sleeping process;
            # persistence, TimeoutExpired handling and accounting stay real.
            return real_run([sys.executable, "-c", "import time; time.sleep(5)"], capture_output=True, timeout=.03)
        action = frozen_policy_action(self.r)
        with patch("src.smt_fullfab.harness.adapters.subprocess.run", side_effect=timeout_worker):
            result = self.r.record_output(action, channel="policy")
        self.assertEqual(result["solver_status"], "TIMEOUT")
        self.assertEqual(len(self.r.store.rows("candidates")), 0)
        with patch("src.smt_fullfab.harness.adapters.subprocess.run", side_effect=lambda *a, **k: real_run([sys.executable, "-c", "pass"], capture_output=True)):
            action["request_id"] = "no-result"
            result = self.r.record_output(action, channel="policy")
        self.assertEqual(result["solver_status"], "NO_RESULT")
        # A durable in-flight worker result stays unknown and is never restarted.
        aid = self.r.reserve_attempt("offline UNKNOWN", {}, channel="policy")
        self.r.mark_started(aid)
        action["request_id"] = "unknown"
        self.r.save_response(aid, encode(action), usage={"input_tokens": 0, "output_tokens": 0}, duration_seconds=0)
        with self.r.store.transaction():
            self.r.store.record("classical_attempts", aid, {"attempt_id": aid, "status": "started", "budget_seconds": 5})
        with patch("src.smt_fullfab.harness.adapters.subprocess.run", side_effect=AssertionError("must not retry")):
            result = self.r.process(aid)
        self.assertEqual(result["solver_status"], "UNKNOWN")
        self.assertEqual(self.r.store.rows("candidates"), [])

    def test_T27_real_fork_entry_keeps_nonzero_frozen_inprocess_state(self):
        task = one_task(self.r)
        delta = wait_delta(self.r, tasks=[task])
        delta["plan_header"]["freeze_until"] = 100
        apply(self.r, propose(self.r, delta)["candidate_ref"])
        self.r.advance()
        self.r.record_output({"tool": "write_notes", "request_id": "notes", "context_ref": self.r.head["context_ref"], "expected_version": 0, "text": "parent-private-notes"})
        initial = self.r.head["state_ref"]
        self.r.close()
        for arm in ("A", "B", "C", "C-fixed"):
            cfg = default_config(arm, seconds=1740)
            cfg["initialization"] = "registered_common_snapshot"
            branch = Runtime.fork_scenario(self.path, self.root / ("real-fork-" + arm), cfg, experiment_id="offline-fork")
            self.assertEqual(branch.manifest["initial_state_sha256"], initial)
            self.assertEqual(branch.env.plan["freeze_until"], 100)
            self.assertEqual(branch.manifest["period_anchor"], 60)
            self.assertEqual(branch.context()["notes"]["text"], "")
            branch.close()
        self.r = Runtime.resume_run(self.path)

    def test_T28_every_resource_limit_prevents_new_attempt(self):
        count = len(self.r.store.rows("attempts"))
        for field in ("attempt_budget", "token_budget", "time_budget", "unknown_attempt", "wall_budget", "storage_budget"):
            original = deepcopy(self.r.manifest)
            self.r.manifest["mode"] = "model"  # No transport invoked in this negative control.
            usage = self.r.usage()
            if field == "attempt_budget": usage["actual_model_attempts"] = self.r.config["limits"]["attempts"]
            if field == "token_budget": usage["input_tokens"] = self.r.config["limits"]["tokens"]
            if field == "time_budget": usage["model_seconds"] = self.r.config["limits"]["model_seconds"]
            if field == "unknown_attempt": usage["unknown_usage"] = 1
            if field == "wall_budget": self.r.manifest["deadline_epoch"] = 0
            if field == "storage_budget": self.r.config["limits"]["storage_bytes"] = 1
            with patch.object(self.r, "usage", return_value=usage):
                with self.assertRaisesRegex(HarnessError, field):
                    self.r.reserve_attempt("never sent", {})
            self.r.manifest = original
            self.r.config = original["config"]
        self.assertEqual(len(self.r.store.rows("attempts")), count)


if __name__ == "__main__":
    unittest.main()
