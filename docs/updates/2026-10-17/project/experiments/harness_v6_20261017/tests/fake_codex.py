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
    action = prompt_action(sys.stdin.read())
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
