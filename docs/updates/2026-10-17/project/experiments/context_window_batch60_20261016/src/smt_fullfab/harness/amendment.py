"""Explicit control-policy revisions; original registrations and seals stay intact.

Only explicitly authorized control policy and evidence routing may change.
Model, physical code, inputs, attempt identities, and clocks remain bound.
"""
from pathlib import Path
from .contracts import digest, require, strict_json

CONTROL_FILES = {
    'src/smt_fullfab/harness/amendment.py',
    'src/smt_fullfab/harness/recovery.py',
    'src/smt_fullfab/harness/runtime.py',
    'src/smt_fullfab/harness/experiment.py',
    'src/smt_fullfab/harness/p5.py',
    'src/smt_fullfab/harness/evaluation.py',
}
COUNT_SCHEMA = 'harness-call-count-amendment-v1'


def _source_proof(value, reg, *, allowed_files=CONTROL_FILES):
    from .experiment import checked_file
    old = checked_file({'path':reg['engineering_report'], 'sha256':reg['engineering_report_sha256']})
    new = checked_file(value['engineering_report'])
    a, b = old['fingerprint'], new['fingerprint']
    require(a['sha256'] == reg['fingerprint_sha256'] and b['sha256'] == value['active_fingerprint_sha256'] and
            digest({k:v for k,v in b.items() if k != 'sha256'}) == b['sha256'],
            'amendment_source', 'Source proof differs')
    changed = {p for p in a['files'].keys() | b['files'].keys() if a['files'].get(p) != b['files'].get(p)}
    require(changed <= allowed_files and
            {k:v for k,v in a.items() if k not in ('files','sha256')} ==
            {k:v for k,v in b.items() if k not in ('files','sha256')},
            'amendment_source', 'Physical code, data, dependencies, or protocol changed')
    tests = checked_file(new['test_evidence'])
    require(all(new['gates'][g] == 'pass' for g in ('G0','G1','G2','G3','G4')) and
            tests['all_pass'] is True and tests['source_unchanged'] is True and
            tests['fingerprint_sha256'] == b['sha256'] and tests['remote_model_calls'] == 0,
            'amendment_tests', 'Passing offline control checks required')


