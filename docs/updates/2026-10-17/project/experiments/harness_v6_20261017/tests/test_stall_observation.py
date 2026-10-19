"""Stall must distinguish cleared demand from genuinely unresolved backlog."""
from copy import deepcopy
import pytest
from harness_v6.cycle import CycleConfig, CycleMachine
from harness_v6.synthetic import SyntheticRun


@pytest.mark.parametrize('trigger', ['event', 'periodic'])
def test_new_demand_cleared_each_time_is_not_stall(trigger):
    cycle = CycleMachine(config=CycleConfig(trigger=trigger, stall_cycles=4))
    for i, before in enumerate((1, 2, 1, 1, 1, 1, 1)):
        cycle.begin(i * 60, avoidable_idle=before, valid_until=900)
        cycle.inflight['avoidable_idle_after'] = 0
        cycle.finish(submitted=True)
        assert cycle.idle_streak == 0 and cycle.stop_reason is None


@pytest.mark.parametrize('trigger', ['event', 'periodic'])
def test_unresolved_positive_idle_still_stops_on_fourth_cycle(trigger):
    cycle = CycleMachine(config=CycleConfig(trigger=trigger, stall_cycles=4))
    for i in range(4):
        cycle.begin(i * 60, avoidable_idle=1, valid_until=900)
        cycle.inflight['avoidable_idle_after'] = 1
        cycle.finish(submitted=True)
        assert cycle.stop_reason == ('stall' if i == 3 else None)


@pytest.mark.parametrize('group', ['E1', 'P2'])
def test_live_adoption_observes_result_without_note_exemption(group, live_dir):
    run = SyntheticRun(group=group, directory=live_dir)
    run.model_note = ''
    # One full two-lot batch: each scripted action reserves all current demand.
    # This is a synthetic unit fixture, not a subset of the sealed experiment.
    run.factory.lots = {k: run.factory.lots[k] for k in ('0', '1')}
    run.checkpoint(run.store)
    for _ in range(8):
        assert run.step()['session']
        assert run.outcome['adopted']
        assert run.cycle.last_record['avoidable_idle_after'] == run.factory.ledger().metrics()['avoidable_idle'] == 0
        assert run.cycle.stop_reason is None


@pytest.mark.parametrize('group', ['E1', 'P2'])
def test_failed_commit_uses_original_observation(group, live_dir, monkeypatch):
    run = SyntheticRun(group=group, directory=live_dir)
    run.model_note = ''
    old = deepcopy(run.factory.plan)
    def reject(self, plan):
        raise ValueError('controlled commit rejection')
    monkeypatch.setattr(type(run.factory), 'adopt', reject)
    run.step()
    assert not run.outcome['adopted'] and run.factory.plan == old
    assert 'avoidable_idle_after' not in run.cycle.last_record
    assert run.cycle.previous_idle == run.cycle.last_record['avoidable_idle']
    assert run.cycle.failures == 1
