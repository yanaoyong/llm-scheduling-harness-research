"""Compare one actual continuation interval and an explicit past-start revision."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from src.smt_fullfab.harness.offline_isolation import install_guard
install_guard()
from src.smt_fullfab.harness.evaluation import Evidence
RUN=Path(sys.argv[1]).resolve();report=json.loads((RUN/'comparison.json').read_text());out={}
for g,r in report['results'].items():
 ev=Evidence(r['evidence_directory'],r['evidence_sha256']);candidates=ev.rows('candidates');contexts=ev.rows('contexts');target={'w421:149:1','w422:149:1'}
 advances=[{k:f[k] for k in ('from','to','dispatch_count_delta','stop_reason')} for f in ev.rows('feedback').values() if 1386<=f['from']<1448.7331921568093]
 commitments=[]
 for c in ev.rows('commits').values():
  if abs(c['time']-1386.1847539996988)>1e-7:continue
  tasks=[t for t in candidates[c['candidate_ref']]['compiled']['plan']['tasks'] if target.intersection(t['operation_ids'])]
  commitments.append({'commit_id':c['commit_id'],'tasks':tasks})
 calls=sorted(a['index']+1 for a in ev.rows('attempts').values() if 1386.1847539996988<contexts[a['context_ref']]['time']<1448.7331921568093 and a['channel']=='codex')
 dispatches=[]
 for ref in ev.value['physical']:
  event=ev.get(ref)
  if event['kind']!='dispatch' or not 1386.1847539996988<event['time']<1448.7331921568093:continue
  ids={f'{lot}:{step}:{visit}' for lot,step,visit in zip(event['lots'],event['steps'],event['visits'])}
  if ids.intersection(target):dispatches.append({'physical_ref':ref,'time':event['time'],'machine':event['machine'],'task_id':event.get('plan_task_id'),'operation_ids':sorted(ids)})
 assert {oid for d in dispatches for oid in d['operation_ids']}==target
 out[g]={'evidence_sha256':r['evidence_sha256'],'advances':advances,'future_tasks_in_commit_at_1386':commitments,'actual_target_dispatches':dispatches,'model_calls_between_boundaries':calls}
 if g=='G1':
  a=next(a for a in ev.rows('attempts').values() if a['index']==30)
  ref=a['transport']['original_input_files']['prompt.txt'];f=json.loads(ev.raw(ref).decode().rsplit('\n',1)[-1])
  out[g]['past_start_requirement']={'call_number':31,'prompt_ref':ref,'feedback':f['context']['pending_start_validation']}
assert out['G0']['model_calls_between_boundaries']==out['G1']['model_calls_between_boundaries']==[]
assert out['G2']['model_calls_between_boundaries']==[40,41,42,43]
(RUN/'execution_cases.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print('Verified automatic execution versus four extra calls, and the preserved past-start requirement.')
