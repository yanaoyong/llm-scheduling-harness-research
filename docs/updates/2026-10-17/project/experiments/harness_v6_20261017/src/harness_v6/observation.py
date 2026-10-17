"""Causal full-fab planning observations, separate from recoverable private state.

Actual future process/transport/PM completion times and queued random events are
private. Predictions below use route means, observed starts/setup and elapsed
past downtime. They are nominal forecasts, not certified resource reservations.
"""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
from weakref import WeakKeyDictionary

_HISTORY = WeakKeyDictionary()
_ROUTE_TABLES = WeakKeyDictionary()

def _route_tables(env):
    """Cache immutable route facts; preserve original left-to-right float sums."""
    cached = _ROUTE_TABLES.get(env)
    if cached is None:
        cached = {}
        for name, route in env.routes.items():
            steps = route.steps
            cached[name] = [(sum(_mean(s.processing_time) for s in steps[i+1:]),
                [s for s in steps[:i] if s.lot_to_lens_dedication == step.order])
                for i, step in enumerate(steps)]
        _ROUTE_TABLES[env] = cached
    return cached



def _mean(distribution):
    if isinstance(distribution, dict):
        return distribution.get('c', distribution.get('m', distribution.get('mean')))
    if hasattr(distribution,'c'):
        return distribution.c
    if hasattr(distribution,'m'):
        return distribution.m
    if hasattr(distribution,'p'):
        return distribution.p
    raise TypeError(type(distribution))


def _history(env):
    """Index append-only observed history once; no simulator state is modified."""
    old=_HISTORY.get(env)
    if old is None or old['trace'] is not env.trace or old['count'] > len(env.trace):
        old={'trace':env.trace,'count':0,'dispatch':{},'latest':{},'down':defaultdict(list)}
        _HISTORY[env]=old
    for event in env.trace[old['count']:]:
        if event['kind']=='dispatch':
            # Deliberately exclude sampled processing/cadence/transport/PM durations.
            old['dispatch'][event['job']]={
                'start':event['time'],'machine':event['machine'],
                'setup_seconds':event['setup_seconds'],
                'steps':event['steps'],'lots':event['lots'],
                'piece_pm_keys':[x['key'] for x in event.get('piece_pm',[])]}
            old['latest'][event['machine']]=event['job']
        elif event['kind']=='downtime':
            old['down'][event['machine']].append(event)
    old['count']=len(env.trace)
    return old


def _union_length(intervals):
    total=0.; end=float('-inf')
    for left,right in sorted(intervals):
        if right>max(left,end):
            total+=right-max(left,end)
        end=max(end,right)
    return total


def _past_downtime(env, history, mid, since, job_id=None):
    intervals=[]
    for event in history['down'].get(mid,[]):
        if job_id is not None and job_id not in event['affected_jobs']:
            continue
        # A future end is clipped to now; its private duration is not disclosed.
        left=max(since,event['time']); right=min(env.t,event['blocked_until'])
        if right>left:
            intervals.append((left,right))
    return _union_length(intervals)


def _repair_forecast(env, history, mid):
    if env.machine_state[mid]['down_until']<=env.t:
        return 0.
    events=history['down'].get(mid,[])
    if not events:
        return 1.  # Unknown active repair: causal lower bound, never exact future end.
    event=events[-1]
    expected=_mean(env.calendars[event['calendar']]['length'])
    return max(1.,expected-(env.t-event['time']))


