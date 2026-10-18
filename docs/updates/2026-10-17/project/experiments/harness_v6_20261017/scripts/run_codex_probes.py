#!/usr/bin/env python3
"""Pinned-Codex loopback-only capability recordings. Wire assumptions fail closed."""
import argparse
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

CHECKS = ('config_injection', 'approval_never', 'schema_with_mcp', 'jsonl_fields',
          'startup_timeout', 'tool_timeout', 'compaction_detection',
          'environment_inheritance', 'large_result_complete',
          'single_schema_no_mcp', 'single_tool_rejection', 'single_usage')
ACTION = dict(expected_state_version=1, submission_id='probe', delta={})
SENTINEL = 'v6-explicit-environment'


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


def sse(items, number):
    response = dict(id=f'resp_{number}', object='response', status='completed', output=items,
        usage=dict(input_tokens=100, output_tokens=10, total_tokens=110,
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
    if overhead:
        from harness_v6.mcp_server import TOOLS, TOOL_DESCRIPTIONS
    if check == 'startup_timeout': time.sleep(4)
    for line in sys.stdin:
        request = json.loads(line)
        if 'id' not in request: continue
        method = request['method']
        if method == 'initialize':
            result = dict(protocolVersion='2024-11-05', capabilities=dict(tools={}),
                          serverInfo=dict(name='harness_v6', version='probe'))
        elif method == 'tools/list':
            result = dict(tools=[dict(name='read_entities', description='Return probe data',
                inputSchema=dict(type='object', properties={}, additionalProperties=False))])
            if overhead:
                result = dict(tools=[dict(name=k, description=TOOL_DESCRIPTIONS[k], inputSchema=v) for k,v in TOOLS.items()])
        elif method == 'tools/call':
            write(directory/'tool-start.json', request['params'])
            if check == 'tool_timeout': time.sleep(4)
            payload = result_payload(check)
            if overhead:
                from harness_v6.compact import decode_snapshot
                payload = decode_snapshot((directory/'snapshot.txt').read_bytes())[1]
            result = dict(content=[dict(type='text', text=json.dumps(payload))])
            write(directory/'mcp-received.json', dict(arguments=request['params'], result=result,
                  marker=os.environ.get('V6_PROBE_SENTINEL'), inherited=os.environ.get('V6_FORBIDDEN_SENTINEL')))
        else: raise ValueError('unsupported MCP method '+method)
        print(json.dumps(dict(jsonrpc='2.0', id=request['id'], result=result)), flush=True)


def outputs(body):
    return [item.get('output') for item in body.get('input', [])
            if isinstance(item, dict) and item.get('type') == 'function_call_output']


def unpack_result(value):
    if isinstance(value, str):
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


def capture(binary, version, directory, check, *, prompt='Return the scripted probe response.', model='probe-model', timeout=15, overhead_rounds=None, context_token_budget=1000000, output_reserve_tokens=10000):
    directory = Path(directory).resolve(); directory.mkdir(parents=True, exist_ok=False)
    single = check.startswith('single_')
    write(directory/'schema.json', OUTPUT_SCHEMA)
    if overhead_rounds is not None:
        if overhead_rounds < 1: raise ValueError('capture rounds must be positive')
        write(directory/'overhead.json', dict(rounds=overhead_rounds))
        (directory/'snapshot.txt').write_text(prompt)
    requests = []
    def response(body):
        requests.append(body)
        tools = body.get('tools', [])
        if single and tools:
            raise ValueError('single_action unexpectedly exposes tools')
        if not single and len(requests) <= (overhead_rounds or 1):
            names = [t.get('name', t.get('function', {}).get('name', '')) for t in tools]
            name = next((n for n in names if n.endswith('read_entities')), None)
            if any(n != name for n in names) and overhead_rounds is None:
                raise ValueError('unexpected native/foreign tools advertised')
            if name is None: raise ValueError('unverified wire: read_entities tool absent')
            items = [dict(type='function_call', id='fc_probe_'+str(len(requests)), call_id='call_probe_'+str(len(requests)), name=name,
                          arguments=json.dumps({'kind':'operations'} if overhead_rounds else {}), status='completed')]
        elif check == 'single_tool_rejection':
            items = [dict(type='function_call', id='fc_forbidden', call_id='call_forbidden',
                          name='unadvertised_forbidden_tool', arguments='{}', status='completed')]
        else:
            items = [dict(type='message', id='msg_probe', role='assistant', status='completed',
                          content=[dict(type='output_text', text=json.dumps(ACTION), annotations=[])])]
        if len(requests) > (overhead_rounds or 1)+3: raise ValueError('unverified wire: unexpected extra model round')
        return sse(items, len(requests))
    with (directory/'requests.jsonl').open('xb') as log:
        server = create_server(response, log)
        endpoint = f'http://127.0.0.1:{server.server_port}/v1'
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        budget = Budget(wall_seconds=timeout, token_cap=context_token_budget)
        if single:
            argv = single_command(directory, directory/'schema.json', model=model, budget=budget, binary=binary)
        else:
            argv = command(directory, directory, model=model, budget=budget, binary=binary)
        settings = provider_settings(endpoint)
        settings['model_max_output_tokens'] = output_reserve_tokens
        if not single:
            settings.update({'mcp_servers.harness_v6.command': sys.executable,
                'mcp_servers.harness_v6.args': [str(Path(__file__).resolve()), '--probe-mcp', check, '--output', str(directory)],
                'mcp_servers.harness_v6.env.PYTHONPATH': os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p),
                'mcp_servers.harness_v6.env.V6_PROBE_SENTINEL': SENTINEL,
                'mcp_servers.harness_v6.startup_timeout_sec': 1 if check == 'startup_timeout' else 5,
                'mcp_servers.harness_v6.tool_timeout_sec': 1 if check == 'tool_timeout' else 5})
        if check == 'compaction_detection': settings['model_auto_compact_token_limit'] = 1
        argv = configure(argv, settings)
        if check == 'schema_with_mcp': argv[-1:-1] = ['--output-schema', str(directory/'schema.json')]
        runner = CodexRunner(binary, workdir=directory, env_allowlist=['PATH','PYTHONPATH'], stderr_path=directory/'stderr.log')
        argv[0] = runner.binary
        runner.env['PYTHONPATH'] = os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p)
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
        passed &= len(requests) == 1 and not requests[0].get('tools')
        if check == 'single_tool_rejection':
            passed = healthy and len(requests) == 1 and any(e.startswith('forbidden_item:') for e in parsed['errors'])
        else:
            passed &= parsed['arguments'] == ACTION
            if check == 'single_usage':
                passed &= parsed['usage'] == dict(input_tokens=100, cached_input_tokens=20, output_tokens=10)
    elif check in ('startup_timeout', 'tool_timeout'):
        # A host deadline is NOT proof that Codex honored its configured timeout.
        raw = result.jsonl + (directory/'stderr.log').read_text()
        passed = (not result.timed_out and bool(requests) and evidence is None
                  and result.wall_seconds < 4
                  and bool(re.search(r'(harness_v6|initialize|tools/call).{0,200}(timed out|timeout)', raw, re.I|re.S))
                  and (directory/'mcp-start.json').exists()
                  and ((directory/'tool-start.json').exists() == (check == 'tool_timeout')))
        reason = 'configured MCP timeout before host deadline; no successful tool result'
    elif check == 'compaction_detection':
        passed = healthy and bool(requests) and 'compaction' in parsed['errors']
        reason = 'actual Codex compaction event recognized by classifier'
    else:
        passed &= evidence is not None and parsed['calls'] == [dict(tool='read_entities', arguments={})]
        started = [e.get('item') for e in map(json.loads, result.jsonl.splitlines()) if e.get('type') == 'item.started'] if 'malformed_jsonl' not in parsed['errors'] else []
        passed &= any(i.get('type') == 'mcp_tool_call' and i.get('server') == 'harness_v6' and i.get('tool') == 'read_entities' and i.get('arguments') in ({}, '{}') for i in started)
        if evidence:
            passed &= evidence['marker'] == SENTINEL and evidence['inherited'] is None
            passed &= evidence['arguments'] == dict(name='read_entities', arguments={})
        if check == 'large_result_complete':
            received = [unpack_result(o) for body in requests[1:] for o in outputs(body)]
            expected = dict(marker=SENTINEL, inherited=None, payload='0123456789abcdef'*16384)
            passed &= expected in received
            write(directory/'received_result.json', received[0] if received else None)
    if overhead_rounds is not None:
        passed = healthy and not parsed['errors'] and len(requests) == (1 if single else overhead_rounds+1)
    row = dict(passed=bool(passed), command=argv, expected=reason, jsonl='session.jsonl',
               requests='requests.jsonl', schema='schema.json', expected_arguments=ACTION,
               errors=parsed['errors'], returncode=result.returncode, timed_out=result.timed_out)
    if check == 'large_result_complete':
        row.update(received_result='received_result.json', sent_result_sha256=digest(dict(marker=SENTINEL, inherited=None, payload='0123456789abcdef'*16384)))
    write(directory/'check.json', row)
    return endpoint, row


