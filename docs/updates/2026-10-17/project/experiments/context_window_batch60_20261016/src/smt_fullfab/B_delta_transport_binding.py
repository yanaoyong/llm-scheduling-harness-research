"""Read-only local channel files + authorization-prefix binding, never a model call.

No BudgetLedger, model_transport or recovery mutator is imported. A verified
local file set is not independent proof of backend identity or an actual call.
"""
from copy import deepcopy
from dataclasses import dataclass
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import tomllib

from src.smt_fullfab.controller_audit import _audit_ledger_admission, _record_digest, _schema_errors
from src.smt_fullfab.constructor_audit import audit_constructor_ledger

SCHEMA = 'draft-smt-fullfab-readonly-transport-binding-v1'
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
FILES = ('prompt.txt', 'schema.json', 'system-instructions.txt', 'command.json', 'attempt.claim',
         'request.json', 'result.json', 'events.jsonl', 'final.txt')
DISABLED_FEATURES = (
    'apps', 'plugins', 'remote_plugin', 'browser_use', 'browser_use_external', 'browser_use_full_cdp_access',
    'in_app_browser', 'computer_use', 'shell_tool', 'unified_exec', 'shell_snapshot', 'multi_agent', 'view_image',
    'image_generation', 'artifact', 'workspace_dependencies', 'code_mode', 'code_mode_host', 'code_mode_only',
    'hooks', 'memories', 'skill_search', 'skill_mcp_dependency_install', 'tool_suggest', 'goals',
    'default_mode_request_user_input', 'request_permissions_tool', 'standalone_web_search', 'sleep_tool',
    'unbounded_connection_retries', 'agent_message_board', 'send_message_to_user_async',
)
SYSTEM_TEXT = '''You are a decision component in a controlled scheduling experiment.
Use only data in the user message. No native tools are available or permitted.
Return exactly one JSON object conforming to the supplied schema. Any requested action
is data for an external deterministic runner, not a native tool call. Do not access files,
networks, shells, code interpreters, memory, other runs, or reference solutions.
Provide concise decision justifications when the schema requests them.
'''
REQUEST_FIELDS = {
    'catalog_page': ['path', 'offset', 'count'], 'catalog_text': ['offset', 'count'], 'session_query': ['action'],
    'create_draft': ['draft_id'], 'assembly_action': ['action'],
    'check_assembly': ['draft_id', 'sealed_state_sha256', 'seal_action_sha256', 'delta_sha256'],
    'read_draft': ['draft_id', 'state_sha256', 'path', 'format', 'offset', 'count'],
    'read_candidate': ['candidate_id', 'candidate_sha256', 'path', 'format', 'offset', 'count'],
    'read_candidates': [], 'read_archive_feedback': ['history_index', 'feedback_sha256', 'path', 'format', 'offset', 'count'],
    'apply': ['candidate_id', 'candidate_sha256'],
}
FLAGS = {'backend_identity_independently_proven': False, 'actual_backend_invocation_independently_proven': False,
         'credentials_inspected': False, 'ledger_modified': False, 'model_or_cli_called': False,
         'physical_validation_performed': False, 'physical_commit_performed': False}


class BindingError(ValueError):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(code + ': ' + detail)


def require(ok, code, detail):
    if not ok:raise BindingError(code, detail)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def same(left, right):
    return canonical(left) == canonical(right)


def parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate_json_key', 'duplicate original JSON key')
            result[key] = value
        return result
    def constant(value):raise BindingError('json', 'nonfinite JSON constant ' + value)
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
    canonical(value)  # Also reject finite-looking exponents that overflow to infinity.
    return value


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_snapshot(path):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno());ident = identity(info)
        require(stat.S_ISREG(info.st_mode) and ident == identity(os.stat(path, follow_symlinks=False)), 'file_identity', 'regular descriptor and path must agree')
        require(info.st_size <= MAX_FILE_BYTES, 'file_size', 'read-only evidence file exceeds cap')
        raw = stream.read()
        require(len(raw) == info.st_size and identity(os.fstat(stream.fileno())) == ident
                and identity(os.stat(path, follow_symlinks=False)) == ident, 'file_changed', 'file changed during snapshot read')
    return raw, {'path': str(path), 'sha256': sha(raw), 'bytes': len(raw), 'identity': list(ident)}


