"""Explicit installed admission: preserve one closed V8 pure prefix and all original costs.

No terminal evidence is guessed here. Root must supply and freeze a complete
package after the live predecessor ends. This module validates account/receipt
links only; the producer's pure replay and root's physical closure remain separate.
"""
from __future__ import annotations
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import time
import uuid
from src.smt_fullfab.B_v8_launch_recovery import admission as prior

legacy = prior.legacy
require, same, digest = prior.require, prior.same, prior.digest
SCHEMA = 'smt-B-v8-preserved-admission-v1'
EVENT = 'preserved_protocol_segment_registered'
# Root approved this one cumulative extension; each call still requires all
# original closed certificates, the actual first clock, frozen source and mapping.
LAUNCH_BLOCKERS = ()
PRIOR_SOURCE_SHA = '79ea86254c01cb1ff079e2926ee070b697bda91679dbf3900129724467aad5a8'
PARENT, PREDECESSOR = prior.PARENT, prior.SEGMENT
MODEL, EFFORT, START, HORIZON, PER_CALL = prior.MODEL, prior.EFFORT, prior.START, prior.HORIZON, prior.PER_CALL
OLD_PENDING = prior.OLD_PENDING
PACKAGE_FIELDS = {
    'schema','parent_run_id','predecessor_run_id','segment_run_id','root_completion',
    'prior_ledger_final','prefix_record_count','prior_admission_package','predecessor_result',
    'registration_id','branch_id','store_id','instance_id','simulation_start','horizon_end',
    'next_model_index','first_clock','runtime_source_manifest','continuation_source',
    'resource_contract','physical_restore','model','reasoning_effort','maximum_timeout_seconds',
    'global_max_calls','global_max_tokens','solver_seconds','automatic_retry','parent_status'}
BOUNDARY_KEYS = ('profile','parent_store_id','parent_database_path','parent_prefix',
    'projected_parent_records','first_new_model_index','last_parent_model_index',
    'failed_attempt_id','failed_call_id','failed_model_index','failed_status',
    'parent_interaction_evidence_sha256','parent_bootstrap_sha256')


def finite(value): return type(value) in (int,float) and math.isfinite(value)
def _hash(value): return type(value) is str and len(value)==64 and all(c in '0123456789abcdef' for c in value)
def _small_ref(root, ref, refs): return prior._small_ref(root, ref, refs)


def require_same_root_auditor():
    here=Path(__file__).resolve()
    if here.parent.name=='B_v8_preserved_admission_candidate_v1': source=here.parents[3]/'src'
    else:
        require(here.parent.name=='B_v8_preserved_resume_v1' and here.parents[1].name=='smt_fullfab'
                and here.parents[2].name=='src','unexpected preserved helper location')
        source=here.parents[2]
    expected=source/'smt_fullfab/B_v8_launch_recovery/admission.py'
    require(Path(prior.__file__).resolve()==expected and hashlib.sha256(expected.read_bytes()).hexdigest()==PRIOR_SOURCE_SHA,
            'unchanged same-frozen-source complete predecessor auditor required')
    prior.require_same_root_auditor()


def _decimal(value, name):
    require(type(value) is str and bool(value), name+' must be an exact decimal string')
    try: result=Decimal(value)
    except InvalidOperation as exc: raise ValueError(name+' invalid decimal') from exc
    require(result.is_finite() and result>=0,name+' must be finite/nonnegative')
    return result


def _paths(root, package):
    base=Path(root).resolve()/'runs/smt_fullfab_stage2'
    parent,previous=str(base/PARENT),str(base/PREDECESSOR)
    segment=Path(package['segment_run_id'])
    require(segment==segment.resolve() and segment.parent==base and segment.name.startswith('B_1701_1h_delta_v8__preserved_')
            and segment.name not in (PARENT,PREDECESSOR), 'new direct stage2 preserved identity required')
    require(package['parent_run_id']==parent and package['predecessor_run_id']==previous,'lineage path differs')
    return parent,previous,str(segment)


def _read_prefix(root, ref, count, refs):
    path=Path(ref['path']);path=path if path.is_absolute() else Path(root)/path
    require(path==path.resolve() and path.is_relative_to(Path(root).resolve()) and not path.is_symlink(),'closed prefix path differs')
    require(type(count) is int and count>=prior.PREFIX_ROWS,'complete prefix record count required')
    ident=legacy._identity(path.stat());require(ident[2]<=32*1024*1024,'bounded original prefix exceeded')
    with path.open('rb') as stream:
        require(legacy._identity(os.fstat(stream.fileno()))==ident,'prefix identity changed at open')
        raw=stream.read(32*1024*1024+1)
        require(legacy._identity(os.fstat(stream.fileno()))==ident,'prefix changed while reading')
    require(legacy._identity(path.stat())==ident and hashlib.sha256(raw).hexdigest()==ref['sha256']
            and raw.endswith(b'\n') and all(line.strip() for line in raw.splitlines()),'original raw prefix differs')
    rows=[json.loads(line) for line in raw.splitlines()]
    require(len(rows)==count,'raw prefix record count differs');legacy.canonical(rows)
    refs[str(path)]={'sha256':ref['sha256'],'bytes':len(raw),'file_identity':ident}
    return rows


