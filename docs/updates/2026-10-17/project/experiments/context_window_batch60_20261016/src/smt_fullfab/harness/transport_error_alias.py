"""Reviewed exact terminal-error alias and bounded same-run resource allowance.

No connection probe, business replay, prompt change, or missing-usage estimate.
The alias requires its immutable tenth source marker and closed-process proof.
"""
from pathlib import Path
from types import SimpleNamespace
import time

from .contracts import digest, require, strict_json

MESSAGE = 'stream disconnected before completion: error sending request'
REPAIR = ['closed_request_error_alias_and_bounded_runway']
KEY = 'terminal-error-alias-runway'
ACTIVATIONS = 'control_error_alias_activations'
FILES = {'src/smt_fullfab/harness/transport_error_alias.py',
         'src/smt_fullfab/harness/recovery.py',
         'src/smt_fullfab/harness/source_revision.py',
         'src/smt_fullfab/harness/wall_budget.py'}


def validate_grant(grant, manifest):
    before = grant['limits_before']
    require(grant['schema'] == 'harness-error-alias-runway-authorization-v1'
            and grant['user_instruction'] == '取消异常额度这些限制，你的目标是不浪费的情况下测试推进B'
            and grant['user_budget_instruction'] == '如何继续，批准需要的预算以及可能超标的预算'
            and grant['network_instruction'] == '不要管网络的问题了，我会人为的管理切换的'
            and grant['run_id'] == manifest['run_id']
            and manifest['admission']['group'] == 'B3600'
            and grant['original_created_epoch'] == manifest['created_epoch']
            and grant['original_deadline_epoch'] == manifest['deadline_epoch']
            and grant['same_run_only'] is True
            and grant['preserve_all_costs_and_results'] is True
            and grant['strict_zero_unknown_audit_unchanged'] is True
            and all(grant[k] is False for k in ('new_B_start', 'reset_time', 'reset_costs',
                                               'change_model', 'change_production_decisions', 'change_network'))
            and grant['exact_error_message'] == MESSAGE and grant['failure_kind'] == 'connection'
            and grant['max_retries_per_request'] == 2 and grant['cooldown_seconds'] == [60, 180]
            and grant['additional_wall_seconds'] == 21600
            and grant['additional_storage_bytes'] == 2147483648
            and grant['additional_model_seconds'] == 0
            and before['wall_seconds'] == 93600 and before['model_seconds'] == 36000
            and before['storage_bytes'] == 4294967296
            and grant['limits_after'] == {**before, 'wall_seconds': 115200, 'storage_bytes': 6442450944},
            'error_alias_grant', 'Only exact same-run alias and bounded wall/storage allowance are authorized')
    return grant


def closed_alias_proof(evidence, attempt):
    from .experiment import validate_closed_unknown
    require(attempt['channel'] == 'codex' and attempt['status'] == 'responded'
            and attempt['usage'] is None and attempt['transport']['timed_out'] is False,
            'error_alias_proof', 'Only a settled non-timeout failure with unknown usage qualifies')
    validate_closed_unknown(evidence, attempt)
    receipt = strict_json(evidence.raw(attempt['transport']['original_guard_files']['receipt.json']))
    require(receipt['stop_reason'] == 'command_exit' and receipt['owner_eof'] is False
            and receipt['launch_error'] is None and receipt['guard_error'] is None,
            'error_alias_proof', 'Ownership loss or an incomplete guard cannot authorize another request')
    events = [strict_json(line) for line in evidence.raw(attempt['transport']['events_ref']).splitlines() if line.strip()]
    errors = [e['error']['message'] for e in events if e.get('type') == 'turn.failed']
    require(errors == [MESSAGE] and not any(e.get('item', {}).get('type') == 'agent_message' for e in events),
            'error_alias_proof', 'Only the exact retained no-answer terminal error is recognized')
    return 'connection'


def validate_boundary(boundary, manifest, grant):
    from .recovery import LiveEvidence
    validate_grant(grant, manifest)
    view = object.__new__(LiveEvidence)
    view.path = Path(boundary['manifest']['path']).parent
    view.records = boundary['records']
    view.manifest = manifest
    attempts = view.rows('attempts')
    aid = boundary['closed_terminal_failure_id']
    attempt = attempts[aid]
    require(aid == grant['closed_terminal_failure_id']
            and digest(attempt) == grant['closed_terminal_failure_sha256']
            and attempt['index'] + 1 == grant['first_actual_call']
            and attempt == max(attempts.values(), key=lambda a: a['index'])
            and attempt['context_ref'] == boundary['head']['context_ref'],
            'error_alias_boundary', 'The exact last retained failed request must anchor the repair')
    unfinished = [a['attempt_id'] for a in attempts.values()
                  if a['status'] in ('reserved', 'started', 'unknown')
                  or (a['status'] == 'responded' and a['attempt_id'] not in view.records.get('transport_recoveries', {}))]
    require(unfinished == [aid], 'error_alias_boundary', 'No other unresolved request may be skipped')
    closed_alias_proof(view, attempt)
    return attempt


