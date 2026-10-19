#!/usr/bin/env python3
"""Pinned-Codex loopback-only capability recordings. Wire assumptions fail closed."""
import argparse
import difflib
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import threading
import time
from urllib.parse import urlparse
from harness_v6.codex_runner import CodexRunner
from harness_v6.contracts import digest, encode
from harness_v6.mac_probe import create_server
from harness_v6.session import Budget, classify, command
from harness_v6.single_action import command as single_command, parse, OUTPUT_SCHEMA
from harness_v6.tool_contract import declared_tools, request_tools, RESOURCE_TOOLS

CHECKS = ('config_injection', 'approval_never', 'schema_with_mcp', 'jsonl_fields',
          'startup_timeout', 'tool_timeout', 'compaction_detection',
          'environment_inheritance', 'large_result_complete',
          'single_schema_no_mcp', 'single_tool_rejection', 'single_usage')
CHECKS += ('required_startup_ready', 'over_limit_harness', 'resource_abort', 'rollout_budget_stop', 'resource_list_abort', 'resource_templates_abort')
ACTION = dict(expected_state_version=1, submission_id='probe', delta={})
SENTINEL = 'v6-explicit-environment'
COMPACTION_SENTINEL = 'V6_OFFLINE_COMPACTION_REQUEST'


def write(path, value):
    Path(path).write_bytes(encode(value) + b'\n')


def provider_settings(url):
    parsed = urlparse(url)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port or parsed.username or parsed.password:
        raise ValueError('mock provider URL must be http://127.0.0.1:PORT/v1')
    return {'model_provider': 'v6_mock', 'model_providers.v6_mock.name': 'V6 loopback mock',
            'model_providers.v6_mock.base_url': url, 'model_providers.v6_mock.wire_api': 'responses',
            'model_providers.v6_mock.requires_openai_auth': False,
            'model_providers.v6_mock.request_max_retries': 0,
            'model_providers.v6_mock.stream_max_retries': 0}


def configure(argv, settings):
    # Replace existing assignments, keeping the final stdin marker last.
    result = []; index = 0
    while index < len(argv)-1:
        if argv[index] == '-c' and argv[index+1].split('=', 1)[0] in settings:
            index += 2
        else:
            result.append(argv[index]); index += 1
    for key, value in settings.items():
        result += ['-c', key + '=' + json.dumps(value)]
    return result + ['-']


def sse(items, number, usage=None):
    response = dict(id=f'resp_{number}', object='response', status='completed', output=items,
        usage=usage if usage is not None else dict(input_tokens=100, output_tokens=10, total_tokens=110,
                   input_tokens_details=dict(cached_tokens=20)))
    events = [dict(type='response.created', response=dict(response, status='in_progress', output=[]))]
    for index, item in enumerate(items):
        events.append(dict(type='response.output_item.added', output_index=index,
                           item=dict(item, status='in_progress')))
        if item['type'] == 'message':
            text = item['content'][0]['text']
            events += [dict(type='response.content_part.added', item_id=item['id'], output_index=index,
                            content_index=0, part=dict(type='output_text', text='', annotations=[])),
                       dict(type='response.output_text.delta', item_id=item['id'], output_index=index,
                            content_index=0, delta=text),
                       dict(type='response.output_text.done', item_id=item['id'], output_index=index,
                            content_index=0, text=text)]
        else:
            events.append(dict(type='response.function_call_arguments.done', item_id=item['id'],
                               output_index=index, arguments=item['arguments']))
        events.append(dict(type='response.output_item.done', output_index=index, item=item))
    events.append(dict(type='response.completed', response=response))
    return dict(content_type='text/event-stream', body=''.join(
        'event: '+e['type']+'\ndata: '+json.dumps(dict(e, sequence_number=i))+'\n\n'
        for i, e in enumerate(events)))


def result_payload(check):
    return dict(marker=SENTINEL, inherited=os.environ.get('V6_FORBIDDEN_SENTINEL'),
                payload='0123456789abcdef' * (16384 if check == 'large_result_complete' else 1))


