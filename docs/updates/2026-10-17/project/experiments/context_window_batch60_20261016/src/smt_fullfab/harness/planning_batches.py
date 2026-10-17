"""One planner, two strategies. These functions package evidence, never tasks.

Capacity arrival and unresolved work are separate ledgers: seeing a cohort once
consumes its capacity notification, NOT its production demand or ready deadline.
"""
from copy import deepcopy
import math

from .contracts import digest, require


def revisions(problem, demands):
    wanted = {oid for d in demands for oid in d['operation_ids']}
    # release_time is clamped to observation time by the public exporter. A clock
    # tick alone must not turn all old work into new capacity arrivals.
    return {op['operation_id']: digest({k:v for k,v in op.items() if k != 'release_time'})
            for op in problem['operations'] if op['operation_id'] in wanted}


def strategy(env):
    if env.plan is None or env.plan['valid_until'] <= env.t:
        return 'initial'
    if env._pending() or env._active_holds():
        return 'continuation'
    # Restoring a running factory is not a cold start, even without queued work.
    if any(m.get('currently_busy') for m in env.problem(
            plan_seconds=env.batch_state['plan_seconds'],
            lookahead_depth=env.batch_state['lookahead_depth'])['machines']):
        return 'continuation'
    return 'initial'


def incoming_demands(env, problem):
    state = env.batch_state
    demands = list(state['pending_demands'].values())
    current = revisions(problem, demands)
    incoming = {oid for oid, rev in current.items() if state['capacity_watermark'].get(oid) != rev}
    return [{**d, 'operation_ids':[oid for oid in d['operation_ids'] if oid in incoming]}
            for d in demands if any(oid in incoming for oid in d['operation_ids'])]


def open_batch(env, context):
    """Freeze the offered scope once per observation, with complete dependencies.

    Ready/triggering/nearby demand precedes new records in continuation. Cold
    initial overflow remains disjoint. This orders evidence, never production.
    """
    from .capacity_prompt import PublicPacket, instructions
    from .transport import PROTOCOL_TEXT
    state = env.batch_state
    require(state['active_batch'] is None, 'planning_batch', 'An active batch must be committed before opening another')
    demands = context['batch_demands']
    current = revisions(context['problem'], demands)
    presented = state['presented_revisions']
    seen = [oid for oid, rev in current.items() if presented.get(oid) == rev]
    urgent = {oid for d in demands if d['ready_since'] is not None for oid in d['operation_ids']}
    cfg = state['capacity']
    mode = strategy(env)
    from .forecast_collection import focus_demands
    focus = focus_demands(demands,context.get('trigger') or env.last_stop,env.t,cfg['forecast_lookahead_seconds'],cfg['max_ready_wait_seconds'])
    priorities = {}
    for demand in focus:
        for oid in demand['operation_ids']:
            priorities[oid] = min(priorities.get(oid,(3,0)),(demand['rank'],demand['deadline']))
    fresh = set(current) - set(seen)
    packet_context = {**context,'packet_focus_demands':focus}
    if fresh and mode == 'initial':
        packet_context = {**packet_context, 'batch_demands':[
            {**d, 'operation_ids':[oid for oid in d['operation_ids'] if oid in fresh]}
            for d in demands if any(oid in fresh for oid in d['operation_ids'])]}
    builder = PublicPacket(packet_context, urgent_ids=urgent, deprioritized_ids=seen,
                           priority_by_operation=priorities)
    # Keep shared space for context metadata, later tool feedback and history.
    out = builder.fit({}, prefix=PROTOCOL_TEXT + instructions(cfg),
                      budget=int(cfg['input_token_budget'] * cfg['capacity_trigger_fraction']),
                      reserve=cfg['wrapper_reserve_tokens'])
    indices = [i for group in out['frame']['public_problem']['operation_groups'] for i in group['source_indices']]
    if not indices and builder.bundles:
        # Explicitly addressed oversized unit, never silently discard it.
        indices = builder.bundles[0]
    ids = [context['problem']['operations'][i]['operation_id'] for i in sorted(indices)]
    state['batch_sequence'] += 1
    batch = {'batch_id':f"batch-{state['batch_sequence']}", 'strategy':mode,
             'focus_demands':focus,
             'opened_at':env.t, 'operation_ids':ids, 'cohort_revisions':current,
             'offered_revisions':{oid:current[oid] for oid in ids if oid in current},
             'offered_operation_count':len(ids), 'cohort_operation_count':len(current),
             'not_yet_offered_count':sum(oid not in ids and oid not in seen for oid in current),
             'requires_paged_read':out['oversized_bundle_requires_paged_read'],
             'forecast_observations':{str(d['machine']):{'available_at':d['forecast_available_at'],
                                                       'revision':d['forecast_revision']} for d in demands
                 if d['forecast_available_at'] is not None and any(oid in ids for oid in d['operation_ids'])}}
    if 'forecast_scope' in out['frame']: batch['forecast_scope']=deepcopy(out['frame']['forecast_scope'])
    if 'forecast_notifications' in state:
        batch['notification_merge_seconds']=cfg['forecast_min_interval_seconds']
    state['active_batch'] = deepcopy(batch)
    env._emit('planning_batch_opened', batch_id=batch['batch_id'], strategy=batch['strategy'],
              operation_ids=ids, cohort_revisions=current,
              offered_revisions=batch['offered_revisions'], forecast_observations=batch['forecast_observations'],
              focus_demands=deepcopy(focus),
              **({'notification_merge_seconds':batch['notification_merge_seconds'],
                  'requires_paged_read':batch['requires_paged_read']} if 'notification_merge_seconds' in batch else {}))
    return batch


