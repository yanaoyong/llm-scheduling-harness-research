"""Blocked A24 capacity-gate draft; no launch authority from this module.

One cold offline run, unchanged A8 planner, full stream bundle and exact restore.
The complete host publication/exit closure is a separate pending integration.
Never reuse an attempt, resume a partial run, edit old evidence or call a model.
"""
from __future__ import annotations
import argparse
from contextlib import nullcontext
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import sys
import time
import traceback
from .offline_pilot import ROOT, DATA, VENDOR, _runtime, _origin_git, _git_pointer, _serial_lock
from .offline_A_gate_v3 import AUDIT_DEPENDENCIES, AUDIT_EVIDENCE_KEYS, _active_with_finalizers
from .model_process_guard import run_guarded, verify_lifecycle

SCHEMA = 'smt-fullfab-offline-A24-gate-v4'
RUN_ID = 'A_1701_24h_hybrid_v1'
PROTOCOL = 'configs/smt_fullfab/A_hybrid_24h_v1.protocol.json'
AREA = 'runs/smt_fullfab_offline_A_gate'
CHILD_SECONDS, OUTER_SECONDS, READBACK_SECONDS, RESTORE_SECONDS = 10800, 12600, 1200, 900
TRACE_BYTES, MAX_BYTES, MIN_FREE_BYTES, RSS_BYTES = 4*1024**3, 32*1024**3, 64*1024**3, 8*1024**3
EXPECTED = dict(arm='A', run_id=RUN_ID, seconds=86400, seed=1701,
    wall_seconds=10800.0, max_plans=3600, plan_seconds=14400, period_seconds=1800,
    lookahead_depth=2, solver_seconds=2.0, solver_budget_seconds=96.0,
    max_slots=4, snapshot_path=None, solver_method='hybrid', max_log_bytes=MAX_BYTES,
    constructor_seconds=5.0, max_candidate_evaluations=250000,
    max_trace_bytes=TRACE_BYTES, audit_mode='stream', snapshot_mode='stream')
LAUNCH_BLOCKERS = ()
ALGORITHM_SOURCES = {'src/smt_fullfab/runner.py': '3235ffa2346a887ab294e5696ffd7245150b6707155e0e203bce25e80a200c70', 'src/smt_fullfab/hybrid.py': '3c89ea263fdace8cb3636b5119e60374944ae2a2ea8d1e9c558cc0496f9cf6bd', 'src/smt_fullfab/optimizer.py': '30a0d40c9d94f7e462447d8496d21237089e12bd66ab142c51f9ae7346f72d60', 'src/smt_fullfab/decomposition.py': '0f558c3be26a093f3099ad8c61a2587dda42d85ddef175ed80c425ea3aaf3a4f', 'src/smt_fullfab/incumbent.py': 'faa6c1e9246f0462ee68d7f9ceb05931c37d461e5f43a6b43f728bf1860a9bd6', 'src/smt_fullfab/constructive_tool.py': '824de288425783f0a23b79f617bc3505e42e4b37280ff90617cb15e61b956c86'}
PREREQUISITE_ROLES = {'terminal_report': 'artifacts/smt_fullfab_diagnostics/A_8h_hybrid_v3_terminal_v1/report.json', 'readback': 'artifacts/smt_fullfab_recovery/A_8h_hybrid_v3_acceptance_readback_v1/result.json', 'restore': 'artifacts/smt_fullfab_recovery/A_8h_hybrid_v3_final_restore_v1/result.json', 'readback_process': 'artifacts/smt_fullfab_recovery/A_8h_hybrid_v3_acceptance_readback_v1/process_result.json', 'restore_process': 'artifacts/smt_fullfab_recovery/A_8h_hybrid_v3_final_restore_v1/process_result.json'}


def require(ok, message):
    if not ok:
        raise ValueError(message)



def encoded(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)+'\n').encode('utf-8')



def same(a, b):
    return json.dumps(a, sort_keys=True, separators=(',', ':'), allow_nan=False) == json.dumps(b, sort_keys=True, separators=(',', ':'), allow_nan=False)



def number(value, *, minimum=0, maximum=None):
    return (type(value) in (int, float) and math.isfinite(value) and value >= minimum
            and (maximum is None or value <= maximum))



def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()



def strict(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, 'duplicate JSON key')
            value[key] = item
        return value
    value = json.loads(raw, object_pairs_hook=pairs)
    same(value, value)
    return value



def identity(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)



def read_file(path, *, expected_sha256=None, keep_bytes=False):
    """Hash the exact same complete FD bytes that a JSON caller will parse."""
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and identity(before) == identity(path.lstat()), 'nonregular/replaced evidence')
        hasher, count, chunks = hashlib.sha256(), 0, []
        while True:
            block = stream.read(1024*1024)
            if not block:
                break
            count += len(block)
            hasher.update(block)
            if keep_bytes:
                chunks.append(block)
        require(count == before.st_size and identity(before) == identity(os.fstat(stream.fileno())) == identity(path.lstat()), 'evidence changed during full read')
    sha = hasher.hexdigest()
    require(expected_sha256 is None or sha == expected_sha256, 'original SHA binding differs: '+str(path))
    return (b''.join(chunks) if keep_bytes else None), {'sha256': sha, 'bytes': count, 'file_identity': list(identity(before))}



def read_json(path, expected_sha256=None):
    raw, receipt = read_file(path, expected_sha256=expected_sha256, keep_bytes=True)
    return strict(raw), receipt



def write_new(path, value, *, raw=False):
    data = value if raw else encoded(value)
    with Path(path).open('xb') as stream:
        require(stream.write(data) == len(data), 'short evidence write')
        stream.flush(); os.fsync(stream.fileno())
    return hashlib.sha256(data).hexdigest()



def validate_protocol(protocol):
    require(protocol.get('schema') == SCHEMA+'-protocol' and protocol.get('formal') is False
            and protocol.get('execute_now') is False and same(protocol.get('run_parameters'), EXPECTED), 'fixed A24 configuration differs')
    limits = dict(child_seconds=CHILD_SECONDS, outer_seconds=OUTER_SECONDS,
        readback_seconds=READBACK_SECONDS, restore_seconds_within_readback=RESTORE_SECONDS,
        trace_bytes=TRACE_BYTES, all_retained_bytes=MAX_BYTES, minimum_free_bytes=MIN_FREE_BYTES,
        maximum_per_pid_peak_rss_bytes=RSS_BYTES, rss_is_hard_guard=False, serial_only=True,
        model_calls=0, periodic_cp_calls=48, cp_requested_seconds=96,
        constructor_seconds=5, max_candidate_evaluations=250000, max_plans=3600)
    require(same(protocol.get('limits'), limits), 'fixed A24 capacity limits differ')
    require(protocol.get('prerequisite_roles') == PREREQUISITE_ROLES
            and protocol.get('algorithm_sha256') == ALGORITHM_SOURCES, 'A8 prerequisite/algorithm contract differs')
    refs=protocol.get('prerequisite_sha256')
    require(type(refs) is dict and set(refs)==set(PREREQUISITE_ROLES.values()), 'prerequisite anchors missing')
    for name, value in refs.items():
        require(type(value) is str and len(value)==64 and all(c in '0123456789abcdef' for c in value), 'bad prerequisite SHA')
    additional=protocol.get('additional_frozen_files')
    require(type(additional) is list and len(additional)==len(set(additional)) and all(type(p) is str
        and not Path(p).is_absolute() and '..' not in Path(p).parts for p in additional), 'unsafe supplemental frozen path')
    return dict(EXPECTED)


