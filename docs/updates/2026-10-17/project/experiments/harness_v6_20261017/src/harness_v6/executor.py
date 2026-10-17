"""Pure queue-head decision; the host alone performs actual dispatch."""
from copy import deepcopy
from .normalize import active_holds, lower_bound_satisfied, start_mode, number


def decide_start(queue, machine_state, lot_readiness, *, now, holds=(), dispatched_task_ids=()):
    """Return {task, reason}; never search for a better or later startable task.

    queue: this machine's ordered pending task objects (no dispatched tasks).
    machine_state: machine, ready, down_until; optional available (default True).
    lot_readiness: operation ID -> public operation identity/qualification/batch
    fields plus ready: bool. The adapter determines readiness from lot status,
    current step/visit and transport; absent rows are not ready. An optional
    legal=False on machine_state blocks dispatch for private setup/min-run rules.
    Invalidated IDs are host receipts and block the whole queue, including tails.
    No input is changed and the returned task retains exactly the model fields.
    """
    def result(reason, task=None):
        return {'task': deepcopy(task), 'reason': reason}
    mid=machine_state['machine']
    if any(t.get('machine') != mid or type(t.get('machine')) is not int for t in queue):
        return result('invalid_queue')
    if any(t['id'] in machine_state.get('invalidated_task_ids', ()) for t in queue):
        return result('plan_invalidated')
    if active_holds(holds, machine=mid, now=now, pending_tasks=queue, dispatched_task_ids=dispatched_task_ids):
        return result('hold')
    if not queue:
        return result('empty_queue')
    task=queue[0]
    if start_mode(task) not in ('when_ready','not_before'):
        return result('invalid_task')
    if 'not_before' in task and not number(task['not_before']):
        return result('invalid_task')
    if not lower_bound_satisfied(task, now):
        return result('not_before')
    if task.get('latest_start') is not None:
        if not number(task['latest_start']):
            return result('invalid_task')
        if now > task['latest_start']:
            return result('expired_task')
    if not machine_state.get('available',True) or max(machine_state['ready'],machine_state['down_until']) > now:
        return result('machine_unavailable')
    arrays=[task.get(k) for k in ('operation_ids','lot_ids','steps','visits')]
    if not all(isinstance(a,list) and a for a in arrays) or len({len(a) for a in arrays}) != 1:
        return result('invalid_task')
    oids,lids,steps,visits=arrays
    if (not all(type(v) is str and v for v in oids+lids)
            or len(set(oids))!=len(oids) or len(set(lids))!=len(lids)
            or not all(type(v) is int and v>=1 for v in steps+visits)):
        return result('invalid_task')
    chosen=[]
    for oid,lid,step,visit in zip(*arrays):
        row=lot_readiness.get(oid)
        if row is None or row.get('ready') is not True:
            return result('material_unready')
        if (row.get('lot_id'),row.get('step'),row.get('visit')) != (lid,step,visit):
            return result('plan_invalidated')
        if mid not in row.get('eligible_machines', ()):
            return result('plan_invalidated')
        chosen.append(row)
    first=chosen[0]
    bounds=(first.get('batch_min'),first.get('batch_max'))
    if (not all(type(n) is int for n in bounds) or not 1<=bounds[0]<=len(chosen)<=bounds[1]
            or not isinstance(first.get('batch_key'),list)
            or not all((r.get('batch_key'),r.get('batch_min'),r.get('batch_max')) ==
                       (first['batch_key'],*bounds) for r in chosen)):
        return result('invalid_batch')
    if machine_state.get('legal',True) is not True:
        return result('plan_invalidated')
    return result('start',task)