def mcp(check, directory):
    write(directory/'mcp-start.json', dict(started=True))
    overhead = (directory/'overhead.json').exists()
    from harness_v6.mcp_server import TOOLS, TOOL_DESCRIPTIONS, CycleServer
    guard = None
    if check == 'over_limit_harness' or check.startswith('resource_'):
        from harness_v6.synthetic import SyntheticFactory, SOURCE
        from harness_v6.facts import build_facts
        factory = SyntheticFactory()
        inp = directory/'cycle-input'; inp.mkdir()
        write(inp/'cycle.json', dict(context_ref='probe', facts=build_facts(factory.problem(), factory.plan),
            execution_state=factory.execution_state(),
            submit_config=dict(state_version=0, next_anchor=60, source_sha256=SOURCE)))
        guard = CycleServer(inp, directory, max_tool_calls=1)
    if check == 'startup_timeout': time.sleep(4)
    if check == 'required_startup_ready': time.sleep(2)
    for line in sys.stdin:
        request = json.loads(line)
        if 'id' not in request: continue
        method = request['method']
        if guard is not None:
            response = guard.rpc(request)
            if response is not None: print(encode(response).decode(), flush=True)
            continue
        if method == 'initialize':
            result = dict(protocolVersion='2024-11-05', capabilities=dict(tools={}),
                          serverInfo=dict(name='harness_v6', version='probe'))
        elif method == 'tools/list':
            result = dict(tools=[dict(name='read_entities', description='Return probe data',
                inputSchema=dict(type='object', properties={}, additionalProperties=False))])
            if overhead or not os.environ.get('V6_FAKE_PROBE'):
                result = dict(tools=[dict(name=k, description=TOOL_DESCRIPTIONS[k], inputSchema=v) for k,v in TOOLS.items()])
        elif method == 'tools/call':
            write(directory/'tool-start.json', request['params'])
            if check == 'tool_timeout': time.sleep(4)
            payload = result_payload(check)
            if overhead:
                from harness_v6.compact import decode_snapshot
                payload = decode_snapshot((directory/'snapshot.txt').read_bytes())[1]
            from harness_v6.tool_codec import text as result_text
            result = dict(content=[dict(type='text', text=result_text(payload) if overhead else encode(payload).decode())], isError=False)
            write(directory/'mcp-received.json', dict(arguments=request['params'], result=result,
                  marker=os.environ.get('V6_PROBE_SENTINEL'), inherited=os.environ.get('V6_FORBIDDEN_SENTINEL')))
        else: raise ValueError('unsupported MCP method '+method)
        print(encode(dict(jsonrpc='2.0', id=request['id'], result=result)).decode(), flush=True)


def outputs(body):
    return [item.get('output') for item in body.get('input', [])
            if isinstance(item, dict) and item.get('type') == 'function_call_output']


def decoded_tool_output(value):
    from harness_v6.contracts import strict_json
    from harness_v6.tool_codec import unpack
    # 0.163 emits a separate header and the unmodified MCP text content.
    # Accept only this exact two-part shape; never join/drop arbitrary parts.
    if isinstance(value,list):
        if len(value)!=2 or any(not isinstance(p,dict) or set(p)!={'type','text'}
                or p['type']!='input_text' or not isinstance(p['text'],str) for p in value):
            raise ValueError('expected complete native text header and one MCP text result')
        if not re.fullmatch(r'Wall time: \d+(?:\.\d+)? seconds\nOutput:',value[0]['text']):
            raise ValueError('unknown native MCP result framing')
        return unpack(strict_json(value[1]['text'])),value[1]['text']
    if not isinstance(value, str): raise ValueError('tool output must be complete text')
    wrapped = re.fullmatch(r'Wall time: \d+(?:\.\d+)? seconds\nOutput:\n(.*)', value, re.S)
    if not wrapped: raise ValueError('unknown native MCP result framing')
    content = strict_json(wrapped.group(1))
    if not isinstance(content, list) or len(content) != 1 or content[0].get('type') != 'text':
        raise ValueError('expected one complete MCP text result')
    return unpack(strict_json(content[0]['text'])), content[0]['text']


def unpack_result(value):
    if isinstance(value, str):
        # Native Codex wraps the complete MCP content with measured wall time.
        # Only this exact wrapper is decoded; payload bytes are still SHA checked.
        wrapped = re.fullmatch(r'Wall time: \d+(?:\.\d+)? seconds\nOutput:\n(.*)', value, re.S)
        if wrapped:
            return unpack_result(wrapped.group(1))
        try: return unpack_result(json.loads(value))
        except ValueError: return value
    if isinstance(value, dict):
        if 'payload' in value: return value
        for key in ('content', 'result', 'text'):
            if key in value:
                found = unpack_result(value[key])
                if isinstance(found, dict) and 'payload' in found: return found
    if isinstance(value, list):
        for item in value:
            found = unpack_result(item)
            if isinstance(found, dict) and 'payload' in found: return found
    return value



