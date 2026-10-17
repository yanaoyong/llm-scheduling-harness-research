from copy import deepcopy
import pytest
from harness_v6.normalize import normalize_plan, validate_plan, active_holds
from harness_v6.plan_delta import DeltaError, validate_plan_delta
from harness_v6.executor import decide_start
from harness_v6.prompt_rules import V6_RULES
import test_plan_delta as inherited
from test_plan_delta import task, operation, SOURCE

@pytest.fixture
def case():
    c=inherited.PlanDeltaTests();c.setUp();return c

def test_frozen_invalid_cancel_keeps_surviving_prefix(case):
    case.base['freeze_until']=20;case.delta['plan_header']['freeze_until']=20
    case.state['invalidated_task_ids']=['z']
    case.delta['tasks']['keep']['ids']=['z'];case.delta['tasks']['cancel_ids']=['z'];case.bind()
    result=case.compile()
    assert [t['id'] for t in result['plan']['tasks']]==['c','a']
    assert result['evidence']['preserved_frozen_prefixes'][0]['task_ids']==['a']
    case.state.pop('invalidated_task_ids');case.bind()
    with pytest.raises(DeltaError,match='frozen_task'):case.compile()

def test_invalid_frozen_cannot_rewrite(case):
    case.base['freeze_until']=20;case.delta['plan_header']['freeze_until']=20
    case.state['invalidated_task_ids']=['z'];case.delta['tasks']['keep']['ids']=['z']
    replacement=deepcopy(case.base['tasks'][1]);replacement['not_before']=13
    case.delta['tasks']['replace']=[replacement];case.bind()
    with pytest.raises(DeltaError,match='frozen_task'):case.compile()

def test_invalid_receipts_are_host_bound(case):
    case.state['invalidated_task_ids']=['alien'];case.bind()
    with pytest.raises(DeltaError,match='base_state'):case.compile()

@pytest.mark.parametrize('mode',[None,'when_ready','not_before'])
def test_optional_lower_bound_and_implicit_mode_preserve_bytes(case,mode):
    for t in case.base['tasks']:
        t.pop('not_before')
        if mode is not None:t['start_mode']=mode
    case.bind();result=case.compile()
    assert result['plan']['tasks']==case.base['tasks'][1:]
    assert normalize_plan(normalize_plan(result['plan']))==result['plan']

@pytest.mark.parametrize('mode',['predict',None,1,True,{},[]])
def test_invalid_start_mode(case,mode):
    case.base['tasks'][1]['start_mode']=mode;case.bind()
    with pytest.raises(DeltaError,match='start_mode'):case.compile()

def test_all_independent_violations_and_idempotence(case):
    case.base['tasks'][1].update(start_mode='wrong',not_before=120)
    case.base['tasks'][2]['lot_ids']=['wrong-lot']
    case.base['holds'][1]['until']=120;case.bind()
    before=deepcopy((case.base,case.problem,case.state,case.delta))
    errors=validate_plan_delta(*before,source_sha256=SOURCE)
    assert [e['code'] for e in errors]==['start_mode','start','task_identity','hold']
    assert validate_plan_delta(*before,source_sha256=SOURCE)==errors
    assert (case.base,case.problem,case.state,case.delta)==before
    with pytest.raises(DeltaError) as caught:case.compile()
    assert caught.value.violations==errors

def test_expired_hold_anchor_can_leave_plan(case):
    case.base['holds'][0]['until']=10
    case.delta['tasks']['keep']['ids']=['a'];case.delta['tasks']['cancel_ids']=['a'];case.bind()
    assert case.compile()['plan']['holds'][0]==case.base['holds'][0]

def test_frozen_without_bound_stays_exact(case):
    case.base['tasks'][1].pop('not_before');case.base['freeze_until']=15
    case.delta['plan_header']['freeze_until']=15;case.bind()
    assert case.compile()['plan']['tasks'][0]==case.base['tasks'][1]
    case.delta['tasks']['keep']['ids']=['z'];case.delta['tasks']['cancel_ids']=['z']
    with pytest.raises(DeltaError,match='frozen_task'):case.compile()

@pytest.fixture
def execution():
    return ([task('z'),task('a')],{'machine':1,'ready':10,'down_until':0},
            {'op-'+tid:{**operation(tid),'ready':True} for tid in ('z','a')})

def test_executor_order_detachment_and_idempotence(execution):
    before=deepcopy(execution);r=decide_start(*execution,now=20)
    assert r=={'reason':'start','task':execution[0][0]}
    assert decide_start(*execution,now=20)==r
    r['task']['lot_ids'].append('tamper');assert execution==before

@pytest.mark.parametrize('mode',[None,'when_ready','not_before'])
@pytest.mark.parametrize('bound',[None,4,20,21])
def test_executor_mode_lower_bound(execution,mode,bound):
    t=execution[0][0];t.pop('not_before')
    if mode is not None:t['start_mode']=mode
    if bound is not None:t['not_before']=bound
    assert decide_start(*execution,now=20)['reason']==('not_before' if bound==21 else 'start')

