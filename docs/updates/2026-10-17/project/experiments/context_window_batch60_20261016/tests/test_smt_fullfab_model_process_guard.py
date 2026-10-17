"""BENIGN POSIX subprocess tests. Never run a model, factory, solver, or ledger.

Authored for an explicit serial test window; no test has been run by its author.
All subprocesses below are sys.executable with small standard-library programs.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from src.smt_fullfab import model_process_guard as guard


@unittest.skipUnless(os.name == "posix", "POSIX guard only")
class ModelProcessGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="guard_benign_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.run = self.root / "call"
        self.run.mkdir()
        (self.run / "isolated-cwd").mkdir()
        self.command = [sys.executable, "-c", "print('benign')"]
        for name in guard.INPUT_FILES:
            (self.run / name).write_text("fixture\n", encoding="utf-8")
        self.pid = "synthetic-call"
        self.fingerprint = "c" * 64

    def invoke(self, command=None, timeout=2):
        self.command = command or self.command
        (self.run / "command.json").write_text(json.dumps({"argv": self.command}))
        return guard.run_guarded(self.command, run_dir=self.run, timeout_seconds=timeout,
                                 env=os.environ.copy(), call_id=self.pid,
                                 request_fingerprint=self.fingerprint)

    def read(self, name):
        return json.loads((self.run / "process_guard" / name).read_text())

    def verify(self, evidence=None, timeout=2):
        return guard.verify_lifecycle(self.run, expected_command=self.command,
                                      expected_timeout=timeout, expected_call_id=self.pid,
                                      expected_fingerprint=self.fingerprint,
                                      expected_evidence=evidence)

    def wait_file(self, path, seconds=5):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            if path.is_file() and path.stat().st_size:
                return
            time.sleep(.01)
        self.fail(f"No bounded fixture marker: {path}")

    @staticmethod
    def running(pid):
        # Zombies cannot execute; macOS has no /proc. ps is a bounded benign tool.
        result = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                                text=True, capture_output=True, timeout=2)
        state = result.stdout.strip()
        return bool(state) and not state.startswith("Z")

    def wait_stopped(self, pid):
        until = time.monotonic() + 5
        while time.monotonic() < until:
            if not self.running(pid):
                return
            time.sleep(.02)
        self.fail(f"Benign fixture process remains running: {pid}")

    def test_normal_exit_maps_command_zero_not_guard_sigkill(self):
        evidence = self.invoke()
        self.assertEqual(evidence["command_returncode"], 0)
        self.assertEqual(evidence["guard_returncode"], -signal.SIGKILL)
        self.assertEqual(self.read("started.json")["guard_pid"], evidence["guard_pgid"])
        self.assertEqual((self.run / "events.jsonl").read_bytes(), b"benign\n")
        self.assertEqual(self.verify(evidence), evidence)

    def test_nonzero_command_returncode_preserved(self):
        evidence = self.invoke([sys.executable, "-c", "raise SystemExit(17)"])
        self.assertEqual(evidence["command_returncode"], 17)
        self.assertFalse(evidence["timed_out"])

    def test_command_exec_resets_term_handler_and_does_not_inherit_owner_pipe(self):
        program = """import json,os,signal
from pathlib import Path
s=json.loads(Path('../process_guard/started.json').read_text())
try: os.fstat(s['owner_fd']); closed=False
except OSError: closed=True
print(json.dumps({'pipe_closed':closed,'pgid':os.getpgrp(),'term_default':signal.getsignal(signal.SIGTERM)==signal.SIG_DFL}))
"""
        evidence = self.invoke([sys.executable, "-c", program])
        facts = json.loads((self.run / "events.jsonl").read_text())
        self.assertTrue(facts["pipe_closed"])
        self.assertTrue(facts["term_default"])
        self.assertEqual(facts["pgid"], evidence["guard_pid"])

    def test_timeout_kills_term_ignoring_direct_cli(self):
        command = [sys.executable, "-c", "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)"]
        evidence = self.invoke(command, timeout=.5)
        self.assertTrue(evidence["timed_out"])
        self.assertEqual(evidence["command_returncode"], -signal.SIGKILL)
        self.assertEqual(self.verify(evidence, timeout=.5), evidence)

    def descendant_command(self):
        child = "import os,signal,time;from pathlib import Path;signal.signal(signal.SIGTERM,signal.SIG_IGN);Path('descendant.pid').write_text(str(os.getpid()));time.sleep(60)"
        program = f"""import subprocess,sys,time
