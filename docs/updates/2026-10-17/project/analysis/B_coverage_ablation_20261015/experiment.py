"""Explicit isolated, paired, serial model experiment. Never opens live writer APIs."""
from pathlib import Path
from collections import Counter
import argparse, hashlib, json, sqlite3, sys, time, traceback, zlib
OUT=Path(__file__).resolve().parent; W=OUT/'workspace'; ROOT=OUT.parents[1]
sys.path.insert(0,str(W))
from src.smt_fullfab.harness.contracts import default_config,digest,encode,fingerprint,sha_bytes,strict_json,require,HarnessError
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness import transport
from src.smt_fullfab.harness.coverage_ablation import VARIANTS
from src.smt_fullfab.harness.evaluation import seal_evidence,Evidence,audit_provenance,audit_cost,audit_physical_prefix
from src.smt_fullfab.metrics import compute_metrics

def read(p):return strict_json(p.read_bytes())
def write(p,v):p.write_bytes(encode(v)+b'\n')
def ref(p):return {'path':str(p),'sha256':sha_bytes(p.read_bytes())}
def original_unchanged():
 old=read(OUT/'original_source_hashes.json')
 return all(sha_bytes((ROOT/'experiment_round2_3datasets'/p).read_bytes())==h for p,h in old.items())

def prepare():
 require(not (OUT/'experiment.json').exists(),'frozen','Do not replace experiment')
 require(original_unchanged(),'live_source','Original source changed')
 verification=read(OUT/'verification.json');require(verification['all_pass'],'tests','Regression failed')
 snapshot=read(ROOT/'analysis/replan_frequency_20261015/snapshot_index.json');source=Path(snapshot['run_directory'])
 def get(h):
  raw=zlib.decompress((source/'objects'/f'{h}.z').read_bytes());assert sha_bytes(raw)==h;return strict_json(raw)
 refs={(ns,k):h for ns,k,h in snapshot['records']}
 manifest=get(refs['manifest','run']);rows=read(ROOT/'analysis/replan_frequency_20261015/execution_intervals.json')
 batches=[get(h) for seq,kind,h,sha in snapshot['events'] if kind=='execution_batch']
 attempts={get(h)['attempt_id']:get(h) for ns,k,h in snapshot['records'] if ns=='attempts'}
 commits={get(h)['actual_revision']:get(h) for ns,k,h in snapshot['records'] if ns=='commits'}
 cases={};order=[]
 for state_id,when in [('mixed_702',702.0),('transition_1800',1800.0),('singleton_2403',2403.0)]:
  batch=next(b for b in batches if b['to']==when and b['advanced_seconds']>0)
  state=get(batch['after_state_ref']);trace=[get(h) for seq,h in snapshot['physical'] if seq<batch['event_end']]
  row=next(r for r in rows if r['from']==when)
  public=get(refs['contexts',row['context_ref']]);assert digest(state['plan'])==digest(public['base_plan'])
  # Exact saved model note from the prior accepted plan; tool working memory reset identically.
  previous=max((c for c in commits.values() if c['time']<when),key=lambda c:c['actual_revision'])
  action=get(attempts[previous['selection_attempt_id']]['raw_ref']);action=action.get('action',action)
  note={'version':1,'text':action.get('selection_note',''),'authority':'model_notes_only'}
  seed=[{k:r[k] for k in ('from','to','advanced_seconds','dispatch_count','completed_operations','calls','plan_task_count','max_machine_queue_depth','stop_reason')} for r in rows if r['to']<=when and r['ordinal']<row['ordinal']][-8:]
  initial={'state':state,'trace':trace,'period_anchor':manifest['period_anchor'],'evaluation_end':when+300,'parent':{'kind':'immutable_saved_live_B_prefix','run_id':manifest['run_id'],'state_ref':batch['after_state_ref'],'source_snapshot':ref(ROOT/'analysis/replan_frequency_20261015/snapshot_index.json'),'physical_prefix_count':len(trace)},'seed_notes':note,'seed_efficiency':seed}
  config=default_config(seconds=state['horizon']-when,seed=state['seed']);config['initialization']='registered_saved_state';config['model']=manifest['config']['model'];config['limits'].update(attempts=60,tokens=3000000,model_seconds=3600,wall_seconds=28800,cleanup_seconds=120)
  # All branches observe the original horizon; only the evaluator stops after 300 seconds.
  for variant in VARIANTS:
   case=state_id+'__'+variant
   (OUT/(case+'.initial.json.z')).write_bytes(zlib.compress(encode(initial),6));write(OUT/(case+'.config.json'),config)
   cases[case]={'group':'micro','state_id':state_id,'variant':variant,'initial_sha256':digest(initial),'initial_state_sha256':digest(state),'initial_trace_sha256':digest(trace),'config_sha256':digest(config),'evaluation_end':when+300,'start':when}
  write(OUT/(state_id+'.public_expected.json'),{'problem_sha256':digest(public['problem']),'base_plan_sha256':digest(public['base_plan']),'trigger':public['trigger']})
 # Rotate state/variant execution order, then run serially round robin (one action per case).
 for i,state in enumerate(['singleton_2403','mixed_702','transition_1800']):
  order.extend(state+'__'+VARIANTS[(j+i)%3] for j in range(3))
 live_reg=read(ROOT/'experiment_round2_3datasets/artifacts/harness_p5_astra_TUN_B_release/experiment.json')
 reg={'schema':'harness-coverage-ablation-v1','experiment_directory':str(OUT),'registered_epoch':time.time(),'states':['mixed_702','transition_1800','singleton_2403'],'cases':cases,'execution_order':order,'full_B_new_run_limit':0,'user_instruction':'那就先改提示词、默认上下文和效率反馈，用相同保存状态对比现状、只改提示词、提示词加上下文反馈这三组，看看能减少多少重排和模型调用，同时确认排程质量没有下降。不要影响当前正在跑的 B。','network_policy':'inherit_host_no_inspection_or_changes','verification':ref(OUT/'verification.json'),'fingerprint_sha256':fingerprint()['sha256'],'cli_binary':live_reg['cli_binary'],'cli_sha256':live_reg['cli_sha256'],'model_catalog':str(OUT/'model-catalog.json'),'model_catalog_sha256':sha_bytes((OUT/'model-catalog.json').read_bytes()),'model':config['model'],'caps':{g:{'attempts':540,'tokens':27000000,'model_seconds':21600,'wall_seconds':28800} for g in ['micro','B3600','combined']},'memory_policy':'same prior accepted selection_note; prior tool history and fact cache reset equally; seed efficiency is input only to combined variant','evaluation_policy':'Three identical private snapshots with identical trace/RNG/event queues. Original horizon remains 3600; evaluation cutoff 300 simulated seconds. Original period anchor retained. No model reseeding supported, one trajectory per cell. Incomplete/failed runs retained and never counted as savings. No automatic retries; unknown usage freezes cohort.','quality_policy':'Compare exact common 300 seconds: independent provenance and physical/opportunity checks; weighted tardiness, completed lots, completed production operations, ready queue area and production utilization. No quality success claim based only on fewer calls.'}
 require(reg['fingerprint_sha256']==verification['fingerprint_sha256'],'frozen','Source differs from tested version')
 require(sha_bytes(Path(reg['cli_binary']).read_bytes())==reg['cli_sha256'],'cli_changed','CLI differs from live B')
 write(OUT/'experiment.json',reg)
 print(json.dumps({'prepared':len(cases),'order':order,'model':reg['model'],'state_hashes':{k:v['initial_state_sha256'] for k,v in cases.items()}}),flush=True)