def _resource_contract(value, closure, account):
    keys={'schema','original_runner_limit_seconds','closed_cumulative_wall_seconds','closed_cumulative_retained_bytes',
          'cumulative_wall_cap_seconds','wall_increment_seconds','extension_reason','authorization',
          'remaining_wall_seconds','cumulative_log_cap_bytes','remaining_log_bytes','calls_cap','tokens_cap'}
    require(type(value) is dict and set(value)==keys and value['schema']=='smt-B-preserved-cumulative-resource-contract-v1','resource contract schema differs')
    require(type(value['original_runner_limit_seconds']) is int and value['original_runner_limit_seconds']==21600,'original limit cannot be rewritten')
    old=Decimal(21600);closed=_decimal(value['closed_cumulative_wall_seconds'],'closed wall')
    cap=_decimal(value['cumulative_wall_cap_seconds'],'cumulative cap');increment=_decimal(value['wall_increment_seconds'],'increment')
    remaining=_decimal(value['remaining_wall_seconds'],'remaining wall')
    require(value['closed_cumulative_wall_seconds']==closure['combined_wall_seconds_upper']
            and value['closed_cumulative_retained_bytes']==closure['combined_retained_bytes_including_closure'], 'original closed costs cannot reset')
    require(cap>=old and cap-old==increment and 0<remaining<=cap-closed,'new cumulative cap/increment/remaining must reconcile')
    if increment:
        require(value['authorization']=='root_frozen_technical_wall_extension' and type(value['extension_reason']) is str and bool(value['extension_reason'].strip()),'explicit technical extension reason/authority required')
    else: require(value['authorization']=='unchanged_original_technical_wall_cap' and value['extension_reason'] is None,'unchanged cap declaration differs')
    require(type(value['closed_cumulative_retained_bytes']) is int and value['closed_cumulative_retained_bytes']>=0
            and type(value['cumulative_log_cap_bytes']) is int and value['cumulative_log_cap_bytes']==16*1024**3
            and type(value['remaining_log_bytes']) is int and 0<value['remaining_log_bytes']<=value['cumulative_log_cap_bytes']-value['closed_cumulative_retained_bytes'], 'byte allowance cannot reset or silently expand')
    require(value['calls_cap'] is value['tokens_cap'] is None,'model quota must remain waived')
    require(finite(account['active_execution_seconds']) and Decimal(str(account['active_execution_seconds']))<=closed,'closed whole wall cannot omit model/tool active cost')
    return {'runner_wall_seconds':value['remaining_wall_seconds'],'log_bytes':value['remaining_log_bytes']}


def _boundary(value, account_rows, next_index):
    require(type(value) is dict and set(value)==set(BOUNDARY_KEYS)|{'selection','unknown_commit','pending_attempts','physical_new_commits','pure_reference_replay_valid','last_call_final_present','last_call_guard_verified'},'closed pure boundary schema differs')
    require(value['profile'] in ('processed_boundary','terminal_failed_no_final') and value['selection'] is None
            and value['unknown_commit'] is False and value['pending_attempts']==[]
            and value['pure_reference_replay_valid'] is True
            and type(value['physical_new_commits']) is int and value['physical_new_commits']==0,'ambiguous selection/pending/commit is not resumable')
    require(type(value['first_new_model_index']) is int and value['first_new_model_index']==next_index
            and type(value['last_parent_model_index']) is int and value['last_parent_model_index']==next_index-1,
            'next model identity must follow every original reserved attempt')
    p=value['parent_prefix']
    require(type(p) is dict and set(p)=={'journal_records','journal_tail_sha256','database_sha256'}
            and type(p['journal_records']) is int and p['journal_records']>=2
            and _hash(p['journal_tail_sha256']) and _hash(p['database_sha256'])
            and type(value['projected_parent_records']) is int and 2<=value['projected_parent_records']<=p['journal_records']
            and all(_hash(value[k]) for k in ('parent_interaction_evidence_sha256','parent_bootstrap_sha256')),'full original pure prefix/evidence anchors required')
    if value['profile']=='processed_boundary':
        require(all(value[k] is None for k in ('failed_attempt_id','failed_call_id','failed_model_index','failed_status'))
                and value['projected_parent_records']==p['journal_records']
                and value['last_call_final_present'] is True and value['last_call_guard_verified'] is True,'processed boundary cannot omit a suffix')
    else:
        require(type(value['failed_attempt_id']) is str and value['failed_attempt_id']
                and type(value['failed_model_index']) is int and value['failed_model_index']==next_index-1
                and value['last_call_final_present'] is False and value['last_call_guard_verified'] is True
                and value['failed_status'] in ('failed','timeout'), 'terminal failure identity missing')
        starts=[r for r in account_rows if r.get('event')=='reserve' and r.get('call_id')==value['failed_call_id']]
        ends=[r for r in account_rows if r.get('event')=='finish' and r.get('call_id')==value['failed_call_id']]
        require(len(starts)==len(ends)==1 and Path(starts[0]['run_id']).name==f'model_{next_index-1:05d}'
                and ends[0]['status']==value['failed_status'],'failed tail must already have an original unique finish; no synthetic finish')
    return value


# Installed narrow adapter for the actual 221-call closed predecessor. The
# candidate's general boundary policy is unchanged; original certificates remain
# immutable and a derived projection must equal this exact reconstruction.
CLOSED_ROOT_SHA = 'f7b12cd40f7628c0ba83314c2d26cfe0bc7b47ddc1e7385965200f97b8a3b2e6'
COLD_PROOF_SHA = '844529e5d6aaeb6972f8884e9ddf049b901740fea45929742db16246d986bc0e'
TERMINAL_AUDIT_SHA = 'a0189e6fd994a3d326a1be91489ccd0c1b6b707af86480506a2884fcf00f6be9'
ROOT_TESTS_SHA = 'dd1800cd8f1c1cafb3e9a26482dabd2563fc962bf68160697e11150567f4330d'
SEGMENT = 'B_1701_1h_delta_v8__preserved_001'
ORIGIN_FIELDS = {'root_completion','cold_proof','cold_execution','cold_stdout','terminal_audit',
                 'actual_exit','parent_manifest','prior_account','supplemental_cost','candidate_tests'}


