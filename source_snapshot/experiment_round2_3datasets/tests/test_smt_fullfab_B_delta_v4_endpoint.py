"""Installed real pure/durable chain; synthetic files, zero external execution.

These cases have only been authored. The root agent owns the first serial run.
The lifecycle fixture describes fictional PIDs; it never starts a process.
"""
from base64 import b64decode
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from src.smt_fullfab import controller_delta_v4 as controller
from src.smt_fullfab import B_delta_durable_v5 as durable
from src.smt_fullfab import B_delta_call_bridge_v4 as bridge
from src.smt_fullfab import B_delta_transport_binding_v3 as binding
from src.smt_fullfab import B_delta_interaction_v3 as interaction
from tests import test_smt_fullfab_B_delta_v4_chain as baseline
from tests.test_smt_fullfab_B_delta_v4_support import fixture, SOURCE


def at(value, path):
    for key in path:value = value[key]
    return value


class InstalledChainTests(unittest.TestCase):
    # Reuse only the synthetic original-channel writer and fixture lifecycle.
    setUp = baseline.BridgeRejectionTests.setUp
    fake = baseline.BridgeRejectionTests.fake
    execute = baseline.BridgeRejectionTests.execute
    export = baseline.BridgeRejectionTests.export

    def response(self, result):
        return controller.verified_bridge_response(result, directory=result['evidence_dir'],
            store_id='new-rejection-protocol', instance_id='one', store_directory=self.store.directory)

    def send(self, request, memory='explicit legal memory'):
        self.request, self.memory = deepcopy(request), memory
        result = self.execute()
        self.assertEqual(result['phase'], 'action_processed', result)
        return self.response(result)

    def draft_action(self, draft_id, kind, **rest):
        state = self.export()['drafts'][draft_id]
        return {'schema': interaction.assembly_layer.SCHEMA, 'action': kind, 'draft_id': draft_id,
                'anchors': self.context['anchors'], 'previous_state_sha256': state['state_sha256'], **rest}

    def candidate(self, name, delta):
        self.assertEqual(self.send({'kind': 'create_draft', 'draft_id': name})['status'], 'draft_created')
        chunk = self.draft_action(name, 'chunk', sequence=0, chunk_id='explicit-piece',
            set_fields=[{'path': list(p), 'value': deepcopy(at(delta, p))} for p in interaction.assembly_layer.SET_PATHS],
            append_arrays=[{'path': list(p), 'items': deepcopy(at(delta, p))} for p in interaction.assembly_layer.ARRAY_PATHS])
        self.assertEqual(self.send({'kind': 'assembly_action', 'action': chunk})['status'], 'chunk_accepted')
        seal = self.draft_action(name, 'seal')
        self.assertEqual(self.send({'kind': 'assembly_action', 'action': seal})['status'], 'sealed_delta')
        state = self.export()['drafts'][name]
        checked = self.send({'kind': 'check_assembly', 'draft_id': name,
            'sealed_state_sha256': state['state_sha256'], 'seal_action_sha256': state['sealed']['seal_action_sha256'],
            'delta_sha256': state['sealed']['delta_sha256']})
        self.assertEqual(checked['status'], 'candidate_checked', checked)
        return checked['candidate']

    def test_rejection_then_legal_query_all_original_calls_accounted(self):
        self.send({'kind': 'read_candidates'}, memory='last legal memory')
        before = self.export()
        self.memory = 'x' * 8698;self.request = {'kind': 'create_draft', 'draft_id': 'not-dispatched'}
        rejected = self.execute()
        response = self.response(rejected)
        self.assertEqual(response['error']['code'], 'memory_size')
        self.assertFalse(controller.is_selection_response(response))
        after = self.export()
        for field in ('drafts', 'candidates', 'selection', 'query_session_evidence', 'current_memory'):
            self.assertEqual(before[field], after[field])
        self.send({'kind': 'catalog_page', 'path': ['paging_metadata'], 'offset': 0, 'count': 1}, memory='explicit next memory')
        rows = self.export()['history']
        self.assertEqual(len(rows), 3)
        self.assertEqual([r['call_id'] for r in rows], ['fixture-call-0', 'fixture-call-1', 'fixture-call-2'])
        self.assertEqual(len([r for r in self.f.rows if r['event'] == 'reserve']), 3)
        self.assertEqual(len([r for r in self.f.rows if r['event'] == 'finish']), 3)
        for index, row in enumerate(rows):
            self.assertEqual(b64decode(row['raw_output_base64']), (self.parent / f'model_{index:03d}' / 'final.txt').read_bytes())
        self.assertEqual(rows[1]['feedback_admission']['decision'], 'full_original_feedback')

    def reset_large_bootstrap(self, size):
        # A new local fixture with no original call or prior reservation exists.
        self.assertEqual(self.calls, 0)
        self.store = durable.DurableInteractionStore.create(self.root / 'large-durable', store_id='new-rejection-protocol')
        base, problem, state, paging, _ = fixture()
        base['tasks'][1]['original_unranked_large_field'] = 'x' * size
        result = self.store.register('one', dict(base_plan=base, problem=problem, execution_state=state,
            source_sha256=SOURCE, paging=paging))
        self.assertTrue(result['accepted'], result);self.context = result['value']

    def test_fifty_thousand_full_feedback_next_prompt_and_replay(self):
        self.reset_large_bootstrap(50000)
        response = self.send({'kind': 'session_query', 'action': {'action': 'read_base_tasks',
            'session_id': self.context['session_id'], 'anchors': self.context['anchors'], 'task_ids': ['z']}})
        row = self.export()['history'][0]
        self.assertGreater(len(interaction.render(response)), 50000)
        self.assertEqual(row['full_response'], row['feedback'])
        self.assertEqual(row['feedback_admission']['decision'], 'full_original_feedback')
        self.send({'kind': 'read_candidates'})
        prompt = json.loads((self.root / 'bridge-001/issued_prompt.txt').read_text().split('\nINPUT_JSON\n', 1)[1])
        self.assertEqual(prompt['feedback'], response)
        restored = self.export()  # Executes the new complete pure replay, including admission receipt.
        self.assertEqual(restored['history'][0], row)
        self.assertEqual(len(restored['history']), 2)

    def test_oversized_feedback_diagnostic_and_original_remain_in_store(self):
        self.reset_large_bootstrap(130000)
        response = self.send({'kind': 'session_query', 'action': {'action': 'read_base_tasks',
            'session_id': self.context['session_id'], 'anchors': self.context['anchors'], 'task_ids': ['z']}})
        row = self.export()['history'][0]
        self.assertEqual(row['full_response'], response)
        self.assertEqual(row['feedback_admission']['decision'], 'explicit_size_diagnostic')
        self.send({'kind': 'read_candidates'})
        body = json.loads((self.root / 'bridge-001/issued_prompt.txt').read_text().split('\nINPUT_JSON\n', 1)[1])
        self.assertEqual(body['feedback'], row['feedback'])
        self.assertFalse(body['feedback']['full_original_feedback_included'])
        self.assertEqual(self.export()['history'][0], row)

    def test_complete_compile_check_then_later_apply_older_candidate(self):
        _, _, _, _, delta = fixture()
        delta['tasks']['keep'] = {'mode': 'ids', 'ids': ['z', 'a']}
        delta['machine_orders'] = [{'machine': 2, 'task_ids': ['a']}, {'machine': 1, 'task_ids': ['z']}]
        first = self.candidate('first', delta)
        newer = deepcopy(delta);newer['plan_header']['version'] = 'explicit-second'
        second = self.candidate('second', newer)
        archive = self.send({'kind': 'read_candidates'})
        self.assertEqual([c['candidate_id'] for c in archive['candidates']], [first['candidate_id'], second['candidate_id']])
        self.assertIsNone(self.export()['selection'])
        selected = self.send({'kind': 'apply', 'candidate_id': first['candidate_id'], 'candidate_sha256': first['candidate_sha256']})
        self.assertTrue(controller.is_selection_response(selected))
        self.assertEqual(selected, self.export()['selection'])
        self.assertEqual(selected['candidate']['delta'], delta)
        self.assertEqual([t['id'] for t in selected['candidate']['compiled']['plan']['tasks']], ['z', 'a'])
        self.assertFalse(selected['physical_commit_performed'])
        self.assertEqual(self.export()['history'][-1]['feedback_admission']['decision'], 'terminal_no_next_prompt')
        self.assertEqual(self.calls, 10)  # Two four-output drafts + catalog + explicit later apply.

    def test_controller_rejects_unprocessed_rejection_and_no_auto_handle(self):
        self.memory = 'x' * 8698
        result = self.execute(process_success=False)
        before = self.store.path.read_bytes()
        with self.assertRaises(ValueError):self.response(result)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.assertEqual(self.export()['history'], [])

    def test_route_cannot_relabel_original_memory_rejection_as_action(self):
        self.memory = 'x' * 8698;result = self.execute()
        changed = {**result, 'phase': 'action_processed', 'success_action_eligible': True, 'rejection_record_eligible': False}
        with self.assertRaises(ValueError):self.response(changed)

    def test_returned_python_response_cannot_replace_verified_original(self):
        result = self.execute();changed = deepcopy(result)
        changed['interaction_response']['response'] = {'status': 'selection_for_external_commit', 'candidate': {}}
        with self.assertRaises(ValueError):self.response(changed)
        self.assertIsNone(self.export()['selection'])

    def test_bridge_archives_every_original_guard_file_and_rejects_late_change(self):
        result = self.execute();self.response(result)
        for name in binding.GUARD_FILES:
            self.assertEqual((Path(result['evidence_dir']) / 'raw' / (name + '.bin')).read_bytes(), (self.f.run / name).read_bytes())
        (self.f.run / 'process_guard/parent_observed.json').write_bytes(b'{}\n')
        with self.assertRaises(ValueError):self.response(result)

    def test_missing_lifecycle_never_becomes_processed_action(self):
        def no_guard(*args, **kwargs):
            self.fake(*args, **kwargs)
            (self.f.run / 'process_guard/parent_observed.json').unlink()
        result = self.execute(transport_call=no_guard)
        self.assertEqual(result['phase'], 'diagnosis_required', result)
        self.assertEqual(self.export()['history'], [])
        self.assertEqual(self.calls, 1)

    def test_new_wire_schema_exact_bytes_and_source_runtime(self):
        self.assertEqual(controller.response_schema(), self.f.schema)
        result = self.execute();self.response(result)
        raw = (Path(result['evidence_dir']) / 'issued_schema.json').read_bytes()
        self.assertEqual(raw, (json.dumps(controller.response_schema(), ensure_ascii=False, indent=2)+'\n').encode())
        manifest = durable.runtime_manifest()
        root = Path(__file__).resolve().parents[1]
        for name, expected in manifest.items():
            self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), expected)
        self.assertEqual(hashlib.sha256((root / 'src/smt_fullfab/B_delta_interaction_v3.py').read_bytes()).hexdigest(), durable.INTERACTION_SHA256)
        self.assertEqual(manifest['src/smt_fullfab/B_feedback_admission.py'], interaction.DEPENDENCIES['feedback_admission.py'])
        for old in ('B_delta_interaction.py', 'B_delta_durable.py', 'B_delta_call_bridge.py', 'B_delta_transport_binding.py'):
            self.assertNotIn('src/smt_fullfab/' + old, manifest)

    def test_original_production_store_rejected_without_writing(self):
        from src.smt_fullfab import B_delta_durable as old
        store = old.DurableInteractionStore.create(self.root / 'original-production-store', store_id='old')
        before = {str(p): p.read_bytes() for p in store.directory.rglob('*') if p.is_file()}
        proof = durable.recover_read_only(store.directory, expected_store_id='old')
        self.assertFalse(proof['valid'])
        self.assertEqual({str(p): p.read_bytes() for p in store.directory.rglob('*') if p.is_file()}, before)


