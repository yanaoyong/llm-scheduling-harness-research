"""Isolated v6 same-owner incremental replay candidate. No transport/budget/physical action is called.

Immutable blobs + an append-only journal; pure replay checks semantics. Supplied
transport/ledger artifacts are only structurally bound, never authenticated.
"""
from base64 import b64decode
from contextlib import closing, contextmanager
from copy import deepcopy
import fcntl
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sqlite3
import stat

from src.smt_fullfab.B_incremental_v3 import policy as envelope_policy

PROJECT = Path(__file__).resolve().parents[3]
HERE = PROJECT / 'src/smt_fullfab'
WORKFLOW = Path(__file__).resolve().parent / 'workflow'
INTERACTION_SHA256 = '39e5b9d3d01a5494aeb8a9f90b55a2cc1adfee5b0a692869a7b2499adc56234f'
path = WORKFLOW / 'interaction.py'
raw = path.read_bytes()
if hashlib.sha256(raw).hexdigest() != INTERACTION_SHA256:
    raise RuntimeError('interaction draft differs from pinned source')
spec = importlib.util.spec_from_file_location('_smt_fullfab_durable_interaction', path)
interaction = importlib.util.module_from_spec(spec)
exec(compile(raw, str(path), 'exec'), interaction.__dict__)


_TIMING_PATH = Path(__file__).with_name('timing.py')
_TIMING_SHA256 = '46b8b37c60f45329a037fd9e86ed06562a8553a9afc3ba8844b6317e56a59339'
_timing_raw = _TIMING_PATH.read_bytes()
if hashlib.sha256(_timing_raw).hexdigest() != _TIMING_SHA256:
    raise RuntimeError('timing runtime differs from pinned original bytes')
_timing_spec = importlib.util.spec_from_file_location('_B_incremental_timing', _TIMING_PATH)
timing = importlib.util.module_from_spec(_timing_spec)
exec(compile(_timing_raw, str(_TIMING_PATH), 'exec'), timing.__dict__)

SCHEMA = 'smt-fullfab-durable-interaction-v10-call600'
LAUNCH_BLOCKERS = ()  # Runtime candidate; original gate prerequisites remain fail-closed.
MAX_BLOB_BYTES = 8_000_000
MAX_DATABASE_BYTES = 128_000_000
MAX_EVENTS = 8192
FLAGS = {'transport_authenticated': False, 'ledger_authenticated': False,
         'physical_commit_verified': False, 'external_commit_ready': False,
         'automatic_model_retry_allowed': False, 'automatic_physical_commit_allowed': False,
         'cross_store_deduplication_certified': False}


class StoreError(ValueError):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(code + ': ' + detail)


def require(condition, code, detail):
    if not condition:
        raise StoreError(code, detail)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return interaction.render(value).encode('utf-8')


def digest(value):
    return interaction.digest(value)


def same(left, right):
    return digest(left) == digest(right)


def decode(raw):
    value = interaction.prompt_layer.strict_json(raw)
    encode(value)
    return value


def identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def runtime_manifest():
    # Replay must use exactly the installed pure implementation, not merely a matching schema name.
    project = PROJECT
    files = [Path(__file__).resolve(), Path(__file__).with_name('timing.py'),
             Path(__file__).with_name('telemetry.py'), Path(__file__).with_name('bridge.py'),
             Path(__file__).with_name('controller.py'), Path(__file__).with_name('transport.py'),
             Path(__file__).with_name('binding.py'), Path(__file__).with_name('policy.py'), Path(__file__).with_name('stopped_admission.py'),
             Path(__file__).with_name('__init__.py'), WORKFLOW / '__init__.py', WORKFLOW / 'interaction.py',
             WORKFLOW / 'B_delta_prompt.py', WORKFLOW / 'B_delta_assembly.py',
             WORKFLOW / 'B_feedback_admission.py']
    files += [project / 'src/smt_fullfab' / name for name in ('plan_delta.py', 'delta_session.py', 'interface.py',
        'B_feedback_admission.py', 'B_delta_envelope_policy_v2.py', 'B_delta_transport_binding_v3.py', 'B_delta_call_bridge_v4.py',
        'controller_delta_v4.py', 'model_transport_supervised.py', 'model_process_guard.py', 'budget.py',
        'controller_audit.py', 'constructor_audit.py', 'B_incremental_v1/stopped_admission.py', 'B_incremental_v1/__init__.py', 'B_incremental_v2/stopped_admission.py', 'B_incremental_v2/__init__.py', '__init__.py')]
    files.append(project / 'src/__init__.py')
    return {str(p.relative_to(project)): sha(p.read_bytes()) for p in files}


def fresh_session(inputs):
    require(type(inputs) is dict and set(inputs) == {'base_plan', 'problem', 'execution_state', 'source_sha256', 'paging'},
            'bootstrap', 'exact complete interaction bootstrap required')
    return interaction.Interaction(inputs['base_plan'], inputs['problem'], inputs['execution_state'],
                                   source_sha256=inputs['source_sha256'], paging=inputs['paging'])


def expected_fingerprint(prompt, schema_raw, config):
    return sha((prompt + '\n' + schema_raw.decode('utf-8') + '\n' + json.dumps(config, sort_keys=True)).encode())


def _new_state():
    return {'store_id': None, 'runtime': None, 'sessions': {}, 'instances': {}, 'attempts': {},
            'call_ids': set(), 'run_dirs': set(), 'rejections': [], 'tail': None, 'records': 0}


EVENT_FIELDS = {
    'store_created': {'schema', 'store_id', 'runtime'},
    'write_rejected': {'operation', 'args', 'original_blob_refs', 'error'},
    'session_created': {'interaction_id', 'instance_id', 'bootstrap_blob'},
    'instance_attached': {'interaction_id', 'instance_id'},
    'attempt_reserved': {'interaction_id', 'instance_id', 'attempt_id', 'model_index', 'prompt_blob', 'spec_blob', 'full_prompt_sha256', 'body_sha256'},
    'transport_requested': {'attempt_id', 'call_id', 'request_blob', 'reserve_blob', 'claim_blob', 'prompt_file_blob', 'schema_file_blob'},
    'transport_completed': {'attempt_id', 'result_blob', 'finish_blob', 'events_blob', 'final_blob'},
    'action_recorded': {'attempt_id', 'record_blob', 'record_sha256', 'candidate_blobs', 'selection_blob', 'processing'},
    'external_commit_intent': {'interaction_id', 'instance_id', 'intent_id', 'selection_sha256', 'plan_sha256', 'current_anchors', 'unverified_external_reference'},
    'external_commit_receipt': {'interaction_id', 'instance_id', 'intent_id', 'reported_outcome', 'receipt_blob', 'unverified_external_reference'},
}
JSON_BLOBS = {'bootstrap_blob', 'prompt_blob', 'spec_blob', 'request_blob', 'reserve_blob', 'result_blob',
              'finish_blob', 'record_blob', 'selection_blob'}
NULLABLE_BLOBS = {'final_blob', 'selection_blob'}


