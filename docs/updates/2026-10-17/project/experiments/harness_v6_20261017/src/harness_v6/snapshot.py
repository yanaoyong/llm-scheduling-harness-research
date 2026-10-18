"""Complete deterministic snapshot with a fixed-byte history summary.

Full-state only; snapshot scaling awaits a separate user decision.
"""
from dataclasses import dataclass
import hashlib
import json
from .prompt_rules import V6_RULES
from .compact import encode_prefix, decode_prefix, encode_current, decode_snapshot


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


def stable_prefix(*, tool_descriptions, routing, machine_groups):
    if all(isinstance(m, dict) and 'id' in m for m in machine_groups):
        machine_groups = sorted(machine_groups, key=lambda m: m['id'])
    return encode_prefix({'rules': V6_RULES, 'tools': tool_descriptions,
                          'routing': routing, 'machine_groups': machine_groups})


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


def current_state(ledger, *, state_version, running_jobs, last_cycle_receipt,
                  model_notes, history=HistorySummary()):
    """Canonical public object, independent of its wire representation."""
    rows = ledger.rows(); metrics = ledger.metrics()
    ready_rows = []
    for oid, row in rows.items():
        if row['state'] == 'ready_unreserved' and row['ready']:
            op = ledger.operations[oid]
            ready_rows.append({'operation_id': oid, 'eligible_machines': op['eligible_machines'],
                               'batch_key': op['batch_key'], 'batch_min': op['batch_min'],
                               'batch_max': op['batch_max'], 'setup': op.get('setup'),
                               'release_time': op.get('release_time'),
                               'qualification_uncertain': op.get('qualification_uncertain', False)})
    current = {'state_version': state_version, 'time': ledger.now,
               'pending_tasks': ledger.pending_tasks(), 'holds': list(ledger.holds.values()),
               'machines': sorted(ledger.machines.values(), key=lambda m: m['machine']),
               'running_jobs': running_jobs, 'unreserved_ready': sorted(ready_rows, key=lambda r: r['operation_id']),
               'avoidable_idle_matches': metrics['avoidable_idle_matches'],
               'explicit_wait_idle_matches': metrics['explicit_wait_idle_matches'],
               'invalid_tasks': [t for tid, t in ledger.tasks.items()
                                 if ledger.task_receipts.get(tid, {}).get('state') == 'invalid'
                                 or any(rows.get(o, {}).get('state') == 'invalid' for o in t['operation_ids'])],
               'last_cycle_receipt': last_cycle_receipt, 'model_notes': model_notes,
               'reserved_but_earlier_startable': metrics['reserved_but_earlier_startable'],
               'assigned_not_started_age': metrics['assigned_not_started_age'],
               'history_summary': history.digest}
    return current


def build_snapshot(prefix, ledger, *, state_version, running_jobs, last_cycle_receipt,
                   model_notes, token_budget, token_counter=estimate_tokens,
                   history=HistorySummary()):
    current = current_state(ledger, state_version=state_version, running_jobs=running_jobs,
                            last_cycle_receipt=last_cycle_receipt, model_notes=model_notes, history=history)
    payload = prefix + encode_current(decode_prefix(prefix), current)
    count = token_counter(payload.decode('utf-8'))
    if count > token_budget:
        raise SnapshotBudgetExceeded({'code': 'snapshot_budget_exceeded', 'tokens': count,
            'budget': token_budget, 'bytes': len(payload), 'pending_tasks': len(current['pending_tasks']),
            'unreserved_ready': len(current['unreserved_ready']), 'dropped_rows': 0, 'mode': 'full'})
    return payload
