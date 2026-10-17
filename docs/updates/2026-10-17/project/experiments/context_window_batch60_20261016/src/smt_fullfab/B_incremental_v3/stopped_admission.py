"""Exact V4-unsettled + failed V6/unknown usage -> one new V7 with approved600.

This does not repair V4/V6 usage, resume V6, or grant acceptance.
The original v2 auditor checks the complete externally pinned V6 ledger prefix.
"""
from __future__ import annotations
import hashlib
import importlib
import json
import math
import os
import sys
from pathlib import Path
import uuid
from src.smt_fullfab.B_incremental_v2 import stopped_admission as prior
legacy = prior.prior

SCHEMA = 'smt-B-v7-timeout-admission-v1'
EVENT = 'timeout_extended_prior_closed_run_admitted'
OLD_CALL_ID = prior.OLD_CALL_ID
PRIOR_RUN_NAME = 'B_1701_1h_delta_v6'
TARGET_RUN_NAME = 'B_1701_1h_delta_v7'
ROOT_COMPLETION = 'artifacts/smt_fullfab_diagnostics/B_incremental_actual_host_observation_v6/root_completion.json'
ROOT_COMPLETION_SHA256 = '1e02451f6933829c7ac737da675bc7b1dcbe44a81a99de66810504e385daafec'
PRIOR_UNKNOWN_CALL_ID = 'cdee145d-6635-4f65-ab03-b30657a271b9'
TIMEOUT_APPROVAL = 'configs/smt_fullfab/B_timeout_600.approved.json'
TIMEOUT_APPROVAL_SHA256 = 'a82bf66c27204551a7655edff8de90c3f01155830cb2bc066710b44df5e9569d'
PER_CALL_TIMEOUT_SECONDS = 600
require, same, digest = prior.require, prior.same, prior.digest


def _source_directory():
    here = Path(__file__).resolve()
    if here.parent.name == 'B_v7_timeout_admission_v1' and here.parent.parent.name == 'smt_fullfab_diagnostics':
        return here.parents[3] / 'src'  # Explicit authored-only candidate layout.
    require(here.parent.name == 'B_incremental_v3' and here.parents[1].name == 'smt_fullfab'
            and here.parents[2].name == 'src', 'unrecognized V7 helper source layout')
    return here.parents[2]  # Installed or frozen; unrelated to the real ledger root.


def require_same_root_auditor():
    # Gate.prepare imports this helper before controller/binding. Keep the old
    # auditor spelling usable, but never accept a module from a foreign tree.
    import src
    source_root = _source_directory()
    require(Path(src.__file__).resolve().parent == source_root, 'src package differs from this helper source root')
    expected_prior = source_root / 'smt_fullfab/B_incremental_v2/stopped_admission.py'
    require(Path(prior.__file__).resolve() == expected_prior and
            hashlib.sha256(expected_prior.read_bytes()).hexdigest() ==
            '7571354c08a101a2d7d1297cd6e79df17bb5439f3e58eb5f0c09f8b7645d03fe',
            'fixed prior helper source/root differs')
    return prior.require_same_root_auditor()  # Includes fixed V1 and legacy auditor source pins.



def _target(root, value):
    target = Path(root).resolve() / 'runs/smt_fullfab_stage2' / TARGET_RUN_NAME
    require(str(Path(value).resolve()) == str(target), 'only the fixed new V7 target may use this chain')
    return str(target)


def _prefix(path, expected, refs):
    """One original immutable JSONL snapshot, no reads of the live ledger here."""
    path = Path(path); require(not path.is_symlink(), 'prior ledger snapshot symlink')
    identity = legacy._identity(path.stat())
    require(identity[2] <= 16 * 1024 * 1024, 'bounded original V6 prefix snapshot exceeded')
    with path.open('rb') as stream:
        require(legacy._identity(os.fstat(stream.fileno())) == identity, 'prior prefix changed at open')
        raw = stream.read(16 * 1024 * 1024 + 1)
        require(legacy._identity(os.fstat(stream.fileno())) == identity, 'prior prefix changed during read')
    require(legacy._identity(path.stat()) == identity and hashlib.sha256(raw).hexdigest() == expected,
            'original V6 complete raw ledger prefix differs')
    require(raw.endswith(b'\n') and all(line.strip() for line in raw.splitlines()), 'incomplete/blank original ledger line')
    rows = [json.loads(line) for line in raw.splitlines()]
    legacy.canonical(rows)
    refs[str(path)] = {'sha256': expected, 'bytes': len(raw), 'file_identity': identity}
    return rows


