# Phase W — blocked by frozen fixture coverage

S1 preparation cannot proceed with the required original fixture. Its `mixed_702.state.horizon` is **3600.0**, whereas the requested endpoint is **4302**. The unchanged harness additionally requires coverage through `end_time + horizon_seconds`. Both arms fail that gate before a runner is constructed. No real or mock model request was made. No credential file was accessed. `goal/`, the original fixture, and harness source were not modified; no commit or push occurred.

## Verified blocker

| Arm | Start | End | Δ / delta_min | H | Required physical horizon | Available | Shortfall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| P2 d300 | 702 | 4302 | 300 / 300 | 900 | 5202 | 3600 | 1602 |
| P2 d900 | 702 | 4302 | 900 / 900 | 2700 | 7002 | 3600 | 3402 |

`check_fixture_coverage.py` verifies the fixture hash and executes the exact AST-extracted horizon guard from `scripts/run_live.py::execute` for both arms. Both raise `ValueError: fixture horizon must cover end_time + horizon_seconds`. This is two coverage checks, **not** two driver runs or physical audits. Reproducible evidence and source hashes are in `fixture-coverage.json`; the checker uses exclusive output creation.

The fixture SHA-256 is `d76827abb88c0ffdfbf4770a3b9fd4a119ff5416dd61deb968761a334e4ecd69`, matching the final S0 registration. The fixture's physical-data path is `__HOME__/Downloads/大模型训练营/智能排程调研/validation/harness_v6_mac_20261018/inputs/physical/data/smt/SMT2020_LVHM`, mapped to `__LOCAL_WORKSPACE__/v6-mac-env/physical/data/smt/SMT2020_LVHM`.

`DECISIONS_v6.md` explicitly says fixture calendars cannot be extended by changing horizon. `factory_v6.restore` constructs the physical environment using the frozen horizon and restores the recorded calendars and queue. Changing the scalar or bypassing the coverage guard would not establish valid longer calendar coverage. A new, independently qualified longer fixture is required, with coverage through at least **7002**, preserving and verifying the original t=702 physical state and prehistory as applicable. This changes the user's fixed fixture/hash constraint, so authorization or a supplied replacement is needed.

## Fixed decisions retained

Use **4302 exactly**, giving 3600 simulated seconds. S0's `1603.1` is an explicitly chosen numeric cut; no generic “add 0.1” endpoint transformation exists in the driver. `LiveRun.step` advances to the requested endpoint, then returns before opening a decision session when `now >= until`. Thus decision times are before the cut, and physical metrics are measured through the cut. Adding 0.1 would make S1 longer than one hour. The historical sealed-context builder separately uses a common endpoint of `1603.1013031725258`; this does not define a general endpoint epsilon.

Set `delta_min = Δ` in each arm. `CycleConfig.for_stage` permits these values and sets H to `max(3Δ,900)` and breakdowns=false for S1. It does not require delta_min=60. Keep P2 periodic/mcp_session, seed 1, one formal trajectory per arm; seeds 2 and 3 are reference-only. Preserve the session budget, failure policy, stall settings, explicit format and official pin/model configuration.

The final S0 registration uses `stage: S1` and phase `formal_S1` as port-era labels despite its S0 window and Δ=60. Those labels alone do not establish one-hour qualification. `PHASE_V_REPORT.md` includes historical blockers superseded by its V2 section; the new fixture-duration blocker is separate.

## Reference and admission status

| Arm | Reference seeds | Completed references | Sessions / throughput / tardiness / idle | Every-cycle tokens / maximum | Admission margin |
| --- | --- | ---: | --- | --- | --- |
| d300 | 1, 2, 3 | 0 | Unmeasured: fixture coverage fails | Unmeasured | Unmeasured |
| d900 | 1, 2, 3 | 0 | Unmeasured: fixture coverage fails | Unmeasured | Unmeasured |

The actual S0 Δ mechanism script is `__LOCAL_WORKSPACE__/v6-mac-env/s0-evidence/x/goal/run_delta_mechanism.py`, which invokes `scripts/run_live.py --dry-run-scripted` and its public-prompt `prompt_action` planner. `measure_model_delta.py` measures plan-delta encoding size; `replay_triggers.py` describes anchors on one frozen plan history and explicitly is not a causal scheduling counterfactual. They cannot alone produce the requested new reference trajectories.

