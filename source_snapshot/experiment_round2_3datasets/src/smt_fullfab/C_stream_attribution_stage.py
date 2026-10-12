"""Load only exact frozen attribution bytes; no legacy whole-run adapter.

Source modules execute in a private transient package. Inputs, stage and trace
are independently bound before and after the complete stream attribution call.
The original report remains complete; this wrapper is not a physical/resource
gate and cannot authorize a real C8 run.
"""
from pathlib import Path
import sys
import types
import uuid

from src.smt_fullfab.trace_source import inspect_jsonl

from .C_plan_archive import digest, identity, raw_snapshot, snapshot, write_raw_new

ATTRIBUTION_SOURCES = {
    'audit_candidate.py': '80e201fa0849e1bdcdc26fb2b28e59dd8357f9938356db03f90479d9868de8df',
    'legacy_checks.py': '9288d4d630b921d39fc9775a40928e4a0109a9bdf579fe3409ea3550619471eb',
    'storage.py': 'bf2145395dc1e19371c0c64bdf165b4bf11356622ccec9551fb69e2f7642d17a',
}
CONSTRUCTOR_SHA256 = '181f9819bab37e0f60da03cd06f67505d9849336f0326632372903d41c896a60'
# Location only: callers still supply the complete original expected hashes.
DEFAULT_ATTRIBUTION_SOURCE_DIR = Path(__file__).resolve().with_name('C_stream_attribution_v2')
DEFAULT_CONSTRUCTOR_SOURCE = DEFAULT_ATTRIBUTION_SOURCE_DIR / 'constructor_stream.py'
RECEIPT_KEYS = ('sha256', 'byte_count', 'line_count', 'event_count', 'max_record_bytes')


def _source(path, expected):
    path = Path(path).absolute()
    before = identity(path.stat(follow_symlinks=False))
    raw, receipt = raw_snapshot(path, expected)
    if identity(path.stat(follow_symlinks=False)) != before:
        raise ValueError('attribution source identity changed')
    return raw, {'path': str(path), **receipt, 'file_identity': list(before)}


def _fence(record):
    if identity(Path(record['path']).stat(follow_symlinks=False)) != tuple(record['file_identity']):
        raise ValueError('attribution frozen source identity changed')


def validate_sources(source_dir, expected_sources, *, constructor_source, expected_constructor_sha256):
    if type(expected_sources) is not dict or expected_sources != ATTRIBUTION_SOURCES:
        raise ValueError('complete pinned attribution source manifest required')
    if expected_constructor_sha256 != CONSTRUCTOR_SHA256:
        raise ValueError('pinned constructor audit source required')
    paths = {name: Path(source_dir) / name for name in ATTRIBUTION_SOURCES}
    paths['constructor_stream.py'] = Path(constructor_source)
    records = {}
    for name, path in paths.items():
        _, records[name] = _source(path, expected_sources.get(name, CONSTRUCTOR_SHA256))
    for record in records.values():
        _fence(record)
    return {'schema': 'draft-C8-stream-attribution-sources-v1', 'files': records,
        'expected_attribution_sources': dict(expected_sources), 'constructor_sha256': expected_constructor_sha256}


def snapshot_sources(run, source_binding):
    """Create recoverable raw dependency copies without revising any expected SHA."""
    destination = Path(run) / 'source_snapshot/attribution_stream_v2'
    destination.mkdir(parents=True, exist_ok=False)
    inventory = {}
    for name, record in source_binding['files'].items():
        _fence(record)
        raw, _ = raw_snapshot(record['path'], record['sha256'])
        _fence(record)
        write_raw_new(destination / name, raw)
        inventory['attribution_stream_v2/' + name] = record['sha256']
    for record in source_binding['files'].values():
        _fence(record)
    return destination, inventory


def audit_execution_stage(run_dir, *, ledger_path, attribution_source_dir, expected_attribution_sources,
                          constructor_source, expected_constructor_sha256, expected_execution_result_sha256,
                          scratch_dir, expected_trace_receipt):
    run = Path(run_dir).resolve()
    if type(expected_trace_receipt) is not dict or set(expected_trace_receipt) != set(RECEIPT_KEYS):
        raise ValueError('complete original trace receipt required')
    trace_seal = inspect_jsonl(run / 'trace.jsonl', expected_sha256=expected_trace_receipt['sha256'])
    if digest({key: getattr(trace_seal, key) for key in RECEIPT_KEYS}) != digest(expected_trace_receipt):
        raise ValueError('complete original trace receipt differs from actual bytes')
    execution, _ = snapshot(run / 'execution_result.json', expected_execution_result_sha256)
    bound = validate_sources(attribution_source_dir, expected_attribution_sources,
        constructor_source=constructor_source, expected_constructor_sha256=expected_constructor_sha256)
    raw_modules = {}
    for name in ATTRIBUTION_SOURCES:
        record = bound['files'][name]
        raw_modules[name], _ = raw_snapshot(record['path'], record['sha256'])
        _fence(record)
    package_name = '_C8_attribution_bound_' + uuid.uuid4().hex
    package = types.ModuleType(package_name)
    package.__path__ = []  # Relative imports may only resolve our bound modules.
    sys.modules[package_name] = package
    installed = [package_name]
    try:
        for filename in ('storage.py', 'legacy_checks.py', 'audit_candidate.py'):
            name = package_name + '.' + filename[:-3]
            module = types.ModuleType(name)
            module.__package__ = package_name
            module.__file__ = bound['files'][filename]['path']
            sys.modules[name] = module
            installed.append(name)
            exec(compile(raw_modules[filename], module.__file__, 'exec'), module.__dict__)
        report = module.audit_controller(run, ledger_path, scratch_dir=scratch_dir,
            constructor_module_path=constructor_source, expected_constructor_sha256=expected_constructor_sha256,
            result_stage=(run / 'execution_result.json', expected_execution_result_sha256))
    finally:
        for name in reversed(installed):
            sys.modules.pop(name, None)
    if report.get('evidence_sha256', {}).get('trace.jsonl') != expected_trace_receipt['sha256']:
        raise ValueError('stream attribution differs from original trace SHA')
    receipt = report.get('_source_evidence', {}).get('receipts', {}).get(str(run / 'trace.jsonl'), {})
    if receipt.get('sha256') != expected_trace_receipt['sha256'] or receipt.get('bytes') != expected_trace_receipt['byte_count']:
        raise ValueError('stream attribution raw trace receipt differs')
    snapshot(run / 'execution_result.json', expected_execution_result_sha256)
    if identity((run / 'trace.jsonl').stat(follow_symlinks=False)) != trace_seal.file_identity:
        raise ValueError('stage trace identity changed during attribution')
    for record in bound['files'].values():
        _fence(record)
    return {'schema': 'draft-C8-stream-stage-attribution-v1', 'valid': report['valid'],
        'attribution_report': report, 'execution_result_sha256': expected_execution_result_sha256,
        'attribution_source_binding': bound, 'original_trace_receipt': dict(expected_trace_receipt),
        'stage_config_identity': execution.get('identity'), 'real_C8_launch_authorized': False,
        'complete_original_attribution_checks': True, 'legacy_whole_history_adapter_used': False,
        'final_process_resource_acceptance': False,
        'remaining_memory': report.get('_source_evidence', {}).get('remaining_RAM', [])}
