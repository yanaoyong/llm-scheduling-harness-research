"""Single frozen B-delta 1h development gate. Default prepare; no automatic retry.

The supervisor does not import a factory or model transport. Only --execute
launches the frozen controller; readback runs frozen read-only evidence checks.
Local channel evidence cannot independently authenticate a backend/model.
"""
from __future__ import annotations
import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from .offline_pilot import (ROOT, DATA, VENDOR, _sha, _digest, _read, _write,
    _runtime, _origin_git, _git_pointer, _serial_lock, _launch)
from .offline_A_gate_v3 import (AUDIT_DEPENDENCIES,
    _active_with_finalizers, _read_bound_json)

RUN_ID='B_1701_1h_delta_v1'
PROTOCOL='configs/smt_fullfab/B_delta_1h_v1.protocol.json'
AREA='runs/smt_fullfab_B_delta_gate'
SCHEMA='smt-fullfab-B-delta-gate-v1'
APPROVAL='configs/smt_fullfab/stage2_probe.approved.json'
WAIVER='configs/smt_fullfab/research_limit_waiver.approved.json'
LEDGER='progress/smt_fullfab/model_ledger.jsonl'
CHILD_SECONDS=21600
OUTER_SECONDS=22200
VERIFY_SECONDS=600
MIN_FREE_BYTES=40*1024**3
TRACE_BYTES=2*1024**3
MAX_BYTES=16*1024**3
PEAK_RSS_BYTES=8*1024**3
PRIOR_ATTEMPTS=240
CLI_PATH='/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex'
CLI_EXECUTABLE_PATH='/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'
PARAMETERS={'run_id':RUN_ID,'scenario':1701,'seconds':3600,'wall_seconds':21600.0,
    'max_log_bytes':MAX_BYTES,'max_trace_bytes':TRACE_BYTES,'page_chars':45000}
SOURCE_CONVENTION='sha256(json.dumps(relative_path_to_sha256,sort_keys=True,separators=(comma,colon),ensure_ascii=True,allow_nan=False).encode(utf-8))'


def require(ok,message):
    if not ok:raise ValueError(message)


def same(a,b):return json.dumps(a,sort_keys=True,separators=(',',':'),allow_nan=False)==json.dumps(b,sort_keys=True,separators=(',',':'),allow_nan=False)

