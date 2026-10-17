"""非模型、仅机制测试: bounded closed-network factory and scripted planner.

Four circulating lots, two routes/machine groups, batches of two. Random
processing durations are keyed by seed, operation identities and machine, not
by event consumption order. This is not SMT2020 or production-quality evidence.
"""
from copy import deepcopy
import hashlib
from .snapshot import canonical, HistorySummary, stable_prefix, build_snapshot
from .plan_delta import SCHEMA, STATE_SCHEMA, ORDER_POLICY, anchor_hashes, json_sha256
from .executor import decide_start
from .ledger import Ledger, ledger_apply
from .cycle import CycleMachine, CycleConfig, DriftMonitor, DriftRule
from .submit import Submitter
from .metrics import Metrics

SOURCE = hashlib.sha256(b'harness-v6-synthetic-v1').hexdigest()
LABEL = '非模型、仅机制测试'


def keyed_uniform(seed, key):
    return int.from_bytes(hashlib.sha256(canonical([seed, key])).digest()[:8], 'big') / 2**64


class SyntheticFactory:
    def __init__(self, seed=1):
        self.seed = seed
        self.now = 0
        self.lots = {str(i): {'step': 1, 'visit': 1, 'ready_at': 0} for i in range(4)}
        self.running = []
        self.down_until = {'1': 0, '2': 0}
        self.plan = {'version': 'initial', 'created_at': 0, 'valid_until': 1, 'freeze_until': 0,
                     'reason': LABEL, 'scope': [1, 2], 'tasks': [], 'holds': []}
        self.dispatched = []
        self.invalid = []
        self.completed = 0

    def operations(self):
        running = {lot for job in self.running for lot in job['task']['lot_ids']}
        rows = []
        for lid, lot in sorted(self.lots.items()):
            step, visit = lot['step'], lot['visit']
            rows.append({'operation_id': f'{lid}:{step}:{visit}', 'lot_id': lid, 'step': step, 'visit': visit,
                         'family': f'F{step}', 'eligible_machines': [step], 'batch_key': ['part', step, 'recipe'],
                         'batch_min': 2, 'batch_max': 2, 'release_time': lot['ready_at'],
                         'ready': lid not in running and lot['ready_at'] <= self.now})
        return rows

    def problem(self):
        return {'time': self.now, 'horizon_end': self.now + 100000, 'scope': [1, 2],
                'machines': [{'machine': m, 'family': f'F{m}'} for m in (1, 2)],
                'operations': self.operations()}

    def execution_state(self):
        return {'schema': STATE_SCHEMA, 'time': self.now, 'observation_end': self.now + 100000,
                'base_plan_version': self.plan['version'], 'dispatched_task_ids': self.dispatched,
                'invalidated_task_ids': self.invalid}

    def ledger(self):
        result = Ledger(self.now)
        running_ops = [oid for j in self.running for oid in j['task']['operation_ids']]
        ledger_apply(result, {'operations': {'upsert': self.operations()},
            'machines': {'upsert': [{'machine': m, 'family': f'F{m}',
                'currently_busy': any(j['task']['machine'] == m for j in self.running),
                'currently_down': self.down_until[str(m)] > self.now} for m in (1, 2)]},
            'tasks': {'upsert': self.plan['tasks']},
            'holds': {'upsert': [dict(h, id=str(i)) for i, h in enumerate(self.plan['holds'])]},
            'receipts': {'upsert': [{'operation_id': o, 'state': 'running'} for o in running_ops]},
            'task_receipts': {'upsert': ([{'task_id': t, 'state': 'done'} for t in self.dispatched] +
                                       [{'task_id': t, 'state': 'invalid'} for t in self.invalid])},
            'plan_created_at': self.plan['created_at']})
        return result

    def adopt(self, plan):
        if plan != self.plan:
            self.plan = deepcopy(plan)
            self.dispatched = []
            self.invalid = []

    def breakdown(self, machine, duration, *, enabled):
        if not enabled:
            return None
        self.down_until[str(machine)] = self.now + duration
        affected = [t['id'] for t in self.plan['tasks'] if t['machine'] == machine and t['id'] not in self.dispatched]
        self.invalid = sorted(set(self.invalid + affected))
        return 'plan_invalidated' if affected else None

    def _dispatch(self, metrics):
        rows = {op['operation_id']: op for op in self.operations()}
        for mid in (1, 2):
            queue = [t for t in self.plan['tasks'] if t['machine'] == mid and t['id'] not in self.dispatched]
            busy = any(j['task']['machine'] == mid for j in self.running)
            decision = decide_start(queue, {'machine': mid, 'ready': self.now, 'available': not busy,
                'down_until': self.down_until[str(mid)], 'invalidated_task_ids': self.invalid}, rows,
                now=self.now, holds=self.plan['holds'], dispatched_task_ids=self.dispatched)
            if decision['reason'] != 'start':
                continue
            task = decision['task']
            duration = 20 + 30 * keyed_uniform(self.seed, [mid, task['operation_ids']])
            self.running.append({'task': task, 'end': self.now + duration})
            self.dispatched.append(task['id'])
            metrics.execution(self.now, starts=1, start_offset=self.now-task.get('not_before', self.now))
            metrics.production(self.now, queue_wait=sum(self.now-self.lots[l]['ready_at'] for l in task['lot_ids']), setups=1)

    def advance(self, target, metrics):
        if target < self.now:
            raise ValueError('backwards simulation')
        while self.now < target:
            self._dispatch(metrics)
            times = [target] + [j['end'] for j in self.running if j['end'] > self.now]
            times += [v for v in self.down_until.values() if v > self.now]
            times += [h['until'] for h in self.plan['holds'] if h['until'] > self.now]
            times += [t['not_before'] for t in self.plan['tasks'] if t.get('not_before', self.now) > self.now]
            stop = min(times)
            ledger = self.ledger(); values = ledger.metrics()
            metrics.integrate(self.now, stop, unreserved_ready_ops=sum(r['ready'] and r['state']=='ready_unreserved' for r in ledger.rows().values()),
                              avoidable_idle=values['avoidable_idle'], explicit_wait_idle=values['explicit_wait_idle'],
                              reserved_but_earlier_startable=len(values['reserved_but_earlier_startable']))
            self.now = stop
            completed = [j for j in self.running if j['end'] <= stop]
            self.running = [j for j in self.running if j['end'] > stop]
            for job in completed:
                for lid in job['task']['lot_ids']:
                    lot = self.lots[lid]
                    if lot['step'] == 2:
                        lot['step'] = 1; lot['visit'] += 1; self.completed += 1
                        metrics.production(self.now, throughput=1)
                    else:
                        lot['step'] = 2
                    lot['ready_at'] = self.now

    def capture(self):
        return deepcopy(vars(self))

    @classmethod
    def restore(cls, state):
        obj = cls(); obj.__dict__.update(deepcopy(state)); return obj


