"""Uninstalled pure feedback admission draft. No I/O or interaction mutation.

One prompt builder serves both a non-mutating admission preview and the later
final issuance check. This module cannot archive evidence, select actions,
authenticate a response, update memory, or start a model. The caller must supply
the complete next-turn frame and persist the returned originals and receipt.
"""
from copy import deepcopy
import hashlib
import json
import math


VERSION = 'draft-smt-fullfab-B-v12-whole-prompt-feedback-admission-v1'
INTERACTION_SCHEMA = 'draft-smt-fullfab-delta-interaction-v12-commit-progress-v1'
PROMPT_LIMIT = 120_000
MEMORY_LIMIT = 8192
FRAME_FIELDS = frozenset((
    'schema', 'interaction_id', 'session_id', 'anchors', 'catalog_sha256',
    'turn_index', 'task_text_sha256', 'directory', 'memory', 'memory_binding',
    'memory_policy', 'progress', 'working_set', 'execution_context', 'memory_budget', 'feedback', 'response_contract', 'limits',
))


class AdmissionError(ValueError):
    pass


class PromptTooLarge(AdmissionError):
    def __init__(self, row):
        super().__init__('exact full prompt exceeds 120000 characters; no content truncated or issued')
        self.row = deepcopy(row)


def _require(ok, message):
    if not ok:
        raise AdmissionError(message)


def _json(value):
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_json(item) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _json(item) for key, item in value.items())
    return False


def render(value):
    _require(_json(value), 'finite original JSON with exact string object keys required')
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'), allow_nan=False)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    render(value)
    return _sha(json.dumps(value, ensure_ascii=True, sort_keys=True,
                           separators=(',', ':'), allow_nan=False).encode('utf-8'))


def _frame(task_text, body_template):
    _require(type(task_text) is str and type(body_template) is dict, 'original task text and full body template required')
    render(body_template)
    _require(set(body_template) == FRAME_FIELDS, 'complete original prompt frame required; fields are never filtered')
    _require(body_template['schema'] == INTERACTION_SCHEMA, 'new interaction identity required; frozen v2 cannot be migrated in place')
    _require(body_template['feedback'] is None, 'template feedback must be an explicit empty slot')
    _require(type(body_template['turn_index']) is int and body_template['turn_index'] >= 0, 'exact next-turn index required')
    _require(body_template['task_text_sha256'] == _sha(task_text.encode('utf-8')), 'original task text hash differs')
    _require(type(body_template['memory']) is str and type(body_template['memory_binding']) is dict, 'original model memory and binding required')
    _require(len(render(body_template['memory'])) <= MEMORY_LIMIT, 'unchanged model-memory serialized limit exceeded')
    _require(type(body_template['directory']) is dict and type(body_template['response_contract']) is dict, 'complete directory and contract required')
    limits = body_template['limits']
    _require(type(limits) is dict, 'full limits object required')
    _require(type(limits.get('prompt_characters')) is int and limits['prompt_characters'] == PROMPT_LIMIT,
             'unchanged exact 120000-character final limit required')
    _require(type(limits.get('memory_serialized_characters')) is int and limits['memory_serialized_characters'] == MEMORY_LIMIT,
             'unchanged exact memory limit required')
    _require(limits.get('feedback_admission_policy') == VERSION and 'feedback_characters' not in limits,
             'new explicit admission policy required; frozen 24k protocol cannot be silently migrated')


def build_prompt(task_text, body_template, feedback):
    """Pure complete construction plus the final hard character check.

    body_template has every original field in its original insertion order,
    with feedback=None at the original position. No field is removed or sorted.
    Call this same function again at actual next_prompt issuance; a previous
    admission result is not permission to skip the final current-context check.
    """
    _frame(task_text, body_template)
    render(feedback)
    body = deepcopy(body_template)
    body['feedback'] = deepcopy(feedback)
    payload = task_text + '\nINPUT_JSON\n' + render(body)
    body_sha = _sha(payload.encode('utf-8'))
    text = 'PROMPT_BODY_SHA256=' + body_sha + '\n' + payload
    row = {'prompt': text, 'prompt_sha256': _sha(text.encode('utf-8')),
           'prompt_body_sha256': body_sha, 'prompt_characters': len(text),
           'prompt_utf8_bytes': len(text.encode('utf-8')),
           'turn_index': body['turn_index'], 'body': body}
    if len(text) > PROMPT_LIMIT:
        raise PromptTooLarge(row)
    return row


def _measurement(row):
    return {key: row[key] for key in ('prompt_sha256', 'prompt_body_sha256',
                                     'prompt_characters', 'prompt_utf8_bytes', 'turn_index')}


def admit_feedback(task_text, body_template, full_response, *, history_index):
    """Decide only full-original feedback versus an explicit size diagnostic.

    Invoke for a nonterminal action, after determining its ordinary memory
    outcome but before appending the attempted-output history. The frame must
    already contain that exact post-action memory and next history length.
    Nothing here validates an action or infers which page/model choice is next.
    A terminal explicit selection has no next prompt and must bypass this API.
    """
    _frame(task_text, body_template)
    _require(type(history_index) is int and history_index >= 0, 'exact original feedback history index required')
    _require(body_template['turn_index'] == history_index + 1, 'preview must use the actual next history length')
    _require(type(full_response) is dict, 'complete original response object required')
    original = deepcopy(full_response)
    serialized = render(original)
    original_sha = digest(original)
    receipt = {'schema': VERSION + '-receipt', 'history_index': history_index,
               'task_text_sha256': _sha(task_text.encode('utf-8')),
               'body_template_sha256': _sha(render(body_template).encode('utf-8')),
               'full_response': original, 'full_response_sha256': original_sha,
               'full_response_serialized_text': serialized,
               'full_response_serialized_sha256': _sha(serialized.encode('utf-8')),
               'full_response_serialized_characters': len(serialized),
               'prompt_character_limit': PROMPT_LIMIT,
               'durably_archived': False, 'model_called': False, 'state_mutated': False,
               'model_attribution_certified': False, 'physical_commit_performed': False}
    try:
        preview = build_prompt(task_text, body_template, original)
    except PromptTooLarge as error:
        full_measurement = _measurement(error.row)
    else:
        receipt.update(decision='full_original_feedback', ready=True,
                       feedback=deepcopy(original), feedback_sha256=original_sha,
                       full_candidate_measurement=_measurement(preview),
                       diagnostic_candidate_measurement=None, preview=preview)
        return receipt

    diagnostic = {
        'status': 'feedback_size', 'full_response_status': original.get('status'),
        'history_index': history_index, 'feedback_sha256': original_sha,
        'full_serialized_characters': len(serialized),
        'full_candidate_prompt_characters': full_measurement['prompt_characters'],
        'prompt_character_limit': PROMPT_LIMIT, 'feedback_admission_policy': VERSION,
        'full_original_feedback_included': False,
        'diagnostic': 'This is not the complete original feedback. The complete original must be durably archived before issuing this diagnostic. Use explicit read_archive_feedback path/page/text queries; no fields were selected, summarized or truncated.',
    }
    receipt.update(feedback=diagnostic, feedback_sha256=digest(diagnostic),
                   full_candidate_measurement=full_measurement)
    try:
        preview = build_prompt(task_text, body_template, diagnostic)
    except PromptTooLarge as error:
        receipt.update(decision='blocked_prompt_size', ready=False, preview=None,
                       diagnostic_candidate_measurement=_measurement(error.row))
    else:
        receipt.update(decision='explicit_size_diagnostic', ready=True, preview=preview,
                       diagnostic_candidate_measurement=_measurement(preview))
    return receipt