def validate_count_amendment(value, reg):
    from .experiment import checked_file
    require(reg['schema'] == 'harness-model-switch-registration-v1' and
            value['base_registration_sha256'] == digest(reg), 'amendment', 'Wrong frozen cohort')
    grant = checked_file(value['user_authorization'])
    require(grant['schema'] == 'harness-call-count-user-authorization-v1' and
            grant['base_registration_sha256'] == digest(reg) and
            '取消调用次数的硬性门槛' in grant['user_instruction'] and
            grant['call_count_enforcement'] == 'advisory' and
            all(grant[k] is True for k in ('same_twenty_required','retained_completed_results','retain_correctness_audit','full_B_requires_zero_unknown')) and
            all(grant[k] is False for k in ('reset_costs','reset_time','reset_recovery_count','change_model','change_physical_code','change_time_limits')) and
            grant['max_retries_per_request'] == 2 and grant['cooldown_seconds'] == [60,180] and
            grant['exception_limit'] == 30 and grant['full_B_new_run_limit'] == 1,
            'amendment_grant', 'Explicit advisory-only acceptance authorization required')
    require(value['metrics'] == {**reg['micro_metrics'], 'enforcement':'advisory'},
            'amendment_metrics', 'Keep all original count statistics and twenty cases')
    # The broader unknown-cost grant covers only proven terminated timeouts.
    # The retry count, cooldown, total allowance and all time budgets stay fixed.
    timeout = checked_file(value['timeout_authorization'])
    require(timeout['exception_limit'] == 30 and timeout['max_retries_per_request'] == 2 and
            timeout['cooldown_seconds'] == [60,180] and timeout['retain_unknown_usage'] is True and
            timeout['only_guarded_no_answer_timeouts'] is True and
            '未知用量也批准例外' in timeout['user_instruction'] and
            timeout['limit_instruction'] == '异常额度放宽到30次',
            'amendment_grant', 'Bounded unknown-cost authorization required')
    require(value['original_policy'] == reg['recovery_policy'] and
            value['policy'] == {**reg['recovery_policy'], 'allowed_failure_kinds':reg['recovery_policy']['allowed_failure_kinds']+['guarded_timeout']},
            'amendment_policy', 'Recovery limits and cooldown cannot change')
    require(all(cap['attempts'] is None for cap in reg['caps'].values()) and
            all(entry.get('max_attempts_per_fragment') is None for entry in reg['cases'].values()),
            'amendment_metrics', 'No hidden model call-count ceiling may remain')
    _source_proof(value, reg)
    boundary = checked_file(value['recovery_boundary'])
    require(boundary['registration_sha256'] == digest(reg) and boundary['sealed_failure'] == value['sealed_failure'],
            'amendment_boundary', 'Original stopped boundary required')
    from .evaluation import Evidence
    from .experiment import account_records
    from .model_switch import carried_recovery_count
    stopped = Evidence(Path(value['sealed_failure']['path']).parent, value['sealed_failure']['sha256'])
    require(stopped.manifest['admission']['experiment_sha256'] == digest(reg) and
            stopped.manifest['run_id'] == boundary['failed_run_id'] and
            stopped.manifest['created_epoch'] == boundary['created_epoch'] and
            stopped.manifest['deadline_epoch'] == boundary['deadline_epoch'] and
            stopped.rows('transport_recoveries') == boundary['recoveries'] and
            boundary['exceptions_used_before_revision'] == carried_recovery_count(reg)+len(boundary['recoveries']),
            'amendment_boundary', 'Run identity, clocks, or consumed exception slots changed')
    retained_ids = {stopped.manifest['admission']['case_id']}
    for saved in boundary['completed']:
        row = checked_file(saved['fragment'])
        audit = checked_file(saved['audit'])
        seal = checked_file(saved['evidence'])
        require(row['id'] in reg['cases'] and row['accepted'] is True and audit['valid'] is True and
                row['evidence_sha256'] == audit['evidence_sha256'] == saved['evidence']['sha256'] and
                seal['head']['phase'] == 'CLOSED' and row['attempts'] == audit['cost_accounting']['actual_attempts'],
                'amendment_boundary', 'Retained accepted result changed')
        retained_ids.add(row['id'])
    require(len({checked_file(x['fragment'])['id'] for x in boundary['completed']}) == len(boundary['completed']),
            'amendment_boundary', 'Duplicate retained case')
    require(retained_ids == {case for case,group,rid,path,created in account_records(reg['experiment_directory'])
                             if created <= boundary['captured_epoch']},
            'amendment_boundary', 'A pre-revision case was omitted or restarted')
    return value


