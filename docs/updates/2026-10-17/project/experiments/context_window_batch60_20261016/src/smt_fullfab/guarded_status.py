"""Versioned status adapter for the two guarded development runs.

No execution, recovery, ledger mutation or semantic audit is performed. Success
requires the original frozen gate's saved-evidence readback, its host lifecycle,
and a root record of the actual outer command exit and complete resource cost.
Root wait records are trusted local observations, not backend authentication.
An unclosed result is never promoted by its own success/completed flag.
"""
from __future__ import annotations
from contextlib import contextmanager
from decimal import Decimal
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import types
import uuid

VERSION = 'smt-fullfab-guarded-status-v3'
COMPLETION_SCHEMA = 'smt-fullfab-guarded-root-completion-v1'
EXIT_SCHEMA = 'smt-fullfab-guarded-actual-exit-v1'
RUNS = {
    'C_1701_8h_stream_v1': {
        'arm': 'C', 'seconds': 28800, 'outer_seconds': 46800, 'max_bytes': 24 * 1024**3,
        'gate': 'C_stream_gate', 'campaign_area': 'runs/smt_fullfab_C_stream_gate',
        'host_area': 'runs/smt_fullfab_C_host_guard', 'host_schema': 'smt-fullfab-C8-host-launch-v1',
        'host_source': 'artifacts/smt_fullfab_diagnostics/C8_host_launch_v1/host_launch.py',
        'observation': 'artifacts/smt_fullfab_diagnostics/C8_actual_host_observation_v1',
        'preparation': 'artifacts/smt_fullfab_recovery/C8_stream_v1_frozen_preparation.json',
        'session_id': 60905,
        'preparation_sha256': 'c7bf6e529ee2cba44e1a46b84d5d7f99b19afe6b744c15bc8e661bc58435644b',
        'launch_request_sha256': '05f6ce36e534239a1d1224984aa91763160dd39a0bd8d8a3dcc6a158c546dca9',
    },
    'B_1701_1h_delta_v4': {
        'arm': 'B', 'seconds': 3600, 'outer_seconds': 22200, 'max_bytes': 16 * 1024**3,
        'gate': 'B_delta_gate_v4', 'campaign_area': 'runs/smt_fullfab_B_delta_gate',
        'host_area': 'runs/smt_fullfab_B_delta_host_guard', 'host_schema': 'smt-fullfab-B-delta-host-launch-v4',
        'host_source': 'artifacts/smt_fullfab_diagnostics/B_delta_host_launch_v4/host_launch.py',
        'observation': 'artifacts/smt_fullfab_diagnostics/B_delta_actual_host_observation_v4',
        'preparation': 'artifacts/smt_fullfab_recovery/B_delta_v4_frozen_preparation.json',
        # B has not been frozen/launched. A later explicit registration must pin
        # its independent original preparation and launch request, never C's.
        'preparation_sha256': '511f98adbd959c58c065e377f88e74a4aa94d8afa87ff0733af9958b0568dd54',
        'launch_request_sha256': '4d0c25c0cba5faff0e3c4300c10fb14f07559e981515373beb47ad07880ccea7',
        'session_id': 71042,
    },
}
METRICS = ('weighted_tardy_lot_hours', 'throughput_lots', 'terminal_wip_lots', 'terminal_tardy_wip_lots')
COMPUTE = ('solver_calls', 'actual_cp_solve_seconds', 'planner_calls', 'planner_wall_seconds',
           'classical_event_calls', 'classical_construction_wall_seconds', 'constructor_calls',
           'constructor_requested_seconds', 'constructor_active_seconds')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


def strict(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs)
    json.dumps(value, allow_nan=False)
    return value


def read(path, expected=None, *, retain=True):
    """One FD supplies both parsed bytes and their original hash."""
    path = Path(path)
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    chunks, h = [], hashlib.sha256()
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)), 'rb') as f:
        before = os.fstat(f.fileno())
        require(stat.S_ISREG(before.st_mode) and identity(before) == identity(path.lstat()), 'nonregular or replaced file')
        size = 0
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block); size += len(block)
            if retain:
                chunks.append(block)
        require(size == before.st_size and identity(before) == identity(os.fstat(f.fileno())) == identity(path.lstat()), 'file changed while reading')
    actual = h.hexdigest()
    require(expected is None or actual == expected, 'original SHA differs: ' + str(path))
    return b''.join(chunks) if retain else None, actual, size