def hash_string(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def verify_event_closure(kind, payload, get_json, get_blob):
    """Every declared reference is dereferenced even if its action is still pending.

    Rejected input and external receipts are opaque original bytes, not inferred
    JSON or certified external outcomes. Their role/owner/intent is checked by fold.
    """
    require(kind in EVENT_FIELDS and type(payload) is dict and set(payload) == EVENT_FIELDS[kind],
            'journal_schema', 'exact known event fields required')
    for key in ('interaction_id', 'instance_id', 'attempt_id', 'call_id', 'intent_id', 'store_id'):
        if key in payload:require(type(payload[key]) is str and payload[key], 'journal_schema', 'nonempty exact identity string required: ' + key)
    for key, value in payload.items():
        if key.endswith('_sha256'):
            require(hash_string(value), 'journal_schema', 'exact hash string required: ' + key)
        if key.endswith('_blob'):
            if value is None:
                require(key in NULLABLE_BLOBS, 'blob_reference', 'only explicit nullable blob fields permit null')
                continue
            get_blob(value)
            if key in JSON_BLOBS:
                require(type(get_json(value)) is dict, 'blob_type', 'referenced JSON object required: ' + key)
    if kind == 'action_recorded':
        require(type(payload['processing']) is dict and payload['processing'].get('policy_schema') == envelope_policy.SCHEMA
                and (payload['processing'].get('kind') == 'action' or envelope_policy.is_rejection(payload['processing'].get('kind'))),
                'processing', 'versioned explicit classification required')
        require(type(payload['candidate_blobs']) is list, 'blob_reference', 'candidate reference list required')
        for ref in payload['candidate_blobs']:
            require(type(get_json(ref)) is dict, 'blob_type', 'candidate JSON object required')
    elif kind == 'attempt_reserved':
        spec = get_json(payload['spec_blob'])
        require(set(spec) == {'run_dir', 'config', 'schema_blob'} and type(spec['run_dir']) is str
                and spec['run_dir'] == str(Path(spec['run_dir']).resolve()), 'run_dir', 'exact normalized original transport directory required')
        require(type(spec['config']) is dict and {'model', 'reasoning_effort', 'timeout_seconds', 'phase', 'grant_id'} <= set(spec['config']),
                'config', 'original explicit transport config required')
        schema_raw = get_blob(spec['schema_blob']);schema = decode(schema_raw)
        require(type(schema) is dict and schema_raw == (json.dumps(schema, ensure_ascii=False, indent=2) + '\n').encode(),
                'schema_bytes', 'nested original schema reference/serialization differs')
    elif kind == 'write_rejected':
        require(type(payload['operation']) is str and payload['operation'] and type(payload['args']) is dict
                and type(payload['original_blob_refs']) is dict and type(payload['error']) is dict
                and set(payload['error']) == {'code', 'type', 'detail'}
                and all(type(value) is str for value in payload['error'].values()), 'journal_schema', 'rejection evidence fields differ')
        for name, ref in payload['original_blob_refs'].items():
            require(type(name) is str, 'blob_reference', 'original rejected input name must be a string')
            get_blob(ref)


def fold(rows, get_json, get_blob):
    state = _new_state()
    for sequence, kind, payload_text, previous, event_sha in rows:
        payload = decode(payload_text.encode())
        verify_event_closure(kind, payload, get_json, get_blob)
        require(sequence != 0 or kind == 'store_created', 'store', 'first event must create this store')
        require(type(sequence) is int and sequence == state['records'] and previous == state['tail'], 'journal_chain', 'noncontiguous or rewritten journal')
        event = {'sequence': sequence, 'kind': kind, 'payload': payload, 'previous_sha256': previous}
        require(event_sha == digest(event), 'journal_hash', 'event hash mismatch')
        if kind == 'store_created':
            require(sequence == 0 and payload['schema'] == SCHEMA, 'store', 'invalid initial store event')
            state['store_id'], state['runtime'] = payload['store_id'], payload['runtime']
        elif kind == 'write_rejected':
            state['rejections'].append(payload)
        elif kind == 'session_created':
            sid, iid = payload['interaction_id'], payload['instance_id']
            require(sid not in state['sessions'] and iid not in state['instances'], 'session', 'duplicate logical session/instance')
            state['sessions'][sid] = {'bootstrap_blob': payload['bootstrap_blob'], 'attempt_ids': [], 'selection_blob': None,
                                      'intent': None, 'receipt': None, 'candidate_blobs': []}
            state['instances'][iid] = sid
        elif kind == 'instance_attached':
            require(payload['instance_id'] not in state['instances'] and payload['interaction_id'] in state['sessions'], 'instance', 'duplicate or unknown instance')
            state['instances'][payload['instance_id']] = payload['interaction_id']
        elif kind == 'attempt_reserved':
            sid, aid = payload['interaction_id'], payload['attempt_id']
            require(state['instances'].get(payload['instance_id']) == sid and aid not in state['attempts'], 'attempt', 'unknown owner/duplicate attempt')
            session = state['sessions'][sid]
            previous_attempts = [state['attempts'][key] for key in session['attempt_ids']]
            require(session['selection_blob'] is None and session['intent'] is None, 'selected', 'selected session cannot reserve another model attempt')
            require(all(a.get('action') is not None for a in previous_attempts), 'pending', 'unprocessed/failed/pending attempt blocks later calls')
            index = payload['model_index']
            require(type(index) is int and index >= 0 and all(index > a['model_index'] for a in previous_attempts), 'model_index', 'index must advance across every instance')
            run_dir = get_json(payload['spec_blob'])['run_dir']
            require(run_dir not in state['run_dirs'], 'run_dir', 'transport directory reused across stored sessions, including pending attempts')
            state['run_dirs'].add(run_dir)
            state['attempts'][aid] = {**payload, 'request': None, 'completion': None, 'action': None}
            session['attempt_ids'].append(aid)
        elif kind == 'transport_requested':
            attempt = state['attempts'][payload['attempt_id']]
            require(attempt['request'] is None and payload['call_id'] not in state['call_ids'], 'call_id', 'transport call reused across instances/sessions')
            original_call_id = verify_request(attempt, get_json(payload['request_blob']), get_json(payload['reserve_blob']),
                get_blob(payload['claim_blob']), get_blob(payload['prompt_file_blob']), get_blob(payload['schema_file_blob']), get_json, get_blob)
            require(payload['call_id'] == original_call_id, 'transport_binding', 'journal call ID differs from original request/reserve')
            state['call_ids'].add(payload['call_id']);attempt['request'] = payload
        elif kind == 'transport_completed':
            attempt = state['attempts'][payload['attempt_id']]
            require(attempt['request'] is not None and attempt['completion'] is None, 'completion', 'unreserved/duplicate completion')
            attempt['completion'] = payload
        elif kind == 'action_recorded':
            attempt = state['attempts'][payload['attempt_id']]
            require(attempt['completion'] is not None and attempt['action'] is None, 'action', 'completed output required exactly once')
            attempt['action'] = payload
            session = state['sessions'][attempt['interaction_id']]
            session['candidate_blobs'].extend(payload['candidate_blobs'])
            if payload['selection_blob'] is not None:
                require(session['selection_blob'] is None, 'selection', 'logical selection already claimed')
                session['selection_blob'] = payload['selection_blob']
        elif kind == 'external_commit_intent':
            session = state['sessions'][payload['interaction_id']]
            require(state['instances'].get(payload['instance_id']) == payload['interaction_id'], 'commit_owner', 'intent instance differs from logical owner')
            require(session['selection_blob'] is not None and session['intent'] is None, 'commit_intent', 'one selected logical session permits only one intent')
            require(all(s['intent'] is None or s['intent']['intent_id'] != payload['intent_id'] for s in state['sessions'].values()), 'commit_intent', 'intent ID reused')
            session['intent'] = payload
        elif kind == 'external_commit_receipt':
            session = state['sessions'][payload['interaction_id']]
            require(state['instances'].get(payload['instance_id']) == payload['interaction_id']
                    and payload['reported_outcome'] in ('accepted', 'rejected', 'unknown'), 'commit_owner', 'receipt owner/outcome invalid')
            require(session['intent'] is not None and session['receipt'] is None and payload['intent_id'] == session['intent']['intent_id'], 'commit_receipt', 'one immutable receipt requires its original intent')
            session['receipt'] = payload
        else:
            raise StoreError('journal_kind', 'unknown journal event')
        state['tail'], state['records'] = event_sha, sequence + 1
    require(state['store_id'] is not None, 'store', 'missing store registration')
    return state


def verify_request(attempt, request, reserve, claim, prompt_raw, schema_raw, get_json, get_blob):
    spec = get_json(attempt['spec_blob']);prompt = get_json(attempt['prompt_blob'])
    expected = expected_fingerprint(prompt['prompt'], get_blob(spec['schema_blob']), spec['config'])
    require(prompt_raw == prompt['prompt'].encode() and schema_raw == get_blob(spec['schema_blob']),
            'transport_binding', 'actual original prompt.txt/schema.json differ from the durable reservation')
    call_id = request.get('call_id')
    require(type(call_id) is str and call_id and reserve.get('call_id') == call_id, 'transport_binding', 'original request/reserve call ID mismatch')
    require(request.get('request_fingerprint') == expected and same(request.get('config'), spec['config'])
            and claim == (expected + '\n').encode(), 'transport_binding', 'request config/fingerprint/claim differs from reserved exact prompt/schema')
    config = spec['config']
    metadata = {'request_fingerprint': expected, 'model': config['model'], 'timeout_seconds': config['timeout_seconds'],
                'reasoning_effort': config['reasoning_effort'], 'prompt_characters': len(prompt['prompt']), 'prompt_character_limit': 120000,
                'authorization_context': config.get('authorization_context')}
    require(reserve.get('event') == 'reserve' and reserve.get('run_id') == spec['run_dir']
            and reserve.get('phase') == config['phase'] and reserve.get('grant_id') == config['grant_id']
            and same(reserve.get('metadata'), metadata), 'ledger_binding', 'supplied original budget reserve metadata differs')
    require(type(request.get('started_at')) is str and request['started_at'], 'transport_binding', 'original request start timestamp required')
    return call_id


def event_summary(events_raw):
    events, malformed = [], []
    for line in events_raw.decode('utf-8', errors='replace').splitlines():
        if not line.strip():continue
        try:events.append(json.loads(line))
        except json.JSONDecodeError:malformed.append(line)
    require(all(type(e) is dict for e in events), 'events', 'original event entries must be objects')
    completed = [e for e in events if e.get('type') == 'turn.completed']
    usages = [e.get('usage') for e in completed if type(e.get('usage')) is dict]
    invalid = []
    for index, event in enumerate(completed):
        raw = event.get('usage')
        if raw is not None and type(raw) is not dict:
            invalid.append({'completed_turn': index, 'reason': 'usage must be an object or null'})
        elif type(raw) is dict:
            for key, value in raw.items():
                if value is not None and not (type(value) is int and value >= 0):
                    invalid.append({'completed_turn': index, 'field': key,
                                    'reason': 'counter must be a nonnegative integer or null'})
    usage = {key: sum(u[key] for u in usages) if usages and len(usages) == len(completed)
             and all(type(u.get(key)) is int and u[key] >= 0 for u in usages) else None
             for key in ('input_tokens', 'cached_input_tokens', 'output_tokens', 'cache_write_input_tokens', 'reasoning_output_tokens')}
    native = [e.get('item', {}) for e in events if e.get('type') in ('item.started', 'item.completed', 'item.updated')
              and e.get('item', {}).get('type') not in {'agent_message', 'reasoning', 'error'}]
    result = {'completed_turns': len(completed), 'usage': usage,
              'usage_status': 'invalid' if invalid else 'reported' if usages else 'unknown',
              'native_tool_events': native, 'thread_ids': [e['thread_id'] for e in events if e.get('type') == 'thread.started' and 'thread_id' in e],
              'errors': [e for e in events if e.get('type') in {'error', 'turn.failed'}], 'malformed_event_lines': malformed}
    # Match the current transport's derived diagnostic, without rewriting any
    # raw event/result/ledger bytes. Valid historical summaries keep their shape.
    if invalid:result['usage_validation_errors'] = invalid
    return result


def verify_completion(attempt, result, finish, final_raw, events_raw, get_json):
    request = get_json(attempt['request']['request_blob']);spec = get_json(attempt['spec_blob'])
    require(result.get('call_id') == request['call_id'] and result.get('request_fingerprint') == request['request_fingerprint']
            and same(result.get('config'), request['config']) and result.get('started_at') == request['started_at'],
            'transport_binding', 'completion/request identity differs')
    require(result.get('status') in ('success', 'failed', 'timeout') and type(result.get('finished_at')) is str,
            'transport_terminal', 'explicit terminal result required; pending is not a result')
    began, ended = dt.datetime.fromisoformat(result['started_at']), dt.datetime.fromisoformat(result['finished_at'])
    duration = result.get('duration_seconds')
    require(began.tzinfo is not None and ended.tzinfo is not None and ended >= began
            and type(duration) in (int, float) and math.isfinite(duration) and duration >= 0
            and same(duration, result.get('model_elapsed_seconds')) and same(result.get('model_calls'), 1)
            and same(result.get('automatic_retries'), 0) and result.get('cost_usd') is None
            and type(result.get('timed_out')) is bool
            and (result.get('returncode') is None or type(result['returncode']) is int)
            and (result.get('launch_error') is None or type(result['launch_error']) is str)
            and (result.get('decode_error') is None or type(result['decode_error']) is str),
            'transport_terminal', 'terminal timestamps/resources inconsistent')
    summary = event_summary(events_raw)
    require(all(same(result.get(key), value) for key, value in summary.items()), 'events', 'original event evidence differs from terminal summary/usage')
    require(('usage_validation_errors' in result) == ('usage_validation_errors' in summary),
            'events', 'usage diagnostic presence differs from original event evidence')
    # Invalid usage does not erase a higher-precedence transport failure.
    if result['timed_out']:
        status, failure = 'timeout', 'model_call_timeout'
    elif result.get('launch_error'):
        status, failure = 'failed', 'model_launch_error'
    elif summary['native_tool_events']:
        status, failure = 'failed', 'native_tool_isolation_violation'
    elif summary['malformed_event_lines']:
        status, failure = 'failed', 'malformed_event_log'
    elif summary.get('usage_validation_errors'):
        status, failure = 'failed', 'invalid_usage_evidence'
    elif result.get('returncode') != 0 or summary['completed_turns'] != 1:
        status, failure = 'failed', 'model_transport_error'
    elif result.get('decode_error'):
        status, failure = 'failed', 'invalid_model_json'
    else:
        status, failure = 'success', None
    require(result['status'] == status and result.get('failure_reason') == failure,
            'transport_terminal', 'completion status contradicts original evidence and failure precedence')
    details = {'result_path': spec['run_dir'] + '/result.json', 'failure_reason': result['failure_reason'],
               'usage': result['usage'], 'duration_seconds': result['duration_seconds'],
               'cost_usd': result['cost_usd'], 'completed_turns': result['completed_turns']}
    require(finish.get('event') == 'finish' and finish.get('call_id') == request['call_id'] and finish.get('status') == result['status']
            and same(finish.get('details'), details), 'ledger_binding', 'original finish missing or inconsistent; adapter never fabricates budget finish')
    if result['status'] == 'success':
        require(final_raw is not None and same(json.loads(final_raw.decode('utf-8')), result.get('output')),
                'output_binding', 'original final.txt bytes do not decode to original transport result output')
        require(type(result.get('returncode')) is int and result['returncode'] == 0 and result.get('timed_out') is False
                and result.get('launch_error') is None and type(result.get('completed_turns')) is int and result['completed_turns'] == 1
                and result.get('native_tool_events') == [] and result.get('malformed_event_lines') == []
                and result.get('decode_error') is None, 'transport_terminal', 'success conflicts with terminal/isolation fields')


def classify_processing(attempt, model, get_json, get_blob):
    """Pure structural eligibility only; bridge separately binds original authority."""
    completion = attempt['completion']
    raw = get_blob(completion['final_blob'])
    prompt = get_json(attempt['prompt_blob'])['prompt']
    spec = get_json(attempt['spec_blob'])
    return envelope_policy.classify(decode(raw), prompt, model.context(), get_json(spec['schema_blob']))


def replay_session(sid, state, get_json, get_blob):
    session = state['sessions'][sid]
    model = fresh_session(get_json(session['bootstrap_blob']))
    require(model.context()['interaction_id'] == sid, 'bootstrap', 'logical identity differs from bootstrap')
    generated_candidates = []
    for aid in session['attempt_ids']:
        attempt = state['attempts'][aid]
        prompt = model.next_prompt()
        require(same(prompt, get_json(attempt['prompt_blob'])), 'prompt_replay', 'exact regenerated prompt/body/full hash differs')
        require(sha(prompt['prompt'].encode()) == attempt['full_prompt_sha256']
                and prompt['prompt_body_sha256'] == attempt['body_sha256'], 'prompt_replay', 'body/full prompt binding differs')
        if attempt['request'] is None:
            require(attempt['completion'] is None and attempt['action'] is None, 'pending', 'request missing before completion/action')
            break
        req = attempt['request']
        original_call_id = verify_request(attempt, get_json(req['request_blob']), get_json(req['reserve_blob']), get_blob(req['claim_blob']),
                       get_blob(req['prompt_file_blob']), get_blob(req['schema_file_blob']), get_json, get_blob)
        require(req['call_id'] == original_call_id, 'transport_binding', 'journal call ID differs from original request/reserve')
        if attempt['completion'] is None:
            require(attempt['action'] is None, 'pending', 'completion missing before action')
            break
        done = attempt['completion'];final = get_blob(done['final_blob']) if done['final_blob'] is not None else None
        verify_completion(attempt, get_json(done['result_blob']), get_json(done['finish_blob']), final, get_blob(done['events_blob']), get_json)
        if attempt['action'] is None:
            break  # A completed-but-unmapped output is preserved, never automatically handled during recovery.
        require(get_json(done['result_blob'])['status'] == 'success', 'transport_failed', 'failed transport must not execute interaction action')
        processing = classify_processing(attempt, model, get_json, get_blob)
        require(same(processing, attempt['action']['processing']), 'processing_replay', 'original envelope classification differs')
        before_evidence = model.export_evidence();before = len(before_evidence['candidates'])
        response = model.handle(final, call_id=req['call_id'], model_index=attempt['model_index'])
        evidence = model.export_evidence();record = evidence['history'][-1];action = attempt['action']
        if envelope_policy.is_rejection(processing['kind']):
            envelope_policy.verify_rejection_effects(before_evidence, evidence, response, kind=processing['kind'])
        require(same(record, get_json(action['record_blob'])) and response['record_sha256'] == action['record_sha256'], 'action_replay', 'raw-output pure replay differs from stored response/history')
        new = evidence['candidates'][before:]
        require(len(new) == len(action['candidate_blobs']) and all(same(c, get_json(ref)) for c, ref in zip(new, action['candidate_blobs'])),
                'candidate_replay', 'stored candidate differs from original-output compiler replay')
        generated_candidates.extend(action['candidate_blobs'])
        selection = evidence['selection']
        require((selection is None and action['selection_blob'] is None) or
                (selection is not None and action['selection_blob'] is not None and same(selection, get_json(action['selection_blob']))),
                'selection_replay', 'stored selection differs from original later apply')
    require(generated_candidates == session['candidate_blobs'], 'candidate_replay', 'orphan/missing candidate source')
    final = model.export_evidence()['selection']
    require((final is None and session['selection_blob'] is None) or
            (final is not None and same(final, get_json(session['selection_blob']))), 'selection_replay', 'logical selection claim differs')
    intent = session['intent']
    if intent is not None:
        require(final is not None and intent['selection_sha256'] == digest(final)
                and intent['plan_sha256'] == digest(final['candidate']['compiled']['plan'])
                and same(intent['current_anchors'], model.context()['anchors']), 'commit_binding', 'intent selection/plan/current anchor differs')
    return model


class DurableInteractionStore:
    def __init__(self, directory):
        self.directory = Path(directory).absolute();self.path = self.directory / 'ledger.sqlite3'

    @classmethod
    def create(cls, directory, *, store_id):
        require(type(store_id) is str and store_id, 'store_id', 'explicit registration ID required')
        store = cls(directory);store.directory.mkdir(parents=False, exist_ok=False)
        descriptor = os.open(store.directory / 'store.lock', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600);os.close(descriptor)
        with closing(sqlite3.connect(store.path)) as db:
            db.execute('PRAGMA journal_mode=DELETE');db.execute('PRAGMA synchronous=FULL')
            db.executescript('CREATE TABLE journal(sequence INTEGER PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,previous_sha256 TEXT,event_sha256 TEXT NOT NULL);'
                             'CREATE TABLE blobs(sha256 TEXT PRIMARY KEY,data BLOB NOT NULL);')
            for table in ('journal', 'blobs'):
                for action in ('UPDATE', 'DELETE'):
                    db.execute('CREATE TRIGGER no_' + action.lower() + '_' + table + ' BEFORE ' + action + ' ON ' + table + " BEGIN SELECT RAISE(ABORT,'immutable'); END")
            store._append(db, 'store_created', {'schema': SCHEMA, 'store_id': store_id, 'runtime': runtime_manifest()}, 0, None)
            db.commit()
        store._sync()
        return store

    def _sync(self):
        fd = os.open(self.directory, os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)

    def _ready(self):
        require(self.path.is_file() and not self.path.is_symlink(), 'storage', 'regular database required')
        require(self.path.stat().st_size <= MAX_DATABASE_BYTES, 'storage_limit', 'database cap exceeded; retain evidence')
        require(not any(Path(str(self.path) + suffix).exists() for suffix in ('-journal', '-wal', '-shm')),
                'storage_unresolved', 'SQLite sidecar requires external diagnosis; no automatic rollback/checkpoint')

    @contextmanager
    def _lock(self, exclusive):
        fd = os.open(self.directory / 'store.lock', os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        try:
            fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH);yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN);os.close(fd)

    @staticmethod
    def _append(db, kind, payload, sequence, previous):
        event = {'sequence': sequence, 'kind': kind, 'payload': payload, 'previous_sha256': previous};hashed = digest(event)
        db.execute('INSERT INTO journal VALUES(?,?,?,?,?)', (sequence, kind, encode(payload).decode(), previous, hashed))
        return hashed

    @staticmethod
    def _put(db, data):
        require(type(data) is bytes and len(data) <= MAX_BLOB_BYTES, 'blob_limit', 'immutable raw blob requires bytes within cap')
        hashed = sha(data);old = db.execute('SELECT data FROM blobs WHERE sha256=?', (hashed,)).fetchone()
        if old is not None:
            require(old[0] == data, 'blob_hash', 'existing blob was changed')
        else:
            db.execute('INSERT INTO blobs VALUES(?,?)', (hashed, data))
        return hashed

    @staticmethod
    def _load(db):
        blobs = dict(db.execute('SELECT sha256,data FROM blobs'))
        require(all(hash_string(hashed) and type(data) is bytes and len(data) <= MAX_BLOB_BYTES
                    and sha(data) == hashed for hashed, data in blobs.items()), 'blob_hash', 'stored immutable blob type/hash/size was changed')
        def get_blob(ref):
            require(hash_string(ref) and ref in blobs, 'blob_reference', 'referenced original blob missing or invalid')
            return blobs[ref]
        get_json = lambda ref: decode(get_blob(ref))
        rows = db.execute('SELECT sequence,kind,payload,previous_sha256,event_sha256 FROM journal ORDER BY sequence').fetchall()
        state = fold(rows, get_json, get_blob)
        require(same(state['runtime'], runtime_manifest()), 'runtime', 'pure replay source bytes differ from stored runtime manifest')
        return state, get_json, get_blob

    def _t(self, stage, reason, function, *args, **kwargs):
        return timing.call(getattr(self, '_timing', None), stage, reason, function, *args, **kwargs)

    def _replay_for_handler(self, sid, state, get_json, get_blob):
        return replay_session(sid, state, get_json, get_blob)

    def _write(self, operation, args, parts, handler):
        encode(args)
        # Oversize/non-byte host input is outside admission; no partial data is discarded from the store.
        require(all(type(raw) is bytes and len(raw) <= MAX_BLOB_BYTES for raw in parts.values()), 'blob_limit', 'input blob admission failed')
        with self._lock(True):
            self._ready();before = identity(os.stat(self.path, follow_symlinks=False))
            with closing(sqlite3.connect(self.path, timeout=5)) as db:
                db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
                try:
                    state, get_json, get_blob = self._load(db)
                    require(state['records'] < MAX_EVENTS, 'event_limit', 'event cap exhausted; do not evict/restart')
                    refs = {key: self._put(db, value) for key, value in parts.items()}
                    try:
                        kind, payload, value = handler(db, state, get_json, get_blob, refs)
                        accepted, error = True, None
                    except (ValueError, KeyError, TypeError, IndexError) as exc:
                        accepted, kind, value = False, 'write_rejected', None
                        error = {'code': getattr(exc, 'code', 'malformed_input'), 'type': type(exc).__name__, 'detail': str(exc)}
                        payload = {'operation': operation, 'args': args, 'original_blob_refs': refs, 'error': error}
                    tail = self._append(db, kind, payload, state['records'], state['tail'])
                    require(os.stat(self.path, follow_symlinks=False).st_ino == before[1], 'storage_changed', 'database path changed while writing')
                    db.commit()
                except BaseException:
                    db.rollback();raise
            self._sync()
            require((os.stat(self.path, follow_symlinks=False).st_dev, os.stat(self.path, follow_symlinks=False).st_ino) == before[:2],
                    'storage_changed', 'database path replaced during transaction finalization; outcome requires diagnosis')
        return {'accepted': accepted, 'accepted_scope': 'durable structure and explicitly performed pure interaction calculation only',
                'value': deepcopy(value), 'error': error, 'journal_tail_sha256': tail, 'journal_records': state['records'] + 1, **FLAGS}

    @staticmethod
    def _owner(state, instance_id):
        require(type(instance_id) is str and instance_id in state['instances'], 'instance', 'registered instance required')
        return state['instances'][instance_id]

    @staticmethod
    def _attempt(state, instance_id, attempt_id):
        sid = DurableInteractionStore._owner(state, instance_id)
        require(attempt_id in state['attempts'] and state['attempts'][attempt_id]['interaction_id'] == sid, 'attempt', 'attempt belongs to another logical session')
        return state['attempts'][attempt_id]

    def register(self, instance_id, bootstrap):
        bootstrap = decode(encode(bootstrap))
        def run(db, state, gj, gb, refs):
            require(type(instance_id) is str and instance_id and instance_id not in state['instances'], 'instance', 'new explicit instance required')
            model = fresh_session(bootstrap);sid = model.context()['interaction_id']
            require(sid not in state['sessions'], 'session_exists', 'same bootstrap cannot create a fresh empty history; attach and replay original session')
            payload = {'instance_id': instance_id, 'interaction_id': sid, 'bootstrap_blob': refs['bootstrap']}
            return 'session_created', payload, model.context()
        return self._write('register', {'instance_id': instance_id}, {'bootstrap': encode(bootstrap)}, run)

    def attach(self, instance_id, interaction_id):
        def run(db, state, gj, gb, refs):
            require(type(instance_id) is str and instance_id and instance_id not in state['instances'] and interaction_id in state['sessions'], 'instance', 'new instance of existing session required')
            model = self._replay_for_handler(interaction_id, state, gj, gb)
            return 'instance_attached', {'instance_id': instance_id, 'interaction_id': interaction_id}, {'context': model.context(), 'pure_replay_verified': True, 'no_pending_action_executed': True}
        return self._write('attach', {'instance_id': instance_id, 'interaction_id': interaction_id}, {}, run)

    def reserve_attempt(self, instance_id, *, attempt_id, model_index, run_dir, config, schema_bytes):
        config = decode(encode(config))
        def run(db, state, gj, gb, refs):
            sid = self._owner(state, instance_id);session = state['sessions'][sid]
            require(type(attempt_id) is str and attempt_id and attempt_id not in state['attempts'], 'attempt_id', 'new durable attempt ID required')
            require(type(model_index) is int and model_index >= 0, 'model_index', 'exact nonnegative integer index required')
            require(session['selection_blob'] is None, 'selected', 'selection closes model admission')
            prior = [state['attempts'][a] for a in session['attempt_ids']]
            require(all(a['action'] is not None for a in prior), 'pending', 'unresolved transport/action prevents another request')
            require(all(model_index > a['model_index'] for a in prior), 'model_index', 'index cannot be reused by another instance')
            require(type(run_dir) is str and run_dir == str(Path(run_dir).resolve()), 'run_dir', 'absolute normalized transport run directory required')
            require(all(gj(a['spec_blob'])['run_dir'] != run_dir for a in state['attempts'].values()), 'run_dir', 'transport directory already reserved')
            require(type(config) is dict and {'model', 'reasoning_effort', 'timeout_seconds', 'phase', 'grant_id'} <= set(config), 'config', 'explicit transport config required')
            schema = decode(schema_bytes)
            require(schema_bytes == (json.dumps(schema, ensure_ascii=False, indent=2) + '\n').encode(), 'schema_bytes', 'exact existing transport schema serialization required')
            model = self._replay_for_handler(sid, state, gj, gb);prompt = self._t('prompt', 'reserve_exact_next_prompt', model.next_prompt)
            spec = {'run_dir': run_dir, 'config': deepcopy(config), 'schema_blob': refs['schema']}
            payload = {'instance_id': instance_id, 'interaction_id': sid, 'attempt_id': attempt_id, 'model_index': model_index,
                       'prompt_blob': self._put(db, encode(prompt)), 'spec_blob': self._put(db, encode(spec)),
                       'full_prompt_sha256': prompt['prompt_sha256'], 'body_sha256': prompt['prompt_body_sha256']}
            return 'attempt_reserved', payload, {'attempt_id': attempt_id, 'prompt': prompt, 'request_fingerprint': expected_fingerprint(prompt['prompt'], schema_bytes, config),
                                                'budget_reservation_performed': False, 'transport_call_performed': False}
        return self._write('reserve_attempt', {'instance_id': instance_id, 'attempt_id': attempt_id, 'model_index': model_index,
                                             'run_dir': run_dir, 'config': config}, {'schema': schema_bytes}, run)

    def bind_transport_request(self, instance_id, *, attempt_id, request_bytes, reserve_bytes, claim_bytes, prompt_bytes, schema_bytes):
        def run(db, state, gj, gb, refs):
            attempt = self._attempt(state, instance_id, attempt_id)
            require(attempt['request'] is None, 'request_exists', 'request already bound; never repeat transport')
            cid = verify_request(attempt, decode(request_bytes), decode(reserve_bytes), claim_bytes, prompt_bytes, schema_bytes, gj, gb)
            require(cid not in state['call_ids'], 'call_id', 'call ID already bound anywhere in store')
            payload = {'attempt_id': attempt_id, 'call_id': cid, 'request_blob': refs['request'], 'reserve_blob': refs['reserve'], 'claim_blob': refs['claim'],
                       'prompt_file_blob': refs['prompt'], 'schema_file_blob': refs['schema']}
            return 'transport_requested', payload, {'call_id': cid, 'artifact_consistency_verified': True, **FLAGS}
        return self._write('bind_transport_request', {'instance_id': instance_id, 'attempt_id': attempt_id},
                           {'request': request_bytes, 'reserve': reserve_bytes, 'claim': claim_bytes, 'prompt': prompt_bytes, 'schema': schema_bytes}, run)

    def bind_transport_completion(self, instance_id, *, attempt_id, result_bytes, finish_bytes, events_bytes, final_bytes):
        parts = {'result': result_bytes, 'finish': finish_bytes, 'events': events_bytes}
        if final_bytes is not None:parts['final'] = final_bytes
        def run(db, state, gj, gb, refs):
            attempt = self._attempt(state, instance_id, attempt_id)
            require(attempt['request'] is not None and attempt['completion'] is None, 'completion', 'original request must precede unique terminal evidence')
            verify_completion(attempt, decode(result_bytes), decode(finish_bytes), final_bytes, events_bytes, gj)
            payload = {'attempt_id': attempt_id, 'result_blob': refs['result'], 'finish_blob': refs['finish'], 'events_blob': refs['events'], 'final_blob': refs.get('final')}
            return 'transport_completed', payload, {'status': decode(result_bytes)['status'], 'handle_called': False, **FLAGS}
        return self._write('bind_transport_completion', {'instance_id': instance_id, 'attempt_id': attempt_id}, parts, run)

    def process_completed(self, instance_id, *, attempt_id, expected_processing_kind):
        def run(db, state, gj, gb, refs):
            attempt = self._attempt(state, instance_id, attempt_id)
            require(attempt['completion'] is not None and attempt['action'] is None, 'action', 'only one explicit processing of a complete original output is allowed')
            require(gj(attempt['completion']['result_blob'])['status'] == 'success', 'transport_failed', 'failed/timeout call is retained, never executed or silently retried')
            model = self._replay_for_handler(attempt['interaction_id'], state, gj, gb)
            processing = self._t('validation', 'classify_original_envelope', classify_processing, attempt, model, gj, gb)
            require(expected_processing_kind == processing['kind'], 'processing', 'explicit processing mode differs from original output')
            before_evidence = model.export_evidence();before = len(before_evidence['candidates'])
            response = self._t('replay', 'explicit_new_raw_action_handler', model.handle, gb(attempt['completion']['final_blob']), call_id=attempt['request']['call_id'], model_index=attempt['model_index'])
            evidence = model.export_evidence();record = evidence['history'][-1]
            if envelope_policy.is_rejection(processing['kind']):
                envelope_policy.verify_rejection_effects(before_evidence, evidence, response, kind=processing['kind'])
            candidates = [self._put(db, encode(c)) for c in evidence['candidates'][before:]]
            selection = None if evidence['selection'] is None else self._put(db, encode(evidence['selection']))
            payload = {'attempt_id': attempt_id, 'record_blob': self._put(db, encode(record)), 'record_sha256': record['record_sha256'],
                       'candidate_blobs': candidates, 'selection_blob': selection, 'processing': processing}
            return 'action_recorded', payload, {'response': response, 'processing': processing, 'pure_replay_verified': True, 'selection_recorded': selection is not None, **FLAGS}
        return self._write('process_completed', {'instance_id': instance_id, 'attempt_id': attempt_id,
                           'expected_processing_kind': expected_processing_kind}, {}, run)

    def record_commit_intent(self, instance_id, *, intent_id, selection_sha256, plan_sha256, current_anchors, external_validation_reference):
        current_anchors = decode(encode(current_anchors))
        external_validation_reference = decode(encode(external_validation_reference))
        def run(db, state, gj, gb, refs):
            sid = self._owner(state, instance_id);session = state['sessions'][sid]
            require(type(intent_id) is str and intent_id and session['selection_blob'] is not None and session['intent'] is None, 'commit_intent', 'explicit selection permits one intent; unknown outcome cannot be retried')
            require(all(s['intent'] is None or s['intent']['intent_id'] != intent_id for s in state['sessions'].values()), 'commit_intent', 'intent ID reused')
            selection = self._replay_for_handler(sid, state, gj, gb).export_evidence()['selection']
            require(selection_sha256 == digest(selection) and plan_sha256 == digest(selection['candidate']['compiled']['plan'])
                    and same(current_anchors, selection['anchors']), 'commit_binding', 'explicit current anchors/selection/plan differ')
            payload = {'instance_id': instance_id, 'interaction_id': sid, 'intent_id': intent_id, 'selection_sha256': selection_sha256,
                       'plan_sha256': plan_sha256, 'current_anchors': current_anchors, 'unverified_external_reference': external_validation_reference}
            return 'external_commit_intent', payload, {'intent_recorded_only': True, 'not_a_commit_authorization': True, **FLAGS}
        args = dict(instance_id=instance_id, intent_id=intent_id, selection_sha256=selection_sha256, plan_sha256=plan_sha256,
                    current_anchors=current_anchors, external_validation_reference=external_validation_reference)
        return self._write('record_commit_intent', args, {}, run)

    def record_commit_receipt(self, instance_id, *, intent_id, reported_outcome, receipt_bytes, external_reference):
        external_reference = decode(encode(external_reference))
        def run(db, state, gj, gb, refs):
            sid = self._owner(state, instance_id);session = state['sessions'][sid]
            require(session['intent'] is not None and session['intent']['intent_id'] == intent_id and session['receipt'] is None,
                    'commit_receipt', 'one receipt must bind the original intent')
            require(reported_outcome in ('accepted', 'rejected', 'unknown'), 'commit_receipt', 'explicit reported outcome required')
            payload = {'instance_id': instance_id, 'interaction_id': sid, 'intent_id': intent_id, 'reported_outcome': reported_outcome,
                       'receipt_blob': refs['receipt'], 'unverified_external_reference': external_reference}
            return 'external_commit_receipt', payload, {'receipt_recorded_only': True, **FLAGS}
        return self._write('record_commit_receipt', {'instance_id': instance_id, 'intent_id': intent_id,
                           'reported_outcome': reported_outcome, 'external_reference': external_reference}, {'receipt': receipt_bytes}, run)


