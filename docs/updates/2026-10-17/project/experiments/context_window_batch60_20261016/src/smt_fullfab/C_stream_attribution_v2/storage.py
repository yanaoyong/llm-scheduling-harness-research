"""Private disk containers for the attribution draft, not a durable run store.

Only cache payloads leave RAM. Python dictionary key semantics and insertion
order remain in the small key index. JSONL parses all input before exposure;
slices materialize lists for the original ledger-prefix JSON hash. No simulator
or planner is imported. The caller
must exclusively own the create-new scratch directory throughout this context.
"""
from collections.abc import Mapping, Sequence
from contextlib import closing, contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import stat


class EvidenceChangedError(OSError):
    pass


def identity(info):
    if not stat.S_ISREG(info.st_mode):
        raise EvidenceChangedError('regular evidence file required')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def legacy_lines(stream):
    """Exact str.splitlines delimiters after TextIO universal newline decode.

    A physical line iterator alone would wrongly accept literal U+2028/U+0085
    inside JSON strings that the original read_text().splitlines() rejects.
    Auxiliary storage is at most the largest logical line plus a 64 KiB chunk.
    """
    separator = re.compile(r'[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]')
    pieces = []
    for chunk in iter(lambda: stream.read(65536), ''):
        start = 0
        for match in separator.finditer(chunk):
            pieces.append(chunk[start:match.start()])
            yield ''.join(pieces)
            pieces.clear()
            start = match.end()
        pieces.append(chunk[start:])
    if pieces:
        last = ''.join(pieces)
        if last:
            yield last


class DiskSequence(Sequence):
    def __init__(self, owner, namespace):
        self.owner, self.namespace, self.references = owner, namespace, []

    def append(self, value):
        sha = self.owner.put(self.namespace, len(self.references), value)
        self.references.append(sha)

    def __len__(self):
        return len(self.references)

    def __getitem__(self, index):
        if isinstance(index, slice):
            # The unchanged ledger audit hashes ledger[:row_index] using
            # json.dumps. Preserve an actual list here, including allocation:
            # an arbitrary Sequence view is not a JSON-serializable list.
            return [self[position] for position in range(len(self))[index]]
        # range indexing preserves Python bool/int/__index__ and negative-index
        # behavior; string/float keys still raise rather than silently casting.
        position = range(len(self))[index]
        return self.owner.get(self.namespace, position, self.references[position])

    def __iter__(self):
        for index, sha in enumerate(self.references):
            yield self.owner.get(self.namespace, index, sha)


class DiskMapping(Mapping):
    """JSON values outside RAM; dictionary keys retain exact Python semantics.

    String '1' and integer 1 are distinct. Python's original bool/int equality
    and unhashable-key errors are preserved instead of converting keys to text.
    Values are immutable snapshots after insertion; consumers must not mutate
    returned descendants expecting a write-through cache.
    """
    def __init__(self, owner, namespace):
        self.owner, self.namespace, self.positions = owner, namespace, {}

    def __setitem__(self, key, value):
        original = self.positions.get(key)
        position = len(self.positions) if original is None else original[0]
        sha = self.owner.put(self.namespace, position, value)
        self.positions[key] = (position, sha)

    def __getitem__(self, key):
        position, sha = self.positions[key]
        return self.owner.get(self.namespace, position, sha)

    def __len__(self):
        return len(self.positions)

    def __iter__(self):
        return iter(self.positions)


class PriorOutputs:
    """Repeatable original-output membership without loading previous prompts."""
    def __init__(self, outputs, before):
        self.outputs, self.before = outputs, before

    def __iter__(self):
        for index in sorted(self.outputs):
            if index < self.before:
                yield self.outputs[index]

    def __contains__(self, value):
        return any(item == value for item in self)