def json_file(path, expected=None, anchors=None):
    raw, original, size = read(path, expected)
    if anchors is not None:
        anchors[Path(path)] = original
    value = strict(raw)
    require(type(value) is dict, 'JSON object required')
    return value, original, size


def tree(base, *, omit=()):
    found = {}
    for path in sorted(Path(base).rglob('*')):
        require(not path.is_symlink(), 'unexpected status evidence symlink')
        if path.is_file() and path.relative_to(base).as_posix() not in omit:
            _, original, size = read(path, retain=False)
            found[path.relative_to(base).as_posix()] = {'sha256': original, 'bytes': size}
    return found


@contextmanager
def frozen_modules(campaign, manifest, spec):
    """Private namespace: never reuse a current live gate/dependency module."""
    frozen = campaign / 'frozen'
    sources = {name: value for name, value in manifest['frozen_input_sha256'].items()
               if name.startswith('src/')}
    required = ('src/smt_fullfab/' + spec['gate'] + '.py', 'src/smt_fullfab/model_process_guard.py')
    require(all(name in sources for name in required), 'frozen gate/guard source missing')
    require({'src/'+name:value['sha256'] for name,value in tree(frozen/'src').items()} == sources,
            'frozen source inventory differs before import (including unlisted bytecode)')
    prefix = '_fullfab_status_' + uuid.uuid4().hex
    module = types.ModuleType(prefix); module.__path__ = [str(frozen)]
    sys.modules[prefix] = module
    prior = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        gate = importlib.import_module(prefix + '.src.smt_fullfab.' + spec['gate'])
        guard = importlib.import_module(prefix + '.src.smt_fullfab.model_process_guard')
        require(Path(gate.__file__).resolve() == frozen / required[0]
                and Path(guard.__file__).resolve() == frozen / required[1], 'gate/guard not loaded from original frozen tree')
        yield gate, guard
        require({'src/'+name:value['sha256'] for name,value in tree(frozen/'src').items()} == sources,
                'frozen source inventory changed during readback')
    finally:
        sys.dont_write_bytecode = prior
        for key in tuple(sys.modules):
            if key == prefix or key.startswith(prefix + '.'):
                del sys.modules[key]


def _physical_complete(result, spec, run_id):
    cfg = result.get('config')
    if type(cfg) is not dict:
        return False
    common = (cfg.get('run_id') == run_id and cfg.get('arm') == spec['arm']
              and cfg.get('seed') == 1701 and cfg.get('seconds') == spec['seconds']
              and type(result.get('simulation_seconds')) in (int, float)
              and result['simulation_seconds'] == spec['seconds'] and result.get('audit_valid') is True
              and result.get('failure') is None and result.get('accepted') is False)
    if spec['arm'] == 'C':
        return (common and result.get('status') == 'success' and result.get('full_window_completed') is True
                and result.get('terminal_trace_binding_valid') is True
                and result.get('acceptance_authority') == 'external_frozen_gate'
                and result.get('launch_authority_scope') == 'controller_does_not_self_authorize'
                and result.get('real_C8_launch_authorized') is False
                and result.get('direct_public_execution_enabled') is False)
    return (common and result.get('schema') == 'smt-fullfab-B-delta-controller-v4-result'
            and result.get('status') == 'completed' and result.get('delta_attribution_valid') is True
            and result.get('finalization_errors') == [])


