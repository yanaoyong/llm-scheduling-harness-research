"""Official-release policy and host guard regressions; no real model calls."""
import hashlib
import json
from pathlib import Path
import pytest
from harness_v6.session import classify, Budget
from harness_v6.mcp_server import CycleServer
from harness_v6.tool_contract import declared_tools, RESOURCE_TOOLS
from test_phase_p import module
from test_mcp_session import setup_cycle


def test_frozen_catalog_has_only_requested_row_and_six_edits(tmp_path):
    script = module('freeze_model_catalog')
    row = dict(slug='target', untouched={'a': 1}, tool_mode='code_mode_only')
    source = tmp_path/'source.json'; output = tmp_path/'frozen.json'
    source.write_text(json.dumps(dict(identity='private', etag='private', models=[row, {'slug':'other'}])))
    sha = script.freeze(source, output, 'target')
    assert json.loads(output.read_bytes()) == {'models': [dict(row, **script.EDITS)]}
    assert sha == hashlib.sha256(output.read_bytes()).hexdigest()
    assert json.loads(source.read_bytes())['models'][0] == row
    with pytest.raises(ValueError, match='exactly one'): script.freeze(source, output, 'missing')
    with pytest.raises(ValueError, match='outside'): script.freeze(source, Path(__file__).parent/'forbidden.json', 'target')


@pytest.mark.parametrize('interaction', ['single_action', 'mcp_session'])
def test_exact_official_compaction_item(interaction):
    def errors(message):
        return classify(json.dumps(dict(type='item.completed', item=dict(type='error', message=message))), interaction=interaction)['errors']
    assert 'compaction' in errors('Heads up: Long threads and multiple compactions can cause the model to be less accurate.')
    for message in ('other error', 'prefix Heads up: Long threads and multiple compactions', None):
        actual = errors(message)
        assert 'compaction' not in actual and 'forbidden_item:error' in actual


@pytest.mark.parametrize('method', ['resources/read','resources/list','resources/templates/list','resources/unknown'])
def test_resource_methods_abort_without_response(tmp_path, monkeypatch, method):
    server, _ = setup_cycle(tmp_path)
    class Blocked(BaseException): pass
    def blocked(_, timeout): raise Blocked()
    monkeypatch.setattr('threading.Event.wait', blocked)
    with pytest.raises(Blocked): server.rpc(dict(jsonrpc='2.0', id=1, method=method))
    assert json.loads((server.output_dir/'abort.json').read_bytes()) == dict(reason='resource_method', method=method, count=0)
    assert server.records == []
    server.close()


def test_over_limit_blocks_before_record_or_reply(tmp_path, monkeypatch):
    server, _ = setup_cycle(tmp_path); server.max_tool_calls = 1
    server.call('read_entities', dict(kind='operations'))
    class Blocked(BaseException): pass
    def blocked(_, timeout): raise Blocked()
    monkeypatch.setattr('threading.Event.wait', blocked)
    with pytest.raises(Blocked): server.call('read_entities', dict(kind='operations'))
    assert len(server.records) == 1
    assert json.loads((server.output_dir/'abort.json').read_bytes()) == dict(reason='tool_budget', method='tools/call', count=2)
    server.close()


def test_host_marker_kills_group_and_never_adopts(tmp_path, monkeypatch):
    from harness_v6.synthetic import SyntheticRun
    from harness_v6.live import LiveRun
    from test_codex_runner import runner
    run = SyntheticRun(directory=tmp_path/'run', group='P2')
    run.runner = runner(tmp_path, monkeypatch)
    run.budget = Budget(max_tool_calls=1, wall_seconds=10)
    LiveRun.step(run)
    assert not run.outcome['adopted'] and run.outcome['usage_unknown']
    assert 'process_failed' in run.outcome['errors']
    assert (run.directory/'cycle-1/output/abort.json').exists()


def test_resource_names_are_only_top_level_and_unique():
    tools = [dict(type='function', name=name, parameters={'type':'object'}) for name in RESOURCE_TOOLS]
    assert set(declared_tools(tools)) == RESOURCE_TOOLS
    with pytest.raises(ValueError): declared_tools(tools + tools[:1])
    with pytest.raises(ValueError): declared_tools([dict(type='namespace', name='mcp__harness_v6', tools=tools)])


def test_resource_schema_tokens_count_as_overhead():
    measure = module('measure_request_overhead')
    body = dict(input='SNAPSHOT', tools=[dict(type='function', name=name, parameters={'type':'object'}) for name in RESOURCE_TOOLS])
    row = measure.analyze([dict(path='/v1/responses', body=body)], 'SNAPSHOT', len)['rounds'][0]
    assert row['tool_schema_tokens'] > 0
    assert row['non_snapshot_input_tokens'] >= row['tool_schema_tokens']


def test_official_tool_contract_requires_all_six_or_zero():
    from harness_v6.tool_contract import request_tools
    from harness_v6.mcp_server import TOOLS
    harness = dict(type='namespace', name='mcp__harness_v6', tools=[
        dict(type='function', name=name, parameters=schema) for name,schema in TOOLS.items()])
    tools = [harness] + [dict(type='function', name=name, parameters={'type':'object'}) for name in RESOURCE_TOOLS]
    assert request_tools({'tools':tools}, interaction='mcp_session') == tools
    assert request_tools({'tools':[]}, interaction='single_action') == []
    for invalid in (tools[:-1], tools+tools[-1:], [], tools+[dict(type='function', name='exec', parameters={})]):
        with pytest.raises(ValueError): request_tools({'tools':invalid}, interaction='mcp_session')
    with pytest.raises(ValueError): request_tools({'tools':tools}, interaction='single_action')
    flat = [dict(child, name='mcp__harness_v6__'+child['name']) for child in harness['tools']] + tools[1:]
    with pytest.raises(ValueError): request_tools({'tools':flat}, interaction='mcp_session')
    split = [dict(harness, tools=harness['tools'][:1]), dict(harness, tools=harness['tools'][1:])] + tools[1:]
    with pytest.raises(ValueError): request_tools({'tools':split}, interaction='mcp_session')


def test_completed_usage_survives_host_failure_but_never_adopts(tmp_path):
    from harness_v6.single_action import finish
    from harness_v6.session import RunResult
    from harness_v6.metrics import Metrics
    server, _ = setup_cycle(tmp_path)
    usage = dict(input_tokens=100, cached_input_tokens=20, output_tokens=10)
    result = RunResult(json.dumps(dict(type='turn.completed', usage=usage)), returncode=-9, timed_out=True)
    outcome = finish(result, submitter=server.submitter, commit=lambda *args: pytest.fail('must not adopt'), metrics=Metrics(), now=0)
    assert not outcome['usage_unknown'] and not outcome['adopted'] and 'process_failed' in outcome['errors']
    server.close()