def _own(rows, run_id):
    ids = {r['call_id'] for r in rows if r['event'] == 'reserve' and str(Path(r['run_id']).resolve().parent) == run_id}
    return [r for r in rows if r.get('call_id') in ids]


def _timeout_approval(root, research, refs, approval_config):
    cfg = approval_config or {'path': TIMEOUT_APPROVAL, 'sha256': TIMEOUT_APPROVAL_SHA256}
    approval = legacy._read(Path(root) / cfg['path'], cfg['sha256'], refs)
    fields = {'schema', 'extension_id', 'budget_id', 'authorization', 'approval_text', 'selected_by',
              'selection_reason', 'model', 'reasoning_effort', 'allowed_arm', 'allowed_window_seconds',
              'target_run_id', 'per_call_timeout_seconds', 'global_max_calls', 'global_max_tokens',
              'run_wall_seconds', 'original_research_waiver_sha256', 'preserve_all_prior_costs_and_unknown_usage',
              'automatic_transport_retries', 'formal'}
    require(set(approval) == fields and approval['schema'] == 'smt-fullfab-B-timeout-extension-v1'
            and approval['extension_id'] == 'smt-fullfab-B-per-call600-v1'
            and approval['authorization'] == 'approved_by_user'
            and approval['approval_text'] == '把单次180秒超时也放宽，继续排查并推进B的全厂1小时验证，保留完整调用和费用记录，不要停在汇报上。'
            and approval['selected_by'] == 'root_within_user_timeout_relaxation'
            and approval['budget_id'] == research['budget_id'] and approval['model'] == research['model']
            and approval['reasoning_effort'] == research['reasoning_effort'] and approval['allowed_arm'] == 'B'
            and same(approval['allowed_window_seconds'], 3600) and approval['target_run_id'] == TARGET_RUN_NAME
            and same(approval['per_call_timeout_seconds'], PER_CALL_TIMEOUT_SECONDS)
            and approval['global_max_calls'] is None and approval['global_max_tokens'] is None
            and same(approval['run_wall_seconds'], 21600.0)
            and approval['preserve_all_prior_costs_and_unknown_usage'] is True
            and same(approval['automatic_transport_retries'], 0) and approval['formal'] is False,
            'new V7 timeout authorization differs from the explicit narrow approval')
    waiver = legacy._read(Path(root) / 'configs/smt_fullfab/research_limit_waiver.approved.json',
                          approval['original_research_waiver_sha256'], refs)
    require(same(waiver, research) and same(research['per_call_timeout_seconds'], 180),
            'original180 research waiver was changed rather than retained')
    return {'extension_id': approval['extension_id'], 'approval_sha256': cfg['sha256'],
            'approval_path': str(Path(root) / cfg['path']), 'per_call_timeout_seconds': PER_CALL_TIMEOUT_SECONDS,
            'original_research_per_call_timeout_seconds': 180, 'original_research_amendment_id': research['amendment_id'],
            'original_research_waiver_modified': False, 'target_run_id': TARGET_RUN_NAME}


