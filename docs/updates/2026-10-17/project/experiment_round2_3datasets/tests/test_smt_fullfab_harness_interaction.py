"""Regression tests for the retained P5 read loop; no real inference."""
import json
import base64
from pathlib import Path
import tempfile
import unittest

from src.smt_fullfab.harness.contracts import default_config, encode, HarnessError
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.transport import prompt
from tests.test_smt_fullfab_harness import wait_delta, propose, apply


class InteractionTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp(prefix="offline-p5-interaction-")) / "run"
        cfg = default_config(seconds=60)
        cfg['period_seconds'] = 1
        self.r = Runtime.start_new(self.path, cfg, experiment_id='offline-read-loop-regression')

    def tearDown(self):
        self.r.close()

    def restart(self):
        self.r.close()
        self.r = Runtime.resume_run(self.path)

    def context_action(self):
        return {'tool': 'get_context', 'context_ref': self.r.head['context_ref']}

    def frame(self):
        text = prompt(self.r)
        return json.loads(text[text.index('\n{') + 1:])

    def public(self, ref):
        row = self.r.store.read('public', ref)
        self.assertEqual(row['run_id'], self.r.manifest['run_id'])
        return self.r.store.get(row['object_ref'])

    def test_prior_queries_and_exact_results_survive_next_query_and_resume(self):
        cursor = self.r.context()['catalogs']['operations']['first_cursor']
        actions, results = [], []
        for _ in range(2):
            action = {'tool': 'read_entities', 'context_ref': self.r.head['context_ref'],
                      'queries': [{'kind': 'operations', 'cursor': cursor, 'count': 1}]}
            result = self.r.record_output(action)
            actions.append(action); results.append(result)
            cursor = result['results'][0]['next_cursor']
        frame = self.frame()
        history = self.public(frame['interaction_history']['full_history_ref'])
        self.assertEqual(len(history), 2)
        for entry, action, result in zip(history, actions, results):
            self.assertEqual(json.loads(self.public(entry['raw_output_ref'])), action)
            self.assertEqual(self.public(entry['result_ref']), result)
        self.assertNotIn('private_state', encode(frame).decode())
        self.restart()
        again = self.frame()
        self.assertEqual(self.public(again['interaction_history']['full_history_ref']), history)

    def test_identical_context_reads_warn_then_stop_across_resume(self):
        action = self.context_action()
        self.r.record_output(action)
        second = self.r.record_output(action)
        self.assertEqual(second['protocol_progress']['repeated_reads'], 2)
        self.assertIsNotNone(self.public(second['protocol_progress']['first_result_ref']))
        attempt = self.r.store.rows('attempts')[-1][0]
        self.assertEqual(self.r.process(attempt), second)  # replay is not another read
        self.restart()
        third = self.r.record_output(action)
        self.assertEqual(third['protocol_progress']['repeated_reads'], 3)
        self.assertEqual(self.r.head['stop_reason'], 'repeated_identical_read')
        self.assertEqual(len(self.r.store.rows('commits')), 0)
        with self.assertRaisesRegex(HarnessError, 'stopped'):
            self.r.check_admission()
        self.assertEqual(self.r.usage()['offline_outputs'], 3)

    def test_invalid_utf8_output_is_recoverable_without_replacement_characters(self):
        raw = b'\xffnot-valid-json'
        result = self.r.record_output(raw)
        self.assertEqual(result['status'], 'rejected')
        entry = self.frame()['interaction_history']['entries'][0]
        self.assertEqual(entry['raw_output_encoding'], 'base64')
        self.assertEqual(base64.b64decode(self.public(entry['raw_output_ref'])), raw)

    def test_distinct_pages_and_new_context_do_not_count_as_repeated_read(self):
        cursor = self.r.context()['catalogs']['operations']['first_cursor']
        for _ in range(5):
            result = self.r.record_output({'tool': 'read_entities', 'context_ref': self.r.head['context_ref'],
                                          'queries': [{'kind': 'operations', 'cursor': cursor, 'count': 1}]})
            self.assertEqual(result['status'], 'ok')
            cursor = result['results'][0]['next_cursor']
        self.assertNotEqual(self.r.head['phase'], 'STOPPED')
        self.r.record_output(self.context_action())
        self.r.record_output(self.context_action())
        candidate = propose(self.r, wait_delta(self.r))
        apply(self.r, candidate['candidate_ref'])
        self.r.advance()
        self.r.observe()
        result = self.r.record_output(self.context_action())
        self.assertEqual(result['protocol_progress']['repeated_reads'], 1)
        self.assertNotEqual(self.r.head['phase'], 'STOPPED')


if __name__ == '__main__':
    unittest.main()
