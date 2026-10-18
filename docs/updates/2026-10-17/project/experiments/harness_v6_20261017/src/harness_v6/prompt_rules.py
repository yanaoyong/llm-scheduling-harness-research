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
Use validate_plan for violation counts and up to 50 detailed violations, then atomic submit_plan (no dry_run).
Coverage shortfall is reported, never rejected. CQT/Q-time is not implemented.
'''

V6_RULES += """Snapshot format SNAPSHOT_V1: static prefix first, then CURRENT.
@name value contains one JSON value; @name object/table N [columns] introduces
N tab-separated rows with that header. All cells are explicit JSON values:
null is None, ! is absent field, "" is empty string; true/false are booleans.
Umean~offset and Cconstant encode uniform/constant distributions. Integers
remain integers; floats retain a decimal point or exponent and are rounded to
10 significant digits (the only value normalization). No blank defaults or =.
step_definitions rows have zero-based IDs; routes list these IDs in step order;
step_number_is_position=true restores step numbers starting at 1.
machine_groups_compact groups static attributes; $ids lists machine ID ranges,
sorted by id when decoded. Ranges a:b are inclusive; commas join ranges.
ready_groups shares batch/setup/qualification/release fields and $eligible;
$operations lists EVERY operation ID; decoded ready rows sort by operation_id.
$eligible [family,name] means the sorted IDs of every static machine in that
family. Other lists use [set,id] in eligible_sets, preserving their exact order.
machines holds dynamic state sorted by machine; machine_inheritance lists each inherited static
field and its machine ID ranges; machine_constants applies to every
machine (availability_basis is stated once). pending_tasks, holds, invalid_tasks,
running_jobs, idle matches, opportunities, ages and receipt use header-once
tables; nested cells retain their JSON fields. The prompt contains the complete
snapshot once. read_entities accepts at most 512 IDs. Tool receipts report
violation_count, counts_by_code and truncated; acceptance uses ALL violations.
"""
