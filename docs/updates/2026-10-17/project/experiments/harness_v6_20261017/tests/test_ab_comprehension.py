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
    current = dict(upcoming_operations=[dict(ops[0], operation_id='future', earliest_start=20)], time=10, unreserved_ready=ops, machine_orders=[dict(machine=1, task_ids=['task-a'])],
        running_jobs=[dict(job=12, machine=2)], machines=[dict(machine=i, available_at=10000+i,
        processing_until=[10000+i], current_setup='' if i < 90 else 'A') for i in range(100)])
    return {'synthetic': {fmt: encode_prefix(prefix, fmt) + encode_current(prefix, current, fmt)
                          for fmt in ab.FORMATS}}


def independent_answers(questions, current, prefix):
    result = {}
    for q in questions:
        t = q['target']
        if q['type'] == 'upcoming':
            row = next((r for r in current.get('upcoming_operations', []) if r['operation_id'] == t['operation_id']), None)
            value = dict(present=row is not None, earliest_start=row['earliest_start'] if row else None, eligible_machines=sorted(row['eligible_machines']) if row else [])
        elif q['type'] in ('eligible', 'batch_bounds'):
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
    assert {q['type'] for q in questions} == {'upcoming', 'eligible', 'batch_bounds', 'batch_compatible', 'queue', 'available_time', 'value_semantics', 'route_step'}
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
    public_ledger = os.environ.get('V6_PUBLIC_LEDGER')
    selectors = ['g0', 'public:702', 'public:1182', 'public:1602'] if public_ledger else ['g0', 'public:702', 'public:703']
    real = ab.load_real_states(fixture_path, database, selectors, tiktoken_counter(), public_ledger=public_ledger)
    # Cross-entrypoint invariant: A/B/recording samples carry exactly the static
    # schemas and physics tables used by the live production prefix.
    from harness_v6.factory_v6 import restore
    from harness_v6.snapshot import production_prefix
    from harness_v6.compact import decode_prefix
    import json
    bundle = json.loads(Path(fixture_path).read_bytes())
    seed = bundle['mixed_702']
    env = restore(seed['state'], seed['trace'], data_dir=bundle['data_dir'])
    for fmt in ab.FORMATS:
        expected = production_prefix(routing=env.manifest['routes'], machine_groups=env.manifest['machines'],
            setup_transitions=env.manifest['setups'], min_runs=dict(env.min_runs),
            snapshot_format=fmt, token_counter=tiktoken_counter())
        for snapshots in real.values():
            assert snapshots[fmt].startswith(expected)
            assert decode_snapshot(snapshots[fmt])[0] == decode_prefix(expected)
    output = Path(os.environ.get('V6_AB_OUTPUT', str(tmp_path / 'real')))
    questions, key, plan = ab.generate(real, output, seed=7)
    assert_validity(real, questions, key)
    assert len(real) == len(selectors) and len(plan) == 4 * len(selectors)
    times = set()
    for state, snapshots in real.items():
        prefix, current = decode_snapshot(snapshots['explicit'])
        times.add(current['time'])
        subset = [q for q in questions if q['state'] == state]
        assert {q['id']: key[q['id']] for q in subset} == independent_answers(subset, current, prefix)
    assert len(times) == len(selectors)
    if public_ledger:
        import gzip, json
        from harness_v6.compact import normalize
        seen = set()
        with gzip.open(public_ledger, 'rt') as stream:
            for line in stream:
                source = json.loads(line); now = source['time']
                if now not in (702,1182,1602) or now in seen: continue
                seen.add(now)
                completed = {r['task_id'] for r in source['receipts'].get('tasks',[]) if r['state'] in ('running','done')}
                reserved = {oid for t in source['plan']['tasks'] if t['id'] not in completed for oid in t['operation_ids']}
                from harness_v6.physical_window import frozen_operations
                from harness_v6.factory_v6 import restore
                from harness_v6.ledger import ready
                bundle=json.loads(Path(fixture_path).read_bytes())
                seed=bundle['mixed_702']
                manifest=restore(seed['state'],seed['trace'],data_dir=bundle['data_dir']).manifest
                problem=frozen_operations(source['problem'],manifest)
                expected=[]
                for op in problem['operations']:
                    if not ready(op,now) and op['earliest_start']<=now+900 and op['operation_id'] not in reserved:
                        expected.append({k:op.get(k) for k in ('operation_id','earliest_start','nominal_start',
                            'batch_key','batch_min','batch_max','setup','eligible_machines','priority',
                            'processing_seconds_min','processing_seconds_max','readiness_basis','predecessor_ids',
                            'sampling_percent','conditional')})
                expected.sort(key=lambda r:r['operation_id'])
                for fmt in ab.FORMATS:
                    assert decode_snapshot(real['public:'+str(int(now))][fmt])[1]['upcoming_operations']==normalize(expected)
                if len(seen)==3: break
        assert seen == {702,1182,1602}

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
    value_schema = ab.SCHEMAS['value_semantics']['properties']['value']
    assert value_schema == ab.CONTRACT_VALUE
    for value in (None, True, 0, '', [], [1, 2.5], {'type':'constant','c':2},
                  {'type':'uniform','m':3,'offset':1}, {'type':'exponential','mean':4}):
        assert ab.schema_matches(value, value_schema)
    assert not ab.schema_matches({'unknown_distribution': 1}, value_schema)
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
