"""Gate orchestration with temporary tiny trees and explicit readback/child mocks.

No real preparation directory, ledger, model, factory, solver or subprocess runs.
These tests do not certify the mocked semantic audit as a physical audit.
"""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.smt_fullfab import B_delta_gate_v2 as gate, offline_pilot

REAL_RUNTIME_CAPTURE=gate._runtime_capture


class GateTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.root=Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        for relative in ('src/smt_fullfab','src/smt',gate.DATA,gate.VENDOR,'configs/smt_fullfab','progress/smt_fullfab','runs'):
            (self.root/relative).mkdir(parents=True,exist_ok=True)
        for relative in ('src/__init__.py','src/smt/__init__.py','src/smt_fullfab/__init__.py'):(self.root/relative).write_text('')
        for name in ('B_delta_gate_v2.py','offline_pilot.py','offline_A_gate_v3.py'):
            (self.root/'src/smt_fullfab'/name).write_bytes(Path(gate.__file__).with_name(name).read_bytes())
        (self.root/gate.DATA/'input.txt').write_text('tiny synthetic factory data, never loaded')
        (self.root/gate.VENDOR/'fixture.py').write_text('# vendor placeholder never imported')
        (self.root/'requirements.lock').write_text('# synthetic requirements')
        for relative in (gate.PROTOCOL,gate.APPROVAL,gate.WAIVER):
            (self.root/relative).write_bytes((gate.ROOT/relative).read_bytes())
        self.rows=[{'event':'approval','approval':gate._read(self.root/gate.APPROVAL)},
                   {'event':'research_limit_waiver','amendment':gate._read(self.root/gate.WAIVER)}]
        for i in range(gate.PRIOR_ATTEMPTS):
            self.rows += [{'event':'reserve','call_id':f'prior{i}','run_id':str(self.root/'runs/prior'/str(i))},
                          {'event':'finish','call_id':f'prior{i}','status':'success','details':{'usage':None}}]
        self.ledger=self.root/gate.LEDGER;self.sync_ledger()
        self.stack.enter_context(patch.object(gate,'_origin_git',return_value='1'*40))
        self.stack.enter_context(patch.object(offline_pilot,'_origin_git',return_value='1'*40))
        gate._git_pointer(self.root,'1'*40)
        self.stack.enter_context(patch.object(gate,'_runtime_capture',return_value={'synthetic_runtime':True}))
        self.stack.enter_context(patch.object(gate,'_active_with_finalizers',return_value=[]))
        self.stack.enter_context(patch.object(gate.shutil,'disk_usage',return_value=SimpleNamespace(free=50*1024**3)))
        self.clock=[0.0];self.stack.enter_context(patch.object(gate.time,'monotonic',side_effect=lambda:self.clock[0]))
        self.child_wall=20.0;self.usage=123456;self.post_hook=None;self.readback_count=0
        self.launch=self.stack.enter_context(patch.object(gate,'_launch',side_effect=self.child))
        self.readback=self.stack.enter_context(patch.object(gate,'_readback',side_effect=self.verifier))
        self.stack.enter_context(patch.object(gate.subprocess,'run',side_effect=AssertionError('no real subprocess')))

    def sync_ledger(self):self.ledger.write_bytes(b''.join((json.dumps(r)+'\n').encode() for r in self.rows))
    def prepare(self):return gate.prepare(root=self.root)
    def run_gate(self):
        campaign,manifest=self.prepare();return campaign,manifest,gate.execute(campaign,manifest)

    def child(self,command,frozen,campaign,timeout):
        manifest=gate._read(campaign/'manifest.json');self.assertEqual(command,manifest['child_command'])
        self.assertGreater(timeout,0);self.assertLessEqual(timeout,gate.OUTER_SECONDS)
        self.clock[0]+=self.child_wall
        gate._write(campaign/'child_started.json',{'pid':7654321})
        gate._write(campaign/'child_usage.json',{'schema':'smt-child-peak-rss-v1','pid':7654321,'platform':'darwin',
            'source':'resource.getrusage(RUSAGE_SELF).ru_maxrss','raw_maxrss':self.usage,'raw_unit':'bytes',
            'peak_rss_bytes':self.usage,'hard_memory_guard':False})
        (campaign/'stdout.log').write_bytes(b'synthetic child\n');(campaign/'stderr.log').write_bytes(b'')
        out=Path(manifest['output_directory']);out.mkdir(parents=True)
        gate._write(out/'result.json',{'end_to_end_wall_seconds':10.0,'status':'completed'})
        (out/'trace.jsonl').write_bytes(b'{"kind":"terminal","time":3600}\n')
        (out/'checkpoint.json').write_bytes(b'{"synthetic_only":true}\n')
        (out/'model_raw.txt').write_bytes(b'exact synthetic raw output')
        self.rows += [{'event':'reserve','call_id':'new-call','registration_id':'new-registration','run_id':str(out/'model_00000')},
                      {'event':'finish','call_id':'new-call','status':'success','details':{'usage':None}}]
        self.sync_ledger();(out/'ledger_final.jsonl').write_bytes(self.ledger.read_bytes())
        return {'returncode':0,'timed_out':False,'wall_seconds':self.child_wall,'pid':7654321}

    def verifier(self,run,manifest,*,timeout=600):
        self.readback_count+=1
        proof={'valid':True,'result':gate._read(run/'result.json'),'registration_id':'new-registration',
               'verified_evidence_sha256':{'run/'+p.relative_to(run).as_posix():gate._sha(p) for p in gate._files(run)}}
        if self.post_hook:self.post_hook(run,manifest)
        return proof

    def test_prepare_freezes_exact_sources_and_maps_original_ledger_without_call(self):
        campaign,manifest=self.prepare();self.assertEqual(self.launch.call_count,0)
        self.assertEqual((campaign/'frozen/progress').resolve(),self.root/'progress')
        self.assertEqual((campaign/'frozen/runs').resolve(),self.root/'runs')
        self.assertEqual(manifest['source_sha256'],gate._digest(gate._sources(manifest['frozen_input_sha256'])))
        self.assertNotIn(gate.PROTOCOL,gate._sources(manifest['frozen_input_sha256']))
        self.assertEqual(manifest['prior_ledger']['original_model_attempts'],241)
        self.assertEqual(self.ledger.read_bytes(),(campaign/'ledger_at_prepare.jsonl').read_bytes())
        self.assertFalse(Path(manifest['output_directory']).exists())
        self.assertEqual(self.prepare(),(campaign,manifest))
        self.assertIn('d.main()',manifest['child_command'][4]);self.assertNotIn('runpy',manifest['child_command'][4])

    def test_success_requires_mock_verification_process_costs_and_exact_readback(self):
        campaign,manifest,acceptance=self.run_gate();self.assertTrue(acceptance['accepted'],acceptance)
        self.assertEqual(acceptance['final_total_bytes_including_acceptance'],gate._bytes(campaign,Path(manifest['output_directory'])))
        replay=gate.read_acceptance(root=self.root);self.assertTrue(replay['valid'],replay);self.assertTrue(replay['accepted'])
        self.assertEqual(self.launch.call_count,1)
        self.assertTrue(gate.execute(campaign,manifest)['accepted']);self.assertEqual(self.launch.call_count,1)
        self.assertFalse(acceptance['backend_identity_independently_proven'])

    def test_capacity_or_active_claim_blocks_before_original_call(self):
        campaign,manifest=self.prepare()
        with patch.object(gate.shutil,'disk_usage',return_value=SimpleNamespace(free=gate.MIN_FREE_BYTES-1)):
            self.assertEqual(gate.execute(campaign,manifest)['status'],'blocked_disk_capacity')
        with patch.object(gate,'_active_with_finalizers',return_value=[{'pid':1}]):
            self.assertEqual(gate.execute(campaign,manifest)['status'],'blocked_active_runs')
        self.assertFalse((campaign/'attempt.json').exists());self.assertEqual(self.launch.call_count,0)

    def test_existing_attempt_or_run_is_never_restarted(self):
        campaign,manifest=self.prepare();gate._write(campaign/'attempt.json',{'partial':True})
        with self.assertRaises(ValueError):gate.execute(campaign,manifest)
        self.assertEqual(self.launch.call_count,0)

    def test_protocol_any_resource_or_boolean_type_change_is_rejected(self):
        protocol=gate._read(self.root/gate.PROTOCOL)
        for change in ({'max_calls':0},{'solver_seconds':1},{'per_call_timeout_seconds':181},{'serial_only':1},{'trace_bytes':gate.TRACE_BYTES+1}):
            with self.subTest(change=change):
                mutated=deepcopy(protocol);mutated['limits'].update(change)
                with self.assertRaises(ValueError):gate._config(mutated)

    def test_prior_history_reset_pending_or_existing_target_registration_rejected(self):
        raw=self.ledger.read_bytes()
        for rows in (self.rows[:4],self.rows+[{'event':'reserve','call_id':'pending','run_id':str(self.root/'other')}],
                     self.rows+[{'event':'stage_run_registered','registration':{'run_id':str(self.root/'runs/smt_fullfab_stage2'/gate.RUN_ID)}}]):
            with self.subTest(rows=len(rows)):
                bad=b''.join((json.dumps(r)+'\n').encode() for r in rows)
                with self.assertRaises(ValueError):gate._ledger_preflight(bad,self.root)
        self.assertEqual(self.ledger.read_bytes(),raw)

    def test_complete_child_wall_limit_not_just_smaller_result_timer(self):
        self.child_wall=21600.1;_,_,result=self.run_gate()
        self.assertFalse(result['accepted']);self.assertIn('complete child wall',str(result['errors']))

    def test_outer_verification_cost_is_charged(self):
        self.post_hook=lambda *_:self.clock.__setitem__(0,22200.1)
        _,_,result=self.run_gate();self.assertFalse(result['accepted']);self.assertIn('outer wall',str(result['errors']))

    def test_peak_rss_overrun_is_failed_without_deleting_raws(self):
        self.usage=gate.PEAK_RSS_BYTES+1;campaign,manifest,result=self.run_gate()
        self.assertFalse(result['accepted']);self.assertTrue((Path(manifest['output_directory'])/'model_raw.txt').exists())

    def test_timeout_preserves_missing_result_and_does_not_invent_checkpoint(self):
        self.launch.side_effect=lambda *args:{'returncode':-9,'timed_out':True,'wall_seconds':22200.0,'pid':7654321}
        campaign,manifest,result=self.run_gate();self.assertFalse(result['accepted'])
        self.assertFalse((Path(manifest['output_directory'])/'checkpoint.json').exists())
        self.assertFalse((Path(manifest['output_directory'])/'result.json').exists())
        self.assertFalse(gate.execute(campaign,manifest)['accepted']);self.assertEqual(self.launch.call_count,1)

    def test_readback_timeout_fails_without_retry(self):
        self.readback.side_effect=subprocess.TimeoutExpired('synthetic verifier',600)
        _,_,result=self.run_gate();self.assertFalse(result['accepted']);self.assertEqual(self.readback.call_count,1)

    def test_modified_or_added_file_after_verified_hash_cannot_be_reanchored(self):
        self.post_hook=lambda run,_:(run/'model_raw.txt').write_bytes(b'changed after verification')
        _,_,result=self.run_gate();self.assertFalse(result['accepted']);self.assertIn('original verification anchors',str(result['errors']))

    def test_new_unverified_file_after_readback_rejected(self):
        self.post_hook=lambda run,_:(run/'unverified_orphan').write_bytes(b'new')
        _,_,result=self.run_gate();self.assertFalse(result['accepted'])

    def test_postrun_source_change_rejects(self):
        def changed(run,manifest):
            path=self.root/gate.AREA/gate.RUN_ID/'frozen'/gate.DATA/'input.txt'
            path.chmod(0o644);path.write_text('changed frozen data')
        self.post_hook=changed
        _,_,result=self.run_gate();self.assertFalse(result['accepted']);self.assertIn('frozen',str(result['errors']))

    def test_final_byte_overrun_counts_acceptance_and_all_files(self):
        campaign,manifest=self.prepare()
        real=gate._bytes
        with patch.object(gate,'_bytes',side_effect=lambda *args:gate.MAX_BYTES+real(*args)):
            result=gate.execute(campaign,manifest)
        self.assertFalse(result['accepted']);self.assertIn('16GiB',str(result['errors']))

    def test_other_runs_may_append_but_same_registration_new_cost_invalidates_readback(self):
        _,_,result=self.run_gate();self.assertTrue(result['accepted'])
        self.rows += [{'event':'reserve','call_id':'other','registration_id':'other-reg','run_id':str(self.root/'runs/other/model0')},
                      {'event':'finish','call_id':'other','status':'success','details':{'usage':None}}]
        self.sync_ledger();self.assertTrue(gate.read_acceptance(root=self.root)['accepted'])
        self.rows += [{'event':'reserve','call_id':'late','registration_id':'new-registration','run_id':str(self.root/'runs/elsewhere')},
                      {'event':'finish','call_id':'late','status':'success','details':{'usage':None}}]
        self.sync_ledger();replay=gate.read_acceptance(root=self.root)
        self.assertFalse(replay['valid']);self.assertIn('new resource events',str(replay['errors']))

    def test_known_call_finish_append_is_not_hidden_as_another_run(self):
        _,_,result=self.run_gate();self.assertTrue(result['accepted'])
        self.rows += [{'event':'finish','call_id':'new-call','status':'success','details':{'usage':None}}]
        self.sync_ledger();self.assertFalse(gate.read_acceptance(root=self.root)['valid'])

    def test_missing_acceptance_cannot_pass_even_with_completed_result(self):
        campaign,_,_=self.run_gate();(campaign/'acceptance.json').unlink()
        self.assertFalse(gate.read_acceptance(root=self.root)['valid'])
        with self.assertRaises(ValueError):gate.execute(campaign,gate._read(campaign/'manifest.json'))
        self.assertEqual(self.launch.call_count,1)

    def test_runtime_change_blocks_execute_but_not_saved_evidence_readback(self):
        campaign,manifest,result=self.run_gate();self.assertTrue(result['accepted'])
        with patch.object(gate,'_runtime_capture',return_value={'changed':True}):
            self.assertTrue(gate.read_acceptance(root=self.root)['accepted'])
            with self.assertRaises(ValueError):gate.verify_frozen(campaign,manifest,for_execution=True)

    def mutate_after_process_check(self,name):
        original=gate._verify_process
        def wrapped(campaign,manifest,proof,**kwargs):
            usage=original(campaign,manifest,proof,**kwargs)
            path=campaign/name;value=gate._read(path)
            value['returncode' if name=='process_outcome.json' else 'pid' if name=='child_started.json' else 'peak_rss_bytes' if name=='child_usage.json' else 'manifest_identity']=1
            path.write_text(json.dumps(value)+'\n')
            return usage
        with patch.object(gate,'_verify_process',side_effect=wrapped):
            _,_,result=self.run_gate()
        self.assertFalse(result['accepted']);self.assertIn('campaign evidence differs',str(result['errors']))

    def test_late_process_outcome_replacement_refused(self):self.mutate_after_process_check('process_outcome.json')
    def test_late_child_pid_replacement_refused(self):self.mutate_after_process_check('child_started.json')
    def test_late_child_rss_replacement_refused(self):self.mutate_after_process_check('child_usage.json')
    def test_late_attempt_identity_replacement_refused(self):self.mutate_after_process_check('attempt.json')

    def test_all_same_domain_event_names_and_nested_mapping_refused(self):
        out=self.root/'runs/smt_fullfab_stage2'/gate.RUN_ID
        initial=[{'event':'stage_run_registered','registration':{'run_id':str(out),'registration_id':'R'}},
                 {'event':'reserve','run_id':str(out/'model_0'),'call_id':'C','registration_id':'R'},
                 {'event':'finish','call_id':'C'}]
        encode=lambda rows:b''.join((json.dumps(r)+'\n').encode() for r in rows)
        sealed=encode(initial)
        cases=[{'event':'note','registration_id':'R'}, {'event':'note','call_id':'C'},
               {'event':'note','run_id':str(out)},
               {'event':'mapping_added','mapping':{'parent_run_id':str(out),'registration_id':'X'}},
               {'event':'mapping_added','mapping':{'registration_id':'R'}},
               {'event':'finished','finalization':{'segment_run_id':str(out/'segment')}},
               {'event':'registered','registration':{'run_id':str(out),'registration_id':'X'}}]
        for extra in cases:
            with self.subTest(extra=extra):
                with self.assertRaisesRegex(ValueError,'attribution events'):
                    gate._ledger_unchanged_for_run(sealed,sealed+encode([extra]),out,'R')
        gate._ledger_unchanged_for_run(sealed,sealed+encode([{'event':'note','registration_id':'elsewhere','call_id':'other'}]),out,'R')

    def test_late_note_after_readback_is_failed_without_reanchoring(self):
        def append(*_):
            self.rows.append({'event':'note','call_id':'new-call','message':'post-snapshot'})
            self.sync_ledger()
        self.post_hook=append
        _,_,result=self.run_gate();self.assertFalse(result['accepted']);self.assertIn('attribution events',str(result['errors']))

    def test_late_nested_mapping_after_readback_is_failed(self):
        def append(*_):
            self.rows.append({'event':'mapping_added','mapping':{'registration_id':'new-registration','segment_run_id':str(self.root/'elsewhere')}})
            self.sync_ledger()
        self.post_hook=append
        _,_,result=self.run_gate();self.assertFalse(result['accepted'])

    def test_previously_verified_manifest_cannot_be_reanchored_after_last_freeze_check(self):
        real_evidence=gate._evidence
        def replace(campaign,run):
            path=campaign/'manifest.json';value=gate._read(path);value['origin_git_note']='changed after check'
            value['identity']=gate._digest({k:v for k,v in value.items() if k!='identity'})
            path.write_text(json.dumps(value)+'\n')
            return real_evidence(campaign,run)
        with patch.object(gate,'_evidence',side_effect=replace):_,_,result=self.run_gate()
        self.assertFalse(result['accepted']);self.assertIn('campaign evidence differs',str(result['errors']))

    def test_runtime_capture_hashes_wrapper_and_actual_executable(self):
        wrapper=self.root/'wrapper';binary=self.root/'binary'
        wrapper.write_bytes(b'exec actual-code "$@"');binary.write_bytes(b'synthetic executable A')
        # Bypass only the fixture runtime stub, never execute either file.
        with patch.object(gate,'CLI_PATH',str(wrapper)),patch.object(gate,'CLI_EXECUTABLE_PATH',str(binary)),patch.object(gate,'_runtime',return_value={}):
            first=REAL_RUNTIME_CAPTURE();binary.write_bytes(b'synthetic executable B');second=REAL_RUNTIME_CAPTURE()
        self.assertEqual(first['model_cli']['sha256'],second['model_cli']['sha256'])
        self.assertNotEqual(first['model_cli']['executable_sha256'],second['model_cli']['executable_sha256'])


