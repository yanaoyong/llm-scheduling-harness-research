#!/usr/bin/env python3
"""Offline protocol client, never invokes a model. FAKE_CODEX_MODE injects faults."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from harness_v6.synthetic import prompt_action


def emit(value):
    print(json.dumps(value, sort_keys=True, separators=(',', ':')), flush=True)


def mock_client(settings, prompt):
    """Exercise actual HTTP recording and MCP process I/O; no model inference."""
    import urllib.request
    import selectors
    url = settings['model_providers.v6_mock.base_url']
    assert url.startswith('http://127.0.0.1:')
    key = 'mcp_servers.harness_v6.'
    single = key+'command' not in settings
    body = dict(model='probe-model', instructions='offline fake instructions',
                input=[dict(role='user', content=prompt)], tools=[])
    def request():
        with urllib.request.urlopen(urllib.request.Request(url+'/responses',
                data=json.dumps(body).encode(), headers={'Content-Type':'application/json'}), timeout=10) as response:
            events = [json.loads(line[6:]) for line in response.read().decode().splitlines() if line.startswith('data: ')]
        return events[-1]['response']['output']
    emit(dict(type='thread.started', thread_id='offline-mock'))
    if single:
        items = request()
        if items[0]['type'] == 'function_call':
            emit(dict(type='item.completed', item=dict(type='command_execution', command='never executed')))
        else:
            emit(dict(type='item.completed', item=dict(type='agent_message', text=items[0]['content'][0]['text'])))
    else:
        env = {k: os.environ[k] for k in ('PATH',) if k in os.environ}
        env.update({k[len(key+'env.'):]:v for k,v in settings.items() if k.startswith(key+'env.')})
        server = subprocess.Popen([settings[key+'command'], *settings[key+'args']], env=env,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        def rpc(number, method, params=None, timeout=5):
            server.stdin.write(json.dumps(dict(jsonrpc='2.0', id=number, method=method, params=params or {}))+'\n')
            server.stdin.flush()
            with selectors.DefaultSelector() as selector:
                selector.register(server.stdout, selectors.EVENT_READ)
                if not selector.select(timeout): raise TimeoutError(method+' timed out')
            return json.loads(server.stdout.readline())['result']
        try:
            try:
                rpc(0, 'initialize', timeout=settings[key+'startup_timeout_sec'])
                listing = rpc(1, 'tools/list')
                body['tools'] = [dict(type='function', name='mcp__harness_v6__'+t['name'],
                                     parameters=t['inputSchema'], description=t['description']) for t in listing['tools']]
            except TimeoutError as exc:
                # Startup failures still permit the model request, with no MCP tools.
                body['tools'] = [dict(type='function', name='mcp__harness_v6__read_entities', parameters={})]
                request(); print(str(exc), file=sys.stderr)
                emit(dict(type='turn.failed')); return
            final = request()
            number = 2
            while final[0]['type'] == 'function_call':
                call = final[0]
                item = dict(id=str(number), type='mcp_tool_call', server='harness_v6', tool='read_entities', arguments=json.loads(call['arguments']))
                emit(dict(type='item.started', item=item))
                try:
                    result = rpc(number, 'tools/call', dict(name='read_entities', arguments=item['arguments']), timeout=settings[key+'tool_timeout_sec'])
                except TimeoutError as exc:
                    print(str(exc), file=sys.stderr); emit(dict(type='turn.failed')); return
                emit(dict(type='item.completed', item=dict(item, status='completed', result=result)))
                body['input'] += [call, dict(type='function_call_output', call_id=call['call_id'], output=json.dumps(result))]
                final = request(); number += 1
            if settings.get('model_auto_compact_token_limit') == 1: emit(dict(type='thread.compacted'))
            emit(dict(type='item.completed', item=dict(type='agent_message', text=final[0]['content'][0]['text'])))
        finally:
            server.terminate(); server.wait(timeout=5)
    emit(dict(type='turn.completed', usage=dict(input_tokens=100, cached_input_tokens=20, output_tokens=10)))


def main():
    if '--version' in sys.argv:
        print('fake-codex 1'); return
    mode = os.environ.get('FAKE_CODEX_MODE', '')
    print('fake codex stderr', file=sys.stderr, flush=True)
    if mode == 'hang':
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])
        if os.environ.get('FAKE_CHILD_PID'):
            Path(os.environ['FAKE_CHILD_PID']).write_text(str(child.pid))
        time.sleep(300)
    if mode == 'nonzero':
        sys.exit(17)
    if mode == 'malformed':
        print('not json'); return
    prompt = sys.stdin.read()
    settings = {}
    for i, arg in enumerate(sys.argv):
        if arg == '-c':
            key, value = sys.argv[i+1].split('=', 1)
            settings[key] = json.loads(value)
    if 'model_providers.v6_mock.base_url' in settings:
        mock_client(settings, prompt); return
    if os.environ.get('FAKE_AB_ANSWERS'):
        answers = json.loads(Path(os.environ['FAKE_AB_ANSWERS']).read_text())
        schema = json.loads(Path(sys.argv[sys.argv.index('--output-schema')+1]).read_text())
        action = {k: answers[k] for k in schema['required']}
    else:
        action = prompt_action(prompt)
    emit(dict(type='thread.started', thread_id='offline-fake'))
    if '--output-schema' in sys.argv:
        emit(dict(type='item.completed', item=dict(type='agent_message', text=json.dumps(action))))
    else:
        settings = {}
        for i, arg in enumerate(sys.argv):
            if arg == '-c':
                key, value = sys.argv[i+1].split('=', 1)
                settings[key] = json.loads(value)
        key = 'mcp_servers.harness_v6.'
        env = dict(os.environ)
        env.update({k[len(key+'env.'):]: v for k,v in settings.items() if k.startswith(key+'env.')})
        server = subprocess.Popen([settings[key+'command'], *settings[key+'args']],
            env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        def rpc(number, method, params=None):
            server.stdin.write(json.dumps(dict(jsonrpc='2.0', id=number, method=method, params=params or {}))+'\n')
            server.stdin.flush()
            response = json.loads(server.stdout.readline())
            assert response['id'] == number and 'error' not in response, response
            return response['result']
        try:
            rpc(0, 'initialize', dict(protocolVersion='2024-11-05', capabilities={}, clientInfo=dict(name='fake-codex', version='1')))
            server.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n'); server.stdin.flush()
            assert len(rpc(1, 'tools/list')['tools']) == 3
            for number, tool in enumerate(('validate_plan', 'submit_plan'), 2):
                item = dict(id=str(number), type='mcp_tool_call', server='harness_v6', tool=tool, arguments=action)
                emit(dict(type='item.started', item=item))
                response = rpc(number, 'tools/call', dict(name=tool, arguments=action))
                emit(dict(type='item.completed', item=dict(item, status='completed', result=response)))
        finally:
            server.stdin.close(); server.wait(timeout=10)
        emit(dict(type='item.completed', item=dict(type='agent_message', text='Submitted offline scripted plan.')))
    if mode == 'forbidden':
        emit(dict(type='item.completed', item=dict(type='command_execution', command='forbidden-test')))
    if mode == 'crash_after_submit':
        sys.exit(18)
    emit(dict(type='turn.completed', **({} if mode == 'missing_usage' else
        dict(usage=dict(input_tokens=100, cached_input_tokens=20, output_tokens=10)))))


if __name__ == '__main__':
    main()
