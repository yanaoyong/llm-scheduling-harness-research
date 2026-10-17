"""Repeatable, verified reads of one archived JSONL trace.

This module checks storage and the event envelope only. It imports no simulator,
controller, optimizer or other auditor, and cannot certify physical correctness,
plan provenance or absence of omitted dispatch opportunities. Existing consumers
are deliberately unchanged. Memory is bounded by individual decoded records;
consumer state and the largest record still require their own resource budgets.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat


class TraceSourceError(ValueError):
    """Invalid trace storage or envelope; never a successful partial audit."""


class SourceChangedError(TraceSourceError):
    """The file identity, raw bytes or record counts changed."""


class IncompleteReadError(TraceSourceError):
    """A verified pass did not reach EOF; no receipt is available."""


@dataclass(frozen=True)
class TraceSeal:
    path: Path
    sha256: str
    byte_count: int
    line_count: int
    event_count: int
    max_record_bytes: int
    # A conservative local mutation fence, not the authoritative content hash.
    file_identity: tuple[int, int, int, int, int]


@dataclass(frozen=True)
class TraceRecord:
    event_index: int
    line_number: int
    byte_offset: int
    raw_line: bytes
    event: dict


@dataclass(frozen=True)
class ReadReceipt:
    sha256: str
    byte_count: int
    line_count: int
    event_count: int
    max_record_bytes: int


@dataclass(frozen=True)
class TraceEnvelope:
    receipt: ReadReceipt
    first_time: int | float
    last_time: int | float
    horizon: int | float
    terminal_at_eof: bool
    snapshot_count: int
    scope: str = 'event-format-time-sequence-and-prefix-only'
    physical_audit_performed: bool = False
    plan_source_audit_performed: bool = False
    opportunity_audit_performed: bool = False


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class VerifiedJsonlPass:
    """Context-managed iterator; consume through EOF before leaving the context.

    Each pass opens and decodes fresh records. Blank lines contribute raw bytes
    and physical line numbers, but not event indexes. Complete final JSON without
    a newline is accepted, as in the legacy readers. Truncated JSON is rejected.
    ``receipt`` is None until verified EOF and successful context exit.
    Even reading exactly seal.event_count records is insufficient: EOF must be
    observed. An early break raises IncompleteReadError on normal context exit;
    an existing consumer exception is preserved without being masked.
    """

    def __init__(self, path, seal=None):
        self.path = Path(path)
        self._seal = seal
        self._stream = None
        self._entered = False
        self._closed = False
        self._eof = False
        self._failed = False
        self._identity = None
        self._hash = hashlib.sha256()
        self._bytes = self._lines = self._events = self._max_record = 0
        self._receipt = None
        self._candidate_receipt = None

    @property
    def receipt(self):
        """Read-only evidence, published only after successful context exit."""
        return self._receipt

    def __enter__(self):
        if self._entered or self._closed:
            raise TraceSourceError('a pass is single-use; open a new verified pass')
        self._entered = True
        try:
            self._stream = self.path.open('rb')
            info = os.fstat(self._stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise TraceSourceError('trace source must be a regular file')
            self._identity = _identity(info)
            if self._seal is not None and self._identity != self._seal.file_identity:
                raise SourceChangedError('trace identity changed since inspection')
            self._check_identity()
        except BaseException:
            if self._stream is not None:
                self._stream.close()
            self._closed = True
            raise
        return self

    def _check_identity(self):
        try:
            same = (_identity(os.fstat(self._stream.fileno())) == self._identity
                    and _identity(self.path.stat()) == self._identity)
        except OSError as exc:
            raise SourceChangedError('trace path changed during read') from exc
        if not same:
            raise SourceChangedError('trace identity changed during read')

    def __iter__(self):
        return self

    def __next__(self):
        if not self._entered or self._closed:
            raise TraceSourceError('read the pass inside its context')
        if self._failed:
            raise TraceSourceError('failed pass cannot be resumed or certified')
        if self._eof:
            return self._stop()
        try:
            while True:
                offset = self._bytes
                raw = self._stream.readline()
                if not raw:
                    self._check_identity()
                    actual = ReadReceipt(self._hash.hexdigest(), self._bytes, self._lines,
                                         self._events, self._max_record)
                    if self._seal is not None:
                        expected = ReadReceipt(self._seal.sha256, self._seal.byte_count,
                                               self._seal.line_count, self._seal.event_count,
                                               self._seal.max_record_bytes)
                        if actual != expected:
                            raise SourceChangedError('trace bytes or record counts differ from seal')
                    self._eof = True
                    self._candidate_receipt = actual
                    return self._stop()
                self._hash.update(raw)
                self._bytes += len(raw)
                self._lines += 1
                if not raw.strip():
                    continue
                self._max_record = max(self._max_record, len(raw))
                try:
                    event = json.loads(raw.decode('utf-8'))
                except (UnicodeError, ValueError) as exc:
                    raise TraceSourceError(f'invalid UTF-8 JSON at line {self._lines}, byte {offset}') from exc
                if not isinstance(event, dict):
                    raise TraceSourceError(f'event is not an object at line {self._lines}, byte {offset}')
                record = TraceRecord(self._events, self._lines, offset, raw, event)
                self._events += 1
                return record
        except StopIteration:
            raise
        except BaseException:
            self._receipt = self._candidate_receipt = None
            self._failed = True
            raise

    @staticmethod
    def _stop():
        raise StopIteration

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if exc_type is not None:
                self._receipt = self._candidate_receipt = None
            else:
                if self._failed:
                    raise TraceSourceError('failed pass cannot be certified')
                if not self._eof:
                    raise IncompleteReadError('verified pass did not reach EOF; no receipt')
                self._check_identity()
        except BaseException:
            self._receipt = self._candidate_receipt = None
            raise
        finally:
            try:
                if self._stream is not None:
                    self._stream.close()
            except BaseException:
                self._receipt = self._candidate_receipt = None
                raise
            finally:
                self._closed = True
        if exc_type is None:
            self._receipt = self._candidate_receipt
        return False


def inspect_jsonl(path, *, expected_sha256=None):
    """Read a whole file sequentially once and seal its raw bytes and counts.

    Inspection authenticates neither the supplied file nor its event semantics.
    A trusted external expected_sha256 may bind it to an existing evidence file.
    No complete event or line list is retained. No source file is modified.
    """
    if expected_sha256 is not None and (not isinstance(expected_sha256, str)
                                       or re.fullmatch('[0-9a-f]{64}', expected_sha256) is None):
        raise TraceSourceError('expected_sha256 must be 64 lowercase hexadecimal characters')
    path = Path(path).resolve(strict=True)
    with VerifiedJsonlPass(path) as reader:
        for _ in reader:
            pass
    receipt = reader.receipt
    if expected_sha256 is not None and receipt.sha256 != expected_sha256:
        raise SourceChangedError('trace SHA-256 differs from expected source')
    return TraceSeal(path, receipt.sha256, receipt.byte_count, receipt.line_count,
                     receipt.event_count, receipt.max_record_bytes, reader._identity)


def open_verified(seal):
    """Open a fresh, complete pass bound to an immutable TraceSeal."""
    if not isinstance(seal, TraceSeal):
        raise TypeError('open_verified requires TraceSeal from inspect_jsonl')
    return VerifiedJsonlPass(seal.path, seal)


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def scan_envelope(seal, *, require_terminal=True):
    """Verify event framing, sequence, observed time and snapshot-prefix shape.

    Unknown event kinds are left to semantic auditors. The snapshot SHA syntax
    and prefix count do not authenticate snapshot state. A partial file can be
    scanned with require_terminal=False, but terminal_at_eof remains false.
    All records, including any suffix, must be read before a result is returned.
    """
    if type(require_terminal) is not bool:
        raise TypeError('require_terminal must be a boolean')
    first = previous = horizon = None
    terminal = False
    snapshots = 0
    with open_verified(seal) as reader:
        for record in reader:
            event, index = record.event, record.event_index
            def reject(message):
                raise TraceSourceError(f'event {index}: {message}')
            if type(event.get('seq')) is not int or event['seq'] != index:
                reject('sequence must be the contiguous integer event index')
            kind, t = event.get('kind'), event.get('time')
            if not isinstance(kind, str) or not kind:
                reject('missing event kind')
            if not _number(t):
                reject('event time must be finite')
            if terminal:
                reject('terminal must be the last event')
            if index == 0:
                if kind != 'initial' or not isinstance(event.get('manifest'), dict):
                    reject('missing initial manifest')
                horizon = event['manifest'].get('horizon')
                if not _number(horizon) or horizon < 0:
                    reject('manifest horizon must be finite and nonnegative')
                first = previous = t
            elif kind == 'initial':
                reject('duplicate initial event')
            if t < previous or not 0 <= t <= horizon:
                reject('time reversed or outside declared horizon')
            previous = t
            if kind == 'snapshot_loaded':
                if (first != 0 or type(event.get('prefix_event_count')) is not int
                        or event['prefix_event_count'] != index):
                    reject('snapshot requires complete initial prehistory prefix')
                sha = event.get('snapshot_sha256')
                if not isinstance(sha, str) or re.fullmatch('[0-9a-f]{64}', sha) is None:
                    reject('invalid snapshot SHA-256 syntax')
                snapshots += 1
            elif kind == 'terminal':
                if not math.isclose(t, horizon, rel_tol=1e-10, abs_tol=1e-6):
                    reject('terminal does not reach declared horizon')
                terminal = True
        if first is None:
            raise TraceSourceError('missing initial manifest')
        if require_terminal and not terminal:
            raise TraceSourceError('missing terminal event')
    return TraceEnvelope(reader.receipt, first, previous, horizon, terminal, snapshots)
