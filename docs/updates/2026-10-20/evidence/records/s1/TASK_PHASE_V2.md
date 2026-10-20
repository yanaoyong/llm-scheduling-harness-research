# Task: Phase V2 — finish S1 qualification with the original fixture and physics module (zero model cost)

Continue Phase V in `__LOCAL_WORKSPACE__/v6-mac-env/s1/goal/` (read `goal/PHASE_V_REPORT.md` first). Same hard
rules: NO real model request (loopback mock only), never read/print/modify `~/.codex/auth.json` or
`__LOCAL_WORKSPACE__/v6-mac-env/s1/codex-home/auth.json` (now a symlink to the real login — production home;
qualification runs must keep provider auth disabled), no commit/push, never overwrite retained
evidence (new directories/files only; keep the old qualification records).

## New inputs (already restored and hash-verified by the orchestrator)

- Original S0 fixture: `__LOCAL_WORKSPACE__/v6-mac-env/s1/restored-mac-inputs/sealed/fixture.json`,
  SHA-256 `d76827abb88c0ffdfbf4770a3b9fd4a119ff5416dd61deb968761a334e4ecd69` (= S0 `fixture_sha256`).
  Its `data_dir` is a Mac path. The orchestrator created
  `__HOME__/Downloads/大模型训练营/智能排程调研/validation/harness_v6_mac_20261018/inputs/physical`
  → symlink to `__LOCAL_WORKSPACE__/v6-mac-env/physical` (trusted-hash verified mirror). Do not rewrite the
  fixture; `source_check.verify_source` re-hashes the data files and is the guard for this mapping.
  Record the mapping in the technical amendment.
- Original `independent_physics` package (5 files):
  `__LOCAL_WORKSPACE__/v6-mac-env/s1/restored-mac-inputs/goal-s0-20261019/independent_physics/`. Copy it byte-for-byte
  to `goal/independent_physics/`, verify the 5 hashes against
  `__PROJECT_ROOT__` branch `origin/archive/harness-v6-physics-fixture`
  `docs/updates/2026-10-19/evidence/physics-fixture/manifest.json` (use `git show`, do not check out),
  and add them to the frozen files.

## Required

1. Switch `freeze_s1.py`'s production fixture to the original fixture; the fixture-equality gate must
   now pass. Freeze the final `registration-smoke-s1.json` and `technical-amendment-s1.json` (if the
   earlier qualification-only records would be overwritten, write new names and say so). The
   registration must pass `registration.validate(..., results=True)` and the S1 driver preflight.
2. Re-run the positive mock replays (S0 smoke-E1-selfcheck-1 and smoke-P2-selfcheck-1 outputs) through
   the real S1 driver with the final registration and original fixture, then the full
   `audit_model_run_s1.py --smoke` CLI: both must PASS end-to-end, including independent physics and
   idle audits. Report the initial-record comparison against S0 again (expect byte-identical now).
3. Physical qualification equivalent to S0 `verify_independent_physics.py` (S0 record:
   `__LOCAL_WORKSPACE__/v6-mac-env/s0-evidence/x/goal/independent-physics-qualification.json`). The S0 positive
   runs `e1-mechanism-v2` / `delta-mechanism-v1` were not published; use the two new positive replay runs
   as positives and apply the same 7 mutation classes (wrong seed, wrong warm-up boundary, changed
   processing duration, machine release, transport duration, dropped due completion, and the 7th in the
   S0 record) to a positive run's projected trace; each must be rejected. Also confirm
   `verify_source` actually hashed the data files through the mapped path (`verified_input_hashes`).
4. Re-run the launcher-stop and negative native cases only if any driver/runtime/auditor file changed;
   otherwise state they are unchanged by hash.
5. Prepare (do not run) the exact real-smoke command line for the orchestrator.

Append a `## Phase V2` section to `goal/PHASE_V_REPORT.md` with exact counts, hashes, the final
registration SHA-256, the margin numbers, and anything still unverified.
