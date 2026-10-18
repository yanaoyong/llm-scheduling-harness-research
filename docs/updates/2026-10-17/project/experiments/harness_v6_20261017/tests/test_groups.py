from copy import deepcopy
import json
from pathlib import Path
import pytest
from harness_v6.cycle import CycleMachine, CycleConfig
from harness_v6.groups import GROUPS, config_for
from harness_v6.ledger import ledger_from_scratch
from harness_v6.metrics import Metrics
from harness_v6.registration import validate
from harness_v6.single_action import command, write_schema, OUTPUT_SCHEMA, parse, finish, run, audit_provenance, raw_delta
from harness_v6.session import RunResult, Budget
from harness_v6.submit import Submitter
from harness_v6.synthetic import SyntheticFactory, SyntheticRun, SOURCE, scripted_delta


def setup_action():
    f = SyntheticFactory()
    s = Submitter(f.plan, f.problem(), f.execution_state(), state_version=1,
                  next_anchor=None, source_sha256=SOURCE, trigger='event')
    return f, s, dict(expected_state_version=1, submission_id='one', delta=scripted_delta(f, 1))


def jsonl(args, extra=()):
    return '\n'.join(json.dumps(e, sort_keys=True, separators=(',', ':')) for e in [
        *extra,
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(args)}},
        {'type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 40, 'output_tokens': 10}}])


@pytest.mark.parametrize('group', GROUPS)
def test_fifty_decisions_per_group(group):
    r = SyntheticRun(group=group); times = []
    for _ in range(55):
        record = r.step()
        assert record['session'] and r.cycle.last_record['success']
        assert r.cycle.stop_reason is None
        times.append(r.factory.now)
    assert all(a < b for a, b in zip(times, times[1:]))
    assert r.factory.completed > 0
    totals = {k: sum(b.get(k, 0) for b in r.metrics.buckets.values())
              for k in ('sessions', 'model_request_lower_bound', 'uncached_equivalent_input_tokens')}
    assert totals['sessions'] == 55
    assert totals['model_request_lower_bound'] == 55 * (1 if GROUPS[group]['interaction'] == 'single_action' else 3)
    assert totals['uncached_equivalent_input_tokens'] == 5500
    for row in r.metrics.report().values():
        if row.get('simulated_seconds'):
            assert row['uncached_equivalent_input_tokens_per_sim_hour'] == pytest.approx(
                row['uncached_equivalent_input_tokens'] * 3600 / row['simulated_seconds'])


def test_event_matching_not_uncovered_or_reservation_opportunity():
    p = {'time': 0, 'machines': [{'machine': 1}, {'machine': 2}],
         'operations': [{'operation_id': 'a', 'lot_id': 'a', 'step': 1, 'visit': 1,
                         'eligible_machines': [1, 2], 'batch_key': ['x'], 'batch_min': 2, 'batch_max': 2}]}
    plan = {'created_at': 0, 'tasks': [], 'holds': []}
    c = CycleMachine(config=config_for('E1'))
    assert c.anchor is None
    ledger = ledger_from_scratch(p, plan)
    assert ledger.rows()['a']['state'] == 'ready_unreserved'
    assert not c.begin(0, avoidable_idle=ledger.metrics()['avoidable_idle'])['session']
    p['operations'][0].update(batch_min=1)
    p['machines'][0].update(currently_busy=True, available_at=100)
    plan['tasks'] = [{'id': 'reserved', 'machine': 1, 'operation_ids': ['a'], 'not_before': 100}]
    ledger = ledger_from_scratch(p, plan)
    assert ledger.metrics()['reserved_but_earlier_startable']
    assert not c.begin(7, avoidable_idle=ledger.metrics()['avoidable_idle'])['session']
    plan['tasks'] = []
    ledger = ledger_from_scratch(p, plan)
    assert ledger.metrics()['avoidable_idle'] > 0
    assert c.begin(7.25, avoidable_idle=ledger.metrics()['avoidable_idle'])['session']
    assert c.inflight['time'] == 7.25 and c.anchor is None


def test_synthetic_event_decision_at_first_completion():
    r = SyntheticRun(group='E1'); r.step(); r.factory._dispatch(r.metrics)
    first = min(j['end'] for j in r.factory.running)
    record = r.step()
    assert record['time'] == first and record['avoidable_idle'] > 0


@pytest.mark.parametrize('end,accepted', [(60, False), (60.001, True), (59, False)])
def test_event_strict_validity(end, accepted):
    f, s, args = setup_action()
    args['delta']['plan_header']['valid_until'] = end
    assert s.submit_plan(**args)['accepted'] is accepted


def test_event_custom_min_and_nonzero_now():
    f = SyntheticFactory(); f.now = 100
    s = Submitter(f.plan, f.problem(), f.execution_state(), state_version=1, next_anchor=None,
                  trigger='event', delta_min=30, source_sha256=SOURCE)
    d = scripted_delta(f, 1); d['plan_header']['valid_until'] = 130
    assert not s.submit_plan(1, 'short', d)['accepted']
    d['plan_header']['valid_until'] = 131
    assert s.submit_plan(1, 'ok', d)['accepted']


def test_event_failure_and_stall_with_time_advancing():
    c = CycleMachine(config=config_for('E1'))
    c.begin(0, avoidable_idle=1); c.finish(submitted=False)
    assert not c.begin(0, avoidable_idle=1)['session']
    c.begin(13.5, avoidable_idle=1); c.finish(submitted=False)
    assert c.stop_reason == 'consecutive_failures'
    for success in (False, True):
        c = CycleMachine(config=CycleConfig(trigger='event', k_fail=10, stall_cycles=3))
        for t in (1, 15, 125):
            c.begin(t, avoidable_idle=1); c.finish(submitted=success)
        assert c.stop_reason == 'stall'


@pytest.mark.parametrize('event', ['plan_invalidated', 'expired_task', 'no_plan', 'terminal', 'breakdown'])
def test_event_interrupts(event):
    c = CycleMachine(config=CycleConfig(trigger='event', breakdowns=True))
    r = c.begin(17, event=event, invalid_tasks=['x'], avoidable_idle=1)
    assert r['session'] and r['next_anchor'] is None
    c.finish(submitted=True)
    if event == 'terminal': assert c.stop_reason == 'terminal'


@pytest.mark.parametrize('kind', ['mcp_tool_call', 'command_execution', 'web_search', 'file_change', 'unknown_tool'])
@pytest.mark.parametrize('stage', ['item.started', 'item.updated', 'item.completed'])
def test_any_tool_item_rejected(kind, stage):
    _, _, args = setup_action()
    raw = jsonl(args, [{'type': stage, 'item': {'type': kind}}])
    assert 'forbidden_item:' + kind in parse(raw)['errors']


def test_command_schema_and_fake_runner(tmp_path):
    f, s, args = setup_action()
    schema = tmp_path / 'schema.json'; write_schema(schema)
    assert json.loads(schema.read_text()) == OUTPUT_SCHEMA
    argv = command(tmp_path, schema, model='fake')
    assert argv[:2] == ['codex', 'exec']
    assert all(v in argv for v in ('--ephemeral', '--json', '--output-schema', 'mcp_servers={}'))
    assert not any('mcp_servers.' in v for v in argv)
    calls = []
    class Fake:
        def run(self, command, prompt, *, timeout):
            calls.append((command, prompt, timeout))
            return RunResult(jsonl(args))
    metrics = Metrics(); state = s.capture()
    outcome = run(Fake(), argv, 'snapshot', submitter=s, commit=lambda v, p: True, metrics=metrics, now=0)
    assert len(calls) == 1 and outcome['adopted']
    assert raw_delta(outcome['evidence']['jsonl']) == args['delta']
    assert not audit_provenance(outcome['evidence'], state)
    row = metrics.report()[0]
    assert row['sessions'] == row['model_request_lower_bound'] == 1
    assert row['uncached_equivalent_input_tokens'] == 64
    bad = deepcopy(outcome['evidence']); bad['plan']['tasks'][0]['machine'] = 2
    assert 'production_not_from_model' in audit_provenance(bad, state)
    bad = deepcopy(outcome['evidence']); bad['arguments']['delta']['tasks']['add'] = []
    assert 'final_output_mismatch' in audit_provenance(bad, state)


@pytest.mark.parametrize('failure', ['crash', 'timeout', 'tool', 'usage', 'final', 'stale', 'budget', 'wall'])
def test_single_failure_retains_plan_and_counts_cost(failure):
    f, s, args = setup_action(); old = deepcopy(f.plan)
    raw = jsonl(args); result = RunResult(raw)
    if failure == 'crash': result.returncode = 1
    if failure == 'timeout': result.timed_out = True
    if failure == 'tool': result.jsonl = jsonl(args, [{'type': 'item.started', 'item': {'type': 'command_execution'}}])
    if failure == 'usage': result.jsonl = raw.rsplit('\n', 1)[0]
    if failure == 'final':
        events = [json.loads(line) for line in raw.splitlines()]
        events.insert(-1, {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'not JSON'}})
        result.jsonl = '\n'.join(json.dumps(e) for e in events)
    budget = Budget(token_cap=1) if failure == 'budget' else Budget()
    if failure == 'wall': result.wall_seconds = 301
    metrics = Metrics(); commits = []
    def commit(v, plan):
        commits.append(plan); return False
    outcome = finish(result, submitter=s, commit=commit, metrics=metrics, now=0, budget=budget)
    assert not outcome['adopted'] and not s.adopted
    assert s.finalize(process_ok=True) == old
    assert bool(commits) == (failure == 'stale')
    assert metrics.report()[0]['model_request_lower_bound'] == 1


