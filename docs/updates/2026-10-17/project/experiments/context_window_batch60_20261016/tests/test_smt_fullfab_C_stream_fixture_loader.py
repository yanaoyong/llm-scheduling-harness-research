"""Bind unchanged reviewed tiny suites to installed C modules at test time.

This helper is not a runtime loader. It checks the original fixture bytes and
only aliases imports; it neither rewrites test bodies nor executes an experiment.
"""
import hashlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from src.smt_fullfab import C_plan_archive, C_stream_attribution_stage, C_stream_controller

ROOT = Path(__file__).resolve().parents[1]
DRAFT = ROOT / 'artifacts/smt_fullfab_review_drafts/C8_stream_controller_v3'


def load_fixture(filename, expected_sha256, original_package, *, module_name):
    path = DRAFT / filename
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('original reviewed fixture changed')
    module = types.ModuleType(module_name)
    module.__file__ = str(path)
    sys.modules[module_name] = module
    aliases = {original_package + '.plan_archive': C_plan_archive,
               original_package + '.controller_candidate': C_stream_controller,
               original_package + '.stream_attribution_stage': C_stream_attribution_stage}
    with patch.dict(sys.modules, aliases):
        exec(compile(raw, str(path), 'exec'), module.__dict__)
    # These are test input locations only. Expected source hashes and all test
    # bodies remain the original reviewed bytes. No real ledger is substituted.
    if hasattr(module, 'SOURCE'):
        module.SOURCE = C_stream_attribution_stage.DEFAULT_ATTRIBUTION_SOURCE_DIR
    if hasattr(module, 'CONSTRUCTOR'):
        module.CONSTRUCTOR = C_stream_attribution_stage.DEFAULT_CONSTRUCTOR_SOURCE
    return module


def export_tests(module, namespace):
    for name, value in vars(module).items():
        if isinstance(value, type) and issubclass(value, unittest.TestCase) and value.__module__ == module.__name__:
            namespace[name] = value
