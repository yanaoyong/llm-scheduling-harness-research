"""Prepare immutable evidence for a stopped B v2 first-plan recovery.

This module never invokes a model, optimizer, dispatch, or clock advance. It
accepts only a failed cold-start run with a completely closed ledger. Restoring
later physical states and actually resuming the controller are separate work.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from .controller_audit import (audit_controller, digest, sha_file, _record_digest,
                               _schema_errors, _sections)

ROOT = Path(__file__).resolve().parents[2]
VERSION = 'smt-fullfab-B-page-recovery-prepare-v1'


def _read(path, lines=False):
    text = Path(path).read_text()
    return [json.loads(line) for line in text.splitlines() if line.strip()] if lines else json.loads(text)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _inventory(run):
    result = {}
    for path in sorted(run.rglob('*')):
        if path.is_symlink():
            raise ValueError('run contains a symbolic link: ' + str(path.relative_to(run)))
        if path.is_file():
            result[str(path.relative_to(run))] = {'sha256': sha_file(path), 'bytes': path.stat().st_size}
    return result


def _dead_claim(run, cfg):
    claim = _read(run / 'claim.json')
    if claim.get('identity') != digest(cfg) or type(claim.get('pid')) is not int or claim['pid'] <= 0:
        raise ValueError('invalid original run process claim')
    try:
        os.kill(claim['pid'], 0)
    except ProcessLookupError:
        return
    except PermissionError:
        pass
    raise ValueError('original process may still be alive; preparation requires a stopped run')


def _schema_from_frozen_source(run):
    tree = ast.parse((run / 'source_snapshot/src/smt_fullfab/controller.py').read_text())
    nodes = [node.value for node in tree.body if isinstance(node, ast.Assign)
             and any(isinstance(target, ast.Name) and target.id == 'B_SCHEMA' for target in node.targets)]
    if len(nodes) != 1:
        raise ValueError('frozen controller has no unique literal B_SCHEMA')
    return ast.literal_eval(nodes[0])


def _verify_cold_checkpoint(run, cfg, snapshot, problem):
    """Reconstruct initial state under archived code, without advancing it.

    Comparing the entire cold state also checks its private event queue; a
    snapshot's self-reported hash or public problem alone is insufficient.
    """
    frozen = run / 'source_snapshot'
    provenance = _read(run / 'provenance.json')
    if provenance.get('requirements_sha256') != sha_file(ROOT / 'requirements.lock'):
        raise ValueError('locked runtime dependencies differ from original provenance')
    if sha_file(frozen / 'src/__init__.py') != sha_file(ROOT / 'src/__init__.py'):
        raise ValueError('unlisted root package initializer differs from locked workspace source')
    dependencies = snapshot.get('implementation_sha256')
    if not isinstance(dependencies, dict) or not dependencies:
        raise ValueError('checkpoint has no implementation dependency inventory')
    for name, expected in dependencies.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('unsafe checkpoint dependency path')
        path = (ROOT if name.startswith('vendor/') else frozen) / relative
        if not path.is_file() or sha_file(path) != expected:
            raise ValueError('checkpoint frozen dependency mismatch: ' + name)
        if not name.startswith('vendor/') and provenance['source_sha256'].get(name) != expected:
            raise ValueError('checkpoint implementation differs from archived provenance: ' + name)
    physics = frozen / 'src/smt/environment.py'
    if sha_file(physics) != snapshot.get('physics_sha256'):
        raise ValueError('checkpoint physics source mismatch')
    code = r'''
import json, sys
from pathlib import Path
from src.smt_fullfab.environment import FullFabEnvironment, digest
run=Path(sys.argv[1]); cfg=json.loads((run/'config.json').read_text())
v=json.loads((run/'checkpoint.json').read_text())
fresh=FullFabEnvironment(seed=cfg['seed'],window_seconds=cfg['seconds'])
fresh.snapshot('cold.json')
cold=json.loads(Path('cold.json').read_text())
if cold != v: raise ValueError('checkpoint differs from exact frozen cold initial state')
env=FullFabEnvironment.from_snapshot(run/'checkpoint.json')
problem=env.problem(plan_seconds=cfg['plan_seconds'],lookahead_depth=cfg['lookahead_depth'])
original=json.loads((run/'problem_000.json').read_text())
if digest(problem)!=digest(original): raise ValueError('restored problem differs from saved model observation')
env.snapshot('roundtrip.json')
s=json.loads(Path('roundtrip.json').read_text())['state']
e=s['trace'].pop()
if e['kind']!='snapshot_loaded' or digest(s)!=v['state_sha256']:
    raise ValueError('checkpoint roundtrip changed physical state')
print(json.dumps({'valid':True,'mode':'exact-frozen-cold-state-and-public-problem',
    'state_sha256':v['state_sha256'],'problem_sha256':digest(problem),
    'simulation_seconds':env.t,'model_calls':0,'solver_calls':0,'clock_advances':0}))
'''
    with tempfile.TemporaryDirectory(prefix='smt_B_prepare_') as temp:
        work = Path(temp)
        shutil.copytree(frozen / 'src', work / 'src')
        for name in ('vendor', 'data'):
            (work / name).symlink_to(ROOT / name, target_is_directory=True)
        completed = subprocess.run([sys.executable, '-c', code, str(run)], cwd=work,
            env={**os.environ, 'PYTHONPATH': str(work), 'PYTHONDONTWRITEBYTECODE': '1'},
            capture_output=True, text=True, timeout=45)
    if completed.returncode:
        raise ValueError('frozen cold checkpoint verification failed: ' + completed.stderr[-2000:])
    report = json.loads(completed.stdout)
    if report.get('valid') is not True or report.get('problem_sha256') != digest(problem):
        raise ValueError('cold checkpoint verifier did not certify exact problem')
    return report


def _choice_errors(problem, tasks, holds, observation_end):
    """Independent exact identity/batch/sequence validation; no task repairs."""
    errors, seen, sequences, hold_keys = [], set(), set(), set()
    operations = {row['operation_id']: row for row in problem['operations']}
    machines = {row['machine'] for row in problem['machines']}
    for task in tasks:
        mid, start, sequence = task.get('machine'), task.get('start'), task.get('sequence')
        if type(mid) is not int or mid not in machines or not _finite(start) or start < problem['time']:
            errors.append('invalid explicit machine/start')
        if type(sequence) is not int or (mid, sequence) in sequences:
            errors.append('repeated or invalid explicit machine sequence')
        sequences.add((mid, sequence))
        ids = task.get('operations')
        if not isinstance(ids, list) or not ids:
            errors.append('empty or invalid explicit batch'); continue
        chosen = []
        for oid in ids:
            if oid not in operations:
                errors.append('unknown operation: ' + str(oid)); continue
            if oid in seen:
                errors.append('duplicate operation: ' + oid)
            seen.add(oid); chosen.append(operations[oid])
        if chosen:
            if any(mid not in op['eligible_machines'] for op in chosen):
                errors.append('ineligible explicit machine')
            if any(op['batch_key'] != chosen[0]['batch_key'] for op in chosen):
                errors.append('incompatible explicit batch')
            if not chosen[0]['batch_min'] <= len(chosen) <= chosen[0]['batch_max']:
                errors.append('explicit batch min/max')
    for hold in holds:
        mid, until, after = hold.get('machine'), hold.get('until'), hold.get('after_sequence')
        if type(mid) is not int or mid not in machines or not _finite(until) or not problem['time'] < until <= observation_end:
            errors.append('invalid explicit hold machine/time')
        if not isinstance(hold.get('reason'), str):
            errors.append('invalid hold reason')
        if after is not None and (type(after) is not int or (mid, after) not in sequences):
            errors.append('hold after_sequence is not in already chosen tasks; explicit model revision required')
        if (mid, after) in hold_keys:
            errors.append('duplicate explicit hold key requires model revision')
        hold_keys.add((mid, after))
    return sorted(set(errors))


def _raw_plan(problem, tasks, holds, reason, version):
    """Decode only explicit model sequence values, never invent an ordering."""
    operations = {op['operation_id']: op for op in problem['operations']}
    chosen = sorted(tasks, key=lambda task: (task['machine'], task['sequence']))
    decoded = []
    for index, task in enumerate(chosen):
        rows = [operations[oid] for oid in task['operations']]
        decoded.append({'id': str(index), 'machine': task['machine'],
            'lot_ids': [row['lot_id'] for row in rows], 'steps': [row['step'] for row in rows],
            'visits': [row['visit'] for row in rows], 'operation_ids': list(task['operations']),
            'not_before': task['start']})
    decoded_holds = []
    for hold in holds:
        item = {key: value for key, value in hold.items() if key != 'after_sequence'}
        if hold.get('after_sequence') is not None:
            item['after_task_id'] = str(next(index for index, task in enumerate(chosen)
                if task['machine'] == hold['machine'] and task['sequence'] == hold['after_sequence']))
        decoded_holds.append(item)
    return {'version': version, 'created_at': problem['time'], 'valid_until': problem['horizon_end'],
            'freeze_until': problem['time'], 'reason': reason, 'scope': problem['scope'],
            'tasks': decoded, 'holds': decoded_holds}


def prepare_B_recovery(run_dir, output_path, ledger_path=None):
    """Write one new recovery manifest, never the parent run or ledger.

    ``prepared`` means evidence can seed a future recovery controller, not that
    production succeeded or execution is authorized automatically. The original
    registration and model index sequence must be retained by that controller.
    """
    run, out = Path(run_dir).resolve(), Path(output_path).resolve()
    ledger_path = Path(ledger_path).resolve() if ledger_path else ROOT / 'progress/smt_fullfab/model_ledger.jsonl'
    if out.is_relative_to(run) or out == ledger_path or out.exists():
        raise ValueError('output must be a new independent artifact outside the original run and ledger')
    report = {'recovery_version': VERSION, 'status': 'rejected', 'parent_run': str(run),
              'errors': [], 'model_calls': 0, 'solver_calls': 0, 'clock_advances': 0,
              'executes_recovery': False, 'formal': False,
              'scope': 'first uncommitted B v2 plan at t=0 only; later-state recovery is unsupported'}
    try:
        initial_inventory = _inventory(run)
        ledger_bytes = ledger_path.read_bytes()
        ledger = [json.loads(line) for line in ledger_bytes.splitlines() if line.strip()]
        cfg, result = _read(run / 'config.json'), _read(run / 'result.json')
        if cfg.get('arm') != 'B' or result.get('status') != 'failed' or result.get('full_window_completed') is not False:
            raise ValueError('only an authoritative failed B run can be prepared')
        if not isinstance(result.get('failure'), str) or not result['failure']:
            raise ValueError('failed run has no preserved failure reason')
        _dead_claim(run, cfg)
        if result.get('plans_committed') != 0 or result.get('simulation_seconds') != 0:
            raise ValueError('later physical-state recovery is not yet supported')
        pending = {}
        for row in ledger:
            if row.get('event') in ('reserve', 'solver_reserve'):
                pending[row['call_id']] = row
            elif row.get('event') in ('finish', 'solver_finish'):
                pending.pop(row['call_id'], None)
        if pending:
            raise ValueError('unresolved ledger attempt; authoritative termination/reconciliation required first')
        audit = audit_controller(run, ledger_path)
        report['controller_evidence_audit'] = {'valid': audit['valid'], 'errors': audit['errors'],
            'missing_evidence': audit['missing_evidence'], 'audit_version': audit['audit_version']}
        if not audit['valid']:
            raise ValueError('controller saved-evidence audit did not pass')
        if not audit['all_saved_problem_pages_lossless_certified']:
            raise ValueError('legacy v1/partial observation cannot be migrated to v2 recovery')
        registration = audit['budget_admission_replay']['registered_runs'].get(str(run))
        if not registration or registration['arm'] != 'B':
            raise ValueError('recovery requires the original immutable research run registration')
        if set(p.name for p in run.glob('problem_*.json')) != {'problem_000.json'}:
            raise ValueError('only one uncommitted original problem is supported')
        problem, manifest = _read(run / 'problem_000.json'), _read(run / 'page_manifest_000.json')
        if manifest.get('schema') != 'fullfab-compact-paging-v2':
            raise ValueError('only exact compact v2 observations are recoverable')
        snapshot, trace = _read(run / 'checkpoint.json'), _read(run / 'trace.jsonl', lines=True)
        state = snapshot.get('state', {})
        if snapshot.get('schema') != 'smt-fullfab-snapshot-1' or digest(state) != snapshot.get('state_sha256'):
            raise ValueError('checkpoint schema/state hash mismatch')
        if state.get('trace') != trace or not trace or trace[0].get('kind') != 'initial':
            raise ValueError('checkpoint trace differs from immutable parent trace')
        if state.get('t') != 0 or state.get('finished') is not False or state.get('plan') is not None or state.get('executed_tasks') or state.get('plan_versions'):
            raise ValueError('checkpoint is not an untouched first-plan physical state')
        if any(e.get('kind') in ('dispatch', 'plan_committed', 'time_advance', 'terminal') for e in trace):
            raise ValueError('physical execution already occurred; cold recovery unsupported')
        report['checkpoint_verification'] = _verify_cold_checkpoint(run, cfg, snapshot, problem)
        schema = _schema_from_frozen_source(run)
        links = _read(run / 'controller_decisions.jsonl', lines=True)
        if [row.get('model_index') for row in links] != list(range(result['model_calls'])):
            raise ValueError('original model/decision indexes are not complete and contiguous')
        pages = [_read(run / f'page_000_{i:02d}.json') for i in range(manifest['page_count'])]
        if len(links) > len(pages):
            raise ValueError('repeated page attempts require an explicit recovery history schema')
        staged, holds, accepted, failures, patch_names = [], [], [], [], set()
        for index, link in enumerate(links):
            if link.get('plan_index') != 0 or link.get('page_index') != index or link.get('arm') != 'B' or link.get('stage') != 'B_page' or link.get('input_problem_sha256') != digest(problem):
                raise ValueError('page linkage changed original plan/order/problem')
            directory = run / f'model_{index:03d}'
            model = _read(directory / 'result.json')
            if _read(directory / 'schema.json') != schema:
                raise ValueError('model schema differs from the frozen B schema')
            if model.get('returncode') is None and not model.get('launch_error'):
                raise ValueError('model result lacks authoritative terminated process evidence')
            claim = directory / 'attempt.claim'
            if not claim.exists() or claim.read_text() != model['request_fingerprint'] + '\n':
                raise ValueError('attempt claim differs from original model fingerprint')
            if model.get('status') == 'success' and (model.get('returncode') != 0 or model.get('failure_reason') is not None):
                raise ValueError('successful model status contradicts terminal process evidence')
            sections = _sections((directory / 'prompt.txt').read_text())
            metadata = {**manifest, 'page_index': index, 'last_page': index == len(pages) - 1,
                        'remaining_model_responses': None if cfg.get('max_calls') is None else cfg['max_calls'] - index}
            predecessors = {p for group in pages[index] for row in group['operations'] for p in row[3]}
            mids = {row[0] for group in pages[index] for row in group['machines']}
            expected_prior = [task for task in staged if task['machine'] in mids or any(op in predecessors for op in task['operations'])]
            if sections != {'SCHEMA_AND_LIMITS': metadata, 'PAGE': pages[index], 'YOUR_PRIOR_PREDECESSOR_CHOICES': expected_prior}:
                raise ValueError('page input/prior accepted choices are not exact')
            patch_path = run / f'patch_000_{index:02d}.json'
            if patch_path.exists():
                patch_names.add(patch_path.name)
                if _read(patch_path) != model.get('output'):
                    raise ValueError('saved patch differs from raw model output')
            if failures:
                raise ValueError('controller proceeded after a nonaccepted page')
            if model.get('status') != 'success':
                if patch_path.exists():
                    raise ValueError('failed transport unexpectedly has a staged patch')
                failures.append({'page_index': index, 'call_id': link['call_id'], 'kind': 'transport_failure',
                    'failure_reason': model.get('failure_reason'), 'failed_output_sha256': digest(model.get('output'))})
                continue
            response = model['output']
            violations = _schema_errors(response, schema)
            allowed = {row[0] for group in pages[index] for row in group['operations']}
            if any(op not in allowed for task in response['tasks'] for op in task['operations']):
                violations.append('patch references an operation outside the supplied page')
            if response['commit'] != (index == len(pages) - 1):
                violations.append('explicit commit before all pages' if response['commit'] else 'final page lacks explicit commit')
            proposed_tasks, proposed_holds = staged + response['tasks'], holds + response['holds']
            violations += _choice_errors(problem, proposed_tasks, proposed_holds, manifest['observation_end'])
            if violations:
                failures.append({'page_index': index, 'call_id': link['call_id'], 'kind': 'explicit_model_revision_required',
                    'violations': sorted(set(violations)), 'failed_output_sha256': digest(response)})
                continue
            if not patch_path.exists():
                raise ValueError('semantically accepted page lacks its durable original patch')
            staged, holds = proposed_tasks, proposed_holds
            accepted.append({'page_index': index, 'call_id': link['call_id'], 'model_index': index,
                'patch_sha256': digest(response), 'patch_file_sha256': sha_file(patch_path),
                'cumulative_staged_sha256': digest(staged), 'cumulative_holds_sha256': digest(holds),
                'task_count': len(staged), 'hold_count': len(holds)})
        if {p.name for p in run.glob('patch_*.json')} != patch_names:
            raise ValueError('unattributed original patch artifact')
        own_ids = result['model_call_ids']
        finishes = [row for row in ledger if row.get('event') == 'finish' and row.get('call_id') in own_ids]
        model_active = sum(row['details']['duration_seconds'] for row in finishes)
        known_tokens, unknown_ids = 0, []
        for row in finishes:
            usage = row['details'].get('usage', {})
            if all(type(usage.get(k)) is int and usage[k] >= 0 for k in ('input_tokens', 'output_tokens')):
                known_tokens += usage['input_tokens'] + usage['output_tokens']
            else:
                unknown_ids.append(row['call_id'])
        wall = result.get('wall_seconds')
        if not _finite(wall) or wall < model_active:
            raise ValueError('original run wall evidence cannot preserve prior model consumption')
        used_bytes = sum(row['bytes'] for row in initial_inventory.values())
        remaining_wall = max(0, registration['wall_seconds'] - wall)
        remaining_model = max(0, registration['wall_seconds'] - model_active)
        remaining_log = max(0, registration['max_log_bytes'] - used_bytes)
        exhausted = remaining_wall < 1 or remaining_model < 1 or remaining_log <= 0
        all_accepted = len(accepted) == len(pages)
        raw_files = list(run.glob('raw_plan_*.json'))
        if raw_files:
            if not all_accepted or [path.name for path in raw_files] != ['raw_plan_000.json']:
                raise ValueError('raw plan exists without a complete accepted page collection')
            reason = _read(run / f'patch_000_{len(pages) - 1:02d}.json')['reason']
            if _read(raw_files[0]) != _raw_plan(problem, staged, holds, reason, cfg['run_id'] + ':0'):
                raise ValueError('uncommitted raw plan differs from exact explicit model choices')
        needs_revision = all_accepted or any(row['kind'] == 'explicit_model_revision_required' for row in failures)
        mode = 'needs_explicit_model_revision' if needs_revision else 'resume_next_page'
        if all_accepted:
            failures.append({'kind': 'whole_plan_commit_failure_requires_explicit_model_revision',
                'original_failure': result.get('failure'), 'revision_scope': 'full staged plan; no automatic task repair or apply'})
        report.update(status='prepared', recovery_mode=mode, executable_now=False,
            original_failure=result.get('failure'), plan_index=0,
            next_page=None if all_accepted else len(accepted), next_model_index=result['model_calls'],
            page_count=len(pages), accepted_pages=accepted, staged_tasks=staged, staged_holds=holds,
            staged_sha256=digest(staged), holds_sha256=digest(holds), failed_page_feedback=failures,
            original_registration=registration,
            prefix_acceptance_scope='exact page/schema/task identities, batching, eligibility, unique sequences and already-resolved holds; full-plan physical commit may still require revision',
            unresolved_forward_hold_policy='do not retain a hold whose after_sequence is absent from the accepted prefix; report explicit revision instead of guessing a future task',
            consumption={'model_attempts': len(own_ids), 'model_call_ids': own_ids, 'model_active_seconds': model_active,
                'reported_input_output_tokens': known_tokens, 'unknown_usage_call_ids': unknown_ids,
                'runner_wall_seconds': wall, 'parent_log_bytes': used_bytes, 'solver_requested_seconds': 0},
            remaining={'runner_wall_seconds': remaining_wall, 'model_active_seconds': remaining_model,
                'log_bytes': remaining_log, 'attempt_count': None, 'reported_tokens': None},
            resource_exhausted=exhausted, checkpoint_state_sha256=snapshot['state_sha256'],
            problem_sha256=digest(problem), manifest_sha256=digest(manifest),
            ledger_prefix={'path': str(ledger_path), 'bytes': len(ledger_bytes), 'records': len(ledger),
                'sha256': hashlib.sha256(ledger_bytes).hexdigest(), 'canonical_sha256': _record_digest(ledger)},
            parent_evidence=initial_inventory,
            execution_requirements=['Keep original absolute run_id and registration; never register a fresh allowance.',
                'Use new model indexes, retain original call IDs, and never recall accepted pages.',
                'Verify original evidence hashes and ledger prefix again before any future reservation.',
                'Charge all later wall/log activity cumulatively; historical unknown usage remains unknown.',
                'Require a separate versioned recovery executor and independent resumed-history audit before execution.'])
        if _inventory(run) != initial_inventory or ledger_path.read_bytes() != ledger_bytes:
            raise ValueError('parent evidence or ledger changed during preparation')
    except (ValueError, KeyError, TypeError, IndexError, SyntaxError, OSError, subprocess.SubprocessError) as exc:
        report['status'] = 'rejected'
        report['errors'].append(str(exc))
    report['package_sha256'] = _record_digest(report)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir'); parser.add_argument('--output', required=True); parser.add_argument('--ledger')
    args = parser.parse_args()
    result = prepare_B_recovery(args.run_dir, args.output, args.ledger)
    print(json.dumps({k: result.get(k) for k in ('status', 'recovery_mode', 'next_page', 'next_model_index', 'errors')}, ensure_ascii=False))
    return 0 if result['status'] == 'prepared' else 1


if __name__ == '__main__':
    raise SystemExit(main())
