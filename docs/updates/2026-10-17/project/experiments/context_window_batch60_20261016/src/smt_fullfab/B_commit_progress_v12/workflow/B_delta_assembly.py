"""Pure, explicit, append-only delta assembly draft. No compiler or runtime imports.

JSON values are preserved, not original transport bytes. Hashes bind local
structure only; neither a model call nor physical executability is certified.
"""
from copy import deepcopy
import hashlib
import json
import math

SCHEMA = 'draft-smt-fullfab-delta-assembly-v1'
DELTA_SCHEMA = 'smt-fullfab-explicit-plan-delta-v1'
ORDER_POLICY = 'preserve_base_machine_order_unless_explicit'
ANCHOR_KEYS = ('base_plan_sha256', 'problem_sha256', 'state_sha256', 'source_sha256')
SET_PATHS = (
    ('schema',), ('anchors',), ('plan_header',), ('order_policy',),
    ('tasks', 'keep', 'mode'), ('holds', 'keep', 'mode'),
)
ARRAY_PATHS = (
    ('tasks', 'keep', 'ids'), ('tasks', 'cancel_ids'), ('tasks', 'replace'),
    ('tasks', 'add'), ('holds', 'keep', 'ids'), ('holds', 'cancel_ids'),
    ('holds', 'replace'), ('holds', 'add'), ('machine_orders',),
)
MAX_ACTION_CHARS = 100_000
MAX_DRAFT_CHARS = 4_000_000
MAX_HISTORY_ACTION_CHARS = 8_000_000
MAX_ACTIONS = 512
MAX_CHUNKS = 256
MAX_QUERY_CHARS = 100_000
MAX_JSON_DEPTH = 48
ASSURANCE = {
    'assembly_only': True,
    'compiler_called': False,
    'model_attribution_certified': False,
    'physical_validation_performed': False,
    'selection_for_external_commit': False,
    'physical_commit_performed': False,
}


class AssemblyError(ValueError):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(code + ': ' + detail)


class AdmissionError(AssemblyError):
    """Not admitted to bounded history; caller must archive raw_action itself.

    The original supplied object is attached, not copied, to avoid another
    allocation of an over-limit input. It is not an accepted model action.
    """
    def __init__(self, code, detail, raw_action):
        super().__init__(code, detail)
        self.raw_action = raw_action


