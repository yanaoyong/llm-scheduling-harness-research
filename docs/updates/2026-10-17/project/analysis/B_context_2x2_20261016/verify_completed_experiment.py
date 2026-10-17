"""Final cross-file integrity/accounting check, after each arm's independent audit."""
from pathlib import Path
import json,hashlib,sys,time,zlib
O=Path(__file__).resolve().parent;sys.path.insert(0,str(O/'workspace'))
from src.smt_fullfab.harness.contracts import fingerprint,strict_json,sha_bytes,digest
from src.smt_fullfab.harness.context_recovery import amendment,cohort
from src.smt_fullfab.harness.evaluation import Evidence
reg=strict_json((O/'experiment.json').read_bytes());revision=amendment(reg)
assert fingerprint()==strict_json(Path(revision['after_fingerprint']['path']).read_bytes())
summary=strict_json((O/'summary.json').read_bytes());assert summary['complete_comparison'] and summary['pending_calls']==0
initial_bytes=(O/'singleton_2403__baseline.initial.json.z').read_bytes();config_bytes=(O/'singleton_2403__baseline.config.json').read_bytes()
rows=[]
recoveries=cohort(reg)
for case in reg['execution_order']:
 assert (O/(case+'.initial.json.z')).read_bytes()==initial_bytes
 assert (O/(case+'.config.json')).read_bytes()==config_bytes
 path=O/(case+'.audited.result.json');result=strict_json(path.read_bytes());raw_path=O/(case+'.result.json');raw_result=strict_json(raw_path.read_bytes());repair=result['read_only_audit_repair'];assert repair['original_result_sha256']==sha_bytes(raw_path.read_bytes()) and repair['reader_sha256']==sha_bytes((O/'repair_cost_audit_view.py').read_bytes()) and repair['original_limits_and_all_evidence_unchanged'] and repair['new_model_calls']==0;assert {k:v for k,v in result.items() if k not in ('cost','known_accounting_verified_with_authorized_unknown','read_only_audit_repair')}=={k:v for k,v in raw_result.items() if k not in ('cost','known_accounting_verified_with_authorized_unknown')};entry=next(r for r in summary['rows'] if r['case']==case)
 assert result['complete_common_window'] and result['start']==2403 and result['end']==2703 and result['advanced_seconds']==300
 e=Evidence(O/'runs'/case,result['evidence_sha256']);assert e.value['head']['phase']=='CLOSED'
 attempts=[a for a in e.rows('attempts').values() if a['channel']=='codex' and a['status'] not in ('reserved','not_sent')]
 assert not any(a['status'] in ('reserved','started','unknown') for a in e.rows('attempts').values())
 known=[a for a in attempts if a.get('usage') is not None];unknown=[a for a in attempts if a.get('usage') is None]
 assert len(attempts)==entry['calls']==result['cost']['actual_attempts']
 assert sum(a['usage']['input_tokens']+a['usage']['output_tokens'] for a in known)==entry['total_known_tokens']==result['cost']['total_reported_tokens']
 assert len(unknown)==entry['unknown_usage']==result['cost']['unknown_usage']==result['authorized_recovery_count']==len(recoveries[e.manifest['run_id']][1])
 assert result['provenance']['valid'] and result['physical_audit']['prefix_valid_except_expected_missing_terminal']
 assert result['known_accounting_verified_with_authorized_unknown']
 assert result['cost']['valid']==(len(unknown)==0)
 rows.append({'case':case,'result_sha256':sha_bytes(path.read_bytes()),'original_result_sha256':sha_bytes(raw_path.read_bytes()),'audit_metadata_only_repair_verified':True,'evidence_sha256':result['evidence_sha256'],'actual_calls':len(attempts),'known_reported_tokens':entry['total_known_tokens'],'unknown_usage':len(unknown),'complete_common_window':True,'physical_and_provenance_valid':True,'strict_zero_unknown_cost_audit':result['cost']['valid'],'known_accounting_and_closed_failures_verified':True})
original=strict_json((O/'source_baseline_manifest.json').read_bytes());assert all(sha_bytes((Path(original['source'])/p).read_bytes())==h for p,h in original['files'].items())
assert sum(r['actual_calls'] for r in rows)==summary['total_calls'] and sum(r['known_reported_tokens'] for r in rows)==summary['total_known_tokens'] and sum(r['unknown_usage'] for r in rows)==summary['unknown_usage']
proof={'all_pass':True,'epoch':time.time(),'remote_model_calls_in_verification':0,'all_four_initial_bytes_and_configs_equal':True,'frozen_active_control_source_verified':True,'original_source_files_unchanged':len(original['files']),'live_B_write_or_process_actions':0,'rows':rows,'analysis_artifact_sha256':{name:sha_bytes((O/name).read_bytes()) for name in ['完整实验结论.txt','实验结果.txt','behavior_diagnostics.json','dispatch_diagnostics.json','context_input_breakdown.json']},'summary_sha256':sha_bytes((O/'summary.json').read_bytes()),'registration_sha256':sha_bytes((O/'experiment.json').read_bytes()),'recovery_amendment_sha256':sha_bytes((O/'recovery_amendment.json').read_bytes())}
(O/'completion_verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof,ensure_ascii=False))