Admission remains `max snapshot + 441000 + 10000 < 784799`, leaving **333799 tokens** before snapshot/prompt payload; strict inequality requires a snapshot below that threshold. The actual runtime also checks the complete prompt including cycle footer. No one-hour admission pass or failure has been established. Do not substitute the S0 maximum of 222711 for an S1 maximum.

Existing overhead recordings cover `g0`, `public-702`, `public-1182`, and `public-1602` in both interaction modes. They do not certify states through 4302 or the enlarged H=2700 view. The S0 report records maximum overhead 440121, rounded to 441000. Worst-state loopback re-recording remains required after valid longer references exist. `__LOCAL_WORKSPACE__/v6-mac-env/official-diag/record_overhead.sh` documents the method but removes old output directories; it was read only and must be adapted to new exclusive paths before reuse.

## Remaining dependent work

No smoke registrations, scientific rules, technical amendment, formal freeze script, or real launch commands were frozen: their required reference-derived values and admission evidence are unavailable. Creating passing-looking records with S0 numbers would misstate readiness.

After fixture resolution, derive per-arm quality floors from the scripted reference (mechanism evidence only), with throughput/tardiness tolerances zero and idle tolerance 10% of the reference integral, and explicitly document the seed aggregation rule. Recompute finite guard caps using S0's 1.25 margin and rounding: for reference session bound N and exactly one hour, requests `100 * ceil(1.25 * N * 4 / 100)` and tokens `1000000 * ceil(1.25 * N * 2500000 / 1000000)`. These are engineering guards, not user spend caps; formal smoke calibration must follow the S0 method.

Estimated formal input use remains **N × 0.55M tokens per arm**, approximately 66% cached (0.363M cached and 0.187M uncached per session), based on the user-supplied S0 P2 estimate. Including one smoke adds approximately 0.55M input tokens per arm. N is not yet measured, so no numeric per-arm total is claimed. Real one-hour behavior may change both session counts and per-session usage.

Driver/runtime/auditor adaptation, registration validators, multi-session loopback replay, full idle/physics audits, and checkpoint/resume qualification are unexecuted. Audit duration and peak memory for the requested reference are **unmeasured**, not inferred from S0. No launcher-stop/native negative rerun was needed yet because those components were not changed. Harness git status and diff check were clean; the conditional plain suite was not run because source was unchanged.

The intended eventual real sequence remains smoke d300, smoke d900, formal freeze from audited smoke usage, formal d300, formal d900, stopping on failure. No runnable real commands are issued at this blocked stage. No real smoke or formal trajectory was run.

## Resolution requested

Supply a longer, qualified fixture, or authorize generating and qualifying one from the original physical inputs with a new registered hash. This request arises from the user's fixed original-fixture requirement and the existing harness coverage gate, not from a skill or automatic approval rejection. The original S0 evidence must remain read-only.


## Phase W2

The user-authorized option A resolves the fixture-coverage blocker. A new **36,000-second** `mixed_702` has been reconstructed and qualified under a new hash. **S1 results will not be byte-comparable with S0.** The original fixture and `goal/` remain untouched. Overall Phase W release status depends on the reference/admission findings recorded below; successful fixture qualification alone is not release approval.

The registered new fixture is `__LOCAL_WORKSPACE__/v6-mac-env/s1/stage-s1/fixture/sealed-36000/fixture.json`, SHA-256 **`07afb411bbd691bad487ef5f515fde330300667ae168c134ec8eae7ef7dbc772`**, **226,961,987 bytes**. Both arm registrations bind this same path and hash. The original S0 fixture still hashes to `d76827abb88c0ffdfbf4770a3b9fd4a119ff5416dd61deb968761a334e4ecd69`. `fixture/fixture-registration.json` records the explicit window, input/source hashes, Linux mapping, and the S0 comparability exclusion.

### Construction and size decision

