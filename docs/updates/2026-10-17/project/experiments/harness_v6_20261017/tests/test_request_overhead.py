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