def probe_call_matches(envelope, arguments):
    """MCP transport metadata is outside, and never merged into, tool arguments."""
    if not isinstance(envelope, dict) or set(envelope)-{'name','arguments','_meta'}:
        return False
    if envelope.get('name') != 'read_entities' or envelope.get('arguments') != arguments:
        return False
    if '_meta' not in envelope:
        return True
    meta = envelope['_meta']
    modern_keys = {'callId','itemId','sessionId','windowId'}
    allowed = {'progressToken','threadId','x-codex-turn-metadata','codex_bridge_mcp_call_id'} | modern_keys
    if not isinstance(meta, dict) or set(meta)-allowed:
        return False
    if 'progressToken' in meta and type(meta['progressToken']) not in (int,str):
        return False
    if 'threadId' in meta and not isinstance(meta['threadId'],str):
        return False
    if 'codex_bridge_mcp_call_id' in meta:
        from uuid import UUID
        try:
            bridge = meta['codex_bridge_mcp_call_id']
            if not isinstance(bridge,str) or str(UUID(bridge)) != bridge: return False
        except ValueError:
            return False
    modern = bool(set(meta) & modern_keys)
    if modern:
        if not modern_keys <= set(meta) or not all(isinstance(meta[k],str) and meta[k] for k in modern_keys):
            return False
        if meta['sessionId'] != meta.get('threadId') or not re.fullmatch(re.escape(meta['sessionId'])+r':\d+',meta['windowId']):
            return False
        if 'x-codex-turn-metadata' not in meta: return False
    if 'x-codex-turn-metadata' in meta:
        trace = meta['x-codex-turn-metadata']
        string_keys = {'model','reasoning_effort','sandbox','session_id','thread_id','thread_source','turn_id'}
        bool_keys = {'auto_review_enabled','node_repl_auto_review_required','node_repl_disabled'} if modern else set()
        if modern: string_keys |= {'codex_version','sandbox_mode','turn_trigger'}
        if not isinstance(trace,dict) or set(trace) != string_keys | bool_keys | {'turn_started_at_unix_ms'}:
            return False
        if not all(isinstance(trace[k],str) for k in string_keys) or type(trace['turn_started_at_unix_ms']) is not int:
            return False
        if not all(type(trace[k]) is bool for k in bool_keys): return False
        if modern and (trace['codex_version'] != '0.163.0' or trace['sandbox_mode'] != 'read-only'
                       or trace['turn_trigger'] != 'exec' or trace['auto_review_enabled']):
            return False
        if trace['thread_id'] != meta.get('threadId') or trace['session_id'] != meta.get('threadId'):
            return False
    return True


