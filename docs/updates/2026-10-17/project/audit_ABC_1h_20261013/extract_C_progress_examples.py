"""Read saved evidence only; do not call models, constructors or simulators."""
import ast
import hashlib
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / 'experiment_round2_3datasets'
C = PROJECT / 'runs/smt_fullfab_stage2/C_1701_1h_constructive_v2'
B = PROJECT / 'runs/smt_fullfab_stage2/B_1701_1h_delta_v15__authorized_extension_001/physical'
hashes = {}


def read(path):
    raw = path.read_bytes()
    hashes[str(path.relative_to(ROOT))] = hashlib.sha256(raw).hexdigest()
    return raw.decode()


def obj(path):
    return json.loads(read(path))


def events(path):
    return [json.loads(line) for line in read(path).splitlines()]


ce, be = events(C / 'trace.jsonl'), events(B / 'trace.jsonl')
commits = [(i, e) for i, e in enumerate(ce) if e['kind'] == 'plan_committed']
# Execute just the recorded, deterministic projection function; this is not
# independent feasibility validation or a rerun of the scheduling algorithm.
runner = C / 'source_snapshot/src/smt_fullfab/runner.py'
node = next(n for n in ast.parse(read(runner)).body
            if isinstance(n, ast.FunctionDef) and n.name == 'crop_plan')
space = {'json': json}
exec(compile(ast.Module(body=[node], type_ignores=[]), str(runner), 'exec'), space)

rows, selected = [], {}
for n, (line, event) in enumerate(commits):
    history = obj(C / f'controller_history_{n:03d}.json')
    request = obj(C / f'constructor_request_{n:03d}.json')
    construction = obj(C / f'constructor_{n+1:03d}.json')
    raw = obj(C / f'raw_plan_{n:03d}.json')
    models = [obj(C / f'model_{2*n+j:03d}/result.json') for j in range(2)]
    assert len(history) == 2
    assert all(m['status'] == 'success' and m['output'] == h['decision']
               for m, h in zip(models, history))
    assert models[0]['output'] == request['response']
    assert request['model_call_id'] == models[0]['call_id']
    assert models[0]['output']['action'] == 'solve'
    assert models[0]['output']['method'] == 'constructive'
    assert models[1]['output']['action'] == 'apply' and models[1]['output']['index'] == 0
    assert construction['plan'] == raw
    assert construction['parameters']['weights'] == request['parameters']['weights']
    assert history[0]['result']['plan_sha256'] == history[1]['plan_sha256']
    assert construction['nominal_audit']['valid']
    assert space['crop_plan'](raw, SimpleNamespace(physical=raw['scope'], horizon=3600.0)) == event['plan']
    end = commits[n+1][0] if n+1 < len(commits) else len(ce)
    row = {
        'commit_number': n+1, 'simulation_seconds': event['time'],
        'trace_line': line+1, 'model_indices': [2*n, 2*n+1],
        'solve': models[0]['output'], 'apply': models[1]['output'],
        'model_duration_sum_seconds': sum(m['duration_seconds'] for m in models),
        'input_plus_output_tokens': sum(m['usage']['input_tokens'] + m['usage']['output_tokens'] for m in models),
        'constructor_invocation_seconds': construction['invocation_duration_seconds'],
        'constructor_status': construction['solver_status'],
        'raw_tasks': len(raw['tasks']), 'raw_operation_visits': construction['planned_operations'],
        'unplanned_operation_visits': len(construction['unplanned_operations']),
        'committed_tasks': len(event['plan']['tasks']),
        'committed_operation_visits': sum(len(t['lot_ids']) for t in event['plan']['tasks']),
        'committed_holds': len(event['plan']['holds']),
        'production_dispatches_until_next_commit': sum(e['kind'] == 'dispatch' and e.get('owner') == 'plan' for e in ce[line:end]),
        'next_commit_or_terminal_seconds': ce[end]['time'] if end < len(ce) else 3600,
        'feedback_task_preview_count': len(history[0]['result']['tasks_preview']),
        'history_file': str((C / f'controller_history_{n:03d}.json').relative_to(ROOT)),
    }
    rows.append(row)
    if n in [0, 1, 2, 7, 10, 17, 43, 45]:
        selected[n] = (raw, event['plan'])

lots = ['w1114', 'w1130', 'w1141', 'w1144', 'w1346', 'w1387', 'w1462', 'w1193', 'w842']
examples = {}
for lot in lots:
    examples[lot] = {}
    for arm, stream in [('B', be), ('C', ce)]:
        examples[lot][arm] = {
            'physical_events': [{'trace_line': i+1, **e} for i, e in enumerate(stream)
                                if e['kind'] in ['ready', 'skip', 'dispatch', 'operation_complete', 'lot_complete']
                                and (e.get('lot') == lot or lot in e.get('lots', []))],
            'terminal_status': stream[-1]['lot_statuses'][lot],
        }
    examples[lot]['C_selected_plans'] = [
        {'commit_number': n+1,
         'raw_tasks': [t for t in raw['tasks'] if lot in t['lot_ids']],
         'committed_tasks': [t for t in committed['tasks'] if lot in t['lot_ids']]}
        for n, (raw, committed) in selected.items()
    ]

last_problem = obj(C / 'problem_045.json')
out = {
    'scope': 'Saved model-result/history/request/constructor-plan/projection/trace links checked. No new model, scheduling or physical simulation run. Model reasons are declared intentions; no causal quality benefit or global optimality inferred.',
    'checked_model_results': len(rows)*2, 'checked_constructive_requests': len(rows),
    'checked_raw_plans_and_recorded_projection': len(rows),
    'C_event_counts': dict(Counter(e['kind'] for e in ce)),
    'C_each_committed_plan_hold_count': sorted(set(r['committed_holds'] for r in rows)),
    'C_final_metrics': ce[-1]['metrics'],
    'C_model_actions_and_plan_summaries': rows,
    'paired_lot_examples': examples,
    'C_final_holds_for_w842_eligible_machines': [h for h in commits[-1][1]['plan']['holds'] if h['machine'] in [1153, 1159]],
    'C_last_public_observation_for_w842_example': {
        'time': last_problem['time'],
        'machines': [m for m in last_problem['machines'] if m['machine'] in [1153, 1159]],
        'operations': [o for o in last_problem['operations'] if o['lot_id'] == 'w842'],
    },
    'source_file_sha256': hashes,
}
dest = Path(__file__).with_name('C_progress_examples.json')
dest.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'saved': str(dest), 'checked_model_results': len(rows)*2,
                  'checked_plans': len(rows), 'initial': rows[0], 'w1193_preplanned': rows[43]},
                 ensure_ascii=False, indent=2))