def database_snapshot(store):
    fd = os.open(store.path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno());ident = identity(before)
        require(stat.S_ISREG(before.st_mode) and identity(os.stat(store.path, follow_symlinks=False)) == ident, 'storage_changed', 'descriptor/path differ')
        raw = stream.read()
        require(len(raw) == before.st_size and identity(os.fstat(stream.fileno())) == ident
                and identity(os.stat(store.path, follow_symlinks=False)) == ident, 'storage_changed', 'database changed while reading')
    return raw, ident


def recover_read_only(directory, *, expected_store_id=None, expected_prefix=None, include_interaction_evidence=False):
    store = DurableInteractionStore(directory)
    report = {'schema': SCHEMA + '-recovery', 'valid': False, 'errors': [], 'pure_replay_verified': False, **FLAGS}
    try:
        require(type(include_interaction_evidence) is bool, 'export', 'explicit boolean export choice required')
        if include_interaction_evidence:
            require(type(expected_store_id) is str and bool(expected_store_id)
                    and type(expected_prefix) is dict
                    and {'journal_records', 'journal_tail_sha256', 'database_sha256'} <= set(expected_prefix)
                    and hash_string(expected_prefix['journal_tail_sha256']) and hash_string(expected_prefix['database_sha256']),
                    'export', 'complete external store and snapshot anchors required for export')
        with store._lock(False):
            store._ready();raw, ident = database_snapshot(store)
            with closing(sqlite3.connect(':memory:')) as db:
                db.deserialize(raw);db.execute('PRAGMA query_only=ON')
                require(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'storage', 'database integrity check failed')
                state, gj, gb = store._load(db)
                require(expected_store_id is None or expected_store_id == state['store_id'], 'store_id', 'external registration mismatch')
                if expected_prefix is not None:
                    count = expected_prefix['journal_records']
                    require(type(count) is int and 1 <= count <= state['records'], 'prefix', 'external prefix missing')
                    row = db.execute('SELECT event_sha256 FROM journal WHERE sequence=?', (count - 1,)).fetchone()
                    require(row[0] == expected_prefix['journal_tail_sha256'], 'prefix', 'external prefix was changed')
                    if include_interaction_evidence:
                        require(count == state['records'] and expected_prefix['database_sha256'] == sha(raw),
                                'export', 'export requires the exact externally anchored current snapshot')
                sessions, interactions = [], []
                for sid, session in state['sessions'].items():
                    model = replay_session(sid, state, gj, gb)
                    phase = 'idle'
                    pending = None
                    for aid in session['attempt_ids']:
                        a = state['attempts'][aid]
                        if a['action'] is None:
                            pending = aid
                            phase = 'reserved_transport_unknown' if a['request'] is None else 'transport_pending' if a['completion'] is None else 'completed_unprocessed' if gj(a['completion']['result_blob'])['status'] == 'success' else 'failed_transport_preserved'
                    if session['selection_blob'] is not None:phase = 'selection_recorded'
                    if session['intent'] is not None:phase = 'external_commit_outcome_unknown'
                    if session['receipt'] is not None:phase = 'external_receipt_reported_' + session['receipt']['reported_outcome']
                    sessions.append({'interaction_id': sid, 'phase': phase, 'pending_attempt_id': pending,
                                     'pending_transport_run_dir': None if pending is None else gj(state['attempts'][pending]['spec_blob'])['run_dir'],
                                     'pending_call_id': None if pending is None or state['attempts'][pending]['request'] is None else state['attempts'][pending]['request']['call_id'],
                                     'pending_full_prompt_sha256': None if pending is None else state['attempts'][pending]['full_prompt_sha256'],
                                     'pending_body_sha256': None if pending is None else state['attempts'][pending]['body_sha256'],
                                     'action_count': len(model.export_evidence()['history']), 'candidate_count': len(model.export_evidence()['candidates']),
                                     'selection_sha256': None if session['selection_blob'] is None else digest(gj(session['selection_blob'])),
                                     'selection_blob': session['selection_blob'], 'anchors': model.context()['anchors'],
                                     'no_automatic_processing_or_commit': True})
                    if include_interaction_evidence:
                        interactions.append({'interaction_id': sid, 'evidence': model.export_evidence()})
                report.update(valid=True, pure_replay_verified=True, store_id=state['store_id'], journal_records=state['records'],
                              journal_tail_sha256=state['tail'], database_sha256=sha(raw), database_bytes=len(raw),
                              instances=deepcopy(state['instances']), sessions=sessions, rejected_write_count=len(state['rejections']))
            store._ready()
            require(identity(os.stat(store.path, follow_symlinks=False)) == ident, 'storage_changed', 'path changed during snapshot/replay')
            # Do not expose candidates/selection from a snapshot whose final
            # path identity check failed. This is pure historical replay only.
            if include_interaction_evidence:report['interactions'] = interactions
    except Exception as exc:
        report.update(valid=False, pure_replay_verified=False)
        report['errors'].append({'code': getattr(exc, 'code', 'recovery_exception'), 'type': type(exc).__name__, 'detail': str(exc)})
    return report


