"""One fresh V8 protocol segment, charged to the closed original V7 lineage.

This is only ledger admission. It neither restores physical state nor certifies
that a host-produced fresh-store proof is an independent database/physical audit.
No previous action, pending call, completion, or allowance is rewritten.
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
from src.smt_fullfab.B_resume_v1 import admission as prior

legacy = prior.legacy
require, same, digest = prior.require, prior.same, prior.digest
SCHEMA = 'smt-B-direct-v8-admission-v1'
EVENT = 'fresh_protocol_segment_registered'
PARENT = prior.PARENT
PREDECESSOR = prior.SEGMENT
SEGMENT = 'B_1701_1h_delta_v8'
PREFIX_ROWS = 1927
PREFIX_SHA = '6c1166ccff241298bb4cd36c9d4d648f53ae89dfce6e46a7b93b6df87c70af5b'
CLOSURE_PATH = 'artifacts/smt_fullfab_diagnostics/B_v7_resume_root_review_v1/root_completion.json'
CLOSURE_SHA = 'a161b2fecabd0c7409659bfd51fb26b7bad9e4eb7f1d0cd19467d55df88be2be'
PRIOR_PACKAGE_PATH = 'runs/smt_fullfab_B_resume_gate/' + PREDECESSOR + '/recovery_package.json'
PRIOR_PACKAGE_SHA = '3fbe3ad1a771f98776f83d399bfaa8ec3e046a9f99afb114ac448ec5cda97847'
PRIOR_SOURCE_SHA = 'be44cb50376d3c34b62b85b25816e38f84184e7b799f153e6c80d2740b58b6d5'
MODEL, EFFORT = prior.MODEL, prior.EFFORT
START, HORIZON, PER_CALL = prior.START, prior.HORIZON, prior.PER_CALL
OLD_PENDING = prior.OLD_PENDING
INHERITED_WALL, INHERITED_BYTES = '17215.7923935429', 2231144880
REMAINING_WALL, REMAINING_BYTES = '4384.20', 14948724304
FIRST_MODEL_INDEX = 187
RESTORE_SHA = '957d6daa18268afdd466e6f702d39e96477ec932b09680cc29e226161ae59481'
RESTORE_STATE_SHA = 'd7efac142601890f5bf5223deb7a2907814f8a8681099048376ab66d1ec358e8'
PROTOCOL_CHANGE = {
    'schema': 'smt-B-v8-fresh-protocol-change-v1',
    'change': 'fresh Interaction from equivalent original physical checkpoint',
    'previous_uncommitted_draft_imported': False,
    'previous_failed_response_replayed': False,
    'original_committed_physical_plan_preserved': True,
    'original_failure_and_cost_preserved': True,
    'new_cold_start': False,
}
PACKAGE_FIELDS = {
    'schema', 'parent_run_id', 'predecessor_run_id', 'segment_run_id',
    'root_completion_sha256', 'prior_recovery_package', 'prior_ledger_final_sha256',
    'parent_checkpoint_sha256', 'parent_checkpoint_state_sha256',
    'predecessor_checkpoint_sha256', 'predecessor_checkpoint_state_sha256',
    'registration_id', 'branch_id', 'store_id', 'instance_id', 'simulation_start',
    'horizon_end', 'next_model_index', 'first_clock', 'runtime_source_manifest',
    'protocol_change', 'model', 'reasoning_effort', 'maximum_timeout_seconds',
    'global_max_calls', 'global_max_tokens', 'remaining_wall_seconds',
    'remaining_log_bytes', 'solver_seconds', 'automatic_retry', 'parent_status',
}
FRESH_FIELDS = {'schema', 'segment_run_id', 'branch_id', 'store_id', 'instance_id',
                'bootstrap_file_sha256', 'registration_file', 'durable_directory',
                'initial_prefix', 'history_count', 'drafts_count', 'candidates_count',
                'selection', 'memory'}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _hash(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _paths(root):
    base = Path(root).resolve() / 'runs/smt_fullfab_stage2'
    return tuple(str(base / name) for name in (PARENT, PREDECESSOR, SEGMENT))


def require_same_root_auditor():
    here = Path(__file__).resolve()
    require(here.parent.name == 'B_direct_v8' and here.parents[1].name == 'smt_fullfab'
            and here.parents[2].name == 'src', 'unexpected V8 source location')
    expected = here.parents[2] / 'smt_fullfab/B_resume_v1/admission.py'
    require(Path(prior.__file__).resolve() == expected
            and hashlib.sha256(expected.read_bytes()).hexdigest() == PRIOR_SOURCE_SHA,
            'V8 must use unchanged same-source complete recovery admission')
    prior.require_same_root_auditor()


def _small_ref(root, ref, refs):
    return prior._small_ref(root, ref, refs)


def _lineage_rows(rows, root):
    parent, predecessor, _ = _paths(root)
    ids = {r['call_id'] for r in rows if r.get('event') == 'reserve'
           and str(Path(r['run_id']).parent) in (parent, predecessor)}
    return [r for r in rows if r.get('call_id') in ids]


def _base(rows, approval, *, root):
    require_same_root_auditor()
    root = Path(root).resolve(); refs = {}; parent, predecessor, segment = _paths(root)
    closure = legacy._read(root / CLOSURE_PATH, CLOSURE_SHA, refs)
    require(closure['schema'] == 'smt-B-v7-recovery-root-failure-closure-v1'
            and closure['accepted'] is False and closure['status'] == 'failed_evidence_closed'
            and closure['failure_evidence_verified'] is True and closure['parent_status'] == 'failed'
            and closure['exact_physical_state_unchanged_except_restore_marker'] is True
            and closure['retry_or_replay_of_00186_permitted'] is False
            and closure['next_unique_model_index'] == FIRST_MODEL_INDEX
            and closure['new_interaction_requires_explicit_new_protocol_and_preserved_cumulative_cost'] is True,
            'original failed closure does not authorize a fresh protocol boundary')
    require(same(closure['simulation_seconds'], START) and closure['new_commits'] == 0
            and closure['full_window_completed'] is False and closure['original_runner_limit_seconds'] == 21600
            and str(closure['combined_wall_seconds_upper']) == INHERITED_WALL
            and closure['combined_retained_bytes_including_closure'] == INHERITED_BYTES
            and closure['remaining_original_retained_bytes'] == REMAINING_BYTES
            and Decimal(REMAINING_WALL) <= Decimal(str(closure['remaining_original_runner_seconds']))
            and Decimal(INHERITED_WALL) + Decimal(REMAINING_WALL) <= Decimal(21600),
            'fresh protocol cannot reset or extend the original resource allowance')
    original = prior.prior._prefix(root / 'runs/smt_fullfab_B_resume_gate' / PREDECESSOR / 'ledger_final.jsonl', PREFIX_SHA, refs)
    require(closure['ledger_final_sha256'] == PREFIX_SHA and len(original) == PREFIX_ROWS
            and len(rows) >= PREFIX_ROWS and same(rows[:PREFIX_ROWS], original),
            'entire closed parent+diagnostic+recovery ledger prefix required')
    config = {'path': str(root / PRIOR_PACKAGE_PATH), 'sha256': PRIOR_PACKAGE_SHA}
    report = prior.audit_admissions(original, approval, root=root,
                                    target_run_id=predecessor, package_config=config)
    require(not report['errors'] and not report['missing_evidence'],
            'original complete recovery prefix audit failed: ' + repr(report['errors']))
    result = legacy._read(Path(predecessor) / 'result.json', closure['result_sha256'], refs)
    require(result['status'] == 'failed' and result['accepted'] is False
            and same(result['simulation_seconds'], START) and result['new_commits'] == 0
            and result['checkpoint_sha256'] == closure['checkpoint_sha256']
            and result['checkpoint_state_sha256'] == closure['checkpoint_state_sha256'],
            'closed predecessor terminal state differs')
    local = legacy._account(_lineage_rows(original, root)); global_account = legacy._account(original)
    require(same(local, closure['cumulative_model_account']) and same(local, report['recovery_account'])
            and same(report['segment_account'], closure['segment_model_account'])
            and local['attempts'] == 187 and local['reported_input_output_tokens'] == 4475910
            and local['pending'] == [] and local['unknown_completed'] == [prior.FAILED_CALL]
            and global_account['pending'] == [OLD_PENDING]
            and global_account['pending_solver_calls'] == global_account['pending_constructor_calls'] == [],
            'original cumulative costs, unknown usage, or old pending differ')
    original_package = _small_ref(root, config, refs)
    require(original_package['parent_checkpoint_sha256'] == RESTORE_SHA
            and original_package['parent_checkpoint_state_sha256'] == RESTORE_STATE_SHA,
            'original equivalent checkpoint differs')
    legacy._fence(refs)
    return {'report': report, 'registration': report['registered_runs'][parent],
            'prefix_rows': original, 'lineage_rows': _lineage_rows(original, root),
            'parent_account': local, 'diagnostic_account': report['diagnostic_account_separate'],
            'closure': closure, 'result': result, 'refs': refs, 'prior_package': config}


def _package(root, config, base, refs):
    require(config is not None, 'externally pinned explicit fresh protocol package required')
    p = _small_ref(root, config, refs); parent, predecessor, segment = _paths(root)
    require(type(p) is dict and set(p) == PACKAGE_FIELDS
            and p['schema'] == 'smt-B-v8-fresh-protocol-package-v1', 'fresh package schema differs')
    require(p['parent_run_id'] == parent and p['predecessor_run_id'] == predecessor
            and p['segment_run_id'] == segment and p['parent_status'] == 'failed'
            and p['automatic_retry'] is False and p['root_completion_sha256'] == CLOSURE_SHA
            and p['prior_ledger_final_sha256'] == PREFIX_SHA
            and same(p['prior_recovery_package'], base['prior_package'])
            and p['registration_id'] == base['registration']['registration_id'],
            'fresh package changed original lineage/authority')
    require(p['parent_checkpoint_sha256'] == RESTORE_SHA
            and p['parent_checkpoint_state_sha256'] == RESTORE_STATE_SHA
            and p['predecessor_checkpoint_sha256'] == base['closure']['checkpoint_sha256']
            and p['predecessor_checkpoint_state_sha256'] == base['closure']['checkpoint_state_sha256']
            and same(p['simulation_start'], START) and same(p['horizon_end'], HORIZON)
            and same(p['next_model_index'], FIRST_MODEL_INDEX),
            'fresh segment must restore original equivalent physical state with absolute clock')
    require(type(p['branch_id']) is str and p['branch_id'].startswith(SEGMENT + ':')
            and p['instance_id'] == p['branch_id'] + ':instance'
            and type(p['store_id']) is str and p['store_id'].startswith(SEGMENT + ':'),
            'new explicit branch/store/instance identities required')
    require(p['model'] == MODEL and p['reasoning_effort'] == EFFORT
            and same(p['maximum_timeout_seconds'], PER_CALL)
            and p['global_max_calls'] is p['global_max_tokens'] is None
            and p['remaining_wall_seconds'] == REMAINING_WALL
            and same(p['remaining_log_bytes'], REMAINING_BYTES) and same(p['solver_seconds'], 0),
            'fresh protocol adds allowance or changes model')
    change = _small_ref(root, p['protocol_change'], refs)
    require(same(change, PROTOCOL_CHANGE), 'explicit fresh-protocol/no-draft/no-replay declaration differs')
    clock = _small_ref(root, p['first_clock'], refs)
    require(clock['schema'] == 'smt-B-v8-fresh-first-clock-v1' and clock['segment_run_id'] == segment
            and finite(clock['started_monotonic_seconds']) and clock['started_monotonic_seconds'] > 0
            and type(clock['started_utc']) is str and clock['started_utc'],
            'original whole-segment first clock required')
    sources = _small_ref(root, p['runtime_source_manifest'], refs)
    require(type(sources) is dict and bool(sources)
            and all(type(k) is str and _hash(v) for k, v in sources.items()),
            'original frozen source hash manifest required')
    return p, clock


def _mapping(root, config, base, fresh_ref):
    refs = dict(base['refs']); p, clock = _package(root, config, base, refs)
    segment = Path(p['segment_run_id'])
    require(Path(fresh_ref['path']).is_absolute() and Path(fresh_ref['path']).is_relative_to(segment),
            'fresh-store proof must be an original file inside the new segment')
    fresh = _small_ref(root, fresh_ref, refs)
    require(type(fresh) is dict and set(fresh) == FRESH_FIELDS
            and fresh['schema'] == 'smt-B-v8-fresh-store-proof-v1'
            and all(fresh[k] == p[k] for k in ('segment_run_id','branch_id','store_id','instance_id'))
            and all(type(fresh[k]) is int and fresh[k] == 0
                    for k in ('history_count','drafts_count','candidates_count'))
            and fresh['selection'] is fresh['memory'] is None
            and _hash(fresh['bootstrap_file_sha256']), 'fresh store is not the explicit empty model history')
    directory = Path(fresh['durable_directory'])
    require(directory == directory.resolve() and directory.is_relative_to(segment), 'fresh store outside this segment')
    registration_ref = fresh['registration_file']
    require(Path(registration_ref['path']).is_relative_to(segment), 'fresh registration file outside this segment')
    registration = _small_ref(root, registration_ref, refs); proof = fresh['initial_prefix']
    require(type(proof) is dict and set(proof) == {'journal_records','journal_tail_sha256','database_sha256'}
            and type(proof['journal_records']) is int and proof['journal_records'] == 2
            and _hash(proof['journal_tail_sha256']) and _hash(proof['database_sha256'])
            and registration['accepted'] is True and registration['error'] is None
            and same(registration['journal_records'], proof['journal_records'])
            and registration['journal_tail_sha256'] == proof['journal_tail_sha256']
            and type(registration['value']) is dict
            and type(registration['value'].get('interaction_id')) is str,
            'fresh producer registration is not bound to its original two-event prefix')
    reg = base['registration']
    m = {'schema': SCHEMA, 'parent_run_id':p['parent_run_id'], 'predecessor_run_id':p['predecessor_run_id'],
         'segment_run_id':p['segment_run_id'], 'registration_id':reg['registration_id'],
         'original_registration':reg, 'package':deepcopy(config), 'fresh_store':deepcopy(fresh_ref),
         'branch_id':p['branch_id'], 'instance_id':p['instance_id'], 'store_id':p['store_id'],
         'prior_prefix_sha256':PREFIX_SHA, 'prefix_record_count':PREFIX_ROWS,
         'prior_records_sha256':digest(base['prefix_rows']), 'simulation_start':p['simulation_start'],
         'horizon_end':p['horizon_end'], 'next_model_index':FIRST_MODEL_INDEX,
         'first_clock':p['first_clock'], 'started_monotonic_seconds':clock['started_monotonic_seconds'],
         'inherited':{'runner_wall_seconds':INHERITED_WALL,'log_bytes':INHERITED_BYTES,'parent_account':base['parent_account']},
         'remaining':{'runner_wall_seconds':REMAINING_WALL,'log_bytes':REMAINING_BYTES},
         'diagnostic_account_separate':base['diagnostic_account'], 'solver_seconds':0,
         'protocol_change':p['protocol_change'],'automatic_retry':False,'new_cold_registration':False}
    m['fresh_protocol_segment_id'] = digest(m)
    legacy._fence(refs)
    return m, refs


def _resources(value, previous, local, mapping):
    return prior._resources(value, previous, local, mapping)


def preflight_recovery(rows, approval, *, root, package_config):
    require(len(rows) == PREFIX_ROWS, 'fresh preflight requires the exact closed recovery prefix')
    base = _base(rows, approval, root=root); refs = dict(base['refs'])
    package, clock = _package(root, package_config, base, refs); legacy._fence(refs)
    return {'schema':SCHEMA, 'registration':deepcopy(base['registration']), 'package':deepcopy(package_config),
            'branch_id':package['branch_id'],'instance_id':package['instance_id'],'store_id':package['store_id'],
            'started_monotonic_seconds':clock['started_monotonic_seconds'],
            'inherited':{'runner_wall_seconds':INHERITED_WALL,'log_bytes':INHERITED_BYTES,'parent_account':base['parent_account']},
            'remaining':{'runner_wall_seconds':REMAINING_WALL,'log_bytes':REMAINING_BYTES},
            'diagnostic_account_separate':base['diagnostic_account'],
            'physical_recovery_verified':False,'resource_acceptance_verified':False}


def audit_admissions(rows, approval, *, root, target_run_id=None, package_config=None):
    report = {'errors':[],'missing_evidence':[],'registered_runs':{},'admissions':{}}
    try:
        parent, predecessor, segment = _paths(root)
        require(target_run_id is None or str(Path(target_run_id).resolve()) in (parent, predecessor, segment),
                'unrelated fresh protocol target')
        base = _base(rows, approval, root=root); report = deepcopy(base['report'])
        history = list(rows[:PREFIX_ROWS]); own = []; mapping = None
        previous = {'elapsed_seconds':0,'retained_bytes':0}; last_index = FIRST_MODEL_INDEX - 1
        if len(rows) > PREFIX_ROWS:
            row = rows[PREFIX_ROWS]
            require(row.get('event') == EVENT and row.get('segment_run_id') == segment,
                    'unique fresh protocol mapping must precede new calls')
            mapping, refs = _mapping(root, package_config, base, row['mapping']['fresh_store'])
            require(same(row['mapping'], mapping) and row.get('registration_id') == mapping['registration_id'],
                    'fresh mapping is not exact original package/store/account projection')
            history.append(row); report['registered_runs'][segment] = deepcopy(base['registration'])
            for row in rows[PREFIX_ROWS + 1:]:
                account = legacy._account(history); local = legacy._account(own); cid = row.get('call_id')
                if row.get('event') == 'reserve':
                    md = row['metadata']; run = Path(row['run_id']); stem = run.name
                    require(run.parent == Path(segment) and stem.startswith('model_') and stem[6:].isdigit()
                            and stem == f'model_{int(stem[6:]):05d}' and int(stem[6:]) == last_index + 1,
                            'new sequential unique model directories must begin at187')
                    require(type(cid) is str and cid and not any(r.get('call_id') == cid for r in history),
                            'old or duplicate call identity forbidden')
                    require(account['pending'] == [OLD_PENDING]
                            and account['pending_solver_calls'] == account['pending_constructor_calls'] == [],
                            'new pending call blocks admission; no retry')
                    reg = base['registration']; timeout = md['timeout_seconds']
                    require(row['registration_id'] == reg['registration_id']
                            and row['fresh_protocol_segment_id'] == mapping['fresh_protocol_segment_id']
                            and row['parent_run_id'] == parent and row['phase'] == reg['phase']
                            and row['grant_id'] == reg['budget_id'] and row['amendment_id'] == reg['amendment_id']
                            and same(md['authorization_context'],{'purpose':'B','arm':'B','scenario':reg['scenario'],'window_seconds':reg['window_seconds']})
                            and md['model'] == MODEL and md['reasoning_effort'] == EFFORT,
                            'fresh reserve changed original authority or model')
                    cap = _resources(row['fresh_resources_before'], previous, local, mapping)
                    require(finite(timeout) and 1 <= timeout <= cap, 'timeout exceeds600 or cumulative remaining allowance')
                    combined = legacy._account(base['lineage_rows'] + own)
                    require(same(row['account_before'], account) and same(row['run_account_before'], combined)
                            and same(row['segment_account_before'], local), 'fresh reserve reset original cumulative costs')
                    report['admissions'][cid] = {'purpose':'B','waiver_applied':True,
                        'amendment_id':reg['amendment_id'],'waiver_scope':'registered_research','registration':reg,
                        'active_seconds_before':account['model_active_seconds'],'timeout_seconds':timeout,
                        'solver_requested_seconds_before_by_arm':{},'run_solver_requested_seconds_before':0,
                        'run_active_seconds_before':combined['model_active_seconds'],
                        'fresh_protocol_segment_id':mapping['fresh_protocol_segment_id'],
                        'timeout_extension':base['report']['stopped_pending']['timeout_extension']}
                    previous = row['fresh_resources_before']; last_index += 1
                elif row.get('event') == 'finish':
                    require(cid in local['pending'] and row['status'] in ('success','failed','timeout')
                            and finite(row['details'].get('duration_seconds')) and row['details']['duration_seconds'] >= 0,
                            'finish can close only a unique new fresh-segment call')
                else:
                    raise ValueError('unsupported fresh suffix; no tools, cold registration, or second mapping')
                own.append(row); history.append(row); legacy._account(history)
            legacy._fence(refs)
        global_account = legacy._account(history); local = legacy._account(own)
        report['stopped_pending'] = {**base['report']['stopped_pending'],'allowed_pending_call_ids':[OLD_PENDING],
            'raw_pending':global_account['pending'],'new_run_pending_call_ids':local['pending'],
            'target_run_id':segment,'preserved_completed_unknown_call_ids':base['parent_account']['unknown_completed']}
        report.update(model_active_seconds=global_account['model_active_seconds'],
            unknown_usage_call_ids=global_account['unknown_completed'],fresh_mapping=mapping,
            recovery_mapping=mapping, recovery_account=legacy._account(base['lineage_rows'] + own),
            parent_account=base['parent_account'],segment_account=local,
            diagnostic_account_separate=base['diagnostic_account'],original_parent_kept_failed=True,
            physical_recovery_verified=False,resource_acceptance_verified=False)
        legacy._fence(base['refs'])
    except (ValueError, KeyError, TypeError, OSError, OverflowError) as exc:
        report['errors'].append('V8 fresh admission: ' + str(exc))
    return report


def _raw_prefix(path):
    path = Path(path); require(not path.is_symlink(), 'live ledger symlink')
    ident = legacy._identity(path.stat()); raw = bytearray()
    with path.open('rb') as f:
        require(legacy._identity(os.fstat(f.fileno())) == ident, 'ledger changed at open')
        for _ in range(PREFIX_ROWS):
            line = f.readline(1024 * 1024 + 1)
            require(line.endswith(b'\n') and len(line) <= 1024 * 1024, 'incomplete fixed ledger prefix')
            raw.extend(line)
        require(legacy._identity(os.fstat(f.fileno())) == ident, 'ledger changed during prefix read')
    require(legacy._identity(path.stat()) == ident and hashlib.sha256(raw).hexdigest() == PREFIX_SHA,
            'complete closed V7 recovery raw prefix changed')


def make_ledger_class(original_budget_module, *, package_config, started_monotonic=None, retained_bytes_provider=None):
    b = original_budget_module
    class FreshSegmentLedger(b.BudgetLedger):
        def _audit(self, rows):
            approvals = [r['approval'] for r in rows if r.get('event') == 'approval']
            require(len(approvals) == 1, 'unique original approval required')
            report = audit_admissions(rows, approvals[0], root=b.ROOT, package_config=package_config)
            require(not report['errors'] and not report['missing_evidence'], 'fresh ledger rejected: ' + repr(report['errors']))
            return approvals[0], report

        def register_stage_run(self, *args, **kwargs):
            raise ValueError('fresh protocol inherits original registration; no cold allowance')

        def register_fresh_segment(self, segment_run_id, *, fresh_store_path, expected_fresh_store_sha256):
            with self._locked() as rows:
                parent, predecessor, segment = _paths(b.ROOT)
                require(str(Path(segment_run_id).resolve()) == segment and len(rows) == PREFIX_ROWS,
                        'only one create-new fresh mapping; no reentry')
                approval, _ = self._audit(rows); base = _base(rows, approval, root=b.ROOT)
                ref = {'path':str(Path(fresh_store_path).resolve()),'sha256':expected_fresh_store_sha256}
                mapping, refs = _mapping(b.ROOT, package_config, base, ref)
                row = {'event':EVENT,'segment_run_id':segment,'registration_id':mapping['registration_id'],'mapping':mapping}
                self._audit(rows + [row]); _raw_prefix(self.path); legacy._fence(refs)
                self._append(row)
                return {'registration':deepcopy(base['registration']),'mapping':deepcopy(mapping)}

        def reserve(self, *, phase, run_id, grant_id, call_id=None, metadata=None):
            with self._locked() as rows:
                _, report = self._audit(rows); m = report['fresh_mapping']
                require(m is not None and finite(started_monotonic)
                        and same(started_monotonic,m['started_monotonic_seconds'])
                        and callable(retained_bytes_provider), 'original whole-segment clock/bytes observer required')
                require(not (Path(m['segment_run_id'])/'result.json').exists(), 'terminal segment cannot reopen')
                resources = {'elapsed_seconds':time.monotonic()-started_monotonic,
                             'retained_bytes':retained_bytes_provider()}
                reg = m['original_registration']
                row = {'event':'reserve','call_id':call_id or str(uuid.uuid4()),'phase':phase,
                       'run_id':str(Path(run_id).resolve()),'grant_id':grant_id,'metadata':metadata or {},
                       'account_before':self.account(rows),'run_account_before':report['recovery_account'],
                       'segment_account_before':report['segment_account'],'amendment_id':reg['amendment_id'],
                       'registration_id':reg['registration_id'],'parent_run_id':m['parent_run_id'],
                       'fresh_protocol_segment_id':m['fresh_protocol_segment_id'],'fresh_resources_before':resources}
                self._audit(rows + [row]); _raw_prefix(self.path)
                require(finite(row['metadata'].get('timeout_seconds')) and row['metadata']['timeout_seconds'] <=
                        float(Decimal(m['remaining']['runner_wall_seconds']))-(time.monotonic()-started_monotonic),
                        'remaining time exhausted during admission')
                self._append(row); return row['call_id']

        def finish(self, call_id, status, details=None):
            with self._locked() as rows:
                _, report = self._audit(rows)
                require(call_id in report['segment_account']['pending'], 'cannot finish original/foreign/completed call')
                row = {'event':'finish','call_id':call_id,'status':status,'details':details or {}}
                self._audit(rows + [row]); _raw_prefix(self.path)
                return self._append(row)

        def summary(self, run_id=None):
            with self._locked() as rows:
                if run_id is None: return self.account(rows)
                require(str(Path(run_id).resolve()) in _paths(b.ROOT), 'summary outside cumulative lineage')
                _, report = self._audit(rows); m = report['fresh_mapping']
                return {**report['recovery_account'],'parent_account':report['parent_account'],
                    'segment_account':report['segment_account'],'diagnostic_account_separate':report['diagnostic_account_separate'],
                    'fresh_mapping':m,'recovery_mapping':m,'inherited':None if m is None else m['inherited'],
                    'remaining':None if m is None else m['remaining'],'resource_acceptance_verified':False}

        def solver_remaining_seconds(self, arm, run_id=None): return 0.0
        def constructor_remaining_seconds(self, arm, run_id=None): return 0.0
        def reserve_solver(self, *args, **kwargs): raise ValueError('B fresh segment forbids solvers')
        def reserve_constructor(self, *args, **kwargs): raise ValueError('B fresh segment forbids constructors')
        def register_recovery_segment(self, *args, **kwargs): raise ValueError('fresh protocol cannot fork or replay previous draft')
        def record_stopped_diagnosis(self, *args, **kwargs): raise ValueError('old stopped evidence is immutable')
    return FreshSegmentLedger