def coverage(batch, plan):
    assigned = {oid for t in plan['tasks'] for oid in t.get('operation_ids', [])}
    offered = batch['operation_ids']
    return {'batch_id':batch['batch_id'], 'offered_operations':len(offered),
            'assigned_operation_ids':[oid for oid in offered if oid in assigned],
            'unassigned_operation_ids':[oid for oid in offered if oid not in assigned],
            'meaning':'Unassigned work remains pending; a hold is an explicit machine wait, not completed work.'}


def review_receipt(batch, plan, pending, now, interval, model_reviews=None):
    """Advisory metadata only. Invalid annotations cannot mutate/reject tasks."""
    supplied = {}; errors = []
    focus = {row['machine']:row for row in batch.get('focus_demands',[])}
    if model_reviews is not None and not isinstance(model_reviews,list):
        errors.append('machine_reviews must be a list')
    for row in model_reviews if isinstance(model_reviews,list) else []:
        if not isinstance(row,dict) or type(row.get('machine')) is not int or row['machine'] not in focus:
            errors.append('review machine was not in this focus set'); continue
        mid = row['machine']; revisit = row.get('revisit_at')
        if mid in supplied or row.get('disposition') not in ('planned','deferred','insufficient_information') or not isinstance(row.get('reason'),str) or not 0<len(row['reason'])<=2000 or (revisit is not None and (type(revisit) not in (int,float) or not math.isfinite(revisit) or revisit<now)):
            errors.append(f'invalid or duplicate review for {mid}'); continue
        if row['disposition']=='planned' and not pending.get(mid):
            errors.append(f'no pending task supports planned review for {mid}'); continue
        supplied[mid] = deepcopy(row)
    rows = []
    for mid,demand in focus.items():
        total = len(demand['operation_ids']); offered = len(set(demand['operation_ids']) & set(batch['operation_ids']))
        review = supplied.get(mid)
        rows.append({'machine':mid,'information_status':'complete' if offered==total else 'partial' if offered else 'not_offered',
            'offered_candidates':offered,'candidate_count':total,
            'production_status':'planned' if pending.get(mid) else 'unplanned',
            'model_review':review, 'review_status':'explicit' if review else 'unreported',
            'forecast_eligible_again_at':now+interval})
    return {'machine_reviews':rows,'review_errors':errors}


def accept_batch(env, batch, model_reviews=None):
    """Called only in the accepted commit's detached state, never during check."""
    state = env.batch_state
    require(state['active_batch'] == batch, 'planning_batch', 'Stale or mismatched batch receipt')
    receipt = coverage(batch, env.plan)
    receipt['newly_offered_operations'] = sum(state['presented_revisions'].get(oid) != rev
        for oid, rev in batch['offered_revisions'].items())
    state['presented_revisions'].update(batch['offered_revisions'])
    state['last_planning_at'] = env.t
    receipt.update(review_receipt(batch,env.plan,env._pending(),env.t,
                                 state['capacity']['forecast_min_interval_seconds'],model_reviews))
    state['machine_reviews'].update({str(row['machine']):deepcopy(row) for row in receipt['machine_reviews']})
    if 'forecast_notifications' in state:
        from .deadline_collection import delivery_receipts
        receipt['forecast_notifications']=delivery_receipts(batch,env.t,state['forecast_notifications'])
        state['forecast_notifications'].update(deepcopy(receipt['forecast_notifications']))
    # Consume one notification for the known cohort, including its overflow.
    # Overflow remains unoffered and will enter the next due planning batch.
    state['capacity_watermark'].update(batch['cohort_revisions'])
    # The legacy reviewed_forecasts map stays empty in v4. Merely presenting a
    # candidate is not proof that the model reviewed this machine's need.
    state['last_batch_receipt'] = {**receipt, 'time':env.t}
    state['active_batch'] = None
    env._emit('planning_batch_accepted', **receipt,
              cohort_revisions=batch['cohort_revisions'], offered_revisions=batch['offered_revisions'],
              reviewed_forecasts=deepcopy(state['reviewed_forecasts']))
    return receipt