def scripted_delta(factory, cycle):
    """Only this explicitly non-model planner creates production tasks."""
    problem, state, base = factory.problem(), factory.execution_state(), factory.plan
    pending = [t for t in base['tasks'] if t['id'] not in factory.dispatched]
    cancel = [t['id'] for t in pending if t['id'] in factory.invalid]
    retained = [t for t in pending if t['id'] not in cancel]
    used = {o for t in retained for o in t['operation_ids']}
    tasks = []
    for mid in (1, 2):
        rows = [r for r in problem['operations'] if r['ready'] and mid in r['eligible_machines'] and r['operation_id'] not in used]
        for index in range(0, len(rows)-1, 2):
            batch = rows[index:index+2]
            tasks.append({'id': f'c{cycle}-m{mid}-b{index}', 'machine': mid, 'start_mode': 'when_ready',
                          'operation_ids': [r['operation_id'] for r in batch], 'lot_ids': [r['lot_id'] for r in batch],
                          'steps': [r['step'] for r in batch], 'visits': [r['visit'] for r in batch]})
    return {'schema': SCHEMA, 'anchors': anchor_hashes(base, problem, state, source_sha256=SOURCE),
            'order_policy': ORDER_POLICY, 'plan_header': {'version': f'v{cycle}', 'created_at': factory.now,
                'valid_until': factory.now + 100000, 'freeze_until': factory.now, 'reason': LABEL, 'scope': [1, 2]},
            'tasks': {'keep': {'mode': 'all_pending_except', 'ids': cancel}, 'cancel_ids': cancel, 'replace': [], 'add': tasks},
            'holds': {'keep': {'mode': 'all_except', 'ids': []}, 'cancel_ids': [], 'replace': [], 'add': []},
            'machine_orders': [{'machine': m, 'task_ids': [t['id'] for t in retained+tasks if t['machine']==m]}
                               for m in sorted({t['machine'] for t in tasks})]}


