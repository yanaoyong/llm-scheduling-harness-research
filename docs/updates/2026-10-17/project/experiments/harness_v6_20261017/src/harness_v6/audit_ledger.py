"""Independent reference audit.

No ledger helpers are imported. Re-implements the SAME greedy policy, catching
implementation slips, not algorithm errors or departure from maximum matching.
Active holds count only as explicit wait, disjoint from avoidable idle.
"""
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
    # Independent inverted qualification index; each operation appears once per
    # machine even if an input qualification list contains duplicate IDs.
    qualified = {}
    for op, state in candidates:
        for mid in set(op['eligible_machines']):
            qualified.setdefault(mid, []).append((op, state))
    used = set(); matches = []; waits = []
    for machine in sorted(problem['machines'], key=lambda m: m['machine']):
        mid = machine['machine']
        if (machine.get('currently_busy') or machine.get('currently_down') or not machine.get('available', True)
                or any(a <= now < b for a, b in machine.get('unavailable_intervals', []))):
            continue
        legal = [(o, s) for o, s in qualified.get(mid, []) if not o.get('qualification_uncertain') and not o.get('same_machine_as')
                 and (machine.get('min_left', 0) <= 0 or machine.get('min_setup') == o.get('setup'))]
        def enumerate_batches(items):
            batches = []
            # Only the lexicographically first combination of each equivalence
            # class can win. Filtering by a representative is independent of
            # ledger bucketing and avoids enumerating C(WIP, batch_min) losers.
            seen = set()
            for a in sorted(items, key=lambda o: o['operation_id']):
                signature = [a['batch_key'], a['batch_min'], a['batch_max']]
                key = json.dumps(signature, sort_keys=True, separators=(',', ':'))
                if key in seen: continue
                seen.add(key)
                n = a['batch_min']
                if not 1 <= n <= a['batch_max']: continue
                compatible = sorted(o['operation_id'] for o in items
                    if [o['batch_key'], o['batch_min'], o['batch_max']] == signature)
                first = compatible[:n] if len(compatible) >= n else None
                if first is not None: batches.append((key, list(first)))
            return sorted(batches)
        held = any(h['machine'] == mid and h['until'] > now and
                   (h.get('after_task_id') is None or
                    (task_states.get(h['after_task_id']) in ('running', 'done')
                     and not any(t['machine'] == mid for t in pending))) for h in plan.get('holds', []))
        if held:
            batches = enumerate_batches([o for o, s in legal])
            if batches: waits.append({'machine': mid, 'operation_ids': batches[0][1]})
            continue
        batches = enumerate_batches([o for o, s in legal if s == 'ready_unreserved' and o['operation_id'] not in used])
        if batches:
            ids = batches[0][1]; used.update(ids)
            matches.append({'machine': mid, 'operation_ids': ids})
    return {'avoidable_idle': len(matches), 'avoidable_idle_matches': matches,
            'explicit_wait_idle': len(waits), 'explicit_wait_idle_matches': waits}


def reconcile(ledger_metrics, problem, plan=None, receipts=None):
    independent = audit_ledger(problem, plan, receipts)
    differences = [{'metric': k, 'ledger': ledger_metrics.get(k), 'audit': v}
                   for k, v in independent.items() if ledger_metrics.get(k) != v]
    return {'ok': not differences, 'differences': differences}
