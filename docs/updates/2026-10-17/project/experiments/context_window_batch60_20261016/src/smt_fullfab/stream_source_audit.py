"""File-only streaming plan-source audit; existing consumers are unchanged.

The reference contract is audit.py::audit_plan_sources, not physical replay or
opportunity coverage. No legacy auditor, environment, controller or solver is
imported. Plans, executed identities and every coverage-gap detail live in an
ephemeral SQLite index; the immutable raw JSONL remains the source of evidence.
The full report is streamed to a new file after a verified complete input pass.
Its audit_version identifies this implementation; _source_evidence embeds the
verified complete-read receipt. Other report fields follow the reference source-
audit contract, including the existing 200-error limit.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from dataclasses import asdict
import hashlib
from itertools import chain
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile

from .trace_source import TraceSeal, inspect_jsonl, open_verified

VERSION = 'smt-fullfab-stream-plan-source-audit-v3'
REFERENCE_VERSION = 'smt-fullfab-independent-plan-audit-v3'
PHYSICAL_KINDS = {'initial', 'release', 'ready', 'skip', 'dispatch', 'downtime',
                  'operation_complete', 'rework', 'lot_complete', 'terminal'}
CONTROL_KINDS = {'plan_committed', 'coverage_gap', 'plan_invalidated', 'time_advance',
                 'decision_opportunity', 'action', 'plan_exhausted', 'snapshot_loaded'}


def _number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _key(value):
    """Preserve Python dict/set equality for JSON scalar identity keys.

    In particular integer 1 and string '1' remain distinct. Invalid bool/float/
    None IDs still receive the reference validation errors; their storage must
    not erase subsequent errors. Numeric equality aliases follow Python, as in
    the reference dict. Containers raise the original unhashable-type error.
    """
    hash(value)
    if isinstance(value, str):
        return 's:' + json.dumps(value)
    if value is None:
        return 'null'
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return 'n:' + repr(value)
        numerator, denominator = value.as_integer_ratio()
        return f'n:{numerator}/{denominator}'
    raise TypeError('unsupported non-JSON identity')


class _Plans:
    """Exact disk mapping with a one-plan cache, never all plan history."""
    def __init__(self, db):
        self.db = db
        self.cache_key = object()
        self.cache_value = None

    def __contains__(self, version):
        return self.db.execute('SELECT 1 FROM plans WHERE key=?', (_key(version),)).fetchone() is not None

    def __getitem__(self, version):
        key = _key(version)
        if key == self.cache_key:
            return self.cache_value
        row = self.db.execute('SELECT payload FROM plans WHERE key=?', (key,)).fetchone()
        if row is None:
            raise KeyError(version)
        plan, entries = json.loads(row[0])
        plan['task_map'] = dict(entries)
        self.cache_key, self.cache_value = key, plan
        return plan

    def __setitem__(self, version, value):
        key = _key(version)
        # Entry pairs preserve task-key types, unlike JSON object-key coercion.
        payload = json.dumps([{k: v for k, v in value.items() if k != 'task_map'},
                              list(value['task_map'].items())], separators=(',', ':'))
        self.db.execute('INSERT INTO plans(key,payload,hold_count) VALUES(?,?,?) '
                        'ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,hold_count=excluded.hold_count',
                        (key, payload, len(value.get('holds', []))))
        self.cache_key, self.cache_value = key, value

    def __len__(self):
        return self.db.execute('SELECT count(*) FROM plans').fetchone()[0]

    def hold_count(self):
        return self.db.execute('SELECT coalesce(sum(hold_count),0) FROM plans').fetchone()[0]


class _Done:
    def __init__(self, db):
        self.db = db

    def __contains__(self, identity):
        version, task = identity
        return self.db.execute('SELECT 1 FROM done WHERE version=? AND task=?',
                               (_key(version), _key(task))).fetchone() is not None

    def add(self, identity):
        version, task = identity
        self.db.execute('INSERT OR IGNORE INTO done(version,task) VALUES(?,?)',
                        (_key(version), _key(task)))


def _replay(reader, db):
    """Preserve reference check ordering and partial-state behavior on bad events."""
    errors, plans, active, done, pending = [], _Plans(db), None, _Done(db), defaultdict(list)
    dispatches = virtual = gaps = opportunities = 0
    dispatched_machines = set()

    def check(ok, message):
        if not ok and len(errors) < 200:
            errors.append(message)

    first = next(reader, None)
    if first is None or first.event.get('kind') != 'initial':
        # A failure report still binds the whole input, never only its first row.
        for _ in reader:
            pass
        return {'valid': False, 'errors': ['missing initial manifest'], 'audit_version': VERSION}
    manifest = first.event['manifest']
    machines = {m['id']: m for m in manifest['machines']}
    manifest_lots = {lot['id']: lot for lot in manifest['lots']}
    production = {mid for mid, m in machines.items() if m['group'] != 'Delay_32'}
    declared = set(manifest['controlled_machine_ids'])
    check(declared == production, 'declared controller domain does not exactly equal all production machines')
    first_time = previous = first.event['time']
    for record in chain((first,), reader):
        index, event = record.event_index, record.event
        if index % 256 == 0:
            db.commit()
        t, kind = event.get('time'), event.get('kind')
        check(event.get('seq') == index, f'{index}: sequence gap')
        if not _number(t):
            check(False, f'{index}: invalid time')
            continue
        check(t >= previous, f'{index}: time reversed')
        previous = t
        check(kind in PHYSICAL_KINDS | CONTROL_KINDS, f'{index}: unknown or unsupported event {kind}')
        try:
            if kind == 'plan_committed':
                plan = event['plan']
                version = plan['version']
                check(isinstance(version, (str, int)) and not isinstance(version, bool), f'{index}: invalid version')
                check(version not in plans, f'{index}: duplicate plan version')
                for key in ('created_at', 'valid_until', 'freeze_until'):
                    check(_number(plan[key]), f'{index}: invalid {key}')
                check(plan['created_at'] == t, f'{index}: commit time differs from creation time')
                check(t <= plan['freeze_until'] <= plan['valid_until'] <= manifest['horizon'] and t < plan['valid_until'], f'{index}: invalid plan/freeze interval')
                check(sorted(plan['scope']) == sorted(production), f'{index}: plan scope does not explicitly include every production machine')
                check(isinstance(plan['reason'], str) and bool(plan['reason'].strip()), f'{index}: missing revision reason')
                tasks, new_pending = {}, defaultdict(list)
                identities = set()
                for task in plan['tasks']:
                    tid, mid = task['id'], task['machine']
                    check(isinstance(tid, (str, int)) and not isinstance(tid, bool), f'{index}: invalid task id')
                    check(tid not in tasks, f'{index}: duplicate task id')
                    check(mid in production, f'{index}: planned non-production/unknown machine')
                    check(bool(task['lot_ids']) and len(set(task['lot_ids'])) == len(task['lot_ids']), f'{index}: empty/duplicate task lots')
                    check(len(task['steps']) == len(task['lot_ids']) == len(task['visits']), f'{index}: task operation arity')
                    planned_steps = []
                    for lid, step, visit in zip(task['lot_ids'], task['steps'], task['visits']):
                        check(lid in manifest_lots, f'{index}: planned unknown lot')
                        check(type(step) is int and type(visit) is int and step > 0 and visit > 0, f'{index}: invalid planned step/visit')
                        if lid in manifest_lots and type(step) is int:
                            route = manifest['routes'][manifest_lots[lid]['route']]
                            check(1 <= step <= len(route), f'{index}: planned step outside route')
                            if 1 <= step <= len(route):
                                s = route[step - 1]
                                planned_steps.append((manifest_lots[lid]['part'], s))
                                check(mid in machines and s['family'] == machines[mid]['family'], f'{index}: planned unqualified machine')
                    if planned_steps:
                        part, start_step = planned_steps[0]
                        check(start_step['batch_min'] <= len(task['lot_ids']) <= start_step['batch_max'], f'{index}: planned batch outside bounds')
                        check(all((p, s['step'], s['name']) == (part, start_step['step'], start_step['name']) for p, s in planned_steps), f'{index}: planned incompatible batch')
                    check(_number(task['not_before']), f'{index}: invalid not_before')
                    frozen_carry = bool(active is not None and t < plans[active]['freeze_until'] and
                                        tid in pending[mid] and plans[active]['task_map'][tid] == task and
                                        task['not_before'] < plans[active]['freeze_until'])
                    check((t <= task['not_before'] or frozen_carry) and task['not_before'] <= plan['valid_until'],
                          f'{index}: task outside plan validity or not an exact frozen carry')
                    if task.get('latest_start') is not None:
                        check(_number(task['latest_start']) and task['latest_start'] >= task['not_before'], f'{index}: invalid latest_start')
                    if task.get('expected_start') is not None:
                        check(_number(task['expected_start']) and task['expected_start'] >= task['not_before'], f'{index}: invalid expected_start')
                    for identity in zip(task['lot_ids'], task['steps'], task['visits']):
                        check(identity not in identities, f'{index}: duplicate planned lot operation')
                        identities.add(identity)
                    tasks[tid] = task
                    new_pending[mid].append(tid)
                if active is not None:
                    old = plans[active]
                    frozen_by_machine = defaultdict(list)
                    for mid, tids in pending.items():
                        for tid in tids:
                            task = old['task_map'][tid]
                            planned_start = task['not_before']
                            if planned_start < old['freeze_until'] and t < old['freeze_until']:
                                frozen_by_machine[mid].append(tid)
                                check(tid in tasks and tasks[tid] == task, f'{index}: changed or dropped frozen task {tid}')
                    if frozen_by_machine:
                        check(plan['freeze_until'] >= old['freeze_until'],
                              f'{index}: shortened prior freeze interval with pending frozen tasks')
                    for mid, frozen_ids in frozen_by_machine.items():
                        check([tid for tid in new_pending[mid] if tid in frozen_ids] == frozen_ids,
                              f'{index}: reordered frozen tasks')
                holds = plan.get('holds', [])
                hold_keys = set()
                for hold in holds:
                    check(hold['machine'] in production, f'{index}: hold non-production machine')
                    hold_key = (hold['machine'], hold.get('after_task_id'))
                    check(hold_key not in hold_keys, f'{index}: duplicate hold activation condition')
                    check(_number(hold['until']) and t < hold['until'] <= plan['valid_until'], f'{index}: invalid hold interval')
                    check(bool(hold.get('reason')), f'{index}: hold missing reason')
                    if hold.get('after_task_id') is not None:
                        task = tasks.get(hold['after_task_id'])
                        check(task is not None and task['machine'] == hold['machine'], f'{index}: conditional hold refers to no task on its machine')
                    hold_keys.add(hold_key)
                plans[version] = {**plan, 'task_map': tasks}
                active, pending = version, new_pending
            elif kind == 'dispatch':
                mid = event['machine']
                check(mid in machines, f'{index}: unknown dispatch machine')
                if mid not in production:
                    check(event.get('owner') == 'environment', f'{index}: virtual process has controller ownership')
                    virtual += 1
                    continue
                dispatches += 1
                dispatched_machines.add(mid)
                check(event.get('owner') == 'plan', f'{index}: production dispatch missing plan ownership')
                version, tid = event.get('plan_version'), event.get('plan_task_id')
                check(version in plans, f'{index}: missing committed source plan')
                check(version == active, f'{index}: dispatch references superseded plan')
                if version not in plans:
                    continue
                plan = plans[version]
                check(tid in plan['task_map'], f'{index}: missing source task')
                if tid not in plan['task_map']:
                    continue
                task = plan['task_map'][tid]
                check((version, tid) not in done, f'{index}: task dispatched twice')
                check(bool(pending[mid]) and pending[mid][0] == tid, f'{index}: machine task order changed')
                for trace_key, task_key in (('machine', 'machine'), ('lots', 'lot_ids'), ('steps', 'steps'), ('visits', 'visits')):
                    check(event[trace_key] == task[task_key], f'{index}: dispatch differs from plan {task_key}')
                check(plan['created_at'] <= t <= plan['valid_until'], f'{index}: dispatch outside plan interval')
                check(t >= task['not_before'], f'{index}: dispatch before start condition')
                if task.get('latest_start') is not None:
                    check(t <= task['latest_start'], f'{index}: dispatch after latest_start')
                for hold in plan.get('holds', []):
                    hold_active = hold.get('after_task_id') is None or ((version, hold['after_task_id']) in done and not pending[hold['machine']])
                    check(hold['machine'] != mid or not hold_active or t >= hold['until'], f'{index}: dispatch during explicit hold')
                done.add((version, tid))
                if tid in pending[mid]:
                    pending[mid].remove(tid)
            elif kind == 'coverage_gap':
                db.execute('INSERT INTO gaps(event_index,payload) VALUES(?,?)',
                           (index, json.dumps(event, separators=(',', ':'))))
                gaps += 1
            elif kind == 'decision_opportunity':
                opportunities += 1
            elif kind == 'snapshot_loaded':
                check(first_time == 0 and event.get('prefix_event_count') == index,
                      f'{index}: snapshot lacks complete prehistory prefix')
                sha = event.get('snapshot_sha256', '')
                check(isinstance(sha, str) and len(sha) == 64 and all(c in '0123456789abcdef' for c in sha),
                      f'{index}: invalid snapshot state hash')
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            check(False, f'{index}: malformed plan/trace: {exc}')
    return {'valid': not errors, 'errors': errors, 'audit_version': VERSION,
            'production_machine_count': len(production), 'declared_control_machine_count': len(declared),
            'declared_full_factory_domain': declared == production,
            'production_dispatches': dispatches, 'virtual_process_dispatches': virtual,
            'production_machines_with_dispatch': len(dispatched_machines),
            'plans_committed': len(plans), 'coverage_gap_events': gaps,
            'coverage_gap_details': None, 'decision_opportunity_events': opportunities,
            'explicit_hold_count': plans.hold_count(),
            'actual_dispatch_provenance_complete': bool(dispatches) and not errors,
            'absence_of_unreported_legal_demand_certified': False,
            'scope': 'exact production dispatch provenance and declared responsibility; legal-demand completeness requires additional independent opportunity replay'}


class _HashingTextWriter:
    """Encode once and hash exactly the bytes written to the private report."""
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()

    def write(self, text):
        data = text.encode('utf-8')
        if self.stream.write(data) != len(data):
            raise OSError('short report write')
        self.digest.update(data)
        return len(text)


def _write_report(path, result, db):
    """Create-new publish and return the hash of the bytes we actually wrote.

    Do not reopen the published path to construct its evidence: another writer
    could replace it in that interval. As with any saved content address, callers
    must compare this hash before trusting later reads of report_path.
    """
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.partial', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as binary:
            stream = _HashingTextWriter(binary)
            stream.write('{')
            for number, (key, value) in enumerate(result.items()):
                if number:
                    stream.write(',')
                stream.write(json.dumps(key) + ':')
                if key == 'coverage_gap_details':
                    stream.write('[')
                    for gap_index, (payload,) in enumerate(db.execute('SELECT payload FROM gaps ORDER BY event_index')):
                        if gap_index:
                            stream.write(',')
                        stream.write(payload)
                    stream.write(']')
                else:
                    json.dump(value, stream, separators=(',', ':'))
            stream.write('}\n')
            binary.flush()
            os.fsync(binary.fileno())
            report_sha256 = stream.digest.hexdigest()
        # link() is atomic create-new on the same filesystem; unlike replace(),
        # it cannot overwrite an existing report even if a race creates one.
        os.link(temporary, path)
        return report_sha256
    finally:
        Path(temporary).unlink(missing_ok=True)


def audit_plan_sources(source, *, report_path, work_dir=None):
    """Audit one whole JSONL source and return a small evidence descriptor.

    ``report_path`` must be new. The complete report preserves every gap detail
    in source order; it is not returned as an ever-growing Python list.
    Input mutation, undecodable JSON and errors before publication raise without
    publishing a report. A post-publication cleanup/return error may leave the
    complete report; its embedded _source_evidence preserves the verified receipt
    without depending on successful descriptor return or a separate sidecar.
    Source-semantic errors produce valid=False with the reference error contract.
    A nonterminal prefix may pass source provenance: that is not a completed
    physical-window certificate. RAM still includes the manifest and active/new
    plans; disk and the full report grow with evidence. No long-run readiness is
    implied. ``work_dir`` optionally selects the parent of a temporary SQLite dir.
    """
    output = Path(report_path).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    seal = source if isinstance(source, TraceSeal) else inspect_jsonl(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='smt-source-audit-', dir=work_dir) as temporary:
        with closing(sqlite3.connect(str(Path(temporary) / 'index.sqlite'))) as db:
            db.execute('PRAGMA cache_size=-2048')
            db.execute('PRAGMA temp_store=FILE')
            db.executescript('CREATE TABLE plans(key TEXT PRIMARY KEY,payload TEXT NOT NULL,hold_count INTEGER NOT NULL);'
                             'CREATE TABLE done(version TEXT,task TEXT,PRIMARY KEY(version,task));'
                             'CREATE TABLE gaps(event_index INTEGER PRIMARY KEY,payload TEXT NOT NULL);')
            with open_verified(seal) as reader:
                result = _replay(reader, db)
            db.commit()
            evidence = {'implementation_version': VERSION,
                        'reference_contract_version': REFERENCE_VERSION,
                        'reference_function': 'src.smt_fullfab.audit.audit_plan_sources',
                        'source_receipt': asdict(reader.receipt),
                        'absence_of_unreported_legal_demand_certified': False,
                        'physical_audit_performed': False, 'complete_jsonl_pass': True}
            result['_source_evidence'] = evidence
            report_sha256 = _write_report(output, result, db)
    return {**evidence,
            'report_path': str(output), 'report_sha256': report_sha256,
            'valid': result['valid'], 'errors': result['errors'],
            'actual_dispatch_provenance_complete': result.get('actual_dispatch_provenance_complete', False)}