def validate_amendment(value, reg):
    from .experiment import checked_file
    from .B_exception_policy import SCHEMA as B_EXCEPTION_SCHEMA, validate as validate_B_exception
    if value.get('schema') == B_EXCEPTION_SCHEMA:
        return validate_B_exception(value, reg)
    if value.get('schema') == COUNT_SCHEMA:
        return validate_count_amendment(value, reg)
    require(value['schema'] == 'harness-recovery-amendment-v1' and
            value['base_registration_sha256'] == digest(reg), 'amendment', 'Wrong frozen cohort')
    require(reg['schema'] == 'harness-model-switch-registration-v1', 'amendment', 'Only the fixed Sol cohort is amended')
    grant = checked_file(value['user_authorization'])
    require(grant['user_instruction'] == '异常额度放宽到30次' and
            grant['old_cohort_limit'] == 5 and grant['new_cohort_limit'] == 30 and
            grant['already_used_failures_retained'] is True and
            grant['max_retries_per_request'] == 2 and grant['cooldown_seconds'] == [60, 180] and
            all(grant[k] is False for k in ('change_model', 'change_business_acceptance', 'change_B_zero_unknown_rule')),
            'amendment_grant', 'Exact explicit limit-only authorization required')
    require(value['original_policy'] == reg['recovery_policy'] and
            value['policy'] == {**reg['recovery_policy'], 'max_failures_per_cohort': 30},
            'amendment_policy', 'Only the cohort exception ceiling may change')
    old = checked_file({'path':reg['engineering_report'], 'sha256':reg['engineering_report_sha256']})
    new = checked_file(value['engineering_report'])
    a, b = old['fingerprint'], new['fingerprint']
    require(a['sha256'] == reg['fingerprint_sha256'] and b['sha256'] == value['active_fingerprint_sha256'] and
            digest({k:v for k,v in b.items() if k != 'sha256'}) == b['sha256'],
            'amendment_source', 'Source proof differs')
    changed = {p for p in a['files'].keys() | b['files'].keys() if a['files'].get(p) != b['files'].get(p)}
    require(changed <= CONTROL_FILES and
            {k:v for k,v in a.items() if k not in ('files','sha256')} ==
            {k:v for k,v in b.items() if k not in ('files','sha256')},
            'amendment_source', 'Physical code, data, dependencies, or protocol changed')
    tests = checked_file(new['test_evidence'])
    require(all(new['gates'][g] == 'pass' for g in ('G0','G1','G2','G3','G4')) and
            tests['all_pass'] is True and tests['source_unchanged'] is True and
            tests['fingerprint_sha256'] == b['sha256'] and tests['remote_model_calls'] == 0,
            'amendment_tests', 'Passing offline control checks required')
    baseline = checked_file(value['recovery_boundary'])
    require(baseline['registration_sha256'] == digest(reg) and len(baseline['recoveries']) == 5 and
            sorted(r['cohort_failure_ordinal'] for r in baseline['recoveries'].values()) == list(range(1,6)),
            'amendment_boundary', 'The original five exceptions must stay counted')
    return value


def amendment_for(reg):
    from .B_exception_policy import REGISTRATION as B_REGISTRATION
    if reg.get('schema') == B_REGISTRATION:
        path = Path(reg['experiment_directory']) / 'exception_policy_amendment.json'
        return validate_amendment(strict_json(path.read_bytes()), reg) if path.exists() else None
    if reg.get('schema') != 'harness-model-switch-registration-v1':
        return None
    paths = [Path(reg['experiment_directory']) / name for name in ('recovery_amendment.json','acceptance_amendment.json')]
    paths = [p for p in paths if p.exists()]
    require(len(paths) <= 1, 'amendment', 'Ambiguous active control revision')
    return validate_amendment(strict_json(paths[0].read_bytes()), reg) if paths else None


def effective_micro_metrics(reg):
    value = amendment_for(reg)
    return value['metrics'] if value and value['schema'] == COUNT_SCHEMA else {
        **reg.get('micro_metrics', {'n_min':20,'median_max':3,'p95_max':5}), 'enforcement':'hard'}


