"""Physical-core / verified-projection binding; no runner consumer yet.

Only a completed, source-bound consumption may be published. This wrapper is
not a full-fab plan-source, opportunity, model-attribution or official audit.
The core still returns an in-memory dict including its growing batch-fill list.
"""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from types import ModuleType

from src.smt_fullfab import stream_physical_projection as projection
from src.smt_fullfab.trace_source import TraceSeal, SourceChangedError, inspect_jsonl

VERSION = 'smt-physical-projection-binding-v1'
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DEPENDENCIES = {
    'src/smt_fullfab/stream_physical_core.py':
        'ab431c0f22386be951cbf2b6f2441feb5e0171909b56cf97bdb1c73d7c79e00d',
    'src/smt_fullfab/stream_physical_projection.py':
        '7ecc12b316e0ac9f146f5b4189fd00f4069d5f0486783d1bdd309e00f476b582',
    'src/smt_fullfab/trace_source.py':
        '915b2447ed19ad99676b6a2f1b1ef2f807001885e1d3513c034dc4c670bd93b4',
    'src/smt/source_check.py':
        '973bf61ea9754101795cf6875967479ad0ca7fd65938bf2799405ceba4c4b786',
}
RECEIPT_FIELDS = frozenset(('sha256', 'byte_count', 'line_count', 'event_count', 'max_record_bytes'))
EVIDENCE_FIELDS = frozenset(('manifest_sha256', 'source_receipt', 'output_receipt'))
SCOPE = {
    'physical_contract': 'smt-independent-audit-v2 on the complete verified legacy projection',
    'projection_complete_eof_verified': True,
    'original_source_to_projection_verified': True,
    'core_historical_state': 'SQLite jobs/dispatch/completed/machine_refs/downtime',
    'core_report_arrays_in_memory': True,
    'plan_source_audit_performed': False,
    'opportunity_audit_performed': False,
    'model_attribution_verified': False,
    'raw_fullfab_event_envelope_certified': False,
    'official_simulator_equivalence_certified': False,
    'long_window_readiness_certified': False,
    'expected_evidence_trust': 'caller supplied; storage binding does not authenticate its external origin',
    'path_scope': 'point-in-time identity fences; receipts bind consumed bytes, not future path contents',
}


class BindingError(ValueError):
    """Incomplete, changed, or mismatched evidence cannot yield a report."""


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def _sha(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _receipt(value):
    if type(value) is not dict or set(value) != RECEIPT_FIELDS or not _sha(value.get('sha256')):
        raise BindingError('receipt must contain the exact complete receipt fields')
    if any(type(value[key]) is not int or value[key] < 0 for key in RECEIPT_FIELDS - {'sha256'}):
        raise BindingError('receipt counts must be nonnegative integers, not booleans')


def _expected(value):
    if type(value) is not dict or set(value) != EVIDENCE_FIELDS or not _sha(value.get('manifest_sha256')):
        raise BindingError('expected_evidence requires manifest_sha256, source_receipt, output_receipt')
    _receipt(value['source_receipt']);_receipt(value['output_receipt'])
    return json.loads(_canonical(value))  # Freeze the caller's mutable metadata.


def _dependencies():
    for relative, expected in DEPENDENCIES.items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected:
            raise BindingError('frozen dependency changed: ' + relative)


def _load_core():
    relative = next(iter(DEPENDENCIES))
    path = ROOT / relative
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != DEPENDENCIES[relative]:
        raise BindingError('frozen physical core changed')
    module = ModuleType('isolated_physical_core_v2')
    module.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


core = _load_core()  # Execute the same bytes whose frozen SHA was checked.


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _regular_identity(path):
    try:
        info = path.lstat()
    except OSError as exc:
        raise SourceChangedError('bound evidence path disappeared: ' + str(path)) from exc
    if not stat.S_ISREG(info.st_mode):
        raise SourceChangedError('bound evidence must be a regular non-symlink file: ' + str(path))
    return _identity(info)


def _fence(identities):
    for path, expected in identities.items():
        if _regular_identity(path) != expected:
            raise SourceChangedError('bound evidence identity changed: ' + str(path))


def _manifest_snapshot(path):
    before = _regular_identity(path)
    with path.open('rb') as stream:
        if _identity(os.fstat(stream.fileno())) != before:
            raise SourceChangedError('manifest replaced before bounded read')
        raw = stream.read(projection.MAX_MANIFEST_BYTES + 1)
        if _identity(os.fstat(stream.fileno())) != before:
            raise SourceChangedError('manifest changed during bounded read')
    _fence({path: before})
    if len(raw) > projection.MAX_MANIFEST_BYTES:
        raise BindingError('projection manifest exceeds fixed metadata bound')
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise BindingError('invalid projection manifest JSON') from exc
    if type(value) is not dict:
        raise BindingError('projection manifest is not an object')
    return value, hashlib.sha256(raw).hexdigest(), before


def _fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_report(report, destination, fence):
    """Create-new atomic publication; hash exactly the bytes written, never reread.

    A caught failure after link rolls back only our own inode. A process crash
    after link can leave the complete source-bound report, never a half JSON.
    Directory fsync is required before reporting durable publication success.
    """
    destination = Path(destination)
    parent = destination.parent.resolve(strict=True)
    target = parent / destination.name
    if os.path.lexists(target):
        raise FileExistsError(target)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + target.name + '.', suffix='.partial', dir=parent)
    temporary = Path(temporary)
    linked = False
    owned_inode = None
    raw_hash = hashlib.sha256()
    byte_count = 0
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            owned_inode = _identity(os.fstat(stream.fileno()))[:2]
            encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            for chunk in encoder.iterencode(report):
                raw = chunk.encode('utf-8')
                stream.write(raw);raw_hash.update(raw);byte_count += len(raw)
            stream.write(b'\n');raw_hash.update(b'\n');byte_count += 1
            stream.flush()
            written_identity = _identity(os.fstat(stream.fileno()))
            if written_identity[2] != byte_count:
                raise SourceChangedError('temporary report size differs from bytes written')
            os.fsync(stream.fileno())
            if _identity(os.fstat(stream.fileno())) != written_identity:
                raise SourceChangedError('temporary report changed during file fsync')
            fence()
            os.link(temporary, target)  # Atomic visibility, refuses all existing names.
            linked = True
            expected = _identity(os.fstat(stream.fileno()))
            _fence({target: expected})
            _fsync_directory(parent)
            fence()
            _fence({target: expected})
            # Our alias removal changes ctime. Keep the original descriptor
            # open, require all other identity fields unchanged, then fence the
            # newly established full identity through durability and close.
            temporary.unlink()
            after_unlink = _identity(os.fstat(stream.fileno()))
            if after_unlink[:4] != expected[:4]:
                raise SourceChangedError('published report changed during alias removal')
            expected = after_unlink
            _fsync_directory(parent)
            fence()
            _fence({target: expected})
        _fence({target: expected})
        fence()
        return {'report_path': str(target), 'report_sha256': raw_hash.hexdigest(),
                'report_byte_count': byte_count, 'durable_publication_complete': True}
    except BaseException as primary:
        # Never remove a different file installed concurrently at the destination.
        cleanup_errors = []
        # Also catch an interrupted os.link after the OS created the link but
        # before the Python call returned and set `linked`.
        if owned_inode is not None:
            try:
                target_info = target.lstat()
                if (target_info.st_dev, target_info.st_ino) == owned_inode:
                    target.unlink()
                    _fsync_directory(parent)
                elif linked:
                    primary.add_note('Destination was replaced; replacement was not removed or certified.')
            except FileNotFoundError:
                pass
            except BaseException as cleanup_error:
                cleanup_errors.append(cleanup_error)
        try:
            temporary.unlink(missing_ok=True)
        except BaseException as cleanup_error:
            cleanup_errors.append(cleanup_error)
        for cleanup_error in cleanup_errors:
            primary.add_note('Publication cleanup failed: ' + repr(cleanup_error))
        raise


