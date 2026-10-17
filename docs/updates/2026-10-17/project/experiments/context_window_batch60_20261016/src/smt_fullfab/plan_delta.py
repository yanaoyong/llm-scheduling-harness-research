"""Pure explicit plan-delta compiler; no scheduling, execution or auto repair.

Inputs must be the caller's authoritative base plan/current public observation
and dispatch state. A successful compile is not a physics or model-provenance
certificate. The caller still binds the real model call and explicit commit,
then uses the common validator/executor and independent audit.
"""
from copy import deepcopy
import hashlib
import json
import math

SCHEMA = 'smt-fullfab-explicit-plan-delta-v1'
STATE_SCHEMA = 'smt-fullfab-plan-delta-state-v1'
ORDER_POLICY = 'preserve_base_machine_order_unless_explicit'


class DeltaError(ValueError):
    """Deterministic rejection with a machine-readable diagnostic code."""
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(code + ': ' + detail)


def json_sha256(value):
    # Same canonical JSON spelling as environment.digest, with NaN rejected.
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _require(condition, code, detail):
    if not condition:raise DeltaError(code, detail)


def _keys(value, expected, label):
    _require(isinstance(value, dict) and set(value) == set(expected), 'schema', label)


def _ids(value, label):
    _require(isinstance(value, list) and all(type(v) is str and v for v in value), 'ids', label)
    _require(len(value) == len(set(value)), 'duplicate_ids', label)
    return list(value)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _sha(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _machine_ids(value):
    return (isinstance(value, list) and all(type(mid) is int for mid in value)
            and len(value) == len(set(value)))


def _observed_operations(operations, machine_by_id):
    """Check public identity/qualification types before Python equality aliases."""
    required = {'operation_id', 'lot_id', 'step', 'visit', 'family',
                'eligible_machines', 'batch_key', 'batch_min', 'batch_max'}
    _require(isinstance(operations, list) and all(isinstance(o, dict) and required <= set(o) for o in operations),
             'schema', 'complete observed operation identity/qualification required')
    for op in operations:
        _require(all(type(op[key]) is str and op[key] for key in ('operation_id', 'lot_id', 'family'))
                 and all(type(op[key]) is int and op[key] >= 1 for key in ('step', 'visit')),
                 'observed_identity', 'operation IDs/family must be nonempty strings; step/visit must be positive exact integers')
        eligible = op['eligible_machines']
        _require(_machine_ids(eligible) and eligible and set(eligible) <= set(machine_by_id)
                 and all(machine_by_id[mid]['family'] == op['family'] for mid in eligible),
                 'observed_eligibility', 'eligible machines must be unique exact integers in the observed family/scope')
        key = op['batch_key']
        _require(isinstance(key, list) and len(key) == 3 and type(key[0]) is str and type(key[2]) is str
                 and type(key[1]) is int and key[1] == op['step']
                 and type(op['batch_min']) is int and type(op['batch_max']) is int
                 and 1 <= op['batch_min'] <= op['batch_max'],
                 'observed_batch', 'batch key must be [part, exact step, name]; bounds must be positive exact integers')
    ops = {o['operation_id']: o for o in operations}
    _require(len(ops) == len(operations), 'schema', 'duplicate observed operation IDs')
    _require(len({(o['lot_id'], o['step'], o['visit']) for o in operations}) == len(operations),
             'observed_identity', 'duplicate observed lot/step/visit identity')
    return ops


def anchor_hashes(base_plan, problem, execution_state, *, source_sha256):
    """Public deterministic hash helper, without choosing or retaining tasks."""
    _require(_sha(source_sha256), 'source_hash', 'expected lowercase source SHA256')
    return {'base_plan_sha256': json_sha256(base_plan), 'problem_sha256': json_sha256(problem),
            'state_sha256': json_sha256(execution_state), 'source_sha256': source_sha256}


def _partition(universe, patch, *, all_mode, replacement_key, label):
    _keys(patch, ('keep', 'cancel_ids', 'replace', 'add'), label)
    _keys(patch['keep'], ('mode', 'ids'), label + '.keep')
    selected = _ids(patch['keep']['ids'], label + '.keep.ids')
    cancelled = _ids(patch['cancel_ids'], label + '.cancel_ids')
    _require(isinstance(patch['replace'], list) and isinstance(patch['add'], list), 'schema', label + ' arrays')
    if replacement_key == 'id':
        _require(all(isinstance(t, dict) and 'id' in t for t in patch['replace']), 'schema', 'replacement task')
        replaced = _ids([t['id'] for t in patch['replace']], label + '.replace ids')
    else:
        for item in patch['replace']:_keys(item, ('ref', 'hold'), 'replacement hold')
        replaced = _ids([t['ref'] for t in patch['replace']], label + '.replace refs')
    domain = set(universe)
    _require(not (set(cancelled) & set(replaced)), 'partition', label + ' cancel and replace overlap')
    _require(set(selected + cancelled + replaced) <= domain, 'unknown_or_dispatched_id', label)
    mode = patch['keep']['mode']
    if mode == 'ids':
        retained = set(selected)
    elif mode == all_mode:
        _require(set(selected) == set(cancelled + replaced), 'partition', label + ' exceptions must exactly name cancellation/replacement')
        retained = domain - set(selected)
    else:raise DeltaError('schema', label + ' retention mode')
    _require(not retained.intersection(cancelled + replaced) and retained | set(cancelled + replaced) == domain,
             'partition', label + ' every base item needs exactly one explicit disposition')
    return retained, cancelled, replaced


def compile_plan_delta(base_plan, problem, execution_state, delta, *, source_sha256):
    """Compile declared keeps/cancels/replacements/additions into one full plan.

    No input is mutated. Task array order within each machine is authoritative;
    no sorting by machine/ID/priority is performed. Existing global interleaving
    is retained where possible and has no cross-machine scheduling semantics.
    """
    anchors = anchor_hashes(base_plan, problem, execution_state, source_sha256=source_sha256)
    _keys(delta, ('schema', 'anchors', 'plan_header', 'order_policy', 'tasks', 'holds', 'machine_orders'), 'delta')
    _require(delta['schema'] == SCHEMA and delta['order_policy'] == ORDER_POLICY, 'schema', 'delta version/order policy')
    _keys(delta['anchors'], anchors, 'anchors')
    _require(all(delta['anchors'][k] == v for k, v in anchors.items()), 'stale_anchor', 'base/problem/state/source hash mismatch')
    _keys(execution_state, ('schema', 'time', 'observation_end', 'base_plan_version', 'dispatched_task_ids'), 'execution_state')
    now, observation_end = execution_state['time'], execution_state['observation_end']
    _require(execution_state['schema'] == STATE_SCHEMA and _number(now) and _number(observation_end)
             and 0 <= now < observation_end, 'state', 'invalid current time/window')
    _require(_number(problem.get('time')) and problem['time'] == now and _number(problem.get('horizon_end'))
             and problem['horizon_end'] > now, 'stale_observation', 'problem time/window differs from current state')
    _require(type(base_plan.get('version')) is str and base_plan['version'] == execution_state['base_plan_version']
             and _number(base_plan.get('created_at')) and base_plan['created_at'] <= now
             and _number(base_plan.get('freeze_until')), 'base_state', 'base version/time differs from state')
    base_tasks = base_plan.get('tasks')
    _require(isinstance(base_tasks, list) and all(isinstance(t, dict) and 'id' in t for t in base_tasks), 'schema', 'base tasks')
    base_ids = _ids([t['id'] for t in base_tasks], 'base task IDs')
    _require(all(type(t.get('machine')) is int and _number(t.get('not_before')) for t in base_tasks),
             'base_state', 'base machine/start identities must be explicit and correctly typed')
    by_id = {t['id']: t for t in base_tasks}
    dispatched = _ids(execution_state['dispatched_task_ids'], 'dispatched task IDs')
    _require(set(dispatched) <= set(base_ids), 'base_state', 'dispatch receipt does not belong to the base plan')
    pending = [tid for tid in base_ids if tid not in set(dispatched)]
    retained, cancelled, replaced = _partition(pending, delta['tasks'], all_mode='all_pending_except', replacement_key='id', label='tasks')
    replacements = {t['id']: t for t in delta['tasks']['replace']}
    added = delta['tasks']['add']
    _require(all(isinstance(t, dict) and 'id' in t for t in added), 'schema', 'added task')
    added_ids = _ids([t['id'] for t in added], 'added task IDs')
    _require(not set(added_ids).intersection(base_ids), 'reused_id', 'new task reuses any base task ID')
    tasks = [deepcopy(by_id[tid] if tid in retained else replacements[tid]) for tid in pending if tid in retained or tid in replacements]
    tasks += deepcopy(added)
    required_task_fields = {'id', 'machine', 'lot_ids', 'steps', 'visits', 'operation_ids', 'not_before'}
    _require(all(required_task_fields <= set(t) for t in tasks), 'schema', 'full task fields required; none are inferred')
    _require(all(type(t['machine']) is int for t in tasks), 'machine', 'machine identity must remain an integer')
    orders = delta['machine_orders']
    _require(isinstance(orders, list), 'schema', 'machine_orders')
    explicit = {}
    for order in orders:
        _keys(order, ('machine', 'task_ids'), 'machine order')
        mid = order['machine']
        _require(type(mid) is int and mid not in explicit, 'machine_order', 'invalid/duplicate machine order')
        values = _ids(order['task_ids'], 'machine order IDs')
        expected = [t['id'] for t in tasks if t['machine'] == mid]
        _require(set(values) == set(expected), 'machine_order', 'machine order must list exactly its resulting task IDs')
        explicit[mid] = values
    changed_machines = {t['machine'] for t in added}
    for tid in replaced:
        if by_id[tid]['machine'] != replacements[tid]['machine']:
            changed_machines.update((by_id[tid]['machine'], replacements[tid]['machine']))
    _require(changed_machines <= set(explicit), 'missing_machine_order', 'additions/moves need explicit full affected-machine order')
    compiled_by_id = {t['id']: t for t in tasks}
    positions = {mid: iter(ids) for mid, ids in explicit.items()}
    tasks = [deepcopy(compiled_by_id[next(positions[t['machine']])]) if t['machine'] in positions else t for t in tasks]
    header = delta['plan_header']
    _keys(header, ('version', 'created_at', 'valid_until', 'freeze_until', 'reason', 'scope'), 'plan_header')
    _require(type(header['version']) is str and header['version'] and header['version'] != base_plan['version']
             and header['created_at'] == now and type(header['reason']) is str and bool(header['reason']), 'header', 'new explicit version/time/reason required')
    _require(_number(header['created_at']) and _number(header['valid_until']) and _number(header['freeze_until'])
             and now <= header['freeze_until'] <= header['valid_until'] <= observation_end
             and now < header['valid_until'] <= problem['horizon_end'], 'header', 'invalid explicit plan/freeze window')
    machine_rows = problem.get('machines', [])
    _require(isinstance(machine_rows, list) and all(isinstance(m, dict) and type(m.get('machine')) is int
             and type(m.get('family')) is str and m['family'] for m in machine_rows), 'schema', 'observed machines')
    mids = [m['machine'] for m in machine_rows]
    _require(len(mids) == len(set(mids)), 'schema', 'duplicate observed machines')
    scope = header['scope']
    _require(_machine_ids(scope) and _machine_ids(problem.get('scope')) and _machine_ids(base_plan.get('scope'))
             and set(scope) == set(mids) == set(problem['scope']) == set(base_plan['scope']), 'scope', 'full current/base responsibility must match with exact integer identities')
    _require(set(explicit) <= set(scope), 'machine_order', 'unknown explicit-order machine')
    machine_by_id = {m['machine']: m for m in machine_rows}
    ops = _observed_operations(problem.get('operations'), machine_by_id)
    frozen = [t for t in base_tasks if t['id'] in pending and now < base_plan['freeze_until'] and t['not_before'] < base_plan['freeze_until']]
    _require(not frozen or header['freeze_until'] >= base_plan['freeze_until'],
             'frozen_horizon', 'pending frozen tasks forbid shortening the original freeze_until; no automatic max is applied')
    for old in frozen:
        _require(old['id'] in compiled_by_id and json_sha256(old) == json_sha256(compiled_by_id[old['id']]), 'frozen_task', 'frozen task must survive byte-equivalent JSON values')
    frozen_ids = {t['id'] for t in frozen}
    frozen_prefixes = []
    for mid in mids:
        before = [t for t in base_tasks if t['machine'] == mid and t['id'] in pending]
        last_frozen = max((i for i, t in enumerate(before) if t['id'] in frozen_ids), default=-1)
        prefix = before[:last_frozen + 1]
        if not prefix:
            continue
        after = [t for t in tasks if t['machine'] == mid]
        _require(json_sha256(after[:len(prefix)]) == json_sha256(prefix), 'frozen_prefix',
                 'exact pending machine prefix through the last frozen task must survive; no insertion, deletion, migration or reordering')
        frozen_prefixes.append({'machine': mid, 'task_ids': [t['id'] for t in prefix], 'tasks_sha256': json_sha256(prefix)})
    executed_ops = {oid for tid in dispatched for oid in by_id[tid].get('operation_ids', [])}
    executed_tuples = {(lid, step, visit) for tid in dispatched for lid, step, visit in
                       zip(by_id[tid]['lot_ids'], by_id[tid]['steps'], by_id[tid]['visits'])}
    seen_ops, seen_visits = set(), set()
    for task in tasks:
        tid, mid = task['id'], task['machine']
        _require(mid in machine_by_id, 'machine', 'task machine outside declared physical scope: ' + tid)
        oid_list = _ids(task['operation_ids'], 'operation IDs for ' + tid)
        arrays = [task[k] for k in ('lot_ids', 'steps', 'visits')]
        _require(oid_list and all(isinstance(v, list) and len(v) == len(oid_list) for v in arrays)
                 and all(type(v) is str and v for v in arrays[0]) and len(set(arrays[0])) == len(arrays[0])
                 and all(type(v) is int and v >= 1 for v in arrays[1] + arrays[2]), 'task_identity', tid)
        _require(_number(task['not_before']) and task['not_before'] < header['valid_until'], 'start', 'invalid unchanged start: ' + tid)
        is_frozen = any(json_sha256(task) == json_sha256(t) for t in frozen)
        _require(task['not_before'] >= now or is_frozen, 'past_start', 'explicit replacement required; no automatic max(now,start): ' + tid)
        chosen = []
        for oid, lid, step, visit in zip(oid_list, *arrays):
            _require(oid in ops, 'unknown_operation', 'retained/new operation not in current observation: ' + oid)
            op = ops[oid];identity = (lid, step, visit)
            _require(oid not in seen_ops | executed_ops and identity not in seen_visits | executed_tuples, 'operation_reuse', oid)
            _require((op['lot_id'], op['step'], op['visit']) == identity, 'task_identity', 'operation identity is never parsed or rewritten: ' + oid)
            _require(mid in op['eligible_machines'] and op['family'] == machine_by_id[mid]['family'], 'eligibility', oid)
            seen_ops.add(oid);seen_visits.add(identity);chosen.append(op)
        first = chosen[0]
        _require(all(o['batch_key'] == first['batch_key'] and o['batch_min'] == first['batch_min'] and o['batch_max'] == first['batch_max'] for o in chosen)
                 and first['batch_min'] <= len(chosen) <= first['batch_max'], 'batch', 'explicit batch incompatible/min/max: ' + tid)
    base_holds = base_plan.get('holds', [])
    _require(isinstance(base_holds, list) and all(isinstance(h, dict) for h in base_holds), 'schema', 'base holds')
    refs = ['h:' + str(i) for i in range(len(base_holds))]
    kept_holds, cancelled_holds, replaced_holds = _partition(refs, delta['holds'], all_mode='all_except', replacement_key='ref', label='holds')
    hold_replacements = {item['ref']: item['hold'] for item in delta['holds']['replace']}
    holds = [deepcopy(base_holds[i] if ref in kept_holds else hold_replacements[ref]) for i, ref in enumerate(refs) if ref in kept_holds or ref in hold_replacements]
    holds += deepcopy(delta['holds']['add'])
    hold_keys = set()
    for hold in holds:
        _require(isinstance(hold, dict) and {'machine', 'until', 'reason'} <= set(hold), 'hold', 'complete explicit hold required')
        mid, after = hold['machine'], hold.get('after_task_id')
        _require(type(mid) is int and mid in machine_by_id and _number(hold['until']) and now < hold['until'] <= header['valid_until']
                 and type(hold['reason']) is str and bool(hold['reason']), 'hold', 'expired/invalid hold needs explicit replacement or cancellation')
        _require(after is None or (type(after) is str and after in compiled_by_id and compiled_by_id[after]['machine'] == mid),
                 'hold_anchor', 'no automatic migration from an executed/deleted/other-machine task')
        _require((mid, after) not in hold_keys, 'hold', 'duplicate explicit hold key')
        hold_keys.add((mid, after))
    plan = {**deepcopy(header), 'tasks': tasks, 'holds': holds}
    evidence = {'schema': SCHEMA + '-evidence', 'anchors': anchors, 'delta_sha256': json_sha256(delta),
        'compiled_plan_sha256': json_sha256(plan), 'physically_dispatched_excluded_ids': dispatched,
        'cancelled_task_ids': cancelled, 'replaced_task_ids': replaced, 'added_task_ids': added_ids,
        'task_sources': [{'id': t['id'], 'source': 'base_exact' if t['id'] in retained else 'explicit_replace' if t['id'] in replacements else 'explicit_add',
                          'task_sha256': json_sha256(t)} for t in tasks],
        'hold_sources': [{'ref': ref, 'source': 'base_exact' if ref in kept_holds else 'explicit_replace'} for ref in refs if ref in kept_holds or ref in hold_replacements]
                        + [{'add_index': i, 'source': 'explicit_add'} for i in range(len(delta['holds']['add']))],
        'cancelled_hold_refs': cancelled_holds, 'replaced_hold_refs': replaced_holds,
        'explicit_machine_orders': deepcopy(orders), 'order_policy': delta['order_policy'],
        'preserved_frozen_prefixes': frozen_prefixes,
        'common_commit_validation_required': True, 'independent_physical_and_source_audit_required': True,
        'model_attribution_certified': False,
        'caller_required_bindings': 'Bind authoritative current state/source, actual model call/request/raw output and all four anchors; an explicit model commit remains mandatory. This compiler does not authenticate model ownership or certify complete physical feasibility.'}
    return {'plan': plan, 'evidence': evidence}
