"""Private, byte-bound unfinished shared start and explicit independent branches.

Packaging is storage/structure validation, not a physical audit or warm-up claim.
Existing snapshot-1, physics, state and observation code are never rewritten.
Only trusted drivers may receive packages/branches; model-facing data must come
from Branch.problem(). This Python facade is not an adversarial access sandbox.
No existing runner/controller consumes this new interface automatically.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import tempfile
import time

SCHEMA = 'smt-fullfab-shared-start-v1'
SNAPSHOT_SCHEMA = 'smt-fullfab-snapshot-1'
SNAPSHOT_VERSION = 'smt-fullfab-env-0.3'
RANDOM_MECHANISM = 'event-keyed SHA256; no mutable global RNG'
STATE_FIELDS = ('seed','horizon','t','seq','dispatch_id','decisions','releases','completed',
    'finished','wait_until','lots','machine_state','jobs','calendars','pm_counters',
    'queue_area','last_area_t','manifest','plan','observation_start','q','waiting',
    'processing_by_machine','stats','executed_tasks','plan_versions','trace')
WRAPPER_FILES = ('src/smt_fullfab/shared_start.py','src/smt_fullfab/stream_snapshot.py',
                 'src/smt_fullfab/trace_source.py')
EVIDENCE_ROLES = ('generation_contract','boundary','shared_cost','prehistory_audit')


class SharedStartError(ValueError):
    pass


def require(ok, message):
    if not ok: raise SharedStartError(message)


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')


def digest(value): return hashlib.sha256(canonical(value)).hexdigest()


def strict(raw):
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,'duplicate JSON key')
            result[key]=value
        return result
    value=json.loads(raw,object_pairs_hook=pairs)
    canonical(value)  # Also rejects exponent overflow, NaN and infinity.
    return value


def number(value):
    try:return type(value) in (int,float) and math.isfinite(value)
    except OverflowError:return False


def sha_string(value):
    return type(value)is str and len(value)==64 and all(x in '0123456789abcdef' for x in value)


def name_string(value):
    return type(value)is str and bool(value) and all(x.isascii() and (x.isalnum() or x in '_-') for x in value)


def relative(value):
    require(type(value)is str and value and not Path(value).is_absolute()
            and '..' not in Path(value).parts and Path(value).as_posix()==value,'unsafe relative member name')
    return value


def identity(value):return (value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)


def read_bytes(path, expected=None, *, retain=True):
    """One FD and original path fence; retained snapshot bytes remain a RAM limit."""
    path=Path(path);fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(fd,'rb') as stream:
        before=os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and identity(before)==identity(path.lstat()),'nonregular/replaced source')
        chunks=[];hasher=hashlib.sha256();count=0
        while True:
            raw=stream.read(1024*1024)
            if not raw:break
            count+=len(raw);hasher.update(raw)
            if retain:chunks.append(raw)
        require(count==before.st_size and identity(before)==identity(os.fstat(stream.fileno()))==identity(path.lstat()),'source changed during complete read')
    sha=hasher.hexdigest();require(expected is None or sha==expected,'original source SHA differs: '+str(path))
    return b''.join(chunks) if retain else None, {'sha256':sha,'bytes':count}


def read_json(path, expected=None):
    raw,receipt=read_bytes(path,expected)
    return strict(raw),receipt


def _checked_write(stream, raw):
    require(type(raw)is bytes,'writer requires bytes')
    count=stream.write(raw)
    if type(count)is not int or count!=len(raw):raise OSError('incomplete evidence write')


def _fsync_dir(path):
    fd=os.open(path,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def publish(path, value):
    """Create-new atomic complete JSON; partial temp evidence is retained on error."""
    path=Path(path);raw=canonical(value)+b'\n'
    fd,temp=tempfile.mkstemp(prefix='.'+path.name+'.',suffix='.partial',dir=path.parent)
    temp=Path(temp)
    with os.fdopen(fd,'wb') as stream:
        _checked_write(stream,raw);stream.flush();os.fsync(stream.fileno())
    os.link(temp,path)  # Existing target fails; never replace or merge a claim.
    _fsync_dir(path.parent)
    temp.unlink();_fsync_dir(path.parent)
    sha=hashlib.sha256(raw).hexdigest();read_bytes(path,sha,retain=False)
    return sha


def copy_exact(source, target, expected):
    source=Path(source);target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(source,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0));hasher=hashlib.sha256();count=0
    with os.fdopen(fd,'rb') as src, target.open('xb') as dst:
        before=os.fstat(src.fileno())
        require(stat.S_ISREG(before.st_mode) and identity(before)==identity(source.lstat()),'nonregular/replaced copy source')
        while True:
            raw=src.read(1024*1024)
            if not raw:break
            _checked_write(dst,raw);hasher.update(raw);count+=len(raw)
        require(count==before.st_size and identity(before)==identity(os.fstat(src.fileno()))==identity(source.lstat())
                and hasher.hexdigest()==expected,'copy source changed or differs')
        dst.flush();os.fsync(dst.fileno())
    target.chmod(0o444)
    read_bytes(target,expected,retain=False)
    return {'sha256':expected,'bytes':count}


def _files(directory):
    result={}
    for path in sorted(Path(directory).rglob('*')):
        require(not path.is_symlink(),'linked package/branch evidence')
        if path.is_file():result[path.relative_to(directory).as_posix()]=read_bytes(path,retain=False)[1]
    return result


def _failure(directory, exc):
    try:publish(Path(directory)/'failure.json',{'type':type(exc).__name__,'message':str(exc),'retry_permitted':False})
    except BaseException as cleanup:
        if hasattr(exc,'add_note'):exc.add_note('failure evidence publication also failed: '+repr(cleanup))


def validate_contract(contract):
    require(type(contract)is dict and set(contract)=={'schema','shared_start_id','seed','evaluation','policy','steady_state_claim'},'shared contract fields differ')
    require(contract['schema']==SCHEMA+'-generation-contract' and name_string(contract['shared_start_id'])
            and type(contract['seed'])is int and type(contract['policy'])is str and bool(contract['policy'])
            and contract['steady_state_claim']is False,'invalid shared generation contract or unsupported steady-state claim')
    w=contract['evaluation']
    require(type(w)is dict and set(w)=={'absolute_start','absolute_end','physical_episode_end','period_anchor','period_seconds','plan_seconds','lookahead_depth'},'explicit evaluation window required')
    require(all(number(w[k]) for k in ('absolute_start','absolute_end','physical_episode_end','period_anchor','period_seconds','plan_seconds'))
            and 0<w['absolute_start']<w['absolute_end']==w['physical_episode_end']
            and w['period_anchor']==w['absolute_start'] and w['period_seconds']>0 and w['plan_seconds']>0
            and type(w['lookahead_depth'])is int and w['lookahead_depth']>0,'require 0<T0<H=T1 and explicit positive planning parameters')
    return w


def inspect_state(snapshot, contract):
    """Structural checks only. Full original private fields are hashed and kept."""
    w=validate_contract(contract);t=w['absolute_start'];h=w['physical_episode_end']
    require(type(snapshot)is dict and set(snapshot)=={'schema','version','implementation_sha256','physics_sha256','data_hashes','state','state_sha256','random_mechanism','initialization'},'complete snapshot-1 document required')
    state=snapshot['state']
    require(snapshot['schema']==SNAPSHOT_SCHEMA and snapshot['version']==SNAPSHOT_VERSION
            and type(state)is dict and set(state)==set(STATE_FIELDS) and digest(state)==snapshot['state_sha256']
            and snapshot['random_mechanism']==RANDOM_MECHANISM,'snapshot schema/version/state/RNG identity differs')
    require(type(state['seed'])is int and state['seed']==contract['seed'] and state['finished']is False
            and number(state['t']) and state['t']==t and number(state['horizon']) and state['horizon']==h
            and number(state['observation_start']) and 0<=state['observation_start']<=t,'not the declared unfinished common boundary; never extend or reset terminal state')
    manifest=state['manifest'];machines=manifest['machines']
    mids=[m['id'] for m in machines]
    require(all(type(x)is int and x>=0 for x in mids) and len(mids)==len(set(mids)),'invalid source machine identities')
    physical=sorted(m['id'] for m in machines if m['group']!='Delay_32')
    require(len(physical)==913 and manifest['physical_machines']==913 and manifest['controlled_machine_ids']==physical
            and manifest['seed']==state['seed'] and manifest['horizon']==h
            and manifest['fullfab_version']==SNAPSHOT_VERSION
            and manifest['outside_policy']=='virtual-delay-only; no background production'
            and snapshot['data_hashes']==manifest['data_hashes'],'incomplete full913 source/domain/data identity')
    deps=snapshot['implementation_sha256']
    required={'src/smt_fullfab/environment.py','src/smt_fullfab/observation.py','src/smt/environment.py'}
    require(type(deps)is dict and required<=set(deps) and any(k.startswith('vendor/') for k in deps)
            and all(sha_string(v) and relative(k) for k,v in deps.items())
            and deps['src/smt/environment.py']==snapshot['physics_sha256'],'complete original implementation/physics hashes required')
    require(type(snapshot['data_hashes'])is dict and snapshot['data_hashes']
            and all(type(k)is str and Path(k).name==k and relative(k) and sha_string(v) for k,v in snapshot['data_hashes'].items()),'invalid source data identity')
    require(type(state['q'])is list and type(state['seq'])is int and state['seq']>=0,'invalid original event queue')
    queue_sequences=[]
    for i,event in enumerate(state['q']):
        require(type(event)is list and len(event)==4 and number(event[0]) and event[0]>t
                and type(event[1])is int and 0<event[1]<=state['seq'] and type(event[2])is str,'boundary has undrained/invalid queued event; do not discard it')
        queue_sequences.append(event[1])
        if i:require(tuple(state['q'][(i-1)//2][:2])<=tuple(event[:2]),'original q is not an intact heap')
    require(len(queue_sequences)==len(set(queue_sequences)),'duplicate original queue identity')
    executed=state['executed_tasks']
    require(type(executed)is list and all(type(x)is list and len(x)==2 and all(type(y)is str for y in x) for x in executed)
            and len({tuple(x) for x in executed})==len(executed),'invalid executed task identities')
    plan=state['plan'];require(type(plan)is dict,'first version requires original completed warm-up plan to remain present')
    require(type(plan.get('version'))is str and plan['version'] in state['plan_versions'] and plan['scope']==physical,'original plan/scope/version missing')
    frozen=[task for task in plan['tasks'] if [plan['version'],task['id']] not in executed
            and t<plan['freeze_until'] and task['not_before']<plan['freeze_until']]
    require(not frozen,'unsupported nonempty cross-boundary frozen commitments; adoption not implemented')
    require(number(plan['valid_until']) and number(plan['freeze_until'])
            and plan['freeze_until']<=plan['valid_until']<=t,'original plan must naturally expire at/before T0; no automatic hold, clearing or waiting')
    jobs=state['jobs'];processing=state['processing_by_machine'];active=[]
    require(type(jobs)is dict and type(processing)is dict,'missing original jobs/processing index')
    for mid,ids in processing.items():
        require(str(int(mid))==mid and int(mid) in mids and type(ids)is list and len(ids)==len(set(ids)),'invalid original processing index')
        for jid in ids:
            require(type(jid)is int and str(jid) in jobs,'missing indexed inherited job')
            job=jobs[str(jid)]
            require(job['machine']==int(mid) and job['done']is False and number(job['process_end']) and job['process_end']>t,'processing index contradicts inherited job')
            require(all(lid in state['lots'] and state['lots'][lid]['status']=='processing' for lid in job['lots']),'inherited processing lot missing')
            if int(mid) in physical:active.append(jid)
    require(active,'shared start must contain real indexed unfinished production processing, not an idle/transport-only fabricated label')
    require(type(state['dispatch_id'])is int and set(jobs)=={str(i) for i in range(state['dispatch_id'])},'job history truncated or identity reset')
    require(type(state['trace'])is list and state['trace'],'complete nonempty prehistory required')
    return {'production_scope':physical,'processing_production_job_ids':active,
        'unfinished_production_jobs':sum(j['machine'] in physical and j['done']is False for j in jobs.values()),
        'unfinished_virtual_jobs':sum(j['machine'] not in physical and j['done']is False for j in jobs.values()),
        'original_job_count':len(jobs),'pending_event_count':len(state['q']),
        'original_observation_start':state['observation_start'],'original_plan_sha256':digest(plan),
        'executed_tasks_sha256':digest(executed),'frozen_commitments_supported':False,
        'frozen_unstarted_count':0,'first_new_plan_required':True}


def _check_trace(path, snapshot, expected_sha):
    from .trace_source import inspect_jsonl,open_verified
    seal=inspect_jsonl(path,expected_sha256=expected_sha)
    state=snapshot['state'];trace=state['trace'];previous=-math.inf;last_plan=None;commits=0
    with open_verified(seal) as reader:
        for record in reader:
            event=strict(record.raw_line);i=record.event_index
            require(i<len(trace) and canonical(event)==canonical(trace[i]),'original raw prehistory and private snapshot differ')
            require(type(event.get('seq'))is int and event['seq']==i and number(event.get('time'))
                    and previous<=event['time']<=state['t'] and event.get('kind')!='terminal','invalid sequence/time or terminal prehistory')
            if event.get('kind')=='time_advance':require(number(event.get('to')) and event['time']<=event['to']<=state['t'],'advance crosses shared boundary')
            if i==0:require(event.get('kind')=='initial' and event['time']==0 and canonical(event['manifest'])==canonical(state['manifest']),'original initial manifest differs')
            if event.get('kind')=='plan_committed':last_plan=event['plan'];commits+=1
            previous=event['time']
    require(reader.receipt.event_count==len(trace) and canonical(last_plan)==canonical(state['plan'])
            and type(state['decisions'])is int and commits==state['decisions'],'snapshot plan/decision history differs')
    return asdict(reader.receipt)


def _bound_evidence(evidence):
    require(type(evidence)is dict and set(evidence)==set(EVIDENCE_ROLES),'all shared evidence roles required')
    result={}
    for role,ref in evidence.items():
        require(type(ref)is dict and set(ref)=={'path','sha256'} and sha_string(ref['sha256']),'externally hash-bound evidence required')
        result[role]=read_json(ref['path'],ref['sha256'])[0]
    return result


def _check_evidence(objects, contract, snapshot, snapshot_sha, trace_sha):
    require(canonical(objects['generation_contract'])==canonical(contract),'generation contract is not original external evidence')
    boundary=objects['boundary'];t=contract['evaluation']['absolute_start']
    require(boundary.get('schema')==SCHEMA+'-boundary' and boundary.get('snapshot_sha256')==snapshot_sha
            and boundary.get('state_sha256')==snapshot['state_sha256'] and boundary.get('trace_sha256')==trace_sha
            and boundary.get('time')==boundary.get('drained_events_through')==t
            and boundary.get('active_task','missing') is None and boundary.get('inflight_actions')==[]
            and boundary.get('phase')=='paused_between_executor_calls' and type(boundary.get('last_stop'))is dict,
            'missing original exclusive non-atomic boundary attestation')
    cost=objects['shared_cost']
    require(cost.get('shared_start_id')==contract['shared_start_id']
            and cost.get('cost_scope')=='shared_scenario_construction_once' and type(cost.get('resources'))is dict,
            'shared scenario cost evidence missing; never adopt arm checkpoint resources')
    audit=objects['prehistory_audit']
    require(audit.get('snapshot_sha256')==snapshot_sha and audit.get('trace_sha256')==trace_sha
            and audit.get('valid')is True and audit.get('errors')==[],'prior legal-generation audit evidence missing/invalid')
    # These caller-pinned receipts are retained and structurally checked, not
    # independently replayed by this storage/restoration module.


def create_shared_start(*, snapshot_path, trace_path, output_dir, contract,
                        expected_snapshot_sha256, expected_trace_sha256,
                        evidence, source_root, data_dir):
    """Wrap an already legal unfinished boundary; never generate a snapshot."""
    require(sha_string(expected_snapshot_sha256) and sha_string(expected_trace_sha256),'external original input hashes required')
    started=time.perf_counter();output=Path(output_dir).resolve();source_root=Path(source_root).resolve();data_dir=Path(data_dir).resolve()
    snapshot,receipt=read_json(snapshot_path,expected_snapshot_sha256)
    summary=inspect_state(snapshot,contract);trace_receipt=_check_trace(trace_path,snapshot,expected_trace_sha256)
    objects=_bound_evidence(evidence);_check_evidence(objects,contract,snapshot,expected_snapshot_sha256,expected_trace_sha256)
    output.mkdir(parents=True,exist_ok=False)
    try:
        members={}
        def copy(name,path,sha):members[name]=copy_exact(path,output/name,sha)
        copy('snapshot.json',snapshot_path,expected_snapshot_sha256)
        copy('prehistory.jsonl',trace_path,expected_trace_sha256)
        for role,ref in evidence.items():copy('evidence/'+role+'.json',ref['path'],ref['sha256'])
        for name,sha in snapshot['implementation_sha256'].items():copy('source/'+relative(name),source_root/name,sha)
        for name,sha in snapshot['data_hashes'].items():copy('data/'+name,data_dir/name,sha)
        wrappers={}
        for name in WRAPPER_FILES:
            actual=Path(__file__).resolve().parents[2]/name
            sha=read_bytes(actual,retain=False)[1]['sha256']
            read_bytes(source_root/name,sha,retain=False)
            wrappers[name]=sha;copy('source/'+name,source_root/name,sha)
        manifest={'schema':SCHEMA+'-package','shared_start_id':contract['shared_start_id'],
            'contract':deepcopy(contract),'members':members,'wrapper_sha256':wrappers,
            'snapshot_schema':snapshot['schema'],'snapshot_version':snapshot['version'],
            'snapshot_sha256':expected_snapshot_sha256,'state_sha256':snapshot['state_sha256'],
            'prehistory_receipt':trace_receipt,'implementation_sha256':snapshot['implementation_sha256'],
            'data_hashes':snapshot['data_hashes'],'random_mechanism':snapshot['random_mechanism'],
            'boundary_summary':summary,'evaluation_window':deepcopy(contract['evaluation']),
            'shared_cost_reference':{'path':'evidence/shared_cost.json','sha256':evidence['shared_cost']['sha256'],
                'scope':'one shared scene cost; branches reference it, do not reset or multiply it'},
            'package_wall_seconds_before_publication':time.perf_counter()-started,
            'model_calls':0,'solver_calls':0,'factory_generations':0,'steady_state_certified':False,
            'prior_physical_audit_independently_replayed':False,'adapter_integration_pending':True,
            'private_to_trusted_driver':True,'scope':'original storage and structural handoff only; not experimental acceptance',
            'limitations':['existing full snapshot/history remains in RAM','cross-boundary frozen adoption not implemented',
                'external evaluation window is not installed into old cold consumers','source reference audit/atomic boundary are pinned external attestations']}
        require(_files(output)==members,'package has missing/orphan/replaced original members')
        manifest_bytes=len(canonical(manifest)+b'\n')
        sha=publish(output/'manifest.json',manifest)
        expected_files={**members,'manifest.json':{'sha256':sha,'bytes':manifest_bytes}}
        require(_files(output)==expected_files,'package changed during publication')
        return {'path':str(output),'manifest_sha256':sha,'shared_start_id':contract['shared_start_id'],
                'adapter_integration_pending':True,'actual_branch_runs':0}
    except BaseException as exc:
        _failure(output,exc);raise


def read_shared_start(directory, *, expected_manifest_sha256):
    """Private complete readback, pinned to the caller's original package hash."""
    require(sha_string(expected_manifest_sha256),'original package hash required')
    directory=Path(directory).resolve();require(not (directory/'failure.json').exists(),'package creation failed; no automatic continuation')
    manifest,manifest_receipt=read_json(directory/'manifest.json',expected_manifest_sha256)
    require(manifest.get('schema')==SCHEMA+'-package' and manifest.get('adapter_integration_pending')is True
            and manifest.get('private_to_trusted_driver')is True,'shared package schema/scope differs')
    expected_files={**manifest['members'],'manifest.json':manifest_receipt}
    require(manifest_receipt['sha256']==expected_manifest_sha256 and _files(directory)==expected_files,'package original membership/hash differs')
    snapshot,_=read_json(directory/'snapshot.json',manifest['snapshot_sha256'])
    summary=inspect_state(snapshot,manifest['contract'])
    require(canonical(summary)==canonical(manifest['boundary_summary']) and snapshot['state_sha256']==manifest['state_sha256']
            and snapshot['implementation_sha256']==manifest['implementation_sha256'] and snapshot['data_hashes']==manifest['data_hashes']
            and manifest['evaluation_window']==manifest['contract']['evaluation'],'package summary is not bound to its original state')
    require(type(manifest.get('wrapper_sha256'))is dict and set(manifest['wrapper_sha256'])==set(WRAPPER_FILES), 'complete wrapper dependency mapping required')
    expected_members={'snapshot.json':manifest['snapshot_sha256'],'prehistory.jsonl':manifest['prehistory_receipt']['sha256']}
    expected_members.update({'source/'+relative(name):sha for name,sha in manifest['implementation_sha256'].items()})
    expected_members.update({'source/'+relative(name):sha for name,sha in manifest['wrapper_sha256'].items()})
    expected_members.update({'data/'+name:sha for name,sha in manifest['data_hashes'].items()})
    expected_members.update({'evidence/'+role+'.json':manifest['members']['evidence/'+role+'.json']['sha256'] for role in EVIDENCE_ROLES})
    require(set(manifest['members'])==set(expected_members)
            and all(manifest['members'][name]['sha256']==sha for name,sha in expected_members.items())
            and manifest['members']['prehistory.jsonl']['bytes']==manifest['prehistory_receipt']['byte_count'], 'original state/dependency/data hashes differ from retained members')
    require(_check_trace(directory/'prehistory.jsonl',snapshot,manifest['prehistory_receipt']['sha256'])==manifest['prehistory_receipt'],'original complete trace receipt differs')
    refs={role:{'path':directory/'evidence'/ (role+'.json'),'sha256':manifest['members']['evidence/'+role+'.json']['sha256']} for role in EVIDENCE_ROLES}
    _check_evidence(_bound_evidence(refs),manifest['contract'],snapshot,manifest['snapshot_sha256'],manifest['prehistory_receipt']['sha256'])
    require(_files(directory)==expected_files,'package changed during complete readback')
    return manifest


