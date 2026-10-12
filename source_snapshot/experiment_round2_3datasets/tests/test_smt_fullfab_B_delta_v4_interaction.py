"""Only synthetic JSON interaction chains; no external calls or physical runtime."""
from base64 import b64decode
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from src.smt_fullfab import B_delta_interaction_v3 as module
from src.smt_fullfab.B_delta_interaction_v3 import Interaction, Error, AdmissionError, digest, render
from tests.test_smt_fullfab_delta_session import fixture, SOURCE


def at(root, path):
    for key in path:
        root = root[key]
    return root


class InteractionTests(unittest.TestCase):
    def setUp(self):
        self.base, self.problem, self.state, self.paging, self.delta = fixture()
        self.delta['tasks']['keep'] = {'mode': 'ids', 'ids': ['z', 'a']}
        self.delta['machine_orders'] = [{'machine': 2, 'task_ids': ['a']}, {'machine': 1, 'task_ids': ['z']}]
        self.session = self.new()
        self.index = 0

    def new(self):
        return Interaction(self.base, self.problem, self.state, source_sha256=SOURCE, paging=self.paging)

    def envelope(self, request, memory='model memory 原样\n'):
        prompt = self.session.next_prompt()
        return {'schema': module.RESPONSE_SCHEMA, **self.session.context(), 'prompt_body_sha256': prompt['prompt_body_sha256'],
                'memory': memory, 'request': deepcopy(request)}

    def raw(self, envelope):
        return json.dumps(envelope, ensure_ascii=False, separators=(',', ':')).encode()

    def send_raw(self, raw, call_id=None, index=None):
        index = self.index if index is None else index
        call_id = 'call-' + str(index) if call_id is None else call_id
        self.index = max(self.index, index + 1) if type(index) is int else self.index + 1
        return self.session.handle(raw, call_id=call_id, model_index=index)

    def send(self, request, memory='model memory 原样\n'):
        return self.send_raw(self.raw(self.envelope(request, memory)))

    def draft_action(self, did, kind, **extra):
        state = self.session.export_evidence()['drafts'][did]
        return {'schema': module.assembly_layer.SCHEMA, 'action': kind, 'draft_id': did,
                'anchors': self.session.context()['anchors'], 'previous_state_sha256': state['state_sha256'], **extra}

    def build(self, did='draft-1', delta=None, split=True):
        delta = self.delta if delta is None else delta
        self.assertEqual(self.send({'kind': 'create_draft', 'draft_id': did})['response']['status'], 'draft_created')
        sets = [{'path': list(p), 'value': deepcopy(at(delta, p))} for p in module.assembly_layer.SET_PATHS]
        arrays = [{'path': list(p), 'items': deepcopy(at(delta, p))} for p in module.assembly_layer.ARRAY_PATHS]
        later = []
        if split:
            for row in arrays:
                if row['path'] in (['tasks', 'keep', 'ids'], ['machine_orders']):
                    later.append({'path': row['path'], 'items': row['items'][1:]})
                    row['items'] = row['items'][:1]
        first = self.draft_action(did, 'chunk', sequence=0, chunk_id='part-1', set_fields=sets, append_arrays=arrays)
        self.assertEqual(self.send({'kind': 'assembly_action', 'action': first})['response']['status'], 'chunk_accepted')
        if later:
            second = self.draft_action(did, 'chunk', sequence=1, chunk_id='part-2', set_fields=[], append_arrays=later)
            self.assertEqual(self.send({'kind': 'assembly_action', 'action': second})['response']['status'], 'chunk_accepted')
        seal = self.draft_action(did, 'seal')
        self.assertEqual(self.send({'kind': 'assembly_action', 'action': seal})['response']['status'], 'sealed_delta')
        return self.check_request(did)

    def check_request(self, did):
        archive = self.session.export_evidence()['drafts'][did]
        return {'kind': 'check_assembly', 'draft_id': did, 'sealed_state_sha256': archive['state_sha256'],
                'seal_action_sha256': archive['sealed']['seal_action_sha256'], 'delta_sha256': archive['sealed']['delta_sha256']}

    def checked(self, did='draft-1', delta=None):
        result = self.send(self.build(did, delta))
        self.assertEqual(result['response']['status'], 'candidate_checked', result)
        return result['response']['candidate']

    @staticmethod
    def candidate_request(kind, candidate, **extra):
        return {'kind': kind, 'candidate_id': candidate['candidate_id'], 'candidate_sha256': candidate['candidate_sha256'], **extra}

    def assert_rejected(self, result, code):
        self.assertEqual(result['response']['status'], 'rejected', result)
        self.assertEqual(result['response']['error']['code'], code, result)

    def test_explicit_full_chain_and_candidate_provenance(self):
        with patch.object(module, 'compile_plan_delta', wraps=module.compile_plan_delta) as compiler:
            request = self.build()
            self.assertEqual(compiler.call_count, 0)
            self.assertIsNone(self.session.export_evidence()['selection'])
            candidate = self.send(request)['response']['candidate']
            self.assertEqual(compiler.call_count, 1)
            read = self.send(self.candidate_request('read_candidate', candidate, path=['compiled', 'plan', 'tasks'], format='page', offset=0, count=2))
            self.assertEqual([t['id'] for t in read['response']['payload']], ['z', 'a'])
            self.assertIsNone(self.session.export_evidence()['selection'])
            applied = self.send(self.candidate_request('apply', candidate))
            self.assertEqual(applied['response']['status'], 'selection_for_external_commit')
            self.assertEqual(compiler.call_count, 1)
        record = self.session.export_evidence()
        c = record['candidates'][0]['candidate']
        self.assertEqual(c['delta'], self.delta)
        self.assertEqual([e['assembly_action'] for e in c['provenance']['assembly_actions']], ['chunk', 'chunk', 'seal'])
        bindings = [c['provenance']['create'], *c['provenance']['assembly_actions'], c['provenance']['check']]
        for binding in bindings:
            row = record['history'][binding['history_index']]
            self.assertEqual(binding['raw_output_sha256'], row['raw_output_sha256'])
            self.assertEqual(binding['call_id'], row['call_id'])
            self.assertEqual(binding['envelope_sha256'], digest(row['parsed_envelope']))
        self.assertEqual(record['query_session_evidence']['candidates'], [])
        self.assertEqual(record['query_session_evidence']['history'], [])
        self.assertIn('not a single original check_delta', c['provenance']['delta_origin'])
        self.assertFalse(applied['response']['physical_commit_performed'])
        self.assertFalse(applied['response']['transport_authenticated'])

    def test_multiple_candidates_have_no_default_and_model_can_choose_older(self):
        first = self.checked()
        delta = deepcopy(self.delta);delta['plan_header']['version'] = 'delta-2'
        second = self.checked('draft-2', delta)
        response = self.send({'kind': 'read_candidates'})['response']
        self.assertEqual([c['candidate_id'] for c in response['candidates']], [first['candidate_id'], second['candidate_id']])
        self.assertIsNone(self.session.export_evidence()['selection'])
        chosen = self.send(self.candidate_request('apply', first))['response']
        self.assertEqual(chosen['candidate_sha256'], first['candidate_sha256'])

    def test_query_catalog_original_pages_and_exact_references(self):
        catalog = self.session.export_evidence()['full_catalog']['catalog']
        original_actions = []
        for kind, field, value in [('read_page', 'page_index', 0), ('read_base_tasks', 'task_ids', ['a', 'z']),
                                   ('read_base_holds', 'hold_refs', ['h:2', 'h:0']), ('read_operations', 'operation_ids', ['op-a', 'op-z'])]:
            action = {'action': kind, 'session_id': catalog['session_id'], 'anchors': catalog['anchors'], field: value}
            original_actions.append(action)
            response = self.send({'kind': 'session_query', 'action': action})['response']
            self.assertEqual(response['status'], 'query_result')
            if kind == 'read_base_tasks':
                self.assertEqual([t['id'] for t in response['tasks']], ['a', 'z'])
        qs = self.session.export_evidence()['query_session_evidence']
        self.assertEqual([row['action'] for row in qs['history']], original_actions)
        page = self.send({'kind': 'catalog_page', 'path': ['pending_base_task_ids'], 'offset': 0, 'count': 5})['response']
        self.assertEqual(page['payload'], ['z', 'a'])
        text = self.send({'kind': 'catalog_text', 'offset': 0, 'count': 300})['response']['payload']
        self.assertEqual(text, self.session.export_evidence()['full_catalog']['catalog_serialized_text'][:300])

    def test_legacy_check_or_apply_cannot_be_synthetic_original_actions(self):
        for action in ('check_delta', 'apply'):
            raw = {'action': action, 'session_id': self.session.context()['session_id'], 'anchors': self.session.context()['anchors']}
            with patch.object(module, 'compile_plan_delta', side_effect=AssertionError('must not compile')):
                self.assert_rejected(self.send({'kind': 'session_query', 'action': raw}), 'query_only')
        self.assertEqual(self.session.export_evidence()['query_session_evidence']['history'], [])

    def test_missing_create_seal_check_and_wrong_hashes_never_select(self):
        self.assert_rejected(self.send({'kind': 'apply', 'candidate_id': 'unknown', 'candidate_sha256': 'a' * 64}), 'unknown_candidate')
        self.assert_rejected(self.send({'kind': 'check_assembly', 'draft_id': 'none', 'sealed_state_sha256': 'a' * 64,
                                        'seal_action_sha256': 'a' * 64, 'delta_sha256': 'a' * 64}), 'unknown_draft')
        self.send({'kind': 'create_draft', 'draft_id': 'unsealed'})
        self.assert_rejected(self.send({'kind': 'check_assembly', 'draft_id': 'unsealed', 'sealed_state_sha256': 'a' * 64,
                                        'seal_action_sha256': 'a' * 64, 'delta_sha256': 'a' * 64}), 'unsealed')
        request = self.build()
        for key in ('sealed_state_sha256', 'seal_action_sha256', 'delta_sha256'):
            changed = deepcopy(request);changed[key] = '0' * 64
            self.assert_rejected(self.send(changed), 'assembly_binding')
        self.assertIsNone(self.session.export_evidence()['selection'])

    def test_invalid_delta_compiler_rejection_keeps_raw_evidence_and_no_candidate(self):
        invalid = deepcopy(self.delta);invalid['tasks']['keep']['ids'] = []
        request = self.build(delta=invalid, split=False)
        self.assert_rejected(self.send(request), 'partition')
        evidence = self.session.export_evidence()
        self.assertEqual(evidence['candidates'], [])
        self.assertEqual(evidence['history'][-1]['projection']['value'], request)
        self.assertIsNone(evidence['selection'])

    def test_bad_assembly_chunk_keeps_raw_action_and_state_unchanged(self):
        self.send({'kind': 'create_draft', 'draft_id': 'd'})
        before = self.session.export_evidence()['drafts']['d']['state_sha256']
        action = self.draft_action('d', 'chunk', sequence=7, chunk_id='x', set_fields=[], append_arrays=[])
        response = self.send({'kind': 'assembly_action', 'action': action})['response']
        self.assertEqual(response['assembly_result']['error']['code'], 'sequence')
        evidence = self.session.export_evidence()
        self.assertEqual(evidence['drafts']['d']['state_sha256'], before)
        self.assertEqual(evidence['history'][-1]['projection']['nested_action']['value'], action)

    def test_output_bytes_and_exact_projection_are_not_reserialized_as_original_action(self):
        envelope = self.envelope({'kind': 'create_draft', 'draft_id': 'd'}, memory='  exact\n中文  ')
        raw = json.dumps(envelope, ensure_ascii=False, indent=3).encode() + b'\n'
        self.send_raw(raw)
        row = self.session.export_evidence()['history'][0]
        self.assertEqual(b64decode(row['raw_output_base64']), raw)
        self.assertEqual(row['projection']['value'], envelope['request'])
        self.assertNotEqual(row['raw_output_sha256'], digest(envelope['request']))
        self.assertEqual(row['memory_after']['memory'], '  exact\n中文  ')

    def test_invalid_json_wrapper_context_and_memory_preserve_previous_valid_memory(self):
        self.send({'kind': 'catalog_text', 'offset': 0, 'count': 20}, memory='keep exactly')
        old = self.session.export_evidence()['current_memory']
        self.session.next_prompt();bad_json = b'{not-json'
        self.assert_rejected(self.send_raw(bad_json), 'json')
        for change in ('schema', 'anchors', 'memory_type', 'memory_size', 'extra'):
            envelope = self.envelope({'kind': 'read_candidates'}, memory='should not be used')
            if change == 'schema':envelope['schema'] = 'old'
            if change == 'anchors':envelope['anchors']['state_sha256'] = 'f' * 64
            if change == 'memory_type':envelope['memory'] = {'summary': 'forbidden'}
            if change == 'memory_size':envelope['memory'] = 'x' * 8191
            if change == 'extra':envelope['memory_source'] = 'forged'
            self.send_raw(self.raw(envelope))
            self.assertEqual(self.session.export_evidence()['current_memory'], old)
            prompt = self.session.next_prompt()
            self.assertEqual(prompt['body']['memory'], 'keep exactly')
            self.assertEqual(prompt['body']['memory_binding']['source'], old['source'])
        self.assertIn(bad_json, [b64decode(r['raw_output_base64']) for r in self.session.export_evidence()['history']])

    def test_valid_wrapper_rejected_action_memory_remains_model_authored(self):
        self.assert_rejected(self.send({'kind': 'invented'}, memory='my retained note'), 'request')
        prompt = self.session.next_prompt()
        self.assertEqual(prompt['body']['memory'], 'my retained note')
        self.assertEqual(prompt['body']['memory_binding']['source']['history_index'], 0)
        self.assertEqual(prompt['body']['feedback']['status'], 'rejected')

    def test_empty_memory_allowed_and_never_replaced_by_tool_summary(self):
        self.send({'kind': 'read_candidates'}, memory='')
        prompt = self.session.next_prompt()
        self.assertEqual(prompt['body']['memory'], '')
        self.assertEqual(prompt['body']['memory_binding']['memory_sha256'], digest(''))

    def test_stale_prompt_and_replayed_raw_output_rejected_even_with_new_call(self):
        raw = self.raw(self.envelope({'kind': 'create_draft', 'draft_id': 'd'}))
        self.send_raw(raw)
        self.session.next_prompt()
        self.assert_rejected(self.send_raw(raw), 'prompt_binding')
        self.assertEqual(len(self.session.export_evidence()['drafts']), 1)

    def test_call_reuse_and_index_order_do_not_rerun_compiler(self):
        request = self.build()
        raw = self.raw(self.envelope(request))
        with patch.object(module, 'compile_plan_delta', wraps=module.compile_plan_delta) as compiler:
            index = self.index;self.send_raw(raw)
            self.session.next_prompt()
            self.assert_rejected(self.send_raw(raw, call_id='call-' + str(index), index=index + 1), 'call_reuse')
            fresh = self.raw(self.envelope(request))
            self.assert_rejected(self.send_raw(fresh, call_id='fresh', index=0), 'call_reuse')
            self.assertEqual(compiler.call_count, 1)
        self.assertEqual(len(self.session.export_evidence()['candidates']), 1)

    def test_missing_prompt_and_bool_model_index_are_rejected_and_preserved(self):
        envelope = {'schema': module.RESPONSE_SCHEMA, **self.session.context(), 'prompt_body_sha256': 'a' * 64,
                    'memory': '', 'request': {'kind': 'read_candidates'}}
        self.assert_rejected(self.send_raw(self.raw(envelope)), 'prompt_binding')
        envelope = self.envelope({'kind': 'read_candidates'})
        self.assert_rejected(self.send_raw(self.raw(envelope), index=True), 'call_identity')
        self.assertEqual(len(self.session.export_evidence()['history']), 2)

    def test_candidate_hash_tampering_and_external_mutation_do_not_change_registry(self):
        candidate = self.checked()
        bad = self.candidate_request('apply', candidate);bad['candidate_sha256'] = 'b' * 64
        self.assert_rejected(self.send(bad), 'candidate_hash')
        exported = self.session.export_evidence();exported['candidates'][0]['candidate']['compiled']['plan']['tasks'].clear()
        self.assertEqual(len(self.session.export_evidence()['candidates'][0]['candidate']['compiled']['plan']['tasks']), 2)
        self.assertIsNone(self.session.export_evidence()['selection'])

    def test_once_selected_no_second_apply_or_new_prompt(self):
        candidate = self.checked()
        raw = self.raw(self.envelope(self.candidate_request('apply', candidate)))
        self.send_raw(raw)
        with self.assertRaises(Error) as caught:
            self.session.next_prompt()
        self.assertEqual(caught.exception.code, 'selected')
        self.assert_rejected(self.send_raw(raw), 'prompt_binding')
        self.assertEqual(self.session.export_evidence()['selection']['candidate_sha256'], candidate['candidate_sha256'])

    def test_oversized_feedback_is_archived_and_reachable_without_automatic_shrinking(self):
        self.base['tasks'][1]['large_unranked_field'] = 'x' * 130000
        self.session = self.new()
        result = self.send({'kind': 'session_query', 'action': {
            'action': 'read_base_tasks', 'session_id': self.session.context()['session_id'],
            'anchors': self.session.context()['anchors'], 'task_ids': ['z']}})
        self.assertEqual(result['response']['status'], 'query_result')
        self.assertEqual(result['feedback']['status'], 'feedback_size')
        diagnostic = result['feedback']
        self.assertFalse(diagnostic['full_original_feedback_included'])
        prompt = self.session.next_prompt()
        self.assertEqual(prompt['body']['feedback'], diagnostic)
        self.assertEqual(result['response'], self.session.export_evidence()['history'][0]['full_response'])
        request = {'kind': 'read_archive_feedback', 'history_index': 0, 'feedback_sha256': diagnostic['feedback_sha256'],
                   'path': [], 'format': 'text', 'offset': 0, 'count': 80}
        first = self.send(request)['response']
        request['offset'] = 80
        second = self.send(request)['response']
        self.assertEqual(first['payload'] + second['payload'], render(result['response'])[:160])
        request['feedback_sha256'] = '0' * 64
        self.assert_rejected(self.send(request), 'feedback_hash')

    def test_candidate_and_draft_path_slice_queries_preserve_original_order(self):
        candidate = self.checked()
        request = self.candidate_request('read_candidate', candidate, path=['compiled', 'plan', 'tasks'], format='page', offset=1, count=1)
        result = self.send(request)['response']
        self.assertEqual(result['payload'][0]['id'], 'a')
        draft = self.session.export_evidence()['drafts']['draft-1']
        request = {'kind': 'read_draft', 'draft_id': 'draft-1', 'state_sha256': draft['state_sha256'],
                   'path': ['sealed', 'delta', 'machine_orders'], 'format': 'page', 'offset': 0, 'count': 2}
        result = self.send(request)['response']
        self.assertEqual([item['machine'] for item in result['payload']], [2, 1])
        request['state_sha256'] = 'f' * 64
        self.assert_rejected(self.send(request), 'draft_hash')

    def test_actual_large_feedback_remains_completely_reconstructible_by_model_text_queries(self):
        self.base['tasks'][1]['large_unranked_field'] = 'x' * 130000
        self.session = self.new()
        result = self.send({'kind': 'session_query', 'action': {
            'action': 'read_base_tasks', 'session_id': self.session.context()['session_id'],
            'anchors': self.session.context()['anchors'], 'task_ids': ['z']}})
        self.assertGreater(len(render(result['response'])), 24000)
        self.assertEqual(result['feedback']['status'], 'feedback_size')
        expected = self.session.export_evidence()['history'][0]['full_response_serialized_text']
        pieces = []
        for offset in range(0, len(expected), 8000):
            response = self.send({'kind': 'read_archive_feedback', 'history_index': 0,
                                  'feedback_sha256': result['feedback']['feedback_sha256'],
                                  'path': [], 'format': 'text', 'offset': offset, 'count': 8000})['response']
            pieces.append(response['payload'])
        self.assertEqual(''.join(pieces), expected)
        self.assertEqual(json.loads(''.join(pieces)), result['response'])

    def test_forged_envelope_candidate_or_compiler_payload_is_not_an_input(self):
        candidate = self.checked()
        request = self.candidate_request('apply', candidate)
        request['candidate'] = {'compiled': {'plan': {'tasks': []}}}
        self.assert_rejected(self.send(request), 'request')
        self.assertIsNone(self.session.export_evidence()['selection'])

    def test_prompt_is_exactly_measured_and_overflow_archives_full_untrimmed_prompt(self):
        prompt = self.session.next_prompt()
        self.assertEqual(prompt['prompt_characters'], len(prompt['prompt']))
        header, payload = prompt['prompt'].split('\n', 1)
        self.assertEqual(header, 'PROMPT_BODY_SHA256=' + prompt['prompt_body_sha256'])
        self.assertEqual(module.hashlib.sha256(payload.encode()).hexdigest(), prompt['prompt_body_sha256'])
        self.assertEqual(module.hashlib.sha256(prompt['prompt'].encode()).hexdigest(), prompt['prompt_sha256'])
        self.assertEqual(self.session.next_prompt(), prompt)
        self.assertIn('Minimize priority-weighted integral', prompt['prompt'])
        self.assertIn('check_assembly', prompt['body']['response_contract']['request_exact_fields'])
        other = self.new()
        other._feedback = {'synthetic_boundary_padding': ''}
        measured = other.next_prompt()['prompt_characters']
        exact = self.new()
        exact._feedback = {'synthetic_boundary_padding': 'x' * (120000 - measured)}
        self.assertEqual(exact.next_prompt()['prompt_characters'], 120000)
        over = self.new()
        over._feedback = {'synthetic_boundary_padding': 'x' * (120001 - measured)}
        with self.assertRaises(Error) as caught:
            over.next_prompt()
        self.assertEqual(caught.exception.code, 'prompt_size')
        self.assertEqual(caught.exception.archive['prompt_characters'], 120001)
        self.assertEqual(over.export_evidence()['prompt_failures'][0]['prompt'], caught.exception.archive['prompt'])

    def test_only_latest_memory_and_current_feedback_enter_next_prompt(self):
        for text in ('old memory A', 'old memory B', 'latest exact C'):
            self.send({'kind': 'read_candidates'}, memory=text)
        prompt = self.session.next_prompt()
        self.assertEqual(prompt['body']['memory'], 'latest exact C')
        self.assertNotIn('old memory A', prompt['prompt'])
        self.assertNotIn('old memory B', prompt['prompt'])
        self.assertEqual(len(self.session.export_evidence()['history']), 3)

    def test_duplicate_json_keys_nonfinite_and_invalid_utf8_preserved(self):
        for raw in (b'{"schema":1,"schema":2}', b'{"x":NaN}', b'\xff', b'{"x":1e999}'):
            self.session.next_prompt()
            result = self.send_raw(raw)
            self.assertEqual(result['response']['status'], 'rejected')
            self.assertEqual(b64decode(self.session.export_evidence()['history'][-1]['raw_output_base64']), raw)
        self.assertIsNone(self.session.export_evidence()['current_memory'])

    def test_nonfinite_nested_request_does_not_break_history_hashing(self):
        envelope = self.envelope({'kind': 'read_candidates', 'invalid_number': 1.25})
        raw = self.raw(envelope).replace(b'1.25', b'1e999')
        self.assert_rejected(self.send_raw(raw), 'json')
        row = self.session.export_evidence()['history'][-1]
        self.assertIsNone(row['parsed_envelope'])
        self.assertEqual(b64decode(row['raw_output_base64']), raw)
        self.assertIsNone(row['memory_after'])

    def test_unexpected_compiler_exception_preserved_without_fallback(self):
        request = self.build()
        with patch.object(module, 'compile_plan_delta', side_effect=RuntimeError('injected pure check failure')):
            result = self.send(request)
        self.assert_rejected(result, 'unexpected_exception')
        self.assertEqual(self.session.export_evidence()['candidates'], [])
        self.assertIn('injected pure check failure', result['response']['error']['detail'])

    def test_export_replays_original_outputs_to_identical_candidates_history_and_selection(self):
        candidate = self.checked()
        self.send(self.candidate_request('read_candidate', candidate, path=['compiled', 'plan', 'tasks'], format='page', offset=0, count=1))
        self.send(self.candidate_request('apply', candidate))
        evidence = self.session.export_evidence()
        replay = self.new()
        for row in evidence['history']:
            prompt = replay.next_prompt()
            self.assertEqual(prompt['prompt_sha256'], row['issued_prompt_sha256'])
            result = replay.handle(b64decode(row['raw_output_base64']), call_id=row['call_id'], model_index=row['model_index'])
            self.assertEqual(result['record_sha256'], row['record_sha256'])
        self.assertEqual(replay.export_evidence(), evidence)
        self.assertFalse(evidence['assurance']['transport_authenticated'])

    def test_input_and_export_copies_do_not_change_session_and_new_state_changes_context(self):
        initial = self.session.context()
        self.base['reason'] = 'changed external source'
        self.assertEqual(self.session.context(), initial)
        newer = self.new()
        self.assertNotEqual(newer.context()['interaction_id'], initial['interaction_id'])
        old = self.envelope({'kind': 'read_candidates'})
        newer.next_prompt()
        result = newer.handle(self.raw(old), call_id='new-call', model_index=0)
        self.assertEqual(result['response']['error']['code'], 'stale_context')

    def test_full_feedback_above_old_cap_is_returned_without_queries_or_summary(self):
        self.base['tasks'][1]['large_unranked_field'] = 'x' * 50000
        self.session = self.new()
        result = self.send({'kind': 'session_query', 'action': {
            'action': 'read_base_tasks', 'session_id': self.session.context()['session_id'],
            'anchors': self.session.context()['anchors'], 'task_ids': ['z']}}, memory='exact new note')
        self.assertGreater(len(render(result['response'])), 24000)
        self.assertEqual(result['response'], result['feedback'])
        evidence = self.session.export_evidence()
        self.assertEqual(len(evidence['history']), 1)
        self.assertEqual(len(evidence['query_session_evidence']['history']), 1)
        receipt = evidence['history'][0]['feedback_admission']
        self.assertEqual(receipt['decision'], 'full_original_feedback')
        self.assertFalse(receipt['durably_archived'])
        self.assertNotIn('preview', receipt)
        prompt = self.session.next_prompt()
        self.assertEqual(prompt['body']['feedback'], result['response'])
        self.assertEqual(prompt['body']['memory'], 'exact new note')
        self.assertEqual(prompt['prompt_sha256'], receipt['full_candidate_measurement']['prompt_sha256'])
        self.assertEqual(prompt['prompt_body_sha256'], receipt['full_candidate_measurement']['prompt_body_sha256'])

    def test_frame_and_preview_are_readonly_and_do_not_issue_a_prompt(self):
        before = self.session.export_evidence()
        frame = self.session._frame(1)
        self.assertIsNone(frame['feedback'])
        receipt = module.feedback_layer.admit_feedback(module.TASK_TEXT, frame, {'status': 'query_result', 'payload': [3, 2, 1]}, history_index=0)
        self.assertTrue(receipt['ready'])
        self.assertEqual(self.session.export_evidence(), before)
        self.assertIsNone(self.session._pending_prompt)

    def test_rejected_memory_preview_uses_prior_legal_memory_and_no_action(self):
        self.send({'kind': 'read_candidates'}, memory='retain prior exact memory')
        before = self.session.export_evidence()
        result = self.send({'kind': 'create_draft', 'draft_id': 'must-not-exist'}, memory='x' * 9000)
        self.assert_rejected(result, 'memory_size')
        after = self.session.export_evidence()
        self.assertEqual(before['drafts'], after['drafts'])
        self.assertEqual(before['current_memory'], after['current_memory'])
        self.assertIsNone(after['history'][-1]['projection'])
        prompt = self.session.next_prompt()
        self.assertEqual(prompt['body']['memory'], 'retain prior exact memory')
        self.assertEqual(prompt['prompt_sha256'], after['history'][-1]['feedback_admission']['full_candidate_measurement']['prompt_sha256'])

    def test_terminal_apply_never_constructs_a_followup_admission(self):
        candidate = self.checked()
        raw = self.raw(self.envelope(self.candidate_request('apply', candidate)))
        with patch.object(module.feedback_layer, 'admit_feedback', side_effect=AssertionError('terminal preview forbidden')):
            result = self.send_raw(raw)
        self.assertEqual(result['response']['status'], 'selection_for_external_commit')
        receipt = self.session.export_evidence()['history'][-1]['feedback_admission']
        self.assertEqual(receipt['decision'], 'terminal_no_next_prompt')
        self.assertFalse(receipt['next_prompt_built'])

    def test_issuance_rechecks_current_context_instead_of_reusing_preview(self):
        self.send({'kind': 'read_candidates'}, memory='small')
        preview = self.session.export_evidence()['history'][-1]['feedback_admission']['full_candidate_measurement']['prompt_sha256']
        # A synthetic changed context cannot reuse the stored small preview.
        self.session._feedback = {'synthetic_changed_context': 'x' * 120000}
        with self.assertRaises(Error) as caught:
            self.session.next_prompt()
        self.assertEqual(caught.exception.code, 'prompt_size')
        self.assertNotEqual(caught.exception.archive['prompt_sha256'], preview)
        self.assertIsNone(self.session._pending_prompt)


    def test_handle_blocked_next_prompt_preserves_original_attempt_and_stops_issuance(self):
        raw = self.raw(self.envelope({'kind': 'read_candidates'}, memory='explicit original'))
        frame = self.session._frame
        def oversized_frame(index):
            value = frame(index)
            value['directory']['synthetic_capacity_probe'] = 'x' * 120000
            return value
        with patch.object(self.session, '_frame', side_effect=oversized_frame):
            result = self.send_raw(raw)
            row = self.session.export_evidence()['history'][-1]
            self.assertEqual(row['feedback_admission']['decision'], 'blocked_prompt_size')
            self.assertFalse(row['feedback_admission']['ready'])
            self.assertEqual(b64decode(row['raw_output_base64']), raw)
            self.assertEqual(row['full_response'], result['response'])
            self.assertFalse(result['feedback']['full_original_feedback_included'])
            self.assertEqual(len(self.session.export_evidence()['history']), 1)
            with self.assertRaises(Error):self.session.next_prompt()
            self.assertIsNone(self.session._pending_prompt)
            self.assertEqual(self.session.export_evidence()['history'][-1], row)
            self.assertIsNone(self.session.export_evidence()['selection'])


    def test_resource_admission_keeps_raw_bytes_without_eviction_or_execution(self):
        raw = self.raw(self.envelope({'kind': 'read_candidates'}))
        with patch.object(module, 'MAX_OUTPUT_BYTES', len(raw) - 1):
            with self.assertRaises(AdmissionError) as caught:
                self.send_raw(raw)
        self.assertIs(caught.exception.raw_output, raw)
        self.assertEqual(self.session.export_evidence()['history'], [])
        self.send_raw(raw)
        before = self.session.export_evidence()
        with patch.object(module, 'MAX_ATTEMPTS', 1):
            with self.assertRaises(AdmissionError):
                self.send_raw(raw)
        self.assertEqual(self.session.export_evidence(), before)


if __name__ == '__main__':
    unittest.main()
