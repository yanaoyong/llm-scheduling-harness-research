import json
from pathlib import Path
import pytest
from harness_v6.synthetic import SyntheticRun
from harness_v6.cycle import CycleConfig
from harness_v6.checkpoint import sha


def test_segments_pruning_one_read_and_chain_tamper(live_dir, monkeypatch):
    run = SyntheticRun(directory=live_dir, config=CycleConfig(segment_cycles=3))
    for _ in range(10):
        run.step()
    store = run.store
    assert len(list(store.directory.glob('checkpoint-*.json'))) == 2
    reads = []
    original = Path.read_bytes
    def read(path):
        if path.name.startswith('checkpoint-'):
            reads.append(path)
        return original(path)
    monkeypatch.setattr(Path, 'read_bytes', read)
    assert store.latest()['cycle']['cycles'] == 9
    assert len(reads) == 1
    chain = store.directory / 'chain.jsonl'
    entries = [json.loads(line) for line in chain.read_text().splitlines()]
    entries[1]['previous_sha256'] = '0' * 64
    chain.write_text(''.join(json.dumps(e)+'\n' for e in entries))
    with pytest.raises(ValueError, match='chain hash'):
        store.latest()


def test_completed_cycles_replayed_and_abandoned(live_dir):
    config = CycleConfig(segment_cycles=3)
    run = SyntheticRun(directory=live_dir/'crash', config=config)
    for _ in range(5):
        run.step()
    checkpoint = run.store.latest()
    assert checkpoint['cycle']['cycles'] == 3
    fresh = SyntheticRun.restore(checkpoint)
    run.recover()
    for _ in range(2):
        run.step(); fresh.step()
    assert run.state_hash() == fresh.state_hash()
    assert (run.directory/'cycle-4.abandoned-1').is_dir()
    assert (run.directory/'cycle-5.abandoned-1').is_dir()


@pytest.mark.parametrize('interaction', ['single_action', 'mcp_session'])
def test_hundred_steps_storage_and_archive(live_dir, monkeypatch, interaction):
    import tarfile
    run = SyntheticRun(directory=live_dir)
    if interaction == 'single_action':
        monkeypatch.setattr(type(run.factory), 'private_state', lambda self: {'reproducible': True})
    # Synthetic private payload is not physics: use single-action for this probe.
    run.cycle.config = CycleConfig(interaction=interaction, segment_cycles=60)
    for _ in range(100):
        run.step()
    assert len(list(run.store.directory.glob('checkpoint-*.json'))) <= 3
    assert not list(live_dir.glob('cycle-*/input/private.json'))
    manifest = json.loads((run.store.directory/'logs-1.json').read_bytes())[0]
    archive = run.store.directory/manifest['file']
    assert sha(archive.read_bytes()) == manifest['sha256']
    with tarfile.open(archive, 'r:gz') as packed:
        names = packed.getnames()
    assert 'cycle-1/initial.json' in names and 'cycle-60/output/evidence.json' in names
    assert not any(name.endswith('private.json') for name in names)
    assert not (live_dir/'cycle-1').exists()


def test_snapshot_counter_separate_from_session_budget(live_dir):
    run = SyntheticRun(directory=live_dir)
    calls = []
    run.token_counter = lambda text: calls.append(text) or 51
    run.snapshot_token_budget = 50
    run.step()
    assert calls and run.cycle.stop_reason == 'snapshot_budget_exceeded'


def test_event_advance_uses_requested_horizon(monkeypatch):
    from harness_v6.synthetic import SyntheticFactory
    from harness_v6.metrics import Metrics
    factory = SyntheticFactory(); factory.metrics = Metrics()
    targets = []
    def advance(target, metrics, **kw):
        targets.append(target); factory.now = target
        if len(targets) == 2:
            factory.invalid = ['task']
    class Idle:
        def metrics(self):
            return {'avoidable_idle': 0}
    monkeypatch.setattr(factory, 'advance', advance)
    monkeypatch.setattr(factory, '_dispatch', lambda metrics: None)
    monkeypatch.setattr(factory, 'ledger', lambda: Idle())
    assert factory.advance_to(125, True) == 'plan_invalidated'
    assert targets == [125, 250]


def test_mcp_log_authoritative_even_with_more_jsonl_calls(live_dir):
    from harness_v6.session import RunResult
    run = SyntheticRun(directory=live_dir)
    original = run.runner.run
    def missing_log(*args, **kwargs):
        result = original(*args, **kwargs)
        (live_dir/'cycle-1/output/mcp.jsonl').write_text('')
        return result
    run.runner.run = missing_log
    run.step()
    row = run.metrics.report()[0]
    assert not run.outcome['adopted']
    assert row['tool_calls'] == 0 and row['model_request_lower_bound'] == 4
