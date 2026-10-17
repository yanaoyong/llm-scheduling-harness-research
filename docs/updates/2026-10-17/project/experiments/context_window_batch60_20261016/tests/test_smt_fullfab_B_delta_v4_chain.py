"""Pure synthetic temporary file tests. AUTHORED, NOT EXECUTED during drafting."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import shutil
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab import B_delta_transport_binding_v3 as b
from src.smt_fullfab import B_delta_call_bridge_v4 as bridge
from src.smt_fullfab import B_delta_durable_v5 as d
from src.smt_fullfab import B_delta_envelope_policy_v2 as policy
from tests.test_smt_fullfab_B_delta_v4_support import Fixture, encoded, fixture, SOURCE, toml


class BindingSeparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.f = Fixture(self.temp.name)

    def oversized(self):
        self.f.output['memory'] = 'x' * 8698  # Exactly 8700 serialized characters.
        self.f.sync_result()

    def fail_closed(self):
        result = self.f.bind()
        self.assertFalse(result.report['local_channel_files_and_ledger_verified'], result.report)
        self.assertFalse(result.report['success_action_eligible'])
        self.assertFalse(result.report['rejection_record_eligible'])
        self.assertTrue(result.report['errors'])
        with self.assertRaises(b.BindingError):result.durable_attachments()
        return result

    def test_only_memory_overflow_is_completed_rejection_not_action(self):
        self.oversized();before = {p: p.read_bytes() for p in self.f.root.rglob('*') if p.is_file()}
        result = self.f.bind();report = result.report
        self.assertTrue(report['local_channel_files_and_ledger_verified'], report)
        self.assertFalse(report['success_action_eligible']);self.assertFalse(report['interaction_envelope_verified'])
        self.assertTrue(report['rejection_record_eligible']);self.assertEqual(report['errors'], [])
        self.assertEqual(report['envelope']['memory_serialized_characters'], 8700)
        self.assertEqual(report['envelope']['error']['code'], 'memory_size')
        self.assertEqual(result.durable_attachments()['completion']['final_bytes'], encoded(self.f.output))
        self.assertEqual(report['usage']['input_tokens'], 3)
        self.assertFalse(report['assurance']['actual_backend_invocation_independently_proven'])
        self.assertEqual(before, {p: p.read_bytes() for p in self.f.root.rglob('*') if p.is_file()})

    def test_exact_limit_and_empty_memory_remain_valid(self):
        for memory in ('', 'x' * 8190):
            self.f.output['memory'] = memory;self.f.sync_result();result = self.f.bind()
            self.assertTrue(result.report['success_action_eligible'], result.report)
            self.assertFalse(result.report['rejection_record_eligible'])

    def test_unicode_escaping_is_counted_exactly(self):
        self.f.output['memory'] = '中' * 1366;self.f.sync_result()
        report = self.f.bind().report
        self.assertTrue(report['rejection_record_eligible'], report)
        self.assertEqual(report['envelope']['memory_serialized_characters'], 8198)

    def test_nonstring_memory_is_not_rejection_allowlisted(self):
        for memory in (None, True, [], {}, 8193):
            self.f.output['memory'] = memory;self.f.sync_result();self.fail_closed()

    def test_wrong_outer_context_or_body_never_softened(self):
        original = deepcopy(self.f.output)
        for key in ('interaction_id', 'session_id', 'anchors', 'catalog_sha256', 'prompt_body_sha256', 'schema'):
            with self.subTest(key=key):
                self.f.output = deepcopy(original);self.f.result['output'] = self.f.output
                self.f.output['memory'] = 'x' * 8698
                self.f.output[key] = {} if key == 'anchors' else 'wrong'
                self.f.sync_result();self.fail_closed()

    def test_anyof_nested_type_error_is_not_hidden_by_memory_error(self):
        self.oversized()
        self.f.output['request'] = {'kind': 'catalog_page', 'path': [], 'offset': True, 'count': 1}
        self.f.sync_result();report = self.fail_closed().report
        self.assertEqual(report['errors'][0]['code'], 'output_schema')

    def test_nested_query_anchor_and_session_mismatch_stop(self):
        self.oversized()
        action = {'action': 'read_page', 'page_index': 0, 'anchors': deepcopy(self.f.context['anchors']), 'session_id': self.f.context['session_id']}
        self.f.output['request'] = {'kind': 'session_query', 'action': action}
        action['anchors']['state_sha256'] = '0' * 64;self.f.sync_result();self.fail_closed()
        action['anchors'] = deepcopy(self.f.context['anchors']);action['session_id'] = 'wrong'
        self.f.sync_result();self.fail_closed()

    def test_nested_assembly_anchor_mismatch_stops(self):
        self.oversized()
        self.f.output['request'] = {'kind': 'assembly_action', 'action': {
            'schema': 'draft-smt-fullfab-delta-assembly-v1', 'action': 'seal', 'draft_id': 'x',
            'anchors': {**self.f.context['anchors'], 'problem_sha256': '0' * 64}, 'previous_state_sha256': 'f' * 64}}
        self.f.sync_result();self.fail_closed()

    def test_unknown_schema_keyword_is_not_silently_ignored(self):
        schema = deepcopy(self.f.schema);schema['properties']['memory']['maxLength'] = 99999
        with self.assertRaises(policy.PolicyError):
            policy.classify(self.f.output, self.f.prompt, self.f.context, schema)

    def test_missing_finish_pending_remains_hard_stop(self):
        self.oversized();self.f.rows.pop();self.f.sync_ledger();self.fail_closed()

    def test_duplicate_reserve_is_hard_stop(self):
        self.oversized();self.f.rows.append(deepcopy(self.f.reserve));self.f.sync_ledger();self.fail_closed()

    def test_timeout_is_not_a_completed_wrapper_rejection(self):
        self.oversized()
        self.f.result.update(status='timeout', failure_reason='model_call_timeout', timed_out=True, returncode=-15)
        self.f.finish['status'] = 'timeout';self.f.sync_result();self.fail_closed()

    def test_native_tool_event_is_not_a_completed_wrapper_rejection(self):
        self.oversized()
        self.f.events.insert(1, {'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'not executed fixture'}})
        self.f.sync_result();self.fail_closed()

    def test_final_event_raw_disagreement_is_not_softened(self):
        self.oversized()
        self.f.events[1]['item']['text'] += ' '
        self.f.sync_result(update_agent_text=False);self.fail_closed()

    def test_unknown_usage_keeps_null_and_does_not_invent_known_cost(self):
        self.oversized();self.f.events[-1].pop('usage');self.f.sync_result();report = self.f.bind().report
        self.assertTrue(report['rejection_record_eligible'], report);self.assertFalse(report['usage_known'])
        self.assertIsNone(report['usage']['input_tokens'])

    def test_illegal_usage_stops_even_if_result_and_finish_coerce_it(self):
        self.oversized();self.f.events[-1]['usage']['input_tokens'] = True
        self.f.result['usage']['input_tokens'] = 1
        self.f.write('events.jsonl', b''.join((json.dumps(e) + '\n').encode() for e in self.f.events))
        self.f.write_json('result.json', self.f.result);self.f.finish['details']['usage'] = deepcopy(self.f.result['usage'])
        self.f.sync_ledger();self.fail_closed()

    def test_original_schema_request_command_and_final_tamper_stop(self):
        self.oversized()
        for name in ('schema.json', 'request.json', 'command.json', 'attempt.claim', 'system-instructions.txt', 'final.txt'):
            with self.subTest(name=name):
                old = (self.f.run / name).read_bytes()
                self.f.write(name, b'{}\n');self.fail_closed();self.f.write(name, old)

    def test_late_path_replacement_cannot_publish_rejection_eligibility(self):
        self.oversized();original = b.verify_envelope
        def replace_after_parse(*args):
            answer = original(*args)
            p = self.f.run / 'final.txt';q = self.f.run / 'late';q.write_bytes(p.read_bytes());q.replace(p)
            return answer
        with patch.object(b, 'verify_envelope', replace_after_parse):self.fail_closed()

    def test_equal_schema_meaning_does_not_authorize_reordered_request_bytes(self):
        self.oversized()
        reordered = json.loads(json.dumps(self.f.schema, sort_keys=True))
        self.assertTrue(b.same(reordered, self.f.schema))
        self.assertNotEqual(encoded(reordered), self.f.schema_raw)
        report = self.f.bind(expected_schema=reordered).report
        self.assertFalse(report['local_channel_files_and_ledger_verified'], report)
        self.assertFalse(report['rejection_record_eligible'])
        self.assertEqual(report['errors'][0]['code'], 'request_bytes')


class BridgeRejectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve();self.f = Fixture(self.root)
        self.parent = self.f.run.parent
        shutil.rmtree(self.f.run);self.f.rows = self.f.rows[:3];self.f.sync_ledger()
        self.store = d.DurableInteractionStore.create(self.root / 'durable', store_id='new-rejection-protocol')
        base, problem, state, paging, _ = fixture()
        registered = self.store.register('one', dict(base_plan=base, problem=problem, execution_state=state, source_sha256=SOURCE, paging=paging))
        self.assertTrue(registered['accepted'], registered);self.context = registered['value']
        self.calls = 0;self.memory = 'legal original memory';self.request = {'kind': 'read_candidates'}
        self.fail = None;self.last_args = None

    def fake(self, prompt, schema, run, config, *, resume):
        """Write only temporary original-channel-shaped files; no BudgetLedger/CLI."""
        self.assertFalse(resume);self.calls += 1
        f = self.f;prior = deepcopy(f.rows);index = self.calls - 1
        f.run = Path(run);f.run.mkdir();f.prompt = prompt;f.schema = schema;f.schema_raw = encoded(schema);f.config = config
        f.cid = 'fixture-call-' + str(index)
        fingerprint = b.sha((prompt + '\n' + f.schema_raw.decode() + '\n' + json.dumps(config, sort_keys=True)).encode())
        f.request = {'call_id': f.cid, 'started_at': '2026-10-10T01:00:00+00:00', 'request_fingerprint': fingerprint, 'config': config}
        f.output = {'schema': d.interaction.RESPONSE_SCHEMA, **self.context,
                    'prompt_body_sha256': prompt.split('\n', 1)[0].split('=', 1)[1],
                    'memory': self.memory, 'request': deepcopy(self.request)}
        f.result = {**deepcopy(f.result), 'call_id': f.cid, 'request_fingerprint': fingerprint, 'config': config,
                    'prompt_characters': len(prompt), 'output': f.output, 'status': 'success', 'failure_reason': None}
        f.reserve = {**deepcopy(f.reserve), 'call_id': f.cid, 'run_id': run,
            'metadata': {**f.reserve['metadata'], 'request_fingerprint': fingerprint, 'prompt_characters': len(prompt)},
            'run_account_before': {'attempts': index, 'reported_input_output_tokens': 5 * index,
                'unknown_completed': [], 'pending': [], 'model_active_seconds': float(index)}}
        f.finish = {'event': 'finish', 'call_id': f.cid, 'status': 'success', 'details': {}}
        f.rows = prior + [f.reserve, f.finish]
        f.events = [{'type': 'thread.started', 'thread_id': 'fake-' + str(index)},
                    {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': ''}},
                    {'type': 'turn.completed', 'usage': {'input_tokens': 3, 'output_tokens': 2}}]
        command = {'cwd': str(f.run / 'isolated-cwd'), 'stdin': 'prompt.txt', 'proxy': None,
            'argv': [config['codex_binary'], 'exec', '--json', '--ephemeral', '--ignore-user-config', '--ignore-rules',
                     '--skip-git-repo-check', '--sandbox', 'read-only', '--color', 'never', '--model', 'gpt-6-astra',
                     '--cd', str(f.run / 'isolated-cwd'), '--output-schema', str(f.run / 'schema.json'),
                     '--output-last-message', str(f.run / 'final.txt')]}
        for key, value in {**b.expected_settings(f.run, config), 'skills.config': []}.items():
            command['argv'] += ['-c', key + '=' + toml(value)]
        command['argv'].append('-')
        f.write('prompt.txt', prompt.encode());f.write('schema.json', f.schema_raw)
        f.write('system-instructions.txt', b.SYSTEM_TEXT.encode());f.write('attempt.claim', (fingerprint + '\n').encode())
        f.write_json('request.json', f.request);f.write_json('command.json', command);f.write('stderr.log', b'original stderr\n')
        f.sync_result()
        if self.fail == 'no_finish':f.rows.pop();f.sync_ledger()
        if self.fail == 'raise_after_finish':raise RuntimeError('synthetic post-finish interruption')
        return {'fabricated_return': 'ignored'}

    def execute(self, **changes):
        index = self.calls
        authorization = {'ledger_path': str(self.f.ledger), 'ledger_before_sha256': bridge.sha(self.f.ledger.read_bytes()),
            'approval_sha256': b._record_digest(self.f.approval), 'registration_id': self.f.registration['registration_id'],
            'registration_sha256': b._record_digest(self.f.registration), 'disabled_skill_paths': []}
        args = dict(expected_store_id='new-rejection-protocol', instance_id='one', attempt_id='attempt-' + str(index), model_index=index,
            transport_run_dir=str(self.parent / ('model_%03d' % index)), evidence_dir=self.root / ('bridge-%03d' % index),
            config=self.f.config, schema=self.f.schema, expected_context=self.context, authorization=authorization,
            transport_call=self.fake, process_success=True)
        args.update(changes);self.last_args = args
        return bridge.execute_once(self.store, **args)

    def export(self):
        proof = d.recover_read_only(self.store.directory, expected_store_id='new-rejection-protocol')
        self.assertTrue(proof['valid'], proof)
        prefix = {k: proof[k] for k in ('journal_records', 'journal_tail_sha256', 'database_sha256')}
        report = d.export_verified_interaction(self.store.directory, expected_store_id='new-rejection-protocol', expected_prefix=prefix)
        self.assertTrue(report['valid'], report)
        return report['interactions'][0]['evidence']

    def test_rejection_keeps_legal_memory_feedback_then_explicit_new_request(self):
        self.memory = 'x' * 8181  # Serialized 8183, mirrors call16 occupancy without using its decisions.
        first = self.execute();self.assertEqual(first['phase'], 'action_processed', first)
        before = self.export();self.memory = 'x' * 8698
        self.request = {'kind': 'create_draft', 'draft_id': 'must-not-execute'}
        second = self.execute();self.assertEqual(second['phase'], 'envelope_rejected_recorded', second)
        self.assertFalse(second['success_action_eligible']);self.assertTrue(second['rejection_record_eligible'])
        after = self.export();self.assertEqual(after['current_memory'], before['current_memory'])
        self.assertEqual(after['drafts'], {});self.assertEqual(after['candidates'], []);self.assertIsNone(after['selection'])
        last = after['history'][-1];self.assertIsNone(last['projection']);self.assertIsNone(last['parsed_envelope'])
        self.assertEqual(last['full_response']['error']['code'], 'memory_size')
        self.assertEqual((Path(second['evidence_dir']) / 'raw/final.txt.bin').read_bytes(), (self.f.run / 'final.txt').read_bytes())
        self.memory = 'new model-authored short memory';self.request = {'kind': 'read_candidates'}
        third = self.execute();self.assertEqual(third['phase'], 'action_processed', third)
        prompt = json.loads((Path(third['evidence_dir']) / 'issued_prompt.txt').read_text().split('\nINPUT_JSON\n', 1)[1])
        self.assertEqual(prompt['memory'], before['current_memory']['memory'])
        self.assertEqual(prompt['memory_binding']['source']['call_id'], 'fixture-call-0')
        self.assertEqual(prompt['feedback'], last['feedback'])
        self.assertEqual(self.calls, 3)
        self.assertEqual(len([r for r in self.f.rows if r.get('event') == 'reserve']), 3)

    def test_bad_wrapper_never_dispatches_apply(self):
        self.memory = 'x' * 8698
        self.request = {'kind': 'apply', 'candidate_id': 'nonexistent', 'candidate_sha256': 'f' * 64}
        with patch.object(d.interaction.Interaction, '_dispatch', side_effect=AssertionError('bad wrapper dispatched')):
            result = self.execute()
        self.assertEqual(result['phase'], 'envelope_rejected_recorded', result);self.assertIsNone(self.export()['selection'])

    def test_bad_wrapper_never_dispatches_nested_action(self):
        self.memory = 'x' * 8698
        self.request = {'kind': 'session_query', 'action': {'action': 'read_page', 'session_id': self.context['session_id'],
                        'anchors': self.context['anchors'], 'page_index': 0}}
        with patch.object(d.interaction.Interaction, '_dispatch', side_effect=AssertionError('nested action dispatched')):
            result = self.execute()
        self.assertEqual(result['phase'], 'envelope_rejected_recorded', result)

    def test_readonly_recovery_of_recorded_rejection_changes_no_bytes(self):
        self.memory = 'x' * 8698;result = self.execute()
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch.object(d.DurableInteractionStore, 'process_completed', side_effect=AssertionError('recovery must not process')):
            report = bridge.recover_read_only(result['evidence_dir'], expected_intent_sha256=result['intent_sha256'], expected_outcome_sha256=result['outcome_sha256'])
        self.assertTrue(report['valid'], report);self.assertEqual(report['phase'], 'envelope_rejection_already_recorded_no_replay')
        self.assertFalse(report['success_action_eligible']);self.assertTrue(report['rejection_record_eligible'])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_unprocessed_rejection_does_not_get_handled_by_recovery(self):
        self.memory = 'x' * 8698;result = self.execute(process_success=False)
        self.assertEqual(result['phase'], 'terminal_envelope_rejection_unprocessed', result)
        with patch.object(d.interaction.Interaction, 'handle', side_effect=AssertionError('unprocessed raw output handled')):
            recovered = bridge.recover_read_only(result['evidence_dir'], expected_intent_sha256=result['intent_sha256'], expected_outcome_sha256=result['outcome_sha256'])
        self.assertTrue(recovered['valid'], recovered);self.assertEqual(recovered['phase'], 'terminal_envelope_rejection_requires_explicit_processing')
        self.assertEqual(self.export()['history'], [])

    def test_interruption_after_finish_preserves_unprocessed_rejection(self):
        self.memory = 'x' * 8698;self.fail = 'raise_after_finish';result = self.execute()
        self.assertEqual(result['phase'], 'terminal_envelope_rejection_unprocessed', result)
        self.assertEqual(self.export()['history'], [])

    def test_no_finish_is_pending_not_wrapper_feedback(self):
        self.memory = 'x' * 8698;self.fail = 'no_finish';result = self.execute()
        self.assertEqual(result['phase'], 'pending_original_call', result);self.assertEqual(self.export()['history'], [])

    def test_duplicate_attempt_never_calls_transport_again(self):
        self.memory = 'x' * 8698;self.execute()
        with self.assertRaises(bridge.BridgeError):bridge.execute_once(self.store, **self.last_args)
        self.assertEqual(self.calls, 1)

    def test_explicit_wrong_processing_kind_is_refused(self):
        self.memory = 'x' * 8698;self.execute(process_success=False)
        rejected = self.store.process_completed('one', attempt_id='attempt-0', expected_processing_kind='action')
        self.assertFalse(rejected['accepted']);self.assertEqual(self.export()['history'], [])

    def test_complete_runtime_dependency_manifest_and_old_version_refusal(self):
        runtime = d.runtime_manifest()
        for name in ('B_delta_call_bridge_v4.py', 'B_delta_transport_binding_v3.py', 'B_delta_envelope_policy_v2.py',
                     'B_delta_interaction_v3.py', 'B_feedback_admission.py', 'model_transport_supervised.py',
                     'model_process_guard.py', 'controller_delta_v4.py', 'controller_audit.py', 'constructor_audit.py'):
            self.assertIn('src/smt_fullfab/' + name, runtime)
        self.assertNotEqual(d.SCHEMA, 'draft-smt-fullfab-durable-interaction-v2')
        for index, old_schema in enumerate(('draft-smt-fullfab-durable-interaction-v2',
                'draft-smt-fullfab-durable-interaction-v3-envelope-rejection',
                'draft-smt-fullfab-durable-interaction-v4-envelope-rejection-schema-bytes')):
            with patch.object(d, 'SCHEMA', old_schema):
                old = d.DurableInteractionStore.create(self.root / ('old-version-' + str(index)), store_id='legacy')
            self.assertFalse(d.recover_read_only(old.directory)['valid'])

    def test_saved_intent_retains_exact_pre_reservation_schema_bytes(self):
        from base64 import b64decode
        result = self.execute()
        self.assertEqual(result['phase'], 'action_processed', result)
        directory = Path(result['evidence_dir'])
        intent = json.loads((directory / 'intent.json').read_bytes())
        original = (directory / 'issued_schema.json').read_bytes()
        self.assertNotEqual(encoded(intent['schema_json']), original)
        self.assertTrue(b.same(intent['schema_json'], b.parse(original)))
        self.assertEqual(b64decode(intent['schema_utf8_base64'], validate=True), original)
        self.assertEqual(intent['schema_raw_sha256'], b.sha(original))
        self.assertEqual(original, (self.f.run / 'schema.json').read_bytes())
        _, state, _ = bridge.inspect_store(self.store, 'new-rejection-protocol', 'attempt-0')
        self.assertEqual(state['_inspected_attempt']['schema_bytes'], original)
        report = bridge.recover_read_only(directory, expected_intent_sha256=result['intent_sha256'],
                                         expected_outcome_sha256=result['outcome_sha256'])
        self.assertTrue(report['valid'], report)
        self.assertEqual(report['phase'], 'action_already_processed_no_replay')

    def test_reordered_raw_schema_is_rejected_even_with_consistent_new_intent_hash(self):
        from base64 import b64encode
        result = self.execute(process_success=False)
        directory = Path(result['evidence_dir'])
        intent = json.loads((directory / 'intent.json').read_bytes())
        reordered = encoded(intent['schema_json'])
        self.assertNotEqual(reordered, (directory / 'issued_schema.json').read_bytes())
        intent['schema_utf8_base64'] = b64encode(reordered).decode('ascii')
        intent['schema_raw_sha256'] = b.sha(reordered)
        changed = bridge.encode(intent)
        (directory / 'intent.json').write_bytes(changed)
        report = bridge.recover_read_only(directory, expected_intent_sha256=b.sha(changed),
                                         expected_outcome_sha256=result['outcome_sha256'])
        self.assertFalse(report['valid'], report)
        self.assertIn('bridge schema differs from durable reservation', str(report['errors']))

    def test_raw_schema_hash_base64_and_semantic_mismatch_are_all_refused(self):
        result = self.execute(process_success=False)
        intent = json.loads((Path(result['evidence_dir']) / 'intent.json').read_bytes())
        for changed in ({**intent, 'schema_raw_sha256': '0' * 64},
                        {**intent, 'schema_utf8_base64': '%%% not raw bytes %%%'},
                        {**intent, 'schema_json': {'type': 'string'}},
                        {k: v for k, v in intent.items() if k != 'schema_utf8_base64'}):
            with self.subTest(fields=set(changed)), self.assertRaises((ValueError, TypeError)):
                bridge.intent_schema_bytes(changed)

    def test_old_bridge_intent_cannot_be_upgraded_by_current_reader(self):
        result = self.execute(process_success=False)
        directory = Path(result['evidence_dir'])
        intent = json.loads((directory / 'intent.json').read_bytes())
        intent['schema'] = 'draft-smt-fullfab-B-delta-call-bridge-v2-envelope-rejection'
        intent.pop('schema_utf8_base64');intent.pop('schema_raw_sha256')
        changed = bridge.encode(intent);(directory / 'intent.json').write_bytes(changed)
        report = bridge.recover_read_only(directory, expected_intent_sha256=b.sha(changed),
                                         expected_outcome_sha256=result['outcome_sha256'])
        self.assertFalse(report['valid'], report);self.assertIn('bridge schema mismatch', str(report['errors']))

    def test_recomputed_journal_cannot_relabel_rejection_as_action(self):
        self.memory = 'x' * 8698;self.execute()
        with sqlite3.connect(self.store.path) as db:
            db.execute('DROP TRIGGER no_update_journal')
            rows = db.execute('SELECT sequence,kind,payload,previous_sha256,event_sha256 FROM journal ORDER BY sequence').fetchall()
            tail = None
            for sequence, kind, raw, _, _ in rows:
                payload = json.loads(raw)
                if kind == 'action_recorded':payload['processing']['kind'] = 'action'
                event = dict(sequence=sequence, kind=kind, payload=payload, previous_sha256=tail)
                hashed = d.digest(event)
                db.execute('UPDATE journal SET payload=?,previous_sha256=?,event_sha256=? WHERE sequence=?',
                           (d.encode(payload).decode(), tail, hashed, sequence));tail = hashed
        report = d.recover_read_only(self.store.directory)
        self.assertFalse(report['valid'], report);self.assertEqual(report['errors'][0]['code'], 'processing_replay')


if __name__ == '__main__':
    unittest.main()