def audit_projection_to_file(bundle, *, source, expected_evidence, report_path,
                             verify_data_dir=None, work_dir=None):
    """Consume the complete existing projection and create one bound report.

    expected_evidence is an exact three-key dict of manifest_sha256,
    source_receipt and output_receipt, obtained from the caller's saved bundle
    evidence. The caller supplies source bytes (path or TraceSeal), never a bare
    physical output path. No valid result is returned before context EOF,
    identity and receipt checks, complete serialization and durable publication.
    A fully read physically invalid trace may publish valid=False diagnostics.
    """
    expected = _expected(expected_evidence)
    _dependencies()
    # Refuse collisions before doing any event work; link still handles races.
    if os.path.lexists(report_path):
        raise FileExistsError(report_path)
    bundle = Path(bundle).resolve(strict=True)
    manifest_path = bundle / projection.MANIFEST_NAME
    output_path = bundle / projection.PHYSICAL_NAME
    manifest, manifest_sha, manifest_identity = _manifest_snapshot(manifest_path)
    if manifest_sha != expected['manifest_sha256']:
        raise BindingError('manifest hash differs from caller evidence')
    for name in ('source_receipt', 'output_receipt'):
        if _canonical(manifest.get(name)) != _canonical(expected[name]):
            raise BindingError(name + ' differs from caller evidence')
    seal = source if isinstance(source, TraceSeal) else inspect_jsonl(source,
        expected_sha256=expected['source_receipt']['sha256'])
    source_receipt = {key: getattr(seal, key) for key in RECEIPT_FIELDS}
    if _canonical(source_receipt) != _canonical(expected['source_receipt']):
        raise BindingError('source seal differs from caller complete receipt')
    identities = {seal.path: seal.file_identity, manifest_path: manifest_identity,
                  output_path: _regular_identity(output_path)}
    _fence(identities)
    with projection.open_verified_projection(bundle, source=seal,
            expected_manifest_sha256=expected['manifest_sha256']) as reader:
        physical_report = core.audit_events((record.event for record in reader),
                                            verify_data_dir, work_dir=work_dir)
        # No receipt exists here, including when the core happened to see EOF.
        _fence(identities)
    if reader.receipt is None:
        raise BindingError('verified context returned no complete consumption receipt')
    consumed_receipt = asdict(reader.receipt)
    if _canonical(consumed_receipt) != _canonical(expected['output_receipt']):
        raise BindingError('consumption receipt differs from expected full projection')
    _fence(identities)
    _dependencies()
    report = {
        'schema': 'smt-physical-bound-report-v1', 'binding_version': VERSION,
        'status': 'complete', 'physical_report': physical_report,
        'core_scope': physical_report.get('_core_scope'), 'scope': SCOPE,
        '_source_evidence': {
            'expected_evidence': expected, 'projection_manifest': manifest,
            'projection_manifest_sha256': manifest_sha,
            'source_receipt': source_receipt, 'consumption_receipt': consumed_receipt,
            'complete_verified_context_exit': True,
            'projection_version': projection.VERSION,
            'projection_verification_version': projection.VERIFICATION_VERSION,
            'dependency_sha256': dict(DEPENDENCIES),
            'binding_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
    }
    published = _publish_report(report, report_path, lambda: _fence(identities))
    return dict(published, binding_version=VERSION, physical_valid=physical_report['valid'],
                scope=dict(SCOPE), expected_evidence=expected)