def expected_settings(run_dir, config):
    settings = {'model_reasoning_effort': config['reasoning_effort'], 'approval_policy': 'never', 'web_search': 'disabled',
                'project_doc_max_bytes': 0, 'mcp_servers': {}, 'skills.max_context_tokens': 1,
                'features.skip_host_skill_discovery': True, 'agents.max_concurrent_threads_per_session': 1,
                'features.multi_agent_v2': {'enabled': False, 'max_concurrent_threads_per_session': 1, 'wait_agent_enabled': False},
                'model_instructions_file': str(run_dir / 'system-instructions.txt'), 'log_dir': str(run_dir / 'runtime/log'),
                'sqlite_home': str(run_dir / 'runtime/state'), 'history.persistence': 'none', 'shell_environment_policy.inherit': 'none'}
    settings.update({'features.' + feature: False for feature in DISABLED_FEATURES})
    return settings


def verify_command(command, run_dir, config, disabled_skill_paths):
    require(type(command) is dict and set(command) == {'argv', 'cwd', 'stdin', 'proxy'}, 'command', 'exact saved command structure required')
    require(command['cwd'] == str(run_dir / 'isolated-cwd') and command['stdin'] == 'prompt.txt'
            and same(command['proxy'], config['proxy']), 'command', 'cwd/stdin/proxy differ')
    prefix = [config['codex_binary'], 'exec', '--json', '--ephemeral', '--ignore-user-config', '--ignore-rules',
              '--skip-git-repo-check', '--sandbox', 'read-only', '--color', 'never', '--model', config['model'],
              '--cd', str(run_dir / 'isolated-cwd'), '--output-schema', str(run_dir / 'schema.json'),
              '--output-last-message', str(run_dir / 'final.txt')]
    args = command['argv']
    require(type(args) is list and all(type(arg) is str for arg in args) and args[:len(prefix)] == prefix
            and args[-1:] == ['-'], 'command', 'CLI prefix/model/path/isolation flags differ')
    rest = args[len(prefix):-1]
    require(len(rest) % 2 == 0, 'command', 'unpaired override')
    actual = {}
    for i in range(0, len(rest), 2):
        require(rest[i] == '-c' and '=' in rest[i + 1], 'command', 'only explicit -c configuration pairs allowed')
        key = rest[i + 1].split('=', 1)[0]
        require(key not in actual, 'command', 'duplicate overriding configuration key')
        parsed = tomllib.loads(rest[i + 1]);value = parsed
        for component in key.split('.'):
            require(type(value) is dict and set(value) == {component}, 'command', 'ambiguous override syntax')
            value = value[component]
        actual[key] = value
    expected = expected_settings(run_dir, config)
    require(set(actual) == set(expected) | {'skills.config'} and all(same(actual[k], v) for k, v in expected.items()),
            'command', 'missing/extra/altered isolation override')
    skills = actual['skills.config']
    require(type(skills) is list and all(type(s) is dict and set(s) == {'path', 'enabled'} and s['enabled'] is False
            and type(s['path']) is str and Path(s['path']).is_absolute() for s in skills), 'command', 'all declared skills must be explicitly disabled')
    paths = [s['path'] for s in skills]
    require(len(paths) == len(set(paths)), 'command', 'duplicate disabled skill path')
    if disabled_skill_paths is not None:
        require(paths == disabled_skill_paths, 'command', 'disabled skill inventory differs from supplied frozen expectation')
    return {'disabled_skill_paths': paths, 'external_skill_inventory_verified': disabled_skill_paths is not None,
            'isolation_command_and_system_verified': True, 'backend_enforcement_independently_proven': False}


