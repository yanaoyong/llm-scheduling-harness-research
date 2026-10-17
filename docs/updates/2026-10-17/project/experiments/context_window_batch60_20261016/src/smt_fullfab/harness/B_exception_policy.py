"""User-authorized continuation of B without a cumulative exception quota.

This changes admission control only. Unknown usage remains unknown, the strict
cost audit remains unchanged, and the original sealed segment is never edited.
"""
from pathlib import Path

from .contracts import digest, require

SCHEMA = 'harness-B-exception-quota-removal-v1'
REGISTRATION = 'harness-B-network-restart-registration-v1'
INSTRUCTION = '取消异常额度这些限制，你的目标是不浪费的情况下测试推进B'
CONTROL_FILES = {
    'src/smt_fullfab/harness/B_exception_policy.py',
    'src/smt_fullfab/harness/amendment.py',
    'src/smt_fullfab/harness/recovery.py',
}


def validate(value, reg):
    from .experiment import checked_file, validate_closed_unknown
    from .evaluation import Evidence
    from .amendment import _source_proof
    require(value['schema'] == SCHEMA and reg['schema'] == REGISTRATION
            and value['base_registration_sha256'] == digest(reg),
            'B_exception_policy', 'Wrong frozen B registration')
    grant = checked_file(value['user_authorization'])
    require(grant['user_instruction'] == INSTRUCTION
            and grant['active_registration_sha256'] == digest(reg)
            and grant['cumulative_exception_limit'] is None
            and grant['repeat_exception_budget_approval_required'] is False
            and all(grant[k] is True for k in ('retain_all_prior_failure_and_cost_records',
                    'avoid_duplicate_model_calls', 'reconcile_returned_results_before_any_retry',
                    'retain_cooldown_and_progress_checks')),
            'B_exception_grant', 'Explicit quota removal and retained evidence required')
    require(value['original_policy'] == reg['recovery_policy']
            and value['policy'] == {**reg['recovery_policy'], 'max_failures_per_cohort': None}
            and value['continue_B_on_proven_terminal_unknown'] is True
            and value['strict_zero_unknown_audit_unchanged'] is True
            and all(value[k] is False for k in ('new_B_start', 'reset_costs', 'reset_time',
                                              'change_model', 'change_production_code')),
            'B_exception_policy', 'Only quota and operational early-stop controls may change')
    _source_proof(value, reg, allowed_files=CONTROL_FILES)
    old = Evidence(Path(value['sealed_failure']['path']).parent, value['sealed_failure']['sha256'])
    boundary = checked_file(value['recovery_boundary'])
    require(boundary['registration_sha256'] == digest(reg)
            and boundary['sealed_failure'] == value['sealed_failure']
            and old.manifest['admission']['experiment_sha256'] == digest(reg)
            and old.manifest['admission']['group'] == 'B3600'
            and old.manifest['run_id'] == grant['active_run_id'] == boundary['run_id']
            and old.manifest['created_epoch'] == boundary['created_epoch']
            and old.manifest['deadline_epoch'] == boundary['deadline_epoch']
            and old.value['head'] == boundary['head']
            and old.value['head']['phase'] == 'CLOSED'
            and old.value['head']['stop_reason'] == 'B_zero_unknown_cost_gate_impossible'
            and old.rows('transport_recoveries') == boundary['recoveries']
            and digest(old.rows('attempts')) == boundary['attempts_sha256']
            and digest(old.rows('commits')) == boundary['commits_sha256']
            and digest(old.value['physical']) == boundary['physical_refs_sha256'],
            'B_exception_boundary', 'Original committed state, clocks, costs or failure proof changed')
    attempts = old.rows('attempts')
    require(attempts and not any(a['status'] in ('reserved', 'started', 'unknown') for a in attempts.values()),
            'B_exception_pending', 'In-flight results cannot be retried')
    unknown = {k: a for k, a in attempts.items() if a['channel'] == 'codex' and a.get('usage') is None}
    require(set(unknown) == set(boundary['recoveries']) and unknown,
            'B_exception_pending', 'Every unknown must have an existing terminal-failure proof')
    for aid, attempt in unknown.items():
        validate_closed_unknown(old, attempt, allow_guarded_timeout=True)
        require(boundary['recoveries'][aid]['attempt_sha256'] == digest(attempt),
                'B_exception_boundary', 'Failure identity differs')
    require(Path(value['continuation_directory']).resolve().parent
            == Path(reg['experiment_directory']).resolve() / 'continuations',
            'B_exception_boundary', 'Continuation must remain in the original experiment')
    return value


def operational_continuation_allowed(reg):
    from .amendment import amendment_for
    value = amendment_for(reg)
    return bool(value and value['schema'] == SCHEMA and value['continue_B_on_proven_terminal_unknown'])