class AuditStorage:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700)  # Never reuse another audit's index.
        self.db_path = self.directory / 'scratch.sqlite'
        with self.db_path.open('xb'):
            pass
        created = self.db_path.stat(follow_symlinks=False)
        self.db_identity = (created.st_dev, created.st_ino)
        self.connection = None
        self.closed = False
        try:
            self.connection = sqlite3.connect(self.db_path)
            self._open()
            for statement in ('PRAGMA cache_size=-2048', 'PRAGMA temp_store=FILE',
                              'CREATE TABLE records(namespace TEXT, position INTEGER, payload TEXT, PRIMARY KEY(namespace,position))'):
                with closing(self.connection.execute(statement)):
                    pass
        except BaseException as error:
            try:
                if self.connection is not None:
                    self.connection.close()
            except Exception as cleanup:
                error.add_note('scratch initialization cleanup also failed: ' + repr(cleanup))
            self.closed = True
            raise
        self.next_namespace = 0
        self.sources, self.parsed_lines = {}, {}

    def __enter__(self):
        return self

    def __exit__(self, kind, exception, tb):
        try:
            self.close()
        except Exception as cleanup:
            if exception is None:
                raise
            exception.add_note('scratch close also failed: ' + repr(cleanup))
        return False

    def close(self):
        if not self.closed:
            try:
                self._open()
                self.connection.commit()
                self._open()
            except BaseException as error:
                try:
                    self.connection.close()
                except BaseException as cleanup:
                    error.add_note('scratch connection close also failed: ' + repr(cleanup))
                self.closed = True
                raise
            else:
                try:
                    self.connection.close()
                finally:
                    self.closed = True

    def namespace(self, label):
        self.next_namespace += 1
        return str(self.next_namespace) + ':' + label

    def _open(self):
        if self.closed:
            raise RuntimeError('audit scratch is closed')
        info = self.db_path.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != self.db_identity:
            raise EvidenceChangedError('audit scratch DB path replaced')

    def sequence(self, label):
        return DiskSequence(self, self.namespace(label))

    def mapping(self, label):
        return DiskMapping(self, self.namespace(label))

    def put(self, namespace, position, value):
        # Inputs were already decoded using legacy json.loads. Preserve finite
        # and nonfinite legacy values here; semantic checks reject where required.
        self._open()
        payload = json.dumps(value, ensure_ascii=True, separators=(',', ':'))
        with closing(self.connection.execute('INSERT OR REPLACE INTO records VALUES(?,?,?)', (namespace, position, payload))):
            pass
        self._open()
        return hashlib.sha256(payload.encode()).hexdigest()

    def get(self, namespace, position, expected_sha256):
        self._open()
        with closing(self.connection.execute('SELECT payload FROM records WHERE namespace=? AND position=?', (namespace, position))) as cursor:
            row = cursor.fetchone()
        if row is None:
            raise KeyError((namespace, position))
        if hashlib.sha256(row[0].encode()).hexdigest() != expected_sha256:
            raise EvidenceChangedError('audit scratch payload changed')
        value = json.loads(row[0])
        self._open()
        return value

    def collect(self, label, values):
        result = self.sequence(label)
        for value in values:
            result.append(value)
        return result

    def _fence(self, path, expected):
        if identity(path.stat(follow_symlinks=False)) != expected:
            raise EvidenceChangedError('source identity changed: ' + str(path))

    def sha_file(self, path):
        path = Path(path).absolute()
        if path in self.sources:
            record = self.sources[path]
            self._fence(path, record['identity'])
            return record['sha256']
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            before = identity(os.fstat(stream.fileno()))
            self._fence(path, before)
            sha, size = hashlib.sha256(), 0
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                sha.update(block)
                size += len(block)
            if size != before[2] or identity(os.fstat(stream.fileno())) != before:
                raise EvidenceChangedError('source changed while hashing: ' + str(path))
            self._fence(path, before)
        self.sources[path] = {'sha256': sha.hexdigest(), 'bytes': size, 'identity': before}
        return sha.hexdigest()

    @contextmanager
    def text_stream(self, path):
        path = Path(path).absolute()
        self.sha_file(path)
        expected = self.sources[path]['identity']
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'r') as stream:
            if identity(os.fstat(stream.fileno())) != expected:
                raise EvidenceChangedError('source FD changed before decode: ' + str(path))
            self._fence(path, expected)
            yield stream
            if identity(os.fstat(stream.fileno())) != expected:
                raise EvidenceChangedError('source FD changed during decode: ' + str(path))
            self._fence(path, expected)

    def read_text(self, path):
        with self.text_stream(path) as stream:
            return stream.read()

    def read(self, path, *, lines=False):
        path = Path(path).absolute()
        self.sha_file(path)
        if not lines:
            return json.loads(self.read_text(path))
        if path in self.parsed_lines:
            return self.parsed_lines[path]
        result = self.sequence('jsonl')
        with self.text_stream(path) as stream:
            for line in legacy_lines(stream):
                if line.strip():
                    result.append(json.loads(line))
        # No incomplete/invalid sequence is exposed or cached. Partial scratch
        # rows can remain as diagnostic cache; they are not a success marker.
        self.parsed_lines[path] = result
        return result

    def receipts(self):
        self._open()
        for path, record in self.sources.items():
            self._fence(path, record['identity'])
        return {str(path): {'sha256': record['sha256'], 'bytes': record['bytes']}
                for path, record in self.sources.items()}
