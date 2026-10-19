from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from harness_v6.contracts import encode, digest, strict_json
from harness_v6.facts import build_facts
from harness_v6.synthetic import SyntheticFactory, scripted_delta, SOURCE
from harness_v6.mcp_server import CycleServer
from harness_v6.evidence import audit_chain, audit_provenance
from harness_v6.session import RunResult, Budget, classify, command, finish, run_session
from harness_v6.metrics import Metrics
from harness_v6.store_v6 import Store, compare_and_commit


def test_native_forbidden_tool_is_a_failed_session():
    raw=json.dumps({'type':'error','message':'Fatal error: HARNESS_FORBIDDEN_TOOL: unsupported call: apply_patch'})
    parsed=classify(raw,interaction='single_action')
    assert 'forbidden_item:unadvertised_tool' in parsed['errors']
    assert 'failed_event:error' in parsed['errors']
    assert 'missing_turn_completed' in parsed['errors']
    assert parsed['usage'] is None and parsed['calls']==[]


def setup_cycle(tmp_path, f=None, version=0):
    f=f or SyntheticFactory()
    inp=tmp_path/'input';inp.mkdir(parents=True)
    payload={'snapshot':{'all_tasks':f.plan['tasks']},'context_ref':str(version),
             'facts':build_facts(f.problem(),f.plan),'execution_state':f.execution_state(),
             'submit_config':{'state_version':version,'next_anchor':f.now+60,'source_sha256':SOURCE}}
    (inp/'cycle.json').write_bytes(encode(payload))
    return CycleServer(inp,tmp_path/'output'),f


def jsonl(rows, usage=True):
    events=[{'type':'item.completed','item':{'type':'mcp_tool_call','id':str(i),'server':'harness_v6','tool':r['tool'],'arguments':r['arguments'],'status':'completed'}} for i,r in enumerate(rows)]
    if usage: events.append({'type':'turn.completed','usage':{'input_tokens':100,'cached_input_tokens':20,'output_tokens':10}})
    return '\n'.join(json.dumps(e) for e in events)


def artifacts(server):
    p=server.output_dir/'submission.json'
    return {'rows':server.records,'submission':strict_json(p.read_bytes()) if p.exists() else None}


def test_three_cycles_fake_runner(tmp_path):
    f=SyntheticFactory();metrics=Metrics()
    store=Store(tmp_path/'store',root=tmp_path,create=True)
    try:
        for n in range(3):
            s,f=setup_cycle(tmp_path/str(n),f,n);initial=s.submitter.capture()
            class FakeRunner:
                def run(self, argv, prompt, *, timeout):
                    args={'expected_state_version':n,'submission_id':str(n),'delta':scripted_delta(f,n+1)}
                    assert s.call('validate_plan',args)['accepted']
                    assert not (s.output_dir/'submission.json').exists()
                    assert s.call('submit_plan',args)['accepted']
                    return RunResult(jsonl(s.records),wall_seconds=1)
            outcome=run_session(FakeRunner(),['NEVER_EXECUTED'],'scripted',initial_state=initial,commit=lambda v,p: compare_and_commit(store,v,p),metrics=metrics,now=f.now,artifacts=lambda:artifacts(s))
            assert outcome['adopted'] and not audit_chain(s.records)
            f.adopt(store.read('plans',str(n+1)));f.advance(f.now+60,metrics);s.close()
        assert store.meta('state_version')==3
        assert store.verify()['events']==3
    finally: store.close()


def test_stdio_roundtrip(tmp_path):
    s,f=setup_cycle(tmp_path);s.close()
    requests=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05'}},{'jsonrpc':'2.0','method':'notifications/initialized'}, {'jsonrpc':'2.0','id':2,'method':'tools/list'}, {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'read_entities','arguments':{'kind':'operations','ids':[]}}}]
    env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src')}
    p=subprocess.run([sys.executable,'-m','harness_v6.mcp_server','--input',str(s.input_dir),'--output',str(tmp_path/'stdio')],input='\n'.join(json.dumps(r) for r in requests)+'\n',text=True,capture_output=True,env=env,timeout=10)
    assert p.returncode==0,p.stderr
    replies=[json.loads(x) for x in p.stdout.splitlines()]
    assert [r['id'] for r in replies]==[1,2,3]
    assert len(replies[1]['result']['tools'])==3
    assert not replies[2]['result']['isError']
    from harness_v6.tool_codec import unpack
    wire = strict_json(replies[2]['result']['content'][0]['text'])
    raw_rows = [json.loads(x) for x in (tmp_path/'stdio/mcp.jsonl').read_text().splitlines()]
    assert encode(unpack(wire)) == encode(raw_rows[-1]['result'])
    assert not audit_chain([json.loads(x) for x in (tmp_path/'stdio/mcp.jsonl').read_text().splitlines()])


def test_rpc_read_validate_submit_codec_matches_raw_audit(tmp_path):
    from harness_v6.tool_codec import unpack
    server, factory = setup_cycle(tmp_path)
    args = {'expected_state_version': 0, 'submission_id': 'codec-test', 'delta': scripted_delta(factory, 1)}
    calls = [('read_entities', {'kind': 'operations', 'ids': ['absent-id']}),
             ('validate_plan', args), ('submit_plan', args)]
    try:
        for i, (name, arguments) in enumerate(calls):
            response = server.rpc({'jsonrpc':'2.0', 'id':i, 'method':'tools/call',
                'params':{'name':name, 'arguments':arguments}})
            wire = strict_json(response['result']['content'][0]['text'])
            assert encode(unpack(wire)) == encode(server.records[-1]['result'])
        assert server.records[-1]['result']['accepted']
        assert not audit_chain(server.records)
    finally:
        server.close()


