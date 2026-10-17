"""New B gate tiny fixtures: no real model/factory/solver/ledger or subprocess.

Gate helpers and full guard-caller orchestration run only on temporary files;
common guard and physical algorithms are mocked explicitly, not certified here.
Authored statically; first execution belongs to the root's serial test window.
"""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import patch

from src.smt_fullfab import B_delta_gate_v4 as g
import src.smt_fullfab as package

def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def protocol():
    return json.loads((Path(g.__file__).resolve().parents[2]/g.PROTOCOL).read_text())


def ledger_fixture(root, *, unknown=3):
    approval={'budget_id':'tiny','model':'gpt-6-astra','reasoning_effort':'medium'}
    waiver={'amendment_id':'tiny-research','authorization':'approved_by_user'}
    for name,value in ((g.APPROVAL,approval),(g.WAIVER,waiver)):
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(g.encoded(value))
    rows=[{'event':'approval','approval':approval},{'event':'research_limit_waiver','amendment':waiver}]
    for i in range(g.PRIOR_ATTEMPTS):
        rows.append({'event':'reserve','call_id':f'm{i}','run_id':str(root/'other_run')})
        usage=None if i<unknown else {'input_tokens':2,'output_tokens':1}
        rows.append({'event':'finish','call_id':f'm{i}','status':'failed' if i<unknown else 'success',
                     'details':{'usage':usage,'duration_seconds':.01}})
    return rows


def raw_rows(rows):
    return b''.join(g.encoded(row) for row in rows)




class OriginalByteBindingTests(unittest.TestCase):
    def test_same_raw_bytes_parse_and_hash_preserve_whitespace(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.json';raw=b' { "v" : 1.0 } \n';p.write_bytes(raw)
            value,receipt=g.read_json(p,sha(raw))
            self.assertEqual(value,{'v':1.0});self.assertIs(type(value['v']),float)
            self.assertEqual(receipt['sha256'],sha(raw));self.assertEqual(receipt['bytes'],len(raw))

    def test_wrong_expected_sha_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x';p.write_bytes(b'{}\n')
            with self.assertRaises(ValueError):g.read_json(p,'0'*64)

    def test_duplicate_and_nonfinite_json_rejected(self):
        for raw in (b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":Infinity}'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):g.strict(raw)

    def test_symlink_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x';p.write_text('{}');q=Path(d)/'link';q.symlink_to(p)
            with self.assertRaises((ValueError,OSError)):g.read_json(q)

    def test_replacement_after_fd_read_is_not_reanchored(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x';p.write_bytes(b'{"v":1}\n');real=Path.lstat;calls=0
            def changed(path,*args,**kwargs):
                nonlocal calls
                if path==p:
                    calls+=1
                    if calls==2:
                        q=p.with_name('replace');q.write_bytes(b'{"v":2}\n');os.replace(q,p)
                return real(path,*args,**kwargs)
            with patch.object(Path,'lstat',changed),self.assertRaises(ValueError):g.read_json(p)

    def test_create_new_will_not_overwrite_previous_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x';first=g.write_new(p,{'v':1});old=p.read_bytes()
            with self.assertRaises(FileExistsError):g.write_new(p,{'v':2})
            self.assertEqual(p.read_bytes(),old);self.assertEqual(first,sha(old))

    def test_all_first_raw_run_hashes_required(self):
        first={'run/result.json':'a','run/audit_bundle/physical.json':'b','campaign/manifest.json':'c'}
        g.bind_first(first,{**first,'campaign/new-proof.json':'d'})
        for key in first:
            actual={**first,key:'replaced'}
            with self.subTest(key=key),self.assertRaises(ValueError):g.bind_first(first,actual)

    def test_extra_raw_run_file_rejects_after_validation(self):
        first={'run/result.json':'a'}
        with self.assertRaises(ValueError):g.bind_first(first,{**first,'run/late.json':'b'})

    def test_first_parsed_proof_not_later_self_consistent_replacement(self):
        original={'campaign/verification_payload.json':'original-verified','campaign/restoration_payload.json':'original-restored'}
        for key in original:
            with self.subTest(key=key),self.assertRaises(ValueError):g.bind_receipts(original,{**original,key:'replacement'})

    def test_external_source_and_phase_proof_sha_in_child_arguments(self):
        manifest={'launcher_executable':'/python','identity':'original'}
        command=g._phase_command('/campaign',manifest,'restore','/first','/proof',first_sha='a'*64,proof_sha='b'*64)
        self.assertEqual(command[-7:],['restore','/campaign','original','/first','/proof','a'*64,'b'*64])




class LedgerTests(unittest.TestCase):
    def test_historical_unknown_calls_are_preserved_not_zeroed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);rows=ledger_fixture(root);raw=raw_rows(rows)
            report=g.ledger_preflight(raw,root)
            self.assertEqual(report['original_model_attempts'],260)
            self.assertEqual(report['original_unknown_call_ids'],['m0','m1','m2'])
            self.assertEqual(report['prefix_sha256'],sha(raw));self.assertEqual(report['prefix_bytes'],len(raw))

    def test_pending_any_resource_blocks_new_run(self):
        for event in ('reserve','solver_reserve','constructor_reserve'):
            with self.subTest(event=event),tempfile.TemporaryDirectory() as d:
                root=Path(d);rows=ledger_fixture(root)+[{'event':event,'call_id':'pending'}]
                with self.assertRaises(ValueError):g.ledger_preflight(raw_rows(rows),root)

    def test_reset_prior_attempts_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);rows=ledger_fixture(root)[:-2]
            with self.assertRaises(ValueError):g.ledger_preflight(raw_rows(rows),root)

    def test_erased_unknown_history_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);rows=ledger_fixture(root,unknown=0)
            with self.assertRaises(ValueError):g.ledger_preflight(raw_rows(rows),root)

    def test_bool_negative_and_null_usage_never_known(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);rows=ledger_fixture(root)
            finishes=[r for r in rows if r['event']=='finish']
            for i,value in enumerate((True,-1,1.0,None),start=3):
                finishes[i]['details']['usage']={'input_tokens':value,'output_tokens':1}
            value=g.ledger_preflight(raw_rows(rows),root)
            self.assertEqual(value['original_unknown_call_ids'],['m'+str(i) for i in range(7)])

    def test_wrong_resource_finish_type_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);rows=ledger_fixture(root);rows[3]['event']='solver_finish'
            with self.assertRaises(ValueError):g.ledger_preflight(raw_rows(rows),root)

    def test_duplicate_finish_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);rows=ledger_fixture(root);rows.append(deepcopy(rows[-1]))
            with self.assertRaises(ValueError):g.ledger_preflight(raw_rows(rows),root)

    def test_existing_run_nested_registration_blocks_retry(self):
        for key in ('registration','mapping','finalization'):
            with self.subTest(key=key),tempfile.TemporaryDirectory() as d:
                root=Path(d);rows=ledger_fixture(root)
                rows.append({'event':'note',key:{'run_id':str(root/'runs/smt_fullfab_stage2'/g.RUN_ID)}})
                with self.assertRaises(ValueError):g.ledger_preflight(raw_rows(rows),root)

    def test_same_domain_late_note_and_call_id_only_event_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);run=root/'run';run.mkdir();ledger=root/'ledger.jsonl'
            rows=[{'event':'stage_run_registered','registration':{'run_id':str(run),'registration_id':'reg'}},
                  {'event':'reserve','run_id':str(run),'call_id':'call'},
                  {'event':'finish','call_id':'call'}]
            raw=raw_rows(rows);(run/'ledger_final.jsonl').write_bytes(raw)
            for extra in ({'event':'note','run_id':str(run)}, {'event':'note','call_id':'call'},
                          {'event':'note','mapping':{'registration_id':'reg'}}):
                ledger.write_bytes(raw+g.encoded(extra))
                with self.subTest(extra=extra),self.assertRaises(ValueError):
                    g._final_ledger(run,{'actual_ledger_path':str(ledger)},sha(raw),'reg')

    def test_unrelated_domain_suffix_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);run=root/'run';run.mkdir();ledger=root/'ledger.jsonl'
            raw=raw_rows([{'event':'reserve','run_id':str(run),'call_id':'mine'}, {'event':'finish','call_id':'mine'}])
            (run/'ledger_final.jsonl').write_bytes(raw)
            ledger.write_bytes(raw+g.encoded({'event':'note','run_id':str(root/'other'),'call_id':'other'}))
            g._final_ledger(run,{'actual_ledger_path':str(ledger)},sha(raw),'reg')




