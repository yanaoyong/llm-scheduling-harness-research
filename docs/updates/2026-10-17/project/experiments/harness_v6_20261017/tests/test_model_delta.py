"""Decision-only protocol, authoritative expansion and shared schema contracts."""
from copy import deepcopy
import pytest
from harness_v6.delta_schema import DELTA_SCHEMA, TASK, HOLD, model_task
from harness_v6.mcp_server import TOOLS, TOOL_DESCRIPTIONS
from harness_v6.single_action import OUTPUT_SCHEMA
from harness_v6.plan_delta import compile_plan_delta, DeltaError
import test_plan_delta as inherited
from test_plan_delta import SOURCE, task


@pytest.fixture
def case():
    c = inherited.PlanDeltaTests(); c.setUp(); return c


def test_projection_expands_to_identical_internal_task(case):
    old = task('new', start=4)
    old.update(start_mode='when_ready', latest_start=90)
    case.delta['tasks']['add'] = [model_task(old)]
    case.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['z', 'a', 'new']}]
    result = case.compile()
    assert result['plan']['tasks'] == case.base['tasks'][1:] + [old]
    assert result['plan']['created_at'] == case.state['time']
    assert result['plan']['scope'] == case.problem['scope']
    assert case.compile() == result
    a = compile_plan_delta(case.base, case.problem, case.state, case.delta,
                           source_sha256=SOURCE, state_version=5, submission_id='a')
    b = compile_plan_delta(case.base, case.problem, case.state, case.delta,
                           source_sha256=SOURCE, state_version=5, submission_id='b')
    assert a['plan']['version'] != b['plan']['version']
    assert {k:v for k,v in a['plan'].items() if k != 'version'} == {k:v for k,v in b['plan'].items() if k != 'version'}


def test_identity_uses_current_observation(case):
    case.delta['tasks']['replace'] = [model_task(case.base['tasks'][1])]
    case.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['z', 'a']}]
    case.problem['operations'][1]['visit'] = 2
    assert case.compile()['plan']['tasks'][0]['visits'] == [2]
    case.delta['tasks']['replace'][0]['operation_ids'] = ['unknown']
    case.reject('unknown_operation')


@pytest.mark.parametrize('field,value', [('machine',1), ('lot_ids',['wrong']), ('steps',[2]), ('visits',[2])])
def test_redundant_task_fields_rejected(case, field, value):
    item = model_task(task('new')); item[field] = value
    case.delta['tasks']['add'] = [item]
    case.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['z','a','new']}]
    case.reject('schema')


def test_retained_move_is_explicit_and_requires_complete_orders(case):
    case.delta['machine_orders'] = [{'machine':2, 'task_ids':['c','z']}]
    case.reject('missing_machine_order')
    case.delta['machine_orders'].append({'machine':1, 'task_ids':['a']})
    result = case.compile()
    moved = next(t for t in result['plan']['tasks'] if t['id']=='z')
    assert moved == dict(case.base['tasks'][1], machine=2)
    assert next(t for t in result['evidence']['task_sources'] if t['id']=='z')['source'] == 'base_move'
    case.delta['machine_orders'][1]['task_ids'].append('z')
    case.reject('machine_order')


def test_cancellation_without_order_preserves_remaining_queue(case):
    case.delta['tasks']['cancel_ids'] = ['z']
    case.base['tasks'].append(task('new', start=20))
    before = deepcopy((case.base, case.delta))
    assert case.compile()['plan']['tasks'] == case.base['tasks'][2:]
    assert (case.base, case.delta) == before
    case.delta['machine_orders'] = [{'machine':1, 'task_ids':[]}]
    case.reject('machine_order')
    case.delta['machine_orders'][0]['task_ids'] = ['a', 'new']
    assert [t['id'] for t in case.compile()['plan']['tasks']] == ['c','a','new']


