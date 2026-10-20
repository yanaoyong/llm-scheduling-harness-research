# Task: Phase X — make the independent run audit fast enough for S2 (zero model cost)

Context: `__LOCAL_WORKSPACE__/v6-mac-env/s1/stage-s1/w5/` holds the frozen S1 stack (`audit_model_run_s1.py`,
`audit_physical_prefix.py`, `audit_idle_replay_v2.py`, `cycle_artifacts.py`, `independent_physics/`,
`traced_runtime_s1.py`). Read `stage-s1/PHASE_W_REPORT.md` (W5 section) and the auditor sources first.
The full independent audit of a 1-simulated-hour P2 trajectory takes ~1.5 h on ONE core (S0 15-minute
trajectories took 20–40 min). S2 will run 8 simulated hours, so audits would take 8–12 h each. The
machine has 16 cores; container memory limit 10.7 GB (shared; keep anonymous memory of your jobs
below ~5 GB because a real audit, `formal-S1-d900`, is running right now — do NOT touch, kill, slow or
read-lock its files; read-only access to its finished inputs is fine).

**Hard rules:** no model request of any kind; never touch auth files; no commit/push; do not modify
anything under `stage-s1/`, `goal/`, the fixtures or the harness source. Work only in
`__LOCAL_WORKSPACE__/v6-mac-env/s1/audit-opt/` (copies + new files, exclusive writes).

## Do

1. **Profile first.** Using `cProfile`/timers on a completed run (start with an S0 run such as
   `__LOCAL_WORKSPACE__/v6-mac-env/s1/goal/formal-P2-2-s1` + its native trace, then `stage-s1/w5/formal-S1-d300`),
   measure wall time and peak RSS of each audit stage: native trace audit per call, provenance, physics
   prefix audit (`independent_physics.audit_prefix.audit_trace` and projection), idle replay
   (restore + forward replay + per-interval computation), cycle-artifact reading, JSON parsing,
   hashing. Report the top hotspots with numbers.
2. **Optimize without weakening independence.** Allowed:
   - Run the physics audit and the idle replay audit in separate processes concurrently (they are
     independent), and the per-call native trace audits in a process pool.
   - Remove pure overhead found by profiling (repeated JSON decoding/hashing of the same bytes,
     repeated deep copies, quadratic scans, re-reading archived tarballs, etc.).
   - A batch runner that audits several runs in parallel within a memory budget.
   **Not allowed:** starting the replay from host-produced intermediate checkpoints instead of the
   sealed initial state, skipping or sampling any check, relaxing any tolerance, trusting any host-
   reported value that is currently re-derived, or changing the physics/idle semantics. If a speedup
   would require one of these, describe it and its trade-off in the report but do not implement it.
3. **Prove equivalence.** The optimized auditor must produce results identical to the frozen auditor
   (same JSON content, except added timing fields, which must be kept separate) on every completed
   run you can use: all S0 formal runs and smokes in `goal/` (incl. the stopped `formal-E1-3-s1`,
   which must still fail only `formal_requires_registered_end`), the S1 smokes and `formal-S1-d300`
   in `stage-s1/w5/` (and `formal-S1-d900` only after its official audit JSON exists). Compare against
   the existing official audit JSONs. Also rerun the physics 7-mutation rejection qualification and the
   idle/trace tamper negatives against the optimized code; every negative must still be rejected.
4. **Measure the speedup** (wall time, CPU, peak RSS) old vs new on at least one S0 run and on
   `formal-S1-d300`, plus an extrapolation for an 8-hour S2 trajectory, and the parallel batch case.

Write `audit-opt/PHASE_X_REPORT.md`: profile table, changes (each with why it keeps independence),
equivalence results (counts, any difference), negative-case results, speedups, S2 extrapolation, and
what is still slow and why.
