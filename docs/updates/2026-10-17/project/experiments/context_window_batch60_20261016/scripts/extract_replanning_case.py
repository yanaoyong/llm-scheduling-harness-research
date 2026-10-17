"""Preserve a concrete already-planned-operation replan case from sealed evidence."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from src.smt_fullfab.harness.offline_isolation import install_guard
install_guard()
from src.smt_fullfab.harness.evaluation import Evidence
from src.smt_fullfab.harness.presentation import unpack
source=ROOT/'live_pilots/extended_three_group_capacity_retry_20261017';out=ROOT/'live_pilots/extended_three_group_completion_20261017'
r=json.loads((source/'G1.result.json').read_text());ev=Evidence(source/'G1',r['evidence_sha256']);target='w1462:131:1';when=1161.8061422329447
contexts=ev.rows('contexts');candidates=ev.rows('candidates');commits=[];calls=[]
for receipt in sorted(ev.rows('commits').values(),key=lambda r:r['time']):
 if not 1000<receipt['time']<1162:continue
 cand=candidates[receipt['candidate_ref']]
 for t in cand['compiled']['plan']['tasks']:
  if target in t['operation_ids']:commits.append({'time':receipt['time'],'commit_id':receipt['commit_id'],'task':t})
for a in sorted(ev.rows('attempts').values(),key=lambda a:a['index']):
 c=contexts[a['context_ref']]
 if abs(c['time']-when)>1e-7:continue
 ref=(a.get('transport') or {}).get('original_input_files',{}).get('prompt.txt')
 f=json.loads(ev.raw(ref).decode().rsplit('\n',1)[-1]);ops=[o for family in f['public_problem']['operation_groups'] for o in unpack(family['records'])]
 action=json.loads(ev.raw(a['raw_ref']));action=action.get('action',action)
 calls.append({'call_number':a['index']+1,'attempt_id':a['attempt_id'],'time':c['time'],'tool':action['tool'],
               'operation_details_inline':any(o['operation_id']==target for o in ops),
               'existing_task_inline':any(target in t['operation_ids'] for t in unpack(f['base_plan']['tasks'])),
               'context_ref':c['context_ref'],'prompt_ref':ref,'raw_output_ref':a['raw_ref']})
assert len(commits)==2 and [a['tool'] for a in calls]==['read_entities','propose_delta','apply_candidate']
assert calls[0]['existing_task_inline'] and not calls[0]['operation_details_inline']
value={'source_evidence':{'directory':str(source/'G1'),'sha256':r['evidence_sha256']},'operation':target,'commits':commits,'calls':calls,
       'interpretation':'An already assigned future task was re-read, moved and advanced by explicit model choice after it became ready earlier than its not_before. No harness task selection occurred.'}
(out/'already_planned_replan_case.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
print('Verified prior assignment, changed assignment, and all three actual model calls.')
