"""Read-only check that scheduled future tasks actually reached dispatch."""
from pathlib import Path
import sqlite3,zlib,json,hashlib
O=Path(__file__).resolve().parent;reg=json.loads((O/'experiment.json').read_text());rows=[]
for case in reg['execution_order']:
 p=O/'runs'/case;db=sqlite3.connect(f'file:{p}/events.sqlite3?mode=ro',uri=True);db.execute('BEGIN')
 def get(h):
  v=zlib.decompress((p/'objects'/(h+'.z')).read_bytes());assert hashlib.sha256(v).hexdigest()==h;return json.loads(v)
 def records(ns):return {k:get(h) for k,h in db.execute('SELECT key,ref FROM records WHERE namespace=? ORDER BY rowid',(ns,))}
 candidates=records('candidates');commits=records('commits');seen=set();future=[]
 head=json.loads(db.execute("SELECT value FROM metadata WHERE key='head'").fetchone()[0]);contexts=records('contexts');latest=contexts.get(head.get('context_ref'),{});entities=(latest.get('facts') or {}).get('entities',{})
 trace=[get(h) for h, in db.execute('SELECT object_ref FROM physical ORDER BY seq')]
 for c in commits.values():
  plan=candidates[c['candidate_ref']]['compiled']['plan']
  for t in plan['tasks']:
   if t['id'] in seen:continue
   seen.add(t['id'])
   if t['not_before']>plan['created_at']:
    future.append({'created_at':plan['created_at'],'task':t,'matching_dispatch_events':[e for e in trace if e['kind']=='dispatch' and e['machine']==t['machine'] and e['time']>=plan['created_at'] and e.get('plan_task_id')==t['id'] and set(t['operation_ids'])<={f'{lot}:{step}:{visit}' for lot,step,visit in zip(e.get('lots',[]),e.get('steps',[]),e.get('visits',[]))}]})
 for item in future:
  task=item['task'];keys=['machines:'+str(task['machine'])]+['operations:'+op for op in task['operation_ids']]
  item['latest_public_observation']={'time':latest.get('time'),'context_ref':latest.get('context_ref'),'facts_ref':latest.get('facts_ref'),'values':{k:entities[k]['value'] for k in keys if k in entities}}
 rows.append({'variant':reg['cases'][case]['variant'],'future_tasks':future});db.close()
(O/'dispatch_diagnostics.json').write_text(json.dumps({'note':'Matched by exact plan_task_id, machine and reconstructed lot:step:visit IDs in raw dispatch; inspect each event before claiming successful precoverage. Pending plans do not prove execution.','rows':rows},ensure_ascii=False,indent=2)+'\n')
print([(r['variant'],len(r['future_tasks']),sum(bool(t['matching_dispatch_events']) for t in r['future_tasks'])) for r in rows])
