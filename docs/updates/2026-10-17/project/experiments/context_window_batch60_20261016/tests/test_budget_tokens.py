"""Offline budget admission tests: no real CLI, model, solver or shared ledger use."""
import dataclasses
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from src.agents.budget import BudgetLedger, BudgetExceeded, PHASE_TOKEN_LIMITS
from src.agents.model_transport import call_model, ModelConfig, PromptTooLarge, PROMPT_CHARACTER_LIMIT

ROOT=Path(__file__).resolve().parents[1]

class TokenBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='token-budget-unit-',dir=ROOT/'tests')
        self.root=Path(self.temp.name)
        self.ledger=BudgetLedger(self.root/'ledger.jsonl')
    def tearDown(self):self.temp.cleanup()
    def grant(self,threshold=None):
        return self.ledger.grant('dev','development',24,str(self.root),phase_limit_tokens=threshold)
    def reserve(self,phase='development',grant='dev'):
        return self.ledger.reserve(phase=phase,run_id=str(self.root/'run'),grant_id=grant)
    def finish(self,input_tokens=None,output_tokens=None,status='success',**extra):
        cid=self.reserve()
        self.ledger.finish(cid,status,{'usage':{'input_tokens':input_tokens,'output_tokens':output_tokens,**extra}})
        return cid
    def test_threshold_uses_input_plus_output_without_double_counting_subsets(self):
        self.grant(101)
        self.finish(80,20,cached_input_tokens=80,reasoning_output_tokens=20)
        tokens=self.ledger.summary()['tokens_by_phase']['development']
        self.assertEqual(tokens['reported_total_tokens'],100)
        self.assertEqual(tokens['unknown_completed_attempts'],0)
        last=self.reserve();self.ledger.finish(last,'success',{'usage':{'input_tokens':1,'output_tokens':0}})
        with self.assertRaisesRegex(BudgetExceeded,'token threshold'):self.reserve()
    def test_exact_threshold_and_failed_usage_consume_budget(self):
        self.grant(100)
        self.finish(70,30,status='failed')
        before=self.ledger.path.read_bytes()
        with self.assertRaises(BudgetExceeded):self.reserve()
        self.assertEqual(self.ledger.path.read_bytes(),before)
        self.assertEqual(self.ledger.summary()['attempts'],1)
    def test_one_admitted_call_can_overshoot_then_next_is_denied(self):
        self.grant(100)
        self.finish(10,10)
        self.finish(70,50)
        self.assertEqual(self.ledger.summary()['tokens_by_phase']['development']['reported_total_tokens'],140)
        with self.assertRaises(BudgetExceeded):self.reserve()
    def test_three_unknown_completions_stop_next_call(self):
        self.grant()
        for i in range(3): self.finish(status='failed')
        s=self.ledger.summary()['tokens_by_phase']['development']
        self.assertEqual(s['unknown_completed_attempts'],3)
        self.assertEqual(s['reported_total_tokens'],0)
        with self.assertRaisesRegex(BudgetExceeded,'unknown usage'):self.reserve()
    def test_pending_reservations_are_not_unknown_usage(self):
        self.grant()
        calls=[self.reserve() for _ in range(5)]
        s=self.ledger.summary()['tokens_by_phase']['development']
        self.assertEqual(s['pending_attempts'],5)
        self.assertEqual(s['unknown_completed_attempts'],0)
        for cid in calls[:2]:self.ledger.finish(cid,'failed',{})
        another=self.reserve()
        self.assertIsInstance(another,str)
        self.assertEqual(self.ledger.summary()['tokens_by_phase']['development']['unknown_completed_attempts'],2)
    def test_partial_usage_counts_known_lower_bound_and_unknown_attempt(self):
        self.grant(100)
        self.finish(100,None)
        s=self.ledger.summary()['tokens_by_phase']['development']
        self.assertEqual(s['reported_total_tokens'],100)
        self.assertEqual(s['unknown_completed_attempts'],1)
        with self.assertRaises(BudgetExceeded):self.reserve()
    def test_legacy_grant_receives_default_without_mutating_record(self):
        old={'event':'grant','grant_id':'dev','phase':'development','max_calls':24,'run_prefix':str(self.root),'phase_limit':24}
        self.ledger.path.write_text(json.dumps(old)+'\n')
        before=self.ledger.path.read_bytes()
        self.assertEqual(self.grant(),old)
        self.assertEqual(before,self.ledger.path.read_bytes())
        self.finish(399_990,10)
        with self.assertRaises(BudgetExceeded):self.reserve()
        self.assertEqual(self.ledger.summary()['tokens_by_phase']['development']['phase_limit_tokens'],400_000)
    def test_phase_separation_and_formal_default(self):
        self.grant()
        for _ in range(3):self.finish(status='failed')
        grant=self.ledger.grant('formal','formal',10,str(self.root),phase_limit=10)
        self.assertEqual(grant['phase_limit_tokens'],3_000_000)
        cid=self.reserve('formal','formal')
        self.ledger.finish(cid,'success',{'usage':{'input_tokens':3_000_000,'output_tokens':0}})
        with self.assertRaises(BudgetExceeded):self.reserve('formal','formal')
    def test_token_and_call_phase_limits_stay_immutable(self):
        self.ledger.grant('formal','formal',10,str(self.root),phase_limit=10,phase_limit_tokens=100)
        with self.assertRaises(ValueError):self.ledger.grant('second','formal',10,str(self.root),phase_limit=11,phase_limit_tokens=100)
        with self.assertRaises(ValueError):self.ledger.grant('second','formal',10,str(self.root),phase_limit=10,phase_limit_tokens=101)
        with self.assertRaises(ValueError):self.ledger.grant('formal','formal',10,str(self.root),phase_limit=10,phase_limit_tokens=101)
    def test_invalid_token_threshold_rejected(self):
        for threshold in (0,-1,True,1.5,400_001):
            with self.assertRaises(ValueError):self.grant(threshold)
    def test_solver_finishes_do_not_count_as_unknown_model_usage(self):
        self.grant()
        self.ledger.grant_solver('solver','development',10,str(self.root))
        for _ in range(4):
            cid=self.ledger.reserve_solver(phase='development',run_id=str(self.root),grant_id='solver',requested_seconds=1)
            self.ledger.finish(cid,'failed',{})
        self.reserve()
        self.assertEqual(self.ledger.summary()['tokens_by_phase']['development']['unknown_completed_attempts'],0)
    def test_oversized_prompt_rejected_before_reserve_or_process(self):
        config=ModelConfig(ledger_path=str(self.ledger.path))
        output=self.root/'oversized'
        with patch('src.agents.model_transport.BudgetLedger.reserve') as reserve, patch('src.agents.model_transport.subprocess.Popen') as popen:
            with self.assertRaises(PromptTooLarge):call_model('汉'*(PROMPT_CHARACTER_LIMIT+1),{},output,config)
            reserve.assert_not_called();popen.assert_not_called()
        self.assertFalse(output.exists());self.assertFalse(self.ledger.path.exists())
    def test_exact_character_limit_reaches_admission_not_process(self):
        config=ModelConfig(ledger_path=str(self.ledger.path))
        with patch('src.agents.model_transport.BudgetLedger.reserve',side_effect=BudgetExceeded('unit admission stop')) as reserve, patch('src.agents.model_transport.subprocess.Popen') as popen:
            with self.assertRaisesRegex(BudgetExceeded,'unit admission stop'):
                call_model('汉'*PROMPT_CHARACTER_LIMIT,{},self.root/'boundary',config)
            reserve.assert_called_once();popen.assert_not_called()
    def test_offline_resume_is_not_a_fresh_prompt_admission(self):
        config=ModelConfig(ledger_path=str(self.ledger.path));prompt='x'*(PROMPT_CHARACTER_LIMIT+1);schema={}
        schema_text=json.dumps(schema,ensure_ascii=False,indent=2)+'\n'
        fingerprint=hashlib.sha256((prompt+'\n'+schema_text+'\n'+json.dumps(dataclasses.asdict(config),sort_keys=True)).encode()).hexdigest()
        directory=self.root/'historical';directory.mkdir()
        record={'request_fingerprint':fingerprint,'status':'historical-unit-fixture'}
        (directory/'result.json').write_text(json.dumps(record))
        with patch('src.agents.model_transport.BudgetLedger.reserve') as reserve, patch('src.agents.model_transport.subprocess.Popen') as popen:
            self.assertEqual(call_model(prompt,schema,directory,config,resume=True),record)
            reserve.assert_not_called();popen.assert_not_called()

if __name__=='__main__':unittest.main()
