"""Validate archived local-mock probe outputs; tests never execute codex."""
import os
from pathlib import Path
import pytest
from harness_v6.contracts import strict_json
from harness_v6.session import classify

CHECKS=('config_injection','approval_never','schema_with_mcp','jsonl_fields','startup_timeout','tool_timeout','compaction_detection','environment_inheritance','large_result_complete')
@pytest.mark.parametrize('check',CHECKS)
def test_f6_local_mock(check):
    directory=os.environ.get('V6_F6_PROBE_DIR')
    if not directory:pytest.skip('Mac-only pinned codex/local mock Responses probe evidence absent: V6_F6_PROBE_DIR')
    root=Path(directory);manifest=strict_json((root/'manifest.json').read_bytes())
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