def _metadata_ref(root, ref, refs):
    require(type(ref) is dict and set(ref)=={'path','sha256'} and _hash(ref['sha256']),'exact metadata original ref required')
    path=Path(ref['path']);path=path if path.is_absolute() else Path(root)/path
    require(path==path.resolve() and path.is_relative_to(Path(root).resolve()) and not path.is_symlink(),'metadata path outside root')
    identity=legacy._identity(path.stat());require(identity[2]<=4*1024*1024,'bounded metadata exceeded')
    with os.fdopen(os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)),'rb') as stream:
        require(legacy._identity(os.fstat(stream.fileno()))==identity,'metadata changed at open')
        raw=stream.read(4*1024*1024+1)
        require(legacy._identity(os.fstat(stream.fileno()))==identity,'metadata changed while reading')
    require(legacy._identity(path.stat())==identity and hashlib.sha256(raw).hexdigest()==ref['sha256'],'metadata original bytes differ')
    value=json.loads(raw);legacy.canonical(value)
    previous=refs.get(str(path));current={'sha256':ref['sha256'],'bytes':len(raw),'file_identity':identity}
    require(previous is None or same(previous,current),'metadata reanchored')
    refs[str(path)]=current
    return value


def project_closed_evidence(root, origin_refs, *, physical_restore_sha256=None, references=None):
    """Pure small-certificate projection. No ledger mutation, DB or restore.

    The supplemental receipt is an externally frozen root measurement. Its wall
    must include the full cold-proof process, not oracle+process double counting.
    The new segment firstclock owns all subsequent preparation/execution costs.
    """
    refs={} if references is None else references
    require(type(origin_refs) is dict and set(origin_refs)==ORIGIN_FIELDS,'complete original projection refs required')
    d={k:_metadata_ref(root,v,refs) for k,v in origin_refs.items()}
    c=d['root_completion'];proof=d['cold_proof'];execution=d['cold_execution'];audit=d['terminal_audit']
    m=d['parent_manifest'];x=d['actual_exit'];account=d['prior_account'];supp=d['supplemental_cost'];tests=d['candidate_tests']
    require(origin_refs['root_completion']['sha256']==CLOSED_ROOT_SHA and origin_refs['cold_proof']['sha256']==COLD_PROOF_SHA
            and origin_refs['terminal_audit']['sha256']==TERMINAL_AUDIT_SHA
            and origin_refs['candidate_tests']['sha256']==ROOT_TESTS_SHA,'original externally supplied roots differ')
    require(c['schema']=='smt-B-v8-corrected-launch-root-failure-closure-v1'
            and c['status']=='failed_evidence_closed' and c['failure_evidence_verified'] is True and c['accepted'] is False
            and c['exact_physical_state_unchanged_except_restore_marker'] is True
            and c['new_commits']==0 and same(c['simulation_seconds'],START)
            and c['next_unique_model_index']==221 and c['last_processed_model_index']==220,'actual closed predecessor boundary differs')
    require(x['session_id']==3830 and x['actual_tool_exit_code']==1 and same(x,c['actual_exit'])
            and same(x,proof['actual_parent_exit']) and same(x,audit['actual_exit']),'actual terminal receipt differs')
    require(proof['schema']=='smt-B-v8-preserved-parent-proof-v1' and proof['valid'] is True
            and proof['processed_boundary_eligible'] is True and proof['accepted'] is False
            and proof['model_calls']==proof['ledger_mutations']==proof['physical_operations']==0
            and proof['source_or_parent_bytes_modified'] is False and proof['oracle_calls']==1
            and proof['selection'] is proof['pending_attempt_id'] is None
            and proof['intent_present'] is proof['receipt_present'] is False
            and proof['history_model_indices']==list(range(188,221)) and proof['next_unique_model_index']==221
            and proof['expected_prefix']==c['last_processed_original_prefix']
            and proof['database_before_sha256']==proof['database_after_sha256']==proof['expected_prefix']['database_sha256'],
            'original cold full-replay proof is absent or incompatible')
    require(execution['schema']=='smt-B-v8-parent-proof-execution-v1' and execution['actual_returncode']==0
            and execution['timed_out'] is False and execution['model_calls']==0
            and finite(execution['wall_seconds']) and execution['wall_seconds']>0
            and execution['stdout_sha256']==origin_refs['cold_stdout']['sha256']
            and d['cold_stdout']['valid'] is True
            and d['cold_stdout']['summary']['sha256']==origin_refs['cold_proof']['sha256'], 'cold proof actual process completion differs')
    require(audit['verification_valid'] is True and audit['errors']==audit['incomplete_evidence']==[] and audit['accepted'] is False
            and audit['manifest_sha256']==c['manifest_sha256']==origin_refs['parent_manifest']['sha256']
            and audit['ledger']['sha256']==c['ledger_final_sha256']
            and same(audit['costs']['cumulative'],c['cumulative_model_account'])
            and same(audit['costs']['new_segment'],c['segment_model_account']), 'original terminal model/guard/account audit differs')
    last=audit['calls'][-1];last_index=proof['original_last_call_finished']['payload']
    require(last['model_index']==last_index['model_index']==220 and last['call_id']==last_index['call_id']
            and last['outcome_sha256']==last_index['outcome_sha256'] and last['status']=='success'
            and last['returncode']==0 and last['timed_out'] is False and _hash(last['guard_original_outputs']['final.txt']),
            'processed boundary lacks an original verified final/guard')
    require(same(account['recovery_account'],c['cumulative_model_account'])
            and same(account['segment_account'],c['segment_model_account'])
            and same(account['diagnostic_account_separate'],audit['costs']['diagnostic_separate'])
            and origin_refs['prior_account']['sha256']==audit['original_host']['account_sha256'], 'separate original costs differ')
    require(tests['actual_tests_passed']==66 and sorted((r['scope'],r['test_count'],r['actual_tool_exit_code']) for r in tests['results'])
            ==[('admission',22,0),('attribution',24,0),('interaction',20,0)], 'original 66 candidate test record differs')
    require(supp['schema']=='smt-B-preserved-supplemental-cost-v1' and supp['root_completion_sha256']==CLOSED_ROOT_SHA
            and same(supp['cold_execution'],origin_refs['cold_execution'])
            and supp['scope_end']=='before_new_segment_first_clock' and supp['oracle_subtime_added_separately'] is False,
            'root supplemental process/preparation cost receipt required')
    extra=_decimal(supp['wall_seconds_upper'],'supplemental whole wall')
    require(extra>=Decimal(str(execution['wall_seconds'])) and type(supp['retained_bytes']) is int
            and supp['retained_bytes']>=proof['full_export']['bytes']+refs[str((Path(root)/origin_refs['cold_proof']['path']).resolve())]['bytes'],
            'supplement cannot omit the actual full cold proof wall/retained export')
    require(type(supp['measured_scopes']) is list and bool(supp['measured_scopes'])
            and type(supp['measurement_records']) is list and bool(supp['measurement_records']), 'root supplemental measured scope required')
    for ref in supp['measurement_records']:_metadata_ref(root,ref,refs)
    parent=Path(root).resolve()/'runs/smt_fullfab_stage2'/PREDECESSOR
    require(proof['parent_run']==str(parent) and m['segment']==str(parent.relative_to(Path(root).resolve())), 'original parent physical/runtime mismatch')
    contract=m['parent_contract'];physical={'schema':'smt-B-v8-preserved-physical-source-v1',
        'equivalent_original_state_verified':True,'simulation_seconds':START,'horizon_end':HORIZON,
        'checkpoint':{'path':str(parent/'checkpoint.json'),'sha256':c['checkpoint_sha256']},
        'checkpoint_state_sha256':c['checkpoint_state_sha256'],
        'trace':{'path':str(parent/'physical/trace.jsonl'),'sha256':c['trace_sha256']},'source_sha256':contract['parent_source_sha256']}
    boundary={'profile':'processed_boundary','parent_store_id':proof['parent_store_id'],
        'parent_database_path':str(parent/'plan_00001/durable/ledger.sqlite3'),'parent_prefix':proof['expected_prefix'],
        'projected_parent_records':proof['expected_prefix']['journal_records'],'first_new_model_index':221,'last_parent_model_index':220,
        'failed_attempt_id':None,'failed_call_id':None,'failed_model_index':None,'failed_status':None,
        'parent_interaction_evidence_sha256':proof['interaction_evidence_sha256'],
        # Producer uses canonical bootstrap digest, distinct from original file SHA.
        'parent_bootstrap_sha256':proof['bootstrap_canonical_sha256'],
        'selection':None,'unknown_commit':False,'pending_attempts':[],'physical_new_commits':0,
        'pure_reference_replay_valid':True,'last_call_final_present':True,'last_call_guard_verified':True}
    projection={'schema':'smt-B-v8-preserved-predecessor-closure-v1','run_id':str(parent),'accepted':False,
        'status':'failed_evidence_closed','failure_evidence_verified':True,'actual_exit_verified':True,'source_fence_verified':True,
        'exact_physical_state_unchanged_except_restore_marker':True,'ledger_final_sha256':c['ledger_final_sha256'],
        'ledger_records':audit['ledger']['rows'],'result_sha256':c['result_sha256'],'simulation_seconds':START,'new_commits':0,
        'cumulative_model_account':c['cumulative_model_account'],'segment_model_account':c['segment_model_account'],
        'diagnostic_account_separate':account['diagnostic_account_separate'],'next_unique_model_index':221,'continuation_boundary':boundary,
        'combined_wall_seconds_upper':str(Decimal(str(c['combined_wall_seconds_upper']))+extra),
        'combined_retained_bytes_including_closure':c['combined_retained_bytes_including_closure']+supp['retained_bytes'],
        'physical_restore_sha256':physical_restore_sha256,'original_evidence':deepcopy(origin_refs),
        'projection_scope':'original closed certificate plus original full pure proof and root supplemental cost; originals unchanged'}
    legacy._fence(refs)
    return projection,physical


