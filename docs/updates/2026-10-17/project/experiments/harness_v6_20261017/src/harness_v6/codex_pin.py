"""The dedicated build is intentionally distinct from upstream Codex."""
import hashlib
from pathlib import Path

SOURCE_COMMIT = '83086188ae0614bd882818ff1aa23f3194962012'
ISOLATED_VERSION = 'codex-cli 0.163.0-harness-v6.5'


def require_isolated_pin(binary, version, expected_sha256):
    if version != ISOLATED_VERSION:
        raise ValueError('production requires the verified Harness-only Codex build')
    actual = hashlib.sha256(Path(binary).read_bytes()).hexdigest()
    if not isinstance(expected_sha256, str) or actual != expected_sha256:
        raise ValueError('codex_binary_sha256 mismatch or missing pin')
    return actual
