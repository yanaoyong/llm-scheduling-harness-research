"""One new Astra B after three verified TUN streams; closed Bs remain failed."""
from copy import deepcopy
from pathlib import Path

from .contracts import digest, require, sha_bytes, strict_json, validate_config

SCHEMA = 'harness-B-network-restart-registration-v1'
GRANT = 'harness-B-network-restart-authorization-v1'
MODEL = {'name': 'gpt-6-astra', 'reasoning_effort': 'medium'}
USER_INSTRUCTION = '我切换了网络你看看是否断流缓解了是否可以开始使用astra进行B方案'
MODEL_CONFIRMATION = '使用 gpt-6-astra（已实测通过）'
ADDITIONAL = {'attempts': None, 'tokens': None, 'model_seconds': 10800, 'wall_seconds': 14400}
CONTROL_FILES = {'src/smt_fullfab/harness/' + name for name in (
    'B_network_restart.py', 'diagnostic_costs.py', 'network.py', 'network_tun.py',
    'experiment.py', 'model_switch.py', 'recovery.py')}


def previous_evidence(reg):
    from .experiment import checked_file, account_records
    from .evaluation import Evidence
    previous = checked_file(reg['previous_registration'])
    require(previous['schema'] == 'harness-B-model-switch-registration-v1' and previous['model'] == MODEL,
            'B_restart_ancestor', 'The closed Astra predecessor is required')
    root = Path(reg['previous_registration']['path']).parent
    evidence = Evidence(root / 'runs/B3600', reg['previous_B_evidence']['sha256'])
    require(Path(reg['previous_B_evidence']['path']).resolve() == root / 'runs/B3600/evidence_manifest.json'
            and evidence.manifest['admission']['experiment_sha256'] == reg['previous_registration']['sha256'],
            'B_restart_ancestor', 'Prior B identity differs')
    rows = account_records(root)
    require(len(rows) == 1 and rows[0][0:3] == ('B3600', 'B3600', evidence.manifest['run_id'])
            and Path(rows[0][3]) == evidence.path and rows[0][4] == evidence.manifest['created_epoch']
            and evidence.value['head']['phase'] == 'CLOSED',
            'B_restart_ancestor', 'Old B must remain the sole sealed predecessor run')
    closure = checked_file(reg['previous_B_closure'])
    require(closure['evidence_sha256'] == reg['previous_B_evidence']['sha256']
            and Path(reg['previous_B_closure']['path']).resolve() == root / 'runs/B3600/audit_closure.json',
            'B_restart_ancestor', 'Original B audit clock closure required')
    return previous, evidence, closure


def carried_costs(reg):
    from .B_model_switch import carried_costs as previous_costs
    from .diagnostic_costs import verify_chain
    from .evaluation import audit_cost
    from .experiment import checked_file
    previous, evidence, closure = previous_evidence(reg)
    totals, starts, ids = previous_costs(previous)
    totals, ids = deepcopy(totals), set(ids)
    cost = audit_cost(evidence)
    require(cost['pending_attempts'] == 0 and evidence.manifest['run_id'] not in ids,
            'B_restart_cost', 'Pending or duplicate old B')
    old = checked_file(reg['previous_outcome'])
    require(old['B_passed'] is False and all(old['B_cost'][key] == value for key, value in cost.items())
            and old['evidence'][reg['previous_B_evidence']['path']] == reg['previous_B_evidence']['sha256'],
            'B_restart_cost', 'Original failed B cost or status changed')
    delta = {'attempts': cost['actual_attempts'], 'tokens': cost['total_reported_tokens'],
             'model_seconds': cost['model_seconds'], 'unknown_usage': cost['unknown_usage'],
             'wall_seconds': closure['completed_epoch'] - evidence.manifest['created_epoch']}
    for group in ('B3600', 'combined'):
        for key, value in delta.items():
            totals[group][key] += value
    reported = old['registered_cumulative_usage_after_B']
    require(all(totals['combined'][key] == reported[key] for key in delta if key != 'wall_seconds'),
            'B_restart_cost', 'Prior cumulative costs were discounted')
    # The historical narrative used guard time for its one old probe's wall
    # clock. Its frozen registration correctly retained launch-to-end time.
    # Preserve that report and carry the larger original registered clock.
    probe = checked_file(previous['successful_probe'])
    probe_root = Path(previous['successful_probe']['path']).parent
    launch = strict_json((probe_root / 'launch_once.json').read_bytes())['started_epoch']
    correction = probe['ended_epoch'] - launch - probe['duration_seconds']
    require(correction >= 0 and abs(totals['combined']['wall_seconds'] - reported['wall_seconds'] - correction) < 1e-8,
            'B_restart_cost', 'Wall-clock difference is not the exact retained probe-clock correction')
    ids.add(evidence.manifest['run_id'])
    diagnostics, calls, base = verify_chain(reg['diagnostics'], model=MODEL)
    require(base == reg['previous_outcome'] and not ids & calls, 'B_restart_cost', 'Diagnostic ancestry or identity differs')
    for group in ('B3600', 'combined'):
        for key, value in diagnostics.items():
            totals[group][key] += value
    ids.update(calls)
    return totals, starts + 1, ids


def carried_recovery_count(reg):
    from .model_switch import carried_recovery_count as old_count
    from .recovery import _validate_recovery_records
    from .diagnostic_costs import verify_chain
    previous, evidence, _ = previous_evidence(reg)
    offset = old_count(previous)
    records = _validate_recovery_records(evidence, evidence.rows('transport_recoveries'), previous['recovery_policy'], previous)
    require(sorted(row['cohort_failure_ordinal'] for row in records.values()) == list(range(offset + 1, offset + len(records) + 1)),
            'B_restart_recovery', 'Prior failure ordinals changed')
    diagnostics, _, _ = verify_chain(reg['diagnostics'], model=MODEL)
    return offset + len(records) + diagnostics['unknown_usage']


