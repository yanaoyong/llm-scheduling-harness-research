"""Deterministic timing for decisions explicitly supplied by the direct Agent.

No priority rule, machine choice, maintenance insertion, solver, or search lives
here. Actions define a global topological append order. All decisions are logged
by the caller; this module merely propagates resulting lower bounds.
"""
from __future__ import annotations


class DispatchError(ValueError):
    def __init__(self, code, message, action_index=None, operation_id=None):
        super().__init__(message)
        self.feedback = dict(code=code, message=message, action_index=action_index,
                             operation_id=operation_id)


def build_schedule(instance, actions, require_complete=True):
    if not isinstance(actions, list):
        raise DispatchError("actions_type", "actions must be a list")
    operations = {o["id"]: o for o in instance["operations"]}
    # Knowing how many explicitly supplied operations use a machine only
    # determines the source's initial-setup bound; it does not pick an action.
    assigned_counts = {}
    for action in actions:
        if isinstance(action, dict) and isinstance(action.get("id"), str) and action["id"] in operations and type(action.get("machine")) is int:
            key = operations[action["id"]]["group"], action["machine"]
            assigned_counts[key] = assigned_counts.get(key, 0) + 1
    done, machines, output = {}, {}, []
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise DispatchError("action_type", "Every action must be an object", index)
        oid = action.get("id")
        def fail(code, message):
            raise DispatchError(code, message, index, oid)
        if not isinstance(oid, str) or oid not in operations:
            fail("unknown_operation", f"Unknown operation {oid!r}")
        if oid in done:
            fail("duplicate_operation", f"Operation {oid} was already dispatched")
        op = operations[oid]
        machine = action.get("machine")
        if type(machine) is not int or machine not in instance["machines"][op["group"]]:
            fail("invalid_machine", f"Choose one of {instance['machines'][op['group']]} for {op['group']}")
        if op["predecessor"] is not None and op["predecessor"] not in done:
            fail("not_ready", f"First dispatch predecessor {op['predecessor']}")
        selected = action.get("maintenance", [])
        if not isinstance(selected, list) or any(not isinstance(e, str) for e in selected):
            fail("maintenance_type", "maintenance must be a list of event names")
        if len(selected) != len(set(selected)):
            fail("maintenance_duplicate", "Maintenance events must be unique")
        definitions = {p["name"]: p for p in instance["maintenance"] if p["group"] == op["group"]}
        if set(selected) - definitions.keys():
            fail("maintenance_unknown", f"Allowed maintenance names: {list(definitions)}")
        key = op["group"], machine
        previous = machines.get(key)
        if previous is None:
            missing = definitions.keys() - set(selected)
            if missing:
                fail("initial_maintenance", f"First operation on this machine must explicitly assign {sorted(missing)}")
            counters = {e: 0 for e in definitions}
            previous_setup, machine_end = 0, 0
        else:
            counters = dict(previous["counters"])
            previous_setup, machine_end = previous["setup"], previous["end"]
            for event in selected:
                if counters[event] < definitions[event]["min"]:
                    fail("maintenance_too_early", f"{event}: completed load {counters[event]} is below min {definitions[event]['min']}")
                counters[event] = 0
        for event, pm in definitions.items():
            increment = op["wafers"] if pm["type"] == "counter_based" else op["duration"]
            counters[event] += increment
            if counters[event] > pm["max"]:
                fail("maintenance_max", f"{event}: load would be {counters[event]} > max {pm['max']}; agent must revise ordering/machine/maintenance")
        effective_setup = op["setup"] if op["setup"] != 0 else previous_setup
        setup_changed = previous is None or effective_setup != previous_setup
        setup_definition = instance["setups"].get(op["group"], {}).get(effective_setup)
        setup_duration = setup_definition["duration"] if setup_changed and setup_definition else 0
        pm_duration = sum(definitions[e]["duration"] for e in selected) if previous else 0
        predecessor_end = done[op["predecessor"]]["end"] if op["predecessor"] is not None else 0
        lower = max(predecessor_end, op["release"] + setup_duration if op["is_first"] else 0)
        if previous:
            lower = max(lower, machine_end + pm_duration + setup_duration)
        elif assigned_counts.get(key, 0) > 1:
            # Source imposes this initial bound only when a successor exists.
            # The singleton, non-current-lot-step exception is intentional.
            lower = max(lower, setup_duration)
        start = lower
        row = dict(id=oid, machine=machine, start=start, end=start + op["duration"],
            maintenance=list(selected), effective_setup=effective_setup,
            setup_duration=setup_duration, maintenance_duration=pm_duration,
            action_index=index)
        output.append(row)
        done[oid] = row
        machines[key] = dict(end=row["end"], setup=effective_setup, counters=counters)
    if require_complete and len(done) != len(operations):
        missing = sorted(operations.keys() - done.keys())
        raise DispatchError("incomplete", f"Missing {len(missing)} operations: {missing}")
    return dict(schema_version=1, instance=instance["name"], operations=output,
                action_count=len(actions), timing_policy="append_lower_bounds_no_decision_selection")
