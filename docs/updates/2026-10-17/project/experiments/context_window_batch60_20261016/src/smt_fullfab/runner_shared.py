"""M2 shared-start A control-loop candidate; not a gate or resume endpoint.

Only a trusted host may hold the M1 context. Public execution remains blocked
pending M2 tests, independent shared-suffix audit and outer freeze.
"""
from __future__ import annotations
from copy import deepcopy
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback
from types import ModuleType, SimpleNamespace

SCHEMA = 'smt-shared-A-controller-v1'
LAUNCH_BLOCKERS = ('M2 first tests, M5 shared attribution and outer frozen admission pending',)
CONTEXT_SHA = '5186e2cdc1a136ff6f80c02543e34ba87b9ff3ad375f10df2f5f68e7d2847e0d'
RUNTIME_SHA = {
    'src/smt_fullfab/hybrid.py': '3c89ea263fdace8cb3636b5119e60374944ae2a2ea8d1e9c558cc0496f9cf6bd',
    'src/smt_fullfab/runner.py': '3235ffa2346a887ab294e5696ffd7245150b6707155e0e203bce25e80a200c70',
    'src/smt_fullfab/stream_audit_bundle.py': '072b4bc9c5da49d95beaad767b2ef3fab806a64ccaeab29124b5813241f3e44d',
}
CONFIG_KEYS = {'schema', 'arm', 'run_id', 'seed', 'evaluation', 'window_seconds',
    'wall_seconds', 'max_plans', 'solver_budget_seconds', 'max_log_bytes',
    'max_trace_bytes', 'period_seconds', 'plan_seconds', 'lookahead_depth',
    'solver_seconds', 'max_slots', 'constructor_seconds', 'max_candidate_evaluations',
    'solver_method', 'audit_mode', 'snapshot_mode', 'model_calls', 'formal'}
ALGORITHM = {'period_seconds': 1800, 'plan_seconds': 14400, 'lookahead_depth': 2,
    'solver_seconds': 2.0, 'max_slots': 4, 'constructor_seconds': 5.0,
    'max_candidate_evaluations': 250000, 'solver_method': 'hybrid',
    'audit_mode': 'stream', 'snapshot_mode': 'stream', 'model_calls': 0, 'formal': False}


def require(value, message):
    if not value: raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def digest(value): return hashlib.sha256(canonical(value)).hexdigest()
def same(left, right): return canonical(left) == canonical(right)
def finite(value): return type(value) in (int, float) and math.isfinite(value)


def load_context(path):
    """Load the exact M1 source, never an AST-extracted approximation."""
    path = Path(path).resolve(); raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == CONTEXT_SHA, 'M1 version differs; explicit re-review/re-pin required')
    module = ModuleType('shared_A_bound_M1'); module.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    require(path.read_bytes() == raw, 'M1 source changed during loading')
    return module, raw


def load_runtime(source_root, context_path):
    root = Path(source_root).resolve(); sources = {}
    for name, expected in RUNTIME_SHA.items():
        raw = (root / name).read_bytes()
        require(hashlib.sha256(raw).hexdigest() == expected, 'runtime dependency differs: ' + name)
        sources[name] = raw
    sys.path.insert(0, str(root))
    context, raw = load_context(context_path)
    sources['src/smt_fullfab/shared_controller.py'] = raw
    from src.smt_fullfab import hybrid, runner, stream_audit_bundle
    for module, name in ((hybrid, 'src/smt_fullfab/hybrid.py'), (runner, 'src/smt_fullfab/runner.py'),
                         (stream_audit_bundle, 'src/smt_fullfab/stream_audit_bundle.py')):
        require(Path(module.__file__).resolve() == root / name and (root / name).read_bytes() == sources[name], 'import source differs')
    sources['runner_shared.py'] = Path(__file__).read_bytes()
    return SimpleNamespace(context=context, ss=context.ss, hybrid=hybrid, crop_plan=runner.crop_plan,
        bundle=stream_audit_bundle, sources=sources, source_root=root, context_path=Path(context_path).resolve(),
        source_paths={**{name: root / name for name in RUNTIME_SHA},
            'src/smt_fullfab/shared_controller.py': Path(context_path).resolve(),
            'runner_shared.py': Path(__file__).resolve()})


