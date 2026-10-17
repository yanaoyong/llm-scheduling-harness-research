"""Independent, deliberately exponential fixture/reference audit.

No ledger helpers are imported. Enumerates all minimum-size combinations and
then implements the documented deterministic greedy consumption policy. This
checks that policy, not maximum matching; use only small contexts/subsets.
"""
import itertools
import json


def audit_ledger(problem, plan=None, receipts=None):
    plan = plan or {}; receipts = receipts or {}; now = problem['time']
    task_states = {r['task_id']: r['state'] for r in receipts.get('tasks', [])}
    op_states = {r['operation_id']: r['state'] for r in receipts.get('operations', [])}
    tasks = plan.get('tasks', [])
    pending = [t for t in tasks if task_states.get(t['id']) not in ('running', 'done')]
    candidates = []
    for op in problem['operations']:
        owners = [t for t in tasks if op['operation_id'] in t['operation_ids']]
        states = [task_states.get(t['id']) for t in owners]
        state = op_states.get(op['operation_id'])
        if state is None:
            state = next((s for s in ('done', 'running', 'invalid') if s in states),
                         'reserved_not_started' if owners else 'ready_unreserved')
        if (state not in ('ready_unreserved', 'reserved_not_started') or op.get('conditional', False)
                or op.get('predecessor_ids') or op.get('release_time', now) > now):
            continue
        candidates.append((op, state))
    used = set(); matches = []; waits = []
    for machine in sorted(problem['machines'], key=lambda m: m['machine']):
        mid = machine['machine']
        if (machine.get('currently_busy') or machine.get('currently_down') or not machine.get('available', True)
                or any(a <= now < b for a, b in machine.get('unavailable_intervals', []))):
            continue
        legal = [(o, s) for o, s in candidates if mid in o['eligible_machines']
                 and not o.get('qualification_uncertain') and not o.get('same_machine_as')
                 and (machine.get('min_left', 0) <= 0 or machine.get('min_setup') == o.get('setup'))]
        def enumerate_batches(items):
            batches = []
            sizes = sorted({o['batch_min'] for o in items if 1 <= o['batch_min'] <= o['batch_max']})
            for n in sizes:
                for combo in itertools.combinations(sorted(items, key=lambda o: o['operation_id']), n):
                    a = combo[0]
                    if n != a['batch_min']: continue
                    signature = [a['batch_key'], a['batch_min'], a['batch_max']]
                    if all([b['batch_key'], b['batch_min'], b['batch_max']] == signature for b in combo):
                        batches.append((json.dumps(signature, sort_keys=True, separators=(',', ':')),
                                        [o['operation_id'] for o in combo]))
            return sorted(batches)
        batches = enumerate_batches([o for o, s in legal if s == 'ready_unreserved' and o['operation_id'] not in used])
        if batches:
            ids = batches[0][1]; used.update(ids)
            matches.append({'machine': mid, 'operation_ids': ids})
        held = any(h['machine'] == mid and h['until'] > now and
                   (h.get('after_task_id') is None or
                    (task_states.get(h['after_task_id']) in ('running', 'done')
                     and not any(t['machine'] == mid for t in pending))) for h in plan.get('holds', []))
        if held:
            batches = enumerate_batches([o for o, s in legal])
            if batches: waits.append({'machine': mid, 'operation_ids': batches[0][1]})
    return {'avoidable_idle': len(matches), 'avoidable_idle_matches': matches,
            'explicit_wait_idle': len(waits), 'explicit_wait_idle_matches': waits}


def reconcile(ledger_metrics, problem, plan=None, receipts=None):
    independent = audit_ledger(problem, plan, receipts)
    differences = [{'metric': k, 'ledger': ledger_metrics.get(k), 'audit': v}
                   for k, v in independent.items() if ledger_metrics.get(k) != v]
    return {'ok': not differences, 'differences': differences}