def validate_advisory_B_gate(reg, gate):
    """Advisory efficiency never substitutes for all twenty proven acceptances."""
    value = amendment_for(reg)
    if not value or value['schema'] != COUNT_SCHEMA:
        return
    from .contracts import sha_bytes, within_cap
    from .evaluation import microbenchmark_gate
    from .experiment import cumulative_usage, resource_status
    root = Path(reg['experiment_directory'])
    rows = []
    for case, entry in reg['cases'].items():
        if entry['group'] != 'micro':
            continue
        path = case_directory(root, case)
        require((path/'fragment_result.json').exists() and (path/'audit/acceptance.json').exists(),
                'micro_gate', 'Every original fragment must finish with an independent audit')
        row = strict_json((path/'fragment_result.json').read_bytes())
        audit = strict_json((path/'audit/acceptance.json').read_bytes())
        require(row['id'] == case and row['accepted'] is True and audit['valid'] is True and
                row['attempts'] == audit['cost_accounting']['actual_attempts'] and
                row['evidence_sha256'] == audit['evidence_sha256'] == sha_bytes((path/'evidence_manifest.json').read_bytes()),
                'micro_gate', 'Fragment result, audit, or sealed identity differs')
        rows.append(row)
    expected = microbenchmark_gate(rows, metrics=value['metrics'])
    require(len(rows) == 20 and gate['registered_count'] == 20 and gate['fragments'] == rows and
            gate['experiment_sha256'] == digest(reg) and gate.get('control_amendment_sha256') == digest(value) and
            all(gate[k] == expected[k] for k in ('n','complete','correctness_pass','call_count_enforcement','median','p95_nearest_rank','efficiency_target_pass')) and
            expected['pass'] and gate['pass'] and gate['resource_pass'],
            'micro_gate', 'B requires the exact complete advisory gate, not a rewritten pass flag')
    usage = cumulative_usage({'experiment_directory':str(root),'experiment_sha256':digest(reg)})
    status = resource_status(reg, usage)
    require(all(usage[g]['pending'] == 0 and status['unexempt_unknown_usage'][g] == 0 and
                all(within_cap(usage[g][k], v) for k,v in reg['caps'][g].items()) for g in ('micro','combined')),
            'micro_gate', 'Retained time/cost/unknown protections must still permit B')


def effective_policy(reg, original):
    value = amendment_for(reg)
    return value['policy'] if value else original


def policy_for_record(reg, current, attempt_id, row):
    value = amendment_for(reg)
    if value and row['policy_sha256'] == digest(value['original_policy']):
        from .experiment import checked_file
        boundary = checked_file(value['recovery_boundary'])
        require(boundary['recoveries'].get(attempt_id) == row, 'amendment_boundary', 'Old exception changed or added after revision')
        return value['original_policy']
    return current


def registered_source(reg, fp):
    """Select the matching tested control revision, never rewrite old proof."""
    from .experiment import checked_file
    value = amendment_for(reg)
    from .source_revision import for_amendment, revision_chain
    for revision in revision_chain(for_amendment(reg, value)):
        if fp['sha256'] == revision['active_fingerprint_sha256']:
            return checked_file(revision['engineering_report'])
    if fp['sha256'] == reg['fingerprint_sha256']:
        return checked_file({'path':reg['engineering_report'], 'sha256':reg['engineering_report_sha256']})
    require(value is not None and fp['sha256'] == value['active_fingerprint_sha256'],
            'registration_source', 'No authorized source revision')
    return checked_file(value['engineering_report'])


def validate_runtime_source(manifest, current):
    if manifest['fingerprint'] == current:
        return
    from .experiment import registration
    require(manifest.get('admission') is not None, 'fingerprint_changed', 'Offline source migration is not authorized')
    reg = registration(manifest['admission'])
    value = amendment_for(reg)
    from .source_revision import for_amendment, live_view, validate_marker, revision_chain
    matching = [r for r in revision_chain(for_amendment(reg, value)) if current['sha256'] == r['active_fingerprint_sha256']]
    if matching:
        require(manifest['fingerprint']['sha256'] == reg['fingerprint_sha256'],
                'fingerprint_changed', 'Original B identity changed')
        validate_marker(live_view(case_directory(reg['experiment_directory'], 'B3600')), reg, value,
                        required=True, through_revision=digest(matching[0]))
        registered_source(reg, current)
        return
    require(value is not None and manifest['fingerprint']['sha256'] == reg['fingerprint_sha256'] and
            current['sha256'] == value['active_fingerprint_sha256'],
            'fingerprint_changed', 'No explicit tested control revision')
    registered_source(reg, current)


