import json
import pytest
from harness_v6 import session,single_action


def test_command_binds_native_request_count_to_interaction(tmp_path):
    budget=session.Budget(max_tool_calls=3)
    for mode,expected in ((session,4),(single_action,1)):
        argv=mode.command(tmp_path,tmp_path/'output',model='offline-command-only',budget=budget)
        values=[argv[i+1] for i,x in enumerate(argv[:-1]) if x=='-c' and argv[i+1].startswith('harness_max_inference_requests=')]
        assert values==['harness_max_inference_requests='+str(expected)]


@pytest.mark.parametrize('mode',['single_action','mcp_session'])
def test_native_pre_request_guard_keeps_cost_but_never_becomes_success(mode):
    usage=dict(input_tokens=123,cached_input_tokens=23,output_tokens=45)
    raw=json.dumps(dict(type='turn.failed',error=dict(message='Fatal error: Harness inference request limit reached: 4'),usage=usage))
    parsed=session.classify(raw,interaction=mode)
    assert parsed['usage']==usage
    assert 'failed_event:turn.failed' in parsed['errors'] and 'missing_turn_completed' in parsed['errors']
    assert 'usage_unknown' not in parsed['errors']


@pytest.mark.parametrize('message,usage',[
 ('network failed',dict(input_tokens=123,cached_input_tokens=23,output_tokens=45)),
 ('Fatal error: Harness inference request limit reached: unknown',dict(input_tokens=123,cached_input_tokens=23,output_tokens=45)),
 ('Fatal error: Harness inference request limit reached: 4',dict(input_tokens=123,output_tokens=45)),
 ('Fatal error: Harness inference request limit reached: 4',dict(input_tokens=123,cached_input_tokens=124,output_tokens=45)),
 ('Fatal error: Harness inference request limit reached: 4',None)])
def test_other_or_incomplete_failure_usage_remains_unknown(message,usage):
    parsed=session.classify(json.dumps(dict(type='turn.failed',error=dict(message=message),usage=usage)))
    assert parsed['usage'] is None and 'usage_unknown' in parsed['errors']
