"""One explicit V7 continuation, charged to its immutable original registration.

This module never restores a factory, forks a store, invokes a model, retries an
attempt, or grants physical acceptance. The caller must separately verify those
contracts. Old V4 pending and all completed unknown usage remain in the account.
Only the new namespace is intended for installation: src.smt_fullfab.B_resume_v1.
"""
from __future__ import annotations
from copy import deepcopy
from decimal import Decimal
import hashlib
import math
import os
from pathlib import Path
import time
import uuid
from src.smt_fullfab.B_incremental_v3 import stopped_admission as prior

legacy = prior.legacy
require, same, digest = prior.require, prior.same, prior.digest
SCHEMA = 'smt-B-v7-recovery-admission-v1'
EVENT = 'v7_recovery_segment_registered'
PARENT = 'B_1701_1h_delta_v7'
SEGMENT = PARENT + '__recovery_001'
OLD_PENDING = prior.OLD_CALL_ID
FAILED_CALL = '278be30e-f37c-4de4-bbc3-76d81dffd4ad'
DIAGNOSTIC_CALL = '6fc8cbaf-2778-4214-a843-f76ba5f1be1e'
PARENT_LEDGER_SHA = 'bd5cea0e995b2662c9bb0b80c1b81362b267d479f00db798e6d5d20ebe88a556'
AFTER_DIAGNOSTIC_SHA = '82802f41d74a184e6b5060173215a088146c946b58bf571485015e9ce586cd53'
DIAGNOSTIC_ROWS_SHA = 'a7f73f46fab4ad590a0dd635ba4ecb9a32ea3c625d015494c1c74e54d1e93791'
PARENT_ROWS = 1813
PREFIX_ROWS = 1816
MODEL = 'gpt-6-astra'
EFFORT = 'medium'
START = 803.2499999999999
HORIZON = 3600
PER_CALL = 600
REMAINING_WALL = '10224.53'
REMAINING_BYTES = 15650178764
PARENT_WALL = '11375.47'
PARENT_BYTES = 1529690420
BASE_REFS = {
 'closure': ('artifacts/smt_fullfab_diagnostics/B_incremental_actual_host_observation_v7/root_completion.json', '6887bd18de6ae62805b082aff0ebfc24f0905b94994a9b5601bf02087b726fa5'),
 'protocol': ('artifacts/smt_fullfab_diagnostics/B_v7_channel_restore_v1/protocol.json', '61085c2890ec0888d402b81db9cab3dcf92056a5e6514652795cef48b88f710b'),
 'diagnostic': ('artifacts/smt_fullfab_diagnostics/B_v7_channel_restore_v1/diagnostic_result.json', 'a3c4bac06f1fdd2d465170c143b5f58d54ea9ddbd3364831ec66a963a0c40724'),
 'posthoc': ('artifacts/smt_fullfab_diagnostics/B_v7_channel_restore_v1/posthoc_verification.json', '9ad0ad727f2db942c13f47eadee55dcfcb4ba3cfdc003739835e336fb95c6248'),
 'after': ('artifacts/smt_fullfab_diagnostics/B_v7_channel_restore_v1/ledger_after.json', 'd8a69986cffc83e06e0f2d577dcb40adcb2d548d91e419d013976a397afe022c'),
}
PACKAGE_FIELDS = {'schema','parent_run_id','segment_run_id','parent_root_completion_sha256',
 'parent_result_sha256','parent_ledger_final_sha256','diagnostic_ledger_prefix_sha256',
 'parent_checkpoint_sha256','parent_checkpoint_state_sha256','registration_id','branch_id','instance_id',
 'simulation_start','horizon_end','next_model_index','first_clock','runtime_source_manifest',
 'model','reasoning_effort','maximum_timeout_seconds','global_max_calls','global_max_tokens',
 'remaining_wall_seconds','remaining_log_bytes','solver_seconds','automatic_retry','parent_status'}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _paths(root):
    base = Path(root).resolve() / 'runs/smt_fullfab_stage2'
    return str(base / PARENT), str(base / SEGMENT)


