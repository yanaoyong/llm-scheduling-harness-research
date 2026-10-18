"""Complete deterministic snapshot with a fixed-byte history summary.

Full-state only; snapshot scaling awaits a separate user decision.
"""
from .delta_schema import model_task
from dataclasses import dataclass
import hashlib
import json
from .prompt_rules import V6_RULES, rules_for_format
from .compact import token_cost, encode_prefix, decode_prefix, encode_current, decode_snapshot


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def estimate_tokens(text):
    """Deterministic char estimator, not a model-token guarantee."""
    return (len(text) + 3) // 4


def tiktoken_counter(encoding_name='o200k_base'):
    """Mac-only lazy adapter; caller records installed version and encoding."""
    import tiktoken
    encoding = tiktoken.get_encoding(encoding_name)
    return lambda text: len(encoding.encode(text, disallowed_special=()))


def stable_prefix(*, tool_descriptions, routing, machine_groups, snapshot_format="explicit", token_counter=token_cost, setup_transitions=None, min_runs=None):
    if all(isinstance(m, dict) and 'id' in m for m in machine_groups):
        machine_groups = sorted(machine_groups, key=lambda m: m['id'])
    return encode_prefix({'rules': rules_for_format(snapshot_format), 'tools': tool_descriptions,
                          'routing': routing, 'machine_groups': machine_groups,
                          **({'setup_transitions':setup_transitions,'min_runs':min_runs} if setup_transitions is not None else {})}, snapshot_format=snapshot_format, token_counter=token_counter)


@dataclass(frozen=True)
class HistorySummary:
    """Constant storage chain digest, no unbounded counters or raw history."""
    digest: str = '0' * 64

    def append(self, event):
        return HistorySummary(hashlib.sha256(bytes.fromhex(self.digest) + canonical(event)).hexdigest())


class SnapshotBudgetExceeded(ValueError):
    def __init__(self, report):
        self.report = report
        super().__init__('complete snapshot exceeds token budget')


# G0 dedicated lot map costs 10,676 dense tokens (> user-approved 8,000 cap).
INCLUDE_DUE = False


def due_values(ledger, current):
    visible={r['operation_id'] for section in ('unreserved_ready','upcoming_operations') for r in current[section]}
    return {op['lot_id']:op.get('due') for oid,op in sorted(ledger.operations.items()) if oid in visible}


def current_state(ledger, *, horizon_seconds, state_version, running_jobs, last_cycle_receipt,
                  model_notes, history=HistorySummary()):
    """Canonical public object, independent of its wire representation."""
    from .normalize import number
    if not number(horizon_seconds) or horizon_seconds <= 0:
        raise ValueError('horizon_seconds must be explicitly positive and finite')
    rows = ledger.rows(); metrics = ledger.metrics()
    pending = ledger.pending_tasks()
    reserved = {oid for task in pending for oid in task['operation_ids']}
    from .physical_window import public_operation, queue_diagnostics
    upcoming, ready_rows = [], []
    common = ('earliest_start','nominal_start','batch_key','batch_min','batch_max','setup',
              'eligible_machines','priority','processing_seconds_min','processing_seconds_max')
    for oid, op in sorted(ledger.operations.items()):
        public = public_operation(op, ledger.now)
        row = dict(operation_id=oid, **{k:public.get(k) for k in common})
        if rows[oid]['state']=='ready_unreserved' and rows[oid]['ready']:
            row['waiting_since']=public.get('waiting_since')
            ready_rows.append(row)
        elif not rows[oid]['ready'] and oid not in reserved and public['earliest_start'] <= ledger.now+horizon_seconds:
            row.update({k:public.get(k) for k in ('readiness_basis','predecessor_ids','sampling_percent','conditional')})
            upcoming.append(row)
    current = {'state_version': state_version, 'time': ledger.now, 'horizon_seconds': horizon_seconds,
               'upcoming_operations': upcoming,
               'pending_tasks': [model_task(t) for t in pending],
               'machine_orders': [{'machine': mid, 'task_ids': [t['id'] for t in pending if t['machine'] == mid]}
                                  for mid in sorted({t['machine'] for t in pending})], 'holds': list(ledger.holds.values()),
               'machines': sorted(ledger.machines.values(), key=lambda m: m['machine']),
               'running_jobs': running_jobs, 'unreserved_ready': sorted(ready_rows, key=lambda r: r['operation_id']),
               'avoidable_idle_matches': metrics['avoidable_idle_matches'],
               'explicit_wait_idle_matches': metrics['explicit_wait_idle_matches'],
               'invalid_tasks': [model_task(t) for tid, t in ledger.tasks.items()
                                 if ledger.task_receipts.get(tid, {}).get('state') == 'invalid'
                                 or any(rows.get(o, {}).get('state') == 'invalid' for o in t['operation_ids'])],
               'last_cycle_receipt': last_cycle_receipt, 'model_notes': model_notes,
               'reserved_but_earlier_startable': metrics['reserved_but_earlier_startable'],
               'assigned_not_started_age': metrics['assigned_not_started_age'],
               'history_summary': history.digest}
    if INCLUDE_DUE:
        current["lot_due"]=due_values(ledger,current)
    current.update(queue_diagnostics(ledger))
    return current


def build_snapshot(prefix, ledger, *, horizon_seconds, state_version, running_jobs, last_cycle_receipt,
                   model_notes, token_budget, token_counter=estimate_tokens,
                   history=HistorySummary(), snapshot_format="explicit"):
    from .compact import check_format
    check_format(snapshot_format)
    magic = b"SNAPSHOT_V1_DENSE\n" if snapshot_format == "dense" else b"SNAPSHOT_V1\n"
    if not prefix.startswith(magic):
        raise ValueError("snapshot_format does not match prefix")
    current = current_state(ledger, horizon_seconds=horizon_seconds, state_version=state_version, running_jobs=running_jobs,
                            last_cycle_receipt=last_cycle_receipt, model_notes=model_notes, history=history)
    payload = prefix + (encode_current(decode_prefix(prefix), current, snapshot_format="dense", token_counter=token_counter)
                        if snapshot_format == "dense" else encode_current(decode_prefix(prefix), current))
    count = token_counter(payload.decode('utf-8'))
    if count > token_budget:
        raise SnapshotBudgetExceeded({'code': 'snapshot_budget_exceeded', 'tokens': count,
            'budget': token_budget, 'bytes': len(payload), 'pending_tasks': len(current['pending_tasks']),
            'unreserved_ready': len(current['unreserved_ready']), 'dropped_rows': 0, 'mode': 'full'})
    return payload
