"""非模型、仅机制测试: bounded closed-network factory and scripted planner.

Four circulating lots, two routes/machine groups, batches of two. Random
processing durations are keyed by seed, operation identities and machine, not
by event consumption order. This is not SMT2020 or production-quality evidence.
"""
from .delta_schema import model_task
from copy import deepcopy
import hashlib
from .snapshot import canonical, HistorySummary, stable_prefix, estimate_tokens
from .plan_delta import STATE_SCHEMA, json_sha256
from .executor import decide_start
from .ledger import Ledger, ledger_apply
from .cycle import CycleMachine, DriftMonitor, DriftRule
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

    def advance(self, target, metrics, *, stop_on_event=False):
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
            if stop_on_event:
                return

    def advance_to(self, target, stop_on_event):
        if not stop_on_event:
            self.advance(target, self.metrics)
            return None
        horizon = target - self.now
        self.advance(target, self.metrics, stop_on_event=True)
        self._dispatch(self.metrics)
        while self.ledger().metrics()['avoidable_idle'] <= 0 and not self.invalid:
            before = self.now
            self.advance(self.now + horizon, self.metrics, stop_on_event=True)
            self._dispatch(self.metrics)
            if self.now == before:
                raise RuntimeError('synthetic event clock stalled')
        return 'plan_invalidated' if self.invalid else None

    def running_jobs(self):
        return self.running

    def private_state(self):
        return None

    def capture(self):
        return deepcopy({k:v for k,v in vars(self).items() if k != 'metrics'})

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
    return {'plan_header': {
                'valid_until': factory.now + 100000, 'freeze_until': factory.now, 'reason': LABEL},
            'tasks': {'cancel_ids': cancel, 'replace': [], 'add': [model_task(t) for t in tasks]},
            'holds': {'cancel_ids': [], 'replace': [], 'add': []},
            'machine_orders': [{'machine': m, 'task_ids': [t['id'] for t in retained+tasks if t['machine']==m]}
                               for m in sorted({t['machine'] for t in tasks + pending})]}


from .checkpoint import capture_ledger as ledger_capture


class ScriptedRunner:
    """Non-model planner; emits real tool calls and matching wire evidence."""
    def __init__(self, planner):
        self.planner = planner
        self.usage = 100

    def run(self, argv, prompt, *, timeout):
        import json
        from pathlib import Path
        from .session import RunResult
        from .mcp_server import CycleServer
        inputs = Path(argv[argv.index('--cd') + 1])
        frozen = json.loads((inputs / 'cycle.json').read_bytes())
        args = self.planner(frozen)
        events = []
        if '--output-schema' in argv:
            events.append({'type':'item.completed','item':{'type':'agent_message','text':canonical(args).decode()}})
        else:
            outputs = inputs.parent / 'output'
            server = CycleServer(inputs, outputs)
            try:
                for index, (tool, arguments) in enumerate([
                    ('validate_plan', args), ('submit_plan', args)]):
                    item = dict(id=str(index), type='mcp_tool_call', server='harness_v6', tool=tool, arguments=arguments)
                    events.append(dict(type='item.started', item=dict(item)))
                    server.rpc(dict(jsonrpc='2.0', id=index, method='tools/call',
                                    params=dict(name=tool, arguments=arguments)))
                    events.append(dict(type='item.completed', item=dict(item, status='completed')))
            finally:
                server.close()
        events.append(dict(type='turn.completed', usage=dict(input_tokens=self.usage, cached_input_tokens=0, output_tokens=0)))
        return RunResult('\n'.join(canonical(e).decode() for e in events))


from .live import LiveRun


class SyntheticRun(LiveRun):
    def __init__(self, *, seed=1, config=None, drift_rule=None, group=None, directory=None):
        import tempfile
        if group is not None:
            from .groups import config_for
            config = config_for(group, config)
        self._temporary = tempfile.TemporaryDirectory() if directory is None else None
        runner = ScriptedRunner(lambda frozen: dict(expected_state_version=self.cycle.cycles,
            submission_id=str(self.cycle.cycles), delta=scripted_delta(self.factory, self.cycle.cycles)))
        super().__init__(SyntheticFactory(seed), runner, directory=directory or self._temporary.name,
            prefix=stable_prefix(tool_descriptions=[], routing=[1,2], machine_groups=[1,2]),
            source_sha256=SOURCE, request_overhead_tokens=0, output_reserve_tokens=0, context_token_budget=100000, token_counter=estimate_tokens, config=config, drift_rule=drift_rule, model_note=LABEL)

    def step(self, *, event=None, injected_usage=100):
        self.runner.usage = injected_usage
        return super().step(event=event)

    @classmethod
    def restore(cls, payload):
        obj = cls()
        state = payload['extra']
        obj.budget_report = state.get('budget_report')
        obj.factory = SyntheticFactory.restore(payload['state'])
        obj.cycle = CycleMachine.restore(payload['cycle'])
        obj.metrics = Metrics.restore(state['metrics'])
        obj.factory.metrics = obj.metrics
        obj.history = HistorySummary(state['history'])
        for key in ('max_snapshot_bytes', 'min_snapshot_bytes', 'last_hour'):
            setattr(obj, key, state[key])
        if state['drift']:
            d = state['drift']; obj.drift = DriftMonitor(DriftRule(d['limits'], d['consecutive_hours']))
            obj.drift.streak = d['streak']; obj.drift.last_hour = d['last_hour']
        return obj