def admission(case):
 reg=read(OUT/'experiment.json')
 return {'experiment_directory':str(OUT),'experiment_sha256':sha_bytes((OUT/'experiment.json').read_bytes()),'group':'micro','case_id':case,'experiment_kind':reg['schema'],'cli_binary':reg['cli_binary'],'cli_sha256':reg['cli_sha256'],'model_catalog':reg['model_catalog'],'model_catalog_sha256':reg['model_catalog_sha256']}

def finish(case,r):
 start=r.manifest['start_time'];end=r.env.t;complete=abs(end-r.manifest['evaluation_end'])<1e-7
 feedback=[v for _,v in r.store.rows('feedback')]; attempts=[v for _,v in r.store.rows('attempts')];plans=[c['compiled']['plan'] for _,c in r.store.rows('candidates') if any(cm['candidate_ref']==c['candidate_ref'] for _,cm in r.store.rows('commits'))]
 if r.head['phase'] not in ('STOPPED','AUDITING'):r.stop('registered_evaluation_cutoff' if complete else 'incomplete_experiment')
 usage=r.usage();trace=r.env.trace
 # A time_advance records its start and target. At an event-free evaluation cut,
 # use an explicitly labelled analysis-only clock observation from the durable head.
 # Never append it to the physical store or fabricate a production/terminal event.
 metric_trace=trace
 clock_projection=None
 if trace[-1]['time'] < end:
  require(any(e['kind']=='time_advance' and e.get('to')==end for e in trace[-5:]),'evaluation_clock','Cutoff must be backed by the executed advance and durable head')
  clock_projection={'kind':'evaluation_observed_clock','time':end,'seq':len(trace),'source':'durable head and completed execution feedback; analysis view only'}
  metric_trace=trace+[clock_projection]
 metrics=compute_metrics(metric_trace,window_start=start,window_end=end,priority_weights=r.config['priority_weights']) if end>start else None
 physical=audit_physical_prefix(trace,end,r.config['priority_weights']);errors=[e for e in physical['errors'] if e!='physical: missing terminal event']
 sealed=seal_evidence(r);r.close(); evidence=Evidence(OUT/'runs'/case,sealed)
 try:provenance=audit_provenance(evidence,trace)
 except Exception as e:provenance={'valid':False,'error':str(e)}
 try:cost=audit_cost(evidence)
 except Exception as e:cost={'valid':False,'error':str(e)}
 result={'case':case,'complete_common_window':complete,'start':start,'end':end,'advanced_seconds':end-start,'replans':len(feedback),'stop_counts':dict(Counter(f['stop_reason']['reason'] for f in feedback)),'usage':usage,'plan_task_counts':[len(p['tasks']) for p in plans],'plan_max_queue_depths':[max(Counter(t['machine'] for t in p['tasks']).values(),default=0) for p in plans],'rejections':sum((evidence.get(a['response_ref']).get('status')=='rejected') for a in attempts if 'response_ref' in a),'metrics':metrics,'physical_audit':{'prefix_valid_except_expected_missing_terminal':not errors,'errors':errors,'expected_missing_terminal':True,'opportunity':physical['opportunity_audit']},'provenance':provenance,'cost':cost,'evidence_sha256':sealed,'completed_epoch':time.time(),'analysis_only_clock_projection':clock_projection}
 write(OUT/'runs'/case/'audit_closure.json',{'completed_epoch':result['completed_epoch'],'source':'isolated 300-second ablation audit, not full-run acceptance'})
 write(OUT/(case+'.result.json'),result)
 print(json.dumps({'completed_case':case,'complete':complete,'replans':len(feedback),'calls':usage['actual_model_attempts'],'physical_errors':errors,'provenance_valid':provenance.get('valid'),'cost_valid':cost.get('valid')},ensure_ascii=False),flush=True)
 return result