@pytest.mark.parametrize('field,value,reason',[
    ('ready',21,'machine_unavailable'),('down_until',21,'machine_unavailable'),
    ('available',False,'machine_unavailable'),('legal',False,'plan_invalidated'),
    ('invalidated_task_ids',['a'],'plan_invalidated')])
def test_machine_constraints(execution,field,value,reason):
    execution[1][field]=value
    assert decide_start(*execution,now=20)['reason']==reason

def test_never_bypass_unready_head(execution):
    execution[2]['op-z']['ready']=False
    assert decide_start(*execution,now=20)=={'task':None,'reason':'material_unready'}
    execution[2].pop('op-z')
    assert decide_start(*execution,now=20)['task'] is None

@pytest.mark.parametrize('field,value',[('visit',2),('step',2),('lot_id','other'),('eligible_machines',[2])])
def test_route_and_qualification(execution,field,value):
    execution[2]['op-z'][field]=value
    assert decide_start(*execution,now=20)['reason']=='plan_invalidated'

@pytest.mark.parametrize('count,minimum,maximum,expected',[(1,2,3,'invalid_batch'),(2,1,1,'invalid_batch'),(2,2,2,'start')])
def test_batch_bounds(execution,count,minimum,maximum,expected):
    queue,machine,rows=execution
    if count==2:
        for k in ('operation_ids','lot_ids','steps','visits'):queue[0][k]+=queue[1][k]
        queue.pop()
    for row in rows.values():row.update(batch_min=minimum,batch_max=maximum)
    assert decide_start(*execution,now=20)['reason']==expected

def test_incompatible_batch(execution):
    for k in ('operation_ids','lot_ids','steps','visits'):execution[0][0][k]+=execution[0][1][k]
    for r in execution[2].values():r['batch_max']=2
    execution[2]['op-a']['batch_key']=['other',1,'recipe']
    assert decide_start(*execution,now=20)['reason']=='invalid_batch'

@pytest.mark.parametrize('until,anchor,queue_empty,dispatched,expected',[
    (21,None,False,[],'hold'),(20,None,False,[],'start'),(19,None,False,[],'start'),
    (21,'done',False,['done'],'start'),(21,'done',True,['done'],'hold'),
    (21,'done',True,[],'empty_queue'),(21,'z',False,[],'start')])
def test_hold_semantics(execution,until,anchor,queue_empty,dispatched,expected):
    queue,machine,rows=execution
    if queue_empty:queue.clear()
    holds=[{'machine':1,'until':until,'after_task_id':anchor}]
    assert decide_start(*execution,now=20,holds=holds,dispatched_task_ids=dispatched)['reason']==expected

@pytest.mark.parametrize('latest,reason',[(19,'expired_task'),(20,'start'),(21,'start')])
def test_latest_start(execution,latest,reason):
    execution[0][0]['latest_start']=latest
    assert decide_start(*execution,now=20)['reason']==reason

def test_prompt_semantics():
    assert 'not_before is never clamped' not in V6_RULES
    for phrase in ('when_ready','optional hard lower bound','past not_before','Expired holds','queue head','host-invalidated'):
        assert phrase in V6_RULES


def test_header_and_task_violations_together(case):
    case.delta['plan_header']['valid_until']=101
    case.base['tasks'][1]['start_mode']='wrong';case.bind()
    with pytest.raises(DeltaError) as caught:case.compile()
    assert [e['code'] for e in caught.value.violations]==['header','start_mode']


def test_malformed_task_does_not_hide_other_task_or_hold_failures(case):
    case.base['tasks'][1].pop('steps')
    case.base['tasks'][2]['start_mode']='bad'
    case.base['holds'][1]['reason']='';case.bind()
    with pytest.raises(DeltaError) as caught:case.compile()
    assert [e['code'] for e in caught.value.violations]==['schema','start_mode','hold']


def test_multiple_observed_operation_errors_are_collected(case):
    case.problem['operations'][1]['step']=True
    case.problem['operations'][2]['eligible_machines']=[True]
    case.bind()
    with pytest.raises(DeltaError) as caught:case.compile()
    codes=[e['code'] for e in caught.value.violations]
    assert 'observed_identity' in codes and 'observed_eligibility' in codes


def test_full_plan_validator_no_mutation(case):
    plan=case.compile()['plan'];before=deepcopy(plan)
    assert validate_plan(plan,case.problem,case.state,base_plan=case.base)==[]
    normalized=normalize_plan(plan);normalized['tasks'].clear()
    assert plan==before


def test_empty_queue_other_machine_hold_and_wrong_queue(execution):
    assert decide_start([],execution[1],execution[2],now=20)['reason']=='empty_queue'
    assert decide_start(*execution,now=20,holds=[{'machine':2,'until':30}])['reason']=='start'
    execution[0][0]['machine']=2
    assert decide_start(*execution,now=20)['reason']=='invalid_queue'
