"""Explicit full-fab development dispatching references; never an A/B/C fallback.

HP -> setup -> CR follows the declared official ranking order. The pinned Python
upstream instead uses setup -> HP -> CR and a separate batch-fill precedence.
This implementation is a candidate for calibration, NOT an exact AutoSched replay.
Only currently observable queues, legal eligibility and route expectations are read.
"""
from __future__ import annotations
from collections import defaultdict

VERSION = 'reference-hp-setup-v1'


def _mean(distribution):
    if hasattr(distribution, 'c'):
        return distribution.c
    if hasattr(distribution, 'm'):
        return distribution.m
    if hasattr(distribution, 'p'):
        return distribution.p
    raise TypeError(type(distribution))


def _eligible_without_cache_mutation(env, mid):
    machine=env.machines[mid]
    state=env.machine_state[mid]
    if max(state['ready'],state['down_until']) > env.t:
        return []
    if len(env.processing_by_machine.get(mid,())) >= (2 if machine.cascading else 1):
        return []
    result=[]
    for lid in sorted(env.waiting.get(machine.family,())):
        lot=env.lots[lid]
        step=env._step(lot)
        bound=lot['dedications'].get(str(step.order))
        if bound is not None and bound != mid:
            continue
        if state['min_left'] > 0 and state['min_setup'] != step.setup_needed:
            continue
        result.append(lid)
    return result


def reference_action(env, policy='cr'):
    """Return an explicit legal immediate action and provenance, without mutation.

    All production machines are considered. No implicit dispatch occurs. Independent
    reference runs may convert this immediate action to a one-step plan. This is
    NOT a rolling optimizer; CR uses expected remaining processing only (not
    transport, setup or rework forecasts), as pinned upstream Lot.cr does.
    """
    if policy not in {'cr', 'fifo', 'edd'}:
        raise ValueError('reference policy must be cr, fifo or edd')
    route_remaining = {}
    for name, route in env.routes.items():
        suffix = [0.] * (len(route.steps) + 1)
        for i in range(len(route.steps)-1, -1, -1):
            suffix[i] = suffix[i+1] + _mean(route.steps[i].processing_time)
        route_remaining[name] = suffix
    def lot_key(lid):
        lot = env.lots[lid]
        if policy == 'cr':
            remaining = route_remaining[lot['route']][lot['step']]
            value = (lot['due']-env.t)/remaining if remaining > 0 else 1.
        elif policy == 'fifo':
            value = lot['ready_since']
        else:
            value = lot['due']
        return (-lot['priority'], value, lot['due'], lid)
    families = defaultdict(list)
    eligible = {}
    for mid in sorted(env.physical):
        ids = _eligible_without_cache_mutation(env, mid)
        if ids:
            families[env.machines[mid].family].append(mid)
            eligible[mid] = ids
    selected = set()
    dispatches = []
    opportunities = 0
    candidates = 0
    for family in sorted(families):
        remaining_machines = set(families[family])
        while remaining_machines:
            proposals = []
            for mid in sorted(remaining_machines):
                groups = defaultdict(list)
                for lid in eligible[mid]:
                    if lid not in selected:
                        lot=env.lots[lid]
                        step=env._step(lot)
                        groups[(lot['part'],step.order,step.step_name)].append(lid)
                for group in groups.values():
                    step=env._step(env.lots[group[0]])
                    if len(group) < step.batch_min:
                        continue
                    group.sort(key=lot_key)
                    head=lot_key(group[0])
                    setup=env._setup(mid,step)
                    # Explicit Demand batching: take the ranked feasible members
                    # up to maximum; wait only if minimum cannot be met.
                    batch=group[:step.batch_max]
                    key=(head[0],setup,*head[1:],-len(batch),mid)
                    proposals.append((key,mid,batch))
            if not proposals:
                break
            candidates += len(proposals)
            opportunities += len(proposals) > 1
            _,mid,batch=min(proposals)
            selected.update(batch)
            remaining_machines.remove(mid)
            dispatches.append({'machine':mid,'lot_ids':batch})
    return {'action':{'dispatches':dispatches,'wait_seconds':0 if dispatches else 60},
            'provenance':{'version':VERSION,'policy':policy,
                'official_calibrated':False,'scope':'all_production_machines',
                'production_machines_considered':len(env.physical),
                'machines_with_eligible_lots':len(eligible),
                'proposal_evaluations':candidates,'multiple_proposal_selections':opportunities,
                'ranking':'higher_priority, least_setup, '+policy+', due, lot_id, fill, machine_id',
                'batch_policy':'same_part_and_step_demand_min_max',
                'limitations':['immediate_dispatch_not_rolling_optimization',
                    'AutoSched_tie_breaking_and_batch_selection_not_validated',
                    'no_superhot_reservations_required_by_locked_periodic_HOTLOT_no_input',
                    'CQT_not_enforced_in_adapter_v2',
                    'initial_historical_bindings_unknown']}}
