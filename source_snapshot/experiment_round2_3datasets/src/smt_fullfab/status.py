"""Reconcile only the new study. Never write historical campaign artifacts."""
from __future__ import annotations
import argparse
import datetime
import hashlib
import json
import math
from pathlib import Path

from .budget import ROOT,BudgetLedger,record_sha256
from .guarded_status import RUNS as GUARDED_RUNS, guarded_result_row


def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def reported_compute_resources(result):
    """Preserve each runner's cost fields; absent measurements remain unknown.

    A's classical construction time includes periodic incumbent construction.
    It is not equivalent to C's separately ledgered constructor tool calls, and
    neither time is additive to the encompassing planner/runner wall time.
    """
    return {key: result.get(key) for key in (
        'solver_calls', 'actual_cp_solve_seconds', 'planner_calls',
        'planner_wall_seconds', 'classical_event_calls',
        'classical_construction_wall_seconds',
        'constructor_calls', 'constructor_requested_seconds',
        'constructor_active_seconds')}


def recovery_acceptance(folder, result, ledger_rows=()):
    """A physical result alone cannot certify recovered model attribution."""
    folder = Path(folder)
    accepted_path, audit_path = folder / 'acceptance.json', folder / 'recovery_audit.json'
    errors = []
    final_wall = None
    if not accepted_path.is_file() or not audit_path.is_file():
        return {'accepted': False, 'errors': ['recovery acceptance or attribution audit is missing']}
    try:
        accepted = json.loads(accepted_path.read_text())
        audit = json.loads(audit_path.read_text())
        if accepted.get('schema') != 'smt-fullfab-recovery-acceptance-v1':
            errors.append('unrecognized recovery acceptance schema')
        for key in ('parent_run_id', 'segment_run_id', 'registration_id', 'recovery_segment_id'):
            if not result.get(key) or accepted.get(key) != result[key]:
                errors.append('recovery acceptance identity mismatch: ' + key)
        if accepted.get('result_sha256') != file_hash(folder / 'result.json'):
            errors.append('recovery result hash mismatch')
        else:
            value = accepted.get('segment_final_wall_seconds')
            if type(value) in (int, float) and math.isfinite(value) and value >= result.get('wall_seconds', 0):
                final_wall = value
        if accepted.get('recovery_audit_sha256') != file_hash(audit_path):
            errors.append('recovery attribution audit hash mismatch')
        finalized = [row['finalization'] for row in ledger_rows
                     if row.get('event') == 'recovery_segment_finalized'
                     and row['finalization'].get('segment_run_id') == result.get('segment_run_id')]
        if len(finalized) != 1:
            errors.append('recovery final audit costs are not uniquely finalized in ledger')
        else:
            final = finalized[0]
            if (final.get('finalization_id') != record_sha256({k:v for k,v in final.items() if k != 'finalization_id'})
                    or final.get('acceptance_sha256') != file_hash(accepted_path)
                    or any(final.get(key) != result.get(key) for key in
                           ('parent_run_id','segment_run_id','registration_id','recovery_segment_id'))
                    or final.get('accepted') != accepted.get('accepted')):
                errors.append('recovery finalization does not bind this accepted result')
        if (folder / 'resource_finalization_error.json').exists():
            errors.append('recovery final resource accounting failed')
        if not (result.get('status') == 'success' and result.get('audit_valid') is True
                and result.get('full_window_completed') is True):
            errors.append('physical full-window execution did not pass')
        if not (accepted.get('accepted') is True and accepted.get('status') == 'success'
                and accepted.get('physical_success') is True
                and accepted.get('controller_evidence_valid') is True
                and accepted.get('successful_full_window') is True and audit.get('valid') is True
                and audit.get('successful_full_window') is True):
            errors.append('recovery attribution acceptance did not pass')
        if accepted.get('resource_overrun') is True:
            errors.append('recovery exceeded its inherited registered resources')
    except (OSError, ValueError, TypeError) as exc:
        errors.append('unreadable recovery acceptance: ' + str(exc))
    return {'accepted': not errors, 'errors': errors, 'end_to_end_wall_seconds': final_wall}