def _closed(root, *, closure_config=None, prior_closure_config=None, approval_config=None, stop_config=None):
    """Private complete proof. Overrides are synthetic-fixture seams only."""
    require_same_root_auditor()
    root = Path(root).resolve(); refs = {}
    cfg = closure_config or {'path': ROOT_COMPLETION, 'sha256': ROOT_COMPLETION_SHA256}
    path = root / cfg['path']; closure = legacy._read(path, cfg['sha256'], refs)
    run = root / 'runs/smt_fullfab_stage2' / PRIOR_RUN_NAME
    require(closure['run_id'] == PRIOR_RUN_NAME and closure['status'] == 'failed' and closure['accepted'] is False
            and closure['old_unsettled_call_preserved'] == OLD_CALL_ID, 'V6 must remain the failed closed prior run')
    diagnosis = legacy._read(path.parent / 'failure_diagnosis.json', closure['failure_diagnosis_sha256'], refs)
    actual = legacy._read(path.parent / 'actual_exit.json', closure['actual_exit_sha256'], refs)
    result = legacy._read(run / 'result.json', closure['runner_result_sha256'], refs)
    require(actual['wait_completed'] is True and type(actual['actual_exit_code']) is int
            and actual['actual_exit_code'] == 1 and actual['automatic_retry'] is False,
            'V6 original actual exit is not the closed failed process')
    require(diagnosis['run_id'] == PRIOR_RUN_NAME and diagnosis['active_with_finalizers'] is False
            and diagnosis['serial_lock_acquired_after_exit'] is True
            and diagnosis['failed_gate_readback']['valid'] is True
            and diagnosis['failed_gate_readback']['accepted'] is False
            and diagnosis['failed_gate_readback']['status'] == 'failed'
            and diagnosis['failed_gate_readback']['acceptance_sha256'] == closure['gate_acceptance_sha256']
            and result['config']['run_id'] == PRIOR_RUN_NAME and result['status'] == 'failed'
            and result['accepted'] is False and result['automatic_recovery_or_retry'] is False,
            'V6 original failure/readback/serial/result chain differs')
    rows = _prefix(run / 'ledger_final.jsonl', diagnosis['ledger_sha256'], refs)
    approvals = [r['approval'] for r in rows if r['event'] == 'approval']
    require(len(approvals) == 1, 'unique approval in original prefix required')
    report = prior.audit_admissions(rows, approvals[0], root=root, target_run_id=str(run),
                                    closure_config=prior_closure_config, stop_config=stop_config)
    require(not report['errors'] and not report['missing_evidence'], 'original full V6 admission prefix does not verify')
    account = legacy._account(_own(rows, str(run))); global_account = legacy._account(rows)
    reserve_ids = [r['call_id'] for r in rows if r['event'] == 'reserve' and str(Path(r['run_id']).resolve().parent) == str(run)]
    require(same(account, closure['model_account']) and same(account, diagnosis['run_account'])
            and same(account, result['model_account']) and same(global_account, diagnosis['global_account'])
            and same(reserve_ids, result['reserve_call_ids']) and result['model_calls'] == len(reserve_ids)
            and result['pending_call_ids'] == [] and result['unknown_usage_call_ids'] == [PRIOR_UNKNOWN_CALL_ID]
            and account['attempts'] > 0 and account['pending'] == [] and account['unknown_completed'] == [PRIOR_UNKNOWN_CALL_ID]
            and diagnosis['model_timeout_call_id'] == PRIOR_UNKNOWN_CALL_ID
            and account['pending_solver_calls'] == account['pending_constructor_calls'] == []
            and account['constructor_calls'] == 0 and result['solver_calls'] == result['constructor_calls'] == 0
            and global_account['pending'] == [OLD_CALL_ID] and global_account['pending_solver_calls'] == []
            and global_account['pending_constructor_calls'] == [], 'V6 original completed account/unknown usage does not match the preserved timeout')
    require(same(report['stopped_pending'], diagnosis['original_pending_preserved']), 'prior original stopped diagnosis changed')
    upstream = [r for r in rows if r['event'] == prior.EVENT]
    require(len(upstream) == 1, 'unique original V6 chain required')
    refs.update(upstream[0]['diagnosis']['prior_closed_evidence']['refs'])
    extension = _timeout_approval(root, report['effective_research_amendment'], refs, approval_config)
    legacy._fence(refs)
    proof = {'schema': SCHEMA, 'prior_run_id': str(run), 'prior_status': 'failed', 'prior_accepted': False,
             'root_completion_sha256': cfg['sha256'], 'ledger_prefix_sha256': diagnosis['ledger_sha256'],
             'prefix_record_count': len(rows), 'prefix_records_sha256': digest(rows), 'prior_account': account,
             'prior_reserve_call_ids': reserve_ids, 'prior_diagnosis_id': report['stopped_pending']['diagnosis_id'],
             'allowed_pending_call_ids': [OLD_CALL_ID], 'cost_complete': False, 'refs': refs,
             'prior_unknown_usage_call_ids': [PRIOR_UNKNOWN_CALL_ID], 'timeout_extension': extension}
    return rows, approvals[0], report, proof


def _registration(row, root, research):
    reg = row['registration']; target = _target(root, reg['run_id'])
    fields = {'registration_id', 'amendment_id', 'budget_id', 'run_id', 'arm', 'scenario', 'window_seconds',
              'solver_seconds', 'wall_seconds', 'max_log_bytes', 'phase', 'formal'}
    require(row['event'] == 'stage_run_registered' and set(reg) == fields
            and reg['registration_id'] == digest({k: v for k, v in reg.items() if k != 'registration_id'})
            and reg['run_id'] == target and reg['arm'] == 'B' and reg['formal'] is False
            and reg['phase'] == 'stage2_research' and reg['budget_id'] == research['budget_id']
            and reg['amendment_id'] == research['amendment_id'] and same(reg['scenario'], 1701)
            and same(reg['window_seconds'], 3600) and same(reg['solver_seconds'], 0)
            and same(reg['wall_seconds'], 21600.0) and same(reg['max_log_bytes'], 17179869184),
            'V7 immutable registration scope/resource/type differs')
    return reg


