"""Read-only trace evidence for plan coverage and rejected model actions."""
from pathlib import Path
from collections import Counter
import sqlite3,zlib,json,hashlib
O=Path(__file__).resolve().parent;reg=json.loads((O/'experiment.json').read_text());out=[]
for case in reg['execution_order']:
 p=O/'runs'/case;db=sqlite3.connect(f'file:{p}/events.sqlite3?mode=ro',uri=True);db.execute('BEGIN')
 def get(h):
  data=zlib.decompress((p/'objects'/(h+'.z')).read_bytes());assert hashlib.sha256(data).hexdigest()==h;return json.loads(data)
 def records(ns):return {k:get(h) for k,h in db.execute('SELECT key,ref FROM records WHERE namespace=? ORDER BY rowid',(ns,))}
 attempts=sorted(records('attempts').values(),key=lambda a:a['index']);candidates=records('candidates');commits=records('commits');errors=[];proposals=[]
 for a in attempts:
  if a['status']!='processed':continue
  try:action=get(a['raw_ref']);action=action.get('action',action)
  except ValueError:continue
  response=get(a['response_ref'])
  if action.get('tool')=='propose_delta':
   d=action['delta'];scope=d['plan_header']['scope'];duplicates=[k for k,v in Counter(scope).items() if v>1]
   proposals.append({'attempt':a['index']+1,'attempt_id':a['attempt_id'],'response_status':response.get('status'),'scope_length':len(scope),'scope_unique':len(set(scope)),'scope_duplicate_ids':duplicates,'new_task_count':len(d['tasks']['add']),'pending_keep':d['tasks']['keep'],'cancel_ids':d['tasks']['cancel_ids'],'replaced_task_count':len(d['tasks']['replace']),'candidate_ref':response.get('candidate_ref')})
  if response.get('status')=='rejected':errors.append({'attempt':a['index']+1,'attempt_id':a['attempt_id'],'tool':action.get('tool'),'error':response.get('error'),'raw_action_sha256':a['raw_ref']})
 chosen=[]
 for c in commits.values():
  candidate=candidates[c['candidate_ref']];plan=candidate['compiled']['plan'];chosen.append({'candidate_ref':c['candidate_ref'],'plan_created_at':plan['created_at'],'valid_until':plan['valid_until'],'tasks':[{'id':t['id'],'machine':t['machine'],'operation_ids':t['operation_ids'],'not_before':t['not_before']} for t in plan['tasks']]})
 feedback=list(records('feedback').values())
 out.append({'case':case,'variant':reg['cases'][case]['variant'],'proposal_actions':proposals,'business_rejections':errors,'committed_plans':chosen,'execution_segments':[{'advanced_seconds':f['advanced_seconds'],'stop_reason':f['stop_reason']} for f in feedback]});db.close()
(O/'behavior_diagnostics.json').write_text(json.dumps({'cases':out,'note':'Plan totals may include carried pending tasks. proposal_actions.new_task_count counts newly added tasks; rejected actions never imply physical execution.'},ensure_ascii=False,indent=2)+'\n')
print([(x['variant'],len(x['committed_plans']),len(x['business_rejections'])) for x in out])
