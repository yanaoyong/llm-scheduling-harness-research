"""C8 streaming controller, callable only through an external frozen gate.

The public entry cannot register or run an experiment. The external gate binds
source/runtime, parity, capacity and independent acceptance. Private results
never authorize their own execution or acceptance. Old C1 evidence is unchanged.
"""
import dataclasses
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import time
import traceback

from src.smt_fullfab import controller as legacy
from src.smt_fullfab.budget import ROOT, APPROVAL, DEFAULT_LEDGER, BudgetLedger
from src.smt_fullfab.controller_delta import account_from_rows, next_boundary
from src.smt_fullfab.environment import FullFabEnvironment
from src.smt_fullfab.interface import compact_pages
from src.smt_fullfab.model_transport_supervised import ModelConfig, call_model
from src.smt_fullfab.runner import source_snapshot, crop_plan, stream_audit, include_result_bytes
from src.smt_fullfab.stream_snapshot import write_snapshot
from src.smt_fullfab.stream_audit_bundle import read_bundle
from src.smt_fullfab.trace_source import inspect_jsonl, open_verified, scan_envelope

from .C_plan_archive import PlanArchive, digest, parse, raw_snapshot, snapshot, write_new, write_raw_new
from .C_stream_attribution_stage import audit_execution_stage, validate_sources, snapshot_sources, ATTRIBUTION_SOURCES, CONSTRUCTOR_SHA256

VERSION = 'fullfab-C8-stream-controller-v4-supervised'
BLOCKER = 'direct controller execution blocked; use the external frozen C_stream_gate'
PROPOSAL = {'arm': 'C', 'run_id': 'C_1701_8h_constructive_v3_candidate', 'seed': 1701, 'seconds': 28800,
            'max_calls': None, 'max_tokens': None, 'per_call_timeout_seconds': 180,
            'solver_method_available': 'decomposed', 'solver_budget_seconds': 32.0,
            'wall_seconds': 43200.0, 'outer_wall_seconds': 46800.0,
            'max_log_bytes': 25769803776, 'max_trace_bytes': 2147483648,
            'minimum_free_bytes': 68719476736, 'peak_rss_bytes': 8589934592,
            'peak_rss_is_final_acceptance_not_hard_guard': True,
            'plan_seconds': 14400, 'lookahead_depth': 2, 'period_seconds': 1800,
            'page_chars': 45000, 'enable_constructive': True,
            'constructor_seconds_cap': 5.0, 'constructor_evaluation_cap': 250000,
            'controller_version': legacy.C_CONSTRUCTIVE_VERSION,
            'storage_controller_version': VERSION, 'audit_mode': 'stream', 'snapshot_mode': 'stream',
            'formal': False, 'cold_start_only': True}


def validate_scope(cfg):
    """Fixed C8 semantics; a later frozen gate owns resource preregistration."""
    fixed = {'arm': 'C', 'seed': 1701, 'seconds': 28800,
        'max_calls': None, 'max_tokens': None, 'per_call_timeout_seconds': 180,
        'solver_method_available': 'decomposed', 'solver_budget_seconds': 32.0,
        'plan_seconds': 14400, 'lookahead_depth': 2, 'period_seconds': 1800,
        'page_chars': 45000, 'enable_constructive': True,
        'constructor_seconds_cap': 5.0, 'constructor_evaluation_cap': 250000,
        'controller_version': legacy.C_CONSTRUCTIVE_VERSION,
        'storage_controller_version': VERSION, 'audit_mode': 'stream', 'snapshot_mode': 'stream',
        'formal': False, 'cold_start_only': True}
    for key, expected in fixed.items():
        if key not in cfg or digest(cfg[key]) != digest(expected):
            raise ValueError('fixed C8 scope differs: ' + key)
    if type(cfg.get('wall_seconds')) not in (int, float) or not math.isfinite(cfg['wall_seconds']) or cfg['wall_seconds'] <= 0:
        raise ValueError('finite positive configured child wall cap required')
    for key in ('max_trace_bytes', 'max_log_bytes'):
        if type(cfg.get(key)) is not int or cfg[key] <= 0:
            raise ValueError('positive configured byte cap required: ' + key)


def registration_parameters(cfg, out):
    validate_scope(cfg)
    return {'run_id': str(Path(out).resolve()), 'arm': cfg['arm'], 'scenario': cfg['seed'],
        'window_seconds': cfg['seconds'], 'solver_seconds': cfg['solver_budget_seconds'],
        'wall_seconds': cfg['wall_seconds'], 'max_log_bytes': cfg['max_log_bytes']}


