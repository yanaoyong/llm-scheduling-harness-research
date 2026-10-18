import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import pytest
from harness_v6.snapshot import stable_prefix, build_snapshot, canonical, tiktoken_counter
from harness_v6.compact import decode_snapshot
from harness_v6.ledger import ledger_from_scratch
from test_ledger import fixture, op, task

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'ab_comprehension.py'
spec = importlib.util.spec_from_file_location('ab_comprehension', SCRIPT)
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)


def states():
    from harness_v6.compact import encode_prefix, encode_current
    prefix = dict(rules='', tools=[], machine_groups=[], routing={'R': [
        dict(step=i+1, processing={'type': 'constant', 'c': 100+i},
             cadence={'type': 'constant', 'c': 100+i}, batch_min=2, batch_max=4,
             setup='' if i < 90 else 'A', setup_time=None if i < 90 else 15,
             sampling_percent=100 if i < 90 else 50) for i in range(100)]})
    ops = [op(str(i), eligible_machines=[1] if i < 40 else [2]) for i in range(80)]
    for i, row in enumerate(ops):
        row.update(batch_min=2, batch_max=4, release_time=10, batch_key=['A' if i % 2 else 'B'])
    current = dict(time=10, unreserved_ready=ops, machine_orders=[dict(machine=1, task_ids=['task-a'])],
        running_jobs=[dict(job=12, machine=2)], machines=[dict(machine=i, available_at=10000+i,
        processing_until=[10000+i], current_setup='' if i < 90 else 'A') for i in range(100)])
    return {'synthetic': {fmt: encode_prefix(prefix, fmt) + encode_current(prefix, current, fmt)
                          for fmt in ab.FORMATS}}


def independent_answers(questions, current, prefix):
    result = {}
    for q in questions:
        t = q['target']
        if q['type'] in ('eligible', 'batch_bounds'):
            row = next(r for r in current['unreserved_ready'] if r['operation_id'] == t['operation_id'])
            value = sorted(row['eligible_machines']) if q['type'] == 'eligible' else {'batch_min': row['batch_min'], 'batch_max': row['batch_max']}
        elif q['type'] == 'batch_compatible':
            rows = [next(r for r in current['unreserved_ready'] if r['operation_id'] == oid) for oid in t['operation_ids']]
            union = {m for r in rows for m in r['eligible_machines']}
            value = any(all(m in r['eligible_machines'] for r in rows) for m in union)
            value &= all(r['batch_min'] <= len(rows) <= r['batch_max'] for r in rows)
            value &= len({canonical([r['batch_key'], r['batch_min'], r['batch_max']]) for r in rows}) == 1
        elif q['type'] == 'queue':
            pending = [tid for order in current['machine_orders'] if order['machine'] == t['machine'] for tid in order['task_ids']]
            value = dict(pending=pending, head=pending[0] if pending else None,
                         running=sorted(r['job'] for r in current['running_jobs'] if r['machine'] == t['machine']))
        elif q['type'] == 'available_time':
            value = next(r['available_at'] for r in current['machines'] if r['machine'] == t['machine'])
        elif q['type'] == 'route_step':
            step = next(r for r in prefix['routing'][t['route']] if r['step'] == t['step'])
            value = {k: step[k] for k in ('processing', 'cadence', 'batch_min', 'batch_max', 'setup')}
        else:
            if 'route' in t:
                row = next(r for r in prefix['routing'][t['route']] if r['step'] == t['step'])
            elif 'machine' in t:
                row = next(r for r in current['machines'] if r['machine'] == t['machine'])
            else:
                row = next(r for r in current['unreserved_ready'] if r['operation_id'] == t['operation_id'])
            obj = row.get(t['field'])
            kind = ('absent' if t['field'] not in row else 'null' if obj is None else
                    'empty_string' if isinstance(obj, str) and not obj else 'value')
            value = dict(present=t['field'] in row, kind=kind, value=obj)
        result[q['id']] = value
    return result


