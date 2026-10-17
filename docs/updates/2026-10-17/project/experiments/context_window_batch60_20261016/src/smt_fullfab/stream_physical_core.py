"""Physical event fold with SQLite-backed historical records.

No simulator/controller/optimizer imports. The old auditor is a test oracle only.
This iterable API does NOT bind projection/source receipts or publish a durable
report. Its final batch-fill array is still materialized for small-test parity.
"""
from collections import Counter
from contextlib import closing, contextmanager
import hashlib
import json
import math
from pathlib import Path
import random
import sqlite3
from tempfile import TemporaryDirectory

VERSION = 'smt-fullfab-stream-physical-core-v1'
REFERENCE_VERSION = 'smt-independent-audit-v2'


def sampled(seed, key, distribution):
    raw = json.dumps([seed, key], separators=(',', ':')).encode()
    generator = random.Random(int.from_bytes(hashlib.sha256(raw).digest(), 'big'))
    if distribution['type'] == 'constant':
        return distribution['c']
    if distribution['type'] == 'uniform':
        offset = distribution['offset'] if 'offset' in distribution else distribution['width'] / 2
        return generator.uniform(distribution['m'] - offset, distribution['m'] + offset)
    if distribution['type'] == 'exponential':
        return generator.expovariate(1 / distribution['mean'])
    raise ValueError('unknown distribution')


def key_token(value):
    """Python-equal finite JSON scalar keys alias; string '1' never aliases 1.

    JSON container keys retain Python's exact unhashable error. Non-finite scalar
    identities are outside this prototype's explicit domain and fail closed.
    """
    hash(value)  # preserve TypeError for list/dict identities
    if value is None:
        return 'null'
    if type(value) is str:
        return 'str:' + json.dumps(value, ensure_ascii=True)
    if type(value) in (bool, int):
        return 'number:' + str(int(value)) + '/1'
    if type(value) is float:
        if not math.isfinite(value):
            raise UnsupportedIdentity('non-finite identities require a separate compatibility implementation')
        numerator, denominator = value.as_integer_ratio()
        return f'number:{numerator}/{denominator}'
    raise UnsupportedIdentity('only finite JSON scalar identities are supported by this draft')


class UnsupportedIdentity(RuntimeError):
    """No candidate report may certify an identity outside the stated domain."""