def prerequisite_proof(root, protocol):
    """Use original saved A8 metadata, never edit/rerun the original A8 result."""
    objects={p:read_json(Path(root)/p,h)[0] for p,h in protocol['prerequisite_sha256'].items()}
    at=lambda role:objects[PREREQUISITE_ROLES[role]]
    terminal,check,restore=at('terminal_report'),at('readback'),at('restore')
    require(terminal.get('schema')=='smt-fullfab-A8-v3-descriptive-terminal-report-v1'
        and terminal.get('accepted') is True and terminal.get('exact_restoration_verified') is True
        and terminal.get('formal') is False and terminal.get('production_responsibility')==913
        and terminal['metrics']['window_start']==0 and terminal['metrics']['window_end']==28800,
        'real completed A8 prerequisite absent')
    require(check.get('valid') is True and check.get('accepted') is True and check.get('errors')==[]
        and check['result_sha256']==terminal['inputs_sha256']['runs/smt_fullfab_development/A_1701_8h_hybrid_v3/result.json'], 'A8 original readback absent')
    require(restore.get('valid') is True and restore.get('complete_snapshot_dependency_binding') is True
        and restore['restored_state_sha256']==restore['expected_state_sha256']
        and restore['simulation_seconds']==restore['horizon_seconds']==28800
        and restore['production_scope']==913 and restore['model_calls']==restore['solver_calls']==0,
        'A8 original exact restore absent')
    for role in ('readback','restore'):
        path=PREREQUISITE_ROLES[role]; process=at(role+'_process')
        require(terminal['inputs_sha256'].get(path)==protocol['prerequisite_sha256'][path]
            and terminal['inputs_sha256'].get(PREREQUISITE_ROLES[role+'_process'])==protocol['prerequisite_sha256'][PREREQUISITE_ROLES[role+'_process']]
            and type(process.get('returncode')) is int and process['returncode']==0
            and process.get('timed_out') is False and process.get('original_terminal_files_unchanged') is True
            and process.get('result_sha256')==protocol['prerequisite_sha256'][path]
            and process['original_terminal_hashes_after']['checkpoint_sha256']==restore['checkpoint_sha256']
            and process['model_calls']==process['solver_calls']==0, 'A8 prerequisite process/source binding differs')
    for path, expected in ALGORITHM_SOURCES.items():
        read_file(Path(root)/path,expected_sha256=expected)
    return {'real_A8_accepted':True,'real_A8_exact_restore':True,
            'prerequisite_sha256':dict(protocol['prerequisite_sha256']), 'algorithm_sha256':dict(ALGORITHM_SOURCES)}


def input_paths(root, protocol):
    paths=[]
    for name in ('src', VENDOR, DATA):
        base=Path(root)/name;require(base.is_dir(), 'missing required source/input tree: '+name)
        for p in sorted(base.rglob('*')):
            if '__pycache__' in p.parts or p.suffix in ('.pyc','.pyo'): continue
            require(not p.is_symlink(), 'frozen input symlink')
            if p.is_file(): paths.append(p)
    paths.extend(Path(root).glob('requirements*'))
    paths.extend(Path(root)/p for p in [PROTOCOL,*protocol['prerequisite_sha256'],*protocol['additional_frozen_files']])
    require(Path(root)/'requirements.lock' in paths,'requirements lock missing')
    require(all(p.is_file() and not p.is_symlink() for p in paths),'nonregular frozen input')
    return sorted(set(paths))


def inventory(root, protocol):
    return {p.relative_to(root).as_posix():read_file(p)[1]['sha256'] for p in input_paths(root,protocol)}


def runtime_capture():
    # No CLI or --version subprocess: offline A has exactly zero model calls.
    return _runtime()


def prepare(*,root=ROOT):
    require(not LAUNCH_BLOCKERS,'A24 preparation blocked: '+'; '.join(LAUNCH_BLOCKERS))
    root=Path(root).resolve();campaign=root/AREA/RUN_ID;started=time.monotonic()
    require(not campaign.exists(), 'existing campaign; never reprepare')
    protocol=read_json(root/PROTOCOL)[0];validate_protocol(protocol)
    with _serial_lock(root):
        require(not _active_with_finalizers(root),'active experiment/finalizer')
        require(not (root/'runs/smt_fullfab_development'/RUN_ID).exists(),'original target already exists')
        require(shutil.disk_usage(root).free>=MIN_FREE_BYTES,'insufficient free disk')
        prerequisite=prerequisite_proof(root,protocol)
        inputs,runtime,head=inventory(root,protocol),runtime_capture(),_origin_git(root)
        campaign.mkdir(parents=True,exist_ok=False);frozen=campaign/'frozen';frozen.mkdir()
        try:
            for name,sha in inputs.items():
                raw,_=read_file(root/name,expected_sha256=sha,keep_bytes=True)
                target=frozen/name;target.parent.mkdir(parents=True,exist_ok=True)
                write_new(target,raw,raw=True);target.chmod(0o444)
            require(inputs==inventory(root,protocol) and runtime==runtime_capture(),'inputs/runtime changed during freeze')
            require((root/'runs').is_dir(),'actual output root missing')
            (frozen/'runs').symlink_to(root/'runs',target_is_directory=True);_git_pointer(frozen,head)
            manifest=dict(schema=SCHEMA+'-frozen',run_id=RUN_ID,origin_root=str(root),origin_git_head=head,
                config=dict(EXPECTED),protocol_sha256=inputs[PROTOCOL],frozen_input_sha256=inputs,
                runtime=runtime,launcher_executable=sys.executable,
                output_directory=str(root/'runs/smt_fullfab_development'/RUN_ID),
                prerequisite_proof=prerequisite,prepare_wall_seconds=time.monotonic()-started,
                launch_blockers=list(LAUNCH_BLOCKERS),formal=False,model_calls=0,
                origin_git_is_clean_checkout_claim=False)
            manifest['identity']=digest(manifest);write_new(campaign/'manifest.json',manifest)
            return campaign,manifest
        except BaseException as exc:
            write_new(campaign/'freeze_failure.json',dict(type=type(exc).__name__,message=str(exc)))
            raise


def verify_frozen(campaign,manifest,*,for_execution=False):
    campaign=Path(campaign).resolve();root=Path(manifest['origin_root']);frozen=campaign/'frozen'
    require(campaign==root/AREA/RUN_ID and manifest['schema']==SCHEMA+'-frozen'
        and manifest['identity']==digest({k:v for k,v in manifest.items() if k!='identity'}),'frozen path/identity differs')
    require(same(read_json(campaign/'manifest.json')[0],manifest),'manifest original bytes changed')
    protocol=read_json(frozen/PROTOCOL,manifest['protocol_sha256'])[0];validate_protocol(protocol)
    require(inventory(frozen,protocol)==manifest['frozen_input_sha256'],'frozen inventory changed')
    require(all(not (frozen/n).stat().st_mode & 0o222 for n in manifest['frozen_input_sha256']),'frozen input writable')
    require(same(manifest['config'],EXPECTED) and manifest['model_calls']==0,'fixed offline config differs')
    require((frozen/'runs').is_symlink() and (frozen/'runs').resolve()==root/'runs','actual output mapping differs')
    require(manifest['output_directory']==str(root/'runs/smt_fullfab_development'/RUN_ID),'output path differs')
    require(same(prerequisite_proof(frozen,protocol),manifest['prerequisite_proof']),'frozen prior A8 proof differs')
    if for_execution:
        require(not LAUNCH_BLOCKERS,'unreviewed A24 draft')
        require(runtime_capture()==manifest['runtime'] and sys.executable==manifest['launcher_executable'],'runtime changed')
        read_file(__file__,expected_sha256=manifest['frozen_input_sha256']['src/smt_fullfab/offline_A_gate_v4.py'])


def files(base, *, campaign=False):
    base = Path(base)
    if not base.exists(): return []
    result = []
    for path in sorted(base.rglob('*')):
        if path.is_symlink():
            require(campaign and path in (base/'frozen/runs',), 'unexpected evidence symlink')
            continue
        if path.is_file(): result.append(path)
    return result



def evidence(campaign, run, *, include_outer=False):
    return {prefix+'/'+p.relative_to(base).as_posix(): read_file(p)[1]['sha256']
            for prefix,base in (('campaign', Path(campaign)), ('run', Path(run)))
            for p in files(base, campaign=prefix == 'campaign') if p != Path(campaign)/'acceptance.json'
            and (include_outer or prefix!='campaign' or (base/'outer_process') not in p.parents)}



def total_bytes(campaign, run):
    return sum(p.stat().st_size for p in files(campaign, campaign=True)+files(run))