def _source_fence(runtime):
    # Only these immediate sources are checked here. The host must freeze all
    # transitive src/vendor/data/requirements; this is not a full source seal.
    for name, path in runtime.source_paths.items():
        require(path.read_bytes() == runtime.sources[name], 'original runtime source changed: ' + name)


def _config(config, runtime):
    require(type(config) is dict and set(config) == CONFIG_KEYS and config['schema'] == SCHEMA + '-config'
            and config['arm'] == 'A', 'exact shared-A config required; same-A snapshot resume is not supported')
    require(all(same(config[key], value) for key, value in ALGORITHM.items()), 'original A hybrid algorithm parameters differ')
    require(runtime.ss.name_string(config['run_id']) and type(config['seed']) is int, 'explicit run name/seed required')
    runtime.context.AnchoredPeriodClock(config['evaluation'])  # Exact M1 window contract.
    w = config['evaluation']
    require(type(config['window_seconds']) is int and config['window_seconds'] in (3600, 28800, 86400)
            and config['window_seconds'] == w['absolute_end'] - w['absolute_start'], 'shared duration must be delta, not H')
    require(all(finite(config[k]) and config[k] > 0 for k in ('wall_seconds', 'solver_budget_seconds')),
            'positive offline wall/CP limits required')
    require(all(type(config[k]) is int and config[k] > 0 for k in ('max_plans', 'max_log_bytes', 'max_trace_bytes')),
            'positive original integer resource caps required')
    return deepcopy(config)


def _admission(config, binding, admission, output, source_sha):
    require(binding['registration_kind'] == 'offline_A_admission' and binding['registration_id'] is None,
            'real offline-A admission required; not a BudgetLedger registration')
    expected = {'schema': 'smt-shared-controller-context-v1-offline-A-admission', 'arm': 'A',
        'run_path': str(output), 'run_name': config['run_id'], 'seed': config['seed'],
        'window_seconds': config['window_seconds'], 'source_sha256': source_sha,
        'config_sha256': digest(config), 'solver_budget_seconds': config['solver_budget_seconds'],
        'wall_seconds': config['wall_seconds'], 'max_log_bytes': config['max_log_bytes'], 'model_calls': 0}
    require(same(admission, expected), 'offline config/admission limits or identity differ')
    require(binding['arm'] == 'A' and binding['run_name'] == config['run_id'] and binding['run_path'] == str(output)
            and binding['source_sha256'] == source_sha and binding['config_sha256'] == digest(config)
            and binding['window_seconds'] == config['window_seconds']
            and same(binding['evaluation'], config['evaluation']), 'original branch binding differs')


def _write(runtime, path, value):
    return {'path': str(path), 'sha256': runtime.ss.publish(path, value)}


def _append(path, value):
    raw = canonical(value) + b'\n'
    with Path(path).open('ab') as stream:
        written = stream.write(raw)
        require(type(written) is int and written == len(raw), 'short resource/event journal write')
        stream.flush(); os.fsync(stream.fileno())


def _bytes(path):
    total = 0
    for member in Path(path).rglob('*'):
        require(not member.is_symlink(), 'run evidence symlink rejected')
        if member.is_file(): total += member.stat().st_size
    return total


def _limits(config, output, begun, *, extra=0):
    require(time.monotonic() - begun <= config['wall_seconds'], 'offline wall cap exceeded')
    require(_bytes(output) + extra <= config['max_log_bytes'], 'complete run byte cap exceeded')
    trace = output / 'trace.jsonl'
    require(not trace.exists() or trace.stat().st_size <= config['max_trace_bytes'], 'full prefix+suffix trace cap exceeded')


def _costs():
    return {'planner_calls': 0, 'solver_calls': 0, 'classical_event_calls': 0,
        'solver_requested_seconds': 0.0, 'event_constructor_requested_seconds': 0.0,
        'planner_outer_wall_seconds': 0.0,
        'unclosed_tool_reservations': 0, 'commit_attempts': 0, 'commit_receipts_confirmed': 0,
        'advance_receipts_confirmed': 0,
        'inner_costs': {key: {'known_sum': 0.0, 'unknown_count': 0} for key in
            ('wall_seconds', 'solve_wall_seconds', 'classical_construction_wall_seconds')}}


def _inner_costs(costs, response):
    for key, target in costs['inner_costs'].items():
        value = response.get(key) if type(response) is dict else None
        if finite(value) and value >= 0: target['known_sum'] += value
        else: target['unknown_count'] += 1


