"""Exact parent state restoration and explicit-commit-only advancement.

Uses the original environment's from_snapshot; never changes H, observation_start,
queues, random mechanism, executed identities, or existing plan. New trace keeps
all original events and the one real snapshot_loaded event emitted by restore.
"""
from copy import deepcopy
import json
from pathlib import Path

from .fork_store import need, read, fence, raw_json, same, write_new

SCHEMA = 'smt-B-v7-physical-resume-v1'


def compare_restored(parent, restored, *, digest):
    need(restored['schema'] == parent['schema'] and restored['version'] == parent['version'], 'snapshot schema/version changed')
    for key in ('implementation_sha256', 'physics_sha256', 'data_hashes', 'random_mechanism'):
        need(same(restored[key], parent[key]), 'snapshot dependency/domain changed: ' + key)
    state = deepcopy(restored['state']); trace = state['trace']
    need(len(trace) == len(parent['state']['trace']) + 1, 'restore must add exactly one real marker')
    marker = trace.pop()
    need(same(marker, {'seq': len(trace), 'time': parent['state']['t'], 'kind': 'snapshot_loaded',
                      'snapshot_sha256': parent['state_sha256'], 'prefix_event_count': len(trace)}), 'restore marker differs')
    need(digest(state) == parent['state_sha256'] and same(state, parent['state']), 'full restored physical state differs')
    return marker


def restore(parent_contract, *, directory, controller, snapshot_writer):
    """Explicit host call, no model/solver and no advancing time. Parent source must be frozen."""
    directory = Path(directory)
    raw, snap_ref = read(parent_contract['checkpoint_path'], parent_contract['checkpoint_sha256'])
    parent = json.loads(raw); state = parent['state']
    need(parent['state_sha256'] == parent_contract['state_sha256']
         and controller.durable.interaction.digest(state) == parent['state_sha256'], 'original checkpoint state hash differs')
    need(state['seed'] == 1701 and type(state['seed']) is int and state['finished'] is False
         and same(state['t'], parent_contract['simulation_start'])
         and same(state['horizon'], 3600.0) and same(state['observation_start'], 0.0), 'fixed V7 physical bounds differ')
    raw_trace, trace_ref = read(parent_contract['trace_path'], parent_contract['trace_sha256'])
    original_events = [json.loads(line) for line in raw_trace.splitlines()]
    need(same(original_events, state['trace']), 'checkpoint and complete raw parent trace differ')
    boot_raw, boot_ref = read(parent_contract['bootstrap_path'], parent_contract['bootstrap_file_sha256'])
    boot = json.loads(boot_raw)
    need(same(boot['base_plan'], state['plan']) and boot['source_sha256'] == parent_contract['parent_source_sha256'], 'original committed plan/source differs')
    directory.mkdir(parents=False, exist_ok=False)
    refs = [snap_ref, trace_ref, boot_ref]
    env = controller.FullFabEnvironment.from_snapshot(parent_contract['checkpoint_path'], trace_path=directory/'trace.jsonl')
    try:
        snapshot_writer(env, directory/'restored_initial.json')
        restored = json.loads((directory/'restored_initial.json').read_bytes())
        marker = compare_restored(parent, restored, digest=controller.json_sha256)
        current = controller.bootstrap(env, run_id=parent_contract['parent_run_name'],
            source_sha256=parent_contract['parent_source_sha256'], page_chars=parent_contract['page_chars'])
        need(same(current, boot), 'restoration changed full current public bootstrap/four anchors')
        need(len(env.physical) == 913 and set(env.physical) == set(boot['problem']['scope']), 'full original machine scope differs')
        prior_ops = set()
        for event in original_events:
            if event['kind'] == 'dispatch' and event['machine'] in env.physical:
                prior_ops.update(zip(event['lots'], event['steps'], event['visits']))
        proof = {'schema': SCHEMA, 'snapshot_sha256': snap_ref['sha256'], 'state_sha256': parent['state_sha256'],
            'parent_trace_sha256': trace_ref['sha256'], 'parent_trace_events': len(original_events),
            'simulation_start': env.t, 'absolute_target': env.horizon, 'period_anchor': env.observation_start,
            'plan_sha256': controller.json_sha256(env.plan), 'executed_identities_sha256': controller.json_sha256(sorted(env.executed_tasks)),
            'production_scope': len(env.physical), 'restore_marker': marker, 'no_physical_advance': True,
            'no_model_call': True, 'accepted': False, 'scope': 'exact restoration only; independent segment attribution/resources remain required'}
        for ref in refs: fence(ref)
        write_new(directory/'restore_receipt.json', raw_json(proof))
        return ResumePhysical(env, controller, boot, refs, prior_ops, parent_contract, directory)
    except BaseException as exc:
        try: write_new(directory/'restore_failure.json', raw_json({'type': type(exc).__name__, 'message': str(exc), 'retry': False}))
        except BaseException as secondary: exc.add_note('restore failure publication: ' + repr(secondary))
        raise


