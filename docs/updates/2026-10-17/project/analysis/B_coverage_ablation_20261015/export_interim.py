"""Read-only terminal checkpoint for an interrupted cohort. No case is sealed or reset."""
from pathlib import Path
from collections import Counter
import sys,json,sqlite3,time,hashlib
O=Path(__file__).resolve().parent;sys.path.insert(0,str(O/'workspace'))
from src.smt_fullfab.harness.evaluation import Evidence,audit_provenance,audit_cost,audit_physical_prefix
from src.smt_fullfab.metrics import compute_metrics
reg=json.loads((O/'experiment.json').read_text());rows=[]
for case,registered in reg['cases'].items():
 p=O/'runs'/case;c=sqlite3.connect(f'file:{p}/events.sqlite3?mode=ro',uri=True);c.execute('BEGIN');records={}
 for ns,k,h in c.execute('select namespace,key,ref from records'):records.setdefault(ns,{})[k]=h
 physical=[h for h, in c.execute('select object_ref from physical order by seq')];head=json.loads(c.execute("select value from metadata where key='head'").fetchone()[0]);c.close()
 e=Evidence.__new__(Evidence);e.path=p;e.allowed={f.stem for f in (p/'objects').glob('*.z')};e.cache={};e.value={'records':records,'head':head,'sealed_epoch':time.time()};e.manifest=e.get(records['manifest']['run']);trace=[e.get(h) for h in physical]
 start=e.manifest['start_time'];end=head['time'];attempts=list(e.rows('attempts').values());known=[a for a in attempts if a.get('usage') is not None];feedback=list(e.rows('feedback').values());tools=Counter()
 for a in attempts:
  if not a.get('raw_ref'):continue
  try:v=e.get(a['raw_ref']);v=v.get('action',v);tools[v.get('tool','unparsed')]+=1
  except (ValueError,AttributeError):tools['no_valid_action']+=1
 plans=[e.rows('candidates')[cm['candidate_ref']]['compiled']['plan'] for cm in e.rows('commits').values()]
 phys=audit_physical_prefix(trace,end,e.manifest['config']['priority_weights']);metrics=None
 if end>start:
  view=trace if trace[-1]['time']==end else trace+[{'kind':'evaluation_observed_clock','time':end,'seq':len(trace)}]
  m=compute_metrics(view,window_start=start,window_end=end,priority_weights=e.manifest['config']['priority_weights']);jobs={x['job']:x['machine'] for x in trace if x['kind']=='dispatch'};prod={m['id'] for m in trace[0]['manifest']['machines'] if m['group']!='Delay_32'}
  metrics={k:m[k] for k in ['weighted_tardy_lot_seconds','throughput_lots']};metrics['production_operation_lots_completed']=sum(x['kind']=='operation_complete' and start<x['time']<=end and jobs.get(x.get('job')) in prod for x in trace);metrics['ready_wait_lot_seconds']=sum(f['queue_wait_lot_seconds'] for f in m['production_family_statistics'].values())
 row={'case':case,'state':registered['state_id'],'variant':registered['variant'],'phase':head['phase'],'start':start,'end':end,'advanced_seconds':end-start,'complete_common_window':abs(end-registered['evaluation_end'])<1e-7,'model_calls':len(attempts),'known_usage_calls':len(known),'unknown_usage_calls':sum(a.get('usage') is None for a in attempts),'known_reported_tokens':sum(a['usage']['input_tokens']+a['usage']['output_tokens'] for a in known),'model_seconds':sum(a.get('duration_seconds',0) for a in attempts),'replans':len(feedback),'tool_calls':dict(tools),'plan_task_counts':[len(p['tasks']) for p in plans],'plan_max_machine_queue_depths':[max(Counter(t['machine'] for t in p['tasks']).values(),default=0) for p in plans],'rejections':sum(e.get(a['response_ref']).get('status')=='rejected' for a in attempts if a.get('response_ref')),'metrics_for_own_prefix_only':metrics,'provenance':audit_provenance(e,trace),'cost':audit_cost(e),'physical_errors_without_expected_missing_terminal':[v for v in phys['errors'] if v!='physical: missing terminal event'],'physical_opportunity_valid':phys['opportunity_audit'].get('valid'),'head_state_sha256':head['state_ref'],'provisional_readonly_unsealed':True}
 rows.append(row)
orig=O.parents[1]/'experiment_round2_3datasets';hashes=json.loads((O/'original_source_hashes.json').read_text())
result={'status':'interrupted_unknown_usage_freeze','exported_epoch':time.time(),'no_new_calls_after_failure':True,'error':'Connection failed: error sending request','failed_attempt':'attempt:d3a356bbf9fd4b80bb8cce02','total_model_calls':sum(r['model_calls'] for r in rows),'known_usage_calls':sum(r['known_usage_calls'] for r in rows),'unknown_usage_calls':sum(r['unknown_usage_calls'] for r in rows),'known_reported_tokens_lower_bound':sum(r['known_reported_tokens'] for r in rows),'complete_300_second_windows':sum(r['complete_common_window'] for r in rows),'rows':rows,'valid_paired_comparisons':[],'call_savings_conclusion':None,'quality_non_regression_conclusion':None,'original_B_source_unchanged':all(hashlib.sha256((orig/p).read_bytes()).hexdigest()==h for p,h in hashes.items()),'interpretation':'No complete common window. Zero replans in unadvanced branches is not a saving. Prefix metrics have different durations and must not be compared as quality outcomes. One failed call has unknown usage; known token sum is only a lower bound. Exact saved states and accounts remain unsealed for an explicit recovery decision, never silently restarted.'}
(O/'interim_snapshot.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False,indent=2))
