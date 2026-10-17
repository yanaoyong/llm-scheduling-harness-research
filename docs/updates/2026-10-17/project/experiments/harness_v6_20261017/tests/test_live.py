"""Host integration; scripted non-model fixtures only."""
from copy import deepcopy
import itertools
import json
import pytest
from harness_v6.synthetic import SyntheticRun
from harness_v6.session import classify, RunResult
from harness_v6.evidence import audit_provenance
from harness_v6.checkpoint import capture_ledger, restore_ledger
from harness_v6.ledger import ledger_from_scratch
from harness_v6.audit_ledger import audit_ledger
from harness_v6.cycle import CycleMachine, CycleConfig
from test_ledger import fixture, op

@pytest.mark.parametrize('group', ['E1','P1','E2','P2'])
def test_live_fifty_audited_decisions(group, tmp_path):
    run = SyntheticRun(group=group, directory=tmp_path)
    from harness_v6.live import LiveRun
    assert isinstance(run, LiveRun)
    for _ in range(50):
        assert run.step()['session']
        assert run.outcome['adopted'], run.outcome
        directory = tmp_path / f'cycle-{run.cycle.cycles}'
        if group.endswith('2'):
            rows = [json.loads(line) for line in (directory/'output/mcp.jsonl').read_text().splitlines()]
            submission = json.loads((directory/'output/submission.json').read_text())
            initial = json.loads((directory/'initial.json').read_text())
            parsed = classify((directory/'output/session.jsonl').read_text())
            assert not audit_provenance(rows, parsed['calls'], submission, initial)
            assert parsed['tool_rounds'] == 3
    assert run.cycle.sessions == 50

def test_tampered_jsonl_keeps_old_plan(tmp_path):
    run = SyntheticRun(directory=tmp_path); run.step()
    old = deepcopy(run.factory.plan); original = run.runner.run
    def tamper(*args, **kw):
        result = original(*args, **kw)
        events = [json.loads(line) for line in result.jsonl.splitlines()]
        events[-2]['item']['arguments']['submission_id'] = 'tampered'
        result.jsonl = '\n'.join(json.dumps(e) for e in events)
        return result
    run.runner.run = tamper; run.step()
    assert not run.outcome['adopted'] and run.factory.plan == old
    assert run.cycle.failures == 1

def test_mid_session_recover_matches_failed_cycle(tmp_path):
    crashed = SyntheticRun(directory=tmp_path/'crashed'); failed = SyntheticRun(directory=tmp_path/'failed')
    for run in (crashed, failed): run.step()
    old = deepcopy(crashed.factory.plan); original = crashed.runner.run
    def crash(*args, **kw):
        original(*args, **kw); raise RuntimeError('host crash after submission')
    crashed.runner.run = crash
    with pytest.raises(RuntimeError, match='host crash'): crashed.step()
    assert (tmp_path/'crashed/cycle-2/output/submission.json').exists()
    crashed.recover(); assert crashed.factory.plan == old
    crashed.runner.run = original
    other = failed.runner.run; failed.runner.run = lambda *args, **kw: RunResult('', returncode=1)
    failed.step(); failed.runner.run = other
    for _ in range(5): crashed.step(); failed.step()
    assert crashed.factory.capture() == failed.factory.capture()
    assert crashed.cycle.capture() == failed.cycle.capture()
    assert crashed.metrics.capture() == failed.metrics.capture()
    assert crashed.state_hash() == failed.state_hash()

@pytest.mark.parametrize('stages,rounds', [([],0), (['s','c','s','c','s','c'],3), (['s','s','c','c','s','c'],2)])
def test_request_rounds(stages, rounds):
    events=[]; pending=[]; index=0
    for stage in stages:
        if stage=='s':
            identity=str(index); index+=1; pending.append(identity)
        else: identity=pending.pop(0)
        events.append(dict(type='item.started' if stage=='s' else 'item.completed',
            item=dict(type='mcp_tool_call', id=identity, server='harness_v6', tool='get_decision_snapshot', arguments={}, status='completed')))
    events.append(dict(type='turn.completed', usage=dict(input_tokens=1,cached_input_tokens=0,output_tokens=0)))
    parsed=classify('\n'.join(json.dumps(e) for e in events))
    assert not parsed['errors'] and parsed['tool_rounds']==rounds
    from harness_v6.metrics import Metrics
    m=Metrics(); m.session(0,tool_calls=index,tool_rounds=parsed['tool_rounds'])
    assert m.report()[0]['model_request_lower_bound']==rounds+1

@pytest.mark.parametrize('trigger',['periodic','event'])
def test_hold_only_wait_until_expiry(trigger):
    p,plan=fixture();p['machines']=p['machines'][:1];plan['holds']=[dict(machine=1,until=70)]
    values=ledger_from_scratch(p,plan).metrics()
    assert values['avoidable_idle']==0 and values['explicit_wait_idle']==1
    assert audit_ledger(p,plan)['avoidable_idle']==0
    from harness_v6.audit_v6 import audit_idle
    assert audit_idle(p,plan)==audit_ledger(p,plan)
    c=CycleMachine(origin=10,config=CycleConfig(trigger=trigger))
    assert not c.begin(10,avoidable_idle=values['avoidable_idle'],valid_until=900)['session']
    p['time']=70;values=ledger_from_scratch(p,plan).metrics()
    assert values['avoidable_idle']==1 and values['explicit_wait_idle']==0
    assert c.begin(70,avoidable_idle=values['avoidable_idle'],valid_until=900)['session']
    plan['holds']=[dict(machine=1,until=100,after_task_id='not-started')]
    assert ledger_from_scratch(p,plan).metrics()['avoidable_idle']==1

