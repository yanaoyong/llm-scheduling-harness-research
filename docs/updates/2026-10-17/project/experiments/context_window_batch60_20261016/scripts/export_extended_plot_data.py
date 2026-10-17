from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from src.smt_fullfab.harness.offline_isolation import install_guard
install_guard()
from src.smt_fullfab.harness.evaluation import Evidence
RUN=Path(sys.argv[1]).resolve();x=json.loads((RUN/'comparison.json').read_text());out={'common_window':x['common_window'],'groups':{}}
for g,r in x['results'].items():
 ev=Evidence(r['evidence_directory'],r['evidence_sha256']);contexts=ev.rows('contexts');pts=[(702,0)];failed=[]
 for a in sorted(ev.rows('attempts').values(),key=lambda a:a['index']):
  if a['channel']!='codex' or a['status']=='not_sent':continue
  t=contexts[a['context_ref']]['time'];n=a['index']+1;pts.append((t,n))
  if a.get('usage') is None:failed.append((t,n))
 pts.append((r['head']['time'],pts[-1][1]));out['groups'][g]={'points':pts,'failed':failed,'end':r['head']['time']}
(RUN/'plot_data.json').write_text(json.dumps(out,indent=2)+'\n')
