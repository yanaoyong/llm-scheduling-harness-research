"""Explicit isolated, paired, serial model experiment. Never opens live writer APIs."""
from pathlib import Path
from collections import Counter
import argparse, hashlib, json, sqlite3, sys, time, traceback, zlib
OUT=Path(__file__).resolve().parent; W=OUT/'workspace'; ROOT=OUT.parents[1]
sys.path.insert(0,str(W))
from src.smt_fullfab.harness.contracts import default_config,digest,encode,fingerprint,sha_bytes,strict_json,require,HarnessError
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness import transport
from src.smt_fullfab.harness.context_ablation import VARIANTS, SCHEMA, OFFLOAD_CHARS
from src.smt_fullfab.harness.evaluation import seal_evidence,Evidence,audit_provenance,audit_cost,audit_physical_prefix
from src.smt_fullfab.metrics import compute_metrics

def read(p):return strict_json(p.read_bytes())
def write(p,v):p.write_bytes(encode(v)+b'\n')
def ref(p):return {'path':str(p),'sha256':sha_bytes(p.read_bytes())}
def original_unchanged():
 manifest=read(OUT/'source_baseline_manifest.json');source=Path(manifest['source'])
 return all(sha_bytes((source/p).read_bytes())==h for p,h in manifest['files'].items())

def prepare():
 require(not (OUT/'experiment.json').exists(),'frozen','Do not replace experiment')
 require(original_unchanged(),'isolated_source','Prior isolated source changed')
 proof=read(OUT/'verification.json');require(proof['all_pass'] and proof['source_unchanged_during_tests'],'tests','Regression failed or environment changed')
 integration=read(OUT/'integration_preflight.json');require(integration['all_pass'] and integration['source_unchanged'] and integration['fingerprint_sha256']==proof['fingerprint_sha256'],'tests','End-to-end restoration preflight differs')
 initial=strict_json(zlib.decompress((OUT/'singleton_2403__baseline.initial.json.z').read_bytes()))
 config=read(OUT/'singleton_2403__baseline.config.json');cases={};order=[]
 for variant in VARIANTS:
  case='singleton_2403__'+variant
  if variant!='baseline':
   (OUT/(case+'.initial.json.z')).write_bytes((OUT/'singleton_2403__baseline.initial.json.z').read_bytes())
   write(OUT/(case+'.config.json'),config)
  cases[case]={'group':'micro','state_id':'singleton_2403','variant':variant,'initial_sha256':digest(initial),'initial_state_sha256':digest(initial['state']),'initial_trace_sha256':digest(initial['trace']),'config_sha256':digest(config),'evaluation_end':initial['evaluation_end'],'start':2403.0}
  order.append(case)
 prior=read(OUT.parent/'B_coverage_ablation_20261015'/'experiment.json')
 caps={'attempts':240,'tokens':12000000,'model_seconds':14400,'wall_seconds':28800}
 reg={'schema':SCHEMA,'python_executable':sys.executable,'bytecode_writes_disabled':bool(sys.dont_write_bytecode),'experiment_directory':str(OUT),'registered_epoch':time.time(),'states':['singleton_2403'],'cases':cases,'execution_order':order,'full_B_new_run_limit':0,'user_instruction':'那就在隔离副本里实现并对比这两种方案，用同一保存状态跑现状、只改过滤投影、只改定向恢复、两者结合四组，其他条件保持一致，比较总调用、token、首次提案时间和排程质量，不要影响正在跑的 B。','network_policy':'inherit_host_no_inspection_or_changes','verification':ref(OUT/'verification.json'),'integration_preflight':ref(OUT/'integration_preflight.json'),'fingerprint_sha256':fingerprint()['sha256'],'cli_binary':prior['cli_binary'],'cli_sha256':sha_bytes(Path(prior['cli_binary']).read_bytes()),'prior_cli_sha256':prior['cli_sha256'],'model_catalog':str(OUT/'model-catalog.json'),'model_catalog_sha256':sha_bytes((OUT/'model-catalog.json').read_bytes()),'model':config['model'],'caps':{g:caps.copy() for g in ['micro','B3600','combined']},'prior_experiment_status':ref(OUT/'prior_experiment_status.json'),'memory_policy':'Identical prior accepted selection_note; tool history and fact cache reset equally. Original fact_memory.py and two-read threshold unchanged. No efficiency feedback and no coverage guidance in any arm.','treatment_policy':{'filter_projection':'Add model-selected numeric/set predicates; preserve all selected business values, entity IDs, source order, absent fields, paging coverage. Move repeated row provenance metadata to unchanged full tool-result artifact.','targeted_recovery':'After normal lossless packing exceeds '+str(OFFLOAD_CHARS)+' characters, retain original artifact and publish exact path index with bounded original-order preview. Add explicit current public facts locator and 1..32 batched exact-path field recovery. No extra summarizing model.','interaction':'Filtering/projection runs before offload threshold. Tool schema/descriptors are treatment differences; scheduling protocol text, original preview selection, cap, fact-memory gate and physical engine are identical.'},'evaluation_policy':'Same saved private state, trace/RNG/event queues and config; t=2403 to2703, original horizon3600 and period anchor unchanged. Serial round-robin one model action per arm. One unseeded model trajectory per cell. Equal per-arm60calls/3Mtokens/3600modelseconds/600secondspercall. Incomplete or failed arms not counted as savings. No automatic retries; new unknown usage freezes this cohort.','first_proposal_policy':'Report first propose_delta/finalize attempt and first successful candidate_checked separately. Sum per-arm model duration through event; also report per-arm attempt and reported tokens through event. Wall timestamps include round-robin waiting and are not model latency.','quality_policy':'Compare complete common300seconds only: independently audit provenance, raw usage, physical prefix/opportunity; weighted tardiness, completed lots/production operations, ready queue area and production utilization. Short pilot cannot establish statistical noninferiority; require longer replicated experiments for deployment.'}
 require(reg['fingerprint_sha256']==proof['fingerprint_sha256'],'frozen','Source differs from tested version')
 write(OUT/'experiment.json',reg)
 print(json.dumps({'prepared':4,'order':order,'model':reg['model'],'cli_matches_prior':reg['cli_sha256']==reg['prior_cli_sha256'],'per_arm_limits':config['limits'],'fingerprint_sha256':reg['fingerprint_sha256']}),flush=True)