def preflight_stopped_pending(rows, *, root, target_run_id, closure_config=None, prior_closure_config=None, approval_config=None, stop_config=None):
    target = _target(root, target_run_id)
    original, approval, report, proof = _closed(root, closure_config=closure_config, prior_closure_config=prior_closure_config, approval_config=approval_config, stop_config=stop_config)
    n = len(original)
    require(same(rows[:n], original) and len(rows) in (n, n + 1), 'preflight requires the complete original prefix and at most new V7 registration')
    if len(rows) > n: _registration(rows[n], root, report['effective_research_amendment'])
    require(target not in report['registered_runs'], 'V7 already present in original prefix')
    legacy._fence(proof['refs'])
    return {'allowed_pending_call_ids': [OLD_CALL_ID], 'raw_pending': [OLD_CALL_ID], 'target_run_id': target,
            'stop_evidence': proof, 'prior_account': proof['prior_account']}


def audit_admissions(rows, approval, *, root, target_run_id=None, closure_config=None, prior_closure_config=None, approval_config=None, stop_config=None):
    """Original full V6 auditor then exact new registration/note/call sequence."""
    if not any(r.get('event') in (legacy.EVENT, prior.EVENT, EVENT) for r in rows):
        # Preserve the original channel/legacy fixture contract. This branch
        # cannot grant a V7 call: its real registration/path requires the chain.
        require_same_root_auditor()
        report = prior.audit_admissions(rows, approval, root=root, closure_config=prior_closure_config, stop_config=stop_config)
        if any(TARGET_RUN_NAME in str(r.get('run_id', '')) or
               TARGET_RUN_NAME in str(r.get('registration', {}).get('run_id', '')) for r in rows):
            report['errors'].append('V7 identity requires the complete original stopped/closed prefix')
        return report
    original, old_approval, report, proof = _closed(root, closure_config=closure_config, prior_closure_config=prior_closure_config, approval_config=approval_config, stop_config=stop_config)
    try:
        n = len(original); target = _target(root, target_run_id or (Path(root) / 'runs/smt_fullfab_stage2' / TARGET_RUN_NAME))
        require(same(approval, old_approval) and same(rows[:n], original), 'full original ledger prefix/approval changed')
        if len(rows) == n:
            legacy._fence(proof['refs']); return report  # No new admission exists yet.
        reg = _registration(rows[n], root, report['effective_research_amendment'])
        require(target not in report['registered_runs'], 'V7 was already registered in the original prefix')
        report['registered_runs'][target] = reg
        if len(rows) == n + 1:
            legacy._fence(proof['refs']); return report  # Registration alone grants no call.
        note = rows[n + 1]; d = note['diagnosis']
        require(note['event'] == EVENT and note['run_id'] == target and note['registration_id'] == reg['registration_id']
                and note['call_id'] == OLD_CALL_ID and d['schema'] == SCHEMA
                and d['diagnosis_id'] == digest({k: v for k, v in d.items() if k != 'diagnosis_id'})
                and d['prefix_record_count'] == n + 1 and d['prior_ledger_sha256'] == digest(rows[:n + 1])
                and d['target_run_id'] == target and d['target_registration_id'] == reg['registration_id']
                and d['budget_id'] == approval['budget_id'] and same(d['prior_closed_evidence'], proof),
                'V7 chained admission differs from original closed prior proof')
        history = list(rows[:n + 2]); own = []; own_ids = set(); research = report['effective_research_amendment']
        solver_used = {}
        for r in original:
            if r['event'] == 'solver_reserve' and not r.get('registration_id'):
                solver_used[r['arm']] = solver_used.get(r['arm'], 0) + r['requested_seconds']
        for row in rows[n + 2:]:
            cid = row.get('call_id'); account = legacy._account(history); local = legacy._account(own)
            if row['event'] == 'reserve':
                md = row['metadata']; ctx = md['authorization_context']; timeout = md['timeout_seconds']
                require(isinstance(cid, str) and cid and not any(r.get('call_id') == cid for r in history)
                        and str(Path(row['run_id']).resolve().parent) == target, 'new V7 reservation reused identity/old directory')
                require(account['pending'] == [OLD_CALL_ID] and account['pending_solver_calls'] == account['pending_constructor_calls'] == [],
                        'new unsettled attempt still blocks another call')
                require(row['stopped_pending_diagnosis_id'] == d['diagnosis_id'] and row['registration_id'] == reg['registration_id']
                        and row['amendment_id'] == research['amendment_id'] and row['grant_id'] == approval['budget_id']
                        and row['phase'] == reg['phase'] and ctx['purpose'] == ctx['arm'] == 'B'
                        and same(ctx['scenario'], reg['scenario']) and same(ctx['window_seconds'], reg['window_seconds'])
                        and md['model'] == research['model'] and md['reasoning_effort'] == research['reasoning_effort']
                        and row.get('recovery_segment_id') is None, 'new V7 reservation outside retained scope')
                require(type(timeout) in (int, float) and math.isfinite(timeout)
                        and 1 <= timeout <= min(PER_CALL_TIMEOUT_SECONDS, reg['wall_seconds'] - local['active_execution_seconds']), 'V7 timeout exceeds retained bounds')
                require(same(row['account_before'], account) and same(row['run_account_before'], local), 'V7 raw account changed original costs/pending')
                report['admissions'][cid] = {'purpose': 'B', 'waiver_applied': True, 'amendment_id': research['amendment_id'],
                    'active_seconds_before': account['model_active_seconds'], 'timeout_seconds': timeout,
                    'solver_requested_seconds_before_by_arm': dict(solver_used), 'waiver_scope': 'registered_research',
                    'registration': reg, 'run_active_seconds_before': local['model_active_seconds'],
                    'run_solver_requested_seconds_before': 0, 'stopped_pending_diagnosis_id': d['diagnosis_id'],
                    'timeout_extension': proof['timeout_extension']}
                own_ids.add(cid)
            elif row['event'] == 'finish':
                require(cid in own_ids and cid in local['pending'] and cid != OLD_CALL_ID
                        and 'duration_seconds' in row['details'], 'new finish cannot alter/reconcile an earlier call')
            else: raise ValueError('unsupported event after unique V7 admission')
            own.append(row); history.append(row); legacy._account(history)
        account = legacy._account(history)
        report.update(model_active_seconds=account['model_active_seconds'], unknown_usage_call_ids=account['unknown_completed'])
        report['stopped_pending'] = {'allowed_pending_call_ids': [OLD_CALL_ID], 'raw_pending': account['pending'],
            'diagnosis_id': d['diagnosis_id'], 'target_run_id': target, 'cost_complete': False,
            'unknown_model_active_duration_call_ids': [OLD_CALL_ID], 'unsettled_usage_call_ids': [OLD_CALL_ID],
            'new_run_pending_call_ids': legacy._account(own)['pending'], 'prior_closed_run_id': proof['prior_run_id'],
            'prior_root_completion_sha256': proof['root_completion_sha256'],
            'preserved_completed_unknown_call_ids': [PRIOR_UNKNOWN_CALL_ID], 'timeout_extension': proof['timeout_extension']}
        legacy._fence(proof['refs'])
    except (ValueError, KeyError, TypeError, OSError) as exc:
        report['errors'].append('V7 prior-closed admission: ' + str(exc))
    return report


