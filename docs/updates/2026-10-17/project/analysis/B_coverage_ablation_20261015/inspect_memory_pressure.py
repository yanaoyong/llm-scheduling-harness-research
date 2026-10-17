from pathlib import Path
from copy import deepcopy
import sqlite3,json,zlib,sys
O=Path(__file__).resolve().parent;sys.path.insert(0,str(O/'workspace'))
from src.smt_fullfab.harness.fact_memory import FactMemory
from src.smt_fullfab.harness.contracts import encode
rows=[]
for p in sorted((O/'runs').iterdir()):
 c=sqlite3.connect(f'file:{p}/events.sqlite3?mode=ro',uri=True);g=lambda h:json.loads(zlib.decompress((p/'objects'/f'{h}.z').read_bytes()));aa=[g(h) for h, in c.execute("select ref from records where namespace='attempts'")];aa.sort(key=lambda a:a['index']);latest=next(a for a in reversed(aa) if a.get('prompt_ref'))
 text=zlib.decompress((p/'objects'/(latest['prompt_ref']+'.z')).read_bytes()).decode();prefix,last=text.rsplit('\n',1);frame=json.loads(last);fm=frame.get('same_context_fact_memory',{});row={'case':p.name,'attempt_index':latest['index'],'prompt_chars':len(text),'fact_count':fm.get('fact_count'),'all_values_inline':fm.get('all_known_field_values_inline'),'memory_schema':fm.get('schema')}
 if fm:
  memory=FactMemory(latest['context_ref'])
  for a in aa:
   if a['index']>=latest['index'] or a.get('context_ref')!=latest['context_ref'] or a.get('status')!='processed' or not a.get('response_ref'):continue
   action=g(a['raw_ref']);action=action.get('action',action);response=g(a['response_ref'])
   if action.get('tool')=='read_entities' and response.get('status')=='ok':
    er=c.execute("select ref from records where namespace='interaction_entries' and key=?",(a['attempt_id'],)).fetchone();entry=g(er[0]) if er else {};memory.add(a['index']+1,action,response,entry.get('result_ref'))
  ref=fm.get('full_memory_ref');full=deepcopy(frame);full['same_context_fact_memory']=memory.inline(ref);size=lambda f:len(prefix+'\n'+encode(f).decode());row['size_with_full_known_values']=size(full)
  for key in ['factory_coverage','execution_efficiency']:full['context'].pop(key,None)
  row['size_with_full_values_without_extra_coverage_feedback']=size(full)
 rows.append(row);c.close()
(O/'memory_pressure_preview.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2));print(json.dumps(rows,ensure_ascii=False,indent=2))
