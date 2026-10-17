"""Single trajectory host: paused frozen inputs, audited adoption, durable recovery.

The environment supplies now/plan, problem(), execution_state(), ledger(),
advance_to(t, stop_on_event), adopt(plan), capture()/restore(), running_jobs()
and private_state() (None for synthetic physics). Only the injected Runner
produces planning decisions. No subprocess or model is launched by this module.
"""
from pathlib import Path
import os
import sys
from .snapshot import canonical, HistorySummary, build_snapshot, SnapshotBudgetExceeded
from .plan_delta import json_sha256
from .cycle import CycleMachine, CycleConfig, DriftMonitor, DriftRule
from .metrics import Metrics
from .submit import Submitter
from .facts import build_facts
from .checkpoint import CheckpointStore, capture_ledger as ledger_capture, atomic_write
from . import session, single_action


class LiveRun:
    def __init__(self, factory, runner, *, directory, prefix, source_sha256,
                 config=None, drift_rule=None, model='scripted', budget=session.Budget(), model_note=''):
        self.factory, self.runner = factory, runner
        self.directory = Path(directory)
        self.store = CheckpointStore(self.directory / 'checkpoints')
        self.prefix, self.source_sha256 = prefix, source_sha256
        self.model, self.budget, self.model_note = model, budget, model_note
        self.cycle = CycleMachine(origin=factory.now, config=config or CycleConfig())
        self.metrics = Metrics(origin=factory.now, exclude_first_hours=1)
        factory.metrics = self.metrics
        self.history = HistorySummary()
        self.max_snapshot_bytes = 0
        self.min_snapshot_bytes = None
        self.drift = DriftMonitor(drift_rule) if drift_rule else None
        self.last_hour = -1
        if not (self.store.directory / 'latest.json').exists():
            self.checkpoint(self.store)

    def step(self, *, event=None):
        c, f = self.cycle, self.factory
        if c.stop_reason:
            return None
        if event is None:
            target = c.anchor if c.config.trigger == 'periodic' else f.now + c.config.horizon
            # First event decision observes the initial factory before advancing.
            if c.config.trigger == 'periodic' or c.last_record is not None or not f.ledger().metrics()['avoidable_idle']:
                event = f.advance_to(target, stop_on_event=c.config.trigger == 'event')
        ledger = f.ledger()
        execution = f.execution_state()
        record = c.begin(f.now, avoidable_idle=ledger.metrics()['avoidable_idle'],
                         invalid_tasks=execution.get('invalidated_task_ids', []),
                         valid_until=f.plan['valid_until'] if f.plan else None, event=event)
        if record['session']:
            try:
                payload = build_snapshot(self.prefix, ledger, state_version=c.cycles,
                    running_jobs=f.running_jobs(), last_cycle_receipt=c.last_record,
                    model_notes=self.model_note, token_budget=self.budget.token_cap, history=self.history)
            except SnapshotBudgetExceeded:
                c.finish(submitted=False, model_note=self.model_note)
                c.stop_reason = 'snapshot_budget_exceeded'
                self.checkpoint(self.store)
                return record
            self.max_snapshot_bytes = max(self.max_snapshot_bytes, len(payload))
            self.min_snapshot_bytes = min(self.min_snapshot_bytes or len(payload), len(payload))
            config = dict(state_version=c.cycles, next_anchor=c.anchor, delta_seconds=c.config.delta,
                          source_sha256=self.source_sha256, trigger=c.config.trigger, delta_min=c.config.delta_min)
            problem = f.problem()
            submit = Submitter(f.plan, problem, execution, **config)
            initial = submit.capture()
            directory = self.directory / f'cycle-{c.cycles}'
            inputs, outputs = directory / 'input', directory / 'output'
            inputs.mkdir(parents=True); outputs.mkdir()
            frozen = dict(snapshot={'text': payload.decode()}, facts=build_facts(problem, f.plan),
                          context_ref=f'cycle:{c.cycles}', execution_state=execution, submit_config=config)
            private = f.private_state()
            if private is not None:
                frozen['private_state'] = 'private.json'
                atomic_write(inputs / 'private.json', canonical(private))
            atomic_write(inputs / 'cycle.json', canonical(frozen))
            atomic_write(directory / 'initial.json', canonical(initial))
            captured = self.capture()
            bundle = dict(state=captured.pop('factory'), cycle=captured.pop('cycle'),
                          ledger=ledger_capture(ledger), submit=initial, extra=captured, model_note=self.model_note)
            def commit(version, plan):
                if version != c.cycles or c.inflight is None:
                    return False
                f.adopt(plan)
                return True
            class RecordingRunner:
                def run(_, argv, prompt, *, timeout):
                    result = self.runner.run(argv, prompt, timeout=timeout)
                    atomic_write(outputs / 'session.jsonl', result.jsonl.encode())
                    return result
            def completed(outcome):
                self.history = self.history.append({'adopted': outcome['adopted']})
                self._observe_drift()
                self.checkpoint(self.store)
            common = dict(commit=commit, metrics=self.metrics, now=f.now, cycle=c,
                          budget=self.budget, checkpoint=self.store, inflight_bundle=bundle,
                          persist_completed=completed, model_note=self.model_note)
            if c.config.interaction == 'single_action':
                schema = inputs / 'submit.schema.json'; single_action.write_schema(schema)
                argv = single_action.command(inputs, schema, model=self.model, budget=self.budget)
                self.outcome = single_action.run(RecordingRunner(), argv, payload.decode(), submitter=submit, **common)
                atomic_write(outputs / 'evidence.json', canonical(self.outcome))
            else:
                argv = session.command(inputs, outputs, model=self.model, budget=self.budget,
                    env={'PYTHONPATH': os.pathsep.join(str(Path(p).resolve()) for p in sys.path)})
                self.outcome = session.run_session(RecordingRunner(), argv, payload.decode(),
                    initial_state=initial, artifacts=lambda: session.read_artifacts(outputs), **common)
        self._observe_drift()
        if c.inflight is None and c.last_record and c.last_record.get('segment_boundary'):
            self.checkpoint(self.store)
        return record

    def _observe_drift(self):
        c, f = self.cycle, self.factory
        completed_hour = int((f.now-c.origin)//3600)-1
        while self.last_hour < completed_hour:
            self.last_hour += 1
            if self.drift and self.drift.observe(self.last_hour, self.metrics.derived(self.metrics.buckets.get(self.last_hour, {}))):
                c.stop_reason = c.stop_reason or 'drift'

    def capture(self):
        return {'factory': self.factory.capture(), 'cycle': self.cycle.capture(), 'metrics': self.metrics.capture(),
                'history': self.history.digest, 'max_snapshot_bytes': self.max_snapshot_bytes,
                'min_snapshot_bytes': self.min_snapshot_bytes, 'last_hour': self.last_hour,
                'drift': None if not self.drift else {'limits': self.drift.rule.limits,
                    'consecutive_hours': self.drift.rule.consecutive_hours, 'streak': self.drift.streak,
                    'last_hour': self.drift.last_hour}}

    def checkpoint(self, store):
        captured = self.capture()
        return store.save(self.cycle.segment, state=captured.pop('factory'), cycle=captured.pop('cycle'),
                          ledger=ledger_capture(self.factory.ledger()), cumulative_costs={'cost': self.cycle.cost,
                          'wall_seconds': self.cycle.wall_seconds}, extra=captured)

    def recover(self):
        payload = self.store.recover()
        state = payload['extra']
        self.factory = self.factory.restore(payload['state'])
        self.cycle = CycleMachine.restore(payload['cycle'])
        self.metrics = Metrics.restore(state['metrics'])
        self.factory.metrics = self.metrics
        self.history = HistorySummary(state['history'])
        for key in ('max_snapshot_bytes', 'min_snapshot_bytes', 'last_hour'):
            setattr(self, key, state[key])
        if state['drift']:
            d = state['drift']; self.drift = DriftMonitor(DriftRule(d['limits'], d['consecutive_hours']))
            self.drift.streak = d['streak']; self.drift.last_hour = d['last_hour']
        self._observe_drift()
        self.checkpoint(self.store)
        return self

    def state_hash(self):
        return json_sha256(self.capture())
