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


def test_event_trigger():
    env, b = environment('event_trigger')
    fixture = b['event_trigger']
    env.commit_plan(fixture['plan'])
    result = env.advance_cycle(fixture['until'], trigger='event')
    assert result['reason'] == 'avoidable_idle'
    assert env.t == fixture['expected_time']
    assert env.ledger_snapshot()['metrics']['avoidable_idle'] > 0


def test_public_time_semantics():
    env,b=environment('public_time_semantics')
    plan=b['public_time_semantics']['plan']
    from harness_v6.factory_v6 import prepare,capture
    before=capture(env); clone=prepare(env,plan)
    assert capture(env)==before and clone.plan==plan
    clone.advance_cycle(env.t+0.01)
    assert any(e['kind']=='dispatch' and e['time']==env.t for e in clone.trace[len(env.trace):])


def test_public_hard_bound_and_default_mode():
    env,b=environment('when_ready')
    plan=deepcopy(b['when_ready']['plan'])
    task=plan['tasks'][0]
    task.pop('start_mode',None)
    task['not_before']=env.t+0.5
    start=len(env.trace)
    env.commit_plan(plan)
    env.advance_cycle(env.t+0.25)
    assert not any(e['kind']=='dispatch' and e['machine']==task['machine'] for e in env.trace[start:])
    env.advance_cycle(task['not_before']+0.01)
    events=[e for e in env.trace[start:] if e['kind']=='dispatch' and e['machine']==task['machine']]
    assert len(events)==1 and events[0]['time']==task['not_before']


def test_public_observation_cache_matches_original():
    from pathlib import Path
    from types import ModuleType
    env,b=environment()
    root=Path(__file__).resolve().parents[2]
    source=root/'context_window_batch60_20261016/src/smt_fullfab/observation.py'
    original=ModuleType('original_observation_reference')
    exec(compile(source.read_text(),str(source),'exec'),original.__dict__)
    assert env.problem()==original.build_problem(env)
    env._events_to(env.q[0][0])
    assert env.problem()==original.build_problem(env)


def test_public_expired_conditional_hold_anchor_gone():
    env,b=environment('public_time_semantics')
    plan=deepcopy(b['public_time_semantics']['plan'])
    plan['holds'][0]['after_task_id']='completed-task-no-longer-in-plan'
    env.commit_plan(plan)
    assert env.plan==plan
    env.advance_cycle(env.t+0.01)
    from harness_v6.audit_v6 import audit_plan_sources
    result=audit_plan_sources(env.trace)
    assert result['valid'],result['errors']


def test_public_frozen_default_when_ready_observation():
    env,b=environment('when_ready')
    plan=deepcopy(b['when_ready']['plan']);plan['freeze_until']=env.t+10
    for t in plan['tasks']:t.pop('not_before',None)
    env.commit_plan(plan)
    problem=env.problem()
    assert len(problem['frozen_tasks'])==len(plan['tasks'])
    assert all(t['original_not_before']==env.t for t in problem['frozen_tasks'])
    assert env.plan==plan


def test_public_breakdown_switch():
    """Controlled public-state fault injection; not a natural-event frequency claim."""
    from harness_v6.factory_v6 import capture,restore
    env,b=environment('when_ready')
    state=capture(env)
    for enabled in (False,True):
        probe=restore(state,env.trace,data_dir=b['data_dir']);probe.breakdowns=enabled
        plan=deepcopy(b['when_ready']['plan']);task=plan['tasks'][0]
        task['not_before']=probe.t+10
        probe.commit_plan(plan)
        key=next(k for k,c in probe.calendars.items() if c['machine']==task['machine'] and c['breakdown'])
        probe._calendar({'key':key,'n':0})
        result=probe.advance_cycle(probe.t+0.01)
        assert (result['reason']=='plan_invalidated')==enabled
        assert (task['id'] in probe.invalidated_task_ids)==enabled
        if enabled:
            replacement={**plan,'version':'cancel-after-breakdown','tasks':[]}
            probe.commit_plan(replacement)
            assert probe.advance_cycle(probe.t+0.01)['reason']=='periodic_replan'


def test_public_latest_start_interrupt():
    import math
    env,b=environment('when_ready');plan=deepcopy(b['when_ready']['plan']);task=plan['tasks'][0]
    task['latest_start']=env.t+0.5
    plan['holds']=[dict(machine=task['machine'],until=env.t+1,reason='controlled expiry test')]
    env.commit_plan(plan)
    result=env.advance_cycle(env.t+1)
    assert result['reason']=='expired_task'
    assert env.t==math.nextafter(task['latest_start'],math.inf)