def _verify_host_lifecycle(host, host_result, campaign, manifest, manifest_sha,
                           spec, run_id, gate, guard, anchors, *, failed_acceptance_sha=None):
    """The original success check; narrowly also bind completed nonzero failure.

    Failed-cost closure never makes an acceptance claim. Its original output
    SHA is supplied by the saved host guard, not derived from current bytes.
    """
    frozen_host = campaign / 'frozen' / spec['host_source']
    executable = manifest['launcher_executable']
    request, request_sha, _ = json_file(host / 'request.json', host_result['host_request_sha256'], anchors)
    child_command = [executable, '-I', '-B', str(frozen_host), '--gate-child', '--campaign', str(campaign), '--manifest-sha256', manifest_sha]
    require(request == {'schema':spec['host_schema']+'-request', 'campaign':str(campaign),
                       'manifest_sha256':manifest_sha, 'command':child_command, 'automatic_retry':False}, 'host original guarded request differs')
    io = {'cwd':str(campaign/'frozen'), 'stdin':None, 'stdout':str(host/'stdout.log'), 'stderr':str(host/'stderr.log'),
          'inputs':{'manifest':str(campaign/'manifest.json'), 'host_request':str(host/'request.json'), 'wrapper':str(frozen_host)},
          'outputs':{'stdout':str(host/'stdout.log'), 'stderr':str(host/'stderr.log'), 'gate_acceptance':str(campaign/'acceptance.json')}}
    original = host_result['guard_evidence']
    failed = failed_acceptance_sha is not None
    require(type(original) is dict and original.get('guard_source_sha256') == manifest['frozen_input_sha256']['src/smt_fullfab/model_process_guard.py']
            and original.get('lifecycle_complete') is True and type(original.get('command_returncode')) is int
            and ((failed and original['command_returncode'] != 0) or (not failed and original['command_returncode'] == 0))
            and original.get('timed_out') is False and original.get('launch_error') is None
            and all(type(original.get(k)) is int and 0 <= original[k]
                    and (failed or original[k] <= gate.RSS_BYTES)
                    for k in ('command_peak_rss_bytes', 'guard_peak_rss_bytes')), 'host guard terminal/RSS failed')
    if failed:
        require(original.get('input_files_sha256') == {
                    'manifest':manifest_sha, 'host_request':request_sha,
                    'wrapper':manifest['frozen_input_sha256'][spec['host_source']]}
                and original.get('io_spec') == io
                and original.get('output_files_sha256', {}).get('gate_acceptance') == failed_acceptance_sha,
                'failed host original guard input/io/output anchors differ')
    require(number(host_result['guard_admitted_seconds']) and 0 < host_result['guard_admitted_seconds'] <= spec['outer_seconds'], 'host admitted timeout invalid')
    guard.verify_lifecycle(host, expected_command=child_command, expected_timeout=host_result['guard_admitted_seconds'],
        expected_call_id=run_id+':host', expected_fingerprint=digest(request), expected_evidence=original, expected_io_spec=io)


