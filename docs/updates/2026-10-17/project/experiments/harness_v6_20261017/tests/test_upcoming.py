"""Approved horizon presentation only; physical and submission rules stay unchanged."""
from copy import deepcopy
import os
import pytest
from harness_v6.ledger import ledger_from_scratch
from harness_v6.snapshot import current_state, build_snapshot, stable_prefix
from harness_v6.compact import decode_snapshot, normalize, sections, CURRENT
from test_ledger import fixture, op as base_op, task


def op(oid, **kw):
    return dict(base_op(oid), **kw)


@pytest.mark.parametrize('fmt', ['explicit', 'dense'])
def test_upcoming_boundaries_reservations_flags_and_encoding(fmt):
    p, plan = fixture(); now = p['time']
    def future(oid, **kw):
        return op(oid, readiness_basis='executing_predecessor', conditional=True,
                  sampling_percent=30, **kw)
    p['operations'] = [future('z', release_time=now+900, eligible_machines=[2,1]),
        future('a', release_time=now+1, qualification_uncertain=True),
        future('late', release_time=now+900.001), future('reserved',release_time=now+10),
        op('exported',readiness_basis='exported_predecessor',predecessor_ids=['a'],release_time=now),
        op('ready',readiness_basis='observed_ready',release_time=now),
        future('past',release_time=now-1)]
    plan['tasks'] = [task('reserved')]
    ledger = ledger_from_scratch(p,plan)
    before=deepcopy((p,plan,ledger.metrics()))
    args=dict(horizon_seconds=900,state_version=1,running_jobs=[],last_cycle_receipt=None,model_notes='')
    current=current_state(ledger,**args)
    assert [r['operation_id'] for r in current['upcoming_operations']]==['a','past','z']
    assert current['upcoming_operations'][0]['qualification_uncertain'] is True
    assert all(r['conditional'] and r['sampling_percent']==30 for r in current['upcoming_operations'])
    prefix=stable_prefix(tool_descriptions=[],routing={},machine_groups=[dict(id=i,family='F') for i in [1,2]],snapshot_format=fmt)
    payload=build_snapshot(prefix,ledger,snapshot_format=fmt,token_budget=10**8,**args)
    assert decode_snapshot(payload)[1]==normalize(current)
    raw=sections(payload.split(CURRENT)[1].decode())
    assert {r['$eligible'][0] for r in raw['upcoming_operations']}=={'family','set'}
    assert (p,plan,ledger.metrics())==before
    args['horizon_seconds']=1
    assert [r['operation_id'] for r in current_state(ledger,**args)['upcoming_operations']]==['a','past']
    del args['horizon_seconds']
    with pytest.raises(TypeError): current_state(ledger,**args)
    for horizon in (0,-1,True,float('inf')):
        with pytest.raises(ValueError): current_state(ledger,horizon_seconds=horizon,**args)


def test_g0_when_ready_upcoming_compiles_and_submits():
    from harness_v6.sealed_contexts import SQLiteContextReader
    from harness_v6.submit import Submitter
    path=os.environ.get('V6_SEALED_DB')
    if not path: pytest.skip('Mac-only G0 sealed fixture absent: set V6_SEALED_DB')
    for entry in SQLiteContextReader(path,'SELECT group_name,payload FROM contexts').contexts():
        c=entry['context']
        if entry['group']!='G0' or abs(c['time']-1649.82)>.01: continue
        p=c['base_plan']; state=c['execution_state']; problem=c['problem']
        known={o['operation_id'] for o in problem['operations']}
        reserved={oid for t in p['tasks'] for oid in t['operation_ids']}
        upcoming=[o for o in problem['operations'] if o.get('readiness_basis')=='executing_predecessor'
            and o['release_time']<=c['time']+900 and o['operation_id'] not in reserved]
        assert len(upcoming)==74
        o=next(o for o in upcoming if o['batch_min']==1); mid=o['eligible_machines'][0]
        # Explicit fixture delta, not production repair: archived base contains a stale task.
        cancel=[t['id'] for t in p['tasks'] if t['id'] not in state['dispatched_task_ids']
                and any(oid not in known for oid in t['operation_ids'])]
        assert cancel==['d43-g']
        delta=dict(plan_header=dict(valid_until=p['valid_until'],freeze_until=c['time'],reason='offline upcoming test'),
            tasks=dict(cancel_ids=cancel,replace=[],add=[dict(id='r-upcoming',operation_ids=[o['operation_id']],start_mode='when_ready')]),
            holds=dict(cancel_ids=[],replace=[],add=[]),machine_orders=[dict(machine=mid,task_ids=[t['id'] for t in p['tasks']
                if t['machine']==mid and t['id'] not in state['dispatched_task_ids'] and t['id'] not in cancel]+['r-upcoming'])])
        from harness_v6.facts import FactReader, build_facts
        from harness_v6.contracts import HarnessError
        reader=FactReader(c['context_ref'],build_facts(problem,p))
        query=dict(kind='operations',cursor=None,count=512,where=[dict(field='readiness_basis',op='eq',value='executing_predecessor')])
        found=[]
        while True:
            page=reader.read(query);found.extend(r['value'] for r in page['entities'])
            if page['next_cursor'] is None: break
            query['cursor']=page['next_cursor']
        assert len(found)==1159
        assert any(r['release_time']>c['time']+900 for r in found)
        with pytest.raises(HarnessError):
            reader.read(dict(kind='operations',cursor=None,count=512,where=[dict(field='release_time',op='gt',value=c['time']+900)]))
        target=Submitter(p,problem,state,state_version=c['state_revision'],next_anchor=c['time']+60,source_sha256='0'*64)
        receipt=target.submit_plan(c['state_revision'],'r',delta)
        assert receipt['accepted'],receipt['violations']
        assert next(t for t in target.candidate['tasks'] if t['id']=='r-upcoming')['operation_ids']==[o['operation_id']]
        return
    pytest.fail('configured G0 absent')
