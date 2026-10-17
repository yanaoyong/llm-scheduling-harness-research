"""Tiny static-authored status fixtures. No real ledger/model/factory or audit.

The original frozen gate and lifecycle reader are explicit stubs in closure
fixtures, except GS1 cases use the real gates' final-ledger reader on temporary
synthetic files. A separate tiny module fixture tests the isolated frozen import
path. These tests do not claim actual C/B experiment acceptance.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from src.smt_fullfab import guarded_status as s


def raw(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()


def put(path, value, *, binary=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = value if binary else raw(value)
    path.write_bytes(data)
    return s.sha(data)


def identity(value):
    value.pop('identity', None)
    value['identity'] = s.digest(value)
    return value


class Fixture:
    def __init__(self, root, run_id='C_1701_8h_stream_v1'):
        self.root, self.run_id = root, run_id
        self.spec = deepcopy(s.RUNS[run_id]); self.spec['session_id'] = 99
        self.folder = root / 'runs/smt_fullfab_stage2' / run_id
        self.campaign = root / self.spec['campaign_area'] / run_id
        self.host = root / self.spec['host_area'] / run_id
        self.obs = root / self.spec['observation']
        self.frozen = self.campaign / 'frozen'
        self.source = self.frozen / self.spec['host_source']
        self.result = {'config': {'run_id':run_id, 'arm':self.spec['arm'], 'seed':1701,
                       'seconds':self.spec['seconds'], 'solver_budget_seconds':0},
            'status':'success' if self.spec['arm'] == 'C' else 'completed', 'accepted':False,
            'failure':None, 'audit_valid':True, 'simulation_seconds':self.spec['seconds'],
            'full_window_completed':True, 'terminal_trace_binding_valid':True,
            'acceptance_authority':'external_frozen_gate', 'launch_authority_scope':'controller_does_not_self_authorize',
            'real_C8_launch_authorized':False, 'direct_public_execution_enabled':False,
            'model_calls':7, 'plans_committed':2, 'plans':2, 'solver_requested_seconds':2.0,
            'wall_seconds':10.0, 'end_to_end_wall_seconds':10.0, 'delta_attribution_valid':True,
            'finalization_errors':[], 'metrics':{'throughput_lots':1},
            'schema':'smt-fullfab-B-delta-controller-v4-result'}
        result_sha = put(self.folder/'result.json', self.result)
        self.registration_id = 'fixture-registration-1'
        self.call_id = 'fixture-call-1'
        self.ledger_rows = [
            {'event':'stage_run_registered','registration':{'run_id':str(self.folder),
             'registration_id':self.registration_id}},
            {'event':'reserve','run_id':str(self.folder),'registration_id':self.registration_id,'call_id':self.call_id},
            {'event':'finish','call_id':self.call_id,'status':'success'}]
        ledger_raw = b''.join(raw(row) for row in self.ledger_rows)
        self.live_ledger = root / ('temporary_ledger_'+run_id+'.jsonl')
        put(self.live_ledger, ledger_raw, binary=True)
        self.ledger_sha = put(self.folder/'ledger_final.jsonl', ledger_raw, binary=True)
        self.proof = {'valid':True,'ledger_sha256':self.ledger_sha,'registration_id':self.registration_id}
        self.proof_sha = put(self.campaign/'verification_payload.json', self.proof)
        inputs = {}
        for name in ('src/smt_fullfab/'+self.spec['gate']+'.py', 'src/smt_fullfab/model_process_guard.py', self.spec['host_source']):
            inputs[name] = put(self.frozen/name, b'# tiny immutable source fixture\n', binary=True)
        self.manifest = identity({'run_id':run_id, 'origin_root':str(root), 'output_directory':str(self.folder),
            'prepare_wall_seconds':1.0, 'launcher_executable':'/fixture/python', 'frozen_input_sha256':inputs,
            'actual_ledger_path':str(self.live_ledger)})
        manifest_sha = put(self.campaign/'manifest.json', self.manifest)
        prep = {'campaign':str(self.campaign), 'manifest_sha256':manifest_sha,
                'root_preparation_and_immediate_verification_wall_seconds':1.5}
        self.spec['preparation_sha256'] = put(root/self.spec['preparation'], prep)
        command = ['/usr/bin/time','-p','/fixture/python','-I','-B',str(self.source),
                   '--campaign',str(self.campaign),'--manifest-sha256',manifest_sha]
        self.launch = {'command':command, 'manifest_sha256':manifest_sha, 'actual_wait_required':True,
                       'automatic_retry':False, 'one_attempt':True}
        self.spec['launch_request_sha256'] = put(self.obs/'request.json', self.launch)
        self.acceptance = {'accepted':True, 'status':'success', 'runner_result_sha256':result_sha,
                           'evidence_sha256':{'run/result.json':result_sha,'run/ledger_final.jsonl':self.ledger_sha,
                                             'campaign/verification_payload.json':self.proof_sha}}
        self.acceptance_sha = put(self.campaign/'acceptance.json', self.acceptance)
        self.verified = {'valid':True,'accepted':True,'acceptance_sha256':self.acceptance_sha,
                         'status':'success','semantic_audits_rerun':False,'errors':[]}
        child_command = ['/fixture/python','-I','-B',str(self.source),'--gate-child',
                         '--campaign',str(self.campaign),'--manifest-sha256',manifest_sha]
        request = {'schema':self.spec['host_schema']+'-request','campaign':str(self.campaign),
                   'manifest_sha256':manifest_sha,'command':child_command,'automatic_retry':False}
        request_sha = put(self.host/'request.json', request)
        process_sha = put(self.host/'process_guard/spec.json', {'fixture':True})
        out_sha = put(self.host/'stdout.log', b'gate fixture stdout\n', binary=True)
        err_sha = put(self.host/'stderr.log', b'', binary=True)
        self.original = {'guard_source_sha256':inputs['src/smt_fullfab/model_process_guard.py'],
            'lifecycle_complete':True,'command_returncode':0,'timed_out':False,'launch_error':None,
            'command_peak_rss_bytes':100,'guard_peak_rss_bytes':100,
            'files_sha256':{'spec.json':process_sha},
            'output_files_sha256':{'stdout':out_sha,'stderr':err_sha,'gate_acceptance':self.acceptance_sha}}
        self.host_result = {'schema':self.spec['host_schema']+'-result','run_id':run_id,
            'manifest_sha256':manifest_sha,'campaign':str(self.campaign),'host_directory':str(self.host),
            'accepted':True,'status':'success','errors':[], 'gate_acceptance_sha256':self.acceptance_sha,
            'gate_readback':self.verified, 'host_request_sha256':request_sha,
            'host_evidence_sha256':{k:v['sha256'] for k,v in s.tree(self.host).items()},
            'total_wall_seconds_at_last_encoding_start':20.0,'prepare_wall_seconds':1.0,
            'total_bytes_including_host_result':0,'guard_admitted_seconds':100.0,'guard_evidence':self.original}
        self.exit = {'schema':s.EXIT_SCHEMA,'run_id':run_id,'observation_method':'write_stdin_terminal_result',
                     'exited':True,'session_id':99,'exit_code':0,'timed_out':False,
                     'terminal_tool_result':{'exit_code':0},'command':command}
        self.completion = {'schema':s.COMPLETION_SCHEMA,'run_id':run_id,
            'manifest_sha256':manifest_sha,'preparation_sha256':self.spec['preparation_sha256'],
            'launch_request_sha256':self.spec['launch_request_sha256'],'campaign':str(self.campaign),'host_directory':str(self.host),
            'gate_acceptance_sha256':self.acceptance_sha,'runner_result_sha256':result_sha,
            'host_real_seconds_text':'30.00','host_wall_seconds_upper_bound':'30.01',
            'total_wall_seconds_upper_bound':'31.51','preparation_wall_seconds':1.5,
            'posterior_readback_wall_seconds':0.2,
            'posterior_scope':'read-only status/review after actual experiment exit; separately reported; no model/factory/solver',
            'accepted':True,'status':'success','errors':[], 'total_bytes_including_completion':0,
            'disk_scope':'gate_campaign_run_scratch+host+all_observation_files+preparation_record+root_completion'}
        put(self.obs/'initial_observation.json', {'running_at_previous_observation':True})
        put(self.obs/'observation_002.json', {'progress':2})
        self.stderr = b'real 30.00\nuser 2.00\nsys 0.50\n'
        self.gate = SimpleNamespace(RUN_ID=run_id,OUTER_SECONDS=self.spec['outer_seconds'],MAX_BYTES=self.spec['max_bytes'],RSS_BYTES=8*1024**3,
            read_acceptance=Mock(side_effect=lambda **kw: deepcopy(self.verified)),total_bytes=lambda *_:self.gate_bytes(),
            evidence=Mock(side_effect=lambda *a,**k: deepcopy(self.acceptance['evidence_sha256'])),
            _final_ledger=Mock())
        self.guard = SimpleNamespace(verify_lifecycle=Mock(return_value=self.original))
        self.seal()

    def gate_bytes(self):
        return sum(p.stat().st_size for base in (self.campaign,self.folder) for p in base.rglob('*') if p.is_file())

    def seal(self):
        # Synthetic publication only. Preserve exact raw hashes just like root's
        # future create-new receipts, while allowing deliberate tamper fixtures.
        self.host_result['host_evidence_sha256'] = {k:v['sha256'] for k,v in s.tree(self.host, omit=('result.json',)).items()}
        for _ in range(20):
            payload = raw(identity(self.host_result))
            size = self.gate_bytes() + sum(v['bytes'] for v in s.tree(self.host,omit=('result.json',)).values()) + len(payload)
            if size == self.host_result['total_bytes_including_host_result']:
                break
            self.host_result['total_bytes_including_host_result'] = size
        host_sha = put(self.host/'result.json', identity(self.host_result))
        stdout = {'accepted':self.host_result['accepted'],'status':self.host_result['status'],
                  'result_path':str(self.host/'result.json'),'result_sha256':host_sha}
        self.exit['stdout_sha256'] = put(self.obs/'stdout.log', stdout)
        self.exit['time_and_stderr_sha256'] = put(self.obs/'time_and_stderr.log', self.stderr,binary=True)
        self.completion['actual_exit_sha256'] = put(self.obs/'actual_exit.json', self.exit)
        self.completion['host_result_sha256'] = host_sha
        self.completion['observation_evidence_sha256'] = {k:v['sha256'] for k,v in s.tree(self.obs,omit=('root_completion.json',)).items()}
        for _ in range(20):
            payload = raw(identity(self.completion))
            total = self.gate_bytes() + sum(v['bytes'] for v in s.tree(self.host).values()) + sum(v['bytes'] for v in s.tree(self.obs,omit=('root_completion.json',)).values()) + (self.root/self.spec['preparation']).stat().st_size + len(payload)
            if self.completion['total_bytes_including_completion'] == total:
                break
            self.completion['total_bytes_including_completion'] = total
        put(self.obs/'root_completion.json', identity(self.completion))

    def read(self):
        @contextmanager
        def load(*args):
            yield self.gate,self.guard
        with patch.dict(s.RUNS,{self.run_id:self.spec}), patch.object(s,'frozen_modules',load):
            return s.guarded_result_row(self.folder,root=self.root)

    def use_real_final_ledger(self):
        # Deliberately called only when root executes these tests. The helper
        # reads this fixture's tiny saved/live ledgers, never the real ledger.
        from importlib import import_module
        module = import_module('src.smt_fullfab.'+self.spec['gate'])
        self.gate._final_ledger = Mock(side_effect=module._final_ledger)

    def append_ledger(self, value):
        with self.live_ledger.open('ab') as stream:
            stream.write(raw(value))

    def read_with_late_suffix(self, value):
        original_tree = s.tree
        calls = []
        def final_collection(base, **kwargs):
            result = original_tree(base, **kwargs)
            if Path(base) == self.host:
                calls.append(str(base))
                if len(calls) == 2:
                    # After the second/final host inventory, so an initial
                    # gate readback or earlier lifecycle check cannot see it.
                    self.append_ledger(value)
            return result
        with patch.object(s, 'tree', side_effect=final_collection):
            result = self.read()
        return result, len(calls)


class GuardedStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.f=Fixture(self.root)

    def test_complete_c_requires_all_layers_and_preserves_outer_cost(self):
        row=self.f.read()
        self.assertTrue(row['accepted'],row['guarded_acceptance_errors'])
        self.assertEqual(row['wall_seconds'],31.51)
        self.assertEqual(row['physical_result_wall_seconds'],10.0)
        self.assertEqual(row['root_resource_closure']['posterior_readback_wall_seconds'],0.2)
        self.f.gate.read_acceptance.assert_called_once_with(root=self.root)
        self.f.guard.verify_lifecycle.assert_called_once()
        self.assertEqual(self.f.guard.verify_lifecycle.call_args.kwargs['expected_evidence'],self.f.original)

    def test_b4_has_its_own_host_and_gate_contract(self):
        f=Fixture(self.root,'B_1701_1h_delta_v4');row=f.read()
        self.assertTrue(row['accepted'],row['guarded_acceptance_errors'])
        self.assertEqual(row['arm'],'B');self.assertEqual(row['window_seconds'],3600)

    def test_current_unregistered_b_anchor_never_uses_c(self):
        f=Fixture(self.root,'B_1701_1h_delta_v4')
        f.spec['preparation_sha256']=None
        self.assertFalse(f.read()['accepted']);f.gate.read_acceptance.assert_not_called()

    def test_running_with_no_result_is_pending_not_zero_cost(self):
        (self.f.obs/'root_completion.json').unlink();(self.f.folder/'result.json').unlink()
        (self.f.host/'result.json').unlink();(self.f.campaign/'acceptance.json').unlink()
        row=self.f.read();self.assertEqual(row['status'],'pending')
        self.assertIsNone(row['model_calls']);self.assertIsNone(row['wall_seconds'])
        self.assertFalse(row['full_window_completed'])

    def test_success_result_without_root_closure_stays_pending(self):
        (self.f.obs/'root_completion.json').unlink()
        row=self.f.read();self.assertEqual(row['status'],'pending');self.assertFalse(row['audit_valid'])
        self.assertEqual(row['model_calls'],7);self.f.gate.read_acceptance.assert_not_called()

    def test_saved_failed_result_remains_failed_before_closure(self):
        (self.f.obs/'root_completion.json').unlink()
        self.f.result.update(status='failed',failure='original timeout',model_calls=None)
        put(self.f.folder/'result.json',self.f.result)
        row=self.f.read();self.assertEqual(row['status'],'failed')
        self.assertEqual(row['failure'],'original timeout');self.assertIsNone(row['model_calls'])

    def test_actual_nonzero_exit_before_completion_is_already_failed(self):
        (self.f.obs/'root_completion.json').unlink()
        self.f.exit.update(exit_code=1,terminal_tool_result={'exit_code':1})
        put(self.f.obs/'actual_exit.json',self.f.exit)
        self.assertEqual(self.f.read()['status'],'failed')

    def test_missing_actual_wait_is_failed_and_never_promoted(self):
        (self.f.obs/'actual_exit.json').unlink()
        row=self.f.read();self.assertEqual(row['status'],'failed');self.assertFalse(row['accepted'])
        self.f.gate.read_acceptance.assert_not_called()

    def test_nonzero_actual_exit_even_if_host_and_gate_succeeded(self):
        self.f.exit.update(exit_code=1,terminal_tool_result={'exit_code':1});self.f.seal()
        row=self.f.read();self.assertFalse(row['accepted']);self.assertEqual(row['wall_seconds'],31.51)

    def test_bool_exit_or_wrong_session_rejected(self):
        for values in ({'exit_code':False,'terminal_tool_result':{'exit_code':False}}, {'session_id':100}):
            with self.subTest(values=values):
                saved=deepcopy(self.f.exit);self.f.exit.update(values);self.f.seal()
                self.assertFalse(self.f.read()['accepted']);self.f.exit=saved

    def test_original_manifest_cannot_be_reanchored_by_completion(self):
        self.f.manifest['prepare_wall_seconds']=0.5
        newer=put(self.f.campaign/'manifest.json',identity(self.f.manifest))
        self.f.completion['manifest_sha256']=newer;self.f.seal()
        self.assertFalse(self.f.read()['accepted'])

    def test_original_preparation_and_launch_request_are_external_pins(self):
        for target in (self.root/self.f.spec['preparation'],self.f.obs/'request.json'):
            with self.subTest(target=target):
                before=target.read_bytes();target.write_bytes(before+b' ');self.f.seal()
                self.assertFalse(self.f.read()['accepted']);target.write_bytes(before)

    def test_result_changed_after_original_gate_is_not_promoted(self):
        self.f.result['model_calls']=8;put(self.f.folder/'result.json',self.f.result)
        self.f.seal();self.assertFalse(self.f.read()['accepted'])

    def test_full_window_and_authority_predicates_cannot_be_self_upgraded(self):
        for change in ({'simulation_seconds':12},{'audit_valid':False},{'accepted':True},
                       {'terminal_trace_binding_valid':False},{'direct_public_execution_enabled':True}):
            with self.subTest(change=change):
                f=Fixture(self.root);f.result.update(change)
                new=put(f.folder/'result.json',f.result)
                f.acceptance.update(runner_result_sha256=new,evidence_sha256={'run/result.json':new})
                f.acceptance_sha=put(f.campaign/'acceptance.json',f.acceptance)
                f.verified['acceptance_sha256']=f.acceptance_sha
                f.host_result['gate_acceptance_sha256']=f.acceptance_sha
                f.completion.update(gate_acceptance_sha256=f.acceptance_sha,runner_result_sha256=new)
                f.seal();self.assertFalse(f.read()['accepted'])

    def test_gate_must_be_valid_and_preserve_original_acceptance_sha(self):
        for change in ({'valid':False},{'accepted':False},{'acceptance_sha256':'0'*64}):
            with self.subTest(change=change):
                saved=deepcopy(self.f.verified);self.f.verified.update(change)
                self.assertFalse(self.f.read()['accepted']);self.f.verified=saved

    def test_lifecycle_verifier_failure_rejects(self):
        self.f.guard.verify_lifecycle.side_effect=ValueError('original lifecycle differs')
        self.assertFalse(self.f.read()['accepted'])

    def test_host_rss_must_be_exact_int_within_original_cap(self):
        for value in (True,None,-1,8*1024**3+1):
            with self.subTest(value=value):
                self.f.original['command_peak_rss_bytes']=value;self.f.seal()
                self.assertFalse(self.f.read()['accepted'])

    def test_actual_timing_missing_duplicate_or_wrong_rounding_rejects(self):
        for stderr in (b'',b'real 30.00\nreal 30.00\n',b'real NaN\n'):
            with self.subTest(stderr=stderr):
                self.f.stderr=stderr;self.f.seal();self.assertFalse(self.f.read()['accepted'])
        self.f.stderr=b'real 30.00\n';self.f.completion['host_wall_seconds_upper_bound']=30
        self.f.seal();self.assertFalse(self.f.read()['accepted'])

    def test_long_preparation_exact_decimal_text_and_float_rejection(self):
        path=self.root/self.f.spec['preparation']
        preparation=json.loads(path.read_text())
        preparation['root_preparation_and_immediate_verification_wall_seconds']=1.592322041047737
        expected=put(path,preparation)
        self.f.spec['preparation_sha256']=expected
        self.f.completion.update(preparation_sha256=expected,preparation_wall_seconds=1.592322041047737,
                                 total_wall_seconds_upper_bound='31.602322041047737')
        self.f.seal();row=self.f.read()
        self.assertTrue(row['accepted'],row['guarded_acceptance_errors'])
        self.assertEqual(row['root_resource_closure']['wall_seconds_upper_bound_text'],'31.602322041047737')
        self.f.completion['total_wall_seconds_upper_bound']=float('31.602322041047737')
        self.f.seal();self.assertFalse(self.f.read()['accepted'])

    def test_complete_wall_over_cap_cannot_be_accepted(self):
        self.f.stderr=b'real 46800.00\n'
        self.f.completion.update(host_real_seconds_text='46800.00',host_wall_seconds_upper_bound='46800.01',total_wall_seconds_upper_bound='46801.51')
        self.f.seal();row=self.f.read()
        self.assertFalse(row['accepted']);self.assertEqual(row['wall_seconds'],46801.51)

    def test_exact_terminal_disk_and_prior_observation_files_count(self):
        expected=self.f.completion['total_bytes_including_completion']
        row=self.f.read();self.assertEqual(row['root_resource_closure']['total_bytes'],expected)
        put(self.f.obs/'observation_late.json',{'late':True})
        self.assertFalse(self.f.read()['accepted'])

    def test_nested_same_name_completion_is_counted_not_omitted(self):
        before=self.f.completion['total_bytes_including_completion']
        nested=self.f.obs/'nested/root_completion.json'
        put(nested,{'nested':'must count'})
        listing=s.tree(self.f.obs,omit=('root_completion.json',))
        self.assertIn('nested/root_completion.json',listing)
        self.assertNotIn('root_completion.json',listing)
        self.assertFalse(self.f.read()['accepted'])
        self.f.seal();row=self.f.read()
        self.assertTrue(row['accepted'],row['guarded_acceptance_errors'])
        self.assertGreater(row['root_resource_closure']['total_bytes'],before+nested.stat().st_size)

    def test_total_bytes_mismatch_or_cap_rejects(self):
        self.f.completion['total_bytes_including_completion']+=1
        put(self.f.obs/'root_completion.json',identity(self.f.completion))
        self.assertFalse(self.f.read()['accepted'])
        self.f.seal();self.f.spec['max_bytes']=1;self.f.gate.MAX_BYTES=1
        self.assertFalse(self.f.read()['accepted'])

    def test_readback_replacement_cannot_become_new_anchor(self):
        def changed(**kwargs):
            data=(self.f.host/'result.json').read_bytes()
            (self.f.host/'result.json').write_bytes(data+b' ')
            return deepcopy(self.f.verified)
        self.f.gate.read_acceptance.side_effect=changed
        self.assertFalse(self.f.read()['accepted'])

    def test_actual_stdout_must_name_original_host_result(self):
        self.f.exit['stdout_sha256']=put(self.f.obs/'stdout.log',{'accepted':True})
        self.f.completion['actual_exit_sha256']=put(self.f.obs/'actual_exit.json',self.f.exit)
        self.f.completion['observation_evidence_sha256']={k:v['sha256'] for k,v in s.tree(self.f.obs,omit=('root_completion.json',)).items()}
        put(self.f.obs/'root_completion.json',identity(self.f.completion))
        self.assertFalse(self.f.read()['accepted'])

    def test_original_host_inventory_or_new_file_rejects(self):
        put(self.f.host/'unexpected.json',{'extra':True})
        self.assertFalse(self.f.read()['accepted'])

    def test_symlink_evidence_is_rejected(self):
        original=self.f.obs/'initial_observation.json';target=self.root/'moved.json'
        original.rename(target);original.symlink_to(target)
        self.assertFalse(self.f.read()['accepted'])

    def test_duplicate_or_nonobject_json_never_crashes_status(self):
        for bad in (b'{"status":"failed","status":"success"}',b'[]'):
            with self.subTest(bad=bad):
                (self.f.folder/'result.json').write_bytes(bad)
                self.assertEqual(self.f.read()['status'],'failed')


class FinalLedgerFenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def cases(self):
        for run_id in s.RUNS:
            f = Fixture(self.root/run_id, run_id)
            f.use_real_final_ledger()
            yield f

    def reject_late(self, value):
        for f in self.cases():
            with self.subTest(arm=f.spec['arm']):
                row, collections = f.read_with_late_suffix(value(f))
                self.assertEqual(collections, 2)
                self.assertFalse(row['accepted'])
                self.assertEqual(row['status'], 'failed')
                self.assertTrue(any('same run/registration/call acquired suffix' in error
                                    for error in row['guarded_acceptance_errors']), row)
                f.gate._final_ledger.assert_called_once_with(f.folder, f.manifest, f.ledger_sha, f.registration_id)

    def test_unchanged_uses_original_payload_ledger_and_registration(self):
        for f in self.cases():
            with self.subTest(arm=f.spec['arm']):
                row = f.read()
                self.assertTrue(row['accepted'], row['guarded_acceptance_errors'])
                f.gate._final_ledger.assert_called_once_with(f.folder, f.manifest, f.ledger_sha, f.registration_id)
                self.assertEqual(s.sha((f.campaign/'verification_payload.json').read_bytes()), f.proof_sha)
                self.assertEqual(s.sha(f.live_ledger.read_bytes()), f.ledger_sha)

    def test_late_same_run_note_rejected_after_last_inventory(self):
        self.reject_late(lambda f: {'event':'note','run_id':str(f.folder),'message':'late'})

    def test_late_nested_registration_rejected_after_last_inventory(self):
        self.reject_late(lambda f: {'event':'note','registration':{
            'run_id':str(f.folder),'registration_id':'new-registration'}})

    def test_late_nested_mapping_original_registration_rejected(self):
        self.reject_late(lambda f: {'event':'note','mapping':{
            'registration_id':f.registration_id},'message':'no top-level run id'})

    def test_late_original_call_only_note_rejected(self):
        self.reject_late(lambda f: {'event':'note','call_id':f.call_id,'message':'no run or registration'})

    def test_late_unrelated_run_is_allowed_without_reanchoring(self):
        for f in self.cases():
            with self.subTest(arm=f.spec['arm']):
                row, collections = f.read_with_late_suffix({'event':'note',
                    'run_id':str(f.root/'runs/other_run'),'registration_id':'other-registration',
                    'call_id':'other-call','message':'unrelated'})
                self.assertEqual(collections, 2)
                self.assertTrue(row['accepted'], row['guarded_acceptance_errors'])
                self.assertNotEqual(s.sha(f.live_ledger.read_bytes()), f.ledger_sha)
                f.gate._final_ledger.assert_called_once_with(f.folder, f.manifest, f.ledger_sha, f.registration_id)

    def test_verification_payload_replacement_does_not_reanchor(self):
        for f in self.cases():
            with self.subTest(arm=f.spec['arm']):
                replaced = dict(f.proof, registration_id='fixture-registration-2')
                put(f.campaign/'verification_payload.json', replaced)
                f.seal()  # Even internally matching totals cannot replace its original acceptance SHA.
                row = f.read()
                self.assertFalse(row['accepted'])
                f.gate._final_ledger.assert_not_called()

    def test_late_verification_payload_change_is_fenced(self):
        for f in self.cases():
            with self.subTest(arm=f.spec['arm']):
                def late_change(*args, **kwargs):
                    put(f.campaign/'verification_payload.json',
                        dict(f.proof, registration_id='fixture-registration-2'))
                    return f.original
                f.guard.verify_lifecycle.side_effect = late_change
                row = f.read()
                self.assertFalse(row['accepted'])
                f.gate._final_ledger.assert_not_called()

    def test_retained_original_function_runs_after_frozen_namespace_exit(self):
        f = Fixture(self.root)
        f.use_real_final_ledger()
        active = {'inside':False,'exited':False}
        original_check = f.gate._final_ledger.side_effect
        def final_check(*args):
            self.assertFalse(active['inside'])
            self.assertTrue(active['exited'])
            return original_check(*args)
        f.gate._final_ledger.side_effect = final_check
        @contextmanager
        def lifetime(*args):
            active['inside'] = True
            try:
                yield f.gate, f.guard
            finally:
                active.update(inside=False, exited=True)
        with patch.dict(s.RUNS, {f.run_id:f.spec}), patch.object(s, 'frozen_modules', lifetime):
            row = s.guarded_result_row(f.folder, root=f.root)
        self.assertTrue(row['accepted'], row['guarded_acceptance_errors'])


class FrozenLoaderTests(unittest.TestCase):
    def test_private_frozen_module_namespace_and_source_fence(self):
        with tempfile.TemporaryDirectory() as tmp:
            campaign=Path(tmp).resolve();frozen=campaign/'frozen';sources={}
            for name,content in {'tiny_gate':'from .tiny_value import VALUE\n','model_process_guard':'VALUE=2\n','tiny_value':'VALUE=1\n'}.items():
                path='src/smt_fullfab/'+name+'.py';sources[path]=put(frozen/path,content.encode(),binary=True)
            manifest={'frozen_input_sha256':sources}
            with s.frozen_modules(campaign,manifest,{'gate':'tiny_gate'}) as (gate,guard):
                self.assertEqual(gate.VALUE,1);self.assertEqual(guard.VALUE,2)
                self.assertTrue(gate.__name__.startswith('_fullfab_status_'))
            with self.assertRaises(ValueError):
                with s.frozen_modules(campaign,manifest,{'gate':'tiny_gate'}):
                    (frozen/'src/smt_fullfab/tiny_value.py').write_text('VALUE=3\n')

    def test_unlisted_source_or_bytecode_rejected_before_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            campaign=Path(tmp).resolve();frozen=campaign/'frozen';sources={}
            for name in ('tiny_gate','model_process_guard'):
                path='src/smt_fullfab/'+name+'.py';sources[path]=put(frozen/path,b'VALUE=1\n',binary=True)
            put(frozen/'src/__init__.pyc',b'unlisted bytecode',binary=True)
            with self.assertRaisesRegex(ValueError,'before import'):
                with s.frozen_modules(campaign,{'frozen_input_sha256':sources},{'gate':'tiny_gate'}):
                    self.fail('unlisted frozen member was imported')

    def test_status_dispatch_has_no_dependency_on_legacy_acceptance(self):
        # Exercise inventory's dispatch using only tiny synthetic roots/ledger
        # stubs; it must not call old C constructive or old B delta adapters.
        from src.smt_fullfab import status
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()
            put(root/'progress/smt_fullfab/history_baseline.json',{'files':{}})
            put(root/'configs/smt_fullfab/stage2_probe.approved.json',{'total_active_wall_seconds':2700,'max_model_attempts':12,'observed_input_output_token_admission_limit':1})
            for run in s.RUNS:(root/'runs/smt_fullfab_stage2'/run).mkdir(parents=True)
            @contextmanager
            def locked():yield []
            ledger=SimpleNamespace(_locked=locked,summary=lambda:{'model_active_seconds':0,'unknown_completed':[], 'pending':[], 'attempts':0,'reported_input_output_tokens':0},scoped_limit_waiver=lambda arm:None,research_limit_waiver=lambda:{},solver_remaining_seconds=lambda arm:0)
            def adapter(folder,*,root):
                spec=s.RUNS[folder.name]
                return {'run_id':folder.name,'kind':'experiment','arm':spec['arm'],'window_seconds':spec['seconds'],'status':'pending','audit_valid':False,'full_window_completed':False,'result_sha256':None,'wall_seconds':None,'solver_requested_seconds':None}
            with patch.object(status,'ROOT',root),patch.object(status,'BudgetLedger',return_value=ledger),patch.object(status,'guarded_result_row',side_effect=adapter),patch.object(status,'constructive_acceptance',side_effect=AssertionError('legacy C')),patch.object(status,'delta_result_row',side_effect=AssertionError('legacy B')):
                value=status.inventory()
            self.assertEqual(len(value['incomplete_or_running_paths']),2)
            self.assertIsNone(value['experiment_activity_wall_seconds'])
            self.assertEqual(value['experiment_activity_wall_seconds_known_sum'],0)
            self.assertFalse(value['short_window_gates']['C']['28800']['passed'])
            self.assertFalse(value['short_window_gates']['B']['3600']['passed'])


if __name__=='__main__':
    unittest.main()
