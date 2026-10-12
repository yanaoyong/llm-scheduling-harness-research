"""Standard-library reader for the pinned PADL-2023 fact instances.

Only predicates actually consumed by encoding_msw.lp are interpreted. In
particular pro_time is already the duration: pro_unit, load/unload, due dates,
and cascading flags do not introduce constraints in this version.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


class InstanceError(ValueError):
    pass


def operation_id(lot, product, step, priority):
    return f"{lot}:{product}:{step}:{priority}"


def _atom(text):
    text = text.strip()
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"[a-z][A-Za-z0-9_]*", text):
        return text
    raise InstanceError(f"Unsupported fact atom: {text!r}")


def parse_instance(text, name="instance", source=None):
    """Parse ground facts without consulting clingo or another solution."""
    clean = re.sub(r"%[^\n]*", "", text)
    facts = {p: [] for p in ("wip", "product", "tool", "pm", "setup_change")}
    arities = dict(wip=7, product=9, tool=6, pm=6, setup_change=4)
    for statement in clean.split("."):
        if not statement.strip():
            continue
        match = re.fullmatch(r"\s*([a-z_]+)\s*\(([^()]*)\)\s*", statement)
        if not match or match[1] not in facts:
            raise InstanceError(f"Unsupported fact statement: {statement.strip()!r}")
        args = tuple(_atom(a) for a in match[2].split(","))
        if len(args) != arities[match[1]]:
            raise InstanceError(f"Wrong arity: {match[1]}{args}")
        if args not in facts[match[1]]:  # ASP facts have set semantics.
            facts[match[1]].append(args)

    routes = {}
    for p, s, area, group, duration, unit, cascade, st, setup in facts["product"]:
        if (p, s) in routes:
            raise InstanceError(f"Ambiguous product route at {(p, s)}")
        if not isinstance(duration, int) or duration <= 0:
            raise InstanceError("This experiment requires positive integer pro_time")
        routes[p, s] = (area, group, duration, setup)

    by_lot_projection = {}
    operations = []
    for lot, product, current, priority, wafers, release, due in facts["wip"]:
        projection = (wafers, release)
        if lot in by_lot_projection and by_lot_projection[lot] != projection:
            raise InstanceError("Conflicting lot-index wafer/release projections are outside the locked corpus")
        by_lot_projection[lot] = projection
        steps = sorted(s for p, s in routes if p == product and s >= current)
        if not steps or steps[0] != current or steps != list(range(current, steps[-1] + 1)):
            raise InstanceError(f"Non-contiguous active product route for {(lot, product, current, priority)}")
        for step in steps:
            area, group, duration, setup = routes[product, step]
            operations.append(dict(id=operation_id(lot, product, step, priority), lot=lot,
                product=product, step=step, priority=priority, area=area, group=group,
                duration=duration, setup=setup, wafers=wafers, release=release, due=due,
                is_first=step == current,
                predecessor=None if step == current else operation_id(lot, product, step - 1, priority)))
    if len({o["id"] for o in operations}) != len(operations):
        raise InstanceError("Duplicate or overlapping WIP operation identities")
    if not operations:
        raise InstanceError("No active operations")

    raw_machines = {}
    for area, group, machine, cascade, loading, unloading in facts["tool"]:
        raw_machines.setdefault(group, set()).add(machine)
    machines = {}
    for group in sorted({o["group"] for o in operations}):
        count = min(len(raw_machines.get(group, set())), sum(o["group"] == group for o in operations))
        if not count:
            raise InstanceError(f"No machine for group {group}")
        # machine_selection.lp deliberately creates 1..count, not raw IDs.
        machines[group] = list(range(1, count + 1))

    maintenance = []
    for name_, group, type_, maximum, duration, minimum in facts["pm"]:
        if type_ not in ("counter_based", "time_based"):
            raise InstanceError(f"Unsupported PM type {type_}")
        if not (0 <= minimum <= maximum and duration >= 0):
            raise InstanceError(f"Invalid PM bounds: {name_}")
        maintenance.append(dict(name=name_, group=group, type=type_, max=maximum,
                                duration=duration, min=minimum))
    if len({(p["group"], p["name"]) for p in maintenance}) != len(maintenance):
        raise InstanceError("Ambiguous maintenance definitions")
    # This is a corpus guard, not a new scheduling constraint: this reader does
    # not silently generalize the source's pair construction to unsupported data.
    if any(not any(p["group"] == g for p in maintenance) for g in machines):
        raise InstanceError("Locked PADL corpus requires PM for every active group")

    setups = {}
    for group, setup, duration, min_runs in facts["setup_change"]:
        if setup in setups.setdefault(group, {}):
            raise InstanceError(f"Ambiguous setup definition {group}:{setup}")
        setups[group][setup] = dict(duration=duration, min_runs=min_runs)
    for op in operations:
        if op["setup"] != 0 and op["setup"] not in setups.get(op["group"], {}):
            raise InstanceError(f"Undefined setup on {op['id']}")

    return dict(schema_version=1, name=name, source=str(source) if source else None,
        source_sha256=hashlib.sha256(text.encode()).hexdigest(), flex=1,
        operations=sorted(operations, key=lambda o: (o["lot"], o["product"], o["priority"], o["step"])),
        machines=machines, maintenance=maintenance, setups=setups,
        semantics="PADL-2023/encoding_msw.lp@6253f982; flex=1",
        ignored_fields=["pro_unit", "cascading_interval", "load_time", "unload_time", "due_time"])


def load_instance(path):
    path = Path(path)
    return parse_instance(path.read_text(encoding="utf-8"), path.stem, str(path.resolve()))


def save_instance(instance, path):
    Path(path).write_text(json.dumps(instance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instance")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = load_instance(args.instance)
    if args.output:
        save_instance(result, args.output)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
