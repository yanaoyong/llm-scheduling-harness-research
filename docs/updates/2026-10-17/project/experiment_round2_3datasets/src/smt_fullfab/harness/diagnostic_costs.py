"""Verify separate transport diagnostics before carrying them into B accounts."""
from pathlib import Path

from .contracts import digest, require, sha_bytes, strict_json


def verify_attempt(reference, *, model):
    from .experiment import checked_file
    from ..model_process_guard import INPUT_FILES, OUTPUT_FILES, verify_lifecycle
    from ..model_transport import summarize_events
    result = checked_file(reference)
    path = Path(reference['path']).parent
    plan = strict_json((path / 'plan.json').read_bytes())
    argv = strict_json((path / 'command.json').read_bytes())['argv']
    require(plan['model'] == result['model'] == model['name']
            and plan['reasoning_effort'] == model['reasoning_effort']
            and argv[argv.index('--model') + 1] == model['name']
            and 'model_reasoning_effort="' + model['reasoning_effort'] + '"' in argv
            and sha_bytes(Path(argv[0]).read_bytes()) == plan['cli_sha256'],
            'diagnostic_model', 'Probe model, effort or executable differs')
    require(all(setting in argv for setting in (
        'model_providers.harness-openai.request_max_retries=0',
        'model_providers.harness-openai.stream_max_retries=0')),
        'diagnostic_retries', 'Hidden transport retries are forbidden')
    inputs = {name: sha_bytes((path / name).read_bytes()) for name in plan['inputs_sha256']}
    require(inputs == plan['inputs_sha256'] and digest({'argv': argv, 'inputs': inputs}) == plan['request_fingerprint'],
            'diagnostic_inputs', 'Probe request changed')
    io = {'cwd': str(path / 'isolated-cwd'), 'stdin': str(path / 'prompt.txt'),
          'stdout': str(path / 'events.jsonl'), 'stderr': str(path / 'stderr.log'),
          'inputs': {name: str(path / name) for name in (*INPUT_FILES, 'model-catalog.json', 'network.json')},
          'outputs': {name: str(path / name) for name in OUTPUT_FILES}}
    guard = verify_lifecycle(path, expected_command=argv, expected_timeout=plan['timeout_seconds'],
                             expected_call_id=plan['call_id'], expected_fingerprint=plan['request_fingerprint'], expected_io_spec=io)
    events = [strict_json(line) for line in (path / 'events.jsonl').read_bytes().splitlines() if line.strip()]
    raw = summarize_events(events)
    known = all(type(raw['usage'][key]) is int for key in ('input_tokens', 'output_tokens'))
    require(result['actual_calls'] == 1 and result['call_id'] == plan['call_id']
            and result['unknown_usage'] == (not known) and result['usage'] == (raw['usage'] if known else None)
            and result['duration_seconds'] == guard['parent_wait_wall_seconds']
            and result['returncode'] == guard['command_returncode'] and result['errors'] == raw['errors']
            and result['completed_turns'] == raw['completed_turns'] and not raw['native_tool_events']
            and not guard['timed_out'] and result['business_actions_executed'] is False,
            'diagnostic_cost', 'Probe usage, identity, duration or native actions differ from original evidence')
    if known:
        require(raw['completed_turns'] == 1 and not raw['errors'] and guard['command_returncode'] == 0
                and isinstance(strict_json((path / 'final.txt').read_bytes()), dict),
                'diagnostic_completion', 'Completed stream and structured answer required')
    else:
        failures = [event for event in events if event.get('type') == 'turn.failed']
        require(len(failures) == 1 and failures[0]['error']['message'] ==
                'stream disconnected before completion: Transport error: network error: error decoding response body'
                and raw['completed_turns'] == 0 and guard['command_returncode'] != 0
                and not any(event.get('item', {}).get('type') == 'agent_message' for event in events)
                and not (path / 'final.txt').exists(),
                'diagnostic_unknown', 'Only the exact retained terminal stream failure is exempt')
    started = strict_json((path / 'launch_once.json').read_bytes())['started_epoch']
    require(started == result['started_epoch'] and result['ended_epoch'] >= started,
            'diagnostic_clock', 'Probe clock changed or reversed')
    return result


