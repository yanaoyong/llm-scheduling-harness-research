"""Read-only snapshot; does not acquire harness writer locks."""
from pathlib import Path
from collections import Counter
import json,sqlite3,zlib,time
O=Path(__file__).resolve().parent
rows=[]
for p in sorted((O/'runs').iterdir()):
 if not (p/'events.sqlite3').exists():continue
 c=sqlite3.connect(f'file:{p}/events.sqlite3?mode=ro',uri=True)
 g=lambda h:json.loads(zlib.decompress((p/'objects'/f'{h}.z').read_bytes()))
 head=json.loads(c.execute("select value from metadata where key='head'").fetchone()[0]);attempts=[g(x[0]) for x in c.execute("select ref from records where namespace='attempts'")];attempts.sort(key=lambda a:a['index']);feedback=[g(x[0]) for x in c.execute("select ref from records where namespace='feedback'")];c.close()
 actions=[]
 for a in attempts:
  if not a.get('raw_ref'):continue
  try:
   v=g(a['raw_ref']);v=v.get('action',v);actions.append(v)
  except (ValueError,AttributeError):actions.append({'tool':'unparsed'})
 latest=actions[-1] if actions else {};inflight=[{'status':a['status'],'seconds':round(time.time()-a.get('started_epoch',time.time()))} for a in attempts if a['status'] in ('started','unknown','responded','reserved')]
 rows.append({'case':p.name,'time':head['time'],'phase':head['phase'],'calls':len(attempts),'replans':len(feedback),'tools':dict(Counter(v.get('tool') for v in actions)),'last_tool':latest.get('tool'),'last_read_queries':latest.get('queries'),'last_read_path':latest.get('path'),'last_read_offset':latest.get('offset'),'inflight':inflight,'tokens':sum(sum(a['usage'].get(k,0) for k in ['input_tokens','output_tokens']) for a in attempts if a.get('usage'))})
print(json.dumps(rows,ensure_ascii=False,indent=2))
