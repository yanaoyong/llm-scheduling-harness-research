from copy import deepcopy
from mac_fixture import environment

def test_time_semantics():
    env,b=environment('d34_421')
    plan=b['d34_421']['plan']
    before=deepcopy(plan)
    env.commit_plan(plan)
    assert env.plan==before
    assert any(t.get('not_before',env.t)<env.t for t in plan['tasks'])

def test_frozen_invalidated():
    env,b=environment('frozen_invalidated')
    fixture=b['frozen_invalidated']
    assert env.invalidated_task_ids and env.plan['freeze_until']>env.t
    cancelled=set(env.invalidated_task_ids)
    env.commit_plan(fixture['plan'])
    assert not cancelled.intersection(t['id'] for t in env.plan['tasks'])
    assert env.advance_cycle(fixture['until'])['reason']!='plan_invalidated'

def test_when_ready():
    env,b=environment('when_ready')
    fixture=b['when_ready'];env.commit_plan(fixture['plan'])
    env.advance_cycle(fixture['until'])
    dispatch=[e for e in env.trace if e['kind']=='dispatch' and e['time']>=fixture['state']['t']]
    assert dispatch==fixture['expected_dispatches']

def test_advance_cycle():
    env,b=environment('advance_cycle')
    fixture=b['advance_cycle'];env.commit_plan(fixture['plan'])
    result=env.advance_cycle(fixture['until'])
    assert result['reason']==fixture['expected_reason']
    assert env.t==fixture['expected_time']
    from harness_v6.audit_v6 import audit_opportunity_coverage
    segment=[e for e in env.trace if e['time']>=fixture['state']['t']]
    audit=audit_opportunity_coverage(segment)
    assert audit['steps']>0 and audit['valid'],audit

def test_submit_precheck():
    env,b=environment('d34_421')
    from harness_v6.factory_v6 import prepare,capture
    before=capture(env);clone=prepare(env,b['d34_421']['plan'])
    assert capture(env)==before and clone.plan==b['d34_421']['plan']
