# Task: Harness v6 Phase V — S1 real-run stack on official Codex (zero model cost)

Work directory for new files: `__LOCAL_WORKSPACE__/v6-mac-env/s1/goal/` (outside the repo).
Harness source (read-only unless a change is unavoidable; if you change it, list every diff and rerun
the affected tests): `__PROJECT_ROOT__/docs/updates/2026-10-17/project/experiments/harness_v6_20261017`
(git main, commit f6bcd8e; do NOT commit/push/branch).

**Hard rules.** Make NO real model request. Every Codex process you start must talk to a loopback mock
on 127.0.0.1. Never read, print, copy or modify `~/.codex/auth.json` or any credential. Do not run the
real smoke — you only build and qualify the stack; the orchestrator runs it after user approval.

## Context

S0 (Mac, patched Codex fork, gpt-6-astra) ran real E1/P2 trajectories through a small stack of
scripts. Their verified copies are in `__LOCAL_WORKSPACE__/v6-mac-env/s1/goal/s0-reference/` (the full verified
S0 archive is extracted at `__LOCAL_WORKSPACE__/v6-mac-env/s0-evidence/x/`, read-only):

- `run_registered_real_v5.py` — execution driver: checks frozen hashes/registration, sets
  `CODEX_ROLLOUT_TRACE_ROOT`, swaps in an audited runner, calls `scripts/run_live.py::execute`.
- `traced_runtime_v163.py` — `AuditedCodexRunner` + `audit_bundle`: audits every native request from the
  Codex rollout trace (model/effort, tools, full history retained, per-request usage == JSONL usage).
  Adds a named provider `harness_live` (OpenAI auth, zero retries, `supports_websockets=false`).
- `traced_runtime_proxy.py` — Mac-only Clash proxy. **Not needed here**: this Linux machine reaches
  `chatgpt.com` directly (api.openai.com is unreachable); no proxy env must be passed.
- `audit_model_run_v4.py` (+ `cycle_artifacts.py`, `audit_idle_replay_v2.py`, `audit_physical_prefix.py`)
  — independent post-run audit; `--smoke` gate = one normally completed adopted session.
- `execute_registered_phase_v5.py`, `execute_stall_smoke_v1.py` — sequential launchers, stop on first
  failure, audit before the next run, never overwrite or retry.
- `prepare_smoke_registration.py`, `freeze_stall_amendment.py` — how S0 froze rules/registration.
- `experiment-rules-v1.json`, `registration-smoke-v5.json`, `technical-amendment-*.json` — S0 records.

Phase U (already merged) moved the harness to official `codex-cli 0.163.0`
(`__LOCAL_WORKSPACE__/v6-mac-env/codex-official/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex`,
SHA-256 `399ff69c431c066e40de318fba45c2b07f45a76b19939d247ee4828fc70c4215`). Read `PHASE_U_REPORT.md`
in the harness directory first. Accepted relaxations: the 3 MCP resource tools are visible in MCP mode;
the request cap is enforced by host kill (usage then unknown, never zero); there is no per-request
output cap (requests carry no `max_output_tokens`); the client catalog is edited. The official rollout
trace (`codex-rs/rollout-trace`, source in `__LOCAL_WORKSPACE__/v6-mac-env/codex-src-0.163.0/`) was never
patched by the fork, so the S0 trace format should be unchanged — verify it.

## Required work

1. **Port the stack to official Codex** as new files in `goal/` (`traced_runtime_s1.py`,
   `run_registered_s1.py`, `audit_model_run_s1.py`, launcher(s)), copying `cycle_artifacts.py`,
   `audit_idle_replay_v2.py`, `audit_physical_prefix.py` unchanged. Minimal, explicit changes only:
   - `audit_bundle`: no `max_output_tokens` check (assert the key is absent instead); MCP tool set =
     the 3 Harness tools + exactly the 3 resource tools (reuse `tool_contract.request_tools(...,
     interaction=...)`); keep every other check, including `output_tokens <= reserve` per request
     (report it as a fail-closed post-hoc check now that no native cap exists); `limit`/`reserve` must
     come from the registration/model_config, not from removed `-c` keys.
   - Auditor: drop `harness_max_inference_requests` assertion; model comes from the registration (no
     hard-coded `gpt-6-astra`); limit = `model_config.admission_limit(...)`.
   - Abort-marker sessions (Phase U) must surface as failed, usage unknown, never adopted, and stop the
     launcher.
   - Driver: no proxy; keep `features.respect_system_proxy=false`, `system_proxy_fallback=false`,
     `unbounded_connection_retries=false`, zero retries, `supports_websockets=false`. Production must
     refuse any `base_url` override.
