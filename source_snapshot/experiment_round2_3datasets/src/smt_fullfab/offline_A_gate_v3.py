"""One frozen A8 capacity development gate v3 (stream audit/snapshot writer). Default prepare; --execute is explicit.

This supervisor imports no environment, optimizer or model transport. Its child
uses the frozen A/hybrid runner. An interrupted attempt is evidence, never an
authorization to repeat work or reset accumulated resources.
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
import stat
import subprocess
import sys
import time

from .offline_pilot import (
    DATA, VENDOR, ROOT, _sha, _digest, _read, _write, _runtime,
    _origin_git, _git_pointer, _active_claims, _serial_lock, _launch,
)

RUN_ID = 'A_1701_8h_hybrid_v3'
PROTOCOL = 'configs/smt_fullfab/A_hybrid_8h_v3.protocol.json'
AREA = 'runs/smt_fullfab_offline_A_gate'
SCHEMA = 'smt-fullfab-offline-A-gate-frozen-v3'
ACCEPTANCE_SCHEMA = 'smt-fullfab-offline-A-gate-acceptance-v3'
OUTER_SECONDS = 6000
BUNDLE_READBACK_SECONDS = 180
MIN_FREE_BYTES = 40 * 1024**3
TRACE_BYTES = 2 * 1024**3
PEAK_RSS_BYTES = 8 * 1024**3
AUDIT_DEPENDENCIES = frozenset(('src/smt_fullfab/stream_physical_binding.py',
    'src/smt_fullfab/stream_physical_core.py','src/smt_fullfab/stream_physical_projection.py',
    'src/smt_fullfab/trace_source.py','src/smt/source_check.py','src/smt_fullfab/stream_metrics.py',
    'src/smt_fullfab/metrics.py','src/smt_fullfab/stream_source_audit.py',
    'src/smt_fullfab/stream_opportunity_audit.py'))
AUDIT_EVIDENCE_KEYS = frozenset(('run/trace.jsonl','run/audit_bundle/audit_bundle.json',
    'run/audit_bundle/source.json','run/audit_bundle/opportunity.json','run/audit_bundle/physical.json',
    'run/audit_bundle/metrics.json','run/audit_bundle/projection/projection.json',
    'run/audit_bundle/projection/physical.jsonl'))
EXPECTED = dict(arm='A', run_id=RUN_ID, seconds=28800, seed=1701,
                wall_seconds=5400.0, max_plans=1200, plan_seconds=14400,
                period_seconds=1800, lookahead_depth=2, solver_seconds=2.0,
                solver_budget_seconds=32.0, max_slots=4, snapshot_path=None,
                solver_method='hybrid', max_log_bytes=16 * 1024**3,
                constructor_seconds=5.0, max_candidate_evaluations=250000,
                max_trace_bytes=TRACE_BYTES, audit_mode='stream', snapshot_mode='stream')


def _config(protocol):
    if (protocol.get('schema') != 'smt-fullfab-A-hybrid-8h-development-protocol-v3'
            or protocol.get('formal') is not False or type(protocol.get('model_calls_authorized')) is not int
            or protocol.get('model_calls_authorized') != 0
            or protocol.get('execute_now') is not False):
        raise ValueError('only the preregistered zero-model A development gate is supported')
    config = protocol.get('run_config')
    if (config != EXPECTED or any(type(config[k]) is not type(v) for k, v in EXPECTED.items())):
        raise ValueError('A gate parameters differ from the single approved protocol')
    constraints = protocol.get('execution_constraints', {})
    limits = protocol.get('budget_semantics', {})
    if any(constraints.get(k) != v or type(constraints.get(k)) is not type(v) for k, v in dict(serial_only=True, solver_workers=1,
            solver_seed=11, event_total_slots_per_machine=8, external_watchdog_seconds=OUTER_SECONDS,
            minimum_free_disk_bytes=MIN_FREE_BYTES, maximum_child_peak_rss_bytes=PEAK_RSS_BYTES,
            bundle_readback_timeout_seconds=BUNDLE_READBACK_SECONDS,
            rss_is_hard_guard=False).items()) or type(limits.get('fixed_trace_cap_bytes')) is not int or limits.get('fixed_trace_cap_bytes') != TRACE_BYTES:
        raise ValueError('A gate external/physical resource limits differ')
    argv = protocol.get('argv', [])
    if argv[:3] != ['.venv/bin/python', '-m', 'src.smt_fullfab.runner'] or len(argv[3:]) % 2:
        raise ValueError('unexpected protocol command')
    pairs = list(zip(argv[3::2], argv[4::2]))
    actual = dict(pairs)
    wanted = {'--' + k.replace('_', '-'): str(int(v)) if type(v) is float and v.is_integer() else str(v)
              for k, v in EXPECTED.items() if v is not None}
    if len(actual) != len(pairs) or actual != wanted:
        raise ValueError('protocol argv and explicit configuration differ')
    return dict(config)


def _input_paths(root):
    paths = []
    for relative in ('src', VENDOR, DATA):
        base = root / relative
        if not base.is_dir():raise ValueError('missing frozen directory: ' + relative)
        for path in sorted(base.rglob('*')):
            if '__pycache__' in path.parts or path.suffix in ('.pyc', '.pyo'):continue
            if path.is_symlink():raise ValueError('input symlink: ' + str(path))
            if path.is_file():paths.append(path)
    paths += sorted(root.glob('requirements*')) + [root / PROTOCOL]
    if root / 'requirements.lock' not in paths:raise ValueError('requirements.lock required')
    for path in paths:
        if not path.is_file() or path.is_symlink():raise ValueError('nonregular frozen input')
    return sorted(set(paths))


def _inventory(root):
    return {str(p.relative_to(root)): _sha(p) for p in _input_paths(root)}


def prepare(*, root=ROOT):
    root = Path(root).resolve()
    campaign = root / AREA / RUN_ID
    if campaign.exists():
        manifest = _read(campaign / 'manifest.json')
        verify_frozen(campaign, manifest, for_execution=False)
        if _sha(root / PROTOCOL) != manifest['protocol_sha256']:
            raise ValueError('live protocol changed after preparation')
        return campaign, manifest
    config = _config(_read(root / PROTOCOL))
    target = root / 'runs/smt_fullfab_development' / RUN_ID
    if target.exists():raise FileExistsError('existing target cannot be adopted or restarted')
    inputs, runtime, head = _inventory(root), _runtime(), _origin_git(root)
    campaign.mkdir(parents=True, exist_ok=False)
    frozen = campaign / 'frozen'
    frozen.mkdir()
    try:
        for relative, expected in inputs.items():
            data = (root / relative).read_bytes()
            if hashlib.sha256(data).hexdigest() != expected:raise ValueError('input changed during freeze: ' + relative)
            path = frozen / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(0o444)
        if inputs != _inventory(root):raise ValueError('inventory changed during freeze')
        if runtime != _runtime():raise ValueError('runtime changed during freeze')
        (root / 'runs').mkdir(exist_ok=True)
        (frozen / 'runs').symlink_to(root / 'runs', target_is_directory=True)
        _git_pointer(frozen, head)
        manifest = dict(schema=SCHEMA, run_id=RUN_ID, origin_root=str(root),
            created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            origin_git_head=head, git_identity_note='origin pointer only, not a clean checkout; file hashes include dirty source',
            frozen_input_sha256=inputs, protocol_sha256=inputs[PROTOCOL], runtime=runtime, launcher_executable=sys.executable,
            config=config, child_command=_command(campaign, config), output_directory=str(target), model_calls_permitted=0,
            cp_requested_seconds_permitted=32, outer_wall_seconds=OUTER_SECONDS,
            minimum_free_disk_bytes=MIN_FREE_BYTES, fixed_trace_cap_bytes=TRACE_BYTES,
            maximum_child_peak_rss_bytes=PEAK_RSS_BYTES, rss_is_hard_guard=False,
            bundle_readback_timeout_seconds=BUNDLE_READBACK_SECONDS)
        manifest['identity'] = _digest(manifest)
        _write(campaign / 'manifest.json', manifest)
        verify_frozen(campaign, manifest)
        return campaign, manifest
    except Exception as exc:
        _write(campaign / 'freeze_failure.json', dict(status='failed', error=str(exc)))
        raise


def verify_frozen(campaign, manifest, *, for_execution=True):
    campaign = Path(campaign).resolve()
    root = Path(manifest['origin_root'])
    if (manifest.get('schema') != SCHEMA or manifest.get('identity') != _digest({k: v for k, v in manifest.items() if k != 'identity'})
            or campaign != root / AREA / RUN_ID or manifest.get('run_id') != RUN_ID
            or manifest.get('output_directory') != str(root / 'runs/smt_fullfab_development' / RUN_ID)):
        raise ValueError('invalid fixed A gate manifest identity/path')
    frozen = campaign / 'frozen'
    inputs = _inventory(frozen)
    if inputs != manifest['frozen_input_sha256']:raise ValueError('frozen source/data changed')
    if any((frozen / p).stat().st_mode & 0o222 for p in inputs):raise ValueError('frozen input is writable')
    if (_config(_read(frozen / PROTOCOL)) != manifest['config'] or inputs[PROTOCOL] != manifest['protocol_sha256']
            or manifest.get('model_calls_permitted') != 0 or manifest.get('cp_requested_seconds_permitted') != 32
            or manifest.get('outer_wall_seconds') != OUTER_SECONDS or manifest.get('minimum_free_disk_bytes') != MIN_FREE_BYTES
            or manifest.get('fixed_trace_cap_bytes') != TRACE_BYTES
            or manifest.get('maximum_child_peak_rss_bytes') != PEAK_RSS_BYTES
            or manifest.get('bundle_readback_timeout_seconds') != BUNDLE_READBACK_SECONDS
            or manifest.get('rss_is_hard_guard') is not False):
        raise ValueError('frozen protocol/bounds changed')
    if for_execution and (_runtime() != manifest['runtime'] or sys.executable != manifest.get('launcher_executable')):
        raise ValueError('runtime differs from freeze')
    if for_execution and manifest.get('child_command') != _command(campaign, manifest['config']):
        raise ValueError('frozen child invocation differs')
    if _origin_git(frozen) != manifest['origin_git_head']:raise ValueError('origin pointer changed')
    if not (frozen / 'runs').is_symlink() or (frozen / 'runs').resolve() != root / 'runs':
        raise ValueError('frozen output mapping changed')
    if for_execution:
        for name, path in [('src/smt_fullfab/offline_A_gate_v3.py', Path(__file__)),
                           ('src/smt_fullfab/offline_pilot.py', Path(__file__).with_name('offline_pilot.py'))]:
            if inputs.get(name) != _sha(path):raise ValueError('use the frozen supervisor/helper; live code differs')


def _command(campaign, config, *, executable=None):
    if config != EXPECTED:raise ValueError('A child config differs')
    # Persist the real child PID before importing the frozen runner. The shared
    # watchdog helper returns the same PID/exit code after wait/kill completes.
    bootstrap = """import sys,os,json,runpy,datetime,resource
