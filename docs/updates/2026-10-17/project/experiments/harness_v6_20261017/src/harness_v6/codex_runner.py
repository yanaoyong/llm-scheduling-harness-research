"""POSIX Codex transport. Credentials must already work; never manages auth.

Only explicit environment names are inherited. model_seconds conservatively
uses elapsed wall time: the pinned JSONL contract has no model-time field.
"""
import os
from pathlib import Path
import signal
import subprocess
import time
from .session import RunResult


class CodexRunner:
    def __init__(self, binary, *, workdir, env_allowlist, stderr_path):
        self.binary = str(binary)
        self.workdir = str(Path(workdir).resolve())
        self.env = {k: os.environ[k] for k in env_allowlist if k in os.environ}
        self.stderr_path = Path(stderr_path)
        self._version = None

    def _execute(self, argv, prompt, timeout):
        start = time.monotonic()
        self.stderr_path.parent.mkdir(parents=True, exist_ok=True)
        with self.stderr_path.open('ab') as errors:
            process = subprocess.Popen([self.binary, *argv[1:]], cwd=self.workdir,
                env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=errors, start_new_session=True)
            expired = False
            try:
                output, _ = process.communicate(prompt.encode(), timeout=timeout)
            except subprocess.TimeoutExpired:
                expired = True
                self._signal(process.pid, signal.SIGTERM)
                try:
                    output, _ = process.communicate(timeout=0.5)
                except subprocess.TimeoutExpired:
                    self._signal(process.pid, signal.SIGKILL)
                    output, _ = process.communicate()
                finally:
                    # Descendants may ignore TERM even after the leader exits.
                    self._signal(process.pid, signal.SIGKILL)
        wall = time.monotonic() - start
        return RunResult(output.decode('utf-8', errors='replace'), process.returncode,
                         wall, expired, wall)

    @staticmethod
    def _signal(group, sig):
        try:
            os.killpg(group, sig)
        except ProcessLookupError:
            pass

    def version(self, expected=None):
        if self._version is None:
            result = self._execute([self.binary, '--version'], '', 10)
            if result.returncode or result.timed_out or not result.jsonl.strip():
                raise ValueError('cannot determine Codex version')
            self._version = result.jsonl.strip()
        if expected is not None and self._version != expected:
            raise ValueError('codex_version mismatch: ' + self._version)
        return self._version

    def run(self, argv, prompt, *, timeout):
        return self._execute(argv, prompt, timeout)
