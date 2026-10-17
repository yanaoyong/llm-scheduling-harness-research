"""Isolated explicit delta interaction; no model, scheduling or execution.

The caller supplies authoritative inputs and records real model provenance.
This in-memory prototype only exposes exact observations, invokes the pure delta
compiler and records a one-time selection for external commit. It is not wired
to any running controller, budget, simulator or physical audit.
"""
from copy import deepcopy
import math

from .interface import expand_pages
from .plan_delta import STATE_SCHEMA, DeltaError, anchor_hashes, compile_plan_delta, json_sha256

SCHEMA = 'smt-fullfab-plan-delta-session-v1'
CANDIDATE_SCHEMA = 'smt-fullfab-checked-delta-candidate-v1'
_COMMON = {'action', 'session_id', 'anchors'}
_PAGING_REQUIRED = {'schema', 'problem_metadata', 'source_problem_sha256', 'machine_fields', 'type_fields',
                    'operation_fields', 'operation_identity', 'eligible_override_sentinel', 'dictionary_semantics',
                    'pages', 'machine_count', 'operation_count', 'page_count'}
_PAGING_MIRRORS = {'time', 'horizon_end', 'scope', 'setup_transitions', 'min_runs'}
_PAGING_EXPLANATIONS = {
    'operation_identity': 'lot_id, step and visit are explicit columns; operation_id is never parsed',
    'dictionary_semantics': 'extras.values restores every unencoded field; extras.absent removes missing encoded fields; source_index restores original array order',
}
ACTION_FIELDS = {
    'read_page': ['page_index'],
    'read_base_tasks': ['task_ids'],
    'read_base_holds': ['hold_refs'],
    'read_operations': ['operation_ids'],
    'read_candidates': [],
    'read_candidate': ['candidate_id', 'candidate_sha256'],
    'check_delta': ['delta'],
    'apply': ['candidate_id', 'candidate_sha256'],
}


class SessionError(ValueError):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(code + ': ' + detail)


def _require(condition, code, detail):
    if not condition:
        raise SessionError(code, detail)


def _json_value(value):
    """Avoid coercing integer object keys, tuples, NaN or custom Python values."""
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_json_value(item) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _json_value(item) for key, item in value.items())
    return False


def _json_copy(value, label):
    _require(_json_value(value), 'non_json_input', label + ' must be finite JSON with string object keys')
    return deepcopy(value)


def _ids(values, label):
    _require(type(values) is list and all(type(v) is str and v for v in values), 'ids', label)
    _require(len(values) == len(set(values)), 'duplicate_ids', label)
    return values


def _validate_paging_metadata(paging, problem, state):
    """Constrain the published v2 envelope as well as the decoded observation.

    Lossless expand alone cannot reject instructions in unused top-level fields.
    observation_end is the only supported controller-added metadata extension.
    """
    expected = _PAGING_REQUIRED | (_PAGING_MIRRORS & set(problem))
    if 'observation_end' in paging:
        expected = expected | {'observation_end'}
        _require(type(paging['observation_end']) in (int, float)
                 and json_sha256(paging['observation_end']) == json_sha256(state.get('observation_end')),
                 'paging_metadata', 'observation_end must exactly mirror authoritative execution state')
    _require(set(paging) == expected, 'paging_metadata', 'unknown, missing or mismatched v2 top-level metadata fields')
    _require(all(type(paging[key]) is str and paging[key] == value for key, value in _PAGING_EXPLANATIONS.items()),
             'paging_metadata', 'v2 identity/dictionary explanations must match the published fixed schema')
    _require(type(paging['pages']) is list and all(type(page) is list for page in paging['pages'])
             and type(paging['page_count']) is int and paging['page_count'] == len(paging['pages']),
             'paging_metadata', 'page_count must exactly match the complete page array')


