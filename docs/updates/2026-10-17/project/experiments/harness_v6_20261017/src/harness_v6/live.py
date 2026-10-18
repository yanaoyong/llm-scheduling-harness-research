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
from .prompt_rules import cycle_footer


class LiveRun:
    def __init__(self, factory, runner, *, directory, prefix, source_sha256,
                 context_token_budget, request_overhead_tokens, output_reserve_tokens, token_counter, config=None, drift_rule=None, model='scripted', budget=session.Budget(), model_note='', snapshot_format='explicit', checkpoint_completed=False):
        from .compact import check_format
        self.checkpoint_completed = checkpoint_completed
        self.snapshot_format = check_format(snapshot_format)
        magic = b"SNAPSHOT_V1_DENSE\n" if snapshot_format == "dense" else b"SNAPSHOT_V1\n"
        if not prefix.startswith(magic):
            raise ValueError("snapshot_format does not match prefix")
        self.factory, self.runner = factory, runner
        self.context_token_budget = context_token_budget
        self.request_overhead_tokens = request_overhead_tokens
        self.output_reserve_tokens = output_reserve_tokens
        self.token_counter = token_counter
        if any(type(v) is not int or v < 0 for v in
               (context_token_budget, request_overhead_tokens, output_reserve_tokens)):
            raise ValueError('context budget, overhead and reserve must be nonnegative integers')
        self.budget_report = None
        self.directory = Path(directory)
        self.store = CheckpointStore(self.directory / 'checkpoints')
        if hasattr(factory, 'env'):
            from .compact import decode_prefix, encode_prefix
            static=decode_prefix(prefix)
            static.update(setup_transitions=factory.env.manifest['setups'],min_runs=dict(factory.env.min_runs))
            prefix=encode_prefix(static,snapshot_format=snapshot_format,token_counter=token_counter)
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
        if not self.store.has_checkpoint():
            self.checkpoint(self.store)

    def step(self, *, event=None, until=None):
        c, f = self.cycle, self.factory
        if hasattr(f, "env"):
            f.env.presentation_horizon_seconds = c.config.horizon
        if c.stop_reason:
            return None
        if event is None:
            target = c.anchor if c.config.trigger == 'periodic' else f.now + c.config.horizon
            if until is not None:
                target = min(target, until)
            # First event decision observes the initial factory before advancing.
            if c.config.trigger == 'periodic' or c.last_record is not None or not f.ledger().metrics()['avoidable_idle']:
                event = f.advance_to(target, stop_on_event=c.config.trigger == 'event',
                    **({'stop_at': until} if until is not None else {}))
        if until is not None and f.now >= until:
            return None
        ledger = f.ledger()
        execution = f.execution_state()
        record = c.begin(f.now, avoidable_idle=ledger.metrics()['avoidable_idle'],
                         invalid_tasks=execution.get('invalidated_task_ids', []),
                         valid_until=f.plan['valid_until'] if f.plan else None, event=event)
        if record['session']:
            footer = cycle_footer(state_version=c.cycles, submission_id=str(c.cycles),
                now=f.now, next_anchor=c.anchor, delta=c.config.delta, delta_min=c.config.delta_min,
                trigger=c.config.trigger, interaction=c.config.interaction, wall_seconds=self.budget.wall_seconds)
            try:
                payload = build_snapshot(self.prefix, ledger, horizon_seconds=c.config.horizon, snapshot_format=self.snapshot_format, state_version=c.cycles,
                    running_jobs=f.running_jobs(), last_cycle_receipt=c.last_record,
                    model_notes=self.model_note, token_budget=self.context_token_budget - self.request_overhead_tokens - self.output_reserve_tokens, token_counter=self.token_counter, history=self.history)
                prompt = payload.decode() + footer
                prompt_tokens = self.token_counter(prompt)
                if prompt_tokens + self.request_overhead_tokens + self.output_reserve_tokens > self.context_token_budget:
                    raise SnapshotBudgetExceeded(dict(tokens=prompt_tokens, bytes=len(prompt.encode()), dropped_rows=0))
            except SnapshotBudgetExceeded as exc:
                self.budget_report = dict(exc.report, code='context_budget_exceeded',
                    snapshot_tokens=exc.report['tokens'], request_overhead_tokens=self.request_overhead_tokens,
                    output_reserve_tokens=self.output_reserve_tokens, context_token_budget=self.context_token_budget,
                    request_tokens=exc.report['tokens'] + self.request_overhead_tokens + self.output_reserve_tokens)
                atomic_write(self.directory / 'budget_report.json', canonical(self.budget_report))
                c.finish(submitted=False, model_note=self.model_note)
                c.stop_reason = 'context_budget_exceeded'
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
            if directory.exists():
                attempt = 1
                while directory.with_name(directory.name + f'.abandoned-{attempt}').exists():
                    attempt += 1
                directory.rename(directory.with_name(directory.name + f'.abandoned-{attempt}'))
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
                (inputs / 'private.json').unlink(missing_ok=True)
                if self.checkpoint_completed:
                    self.checkpoint(self.store)
            common = dict(commit=commit, metrics=self.metrics, now=f.now, cycle=c,
                          budget=self.budget, checkpoint=self.store, inflight_bundle=bundle,
                          persist_completed=completed, model_note=self.model_note)
            if c.config.interaction == 'single_action':
                schema = inputs / 'submit.schema.json'; single_action.write_schema(schema)
                argv = single_action.command(inputs, schema, model=self.model, budget=self.budget)
                self.outcome = single_action.run(RecordingRunner(), argv, prompt, submitter=submit, **common)
            else:
                argv = session.command(inputs, outputs, model=self.model, budget=self.budget,
                    env={'PYTHONPATH': os.pathsep.join(str(Path(p).resolve()) for p in sys.path)})
                self.outcome = session.run_session(RecordingRunner(), argv, prompt,
                    initial_state=initial, artifacts=lambda: session.read_artifacts(outputs), **common)
            atomic_write(outputs / 'evidence.json', canonical(self.outcome))
        self._observe_drift()
        if c.inflight is None and (c.stop_reason or (c.last_record and c.last_record.get('segment_boundary'))):
            self.checkpoint(self.store)
            directories = [p for p in self.directory.glob('cycle-*') if p.is_dir() and '.abandoned-' not in p.name]
            if directories and c.last_record and c.last_record.get('segment_boundary'):
                self.store.rotate_logs(c.segment, {'cycles': directories})
        return record

    def _observe_drift(self):
        c, f = self.cycle, self.factory
        if hasattr(f, "env"):
            f.env.presentation_horizon_seconds = c.config.horizon
        completed_hour = int((f.now-c.origin)//3600)-1
        while self.last_hour < completed_hour:
            self.last_hour += 1
            if self.drift and self.drift.observe(self.last_hour, self.metrics.derived(self.metrics.buckets.get(self.last_hour, {}))):
                c.stop_reason = c.stop_reason or 'drift'

    def capture(self):
        return {'factory': self.factory.capture(), 'cycle': self.cycle.capture(), 'metrics': self.metrics.capture(),
                'snapshot_format': self.snapshot_format, 'history': self.history.digest, 'budget_report': self.budget_report, 'max_snapshot_bytes': self.max_snapshot_bytes,
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
        if state.get('snapshot_format', 'explicit') != self.snapshot_format:
            raise ValueError('checkpoint snapshot_format mismatch')
        self.budget_report = state.get('budget_report')
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
        (self.directory / f'cycle-{self.cycle.cycles}' / 'input/private.json').unlink(missing_ok=True)
        self._observe_drift()
        if self.cycle.stop_reason:
            self.checkpoint(self.store)
        return self

    def state_hash(self):
        return json_sha256(self.capture())