def test_idless_holds_checkpoint_exact():
    p,plan=fixture();plan['holds']=[dict(machine=1,until=30),dict(machine=2,until=40,after_task_id='anchor')]
    before=deepcopy(plan);ledger=ledger_from_scratch(p,plan)
    restored=restore_ledger(json.loads(json.dumps(capture_ledger(ledger))))
    assert restored.holds==ledger.holds
    assert restored.rows()==ledger.rows() and restored.metrics()==ledger.metrics()
    assert plan==before and all('id' not in h for h in restored.holds.values())

def test_greedy_is_bounded_by_exhaustive_maximum():
    # Greedy assigns flexible a to machine 1; optimum reserves 1 for b/c.
    differs=[]
    for qualifications in itertools.product(([1],[2],[1,2]), repeat=3):
        operations=[dict(op(chr(97+i)),eligible_machines=mid) for i,mid in enumerate(qualifications)]
        p=dict(time=0,machines=[dict(machine=1),dict(machine=2)],operations=operations); maximum=0
        for assignment in itertools.product((None,1,2),repeat=len(operations)):
            assigned=[m for m in assignment if m is not None]
            if len(set(assigned))!=len(assigned): continue
            if all(m is None or m in o['eligible_machines'] for m,o in zip(assignment,operations)):
                maximum=max(maximum,len(assigned))
        greedy=ledger_from_scratch(p).metrics()['avoidable_idle']
        from harness_v6.audit_v6 import audit_idle
        assert greedy==audit_ledger(p)['avoidable_idle']==audit_idle(p)['avoidable_idle']<=maximum
        if greedy<maximum: differs.append((qualifications,greedy,maximum))
    assert (([1,2],[1],[1]),1,2) in differs

def test_chain_checks_earlier_segment(tmp_path):
    run=SyntheticRun(directory=tmp_path);run.step();run.step()
    prior=run.store.latest()['previous']; (run.store.directory/prior['file']).write_text('tampered')
    with pytest.raises(ValueError,match='hash'): run.store.latest()

def test_private_precheck_rejects(monkeypatch,tmp_path):
    from harness_v6 import factory_v6
    from harness_v6.mcp_server import CycleServer
    run=SyntheticRun(directory=tmp_path/'run');run.step(); inputs=tmp_path/'run/cycle-1/input'
    frozen=json.loads((inputs/'cycle.json').read_text());frozen['private_state']='private.json'
    (inputs/'private.json').write_text('{}');(inputs/'cycle.json').write_text(json.dumps(frozen));calls=[]
    monkeypatch.setattr(factory_v6,'restore',lambda state,trace: calls.append('restore') or object())
    def reject(env,plan):
        calls.append('prepare');raise ValueError('physical rejection')
    monkeypatch.setattr(factory_v6,'prepare',reject)
    args=json.loads((tmp_path/'run/cycle-1/output/submission.json').read_text())['arguments']
    server=CycleServer(inputs,tmp_path/'reject')
    try: receipt=server.call('submit_plan',args)
    finally: server.close()
    assert calls==['restore','prepare'] and not receipt['accepted']
    assert any(v['code']=='physical_precheck' for v in receipt['violations'])
    assert not (tmp_path/'reject/submission.json').exists()

def test_mac_live_p2_three_cycles(tmp_path):
    from mac_fixture import environment
    env,b=environment('mixed_702')
    from harness_v6.factory_v6 import LiveFactory
    from harness_v6.live import LiveRun
    from harness_v6.synthetic import ScriptedRunner, SOURCE
    from harness_v6.snapshot import stable_prefix
    from harness_v6.session import Budget
    def planner(frozen):
        from harness_v6.facts import reconstruct
        from harness_v6.plan_delta import SCHEMA, ORDER_POLICY, anchor_hashes
        problem,base=reconstruct(frozen['facts']);state=frozen['execution_state']
        config=frozen['submit_config'];now=state['time']
        delta=dict(schema=SCHEMA,order_policy=ORDER_POLICY,machine_orders=[],
            anchors=anchor_hashes(base,problem,state,source_sha256=SOURCE),
            plan_header=dict(version='live-'+str(config['state_version']),created_at=now,
                valid_until=now+900,freeze_until=now,reason='scripted mechanism test',scope=base['scope']))
        return dict(expected_state_version=config['state_version'],submission_id=str(config['state_version']),delta=delta)
    run=LiveRun(LiveFactory(env),ScriptedRunner(planner),directory=tmp_path,
        prefix=stable_prefix(tool_descriptions=[],routing=[],machine_groups=[]),source_sha256=SOURCE,
        budget=Budget(token_cap=10**8),model_note='scripted mechanism test')
    for _ in range(3):
        assert run.step()['session']
        assert run.outcome['adopted'],run.outcome
        assert (tmp_path/f'cycle-{run.cycle.cycles}/input/private.json').exists()
    assert run.cycle.sessions==3


def test_snapshot_budget_stops_before_runner(tmp_path):
    from harness_v6.session import Budget
    run=SyntheticRun(directory=tmp_path);run.budget=Budget(token_cap=1)
    def forbidden(*args,**kwargs): raise AssertionError('runner must not launch')
    run.runner.run=forbidden
    run.step()
    assert run.cycle.stop_reason=='snapshot_budget_exceeded'
    assert not run.metrics.buckets
    assert run.store.latest()['cycle']['stop_reason']=='snapshot_budget_exceeded'