def test_serialized_idempotent_submit_and_readonly(tmp_path):
    s,f=setup_cycle(tmp_path);original=(s.input_dir/'cycle.json').read_bytes()
    args={'expected_state_version':0,'submission_id':'same','delta':scripted_delta(f,1)}
    with ThreadPoolExecutor(4) as pool: results=list(pool.map(lambda _:s.call('submit_plan',args),range(8)))
    assert all(r==results[0] and r['accepted'] for r in results)
    assert not audit_chain(s.records)
    assert (s.input_dir/'cycle.json').read_bytes()==original
    args['submission_id']='different';assert not s.call('submit_plan',args)['accepted']
    assert not s.call('read_entities',{'kind':'machines','ids':[1]})['entities']==[]
    s.close()


@pytest.mark.parametrize('failure',['crash','timeout','usage','native','unknown','compaction','tokens','wall','tools','stale','missing_jsonl','hash','production','no_submit'])
def test_fail_closed_retains_plan(tmp_path,failure):
    s,f=setup_cycle(tmp_path);initial=s.submitter.capture()
    if failure!='no_submit': s.call('submit_plan',{'expected_state_version':0,'submission_id':'a','delta':scripted_delta(f,1)})
    a=artifacts(s);result=RunResult(jsonl(s.records),wall_seconds=1);budget=Budget();commits=[]
    if failure=='crash':result.returncode=1
    if failure=='timeout':result.timed_out=True
    if failure=='usage':result.jsonl=jsonl(s.records,False)
    if failure=='native':result.jsonl+='\n'+json.dumps({'type':'item.completed','item':{'type':'command_execution'}})
    if failure=='unknown':result.jsonl+='\n'+json.dumps({'type':'future_event'})
    if failure=='compaction':result.jsonl+='\n'+json.dumps({'type':'thread.compacted'})
    if failure=='tokens':budget=Budget(token_cap=10)
    if failure=='wall':result.wall_seconds=301
    if failure=='tools':
        s.call('read_entities',{'kind':'operations','ids':[]});result.jsonl=jsonl(s.records);budget=Budget(max_tool_calls=1)
    if failure=='missing_jsonl':result.jsonl=jsonl([])
    if failure=='hash':a['rows'][0]['arguments']['submission_id']='forged'
    if failure=='production':a['submission']['plan']['tasks'][0]['machine']=999
    def commit(v,p):
        if failure=='stale':return False
        commits.append(p);return True
    outcome=finish(result,**a,initial_state=initial,commit=commit,metrics=Metrics(),now=0,budget=budget)
    assert not outcome['adopted'] and outcome['errors']
    assert not commits
    s.close()


@pytest.mark.parametrize('typ',['file_change','web_search','error','custom_tool_call','compaction'])
def test_native_types_rejected(typ):
    assert classify(json.dumps({'type':'item.completed','item':{'type':typ}}))['errors']


def test_command_is_only_built(tmp_path):
    argv=command(tmp_path,tmp_path/'out',model='UNUSED',budget=Budget(token_cap=1000),env={'PYTHONPATH':'/isolated/src'})
    assert '--ephemeral' in argv and '--json' in argv
    assert 'approval_policy="never"' in argv
    assert 'mcp_servers.harness_v6.command='+json.dumps(sys.executable) in argv
    assert 'model_auto_compact_token_limit=1001' in argv
    assert '--output-schema' not in argv
    assert 'features.shell_snapshot=false' in argv
    assert 'mcp_servers.harness_v6.enabled_tools='+json.dumps(list(__import__('harness_v6.mcp_server',fromlist=['TOOLS']).TOOLS)) in argv
    approvals=[x for x in argv if x.startswith('mcp_servers.harness_v6.tools.')]
    assert len(approvals)==3 and all(x.endswith('.approval_mode="approve"') for x in approvals)


def test_store_root_and_atomic_cas(tmp_path):
    with pytest.raises(ValueError):Store(tmp_path/'escape',create=True)
    s=Store(tmp_path/'store',root=tmp_path,create=True)
    try:
        assert compare_and_commit(s,0,{'tasks':[]})
        assert not compare_and_commit(s,0,{'tasks':['forged']})
        assert s.read('plans','1')=={'tasks':[]}
    finally:s.close()

def test_incomplete_mcp_item_and_post_completion_rejected():
    started={'type':'item.started','item':{'type':'mcp_tool_call','server':'harness_v6','tool':'read_entities','id':'unfinished'}}
    assert 'incomplete_mcp_items' in classify(json.dumps(started)+'\n'+jsonl([]))['errors']
    assert 'event_after_completion' in classify(jsonl([])+'\n'+json.dumps({'type':'turn.started'}))['errors']


def test_wal_precedes_runner_and_clear_follows_persistence(tmp_path):
    s,f=setup_cycle(tmp_path);initial=s.submitter.capture();order=[]
    class Checkpoint:
        def mark_inflight(self,bundle):order.append('wal')
        def clear_inflight(self):order.append('clear')
    class Fake:
        def run(self,*args,**kwargs):
            order.append('run')
            raise TimeoutError()
    out=run_session(Fake(),[], '',checkpoint=Checkpoint(),inflight_bundle={},persist_completed=lambda result:order.append('persist'),initial_state=initial,commit=lambda *args:False,metrics=Metrics(),now=0,artifacts=lambda:artifacts(s))
    assert order==['wal','run','persist','clear']
    assert not out['adopted'] and out['usage_unknown']
    s.close()