def _base(rows, approval, *, root, package_config):
    require_same_root_auditor();refs={};p=_small_ref(root,package_config,refs)
    require(type(p) is dict and set(p)==PACKAGE_FIELDS and p['schema']=='smt-B-v8-preserved-package-v1','explicit frozen preserved package required')
    parent,previous,segment=_paths(root,p)
    original=_read_prefix(root,p['prior_ledger_final'],p['prefix_record_count'],refs)
    require(len(rows)>=len(original) and same(rows[:len(original)],original),'entire immutable predecessor ledger prefix required')
    report=prior.audit_admissions(original,approval,root=root,target_run_id=previous,package_config=p['prior_admission_package'])
    require(not report['errors'] and not report['missing_evidence'],'unchanged full predecessor audit rejected: '+repr(report['errors']))
    closure=_small_ref(root,p['root_completion'],refs)
    expected_closure,expected_physical=project_closed_evidence(root,closure['original_evidence'],physical_restore_sha256=p['physical_restore']['sha256'],references=refs)
    require(same(closure,expected_closure),'derived closure must remain exact original certificate projection')
    require(Path(segment).name==SEGMENT,'only this explicitly installed preserved segment is permitted')
    require(closure['schema']=='smt-B-v8-preserved-predecessor-closure-v1' and closure['run_id']==previous
            and closure['accepted'] is False and closure['status']=='failed_evidence_closed'
            and closure['failure_evidence_verified'] is True and closure['actual_exit_verified'] is True
            and closure['source_fence_verified'] is True and closure['exact_physical_state_unchanged_except_restore_marker'] is True,
            'original actual terminal/source/physical closure required')
    require(closure['ledger_final_sha256']==p['prior_ledger_final']['sha256'] and closure['ledger_records']==len(original)
            and closure['result_sha256']==p['predecessor_result']['sha256'],'closure/raw terminal anchors differ')
    result=_small_ref(root,p['predecessor_result'],refs)
    require(result['status']=='failed' and result['accepted'] is False and result['full_window_completed'] is False
            and type(result['new_commits']) is int and result['new_commits']==0 and same(result['simulation_seconds'],START)
            and same(closure['simulation_seconds'],START) and closure['new_commits']==0,'only original zero-new-commit 803.25 profile supported')
    physical=_small_ref(root,p['physical_restore'],refs)
    require(same(physical,expected_physical),'physical restore contract changed from original frozen parent')
    require(closure['physical_restore_sha256']==p['physical_restore']['sha256']
            and physical['schema']=='smt-B-v8-preserved-physical-source-v1'
            and physical['equivalent_original_state_verified'] is True
            and same(physical['simulation_seconds'],START) and same(physical['horizon_end'],HORIZON)
            and _hash(physical['checkpoint']['sha256']) and _hash(physical['checkpoint_state_sha256'])
            and _hash(physical['trace']['sha256']) and _hash(physical['source_sha256']),
            'root-bound original physical restore/source contract required')
    for field in ('checkpoint','trace'):
        path=Path(physical[field]['path'])
        require(path==path.resolve() and path.is_relative_to(Path(root).resolve()),'physical source must belong to original root')
    parent_account=report['recovery_account'];global_account=legacy._account(original)
    own_ids={r['call_id'] for r in prior._lineage_rows(original,root) if r.get('event')=='reserve'}
    own_ids|={r['call_id'] for r in original if r.get('event')=='reserve' and str(Path(r['run_id']).parent)==previous}
    lineage=[r for r in original if r.get('call_id') in own_ids]
    require(same(legacy._account(lineage),parent_account) and same(parent_account,closure['cumulative_model_account'])
            and same(report['segment_account'],closure['segment_model_account'])
            and same(report['diagnostic_account_separate'],closure['diagnostic_account_separate']), 'complete cumulative/diagnostic costs differ')
    require(parent_account['attempts']==188+report['segment_account']['attempts']
            and parent_account['reported_input_output_tokens']==4475910+report['segment_account']['reported_input_output_tokens']
            and parent_account['unknown_completed']==prior.UNKNOWN_CALLS+report['segment_account']['unknown_completed']
            and parent_account['pending']==[] and global_account['pending']==[OLD_PENDING]
            and global_account['pending_solver_calls']==global_account['pending_constructor_calls']==[], 'unknown/pending ancestry changed or new pending remains')
    next_index=188+report['segment_account']['attempts']
    require(type(p['next_model_index']) is int and p['next_model_index']==next_index
            and result['next_global_model_index']==next_index and closure['next_unique_model_index']==next_index,'old model index cannot be reused')
    boundary=_boundary(closure['continuation_boundary'],lineage,next_index)
    require(Path(boundary['parent_database_path']).is_relative_to(Path(previous)),'parent DB source outside original segment')
    reg=report['registered_runs'][parent]
    require(p['registration_id']==reg['registration_id'] and p['parent_status']=='failed' and p['automatic_retry'] is False
            and same(p['simulation_start'],START) and same(p['horizon_end'],HORIZON),'new allowance/relative physical clock forbidden')
    require(type(p['branch_id']) is str and p['branch_id'].startswith(Path(segment).name+':')
            and p['store_id']==p['branch_id'] and p['instance_id']==p['branch_id']+':instance','new preserved store/instance identities required')
    require(p['model']==MODEL and p['reasoning_effort']==EFFORT and same(p['maximum_timeout_seconds'],PER_CALL)
            and p['global_max_calls'] is p['global_max_tokens'] is None and same(p['solver_seconds'],0),'original model/600/tool constraints changed')
    contract=_small_ref(root,p['resource_contract'],refs);remaining=_resource_contract(contract,closure,parent_account)
    require(contract['cumulative_wall_cap_seconds']=='86400' and contract['wall_increment_seconds']=='64800', 'root approved cumulative technical extension differs')
    clock=_small_ref(root,p['first_clock'],refs)
    require(clock['schema']=='smt-B-v8-preserved-first-clock-v1' and clock['segment_run_id']==segment
            and finite(clock['started_monotonic_seconds']) and clock['started_monotonic_seconds']>0
            and type(clock['started_utc']) is str and clock['started_utc'],'original whole-segment firstclock required')
    sources=_small_ref(root,p['runtime_source_manifest'],refs)
    require(type(sources) is dict and sources and all(type(k) is str and _hash(v) for k,v in sources.items()),'frozen runtime source closure required')
    code_ref=p['continuation_source'];code=Path(code_ref['path']);code=code if code.is_absolute() else Path(root)/code
    require(code==code.resolve() and code.is_relative_to(Path(root).resolve()) and _hash(code_ref['sha256']),'explicit continuation producer source required')
    # The original runtime keys stay repository-relative in both live and frozen namespaces.
    frozen=Path(root).resolve()/'runs/smt_fullfab_B_direct_gate'/SEGMENT/'frozen'
    source_root=frozen if code.is_relative_to(frozen) else Path(root).resolve()
    code_key=str(code.relative_to(source_root))
    require(code_key=='src/smt_fullfab/B_v8_preserved_resume_v1/continuation_store.py'
            and sources.get(code_key)==code_ref['sha256'],'producer absent from frozen source manifest')
    ident=legacy._identity(code.stat())
    with os.fdopen(os.open(code,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)),'rb') as stream:
        require(legacy._identity(os.fstat(stream.fileno()))==ident,'continuation source changed at open')
        raw=stream.read()
        require(legacy._identity(os.fstat(stream.fileno()))==ident,'continuation source changed while reading')
    require(legacy._identity(code.stat())==ident and hashlib.sha256(raw).hexdigest()==code_ref['sha256'],'continuation source changed')
    refs[str(code)]={'sha256':code_ref['sha256'],'bytes':len(raw),'file_identity':ident}
    legacy._fence(refs)
    return {'package':p,'report':report,'registration':reg,'prefix_rows':original,'lineage_rows':lineage,
        'parent_account':parent_account,'diagnostic_account':report['diagnostic_account_separate'],'closure':closure,
        'boundary':boundary,'contract':contract,'remaining':remaining,'clock':clock,'refs':refs}