class ControllerBoundaryTests(unittest.TestCase):
    def test_public_execution_stays_blocked_before_source_or_ledger(self):
        with patch.object(controller, '_run_registered', side_effect=AssertionError('gate not authorized')):
            with self.assertRaisesRegex(RuntimeError, 'public execution blocked'):
                controller.run('B_not_registered', expected_source_sha256='0'*64)

    def test_exact_phase_and_eligibility_failure_matrix(self):
        verified = {'valid': True, 'errors': [], 'saved_phase': 'envelope_rejected_recorded',
            'phase': 'envelope_rejection_already_recorded_no_replay',
            'success_action_eligible': False, 'rejection_record_eligible': True,
            'read_only_success_binding': {'local_channel_files_and_ledger_verified': True, 'errors': [],
                'success_action_eligible': False, 'rejection_record_eligible': True,
                'envelope': {'kind': 'memory_size_rejection'}, 'process_guard': {'lifecycle_complete': True}}}
        self.assertEqual(controller.verified_processed_kind(verified, 'envelope_rejected_recorded'), 'memory_size_rejection')
        for key, value in [('valid', False), ('errors', ['x']), ('success_action_eligible', True),
            ('rejection_record_eligible', 1), ('phase', 'terminal_envelope_rejection_requires_explicit_processing'),
            ('saved_phase', 'action_processed'), ('read_only_success_binding', {})]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                controller.verified_processed_kind({**verified, key: value}, 'envelope_rejected_recorded')

    def test_rejection_row_cannot_have_request_projection_or_changed_memory(self):
        row = {'parsed_envelope': None, 'projection': None, 'memory_before': {'memory': 'x'}, 'memory_after': {'memory': 'x'},
            'full_response': {'status': 'rejected', 'error': {'code': 'memory_size'}}}
        controller.verify_history_kind(row, 'memory_size_rejection')
        for changed in ({**row, 'projection': {}}, {**row, 'parsed_envelope': {}},
                        {**row, 'memory_after': {'memory': 'new'}},
                        {**row, 'full_response': {'status': 'rejected', 'error': {'code': 'stale_context'}}}):
            with self.assertRaises(ValueError):controller.verify_history_kind(changed, 'memory_size_rejection')


if __name__ == '__main__':
    unittest.main()
