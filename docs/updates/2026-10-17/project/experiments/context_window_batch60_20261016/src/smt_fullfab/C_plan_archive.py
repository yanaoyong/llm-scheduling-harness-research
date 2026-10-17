"""Exact per-observation history/candidate storage; never selects or repairs.

Only counters and expected file hashes remain resident. Full history is decoded
for the current prompt, and a candidate is loaded only on the model's explicit
apply index. Original array order/JSON types survive. This is not a generic
concurrent database or a physical/model attribution certificate.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat


def encode(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def identity(info):
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('regular original file required')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def raw_snapshot(path, expected_sha256=None):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        before = identity(os.fstat(stream.fileno()))
        if before != identity(os.stat(path, follow_symlinks=False)):
            raise ValueError('original path differs before read')
        raw = stream.read()
        if len(raw) != before[2] or identity(os.fstat(stream.fileno())) != before or identity(os.stat(path, follow_symlinks=False)) != before:
            raise ValueError('original file changed during read')
    sha = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and sha != expected_sha256:
        raise ValueError('original evidence hash changed')
    return raw, {'sha256': sha, 'bytes': len(raw)}


def parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate original JSON key')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs)
    digest(value)
    return value


def snapshot(path, expected_sha256=None):
    raw, receipt = raw_snapshot(path, expected_sha256)
    return parse(raw), receipt


def write_new(path, value):
    return write_raw_new(path, encode(value))


def write_raw_new(path, raw):
    with Path(path).open('xb') as stream:
        written = stream.write(raw)
        if type(written) is not int or written != len(raw):
            raise OSError('short original evidence write')
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


class PlanArchive:
    """One create-new plan context; exact append order, no pruning/selection."""
    def __init__(self, directory, *, run_dir, plan_index):
        self.directory = Path(directory)
        self.directory.mkdir()
        self.run_dir = Path(run_dir).resolve()
        if type(plan_index) is not int or plan_index < 0:
            raise ValueError('exact plan index required')
        self.plan_index = plan_index
        self.history_hashes, self.candidate_hashes = [], []  # O(number of actions), not full contexts/plans.
        self.closed = False
        write_new(self.directory / 'context.json', {'schema': 'draft-C8-plan-archive-v2', 'plan_index': plan_index})

    def _open(self):
        if self.closed:
            raise ValueError('plan archive already closed')

    def append_history(self, entry):
        self._open()
        index = len(self.history_hashes)
        sha = write_new(self.directory / f'history_{index:06d}.json', entry)
        self.history_hashes.append(sha)
        return index

    def history_for_prompt(self):
        self._open()
        return [snapshot(self.directory / f'history_{i:06d}.json', sha)[0] for i, sha in enumerate(self.history_hashes)]

    def record_candidate(self, *, path, expected_candidate_sha256, valid, feedback, method, model_index, call_id):
        self._open()
        path = Path(path).resolve()
        if not path.is_relative_to(self.run_dir) or type(valid) is not bool or type(model_index) is not int:
            raise ValueError('original run-local candidate/type required')
        if (type(expected_candidate_sha256) is not str or len(expected_candidate_sha256) != 64
                or any(c not in '0123456789abcdef' for c in expected_candidate_sha256)):
            raise ValueError('original in-memory candidate SHA required')
        value, receipt = snapshot(path)
        if digest(value) != expected_candidate_sha256:
            raise ValueError('candidate file differs from original tool outcome digest')
        index = len(self.candidate_hashes)
        record = {'plan_index': self.plan_index, 'candidate_index': index, 'path': path.relative_to(self.run_dir).as_posix(),
                  'receipt': receipt, 'candidate_sha256': expected_candidate_sha256, 'valid': valid,
                  'feedback': deepcopy(feedback), 'method': method, 'model_index': model_index, 'call_id': call_id}
        sha = write_new(self.directory / f'candidate_{index:06d}.json', record)
        self.candidate_hashes.append(sha)
        return index

    def load_explicit_candidate(self, index):
        self._open()
        if type(index) is not int or not 0 <= index < len(self.candidate_hashes):
            raise ValueError('explicit existing candidate index required')
        record, _ = snapshot(self.directory / f'candidate_{index:06d}.json', self.candidate_hashes[index])
        if record['plan_index'] != self.plan_index or record['candidate_index'] != index or record['valid'] is not True:
            raise ValueError('explicit candidate is invalid or belongs to another observation')
        path = self.run_dir / record['path']
        if not path.resolve().is_relative_to(self.run_dir):
            raise ValueError('candidate escaped original run')
        value, _ = snapshot(path, record['receipt']['sha256'])
        if digest(value) != record['candidate_sha256']:
            raise ValueError('candidate content differs')
        return value, record

    def close(self, legacy_history_path):
        self._open()
        # Preserve the complete old-format history file without creating another
        # full array. Prompt materialization remains only within this observation.
        with Path(legacy_history_path).open('xb') as stream:
            def put(raw):
                if stream.write(raw) != len(raw):
                    raise OSError('short final history write')
            put(b'[')
            for index, sha in enumerate(self.history_hashes):
                value, _ = snapshot(self.directory / f'history_{index:06d}.json', sha)
                if index:
                    put(b',')
                put(encode(value).rstrip(b'\n'))
            put(b']\n')
            stream.flush()
            os.fsync(stream.fileno())
        write_new(self.directory / 'closure.json', {'plan_index': self.plan_index,
            'history_sha256': list(self.history_hashes), 'candidate_reference_sha256': list(self.candidate_hashes),
            'choice_inferred': False})
        self.closed = True