class History:
    """All growing job/dispatch/completion/machine-reference histories on disk."""
    def __init__(self, db):
        self.db = db
        db.executescript('''
            CREATE TABLE jobs(key TEXT PRIMARY KEY, ordinal INTEGER UNIQUE, original_key TEXT, value TEXT);
            CREATE TABLE records(stream TEXT, ordinal INTEGER, value TEXT, PRIMARY KEY(stream, ordinal));
        ''')
        self.job_count = 0
        self.stream_counts = Counter()
        self._active_cursors = set()
        self._closed = False

    @contextmanager
    def cursor(self, sql, parameters=()):
        if self._closed:
            raise RuntimeError('history is closed')
        cursor = self.db.execute(sql, parameters)
        self._active_cursors.add(cursor)
        try:
            yield cursor
        finally:
            # close() can already have released this suspended generator's
            # cursor while the connection was still open. Never touch it twice.
            if cursor in self._active_cursors:
                self._active_cursors.remove(cursor)
                cursor.close()

    def close(self):
        """Release suspended iterator cursors BEFORE the owner closes SQLite.

        Clear ownership first so delayed generator finalization is a no-op even
        if a real cursor.close failure occurs. Such SQL errors still propagate.
        """
        self._closed = True
        cursors = tuple(self._active_cursors)
        self._active_cursors.clear()
        failures = []
        for cursor in cursors:
            try:
                cursor.close()
            except Exception as exc:
                failures.append(exc)
        if len(failures) == 1:
            raise failures[0]
        if failures:
            raise ExceptionGroup('history cursor cleanup failures', failures)

    def __contains__(self, key):
        return self.db.execute('SELECT 1 FROM jobs WHERE key=?', (key_token(key),)).fetchone() is not None

    @staticmethod
    def encode_job(value):
        return json.dumps({**value, 'pending': list(value['pending'])}, separators=(',', ':'))

    @staticmethod
    def decode_job(raw):
        value = json.loads(raw)
        value['pending'] = set(value['pending'])
        return value

    def job(self, key):
        row = self.db.execute('SELECT value FROM jobs WHERE key=?', (key_token(key),)).fetchone()
        if row is None:
            raise KeyError(key)
        return self.decode_job(row[0])

    def put_job(self, key, value):
        token = key_token(key)
        raw = self.encode_job(value)
        if self.db.execute('SELECT 1 FROM jobs WHERE key=?', (token,)).fetchone() is None:
            self.db.execute('INSERT INTO jobs VALUES(?,?,?,?)',
                            (token, self.job_count, json.dumps(key), raw))
            self.job_count += 1
        else:
            # UPDATE preserves the first key object and insertion ordinal.
            self.db.execute('UPDATE jobs SET value=? WHERE key=?', (raw, token))

    def jobs(self):
        with self.cursor('SELECT original_key,value FROM jobs ORDER BY ordinal') as cursor:
            for key, raw in cursor:
                yield json.loads(key), self.decode_job(raw)

    def append(self, stream, value):
        index = self.stream_counts[stream]
        self.db.execute('INSERT INTO records VALUES(?,?,?)',
                        (stream, index, json.dumps(value, separators=(',', ':'))))
        self.stream_counts[stream] += 1

    def records(self, stream):
        with self.cursor('SELECT value FROM records WHERE stream=? ORDER BY ordinal', (stream,)) as cursor:
            for (raw,) in cursor:
                yield json.loads(raw)

    def machine_stream(self, machine):
        return 'machine:' + key_token(machine)