def _tool(problem, *, index, mode, request, kernel, clock, config, output, runtime, costs):
    reservation = {'event': 'solver_reserve', 'arm': 'A', 'plan': index,
        'requested_seconds': request, 'planner_mode': mode,
        'constructor_seconds_limit': config['constructor_seconds'] if mode == 'event_classical' else None,
        'max_candidate_evaluations': config['max_candidate_evaluations'] if mode == 'event_classical' else None,
        'kernel_configuration': kernel, 'effective_period_clock': clock,
        'problem_sha256': digest(problem), 'offline_admission': True}
    _append(output / 'resources.jsonl', reservation)
    costs['planner_calls'] += 1; costs['unclosed_tool_reservations'] += 1
    costs['solver_requested_seconds'] += request
    costs['solver_calls' if mode == 'periodic_cp' else 'classical_event_calls'] += 1
    if mode == 'event_classical': costs['event_constructor_requested_seconds'] += config['constructor_seconds']
    started = time.monotonic(); response = None
    try:
        response = runtime.hybrid.solve_hybrid_plan(problem, mode=mode, config=kernel,
            time_limit_seconds=request, seed=11, plan_version=config['run_id'] + ':' + str(index))
    except BaseException as exc:
        elapsed = time.monotonic() - started; costs['planner_outer_wall_seconds'] += elapsed
        _inner_costs(costs, None)
        row = {'event': 'solver_finish', 'arm': 'A', 'plan': index, 'planner_mode': mode,
            'requested_seconds_consumed': request, 'actual_outer_wall_seconds': elapsed,
            'solver_status': 'EXCEPTION', 'reported_inner_costs': None,
            'exception': {'type': type(exc).__name__, 'message': str(exc), 'traceback': traceback.format_exc()}}
        try:
            _write(runtime, output / f'solver_exception_{index:05d}.json', row)
            _append(output / 'resources.jsonl', row); costs['unclosed_tool_reservations'] -= 1
        except BaseException as secondary:
            if hasattr(exc, 'add_note'): exc.add_note('tool failure evidence also failed: ' + repr(secondary))
            if not isinstance(secondary, Exception): raise secondary from exc
        raise
    elapsed = time.monotonic() - started; costs['planner_outer_wall_seconds'] += elapsed
    _inner_costs(costs, response)
    response_ref = _write(runtime, output / f'solver_{index:05d}.json', response)  # Original returned object, no added schedule field.
    row = {'event': 'solver_finish', 'arm': 'A', 'plan': index, 'planner_mode': mode,
        'requested_seconds_consumed': request, 'actual_outer_wall_seconds': elapsed,
        'solver_status': response.get('solver_status') if type(response) is dict else None,
        'reported_inner_costs': {key: response.get(key) for key in costs['inner_costs']} if type(response) is dict else None,
        'response_ref': response_ref}
    _append(output / 'resources.jsonl', row); costs['unclosed_tool_reservations'] -= 1
    require(type(response) is dict and response.get('hybrid_mode') == mode
            and same(response.get('hybrid_configuration'), kernel)
            and response.get('cp_requested_seconds_reserved') == request, 'kernel response/config/reservation differs')
    require(response.get('solver_status') in ('OPTIMAL', 'FEASIBLE', 'FEASIBLE_HEURISTIC')
            and response.get('nominal_audit', {}).get('valid') is True and type(response.get('plan')) is dict,
            'planner failed or nominal plan rejected; no fallback')
    return response, response_ref


def _trace_anchor(runtime, path):
    before = runtime.ss.identity(Path(path).lstat())
    _, receipt = runtime.ss.read_bytes(path, retain=False)
    require(runtime.ss.identity(Path(path).lstat()) == before, 'trace changed while obtaining original anchor')
    return {**receipt, 'identity': list(before)}


def _trace_fence(runtime, path, original):
    runtime.ss.read_bytes(path, original['sha256'], retain=False)
    require(list(runtime.ss.identity(Path(path).lstat())) == original['identity'], 'original trace identity changed')