def bind_first(verified, final):
    """Original verified anchors remain authoritative; never adopt later bytes."""
    require(type(verified) is dict and verified, 'original verification anchors missing')
    require(all(final.get(k) == v for k,v in verified.items()), 'verified evidence changed before acceptance')
    require({k:v for k,v in final.items() if k.startswith('run/')} ==
            {k:v for k,v in verified.items() if k.startswith('run/')}, 'raw run inventory changed after verification')



def bind_receipts(verified, final):
    """Small late-produced proofs must retain their first parsed raw SHA too."""
    require(all(final.get(name) == sha for name,sha in verified.items()), 'first parsed phase proof changed before acceptance')



def _validate_run(run, manifest, first):
    """Inspect saved evidence only; physical audit was run inside the child."""
    run=Path(run)
    def _sha(path):
        relative='run/'+Path(path).relative_to(run).as_posix()
        require(relative in first,'unregistered original run file: '+relative)
        return read_file(path,expected_sha256=first[relative])[1]['sha256']
    def _read(path):
        relative='run/'+Path(path).relative_to(run).as_posix()
        require(relative in first,'unregistered original run JSON: '+relative)
        return read_json(path,first[relative])[0]
    def _read_bound_json(path,sha):
        require(first['run/'+Path(path).relative_to(run).as_posix()]==sha,'bundle original reference differs')
        return _read(path)
    _digest=digest
    _trace_size=lambda directory: (directory/'trace.jsonl').stat().st_size
    def _bundle_storage_readback(directory,unused_manifest,expected_sha):
        from .stream_audit_bundle import read_bundle
        return read_bundle(directory/'audit_bundle',expected_manifest_sha256=expected_sha)
    result, config, provenance = (_read(run / name) for name in ('result.json', 'config.json', 'provenance.json'))
    if _trace_size(run)>TRACE_BYTES:raise ValueError('final runner resource limit exceeded')
    expected = manifest['config']
    if config != expected or result.get('config') != expected or result.get('identity') != _digest(expected):
        raise ValueError('runner configuration/identity differs')
    inputs = manifest['frozen_input_sha256']
    sources = {k: v for k, v in inputs.items() if Path(k).parent.as_posix() in ('src/smt', 'src/smt_fullfab') and k.endswith('.py')}
    if (provenance.get('source_sha256') != sources or provenance.get('requirements_sha256') != inputs['requirements.lock']
            or provenance.get('git_commit') != manifest['origin_git_head'] or result.get('provenance') != provenance):
        raise ValueError('runner source provenance differs from frozen inventory')
    for relative, sha in {**sources, 'src/__init__.py': inputs['src/__init__.py']}.items():
        if _sha(run / 'source_snapshot' / relative) != sha:raise ValueError('saved source differs: ' + relative)
    if result.get('model_calls') != 0 or result.get('formal') is not False:raise ValueError('not a zero-model development result')
    with (run / 'trace.jsonl').open('rb') as stream:initial = json.loads(next(stream))
    hashes = {Path(k).name: v for k, v in inputs.items() if k.startswith(DATA + '/')}
    if initial.get('kind') != 'initial' or initial.get('manifest', {}).get('data_hashes') != hashes:
        raise ValueError('trace input hashes differ')
    raw,_=read_file(run/'resources.jsonl',expected_sha256=first['run/resources.jsonl'],keep_bytes=True)
    rows = [strict(line) for line in raw.splitlines() if line.strip()]
    reserves = [r for r in rows if r.get('event') == 'solver_reserve']
    finishes = [r for r in rows if r.get('event') == 'solver_finish']
    if (len(rows) != len(reserves) + len(finishes) or len(reserves) != len(finishes)
            or [r.get('plan') for r in reserves] != list(range(len(reserves)))
            or [r.get('plan') for r in finishes] != list(range(len(finishes)))
            or rows != [row for pair in zip(reserves, finishes) for row in pair]):
        raise ValueError('planner reservations/finishes incomplete or duplicated')
    for prefix in ('problem', 'solver'):
        expected_files = {f'{prefix}_{i:05d}.json' for i in range(len(reserves))}
        if {p.name for p in run.glob(prefix + '_*.json')} != expected_files:
            raise ValueError('saved ' + prefix + ' files do not exactly match planner reservations')
    periodic = 0; next_periodic=0; previous_time=-1
    for reserve, finish in zip(reserves, finishes):
        mode = reserve.get('planner_mode')
        if (mode not in ('periodic_cp', 'event_classical') or finish.get('planner_mode') != mode
                or reserve.get('requested_seconds') != (2 if mode == 'periodic_cp' else 0)):
            raise ValueError('unexpected planner mode/CP allocation')
        problem=_read(run / f"problem_{reserve['plan']:05d}.json")
        now=problem.get('time')
        require(number(now) and now<86400 and now>=previous_time,'invalid/nonmonotonic problem time')
        require(problem.get('horizon_end')==now+14400,'planning horizon changed')
        if mode=='periodic_cp':
            require(now==next_periodic,'absolute 30 minute periodic boundary missing/delayed')
            next_periodic+=1800
        else:
            require(now<next_periodic,'event plan must not postpone periodic optimization')
        previous_time=now
        periodic += mode == 'periodic_cp'
        if mode == 'event_classical' and (reserve.get('constructor_seconds_limit') != 5 or reserve.get('max_candidate_evaluations') != 250000):
            raise ValueError('event construction bounds differ')
        response = _read(run / f"solver_{reserve['plan']:05d}.json")
        if (response.get('solver_status') != finish.get('solver_status') or response.get('hybrid_mode') != mode
                or response.get('solver_status') not in ('FEASIBLE_HEURISTIC', 'FEASIBLE', 'OPTIMAL')
                or not isinstance(response.get('nominal_audit'), dict) or response['nominal_audit'].get('valid') is not True):
            raise ValueError('planner response lacks valid explicit nominal plan')
        for key in ('wall_seconds', 'solve_wall_seconds', 'classical_construction_wall_seconds'):
            value = finish.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError('invalid planner measured duration: ' + key)
            if response.get(key) != finish.get(key):raise ValueError('planner timing differs: ' + key)
    requested = sum(r['requested_seconds'] for r in reserves)
    totals = dict(planner_calls=len(reserves), cumulative_planner_calls=len(reserves), plans=len(reserves),
                  solver_calls=periodic, classical_event_calls=len(reserves) - periodic, solver_requested_seconds=requested,
                  actual_cp_solve_seconds=sum(r['solve_wall_seconds'] for r in finishes),
                  planner_wall_seconds=sum(r['wall_seconds'] for r in finishes),
                  classical_construction_wall_seconds=sum(r['classical_construction_wall_seconds'] for r in finishes))
    if any(result.get(k) != v for k, v in totals.items()):raise ValueError('result planner totals differ from resource evidence')
    checkpoint = _read(run / 'checkpoint_resources.json')
    if (checkpoint.get('parent_checkpoint') is not None or checkpoint.get('solver_method') != 'hybrid'
            or checkpoint.get('solver_budget_seconds') != 96 or checkpoint.get('scenario_seed') != 1701
            or checkpoint.get('model_calls') != 0 or checkpoint.get('log_bytes_in_earlier_runs') != 0
            or checkpoint.get('hybrid_resource_limits') != dict(runner_wall_seconds=10800.0, max_plans=3600, max_log_bytes=MAX_BYTES,
                max_trace_bytes=TRACE_BYTES,audit_mode='stream',snapshot_mode='stream')
            or checkpoint.get('cumulative_solver_requested_seconds') != requested
            or checkpoint.get('cumulative_planner_calls') != len(reserves)):
        raise ValueError('checkpoint resource inheritance differs')
    if not (run / 'checkpoint.json').is_file():raise ValueError('successful run lacks actual physical checkpoint')
    if (result.get('checkpoint') != 'runs/smt_fullfab_development/'+RUN_ID+'/checkpoint.json'
            or result.get('checkpoint_failure') is not None):
        raise ValueError('successful run lacks completed checkpoint reference')
    if (run/'audit.json').exists():raise ValueError('stream gate must preserve bundle, not produce legacy full audit.json')
    reference=result.get('audit_bundle')
    if (type(reference) is not dict or set(reference)!={'path','manifest_sha256'} or reference.get('path')!='audit_bundle'
            or type(reference.get('manifest_sha256')) is not str or len(reference['manifest_sha256'])!=64
            or any(c not in '0123456789abcdef' for c in reference['manifest_sha256'])):
        raise ValueError('missing/extraneous/unsafe audit bundle reference')
    checked=_bundle_storage_readback(run,manifest,reference['manifest_sha256'])
    audit=_read_bound_json(run/'audit_bundle/audit_bundle.json',reference['manifest_sha256'])
    source=_read_bound_json(run/'audit_bundle/source.json',audit['members']['source.json']['sha256'])
    summary=audit.get('summary',{});envelope=audit.get('envelope',{});receipt=audit.get('source_receipt',{})
    if (checked.get('storage_verified') is not True or checked.get('semantic_replay_performed') is not False
            or checked.get('manifest_sha256')!=reference['manifest_sha256'] or checked.get('summary')!=summary
            or checked.get('source_receipt')!=receipt or _sha(run/'audit_bundle/audit_bundle.json')!=reference['manifest_sha256']
            or receipt.get('sha256')!=_sha(run/'trace.jsonl') or receipt.get('byte_count')!=_trace_size(run)
            or audit.get('dependency_sha256')!={k:inputs[k] for k in AUDIT_DEPENDENCIES}
            or audit.get('bundle_source_sha256')!=inputs['src/smt_fullfab/stream_audit_bundle.py']
            or envelope.get('terminal_at_eof') is not True or envelope.get('last_time')!=86400 or envelope.get('horizon')!=86400
            or envelope.get('receipt')!=receipt or envelope.get('first_time')!=0
            or audit.get('configuration')!={'window_start':0,'priority_weights':None,'require_terminal':True,'verify_data_dir_supplied':True}):
        raise ValueError('bundle source/terminal/dependency/manifest binding differs')
    source_evidence=source.get('_source_evidence',{})
    if source_evidence.get('complete_jsonl_pass') is not True or source_evidence.get('source_receipt')!=receipt:
        raise ValueError('complete source report receipt differs')
    if not (result.get('status') == 'success' and result.get('audit_valid') is True
            and result.get('full_window_completed') is True and result.get('simulation_seconds') == 86400
            and all(summary.get(k) is True for k in ('valid','source_valid','opportunity_valid','physical_valid',
                'actual_dispatch_provenance_complete',
                'complete_physical_window_certified','absence_of_unreported_legal_demand_certified','verified_input_hashes'))
            and source.get('valid') is True and source.get('errors') == []
            and summary.get('source_errors') == summary.get('opportunity_errors') == []
            and type(source.get('production_machine_count')) is int and type(source.get('declared_control_machine_count')) is int
            and source.get('production_machine_count') == source.get('declared_control_machine_count') == 913
            and source.get('declared_full_factory_domain') is True and result.get('metrics') == summary.get('metrics')
            and periodic == 48):
        raise ValueError('full-window physical/source/opportunity evidence does not pass')
    metrics=summary.get('metrics')
    if (type(metrics) is not dict or set(metrics)!={'window_start','window_end','weighted_tardy_lot_hours',
            'throughput_lots','terminal_wip_lots','terminal_tardy_wip_lots'}
            or metrics['window_start']!=0 or metrics['window_end']!=86400
            or any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in metrics.values())):
        raise ValueError('primary metric summary differs from six-field contract')
    if (len(reserves) > 3600 or requested > 96 or (run / 'trace.jsonl').stat().st_size > TRACE_BYTES
            or type(result.get('wall_seconds')) not in (int, float) or not 0 <= result['wall_seconds'] <= 10800):
        raise ValueError('final runner resource limit exceeded')
    # Carry the originally checked hashes across final evidence collection.
    # Never re-read a changed manifest to manufacture replacement expectations.
    verified = {'run/audit_bundle/audit_bundle.json':reference['manifest_sha256'],
                'run/trace.jsonl':receipt['sha256']}
    verified.update({'run/audit_bundle/'+name:metadata['sha256'] for name,metadata in audit['members'].items()})
    require(requested==96 and next_periodic==86400,'48 original periodic requests not fully accounted')
    return result, totals, verified



