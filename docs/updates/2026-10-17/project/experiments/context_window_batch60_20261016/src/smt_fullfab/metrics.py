"""Full-factory metrics reconstructed from events, never result/success flags.

This module does not import the environment, controller, or their metrics. The
proposed priority mapping is a development choice, not a frozen study protocol.
"""
from __future__ import annotations

from collections import defaultdict
import json
import math
from pathlib import Path

DEFAULT_PRIORITY_WEIGHTS = {10: 1.0, 20: 2.0, 30: 3.0}
METRICS_VERSION = "smt-fullfab-metrics-v1"


def read_events(source):
    if isinstance(source, (str, Path)):
        return [json.loads(line) for line in Path(source).read_text().splitlines() if line.strip()]
    return list(source)


def _finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def weighted_tardy_seconds(*, release, due, completion, window_start,
                           window_end, weight=1.0):
    """Integral of weight * released * unfinished * overdue over the window.

    Historical overdue time before window_start is excluded; a lot already late
    at window_start accrues its weight immediately. None completion means WIP.
    """
    release, due = _finite(release, "release"), _finite(due, "due")
    start, end = _finite(window_start, "window_start"), _finite(window_end, "window_end")
    weight = _finite(weight, "weight")
    if end <= start or weight <= 0:
        raise ValueError("window_end must exceed window_start and weight must be positive")
    completion = end if completion is None else _finite(completion, "completion")
    if completion < release:
        raise ValueError("completion precedes release")
    return weight * max(0.0, min(end, completion) - max(start, release, due))


def _union_seconds(intervals, start, end):
    intervals = sorted((max(start, a), min(end, b)) for a, b in intervals if b > start and a < end)
    total, last = 0.0, start
    for a, b in intervals:
        total += max(0.0, b - max(a, last))
        last = max(last, b)
    return total