def capture(binary, version, directory, check, *, prompt='Return the scripted probe response.', snapshot=None, model='gpt-5.4', timeout=15, overhead_rounds=None, context_token_budget=1000000, output_reserve_tokens=10000, forbidden_name='apply_patch', model_config=None, forbidden_with_mcp=False, rollout_budget=None):
    from harness_v6.model_config import settings as model_settings
    model_settings(model_config, model=model, context_token_budget=context_token_budget)
    if check == 'single_tool_rejection': timeout = min(timeout, 2)
    directory = Path(directory).resolve(); directory.mkdir(parents=True, exist_ok=False)
    if forbidden_with_mcp and check != 'single_tool_rejection':
        raise ValueError('forbidden_with_mcp is only valid for tool rejection probes')
    single = check.startswith('single_') and not forbidden_with_mcp
    write(directory/'schema.json', OUTPUT_SCHEMA)
    if overhead_rounds is not None:
        if overhead_rounds < 1: raise ValueError('capture rounds must be positive')
        write(directory/'overhead.json', dict(rounds=overhead_rounds))
        (directory/'snapshot.txt').write_text(prompt if snapshot is None else snapshot)
    requests = []
    compaction_requests = []
    measured_usage = []
    counter = None
    if overhead_rounds is not None and not version.startswith('fake-codex'):
        from harness_v6.snapshot import tiktoken_counter
        from harness_v6.compact import decode_snapshot
        from harness_v6.tool_codec import text as result_text
        counter = tiktoken_counter()
        expected_current = decode_snapshot((directory/'snapshot.txt').read_bytes())[1]
        expected_result_text = result_text(expected_current)
    def response(body):
        requests.append(body)
        if model_config is not None and (body.get('model') != model or
                body.get('reasoning', {}).get('effort') != model_config['reasoning_effort']):
            raise ValueError('native request model/reasoning differs from frozen configuration')
        tools = request_tools(body)
        if single and tools:
            raise ValueError('single_action unexpectedly exposes tools')
        functions = declared_tools(tools)
        if counter is not None and not single:
            found = outputs(body)
            if len(found) != len(requests)-1:
                raise ValueError('tool history missing or duplicated')
            for output in found:
                value, raw = decoded_tool_output(output)
                if encode(value) != encode(expected_current) or raw != expected_result_text:
                    raise ValueError('tool result bytes/facts changed or truncated')
        if check == 'compaction_detection' and COMPACTION_SENTINEL in json.dumps(body.get('input')):
            if functions:
                raise ValueError('compaction unexpectedly advertises tools')
            compaction_requests.append(len(requests))
            return sse([dict(type='message', id='msg_compaction', role='assistant', status='completed',
                content=[dict(type='output_text',text='Offline compaction summary.',annotations=[])])],len(requests))
        if not version.startswith('fake-codex') and check != 'startup_timeout':
            request_tools(body, interaction='single_action' if single else 'mcp_session')
        if not single:
            from harness_v6.mcp_server import TOOLS
            expected_tools = ({'read_entities'} if version.startswith('fake-codex') and not overhead_rounds else set(TOOLS))
            if not version.startswith('fake-codex'): expected_tools |= RESOURCE_TOOLS
            if check == 'startup_timeout': expected_tools = set()
            if set(functions) != expected_tools:
                raise ValueError('unexpected native/foreign/missing tools advertised')
        if check.startswith('resource_'):
            items = [dict(type='function_call', id='fc_resource', call_id='call_resource',
                name={'resource_abort':'read_mcp_resource', 'resource_list_abort':'list_mcp_resources',
                      'resource_templates_abort':'list_mcp_resource_templates'}[check],
                arguments=json.dumps(dict(server='harness_v6', **({'uri':'probe://blocked'} if check == 'resource_abort' else {}))), status='completed')]
        elif not single and check != 'startup_timeout' and len(requests) <= (2 if check == 'over_limit_harness' else overhead_rounds or 1):
            namespace, name = functions['read_entities']
            items = [dict(type='function_call', id='fc_probe_'+str(len(requests)), call_id='call_probe_'+str(len(requests)), name=name,
                          **({'namespace': namespace} if namespace else {}),
                          arguments=json.dumps({'kind':'operations', 'ids':[]} if check == 'over_limit_harness' else {'kind':'operations'} if overhead_rounds else {}), status='completed')]
        elif check == 'single_tool_rejection':
            items = [dict(type='function_call', id='fc_forbidden', call_id='call_forbidden',
                          name=forbidden_name, arguments='{}', status='completed')]
        else:
            items = [dict(type='message', id='msg_probe', role='assistant', status='completed',
                          content=[dict(type='output_text', text=json.dumps(ACTION), annotations=[])])]
        if check == 'single_tool_rejection': time.sleep(.1)
        if check != 'single_tool_rejection' and len(requests) > (overhead_rounds or 1)+3: raise ValueError('unverified wire: unexpected extra model round')
        usage = None
        if counter is not None:
            from harness_v6.snapshot import canonical
            input_tokens = counter(canonical(body).decode())
            output_tokens = sum(counter(item['arguments'] if item['type'] == 'function_call'
                else item['content'][0]['text']) for item in items)
            if output_tokens > output_reserve_tokens:
                raise ValueError('synthetic response exceeds output reserve')
            usage = dict(input_tokens=input_tokens, output_tokens=output_tokens,
                total_tokens=input_tokens+output_tokens, input_tokens_details=dict(cached_tokens=0))
            measured_usage.append(usage)
        return sse(items, len(requests), usage=usage)
    with (directory/'requests.jsonl').open('xb') as log:
        server = create_server(response, log)
        endpoint = f'http://127.0.0.1:{server.server_port}/v1'
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        budget = Budget(wall_seconds=timeout, token_cap=context_token_budget, max_tool_calls=overhead_rounds or 100)
        if single:
            argv = single_command(directory, directory/'schema.json', model=model, budget=budget, binary=binary,
                context_token_budget=context_token_budget, output_reserve_tokens=output_reserve_tokens, model_config=model_config)
        else:
            argv = command(directory, directory, model=model, budget=budget, binary=binary,
                context_token_budget=context_token_budget, output_reserve_tokens=output_reserve_tokens, model_config=model_config)
        settings = provider_settings(endpoint)
        if check == 'rollout_budget_stop': rollout_budget = 90
        if rollout_budget is not None:
            settings.update({'features.rollout_budget': None})
            for key, value in dict(enabled=True, limit_tokens=rollout_budget, sampling_token_weight=1.0,
                    prefill_token_weight=1.0, reminder_at_remaining_tokens=[]).items():
                settings['features.rollout_budget.'+key] = value
        if not single:
            if version.startswith('fake-codex'):
                settings['mcp_servers.harness_v6.env.V6_FAKE_PROBE'] = '1'
            settings.update({'mcp_servers.harness_v6.command': sys.executable,
                'mcp_servers.harness_v6.args': [str(Path(__file__).resolve()), '--probe-mcp', check, '--output', str(directory)],
                'mcp_servers.harness_v6.env.PYTHONPATH': os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p),
                'mcp_servers.harness_v6.env.V6_PROBE_SENTINEL': SENTINEL,
                'mcp_servers.harness_v6.startup_timeout_sec': 1 if check == 'startup_timeout' else 5,
                'mcp_servers.harness_v6.tool_timeout_sec': 1 if check == 'tool_timeout' else 5})
        if check == 'compaction_detection':
            settings.update(model_auto_compact_token_limit=1, compact_prompt=COMPACTION_SENTINEL)
        argv = configure(argv, settings)
        if rollout_budget is not None:
            i = argv.index('features.rollout_budget=null'); del argv[i-1:i+1]
        if check == 'schema_with_mcp': argv[-1:-1] = ['--output-schema', str(directory/'schema.json')]
        runner = CodexRunner(binary, workdir=directory, env_allowlist=['PATH','PYTHONPATH'], stderr_path=directory/'stderr.log')
        argv[0] = runner.binary
        runner.env['PYTHONPATH'] = os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p)
        # Keep mock runs independent of the user's credentials, configuration and plugins.
        for variable, child in (('HOME', 'home'), ('CODEX_HOME', 'codex-home')):
            isolated = directory / child
            isolated.mkdir()
            runner.env[variable] = str(isolated)
        runner.env['V6_FORBIDDEN_SENTINEL'] = 'must-not-reach-mcp'
        try:
            runner.version(version)
            result = runner.run(argv, prompt, timeout=timeout)
        finally:
            server.shutdown(); thread.join(timeout=2); server.server_close()
    (directory/'session.jsonl').write_text(result.jsonl)
    (directory/'prompt.txt').write_text(prompt)
    parsed = parse(result.jsonl) if single else classify(result.jsonl)
    evidence = json.loads((directory/'mcp-received.json').read_text()) if (directory/'mcp-received.json').exists() else None
    healthy = not result.timed_out and result.returncode == 0
    passed = healthy and bool(requests) and not parsed['errors']
    reason = 'schema output and usage, or completed MCP call with matching recorded arguments'
    if single:
        passed &= len(requests) == 1 and not request_tools(requests[0])
        if check == 'single_tool_rejection':
            if version.startswith('fake-codex'):
                passed = healthy and len(requests) == 1 and any(e.startswith('forbidden_item:') for e in parsed['errors'])
            else:
                passed = result.timed_out and result.returncode != 0 and 1 <= len(requests) <= 20 and 'usage_unknown' in parsed['errors']
            reason = 'wall-clock guard stops unsupported-call loop; failed session with unknown usage'
        else:
            passed &= parsed['arguments'] == ACTION
            if check == 'single_usage':
                expected_usage = dict(input_tokens=100, cached_input_tokens=20, output_tokens=10)
                usage = parsed['usage'] or {}
                extras = {'cache_write_input_tokens','reasoning_output_tokens'}
                passed &= (all(usage.get(k)==v for k,v in expected_usage.items())
                    and set(usage) <= set(expected_usage)|extras
                    and all(usage.get(k,0)==0 for k in extras))
    elif check == 'over_limit_harness' or check.startswith('resource_'):
        expected_count = 2 if check == 'over_limit_harness' else 1
        passed = (result.timed_out and result.returncode != 0 and len(requests) == expected_count
            and (directory/'abort.json').exists() and 'usage_unknown' in parsed['errors'])
        if check == 'over_limit_harness':
            records = [json.loads(line) for line in (directory/'mcp.jsonl').read_text().splitlines()]
            passed &= len(records) == 1 and not records[0]['result'].get('isError')
        reason = 'server abort marker blocks reply; host kills group before any extra request'
    elif check == 'rollout_budget_stop':
        passed = (result.returncode != 0 and not result.timed_out and len(requests) == 1
            and 'usage_unknown' in parsed['errors'] and 'shared rollout token budget exhausted' in result.jsonl)
        reason = 'official rollout budget stops after first 90 weighted tokens; diagnostic only'
    elif check in ('startup_timeout', 'tool_timeout'):
        # A host deadline is NOT proof that Codex honored its configured timeout.
        raw = result.jsonl + (directory/'stderr.log').read_text()
        request_gate = bool(requests)
        if check == 'startup_timeout' and not version.startswith('fake-codex'):
            request_gate = not requests and result.returncode != 0
        passed = (not result.timed_out and request_gate and evidence is None
                  and result.wall_seconds < 4
                  and bool(re.search(r'(harness_v6|initialize|tools/call).{0,200}(timed out|timeout)', raw, re.I|re.S))
                  and (directory/'mcp-start.json').exists()
                  and ((directory/'tool-start.json').exists() == (check == 'tool_timeout')))
        reason = ('required MCP startup timeout aborts before any model request' if check == 'startup_timeout'
            else 'configured MCP tool timeout before host deadline; no successful tool result')
    elif check == 'compaction_detection':
        passed = healthy and bool(requests) and 'compaction' in parsed['errors'] and 'mcp_failed' not in parsed['errors']
        if not version.startswith('fake-codex'):
            passed &= bool(compaction_requests)
        reason = 'actual Codex compaction event recognized by classifier'
    else:
        passed &= evidence is not None and parsed['calls'] == [dict(tool='read_entities', arguments={})]
        started = [e.get('item') for e in map(json.loads, result.jsonl.splitlines()) if e.get('type') == 'item.started'] if 'malformed_jsonl' not in parsed['errors'] else []
        passed &= any(i.get('type') == 'mcp_tool_call' and i.get('server') == 'harness_v6' and i.get('tool') == 'read_entities' and i.get('arguments') in ({}, '{}') for i in started)
        if evidence:
            passed &= evidence['marker'] == SENTINEL and evidence['inherited'] is None
            passed &= probe_call_matches(evidence['arguments'], {})
        if check == 'large_result_complete':
            received = [unpack_result(o) for body in requests[1:] for o in outputs(body)]
            expected = dict(marker=SENTINEL, inherited=None, payload='0123456789abcdef'*16384)
            passed &= expected in received
            write(directory/'received_result.json', received[0] if received else None)
    if forbidden_with_mcp:
        passed = (result.returncode != 0 and result.timed_out and 2 <= len(requests) <= 20
            and parsed['calls'] == [dict(tool='read_entities', arguments={})]
            and 'usage_unknown' in parsed['errors'])
        reason = 'one allowed MCP read followed by unsupported-call loop stopped by wall-clock guard'
    if overhead_rounds is not None:
        passed = healthy and not parsed['errors'] and len(requests) == (1 if single else overhead_rounds+1)
        if counter is not None:
            for key in ('input_tokens', 'output_tokens'):
                passed &= (parsed['usage'] or {}).get(key) == sum(u[key] for u in measured_usage)
    row = dict(passed=bool(passed), command=argv, expected=reason, jsonl='session.jsonl',
               request_count=len(requests), requests='requests.jsonl', schema='schema.json', expected_arguments=ACTION,
               errors=parsed['errors'], returncode=result.returncode, timed_out=result.timed_out)
    if counter is not None:
        row['usage_basis'] = 'synthetic conservative full serialized request counts; cached=0; not provider billing'
        row['synthetic_request_usage'] = measured_usage
        row['native_cumulative_usage'] = parsed['usage']
        row['complete_tool_output_occurrences'] = sum(len(outputs(body)) for body in requests)
    if check == 'single_tool_rejection': row['forbidden_tool'] = forbidden_name
    if check == 'compaction_detection': row['compaction_request_numbers'] = compaction_requests
    if check == 'large_result_complete':
        row.update(received_result='received_result.json', sent_result_sha256=digest(dict(marker=SENTINEL, inherited=None, payload='0123456789abcdef'*16384)))
    write(directory/'check.json', row)
    return endpoint, row