`build_public_fixture.py` uses `window_seconds=10000` for a separate greedy **public_702** warm-up. It is not the source of sealed `mixed_702`. `build_sealed_fixture.py` imports the archived state/trace verbatim. The original `B_coverage_ablation_20261015/experiment.py::prepare` selected the saved live-B execution batch ending at 702.0 and its complete physical prefix. `factory_v6.restore` reinstantiates with the saved horizon and restores the saved state; it is not a calendar-extension facility. The earlier physical harness has `default_config(seconds=3600)` → `window_seconds=seconds`; its runtime passes that value to `FullFabEnvironment`, whose base adapter sets `horizon=float(window_seconds)`. The saved prefix records 3600.0. These defaults remain untouched; `fixture/horizon-lineage.json` records the source hashes and original parent run `run:807710f971804da69f18b099`.

`build_long_fixture.py --window-seconds N --output NEW_DIRECTORY` replays the original **31 accepted plans, 10 time-advance boundaries and 31 coverage-gap observations** using the original physical `FullFabEnvironment` and executor. No new scheduling decisions or model requests enter warm-up. The constructor's explicit `window_seconds` is the only physical configuration change; no defaults were edited. Warm-up seed remains **1701**, boundary **702.0**, and subsequent reference seeds are assigned by unchanged `run_live.py` semantics. A 3600-second control reconstruction has **zero state/trace differences**, validating this replay method against the original archived seed. `register_fixture.py` additionally asserts that the archived seed's state/trace equals the actual S0 fixture's `mixed_702`, rather than merely assuming the archives match.

| Construction | Execution seconds | Peak RSS KiB | Fixture bytes |
| --- | ---: | ---: | ---: |
| Control 3,600 | 14.986406870 | 373,024 | 9,009,307 |
| Benchmark 7,200 | 15.623291985 | 151,808 | 9,009,307 |
| New mixed state 36,000 | 15.414383491 | 153,668 | 9,021,948 |
| Seal with unchanged historical validation cases | 106.736795337 | 1,382,948 | 226,961,987 |

The pre-build conservative 5× extrapolation from 7200 was **78.116459926 seconds**, **759,040 KiB**, and **45,046,535 bytes** for the reconstructed state. Historical validation cases and their 998-MiB context database are fixed ancillary overhead, not multiplied by horizon. Actual reconstruction plus sealing took **122.151178828 execution seconds**; sealing's measured peak is **1.318882 GiB**. The 36,000 target therefore stayed below both the approximately 4-GB memory and 90-minute build thresholds; no 7200 fallback was needed. All generated artifacts use new paths below `stage-s1/fixture/`; source and S0 artifacts were not overwritten.

### Exact state and prehistory comparison

`fixture/comparison.json` gives semantic counts; `fixture/reconstructed-36000/differences.json` retains every raw recursive difference path and type.

- **5,355 events** in both prefixes; **5,354/5,355 events identical**. Every event after the initial manifest is exactly identical, including all decisions, dispatches, sampled durations and physical events through 702. The initial manifest differs, so the complete raw prehistory is **not** identical.
- Raw recursive comparison has **14,198 differences**: state horizon 1; state lots 20; state manifest 123; state queue 13,930; state queue sequence 1; initial trace manifest 123. List length changes count as one difference and common indices are compared verbatim; heap/list shifts explain many raw differences.
- The **2,177 shared lots** have **zero changed values**. Exactly **20 future unreleased lots** are added, ten each at **15507.599999999999** and **31015.199999999997** seconds. None release during S1.
- Jobs, machine states, calendars, accepted plan, waiting state, statistics and other shared state fields are identical. Changed top-level state fields are exactly `horizon`, `lots`, `manifest`, `q`, and `seq`.
- Queue length changes **4413 → 4433**, and sequence counter **6606 → 6626**. Comparing queue events by time/kind/payload instead of internal heap position/tie-break IDs finds **zero removed events and exactly 20 added releases**. This is an explanatory comparison only; the fixture itself was not normalized or repaired.
- Randomness remains event-keyed SHA-256 with **no mutable global RNG**. Calendars are constructed from the original distributions and recur lazily through physical execution; there are no changed calendar distributions or prehistory random draws. The new future release inventory comes from the same original order table under the longer constructor window.