def test_registration_mapping_and_all_groups():
    value = json.loads((Path(__file__).parents[1] / 'registration_template.json').read_text())
    value['groups'] = list(GROUPS); value['group_configs'] = deepcopy(GROUPS)
    assert not validate(value)
    value['group_configs']['E1']['trigger'] = 'periodic'
    assert 'group_config:E1' in validate(value)
    value['delta_min_seconds'] = 0
    assert 'delta_min_seconds' in validate(value)


def test_event_breakdown_off_still_measures_idle_and_terminal_is_immediate():
    c = CycleMachine(config=config_for('E1'))
    assert not c.begin(2, event='breakdown', invalid_tasks=[])['session']
    assert c.begin(3, event='breakdown', avoidable_idle=1)['session']
    c.finish(submitted=True, model_note='explained')
    assert c.begin(3, event='terminal')['session']
    c.finish(submitted=True)
    assert c.stop_reason == 'terminal'


@pytest.mark.parametrize('group', GROUPS)
def test_group_checkpoint_roundtrip(group, tmp_path):
    from harness_v6.checkpoint import CheckpointStore
    r = SyntheticRun(group=group)
    for _ in range(5): r.step()
    store = CheckpointStore(tmp_path)
    r.checkpoint(store)
    restored = SyntheticRun.restore(store.latest())
    for _ in range(5):
        r.step(); restored.step()
    assert r.state_hash() == restored.state_hash()


def test_failures_use_k_fail_when_idle_improves():
    c = CycleMachine(config=CycleConfig(trigger='event', k_fail=10, stall_cycles=3))
    for t, idle in [(1, 3), (2, 2), (3, 1)]:
        c.begin(t, avoidable_idle=idle)
        c.finish(submitted=False, model_note='explanation')
    assert c.stop_reason is None and c.failures == 3


@pytest.mark.parametrize('key,value', [('trigger','bad'), ('interaction','bad'), ('delta_min',0)])
def test_invalid_modes(key, value):
    with pytest.raises(ValueError): CycleConfig(**{key: value})
