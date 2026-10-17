"""Read-only time semantics and collecting validation of full production plans.

Defaults are interpreted, never inserted into production JSON. Validation is
pure and deterministic. A malformed parent prevents only its dependent checks.
Invalidation receipts must come from the host, never from the model delta.
"""
from copy import deepcopy
import math


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def normalize_plan(plan):
    """Detached, idempotent identity: no clamping, inferred tasks or defaults."""
    return deepcopy(plan)


def start_mode(task):
    return task.get('start_mode', 'when_ready')


def lower_bound_satisfied(task, now):
    return 'not_before' not in task or now >= task['not_before']


def active_holds(holds, *, machine, now, pending_tasks, dispatched_task_ids=()):
    """F15: a conditional hold applies only after its anchor and an empty queue."""
    return [deepcopy(h) for h in holds if h['machine'] == machine and h['until'] > now
            and (h.get('after_task_id') is None or
                 (h['after_task_id'] in dispatched_task_ids and not pending_tasks))]


def validate_plan(plan, problem, execution_state, *, base_plan=None):
    """Return every independently evaluable violation, in source/check order.

    This validates public identity/qualification/batch/time/freeze constraints;
    private physical min-run/setup constraints remain the adapter's responsibility.
    """
    from .plan_delta import _observed_operations, DeltaError, json_sha256
    errors = []
    def check(ok, code, detail):
        if not ok:
            errors.append({'code': code, 'detail': detail})
        return ok
    if not check(isinstance(plan, dict), 'schema', 'plan must be an object'):
        return errors
    now = execution_state['time']
    end = plan.get('valid_until')
    check(number(plan.get('created_at')) and plan['created_at'] == now, 'header', 'invalid explicit creation time')
    check(number(end) and now < end <= execution_state['observation_end']
          and end <= problem['horizon_end'], 'header', 'invalid explicit plan window')
    check(number(plan.get('freeze_until')) and number(end)
          and now <= plan['freeze_until'] <= end, 'header', 'invalid freeze window')
    machines = problem.get('machines', [])
    if not check(isinstance(machines, list) and all(isinstance(m, dict) and type(m.get('machine')) is int
                 and type(m.get('family')) is str and m['family'] for m in machines), 'schema', 'observed machines'):
        machines = []
    machine_by_id = {m['machine']: m for m in machines}
    check(len(machine_by_id) == len(machines), 'schema', 'duplicate observed machines')
    scope = plan.get('scope')
    expected_scope = problem.get('scope')
    from .plan_delta import _machine_ids
    check(_machine_ids(scope) and _machine_ids(expected_scope)
          and set(scope) == set(expected_scope) == set(machine_by_id)
          and (base_plan is None or (_machine_ids(base_plan.get('scope')) and set(scope) == set(base_plan['scope']))),
          'scope', 'full current/base responsibility must match with exact integer identities')
    operations = problem.get('operations')
    ops = {}
    identities = set()
    if check(isinstance(operations, list), 'schema', 'observed operations must be a list'):
        for op in operations:
            try:
                found = _observed_operations([op], machine_by_id)
            except DeltaError as exc:
                errors.append({'code': exc.code, 'detail': exc.detail})
                continue
            oid = op['operation_id']; identity = (op['lot_id'], op['step'], op['visit'])
            check(oid not in ops, 'schema', 'duplicate observed operation IDs')
            check(identity not in identities, 'observed_identity', 'duplicate observed lot/step/visit identity')
            ops.update(found); identities.add(identity)
    tasks = plan.get('tasks')
    if not check(isinstance(tasks, list), 'schema', 'tasks must be a list'):
        tasks = []
    valid_tasks = []
    ids = set()
    for task in tasks:
        if not check(isinstance(task, dict), 'schema', 'task must be an object'):
            continue
        tid = task.get('id')
        if not check(type(tid) is str and bool(tid), 'ids', 'task ID'):
            continue
        check(tid not in ids, 'duplicate_ids', 'task ID: ' + tid); ids.add(tid)
        valid_tasks.append(task)
    by_id = {t['id']: t for t in valid_tasks}
    dispatched = set(execution_state.get('dispatched_task_ids', []))
    invalidated = set(execution_state.get('invalidated_task_ids', []))
    base_tasks = (base_plan or {}).get('tasks', [])
    # Only explicit cancellation is exempt; invalidation does not permit rewriting.
    cancelled_invalid = invalidated - set(by_id)
    frozen = [t for t in base_tasks if t['id'] not in dispatched | cancelled_invalid
              and now < base_plan['freeze_until']
              and t.get('not_before', base_plan['created_at']) < base_plan['freeze_until']]
    if frozen:
        check(number(plan.get('freeze_until')) and plan['freeze_until'] >= base_plan['freeze_until'],
              'frozen_horizon', 'pending frozen tasks forbid shortening the original freeze_until')
    for old in frozen:
        check(old['id'] in by_id and json_sha256(old) == json_sha256(by_id[old['id']]),
              'frozen_task', 'frozen task must survive byte-equivalent JSON values')
    frozen_ids = {t['id'] for t in frozen}
    for mid in machine_by_id:
        before = [t for t in base_tasks if t['machine'] == mid and t['id'] not in dispatched | cancelled_invalid]
        last = max((i for i,t in enumerate(before) if t['id'] in frozen_ids), default=-1)
        if last >= 0:
            after = [t for t in valid_tasks if t.get('machine') == mid]
            check(json_sha256(after[:last+1]) == json_sha256(before[:last+1]), 'frozen_prefix',
                  'exact pending machine prefix through the last frozen task must survive')
    seen_ops = {oid for t in base_tasks if t['id'] in dispatched for oid in t['operation_ids']}
    seen_visits = {(lid,s,v) for t in base_tasks if t['id'] in dispatched
                   for lid,s,v in zip(t['lot_ids'],t['steps'],t['visits'])}
    for task in valid_tasks:
        tid = task['id']; mid = task.get('machine')
        known_machine = type(mid) is int and mid in machine_by_id
        check(known_machine, 'machine', 'task machine outside declared physical scope: ' + tid)
        check(start_mode(task) in ('when_ready', 'not_before'), 'start_mode', 'invalid start_mode: ' + tid)
        if 'not_before' in task:
            check(number(task['not_before']) and number(end) and task['not_before'] < end,
                  'start', 'invalid unchanged start: ' + tid)
        # The hard lower bound is optional in either mode, including legacy mode.
        arrays = [task.get(k) for k in ('operation_ids','lot_ids','steps','visits')]
        if not check(all(isinstance(a,list) for a in arrays), 'schema', 'full task identity arrays: ' + tid):
            continue
        oids,lids,steps,visits = arrays
        oid_valid = all(type(o) is str and o for o in oids)
        check(oid_valid, 'ids', 'operation IDs for ' + tid)
        if oid_valid:
            check(len(oids)==len(set(oids)), 'duplicate_ids', 'operation IDs for ' + tid)
        identity_valid = (bool(oids) and all(len(a)==len(oids) for a in arrays)
                          and all(type(l) is str and l for l in lids) and len(set(lids))==len(lids)
                          and all(type(v) is int and v>=1 for v in steps+visits))
        if not check(identity_valid, 'task_identity', tid) or not oid_valid:
            continue
        chosen=[]
        for oid,lid,step,visit in zip(*arrays):
            identity=(lid,step,visit)
            check(oid not in seen_ops and identity not in seen_visits, 'operation_reuse', oid)
            seen_ops.add(oid);seen_visits.add(identity)
            if not check(oid in ops, 'unknown_operation', 'retained/new operation not in current observation: ' + oid):
                continue
            op=ops[oid];chosen.append(op)
            check((op['lot_id'],op['step'],op['visit'])==identity, 'task_identity', 'operation identity: '+oid)
            check(known_machine and mid in op['eligible_machines'] and op['family']==machine_by_id[mid]['family'],
                  'eligibility', oid)
        if chosen:
            first=chosen[0]
            check(all(o['batch_key']==first['batch_key'] and o['batch_min']==first['batch_min']
                      and o['batch_max']==first['batch_max'] for o in chosen)
                  and first['batch_min']<=len(oids)<=first['batch_max'], 'batch', 'explicit batch incompatible/min/max: '+tid)
    holds=plan.get('holds', [])
    if not check(isinstance(holds,list), 'schema', 'holds must be a list'):
        holds=[]
    hold_keys=set()
    for hold in holds:
        if not check(isinstance(hold,dict) and {'machine','until','reason'}<=set(hold), 'hold', 'complete explicit hold required'):
            continue
        mid=hold['machine'];after=hold.get('after_task_id');until=hold['until']
        check(type(mid) is int and mid in machine_by_id and number(until) and number(end) and until<=end
              and type(hold['reason']) is str and bool(hold['reason']), 'hold', 'invalid hold')
        # An expired hold has no effect, even if its anchor has left the plan.
        check((number(until) and until<=now) or after is None or
              (type(after) is str and after in by_id and by_id[after].get('machine')==mid),
              'hold_anchor', 'no automatic migration from an executed/deleted/other-machine task')
        if type(mid) is int and (after is None or type(after) is str):
            check((mid,after) not in hold_keys, 'hold', 'duplicate explicit hold key');hold_keys.add((mid,after))
    return errors