def _closed(root, folder, spec, result, result_sha, completion, completion_sha, closed):
    run_id = folder.name
    campaign = root / spec['campaign_area'] / run_id
    host = root / spec['host_area'] / run_id
    observation = root / spec['observation']
    anchors = {observation / 'root_completion.json': completion_sha}
    if result_sha is not None:
        anchors[folder / 'result.json'] = result_sha
    prep, prep_sha, prep_size = json_file(root / spec['preparation'], spec['preparation_sha256'], anchors)
    launch, launch_sha, _ = json_file(observation / 'request.json', spec['launch_request_sha256'], anchors)
    manifest_sha = prep['manifest_sha256']
    manifest, _, _ = json_file(campaign / 'manifest.json', manifest_sha, anchors)
    require(prep['campaign'] == str(campaign) and manifest['run_id'] == run_id
            and manifest['origin_root'] == str(root) and manifest['output_directory'] == str(folder)
            and manifest['identity'] == digest({k:v for k,v in manifest.items() if k != 'identity'}), 'original preparation/manifest identity differs')
    require(completion.get('schema') == COMPLETION_SCHEMA and completion.get('run_id') == run_id
            and completion.get('manifest_sha256') == manifest_sha
            and completion.get('preparation_sha256') == prep_sha
            and completion.get('launch_request_sha256') == launch_sha
            and completion.get('campaign') == str(campaign) and completion.get('host_directory') == str(host)
            and completion.get('status') in ('success', 'failed')
            and completion.get('identity') == digest({k:v for k,v in completion.items() if k != 'identity'}), 'root completion original identity differs')
    exited, _, _ = json_file(observation / 'actual_exit.json', completion['actual_exit_sha256'], anchors)
    require(exited.get('schema') == EXIT_SCHEMA and exited.get('run_id') == run_id
            and exited.get('observation_method') == 'write_stdin_terminal_result'
            and exited.get('exited') is True and type(exited.get('session_id')) is int
            and exited['session_id'] == spec['session_id']
            and type(exited.get('exit_code')) is int and type(exited.get('timed_out')) is bool
            and type(exited.get('terminal_tool_result')) is dict
            and type(exited['terminal_tool_result'].get('exit_code')) is int
            and exited['terminal_tool_result']['exit_code'] == exited['exit_code'], 'actual host terminal wait missing/invalid')
    if 'session_id' in exited['terminal_tool_result']:
        require(exited['terminal_tool_result']['session_id'] == exited['session_id'], 'original session identity differs')
    executable = manifest['launcher_executable']
    command = ['/usr/bin/time', '-p', executable, '-I', '-B', str(campaign / 'frozen' / spec['host_source']),
               '--campaign', str(campaign), '--manifest-sha256', manifest_sha]
    require(launch.get('command') == command and exited.get('command') == command
            and launch.get('manifest_sha256') == manifest_sha
            and launch.get('actual_wait_required') is True and launch.get('automatic_retry') is False
            and launch.get('one_attempt') is True, 'original host invocation differs')
    stdout_raw, stdout_sha, _ = read(observation / 'stdout.log', exited['stdout_sha256'])
    stderr_raw, stderr_sha, _ = read(observation / 'time_and_stderr.log', exited['time_and_stderr_sha256'])
    anchors[observation / 'stdout.log'] = stdout_sha; anchors[observation / 'time_and_stderr.log'] = stderr_sha
    # /usr/bin/time -p rounds to two decimal places. Keep its original text and
    # add one hundredth conservatively; do not equate missing timing with zero.
    times = re.findall(rb'(?m)^real[ \t]+([0-9]+\.[0-9]{2})[ \t]*$', stderr_raw)
    require(len(times) == 1, 'unique actual /usr/bin/time real measurement missing')
    real_text = times[0].decode('ascii')
    host_upper = Decimal(real_text) + Decimal('0.01')
    preparation = prep['root_preparation_and_immediate_verification_wall_seconds']
    require(number(preparation) and preparation >= manifest['prepare_wall_seconds'], 'external preparation cost missing/invalid')
    total_wall = Decimal(str(preparation)) + host_upper
    require(all(type(completion.get(k)) is str and re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', completion[k])
                for k in ('host_wall_seconds_upper_bound', 'total_wall_seconds_upper_bound')),
            'wall upper bounds must be finite decimal strings, never rounded floats')
    require(completion.get('host_real_seconds_text') == real_text
            and Decimal(str(completion.get('host_wall_seconds_upper_bound'))) == host_upper
            and Decimal(str(completion.get('total_wall_seconds_upper_bound'))) == total_wall
            and completion.get('preparation_wall_seconds') == preparation, 'complete actual wall bound differs')
    obs_tree = tree(observation, omit=('root_completion.json',))
    require(completion.get('observation_evidence_sha256') == {k:v['sha256'] for k,v in obs_tree.items()}, 'observation inventory changed or omitted files')
    require(type(completion.get('posterior_readback_wall_seconds')) in (int, float)
            and number(completion['posterior_readback_wall_seconds'])
            and completion.get('posterior_scope') == 'read-only status/review after actual experiment exit; separately reported; no model/factory/solver',
            'posterior review scope/time missing')
    require(type(completion.get('errors')) is list and type(completion.get('accepted')) is bool, 'invalid root terminal flags')
    host_result, host_sha, _ = json_file(host / 'result.json', completion['host_result_sha256'], anchors)
    require(host_result.get('schema') == spec['host_schema'] + '-result'
            and host_result.get('run_id') == run_id and host_result.get('manifest_sha256') == manifest_sha
            and host_result.get('campaign') == str(campaign) and host_result.get('host_directory') == str(host)
            and host_result.get('identity') == digest({k:v for k,v in host_result.items() if k != 'identity'}), 'host result identity differs')
    # A nonzero gate child can make the original host exit before it copies its
    # guard's acceptance output SHA into the optional explicit result field.
    # Preserve the old explicit-anchor path, especially every success case.
    failed_guard_anchor = ('gate_acceptance_sha256' in host_result
                           and host_result['gate_acceptance_sha256'] is None)
    if failed_guard_anchor:
        require(host_result.get('status') == 'failed' and host_result.get('accepted') is False
                and completion['status'] == 'failed' and completion['accepted'] is False
                and exited['exit_code'] != 0 and exited['timed_out'] is False,
                'missing explicit host acceptance anchor is not an eligible completed failure')
        original = host_result.get('guard_evidence')
        require(type(original) is dict and type(original.get('output_files_sha256')) is dict,
                'failed host original guard output missing')
        acceptance_anchor = original['output_files_sha256'].get('gate_acceptance')
        require(type(acceptance_anchor) is str and re.fullmatch(r'[0-9a-f]{64}', acceptance_anchor)
                and acceptance_anchor == completion['gate_acceptance_sha256'],
                'failed host original guard acceptance SHA missing or differs')
    else:
        acceptance_anchor = host_result['gate_acceptance_sha256']
        require(acceptance_anchor == completion['gate_acceptance_sha256'], 'host did not retain original gate acceptance')
    acceptance, acceptance_sha, _ = json_file(campaign / 'acceptance.json', acceptance_anchor, anchors)
    require(completion['runner_result_sha256'] == result_sha == acceptance.get('runner_result_sha256'), 'original runner result differs')
    if failed_guard_anchor:
        require(acceptance.get('accepted') is False and acceptance.get('status') == 'failed',
                'failed host guard output does not bind a failed gate acceptance')
    host_tree = tree(host)
    require({k:v['sha256'] for k,v in host_tree.items() if k != 'result.json'} == host_result['host_evidence_sha256']
            and host_tree['result.json']['sha256'] == host_sha, 'host original inventory changed')
    for key, entry in host_tree.items():
        anchors[host / key] = entry['sha256']
    for key, entry in obs_tree.items():
        anchors[observation / key] = entry['sha256']
    expected_stdout = {'accepted':host_result['accepted'], 'status':host_result['status'],
                       'result_path':str(host / 'result.json'), 'result_sha256':host_sha}
    require(strict(stdout_raw) == expected_stdout, 'actual host stdout does not bind its original result')
    closed.update(wall_seconds=float(total_wall), wall_seconds_upper_bound_text=str(total_wall), actual_exit_code=exited['exit_code'],
                  actual_timed_out=exited['timed_out'], posterior_readback_wall_seconds=completion['posterior_readback_wall_seconds'])
    final_ledger_check = ledger_proof = None
    with frozen_modules(campaign, manifest, spec) as (gate, guard):
        require(gate.RUN_ID == run_id and gate.OUTER_SECONDS == spec['outer_seconds']
                and gate.MAX_BYTES == spec['max_bytes'] and gate.RSS_BYTES == 8 * 1024**3, 'frozen version/limits differ')
        frozen_host = campaign / 'frozen' / spec['host_source']
        read(frozen_host, manifest['frozen_input_sha256'][spec['host_source']], retain=False)
        verified = gate.read_acceptance(root=root)
        require(verified.get('valid') is True and verified.get('acceptance_sha256') == acceptance_sha, 'original frozen gate readback rejected')
        if failed_guard_anchor:
            require(verified.get('accepted') is False and verified.get('status') == 'failed',
                    'failed host guard anchor cannot certify a success readback')
            _verify_host_lifecycle(host, host_result, campaign, manifest, manifest_sha,
                spec, run_id, gate, guard, anchors, failed_acceptance_sha=acceptance_sha)
            closed.update(gate_acceptance_anchor_source='original_host_guard_output',
                          host_lifecycle_verified_for_failed_cost=True)
        gate_bytes = gate.total_bytes(campaign, folder)
        total_bytes = gate_bytes + sum(v['bytes'] for v in host_tree.values()) + sum(v['bytes'] for v in obs_tree.values()) + prep_size + (observation / 'root_completion.json').stat().st_size
        require(type(completion.get('total_bytes_including_completion')) is int
                and completion['total_bytes_including_completion'] == total_bytes
                and completion.get('disk_scope') == 'gate_campaign_run_scratch+host+all_observation_files+preparation_record+root_completion', 'complete original disk cost differs')
        closed['total_bytes'] = total_bytes
        require(number(host_result['total_wall_seconds_at_last_encoding_start'])
                and float(total_wall) >= host_result['total_wall_seconds_at_last_encoding_start']
                and host_result['prepare_wall_seconds'] == manifest['prepare_wall_seconds'], 'root outer wall is less than already measured inner wall')
        require(host_result['total_bytes_including_host_result'] == gate_bytes + sum(v['bytes'] for v in host_tree.values()), 'host disk total differs')
        accepted = (completion['accepted'] is True and completion['status'] == 'success' and completion['errors'] == []
                    and exited['exit_code'] == 0 and exited['timed_out'] is False
                    and total_wall <= Decimal(spec['outer_seconds']) and total_bytes <= spec['max_bytes']
                    and host_result.get('accepted') is True and host_result.get('status') == 'success'
                    and host_result.get('errors') == [] and verified.get('accepted') is True
                    and verified.get('status') == 'success' and acceptance.get('accepted') is True
                    and _physical_complete(result, spec, run_id))
        if accepted:
            # Carry original account anchors through the long trailing evidence
            # collections. Never take a newer ledger SHA from the live ledger.
            ledger_proof, _, _ = json_file(campaign / 'verification_payload.json',
                acceptance['evidence_sha256']['campaign/verification_payload.json'], anchors)
            require(ledger_proof.get('valid') is True
                    and type(ledger_proof.get('ledger_sha256')) is str
                    and re.fullmatch(r'[0-9a-f]{64}', ledger_proof['ledger_sha256'])
                    and type(ledger_proof.get('registration_id')) is str
                    and bool(ledger_proof['registration_id']), 'original ledger verification payload invalid')
            final_ledger_check = gate._final_ledger
            require(host_result.get('gate_readback') == verified, 'host original gate readback differs')
            _verify_host_lifecycle(host, host_result, campaign, manifest, manifest_sha,
                spec, run_id, gate, guard, anchors)
        require(gate.evidence(campaign, folder, include_outer=True) == acceptance['evidence_sha256']
                and gate.total_bytes(campaign, folder) == gate_bytes, 'gate original evidence changed after readback')
    for path, expected in anchors.items():
        read(path, expected, retain=False)
    require(tree(observation, omit=('root_completion.json',)) == obs_tree and tree(host) == host_tree, 'terminal evidence inventory changed during status readback')
    if accepted:
        # This retained function is the already-verified original frozen gate
        # implementation. Its globals remain bound after namespace cleanup; no
        # module is imported again. Check the live account after the LAST large
        # source/campaign/host/observation collection, including its final fence.
        final_ledger_check(folder, manifest, ledger_proof['ledger_sha256'], ledger_proof['registration_id'])
    return accepted


