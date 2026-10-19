"""Offline provider-shape failures and lossless optional-field semantics."""
from copy import deepcopy
from itertools import combinations
import json
import pytest
from harness_v6.structured_schema import strict_projection, validate_strict_schema
from harness_v6.delta_schema import TASK, HOLD, DELTA_SCHEMA
from harness_v6.single_action import OUTPUT_SCHEMA, write_schema
from harness_v6.mcp_server import TOOLS
from test_ab_comprehension import ab, states


def box(value):
    return ab.object_schema({'value': value})


@pytest.mark.parametrize('bad', [
    {'type': ['null', 'boolean', 'number', 'string', 'array', 'object']},
    {'type': 'array'}, {},
    {'type': 'object', 'properties': {'x': {'type':'string'}}, 'required': [], 'additionalProperties': False},
    {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': True},
    {'type': 'array', 'items': {'type':'string'}, 'uniqueItems': True},
    {'type':'string', 'minLength':1},
    {'allOf':[{'type':'string'}]},
])
def test_reject_provider_incompatible_shapes(bad):
    with pytest.raises(ValueError): validate_strict_schema(box(bad))


def test_old_production_schema_fails_before_any_transport():
    old = deepcopy(TOOLS['submit_plan'])
    old['properties']['delta'] = DELTA_SCHEMA
    with pytest.raises(ValueError): validate_strict_schema(old)
    assert validate_strict_schema(OUTPUT_SCHEMA)['max_depth'] <= 10


@pytest.mark.parametrize('original,values', [
    (TASK, dict(id='task', operation_ids=['operation'], start_mode='not_before', not_before=7, latest_start=9)),
    (HOLD, dict(machine=1, until=9, reason='maintenance', after_task_id='task')),
])
def test_optional_omission_is_preserved_exactly(original, values):
    projected = strict_projection(original)
    validate_strict_schema(box(projected))
    optional = [k for k in values if k not in original['required']]
    expected_sets = set()
    for n in range(len(optional)+1):
        for chosen in combinations(optional, n):
            value = {k: v for k,v in values.items() if k in original['required'] or k in chosen}
            expected_sets.add(frozenset(value))
            assert ab.schema_matches(value, projected)
            assert not ab.schema_matches(dict(value, injected=1), projected)
            for required in original['required']:
                missing = dict(value); missing.pop(required)
                assert not ab.schema_matches(missing, projected)
    assert {frozenset(b['properties']) for b in projected['anyOf']} == expected_sets
    if original is TASK:
        assert not ab.schema_matches(dict(values, not_before=None), projected)
        assert not ab.schema_matches(dict(values, latest_start=None), projected)
    else:
        assert ab.schema_matches(dict(values, after_task_id=None), projected)


def test_whole_kit_preflight_before_runner_construction(tmp_path, monkeypatch):
    kit=tmp_path/'kit'; _, _, plan=ab.generate(states(), kit, per_type=2)
    for row in plan:
        validate_strict_schema(json.loads((kit/row['output_schema']).read_text()))
    # Deliberately corrupt the LAST schema: no earlier paid request may start.
    (kit/plan[-1]['output_schema']).write_text(json.dumps(box({'type':'array'})))
    import harness_v6.codex_runner as module
    def forbidden(*a, **kw): raise AssertionError('runner must not be constructed')
    monkeypatch.setattr(module, 'CodexRunner', forbidden)
    with pytest.raises(ValueError, match='missing items'):
        ab.run(kit, tmp_path/'run', codex_binary='unused', codex_version='unused', model='fake-only',
               context_token_budget=1000000, request_overhead_tokens=100,
               output_reserve_tokens=1000, counter=len)
    assert not (tmp_path/'run').exists()


def test_schema_limits_and_shared_transport(tmp_path):
    assert OUTPUT_SCHEMA == TOOLS['submit_plan'] == TOOLS['validate_plan']
    path=tmp_path/'schema.json'; write_schema(path)
    assert json.loads(path.read_text()) == OUTPUT_SCHEMA
    nested={'type':'string'}
    for _ in range(11): nested=box(nested)
    with pytest.raises(ValueError, match='depth'): validate_strict_schema(nested)
    with pytest.raises(ValueError, match='properties'):
        validate_strict_schema(ab.object_schema({str(i): {'type':'boolean'} for i in range(5001)}))