def export_verified_interaction(directory, *, expected_store_id, expected_prefix):
    """Export existing pure evidence from one exactly externally anchored DB.

    No unprocessed output is handled and no external intent/receipt is replayed.
    On failure the report has valid=False and no interactions field. A valid
    export remains a local consistency proof, never backend or physical proof.
    """
    return recover_read_only(directory, expected_store_id=expected_store_id,
                             expected_prefix=expected_prefix, include_interaction_evidence=True)


# Exact v5 fold body above, with only initialization from a verified state.
def fold_suffix(rows, get_json, get_blob, verified_state):
    state = deepcopy(verified_state)
    for sequence, kind, payload_text, previous, event_sha in rows:
        payload = decode(payload_text.encode())
        verify_event_closure(kind, payload, get_json, get_blob)
        require(sequence != 0 or kind == 'store_created', 'store', 'first event must create this store')
        require(type(sequence) is int and sequence == state['records'] and previous == state['tail'], 'journal_chain', 'noncontiguous or rewritten journal')
        event = {'sequence': sequence, 'kind': kind, 'payload': payload, 'previous_sha256': previous}
        require(event_sha == digest(event), 'journal_hash', 'event hash mismatch')
        if kind == 'store_created':
            require(sequence == 0 and payload['schema'] == SCHEMA, 'store', 'invalid initial store event')
            state['store_id'], state['runtime'] = payload['store_id'], payload['runtime']
        elif kind == 'write_rejected':
            state['rejections'].append(payload)
        elif kind == 'session_created':
            sid, iid = payload['interaction_id'], payload['instance_id']
            require(sid not in state['sessions'] and iid not in state['instances'], 'session', 'duplicate logical session/instance')
            state['sessions'][sid] = {'bootstrap_blob': payload['bootstrap_blob'], 'attempt_ids': [], 'selection_blob': None,
                                      'intent': None, 'receipt': None, 'candidate_blobs': []}
            state['instances'][iid] = sid
        elif kind == 'instance_attached':
            require(payload['instance_id'] not in state['instances'] and payload['interaction_id'] in state['sessions'], 'instance', 'duplicate or unknown instance')
            state['instances'][payload['instance_id']] = payload['interaction_id']
        elif kind == 'attempt_reserved':
            sid, aid = payload['interaction_id'], payload['attempt_id']
            require(state['instances'].get(payload['instance_id']) == sid and aid not in state['attempts'], 'attempt', 'unknown owner/duplicate attempt')
            session = state['sessions'][sid]
            previous_attempts = [state['attempts'][key] for key in session['attempt_ids']]
            require(session['selection_blob'] is None and session['intent'] is None, 'selected', 'selected session cannot reserve another model attempt')
            require(all(a.get('action') is not None for a in previous_attempts), 'pending', 'unprocessed/failed/pending attempt blocks later calls')
            index = payload['model_index']
            require(type(index) is int and index >= 0 and all(index > a['model_index'] for a in previous_attempts), 'model_index', 'index must advance across every instance')
            run_dir = get_json(payload['spec_blob'])['run_dir']
            require(run_dir not in state['run_dirs'], 'run_dir', 'transport directory reused across stored sessions, including pending attempts')
            state['run_dirs'].add(run_dir)
            state['attempts'][aid] = {**payload, 'request': None, 'completion': None, 'action': None}
            session['attempt_ids'].append(aid)
        elif kind == 'transport_requested':
            attempt = state['attempts'][payload['attempt_id']]
            require(attempt['request'] is None and payload['call_id'] not in state['call_ids'], 'call_id', 'transport call reused across instances/sessions')
            original_call_id = verify_request(attempt, get_json(payload['request_blob']), get_json(payload['reserve_blob']),
                get_blob(payload['claim_blob']), get_blob(payload['prompt_file_blob']), get_blob(payload['schema_file_blob']), get_json, get_blob)
            require(payload['call_id'] == original_call_id, 'transport_binding', 'journal call ID differs from original request/reserve')
            state['call_ids'].add(payload['call_id']);attempt['request'] = payload
        elif kind == 'transport_completed':
            attempt = state['attempts'][payload['attempt_id']]
            require(attempt['request'] is not None and attempt['completion'] is None, 'completion', 'unreserved/duplicate completion')
            attempt['completion'] = payload
        elif kind == 'action_recorded':
            attempt = state['attempts'][payload['attempt_id']]
            require(attempt['completion'] is not None and attempt['action'] is None, 'action', 'completed output required exactly once')
            attempt['action'] = payload
            session = state['sessions'][attempt['interaction_id']]
            session['candidate_blobs'].extend(payload['candidate_blobs'])
            if payload['selection_blob'] is not None:
                require(session['selection_blob'] is None, 'selection', 'logical selection already claimed')
                session['selection_blob'] = payload['selection_blob']
        elif kind == 'external_commit_intent':
            session = state['sessions'][payload['interaction_id']]
            require(state['instances'].get(payload['instance_id']) == payload['interaction_id'], 'commit_owner', 'intent instance differs from logical owner')
            require(session['selection_blob'] is not None and session['intent'] is None, 'commit_intent', 'one selected logical session permits only one intent')
            require(all(s['intent'] is None or s['intent']['intent_id'] != payload['intent_id'] for s in state['sessions'].values()), 'commit_intent', 'intent ID reused')
            session['intent'] = payload
        elif kind == 'external_commit_receipt':
            session = state['sessions'][payload['interaction_id']]
            require(state['instances'].get(payload['instance_id']) == payload['interaction_id']
                    and payload['reported_outcome'] in ('accepted', 'rejected', 'unknown'), 'commit_owner', 'receipt owner/outcome invalid')
            require(session['intent'] is not None and session['receipt'] is None and payload['intent_id'] == session['intent']['intent_id'], 'commit_receipt', 'one immutable receipt requires its original intent')
            session['receipt'] = payload
        else:
            raise StoreError('journal_kind', 'unknown journal event')
        state['tail'], state['records'] = event_sha, sequence + 1
    require(state['store_id'] is not None, 'store', 'missing store registration')
    return state



