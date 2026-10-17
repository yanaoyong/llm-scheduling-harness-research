"""Deterministic per-issued-prompt grammar. Never repairs a model output."""
from copy import deepcopy
import hashlib
import json
from . import policy

VERSION = 'smt-B-v10-dynamic-response-schema-v1'
ANCHORS = ('base_plan_sha256', 'problem_sha256', 'state_sha256', 'source_sha256')

def static_response_schema(*, response_schema, assembly_schema):
    """Exact original feedback-v3 envelopes; no response projection or field defaults.

    Required task fields and optional latest_start are exposed in this transport
    grammar. Already retained base extras remain unchanged. Pure Interaction is
    still the authoritative stricter semantic validator of every original byte.
    """
    def obj(fields):
        return {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}
    def arr(item):
        return {'type': 'array', 'items': item}
    def const(value):
        return {'type': 'string', 'enum': [value]}
    text, number, integer = {'type': 'string'}, {'type': 'number'}, {'type': 'integer'}
    anchors = obj({k: text for k in ('base_plan_sha256', 'problem_sha256', 'state_sha256', 'source_sha256')})
    path = arr({'anyOf': [text, integer]})
    view = {'path': path, 'format': {'type': 'string', 'enum': ['value', 'page', 'text']}, 'offset': integer, 'count': integer}
    header = obj({'version': text, 'created_at': number, 'valid_until': number,
                  'freeze_until': number, 'reason': text, 'scope': arr(integer)})
    task_fields = {'id': text, 'machine': integer, 'lot_ids': arr(text), 'steps': arr(integer),
                   'visits': arr(integer), 'operation_ids': arr(text), 'not_before': number}
    task = {'anyOf': [obj(task_fields), obj({**task_fields, 'latest_start': {'type': ['number', 'null']}})]}
    hold_fields = {'machine': integer, 'until': number, 'reason': text}
    hold = {'anyOf': [obj(hold_fields), obj({**hold_fields, 'after_task_id': {'type': ['string', 'null']}})]}
    item = {'anyOf': [text, task, hold, obj({'ref': text, 'hold': hold}), obj({'machine': integer, 'task_ids': arr(text)})]}
    common = {'schema': const(assembly_schema), 'draft_id': text,
              'anchors': anchors, 'previous_state_sha256': text}
    assembly = {'anyOf': [obj({**common, 'action': const('seal')}), obj({**common, 'action': const('chunk'),
        'sequence': integer, 'chunk_id': text,
        'set_fields': arr(obj({'path': arr(text), 'value': {'anyOf': [text, anchors, header]}})),
        'append_arrays': arr(obj({'path': arr(text), 'items': arr(item)}))})]}
    queries = []
    for action, field in (('read_page', 'page_index'), ('read_base_tasks', 'task_ids'),
                          ('read_base_holds', 'hold_refs'), ('read_operations', 'operation_ids'), ('read_machines','machine_ids')):
        queries.append(obj({'action': const(action), 'session_id': text, 'anchors': anchors,
                            field: integer if action == 'read_page' else (arr(integer) if action == 'read_machines' else arr(text))}))
    variants = {
        'catalog_page': {'path': path, 'offset': integer, 'count': integer},
        'catalog_text': {'offset': integer, 'count': integer},
        'session_query': {'action': {'anyOf': queries}}, 'create_draft': {'draft_id': text},
        'assembly_action': {'action': assembly},
        'check_assembly': {k: text for k in ('draft_id', 'sealed_state_sha256', 'seal_action_sha256', 'delta_sha256')},
        'read_draft': {'draft_id': text, 'state_sha256': text, **view},
        'read_candidate': {'candidate_id': text, 'candidate_sha256': text, **view},
        'read_candidates': {}, 'read_archive_feedback': {'history_index': integer, 'feedback_sha256': text, **view},
        'apply': {'candidate_id': text, 'candidate_sha256': text}}
    return obj({'schema': const(response_schema), 'interaction_id': text, 'session_id': text,
                'anchors': anchors, 'catalog_sha256': text, 'prompt_body_sha256': text, 'memory': text, 'read_reason': text,
                'request': {'anyOf': [obj({'kind': const(kind), **fields}) for kind, fields in variants.items()]}})