from .checkpoint import capture_ledger as ledger_capture


class SyntheticRun:
    def __init__(self, *, seed=1, config=None, drift_rule=None):
        self.factory = SyntheticFactory(seed)
        self.cycle = CycleMachine(config=config or CycleConfig())
        self.metrics = Metrics(exclude_first_hours=1)
        self.history = HistorySummary()
        self.max_snapshot_bytes = 0
        self.min_snapshot_bytes = None
        self.drift = DriftMonitor(drift_rule) if drift_rule else None
        self.last_hour = -1

    def step(self, *, event=None, injected_usage=100):
        c, f = self.cycle, self.factory
        if c.stop_reason:
            return None
        if event is None:
            f.advance(c.anchor, self.metrics)
        ledger = f.ledger()
        record = c.begin(f.now, avoidable_idle=ledger.metrics()['avoidable_idle'], invalid_tasks=f.invalid,
                         valid_until=f.plan['valid_until'], event=event)
        if record['session']:
            payload = build_snapshot(stable_prefix(tool_descriptions=[], routing=[1, 2], machine_groups=[1, 2]),
                ledger, state_version=c.cycles, running_jobs=f.running, last_cycle_receipt=c.last_record,
                model_notes=LABEL, token_budget=100000, history=self.history)
            self.max_snapshot_bytes = max(self.max_snapshot_bytes, len(payload))
            self.min_snapshot_bytes = min(self.min_snapshot_bytes or len(payload), len(payload))
            submit = Submitter(f.plan, f.problem(), f.execution_state(), state_version=c.cycles,
                               next_anchor=c.anchor, delta_seconds=c.config.delta, source_sha256=SOURCE)
            receipt = submit.submit_plan(c.cycles, str(c.cycles), scripted_delta(f, c.cycles))
            f.adopt(submit.finalize(process_ok=True))
            c.finish(submitted=receipt['accepted'], cost=injected_usage, model_note=LABEL)
            self.metrics.session(f.now, tool_calls=1, tool_rounds=1, input_tokens=injected_usage,
                                 submit_attempts=1, submit_rejections=int(not receipt['accepted']), failed=not receipt['accepted'])
            self.history = self.history.append(receipt)
        completed_hour = int((f.now-c.origin)//3600)-1
        while self.last_hour < completed_hour:
            self.last_hour += 1
            if self.drift and self.drift.observe(self.last_hour, self.metrics.derived(self.metrics.buckets.get(self.last_hour, {}))):
                c.stop_reason = c.stop_reason or 'drift'
        return record

    def capture(self):
        return {'factory': self.factory.capture(), 'cycle': self.cycle.capture(), 'metrics': self.metrics.capture(),
                'history': self.history.digest, 'max_snapshot_bytes': self.max_snapshot_bytes,
                'min_snapshot_bytes': self.min_snapshot_bytes, 'last_hour': self.last_hour,
                'drift': None if not self.drift else {'limits': self.drift.rule.limits,
                    'consecutive_hours': self.drift.rule.consecutive_hours, 'streak': self.drift.streak,
                    'last_hour': self.drift.last_hour}}

    def checkpoint(self, store):
        return store.save(self.cycle.segment, state=self.factory.capture(), cycle=self.cycle.capture(),
                          ledger=ledger_capture(self.factory.ledger()), cumulative_costs={'cost': self.cycle.cost,
                          'wall_seconds': self.cycle.wall_seconds}, extra=self.capture())

    @classmethod
    def restore(cls, payload):
        state = payload['extra']; obj = cls()
        obj.factory = SyntheticFactory.restore(payload['state'])
        obj.cycle = CycleMachine.restore(payload['cycle'])
        obj.metrics = Metrics.restore(state['metrics'])
        obj.history = HistorySummary(state['history'])
        for key in ('max_snapshot_bytes', 'min_snapshot_bytes', 'last_hour'):
            setattr(obj, key, state[key])
        if state['drift']:
            d = state['drift']; obj.drift = DriftMonitor(DriftRule(d['limits'], d['consecutive_hours']))
            obj.drift.streak = d['streak']; obj.drift.last_hour = d['last_hour']
        return obj

    def state_hash(self):
        return json_sha256(self.capture())