def require_same_root_auditor():
    here = Path(__file__).resolve()
    if here.parent.name == 'B_v7_resume_admission_v1':
        source = here.parents[3] / 'src'
    else:
        require(here.parent.name == 'B_resume_v1' and here.parents[1].name == 'smt_fullfab'
                and here.parents[2].name == 'src', 'unexpected recovery helper source location')
        source = here.parents[2]
    p = source / 'smt_fullfab/B_incremental_v3/stopped_admission.py'
    require(Path(prior.__file__).resolve() == p and hashlib.sha256(p.read_bytes()).hexdigest() ==
            '276ce9043619a813e4db60c01ba100e352b51d386aa54852d930beec4f0e58f2',
            'recovery admission must use the unchanged same-source original V7 auditor')
    prior.require_same_root_auditor()


def _small_ref(root, ref, refs):
    require(type(ref) is dict and set(ref) == {'path','sha256'}, 'explicit original small-file reference required')
    p = Path(ref['path'])
    if not p.is_absolute(): p = Path(root) / p
    require(p == p.resolve() and p.is_relative_to(Path(root).resolve()), 'evidence path must be canonical inside root')
    return legacy._read(p, ref['sha256'], refs)


def _diagnostic_rows(rows):
    diagnostic = rows[PARENT_ROWS:PREFIX_ROWS]
    require(len(diagnostic) == 3 and digest(diagnostic) == DIAGNOSTIC_ROWS_SHA,
            'complete original diagnostic records changed, including non-account fields')
    return diagnostic


def _base(rows, approval, *, root):
    """Full unchanged parent audit, then the one independently anchored diagnostic.

    No slice removes historical pending. The slice ends at the externally fixed
    original failed-parent snapshot, which the old auditor actually understands.
    """
    require_same_root_auditor()
    root = Path(root).resolve(); refs = {}; parent, segment = _paths(root)
    docs = {k: legacy._read(root / p, s, refs) for k, (p, s) in BASE_REFS.items()}
    c = docs['closure']; p = docs['protocol']; d = docs['diagnostic']; post = docs['posthoc']
    require(c['run_id'] == PARENT and c['status'] == 'failed' and c['accepted'] is False
            and c['ledger_prefix_sha256'] == PARENT_LEDGER_SHA
            and c['total_wall_seconds_upper_bound'] == PARENT_WALL
            and c['total_bytes_including_completion'] == PARENT_BYTES, 'original parent failed cost closure differs')
    actual = legacy._read(root / Path(BASE_REFS['closure'][0]).parent / 'actual_exit.json', c['actual_exit_sha256'], refs)
    require(actual['wait_completed'] is True and type(actual['actual_exit_code']) is int
            and actual['actual_exit_code'] == 1 and actual['automatic_retry'] is False, 'parent has no original terminal wait')
    result = legacy._read(Path(parent) / 'result.json', c['runner_result_sha256'], refs)
    require(result['status'] == 'failed' and result['accepted'] is False
            and same(result['simulation_seconds'], START) and result['plans'] == 1,
            'recovery requires original failed nonzero parent, not a fresh run')
    original = prior._prefix(Path(parent) / 'ledger_final.jsonl', PARENT_LEDGER_SHA, refs)
    require(len(original) == PARENT_ROWS and len(rows) >= PREFIX_ROWS and same(rows[:PARENT_ROWS], original),
            'entire original parent ledger prefix required')
    approvals = [r['approval'] for r in original if r.get('event') == 'approval']
    require(len(approvals) == 1 and same(approval, approvals[0]), 'original approval changed')
    report = prior.audit_admissions(original, approval, root=root, target_run_id=parent)
    require(not report['errors'] and not report['missing_evidence'], 'complete original V7 prefix admission failed')
    reg = report['registered_runs'][parent]
    local = legacy._account(prior._own(original, parent))
    require(same(local, c['model_account']) and same(local, result['model_account'])
            and local['attempts'] == 132 and local['pending'] == []
            and local['unknown_completed'] == [FAILED_CALL]
            and same(reg['wall_seconds'], 21600.0) and same(reg['max_log_bytes'], 17179869184)
            and reg['solver_seconds'] == 0, 'parent account or original allowance differs')
    diagnostic = _diagnostic_rows(rows)
    note, reserve, finish = diagnostic
    require([r['event'] for r in diagnostic] == ['channel_diagnostic_registered','reserve','finish'],
            'only the exact closed channel diagnostic may intervene')
    require(note['protocol_sha256'] == BASE_REFS['protocol'][1] and same(note['protocol'], p)
            and note['parent_run_id'] == parent and same(note['global_account_before'], legacy._account(original)),
            'diagnostic registration differs from its original anchored protocol/account')
    md = reserve['metadata']
    require(reserve['call_id'] == finish['call_id'] == d['call_id'] == DIAGNOSTIC_CALL
            and reserve['phase'] == 'stage2_channel_diagnostic'
            and reserve['run_id'] == str(root / 'runs/smt_fullfab_stage2/B_v7_channel_diagnostic_001/model_00000')
            and reserve['grant_id'] == approval['budget_id']
            and reserve['diagnostic_protocol_sha256'] == BASE_REFS['protocol'][1]
            and reserve['parent_failed_call_preserved'] == FAILED_CALL
            and same(reserve['account_before'], legacy._account(original))
            and md['model'] == MODEL and md['reasoning_effort'] == EFFORT
            and same(md['timeout_seconds'], 600) and same(md['authorization_context'], p['authorization_context']),
            'diagnostic reservation changed or acquired scheduling authority')
    diagnostic_result_path = root / 'runs/smt_fullfab_stage2/B_v7_channel_diagnostic_001/model_00000/result.json'
    diagnostic_result = legacy._read(diagnostic_result_path, d['result_sha256'], refs)
    expected_finish = {k:diagnostic_result[k] for k in
                       ('failure_reason','usage','duration_seconds','cost_usd','completed_turns')}
    expected_finish['result_path'] = str(diagnostic_result_path)
    require(same(finish['details'], expected_finish) and finish['status'] == d['status'] == 'success'
            and same(finish['details']['usage'], d['usage'])
            and same(finish['details']['duration_seconds'], d['duration_seconds'])
            and d['result_sha256'] == post['original_result_sha256']
            and post['valid'] is True and post['new_model_calls'] == 0
            and post['source_check_timing'] == 'post-exit only; not a claim of a pre-call source fence'
            and d['parent_status'] == 'failed' and d['scheduling_actions'] == d['physical_seconds_advanced'] == 0,
            'diagnostic completion/posthoc evidence differs')
    global_account = legacy._account(rows[:PREFIX_ROWS])
    require(same(global_account, docs['after']['global_account'])
            and docs['after']['raw_ledger_sha256'] == AFTER_DIAGNOSTIC_SHA
            and global_account['pending'] == [OLD_PENDING]
            and global_account['pending_solver_calls'] == global_account['pending_constructor_calls'] == [],
            'diagnostic must preserve every original cost/unknown/pending')
    legacy._fence(refs)
    return {'report': report, 'registration': reg, 'parent_rows': original, 'prefix_rows': list(rows[:PREFIX_ROWS]),
            'parent_account': local, 'diagnostic_account': legacy._account(diagnostic), 'result': result,
            'refs': refs, 'root_completion_sha256': BASE_REFS['closure'][1]}