class DeltaSession:
    """One immutable observation, arbitrary explicit queries, one selection.

    ``describe`` is the bootstrap catalog; ``handle`` records every JSON action
    attempt, including rejections. No loading/importing candidate or state-update
    API exists. Non-JSON host values are rejected before action processing.
    ``export_evidence`` is a detached archive for an external durable recorder.
    The content-defined session_id denotes a logical snapshot, not a unique
    execution instance. Call uniqueness and selection are enforced in this object
    only; external persistent registration must prevent duplicate instances.
    """

    def __init__(self, base_plan, problem, execution_state, *, source_sha256, paging):
        self._base = _json_copy(base_plan, 'base_plan')
        self._problem = _json_copy(problem, 'problem')
        self._state = _json_copy(execution_state, 'execution_state')
        self._paging = _json_copy(paging, 'paging')
        _require(all(type(value) is dict for value in (self._base, self._problem, self._state, self._paging)),
                 'inputs', 'base/problem/state/paging must be objects')
        _validate_paging_metadata(self._paging, self._problem, self._state)
        try:
            self._anchors = anchor_hashes(self._base, self._problem, self._state, source_sha256=source_sha256)
            decoded = expand_pages(self._paging)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise SessionError('input_binding', type(exc).__name__ + ': ' + str(exc)) from exc
        _require(json_sha256(decoded) == self._anchors['problem_sha256'], 'paging_mismatch',
                 'complete v2 pages must reconstruct the authoritative problem exactly')
        _require(self._state.get('schema') == STATE_SCHEMA and self._state.get('base_plan_version') == self._base.get('version')
                 and self._state.get('time') == self._problem.get('time'), 'state_binding',
                 'current state must identify the exact base version and observation time')
        for key in ('time', 'observation_end'):
            _require(type(self._state.get(key)) in (int, float) and math.isfinite(self._state[key]),
                     'state_binding', 'state time/window must be finite numbers')
        _require(0 <= self._state['time'] < self._state['observation_end'], 'state_binding', 'state observation has expired')
        _require(type(self._problem.get('time')) in (int, float) and math.isfinite(self._problem['time'])
                 and type(self._problem.get('horizon_end')) in (int, float) and math.isfinite(self._problem['horizon_end'])
                 and self._problem['horizon_end'] > self._state['time'], 'state_binding', 'problem time/window must be current finite numbers')
        _require(type(self._base.get('version')) is str and self._base['version'], 'state_binding', 'base version must be explicit')
        tasks, holds, operations = self._base.get('tasks'), self._base.get('holds'), self._problem.get('operations')
        _require(type(tasks) is list and all(type(t) is dict for t in tasks), 'inputs', 'complete base tasks required')
        _require(type(holds) is list and all(type(h) is dict for h in holds), 'inputs', 'complete base holds required')
        _require(type(operations) is list and all(type(op) is dict for op in operations), 'inputs', 'complete operations required')
        task_ids = _ids([t.get('id') for t in tasks], 'base task IDs')
        operation_ids = _ids([op.get('operation_id') for op in operations], 'observed operation IDs')
        dispatched = _ids(self._state.get('dispatched_task_ids'), 'dispatched task IDs')
        _require(set(dispatched) <= set(task_ids), 'state_binding', 'dispatched task is not in the base plan')
        self._source_sha256 = source_sha256
        self._paging_sha256 = json_sha256(self._paging)
        identity = {'schema': SCHEMA, 'anchors': self._anchors, 'paging_sha256': self._paging_sha256}
        self._session_id = 'delta-session:' + json_sha256(identity)
        self._task_rows = {tid: (i, tasks[i]) for i, tid in enumerate(task_ids)}
        self._hold_rows = {'h:' + str(i): (i, hold) for i, hold in enumerate(holds)}
        self._operation_rows = {oid: (i, operations[i]) for i, oid in enumerate(operation_ids)}
        self._paging_metadata = {key: value for key, value in self._paging.items() if key != 'pages'}
        self._catalog = {**identity, 'session_id': self._session_id,
            'session_identity_semantics': 'Content-defined logical snapshot; no unique execution-instance identity.',
            'call_uniqueness_scope': 'This in-memory object only; external durable registration must prevent duplicate instances.',
            'selection_once_scope': 'This in-memory object only; physical commit and cross-instance deduplication are external.',
            'paging_metadata': self._paging_metadata,
            'page_indices': list(range(len(self._paging['pages']))),
            'base_plan_header': {key: value for key, value in self._base.items() if key not in ('tasks', 'holds')},
            'execution_state': self._state, 'base_task_ids': task_ids,
            'pending_base_task_ids': [tid for tid in task_ids if tid not in set(dispatched)],
            'base_hold_refs': list(self._hold_rows), 'operation_ids': operation_ids,
            'action_fields': {kind: sorted(_COMMON) + fields for kind, fields in ACTION_FIELDS.items()},
            'query_order': 'Source order in catalogs/pages; exact caller-requested ID order in reference queries. No quality ranking or truncation.',
            'model_attribution_certified': False, 'physical_validation_performed': False,
            'apply_semantics': 'One-time selection_for_external_commit only; common validation and real model provenance remain external.'}
        self._history = []
        self._candidates = {}
        self._seen_call_ids = set()
        self._last_model_index = -1
        self._selection = None

    def describe(self):
        """Immutable full reference catalog for external bootstrap delivery."""
        return deepcopy(self._catalog)

    def _candidate(self, action):
        cid = action['candidate_id']
        _require(type(cid) is str and cid in self._candidates, 'unknown_candidate',
                 'candidate must have been successfully checked in this session')
        candidate = self._candidates[cid]
        digest = json_sha256(candidate)
        _require(type(action['candidate_sha256']) is str and action['candidate_sha256'] == digest,
                 'candidate_hash', 'explicit candidate SHA256 differs from the complete stored candidate')
        _require(candidate['anchors'] == self._anchors and candidate['session_id'] == self._session_id,
                 'candidate_binding', 'candidate cannot cross observations/sessions')
        return candidate, digest

    @staticmethod
    def _summary(candidate, digest):
        compiled = candidate['compiled']
        return {'candidate_id': candidate['candidate_id'], 'candidate_sha256': digest,
                'session_id': candidate['session_id'], 'anchors': deepcopy(candidate['anchors']),
                'checked_action': deepcopy(candidate['checked_action']),
                'delta_sha256': compiled['evidence']['delta_sha256'],
                'compiled_plan_sha256': compiled['evidence']['compiled_plan_sha256'],
                'task_count': len(compiled['plan']['tasks']), 'hold_count': len(compiled['plan']['holds']),
                'compiler_accepted': True, 'model_attribution_certified': False,
                'physical_validation_performed': False, 'selected_for_external_commit': False}

    def _query_rows(self, values, rows, label, payload_name):
        requested = _ids(values, label)
        _require(all(ref in rows for ref in requested), 'unknown_reference', label + ' contains an unknown reference; no partial response')
        return {payload_name: [deepcopy(rows[ref][1]) for ref in requested],
                'references': [{'ref': ref, 'source_index': rows[ref][0]} for ref in requested]}

    def _execute(self, action, context):
        _require(self._selection is None, 'session_selected', 'session already selected a candidate; no further action or implicit revision is permitted')
        _require(type(action) is dict and type(action.get('action')) is str and action['action'] in ACTION_FIELDS,
                 'action_schema', 'unknown explicit session action')
        kind = action['action']
        _require(set(action) == _COMMON | set(ACTION_FIELDS[kind]), 'action_schema', 'unexpected or missing action fields')
        _require(action['session_id'] == self._session_id and type(action['session_id']) is str,
                 'stale_session', 'action names another observation session')
        _require(type(action['anchors']) is dict and action['anchors'] == self._anchors,
                 'stale_anchor', 'all four action anchors must exactly match this immutable session')
        if kind == 'read_page':
            index = action['page_index']
            _require(type(index) is int and 0 <= index < len(self._paging['pages']), 'page_index', 'exact valid integer page index required')
            return {'status': 'query_result', 'page_index': index, 'page': deepcopy(self._paging['pages'][index]),
                    'paging_metadata': deepcopy(self._paging_metadata)}
        if kind == 'read_base_tasks':
            result = self._query_rows(action['task_ids'], self._task_rows, 'task_ids', 'tasks')
            for ref in result['references']:
                ref['dispatched'] = ref['ref'] in self._state['dispatched_task_ids']
            return {'status': 'query_result', **result}
        if kind == 'read_base_holds':
            return {'status': 'query_result', **self._query_rows(action['hold_refs'], self._hold_rows, 'hold_refs', 'holds')}
        if kind == 'read_operations':
            return {'status': 'query_result', **self._query_rows(action['operation_ids'], self._operation_rows, 'operation_ids', 'operations')}
        if kind == 'read_candidates':
            return {'status': 'query_result', 'candidates': [self._summary(c, json_sha256(c)) for c in self._candidates.values()],
                    'order': 'successful check creation order; no default or preferred candidate'}
        if kind == 'read_candidate':
            candidate, digest = self._candidate(action)
            return {'status': 'query_result', 'candidate_sha256': digest, 'candidate': deepcopy(candidate)}
        if kind == 'check_delta':
            # No alternate planner, retry, inferred repair, or physical validator.
            compiled = compile_plan_delta(self._base, self._problem, self._state, action['delta'], source_sha256=self._source_sha256)
            cid = self._session_id + ':candidate:' + str(len(self._candidates))
            candidate = {'schema': CANDIDATE_SCHEMA, 'candidate_id': cid, 'session_id': self._session_id,
                         'anchors': deepcopy(self._anchors), 'paging_sha256': self._paging_sha256,
                         'checked_action': deepcopy(context), 'delta': deepcopy(action['delta']), 'compiled': compiled}
            digest = json_sha256(candidate)
            summary = self._summary(candidate, digest)
            self._candidates[cid] = candidate
            return {'status': 'candidate_checked', 'candidate': summary}
        candidate, digest = self._candidate(action)
        _require(candidate['checked_action']['action_index'] < context['action_index']
                 and candidate['checked_action']['model_index'] < context['model_index'],
                 'apply_order', 'apply must be a later explicit model action than the successful check')
        selection = {'status': 'selection_for_external_commit', 'session_id': self._session_id,
                     'anchors': deepcopy(self._anchors), 'candidate_id': candidate['candidate_id'],
                     'candidate_sha256': digest, 'selection_action': deepcopy(context),
                     'candidate': deepcopy(candidate), 'physical_commit_performed': False,
                     'model_attribution_certified': False, 'external_common_validation_required': True}
        self._selection = deepcopy(selection)
        return selection

    def handle(self, action, *, call_id, model_index):
        """Return a recorded response, with expected rejections as diagnostics.

        call_id/model_index are untrusted attribution references. They are only
        checked for consistency and uniqueness, never proof of a real model call.
        Every JSON attempt consumes its well-typed new call/index identity even
        if rejected; duplicate calls cannot silently invoke the compiler again.
        """
        action = _json_copy(action, 'action')
        call_id = _json_copy(call_id, 'call_id')
        model_index = _json_copy(model_index, 'model_index')
        context = {'action_index': len(self._history), 'call_id': call_id, 'model_index': model_index,
                   'action_sha256': json_sha256(action)}
        previous = self._history[-1]['record_sha256'] if self._history else None
        try:
            _require(type(call_id) is str and call_id and type(model_index) is int and model_index >= 0,
                     'call_identity', 'nonempty call ID and nonnegative exact integer model index required')
            fresh_identity = call_id not in self._seen_call_ids and model_index > self._last_model_index
            self._seen_call_ids.add(call_id)
            self._last_model_index = max(self._last_model_index, model_index)
            _require(fresh_identity, 'call_reuse', 'call ID must be unused and model index strictly increasing')
            response = self._execute(action, context)
        except (SessionError, DeltaError) as exc:
            response = {'status': 'rejected', 'error': {'origin': 'compiler' if isinstance(exc, DeltaError) else 'session',
                        'type': type(exc).__name__, 'code': exc.code, 'detail': exc.detail},
                        'candidate_created': False, 'physical_commit_performed': False}
        except Exception as exc:
            response = {'status': 'rejected', 'error': {'origin': 'unexpected_exception', 'type': type(exc).__name__,
                        'code': 'action_exception', 'detail': str(exc)},
                        'candidate_created': False, 'physical_commit_performed': False}
        record = {**context, 'session_id': self._session_id, 'anchors': deepcopy(self._anchors),
                  'action': action, 'response': deepcopy(response), 'response_sha256': json_sha256(response),
                  'previous_record_sha256': previous}
        record['record_sha256'] = json_sha256(record)
        self._history.append(record)
        return deepcopy(response)

    def export_evidence(self):
        """Detached full archive; no persistence/resume or provenance certificate."""
        return deepcopy({'schema': SCHEMA + '-evidence', 'catalog': self._catalog,
                         'inputs': {'base_plan': self._base, 'problem': self._problem, 'execution_state': self._state,
                                    'source_sha256': self._source_sha256, 'paging': self._paging},
                         'history': self._history,
                         'candidates': [{'candidate_sha256': json_sha256(c), 'candidate': c} for c in self._candidates.values()],
                         'selection': self._selection, 'model_attribution_certified': False,
                         'physical_commit_performed': False,
                         'caller_required_bindings': 'Persistently register the logical session and actual execution instance to prevent duplicate-instance execution. Persist bootstrap, original model request/output, real call provenance, all action records and selected candidate. Recheck the four anchors against actual current state before external common commit and independent audit.'})
