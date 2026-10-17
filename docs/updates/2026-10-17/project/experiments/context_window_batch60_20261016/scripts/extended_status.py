from pathlib import Path
import json,sys
root=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parents[1]/'live_pilots/extended_three_group_completion_20261017'
for g in ('G0','G1','G2'):
 p=root/(g+'.progress.json')
 if not p.exists():p=root/(g+'.result.json')
 if not p.exists():continue
 try:r=json.loads(p.read_text())
 except ValueError:continue
 print(g,json.dumps({'time':round(r['head']['time'],3),'calls':r['usage']['actual_model_attempts'],'phase':r['head']['phase'],
      'commits':r['model_commits'],'unknown_usage':r['usage']['unknown_usage'],'dispatches':r['production_dispatches']}))
lines=(root/'run.log').read_text().splitlines()
print('Latest:',lines[-1] if lines else 'starting')