def summarize_events(raw):
    events = []
    for line in raw.decode('utf-8').splitlines():
        if line.strip():events.append(parse(line.encode()))
    require(all(type(e) is dict for e in events), 'events', 'original events must be JSON objects')
    completed = [e for e in events if e.get('type') == 'turn.completed']
    # Validate original counters before aggregating. Python's bool-is-int and
    # numeric coercions must never turn invalid source evidence into known cost.
    for event in completed:
        original = event.get('usage')
        require(original is None or type(original) is dict, 'usage_type', 'original usage must be an object, missing, or null')
        if original is not None:
            for key, value in original.items():
                require(value is None or (type(value) is int and value >= 0), 'usage_type',
                        'original usage counter must be a nonnegative integer or null: ' + key)
    usages = [e['usage'] for e in completed if type(e.get('usage')) is dict]
    usage = {key: sum(u[key] for u in usages) if len(usages) == len(completed) and usages
             and all(type(u.get(key)) is int for u in usages) else None
             for key in ('input_tokens', 'cached_input_tokens', 'output_tokens', 'cache_write_input_tokens', 'reasoning_output_tokens')}
    native = [e.get('item', {}) for e in events if e.get('type') in ('item.started', 'item.completed', 'item.updated')
              and e.get('item', {}).get('type') not in {'agent_message', 'reasoning', 'error'}]
    return {'completed_turns': len(completed), 'usage': usage, 'usage_status': 'reported' if usages else 'unknown',
            'native_tool_events': native, 'thread_ids': [e['thread_id'] for e in events if e.get('type') == 'thread.started' and 'thread_id' in e],
            'errors': [e for e in events if e.get('type') in {'error', 'turn.failed'}]}


def verify_envelope(output, prompt, context):
    keys = {'schema', 'interaction_id', 'session_id', 'anchors', 'catalog_sha256', 'prompt_body_sha256', 'memory', 'request'}
    require(type(output) is dict and set(output) == keys and output['schema'] == 'draft-smt-fullfab-delta-interaction-v2-response', 'envelope', 'exact v2 original envelope required')
    require(type(context) is dict and set(context) == {'interaction_id', 'session_id', 'anchors', 'catalog_sha256'}, 'envelope', 'external issued interaction context required')
    require(all(type(output[k]) is type(v) and same(output[k], v) for k, v in context.items()), 'envelope', 'original envelope differs from external context')
    header, payload = prompt.split('\n', 1)
    body_sha = sha(payload.encode())
    require(header == 'PROMPT_BODY_SHA256=' + body_sha and output['prompt_body_sha256'] == body_sha, 'envelope', 'actual full prompt/body hash binding differs')
    require(payload.count('\nINPUT_JSON\n') == 1, 'envelope', 'exact interaction prompt separator required')
    body = parse(payload.split('\nINPUT_JSON\n', 1)[1].encode())
    require(all(same(body.get(k), v) for k, v in context.items()), 'envelope', 'issued prompt context differs from external expectation')
    require(type(output['memory']) is str and len(json.dumps(output['memory'], ensure_ascii=True, separators=(',', ':'))) <= 8192,
            'envelope', 'model memory is not an exact bounded string')
    request = output['request']
    require(type(request) is dict and type(request.get('kind')) is str and request['kind'] in REQUEST_FIELDS
            and set(request) == {'kind', *REQUEST_FIELDS[request['kind']]}, 'envelope', 'unknown/malformed explicit request')
    return {'schema': output['schema'], 'prompt_body_sha256': body_sha, 'full_prompt_sha256': sha(prompt.encode()),
            'request_sha256': sha(canonical(request).encode()), 'projection_pointer': '/request',
            'semantic_action_validation_performed': False}


@dataclass(frozen=True)
class BindingResult:
    report: dict
    raw_artifacts: dict

    def durable_attachments(self):
        require(self.report.get('success_action_eligible') is True, 'not_eligible', 'only a locally verified successful v2 envelope may be attached as an action')
        raw = self.raw_artifacts
        return {'request': {'request_bytes': raw['request.json'], 'reserve_bytes': raw['ledger_reserve_line'],
                            'claim_bytes': raw['attempt.claim'], 'prompt_bytes': raw['prompt.txt'], 'schema_bytes': raw['schema.json']},
                'completion': {'result_bytes': raw['result.json'], 'finish_bytes': raw['ledger_finish_line'],
                               'events_bytes': raw['events.jsonl'], 'final_bytes': raw['final.txt']}}


