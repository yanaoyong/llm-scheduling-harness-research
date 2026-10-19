import json
import pytest
from test_phase_p import module, SCRIPTS
from test_ab_comprehension import states
from harness_v6.compact import decode_snapshot, encode_current, decode_prefix
from harness_v6.snapshot import production_prefix


def test_export_keeps_full_snapshot_and_production_interaction_footer(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    export = module('prepare_recording_snapshots').export
    samples = {}
    for fmt, old in states()['synthetic'].items():
        static,current=decode_snapshot(old)
        current.update(state_version=1,time=100)
        prefix=production_prefix(routing=static['routing'],machine_groups=static['machine_groups'],
            setup_transitions={},min_runs={},snapshot_format=fmt,token_counter=len)
        samples[fmt]=prefix+encode_current(decode_prefix(prefix),current,snapshot_format=fmt,token_counter=len)
    root=tmp_path/'samples'
    report=export({'synthetic':samples},root,delta=60,delta_min=30,wall_seconds=300,valid_until_maximum=3600,max_tool_calls=3,counter=len)
    assert len(report['samples'])==2
    for row in report['samples']:
        snapshot=(root/row['snapshot']).read_text()
        assert snapshot.encode()==samples[row['format']]
        for mode,prompt_row in row['prompts'].items():
            prompt=(root/prompt_row['path']).read_text()
            validate = module('measure_request_overhead').validate_production_prompt
            validate(snapshot, prompt)
            with pytest.raises(ValueError, match='cycle footer'):
                validate(snapshot, snapshot)
            with pytest.raises(ValueError, match='cycle footer'):
                validate(snapshot, 'changed'+prompt)
            assert prompt.startswith(snapshot+'\nCYCLE_FOOTER\n')
            footer=json.loads(prompt[len(snapshot):].split('\nCYCLE_FOOTER\n')[1])
            expected='event' if mode=='single_action' else 'periodic'
            assert footer['trigger']==expected
            assert footer['valid_until_comparison']==('>' if expected=='event' else '>=')
            assert footer['valid_until_maximum']==3600
            assert footer['max_tool_calls']==(3 if mode=='mcp_session' else 0)
            assert footer['max_model_requests']==footer['max_tool_calls']+1
            for key in ('valid_until_maximum','valid_until_maximum_comparison','max_tool_calls','max_model_requests'):
                incomplete=dict(footer);incomplete.pop(key)
                with pytest.raises(ValueError,match='cycle footer'):
                    validate(snapshot,snapshot+'\nCYCLE_FOOTER\n'+json.dumps(incomplete))
    with pytest.raises(FileExistsError):
        export({'synthetic':samples},root,delta=60,delta_min=30,wall_seconds=300,valid_until_maximum=3600,max_tool_calls=3,counter=len)