def _raw(path):
    # Reuse the bound reader's identity fence, but retain original bytes too.
    path=Path(path);before=path.lstat()
    identity=lambda info:(info.st_dev,info.st_ino,info.st_mode,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
    require(not path.is_symlink() and path.is_file(),'nonregular evidence: '+str(path))
    with path.open('rb') as stream:
        require(identity(os.fstat(stream.fileno()))==identity(before),'evidence changed before read')
        raw=stream.read();after=os.fstat(stream.fileno())
    require(identity(before)==identity(after)==identity(path.lstat()),'evidence changed during read')
    return raw


def _strict(raw):
    def pairs(items):
        value={}
        for key,item in items:
            require(key not in value,'duplicate JSON key');value[key]=item
        return value
    value=json.loads(raw,object_pairs_hook=pairs)
    same(value,value)  # Reject nonfinite values, including exponent overflow.
    return value


def _config(protocol):
    require(protocol.get('schema')==SCHEMA+'-protocol' and protocol.get('formal') is False
        and protocol.get('execute_now') is False and same(protocol.get('run_parameters'),PARAMETERS),'only fixed new B1h protocol permitted')
    expected={'serial_only':True,'external_watchdog_seconds':OUTER_SECONDS,'child_complete_wall_seconds':CHILD_SECONDS,
        'readback_seconds':VERIFY_SECONDS,'minimum_free_disk_bytes':MIN_FREE_BYTES,'maximum_child_peak_rss_bytes':PEAK_RSS_BYTES,
        'rss_is_hard_guard':False,'trace_bytes':TRACE_BYTES,'campaign_and_run_bytes':MAX_BYTES,
        'minimum_preserved_prior_model_attempts':PRIOR_ATTEMPTS,'model':'gpt-6-astra','reasoning_effort':'medium',
        'per_call_timeout_seconds':180,'max_calls':None,'max_tokens':None,'solver_seconds':0,'constructor_seconds':0,
        'plan_seconds':14400,'lookahead_depth':2,'period_seconds':1800,'period_is_absolute':True}
    require(same(protocol.get('limits'),expected),'fixed protocol limits differ')
    return dict(PARAMETERS)


def _input_paths(root):
    paths=[]
    for name in ('src',VENDOR,DATA):
        base=root/name;require(base.is_dir() and not base.is_symlink(),'missing/linked frozen directory')
        for path in sorted(base.rglob('*')):
            if '__pycache__' in path.parts or path.suffix in ('.pyc','.pyo'):continue
            require(not path.is_symlink(),'linked frozen input')
            if path.is_file():paths.append(path)
    paths+=sorted(root.glob('requirements*'))+[root/PROTOCOL,root/APPROVAL,root/WAIVER]
    require(root/'requirements.lock' in paths,'requirements.lock missing')
    require(all(p.is_file() and not p.is_symlink() for p in paths),'nonregular frozen input')
    return sorted(set(paths))


def _inventory(root):return {p.relative_to(root).as_posix():_sha(p) for p in _input_paths(root)}

def _runtime_capture():
    cli=Path(CLI_PATH).resolve();binary=Path(CLI_EXECUTABLE_PATH).resolve()
    require(cli.is_file() and binary.is_file(),'model CLI wrapper/executable runtime missing')
    return {'python':_runtime(),'model_cli':{'path':CLI_PATH,'resolved_path':str(cli),'sha256':_sha(cli),
        'executable_path':CLI_EXECUTABLE_PATH,'executable_resolved_path':str(binary),'executable_sha256':_sha(binary)}}


def _sources(inputs):return {k:v for k,v in inputs.items() if k not in (PROTOCOL,APPROVAL,WAIVER)}


def _ledger_rows(raw):
    return [_strict(line) for line in raw.splitlines() if line.strip()]


def _ledger_preflight(raw,root,*,require_unused=True):
    rows=_ledger_rows(raw);approval=_strict(_raw(root/APPROVAL));waiver=_strict(_raw(root/WAIVER))
    require([r['approval'] for r in rows if r.get('event')=='approval']==[approval],'actual original approval differs')
    require([r['amendment'] for r in rows if r.get('event')=='research_limit_waiver']==[waiver],'actual research waiver differs')
    reserves=[r for r in rows if r.get('event') in ('reserve','solver_reserve','constructor_reserve')]
    finishes=[r for r in rows if r.get('event') in ('finish','solver_finish','constructor_finish')]
    ids=[r['call_id'] for r in reserves];done=[r['call_id'] for r in finishes]
    require(len(ids)==len(set(ids)) and len(done)==len(set(done)) and set(done)==set(ids),'original ledger has duplicate/pending/orphan calls')
    attempts=sum(r['event']=='reserve' for r in reserves)
    require(attempts>=PRIOR_ATTEMPTS,'original cumulative model history is missing/reset')
    target=(root/'runs/smt_fullfab_stage2'/RUN_ID).resolve()
    if require_unused:
        for row in rows:
            value=row.get('registration',row)
            if value.get('run_id') is not None:
                path=Path(value['run_id']).resolve()
                require(path!=target and target not in path.parents,'target has prior registration/call; cannot restart')
    return {'original_model_attempts':attempts,'prefix_sha256':hashlib.sha256(raw).hexdigest(),'prefix_bytes':len(raw)}


def _ledger_domain(rows,run,registration_id):
    """Same complete ordered event domain as controller.account_from_rows.

    Do not filter by event name: notes, mappings and finalizations can change
    attribution too. Registration and reserved call identities close the domain.
    """
    run=Path(run).resolve()
    def records(row):
        return [row]+[row[k] for k in ('registration','mapping','finalization') if type(row.get(k))is dict]
    def own_path(row):
        for record in records(row):
            for key in ('run_id','parent_run_id','segment_run_id'):
                if type(record.get(key))is str:
                    path=Path(record[key]).resolve()
                    if path==run or run in path.parents:return True
        return False
    registrations={record['registration_id'] for row in rows if own_path(row)
        for record in records(row) if type(record.get('registration_id'))is str}
    registrations.add(registration_id)
    def own_domain(row):
        return own_path(row) or any(record.get('registration_id') in registrations for record in records(row))
    starts=[r for r in rows if r.get('event') in ('reserve','solver_reserve','constructor_reserve') and own_domain(r)]
    ids=[r['call_id'] for r in starts]
    require(len(ids)==len(set(ids)),'duplicate original reservation')
    selected=[r for r in rows if r.get('call_id') in set(ids) or own_domain(r)]
    return {'registration_ids':sorted(registrations),'reserve_call_ids':ids,
        'run_events_count':len(selected),'run_events_sha256':_digest(selected)}


def _ledger_unchanged_for_run(sealed,live,run,registration_id):
    require(live.startswith(sealed),'actual ledger no longer extends original snapshot')
    require(_ledger_domain(_ledger_rows(sealed),run,registration_id)==_ledger_domain(_ledger_rows(live),run,registration_id),
        'same run/registration/call identity has new resource events or attribution events after sealed account')


def _command(campaign,manifest,*,executable=None):
    bootstrap="""import sys,os,json,datetime,resource
frozen,origin,pidfile,usagefile=sys.argv[1:5];del sys.argv[1:5]
sys.path.insert(0,frozen)
with open(pidfile,'x') as f:
 json.dump({'pid':os.getpid(),'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()},f);f.write('\\n');f.flush();os.fsync(f.fileno())
try:
 from pathlib import Path
 from src.smt_fullfab import controller_delta as d, budget
 d.ROOT=Path(origin);budget.ROOT=Path(origin)
 d.DEFAULT_LEDGER=Path(origin)/'progress/smt_fullfab/model_ledger.jsonl'
 d.APPROVAL=Path(frozen)/'configs/smt_fullfab/stage2_probe.approved.json'
 raise SystemExit(d.main())
finally:
 raw=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
 unit='bytes' if sys.platform=='darwin' else 'KiB' if sys.platform.startswith('linux') else 'unsupported'
 value={'schema':'smt-child-peak-rss-v1','pid':os.getpid(),'platform':sys.platform,'source':'resource.getrusage(RUSAGE_SELF).ru_maxrss','raw_maxrss':raw,'raw_unit':unit,'peak_rss_bytes':raw*(1024 if unit=='KiB' else 1) if unit!='unsupported' else None,'hard_memory_guard':False}
 with open(usagefile,'x') as f:json.dump(value,f);f.write('\\n');f.flush();os.fsync(f.fileno())
"""
    return [executable or sys.executable,'-I','-B','-c',bootstrap,str(campaign/'frozen'),manifest['origin_root'],
        str(campaign/'child_started.json'),str(campaign/'child_usage.json'),'run','--run-id',RUN_ID,
        '--expected-source-sha256',manifest['source_sha256'],'--wall-seconds',str(CHILD_SECONDS),
        '--max-log-bytes',str(MAX_BYTES),'--max-trace-bytes',str(TRACE_BYTES)]


def prepare(*,root=ROOT):
    root=Path(root).resolve();campaign=root/AREA/RUN_ID;target=root/'runs/smt_fullfab_stage2'/RUN_ID
    if campaign.exists():
        manifest=_read(campaign/'manifest.json');verify_frozen(campaign,manifest,for_execution=False)
        require(_sha(root/PROTOCOL)==manifest['protocol_sha256'],'registered protocol changed')
        return campaign,manifest
    begun=time.monotonic();config=_config(_read(root/PROTOCOL))
    require(not target.exists(),'existing target cannot be adopted/restarted')
    ledger=_raw(root/LEDGER);prior=_ledger_preflight(ledger,root)
    inputs,runtime,head=_inventory(root),_runtime_capture(),_origin_git(root)
    campaign.mkdir(parents=True,exist_ok=False);frozen=campaign/'frozen';frozen.mkdir()
    try:
        for relative,expected in inputs.items():
            raw=_raw(root/relative);require(hashlib.sha256(raw).hexdigest()==expected,'input changed during freeze')
            path=frozen/relative;path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb') as stream:stream.write(raw)
            path.chmod(0o444)
        require(inputs==_inventory(root) and runtime==_runtime_capture(),'input/runtime changed during freeze')
        with (campaign/'ledger_at_prepare.jsonl').open('xb') as stream:stream.write(ledger)
        for name in ('runs','progress'):
            require((root/name).is_dir(),'original mapped directory missing')
            (frozen/name).symlink_to(root/name,target_is_directory=True)
        _git_pointer(frozen,head)
        manifest={'schema':SCHEMA+'-frozen','run_id':RUN_ID,'origin_root':str(root),'origin_git_head':head,
            'origin_git_note':'origin pointer only; file inventory includes dirty code, not a clean checkout',
            'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'config':config,'output_directory':str(target),
            'frozen_input_sha256':inputs,'source_sha256':_digest(_sources(inputs)),'source_hash_convention':SOURCE_CONVENTION,
            'protocol_sha256':inputs[PROTOCOL],'runtime':runtime,'launcher_executable':sys.executable,
            'actual_ledger_path':str((root/LEDGER).resolve()),'prior_ledger':prior,
            'prepare_wall_seconds':time.monotonic()-begun}
        manifest['child_command']=_command(campaign,manifest);manifest['identity']=_digest(manifest)
        _write(campaign/'manifest.json',manifest);verify_frozen(campaign,manifest)
        return campaign,manifest
    except Exception as exc:
        _write(campaign/'freeze_failure.json',{'status':'failed','error':str(exc)});raise


def verify_frozen(campaign,manifest,*,for_execution=True):
    campaign=Path(campaign).resolve();root=Path(manifest['origin_root']);frozen=campaign/'frozen'
    require(manifest.get('schema')==SCHEMA+'-frozen' and manifest.get('identity')==_digest({k:v for k,v in manifest.items() if k!='identity'})
        and campaign==root/AREA/RUN_ID and manifest.get('run_id')==RUN_ID
        and manifest.get('output_directory')==str(root/'runs/smt_fullfab_stage2'/RUN_ID),'frozen identity/path differs')
    require(same(_strict(_raw(campaign/'manifest.json')),manifest),'manifest file differs from supplied original identity')
    require(type(manifest.get('prepare_wall_seconds'))in(int,float) and math.isfinite(manifest['prepare_wall_seconds'])
        and manifest['prepare_wall_seconds']>=0,'invalid original preparation wall')
    inputs=_inventory(frozen)
    require(inputs==manifest['frozen_input_sha256'] and _digest(_sources(inputs))==manifest['source_sha256']
        and manifest['source_hash_convention']==SOURCE_CONVENTION,'frozen source/data hash differs')
    require(all(not (frozen/k).stat().st_mode&0o222 for k in inputs),'frozen input writable')
    require(_config(_read(frozen/PROTOCOL))==manifest['config'] and inputs[PROTOCOL]==manifest['protocol_sha256'],'frozen protocol changed')
    for name in ('runs','progress'):
        require((frozen/name).is_symlink() and (frozen/name).resolve()==root/name,'actual output/ledger mapping changed')
    require(manifest['actual_ledger_path']==str((root/LEDGER).resolve()) and _origin_git(frozen)==manifest['origin_git_head'],'origin ledger/git pointer changed')
    prior=_raw(campaign/'ledger_at_prepare.jsonl')
    require(hashlib.sha256(prior).hexdigest()==manifest['prior_ledger']['prefix_sha256'] and len(prior)==manifest['prior_ledger']['prefix_bytes'],'original historical ledger changed')
    require(_raw(root/LEDGER).startswith(prior),'original cumulative ledger was reset')
    if for_execution:
        require(_runtime_capture()==manifest['runtime'] and sys.executable==manifest['launcher_executable'],'runtime changed')
        require(_command(campaign,manifest)==manifest['child_command'],'frozen child invocation differs')
        for name in ('B_delta_gate.py','offline_pilot.py','offline_A_gate_v3.py'):
            require(inputs['src/smt_fullfab/'+name]==_sha(Path(__file__).with_name(name)),'use frozen gate/helper bytes')


def _files(base,*,campaign=False):
    if not base.exists():return []
    result=[]
    for path in sorted(base.rglob('*')):
        if path.is_symlink():
            if campaign and path in (base/'frozen/runs',base/'frozen/progress'):continue
            raise ValueError('unexpected evidence symlink')
        if path.is_file():result.append(path)
    return result


def _evidence(campaign,run):return {prefix+'/'+p.relative_to(base).as_posix():_sha(p) for prefix,base in (('campaign',campaign),('run',run)) for p in _files(base,campaign=prefix=='campaign') if p!=campaign/'acceptance.json'}

def _bytes(campaign,run):return sum(p.stat().st_size for p in _files(campaign,campaign=True)+_files(run))


def _bind(verified,evidence):
    require(type(verified)is dict and verified and {k:v for k,v in evidence.items() if k.startswith('run/')}==verified,'final evidence differs from original verification anchors')


def _campaign_anchors(campaign):
    return {'campaign/'+p.relative_to(campaign).as_posix():_sha(p) for p in _files(campaign,campaign=True)
        if p.name not in ('verification.json','acceptance.json') or p.parent!=campaign}


def _bind_campaign(anchors,evidence,*,exact=True):
    actual={k:v for k,v in evidence.items() if k.startswith('campaign/') and k not in ('campaign/verification.json','campaign/acceptance.json')}
    require(type(anchors)is dict and anchors and (actual==anchors if exact else all(actual.get(k)==v for k,v in anchors.items())),
        'campaign evidence differs from original verification anchors')


def _checkpoint(run,reference,inputs):
    from .environment import VERSION,snapshot_dependencies
    require(type(reference)is dict and set(reference)=={'path','state_sha256','file_sha256'} and reference['path']=='checkpoint.json','checkpoint reference invalid')
    checkpoint=_read_bound_json(run/'checkpoint.json',reference['file_sha256']);state=checkpoint['state']
    require(checkpoint.get('schema')=='smt-fullfab-snapshot-1' and checkpoint.get('version')==VERSION
        and checkpoint.get('state_sha256')==reference['state_sha256']==_digest(state)
        and checkpoint.get('implementation_sha256')==snapshot_dependencies()
        and checkpoint.get('physics_sha256')==inputs['src/smt/environment.py'],'checkpoint schema/state/dependencies differ')
    require(set(state)==set(('seed','horizon','t','seq','dispatch_id','decisions','releases','completed','finished','wait_until',
        'lots','machine_state','jobs','calendars','pm_counters','queue_area','last_area_t','manifest','plan','observation_start',
        'q','waiting','processing_by_machine','stats','executed_tasks','plan_versions','trace')),'checkpoint state fields incomplete/extra')
    require(type(state['seed'])is int and state['finished'] is True and state['t']==state['horizon']==3600 and state['seed']==1701 and state['observation_start']==0,'checkpoint is not original full cold window')
    data={Path(k).name:v for k,v in inputs.items() if k.startswith(DATA+'/')}
    require(checkpoint['data_hashes']==state['manifest']['data_hashes']==data,'checkpoint source data differs')
    count=0
    with (run/'trace.jsonl').open('rb') as stream:
        for line in stream:
            if not line.strip():continue
            require(count<len(state['trace']) and same(_strict(line),state['trace'][count]),'checkpoint history differs from raw trace')
            count+=1
    require(count==len(state['trace']) and count>0 and state['trace'][-1]['kind']=='terminal','checkpoint omits/adds raw trace')
    return {'state_sha256':checkpoint['state_sha256'],'file_sha256':reference['file_sha256'],'trace_events':count,'restoration_executed':False}


def _verification_payload(run,manifest):
    """Frozen subprocess: read-only audits, no recovery/model/physical execution."""
    from . import controller_delta as d,budget
    from .stream_audit_bundle import read_bundle
    root=Path(manifest['origin_root']);run=Path(run).resolve();inputs=manifest['frozen_input_sha256']
    d.ROOT=root;budget.ROOT=root;d.DEFAULT_LEDGER=root/LEDGER
    verified={'run/'+p.relative_to(run).as_posix():_sha(p) for p in _files(run)}
    result_sha=verified['run/result.json'];result=_read_bound_json(run/'result.json',result_sha)
    def bound(name,expected=None):
        digest=expected or verified['run/'+name]
        require(verified.get('run/'+name)==digest,'validated file differs from initial readback anchor')
        return _read_bound_json(run/name,digest)
    cfg=bound('config.json');source=bound('source_manifest.json');provenance=bound('provenance.json')
    expected={'schema':d.SCHEMA,'arm':'B','run_id':RUN_ID,'seed':1701,'seconds':3600,'source_sha256':manifest['source_sha256'],
        'max_calls':None,'max_tokens':None,'per_call_timeout_seconds':180,'wall_seconds':float(CHILD_SECONDS),
        'max_log_bytes':MAX_BYTES,'max_trace_bytes':TRACE_BYTES,'page_chars':45000,'plan_seconds':14400,'lookahead_depth':2,
        'period_seconds':1800,'solver_budget_seconds':0,'constructor_enabled':False,'audit_mode':'stream','snapshot_mode':'stream',
        'cold_start_only':True,'automatic_retry':False,'formal':False,'budget_id':_read(Path(__file__).parents[2]/APPROVAL)['budget_id'],
        'amendment_id':_read(Path(__file__).parents[2]/WAIVER)['amendment_id'],'resource_acceptance_requires_external_gate':True}
    require(same(cfg,expected) and same(result.get('config'),cfg) and result.get('identity')==_digest(cfg),'controller config/identity differs')
    require(source.get('files')==_sources(inputs) and source.get('source_sha256')==manifest['source_sha256']
        and source.get('canonical_hash_convention')==SOURCE_CONVENTION,'controller source inventory differs')
    sources={k:v for k,v in inputs.items() if Path(k).parent.as_posix() in ('src/smt','src/smt_fullfab') and k.endswith('.py')}
    require(provenance.get('source_sha256')==sources and provenance.get('requirements_sha256')==inputs['requirements.lock']
        and provenance.get('git_commit')==manifest['origin_git_head'],'controller provenance differs')
    for name,digest in {**sources,'src/__init__.py':inputs['src/__init__.py']}.items():
        require(verified.get('run/source_snapshot/'+name)==digest and _sha(run/'source_snapshot'/name)==digest,'saved source bytes differ')
    require(result.get('status')=='completed' and result.get('failure') is None and result.get('finalization_errors')==[]
        and result.get('accepted') is False and result.get('formal') is False and result.get('simulation_seconds')==3600
        and result.get('audit_valid') is True and result.get('delta_attribution_valid') is True
        and result.get('solver_calls')==result.get('constructor_calls')==0,'controller terminal is not complete/valid B')
    require(type(result.get('end_to_end_wall_seconds'))in(int,float) and math.isfinite(result['end_to_end_wall_seconds'])
        and 0<=result['end_to_end_wall_seconds']<=CHILD_SECONDS and result.get('resource_overrun') is not True,'controller resource result invalid')
    bundle_ref=result['audit_bundle'];require(set(bundle_ref)=={'path','manifest_sha256'} and bundle_ref['path']=='audit_bundle','unsafe/missing audit reference')
    checked=read_bundle(run/'audit_bundle',expected_manifest_sha256=bundle_ref['manifest_sha256'])
    bundle=bound('audit_bundle/audit_bundle.json',bundle_ref['manifest_sha256'])
    for name,metadata in bundle['members'].items():require(verified.get('run/audit_bundle/'+name)==metadata['sha256'],'bundle member differs from initial anchor')
    receipt=bundle['source_receipt'];trace_sha=receipt['sha256'];require(verified.get('run/trace.jsonl')==trace_sha,'trace differs from initial anchor')
    require(_sha(run/'trace.jsonl')==trace_sha and (run/'trace.jsonl').stat().st_size==receipt['byte_count']<=TRACE_BYTES,'trace source receipt/cap differs')
    summary=bundle['summary'];envelope=bundle['envelope']
    require(checked.get('storage_verified') is True and checked.get('semantic_replay_performed') is False
        and checked['summary']==summary and checked['source_receipt']==receipt
        and bundle['dependency_sha256']=={k:inputs[k] for k in AUDIT_DEPENDENCIES}
        and bundle['bundle_source_sha256']==inputs['src/smt_fullfab/stream_audit_bundle.py']
        and envelope.get('terminal_at_eof') is True and envelope.get('first_time')==0 and envelope.get('last_time')==envelope.get('horizon')==3600
        and envelope.get('receipt')==receipt and bundle.get('configuration')=={'window_start':0,'priority_weights':None,'require_terminal':True,'verify_data_dir_supplied':True},'audit bundle terminal/dependencies differ')
    source_report=bound('audit_bundle/source.json',bundle['members']['source.json']['sha256'])
    require(all(summary.get(k)is True for k in ('valid','source_valid','opportunity_valid','physical_valid','actual_dispatch_provenance_complete',
        'complete_physical_window_certified','absence_of_unreported_legal_demand_certified','verified_input_hashes'))
        and source_report.get('valid')is True and source_report.get('errors')==[]
        and source_report.get('production_machine_count')==source_report.get('declared_control_machine_count')==913
        and type(source_report.get('production_machine_count'))is int and type(source_report.get('declared_control_machine_count'))is int
        and source_report.get('declared_full_factory_domain')is True
        and source_report.get('_source_evidence',{}).get('source_receipt')==receipt
        and source_report.get('_source_evidence',{}).get('complete_jsonl_pass')is True
        and result['metrics']==summary['metrics'],'complete 913-machine physical/opportunity/source audit absent')
    audit=bound('delta_attribution_audit.json');index_sha=result['index_sha256'];require(verified.get('run/delta_index.jsonl')==index_sha,'index differs from initial anchor')
    replayed=d.audit_delta_run(run,expected_index_sha256=index_sha,expected_source_sha256=manifest['source_sha256'],expected_trace_sha256=trace_sha)
    require(audit.get('valid')is True and same(replayed,audit) and audit.get('source_receipt')==receipt
        and audit.get('index_sha256')==index_sha and audit.get('source_sha256')==manifest['source_sha256'],'independent delta attribution replay differs')
    rows=d.read_index(run/'delta_index.jsonl',expected_sha256=index_sha)
    resources=d.read_account_evidence(run,rows[-1]['payload']['account_report_sha256'])
    account=resources['account'];registration=bound('resource_registration.json')
    for name,digest in (('ledger_final_account.json',rows[-1]['payload']['account_report_sha256']),('ledger_final.jsonl',resources['ledger_sha256'])):
        require(verified.get('run/'+name)==digest and _sha(run/name)==digest,'final real ledger account changed')
    require(registration['run_id']==str(run) and registration['arm']=='B' and registration['scenario']==1701
        and registration['window_seconds']==3600 and registration['solver_seconds']==0 and registration['wall_seconds']==CHILD_SECONDS
        and registration['max_log_bytes']==MAX_BYTES,'original registration scope differs')
    count=account['attempts'];require(type(count)is int and count>0 and all(result.get(k)==count for k in ('model_calls','local_bridge_attempts','returned_bridge_attempts','next_local_model_index'))
        and result.get('model_account')==account and result.get('pending_call_ids')==account['pending']==[]
        and result.get('unknown_usage_call_ids')==account['unknown_completed']==audit['unknown_usage_call_ids']
        and result.get('reserve_call_ids')==resources['reserve_call_ids']==audit['reserve_call_ids']
        and audit['model_calls']==count and result['plans']==len(audit['plans'])>0,'original model/cost counts differ')
    require(not resources['solver_call_ids'] and not resources['constructor_call_ids'],'B used forbidden optimization/construction')
    require({p.name for p in run.glob('model_*')}=={f'model_{i:05d}' for i in range(count)}
        and {p.name for p in run.glob('call_*')}=={f'call_{i:05d}' for i in range(count)}
        and {p.name for p in run.glob('plan_*')}=={f'plan_{i:05d}' for i in range(result['plans'])},'orphan/missing call or plan directories')
    for row in rows:
        if row['event']=='call_finished':
            item=row['payload'];intent=bound(f"call_{item['model_index']:05d}/intent.json",item['intent_sha256'])
            require(intent['config']['codex_binary']==manifest['runtime']['model_cli']['path'],'call used a different model CLI runtime')
        if row['event']=='plan_closed':
            p=row['payload'];require(verified.get(f"run/plan_{p['plan_index']:05d}/durable/ledger.sqlite3")==p['durable_prefix']['database_sha256'],'store differs from original final prefix')
    checkpoint=_checkpoint(run,result['checkpoint'],inputs);require(verified.get('run/checkpoint.json')==checkpoint['file_sha256'],'checkpoint differs from initial anchor')
    _bind(verified,{'run/'+p.relative_to(run).as_posix():_sha(p) for p in _files(run)})
    _ledger_unchanged_for_run(_raw(run/'ledger_final.jsonl'),_raw(root/LEDGER),run,registration['registration_id'])
    return {'valid':True,'result':result,'verified_evidence_sha256':verified,'registration_id':registration['registration_id'],
        'checkpoint':checkpoint,'backend_identity_independently_proven':False,'physical_reexecution_performed':False}


def _readback(run,manifest,*,timeout=VERIFY_SECONDS):
    campaign=Path(manifest['origin_root'])/AREA/RUN_ID;frozen=campaign/'frozen'
    code="import sys,json;sys.path.insert(0,sys.argv[1]);from src.smt_fullfab.B_delta_gate import _verification_payload;print(json.dumps(_verification_payload(sys.argv[2],json.load(open(sys.argv[3]))),separators=(',',':')))"
    process=subprocess.run([manifest['launcher_executable'],'-I','-B','-c',code,str(frozen),str(run),str(campaign/'manifest.json')],
        cwd=frozen,capture_output=True,text=True,timeout=timeout)
    require(process.returncode==0,'frozen readback failed: '+process.stderr[-4000:])
    return _strict(process.stdout)


def _verify_process(campaign,manifest,proof,*,anchors):
    def bound(name):return _read_bound_json(campaign/name,anchors['campaign/'+name])
    child=bound('process_outcome.json');started=bound('child_started.json');attempt=bound('attempt.json');usage=bound('child_usage.json')
    require(type(child.get('pid'))is int and child['pid']>0 and type(started.get('pid'))is int and started['pid']==child['pid']
        and type(child.get('returncode'))is int and child['returncode']==0 and child.get('timed_out')is False
        and type(child.get('wall_seconds'))in(int,float) and math.isfinite(child['wall_seconds'])
        and 0<=proof['result']['end_to_end_wall_seconds']<=child['wall_seconds']<=CHILD_SECONDS
        and attempt.get('manifest_identity')==manifest['identity'] and attempt.get('command')==manifest['child_command'],'actual invocation/complete child wall invalid')
    # Same RUSAGE_SELF normalization as the A8 helper, using these already bound
    # bytes rather than opening the path again after verification.
    platform=usage.get('platform');raw=usage.get('raw_maxrss')
    unit='bytes' if platform=='darwin' else 'KiB' if isinstance(platform,str) and platform.startswith('linux') else None
    require(usage.get('schema')=='smt-child-peak-rss-v1' and type(usage.get('pid'))is int and usage['pid']==child['pid']
        and usage.get('source')=='resource.getrusage(RUSAGE_SELF).ru_maxrss' and unit is not None and usage.get('raw_unit')==unit
        and type(raw)is int and raw>0 and usage.get('hard_memory_guard')is False,'missing/invalid child peak RSS evidence')
    measured=raw*(1024 if unit=='KiB' else 1)
    require(type(usage.get('peak_rss_bytes'))is int and usage['peak_rss_bytes']==measured<=PEAK_RSS_BYTES,'child measured peak RSS exceeds8GiB or normalization differs')
    return usage


def _final_ledger(run,manifest,proof):
    sealed=_raw(run/'ledger_final.jsonl')
    require(hashlib.sha256(sealed).hexdigest()==proof['verified_evidence_sha256']['run/ledger_final.jsonl'],'verified ledger snapshot changed')
    _ledger_unchanged_for_run(sealed,_raw(Path(manifest['actual_ledger_path'])),run,proof['registration_id'])


def _replay(campaign,manifest):
    run=Path(manifest['output_directory']);acceptance=_read(campaign/'acceptance.json')
    require(acceptance.get('schema')==SCHEMA+'-acceptance' and acceptance.get('identity')==_digest({k:v for k,v in acceptance.items() if k!='identity'})
        and acceptance.get('manifest_identity')==manifest['identity'] and acceptance.get('protocol_sha256')==manifest['protocol_sha256'],'acceptance identity changed')
    require(_evidence(campaign,run)==acceptance['evidence_sha256'] and _bytes(campaign,run)==acceptance['final_total_bytes_including_acceptance'],'saved evidence changed')
    if acceptance.get('accepted')is True:
        proof=_readback(run,manifest);usage=_verify_process(campaign,manifest,proof,anchors=acceptance['verified_campaign_sha256'])
        final=_evidence(campaign,run);_bind(proof['verified_evidence_sha256'],final)
        _bind_campaign(acceptance['verified_campaign_sha256'],final)
        require(final==acceptance['evidence_sha256'] and proof['verified_evidence_sha256']==acceptance['verified_evidence_sha256']
            and usage['peak_rss_bytes']==acceptance['child_peak_rss_bytes'] and 0<=acceptance['outer_wall_seconds']<=OUTER_SECONDS
            and acceptance['final_total_bytes_including_acceptance']<=MAX_BYTES,'readback replaced verified anchors or exceeded resources')
        _final_ledger(run,manifest,proof)
    return acceptance


def read_acceptance(*,root=ROOT):
    try:
        root=Path(root).resolve();campaign=root/AREA/RUN_ID;manifest=_read(campaign/'manifest.json')
        require(_sha(root/PROTOCOL)==manifest['protocol_sha256'],'registered protocol changed')
        verify_frozen(campaign,manifest,for_execution=False);acceptance=_replay(campaign,manifest)
        return {'valid':True,'accepted':acceptance.get('accepted')is True,'status':acceptance['status'],'acceptance':acceptance,'errors':[]}
    except Exception as exc:return {'valid':False,'accepted':False,'status':'unverified','errors':[str(exc)]}


def execute(campaign,manifest):
    started=time.monotonic();campaign=Path(campaign).resolve();root=Path(manifest['origin_root']);run=Path(manifest['output_directory'])
    elapsed=lambda:manifest['prepare_wall_seconds']+time.monotonic()-started
    with _serial_lock(root):
        if (campaign/'acceptance.json').exists():
            verify_frozen(campaign,manifest,for_execution=False);return _replay(campaign,manifest)
        original_campaign=_campaign_anchors(campaign)
        verify_frozen(campaign,manifest)
        require(not run.exists() and not (campaign/'attempt.json').exists(),'existing/interrupted attempt preserved; no retry/finalization')
        active=_active_with_finalizers(root)
        if active:return {'accepted':False,'status':'blocked_active_runs','active_claims':active}
        free=shutil.disk_usage(root).free
        if free<MIN_FREE_BYTES:return {'accepted':False,'status':'blocked_disk_capacity','available_bytes':free}
        _ledger_preflight(_raw(root/LEDGER),root)
        _write(campaign/'attempt.json',{'manifest_identity':manifest['identity'],'supervisor_pid':os.getpid(),
            'command':manifest['child_command'],'available_disk_bytes':free,'outer_wall_limit':OUTER_SECONDS})
        original_campaign['campaign/attempt.json']=_sha(campaign/'attempt.json')
        anchors=original_campaign;proof=None;usage=None;errors=[]
        try:
            child=_launch(manifest['child_command'],campaign/'frozen',campaign,max(.001,OUTER_SECONDS-elapsed()))
            _write(campaign/'process_outcome.json',child)
            terminal_campaign=_campaign_anchors(campaign)
            _bind_campaign(original_campaign,terminal_campaign,exact=False);anchors=terminal_campaign
            require(child.get('returncode')==0 and child.get('timed_out')is False,'controller failed/timeout; preserve raw partials')
            verify_frozen(campaign,manifest)
            remaining=OUTER_SECONDS-elapsed();require(remaining>0,'outer budget exhausted before readback')
            proof=_readback(run,manifest,timeout=min(VERIFY_SECONDS,remaining));require(proof.get('valid')is True,'readback invalid')
            usage=_verify_process(campaign,manifest,proof,anchors=anchors);_final_ledger(run,manifest,proof)
        except Exception as exc:errors.append(type(exc).__name__+': '+str(exc))
        try:verify_frozen(campaign,manifest)
        except Exception as exc:errors.append('post-run freeze: '+str(exc))
        _write(campaign/'verification.json',{'valid':not errors,'errors':list(errors),'proof':proof})
        evidence=_evidence(campaign,run)
        try:_bind_campaign(anchors,evidence)
        except Exception as exc:errors.append(str(exc))
        if proof is not None:
            try:_bind(proof['verified_evidence_sha256'],evidence);_final_ledger(run,manifest,proof)
            except Exception as exc:errors.append(str(exc))
        existing=_bytes(campaign,run);wall=elapsed()
        if wall>OUTER_SECONDS:errors.append('final outer wall exceeds22200 seconds')
        acceptance={'schema':SCHEMA+'-acceptance','run_id':RUN_ID,'manifest_identity':manifest['identity'],
            'protocol_sha256':manifest['protocol_sha256'],'evidence_sha256':evidence,
            'verified_evidence_sha256':proof['verified_evidence_sha256'] if proof else None,
            'verified_campaign_sha256':anchors,
            'runner_result_sha256':evidence.get('run/result.json'),'outer_wall_seconds':wall,'prepare_wall_seconds':manifest['prepare_wall_seconds'],
            'child_peak_rss_bytes':usage['peak_rss_bytes'] if usage else None,'rss_is_hard_guard':False,
            'final_total_bytes_including_acceptance':0,'errors':errors,'formal':False,'backend_identity_independently_proven':False,
            'outer_wall_scope':'prepare plus execution, freeze checks, readbacks and evidence collection; excludes final acceptance publication and supervisor exit'}
        for _ in range(16):
            acceptance.update(accepted=not errors,status='failed' if errors else 'success')
            acceptance['identity']=_digest({k:v for k,v in acceptance.items() if k!='identity'})
            total=existing+len((json.dumps(acceptance,ensure_ascii=False,separators=(',',':'))+'\n').encode())
            if total>MAX_BYTES and 'final evidence exceeds16GiB' not in errors:errors.append('final evidence exceeds16GiB')
            if total==acceptance['final_total_bytes_including_acceptance'] and acceptance['accepted']==(not errors):break
            acceptance['final_total_bytes_including_acceptance']=total
        acceptance['identity']=_digest({k:v for k,v in acceptance.items() if k!='identity'})
        _write(campaign/'acceptance.json',acceptance);return acceptance


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true');parser.add_argument('--read-acceptance',action='store_true')
    args=parser.parse_args();require(not(args.execute and args.read_acceptance),'choose execution or readback')
    if args.read_acceptance:result=read_acceptance()
    else:
        campaign,manifest=prepare();result=execute(campaign,manifest) if args.execute else {'status':'prepared','run_id':RUN_ID,'campaign':str(campaign),'manifest_identity':manifest['identity']}
    print(json.dumps(result,ensure_ascii=False,separators=(',',':')))
    return 0 if result.get('status')=='prepared' or result.get('accepted')is True else 1


if __name__=='__main__':raise SystemExit(main())
