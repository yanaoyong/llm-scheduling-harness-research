"""One explicit preserved continuation with ordered soft and hard deadlines."""
import time
BEGUN = time.monotonic()
import argparse
import json
import math
import os
from pathlib import Path
import sys
import traceback


def deadline_contract(first, remaining, prepare, *, now):
    values = (first, remaining, prepare, now)
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in values):
        raise ValueError('finite explicit wall times required')
    if not 0 < first <= now or prepare < 0 or remaining <= prepare:
        raise ValueError('invalid cumulative remaining wall or original clock')
    hard = first + remaining - prepare - 30.0
    soft = hard - 900.0
    if now + 660.0 >= soft:
        raise ValueError('insufficient time for one 600-second call plus close reserve')
    return {'first_monotonic':first, 'hard_deadline_monotonic':hard,
            'soft_deadline_monotonic':soft, 'terminal_cleanup_reserve_seconds':900.0,
            'outer_publication_reserve_seconds':30.0,
            'minimum_call_admission_reserve_seconds':660.0,
            'timeout_seconds_at_request':hard-now}


def main(campaign, expected):
    campaign = Path(campaign).resolve(); frozen = campaign/'frozen'
    assert Path(__file__).resolve().is_relative_to(frozen)
    sys.path.insert(0, str(frozen))
    from src.smt_fullfab.B_v8_preserved_resume_v1.host import bound
    from src.smt_fullfab.B_candidate_paths_v14.recovery import sha, new
    from src.smt_fullfab.model_process_guard import run_guarded
    digest, _, raw = bound(campaign/'manifest.json', keep=True)
    assert digest == expected
    manifest = json.loads(raw)
    assert sha(__file__) == manifest['runtime_files']['src/smt_fullfab/B_budget_extension_v15/outer.py']
    assert sha(frozen/'src/smt_fullfab/model_process_guard.py') == manifest['runtime_files']['src/smt_fullfab/model_process_guard.py']
    root = Path(manifest['root']); segment = Path(manifest['segment_path'])
    guard = campaign/'outer'; guard.mkdir()
    remaining = float(manifest['remaining_wall_seconds'])
    deadlines = deadline_contract(BEGUN, remaining, manifest['prepare_wall_seconds'], now=time.monotonic())
    command = [manifest['python'], '-B', str(frozen/'src/smt_fullfab/B_budget_extension_v15/host.py'),
               '--campaign', str(campaign), '--manifest-sha256', expected,
               '--first-monotonic', repr(BEGUN),
               '--hard-deadline-monotonic', repr(deadlines['hard_deadline_monotonic']),
               '--soft-deadline-monotonic', repr(deadlines['soft_deadline_monotonic'])]
    req = {'schema':'smt-B-v15-budget-extension-outer-request-v1', 'command':command,
           'manifest_sha256':expected, **deadlines, 'automatic_retry':False, 'parent_status':'failed'}
    fingerprint = new(guard/'request.json', req)
    io = {'cwd':str(frozen), 'stdin':None, 'stdout':str(guard/'stdout.log'), 'stderr':str(guard/'stderr.log'),
          'inputs':{'request':str(guard/'request.json'), 'manifest':str(campaign/'manifest.json'), 'host':command[2]},
          'outputs':{'stdout':str(guard/'stdout.log'), 'stderr':str(guard/'stderr.log'), 'host_result':str(campaign/'host_result.json')}}
    result = {'schema':'smt-B-v15-budget-extension-outer-result-v1', 'accepted':False, 'status':'failed',
              'manifest_sha256':expected, 'cost_usd':None, 'parent_status':'failed', 'formal':False,
              'automatic_retry':False, 'deadlines':deadlines, 'errors':[]}
    try:
        # Recompute from the fixed absolute deadline, never grant time spent preparing the request again.
        timeout = deadlines['hard_deadline_monotonic'] - time.monotonic()
        assert timeout > 0
        result['guard'] = run_guarded(command, run_dir=guard, timeout_seconds=timeout, env=os.environ.copy(),
            call_id=segment.name+':outer', request_fingerprint=fingerprint, io_spec=io)
        host_sha, host_identity, host_raw = bound(campaign/'host_result.json', keep=True)
        assert host_sha == result['guard']['output_files_sha256']['host_result']
        host = json.loads(host_raw); result['host_result_sha256'] = host_sha
        assert result['guard']['lifecycle_complete'] and result['guard']['command_returncode'] == 0 and not result['guard']['timed_out']
        assert host['status'] == 'completed_pending_outer_resource_check' and host['accepted'] is False
        assert bound(campaign/'host_result.json')[:2] == (host_sha, host_identity)
        result['status'] = 'completed_pending_root_actual_wait'
    except BaseException as exc:
        result['errors'].append({'type':type(exc).__name__, 'message':str(exc), 'traceback':traceback.format_exc()})
    result['elapsed_outer_seconds_before_encoding'] = time.monotonic() - BEGUN
    result['prepare_wall_seconds'] = manifest['prepare_wall_seconds']
    result['bytes_before_result'] = sum(p.stat().st_size for base in (campaign, segment) if base.exists() for p in base.rglob('*') if p.is_file())
    if result['elapsed_outer_seconds_before_encoding'] + manifest['prepare_wall_seconds'] >= remaining or result['bytes_before_result'] >= manifest['remaining_log_bytes']:
        result['status'] = 'failed'; result['errors'].append({'type':'resource_limit', 'message':'cumulative segment allowance exceeded'})
    new(campaign/'outer_result.json', result)
    print(json.dumps({'status':result['status'], 'accepted':False, 'outer_result_sha256':sha(campaign/'outer_result.json')}), flush=True)
    return 0 if result['status'] == 'completed_pending_root_actual_wait' else 1


if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--campaign', required=True); p.add_argument('--manifest-sha256', required=True)
    args=p.parse_args(); raise SystemExit(main(args.campaign,args.manifest_sha256))
