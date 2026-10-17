"""One frozen A 8h development gate. Default prepare; --execute is explicit.

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
import sys
import time

from .offline_pilot import (
    DATA, VENDOR, ROOT, _sha, _digest, _read, _write, _runtime,
    _origin_git, _git_pointer, _active_claims, _serial_lock, _launch,
)

RUN_ID = 'A_1701_8h_hybrid_v2'
PROTOCOL = 'configs/smt_fullfab/A_hybrid_8h_v2.protocol.json'
AREA = 'runs/smt_fullfab_offline_A_gate'
SCHEMA = 'smt-fullfab-offline-A-gate-frozen-v1'
ACCEPTANCE_SCHEMA = 'smt-fullfab-offline-A-gate-acceptance-v1'
OUTER_SECONDS = 4200
MIN_FREE_BYTES = 24 * 1024**3
TRACE_BYTES = 256 * 1024**2
EXPECTED = dict(arm='A', run_id=RUN_ID, seconds=28800, seed=1701,
                wall_seconds=3600.0, max_plans=1200, plan_seconds=14400,
                period_seconds=1800, lookahead_depth=2, solver_seconds=2.0,
                solver_budget_seconds=32.0, max_slots=4, snapshot_path=None,
                solver_method='hybrid', max_log_bytes=8 * 1024**3,
                constructor_seconds=5.0, max_candidate_evaluations=250000)


def _config(protocol):
    if (protocol.get('schema') != 'smt-fullfab-A-hybrid-8h-development-protocol-v2'
            or protocol.get('formal') is not False or protocol.get('model_calls_authorized') != 0
            or protocol.get('execute_now') is not False):
        raise ValueError('only the preregistered zero-model A development gate is supported')
    config = protocol.get('run_config')
    if (config != EXPECTED or any(type(config[k]) is not type(v) for k, v in EXPECTED.items())):
        raise ValueError('A gate parameters differ from the single approved protocol')
    constraints = protocol.get('execution_constraints', {})
    limits = protocol.get('budget_semantics', {})
    if any(constraints.get(k) != v for k, v in dict(serial_only=True, solver_workers=1,
            solver_seed=11, event_total_slots_per_machine=8, external_watchdog_seconds=OUTER_SECONDS,
            minimum_free_disk_bytes=MIN_FREE_BYTES).items()) or limits.get('fixed_trace_cap_bytes') != TRACE_BYTES:
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
            minimum_free_disk_bytes=MIN_FREE_BYTES, fixed_trace_cap_bytes=TRACE_BYTES)
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
            or manifest.get('fixed_trace_cap_bytes') != TRACE_BYTES):
        raise ValueError('frozen protocol/bounds changed')
    if for_execution and (_runtime() != manifest['runtime'] or sys.executable != manifest.get('launcher_executable')):
        raise ValueError('runtime differs from freeze')
    if for_execution and manifest.get('child_command') != _command(campaign, manifest['config']):
        raise ValueError('frozen child invocation differs')
    if _origin_git(frozen) != manifest['origin_git_head']:raise ValueError('origin pointer changed')
    if not (frozen / 'runs').is_symlink() or (frozen / 'runs').resolve() != root / 'runs':
        raise ValueError('frozen output mapping changed')
    if for_execution:
        for name, path in [('src/smt_fullfab/offline_A_gate.py', Path(__file__)),
                           ('src/smt_fullfab/offline_pilot.py', Path(__file__).with_name('offline_pilot.py'))]:
            if inputs.get(name) != _sha(path):raise ValueError('use the frozen supervisor/helper; live code differs')


def _command(campaign, config, *, executable=None):
    if config != EXPECTED:raise ValueError('A child config differs')
    # Persist the real child PID before importing the frozen runner. The shared
    # watchdog helper returns the same PID/exit code after wait/kill completes.
    bootstrap = ("import sys,os,json,runpy,datetime;frozen=sys.argv.pop(1);pidfile=sys.argv.pop(1);"
                 "sys.path.insert(0,frozen);f=open(pidfile,'x');"
                 "json.dump({'pid':os.getpid(),'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()},f);"
                 "f.write('\\n');f.flush();os.fsync(f.fileno());f.close();"
                 "runpy.run_module('src.smt_fullfab.runner',run_name='__main__')")
    command = [executable or sys.executable, '-I', '-B', '-c', bootstrap, str(campaign / 'frozen'), str(campaign / 'child_started.json')]
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


def _validate_run(run, manifest):
    """Inspect saved evidence only; physical audit was run inside the child."""
    result, config, provenance = (_read(run / name) for name in ('result.json', 'config.json', 'provenance.json'))
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
            or checkpoint.get('hybrid_resource_limits') != dict(runner_wall_seconds=3600.0, max_plans=1200, max_log_bytes=8 * 1024**3)
            or checkpoint.get('cumulative_solver_requested_seconds') != requested
            or checkpoint.get('cumulative_planner_calls') != len(reserves)):
        raise ValueError('checkpoint resource inheritance differs')
    if not (run / 'checkpoint.json').is_file():raise ValueError('successful run lacks actual physical checkpoint')
    audit = _read(run / 'audit.json')
    source, opportunity = audit.get('plan_source_audit', {}), audit.get('opportunity_audit', {})
    if not (result.get('status') == 'success' and result.get('audit_valid') is True
            and result.get('full_window_completed') is True and result.get('simulation_seconds') == 28800
            and audit.get('valid') is True and source.get('valid') is True and opportunity.get('valid') is True
            and source.get('production_machine_count') == source.get('declared_control_machine_count') == 913
            and source.get('declared_full_factory_domain') is True and result.get('metrics') == audit.get('metrics')
            and periodic == 16):
        raise ValueError('full-window physical/source/opportunity evidence does not pass')
    if (len(reserves) > 1200 or requested > 32 or (run / 'trace.jsonl').stat().st_size > TRACE_BYTES
            or type(result.get('wall_seconds')) not in (int, float) or not 0 <= result['wall_seconds'] <= 3600):
        raise ValueError('final runner resource limit exceeded')
    return result, totals


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
        result, _ = _validate_run(run, manifest)
        process = _read(campaign / 'process_outcome.json')
        child = _read(campaign / 'child_started.json')
        attempt = _read(campaign / 'attempt.json')
        if (process.get('returncode') != 0 or process.get('timed_out') is not False
                or type(process.get('pid')) is not int or process['pid'] <= 0 or child.get('pid') != process['pid']
                or attempt.get('manifest_identity') != manifest['identity'] or attempt.get('config') != manifest['config']
                or attempt.get('command') != manifest.get('child_command')
                or acceptance.get('runner_result_sha256') != _sha(run / 'result.json')
                or result['wall_seconds'] > process.get('wall_seconds', -1)
                or not 0 <= process.get('wall_seconds', -1) <= min(3600, acceptance.get('outer_wall_seconds', -1))
                or not 0 <= acceptance.get('outer_wall_seconds', -1) <= OUTER_SECONDS
                or acceptance['final_total_bytes_including_acceptance'] > EXPECTED['max_log_bytes']):
            raise ValueError('successful acceptance lacks valid process/final resource evidence')
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
        errors, result = [], None
        try:
            child = _launch(command, campaign / 'frozen', campaign, max(.001, OUTER_SECONDS - (time.monotonic() - started)))
            _write(campaign / 'process_outcome.json', child)
            if child['timed_out']:raise TimeoutError('watchdog terminated child; preserve partial artifacts without invented checkpoint')
            if child['returncode'] != 0:raise ValueError('runner process returned nonzero')
            if (type(child.get('pid')) is not int or child['pid'] <= 0
                    or type(child.get('wall_seconds')) not in (int, float)
                    or not math.isfinite(child['wall_seconds']) or not 0 <= child['wall_seconds'] <= 3600):
                raise ValueError('invalid child PID or measured wall')
            actual_pid = _read(campaign / 'child_started.json')['pid']
            if actual_pid != child['pid']:raise ValueError('actual child PID differs')
            verify_frozen(campaign, manifest)
            result, totals = _validate_run(run, manifest)
            if result['wall_seconds'] > child['wall_seconds']:raise ValueError('runner wall exceeds complete child measurement')
            verification = dict(valid=True, runner_result_sha256=_sha(run / 'result.json'), resource_totals=totals)
        except Exception as exc:
            errors.append(f'{type(exc).__name__}: {exc}')
            verification = dict(valid=False, errors=list(errors), runner_result_present=(run / 'result.json').exists())
        # Even a timeout/nonzero process must receive the post-run freeze check.
        try:verify_frozen(campaign, manifest)
        except Exception as exc:errors.append('post-run freeze: ' + str(exc))
        _write(campaign / 'verification.json', verification)
        evidence = _evidence(campaign, run)
        elapsed = time.monotonic() - started
        acceptance = dict(schema=ACCEPTANCE_SCHEMA, run_id=RUN_ID, formal=False,
            manifest_identity=manifest['identity'], protocol_sha256=manifest['protocol_sha256'],
            evidence_sha256=evidence, runner_result_sha256=_sha(run / 'result.json') if (run / 'result.json').exists() else None,
            outer_wall_seconds=elapsed, final_total_bytes_including_acceptance=0,
            successful_full_window=result is not None, accepted=not errors, status='success' if not errors else 'failed', errors=errors)
        existing = _bytes(campaign, run)
        if elapsed > OUTER_SECONDS:acceptance['errors'].append('outer final wall exceeds4200 seconds')
        # Size includes frozen files, stdout/stderr, all audit/checkpoint files,
        # supervisor evidence and this exact newline-terminated compact JSON.
        for _ in range(12):
            acceptance.update(accepted=not acceptance['errors'], status='failed' if acceptance['errors'] else 'success')
            acceptance['identity'] = _digest({k: v for k, v in acceptance.items() if k != 'identity'})
            size = existing + len((json.dumps(acceptance, ensure_ascii=False, separators=(',', ':')) + '\n').encode())
            if size > EXPECTED['max_log_bytes'] and 'final total evidence exceeds8GiB' not in acceptance['errors']:
                acceptance['errors'].append('final total evidence exceeds8GiB')
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