class PayloadTests(unittest.TestCase):
    """Real small file/hash/checkpoint/bundle readers; attribution alone stubbed.

    This fixture is deliberately synthetic and does not claim a physical audit.
    No environment constructor, model transport or solver is called.
    """
    def setUp(self):
        from src.smt_fullfab import controller_delta as d, budget, environment, stream_audit_bundle as bundle
        self.d=d;self.bundle=bundle;self.environment=environment
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.root=Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.run=self.root/'runs/smt_fullfab_stage2'/gate.RUN_ID;self.run.mkdir(parents=True)
        for module,key in ((d,'ROOT'),(d,'DEFAULT_LEDGER'),(budget,'ROOT')):
            self.stack.enter_context(patch.object(module,key,getattr(module,key)))
        self.stack.enter_context(patch.object(environment.FullFabEnvironment,'__init__',side_effect=AssertionError('no real factory')))
        self.stack.enter_context(patch.object(environment,'snapshot_dependencies',return_value={'synthetic':'dependencies'}))
        source_paths=set(gate.AUDIT_DEPENDENCIES)|{'src/smt_fullfab/stream_audit_bundle.py','src/smt/environment.py','src/__init__.py','requirements.lock',gate.DATA+'/input.txt'}
        inputs={}
        for relative in source_paths:
            data=('synthetic '+relative).encode();inputs[relative]=__import__('hashlib').sha256(data).hexdigest()
            if relative.startswith('src/'):
                path=self.run/'source_snapshot'/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        self.inputs=inputs;source_sha=gate._digest(inputs)
        self.manifest={'origin_root':str(self.root),'frozen_input_sha256':inputs,'source_sha256':source_sha,
                       'origin_git_head':'1'*40,'runtime':{'model_cli':{'path':gate.CLI_PATH}}}
        cfg={'schema':d.SCHEMA,'arm':'B','run_id':gate.RUN_ID,'seed':1701,'seconds':3600,'source_sha256':source_sha,
            'max_calls':None,'max_tokens':None,'per_call_timeout_seconds':180,'wall_seconds':float(gate.CHILD_SECONDS),
            'max_log_bytes':gate.MAX_BYTES,'max_trace_bytes':gate.TRACE_BYTES,'page_chars':45000,'plan_seconds':14400,'lookahead_depth':2,
            'period_seconds':1800,'solver_budget_seconds':0,'constructor_enabled':False,'audit_mode':'stream','snapshot_mode':'stream',
            'cold_start_only':True,'automatic_retry':False,'formal':False,'budget_id':gate._read(gate.ROOT/gate.APPROVAL)['budget_id'],
            'amendment_id':gate._read(gate.ROOT/gate.WAIVER)['amendment_id'],'resource_acceptance_requires_external_gate':True}
        self.write('config.json',cfg)
        self.write('source_manifest.json',{'files':inputs,'source_sha256':source_sha,'canonical_hash_convention':gate.SOURCE_CONVENTION})
        self.write('provenance.json',{'source_sha256':{k:v for k,v in inputs.items() if Path(k).parent.as_posix() in ('src/smt','src/smt_fullfab') and k.endswith('.py')},'requirements_sha256':inputs['requirements.lock'],'git_commit':'1'*40})
        (self.run/'trace.jsonl').write_bytes(b'{"kind":"terminal","time":3600}\n')
        self.receipt={'sha256':gate._sha(self.run/'trace.jsonl'),'byte_count':(self.run/'trace.jsonl').stat().st_size}
        source={'valid':True,'errors':[],'production_machine_count':913,'declared_control_machine_count':913,'declared_full_factory_domain':True,
                '_source_evidence':{'source_receipt':self.receipt,'complete_jsonl_pass':True}}
        members={}
        for name in bundle.MEMBERS:
            self.write('audit_bundle/'+name,source if name=='source.json' else {'synthetic_member':name})
            path=self.run/'audit_bundle'/name;members[name]={'sha256':gate._sha(path),'bytes':path.stat().st_size}
        self.summary={k:True for k in ('valid','source_valid','opportunity_valid','physical_valid','actual_dispatch_provenance_complete',
            'complete_physical_window_certified','absence_of_unreported_legal_demand_certified','verified_input_hashes')}
        self.summary['metrics']={'window_start':0,'window_end':3600,'throughput_lots':0,'weighted_tardy_lot_hours':0,'terminal_wip_lots':1,'terminal_tardy_wip_lots':0}
        self.report={'schema':bundle.SCHEMA,'status':'complete','summary':self.summary,'members':members,'source_receipt':self.receipt,
            'envelope':{'terminal_at_eof':True,'first_time':0,'last_time':3600,'horizon':3600,'receipt':self.receipt},
            'configuration':{'window_start':0,'priority_weights':None,'require_terminal':True,'verify_data_dir_supplied':True},
            'dependency_sha256':{k:inputs[k] for k in gate.AUDIT_DEPENDENCIES},'bundle_source_sha256':inputs['src/smt_fullfab/stream_audit_bundle.py']}
        self.write('audit_bundle/audit_bundle.json',self.report)
        (self.run/'model_00000').mkdir();(self.run/'call_00000').mkdir();(self.run/'plan_00000/durable').mkdir(parents=True)
        (self.run/'plan_00000/durable/ledger.sqlite3').write_bytes(b'synthetic durable DB; replay is explicitly stubbed')
        self.write('call_00000/intent.json',{'config':{'codex_binary':gate.CLI_PATH}})
        self.account={'attempts':1,'pending':[],'unknown_completed':['C']}
        (self.root/gate.LEDGER).parent.mkdir(parents=True)
        raw=(json.dumps({'event':'reserve','run_id':str(self.run/'model_00000'),'registration_id':'R','call_id':'C'})+'\n'+json.dumps({'event':'finish','call_id':'C'})+'\n').encode()
        (self.root/gate.LEDGER).write_bytes(raw);(self.run/'ledger_final.jsonl').write_bytes(raw)
        self.resources={'account':self.account,'ledger_sha256':gate._sha(self.run/'ledger_final.jsonl'),'reserve_call_ids':['C'],'solver_call_ids':[],'constructor_call_ids':[]}
        self.write('ledger_final_account.json',self.resources)
        self.write('resource_registration.json',{'run_id':str(self.run),'registration_id':'R','arm':'B','scenario':1701,'window_seconds':3600,'solver_seconds':0,'wall_seconds':gate.CHILD_SECONDS,'max_log_bytes':gate.MAX_BYTES})
        self.rows=[{'event':'call_finished','payload':{'model_index':0,'intent_sha256':gate._sha(self.run/'call_00000/intent.json')}},
            {'event':'plan_closed','payload':{'plan_index':0,'durable_prefix':{'database_sha256':gate._sha(self.run/'plan_00000/durable/ledger.sqlite3')}}},
            {'event':'run_stopped','payload':{'account_report_sha256':gate._sha(self.run/'ledger_final_account.json')}}]
        (self.run/'delta_index.jsonl').write_bytes(b''.join((json.dumps(r)+'\n').encode() for r in self.rows))
        self.attribution={'valid':True,'source_receipt':self.receipt,'index_sha256':gate._sha(self.run/'delta_index.jsonl'),
            'source_sha256':source_sha,'unknown_usage_call_ids':['C'],'reserve_call_ids':['C'],'model_calls':1,'plans':[{}]}
        self.write('delta_attribution_audit.json',self.attribution)
        self.stack.enter_context(patch.object(d,'audit_delta_run',side_effect=lambda *a,**k:deepcopy(self.attribution)))
        self.stack.enter_context(patch.object(d,'read_index',return_value=self.rows))
        self.stack.enter_context(patch.object(d,'read_account_evidence',return_value=self.resources))
        state={k:{} for k in ('seed','horizon','t','seq','dispatch_id','decisions','releases','completed','finished','wait_until','lots','machine_state','jobs','calendars','pm_counters','queue_area','last_area_t','manifest','plan','observation_start','q','waiting','processing_by_machine','stats','executed_tasks','plan_versions','trace')}
        state.update(seed=1701,horizon=3600,t=3600,observation_start=0,finished=True,manifest={'data_hashes':{'input.txt':inputs[gate.DATA+'/input.txt']}},trace=[{'kind':'terminal','time':3600}])
        self.snapshot={'schema':'smt-fullfab-snapshot-1','version':environment.VERSION,'implementation_sha256':{'synthetic':'dependencies'},'physics_sha256':inputs['src/smt/environment.py'],'data_hashes':state['manifest']['data_hashes'],'state':state,'state_sha256':gate._digest(state)}
        self.write('checkpoint.json',self.snapshot)
        self.result={'config':cfg,'identity':gate._digest(cfg),'status':'completed','failure':None,'finalization_errors':[],'accepted':False,'formal':False,'simulation_seconds':3600,'audit_valid':True,'delta_attribution_valid':True,'solver_calls':0,'constructor_calls':0,'end_to_end_wall_seconds':10,
            'audit_bundle':{'path':'audit_bundle','manifest_sha256':gate._sha(self.run/'audit_bundle/audit_bundle.json')},'metrics':self.summary['metrics'],
            'index_sha256':self.attribution['index_sha256'],'model_calls':1,'local_bridge_attempts':1,'returned_bridge_attempts':1,'next_local_model_index':1,'model_account':self.account,'pending_call_ids':[],'unknown_usage_call_ids':['C'],'reserve_call_ids':['C'],'plans':1,
            'checkpoint':{'path':'checkpoint.json','state_sha256':self.snapshot['state_sha256'],'file_sha256':gate._sha(self.run/'checkpoint.json')}}
        self.write('result.json',self.result)

    def write(self,name,value):
        p=self.run/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,separators=(',',':'))+'\n')
    def verify(self):return gate._verification_payload(self.run,self.manifest)
    def update_bundle(self):
        self.write('audit_bundle/audit_bundle.json',self.report)
        self.result['audit_bundle']['manifest_sha256']=gate._sha(self.run/'audit_bundle/audit_bundle.json');self.write('result.json',self.result)
    def update_checkpoint(self):
        self.snapshot['state_sha256']=gate._digest(self.snapshot['state']);self.write('checkpoint.json',self.snapshot)
        self.result['checkpoint'].update(state_sha256=self.snapshot['state_sha256'],file_sha256=gate._sha(self.run/'checkpoint.json'));self.write('result.json',self.result)

    def test_actual_bundle_and_checkpoint_readers_bind_every_terminal_file(self):
        result=self.verify();self.assertTrue(result['valid']);self.assertFalse(result['checkpoint']['restoration_executed'])
        self.assertEqual(result['verified_evidence_sha256'],{'run/'+p.relative_to(self.run).as_posix():gate._sha(p) for p in gate._files(self.run)})
        self.assertEqual(result['result']['unknown_usage_call_ids'],['C'])
    def test_incomplete_terminal_refused_even_with_complete_result(self):
        self.report['envelope']['terminal_at_eof']=False;self.update_bundle()
        with self.assertRaisesRegex(ValueError,'terminal'):self.verify()
    def test_missing_machine_refused_even_with_valid_summary(self):
        path=self.run/'audit_bundle/source.json';value=gate._read(path);value['declared_control_machine_count']=912;self.write('audit_bundle/source.json',value)
        self.report['members']['source.json'].update(sha256=gate._sha(path),bytes=path.stat().st_size);self.update_bundle()
        with self.assertRaisesRegex(ValueError,'913'):self.verify()
    def test_opportunity_failure_cannot_be_overridden_by_result_audit_true(self):
        self.report['summary']['opportunity_valid']=False;self.update_bundle()
        with self.assertRaisesRegex(ValueError,'913'):self.verify()
    def test_missing_checkpoint_fields_refused_after_recomputed_hash(self):
        del self.snapshot['state']['jobs'];self.update_checkpoint()
        with self.assertRaisesRegex(ValueError,'state fields'):self.verify()
    def test_checkpoint_different_raw_trace_refused(self):
        self.snapshot['state']['trace'][0]['time']=3599;self.update_checkpoint()
        with self.assertRaisesRegex(ValueError,'checkpoint history'):self.verify()
    def test_orphan_model_directory_and_cost_count_refused(self):
        (self.run/'model_00001').mkdir()
        with self.assertRaisesRegex(ValueError,'orphan'):self.verify()
    def test_pending_original_call_cannot_count_as_closed(self):
        self.account['pending']=['C'];self.resources['account']=self.account
        with self.assertRaisesRegex(ValueError,'cost counts'):self.verify()
    def test_actual_call_cannot_use_an_unfrozen_cli_wrapper(self):
        self.write('call_00000/intent.json',{'config':{'codex_binary':'/different/cli'}})
        self.rows[0]['payload']['intent_sha256']=gate._sha(self.run/'call_00000/intent.json')
        with self.assertRaisesRegex(ValueError,'different model CLI'):self.verify()


