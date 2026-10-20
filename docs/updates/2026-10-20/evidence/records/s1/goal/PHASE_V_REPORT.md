# Phase V — S1 official Codex stack (release blocked)

No real model requests. No credential was read, printed, copied, or modified. No real smoke, commit, push, or branch operation was performed. Harness source remains unchanged at `f6bcd8e699130c1fecf96f0eabcfbb377ff0a4ee`.

## Release status

**Blocked; not approved for real smoke.** The required byte-identical fixture gate fails: `__LOCAL_WORKSPACE__/v6-mac-env/work/sealed2/fixture.json` is SHA-256 `fb25761c6236f2cae66027497db6efdef21440037b1b231e53eb79b81eb155cf`, while S0 registered `d76827abb88c0ffdfbf4770a3b9fd4a119ff5416dd61deb968761a334e4ecd69`. There is no final `registration-smoke-s1.json`. The qualification-only registration explicitly records this rebind and the driver rejects its use without a loopback test provider. It is not authorization to change the production fixture.

`independent_physics.audit_prefix` is also absent. The unchanged physical auditor remains mandatory. Full smoke audits fail closed at that import; no replacement checker or bypass was introduced. Required physical qualification: 2 positives and 7 negatives, currently 0 executed.

## Files and policy

- `traced_runtime_s1.py`: S0 native trace wrapper, strict official interaction tool contract, absent `max_output_tokens`, admission/reserve from registration/model_config, and post-hoc output-reserve rejection. Named `harness_live` provider retains ChatGPT auth, disables websockets, has zero request/stream retries, disables all three proxy/retry features, and strips proxy environment names.
- `run_registered_s1.py`: frozen-file checks and registration validation, official pin, dedicated home, exclusive new outputs, no resume/retry. Production refuses provider overrides. Explicit test URL is restricted to HTTP on literal `127.0.0.1` with a port.
- `audit_model_run_s1.py`: model and admission ceiling from registration, no removed request-cap assertion; independent source, usage, adoption, idle and physical gates retained.
- `execute_registered_s1.py`: smoke E1 then P2; formal seeds 1, 2, 3 with E1 then P2 per seed. `--seed 1`, then later `--seed 2` and `--seed 3` are prepared; formal registration must follow smoke calibration. Stops on driver/auditor failure and never overwrites attempts. Not run against a real model.
- `cycle_artifacts.py`, `audit_idle_replay_v2.py`, `audit_physical_prefix.py`: copied byte-for-byte; 3/3 hashes match S0.
- `freeze_s1.py`: exclusive records, scientific rules differ only at `/model`. Final mode checks fixture equality before writing. The initial failed partial freeze is preserved in `failed-freeze-1/`.
- `qualify_s1.py`, `qualify_trace_s1.py`, and `qualification-s1/scripts/`: loopback replay and rejection evidence.

## Frozen numbers

Official binary `codex-cli 0.163.0`, SHA-256 `399ff69c431c066e40de318fba45c2b07f45a76b19939d247ee4828fc70c4215`.
Catalog `__LOCAL_WORKSPACE__/v6-mac-env/work/official/catalog-gpt-6.1-sol.json`, SHA-256 `d5ec7a2ed2ca98f8308ecbf08da289efa33e2b6861566a80b9b5d93aba8d484b`; model config `__LOCAL_WORKSPACE__/v6-mac-env/work/official/model-config-sol.json`, medium reasoning.

Eight overhead JSON recordings recompute maximum 440,121; registered overhead 441,000, rounding margin 879. Admission 784,799; S0 maximum snapshot 222,711; reserve 10,000; required sum 673,711; remaining admission margin **111,088**. The historical scientific rules' capacity numbers remain unchanged as requested; the technical amendment records the S1 operational values.

Four accepted relaxations: three visible MCP resource tools; host abort with unknown usage; no native per-request output cap; edited client catalog. Output reserve is a fail-closed post-hoc check, not a native output limit. Wall time is not a deterministic inference-count bound for hallucinated tools.

Format is explicit, carried over from gpt-6-astra, **not sol format evidence**. S0 format-decision hash is `92691320d46c9c9a14e8552676bd2b567b33f6d04a6ba791c25c5224e8c03cfc`. Quality, seeds, end time, session budget and stall settings are retained; S0 formal exclusions are dropped.

