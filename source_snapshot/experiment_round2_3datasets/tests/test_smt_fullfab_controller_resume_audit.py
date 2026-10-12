"""Full file-chain audit fixtures with explicitly synthetic physical/model stubs."""
import dataclasses
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from src.smt_fullfab import budget, controller_resume as resume
from src.smt_fullfab.controller_audit import _sections
from src.smt_fullfab.controller_resume_audit import audit_controller_resume
from src.smt_fullfab.environment import write_new
from tests.test_smt_fullfab_controller_resume import SyntheticPhysicalState
from tests import test_smt_fullfab_controller_resume as resume_fixtures


class JournalPhysicalStub(SyntheticPhysicalState):
    @classmethod
    def from_snapshot(cls,path,*,trace_path):
        env=super().from_snapshot(path,trace_path=trace_path)
        env.state['trace'][-1]['prefix_event_count']=len(env.state['trace'])-1
        env.flush();return env

    def flush(self):self.trace_path.write_text(''.join(json.dumps(e)+'\n' for e in self.state['trace']))

    def commit_plan(self,plan):
        super().commit_plan(plan)
        self.state['trace'].append({'kind':'plan_committed','time':self.t,'plan':plan});self.flush()

    def advance_plan(self,target):
        super().advance_plan(target)
        if self.finished:self.state['trace'].append({'kind':'terminal','time':self.t})
        self.flush()


