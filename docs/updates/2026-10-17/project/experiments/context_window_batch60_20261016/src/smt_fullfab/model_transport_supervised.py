"""Full-fab version copy of the verified bounded no-native-tools transport.

The surrounding experiment executes only JSON actions it explicitly recognizes.
No solver or scheduling logic belongs in this module.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import stat
import subprocess
import time
from typing import Any
from .budget import BudgetLedger, DEFAULT_LEDGER
from .model_process_guard import run_guarded, verify_lifecycle

PROMPT_CHARACTER_LIMIT = 120_000

class PromptTooLarge(ValueError):
    """Rejected before budget reservation and before any CLI/model attempt."""


DISABLED_FEATURES = (
    "apps", "plugins", "remote_plugin", "browser_use", "browser_use_external",
    "browser_use_full_cdp_access", "in_app_browser", "computer_use",
    "shell_tool", "unified_exec", "shell_snapshot", "multi_agent",
    "view_image", "image_generation", "artifact", "workspace_dependencies",
    "code_mode", "code_mode_host", "code_mode_only", "hooks", "memories",
    "skill_search", "skill_mcp_dependency_install", "tool_suggest", "goals",
    "default_mode_request_user_input", "request_permissions_tool", "standalone_web_search",
    "sleep_tool", "unbounded_connection_retries", "agent_message_board", "send_message_to_user_async",
)

BASE_INSTRUCTIONS = """You are a decision component in a controlled scheduling experiment.
Use only data in the user message. No native tools are available or permitted.
Return exactly one JSON object conforming to the supplied schema. Any requested action
is data for an external deterministic runner, not a native tool call. Do not access files,
networks, shells, code interpreters, memory, other runs, or reference solutions.
Provide concise decision justifications when the schema requests them.
"""


@dataclasses.dataclass(frozen=True)
class ModelConfig:
    model: str = "gpt-6-astra"
    reasoning_effort: str = "medium"
    timeout_seconds: float = 240.0
    codex_binary: str = "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex"
    proxy: str | None = "http://127.0.0.1:7897"
    ledger_path: str = str(DEFAULT_LEDGER)
    phase: str = "development"
    grant_id: str = "unallocated"
    authorization_context: dict | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.timeout_seconds <= 300:
            raise ValueError("Each transport call must have a timeout of 1–300 seconds")


def _write_json(path: Path, value: Any) -> None:
    # Atomic completion markers make interrupted runs distinguishable and replayable.
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _disabled_skills() -> list[Path]:
    # Read names only; never inspect auth files or copy credentials.
    roots = [Path.home() / ".codex" / "skills", Path.home() / ".agents" / "skills"]
    return sorted({p.parent.resolve() for root in roots if root.exists() for p in root.rglob("SKILL.md")})


def _config_overrides(run_dir: Path, config: ModelConfig) -> list[str]:
    settings = [
        'model_reasoning_effort=' + json.dumps(config.reasoning_effort),
        'approval_policy="never"', 'web_search="disabled"', 'project_doc_max_bytes=0',
        'mcp_servers={}', 'skills.max_context_tokens=1',
        'features.skip_host_skill_discovery=true', 'agents.max_concurrent_threads_per_session=1',
        'features.multi_agent_v2={enabled=false,max_concurrent_threads_per_session=1,wait_agent_enabled=false}',
        'model_instructions_file=' + json.dumps(str(run_dir / "system-instructions.txt")),
        'log_dir=' + json.dumps(str(run_dir / "runtime" / "log")),
        'sqlite_home=' + json.dumps(str(run_dir / "runtime" / "state")),
        'history.persistence="none"', 'shell_environment_policy.inherit="none"',
    ]
    settings.extend('features.' + feature + '=false' for feature in DISABLED_FEATURES)
    disabled = _disabled_skills()
    settings.append('skills.config=[' + ','.join(
        '{path=' + json.dumps(str(p)) + ',enabled=false}' for p in disabled
    ) + ']')
    return settings


def build_command(run_dir: Path, config: ModelConfig) -> list[str]:
    args = [config.codex_binary, "exec", "--json", "--ephemeral", "--ignore-user-config",
            "--ignore-rules", "--skip-git-repo-check", "--sandbox", "read-only",
            "--color", "never", "--model", config.model, "--cd", str(run_dir / "isolated-cwd"),
            "--output-schema", str(run_dir / "schema.json"),
            "--output-last-message", str(run_dir / "final.txt")]
    for setting in _config_overrides(run_dir, config):
        args.extend(["-c", setting])
    args.append("-")
    return args


def read_events(path: Path) -> tuple[list[dict], list[str]]:
    events, malformed = [], []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                malformed.append(line)
    return events, malformed


def _bound_output_bytes(path, expected_sha256, *, keep_bytes):
    """Hash and optionally retain the same original FD bytes, not a later read."""
    if expected_sha256 is None:
        try:
            path.lstat()
        except FileNotFoundError:
            return None
        raise ValueError("Previously absent guarded output now exists: " + path.name)
    if (type(expected_sha256) is not str or len(expected_sha256) != 64
            or any(c not in '0123456789abcdef' for c in expected_sha256)):
        raise ValueError("Invalid original guard output SHA")
    def identity(value):
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or identity(before) != identity(path.lstat()):
            raise ValueError("Nonregular or replaced guarded output: " + path.name)
        digest, chunks, remaining = hashlib.sha256(), [], before.st_size
        while remaining:
            block = os.read(fd, min(1024 * 1024, remaining))
            if not block:
                raise ValueError("Guarded output shortened during read: " + path.name)
            digest.update(block)
            if keep_bytes:
                chunks.append(block)
            remaining -= len(block)
        if (identity(before) != identity(os.fstat(fd)) or identity(before) != identity(path.lstat())
                or digest.hexdigest() != expected_sha256):
            raise ValueError("Guarded output differs from original verified bytes: " + path.name)
        return b''.join(chunks) if keep_bytes else None
    finally:
        os.close(fd)


def _guard_output_hashes(guarded):
    value = guarded.get('output_files_sha256')
    if type(value) is not dict or set(value) != {'events.jsonl', 'stderr.log', 'final.txt'}:
        raise ValueError("Supervised model requires all three original output anchors")
    if value['events.jsonl'] is None or value['stderr.log'] is None:
        raise ValueError("Original guarded events/stderr streams are missing")
    return value


def _read_guarded_outputs(run_dir, guarded):
    hashes = _guard_output_hashes(guarded)
    # stderr is hash-checked incrementally but never unnecessarily held in RAM.
    return {name: _bound_output_bytes(run_dir / name, hashes[name], keep_bytes=name != 'stderr.log')
            for name in ('events.jsonl', 'stderr.log', 'final.txt')}


def _fence_guarded_outputs(run_dir, guarded):
    for name, sha in _guard_output_hashes(guarded).items():
        _bound_output_bytes(run_dir / name, sha, keep_bytes=False)


def _original_text(raw, *, errors='strict'):
    # Match Path.read_text's universal-newline semantics without reopening a path.
    return raw.decode('utf-8', errors=errors).replace('\r\n', '\n').replace('\r', '\n')


def _events_from_original_bytes(raw):
    events, malformed = [], []
    for line in _original_text(raw, errors='replace').splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            malformed.append(line)
    return events, malformed


def summarize_events(events: list[dict]) -> dict:
    completed = [e for e in events if e.get("type") == "turn.completed"]
    usages = [e.get("usage") for e in completed if type(e.get("usage")) is dict]
    invalid=[]
    for index,event in enumerate(completed):
        raw=event.get('usage')
        if raw is not None and type(raw) is not dict:
            invalid.append({'completed_turn':index,'reason':'usage must be an object or null'})
        elif type(raw) is dict:
            for key,value in raw.items():
                if value is not None and not (type(value) is int and value>=0):
                    invalid.append({'completed_turn':index,'field':key,'reason':'counter must be a nonnegative integer or null'})
    usage = {
        key: sum(u[key] for u in usages) if usages and len(usages)==len(completed)
            and all(type(u.get(key)) is int and u[key]>=0 for u in usages) else None
        for key in ("input_tokens", "cached_input_tokens", "output_tokens", "cache_write_input_tokens", "reasoning_output_tokens")
    }
    # Fail closed if the supposedly tool-free backend performs a native action.
    allowed_items = {"agent_message", "reasoning", "error"}
    native_items = [e.get("item", {}) for e in events
                    if e.get("type") in {"item.started", "item.completed", "item.updated"}
                    and e.get("item", {}).get("type") not in allowed_items]
    result = {
        "completed_turns": len(completed), "usage": usage,
        "usage_status": "invalid" if invalid else "reported" if usages else "unknown",
        "native_tool_events": native_items,
        "thread_ids": [e["thread_id"] for e in events if e.get("type") == "thread.started" and "thread_id" in e],
        "errors": [e for e in events if e.get("type") in {"error", "turn.failed"}],
    }
    # Valid historical summaries retain their original shape. Raw invalid values
    # stay in events.jsonl; derived diagnostics cannot coerce them into costs.
    if invalid:result['usage_validation_errors']=invalid
    return result


def _finish_details(result: dict, result_path: Path) -> dict:
    """The same immutable completion facts are used for fresh and replayed calls."""
    return {"result_path": str(result_path), "failure_reason": result["failure_reason"],
            "usage": result["usage"], "duration_seconds": result["duration_seconds"],
            "cost_usd": result["cost_usd"], "completed_turns": result["completed_turns"]}


def _same_json(left, right) -> bool:
    # Preserve nulls and JSON types; Python otherwise treats False == 0.
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def _replay_completed(prompt, schema_text, run_dir, config, fingerprint, old):
    """Verify local completion, then reconcile only its reserved ledger finish.

    A result marker is required. Neither a pending request nor a temporary result
    is evidence that an interrupted process has terminated. No CLI is invoked.
    """
    request_path = run_dir / "request.json"
    required_files = (request_path, run_dir / "prompt.txt", run_dir / "schema.json",
                      run_dir / "attempt.claim", run_dir / "events.jsonl")
    if any(not path.is_file() for path in required_files):
        raise ValueError("Completed-call replay lacks original request evidence")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    saved_config = dataclasses.asdict(config)
    if (not isinstance(old, dict) or not isinstance(request, dict)
            or old.get("request_fingerprint") != fingerprint
            or request.get("request_fingerprint") != fingerprint
            or not _same_json(old.get("config"), saved_config)
            or not _same_json(request.get("config"), saved_config)
            or (run_dir / "prompt.txt").read_text(encoding="utf-8") != prompt
            or (run_dir / "schema.json").read_text(encoding="utf-8") != schema_text
            or (run_dir / "attempt.claim").read_text(encoding="utf-8") != fingerprint + "\n"):
        raise ValueError("Cannot replay call with changed prompt/schema/config/fingerprint")
    call_id = old.get("call_id")
    if not isinstance(call_id, str) or not call_id or request.get("call_id") != call_id:
        raise ValueError("Completed result and original request call_id differ")
    # Incomplete guard records are never used to reconcile a pending finish.
    guarded = verify_lifecycle(
        run_dir, expected_command=build_command(run_dir, config),
        expected_timeout=config.timeout_seconds, expected_call_id=call_id,
        expected_fingerprint=fingerprint, expected_evidence=old.get("process_guard"))
    if (old.get("process_guard") is None or old.get("cli_version") is not None
            or old.get("cli_version_policy") != "not_run; enclosing freeze binds CLI wrapper and actual executable"
            or not _same_json(old.get("returncode"), guarded["command_returncode"])
            or not _same_json(old.get("timed_out"), guarded["timed_out"])
            or old.get("launch_error") != guarded["launch_error"]):
        raise ValueError("Completed result differs from supervised lifecycle")
    if old.get("started_at") != request.get("started_at"):
        raise ValueError("Completed result and request start times differ")
    try:
        began = dt.datetime.fromisoformat(old["started_at"])
        ended = dt.datetime.fromisoformat(old["finished_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Completed result lacks valid terminal timestamps") from exc
    if began.tzinfo is None or ended.tzinfo is None or ended < began:
        raise ValueError("Completed result has inconsistent terminal timestamps")
    duration = old.get("duration_seconds")
    if (type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0
            or not _same_json(old.get("model_elapsed_seconds"), duration)
            or not _same_json(old.get("model_calls"), 1)
            or not _same_json(old.get("automatic_retries"), 0)
            or old.get("cost_usd") is not None
            or not _same_json(old.get("prompt_characters"), len(prompt))
            or not _same_json(old.get("prompt_character_limit"), PROMPT_CHARACTER_LIMIT)
            or type(old.get("timed_out")) is not bool
            or (old.get("returncode") is not None and type(old["returncode"]) is not int)
            or (old.get("launch_error") is not None and not isinstance(old["launch_error"], str))):
        raise ValueError("Completed result resource/completion fields are inconsistent")

    original_outputs = _read_guarded_outputs(run_dir, guarded)
    events, malformed = _events_from_original_bytes(original_outputs['events.jsonl'])
    summary = summarize_events(events)
    if any(not _same_json(old.get(key), value) for key, value in summary.items()) or not _same_json(old.get("malformed_event_lines"), malformed):
        raise ValueError("Completed result differs from original event/usage evidence")
    output, decode_error = None, None
    if original_outputs['final.txt'] is not None:
        try:
            output = json.loads(_original_text(original_outputs['final.txt']))
        except json.JSONDecodeError as exc:
            decode_error = str(exc)
    else:
        decode_error = "No final message file"
    if not _same_json(old.get("output"), output) or old.get("decode_error") != decode_error:
        raise ValueError("Completed result differs from original final output")
    if old["timed_out"]:
        status, failure = "timeout", "model_call_timeout"
    elif old.get("launch_error"):
        status, failure = "failed", "model_launch_error"
    elif summary["native_tool_events"]:
        status, failure = "failed", "native_tool_isolation_violation"
    elif malformed:
        status, failure = "failed", "malformed_event_log"
    elif summary.get('usage_validation_errors'):
        status, failure = "failed", "invalid_usage_evidence"
    elif old.get("returncode") != 0 or summary["completed_turns"] != 1:
        status, failure = "failed", "model_transport_error"
    elif decode_error:
        status, failure = "failed", "invalid_model_json"
    else:
        status, failure = "success", None
    if old.get("status") != status or old.get("failure_reason") != failure:
        raise ValueError("Completed result status contradicts original evidence")

    ledger = BudgetLedger(config.ledger_path)
    expected_metadata = {"request_fingerprint": fingerprint, "model": config.model,
                         "timeout_seconds": config.timeout_seconds,
                         "reasoning_effort": config.reasoning_effort,
                         "prompt_characters": len(prompt), "prompt_character_limit": PROMPT_CHARACTER_LIMIT,
                         "authorization_context": config.authorization_context}
    details = _finish_details(old, run_dir / "result.json")

    def verify_ledger():
        with ledger._locked() as rows:
            reservations = [row for row in rows if row.get("event") == "reserve" and row.get("call_id") == call_id]
            finishes = [row for row in rows if row.get("event") == "finish" and row.get("call_id") == call_id]
            if len(reservations) != 1:
                raise ValueError("Completed replay requires exactly one matching reserve")
            reserved = reservations[0]
            if (reserved.get("run_id") != str(run_dir) or reserved.get("phase") != config.phase
                    or reserved.get("grant_id") != config.grant_id
                    or not _same_json(reserved.get("metadata"), expected_metadata)):
                raise ValueError("Completed replay reserve run_id/metadata/config differs")
            if len(finishes) > 1 or (finishes and
                    (finishes[0].get("status") != old["status"] or not _same_json(finishes[0].get("details"), details))):
                raise ValueError("Completed replay conflicts with recorded finish")
            return bool(finishes)

    if not verify_ledger():
        _fence_guarded_outputs(run_dir, guarded)
        try:
            ledger.finish(call_id, old["status"], details)
        except ValueError:
            # Another serial recovery caller may have closed the same gap.
            # Only accept a byte-equivalent JSON completion; never duplicate it.
            if not verify_ledger():
                raise
    _fence_guarded_outputs(run_dir, guarded)
    return old


def call_model(prompt: str, schema: dict, run_dir: str | Path,
               config: ModelConfig | dict | None = None, *, resume: bool = False) -> dict:
    """Make exactly one fresh invocation, or replay an identical completed call.

    Returns the persisted result record; `output` is decoded JSON on success. No
    retry is automatic. Caller must give each retry/revision a new run_dir.
    `model_calls` counts CLI attempts, while backend HTTP retries and pure model
    processing time are not observable and explicitly remain unknown.
    Fresh prompts are limited to 120000 Python Unicode code points, not tokens.
    The ledger checks observed phase tokens before admission. Server-side output
    tokens cannot be hard-capped by this verified CLI channel; a serial batch can
    exceed its observed threshold by one already-admitted, time-bounded call.
    """
    config = ModelConfig(**config) if isinstance(config, dict) else (config or ModelConfig())
    # This new explicit transport version is capped before ledger reservation.
    if (type(config.timeout_seconds) not in (int, float)
            or not math.isfinite(config.timeout_seconds) or not 1 <= config.timeout_seconds <= 180):
        raise ValueError("Supervised model execution timeout must be 1–180 seconds")
    if not isinstance(prompt,str):
        raise TypeError('prompt must be a string')
    run_dir = Path(run_dir).resolve()
    schema_text = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
    fingerprint = _sha(prompt + "\n" + schema_text + "\n" + json.dumps(dataclasses.asdict(config), sort_keys=True))
    result_path = run_dir / "result.json"
    if result_path.exists():
        old = json.loads(result_path.read_text(encoding="utf-8"))
        if not resume:
            raise FileExistsError(f"Call already exists; use resume=True or new directory: {run_dir}")
        return _replay_completed(prompt, schema_text, run_dir, config, fingerprint, old)
    if resume:
        raise FileNotFoundError("No completed result exists; pending requests require diagnosis, not replay or a new call")
    if len(prompt)>PROMPT_CHARACTER_LIMIT:
        raise PromptTooLarge(f'Prompt has {len(prompt)} Unicode characters; limit is {PROMPT_CHARACTER_LIMIT}. No model attempt or budget reservation was made.')
    if (run_dir / "request.json").exists():
        raise FileExistsError(f"Interrupted call preserved; diagnose and use a new attempt directory: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    # Exclusive marker prevents races between callers using the same directory.
    with (run_dir / "attempt.claim").open('x', encoding='utf-8') as marker:
        marker.write(fingerprint + '\n')
    ledger = BudgetLedger(config.ledger_path)
    call_id = ledger.reserve(phase=config.phase,run_id=str(run_dir),grant_id=config.grant_id,
                             metadata={'request_fingerprint':fingerprint,'model':config.model,
                                       'timeout_seconds':config.timeout_seconds,'reasoning_effort':config.reasoning_effort,
                                       'prompt_characters':len(prompt),'prompt_character_limit':PROMPT_CHARACTER_LIMIT,
                                       'authorization_context':config.authorization_context})
    for p in (run_dir / "isolated-cwd", run_dir / "runtime" / "log", run_dir / "runtime" / "state"):
        p.mkdir(parents=True, exist_ok=True)
    (run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    (run_dir / "schema.json").write_text(schema_text, encoding="utf-8")
    (run_dir / "system-instructions.txt").write_text(BASE_INSTRUCTIONS, encoding="utf-8")
    command = build_command(run_dir, config)
    _write_json(run_dir / "command.json", {"argv": command, "cwd": str(run_dir / "isolated-cwd"), "stdin": "prompt.txt", "proxy": config.proxy})
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    _write_json(run_dir / "request.json", {"call_id":call_id,"started_at": started, "request_fingerprint": fingerprint, "config": dataclasses.asdict(config)})
    env = os.environ.copy()
    # No environment snapshot is written. Avoid inheriting parent run identity.
    for key in list(env):
        if key.startswith("CODEX_") and key != "CODEX_HOME":
            env.pop(key)
    if config.proxy:
        for key in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
            env[key] = config.proxy
    # No separate unguarded --version process. The enclosing freeze binds the
    # wrapper and actual executable bytes; cli_version remains explicitly null.
    cli_version = None
    begun = time.monotonic()
    # A guard failure is intentionally NOT converted to a completed result. Raw
    # lifecycle evidence and the original reservation remain pending for diagnosis.
    guarded = run_guarded(command, run_dir=run_dir, timeout_seconds=config.timeout_seconds,
                          env=env, call_id=call_id, request_fingerprint=fingerprint)
    returncode = guarded["command_returncode"]
    timed_out = guarded["timed_out"]
    launch_error = guarded["launch_error"]
    duration = time.monotonic() - begun
    original_outputs = _read_guarded_outputs(run_dir, guarded)
    events, malformed = _events_from_original_bytes(original_outputs['events.jsonl'])
    event_summary = summarize_events(events)
    output, decode_error = None, None
    if original_outputs['final.txt'] is not None:
        try:
            output = json.loads(_original_text(original_outputs['final.txt']))
        except json.JSONDecodeError as exc:
            decode_error = str(exc)
    else:
        decode_error = "No final message file"
    if timed_out:
        status, failure = "timeout", "model_call_timeout"
    elif launch_error:
        status, failure = "failed", "model_launch_error"
    elif event_summary["native_tool_events"]:
        status, failure = "failed", "native_tool_isolation_violation"
    elif malformed:
        status, failure = "failed", "malformed_event_log"
    elif event_summary.get('usage_validation_errors'):
        status, failure = "failed", "invalid_usage_evidence"
    elif returncode != 0 or event_summary["completed_turns"] != 1:
        status, failure = "failed", "model_transport_error"
    elif decode_error:
        status, failure = "failed", "invalid_model_json"
    else:
        status, failure = "success", None
    result = {
        "call_id":call_id,"status": status, "failure_reason": failure, "request_fingerprint": fingerprint,
        "started_at": started, "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "config": dataclasses.asdict(config), "cli_version": cli_version, "returncode": returncode, "timed_out": timed_out,
        "duration_seconds": duration, "model_elapsed_seconds": duration,
        "pure_model_seconds": None, "backend_http_requests": None,
        "model_calls": 1, "automatic_retries": 0, "cost_usd": None,
        "prompt_characters":len(prompt),"prompt_character_limit":PROMPT_CHARACTER_LIMIT,
        "server_output_token_limit":None,
        "token_budget_policy":"append-only ledger authorization checked before admission; research waiver removes aggregate call/token ceilings without removing observed usage",
        "cost_status": "unknown: ChatGPT-authenticated CLI does not return monetary billing",
        "output": output, "decode_error": decode_error, "launch_error": launch_error,
        "malformed_event_lines": malformed, **event_summary,
        "process_guard": guarded,
        "cli_version_policy": "not_run; enclosing freeze binds CLI wrapper and actual executable",
    }
    _fence_guarded_outputs(run_dir, guarded)
    _write_json(result_path, result)
    _fence_guarded_outputs(run_dir, guarded)
    ledger.finish(call_id,status,_finish_details(result, result_path))
    _fence_guarded_outputs(run_dir, guarded)
    return result
