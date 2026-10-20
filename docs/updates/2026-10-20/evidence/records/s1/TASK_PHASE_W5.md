# Task: Phase W5 — FAST PATH to the real S1 runs (user decision 2026-10-19: "提速")

Read `TASK_PHASE_W.md`, `TASK_PHASE_W2.md`, `TASK_PHASE_W3.md`, `TASK_PHASE_W4.md` and `stage-s1/PHASE_W_REPORT.md`.
All hard rules still apply (no real model request, never touch auth files, no commit/push, never modify
`goal/`, the original fixture or S0 evidence, exclusive writes, retain all artifacts).

The user chose speed: do NOT wait for the remaining offline references (`references-w4/` d300-seed2,
d300-seed3, d900-seed3) or the full-hour mock audits. They keep running as background processes started
by the previous (stopped) Codex run — leave them alone, do not kill them, and do not depend on them.

Do, as fast as correctness allows:
1. **Freeze from seed-1 references only** (plus d900-seed2 which is complete): quality floors from seed 1
   (unchanged rule); guard caps from the max session count over the completed references per arm
   (d300: seed 1 only; d900: seeds 1, 2), recording explicitly that the 3-seed bound was not available.
   Adapt `freeze_stage_s1_records.py` (new file name, keep the old one) accordingly.
2. **Admission from known worst states**: d900 = cycle-4 recording (snapshot 247,090, overhead 470,796);
   d300 = max snapshot over all d300-seed1 cycles plus one overhead recording at its largest state
   (mock, loopback, auth disabled). Registered overhead = max measured rounded up to 1,000 (≥ 471,000),
   shared by both arms. Both margins must be positive (else stop and report). Record that runtime
   admission fails closed before any model call if a later state is larger.
3. **Minimal mock qualification** of the real driver per arm: one or two loopback sessions through the
   S1 driver with the frozen smoke registration semantics (mock registration), followed by the
   independent audit in smoke mode; plus confirm the launcher stops on a driver failure. Skip full-hour
   mock replays.
4. **Real-run launcher** that survives the orchestrator's session ending: a script the orchestrator will
   start with `setsid nohup`, which runs smoke d300 → audit → smoke d900 → audit → formal freeze from
   smoke usage (S0 method) → formal d300 → formal d900, audits in background as in
   `__LOCAL_WORKSPACE__/v6-mac-env/s1/goal/execute_pipelined_s1.py`, stop on any failure, never retry/overwrite,
   and support `--resume` of an interrupted formal trajectory via the driver's resume semantics (host
   state only, never old model history) if the driver supports it — document exactly how.
   Write a `release-readiness.json` with `ready: true` only if 1–3 passed. Do NOT start it.

Append `## Phase W5 (fast path)` to `stage-s1/PHASE_W_REPORT.md`: what was skipped vs the full plan,
exact numbers (margins, caps, floors, hashes), qualification results, the exact start command.