## Source and replay findings

The archived v6.5 patch changes 24 files and contains no rollout-trace change. Official `codex-rs/rollout-trace/src/inference.rs` writes the same request/response payload references, output items and token-usage structure. Native official replay bundles are accepted by the ported S0 audit. The published S0 archive replaces private reasoning with `publication_omitted`; replay uses all retained output items and recorded usage, does not invent omitted reasoning, and cannot certify byte-identical original opaque reasoning.

Both E1 and P2 complete cycle prompts and snapshots are byte-identical to S0. Complete initial records are **not** identical: each has 5,377 differences, consisting of the fixture source hash and 5,376 `problem.operations[*].remaining_work_seconds` floats, maximum absolute difference `1.862645149230957e-09`. No other initial-record differences were found. These are consistent with floating-point summation differences (local Python 3.10.12); the exact cause has not been independently established. Model-visible serialization removes these differences. Full hashes and every differing field are retained in `initial-state-comparison.json` and `initial-state-differences.json`. This does not waive the fixture gate or establish byte-identical initial state.

## Home/auth findings

Production home is `__LOCAL_WORKSPACE__/v6-mac-env/s1/codex-home`, separate from personal Codex state. Harness commands already use `--ignore-user-config`, `--ignore-rules`, `--ephemeral`, disable skill/plugin/app inputs, and the S1 wrapper adds `project_doc_max_bytes=0`. Official `config/src/loader/mod.rs::load_user_config_layer` returns an empty user layer when ignored. `CODEX_HOME` controls the separate state location. No personal config, AGENTS, skills, memories, MCP configuration, or plugins are copied.

The production-home and empty-probe-home E1 requests have exactly equal instructions/input content/tools after removing only message IDs and internal turn/time metadata. Raw diffs are retained, as is the empty model-visible diff; full request bytes are not falsely claimed equal. No prompt text, tool schema, role, ordering, or instruction content is normalized. Both tests disabled provider auth; this comparison does not validate real ChatGPT login.

A later orchestrator can create an auth symlink with `ln -s "$HOME/.codex/auth.json" __LOCAL_WORKSPACE__/v6-mac-env/s1/codex-home/auth.json` without reading its target. **That command was not executed.** Source `codex-rs/login/src/auth/storage.rs:215` saves with `OpenOptions.truncate(true).write(true).create(true)` and writes through the symlink, not an atomic replacement. Refresh can update the main login; interrupted writes or concurrent refreshes can damage/invalidate it. `auth/manager.rs::refresh_token` uses an in-process semaphore and guarded reload; this does not prove cross-process safety for two homes. The symlink isolates model input, not credential writes. Refresh and live authentication remain unverified.

## Verification

All executable tests use `__LOCAL_WORKSPACE__/v6-mac-env/venv/bin/python`, harness `src` plus `__LOCAL_WORKSPACE__/v6-mac-env/physical` in PYTHONPATH, and `__LOCAL_WORKSPACE__/v6-mac-env/tiktoken_cache` where tokenization is used. No harness edits, so the conditional plain harness suite was not rerun. Exact final counts are below and in `qualification-s1/manifest.json`. All mock processes have finished.

The request-body gate now verifies the complete original S0 user prompt before the mock emits each replayed response (`*-pre-replay-gate.json`). Exact text hashes:

| Item | SHA-256 (S0 = S1) |
| --- | --- |
| E1 prompt | `5266920c9136e102e7f9030388eca8dc64a06f8e685f4f7e21e172ac62fe2545` |
| P2 prompt | `0a36323e4ac77dd634fe876fb328f7adf2f691a4221e9c74a77d8aeeffbf57c7` |
| Snapshot text, both groups | `663599f14a93f5fc137b7dbdbea0775ac69e873f61c725cb0eda6150d9dc4472` |

Qualification revisions are retained in `qualification-s1/records-v1/` and `records-v2/`. The second revision added explicit immutable-registration preflight checks and CLI JSON reporting for audit failures. The third added the pre-response equality gate in the mock qualifier. Native runtime behavior remained unchanged across these revisions. Positive replay was repeated on fresh qualification directories after each change; no production attempt was made or retried. The latest technical amendment hashes 55 files, including all 14 S1 Python scripts and the requested harness source/run_live files.

