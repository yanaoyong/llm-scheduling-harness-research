"""Small synthetic original-file fixtures; no transport/budget execution."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab import B_delta_transport_binding_v3 as b

ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT/'artifacts/smt_fullfab_review_drafts/B_envelope_rejection_v2/fixtures'


def encoded(v):return (json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode()
def toml(v):
    if type(v)is bool:return 'true' if v else 'false'
    if type(v)is dict:return '{'+','.join(k+'='+toml(x) for k,x in v.items())+'}'
    if type(v)is list:return '['+','.join(map(toml,v))+']'
    return json.dumps(v)



def synthetic_guard(run, request, config, result):
    """Hand-authored local consistency evidence; no process ever exists.

    Return an independently assembled result descriptor. The real lifecycle
    reader verifies it during binding; that reader is not used to generate it.
    """
    import hashlib
    import sys
    from src.smt_fullfab import model_process_guard as guard
    def sha(raw):return hashlib.sha256(raw).hexdigest()
    def raw(value):return (json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
    def put(name,value):
        data=raw(value);(directory/name).write_bytes(data);return sha(data)
    directory=run/'process_guard';directory.mkdir(exist_ok=True)
    command=json.loads((run/'command.json').read_bytes())['argv']
    io={'cwd':str(run/'isolated-cwd'),'stdin':str(run/'prompt.txt'),'stdout':str(run/'events.jsonl'),'stderr':str(run/'stderr.log'),
        'inputs':{name:str(run/name) for name in guard.INPUT_FILES},'outputs':{name:str(run/name) for name in guard.OUTPUT_FILES}}
    input_hashes={name:sha(Path(path).read_bytes()) for name,path in io['inputs'].items()}
    output_hashes={name:sha(Path(path).read_bytes()) for name,path in io['outputs'].items()}
    schema=guard.PROTOCOL;pid=234567;cpid=234568;parent=234566;fd=12
    source=sha(Path(guard.__file__).read_bytes());start=100.0
    timed=result.get('timed_out',False);end=start+config['timeout_seconds']+1 if timed else start+1
    spec={'schema':schema,'run_dir':str(run),'argv':command,'io_spec':io,'timeout_seconds':config['timeout_seconds'],
        'call_id':request['call_id'],'request_fingerprint':request['request_fingerprint'],'input_files_sha256':input_hashes,
        'begun_monotonic_seconds':start,'deadline_monotonic_seconds':start+config['timeout_seconds'],
        'term_grace_seconds':guard.TERM_GRACE_SECONDS,'direct_kill_wait_seconds':guard.DIRECT_KILL_WAIT_SECONDS,
        'guard_source_sha256':source}
    hashes={'spec.json':put('spec.json',spec)};common={'schema':schema,'spec_sha256':hashes['spec.json']}
    hashes['launch.json']=put('launch.json',{**common,'guard_argv':[str(Path(sys.executable).resolve()),'-I','-B',
        str(Path(guard.__file__).resolve()),'--guard',str(directory/'spec.json'),str(fd),hashes['spec.json']],
        'owner_read_fd':fd,'writer_inheritable':False,'start_new_session':True,'parent_pid':parent})
    hashes['parent_started.json']=put('parent_started.json',{**common,'guard_pid':pid,'parent_pid':parent})
    hashes['started.json']=put('started.json',{**common,'guard_pid':pid,'guard_pgid':pid,'guard_sid':pid,
        'owner_fd_inheritable':False,'owner_fd':fd,'started_monotonic_seconds':start+0.1})
    hashes['command_started.json']=put('command_started.json',{**common,'command_pid':cpid,'guard_pid':pid,
        'inherited_pgid':pid,'start_new_session':False,'close_fds':True,'started_monotonic_seconds':start+0.2})
    hashes['receipt.json']=put('receipt.json',{**common,'guard_pid':pid,'guard_pgid':pid,'command_pid':cpid,
        'call_id':request['call_id'],'request_fingerprint':request['request_fingerprint'],'command_returncode':result.get('returncode',0),
        'command_peak_rss_bytes':0,'timed_out':timed,'owner_eof':False,'guard_error':None,'launch_error':result.get('launch_error'),
        'stop_reason':'deadline' if timed else 'command_exit','group_term_sent':True,'final_group_signal':9,
        'output_files_sha256':output_hashes,'command_started_monotonic_seconds':start+0.2,
        'command_finished_monotonic_seconds':end,'before_final_kill_monotonic_seconds':end+0.1})
    (directory/'guard_stderr.log').write_bytes(b'');hashes['guard_stderr.log']=sha(b'')
    observed={'schema':schema,'files_sha256':dict(hashes),'guard_pid':pid,'guard_returncode':-9,
        'guard_peak_rss_bytes':0,'wait_completed':True,'observed_monotonic_seconds':end+0.2}
    hashes['parent_observed.json']=put('parent_observed.json',observed)
    return {'schema':schema,'lifecycle_complete':True,'guard_pid':pid,'guard_pgid':pid,'command_pid':cpid,
        'guard_returncode':-9,'command_returncode':result.get('returncode',0),'timed_out':timed,'launch_error':result.get('launch_error'),
        'files_sha256':hashes,'guard_source_sha256':source,'input_files_sha256':input_hashes,'output_files_sha256':output_hashes,
        'io_spec':io,'command_peak_rss_bytes':0,'guard_peak_rss_bytes':0,'parent_wait_wall_seconds':end+0.2-start}


class Fixture:
    def __init__(self,directory):
        self.root=Path(directory).resolve();self.run=self.root/'runs/smt_fullfab_stage2/B_fixture/model_000';self.run.mkdir(parents=True)
        self.ledger=self.root/'ledger.jsonl';self.cid='synthetic-only-call'
        self.config={'model':'gpt-6-astra','reasoning_effort':'medium','timeout_seconds':180,
            'codex_binary':'/synthetic/not-executed/codex','proxy':None,'ledger_path':str(self.ledger),
            'phase':'stage2_research','grant_id':'smt-fullfab-stage2-probe-v1',
            'authorization_context':{'purpose':'B','arm':'B','scenario':1701,'window_seconds':3600}}
        self.context={'interaction_id':'i','session_id':'s','anchors':{'base_plan_sha256':'a'*64,
            'problem_sha256':'b'*64,'state_sha256':'c'*64,'source_sha256':'d'*64},'catalog_sha256':'e'*64}
        body='SYNTHETIC FIXTURE TASK\nINPUT_JSON\n'+json.dumps(self.context)
        self.prompt='PROMPT_BODY_SHA256='+b.sha(body.encode())+'\n'+body
        self.output={'schema':b.envelope_policy.RESPONSE_SCHEMA,**self.context,
            'prompt_body_sha256':b.sha(body.encode()),'memory':'原样 memory','request':{'kind':'read_candidates'}}
        self.schema=json.loads((ASSETS/'response_schema.json').read_bytes())
        self.schema['properties']['schema']['enum']=[b.envelope_policy.RESPONSE_SCHEMA]
        self.schema_raw=encoded(self.schema)
        fingerprint=b.sha((self.prompt+'\n'+self.schema_raw.decode()+'\n'+json.dumps(self.config,sort_keys=True)).encode())
        self.request={'call_id':self.cid,'started_at':'2026-10-10T01:00:00+00:00','request_fingerprint':fingerprint,'config':self.config}
        self.events=[{'type':'thread.started','thread_id':'synthetic-thread'},
            {'type':'item.completed','item':{'type':'agent_message','text':encoded(self.output).decode()}},
            {'type':'turn.completed','usage':{'input_tokens':3,'output_tokens':2}}]
        self.result={'call_id':self.cid,'status':'success','failure_reason':None,'config':self.config,'request_fingerprint':fingerprint,
            'started_at':self.request['started_at'],'finished_at':'2026-10-10T01:00:01+00:00','duration_seconds':1.,'model_elapsed_seconds':1.,
            'model_calls':1,'automatic_retries':0,'cost_usd':None,'prompt_characters':len(self.prompt),'prompt_character_limit':120000,
            'returncode':0,'timed_out':False,'launch_error':None,'decode_error':None,'malformed_event_lines':[],'output':self.output}
        self.approval=json.loads((ASSETS/'stage2_probe.approved.json').read_text())
        amendment=json.loads((ASSETS/'research_limit_waiver.approved.json').read_text())
        self.rows=[{'event':'approval','approval':self.approval}]
        self.rows.append({'event':'research_limit_waiver','amendment':amendment,'original_approval_sha256':b._record_digest(self.approval),
            'prefix_record_count':1,'prior_ledger_sha256':b._record_digest(self.rows)})
        self.registration={'amendment_id':amendment['amendment_id'],'budget_id':amendment['budget_id'],'run_id':str(self.run.parent),
            'arm':'B','scenario':1701,'window_seconds':3600,'solver_seconds':0,'wall_seconds':7200,'max_log_bytes':1073741824,
            'phase':'stage2_research','formal':False}
        self.registration['registration_id']=b._record_digest(self.registration)
        self.rows.append({'event':'stage_run_registered','registration':self.registration})
        self.reserve={'event':'reserve','call_id':self.cid,'phase':self.config['phase'],'run_id':str(self.run),'grant_id':self.config['grant_id'],
            'metadata':{'request_fingerprint':fingerprint,'model':self.config['model'],'timeout_seconds':180,'reasoning_effort':'medium',
                'prompt_characters':len(self.prompt),'prompt_character_limit':120000,'authorization_context':self.config['authorization_context']},
            'amendment_id':amendment['amendment_id'],'registration_id':self.registration['registration_id'],
            'run_account_before':{'attempts':0,'reported_input_output_tokens':0,'unknown_completed':[],'pending':[],'model_active_seconds':0.}}
        self.rows.append(self.reserve)
        self.finish={'event':'finish','call_id':self.cid,'status':'success','details':{}}
        self.rows.append(self.finish)
        self.command={'cwd':str(self.run/'isolated-cwd'),'stdin':'prompt.txt','proxy':None,
            'argv':[self.config['codex_binary'],'exec','--json','--ephemeral','--ignore-user-config','--ignore-rules',
                '--skip-git-repo-check','--sandbox','read-only','--color','never','--model','gpt-6-astra',
                '--cd',str(self.run/'isolated-cwd'),'--output-schema',str(self.run/'schema.json'),'--output-last-message',str(self.run/'final.txt')]}
        for key,value in {**b.expected_settings(self.run,self.config),'skills.config':[]}.items():self.command['argv']+=['-c',key+'='+toml(value)]
        self.command['argv'].append('-')
        self.write('prompt.txt',self.prompt.encode());self.write('schema.json',self.schema_raw);self.write('system-instructions.txt',b.SYSTEM_TEXT.encode())
        self.write('attempt.claim',(fingerprint+'\n').encode());self.write_json('command.json',self.command);self.write_json('request.json',self.request)
        self.sync_result()
    def write(self,name,raw):(self.run/name).write_bytes(raw)
    def write_json(self,name,v):self.write(name,encoded(v))
    def sync_result(self, update_agent_text=True):
        if update_agent_text:
            for event in self.events:
                if event.get('type')=='item.completed' and event.get('item',{}).get('type')=='agent_message':event['item']['text']=encoded(self.output).decode()
        events=b''.join((json.dumps(e,ensure_ascii=False)+'\n').encode() for e in self.events)
        self.result.update(b.summarize_events(events));self.write('events.jsonl',events)
        self.write('final.txt',encoded(self.output))
        if not (self.run/'stderr.log').exists():self.write('stderr.log',b'original synthetic stderr\n')
        self.result['process_guard']=synthetic_guard(self.run,self.request,self.config,self.result)
        self.result['cli_version']=None
        self.result['cli_version_policy']='not_run; enclosing freeze binds CLI wrapper and actual executable'
        self.write_json('result.json',self.result)
        self.finish['details']={'result_path':str(self.run/'result.json'),'failure_reason':self.result['failure_reason'],'usage':self.result['usage'],
            'duration_seconds':self.result['duration_seconds'],'cost_usd':None,'completed_turns':self.result['completed_turns']}
        self.sync_ledger()
    def sync_ledger(self):self.ledger.write_bytes(b''.join((json.dumps(r,ensure_ascii=False)+'\n').encode() for r in self.rows))
    def args(self):
        return dict(run_dir=self.run,expected_run_dir=self.run,expected_prompt=self.prompt,expected_schema=self.schema,expected_config=self.config,
            ledger_snapshot_path=self.ledger,ledger_source_path=self.ledger,expected_ledger_sha256=b.sha(self.ledger.read_bytes()),
            expected_approval_record_sha256=b._record_digest(self.approval),expected_registration_id=self.registration['registration_id'],
            expected_registration_record_sha256=b._record_digest(self.registration),expected_interaction_context=self.context,
            expected_disabled_skill_paths=[])
    def bind(self,**changes):return b.bind_original_call(**(self.args()|changes))

from src.smt_fullfab.interface import compact_pages
from src.smt_fullfab.plan_delta import SCHEMA, STATE_SCHEMA, ORDER_POLICY, anchor_hashes

SOURCE = 'a' * 64


def fixture():
    def task(tid, mid, start):
        return {'id': tid, 'machine': mid, 'lot_ids': ['lot-' + tid], 'steps': [1], 'visits': [1],
                'operation_ids': ['op-' + tid], 'not_before': start,
                'unknown_future_field': {'note': '原样', 'explicit_null': None}}
    base = {'version': 'base', 'created_at': 0, 'valid_until': 100, 'freeze_until': 0,
            'reason': 'exact prior model choice', 'scope': [2, 1, 913],
            'tasks': [task('done', 1, 0), task('z', 1, 12), task('a', 2, 13)],
            'holds': [{'machine': 1, 'until': 90, 'after_task_id': 'z', 'reason': 'tail'},
                      {'machine': 913, 'until': 90, 'reason': 'explicit wait', 'extra': None},
                      {'machine': 2, 'until': 90, 'after_task_id': 'a', 'reason': 'tail'}]}
    problem = {'schema': 'smt-fullfab-problem-2', 'time': 10, 'horizon_end': 100, 'scope': [2, 1, 913],
               'machines': [{'machine': 2, 'family': 'F', 'custom': ['not ranked']},
                            {'machine': 1, 'family': 'F'}, {'machine': 913, 'family': 'idle'}],
               'operations': [{'operation_id': 'op-' + tid, 'lot_id': 'lot-' + tid, 'step': 1, 'visit': 1,
                               'eligible_machines': [2, 1], 'family': 'F', 'batch_key': ['part', 1, 'recipe'],
                               'batch_min': 1, 'batch_max': 1, 'priority': priority,
                               'unknown_operation_field': {'nullable': None, '中文': ['retain', tid]}}
                              for tid, priority in [('z', 1), ('done', 900), ('a', 10), ('new', 100)]],
               'public_metadata': {'no_loss': None}}
    state = {'schema': STATE_SCHEMA, 'time': 10, 'observation_end': 100,
             'base_plan_version': 'base', 'dispatched_task_ids': ['done']}
    delta = {'schema': SCHEMA, 'anchors': anchor_hashes(base, problem, state, source_sha256=SOURCE),
             'order_policy': ORDER_POLICY,
             'plan_header': {'version': 'delta-1', 'created_at': 10, 'valid_until': 100,
                             'freeze_until': 10, 'reason': 'explicit keep', 'scope': [2, 1, 913]},
             'tasks': {'keep': {'mode': 'all_pending_except', 'ids': []}, 'cancel_ids': [], 'replace': [], 'add': []},
             'holds': {'keep': {'mode': 'all_except', 'ids': []}, 'cancel_ids': [], 'replace': [], 'add': []},
             'machine_orders': []}
    paging = compact_pages(problem)
    # Two complete pages with the exact original compact family groups.
    paging['pages'] = [[group] for page in paging['pages'] for group in page]
    paging['page_count'] = len(paging['pages'])
    return base, problem, state, paging, delta