from pathlib import Path
subprocess.Popen([sys.executable,'-c',{child!r}])
end=time.monotonic()+3
while not Path('descendant.pid').exists() and time.monotonic()<end:time.sleep(.01)
"""
        return [sys.executable, "-c", program]

    def test_normal_direct_exit_still_cleans_unknown_descendant(self):
        evidence = self.invoke(self.descendant_command(), timeout=5)
        descendant = int((self.run / "isolated-cwd/descendant.pid").read_text())
        self.assertEqual(evidence["command_returncode"], 0)
        self.wait_stopped(descendant)

    def test_receipt_io_failure_still_kills_guard_and_descendant(self):
        original = guard._write_new
        processes = []
        original_popen = guard.subprocess.Popen

        def marker(path, value):
            saved = original(path, value)
            if Path(path).name == "launch.json":
                (self.run / "process_guard/receipt.json").mkdir()
            return saved

        def popen(*args, **kwargs):
            p = original_popen(*args, **kwargs)
            processes.append(p)
            return p

        with patch.object(guard, "_write_new", side_effect=marker), patch.object(guard.subprocess, "Popen", side_effect=popen):
            with self.assertRaises((guard.GuardError, OSError)):
                self.invoke(self.descendant_command(), timeout=5)
        self.assertEqual(processes[0].returncode, -signal.SIGKILL)
        descendant = int((self.run / "isolated-cwd/descendant.pid").read_text())
        self.wait_stopped(descendant)
        self.assertFalse((self.run / "process_guard/parent_observed.json").exists())

    def test_guard_started_marker_failure_forbids_command_launch(self):
        original = guard._write_new
        marker_path = self.run / "cli-must-not-start"

        def marker(path, value):
            result = original(path, value)
            if Path(path).name == "launch.json":
                (self.run / "process_guard/started.json").mkdir()
            return result

        with patch.object(guard, "_write_new", side_effect=marker):
            with self.assertRaises((guard.GuardError, OSError)):
                self.invoke([sys.executable, "-c", f"from pathlib import Path;Path({str(marker_path)!r}).touch()"])
        self.assertFalse(marker_path.exists())

    def test_parent_pid_marker_failure_withholds_startup_permission(self):
        original = guard._write_new
        processes = []
        original_popen = guard.subprocess.Popen

        def marker(path, value):
            if Path(path).name == "parent_started.json":
                raise OSError("synthetic PID marker failure")
            return original(path, value)

        def popen(*args, **kwargs):
            p = original_popen(*args, **kwargs)
            processes.append(p)
            return p

        with patch.object(guard, "_write_new", side_effect=marker), patch.object(guard.subprocess, "Popen", side_effect=popen):
            with self.assertRaisesRegex(OSError, "PID marker"):
                self.invoke()
        self.assertEqual(processes[0].returncode, -signal.SIGKILL)
        self.assertFalse((self.run / "process_guard/command_started.json").exists())
        self.assertEqual((self.run / "events.jsonl").read_bytes(), b"")

    def launch_outer(self, *, startup_gap):
        source = str(Path(guard.__file__).resolve())
        ready = self.root / "outer_ready.json"
        program = f"""import importlib.util,json,os,time
from pathlib import Path
spec=importlib.util.spec_from_file_location('isolated_guard',{source!r})
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
run=Path({str(self.run)!r})
original=g._write_new
startup_gap={startup_gap!r}
def write(path,value):
    if startup_gap and Path(path).name=='parent_started.json':
        Path({str(ready)!r}).write_text(json.dumps(value))
        while True:time.sleep(.02)
    return original(path,value)