def _package(root, config, base, refs):
    require(config is not None, 'recovery package must be externally pinned; no automatic activation')
    p = _small_ref(root, config, refs); parent, segment = _paths(root)
    require(type(p) is dict and set(p) == PACKAGE_FIELDS and p['schema'] == 'smt-B-v7-recovery-package-v1', 'recovery package schema differs')
    require(p['parent_run_id'] == parent and p['segment_run_id'] == segment
            and p['parent_status'] == 'failed' and p['automatic_retry'] is False
            and p['parent_root_completion_sha256'] == BASE_REFS['closure'][1]
            and p['parent_result_sha256'] == base['refs'][str(Path(parent) / 'result.json')]['sha256']
            and p['parent_ledger_final_sha256'] == PARENT_LEDGER_SHA
            and p['diagnostic_ledger_prefix_sha256'] == AFTER_DIAGNOSTIC_SHA
            and p['registration_id'] == base['registration']['registration_id'], 'recovery cannot replace original parent/registration')
    checkpoint = base['result']['checkpoint']
    require(p['parent_checkpoint_sha256'] == checkpoint['file_sha256']
            and p['parent_checkpoint_state_sha256'] == checkpoint['state_sha256']
            and same(p['simulation_start'], START) and same(p['horizon_end'], HORIZON)
            and same(p['next_model_index'], 132), 'original physical checkpoint/start/H/index differs')
    require(type(p['branch_id']) is str and p['branch_id'].startswith(SEGMENT + ':')
            and p['instance_id'] == p['branch_id'] + ':instance', 'new branch and instance must be explicit')
    require(p['model'] == MODEL and p['reasoning_effort'] == EFFORT
            and same(p['maximum_timeout_seconds'], PER_CALL) and p['global_max_calls'] is p['global_max_tokens'] is None
            and p['remaining_wall_seconds'] == REMAINING_WALL and same(p['remaining_log_bytes'], REMAINING_BYTES)
            and same(p['solver_seconds'], 0), 'recovery cannot add a fresh allowance or different model')
    clock = _small_ref(root, p['first_clock'], refs)
    require(clock['schema'] == 'smt-B-v7-recovery-first-clock-v1' and clock['segment_run_id'] == segment
            and finite(clock['started_monotonic_seconds']) and clock['started_monotonic_seconds'] > 0
            and type(clock['started_utc']) is str and clock['started_utc'], 'one original full recovery clock required')
    sources = _small_ref(root, p['runtime_source_manifest'], refs)
    require(type(sources) is dict and bool(sources), 'original frozen runtime source manifest required')
    return p, clock


