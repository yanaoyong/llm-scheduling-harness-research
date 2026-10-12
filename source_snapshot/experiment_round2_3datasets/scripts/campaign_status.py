#!/usr/bin/env python3
"""Read-only campaign inventory, optionally refresh the resumable status file.

This reports recorded status, not independent certification. It never runs a
solver or model, mutates a run, or admits new work.
"""
import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.experiment import git, now, read_json, write_json


def snapshot():
    freezes = [read_json(ROOT / 'configs/freezes' / (n + '.json')) for n in
               ('static-v1', 'smt-v1', 'static-aux-v2', 'smt-aux-v1')]
    groups, failures, unfinished = [], [], []
    wall = 0.0
    resume = []
    for f in freezes:
        statuses = Counter()
        for instance, arm, repeat in f['matrix']:
            rid = f"{'smt' if f.get('dataset') == 'smt2020' else ''}{instance}_{arm}_r{repeat}"
            path = ROOT / 'runs' / f['phase'] / rid
            if (path / 'result.json').exists():
                r = read_json(path / 'result.json')
                statuses[r['status']] += 1
                wall += r.get('costs', {}).get('end_to_end_seconds', 0)
                if r['status'] != 'success':
                    failures.append({'phase': f['phase'], 'run_id': rid,
                                     'status': r['status'], 'type': r.get('failure_type')})
            elif path.exists():
                statuses['unfinished'] += 1
                unfinished.append({'phase': f['phase'], 'run_id': rid})
            else:
                statuses['not_started'] += 1
        if statuses['not_started'] or statuses['unfinished']:
            resume.append('.venv/bin/python -m src.batch --freeze ' + f['name'])
        groups.append({'phase': f['phase'], 'core': f['core'], 'expected': len(f['matrix']),
                       'statuses': dict(statuses)})
    events = [json.loads(line) for line in (ROOT / 'progress/model_ledger.jsonl').read_text().splitlines()]
    finished = {e['call_id']: e for e in events if e['event'] == 'finish'}
    budget = {}
    for phase in ('development', 'formal'):
        models = [e for e in events if e['event'] == 'reserve' and e['phase'] == phase]
        done = [finished[e['call_id']] for e in models if e['call_id'] in finished]
        usage = [e.get('details', {}).get('usage', {}) or {} for e in done]
        known = [u for u in usage if u.get('input_tokens') is not None and u.get('output_tokens') is not None]
        budget[phase] = {'model_attempts': len(models), 'model_completed': len(done),
                         'pending_model_attempts': len(models) - len(done),
                         'unknown_completed_usage': len(done) - len(known),
                         'reported_input_output_tokens': sum(u['input_tokens'] + u['output_tokens'] for u in known),
                         'reserved_solver_seconds': sum(e['requested_seconds'] for e in events
                            if e['event'] == 'solver_reserve' and e['phase'] == phase)}
    core = [g for g in groups if g['core']]
    development, probes, blockers = [], [], []
    for path in sorted((ROOT / 'runs/development').glob('*/result.json')):
        r = read_json(path)
        row = {'run_id': path.parent.name, 'status': r.get('status'),
               'type': r.get('failure_type', r.get('failure_reason'))}
        (development if r.get('arm') in ('A', 'B', 'C', 'F') else probes).append(row)
    for f in freezes:
        path = ROOT / 'progress' / (f['phase'] + '-batch.json')
        if path.exists():
            stopped = read_json(path).get('stopped_reason')
            if stopped:
                blockers.append({'phase': f['phase'], 'recorded_stop_reason': stopped})
    supplemental = []
    for path in sorted((ROOT / 'runs/recovery_static_channel_v1').glob('*/result.json')):
        r = read_json(path)
        supplemental.append({'run_id': r['run_id'], 'original_run_id': r['original_run_id'],
                             'status': r['status'], 'end_to_end_seconds': r['costs']['end_to_end_seconds']})
    final = ROOT / 'artifacts/final/acceptance.json'
    final_verified = False
    final_errors = []
    if final.exists():
        try:
            a = read_json(final)
            refs = dict(a['verified_saved_sources_sha256'])
            refs['artifacts/final/evidence-index.json'] = a['evidence_index_sha256']
            refs['artifacts/final/review-signoffs.json'] = a['signoffs_sha256']
            refs['scripts/final_acceptance.py'] = a['checker_sha256']
            final_errors = [p for p, h in refs.items() if not (ROOT/p).is_file()
                            or hashlib.sha256((ROOT/p).read_bytes()).hexdigest() != h]
            final_verified = a.get('acceptance_ready') is True and a.get('unfinished_items') == [] and not final_errors
        except (ValueError, KeyError, OSError):
            final_errors = ['malformed final acceptance evidence']
    if final_verified:
        resume = ['.venv/bin/python scripts/final_acceptance.py --check-only']
    return {'updated_at': now(), 'stage': 'final_accepted' if final_verified else 'formal_execution', 'goal_complete': final_verified,
            'latest_valid_commit': git('rev-parse', 'HEAD'), 'formal_expected': sum(g['expected'] for g in core),
            'formal_completed': sum(sum(v for k, v in g['statuses'].items() if k not in ('unfinished', 'not_started')) for g in core),
            'formal_success_raw': sum(g['statuses'].get('success', 0) for g in core),
            'certification_note': 'Original raw statuses retained. Final acceptance, when present, is separately hash-verified; this command never updates the Codex goal.',
            'final_acceptance': str(final.relative_to(ROOT)) if final.exists() else None,
            'final_acceptance_hash_bindings_valid': final_verified, 'final_acceptance_binding_errors': final_errors,
            'supplemental_recovery': supplemental,
            'formal_activity_including_recovery_seconds': wall + sum(r['end_to_end_seconds'] for r in supplemental),
            'groups': groups, 'failures': failures, 'unfinished': unfinished, 'blockers': blockers,
            'development_completed': len(development),
            'development_failures': [r for r in development if r['status'] != 'success'],
            'channel_probe_records': probes,
            'formal_recorded_wall_seconds': wall, 'budget': budget,
            'resume_commands': resume, 'resume_command': resume[0] if resume else 'Run offline replay and final acceptance review.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    data = snapshot()
    if args.write:
        write_json(ROOT / 'progress/STATUS.json', data)
    print(json.dumps(data, ensure_ascii=False, indent=2))