def compute_metrics(source, *, window_start=0.0, window_end=None,
                    priority_weights=None, include_lot_details=False):
    """Compute complete/partial observed metrics; full physical validity is separate.

    Requires event history from the initial manifest. Snapshot-root-only traces
    are rejected until they carry independently replayable prehistory.
    """
    events = read_events(source)
    if not events or events[0].get("kind") != "initial":
        raise ValueError("missing initial manifest and replayable event history")
    for index, event in enumerate(events):
        if event.get("kind") == "snapshot_loaded" and (events[0]["time"] != 0 or event.get("prefix_event_count") != index):
            raise ValueError("snapshot root requires complete prehistory before metric computation")
    manifest = events[0]["manifest"]
    start = _finite(window_start, "window_start")
    observed_end = max(_finite(e["time"], "event time") for e in events)
    end = observed_end if window_end is None else _finite(window_end, "window_end")
    if start < events[0]["time"] or end > observed_end or end <= start:
        raise ValueError("metric window must be positive and within observed event history")
    weights = {int(k): _finite(v, "priority weight") for k, v in
               (DEFAULT_PRIORITY_WEIGHTS if priority_weights is None else priority_weights).items()}
    if any(v <= 0 for v in weights.values()):
        raise ValueError("priority weights must be positive")
    lots = {lot["id"]: lot for lot in manifest["lots"]}
    if len(lots) != len(manifest["lots"]):
        raise ValueError("duplicate lot in manifest")
    machines = {m["id"]: m for m in manifest["machines"]}
    production = {mid for mid, m in machines.items() if m["group"] != "Delay_32"}
    releases, completions, ready = {}, {}, {}
    queue_intervals, reservations, materials, calendar = defaultdict(list), defaultdict(list), {}, defaultdict(list)
    jobs_by_machine, dispatches = defaultdict(list), []
    previous = events[0]["time"]
    for e in events:
        t, kind = _finite(e["time"], "event time"), e["kind"]
        if t < previous:
            raise ValueError("time reversed")
        previous = t
        if t > end:
            break
        if kind == "release":
            lid = e["lot"]
            if lid not in lots or lid in releases:
                raise ValueError("unknown or duplicate release")
            releases[lid] = t
        elif kind == "lot_complete":
            lid = e["lot"]
            if lid not in releases or lid in completions:
                raise ValueError("unknown or duplicate completion")
            completions[lid] = t
        elif kind == "ready":
            if e["lot"] in ready:
                raise ValueError("duplicate ready state")
            ready[e["lot"]] = (t, e["step"])
        elif kind == "dispatch":
            mid, jid = e["machine"], e["job"]
            for lid in e["lots"]:
                if lid not in ready:
                    raise ValueError("dispatch without ready event")
                rt, step = ready.pop(lid)
                family = manifest["routes"][lots[lid]["route"]][step - 1]["family"]
                queue_intervals[family].append((rt, t))
            if jid in materials:
                raise ValueError("duplicate job")
            materials[jid] = [t, e["process_end"]]
            reservations[mid].append([t, e["machine_ready"]])
            jobs_by_machine[mid].append(jid)
            dispatches.append(e)
        elif kind == "downtime":
            mid = e["machine"]
            calendar[mid].append((e["blocked_until"] - e["duration"], e["blocked_until"]))
            for jid in e["affected_jobs"]:
                if jid not in materials:
                    raise ValueError("downtime references unknown job")
                materials[jid][1] += e["duration"]
            if reservations[mid] and reservations[mid][-1][1] > t:
                reservations[mid][-1][1] = e["machine_ready"]
    for lid, (rt, step) in ready.items():
        family = manifest["routes"][lots[lid]["route"]][step - 1]["family"]
        queue_intervals[family].append((rt, end))

    population = [lid for lid, rt in releases.items() if rt <= end and completions.get(lid, math.inf) > start]
    done = [lid for lid, ct in completions.items() if start < ct <= end]
    initial = [lid for lid, rt in releases.items() if rt <= start and completions.get(lid, math.inf) > start]
    arrivals = [lid for lid, rt in releases.items() if start < rt <= end]
    terminal = [lid for lid, rt in releases.items() if rt <= end and lid not in completions]
    details = []
    for lid in population:
        lot = lots[lid]
        if lot["priority"] not in weights:
            raise ValueError(f"unmapped priority {lot['priority']}")
        contribution = weighted_tardy_seconds(release=releases[lid], due=lot["due"],
            completion=completions.get(lid), window_start=start, window_end=end, weight=weights[lot["priority"]])
        details.append({"lot": lid, "priority": lot["priority"], "weight": weights[lot["priority"]],
                        "completed_in_window": lid in completions, "weighted_tardy_seconds": contribution})
    total = sum(row["weighted_tardy_seconds"] for row in details)
    weight_sum = sum(row["weight"] for row in details)
    exposure = sum(weights[lots[lid]["priority"]] * max(0.0, end - max(start, releases[lid])) for lid in population)
    summary = {}
    for field in ("part", "priority"):
        summary[field] = {}
        for value in sorted({lots[lid][field] for lid in population}, key=str):
            group_done = [lid for lid in done if lots[lid][field] == value]
            group_wip = [lid for lid in terminal if lots[lid][field] == value]
            ontime = sum(completions[lid] <= lots[lid]["due"] for lid in group_done)
            summary[field][str(value)] = {
                "completed_lots": len(group_done), "ontime_completed_lots": ontime,
                "ontime_fraction_completed_only": ontime / len(group_done) if group_done else None,
                "terminal_wip_lots": len(group_wip),
                "terminal_tardy_wip_lots": sum(lots[lid]["due"] < end for lid in group_wip)}
    fills, setup_seconds = [], 0.0
    family_statistics = {}
    for family in sorted({machines[mid]["family"] for mid in production}):
        mids = {mid for mid in production if machines[mid]["family"] == family}
        ds = [d for d in dispatches if d["machine"] in mids and start <= d["time"] < end]
        family_statistics[family] = {
            "machine_count": len(mids), "dispatches": len(ds),
            "operation_lots_dispatched": sum(len(d["lots"]) for d in ds),
            "queue_wait_lot_seconds": sum(max(0, min(b, end) - max(a, start)) for a, b in queue_intervals[family]),
            "reserved_observed_fraction": sum(_union_seconds(reservations[mid], start, end) for mid in mids) / (len(mids) * (end - start)),
            "calendar_down_observed_fraction": sum(_union_seconds(calendar[mid], start, end) for mid in mids) / (len(mids) * (end - start)),
            "material_present_observed_fraction": sum(_union_seconds([materials[jid] for jid in jobs_by_machine[mid]], start, end) for mid in mids) / (len(mids) * (end - start))}
    for d in dispatches:
        if d["machine"] not in production:
            continue
        setup_seconds += max(0.0, min(end, d["time"] + d["setup_seconds"]) - max(start, d["time"]))
        step = manifest["routes"][lots[d["lots"][0]]["route"]][d["steps"][0] - 1]
        if step["batch_max"] > 1 and start <= d["time"] < end:
            fills.append(len(d["lots"]) / step["batch_max"])
    result = {
        "metrics_version": METRICS_VERSION, "window_start": start, "window_end": end,
        "observed_seconds": end - start,
        "completed_declared_window": bool(events[-1].get("kind") == "terminal" and end == manifest["horizon"]),
        "priority_weights": {str(k): v for k, v in weights.items()},
        "priority_weight_status": "development_proposal_requires_prefreeze",
        "weighted_tardy_lot_seconds": total,
        "weighted_tardy_lot_hours": total / 3600,
        "weighted_tardy_seconds_completed_contribution": sum(r["weighted_tardy_seconds"] for r in details if r["completed_in_window"]),
        "weighted_tardy_seconds_unfinished_contribution": sum(r["weighted_tardy_seconds"] for r in details if not r["completed_in_window"]),
        "normalization_population_weight": weight_sum,
        "mean_tardy_seconds_per_weighted_lot": total / weight_sum if weight_sum else None,
        "tardy_fraction_of_exogenous_weighted_exposure": total / exposure if exposure else None,
        "exogenous_weighted_exposure_seconds": exposure,
        "throughput_lots": len(done), "throughput_wafers": sum(lots[lid]["pieces"] for lid in done),
        "initial_window_wip_lots": len(initial), "released_in_window_lots": len(arrivals),
        "terminal_wip_lots": len(terminal),
        "lot_conservation_valid": len(initial) + len(arrivals) == len(done) + len(terminal),
        "terminal_tardy_wip_lots": sum(lots[lid]["due"] < end for lid in terminal),
        "window_start_already_tardy_wip_lots": sum(lots[lid]["due"] < start for lid in initial),
        "mean_cycle_seconds_completed": sum(completions[lid] - lots[lid]["release"] for lid in done) / len(done) if done else None,
        "completion_groups": summary, "setup_loss_seconds": setup_seconds,
        "batch_dispatch_count": len(fills), "batch_fill_mean": sum(fills) / len(fills) if fills else None,
        "batch_fill_ratios": fills, "production_family_statistics": family_statistics,
        "interpretation": "observed-window metrics, not a steady-state or physical-validity certificate"}
    if include_lot_details:
        result["lot_contributions"] = details
    return result
