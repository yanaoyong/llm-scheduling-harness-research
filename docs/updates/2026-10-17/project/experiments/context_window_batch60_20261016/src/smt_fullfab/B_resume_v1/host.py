"""Frozen explicit recovery host. Original model channel; no automatic retries."""
import time
FIRST_CLOCK = time.monotonic()
import argparse
from functools import partial
import hashlib
import os
import stat
import json
from pathlib import Path
import sys
import datetime
import traceback


def bound(path, *, keep=False):
    path=Path(path)
    ident=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    fd=os.open(path,os.O_RDONLY | getattr(os,'O_NOFOLLOW',0)); parts=[]; h=hashlib.sha256()
    with os.fdopen(fd,'rb') as f:
        before=os.fstat(f.fileno()); assert stat.S_ISREG(before.st_mode)
        for block in iter(lambda:f.read(1024*1024),b''):
            h.update(block)
            if keep:parts.append(block)
        identity=ident(before)
        assert identity==ident(os.fstat(f.fileno()))==ident(path.stat())
    return h.hexdigest(),identity,b''.join(parts) if keep else None


def sha(path):return bound(path)[0]


def new(path,value):
    with Path(path).open('x') as f:
        json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
    return sha(path)


def identities(paths):
    return {str(p):(p.stat().st_dev,p.stat().st_ino,p.stat().st_size,p.stat().st_mtime_ns,p.stat().st_ctime_ns) for p in paths}