def run():
 reg=read(OUT/'experiment.json'); runtimes={};status={}
 try:
  for case in reg['execution_order']:
   if (OUT/(case+'.result.json')).exists():continue
   target=OUT/'runs'/case
   if target.exists():r=Runtime.resume_run(target)
   else:
    initial=strict_json(zlib.decompress((OUT/(case+'.initial.json.z')).read_bytes()));r=Runtime.start_new(target,read(OUT/(case+'.config.json')),experiment_id='coverage-ablation-20261015',mode='model',initial=initial,admission=admission(case))
    with r.store.transaction():
     r.store.record('notes','current',initial['seed_notes']);r.store.record('ablation_seed','efficiency',initial['seed_efficiency'])
    expected=read(OUT/(reg['cases'][case]['state_id']+'.public_expected.json'));full=r.store.read('contexts',r.head['context_ref']);require(digest(full['problem'])==expected['problem_sha256'] and digest(full['base_plan'])==expected['base_plan_sha256'] and full['trigger']==expected['trigger'],'initial_public','Saved public observations differ')
   runtimes[case]=r
   # Render all variants before spending calls; capacity/public-only checks must pass.
   if r.head['context_ref'] and not (OUT/(case+'.first_prompt.txt')).exists():
    text=transport.prompt(r);write(OUT/(case+'.first_prompt_check.json'),{'chars':len(text),'sha256':sha_bytes(text.encode()),'has_coverage':'factory_coverage' in text,'has_efficiency':'execution_efficiency' in text});(OUT/(case+'.first_prompt.txt')).write_text(text)
  while runtimes:
   for case in list(runtimes):
    r=runtimes[case]
    if r.env.t>=r.manifest['evaluation_end'] or r.head['phase'] in ('STOPPED','AUDITING'):
     finish(case,r);del runtimes[case];continue
    try:
     if r.head['phase']=='COMMITTED': result=r.advance()
     else:result=transport.call(r)
    except HarnessError as exc:
     if exc.code in ('attempt_budget','token_budget','time_budget','wall_budget','storage_budget'):
      r.stop(exc.code);finish(case,r);del runtimes[case];continue
     raise
    if r.head['phase']=='COMMITTED':
     f=r.advance();result={**result,'advance_seconds':f['advanced_seconds'],'stop_reason':f['stop_reason']['reason']}
    u=r.usage();status[case]={'time':r.env.t,'start':r.manifest['start_time'],'phase':r.head['phase'],'calls':u['actual_model_attempts'],'replans':len(r.store.rows('feedback')),'status':result.get('status'),'unknown_usage':u['unknown_usage']}
    write(OUT/'progress.json',{'updated_epoch':time.time(),'cases':status,'live_original_sources_unchanged':original_unchanged()})
    print(json.dumps({'case':case,**status[case],**{k:result[k] for k in ['advance_seconds','stop_reason'] if k in result}},ensure_ascii=False),flush=True)
    if u['unknown_usage']:raise RuntimeError('Unknown usage freezes cohort; preserve failure, do not retry or switch model')
 except BaseException as exc:
  write(OUT/'interruption.json',{'epoch':time.time(),'error':str(exc),'traceback':traceback.format_exc(),'active_cases':list(runtimes),'live_original_sources_unchanged':original_unchanged()});raise
 finally:
  for r in runtimes.values():r.close()
if __name__=='__main__':
 command=sys.argv[1]
 if command=='prepare':prepare()
 elif command=='run':run()
