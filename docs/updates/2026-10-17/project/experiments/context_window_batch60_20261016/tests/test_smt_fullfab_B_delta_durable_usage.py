"""Strict usage compatibility and explicit readonly export; synthetic only.

Prepared while A8 runs: these tests must not be executed until root releases the
serial run. No test calls transport, a factory, or a solver.
"""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from src.smt_fullfab import B_delta_durable as module
from src.smt_fullfab import model_transport
from tests import test_smt_fullfab_B_delta_durable as fixtures


def event_bytes(events):
    return b''.join((json.dumps(e,ensure_ascii=False)+'\n').encode() for e in events)


class DurableUsageTests(unittest.TestCase):
    def setUp(self):
        self.h=fixtures.DurableTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.guard=patch.object(model_transport,'call_model',side_effect=AssertionError('real transport forbidden'))
        self.guard.start();self.addCleanup(self.guard.stop)

    def completion(self,usage,*,flags=None,extra_events=(),malformed=False,status='failed',failure='invalid_usage_evidence'):
        reserved=self.h.reserve();artifacts=self.h.artifacts(reserved,{'kind':'read_candidates'})
        events=[{'type':'turn.completed','usage':usage},*deepcopy(extra_events)]
        raw=event_bytes(events)+(b'{broken\n' if malformed else b'')
        result=module.decode(artifacts['result_bytes'])
        result.update(model_transport.summarize_events(events))
        result.update(status=status,failure_reason=failure,malformed_event_lines=['{broken'] if malformed else [])
        result.update(flags or {})
        finish=module.decode(artifacts['finish_bytes']);finish['status']=result['status']
        finish['details']=model_transport._finish_details(result,Path('/synthetic/a0/result.json'))
        artifacts.update(events_bytes=raw,result_bytes=module.encode(result),finish_bytes=module.encode(finish))
        self.assertTrue(self.h.bind_request('a0',artifacts)['accepted'])
        return artifacts

    def test_raw_usage_domain_matches_current_pure_transport_summary(self):
        values=(True,False,-1,'1',1.0,1.25,float('inf'),float('-inf'),float('nan'),[],{})
        for value in values:
            for usage in ({'input_tokens':value,'output_tokens':2},{'input_tokens':3,'output_tokens':2,'future_tokens':value}):
                with self.subTest(usage=usage):
                    events=[{'type':'turn.completed','usage':usage}]
                    actual=module.event_summary(event_bytes(events));expected=model_transport.summarize_events(events)
                    self.assertEqual(actual,{**expected,'malformed_event_lines':[]})
                    self.assertEqual(actual['usage_status'],'invalid')
                    self.assertTrue(actual['usage_validation_errors'])
        for usage in (True,'unknown',[],3):
            events=[{'type':'turn.completed','usage':usage}]
            self.assertEqual(module.event_summary(event_bytes(events)),
                             {**model_transport.summarize_events(events),'malformed_event_lines':[]})

    def test_missing_null_and_valid_counters_preserve_valid_shape_and_no_rounding(self):
        for event in ({'type':'turn.completed'}, {'type':'turn.completed','usage':None},
                      {'type':'turn.completed','usage':{}},
                      {'type':'turn.completed','usage':{'input_tokens':None,'output_tokens':2}},
                      {'type':'turn.completed','usage':{'input_tokens':0,'output_tokens':2**64+1}}):
            with self.subTest(event=event):
                summary=module.event_summary(event_bytes([event]))
                self.assertEqual(summary,{**model_transport.summarize_events([event]),'malformed_event_lines':[]})
                self.assertNotIn('usage_validation_errors',summary)
        events=[{'type':'turn.completed','usage':{'input_tokens':3,'output_tokens':4}}, {'type':'turn.completed'}]
        summary=module.event_summary(event_bytes(events))
        self.assertIsNone(summary['usage']['input_tokens']);self.assertIsNone(summary['usage']['output_tokens'])
        self.assertNotIn('usage_validation_errors',summary)

    def test_new_invalid_usage_failure_is_preserved_but_not_processed(self):
        artifacts=self.completion({'input_tokens':True,'output_tokens':2})
        before=deepcopy(artifacts)
        self.assertTrue(self.h.bind_completion('a0',artifacts)['accepted'])
        self.assertEqual(artifacts,before)
        report=self.h.report();self.assertEqual(report['sessions'][0]['phase'],'failed_transport_preserved')
        self.assertFalse(self.h.store.process_completed('i0',attempt_id='a0')['accepted'])
        self.assertFalse(self.h.reserve(index=1)['accepted'])

    def test_invalid_usage_cannot_claim_success_with_matching_finish(self):
        artifacts=self.completion({'input_tokens':True},status='success',failure=None)
        result=self.h.bind_completion('a0',artifacts)
        self.assertFalse(result['accepted']);self.assertIn('failure precedence',str(result))

    def test_higher_priority_failure_is_preserved_over_invalid_usage(self):
        cases=[({'timed_out':True,'launch_error':'failed'},(),False,'timeout','model_call_timeout'),
               ({'launch_error':'failed'},(),False,'failed','model_launch_error'),
               ({},({'type':'item.completed','item':{'type':'command_execution'}},),False,'failed','native_tool_isolation_violation'),
               ({},(),True,'failed','malformed_event_log')]
        for i,(flags,extra,malformed,status,failure) in enumerate(cases):
            with self.subTest(failure=failure):
                # A distinct new store per terminal failed call; no retry/reset in one store.
                if i:self.h.doCleanups();self.h=fixtures.DurableTests();self.h.setUp();self.addCleanup(self.h.doCleanups)
                artifacts=self.completion({'input_tokens':True},flags=flags,extra_events=extra,malformed=malformed,status=status,failure=failure)
                self.assertTrue(self.h.bind_completion('a0',artifacts)['accepted'])
                self.assertEqual(self.h.report()['sessions'][0]['action_count'],0)

    def test_invalid_usage_precedes_nonzero_returncode_and_decode_error(self):
        artifacts=self.completion({'input_tokens':True},flags={'returncode':1,'decode_error':'No final message file'})
        self.assertTrue(self.h.bind_completion('a0',artifacts)['accepted'])

    def test_wrong_priority_failure_and_malformed_diagnostics_are_rejected(self):
        artifacts=self.completion({'input_tokens':True},flags={'timed_out':True})
        self.assertFalse(self.h.bind_completion('a0',artifacts)['accepted'])
        result=module.decode(artifacts['result_bytes'])
        result.update(status='timeout',failure_reason='model_call_timeout',usage_validation_errors=['incorrect old fixture'])
        finish=module.decode(artifacts['finish_bytes']);finish['status']='timeout'
        finish['details']['failure_reason']='model_call_timeout'
        artifacts.update(result_bytes=module.encode(result),finish_bytes=module.encode(finish))
        self.assertFalse(self.h.bind_completion('a0',artifacts)['accepted'])

    def test_legacy_coerced_usage_and_extra_diagnostics_do_not_become_valid(self):
        artifacts=self.completion({'input_tokens':True,'output_tokens':2})
        result=module.decode(artifacts['result_bytes']);result['usage']['input_tokens']=1
        result.update(usage_status='reported',status='success',failure_reason=None);result.pop('usage_validation_errors')
        finish=module.decode(artifacts['finish_bytes']);finish.update(status='success')
        finish['details'].update(usage=deepcopy(result['usage']),failure_reason=None)
        artifacts.update(result_bytes=module.encode(result),finish_bytes=module.encode(finish))
        original=deepcopy(artifacts)
        self.assertFalse(self.h.bind_completion('a0',artifacts)['accepted']);self.assertEqual(artifacts,original)
        events=[{'type':'turn.completed','usage':{'input_tokens':3,'output_tokens':2}}]
        result.update(model_transport.summarize_events(events),usage_validation_errors=[])
        finish['details']['usage']=deepcopy(result['usage'])
        artifacts.update(events_bytes=event_bytes(events),result_bytes=module.encode(result),finish_bytes=module.encode(finish))
        self.assertFalse(self.h.bind_completion('a0',artifacts)['accepted'])