All **20/20 physical input hashes** match S0. The independent auditor separately reports `verified_input_hashes=true` and `verified_source_semantics=true`. Linux data path: `__LOCAL_WORKSPACE__/v6-mac-env/physical/data/smt/SMT2020_LVHM`; the original Mac physical root mapping is explicitly retained in the fixture registration.

### Fixture qualification

The unchanged `validate_sealed_fixture.py` completed with exit 0 in **604.701618084 seconds**, peak **1,608,644 KiB**. Round-trip equality is true; round-trip digest is `8853df30657089efeec8861c0814e2176e597ee9dc250d1f14ff86ebfdfc81a9`. Historical classification remains **G0/G1/G2 = 10/15/4**, with **two exceptions**. Physical equivalence replay through **1603.1** matches **128 events**. Historical G0 checks retain 23 pending tasks, 26 accounted base tasks, 907 running jobs, and a 177,243-token snapshot. These historical cases are retained validator evidence, not new one-hour reference results.

Independent physics qualification on a detached seed-1 continuation of the first archived G0 accepted plan gives **1 positive PASS + 7/7 rejected mutations**, with 5,965 trace events, 21 post-warm-up dispatches and 61 operation completions. It covers **702 → 1603.1**, not a full one-hour S1 reference. Total profiled qualification time was **64.641595313 seconds**, peak **1,608,980 KiB**. Error counts: wrong registered seed **94**; wrong warm-up boundary **4870**; processing duration **1**; machine release **1**; transport duration **1**; dropped completion **5**; foreign dispatch source **1**. The seventh uses the unprojected plan-source auditor, as in S0. The independent physics files and copied auditors are unchanged by hash.

The first retained physics attempt also passed its positive archived replay, but its warm-up-boundary mutation was ineffective because prehistory and continuation both used seed 1701. It failed the qualification assertion rather than claiming a rejection. `physics-qualification-v2` uses the actual S1 seed switch to 1; the auditor was not changed. Both attempts and their timing/logs are retained.

### Fixed S1 decisions and initial admission

Endpoint remains **4302 exactly**, for 3600 simulated seconds; no generic +0.1 convention exists. `delta_min=Δ`; H remains 900 for d300 and 2700 for d900. Physical coverage needs 5202/7002 respectively and is satisfied by the new 36000 horizon. Explicit presentation, P2 periodic/MCP interaction, model, official pin, catalog, reasoning, session budget, failure policy and stall settings remain unchanged.

| Initial t=702 arm | Snapshot tokens | Complete prompt tokens | Snapshot + 441000 + 10000 | Margin to 784799 |
| --- | ---: | ---: | ---: | ---: |
| d300, H=900 | 173088 | 173511 | 624088 | 160711 |
| d900, H=2700 | 222666 | 223089 | 673666 | 111133 |

Complete prompt counts use the actual frozen cycle footer numeric types; the exploratory integer-footer counts are preserved in `initial-admission/measurements.json` and corrected in `production-prompts-correction.json`. These are **initial-state measurements only**, not full-trajectory maxima. The d900 reference's actual first snapshot independently matches 222666 tokens and SHA-256 `a58b1b41da6f69bf860eabc67b404cb741d58406ca2f174cfe37692a653a6496`. Three-round initial d900 MCP overhead was re-recorded with the pinned official binary, empty isolated homes and provider authentication disabled: **8 loopback HTTP requests, zero real requests**, common measured overhead **396810**, retaining the larger **441000** floor. Recording took **54.907956660 seconds**, peak **444,212 KiB**. Dense was used only as the recorder's paired pressure representation; production remains explicit. This recording does not certify later or worst-case states.

`quality-derivation-policy.json` records the rule before completed results: per-arm seed-1 scripted floors, 10% idle tolerance, zero throughput/tardiness tolerance; seeds 2 and 3 are supplementary mechanism results, and the maximum session count across the three seeds determines guard caps. Numerical quality criteria remain dependent on completed references and admission.

