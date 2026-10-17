"""Offline measurement only; never proposes, dispatches, or advances work."""
from src.smt_fullfab.harness.factory import restore


def measure(ev,trace,end):
    batches=[ev.get(e['payload_ref']) for e in ev.value['events'] if e['kind']=='execution_batch']
    replayed_seconds=0.
    matches=[b for b in batches if abs(b['to']-end)<1e-7]
    if matches:
        b=min(matches,key=lambda b:b['event_end'])
        env=restore(ev.get(b['after_state_ref']),trace[:b['event_end']])
    elif abs(ev.value['head']['time']-end)<1e-7:
        env=restore(ev.get(ev.value['head']['state_ref']),trace)
    else:
        crossing=[b for b in batches if b['from']<end<b['to']]
        if not crossing:return {'available':False,'reason':'No preserved execution batch covers the common boundary'}
        b=min(crossing,key=lambda b:b['event_end']);prefix=trace[:b['event_start']]
        env=restore(ev.get(b['before_state_ref']),prefix)
        env.advance_plan(until=end)
        assert abs(env.t-end)<1e-7,'Replay stopped before the common boundary'
        def physical(rows):
            return [{k:v for k,v in e.items() if k!='seq'} for e in rows if e['time']<=end and e['kind'] not in ('time_advance','batch_check')]
        assert physical(env.trace[len(prefix):])==physical(trace[b['event_start']:b['event_end']]),'Read-only replay differs from actual physical events'
        replayed_seconds=end-b['from']
    pending=env._pending();assigned={oid for tasks in pending.values() for t in tasks for oid in t['operation_ids']}
    cfg=ev.manifest['config'];problem=env.problem(plan_seconds=cfg['plan_seconds'],lookahead_depth=cfg['lookahead_depth'])
    op_by_lot={o['lot_id']:o['operation_id'] for o in problem['operations'] if not o['conditional'] and o['release_time']<=end}
    gaps=env._gaps();urgent=set();machines=[];reserved_only=[];too_small=[]
    for gap in gaps:
        mid=gap['machine'];ready=[];all_candidates=[]
        for lots in env._groups(mid):
            all_candidates.extend(op_by_lot[lid] for lid in lots)
            uncovered=[lid for lid in lots if op_by_lot[lid] not in assigned]
            if uncovered and len(uncovered)>=env._step(env.lots[uncovered[0]]).batch_min:
                ready.extend(op_by_lot[lid] for lid in uncovered)
        if ready:machines.append(mid);urgent.update(ready)
        elif all_candidates and all(oid in assigned for oid in all_candidates):reserved_only.append(mid)
        else:too_small.append(mid)
    physical_ready=set();physical_machines=[]
    for mid in sorted(env.physical):
        ready=[]
        for lots in env._groups(mid):
            uncovered=[lid for lid in lots if op_by_lot[lid] not in assigned]
            if uncovered and len(uncovered)>=env._step(env.lots[uncovered[0]]).batch_min:
                ready.extend(op_by_lot[lid] for lid in uncovered)
        if ready:physical_ready.update(ready);physical_machines.append(mid)
    invalid_pending=[]
    for tasks in pending.values():
        for task in tasks:
            if any(env.lots[lid]['status']=='done' or env.lots[lid]['step']+1>step or env.lots[lid]['visits'].get(str(step),0)>visit
                   for lid,step,visit in zip(task['lot_ids'],task['steps'],task['visits'])):
                invalid_pending.append(task['id'])
    unassigned=[o for o in problem['operations'] if o['operation_id'] not in assigned]
    from src.smt_fullfab.harness.batch_window import observe_demands
    observe_demands(env,problem,gaps)
    backlog={'time':end,'accepted_pending_task_count':sum(len(v) for v in pending.values()),
       'unassigned_public_operations':len(unassigned),'unassigned_nonconditional_operations':sum(not o['conditional'] for o in unassigned),
       'pending_demand_machine_count':len(env.batch_state['pending_demands']),
       'program_reported_gap_machines':len(gaps),'measurement':'Preserved common-boundary factory state before any new planning at that boundary'}
    return {'available':True,'time':end,'global_backlog':backlog,'method':'Use an exact snapshot or replay only the already committed plan inside a recorded execution batch; verify physical events against the actual trace.',
       'unassigned_immediately_executable_unique_operations':len(urgent),'unassigned_immediately_executable_operation_ids':sorted(urgent),
       'gap_filtered_metric_scope':'Only machines reported by the program as lacking a queue/hold; not every physically available machine.',
       'unassigned_physically_ready_unique_operations':len(physical_ready),'unassigned_physically_ready_operation_ids':sorted(physical_ready),
       'physical_ready_metric_scope':'All physically eligible machines and legal batch minima, before enforcing existing queue order or explicit holds; execution may require a new model choice.',
       'physically_eligible_machines_for_unassigned_work':physical_machines,'observed_invalid_pending_task_ids':sorted(invalid_pending),
       'machines_with_an_unassigned_legal_batch':machines,'program_reported_gap_machine_count':len(gaps),
       'gap_machines_whose_candidates_are_all_already_assigned':reserved_only,
       'gap_machines_without_enough_unassigned_lots_to_form_a_batch':too_small,
       'production_tasks_selected':0,'actual_simulation_advanced_seconds':0,'offline_replay_seconds':replayed_seconds}
