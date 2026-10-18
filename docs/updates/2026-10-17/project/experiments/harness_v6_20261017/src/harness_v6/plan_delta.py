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
    def __init__(self, code, detail, violations=None):
        self.violations = violations or [{"code": code, "detail": detail}]
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


def _partition(universe, patch, *, replacement_key, label):
    _keys(patch, ('cancel_ids', 'replace', 'add'), label)
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
    _require(set(cancelled + replaced) <= domain, 'unknown_or_dispatched_id', label)
    retained = domain - set(cancelled + replaced)
    return retained, cancelled, replaced


def compile_plan_delta(base_plan, problem, execution_state, delta, *, source_sha256, state_version=None, submission_id=None):
    """Compile implicit retention and explicit cancellations/replacements/additions into one full plan.

    No input is mutated. Task array order within each machine is authoritative;
    no sorting by machine/ID/priority is performed. Existing global interleaving
    is retained where possible and has no cross-machine scheduling semantics.
    """
    errors = []
    def check(condition, code, detail):
        if not condition:
            errors.append({'code': code, 'detail': detail})
    anchors = anchor_hashes(base_plan, problem, execution_state, source_sha256=source_sha256)
    _keys(delta, ('plan_header', 'tasks', 'holds', 'machine_orders'), 'delta')
    _keys({k: v for k, v in execution_state.items() if k != 'invalidated_task_ids'}, ('schema', 'time', 'observation_end', 'base_plan_version', 'dispatched_task_ids'), 'execution_state')
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
    _require(all(type(t.get('machine')) is int and ('not_before' not in t or _number(t['not_before'])) for t in base_tasks),
             'base_state', 'base machine/start identities must be explicit and correctly typed')
    by_id = {t['id']: t for t in base_tasks}
    dispatched = _ids(execution_state['dispatched_task_ids'], 'dispatched task IDs')
    _require(set(dispatched) <= set(base_ids), 'base_state', 'dispatch receipt does not belong to the base plan')
    invalidated = _ids(execution_state.get('invalidated_task_ids', []), 'invalidated task IDs')
    _require(set(invalidated) <= set(base_ids) - set(dispatched), 'base_state', 'invalidation receipt must name pending base tasks')
    pending = [tid for tid in base_ids if tid not in set(dispatched)]
    retained, cancelled, replaced = _partition(pending, delta['tasks'], replacement_key='id', label='tasks')
    replacements = {t['id']: t for t in delta['tasks']['replace']}
    added = delta['tasks']['add']
    _require(all(isinstance(t, dict) and 'id' in t for t in added), 'schema', 'added task')
    added_ids = _ids([t['id'] for t in added], 'added task IDs')
    _require(not set(added_ids).intersection(base_ids), 'reused_id', 'new task reuses any base task ID')
    tasks = [deepcopy(by_id[tid] if tid in retained else replacements[tid]) for tid in pending if tid in retained or tid in replacements]
    tasks += deepcopy(added)
    orders = delta['machine_orders']
    _require(isinstance(orders, list), 'schema', 'machine_orders')
    explicit, assignments = {}, {}
    task_ids = {t['id'] for t in tasks}
    for order in orders:
        _keys(order, ('machine', 'task_ids'), 'machine order')
        mid = order['machine']
        _require(type(mid) is int and mid not in explicit, 'machine_order', 'invalid/duplicate machine order')
        values = _ids(order['task_ids'], 'machine order IDs')
        _require(set(values) <= task_ids, 'machine_order', 'unknown task in machine order')
        for tid in values:
            _require(tid not in assignments, 'machine_order', 'task listed in multiple orders: ' + tid)
            assignments[tid] = mid
        explicit[mid] = values
    ops = {o['operation_id']: o for o in problem.get('operations', [])}
    for task in tasks:
        tid = task['id']
        if tid not in retained:
            _require(isinstance(task, dict) and {'id', 'operation_ids'} <= set(task)
                     and set(task) <= {'id', 'operation_ids', 'start_mode', 'not_before', 'latest_start'},
                     'schema', 'model task decisions only')
            if 'latest_start' in task:
                check(_number(task['latest_start']), 'latest_start', 'finite latest_start required: ' + tid)
            oids = _ids(task['operation_ids'], 'task operation IDs')
            _require(bool(oids), 'ids', 'task operation IDs must not be empty')
            unknown = [oid for oid in oids if oid not in ops]
            _require(not unknown, 'unknown_operation', str(unknown))
            for key, field in [('lot_ids', 'lot_id'), ('steps', 'step'), ('visits', 'visit')]:
                task[key] = [ops[oid][field] for oid in oids]
            if tid in replacements:
                task['machine'] = by_id[tid]['machine']
            else:
                _require(tid in assignments, 'missing_machine_order', 'new task must be listed: ' + tid)
        if tid in assignments:
            task['machine'] = assignments[tid]
    for mid, values in explicit.items():
        _require(set(values) == {t['id'] for t in tasks if t['machine'] == mid},
                 'machine_order', 'machine order must list exactly its resulting task IDs')
    changed_machines = {t['machine'] for t in tasks if t['id'] in added_ids}
    for task in tasks:
        if task['id'] in by_id and task['machine'] != by_id[task['id']]['machine']:
            changed_machines.update((task['machine'], by_id[task['id']]['machine']))
    _require(changed_machines <= set(explicit), 'missing_machine_order', 'new or moved tasks need full affected-machine orders')
    compiled_by_id = {t['id']: t for t in tasks}
    positions = {mid: iter(ids) for mid, ids in explicit.items()}
    tasks = [deepcopy(compiled_by_id[next(positions[t['machine']])]) if t['machine'] in positions else t for t in tasks]
    _keys(delta['plan_header'], ('valid_until', 'freeze_until', 'reason'), 'plan_header')
    header = dict(deepcopy(delta['plan_header']), created_at=now, scope=deepcopy(problem['scope']),
                  version='v6:' + json_sha256([state_version, submission_id, anchors, delta]))
    check(type(header['reason']) is str and bool(header['reason']), 'header', 'nonempty reason required')
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
    # Frozen evidence mirrors the collector, exempting only cancelled invalid tasks.
    cancelled_invalid = set(invalidated) & set(cancelled)
    frozen = [t for t in base_tasks if t['id'] in pending and t['id'] not in cancelled_invalid
              and now < base_plan['freeze_until']
              and t.get('not_before', base_plan['created_at']) < base_plan['freeze_until']]
    frozen_ids = {t['id'] for t in frozen}
    frozen_prefixes = []
    for mid in mids:
        before = [t for t in base_tasks if t['machine'] == mid and t['id'] in pending and t['id'] not in cancelled_invalid]
        last_frozen = max((i for i,t in enumerate(before) if t['id'] in frozen_ids), default=-1)
        prefix = before[:last_frozen+1]
        if prefix:
            frozen_prefixes.append({'machine': mid, 'task_ids': [t['id'] for t in prefix], 'tasks_sha256': json_sha256(prefix)})
    base_holds = base_plan.get('holds', [])
    _require(isinstance(base_holds, list) and all(isinstance(h, dict) for h in base_holds), 'schema', 'base holds')
    refs = ['h:' + str(i) for i in range(len(base_holds))]
    kept_holds, cancelled_holds, replaced_holds = _partition(refs, delta['holds'], replacement_key='ref', label='holds')
    hold_replacements = {item['ref']: item['hold'] for item in delta['holds']['replace']}
    holds = [deepcopy(base_holds[i] if ref in kept_holds else hold_replacements[ref]) for i, ref in enumerate(refs) if ref in kept_holds or ref in hold_replacements]
    for hold in list(hold_replacements.values()) + delta['holds']['add']:
        _require(isinstance(hold, dict) and {'machine', 'until', 'reason'} <= set(hold)
                 and set(hold) <= {'machine', 'until', 'reason', 'after_task_id'}, 'schema', 'hold decisions only')
    holds += deepcopy(delta['holds']['add'])
    plan = {**deepcopy(header), 'tasks': tasks, 'holds': holds}
    from .normalize import validate_plan
    violations = errors + validate_plan(plan, problem, execution_state, base_plan=base_plan)
    if violations:
        raise DeltaError(violations[0]['code'], violations[0]['detail'], violations)
    evidence = {'schema': SCHEMA + '-evidence', 'anchors': anchors, 'delta_sha256': json_sha256(delta),
        'compiled_plan_sha256': json_sha256(plan), 'physically_dispatched_excluded_ids': dispatched,
        'cancelled_task_ids': cancelled, 'replaced_task_ids': replaced, 'added_task_ids': added_ids,
        'task_sources': [{'id': t['id'], 'source': 'base_move' if t['id'] in retained and t['machine'] != by_id[t['id']]['machine'] else 'base_exact' if t['id'] in retained else 'explicit_replace' if t['id'] in replacements else 'explicit_add',
                          'task_sha256': json_sha256(t)} for t in tasks],
        'hold_sources': [{'ref': ref, 'source': 'base_exact' if ref in kept_holds else 'explicit_replace'} for ref in refs if ref in kept_holds or ref in hold_replacements]
                        + [{'add_index': i, 'source': 'explicit_add'} for i in range(len(delta['holds']['add']))],
        'cancelled_hold_refs': cancelled_holds, 'replaced_hold_refs': replaced_holds,
        'explicit_machine_orders': deepcopy(orders), 'order_policy': ORDER_POLICY,
        'preserved_frozen_prefixes': frozen_prefixes,
        'common_commit_validation_required': True, 'independent_physical_and_source_audit_required': True,
        'model_attribution_certified': False,
        'caller_required_bindings': 'Bind authoritative current state/source, actual model call/request/raw output and all four anchors; an explicit model commit remains mandatory. This compiler does not authenticate model ownership or certify complete physical feasibility.'}
    return {'plan': plan, 'evidence': evidence}


def validate_plan_delta(base_plan, problem, execution_state, delta, *, source_sha256, state_version=None, submission_id=None):
    """Read-only diagnostics. Structural dependency failures block compilation;
    a structurally compilable plan returns all independent constraint failures.
    """
    try:
        compile_plan_delta(base_plan, problem, execution_state, delta, source_sha256=source_sha256, state_version=state_version, submission_id=submission_id)
    except DeltaError as exc:
        return exc.violations
    return []