def _mapping(root, config, base, fork_ref):
    refs = dict(base['refs']); p, clock = _package(root, config, base, refs)
    require(Path(fork_ref['path']).is_absolute() and Path(fork_ref['path']).is_relative_to(Path(p['segment_run_id'])),
            'fork manifest must be the original file inside this segment')
    fork = _small_ref(root, fork_ref, refs)
    require(fork['schema'] == 'smt-B-v7-explicit-fork-v1'
            and fork['branch_id'] == p['branch_id'] and fork['instance_id'] == p['instance_id']
            and fork['segment_run_path'] == p['segment_run_id']
            and fork['failed_call_id'] == FAILED_CALL and same(fork['failed_model_index'], 131)
            and fork['not_a_parent_success'] is True and fork['automatic_retry'] is False
            and fork['external_authorization_sha256'] == config['sha256'], 'fork lineage and package authority differ')
    reg = base['registration']
    m = {'schema': SCHEMA, 'parent_run_id': p['parent_run_id'], 'segment_run_id': p['segment_run_id'],
         'registration_id': reg['registration_id'], 'original_registration': reg,
         'package': deepcopy(config), 'fork_manifest': deepcopy(fork_ref),
         'branch_id': p['branch_id'], 'instance_id': p['instance_id'],
         'parent_prefix_sha256': PARENT_LEDGER_SHA, 'prior_prefix_sha256': AFTER_DIAGNOSTIC_SHA,
         'prefix_record_count': PREFIX_ROWS, 'prior_records_sha256': digest(base['prefix_rows']),
         'simulation_start': p['simulation_start'], 'horizon_end': p['horizon_end'], 'next_model_index': 132,
         'first_clock': p['first_clock'], 'started_monotonic_seconds': clock['started_monotonic_seconds'],
         'inherited': {'runner_wall_seconds': PARENT_WALL, 'log_bytes': PARENT_BYTES,
                       'parent_account': base['parent_account']},
         'remaining': {'runner_wall_seconds': REMAINING_WALL, 'log_bytes': REMAINING_BYTES},
         'diagnostic_account_separate': base['diagnostic_account'], 'solver_seconds': 0,
         'automatic_retry': False, 'new_cold_registration': False}
    m['recovery_segment_id'] = digest(m)
    legacy._fence(refs)
    return m, refs


def _resources(value, previous, local, mapping):
    require(type(value) is dict and set(value) == {'elapsed_seconds','retained_bytes'}, 'small original runtime resource observation required')
    t = value['elapsed_seconds']; n = value['retained_bytes']
    require(finite(t) and t >= 0 and type(n) is int and n >= 0, 'invalid resource observation')
    require(t >= previous['elapsed_seconds'] and n >= previous['retained_bytes'], 'resource counters cannot reset')
    remain = float(Decimal(mapping['remaining']['runner_wall_seconds'])) - t
    active = 21600.0 - mapping['inherited']['parent_account']['active_execution_seconds'] - local['active_execution_seconds']
    require(remain >= 1 and n < mapping['remaining']['log_bytes'], 'inherited recovery wall/log allowance exhausted')
    return min(PER_CALL, remain, active)