def run(binary, version, output, checks=CHECKS, *, model='gpt-5.4', model_config=None, context_token_budget=1000000, output_reserve_tokens=10000):
    root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=False)
    manifest = dict(endpoint='', real_model_requests=0, codex_version=version, model=model, model_config=model_config,
        context_token_budget=context_token_budget, output_reserve_tokens=output_reserve_tokens, checks={},
        wire_status='Unverified until all checks pass against this exact pinned binary',
        mechanism_only=version.startswith('fake-codex'))
    for check in checks:
        endpoint, row = capture(binary, version, root/check, check, model=model, model_config=model_config,
            context_token_budget=context_token_budget, output_reserve_tokens=output_reserve_tokens)
        for key in ('jsonl','requests','schema','received_result'):
            if key in row: row[key] = check+'/'+row[key]
        manifest['checks'][check] = row; manifest['endpoint'] = endpoint
        binary_sha256 = hashlib.sha256(Path(row['command'][0]).read_bytes()).hexdigest()
        if manifest.get('binary_sha256') not in (None, binary_sha256):
            raise ValueError('Codex binary changed between probe checks')
        manifest['binary_sha256'] = binary_sha256
        row['artifact_sha256'] = {key: hashlib.sha256((root/row[key]).read_bytes()).hexdigest()
            for key in ('jsonl','requests','schema','received_result') if key in row}
        write(root/'manifest.json', manifest)
        print(check, 'PASS' if row['passed'] else 'FAIL: inspect JSONL, stderr and recorded requests', flush=True)
    if {'config_injection', 'rollout_budget_stop'} <= set(manifest['checks']):
        def first_body(check):
            record = json.loads((root/check/'requests.jsonl').read_text().splitlines()[0])
            return json.loads(record['body'])
        def without_ids(value):
            if isinstance(value, dict): return {k:without_ids(v) for k,v in value.items() if k != 'id'}
            if isinstance(value, list): return [without_ids(v) for v in value]
            return value
        baseline = without_ids(first_body('config_injection'))
        enabled = without_ids(first_body('rollout_budget_stop'))
        diff = ''.join(difflib.unified_diff(
            json.dumps(baseline, indent=2, sort_keys=True).splitlines(True),
            json.dumps(enabled, indent=2, sort_keys=True).splitlines(True),
            fromfile='budget-off', tofile='budget-on-empty-reminders'))
        (root/'rollout-budget.diff').write_text(diff)
        manifest['rollout_budget_evidence'] = dict(enabled_in_production=False,
            input_equal=baseline.get('input') == enabled.get('input'),
            diff='rollout-budget.diff', normalization='remove message ids only',
            reason='empty reminder thresholds still inject initial rollout_budget developer input')
        write(root/'manifest.json', manifest)
    if not all(row['passed'] for row in manifest['checks'].values()):
        raise ValueError('probe failure: pinned Codex flags/Responses wire/capability unverified; do not proceed to live runs')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-binary'); parser.add_argument('--codex-version')
    parser.add_argument('--model', default='gpt-5.4', help='Local mock model metadata label; never calls that model')
    parser.add_argument('--model-config', help='Frozen model catalog/hash/reasoning JSON')
    parser.add_argument('--context-token-budget', type=int, default=1000000)
    parser.add_argument('--output-reserve-tokens', type=int, default=10000)
    parser.add_argument('--output', required=True); parser.add_argument('--probe-mcp', choices=CHECKS)
    args = parser.parse_args()
    if args.probe_mcp: mcp(args.probe_mcp, Path(args.output)); return
    if not args.codex_binary or not args.codex_version: parser.error('--codex-binary and --codex-version required')
    from harness_v6.model_config import load as load_model_config
    run(args.codex_binary, args.codex_version, args.output, model=args.model,
        model_config=load_model_config(args.model_config), context_token_budget=args.context_token_budget,
        output_reserve_tokens=args.output_reserve_tokens)

if __name__ == '__main__': main()