g._write_new=write
command=[{sys.executable!r},'-c',"import time;time.sleep(60)"]
g.run_guarded(command,run_dir=run,timeout_seconds=8,env=os.environ.copy(),call_id='synthetic-call',request_fingerprint={'c'*64!r})
"""
        outer = subprocess.Popen([sys.executable, "-c", program], start_new_session=True,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def cleanup():
            if outer.poll() is None:
                os.killpg(outer.pid, signal.SIGKILL)
                outer.wait(timeout=5)
            started = self.run / "process_guard/started.json"
            if started.is_file():
                pid = json.loads(started.read_text())["guard_pid"]
                if self.running(pid):
                    os.killpg(pid, signal.SIGKILL)
        self.addCleanup(cleanup)
        return outer, ready

    def test_owner_dies_in_popen_to_pid_record_gap_no_command_starts(self):
        outer, ready = self.launch_outer(startup_gap=True)
        self.wait_file(ready)
        self.wait_file(self.run / "process_guard/started.json")
        pid = json.loads(ready.read_text())["guard_pid"]
        os.killpg(outer.pid, signal.SIGKILL)
        outer.wait(timeout=5)
        self.wait_file(self.run / "process_guard/receipt.json")
        receipt = self.read("receipt.json")
        self.assertTrue(receipt["owner_eof"])
        self.assertIsNone(receipt["command_pid"])
        self.wait_stopped(pid)
        self.assertFalse((self.run / "process_guard/parent_observed.json").exists())

    def test_outer_process_group_killed_guard_group_cleans_live_cli(self):
        outer, _ = self.launch_outer(startup_gap=False)
        self.wait_file(self.run / "process_guard/command_started.json")
        started = self.read("command_started.json")
        self.assertNotEqual(started["guard_pid"], outer.pid)
        os.killpg(outer.pid, signal.SIGKILL)
        outer.wait(timeout=5)
        self.wait_file(self.run / "process_guard/receipt.json")
        self.assertTrue(self.read("receipt.json")["owner_eof"])
        self.wait_stopped(started["command_pid"])
        self.wait_stopped(started["guard_pid"])
        self.assertFalse((self.run / "process_guard/parent_observed.json").exists())

    def test_readback_missing_wait_or_changed_receipt_rejected(self):
        evidence = self.invoke()
        observed = self.run / "process_guard/parent_observed.json"
        raw = observed.read_bytes()
        observed.unlink()
        with self.assertRaises((OSError, guard.GuardError)):
            self.verify(evidence)
        observed.write_bytes(raw)
        path = self.run / "process_guard/receipt.json"
        receipt = json.loads(path.read_text())
        receipt["command_returncode"] = 19
        path.write_text(json.dumps(receipt))
        with self.assertRaises(guard.GuardError):
            self.verify(evidence)

    def test_result_reanchor_after_semantic_verification_is_rejected(self):
        evidence = self.invoke()
        original = guard._read_terminal

        def replace(*args, **kwargs):
            result = original(*args, **kwargs)
            path = self.run / "process_guard/launch.json"
            item = json.loads(path.read_text())
            item["writer_inheritable"] = True
            path.write_text(json.dumps(item))
            return result

        with patch.object(guard, "_read_terminal", side_effect=replace):
            with self.assertRaises(guard.GuardError):
                self.verify(evidence)

    def test_repeat_attempt_cannot_overwrite_lifecycle(self):
        self.invoke()
        before = (self.run / "process_guard/spec.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.invoke()
        self.assertEqual(before, (self.run / "process_guard/spec.json").read_bytes())

    def test_illegal_timeout_rejected_before_process_directory(self):
        for value in (True, 0, -1, float("nan"), float("inf"), "1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.invoke(timeout=value)
            self.assertFalse((self.run / "process_guard").exists())

    def test_generic_phase_supports_finite_long_deadline_and_explicit_io(self):
        phase = self.root / "phase"
        phase.mkdir()
        approved = phase / "approved.json"
        approved.write_text('{"phase":"benign-generic"}\n')
        io = {"cwd": str(phase), "stdin": None,
              "stdout": str(phase / "stdout.log"), "stderr": str(phase / "stderr.log"),
              "inputs": {"approved": str(approved)},
              "outputs": {"stdout": str(phase / "stdout.log"), "stderr": str(phase / "stderr.log")}}
        command = [sys.executable, "-c", "print('generic no model')"]
        evidence = guard.run_guarded(command, run_dir=phase, timeout_seconds=46800,
                                     env=os.environ.copy(), call_id="outer-phase", request_fingerprint="f" * 64,
                                     io_spec=io)
        self.assertEqual(evidence["command_returncode"], 0)
        self.assertEqual(evidence["io_spec"], io)
        self.assertIsInstance(evidence["command_peak_rss_bytes"], int)
        self.assertIsInstance(evidence["guard_peak_rss_bytes"], int)
        self.assertGreaterEqual(evidence["parent_wait_wall_seconds"], 0)
        self.assertEqual(evidence, guard.verify_lifecycle(
            phase, expected_command=command, expected_timeout=46800, expected_call_id="outer-phase",
            expected_fingerprint="f" * 64, expected_io_spec=io, expected_evidence=evidence))
        changed = dict(io, cwd=str(self.root))
        with self.assertRaises(guard.GuardError):
            guard.verify_lifecycle(phase, expected_command=command, expected_timeout=46800,
                                   expected_call_id="outer-phase", expected_fingerprint="f" * 64,
                                   expected_io_spec=changed)

    def test_generic_io_omission_and_alias_are_rejected_before_launch(self):
        with self.assertRaises(ValueError):
            guard.run_guarded(self.command, run_dir=self.run, timeout_seconds=600,
                              env={}, call_id=self.pid, request_fingerprint=self.fingerprint,
                              io_spec={"cwd": str(self.root)})
        self.assertFalse((self.run / "process_guard").exists())

    def test_owner_chain_cleans_nested_new_session_guard(self):
        inner = self.root / "inner"
        inner.mkdir()
        (inner / "approved.json").write_text('{"purpose":"nested benign"}\n')
        io = {"cwd": str(inner), "stdin": None,
              "stdout": str(inner / "stdout.log"), "stderr": str(inner / "stderr.log"),
              "inputs": {"approved": str(inner / "approved.json")},
              "outputs": {"stdout": str(inner / "stdout.log"), "stderr": str(inner / "stderr.log")}}
        source = str(Path(guard.__file__).resolve())
        load = f"import importlib.util,os;from pathlib import Path;s=importlib.util.spec_from_file_location('g',{source!r});g=importlib.util.module_from_spec(s);s.loader.exec_module(g);"
        leaf = [sys.executable, "-c", "import time;time.sleep(60)"]
        worker = load + f"g.run_guarded({leaf!r},run_dir={str(inner)!r},timeout_seconds=8,env=os.environ.copy(),call_id='inner',request_fingerprint={'b'*64!r},io_spec={io!r})"
        outer_command = [sys.executable, "-c", worker]
        parent_program = load + f"g.run_guarded({outer_command!r},run_dir={str(self.run)!r},timeout_seconds=9,env=os.environ.copy(),call_id={self.pid!r},request_fingerprint={self.fingerprint!r})"
        parent = subprocess.Popen([sys.executable, "-c", parent_program], start_new_session=True,
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.wait_file(inner / "process_guard/command_started.json")
            first = self.read("command_started.json")
            second = json.loads((inner / "process_guard/command_started.json").read_text())
            self.assertNotEqual(first["guard_pid"], second["guard_pid"])
            os.killpg(parent.pid, signal.SIGKILL)
            parent.wait(timeout=5)
            self.wait_file(inner / "process_guard/receipt.json")
            self.assertTrue(json.loads((inner / "process_guard/receipt.json").read_text())["owner_eof"])
            self.wait_stopped(second["command_pid"])
            self.wait_stopped(second["guard_pid"])
            self.wait_stopped(first["guard_pid"])
        finally:
            if parent.poll() is None:
                os.killpg(parent.pid, signal.SIGKILL)
                parent.wait(timeout=5)
            for directory in (self.run, inner):
                path = directory / "process_guard/started.json"
                if path.is_file():
                    pid = json.loads(path.read_text())["guard_pid"]
                    if self.running(pid):
                        os.killpg(pid, signal.SIGKILL)

    def test_cleanup_wait_failure_preserves_primary_baseexception_and_diagnostic(self):
        directory = self.root / "cleanup"
        directory.mkdir()
        primary = KeyboardInterrupt("synthetic interrupted owner")
        with patch.object(guard.os, "close"), patch.object(guard, "_bounded_reap", side_effect=OSError("synthetic wait4 failure")):
            try:
                try:
                    raise primary
                finally:
                    guard._release_owner_and_reap(object(), 99998, 99999, sys.exc_info()[1], directory)
            except BaseException as caught:
                self.assertIs(caught, primary)
        self.assertTrue(any("wait4 failure" in note for note in primary.__notes__))
        saved = json.loads((directory / "cleanup_errors.json").read_text())
        self.assertEqual(saved["primary_error_type"], "KeyboardInterrupt")
        self.assertFalse(saved["lifecycle_complete"])

    def test_cleanup_kill_failure_preserves_primary_without_signalling_real_pid(self):
        from types import SimpleNamespace
        directory = self.root / "cleanup-kill"
        directory.mkdir()
        primary = guard.GuardError("original missing receipt")
        process = SimpleNamespace(pid=99997, args=["never-executed"], returncode=None)
        with patch.object(guard.os, "close"), \
                patch.object(guard, "_wait4", side_effect=subprocess.TimeoutExpired("fake", 1)), \
                patch.object(guard, "_poll_wait4", return_value=None), \
                patch.object(guard.os, "killpg", side_effect=PermissionError("synthetic kill failure")) as kill:
            try:
                try:
                    raise primary
                finally:
                    guard._release_owner_and_reap(process, None, 99999, sys.exc_info()[1], directory)
            except BaseException as caught:
                self.assertIs(caught, primary)
            kill.assert_called_once_with(99997, signal.SIGKILL)
        self.assertTrue(any("kill failure" in note for note in primary.__notes__))

    def test_cleanup_failure_on_otherwise_normal_path_rejects_success(self):
        directory = self.root / "cleanup-normal"
        directory.mkdir()
        with patch.object(guard.os, "close"), patch.object(guard, "_bounded_reap", side_effect=OSError("synthetic wait failure")):
            with self.assertRaises(guard.GuardError):
                guard._release_owner_and_reap(object(), None, 99999, None, directory)

    def test_cleanup_diagnostic_failure_does_not_override_primary(self):
        primary = ValueError("original failure")
        with patch.object(guard.os, "close", side_effect=OSError("close failure")), \
                patch.object(guard, "_write_new", side_effect=OSError("diagnostic failure")):
            guard._release_owner_and_reap(None, None, 99999, primary, self.root)
        self.assertTrue(any("diagnostic failure" in note for note in primary.__notes__))


if __name__ == "__main__":
    unittest.main()
