"""Physical duration supports and causal route lower bounds. No rework revisits projected."""


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
                     executing=None, release=None, observed_first=False,
                     end_index=None, horizon_end=None, minimum_end_index=None):
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
    for i in range(start_index, len(route) if end_index is None else end_index+1):
        if horizon_end is not None and bound>horizon_end and i>minimum_end_index:
            break
        step = route[i]
        result.append(dict(step=step['step'], earliest_start=bound, nominal_start=nominal,
                           conditional=not (i == start_index and observed_first),
                           sampling_percent=step['sampling_percent']))
        lo, mean, _ = phase_duration(route, i, machines)
        if step['sampling_percent'] >= 100 or (i == start_index and observed_first):
            bound += lo
        nominal += mean
    return result



def frozen_operations(problem, manifest, *, running_jobs=(), dispatches=()):
    """Enrich existing frozen operations only; never extend sealed inventories.

    Missing public job starts imply a weak now lower bound, never a mean bound.
    """
    from collections import defaultdict
    from copy import deepcopy
    result = deepcopy(problem)
    machines = defaultdict(list)
    for m in manifest['machines']:
        machines[m['family']].append(m)
    lots = {l['id']: l for l in manifest['lots']}
    groups = defaultdict(list)
    for o in result['operations']:
        groups[o['lot_id']].append(o)
    jobs = {lid: j for j in running_jobs for lid in j['lot_ids']}
    events = {e['job']: e for e in dispatches if e['kind']=='dispatch' and e['time']<=problem['time']}
    now = problem['time']
    for lid, ops in groups.items():
        ops.sort(key=lambda o:o['step'])
        first=ops[0]; lot=lots[lid]; route=manifest['routes'][lot['route']]
        start=first['step']-1; executing=None; nominal=max(now,first['release_time'])
        job=jobs.get(lid); event=events.get(job['job']) if job else None
        if first.get('readiness_basis')=='executing_predecessor' and event:
            index=event['steps'][event['lots'].index(lid)]-1
            executing=(job['started_at'],phase_duration(route,index,machines)[0])
            start=index+1
            nominal=max(now,job['started_at']+event['setup_seconds']+phase_duration(route,index,machines)[1])
        walk={r['step']:r for r in lower_bound_walk(route,start,now=now,first_bound=now,
            first_nominal=nominal,machines=machines,executing=executing,
            release=lot['release'] if lot['release']>now else None,
            observed_first=first.get('readiness_basis')=='observed_ready',end_index=ops[-1]['step']-1)}
        for op in ops:
            row=walk[op['step']]
            op.update(earliest_start=row['earliest_start'],nominal_start=row['nominal_start'])
            step=route[op['step']-1]; support=distribution_bounds(step['processing'])
            group=[m for m in machines[step['family']] if m['id'] in op['eligible_machines']]
            op['processing_seconds_min']=support[0]+min(m['load']+m['unload'] for m in group)
            op['processing_seconds_max']=None if support[2] is None else support[2]+max(m['load']+m['unload'] for m in group)
            if op.pop('qualification_uncertain',False):
                op['qualification_basis']='no recorded dedication; simulator does not restrict'
    return result


def public_operation(op, now):
    """Public labels; internal compatibility release_time is not an arrival fact."""
    from copy import deepcopy
    row=deepcopy(op)
    row.pop('release_time',None)
    if row.pop('qualification_uncertain',False):
        row['qualification_basis']='no recorded dedication; simulator does not restrict'
    observed=not op.get('conditional',False) and not op.get('predecessor_ids') and op.get('release_time',now)<=now
    row.setdefault('earliest_start', max(now,op.get('release_time',now)) if observed else now)
    row.setdefault('nominal_start', None if op.get('predecessor_ids') else max(now,op.get('release_time',now)))
    if type(row['earliest_start']) in (int,float):
        row['earliest_start']=max(now,row['earliest_start'])
    if not observed:
        row.pop('waiting_since',None)
    return row


def queue_diagnostics(ledger):
    rows=ledger.rows(); queues={}; absent=[]
    for task in ledger.pending_tasks():
        queues.setdefault(task['machine'],[]).append(task)
        missing=[o for o in task['operation_ids'] if o not in ledger.operations]
        if missing:
            absent.append(dict(task_id=task['id'],operation_ids=missing,action='model cancellation required'))
    blocked=[]
    for mid, tasks in sorted(queues.items()):
        head=tasks[0]
        invalid=ledger.task_receipts.get(head['id'],{}).get('state')=='invalid' or any(
            o not in ledger.operations or rows.get(o,{}).get('state')=='invalid' for o in head['operation_ids'])
        reason='invalid task' if invalid else 'head task waiting for material' if any(
            not rows.get(o,{}).get('ready',False) for o in head['operation_ids']) else None
        if reason:
            blocked.append(dict(machine=mid,task_id=head['id'],reason=reason))
    return dict(blocked_queues=blocked,absent_operation_tasks=absent)