def _terminal_audit(config, runtime, output, data_dir, anchor):
    created = runtime.bundle.audit_to_bundle(output / 'trace.jsonl', output_dir=output / 'audit_bundle',
        expected_source_sha256=anchor['sha256'], verify_data_dir=data_dir,
        window_start=config['evaluation']['absolute_start'], require_terminal=True)
    checked = runtime.bundle.read_bundle(output / 'audit_bundle', expected_manifest_sha256=created['report_sha256'])
    require(checked['storage_verified'] is True and same(checked['source_receipt'], created['source_receipt'])
            and same(checked['summary'], created['summary'])
            and checked['source_receipt']['sha256'] == anchor['sha256'], 'terminal bundle differs from first trace anchor')
    summary = checked['summary']; metrics = summary['metrics']
    require(summary['valid'] is True and summary['complete_physical_window_certified'] is True
            and summary['verified_input_hashes'] is True
            and metrics['window_start'] == config['evaluation']['absolute_start']
            and metrics['window_end'] == config['evaluation']['absolute_end'], 'terminal audit/window rejected')
    _trace_fence(runtime, output / 'trace.jsonl', anchor)
    return {'path': 'audit_bundle', 'manifest_sha256': created['report_sha256'],
            'summary': summary, 'source_receipt': checked['source_receipt']}


