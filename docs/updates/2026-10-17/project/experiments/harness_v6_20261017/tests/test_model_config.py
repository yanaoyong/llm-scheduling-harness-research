"""No model fallback, unsupported window, or checkpoint configuration drift."""
import hashlib
import json
import pytest
from harness_v6.model_config import settings, admission_limit
from harness_v6.session import command
from harness_v6.single_action import command as single_command
from harness_v6.synthetic import SyntheticRun


@pytest.fixture
def pinned(tmp_path):
    path = tmp_path/'catalog.json'
    path.write_text(json.dumps({'models': [{'slug': 'gpt-6-astra', 'context_window': 272000,
        'max_context_window': 872000, 'supported_reasoning_levels': [{'effort': 'medium'}]}]}))
    return dict(model_catalog_json=str(path), model_catalog_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                reasoning_effort='medium')


@pytest.mark.parametrize('single', [False, True])
def test_both_modes_use_identical_pinned_model_settings(pinned, tmp_path, single):
    argv = (single_command if single else command)(tmp_path, tmp_path/'output', model='gpt-6-astra',
        context_token_budget=872000, output_reserve_tokens=10000, model_config=pinned)
    actual = dict(argv[i+1].split('=', 1) for i, arg in enumerate(argv) if arg == '-c')
    assert json.loads(actual['model_catalog_json']) == pinned['model_catalog_json']
    assert json.loads(actual['model_reasoning_effort']) == 'medium'
    assert actual['model_context_window'] == '872000'
    if single:
        assert actual['mcp_servers'] == '{}'
        assert not any(key.startswith('mcp_servers.') for key in actual)
    else:
        assert actual['mcp_servers.harness_v6.required'] == 'true'


@pytest.mark.parametrize('model,context,change', [
    ('unknown-model', 872000, {}), ('gpt-6-astra', 872001, {}),
    ('gpt-6-astra', True, {}), ('gpt-6-astra', 872000, {'reasoning_effort': 'none'}),
    ('gpt-6-astra', 872000, {'model_catalog_sha256': '0'*64}),
    ('gpt-6-astra', 872000, {'unexpected': 1}),
])
def test_invalid_model_binding_fails_closed(pinned, model, context, change):
    with pytest.raises(ValueError):
        settings(pinned | change, model=model, context_token_budget=context)


def test_catalog_changes_are_checked_on_every_command(pinned, tmp_path):
    command(tmp_path, tmp_path, model='gpt-6-astra', model_config=pinned, context_token_budget=872000)
    from pathlib import Path
    path = Path(pinned['model_catalog_json'])
    path.write_bytes(path.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='SHA256'):
        command(tmp_path, tmp_path, model='gpt-6-astra', model_config=pinned, context_token_budget=872000)


def test_target_model_cannot_silently_use_fallback(tmp_path):
    with pytest.raises(ValueError, match='requires a pinned'):
        command(tmp_path, tmp_path, model='gpt-6-astra', context_token_budget=872000)


def test_admission_respects_native_compaction_not_nominal_window(pinned):
    assert admission_limit(pinned, model='gpt-6-astra', context_token_budget=872000) == 784799
    assert admission_limit(pinned, model='gpt-6-astra', context_token_budget=1000) == 899
    assert admission_limit(None, model='scripted', context_token_budget=1000) == 1000


def test_live_rejects_before_runner_when_only_nominal_window_fits(pinned, tmp_path):
    from harness_v6.live import LiveRun
    from harness_v6.synthetic import SyntheticFactory, SOURCE
    from harness_v6.snapshot import stable_prefix
    class NoRequests:
        def run(self, *args, **kwargs):
            raise AssertionError('request must be rejected before runner invocation')
    run = LiveRun(SyntheticFactory(), NoRequests(), directory=tmp_path/'run',
        prefix=stable_prefix(tool_descriptions=[], routing=[], machine_groups=[]), source_sha256=SOURCE,
        context_token_budget=20000, request_overhead_tokens=18500, output_reserve_tokens=100,
        token_counter=lambda _: 1, model='gpt-6-astra', model_config=pinned)
    run.step()
    assert run.cycle.stop_reason == 'context_budget_exceeded'
    assert run.budget_report['request_context_limit'] == 17999


def test_checkpoint_rejects_model_configuration_drift(tmp_path, pinned):
    run = SyntheticRun(directory=tmp_path/'run')
    run.model_config = dict(pinned)
    run.checkpoint(run.store)
    run.model_config['reasoning_effort'] = 'high'
    with pytest.raises(ValueError, match='model_config mismatch'):
        run.recover()
