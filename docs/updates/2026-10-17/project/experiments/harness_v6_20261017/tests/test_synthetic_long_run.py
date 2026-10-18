from harness_v6.synthetic import SyntheticRun, keyed_uniform
from harness_v6.cycle import CycleConfig, DriftRule
from harness_v6.checkpoint import CheckpointStore


def _checkpoint_trajectory(directory):
    # A separate process keeps both complete 1,200-cycle trajectories affordable.
    import tempfile
    tempfile.tempdir = str(directory)
    split = SyntheticRun(seed=73)
    store = CheckpointStore(directory / 'split'); split.checkpoint(store)
    for _ in range(613): split.step()
    split.checkpoint(store); resumed = SyntheticRun.restore(store.latest())
    for _ in range(587): resumed.step()
    return resumed.checkpoint(resumed.store)


def test_1200_cycles_checkpoint_and_bounded_snapshot(live_dir):
    from concurrent.futures import ProcessPoolExecutor
    uninterrupted = SyntheticRun(seed=73)
    with ProcessPoolExecutor(max_workers=1) as worker:
        future = worker.submit(_checkpoint_trajectory, live_dir)
        for _ in range(1200): uninterrupted.step()
        resumed = SyntheticRun.restore(future.result())
    assert uninterrupted.state_hash()==resumed.state_hash()
    assert resumed.cycle.cycles==1200 and resumed.cycle.stop_reason is None
    assert resumed.factory.completed>1000
    assert resumed.max_snapshot_bytes<12000
    assert resumed.max_snapshot_bytes-resumed.min_snapshot_bytes<3000
    assert len(resumed.factory.lots)==4 and len(resumed.factory.plan['tasks'])<=4
    assert resumed.cycle.sessions==sum(r.get('sessions',0) for r in resumed.metrics.report().values())


def test_budget_boundary():
    run=SyntheticRun(config=CycleConfig(segment_cycles=7,cost_cap=150))
    for _ in range(20):
        run.step()
        if run.cycle.stop_reason:break
    assert run.cycle.stop_reason=='budget_cap'
    assert run.cycle.cycles==7 and run.cycle.last_record['segment_boundary']


def test_drift_injection():
    run=SyntheticRun(drift_rule=DriftRule({'input_per_request':100},2))
    for i in range(250):
        run.step(injected_usage=100 if i<60 else 1000)
        if run.cycle.stop_reason:break
    assert run.cycle.stop_reason=='drift' and run.last_hour==2
    assert run.metrics.report()[0]['input_per_request']==100/3


def test_breakdown():
    run=SyntheticRun(config=CycleConfig(breakdowns=True));run.step()
    assert run.factory.breakdown(1,30,enabled=False) is None and not run.factory.invalid
    event=run.factory.breakdown(1,30,enabled=run.cycle.config.breakdowns)
    assert event=='plan_invalidated' and run.factory.invalid
    row=run.step(event=event)
    assert row['event']=='plan_invalidated' and not run.factory.invalid
    run.step();assert run.cycle.failures==0


def test_hold_batch_route_randomness():
    run=SyntheticRun();run.step();f=run.factory
    f.plan['holds']=[{'machine':1,'until':25,'reason':'test hold'}]
    f.advance(24,run.metrics);assert not f.running and not f.dispatched
    f.advance(26,run.metrics);assert len(f.running)==1 and len(f.running[0]['task']['lot_ids'])==2
    f.advance(120,run.metrics);assert any(lot['step']==2 for lot in f.lots.values())
    assert keyed_uniform(1,['x'])==keyed_uniform(1,['x'])!=keyed_uniform(2,['x'])