class DurableExportTests(unittest.TestCase):
    def setUp(self):
        self.h=fixtures.DurableTests();self.h.setUp();self.addCleanup(self.h.doCleanups)

    def prefix(self):
        report=self.h.report()
        return {key:report[key] for key in ('journal_records','journal_tail_sha256','database_sha256')}

    def export(self,prefix=None,store_id='store-test'):
        before={p:p.read_bytes() for p in self.h.directory.iterdir() if p.is_file()}
        with patch.object(module.DurableInteractionStore,'process_completed',side_effect=AssertionError('no new processing')):
            result=module.export_verified_interaction(self.h.directory,expected_store_id=store_id,
                expected_prefix=self.prefix() if prefix is None else prefix)
        self.assertEqual(before,{p:p.read_bytes() for p in self.h.directory.iterdir() if p.is_file()})
        return result

    def test_default_recovery_shape_does_not_export_candidates_or_history(self):
        self.assertNotIn('interactions',self.h.report())

    def test_pending_and_completed_unprocessed_export_never_handle_original_output(self):
        reservation=self.h.reserve();artifacts=self.h.artifacts(reservation,{'kind':'read_candidates'})
        for phase in ('reserved_transport_unknown','transport_pending','completed_unprocessed'):
            if phase=='transport_pending':self.assertTrue(self.h.bind_request('a0',artifacts)['accepted'])
            if phase=='completed_unprocessed':self.assertTrue(self.h.bind_completion('a0',artifacts)['accepted'])
            with patch.object(module.interaction.Interaction,'handle',side_effect=AssertionError('unprocessed output cannot be replayed')):
                result=self.export();self.assertTrue(result['valid'],result)
            self.assertEqual(result['sessions'][0]['phase'],phase)
            evidence=result['interactions'][0]['evidence'];self.assertEqual(evidence['history'],[])
            self.assertIsNone(evidence['selection']);self.assertEqual(evidence['bootstrap'],self.h.inputs)

    def test_processed_query_export_contains_exact_existing_history_without_new_writes(self):
        self.h.send({'kind':'read_candidates'})
        result=self.export();self.assertTrue(result['valid'],result)
        evidence=result['interactions'][0]['evidence'];self.assertEqual(len(evidence['history']),1)
        self.assertIsNone(evidence['selection']);self.assertFalse(result['transport_authenticated'])

    def test_selected_export_matches_stored_plan_selection_and_assurance_remains_false(self):
        selection=self.h.selected();result=self.export();self.assertTrue(result['valid'],result)
        self.assertEqual(result['interactions'][0]['evidence']['selection'],selection)
        self.assertEqual(result['sessions'][0]['selection_sha256'],module.digest(selection))
        self.assertFalse(result['physical_commit_verified']);self.assertFalse(result['external_commit_ready'])

    def test_external_anchors_are_required_and_snapshot_must_be_exact(self):
        old=self.prefix();self.h.send({'kind':'read_candidates'});current=self.prefix()
        for prefix,store_id in (({},'store-test'),(current,'wrong'),(current|{'database_sha256':'0'*64},'store-test'),(old,'store-test')):
            result=self.export(prefix,store_id);self.assertFalse(result['valid'],result)
            self.assertNotIn('interactions',result)
        with self.assertRaises(TypeError):module.export_verified_interaction(self.h.directory,expected_store_id='store-test')

    def test_runtime_difference_rejects_old_store_without_migrating_manifest(self):
        original=module.runtime_manifest();prefix=self.prefix()
        with patch.object(module,'runtime_manifest',return_value=original|{'changed_runtime':'0'*64}):
            result=self.export(prefix)
        self.assertFalse(result['valid']);self.assertNotIn('interactions',result)
        self.assertTrue(self.h.report()['valid'])

    def test_database_path_replacement_after_replay_cannot_expose_selection(self):
        self.h.selected();prefix=self.prefix();original=module.replay_session
        def replace_after_replay(*args):
            model=original(*args)
            path=self.h.store.path;raw=path.read_bytes()
            path.rename(path.with_suffix('.original'))
            path.write_bytes(raw)  # same content, different file identity
            return model
        with patch.object(module,'replay_session',side_effect=replace_after_replay):
            result=module.export_verified_interaction(self.h.directory,expected_store_id='store-test',expected_prefix=prefix)
        self.assertFalse(result['valid']);self.assertNotIn('interactions',result)


if __name__=='__main__':unittest.main()