def _runtime():
    # No environment import or construction happens during package creation.
    from . import environment,stream_snapshot,observation
    return environment,stream_snapshot,observation


def _state_hash(view, writer):
    hasher=hashlib.sha256()
    for raw in writer._chunks(view):hasher.update(raw)
    return hasher.hexdigest()


class Branch:
    """Trusted-driver facade; it exposes no private snapshot in model feedback.

    Not a security sandbox. Do not grant a model Python/object/filesystem access.
    The caller supplies every plan and owns arm attribution/ledger registration.
    Unknown commit/advance outcomes poison this instance and are never retried.
    """
    def __init__(self, env, writer, observation, directory, receipt):
        self._env=env;self._writer=writer;self._observation=observation
        self._directory=directory;self._receipt=deepcopy(receipt);self._committed=False;self._poisoned=False
        self._origin_state_sha256=receipt['restored_state_with_marker_sha256']

    @property
    def receipt(self):return deepcopy(self._receipt)

    def problem(self):
        require(not self._poisoned,'branch has an unknown result; read-only diagnosis required')
        w=self._receipt['evaluation_window']
        result=self._observation.build_problem(self._env,plan_seconds=w['plan_seconds'],lookahead_depth=w['lookahead_depth'])
        return deepcopy(result)

    def _before_first(self):
        if not self._committed:
            require(_state_hash(self._writer._state_view(self._env),self._writer)==self._origin_state_sha256,
                    'inherited state changed before first explicit branch commit')

    def commit_plan(self, plan):
        require(not self._poisoned,'branch result unknown; do not replay a commit')
        self._before_first()
        index=len(self._env.trace);original_hash=digest(plan)
        try:
            result=self._env.commit_plan(plan)  # Original executor; no crop/fill/keep/repair.
            require(digest(plan)==original_hash,'caller plan mutated during original commit')
            if not self._committed:
                self._committed=True  # Physical commit happened before receipt I/O.
                publish(self._directory/'first_commit.json',{'schema':SCHEMA+'-first-commit',
                    'branch_identity':self._receipt['branch_identity'],'shared_start_id':self._receipt['shared_start_id'],
                    'trace_event_index':index,'plan_sha256':original_hash,'executor_result':result,
                    'source':'explicit caller plan; arm model/tool attribution remains external'})
            return result
        except BaseException as exc:
            self._poisoned=True;_failure(self._directory,exc);raise

    def advance_plan(self, until=None):
        require(not self._poisoned and self._committed,'first explicit new branch commit required before any advancement')
        try:return self._env.advance_plan(until)  # Inherited work and newly explicit plan only.
        except BaseException as exc:
            self._poisoned=True;_failure(self._directory,exc);raise

    def next_period_boundary(self):
        w=self._receipt['evaluation_window'];now=self._env.t;anchor=w['period_anchor'];period=w['period_seconds']
        return min(w['absolute_end'],anchor+(math.floor((now-anchor)/period)+1)*period)