def admission(case):
 reg=read(OUT/'experiment.json')
 return {'experiment_directory':str(OUT),'experiment_sha256':sha_bytes((OUT/'experiment.json').read_bytes()),'group':'micro','case_id':case,'experiment_kind':reg['schema'],'cli_binary':reg['cli_binary'],'cli_sha256':reg['cli_sha256'],'model_catalog':reg['model_catalog'],'model_catalog_sha256':reg['model_catalog_sha256']}

def finish(case,r):
 start=r.manifest['start_time'];end=r.env.t;complete=abs(end-r.manifest['evaluation_end'])<1e-7
 feedback=[v for _,v in r.store.rows('feedback')]; attempts=[v for _,v in r.store.rows('attempts')];plans=[c['compiled']['plan'] for _,c in r.store.rows('candidates') if any(cm['candidate_ref']==c['candidate_ref'] for _,cm in r.store.rows('commits'))]
 if r.head['phase'] not in ('STOPPED','AUDITING'):r.stop('registered_evaluation_cutoff' if complete else 'incomplete_experiment')
 milestones={};action_counts=Counter();seconds=0.0;calls=0;tokens=0;unknown=0
 for attempt in attempts:
  if attempt['channel']!='codex' or attempt['status'] in ('reserved','not_sent'):continue
  calls+=1;seconds+=attempt.get('duration_seconds',0)
  u=attempt.get('usage');tokens+=(u['input_tokens']+u['output_tokens']) if u else 0;unknown+=u is None
  try:
   action=r.store.get(attempt['raw_ref']);action=action.get('action',action);tool=action.get('tool','invalid')
  except Exception:tool='invalid'
  action_counts[tool]+=1
  point={'attempt_id':attempt['attempt_id'],'calls':calls,'model_seconds':seconds,'reported_tokens':tokens,'unknown_usage':unknown}
  if tool in ('propose_delta','finalize_proposal') and 'first_proposal' not in milestones:milestones['first_proposal']=point.copy()
  response=r.store.get(attempt['response_ref']) if 'response_ref' in attempt else {}
  if response.get('status')=='candidate_checked' and 'first_checked_proposal' not in milestones:milestones['first_checked_proposal']=point.copy()
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
 from src.smt_fullfab.harness.recovery import validate_recoveries
 recovery_rows=validate_recoveries(evidence)
 # The strict audit remains false for unknown usage; this separate field only recognizes the approved, proven missing telemetry.
 reg_limits=evidence.manifest['config']['limits']
 known_accounting_verified='error' not in cost and cost.get('pending_attempts')==0 and cost.get('unknown_usage')==len(recovery_rows) and cost.get('classical_unknown')==0 and usage['actual_model_attempts']<=reg_limits['attempts'] and usage['input_tokens']+usage['output_tokens']<=reg_limits['tokens'] and usage['model_seconds']<=reg_limits['model_seconds'] and cost.get('experiment_through_seal_wall_seconds',float('inf'))<=reg_limits['wall_seconds']
 result={'case':case,'known_accounting_verified_with_authorized_unknown':known_accounting_verified,'authorized_recovery_count':len(recovery_rows),'recovery_records':recovery_rows,'milestones':milestones,'action_counts':dict(action_counts),'complete_common_window':complete,'start':start,'end':end,'advanced_seconds':end-start,'replans':len(feedback),'stop_counts':dict(Counter(f['stop_reason']['reason'] for f in feedback)),'usage':usage,'plan_task_counts':[len(p['tasks']) for p in plans],'plan_max_queue_depths':[max(Counter(t['machine'] for t in p['tasks']).values(),default=0) for p in plans],'rejections':sum((evidence.get(a['response_ref']).get('status')=='rejected') for a in attempts if 'response_ref' in a),'metrics':metrics,'physical_audit':{'prefix_valid_except_expected_missing_terminal':not errors,'errors':errors,'expected_missing_terminal':True,'opportunity':physical['opportunity_audit']},'provenance':provenance,'cost':cost,'evidence_sha256':sealed,'completed_epoch':time.time(),'analysis_only_clock_projection':clock_projection}
 write(OUT/'runs'/case/'audit_closure.json',{'completed_epoch':result['completed_epoch'],'source':'isolated context 2x2 300-second audit, not full-run acceptance','evidence_sha256':sealed})
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
    initial=strict_json(zlib.decompress((OUT/(case+'.initial.json.z')).read_bytes()));r=Runtime.start_new(target,read(OUT/(case+'.config.json')),experiment_id='context-2x2-20261016',mode='model',initial=initial,admission=admission(case))
    with r.store.transaction():
     r.store.record('notes','current',initial['seed_notes'])
    expected=read(OUT/(reg['cases'][case]['state_id']+'.public_expected.json'));full=r.store.read('contexts',r.head['context_ref']);require(digest(full['problem'])==expected['problem_sha256'] and digest(full['base_plan'])==expected['base_plan_sha256'] and full['trigger']==expected['trigger'],'initial_public','Saved public observations differ')
   from src.smt_fullfab.harness.context_recovery import activate
   activate(r)
   runtimes[case]=r
   # Render all variants before spending calls; capacity/public-only checks must pass.
   if r.head['context_ref'] and not (OUT/(case+'.first_prompt.txt')).exists():
    text=transport.prompt(r);write(OUT/(case+'.first_prompt_check.json'),{'chars':len(text),'sha256':sha_bytes(text.encode()),'has_filter_extension':'query_extensions' in text,'has_exact_recovery':'exact_recovery' in text});(OUT/(case+'.first_prompt.txt')).write_text(text)
  if (OUT/'recovery_amendment.json').exists() and runtimes:
   latest=[]
   for case,r in runtimes.items():
    for _,a in r.store.rows('attempts'):
     if a['channel']=='codex' and a['status'] not in ('reserved','not_sent'):latest.append((a.get('started_epoch',a['reserved_epoch']),case,a))
   if latest:
    _,last_case,last=max(latest,key=lambda x:x[0]);order=reg['execution_order'];offset=(order.index(last_case)+(0 if last.get('usage') is None else 1))%len(order)
    order=order[offset:]+order[:offset];runtimes={case:runtimes[case] for case in order if case in runtimes}
    write(OUT/'continuation_order.json',{'order':list(runtimes),'after_attempt':last['attempt_id'],'retry_first':last.get('usage') is None,'epoch':time.time()})
  while runtimes:
   for case in list(runtimes):
    r=runtimes[case]
    if r.env.t>=r.manifest['evaluation_end'] or r.head['phase'] in ('STOPPED','AUDITING'):
     finish(case,r);del runtimes[case];continue
    try:
     if r.head['phase']=='COMMITTED': result=r.advance()
     else:result=transport.call(r)
    except HarnessError as exc:
     if exc.code in ('attempt_budget','token_budget','time_budget','wall_budget','storage_budget','experiment_budget','experiment_time'):
      # Preserve resumable accounts; the user's completion grant permits a separately audited equal budget extension.
      raise
     raise
    if r.head['phase']=='COMMITTED':
     f=r.advance();result={**result,'advance_seconds':f['advanced_seconds'],'stop_reason':f['stop_reason']['reason']}
    u=r.usage();status[case]={'time':r.env.t,'start':r.manifest['start_time'],'phase':r.head['phase'],'calls':u['actual_model_attempts'],'replans':len(r.store.rows('feedback')),'status':result.get('status'),'unknown_usage':u['unknown_usage']}
    write(OUT/'progress.json',{'updated_epoch':time.time(),'cases':status,'prior_isolated_sources_unchanged':original_unchanged()})
    print(json.dumps({'case':case,**status[case],**{k:result[k] for k in ['advance_seconds','stop_reason'] if k in result}},ensure_ascii=False),flush=True)
    if u['unknown_usage']:
     from src.smt_fullfab.harness.recovery import current_recoveries
     if u['unknown_usage']!=len(current_recoveries(r)):raise RuntimeError('Unexempt unknown usage freezes cohort; preserve all failures and budgets')
 except BaseException as exc:
  write(OUT/'interruption.json',{'epoch':time.time(),'error':str(exc),'traceback':traceback.format_exc(),'active_cases':list(runtimes),'prior_isolated_sources_unchanged':original_unchanged()});raise
 finally:
  for r in runtimes.values():r.close()
if __name__=='__main__':
 command=sys.argv[1]
 if command=='prepare':prepare()
 elif command=='run':run()