def _live_prefix(path, proof):
    # The original BudgetLedger lock is held by the caller. Check exact raw
    # prefix bytes, not only decoded row equality, before every new append.
    size = proof['refs'][str(Path(proof['prior_run_id']) / 'ledger_final.jsonl')]['bytes']
    path = Path(path); require(not path.is_symlink(), 'live ledger symlink')
    identity = legacy._identity(path.stat())
    with path.open('rb') as stream:
        require(legacy._identity(os.fstat(stream.fileno())) == identity, 'live ledger changed at open')
        raw = stream.read(size)
        require(legacy._identity(os.fstat(stream.fileno())) == identity, 'live ledger changed during prefix read')
    require(legacy._identity(path.stat()) == identity and len(raw) == size and
            hashlib.sha256(raw).hexdigest() == proof['ledger_prefix_sha256'], 'live ledger raw V6 prefix changed')


def make_ledger_class(original_budget_module, *, closure_config=None, prior_closure_config=None, approval_config=None, stop_config=None):
    b = original_budget_module
    class PriorClosedLedger(b.BudgetLedger):
        def record_stopped_diagnosis(self, target_run_id):
            with self._locked() as rows:
                target = _target(b.ROOT, target_run_id); approvals = [r['approval'] for r in rows if r['event'] == 'approval']
                require(len(approvals) == 1, 'unique original approval required'); approval = approvals[0]
                notes = [r for r in rows if r['event'] == EVENT]
                if notes:
                    report = audit_admissions(rows, approval, root=b.ROOT, target_run_id=target, closure_config=closure_config, prior_closure_config=prior_closure_config, approval_config=approval_config, stop_config=stop_config)
                    require(len(notes) == 1 and not report['errors'] and not report['missing_evidence'], 'existing V7 chain invalid')
                    _live_prefix(self.path, notes[0]['diagnosis']['prior_closed_evidence'])
                    return notes[0]
                pre = preflight_stopped_pending(rows, root=b.ROOT, target_run_id=target, closure_config=closure_config, prior_closure_config=prior_closure_config, approval_config=approval_config, stop_config=stop_config)
                reg = self._registrations(rows, approval).get(target)
                require(reg is not None, 'register unique V7 before its chained note')
                d = {'schema': SCHEMA, 'budget_id': approval['budget_id'], 'prefix_record_count': len(rows),
                     'prior_ledger_sha256': digest(rows), 'target_run_id': target,
                     'target_registration_id': reg['registration_id'], 'prior_closed_evidence': pre['stop_evidence']}
                d['diagnosis_id'] = digest(d)
                row = {'event': EVENT, 'run_id': target, 'registration_id': reg['registration_id'], 'call_id': OLD_CALL_ID, 'diagnosis': d}
                report = audit_admissions(rows + [row], approval, root=b.ROOT, target_run_id=target, closure_config=closure_config, prior_closure_config=prior_closure_config, approval_config=approval_config, stop_config=stop_config)
                require(not report['errors'] and not report['missing_evidence'], 'V7 note audit failed: ' + repr(report['errors']))
                _live_prefix(self.path, pre['stop_evidence'])
                legacy._fence(pre['stop_evidence']['refs']); return self._append(row)

        def reserve(self, *, phase, run_id, grant_id, call_id=None, metadata=None):
            with self._locked() as rows:
                target = _target(b.ROOT, str(Path(run_id).resolve().parent))
                approvals = [r['approval'] for r in rows if r['event'] == 'approval']
                require(len(approvals) == 1, 'unique original approval required'); approval = approvals[0]
                report = audit_admissions(rows, approval, root=b.ROOT, target_run_id=target, closure_config=closure_config, prior_closure_config=prior_closure_config, approval_config=approval_config, stop_config=stop_config)
                notes = [r for r in rows if r['event'] == EVENT]
                require(len(notes) == 1 and not report['errors'] and not report['missing_evidence'], 'unique verified V7 admission required')
                d = notes[0]['diagnosis']; reg, recovery = self._resolve_registration(rows, approval, target)
                require(reg is not None and recovery is None, 'V7 cannot be an inherited recovery segment')
                row = {'event': 'reserve', 'call_id': call_id or str(uuid.uuid4()), 'phase': phase, 'run_id': str(Path(run_id).resolve()),
                    'grant_id': grant_id, 'metadata': metadata or {}, 'account_before': self.account(rows),
                    'run_account_before': self.account(self._run_rows(rows, target)), 'amendment_id': reg['amendment_id'],
                    'registration_id': reg['registration_id'], 'stopped_pending_diagnosis_id': d['diagnosis_id']}
                checked = audit_admissions(rows + [row], approval, root=b.ROOT, target_run_id=target, closure_config=closure_config, prior_closure_config=prior_closure_config, approval_config=approval_config, stop_config=stop_config)
                require(not checked['errors'] and not checked['missing_evidence'], 'V7 reserve rejected: ' + repr(checked['errors']))
                _live_prefix(self.path, d['prior_closed_evidence'])
                legacy._fence(d['prior_closed_evidence']['refs']); self._append(row); return row['call_id']

        def finish(self, call_id, status, details=None):
            with self._locked() as rows:
                starts = [r for r in rows if r['event'] == 'reserve' and r['call_id'] == call_id]
                require(len(starts) == 1 and str(Path(starts[0]['run_id']).resolve().parent) ==
                        _target(b.ROOT, Path(b.ROOT) / 'runs/smt_fullfab_stage2' / TARGET_RUN_NAME),
                        'V7 helper cannot finish V4 or V6 identities')
            return super().finish(call_id, status, details)
    return PriorClosedLedger
