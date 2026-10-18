"""Shared archived-probe checks; content checks also support offline fixtures."""
from pathlib import Path
from harness_v6.contracts import strict_json
from harness_v6.session import classify
from harness_v6.single_action import parse, OUTPUT_SCHEMA


def require_real_codex(manifest):
    assert manifest.get('mechanism_only') is False, 'mechanism-only evidence cannot satisfy the Mac gate'
    assert not manifest['codex_version'].startswith('fake-codex'), 'fake Codex version'
    fake = Path(__file__).with_name('fake_codex.py').resolve()
    for row in manifest['checks'].values():
        binary = Path(row['command'][0])
        assert binary.is_absolute(), 'recorded Codex binary must be absolute'
        assert binary.resolve() != fake and binary.name != fake.name, 'repository fake Codex binary cannot satisfy the Mac gate'


def check_f6(root, manifest, check):
    assert manifest['endpoint'].startswith('http://127.0.0.1:')
    assert manifest['real_model_requests']==0 and manifest['codex_version']
    row=manifest['checks'][check]
    assert row['passed'] is True and row['command'] and row['expected']
    raw=(root/row['jsonl']).read_text()
    if check=='compaction_detection': assert 'compaction' in classify(raw)['errors']
    elif check not in ('startup_timeout','tool_timeout'): assert not classify(raw)['errors']
    if check=='large_result_complete':
        from harness_v6.contracts import digest
        assert digest(strict_json((root/row['received_result']).read_bytes()))==row['sent_result_sha256']


def check_single_action(root, manifest, check):
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
