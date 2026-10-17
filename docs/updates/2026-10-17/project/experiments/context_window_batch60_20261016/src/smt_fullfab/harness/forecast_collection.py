"""Public arrival forecasts along already chosen tasks. Never choose production.

Unknown predecessor work stays unknown: no hypothetical dispatch, resource
assignment, sampled future event or optimizer is used to make a reminder urgent.
"""
def supported_arrivals(problem, pending):
    operations = {o['operation_id']:o for o in problem['operations']}
    machines = {m['machine']:m for m in problem['machines']}
    transitions = problem.get('setup_transitions',[])
    setups = ({(old,new):seconds for old,values in transitions.items() for new,seconds in values.items()}
              if isinstance(transitions,dict) else {(r['old'],r['new']):r['seconds'] for r in transitions})
    tasks = {}; owner = {}; previous = {}
    for mid, queue in pending.items():
        for index, task in enumerate(queue):
            tasks[task['id']] = task
            previous[task['id']] = queue[index-1]['id'] if index else None
            for oid in task.get('operation_ids',[]): owner[oid] = task['id']
    cache = {}; visiting = set()

    def arrival(oid):
        key = ('operation',oid)
        if key in cache: return cache[key]
        if key in visiting or oid not in operations: return None
        visiting.add(key); op = operations[oid]; result = None
        parents = op.get('predecessor_ids',[])
        if parents:
            ends = [finish(owner[p]) if p in owner else None for p in parents]
            if all(end is not None for end in ends):
                result = max(end['process_end'] + operations[p].get('transport_seconds',0)
                             for p,end in zip(parents,ends))
        elif not op.get('conditional',False) or op.get('readiness_basis') == 'executing_predecessor':
            result = op.get('release_time',problem['time'])
        visiting.remove(key); cache[key] = result
        return result

    def finish(tid):
        key = ('task',tid)
        if key in cache: return cache[key]
        if key in visiting: return None
        visiting.add(key); task = tasks[tid]; ids = task.get('operation_ids',[])
        arrivals = [arrival(oid) for oid in ids]
        prior = finish(previous[tid]) if previous[tid] else None
        result = None
        if ids and all(a is not None for a in arrivals) and (previous[tid] is None or prior is not None):
            rows = [operations[oid] for oid in ids]
            start = max(problem['time'],task['not_before'],machines[task['machine']]['available_at'],
                        prior['machine_end'] if prior else problem['time'],*arrivals)
            # Follow the chosen queue's setup transitions, never reorder it.
            old = prior['setup_after'] if prior else machines[task['machine']].get('current_setup','')
            new = rows[0].get('setup','')
            override = rows[0].get('setup_time')
            setup = (override if override is not None else setups.get((old,new),setups.get(('',new),0))) if new and new!=old else 0
            result = {'process_end':start+setup+max(o['processing_seconds'] for o in rows),
                      'machine_end':start+setup+max(o.get('occupation_seconds',o['processing_seconds']) for o in rows),
                      'setup_after':new or old}
        visiting.remove(key); cache[key] = result
        return result

    return {oid:eta for oid in operations if (eta:=arrival(oid)) is not None}


def forecast_fields(machine, operations, arrivals, lead):
    supported = [o for o in operations if o['operation_id'] in arrivals]
    eta = min((arrivals[o['operation_id']] for o in supported),default=None)
    available = machine['available_at'] if machine.get('currently_busy') or machine.get('currently_down') else None
    due = max(available,eta)-lead if available is not None and eta is not None else None
    return {'forecast_available_at':available, 'supported_arrival_at':eta,
            'forecast_due_at':due, 'supported_operation_count':len(supported)}


def focus_demands(demands, trigger, now, lookahead, ready_wait=60):
    """Only prioritize evidence. Return every urgent machine even if it overflows."""
    trigger = trigger or {}
    triggered = set(trigger.get('forecast_trigger_machines',[]))
    triggered.update(row['machine'] for row in trigger.get('machines',[]))
    result = []
    for demand in demands:
        if demand['ready_since'] is not None:
            rank, reason, deadline = 0, 'ready_unplanned', demand['ready_since']+ready_wait
        elif demand['machine'] in triggered:
            rank, reason, deadline = 1, 'triggering_machine', now
        elif demand.get('forecast_due_at') is not None and (lookahead is None or demand['forecast_due_at'] <= now+lookahead):
            rank, reason, deadline = 2, 'nearby_supported_forecast', demand['forecast_due_at']
        else: continue
        result.append({'machine':demand['machine'],'rank':rank,'reason':reason,'deadline':deadline,
                       'operation_ids':list(demand['operation_ids']),
                       **{k:demand[k] for k in ('forecast_latest_start','forecast_need_at','forecast_notice_key') if k in demand}})
    return sorted(result,key=lambda d:(d['rank'],d['deadline'],d['machine']))
