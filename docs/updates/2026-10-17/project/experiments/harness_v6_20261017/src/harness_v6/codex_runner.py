"""POSIX Codex transport. Credentials must already work; never manages auth.

Only explicit environment names are inherited. model_seconds conservatively
uses elapsed wall time: the pinned JSONL contract has no model-time field.
"""
import json
import os
from pathlib import Path
import selectors
import signal
import shutil
import subprocess
import time
from .session import RunResult


class CodexRunner:
    def __init__(self, binary, *, workdir, env_allowlist, stderr_path):
        candidate = os.fspath(binary)
        # Explicit paths are relative to the caller, before subprocess cwd changes.
        resolved = shutil.which(candidate) if '/' not in candidate else candidate
        if resolved is None or not Path(resolved).is_file():
            raise ValueError(f'Codex binary does not exist: {candidate}')
        path = Path(resolved).resolve()
        if not os.access(path, os.X_OK):
            raise ValueError(f'Codex binary is not executable: {path}')
        self.binary = str(path)
        self.workdir = str(Path(workdir).resolve())
        self.env = {k: os.environ[k] for k in env_allowlist if k in os.environ}
        self.stderr_path = Path(stderr_path)
        self._version = None

    def _execute(self, argv, prompt, timeout):
        marker = None
        for arg in argv:
            if arg.startswith('mcp_servers.harness_v6.args='):
                args = json.loads(arg.split('=', 1)[1])
                if '--output' in args:
                    marker = Path(args[args.index('--output')+1])/'abort.json'
        start = time.monotonic()
        self.stderr_path.parent.mkdir(parents=True, exist_ok=True)
        with self.stderr_path.open('ab') as errors:
            process = subprocess.Popen([self.binary, *argv[1:]], cwd=self.workdir,
                env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=errors, start_new_session=True)
            expired = False
            chunks = []
            pending = memoryview(prompt.encode())
            # Pipe EOF belongs to all descendants, not just the session leader.
            # Nonblocking I/O keeps both prompt writes and output drains bounded.
            with selectors.DefaultSelector() as selector:
                os.set_blocking(process.stdout.fileno(), False)
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdout, selectors.EVENT_READ)
                if pending:
                    selector.register(process.stdin, selectors.EVENT_WRITE)
                else:
                    process.stdin.close()

                def pump(wait):
                    nonlocal pending
                    for key, _ in selector.select(wait):
                        if key.fileobj is process.stdout:
                            data = os.read(process.stdout.fileno(), 65536)
                            if data:
                                chunks.append(data)
                            else:
                                selector.unregister(process.stdout)
                        else:
                            try:
                                pending = pending[os.write(process.stdin.fileno(), pending[:65536]):]
                            except BrokenPipeError:
                                pending = memoryview(b'')
                            if not pending:
                                selector.unregister(process.stdin)
                                process.stdin.close()

                try:
                    deadline = start + timeout
                    while process.poll() is None:
                        remaining = deadline - time.monotonic()
                        if (marker is not None and marker.exists()) or remaining <= 0:
                            expired = process.poll() is None
                            break
                        pump(min(.02, remaining))
                    if expired:
                        self._signal(process.pid, signal.SIGTERM)
                        grace = time.monotonic() + .5
                        while process.poll() is None and time.monotonic() < grace:
                            pump(.02)
                finally:
                    # Also clean up successful leaders' TERM-ignoring children.
                    self._signal(process.pid, signal.SIGKILL)
                    process.wait()
                    drain_deadline = time.monotonic() + .5
                    while selector.get_map() and time.monotonic() < drain_deadline:
                        pump(.02)
                    process.stdout.close()
                    process.stdin.close()
            output = b''.join(chunks)
        wall = time.monotonic() - start
        # A marker remains fatal even if the leader exited between polls.
        expired |= marker is not None and marker.exists()
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