def main(campaign, expected_manifest):
    campaign=Path(campaign).resolve(); manifest_path=campaign/'manifest.json'
    actual,manifest_identity,manifest_raw=bound(manifest_path,keep=True)
    assert actual==expected_manifest
    manifest=json.loads(manifest_raw); root=Path(manifest['root']); frozen=campaign/'frozen'
    assert Path(__file__).resolve().is_relative_to(frozen)
    sys.path.insert(0,str(frozen))
    pins={str(manifest_path):manifest_identity}
    for name,expected in manifest['runtime_files'].items():
        p=frozen/name;actual,identity,_=bound(p);assert actual==expected,name;pins[str(p)]=identity
    for name,expected in manifest['parent_inputs'].items():
        p=root/name;actual,identity,_=bound(p);assert actual==expected,name;pins[str(p)]=identity
    def fence():
        assert identities([Path(x) for x in pins])==pins,'Frozen runtime/parent evidence changed'
    from src.smt_fullfab import budget as original_budget
    from src.smt_fullfab.B_incremental_v3 import controller,transport
    from src.smt_fullfab.B_resume_v1 import admission,resume_binding,resume_controller,resume_bridge,fresh_bridge,fork_store,acceptance
    # Same explicit actual-ledger/root routing used by the original frozen gate.
    original_budget.ROOT=root;controller.ROOT=root;controller.DEFAULT_LEDGER=root/'progress/smt_fullfab/model_ledger.jsonl'
    ledger_path=controller.DEFAULT_LEDGER;segment=root/manifest['segment'];parent=root/manifest['parent']
    clock={'schema':'smt-B-v7-recovery-first-clock-v1','segment_run_id':str(segment),
           'started_monotonic_seconds':FIRST_CLOCK,'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    clock_sha=new(campaign/'first_clock.json',clock)
    sources_sha=new(campaign/'runtime_source_manifest.json',manifest['runtime_files'])
    package={**manifest['package_static'],'first_clock':{'path':str(campaign/'first_clock.json'),'sha256':clock_sha},
             'runtime_source_manifest':{'path':str(campaign/'runtime_source_manifest.json'),'sha256':sources_sha}}
    package_sha=new(campaign/'recovery_package.json',package)
    package_config={'path':str(campaign/'recovery_package.json'),'sha256':package_sha}
    resume_binding.configure_admission(admission,package_config=package_config)
    def retained():
        return sum(p.stat().st_size for base in (campaign,segment) if base.exists() for p in base.rglob('*') if p.is_file())
    Ledger=admission.make_ledger_class(original_budget,package_config=package_config,
        started_monotonic=FIRST_CLOCK,retained_bytes_provider=retained)
    ledger=Ledger(ledger_path)
    with ledger._locked() as ledger_rows:
        approval=[r['approval'] for r in ledger_rows if r['event']=='approval'][0]
        checked=admission.preflight_recovery(ledger_rows,approval,root=root,package_config=package_config)
    new(campaign/'admission_preflight.json',checked)
    registration=checked['registration']
    envelope={'segment_run_id':str(segment),'parent_run_id':str(parent),
              'remaining_runner_wall_seconds':float(package['remaining_wall_seconds']),
              'remaining_log_bytes':package['remaining_log_bytes'],'per_call_timeout_seconds':600,
              'registration':registration,'ledger_path':str(ledger_path)}
    disabled=[str(p) for p in transport._disabled_skills()]
    assert disabled==manifest['disabled_skill_paths'],'native isolation inventory changed'
    def authority():
        fence()
        return {'ledger_path':str(ledger_path),'ledger_before_sha256':sha(ledger_path),
            'approval_sha256':original_budget.record_sha256(approval),'registration_id':registration['registration_id'],
            'registration_sha256':original_budget.record_sha256(registration),'disabled_skill_paths':disabled}
    def register(fork_path,fork_sha):
        fence()
        return ledger.register_recovery_segment(str(segment),fork_manifest_path=fork_path,
                                               expected_fork_manifest_sha256=fork_sha)
    def invoke(*args,**kwargs):
        fence()
        try:return transport.call_model(*args,**kwargs,ledger_factory=Ledger)
        finally:fence()
    record={'schema':'smt-B-v7-resume-host-result-v1','accepted':False,'parent_status':'failed',
        'goal_complete':False,'manifest_sha256':expected_manifest,'package_sha256':package_sha,
        'status':'failed','errors':[],'cost_usd':None,'automatic_retry':False}
    try:
        result=resume_controller.run_segment(str(segment),parent_contract=manifest['parent_contract'],
            admission=envelope,external_authorization_sha256=package_sha,controller=controller,
            fork_bridge=resume_bridge,fresh_bridge=fresh_bridge,transport_call=invoke,
            authorization_for_call=authority,register_after_fork=register,started_monotonic=FIRST_CLOCK)
        fence()
        assert result['full_window_completed'] and result['status']=='completed_pending_external_audit'
        # Hold original first-read inventory across all independent terminal work.
        terminal_files={};terminal_identity={}
        for p in sorted(segment.rglob('*')):
            if p.is_file():
                actual,identity,_=bound(p);terminal_files[str(p)]=actual;terminal_identity[str(p)]=identity
        new(campaign/'first_terminal_inventory.json',terminal_files)
        a=acceptance.attribution(segment,parent=parent,controller=controller,fork_store=fork_store,
                                 transport=transport,ledger_path=ledger_path)
        new(campaign/'attribution.json',a)
        summary,bundle=controller.stream_audit(segment/'physical/trace.jsonl',campaign,
            data_dir=frozen/'data/smt/SMT2020_LVHM',window_start=0.0)
        new(campaign/'physical_audit.json',{'summary':summary,'bundle':bundle})
        assert a['valid'] and summary['valid'] and summary['complete_physical_window_certified']
        assert identities([Path(x) for x in terminal_files])==terminal_identity
        assert all(sha(Path(p))==expected for p,expected in terminal_files.items())
        fence()
        record.update(status='completed_pending_outer_resource_check',attribution_sha256=sha(campaign/'attribution.json'),
            physical_audit_sha256=sha(campaign/'physical_audit.json'),metrics=summary['metrics'],
            full_window_completed=True,simulation_seconds=3600.0)
    except BaseException as exc:
        record['errors'].append({'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()})
    finally:
        try:
            raw=ledger_path.read_bytes();rows=[json.loads(x) for x in raw.splitlines()]
            account=admission.audit_admissions(rows,approval,root=root,package_config=package_config)
            assert not account['errors'] and not account['missing_evidence']
            with (campaign/'ledger_final.jsonl').open('xb') as f:f.write(raw)
            new(campaign/'ledger_final_account.json',{k:account[k] for k in
                ('parent_account','segment_account','diagnostic_account_separate','recovery_account','unknown_usage_call_ids','stopped_pending')})
            record.update(ledger_final_sha256=sha(campaign/'ledger_final.jsonl'),
                account_sha256=sha(campaign/'ledger_final_account.json'),segment_account=account['segment_account'],
                cumulative_parent_segment_account=account['recovery_account'])
            fence()
        except BaseException as exc:
            record['status']='failed';record['errors'].append({'stage':'account_or_source_fence','type':type(exc).__name__,'message':str(exc)})
        record['host_wall_seconds_before_publication']=time.monotonic()-FIRST_CLOCK
        record['retained_bytes_before_publication']=retained()
        if record['host_wall_seconds_before_publication']>float(package['remaining_wall_seconds']) or retained()>package['remaining_log_bytes']:
            record['status']='failed';record['errors'].append({'stage':'resources','message':'inherited remaining wall/log allowance exceeded'})
        new(campaign/'host_result.json',record)
    print(json.dumps({'status':record['status'],'accepted':False,'host_result_sha256':sha(campaign/'host_result.json')}))
    return 0 if record['status']=='completed_pending_outer_resource_check' else 1


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--campaign',required=True);p.add_argument('--manifest-sha256',required=True)
    a=p.parse_args();raise SystemExit(main(a.campaign,a.manifest_sha256))
