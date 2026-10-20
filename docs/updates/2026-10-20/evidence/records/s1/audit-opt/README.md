# Offline independent audit optimization

All writes belong below this directory. No driver or Codex executable is invoked.
The `offline_guard` rejects network connections, credential-file access, and writes
outside `audit-opt`. Existing source, fixtures, registrations, and audit inputs are
read only. `frozen/` contains the unchanged W5 auditors; `optimized/` contains the
candidate. The original harness package is imported without modifying its files.

Run a completed trajectory and compare its complete JSON with the official result:

```bash
PYTHONDONTWRITEBYTECODE=1 __LOCAL_WORKSPACE__/v6-mac-env/venv/bin/python -B \
  audit-opt/run_audit.py \
  --run __LOCAL_WORKSPACE__/v6-mac-env/s1/goal/formal-P2-2-s1 \
  --output __LOCAL_WORKSPACE__/v6-mac-env/s1/audit-opt/results/NEW-NAME
```

`--variant frozen` runs the baseline. `--stage-workers 2` runs physics and idle in
independent processes. Default stage concurrency is one to keep batch memory low.
`--official`, `--trace`, `--fixture`, `--smoke`, and `--test-base-url` support retained
mock evidence; the URL is checked as provenance only, never contacted.

`audit.json` has no added timing fields. `timing.json` holds wall/CPU measurements,
per-stage inclusive timers, and per-process RSS high-water marks. When stages run
in parallel, `worker-timings.json` records their measurements. RSS high-water marks
are not additive simultaneous memory measurements. `comparison.json` records exact
canonical JSON-content equality, including all floats, errors, lists, and path strings.
A correctly rejected stopped run compares equal and therefore returns runner exit 0.

Batch manifests are JSON lists of objects with `run` and optionally `official`,
`trace`, `fixture`, `smoke`, `test-base-url`, and `variant`. For example:

```bash
__LOCAL_WORKSPACE__/v6-mac-env/venv/bin/python -B audit-opt/batch.py \
  --manifest audit-opt/suite-manifest.json --output audit-opt/results/NEW-BATCH \
  --jobs 2 --budget-gib 4.5 --reserve-gib 2.2
```

The batch uses fresh processes, one stage worker per process, and admits no more
than `floor(budget / reserve)` workers. It samples its own processes every 0.5 s
and terminates only its own jobs if their aggregate anonymous memory exceeds the
budget. Leave room for other independently launched audit jobs; this is not a
container-wide admission controller. Output directories must not already exist. The default reserve is measured on
S0/S1 only. For an unmeasured eight-hour S2 input, start with `--jobs 1
--budget-gib 4.5 --reserve-gib 4.5` and qualify its memory before increasing
concurrency.

`qualify_negatives.py` replays the seven physics mutations and six each of idle
and trace tampering tests from retained evidence, without making a model request.
`check_observations.py` compares full old/new observation objects during the first
ten replay observations; full-run comparisons separately cover every interval.
The deliberately bounded profiling/differential probes are not full audits.

The replay computation changes are caches of immutable route eligibility and
intrinsic duration lookups, plus a per-observation ownership index in a copied
independent idle checker. The index preserves task order and duplicate-membership
semantics; it imports no production ledger helpers. Source arithmetic, operation order, observation fields,
ledger matching logic, event loop, seed policy, tolerances, initial restore, and
final physical-state comparison are retained. Cache state is scoped to a replay
environment and never populated from host intermediate checkpoints.