The official source's `model-provider-info/src/lib.rs::to_api_provider` chooses `https://chatgpt.com/backend-api/codex` for ChatGPT auth when no base URL is supplied; the API-key default is `api.openai.com/v1`. This is a source finding, not a live connectivity/auth test.

The initial hallucinated-tool case exhausted the mock after the unsupported call and failed transport. An additional case supplied a valid final answer on the next request: native completion was healthy, but the wrapper rejected the two-request single-action session, and the host did not adopt it. This distinguishes trace enforcement from mock-exhaustion failure. For abort cases, `usage_unknown=true` and no complete usage is accepted. Zero-valued aggregate known-usage subtotals are not interpreted as zero session cost.


## Final counts and evidence

| Check | Exact result | Evidence under `qualification-s1/` |
| --- | --- | --- |
| Model traffic | **0 real requests; 23 loopback HTTP requests** | `wire-contract.json`, all `*-requests.jsonl` |
| Driver invocations | 12 total: 8 adopted qualification sessions, 4 rejected negative sessions; 3 unknown-usage sessions | `manifest.json` |
| Latest gated E1/P2 replay | **2/2 adopted**, native trace audits pass (1 and 3 requests respectively) | `gated-E1-result.json`, `gated-P2-result.json` |
| Before-response prompt equality | **7/7** checks across gated E1, gated P2, and production-home P2 | `*-pre-replay-gate.json` |
| Full independent smoke CLI | **0 passed; 2 failed closed**, both solely at missing `independent_physics` import after preceding evidence checks | `cli-smoke-E1.json`, `cli-smoke-P2.json` (final-E1/final-P2 cohort) |
| Idle replay | **4/4 passed**: initial and final-driver E1/P2 pairs | `idle-E1.json`, `idle-P2.json`, `final-idle-E1.json`, `final-idle-P2.json` |
| Trace tampering | **6/6 rejected**: dropped request, extra request, usage mismatch, extra tool, missing history, output over reserve | `trace-negatives.json` |
| Native failure cases | **4/4 rejected**: hallucination with exhausted mock, resource call, mid-session abort, hallucination followed by valid final answer | `native-negatives.json`, `hallucinated-completion-check.json` |
| Launcher stops | **10/10** stopped before a second driver invocation | `launcher-stop.json` (9) plus `hallucinated-completion-check.json` (1) |
| Registration preflight | **1 positive passed; 31 negative mutations rejected** | `registration-preflight.json` |
| Freeze gates | **2/2**: production fixture mismatch rejected; overwrite refused without changing records | `production-freeze-gate.json`, `freeze-overwrite.json` |
| Candidate registration validator | **1/1 passed**, `results=True`; qualification-only, not a final smoke registration | `registration-validation.json` |
| Home comparison, first request | **2/2 modes match** after only transport ID/turn-time metadata normalization | `home-comparison.json`, first round of `home-comparison-P2.json` |
| MCP entire-session home comparison | **1/3 request pairs equal; 2/3 differ** in visible wall-time headers only | `home-P2-round-*-visible.diff` |
| Independent physical qualification | **0/2 positives and 0/7 negatives executed**; blocked, not skipped as a pass | `physical-qualification.json` |
| Unchanged copied auditors/helpers | **3/3 byte-identical** | `copied-dependencies.json` |
| Frozen hashes | **55/55 match** | `frozen-hash-check.json` |
| Compileall | **14/14 S1 Python files compile** | `compileall.json` |
| Harness plain suite | **0 executed**; conditional requirement does not apply because harness source was untouched | `harness-status.json` |
| Git status / diff check | Clean; diff check exit 0; no commits, pushes, or branches | `harness-status.json` |

The launcher-stop tests feed actual observed rejection statuses into the real launcher's subprocess boundary; that boundary is mocked to prove no second launch without creating more model traffic. They are control-flow tests, not ten additional native runs. Negative runtime sessions and their raw request/trace/marker evidence are separate actual official-binary driver runs. Trace-tamper tests operate on retained native bundles offline.

The final-driver idle pair and smoke CLI pair precede the qualifier-only pre-response-gate change; driver, runtime, and auditor code are unchanged in the latest gated pair. Earlier qualification records and attempts remain available; their counts are not hidden or merged into two nominal smoke attempts.

