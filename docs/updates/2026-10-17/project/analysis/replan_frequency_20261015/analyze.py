"""Read a consistent snapshot of the live harness; never open its writer API."""
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib
import json
import math
import sqlite3
import statistics
import sys
import zlib

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'experiment_round2_3datasets/artifacts/harness_p5_astra_TUN_B_release/continuations/B3600-no-exception-quota'
OUT = Path(__file__).resolve().parent

def dist(xs):
    xs = sorted(xs)
    return {'n': len(xs), 'sum': sum(xs), 'mean': statistics.mean(xs) if xs else None,
            'median': statistics.median(xs) if xs else None,
            'p90_nearest_rank': xs[math.ceil(.9*len(xs))-1] if xs else None,
            'min': min(xs) if xs else None, 'max': max(xs) if xs else None}

def main():
    if '--snapshot' in sys.argv:
        saved = json.loads((OUT/'snapshot_index.json').read_text())
        head, records, event_refs, physical_refs, observed = (
            saved[k] for k in ('head','records','events','physical','captured_local'))
    else:
        with sqlite3.connect(RUN.joinpath('events.sqlite3').as_uri()+'?mode=ro', uri=True) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            head = json.loads(db.execute("select value from metadata where key='head'").fetchone()[0])
            records = list(db.execute('select namespace,key,ref from records order by rowid'))
            event_refs = list(db.execute('select seq,kind,payload_ref,sha256 from events order by seq'))
            physical_refs = list(db.execute('select seq,object_ref from physical order by seq'))
            observed = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
    cache = {}
    def get(ref):
        if ref not in cache:
            raw = zlib.decompress((RUN/'objects'/f'{ref}.z').read_bytes())
            assert hashlib.sha256(raw).hexdigest() == ref
            cache[ref] = json.loads(raw)
        return cache[ref]
    by_ns = defaultdict(dict)
    for ns,key,ref in records:
        by_ns[ns][key] = ref
    manifest = get(by_ns['manifest']['run'])
    trace = {seq:get(ref) for seq,ref in physical_refs}
    attempts = [get(ref) for ref in by_ns['attempts'].values()]
    actual = [a for a in attempts if a['channel']=='codex' and a['status'] not in ('reserved','not_sent')]
    by_context = defaultdict(list)
    tools, statuses = Counter(), Counter()
    for a in actual:
        by_context[a['context_ref']].append(a)
        try:
            raw = get(a['raw_ref']) if a.get('raw_ref') else {}
            action = raw.get('action', raw)
            tool = action.get('tool', 'no_tool')
        except (ValueError, AttributeError):
            tool = 'unparseable'
        tools[tool] += 1
        response = get(a['response_ref']) if a.get('response_ref') else {}
        statuses[response.get('status','no_response')] += 1
    commits = {get(ref)['actual_revision']:get(ref) for ref in by_ns['commits'].values()}
    attempt_by_id = {a['attempt_id']:a for a in actual}
    rows = []
    for key, ref in sorted(by_ns['feedback'].items(), key=lambda item:int(item[0])):
        f = get(ref)
        commit = commits[int(key)]
        candidate = get(by_ns['candidates'][commit['candidate_ref']])
        plan = candidate['compiled']['plan']
        selection = attempt_by_id[commit['selection_attempt_id']]
        calls = by_context[selection['context_ref']]
        context = get(by_ns['contexts'][selection['context_ref']])
        prior_trigger = context['trigger']
        events = [trace[i] for i in range(f['event_start'],f['event_end'])]
        ds = [e for e in events if e['kind']=='dispatch' and e.get('owner')=='plan']
        done_ids = {e['plan_task_id'] for e in ds}
        pending = [t for t in plan['tasks'] if t['id'] not in done_ids]
        machines = f['stop_reason'].get('machines',[])
        counts = Counter(t['machine'] for t in plan['tasks'])
        end_events = [e for e in events if abs(e['time']-f['to'])<1e-7]
        rows.append({'ordinal':len(rows)+1,'feedback_ref':ref,'commit_id':commit['commit_id'],
            'plan_version':plan['version'],'context_ref':selection['context_ref'],
            'from':f['from'],'to':f['to'],'advanced_seconds':f['advanced_seconds'],
            'stop_reason':f['stop_reason']['reason'],'trigger_entering_context':prior_trigger,
            'gap_count':len(machines),'gap_machines':machines,
            'calls':len(calls),'call_numbers':[a['index']+1 for a in calls],
            'known_tokens':sum((a.get('usage') or {}).get('input_tokens',0)+(a.get('usage') or {}).get('output_tokens',0) for a in calls),
            'model_seconds':sum(a.get('duration_seconds',0) for a in calls),
            'plan_valid_seconds':plan['valid_until']-plan['created_at'],
            'plan_remaining_at_stop':plan['valid_until']-f['to'],
            'plan_task_count':len(plan['tasks']),'plan_machine_count':len(counts),
            'max_machine_queue_depth':max(counts.values(),default=0),
            'plan_hold_count':len(plan.get('holds',[])),
            'holds_expiring_at_stop':[h['machine'] for h in plan.get('holds',[]) if abs(h['until']-f['to'])<1e-7],
            'tasks_starting_after_commit':sum(t['not_before']>f['from']+1e-7 for t in plan['tasks']),
            'tasks_remaining_at_stop':len(pending),
            'dispatch_count':f['dispatch_count_delta'],'completed_operations':f['completed_operations_delta'],
            'end_event_kinds':dict(Counter(e['kind'] for e in end_events)),
            'reason_text':plan['reason']})
    rows.sort(key=lambda r:r['ordinal'])
    positive = [r for r in rows if r['advanced_seconds']>1e-9]
    zeros = [r for r in rows if r['advanced_seconds']<=1e-9]
    gaps = [r for r in rows if r['stop_reason']=='uncovered_demand']
    positive_gaps = [r for r in gaps if r['advanced_seconds']>1e-9]
    def summarize(rs):
        return {'commits':len(rs),'stop_counts':dict(Counter(r['stop_reason'] for r in rs)),
                'advance_seconds':dist([r['advanced_seconds'] for r in rs]),
                'advance_le_1':sum(r['advanced_seconds']<=1 for r in rs),
                'advance_le_10':sum(r['advanced_seconds']<=10 for r in rs),
                'advance_le_30':sum(r['advanced_seconds']<=30 for r in rs),
                'calls':sum(r['calls'] for r in rs),'calls_per_commit':dist([r['calls'] for r in rs]),
                'plan_valid_seconds':dist([r['plan_valid_seconds'] for r in rs]),
                'plan_task_count':dist([r['plan_task_count'] for r in rs]),
                'all_machine_queues_at_most_one':sum(r['max_machine_queue_depth']<=1 for r in rs),
                'no_tasks_remaining_at_stop':sum(r['tasks_remaining_at_stop']==0 for r in rs),
                'gap_machine_count':dist([r['gap_count'] for r in rs if r['gap_count']]),
                'one_family_gap':sum(len({m['family'] for m in r['gap_machines']})==1 for r in rs if r['gap_count'])}
    # Keep groups by exact simulation start, not elapsed wall time or model calls.
    bands = {}
    for lo,hi in [(0,1e-9),(1e-9,600),(600,1200),(1200,1800),(1800,2400),(2400,3600)]:
        rs = [r for r in rows if lo<=r['from']<hi]
        bands[f'{lo:g}_to_{hi:g}'] = summarize(rs)
    snapshot = {'captured_local':observed,'run_directory':str(RUN),'run_id':manifest['run_id'],
                'head':head,'last_event':event_refs[-1],'last_physical':physical_refs[-1],
                'records':records,'events':event_refs,'physical':physical_refs}
    summary = {'captured_local':observed,'run_id':manifest['run_id'],'live_prefix_not_completed_window':True,
        'simulation_seconds':head['time'],'target_seconds':manifest['end_time'],
        'config':{k:manifest['config'][k] for k in ['period_seconds','plan_seconds','lookahead_depth','time_mode']},
        'all':summarize(rows),'positive':summarize(positive),'zero_progress':summarize(zeros),
        'positive_gaps':summarize(positive_gaps),
        'last_20':summarize(rows[-20:]),'bands_by_start_time':bands,
        'actual_model_attempts':len(actual),'model_tool_counts':dict(tools),'response_status_counts':dict(statuses),
        'known_tokens':sum((a.get('usage') or {}).get('input_tokens',0)+(a.get('usage') or {}).get('output_tokens',0) for a in actual),
        'model_seconds':sum(a.get('duration_seconds',0) for a in actual),
        'unknown_usage_attempts':sum(a.get('usage') is None for a in actual),
        'channel_valid_counts':dict(Counter(str((a.get('transport') or {}).get('channel_valid')) for a in actual)),
        'calls_in_completed_rounds':sum(r['calls'] for r in rows),
        'calls_in_uncommitted_contexts':len(actual)-sum(r['calls'] for r in rows),
        'positive_gap_top_families':Counter(m['family'] for r in positive_gaps for m in {m['family']:m for m in r['gap_machines']}.values()).most_common(12),
        'positive_gap_single_machine':sum(r['gap_count']==1 for r in positive_gaps),
        'positive_gap_with_hold_expiry':sum(bool(r['holds_expiring_at_stop']) for r in positive_gaps),
        'gaps_before_plan_expiry':sum(r['plan_remaining_at_stop']>1e-9 for r in gaps),
        'positive_gap_no_tasks_remaining':sum(r['tasks_remaining_at_stop']==0 for r in positive_gaps),
        'plan_horizon_rows':[r for r in rows if r['stop_reason']=='plan_horizon'],
        'last_10':rows[-10:]}
    assert len(commits)==len(rows)==sum(e[1]=='execution_batch' for e in event_refs)
    assert abs(sum(r['advanced_seconds'] for r in rows)-(head['time']-manifest['start_time']))<1e-6
    assert sum(e['kind']=='coverage_gap' for e in trace.values())==len(gaps)
    for filename,data in [('snapshot_index.json',snapshot),('summary.json',summary),('execution_intervals.json',rows)]:
        (OUT/filename).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:summary[k] for k in ['captured_local','simulation_seconds','actual_model_attempts','calls_in_completed_rounds','calls_in_uncommitted_contexts','channel_valid_counts']},ensure_ascii=False))
    print('Saved summary.json, execution_intervals.json and snapshot_index.json')

if __name__=='__main__':
    main()