def _blob_readers(blobs):
    def gb(ref):
        require(hash_string(ref) and ref in blobs, 'blob_reference', 'referenced original blob missing or invalid')
        return blobs[ref]
    return lambda ref: decode(gb(ref)), gb


def _state_value(state):
    value = deepcopy(state)
    for name in ('call_ids', 'run_dirs'): value[name] = sorted(value[name])
    return value


def _replay_added_action(model, attempt, gj, gb):
    """Same checks as the original replay loop, for this newly recorded action."""
    done, action = attempt['completion'], attempt['action']
    require(gj(done['result_blob'])['status'] == 'success', 'transport_failed', 'failed transport must not execute interaction action')
    processing = classify_processing(attempt, model, gj, gb)
    require(same(processing, action['processing']), 'processing_replay', 'original envelope classification differs')
    before_evidence = model.export_evidence(); before = len(before_evidence['candidates'])
    response = model.handle(gb(done['final_blob']), call_id=attempt['request']['call_id'], model_index=attempt['model_index'])
    evidence = model.export_evidence(); record = evidence['history'][-1]
    if envelope_policy.is_rejection(processing['kind']):
        envelope_policy.verify_rejection_effects(before_evidence, evidence, response, kind=processing['kind'])
    require(same(record, gj(action['record_blob'])) and response['record_sha256'] == action['record_sha256'],
            'action_replay', 'raw-output pure replay differs from stored response/history')
    new = evidence['candidates'][before:]
    require(len(new) == len(action['candidate_blobs']) and all(same(c, gj(ref)) for c, ref in zip(new, action['candidate_blobs'])),
            'candidate_replay', 'stored candidate differs from original-output compiler replay')
    selection = evidence['selection']
    require((selection is None and action['selection_blob'] is None) or
            (selection is not None and action['selection_blob'] is not None and same(selection, gj(action['selection_blob']))),
            'selection_replay', 'stored selection differs from original later apply')
    return model


