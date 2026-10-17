"""Event-driven collection; no production selection and no fixed batch interval."""
from copy import deepcopy
from .capacity_config import POLICY, DEADLINE_POLICY, experiment_config


def configure(env, *, anchor, capacity=None, plan_seconds=14400, lookahead_depth=2):
    capacity = deepcopy(capacity or experiment_config('G1')['capacity_experiment'])
    settings = {'policy': capacity['policy'], 'anchor': anchor, 'capacity': capacity,
                'plan_seconds': plan_seconds, 'lookahead_depth': lookahead_depth}
    if hasattr(env, 'batch_state'):
        if any(env.batch_state[k] != v for k, v in settings.items()):
            raise ValueError('Cannot change restored collection settings')
        return
    env.batch_state = {**settings, 'pending_demands': {}, 'ready_since': {}, 'last_measurement': None,
                       'capacity_watermark': {}, 'presented_revisions': {}, 'reviewed_forecasts': {},
                       'last_planning_at': None, 'machine_reviews': {},
                       'batch_sequence': 0, 'active_batch': None, 'last_batch_receipt': None}
    if capacity['policy']==DEADLINE_POLICY: env.batch_state['forecast_notifications']={}
    env._emit('batching_enabled', policy=capacity['policy'], anchor=anchor,
              max_ready_wait_seconds=capacity['max_ready_wait_seconds'],
              planning_lead_seconds=capacity['planning_lead_seconds'],
              input_token_budget=capacity['input_token_budget'],
              forecast_min_interval_seconds=capacity['forecast_min_interval_seconds'],
              forecast_lookahead_seconds=capacity['forecast_lookahead_seconds'],
              capacity_trigger_fraction=capacity['capacity_trigger_fraction'],
              **({'execution_rule':capacity['execution_rule']} if capacity['policy']==DEADLINE_POLICY else {}))
    observe_demands(env, env.problem(plan_seconds=plan_seconds, lookahead_depth=lookahead_depth), env._gaps())


def observe_demands(env, problem, gaps):
    """Public forecasts only; no simulator queue timestamps or production ranking.

    An executing last task with no pending successor creates a future planning need.
    A submitted queue/active hold is already an explicit production decision.
    """
    state = env.batch_state; old = state['pending_demands']
    # Only observed event identity, never sampled future durations/timestamps.
    observed_epoch = {}
    for index, event in enumerate(env.trace):
        if event['kind'] in ('dispatch','downtime') and 'machine' in event:
            observed_epoch[event['machine']] = index
    pending, holds = env._pending(), env._active_holds()
    from .forecast_collection import supported_arrivals, forecast_fields
    arrivals = supported_arrivals(problem,pending)
    reserved = {oid for tasks in pending.values() for t in tasks for oid in t.get('operation_ids', [])}
    available = {}
    for op in problem['operations']:
        if op['operation_id'] in reserved: continue
        for mid in op['eligible_machines']:
            available.setdefault(mid, []).append(op)
    gap_by_mid = {r['machine']: r for r in gaps}
    state['ready_since'] = {str(mid):state['ready_since'].get(str(mid), env.t) for mid in gap_by_mid}
    demands = {}
    for machine in problem['machines']:
        mid = machine['machine']; key = str(mid)
        if pending.get(mid) or holds.get(mid, env.t) > env.t: continue
        ops = available.get(mid, [])
        if not ops and mid not in gap_by_mid: continue
        ready_since = state['ready_since'].get(key)
        # Batch minima alone do not invent a forecast start deadline.
        forecast = forecast_fields(machine,ops,arrivals,state['capacity']['planning_lead_seconds'])
        demands[key] = {'machine':mid, 'family':machine['family'],
                        'first_seen':old.get(key, {}).get('first_seen', env.t),
                        'ready_since':ready_since, **forecast,
                        'forecast_revision':[observed_epoch.get(mid),bool(machine.get('currently_busy')),
                                             bool(machine.get('currently_down'))],
                        'operation_ids':[op['operation_id'] for op in ops]}
        if state['policy']==DEADLINE_POLICY:
            from .deadline_collection import forecast_metadata
            demands[key].update(forecast_metadata(demands[key],ops,arrivals,state['capacity']['planning_lead_seconds']))
    state['pending_demands'] = demands
    return demands


