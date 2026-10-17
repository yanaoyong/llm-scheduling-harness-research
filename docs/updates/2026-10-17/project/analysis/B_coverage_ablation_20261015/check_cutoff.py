from pathlib import Path
import json,sys,zlib,tempfile
O=Path(__file__).resolve().parent;sys.path.insert(0,str(O/'workspace'))
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.contracts import strict_json,encode
from src.smt_fullfab.harness.evaluation import audit_physical_prefix
from src.smt_fullfab.metrics import compute_metrics
from tests.test_smt_fullfab_harness import wait_delta,propose,apply
initial=strict_json(zlib.decompress((O/'mixed_702__baseline.initial.json.z').read_bytes()));config=strict_json((O/'mixed_702__baseline.config.json').read_bytes())
with tempfile.TemporaryDirectory(prefix='ablation-cutoff-') as folder:
 r=Runtime.start_new(Path(folder)/'run',config,experiment_id='offline-evaluation-clock-test',initial=initial)
 try:
  result=propose(r,wait_delta(r,until=initial['evaluation_end']));assert result['status']=='candidate_checked',result
  assert apply(r,result['candidate_ref'])['status']=='accepted';f=r.advance();assert r.env.t==1002 and r.env.horizon==3600 and r.manifest['period_anchor']==0
  original=list(r.env.trace);view=original+[{'kind':'evaluation_observed_clock','time':r.env.t,'seq':len(original),'source':'offline test only'}] if original[-1]['time']<r.env.t else original
  m=compute_metrics(view,window_start=702,window_end=1002);a=audit_physical_prefix(original,1002,config['priority_weights']);assert m['observed_seconds']==300
  assert a['errors']==['physical: missing terminal event'],a['errors']
  assert r.env.trace==original and len(r.store.rows('attempts'))==2 and r.usage()['actual_model_attempts']==0
  (O/'cutoff_verification.json').write_bytes(encode({'passed':True,'remote_model_calls':0,'original_horizon_preserved':True,'period_anchor_preserved':True,'cutoff_seconds':300,'physical_errors':a['errors'],'analysis_marker_changes_no_production_events':True}));print('Cutoff, exact 300-second metrics and independent physical prefix checks passed; zero remote model calls.')
 finally:r.close()
