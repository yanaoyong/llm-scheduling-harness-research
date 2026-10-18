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
Coverage shortfall is reported, never rejected. coverage contains observed_operations,
reserved_operations, ready_operations, ready_unreserved_count, ready_unreserved_sample
(first 50 sorted ready-and-unreserved IDs), truncated and report_only=true.
Readiness uses the ledger definition; non-ready work is excluded from ready counts
and sample. Full uncovered IDs can be reconstructed offline from saved plan/problem. CQT/Q-time is not implemented.
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

V6_RULES += """Decision delta: plan_header has valid_until, freeze_until, reason only.
Tasks use id, operation_ids, optional start_mode/not_before/latest_start; never
send machine, lot_ids, steps, visits. machine_orders assigns machines and full
queue order; list each new task exactly once. Unlisted replacements keep their
base machine and queue position. Cancellation needs no order and preserves the
remaining order. Retained/replaced tasks move only when listed on another machine.
New tasks require the receiving machine's full order; moves require full source
and destination orders (even an empty source []). Every supplied order is complete.
Snapshot pending_tasks/invalid_tasks use this projection; machine_orders retains
pending assignments and queue order. Both patches use cancel_ids, replace, add;
unmentioned items remain. Hold replacements use {ref:"h:0",hold:{...}}.
Do not send schema, anchors, order_policy, version, created_at or scope: the host
fills constants/provenance from frozen state; expected_state_version binds it.
Submit {} for explicit no-change. For cancellation alone, use cancel_ids:["t1"]
and machine_orders:[]; for replacement in place, use replace:[{"id":"t1",
"operation_ids":["op1"],"latest_start":800}] and machine_orders:[].
Example addition delta (assuming empty base queues):
{"plan_header":{"valid_until":900,"freeze_until":0,"reason":"run ready work"},
 "tasks":{"cancel_ids":[],"replace":[],"add":[{"id":"t1","operation_ids":["op1"]}]},
 "holds":{"cancel_ids":[],"replace":[],"add":[]},
 "machine_orders":[{"machine":1,"task_ids":["t1"]}]}
"""


DENSE_LEGEND = """Dense conventions (SNAPSHOT_V1_DENSE): table headers append defaults {column:value}
and equals {column:source} (or {column:[source]} for a singleton list).
Empty cells mean the declared column default; ! still means absent, never null.
= means the declared same-row source (cadence=processing; processing_until=[available_at]).
Strings may be bare unless ambiguous, empty, numeric-looking or marker-prefixed;
otherwise they are JSON-quoted. Nested values remain JSON/distribution cells.
Defaults use the most frequent normalized typed value, ties by encoded lexical order;
only positive whole-table savings under the supplied token counter are used.
$release_time_is_time=true means omitted release_time equals CURRENT time in that ready group;
without that flag, an absent release_time remains absent. All other compact conventions apply.
"""


def rules_for_format(snapshot_format):
    if snapshot_format == 'explicit':
        return V6_RULES
    if snapshot_format != 'dense':
        raise ValueError('snapshot_format must be explicit or dense')
    return V6_RULES.replace('Snapshot format SNAPSHOT_V1:', 'Snapshot format SNAPSHOT_V1_DENSE:').replace(
        'All cells are explicit JSON values:', 'Base cell types:').replace(
        'No blank defaults or =.', 'Dense cell overrides are declared below.') + DENSE_LEGEND


def cycle_footer(*, state_version, submission_id, now, next_anchor, delta,
                 delta_min, trigger, interaction, wall_seconds):
    """Only per-cycle instruction tail; snapshot prefix remains byte-stable."""
    import json
    minimum = next_anchor + delta if trigger == 'periodic' else now + delta_min
    instruction = ('Use read_entities for additional public facts, validate_plan, then submit_plan.'
                   if interaction == 'mcp_session' else
                   'Return exactly the JSON object {expected_state_version,submission_id,delta} '
                   'matching the output schema; no prose or tool calls.')
    value = dict(current_time=now, expected_state_version=state_version, submission_id=submission_id,
                 valid_until_minimum=minimum, valid_until_comparison=">=" if trigger == "periodic" else ">", trigger=trigger,
                 wall_deadline_seconds=wall_seconds, instruction=instruction + ' Use exact current_time for freeze_until; snapshot times are rounded.')
    return '\nCYCLE_FOOTER\n' + json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n'