def render(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'), allow_nan=False)


def sha256(value):
    text = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _require(condition, code, detail):
    if not condition:
        raise AssemblyError(code, detail)


def _json(value, depth=0):
    _require(depth <= MAX_JSON_DEPTH, 'json_depth', 'JSON nesting exceeds the explicit depth limit')
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        _require(math.isfinite(value), 'json', 'nonfinite float')
        return
    if type(value) is list:
        for item in value:
            _json(item, depth + 1)
        return
    if type(value) is dict:
        _require(all(type(key) is str for key in value), 'json', 'JSON object keys must be strings')
        for item in value.values():
            _json(item, depth + 1)
        return
    raise AssemblyError('json', 'only exact JSON value types are supported')


def _keys(value, keys, label):
    _require(type(value) is dict and set(value) == set(keys), 'schema', label)


def _text(value):
    return type(value) is str and bool(value)


def _number(value):
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _anchors(value):
    _keys(value, ANCHOR_KEYS, 'four complete anchors required')
    _require(all(type(v) is str and len(v) == 64 and all(c in '0123456789abcdef' for c in v)
                 for v in value.values()), 'anchors', 'lowercase SHA256 anchors required')


def _ids(values, label):
    _require(type(values) is list and all(_text(v) for v in values), 'identity', label)
    _require(len(set(values)) == len(values), 'duplicate_identity', label)


def _path(value):
    _require(type(value) is list and value and all(type(v) is str for v in value), 'path', 'explicit nonempty string path required')
    return tuple(value)


def _get(root, path):
    for key in path:
        root = root[key]
    return root


def _put(root, path, value):
    for key in path[:-1]:
        if key not in root:
            root[key] = {}  # Only the JSON container; no decision value is inferred.
        root = root[key]
    root[path[-1]] = deepcopy(value)


def _field(path, value, anchors):
    if path == ('schema',):
        _require(value == DELTA_SCHEMA, 'schema', 'unsupported explicit delta schema')
    elif path == ('anchors',):
        _anchors(value)
        _require(value == anchors, 'stale_anchor', 'delta anchors differ from draft anchors')
    elif path == ('order_policy',):
        _require(value == ORDER_POLICY, 'order_policy', 'unsupported explicit order policy')
    elif path == ('plan_header',):
        _keys(value, ('version', 'created_at', 'valid_until', 'freeze_until', 'reason', 'scope'), 'complete plan_header required')
        _require(_text(value['version']) and _text(value['reason'])
                 and all(_number(value[k]) for k in ('created_at', 'valid_until', 'freeze_until')),
                 'header', 'header identity/time types')
        scope = value['scope']
        _require(type(scope) is list and all(type(mid) is int for mid in scope)
                 and len(scope) == len(set(scope)), 'header', 'scope must contain unique exact integer machines')
    else:
        choices = ('ids', 'all_pending_except') if path[0] == 'tasks' else ('ids', 'all_except')
        _require(type(value) is str and value in choices, 'keep_mode', 'explicit supported keep mode required')


def _task(value):
    required = {'id', 'machine', 'lot_ids', 'steps', 'visits', 'operation_ids', 'not_before'}
    _require(type(value) is dict and required <= set(value), 'task', 'complete task required; extra fields preserved')
    _require(_text(value['id']) and type(value['machine']) is int and _number(value['not_before']), 'task', 'task identity/start types')
    _ids(value['operation_ids'], 'task operation IDs')
    _ids(value['lot_ids'], 'task lot IDs')
    n = len(value['operation_ids'])
    _require(n > 0 and len(value['lot_ids']) == n
             and all(type(value[k]) is list and len(value[k]) == n
                     and all(type(v) is int and v >= 1 for v in value[k]) for k in ('steps', 'visits')),
             'task', 'full equal-length exact task identity arrays required')


def _hold(value):
    _require(type(value) is dict and {'machine', 'until', 'reason'} <= set(value), 'hold', 'complete hold required; extra fields preserved')
    _require(type(value['machine']) is int and _number(value['until']) and _text(value['reason']), 'hold', 'hold field types')
    if 'after_task_id' in value:
        _require(value['after_task_id'] is None or _text(value['after_task_id']), 'hold', 'explicit hold anchor type')


def _array(path, values):
    if path[-1] in ('ids', 'cancel_ids'):
        _ids(values, '.'.join(path))
    elif path[0] == 'tasks':
        for item in values:
            _task(item)
        _ids([item['id'] for item in values], '.'.join(path) + ' task IDs')
    elif path == ('holds', 'replace'):
        for item in values:
            _keys(item, ('ref', 'hold'), 'complete hold replacement required')
            _hold(item['hold'])
        _ids([item['ref'] for item in values], 'replacement hold refs')
    elif path == ('holds', 'add'):
        for item in values:
            _hold(item)
        # No native hold ID: identical user items remain identical separate items.
    else:
        machines = []
        for item in values:
            _keys(item, ('machine', 'task_ids'), 'complete indivisible machine order required')
            _require(type(item['machine']) is int, 'machine_order', 'exact integer machine required')
            _ids(item['task_ids'], 'machine task IDs')
            machines.append(item['machine'])
        _require(len(set(machines)) == len(machines), 'duplicate_identity', 'a machine order cannot be redeclared or extended')


class DeltaAssembly:
    """One local draft. Cross-instance ID registration is an external duty."""
    def __init__(self, draft_id, anchors):
        _require(_text(draft_id) and len(draft_id) <= 128, 'draft_id', 'explicit draft ID of 1..128 characters required')
        _json(anchors)
        _anchors(anchors)
        self._draft_id = draft_id
        self._anchors = deepcopy(anchors)
        self._delta = {}
        self._sources = []
        self._chunks = []
        self._history = []
        self._history_chars = 0
        self._sealed = None

    def _state(self):
        return {'schema': SCHEMA, 'draft_id': self._draft_id, 'anchors': deepcopy(self._anchors),
                'phase': 'sealed' if self._sealed is not None else 'open',
                'next_sequence': len(self._chunks), 'delta': deepcopy(self._delta),
                'sources': deepcopy(self._sources),
                'accepted_chunks': [{'chunk_id': c['chunk_id'], 'action_sha256': sha256(c)} for c in self._chunks],
                'seal_action_sha256': None if self._sealed is None else self._sealed['seal_action_sha256']}

    @property
    def state_sha256(self):
        return sha256(self._state())

    def snapshot(self):
        state = self._state()
        return {'state': state, 'state_sha256': sha256(state), 'assurance': deepcopy(ASSURANCE)}

    def export_evidence(self):
        return {**self.snapshot(), 'accepted_chunks': deepcopy(self._chunks),
                'history': deepcopy(self._history), 'sealed': deepcopy(self._sealed),
                'history_action_chars': self._history_chars,
                'identity_scope': 'draft uniqueness and sequence/selection protection are local to this object only'}

    def read(self, path, *, offset=None, count=None):
        """Exact declared value/slice, without changing state/history or ordering."""
        _require(type(path) is list and all(type(k) is str for k in path), 'path', 'JSON object path required')
        try:
            value = _get(self._delta, path)
        except (KeyError, TypeError):
            raise AssemblyError('undeclared_path', 'path has not been explicitly declared') from None
        if offset is not None or count is not None:
            _require(type(value) is list and type(offset) is int and type(count) is int
                     and 0 <= offset <= len(value) and count >= 1,
                     'slice', 'explicit array offset/count required')
            value = value[offset:offset + count]
        reply = {'path': deepcopy(path), 'offset': offset, 'count': count,
                 'value': deepcopy(value), 'state_sha256': self.state_sha256}
        _require(len(render(reply)) <= MAX_QUERY_CHARS, 'query_size', 'query exceeds character cap; caller may explicitly request a smaller array slice')
        return reply

    def submit(self, raw_action):
        """Admit one bounded JSON action, retaining accepted/rejected raw values.

        AdmissionError is outside the bounded journal and includes the supplied
        object for caller archival. No rejected action consumes sequence/hash.
        """
        try:
            _json(raw_action)
            text = render(raw_action)
            _require(len(text) <= MAX_ACTION_CHARS, 'action_size', 'action exceeds serialized character cap')
            _require(len(self._history) < MAX_ACTIONS, 'history_limit', 'attempt capacity exhausted')
            _require(self._history_chars + len(text) <= MAX_HISTORY_ACTION_CHARS,
                     'history_limit', 'raw action history character capacity exhausted')
        except (AssemblyError, ValueError, RecursionError) as error:
            raise AdmissionError(getattr(error, 'code', 'json'), str(error), raw_action) from None
        action = deepcopy(raw_action)
        before = self.state_sha256
        try:
            response = self._submit(action)
        except AssemblyError as error:
            response = {'status': 'rejected', 'error': {'code': error.code, 'detail': error.detail}}
        after = self.state_sha256
        response = {**response, 'state_sha256': after, 'assurance': deepcopy(ASSURANCE)}
        row = {'index': len(self._history), 'raw_action': action, 'raw_action_sha256': sha256(action),
               'before_state_sha256': before, 'after_state_sha256': after,
               'response': deepcopy(response),
               'previous_history_sha256': self._history[-1]['row_sha256'] if self._history else None}
        row['row_sha256'] = sha256(row)
        self._history.append(row)
        self._history_chars += len(text)
        return deepcopy(response)

    def _submit(self, action):
        _require(type(action) is dict, 'schema', 'action object required')
        kind = action.get('action')
        common = ('schema', 'action', 'draft_id', 'anchors', 'previous_state_sha256')
        if kind == 'chunk':
            _keys(action, (*common, 'sequence', 'chunk_id', 'set_fields', 'append_arrays'), 'exact chunk envelope required')
        elif kind == 'seal':
            _keys(action, common, 'exact seal envelope required')
        else:
            raise AssemblyError('action', 'only explicit chunk and seal actions are supported')
        _require(action['schema'] == SCHEMA, 'schema', 'unsupported assembly schema')
        _require(type(action['draft_id']) is str and action['draft_id'] == self._draft_id, 'draft_id', 'different draft identity')
        _anchors(action['anchors'])
        _require(action['anchors'] == self._anchors, 'stale_anchor', 'different authoritative anchors')
        _require(self._sealed is None, 'sealed', 'seal is one-time; no more mutations or seal retries')
        _require(type(action['previous_state_sha256']) is str and action['previous_state_sha256'] == self.state_sha256,
                 'stale_state', 'action must reference the exact current pre-action state hash')
        if kind == 'seal':
            declared = {tuple(s['path']) for s in self._sources}
            missing = [list(p) for p in (*SET_PATHS, *ARRAY_PATHS) if p not in declared]
            _require(not missing, 'missing_fields', 'all fields including empty arrays must be explicitly declared: ' + render(missing))
            delta = deepcopy(self._delta)
            self._sealed = {'delta': delta, 'delta_sha256': sha256(delta),
                            'pre_seal_state_sha256': action['previous_state_sha256'],
                            'seal_action_sha256': sha256(action), 'seal_action': deepcopy(action),
                            'sources': deepcopy(self._sources), 'assurance': deepcopy(ASSURANCE)}
            return {'status': 'sealed_delta', 'delta': delta, 'delta_sha256': sha256(delta),
                    'pre_seal_state_sha256': action['previous_state_sha256']}
        _require(type(action['sequence']) is int and action['sequence'] == len(self._chunks), 'sequence', 'only the next successful sequence is accepted')
        _require(_text(action['chunk_id']) and len(action['chunk_id']) <= 128, 'chunk_id', 'explicit chunk ID of 1..128 characters required')
        _require(action['chunk_id'] not in {c['chunk_id'] for c in self._chunks}, 'duplicate_chunk', 'chunk ID was already accepted')
        _require(len(self._chunks) < MAX_CHUNKS, 'chunk_limit', 'accepted chunk capacity exhausted')
        _require(type(action['set_fields']) is list and type(action['append_arrays']) is list
                 and (action['set_fields'] or action['append_arrays']), 'chunk', 'explicit nonempty set_fields/append_arrays declarations required')
        delta, sources = deepcopy(self._delta), deepcopy(self._sources)
        declared = {tuple(s['path']) for s in sources}
        touched = set()
        origin = {'chunk_id': action['chunk_id'], 'sequence': action['sequence'], 'action_sha256': sha256(action)}
        for operation_index, item in enumerate(action['set_fields']):
            _keys(item, ('path', 'value'), 'set_fields declaration')
            path = _path(item['path'])
            _require(path in SET_PATHS, 'path', 'unsupported scalar/object field path')
            _require(path not in declared and path not in touched, 'field_overwrite', 'a complete field may be declared only once')
            _field(path, item['value'], self._anchors)
            _put(delta, path, item['value'])
            sources.append({'path': list(path), 'kind': 'field', 'origin': {**origin, 'set_fields_index': operation_index}})
            touched.add(path)
        for operation_index, item in enumerate(action['append_arrays']):
            _keys(item, ('path', 'items'), 'append_arrays declaration')
            path = _path(item['path'])
            _require(path in ARRAY_PATHS, 'path', 'unsupported array path')
            _require(path not in touched, 'duplicate_path', 'each path may be declared at most once in one chunk')
            _require(type(item['items']) is list, 'array', 'explicit array items required')
            existing = _get(delta, path) if path in declared else []
            _require(path not in declared or item['items'], 'empty_append', 'an already declared array cannot be redeclared without items')
            combined = existing + deepcopy(item['items'])
            _array(path, combined)
            _put(delta, path, combined)
            entry = next((s for s in sources if tuple(s['path']) == path), None)
            array_origin = {**origin, 'append_arrays_index': operation_index}
            if entry is None:
                entry = {'path': list(path), 'kind': 'array', 'declaration_origin': array_origin, 'items': []}
                sources.append(entry)
            entry['items'].extend({'output_index': len(existing) + index,
                                   'origin': {**array_origin, 'items_index': index}}
                                  for index in range(len(item['items'])))
            touched.add(path)
        if 'tasks' in delta and 'replace' in delta['tasks'] and 'add' in delta['tasks']:
            replaced = {t['id'] for t in delta['tasks']['replace']}
            _require(not replaced.intersection(t['id'] for t in delta['tasks']['add']), 'duplicate_identity', 'task ID cannot be both replaced and added')
        _require(len(render(delta)) <= MAX_DRAFT_CHARS, 'draft_size', 'assembled delta exceeds serialized character cap')
        # All validation completed against copies; rejected chunks never publish partial work.
        self._delta, self._sources = delta, sources
        self._chunks.append(deepcopy(action))
        return {'status': 'chunk_accepted', 'chunk_id': action['chunk_id'], 'sequence': action['sequence'],
                'next_sequence': len(self._chunks), 'declared_paths': [deepcopy(s['path']) for s in sources]}