def test_generation_determinism_keys_and_counterbalance(tmp_path):
    data = states()
    a, b = tmp_path / 'a', tmp_path / 'b'
    questions, key, plan = ab.generate(data, a, seed=42, repetitions=4)
    ab.generate(data, b, seed=42, repetitions=4)
    assert {p.name: p.read_bytes() for p in a.iterdir()} == {p.name: p.read_bytes() for p in b.iterdir()}
    assert b'answer_class' not in (a / 'questions.json').read_bytes()
    assert key == independent_answers(questions, *decode_snapshot(data['synthetic']['explicit'])[::-1])
    assert {q['type'] for q in questions} == {'eligible', 'batch_bounds', 'batch_compatible', 'queue', 'available_time', 'value_semantics', 'route_step'}
    assert [r['format'] for r in plan[:2]] == [r['format'] for r in plan[2:4]][::-1]
    for fmt in ab.FORMATS:
        prompt = (a / f'state-000-{fmt}.txt').read_text()
        assert 'answer_key' not in prompt
        assert prompt.split('QUESTIONS\n')[1] == (a / 'state-000-explicit.txt').read_text().split('QUESTIONS\n')[1]
    with pytest.raises(ValueError, match='even'): ab.generate(data, tmp_path / 'bad', repetitions=3)


def test_score_perfect_corrupt_missing_and_token_usage(tmp_path):
    kit = tmp_path / 'kit'
    questions, key, plan = ab.generate(states(), kit)
    responses = tmp_path / 'responses'
    responses.mkdir()
    for r in plan:
        ab.write_json(responses / (r['request_id'] + '.json'), dict(r, answers=key, usage={'input_tokens': 100, 'output_tokens': 10}))
    result = ab.score(kit / 'questions.json', responses, tmp_path / 'summary.json')
    assert all(v['overall']['accuracy'] == 1 for v in result['summary'].values())
    assert len(result['requests']) == 4
    assert all(r['usage']['input_tokens'] == 100 for r in result['requests'])
    record = dict(plan[0], answers=dict(key))
    record['answers'][questions[0]['id']] = 'corrupted'
    ab.write_json(responses / (record['request_id'] + '.json'), record)
    result = ab.score(kit / 'questions.json', responses, tmp_path / 'corrupt.json')
    group = result['summary'][record['format']]['overall']
    assert group['correct'] == group['total'] - 1
    assert group['accuracy'] == (2 * len(questions) - 1) / (2 * len(questions))
    (responses / (record['request_id'] + '.json')).unlink()
    result = ab.score(kit / 'questions.json', responses, tmp_path / 'missing.json')
    assert result['summary'][record['format']]['overall']['accuracy'] == .5
    assert result['missing_requests'] == [record['request_id']]
    assert '准确率' in (tmp_path / 'summary.md').read_text()


def test_score_unknown_request_and_unavailable_run(tmp_path):
    kit = tmp_path / 'kit'
    ab.generate(states(), kit)
    responses = tmp_path / 'responses'
    responses.mkdir()
    ab.write_json(responses / 'bad.json', {'request_id': 'unknown'})
    with pytest.raises(ValueError, match='unknown or duplicate'):
        ab.score(kit / 'questions.json', responses, tmp_path / 'score.json')
    p = subprocess.run([sys.executable, str(SCRIPT), 'run'], capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=str(SCRIPT.parents[1] / 'src')))
    assert p.returncode == 2 and 'required' in p.stderr


def test_configured_real_generation(tmp_path):
    fixture_path, database = os.environ.get('V6_MAC_FIXTURE'), os.environ.get('V6_SEALED_DB')
    if not fixture_path or not database:
        pytest.skip('Mac-only real snapshots: set V6_MAC_FIXTURE and V6_SEALED_DB plus physics/tokenizer dependencies')
    real = ab.load_real_states(fixture_path, database, ['g0', 'public:702', 'public:703'], tiktoken_counter())
    output = Path(os.environ.get('V6_AB_OUTPUT', str(tmp_path / 'real')))
    questions, key, plan = ab.generate(real, output, seed=7)
    assert_validity(real, questions, key)
    assert len(real) == 3 and len(plan) == 12
    times = set()
    for state, snapshots in real.items():
        prefix, current = decode_snapshot(snapshots['explicit'])
        times.add(current['time'])
        subset = [q for q in questions if q['state'] == state]
        assert {q['id']: key[q['id']] for q in subset} == independent_answers(subset, current, prefix)
    assert len(times) == 3
    assert abs(decode_snapshot(real['g0']['explicit'])[1]['time'] - 1649.82) < .01


