"""Re-audit immutable saved runs into a separate directory; no model/solver calls."""
import json, hashlib, sys, time, platform
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'experiment_round2_3datasets'
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from src.smt_fullfab.stream_audit_bundle import audit_to_bundle,read_bundle
PATHS={'A':'runs/smt_fullfab_development/A_1701_1h_hybrid_v1/trace.jsonl','B':'runs/smt_fullfab_stage2/B_1701_1h_delta_v15__authorized_extension_001/physical/trace.jsonl','C':'runs/smt_fullfab_stage2/C_1701_1h_constructive_v2/trace.jsonl'}
expected=json.loads((ROOT/'artifacts/smt_fullfab_diagnostics/ABC_one_hour_comparison_20261012/sources.sha256.json').read_text())
report={'scope':'saved trace semantic replay, not fresh model scheduling','model_calls':0,'runtime':sys.version,'platform':platform.platform(),'arms':{}}
for arm,rel in PATHS.items():
 start=time.monotonic();p=ROOT/rel
 sha=hashlib.sha256(p.read_bytes()).hexdigest()
 print(arm,'hash_matches',sha==expected[rel],flush=True)
 if sha!=expected[rel]:raise RuntimeError('source changed: '+arm)
 created=audit_to_bundle(p,output_dir=OUT/(arm+'_bundle'),expected_source_sha256=expected[rel],verify_data_dir=ROOT/'data/smt/SMT2020_LVHM',window_start=0,require_terminal=True)
 checked=read_bundle(OUT/(arm+'_bundle'),expected_manifest_sha256=created['report_sha256'])
 report['arms'][arm]={'elapsed_seconds':time.monotonic()-start,'created':created,'checked':checked}
 (OUT/'recheck_results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 print(arm,json.dumps(created['summary']),flush=True)
print('RECHECK_COMPLETE',flush=True)