def _mapping(root, config, base, continuation_ref):
    refs=dict(base['refs']);p=base['package'];segment=Path(p['segment_run_id'])
    path=Path(continuation_ref['path']);require(path==path.resolve() and path.is_relative_to(segment),'continuation manifest must belong to the new segment')
    manifest=_small_ref(root,continuation_ref,refs)
    require(manifest['schema']=='smt-B-v8-preserved-continuation-v1' and manifest['segment_run_path']==str(segment)
            and manifest['branch_id']==p['branch_id'] and manifest['instance_id']==p['instance_id']
            and manifest['external_authorization_sha256']==config['sha256']
            and manifest['fork_code_sha256']==p['continuation_source']['sha256']
            and _hash(manifest['next_prompt_sha256']) and _hash(manifest['next_schema_sha256']),'continuation producer identity/source/authority differs')
    require(all(same(manifest[k],base['boundary'][k]) for k in BOUNDARY_KEYS),'producer boundary changed from original root-verified pure prefix')
    reg=base['registration'];contract=base['contract']
    m={'schema':SCHEMA,'parent_run_id':p['parent_run_id'],'predecessor_run_id':p['predecessor_run_id'],
        'segment_run_id':p['segment_run_id'],'registration_id':reg['registration_id'],'original_registration':reg,
        'package':deepcopy(config),'continuation_manifest':deepcopy(continuation_ref),
        'branch_id':p['branch_id'],'store_id':p['store_id'],'instance_id':p['instance_id'],
        'prior_prefix_sha256':p['prior_ledger_final']['sha256'],'prefix_record_count':len(base['prefix_rows']),
        'prior_records_sha256':digest(base['prefix_rows']),'simulation_start':p['simulation_start'],
        'horizon_end':p['horizon_end'],'next_model_index':p['next_model_index'],
        'first_clock':p['first_clock'],'started_monotonic_seconds':base['clock']['started_monotonic_seconds'],
        'inherited':{'runner_wall_seconds':contract['closed_cumulative_wall_seconds'],
                     'log_bytes':contract['closed_cumulative_retained_bytes'],'parent_account':base['parent_account']},
        'remaining':base['remaining'],'cumulative_wall_cap_seconds':contract['cumulative_wall_cap_seconds'],
        'resource_contract':p['resource_contract'],'physical_restore':p['physical_restore'],
        'continuation_prompt_sha256':manifest['next_prompt_sha256'],'continuation_schema_sha256':manifest['next_schema_sha256'],
        'diagnostic_account_separate':base['diagnostic_account'],
        'solver_seconds':0,'automatic_retry':False,'new_cold_registration':False,'pure_prefix_preserved':True}
    m['preserved_protocol_segment_id']=digest(m);legacy._fence(refs)
    return m,refs


