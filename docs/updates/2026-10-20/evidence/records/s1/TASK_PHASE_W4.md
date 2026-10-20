# Task: Phase W4 — continue Phase W3 now that memory is free (zero model cost)

Read `TASK_PHASE_W.md`, `TASK_PHASE_W2.md`, `TASK_PHASE_W3.md` and `stage-s1/PHASE_W_REPORT.md`
(through `## Phase W3`). All hard rules still apply. The user closed 15 idle Claude sessions: container
memory is now ~4.6 GB of 10.7 GB (anon ~1.0 GB, the rest reclaimable file cache). Keep anonymous memory
(`anon` in `/sys/fs/cgroup/memory.stat`) below ~7 GB; you may run references/audits in parallel within that.

Complete every remaining gate listed at the end of `## Phase W3` (three new offline references, all-cycle
token inventory and worst-state overhead recordings, final admission per arm with the shared measured
overhead bound, guard caps from max sessions over three seeds, frozen rules/amendment/smoke registrations
and validators, mock driver qualification with full independent audit duration/peak memory, restored
follow-on session checks, applicable launcher-stop/native negatives, prepared real commands). Do not run
any real smoke or trajectory. Append `## Phase W4` to `stage-s1/PHASE_W_REPORT.md` with exact numbers and
a clear release status (ready / blocked, and why).
