"""Offline attribution of the baseline's 24 uncovered-demand stops.

Only reads sealed SQLite rows, content-addressed objects, and saved prompts.
Does not import a runtime, simulate, compile a candidate, or call a model.
Writes derived analysis only alongside this script.
"""
from pathlib import Path
from collections import Counter
from functools import lru_cache
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
import sqlite3
import zlib

OUT = Path(__file__).resolve().parent
SOURCE = OUT.parent / 'B_context_2x2_20261016'
RUN = SOURCE / 'runs/singleton_2403__baseline'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unpack(value):
    """Decode the saved lossless-v1/v2 presentation, without executing source."""
    if isinstance(value, list):
        return [unpack(x) for x in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {'_literal_object'}:
        return {k: unpack(v) for k, v in value['_literal_object']}
    marker = value.get('_record_table')
    if marker in ('lossless-v1', 'lossless-v2') and 'record_count' in value:
        result = []
        for row in value['rows']:
            columns, vals = (value['columns'], row) if marker == 'lossless-v1' else (value['layouts'][row[0]], row[1])
            item = {}
            for path, v in [*value['constants'], *zip(columns, vals)]:
                cur = item
                for key in path[:-1]:
                    cur = cur.setdefault(key, {})
                cur[path[-1]] = unpack(v)
            result.append(item)
        assert len(result) == value['record_count']
        return result
    return {k: unpack(v) for k, v in value.items()}


def walk(value, path='$'):
    if isinstance(value, dict):
        yield path, value
        for k, v in value.items():
            yield from walk(v, path + '.' + str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from walk(v, path + f'[{i}]')


class Evidence:
    def __init__(self, directory):
        self.directory = directory
        wal = directory / 'events.sqlite3-wal'
        assert not wal.exists() or wal.stat().st_size == 0, 'immutable reader requires no pending WAL'
        self.db = sqlite3.connect(f'file:{directory / "events.sqlite3"}?mode=ro&immutable=1', uri=True)
        self.refs = {}

    @lru_cache(maxsize=None)
    def raw(self, h):
        data = zlib.decompress((self.directory / 'objects' / (h + '.z')).read_bytes())
        assert hashlib.sha256(data).hexdigest() == h, h
        self.refs[h] = len(data)
        return data

    @lru_cache(maxsize=None)
    def get(self, h):
        return json.loads(self.raw(h))

    def records(self, namespace):
        return {key: self.get(ref) for key, ref in self.db.execute(
            'SELECT key,ref FROM records WHERE namespace=? ORDER BY rowid', (namespace,))}


LABELS = {
    'ready_backlog_machine_release': 'A 已就绪任务等设备：明确的提前排队候选',
    'known_successor_no_observed_branch': 'B 已知后继变就绪：条件预排候选，未观察到分支',
    'sampled_target_realized': 'C 抽样工序实际被保留：须确认分支，不能当作确定需求',
    'sampled_predecessor_skipped': 'D 抽样前序被跳过：须确认分支，不能预知跳步',
}


def main():
    verification = json.loads((SOURCE / 'completion_verification.json').read_text())
    tracked = [RUN / 'events.sqlite3', RUN / 'manifest.json', RUN / 'evidence_manifest.json',
               SOURCE / 'summary.json', SOURCE / 'completion_verification.json',
               SOURCE / 'singleton_2403__baseline.audited.result.json']
    before = {str(p): sha(p) for p in tracked}
    assert sha(SOURCE / 'summary.json') == verification['summary_sha256']
    assert sha(tracked[-1]) == verification['rows'][0]['result_sha256']
    assert sha(RUN / 'evidence_manifest.json') == verification['rows'][0]['evidence_sha256']
    e = Evidence(RUN)
    contexts = e.records('contexts')
    candidates = e.records('candidates')
    commits = sorted(e.records('commits').values(), key=lambda x: x['actual_revision'])
    feedback = [v for _, v in sorted(e.records('feedback').items(), key=lambda kv: int(kv[0]))]
    attempts = sorted(e.records('attempts').values(), key=lambda a: a['index'])
    trace = [e.get(h) for h, in e.db.execute('SELECT object_ref FROM physical ORDER BY seq')]
    frames = {}
    prompt_ops = {}
    for a in attempts:
        text = e.raw(a['prompt_ref']).decode()
        offset = text.find('\n{"context":')
        assert offset >= 0, a['attempt_id']
        frame = unpack(json.loads(text[offset + 1:]))
        assert frame['context']['context_ref'] == a['context_ref']
        frames[a['attempt_id']] = frame
        prompt_ops[a['attempt_id']] = [(p, v) for p, v in walk(frame) if 'operation_id' in v]
    assert len(commits) == len(feedback) == 25
    assert [f['stop_reason']['reason'] for f in feedback] == ['uncovered_demand'] * 24 + ['periodic_replan']
    rows = []
    critical = ['operation_id', 'eligible_machines', 'conditional', 'release_time',
                'predecessor_ids', 'sampling_percent', 'rework_percent', 'qualification_basis']
    rejection_rows = []
    for a in attempts:
        if a.get('response_ref'):
            r = e.get(a['response_ref'])
            if r.get('status') == 'rejected':
                rejection_rows.append({'attempt': a['index'] + 1, 'context_ref': a['context_ref'], 'error': r['error']})
    for i, f in enumerate(feedback[:24]):
        commit = commits[i]
        cand = candidates[commit['candidate_ref']]
        context = contexts[cand['context_ref']]
        prior_plan = cand['compiled']['plan']
        next_cand = candidates[commits[i + 1]['candidate_ref']]
        next_plan = next_cand['compiled']['plan']
        after_context = contexts[next_cand['context_ref']]
        assert f['from'] == context['time'] == commit['time']
        assert f['to'] == after_context['time'] == commits[i + 1]['time']
        public_ops = {o['operation_id']: o for o in context['problem']['operations']}
        machines = {m['machine']: m for m in context['problem']['machines']}
        next_machines = {m['machine']: m for m in after_context['problem']['machines']}
        ctx_attempts = [a for a in attempts if a['context_ref'] == context['context_ref'] and a['index'] <= e.records('attempts')[commit['selection_attempt_id']]['index']]
        batch = trace[f['event_start']:f['event_end']]
        dispatches = [x for x in batch if x['kind'] == 'dispatch' and x.get('plan_version') == prior_plan['version']]
        dispatched_ids = {x['plan_task_id'] for x in dispatches}
        remaining = [t for t in prior_plan['tasks'] if t['id'] not in dispatched_ids]
        next_batch = trace[feedback[i + 1]['event_start']:feedback[i + 1]['event_end']]
        details = []
        categories = set()
        for task in next_plan['tasks']:
            for oid in task['operation_ids']:
                op = public_ops.get(oid)
                assert op is not None, f'Newly unavailable operation: {oid}'
                predecessors = []
                def ancestry(x):
                    for pid in x.get('predecessor_ids', []):
                        ancestor = public_ops[pid]
                        if ancestor not in predecessors:
                            predecessors.append(ancestor)
                            ancestry(ancestor)
                ancestry(op)
                lot_events = [x for x in batch if x.get('lot') == op['lot_id']]
                skips = [x for x in lot_events if x['kind'] == 'skip']
                if not op['conditional']:
                    category = 'ready_backlog_machine_release'
                elif skips:
                    category = 'sampled_predecessor_skipped'
                elif op['sampling_percent'] < 100:
                    category = 'sampled_target_realized'
                else:
                    category = 'known_successor_no_observed_branch'
                categories.add(category)
                shown = []
                historical = []
                for a in ctx_attempts:
                    matches = [path for path, val in prompt_ops[a['attempt_id']]
                               if all(k in val and val[k] == op.get(k) for k in critical)]
                    if matches:
                        shown.append({'attempt': a['index'] + 1, 'prompt_sha256': a['prompt_ref'], 'paths': matches})
                    old_matches = [{'path': path, 'different_fields': {k: {'shown': val[k], 'current': op.get(k)} for k in critical if val[k] != op.get(k)}}
                                   for path, val in prompt_ops[a['attempt_id']]
                                   if val.get('operation_id') == oid and all(k in val for k in critical)
                                   and any(val[k] != op.get(k) for k in critical)]
                    if old_matches:
                        historical.append({'attempt': a['index'] + 1, 'prompt_sha256': a['prompt_ref'], 'matches': old_matches})
                returned = []
                queries = []
                for a in ctx_attempts:
                    if not a.get('raw_ref') or not a.get('response_ref'):
                        continue
                    try:
                        action = e.get(a['raw_ref'])
                        action = action.get('action', action)
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if action.get('tool') == 'read_entities':
                        queries.append({'attempt': a['index'] + 1, 'queries': action['queries']})
                        res = e.get(a['response_ref'])
                        for result in res.get('results', []):
                            for ent in result.get('entities', []):
                                if ent.get('kind') == 'operations' and ent.get('id') == oid:
                                    returned.append({'attempt': a['index'] + 1, 'fields': ent.get('projection_fields'), 'response_sha256': a['response_ref']})
                mid = task['machine']
                actual = [x for x in next_batch if x['kind'] == 'dispatch' and x.get('plan_task_id') == task['id'] and x['machine'] == mid]
                assert len(actual) == 1 and actual[0]['time'] == f['to']
                prior_same_lot = [t for t in prior_plan['tasks'] if op['lot_id'] in t['lot_ids']]
                prior_same_machine = [t for t in prior_plan['tasks'] if t['machine'] == mid]
                assert mid in op['eligible_machines']
                assert op['batch_min'] <= len(task['lot_ids']) <= op['batch_max']
                details.append({
                    'task': task, 'category': category,
                    'prior_public_operation': op,
                    'prior_public_predecessors': predecessors,
                    'prior_public_machine': machines[mid], 'next_public_machine': next_machines[mid],
                    'shown_with_current_critical_fields_in_prior_prompts': shown,
                    'shown_with_different_critical_fields_in_prior_prompts': historical,
                    'returned_by_prior_read_entities': returned,
                    'prior_entity_queries': queries,
                    'prior_plan_same_lot': prior_same_lot, 'prior_plan_same_machine': prior_same_machine,
                    'relevant_actual_lot_events': lot_events, 'actual_dispatch': actual[0],
                    'static_checks': {
                        'identity_known_in_previous_public_catalog': True,
                        'selected_machine_in_previous_eligibility': True,
                        'batch_size_within_previous_bounds': True,
                        'qualification_explicitly_uncertain': op.get('qualification_uncertain', False),
                        'no_same_lot_or_machine_in_previous_new_plan': not prior_same_lot and not prior_same_machine,
                    },
                })
        assert len(categories) == 1
        inherited_pending = [t for t in context['base_plan']['tasks']
                             if t['id'] not in context['execution_state']['dispatched_task_ids']]
        rows.append({
            'number': i + 1, 'prior_decision_time': f['from'], 'trigger_time': f['to'],
            'advanced_seconds': f['advanced_seconds'], 'category': categories.pop(),
            'gap_machines': f['stop_reason']['machines'], 'prior_context_ref': context['context_ref'],
            'after_context_ref': after_context['context_ref'], 'prior_candidate_ref': cand['candidate_ref'],
            'next_candidate_ref': next_cand['candidate_ref'], 'prior_plan': prior_plan,
            'next_plan_reason': next_plan['reason'], 'feedback': f,
            'trace_events': batch,
            'queue_audit': {
                'inherited_pending_tasks': inherited_pending, 'previous_plan_task_count': len(prior_plan['tasks']),
                'dispatched_task_ids': sorted(dispatched_ids), 'remaining_at_trigger': remaining,
                'holds': prior_plan['holds'], 'plan_validity_remaining_seconds': prior_plan['valid_until'] - f['to'],
                'cancelled_ids': cand['compiled']['evidence']['cancelled_task_ids'],
                'replaced_ids': cand['compiled']['evidence']['replaced_task_ids'],
                'invalidation_events': [x for x in batch if x['kind'] == 'plan_invalidated'],
            },
            'operation_details': details,
        })
    all_details = [x for r in rows for x in r['operation_details']]
    counts = Counter(r['category'] for r in rows)
    summary = {
        'stops': len(rows), 'looked_up_followup_operations': len(all_details),
        'category_counts': dict(counts), 'category_labels': LABELS,
        'previous_public_catalog_contains_all_followup_operations': all(x['static_checks']['identity_known_in_previous_public_catalog'] for x in all_details),
        'operations_shown_in_prior_prompts': sum(bool(x['shown_with_current_critical_fields_in_prior_prompts']) for x in all_details),
        'operations_with_only_historical_prompt_records': [x['prior_public_operation']['operation_id'] for x in all_details
            if x['shown_with_different_critical_fields_in_prior_prompts'] and not x['shown_with_current_critical_fields_in_prior_prompts']],
        'events_all_followup_operations_shown': [r['number'] for r in rows if all(x['shown_with_current_critical_fields_in_prior_prompts'] for x in r['operation_details'])],
        'events_any_followup_operations_shown': [r['number'] for r in rows if any(x['shown_with_current_critical_fields_in_prior_prompts'] for x in r['operation_details'])],
        'events_with_prior_read_of_followup_operation': [r['number'] for r in rows if any(x['returned_by_prior_read_entities'] for x in r['operation_details'])],
        'events_with_pending_at_trigger': [r['number'] for r in rows if r['queue_audit']['remaining_at_trigger']],
        'events_with_inherited_pending': [r['number'] for r in rows if r['queue_audit']['inherited_pending_tasks']],
        'events_with_cancellations_or_replacements': [r['number'] for r in rows if r['queue_audit']['cancelled_ids'] or r['queue_audit']['replaced_ids']],
        'events_with_holds_or_invalidation': [r['number'] for r in rows if r['queue_audit']['holds'] or r['queue_audit']['invalidation_events']],
        'business_rejections': rejection_rows,
        'remaining_plan_validity_range_seconds': [min(r['queue_audit']['plan_validity_remaining_seconds'] for r in rows), max(r['queue_audit']['plan_validity_remaining_seconds'] for r in rows)],
    }
    out = {
        'schema': 'offline-baseline-replan-attribution-v1',
        'created_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        'source_run': str(RUN), 'source_files_sha256': before,
        'method': 'Join accepted plan, same-context public facts and saved actual prompts, execution feedback, raw physical events, and next accepted/actually-dispatched tasks. No new schedule execution.',
        'limits': [
            'Next accepted task is a retrospective witness, not a policy that would have selected it earlier.',
            'Public catalog availability differs from rendered prompt visibility and from model attention.',
            'Waiting for a physical event does not imply a new model call is unavoidable.',
            'Branch outcomes are not knowable beforehand; conditional preplans may help on some realized branches but no avoidable-replan count or quality counterfactual is proven.',
            'No hypothetical candidate was compiled or simulated. Selected identity, eligibility, batch size and local conflicts are static evidence only.',
            'Actual future event times and draws are used only for retrospective attribution, never treated as prior public facts.',
            'No fresh model, solver, simulator, rollout, source change, or mutation of the source run.',
        ],
        'summary': summary, 'rows': rows,
    }
    after = {str(p): sha(p) for p in tracked}
    assert before == after
    out['verification'] = {'source_files_unchanged': True, 'content_objects_verified': len(e.refs),
                           'sqlite_mode': 'read-only immutable, empty WAL', 'all_24_matched': True,
                           'new_model_calls': 0, 'new_simulator_calls': 0, 'new_solver_calls': 0}
    (OUT / 'attribution.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
    (OUT / 'source_objects.json').write_text(json.dumps(e.refs, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'summary': summary, 'verification': out['verification']}, ensure_ascii=False, indent=2))
    for r in rows:
        print(r['number'], round(r['trigger_time'], 3), r['category'],
              [(x['task']['operation_ids'], bool(x['shown_with_current_critical_fields_in_prior_prompts']), bool(x['returned_by_prior_read_entities'])) for x in r['operation_details']])
    e.db.close()


if __name__ == '__main__':
    main()
