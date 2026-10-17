import json
from pathlib import Path
import tempfile
import unittest

from src.smt_fullfab.budget import ROOT, BudgetExceeded, BudgetLedger


class ConstructorBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='smt_fullfab_constructor_')
        self.addCleanup(self.temp.cleanup)
        self.ledger=BudgetLedger(Path(self.temp.name)/'ledger.jsonl')
        self.approval=json.loads((ROOT/'configs/smt_fullfab/stage2_probe.approved.json').read_text())
        self.ledger.approve(self.approval)
        self.ledger.approve_research_limit_waiver(json.loads((ROOT/'configs/smt_fullfab/research_limit_waiver.approved.json').read_text()))
        self.root=ROOT/'runs/smt_fullfab_stage2'/Path(self.temp.name).name
        self.registration=self.ledger.register_stage_run(str(self.root),'C',1901,3600,60,200,1000000)
        self.index=0

    def model(self,timeout=180,finish=True,duration=1):
        index=self.index;self.index+=1
        cid=self.ledger.reserve(phase='stage2_research',run_id=str(self.root/f'model_{index:03d}'),
            grant_id=self.approval['budget_id'],metadata={'model':'gpt-6-astra','reasoning_effort':'medium','timeout_seconds':timeout,
            'authorization_context':{'purpose':'C','arm':'C','scenario':1901,'window_seconds':3600}})
        if finish:self.ledger.finish(cid,'success',{'duration_seconds':duration,'usage':{'input_tokens':1,'output_tokens':1}})
        return cid,index

    def construct(self,source=None,seconds=5,**changes):
        cid,index=source or self.model()
        metadata={'model_call_id':cid,'model_index':index,'plan_index':0,'problem_sha256':'a'*64,
            'method':'constructive','max_candidate_evaluations':250000,'max_slots_per_machine':4,
            'actual_constructor_module':'src.smt_fullfab.constructive_tool','actual_constructor_function':'solve_constructive_plan'}
        metadata.update(changes)
        return self.ledger.reserve_constructor(arm='C',run_id=str(self.root),requested_seconds=seconds,metadata=metadata)

    def finish(self,cid,duration=4,status='success'):
        return self.ledger.finish_constructor(cid,status,{'duration_seconds':duration,'solver_status':'FEASIBLE_HEURISTIC' if status=='success' else 'CONSTRUCTOR_EXCEPTION','constructor_result_sha256':'b'*64})

    def test_constructor_is_measured_separately_without_consuming_cp(self):
        cid=self.construct();self.finish(cid)
        s=self.ledger.summary(str(self.root))
        self.assertEqual((s['attempts'],s['constructor_calls'],s['constructor_requested_seconds'],s['constructor_active_seconds'],s['active_execution_seconds']),(1,1,5,4,5))
        self.assertEqual(self.ledger.solver_remaining_seconds('C',str(self.root)),60)
        self.assertEqual(self.ledger.constructor_remaining_seconds('C',str(self.root)),195)
        self.assertEqual(s['pending_constructor_calls'],[])

    def test_pending_constructor_blocks_all_admission_and_is_not_retried(self):
        source=self.model();cid=self.construct(source)
        before=self.ledger.path.read_bytes()
        for action in (lambda:self.model(),lambda:self.construct(source),lambda:self.ledger.reserve_solver(arm='C',run_id=str(self.root),requested_seconds=1)):
            with self.assertRaises(BudgetExceeded):action()
        self.assertEqual(before,self.ledger.path.read_bytes())
        self.assertEqual(self.ledger.summary()['pending_constructor_calls'],[cid])
        self.finish(cid,status='failed')
        with self.assertRaises(ValueError):self.construct(source)
        self.construct()  # a new explicit model choice is permitted

    def test_constructor_actual_overrun_is_retained_and_stops_future_calls(self):
        source=self.model(duration=195)
        cid=self.construct(source,seconds=5);self.finish(cid,duration=7,status='failed')
        self.assertEqual(self.ledger.summary(str(self.root))['active_execution_seconds'],202)
        self.assertEqual(self.ledger.constructor_remaining_seconds('C',str(self.root)),0)
        with self.assertRaises(BudgetExceeded):self.model(timeout=1)
        with self.assertRaises(BudgetExceeded):self.ledger.reserve_solver(arm='C',run_id=str(self.root),requested_seconds=1)

    def test_model_timeout_includes_completed_constructor_time(self):
        cid=self.construct(self.model(duration=190));self.finish(cid,duration=4)
        with self.assertRaises(BudgetExceeded):self.model(timeout=7)
        self.model(timeout=6)

    def test_source_and_shared_tool_scope_are_required(self):
        source=self.model()
        for changes in ({'method':'global'},{'actual_constructor_module':'other'},{'actual_constructor_function':'other'},
            {'max_candidate_evaluations':250001},{'max_slots_per_machine':9},{'model_index':True},
            {'problem_sha256':'invalid'},{'model_call_id':'unknown'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.construct(source,**changes)
        for seconds in (0,6,float('nan'),True):
            with self.subTest(seconds=seconds),self.assertRaises(BudgetExceeded):self.construct(source,seconds=seconds)
        with self.assertRaises(BudgetExceeded):self.ledger.reserve_constructor(arm='B',run_id=str(self.root),requested_seconds=1,metadata={})

    def test_constructor_cannot_use_an_unfinished_model(self):
        with self.assertRaises(BudgetExceeded):self.construct(self.model(finish=False))

    def test_finish_is_unique_and_cannot_hide_duration(self):
        cid=self.construct()
        for duration in (None,-1,float('nan'),True):
            with self.subTest(duration=duration),self.assertRaises(ValueError):self.finish(cid,duration)
        self.finish(cid)
        with self.assertRaises(ValueError):self.finish(cid)
        with self.assertRaises(ValueError):self.finish('unreserved')

    def test_new_run_is_separate_without_resetting_original_account(self):
        cid=self.construct();self.finish(cid)
        second=self.root.with_name(self.root.name+'_other')
        self.ledger.register_stage_run(str(second),'C',1901,3600,60,200,1000000)
        self.assertEqual(self.ledger.summary(str(second))['constructor_active_seconds'],0)
        self.assertEqual(self.ledger.summary(str(self.root))['constructor_active_seconds'],4)
        self.assertEqual(self.ledger.summary()['constructor_active_seconds'],4)


if __name__=='__main__':unittest.main()
