"""Re-execute DES from cold source data using saved decisions and boundary targets."""
import sys,json,hashlib,time,collections
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'experiment_round2_3datasets';OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from src.smt_fullfab.environment import FullFabEnvironment
paths={'A':'runs/smt_fullfab_development/A_1701_1h_hybrid_v1/trace.jsonl','B':'runs/smt_fullfab_stage2/B_1701_1h_delta_v15__authorized_extension_001/physical/trace.jsonl','C':'runs/smt_fullfab_stage2/C_1701_1h_constructive_v2/trace.jsonl'}
physical={'release','ready','skip','dispatch','downtime','operation_complete','rework','lot_complete','terminal'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def projection(events):return [{k:v for k,v in e.items() if k!='seq'} for e in events if e['kind'] in physical]
result={'scope':'Deterministic DES re-execution with saved plans and recorded stop targets; not fresh scheduling/model reproduction. Current shared environment is used.','new_model_calls':0,'new_solver_calls':0,'arms':{},'implementation_sha256':{str(p.relative_to(ROOT)):sha(p) for p in [ROOT/'src/smt_fullfab/environment.py',ROOT/'src/smt/environment.py']}}
for arm,path in paths.items():
 start=time.monotonic();events=[json.loads(x) for x in (ROOT/path).read_text().splitlines()];indices=[i for i,e in enumerate(events) if e['kind']=='plan_committed']
 env=FullFabEnvironment(seed=1701,window_seconds=3600,data_dir=ROOT/'data/smt/SMT2020_LVHM')
 status={'source_sha256':sha(ROOT/path),'saved_plans':len(indices),'replayed_plans':0}
 try:
  for n,i in enumerate(indices):
   event=events[i];end=indices[n+1] if n+1<len(indices) else len(events);last=events[end-1]
   if env.t!=event['time']:raise ValueError(f'plan {n} time {env.t} != {event["time"]}')
   env.commit_plan(event['plan'])
   target=3600 if last['kind'] in ('coverage_gap','plan_invalidated','terminal') else last['time']
   env.advance_plan(target);status['replayed_plans']+=1
  old,new=projection(events),projection(env.trace)
  diff=next((i for i,(a,b) in enumerate(zip(old,new)) if a!=b),None)
  status.update(simulation_seconds=env.t,finished=env.finished,saved_physical_events=len(old),replayed_physical_events=len(new),exact_physical_events_match=old==new,first_difference=diff)
  if diff is not None:status['difference']={'old':old[diff],'new':new[diff]}
 except Exception as exc:status['error']=str(exc)
 status['elapsed_seconds']=time.monotonic()-start;result['arms'][arm]=status
 (OUT/'DES_plan_reexecution.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(arm,json.dumps(status,ensure_ascii=False)[:1800],flush=True)
