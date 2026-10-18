"""Public operation ledger; no production tasks are generated or dispatched.

Updates mutate only indexed input records, O(changed records + changed task
memberships). Time is a scalar: age/readiness/hold expiry are evaluated on read.
rows()/metrics() perform full O(WIP) reads; matching adds qualification and
witness work. Machine queues are built once per metrics() call.

Matching is a deterministic greedy maximal approximation, NOT maximum matching:
visit idle machines by numeric ID, bucket eligible ready operations by exact
(batch_key, min, max), choose the lexicographically first bucket with enough
members, take its minimum batch in operation-ID order, consume those members.
This prevents double-counting cross-machine demand but can underestimate optimal
utilization. Active holds exclude machines from avoidable idle; feasible held
work counts only as explicit_wait_idle. The two disjoint metrics may be summed.
Unresolved same_machine_as bindings remain exclusions; absent recorded dedication
is not an exclusion. Avoidable idle is a greedy witness lower bound. Receipt extensions supply running/done/invalid identity.
"""
from copy import deepcopy
from dataclasses import dataclass, field
import json
from .normalize import active_holds


def batch_signature(op):
    return json.dumps([op['batch_key'], op['batch_min'], op['batch_max']],
                      sort_keys=True, separators=(',', ':'))


def ready(op, now):
    return (not op.get('conditional', False) and not op.get('predecessor_ids')
            and op.get('release_time', now) <= now)


def idle(machine, now):
    return (len(machine.get('processing_until', [])) < (2 if machine.get('cascading') else 1)
            and not machine.get('currently_busy', False)
            and not machine.get('currently_down', False)
            and machine.get('available', True)
            and not any(a <= now < b for a, b in machine.get('unavailable_intervals', [])))


def eligible(op, machine):
    return (machine['machine'] in op['eligible_machines']
            and not op.get('same_machine_as')
            and (machine.get('min_left', 0) <= 0
                 or machine.get('min_setup') == op.get('setup')))


def choose_batch(ops, machine, used=()):
    buckets = {}
    for oid, op in ops.items():
        if oid not in used and eligible(op, machine):
            buckets.setdefault(batch_signature(op), []).append(oid)
    for key in sorted(buckets):
        ids = sorted(buckets[key]); op = ops[ids[0]]
        if 1 <= op['batch_min'] <= op['batch_max'] and len(ids) >= op['batch_min']:
            return ids[:op['batch_min']]
    return []


@dataclass
class Ledger:
    now: float
    operations: dict = field(default_factory=dict)
    machines: dict = field(default_factory=dict)
    tasks: dict = field(default_factory=dict)
    holds: dict = field(default_factory=dict)
    receipts: dict = field(default_factory=dict)
    task_receipts: dict = field(default_factory=dict)
    owners: dict = field(default_factory=dict)
    plan_created_at: float = 0
    update_work: int = 0

    def rows(self):
        rows = {}
        for oid in sorted(self.operations.keys() | self.receipts.keys() | self.owners.keys()):
            op = self.operations.get(oid, {})
            receipt = self.receipts.get(oid, {})
            tids = sorted(self.owners.get(oid, ()))
            pending = [t for t in tids if self.task_receipts.get(t, {}).get('state') not in ('running', 'done')]
            states = [self.task_receipts.get(t, {}).get('state') for t in tids]
            state = receipt.get('state')
            if state is None:
                state = ('done' if 'done' in states else 'running' if 'running' in states else
                         'invalid' if 'invalid' in states else
                         'reserved_not_started' if pending else 'ready_unreserved')
            rows[oid] = {'operation_id': oid, 'state': state,
                         'ready': bool(op) and ready(op, self.now), 'task_ids': pending,
                         'assigned_not_started_age': max([0] + [max(0, self.now -
                             self.tasks[t].get('assigned_at', self.plan_created_at)) for t in pending])}
        return rows

    def pending_tasks(self):
        return [deepcopy(t) for tid, t in self.tasks.items()
                if self.task_receipts.get(tid, {}).get('state') not in ('running', 'done')]

    def metrics(self):
        rows = self.rows()
        available = {oid: self.operations[oid] for oid, r in rows.items()
                     if r['ready'] and r['state'] in ('ready_unreserved', 'reserved_not_started')}
        unreserved = {oid: op for oid, op in available.items() if rows[oid]['state'] == 'ready_unreserved'}
        by_machine = {}
        for oid, op in available.items():
            for mid in op['eligible_machines']:
                by_machine.setdefault(mid, {})[oid] = op
        matches, waits, opportunities, used = [], [], [], set()
        pending = self.pending_tasks()
        queues = {}
        for task in pending:
            queues.setdefault(task['machine'], []).append(task)
        dispatched = {t for t, r in self.task_receipts.items() if r.get('state') in ('running', 'done')}
        for mid, machine in sorted(self.machines.items()):
            if not idle(machine, self.now):
                continue
            candidates = by_machine.get(mid, {})
            free = {oid: op for oid, op in candidates.items() if oid in unreserved}
            queue = queues.get(mid, [])
            held = active_holds(self.holds.values(), machine=mid, now=self.now,
                                pending_tasks=queue, dispatched_task_ids=dispatched)
            batch = choose_batch(candidates, machine)
            if held and batch:
                waits.append({'machine': mid, 'operation_ids': batch})
            if held:
                continue
            batch = choose_batch(free, machine, used)
            if batch:
                matches.append({'machine': mid, 'operation_ids': batch}); used.update(batch)
            # Opportunity witnesses are diagnostic, not proposed task batches.
            for oid, op in sorted(candidates.items()):
                if rows[oid]['state'] != 'reserved_not_started' or not eligible(op, machine):
                    continue
                compatible = {k: v for k, v in candidates.items() if batch_signature(v) == batch_signature(op)}
                if not choose_batch(compatible, machine):
                    continue
                for tid in rows[oid]['task_ids']:
                    task = self.tasks[tid]
                    if task['machine'] == mid:
                        continue
                    original = self.machines.get(task['machine'], {})
                    original_queue = queues.get(task['machine'], [])
                    original_hold = active_holds(self.holds.values(), machine=task['machine'], now=self.now,
                                                pending_tasks=original_queue, dispatched_task_ids=dispatched)
                    estimate = max(self.now, task.get('not_before', self.now), original.get('available_at', self.now))
                    delayed = (estimate > self.now or not idle(original, self.now) or original_hold
                               or (original_queue and original_queue[0]['id'] != tid))
                    if delayed:
                        opportunities.append({'operation_id': oid, 'task_id': tid, 'machine': mid,
                                              'assigned_machine': task['machine'],
                                              'potential_idle_seconds': estimate - self.now,
                                              'seconds_basis': 'public_forecast_estimate'})
        return {'avoidable_idle': len(matches), 'avoidable_idle_matches': matches,
                'explicit_wait_idle': len(waits), 'explicit_wait_idle_matches': waits,
                'reserved_but_earlier_startable': opportunities,
                'assigned_not_started_age': {oid: r['assigned_not_started_age'] for oid, r in rows.items()
                                            if r['state'] == 'reserved_not_started'}}