def _job_forecast(env, history, jid, pm_by_key):
    job=env.jobs[jid]
    evidence=history['dispatch'][jid]
    mid=job['machine']; machine=env.machines[mid]
    lot=env.lots[evidence['lots'][0]]
    step=env.routes[lot['route']].steps[evidence['steps'][0]-1]
    processing=_mean(step.processing_time)+machine.load_time+machine.unload_time
    occupation=_mean(step.cascading_time)+(0 if machine.cascading else machine.load_time+machine.unload_time)
    setup=evidence['setup_seconds']
    base=evidence['start']+setup
    paused=_past_downtime(env,history,mid,evidence['start'],jid)
    repair=_repair_forecast(env,history,mid) if jid in env.processing_by_machine.get(mid,()) else 0.
    expected_process_end=base+processing+paused+repair
    current_processing=jid in env.processing_by_machine.get(mid,())
    if current_processing:
        # The nominal mean may be exhausted while real processing is still active.
        expected_process_end=max(env.t+1.,expected_process_end)
    elif job['process_end']<=env.t:
        # This is a completed, observable event, not a future random outcome.
        expected_process_end=job['process_end']
    next_index=evidence['steps'][0]
    route=env.routes[lot['route']].steps
    expected_transport=_mean(route[next_index].transport_time) if next_index<len(route) and route[next_index].transport_time else 0.
    lot_available=expected_process_end+expected_transport
    if not job['done']:
        lot_available=max(env.t+1.,lot_available)
    expected_pm=sum(_mean(pm_by_key[key]) for key in evidence['piece_pm_keys'])
    machine_available=base+(max(processing,occupation) if expected_pm else occupation)+expected_pm
    machine_available+=_past_downtime(env,history,mid,evidence['start'])
    if env.machine_state[mid]['down_until']>env.t:
        machine_available=max(machine_available,env.t+_repair_forecast(env,history,mid))
    return {'process_end':expected_process_end,'lot_available':lot_available,
            'machine_available':machine_available,'expected_piece_pm_seconds':expected_pm}


