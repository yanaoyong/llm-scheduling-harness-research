"""Strict parser for the pinned SchedulingLab zero-based FJSP text format.

No reference values or schedule decisions are loaded by this module. One job per
nonempty line, two-field header only. Other dialects require explicit conversion.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
import re

_INT = re.compile(r'[0-9]+\Z')


class FJSParseError(ValueError):
    """The source text does not match the declared dialect or hard constraints."""


def parse_fjs(path, instance_id=None, family=None) -> dict:
    path = Path(path)
    raw = path.read_bytes()
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise FJSParseError('Source is not UTF-8') from exc
    rows = [(n, line.split()) for n, line in enumerate(text.splitlines(), 1) if line.strip()]
    if not rows:
        raise FJSParseError('Empty instance')
    for n, tokens in rows:
        if any(not _INT.fullmatch(t) for t in tokens):
            raise FJSParseError(f'Line {n}: expected nonnegative decimal integers')
    if len(rows[0][1]) != 2:
        raise FJSParseError('Expected two-field zero-based SchedulingLab header')
    n_jobs, n_machines = map(int, rows[0][1])
    if n_jobs < 1 or n_machines < 1:
        raise FJSParseError('Job and machine counts must be positive')
    if len(rows) != n_jobs + 1:
        raise FJSParseError(f'Expected {n_jobs} job rows, got {len(rows) - 1}')
    jobs = []
    for j, (line_num, row) in enumerate(rows[1:]):
        tokens = list(map(int, row))
        count = tokens[0]
        if count < 1:
            raise FJSParseError(f'Line {line_num}: job has no operations')
        cursor = 1
        ops = []
        for k in range(count):
            if cursor >= len(tokens):
                raise FJSParseError(f'Line {line_num}: truncated operation {k}')
            n_alts = tokens[cursor]
            cursor += 1
            if not 1 <= n_alts <= n_machines:
                raise FJSParseError(f'Line {line_num}: invalid alternative count {n_alts}')
            if cursor + 2 * n_alts > len(tokens):
                raise FJSParseError(f'Line {line_num}: truncated machine-duration pairs')
            alternatives = []
            seen = set()
            for _ in range(n_alts):
                machine, duration = tokens[cursor:cursor + 2]
                cursor += 2
                if not 0 <= machine < n_machines:
                    raise FJSParseError(f'Line {line_num}: machine {machine} outside zero-based range')
                if machine in seen:
                    raise FJSParseError(f'Line {line_num}: duplicate alternative machine {machine}')
                if duration < 1:
                    raise FJSParseError(f'Line {line_num}: duration must be positive')
                seen.add(machine)
                alternatives.append({'machine': machine, 'duration': duration})
            ops.append({'id': f'j{j}o{k}', 'job': j, 'index': k, 'alternatives': alternatives})
        if cursor != len(tokens):
            raise FJSParseError(f'Line {line_num}: {len(tokens) - cursor} unconsumed tokens')
        jobs.append({'id': j, 'operations': ops})
    return {
        'schema_version': 'fjsp-1', 'instance_id': instance_id or path.stem,
        'family': family or 'unspecified', 'machines': list(range(n_machines)),
        'jobs': jobs, 'source': {'format': 'schedulinglab-zero-based-fjsp', 'sha256': hashlib.sha256(raw).hexdigest()},
    }
