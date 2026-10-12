"""Capacity/control regressions: synthetic environment, no model or factory."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from src.smt_fullfab import runner

spec=importlib.util.spec_from_file_location('capacity_hybrid_fixtures',Path(__file__).with_name('test_smt_fullfab_hybrid.py'))
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)


class CapacityTests(unittest.TestCase):
    setUp=fixtures.HybridRunnerTests.setUp
    run_case=fixtures.HybridRunnerTests.run_case
    fake_periodic=staticmethod(fixtures.HybridRunnerTests.fake_periodic)
    inherited_checkpoint=fixtures.HybridRunnerTests.inherited_checkpoint

    def test_defaults_preserve_old_config_and_recovery_limit_keys(self):
        result,out=self.run_case('defaults')
        self.assertEqual(result['status'],'success')
        for key in ('max_trace_bytes','audit_mode','snapshot_mode'):
            self.assertNotIn(key,result['config'])
        saved=json.loads((out/'checkpoint_resources.json').read_text())
        self.assertEqual(set(saved['hybrid_resource_limits']),{'runner_wall_seconds','max_plans','max_log_bytes'})

    def test_stream_modes_bind_receipt_and_record_explicit_recovery_limits(self):
        module=types.ModuleType('src.smt_fullfab.stream_snapshot')
        calls=[]
        def snapshot(env,path):
            calls.append(str(path));env.snapshot(path)
        module.write_snapshot=snapshot
        summary={'valid':True,'metrics':{'weighted_tardy_lot_hours':2}}
        receipt={'path':'audit_bundle','manifest_sha256':'a'*64}
        with patch.dict(sys.modules,{module.__name__:module}),patch.object(runner,'stream_audit',return_value=(summary,receipt)) as audit:
            result,out=self.run_case('stream',max_trace_bytes=123456789,audit_mode='stream',snapshot_mode='stream')
        self.audit.assert_not_called();audit.assert_called_once()
        self.assertEqual(result['status'],'success')
        self.assertEqual(result['metrics'],summary['metrics'])
        self.assertEqual(result['audit_bundle'],receipt)
        self.assertEqual(len(calls),1)
        self.assertFalse((out/'audit.json').exists())
        limits=json.loads((out/'checkpoint_resources.json').read_text())['hybrid_resource_limits']
        for key in ('max_trace_bytes','audit_mode','snapshot_mode'):self.assertEqual(limits[key],result['config'][key])

    def test_resumed_run_cannot_enlarge_trace_cap_or_change_audit_method(self):
        path=self.inherited_checkpoint()
        for i,change in enumerate(({'max_trace_bytes':999999999},{'audit_mode':'stream'},{'snapshot_mode':'stream'})):
            result,_=self.run_case('resume_cap_'+str(i),snapshot_path=str(path),**change)
            self.assertEqual(result['status'],'failed')
            self.assertIn('resource limits differ',result['failure'])

    def test_last_terminal_event_cannot_evade_trace_limit(self):
        original=fixtures.SyntheticEnvironment.advance_plan
        def advance(env,until):
            result=original(env,until)
            if env.finished:
                with env.trace_path.open('a') as stream:stream.write('terminal crosses cap\n')
            return result
        with patch.object(fixtures.SyntheticEnvironment,'advance_plan',advance):
            result,out=self.run_case('terminal_cap',max_trace_bytes=10)
        self.assertTrue(result['full_window_completed'])
        self.assertEqual(result['status'],'failed')
        self.assertIn('final trace volume cap',result['failure'])
        self.assertTrue((out/'checkpoint.json').exists())

    def test_final_checkpoint_cost_is_charged_to_wall(self):
        clock=[0.0];original=fixtures.SyntheticEnvironment.snapshot
        def snapshot(env,path):original(env,path);clock[0]=2.0
        with patch.object(runner.time,'monotonic',side_effect=lambda:clock[0]),patch.object(fixtures.SyntheticEnvironment,'snapshot',snapshot):
            result,_=self.run_case('checkpoint_time',wall_seconds=1)
        self.assertEqual(result['status'],'failed')
        self.assertIn('final run wall budget',result['failure'])
        self.assertEqual(result['wall_seconds'],2)

    def test_snapshot_failure_preserves_terminal_result_and_partial_file(self):
        def snapshot(env,path):
            Path(path).write_text('partial evidence')
            raise OSError('disk fixture failure')
        with patch.object(fixtures.SyntheticEnvironment,'snapshot',snapshot):
            result,out=self.run_case('snapshot_failure')
        self.assertEqual(result['status'],'failed')
        self.assertIsNone(result['checkpoint'])
        self.assertIn('disk fixture failure',result['checkpoint_failure'])
        self.assertEqual((out/'checkpoint.json').read_text(),'partial evidence')
        self.assertTrue((out/'result.json').exists())

    def test_raw_response_cannot_overwrite_reserved_costs_or_keep_payload_in_summary(self):
        original=self.fake_periodic
        def response(*args,**kwargs):
            return {**original(*args,**kwargs),'requested_seconds':999,'planner_mode':'foreign','large_detail':['kept']*100}
        self.periodic.side_effect=response
        result,out=self.run_case('cost_summary')
        self.assertEqual(result['status'],'success')
        self.assertEqual(result['solver_requested_seconds'],4)
        saved=json.loads((out/'solver_00000.json').read_text())
        self.assertEqual(saved['large_detail'],['kept']*100)
        summary=runner.planner_cost_summary(saved)
        self.assertEqual(set(summary),{'wall_seconds','solve_wall_seconds','classical_construction_wall_seconds'})
        self.assertNotIn('plan',summary)

    def test_invalid_trace_limits_fail_before_claim_creation(self):
        for index,cap in enumerate((0,-1,True,1.5,'20')):
            with self.assertRaisesRegex(ValueError,'trace byte limit'):
                self.run_case('invalid_'+str(index),max_trace_bytes=cap)
        self.assertFalse((self.root/'runs').exists())

    def test_stream_audit_error_preserves_failed_result(self):
        with patch.object(runner,'stream_audit',side_effect=ValueError('source changed fixture')):
            result,out=self.run_case('bad_audit',audit_mode='stream')
        self.assertEqual(result['status'],'failed')
        self.assertIn('source changed',result['failure'])
        self.assertFalse(result['audit_valid'])
        self.assertTrue((out/'checkpoint.json').exists())

    def test_result_itself_is_counted_and_overrun_is_preserved_as_failure(self):
        cap=100000;original=runner.write_new
        def write(path,value):
            original(path,value)
            if path.name=='checkpoint_resources.json':
                current=sum(p.stat().st_size for p in path.parent.rglob('*') if p.is_file())
                (path.parent/'test_filler').write_bytes(b'x'*(cap-current-1))
        with patch.object(runner,'write_new',side_effect=write):
            result,out=self.run_case('result_bytes',max_log_bytes=cap)
        self.assertEqual(result['status'],'failed')
        self.assertIn('including result publication',result['failure'])
        actual=sum(p.stat().st_size for p in out.rglob('*') if p.is_file())
        self.assertGreater(actual,cap)
        self.assertEqual(result['cumulative_log_bytes_including_result'],actual)
        self.assertEqual(json.loads((out/'result.json').read_text()),result)


class AuditBindingTests(unittest.TestCase):
    def test_source_hash_and_complete_terminal_are_required_and_storage_rechecked(self):
        import hashlib
        import tempfile
        from src.smt_fullfab import stream_audit_bundle as bundle
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);path=out/'trace.jsonl';path.write_bytes(b'raw source\n')
            created={'report_sha256':'a'*64,'source_receipt':{'sha256':hashlib.sha256(path.read_bytes()).hexdigest()},'summary':{'valid':True,'metrics':{}}}
            checked={'storage_verified':True,'source_receipt':created['source_receipt'],'summary':created['summary']}
            with patch.object(bundle,'audit_to_bundle',return_value=created) as create,patch.object(bundle,'read_bundle',return_value=checked):
                result,receipt=runner.stream_audit(path,out,data_dir='fixture',window_start=0)
                self.assertEqual(create.call_args.kwargs['expected_source_sha256'],created['source_receipt']['sha256'])
                self.assertIs(create.call_args.kwargs['require_terminal'],True)
                self.assertEqual(receipt['manifest_sha256'],'a'*64)
                checked['source_receipt']={'sha256':'b'*64}
                with self.assertRaisesRegex(ValueError,'bundle differs'):
                    runner.stream_audit(path,out,data_dir='fixture',window_start=0)


if __name__=='__main__':unittest.main()
