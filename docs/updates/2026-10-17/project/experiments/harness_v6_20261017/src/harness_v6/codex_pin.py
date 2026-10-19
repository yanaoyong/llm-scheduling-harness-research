"""Production requires the official release and its registered binary digest."""
import hashlib
from pathlib import Path

OFFICIAL_VERSION = 'codex-cli 0.163.0'


def require_official_pin(binary, version, expected_sha256):
    if version != OFFICIAL_VERSION:
        raise ValueError('production requires the official Codex 0.163.0 release')
    actual = hashlib.sha256(Path(binary).read_bytes()).hexdigest()
    if not isinstance(expected_sha256, str) or actual != expected_sha256:
        raise ValueError('codex_binary_sha256 mismatch or missing pin')
    return actual