The original copied offline registration retained a stale S0 `fixture_sha256` field even though its path and actual run-manifest hash selected the new fixture. That attempt was interrupted after its first completed cycle and preserved in `references/`. Corrected registrations and new attempts are in `references-v2/`; their path, declared hash and actual manifest hash agree. Later scheduler handoffs leave the corrected d900 reference uninterrupted. This is offline mechanism work, not a model retry.

`source-comparison.json` shows 8/9 inspected active files equal the S0 archive. The sole pre-existing difference is `run_live.py` calling `require_official_pin` instead of `require_isolated_pin` on the non-scripted path; its exact diff is retained. No harness source was changed during W2. The conditional harness plain-suite requirement therefore does not apply. Preparatory driver/runtime/auditor copies and a guarded real-launch script exist, but they are not release-ready until the remaining gates pass.


## Phase W3

Status: **incomplete — blocked by shared-container memory, not released for real runs**. W2 was interrupted around 16:24 UTC on 2026-10-19 when the orchestrator session ended; its child processes stopped. W3 preserved every interrupted artifact and did not rerun any completed reference. No real or mock request was made in W3, no auth file was accessed, no harness source was modified, and no commit/push occurred. Original fixture, S0 evidence and `goal/` remain untouched.

Verification evidence: `retained-verification-w3.json` (SHA-256 `fda00f249f19e827df8cb81963aee9660316b3d01af53f6663391e698055ffcf`), generated by `verify_retained_w3.py`. Recomputed fixture SHA-256 is `07afb411bbd691bad487ef5f515fde330300667ae168c134ec8eae7ef7dbc772`. The verifier checked exact manifest/registration equality, fixture bindings, registered endpoint, failures/unknown usage, and hashes of available content-addressed checkpoints. It also recorded fresh SHA-256 hashes of every retained file in the three completed references and the interrupted reference. Rotated checkpoint files absent from disk are explicitly listed, not claimed verified. This verification is not an independent idle/physics audit.

| Reference | Sessions | End | Throughput | Weighted tardiness | Avoidable idle integral |
| --- | ---: | ---: | ---: | ---: | ---: |
| d300 seed 1 | 12 | 4302.0 | 2 | 4242.296694920063 | 51457.61149434129 |
| d900 seed 1 | 4 | 4302.0 | 1 | 0 | 146897.46876950562 |
| d900 seed 2 | 4 | 4302.0 | 1 | 0 | 146353.25077999328 |

All three stop at `registered_end`, start at 702, and report zero failures and zero unknown usage. Original process exit codes are not inferred from summaries. `references-v2/d300-seed2` retains **six cycles and no summary**; it must be rerun into a new directory. d300-seed3 and d900-seed3 remain unstarted. No remaining reference was launched because the memory gate failed.

Seed-1 mechanism quality criteria, now derived from verified summaries (not model quality evidence):

| Arm | Throughput floor | Weighted tardiness floor | Idle integral floor | Idle tolerance |
| --- | ---: | ---: | ---: | ---: |
| d300 | 2 | 4242.296694920063 | 51457.61149434129 | 5145.761149434129 |
| d900 | 1 | 0 | 146897.46876950562 | 14689.746876950563 |

Throughput and tardiness tolerances are zero. Guard caps remain unfrozen until all three seeds per arm complete. Based on seed 1 alone, estimated formal input is 6,600,000 tokens for d300 and 2,200,000 for d900; with one smoke each, 7,150,000 and 2,750,000. These use the supplied 550,000 input tokens/session estimate, approximately 66% cached, and are not measured S1 model usage.

The retained `overhead/d900-cycle4.json` confirms **470,796** common overhead tokens and **247,090** explicit snapshot tokens. The minimum rounded S1 overhead bound is therefore **471,000**, giving snapshot admission margin **56,709** (`784799 - 247090 - 471000 - 10000`). This is a retained single-state result, not final six-reference admission. The final registration must use at least the rounded maximum across all required recordings; 441,000 is insufficient. Complete-prompt margins and worst tool-payload recordings across all six references remain pending.

Retained checkpoint qualifications report PASS for d300 **1602→1902** and d900 **2502→3402**, with identical full physical state/trace and exact cumulative metrics. These end before the next decision, add zero sessions, and preserve 4/3 prior sessions respectively. Follow-on session attempts were interrupted: pre-session artifacts exist, but `session-result.json` does not exist for either arm. Preserve those attempts and use fresh directories for any new qualification. No full independent one-hour audit result/duration/peak-memory measurement is available.

