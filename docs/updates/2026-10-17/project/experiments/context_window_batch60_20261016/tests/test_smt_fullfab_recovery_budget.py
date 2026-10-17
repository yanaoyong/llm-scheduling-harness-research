"""Recovery accounting on isolated temporary ledgers only."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab.budget import BudgetLedger, BudgetExceeded
from src.smt_fullfab.controller_recovery import prepare_B_recovery, _inventory
from src.smt_fullfab.controller_audit import _audit_ledger_admission
from tests.test_smt_fullfab_page_recovery import make_fixture
from tests.test_smt_fullfab_controller_audit import write


class RecoveryBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='smt_fullfab_recovery_budget_');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.parent,self.ledger_path=make_fixture(self.root)
        self.package=self.root/'prepared.json'
        with patch('src.smt_fullfab.controller_recovery._verify_cold_checkpoint',return_value={'valid':True,'simulation_seconds':0}):
            prepared=prepare_B_recovery(self.parent,self.package,self.ledger_path)
        self.assertEqual(prepared['status'],'prepared',prepared)
        self.ledger=BudgetLedger(self.ledger_path)
        self.segment=self.parent.with_name(self.parent.name+'__recovery_001')
        self.root_patch=patch('src.smt_fullfab.budget.ROOT',self.root);self.root_patch.start();self.addCleanup(self.root_patch.stop)

    def register(self):
        return self.ledger.register_recovery_segment(str(self.parent),str(self.segment),self.package)

    def reserve(self,index=2,timeout=180):
        return self.ledger.reserve(phase='stage2_research',run_id=str(self.segment/f'model_{index:03d}'),grant_id='smt-fullfab-stage2-probe-v1',
            metadata={'model':'gpt-6-astra','reasoning_effort':'medium','timeout_seconds':timeout,
                      'authorization_context':{'purpose':'B','arm':'B','scenario':1901,'window_seconds':3600}})

    def close(self,mapping,wall=3):
        self.segment.mkdir(exist_ok=True)
        own=[r['call_id'] for r in self.rows() if r.get('event')=='reserve' and Path(r['run_id']).parent==self.segment]
        result={k:mapping[k] for k in ('parent_run_id','segment_run_id','recovery_segment_id','registration_id')}
        result.update(status='failed',full_window_completed=False,wall_seconds=wall,simulation_seconds=0,model_calls=len(own),model_call_ids=own)
        write(self.segment/'result.json',result)
        return self.ledger.report_recovery_segment_finish(str(self.segment),self.segment/'result.json')

    def rows(self):return [json.loads(line) for line in self.ledger_path.read_text().splitlines()]

    def test_append_binding_keeps_original_parent_and_allowance(self):
        before=self.ledger_path.read_bytes();parent=_inventory(self.parent)
        mapping=self.register()
        self.assertTrue(self.ledger_path.read_bytes().startswith(before));self.assertEqual(_inventory(self.parent),parent)
        self.assertEqual(mapping['inherited']['model_attempts'],2)
        self.assertEqual(mapping['inherited']['unknown_usage_call_ids'],['synthetic-call-1'])
        self.assertEqual(mapping['remaining']['runner_wall_seconds'],7190)
        self.assertEqual(self.register(),mapping)
        self.assertEqual(sum(r['event']=='stage_run_registered' for r in self.rows()),1)
        self.assertEqual(sum(r['event']=='recovery_segment_registered' for r in self.rows()),1)
        self.assertEqual(self.ledger.stage_registration(str(self.segment)),mapping['original_registration'])

    def test_segment_calls_share_original_account_without_erasing_unknown(self):
        mapping=self.register();self.segment.mkdir()
        cid=self.reserve();self.ledger.finish(cid,'success',{'usage':{'input_tokens':5,'output_tokens':7},'duration_seconds':1})
        parent,segment=self.ledger.summary(str(self.parent)),self.ledger.summary(str(self.segment))
        self.assertEqual(parent,segment);self.assertEqual(parent['attempts'],3)
        self.assertEqual(parent['reported_input_output_tokens'],30);self.assertEqual(parent['unknown_completed'],['synthetic-call-1'])
        row=next(r for r in self.rows() if r.get('event')=='reserve' and r['call_id']==cid)
        self.assertEqual(row['registration_id'],mapping['registration_id']);self.assertEqual(row['run_account_before']['attempts'],2)
        self.assertEqual(row['recovery_segment_id'],mapping['recovery_segment_id'])
        self.assertEqual(self.ledger.solver_remaining_seconds('B',str(self.segment)),0)

    def test_finish_preserves_cost_but_second_segment_needs_new_accepted_prefix(self):
        mapping=self.register();self.segment.mkdir();cid=self.reserve()
        self.ledger.finish(cid,'failed',{'usage':{'input_tokens':None,'output_tokens':None},'duration_seconds':2})
        closed=self.close(mapping,wall=4)
        self.assertEqual(self.ledger.report_recovery_segment_finish(str(self.segment),self.segment/'result.json'),closed)
        self.assertEqual(json.loads((self.parent/'result.json').read_text())['status'],'failed')
        summary=self.ledger.summary(str(self.parent));self.assertEqual(summary['runner_wall_seconds'],14)
        self.assertEqual(summary['model_active_seconds'],4)
        self.assertEqual(summary['open_recovery_segments'],[])
        next_segment=self.parent.with_name(self.parent.name+'__recovery_002')
        with self.assertRaisesRegex(ValueError,'accepted-prefix chain'):
            self.ledger.register_recovery_segment(str(self.parent),str(next_segment),self.package)
        self.assertEqual(summary['attempts'],3)
        self.assertEqual(summary['unknown_completed'],['synthetic-call-1',cid])
        self.assertLess(summary['remaining_log_bytes'],mapping['remaining']['log_bytes'])

    def test_pending_or_open_segment_cannot_spawn_another(self):
        self.register();self.segment.mkdir();cid=self.reserve()
        second=self.parent.with_name(self.parent.name+'__recovery_002')
        with self.assertRaises(BudgetExceeded):self.ledger.register_recovery_segment(str(self.parent),str(second),self.package)
        self.ledger.finish(cid,'failed',{'usage':{},'duration_seconds':1})
        with self.assertRaises(BudgetExceeded):self.ledger.register_recovery_segment(str(self.parent),str(second),self.package)

    def test_close_requires_all_attempts_finished_and_exact_count(self):
        mapping=self.register();self.segment.mkdir();cid=self.reserve()
        with self.assertRaises(BudgetExceeded):self.close(mapping)
        self.ledger.finish(cid,'failed',{'usage':{},'duration_seconds':1})
        path=self.segment/'result.json';value=json.loads(path.read_text());value['model_calls']=0;write(path,value)
        with self.assertRaisesRegex(ValueError,'omits attempts'):self.ledger.report_recovery_segment_finish(str(self.segment),path)

    def test_cannot_reset_resources_using_fresh_stage_registration(self):
        with self.assertRaisesRegex(ValueError,'fresh allowance'):
            self.ledger.register_stage_run(str(self.segment),'B',1901,3600,0,7200,1000000)

    def test_parent_and_closed_segment_cannot_reserve_new_calls(self):
        mapping=self.register();self.segment.mkdir();self.close(mapping)
        with self.assertRaises(BudgetExceeded):self.reserve()
        self.segment=self.parent
        with self.assertRaises(BudgetExceeded):self.reserve(index=9)

    def test_package_or_parent_mutation_is_rejected(self):
        package=json.loads(self.package.read_text());package['remaining']['runner_wall_seconds']=999999;write(self.package,package)
        with self.assertRaisesRegex(ValueError,'intact prepared'):self.register()

    def test_original_byte_prefix_is_required(self):
        content=self.ledger_path.read_text();self.ledger_path.write_text(content.replace('synthetic-call-1','synthetic-call-X'))
        with self.assertRaisesRegex(ValueError,'byte prefix'):self.register()

    def test_segment_bytes_are_counted_at_each_reservation(self):
        self.register();self.segment.mkdir();(self.segment/'large.bin').write_bytes(b'x'*1000001)
        with self.assertRaisesRegex(BudgetExceeded,'log allowance'):self.reserve()

    def test_closed_result_cannot_be_replaced(self):
        mapping=self.register();self.segment.mkdir();self.close(mapping)
        result=json.loads((self.segment/'result.json').read_text());result['wall_seconds']=1;write(self.segment/'result.json',result)
        with self.assertRaisesRegex(ValueError,'changed'):self.ledger.summary(str(self.segment))

    def test_mapping_does_not_admit_pre_mapping_attempt(self):
        with self.assertRaisesRegex(BudgetExceeded,'prior immutable'):self.reserve()

    def test_independent_ledger_replay_binds_mapping_only_after_its_event(self):
        m=self.register();self.segment.mkdir();cid=self.reserve()
        self.ledger.finish(cid,'success',{'usage':{'input_tokens':1,'output_tokens':2},'duration_seconds':1})
        self.close(m)
        rows=self.rows();approval=rows[0]['approval']
        audited=_audit_ledger_admission(rows,approval)
        self.assertEqual(audited['errors'],[],audited)
        moved=copy.deepcopy(rows);index=next(i for i,r in enumerate(moved) if r['event']=='recovery_segment_registered')
        m=moved.pop(index);moved.append(m)
        self.assertTrue(_audit_ledger_admission(moved,approval)['errors'])

    def test_finalization_adds_audit_wall_and_exact_acceptance_log_bytes(self):
        mapping=self.register();self.segment.mkdir();closed=self.close(mapping,wall=3)
        write(self.segment/'recovery_audit.json',{'valid':True,'successful_full_window':False})
        acceptance={k:mapping[k] for k in ('parent_run_id','segment_run_id','registration_id','recovery_segment_id')}
        acceptance.update(result_sha256=closed['result_sha256'],recovery_audit_sha256=hashlib.sha256((self.segment/'recovery_audit.json').read_bytes()).hexdigest(),
            segment_final_wall_seconds=5,cumulative_final_wall_seconds=15,cumulative_log_bytes_including_acceptance=0,
            resource_overrun=False,accepted=False,successful_full_window=False,status='failed')
        for _ in range(10):
            write(self.segment/'acceptance.json',acceptance)
            count=mapping['inherited']['log_bytes']+sum(v['bytes'] for v in _inventory(self.segment).values())
            if count==acceptance['cumulative_log_bytes_including_acceptance']:break
            acceptance['cumulative_log_bytes_including_acceptance']=count
        final=self.ledger.report_recovery_segment_finalization(str(self.segment),self.segment/'acceptance.json')
        self.assertEqual(final['segment_final_wall_seconds'],5)
        self.assertEqual(self.ledger.summary(str(self.segment))['runner_wall_seconds'],15)
        self.assertEqual(self.ledger.report_recovery_segment_finalization(str(self.segment),self.segment/'acceptance.json'),final)
        replay=_audit_ledger_admission(self.rows(),self.rows()[0]['approval']);self.assertEqual(replay['errors'],[],replay)
        acceptance['accepted']=True;write(self.segment/'acceptance.json',acceptance)
        with self.assertRaisesRegex(ValueError,'changed'):
            self.ledger.report_recovery_segment_finalization(str(self.segment),self.segment/'acceptance.json')


if __name__=='__main__':unittest.main()