def _run_A_shared(*, config, package_dir, expected_manifest_sha256, branch_binding_path,
                  expected_binding_sha256, output_dir, expected_source_sha256, runtime, started=None):
    """Actual create-new loop; injectable pure dependencies only for tiny tests."""
    begun = time.monotonic() if started is None else started
    config = _config(config, runtime); output = Path(output_dir).resolve(); package = Path(package_dir).resolve()
    require(not output.exists(), 'existing run preserved; no same-A or shared automatic resume')
    binding, _ = runtime.ss.read_json(branch_binding_path, expected_binding_sha256)
    admission, _ = runtime.ss.read_json(binding['registration_path'], binding['registration_document_sha256'])
    _admission(config, binding, admission, output, expected_source_sha256)
    manifest, _ = runtime.ss.read_json(package / 'manifest.json', expected_manifest_sha256)
    require(manifest['evaluation_window'] == config['evaluation'], 'package evaluation differs')
    shared_cost = deepcopy(manifest['shared_cost_reference'])
    kernel = runtime.hybrid.configuration(period_seconds=1800, plan_seconds=14400, lookahead_depth=2,
        max_slots=4, solver_seconds=2.0, constructor_seconds=5.0, max_candidate_evaluations=250000)
    require(kernel['anchor_time'] == 0, 'legacy kernel zero-anchor identity changed')
    context = None; costs = _costs(); last_status = None; failure = None; interruption = None
    checkpoint = None; bundle = None; trace_anchor = None; unknown_physical_outcome = False
    try:
        require(time.monotonic() - begun <= config['wall_seconds'], 'wall cap exhausted before shared restore')
        _source_fence(runtime)
        context = runtime.context.open_shared_run(package, expected_manifest_sha256=expected_manifest_sha256,
            branch_binding_path=branch_binding_path, expected_binding_sha256=expected_binding_sha256,
            output_dir=output, expected_source_sha256=expected_source_sha256)
        _write(runtime, output / 'config.json', config)
        _write(runtime, output / 'controller_claim.json', {'pid': os.getpid(), 'identity': digest(config),
            'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'arm': 'A',
            'registration_kind': 'offline_A_admission', 'registration_document_sha256': binding['registration_document_sha256']})
        _write(runtime, output / 'admission.json', admission)
        provenance = {'declared_source_sha256': expected_source_sha256, 'M1_sha256': CONTEXT_SHA,
            'shared_package_manifest_sha256': expected_manifest_sha256, 'runtime_files': {},
            'complete_runtime_freeze_verified_here': False}
        for name, raw in runtime.sources.items():
            target = output / 'source_snapshot' / name; target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                require(stream.write(raw) == len(raw), 'short local source snapshot write')
                stream.flush(); os.fsync(stream.fileno())
            provenance['runtime_files'][name] = hashlib.sha256(raw).hexdigest()
        _write(runtime, output / 'provenance.json', provenance)
        with (output / 'resources.jsonl').open('xb'): pass
        last_status = context.status()
        require(last_status['absolute_time'] == config['evaluation']['absolute_start']
                and last_status['physical_horizon'] == config['evaluation']['physical_episode_end']
                and len(last_status['physical_scope']) == 913 and not last_status['finished'], 'restored shared start differs')
        while not last_status['finished']:
            _limits(config, output, begun)
            require(costs['planner_calls'] < config['max_plans'], 'planner call cap reached')
            index = costs['planner_calls']; clock = context.evidence()['clock']
            mode, request = runtime.context.SharedHybridClock(config['evaluation'], state=clock).request(
                last_status['absolute_time'], remaining_cp_seconds=config['solver_budget_seconds'] - costs['solver_requested_seconds'],
                periodic_request_seconds=kernel['periodic_cp_request_seconds'])
            problem = context.problem()
            require(len(problem['machines']) == 913 and set(problem['scope']) == set(last_status['physical_scope']), 'full913 public problem required')
            problem_ref = _write(runtime, output / f'problem_{index:05d}.json', problem)
            response, response_ref = _tool(problem, index=index, mode=mode, request=request, kernel=kernel,
                clock=clock, config=config, output=output, runtime=runtime, costs=costs)
            # Original disclosed projection only: this facade contains two public fields.
            projected = runtime.crop_plan(response['plan'], SimpleNamespace(
                physical=set(last_status['physical_scope']), horizon=last_status['physical_horizon']))
            raw_ref = _write(runtime, output / f'raw_plan_{index:05d}.json', response['plan'])
            projected_ref = _write(runtime, output / f'committed_plan_{index:05d}.json', projected)
            decision_ref = _write(runtime, output / f'decision_{index:05d}.json', {
                'schema': SCHEMA + '-decision', 'plan_index': index, 'problem_ref': problem_ref,
                'kernel_response_ref': response_ref, 'raw_plan_ref': raw_ref, 'projected_plan_ref': projected_ref,
                'kernel_configuration': kernel, 'effective_period_clock_before': clock,
                'mode': mode, 'projection_implementation_sha256': RUNTIME_SHA['src/smt_fullfab/runner.py'],
                'selection': 'single explicit A hybrid result; no alternate candidate or fallback'})
            _limits(config, output, begun)
            costs['commit_attempts'] += 1
            unknown_physical_outcome = True
            receipt = context.commit_exact(projected, decision_evidence_ref=decision_ref)
            costs['commit_receipts_confirmed'] += 1  # Physical success precedes any caller evidence write.
            unknown_physical_outcome = False
            require(receipt['mode_at_commit'] == mode, 'context commit mode differs from actual kernel')
            _write(runtime, output / f'commit_{index:05d}.json', {'decision_ref': decision_ref, 'context_receipt': receipt})
            unknown_physical_outcome = True
            stop = context.advance_to_boundary()  # First operation that may advance; always after explicit commit.
            costs['advance_receipts_confirmed'] += 1
            last_status = context.status(); unknown_physical_outcome = False
            _write(runtime, output / f'advance_{index:05d}.json', stop)
            del response, problem, projected
        _limits(config, output, begun)
        trace_anchor = _trace_anchor(runtime, output / 'trace.jsonl')
        _write(runtime, output / 'terminal_trace_anchor.json', trace_anchor)
        bundle = _terminal_audit(config, runtime, output, package / 'data', trace_anchor)
    except BaseException as exc:
        failure = {'type': type(exc).__name__, 'message': str(exc), 'traceback': traceback.format_exc()}
        if not isinstance(exc, Exception):
            failure['interrupted'] = True
            interruption = exc
        if output.is_dir():
            try: _write(runtime, output / 'exception.json', failure)
            except BaseException as secondary:
                failure['evidence_error'] = repr(secondary)
                if not isinstance(secondary, Exception) and interruption is None: interruption = secondary
    context_evidence = None
    if context is not None:
        context_evidence = context.evidence()
        try: checkpoint = context.write_checkpoint(output / 'checkpoint.json')
        except BaseException as exc:
            if not isinstance(exc, Exception) and interruption is None: interruption = exc
            failure = failure or {'type': type(exc).__name__, 'message': 'checkpoint: ' + str(exc)}
            if output.is_dir():
                try: _write(runtime, output / 'checkpoint_failure.json', {'type': type(exc).__name__, 'message': str(exc)})
                except BaseException as secondary:
                    failure['checkpoint_evidence_error'] = repr(secondary)
                    if not isinstance(secondary, Exception) and interruption is None: interruption = secondary
        context_evidence = context.evidence()
        try:
            _write(runtime, output / 'shared_checkpoint_resources.json', {'schema': SCHEMA + '-resources',
                'config_sha256': digest(config), 'admission_sha256': binding['registration_document_sha256'],
                'resources': costs, 'kernel_configuration': kernel, 'effective_clock': context_evidence['clock'],
                'context_evidence': context_evidence, 'shared_generation_cost_reference': shared_cost,
                'shared_generation_count_in_branch_cost': 0, 'execution_resume_authorized': False})
        except BaseException as exc:
            failure = failure or {'type': type(exc).__name__, 'message': 'resource evidence: ' + str(exc)}
            if not isinstance(exc, Exception) and interruption is None: interruption = exc
    complete = bool(last_status and last_status['finished'] and not unknown_physical_outcome)
    absolute = None if unknown_physical_outcome or last_status is None else last_status['absolute_time']
    result = {'schema': SCHEMA + '-result', 'identity': digest(config), 'config': config,
        'status': 'completed_pending_shared_audit' if complete and failure is None else 'failed', 'failure': failure,
        'package_manifest_sha256': expected_manifest_sha256, 'branch_binding_sha256': expected_binding_sha256,
        'shared_start_id': binding['shared_start_id'], 'arm': 'A', 'run_id': config['run_id'], 'seed': config['seed'],
        'absolute_start': config['evaluation']['absolute_start'], 'absolute_end': config['evaluation']['absolute_end'],
        'physical_horizon': config['evaluation']['physical_episode_end'], 'absolute_time': absolute,
        'last_confirmed_status': last_status, 'unknown_physical_outcome': unknown_physical_outcome,
        'simulation_seconds': None if absolute is None else absolute - config['evaluation']['absolute_start'],
        'full_window_completed': complete, 'model_calls': 0, 'formal': False, 'resources': costs,
        'context_evidence': context_evidence, 'checkpoint': checkpoint, 'audit_bundle': bundle,
        'first_terminal_trace_anchor': trace_anchor, 'physical_audit_valid': bool(bundle and bundle['summary']['valid']),
        'metrics': None if bundle is None else bundle['summary']['metrics'],
        'metrics_scope': 'full metrics at audit_bundle/metrics.json; explicit T0..H window, old terminal unchanged',
        'shared_generation_cost_reference': shared_cost, 'shared_generation_count_in_branch_cost': 0,
        'branch_scope_audit': None, 'shared_period_audit': None, 'arm_attribution': None,
        'acceptance_eligible': False, 'execution_resume_authorized': False,
        'wall_seconds_before_result': time.monotonic() - begun,
        'resource_scope': 'entire branch run incl restored full prefix, tool originals, audits and snapshot; outer freeze/host/exit separate, no self-acceptance'}
    if output.is_dir():
        try:
            runtime.ss.read_json(branch_binding_path, expected_binding_sha256)
            runtime.ss.read_json(binding['registration_path'], binding['registration_document_sha256'])
            runtime.ss.read_json(package / 'manifest.json', expected_manifest_sha256)
            _source_fence(runtime)
            if bundle is not None:
                final_bundle = runtime.bundle.read_bundle(output / bundle['path'],
                    expected_manifest_sha256=bundle['manifest_sha256'])
                require(final_bundle['storage_verified'] is True
                        and same(final_bundle['source_receipt'], bundle['source_receipt'])
                        and same(final_bundle['summary'], bundle['summary']), 'final bundle differs from its original audit')
            if trace_anchor is not None: _trace_fence(runtime, output / 'trace.jsonl', trace_anchor)
            _limits(config, output, begun, extra=len(canonical(result)) + 1)
        except BaseException as exc:
            if not isinstance(exc, Exception) and interruption is None: interruption = exc
            result['status'] = 'failed'; result['failure'] = result['failure'] or {'type': type(exc).__name__, 'message': 'final resource/input check: ' + str(exc)}
        _write(runtime, output / 'result.json', result)
    if interruption is not None: raise interruption
    return result


def run_A_shared(*, source_root, context_path, **arguments):
    require(not LAUNCH_BLOCKERS, 'execution blocked: ' + '; '.join(LAUNCH_BLOCKERS))
    begun = time.monotonic()
    return _run_A_shared(runtime=load_runtime(source_root, context_path), started=begun, **arguments)
