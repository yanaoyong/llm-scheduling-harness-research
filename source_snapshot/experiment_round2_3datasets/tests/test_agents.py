"""Offline unit tests only. Synthetic transport outputs never become experiment records."""
import concurrent.futures
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from src.agents.budget import BudgetLedger, BudgetExceeded
from src.agents.model_transport import ModelConfig, build_command, summarize_events
from src.agents.static import decode_order, ActionError, observed_problem, run_b, run_c
from src.fjsp.validator import validate

ROOT=Path(__file__).resolve().parents[1]
P={'schema_version':'fjsp-1','instance_id':'unit','family':'unit','machines':[0,1],
   'source':{'reference_answer':'MUST NOT LEAK'},'known_optimum':42,
   'jobs':[{'id':0,'operations':[
       {'id':'j0o0','job':0,'index':0,'alternatives':[{'machine':0,'duration':3},{'machine':1,'duration':5}]},
       {'id':'j0o1','job':0,'index':1,'alternatives':[{'machine':1,'duration':2}]}]},
       {'id':1,'operations':[{'id':'j1o0','job':1,'index':0,'alternatives':[{'machine':1,'duration':4}]}]}]}
ORDER=[{'id':'j0o0','machine':0},{'id':'j1o0','machine':1},{'id':'j0o1','machine':1}]

def _reserve_worker(path):
    try:
        BudgetLedger(path).reserve(phase='development',run_id='/unit/run',grant_id='test')
        return 1
    except BudgetExceeded:
        return 0

def transport(output):
    return {'status':'success','output':output,'usage':{'input_tokens':1,'output_tokens':1},'duration_seconds':0,'model_calls':1}

