"""Pure Phase S measurement prototypes; never imported by production code."""
from collections import Counter


def distribution_bounds(spec):
    """Nonnegative duration support; unknown/unbounded families fail explicitly."""
    kind = spec['type']
    if kind == 'constant':
        return spec['c'], spec['c'], spec['c']
    if kind == 'uniform':
        return spec['m'] - spec['offset'], spec['m'], spec['m'] + spec['offset']
    if kind == 'exponential':
        return 0., spec['mean'], None
    raise ValueError('unsupported distribution: ' + kind)


def phase_duration(route, index, machines):
    """Material completion: process + load/unload + transport INTO next step.

    Setup/queue/batch/PM/breakdowns contribute zero to the lower bound. Upper
    support here is intrinsic duration only, never a wall-clock completion bound.
    """
    step = route[index]
    group = machines[step['family']] if isinstance(machines, dict) else [m for m in machines if m['family'] == step['family']]
    load_min = min(m['load'] + m['unload'] for m in group)
    load_max = max(m['load'] + m['unload'] for m in group)
    p = distribution_bounds(step['processing'])
    tr = distribution_bounds(route[index + 1]['transport']) if index + 1 < len(route) else (0, 0, 0)
    return (p[0] + load_min + tr[0], p[1] + load_min + tr[1],
            None if p[2] is None or tr[2] is None else p[2] + load_max + tr[2])


def lower_bound_walk(route, start_index, *, now, first_bound, first_nominal, machines,
                     executing=None, release=None, observed_first=False):
    """Return all nominal route steps with separate earliest and nominal starts.

    executing=(public started_at, intrinsic minimum duration) optionally tightens
    the first bound. A sampled-out step consumes no time for later steps. The
    already observed waiting step cannot be sampled out again.
    """
    bound = max(now, first_bound, release if release is not None else now)
    if executing is not None:
        bound = max(bound, executing[0] + executing[1])
    nominal = max(now, first_nominal, release if release is not None else now)
    result = []
    for i in range(start_index, len(route)):
        step = route[i]
        result.append(dict(step=step['step'], earliest_start=bound, nominal_start=nominal,
                           conditional=not (i == start_index and observed_first),
                           sampling_percent=step['sampling_percent']))
        lo, mean, _ = phase_duration(route, i, machines)
        if step['sampling_percent'] >= 100 or (i == start_index and observed_first):
            bound += lo
        nominal += mean
    return result


def slot_available(machine):
    # Values are forecasts, but list membership is observed processing activity.
    return len(machine.get('processing_until', [])) < (2 if machine.get('cascading') else 1)


def persistent_idle(current, previous):
    return set(current) & set(previous)


def depth_distribution(rows, lot_ids):
    counts = Counter(r['operation_id'].rsplit(':', 2)[0] for r in rows)
    return dict(sorted(Counter(counts[lid] for lid in lot_ids).items()))