def test_schema_is_complete_shared_and_closed():
    assert OUTPUT_SCHEMA == TOOLS['submit_plan'] == TOOLS['validate_plan']
    assert OUTPUT_SCHEMA['properties']['delta'] == DELTA_SCHEMA
    assert set(TASK['properties']) == {'id','operation_ids','start_mode','not_before','latest_start'}
    assert set(HOLD['properties']) == {'machine','until','reason','after_task_id'}
    assert all(TOOL_DESCRIPTIONS[n] != n for n in TOOLS)
    def walk(schema):
        if schema.get('type') == 'object':
            assert schema['additionalProperties'] is False
            assert set(schema['required']) <= set(schema['properties'])
            for child in schema['properties'].values(): walk(child)
        if schema.get('type') == 'array': walk(schema['items'])
        for child in schema.get('anyOf', []): walk(child)
    walk(DELTA_SCHEMA)
    fields = DELTA_SCHEMA['anyOf'][1]['properties']
    assert set(fields) == {'plan_header','tasks','holds','machine_orders'}
    assert set(fields['plan_header']['properties']) == {'valid_until','freeze_until','reason'}
    for key in ('tasks','holds'):
        assert set(fields[key]['properties']) == {'cancel_ids','replace','add'}


def test_conditional_hold_and_timing_example_compiles(case):
    case.delta['tasks']['add'] = [dict(id='new',operation_ids=['op-new'],start_mode='when_ready',not_before=4,latest_start=80)]
    case.delta['machine_orders'] = [{'machine':1,'task_ids':['z','a','new']}]
    case.delta['holds']['replace'] = [{'ref':'h:0','hold':dict(machine=1,until=90,reason='tail',after_task_id='new')}]
    assert case.compile()['plan']['holds'][0]['after_task_id'] == 'new'
    case.delta['tasks']['add'][0]['latest_start'] = True
    case.reject('latest_start')


@pytest.mark.parametrize('field', ['schema', 'anchors', 'order_policy'])
def test_host_constants_are_not_model_fields(case, field):
    case.delta[field] = 'forbidden'
    case.reject('schema')


@pytest.mark.parametrize('field', ['version', 'created_at', 'scope'])
def test_header_host_fields_are_not_model_fields(case, field):
    case.delta['plan_header'][field] = 'forbidden'
    case.reject('schema')


def test_no_change_receipt_still_records_host_anchors():
    from harness_v6.synthetic import SyntheticFactory
    from test_cycle_submit import submitter
    from harness_v6.plan_delta import anchor_hashes
    factory = SyntheticFactory(); target = submitter(factory)
    result = target.submit_plan(1, 'no-change', {})
    assert result['evidence']['anchors'] == anchor_hashes(target.base_plan, target.problem, target.execution_state, source_sha256=target.source_sha256)


def test_replacement_without_order_keeps_machine_and_position(case):
    replacement = dict(model_task(case.base['tasks'][1]), latest_start=80)
    case.delta['tasks']['replace'] = [replacement]
    before = deepcopy((case.base, case.delta))
    expected = deepcopy(case.base['tasks'][1:])
    expected[0]['latest_start'] = 80
    assert case.compile()['plan']['tasks'] == expected
    assert (case.base, case.delta) == before
    # A supplied order still cannot omit a replacement on that machine.
    case.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['a']}]
    case.reject('machine_order')


def test_replacement_move_requires_both_full_orders(case):
    case.delta['tasks']['replace'] = [model_task(case.base['tasks'][1])]
    case.delta['machine_orders'] = [{'machine': 2, 'task_ids': ['c', 'z']}]
    case.reject('missing_machine_order')
    case.delta['machine_orders'].append({'machine': 1, 'task_ids': ['a']})
    result = case.compile()['plan']['tasks']
    assert [t['id'] for t in result if t['machine'] == 2] == ['c', 'z']
    assert next(t for t in result if t['id'] == 'z') == dict(case.base['tasks'][1], machine=2)


def test_addition_still_requires_one_listing(case):
    case.delta['tasks']['add'] = [model_task(task('new'))]
    case.reject('missing_machine_order')
    case.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['z', 'a', 'new']}]
    assert case.compile()['plan']['tasks'][-1]['id'] == 'new'
    case.delta['machine_orders'].append({'machine': 2, 'task_ids': ['c', 'new']})
    case.reject('machine_order')


def test_cancel_entire_queue_without_order(case):
    case.delta['tasks']['cancel_ids'] = ['z', 'a']
    case.delta['holds']['cancel_ids'] = ['h:0']
    assert case.compile()['plan']['tasks'] == [case.base['tasks'][2]]
