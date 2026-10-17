"""Deadline-aware notification delivery. No production task or hold is generated."""
from copy import deepcopy
from .contracts import digest


def forecast_metadata(demand, operations, arrivals, lead):
    supported = sorted(o['operation_id'] for o in operations if o['operation_id'] in arrivals)
    available, arrival = demand['forecast_available_at'], demand['supported_arrival_at']
    need = max(available,arrival) if available is not None and arrival is not None else None
    return {'forecast_need_at':need, 'forecast_latest_start':need-lead if need is not None else None,
            'forecast_notice_key':digest({'machine':demand['machine'], 'episode':demand['forecast_revision'],
                                         'supported_operations':supported}) if need is not None else None}


def forecast_notice(demand, state):
    hard = demand.get('forecast_latest_start')
    if hard is None or demand['ready_since'] is not None: return None
    interval = state['capacity']['forecast_min_interval_seconds']
    previous = state.get('forecast_notifications',{}).get(str(demand['machine']))
    same = previous is not None and previous['notice_key']==demand['forecast_notice_key']
    # A newly earlier deadline overrides an old delivery; clock drift later does not.
    if same and previous['stage']=='deadline' and hard >= previous['latest_start']: return None
    last = state['last_planning_at']
    normal = max(hard-interval, last+interval if last is not None else state['anchor'])
    due = hard if same and previous['stage']=='early' else min(normal,hard)
    return {'machine':demand['machine'],'notice_key':demand['forecast_notice_key'],
            'need_at':demand['forecast_need_at'],'latest_start':hard,'normal_collection_at':normal,'due_at':due}


def decision(env, gaps, measurement):
    state=env.batch_state;cfg=state['capacity'];now=env.t
    notices=[n for d in state['pending_demands'].values() if (n:=forecast_notice(d,state)) is not None]
    deadline=min((n['due_at'] for n in notices),default=None)
    renewal=env.plan['valid_until']-cfg['planning_lead_seconds'] if env.plan['valid_until']<env.horizon else None
    ready=min(state['ready_since'].values(),default=None)
    if gaps:reason='uncovered_demand'
    elif renewal is not None and now>=renewal:reason='plan_renewal'
    elif deadline is not None and now>=deadline:reason='plan_runway'
    elif measurement['incoming_operation_count'] and measurement['pending_input_tokens']>=measurement['trigger_tokens']:reason='capacity_limit'
    else:reason=None
    return {'reason':reason,'time':now,'machines':deepcopy(gaps),'ready_since':deepcopy(state['ready_since']),
            'ready_deadline':ready,'renewal_deadline':renewal,'forecast_deadline':deadline,
            'forecast_trigger_machines':[n['machine'] for n in notices if n['due_at']<=now],
            'forecast_notifications':notices,'capacity':measurement,'pending_demand_count':len(state['pending_demands'])}


def delivery_receipts(batch, now, previous=None):
    """Receipt means notification delivered, never model review or task coverage."""
    # A paging address alone must not suppress the machine's reminder.
    if batch.get('requires_paged_read'):return {}
    offered=set(batch['operation_ids']);result={};previous=previous or {}
    focused=[r for r in batch.get('focus_demands',[]) if r.get('forecast_notice_key') is not None
             and offered.intersection(r['operation_ids'])]
    # At a deadline round, also deliver nearby deadlines early. Otherwise two
    # machines with deadlines seconds apart would immediately split again.
    through=now+(batch.get('notification_merge_seconds',0) if any(r['forecast_latest_start']<=now for r in focused) else 0)
    for row in focused:
        hard=row['forecast_latest_start']
        old=previous.get(str(row['machine']))
        already_final=old is not None and old['notice_key']==row['forecast_notice_key'] and old['stage']=='deadline' and hard>=old['latest_start']
        result[str(row['machine'])]={'notice_key':row['forecast_notice_key'],'latest_start':hard,
            'stage':'deadline' if through>=hard or already_final else 'early','delivered_at':now,
            'meaning':'notification delivered with accepted plan; review and production remain separate'}
    return result


def forecast_scope(focus):
    """Describe actual packet capacity, including a boundary tie that is partial."""
    forecasts=[r for r in focus if r.get('forecast_latest_start') is not None]
    by_time={}
    for row in forecasts:by_time.setdefault(row['forecast_latest_start'],[]).append(row)
    through=None;blocked=None
    for deadline,rows in sorted(by_time.items()):
        if any(r['information_status']!='complete' for r in rows):blocked=deadline;break
        through=deadline
    return {'mode':'input_budget_adaptive','fully_included_deadline_through':through,
            'first_incomplete_deadline':blocked,'known_forecast_machines':len(forecasts),
            'complete':sum(r['information_status']=='complete' for r in forecasts),
            'partial':sum(r['information_status']=='partial' for r in forecasts),
            'not_offered':sum(r['information_status']=='not_offered' for r in forecasts),
            'meaning':'evidence coverage only, not a production commitment or guaranteed arrival'}
