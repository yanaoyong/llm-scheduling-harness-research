"""If needed, finish capped trajectories at the unchanged 1800-second target."""
from pathlib import Path
import sys,json,shutil,time,tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from src.smt_fullfab.harness.contracts import digest,fingerprint,sha_bytes,strict_json,require
from src.smt_fullfab.harness.evaluation import Evidence,seal_evidence,audit_provenance,audit_cost
from src.smt_fullfab.harness.transport import call
from src.smt_fullfab.harness import capacity_pilot as pilot
from run_extended_three_group_pilot import outcome,write,isolation
from extended_resource_final_segment import branch,audit
from extended_lineage_audit import verify_inheritance
BASE=ROOT/'live_pilots/extended_three_group_completion_20261017'
RUN=ROOT/'live_pilots/extended_three_group_final_segment_20261017'

def admission(g,reg,root=RUN):
 return {'schema':pilot.SCHEMA,'group':g,'experiment_directory':str(root),'experiment_sha256':digest(reg),
         **{k:reg[k] for k in ('cli_binary','cli_sha256','model_catalog','model_catalog_sha256')}}

def prepare():
 from src.smt_fullfab.harness.offline_isolation import install_guard
 install_guard();RUN.mkdir(exist_ok=False)
 reg=strict_json((BASE/'registration.json').read_bytes());parents={};configs={};active=[];completed={}
 for g in reg['groups']:
  r=strict_json((BASE/(g+'.result.json')).read_bytes());ev=Evidence(BASE/g,r['evidence_sha256'])
  parents[g]={'directory':str(BASE/g),'evidence_sha256':ev.sha256}
  if r['head']['time']>=1800:completed[g]={**r,'evidence_directory':str(BASE/g)}
  else:
   require(ev.value['head']['stop_reason']=='pilot_attempt_cap','final_segment','A further unknown failure is not authorized for recovery')
   active.append(g)
  cfg=strict_json((BASE/(g+'.config.json')).read_bytes())
  cfg['limits'].update(attempts=96,tokens=46000000,model_seconds=23040,wall_seconds=int(time.time()-ev.manifest['created_epoch'])+10800)
  configs[g]=cfg;write(RUN/(g+'.config.json'),cfg);shutil.copyfile(BASE/(g+'.initial_backlog.json'),RUN/(g+'.initial_backlog.json'))
 require(bool(active),'final_segment','No unfinished trajectory needs continuation')
 for filename in ('model-catalog.json','outbound_verification.json','already_planned_replan_case.json'):
  shutil.copyfile(BASE/filename,RUN/filename)
 reg.update(experiment_directory=str(RUN),model_catalog=str(RUN/'model-catalog.json'),
    config_sha256={g:digest(c) for g,c in configs.items()},fingerprint_sha256=fingerprint()['sha256'],
    per_group_call_cap=96,model_calls_maximum_total=288,max_new_calls_total=32*len(active),
    task=reg['task'].replace('64 cumulative calls','96 cumulative calls'),
    resource_continuation={'from_cap':64,'to_cap':96,'predecessors':parents,'target_unchanged':1800,
        'reason':'Continue only capped trajectories that have not reached the unchanged shared observation endpoint.'},
    groups_needing_continuation=active,already_completed_results=completed,
    script_sha256=sha_bytes(Path(__file__).read_bytes()),runner_name=Path(__file__).name,
    final_resource_support_sha256=sha_bytes((ROOT/'scripts/extended_resource_final_segment.py').read_bytes()),
    lineage_audit_sha256=sha_bytes((ROOT/'scripts/extended_lineage_audit.py').read_bytes()),
    execution_order='Round robin unfinished groups; finished trajectories remain sealed and incur no further calls',
    isolation_before=isolation(),prepared_epoch=time.time())
 write(RUN/'registration.json',reg);checks={}
 with tempfile.TemporaryDirectory(dir=ROOT/'live_pilots',prefix='offline_final_segment_') as d:
  root=Path(d);test=dict(reg);test['experiment_directory']=str(root);write(root/'registration.json',test)
  for g in active:
   rt=branch(root/g,g,test,configs[g],admission(g,test,root))
   try:
    before=rt.usage();rt.check_admission(actual=True,reserve=configs[g]['capacity_experiment']['input_token_budget']+32768)
    assert rt.usage()['actual_model_attempts']==before['actual_model_attempts']==64
    rt.stop('offline_final_segment_check');sha=seal_evidence(rt)
   finally:rt.close()
   ev=Evidence(root/g,sha);trace=[ev.get(ref) for ref in ev.value['physical']];proof=audit(ev);lineage=verify_inheritance(ev)
   production=audit_provenance(ev,trace);cost=audit_cost(ev)
   assert production['valid'] and production['algorithm_production_tasks']==0 and cost['unknown_usage']==(1 if g=='G1' else 0)
   checks[g]={'resource':proof,'inheritance':lineage,'production':production,'cost':cost,'new_model_calls':0}
   print(json.dumps({'event':'offline_pass','group':g,'calls_retained':64,'new_calls':0}),flush=True)
 write(RUN/'offline_validation.json',{'all_pass':True,'groups':checks,'no_model_calls':True,'completed_groups_not_restarted':list(completed),'original_B_unchanged':isolation()['valid']})
 print(json.dumps({'event':'prepared','active':active,'finished':list(completed),'target':1800}),flush=True)

