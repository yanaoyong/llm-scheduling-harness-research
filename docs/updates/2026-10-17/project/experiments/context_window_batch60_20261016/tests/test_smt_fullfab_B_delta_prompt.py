"""Small synthetic protocol tests. No real data, transport, environment or CP."""
from base64 import b64decode
from copy import deepcopy
import ast
import json
from pathlib import Path
import unittest

from src.smt_fullfab import B_delta_prompt as protocol
from src.smt_fullfab.B_delta_prompt import (CatalogPager, ProtocolError, RESPONSE_SCHEMA, PROMPT_CHARACTER_LIMIT,
    MEMORY_SERIALIZED_CHARACTER_LIMIT, CATALOG_REPLY_CHARACTER_LIMIT, build_prompt, digest, render, validate_response)
from src.smt_fullfab.delta_session import DeltaSession
from tests.test_smt_fullfab_delta_session import SOURCE, fixture


class PromptProtocolTests(unittest.TestCase):
    def setUp(self):
        self.base, self.problem, self.state, self.paging, self.delta = fixture()
        self.catalog = DeltaSession(self.base, self.problem, self.state, source_sha256=SOURCE, paging=self.paging).describe()
        self.pager = CatalogPager(self.catalog)

    def envelope(self, *, memory='', request=None):
        return {'schema': RESPONSE_SCHEMA, **self.pager.context(), 'memory': memory,
                'request': request or {'kind': 'catalog_page', 'path': ['operation_ids'], 'offset': 0, 'count': 1}}

    def validate(self, envelope):
        return validate_response(json.dumps(envelope, ensure_ascii=False, indent=2).encode(), pager=self.pager)

    def memory(self, text=''):
        return self.validate(self.envelope(memory=text))['memory_record']

    def rejected(self, envelope, code):
        raw = json.dumps(envelope, ensure_ascii=False).encode()
        with self.assertRaises(ProtocolError) as error:validate_response(raw, pager=self.pager)
        self.assertEqual(error.exception.code, code)
        self.assertEqual(b64decode(error.exception.archive['raw_output_base64']), raw)

    def test_first_directory_omits_id_payloads_but_complete_catalog_is_archivable(self):
        result = build_prompt(pager=self.pager, turn_index=0, feedback=None)
        directory = result['archive']['body']['directory']
        self.assertEqual(directory['counts']['operation_ids'], 4)
        self.assertEqual([row['key'] for row in directory['root_fields']], list(self.catalog))
        for ids in ('operation_ids', 'base_task_ids', 'pending_base_task_ids', 'base_hold_refs'):
            self.assertNotIn(ids, directory)
        self.assertNotIn('"op-z"', result['prompt'])
        self.assertNotIn('"lot-z"', result['prompt'])
        self.assertEqual(result['archive']['full_catalog']['catalog'], self.catalog)
        self.assertFalse(result['model_called']);self.assertFalse(result['budget_reserved'])
        self.assertEqual(result['prompt_characters'], len(result['prompt']))

    def test_catalog_array_pages_preserve_all_ids_original_order_and_exact_indices(self):
        query = {'kind': 'catalog_page', 'path': ['operation_ids'], 'offset': 0, 'count': 2}
        first = self.pager.query(query);query['offset'] = first['next_offset'];second = self.pager.query(query)
        self.assertEqual(first['payload'] + second['payload'], self.catalog['operation_ids'])
        self.assertEqual(first['payload'], ['op-z', 'op-done'])
        self.assertIsNone(second['next_offset'])
        query['offset'] = 4
        self.assertEqual(self.pager.query(query)['payload'], [])

    def test_object_directories_string_chunks_and_scalar_values_are_complete(self):
        top = self.pager.query({'kind': 'catalog_page', 'path': [], 'offset': 0, 'count': len(self.catalog)})
        self.assertEqual([item['key'] for item in top['payload']], list(self.catalog))
        text = self.catalog['query_order']
        left = self.pager.query({'kind': 'catalog_page', 'path': ['query_order'], 'offset': 0, 'count': 11})
        right = self.pager.query({'kind': 'catalog_page', 'path': ['query_order'], 'offset': 11, 'count': len(text)})
        self.assertEqual(left['payload'] + right['payload'], text)
        scalar = self.pager.query({'kind': 'catalog_page', 'path': ['model_attribution_certified'], 'offset': 0, 'count': 1})
        self.assertIs(scalar['payload'], False)

    def test_nested_metadata_unknown_fields_and_null_are_reachable_without_ranking(self):
        catalog = deepcopy(self.catalog)
        catalog['base_plan_header']['unknown'] = {'z': [None, '中文', {'b': 2, 'a': 1}], 'a': 'keep'}
        pager = CatalogPager(catalog)
        query = {'kind': 'catalog_page', 'path': ['base_plan_header', 'unknown', 'z'], 'offset': 0, 'count': 3}
        response = pager.query(query)
        self.assertEqual(response['payload'], [None, '中文', {'b': 2, 'a': 1}])
        self.assertEqual(list(response['payload'][2]), ['b', 'a'])

    def test_catalog_text_chunks_exactly_reconstruct_every_original_field(self):
        pieces = [];offset = 0
        while offset is not None:
            reply = self.pager.query({'kind': 'catalog_text', 'offset': offset, 'count': 137})
            pieces.append(reply['payload']);offset = reply['next_offset']
        joined = ''.join(pieces)
        self.assertEqual(joined, self.pager.archive_catalog()['catalog_serialized_text'])
        self.assertEqual(json.loads(joined), self.catalog)
        self.assertEqual(protocol.sha_bytes(joined.encode()), self.pager.directory()['catalog_text_sha256'])

    def test_query_size_error_retains_full_original_response_and_never_shortens_slice(self):
        catalog = deepcopy(self.catalog);catalog['base_plan_header']['large'] = 'x' * CATALOG_REPLY_CHARACTER_LIMIT
        pager = CatalogPager(catalog)
        query = {'kind': 'catalog_page', 'path': ['base_plan_header', 'large'], 'offset': 0, 'count': CATALOG_REPLY_CHARACTER_LIMIT}
        with self.assertRaises(ProtocolError) as error:pager.query(query)
        self.assertEqual(error.exception.code, 'query_size')
        self.assertEqual(error.exception.archive['query'], query)
        self.assertEqual(error.exception.archive['full_original_response']['payload'], catalog['base_plan_header']['large'])
        smaller = {**query, 'count': 10}
        self.assertEqual(pager.query(smaller)['payload'], 'x' * 10)

    def test_indivisible_large_object_key_has_exact_neutral_text_fallback(self):
        catalog = deepcopy(self.catalog);catalog['base_plan_header']['K' * CATALOG_REPLY_CHARACTER_LIMIT] = 'value'
        pager = CatalogPager(catalog)
        with self.assertRaises(ProtocolError) as error:
            pager.query({'kind': 'catalog_page', 'path': ['base_plan_header'], 'offset': 0, 'count': 99})
        self.assertEqual(error.exception.code, 'query_size')
        parts = [];offset = 0
        while offset is not None:
            page = pager.query({'kind': 'catalog_text', 'offset': offset, 'count': 2000})
            parts.append(page['payload']);offset = page['next_offset']
        self.assertEqual(json.loads(''.join(parts)), catalog)

    def test_invalid_catalog_queries_do_not_coerce_types_or_choose_alternatives(self):
        invalid = [
            {'kind': 'catalog_page', 'path': ['missing'], 'offset': 0, 'count': 1},
            {'kind': 'catalog_page', 'path': ['operation_ids', True], 'offset': 0, 'count': 1},
            {'kind': 'catalog_page', 'path': ['operation_ids', '0'], 'offset': 0, 'count': 1},
            {'kind': 'catalog_text', 'offset': True, 'count': 1},
            {'kind': 'catalog_text', 'offset': 0, 'count': 1.0},
            {'kind': 'catalog_text', 'offset': 0, 'count': 0},
            {'kind': 'catalog_text', 'offset': -1, 'count': 1},
            {'kind': 'catalog_page', 'path': ['model_attribution_certified'], 'offset': 0, 'count': 2},
            {'kind': 'catalog_page', 'path': ['operation_ids'], 'offset': 99, 'count': 1},
            {'kind': 'catalog_page', 'path': ['operation_ids'], 'offset': 0, 'count': 1, 'sort_by': 'priority'},
        ]
        before = self.pager.archive_catalog()
        for query in invalid:
            with self.subTest(query=query), self.assertRaises(ProtocolError):self.pager.query(query)
        self.assertEqual(self.pager.archive_catalog(), before)

    def test_model_memory_is_preserved_exactly_including_spaces_newlines_unicode_and_empty(self):
        for memory in ('', '  我自己记下：\n\tkeep z, revisit a.  \u200b'):
            with self.subTest(memory=memory):
                validated = self.validate(self.envelope(memory=memory))
                feedback = self.pager.query(validated['request'])
                built = build_prompt(pager=self.pager, turn_index=1, memory_record=validated['memory_record'], feedback=feedback)
                self.assertEqual(built['archive']['body']['memory'], memory)
                decoded = json.loads(built['prompt'][len(protocol.INSTRUCTION):])
                self.assertEqual(decoded['memory'], memory)
                self.assertEqual(decoded['feedback'], feedback)

    def test_memory_limit_uses_exact_serialized_characters_not_python_string_length(self):
        exact = 'x' * (MEMORY_SERIALIZED_CHARACTER_LIMIT - 2)
        self.assertEqual(self.validate(self.envelope(memory=exact))['memory_serialized_characters'], MEMORY_SERIALIZED_CHARACTER_LIMIT)
        self.rejected(self.envelope(memory=exact + 'x'), 'memory_size')
        escaped = '中' * (MEMORY_SERIALIZED_CHARACTER_LIMIT // 6 + 1)
        self.assertLess(len(escaped), MEMORY_SERIALIZED_CHARACTER_LIMIT)
        self.rejected(self.envelope(memory=escaped), 'memory_size')
        self.assertEqual(self.validate(self.envelope(memory='\n"'))['memory_serialized_characters'], len(render('\n"')))

    def test_nonstring_or_stale_memory_response_is_rejected_with_raw_output_preserved(self):
        for value in (None, [], {}, 0, True):self.rejected(self.envelope(memory=value), 'memory')
        for field in ('session_id', 'catalog_sha256'):
            invalid = self.envelope();invalid[field] = 'old'
            self.rejected(invalid, 'stale_context')
        for key in self.pager.context()['anchors']:
            invalid = self.envelope();invalid['anchors'][key] = 'b' * 64
            self.rejected(invalid, 'stale_context')

    def test_response_projected_action_is_exact_and_bound_to_original_wrapper(self):
        action = {'action': 'check_delta', 'session_id': self.catalog['session_id'], 'anchors': self.catalog['anchors'], 'delta': self.delta}
        envelope = self.envelope(memory='I choose this exact delta.', request={'kind': 'session_action', 'action': action})
        raw = json.dumps(envelope, ensure_ascii=False, indent=3).encode()
        validated = validate_response(raw, pager=self.pager)
        projection = validated['session_action_projection']
        self.assertEqual(projection['action'], action)
        self.assertEqual(projection['action_sha256'], digest(action))
        self.assertEqual(projection['raw_output_sha256'], protocol.sha_bytes(raw))
        self.assertEqual(projection['envelope_sha256'], digest(envelope))
        self.assertEqual(projection['pointer'], '/request/action')
        self.assertFalse(validated['action_executed'])
        self.assertFalse(validated['v1_durable_raw_output_equals_action_compatible'])
        self.assertNotEqual(json.loads(raw), action)
        self.assertEqual(b64decode(validated['archive']['raw_output_base64']), raw)

    def test_wrapper_does_not_fill_missing_action_context_or_allow_extra_action_fields(self):
        action = {'action': 'read_candidates', 'session_id': self.catalog['session_id'], 'anchors': self.catalog['anchors']}
        for field in ('session_id', 'anchors'):
            missing = deepcopy(action);missing.pop(field)
            self.rejected(self.envelope(request={'kind': 'session_action', 'action': missing}), 'action')
        wrong = deepcopy(action);wrong['anchors']['state_sha256'] = 'b' * 64
        self.rejected(self.envelope(request={'kind': 'session_action', 'action': wrong}), 'stale_context')
        extra = deepcopy(action);extra['default_apply_latest'] = True
        self.rejected(self.envelope(request={'kind': 'session_action', 'action': extra}), 'action')
        wrong = deepcopy(action);wrong['action'] = []
        self.rejected(self.envelope(request={'kind': 'session_action', 'action': wrong}), 'action')

    def test_catalog_query_is_not_projected_or_executed_as_a_session_action(self):
        result = self.validate(self.envelope())
        self.assertIsNone(result['session_action_projection'])
        self.assertFalse(result['action_executed'])
        self.assertEqual(result['request'], self.envelope()['request'])
        self.assertNotIn('payload', result)

    def test_duplicate_keys_non_json_and_unknown_wrapper_fields_are_rejected(self):
        raw = json.dumps(self.envelope()).encode()
        duplicate = raw.replace(b'"memory": ""', b'"memory": "", "memory": "different"')
        for invalid, code in ((duplicate, 'duplicate_key'), (b'{broken', 'json'), (b'\xff', 'json'), (raw.replace(b'"memory": ""', b'"memory": NaN'), 'json')):
            with self.subTest(code=code), self.assertRaises(ProtocolError) as error:validate_response(invalid, pager=self.pager)
            self.assertEqual(error.exception.code, code)
            self.assertEqual(b64decode(error.exception.archive['raw_output_base64']), invalid)
        extra = self.envelope();extra['auto_apply'] = True;self.rejected(extra, 'schema')

    def test_initial_memory_reset_requires_explicit_turn_zero_and_is_not_a_later_default(self):
        with self.assertRaises(ProtocolError):build_prompt(pager=self.pager, turn_index=1, feedback=None)
        with self.assertRaises(ProtocolError):build_prompt(pager=self.pager, turn_index=True, feedback=None)
        with self.assertRaises(ProtocolError):build_prompt(pager=self.pager, turn_index=0, memory_record=self.memory('remember'), feedback=None)
        self.assertEqual(build_prompt(pager=self.pager, turn_index=0, feedback=None)['archive']['body']['memory'], '')

    def test_builder_rejects_changed_or_stale_memory_record_without_tool_rewriting(self):
        record = self.memory('model authored')
        changed = deepcopy(record);changed['memory'] = 'tool summary'
        with self.assertRaisesRegex(ProtocolError, 'memory_record'):
            build_prompt(pager=self.pager, turn_index=1, memory_record=changed, feedback=None)
        stale = deepcopy(record);stale['anchors']['problem_sha256'] = 'b' * 64
        with self.assertRaisesRegex(ProtocolError, 'stale_context'):
            build_prompt(pager=self.pager, turn_index=1, memory_record=stale, feedback=None)
        self.assertEqual(record['memory'], 'model authored')

    def test_final_prompt_exact_limit_passes_and_one_more_character_fails_without_truncation(self):
        memory = self.memory('')
        original = build_prompt(pager=self.pager, turn_index=1, memory_record=memory, feedback={'payload': ''})
        padding = 'x' * (PROMPT_CHARACTER_LIMIT - original['prompt_characters'])
        feedback = {'payload': padding}
        exact = build_prompt(pager=self.pager, turn_index=1, memory_record=memory, feedback=feedback)
        self.assertEqual(len(exact['prompt']), PROMPT_CHARACTER_LIMIT)
        oversized = {'payload': padding + 'x'}
        with self.assertRaises(ProtocolError) as error:
            build_prompt(pager=self.pager, turn_index=1, memory_record=memory, feedback=oversized)
        self.assertEqual(error.exception.code, 'prompt_size')
        self.assertEqual(error.exception.archive['prompt_characters'], PROMPT_CHARACTER_LIMIT + 1)
        self.assertEqual(error.exception.archive['full_feedback'], oversized)
        self.assertEqual(error.exception.archive['feedback_sha256'], digest(oversized))

    def test_prompt_limit_counts_actual_quote_backslash_and_unicode_expansion(self):
        memory = self.memory('')
        ascii_prompt = build_prompt(pager=self.pager, turn_index=1, memory_record=memory, feedback={'text': 'abc'})
        escaped_prompt = build_prompt(pager=self.pager, turn_index=1, memory_record=memory, feedback={'text': '中"\\'})
        self.assertEqual(escaped_prompt['prompt_characters'] - ascii_prompt['prompt_characters'], len(render('中"\\')) - len(render('abc')))
        self.assertEqual(escaped_prompt['prompt_characters'], len(escaped_prompt['prompt']))

    def test_full_feedback_request_output_and_catalog_are_available_for_external_archiving(self):
        result = self.validate(self.envelope(memory='I will query page 1 next.'))
        feedback = self.pager.query(result['request'])
        built = build_prompt(pager=self.pager, turn_index=1, memory_record=result['memory_record'], feedback=feedback)
        self.assertEqual(built['archive']['full_catalog']['catalog'], self.catalog)
        self.assertEqual(built['archive']['raw_prompt'], built['prompt'])
        self.assertEqual(built['archive']['full_feedback'], feedback)
        self.assertEqual(result['archive']['parsed_envelope']['memory'], 'I will query page 1 next.')
        self.assertNotIn('OWN_HISTORY', built['archive']['body'])
        self.assertFalse(built['physical_commit_performed'])

    def test_catalog_inputs_and_returned_query_archive_are_detached(self):
        expected = self.pager.archive_catalog()
        self.catalog['operation_ids'].clear()
        directory = self.pager.directory();directory['anchors'].clear()
        reply = self.pager.query({'kind': 'catalog_page', 'path': ['operation_ids'], 'offset': 0, 'count': 4})
        reply['payload'].clear()
        self.assertEqual(self.pager.archive_catalog(), expected)

    def test_no_runtime_or_planner_dependencies(self):
        parsed = ast.parse(Path(protocol.__file__).read_text())
        imports = []
        for node in ast.walk(parsed):
            if isinstance(node, ast.Import):imports.extend(n.name for n in node.names)
            elif isinstance(node, ast.ImportFrom):imports.append(node.module)
        self.assertEqual(set(imports), {'base64', 'copy', 'hashlib', 'json', 'math'})


if __name__ == '__main__':unittest.main()