class ResumePhysical:
    def __init__(self, env, controller, boot, refs, prior_ops, contract, directory):
        self.env, self.controller, self.bootstrap = env, controller, boot
        self.refs, self.prior_ops, self.contract = refs, prior_ops, contract
        self.directory = Path(directory); self.poisoned = False; self.committed = False
        self.initial_trace_length = len(env.trace)

    def healthy(self):
        need(not self.poisoned, 'physical resume outcome unknown; no retry')
        try:
            for ref in self.refs: fence(ref)
            need(same(self.env.horizon, 3600.0) and same(self.env.observation_start, 0.0), 'physical evaluation clock changed')
        except BaseException:
            self.poisoned = True; raise

    def before_commit(self, plan, *, expected_bootstrap):
        self.healthy()
        current = self.controller.bootstrap(self.env, run_id=self.contract['parent_run_name'],
            source_sha256=self.contract['parent_source_sha256'], page_chars=self.contract['page_chars'])
        need(same(current, expected_bootstrap), 'physical/public state changed before explicit commit')
        need(plan['version'] not in self.env.plan_versions, 'original committed version cannot be replayed')
        for task in plan['tasks']:
            need(not any(op in self.prior_ops for op in zip(task['lot_ids'], task['steps'], task['visits'])), 'already dispatched production identity reintroduced')

    def commit_once(self, plan, *, expected_bootstrap, record_intent_and_commit):
        self.before_commit(plan, expected_bootstrap=expected_bootstrap)
        try:
            # Caller must record explicit selected-plan intent before common commit.
            before = len(self.env.trace)
            returned = record_intent_and_commit()
            need(len(self.env.trace) == before + 1 and self.env.trace[before]['kind'] == 'plan_committed'
                 and same(self.env.trace[before]['plan'], plan) and same(self.env.plan, plan)
                 and plan['version'] in self.env.plan_versions,
                 'callback did not perform exactly the explicit common commit')
            self.committed = True; self.healthy(); return returned
        except BaseException:
            self.poisoned = True; raise

    def advance_once(self):
        self.healthy(); need(self.committed, 'first new explicit committed plan required; inherited plan never auto-advanced')
        target = self.controller.next_boundary(self.env.t, self.env.observation_start, self.env.horizon, 1800)
        need(target <= 3600.0, 'absolute target exceeded')
        before = len(self.env.trace)
        try:
            stop = self.env.advance_plan(target)
            for event in self.env.trace[before:]:
                if event['kind'] == 'dispatch' and event['machine'] in self.env.physical:
                    ops = list(zip(event['lots'], event['steps'], event['visits']))
                    need(not any(op in self.prior_ops for op in ops), 'repeated production operation dispatched')
                    self.prior_ops.update(ops)
            self.committed = False; self.healthy()
            return {'stop': stop, 'advance_target': target, 'simulation_seconds': self.env.t}
        except BaseException:
            self.poisoned = True; raise