MCP home findings are deliberately narrower than complete body equality. Both first requests are equal in model-visible instructions, input and tools. Later requests contain Codex-generated `Wall time: 8.5035 seconds` versus `8.7170 seconds`, then `5.4117` versus `5.4393`, from `codex-rs/core/src/tools/context.rs::McpToolOutput`. These are model-visible and were **not** normalized away. Complete later-request equality is therefore not established; the retained diffs show no other model-visible differences. No timing suppression or official-binary patch was introduced.

## Remaining work before real smoke

Supply the required byte-identical S0 fixture or explicitly resolve the fixture-registration discrepancy; then freeze a valid final smoke registration without overwriting retained evidence. Supply the unpublished `independent_physics` package, run its required 2 positive / 7 negative checks, and rerun the full independent audits. The raw-initial-state float differences, published reasoning omissions, and later MCP timing differences remain documented limits of exact replay/equality claims.

The orchestrator must arrange ChatGPT auth for the isolated home with awareness of symlink refresh semantics and obtain the user's real-smoke approval. Real endpoint/auth behavior, live billing/unknown usage, output-reserve failures against real provider output, and gpt-6.1-sol planning/quality/format performance remain unverified. This work provides mechanism evidence only; it does not authorize or substitute for the real smoke.


## Phase V2

The original fixture gate is now satisfied. The final registration validates with `registration.validate(..., results=True)` and the production S1 validator, and both positive runs pass the actual S1 driver preflight and end-to-end smoke audits. **Zero real model requests; no real smoke executed.** This section supersedes the earlier missing-fixture/missing-physics blockers, while preserving the original report and all earlier evidence. There are two qualification limits: full initial records remain nonidentical, and the seven mutation tests require a separately labeled offline continuation because the requested one-session replay prefixes contain no post-warm-up dispatch or completion.

Final records are `registration-smoke-s1.json` and **`technical-amendment-s1-v2.json`**. The earlier `technical-amendment-s1.json`, rules, qualification registrations and records were preserved. The driver now accepts the registration's explicit `engineering_amendment_path`, checks its registered SHA-256, and retains the previous filename fallback. The unchanged scientific rules were checked for equality rather than overwritten. New evidence is exclusively under `qualification-s1-v2/`.

- Final registration SHA-256: `55f9f6b2d3c11009950c959a35e7ca2c6d8e1fad0cdffbf60eb8d676d2c56f8d`.
- Final technical amendment SHA-256: `39dbff18fafd1831fa0d295cfc78e624d105a4f967d7df00d8b28e4686fb9246`.
- Original fixture: `__LOCAL_WORKSPACE__/v6-mac-env/s1/restored-mac-inputs/sealed/fixture.json`; SHA-256 `d76827abb88c0ffdfbf4770a3b9fd4a119ff5416dd61deb968761a334e4ecd69`, exactly S0. Its bytes were not rewritten.
- Mapping recorded in the amendment: `__HOME__/Downloads/大模型训练营/智能排程调研/validation/harness_v6_mac_20261018/inputs/physical` → `__LOCAL_WORKSPACE__/v6-mac-env/physical`.
- Original `verify_source` was observed calling `Path.read_bytes` on **20/20** input files through that mapped path; their computed SHA-256 values equal the manifest. Both positive independent physics audits report `verified_input_hashes=true` and `verified_source_semantics=true`. See `verified-input-hashes.json` for every path, resolved path, size and hash.

The five physics files were copied byte-for-byte and checked against the manifest obtained with `git show origin/archive/harness-v6-physics-fixture:docs/updates/2026-10-19/evidence/physics-fixture/manifest.json` in `__PROJECT_ROOT__`; no checkout occurred. All five are frozen:

| File | SHA-256 |
| --- | --- |
| `__init__.py` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `audit.py` | `a0b96922c76950f323a5c60bf34051419fc3955bfe982973c77bf7da9aa50cf1` |
| `audit_prefix.py` | `ac474f3595dc1fcde3254240b8057b9d7f191d17f21f5a268989c86225c8067f` |
| `manifest.json` | `9444bfbbd9e48123406e8c90347f3263db960da8c592aba175c07f01ea4fd859` |
| `source_check.py` | `973bf61ea9754101795cf6875967479ad0ca7fd65938bf2799405ceba4c4b786` |

