"""One stopped, unsettled call may admit one genuinely new B registration.

No finish, original account, guard, model result or old run is rewritten.
This is admission evidence, not proof of provider completion/usage or acceptance.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import uuid

SCHEMA = 'smt-B-stopped-pending-admission-v1'
EVENT = 'stopped_pending_diagnosed'
OLD_CALL_ID = '74508a8f-b5d3-4670-9ed3-ed2ee753a981'
OLD_RUN_NAME = 'B_1701_1h_delta_v4'
ROOT_COMPLETION = 'artifacts/smt_fullfab_diagnostics/B_delta_actual_host_observation_v4/root_completion.json'
ROOT_COMPLETION_SHA256 = '76bf98f87a67a4f0c713c62b5e57e6707a2627c82379fca6f95026d987460852'
GUARD_SHA256 = 'b421a4872206e4f1322961efbf26001396a23b7aa17d9dbf39ece97d470db5bc'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def same(left, right):
    return canonical(left) == canonical(right)


def _identity(st):
    return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]


def _read(path, expected, refs):
    path = Path(path)
    require(not path.is_symlink(), 'stop evidence symbolic link')
    before = _identity(path.stat())
    require(before[2] <= 1048576, 'stop certificate exceeds bounded small-file contract')
    with path.open('rb') as stream:
        require(_identity(os.fstat(stream.fileno())) == before, 'stop evidence changed at open')
        raw = stream.read(1048577)
        require(_identity(os.fstat(stream.fileno())) == before, 'stop evidence changed during read')
    require(_identity(path.stat()) == before and hashlib.sha256(raw).hexdigest() == expected,
            'stop evidence original hash/identity mismatch')
    value = json.loads(raw)
    canonical(value)  # Reject non-finite values; original trusted SHA binds JSON bytes.
    refs[str(path)] = {'sha256': expected, 'bytes': len(raw), 'file_identity': before}
    return value


def _fence(refs):
    for name, ref in refs.items():
        path = Path(name)
        require(not path.is_symlink() and _identity(path.stat()) == ref['file_identity'],
                'stop evidence changed after its original read')


def verify_stop_evidence(root, *, stop_config=None):
    """Read only small original certificates. stop_config is ONLY a fixture seam.

    Production freezes must use the default external root SHA. No missing CLI
    parent wait is manufactured, and no transport/replay/ledger method is called.
    """
    root = Path(root).resolve(); refs = {}
    cfg = stop_config or {'path': ROOT_COMPLETION, 'sha256': ROOT_COMPLETION_SHA256}
    closure_path = root / cfg['path']
    closure = _read(closure_path, cfg['sha256'], refs)
    run = root / 'runs/smt_fullfab_stage2' / OLD_RUN_NAME
    campaign = root / 'runs/smt_fullfab_B_delta_gate' / OLD_RUN_NAME
    host = root / 'runs/smt_fullfab_B_delta_host_guard' / OLD_RUN_NAME
    require(closure['run_id'] == OLD_RUN_NAME and closure['campaign'] == str(campaign)
            and closure['host_directory'] == str(host) and closure['status'] == 'failed'
            and closure['accepted'] is False and closure['model_account']['pending'] == [OLD_CALL_ID],
            'root closure is not the fixed failed stopped run')
    actual = _read(closure_path.parent / 'actual_exit.json', closure['actual_exit_sha256'], refs)
    require(actual['run_id'] == OLD_RUN_NAME and actual['exited'] is True and actual['exit_code'] == 1
            and actual['timed_out'] is False and actual['user_requested_stop'] is True,
            'original root actual exit is not the explicit stopped terminal')
    posterior = closure['posterior_readback_evidence']
    require(Path(posterior['path']).resolve().is_relative_to(root), 'posterior certificate outside root')
    readback = _read(Path(posterior['path']), posterior['sha256'], refs)
    require(readback['run_id'] == OLD_RUN_NAME and readback['actual_exit_sha256'] == closure['actual_exit_sha256']
            and readback['accepted'] is False and readback['source_run_status'] == 'failed'
            and readback['user_requested_stop'] is True and readback['active_with_finalizers'] is False
            and readback['serial_lock_acquired_after_actual_exit'] is True
            and readback['model_account_from_original_ledger']['pending'] == [OLD_CALL_ID],
            'original post-stop serial closure is missing')
    acceptance = _read(campaign / 'acceptance.json', closure['gate_acceptance_sha256'], refs)
    require(acceptance['run_id'] == OLD_RUN_NAME and acceptance['accepted'] is False
            and acceptance['status'] == 'failed', 'failed acceptance anchor changed')
    inventory = acceptance['evidence_sha256']
    def original(base, relative, prefix):
        return _read(base / relative, inventory[prefix + relative], refs)
    attempt = run / 'model_00072'
    request = original(run, 'model_00072/request.json', 'run/')
    cli = original(run, 'model_00072/process_guard/receipt.json', 'run/')
    spec = original(run, 'model_00072/process_guard/spec.json', 'run/')
    require(request['call_id'] == cli['call_id'] == spec['call_id'] == OLD_CALL_ID
            and request['request_fingerprint'] == cli['request_fingerprint'] == spec['request_fingerprint']
            and spec['run_dir'] == str(attempt) and spec['guard_source_sha256'] == GUARD_SHA256
            and cli['spec_sha256'] == inventory['run/model_00072/process_guard/spec.json'],
            'stopped CLI original request/spec/receipt identity differs')
    require(cli['owner_eof'] is True and cli['stop_reason'] == 'owner_eof'
            and cli['command_returncode'] == -15 and cli['group_term_sent'] is True
            and cli['final_group_signal'] == 9 and cli['timed_out'] is False
            and cli['guard_error'] is None and cli['launch_error'] is None,
            'original CLI stop is not the documented incomplete owner-death state')
    phase = original(campaign, 'child_process/process.json', 'campaign/')
    child = original(campaign, 'child_process/process_guard/receipt.json', 'campaign/')
    waited = original(campaign, 'child_process/process_guard/parent_observed.json', 'campaign/')
    guard = phase['guard_evidence']
    require(phase['returncode'] == -15 and phase['cleanup_errors'] == []
            and guard['lifecycle_complete'] is True and guard['guard_source_sha256'] == GUARD_SHA256
            and guard['command_returncode'] == child['command_returncode'] == -15
            and child['owner_eof'] is False and child['stop_reason'] == 'command_exit'
            and child['final_group_signal'] == 9 and child['guard_error'] is None
            and waited['wait_completed'] is True and waited['guard_returncode'] == -9
            and waited['guard_pid'] == child['guard_pid'] == guard['guard_pid']
            and waited['files_sha256']['receipt.json'] == inventory['campaign/child_process/process_guard/receipt.json']
            and guard['files_sha256']['parent_observed.json'] == inventory['campaign/child_process/process_guard/parent_observed.json'],
            'controller original actual wait/termination chain is incomplete')
    times = [cli['command_started_monotonic_seconds'], cli['command_finished_monotonic_seconds'],
             cli['before_final_kill_monotonic_seconds'], child['command_finished_monotonic_seconds'],
             child['before_final_kill_monotonic_seconds'], waited['observed_monotonic_seconds']]
    require(all(type(t) in (int, float) and math.isfinite(t) for t in times) and times == sorted(times),
            'original stopped process timestamps are inconsistent')
    absent = [attempt / name for name in ('result.json', 'final.txt', 'process_guard/parent_observed.json')]
    require(all(not path.exists() and not path.is_symlink() for path in absent),
            'incomplete old attempt acquired new completion material')
    _fence(refs)
    return {'schema': SCHEMA, 'call_id': OLD_CALL_ID, 'old_run_id': str(run), 'attempt_run_id': str(attempt),
            'original_registration_ids': readback['original_ledger_domain']['registration_ids'],
            'request': request, 'refs': refs, 'missing_completion_paths': list(map(str, absent)),
            'local_stopped_under_original_root_certificate': True, 'provider_usage_known': False,
            'model_completion_authenticated': False, 'cost_complete': False}


def _account(rows):
    """Independent arithmetic over all original events; never remove a pending."""
    starts = [r for r in rows if r['event'] == 'reserve']; ends = {r['call_id']: r for r in rows if r['event'] == 'finish'}
    require(len(ends) == sum(r['event'] == 'finish' for r in rows), 'duplicate finish')
    require(len({r['call_id'] for r in starts}) == len(starts), 'duplicate reserve')
    tokens = 0; unknown = []; active = 0.0; amended = {}
    for row in starts:
        aid = row.get('amendment_id')
        if aid: amended[aid] = amended.get(aid, 0) + 1
        if row['call_id'] not in ends: continue
        details = ends[row['call_id']]['details']; usage = details.get('usage', {})
        if all(type(usage.get(k)) is int and usage[k] >= 0 for k in ('input_tokens', 'output_tokens')):
            tokens += usage['input_tokens'] + usage['output_tokens']
        else: unknown.append(row['call_id'])
        duration = details.get('duration_seconds', 0)
        require(type(duration) in (int, float) and math.isfinite(duration) and duration >= 0, 'invalid original duration')
        active += duration
    cs = [r for r in rows if r['event'] == 'constructor_reserve']; ce = {r['call_id']: r for r in rows if r['event'] == 'constructor_finish'}
    require(len(ce) == sum(r['event'] == 'constructor_finish' for r in rows), 'duplicate constructor finish')
    cw = sum((ce[r['call_id']]['details']['duration_seconds'] for r in cs if r['call_id'] in ce), 0.0)
    return {'attempts': len(starts), 'reported_input_output_tokens': tokens, 'unknown_completed': unknown,
            'pending': [r['call_id'] for r in starts if r['call_id'] not in ends],
            'pending_solver_calls': [r['call_id'] for r in rows if r['event'] == 'solver_reserve'
                                     and not any(s['event'] == 'solver_finish' and s['call_id'] == r['call_id'] for s in rows)],
            'model_active_seconds': active, 'constructor_calls': len(cs),
            'constructor_requested_seconds': sum(r['requested_seconds'] for r in cs),
            'constructor_active_seconds': cw, 'active_execution_seconds': active + cw,
            'pending_constructor_calls': [r['call_id'] for r in cs if r['call_id'] not in ce],
            'cost_usd': None, 'development_collaboration_cost_usd': None, 'amendment_attempts': amended}


def _target(root, target):
    path = Path(target).resolve()
    require(path.parent == (Path(root).resolve() / 'runs/smt_fullfab_stage2') and path.name != OLD_RUN_NAME
            and '__recovery_' not in path.name, 'requires a genuinely new direct B stage run')
    return str(path)


def _old_reserve(rows, proof):
    original = [r for r in rows if r['event'] == 'reserve' and r['call_id'] == OLD_CALL_ID]
    require(len(original) == 1 and not any(r['event'] == 'finish' and r['call_id'] == OLD_CALL_ID for r in rows),
            'original call must remain uniquely reserved and unfinished')
    row = original[0]; req = proof['request']; cfg = req['config']; md = row['metadata']
    require(row['run_id'] == proof['attempt_run_id'] and row['registration_id'] in proof['original_registration_ids']
            and row['phase'] == cfg['phase'] and row['grant_id'] == cfg['grant_id']
            and md['request_fingerprint'] == req['request_fingerprint']
            and all(same(md[k], cfg[k]) for k in ('model', 'reasoning_effort', 'timeout_seconds', 'authorization_context')),
            'original pending reserve differs from originally bound request')
    return row


def preflight_stopped_pending(rows, *, root, target_run_id, stop_config=None):
    """No write/registration. An unused target may already be registered."""
    target = _target(root, target_run_id); proof = verify_stop_evidence(root, stop_config=stop_config)
    _old_reserve(rows, proof); account = _account(rows)
    require(account['pending'] == [OLD_CALL_ID] and not account['pending_solver_calls']
            and not account['pending_constructor_calls'], 'another unsettled attempt still blocks admission')
    require(not any(r.get('event') in ('reserve', 'solver_reserve', 'constructor_reserve') and
                    (str(Path(r.get('run_id', '/')).resolve()) == target or str(Path(r.get('run_id', '/')).resolve().parent) == target)
                    for r in rows), 'target has already been used')
    require(not any(r.get('event') == 'recovery_segment_registered' and target in
                    (r['mapping']['parent_run_id'], r['mapping']['segment_run_id']) for r in rows), 'target is a recovery identity')
    diagnoses = [r for r in rows if r['event'] == EVENT]
    require(not diagnoses or (len(diagnoses) == 1 and diagnoses[0]['run_id'] == target), 'diagnosis belongs to another target')
    return {'allowed_pending_call_ids': [OLD_CALL_ID], 'raw_pending': account['pending'],
            'target_run_id': target, 'stop_evidence': proof}


def _diagnosis(prefix, row, approval, root, registrations, stop_config):
    d = row['diagnosis']; target = _target(root, row['run_id']); proof = verify_stop_evidence(root, stop_config=stop_config)
    original = _old_reserve(prefix, proof); reg = registrations[target]
    require(same(d['stop_evidence'], proof) and d['diagnosis_id'] == digest({k: v for k, v in d.items() if k != 'diagnosis_id'})
            and d['prefix_record_count'] == len(prefix) and d['prior_ledger_sha256'] == digest(prefix)
            and d['reserve_sha256'] == digest(original) and d['budget_id'] == approval['budget_id']
            and d['amendment_id'] == reg['amendment_id'] and d['target_registration_id'] == reg['registration_id']
            and d['target_run_id'] == target and row['registration_id'] == reg['registration_id']
            and row['call_id'] == d['call_id'] == OLD_CALL_ID and d['schema'] == SCHEMA,
            'diagnosis differs from original prefix/request/stop/new registration')
    require(reg['arm'] == 'B' and type(reg['solver_seconds']) is int and reg['solver_seconds'] == 0,
            'stopped exception permits only the zero-solver new B registration')
    preflight_stopped_pending(prefix, root=root, target_run_id=target, stop_config=stop_config)
    return d, reg


def audit_admissions(rows, approval, *, root, target_run_id=None, stop_config=None):
    """Sequential independent extension; complete original pre-diagnosis audit.

    No filtering of pending/errors. Original guard/model provenance remains a
    separate required binder. Any new unknown pending still blocks the next call.
    """
    from smt_fullfab.controller_audit import _audit_ledger_admission
    indices = [i for i, r in enumerate(rows) if r['event'] == EVENT]
    prefix = rows[:indices[0]] if indices else rows
    result = _audit_ledger_admission(prefix, approval)
    if not indices: return result
    try:
        require(len(indices) == 1, 'duplicate stopped diagnosis')
        index = indices[0]; d, reg = _diagnosis(prefix, rows[index], approval, root, result['registered_runs'], stop_config)
        require(target_run_id is None or _target(root, target_run_id) == reg['run_id'], 'wrong diagnosis target')
        research = result['effective_research_amendment']; require(research is not None, 'missing research authority')
        history = list(prefix); own = []; own_ids = set(); solver_used = {}
        for r in prefix:
            if r['event'] == 'solver_reserve' and not r.get('registration_id'):
                solver_used[r['arm']] = solver_used.get(r['arm'], 0) + r['requested_seconds']
        for row in rows[index + 1:]:
            event = row['event']; cid = row.get('call_id'); global_before = _account(history); local = _account(own)
            if event == 'reserve':
                md = row['metadata']; ctx = md['authorization_context']; timeout = md['timeout_seconds']
                require(isinstance(cid, str) and cid and not any(r.get('call_id') == cid for r in history)
                        and str(Path(row['run_id']).resolve().parent) == reg['run_id'], 'new reserve reuses identity or targets another run')
                require(global_before['pending'] == [OLD_CALL_ID] and not global_before['pending_solver_calls']
                        and not global_before['pending_constructor_calls'], 'new pending still blocks the next reservation')
                require(row['stopped_pending_diagnosis_id'] == d['diagnosis_id'] and row['registration_id'] == reg['registration_id']
                        and row['amendment_id'] == research['amendment_id'] and row['grant_id'] == approval['budget_id']
                        and row['phase'] == reg['phase'] and ctx['purpose'] == ctx['arm'] == 'B'
                        and same(ctx['scenario'], reg['scenario']) and same(ctx['window_seconds'], reg['window_seconds'])
                        and md['model'] == research['model'] and md['reasoning_effort'] == research['reasoning_effort']
                        and row.get('recovery_segment_id') is None, 'new reservation exceeds diagnosed identity/scope')
                require(type(timeout) in (int, float) and math.isfinite(timeout)
                        and 1 <= timeout <= min(180, reg['wall_seconds'] - local['active_execution_seconds']), 'new timeout exceeds retained bounds')
                require(same(row['account_before'], global_before) and same(row['run_account_before'], local),
                        'raw account_before changes original pending/counters/unknown values')
                result['admissions'][cid] = {'purpose': 'B', 'waiver_applied': True, 'amendment_id': research['amendment_id'],
                    'active_seconds_before': global_before['model_active_seconds'], 'timeout_seconds': timeout,
                    'solver_requested_seconds_before_by_arm': dict(solver_used), 'waiver_scope': 'registered_research',
                    'registration': reg, 'run_active_seconds_before': local['model_active_seconds'],
                    'run_solver_requested_seconds_before': 0, 'stopped_pending_diagnosis_id': d['diagnosis_id']}
                own_ids.add(cid)
            elif event == 'finish':
                require(cid in own_ids and cid in local['pending'] and cid != OLD_CALL_ID, 'finish cannot reconcile the original stopped call')
                require('duration_seconds' in row['details'], 'new finish lacks measured duration')
            else:
                raise ValueError('unsupported post-diagnosis event; no new authority, recovery or solver scope')
            own.append(row); history.append(row); _account(history)
        account = _account(history)
        result.update(model_active_seconds=account['model_active_seconds'], unknown_usage_call_ids=account['unknown_completed'])
        result['stopped_pending'] = {'allowed_pending_call_ids': [OLD_CALL_ID], 'raw_pending': account['pending'],
            'diagnosis_id': d['diagnosis_id'], 'target_run_id': reg['run_id'], 'cost_complete': False,
            'unknown_model_active_duration_call_ids': [OLD_CALL_ID], 'unsettled_usage_call_ids': [OLD_CALL_ID],
            'new_run_pending_call_ids': _account(own)['pending']}
        _fence(d['stop_evidence']['refs'])
    except (ValueError, KeyError, TypeError, OSError) as exc:
        result['errors'].append('stopped admission: ' + str(exc))
    return result


def make_ledger_class(original_budget_module, *, stop_config=None):
    """Explicit dependency injection, no monkeypatch and no second ledger."""
    b = original_budget_module
    class StoppedPendingLedger(b.BudgetLedger):
        def record_stopped_diagnosis(self, target_run_id):
            with self._locked() as rows:
                approvals = [r['approval'] for r in rows if r['event'] == 'approval']
                require(len(approvals) == 1, 'unique original approval required'); approval = approvals[0]
                existing = [r for r in rows if r['event'] == EVENT]
                if existing:
                    report = audit_admissions(rows, approval, root=b.ROOT, target_run_id=target_run_id, stop_config=stop_config)
                    require(not report['errors'] and not report['missing_evidence'], 'existing diagnosis no longer verifies')
                    return existing[0]
                pre = preflight_stopped_pending(rows, root=b.ROOT, target_run_id=target_run_id, stop_config=stop_config)
                reg = self._registrations(rows, approval).get(pre['target_run_id'])
                require(reg is not None, 'register the new B run before its stopped diagnosis')
                d = {'schema': SCHEMA, 'call_id': OLD_CALL_ID, 'reserve_sha256': digest(_old_reserve(rows, pre['stop_evidence'])),
                     'prefix_record_count': len(rows), 'prior_ledger_sha256': digest(rows), 'budget_id': approval['budget_id'],
                     'amendment_id': reg['amendment_id'], 'target_run_id': reg['run_id'],
                     'target_registration_id': reg['registration_id'], 'stop_evidence': pre['stop_evidence']}
                d['diagnosis_id'] = digest(d)
                row = {'event': EVENT, 'call_id': OLD_CALL_ID, 'run_id': reg['run_id'],
                       'registration_id': reg['registration_id'], 'diagnosis': d}
                report = audit_admissions(rows + [row], approval, root=b.ROOT, target_run_id=target_run_id, stop_config=stop_config)
                require(not report['errors'] and not report['missing_evidence'], 'diagnosis admission audit failed: ' + repr(report['errors']))
                _fence(pre['stop_evidence']['refs'])
                return self._append(row)

        def reserve(self, *, phase, run_id, grant_id, call_id=None, metadata=None):
            with self._locked() as rows:
                approvals = [r['approval'] for r in rows if r['event'] == 'approval']
                require(len(approvals) == 1, 'unique original approval required'); approval = approvals[0]
                target = _target(b.ROOT, str(Path(run_id).resolve().parent))
                report = audit_admissions(rows, approval, root=b.ROOT, target_run_id=target, stop_config=stop_config)
                require(not report['errors'] and not report['missing_evidence'] and 'stopped_pending' in report,
                        'new call requires the unique verified stopped diagnosis')
                diagnosis = next(r['diagnosis'] for r in rows if r['event'] == EVENT)
                reg, recovery = self._resolve_registration(rows, approval, target)
                require(reg is not None and recovery is None, 'no recovery or unregistered admission')
                research = self._validated_research_waiver(rows, approval)
                row = {'event': 'reserve', 'call_id': call_id or str(uuid.uuid4()), 'phase': phase, 'run_id': str(Path(run_id).resolve()),
                       'grant_id': grant_id, 'metadata': metadata or {}, 'account_before': self.account(rows),
                       'run_account_before': self.account(self._run_rows(rows, target)),
                       'amendment_id': research['amendment_id'], 'registration_id': reg['registration_id'],
                       'stopped_pending_diagnosis_id': diagnosis['diagnosis_id']}
                checked = audit_admissions(rows + [row], approval, root=b.ROOT, target_run_id=target, stop_config=stop_config)
                require(not checked['errors'] and not checked['missing_evidence'], 'new reserve rejected: ' + repr(checked['errors']))
                _fence(diagnosis['stop_evidence']['refs'])
                self._append(row)
                return row['call_id']

        def finish(self, call_id, status, details=None):
            require(call_id != OLD_CALL_ID, 'stopped diagnosis cannot manufacture an original finish')
            return super().finish(call_id, status, details)
    return StoppedPendingLedger
