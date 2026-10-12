"""Independent hard-constraint checker and objective calculator.

This module does not import dispatch, clingo, the solver wrapper, or any Agent.
It reconstructs machine sequences from submitted timestamps and recomputes
maintenance, setup, and all temporal bounds from the instance facts.
"""
from __future__ import annotations

import json


def validate_schedule(instance, schedule):
    violations = []
    def error(code, message, **context):
        violations.append(dict(code=code, message=message, **context))
    expected = {o["id"]: o for o in instance["operations"]}
    rows = schedule.get("operations") if isinstance(schedule, dict) else None
    if not isinstance(rows, list):
        return dict(feasible=False, violations=[dict(code="schedule_type", message="operations must be a list")],
                    objective=None, operation_count=0)
    found, ordered = {}, {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            error("record_type", "Operation record must be an object", index=index)
            continue
        oid = row.get("id")
        if not isinstance(oid, str) or oid not in expected:
            error("unknown_operation", "Unknown operation identity", index=index, operation_id=oid)
            continue
        if oid in found:
            error("duplicate_operation", "Operation appears more than once", operation_id=oid)
            continue
        found[oid] = row
        op = expected[oid]
        machine, start, end = row.get("machine"), row.get("start"), row.get("end")
        machine_valid = type(machine) is int and machine in instance["machines"][op["group"]]
        if not machine_valid:
            error("machine_eligibility", "Machine is outside the operation's eligible group", operation_id=oid, machine=machine)
        times_valid = type(start) is int and type(end) is int
        if not times_valid:
            error("integer_time", "Start and end must be integers", operation_id=oid)
        else:
            if start < 0 or end < 0:
                error("nonnegative_time", "Times must be nonnegative", operation_id=oid)
            if end - start != op["duration"]:
                error("processing_duration", "end - start must equal unscaled pro_time", operation_id=oid,
                      expected=op["duration"], actual=end-start)
        maintenance = row.get("maintenance", [])
        if not isinstance(maintenance, list) or any(not isinstance(e, str) for e in maintenance):
            error("maintenance_type", "Maintenance must be a list of names", operation_id=oid)
        else:
            if len(maintenance) != len(set(maintenance)):
                error("maintenance_duplicate", "A maintenance assignment cannot occur twice", operation_id=oid)
            allowed = {p["name"] for p in instance["maintenance"] if p["group"] == op["group"]}
            for event in set(maintenance) - allowed:
                error("maintenance_unknown", "Unknown maintenance for group", operation_id=oid, event=event)
        if machine_valid and times_valid:
            ordered.setdefault((op["group"], machine), []).append(row)
    for oid in sorted(expected.keys() - found.keys()):
        error("missing_operation", "Required operation is absent", operation_id=oid)

    # Product-route precedence is separate from machine timing.
    for oid, row in found.items():
        op = expected[oid]
        predecessor = found.get(op["predecessor"])
        if predecessor is not None and type(row.get("start")) is int and type(predecessor.get("end")) is int:
            if row["start"] < predecessor["end"]:
                error("lot_precedence", "Operation starts before its immediate route predecessor ends",
                      operation_id=oid, predecessor=op["predecessor"])

    setup_violations = 0
    machine_details = []
    for (group, machine), sequence in sorted(ordered.items()):
        sequence.sort(key=lambda r: (r["start"], r["end"], r["id"]))
        definitions = {p["name"]: p for p in instance["maintenance"] if p["group"] == group}
        setup_events, setup_durations, effective_setups = [], [], []
        last_setup = 0
        for i, row in enumerate(sequence):
            op = expected[row["id"]]
            current_setup = op["setup"] if op["setup"] != 0 else last_setup
            # Source creates an initial assign_setup even for setup zero.
            assigned = i == 0 or (current_setup != last_setup and current_setup != 0)
            setup_definition = instance["setups"].get(group, {}).get(current_setup)
            setup_duration = setup_definition["duration"] if assigned and setup_definition else 0
            setup_durations.append(setup_duration)
            effective_setups.append(current_setup)
            if assigned:
                setup_events.append((i, current_setup, setup_definition))
            last_setup = current_setup
            if op["is_first"] and row["start"] < op["release"] + setup_duration:
                error("release_setup", "Lot current step starts before release plus its assigned setup",
                      operation_id=op["id"], minimum=op["release"] + setup_duration)
            if i == 0:
                if len(sequence) > 1 and row["start"] < setup_duration:
                    error("initial_setup_time", "First machine operation with successors must allow initial setup",
                          operation_id=op["id"], minimum=setup_duration)
            else:
                previous = sequence[i - 1]
                if row["start"] < previous["end"]:
                    error("machine_overlap", "Processing intervals overlap on the machine",
                          operation_id=op["id"], previous=previous["id"], group=group, machine=machine)
                selected = row.get("maintenance", [])
                selected = set(selected) if isinstance(selected, list) and all(isinstance(e, str) for e in selected) else set()
                # Multiple non-initial PM events are consecutive: source uses
                # the sum of all assigned positive durations, plus setup.
                pm_duration = sum(pm["duration"] for name, pm in definitions.items() if name in selected)
                lower = previous["end"] + setup_duration + pm_duration
                if row["start"] < lower:
                    error("machine_transition_time", "Machine gap is shorter than PM plus setup durations",
                          operation_id=op["id"], previous=previous["id"], minimum=lower,
                          pm_duration=pm_duration, setup_duration=setup_duration)

        # Each completed setup campaign below min_runs costs one, regardless of
        # deficit size. The final campaign carries no minimum-run penalty.
        for (index, setup, definition), (next_index, _, _) in zip(setup_events, setup_events[1:]):
            if definition and next_index - index < definition["min_runs"]:
                setup_violations += 1

        pm_segments = []
        for event, pm in definitions.items():
            boundaries = []
            for i, row in enumerate(sequence):
                assignments = row.get("maintenance", [])
                if isinstance(assignments, list) and event in assignments:
                    boundaries.append(i)
            if not boundaries or boundaries[0] != 0:
                error("initial_maintenance", "Every used machine must assign every PM type before its first operation",
                      operation_id=sequence[0]["id"], group=group, machine=machine, event=event)
            # Include the initial segment even when its required assignment is
            # absent, so max violations are not hidden by that separate error.
            cuts = sorted(set([0] + boundaries + [len(sequence)]))
            for begin, finish in zip(cuts, cuts[1:]):
                load = sum(expected[r["id"]]["wafers" if pm["type"] == "counter_based" else "duration"]
                           for r in sequence[begin:finish])
                if load > pm["max"]:
                    error("maintenance_max", "Maintenance segment exceeds maximum processing load",
                          group=group, machine=machine, event=event, start_operation=sequence[begin]["id"],
                          load=load, maximum=pm["max"])
                if finish < len(sequence) and load < pm["min"]:
                    error("maintenance_min", "Renewal occurs before minimum processing load",
                          group=group, machine=machine, event=event, operation_id=sequence[finish]["id"],
                          load=load, minimum=pm["min"])
                pm_segments.append(dict(event=event, begin=begin, end=finish, load=load, final=finish==len(sequence)))
        machine_details.append(dict(group=group, machine=machine, sequence=[r["id"] for r in sequence],
            effective_setups=effective_setups, setup_durations=setup_durations, pm_segments=pm_segments))
    valid_ends = [r["end"] for r in found.values() if type(r.get("end")) is int]
    objective = dict(makespan=max(valid_ends, default=0), setup_violations=setup_violations)
    return dict(feasible=not violations, violations=violations, objective=objective,
                operation_count=len(found), required_operation_count=len(expected), machines=machine_details)


if __name__ == "__main__":
    import argparse
    try:
        from .problem import load_instance
    except ImportError:
        from problem import load_instance
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instance")
    parser.add_argument("schedule")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = validate_schedule(load_instance(args.instance), json.loads(open(args.schedule, encoding="utf-8").read()))
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        open(args.output, "w", encoding="utf-8").write(rendered)
    else:
        print(rendered, end="")
    raise SystemExit(0 if result["feasible"] else 1)
