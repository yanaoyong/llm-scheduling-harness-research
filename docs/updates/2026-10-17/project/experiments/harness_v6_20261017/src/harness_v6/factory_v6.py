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