def constructive_acceptance(folder,result,ledger_rows=()):
    """New enabled C cannot pass a stage gate on physical success alone."""
    from .constructor_audit import evidence_inventory
    errors=[];folder=Path(folder)
    def check(ok,message):
        if not ok:errors.append(message)
    try:
        acceptance=json.loads((folder/'controller_acceptance.json').read_text())
        audit=json.loads((folder/'controller_audit.json').read_text())
        registration=json.loads((folder/'resource_registration.json').read_text())
        check(acceptance.get('schema')=='smt-fullfab-constructive-controller-acceptance-v1','missing constructive acceptance schema')
        check(acceptance.get('run_id')==str(folder.resolve()) and acceptance.get('registration_id')==registration['registration_id'],'constructive acceptance identity mismatch')
        for field,path in (('result_sha256','result.json'),('trace_sha256','trace.jsonl'),('controller_audit_sha256','controller_audit.json')):
            check(acceptance.get(field)==file_hash(folder/path),'constructive acceptance hash mismatch: '+path)
        check(acceptance.get('evidence')==evidence_inventory(folder),'constructive raw evidence changed since audit')
        ledger_bytes=Path(acceptance['ledger_path']).read_bytes();n=acceptance['ledger_prefix_bytes']
        check(type(n)is int and 0<n<=len(ledger_bytes) and hashlib.sha256(ledger_bytes[:n]).hexdigest()==acceptance['ledger_prefix_sha256'],'constructive audited ledger prefix changed')
        current_rows=[json.loads(line) for line in ledger_bytes.splitlines() if line.strip()]
        pending={r['call_id'] for r in current_rows if r.get('event')=='constructor_reserve' and
                 r.get('run_id')==str(folder.resolve()) and r.get('registration_id')==registration['registration_id']}-{r['call_id'] for r in current_rows if r.get('event')=='constructor_finish'}
        own_call_ids={r['call_id'] for r in current_rows if r.get('event') in ('reserve','solver_reserve','constructor_reserve') and
                      (r.get('registration_id')==registration['registration_id'] or Path(r.get('run_id','/')).resolve()==folder.resolve() or Path(r.get('run_id','/')).resolve().parent==folder.resolve())}
        later_rows=[json.loads(line) for line in ledger_bytes[n:].splitlines() if line.strip()]
        check(not any(r.get('event') in ('reserve','finish','solver_reserve','solver_finish','constructor_reserve','constructor_finish') and
                      r.get('call_id') in own_call_ids for r in later_rows),'same-run activity appended after sealed controller audit')
        check(not pending and not acceptance.get('pending_constructor_calls'),'constructor still pending')
        check(result.get('status')=='success' and result.get('full_window_completed') is True and result.get('audit_valid') is True,'constructive physical run did not pass')
        check(audit.get('valid') is True and audit.get('successful_full_window') is True,'constructive attribution did not pass')
        check(acceptance.get('accepted') is True and acceptance.get('successful_full_window') is True and acceptance.get('controller_evidence_valid') is True and acceptance.get('physical_success') is True,'constructive acceptance not passed')
        final_wall=acceptance.get('final_wall_seconds')
        check(type(final_wall)in(int,float) and result['wall_seconds']<=final_wall<=registration['wall_seconds'],'constructive end-to-end wall exceeds registration')
        logs=sum(p.stat().st_size for p in folder.rglob('*') if p.is_file())
        check(acceptance.get('final_log_bytes')==logs and logs<=registration['max_log_bytes'] and acceptance.get('resource_overrun') is False,'constructive log/resource cap not certified')
        return {'accepted':not errors,'errors':errors,'end_to_end_wall_seconds':final_wall}
    except (OSError,ValueError,KeyError,TypeError) as exc:
        errors.append('constructive attribution evidence unavailable: '+type(exc).__name__)
        return {'accepted':False,'errors':errors,'end_to_end_wall_seconds':None}


