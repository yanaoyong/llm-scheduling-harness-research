# Task: Phase W3 — resume and finish Phase W2 after an interruption (zero model cost)

Your previous Phase W2 process (`__LOCAL_WORKSPACE__/v6-mac-env/s1/TASK_PHASE_W2.md`, log `codex-impl-w2.jsonl`)
was killed around 16:24 UTC when the orchestrator's session ended; all child processes stopped too. Read
`TASK_PHASE_W.md`, `TASK_PHASE_W2.md`, and `stage-s1/PHASE_W_REPORT.md` (incl. `## Phase W2`). All hard
rules still apply (no real model request, never touch auth files, no commit/push, never modify `goal/`,
the original fixture or S0 evidence, exclusive writes, retain every interrupted artifact).

State found by the orchestrator:
- New fixture `stage-s1/fixture/sealed-36000/fixture.json` (sha `07afb411…`) built and qualified.
- `references-v2/`: d300-seed1, d900-seed1, d900-seed2 reached `registered_end` 4302; d300-seed2 stopped
  mid-run (6 cycles, no summary) — interrupted, retain it as interrupted; d300-seed3 and d900-seed3 not
  started.
- Your last messages: d900 seed-1 largest snapshot 247,090 tokens with pressure-recorded overhead
  470,796 (→ 471,000, margin 56,709); d900 recovery test 2502→3402 passed; restored-run follow-on
  tests were in progress.

Do:
1. Verify the completed references (summary, hashes) rather than trusting this list. Do not rerun completed
   ones. Rerun d300-seed2 in a new directory (keep the interrupted one) and run d300-seed3, d900-seed3.
   Run them in parallel if memory allows (keep total container memory below ~8.5 GB; check
   `/sys/fs/cgroup/memory.current`).
2. Finish the worst-case snapshot / tool-payload overhead recordings across all six references. The
   registered `request_overhead_tokens` for S1 must be ≥ the measured maximum rounded up to 1,000 (it is
   no longer 441,000 if 470,796 holds); each arm's margin must stay positive, else stop and report.
3. Finish everything else in TASK_PHASE_W.md / W2: quality criteria from seed-1 references, guard caps
   from max sessions over three seeds, frozen rules/amendment/smoke registrations for d300 and d900,
   driver adaptation, mock qualification incl. full independent audit duration/memory and the
   checkpoint/resume checks, prepared real commands (smoke d300, smoke d900, formal freeze from smoke,
   formal d300, formal d900; stop on any failure).
4. Append `## Phase W3` to `stage-s1/PHASE_W_REPORT.md` with exact numbers, including the interruption.
