"""Synthetic isolated accounting fixtures; never calls a model or real ledger."""
import json
from pathlib import Path
import tempfile
import unittest

from src.smt_fullfab.budget import BudgetLedger,BudgetExceeded,ROOT


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='smt_fullfab_test_')
        self.ledger=BudgetLedger(Path(self.temp.name)/'smt_fullfab.jsonl')
        self.approval={'authorization':'approved_by_user','budget_id':'synthetic-fixture-only','max_model_attempts':12,
                       'observed_input_output_token_admission_limit':100,'max_completed_unknown_usage':1,
                       'total_active_wall_seconds':100,'window_seconds':3600,
                       'allocation':{'B':5,'C':4,'channel_probe':1},'max_solver_requested_seconds_per_arm':60}
        self.ledger.approve(self.approval)

    def tearDown(self):self.temp.cleanup()

    def reserve(self,arm='B',window=3600):
        return self.ledger.reserve(phase='stage2_probe',run_id=str(ROOT/'runs/smt_fullfab_stage2/synthetic_fixture'),
                   grant_id='synthetic-fixture-only',metadata={'authorization_context':{'purpose':arm,'arm':arm,'window_seconds':window}})

    def finish(self,cid,amount=10):
        return self.ledger.finish(cid,'success',{'usage':{'input_tokens':amount,'output_tokens':0},'duration_seconds':1})

    def test_unknown_usage_stops_without_reclaiming_attempt(self):
        cid=self.reserve();self.ledger.finish(cid,'timeout',{'usage':{'input_tokens':None,'output_tokens':None},'duration_seconds':5})
        with self.assertRaises(BudgetExceeded):self.reserve('C')
        self.assertEqual(self.ledger.summary()['attempts'],1)

    def test_pending_reservation_blocks_concurrent_or_duplicate_retry(self):
        self.reserve()
        with self.assertRaises(BudgetExceeded):self.reserve('C')

    def test_cumulative_category_across_new_run_names(self):
        for _ in range(5):self.finish(self.reserve(),1)
        with self.assertRaises(BudgetExceeded):self.reserve()
        self.finish(self.reserve('C'),1)

    def test_observed_token_admission_threshold_includes_last_overshoot(self):
        self.finish(self.reserve(),110)
        with self.assertRaises(BudgetExceeded):self.reserve('C')
        self.assertEqual(self.ledger.summary()['reported_input_output_tokens'],110)

    def test_unapproved_window_and_old_ledger_rejected(self):
        with self.assertRaises(BudgetExceeded):self.reserve(window=28800)
        with self.assertRaises(ValueError):BudgetLedger(ROOT/'progress/model_ledger.jsonl')

    def test_solver_budget_cumulative_and_b_solver_forbidden(self):
        sid=self.ledger.reserve_solver(arm='C',run_id='synthetic',requested_seconds=40)
        self.ledger.finish_solver(sid,'failed',{'error':'synthetic failure'})
        with self.assertRaises(BudgetExceeded):self.ledger.reserve_solver(arm='C',run_id='another',requested_seconds=21)
        with self.assertRaises(BudgetExceeded):self.ledger.reserve_solver(arm='B',run_id='synthetic',requested_seconds=1)