def capacity_measurement(env, problem):
    from .capacity_prompt import PublicPacket, instructions
    from .transport import PROTOCOL_TEXT
    from .contracts import encode, digest
    from .local_tokens import count
    cfg = env.batch_state['capacity']
    from .planning_batches import incoming_demands
    incoming = incoming_demands(env, problem)
    base = env.plan or {'version':'uncommitted', 'created_at':env.t, 'valid_until':env.horizon,
                       'freeze_until':env.t, 'reason':'No confirmed plan', 'scope':problem['scope'], 'tasks':[], 'holds':[]}
    context = {'problem':problem, 'base_plan':base,
               'execution_state':{'dispatched_task_ids':[t['id'] for t in base['tasks']
                   if (base['version'],t['id']) in env.executed_tasks]},
               'batch_demands':incoming,
               'problem_ref':'public-snapshot-at-decision', 'facts_ref':'public-facts-at-decision',
               'base_plan_ref':'submitted-plan-at-decision'}
    builder = PublicPacket(context)
    frame = builder.frame(len(builder.bundles), {})
    text = PROTOCOL_TEXT + instructions(cfg) + '\n' + encode(frame).decode()
    tokens = count(text) + cfg['wrapper_reserve_tokens']
    return {'pending_input_tokens':tokens, 'input_token_budget':cfg['input_token_budget'],
            'trigger_tokens':int(cfg['input_token_budget'] * cfg['capacity_trigger_fraction']),
            'pending_operations':len(builder.order), 'pending_machines':len(context['batch_demands']),
            'incoming_operation_count':len({oid for d in incoming for oid in d['operation_ids']}),
            'total_pending_machines':len(env.batch_state['pending_demands']),
            'scope':'new_or_changed_since_last_accepted_batch; not the entire unresolved catalog',
            'public_packet_sha256':digest(frame), 'encoding':'o200k_base',
            'includes_future_tool_feedback':False}


def decision(env, problem, gaps, measurement):
    state = env.batch_state; cfg = state['capacity']; now = env.t
    if cfg['policy']==DEADLINE_POLICY:
        from .deadline_collection import decision as deadline_decision
        return deadline_decision(env,gaps,measurement)
    ready_deadline = min((t + cfg['max_ready_wait_seconds'] for t in state['ready_since'].values()), default=None)
    forecasts = [d for d in state['pending_demands'].values()
                 if d.get('forecast_due_at') is not None and d['ready_since'] is None]
    raw_deadline = min((d['forecast_due_at'] for d in forecasts),default=None)
    not_before = (state['last_planning_at'] + cfg['forecast_min_interval_seconds']
                  if state['last_planning_at'] is not None else state['anchor'])
    forecast_deadline = max(raw_deadline,not_before) if raw_deadline is not None else None
    renewal_deadline = (env.plan['valid_until'] - cfg['planning_lead_seconds']
                        if env.plan['valid_until'] < env.horizon else None)
    if ready_deadline is not None and now >= ready_deadline: reason = 'ready_wait_limit'
    elif renewal_deadline is not None and now >= renewal_deadline: reason = 'plan_renewal'
    elif forecast_deadline is not None and now >= forecast_deadline: reason = 'plan_runway'
    elif measurement['incoming_operation_count'] and measurement['pending_input_tokens'] >= measurement['trigger_tokens']: reason = 'capacity_limit'
    else: reason = None
    return {'reason':reason, 'time':now, 'machines':deepcopy(gaps),
            'ready_since':deepcopy(state['ready_since']), 'ready_deadline':ready_deadline,
            'forecast_deadline':forecast_deadline, 'renewal_deadline':renewal_deadline,
            'forecast_raw_deadline':raw_deadline,'forecast_not_before':not_before,
            'forecast_trigger_machines':[d['machine'] for d in forecasts if d['forecast_due_at']<=now and now>=not_before],
            'capacity':measurement, 'pending_demand_count':len(state['pending_demands'])}


def advance(env, until=None):
    limit = min(env.horizon, env.horizon if until is None else float(until))
    env.last_stop = None
    while True:
        if env.t >= env.horizon:
            if not env.finished:
                env.finished = True
                env._emit('terminal', metrics=env.metrics(), lot_statuses={lid:l['status'] for lid,l in env.lots.items()})
            env.last_stop = {'reason':'terminal', 'time':env.t}
            return env.last_stop
        if not env.plan or env.t >= env.plan['valid_until']:
            env.last_stop = {'reason':'plan_horizon' if env.plan else 'no_plan', 'time':env.t}
            return env.last_stop
        env._outside(); env._run_planned_now()
        if env.last_stop: return env.last_stop
        gaps = env._gaps()
        problem = env.problem(plan_seconds=env.batch_state['plan_seconds'], lookahead_depth=env.batch_state['lookahead_depth'])
        observe_demands(env, problem, gaps)
        measurement = capacity_measurement(env, problem)
        env.batch_state['last_measurement'] = measurement
        check = decision(env, problem, gaps, measurement)
        env._emit('batch_check', policy=env.batch_state['policy'], **{k:v for k,v in check.items() if k != 'time'})
        if check['reason']:
            env.last_stop = check
            return check
        if env.t >= limit:
            env.last_stop = {'reason':'collection_limit', 'time':env.t}
            return env.last_stop
        times = [limit, env.plan['valid_until']]
        times += [check[k] for k in ('ready_deadline','forecast_deadline','renewal_deadline') if check[k] is not None]
        if env.q: times.append(env.q[0][0])  # physics event time; never part of model input
        times.extend(tasks[0]['not_before'] for tasks in env._pending().values() if tasks[0]['not_before'] > env.t)
        times.extend(t for t in env._active_holds().values() if t > env.t)
        target = min(t for t in times if t > env.t)
        env._emit('time_advance', to=target, batching_policy=env.batch_state['policy'],
                  ready_deadline=check['ready_deadline'], deferred_gap_machines=[r['machine'] for r in gaps],
                  unplanned_machine_seconds=len(gaps)*(target-env.t))
        env._events_to(target)