2. **Codex home isolation.** Real runs need ChatGPT auth but must not load the user's personal Codex
   config, `AGENTS.md`, skills, memories, MCP servers or plugins into model input. Find, in the 0.163.0
   source, the cleanest supported way (e.g. a dedicated `CODEX_HOME` at `__LOCAL_WORKSPACE__/v6-mac-env/s1/codex-home`
   whose `auth.json` is a symlink to `~/.codex/auth.json`, created with `ln -s` without reading it — check
   what Codex does to a symlinked auth.json on token refresh and whether that can break the user's main
   login; report). On the mock, prove with request-body diffs that the production home yields exactly the
   same model-visible request (instructions, input, tools) as the isolated probe home.
3. **Freeze S1 records** with a `freeze_s1.py` (refuse to overwrite):
   - `experiment-rules-s1.json` = S0 rules with only the model changed to `gpt-6.1-sol`; the script
     asserts that no other key differs and records the diff.
   - `technical-amendment-s1.json`: official pin, the four relaxations, catalog
     `__LOCAL_WORKSPACE__/v6-mac-env/work/official/catalog-gpt-6.1-sol.json` (sha `d5ec7a2ed2ca98f8308ecbf08da289efa33e2b6861566a80b9b5d93aba8d484b`),
     model_config `__LOCAL_WORKSPACE__/v6-mac-env/work/official/model-config-sol.json` (reasoning medium),
     re-recorded overhead (max 440,121 measured in `__LOCAL_WORKSPACE__/v6-mac-env/work/official/overhead/*.json` →
     `request_overhead_tokens=441000`; recompute the margin from the files, S0 max snapshot 222,711,
     admission 784,799), frozen-file hashes of the harness `src/`, `scripts/run_live.py` and every S1 goal script.
   - `registration-smoke-s1.json` from S0 `registration-smoke-v5.json`: model `gpt-6.1-sol`,
     `codex_version` `codex-cli 0.163.0`, official binary sha, new model_config, overhead 441000,
     `snapshot_format=explicit` with `format_decision_path` = the S0 file
     `__LOCAL_WORKSPACE__/v6-mac-env/s0-evidence/x/goal/ab-real-scoring-network-v1/format-decision.json`
     (sha `92691320…cfc`) plus an explicit field stating it is carried over from gpt-6-astra and is not
     sol evidence; fixture `__LOCAL_WORKSPACE__/v6-mac-env/work/sealed2/fixture.json` (verify sha equals S0
     `fixture_sha256`), same seeds/end_time/quality/session_budget/stall settings; drop S0
     `formal_exclusions`; new hashes for driver/auditor/dependencies. Must pass
     `harness_v6.registration.validate(..., results=True)`.
   - Smoke rule: one E1 attempt then one matching P2 attempt, stop on any failure, no retry.
   - Also prepare (do not run) the formal launcher for seed 1 (E1, P2) and later seeds 2, 3.
4. **Qualify on the loopback mock** (official binary, all through the real S1 driver except the
   test-only provider `base_url`):
   - Positive end-to-end: replay S0's adopted real outputs on the identical initial state —
     `s0-evidence/x/goal/smoke-E1-selfcheck-1*` (single_action) and `smoke-P2-selfcheck-1*` (mcp_session;
     raw responses are in the `*-native-trace` bundles). First check that the S1 cycle snapshot/prompt
     equals S0's for that cycle (report hashes; if different, explain exactly why). Both runs must be
     adopted and pass `audit_model_run_s1.py --smoke`, including idle and physical audits.
   - Negative: tampered trace (dropped/extra request, usage mismatch, extra tool, missing history,
     output over reserve), abort marker mid-session, hallucinated tool name, resource tool call —
     each must fail closed and stop the launcher before another model run.
5. **Physical auditor.** `audit_physical_prefix.py` imports `independent_physics.audit_prefix`, which was
   not published. The user may upload it to `__LOCAL_WORKSPACE__/v6-mac-env/s1/goal/independent_physics/`. If it
   is present, run `verify_independent_physics.py`-equivalent qualification (2 positive, 7 negatives).
   If it is absent when you finish, leave that check failing closed and report it as the blocker — do
   NOT write a replacement auditor and do not skip the physical audit.

## Verification to report (exact counts)

Python `__LOCAL_WORKSPACE__/v6-mac-env/venv/bin/python`, `PYTHONPATH=<harness>/src:__LOCAL_WORKSPACE__/v6-mac-env/physical`,
`TIKTOKEN_CACHE_DIR=__LOCAL_WORKSPACE__/v6-mac-env/tiktoken_cache`. Harness plain suite `python -m pytest -q`
(only if you touched the harness), all S1 qualification results as JSON under `goal/qualification-s1/`,
`compileall`. Finish with a report `goal/PHASE_V_REPORT.md`: files, decisions, the frozen numbers,
positive/negative results, auth__LOCAL_HOME__ findings, and anything unverified until the real smoke.
