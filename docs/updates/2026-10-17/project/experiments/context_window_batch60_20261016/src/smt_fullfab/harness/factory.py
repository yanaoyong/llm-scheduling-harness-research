"""Private simulation adapter; only problem() is model-visible."""
from collections import Counter, defaultdict
from copy import deepcopy
import heapq
import time

from ..environment import FullFabEnvironment
from ..stream_snapshot import _state_view
from .contracts import digest, require, encode, strict_json


def capture(env):
    state = _state_view(env)
    state.pop("trace")
    state["last_stop"] = deepcopy(env.last_stop)
    if hasattr(env, "batch_state"):
        state["batch_state"] = deepcopy(env.batch_state)
    # JSON normalization preserves the legacy snapshot number and key spelling.
    return strict_json(encode(state))


def restore(state, trace, *, data_dir=None):
    env = FullFabEnvironment(seed=state["seed"], window_seconds=state["horizon"], data_dir=data_dir)
    require(env.manifest["data_hashes"] == state["manifest"]["data_hashes"], "data_changed", "Data differs from snapshot")
    for key, value in deepcopy(state).items():
        setattr(env, key, value)
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
    prepared.commit_plan(plan)
    return prepared