class Fold:
    def __init__(self, manifest, history):
        self.manifest, self.history = manifest, history
        self.seed, self.horizon = manifest['seed'], manifest['horizon']
        self.controls = set(manifest['controlled_machine_ids'])
        self.routes = manifest['routes']
        self.machines = {m['id']: m for m in manifest['machines']}
        self.lots = {lot['id']: dict(lot, status='unreleased', next_step=lot['step'] + 1,
                                   visits={}, dedications={}, ready=None, done=None) for lot in manifest['lots']}
        self.ms = {mid: dict(ready=0., down=0., setup='', min_left=0, min_setup='') for mid in self.machines}
        self.released = set()
        self.queue_area, self.waiting_control, self.previous = 0., 0, 0.
        self.counts = Counter()
        self.action_count, self.last_action, self.pending, self.wait_until = 0, None, [], 0.
        self.setups = {(x['old'], x['new']): x['seconds'] for x in manifest['setups']}
        self.calendars = manifest['calendars']
        self.nextcal = {key: (cal['first_time'], 0) for key, cal in self.calendars.items()}
        self.piece = {int(mid): [dict(counter) for counter in counters] for mid, counters in manifest['piece_pm'].items()}
        self.control_families = {self.machines[mid]['family'] for mid in self.controls}
        self.errors = []

    def check(self, okay, message):
        if not okay and len(self.errors) < 200:
            self.errors.append(message)

    def near(self, a, b, message):
        self.check(math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-6), f'{message}: {a} != {b}')

    def event(self, index, event, is_last):
        i, e = index, event
        t, kind = e['time'], e['kind']
        self.check(e['seq'] == i, f'{i}: sequence gap')
        self.check(t >= self.previous, f'{i}: time reversed')
        self.check(0 <= t <= self.horizon, f'{i}: time outside window')
        self.queue_area += (t - self.previous) * self.waiting_control
        self.previous = t
        # The reference group statistic reads ALL raw downtime events, even if
        # the corresponding physics branch fails partway through.
        if kind == 'downtime':
            self.history.append('downtime', e)
        try:
            if kind == 'initial':
                self.check(i == 0, 'duplicate initial')
            elif kind == 'release':
                lid = e['lot'];lot = self.lots[lid]
                self.check(lid not in self.released, f'{i}: duplicate release')
                self.check(lot['status'] == 'unreleased', f'{i}: invalid release state')
                self.near(t, max(0, lot['release']) if lot['initial'] else lot['release'], f'{i}: release time')
                self.released.add(lid);lot['status'] = 'released'
            elif kind in ('ready', 'skip'):
                lot = self.lots[e['lot']]
                self.check(lot['status'] in ('released', 'transition') and not lot.get('required_rework'), f'{i}: ready/skip while not transitioning or missing rework')
                self.check(e['step'] == lot['next_step'], f'{i}: illegal route transition')
                step = self.routes[lot['route']][lot['next_step'] - 1]
                visit = lot['visits'].get(str(step['step']), 0) + 1
                self.check(e['visit'] == visit, f'{i}: visit count');lot['visits'][str(step['step'])] = visit
                draw = sampled(self.seed, ['sample', lot['id'], step['step'], visit], {'type': 'uniform', 'm': 50, 'offset': 50})
                if kind == 'skip':
                    self.check(draw > step['sampling_percent'], f'{i}: illegal sampling skip')
                    self.near(draw, e['draw'], f'{i}: sample draw');lot['next_step'] += 1;lot['status'] = 'transition'
                else:
                    self.check(draw <= step['sampling_percent'], f'{i}: missed sampling skip')
                    lot['status'] = 'waiting';lot['ready'] = t;self.waiting_control += step['family'] in self.control_families
            elif kind == 'action':
                self.check(not self.pending, f'{i}: previous action has unexecuted dispatch')
                self.check(t >= self.wait_until, f'{i}: controlled action during explicit wait')
                self.check(e['decision'] == self.action_count, f'{i}: action index')
                action = e['action'];self.check(0 <= action['wait_seconds'] <= 1800, f'{i}: wait bound')
                self.action_count += 1;self.last_action = e;self.pending = list(action['dispatches']);self.wait_until = t + action['wait_seconds']
                self.check(bool(action['dispatches']) or action['wait_seconds'] > 0, f'{i}: empty action without wait')
                declared = []
                for dispatch in action['dispatches']:
                    self.check(dispatch['machine'] in self.controls, f'{i}: action uncontrolled machine')
                    self.check(bool(dispatch['lot_ids']), f'{i}: action empty lot batch');declared += dispatch['lot_ids']
                    for lid in dispatch['lot_ids']:
                        self.check(lid in self.lots and self.lots[lid]['status'] == 'waiting', f'{i}: action lot not currently waiting')
                self.check(len(declared) == len(set(declared)), f'{i}: duplicate lot in action')
                self.check(len({d['machine'] for d in action['dispatches']}) == len(action['dispatches']), f'{i}: duplicate machine in action')
            elif kind == 'dispatch':
                self.dispatch(i, e)
            elif kind == 'downtime':
                self.downtime(i, e)
            elif kind == 'operation_complete':
                jid = e['job'];job = self.history.job(jid);lid = e['lot'];lot = self.lots[lid]
                self.check(lid in job['pending'], f'{i}: duplicated/unassigned operation completion')
                self.near(t, job['lot_end'], f'{i}: wrong operation completion time')
                self.check(lot['status'] == 'processing' and lot['job'] == jid, f'{i}: wrong lot processing state')
                self.check(lot['next_step'] == e['step'], f'{i}: completion wrong step')
                job['pending'].discard(lid);job['done'] = not job['pending'];self.history.put_job(jid, job)
                lot['next_step'] += 1;lot['status'] = 'transition';self.counts['controlled_completed_operation_lots'] += job['controlled']
                step = self.routes[lot['route']][e['step'] - 1]
                draw = sampled(self.seed, ['rework', lot['id'], step['step'], lot['visits'][str(step['step'])]], {'type': 'uniform', 'm': 50, 'offset': 50})
                lot['required_rework'] = draw <= step['rework_percent']
            elif kind == 'rework':
                lot = self.lots[e['lot']];step = self.routes[lot['route']][e['step'] - 1]
                self.check(lot['status'] == 'transition' and lot['next_step'] == e['step'] + 1, f'{i}: rework ordering')
                draw = sampled(self.seed, ['rework', lot['id'], step['step'], e['visit']], {'type': 'uniform', 'm': 50, 'offset': 50})
                self.check(draw <= step['rework_percent'], f'{i}: unsupported rework');self.near(draw, e['draw'], f'{i}: rework draw')
                self.check(e['target'] == step['rework_step'], f'{i}: wrong rework target');lot['next_step'] = e['target'];lot['required_rework'] = False
            elif kind == 'lot_complete':
                lot = self.lots[e['lot']]
                self.check(lot['status'] == 'transition' and not lot.get('required_rework') and lot['next_step'] == len(self.routes[lot['route']]) + 1, f'{i}: incomplete route marked done')
                lot['status'] = 'done';lot['done'] = t;self.history.append('completed', lot['id'])
            elif kind == 'terminal':
                self.check(not self.pending, 'terminal contains unexecuted declared dispatch')
                self.check(is_last, 'terminal must be last');self.near(t, self.horizon, 'unfinished window')
                self.check(e['lot_statuses'] == {lid: lot['status'] for lid, lot in self.lots.items()}, 'terminal inventory mismatch')
                self.check(all(lot['status'] in ('waiting', 'processing', 'done', 'unreleased') for lot in self.lots.values()), 'terminal unresolved transition')
            else:
                self.check(False, f'{i}: unknown event {kind}')
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            self.check(False, f'{i}: malformed trace {exc}')

    def dispatch(self, i, e):
        t, jid, mid = e['time'], e['job'], e['machine']
        machine, state = self.machines[mid], self.ms[mid]
        ids = e['lots']
        self.check(jid not in self.history, f'{i}: duplicate job')
        self.check(bool(ids) and len(ids) == len(set(ids)), f'{i}: duplicate/empty lot batch')
        self.check(state['ready'] <= t + 1e-6 and state['down'] <= t + 1e-6, f'{i}: machine overlap/downtime')
        stream = self.history.machine_stream(mid)
        self.check(sum(self.history.job(key)['process_end'] > t for key in self.history.records(stream)) < (2 if machine['cascading'] else 1), f'{i}: physical processing-slot capacity')
        lots = [self.lots[lid] for lid in ids];step = self.routes[lots[0]['route']][lots[0]['next_step'] - 1]
        self.check(step['batch_min'] <= len(lots) <= step['batch_max'], f'{i}: batch min/max')
        for n, lot in enumerate(lots):
            self.check(lot['status'] == 'waiting', f'{i}: lot not waiting')
            self.check(lot['next_step'] == e['steps'][n], f'{i}: dispatched wrong step')
            actual = self.routes[lot['route']][lot['next_step'] - 1]
            self.check(actual['family'] == machine['family'], f'{i}: machine qualification')
            self.check((lot['part'], actual['step'], actual['name']) == (lots[0]['part'], step['step'], step['name']), f'{i}: batch incompatible')
            self.check(lot['dedications'].get(str(actual['step']), mid) == mid, f'{i}: dedication violation')
            self.check(e['visits'][n] == lot['visits'][str(actual['step'])], f'{i}: dispatch visit mismatch')
            if actual['dedicate_for'] is not None:lot['dedications'][str(actual['dedicate_for'])] = mid
            self.waiting_control -= int(lot['status'] == 'waiting' and actual['family'] in self.control_families)
            lot['status'] = 'processing';lot['job'] = jid
        self.check(e['owner'] == ('controller' if mid in self.controls else 'environment'), f'{i}: unlabelled controller takeover')
        if mid in self.controls:
            declared = {'machine': mid, 'lot_ids': ids}
            self.check(self.last_action is not None and self.last_action['time'] == t and declared in self.last_action['action']['dispatches'], f'{i}: controlled dispatch missing exact explicit action')
            self.check(declared in self.pending, f'{i}: repeated or unclaimed controlled dispatch')
            if declared in self.pending:self.pending.remove(declared)
        self.check(state['min_left'] == 0 or state['min_setup'] == step['setup'], f'{i}: minimum setup runs')
        setup = 0
        if step['setup'] and state['setup'] != step['setup']:
            setup = step['setup_time'] if step['setup_time'] is not None else self.setups.get((state['setup'], step['setup']), self.setups.get(('', step['setup']), 0))
        self.check(state['setup'] == e['setup_before'], f'{i}: setup state');self.near(e['setup_seconds'], setup, f'{i}: setup duration')
        keys = sorted([[lot['id'], step['step'], lot['visits'][str(step['step'])]] for lot in lots])
        process = sampled(self.seed, ['processing', keys], step['processing'])
        cadence = process if step['cadence'] == step['processing'] else sampled(self.seed, ['cadence', keys], step['cadence'])
        nextstep = self.routes[lots[0]['route']][step['step']] if step['step'] < len(self.routes[lots[0]['route']]) else None
        transport = sampled(self.seed, ['transport', keys], nextstep['transport']) if nextstep else 0
        self.near(e['processing_seconds'], process, f'{i}: processing sample');self.near(e['cadence_seconds'], cadence, f'{i}: cadence sample');self.near(e['transport_seconds'], transport, f'{i}: transport sample')
        process_time = process + machine['load'] + machine['unload']
        occupation = cadence + (0 if machine['cascading'] else machine['load'] + machine['unload'])
        pm_total, pm_events = 0, []
        for counter in self.piece.get(mid, []):
            counter['remaining'] -= sum(lot['pieces'] for lot in lots)
            if counter['remaining'] <= 0:
                duration = sampled(self.seed, ['piece_pm', counter['key'], counter['occurrence']], counter['length'])
                pm_events.append({'key': counter['key'], 'duration': duration, 'occurrence': counter['occurrence']})
                counter['occurrence'] += 1;counter['remaining'] = counter['repeat'];pm_total += duration
        self.check(pm_events == e['piece_pm'], f'{i}: piece maintenance obligation')
        ready = t + setup + (max(process_time, occupation) if pm_events else occupation) + pm_total
        self.near(e['machine_ready'], ready, f'{i}: machine completion');self.near(e['process_end'], t + setup + process_time, f'{i}: process end');self.near(e['lot_end'], t + setup + process_time + transport, f'{i}: lot completion')
        state['ready'] = ready;state['setup'] = '' if pm_events else step['setup'];self.check(state['setup'] == e['setup_after'], f'{i}: setup after dispatch')
        if setup > 0 and step['setup'] in self.manifest['min_runs'] and state['min_left'] == 0:
            state['min_left'] = self.manifest['min_runs'][step['setup']];state['min_setup'] = step['setup']
        state['min_left'] = max(0, state['min_left'] - len(lots));self.check(state['min_left'] == e['min_runs_left'], f'{i}: min runs counter')
        self.history.put_job(jid, {'machine': mid, 'lots': ids, 'pending': set(ids), 'process_end': e['process_end'], 'lot_end': e['lot_end'], 'controlled': mid in self.controls, 'done': False})
        self.history.append('dispatch', e);self.history.append(stream, jid)

    def downtime(self, i, e):
        t, key = e['time'], e['calendar'];calendar = self.calendars[key]
        mid = calendar['machine'];state = self.ms[mid];expected_t, occurrence = self.nextcal[key]
        self.near(t, expected_t, f'{i}: calendar occurrence time');self.check(e['occurrence'] == occurrence, f'{i}: calendar occurrence index')
        self.check(e['machine'] == mid and e['breakdown'] == calendar['breakdown'], f'{i}: calendar identity')
        duration = sampled(self.seed, ['calendar', key, 'length', occurrence], calendar['length']);self.near(duration, e['duration'], f'{i}: downtime draw')
        end = max(t, state['down']) + duration
        affected = []
        for jid, job in self.history.jobs():
            if job['machine'] == mid and not job['done'] and job['process_end'] > t:
                affected.append(jid);job['process_end'] += duration;self.history.put_job(jid, job)
                job['lot_end'] += duration;self.history.put_job(jid, job)
        self.check(affected == e['affected_jobs'], f'{i}: downtime affected jobs')
        state['ready'] = max(t, state['ready'], state['down']) + duration;state['down'] = end;state['setup'] = ''
        self.near(state['ready'], e['machine_ready'], f'{i}: downtime ready');self.near(end, e['blocked_until'], f'{i}: downtime block')
        repeat = sampled(self.seed, ['calendar', key, 'repeat', occurrence], calendar['repeat'])
        self.nextcal[key] = (t + duration + repeat if calendar['breakdown'] else t + repeat, occurrence + 1)

    def dispatches(self, predicate=lambda event: True):
        return (event for event in self.history.records('dispatch') if predicate(event))

    def completed_lots(self):
        return (self.lots[lid] for lid in self.history.records('completed'))

    def finish(self, last, event_count, verify_data_dir):
        self.check(last['kind'] == 'terminal', 'missing terminal event')
        for key, (time, _) in self.nextcal.items():self.check(time > self.horizon, f'missing due calendar event: {key}')
        for jid, job in self.history.jobs():self.check(job['done'] or job['lot_end'] > self.horizon, f'unfinished due operation {jid}')
        for lid, lot in self.lots.items():self.check(lot['status'] != 'unreleased' or (not lot['initial'] and lot['release'] >= self.horizon), f'missing lot release {lid}')
        initial = sum(lot['initial'] for lot in self.lots.values())
        new = sum(not self.lots[lid]['initial'] for lid in self.released)
        terminal = sum(lot['status'] not in ('done', 'unreleased') for lot in self.lots.values())
        completed_count = self.history.stream_counts['completed'];dispatch_count = self.history.stream_counts['dispatch']
        controlled_count = sum(1 for _ in self.dispatches(lambda e: e['machine'] in self.controls))
        self.check(initial == self.manifest['initial_wip'], 'initial WIP count')
        self.check(initial + new == completed_count + terminal, 'lot conservation')
        metrics = {
            'throughput_lots': completed_count,
            'throughput_wafers': sum(lot['pieces'] for lot in self.completed_lots()),
            'mean_cycle_seconds_completed': sum(lot['done'] - lot['release'] for lot in self.completed_lots()) / completed_count if completed_count else None,
            'tardy_completed_lots': sum(lot['done'] > lot['due'] for lot in self.completed_lots()),
            'total_tardiness_completed_seconds': sum(max(0, lot['done'] - lot['due']) for lot in self.completed_lots()),
            'initial_wip_lots': initial, 'released_new_lots': new, 'terminal_wip_lots': terminal, 'wip_change': terminal - initial,
            'terminal_tardy_wip_lots': sum(lot['status'] not in ('done', 'unreleased') and lot['due'] < self.horizon for lot in self.lots.values()),
            'controlled_completed_operation_lots': self.counts['controlled_completed_operation_lots'],
            'controlled_family_queue_area_lot_seconds': self.queue_area, 'controlled_decisions': self.action_count,
            'controlled_dispatches': controlled_count, 'dispatches': dispatch_count,
            'unfinished_controlled_batches': sum(job['controlled'] and len(job['lots']) > 1 and job['lot_end'] > self.horizon for _, job in self.history.jobs()),
            'controlled_batch_fill_ratios': [len(e['lots']) / self.routes[self.lots[e['lots'][0]]['route']][e['steps'][0] - 1]['batch_max'] for e in self.dispatches(lambda e: e['machine'] in self.controls and len(e['lots']) > 1)],
        }
        utilization = {}
        for mid in self.controls:
            predicate = lambda e: e['machine'] in self.controls and e['machine'] == mid
            busy = sum(max(0, min(self.horizon, e['machine_ready']) - e['time']) for e in self.dispatches(predicate))
            utilization[str(mid)] = {'scheduled_occupation_fraction': busy / self.horizon,
                'dispatches': sum(1 for _ in self.dispatches(predicate)),
                'completed_operation_lots': sum(len(job['lots']) for _, job in self.history.jobs() if job['machine'] == mid and job['done'])}
        metrics['controlled_machine_utilization'] = utilization
        groups = {}
        for group in sorted({m['group'] for m in self.machines.values() if m['group'] != 'Delay_32'}):
            members = {mid for mid, machine in self.machines.items() if machine['group'] == group}
            predicate = lambda e: e['machine'] in members
            scheduled = sum(max(0, min(self.horizon, e['machine_ready']) - e['time']) for e in self.dispatches(predicate))
            downtime = sum(max(0, min(self.horizon, e['blocked_until']) - e['time']) for e in self.history.records('downtime') if e['machine'] in members)
            groups[group] = {'physical_machine_count': len(members), 'dispatches': sum(1 for _ in self.dispatches(predicate)),
                'operation_lots_dispatched': sum(len(e['lots']) for e in self.dispatches(predicate)),
                'scheduled_occupation_fraction': scheduled / (len(members) * self.horizon),
                'calendar_downtime_exposure_fraction': downtime / (len(members) * self.horizon)}
        metrics['production_group_statistics'] = groups
        metrics['controlled_dispatch_share'] = controlled_count / dispatch_count if dispatch_count else 0
        metrics['controlled_machine_fraction'] = len(self.controls) / sum(m['group'] != 'Delay_32' for m in self.machines.values())
        if last['kind'] == 'terminal':
            original = last['metrics']
            for key, value in metrics.items():
                if key in original:
                    if isinstance(value, (float, int)) and value is not None:self.near(value, original[key], 'metric ' + key)
                    else:self.check(value == original[key], 'metric ' + key)
        if verify_data_dir:
            from src.smt.source_check import verify_source  # pure independent CSV verifier
            for error in verify_source(self.manifest, verify_data_dir):self.check(False, error)
        return {'valid': not self.errors, 'errors': self.errors, 'event_count': event_count, 'metrics': metrics,
                'audit_version': VERSION, 'verified_input_hashes': bool(verify_data_dir), 'verified_source_semantics': bool(verify_data_dir)}


