"""Static classification only; never extrapolates new trajectories or call counts."""
import json
from pathlib import Path
import sqlite3
from typing import Protocol, Iterable
from .ledger import ledger_from_scratch


class ContextReader(Protocol):
    def contexts(self) -> Iterable[dict]:
        """Yield {group, context}; context follows the archived public context schema."""
        ...


class SQLiteContextReader:
    """Read-only Mac adapter. Supply the archive-specific SELECT returning group,
    JSON context columns; no assumptions about sealed Store schema or locations.
    Missing evidence raises FileNotFoundError (the Mac test skips explicitly).
    """
    def __init__(self, path, query):
        self.path, self.query = Path(path), query

    def contexts(self):
        if not self.path.is_file(): raise FileNotFoundError(self.path)
        with sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True) as db:
            db.execute('PRAGMA query_only=ON')
            for group, payload in db.execute(self.query):
                yield {'group': group, 'context': json.loads(payload)}


def classify_sealed_contexts(reader, *, expected, witness_operation, start=882, end=1603.10):
    counts = {}; exceptions = []; classified = []; opportunity_count = 0; seconds = 0
    witness = []
    for entry in reader.contexts():
        group, ctx = entry['group'], entry['context']; counts.setdefault(group, 0)
        execution = ctx.get('execution_state', {})
        receipts = ctx.get('ledger_receipts', {'tasks': [
            {'task_id': tid, 'state': 'running'} for tid in execution.get('dispatched_task_ids', [])] + [
            {'task_id': tid, 'state': 'invalid'} for tid in execution.get('invalidated_task_ids', [])]})
        ledger = ledger_from_scratch(ctx['problem'], ctx['base_plan'], receipts)
        metrics = ledger.metrics()
        pending = ledger.pending_tasks()
        owner = {oid for t in pending for oid in t['operation_ids']}
        trigger = ctx.get('trigger') or {}; gaps = trigger.get('machines', [])
        old = trigger.get('reason') == 'uncovered_demand' and start <= ctx['time'] <= end and bool(gaps)
        for gap in gaps:
            ops = [o for o in ctx['problem']['operations'] if not o.get('conditional', False)
                   and o['release_time'] <= ctx['time'] and gap['machine'] in o['eligible_machines']]
            old = old and bool(ops) and len(ops) == gap['candidate_count'] and all(o['operation_id'] in owner for o in ops)
        ref = ctx.get('context_ref')
        record = {'group': group, 'context_ref': ref, 'old_reserved_only': bool(old),
                  'new_avoidable_idle_trigger': metrics['avoidable_idle'] > 0, 'metrics': metrics}
        classified.append(record)
        if old:
            counts[group] += 1
            if metrics['avoidable_idle']: exceptions.append(record)
            opportunities = metrics['reserved_but_earlier_startable']
            # One op can have several alternative machines: do not sum duplicates.
            per_op = {}
            for o in opportunities:
                per_op[o['operation_id']] = max(per_op.get(o['operation_id'], 0), o['potential_idle_seconds'])
            opportunity_count += len(per_op); seconds += sum(per_op.values())
        if any(witness_operation in m['operation_ids'] for key in ('avoidable_idle_matches', 'explicit_wait_idle_matches')
               for m in metrics[key]):
            witness.append({'group': group, 'context_ref': ref})
    return {'old_rule_counts': counts, 'expected_old_rule_counts': expected,
            'old_counts_match': counts == expected, 'new_rule_exceptions': exceptions,
            'reserved_but_earlier_startable_count': opportunity_count,
            'potential_idle_seconds': seconds, 'seconds_basis': 'static public forecast; not measured trajectory idle',
            'operation_witnesses': witness, 'contexts': classified}