def guarded_result_row(folder, *, root):
    """Return pending/failed/success without promoting an unclosed endpoint.

    Known physical/ledger costs are displayed even for failures. Unknown values
    remain None. Complete wall replaces the child wall only after its original
    actual-exit evidence was validated; posterior review time stays separate.
    """
    root = Path(root).resolve(); folder = Path(folder).resolve(); run_id = folder.name
    require(run_id in RUNS, 'not a registered guarded status version')
    spec = RUNS[run_id]
    require(folder == root / 'runs/smt_fullfab_stage2' / run_id, 'guarded status run path differs')
    result, result_sha, result_size, errors, closed = {}, None, None, [], {}
    try:
        if (folder / 'result.json').exists():
            result, result_sha, result_size = json_file(folder / 'result.json')
    except Exception as exc:
        errors.append(str(exc))
    physical_wall = result.get('wall_seconds' if spec['arm'] == 'C' else 'end_to_end_wall_seconds')
    physical_wall = physical_wall if number(physical_wall) else None
    pending = not errors and result.get('status') != 'failed'
    accepted = False
    completion_path = root / spec['observation'] / 'root_completion.json'
    completion_sha = None
    reported = {}
    if completion_path.exists():
        pending = False
        try:
            require(spec['preparation_sha256'] is not None and spec['launch_request_sha256'] is not None, 'independent original freeze/launch anchors not registered')
            completion, completion_sha, _ = json_file(completion_path)
            reported = {key:completion.get(key) for key in ('total_wall_seconds_upper_bound', 'total_bytes_including_completion', 'posterior_readback_wall_seconds')}
            accepted = _closed(root, folder, spec, result, result_sha, completion, completion_sha, closed)
            if not accepted:
                errors.append('root, host, original gate, resource or full-window acceptance did not pass')
        except Exception as exc:
            closed.clear()
            errors.append(str(exc))
    else:
        errors.append('awaiting root actual-exit and complete-resource closure')
        # A saved explicit failure is already failed, even before cost closure.
        exit_path = root / spec['observation'] / 'actual_exit.json'
        if exit_path.exists():
            try:
                exited, _, _ = json_file(exit_path)
                if (exited.get('schema') == EXIT_SCHEMA and exited.get('run_id') == run_id
                        and exited.get('exited') is True and type(exited.get('exit_code')) is int
                        and (exited['exit_code'] != 0 or exited.get('timed_out') is True)):
                    pending = False
            except Exception as exc:
                pending = False; errors.append(str(exc))
        for parent in (root / spec['host_area'] / run_id, root / spec['campaign_area'] / run_id):
            name = 'result.json' if parent.parent.name == Path(spec['host_area']).name else 'acceptance.json'
            if (parent / name).exists():
                try:
                    value, _, _ = json_file(parent / name)
                    if value.get('status') == 'failed' or value.get('accepted') is False:
                        pending = False
                except Exception as exc:
                    pending = False; errors.append(str(exc))
    status = 'success' if accepted else 'pending' if pending else 'failed'
    metrics = result.get('metrics') if type(result.get('metrics')) is dict else {}
    cfg = result.get('config') if type(result.get('config')) is dict else {}
    row = {'run_id':run_id, 'kind':'experiment', 'arm':spec['arm'], 'scenario':1701, 'window_seconds':spec['seconds'],
           'status':status, 'accepted':accepted, 'guarded_status_version':VERSION, 'guarded_host_accepted':accepted,
           'guarded_acceptance_errors':errors, 'root_completion_sha256':completion_sha, 'result_sha256':result_sha, 'result_bytes':result_size,
           'physical_status':result.get('status'), 'physical_audit_valid':result.get('audit_valid', False),
           'full_window_completed':accepted, 'audit_valid':accepted, 'simulation_seconds':result.get('simulation_seconds'),
           'plans':result.get('plans', result.get('plans_committed')), 'failure':None if accepted or pending else result.get('failure') or 'guarded_complete_acceptance_not_passed',
           'wall_seconds':closed.get('wall_seconds', physical_wall), 'physical_result_wall_seconds':physical_wall,
           'wall_seconds_complete':bool(closed.get('wall_seconds') is not None), 'model_calls':result.get('model_calls'),
           'solver_requested_seconds':result.get('solver_requested_seconds') if spec['arm'] == 'C' else cfg.get('solver_budget_seconds'),
           'root_resource_closure':closed, 'root_reported_resources_unverified':reported if not closed else {}, **{k:result.get(k) for k in COMPUTE}, **{k:metrics.get(k) for k in METRICS}}
    return row