def _resources(value, previous, local, mapping):
    require(type(value) is dict and set(value)=={'elapsed_seconds','retained_bytes'},'original small resource observation required')
    t=value['elapsed_seconds'];n=value['retained_bytes']
    require(finite(t) and t>=previous['elapsed_seconds'] and type(n) is int and n>=previous['retained_bytes'],'whole-segment resources cannot reset')
    remaining=float(_decimal(mapping['remaining']['runner_wall_seconds'],'remaining'))-t
    active=float(_decimal(mapping['cumulative_wall_cap_seconds'],'cumulative cap'))-mapping['inherited']['parent_account']['active_execution_seconds']-local['active_execution_seconds']
    require(remaining>=1 and n<mapping['remaining']['log_bytes'],'whole inherited allowance exhausted')
    return min(PER_CALL,remaining,active)


def preflight_recovery(rows, approval, *, root, package_config):
    base=_base(rows,approval,root=root,package_config=package_config);p=base['package']
    require(len(rows)==len(base['prefix_rows']),'preflight requires exact closed predecessor prefix')
    return {'schema':SCHEMA,'registration':deepcopy(base['registration']),'package':deepcopy(package_config),
        'branch_id':p['branch_id'],'store_id':p['store_id'],'instance_id':p['instance_id'],
        'started_monotonic_seconds':base['clock']['started_monotonic_seconds'],
        'inherited':{'runner_wall_seconds':base['contract']['closed_cumulative_wall_seconds'],
                     'log_bytes':base['contract']['closed_cumulative_retained_bytes'],'parent_account':base['parent_account']},
        'remaining':base['remaining'],'diagnostic_account_separate':base['diagnostic_account'],
        'physical_recovery_verified':False,'pure_replay_independently_verified':False,'resource_acceptance_verified':False,
        'launch_blockers':list(LAUNCH_BLOCKERS)}


