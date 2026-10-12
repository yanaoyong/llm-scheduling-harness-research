"""Small synthetic original-file fixtures; no transport/budget execution."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab import B_delta_transport_binding as b

ROOT=Path(__file__).resolve().parents[1]


def encoded(v):return (json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode()
def toml(v):
    if type(v)is bool:return 'true' if v else 'false'
    if type(v)is dict:return '{'+','.join(k+'='+toml(x) for k,x in v.items())+'}'
    if type(v)is list:return '['+','.join(map(toml,v))+']'
    return json.dumps(v)


class Fixture:
    def __init__(self,directory):
        self.root=Path(directory).resolve();self.run=self.root/'runs/smt_fullfab_stage2/B_fixture/model_000';self.run.mkdir(parents=True)
        self.ledger=self.root/'ledger.jsonl';self.cid='synthetic-only-call'
        self.config={'model':'gpt-6-astra','reasoning_effort':'medium','timeout_seconds':180,
            'codex_binary':'/synthetic/not-executed/codex','proxy':None,'ledger_path':str(self.ledger),
            'phase':'stage2_research','grant_id':'smt-fullfab-stage2-probe-v1',
            'authorization_context':{'purpose':'B','arm':'B','scenario':1701,'window_seconds':3600}}
        self.context={'interaction_id':'i','session_id':'s','anchors':{'base_plan_sha256':'a'*64,
            'problem_sha256':'b'*64,'execution_state_sha256':'c'*64,'source_sha256':'d'*64},'catalog_sha256':'e'*64}
        body='SYNTHETIC FIXTURE TASK\nINPUT_JSON\n'+json.dumps(self.context)
        self.prompt='PROMPT_BODY_SHA256='+b.sha(body.encode())+'\n'+body
        self.output={'schema':'draft-smt-fullfab-delta-interaction-v2-response',**self.context,
            'prompt_body_sha256':b.sha(body.encode()),'memory':'原样 memory','request':{'kind':'read_candidates'}}
        self.schema={'type':'object'};self.schema_raw=encoded(self.schema)
        fingerprint=b.sha((self.prompt+'\n'+self.schema_raw.decode()+'\n'+json.dumps(self.config,sort_keys=True)).encode())
        self.request={'call_id':self.cid,'started_at':'2026-10-10T01:00:00+00:00','request_fingerprint':fingerprint,'config':self.config}
        self.events=[{'type':'thread.started','thread_id':'synthetic-thread'},
            {'type':'item.completed','item':{'type':'agent_message','text':encoded(self.output).decode()}},
            {'type':'turn.completed','usage':{'input_tokens':3,'output_tokens':2}}]
        self.result={'call_id':self.cid,'status':'success','failure_reason':None,'config':self.config,'request_fingerprint':fingerprint,
            'started_at':self.request['started_at'],'finished_at':'2026-10-10T01:00:01+00:00','duration_seconds':1.,'model_elapsed_seconds':1.,
            'model_calls':1,'automatic_retries':0,'cost_usd':None,'prompt_characters':len(self.prompt),'prompt_character_limit':120000,
            'returncode':0,'timed_out':False,'launch_error':None,'decode_error':None,'malformed_event_lines':[],'output':self.output}
        self.approval=json.loads((ROOT/'configs/smt_fullfab/stage2_probe.approved.json').read_text())
        amendment=json.loads((ROOT/'configs/smt_fullfab/research_limit_waiver.approved.json').read_text())
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
        self.write('final.txt',encoded(self.output));self.write_json('result.json',self.result)
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


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.f=Fixture(self.temp.name)
    def rejected(self,**changes):
        r=self.f.bind(**changes);self.assertFalse(r.report['local_channel_files_and_ledger_verified'],r.report)
        self.assertFalse(r.report['success_action_eligible']);self.assertTrue(r.report['errors']);return r
    def test_success_original_bytes_attachments_and_no_writes(self):
        before={p:p.read_bytes() for p in self.f.root.rglob('*') if p.is_file()};r=self.f.bind()
        self.assertTrue(r.report['success_action_eligible'],r.report);self.assertEqual(r.durable_attachments()['completion']['final_bytes'],encoded(self.f.output))
        self.assertEqual(r.durable_attachments()['request']['reserve_bytes'],self.f.ledger.read_bytes().splitlines(keepends=True)[3])
        self.assertFalse(r.report['assurance']['actual_backend_invocation_independently_proven'])
        self.assertEqual(before,{p:p.read_bytes() for p in self.f.root.rglob('*') if p.is_file()})
    def test_unknown_usage_is_preserved_without_future_admission_decision(self):
        self.f.events[-1].pop('usage');self.f.sync_result();r=self.f.bind()
        self.assertTrue(r.report['success_action_eligible'],r.report);self.assertFalse(r.report['usage_known']);self.assertIsNone(r.report['usage']['input_tokens'])
    def test_original_bool_usage_not_legitimized_by_matching_integer_result_and_finish(self):
        self.f.events[-1]['usage']['input_tokens']=True
        # Reproduce the original production summary literally: true had become 1.
        # Do not use the corrected summarizer to build this corrupted evidence.
        self.f.result['usage']['input_tokens']=1
        self.f.write_json('result.json',self.f.result)
        self.f.finish['details']['usage']=deepcopy(self.f.result['usage']);self.f.sync_ledger()
        raw=b''.join((json.dumps(e,ensure_ascii=False)+'\n').encode() for e in self.f.events)
        self.f.write('events.jsonl',raw)
        before={p:p.read_bytes() for p in self.f.root.rglob('*') if p.is_file()}
        r=self.rejected();self.assertEqual(r.report['errors'][0]['code'],'usage_type')
        self.assertNotEqual(r.report.get('usage_known'),True)
        self.assertEqual(r.raw_artifacts['events.jsonl'],raw)
        with self.assertRaises(b.BindingError):r.durable_attachments()
        self.assertEqual(before,{p:p.read_bytes() for p in self.f.root.rglob('*') if p.is_file()})
    def test_each_original_token_counter_rejects_bool_negative_string_and_fraction(self):
        fields=('input_tokens','cached_input_tokens','output_tokens','cache_write_input_tokens','reasoning_output_tokens')
        invalid=(True,False,-1,'1',1.0,1.5,[],{})
        for field in fields:
            for value in invalid:
                with self.subTest(field=field,value=value):
                    self.f.events[-1]['usage']={'input_tokens':3,'output_tokens':2,field:value}
                    self.f.write('events.jsonl',b''.join((json.dumps(e)+'\n').encode() for e in self.f.events))
                    r=self.rejected();self.assertEqual(r.report['errors'][0]['code'],'usage_type')
    def test_original_nonfinite_usage_rejected_before_accounting(self):
        for value in (float('inf'),float('-inf'),float('nan')):
            with self.subTest(value=value):
                self.f.events[-1]['usage']['input_tokens']=value
                self.f.write('events.jsonl',b''.join((json.dumps(e)+'\n').encode() for e in self.f.events))
                r=self.rejected();self.assertEqual(r.report['errors'][0]['code'],'json')
        self.f.events[-1]['usage']['input_tokens']=0
        raw=b''.join((json.dumps(e)+'\n').encode() for e in self.f.events)
        self.f.write('events.jsonl',raw.replace(b'"input_tokens": 0',b'"input_tokens": 1e999'))
        self.rejected()
    def test_null_missing_and_partial_original_usage_remain_unknown(self):
        for usage in (None,{}, {'input_tokens':None,'output_tokens':2},{'input_tokens':3,'output_tokens':None}):
            with self.subTest(usage=usage):
                self.f.events[-1]['usage']=usage;self.f.sync_result();before=self.f.ledger.read_bytes();r=self.f.bind()
                self.assertTrue(r.report['success_action_eligible'],r.report);self.assertFalse(r.report['usage_known'])
                self.assertTrue(r.report['usage']['input_tokens'] is None or r.report['usage']['output_tokens'] is None)
                self.assertEqual(before,self.f.ledger.read_bytes())
    def test_exact_zero_and_large_integer_counters_remain_known_without_rounding(self):
        self.f.events[-1]['usage']={'input_tokens':0,'output_tokens':2**64+1,'cached_input_tokens':None}
        self.f.sync_result();r=self.f.bind();self.assertTrue(r.report['success_action_eligible'],r.report)
        self.assertTrue(r.report['usage_known']);self.assertEqual(r.report['usage']['output_tokens'],2**64+1)
        self.assertIsNone(r.report['usage']['cached_input_tokens'])
    def test_nonobject_usage_and_extra_invalid_counter_cannot_hide_as_unknown(self):
        for usage in (True,'unknown',[],{'input_tokens':3,'output_tokens':2,'future_tokens':True}):
            with self.subTest(usage=usage):
                self.f.events[-1]['usage']=usage
                self.f.write('events.jsonl',b''.join((json.dumps(e)+'\n').encode() for e in self.f.events))
                r=self.rejected();self.assertEqual(r.report['errors'][0]['code'],'usage_type')

    def test_legacy_structural_diagnostic_is_never_attachable(self):
        r=self.f.bind(require_interaction_envelope=False);self.assertTrue(r.report['local_channel_files_and_ledger_verified'],r.report)
        self.assertFalse(r.report['success_action_eligible'])
        with self.assertRaises(b.BindingError):r.durable_attachments()
    def test_external_prompt_schema_config_and_hash_anchors(self):
        for changes in ({'expected_prompt':self.f.prompt+' '},{'expected_schema':{'type':'array'}},
            {'expected_config':self.f.config|{'reasoning_effort':'high'}},{'expected_config':self.f.config|{'timeout_seconds':181}},
            {'expected_ledger_sha256':'0'*64},{'expected_approval_record_sha256':'0'*64},
            {'expected_registration_record_sha256':'0'*64},{'expected_registration_id':'0'*64},
            {'expected_run_dir':self.f.run.parent},{'ledger_source_path':self.f.root/'another'}):
            with self.subTest(changes=changes):self.rejected(**changes)
    def test_pending_missing_finish_no_repair(self):
        self.f.rows.pop();self.f.sync_ledger();before=self.f.ledger.read_bytes();self.rejected();self.assertEqual(before,self.f.ledger.read_bytes())
    def test_result_missing_is_pending_not_completed(self):
        (self.f.run/'result.json').unlink();self.rejected();self.assertFalse((self.f.run/'result.json').exists())
    def test_duplicate_or_reordered_reservation_finish(self):
        old=deepcopy(self.f.rows)
        variants=[old+[deepcopy(old[3])],old+[deepcopy(old[4])],old[:3]+[old[4],old[3]],old[:2]+[old[3],old[2],old[4]]]
        for rows in variants:
            with self.subTest(rows=rows):self.f.rows=rows;self.f.sync_ledger();self.rejected()
    def test_changed_claim_request_or_result_call(self):
        self.f.write('attempt.claim',b'0'*64+b'\n');self.rejected()
        self.f.write('attempt.claim',(self.f.request['request_fingerprint']+'\n').encode());self.f.result['call_id']='other';self.f.sync_result();self.rejected()
    def test_transport_directory_reuse_with_different_call_is_rejected(self):
        extra=deepcopy(self.f.reserve);extra['call_id']='other';self.f.rows.append(extra);self.f.sync_ledger();self.rejected()
    def test_finish_details_mismatch(self):
        self.f.finish['details']['duration_seconds']=0.;self.f.sync_ledger();self.rejected()
    def test_timeout_failed_returncode_and_false_resource_types(self):
        for key,value in (('timed_out',True),('returncode',1),('status','failed'),('model_calls',True),('duration_seconds',False)):
            with self.subTest(key=key):
                old=self.f.result[key];self.f.result[key]=value;self.f.sync_result();self.rejected();self.f.result[key]=old
        self.f.sync_result()
    def test_event_usage_mismatch_and_native_tool_event(self):
        self.f.result['usage']['input_tokens']=999;self.f.write_json('result.json',self.f.result);self.rejected()
        self.f.events.insert(1,{'type':'item.completed','item':{'type':'command_execution','command':'not-run'}});self.f.sync_result();self.rejected()
    def test_multiple_completed_turns_rejected(self):
        self.f.events.append(deepcopy(self.f.events[-1]));self.f.sync_result();self.rejected()
    def test_system_changed(self):self.f.write('system-instructions.txt',b'other');self.rejected()
    def test_command_enable_or_duplicate_override_rejected(self):
        original=deepcopy(self.f.command)
        for value in ('features.shell_tool=true','features.shell_tool=false','unknown=true'):
            self.f.command=deepcopy(original);self.f.command['argv'][-1:-1]=['-c',value];self.f.write_json('command.json',self.f.command);self.rejected()
    def test_missing_isolation_override_rejected(self):
        i=self.f.command['argv'].index('features.shell_tool=false');del self.f.command['argv'][i-1:i+1]
        self.f.write_json('command.json',self.f.command);self.rejected()
    def test_disabled_skill_inventory_is_external_and_exact(self):self.rejected(expected_disabled_skill_paths=['/unexpected/skill'])
    def test_original_agent_message_must_equal_final_bytes(self):
        self.f.events[1]['item']['text']='{}';self.f.sync_result(update_agent_text=False);self.rejected()
    def test_envelope_mode_bool_cannot_be_truthy_string(self):self.rejected(require_interaction_envelope='yes')
    def test_final_bytes_differ_from_result(self):self.f.write('final.txt',b'{"other":true}');self.rejected()
    def test_illegal_json_encoding_duplicates_nonfinite(self):
        for raw in (b'\xff',b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":1e999}'):
            with self.subTest(raw=raw):self.f.write('final.txt',raw);self.rejected()
    def test_envelope_memory_context_body_and_request_bounds(self):
        old=deepcopy(self.f.output)
        for key,value in (('memory',None),('memory','x'*8192),('session_id','old'),('prompt_body_sha256','0'*64),('request',{'kind':'auto_apply'})):
            self.f.output=deepcopy(old);self.f.output[key]=value;self.f.result['output']=self.f.output;self.f.sync_result()
            with self.subTest(key=key):self.rejected()
    def test_symbolic_file_rejected(self):
        path=self.f.run/'final.txt';original=path.read_bytes();path.unlink();target=self.f.root/'other';target.write_bytes(original);path.symlink_to(target);self.rejected()
    def test_path_replacement_after_snapshot_is_rejected(self):
        original=b.verify_envelope
        def swap(*args):
            answer=original(*args);p=self.f.run/'result.json';q=self.f.run/'swap';q.write_bytes(p.read_bytes());q.replace(p);return answer
        with patch.object(b,'verify_envelope',side_effect=swap):self.rejected()
    def test_copied_ledger_snapshot_has_explicit_asserted_original_source(self):
        p=self.f.root/'snapshot';p.write_bytes(self.f.ledger.read_bytes());r=self.f.bind(ledger_snapshot_path=p)
        self.assertTrue(r.report['success_action_eligible'],r.report);self.assertTrue(r.report['ledger_snapshot']['source_path_asserted_by_caller'])


if __name__=='__main__':unittest.main()
