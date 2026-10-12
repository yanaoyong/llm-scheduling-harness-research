"""Full-fab plan executor, explicit virtual processes and recoverable JSON state.

The inherited, pinned adapter-v2 implements physical semantics only. Its old
background production dispatcher and its apply/advance methods are never used.
No production choice is made here, including for a singleton legal candidate.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
import hashlib
import heapq
import json
import math
import time

from src.smt.environment import SmtEnvironment, average, dist_spec, route_key

VERSION = 'smt-fullfab-env-0.3'


def digest(value):
    # JSON round-trip canonicalizes integer dictionary keys (snapshots use JSON).
    value = json.loads(json.dumps(value))
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as f:
        json.dump(value, f, ensure_ascii=False, separators=(',', ':'))
        f.write('\n')


def snapshot_dependencies():
    root=Path(__file__).resolve().parents[2]
    files=[Path(__file__),Path(__file__).with_name('observation.py'),root/'src/smt/environment.py']
    files+=sorted((root/'vendor/PySCFabSim-revised/simulation').rglob('*.py'))
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


class FullFabEnvironment(SmtEnvironment):
    def __init__(self, *, seed=1701, window_seconds=86400, data_dir=None, trace_path=None):
        # All physical IDs are discovered from the pinned source, not a subset.
        self.plan = None
        self.executed_tasks = set()
        self.plan_versions = set()
        self.active_task = None
        self.observation_start = 0.
        self.last_stop = None
        super().__init__(seed=seed, window_seconds=window_seconds,
                         controlled_machine_ids=(), data_dir=data_dir,
                         trace_path=None, max_decisions=10**9)
        self.controlled = set(self.physical)
        self.manifest['controlled_machine_ids'] = sorted(self.physical)
        self.manifest['fullfab_version'] = VERSION
        self.manifest['outside_policy'] = 'virtual-delay-only; no background production'
        # Parent manifest version describes inherited physics, fullfab_version the executor.
        self.trace[0]['manifest'] = deepcopy(self.manifest)
        self.trace_path = Path(trace_path) if trace_path else None
        if self.trace_path:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            with self.trace_path.open('x') as stream:
                for e in self.trace:
                    stream.write(json.dumps(e, separators=(',', ':')) + '\n')
        self.family_machines = defaultdict(list)
        for m in self.machines:
            self.family_machines[m.family].append(m.idx)

    def _outside(self):
        """Virtual delay routing only; no production dispatch may enter this path."""
        changed = False
        for m in self.machines:
            if m.idx in self.physical:
                continue
            groups = self._groups(m.idx)
            if groups:
                g = groups[0]  # Equivalent interchangeable virtual delay slots.
                s = self._step(self.lots[g[0]])
                if len(g) >= s.batch_min:
                    self._dispatch(m.idx, g[:s.batch_max], 'environment')
                    changed = True
        return changed

    def _emit(self, kind, **kw):
        if kind == 'dispatch' and kw['machine'] in self.physical:
            if self.active_task is None:
                raise RuntimeError('production_dispatch_without_explicit_plan')
            kw.update(plan_version=self.plan['version'], plan_task_id=self.active_task['id'])
        super()._emit(kind, **kw)

    def commit_plan(self, plan):
        """Validate a complete plan atomically, preserving frozen commitments."""
        plan = deepcopy(plan)
        if not isinstance(plan.get('version'), str) or plan['version'] in self.plan_versions:
            raise ValueError('plan version must be a new string')
        if plan.get('created_at') != self.t:
            raise ValueError('stale plan observation')
        if sorted(plan.get('scope', [])) != sorted(self.physical):
            raise ValueError('plan scope must explicitly include every physical machine')
        if not self.t <= plan['freeze_until'] <= plan['valid_until'] <= self.horizon:
            raise ValueError('invalid plan/freeze horizon')
        if plan['valid_until'] <= self.t:
            raise ValueError('empty plan horizon')
        if not isinstance(plan.get('reason'), str):
            raise ValueError('missing revision reason')
        ids, ops = set(), set()
        carried_frozen = []
        if self.plan and self.t < self.plan['freeze_until']:
            carried_frozen = [t for t in self.plan['tasks'] if (self.plan['version'],t['id']) not in self.executed_tasks and t['not_before'] < self.plan['freeze_until']]
        if carried_frozen and plan['freeze_until'] < self.plan['freeze_until']:
            raise ValueError('revision would shorten existing frozen commitment')
        for task in plan['tasks']:
            if not isinstance(task['id'], str) or task['id'] in ids:
                raise ValueError('duplicate or invalid plan task id')
            ids.add(task['id'])
            if type(task['machine']) is not int or task['machine'] not in self.physical:
                raise ValueError('not a physical machine')
            lids = task['lot_ids']
            if not lids or len(set(lids)) != len(lids) or len(task['steps']) != len(lids) or len(task['visits']) != len(lids):
                raise ValueError('invalid explicit lot/step/visit tuple')
            if not math.isfinite(task['not_before']) or not task['not_before'] < plan['valid_until'] or (task['not_before'] < self.t and task not in carried_frozen):
                raise ValueError('invalid planned start condition')
            first = None
            for lid, step, visit in zip(lids, task['steps'], task['visits']):
                if lid not in self.lots or type(step) is not int or type(visit) is not int or visit < 1:
                    raise ValueError('unknown lot/step/visit')
                l = self.lots[lid]
                if not 1 <= step <= len(self.routes[l['route']].steps):
                    raise ValueError('step out of route')
                s = self.routes[l['route']].steps[step-1]
                key = route_key(s, l['part'])
                if first is None:
                    first = (key, s)
                if key != first[0] or s.family != self.machines[task['machine']].family:
                    raise ValueError('incompatible planned batch or machine family')
                if str(step) in l['dedications'] and l['dedications'][str(step)] != task['machine']:
                    raise ValueError('known dedication violated')
                op = (lid, step, visit)
                if op in ops:
                    raise ValueError('operation appears twice in plan')
                ops.add(op)
            if not first[1].batch_min <= len(lids) <= first[1].batch_max:
                raise ValueError('planned batch min/max')
        held = set()
        for h in plan.get('holds', []):
            hold_key=(h['machine'],h.get('after_task_id'))
            if h['machine'] not in self.physical or hold_key in held or not self.t < h['until'] <= plan['valid_until'] or not h.get('reason'):
                raise ValueError('invalid explicit wait')
            if h.get('after_task_id') is not None and not any(t['id']==h['after_task_id'] and t['machine']==h['machine'] for t in plan['tasks']):
                raise ValueError('conditional hold must refer to a task on its machine')
            held.add(hold_key)
        # Frozen but unstarted tasks survive revisions identically.
        if self.plan and self.t < self.plan['freeze_until']:
            old = [t for t in self.plan['tasks'] if (self.plan['version'], t['id']) not in self.executed_tasks and t['not_before'] < self.plan['freeze_until']]
            for t in old:
                if t not in plan['tasks']:
                    raise ValueError('revision would change a frozen task')
            for mid in self.physical:
                before = [t['id'] for t in old if t['machine'] == mid]
                after = [t['id'] for t in plan['tasks'] if t['machine'] == mid and t['id'] in before]
                if before != after:
                    raise ValueError('revision would reorder frozen tasks')
        self.plan = plan
        self.plan_versions.add(plan['version'])
        self.decisions += 1
        self._emit('plan_committed', plan=plan)
        return digest(plan)

    def _pending(self):
        result = defaultdict(list)
        if self.plan:
            for task in self.plan['tasks']:
                if (self.plan['version'], task['id']) not in self.executed_tasks:
                    result[task['machine']].append(task)
        return result

    def _run_planned_now(self):
        if not self.plan:
            return False
        changed = False
        pending = self._pending()
        # An observed skip/revisit invalidates the submitted plan immediately,
        # even behind another task or an explicit future start/hold. Otherwise
        # the stale task would hide uncovered demand from _gaps until its start.
        # This only requests replanning; it never cancels or replaces a task.
        for tasks in pending.values():
            for task in tasks:
                for lid, step, visit in zip(task['lot_ids'], task['steps'], task['visits']):
                    lot = self.lots[lid]
                    if lot['status'] == 'done' or lot['step']+1 > step or lot['visits'].get(str(step), 0) > visit:
                        self._emit('plan_invalidated', plan_version=self.plan['version'], task_id=task['id'], reason='observed route/visit changed')
                        self.last_stop = {'reason': 'plan_invalidated', 'task': task['id']}
                        return changed
        holds = self._active_holds()
        # Task list order is the submitted order, never a quality-based sort.
        for mid, tasks in pending.items():
            task = tasks[0]
            if self.t < max(task['not_before'], holds.get(mid, self.t)):
                continue
            if task.get('latest_start') is not None and self.t > task['latest_start']:
                self.last_stop = {'reason': 'expired_task', 'task': task['id']}
                return changed
            ready = True
            for lid, step, visit in zip(task['lot_ids'], task['steps'], task['visits']):
                l = self.lots[lid]
                current_visit = l['visits'].get(str(step), 0)
                if l['status'] != 'waiting' or l['step']+1 != step or current_visit != visit:
                    ready = False
            if not ready or max(self.machine_state[mid]['ready'], self.machine_state[mid]['down_until']) > self.t:
                continue
            try:
                self._validate(mid, task['lot_ids'])
            except ValueError as exc:
                self._emit('plan_invalidated', plan_version=self.plan['version'], task_id=task['id'], reason=str(exc))
                self.last_stop = {'reason': 'plan_invalidated', 'task': task['id']}
                return changed
            self.active_task = task
            try:
                self._dispatch(mid, task['lot_ids'], 'plan')
            finally:
                self.active_task = None
            self.executed_tasks.add((self.plan['version'], task['id']))
            changed = True
        return changed

    def _gaps(self):
        pending = self._pending()
        holds = self._active_holds()
        gaps = []
        for mid in sorted(self.physical):
            if pending.get(mid) or holds.get(mid, -1) > self.t:
                continue
            if self.has_legal(mid):
                gaps.append({'machine': mid, 'family': self.machines[mid].family,
                             'candidate_count': len(self.eligible(mid))})
        return gaps

    def _active_holds(self):
        if not self.plan:return {}
        pending=self._pending()
        result={}
        for h in self.plan.get('holds',[]):
            if h.get('after_task_id') is None or ((self.plan['version'],h['after_task_id']) in self.executed_tasks and not pending.get(h['machine'])):
                result[h['machine']]=max(result.get(h['machine'],self.t),h['until'])
        return result

    def advance_plan(self, until=None):
        """Execute submitted orders until a revision trigger or the requested time."""
        until = min(self.horizon, self.horizon if until is None else float(until))
        self.last_stop = None
        while self.t < until:
            if self.plan and self.t >= self.plan['valid_until']:
                self.last_stop = {'reason': 'plan_horizon', 'time': self.t}
                return self.last_stop
            self._outside()
            self._run_planned_now()
            if self.last_stop:
                return self.last_stop
            gaps = self._gaps()
            if gaps:
                self.last_stop = {'reason': 'uncovered_demand', 'machines': gaps, 'time': self.t}
                self._emit('coverage_gap', plan_version=self.plan['version'] if self.plan else None, machines=gaps)
                return self.last_stop
            times = [until, self.q[0][0] if self.q else until]
            if self.plan:
                times.append(self.plan['valid_until'])
                times.extend(t['not_before'] for ts in self._pending().values() for t in ts[:1] if t['not_before'] > self.t)
                times.extend(h['until'] for h in self.plan.get('holds', []) if h['until'] > self.t)
            nxt = min(x for x in times if x > self.t)
            self._emit('time_advance', to=nxt)
            self._events_to(nxt)
        if self.t == self.horizon and not self.finished:
            self.finished = True
            self._emit('terminal', metrics=self.metrics(), lot_statuses={lid:l['status'] for lid,l in self.lots.items()})
        self.last_stop = {'reason': 'terminal' if self.finished else 'periodic_replan', 'time': self.t}
        return self.last_stop

    def snapshot(self, path):
        """Complete state plus trace prefix; never supplied to runtime models."""
        fields = ('seed', 'horizon', 't', 'seq', 'dispatch_id', 'decisions', 'releases',
                  'completed', 'finished', 'wait_until', 'lots', 'machine_state',
                  'jobs', 'calendars', 'pm_counters', 'queue_area', 'last_area_t',
                  'manifest', 'plan', 'observation_start')
        state = {k:deepcopy(getattr(self,k)) for k in fields}
        state.update(q=deepcopy(self.q), waiting={k:sorted(v) for k,v in self.waiting.items()},
                     processing_by_machine={str(k):sorted(v) for k,v in self.processing_by_machine.items()},
                     stats=dict(self.stats), executed_tasks=sorted(self.executed_tasks),
                     plan_versions=sorted(self.plan_versions), trace=deepcopy(self.trace))
        value = {'schema':'smt-fullfab-snapshot-1', 'version':VERSION,
                 'implementation_sha256':snapshot_dependencies(),
                 'physics_sha256':hashlib.sha256(Path(__file__).parents[1].joinpath('smt/environment.py').read_bytes()).hexdigest(),
                 'data_hashes':self.manifest['data_hashes'], 'state':state,
                 'state_sha256':digest(state), 'random_mechanism':'event-keyed SHA256; no mutable global RNG',
                 'initialization':'official WIP cold start; any prehistory is retained, not asserted steady state'}
        write_new(path, value)
        return value['state_sha256']

    @classmethod
    def from_snapshot(cls, path, *, trace_path=None, data_dir=None):
        value = json.loads(Path(path).read_text())
        if value['schema'] != 'smt-fullfab-snapshot-1' or value['version'] != VERSION or digest(value['state']) != value['state_sha256']:
            raise ValueError('snapshot schema/version/hash mismatch')
        if value.get('implementation_sha256') != snapshot_dependencies():
            raise ValueError('snapshot implementation differs or legacy fingerprint is absent; recover with saved source version, do not silently migrate')
        if hashlib.sha256(Path(__file__).parents[1].joinpath('smt/environment.py').read_bytes()).hexdigest() != value['physics_sha256']:
            raise ValueError('snapshot physics dependency changed')
        s = value['state']
        env = cls(seed=s['seed'], window_seconds=s['horizon'], data_dir=data_dir)
        if env.manifest['data_hashes'] != value['data_hashes']:
            raise ValueError('snapshot data changed')
        for k,v in s.items():
            setattr(env,k,v)
        env.machine_state = {int(k):v for k,v in env.machine_state.items()}
        env.jobs = {int(k):v for k,v in env.jobs.items()}
        env.waiting = defaultdict(set, {k:set(v) for k,v in env.waiting.items()})
        env.processing_by_machine = defaultdict(set, {int(k):set(v) for k,v in env.processing_by_machine.items()})
        env.pm_counters = defaultdict(list, {int(k):v for k,v in env.pm_counters.items()})
        env.q = [tuple(x) for x in env.q]
        heapq.heapify(env.q)
        env.stats = Counter(env.stats)
        env.executed_tasks = {tuple(x) for x in env.executed_tasks}
        env.plan_versions = set(env.plan_versions)
        env.active_task = None
        env.trace_path = Path(trace_path) if trace_path else None
        if env.trace_path:
            env.trace_path.parent.mkdir(parents=True, exist_ok=True)
            with env.trace_path.open('x') as f:
                for e in env.trace:
                    f.write(json.dumps(e,separators=(',',':'))+'\n')
        env.started_wall = time.perf_counter()
        env._emit('snapshot_loaded', snapshot_sha256=value['state_sha256'], prefix_event_count=len(env.trace))
        return env

    def problem(self, *, plan_seconds=14400, lookahead_depth=3):
        """White-listed expectations only; no pending RNG events or future outcomes."""
        from .observation import build_problem
        return build_problem(self, plan_seconds=plan_seconds, lookahead_depth=lookahead_depth)


def plan_from_action(env, action, version, *, valid_seconds=1800, reason='reference-policy decision'):
    """Pure representation conversion; action already contains every choice."""
    tasks = []
    for i,d in enumerate(action['dispatches']):
        ls = [env.lots[lid] for lid in d['lot_ids']]
        tasks.append({'id':str(i),'machine':d['machine'],'lot_ids':list(d['lot_ids']),
                      'steps':[l['step']+1 for l in ls],
                      'visits':[l['visits'][str(l['step']+1)] for l in ls], 'not_before':env.t})
    until = min(env.horizon,env.t+valid_seconds)
    wait = action.get('wait_seconds',0)
    return {'version':str(version),'created_at':env.t,'valid_until':until,'freeze_until':env.t,
            'reason':reason,'scope':sorted(env.physical),'tasks':tasks,
            'holds':[{'machine':mid,'until':min(until,env.t+wait),'reason':'explicit reference wait'} for mid in sorted(env.physical)] if wait>0 else []}
