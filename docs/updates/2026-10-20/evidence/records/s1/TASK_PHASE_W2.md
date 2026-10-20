# Task: Phase W2 — build a longer sealed fixture, then finish Phase W (zero model cost)

Read `__LOCAL_WORKSPACE__/v6-mac-env/s1/TASK_PHASE_W.md` and your report `__LOCAL_WORKSPACE__/v6-mac-env/s1/stage-s1/PHASE_W_REPORT.md`.
All hard rules from TASK_PHASE_W.md still apply (no real model request, never touch auth files, no
commit/push, never modify `__LOCAL_WORKSPACE__/v6-mac-env/s1/goal/`, the original fixture, or S0 evidence).

## User decision (2026-10-19): option A

The user authorized generating a **new, longer sealed fixture** from the original trusted physical inputs
on this Linux machine, registered under a new hash, used by both S1 arms. The original S0 fixture stays
untouched. S1 results will not be byte-comparable with S0; record that explicitly.

1. **Find how the 3600 s horizon is produced** (`scripts/build_public_fixture.py`,
   `scripts/build_sealed_fixture.py`, `validate_sealed_fixture.py`, `factory_v6`/`env_adapter`
   `window_seconds`, how S0's `mixed_702` was built — see `MAC_VALIDATION.md`, `MAC_RUNBOOK.md`,
   `__LOCAL_WORKSPACE__/v6-mac-env/s1/restored-mac-inputs/` and the S0 archive `source/v6/`). Change only the
   horizon/window parameter, through an explicit CLI argument or a registered config value, not by
   editing defaults silently. Everything else (seed handling, warm-up to 702, data inputs, mixed_702
   construction) stays the same method.
2. **Size.** Target horizon **36,000 s** (≥ 702 + 28,800 + 2,700 = 32,202 needed for a later 8-hour S2
   with Δ=900). First measure build time, peak memory and fixture size at a smaller horizon (e.g. 7,200)
   and extrapolate. If 36,000 would need more than ~4 GB RAM (container limit 10 GB, shared) or more than
   ~90 minutes, build **7,200** instead (≥ 7,002 needed for S1 Δ=900) and report the numbers. Write the
   fixture outside the repo under `__LOCAL_WORKSPACE__/v6-mac-env/s1/stage-s1/fixture/` (exclusive writes).
3. **Qualify the new fixture**: run `validate_sealed_fixture.py` (and whatever S0 used to qualify its
   fixture — check `validation.json`/`provenance.json` patterns in `__LOCAL_WORKSPACE__/v6-mac-env/work/sealed2/`)
   on it; verify the physical-data source hashes; compare its t=702 `mixed_702` state against the S0
   fixture and report exactly what differs (expected: calendars/samples beyond 3600 and possibly random
   streams; report whether the 0–702 prehistory and the t=702 state are identical or not, with counts).
   Record the new SHA-256. The independent physics auditor (`independent_physics`) must still accept runs
   on the new fixture (rerun its positive + 7 mutation qualification on a run with the new fixture).
4. **Then complete every item of TASK_PHASE_W.md** (offline references for Δ=300 and Δ=900 over
   702 → 4302 using the new fixture, per-cycle snapshot tokens and admission margin per arm with overhead
   re-recording for the worst states, quality criteria, frozen rules/amendment/smoke registrations, driver
   adaptation, mock qualification incl. full audit duration/memory, prepared real commands). The rule
   "if an arm does not fit the context admission, stop and report — do not shrink H or change filtering"
   still holds.

Append `## Phase W2` to `stage-s1/PHASE_W_REPORT.md` with exact numbers, hashes and what is unverified.
