from copy import deepcopy
from pathlib import Path
import pytest
from harness_v6.registration import load,validate
from harness_v6.replay import equivalence
from harness_v6.audit_v6 import audit_opportunity_coverage
from harness_v6.synthetic import SyntheticFactory


def test_template_cannot_be_results():
    p=Path(__file__).parents[1]/'registration_template.json'
    value=load(p)
    with pytest.raises(ValueError):load(p,results=True)
    value['dry_run']=False;value['plan_source']='model'
    errors=validate(value)
    assert 'token_cap' in errors and 'quality_floor:throughput' in errors


def test_collect_registration_failures():
    assert len(validate({}))>=10


def test_replay_exact_and_mismatch():
    class Env:
        t=702
        trace=[]
        def advance_plan(self,t):self.t=t
        def commit_plan(self,p):self.trace.append({'seq':9,'kind':'dispatch','time':self.t,'plan':p})
    commits=[{'time':800,'plan':{'version':'sealed'}}]
    trace=[{'seq':22,'kind':'dispatch','time':800,'plan':{'version':'sealed'}}]
    e=Env();e.trace=[]
    assert equivalence(e,commits,trace)['valid']
    e=Env();e.trace=[]
    assert not equivalence(e,commits,[])['valid']


def test_independent_ledger_trace_audit():
    f=SyntheticFactory();metrics=f.ledger().metrics()
    events=[{'kind':'ledger_snapshot','time':0,'problem':f.problem(),'plan':f.plan,'receipts':{},'metrics':metrics},{'kind':'time_advance','time':0,'to':60}]
    result=audit_opportunity_coverage(events)
    assert result['valid']
    assert result['integrals']['avoidable_idle']==metrics['avoidable_idle']*60
    events[0]['metrics']['avoidable_idle']=999
    assert not audit_opportunity_coverage(events)['valid']
    assert not audit_opportunity_coverage(events[1:])['valid']

def test_reservation_audit_matches_independent_fixture():
    from harness_v6.audit_v6 import audit_reservations
    from harness_v6.ledger import ledger_from_scratch
    problem={'time':100,'machines':[{'machine':1,'available_at':200,'currently_busy':True},{'machine':2}],
             'operations':[{'operation_id':'a','lot_id':'a','step':1,'visit':1,'eligible_machines':[1,2],'batch_key':['a'],'batch_min':1,'batch_max':1}]}
    plan={'created_at':80,'tasks':[{'id':'t','machine':1,'operation_ids':['a'],'not_before':120}], 'holds':[]}
    actual=audit_reservations(problem,plan);expected=ledger_from_scratch(problem,plan).metrics()
    assert actual=={k:expected[k] for k in actual}
    assert actual['reserved_but_earlier_startable'][0]['potential_idle_seconds']==100


def test_original_replay_has_no_v6_ledger_or_interrupts():
    from harness_v6.env_adapter import FullFabEnvironment
    env=object.__new__(FullFabEnvironment)
    env.t=0;env.horizon=10;env.plan=None;env.q=[];env.finished=False
    events=[]
    env._outside=lambda:None
    env._run_planned_now=lambda:False
    env._gaps=lambda:[]
    env._emit=lambda kind,**fields:events.append(kind)
    env._events_to=lambda t:setattr(env,'t',t)
    def forbidden():raise AssertionError('original replay must not evaluate v6 ledger')
    env.ledger_snapshot=forbidden
    assert env.advance_plan(1)=={'reason':'periodic_replan','time':1}
    assert events==['time_advance']
    env._gaps=lambda:[{'machine':1,'candidate_count':1}]
    assert env.advance_plan(2)['reason']=='uncovered_demand'
    assert env.t==1 and events[-1]=='coverage_gap'
