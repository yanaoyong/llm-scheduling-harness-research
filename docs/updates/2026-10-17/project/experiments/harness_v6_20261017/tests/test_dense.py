from copy import deepcopy
import json
import pytest
from harness_v6.compact import dense_section, sections, dense_cell, dense_uncell, encode_current, encode_prefix, decode_snapshot
from harness_v6.registration import validate


@pytest.mark.parametrize('value', ['=', '', '!', 'null', 'false', 'true', '123', '-0', '1e3', '+3', '.1', 'NaN', 'Infinity', 'U1~2', 'C3', '@x', '$x', 'a\tb', 'a\nb', 'CURRENT', '普通', ' x ', '[1]', '{"a":2}', '"x"'])
def test_adversarial_strings(value):
    assert dense_uncell(dense_cell(value)) == value
    assert sections(dense_section('x', [{'s': value}]))['x'] == [{'s': value}]


def test_defaults_aliases_types_absence_and_savings():
    rows = [dict(cadence={'type':'constant','c':100.0}, processing={'type':'constant','c':100.0},
                 available_at=123456.0+i, processing_until=[123456.0+i], flag=False, text='long repeated text') for i in range(100)]
    rows += [{}, {'flag':None}, {'flag':0}, {'flag':0.0}, {'flag':''}]
    original = deepcopy(rows)
    wire = dense_section('x', rows)
    assert '\t=\t' in wire and 'defaults {' in wire
    assert sections(wire)['x'] == rows and original == rows
    for a,b in zip(rows, sections(wire)['x']):
        for k in a:
            assert type(a[k]) is type(b[k])
    assert 'defaults {}' in dense_section('x', [{'a':1}, {'a':2}])
    assert dense_section('x', rows) == wire


def test_release_time_omission_and_missing_remain_distinct():
    prefix = dict(rules='', tools=[], routing={}, machine_groups=[])
    current = dict(time=10.0, machines=[], running_jobs=[], unreserved_ready=[
        dict(operation_id=str(i), eligible_machines=[], **attrs) for i,attrs in enumerate(
            [{'release_time':10.0}, {'release_time':10}, {}, {'release_time':None}])])
    wire = encode_prefix(prefix, 'dense') + encode_current(prefix, current, 'dense')
    decoded = decode_snapshot(wire)[1]
    assert decoded == current
    assert type(decoded['unreserved_ready'][1]['release_time']) is int
    assert b'$release_time_is_time' in wire


def test_registration_requires_format():
    from pathlib import Path
    registration = json.loads((Path(__file__).parents[1]/'registration_template.json').read_text())
    for value in ('explicit', 'dense'):
        registration['snapshot_format'] = value
        assert 'snapshot_format' not in validate(registration)
    for value in (None, '', 'unknown', 1):
        registration['snapshot_format'] = value
        assert 'snapshot_format' in validate(registration)
    del registration['snapshot_format']
    assert 'snapshot_format' in validate(registration)


@pytest.mark.parametrize('snapshot_format', ['explicit', 'dense'])
def test_live_format_checkpoint_and_prefix_stability(tmp_path, snapshot_format):
    from harness_v6.synthetic import SyntheticRun
    run = SyntheticRun(directory=tmp_path, snapshot_format=snapshot_format)
    prefix = run.prefix
    run.step()
    run.step()
    assert run.prefix == prefix
    checkpoint = run.checkpoint(run.store)
    run.recover()
    assert run.snapshot_format == snapshot_format and run.prefix == prefix
    assert run.capture()['snapshot_format'] == snapshot_format


def test_defaults_respect_counter_and_deterministic_ties():
    rows = [{'x':'aaa'}]*10 + [{'x':'bbb'}]*10
    wire = dense_section('x', rows)
    assert 'defaults {"x":"aaa"}' in wire
    assert 'defaults {}' in dense_section('x', rows, token_counter=lambda _: 1)