frozen=sys.argv.pop(1);pidfile=sys.argv.pop(1);usagefile=sys.argv.pop(1)
sys.path.insert(0,frozen)
with open(pidfile,'x') as f:
    json.dump({'pid':os.getpid(),'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()},f)
    f.write('\\n');f.flush();os.fsync(f.fileno())
try:
    runpy.run_module('src.smt_fullfab.runner',run_name='__main__')
finally:
    raw=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    unit='bytes' if sys.platform=='darwin' else 'KiB' if sys.platform.startswith('linux') else 'unsupported'
    value={'schema':'smt-child-peak-rss-v1','pid':os.getpid(),'platform':sys.platform,
           'source':'resource.getrusage(RUSAGE_SELF).ru_maxrss','raw_maxrss':raw,'raw_unit':unit,
           'peak_rss_bytes':raw*(1024 if unit=='KiB' else 1) if unit!='unsupported' else None,
           'hard_memory_guard':False}
    with open(usagefile,'x') as f:
        json.dump(value,f);f.write('\\n');f.flush();os.fsync(f.fileno())
"""
    command = [executable or sys.executable, '-I', '-B', '-c', bootstrap, str(campaign / 'frozen'),
               str(campaign / 'child_started.json'), str(campaign / 'child_usage.json')]
    for key, value in config.items():
        if value is not None:command += ['--' + key.replace('_', '-'), str(value)]
    return command


def _active_with_finalizers(root):
    """The shared guard plus still-live result writers/audit finalizers.

    A result can precede outer audit/acceptance. Its existence is not proof that
    the process has ended. Ambiguous/reused live PIDs conservatively block.
    """
    active = _active_claims(root)
    known = {r['claim'] for r in active}
    for area in ('smt_fullfab_development', 'smt_fullfab_stage2'):
        for claim in (root / 'runs' / area).glob('*/claim.json'):
            if str(claim) in known or not claim.with_name('result.json').exists():continue
            try:
                pid = _read(claim)['pid']
                if type(pid) is not int or pid <= 0:raise ValueError('invalid claim PID')
                os.kill(pid, 0)
            except ProcessLookupError:continue
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                active.append(dict(claim=str(claim), reason='finished result has an ambiguous process claim'))
            else:active.append(dict(claim=str(claim), pid=pid, reason='result exists but process/finalizer is still alive'))
    return active


def _files(base, *, campaign=False):
    if not base.exists():return []
    found = []
    for path in sorted(base.rglob('*')):
        if path.is_symlink():
            if campaign and path == base / 'frozen/runs':continue
            raise ValueError('unexpected evidence symlink: ' + str(path))
        if path.is_file():found.append(path)
    return found


def _evidence(campaign, run):
    return {prefix + '/' + str(path.relative_to(base)): _sha(path)
            for prefix, base in [('campaign', campaign), ('run', run)]
            for path in _files(base, campaign=prefix == 'campaign') if path != campaign / 'acceptance.json'}


def _bytes(campaign, run):
    return sum(p.stat().st_size for p in _files(campaign, campaign=True) + _files(run))


def _unique_object(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise ValueError('duplicate saved JSON key: '+key)
        value[key]=item
    return value


def _read_unique(path):
    # Deliberate 8h gate limitation: source report is fully parsed in memory.
    # No regex/header shortcut may mistake nested/duplicate fields for top-level.
    with Path(path).open() as stream:return json.load(stream,object_pairs_hook=_unique_object)


def _read_bound_json(path, expected_sha):
    """Parse exactly the bytes named by read_bundle, with an identity fence."""
    path=Path(path)
    def identity(value):
        return (value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
    before=path.lstat()
    if not stat.S_ISREG(before.st_mode):raise ValueError('saved JSON is not a regular file')
    with path.open('rb') as stream:
        if identity(os.fstat(stream.fileno()))!=identity(before):raise ValueError('saved JSON replaced')
        raw=stream.read()
        if identity(os.fstat(stream.fileno()))!=identity(before):raise ValueError('saved JSON changed')
    if identity(path.lstat())!=identity(before) or hashlib.sha256(raw).hexdigest()!=expected_sha:
        raise ValueError('saved JSON identity/hash differs')
    return json.loads(raw,object_pairs_hook=_unique_object)


def _trace_size(run):
    return (run/'trace.jsonl').stat().st_size


def _bundle_storage_readback(run, manifest, expected_sha):
    frozen=Path(manifest['origin_root'])/AREA/RUN_ID/'frozen'
    code=("import sys,json;sys.path.insert(0,sys.argv[1]);"
          "from src.smt_fullfab.stream_audit_bundle import read_bundle;"
          "print(json.dumps(read_bundle(sys.argv[2],expected_manifest_sha256=sys.argv[3])))")
    outcome=subprocess.run([sys.executable,'-I','-B','-c',code,str(frozen),str(run/'audit_bundle'),expected_sha],
        cwd=frozen,capture_output=True,text=True,timeout=BUNDLE_READBACK_SECONDS)
    if outcome.returncode:raise ValueError('frozen bundle storage readback failed: '+outcome.stderr)
    return json.loads(outcome.stdout,object_pairs_hook=_unique_object)


def _validate_peak_rss(campaign, child):
    usage=_read_unique(campaign/'child_usage.json')
    platform=usage.get('platform');raw=usage.get('raw_maxrss')
    unit='bytes' if platform=='darwin' else 'KiB' if isinstance(platform,str) and platform.startswith('linux') else None
    if (usage.get('schema')!='smt-child-peak-rss-v1' or usage.get('pid')!=child.get('pid')
            or type(usage.get('pid')) is not int or usage['pid']<=0
            or usage.get('source')!='resource.getrusage(RUSAGE_SELF).ru_maxrss'
            or unit is None or usage.get('raw_unit')!=unit or type(raw) is not int or raw<=0
            or usage.get('hard_memory_guard') is not False):
        raise ValueError('missing/invalid child peak RSS evidence')
    measured=raw*(1024 if unit=='KiB' else 1)
    if type(usage.get('peak_rss_bytes')) is not int or usage['peak_rss_bytes']!=measured or measured>PEAK_RSS_BYTES:
        raise ValueError('child measured peak RSS exceeds8GiB or normalization differs')
    return usage


def _validate_run(run, manifest):
    """Inspect saved evidence only; physical audit was run inside the child."""
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
    rows = [json.loads(line) for line in (run / 'resources.jsonl').read_text().splitlines() if line.strip()]
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
    periodic = 0
    for reserve, finish in zip(reserves, finishes):
        mode = reserve.get('planner_mode')
        if (mode not in ('periodic_cp', 'event_classical') or finish.get('planner_mode') != mode
                or reserve.get('requested_seconds') != (2 if mode == 'periodic_cp' else 0)):
            raise ValueError('unexpected planner mode/CP allocation')
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
            or checkpoint.get('solver_budget_seconds') != 32 or checkpoint.get('scenario_seed') != 1701
            or checkpoint.get('model_calls') != 0 or checkpoint.get('log_bytes_in_earlier_runs') != 0
            or checkpoint.get('hybrid_resource_limits') != dict(runner_wall_seconds=5400.0, max_plans=1200, max_log_bytes=16 * 1024**3,
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
            or envelope.get('terminal_at_eof') is not True or envelope.get('last_time')!=28800 or envelope.get('horizon')!=28800
            or envelope.get('receipt')!=receipt or envelope.get('first_time')!=0
            or audit.get('configuration')!={'window_start':0,'priority_weights':None,'require_terminal':True,'verify_data_dir_supplied':True}):
        raise ValueError('bundle source/terminal/dependency/manifest binding differs')
    source_evidence=source.get('_source_evidence',{})
    if source_evidence.get('complete_jsonl_pass') is not True or source_evidence.get('source_receipt')!=receipt:
        raise ValueError('complete source report receipt differs')
    if not (result.get('status') == 'success' and result.get('audit_valid') is True
            and result.get('full_window_completed') is True and result.get('simulation_seconds') == 28800
            and all(summary.get(k) is True for k in ('valid','source_valid','opportunity_valid','physical_valid',
                'actual_dispatch_provenance_complete',
                'complete_physical_window_certified','absence_of_unreported_legal_demand_certified','verified_input_hashes'))
            and source.get('valid') is True and source.get('errors') == []
            and summary.get('source_errors') == summary.get('opportunity_errors') == []
            and type(source.get('production_machine_count')) is int and type(source.get('declared_control_machine_count')) is int
            and source.get('production_machine_count') == source.get('declared_control_machine_count') == 913
            and source.get('declared_full_factory_domain') is True and result.get('metrics') == summary.get('metrics')
            and periodic == 16):
        raise ValueError('full-window physical/source/opportunity evidence does not pass')
    metrics=summary.get('metrics')
    if (type(metrics) is not dict or set(metrics)!={'window_start','window_end','weighted_tardy_lot_hours',
            'throughput_lots','terminal_wip_lots','terminal_tardy_wip_lots'}
            or metrics['window_start']!=0 or metrics['window_end']!=28800
            or any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in metrics.values())):
        raise ValueError('primary metric summary differs from six-field contract')
    if (len(reserves) > 1200 or requested > 32 or (run / 'trace.jsonl').stat().st_size > TRACE_BYTES
            or type(result.get('wall_seconds')) not in (int, float) or not 0 <= result['wall_seconds'] <= 5400):
        raise ValueError('final runner resource limit exceeded')
    # Carry the originally checked hashes across final evidence collection.
    # Never re-read a changed manifest to manufacture replacement expectations.
    verified = {'run/audit_bundle/audit_bundle.json':reference['manifest_sha256'],
                'run/trace.jsonl':receipt['sha256']}
    verified.update({'run/audit_bundle/'+name:metadata['sha256'] for name,metadata in audit['members'].items()})
    return result, totals, verified


def _check_audit_binding(verified, evidence):
    if type(verified) is not dict or set(verified)!=AUDIT_EVIDENCE_KEYS:
        raise ValueError('final audit evidence binding is incomplete')
    mismatches=[key for key in sorted(verified) if evidence.get(key)!=verified[key]]
    if mismatches:raise ValueError('final audit evidence differs from verified hashes: '+', '.join(mismatches))


def _replay(campaign, manifest):
    acceptance = _read(campaign / 'acceptance.json')
    run = Path(manifest['output_directory'])
    if (acceptance.get('schema') != ACCEPTANCE_SCHEMA or acceptance.get('manifest_identity') != manifest['identity']
            or acceptance.get('protocol_sha256') != manifest['protocol_sha256'] or acceptance.get('run_id') != RUN_ID
            or acceptance.get('identity') != _digest({k: v for k, v in acceptance.items() if k != 'identity'})):
        raise ValueError('acceptance identity differs')
    if _evidence(campaign, run) != acceptance.get('evidence_sha256'):raise ValueError('saved acceptance evidence changed')
    if _bytes(campaign, run) != acceptance.get('final_total_bytes_including_acceptance'):
        raise ValueError('final evidence bytes differ')
    if acceptance.get('accepted') is True:
        result, _, verified = _validate_run(run, manifest)
        process = _read(campaign / 'process_outcome.json')
        usage = _validate_peak_rss(campaign,process)
        child = _read(campaign / 'child_started.json')
        attempt = _read(campaign / 'attempt.json')
        if (process.get('returncode') != 0 or process.get('timed_out') is not False
                or type(process.get('pid')) is not int or process['pid'] <= 0 or child.get('pid') != process['pid']
                or attempt.get('manifest_identity') != manifest['identity'] or attempt.get('config') != manifest['config']
                or attempt.get('command') != manifest.get('child_command')
                or acceptance.get('runner_result_sha256') != _sha(run / 'result.json')
                or acceptance.get('child_peak_rss_bytes') != usage['peak_rss_bytes']
                or result['wall_seconds'] > process.get('wall_seconds', -1)
                or not 0 <= process.get('wall_seconds', -1) <= min(5400, acceptance.get('outer_wall_seconds', -1))
                or not 0 <= acceptance.get('outer_wall_seconds', -1) <= OUTER_SECONDS
                or acceptance['final_total_bytes_including_acceptance'] > EXPECTED['max_log_bytes']):
            raise ValueError('successful acceptance lacks valid process/final resource evidence')
        # Initial evidence was collected before readback. Repeat at the return
        # boundary so replacement during that readback cannot inherit its pass.
        final_evidence = _evidence(campaign,run)
        _check_audit_binding(verified,final_evidence)
        if (acceptance.get('verified_audit_evidence_sha256')!=verified
                or final_evidence!=acceptance.get('evidence_sha256')):
            raise ValueError('saved acceptance evidence changed during replay')
    return acceptance


def read_acceptance(*, root=ROOT):
    """Pure read-only status gate for the fixed registered A run, fail closed."""
    root = Path(root).resolve()
    try:
        _config(_read(root / PROTOCOL))
        campaign = root / AREA / RUN_ID
        manifest = _read(campaign / 'manifest.json')
        if _sha(root / PROTOCOL) != manifest['protocol_sha256']:raise ValueError('registered protocol changed')
        verify_frozen(campaign, manifest, for_execution=False)
        acceptance = _replay(campaign, manifest)
        return dict(valid=True, accepted=acceptance.get('accepted') is True, status=acceptance['status'],
                    errors=[], acceptance=acceptance, result_sha256=acceptance.get('runner_result_sha256'))
    except Exception as exc:
        return dict(valid=False, accepted=False, status='unverified', errors=[f'{type(exc).__name__}: {exc}'])


def execute(campaign, manifest):
    started = time.monotonic()
    campaign = Path(campaign).resolve()
    root, run = Path(manifest['origin_root']), Path(manifest['output_directory'])
    with _serial_lock(root):
        if (campaign / 'acceptance.json').exists():
            verify_frozen(campaign, manifest, for_execution=False)
            return _replay(campaign, manifest)
        verify_frozen(campaign, manifest)
        if run.exists() or (campaign / 'attempt.json').exists():
            raise FileExistsError('existing/interrupted target or attempt preserved; no automatic restart/finalization')
        active = _active_with_finalizers(root)
        if active:return dict(status='blocked_active_runs', accepted=False, active_claims=active)
        free = shutil.disk_usage(root).free
        if free < MIN_FREE_BYTES:return dict(status='blocked_disk_capacity', accepted=False, available_bytes=free, required_bytes=MIN_FREE_BYTES)
        command = manifest['child_command']
        _write(campaign / 'attempt.json', dict(manifest_identity=manifest['identity'], run_id=RUN_ID,
            supervisor_pid=os.getpid(), started_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            config=manifest['config'], command=command, outer_wall_limit=OUTER_SECONDS, available_disk_bytes=free))
        errors, result, usage, verified = [], None, None, None
        try:
            child = _launch(command, campaign / 'frozen', campaign, max(.001, OUTER_SECONDS - (time.monotonic() - started)))
            _write(campaign / 'process_outcome.json', child)
            if child['timed_out']:raise TimeoutError('watchdog terminated child; preserve partial artifacts without invented checkpoint')
            if child['returncode'] != 0:raise ValueError('runner process returned nonzero')
            if (type(child.get('pid')) is not int or child['pid'] <= 0
                    or type(child.get('wall_seconds')) not in (int, float)
                    or not math.isfinite(child['wall_seconds']) or not 0 <= child['wall_seconds'] <= 5400):
                raise ValueError('invalid child PID or measured wall')
            actual_pid = _read(campaign / 'child_started.json')['pid']
            if actual_pid != child['pid']:raise ValueError('actual child PID differs')
            usage = _validate_peak_rss(campaign,child)
            verify_frozen(campaign, manifest)
            result, totals, verified = _validate_run(run, manifest)
            if result['wall_seconds'] > child['wall_seconds']:raise ValueError('runner wall exceeds complete child measurement')
            verification = dict(valid=True, runner_result_sha256=_sha(run / 'result.json'), resource_totals=totals,
                child_peak_rss=usage, rss_is_hard_guard=False,
                verified_audit_evidence_sha256=verified,
                scope='saved run checks before final acceptance evidence binding')
        except Exception as exc:
            errors.append(f'{type(exc).__name__}: {exc}')
            verification = dict(valid=False, errors=list(errors), runner_result_present=(run / 'result.json').exists())
        # Even a timeout/nonzero process must receive the post-run freeze check.
        try:verify_frozen(campaign, manifest)
        except Exception as exc:errors.append('post-run freeze: ' + str(exc))
        _write(campaign / 'verification.json', verification)
        evidence = _evidence(campaign, run)
        if verified is not None:
            try:_check_audit_binding(verified,evidence)
            except ValueError as exc:errors.append(str(exc))
        elapsed = time.monotonic() - started
        acceptance = dict(schema=ACCEPTANCE_SCHEMA, run_id=RUN_ID, formal=False,
            manifest_identity=manifest['identity'], protocol_sha256=manifest['protocol_sha256'],
            evidence_sha256=evidence, runner_result_sha256=_sha(run / 'result.json') if (run / 'result.json').exists() else None,
            verified_audit_evidence_sha256=verified,
            outer_wall_seconds=elapsed, final_total_bytes_including_acceptance=0,
            child_peak_rss_bytes=usage['peak_rss_bytes'] if usage else None, rss_is_hard_guard=False,
            successful_full_window=result is not None, accepted=not errors, status='success' if not errors else 'failed', errors=errors)
        existing = _bytes(campaign, run)
        if elapsed > OUTER_SECONDS:acceptance['errors'].append('outer final wall exceeds6000 seconds')
        # Size includes frozen files, stdout/stderr, all audit/checkpoint files,
        # supervisor evidence and this exact newline-terminated compact JSON.
        for _ in range(12):
            acceptance.update(accepted=not acceptance['errors'], status='failed' if acceptance['errors'] else 'success')
            acceptance['identity'] = _digest({k: v for k, v in acceptance.items() if k != 'identity'})
            size = existing + len((json.dumps(acceptance, ensure_ascii=False, separators=(',', ':')) + '\n').encode())
            if size > EXPECTED['max_log_bytes'] and 'final total evidence exceeds16GiB' not in acceptance['errors']:
                acceptance['errors'].append('final total evidence exceeds16GiB')
            if size == acceptance['final_total_bytes_including_acceptance'] and acceptance['accepted'] == (not acceptance['errors']):break
            acceptance['final_total_bytes_including_acceptance'] = size
        acceptance['identity'] = _digest({k: v for k, v in acceptance.items() if k != 'identity'})
        _write(campaign / 'acceptance.json', acceptance)
        return acceptance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--execute', action='store_true', help='Explicitly run the single frozen A gate; default prepare only')
    args = parser.parse_args()
    campaign, manifest = prepare(root=args.root)
    result = execute(campaign, manifest) if args.execute else dict(status='prepared', run_id=RUN_ID,
        campaign=str(campaign), identity=manifest['identity'], execution_requires='--execute')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.execute and not result.get('accepted'):raise SystemExit(1)


if __name__ == '__main__':main()