def run():
 reg=strict_json((RUN/'registration.json').read_bytes());require(fingerprint()['sha256']==reg['fingerprint_sha256'],'final_source','Source changed')
 for p,k in [(Path(__file__),'script_sha256'),(ROOT/'scripts/extended_resource_final_segment.py','final_resource_support_sha256'),(ROOT/'scripts/extended_lineage_audit.py','lineage_audit_sha256')]:
  require(sha_bytes(p.read_bytes())==reg[k],'final_source','Runner or helper changed')
 runtimes={}
 try:
  for g,r in reg['already_completed_results'].items():write(RUN/(g+'.result.json'),r)
  for g in reg['groups_needing_continuation']:
   cfg=strict_json((RUN/(g+'.config.json')).read_bytes());runtimes[g]=branch(RUN/g,g,reg,cfg,admission(g,reg))
  for _ in range(32):
   for g,rt in runtimes.items():
    if rt.head['phase'] in ('STOPPED','CLOSED','AUDITING'):continue
    print(json.dumps({'event':'call_start','group':g,'call_number':rt.usage()['actual_model_attempts']+1,'time':rt.env.t}),flush=True)
    try:
     result=call(rt,task=reg['task']);print(json.dumps({'event':'call_end','group':g,'status':result.get('status'),'error':result.get('error'),'usage':rt.usage()}),flush=True)
     if rt.head['phase']=='COMMITTED':
      f=rt.advance();print(json.dumps({'event':'advance','group':g,'from':f['from'],'to':f['to'],'dispatches':f['dispatch_count_delta'],'reason':f['stop_reason']['reason']}),flush=True)
     if rt.env.t>=1800 and rt.head['phase'] not in ('STOPPED','AUDITING'):rt.stop('pilot_evaluation_end')
    except Exception as exc:
     write(RUN/(g+'.failure.json'),{'type':type(exc).__name__,'detail':str(exc)})
     if rt.head['phase'] not in ('STOPPED','CLOSED'):rt.stop('final_exception:'+type(exc).__name__)
     print(json.dumps({'event':'group_stopped','group':g,'error':str(exc)}),flush=True)
    write(RUN/(g+'.progress.json'),outcome(rt))
  for g,rt in runtimes.items():
   if rt.head['phase'] not in ('STOPPED','AUDITING'):rt.stop('pilot_attempt_cap')
   result=outcome(rt);result['evidence_sha256']=seal_evidence(rt);write(RUN/(g+'.result.json'),result)
 finally:
  for rt in runtimes.values():rt.close()
 print(json.dumps({'event':'complete','isolation':isolation()}),flush=True)
if __name__=='__main__':{'prepare':prepare,'run':run}[sys.argv[1]]()
