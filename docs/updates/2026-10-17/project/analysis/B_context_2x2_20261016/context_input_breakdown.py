"""Read-only prompt composition diagnostics. Never influences model context."""
from pathlib import Path
import json,sqlite3,zlib,hashlib
O=Path(__file__).resolve().parent
reg=json.loads((O/'experiment.json').read_text());cases=[]
for case in reg['execution_order']:
 root=O/'runs'/case;db=sqlite3.connect(f'file:{root}/events.sqlite3?mode=ro',uri=True);db.execute('BEGIN')
 def raw(h):
  v=zlib.decompress((root/'objects'/(h+'.z')).read_bytes());assert hashlib.sha256(v).hexdigest()==h;return v
 attempts=sorted([json.loads(raw(h)) for h, in db.execute("SELECT ref FROM records WHERE namespace='attempts'")],key=lambda a:a['index']);rows=[]
 for a in attempts:
  if 'prompt_ref' not in a:continue
  text=raw(a['prompt_ref']).decode();frame=json.loads(text[text.index('\n{')+1:]);mem=frame.get('same_context_fact_memory') or {};fb=frame.get('last_tool_feedback') or {}
  rows.append({'attempt':a['index']+1,'attempt_id':a['attempt_id'],'context_ref':a['context_ref'],'prompt_sha256':a['prompt_ref'],'prompt_chars':len(text),'instruction_chars':text.index('\n{')+1,'json_component_chars':{k:len(json.dumps(v,ensure_ascii=False,separators=(',',':'))) for k,v in frame.items()},'offloaded_feedback':fb.get('offloaded',False),'fact_memory_schema':mem.get('schema'),'fact_memory_all_known_values_inline':mem.get('all_known_field_values_inline'),'fact_memory_fact_count':mem.get('fact_count'),'status':a['status'],'usage':a.get('usage')})
 cases.append({'case':case,'variant':reg['cases'][case]['variant'],'attempts':rows});db.close()
(O/'context_input_breakdown.json').write_text(json.dumps({'note':'Character counts describe prompt components, not token estimates. Tokens are retained from CLI usage only. In-flight rows can lack usage.','cases':cases},ensure_ascii=False,indent=2)+'\n')
for c in cases:
 m=[a for a in c['attempts'] if a['fact_memory_schema']];print(c['variant'],len(c['attempts']),len(m),'memory prompts',[(x['attempt'],x['fact_memory_all_known_values_inline'],x['fact_memory_fact_count']) for x in m])