def case_directory(directory, case):
    """Account identity is stable even when a sealed failure gets a new segment."""
    from .experiment import account_records
    root = Path(directory).resolve()
    rows = [r for r in account_records(root) if r[0] == case]
    require(len(rows) <= 1, 'case_duplicate', case)
    return Path(rows[0][3]) if rows else root / 'runs' / case


def validate_continuation(evidence):
    rows = evidence.rows('control_continuations')
    if not rows:
        return
    from .evaluation import Evidence
    from .experiment import registration, checked_file
    value = amendment_for(registration(evidence.manifest['admission']))
    require(value is not None and len(rows) == 1, 'continuation', 'Exactly one explicit amended segment required')
    row = next(iter(rows.values()))
    require(row['amendment_sha256'] == digest(value) and row['source'] == value['sealed_failure'],
            'continuation', 'Unregistered predecessor seal')
    old = Evidence(Path(row['source']['path']).parent, row['source']['sha256'])
    from .B_exception_policy import SCHEMA as B_EXCEPTION_SCHEMA
    amended_B = value['schema'] == B_EXCEPTION_SCHEMA
    require(old.manifest == evidence.manifest and old.value['head']['phase'] == 'CLOSED' and
            (amended_B or not old.rows('commits')), 'continuation', 'Only an authorized sealed failure can continue')
    events = evidence.value['events']
    require(events[:len(old.value['events'])] == old.value['events'] and
            evidence.value['physical'][:len(old.value['physical'])] == old.value['physical'],
            'continuation', 'Original workflow or physical evidence changed')
    require(all(evidence.rows('attempts').get(k) == v for k,v in old.rows('attempts').items()),
            'continuation', 'Original failures or costs changed')
    require(all(evidence.rows('commits').get(k) == v for k,v in old.rows('commits').items()),
            'continuation', 'Original accepted decisions changed')
    marker = events[len(old.value['events'])]
    require(marker['kind'] == 'control_policy_continuation' and evidence.get(marker['payload_ref']) == row and
            row['head_before'] == old.value['head'] and row['no_new_model_call'] is True,
            'continuation', 'Missing append-only continuation boundary')
    if evidence.rows('control_source_revisions'):
        from .source_revision import validate_marker
        # Sealed Evidence stores refs in value; live views expose records directly.
        if not hasattr(evidence, 'records'):
            evidence.records = evidence.value['records']
        validate_marker(evidence, registration(evidence.manifest['admission']), value)


