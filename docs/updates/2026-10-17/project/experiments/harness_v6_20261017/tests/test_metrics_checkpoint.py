import gzip
import json
import pytest
from harness_v6.metrics import Metrics
from harness_v6.checkpoint import CheckpointStore, sha
from harness_v6.cycle import CycleMachine
from harness_v6.synthetic import SyntheticRun, SyntheticFactory, SOURCE, scripted_delta, ledger_capture
from harness_v6.submit import Submitter


def test_metrics():
    m=Metrics(origin=100,exclude_first_hours=1,cached_input_weight=.25)
    m.integrate(100,7300,avoidable_idle=2,unreserved_ready_ops=3,explicit_wait_idle=1,reserved_but_earlier_startable=4)
    m.session(101,tool_calls=3,tool_rounds=2,input_tokens=100,cached_tokens=40,output_tokens=8,
              model_seconds=5,wall_seconds=7,failed=True,usage_known=False,submit_attempts=2,submit_rejections=1)
    m.production(101,throughput=2,tardiness=5,weight=3,queue_wait=4,setups=1)
    m.execution(101,start_offset=-2,starts=2,machine_changes=1,compared_assignments=4,invalid_tasks=3)
    r=m.report();assert r[0]['avoidable_idle_seconds']==7200 and r[1]['avoidable_idle_seconds']==7200
    assert r[0]['uncached_equivalent_input_tokens_per_sim_hour']==70
    assert r[0]['requests']==3 and r[0]['submit_rejection_rate']==.5
    assert r[0]['weighted_tardiness']==15 and r[0]['machine_change_ratio']==.25
    assert r[0]['mean_start_offset']==-1 and r[0]['unknown_usage']==1
    assert list(m.report(steady_only=True))==[1]
    assert Metrics.restore(json.loads(json.dumps(m.capture()))).report()==r


def test_partial_hour():
    m=Metrics();m.integrate(0,1800,avoidable_idle=1);m.session(0,input_tokens=10)
    assert m.report()[0]['uncached_equivalent_input_tokens_per_sim_hour']==20
    with pytest.raises(ValueError):m.session(0,input_tokens=1,cached_tokens=2)


def test_hash_and_logs(tmp_path):
    store=CheckpointStore(tmp_path);run=SyntheticRun();run.step();run.checkpoint(store)
    assert SyntheticRun.restore(store.latest()).state_hash()==run.state_hash()
    paths={}
    for kind in ('trace','mcp','jsonl'):
        paths[kind]=tmp_path/(kind+'.log');paths[kind].write_bytes(b'{"event":1}\n')
    for row in store.rotate_logs(1,paths):
        data=(tmp_path/row['file']).read_bytes()
        assert sha(data)==row['sha256'] and gzip.decompress(data)==b'{"event":1}\n'
        assert not paths[row['kind']].exists()
    latest=json.loads((tmp_path/'chain.jsonl').read_bytes().splitlines()[-1])
    (tmp_path/latest['file']).write_bytes(b'tampered')
    with pytest.raises(ValueError,match='hash'):store.latest()


def test_crash_recovery_no_adoption_no_replay(tmp_path):
    store=CheckpointStore(tmp_path);f=SyntheticFactory();c=CycleMachine()
    store.save(0,state=f.capture(),cycle=c.capture(),ledger=ledger_capture(f.ledger()),cumulative_costs={})
    c.begin(0,avoidable_idle=1,valid_until=1)
    s=Submitter(f.plan,f.problem(),f.execution_state(),state_version=1,next_anchor=60,source_sha256=SOURCE)
    assert s.submit_plan(1,'pre-crash',scripted_delta(f,1))['accepted']
    store.mark_inflight({'state':f.capture(),'cycle':c.capture(),'submit':s.capture(),
                        'ledger':ledger_capture(f.ledger()),'session_usage':{'cost':17,'wall_seconds':8}})
    recovered=store.recover();assert recovered['state']['plan']==f.plan
    machine=CycleMachine.restore(recovered['cycle'])
    assert machine.failures==1 and machine.unknown_usage==1 and machine.sessions==1
    assert machine.anchor==60 and machine.cost==17 and machine.wall_seconds==8
    assert store.recover()==recovered
    assert machine.begin(60,valid_until=900)['session']


def test_stale_marker(tmp_path):
    store=CheckpointStore(tmp_path);run=SyntheticRun();run.checkpoint(store)
    c=run.cycle;c.begin(0,avoidable_idle=1)
    s=Submitter(run.factory.plan,run.factory.problem(),run.factory.execution_state(),state_version=1,next_anchor=60,source_sha256=SOURCE)
    store.mark_inflight({'cycle':c.capture(),'submit':s.capture()})
    c.finish(submitted=True);run.checkpoint(store)
    assert store.recover()['cycle']['failures']==0


def test_ledger_roundtrip_preserves_order_and_indexes():
    from harness_v6.checkpoint import capture_ledger, restore_ledger
    run=SyntheticRun();run.step();ledger=run.factory.ledger()
    restored=restore_ledger(json.loads(json.dumps(capture_ledger(ledger))))
    assert restored.rows()==ledger.rows()
    assert restored.metrics()==ledger.metrics()
    assert restored.pending_tasks()==ledger.pending_tasks()


def test_recovery_counts_known_partial_usage_and_unknown_session(tmp_path):
    store=CheckpointStore(tmp_path);f=SyntheticFactory();c=CycleMachine();m=Metrics()
    store.save(0,state=f.capture(),cycle=c.capture(),ledger=ledger_capture(f.ledger()),cumulative_costs={})
    c.begin(0,avoidable_idle=1)
    s=Submitter(f.plan,f.problem(),f.execution_state(),state_version=1,next_anchor=60,source_sha256=SOURCE)
    store.mark_inflight({'state':f.capture(),'cycle':c.capture(),'submit':s.capture(),
        'ledger':ledger_capture(f.ledger()),'session_usage':{'cost':10,'input_tokens':10,'wall_seconds':3},
        'extra':{'metrics':m.capture()}})
    payload=store.recover();r=Metrics.restore(payload['extra']['metrics']).report()[0]
    assert r['unknown_usage']==r['failures']==r['sessions']==1
    assert r['input_tokens']==10 and r['wall_seconds']==3
