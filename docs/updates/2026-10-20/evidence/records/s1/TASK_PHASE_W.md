# Task: Phase W — prepare stage S1 (P2 only, 1 simulated hour, Δ=300 and Δ=900), zero model cost

Context: read `__LOCAL_WORKSPACE__/v6-mac-env/s1/goal/PHASE_V_REPORT.md` (whole S0-on-official-Codex stack),
`registration-formal-s1.json` (final S0 registration actually used), and the harness at
`__PROJECT_ROOT__/docs/updates/2026-10-17/project/experiments/harness_v6_20261017`
(`README.md`, `DECISIONS_v6.md`, `src/harness_v6/cycle.py::CycleConfig.for_stage`), plus
`__PROJECT_ROOT__/research/2026-10-17-codex-search/HARNESS_V6_LONG_RUN_ADDENDUM.md`
(stage table: S1 = 1 simulated hour, choose Δ between 300 and 900).

S0 is finished (6 real trajectories, all evidence under `__LOCAL_WORKSPACE__/v6-mac-env/s1/goal/`, read-only —
never modify or overwrite anything there). Work in a NEW directory `__LOCAL_WORKSPACE__/v6-mac-env/s1/stage-s1/`.

**Hard rules:** NO real model request (loopback mock only, provider auth disabled, isolated test homes).
Never read/print/modify `~/.codex/auth.json` or `__LOCAL_WORKSPACE__/v6-mac-env/s1/codex-home/auth.json`. Do not
commit/push. Do not change harness source unless unavoidable; if you must, list every diff and rerun the
plain suite plus affected tests. Do not run the real smoke or real trajectories.

## User decision (fixed — do not change)

- S1 runs **P2 only** (periodic trigger, mcp_session), model gpt-6.1-sol, same official Codex pin, catalog,
  model_config, explicit snapshot format (carried over), session budget, failure policy (k_fail=2,
  keep_old_plan, no retry), stall settings, breakdowns=false (S1 per README; S2+ enable breakdowns).
- Two arms, **one trajectory each, seed 1**: Δ=300 and Δ=900. Window: start 702 (fixture `mixed_702`,
  original S0 fixture `__LOCAL_WORKSPACE__/v6-mac-env/s1/restored-mac-inputs/sealed/fixture.json`), end = 702 + 3600
  = 4302 (check the end time convention used for S0, 1603.1, and apply the same convention for 1 hour;
  report what you chose and why). H per harness rule `max(3Δ, 900)` → 900 and 2700; delta_min = Δ unless
  the harness requires otherwise (report).
- Each arm gets one matching real smoke (1 session) before its trajectory; the orchestrator runs them.

## Required work

1. **Offline scripted reference (mechanism only, no model).** Use the existing offline planner/replay
   tooling that produced S0's Δ reference (`scripts/measure_model_delta.py`, `replay_triggers.py`, the
   S0 rules' `scheduling.delta_basis`) to run 702 → 4302 at Δ=300 and Δ=900, seed 1 (also seeds 2, 3 for
   the reference only, since these are free). Report per arm: number of non-empty cycles/sessions,
   throughput, weighted tardiness, avoidable idle integral, and the snapshot token size of every cycle.
2. **Context admission check.** Compute the maximum snapshot tokens (explicit format, o200k tokenizer as in
   S0) over all cycles of both arms. Required = max snapshot + 441,000 overhead + 10,000 reserve must stay
   below admission 784,799. Note especially Δ=900 with H=2700 (a 3× larger lookahead window). If the
   overhead recordings (`__LOCAL_WORKSPACE__/v6-mac-env/work/official/overhead/`) do not cover states this late or
   this large, re-record overhead on the mock for the worst-case states (same method as before, see
   `prepare_recording_snapshots.py` / `measure_request_overhead.py` and the orchestrator's
   `__LOCAL_WORKSPACE__/v6-mac-env/official-diag/record_overhead.sh`). **If any arm does not fit, stop and report the
   numbers — do not shrink H, drop rows or change any filtering rule; that is the user's decision.**
3. **Quality criteria.** Derive S1 quality floors/tolerances per arm from the offline reference using the
   same rule S0 used (S0 rules `quality` / `quality_basis`: floor from the scripted reference, idle
   tolerance 10 %). Record them explicitly as mechanism references, not model quality evidence.
4. **Freeze S1 records** in `stage-s1/` (exclusive writes): `experiment-rules-stage-s1.json` (S0-s1 rules
   with only the explicit stage-S1 changes, diff recorded and asserted), technical amendment (pin, catalog,
   overhead used, margin per arm, fixture + Mac-path mapping, frozen-file hashes), and per arm
   `registration-smoke-S1-d300.json`, `registration-smoke-S1-d900.json`; plus a freeze script for the
   later formal registrations (from smoke usage, S0 method — see `__LOCAL_WORKSPACE__/v6-mac-env/s1/goal/freeze_formal_s1.py`).
   Per-sim-hour guard caps: recompute with the S0 formula from the offline session counts.
   All must pass `harness_v6.registration.validate(..., results=True)` and a stage-S1 validator (adapt
   `validate_s1_registration.py`; the S0 immutables that legitimately change are Δ, H, delta_min,
   end_time, quality, guard caps, groups=['P2'] — anything else must stay identical).
5. **Driver/launcher/auditor.** Reuse the S0 stack (`run_registered_s1.py`, `traced_runtime_s1.py`,
   `audit_model_run_s1.py`, auditors) by copying into `stage-s1/` with the minimal changes needed
   (phase names, registration path, groups P2 only, longer run). The independent idle/physics audits took
   ~20–40 min per 15-minute S0 trajectory; measure on the offline 1-hour reference how long they take and
   whether memory stays below ~4 GB (container limit 10 GB, shared); report.
6. **Mock qualification.** For each arm, run the real S1 driver on the loopback mock for a multi-session
   replay (use the offline scripted plans as mock model outputs submitted through the real MCP tools, or
   replay S0 P2 outputs where the state matches) far enough to cross several Δ anchors, then the full
   independent audit; plus checkpoint/resume if the runner supports it. Rerun launcher-stop and native
   negative cases only if driver/runtime/auditor changed.
7. Prepare (do not run) the exact real commands: smoke d300, smoke d900, then formal d300 and d900 (one
   trajectory each), sequential, stop on any failure, audits may run in the background as in
   `__LOCAL_WORKSPACE__/v6-mac-env/s1/goal/execute_pipelined_s1.py`.

Report in `stage-s1/PHASE_W_REPORT.md`: decisions (end-time convention, delta_min), offline reference
table, per-arm max snapshot and margin, quality criteria, frozen hashes, qualification counts, audit
duration/memory, estimated real token use per arm (smoke-calibrated method: sessions × S0 per-session
P2 usage ≈ 0.55M input, 66 % cached), commands, and anything unverified.