def validate_registration(cfg, out, registration):
    expected = {**registration_parameters(cfg, out), 'budget_id': cfg['budget_id'],
        'amendment_id': cfg['amendment_id'], 'phase': 'stage2_research', 'formal': False}
    if any(key not in registration or digest(registration[key]) != digest(value) for key, value in expected.items()):
        raise ValueError('immutable registration differs from actual configuration')


def claim_record(cfg):
    return {'identity': digest(cfg), 'pid': os.getpid(),
        'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'mode': 'new cold run; never automatic retry'}


def commit_and_count(env, committed, counts):
    # No persistence or unrelated fallible call may precede the increment after
    # a successful shared commit. The current plan_index is a separate cursor.
    env.commit_plan(committed)
    counts['committed_plans'] += 1


def record_constructor_inner_cost(costs, value):
    if value is None:
        costs['constructor_inner_wall_seconds_unknown_count'] += 1
    elif type(value) in (int, float) and math.isfinite(value) and value >= 0:
        costs['constructor_inner_wall_seconds_known_sum'] += value
    else:
        raise ValueError('invalid reported constructor inner duration')


def trace_receipt(seal):
    return {key: getattr(seal, key) for key in
        ('sha256', 'byte_count', 'line_count', 'event_count', 'max_record_bytes')}


def require_trace_receipt(original, actual, *, phase):
    if type(actual) is not dict or digest(actual) != digest(original):
        raise ValueError(phase + ' source differs from first terminal trace anchor')


def require_attribution_trace(original, attribution):
    if attribution.get('attribution_report', {}).get('evidence_sha256', {}).get('trace.jsonl') != original['sha256']:
        raise ValueError('attribution trace differs from first terminal trace anchor')


def sha_file(path):
    sha = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def byte_count(out):
    return sum(p.stat().st_size for p in Path(out).rglob('*') if p.is_file())


def total_storage_bytes(out, scratch_dir=None):
    return byte_count(out) + (0 if scratch_dir is None else byte_count(scratch_dir))


def check_resources(out, cfg, started, *, scratch_dir=None):
    if time.monotonic() - started >= cfg['wall_seconds']:
        raise TimeoutError('C8 complete child phase wall cap')
    if total_storage_bytes(out, scratch_dir) >= cfg['max_log_bytes']:
        raise RuntimeError('C8 total log cap')
    trace = Path(out) / 'trace.jsonl'
    if trace.exists() and trace.stat().st_size > cfg['max_trace_bytes']:
        raise RuntimeError('C8 raw trace cap')


def directory(problem, manifest, pages, horizon):
    return {'time': problem['time'], 'horizon_end': problem['horizon_end'], 'observation_end': horizon,
            'problem_metadata': manifest['problem_metadata'], 'machines': len(problem['machines']),
            'operations': len(problem['operations']), 'pages': len(pages),
            'family_counts': [{'family': g['family'], 'machines': len(g['machines']), 'operations': len(g['operations'])}
                              for page in pages for g in page],
            'methods_available': ['global', 'decomposed', 'constructive']}


def prompt_from_archive(summary, archive, limits):
    # Preserve the entire current observation's old-format own history. No
    # summary, pruning, quality selection or automatic memory is inserted.
    history = archive.history_for_prompt()
    return (legacy.C_CONSTRUCTIVE_PROMPT + '\nSTATE_DIRECTORY\n' + json.dumps(summary, separators=(',', ':'))
            + '\nOWN_HISTORY\n' + json.dumps(history, separators=(',', ':'))
            + '\nLIMITS\n' + json.dumps(limits))


def tool_parameters(response, run_id, plan_index):
    return {'time_limit_seconds': response['seconds'], 'seed': response['seed'], 'weights': response['weights'],
            'max_slots_per_machine': response['slots'], 'plan_version': run_id + ':' + str(plan_index)}


def _invoke_tool(problem, response, *, cfg, out, ledger, plan_index, model_index, call_id,
                 solver_index, constructor_index, remaining_active):
    """Exactly the shared tool chosen by this original model output, once."""
    params = tool_parameters(response, cfg['run_id'], plan_index)
    method = response['method']
    if method == 'constructive':
        legacy.validate_constructor_request(response, remaining_active)
        from src.smt_fullfab.constructive_tool import solve_constructive_plan
        meta = {'model_call_id': call_id, 'model_index': model_index, 'plan_index': plan_index,
                'problem_sha256': digest(problem), 'max_candidate_evaluations': 250000,
                'max_slots_per_machine': response['slots'], 'method': method,
                'actual_constructor_module': 'src.smt_fullfab.constructive_tool',
                'actual_constructor_function': 'solve_constructive_plan'}
        cid = ledger.reserve_constructor(arm='C', run_id=str(out), requested_seconds=response['seconds'], metadata=meta)
        evidence = {**meta, 'constructor_index': constructor_index, 'constructor_call_id': cid,
                    'call_id': call_id, 'requested_seconds': response['seconds']}
        write_new(out / f'constructor_request_{constructor_index:03d}.json', {'response': response, 'parameters': params, **evidence})
        started = time.monotonic()
        outcome = 'success'
        try:
            result = solve_constructive_plan(problem, **params)
        except Exception as exc:
            outcome = 'failed'
            result = {'record_type': 'constructor_exception', 'solver_status': 'CONSTRUCTOR_EXCEPTION',
                      'plan': None, 'tasks': [], 'unplanned_operations': {op['operation_id']: 'constructor_exception' for op in problem['operations']},
                      'error': f'{type(exc).__name__}: {exc}', 'nominal_audit': None, 'best_bound': None,
                      'global_optimality_claim': False, 'cp_sat': {'status': 'NOT_RUN_BY_POLICY', 'calls': 0, 'requested_seconds': 0},
                      'classical_construction_wall_seconds': None}
        duration = time.monotonic() - started
        result.update(requested_method=method, constructor_call_id=cid, invocation_duration_seconds=duration)
        path = out / f'constructor_{constructor_index + 1:03d}.json'
        legacy.write_constructor_result(path, result)  # Original complete result before finish.
        ledger.finish_constructor(cid, outcome, {'duration_seconds': duration, 'solver_status': result['solver_status'],
                                                'constructor_result_sha256': digest(result)})
        legacy.append_record(out / 'constructor_evidence.jsonl', {**evidence, 'status': outcome,
            'duration_seconds': duration, 'constructor_result_sha256': digest(result)})
        return result, path, {'method': method, 'index': constructor_index, 'call_id': cid,
                             'duration_seconds': duration, 'requested_seconds': response['seconds']}
    remaining_cp = ledger.solver_remaining_seconds('C', run_id=str(out))
    legacy.validate_solver_request(response, min(remaining_cp, remaining_active))
    if method == 'global':
        from src.smt_fullfab.optimizer import solve_plan
        tool_module, function = 'src.smt_fullfab.optimizer', 'solve_plan'
    elif method == 'decomposed':
        from src.smt_fullfab.decomposition import solve_decomposed_plan as solve_plan
        tool_module, function = 'src.smt_fullfab.decomposition', 'solve_decomposed_plan'
    else:
        raise ValueError('unlisted explicit C method')
    cid = ledger.reserve_solver(arm='C', run_id=str(out), requested_seconds=response['seconds'])
    evidence = {'solver_index': solver_index, 'solver_call_id': cid, 'model_index': model_index,
                'call_id': call_id, 'plan_index': plan_index, 'requested_seconds': response['seconds'],
                'method': method, 'actual_solver_module': tool_module, 'actual_solver_function': function}
    write_new(out / f'solver_request_{solver_index:03d}.json',
              {'response': response, 'parameters': params, 'problem_sha256': digest(problem), **evidence})
    started = time.monotonic()
    try:
        result = solve_plan(problem, **params)
    except Exception as exc:
        failed = {'error': str(exc), 'duration_seconds': time.monotonic() - started}
        # Original failure is retained. There is no fallback tool call.
        write_new(out / f'solver_failure_{solver_index:03d}.json', failed)
        ledger.finish_solver(cid, 'failed', failed)
        legacy.append_record(out / 'solver_evidence.jsonl', {**evidence, 'status': 'failed', 'solver_result_sha256': None, **failed})
        raise
    result['requested_method'] = method
    path = out / f'solver_{solver_index + 1:03d}.json'
    write_new(path, result)  # Persist before the terminal accounting record.
    ledger.finish_solver(cid, 'success', {'solver_status': result['solver_status'], 'wall_seconds': result['wall_seconds']})
    legacy.append_record(out / 'solver_evidence.jsonl', {**evidence, 'status': 'success', 'solver_result_sha256': digest(result)})
    return result, path, {'method': method, 'index': solver_index, 'call_id': cid,
                         'duration_seconds': time.monotonic() - started, 'requested_seconds': response['seconds']}


def feedback_for_candidate(result, index, cost):
    valid, feedback = legacy.candidate_feedback(result, index, strict_nominal=cost['method'] == 'constructive')
    if cost['method'] == 'constructive':
        feedback.update(method='constructive', constructor_index=cost['index'], constructor_call_id=cost['call_id'],
                        constructor_requested_seconds=cost['requested_seconds'], constructor_duration_seconds=cost['duration_seconds'],
                        classical_construction_wall_seconds=result.get('classical_construction_wall_seconds'),
                        nominal_audit=result.get('nominal_audit'), seed_semantics=result.get('seed_semantics'), error=result.get('error'))
    return valid, feedback


def _account_snapshot(out, ledger, ledger_path):
    """Real original reserves/finishes, never model-loop counters or filled usage."""
    raw, receipt = raw_snapshot(ledger_path)
    rows = [parse(line) for line in raw.splitlines() if line.strip()]
    domain = account_from_rows(rows, out)
    account = ledger.summary(run_id=str(out))
    if digest(account) != digest(domain['account']):
        raise ValueError('summary differs from actual original run ledger')
    ids = set(domain['solver_call_ids'])
    cp = [r for r in rows if r.get('event') == 'solver_reserve' and r.get('call_id') in ids]
    value = {**domain, 'solver_requested_seconds': sum(r['requested_seconds'] for r in cp),
             'ledger_sha256': receipt['sha256'], 'ledger_source_path': str(Path(ledger_path).resolve())}
    write_raw_new(out / 'ledger_final.jsonl', raw)
    value['account_report_sha256'] = write_new(out / 'ledger_final_account.json', value)
    return value


def read_account_evidence(out, *, ledger_path, expected_report_sha256):
    """Same-domain suffixes reject; unrelated research runs may append."""
    value, _ = snapshot(Path(out) / 'ledger_final_account.json', expected_report_sha256)
    if value['ledger_source_path'] != str(Path(ledger_path).resolve()):
        raise ValueError('original ledger path changed')
    saved, _ = raw_snapshot(Path(out) / 'ledger_final.jsonl', value['ledger_sha256'])
    live, _ = raw_snapshot(ledger_path)
    if not live.startswith(saved):
        raise ValueError('original ledger prefix changed')
    prior = account_from_rows([parse(line) for line in saved.splitlines() if line.strip()], out)
    current = account_from_rows([parse(line) for line in live.splitlines() if line.strip()], out)
    if digest(prior) != digest(current) or any(digest(value[k]) != digest(prior[k]) for k in prior):
        raise ValueError('same run/registration/call acquired ledger suffix; original costs not re-anchored')
    return value


def audit_periods(trace_path, rows, *, expected_trace_sha256, horizon, period=1800):
    """Additional independent absolute-boundary check; full EOF, no simulator."""
    for index, row in enumerate(rows):
        if type(row.get('plan_index')) is not int or row['plan_index'] != index or type(row.get('trace_event_index')) is not int:
            raise ValueError('exact integer period/trace indices required')
        values = [row.get(k) for k in ('start_time', 'stop_time', 'advance_target')]
        if (not all(type(v) in (int, float) and math.isfinite(v) for v in values)
                or not 0 <= values[0] <= values[1] <= values[2] <= horizon):
            raise ValueError('invalid bounded period times')
    seal = inspect_jsonl(trace_path, expected_sha256=expected_trace_sha256)
    envelope = scan_envelope(seal, require_terminal=True)
    if envelope.snapshot_count or envelope.first_time != 0 or envelope.horizon != horizon:
        raise ValueError('cold window trace required')
    commit_index = -1
    observed_stop = 0
    with open_verified(seal) as reader:
        for rec in reader:
            event = rec.event
            if event['kind'] == 'time_advance' and (type(event.get('to')) not in (int, float)
                    or not math.isfinite(event['to']) or event['to'] < event['time']):
                raise ValueError('invalid time advance endpoint')
            if event['kind'] == 'plan_committed':
                if commit_index >= 0 and observed_stop != rows[commit_index]['stop_time']:
                    raise ValueError('next plan does not start at preceding executor stop')
                commit_index += 1
                if commit_index >= len(rows):
                    raise ValueError('commit lacks period receipt')
                row = rows[commit_index]
                if (row['plan_index'] != commit_index or row['trace_event_index'] != rec.event_index
                        or row['start_time'] != event['time']
                        or row['advance_target'] != next_boundary(event['time'], 0.0, horizon, period)):
                    raise ValueError('absolute execution boundary/commit differs')
            if commit_index >= 0:
                row = rows[commit_index]
                if event['time'] > row['advance_target'] or (event['kind'] == 'time_advance' and event['to'] > row['advance_target']):
                    raise ValueError('executor skipped absolute period boundary')
            observed_stop = max(observed_stop, event['time'], event['to'] if event['kind'] == 'time_advance' else event['time'])
    if commit_index + 1 != len(rows) or not rows or rows[-1]['stop_time'] != horizon or observed_stop != horizon:
        raise ValueError('period receipts do not close the complete window')
    return {'valid': True, 'committed_plans': len(rows), 'source_receipt': dataclasses.asdict(envelope.receipt),
            'scope': 'absolute-period-and-commit-indices-only', 'physical_audit_performed': False,
            'model_attribution_audit_performed': False}


def _implementation_draft(*, run_id, root=ROOT, ledger_path=DEFAULT_LEDGER, approval_path=APPROVAL,
                          attribution_source_dir, expected_attribution_sources, constructor_source,
                          expected_constructor_sha256, attribution_scratch_dir):
    """Not a public launch API; public run() remains unconditionally blocked.

    This body demonstrates complete proposed storage/period/finalization wiring.
    It MUST NOT be invoked with real components until attribution parity/readback
    evidence and installation are independently bound by an approved frozen gate.
    """
    started = time.monotonic()
    root, ledger_path = Path(root).resolve(), Path(ledger_path).resolve()
    if type(run_id) is not str or not run_id.startswith('C_') or any(not (c.isascii() and (c.isalnum() or c in '_-')) for c in run_id):
        raise ValueError('new C run ID required')
    approval, _ = snapshot(approval_path)
    if approval['model'] != 'gpt-6-astra' or approval['reasoning_effort'] != 'medium':
        raise ValueError('unchanged approved C model/effort required')
    ledger = BudgetLedger(ledger_path)
    waiver = ledger.research_limit_waiver()
    if waiver is None:
        raise ValueError('existing explicit research waiver required; no new call/token cap')
    cfg = {k: v for k, v in PROPOSAL.items() if k not in ('outer_wall_seconds', 'minimum_free_bytes', 'peak_rss_bytes', 'peak_rss_is_final_acceptance_not_hard_guard')}
    cfg.update(run_id=run_id, budget_id=approval['budget_id'], amendment_id=waiver['amendment_id'])
    validate_scope(cfg)
    out = root / 'runs/smt_fullfab_stage2' / run_id
    scratch = Path(attribution_scratch_dir).resolve()
    if scratch == out or scratch in out.parents or out in scratch.parents or scratch.exists():
        raise ValueError('new attribution scratch must be outside original run')
    source_binding = validate_sources(attribution_source_dir, expected_attribution_sources,
        constructor_source=constructor_source, expected_constructor_sha256=expected_constructor_sha256)
    scratch.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=False)
    write_new(out / 'config.json', cfg)
    write_new(out / 'claim.json', claim_record(cfg))
    write_new(out / 'attribution_source_binding.json', source_binding)
    env, failure, physical, bundle = None, None, None, None
    model_index = plan_index = solver_index = constructor_index = 0
    transport_entries = 0
    returned_model_calls = 0
    execution_counts = {'committed_plans': 0}
    scalar_costs = {'constructor_inner_wall_seconds_known_sum': 0.0,
                    'constructor_inner_wall_seconds_unknown_count': 0, 'tool_outer_wall_seconds': 0.0}
    registration = None
    try:
        registration = ledger.register_stage_run(**registration_parameters(cfg, out))
        validate_registration(cfg, out, registration)
        write_new(out / 'resource_registration.json', registration)
        provenance = source_snapshot(out)
        bound_attribution_dir, added_sources = snapshot_sources(out, source_binding)
        provenance['source_sha256'].update(added_sources)
        write_new(out / 'provenance.json', provenance)
        env = FullFabEnvironment(seed=cfg['seed'], window_seconds=cfg['seconds'], trace_path=out / 'trace.jsonl')
        while not env.finished:
            check_resources(out, cfg, started, scratch_dir=scratch)
            problem = env.problem(plan_seconds=cfg['plan_seconds'], lookahead_depth=cfg['lookahead_depth'])
            if len(problem['machines']) != 913 or set(problem['scope']) != env.physical:
                raise ValueError('complete 913 production machine problem required')
            write_new(out / f'problem_{plan_index:03d}.json', problem)
            compact = compact_pages(problem, max_chars=cfg['page_chars'])
            pages = compact.pop('pages')
            compact.update(page_count=len(pages), observation_end=env.horizon)
            write_new(out / f'page_manifest_{plan_index:03d}.json', compact)
            for i, page in enumerate(pages):
                write_new(out / f'page_{plan_index:03d}_{i:02d}.json', page)
            archive = PlanArchive(out / f'plan_archive_{plan_index:03d}', run_dir=out, plan_index=plan_index)
            summary = directory(problem, compact, pages, env.horizon)
            plan = None
            while plan is None:
                check_resources(out, cfg, started, scratch_dir=scratch)
                remaining = ledger.solver_remaining_seconds('C', run_id=str(out))
                active_remaining = ledger.constructor_remaining_seconds('C', run_id=str(out))
                account = ledger.summary(run_id=str(out))
                limits = {'responses': None, 'solver_seconds': remaining,
                          'model_active_seconds_remaining': active_remaining, 'per_request_solver_seconds': min(60, remaining),
                          'per_request_constructor_seconds': min(5.0, max(0, active_remaining)),
                          'constructor_requested_seconds': account['constructor_requested_seconds'],
                          'constructor_active_seconds': account['constructor_active_seconds'], 'constructor_evaluation_cap': 250000}
                prompt = prompt_from_archive(summary, archive, limits)
                timeout = min(180.0, active_remaining, cfg['wall_seconds'] - (time.monotonic() - started))
                if timeout < 1:
                    raise TimeoutError('no remaining registered model/constructor wall')
                mcfg = ModelConfig(model=approval['model'], reasoning_effort=approval['reasoning_effort'], timeout_seconds=timeout,
                    ledger_path=str(ledger_path), phase='stage2_research', grant_id=approval['budget_id'],
                    authorization_context={'purpose': 'C', 'arm': 'C', 'scenario': cfg['seed'], 'window_seconds': cfg['seconds']})
                current_index = model_index
                # Full original transport artifacts remain under the existing names.
                transport_entries += 1
                returned = call_model(prompt, legacy.C_CONSTRUCTIVE_SCHEMA, out / f'model_{current_index:03d}', mcfg)
                returned_model_calls += 1
                call_id, response = returned['call_id'], returned['output']
                legacy.append_record(out / 'controller_decisions.jsonl', {'model_index': current_index, 'call_id': call_id,
                    'plan_index': plan_index, 'arm': 'C', 'stage': 'C_action', 'page_index': None,
                    'input_problem_sha256': digest(problem), 'response_sha256': digest(response), 'status': returned['status']})
                model_index += 1
                if returned['status'] != 'success':
                    raise RuntimeError('original model channel failed: ' + str(returned.get('failure_reason')))
                del returned, prompt
                if response['action'] == 'read_page':
                    i = response['index']
                    if type(i) is not int or not 0 <= i < len(pages):
                        raise ValueError('invalid explicitly requested page')
                    entry = {'decision': response, 'page': pages[i], 'schema': compact}
                elif response['action'] == 'solve':
                    solved, path, cost = _invoke_tool(problem, response, cfg=cfg, out=out, ledger=ledger,
                        plan_index=plan_index, model_index=current_index, call_id=call_id, solver_index=solver_index,
                        constructor_index=constructor_index,
                        remaining_active=min(ledger.constructor_remaining_seconds('C', run_id=str(out)), cfg['wall_seconds'] - (time.monotonic() - started)))
                    original_candidate_sha256 = digest(solved)
                    if cost['method'] == 'constructive':
                        constructor_index += 1
                        record_constructor_inner_cost(scalar_costs, solved.get('classical_construction_wall_seconds'))
                    else:
                        solver_index += 1
                    scalar_costs['tool_outer_wall_seconds'] += cost['duration_seconds']
                    index = len(archive.candidate_hashes)
                    valid, feedback = feedback_for_candidate(solved, index, cost)
                    archive.record_candidate(path=path, expected_candidate_sha256=original_candidate_sha256, valid=valid,
                        feedback=feedback, method=cost['method'], model_index=current_index, call_id=call_id)
                    entry = {'decision': response, 'result': feedback}
                    del solved  # No global candidate/result list survives a tool call.
                elif response['action'] == 'apply':
                    selected, reference = archive.load_explicit_candidate(response['index'])
                    plan = selected['plan']
                    entry = {'decision': response, 'applied_candidate': response['index'], 'plan_sha256': digest(plan)}
                    del selected
                else:
                    raise ValueError('unknown explicit C action')
                archive.append_history(entry)
                legacy.append_record(out / 'controller_history_events.jsonl', {'plan_index': plan_index, 'model_index': current_index, 'entry': entry})
            archive.close(out / f'controller_history_{plan_index:03d}.json')
            check_resources(out, cfg, started, scratch_dir=scratch)
            write_new(out / f'raw_plan_{plan_index:03d}.json', plan)
            committed = crop_plan(plan, env)  # Existing disclosed C/shared-tool clipping, unchanged.
            trace_index, start_time = len(env.trace), env.t
            write_new(out / f'commit_intent_{plan_index:03d}.json', {'plan_index': plan_index, 'model_call_id': call_id,
                'selected_candidate_index': response['index'], 'raw_plan_sha256': digest(plan),
                'committed_plan_sha256': digest(committed), 'trace_event_index': trace_index,
                'unknown_outcome_must_stop': True})
            commit_and_count(env, committed, execution_counts)
            legacy.append_record(out / 'plan_commits.jsonl', {'plan_index': plan_index, 'model_call_id': call_id,
                'raw_plan_sha256': digest(plan), 'committed_plan_sha256': digest(committed)})
            target = next_boundary(env.t, env.observation_start, env.horizon, cfg['period_seconds'])
            write_new(out / f'advance_intent_{plan_index:03d}.json', {'plan_index': plan_index,
                'trace_event_index': trace_index, 'start_time': start_time, 'advance_target': target})
            committed_index = plan_index
            plan_index += 1  # A later failed advance must not erase a successful commit.
            stop = env.advance_plan(target)
            legacy.append_record(out / 'period_receipts.jsonl', {'plan_index': committed_index, 'trace_event_index': trace_index,
                'start_time': start_time, 'advance_target': target, 'stop_time': env.t, 'stop': stop})
            del archive, problem, compact, pages, plan, committed, summary
    except BaseException as exc:
        failure = {'type': type(exc).__name__, 'message': str(exc), 'traceback': traceback.format_exc()}
        write_new(out / 'failure.json', failure)
    # Immutable execution stage, followed by full independent audits, then a
    # separate final result. The old result is never rewritten after auditing.
    account = None
    if registration:
        try:
            account = _account_snapshot(out, ledger, ledger_path)
            if any(account['account'][key] for key in ('pending', 'pending_solver_calls', 'pending_constructor_calls')):
                raise ValueError('unfinished original call/tool reservation; never repaired or retried')
        except Exception as exc:
            failure = failure or {'type': type(exc).__name__, 'message': 'ledger finalization: ' + str(exc)}
    checkpoint = None
    if env is not None:
        try:
            checkpoint = {'path': 'checkpoint.json', 'state_sha256': write_snapshot(env, out / 'checkpoint.json')}
            checkpoint['file_sha256'] = sha_file(out / 'checkpoint.json')
        except Exception as exc:
            failure = failure or {'type': type(exc).__name__, 'message': 'snapshot: ' + str(exc)}
    execution = {'identity': digest(cfg), 'config': cfg, 'status': 'awaiting_attribution' if env and env.finished and not failure else 'failed',
        'failure': failure, 'plans_committed': execution_counts['committed_plans'], 'simulation_seconds': None if env is None else env.t,
        'full_window_completed': bool(env and env.finished), 'model_calls': None if account is None else account['account']['attempts'],
        'model_call_ids': None if account is None else account['reserve_call_ids'],
        'solver_calls': None if account is None else len(account['solver_call_ids']),
        'solver_requested_seconds': None if account is None else account['solver_requested_seconds'],
        'constructor_calls': None if account is None else account['account']['constructor_calls'],
        'constructor_requested_seconds': None if account is None else account['account']['constructor_requested_seconds'],
        'constructor_active_seconds': None if account is None else account['account']['constructor_active_seconds'],
        'wall_seconds': time.monotonic() - started, 'formal': False, 'accepted': False,
        'transport_entries': transport_entries, 'returned_model_calls': returned_model_calls,
        'ledger_final_account_sha256': None if account is None else account['account_report_sha256'],
        'scalar_costs': scalar_costs, 'checkpoint': checkpoint}
    execution_sha = write_new(out / 'execution_result.json', execution)
    attribution, periods, trace_anchor = None, None, None
    terminal_binding_valid = False
    if env is not None and env.finished and failure is None:
        try:
            trace_seal = inspect_jsonl(out / 'trace.jsonl')
            trace_anchor = trace_receipt(trace_seal)
            trace_anchor_sha = write_new(out / 'terminal_trace_anchor.json', {
                'schema': 'draft-C8-first-terminal-trace-anchor-v1', 'source_receipt': trace_anchor,
                'file_identity': list(trace_seal.file_identity)})
            physical, bundle = stream_audit(out / 'trace.jsonl', out, data_dir=env.data_dir, window_start=env.observation_start)
            checked_bundle = read_bundle(out / bundle['path'], expected_manifest_sha256=bundle['manifest_sha256'])
            require_trace_receipt(trace_anchor, checked_bundle['source_receipt'], phase='physical bundle')
            if checked_bundle['storage_verified'] is not True or checked_bundle['summary'] != physical:
                raise ValueError('physical bundle summary differs from initial verified result')
            period_rows = [json.loads(line) for line in (out / 'period_receipts.jsonl').read_text().splitlines() if line.strip()]
            periods = audit_periods(out / 'trace.jsonl', period_rows, expected_trace_sha256=trace_anchor['sha256'],
                horizon=env.horizon, period=cfg['period_seconds'])
            require_trace_receipt(trace_anchor, periods['source_receipt'], phase='period audit')
            write_new(out / 'period_audit.json', periods)
            attribution = audit_execution_stage(out, ledger_path=ledger_path,
                attribution_source_dir=bound_attribution_dir, expected_attribution_sources=expected_attribution_sources,
                constructor_source=bound_attribution_dir / 'constructor_stream.py', expected_constructor_sha256=expected_constructor_sha256,
                expected_execution_result_sha256=execution_sha, scratch_dir=scratch, expected_trace_receipt=trace_anchor)
            require_attribution_trace(trace_anchor, attribution)
            final_trace_seal = inspect_jsonl(out / 'trace.jsonl', expected_sha256=trace_anchor['sha256'])
            require_trace_receipt(trace_anchor, trace_receipt(final_trace_seal), phase='final trace')
            if final_trace_seal.file_identity != trace_seal.file_identity:
                raise ValueError('terminal trace identity changed between independent phases')
            attribution['first_terminal_trace_anchor_sha256'] = trace_anchor_sha
            attribution['first_terminal_trace_receipt'] = trace_anchor
            write_new(out / 'controller_attribution_stage.json', attribution)
            if not physical['valid'] or not physical['complete_physical_window_certified'] or not attribution['valid']:
                raise ValueError('independent physical/attribution audit rejected')
            terminal_binding_valid = True
        except Exception as exc:
            failure = failure or {'type': type(exc).__name__, 'message': 'terminal independent audit: ' + str(exc)}
    try:
        check_resources(out, cfg, started, scratch_dir=scratch)
        if account is not None:
            read_account_evidence(out, ledger_path=ledger_path, expected_report_sha256=account['account_report_sha256'])
    except Exception as exc:
        failure = failure or {'type': type(exc).__name__, 'message': 'terminal costs: ' + str(exc)}
    result = {**execution, 'status': 'success' if env and env.finished and not failure else 'failed',
        'failure': None if failure is None else failure['type'] + ': ' + failure['message'],
        'failure_details': failure, 'execution_result_sha256': execution_sha, 'audit_bundle': bundle,
        'first_terminal_trace_receipt': trace_anchor,
        'attribution_source_binding': source_binding,
        'attribution_scratch': {'path': str(scratch), 'bytes': byte_count(scratch), 'retained': True},
        'storage_measurement_scope': 'run tree plus separate attribution scratch; final result bytes estimated before publication',
        'terminal_trace_binding_valid': terminal_binding_valid,
        'audit_valid': bool(terminal_binding_valid and physical and physical['valid'] and attribution and attribution['valid'] and periods and periods['valid']),
        'metrics': None if physical is None else physical['metrics'], 'wall_seconds': time.monotonic() - started,
        # Retained compatibility field: a controller never grants itself launch authority.
        'real_C8_launch_authorized': False,
        'launch_authority_scope': 'controller_does_not_self_authorize',
        'acceptance_authority': 'external_frozen_gate', 'direct_public_execution_enabled': False,
        'wall_scope': 'all child phases through initial result encoding; final publication/hash/stdout/process exit belong to outer gate'}
    include_result_bytes(result, existing_bytes=total_storage_bytes(out, scratch), limit=cfg['max_log_bytes'])
    result['wall_seconds'] = time.monotonic() - started
    if result['wall_seconds'] > cfg['wall_seconds']:
        result.update(status='failed', failure=result['failure'] or 'final wall cap')
    include_result_bytes(result, existing_bytes=total_storage_bytes(out, scratch), limit=cfg['max_log_bytes'])
    write_new(out / 'result.json', result)
    return result


def run(*args, **kwargs):
    raise RuntimeError(BLOCKER)  # No flag or env var bypasses the external gate.


if __name__ == '__main__':
    print(json.dumps({'proposal': PROPOSAL, 'execution_blocked': BLOCKER}, ensure_ascii=False, indent=2))
