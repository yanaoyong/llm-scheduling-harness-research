"""Private simulation adapter; only problem() is model-visible."""
from collections import Counter, defaultdict
from copy import deepcopy
import heapq
import time

from .env_adapter import FullFabEnvironment

from .contracts import digest, require, encode, strict_json


def capture(env):
    state = _state_view(env)
    state.pop("trace")
    state["last_stop"] = deepcopy(env.last_stop)
    state['invalidated_task_ids'] = sorted(env.invalidated_task_ids)
    state['breakdowns'] = env.breakdowns
    # JSON normalization preserves the legacy snapshot number and key spelling.
    return strict_json(encode(state))


def restore(state, trace, *, data_dir=None):
    state = deepcopy(state)
    state.pop('batch_state', None)
    state.setdefault('invalidated_task_ids', [])
    state.setdefault('breakdowns', False)
    env = FullFabEnvironment(seed=state["seed"], window_seconds=state["horizon"], data_dir=data_dir)
    require(env.manifest["data_hashes"] == state["manifest"]["data_hashes"], "data_changed", "Data differs from snapshot")
    for key, value in deepcopy(state).items():
        setattr(env, key, value)
    env.invalidated_task_ids = set(env.invalidated_task_ids)
    env.machine_state = {int(k): v for k, v in env.machine_state.items()}
    env.jobs = {int(k): v for k, v in env.jobs.items()}
    env.waiting = defaultdict(set, {k: set(v) for k, v in env.waiting.items()})
    env.processing_by_machine = defaultdict(set, {int(k): set(v) for k, v in env.processing_by_machine.items()})
    env.pm_counters = defaultdict(list, {int(k): v for k, v in env.pm_counters.items()})
    env.q = [tuple(x) for x in env.q]
    heapq.heapify(env.q)
    env.stats = Counter(env.stats)
    env.executed_tasks = {tuple(x) for x in env.executed_tasks}
    env.plan_versions = set(env.plan_versions)
    env.trace = deepcopy(trace)
    env.trace_path = None
    env.active_task = None
    env.started_wall = time.perf_counter()
    require(digest(capture(env)) == digest(state), "restore_mismatch", "Private state failed exact round trip")
    return env


def prepare(env, plan):
    # Preparation can emit only into this detached clone. Formal acceptance is
    # the later SQLite CAS that binds its state, commit receipt and events.
    prepared = deepcopy(env)
    prepared.trace_path = None
    if plan != prepared.plan:
        prepared.commit_plan(plan)
    return prepared

STATE_FIELDS = ('seed', 'horizon', 't', 'seq', 'dispatch_id', 'decisions', 'releases',
                'completed', 'finished', 'wait_until', 'lots', 'machine_state',
                'jobs', 'calendars', 'pm_counters', 'queue_area', 'last_area_t',
                'manifest', 'plan', 'observation_start')

def _state_view(env):
    state = {key: getattr(env, key) for key in STATE_FIELDS}
    state.update(q=env.q, waiting={key: sorted(value) for key, value in env.waiting.items()},
                 processing_by_machine={str(key): sorted(value) for key, value in env.processing_by_machine.items()},
                 stats=dict(env.stats), executed_tasks=sorted(env.executed_tasks),
                 plan_versions=sorted(env.plan_versions), trace=env.trace)
    return state




def commit_physical(store, expected_state_version, env, plan):
    """Prepare privately, then atomically persist physical state, plan and events.

    Returns the adopted clone or None on a stale version. The caller replaces
    its in-memory env only after this transaction returns successfully.
    """
    prepared=prepare(env,plan)
    with store.transaction():
        if store.meta('state_version',0)!=expected_state_version:
            return None
        version=expected_state_version+1
        store.record('plans',str(version),plan)
        store.record('physical_states',str(version),capture(prepared))
        store.set_meta('state_version',version)
        store.event('cycle_commit',{'expected_state_version':expected_state_version,'plan':plan,
                                   'physical_state':capture(prepared),
                                   'new_events':prepared.trace[len(env.trace):]})
    return prepared

class LiveFactory:
    """Thin physical binding for live.LiveRun; private state never enters prompt."""
    def __init__(self, env):
        self.env = env

    @property
    def now(self):
        return self.env.t

    @property
    def plan(self):
        return self.env.plan

    def problem(self):
        return self.env.problem()

    def execution_state(self):
        from .plan_delta import STATE_SCHEMA
        env = self.env
        return dict(schema=STATE_SCHEMA, time=env.t, observation_end=env.horizon,
                    base_plan_version=env.plan['version'],
                    dispatched_task_ids=sorted(t for v,t in env.executed_tasks if v==env.plan['version']),
                    invalidated_task_ids=sorted(env.invalidated_task_ids))

    def ledger(self):
        from .ledger import ledger_read_view
        snap = self.env.ledger_snapshot()
        return ledger_read_view(snap['problem'], snap['plan'], snap['receipts'])

    def running_jobs(self):
        env = self.env
        return [dict(job=jid, machine=j['machine'], lot_ids=j['lots'], started_at=j['start'],
                     phase='processing' if jid in env.processing_by_machine[j['machine']] else 'transport')
                for jid,j in sorted(env.jobs.items()) if not j['done']]

    def advance_to(self, target, stop_on_event):
        env = self.env
        previous = None
        def observe(current):
            nonlocal previous
            if previous is not None:
                start, values = previous
                self.metrics.integrate(start, current.t, **values)
            snap = current.ledger_snapshot()
            from .ledger import ledger_read_view
            ledger = ledger_read_view(snap['problem'], snap['plan'], snap['receipts'])
            values = snap['metrics']
            previous = (current.t, dict(avoidable_idle=values['avoidable_idle'],
                explicit_wait_idle=values['explicit_wait_idle'],
                reserved_but_earlier_startable=len(values['reserved_but_earlier_startable']),
                unreserved_ready_ops=sum(r['ready'] and r['state']=='ready_unreserved' for r in ledger.rows().values())))
            # Full public inputs are frozen once per decision by LiveRun.
            # Keep inter-event trace observations compact instead of retaining
            # a full WIP copy at every physical event.
            return {'metrics': snap['metrics']}
        result = env.advance_cycle(target, ledger_snapshot=observe,
            trigger='event' if stop_on_event else 'periodic', decision_after=env.t)
        if previous is not None:
            self.metrics.integrate(previous[0], env.t, **previous[1])
        reason = result['reason']
        return None if reason in ('avoidable_idle','periodic_replan') else reason

    def adopt(self, plan):
        self.env = prepare(self.env, plan)

    def private_state(self):
        return capture(self.env)

    def capture(self):
        return dict(physical=capture(self.env), trace=deepcopy(self.env.trace), plan=deepcopy(self.env.plan))

    @classmethod
    def restore(cls, state):
        return cls(restore(state['physical'], state['trace']))
