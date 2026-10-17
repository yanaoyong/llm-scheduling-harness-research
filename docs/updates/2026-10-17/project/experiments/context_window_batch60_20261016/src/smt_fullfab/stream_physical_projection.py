"""Stream the existing full-fab -> legacy-physical-checker event adapter.

This performs no physical audit, simulation, model action, scheduling or metric
reconstruction. Synthetic actions ONLY make the old physical checker understand
explicit production dispatches; they are never evidence of model decisions.

A bundle directory becomes visible before it is complete. Only the create-new,
atomically published projection.json is a completion marker. Interrupted files
are retained for diagnosis and the directory is never overwritten or resumed.
verify_projection_bundle is a point-in-time check; its bare path is diagnostic,
never a certificate for later reads. Consumers must use open_verified_projection,
which binds a fresh verified-consumption context to the SAME output TraceSeal
obtained during its verification and requires complete EOF before normal exit.
Conversion, verification and consumption retain only individual records/manifest; the old physical checker itself has NOT been made streaming here.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
from itertools import chain
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from .trace_source import TraceSeal, TraceSourceError, SourceChangedError, inspect_jsonl, open_verified

VERSION = 'smt-fullfab-stream-physical-projection-v1'
VERIFICATION_VERSION = 'smt-fullfab-projection-verification-v2'
SCHEMA = 'smt-fullfab-physical-projection-bundle-v1'
REFERENCE_VERSION = 'smt-fullfab-independent-plan-audit-v2'
REFERENCE_FUNCTION = 'src.smt_fullfab.audit.audit_trace'
PHYSICAL_NAME = 'physical.jsonl'
MANIFEST_NAME = 'projection.json'
MAX_MANIFEST_BYTES = 65536
PHYSICAL_KINDS = frozenset(('initial', 'release', 'ready', 'skip', 'dispatch', 'downtime',
                           'operation_complete', 'rework', 'lot_complete', 'terminal'))
SCOPE = {
    'synthetic_actions_are_model_decisions': False,
    'synthetic_action_scope': 'legacy physical checker adaptation only',
    'physical_audit_performed': False,
    'plan_source_audit_performed': False,
    'opportunity_audit_performed': False,
    'official_simulator_equivalence_certified': False,
    'legacy_physical_checker_streamed': False,
}
RECEIPT_FIELDS = frozenset(('sha256', 'byte_count', 'line_count', 'event_count', 'max_record_bytes'))
COUNT_FIELDS = frozenset(('kept_source_events', 'skipped_source_events', 'synthetic_action_count', 'output_event_count'))


class ProjectionError(TraceSourceError):
    """Incomplete, changed or incorrectly projected evidence is not consumable."""


def _counts():
    return {key: 0 for key in ('kept_source_events', 'skipped_source_events', 'synthetic_action_count', 'output_event_count')}


def _project_records(reader, counts):
    """Per-record deepcopy and exact reference-loop behavior, with its root guard."""
    first = next(reader, None)
    if first is None or first.event.get('kind') != 'initial':
        raise ProjectionError('missing initial manifest; no legacy physical projection')
    try:
        controlled = first.event['manifest']['controlled_machine_ids']
        first_time = first.event['time']
    except (KeyError, TypeError) as exc:
        raise ProjectionError('initial manifest lacks projection inputs') from exc
    if not isinstance(controlled, list):
        raise ProjectionError('controlled_machine_ids must be the saved JSON list')
    for record in chain((first,), reader):
        event = record.event
        if event.get('kind') == 'snapshot_loaded' and (first_time != 0 or event.get('prefix_event_count') != record.event_index):
            raise ProjectionError('snapshot root requires complete prehistory; no cold-start substitution')
        if event['kind'] not in PHYSICAL_KINDS:
            counts['skipped_source_events'] += 1
            continue
        e = copy.deepcopy(event)
        counts['kept_source_events'] += 1
        if e['kind'] == 'dispatch' and e['machine'] in controlled:
            action = {'seq': counts['output_event_count'], 'time': e['time'], 'kind': 'action',
                      'decision': counts['synthetic_action_count'],
                      'action': {'dispatches': [{'machine': e['machine'], 'lot_ids': e['lots']}], 'wait_seconds': 0}}
            counts['synthetic_action_count'] += 1
            counts['output_event_count'] += 1
            yield action
            e['owner'] = 'controller'
        if e['kind'] == 'terminal':
            e['metrics'] = {}
        e['seq'] = counts['output_event_count']
        counts['output_event_count'] += 1
        yield e


class _JsonlWriter:
    def __init__(self, stream):
        self.stream = stream
        self.hash = hashlib.sha256()
        self.bytes = self.events = self.maximum = 0

    def write(self, event):
        raw = (json.dumps(event, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
        if self.stream.write(raw) != len(raw):
            raise OSError('short physical projection write')
        self.hash.update(raw)
        self.bytes += len(raw)
        self.events += 1
        self.maximum = max(self.maximum, len(raw))

    def receipt(self):
        return {'sha256': self.hash.hexdigest(), 'byte_count': self.bytes, 'line_count': self.events,
                'event_count': self.events, 'max_record_bytes': self.maximum}


def _publish_manifest(bundle, manifest):
    """Atomic completion-marker publication, not atomic directory visibility."""
    raw = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ProjectionError('projection manifest exceeds fixed metadata bound')
    fd, temporary = tempfile.mkstemp(prefix='.projection.', suffix='.partial', dir=bundle)
    try:
        with os.fdopen(fd, 'wb') as stream:
            if stream.write(raw) != len(raw):
                raise OSError('short completion manifest write')
            stream.flush()
            os.fsync(stream.fileno())
        # Hash the exact private bytes. Never reopen a published path to certify
        # whatever another writer may have replaced it with in the interval.
        manifest_sha256 = hashlib.sha256(raw).hexdigest()
        os.link(temporary, bundle / MANIFEST_NAME)
        return manifest_sha256
    finally:
        # If this fails after link(), the complete marker and receipt survive.
        # The leftover private regular file is diagnostic, never a new input.
        Path(temporary).unlink(missing_ok=True)


def project_physical_trace(source, *, output_dir):
    """Create a new diagnostic bundle; publish its completion marker last.

    A failure preserves any new directory/partial physical file without an
    authenticated completion marker. A post-publication error may leave a fully
    verifiable marker. Never retry using the existing directory; inspect it with
    verify_projection_bundle or choose a genuinely new output directory.
    """
    requested = Path(output_dir).absolute()
    bundle = requested.parent.resolve(strict=True) / requested.name
    bundle.mkdir()  # create-new, including existing empty directories/symlinks
    seal = source if isinstance(source, TraceSeal) else inspect_jsonl(source)
    counts = _counts()
    with open_verified(seal) as reader:
        with (bundle / PHYSICAL_NAME).open('xb') as stream:
            writer = _JsonlWriter(stream)
            for event in _project_records(reader, counts):
                writer.write(event)
            stream.flush()
            os.fsync(stream.fileno())
    # The source receipt is unavailable until verified EOF AND context exit.
    source_receipt = asdict(reader.receipt)
    manifest = {'schema': SCHEMA, 'status': 'complete', 'projection_version': VERSION,
                'reference_contract_version': REFERENCE_VERSION, 'reference_function': REFERENCE_FUNCTION,
                'source_receipt': source_receipt, 'physical_member': PHYSICAL_NAME,
                'output_receipt': writer.receipt(), 'conversion_counts': counts,
                'complete_input_pass': True, 'output_format': 'utf8-jsonl', 'scope': dict(SCOPE)}
    manifest_sha256 = _publish_manifest(bundle, manifest)
    return {'bundle_path': str(bundle), 'manifest_path': str(bundle / MANIFEST_NAME),
            'manifest_sha256': manifest_sha256, 'projection_version': VERSION,
            'source_receipt': source_receipt, 'output_receipt': manifest['output_receipt'],
            'conversion_counts': counts, 'verification_required_before_use': True, 'scope': dict(SCOPE)}


def _layout(bundle):
    if bundle.is_symlink() or not bundle.is_dir():
        raise ProjectionError('projection bundle must be a real directory, never a symlink')
    members = set()
    for path in bundle.iterdir():
        if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
            raise ProjectionError('projection bundle contains a symlink or nonregular member')
        if path.name in (PHYSICAL_NAME, MANIFEST_NAME):
            members.add(path.name)
        elif not re.fullmatch(r'\.projection\.[a-zA-Z0-9_-]+\.partial', path.name):
            raise ProjectionError('unexpected member in fixed projection bundle')
    if members != {PHYSICAL_NAME, MANIFEST_NAME}:
        raise ProjectionError('incomplete projection bundle: completion marker and physical member required')


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _manifest(path):
    """Read bounded metadata once, binding its original bytes and local identity."""
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_MANIFEST_BYTES:
            raise ProjectionError('completion marker is not bounded regular metadata')
        raw = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise ProjectionError('completion marker exceeds metadata bound')
        after = os.fstat(stream.fileno())
    identity = _identity(before)
    if identity != _identity(after) or identity != _identity(path.stat()):
        raise SourceChangedError('completion marker changed during metadata read')
    try:
        manifest = json.loads(raw.decode('utf-8'))
    except (UnicodeError, ValueError) as exc:
        raise ProjectionError('invalid completion manifest JSON') from exc
    return manifest, hashlib.sha256(raw).hexdigest(), identity


def _valid_receipt(receipt):
    return (isinstance(receipt, dict) and set(receipt) == RECEIPT_FIELDS and
            isinstance(receipt['sha256'], str) and re.fullmatch('[0-9a-f]{64}', receipt['sha256']) is not None and
            all(type(receipt[key]) is int and receipt[key] >= 0 for key in RECEIPT_FIELDS - {'sha256'}))


def _same_object(left, right):
    # Python == treats True, 1 and 1.0 as equal. JSON scalar types, nested list
    # order and signed float representation must remain the reference values.
    return json.dumps(left, sort_keys=True, ensure_ascii=True, separators=(',', ':')) == json.dumps(right, sort_keys=True, ensure_ascii=True, separators=(',', ':'))


def _validate_manifest(manifest):
    expected = {'schema', 'status', 'projection_version', 'reference_contract_version', 'reference_function',
                'source_receipt', 'physical_member', 'output_receipt', 'conversion_counts',
                'complete_input_pass', 'output_format', 'scope'}
    if not isinstance(manifest, dict) or set(manifest) != expected:
        raise ProjectionError('completion manifest schema differs')
    if any(manifest.get(key) != value for key, value in (
        ('schema', SCHEMA), ('status', 'complete'), ('projection_version', VERSION),
        ('reference_contract_version', REFERENCE_VERSION), ('reference_function', REFERENCE_FUNCTION),
        ('physical_member', PHYSICAL_NAME), ('output_format', 'utf8-jsonl'))):
        raise ProjectionError('completion manifest identity or fixed member differs')
    if manifest['complete_input_pass'] is not True or not _same_object(manifest['scope'], SCOPE):
        raise ProjectionError('completion manifest improperly claims audit/model-decision scope')
    if not _valid_receipt(manifest['source_receipt']) or not _valid_receipt(manifest['output_receipt']):
        raise ProjectionError('invalid persisted input/output receipt')
    counts = manifest['conversion_counts']
    if (not isinstance(counts, dict) or set(counts) != COUNT_FIELDS or
            any(type(value) is not int or value < 0 for value in counts.values())):
        raise ProjectionError('invalid persisted conversion counts')


def _check_output_identity(seal):
    """Fence the original output seal, never inspect/reseal a replaced path."""
    try:
        current = seal.path.lstat()
    except OSError as exc:
        raise SourceChangedError('physical output path changed since verified pass') from exc
    if not stat.S_ISREG(current.st_mode) or _identity(current) != seal.file_identity:
        raise SourceChangedError('physical output identity changed since verified pass')


def _verify_projection_bundle(output_dir, *, source, expected_manifest_sha256=None):
    """Internal verified evidence plus the exact output seal used in comparison."""
    candidate = Path(output_dir).absolute()
    if candidate.is_symlink():
        raise ProjectionError('projection bundle cannot be a symlink')
    bundle = candidate.resolve(strict=True)
    _layout(bundle)
    manifest_path = bundle / MANIFEST_NAME
    manifest, manifest_sha256, identity = _manifest(manifest_path)
    _validate_manifest(manifest)
    if expected_manifest_sha256 is not None:
        if not isinstance(expected_manifest_sha256, str) or re.fullmatch('[0-9a-f]{64}', expected_manifest_sha256) is None:
            raise ProjectionError('expected manifest hash must be 64 lowercase hexadecimal characters')
        if manifest_sha256 != expected_manifest_sha256:
            raise SourceChangedError('completion manifest differs from retained hash')
    source_seal = source if isinstance(source, TraceSeal) else inspect_jsonl(source)
    output_seal = inspect_jsonl(bundle / PHYSICAL_NAME, expected_sha256=manifest['output_receipt']['sha256'])
    counts = _counts()
    with open_verified(source_seal) as source_reader, open_verified(output_seal) as output_reader:
        for expected in _project_records(source_reader, counts):
            actual = next(output_reader, None)
            if actual is None:
                raise ProjectionError('physical JSONL omits projected events')
            if not _same_object(actual.event, expected):
                raise ProjectionError(f'physical event {actual.event_index} differs from typed source projection')
        if next(output_reader, None) is not None:
            raise ProjectionError('physical JSONL contains extra projected events')
    source_receipt, output_receipt = asdict(source_reader.receipt), asdict(output_reader.receipt)
    if not _same_object(source_receipt, manifest['source_receipt']):
        raise SourceChangedError('source receipt differs from the completed projection')
    if not _same_object(output_receipt, manifest['output_receipt']):
        raise ProjectionError('physical output receipt/count differs from completion manifest')
    if not _same_object(counts, manifest['conversion_counts']):
        raise ProjectionError('conversion counters differ from complete source replay')
    _layout(bundle)
    _check_output_identity(output_seal)
    if _identity(manifest_path.stat()) != identity:
        raise SourceChangedError('completion manifest changed during projection verification')
    descriptor = {'projection_verified': True, 'bundle_path': str(bundle), 'physical_path': str(bundle / PHYSICAL_NAME),
            'manifest_path': str(manifest_path), 'manifest_sha256': manifest_sha256,
            'projection_version': VERSION, 'source_receipt': source_receipt, 'output_receipt': output_receipt,
            'conversion_counts': counts, 'scope': dict(SCOPE),
            'verification_version': VERIFICATION_VERSION,
            'verification_scope': 'point-in-time source-to-projection comparison',
            'physical_path_is_diagnostic': True, 'verified_consumption_required': True,
            'consumption_api': 'src.smt_fullfab.stream_physical_projection.open_verified_projection'}
    return descriptor, output_seal


def verify_projection_bundle(output_dir, *, source, expected_manifest_sha256=None):
    """Return JSON-serializable point-in-time evidence, NOT a consumable-path grant.

    Even without a retained manifest hash, the complete source projection is
    reconstructed and compared by object/type/order with the output. Both passes
    must reach verified EOF and the original output identity is fenced before
    return. Files can still change after return: physical_path is diagnostic only.
    Use open_verified_projection for any subsequent consumption. Neither entry
    point runs physical replay or certifies opportunity/model attribution.
    """
    descriptor, _ = _verify_projection_bundle(output_dir, source=source,
        expected_manifest_sha256=expected_manifest_sha256)
    return descriptor


@contextmanager
def open_verified_projection(output_dir, *, source, expected_manifest_sha256=None):
    """Verify, then consume the exact same sealed output in a bounded context.

    Yields a trace_source.VerifiedJsonlPass of TraceRecord objects. The original
    output TraceSeal is passed directly to open_verified; a later path is NEVER
    inspected again to grant it a new seal. Replacements between comparison and
    consumption, during consumption, or before context exit fail closed.

    The consumer must read until EOF. On early normal exit IncompleteReadError is
    raised; on any failure no consumption receipt is available. Publish downstream
    conclusions only after successful exit. The reader.receipt then binds all
    consumed bytes. This is checked file consumption, not the physical checker.
    """
    _, output_seal = _verify_projection_bundle(output_dir, source=source,
        expected_manifest_sha256=expected_manifest_sha256)
    _check_output_identity(output_seal)
    with open_verified(output_seal) as reader:
        yield reader
        # Keep this inside the verified context: a failure also prevents the
        # underlying reader from publishing a successful consumption receipt.
        _check_output_identity(output_seal)
