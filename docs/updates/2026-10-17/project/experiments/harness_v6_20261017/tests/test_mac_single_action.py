"""Archived Mac local-mock probes only; never launches Codex or reads sealed data."""
import os
from pathlib import Path
import pytest
from probe_checks import require_real_codex, check_single_action
from harness_v6.contracts import strict_json

@pytest.mark.parametrize('check', ['single_schema_no_mcp', 'single_tool_rejection', 'single_usage'])
def test_single_action_f6(check):
    directory = os.environ.get('V6_SINGLE_ACTION_PROBE_DIR')
    if not directory:
        pytest.skip('Mac-only pinned Codex local mock probe missing: V6_SINGLE_ACTION_PROBE_DIR')
    root = Path(directory)
    manifest = strict_json((root / 'manifest.json').read_bytes())
    require_real_codex(manifest)
    check_single_action(root, manifest, check)
