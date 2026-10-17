"""Explicit Mac fixture contract; configured but broken fixtures fail, never skip."""
import os
from pathlib import Path
import pytest
from harness_v6.contracts import strict_json

def bundle():
    path=os.environ.get('V6_MAC_FIXTURE')
    if not path: pytest.skip('Mac-only SMT2020/vendor/sealed fixture absent: set V6_MAC_FIXTURE')
    return strict_json(Path(path).read_bytes())

def environment(key='mixed_702'):
    b=bundle()
    from harness_v6.env_adapter import PHYSICS_AVAILABLE, FullFabEnvironment
    assert PHYSICS_AVAILABLE, 'Configured Mac validation requires pinned src.smt.environment and vendor'
    from harness_v6.factory_v6 import restore
    fixture=b[key]
    return restore(fixture['state'],fixture['trace'],data_dir=b['data_dir']),b