def apply_offline_A_gate(row, folder, *, root=ROOT):
    """The preregistered A 8h run requires its outer resource certificate.

    Match the run identity before looking for any sidecar: a runner result may
    exist while its supervisor is still auditing or may survive a timeout.
    Neither can pass the stage gate merely because acceptance is not yet saved.
    """
    from . import offline_A_gate as gate
    folder = Path(folder).resolve()
    if folder.name == 'A_1701_8h_hybrid_v3':
        from . import offline_A_gate_v3 as gate
    if folder.name != gate.RUN_ID:
        return row
    verified = gate.read_acceptance(root=root)
    errors = list(verified.get('errors', []))
    expected = Path(root).resolve() / 'runs/smt_fullfab_development' / gate.RUN_ID
    if folder != expected:
        errors.append('supervised A result is outside its registered directory')
    if verified.get('result_sha256') != file_hash(folder / 'result.json'):
        errors.append('supervised A certificate does not bind this result')
    certificate = verified.get('acceptance') or {}
    if not verified.get('accepted'):
        errors.extend(certificate.get('errors', []))
    accepted = verified.get('valid') is True and verified.get('accepted') is True and not errors
    effective = dict(row, physical_status=row['status'], physical_audit_valid=row['audit_valid'],
                     offline_supervisor_accepted=accepted, offline_supervisor_errors=errors)
    outer_wall = certificate.get('outer_wall_seconds')
    if type(outer_wall) in (int, float) and math.isfinite(outer_wall) and outer_wall >= row['wall_seconds']:
        effective.update(physical_result_wall_seconds=row['wall_seconds'], wall_seconds=outer_wall)
    effective['audit_valid'] = bool(row['audit_valid'] and accepted)
    if not accepted:
        effective.update(status='failed', failure=row.get('failure') or 'offline_A_supervisor_acceptance_not_passed')
    return effective


def delta_result_row(folder, result, *, root=ROOT):
    """A new B execution report requires its frozen outer certificate.

    The endpoint deliberately reports accepted=False and status=completed;
    neither is a substitute for original-call and complete-resource acceptance.
    Preserve its actual costs even if the supervisor has not finished.
    """
    from . import B_delta_gate as gate
    folder = Path(folder).resolve()
    if folder.name == 'B_1701_1h_delta_v2':
        from . import B_delta_gate_v2 as gate
    elif folder.name == 'B_1701_1h_delta_v3':
        from . import B_delta_gate_v3 as gate
    cfg = result['config']
    physical_wall = result['end_to_end_wall_seconds']
    verified = gate.read_acceptance(root=root)
    certificate = verified.get('acceptance') or {}
    errors = list(verified.get('errors', []))
    if (result.get('schema') != 'smt-fullfab-B-delta-controller-v1-result'
            or folder != Path(root).resolve() / 'runs/smt_fullfab_stage2' / gate.RUN_ID
            or cfg.get('run_id') != gate.RUN_ID or cfg.get('arm') != 'B'):
        errors.append('B delta result schema or registered identity differs')
    if certificate.get('runner_result_sha256') != file_hash(folder / 'result.json'):
        errors.append('B delta supervisor does not bind this original result')
    if not verified.get('accepted'):
        errors.extend(certificate.get('errors', []))
    physical_complete = (result.get('status') == 'completed'
                         and result.get('failure') is None
                         and result.get('finalization_errors') == []
                         and result.get('audit_valid') is True
                         and result.get('delta_attribution_valid') is True
                         and result.get('simulation_seconds') == cfg.get('seconds') == 3600)
    if not physical_complete:
        errors.append('B delta endpoint has not completed its original full window and audits')
    accepted = (verified.get('valid') is True and verified.get('accepted') is True
                and certificate.get('status') == 'success' and not errors)
    outer_wall = certificate.get('outer_wall_seconds')
    wall = outer_wall if (type(outer_wall) in (int, float) and math.isfinite(outer_wall)
                          and outer_wall >= physical_wall) else physical_wall
    return {'run_id': folder.name, 'kind': 'experiment', 'arm': cfg['arm'],
            'scenario': cfg['seed'], 'window_seconds': cfg['seconds'],
            'status': 'success' if accepted else 'failed',
            'physical_status': result['status'], 'physical_audit_valid': result.get('audit_valid', False),
            'full_window_completed': accepted, 'simulation_seconds': result['simulation_seconds'],
            'audit_valid': accepted, 'plans': result['plans'],
            'failure': None if accepted else result.get('failure') or 'B_delta_supervisor_acceptance_not_passed',
            'wall_seconds': wall, 'physical_result_wall_seconds': physical_wall,
            'model_calls': result['model_calls'],
            'solver_requested_seconds': cfg['solver_budget_seconds'],
            **reported_compute_resources(result),
            'delta_supervisor_accepted': accepted, 'delta_supervisor_errors': errors,
            **{k: (result.get('metrics') or {}).get(k) for k in
               ('weighted_tardy_lot_hours', 'throughput_lots', 'terminal_wip_lots', 'terminal_tardy_wip_lots')}}