class RecoveryEvidenceAuditTests(unittest.TestCase):
    def setUp(self):
        # Reuse only the isolated setup, not the execution test assertions.
        self.fixture=resume_fixtures.ControllerResumeTests(methodName='test_reuses_fourteen_pages_revision_then_rolls_without_original_calls')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture
        f.physical_audit.return_value={'valid':True,'errors':[],'metrics':{'synthetic_metric':1}}
        f.stack.enter_context(patch('src.smt_fullfab.audit.audit_trace',return_value=f.physical_audit.return_value))
        f.stack.enter_context(patch.object(resume,'FullFabEnvironment',JournalPhysicalStub))
        JournalPhysicalStub.problem_value=SyntheticPhysicalState.problem_value
        f.source_audit.side_effect=lambda out,ledger_path:audit_controller_resume(out,ledger_path)
        f.stack.enter_context(patch.object(resume,'source_snapshot',side_effect=self.source_snapshot))
        f.transport.side_effect=self.transport
        self.response_override=None

    def source_snapshot(self,out):
        hashes={}
        for name in ('controller_resume.py','controller_resume_audit.py','budget.py','model_transport.py','environment.py','interface.py'):
            path=out/'source_snapshot/src/smt_fullfab'/name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('# Synthetic hash-bound unit fixture. Never executed.\n')
            hashes[str(path.relative_to(out/'source_snapshot'))]=hashlib.sha256(path.read_bytes()).hexdigest()
        return {'source_sha256':hashes}

    def transport(self,prompt,schema,directory,config):
        f=self.fixture;sections=_sections(prompt);page=sections['SCHEMA_AND_LIMITS']['page_index']
        output={'tasks':[{'machine':g['machines'][0][0],'operations':[row[0]],'sequence':row[8],
                           'start':sections['SCHEMA_AND_LIMITS']['time']} for g in sections['PAGE'] for row in g['operations']],
                'holds':[],'commit':sections['SCHEMA_AND_LIMITS']['last_page'],'reason':'synthetic exact model output'}
        if self.response_override:output=self.response_override(page,output)
        directory.mkdir();cfg=dataclasses.asdict(config)
        fingerprint=hashlib.sha256((prompt+'\n'+json.dumps(schema,ensure_ascii=False,indent=2)+'\n'+'\n'+json.dumps(cfg,sort_keys=True)).encode()).hexdigest()
        (directory/'prompt.txt').write_text(prompt);write_new(directory/'schema.json',schema)
        (directory/'attempt.claim').write_text(fingerprint+'\n')
        ledger=budget.BudgetLedger(f.ledger_path)
        cid=ledger.reserve(phase=config.phase,run_id=str(directory),grant_id=config.grant_id,
            metadata={'model':config.model,'reasoning_effort':config.reasoning_effort,'timeout_seconds':config.timeout_seconds,
                      'authorization_context':config.authorization_context,'request_fingerprint':fingerprint})
        request={'call_id':cid,'config':cfg,'request_fingerprint':fingerprint};write_new(directory/'request.json',request)
        usage={'input_tokens':2,'output_tokens':3,'cached_input_tokens':0,'cache_write_input_tokens':None,'reasoning_output_tokens':None}
        result={**request,'status':'success','output':output,'failure_reason':None,'usage':usage,'duration_seconds':0.000001,
                'returncode':0,'timed_out':False,'native_tool_events':[],'malformed_event_lines':[]}
        write_new(directory/'result.json',result);write_new(directory/'final.txt',output)
        (directory/'events.jsonl').write_text(json.dumps({'type':'turn.completed','usage':{'input_tokens':2,'output_tokens':3,'cached_input_tokens':0}})+'\n')
        ledger.finish(cid,'success',{'usage':usage,'duration_seconds':result['duration_seconds']})
        return result

    def execute(self):
        result=self.fixture.execute();audit=json.loads((self.fixture.segment/'recovery_audit.json').read_text())
        self.assertTrue(audit['valid'],audit)
        return result,audit

    def audit(self):return audit_controller_resume(self.fixture.segment,self.fixture.ledger_path)

    def test_complete_inherited_page_raw_ledger_and_plan_chain(self):
        result,audit=self.execute()
        self.assertEqual(result['status'],'success',result)
        self.assertTrue(audit['successful_full_window'])
        self.assertEqual(audit['new_accepted_pages'],5)
        self.assertEqual(audit['model_attempts_checked'],5)
        self.assertEqual(audit['attribution_checked_plans'],2)
        self.assertTrue(self.audit()['valid'],self.audit())

    def test_rejected_new_page_remains_in_model_and_cost_chain(self):
        seen=set()
        def reject_once(page,output):
            if page==15 and page not in seen:
                seen.add(page);output['tasks'][0]['operations']=['lot0:1:1']
            return output
        self.response_override=reject_once
        result,audit=self.execute()
        self.assertEqual(result['status'],'success',result)
        self.assertEqual(audit['new_rejected_pages'],1)
        self.assertEqual(audit['model_attempts_checked'],6)

    def test_changed_metrics_are_rejected_independently_of_success_flag(self):
        self.execute();path=self.fixture.segment/'result.json';result=json.loads(path.read_text());result['metrics']={'synthetic_metric':999}
        path.write_text(json.dumps(result));audited=self.audit()
        self.assertTrue(any('result metrics differ' in e for e in audited['errors']),audited)
        path=self.fixture.segment/'audit.json';value=json.loads(path.read_text());value['metrics']={'synthetic_metric':999};path.write_text(json.dumps(value))
        self.assertTrue(any('saved physical audit metrics differ' in e for e in self.audit()['errors']))

    def test_parent_page_cannot_be_replaced_by_segment_advice(self):
        self.execute();path=self.fixture.segment/'page_accepted.jsonl';rows=[json.loads(x) for x in path.read_text().splitlines()]
        rows[0]['call_id']='invented-parent-call';path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        self.assertTrue(any('page_accepted journal' in e for e in self.audit()['errors']))

    def test_changed_feedback_and_omitted_rejected_attempt_cannot_pass(self):
        self.response_override=lambda page,output:{**output,'tasks':[{**output['tasks'][0],'operations':['lot0:1:1']}]}
        result,audit=self.execute();self.assertFalse(audit['successful_full_window']);self.assertEqual(result['status'],'failed')
        path=self.fixture.segment/'page_rejected.jsonl';path.write_text('')
        self.assertTrue(any('page_rejected journal' in e for e in self.audit()['errors']))

    def test_finish_and_final_log_overrun_are_never_success_evidence(self):
        self.execute();path=self.fixture.segment/'large-audit.bin';path.write_bytes(b'x'*1000001)
        self.assertTrue(any('cumulative log cap' in e for e in self.audit()['errors']))


if __name__=='__main__':unittest.main()