class ScopedWaiverTests(unittest.TestCase):
    """Synthetic isolated C-only approval fixtures, never the real approved account."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='smt_fullfab_waiver_test_')
        self.ledger=BudgetLedger(Path(self.temp.name)/'smt_fullfab.jsonl')
        self.approval={'authorization':'approved_by_user','budget_id':'smt-fullfab-stage2-probe-v1',
            'model':'gpt-6-astra','max_model_attempts':12,
            'observed_input_output_token_admission_limit':240000,'max_completed_unknown_usage':1,
            'per_call_timeout_seconds':180,'total_active_wall_seconds':2700,
            'scenario':1701,'window_seconds':3600,
            'allocation':{'B':5,'C':4,'channel_probe':1,'reserved_recovery_or_revision':2},
            'max_solver_requested_seconds_per_arm':60}
        self.ledger.approve(self.approval)
        self.amendment={'amendment_id':'isolated-test-c-waiver-v1','budget_id':self.approval['budget_id'],
            'authorization':'approved_by_user','approval_text':'豁免次数与用量限制','allowed_purpose':'C',
            'waived_limits':['attempt_count','reported_tokens','unknown_usage_admission'],
            'scenario':1701,'window_seconds':3600}

    def tearDown(self):self.temp.cleanup()

    def reserve(self,arm='C',scenario=1701,window=3600,timeout=180,model='gpt-6-astra',phase='stage2_probe',call_id=None):
        return self.ledger.reserve(phase=phase,run_id=str(ROOT/'runs/smt_fullfab_stage2/synthetic_waiver_fixture'),
            grant_id=self.approval['budget_id'],call_id=call_id,
            metadata={'model':model,'timeout_seconds':timeout,
                'authorization_context':{'purpose':arm,'arm':arm,'scenario':scenario,'window_seconds':window}})

    def finish(self,cid,amount=10,duration=1,status='success'):
        return self.ledger.finish(cid,status,{'usage':{'input_tokens':amount,'output_tokens':0},'duration_seconds':duration})

    def unknown(self,arm='B',duration=180,call_id='544d0153-8b11-4193-b4e3-4461b3a2c178'):
        cid=self.reserve(arm=arm,call_id=call_id)
        self.ledger.finish(cid,'timeout',{'usage':{'input_tokens':None,'output_tokens':None},'duration_seconds':duration})
        return cid

    def test_default_disabled_and_exact_explicit_approval_required(self):
        self.unknown()
        self.assertIsNone(self.ledger.scoped_limit_waiver('C'))
        with self.assertRaisesRegex(BudgetExceeded,'unknown usage'):
            self.reserve()
        for change in ({'authorization':'proposed'},{'approval_text':''},{'approval_text':'批准四次'}):
            with self.assertRaises(ValueError):
                self.ledger.approve_scoped_limit_waiver({**self.amendment,**change})
        self.assertFalse(any(r['event']=='scoped_limit_waiver' for r in self.rows()))

    def rows(self):return [json.loads(line) for line in self.ledger.path.read_text().splitlines()]

    def test_append_only_anchors_original_unknown_without_rewriting_it(self):
        from src.smt_fullfab.budget import record_sha256
        cid=self.unknown();before=self.ledger.path.read_bytes();before_rows=self.rows()
        row=self.ledger.approve_scoped_limit_waiver(self.amendment)
        self.assertTrue(self.ledger.path.read_bytes().startswith(before))
        finish=next(r for r in before_rows if r['event']=='finish')
        self.assertEqual(row['unknown_finishes_at_approval'],{cid:record_sha256(finish)})
        self.assertEqual(self.rows()[:len(before_rows)],before_rows)
        self.assertEqual(self.ledger.summary()['unknown_completed'],[cid])
        self.assertIsNone(self.ledger.summary()['cost_usd'])
        self.assertEqual(self.ledger.scoped_limit_waiver('C'),self.amendment)
        read=self.ledger.scoped_limit_waiver('C');read['waived_limits'].append('pending')
        self.assertEqual(self.ledger.scoped_limit_waiver('C'),self.amendment)
        self.assertIsNone(self.ledger.scoped_limit_waiver('B'))

    def test_count_and_token_waiver_never_resets_cumulative_counter(self):
        cid=self.unknown()
        self.ledger.approve_scoped_limit_waiver(self.amendment)
        for _ in range(13):self.finish(self.reserve(),amount=20000)
        account=self.ledger.summary()
        self.assertEqual(account['attempts'],14)
        self.assertEqual(account['reported_input_output_tokens'],260000)
        self.assertEqual(account['model_active_seconds'],193)
        self.assertEqual(account['unknown_completed'],[cid])
        self.assertEqual(account['amendment_attempts'],{self.amendment['amendment_id']:13})
        amended=[r for r in self.rows() if r['event']=='reserve' and r.get('amendment_id')]
        self.assertEqual(len(amended),13)
        self.assertEqual(self.rows()[0]['approval'],self.approval)

    def test_future_unknown_is_preserved_and_only_c_admission_is_waived(self):
        old=self.unknown();self.ledger.approve_scoped_limit_waiver(self.amendment)
        later=self.unknown(arm='C',call_id='isolated-later-unknown')
        self.finish(self.reserve())
        self.assertEqual(self.ledger.summary()['unknown_completed'],[old,later])
        with self.assertRaises(BudgetExceeded):self.reserve('B')
        with self.assertRaises(BudgetExceeded):self.reserve('channel_probe')

    def test_pending_cannot_be_waived_or_automatically_retried(self):
        self.ledger.approve_scoped_limit_waiver(self.amendment)
        first=self.reserve()
        with self.assertRaisesRegex(BudgetExceeded,'pending'):
            self.reserve()
        self.assertEqual(self.ledger.summary()['pending'],[first])
        self.assertEqual(self.ledger.summary()['attempts'],1)

    def test_nonwaived_scope_model_and_timeout_stay_enforced(self):
        self.ledger.approve_scoped_limit_waiver(self.amendment)
        for params in ({'scenario':1702},{'scenario':True},{'window':28800},{'timeout':181},
                       {'timeout':None},{'timeout':float('nan')},{'timeout':True},
                       {'model':'different-model'},{'phase':'formal'}):
            with self.subTest(params=params), self.assertRaises(BudgetExceeded):self.reserve(**params)
        self.assertEqual(self.ledger.summary()['attempts'],0)

    def test_active_wall_budget_remains_cumulative_and_next_timeout_must_fit(self):
        self.ledger.approve_scoped_limit_waiver(self.amendment)
        self.finish(self.reserve(),duration=2690)
        with self.assertRaisesRegex(BudgetExceeded,'remaining active time'):
            self.reserve(timeout=11)
        self.finish(self.reserve(timeout=10),duration=10)
        with self.assertRaises(BudgetExceeded):self.reserve(timeout=1)
        self.assertEqual(self.ledger.summary()['model_active_seconds'],2700)

    def test_solver_60_second_cap_is_not_waived(self):
        self.ledger.approve_scoped_limit_waiver(self.amendment)
        sid=self.ledger.reserve_solver(arm='C',run_id='synthetic',requested_seconds=60)
        self.ledger.finish_solver(sid,'failed',{})
        with self.assertRaises(BudgetExceeded):self.ledger.reserve_solver(arm='C',run_id='synthetic2',requested_seconds=0.01)
        with self.assertRaises(BudgetExceeded):self.ledger.reserve_solver(arm='B',run_id='synthetic',requested_seconds=1)

    def test_scope_cannot_be_expanded_and_amendment_is_immutable(self):
        for change in ({'allowed_purpose':'B'},{'scenario':1702},{'window_seconds':86400},
                       {'budget_id':'another-budget'},{'waived_limits':['pending']},
                       {'waived_limits':['attempt_count','reported_tokens','unknown_usage_admission','time']},
                       {'amendment_id':self.approval['budget_id']},{'per_call_timeout_seconds':999}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.ledger.approve_scoped_limit_waiver({**self.amendment,**change})
        self.ledger.approve_scoped_limit_waiver(self.amendment)
        before=self.ledger.path.read_bytes()
        self.ledger.approve_scoped_limit_waiver(self.amendment)
        self.assertEqual(before,self.ledger.path.read_bytes())
        with self.assertRaisesRegex(ValueError,'immutable'):
            self.ledger.approve_scoped_limit_waiver({**self.amendment,'amendment_id':'new-id-cannot-reset'})

    def test_changed_original_approval_or_unknown_finish_is_detected(self):
        self.unknown();self.ledger.approve_scoped_limit_waiver(self.amendment)
        original=self.ledger.path.read_text()
        # Corruption injections occur only in this isolated temporary ledger.
        for kind in ('approval','finish'):
            rows=[json.loads(line) for line in original.splitlines()]
            target=next(r for r in rows if r['event']==kind)
            if kind=='approval':target['approval']['max_model_attempts']=999
            else:target['details']['usage']['input_tokens']=0
            self.ledger.path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            with self.subTest(kind=kind), self.assertRaises(ValueError):self.ledger.scoped_limit_waiver('C')
        self.ledger.path.write_text(original)


class ResearchWaiverTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='smt_fullfab_research_test_')
        self.addCleanup(self.temp.cleanup)
        self.ledger=BudgetLedger(Path(self.temp.name)/'smt_fullfab.jsonl')
        self.approval=json.loads((ROOT/'configs/smt_fullfab/stage2_probe.approved.json').read_text())
        self.amendment=json.loads((ROOT/'configs/smt_fullfab/research_limit_waiver.approved.json').read_text())
        self.ledger.approve(self.approval)
        self.root=ROOT/'runs/smt_fullfab_stage2'/('synthetic_'+Path(self.temp.name).name)

    def approve(self):return self.ledger.approve_research_limit_waiver(self.amendment)

    def register(self,arm='C',**changes):
        values={'run_id':str(self.root),'arm':arm,'scenario':1901,'window_seconds':3600,
                'solver_seconds':120 if arm=='C' else 0,'wall_seconds':5000,'max_log_bytes':1000000}
        values.update(changes);return self.ledger.register_stage_run(**values)

    def reserve(self,arm='C',**changes):
        context={'purpose':arm,'arm':arm,'scenario':1901,'window_seconds':3600}
        metadata={'model':'gpt-6-astra','reasoning_effort':'medium','timeout_seconds':180,'authorization_context':context}
        metadata.update(changes)
        return self.ledger.reserve(phase='stage2_research',run_id=str(self.root/'model_000'),
            grant_id=self.approval['budget_id'],metadata=metadata)

    def finish(self,cid,*,duration=1,unknown=False):
        return self.ledger.finish(cid,'failed' if unknown else 'success',
            {'usage':{'input_tokens':None,'output_tokens':None} if unknown else {'input_tokens':250000,'output_tokens':10000},'duration_seconds':duration})

    def test_explicit_approval_and_registration_required(self):
        with self.assertRaises(BudgetExceeded):self.register()
        with self.assertRaises(ValueError):self.ledger.approve_research_limit_waiver({**self.amendment,'authorization':'proposed'})
        self.approve()
        with self.assertRaises(BudgetExceeded):self.reserve()
        self.register();self.finish(self.reserve())

    def test_append_only_global_counters_and_unknown_usage_survive(self):
        old=self.ledger.reserve(phase='stage2_probe',run_id=str(self.root.parent/'old_synthetic'/'model_000'),grant_id=self.approval['budget_id'],
            metadata={'authorization_context':{'purpose':'B','arm':'B','window_seconds':3600}})
        self.finish(old,duration=2701,unknown=True)
        before=self.ledger.path.read_bytes();self.approve();self.assertTrue(self.ledger.path.read_bytes().startswith(before))
        self.register(arm='B')
        for _ in range(14):self.finish(self.reserve(arm='B'))
        account=self.ledger.summary()
        self.assertEqual(account['attempts'],15);self.assertEqual(account['unknown_completed'],[old])
        self.assertEqual(account['model_active_seconds'],2715);self.assertGreater(account['reported_input_output_tokens'],240000)
        self.assertEqual(self.ledger.summary(run_id=str(self.root))['attempts'],14)
        self.assertIsNone(account['cost_usd'])

    def test_registered_solver_allowance_is_independent_and_not_a_legacy_reset(self):
        old=self.ledger.reserve_solver(arm='C',run_id='old_synthetic',requested_seconds=60)
        self.ledger.finish_solver(old,'failed',{})
        self.approve();registration=self.register()
        self.assertEqual(self.ledger.solver_remaining_seconds('C'),0)
        self.assertEqual(self.ledger.solver_remaining_seconds('C',str(self.root)),120)
        for seconds in (60,60):
            sid=self.ledger.reserve_solver(arm='C',run_id=str(self.root),requested_seconds=seconds)
            self.ledger.finish_solver(sid,'failed',{})
        self.assertEqual(self.ledger.solver_remaining_seconds('C',str(self.root)),0)
        self.assertEqual(self.register(),registration)
        with self.assertRaises(ValueError):self.register(solver_seconds=180)
        with self.assertRaises(BudgetExceeded):self.ledger.reserve_solver(arm='C',run_id=str(self.root),requested_seconds=1)
        with self.assertRaises(BudgetExceeded):self.ledger.reserve_solver(arm='B',run_id=str(self.root),requested_seconds=1)

    def test_model_and_solver_pending_still_block_admission(self):
        self.approve();self.register();cid=self.reserve()
        with self.assertRaises(BudgetExceeded):self.reserve()
        with self.assertRaises(BudgetExceeded):self.ledger.reserve_solver(arm='C',run_id=str(self.root),requested_seconds=1)
        self.finish(cid);sid=self.ledger.reserve_solver(arm='C',run_id=str(self.root),requested_seconds=1)
        with self.assertRaises(BudgetExceeded):self.reserve()
        self.ledger.finish_solver(sid,'failed',{});self.finish(self.reserve())

    def test_per_run_time_and_model_scope_not_waived(self):
        self.approve();self.register(wall_seconds=200)
        self.finish(self.reserve(),duration=190)
        for changes in ({'timeout_seconds':11},{'timeout_seconds':181},{'timeout_seconds':float('nan')},
                        {'model':'other'},{'reasoning_effort':'high'},
                        {'authorization_context':{'purpose':'C','arm':'C','scenario':1902,'window_seconds':3600}}):
            with self.subTest(changes=changes),self.assertRaises(BudgetExceeded):self.reserve(**changes)
        self.finish(self.reserve(timeout_seconds=10),duration=10)
        with self.assertRaises(BudgetExceeded):self.reserve(timeout_seconds=1)

    def test_only_registered_1_8_24_hour_development_windows(self):
        self.approve()
        for invalid in (0,7200,604800,True):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):self.register(window_seconds=invalid)
        for valid in (3600,28800,86400):
            self.register(run_id=str(self.root.parent/(self.root.name+str(valid))),window_seconds=valid)

    def test_registration_cannot_be_retroactive(self):
        self.ledger.reserve_solver(arm='C',run_id=str(self.root),requested_seconds=1)
        self.approve()
        with self.assertRaisesRegex(ValueError,'previously used'):self.register()

    def test_prior_history_mutation_and_waiver_replacement_rejected(self):
        self.approve();before=self.ledger.path.read_bytes();self.approve();self.assertEqual(before,self.ledger.path.read_bytes())
        with self.assertRaises(ValueError):self.ledger.approve_research_limit_waiver({**self.amendment,'amendment_id':'replacement'})
        rows=[json.loads(line) for line in self.ledger.path.read_text().splitlines()]
        rows[0]['approval']['max_model_attempts']=999
        self.ledger.path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
        with self.assertRaises(ValueError):self.ledger.research_limit_waiver()


if __name__=='__main__':
    unittest.main()
