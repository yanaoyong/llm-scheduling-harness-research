"""Validate archived local-mock probe outputs; tests never execute codex."""
import os
from pathlib import Path
import pytest
from probe_checks import require_real_codex, check_f6
from harness_v6.contracts import strict_json

CHECKS=('config_injection','approval_never','schema_with_mcp','jsonl_fields','startup_timeout','tool_timeout','compaction_detection','environment_inheritance','large_result_complete')
@pytest.mark.parametrize('check',CHECKS)
def test_f6_local_mock(check):
    directory=os.environ.get('V6_F6_PROBE_DIR')
    if not directory:pytest.skip('Mac-only pinned codex/local mock Responses probe evidence absent: V6_F6_PROBE_DIR')
    root=Path(directory);manifest=strict_json((root/'manifest.json').read_bytes())
    require_real_codex(manifest)
    check_f6(root, manifest, check)
