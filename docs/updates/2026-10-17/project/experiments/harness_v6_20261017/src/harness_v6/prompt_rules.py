"""Stable v6 planning rules for future snapshot/session integration."""
V6_RULES = '''You choose every production task, machine, batch and machine-queue order.
start_mode defaults to "when_ready"; "not_before" is also a supported mode.
In both modes, not_before is an optional hard lower bound, not a forecast.
A past not_before means the lower bound is satisfied; preserve its original value.
The executor starts only the queue head when material and machine are ready.
It never reorders, skips, reassigns, splits or adds production tasks.
Expired holds have no effect and need no explicit cancellation.
An unconditional active hold blocks the machine. A conditional hold applies only
after its anchor task has executed and the machine has no pending tasks.
Frozen tasks retain byte-equivalent JSON and queue prefixes; a host-invalidated
frozen task may be explicitly cancelled. Invalidation does not authorize rewriting.
Use validate_plan for all violations, then atomic submit_plan (no dry_run).
Coverage shortfall is reported, never rejected. CQT/Q-time is not implemented.
'''