def _check_audit_binding(verified, evidence):
    if type(verified) is not dict or set(verified)!=AUDIT_EVIDENCE_KEYS:
        raise ValueError('final audit evidence binding is incomplete')
    mismatches=[key for key in sorted(verified) if evidence.get(key)!=verified[key]]
    if mismatches:raise ValueError('final audit evidence differs from verified hashes: '+', '.join(mismatches))



def verification_payload(campaign,manifest,first):
    """Bound readback inside one guarded phase; no model/optimizer is invoked."""
    run=Path(manifest['output_directory'])
    bind_first(first,evidence(campaign,run))
    result,totals,audit_anchors=_validate_run(run,manifest,first)
    _check_audit_binding(audit_anchors,first)
    checkpoint=read_json(run/'checkpoint.json',first['run/checkpoint.json'])[0]
    require(checkpoint.get('schema')=='smt-fullfab-snapshot-1','physical checkpoint schema differs')
    state=checkpoint.get('state',{})
    require(state.get('seed')==1701 and state.get('t')==state.get('horizon')==86400
        and state.get('finished') is True and state.get('observation_start')==0,'checkpoint is not cold full 24h terminal')
    ref={'file_sha256':first['run/checkpoint.json'],'state_sha256':checkpoint['state_sha256']}
    del checkpoint,state
    bundle=read_json(run/'audit_bundle/audit_bundle.json',first['run/audit_bundle/audit_bundle.json'])[0]
    proof={'valid':True,'schema':SCHEMA+'-verification','verified_evidence_sha256':dict(first),
        'checkpoint':ref,'first_trace_receipt':bundle['source_receipt'],'result_wall_seconds':result['wall_seconds'],
        'totals':totals,'metrics':result['metrics'],'model_calls':0,'semantic_audits_rerun':False}
    bind_first(first,evidence(campaign,run))
    return proof


def restoration_payload(campaign,manifest,proof):
    """Restore the original full state, compare raw trace, never advance or retime."""
    from .environment import FullFabEnvironment
    from .stream_snapshot import _state_view, _chunks, write_snapshot
    from .trace_source import inspect_jsonl, open_verified
    run=Path(manifest['output_directory']);ref=proof['checkpoint'];first=proof['verified_evidence_sha256']
    bind_first(first,evidence(campaign,run))
    original=read_json(run/'checkpoint.json',ref['file_sha256'])[0]
    require(original['state_sha256']==ref['state_sha256'],'original state SHA differs')
    prefix_events=len(original['state']['trace']);del original
    env=FullFabEnvironment.from_snapshot(run/'checkpoint.json',data_dir=Path(campaign)/'frozen'/DATA)
    require(env.seed==1701 and env.t==env.horizon==86400 and env.finished is True
        and env.observation_start==0 and len(env.physical)==913,'restored scope/window differs')
    require(len(env.trace)==prefix_events+1 and same(env.trace[-1],
        {'seq':prefix_events,'time':86400.0,'kind':'snapshot_loaded','snapshot_sha256':ref['state_sha256'],
         'prefix_event_count':prefix_events}),'unexpected snapshot restore mutation/marker')
    # Shallow list view only: canonical serializer is the original snapshot implementation.
    restored=_state_view(env);restored['trace']=env.trace[:-1]
    hasher=hashlib.sha256()
    for chunk in _chunks(restored):hasher.update(chunk)
    require(hasher.hexdigest()==ref['state_sha256'],'full restored state differs')
    seal=inspect_jsonl(run/'trace.jsonl',expected_sha256=proof['first_trace_receipt']['sha256'])
    count=0
    with open_verified(seal) as reader:
        for record in reader:
            require(count<prefix_events and same(record.event,restored['trace'][count]),'checkpoint/raw trace differs')
            count+=1
    require(count==prefix_events,'missing/extra trace events')
    output=Path(campaign)/'restoration_scratch';output.mkdir(exist_ok=False)
    restored_document_sha=write_snapshot(env,output/'restored.json')
    restored_file=read_file(output/'restored.json')[1]
    bind_first(first,evidence(campaign,run))
    return dict(valid=True,checkpoint_sha256=ref['file_sha256'],restored_state_sha256=hasher.hexdigest(),
        snapshot_loaded_marker=env.trace[-1],restored_snapshot_sha256=restored_file['sha256'],
        restored_snapshot_state_sha256_including_marker=restored_document_sha,
        trace_events=count,simulation_seconds=env.t,production_scope=len(env.physical),
        simulation_advancement_performed=False,model_calls=0,solver_calls=0,restoration_scratch_retained=True)