def bind_original_call(*, run_dir, expected_run_dir, expected_prompt, expected_schema, expected_config,
                       ledger_snapshot_path, ledger_source_path, expected_ledger_sha256,
                       expected_approval_record_sha256, expected_registration_id, expected_registration_record_sha256,
                       expected_interaction_context=None, require_interaction_envelope=True, expected_disabled_skill_paths=None):
    """Compare stable original bytes and trusted expectations. No writes or resume calls."""
    report = {'schema': SCHEMA, 'local_channel_files_and_ledger_verified': False,
              'success_action_eligible': False, 'interaction_envelope_verified': False,
              'errors': [], 'files': {}, 'assurance': deepcopy(FLAGS)}
    raw = {};proofs = []
    try:
        require(type(require_interaction_envelope) is bool, 'mode', 'envelope mode must be an explicit boolean')
        run = Path(run_dir).absolute();expected = Path(expected_run_dir).absolute()
        require(run == expected == run.resolve(), 'run_dir', 'actual directory differs from externally expected normalized directory')
        require(type(expected_prompt) is str and len(expected_prompt) <= 120000, 'prompt', 'external prompt must be within actual transport gate')
        config = deepcopy(expected_config)
        require(type(config) is dict and config.get('model') == 'gpt-6-astra' and config.get('reasoning_effort') == 'medium'
                and finite(config.get('timeout_seconds')) and 1 <= config['timeout_seconds'] <= 180, 'config', 'fixed model/effort and at most180-second timeout required')
        source = str(Path(ledger_source_path).absolute())
        require(source == str(Path(source).resolve()) and config.get('ledger_path') == source, 'ledger_source', 'external original ledger path differs from config')
        ledger_raw, ledger_proof = read_snapshot(Path(ledger_snapshot_path).absolute());proofs.append(ledger_proof)
        raw['ledger_snapshot'] = ledger_raw
        require(sha(ledger_raw) == expected_ledger_sha256, 'ledger_hash', 'ledger snapshot differs from external source hash')
        report['ledger_snapshot'] = {**ledger_proof, 'original_source_path': source,
                                     'source_path_asserted_by_caller': str(Path(ledger_snapshot_path).absolute()) != source}
        for name in FILES:
            data, proof = read_snapshot(run / name)
            raw[name] = data;proofs.append(proof);report['files'][name] = proof
        require(sum(len(v) for v in raw.values()) <= MAX_TOTAL_BYTES, 'total_size', 'read-only evidence exceeds total cap')
        schema_text = json.dumps(expected_schema, ensure_ascii=False, indent=2) + '\n'
        require(raw['prompt.txt'] == expected_prompt.encode('utf-8') and raw['schema.json'] == schema_text.encode(), 'request_bytes', 'actual prompt/schema differ from external original request')
        require(raw['system-instructions.txt'] == SYSTEM_TEXT.encode(), 'system', 'original no-native-tools system instructions changed')
        isolation = verify_command(parse(raw['command.json']), run, config, expected_disabled_skill_paths)
        fingerprint = sha((expected_prompt + '\n' + schema_text + '\n' + json.dumps(config, sort_keys=True)).encode())
        request, result = parse(raw['request.json']), parse(raw['result.json'])
        require(type(request) is dict and type(result) is dict and same(request.get('config'), config) and same(result.get('config'), config)
                and request.get('request_fingerprint') == result.get('request_fingerprint') == fingerprint
                and raw['attempt.claim'] == (fingerprint + '\n').encode(), 'fingerprint', 'original request/result/claim/config mismatch')
        cid = request.get('call_id')
        require(type(cid) is str and cid and result.get('call_id') == cid, 'call_id', 'request/result call identity differs')
        lines = ledger_raw.splitlines(keepends=True)
        entries = [(i, parse(line), line) for i, line in enumerate(lines) if line.strip()]
        rows = [row for _, row, _ in entries]
        require(all(type(row) is dict for row in rows), 'ledger', 'ledger entries must be objects')
        reserves = [(i, row, line) for i, (_, row, line) in enumerate(entries) if row.get('event') == 'reserve' and row.get('call_id') == cid]
        finishes = [(i, row, line) for i, (_, row, line) in enumerate(entries) if row.get('event') == 'finish' and row.get('call_id') == cid]
        require(sum(row.get('event') == 'reserve' and row.get('run_id') == str(run) for row in rows) == 1,
                'run_dir_reused', 'original transport directory must identify only this single ledger reservation')
        require(len(reserves) == len(finishes) == 1, 'ledger_terminal', 'exactly one original reserve and finish required; pending cannot be a successful action')
        ri, reservation, reserve_line = reserves[0];fi, finish, finish_line = finishes[0]
        require(ri < fi, 'ledger_order', 'finish precedes reserve')
        raw['ledger_reserve_line'], raw['ledger_finish_line'] = reserve_line, finish_line
        approvals = [(i, row['approval']) for i, row in enumerate(rows) if row.get('event') == 'approval']
        require(len(approvals) == 1 and approvals[0][0] < ri and _record_digest(approvals[0][1]) == expected_approval_record_sha256
                and approvals[0][1].get('authorization') == 'approved_by_user', 'approval', 'original unique prior authorization differs from external hash')
        registrations = [(i, row['registration']) for i, row in enumerate(rows) if row.get('event') == 'stage_run_registered'
                         and row.get('registration', {}).get('registration_id') == expected_registration_id]
        require(len(registrations) == 1 and registrations[0][0] < ri
                and _record_digest(registrations[0][1]) == expected_registration_record_sha256,
                'registration', 'unique externally expected registration must precede original reserve')
        authority_prefix = rows[:ri + 1]
        admission = _audit_ledger_admission(authority_prefix, approvals[0][1])
        constructors = audit_constructor_ledger(authority_prefix)
        require(not admission['errors'] and not admission['missing_evidence'] and not constructors['errors'],
                'ledger_admission', 'prior authorization/admission replay errors: ' + repr(admission['errors'] + admission['missing_evidence'] + constructors['errors']))
        effective = admission['admissions'].get(cid, {})
        require(effective.get('waiver_scope') == 'registered_research' and same(effective.get('registration'), registrations[0][1])
                and reservation.get('registration_id') == expected_registration_id, 'registration', 'reserve does not use expected prior research registration')
        registration = registrations[0][1]
        require(same(config.get('authorization_context'), {'purpose': registration['arm'], 'arm': registration['arm'],
                'scenario': registration['scenario'], 'window_seconds': registration['window_seconds']}),
                'registration', 'request scenario/window/arm must match prior registration including JSON types')
        require(reservation.get('run_id') == str(run) and reservation.get('phase') == config['phase']
                and reservation.get('grant_id') == config['grant_id'], 'ledger_binding', 'reserve directory/phase/grant mismatch')
        metadata = {'request_fingerprint': fingerprint, 'model': config['model'], 'timeout_seconds': config['timeout_seconds'],
                    'reasoning_effort': config['reasoning_effort'], 'prompt_characters': len(expected_prompt), 'prompt_character_limit': 120000,
                    'authorization_context': config['authorization_context']}
        require(same(reservation.get('metadata'), metadata), 'ledger_binding', 'original reservation metadata differs')
        require(request.get('started_at') == result.get('started_at'), 'terminal', 'request/result start timestamp differs')
        began, ended = dt.datetime.fromisoformat(result['started_at']), dt.datetime.fromisoformat(result['finished_at'])
        require(began.tzinfo is not None and ended.tzinfo is not None and ended >= began, 'terminal', 'terminal timestamps invalid')
        duration = result.get('duration_seconds')
        require(finite(duration) and duration >= 0 and same(duration, result.get('model_elapsed_seconds'))
                and same(result.get('model_calls'), 1) and same(result.get('automatic_retries'), 0)
                and result.get('cost_usd') is None and same(result.get('prompt_characters'), len(expected_prompt))
                and same(result.get('prompt_character_limit'), 120000), 'terminal', 'terminal resource fields inconsistent')
        summary = summarize_events(raw['events.jsonl'])
        require(all(same(result.get(key), value) for key, value in summary.items()) and result.get('malformed_event_lines') == [],
                'events', 'events disagree with original completion/usage/isolation summary')
        require(result.get('status') == finish.get('status') == 'success' and result.get('failure_reason') is None
                and result.get('timed_out') is False and result.get('launch_error') is None and same(result.get('returncode'), 0)
                and summary['completed_turns'] == 1 and not summary['native_tool_events'] and result.get('decode_error') is None,
                'not_success', 'pending/failed/timeout/isolation violation cannot be an eligible successful action')
        details = {'result_path': str(run / 'result.json'), 'failure_reason': result['failure_reason'], 'usage': result['usage'],
                   'duration_seconds': duration, 'cost_usd': result['cost_usd'], 'completed_turns': result['completed_turns']}
        require(same(finish.get('details'), details), 'ledger_finish', 'original finish is missing or changed; no repair performed')
        # Replay through finish also rejects intervening unclosed/duplicate model admissions.
        completion_replay = _audit_ledger_admission(rows[:fi + 1], approvals[0][1])
        require(not completion_replay['errors'] and not completion_replay['missing_evidence']
                and not audit_constructor_ledger(rows[:fi + 1])['errors'], 'ledger_completion', 'ledger completion prefix inconsistent')
        original_events = [parse(line) for line in raw['events.jsonl'].splitlines() if line.strip()]
        messages = [e.get('item', {}).get('text') for e in original_events
                    if e.get('type') == 'item.completed' and e.get('item', {}).get('type') == 'agent_message']
        require(len(messages) == 1 and type(messages[0]) is str and messages[0].encode('utf-8') == raw['final.txt']
                and not summary['errors'], 'final_event', 'one original completed agent message must exactly match final bytes without failed-turn errors')
        output = parse(raw['final.txt'])
        require(same(output, result.get('output')), 'final', 'original UTF8 final differs from original result.output')
        require(not _schema_errors(output, expected_schema), 'output_schema', 'output fails existing declared-schema subset checker')
        envelope = verify_envelope(output, expected_prompt, expected_interaction_context) if require_interaction_envelope else None
        for proof in proofs:
            require(identity(os.stat(proof['path'], follow_symlinks=False)) == tuple(proof['identity']), 'file_changed', 'evidence path changed during complete verification')
        report.update(local_channel_files_and_ledger_verified=True, success_action_eligible=require_interaction_envelope,
                      interaction_envelope_verified=require_interaction_envelope, run_dir=str(run), call_id=cid,
                      request_fingerprint=fingerprint, effective_authorization=effective,
                      reserve_record_index=ri, finish_record_index=fi, authorization_prefix_sha256=_record_digest(authority_prefix),
                      approval_record_sha256=expected_approval_record_sha256, registration_id=expected_registration_id,
                      registration_record_sha256=expected_registration_record_sha256, isolation=isolation,
                      envelope=envelope, usage=summary['usage'], duration_seconds=duration,
                      usage_known=all(type(summary['usage'][k]) is int and summary['usage'][k] >= 0 for k in ('input_tokens', 'output_tokens')),
                      unknown_usage_policy='Preserve original null/unknown values. This checker makes no future admission decision; applicable approved ledger rules govern later calls.',
                      interpretation='Original local channel files and effective ledger authorization have been cross-checked. Backend identity/invocation and enforcement cannot be independently proved from these mutable local artifacts alone.')
    except Exception as exc:
        report['errors'].append({'code': getattr(exc, 'code', 'binding_exception'), 'type': type(exc).__name__, 'detail': str(exc)})
    return BindingResult(report, raw)
