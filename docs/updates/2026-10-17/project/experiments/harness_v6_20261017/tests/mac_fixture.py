"""Explicit Mac fixture contract; configured but broken fixtures fail, never skip."""
import os
from functools import lru_cache
from pathlib import Path
import pytest
from harness_v6.contracts import strict_json

@lru_cache(maxsize=1)
def _read(path):
    return strict_json(Path(path).read_bytes())

def bundle(*keys):
    path=os.environ.get('V6_MAC_FIXTURE')
    if not path: pytest.skip('Mac-only SMT2020/vendor/sealed fixture absent: set V6_MAC_FIXTURE')
    b = _read(path)
    for key in keys:
        if key not in b: pytest.skip('sealed evidence not provided')
    return b

def environment(key=None):
    b=bundle()
    key = key or ('public_702' if 'public_702' in b else 'mixed_702')
    if key not in b: pytest.skip('sealed evidence not provided')
    from harness_v6.env_adapter import PHYSICS_AVAILABLE, FullFabEnvironment
    assert PHYSICS_AVAILABLE, 'Configured Mac validation requires pinned src.smt.environment and vendor'
    from harness_v6.factory_v6 import restore
    fixture=b[key]
    return restore(fixture['state'],fixture['trace'],data_dir=b['data_dir']),b
