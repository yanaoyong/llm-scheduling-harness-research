"""Immutable read-only checkpoint; do not close, resume, or reset any run."""
from pathlib import Path
import sys,sqlite3,json,time,zlib
O=Path(__file__).resolve().parent;sys.path.insert(0,str(O/'workspace'))
from src.smt_fullfab.harness.contracts import encode,sha_bytes,require,strict_json
from src.smt_fullfab.harness.evaluation import Evidence,audit_provenance,audit_cost,audit_physical_prefix
reg=strict_json((O/'experiment.json').read_bytes());out=O/'interruption_evidence';out.mkdir(exist_ok=True);rows=[];failures=[]
for case in reg['execution_order']:
 p=O/'runs'/case;db=sqlite3.connect(f'file:{p}/events.sqlite3?mode=ro',uri=True);db.row_factory=sqlite3.Row;db.execute('BEGIN');records={}
 for r in db.execute('SELECT namespace,key,ref FROM records'):records.setdefault(r['namespace'],{})[r['key']]=r['ref']
 physical=[r[0] for r in db.execute('SELECT object_ref FROM physical ORDER BY seq')];head=strict_json(db.execute("SELECT value FROM metadata WHERE key='head'").fetchone()[0]);events=[dict(r) for r in db.execute('SELECT * FROM events ORDER BY seq')];db.close()
 boundary={'schema':'unsealed-readonly-checkpoint-v1','records':records,'head':head,'events':events,'physical':physical,'objects':sorted(f.stem for f in (p/'objects').glob('*.z')),'manifest_ref':records['manifest']['run'],'sealed_epoch':time.time(),'actually_sealed':False,'may_resume_only_under_explicit_recovery_policy':True}
 raw=encode(boundary);target=out/(case+'.checkpoint.json')
 require(not target.exists(),'immutable','Do not overwrite checkpoint');target.write_bytes(raw)
 e=Evidence.__new__(Evidence);e.path=p;e.allowed=set(boundary['objects']);e.cache={};e.value=boundary;e.sha256=sha_bytes(raw);e.manifest=e.get(boundary['manifest_ref'])
 for h in e.allowed:e.raw(h)
 trace=[e.get(h) for h in physical];attempts=list(e.rows('attempts').values());cost=audit_cost(e);provenance=audit_provenance(e,trace);phys=audit_physical_prefix(trace,head['time'],e.manifest['config']['priority_weights'])
 row={'case':case,'checkpoint':{'path':str(target.resolve()),'sha256':sha_bytes(raw)},'actual_model_calls':cost['actual_attempts'],'known_reported_tokens':cost['total_reported_tokens'],'unknown_usage':cost['unknown_usage'],'pending_attempts':cost['pending_attempts'],'start':e.manifest['start_time'],'end':head['time'],'advanced_seconds':head['time']-e.manifest['start_time'],'commits':len(e.rows('commits')),'checked_candidates':len(e.rows('candidates')),'provenance':provenance,'cost':cost,'physical_prefix_errors':[x for x in phys['errors'] if x!='physical: missing terminal event'],'unsealed':True}
 rows.append(row)
 for a in attempts:
  if a['channel']!='codex' or a['status'] in ('reserved','not_sent') or a.get('usage') is not None:continue
  t=a['transport'];guard=e.get(t['guard_ref']);docs={k:e.get(v) for k,v in t['original_guard_files'].items() if k.endswith('.json')};receipt=docs['receipt.json'];observed=docs['parent_observed.json'];stream=[strict_json(x) for x in e.raw(t['events_ref']).splitlines() if x.strip()]
  require(observed['wait_completed'] and receipt['command_returncode']==t['returncode']==1,'terminated','Exact original process must have terminated')
  require(not any(x.get('type')=='turn.completed' for x in stream),'usage','Do not ignore usage')
  require(not e.raw(a['raw_ref']),'output','No partial output may be treated as a valid action')
  failure={'case':case,'attempt_id':a['attempt_id'],'attempt_record_sha256':records['attempts'][a['attempt_id']],'prompt_sha256':a['prompt_ref'],'schema_sha256':a['schema_ref'],'raw_events_sha256':t['events_ref'],'guard_sha256':t['guard_ref'],'duration_seconds':a['duration_seconds'],'returncode':1,'parent_wait_completed':True,'guard_timed_out':t['timed_out'],'turn_completed':False,'model_output_bytes':0,'reported_usage':None,'errors':[x.get('message') or x.get('error',{}).get('message') for x in stream if x.get('type') in ('error','turn.failed')],'automatic_retries':0,'no_cost_imputation':True}
  failures.append(failure)
summary={'status':'frozen_after_terminated_stream_failure_with_unknown_usage','registration_sha256':sha_bytes((O/'experiment.json').read_bytes()),'created_epoch':time.time(),'rows':rows,'failures':failures,'total_model_calls':sum(r['actual_model_calls'] for r in rows),'known_reported_tokens_lower_bound':sum(r['known_reported_tokens'] for r in rows),'unknown_usage_calls':sum(r['unknown_usage'] for r in rows),'pending_attempts':sum(r['pending_attempts'] for r in rows),'complete_common_windows':0,'can_compare_total_efficiency':False,'can_conclude_quality_non_regression':False,'no_new_calls_after_failure':True,'all_objects_checked_by_sha256':True,'live_B_writer_or_process_actions':0}
(O/'interruption_audit.json').write_bytes(encode(summary));print(json.dumps({k:v for k,v in summary.items() if k!='rows'},ensure_ascii=False,indent=2))