def schema_bytes(schema):
    return (json.dumps(schema, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def _need(ok, message):
    if not ok:
        raise ValueError(message)


def _hash(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _enum(value):
    return {'type': 'integer' if type(value) is int else 'string', 'enum': [value]}


def schema_for_prompt(prompt, context):
    """Rebuild exact schema from an already issued and independently bound prompt.

    A caller must still bind prompt bytes to its original request and replayed
    state. Self-consistent prompt/schema bytes alone are not authentication.
    No model output is consumed or normalized here.
    """
    _need(type(prompt) is str and len(prompt) <= 120000, 'complete bounded prompt required')
    _need(type(context) is dict and set(context) == {'interaction_id', 'session_id', 'anchors', 'catalog_sha256'}, 'exact context required')
    _need(type(context['anchors']) is dict and set(context['anchors']) == set(ANCHORS)
          and all(_hash(value) for value in context['anchors'].values()), 'exact source/state hashes required')
    _need(all(type(context[key]) is str and context[key] for key in ('interaction_id', 'session_id'))
          and _hash(context['catalog_sha256']), 'complete context identities required')
    header, body = prompt.split('\n', 1)
    body_sha = hashlib.sha256(body.encode('utf-8')).hexdigest()
    _need(header == 'PROMPT_BODY_SHA256=' + body_sha, 'original prompt header/body mismatch')
    _need(body.count('\nINPUT_JSON\n') == 1, 'exact original INPUT_JSON delimiter required')
    task, raw_frame = body.split('\nINPUT_JSON\n', 1)
    frame = policy.strict_json(raw_frame.encode('utf-8'))
    _need(type(frame) is dict and all(policy.same(frame.get(key), value) for key, value in context.items()), 'original prompt context mismatch')
    _need(frame.get('task_text_sha256') == hashlib.sha256(task.encode('utf-8')).hexdigest(), 'original task text hash mismatch')
    contract = frame['response_contract']
    _need(contract['schema'] == policy.RESPONSE_SCHEMA
          and all(policy.same(contract.get(key), value) for key, value in context.items()), 'response contract identity mismatch')
    refs = contract['runtime_references']
    interaction_schema = policy.RESPONSE_SCHEMA.removesuffix('-response')
    _need(type(refs) is dict and set(refs) == {'schema', 'order', 'drafts', 'candidates'}
          and refs['schema'] == interaction_schema + '-references'
          and refs['order'] == 'creation_order_no_ranking', 'complete neutral references required')
    drafts, candidates = refs['drafts'], refs['candidates']
    _need(type(drafts) is list and len(drafts) <= 16 and type(candidates) is list and len(candidates) <= 32, 'reference bounds differ')
    draft_ids, candidate_ids = set(), set()
    for row in drafts:
        _need(type(row) is dict and set(row) == {'draft_id', 'state_sha256', 'phase', 'next_sequence', 'seal_action_sha256', 'delta_sha256'}, 'exact draft reference required')
        did = row['draft_id']
        _need(type(did) is str and 0 < len(did) <= 128 and did not in draft_ids and _hash(row['state_sha256']), 'invalid/duplicate draft reference')
        draft_ids.add(did)
        _need(row['phase'] in ('open', 'sealed') and type(row['next_sequence']) is int and row['next_sequence'] >= 0, 'draft phase/sequence invalid')
        _need((row['seal_action_sha256'] is None and row['delta_sha256'] is None) if row['phase'] == 'open'
              else (_hash(row['seal_action_sha256']) and _hash(row['delta_sha256'])), 'draft seal metadata inconsistent')
    for row in candidates:
        _need(type(row) is dict and set(row) == {'candidate_id', 'candidate_sha256'}, 'exact candidate reference required')
        cid = row['candidate_id']
        _need(type(cid) is str and cid and cid not in candidate_ids and _hash(row['candidate_sha256']), 'invalid/duplicate candidate reference')
        candidate_ids.add(cid)
    schema = static_response_schema(response_schema=policy.RESPONSE_SCHEMA,
                                    assembly_schema=contract['assembly_action']['schema'])
    props = schema['properties']
    for key in ('interaction_id', 'session_id', 'catalog_sha256'):
        props[key] = _enum(context[key])
    props['prompt_body_sha256'] = _enum(body_sha)
    anchors = deepcopy(props['anchors'])
    anchors['properties'] = {key: _enum(context['anchors'][key]) for key in ANCHORS}
    props['anchors'] = deepcopy(anchors)
    variants = []
    for original in props['request']['anyOf']:
        variant = deepcopy(original)
        fields = variant['properties']; kind = fields['kind']['enum'][0]
        if kind == 'session_query':
            for action in fields['action']['anyOf']:
                action['properties']['session_id'] = _enum(context['session_id'])
                action['properties']['anchors'] = deepcopy(anchors)
        elif kind == 'assembly_action':
            actions = []
            for row in drafts:
                if row['phase'] != 'open':
                    continue
                for original_action in fields['action']['anyOf']:
                    action = deepcopy(original_action); ap = action['properties']
                    ap['draft_id'] = _enum(row['draft_id'])
                    ap['anchors'] = deepcopy(anchors)
                    ap['previous_state_sha256'] = _enum(row['state_sha256'])
                    if ap['action']['enum'] == ['chunk']:
                        ap['sequence'] = _enum(row['next_sequence'])
                        # The explicitly declared anchors object is also known;
                        # arbitrary header/decision text remains model supplied.
                        values = ap['set_fields']['items']['properties']['value']['anyOf']
                        values[1] = deepcopy(anchors)
                    actions.append(action)
            if not actions:
                continue  # No legal existing-draft operation; create remains free.
            fields['action']['anyOf'] = actions
        elif kind in ('check_assembly', 'read_draft'):
            for row in drafts:
                if kind == 'check_assembly' and row['phase'] != 'sealed':
                    continue
                choice = deepcopy(variant); cp = choice['properties']; cp['draft_id'] = _enum(row['draft_id'])
                if kind == 'read_draft':
                    cp['state_sha256'] = _enum(row['state_sha256'])
                else:
                    for field, source in (('sealed_state_sha256', 'state_sha256'), ('seal_action_sha256', 'seal_action_sha256'), ('delta_sha256', 'delta_sha256')):
                        cp[field] = _enum(row[source])
                variants.append(choice)
            continue
        elif kind in ('read_candidate', 'apply'):
            for row in candidates:
                choice = deepcopy(variant)
                for field in ('candidate_id', 'candidate_sha256'):
                    choice['properties'][field] = _enum(row[field])
                variants.append(choice)
            continue
        variants.append(variant)
    props['request']['anyOf'] = variants
    policy.validate_schema_definition(schema)
    return schema

