"""Inspect only saved public observations and model actions; no runtime calls."""
from collections import Counter
from pathlib import Path
import hashlib
import json
import statistics
import sys
import zlib

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'experiment_round2_3datasets'))
from src.smt_fullfab.harness.presentation import unpack

OUT = Path(__file__).resolve().parent
BASE = ROOT/'analysis/replan_frequency_20261015'
snapshot = json.loads((BASE/'snapshot_index.json').read_text())
intervals = json.loads((BASE/'execution_intervals.json').read_text())
RUN = Path(snapshot['run_directory'])
records = {(ns,key):ref for ns,key,ref in snapshot['records']}
cache = {}

def raw(ref):
    value = zlib.decompress((RUN/'objects'/f'{ref}.z').read_bytes())
    assert hashlib.sha256(value).hexdigest() == ref
    return value

def get(ref):
    if ref not in cache:
        cache[ref] = json.loads(raw(ref))
    return cache[ref]

attempts = sorted([get(ref) for (ns,_),ref in records.items() if ns=='attempts'], key=lambda a:a['index'])
by_call = {a['index']+1:a for a in attempts}
calls = []
for row in intervals[-9:]:
    for number in row['call_numbers']:
        attempt = by_call[number]
        prompt = raw(attempt['prompt_ref']).decode()
        start = prompt.find('\n{')
        assert start >= 0
        frame = json.loads(prompt[start+1:])
        ctx = frame['context']
        inline = unpack(ctx['pertinent_operations'])
        action = get(attempt['raw_ref'])
        action = action.get('action', action)
        entry = {'call':number,'round':row['ordinal'],'context_ref':attempt['context_ref'],
                 'prompt_sha256':attempt['prompt_ref'],'raw_action_sha256':attempt['raw_ref'],
                 'prompt_characters':len(prompt),'tool':action['tool'],
                 'inline_operations':len(inline),'inline_operation_families':dict(Counter(o['family'] for o in inline)),
                 'inline_nonconditional_operations':sum(not o['conditional'] for o in inline),
                 'pertinent_total':ctx['pertinent_operations_total'],'pertinent_omitted':ctx['pertinent_operations_omitted'],
                 'total_public_operations':ctx['catalogs']['operations']['count'],
                 'gap_machine_ids':[m['machine'] for m in ctx['trigger']['machines']],
                 'pending_task_count':len(ctx['pending_base_task_ids']),
                 'notes':ctx['notes'],'history_entries':len(frame['interaction_history']['entries']),
                 'contains_advanced_seconds_feedback':'advanced_seconds' in prompt,
                 'contains_dispatch_count_delta_feedback':'dispatch_count_delta' in prompt,
                 'contains_lookahead_depth':'lookahead_depth' in prompt,
                 'task':frame['task']}
        if action['tool']=='read_entities':entry['queries']=action['queries']
        if action['tool']=='propose_delta':
            delta=action['delta']
            entry.update(header={k:v for k,v in delta['plan_header'].items() if k!='scope'},
                         added_task_count=len(delta['tasks']['add']),
                         explicit_orders=delta['machine_orders'])
        calls.append(entry)

queries = [q for c in calls for q in c.get('queries',[]) if q['kind']=='operations']
selected_refs = {get(ref)['candidate_ref'] for (ns,_),ref in records.items() if ns=='commits'}
all_candidates = [get(ref) for (ns,key),ref in records.items() if ns=='candidates' and key in selected_refs]
multi = sorted([{'call':c['attempt_index']+1,'added':len(c['delta']['tasks']['add']),
                 'candidate_ref':c['candidate_ref'],'reason':c['compiled']['plan']['reason']}
                for c in all_candidates], key=lambda c:c['added'], reverse=True)[:3]
rejections = []
for a in attempts:
    response=get(a['response_ref']) if a.get('response_ref') else {}
    if response.get('status')=='rejected':
        rejections.append({'call':a['index']+1,'response':response})

