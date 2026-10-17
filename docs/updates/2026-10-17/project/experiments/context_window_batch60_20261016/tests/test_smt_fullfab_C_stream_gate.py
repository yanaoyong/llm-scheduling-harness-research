"""Tiny isolated draft-gate fixtures. Authored without executing this module.

No factory, solver, real model CLI, original ledger, or real campaign is used.
The explicitly pending common owner-pipe integration is not certified here.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.smt_fullfab import C_stream_gate as g


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


def terminal():
    execution={'status':'awaiting_attribution','failure':None,'full_window_completed':True,
               'simulation_seconds':28800.0,'wall_seconds':10.0}
    result={'status':'success','failure':None,'failure_details':None,'accepted':False,
            'real_C8_launch_authorized':False,'launch_authority_scope':'controller_does_not_self_authorize',
            'acceptance_authority':'external_frozen_gate','direct_public_execution_enabled':False,'audit_valid':True,'terminal_trace_binding_valid':True,
            'full_window_completed':True,'simulation_seconds':28800.0,'wall_seconds':12.0}
    return result,execution


def stage():
    return {'valid':True,'complete_original_attribution_checks':True,'legacy_whole_history_adapter_used':False,
      'attribution_report':{'valid':True,'errors':[],'missing_evidence':[],'audit_status':'passed',
       'run_status':'awaiting_attribution','successful_full_window':False,
       'all_saved_problem_pages_lossless_certified':True}}


class ProtocolTests(unittest.TestCase):
    def test_exact_static_protocol_and_capacity(self):
        p=protocol();self.assertEqual(g.validate_protocol(p),g.PARAMETERS)
        self.assertEqual(g.MAX_BYTES,25769803776);self.assertEqual(g.MIN_FREE_BYTES,68719476736)
        self.assertEqual(g.READBACK_SECONDS,600);self.assertEqual(g.RESTORE_SECONDS,180)
        self.assertFalse(p['execute_now']);self.assertIsNone(p['limits']['global_max_calls'])

    def test_old_storage_envelope_rejected(self):
        p=protocol();p['limits']['run_scratch_campaign_bytes']=16*1024**3
        with self.assertRaises(ValueError):g.validate_protocol(p)

    def test_old_free_disk_envelope_rejected(self):
        p=protocol();p['limits']['minimum_free_bytes']=40*1024**3
        with self.assertRaises(ValueError):g.validate_protocol(p)

    def test_numerical_config_type_not_normalized(self):
        p=protocol();p['run_parameters']['seconds']=28800.0
        with self.assertRaises(ValueError):g.validate_protocol(p)

    def test_finite_call_cap_not_silently_added(self):
        p=protocol();p['run_parameters']['max_calls']=12
        with self.assertRaises(ValueError):g.validate_protocol(p)

    def test_prerequisite_role_must_be_externally_anchored(self):
        p=protocol();p['prerequisite_roles']['installed_tests']='unbound.json'
        with self.assertRaises(ValueError):g.validate_protocol(p)

    def test_supplemental_path_cannot_escape(self):
        p=protocol();p['additional_frozen_files']=['../outside.py']
        with self.assertRaises(ValueError):g.validate_protocol(p)

    def test_all_launch_paths_reject_before_any_process_or_registration(self):
        with patch.object(g,'LAUNCH_BLOCKERS',('synthetic review blocker',)), \
             patch.object(g.subprocess,'Popen',side_effect=AssertionError('process forbidden')):
            for method in (g.execute,g._execute_reviewed):
                with self.subTest(method=method.__name__),self.assertRaises(ValueError):method('/missing',{})


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


class TerminalTests(unittest.TestCase):
    def test_true_full_window_accepts_recorded_int_or_float_time(self):
        for t in (28800,28800.0):
            r,e=terminal();r['simulation_seconds']=e['simulation_seconds']=t;g.validate_terminal(r,e)

    def test_stage_report_does_not_have_to_claim_final_success(self):
        report=g.validate_attribution_stage(stage())
        self.assertIs(report['successful_full_window'],False)

    def test_wrong_stage_shortcuts_rejected(self):
        for field,value in (('valid',False),('errors',['missing']),('missing_evidence',['raw']),
                            ('all_saved_problem_pages_lossless_certified',False),('successful_full_window',True)):
            s=stage();s['attribution_report'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):g.validate_attribution_stage(s)

    def test_failed_or_prefix_never_promoted(self):
        for field,value in (('status','failed'),('failure','error'),('failure_details',{'message':'error'}),
                            ('full_window_completed',False),('simulation_seconds',10000),('audit_valid',False),
                            ('terminal_trace_binding_valid',False),('accepted',True)):
            r,e=terminal();r[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):g.validate_terminal(r,e)

    def test_bad_numeric_terminal_cost_rejected(self):
        for value in (True,None,-1,float('nan'),float('inf'),43201):
            r,e=terminal();r['wall_seconds']=value
            with self.subTest(value=value),self.assertRaises(ValueError):g.validate_terminal(r,e)

    def test_missing_rss_is_not_zero_and_rss_limit_is_enforced(self):
        p={'returncode':0,'primary_failure':None,'cleanup_errors':[],'wall_seconds':1,'peak_rss_bytes':128}
        g._process_ok(p,2)
        for value in (None,0,True,g.RSS_BYTES+1):
            with self.subTest(value=value),self.assertRaises(ValueError):g._process_ok({**p,'peak_rss_bytes':value},2)

    def test_nonzero_timeout_or_cleanup_failure_blocks(self):
        p={'returncode':0,'primary_failure':None,'cleanup_errors':[],'wall_seconds':1,'peak_rss_bytes':128}
        for field,value in (('returncode',1),('primary_failure',{'type':'Timeout'}),('cleanup_errors',[{'type':'WaitError'}]),('wall_seconds',3)):
            with self.subTest(field=field),self.assertRaises(ValueError):g._process_ok({**p,field:value},2)

    def test_scratch_and_campaign_are_charged(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);campaign=root/'campaign';run=root/'run';campaign.mkdir();run.mkdir()
            (campaign/'attribution_scratch').mkdir();(campaign/'attribution_scratch/index').write_bytes(b'abc')
            (campaign/'restoration_scratch').mkdir();(campaign/'restoration_scratch/state').write_bytes(b'1234')
            (campaign/'phase').write_bytes(b'xy');(run/'raw').write_bytes(b'abcde')
            self.assertEqual(g.total_bytes(campaign,run),14)

    def test_partial_artifacts_do_not_create_acceptance(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);campaign=root/g.AREA/g.RUN_ID;campaign.mkdir(parents=True)
            (campaign/'partial.json').write_text('{}')
            report=g.read_acceptance(root=root)
            self.assertFalse(report['valid']);self.assertFalse(report['accepted'])
            self.assertFalse((campaign/'acceptance.json').exists())


class GuardedPhaseTests(unittest.TestCase):
    """Mocked failure paths plus one real tiny owner-pipe integration fixture."""
    def test_guard_failure_is_recorded_without_success_or_second_process(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(g,'run_guarded',side_effect=KeyboardInterrupt('primary owner interruption')) as guard, \
                 patch.object(g.subprocess,'Popen',side_effect=AssertionError('No second process')):
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

    @unittest.skipUnless(os.name=='posix','common owner-pipe guard is POSIX only')
    def test_benign_owned_phase_verification_and_original_anchors(self):
        # One real, tiny Python process; no model CLI, ps, factory, solver or
        # original ledger. All phase paths satisfy the production canonical API.
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();campaign=root/'campaign';campaign.mkdir()
            frozen=campaign/'frozen';frozen.mkdir();run=root/'run';run.mkdir()
            guard_source=Path(g.__file__).resolve().parent/'model_process_guard.py'
            manifest={'output_directory':str(run),'frozen_input_sha256':{
                'src/smt_fullfab/model_process_guard.py':sha(guard_source.read_bytes())}}
            command=[sys.executable,'-c',"print('C8 benign phase binding')"]
            result=g.owned_phase(command,cwd=frozen,output=campaign/'child_process',timeout=5)
            self.assertEqual(result['returncode'],0)
            self.assertIsNone(result['primary_failure'])
            self.assertEqual(result['guard_evidence']['guard_returncode'],-signal.SIGKILL)
            anchors=g.verify_phase(campaign,manifest,result,command=command,maximum=5)
            self.assertEqual(anchors,g.phase_anchors(campaign,result,run))
            phase=campaign/'child_process'
            self.assertEqual(anchors['campaign/child_process/process.json'],sha((phase/'process.json').read_bytes()))
            self.assertEqual(anchors['campaign/child_process/process_guard/parent_observed.json'],
                             result['guard_evidence']['files_sha256']['parent_observed.json'])
            self.assertEqual((phase/'stdout.log').read_bytes(),b'C8 benign phase binding\n')
            original=result['process_sha256']
            changed=json.loads((phase/'process.json').read_text());changed['wall_seconds']=0.0
            (phase/'process.json').write_text(json.dumps(changed))
            self.assertEqual(g.phase_anchors(campaign,result,run)['campaign/child_process/process.json'],original)
            with self.assertRaisesRegex(ValueError,'original SHA binding differs'):
                g.verify_phase(campaign,manifest,result,command=command,maximum=5)

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
        'restoration':{'valid':True,'simulation_seconds':28800.0,'production_scope':913,
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
                                  ('outer_wall_seconds_through_receipt_preparation',46801)):
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


if __name__=='__main__':unittest.main()