def restore_shared_start(directory, *, expected_manifest_sha256, branch_dir, branch_identity):
    """Restore one distinct branch without advancing or changing private state."""
    require(type(branch_identity)is dict and set(branch_identity)=={'arm','run_id','registration_sha256'}
            and branch_identity['arm'] in ('A','B','C') and name_string(branch_identity['run_id'])
            and sha_string(branch_identity['registration_sha256']),'new explicit arm/run/registration identity required')
    started=time.perf_counter();directory=Path(directory).resolve();branch_dir=Path(branch_dir).resolve()
    require(not branch_dir.is_relative_to(directory) and not directory.is_relative_to(branch_dir),'branch must be independent of immutable package')
    manifest=read_shared_start(directory,expected_manifest_sha256=expected_manifest_sha256)
    environment,writer,observation=_runtime()
    require(environment.VERSION==manifest['snapshot_version'] and environment.snapshot_dependencies()==manifest['implementation_sha256'],
            'restore with exact original dependency version; do not rewrite old snapshot hashes')
    root=Path(__file__).resolve().parents[2]
    for name,sha in manifest['wrapper_sha256'].items():read_bytes(root/relative(name),sha,retain=False)
    branch_dir.mkdir(parents=True,exist_ok=False)
    try:
        publish(branch_dir/'claim.json',{'schema':SCHEMA+'-branch-claim','branch_identity':branch_identity,
            'shared_start_id':manifest['shared_start_id'],'manifest_sha256':expected_manifest_sha256,
            'pid':os.getpid(),'automatic_retry':False})
        env=environment.FullFabEnvironment.from_snapshot(directory/'snapshot.json',trace_path=branch_dir/'trace.jsonl',data_dir=directory/'data')
        n=manifest['prehistory_receipt']['event_count'];marker={'seq':n,'time':manifest['evaluation_window']['absolute_start'],
            'kind':'snapshot_loaded','snapshot_sha256':manifest['state_sha256'],'prefix_event_count':n}
        require(len(env.trace)==n+1 and canonical(env.trace[-1])==canonical(marker),'restore must add exactly one original snapshot_loaded marker')
        view=writer._state_view(env);view['trace']=env.trace[:-1]
        require(_state_hash(view,writer)==manifest['state_sha256'],'full original restored state differs; no reset/cleanup tolerated')
        require(env.active_task is None,'restoration introduced an active dispatch')
        public=observation.build_problem(env,plan_seconds=manifest['evaluation_window']['plan_seconds'],
                                        lookahead_depth=manifest['evaluation_window']['lookahead_depth'])
        require(public.get('frozen_tasks')==[] and public.get('scope')==manifest['boundary_summary']['production_scope'],
                'public observation must preserve full scope and reject unsupported commitments')
        from .trace_source import inspect_jsonl,open_verified
        seal=inspect_jsonl(branch_dir/'trace.jsonl');prefix=hashlib.sha256();count=0
        with open_verified(seal) as reader:
            for record in reader:
                require(count<len(env.trace) and canonical(strict(record.raw_line))==canonical(env.trace[count]),'restored trace output differs from full state')
                if count<n:prefix.update(record.raw_line)
                count+=1
        require(count==n+1,'restored output prefix/marker count differs')
        unchanged=writer._state_view(env);unchanged['trace']=env.trace[:-1]
        require(_state_hash(unchanged,writer)==manifest['state_sha256'], 'observation/trace verification altered original physical state')
        complete_state_sha=_state_hash(writer._state_view(env),writer)
        receipt={'schema':SCHEMA+'-branch-start','branch_identity':deepcopy(branch_identity),
            'shared_start_id':manifest['shared_start_id'],'package_manifest_sha256':expected_manifest_sha256,
            'snapshot_sha256':manifest['snapshot_sha256'],'original_state_sha256':manifest['state_sha256'],
            'restored_state_with_marker_sha256':complete_state_sha,'original_prehistory_receipt':manifest['prehistory_receipt'],
            'restored_trace_receipt':asdict(reader.receipt),'restored_prefix_raw_sha256':prefix.hexdigest(),
            'restored_prefix_bytes_equal_original':prefix.hexdigest()==manifest['prehistory_receipt']['sha256'],
            'prehistory_event_content_order_equal':True,'restore_marker':marker,'branch_event_start_index':n+1,
            'evaluation_window':manifest['evaluation_window'],'source_observation_start':env.observation_start,
            'first_public_problem_sha256':digest(public),'original_plan_sha256':manifest['boundary_summary']['original_plan_sha256'],
            'executed_tasks_sha256':manifest['boundary_summary']['executed_tasks_sha256'],
            'inherited_physical_work':manifest['boundary_summary'],'shared_cost_reference':manifest['shared_cost_reference'],
            'branch_cost':{'scope':'this restore/validation only; future branch model/solver/constructor/ledger costs external',
                'wall_seconds_before_receipt_publication':time.perf_counter()-started,'model_calls':0,'solver_calls':0,
                'random_draws_by_wrapper':0,'shared_cost_included_in_branch_increment':False},
            'first_new_plan_required':True,'adapter_integration_pending':True,'steady_state_certified':False,
            'scope':'exact private restore and common public observation only; no experiment acceptance or independent warmup audit'}
        require(read_shared_start(directory,expected_manifest_sha256=expected_manifest_sha256)==manifest,'original package changed during restore')
        sha=publish(branch_dir/'start_receipt.json',receipt)
        read_bytes(branch_dir/'trace.jsonl',reader.receipt.sha256,retain=False)
        read_bytes(branch_dir/'start_receipt.json',sha,retain=False)
        expected_files={**manifest['members'],'manifest.json':read_bytes(directory/'manifest.json',expected_manifest_sha256,retain=False)[1]}
        require(_files(directory)==expected_files,'package changed before branch return')
        return Branch(env,writer,observation,branch_dir,{**receipt,'receipt_sha256':sha})
    except BaseException as exc:
        _failure(branch_dir,exc);raise