class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='agents-unit-',dir=ROOT/'tests')
        self.root=Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def test_decoder_preserves_order_and_handcomputed_times(self):
        s=decode_order(P,ORDER)
        self.assertEqual(s['operations'],[
            {'id':'j0o0','machine':0,'start':0,'end':3},
            {'id':'j1o0','machine':1,'start':0,'end':4},
            {'id':'j0o1','machine':1,'start':4,'end':6}])
        self.assertEqual(validate(P,s),{'valid':True,'errors':[],'makespan':6})
    def test_decoder_rejects_no_repair(self):
        bad=[ORDER[2],ORDER[0],ORDER[1]]
        cases=[bad,ORDER[:-1],[ORDER[0],ORDER[0],ORDER[2]],
               [dict(ORDER[0],machine=99),*ORDER[1:]],
               [dict(ORDER[0],machine=True),*ORDER[1:]]]
        for order in cases:
            with self.assertRaises(ActionError): decode_order(P,order)
    def test_sanitizer_excludes_references(self):
        text=json.dumps(observed_problem(P))
        self.assertNotIn('reference',text)
        self.assertNotIn('42',text)
        self.assertNotIn('family',text)
    def test_ledger_race_counts_failures_and_prevents_overrun(self):
        path=self.root/'ledger.jsonl'
        ledger=BudgetLedger(path)
        ledger.grant('test','development',3,'/unit')
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
            attempted=list(pool.map(_reserve_worker,[path]*10))
        self.assertEqual(sum(attempted),3)
        self.assertEqual(ledger.summary()['attempts'],3)
        self.assertEqual(len(ledger.summary()['unfinished_call_ids']),3)
        cid=ledger.summary()['unfinished_call_ids'][0]
        ledger.finish(cid,'failed',{'usage':None})
        with self.assertRaises(BudgetExceeded): ledger.reserve(phase='development',run_id='/unit/run',grant_id='test')
        with self.assertRaises(ValueError): ledger.finish(cid,'success')
        with self.assertRaises(ValueError): ledger.grant('test','development',5,'/unit')
    def test_development_hard_cap_across_grants(self):
        ledger=BudgetLedger(self.root/'ledger.jsonl')
        ledger.grant('one','development',24,'/unit')
        ledger.grant('two','development',24,'/unit')
        for i in range(24): ledger.reserve(phase='development',run_id='/unit/run',grant_id='one')
        with self.assertRaises(BudgetExceeded): ledger.reserve(phase='development',run_id='/unit/run',grant_id='two')
    def test_formal_needs_frozen_limit_and_solver_bounds(self):
        ledger=BudgetLedger(self.root/'ledger.jsonl')
        with self.assertRaises(ValueError): ledger.grant('formal','formal',2,'/unit')
        ledger.grant_solver('s','development',2,'/unit')
        cid=ledger.reserve_solver(phase='development',run_id='/unit/a',grant_id='s',requested_seconds=2)
        ledger.finish(cid,'failed')
        with self.assertRaises(BudgetExceeded): ledger.reserve_solver(phase='development',run_id='/unit/a',grant_id='s',requested_seconds=.1)
    def test_event_audit_fails_native_tools_and_preserves_unknown(self):
        result=summarize_events([{'type':'item.completed','item':{'type':'command_execution'}}, {'type':'item.completed','item':{'type':'error'}}])
        self.assertEqual(len(result['native_tool_events']),1)
        self.assertIsNone(result['usage']['input_tokens'])
        cmd=build_command(self.root,ModelConfig())
        for setting in ['features.shell_tool=false','features.code_mode_host=false','approval_policy="never"','mcp_servers={}']:
            self.assertIn(setting,cmd)
        self.assertIn('--ephemeral',cmd)
    def test_b_revision_is_offline_unit_stub_only(self):
        cfg={'max_model_calls':2}
        outputs=[transport({'order':ORDER[:-1],'rationale':'unit invalid'}),transport({'order':ORDER,'rationale':'unit valid'})]
        with patch('src.agents.static.call_model',side_effect=outputs), patch('src.fjsp.solver.solve',side_effect=AssertionError('B must never solve')):
            r=run_b(P,self.root/'b',cfg)
        self.assertEqual(r['status'],'success')
        self.assertEqual(r['metrics']['makespan'],6)
        self.assertEqual(r['revisions'],1)
        self.assertFalse(r['first_output_valid'])
        self.assertTrue(r['revision_success'])
        self.assertIsNotNone(r['first_valid_output_seconds'])
        with patch('src.agents.static.call_model',side_effect=AssertionError('replay must be offline')):
            self.assertEqual(run_b(P,self.root/'b',{**cfg,'resume':True}),r)
    def test_c_requires_explicit_candidate_selection(self):
        ledger=BudgetLedger(self.root/'ledger.jsonl')
        ledger.grant_solver('s','development',3,str(self.root))
        cfg={'model':{'ledger_path':str(ledger.path)},'solver_grant_id':'s','solver_budget_seconds':1,'max_model_calls':1}
        solve={'action':'solve','time_limit':1,'seed':11,'search_branching':'AUTOMATIC_SEARCH','randomize_search':False,'candidate_index':None,'rationale':'unit'}
        with patch('src.agents.static.call_model',return_value=transport(solve)):
            r=run_c(P,self.root/'c_missing',cfg)
        self.assertEqual(r['failure_type'],'missing_explicit_finish')
        self.assertIsNone(r['schedule'])
        self.assertIsNone(r['metrics']['makespan'])
        finish={'action':'finish','time_limit':None,'seed':None,'search_branching':None,'randomize_search':None,'candidate_index':0,'rationale':'unit'}
        with patch('src.agents.static.call_model',side_effect=[transport(solve),transport(finish)]):
            r=run_c(P,self.root/'c_valid',{**cfg,'max_model_calls':2})
        self.assertEqual(r['status'],'success')
        self.assertEqual(r['selected_candidate'],0)
        self.assertTrue(r['validation']['valid'])
        self.assertTrue(r['first_action_valid'])
        self.assertTrue(r['first_candidate_valid'])
        self.assertTrue(r['first_output_valid'])
        self.assertIsNotNone(r['first_valid_output_seconds'])

    def test_c_invalid_first_action_cannot_become_first_output_success(self):
        ledger=BudgetLedger(self.root/'ledger.jsonl')
        ledger.grant_solver('s','development',1,str(self.root))
        cfg={'model':{'ledger_path':str(ledger.path)},'solver_grant_id':'s','solver_budget_seconds':1,'max_model_calls':3}
        solve={'action':'solve','time_limit':1,'seed':11,'search_branching':'AUTOMATIC_SEARCH','randomize_search':False,'candidate_index':None,'rationale':'unit'}
        finish={'action':'finish','time_limit':None,'seed':None,'search_branching':None,'randomize_search':None,'candidate_index':0,'rationale':'unit'}
        with patch('src.agents.static.call_model',side_effect=[transport(finish),transport(solve),transport(finish)]):
            r=run_c(P,self.root/'c',cfg)
        self.assertEqual(r['status'],'success')
        self.assertFalse(r['first_action_valid'])
        self.assertFalse(r['first_output_valid'])
        self.assertTrue(r['first_candidate_valid'])
        self.assertTrue(r['revision_success'])
        self.assertEqual(r['revisions'],1)

if __name__=='__main__': unittest.main()
