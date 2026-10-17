"""Read-only audit adapter: supply one original-budget display label from sealed manifest.
Never changes runtime source, sealed evidence, original result, limits, usage, or simulation.
"""
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
import sys,time,json
O=Path(__file__).resolve().parent;sys.path.insert(0,str(O/'workspace'))
from src.smt_fullfab.harness.contracts import *
from src.smt_fullfab.harness import wall_budget
from src.smt_fullfab.harness.evaluation import Evidence,audit_cost
from src.smt_fullfab.harness.recovery import validate_recoveries
reg=strict_json((O/'experiment.json').read_bytes());source_before=fingerprint();reader_hash=sha_bytes(Path(__file__).read_bytes());original_budget=wall_budget.effective_budget
calls=[]
def audited_budget(manifest,markers):
 original=original_budget(manifest,markers)
 require(original.get('context_completion_allowance') is True and original.get('model_extension_seconds')==3600 and 'original_model_seconds' not in original,'audit_adapter','Only missing reporting metadata may be supplied')
 updated={**deepcopy(original),'original_model_seconds':manifest['config']['limits']['model_seconds']}
 require(updated['original_model_seconds']==3600 and {k:v for k,v in updated.items() if k!='original_model_seconds'}==original,'audit_adapter','Original budget decisions cannot change')
 calls.append({'run_id':manifest['run_id'],'original_budget_sha256':digest(original),'audit_budget_sha256':digest(updated),'only_added_key':'original_model_seconds','value_source':'sealed manifest.config.limits.model_seconds'})
 return updated
rows=[]
for case in reg['execution_order']:
 raw_path=O/(case+'.result.json');out=O/(case+'.audited.result.json')
 if not raw_path.exists():continue
 raw=strict_json(raw_path.read_bytes());raw_hash=sha_bytes(raw_path.read_bytes())
 if out.exists():
  fixed=strict_json(out.read_bytes());require(fixed['read_only_audit_repair']['original_result_sha256']==raw_hash and fixed['read_only_audit_repair']['reader_sha256']==reader_hash,'audit_adapter','Do not replace existing derived audit');rows.append({'case':case,'verified_existing':True});continue
 require(raw['cost']=={'error':"'original_model_seconds'",'valid':False},'audit_adapter','Only the exact metadata KeyError is eligible')
 e=Evidence(O/'runs'/case,raw['evidence_sha256']);budget=original_budget(e.manifest,e.rows('control_source_revisions'));limits=budget['limits']
 with patch.object(wall_budget,'effective_budget',audited_budget):cost=audit_cost(e)
 recovery=validate_recoveries(e);usage=raw['usage']
 known=(cost['pending_attempts']==0 and cost['unknown_usage']==len(recovery) and cost['classical_unknown']==0 and cost['classical_attempts']<=limits['classical_requests'] and cost['classical_seconds']<=limits['classical_seconds'] and within_cap(cost['actual_attempts'],limits['attempts']) and within_cap(cost['total_reported_tokens'],limits['tokens']) and cost['model_seconds']<=limits['model_seconds'] and cost['experiment_through_seal_wall_seconds']<=limits['wall_seconds'])
 require(known and cost['actual_attempts']==usage['actual_model_attempts'] and cost['total_reported_tokens']==usage['input_tokens']+usage['output_tokens'] and cost['unknown_usage']==usage['unknown_usage'] and cost['valid']==(cost['unknown_usage']==0),'audit_adapter','Complete original accounting checks must pass; unknown cannot be hidden')
 fixed={**raw,'cost':cost,'known_accounting_verified_with_authorized_unknown':known,'read_only_audit_repair':{'kind':'missing_original_model_seconds_display_label','original_result_sha256':raw_hash,'original_error':raw['cost'],'reader_sha256':reader_hash,'budget_changes':calls[-1],'original_limits_and_all_evidence_unchanged':True,'new_model_calls':0,'created_epoch':time.time()}}
 require({k:v for k,v in fixed.items() if k not in ('cost','known_accounting_verified_with_authorized_unknown','read_only_audit_repair')}=={k:v for k,v in raw.items() if k not in ('cost','known_accounting_verified_with_authorized_unknown')},'audit_adapter','No physical, quality or original result changes')
 out.write_bytes(encode(fixed)+b'\n');rows.append({'case':case,'known_accounting_verified':known,'strict_zero_unknown_cost_valid':cost['valid'],'unknown_preserved':cost['unknown_usage']})
require(source_before==fingerprint(),'audit_adapter','Frozen runtime source unchanged')
print(json.dumps({'source_unchanged':True,'new_model_calls':0,'rows':rows},ensure_ascii=False))