Memory prevented further execution: first observed `/sys/fs/cgroup/memory.current` was **10,679,988,224 bytes**; verification recorded **10,730,102,784 bytes**; the final check was **10,732,240,896 bytes**, against `memory.max` **10,737,418,240 bytes**. All exceed the user ceiling of approximately 8.5 GB. W3's verifier used streaming file hashing; no reference/audit process was started. Unrelated processes were not terminated and shared caches were not forcibly reclaimed. The user was asked to free memory from other workloads.

Remaining gates: three new offline runs; all-cycle token inventory and worst-state overhead capture; final positive admission per arm with the shared measured overhead bound; maximum-three-seed guard caps; frozen rules/amendment/registrations and validators; driver mock qualification and full independent audit profiles; restored follow-on session checks; applicable launcher-stop/native negative qualification. Existing prepared command files describe smoke d300 → audited smoke d900 → formal freeze → formal d300 → formal d900 with audits and stop-on-failure, but are **not release-ready** and were not executed. Frozen registration files and release readiness were not fabricated.

## Phase W5 (fast path)

Status: **ready for the orchestrator to start; NOT started**. User decision 2026-10-19: 提速. W5 lives exclusively in `stage-s1/w5/` so the remaining W4 background references/audits and their pending freeze cannot collide with it. No existing background job was killed or awaited. Use **w5/release-readiness.json**, not any later W4 release file. No real model request, auth-file access, harness-source change, commit or push occurred. Original fixture, S0 evidence and `goal/` were not modified.

Skipped by authorization: d300 seeds 2/3 and d900 seed 3; six-reference worst-state search; full-hour mock replays/audit timing and restored follow-on-session qualification. The three-seed session bound was unavailable and is **not claimed**. Completed references were checked for registered_end, 702→4302, zero failures/unknown usage, matching fixture/seed and dry-run manifest. Their summary/manifest hashes are frozen in the technical amendment. Quality remains seed-1 mechanism evidence only.

| Arm | Reference seeds | Session bound | Requests/hour cap | Tokens/hour cap | Snapshot max | Complete prompt max | Measured overhead | Snapshot margin | Prompt margin |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| d300 | 1 | 12 | 100 | 38000000 | 193555 | 193979 | 325374 | 110244 | 109820 |
| d900 | 1, 2 | 4 | 100 | 13000000 | 247090 | 247514 | 470796 | 56709 | 56285 |

Shared registered overhead: **471000**, maximum measured rounded up to 1,000 with 471,000 minimum. Limit 784,799; reserve 10,000. d300 largest is cycle 12 at 4002; d900 cycle 4 at 3402. Every seed-1 snapshot is inventoried in w5/reference-token-inventory.json. New d300 recording uses the pinned binary, loopback provider, isolated homes, auth disabled, explicit and dense pressure recordings (production remains explicit).

Largest explicit snapshot hashes: d300 `8647d878334392ef80ba0995118bb3a3ecfffad7773dd847d494913da0432918`; d900 `bc3847ebb82c5e478f0b6289e274a400ea795e26e9d40e67afa92f6f69507670`. Input-use estimates remain 6.6M (d300) and 2.2M (d900) formal tokens, or 7.15M/2.75M including smokes, based on S0 0.55M/session and approximately 66% cached; real smoke calibration supersedes these estimates.

Runtime admission is checked again for every complete prompt in unchanged harness_v6/live.py::LiveRun.step, before runner invocation. A later state exceeding prompt + overhead + reserve capacity stops with context_budget_exceeded before any model call; no rows are dropped. A state merely larger than the observed reference maximum can still fit the registered capacity. Measured overhead is an engineering bound, not proof about unobserved future tool payloads.

| Arm | Throughput floor | Tardiness floor | Idle floor | Idle tolerance |
| --- | ---: | ---: | ---: | ---: |
| d300 | 2 | 4242.296694920063 | 51457.61149434129 | 5145.761149434129 |
| d900 | 1 | 0 | 146897.46876950562 | 14689.746876950563 |