class GuardedPhaseTests(unittest.TestCase):
    """Mocked owner-pipe caller paths; the real common guard has its own suite."""
    def test_guard_failure_is_recorded_without_success_or_second_process(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(g,'run_guarded',side_effect=KeyboardInterrupt('primary owner interruption')) as guard:
                result=g.owned_phase(['/dummy'],cwd=d,output=Path(d)/'phase',timeout=1)
            self.assertEqual(result['primary_failure']['message'],'primary owner interruption')
            self.assertIsNone(result['returncode']);self.assertIsNone(result['guard_evidence'])
            self.assertTrue(result['cleanup_errors']);self.assertEqual(guard.call_count,1)

    def test_original_process_sha_is_not_reanchored_after_return(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();phase=root/'phase'
            fake={'command_returncode':0,'timed_out':False,'launch_error':None,
                  'command_peak_rss_bytes':1024,'guard_peak_rss_bytes':2048,
                  'files_sha256':{},'output_files_sha256':{}}
            with patch.object(g,'run_guarded',return_value=fake) as guard:
                result=g.owned_phase(['/dummy'],cwd=d,output=phase,timeout=600)
            self.assertEqual(result['peak_rss_bytes'],2048)
            self.assertTrue(result['detached_model_guard_integrated'])
            original=result['process_sha256'];(phase/'process.json').write_text('{"replaced":true}')
            anchors=g.phase_anchors(root,result)
            self.assertEqual(anchors['campaign/phase/process.json'],original)
            self.assertNotEqual(original,sha((phase/'process.json').read_bytes()))
            args=guard.call_args.kwargs
            self.assertEqual(args['timeout_seconds'],600)
            self.assertEqual(args['io_spec']['inputs']['approved_phase_request'],str(phase/'phase_request.json'))

    def test_existing_optional_output_is_rejected_before_guard(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);old=root/'old.json';old.write_text('{}')
            with patch.object(g,'run_guarded') as guard,self.assertRaises(ValueError):
                g.owned_phase(['/dummy'],cwd=d,output=root/'phase',timeout=600,output_paths={'terminal':old})
            guard.assert_not_called();self.assertEqual(old.read_text(),'{}')

    def test_checkpoint_storage_check_counts_scratch_and_trace(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);campaign=root/'campaign';run=root/'run';campaign.mkdir();run.mkdir()
            scratch=campaign/'scratch';scratch.mkdir();(scratch/'index').write_bytes(b'123456')
            with patch.object(g,'MAX_BYTES',5),self.assertRaises(ValueError):g.check_storage(campaign,run)
            (run/'trace.jsonl').write_bytes(b'123456')
            with patch.object(g,'TRACE_BYTES',5),self.assertRaises(ValueError):g.check_storage(campaign,run)

    def test_outer_live_directory_excluded_only_from_supervisor_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);campaign=root/'campaign';run=root/'run';campaign.mkdir();run.mkdir()
            outer=campaign/'outer_process';outer.mkdir();(outer/'partial').write_text('x');(campaign/'fixed').write_text('y')
            self.assertNotIn('campaign/outer_process/partial',g.evidence(campaign,run))
            self.assertIn('campaign/outer_process/partial',g.evidence(campaign,run,include_outer=True))




def success_fixture():
    process={'returncode':0,'primary_failure':None,'cleanup_errors':[],'wall_seconds':1.0,
             'peak_rss_bytes':128,'limit_seconds':2.0}
    manifest={'identity':'m','protocol_sha256':'p'}
    value={'schema':g.SCHEMA+'-acceptance','run_id':g.RUN_ID,'manifest_identity':'m','protocol_sha256':'p',
        'accepted':True,'status':'success','errors':[],'formal':False,'automatic_retry':False,
        'outer_wall_seconds_through_receipt_preparation':20.0,'final_total_bytes_including_acceptance':123,
        'child_process':deepcopy(process),'readback_process':deepcopy(process),'restoration_process':deepcopy(process),
        'outer_process':deepcopy(process),'readback_wall_seconds':3.0,'full_supervisor_exit_verified':True,
        'restoration':{'valid':True,'simulation_seconds':3600.0,'production_scope':913,
          'simulation_advancement_performed':False,'model_calls':0,'solver_calls':0},
        'verified_evidence_sha256':{'run/result.json':'r'},'runner_result_sha256':'r'}
    return value,manifest




class AcceptancePredicateTests(unittest.TestCase):
    def test_all_original_success_conditions_required(self):
        value,manifest=success_fixture();g.validate_success(value,manifest)

    def test_self_consistent_accepted_flag_does_not_erase_errors(self):
        value,manifest=success_fixture();value['errors']=[{'type':'OriginalFailure'}]
        with self.assertRaises(ValueError):g.validate_success(value,manifest)

    def test_failed_status_cannot_be_accepted(self):
        value,manifest=success_fixture();value['status']='failed'
        with self.assertRaises(ValueError):g.validate_success(value,manifest)

    def test_outer_wall_or_bytes_overrun_cannot_pass(self):
        for key,value in (('outer_wall_seconds_through_receipt_preparation',g.OUTER_SECONDS+.01),
                          ('final_total_bytes_including_acceptance',g.MAX_BYTES+1),
                          ('final_total_bytes_including_acceptance',True)):
            good,manifest=success_fixture();good[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):g.validate_success(good,manifest)

    def test_readback_and_restoration_share_600_seconds(self):
        value,manifest=success_fixture();value['readback_wall_seconds']=601
        with self.assertRaises(ValueError):g.validate_success(value,manifest)

    def test_own_remaining_phase_deadline_is_enforced(self):
        value,manifest=success_fixture();value['child_process']['limit_seconds']=.5
        with self.assertRaises(ValueError):g.validate_success(value,manifest)

    def test_original_nonzero_child_or_missing_restore_rejected(self):
        for key in ('child_process','readback_process','restoration_process','outer_process'):
            value,manifest=success_fixture();value[key]['returncode']=1
            with self.subTest(key=key),self.assertRaises(ValueError):g.validate_success(value,manifest)
        value,manifest=success_fixture();value['restoration']['valid']=False
        with self.assertRaises(ValueError):g.validate_success(value,manifest)

    def test_original_result_anchor_and_exact_scope_required(self):
        value,manifest=success_fixture();value['runner_result_sha256']='replacement'
        with self.assertRaises(ValueError):g.validate_success(value,manifest)
        value,manifest=success_fixture();value['restoration']['production_scope']=912
        with self.assertRaises(ValueError):g.validate_success(value,manifest)

    def test_terminal_encoding_rechecks_clock_without_time_value_fixed_point(self):
        # Both publishers share this exact encoding routine. Only a tiny dict
        # and fake clock are used; no campaign, process or original ledger.
        original_encoded=g.encoded
        for schema in (g.SCHEMA+'-acceptance',g.SCHEMA+'-supervisor-result'):
            for stage in ('encoding','validation','already_crossed_after_inventory'):
                with self.subTest(schema=schema,stage=stage):
                    now=[float(g.OUTER_SECONDS)-1.0]
                    if stage=='already_crossed_after_inventory':now[0]+=2.0
                    value={'schema':schema,'errors':[],'final_total_bytes_including_acceptance':0,
                           'outer_wall_seconds_through_receipt_preparation':1.0}
                    calls=[0]
                    def encoding(item):
                        raw=original_encoded(item);calls[0]+=1
                        if stage=='encoding':now[0]=float(g.OUTER_SECONDS)+1.0
                        return raw
                    def validated(item):
                        if stage=='validation':now[0]=float(g.OUTER_SECONDS)+1.0
                    with patch.object(g,'encoded',side_effect=encoding):
                        raw=g._terminal_encoding(value,100,lambda:now[0],success_validator=validated)
                    self.assertFalse(value['accepted']);self.assertEqual(value['status'],'failed')
                    self.assertGreater(value['outer_wall_seconds_through_receipt_preparation'],g.OUTER_SECONDS)
                    self.assertEqual([e['type'] for e in value['errors']],['OuterTimeLimit'])
                    self.assertEqual(json.loads(raw),value)
                    self.assertEqual(value['identity'],g.digest({k:v for k,v in value.items() if k!='identity'}))
                    self.assertEqual(value['final_total_bytes_including_acceptance'],100+len(raw))
                    self.assertLessEqual(calls[0],32)
            # A changing timestamp need not equal its previous value to finish.
            now=[1.0];value={'schema':schema,'errors':[],'final_total_bytes_including_acceptance':0}
            def advancing():now[0]+=1.0;return now[0]
            raw=g._terminal_encoding(value,100,advancing)
            self.assertTrue(value['accepted']);self.assertEqual(json.loads(raw),value)
            self.assertEqual(value['final_total_bytes_including_acceptance'],100+len(raw))

    def test_read_acceptance_recomputes_predicates_after_self_consistent_hash(self):
        # Pure structural reproduction of review G3, no factory or real evidence.
        for bad_key,bad_value in (('errors',[{'type':'OriginalFailure'}]),('status','failed'),
                                  ('outer_wall_seconds_through_receipt_preparation',22201)):
            with self.subTest(key=bad_key),tempfile.TemporaryDirectory() as d:
                root=Path(d);campaign=root/g.AREA/g.RUN_ID;run=root/'run'
                value,manifest=success_fixture();manifest['output_directory']=str(run)
                value.update(evidence_sha256={'run/result.json':'r'},first_parsed_phase_proof_sha256={})
                value[bad_key]=bad_value
                value['identity']=g.digest(value)
                def reader(path,*args,**kwargs):
                    if Path(path).name=='manifest.json':return manifest,{'sha256':'m'}
                    if Path(path).name=='acceptance.json':return value,{'sha256':'a'}
                    raise AssertionError('invalid predicate should reject before later reads')
                with patch.object(g,'LAUNCH_BLOCKERS',()),patch.object(g,'read_json',side_effect=reader), \
                     patch.object(g,'verify_frozen'),patch.object(g,'evidence',return_value=value['evidence_sha256']), \
                     patch.object(g,'total_bytes',return_value=123):
                    result=g.read_acceptance(root=root)
                self.assertFalse(result['valid']);self.assertFalse(result['accepted'])




class BProtocolTests(unittest.TestCase):
    def test_fixed_B1h_resource_preservation_and_waiver(self):
        p=protocol();self.assertEqual(g.validate_protocol(p),g.PARAMETERS)
        self.assertEqual((g.CHILD_SECONDS,g.OUTER_SECONDS,g.READBACK_SECONDS,g.RESTORE_SECONDS),(21600,22200,600,180))
        self.assertEqual((g.MAX_BYTES,g.MIN_FREE_BYTES,g.TRACE_BYTES,g.RSS_BYTES),(16*1024**3,40*1024**3,2*1024**3,8*1024**3))
        self.assertIsNone(p['limits']['global_max_calls']);self.assertIsNone(p['limits']['global_max_tokens'])
        self.assertEqual((p['limits']['solver_seconds'],p['limits']['constructor_seconds']),(0,0))
        self.assertEqual(p['historical_fact_reference']['attempts'],260)
        self.assertFalse(p['historical_fact_reference']['is_allowance'])

    def test_arbitrary_scope_cap_or_type_change_is_refused(self):
        for key,value in (('global_max_calls',12),('global_max_tokens',240000),('solver_seconds',1),
                          ('restore_seconds_within_readback',181),('child_seconds',21600.0),
                          ('period_is_absolute',1),('per_call_timeout_seconds',181)):
            p=protocol();p['limits'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):g.validate_protocol(p)
        p=protocol();p['run_parameters']['seconds']=3600.0
        with self.assertRaises(ValueError):g.validate_protocol(p)

    def test_unanchored_prerequisite_or_escape_is_refused(self):
        p=protocol();p['prerequisite_roles']['endpoint_tests']='outside.json'
        with self.assertRaises(ValueError):g.validate_protocol(p)
        p=protocol();p['additional_frozen_files']=['../escape']
        with self.assertRaises(ValueError):g.validate_protocol(p)

    def test_source_subset_matches_controller_scope_not_prerequisite_reports(self):
        inputs={'src/z.py':'z',g.VENDOR+'/v.py':'v',g.DATA+'/d.txt':'d','requirements.lock':'r',
                g.PROTOCOL:'p',g.APPROVAL:'a',g.WAIVER:'w','artifacts/prerequisite.json':'q'}
        self.assertEqual(g.source_inputs(inputs),{k:inputs[k] for k in ('src/z.py',g.VENDOR+'/v.py',g.DATA+'/d.txt','requirements.lock')})

    def test_public_and_private_execute_block_before_process(self):
        with patch.object(g,'LAUNCH_BLOCKERS',('pending independent gate tests',)),patch.object(g,'run_guarded') as runner:
            for method in (g.execute,g._execute_reviewed):
                with self.subTest(method=method.__name__),self.assertRaises(ValueError):method('/absent',{})
            runner.assert_not_called()

    def test_full_failure_inventory_includes_optional_guard_cleanup_error(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);run=root/'run';campaign=root/'campaign';campaign.mkdir();(run/'model_00000/process_guard').mkdir(parents=True)
            path=run/'model_00000/process_guard/cleanup_errors.json';path.write_bytes(b'{"error":"retained"}')
            self.assertEqual(g.evidence(campaign,run)['run/model_00000/process_guard/cleanup_errors.json'],sha(path.read_bytes()))


class GateCallerFlowTests(unittest.TestCase):
    """Actual execute -> owned_phase -> _worker -> privatecore caller contract.

    Only run_guarded/process proof, controller body and semantic check bodies are
    mocked. The production gate's phase requests, byte anchoring, deadlines,
    root/ledger routing, terminal predicates, final inventory and replay run.
    No mock semantic proof here purports to certify physical feasibility.
    """
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.root=Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        for relative in ('src/smt_fullfab','src/smt',g.DATA,g.VENDOR,'configs/smt_fullfab','progress/smt_fullfab','runs'):
            (self.root/relative).mkdir(parents=True,exist_ok=True)
        for relative in ('src/__init__.py','src/smt/__init__.py','src/smt_fullfab/__init__.py'):(self.root/relative).write_text('')
        for name in ('B_delta_gate_v4.py','B_delta_gate_v3.py','offline_pilot.py','offline_A_gate_v3.py','model_process_guard.py'):
            (self.root/'src/smt_fullfab'/name).write_bytes(Path(g.__file__).with_name(name).read_bytes())
        (self.root/g.DATA/'tiny.txt').write_text('synthetic input, never loaded')
        (self.root/g.VENDOR/'tiny.py').write_text('# no imports')
        (self.root/'requirements.lock').write_text('# synthetic requirements')
        p=protocol()
        for relative in p['prerequisite_sha256']:
            path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('{}')
        (self.root/g.PROTOCOL).write_bytes(g.encoded(p))
        self.rows=ledger_fixture(self.root);self.ledger=self.root/g.LEDGER;self.sync_ledger()
        self.stack.enter_context(patch.object(g,'prerequisite_proof',return_value={'synthetic_only':True}))
        self.stack.enter_context(patch.object(g,'_origin_git',return_value='1'*40))
        self.stack.enter_context(patch.object(g,'runtime_capture',return_value={'synthetic_runtime':True}))
        self.stack.enter_context(patch.object(g,'_active_with_finalizers',return_value=[]))
        self.stack.enter_context(patch.object(g.shutil,'disk_usage',return_value=SimpleNamespace(free=50*1024**3)))
        self.clock=0.0;self.stack.enter_context(patch.object(g.time,'monotonic',side_effect=lambda:self.clock))
        self.stack.enter_context(patch.object(g,'LAUNCH_BLOCKERS',()))
        self.phase_calls=[];self.core_calls=[];self.guard_by_path={};self.hooks={};self.fail_phase=None
        self.rss=123456;self.core_status='completed';self.readback_cost=2;self.restore_cost=1
        self.controller=ModuleType('src.smt_fullfab.controller_delta_v4');self.controller._run_registered=self.core
        self.budget=ModuleType('src.smt_fullfab.budget')
        for key,module in (('controller_delta_v4',self.controller),('budget',self.budget)):
            self.stack.enter_context(patch.object(package,key,module,create=True))
            self.stack.enter_context(patch.dict(sys.modules,{'src.smt_fullfab.'+key:module}))
        self.stack.enter_context(patch.object(g,'run_guarded',side_effect=self.guard))
        self.stack.enter_context(patch.object(g,'verify_lifecycle',side_effect=self.verify_guard))
        self.stack.enter_context(patch.object(g,'verification_payload',side_effect=self.verification))
        self.stack.enter_context(patch.object(g,'restoration_payload',side_effect=self.restoration))

    def sync_ledger(self):self.ledger.write_bytes(raw_rows(self.rows))
    def execute(self):
        campaign,manifest=self.prepare();result=g.execute(campaign,manifest)
        return campaign,manifest,result

    def core(self,**kwargs):
        self.core_calls.append(deepcopy(kwargs))
        self.assertEqual(kwargs,{**g.PARAMETERS,'expected_source_sha256':self.manifest['source_sha256']})
        self.assertEqual(self.controller.ROOT,self.root);self.assertEqual(self.budget.ROOT,self.root)
        self.assertEqual(self.controller.DEFAULT_LEDGER,self.ledger)
        self.assertEqual(self.controller.APPROVAL,self.campaign/'frozen'/g.APPROVAL)
        run=Path(self.manifest['output_directory']);run.mkdir(parents=True)
        result={'status':self.core_status,'end_to_end_wall_seconds':1.0}
        g.write_new(run/'result.json',result)
        (run/'trace.jsonl').write_bytes(b'{"kind":"terminal","time":3600}\n')
        g.write_new(run/'checkpoint.json',{'state_sha256':'synthetic','state':{'not_a_factory':True}})
        (run/'model_raw.txt').write_bytes(b'original raw synthetic model output')
        self.rows.extend([{'event':'reserve','call_id':'new-call','registration_id':'new-registration','run_id':str(run/'model_00000')},
                          {'event':'finish','call_id':'new-call','details':{'usage':None}}])
        self.sync_ledger();(run/'ledger_final.jsonl').write_bytes(self.ledger.read_bytes())
        self.clock+=3
        return result

    def verification(self,campaign,manifest,first):
        run=Path(manifest['output_directory']);g.bind_first(first,g.evidence(campaign,run))
        self.clock+=self.readback_cost
        result={'valid':True,'verified_evidence_sha256':deepcopy(first),'registration_id':'new-registration',
                'ledger_sha256':sha((run/'ledger_final.jsonl').read_bytes()),'result_wall_seconds':1.0,
                'first_trace_receipt':{'sha256':first['run/trace.jsonl']},
                'checkpoint':{'state_sha256':'synthetic','file_sha256':first['run/checkpoint.json']}}
        if 'verify' in self.hooks:self.hooks['verify'](run,manifest)
        return result

    def restoration(self,campaign,manifest,proof):
        self.clock+=self.restore_cost
        output=Path(campaign)/'restoration_scratch';output.mkdir();(output/'restored.json').write_bytes(b'{"synthetic":true}')
        result={'valid':True,'checkpoint_sha256':proof['checkpoint']['file_sha256'],'restored_state_sha256':'synthetic',
                'simulation_seconds':3600.0,'production_scope':913,'simulation_advancement_performed':False,
                'model_calls':0,'solver_calls':0}
        if 'restore' in self.hooks:self.hooks['restore'](Path(manifest['output_directory']),manifest)
        return result

    def guard(self,command,*,run_dir,timeout_seconds,env,call_id,request_fingerprint,io_spec):
        phase=Path(run_dir);args=command[-7:];kind=args[0];self.phase_calls.append(kind)
        self.assertEqual(args[1],str(self.campaign));self.assertEqual(args[2],self.manifest['identity'])
        self.assertIn('from src.smt_fullfab.B_delta_gate_v4 import _worker',command[4])
        self.assertGreater(timeout_seconds,0);self.assertEqual(io_spec['cwd'],str(self.campaign/'frozen'))
        Path(io_spec['stdout']).write_bytes(b'synthetic process stdout\n');Path(io_spec['stderr']).write_bytes(b'')
        if self.fail_phase==kind:
            raise KeyboardInterrupt('synthetic lost owner before terminal')
        returncode=g._worker(*args)
        if kind+'-after' in self.hooks:self.hooks[kind+'-after'](Path(self.manifest['output_directory']),self.manifest)
        self.clock+=.01
        guard_dir=phase/'process_guard';guard_dir.mkdir();raw=g.encoded({'synthetic_only':True,'kind':kind})
        (guard_dir/'receipt.json').write_bytes(raw)
        result={'command_returncode':returncode,'timed_out':False,'launch_error':None,
                'guard_source_sha256':self.manifest['frozen_input_sha256']['src/smt_fullfab/model_process_guard.py'],
                'command_peak_rss_bytes':self.rss,'guard_peak_rss_bytes':123,'parent_wait_wall_seconds':.01,
                'files_sha256':{'receipt.json':sha(raw)},
                'output_files_sha256':{k:sha(Path(v).read_bytes()) if Path(v).exists() else None for k,v in io_spec['outputs'].items()}}
        self.guard_by_path[str(phase)]=(deepcopy(result),deepcopy(command),timeout_seconds,call_id,request_fingerprint,deepcopy(io_spec))
        return result

    def verify_guard(self,path,**kwargs):
        record,command,timeout,call,fingerprint,io=self.guard_by_path[str(path)]
        self.assertEqual(kwargs,{'expected_command':command,'expected_timeout':timeout,'expected_call_id':call,
            'expected_fingerprint':fingerprint,'expected_evidence':record,'expected_io_spec':io})
        return deepcopy(record)

    def prepare(self):
        campaign,manifest=g.prepare(root=self.root)
        self.campaign,self.manifest=campaign,manifest
        return campaign,manifest

    def test_prepare_freezes_source_subset_and_original_ledger_without_call(self):
        campaign,manifest=self.prepare()
        self.assertEqual(self.core_calls,[]);self.assertEqual(self.phase_calls,[])
        self.assertEqual(manifest['source_sha256'],g.digest(g.source_inputs(manifest['frozen_input_sha256'])))
        self.assertEqual((campaign/'frozen/progress').resolve(),self.root/'progress')
        self.assertEqual((campaign/'frozen/runs').resolve(),self.root/'runs')
        self.assertEqual((campaign/'ledger_at_prepare.jsonl').read_bytes(),self.ledger.read_bytes())
        self.assertFalse(Path(manifest['output_directory']).exists())
        with self.assertRaises(ValueError):g.prepare(root=self.root)

    def test_actual_caller_chain_success_and_readback_no_extra_core_or_guard(self):
        campaign,manifest,result=self.execute();self.assertTrue(result['accepted'],result)
        self.assertEqual(self.phase_calls,['supervise','run','verify','restore']);self.assertEqual(len(self.core_calls),1)
        saved=g.read_json(campaign/'acceptance.json')[0]
        self.assertEqual(saved['final_total_bytes_including_acceptance'],g.total_bytes(campaign,Path(manifest['output_directory'])))
        replay=g.read_acceptance(root=self.root);self.assertTrue(replay['valid'],replay);self.assertTrue(replay['accepted'])
        self.assertEqual(len(self.core_calls),1);self.assertEqual(len(self.phase_calls),4)
        with self.assertRaises(ValueError):g.execute(campaign,manifest)

    def test_nonzero_controller_is_failed_with_raw_and_no_followup_or_retry(self):
        self.core_status='failed';campaign,manifest,result=self.execute()
        self.assertFalse(result['accepted']);self.assertEqual(self.phase_calls,['supervise','run'])
        self.assertTrue((Path(manifest['output_directory'])/'model_raw.txt').exists())
        replay=g.read_acceptance(root=self.root);self.assertTrue(replay['valid'],replay);self.assertFalse(replay['accepted'])
        with self.assertRaises(ValueError):g.execute(campaign,manifest)
        self.assertEqual(len(self.core_calls),1)

    def test_missing_owner_readback_stops_before_restore_and_retains_raw(self):
        self.fail_phase='verify';campaign,manifest,result=self.execute()
        self.assertFalse(result['accepted']);self.assertEqual(self.phase_calls,['supervise','run','verify'])
        self.assertFalse((campaign/'restoration_payload.json').exists());self.assertTrue((Path(manifest['output_directory'])/'model_raw.txt').exists())

    def test_missing_owner_outer_cannot_self_accept(self):
        self.fail_phase='supervise';campaign,manifest,result=self.execute()
        self.assertFalse(result['accepted']);self.assertEqual(self.core_calls,[])
        self.assertFalse((campaign/'supervisor_result.json').exists())

    def test_readback_and_restore_share_original_600_seconds(self):
        self.readback_cost=599;self.restore_cost=2;campaign,manifest,result=self.execute()
        self.assertFalse(result['accepted'])
        read=g.read_json(campaign/'readback_process/phase_request.json')[0]
        restore=g.read_json(campaign/'restoration_process/phase_request.json')[0]
        self.assertLessEqual(read['timeout_seconds'],600);self.assertLess(restore['timeout_seconds'],1)

    def test_late_model_raw_replacement_fails_original_anchor_not_reanchored(self):
        self.hooks['verify']=lambda run,_:(run/'model_raw.txt').write_bytes(b'late replacement')
        _,_,result=self.execute();self.assertFalse(result['accepted'])

    def test_new_orphan_after_audit_does_not_enter_accepted_inventory(self):
        self.hooks['restore']=lambda run,_:(run/'unexpected').write_bytes(b'new')
        _,_,result=self.execute();self.assertFalse(result['accepted'])

    def test_guard_original_child_result_anchor_cannot_be_replaced_before_inventory(self):
        original=g.verify_phase
        def replace_after(campaign,manifest,process,**kwargs):
            value=original(campaign,manifest,process,**kwargs)
            if Path(process['phase_directory']).name=='child_process':
                (Path(manifest['output_directory'])/'result.json').write_bytes(b'{"status":"other"}')
            return value
        with patch.object(g,'verify_phase',side_effect=replace_after):
            _,_,result=self.execute()
        self.assertFalse(result['accepted'])

    def test_same_call_late_ledger_note_is_rejected(self):
        def late(run,manifest):
            self.rows.append({'event':'note','call_id':'new-call'});self.sync_ledger()
        self.hooks['restore']=late
        _,_,result=self.execute();self.assertFalse(result['accepted'])

    def test_unrelated_ledger_suffix_is_allowed_but_own_suffix_invalidates_replay(self):
        _,_,result=self.execute();self.assertTrue(result['accepted'],result)
        self.rows.append({'event':'note','run_id':str(self.root/'unrelated'),'call_id':'other'});self.sync_ledger()
        self.assertTrue(g.read_acceptance(root=self.root)['accepted'])
        self.rows.append({'event':'note','mapping':{'registration_id':'new-registration'}});self.sync_ledger()
        self.assertFalse(g.read_acceptance(root=self.root)['valid'])

    def test_runtime_change_after_child_fails_without_reexecution(self):
        self.hooks['run-after']=lambda *_:self.stack.enter_context(patch.object(g,'runtime_capture',return_value={'changed':True}))
        _,_,result=self.execute();self.assertFalse(result['accepted']);self.assertEqual(len(self.core_calls),1)

    def test_peak_rss_is_measured_rejection_not_deleted_evidence(self):
        self.rss=g.RSS_BYTES+1;campaign,manifest,result=self.execute()
        self.assertFalse(result['accepted']);self.assertTrue((Path(manifest['output_directory'])/'result.json').exists())

    def test_existing_attempt_or_target_is_never_retried(self):
        campaign,manifest=self.prepare();g.write_new(campaign/'attempt.json',{'original_partial':True})
        with self.assertRaises(ValueError):g.execute(campaign,manifest)
        self.assertEqual(self.phase_calls,[])

    def test_failed_final_phase_publication_leaves_no_fabricated_accepted_payload(self):
        original=g.write_new
        def broken(path,value,**kwargs):
            if Path(path).name=='restoration_payload.json':raise OSError('synthetic disk full on proof')
            return original(path,value,**kwargs)
        with patch.object(g,'write_new',side_effect=broken):
            campaign,_,result=self.execute()
        self.assertFalse(result['accepted']);self.assertFalse((campaign/'restoration_payload.json').exists())



    def test_late_raw_change_during_saved_readback_fails_final_fence(self):
        campaign,manifest,result=self.execute();self.assertTrue(result['accepted'],result)
        original=g._final_ledger
        def late(run,manifest,expected_sha,registration_id):
            original(run,manifest,expected_sha,registration_id)
            (run/'model_raw.txt').write_bytes(b'changed during readback after first full inventory')
        with patch.object(g,'_final_ledger',side_effect=late):report=g.read_acceptance(root=self.root)
        self.assertFalse(report['valid']);self.assertFalse(report['accepted'])
        self.assertEqual(len(self.core_calls),1)

    def test_child_process_metadata_replacement_after_original_validation_is_failed(self):
        original=g.verify_phase
        def late(campaign,manifest,process,**kwargs):
            result=original(campaign,manifest,process,**kwargs)
            if Path(process['phase_directory']).name=='child_process':
                (Path(process['phase_directory'])/'process.json').write_bytes(b'{"forged":true}')
            return result
        with patch.object(g,'verify_phase',side_effect=late):
            _,_,result=self.execute()
        self.assertFalse(result['accepted']);self.assertEqual(len(self.core_calls),1)

    def test_gate_scratch_is_in_combined_admission_without_deletion(self):
        campaign,manifest=self.prepare();scratch=campaign/'tiny_scratch';scratch.write_bytes(b'retain')
        actual=g.total_bytes
        with patch.object(g,'total_bytes',side_effect=lambda *args:actual(*args)+g.MAX_BYTES):
            with self.assertRaises(ValueError):g.execute(campaign,manifest)
        self.assertEqual(scratch.read_bytes(),b'retain');self.assertEqual(self.core_calls,[])


class TerminalEncodingTests(unittest.TestCase):
    def test_exact_returned_raw_hash_identity_and_size(self):
        value,manifest=success_fixture();value['final_total_bytes_including_acceptance']=0
        raw=g._terminal_encoding(value,200,lambda:10.0,success_validator=lambda item:g.validate_success(item,manifest))
        saved=g.strict(raw)
        self.assertEqual(saved,value);self.assertEqual(saved['final_total_bytes_including_acceptance'],200+len(raw))
        self.assertEqual(saved['identity'],g.digest({k:v for k,v in saved.items() if k!='identity'}))

    def test_encoding_crossing_deadline_reencodes_failed_original_cost(self):
        value,manifest=success_fixture();value['final_total_bytes_including_acceptance']=0
        ticks=iter([g.OUTER_SECONDS-1,g.OUTER_SECONDS+1]+[g.OUTER_SECONDS+2]*100)
        raw=g._terminal_encoding(value,20,lambda:next(ticks),success_validator=lambda item:g.validate_success(item,manifest))
        saved=g.strict(raw);self.assertFalse(saved['accepted']);self.assertEqual(saved['status'],'failed')
        self.assertTrue(any(row['type']=='OuterTimeLimit' for row in saved['errors']))
        self.assertEqual(saved['final_total_bytes_including_acceptance'],20+len(raw))

    def test_combined_byte_overrun_is_retained_failed_not_removed(self):
        value,_=success_fixture();value['final_total_bytes_including_acceptance']=0
        saved=g.strict(g._terminal_encoding(value,g.MAX_BYTES,lambda:1.0))
        self.assertFalse(saved['accepted']);self.assertTrue(any(row['type']=='TotalBytesLimit' for row in saved['errors']))
        self.assertGreater(saved['final_total_bytes_including_acceptance'],g.MAX_BYTES)


class ModelLifecycleBindingTests(unittest.TestCase):
    def fixture(self,root):
        run=root/'run';model=run/'model_00000';model.mkdir(parents=True)
        config={'model':'gpt-6-astra','reasoning_effort':'medium','timeout_seconds':180,
                'codex_binary':g.CLI_PATH,'ledger_path':str(root/'ledger')}
        guard={'guard_source_sha256':'guardsha','command_returncode':0,'timed_out':False,'launch_error':None,
               'files_sha256':{'receipt.json':'original-guard'},'output_files_sha256':{'final.txt':'original-final','stderr.log':None}}
        files={'request.json':{'config':config,'call_id':'call','request_fingerprint':'fingerprint'},
               'command.json':{'argv':['actual','original','argv']},
               'result.json':{'returncode':0,'timed_out':False,'launch_error':None,'process_guard':guard}}
        first={}
        for name,value in files.items():
            first['run/model_00000/'+name]=g.write_new(model/name,value)
        first.update({'run/model_00000/process_guard/receipt.json':'original-guard','run/model_00000/final.txt':'original-final'})
        manifest={'actual_ledger_path':str(root/'ledger'),'frozen_input_sha256':{'src/smt_fullfab/model_process_guard.py':'guardsha'}}
        return run,manifest,first,guard

    def test_every_original_command_call_fingerprint_timeout_and_evidence_are_passed(self):
        with tempfile.TemporaryDirectory() as d:
            run,manifest,first,guard=self.fixture(Path(d))
            with patch.object(g,'verify_lifecycle',return_value=guard) as verify:
                result=g.verify_model_lifecycles(run,manifest,first,1)
            verify.assert_called_once_with(run/'model_00000',expected_command=['actual','original','argv'],expected_timeout=180,
                expected_call_id='call',expected_fingerprint='fingerprint',expected_evidence=guard)
            self.assertEqual(result,{'run/model_00000/process_guard/receipt.json':'original-guard','run/model_00000/final.txt':'original-final'})

    def test_model_first_guard_and_output_anchors_cannot_be_rebound(self):
        for field,name in (('files_sha256','receipt.json'),('output_files_sha256','final.txt')):
            with self.subTest(field=field),tempfile.TemporaryDirectory() as d:
                run,manifest,first,guard=self.fixture(Path(d));changed=deepcopy(guard);changed[field][name]='replacement'
                with patch.object(g,'verify_lifecycle',return_value=changed),self.assertRaises(ValueError):
                    g.verify_model_lifecycles(run,manifest,first,1)

    def test_unknown_absence_guard_source_and_result_mapping_are_not_accepted(self):
        for change in ({'guard_source_sha256':'unfrozen'}, {'command_returncode':1}, {'timed_out':True}, {'launch_error':'error'},
                       {'output_files_sha256':{'final.txt':'original-final','stderr.log':'new'}}):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as d:
                run,manifest,first,guard=self.fixture(Path(d))
                with patch.object(g,'verify_lifecycle',return_value={**guard,**change}),self.assertRaises(ValueError):
                    g.verify_model_lifecycles(run,manifest,first,1)

    def test_missing_guard_never_falls_back_to_unverified_legacy_result(self):
        with tempfile.TemporaryDirectory() as d:
            run,manifest,first,guard=self.fixture(Path(d))
            with patch.object(g,'verify_lifecycle',side_effect=ValueError('original lifecycle missing')),self.assertRaises(ValueError):
                g.verify_model_lifecycles(run,manifest,first,1)


class ExactRestoreCallerTests(unittest.TestCase):
    """Actual restoration wrapper with a fake environment, real tiny JSONL reader.

    No factory construction or physical advancement. These tests exercise only
    wrapper binding/scope/state/EOF contracts, not the original physics restore.
    """
    def fixture(self,root):
        campaign=root/'campaign';campaign.mkdir();run=root/'run';run.mkdir()
        events=[{'kind':'initial','time':0,'seq':0},{'kind':'terminal','time':3600,'seq':1}]
        state={'trace':events,'tiny_value':{'type_preserved':1.0}}
        ref={'state_sha256':g.digest(state)}
        ref['file_sha256']=g.write_new(run/'checkpoint.json',{'state_sha256':ref['state_sha256'],'state':state})
        trace=raw_rows(events);(run/'trace.jsonl').write_bytes(trace)
        proof={'checkpoint':ref,'first_trace_receipt':{'sha256':sha(trace)}}
        env=SimpleNamespace(seed=1701,t=3600,horizon=3600,finished=True,observation_start=0,physical=list(range(913)))
        def snapshot(path):
            restored=deepcopy(state);restored['trace'].append({'kind':'snapshot_loaded'})
            g.write_new(path,{'state':restored})
        env.snapshot=snapshot
        source=ModuleType('src.smt_fullfab.environment');source.digest=g.digest
        source.FullFabEnvironment=SimpleNamespace(from_snapshot=lambda path:env)
        return campaign,run,proof,env,source

    def call(self,campaign,run,proof,source):
        with patch.dict(sys.modules,{'src.smt_fullfab.environment':source}),patch.object(package,'environment',source,create=True):
            return g.restoration_payload(campaign,{'output_directory':str(run)},proof)

    def test_exact_full_state_and_complete_trace_consumption_success(self):
        with tempfile.TemporaryDirectory() as d:
            campaign,run,proof,env,source=self.fixture(Path(d));report=self.call(campaign,run,proof,source)
            self.assertTrue(report['valid']);self.assertEqual(report['trace_events'],2)
            self.assertEqual(report['restored_state_sha256'],proof['checkpoint']['state_sha256'])
            self.assertEqual(report['production_scope'],913);self.assertFalse(report['simulation_advancement_performed'])
            self.assertTrue((campaign/'restoration_scratch/restored.json').exists())

    def test_wrong_source_original_checkpoint_or_trace_hash_rejected(self):
        for which in ('checkpoint','trace'):
            with self.subTest(which=which),tempfile.TemporaryDirectory() as d:
                campaign,run,proof,env,source=self.fixture(Path(d))
                if which=='checkpoint':proof['checkpoint']['file_sha256']='0'*64
                else:proof['first_trace_receipt']['sha256']='0'*64
                with self.assertRaises(ValueError):self.call(campaign,run,proof,source)

    def test_restore_wrong_scope_or_state_is_not_full_window(self):
        for field,value in (('t',3599),('seed',1702),('finished',False),('physical',list(range(912)))):
            with self.subTest(field=field),tempfile.TemporaryDirectory() as d:
                campaign,run,proof,env,source=self.fixture(Path(d));setattr(env,field,value)
                with self.assertRaises(ValueError):self.call(campaign,run,proof,source)

    def test_late_checkpoint_replace_after_restore_fails_final_original_fence(self):
        with tempfile.TemporaryDirectory() as d:
            campaign,run,proof,env,source=self.fixture(Path(d));original=env.snapshot
            def changed(path):
                original(path);(run/'checkpoint.json').write_bytes(b'{"replacement":true}')
            env.snapshot=changed
            with self.assertRaises(ValueError):self.call(campaign,run,proof,source)


if __name__=='__main__':unittest.main()