def audit_admissions(rows, approval, *, root, target_run_id=None, package_config=None):
    report = {'errors':[],'missing_evidence':[],'registered_runs':{},'admissions':{}}
    try:
        base = _base(rows, approval, root=root, package_config=package_config)
        parent, predecessor, segment = _paths(root, base['package'])
        prefix_count = len(base['prefix_rows']); first_index = base['package']['next_model_index']
        require(target_run_id is None or str(Path(target_run_id).resolve()) in (parent, predecessor, segment),
                'unrelated preserved protocol target')
        report = deepcopy(base['report'])
        history = list(rows[:prefix_count]); own = []; mapping = None
        previous = {'elapsed_seconds':0,'retained_bytes':0}; last_index = first_index - 1
        if len(rows) > prefix_count:
            row = rows[prefix_count]
            require(row.get('event') == EVENT and row.get('segment_run_id') == segment,
                    'unique preserved protocol mapping must precede new calls')
            mapping, refs = _mapping(root, package_config, base, row['mapping']['continuation_manifest'])
            require(same(row['mapping'], mapping) and row.get('registration_id') == mapping['registration_id'],
                    'preserved mapping is not exact original package/store/account projection')
            history.append(row); report['registered_runs'][segment] = deepcopy(base['registration'])
            for row in rows[prefix_count + 1:]:
                account = legacy._account(history); local = legacy._account(own); cid = row.get('call_id')
                if row.get('event') == 'reserve':
                    md = row['metadata']; run = Path(row['run_id']); stem = run.name
                    require(run.parent == Path(segment) and stem.startswith('model_') and stem[6:].isdigit()
                            and stem == f'model_{int(stem[6:]):05d}' and int(stem[6:]) == last_index + 1,
                            'new sequential unique model directories must begin at the externally closed next index')
                    require(type(cid) is str and cid and not any(r.get('call_id') == cid for r in history),
                            'old or duplicate call identity forbidden')
                    require(account['pending'] == [OLD_PENDING]
                            and account['pending_solver_calls'] == account['pending_constructor_calls'] == [],
                            'new pending call blocks admission; no retry')
                    reg = base['registration']; timeout = md['timeout_seconds']
                    require(row['registration_id'] == reg['registration_id']
                            and row['preserved_protocol_segment_id'] == mapping['preserved_protocol_segment_id']
                            and row['parent_run_id'] == parent and row['phase'] == reg['phase']
                            and row['grant_id'] == reg['budget_id'] and row['amendment_id'] == reg['amendment_id']
                            and same(md['authorization_context'],{'purpose':'B','arm':'B','scenario':reg['scenario'],'window_seconds':reg['window_seconds']})
                            and md['model'] == MODEL and md['reasoning_effort'] == EFFORT,
                            'preserved reserve changed original authority or model')
                    cap = _resources(row['preserved_resources_before'], previous, local, mapping)
                    require(finite(timeout) and 1 <= timeout <= cap, 'timeout exceeds600 or cumulative remaining allowance')
                    combined = legacy._account(base['lineage_rows'] + own)
                    require(same(row['account_before'], account) and same(row['run_account_before'], combined)
                            and same(row['segment_account_before'], local), 'preserved reserve reset original cumulative costs')
                    report['admissions'][cid] = {'purpose':'B','waiver_applied':True,
                        'amendment_id':reg['amendment_id'],'waiver_scope':'registered_research','registration':reg,
                        'active_seconds_before':account['model_active_seconds'],'timeout_seconds':timeout,
                        'solver_requested_seconds_before_by_arm':{},'run_solver_requested_seconds_before':0,
                        'run_active_seconds_before':combined['model_active_seconds'],
                        'preserved_protocol_segment_id':mapping['preserved_protocol_segment_id'],
                        'timeout_extension':base['report']['stopped_pending']['timeout_extension']}
                    previous = row['preserved_resources_before']; last_index += 1
                elif row.get('event') == 'finish':
                    require(cid in local['pending'] and row['status'] in ('success','failed','timeout')
                            and finite(row['details'].get('duration_seconds')) and row['details']['duration_seconds'] >= 0,
                            'finish can close only a unique new preserved-segment call')
                else:
                    raise ValueError('unsupported preserved suffix; no tools, cold registration, or second mapping')
                own.append(row); history.append(row); legacy._account(history)
            legacy._fence(refs)
        global_account = legacy._account(history); local = legacy._account(own)
        report['stopped_pending'] = {**base['report']['stopped_pending'],'allowed_pending_call_ids':[OLD_PENDING],
            'raw_pending':global_account['pending'],'new_run_pending_call_ids':local['pending'],
            'target_run_id':segment,'preserved_completed_unknown_call_ids':base['parent_account']['unknown_completed']}
        report.update(model_active_seconds=global_account['model_active_seconds'],
            unknown_usage_call_ids=global_account['unknown_completed'],preserved_mapping=mapping,
            recovery_mapping=mapping, recovery_account=legacy._account(base['lineage_rows'] + own),
            parent_account=base['parent_account'],segment_account=local,
            diagnostic_account_separate=base['diagnostic_account'],original_parent_kept_failed=True,
            physical_recovery_verified=False,resource_acceptance_verified=False)
        legacy._fence(base['refs'])
    except (ValueError, KeyError, TypeError, OSError, OverflowError) as exc:
        report['errors'].append('V8 preserved continuation admission: ' + str(exc))
    return report


def _raw_prefix(path, mapping):
    path=Path(path);require(not path.is_symlink(),'live ledger symlink')
    ident=legacy._identity(path.stat());raw=bytearray()
    with path.open('rb') as stream:
        require(legacy._identity(os.fstat(stream.fileno()))==ident,'ledger changed at open')
        for _ in range(mapping['prefix_record_count']):
            line=stream.readline(1024*1024+1)
            require(line.endswith(b'\n') and len(line)<=1024*1024,'incomplete original ledger prefix')
            raw.extend(line)
        require(legacy._identity(os.fstat(stream.fileno()))==ident,'ledger changed during read')
    require(legacy._identity(path.stat())==ident and hashlib.sha256(raw).hexdigest()==mapping['prior_prefix_sha256'],'closed original ledger bytes changed')