def preflight_recovery(rows, approval, *, root, package_config):
    """Read-only new-segment preflight; no append, resource reset, or restore."""
    require(len(rows) == PREFIX_ROWS, 'preflight requires original parent plus exactly one closed diagnostic')
    base = _base(rows, approval, root=root); refs = dict(base['refs'])
    package, clock = _package(root, package_config, base, refs)
    legacy._fence(refs)
    return {'schema':SCHEMA, 'registration':deepcopy(base['registration']),
            'package':deepcopy(package_config), 'branch_id':package['branch_id'], 'instance_id':package['instance_id'],
            'started_monotonic_seconds':clock['started_monotonic_seconds'],
            'inherited':{'runner_wall_seconds':PARENT_WALL,'log_bytes':PARENT_BYTES,'parent_account':base['parent_account']},
            'remaining':{'runner_wall_seconds':REMAINING_WALL,'log_bytes':REMAINING_BYTES},
            'diagnostic_account_separate':base['diagnostic_account'],
            'physical_recovery_verified':False,'resource_acceptance_verified':False}


def audit_admissions(rows, approval, *, root, target_run_id=None, package_config=None):
    """Read-only event-order admission. Historical accounts are never filtered."""
    report = {'errors': [], 'missing_evidence': [], 'registered_runs': {}, 'admissions': {}}
    try:
        parent, segment = _paths(root)
        require(target_run_id is None or str(Path(target_run_id).resolve()) in (parent, segment), 'unrelated recovery target')
        base = _base(rows, approval, root=root); report = deepcopy(base['report'])
        history = list(rows[:PREFIX_ROWS]); own = []; mapping = None
        previous = {'elapsed_seconds': 0, 'retained_bytes': 0}; last_index = 131
        if len(rows) > PREFIX_ROWS:
            row = rows[PREFIX_ROWS]
            require(row.get('event') == EVENT and row.get('segment_run_id') == segment, 'unique recovery mapping must precede new calls')
            mapping, refs = _mapping(root, package_config, base, row['mapping']['fork_manifest'])
            require(same(row['mapping'], mapping), 'recovery mapping is not the original package/fork/account projection')
            history.append(row)
            # Alias only after verifying a recovery mapping. The registration
            # itself remains the exact ORIGINAL parent row (including run_id).
            report['registered_runs'][segment] = deepcopy(base['registration'])
            for row in rows[PREFIX_ROWS + 1:]:
                account = legacy._account(history); local = legacy._account(own)
                cid = row.get('call_id')
                if row.get('event') == 'reserve':
                    md = row['metadata']; ctx = md['authorization_context']; timeout = md['timeout_seconds']
                    run = Path(row['run_id']); stem = run.name
                    require(run.parent == Path(segment) and stem.startswith('model_') and stem[6:].isdigit()
                            and stem == f'model_{int(stem[6:]):05d}' and int(stem[6:]) == last_index + 1,
                            'recovery uses one new sequential model directory from index132')
                    require(type(cid) is str and bool(cid) and not any(r.get('call_id') == cid for r in history), 'old/duplicate call identity forbidden')
                    require(account['pending'] == [OLD_PENDING] and account['pending_solver_calls'] == account['pending_constructor_calls'] == [], 'new pending attempt requires diagnosis; no automatic retry')
                    reg = base['registration']; research = report['effective_research_amendment']
                    require(row['registration_id'] == reg['registration_id'] and row['recovery_segment_id'] == mapping['recovery_segment_id']
                            and row['parent_run_id'] == parent and row['phase'] == reg['phase']
                            and row['grant_id'] == reg['budget_id'] and row['amendment_id'] == reg['amendment_id']
                            and same(ctx, {'purpose':'B','arm':'B','scenario':reg['scenario'],'window_seconds':reg['window_seconds']})
                            and md['model'] == MODEL and md['reasoning_effort'] == EFFORT, 'recovery call changed parent authority or model')
                    cap = _resources(row['recovery_resources_before'], previous, local, mapping)
                    require(finite(timeout) and 1 <= timeout <= cap, 'timeout exceeds600 or original remaining allowance')
                    combined = legacy._account(prior._own(base['parent_rows'], parent) + own)
                    require(same(row['account_before'], account) and same(row['run_account_before'], combined)
                            and same(row['segment_account_before'], local), 'recovery call reset original cumulative costs')
                    report['admissions'][cid] = {'purpose':'B','waiver_applied':True,'amendment_id':research['amendment_id'],
                        'waiver_scope':'registered_research','registration':reg,'active_seconds_before':account['model_active_seconds'],
                        'timeout_seconds':timeout,'solver_requested_seconds_before_by_arm':{},'run_solver_requested_seconds_before':0,
                        'run_active_seconds_before':combined['model_active_seconds'], 'recovery_segment_id':mapping['recovery_segment_id'],
                        'timeout_extension':base['report']['stopped_pending']['timeout_extension']}
                    previous = row['recovery_resources_before']; last_index += 1
                elif row.get('event') == 'finish':
                    require(cid in local['pending'] and cid not in (OLD_PENDING, FAILED_CALL, DIAGNOSTIC_CALL)
                            and row['status'] in ('success','failed','timeout')
                            and finite(row['details'].get('duration_seconds')) and row['details']['duration_seconds'] >= 0,
                            'finish must close one new recovery call, preserving original failures')
                else:
                    raise ValueError('unsupported event after recovery mapping; no tools, new registration, or second segment')
                own.append(row); history.append(row); legacy._account(history)
            legacy._fence(refs)
        global_account = legacy._account(history); local = legacy._account(own)
        report['stopped_pending'] = {**base['report']['stopped_pending'], 'allowed_pending_call_ids':[OLD_PENDING],
            'raw_pending':global_account['pending'],'new_run_pending_call_ids':local['pending'],
            'target_run_id':segment,'preserved_completed_unknown_call_ids':list(base['parent_account']['unknown_completed'])}
        report.update(model_active_seconds=global_account['model_active_seconds'], unknown_usage_call_ids=global_account['unknown_completed'],
                      recovery_mapping=mapping, recovery_account=legacy._account(prior._own(base['parent_rows'], parent) + own),
                      parent_account=base['parent_account'], segment_account=local, diagnostic_account_separate=base['diagnostic_account'],
                      original_parent_kept_failed=True, physical_recovery_verified=False, resource_acceptance_verified=False)
        legacy._fence(base['refs'])
    except (ValueError, KeyError, TypeError, OSError, OverflowError) as exc:
        report['errors'].append('V7 recovery admission: ' + str(exc))
    return report