def validate_grant(grant):
    require(grant['schema'] == GRANT and grant['user_instruction'] == USER_INSTRUCTION
            and grant['model_confirmation'] == MODEL_CONFIRMATION and grant['model'] == MODEL
            and grant['additional_B_caps'] == ADDITIONAL and grant['additional_B_starts'] == 1
            and grant['new_micro_runs'] == 0 and grant['retain_failures_and_costs'] is True
            and grant['reset_recovery_count'] is False and grant['full_B_requires_zero_unknown'] is True
            and grant['unknown_usage_policy'] == 'bounded_terminated_failures',
            'B_restart_grant', 'Explicit single Astra B, retained history and zero-unknown rule required')
    from .experiment import checked_file
    previous = checked_file(grant['previous_registration'])
    require(grant['recovery_policy'] == previous['recovery_policy']
            and grant['recovery_policy']['max_failures_per_cohort'] == 30,
            'B_restart_grant', 'Thirty cumulative exceptions and existing cooldowns must remain')
    return grant


def validate_registration(reg, root):
    from .experiment import checked_file
    from .B_model_switch import validate_entry_gate
    from .network import validate_binding
    grant = validate_grant(checked_file(reg['authorization']))
    require(reg['schema'] == SCHEMA and Path(reg['experiment_directory']).resolve() == root.resolve()
            and grant['experiment_directory'] == reg['experiment_directory'] and reg['model'] == MODEL
            and set(reg['cases']) == {'B3600'}, 'B_restart_registration', 'Only one fixed Astra B is in scope')
    for key in ('previous_registration', 'previous_B_evidence', 'previous_B_closure', 'previous_outcome', 'diagnostics',
                'transport_proxy', 'caps', 'recovery_policy', 'full_B_new_run_limit'):
        require(reg[key] == grant[key], 'B_restart_registration', 'Registration differs from grant: ' + key)
    previous, evidence, _ = previous_evidence(reg)
    cfg = strict_json((root / 'B3600.config.json').read_bytes())
    validate_config(cfg)
    oldroot = Path(reg['previous_registration']['path']).parent
    require(cfg == strict_json((oldroot / 'B3600.config.json').read_bytes())
            and cfg['window_seconds'] == 3600
            and reg['cases']['B3600'] == {'group': 'B3600', 'config_sha256': digest(cfg), 'initial_state_sha256': None},
            'B_restart_case', 'Physics, prompts, limits and cold initial state must remain identical')
    usage, starts, _ = carried_costs(reg)
    require(reg['carried_usage_at_registration'] == usage and starts == 2
            and reg['full_B_new_run_limit'] == starts + 1
            and carried_recovery_count(reg) == grant['prior_exception_count'] == 14,
            'B_restart_budget', 'Costs, B starts or failure quota reset')
    expected_caps = {group: {key: None if amount is None else usage[group][key] + (amount if group != 'micro' else 0)
                            for key, amount in ADDITIONAL.items()} for group in usage}
    require(reg['caps'] == expected_caps and reg['B_early_stop_on_new_unknown_usage'] is True,
            'B_restart_budget', 'Finite time limits or zero-unknown B rule changed')
    gate = checked_file(reg['entry_gate'])
    require(gate == strict_json((root / 'micro_gate.json').read_bytes()) == checked_file(previous['entry_gate']),
            'B_restart_entry', 'Original twenty-case prerequisite or model attribution changed')
    validate_entry_gate(previous, gate)
    report = checked_file({'path': reg['engineering_report'], 'sha256': reg['engineering_report_sha256']})
    before, after = evidence.manifest['fingerprint'], report['fingerprint']
    changed = {path for path in before['files'].keys() | after['files'].keys() if before['files'].get(path) != after['files'].get(path)}
    require(changed <= CONTROL_FILES and {key: value for key, value in before.items() if key not in ('files', 'sha256')} ==
            {key: value for key, value in after.items() if key not in ('files', 'sha256')}
            and digest({key: value for key, value in after.items() if key != 'sha256'}) == after['sha256'] == reg['fingerprint_sha256'],
            'B_restart_source', 'Only routing, cost/admission controls and verified recovery validation may change')
    tests = checked_file(report['test_evidence'])
    require(tests['all_pass'] and tests['source_unchanged'] and tests['remote_model_calls'] == 0
            and tests['fingerprint_sha256'] == after['sha256']
            and all(report['gates'][gate] == 'pass' for gate in ('G0', 'G1', 'G2', 'G3', 'G4')),
            'B_restart_source', 'Passing offline checks for the current frozen source required')
    for key in ('cli_binary', 'cli_sha256', 'model_catalog_sha256', 'provider_policy'):
        require(reg[key] == previous[key], 'B_restart_channel', 'CLI, model or provider changed')
    require(sha_bytes(Path(reg['model_catalog']).read_bytes()) == reg['model_catalog_sha256'],
            'B_restart_channel', 'Frozen model metadata changed')
    binding = validate_binding(reg['transport_proxy'])
    audit = checked_file(reg['diagnostics'])
    require(binding['route'] == audit['current_route']['underlying_route'] and reg['transport_proxy']['mode'] == 'system_tun',
            'B_restart_channel', 'B must use the exact successfully tested route')
    return reg