row=intervals[-1]
full=get(records['contexts',row['context_ref']])
ops=full['problem']['operations']; machines=full['problem']['machines']; now=full['time']
conditional=[o for o in ops if o['conditional']]
no_own_branch=[o for o in conditional if o['sampling_percent']==100 and o['rework_percent']==0]
next_machines=[m for m in machines if m['currently_busy'] and now<m['available_at']<=now+300]
machine747=next(m for m in machines if m['machine']==747)
ready747=[o for o in ops if 747 in o['eligible_machines'] and not o['conditional'] and o['release_time']<=now]

sources={}
for name in ['harness/transport.py','harness/runtime.py','harness/fact_memory.py','harness/facts.py','plan_delta.py','observation.py','environment.py']:
    path=ROOT/'experiment_round2_3datasets/src/smt_fullfab'/name
    sources[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()

summary={
    'baseline_snapshot_local':snapshot['captured_local'],
    'scope':'Completed rounds 128–136 and their 28 public model actions; earlier rounds used only to check capability and queue history.',
    'live_runtime_modified':False,'new_evaluation_model_calls':0,
    'recent_rounds':9,'recent_calls':len(calls),
    'recent_operation_queries':len(queries),
    'recent_operation_queries_explicitly_excluding_conditional':sum(any(p=={'field':'conditional','op':'eq','value':False} for p in q.get('where',[])) for q in queries),
    'recent_prompt_characters':{'min':min(c['prompt_characters'] for c in calls),'max':max(c['prompt_characters'] for c in calls),'cap':120000},
    'recent_prompts_with_direct_execution_delta_feedback':sum(c['contains_advanced_seconds_feedback'] for c in calls),
    'recent_proposals_one_new_task':sum(c.get('added_task_count')==1 for c in calls),
    'largest_actual_accepted_candidates':multi,
    'all_rejections':rejections,
    'public_state_at_last_commit':{'time':now,'all_operations':len(ops),'conditional_operations':len(conditional),
        'conditional_operations_without_sampling_or_rework_on_own_step':len(no_own_branch),
        'conditional_count_note':'Own-step checks do not guarantee an entire route; upstream branches and random timing may remain.',
        'busy_machines_nominally_available_within_300_seconds':len(next_machines),
        'machine747':machine747,'nonconditional_operation_candidates_for_747':len(ready747),
        'machine747_in_current_gap':747 in {m['machine'] for m in full['trigger']['machines']},
        'machine747_in_recent_plan':any(t['machine']==747 for c in all_candidates if c['context_ref']==row['context_ref'] for t in c['compiled']['plan']['tasks'])},
    'trajectory':[{k:r[k] for k in ['ordinal','from','plan_task_count','tasks_remaining_at_stop','max_machine_queue_depth','reason_text']} for r in intervals if r['ordinal'] in [33,38,94,95,128,136]],
    'findings':[
        {'claim':'The tools accept many tasks and explicit machine queues in one candidate.','strength':'verified by source and accepted saved candidates'},
        {'claim':'Recent operation reads deliberately discard conditional operations and focus on current gap families.','strength':'verified model action pattern'},
        {'claim':'Current-gap-focused inline context, absent direct efficiency feedback, and repeated one-task history favor reactive dispatch.','strength':'mechanism supported by source and inputs; contribution sizes require ablations'},
        {'claim':'conditional=true includes future/unready operations; it is not a feasibility prohibition.','strength':'verified observation builder semantics'},
        {'claim':'Past not_before checks increase explicit maintenance of pending queues across replans.','strength':'verified rule; not proven sole cause of model behavior'},
        {'claim':'Increasing only plan validity cannot fix missing queues on other resources.','strength':'supported by prior frequency audit'}],
    'source_sha256':sources,
    'no_counterfactual_savings_claim':True}
(OUT/'evidence.json').write_text(json.dumps({'summary':summary,'recent_calls':calls},ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False,indent=2))