def run(binary, version, output, checks=CHECKS):
    root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=False)
    manifest = dict(endpoint='', real_model_requests=0, codex_version=version, checks={},
        wire_status='Unverified until all checks pass against this exact pinned binary',
        mechanism_only=version.startswith('fake-codex'))
    for check in checks:
        endpoint, row = capture(binary, version, root/check, check)
        for key in ('jsonl','requests','schema','received_result'):
            if key in row: row[key] = check+'/'+row[key]
        manifest['checks'][check] = row; manifest['endpoint'] = endpoint
        write(root/'manifest.json', manifest)
        print(check, 'PASS' if row['passed'] else 'FAIL: inspect JSONL, stderr and recorded requests', flush=True)
    if not all(row['passed'] for row in manifest['checks'].values()):
        raise ValueError('probe failure: pinned Codex flags/Responses wire/capability unverified; do not proceed to live runs')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-binary'); parser.add_argument('--codex-version')
    parser.add_argument('--output', required=True); parser.add_argument('--probe-mcp', choices=CHECKS)
    args = parser.parse_args()
    if args.probe_mcp: mcp(args.probe_mcp, Path(args.output)); return
    if not args.codex_binary or not args.codex_version: parser.error('--codex-binary and --codex-version required')
    run(args.codex_binary, args.codex_version, args.output)

if __name__ == '__main__': main()