def build_problem(env, plan_seconds=14400, lookahead_depth=3):
    """Export common observations and conditional expected routes without RNG state.

    `currently_busy`/`currently_down` are observable booleans. `available_at`,
    `processing_until`, and successor release times are forecasts. Planned public
    release streams are not expanded here; newly released demand triggers replans.
    """
    if plan_seconds<=0 or type(lookahead_depth) is not int or lookahead_depth<1:
        raise ValueError('positive planning window and lookahead depth required')
    history=_history(env)
    route_tables=_route_tables(env)
    pm_by_key={c['key']:c['length'] for cs in env.pm_counters.values() for c in cs}
    forecasts={jid:_job_forecast(env,history,jid,pm_by_key)
               for jid,job in env.jobs.items() if not job['done']}
    machine_rows=[]
    for mid in sorted(env.physical):
        machine,state=env.machines[mid],env.machine_state[mid]
        busy=state['ready']>env.t
        down=state['down_until']>env.t
        available=env.t
        if busy or down:
            available=env.t+max(1.,_repair_forecast(env,history,mid))
            latest=history['latest'].get(mid)
            if latest is not None:
                predicted=forecasts.get(latest) or _job_forecast(env,history,latest,pm_by_key)
                available=max(available,predicted['machine_available'])
        active=[]
        for jid in sorted(env.processing_by_machine.get(mid,())):
            active.append(forecasts[jid]['process_end'])
        machine_rows.append({'machine':mid,'family':machine.family,'available_at':available,
            'currently_busy':busy,'currently_down':down,
            'current_setup':state['setup'],'min_left':state['min_left'],'min_setup':state['min_setup'],
            'cascading':machine.cascading,'processing_until':active,'unavailable_intervals':[],
            'availability_basis':'observed state + source means + elapsed past downtime; unknown future events excluded'})
    active_job_by_lot={lid:jid for jid,job in env.jobs.items() if not job['done'] for lid in job['lots']}
    operations=[]
    for lid,lot in sorted(env.lots.items()):
        if lot['status'] in {'done','unreleased'}:
            continue
        index=lot['step']; ready=env.t
        if lot['status']=='processing':
            ready=forecasts[active_job_by_lot[lid]]['lot_available']
            index+=1
        previous=None; delay=0.; count=0; conditional_virtual=[]
        route=env.routes[lot['route']].steps
        # Future bindings can be endogenous to another operation in this plan.
        included_by_step={}
        for si in range(index,len(route)):
            step=route[si]
            mids=[mid for mid in env.family_machines[step.family] if mid in env.physical]
            next_transport=_mean(route[si+1].transport_time) if si+1<len(route) and route[si+1].transport_time else 0.
            if not mids:
                virtual=env.machines[env.family_machines[step.family][0]]
                delay+=_mean(step.processing_time)+virtual.load_time+virtual.unload_time+next_transport
                conditional_virtual.append({'step':step.order,'sampling_percent':step.sampling_percent,
                    'rework_percent':step.rework_percent,'nominal_delay_seconds':_mean(step.processing_time)+virtual.load_time+virtual.unload_time+next_transport})
                continue
            if count>=lookahead_depth:
                break
            known=lot['dedications'].get(str(step.order))
            if known is not None:
                mids=[known]
            machine=env.machines[mids[0]]
            visit=lot['visits'].get(str(step.order),0)+(0 if si==lot['step'] and lot['status']=='waiting' else 1)
            oid=f'{lid}:{step.order}:{visit}'
            if previous is not None:
                operations[-1]['transport_seconds']+=delay
                operations[-1]['conditional_virtual_successors']=deepcopy(conditional_virtual)
            op={'operation_id':oid,'lot_id':lid,'step':step.order,'visit':visit,'family':step.family,
                'eligible_machines':mids,'release_time':ready+delay if previous is None else env.t,
                'predecessor_ids':[previous] if previous else [],
                'processing_seconds':_mean(step.processing_time)+machine.load_time+machine.unload_time,
                'occupation_seconds':_mean(step.cascading_time)+(0 if machine.cascading else machine.load_time+machine.unload_time),
                'transport_seconds':next_transport,'batch_key':[lot['part'],step.order,step.step_name],
                'batch_min':step.batch_min,'batch_max':step.batch_max,
                'setup':step.setup_needed,'setup_time':step.setup_time,'priority':lot['priority'],'due':lot['due'],
                'remaining_work_seconds':route_tables[lot['route']][si][0],
                'terminal':si==len(route)-1,'waiting_since':lot['ready_since'],
                'conditional':si!=lot['step'] or lot['status']!='waiting',
                'readiness_basis':('exported_predecessor' if previous is not None else
                    'executing_predecessor' if lot['status']=='processing' else
                    'observed_ready' if si==lot['step'] and lot['status']=='waiting' else 'nominal_unplanned_route'),
                'sampling_percent':step.sampling_percent,'rework_percent':step.rework_percent,
                'initial_virtual_predecessors':deepcopy(conditional_virtual) if previous is None else []}
            binding_sources=route_tables[lot['route']][si][1]
            if known is not None:
                op['qualification_basis']='observed binding'
            elif binding_sources:
                origin=binding_sources[-1].order
                if origin in included_by_step:
                    op['same_machine_as']=included_by_step[origin]
                    op['qualification_basis']='conditional binding to included nominal predecessor'
                else:
                    op['qualification_basis']='historical or out-of-window binding unknown; executor rechecks observed binding'
                    op['qualification_uncertain']=True
                    op['binding_origin_step']=origin
            else:
                op['qualification_basis']='source family eligibility'
            operations.append(op); included_by_step[step.order]=oid
            previous=oid; delay=0.; conditional_virtual=[]; count+=1
    frozen=[]
    if env.plan and env.t<env.plan['freeze_until']:
        frozen=[deepcopy(task) for task in env.plan['tasks']
                if (env.plan['version'],task['id']) not in env.executed_tasks and task.get('not_before',env.plan['created_at'])<env.plan['freeze_until']]
        for task in frozen:
            task.setdefault('operation_ids',[f'{lid}:{step}:{visit}' for lid,step,visit in zip(task['lot_ids'],task['steps'],task['visits'])])
            task['original_not_before']=task.get('not_before',env.plan['created_at'])
            # A missed earliest-start condition cannot force a start in the past.
            # The executor still requires preservation of the original task record.
            task['start']=max(env.t,task.get('start',task.get('not_before',env.plan['created_at'])))
    return {'schema':'smt-fullfab-problem-2','time':env.t,'horizon_end':env.t+plan_seconds,
        'machines':machine_rows,'operations':operations,'setup_transitions':deepcopy(env.manifest['setups']),
        'min_runs':dict(env.min_runs),'lookahead_depth':lookahead_depth,'frozen_tasks':frozen,
        'uncertainty':'expected residual forecasts; nominal no-skip/no-rework successors; unknown history explicitly marked',
        'unrevealed':'future random failure calendar, repair durations, transport/processing samples, rework/sampling outcomes and RNG state',
        'forecast_limitations':['mean residuals can be exhausted while observed work remains busy; one-second lower bound then used',
            'overlapping repairs use a nominal last-observed-repair residual; no exact future end is exposed',
            'piece PM duration is the source mean, not the private sampled duration',
            'initial historical bindings and active CQT start times cannot be recovered from source WIP',
            'known future public releases/maintenance windows are not yet expanded; replan on observations'],
        'scope':sorted(env.physical)}