class VersionBoundaryTests(unittest.TestCase):
    def test_source_diff_is_only_explicit_new_version_and_prior_counter(self):
        original=Path(gate.__file__).with_name('B_delta_gate.py').read_bytes()
        self.assertEqual(__import__('hashlib').sha256(original).hexdigest(),'398f18b89cb834f0e01c576a0326e8b8c9c80ef46ff8375e1af115ee3af068dd')
        replacements=[(b"RUN_ID='B_1701_1h_delta_v1'",b"RUN_ID='B_1701_1h_delta_v2'"),
            (b"PROTOCOL='configs/smt_fullfab/B_delta_1h_v1.protocol.json'",b"PROTOCOL='configs/smt_fullfab/B_delta_1h_v2.protocol.json'"),
            (b"SCHEMA='smt-fullfab-B-delta-gate-v1'",b"SCHEMA='smt-fullfab-B-delta-gate-v2'"),
            (b'PRIOR_ATTEMPTS=240',b'PRIOR_ATTEMPTS=241'),(b"'B_delta_gate.py'",b"'B_delta_gate_v2.py'"),
            (b'from src.smt_fullfab.B_delta_gate import _verification_payload',b'from src.smt_fullfab.B_delta_gate_v2 import _verification_payload')]
        for before,after in replacements:
            self.assertEqual(original.count(before),1);original=original.replace(before,after)
        self.assertEqual(Path(gate.__file__).read_bytes(),original)

    def test_protocol_preserves_all_resource_limits_and_old_identity_is_rejected(self):
        from src.smt_fullfab import B_delta_gate as old
        original=gate._read(gate.ROOT/old.PROTOCOL);new=gate._read(gate.ROOT/gate.PROTOCOL)
        old_limits=deepcopy(original['limits']);old_limits['minimum_preserved_prior_model_attempts']=241
        self.assertEqual(new['limits'],old_limits)
        old_run=deepcopy(original['run_parameters']);old_run['run_id']=gate.RUN_ID
        self.assertEqual(new['run_parameters'],old_run)
        with self.assertRaises(ValueError):gate._config(original)
        with self.assertRaises(ValueError):old._config(new)
        self.assertIsNone(new['limits']['max_calls']);self.assertIsNone(new['limits']['max_tokens'])
        self.assertTrue(new['new_registration_context']['new_independent_registration'])
        self.assertFalse(new['new_registration_context']['automatic_retry_or_resume'])
        self.assertIn('require_escalated',new['new_registration_context']['execution_requirement'])

    def test_previous_gate_and_contract_source_remain_byte_identical(self):
        expected={'src/smt_fullfab/B_delta_gate.py':'398f18b89cb834f0e01c576a0326e8b8c9c80ef46ff8375e1af115ee3af068dd',
            'configs/smt_fullfab/B_delta_1h_v1.protocol.json':'f9e7138601c01257541df5028d7729e4d629ba7534d91760fedff712c9126e94',
            'tests/test_smt_fullfab_B_delta_gate.py':'0df5357a10cfa1c96894ffeafd8398b9c6c41d127e72e0cf6a4dea5e8fed12ca'}
        for path,digest in expected.items():self.assertEqual(gate._sha(gate.ROOT/path),digest)


if __name__=='__main__':unittest.main()
