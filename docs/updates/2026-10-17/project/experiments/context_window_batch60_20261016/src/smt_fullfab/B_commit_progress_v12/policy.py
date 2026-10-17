"""Pure eligibility classification; neither channel authentication nor dispatch.

Memory size is recorded independently of action eligibility. A wrong echoed
prompt-body hash remains a wrapper rejection. Original prompt/header and all other
structural/schema/context failures still stop. This
policy never repairs bytes, invokes a request, or changes model-authored memory.
"""
import hashlib
import json
import math

SCHEMA = 'smt-fullfab-envelope-policy-v12-commit-progress'
REJECTION_CODES = {'memory_size_rejection':'memory_size','prompt_hash_rejection':'prompt_binding'}

def is_rejection(kind):
    return type(kind) is str and kind in REJECTION_CODES
RESPONSE_SCHEMA = 'draft-smt-fullfab-delta-interaction-v12-commit-progress-v1-response'
MEMORY_LIMIT = 8192
ANCHORS = {'base_plan_sha256', 'problem_sha256', 'state_sha256', 'source_sha256'}
REQUEST_FIELDS = {
    'catalog_page': ['path', 'offset', 'count'], 'catalog_text': ['offset', 'count'],
    'session_query': ['action'], 'create_draft': ['draft_id'], 'assembly_action': ['action'],
    'check_assembly': ['draft_id', 'sealed_state_sha256', 'seal_action_sha256', 'delta_sha256'],
    'read_draft': ['draft_id', 'state_sha256', 'path', 'format', 'offset', 'count'],
    'read_candidate': ['candidate_id', 'candidate_sha256', 'path', 'format', 'offset', 'count'],
    'read_candidates': [],
    'read_archive_feedback': ['history_index', 'feedback_sha256', 'path', 'format', 'offset', 'count'],
    'read_previous_feedback': ['page_index', 'feedback_sha256', 'path', 'format', 'offset', 'count'],
    'apply': ['candidate_id', 'candidate_sha256'],
}


