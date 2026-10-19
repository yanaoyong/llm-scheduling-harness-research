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
and sample. coverage_uncovered provides complete version-bound read_entities paging. CQT/Q-time is not implemented.
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
upcoming_operations contains exported unreserved not-ready operations with earliest_start <= time+H.
earliest_start is a physical lower bound; nominal_start is informational mean-path time,
or null when the source mean path is unavailable.
Neither is an arrival promise or hard constraint; when_ready waits for actual material.
waiting_since is observed-ready history. Processing min/max include process + load/unload,
excluding setup/transport; null maximum means unbounded. Rework revisits are not projected.
No recorded dedication means the simulator does not restrict family-machine qualification;
observed bindings and same_machine_as remain binding.
unavailable_intervals=[] means no data provided, not guaranteed availability. Future maintenance is not provided.
setup_transitions/min_runs are static source facts: explicit step setup_time, else old-to-new
setup table, else empty-old fallback, else zero; min_runs decrement per lot.
avoidable_idle is a greedy witness lower bound. blocked_queues and absent_operation_tasks
are next-anchor diagnostics only; the model must cancel absent-operation tasks explicitly.
read_entities supports eq/contains and finite numeric gt/gte/lt/lte; null/absent never match ranges.
No implicit ranking or sorting is applied. To read ALL uncovered operations in this frozen version:
read_entities({"kind":"operations","cursor":null,"count":512,"where":[{"field":"coverage_uncovered","op":"eq","value":true}]}).
Follow coverage.complete_read after validate/submit for the candidate-specific uncovered list.
Follow next_cursor with identical predicates until null; cursors bind observation, coverage plan and filter.
upcoming_operations uses the same $operations and $eligible grouping as ready_groups;
its decoded rows sort by operation_id. ready_groups shares physical timing, priority, batch/setup fields and $eligible;
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
All other compact conventions apply. Internal release_time is not a public arrival fact.
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
                 delta_min, trigger, interaction, wall_seconds, valid_until_maximum, max_tool_calls):
    """Only per-cycle instruction tail; snapshot prefix remains byte-stable."""
    import json
    minimum = next_anchor + delta if trigger == 'periodic' else now + delta_min
    instruction = ('The full snapshot is already provided. read_entities is optional for additional public facts.'
                   ' validate_plan checks a candidate but does not commit it; submit_plan is required to commit.'
                   ' All tool calls, including extra read pages, count toward max_tool_calls.'
                   ' Reserve at least one tool call for submit_plan; do not spend the last call on reading or validation.'
                   if interaction == 'mcp_session' else
                   'Return exactly the JSON object {expected_state_version,submission_id,delta} '
                   'matching the output schema; no prose or tool calls. Use earliest_start as a lower bound and nominal_start as information only; diagnostics require your explicit delta.')
    value = dict(current_time=now, expected_state_version=state_version, submission_id=submission_id,
                 max_tool_calls=max_tool_calls if interaction == 'mcp_session' else 0,
                 max_model_requests=max_tool_calls+1 if interaction == 'mcp_session' else 1,
                 valid_until_maximum=valid_until_maximum, valid_until_maximum_comparison="<=",
                 valid_until_minimum=minimum, valid_until_comparison=">=" if trigger == "periodic" else ">", trigger=trigger,
                 wall_deadline_seconds=wall_seconds, instruction=instruction +
                 ' Use exact current_time for freeze_until; snapshot times are rounded.'
                 ' valid_until must satisfy both the stated minimum comparison and valid_until <= valid_until_maximum.'
                 ' The maximum is the host plan boundary, independent of the snapshot lookahead horizon.'
                 ' In the complete resulting plan, each operation_id may occur in at most one task, including retained tasks.'
                 ' Every assigned machine must belong to the eligible_machines of every operation in its task.'
                 ' Before final output or submit_plan, silently check the complete delta against the frozen snapshot:'
                 ' For task changes, cancel_ids and replace IDs must name existing pending base tasks; do not cancel a newly added task.'
                 ' Every task ID in machine_orders must exist in the resulting plan, and every new task must appear exactly once.'
                 ' Every supplied machine order must contain its full resulting queue, including retained tasks.'
                 ' For each operation, verify exact membership of its assigned machine in its decoded eligible_machines'
                 ' and exact equality of operation family and machine family; similar names or nearby machine IDs do not establish eligibility.'
                 ' Resolve any inconsistencies in your own proposed action before returning or submitting it; do not describe the check in the output.'
                 ' Plan expiry stops the trajectory as plan_horizon_defect; it never triggers automatic replanning.'
                 ' For event sessions, the next decision may occur after valid_until_minimum; choose sufficient plan validity.')
    return '\nCYCLE_FOOTER\n' + json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n'
