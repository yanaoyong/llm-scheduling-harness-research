"""POSIX owner-pipe guard for one explicitly supplied command.

No model, budget, or environment-snapshot code belongs here. A separate guard
session owns the command's process group. The command does not inherit the owner
pipe. Success requires a terminal receipt AND the parent's completed wait.
This is process-group containment, not a sandbox against setsid()/setpgid().
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import select
import signal
import stat
import subprocess
import sys
import time

PROTOCOL = "smt-model-process-guard-v1"
MAX_METADATA_BYTES = 8 * 1024 * 1024
TERM_GRACE_SECONDS = 1.0
DIRECT_KILL_WAIT_SECONDS = 1.0
PARENT_MARGIN_SECONDS = 3.0
INPUT_FILES = ("request.json", "command.json", "attempt.claim", "prompt.txt",
               "schema.json", "system-instructions.txt")
OUTPUT_FILES = ("events.jsonl", "stderr.log", "final.txt")
CORE_FILES = ("spec.json", "launch.json", "parent_started.json", "started.json", "receipt.json")


class GuardError(RuntimeError):
    """Lifecycle unknown/inconsistent: stop; never infer a model-call finish."""


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _encoded(value):
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def _identity(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def _raw(path):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise GuardError(f"Not a regular evidence file: {path.name}")
        if before.st_size > MAX_METADATA_BYTES:
            raise GuardError(f"Lifecycle metadata exceeds explicit size limit: {path.name}")
        chunks = []
        remaining = before.st_size
        while remaining:
            block = os.read(fd, min(1024 * 1024, remaining))
            if not block:
                raise GuardError(f"Evidence shortened while reading: {path.name}")
            chunks.append(block)
            remaining -= len(block)
        after = os.fstat(fd)
        if _identity(before) != _identity(after) or _identity(after) != _identity(path.stat()):
            raise GuardError(f"Evidence changed while reading: {path.name}")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _write_new(path, value):
    raw = _encoded(value)
    with Path(path).open("xb") as stream:
        if stream.write(raw) != len(raw):
            raise OSError("Short lifecycle evidence write")
        stream.flush()
        os.fsync(stream.fileno())
    return _sha(raw)


def _digest_file(path):
    # Output logs may be large. Hash incrementally, never join their bytes.
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise GuardError(f"Not a regular evidence file: {path.name}")
        digest = hashlib.sha256()
        remaining = before.st_size
        while remaining:
            block = os.read(fd, min(1024 * 1024, remaining))
            if not block:
                raise GuardError(f"Evidence shortened while hashing: {path.name}")
            digest.update(block)
            remaining -= len(block)
        after = os.fstat(fd)
        if _identity(before) != _identity(after) or _identity(after) != _identity(path.stat()):
            raise GuardError(f"Evidence changed while hashing: {path.name}")
        return digest.hexdigest()
    finally:
        os.close(fd)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _timeout(value):
    if not _number(value) or not value > 0:
        raise ValueError("Supervised command timeout must be finite and positive")


def _io_spec(run, supplied=None):
    if supplied is None:
        supplied = {"cwd": str(run / "isolated-cwd"), "stdin": str(run / "prompt.txt"),
                    "stdout": str(run / "events.jsonl"), "stderr": str(run / "stderr.log"),
                    "inputs": {name: str(run / name) for name in INPUT_FILES},
                    "outputs": {name: str(run / name) for name in OUTPUT_FILES}}
    # No permissive defaults/normalization in explicitly supplied phase evidence.
    if type(supplied) is not dict or set(supplied) != {"cwd", "stdin", "stdout", "stderr", "inputs", "outputs"}:
        raise ValueError("io_spec must explicitly contain cwd/stdin/stdout/stderr/inputs/outputs")
    value = json.loads(_encoded(supplied))
    for key in ("cwd", "stdout", "stderr"):
        if type(value[key]) is not str or not Path(value[key]).is_absolute():
            raise ValueError("io_spec paths must be absolute strings")
    if value["stdin"] is not None and (type(value["stdin"]) is not str or not Path(value["stdin"]).is_absolute()):
        raise ValueError("stdin must be an absolute path or null")
    for kind in ("inputs", "outputs"):
        if type(value[kind]) is not dict or not value[kind]:
            raise ValueError("io_spec requires nonempty explicit input/output mappings")
        if any(type(k) is not str or not k or type(v) is not str or not Path(v).is_absolute() for k, v in value[kind].items()):
            raise ValueError("io_spec evidence mappings must contain labels and absolute paths")
    inputs, outputs = set(value["inputs"].values()), set(value["outputs"].values())
    for path in inputs | outputs | {value["cwd"]}:
        if str(Path(path).resolve()) != path:
            raise ValueError("io_spec requires canonical paths, not aliases")
    if (len(outputs) != len(value["outputs"]) or value["stdout"] == value["stderr"]
            or not {value["stdout"], value["stderr"]} <= outputs or inputs & outputs
            or (value["stdin"] is not None and value["stdin"] not in inputs)):
        raise ValueError("io_spec stream/evidence paths overlap or are unbound")
    return value


def _inputs(io):
    return {name: _digest_file(path) for name, path in io["inputs"].items()}


def _outputs(io):
    return {name: _digest_file(path) if Path(path).exists() else None for name, path in io["outputs"].items()}


def _poll_wait4(proc):
    if proc.returncode is None:
        pid, status, usage = os.wait4(proc.pid, os.WNOHANG)
        if pid:
            proc.returncode = os.waitstatus_to_exitcode(status)
            proc.guard_peak_rss_bytes = int(usage.ru_maxrss) * (1 if sys.platform == "darwin" else 1024)
    return proc.returncode


def _wait4(proc, timeout):
    end = time.monotonic() + timeout
    while _poll_wait4(proc) is None:
        if time.monotonic() >= end:
            raise subprocess.TimeoutExpired(proc.args, timeout)
        time.sleep(min(.01, max(0, end - time.monotonic())))
    return proc.returncode


def _owner_read(fd):
    try:
        return os.read(fd, 4096)
    except BlockingIOError:
        return None


def _owner_eof(fd):
    data = _owner_read(fd)
    if data not in (None, b""):
        raise GuardError("Unexpected owner-pipe bytes after startup permission")
    return data == b""


def _signal_group(sig):
    # Only the guard calls this; its actual session/group identity is checked first.
    os.killpg(os.getpid(), sig)


def _guard_main(spec_path, owner_fd, expected_sha):
    """Standalone child entry; final group SIGKILL is intentional, even on error."""
    if os.name != "posix" or os.getpid() != os.getpgrp() or os.getsid(0) != os.getpid():
        return 2  # Never signal an inherited/unverified group.
    signal.signal(signal.SIGTERM, lambda *_: None)
    guard_pid = os.getpid()
    proc = None
    spec = None
    command_started = None
    command_finished = None
    returncode = None
    reason = "guard_error"
    error = None
    launch_error = None
    owner_eof = False
    timed_out = False
    started = time.monotonic()
    directory = Path(spec_path).parent
    try:
        if not stat.S_ISFIFO(os.fstat(owner_fd).st_mode):
            raise GuardError("Owner descriptor is not a pipe")
        os.set_inheritable(owner_fd, False)
        os.set_blocking(owner_fd, False)
        raw = _raw(spec_path)
        if _sha(raw) != expected_sha:
            raise GuardError("Original spec SHA differs")
        spec = json.loads(raw)
        if spec["schema"] != PROTOCOL or spec["guard_source_sha256"] != _sha(_raw(Path(__file__).resolve())):
            raise GuardError("Guard protocol/source differs")
        run = Path(spec["run_dir"])
        if directory != run / "process_guard":
            raise GuardError("Spec paths differ")
        io = _io_spec(run, spec["io_spec"])
        _timeout(spec["timeout_seconds"])
        if (not _number(spec["deadline_monotonic_seconds"])
                or spec["deadline_monotonic_seconds"] != spec["begun_monotonic_seconds"] + spec["timeout_seconds"]
                or spec["term_grace_seconds"] != TERM_GRACE_SECONDS
                or spec["direct_kill_wait_seconds"] != DIRECT_KILL_WAIT_SECONDS
                or type(spec["argv"]) is not list or not spec["argv"]
                or any(type(x) is not str for x in spec["argv"])):
            raise GuardError("Invalid command/deadline/cleanup spec")
        if _inputs(io) != spec["input_files_sha256"]:
            raise GuardError("Original input evidence changed before guard launch")
        _write_new(directory / "started.json", {
            "schema": PROTOCOL, "spec_sha256": expected_sha, "guard_pid": guard_pid,
            "guard_pgid": os.getpgrp(), "guard_sid": os.getsid(0),
            "owner_fd": owner_fd, "owner_fd_inheritable": os.get_inheritable(owner_fd),
            "started_monotonic_seconds": started,
        })
        # Parent records the actual Popen PID before it may send this permission.
        permission = b"GO " + expected_sha.encode("ascii") + b"\n"
        seen = b""
        while seen != permission:
            if time.monotonic() >= spec["deadline_monotonic_seconds"]:
                reason, timed_out = "deadline", True
                break
            select.select([owner_fd], [], [], min(.05, max(0, spec["deadline_monotonic_seconds"] - time.monotonic())))
            data = _owner_read(owner_fd)
            if data == b"":
                reason, owner_eof = "owner_eof", True
                break
            if data:
                seen += data
                if not permission.startswith(seen):
                    raise GuardError("Invalid startup permission")
        if not owner_eof and not timed_out:
            if _owner_eof(owner_fd):
                reason, owner_eof = "owner_eof", True
            elif time.monotonic() >= spec["deadline_monotonic_seconds"]:
                reason, timed_out = "deadline", True
            else:
                # Do not inherit the owner fd or other guard descriptors in command.
                with open(io["stdin"] if io["stdin"] is not None else os.devnull, "rb") as stdin, \
                        open(io["stdout"], "ab") as stdout, \
                        open(io["stderr"], "ab") as stderr:
                    try:
                        command_started = time.monotonic()
                        if _owner_eof(owner_fd):
                            reason, owner_eof = "owner_eof", True
                        elif command_started >= spec["deadline_monotonic_seconds"]:
                            reason, timed_out = "deadline", True
                        else:
                            proc = subprocess.Popen(spec["argv"], cwd=io["cwd"], stdin=stdin,
                                                    stdout=stdout, stderr=stderr, close_fds=True,
                                                    start_new_session=False)
                    except OSError as exc:
                        launch_error = f"{type(exc).__name__}: {exc}"
                        reason = "command_launch_error"
                    if proc is not None:
                        _write_new(directory / "command_started.json", {
                            "schema": PROTOCOL, "spec_sha256": expected_sha,
                            "guard_pid": guard_pid, "command_pid": proc.pid,
                            "inherited_pgid": guard_pid, "start_new_session": False,
                            "close_fds": True, "started_monotonic_seconds": command_started,
                        })
                        while True:
                            if _owner_eof(owner_fd):
                                reason, owner_eof = "owner_eof", True
                                break
                            if _poll_wait4(proc) is not None:
                                reason = "command_exit"
                                break
                            if time.monotonic() >= spec["deadline_monotonic_seconds"]:
                                reason, timed_out = "deadline", True
                                break
                            select.select([owner_fd], [], [], min(.05, max(0, spec["deadline_monotonic_seconds"] - time.monotonic())))
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        reason = "guard_error"
    finally:
        # SIGTERM uses a Python no-op in this process; exec resets command's caught
        # signal handlers to the OS default. No command can postpone group KILL.
        try:
            _signal_group(signal.SIGTERM)
            if proc is not None:
                try:
                    returncode = _wait4(proc, TERM_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    # Avoid Popen.kill()->poll()->waitpid stealing wait4's usage.
                    try:
                        os.kill(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    returncode = _wait4(proc, DIRECT_KILL_WAIT_SECONDS)
                command_finished = time.monotonic()
            if spec is not None:
                receipt = {
                    "schema": PROTOCOL, "spec_sha256": expected_sha,
                    "call_id": spec["call_id"], "request_fingerprint": spec["request_fingerprint"],
                    "guard_pid": guard_pid, "guard_pgid": guard_pid,
                    "command_pid": proc.pid if proc is not None else None,
                    "command_returncode": returncode, "timed_out": timed_out,
                    "command_peak_rss_bytes": getattr(proc, "guard_peak_rss_bytes", None),
                    "owner_eof": owner_eof, "stop_reason": reason,
                    "launch_error": launch_error, "guard_error": error,
                    "guard_started_monotonic_seconds": started,
                    "command_started_monotonic_seconds": command_started,
                    "command_finished_monotonic_seconds": command_finished,
                    "before_final_kill_monotonic_seconds": time.monotonic(),
                    "group_term_sent": True, "final_group_signal": int(signal.SIGKILL),
                    "output_files_sha256": _outputs(spec["io_spec"]),
                }
                _write_new(directory / "receipt.json", receipt)
        except BaseException as exc:
            # Best-effort raw diagnostic only. It cannot replace a receipt and
            # cannot delay the finally group kill by attempting another file.
            try:
                os.write(2, (f"guard cleanup/receipt failure: {type(exc).__name__}: {exc}\n").encode("utf-8", errors="replace"))
            except OSError:
                pass
            raise
        finally:
            # This also runs if receipt open/write/fsync fails. A surviving
            # owner cannot interpret absent receipt as success or retry it.
            _signal_group(signal.SIGKILL)
    return 3  # Unreachable unless the OS failed to deliver SIGKILL.


def _read_terminal(run, command, timeout_seconds, call_id, fingerprint, io_spec=None):
    io = _io_spec(run, io_spec)
    directory = run / "process_guard"
    if (directory / "cleanup_errors.json").exists():
        raise GuardError("Parent ownership cleanup failed; completion is not usable")
    raw = {name: _raw(directory / name) for name in CORE_FILES}
    if (directory / "command_started.json").exists():
        raw["command_started.json"] = _raw(directory / "command_started.json")
    values = {name: json.loads(content) for name, content in raw.items()}
    spec, launch, parent, started, receipt = (values[name] for name in CORE_FILES)
    spec_sha = _sha(raw["spec.json"])
    if any(value.get("schema") != PROTOCOL for value in values.values()):
        raise GuardError("Lifecycle schema differs")
    guard_argv = launch.get("guard_argv")
    if (type(guard_argv) is not list or len(guard_argv) != 8
            or any(type(x) is not str for x in guard_argv)
            or not Path(guard_argv[0]).is_absolute()
            or guard_argv[1:3] != ["-I", "-B"]
            or not Path(guard_argv[3]).is_absolute()
            or guard_argv[4:] != ["--guard", str(directory / "spec.json"), str(launch.get("owner_read_fd")), spec_sha]
            or launch.get("writer_inheritable") is not False
            or launch.get("start_new_session") is not True):
        raise GuardError("Guard launch command or pipe policy differs")
    if (spec.get("run_dir") != str(run) or spec.get("argv") != command
            or spec.get("io_spec") != io
            or spec.get("timeout_seconds") != timeout_seconds
            or spec.get("call_id") != call_id or spec.get("request_fingerprint") != fingerprint
            or spec.get("input_files_sha256") != _inputs(io)):
        raise GuardError("Lifecycle differs from original command/request/inputs")
    _timeout(spec["timeout_seconds"])
    if (not _number(spec.get("begun_monotonic_seconds"))
            or not _number(spec.get("deadline_monotonic_seconds"))
            or spec["deadline_monotonic_seconds"] != spec["begun_monotonic_seconds"] + spec["timeout_seconds"]
            or spec.get("term_grace_seconds") != TERM_GRACE_SECONDS
            or spec.get("direct_kill_wait_seconds") != DIRECT_KILL_WAIT_SECONDS):
        raise GuardError("Lifecycle deadline differs")
    pid = started.get("guard_pid")
    if type(pid) is not int or pid <= 1:
        raise GuardError("Invalid guard PID")
    if (any(value.get("spec_sha256") != spec_sha for name, value in values.items() if name != "spec.json")
            or parent.get("guard_pid") != pid or parent.get("parent_pid") != launch.get("parent_pid")
            or started.get("guard_pgid") != pid or started.get("guard_sid") != pid
            or started.get("owner_fd_inheritable") is not False
            or started.get("owner_fd") != launch.get("owner_read_fd")
            or receipt.get("guard_pid") != pid or receipt.get("guard_pgid") != pid
            or receipt.get("call_id") != call_id or receipt.get("request_fingerprint") != fingerprint
            or receipt.get("group_term_sent") is not True or receipt.get("final_group_signal") != signal.SIGKILL
            or receipt.get("output_files_sha256") != _outputs(io)):
        raise GuardError("Lifecycle identity/group/output binding differs")
    if (type(receipt.get("timed_out")) is not bool or type(receipt.get("owner_eof")) is not bool
            or receipt.get("owner_eof") or receipt.get("guard_error") is not None):
        raise GuardError("Guard failed or lost its owner; no completed lifecycle")
    command_pid, code = receipt.get("command_pid"), receipt.get("command_returncode")
    cli = values.get("command_started.json")
    reason = receipt.get("stop_reason")
    if command_pid is not None:
        if (type(command_pid) is not int or command_pid <= 1 or type(code) is not int or cli is None
                or type(receipt.get("command_peak_rss_bytes")) is not int or receipt["command_peak_rss_bytes"] < 0
                or cli.get("command_pid") != command_pid or cli.get("guard_pid") != pid
                or cli.get("inherited_pgid") != pid or cli.get("start_new_session") is not False
                or cli.get("close_fds") is not True
                or cli.get("started_monotonic_seconds") != receipt.get("command_started_monotonic_seconds")):
            raise GuardError("Direct command terminal/launch evidence differs")
    elif cli is not None or code is not None or receipt.get("command_peak_rss_bytes") is not None:
        raise GuardError("command launch evidence without command identity")
    if reason == "command_exit":
        if command_pid is None or receipt["timed_out"] or receipt.get("launch_error") is not None:
            raise GuardError("command exit receipt contradicts completion")
    elif reason == "deadline":
        if (not receipt["timed_out"] or receipt.get("launch_error") is not None
                or not _number(receipt.get("before_final_kill_monotonic_seconds"))
                or receipt["before_final_kill_monotonic_seconds"] < spec["deadline_monotonic_seconds"]):
            raise GuardError("Deadline receipt contradicts timeout")
    elif reason == "command_launch_error":
        if command_pid is not None or receipt["timed_out"] or not isinstance(receipt.get("launch_error"), str):
            raise GuardError("command launch-error receipt contradicts launch")
    else:
        raise GuardError("Receipt is not a completed supported terminal state")
    times = [spec["begun_monotonic_seconds"], started.get("started_monotonic_seconds")]
    if command_pid is not None:
        times += [receipt.get("command_started_monotonic_seconds"), receipt.get("command_finished_monotonic_seconds")]
    times.append(receipt.get("before_final_kill_monotonic_seconds"))
    if any(not _number(x) for x in times) or times != sorted(times):
        raise GuardError("Lifecycle monotonic timestamps differ")
    hashes = {name: _sha(content) for name, content in raw.items()}
    hashes["guard_stderr.log"] = _digest_file(directory / "guard_stderr.log")
    return values, hashes


def verify_lifecycle(run_dir, *, expected_command, expected_timeout, expected_call_id,
                     expected_fingerprint, expected_evidence=None, expected_io_spec=None):
    """Read-only structural proof, never invoke/reap/finish anything.

    Returns original verified hashes for the outer acceptance's final fence.
    Missing parent wait (e.g. owner death) is unknown, never promoted to success.
    Caller must also bind these hashes to the original ledger and frozen source.
    """
    run = Path(run_dir).resolve()
    io = _io_spec(run, expected_io_spec)
    values, hashes = _read_terminal(run, expected_command, expected_timeout, expected_call_id, expected_fingerprint, io)
    raw = _raw(run / "process_guard" / "parent_observed.json")
    observed = json.loads(raw)
    started, receipt = values["started.json"], values["receipt.json"]
    if (observed.get("schema") != PROTOCOL or observed.get("files_sha256") != hashes
            or observed.get("guard_pid") != started["guard_pid"]
            or type(observed.get("guard_returncode")) is not int
            or observed["guard_returncode"] != -signal.SIGKILL
            or type(observed.get("guard_peak_rss_bytes")) is not int or observed["guard_peak_rss_bytes"] < 0
            or observed.get("wait_completed") is not True
            or not _number(observed.get("observed_monotonic_seconds"))
            or observed["observed_monotonic_seconds"] < receipt["before_final_kill_monotonic_seconds"]):
        raise GuardError("Parent wait does not bind the terminal receipt")
    hashes["parent_observed.json"] = _sha(raw)
    evidence = {"schema": PROTOCOL, "lifecycle_complete": True,
                "guard_pid": started["guard_pid"], "guard_pgid": started["guard_pgid"],
                "command_pid": receipt["command_pid"], "guard_returncode": observed["guard_returncode"],
                "command_returncode": receipt["command_returncode"], "timed_out": receipt["timed_out"],
                "launch_error": receipt["launch_error"], "files_sha256": hashes,
                "guard_source_sha256": values["spec.json"]["guard_source_sha256"],
                "input_files_sha256": values["spec.json"]["input_files_sha256"],
                "output_files_sha256": receipt["output_files_sha256"],
                "io_spec": io, "command_peak_rss_bytes": receipt["command_peak_rss_bytes"],
                "guard_peak_rss_bytes": observed["guard_peak_rss_bytes"],
                "parent_wait_wall_seconds": observed["observed_monotonic_seconds"] - values["spec.json"]["begun_monotonic_seconds"]}
    if expected_evidence is not None and _encoded(evidence) != _encoded(expected_evidence):
        raise GuardError("Result lifecycle evidence differs from original records")
    # Keep original anchors; do not re-anchor replacements after semantic checks.
    for name, digest in hashes.items():
        if _digest_file(run / "process_guard" / name) != digest:
            raise GuardError("Lifecycle evidence replaced after verification")
    if _inputs(io) != evidence["input_files_sha256"] or _outputs(io) != evidence["output_files_sha256"]:
        raise GuardError("Original call files replaced after verification")
    if {path.name for path in (run / "process_guard").iterdir()} != set(hashes):
        raise GuardError("Lifecycle directory contains extra, partial, or cleanup-error evidence")
    return evidence


def _bounded_reap(process):
    try:
        return _wait4(process, TERM_GRACE_SECONDS + DIRECT_KILL_WAIT_SECONDS + PARENT_MARGIN_SECONDS)
    except subprocess.TimeoutExpired:
        # The unreaped direct child still owns its PID; this is not name scanning.
        if _poll_wait4(process) is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        return _wait4(process, DIRECT_KILL_WAIT_SECONDS + PARENT_MARGIN_SECONDS)


def _release_owner_and_reap(process, read_fd, write_fd, primary, directory):
    failures = []
    for name, fd in (("owner_writer_close", write_fd), ("owner_reader_close", read_fd)):
        if fd is not None:
            try:
                os.close(fd)
            except BaseException as exc:
                failures.append((name, exc))
    if process is not None:
        try:
            _bounded_reap(process)
        except BaseException as exc:
            failures.append(("bounded_guard_reap", exc))
    if not failures:
        return
    diagnostics = [{"stage": name, "error_type": type(exc).__name__, "error": str(exc)}
                   for name, exc in failures]
    try:
        _write_new(Path(directory) / "cleanup_errors.json", {
            "schema": PROTOCOL, "primary_error_type": type(primary).__name__ if primary is not None else None,
            "primary_error": str(primary) if primary is not None else None,
            "cleanup_errors": diagnostics, "lifecycle_complete": False,
        })
    except BaseException as exc:
        diagnostics.append({"stage": "cleanup_diagnostic_write", "error_type": type(exc).__name__, "error": str(exc)})
    note = "Secondary owner-pipe cleanup failures: " + json.dumps(diagnostics, ensure_ascii=True)
    if primary is not None:
        primary.add_note(note)
        return  # The already-active BaseException remains the exception raised.
    raise GuardError(note) from failures[0][1]


def run_guarded(command, *, run_dir, timeout_seconds, env, call_id, request_fingerprint, io_spec=None):
    """Fresh one-shot execution; errors leave original raw files and pending ledger.

    env is used in memory only. The caller owns budget reservation and completion.
    Execution deadline includes guard startup; cleanup grace is separately elapsed.
    """
    if os.name != "posix":
        raise GuardError("Owner-pipe guard requires POSIX process groups")
    _timeout(timeout_seconds)
    if type(command) is not list or not command or any(type(x) is not str for x in command):
        raise TypeError("command must be a nonempty list of strings")
    if any(type(x) is not str or not x for x in (call_id, request_fingerprint)):
        raise TypeError("call identity must be nonempty strings")
    begun = time.monotonic()
    run = Path(run_dir).resolve()
    io = _io_spec(run, io_spec)
    directory = run / "process_guard"
    directory.mkdir(exist_ok=False)
    spec = {"schema": PROTOCOL, "run_dir": str(run), "call_id": call_id,
            "request_fingerprint": request_fingerprint, "argv": command,
            "io_spec": io, "timeout_seconds": timeout_seconds,
            "begun_monotonic_seconds": begun, "deadline_monotonic_seconds": begun + timeout_seconds,
            "term_grace_seconds": TERM_GRACE_SECONDS, "direct_kill_wait_seconds": DIRECT_KILL_WAIT_SECONDS,
            "guard_source_sha256": _sha(_raw(Path(__file__).resolve())), "input_files_sha256": _inputs(io)}
    spec_sha = _write_new(directory / "spec.json", spec)
    # Fresh evidence only. Neither streams nor markers may overwrite prior calls.
    for path in (io["stdout"], io["stderr"]):
        with Path(path).open("xb"):
            pass
    read_fd, write_fd = os.pipe()
    process = None
    try:
        os.set_inheritable(read_fd, False)
        os.set_inheritable(write_fd, False)
        guard_command = [sys.executable, "-I", "-B", str(Path(__file__).resolve()),
                         "--guard", str(directory / "spec.json"), str(read_fd), spec_sha]
        _write_new(directory / "launch.json", {
            "schema": PROTOCOL, "spec_sha256": spec_sha, "parent_pid": os.getpid(),
            "guard_argv": guard_command, "owner_read_fd": read_fd,
            "writer_inheritable": False, "start_new_session": True,
        })
        with (directory / "guard_stderr.log").open("xb") as stderr:
            process = subprocess.Popen(guard_command, env=env, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=stderr, close_fds=True,
                                       pass_fds=(read_fd,), start_new_session=True)
        os.close(read_fd)
        read_fd = None
        _write_new(directory / "parent_started.json", {
            "schema": PROTOCOL, "spec_sha256": spec_sha,
            "parent_pid": os.getpid(), "guard_pid": process.pid,
        })
        permission = b"GO " + spec_sha.encode("ascii") + b"\n"
        if os.write(write_fd, permission) != len(permission):
            raise GuardError("Short startup permission write")
        wait_seconds = max(0, spec["deadline_monotonic_seconds"] - time.monotonic()) + TERM_GRACE_SECONDS + DIRECT_KILL_WAIT_SECONDS + PARENT_MARGIN_SECONDS
        code = _wait4(process, wait_seconds)
        if code != -signal.SIGKILL:
            raise GuardError(f"Guard ended without final group SIGKILL: {code}")
        values, hashes = _read_terminal(run, command, timeout_seconds, call_id, request_fingerprint, io)
        _write_new(directory / "parent_observed.json", {
            "schema": PROTOCOL, "guard_pid": process.pid, "guard_returncode": code,
            "wait_completed": True, "observed_monotonic_seconds": time.monotonic(), "files_sha256": hashes,
            "guard_peak_rss_bytes": process.guard_peak_rss_bytes,
        })
        return verify_lifecycle(run, expected_command=command, expected_timeout=timeout_seconds,
                                expected_call_id=call_id, expected_fingerprint=request_fingerprint, expected_io_spec=io)
    finally:
        # Abrupt OS death also closes this writer; no child inherits it. Ordinary
        # exceptions close it before waiting, so the guard can detect owner loss.
        _release_owner_and_reap(process, read_fd, write_fd, sys.exc_info()[1], directory)


if __name__ == "__main__":
    if len(sys.argv) != 5 or sys.argv[1] != "--guard":
        raise SystemExit("Use --guard SPEC OWNER_READ_FD EXPECTED_SPEC_SHA256")
    raise SystemExit(_guard_main(sys.argv[2], int(sys.argv[3]), sys.argv[4]))