def make_ledger_class(original_budget_module, *, package_config, started_monotonic=None, retained_bytes_provider=None):
    require(not LAUNCH_BLOCKERS,'preserved continuation candidate execution blocked: '+repr(LAUNCH_BLOCKERS))
    b=original_budget_module
    class PreservedSegmentLedger(b.BudgetLedger):
        def _audit(self, rows):
            require(not LAUNCH_BLOCKERS,'preserved continuation remains blocked')
            approvals=[r['approval'] for r in rows if r.get('event')=='approval']
            require(len(approvals)==1,'unique original approval required')
            report=audit_admissions(rows,approvals[0],root=b.ROOT,package_config=package_config)
            require(not report['errors'] and not report['missing_evidence'],'preserved ledger rejected: '+repr(report['errors']))
            return approvals[0],report

        def register_preserved_segment(self, segment_run_id, *, continuation_manifest_path, expected_continuation_manifest_sha256):
            with self._locked() as rows:
                approval,_=self._audit(rows)
                base=_base(rows,approval,root=b.ROOT,package_config=package_config)
                require(str(Path(segment_run_id).resolve())==base['package']['segment_run_id']
                        and len(rows)==len(base['prefix_rows']),'unique new mapping; no reentry')
                ref={'path':str(Path(continuation_manifest_path).resolve()),'sha256':expected_continuation_manifest_sha256}
                mapping,refs=_mapping(b.ROOT,package_config,base,ref)
                row={'event':EVENT,'segment_run_id':mapping['segment_run_id'],'registration_id':mapping['registration_id'],'mapping':mapping}
                self._audit(rows+[row]);_raw_prefix(self.path,mapping);legacy._fence(refs)
                self._append(row)
                return {'registration':deepcopy(base['registration']),'mapping':deepcopy(mapping)}

        def reserve(self, *, phase, run_id, grant_id, call_id=None, metadata=None):
            with self._locked() as rows:
                _,report=self._audit(rows);mapping=report['preserved_mapping']
                require(mapping is not None and finite(started_monotonic)
                        and same(started_monotonic,mapping['started_monotonic_seconds']) and callable(retained_bytes_provider),
                        'original outer firstclock and whole-scope retained bytes observer required')
                require(not (Path(mapping['segment_run_id'])/'result.json').exists(),'terminal segment cannot reopen')
                resources={'elapsed_seconds':time.monotonic()-started_monotonic,'retained_bytes':retained_bytes_provider()}
                reg=mapping['original_registration']
                row={'event':'reserve','call_id':call_id or str(uuid.uuid4()),'phase':phase,
                     'run_id':str(Path(run_id).resolve()),'grant_id':grant_id,'metadata':metadata or {},
                     'account_before':self.account(rows),'run_account_before':report['recovery_account'],
                     'segment_account_before':report['segment_account'],'amendment_id':reg['amendment_id'],
                     'registration_id':reg['registration_id'],'parent_run_id':mapping['parent_run_id'],
                     'preserved_protocol_segment_id':mapping['preserved_protocol_segment_id'],'preserved_resources_before':resources}
                self._audit(rows+[row]);_raw_prefix(self.path,mapping)
                require(finite(row['metadata'].get('timeout_seconds')) and row['metadata']['timeout_seconds']<=
                        float(_decimal(mapping['remaining']['runner_wall_seconds'],'remaining wall'))-(time.monotonic()-started_monotonic),
                        'remaining time exhausted during admission')
                self._append(row);return row['call_id']

        def finish(self, call_id, status, details=None):
            with self._locked() as rows:
                _,report=self._audit(rows)
                require(call_id in report['segment_account']['pending'],'cannot finish original/foreign/completed call')
                row={'event':'finish','call_id':call_id,'status':status,'details':details or {}}
                self._audit(rows+[row]);_raw_prefix(self.path,report['preserved_mapping'])
                return self._append(row)

        def summary(self, run_id=None):
            with self._locked() as rows:
                if run_id is None:return self.account(rows)
                _,report=self._audit(rows);mapping=report['preserved_mapping']
                require(mapping is not None and str(Path(run_id).resolve()) in
                        (mapping['parent_run_id'],mapping['predecessor_run_id'],mapping['segment_run_id']),'summary outside cumulative lineage')
                return {**report['recovery_account'],'parent_account':report['parent_account'],
                        'segment_account':report['segment_account'],'diagnostic_account_separate':report['diagnostic_account_separate'],
                        'preserved_mapping':mapping,'recovery_mapping':mapping,'inherited':mapping['inherited'],
                        'remaining':mapping['remaining'],'resource_acceptance_verified':False}

        def register_stage_run(self,*args,**kwargs):raise ValueError('preserved segment inherits registration; no cold allowance')
        def register_fresh_segment(self,*args,**kwargs):raise ValueError('cannot replace preserved prefix by fresh interaction')
        def register_recovery_segment(self,*args,**kwargs):raise ValueError('use the one explicit preserved mapping')
        def record_stopped_diagnosis(self,*args,**kwargs):raise ValueError('old pending/unknown evidence is immutable')
        def solver_remaining_seconds(self,arm,run_id=None):return 0.0
        def constructor_remaining_seconds(self,arm,run_id=None):return 0.0
        def reserve_solver(self,*args,**kwargs):raise ValueError('B preserved segment forbids solvers')
        def reserve_constructor(self,*args,**kwargs):raise ValueError('B preserved segment forbids constructors')
    return PreservedSegmentLedger