def assert_validity(data, questions, key):
    for kind in ab.SCHEMAS:
        schemas = {canonical(q['answer_schema']) for q in questions if q['type'] == kind}
        assert schemas == {canonical(ab.SCHEMAS[kind])}
        # Contract must not encode a sampled answer as a const or singleton enum.
        def check(obj):
            if isinstance(obj, dict):
                assert 'const' not in obj
                if 'enum' in obj:
                    assert len(obj['enum']) > 1
                for value in obj.values(): check(value)
            elif isinstance(obj, list):
                for value in obj: check(value)
        check(ab.SCHEMAS[kind])
    assert ab.SCHEMAS['value_semantics']['properties']['value']['type'] == [
        'null', 'boolean', 'number', 'string', 'array', 'object']
    for state, snapshots in data.items():
        wires = {fmt: ab.wire_tables(snapshots[fmt]) for fmt in ab.FORMATS}
        subset = [q for q in questions if q['state'] == state]
        for q in subset:
            t = q['target']
            assert 'path' not in t
            assert set(t) in ({'operation_id'}, {'operation_ids'}, {'machine'}, {'route', 'step'},
                             {'route', 'step', 'field'}, {'machine', 'field'}, {'operation_id', 'field'})
            for k, value in t.items():
                if k == 'operation_ids':
                    assert len(value) >= 2 and len(set(value)) == len(value)
                    assert all(oid in q['text'] for oid in value)
                else:
                    assert str(value) in q['text']
            if q['type'] == 'value_semantics':
                assert ab.wire_cell(wires['explicit'], t)['cell'] != ab.wire_cell(wires['dense'], t)['cell']
        current = decode_snapshot(snapshots['explicit'])[1]
        by_id = {r['operation_id']: r for r in current['unreserved_ready']}
        for q in subset:
            if q['answer_class'] not in ('same_key_no_common_machine', 'same_machines_different_key'):
                continue
            batch = [by_id[oid] for oid in q['target']['operation_ids']]
            assert all(r['batch_min'] <= len(batch) <= r['batch_max'] for r in batch)
            assert len({(r['batch_min'], r['batch_max']) for r in batch}) == 1
            if q['answer_class'] == 'same_key_no_common_machine':
                assert len({canonical(r['batch_key']) for r in batch}) == 1
                assert not set.intersection(*(set(r['eligible_machines']) for r in batch))
            else:
                assert len({canonical(r['eligible_machines']) for r in batch}) == 1
                assert batch[0]['eligible_machines']
                assert len({canonical(r['batch_key']) for r in batch}) > 1
        batches = [key[q['id']] for q in subset if q['type'] == 'batch_compatible']
        assert abs(batches.count(True) - batches.count(False)) <= 1
        semantics = [q['answer_class'] for q in subset if q['type'] == 'value_semantics']
        assert any(':default:' in x for x in semantics)
        assert any(':non_default:' in x for x in semantics)


def test_schemas_identities_and_representation_conventions(tmp_path):
    data = states()
    questions, key, _ = ab.generate(data, tmp_path, per_type=24)
    assert_validity(data, questions, key)
    counts = ab.coverage(questions)['synthetic']
    assert all(v['count'] == 24 for v in counts.values())
    classes = counts['batch_compatible']['answer_classes']
    assert classes['true'] == 12
    assert classes['same_key_no_common_machine'] > 0
    assert classes['same_machines_different_key'] > 0
    classes = counts['value_semantics']['answer_classes']
    assert any(':alias:' in x for x in classes)
    assert any(':release_omission:' in x for x in classes)
    assert any(':null' in x for x in classes)
    assert any(':empty_string' in x for x in classes)
    assert key == independent_answers(questions, *decode_snapshot(data['synthetic']['explicit'])[::-1])
    with pytest.raises(ValueError, match='per_type'):
        ab.generate(data, tmp_path, per_type=1)