Exact Phase V2 counts (separate from all Phase V counts):

| Check | Result |
| --- | --- |
| Traffic | 0 real requests; **11 loopback HTTP requests** |
| Real S1 driver invocations | 6: 2 adopted positives, 4 rejected native negatives; 3 unknown-usage sessions |
| E1 / P2 S0 output replays | **2/2 PASS**, respectively 1 and 3 requests; 4/4 positive pre-response complete-prompt equality checks |
| In-process full smoke audits | **2/2 PASS**, including independent physics and idle |
| Final full `audit_model_run_s1.py --smoke` CLI | **2/2 PASS**, including independent physics and idle |
| Retained CLI invocation failures | 3, due solely to omitted `--test-base-url`; no driver or model replay repeated to correct these |
| Physical positives | **2/2** original replay prefixes PASS, 5,356 events each; one additional offline continuation PASS |
| Seven S0 mutation classes | **7/7 rejected** on the supplemental continuation; scope below |
| Native negatives rerun | **4/4 rejected** |
| Launcher-stop rerun | **10/10 PASS**, no second driver invocation |
| Registration | 1/1 `results=True` validation and production validator PASS; actual preflight PASS in both positive driver runs |
| Frozen file checks | **64/64** match after qualification |
| Physics restoration | **5/5** archive hashes match |
| Source input hashes | **20/20** read and verified through mapped path |
| Compilation | **23/23** S1/package/qualification Python files compile in memory |
| Harness source | unchanged; clean git status and `git diff --check` exit 0; conditional harness suite not rerun |

The final CLI commands, including each recorded loopback URL, are in `cli-commands.json`. The three incorrect invocations are retained as `cli-smoke-E1.json`, `cli-smoke-E1-absolute.json`, and `cli-smoke-P2.json`; omitting the mock URL correctly fails the auth-mode assertion at `audit_model_run_s1.py:55`. The passing outputs are `cli-smoke-E1-final.json` and `cli-smoke-P2-final.json`. All six native runs used new isolated test homes and `model_providers.harness_live.requires_openai_auth=false`. Neither protected auth file was read, printed, modified, or used. The production-home auth symlink supplied by the orchestrator was untouched.

Physical mutation scope: both original replay runs stop at time **702.0**, immediately after adopting their plan. Their post-warm-up trace contains only one `plan_committed`; the entire prefix contains no `operation_complete`. Thus the exact requested mutation coverage cannot be obtained from those unextended prefixes. `continue_physics.py` restores a detached E1 checkpoint and advances the **unchanged adopted plan** to **1603.1**, with zero model calls and no registered-run resume, retry, altered fixture, or synthetic terminal. Its original trace prefix is verified unchanged. The separate continuation has 45 post-warm-up dispatches and 61 operation completions and passes independent physical/source auditing before mutation. Compact placeholder ledger observations are excluded by physical projection; no supplemental idle/performance claim is made. The original replay idle audits use their real records and pass.

The seven rejected classes and error counts are: wrong registered seed **216**, wrong warm-up boundary **4,875**, changed processing duration **1**, changed machine release **1**, changed transport duration **1**, dropped due completion **14**, and **foreign dispatch source** rejected by `audit_plan_sources`. As in S0, the seventh check uses the unprojected trace because projection omits plan commitments. `physical-qualification.json`, `offline-continuation.json`, and `continuation-provenance.json` distinguish these scopes explicitly. The frozen initial `qualify_physics.py` is retained but was not run; `qualify_physics_extended.py` records the necessary scope adjustment. Supplemental scripts and evidence have hashes in `qualification-s1-v2/manifest.json`.

The driver changed, so native rejection and launcher-stop tests were rerun. Runtime, model auditor, physical auditor, idle auditor, and launcher stayed unchanged by hash:

| File | Current SHA-256 | Same as Phase V |
| --- | --- | --- |
| `run_registered_s1.py` | `d71195448b888f9e3460001a04a198db5f6ab26e8b8f9313e19396f49f32edfe` | no |
| `traced_runtime_s1.py` | `c755ef7d240bfb5033839ffafe1501062989d35df3226f0cc372a94d709e0bd7` | yes |
| `audit_model_run_s1.py` | `fe130fa819a1bb91c54c051c3605deb6719ea937f355bc991fedade1a2bccc3e` | yes |
| `audit_physical_prefix.py` | `6d1b0ed9152167302fd1bcfde40822787997fad29c580e7ba345b65a76244d0d` | yes |
| `audit_idle_replay_v2.py` | `c0f580ef0f846f6eb9ef37793f23f1657c6b56345b975f4450be00270b8a7757` | yes |
| `execute_registered_s1.py` | `1d1adb2d67ceb455e5f09b4d7d97c3a41e0bd8f0c39608d7cee5540515317790` | yes |

Native cases were hallucinated tool with exhausted mock, resource-tool call, mid-session abort, and hallucinated tool followed by a valid final answer. The last completes natively but is rejected for excessive requests in a single-action session. Launcher tests use these four fresh rejection results plus the six retained offline trace-tamper cases; the unchanged auditor's six tamper cases were not rerun. Launcher subprocess boundaries are mocked control-flow checks, not additional model sessions.

Initial records are **not byte-identical**, contrary to the expectation that restoring the fixture would resolve every difference. Each group now has exactly **5,376** differences, all `problem.operations[*].remaining_work_seconds`, maximum absolute difference **1.862645149230957e-09**; the former fixture-source-hash difference is gone. Exact cause remains unverified; no normalization or numerical adjustment was introduced. Full field differences are retained in `initial-state-differences.json`.

| Group | S0 initial SHA-256 | S1 initial SHA-256 |
| --- | --- | --- |
| E1 | `2d491fbc2b89e76579a7192c0f62e4c4bcd9d1cc8e9efc880f69b1a2355c262a` | `a57fa82571a5a7a674c03060fb69baea81d1f42e6505bf6ce02b0dc22ef25327` |
| P2 | `f9de5d0db795a25e37fc9f4b63e117b96d929cb5677ea841343915522d755143` | `245afc6f5fc1035157a7586efed4f9fdc10ee3e27523e1388dfe4004f4126a73` |

Complete model-visible prompt hashes still equal S0: E1 `5266920c9136e102e7f9030388eca8dc64a06f8e685f4f7e21e172ac62fe2545`, P2 `0a36323e4ac77dd634fe876fb328f7adf2f691a4221e9c74a77d8aeeffbf57c7`; snapshot text, both groups, `663599f14a93f5fc137b7dbdbea0775ac69e873f61c725cb0eda6150d9dc4472`.

Frozen capacity numbers are unchanged: eight overhead recordings, maximum **440,121**; registered overhead **441,000**; rounding margin **879**; admission **784,799**; S0 maximum snapshot **222,711**; output reserve **10,000**; required sum **673,711**; remaining admission margin **111,088**. Binary SHA-256 remains `399ff69c431c066e40de318fba45c2b07f45a76b19939d247ee4828fc70c4215`, catalog SHA-256 remains `d5ec7a2ed2ca98f8308ecbf08da289efa33e2b6861566a80b9b5d93aba8d484b`.

Exact real-smoke command, **prepared only, NOT run**, also saved in `qualification-s1-v2/real-smoke-command.sh`:

```bash
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=__PROJECT_ROOT__/docs/updates/2026-10-17/project/experiments/harness_v6_20261017/src:__LOCAL_WORKSPACE__/v6-mac-env/physical \
TIKTOKEN_CACHE_DIR=__LOCAL_WORKSPACE__/v6-mac-env/tiktoken_cache \
__LOCAL_WORKSPACE__/v6-mac-env/venv/bin/python __LOCAL_WORKSPACE__/v6-mac-env/s1/goal/execute_registered_s1.py \
  --registration __LOCAL_WORKSPACE__/v6-mac-env/s1/goal/registration-smoke-s1.json \
  --phase smoke
```

Still unverified: byte-identical full initial state; the seven mutation classes on the unextended requested smoke prefixes (structurally unavailable); exact original opaque reasoning omitted from the published S0 archive; later-request MCP wall-time equality; live authentication/refresh and endpoint behavior; real-provider usage/billing and reserve enforcement; gpt-6.1-sol planning, quality and format performance. The separate continuation supplies physical mechanism evidence, not a longer registered model run or a waiver of those limits. No real smoke, commit, push, branch change, credential access, or overwrite of prior evidence occurred. Real smoke remains for the orchestrator.