def ledger_apply(ledger, delta):
    """Apply an indexed delta in place, return ledger; repeated deltas are idempotent.

    Each table takes {upsert: [rows], delete: [IDs]}; receipt tables take upsert
    rows with operation_id/task_id and state. Operations may be removed without
    implying completion. Explicit receipt deletions allow host history eviction.
    Plan order follows insertion order; replacement preserves position. Reordering
    requires delete+upsert of the affected queue suffix. No full-plan diff occurs.
    """
    ledger.update_work = 0
    ledger.now = delta.get('time', ledger.now)
    ledger.plan_created_at = delta.get('plan_created_at', ledger.plan_created_at)
    for name, key in [('operations', 'operation_id'), ('machines', 'machine'), ('tasks', 'id'),
                      ('holds', 'id'), ('receipts', 'operation_id'), ('task_receipts', 'task_id')]:
        table = getattr(ledger, name)
        change = delta.get(name, {})
        for identity in change.get('delete', []):
            old = table.pop(identity, None)
            if name == 'tasks' and old:
                for oid in old['operation_ids']:
                    ledger.owners[oid].discard(identity)
                    if not ledger.owners[oid]: del ledger.owners[oid]
                    ledger.update_work += 1
            ledger.update_work += 1
        for row in change.get('upsert', []):
            identity = row[key]
            if name == 'tasks':
                old = table.get(identity, {})
                for oid in old.get('operation_ids', []):
                    ledger.owners[oid].discard(identity)
                    if not ledger.owners[oid]: del ledger.owners[oid]
                    ledger.update_work += 1
                for oid in row['operation_ids']:
                    ledger.owners.setdefault(oid, set()).add(identity)
                    ledger.update_work += 1
            table[identity] = deepcopy(row)
            ledger.update_work += 1
    return ledger


def ledger_from_scratch(problem, plan=None, receipts=None):
    """Receipts: operations/task lists of explicit states; no absent==done inference.

    Hold IDs are index keys only: an omitted ID is assigned a stable source index.
    Public future operations occupy ready_unreserved with ready=False and are
    never counted as ready work. The five-state vocabulary stays exhaustive.
    """
    plan = plan or {}; receipts = receipts or {}
    ledger = Ledger(problem['time'])
    ledger_apply(ledger, {'plan_created_at': plan.get('created_at', problem['time']),
        'operations': {'upsert': problem['operations']}, 'machines': {'upsert': problem['machines']},
        'tasks': {'upsert': plan.get('tasks', [])},
        'receipts': {'upsert': receipts.get('operations', [])},
        'task_receipts': {'upsert': receipts.get('tasks', [])}})
    ledger.holds = {h.get('id', f'hold:{i}'): deepcopy(h) for i, h in enumerate(plan.get('holds', []))}
    return ledger


def ledger_read_view(problem, plan=None, receipts=None):
    """Ephemeral read-only projection of caller-owned immutable observations.

    Use only for rows/metrics/snapshot reads while inputs remain unchanged. The
    mutable/persistent API remains ledger_from_scratch and copies all records.
    Tables and ownership indices are fresh; nested observation records are shared.
    """
    plan=plan or {};receipts=receipts or {}
    result=Ledger(problem['time'],plan_created_at=plan.get('created_at',problem['time']))
    for name,key,rows in (
        ('operations','operation_id',problem['operations']),('machines','machine',problem['machines']),
        ('tasks','id',plan.get('tasks',[])),('receipts','operation_id',receipts.get('operations',[])),
        ('task_receipts','task_id',receipts.get('tasks',[]))):
        setattr(result,name,{r[key]:r for r in rows})
    result.holds={h.get('id',f'hold:{i}'):h for i,h in enumerate(plan.get('holds',[]))}
    for tid,task in result.tasks.items():
        for oid in task['operation_ids']:result.owners.setdefault(oid,set()).add(tid)
    return result
