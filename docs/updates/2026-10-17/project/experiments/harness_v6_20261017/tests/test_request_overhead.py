import copy
import importlib.util
import json
from pathlib import Path
import pytest
SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'measure_request_overhead.py'
spec = importlib.util.spec_from_file_location('measure_request_overhead', SCRIPT)
overhead = importlib.util.module_from_spec(spec)
spec.loader.exec_module(overhead)


def records(snapshot='SNAPSHOT\ntext'):
    body = dict(model='pinned', instructions='SYSTEM', input=[dict(role='developer', content='developer'),
        dict(role='user', content=[dict(type='input_text', text='prefix\n' + snapshot + '\nsuffix')])],
        tools=[dict(type='function', name='validate_plan', parameters={'type': 'object'})])
    later = copy.deepcopy(body)
    later['input'] += [dict(type='function_call', call_id='1', name='validate_plan', arguments='{}'),
                       dict(type='function_call_output', call_id='1', output='result' * 50)]
    return [dict(path='/v1/responses', body=json.dumps(body)), dict(path='/responses', body=later)]


def test_multi_round_partition_and_budget_boundary():
    snapshot = 'SNAPSHOT\ntext'
    result = overhead.analyze(records(), snapshot, len)
    a, b = result['rounds']
    assert b['growth_from_first_round'] > 0
    assert b['growth_from_previous_round'] == b['non_snapshot_input_tokens'] - a['non_snapshot_input_tokens']
    assert result['request_overhead_tokens'] == b['non_snapshot_input_tokens']
    assert a['snapshot_tokens'] == len(snapshot)
    assert a['instructions_system_tokens'] > len('SYSTEM')
    assert a['tool_schema_tokens'] > len('validate_plan')
    logs = {'explicit': records(), 'dense': records('DENSE')}
    snapshots = {'explicit': snapshot, 'dense': 'DENSE'}
    report = overhead.measure(logs, snapshots, len, context_token_budget=100000, output_reserve_tokens=50)
    boundary = max(v['budget_check']['required_tokens'] for v in report['formats'].values())
    assert overhead.measure(logs, snapshots, len, context_token_budget=boundary, output_reserve_tokens=50)['passed']
    assert not overhead.measure(logs, snapshots, len, context_token_budget=boundary-1, output_reserve_tokens=50)['passed']


@pytest.mark.parametrize('body,field', [({}, 'input'), ({'input': 123}, 'input'),
    ({'input': [{'role': 'user'}]}, 'content'),
    ({'input': [{'role': 'user', 'content': [{'type': 'input_image'}]}]}, 'type'),
    ({'input': [{'type': 'function_call_output', 'call_id': 'a'}]}, 'output'),
    ({'input': [{'type': 'unknown'}]}, 'type'),
    ({'input': 'snap', 'previous_response_id': 'id'}, 'previous_response_id'),
    ({'input': 'snap', 'tools': [{'type': 'function', 'name': 'x'}]}, 'parameters'),
    ({'input': 'snap', 'instructions': {}}, 'instructions'),
    ({'input': 'no matching payload'}, 'snapshot'), ({'input': 'snap snap'}, 'snapshot'),
    ({'input': [{'type': 'reasoning', 'summary': [], 'encrypted_content': 'opaque'}]}, 'encrypted_content')])
def test_unknown_shapes_fail_explicitly(body, field):
    with pytest.raises(ValueError, match=field):
        overhead.analyze([dict(path='/responses', body=body)], 'snap', len)


def test_string_input_and_reasoning_summary():
    assert overhead.analyze([dict(path='/responses', body={'input': 'snap'})], 'snap', len)['request_count'] == 1
    rec = records()
    rec[1]['body']['input'].append(dict(type='reasoning', summary=[dict(type='summary_text', text='reason')]))
    assert overhead.analyze(rec, 'SNAPSHOT\ntext', len)['request_count'] == 2
    with pytest.raises(ValueError, match='empty'): overhead.analyze([], 'snap', len)


def test_complete_native_tool_text_array_is_fully_counted():
    rec=records()
    output=[dict(type='input_text',text='Wall time: 0.0012 seconds\nOutput:'),
            dict(type='input_text',text='complete-result'*1000)]
    rec[1]['body']['input'][-1]['output']=output
    row=overhead.analyze(rec,'SNAPSHOT\ntext',len)['rounds'][-1]
    assert row['conservative_input_tokens']>=len(overhead.canonical(rec[1]['body']).decode())
    for bad in ([],[dict(type='input_image',image_url='opaque')],
                [dict(type='input_text',text='partial',unknown='opaque')]):
        rec[1]['body']['input'][-1]['output']=bad
        with pytest.raises(ValueError,match='output'):
            overhead.analyze(rec,'SNAPSHOT\ntext',len)


def test_namespaced_tool_cost_and_foreign_rejection():
    body = json.loads(records()[0]['body'])
    body['tools'] = [dict(type='namespace', name='mcp__harness_v6', description='Harness',
        tools=body['tools'])]
    report = overhead.analyze([dict(path='/responses', body=body)], 'SNAPSHOT\ntext', len)
    assert report['rounds'][0]['tool_schema_tokens'] == len(overhead.canonical(body['tools']).decode())
    body['tools'].append(dict(type='custom', name='apply_patch'))
    with pytest.raises(ValueError, match='tools'):
        overhead.analyze([dict(path='/responses', body=body)], 'SNAPSHOT\ntext', len)


def test_lite_tools_are_counted_and_checked_inside_input():
    body = json.loads(records()[0]['body'])
    block = dict(type='additional_tools', role='developer', tools=body.pop('tools'))
    body['input'].insert(0, block)
    report = overhead.analyze([dict(path='/responses', body=body)], 'SNAPSHOT\ntext', len)
    row = report['rounds'][0]
    assert row['tool_schema_tokens'] == len(overhead.canonical([block]).decode())
    assert row['conservative_input_tokens'] >= len(overhead.canonical(body).decode())
    body['tools'] = []
    with pytest.raises(ValueError, match='ambiguous'):
        overhead.analyze([dict(path='/responses', body=body)], 'SNAPSHOT\ntext', len)
    del body['tools']
    block['tools'].append(dict(type='function', name='apply_patch', parameters={}))
    with pytest.raises(ValueError, match='unexpected'):
        overhead.analyze([dict(path='/responses', body=body)], 'SNAPSHOT\ntext', len)


@pytest.mark.parametrize('budget,expected_exit',[(1,1),(100000,0)])
def test_cli_budget_status_matches_report(tmp_path,monkeypatch,budget,expected_exit):
    import sys
    argv=['measure','--context-token-budget',str(budget),'--output-reserve-tokens','50',
          '--output',str(tmp_path/'report.json')]
    for fmt in ('explicit','dense'):
        snapshot=tmp_path/(fmt+'.txt');snapshot.write_text('SNAPSHOT\ntext')
        log=tmp_path/(fmt+'.jsonl')
        log.write_text('\n'.join(json.dumps(row) for row in records())+'\n')
        argv+=['--snapshot',fmt+'='+str(snapshot),'--requests',fmt+'='+str(log)]
    monkeypatch.setattr(sys,'argv',argv)
    monkeypatch.setattr(overhead,'tiktoken_counter',lambda *a:len)
    monkeypatch.setattr(overhead.importlib.metadata,'version',lambda *a:'test')
    assert overhead.main()==expected_exit
    assert json.loads((tmp_path/'report.json').read_text())['passed']==(expected_exit==0)