class PolicyError(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(code + ': ' + detail)


def require(ok, code, detail):
    if not ok:
        raise PolicyError(code, detail)


def render(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def same(left, right):
    return render(left) == render(right)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'json', 'duplicate JSON key')
            result[key] = value
        return result
    def constant(value):
        raise PolicyError('json', 'nonfinite constant: ' + value)
    result = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
    render(result)
    return result


def validate_schema_definition(schema):
    """Exact supported grammar used by controller_delta.response_schema.

    Unlike the legacy subset helper, anyOf is recursively checked. Unknown
    keywords fail closed, including maxLength rather than silently ignoring it.
    A new response grammar requires its own reviewed policy revision.
    """
    require(type(schema) is dict and set(schema) <= {
        'type', 'enum', 'anyOf', 'properties', 'required', 'additionalProperties', 'items'
    }, 'schema_grammar', 'unsupported schema keyword or non-object schema')
    if 'type' in schema:
        types = schema['type'] if type(schema['type']) is list else [schema['type']]
        require(bool(types) and all(type(t) is str and t in {
            'object', 'array', 'string', 'integer', 'number', 'boolean', 'null'
        } for t in types), 'schema_grammar', 'unsupported JSON type')
    if 'enum' in schema:
        require(type(schema['enum']) is list and bool(schema['enum']), 'schema_grammar', 'enum must be a nonempty list')
        render(schema['enum'])
    if 'anyOf' in schema:
        require(type(schema['anyOf']) is list and bool(schema['anyOf']), 'schema_grammar', 'anyOf must be nonempty')
        for variant in schema['anyOf']:
            validate_schema_definition(variant)
    if 'properties' in schema:
        require(type(schema['properties']) is dict, 'schema_grammar', 'properties must be an object')
        for sub in schema['properties'].values():
            validate_schema_definition(sub)
    if 'required' in schema:
        require(type(schema['required']) is list and all(type(k) is str for k in schema['required']),
                'schema_grammar', 'required must be a string array')
    if 'additionalProperties' in schema:
        require(type(schema['additionalProperties']) is bool, 'schema_grammar', 'additionalProperties must be boolean')
    if 'items' in schema:
        validate_schema_definition(schema['items'])


def schema_matches(value, schema):
    def kind(name):
        return {'object': lambda: type(value) is dict, 'array': lambda: type(value) is list,
                'string': lambda: type(value) is str, 'integer': lambda: type(value) is int,
                'number': lambda: type(value) in (int, float) and math.isfinite(value),
                'boolean': lambda: type(value) is bool, 'null': lambda: value is None}[name]()
    if 'type' in schema:
        types = schema['type'] if type(schema['type']) is list else [schema['type']]
        if not any(kind(name) for name in types):
            return False
    if 'enum' in schema and not any(same(value, member) for member in schema['enum']):
        return False
    if 'anyOf' in schema and not any(schema_matches(value, sub) for sub in schema['anyOf']):
        return False
    if type(value) is dict:
        properties = schema.get('properties', {})
        if any(key not in value for key in schema.get('required', [])):
            return False
        if schema.get('additionalProperties') is False and set(value) - set(properties):
            return False
        if any(not schema_matches(value[key], sub) for key, sub in properties.items() if key in value):
            return False
    if type(value) is list and 'items' in schema:
        if any(not schema_matches(item, schema['items']) for item in value):
            return False
    return True


def classify(output, prompt, context, schema):
    """Classify original parsed output; no action/eligibility inferred from memory.

    semantic action validity remains for the original Interaction; this only
    certifies the allowed wrapper-rejection class, not plan/choice feasibility.
    """
    validate_schema_definition(schema)
    require(schema_matches(output, schema), 'output_schema', 'original output fails complete supported declared schema')
    require(type(output) is dict and set(output) == {
        'schema', 'interaction_id', 'session_id', 'anchors', 'catalog_sha256', 'prompt_body_sha256', 'memory', 'read_reason', 'request'
    } and output['schema'] == RESPONSE_SCHEMA, 'envelope', 'exact original v2 envelope required')
    require(type(context) is dict and set(context) == {'interaction_id', 'session_id', 'anchors', 'catalog_sha256'},
            'context', 'complete external context required')
    require(type(context['anchors']) is dict and set(context['anchors']) == ANCHORS
            and all(type(v) is str and len(v) == 64 and all(c in '0123456789abcdef' for c in v)
                    for v in context['anchors'].values()), 'context', 'exact four source/state anchors required')
    require(all(type(output[k]) is type(v) and same(output[k], v) for k, v in context.items()),
            'context', 'output differs from current externally expected context')
    header, body = prompt.split('\n', 1)
    body_sha = sha(body.encode('utf-8'))
    require(header == 'PROMPT_BODY_SHA256=' + body_sha,
            'prompt_binding', 'actual original header/body hash differs')
    require(body.count('\nINPUT_JSON\n') == 1, 'prompt_binding', 'exact interaction body required')
    issued = strict_json(body.split('\nINPUT_JSON\n', 1)[1].encode('utf-8'))
    require(type(issued) is dict and all(same(issued.get(k), v) for k, v in context.items()),
            'prompt_binding', 'issued prompt context differs')
    request = output['request']
    require(type(request) is dict and type(request.get('kind')) is str and request['kind'] in REQUEST_FIELDS
            and set(request) == {'kind', *REQUEST_FIELDS[request['kind']]}, 'request', 'unknown or incomplete request')
    if request['kind'] in ('assembly_action', 'session_query'):
        action = request['action']
        require(type(action) is dict and same(action.get('anchors'), context['anchors']),
                'context', 'nested action anchors differ')
        if request['kind'] == 'session_query':
            require(action.get('session_id') == context['session_id'], 'context', 'nested query session differs')
    require(type(output['memory']) is str, 'memory_type', 'memory must remain an exact string')
    require(type(output['prompt_body_sha256']) is str, 'prompt_hash_type', 'echoed hash must remain a string')
    size = len(render(output['memory']))
    # Match unchanged Interaction._validate order: prompt echo precedes memory.
    if output['prompt_body_sha256'] != body_sha:
        kind='prompt_hash_rejection'
        error={'code':'prompt_binding','detail':'output must reference this currently issued prompt body'}
    else:
        kind='action';error=None
    return {'policy_schema': SCHEMA, 'kind':kind,
            'memory_serialized_characters': size, 'memory_limit': MEMORY_LIMIT,
            'request_sha256': sha(render(request).encode()), 'envelope_sha256': sha(render(output).encode()),
            'full_prompt_sha256': sha(prompt.encode()), 'prompt_body_sha256': body_sha,
            'schema_sha256': sha(render(schema).encode()), 'semantic_action_validation_performed': False,
            'model_prompt_body_sha256':output['prompt_body_sha256'],
            'error':error}


def verify_rejection_effects(before, after, response, *, kind):
    """Assert existing pure handler rejected before projecting/dispatching anything."""
    require(is_rejection(kind),'rejection_effects','only a classified exact wrapper rejection is recordable')
    record = after['history'][-1]
    require(len(after['history']) == len(before['history']) + 1 and response['response']['status'] == 'rejected'
            and response['response']['error']['code'] == REJECTION_CODES[kind], 'rejection_effects', 'expected exact wrapper rejection missing')
    require(record['parsed_envelope'] is None and record['projection'] is None,
            'rejection_effects', 'bad wrapper produced an action projection')
    require(same(record['memory_before'], record['memory_after'])
            and same(before['current_memory'], after['current_memory']), 'rejection_effects', 'invalid memory replaced previous legal memory')
    for key in ('drafts', 'candidates', 'selection', 'query_session_evidence'):
        require(same(before[key], after[key]), 'rejection_effects', 'wrapper rejection mutated action state: ' + key)