Throughput/tardiness tolerances remain zero. Guard formula: 100×ceil(1.25×N×4/100) requests and 1,000,000×ceil(1.25×N×2,500,000/1,000,000) tokens per hour. Fixture SHA-256: `07afb411bbd691bad487ef5f515fde330300667ae168c134ec8eae7ef7dbc772`; new-fixture S1 is not byte-comparable with S0.

Qualification: four registrations pass generic results=True and stage validation; registration mutation qualification: 4 positives, 126 rejected negatives. Actual launcher control flow passes 5 subprocess-boundary tests: driver failure, smoke audit failure, formal driver failure, formal audit failure, and full order. No native runtime/auditor semantics changed; those copied files match prior hashes.

- d300: one real-driver loopback session, 3 mock HTTP requests, zero real requests; adopted plan and independent smoke/native-history/usage/physics/idle audit PASS. Driver 155.851s; audit 80.649s, peak RSS 2636292 KiB. Audited interval 702.0→702.0; smoke stops after submission before physical advancement. These are smoke measurements, not full-hour audit estimates.
- d900: one real-driver loopback session, 3 mock HTTP requests, zero real requests; adopted plan and independent smoke/native-history/usage/physics/idle audit PASS. Driver 151.313s; audit 79.765s, peak RSS 2637216 KiB. Audited interval 702.0→702.0; smoke stops after submission before physical advancement. These are smoke measurements, not full-hour audit estimates.

Memory limitation: shared anonymous memory was observed at 7,629,258,752 bytes during the d300 smoke audit, above the approximate 7-GB target. W5 qualifications remained sequential and no additional heavy process was started during that audit; existing background jobs were untouched. Audit peak RSS is reported separately above; sparse shared-memory observations are not a complete peak profile.

The initial freeze wrote its exclusive records but failed its final validation because the relocated, byte-identical validator expected stage-s1/goal/registration-formal-s1.json. The retained freeze log records that failure. A read-only symlink for that single S0 registration restores the expected lookup; complete_freeze_validation_w5.py then verified all frozen hashes and all four registrations without overwriting any record. The original S0 file is untouched.

The launcher runs smoke d300 → audit → smoke d900 → audit → formal freeze using audited real smoke usage (S0 method) → formal d300 → formal d900. Formal audits run in background; before each next driver it rejects any finished failed audit, and waits for all audits at completion. As in S0, an already in-flight driver finishes if a background audit fails. Driver failures immediately prevent later runs. Exclusive logs, output checks and a persistent exclusive pipeline.lock prevent overwrites, retries or concurrent starts. All artifacts are retained.

**Resume is unsupported by this frozen S1 driver:** it has no --resume argument, rejects existing outputs, and passes resume=False to run_live.execute. The launcher accepts --resume only to reject it before acquiring a lock or making a model call. Underlying harness checkpoint capabilities and prior offline recovery evidence do not qualify production recovery. An interruption requires a separately reviewed/qualified host-state recovery; never load old model history or delete artifacts to retry.

Exact start command (prepared only; bash noclobber protects the launcher log; setsid/nohup detach the pipeline and its children from the orchestrator terminal):

```bash
bash -c 'set -o noclobber; setsid nohup __LOCAL_WORKSPACE__/v6-mac-env/s1/stage-s1/w5/run_real_stage_s1_w5.sh </dev/null >__LOCAL_WORKSPACE__/v6-mac-env/s1/stage-s1/w5/real-launch.log 2>&1 &'
```

System/container shutdown still interrupts detached processes. No real launch has been performed. Formal registration files intentionally do not exist until both real smokes pass and the unchanged S0 calibration method freezes them.