def _raw_prefix(path):
    """Exact complete pre-recovery byte prefix, checked under the original lock."""
    path = Path(path); require(not path.is_symlink(), 'live ledger symlink')
    identity = legacy._identity(path.stat()); raw = bytearray()
    with path.open('rb') as f:
        require(legacy._identity(os.fstat(f.fileno())) == identity, 'ledger changed at open')
        for _ in range(PREFIX_ROWS):
            line = f.readline(1024 * 1024 + 1)
            require(line.endswith(b'\n') and len(line) <= 1024 * 1024, 'incomplete/oversize fixed ledger prefix')
            raw.extend(line)
        require(legacy._identity(os.fstat(f.fileno())) == identity, 'ledger changed during prefix read')
    require(legacy._identity(path.stat()) == identity and hashlib.sha256(raw).hexdigest() == AFTER_DIAGNOSTIC_SHA,
            'exact original parent+diagnostic raw byte prefix changed')


def make_ledger_class(original_budget_module, *, package_config, started_monotonic=None, retained_bytes_provider=None):
    """Original append/lock/account, with one narrowly scoped continuation.

    started_monotonic is the root's first clock (before restore/fork), NOT a new
    per-instance clock. Byte provider observes only newly retained recovery
    material, cheaply; complete final external resource accounting remains required.
    """
    b = original_budget_module
    class RecoveryLedger(b.BudgetLedger):
        def _audit(self, rows):
            approvals = [r['approval'] for r in rows if r.get('event') == 'approval']
            require(len(approvals) == 1, 'unique original approval required')
            report = audit_admissions(rows, approvals[0], root=b.ROOT, package_config=package_config)
            require(not report['errors'] and not report['missing_evidence'], 'recovery ledger rejected: ' + repr(report['errors']))
            return approvals[0], report

        def register_stage_run(self, *args, **kwargs):
            raise ValueError('recovery cannot create a new cold-start registration')

        def register_recovery_segment(self, segment_run_id, *, fork_manifest_path, expected_fork_manifest_sha256):
            with self._locked() as rows:
                parent, segment = _paths(b.ROOT)
                require(str(Path(segment_run_id).resolve()) == segment and len(rows) == PREFIX_ROWS,
                        'only one create-new recovery mapping; no implicit reentry')
                approval, report = self._audit(rows)
                base = _base(rows, approval, root=b.ROOT)
                fork_ref = {'path':str(Path(fork_manifest_path).resolve()), 'sha256':expected_fork_manifest_sha256}
                mapping, refs = _mapping(b.ROOT, package_config, base, fork_ref)
                row = {'event':EVENT,'segment_run_id':segment,'registration_id':mapping['registration_id'],'mapping':mapping}
                self._audit(rows + [row]); _raw_prefix(self.path); legacy._fence(refs)
                self._append(row)
                return {'registration':deepcopy(base['registration']), 'mapping':deepcopy(mapping)}

        def reserve(self, *, phase, run_id, grant_id, call_id=None, metadata=None):
            with self._locked() as rows:
                _, report = self._audit(rows); m = report['recovery_mapping']
                require(m is not None and finite(started_monotonic)
                        and same(started_monotonic, m['started_monotonic_seconds'])
                        and callable(retained_bytes_provider), 'reserve needs the original whole recovery clock and bytes observer')
                require(not (Path(m['segment_run_id']) / 'result.json').exists(),
                        'terminal recovery segment cannot be reopened')
                resources = {'elapsed_seconds':time.monotonic() - started_monotonic,
                             'retained_bytes':retained_bytes_provider()}
                reg = m['original_registration']
                row = {'event':'reserve','call_id':call_id or str(uuid.uuid4()),'phase':phase,
                       'run_id':str(Path(run_id).resolve()),'grant_id':grant_id,'metadata':metadata or {},
                       'account_before':self.account(rows),'run_account_before':report['recovery_account'],
                       'segment_account_before':report['segment_account'],'amendment_id':reg['amendment_id'],
                       'registration_id':reg['registration_id'],'parent_run_id':m['parent_run_id'],
                       'recovery_segment_id':m['recovery_segment_id'],'recovery_resources_before':resources}
                self._audit(rows + [row]); _raw_prefix(self.path)
                require(finite(row['metadata'].get('timeout_seconds')) and row['metadata']['timeout_seconds'] <=
                        float(Decimal(m['remaining']['runner_wall_seconds'])) - (time.monotonic() - started_monotonic),
                        'recovery time expired during admission checks')
                self._append(row); return row['call_id']

        def finish(self, call_id, status, details=None):
            # Finish is recorded even after a timeout/resource overrun; never
            # refuse a known new completion merely because its cost is large.
            with self._locked() as rows:
                _, report = self._audit(rows)
                require(call_id in report['segment_account']['pending'], 'cannot finish an original/foreign/completed call')
                row = {'event':'finish','call_id':call_id,'status':status,'details':details or {}}
                self._audit(rows + [row]); _raw_prefix(self.path)
                return self._append(row)

        def summary(self, run_id=None):
            with self._locked() as rows:
                if run_id is None: return self.account(rows)
                require(str(Path(run_id).resolve()) in _paths(b.ROOT), 'summary outside original recovery account')
                _, report = self._audit(rows); m = report['recovery_mapping']
                return {**report['recovery_account'], 'parent_account':report['parent_account'],
                        'segment_account':report['segment_account'], 'diagnostic_account_separate':report['diagnostic_account_separate'],
                        'recovery_mapping':m, 'inherited':None if m is None else m['inherited'],
                        'remaining':None if m is None else m['remaining'], 'resource_acceptance_verified':False}

        def solver_remaining_seconds(self, arm, run_id=None): return 0.0
        def constructor_remaining_seconds(self, arm, run_id=None): return 0.0
        def reserve_solver(self, *args, **kwargs): raise ValueError('B recovery forbids solver calls')
        def reserve_constructor(self, *args, **kwargs): raise ValueError('B recovery forbids constructor calls')
        def record_stopped_diagnosis(self, *args, **kwargs): raise ValueError('original stopped diagnosis is immutable; use the recovery mapping')
    return RecoveryLedger