def continue_sealed_failure(directory):
    """Copy a bounded transport-only seal into a new append-only segment.

    The shared account keeps its run ID and start time. The old directory is never
    opened for writing; the new directory contains the entire original ledger.
    """
    import shutil
    import sqlite3
    import time
    from .contracts import encode, fingerprint
    from .evaluation import Evidence, audit_cost
    from .experiment import account_records, experiment_lock
    from .recovery import failure_kind
    from .store import Store
    root = Path(directory).resolve()
    reg = strict_json((root/'experiment.json').read_bytes())
    value = amendment_for(reg)
    require(value is not None, 'continuation', 'No explicit amendment')
    registered_source(reg, fingerprint())
    source = value['sealed_failure']
    old = Evidence(Path(source['path']).parent, source['sha256'])
    adm = old.manifest['admission']
    target = Path(value['continuation_directory']).resolve()
    from .B_exception_policy import SCHEMA as B_EXCEPTION_SCHEMA
    amended_B = value['schema'] == B_EXCEPTION_SCHEMA
    require(adm['experiment_sha256'] == digest(reg) and adm['group'] == ('B3600' if amended_B else 'micro') and
            target.parent == root/'continuations' and target != old.path,
            'continuation', 'Wrong cohort, group, or continuation directory')
    attempts = old.rows('attempts')
    if amended_B:
        require(old.value['head']['phase'] == 'CLOSED'
                and old.value['head']['stop_reason'] == 'B_zero_unknown_cost_gate_impossible'
                and audit_cost(old)['pending_attempts'] == 0,
                'continuation', 'Only the explicitly authorized closed B boundary may continue')
        for attempt in attempts.values():
            if attempt['channel'] == 'codex' and attempt.get('usage') is None:
                require(failure_kind(old, attempt) in value['policy']['allowed_failure_kinds'],
                        'continuation', 'An unknown request with an answer cannot be regenerated')
    elif value['schema'] == COUNT_SCHEMA:
        require(attempts and not old.rows('commits') and old.value['head']['phase'] == 'CLOSED' and
                (old.value['head']['stop_reason'] == 'model_transport_or_unknown_usage' or
                 old.value['head']['stop_reason'].startswith('fragment_error:user_stop')),
                'continuation', 'Only the exact stopped uncommitted boundary can continue')
        require(audit_cost(old)['pending_attempts'] == 0, 'continuation', 'In-flight requests cannot migrate')
        for attempt in attempts.values():
            if attempt['channel'] == 'codex' and attempt.get('usage') is None:
                require(failure_kind(old, attempt) in value['policy']['allowed_failure_kinds'],
                        'continuation', 'Unclosed or ineligible unknown request')
    else:
        require(len(attempts) == 1 and not old.rows('commits') and not old.rows('transport_recoveries') and
                old.value['head']['phase'] == 'CLOSED' and old.value['head']['stop_reason'] == 'model_transport_or_unknown_usage',
                'continuation', 'Only the sealed first-call quota failure may be continued')
        attempt = next(iter(attempts.values()))
        require(failure_kind(old, attempt) in value['policy']['allowed_failure_kinds'] and
                audit_cost(old)['pending_attempts'] == 0, 'continuation', 'Pending or ineligible failure')
    with experiment_lock(adm):
        rows = [r for r in account_records(root) if r[0] == adm['case_id']]
        require(len(rows) == 1 and rows[0][2] == old.manifest['run_id'] and
                Path(rows[0][3]) == old.path and rows[0][4] == old.manifest['created_epoch'],
                'continuation_account', 'Original account already moved or replaced')
        target.mkdir(parents=True, exist_ok=False)
        shutil.copytree(old.path/'objects', target/'objects')
        shutil.copytree(old.path/'exports', target/'exports')
        shutil.copy2(old.path/'manifest.json', target/'manifest.json')
        with sqlite3.connect(f'file:{old.path}/events.sqlite3?mode=ro', uri=True) as src, sqlite3.connect(target/'events.sqlite3') as dst:
            src.backup(dst)
        store = Store(target)
        try:
            require(store.meta('head') == old.value['head'], 'continuation', 'Sealed source moved')
            row = {'source':source, 'amendment_sha256':digest(value), 'head_before':store.meta('head'),
                   'no_new_model_call':True, 'continued_epoch':time.time(),
                   'active_fingerprint_sha256':value['active_fingerprint_sha256']}
            with store.transaction():
                key = 'B-exception-quota-removed' if amended_B else ('call-count-advisory' if value['schema'] == COUNT_SCHEMA else 'recovery-limit-30')
                store.record('control_continuations', key, row)
                store.event('control_policy_continuation', row)
                head = store.meta('head')
                head.update(phase='OBSERVED', stop_reason=None, segment=head['segment']+1)
                store.set_meta('head', head)
            store.verify()
        finally:
            store.close()
        with sqlite3.connect(root/'account.sqlite3') as db:
            db.execute('PRAGMA synchronous=FULL')
            changed = db.execute('UPDATE runs SET directory=? WHERE case_id=? AND run_id=? AND directory=?',
                                 (str(target), adm['case_id'], old.manifest['run_id'], str(old.path))).rowcount
            require(changed == 1, 'continuation_account', 'Account transition lost ownership')
        (target/'continuation_receipt.json').write_bytes(encode(row))
    return target
