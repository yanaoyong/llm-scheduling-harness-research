"""Small read-only progress snapshot, never a physical or liveness certificate.

Does not import experiment code, inspect large checkpoints, launch a process,
modify a run/ledger, or infer process exit from a result file. Root must poll its
original exec session separately. The full status/audit is deferred until exit.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = {
    'C_1701_8h_stream_v1': ('smt_fullfab_C_stream_gate', 'smt_fullfab_C_host_guard'),
    'B_1701_1h_delta_v4': ('smt_fullfab_B_delta_gate', 'smt_fullfab_B_delta_host_guard'),
}


def small_json(path):
    if not path.exists():
        return {'present': False}
    if path.stat().st_size > 16 * 1024**2:
        return {'present': True, 'not_parsed': 'metadata exceeds16MiB'}
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
        return {'present': True, 'sha256': hashlib.sha256(raw).hexdigest(),
                'reported': {k: value[k] for k in ('status', 'accepted', 'failure', 'errors',
                    'simulation_seconds', 'model_calls', 'plans', 'plans_committed', 'pid') if k in value}}
    except (OSError, ValueError) as exc:
        return {'present': True, 'not_parsed': type(exc).__name__ + ': ' + str(exc)}


def observe(run_id):
    run = ROOT / 'runs/smt_fullfab_stage2' / run_id
    area, host = RUNS[run_id]
    trace = run / 'trace.jsonl'
    tail, size = [], None
    if trace.exists():
        with trace.open('rb') as stream:
            stream.seek(0, 2); size = stream.tell(); start = max(0, size - 65536)
            stream.seek(start); raw = stream.read(size - start)
        lines = raw.split(b'\n')[:-1]
        if start: lines = lines[1:]
        for line in lines:
            try:
                event = json.loads(line)
                tail.append({k: event[k] for k in ('kind', 'time') if k in event})
            except (ValueError, TypeError):
                continue
    ledger = ROOT / 'progress/smt_fullfab/model_ledger.jsonl'
    raw = ledger.read_bytes(); complete = raw[:raw.rfind(b'\n') + 1]
    rows = [json.loads(line) for line in complete.splitlines() if line.strip()]
    reserves = {r['call_id']: r for r in rows if r.get('event') == 'reserve'}
    finishes = {r['call_id']: r for r in rows if r.get('event') == 'finish'}
    own = {cid for cid, row in reserves.items()
           if row.get('run_id') == str(run) or str(row.get('run_id', '')).startswith(str(run) + '/')}
    def account(ids):
        known = 0; unknown = []
        for cid in ids & finishes.keys():
            usage = (finishes[cid].get('details') or {}).get('usage')
            if type(usage) is dict and all(type(usage.get(k)) is int and usage[k] >= 0
                                         for k in ('input_tokens', 'output_tokens')):
                known += usage['input_tokens'] + usage['output_tokens']
            else: unknown.append(cid)
        return {'attempts': len(ids), 'finished': len(ids & finishes.keys()),
                'pending': sorted(ids - finishes.keys()), 'known_input_output_tokens': known,
                'unknown_finished_call_ids': sorted(unknown)}
    commits = run / 'plan_commits.jsonl'
    count = 0
    if commits.exists():
        with commits.open('rb') as stream:
            for line in stream:
                if line.endswith(b'\n') and line.strip(): count += 1
    return {'schema': 'smt-fullfab-lightweight-observation-v1',
            'at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'run_id': run_id,
            'process_liveness': 'not_checked; poll original exec session separately',
            'acceptance_verified': False, 'scope': 'Small live file metadata; no semantic or complete raw evidence validation',
            'claim': small_json(run/'claim.json'), 'runner_result': small_json(run/'result.json'),
            'gate_acceptance': small_json(ROOT/'runs'/area/run_id/'acceptance.json'),
            'host_result': small_json(ROOT/'runs'/host/run_id/'result.json'),
            'committed_plan_lines': count, 'last_complete_trace_records': tail[-2:],
            'trace_bytes_observed': size, 'model_result_files_present': sum((p/'result.json').exists() for p in run.glob('model_*') if p.is_dir()),
            'ledger_complete_prefix_bytes': len(complete), 'ledger_unterminated_tail_bytes': len(raw)-len(complete),
            'ledger_complete_prefix_sha256': hashlib.sha256(complete).hexdigest(),
            'global_model_account': account(reserves.keys()), 'run_model_account': account(own),
            'currency_cost': None, 'aggregate_call_and_token_limits': None}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', choices=tuple(RUNS), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists(): raise SystemExit('Choose a new observation path; never overwrite saved evidence')
    value = observe(args.run_id)
    with args.output.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2); stream.write('\n')
    print(json.dumps(value, ensure_ascii=False))
