import json,hashlib,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'experiment_round2_3datasets';OUT=Path(__file__).resolve().parent
run=ROOT/'runs/smt_fullfab_stage2/C_1701_1h_constructive_v2'
old=json.loads((run/'controller_audit.json').read_text())
path,target=next((k,v) for k,v in old['evidence_sha256'].items() if 'model_ledger.jsonl' in k)
h=hashlib.sha256();prefix=[]
for line in Path(path).open('rb'):
 h.update(line);prefix.append(line)
 if h.hexdigest()==target:break
else:raise RuntimeError('Original ledger prefix hash cannot be reconstructed')
p=OUT/'C_exact_historical_ledger.jsonl';p.write_bytes(b''.join(prefix))
receipt={'original_sha256':target,'reconstructed_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'rows':len(prefix),'original_path':path,'note':'Exact raw-byte prefix matches historical audit, no selective filtering.'}
(OUT/'C_ledger_reconstruction.json').write_text(json.dumps(receipt,indent=2)+'\n')
sys.path.insert(0,str(ROOT));from src.smt_fullfab.controller_audit import audit_controller
report=audit_controller(run,p);(OUT/'C_controller_historical_reaudit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print({k:report[k] for k in ['valid','audit_status','attribution_checked_plans','model_attempt_directories','checked_constructor_attempts','successful_full_window']})
print('errors',len(report['errors']),'missing',len(report['missing_evidence']))