def audit_events(events, verify_data_dir=None, *, work_dir=None):
    """Consume one iterable fully; no file/EOF/projection authenticity certificate.

    Input domain: JSON-like events with finite JSON scalar historical identities.
    No retained full event array; final metric array and manifest/current lot
    state still scale. Unexpected exceptions produce no successful result.
    """
    if isinstance(events, (str, bytes, Path)):
        raise TypeError('draft core requires an event iterable, not a path')
    iterator = iter(events);sentinel = object();event = next(iterator, sentinel)
    if event is sentinel or event.get('kind') != 'initial':
        return {'valid': False, 'errors': ['missing initial manifest']}
    with TemporaryDirectory(prefix='smt_physical_core_', dir=work_dir) as temporary:
        with closing(sqlite3.connect(Path(temporary) / 'history.sqlite3')) as db:
            db.execute('PRAGMA temp_store=FILE');db.execute('PRAGMA cache_size=-2048')
            with closing(History(db)) as history:
                fold = Fold(event['manifest'], history);count = 0
                while event is not sentinel:
                    following = next(iterator, sentinel)
                    fold.event(count, event, following is sentinel);count += 1
                    last = event;event = following
                report = fold.finish(last, count, verify_data_dir)
    report['_core_scope'] = {'reference_audit_version': REFERENCE_VERSION,
        'input_contract': 'caller-supplied iterable; not authenticated storage',
        'historical_state': 'SQLite jobs/dispatch/completed/machine_refs/downtime',
        'projection_binding_verified': False, 'source_receipt_verified': False,
        'atomic_report_published': False, 'large_report_streamed': False,
        'fullfab_source_opportunity_or_model_attribution_verified': False,
        'long_window_readiness_certified': False}
    return report
