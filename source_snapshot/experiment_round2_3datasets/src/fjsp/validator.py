"""Independent FJSP feasibility checker; no parser, decoder, or solver imports.

Capacity intervals are half-open [start,end), all release dates are zero,
processing is nonpreemptive, and job operations form a total precedence chain.
Only complete valid schedules receive a numeric makespan.
"""
from __future__ import annotations
from collections import Counter, defaultdict


def _integer(x):
    return type(x) is int


def _problem_errors(problem):
    errors = []
    if not isinstance(problem, dict) or problem.get('schema_version') != 'fjsp-1':
        return ['problem_schema: expected fjsp-1 object']
    machines = problem.get('machines')
    if not isinstance(machines, list) or not machines or any(not _integer(m) for m in machines) or machines != list(range(len(machines))):
        errors.append('problem_machines: expected contiguous zero-based machine list')
    jobs = problem.get('jobs')
    if not isinstance(jobs, list) or not jobs:
        return errors + ['problem_jobs: expected nonempty job list']
    machine_set = set(machines) if not errors else set()
    for j, job in enumerate(jobs):
        if not isinstance(job, dict) or not _integer(job.get('id')) or job['id'] != j:
            errors.append(f'problem_job: invalid job at {j}')
            continue
        operations = job.get('operations')
        if not isinstance(operations, list) or not operations:
            errors.append(f'problem_operations: job {j} has no operations')
            continue
        for k, op in enumerate(operations):
            if not isinstance(op, dict):
                errors.append(f'problem_operation: invalid operation at {j},{k}')
                continue
            if op.get('id') != f'j{j}o{k}' or not _integer(op.get('job')) or op['job'] != j or not _integer(op.get('index')) or op['index'] != k:
                errors.append(f'problem_operation_id: invalid identity at {j},{k}')
            alts = op.get('alternatives')
            if not isinstance(alts, list) or not alts:
                errors.append(f'problem_alternatives: empty or malformed at {j},{k}')
                continue
            used = set()
            for a in alts:
                if not isinstance(a, dict) or not _integer(a.get('machine')) or a['machine'] not in machine_set or not _integer(a.get('duration')) or a['duration'] <= 0:
                    errors.append(f'problem_alternative: invalid at {j},{k}')
                    continue
                if a['machine'] in used:
                    errors.append(f'problem_alternative: duplicate machine at {j},{k}')
                used.add(a['machine'])
    return errors


def validate(problem, schedule) -> dict:
    errors = _problem_errors(problem)
    if errors:
        return {'valid': False, 'errors': errors, 'makespan': None}
    expected = {op['id']: op for job in problem['jobs'] for op in job['operations']}
    if not isinstance(schedule, dict) or not isinstance(schedule.get('operations'), list):
        return {'valid': False, 'errors': ['schedule_schema: expected operations list'], 'makespan': None}
    rows = schedule['operations']
    counts = Counter()
    placed = {}
    intervals = defaultdict(list)
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f'row_schema: row {i} must be an object')
            continue
        oid = row.get('id')
        if not isinstance(oid, str) or oid not in expected:
            errors.append(f'unknown_operation: row {i}')
            continue
        counts[oid] += 1
        if counts[oid] > 1:
            errors.append(f'duplicate_operation: {oid}')
        machine, start, end = row.get('machine'), row.get('start'), row.get('end')
        if not _integer(machine):
            errors.append(f'machine_type: {oid} must select one integer machine')
            continue
        if not _integer(start) or not _integer(end) or start < 0 or end <= start:
            errors.append(f'time_range: {oid} requires nonnegative integer start < end')
            continue
        qualifications = {a['machine']: a['duration'] for a in expected[oid]['alternatives']}
        if machine not in qualifications:
            errors.append(f'machine_qualification: {oid} machine {machine}')
            continue
        if end - start != qualifications[machine]:
            errors.append(f'processing_duration: {oid} expected {qualifications[machine]}, got {end-start}')
        if counts[oid] == 1:
            placed[oid] = row
        intervals[machine].append((start, end, oid))
    for oid in sorted(expected):
        if counts[oid] == 0:
            errors.append(f'missing_operation: {oid}')
    for job in problem['jobs']:
        ids = [op['id'] for op in job['operations']]
        for before, after in zip(ids, ids[1:]):
            if before in placed and after in placed and placed[before]['end'] > placed[after]['start']:
                errors.append(f'job_precedence: {before} -> {after}')
    for machine, spans in intervals.items():
        latest_end = -1
        latest_id = None
        for start, end, oid in sorted(spans):
            if start < latest_end:
                errors.append(f'machine_capacity: machine {machine}: {latest_id} overlaps {oid}')
            if end > latest_end:
                latest_end, latest_id = end, oid
    return {'valid': not errors, 'errors': errors, 'makespan': max((r['end'] for r in placed.values()), default=0) if not errors else None}