def inventory(*,write=False):
    ledger=BudgetLedger()
    with ledger._locked() as ledger_rows:
        ledger_history=list(ledger_rows)
    baseline=json.loads((ROOT/'progress/smt_fullfab/history_baseline.json').read_text())
    changed=[name for name,expected in baseline['files'].items() if not (ROOT/name).is_file() or file_hash(ROOT/name)!=expected]
    rows=[];raw={};pending=[]
    for phase in ('smt_fullfab_development','smt_fullfab_stage2'):
        for folder in sorted((ROOT/'runs'/phase).glob('*')):
            if not folder.is_dir():continue
            path=folder/'result.json'
            # These versioned endpoints require host + actual root exit/cost
            # closure. Dispatch before their legacy B schema/C config flags.
            if folder.name in GUARDED_RUNS:
                row=guarded_result_row(folder,root=ROOT)
                row['path']=str(path.relative_to(ROOT));rows.append(row)
                if row['status']=='pending':pending.append(str(folder.relative_to(ROOT)))
                # Do not scan a live multi-GiB tree or re-anchor its result after
                # the adapter's bound readback. Exact terminal evidence remains
                # in the original gate/host certificate, not this old manifest.
                if row['result_sha256'] is not None:
                    raw[str(path.relative_to(ROOT))]={'sha256':row['result_sha256'],'bytes':row['result_bytes']}
                continue
            if not path.exists():
                if (folder/'claim.json').exists():pending.append(str(folder.relative_to(ROOT)))
                continue
            r=json.loads(path.read_text())
            if folder.name.startswith('channel_probe'):
                row={'run_id':folder.name,'kind':'channel_probe','status':r['status'],'full_window_completed':False,'wall_seconds':r['duration_seconds'],'model_calls':1,'solver_requested_seconds':0}
            elif (r.get('schema') == 'smt-fullfab-B-delta-controller-v1-result'
                  or folder.name in ('B_1701_1h_delta_v1', 'B_1701_1h_delta_v2', 'B_1701_1h_delta_v3')):
                row = delta_result_row(folder, r)
            else:
                metrics=r.get('metrics') or {}
                row={'run_id':folder.name,'kind':'experiment','status':r['status'],'arm':r['config']['arm'],
                     'scenario':r['config'].get('seed',1701),'window_seconds':r['config']['seconds'],
                     'full_window_completed':r.get('full_window_completed',False),'simulation_seconds':r['simulation_seconds'],
                     'audit_valid':r.get('audit_valid',False),'plans':r.get('plans',r.get('plans_committed',0)),
                     'failure':r.get('failure'),'wall_seconds':r['wall_seconds'],'model_calls':r['model_calls'],
                     'solver_requested_seconds':r['solver_requested_seconds'],
                     **reported_compute_resources(r),
                     **{k:metrics.get(k) for k in ('weighted_tardy_lot_hours','throughput_lots','terminal_wip_lots','terminal_tardy_wip_lots')}}
                row = apply_offline_A_gate(row, folder)
                if r.get('config',{}).get('enable_constructive') is True:
                    accepted=constructive_acceptance(folder,r,ledger_history)
                    row.update(controller_evidence_accepted=accepted['accepted'],controller_acceptance_errors=accepted['errors'])
                    if accepted['end_to_end_wall_seconds'] is not None:
                        row['physical_result_wall_seconds']=row['wall_seconds'];row['wall_seconds']=accepted['end_to_end_wall_seconds']
                    row['audit_valid']=bool(row['audit_valid'] and accepted['accepted'])
                    if not accepted['accepted']:
                        row['status']='failed';row['failure']=r.get('failure') or 'constructive_controller_acceptance_not_passed'
                if r.get('recovery_segment_id') or r.get('schema') == 'smt-fullfab-B-recovery-result-v1':
                    acceptance = recovery_acceptance(folder, r, ledger_history)
                    row.update(kind='recovery_segment', physical_status=r['status'],
                               physical_audit_valid=r.get('audit_valid', False),
                               recovery_accepted=acceptance['accepted'],
                               recovery_acceptance_errors=acceptance['errors'],
                               **{key:r.get(key) for key in ('parent_run_id','segment_run_id',
                                                          'registration_id','recovery_segment_id')})
                    if acceptance.get('end_to_end_wall_seconds') is not None:
                        row['physical_result_wall_seconds'] = row['wall_seconds']
                        row['wall_seconds'] = acceptance['end_to_end_wall_seconds']
                    row['audit_valid'] = bool(r.get('audit_valid') and acceptance['accepted'])
                    if not acceptance['accepted']:
                        row['status'] = 'failed'
                        row['failure'] = r.get('failure') or 'recovery_acceptance_not_passed'
            row['path']=str(path.relative_to(ROOT));row['result_sha256']=file_hash(path)
            rows.append(row)
            for p in sorted(folder.rglob('*')):
                if p.is_file() and '__pycache__' not in p.parts:
                    raw[str(p.relative_to(ROOT))]={'sha256':file_hash(p),'bytes':p.stat().st_size}
    budget=ledger.summary()
    approval=json.loads((ROOT/'configs/smt_fullfab/stage2_probe.approved.json').read_text())
    waiver=ledger.scoped_limit_waiver('C')
    research_waiver=ledger.research_limit_waiver()
    time_stopped=budget['model_active_seconds']>=approval['total_active_wall_seconds']-1
    original_stopped=bool(budget['unknown_completed'] or budget['pending'] or time_stopped or
                          budget['attempts']>=approval['max_model_attempts'] or
                          budget['reported_input_output_tokens']>=approval['observed_input_output_token_admission_limit'])
    c_stopped=bool(budget['pending'] or time_stopped or ledger.solver_remaining_seconds('C')<0.05) if waiver else original_stopped
    if research_waiver:
        original_stopped=c_stopped=bool(budget['pending'] or budget.get('pending_solver_calls') or budget.get('pending_constructor_calls'))
    short_window_gates={arm:{str(seconds):{
        'passed':any(r.get('arm')==arm and r.get('window_seconds')==seconds and r.get('status')=='success' and r.get('audit_valid') and r.get('full_window_completed') for r in rows),
        'passing_runs':[r['run_id'] for r in rows if r.get('arm')==arm and r.get('window_seconds')==seconds and r.get('status')=='success' and r.get('audit_valid') and r.get('full_window_completed')]}
        for seconds in (3600,28800,86400)} for arm in ('A','B','C')}
    state={'schema':'smt-fullfab-status-2','updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
           'goal_complete':False,'stage':'stage1_and_bounded_stage2_development',
           'historical_files_checked':len(baseline['files']),'historical_files_changed':changed,
           'source_counts_verified':{'production_groups':11,'production_families':105,'production_machines':913,
                                    'virtual_delay_resources':400,'initial_lots':2156,'periodic_release_streams':21},
           'formal_protocol_frozen':False,'formal_runs_completed':0,'official_reference_replication_complete':False,
           'new_budget':{**budget,'authorized_max_attempts':None if research_waiver else approval['max_model_attempts'],
                        'attempts_numerically_remaining_under_original_rule':max(0,approval['max_model_attempts']-budget['attempts']),
                        'known_token_admission_limit':None if research_waiver else approval['observed_input_output_token_admission_limit'],
                        'scoped_C_waiver':waiver,'research_limit_waiver':research_waiver,
                        'aggregate_limit_policy':'waived; immutable per-run resource registrations remain' if research_waiver else 'original proposal plus C scoped waiver',
                        'admission_stopped_by_purpose':{'B':original_stopped,'C':c_stopped},
                        'C_model_activity_seconds_remaining':None if research_waiver else max(0,approval['total_active_wall_seconds']-budget['model_active_seconds']),
                        'legacy_probe_C_solver_requested_seconds_remaining':ledger.solver_remaining_seconds('C')},
           'short_window_gates':short_window_gates,'runs':rows,'incomplete_or_running_paths':pending,
           'offline_solver_requested_seconds':sum(r['solver_requested_seconds'] for r in rows if r['kind']=='experiment' and r.get('arm')=='A'),
           'experiment_activity_wall_seconds':(sum(r['wall_seconds'] for r in rows)
               if all(r['wall_seconds'] is not None for r in rows) else None),
           'experiment_activity_wall_seconds_known_sum':sum(r['wall_seconds'] for r in rows if r['wall_seconds'] is not None),
           'experiment_activity_wall_seconds_unknown_runs':[r['run_id'] for r in rows if r['wall_seconds'] is None],
           'guarded_resource_closure_incomplete_runs':[r['run_id'] for r in rows if r.get('guarded_status_version') and not r.get('wall_seconds_complete')],
           'raw_evidence_scope':'legacy run trees; guarded versions include only the original result receipt here and retain complete evidence in their gate/host certificates',
           'raw_evidence_files':len(raw),'raw_evidence_bytes':sum(v['bytes'] for v in raw.values()),
           'blockers':(['B has a completed timeout with unknown usage; its original stop rule remains active'] if budget['unknown_completed'] and not research_waiver else [])+
                      (['An attempt is open: serialize execution and reconcile it before any further admission' if research_waiver else 'C remaining time or solver allowance exhausted, or a pending attempt requires diagnosis'] if c_stopped else [])+
                      ['Official saved reference uses a different due-date/service-level configuration and unaligned runtime semantics'],
           'remaining':['A/B/C full 1h/8h/24h execution and cost gates','Warmup stability and paired full snapshot selection',
                        'Independent-seed discrimination, variance/MDE and window/frequency sensitivity',
                        'Formal protocol, sample matrix and preregistered comparable resources','Formal runs, replay, Chinese report and independent acceptance'],
           'next_command':'.venv/bin/python -m src.smt_fullfab.status',
           'model_resume_condition':('Research-wide model call/token limits waived by user; register each new stage2 run before calls. Preserve pending-attempt checks and 180s per-call timeout, separate A/C comparable solver budgets, immutable history, and formal preregistration.' if research_waiver else 'C scoped waiver is active only for scenario1701/1h within unchanged time and solver limits; B and expanded stages require explicit bounded authorization. Never edit/delete prior reservations.'),
           'recovery_command':'.venv/bin/python -m src.smt_fullfab.recovery_check runs/smt_fullfab_development/A_1701_1h_hybrid_v1'}
    if write:
        dest=ROOT/'progress/smt_fullfab'
        (dest/'STATUS.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
        (dest/'evidence-manifest.json').write_text(json.dumps({'schema':'smt-fullfab-local-evidence-1','files':raw,
                    'note':'Exact raw model outputs are local evidence and cannot be regenerated by a new stochastic call.'},indent=2)+'\n')
        with ledger._locked() as history:
            prior={r['run_path']:r for r in history if r['event']=='offline_run_observed'}
            for row in rows:
                if row.get('arm') not in ('A','reference_cr','reference_fifo','reference_edd'):continue
                if row['path'] in prior:
                    if prior[row['path']]['result_sha256']!=row['result_sha256']:raise ValueError('completed offline result changed')
                    continue
                ledger._append({'event':'offline_run_observed','run_path':row['path'],'result_sha256':row['result_sha256'],
                                'status':row['status'],'solver_requested_seconds':row['solver_requested_seconds'],
                                'wall_seconds':row['wall_seconds'],'cost_usd':None,
                                'admission_evidence':'immutable per-run config/claim precedes its local resources.jsonl reservations; centralized after completion'})
        with (dest/'iterations.jsonl').open('a') as f:
            f.write(json.dumps({'at':state['updated_at'],'event':'reconcile','historical_changed':changed,
                      'completed_record_count':len(rows),'budget':budget,'goal_complete':False},ensure_ascii=False)+'\n')
    return state


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--write',action='store_true');a=p.parse_args()
    state=inventory(write=a.write)
    print(json.dumps({k:v for k,v in state.items() if k not in ('runs','remaining','source_counts_verified')},ensure_ascii=False,indent=2))
    raise SystemExit(1 if state['historical_files_changed'] else 0)
