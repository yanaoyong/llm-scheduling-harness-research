"""Provisional read-only audit of executed prefixes; never seals a live case."""
from pathlib import Path
import sys,json,sqlite3,time
O=Path(__file__).resolve().parent;sys.path.insert(0,str(O/'workspace'))
from src.smt_fullfab.harness.evaluation import Evidence,audit_provenance,audit_cost,audit_physical_prefix
from src.smt_fullfab.metrics import compute_metrics
out={}
for case in ['mixed_702__baseline','singleton_2403__baseline']:
 p=O/'runs'/case;c=sqlite3.connect(f'file:{p}/events.sqlite3?mode=ro',uri=True);c.execute('BEGIN');records={}
 for ns,k,h in c.execute('select namespace,key,ref from records'):records.setdefault(ns,{})[k]=h
 physical=[h for h, in c.execute('select object_ref from physical order by seq')];head=json.loads(c.execute("select value from metadata where key='head'").fetchone()[0]);c.close()
 e=Evidence.__new__(Evidence);e.path=p;e.allowed={f.stem for f in (p/'objects').glob('*.z')};e.cache={};e.value={'records':records,'head':head,'sealed_epoch':time.time()};e.manifest=e.get(records['manifest']['run']);trace=[e.get(h) for h in physical]
 start=e.manifest['start_time'];end=head['time'];a=audit_physical_prefix(trace,end,e.manifest['config']['priority_weights']);a['errors_without_expected_missing_terminal']=[v for v in a['errors'] if v!='physical: missing terminal event']
 m=compute_metrics(trace if trace[-1]['time']==end else trace+[{'kind':'evaluation_observed_clock','time':end,'seq':len(trace)}],window_start=start,window_end=end,priority_weights=e.manifest['config']['priority_weights'])
 out[case]={'provisional_not_sealed':True,'time':end,'provenance':audit_provenance(e,trace),'cost':audit_cost(e),'physical':a,'metrics':{k:m[k] for k in ['weighted_tardy_lot_seconds','throughput_lots']}}
(O/'prefix_audit_preview.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps({k:{'time':v['time'],'provenance':v['provenance'],'cost_valid':v['cost']['valid'],'physical_errors':v['physical']['errors_without_expected_missing_terminal'],'metrics':v['metrics']} for k,v in out.items()},ensure_ascii=False,indent=2))
