"""Two-pass snapshot-1 writer for a paused, exclusively owned environment.

The state view references the existing in-memory trace; it does not deepcopy
history or build whole-document JSON strings. This is not a concurrent snapshot
or a disk-trace adapter. The existing from_snapshot reader remains unchanged.
"""
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path

from . import environment

STATE_FIELDS = ('seed', 'horizon', 't', 'seq', 'dispatch_id', 'decisions', 'releases',
                'completed', 'finished', 'wait_until', 'lots', 'machine_state',
                'jobs', 'calendars', 'pm_counters', 'queue_area', 'last_area_t',
                'manifest', 'plan', 'observation_start')
BUFFER_BYTES = 64 * 1024


def _json_key(key):
    """The key spelling produced by the legacy JSON round trip."""
    if type(key) is str:
        # JSON decoding joins escaped surrogate pairs before key collision/sort.
        # Only a single key scalar is decoded, never a state/history container.
        return json.loads(json.encoder.encode_basestring_ascii(key))
    if key is True:
        return 'true'
    if key is False:
        return 'false'
    if key is None:
        return 'null'
    if type(key) is int:
        return str(key)
    if type(key) is float and math.isfinite(key):
        return repr(key)
    raise TypeError('snapshot supports only finite JSON scalar dictionary keys')


def _tokens(value, active):
    """Canonical tokens equivalent to dumps(loads(dumps(value)), sort_keys=True).

    Only finite JSON values and the standard containers used by the environment
    are accepted. Per-object indexes hold references, never copied descendants.
    """
    kind = type(value)
    if value is None:
        yield 'null'
    elif kind is bool:
        yield 'true' if value else 'false'
    elif kind is str:
        yield json.encoder.encode_basestring_ascii(value)
    elif kind is int:
        yield str(value)
    elif kind is float:
        if not math.isfinite(value):
            raise ValueError('snapshot rejects non-finite values outside the JSON domain')
        yield repr(value)
    elif kind in (dict, Counter, defaultdict, list, tuple):
        identity = id(value)
        if identity in active:
            raise ValueError('snapshot rejects circular JSON structures')
        active.add(identity)
        try:
            if kind in (dict, Counter, defaultdict):
                normalized = {}
                for key, child in value.items():
                    key = _json_key(key)
                    # Legacy dumps validates even values later lost to key aliases.
                    if key in normalized:
                        for _ in _tokens(normalized[key], active):
                            pass
                    normalized[key] = child
                yield '{'
                for index, key in enumerate(sorted(normalized)):
                    if index:
                        yield ','
                    yield json.encoder.encode_basestring_ascii(key)
                    yield ':'
                    yield from _tokens(normalized[key], active)
                yield '}'
            else:
                yield '['
                for index, child in enumerate(value):
                    if index:
                        yield ','
                    yield from _tokens(child, active)
                yield ']'
        finally:
            active.remove(identity)
    else:
        raise TypeError('snapshot rejects unsupported JSON value type: ' + kind.__name__)


def _chunks(value):
    buffer = bytearray()
    for token in _tokens(value, set()):
        raw = token.encode('ascii')  # ensure_ascii=True is part of legacy digest.
        if len(buffer) + len(raw) > BUFFER_BYTES and buffer:
            yield bytes(buffer)
            buffer.clear()
        if len(raw) >= BUFFER_BYTES:
            yield raw  # Largest scalar may exceed the output buffering threshold.
        else:
            buffer.extend(raw)
    if buffer:
        yield bytes(buffer)


def _state_view(env):
    state = {key: getattr(env, key) for key in STATE_FIELDS}
    state.update(q=env.q, waiting={key: sorted(value) for key, value in env.waiting.items()},
                 processing_by_machine={str(key): sorted(value) for key, value in env.processing_by_machine.items()},
                 stats=dict(env.stats), executed_tasks=sorted(env.executed_tasks),
                 plan_versions=sorted(env.plan_versions), trace=env.trace)
    return state



def _checked_write(stream, raw):
    """Fail closed on a short/invalid count; keep partial evidence, never retry."""
    written = stream.write(raw)
    if type(written) is not int or written != len(raw):
        raise OSError('snapshot write returned an incomplete or invalid byte count')


def write_snapshot(env, path):
    """Write one new snapshot; return the legacy state SHA256.

    Caller must pause and exclusively own env through both passes. On failure,
    any created empty/partial file is retained, never overwritten or promoted as
    successful. RAM trace remains resident; auxiliary memory is dictionary-key
    indexes, sorted set-derived fields, nesting, the largest scalar and a buffer.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        state = _state_view(env)
        hasher = hashlib.sha256()
        for chunk in _chunks(state):
            hasher.update(chunk)
        state_sha256 = hasher.hexdigest()
        physics = Path(environment.__file__).parents[1] / 'smt/environment.py'
        document = {'schema': 'smt-fullfab-snapshot-1', 'version': environment.VERSION,
                    'implementation_sha256': environment.snapshot_dependencies(),
                    'physics_sha256': hashlib.sha256(physics.read_bytes()).hexdigest(),
                    'data_hashes': env.manifest['data_hashes'], 'state': state,
                    'state_sha256': state_sha256,
                    'random_mechanism': 'event-keyed SHA256; no mutable global RNG',
                    'initialization': 'official WIP cold start; any prehistory is retained, not asserted steady state'}
        for chunk in _chunks(document):
            _checked_write(stream, chunk)
        _checked_write(stream, b'\n')
        stream.flush()
        os.fsync(stream.fileno())
    return state_sha256