| Frozen artifact (under w5) | SHA-256 |
| --- | --- |
| `memory-observations.json` | `1453ef06157345ca1c18a6b87fbc0c75d4ffe8051b04263e04417e5723878861` |
| `resume-rejection-check.json` | `6b940b0e70ef32a0a76a9abfd7eafaa29b3904410fab7ecbdd51b4a0555f890d` |
| `complete_freeze_validation_w5.py` | `1067164c5ca03f91b8b3d5cadb25d9a2bc95c4bb5f65ffedf48cc94b449d0c4a` |
| `copy-comparison.json` | `7d8aab04aa6922fa81496a847281fbfd85478d2eb0ed45b7736e46e936636414` |
| `copy-comparison.diff` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `experiment-rules-stage-s1.json` | `50b2cd8e220d23e4bc1fa5501193031fe7b99955853d813b126f455d20102da4` |
| `technical-amendment-stage-s1.json` | `cebdeb31b2e821cd0397582c0b643caebb160db1d1d0b5e30c8f83f51992b1e5` |
| `registration-smoke-S1-d300.json` | `698dea8ab295901e911e837f81b762f1c2d310d41074540e3c38229bac1d4953` |
| `registration-smoke-S1-d900.json` | `ee26459b7ffc2a004e5ea0bd207bd7935c19d56bb2b2ef71404568e6fbf23864` |
| `registration-mock-S1-d300.json` | `36aa97e160cd473328fdd28e14355f969d9bafed7e10cdf88cb4b4cd9dc8f86c` |
| `registration-mock-S1-d900.json` | `5212608bb115c56086224ee89ea8632a151dab3ad60c9fdd2e388c5b20c330cd` |
| `freeze_stage_s1_records_w5.py` | `72fa2f4b78d5c32cf0fc5b5fafdc5f9b3abb101b70987dad92f9f2890ce0c345` |
| `freeze_formal_stage_s1.py` | `3905e3e88afb59eb7e74c734e081efb9a7e6f7b439aba478660a24f543d14e08` |
| `execute_stage_s1_w5.py` | `8e7f894d956775670af25373a43894a67be4e0d641307d4c2072494f2429a099` |
| `run_real_stage_s1_w5.sh` | `5d46907bb0ced0ed86b24616ec9225617676c78121bd2937b9e977851b55855a` |
| `run_registered_s1.py` | `110a4f9ab955f550fe147a45d2044c35261c142bbf8386f6e1fa2511af6c4d37` |
| `admission-final.json` | `6bf3a983d1e2d9ecf08a02e8dadf746b291d2556bf682ae687653a94ec8e9795` |
| `reference-token-inventory.json` | `b68c39c1b40d1b8a75e5012c5ee37b8b63e128647a64e885eb8796aa75fccaa1` |
| `freeze-stage-s1-check.json` | `2d4cdc17a28fe1509faa680feff3f36d2cf9c6df1eeb48470550356e7be7499d` |
| `registration-qualification/results.json` | `f1885d8c849a49b21a83b273e4b0f7ca512feb722cc94f8af76ff131a1df0fbb` |
| `launcher-qualification/results.json` | `3f223c4184e6ded7d24f9b1ad1e76b3ba9550407a1556d5057cd62300b7937a4` |
| `qualify_stage_s1_mock_w5.py` | `88c4a714b3533d31910e4dc69b7c5fc2e238908a95532f0a4d78f4cc3c434a2a` |
| `qualification-stage-s1/d300-driver-result.json` | `ad497e668c2dd1b868401228492acb57ea19e10dd4c66ff022b526893402dbd3` |
| `qualification-stage-s1/d300-audit.json` | `af60ae46c2c14fbf1e48ed5fb9cb354e2a6a9ff6da9a483fe7ce0293ce1d5c13` |
| `qualification-stage-s1/d300-audit-profile.json` | `797a3113c2caed90e176378a65e80843f3e4fbe7ce3510898ea78007f43f14e7` |
| `qualification-stage-s1/d900-driver-result.json` | `45ceb74681958ec461a666d766bf6aa2693532d2cd6df20e07e821feac51006c` |
| `qualification-stage-s1/d900-audit.json` | `ba9455f39a14cfb0bf8eb54142ecbf8aa381c2007ade385ce87d942c94541848` |
| `qualification-stage-s1/d900-audit-profile.json` | `30c58f1e6129f2096a6712b7e4ace27b8115bf9ac9087ace09d2bba7a69d460f` |
| `release-readiness.json` | `9b0f811eef21044fd2c6d9e97be990f9141ce0ef45f0a5c2589c29b32a3a0161` |