def authorize_alias(evidence, attempt):
    from .experiment import checked_file
    from .amendment import amendment_for
    from .source_revision import for_amendment, live_view, validate_marker
    row = evidence.rows('control_source_revisions').get(KEY)
    require(row is not None, 'error_alias_authorization', 'Exact alias requires an installed reviewed source marker')
    admission = evidence.manifest['admission']
    root = Path(admission['experiment_directory'])
    reg = checked_file({'path': str(root / 'experiment.json'), 'sha256': admission['experiment_sha256']})
    value = for_amendment(reg, amendment_for(reg))
    require(value['repairs'] == REPAIR and row['revision_sha256'] == digest(value),
            'error_alias_authorization', 'A different source revision cannot authorize this alias')
    grant = validate_grant(checked_file(value['user_authorization']), evidence.manifest)
    require(attempt['index'] + 1 >= grant['first_actual_call'],
            'error_alias_authorization', 'The alias cannot relabel earlier historical requests')
    view = evidence if hasattr(evidence, 'value') else live_view(evidence.path)
    validate_marker(view, reg, amendment_for(reg), required=True, through_revision=digest(value))
    return closed_alias_proof(evidence, attempt)


def validate_activation(evidence, value, boundary):
    """Require a durable activation before any later request; allow staged installation."""
    aid = boundary['closed_terminal_failure_id']
    failed = evidence.get(boundary['records']['attempts'][aid])
    rows = evidence.rows(ACTIVATIONS)
    if not rows:
        require(not any(a['index'] > failed['index'] for a in evidence.rows('attempts').values()),
                'error_alias_activation', 'New requests require explicit recorded activation')
        return None
    require(set(rows) == {KEY}, 'error_alias_activation', 'Only one activation may exist')
    row = rows[KEY]
    recovery_ref = evidence.records.get('transport_recoveries', {}).get(aid)
    require(recovery_ref is not None and row['recovery_ref'] == recovery_ref,
            'error_alias_activation', 'Original bounded recovery proof must be retained')
    recovery = evidence.get(recovery_ref)
    after = {**boundary['head'], 'phase': 'OBSERVED', 'stop_reason': None}
    require(row['schema'] == 'harness-error-alias-activation-v1'
            and row['run_id'] == evidence.manifest['run_id']
            and row['source_revision_sha256'] == digest(value)
            and row['boundary'] == value['boundary'] and row['attempt_id'] == aid
            and row['attempt_sha256'] == digest(failed)
            and row['head_before'] == boundary['head'] and row['head_after'] == after
            and row['new_model_calls'] == 0 and row['business_action_replayed'] is False
            and recovery['attempt_id'] == aid and recovery['failure_kind'] == 'connection'
            and recovery['request_failure_ordinal'] == 1
            and recovery['not_before_epoch'] == failed['finished_epoch'] + 60,
            'error_alias_activation', 'Activation cannot alter identity, decisions, clocks, costs, or cooldown')
    n = boundary['event_count']
    events = evidence.value['events']
    require(len(events) > n + 2 and events[n+1]['kind'] == 'transport_recovery_scheduled'
            and evidence.get(events[n+1]['payload_ref']) == recovery
            and events[n+2]['kind'] == 'terminal_error_alias_resumed'
            and evidence.get(events[n+2]['payload_ref']) == row,
            'error_alias_activation', 'Recovery and reactivation must follow the immutable source marker')
    return row


def activate(directory):
    """After tested source installation, reopen only this closed no-answer checkpoint."""
    from .amendment import amendment_for, case_directory
    from .experiment import checked_file, experiment_lock
    from .source_revision import for_amendment, live_view, validate_marker, _check_prefix
    from .store import Store
    from .recovery import schedule_recovery
    root = Path(directory).resolve()
    reg = strict_json((root / 'experiment.json').read_bytes())
    base = amendment_for(reg)
    value = for_amendment(reg, base)
    require(value['repairs'] == REPAIR, 'error_alias_activation', 'Exact tested tenth revision required')
    boundary = checked_file(value['boundary'])
    target = case_directory(root, 'B3600')
    with experiment_lock({'experiment_directory': str(root)}):
        store = Store(target)
        try:
            store.verify()
            view = live_view(target)
            validate_marker(view, reg, base, required=True)
            _check_prefix(view, boundary)
            if view.rows(ACTIVATIONS):
                return validate_activation(view, value, boundary)
            require(store.meta('head') == boundary['head'], 'error_alias_activation', 'Checkpoint moved before recovery')
            aid = boundary['closed_terminal_failure_id']
            prior = view.rows('transport_recoveries').get(aid)
            require(len(view.value['events']) == boundary['event_count'] + (2 if prior else 1),
                    'error_alias_activation', 'Only source installation and optional durable scheduling may precede activation')
            runtime = SimpleNamespace(store=store, manifest=view.manifest, config=view.manifest['config'])
            recovery = schedule_recovery(runtime, aid)
            require(recovery is not None and recovery['request_failure_ordinal'] == 1
                    and recovery['failure_kind'] == 'connection',
                    'error_alias_activation', 'Original bounded recovery must qualify without resetting counters')
            after = {**boundary['head'], 'phase': 'OBSERVED', 'stop_reason': None}
            row = {'schema': 'harness-error-alias-activation-v1', 'run_id': view.manifest['run_id'],
                   'recorded_epoch': time.time(), 'source_revision_sha256': digest(value),
                   'boundary': value['boundary'], 'attempt_id': aid,
                   'attempt_sha256': digest(view.rows('attempts')[aid]),
                   'recovery_ref': store.ref('transport_recoveries', aid),
                   'head_before': boundary['head'], 'head_after': after,
                   'new_model_calls': 0, 'business_action_replayed': False}
            with store.transaction():
                store.set_meta('head', after)
                store.record(ACTIVATIONS, KEY, row)
                store.event('terminal_error_alias_resumed', row)
            validate_marker(live_view(target), reg, base, required=True)
            return row
        finally:
            store.close()