def validate_restoration(result,proof,campaign):
    """Bind the original full-state SHA and retained restored bytes at collection."""
    ref=proof['checkpoint']
    require(result.get('valid') is True and result.get('checkpoint_sha256')==ref['file_sha256']
        and result.get('restored_state_sha256')==ref['state_sha256'], 'exact restored state/checkpoint differs')
    require(type(result.get('trace_events')) is int and result['trace_events']>=1,
        'missing restored full trace count')
    require(same(result.get('snapshot_loaded_marker'),dict(seq=result['trace_events'],time=86400.,
        kind='snapshot_loaded',snapshot_sha256=ref['state_sha256'],prefix_event_count=result['trace_events'])),
        'restored trace marker differs')
    read_file(Path(campaign)/'restoration_scratch/restored.json',expected_sha256=result['restored_snapshot_sha256'])


def owned_phase(command, *, cwd, output, timeout, output_paths=None, inputs=None):
    """One explicit generic owner-pipe phase, with original returned SHA anchors.

    run_guarded owns the actual child/session and reaps it. All complete phase
    records are create-new; failures leave partial evidence and never retry.
    """
    output=Path(output).resolve();output.mkdir(exist_ok=False)
    started=time.monotonic();guarded=None;primary=None
    request={'schema':SCHEMA+'-phase-request','command':list(command),'cwd':str(Path(cwd).resolve()),
        'timeout_seconds':timeout,'phase_directory':str(output),'call_id':RUN_ID+':'+output.name,
        'output_paths':{k:str(Path(v).resolve()) for k,v in (output_paths or {}).items()},
        'additional_inputs':{k:str(Path(v).resolve()) for k,v in (inputs or {}).items()}}
    request_sha=write_new(output/'phase_request.json',request)
    fingerprint=digest(request)
    io={'cwd':request['cwd'],'stdin':None,'stdout':str(output/'stdout.log'),'stderr':str(output/'stderr.log'),
        'inputs':{'approved_phase_request':str(output/'phase_request.json'),**request['additional_inputs']},
        'outputs':{'stdout':str(output/'stdout.log'),'stderr':str(output/'stderr.log'),**request['output_paths']}}
    require(all(not Path(path).exists() for path in io['outputs'].values()),'a declared phase output already exists; never reuse it')
    env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME','GIT_DIR','GIT_WORK_TREE','GIT_INDEX_FILE')}
    env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull)
    try:
        guarded=run_guarded(list(command),run_dir=output,timeout_seconds=timeout,env=env,
            call_id=request['call_id'],request_fingerprint=fingerprint,io_spec=io)
        if guarded['command_returncode']!=0 or guarded['timed_out'] or guarded['launch_error'] is not None:
            primary={'type':'GuardedCommandFailed','message':str({k:guarded[k] for k in ('command_returncode','timed_out','launch_error')})}
    except BaseException as exc:
        primary={'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()}
    rss=None if guarded is None else max(guarded['command_peak_rss_bytes'] or 0,guarded['guard_peak_rss_bytes'] or 0)
    result={'schema':SCHEMA+'-phase','phase_directory':str(output),'phase_request_sha256':request_sha,
        'request_fingerprint':fingerprint,'io_spec':io,'guard_evidence':guarded,
        'returncode':None if guarded is None else guarded['command_returncode'],
        'primary_failure':primary,'cleanup_errors':[] if guarded is not None else ['lifecycle incomplete; inspect original guard records'],
        'wall_seconds':time.monotonic()-started,'limit_seconds':timeout,'peak_rss_bytes':rss,
        'rss_is_hard_guard':False,'automatic_retry':False,'owner_pipe_guard_integrated':True}
    result_sha=write_new(output/'process.json',result)
    return {**result,'process_sha256':result_sha}



def phase_anchors(campaign, process, run=None):
    """Original write/parse receipts, never an inventory taken after validation."""
    phase=Path(process['phase_directory']);prefix='campaign/'+phase.relative_to(campaign).as_posix()+'/'
    result={prefix+'phase_request.json':process['phase_request_sha256'],prefix+'process.json':process['process_sha256']}
    guard=process.get('guard_evidence')
    if guard is not None:
        result.update({prefix+'process_guard/'+name:sha for name,sha in guard['files_sha256'].items()})
        for label,sha in guard['output_files_sha256'].items():
            if sha is None:continue
            path=Path(process['io_spec']['outputs'][label])
            if path.is_relative_to(campaign):result['campaign/'+path.relative_to(campaign).as_posix()]=sha
            else:
                require(run is not None and path.is_relative_to(run),'phase output lies outside original campaign/run')
                result['run/'+path.relative_to(run).as_posix()]=sha
    return result



def check_storage(campaign, run):
    require(total_bytes(campaign,run)<=MAX_BYTES,'checkpoint-detected combined storage cap exceeded')
    trace=Path(run)/'trace.jsonl'
    require(not trace.exists() or trace.stat().st_size<=TRACE_BYTES,'checkpoint-detected trace cap exceeded')



def verify_phase(campaign,manifest,process,*,command,maximum):
    """Independent readback of one original phase record and actual guard wait."""
    phase=Path(process['phase_directory'])
    require(phase.parent==Path(campaign) and phase.name in ('child_process','readback_process','restoration_process','outer_process'), 'unexpected phase directory')
    saved=read_json(phase/'process.json',process['process_sha256'])[0]
    require(same(saved,{k:v for k,v in process.items() if k!='process_sha256'}),'phase in-memory record differs from original bytes')
    request=read_json(phase/'phase_request.json',process['phase_request_sha256'])[0]
    require(request['command']==command and request['cwd']==str(Path(campaign)/'frozen')
            and number(request['timeout_seconds'],minimum=0,maximum=maximum) and request['timeout_seconds']>0
            and same(request['timeout_seconds'],process['limit_seconds'])
            and process['request_fingerprint']==digest(request),'phase original command/deadline differs')
    guard=verify_lifecycle(phase,expected_command=command,expected_timeout=request['timeout_seconds'],
        expected_call_id=request['call_id'],expected_fingerprint=process['request_fingerprint'],
        expected_evidence=process['guard_evidence'],expected_io_spec=process['io_spec'])
    require(guard['guard_source_sha256']==manifest['frozen_input_sha256']['src/smt_fullfab/model_process_guard.py']
            and same(guard['command_returncode'],process['returncode'])
            and number(guard.get('parent_wait_wall_seconds')) and guard['parent_wait_wall_seconds']<=process['wall_seconds']
            and process['peak_rss_bytes']==max(guard['command_peak_rss_bytes'] or 0,guard['guard_peak_rss_bytes'] or 0),
            'phase guard source/exit/measured RSS differs')
    _process_ok(process,maximum)
    return phase_anchors(Path(campaign),process,Path(manifest['output_directory']))



def _phase_command(campaign, manifest, kind, first_path=None, proof_path=None, *, first_sha='', proof_sha=''):
    code = "import sys;sys.path.insert(0,sys.argv[1]);from src.smt_fullfab.offline_A_gate_v4 import _worker;raise SystemExit(_worker(*sys.argv[2:]))"
    return [manifest['launcher_executable'],'-I','-B','-c',code,str(Path(campaign)/'frozen'),
            kind,str(campaign),manifest['identity'],str(first_path or ''),str(proof_path or ''),first_sha,proof_sha]



def _worker(kind, campaign, expected_identity, first_path='', proof_path='', first_sha='', proof_sha=''):
    require(not LAUNCH_BLOCKERS,'A24 private worker blocked')
    campaign = Path(campaign); manifest = read_json(campaign/'manifest.json')[0]
    require(manifest['identity'] == expected_identity
            and expected_identity == digest({k:v for k,v in manifest.items() if k!='identity'}), 'worker original manifest differs')
    if kind == 'supervise':
        result=_execute_reviewed(campaign,manifest,_under_outer_guard=True)
        return 0 if result['accepted'] else 1
    if kind == 'run':
        # This private entry is blocked too: importing this draft cannot bypass
        # public execute merely by calling a hidden argv or helper.
        require(not LAUNCH_BLOCKERS, 'A24 launch blocked: '+'; '.join(LAUNCH_BLOCKERS))
        from .runner import run
        result=run(**manifest['config'])
        return 0 if result['status'] == 'success' else 1
    require(len(first_sha)==64, 'worker requires externally passed first-anchor SHA')
    first = read_json(first_path,first_sha)[0]
    if kind == 'verify':
        result = verification_payload(campaign, manifest, first)
        write_new(campaign/'verification_payload.json', result)
    elif kind == 'restore':
        require(len(proof_sha)==64, 'restoration requires original parsed verification SHA')
        proof = read_json(proof_path,proof_sha)[0]
        require(proof['verified_evidence_sha256']==first,'restore received a different first-anchor map')
        result = restoration_payload(campaign, manifest, proof)
        write_new(campaign/'restoration_payload.json', result)
    else: raise ValueError('unknown owned phase')
    return 0 if result['valid'] else 1



def _process_ok(process, limit):
    guarded=process.get('guard_evidence')
    require(type(guarded) is dict and all(type(guarded.get(k)) is int
        and 0<=guarded[k]<=RSS_BYTES for k in ('command_peak_rss_bytes','guard_peak_rss_bytes')),
        'missing/invalid/over-limit measured PID peak RSS')
    require(process.get('peak_rss_bytes')==max(guarded['command_peak_rss_bytes'],guarded['guard_peak_rss_bytes']),
        'reported combined RSS differs from original PID peaks')
    require(type(process.get('returncode')) is int and process['returncode'] == 0
            and process.get('primary_failure') is None and process.get('cleanup_errors') == []
            and type(process.get('wall_seconds')) in (int,float) and math.isfinite(process['wall_seconds'])
            and 0 <= process['wall_seconds'] <= limit and type(process.get('peak_rss_bytes')) is int
            and 0 < process['peak_rss_bytes'] <= RSS_BYTES, 'child/readback exit, complete time or measured RSS failed')



def validate_success(value, manifest, *, supervisor=False):
    """Recompute acceptance predicates; a self-consistent accepted flag is insufficient."""
    require(value.get('schema')==SCHEMA+('-supervisor-result' if supervisor else '-acceptance')
            and value.get('run_id')==RUN_ID and value.get('manifest_identity')==manifest['identity']
            and value.get('protocol_sha256')==manifest['protocol_sha256']
            and value.get('accepted') is True and value.get('status')=='success' and value.get('errors')==[]
            and value.get('formal') is False and value.get('automatic_retry') is False,
            'terminal flags/errors/identity do not establish success')
    require(number(value.get('outer_wall_seconds_through_receipt_preparation'),maximum=OUTER_SECONDS)
            and type(value.get('final_total_bytes_including_acceptance')) is int
            and 0<value['final_total_bytes_including_acceptance']<=MAX_BYTES,
            'outer wall or complete retained byte bound failed')
    for key,limit in (('child_process',CHILD_SECONDS),('readback_process',READBACK_SECONDS),('restoration_process',RESTORE_SECONDS)):
        require(type(value.get(key))is dict,'required completed phase missing')
        _process_ok(value[key],limit)
        require(number(value[key].get('limit_seconds'),minimum=0,maximum=limit)
                and value[key]['limit_seconds']>0 and value[key]['wall_seconds']<=value[key]['limit_seconds'],
                'recorded phase failed its own admitted remaining deadline')
    require(number(value.get('readback_wall_seconds'),maximum=READBACK_SECONDS),'combined readback and restore deadline failed')
    restored=value.get('restoration')
    require(type(restored)is dict and restored.get('valid') is True
            and number(restored.get('simulation_seconds')) and restored['simulation_seconds']==86400
            and type(restored.get('production_scope'))is int and restored['production_scope']==913
            and restored.get('simulation_advancement_performed') is False
            and all(type(restored.get(k))is int and restored[k]==0 for k in ('model_calls','solver_calls')),
            'complete exact restoration missing')
    require(type(value.get('verified_evidence_sha256'))is dict and value['verified_evidence_sha256']
            and value.get('runner_result_sha256')==value['verified_evidence_sha256'].get('run/result.json'),
            'original verified run result anchor missing')
    if not supervisor:
        require(value.get('full_supervisor_exit_verified') is True,'supervisor exit lacks actual original wait')
        _process_ok(value['outer_process'],OUTER_SECONDS)
        require(number(value['outer_process'].get('limit_seconds'),maximum=OUTER_SECONDS)
                and 0<value['outer_process']['limit_seconds']
                and value['outer_process']['wall_seconds']<=value['outer_process']['limit_seconds'],
                'outer supervisor exceeded its admitted remaining deadline')



def _terminal_encoding(result, base_size, elapsed, *, success_validator=None):
    """Prepare exact terminal bytes, refreshing/checking time in every pass.

    Only byte count and failure state must converge, not the changing clock.
    The recorded timestamp precedes the last encoding pass. The deadline is
    checked again after that pass and its success predicates; publication and
    process exit belong to the enclosing guard/host measurement.
    """
    errors=result['errors']
    for _ in range(32):
        wall=elapsed();require(number(wall),'invalid terminal elapsed time')
        result['outer_wall_seconds_through_receipt_preparation']=wall
        if wall>OUTER_SECONDS and not any(e['type']=='OuterTimeLimit' for e in errors):
            errors.append({'type':'OuterTimeLimit','message':'terminal preparation or encoding exceeds original outer cap'})
        result.update(accepted=not errors,status='failed' if errors else 'success')
        result['identity']=digest({k:v for k,v in result.items() if k!='identity'})
        raw=encoded(result);final_size=base_size+len(raw)
        if final_size>MAX_BYTES and not any(e['type']=='TotalBytesLimit' for e in errors):
            errors.append({'type':'TotalBytesLimit','message':'retained run+scratch+campaign exceeds32GiB'})
        stable=(final_size==result['final_total_bytes_including_acceptance']
                and result['accepted']==(not errors))
        if stable and result['accepted'] and success_validator is not None:
            success_validator(result)
        checked_wall=elapsed();require(number(checked_wall),'invalid post-encoding elapsed time')
        if checked_wall>OUTER_SECONDS and not any(e['type']=='OuterTimeLimit' for e in errors):
            errors.append({'type':'OuterTimeLimit','message':'terminal encoding or validation crosses original outer cap'})
            stable=False
        if stable:return raw
        result['final_total_bytes_including_acceptance']=final_size
    raise ValueError('terminal receipt byte accounting did not converge within 32 passes')



def execute(campaign, manifest):
    require(not LAUNCH_BLOCKERS, 'A24 launch blocked: '+'; '.join(LAUNCH_BLOCKERS))
    campaign=Path(campaign).resolve();root=Path(manifest['origin_root']);run=Path(manifest['output_directory'])
    started=time.monotonic();elapsed=lambda:manifest['prepare_wall_seconds']+time.monotonic()-started
    with _serial_lock(root):
        verify_frozen(campaign,manifest,for_execution=True)
        require(not run.exists() and not (campaign/'attempt.json').exists()
                and not (campaign/'outer_process').exists(),'existing original attempt; no retry')
        require(not _active_with_finalizers(root),'active experiment/finalizer')
        require(shutil.disk_usage(root).free>=MIN_FREE_BYTES,'insufficient launch disk margin')
        before=evidence(campaign,run);check_storage(campaign,run)
        remaining=OUTER_SECONDS-elapsed();require(remaining>0,'outer budget already depleted')
        outer=owned_phase(_phase_command(campaign,manifest,'supervise'),cwd=campaign/'frozen',
            output=campaign/'outer_process',timeout=remaining,
            inputs={'manifest':campaign/'manifest.json'},output_paths={'supervisor_result':campaign/'supervisor_result.json'})
        errors=[];supervisor=None;original=phase_anchors(campaign,outer,run)
        try:
            verify_phase(campaign,manifest,outer,command=_phase_command(campaign,manifest,'supervise'),maximum=OUTER_SECONDS)
            expected=outer['guard_evidence']['output_files_sha256']['supervisor_result']
            require(type(expected)is str,'guard did not observe supervisor terminal result')
            supervisor=read_json(campaign/'supervisor_result.json',expected)[0]
            validate_success(supervisor,manifest,supervisor=True)
            original.update(supervisor['first_parsed_phase_proof_sha256'])
            require(supervisor['outer_wall_seconds_through_receipt_preparation']<=elapsed(),'supervisor wall exceeds enclosing measured wall')
        except BaseException as exc:errors.append({'stage':'supervisor','type':type(exc).__name__,'message':str(exc)})
        try:verify_frozen(campaign,manifest,for_execution=True)
        except BaseException as exc:errors.append({'stage':'final_runtime','type':type(exc).__name__,'message':str(exc)})
        final=evidence(campaign,run,include_outer=True)
        try:
            bind_receipts(before,final);bind_receipts(original,final)
            if supervisor is not None:
                bind_first(supervisor['verified_evidence_sha256'],final)
                read_json(campaign/'verification_payload.json',original['campaign/verification_payload.json'])
        except BaseException as exc:errors.append({'stage':'final_original_binding','type':type(exc).__name__,'message':str(exc)})
        result={'schema':SCHEMA+'-acceptance','run_id':RUN_ID,'manifest_identity':manifest['identity'],
            'protocol_sha256':manifest['protocol_sha256'],'evidence_sha256':final,
            'first_parsed_phase_proof_sha256':original,'supervisor_result_sha256':original.get('campaign/supervisor_result.json'),
            'verified_evidence_sha256':None if supervisor is None else supervisor.get('verified_evidence_sha256'),
            'runner_result_sha256':final.get('run/result.json'),'outer_process':outer,
            'child_process':None if supervisor is None else supervisor.get('child_process'),
            'readback_process':None if supervisor is None else supervisor.get('readback_process'),
            'restoration_process':None if supervisor is None else supervisor.get('restoration_process'),
            'restoration':None if supervisor is None else supervisor.get('restoration'),
            'readback_wall_seconds':None if supervisor is None else supervisor.get('readback_wall_seconds'),
            'prepare_wall_seconds':manifest['prepare_wall_seconds'],'errors':errors,'formal':False,
            'automatic_retry':False,'full_supervisor_exit_verified':outer['guard_evidence'] is not None,
            'model_calls_performed':0,
            'outer_wall_seconds_through_receipt_preparation':elapsed(),
            'wall_scope':'prepare plus all guarded supervisor phases, supervisor result publication and exit, guard cleanup/wait/readback and final evidence binding; timestamp resampled before the final encoding pass, deadline checked again after encoding and acceptance predicates; final certificate write/fsync/return measured separately by launching host',
            'final_total_bytes_including_acceptance':0}
        raw=_terminal_encoding(result,total_bytes(campaign,run),elapsed,
                               success_validator=lambda value:validate_success(value,manifest))
        acceptance_sha=write_new(campaign/'acceptance.json',raw,raw=True)
        return {'status':result['status'],'accepted':result['accepted'],
            'acceptance_path':str(campaign/'acceptance.json'),'acceptance_sha256':acceptance_sha,
            'manifest_identity':manifest['identity'],
            'outer_wall_seconds_through_receipt_preparation':result['outer_wall_seconds_through_receipt_preparation'],
            'full_supervisor_exit_verified':result['full_supervisor_exit_verified']}



def _execute_reviewed(campaign, manifest, *, _under_outer_guard=False):
    """Complete supervised terminal flow, pending this integration's validation."""
    require(not LAUNCH_BLOCKERS, 'private execution cannot bypass unresolved launch blockers')
    require(_under_outer_guard is True,'supervisor requires the enclosing common guard and serial lock')
    campaign = Path(campaign).resolve(); root = Path(manifest['origin_root']); run = Path(manifest['output_directory'])
    started = time.monotonic(); elapsed = lambda:manifest['prepare_wall_seconds']+time.monotonic()-started
    # The real outer parent holds the original flock for this entire worker and
    # its final resource/receipt verification. Reacquiring in a new process would
    # deadlock. Owner loss closes the chain and terminates this worker.
    with nullcontext():
        verify_frozen(campaign, manifest, for_execution=True)
        require(not run.exists() and not (campaign/'attempt.json').exists(), 'original attempt exists; no retry')
        require(not _active_with_finalizers(root), 'active experiment/finalizer')
        require(shutil.disk_usage(root).free >= MIN_FREE_BYTES, 'insufficient free disk at launch')
        write_new(campaign/'attempt.json', {'manifest_identity':manifest['identity'],'supervisor_pid':os.getpid(),
            'child_command':_phase_command(campaign,manifest,'run'),'outer_limit':OUTER_SECONDS,'automatic_retry':False})
        original_campaign = evidence(campaign,run); errors=[]; proof=None; child=None; restored=None; parsed_proofs={};verification_process=None;restoration_process=None;readback_wall=None
        try:
            check_storage(campaign,run)
            child=owned_phase(_phase_command(campaign,manifest,'run'),cwd=campaign/'frozen',output=campaign/'child_process',
                              timeout=min(CHILD_SECONDS,max(.001,OUTER_SECONDS-elapsed())),
                              inputs={'manifest':campaign/'manifest.json'},output_paths={'result':run/'result.json'})
            parsed_proofs.update(phase_anchors(campaign,child,run))
            verify_phase(campaign,manifest,child,command=_phase_command(campaign,manifest,'run'),maximum=CHILD_SECONDS)
            check_storage(campaign,run)
            verify_frozen(campaign,manifest,for_execution=True)
            first=evidence(campaign,run);require(all(first.get(k)==v for k,v in original_campaign.items()),'original campaign changed')
            first_sha=write_new(campaign/'first_verification_anchors.json',first)
            parsed_proofs['campaign/first_verification_anchors.json']=first_sha
            validation_started=time.monotonic()
            remaining=min(READBACK_SECONDS,OUTER_SECONDS-elapsed());require(remaining>0,'no remaining readback budget')
            process=owned_phase(_phase_command(campaign,manifest,'verify',campaign/'first_verification_anchors.json',first_sha=first_sha),
                cwd=campaign/'frozen',output=campaign/'readback_process',timeout=remaining,
                inputs={'manifest':campaign/'manifest.json','first':campaign/'first_verification_anchors.json'},
                output_paths={'verification':campaign/'verification_payload.json'})
            verification_process=process;parsed_proofs.update(phase_anchors(campaign,process,run));check_storage(campaign,run)
            _process_ok(process,remaining);proof,proof_receipt=read_json(campaign/'verification_payload.json')
            require(proof_receipt['sha256']==process['guard_evidence']['output_files_sha256']['verification'],'readback payload differs from original guarded bytes')
            parsed_proofs['campaign/verification_payload.json']=proof_receipt['sha256']
            require(proof.get('valid') is True and proof['verified_evidence_sha256']==first,'readback changed first anchors')
            _check_audit_binding({k:first[k] for k in AUDIT_EVIDENCE_KEYS},first)
            remain=min(RESTORE_SECONDS,READBACK_SECONDS-(time.monotonic()-validation_started),OUTER_SECONDS-elapsed())
            require(remain>0,'readback/outer budget depleted before exact restore')
            process=owned_phase(_phase_command(campaign,manifest,'restore',campaign/'first_verification_anchors.json',campaign/'verification_payload.json',
                first_sha=first_sha,proof_sha=proof_receipt['sha256']),
                cwd=campaign/'frozen',output=campaign/'restoration_process',timeout=remain,
                inputs={'manifest':campaign/'manifest.json','first':campaign/'first_verification_anchors.json','proof':campaign/'verification_payload.json'},
                output_paths={'restoration':campaign/'restoration_payload.json'})
            restoration_process=process;parsed_proofs.update(phase_anchors(campaign,process,run));check_storage(campaign,run)
            _process_ok(process,remain);restored,restored_receipt=read_json(campaign/'restoration_payload.json')
            require(restored_receipt['sha256']==process['guard_evidence']['output_files_sha256']['restoration'],'restoration payload differs from original guarded bytes')
            parsed_proofs['campaign/restoration_payload.json']=restored_receipt['sha256']
            validate_restoration(restored,proof,campaign)
            require(proof['result_wall_seconds']<=child['wall_seconds'],'child tail time missing')
            readback_wall=time.monotonic()-validation_started
            require(readback_wall<=READBACK_SECONDS,'combined readback/restore elapsed cap')
        except BaseException as exc:errors.append({'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()})
        try:verify_frozen(campaign,manifest,for_execution=True)
        except BaseException as exc:errors.append({'stage':'post_freeze','type':type(exc).__name__,'message':str(exc)})
        final=evidence(campaign,run)
        try:
            require(all(final.get(k)==v for k,v in original_campaign.items()),'final campaign replaced original anchors')
            bind_receipts(parsed_proofs,final)
            if proof is not None:
                bind_first(proof['verified_evidence_sha256'],final)
        except BaseException as exc:errors.append({'stage':'final_binding','type':type(exc).__name__,'message':str(exc)})
        wall=elapsed()
        if wall>OUTER_SECONDS:errors.append({'type':'OuterTimeLimit','message':'all gate phases exceed original outer cap'})
        result={'schema':SCHEMA+'-supervisor-result','run_id':RUN_ID,'manifest_identity':manifest['identity'],
            'protocol_sha256':manifest['protocol_sha256'],'evidence_sha256':final,
            'first_parsed_phase_proof_sha256':parsed_proofs,
            'verified_evidence_sha256':None if proof is None else proof['verified_evidence_sha256'],
            'runner_result_sha256':final.get('run/result.json'),'outer_wall_seconds_through_receipt_preparation':wall,
            'full_supervisor_exit_requires_external_guard':True,'prepare_wall_seconds':manifest['prepare_wall_seconds'],
            'child_process':child,'readback_process':verification_process,'restoration_process':restoration_process,
            'readback_wall_seconds':readback_wall,
            'restoration':restored,'errors':errors,'final_total_bytes_including_acceptance':0,
            'formal':False,'model_calls_performed':0,'automatic_retry':False}
        result['wall_scope']='timestamp resampled before final terminal encoding pass, deadline checked again afterward; publication and exit measured by enclosing guard'
        raw=_terminal_encoding(result,total_bytes(campaign,run),elapsed)
        write_new(campaign/'supervisor_result.json',raw,raw=True)
        return result



def read_acceptance(*,root=ROOT):
    """Read original terminal evidence and recompute its resource predicates.

    This does not rerun physical/attribution algorithms or start/resume calls.
    This is storage readback only; a future host must close its own complete cost.
    """
    try:
        root=Path(root).resolve();campaign=root/AREA/RUN_ID
        manifest=read_json(campaign/'manifest.json')[0];verify_frozen(campaign,manifest)
        acceptance,receipt=read_json(campaign/'acceptance.json')
        require(acceptance.get('identity')==digest({k:v for k,v in acceptance.items() if k!='identity'})
                and acceptance.get('manifest_identity')==manifest['identity'],'saved acceptance identity differs')
        run=Path(manifest['output_directory']);actual=evidence(campaign,run,include_outer=True)
        require(actual==acceptance['evidence_sha256'] and total_bytes(campaign,run)==acceptance['final_total_bytes_including_acceptance'],'saved complete evidence changed')
        bind_receipts(acceptance['first_parsed_phase_proof_sha256'],actual)
        if acceptance.get('accepted') is True:
            require(not LAUNCH_BLOCKERS,'success cannot be certified by an unresolved gate draft')
            validate_success(acceptance,manifest)
            bind_first(acceptance['verified_evidence_sha256'],actual)
            proof=read_json(campaign/'verification_payload.json',actual['campaign/verification_payload.json'])[0]
            supervisor=read_json(campaign/'supervisor_result.json',acceptance['supervisor_result_sha256'])[0]
            require(supervisor['identity']==digest({k:v for k,v in supervisor.items() if k!='identity'}),'supervisor identity differs')
            validate_success(supervisor,manifest,supervisor=True)
            require(same(proof['verified_evidence_sha256'],supervisor['verified_evidence_sha256'])
                    and same(supervisor['verified_evidence_sha256'],acceptance['verified_evidence_sha256'])
                    and proof.get('valid') is True,'original verification proof differs')
            for key in ('child_process','readback_process','restoration_process','restoration','readback_wall_seconds'):
                require(same(acceptance[key],supervisor[key]),'outer receipt changed supervisor phase fact')
            first_sha=acceptance['first_parsed_phase_proof_sha256']['campaign/first_verification_anchors.json']
            proof_sha=acceptance['first_parsed_phase_proof_sha256']['campaign/verification_payload.json']
            commands={
                'outer_process':_phase_command(campaign,manifest,'supervise'),
                'child_process':_phase_command(campaign,manifest,'run'),
                'readback_process':_phase_command(campaign,manifest,'verify',campaign/'first_verification_anchors.json',first_sha=first_sha),
                'restoration_process':_phase_command(campaign,manifest,'restore',campaign/'first_verification_anchors.json',campaign/'verification_payload.json',first_sha=first_sha,proof_sha=proof_sha)}
            for key,limit in (('outer_process',OUTER_SECONDS),('child_process',CHILD_SECONDS),('readback_process',READBACK_SECONDS),('restoration_process',RESTORE_SECONDS)):
                anchors=verify_phase(campaign,manifest,acceptance[key],command=commands[key],maximum=limit)
                bind_receipts(anchors,actual)
            restored=read_json(campaign/'restoration_payload.json',actual['campaign/restoration_payload.json'])[0]
            require(same(restored,acceptance['restoration']), 'restored proof changed')
            validate_restoration(restored,proof,campaign)
        else:
            require(acceptance.get('accepted') is False and acceptance.get('status')=='failed'
                    and type(acceptance.get('errors'))is list and acceptance['errors'],'failed receipt has inconsistent flags/errors')
        require(evidence(campaign,run,include_outer=True)==actual,'late raw file replacement during readback')
        read_file(campaign/'acceptance.json',expected_sha256=receipt['sha256'])
        require(total_bytes(campaign,run)==acceptance['final_total_bytes_including_acceptance'],'late byte count differs')
        return {'valid':True,'accepted':acceptance.get('accepted') is True,'acceptance_sha256':receipt['sha256'],
                'status':acceptance['status'],'semantic_audits_rerun':False,'errors':[]}
    except Exception as exc:
        return {'valid':False,'accepted':False,'status':'unverified','errors':[str(exc)]}



def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare',action='store_true');parser.add_argument('--execute',action='store_true')
    parser.add_argument('--read-acceptance',action='store_true')
    args=parser.parse_args();require(sum((args.prepare,args.execute,args.read_acceptance))<=1,'choose one operation')
    if args.read_acceptance:result=read_acceptance()
    elif args.execute:
        require(not LAUNCH_BLOCKERS,'A24 launch blocked: '+'; '.join(LAUNCH_BLOCKERS))
        campaign=ROOT/AREA/RUN_ID;result=execute(campaign,read_json(campaign/'manifest.json')[0])
    elif args.prepare:
        campaign,manifest=prepare();result={'status':'prepared_blocked' if LAUNCH_BLOCKERS else 'prepared','campaign':str(campaign),'identity':manifest['identity'],'launch_blockers':list(LAUNCH_BLOCKERS)}
    else:result={'status':'static_plan_only','run_id':RUN_ID,'parameters':EXPECTED,'launch_blockers':list(LAUNCH_BLOCKERS),'actual_execution_performed':False}
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result.get('accepted') is True or result['status'] in ('static_plan_only','prepared_blocked','prepared') else 1



if __name__=='__main__':raise SystemExit(main())
