"""Injected synthetic transport writes temp artifacts; real CLI/budget are forbidden."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab import B_delta_call_bridge as bridge
from src.smt_fullfab import B_delta_durable as durable
from src.smt_fullfab import B_delta_transport_binding as binding
from src.smt_fullfab import model_transport
from tests.test_smt_fullfab_B_delta_transport_binding import Fixture, encoded
from tests.test_smt_fullfab_delta_session import fixture, SOURCE


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.original=Fixture(self.root)
        self.full_rows=deepcopy(self.original.rows)
        # The helper initially creates a synthetic completed record. Remove only
        # that temporary fixture output to establish a genuine pre-call phase.
        for p in self.original.run.iterdir():p.unlink()
        self.original.run.rmdir()
        self.original.rows=self.original.rows[:3];self.original.sync_ledger()
        self.store=durable.DurableInteractionStore.create(self.root/'durable',store_id='synthetic-store')
        base,problem,state,paging,_=fixture()
        self.bootstrap={'base_plan':base,'problem':problem,'execution_state':state,'source_sha256':SOURCE,'paging':paging}
        registered=self.store.register('instance',self.bootstrap);self.assertTrue(registered['accepted'])
        self.context=registered['value'];self.evidence=self.root/'bridge';self.calls=0;self.behavior='success'
        self.authorization={'ledger_path':str(self.original.ledger),'ledger_before_sha256':bridge.sha(self.original.ledger.read_bytes()),
            'approval_sha256':binding._record_digest(self.original.approval),'registration_id':self.original.registration['registration_id'],
            'registration_sha256':binding._record_digest(self.original.registration),'disabled_skill_paths':[]}
        self.guard=patch.object(model_transport,'call_model',side_effect=AssertionError('actual transport forbidden'));self.guard.start();self.addCleanup(self.guard.stop)
        self.process_count=0
    def args(self):
        return dict(expected_store_id='synthetic-store',instance_id='instance',attempt_id='attempt',model_index=0,
            transport_run_dir=str(self.original.run),evidence_dir=self.evidence,config=self.original.config,schema={'type':'object'},
            expected_context=self.context,authorization=self.authorization,transport_call=self.fake,process_success=True)
    def execute(self,**changes):return bridge.execute_once(self.store,**(self.args()|changes))
    def fake(self,prompt,schema,run,config,*,resume):
        self.calls+=1;self.assertIs(resume,False);self.assertEqual(run,str(self.original.run))
        self.assertTrue((self.evidence/'invocation_intent.json').exists())
        report=durable.recover_read_only(self.store.directory)
        self.assertTrue(report['valid'],report);self.assertEqual(report['sessions'][0]['phase'],'reserved_transport_unknown')
        if self.behavior=='return_only':return {'status':'success','output':{'fabricated_return':'must never be processed'}}
        f=self.original;f.run.mkdir();f.prompt=prompt;f.schema=schema;f.schema_raw=encoded(schema);f.config=config
        fingerprint=binding.sha((prompt+'\n'+f.schema_raw.decode()+'\n'+json.dumps(config,sort_keys=True)).encode())
        f.request.update(config=config,request_fingerprint=fingerprint)
        f.output={'schema':durable.interaction.RESPONSE_SCHEMA,**self.context,
            'prompt_body_sha256':prompt.split('\n',1)[0].split('=',1)[1],'memory':' exact 中文 memory ',
            'request':{'kind':'read_candidates'}}
        f.result.update(config=config,request_fingerprint=fingerprint,prompt_characters=len(prompt),output=f.output)
        f.reserve['metadata'].update(request_fingerprint=fingerprint,prompt_characters=len(prompt))
        f.rows=self.full_rows[:3]+[f.reserve,f.finish]
        f.write('attempt.claim',(fingerprint+'\n').encode())
        if self.behavior=='claim_only':
            f.rows=f.rows[:4];f.sync_ledger();raise RuntimeError('crash after original reserve before request')
        f.write('prompt.txt',prompt.encode());f.write('schema.json',f.schema_raw);f.write('system-instructions.txt',binding.SYSTEM_TEXT.encode())
        f.write_json('command.json',f.command);f.write_json('request.json',f.request)
        f.write('stderr.log',b'original synthetic stderr bytes\n')
        if self.behavior=='invalid_wrapper':f.output['session_id']='stale'
        if self.behavior in ('failed','failed_no_final'):
            f.result.update(status='timeout',failure_reason='model_call_timeout',timed_out=True,returncode=-15)
            f.finish['status']='timeout'
        if self.behavior=='unknown_usage':f.events[-1].pop('usage')
        f.sync_result()
        if self.behavior=='failed_no_final':
            (f.run/'final.txt').unlink();f.result.update(output=None,decode_error='No final message file')
            f.write_json('result.json',f.result)
        if self.behavior=='partial_result':
            (f.run/'result.json').unlink();f.write('result.json.tmp',b'{"call_id":"unfinished')
            f.rows=f.rows[:-1];f.sync_ledger();raise RuntimeError('atomic result publication interrupted')
        if self.behavior in ('pending','missing_finish'):
            f.rows=f.rows[:-1];f.sync_ledger()
            if self.behavior=='pending':(f.run/'result.json').unlink()
            raise RuntimeError('original unfinished call')
        if self.behavior=='invalid_usage_old_success':
            f.events[-1]['usage']['input_tokens']=True;f.result['usage']['input_tokens']=1
            f.write('events.jsonl',b''.join((json.dumps(e)+'\n').encode() for e in f.events));f.write_json('result.json',f.result)
            f.finish['details']['usage']=deepcopy(f.result['usage']);f.sync_ledger()
        if self.behavior=='invalid_usage_malformed_diagnostics':
            f.events[-1]['usage']['input_tokens']=True
            f.write('events.jsonl',b''.join((json.dumps(e)+'\n').encode() for e in f.events))
            f.result.update(status='failed',failure_reason='invalid_usage_evidence',usage_status='invalid',usage_validation_errors=['synthetic invalid original bool'])
            f.result['usage']['input_tokens']=None;f.finish.update(status='failed')
            f.finish['details'].update(failure_reason='invalid_usage_evidence',usage=deepcopy(f.result['usage']))
            f.write_json('result.json',f.result);f.sync_ledger()
        if self.behavior=='invalid_usage_new_failure':
            f.events[-1]['usage']['input_tokens']=True
            f.write('events.jsonl',b''.join((json.dumps(e)+'\n').encode() for e in f.events))
            # Actual production shape, including structured diagnostic entries.
            # This calls only the pure summarizer, never the model channel.
            f.result.update(model_transport.summarize_events(f.events))
            f.result.update(status='failed',failure_reason='invalid_usage_evidence')
            f.finish.update(status='failed')
            f.finish['details'].update(failure_reason='invalid_usage_evidence',usage=deepcopy(f.result['usage']))
            f.write_json('result.json',f.result);f.sync_ledger()
        if self.behavior=='raise_after_completion':raise RuntimeError('caller interrupted after original finish')
        if self.behavior=='keyboard_after_completion':raise KeyboardInterrupt('synthetic interruption')
        return {'status':'failed','output':{'wrong_return_value':'ignore this'}}
    def recovery(self,result):
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch.object(durable.DurableInteractionStore,'process_completed',side_effect=AssertionError('no recovery processing')):
            report=bridge.recover_read_only(self.evidence,expected_intent_sha256=result['intent_sha256'],expected_outcome_sha256=result.get('outcome_sha256'))
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        return report
    def test_complete_lifecycle_ignores_return_json_and_attaches_original_bytes(self):
        result=self.execute();self.assertEqual(result['phase'],'action_processed',result);self.assertEqual(self.calls,1)
        self.assertEqual(result['interaction_response']['response']['status'],'query_result')
        self.assertFalse(result['backend_invocation_independently_proven']);self.assertFalse(result['physical_commit_performed'])
        self.assertEqual((self.evidence/'raw/final.txt.bin').read_bytes(),(self.original.run/'final.txt').read_bytes())
        self.assertTrue(json.loads((self.evidence/'success_binding.json').read_bytes())['success_action_eligible'])
        recovered=self.recovery(result);self.assertTrue(recovered['valid'],recovered)
        self.assertEqual(recovered['phase'],'action_already_processed_no_replay')
        with self.assertRaises(bridge.BridgeError):self.execute()
        self.assertEqual(self.calls,1)
    def test_explicit_unprocessed_success_and_read_only_recovery_never_handle_it(self):
        result=self.execute(process_success=False);self.assertEqual(result['phase'],'terminal_successful_unprocessed',result)
        recovered=self.recovery(result);self.assertTrue(recovered['valid'],recovered)
        self.assertEqual(recovered['durable_phase'],'terminal_original_attached_unprocessed')
        self.assertIn('requires_explicit_processing',recovered['phase']);self.assertTrue(recovered['success_action_eligible']);self.assertEqual(self.calls,1)
    def test_terminal_failed_call_preserves_completion_and_original_stderr_without_processing(self):
        self.behavior='failed';result=self.execute();self.assertEqual(result['phase'],'terminal_failed_preserved',result)
        self.assertEqual((self.evidence/'raw/stderr.log.bin').read_bytes(),b'original synthetic stderr bytes\n')
        report=durable.recover_read_only(self.store.directory);self.assertEqual(report['sessions'][0]['phase'],'failed_transport_preserved')
        self.assertEqual(report['sessions'][0]['action_count'],0)
        self.assertEqual(self.recovery(result)['phase'],'terminal_failed_requires_diagnosis')
    def test_failed_call_without_final_is_preserved_not_required_to_pass_success_binder(self):
        self.behavior='failed_no_final';result=self.execute()
        self.assertEqual(result['phase'],'terminal_failed_preserved',result)
        self.assertFalse((self.evidence/'raw/final.txt.bin').exists())
        self.assertIn('final.txt',json.loads((self.evidence/'capture.json').read_bytes())['missing'])
        self.assertEqual(self.recovery(result)['phase'],'terminal_failed_requires_diagnosis')
    def test_partial_atomic_result_bytes_are_retained_without_inventing_completion(self):
        self.behavior='partial_result';result=self.execute()
        self.assertEqual(result['phase'],'pending_original_call',result)
        self.assertEqual((self.evidence/'raw/result.json.tmp.bin').read_bytes(),b'{"call_id":"unfinished')
        self.assertFalse((self.evidence/'raw/result.json.bin').exists())
        self.assertEqual(self.recovery(result)['phase'],'pending_original_call')
    def test_missing_finish_is_pending_even_with_result_and_final(self):
        self.behavior='missing_finish';result=self.execute();self.assertEqual(result['phase'],'pending_original_call',result)
        self.assertTrue((self.evidence/'raw/result.json.bin').exists());self.assertTrue((self.evidence/'raw/final.txt.bin').exists())
        self.assertEqual(self.recovery(result)['phase'],'pending_original_call');self.assertEqual(self.calls,1)
    def test_original_request_without_result_remains_pending_and_new_attempt_blocked(self):
        self.behavior='pending';result=self.execute();self.assertEqual(result['phase'],'pending_original_call',result)
        first_calls=self.calls
        other=self.execute(attempt_id='another',model_index=1,transport_run_dir=str(self.original.run.with_name('model_001')),
                           evidence_dir=self.root/'another',authorization={**self.authorization,'ledger_before_sha256':bridge.sha(self.original.ledger.read_bytes())})
        self.assertEqual(other['phase'],'diagnosis_required');self.assertEqual(self.calls,first_calls)
        self.assertEqual(self.recovery(result)['phase'],'pending_original_call')
    def test_call_id_hook_gap_preserves_local_and_original_reserve_but_claims_no_atomicity(self):
        self.behavior='claim_only';result=self.execute();self.assertEqual(result['phase'],'diagnosis_required')
        self.assertEqual(result['durable_phase'],'local_reserved_transport_outcome_unknown')
        self.assertTrue((self.evidence/'raw/attempt.claim.bin').exists());self.assertTrue((self.evidence/'raw/ledger.bin').exists())
        self.assertEqual(self.recovery(result)['phase'],'local_reservation_transport_outcome_unknown')
    def test_transport_return_value_without_original_files_is_never_a_model_action(self):
        self.behavior='return_only';result=self.execute();self.assertEqual(result['phase'],'diagnosis_required')
        self.assertEqual(result['durable_phase'],'local_reserved_transport_outcome_unknown');self.assertEqual(self.calls,1)
    def test_success_with_invalid_wrapper_does_not_enter_interaction(self):
        self.behavior='invalid_wrapper';result=self.execute();self.assertEqual(result['phase'],'diagnosis_required',result)
        self.assertEqual(result['durable_phase'],'pending_original_call')
        saved=json.loads((self.evidence/'success_binding.json').read_bytes());self.assertFalse(saved['success_action_eligible'])
        self.assertEqual(durable.recover_read_only(self.store.directory)['sessions'][0]['action_count'],0)
    def test_old_coerced_bool_usage_cannot_be_known_or_processed(self):
        self.behavior='invalid_usage_old_success';result=self.execute();self.assertEqual(result['phase'],'diagnosis_required',result)
        self.assertFalse(result['usage_known']);self.assertEqual(result['durable_phase'],'pending_original_call')
        self.assertIn(b'true',(self.evidence/'raw/events.jsonl.bin').read_bytes())
    def test_malformed_invalid_usage_diagnostics_are_retained_but_rejected(self):
        self.behavior='invalid_usage_malformed_diagnostics';result=self.execute();self.assertEqual(result['phase'],'diagnosis_required',result)
        self.assertFalse(result['usage_known']);self.assertEqual(result['durable_phase'],'pending_original_call')
        self.assertFalse(json.loads((self.evidence/'completion_attachment.json').read_bytes())['accepted'])
        self.assertEqual(json.loads((self.evidence/'raw/result.json.bin').read_bytes())['failure_reason'],'invalid_usage_evidence')
        self.assertEqual(self.recovery(result)['phase'],'terminal_failed_requires_diagnosis')
    def test_real_production_invalid_usage_failure_attaches_but_never_handles(self):
        self.behavior='invalid_usage_new_failure';result=self.execute()
        self.assertEqual(result['phase'],'terminal_failed_preserved',result)
        self.assertFalse(result['usage_known'])
        self.assertTrue(json.loads((self.evidence/'completion_attachment.json').read_bytes())['accepted'])
        original=json.loads((self.evidence/'raw/result.json.bin').read_bytes())
        self.assertEqual(original['usage_validation_errors'],model_transport.summarize_events(self.original.events)['usage_validation_errors'])
        self.assertEqual(durable.recover_read_only(self.store.directory)['sessions'][0]['action_count'],0)
        self.assertEqual(self.recovery(result)['phase'],'terminal_failed_requires_diagnosis')
    def test_missing_externally_known_processed_outcome_cannot_downgrade_to_unfinished(self):
        result=self.execute();(self.evidence/'outcome.json').unlink()
        recovered=self.recovery(result);self.assertFalse(recovered['valid'],recovered)
        self.assertIn('known outcome is missing',str(recovered['errors']))
        self.assertEqual(self.calls,1)
    def test_missing_externally_known_unprocessed_outcome_cannot_downgrade_to_unfinished(self):
        result=self.execute(process_success=False);(self.evidence/'outcome.json').unlink()
        recovered=self.recovery(result);self.assertFalse(recovered['valid'],recovered)
        self.assertIn('known outcome is missing',str(recovered['errors']))
        self.assertEqual(self.calls,1)
    def test_unknown_usage_stays_unknown_without_blocking_valid_output(self):
        self.behavior='unknown_usage';result=self.execute();self.assertEqual(result['phase'],'action_processed',result)
        self.assertFalse(result['usage_known']);self.assertIsNone(json.loads((self.evidence/'raw/result.json.bin').read_bytes())['usage']['input_tokens'])
    def test_exception_after_finished_files_preserves_success_unprocessed(self):
        self.behavior='raise_after_completion';result=self.execute();self.assertEqual(result['phase'],'terminal_successful_unprocessed',result)
        self.assertEqual(self.calls,1);self.assertEqual(durable.recover_read_only(self.store.directory)['sessions'][0]['action_count'],0)
    def test_keyboard_interrupt_is_preserved_and_reraised_without_reprocessing(self):
        self.behavior='keyboard_after_completion'
        with self.assertRaises(KeyboardInterrupt):self.execute()
        outcome=json.loads((self.evidence/'outcome.json').read_bytes());self.assertEqual(outcome['phase'],'terminal_successful_unprocessed')
        self.assertEqual(self.calls,1);self.assertTrue((self.evidence/'invocation_exception.json').exists())
    def test_wrong_external_authorization_or_context_prevents_transport(self):
        for i,changes in enumerate(({'authorization':{**self.authorization,'ledger_before_sha256':'0'*64}},
                                   {'authorization':{**self.authorization,'registration_sha256':'0'*64}},
                                   {'expected_context':{**self.context,'session_id':'stale'}},
                                   {'config':{**self.original.config,'timeout_seconds':181}})):
            result=self.execute(evidence_dir=self.root/f'bad{i}',**changes)
            self.assertEqual(result['phase'],'diagnosis_required');self.assertEqual(self.calls,0)
    def test_tampered_archived_final_or_issued_prompt_is_rejected_on_read_only_recovery(self):
        result=self.execute();path=self.evidence/'raw/final.txt.bin';old=path.read_bytes();path.write_bytes(old+b' ')
        self.assertFalse(self.recovery(result)['valid']);path.write_bytes(old)
        path=self.evidence/'issued_prompt.txt';path.write_bytes(path.read_bytes()+b' ')
        self.assertFalse(self.recovery(result)['valid'])
    def test_crash_after_original_finish_before_bridge_capture_is_readonly_verifiable_not_replayed(self):
        with patch.object(bridge,'archive_originals',side_effect=KeyboardInterrupt('capture interrupted')):
            with self.assertRaises(KeyboardInterrupt):self.execute()
        self.assertFalse((self.evidence/'outcome.json').exists())
        self.assertFalse((self.evidence/'raw').exists())
        result={'intent_sha256':bridge.sha((self.evidence/'intent.json').read_bytes())}
        recovered=self.recovery(result);self.assertTrue(recovered['valid'],recovered)
        self.assertEqual(recovered['durable_phase'],'local_reserved_transport_outcome_unknown')
        self.assertEqual(recovered['phase'],'terminal_successful_unprocessed_requires_explicit_processing')
        self.assertTrue(recovered['success_action_eligible'])
        self.assertEqual(self.calls,1)
        self.assertEqual(durable.recover_read_only(self.store.directory)['sessions'][0]['action_count'],0)
        with self.assertRaises(bridge.BridgeError):self.execute()
        self.assertEqual(self.calls,1)
    def test_crash_before_entering_transport_has_unknown_intent_and_never_retries(self):
        original=bridge.save_json
        def interrupted(path,value):
            result=original(path,value)
            if Path(path).name=='invocation_intent.json':raise KeyboardInterrupt('before entry')
            return result
        with patch.object(bridge,'save_json',side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):self.execute()
        result={'intent_sha256':bridge.sha((self.evidence/'intent.json').read_bytes())}
        recovered=self.recovery(result);self.assertTrue(recovered['valid'],recovered)
        self.assertEqual(recovered['phase'],'local_reservation_transport_outcome_unknown');self.assertEqual(self.calls,0)
        with self.assertRaises(FileExistsError):self.execute()
        self.assertEqual(self.calls,0)
    def test_live_original_replacement_cannot_hide_behind_good_archive_or_durable_replay(self):
        result=self.execute(process_success=False)
        for name in ('final.txt','events.jsonl','request.json','command.json'):
            path=self.original.run/name;old=path.read_bytes();path.write_bytes(old+b' ')
            try:
                recovered=self.recovery(result);self.assertFalse(recovered['valid'],(name,recovered))
            finally:path.write_bytes(old)
        self.assertEqual(self.calls,1)
    def test_reported_success_with_bad_wrapper_remains_rejected_during_recovery(self):
        self.behavior='invalid_wrapper';result=self.execute()
        recovered=self.recovery(result);self.assertTrue(recovered['valid'],recovered)
        self.assertFalse(recovered['success_action_eligible'])
        self.assertEqual(recovered['phase'],'terminal_reported_success_rejected_requires_diagnosis')
    def test_external_intent_and_outcome_hashes_are_required_not_self_accepted(self):
        result=self.execute()
        for changes in ({'intent_sha256':'0'*64},{'outcome_sha256':'0'*64},{'outcome_sha256':None}):
            self.assertFalse(self.recovery(result|changes)['valid'])
        self.assertEqual(self.calls,1)
    def test_wrong_disabled_skill_inventory_stops_before_processing(self):
        result=self.execute(authorization={**self.authorization,'disabled_skill_paths':['/external/expected/skill']})
        self.assertEqual(result['phase'],'diagnosis_required');self.assertEqual(self.calls,1)
        self.assertEqual(durable.recover_read_only(self.store.directory)['sessions'][0]['action_count'],0)


if __name__=='__main__':unittest.main()