def verify_batch(reference, *, model, tun_entry=False):
    from .experiment import checked_file
    audit = checked_file(reference)
    expected_schema = 'harness-TUN-isolation-audit-v1' if tun_entry else 'harness-network-recheck-audit-v1'
    require(audit['schema'] == expected_schema and audit['model'] == model['name']
            and audit['reasoning_effort'] == model['reasoning_effort'] and audit['formal_B_started'] is False,
            'diagnostic_batch', 'Unexpected diagnostic boundary or model')
    for path, expected in audit['evidence_sha256'].items():
        require(sha_bytes(Path(path).read_bytes()) == expected, 'diagnostic_evidence', 'Historical probe evidence changed')
    rows, identities = [], set()
    for item in audit['call_identities']:
        row = verify_attempt(item['result'], model=model)
        require(item['call_id'] == row['call_id'] and row['call_id'] not in identities
                and item['unknown_usage'] == row['unknown_usage'], 'diagnostic_duplicate', 'Omitted or duplicated probe identity')
        identities.add(row['call_id'])
        rows.append(row)
    require(len(rows) == (3 if tun_entry else 2), 'diagnostic_batch', 'Expected the exact bounded investigation')
    cost = {'attempts': len(rows), 'tokens': sum(row['usage']['input_tokens'] + row['usage']['output_tokens'] for row in rows if row['usage']),
            'unknown_usage': sum(row['unknown_usage'] for row in rows), 'model_seconds': sum(row['duration_seconds'] for row in rows)}
    if tun_entry:
        require(audit['entry_check_passed'] is True and cost['unknown_usage'] == 0
                and all(row['channel_success'] and row['underlying_route_unchanged'] for row in rows),
                'diagnostic_entry', 'All three TUN-only requests must have completed without unknown usage')
        for index, (item, row) in enumerate(zip(audit['call_identities'], rows), 1):
            path = Path(item['result']['path']).parent
            route = strict_json((path / 'network.json').read_bytes())
            require(route == audit['current_route'] and route['explicit_proxy'] is None and route['NO_PROXY'] == '*',
                    'diagnostic_route', 'Probe routing differs')
            observations = strict_json((path / 'connection_observations.json').read_bytes())
            counts = {name: sum(obs.get('category') == name for obs in observations)
                      for name in ('explicit_Clash_7897', 'non_loopback', 'loopback_other')}
            require(row['connection_categories'] == counts and counts['explicit_Clash_7897'] == 0 and counts['non_loopback'] > 0,
                    'diagnostic_route', 'Explicit proxy removal was not observed')
            answer = strict_json((path / 'final.txt').read_bytes())
            require(isinstance(answer.get('action'), dict) if index == 2 else
                    answer == {'rows': [{'n': n, 'square': n*n} for n in range(1, 257)]},
                    'diagnostic_entry', 'Long-response integrity or representative action failed')
        cost['wall_seconds'] = sum(row['ended_epoch'] - row['started_epoch'] for row in rows)
    else:
        root = Path(reference['path']).parent
        plan = strict_json((root / 'probe_plan.json').read_bytes())
        result = strict_json((root / 'probe_results.json').read_bytes())
        require(result['results'] == rows and cost['unknown_usage'] == 1 and not audit['entry_check_passed'],
                'diagnostic_batch', 'Earlier failed path must remain failed and charged')
        cost['wall_seconds'] = result['completed_epoch'] - plan['started_epoch']
    require(cost['attempts'] == audit['actual_new_calls'] and cost['tokens'] == audit['known_new_tokens']
            and cost['unknown_usage'] == audit['new_unknown_usage'] and cost['model_seconds'] == audit['new_model_seconds']
            and cost['wall_seconds'] == audit['diagnostic_wall_seconds'], 'diagnostic_cost', 'Diagnostic totals were discounted')
    return cost, identities, audit


def verify_chain(reference, *, model):
    """Return all five diagnostic costs, including the failed earlier route."""
    from .experiment import checked_file
    current, ids, audit = verify_batch(reference, model=model, tun_entry=True)
    previous, oldids, old = verify_batch(audit['previous_cost_boundary'], model=model)
    require(not ids & oldids and old['exceptions_used'] == 14
            and audit['exceptions_used'] == old['exceptions_used'] + current['unknown_usage'],
            'diagnostic_duplicate', 'History or exception counter changed')
    base = checked_file(old['previous_cost_boundary'])
    before = base['registered_cumulative_usage_after_B']
    require(base['exception_quota']['used'] + previous['unknown_usage'] == old['exceptions_used'],
            'diagnostic_cost', 'Earlier exception counter reset')
    expected = {key: before[key] + previous[key] for key in previous}
    require(expected == old['cumulative_usage_including_new_diagnostics'], 'diagnostic_cost', 'First diagnostic boundary differs')
    expected = {key: expected[key] + current[key] for key in current}
    require(expected == audit['cumulative_usage_including_new_diagnostics'], 'diagnostic_cost', 'Latest diagnostic boundary differs')
    return {key: previous[key] + current[key] for key in current}, ids | oldids, old['previous_cost_boundary']
