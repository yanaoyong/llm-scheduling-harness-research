"""Exact model-directed filtering and bounded, recoverable public results."""
from pathlib import Path
import tempfile
import unittest

from src.smt_fullfab.harness.contracts import ROOT, HarnessError, default_config, encode, sha_bytes, strict_json
from src.smt_fullfab.harness.facts import FactReader, build_facts
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.transport import prompt, response_schema
from src.smt_fullfab.harness.presentation import unpack
from src.smt_fullfab.harness.experiment import sealed_prior


class BoundedFactTests(unittest.TestCase):
    def test_T11_filtered_pages_exact_complete_source_order_and_cursor_binding(self):
        operations = [{'operation_id': 'op-' + str(i), 'family': 'F' if i % 2 else 'G',
                       'eligible_machines': [2, 3] if i % 4 else [4], 'conditional': i % 3 == 0,
                       **({'nullable': None} if i % 5 else {})} for i in range(1103)]
        facts = build_facts({'machines': [], 'operations': operations}, {'tasks': [], 'holds': []})
        reader = FactReader('owned-context', facts)
        where = [{'field': 'eligible_machines', 'op': 'contains', 'value': 2}, {'field': 'conditional', 'op': 'eq', 'value': False}]
        expected = [v for v in operations if 2 in v['eligible_machines'] and not v['conditional']]
        cursor, found, saved = None, [], None
        while True:
            result = reader.read({'kind': 'operations', 'where': where, 'cursor': cursor, 'count': 73,
                                  'fields': ['operation_id', 'nullable', 'absent']})
            self.assertEqual(result['catalog_total'], len(operations))
            self.assertEqual(result['matching_total'], len(expected))
            for row in result['entities']:
                self.assertIn('absent', row['absent_fields'])
                self.assertEqual('nullable' in row['absent_fields'], row['source_index'] % 5 == 0)
                found.append(row['value']['operation_id'])
            cursor = result['next_cursor']
            if cursor and saved is None: saved = cursor
            if cursor is None: break
        self.assertEqual(found, [v['operation_id'] for v in expected])
        with self.assertRaisesRegex(HarnessError, 'stale_cursor'):
            reader.read({'kind': 'operations', 'where': where[:1], 'cursor': saved, 'count': 1})
        with self.assertRaisesRegex(HarnessError, 'stale_cursor'):
            FactReader('new-context', facts).read({'kind': 'operations', 'where': where, 'cursor': saved, 'count': 1})
        result = reader.read({'kind': 'operations', 'where': [{'field': 'nullable', 'op': 'eq', 'value': None}], 'cursor': None, 'count': 512})
        self.assertTrue(all('nullable' in row['value'] for row in result['entities']))
        result = reader.read({'kind': 'operations', 'where': [{'field': 'conditional', 'op': 'eq', 'value': 0}], 'cursor': None, 'count': 1})
        self.assertEqual(result['matching_total'], 0)  # false is not numeric zero
        for predicate in ({'field': 'private_rng', 'op': 'eq', 'value': 1}, {'field': 'family', 'op': 'rank_best', 'value': 'F'}):
            with self.assertRaisesRegex(HarnessError, 'query_filter'):
                reader.read({'kind': 'operations', 'where': [predicate], 'cursor': None, 'count': 1})
        actions = response_schema('B', comparison_context_refs=[])['properties']['action']['anyOf']
        queries = next(a for a in actions if a['properties']['tool']['enum'] == ['read_entities'])['properties']['queries']['items']['anyOf']
        self.assertTrue(any('where' in q['properties'] for q in queries))

    def runtime(self, chars=120000):
        root = Path(tempfile.mkdtemp(prefix='offline-bounded-facts-'))
        config = default_config(seconds=60); config['limits']['context_chars'] = chars
        return Runtime.start_new(root / 'run', config, experiment_id='offline-bounded-public-results')

    def publish_read(self, runtime, value):
        with runtime.store.transaction(): reference = runtime._publish(value, 'offline-test-public-fixture')
        action = {'tool': 'read_artifact', 'artifact_ref': reference, 'path': [], 'format': 'value', 'offset': 0, 'count': 0}
        return runtime.record_output(action)

    def frame(self, runtime):
        text = prompt(runtime)
        return unpack(strict_json(text[text.index('\n{') + 1:]))

    def test_T12_large_result_preview_continuation_reads_exact_original_slice(self):
        r = self.runtime()
        try:
            rows = [{'id': i, 'value': str(i) * 500} for i in range(1000)]
            self.publish_read(r, {'rows': rows, 'description': 'offline synthetic fixture'})
            first = self.frame(r)['last_tool_feedback']
            self.assertFalse(first['preview_complete'])
            self.assertLess(len(encode(first)), 16000)
            section = next(s for s in first['sections'] if s['path'] == ['value', 'rows'])
            self.assertEqual(section['shown_values'], rows[:section['shown_count']])
            action = section['next_read']
            result = r.record_output(action)
            self.assertEqual(result['value'], rows[action['offset']:action['offset'] + action['count']])
            self.assertLess(len(encode(result)), 40000)
            frame = self.frame(r)
            self.assertEqual(frame['last_tool_feedback']['value'], result['value'])
            self.assertEqual(r.store.rows('commits'), [])
            path = r.store.path; r.close(); r = Runtime.resume_run(path)
            self.assertEqual(self.frame(r)['last_tool_feedback'], frame['last_tool_feedback'])
        finally: r.close()

    def test_T14_prior_small_results_stay_visible_with_large_feedback_and_prompt_cap(self):
        r = self.runtime(chars=50000)
        try:
            for i in range(7): self.publish_read(r, {'index': i, 'payload': str(i) * 4000})
            self.publish_read(r, {'rows': [{'index': i, 'payload': 'x' * 500} for i in range(1000)]})
            frame = self.frame(r)
            self.assertTrue(frame['interaction_history']['entries'])
            self.assertTrue(any('result' in entry and entry['result']['value']['index'] == 6 for entry in frame['interaction_history']['entries']))
            self.assertEqual(frame['last_tool_feedback']['value']['rows'], [{'index': i, 'payload': 'x' * 500} for i in range(1000)])
            text = prompt(r)
            self.assertLessEqual(len(text), r.config['limits']['context_chars'])
            self.assertNotIn('rng_state', text)
            self.assertEqual(frame['interaction_history']['count'], 8)
        finally: r.close()

    def test_T23_all_three_failed_groups_remain_in_cumulative_costs(self):
        path = ROOT / 'artifacts/harness_v1_3_offline/prior_cost_evidence.json'
        usage, starts, ids = sealed_prior({'prior_cost_evidence': {'path': str(path), 'sha256': sha_bytes(path.read_bytes())}})
        self.assertEqual((usage['micro']['attempts'], usage['micro']['tokens'], len(ids), starts), (34, 1355445, 5, 0))
        self.assertEqual(usage['micro']['unknown_usage'], 0)


if __name__ == '__main__': unittest.main()
