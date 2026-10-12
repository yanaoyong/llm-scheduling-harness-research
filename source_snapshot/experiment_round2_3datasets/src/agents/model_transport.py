"""Bounded, auditable, no-native-tools Codex JSON transport.

The surrounding experiment executes only JSON actions it explicitly recognizes.
No solver or scheduling logic belongs in this module.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Any
from .budget import BudgetLedger, DEFAULT_LEDGER

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


def summarize_events(events: list[dict]) -> dict:
    completed = [e for e in events if e.get("type") == "turn.completed"]
    usages = [e.get("usage") for e in completed if isinstance(e.get("usage"), dict)]
    usage = {
        key: sum(u[key] for u in usages) if usages and all(isinstance(u.get(key), (int, float)) for u in usages) else None
        for key in ("input_tokens", "cached_input_tokens", "output_tokens", "cache_write_input_tokens", "reasoning_output_tokens")
    }
    # Fail closed if the supposedly tool-free backend performs a native action.
    allowed_items = {"agent_message", "reasoning", "error"}
    native_items = [e.get("item", {}) for e in events
                    if e.get("type") in {"item.started", "item.completed", "item.updated"}
                    and e.get("item", {}).get("type") not in allowed_items]
    return {
        "completed_turns": len(completed), "usage": usage,
        "usage_status": "reported" if usages else "unknown",
        "native_tool_events": native_items,
        "thread_ids": [e["thread_id"] for e in events if e.get("type") == "thread.started" and "thread_id" in e],
        "errors": [e for e in events if e.get("type") in {"error", "turn.failed"}],
    }


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
        if old.get("request_fingerprint") != fingerprint:
            raise ValueError("Cannot replay call with changed prompt/schema/config")
        return old
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
                                       'prompt_characters':len(prompt),'prompt_character_limit':PROMPT_CHARACTER_LIMIT})
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
    try:
        version_probe = subprocess.run([config.codex_binary, "--version"], cwd=run_dir / "isolated-cwd",
                                       env=env, text=True, capture_output=True, timeout=10)
        cli_version = version_probe.stdout.strip() if version_probe.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        cli_version = None
    begun = time.monotonic()
    returncode, timed_out, launch_error = None, False, None
    with (run_dir / "events.jsonl").open("w", encoding="utf-8") as stdout, (run_dir / "stderr.log").open("w", encoding="utf-8") as stderr:
        try:
            process = subprocess.Popen(command, cwd=run_dir / "isolated-cwd", env=env,
                                       stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                       text=True, start_new_session=True)
            try:
                process.communicate(prompt, timeout=config.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            returncode = process.returncode
        except OSError as exc:
            launch_error = f"{type(exc).__name__}: {exc}"
    duration = time.monotonic() - begun
    events, malformed = read_events(run_dir / "events.jsonl")
    event_summary = summarize_events(events)
    output, decode_error = None, None
    final_path = run_dir / "final.txt"
    if final_path.exists():
        try:
            output = json.loads(final_path.read_text(encoding="utf-8"))
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
        "token_budget_policy":"observed input+output threshold checked before admission; may overshoot by one bounded call in a serial batch",
        "cost_status": "unknown: ChatGPT-authenticated CLI does not return monetary billing",
        "output": output, "decode_error": decode_error, "launch_error": launch_error,
        "malformed_event_lines": malformed, **event_summary,
    }
    _write_json(result_path, result)
    ledger.finish(call_id,status,{'result_path':str(result_path),'failure_reason':failure,
                  'usage':result['usage'],'duration_seconds':duration,'cost_usd':None,
                  'completed_turns':result['completed_turns']})
    return result