class IncrementalStore(DurableInteractionStore):
    """New-schema same-owner cache; never an automatic crash-resume capability.

    Every access still hashes one complete bound DB snapshot and fences source
    bytes. Every write compares ALL original journal and blob bytes, then checks
    the new suffix. Only old JSON folds and old Interaction actions are cached.
    No background model, apply, physical commit or ledger operation is performed.
    """
    def __init__(self, directory):
        super().__init__(directory)
        self._cache = None; self._poison = None; self._owner_pid = os.getpid()
        self._recovered = False; self._created_live = False; self._timing = None
        self._counts = {'full_oracle_passes': 0, 'full_actions_replayed': 0,
                        'incremental_events_folded': 0, 'incremental_actions_replayed': 0,
                        'database_snapshot_bytes_read': 0, 'original_blob_bytes_compared': 0,
                        'original_journal_rows_compared': 0, 'new_blob_bytes_hashed': 0, 'full_events_folded': 0}
        self._reasons = []

    @classmethod
    def create(cls, directory, *, store_id, timing_observer=None):
        # Same DDL/create-new lifetime as reference. This module has a distinct
        # SCHEMA/runtime manifest; legacy v5 stores cannot be adopted.
        if timing_observer is not None: timing_observer.ready()
        store = super().create(directory, store_id=store_id)
        store._timing = timing_observer
        store._created_live = True
        store.verify_full(reason='create_new_bootstrap')
        return store

    def _healthy(self, *, write=False):
        if self._timing is not None:
            try: self._timing.ready()
            except BaseException as exc:
                self._poison = repr(exc); raise
        require(os.getpid() == self._owner_pid, 'owner_pid', 'cache cannot cross fork/process identity')
        require(self._poison is None, 'poisoned', 'unknown transaction/cache state: ' + str(self._poison))
        require(not write or self._created_live and not self._recovered, 'recovery_read_only', 'existing/recovered instance cannot write/retry/process/commit')

    def _snapshot(self):
        raw, ident = self._t('io', 'bound_complete_database_snapshot', database_snapshot, self)
        self._counts['database_snapshot_bytes_read'] += len(raw)
        return raw, ident

    def _fence(self):
        self._healthy(); self._ready(); raw, ident = self._snapshot()
        require(self._cache is not None, 'cache', 'complete reference initialization required')
        require(ident == self._cache['identity'] and sha(raw) == self._cache['database_sha256'],
                'cache_changed', 'original verified DB bytes/identity changed outside this owner; no re-anchor')
        require(same(self._cache['state']['runtime'], self._t('validation', 'exact_runtime_source_manifest', runtime_manifest)), 'runtime', 'pure replay source bytes differ from stored runtime manifest')
        require(identity(os.stat(self.path, follow_symlinks=False)) == ident,
                'storage_changed', 'original database identity changed during final source verification')
        return raw, ident

    @staticmethod
    def _rows(db):
        return db.execute('SELECT sequence,kind,payload,previous_sha256,event_sha256 FROM journal ORDER BY sequence').fetchall()

    def _all_bytes(self, db, prior, *, appended):
        """Compare cached originals byte-for-byte, hash new blobs, reject deletion.

        This is intentionally still linear in bytes. It is not a claim that a
        SQLite immutable trigger alone proves old blobs unchanged.
        """
        blobs = dict(db.execute('SELECT sha256,data FROM blobs')); rows = self._rows(db)
        if prior is not None:
            require(len(rows) == len(prior['rows']) + appended and rows[:len(prior['rows'])] == prior['rows'],
                    'journal_chain', 'original verified journal prefix changed or unexpected append count')
            self._counts['original_journal_rows_compared'] += len(prior['rows'])
            require(prior['blobs'].keys() <= blobs.keys(), 'blob_hash', 'original blob removed')
            if appended == 0:
                require(prior['blobs'].keys() == blobs.keys(), 'blob_hash', 'unrequested blob appeared outside the owner event')
        for key, raw in blobs.items():
            require(hash_string(key) and type(raw) is bytes and len(raw) <= MAX_BLOB_BYTES,
                    'blob_hash', 'stored immutable blob type/hash/size was changed')
            if prior is not None and key in prior['blobs']:
                require(raw == prior['blobs'][key], 'blob_hash', 'original verified blob bytes changed')
                self._counts['original_blob_bytes_compared'] += len(raw)
            else:
                require(sha(raw) == key, 'blob_hash', 'stored immutable blob type/hash/size was changed')
                self._counts['new_blob_bytes_hashed'] += len(raw)
        return rows, blobs

    def _oracle_locked(self, reason, *, require_prior=True):
        self._healthy(); self._ready()
        raw, ident = self._fence() if self._cache is not None and require_prior else self._snapshot()
        with closing(sqlite3.connect(':memory:')) as db:
            db.deserialize(raw); db.execute('PRAGMA query_only=ON')
            require(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'storage', 'database integrity check failed')
            state, gj, gb = self._t('validation', 'full_original_blob_hash_and_journal_fold', self._load, db)  # Original complete fold/blob/source checker.
            models = {sid: self._t('replay', 'full_reference_session', replay_session, sid, state, gj, gb) for sid in state['sessions']}
            rows, blobs = self._t('validation', 'full_original_sql_rows_and_blobs', self._all_bytes, db, None, appended=0)
        self._ready()
        require(identity(os.stat(self.path, follow_symlinks=False)) == ident,
                'storage_changed', 'path changed during snapshot/replay')
        require(same(state['runtime'], self._t('validation', 'exact_runtime_source_manifest', runtime_manifest)), 'runtime', 'source changed during full replay')
        if self._cache is not None:
            require(same(_state_value(state), _state_value(self._cache['state'])), 'cache_parity', 'full fold differs from verified incremental state')
            require(set(models) == set(self._cache['models']) and all(same(model.export_evidence(), self._cache['models'][sid].export_evidence())
                    for sid, model in models.items()), 'cache_parity', 'full interaction replay differs from incremental evidence')
        self._counts['full_oracle_passes'] += 1
        self._counts['full_events_folded'] += state['records']
        self._counts['full_actions_replayed'] += sum(a['action'] is not None for a in state['attempts'].values())
        self._reasons.append({'mode': 'full_reference', 'reason': reason, 'journal_records': state['records']})
        self._cache = {'state': state, 'models': models, 'rows': rows, 'blobs': blobs,
                       'database_sha256': sha(raw), 'database_bytes': len(raw), 'identity': ident}

    def verify_full(self, *, reason):
        require(type(reason) is str and reason, 'reason', 'explicit full-check boundary required')
        try:
            with self._lock(False):
                self._oracle_locked(reason)
                report = self._report(include_evidence=False, mode='full_reference')
                self._fence(); return report
        except BaseException as exc:
            self._poison = repr(exc); raise

    @classmethod
    def recover_existing_read_only(cls, directory, *, expected_store_id, expected_prefix):
        """Crash/new process means complete reference replay, never auto handling.

        The returned object is explicitly permanently read-only. Continuation
        needs a separately reviewed recovery protocol; no reset/attach workaround.
        """
        store = cls(directory); store._recovered = True
        report = store.verify_full(reason='crash_or_new_owner_full_reference')
        require(report['store_id'] == expected_store_id, 'store_id', 'external registration mismatch')
        try:
            with store._lock(False):
                store._prefix(expected_prefix, exact=False)
                store._fence()
        except BaseException as exc:
            store._poison = repr(exc); raise
        return store, report

    def _replay_for_handler(self, sid, state, gj, gb):
        require(self._cache is not None and sid in self._cache['models'], 'cache', 'registered full-verified session required')
        # Handlers may issue a prompt or mutate an action. A rejected operation
        # must not alter the committed cache. This copy remains a RAM cost.
        return self._t('other', 'copy_verified_interaction_for_handler', deepcopy, self._cache['models'][sid])

    def _advance(self, rows, blobs):
        old = self._cache; gj, gb = _blob_readers(blobs)
        suffix = rows[len(old['rows']):]
        state = self._t('replay', 'new_journal_suffix_fold', fold_suffix, suffix, gj, gb, old['state'])
        require(same(state['runtime'], self._t('validation', 'exact_runtime_source_manifest', runtime_manifest)), 'runtime', 'source differs at incremental fold')
        models = dict(old['models'])
        for _, kind, payload_text, _, _ in suffix:
            payload = decode(payload_text.encode())
            if kind == 'session_created':
                sid = payload['interaction_id']; model = fresh_session(gj(payload['bootstrap_blob']))
                require(model.context()['interaction_id'] == sid, 'bootstrap', 'logical identity differs from bootstrap')
                models[sid] = model
            elif kind in ('attempt_reserved', 'transport_completed', 'action_recorded'):
                attempt = state['attempts'][payload['attempt_id']]; sid = attempt['interaction_id']
                model = deepcopy(models[sid])
                if kind == 'attempt_reserved':
                    prompt = self._t('prompt', 'verify_reserved_next_prompt', model.next_prompt)
                    require(same(prompt, gj(attempt['prompt_blob'])), 'prompt_replay', 'exact regenerated prompt/body/full hash differs')
                    require(sha(prompt['prompt'].encode()) == attempt['full_prompt_sha256']
                            and prompt['prompt_body_sha256'] == attempt['body_sha256'], 'prompt_replay', 'body/full prompt binding differs')
                elif kind == 'transport_completed':
                    done = attempt['completion']; final = None if done['final_blob'] is None else gb(done['final_blob'])
                    self._t('validation', 'verify_new_completion', verify_completion, attempt, gj(done['result_blob']), gj(done['finish_blob']), final, gb(done['events_blob']), gj)
                else:
                    model = self._t('replay', 'verify_new_original_action', _replay_added_action, model, attempt, gj, gb)
                    self._counts['incremental_actions_replayed'] += 1
                models[sid] = model
            elif kind == 'external_commit_intent':
                model = models[payload['interaction_id']]; selection = model.export_evidence()['selection']
                require(selection is not None and payload['selection_sha256'] == digest(selection)
                        and payload['plan_sha256'] == digest(selection['candidate']['compiled']['plan'])
                        and same(payload['current_anchors'], model.context()['anchors']), 'commit_binding', 'intent selection/plan/current anchor differs')
            self._counts['incremental_events_folded'] += 1
        # Only append-only suffixes were folded; complete structural indexes
        # (including all call IDs/run directories/intents) remain in state.
        return {'state': state, 'models': models, 'rows': rows, 'blobs': blobs}

    def _write(self, operation, args, parts, handler):
        self._healthy(write=True); encode(args)
        require(all(type(raw) is bytes and len(raw) <= MAX_BLOB_BYTES for raw in parts.values()), 'blob_limit', 'input blob admission failed')
        try:
            with self._lock(True):
                if self._cache is None:
                    self._oracle_locked('first_access_full_reference')
                raw, before = self._fence()
                state = self._cache['state']; gj, gb = _blob_readers(self._cache['blobs'])
                require(state['records'] < MAX_EVENTS, 'event_limit', 'event cap exhausted; do not evict/restart')
                with closing(sqlite3.connect(self.path, timeout=5)) as db:
                    db.execute('PRAGMA synchronous=FULL'); db.execute('BEGIN IMMEDIATE')
                    try:
                        # Every original raw row/blob remains checked, even if
                        # an external writer ignored the cooperative lock.
                        self._t('validation', 'verify_pretransaction_original_bytes', self._all_bytes, db, self._cache, appended=0)
                        require(identity(os.stat(self.path, follow_symlinks=False)) == before,
                                'storage_changed', 'database changed before owner transaction')
                        refs = {key: self._t('io', 'append_original_blob', self._put, db, value) for key, value in parts.items()}
                        try:
                            kind, payload, value = handler(db, state, gj, gb, refs)
                            accepted, error = True, None
                        except (ValueError, KeyError, TypeError, IndexError) as exc:
                            # Preserve a primary domain exception when diagnostic close
                            # also failed. Do not turn instrumentation failure into a
                            # model rejection or permit this transaction to continue.
                            if self._timing is not None and self._timing.failed: raise
                            accepted, kind, value = False, 'write_rejected', None
                            error = {'code': getattr(exc, 'code', 'malformed_input'), 'type': type(exc).__name__, 'detail': str(exc)}
                            payload = {'operation': operation, 'args': args, 'original_blob_refs': refs, 'error': error}
                        tail = self._t('io', 'append_original_journal_event', self._append, db, kind, payload, state['records'], state['tail'])
                        rows, blobs = self._t('validation', 'verify_new_and_original_sql_bytes', self._all_bytes, db, self._cache, appended=1)
                        candidate = self._advance(rows, blobs)
                        require((os.stat(self.path, follow_symlinks=False).st_dev, os.stat(self.path, follow_symlinks=False).st_ino) == before[:2],
                                'storage_changed', 'database path changed while writing')
                        self._t('io', 'sqlite_commit_original_event', db.commit)
                    except BaseException as primary:
                        try: db.rollback()
                        except BaseException as secondary:
                            primary.add_note('rollback after primary failure also failed: '+type(secondary).__name__+': '+str(secondary))
                        raise
                self._t('io', 'sync_store_directory', self._sync); self._ready(); final_raw, ident = self._snapshot()
                require(ident[:2] == before[:2], 'storage_changed', 'database replaced after owner transaction; unknown outcome')
                with closing(sqlite3.connect(':memory:')) as check:
                    check.deserialize(final_raw); check.execute('PRAGMA query_only=ON')
                    self._t('validation', 'verify_posttransaction_original_bytes', self._all_bytes, check, candidate, appended=0)
                require(identity(os.stat(self.path, follow_symlinks=False)) == ident, 'storage_changed', 'database replaced during final byte fence')
                require(same(candidate['state']['runtime'], self._t('validation', 'exact_runtime_source_manifest', runtime_manifest)), 'runtime', 'source changed during transaction')
                candidate.update(database_sha256=sha(final_raw), database_bytes=len(final_raw), identity=ident)
                self._cache = candidate
                self._reasons.append({'mode': 'incremental_suffix', 'reason': operation,
                                      'journal_records': candidate['state']['records'], 'accepted': accepted})
                result = {'accepted': accepted, 'accepted_scope': 'durable structure and explicitly performed pure interaction calculation only',
                          'value': deepcopy(value), 'error': error, 'journal_tail_sha256': tail, 'journal_records': state['records'] + 1, **FLAGS}
                # Preserve the originally captured final snapshot through source
                # checks, cache/report construction, and this operation's return.
                # A replacement here is an unknown committed outcome, not success.
                self._fence(); return result
        except BaseException as exc:
            # Do not recover/retry or re-anchor after any unknown transaction,
            # source/storage failure, interruption or failed cache publication.
            self._poison = repr(exc); raise

    def _prefix(self, prefix, *, exact):
        require(type(prefix) is dict and {'journal_records', 'journal_tail_sha256', 'database_sha256'} <= set(prefix),
                'prefix', 'external prefix fields required')
        count = prefix['journal_records']; cache = self._cache
        require(type(count) is int and 1 <= count <= cache['state']['records'] and
                cache['rows'][count - 1][4] == prefix['journal_tail_sha256'], 'prefix', 'external original prefix differs')
        if exact:
            require(count == cache['state']['records'] and prefix['database_sha256'] == cache['database_sha256'],
                    'export', 'export requires exact externally anchored snapshot')

    def _report(self, *, include_evidence, mode):
        cache = self._cache; state = cache['state']; gj, _ = _blob_readers(cache['blobs'])
        sessions = []; interactions = []
        for sid, session in state['sessions'].items():
            model = cache['models'][sid]; phase = 'idle'; pending = None
            for aid in session['attempt_ids']:
                a = state['attempts'][aid]
                if a['action'] is None:
                    pending = aid
                    phase = 'reserved_transport_unknown' if a['request'] is None else 'transport_pending' if a['completion'] is None else 'completed_unprocessed' if gj(a['completion']['result_blob'])['status'] == 'success' else 'failed_transport_preserved'
            if session['selection_blob'] is not None: phase = 'selection_recorded'
            if session['intent'] is not None: phase = 'external_commit_outcome_unknown'
            if session['receipt'] is not None: phase = 'external_receipt_reported_' + session['receipt']['reported_outcome']
            evidence = model.export_evidence()
            sessions.append({'interaction_id': sid, 'phase': phase, 'pending_attempt_id': pending,
                'pending_transport_run_dir': None if pending is None else gj(state['attempts'][pending]['spec_blob'])['run_dir'],
                'pending_call_id': None if pending is None or state['attempts'][pending]['request'] is None else state['attempts'][pending]['request']['call_id'],
                'pending_full_prompt_sha256': None if pending is None else state['attempts'][pending]['full_prompt_sha256'],
                'pending_body_sha256': None if pending is None else state['attempts'][pending]['body_sha256'],
                'action_count': len(evidence['history']), 'candidate_count': len(evidence['candidates']),
                'selection_sha256': None if session['selection_blob'] is None else digest(gj(session['selection_blob'])),
                'selection_blob': session['selection_blob'], 'anchors': model.context()['anchors'], 'no_automatic_processing_or_commit': True})
            if include_evidence: interactions.append({'interaction_id': sid, 'evidence': evidence})
        report = {'schema': SCHEMA + '-recovery', 'valid': True, 'errors': [], 'pure_replay_verified': True, **FLAGS,
            'store_id': state['store_id'], 'journal_records': state['records'], 'journal_tail_sha256': state['tail'],
            'database_sha256': cache['database_sha256'], 'database_bytes': cache['database_bytes'],
            'instances': deepcopy(state['instances']), 'sessions': sessions, 'rejected_write_count': len(state['rejections']),
            'verification_mode': mode, 'cache_owner_pid': self._owner_pid}
        if include_evidence: report['interactions'] = interactions
        return report

    def inspect_live(self, *, expected_store_id, attempt_id=None):
        """Bridge inspect_store-compatible triple, guarded by original DB bytes.

        The returned state/evidence are copies. No pending action is processed.
        """
        try:
            with self._lock(False):
                self._fence(); state = self._cache['state']
                require(state['store_id'] == expected_store_id, 'store_id', 'external registration mismatch')
                gj, gb = _blob_readers(self._cache['blobs'])
                public_state = deepcopy(state)
                contexts = {sid: deepcopy(model.context()) for sid, model in self._cache['models'].items()}
                if attempt_id in state['attempts']:
                    attempt = state['attempts'][attempt_id]; spec = gj(attempt['spec_blob'])
                    stored = {'spec': spec, 'prompt': gj(attempt['prompt_blob']), 'schema_bytes': gb(spec['schema_blob']), 'attached_bytes': {}}
                    public_state['_inspected_attempt'] = stored
                    for stage, fields in (('request', {'request.json': 'request_blob', 'reserve_line': 'reserve_blob', 'attempt.claim': 'claim_blob', 'prompt.txt': 'prompt_file_blob', 'schema.json': 'schema_file_blob'}),
                                          ('completion', {'result.json': 'result_blob', 'finish_line': 'finish_blob', 'events.jsonl': 'events_blob', 'final.txt': 'final_blob'})):
                        if attempt[stage] is not None:
                            for name, key in fields.items():
                                ref = attempt[stage][key]
                                if ref is not None: stored['attached_bytes'][name] = gb(ref)
                report = self._report(include_evidence=False, mode='incremental_same_owner')
                self._fence()
                return report, public_state, contexts
        except BaseException as exc:
            self._poison = repr(exc); raise

    def export_live(self, *, expected_store_id, expected_prefix):
        try:
            with self._lock(False):
                self._fence(); require(self._cache['state']['store_id'] == expected_store_id, 'store_id', 'external registration mismatch')
                self._prefix(expected_prefix, exact=True)
                report = self._report(include_evidence=True, mode='incremental_same_owner')
                self._fence(); return report
        except BaseException as exc:
            self._poison = repr(exc); raise

    def attach(self, instance_id, interaction_id):
        self._healthy(write=True); self.verify_full(reason='new_instance_before_attach')
        result = super().attach(instance_id, interaction_id)
        self.verify_full(reason='new_instance_after_attach'); return result

    def record_commit_intent(self, instance_id, **kwargs):
        self._healthy(write=True); self.verify_full(reason='critical_commit_intent_before')
        result = super().record_commit_intent(instance_id, **kwargs)
        self.verify_full(reason='critical_commit_intent_after'); return result

    def record_commit_receipt(self, instance_id, **kwargs):
        self._healthy(write=True); self.verify_full(reason='critical_commit_receipt_before')
        result = super().record_commit_receipt(instance_id, **kwargs)
        self.verify_full(reason='critical_commit_receipt_after'); return result

    def diagnostics(self):
        return {'schema': SCHEMA + '-diagnostics', 'counts': deepcopy(self._counts), 'reference_scopes': deepcopy(self._reasons),
                'poisoned': self._poison is not None, 'poison_reason': self._poison, 'recovered_read_only': self._recovered,
                'wall_or_cpu_measured': False, 'performance_improvement_certified': False}
