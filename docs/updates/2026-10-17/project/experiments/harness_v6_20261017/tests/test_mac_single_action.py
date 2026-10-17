"""Archived Mac local-mock probes only; never launches Codex or reads sealed data."""
import os
from pathlib import Path
import pytest
from harness_v6.contracts import strict_json
from harness_v6.single_action import parse, OUTPUT_SCHEMA

@pytest.mark.parametrize('check', ['single_schema_no_mcp', 'single_tool_rejection', 'single_usage'])
def test_single_action_f6(check):
    directory = os.environ.get('V6_SINGLE_ACTION_PROBE_DIR')
    if not directory:
        pytest.skip('Mac-only pinned Codex local mock probe missing: V6_SINGLE_ACTION_PROBE_DIR')
    root = Path(directory)
    manifest = strict_json((root / 'manifest.json').read_bytes())
    assert manifest['endpoint'].startswith('http://127.0.0.1:')
    assert manifest['real_model_requests'] == 0 and manifest['codex_version']
    row = manifest['checks'][check]
    assert row['passed'] is True and row['expected']
    argv = row['command']
    assert isinstance(argv, list)
    assert all(arg in argv for arg in ('--output-schema', '--ephemeral', '--json', 'mcp_servers={}'))
    assert not any(arg.startswith('mcp_servers.') for arg in argv)
    assert strict_json((root / row['schema']).read_bytes()) == OUTPUT_SCHEMA
    parsed = parse((root / row['jsonl']).read_text())
    if check == 'single_tool_rejection':
        assert any(e.startswith('forbidden_item:') for e in parsed['errors'])
    else:
        assert not parsed['errors']
        assert parsed['arguments'] == row['expected_arguments']
    requests = [strict_json(line) for line in (root / row['requests']).read_bytes().splitlines()]
    assert len(requests) == 1
    assert not strict_json(requests[0]['body']).get('tools')
