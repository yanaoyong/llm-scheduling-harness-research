"""Hand-calculated positive cases and independent one-constraint mutations."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from src.fjsp.problem import FJSParseError, parse_fjs
from src.fjsp.validator import validate

ROOT = Path(__file__).resolve().parents[1]
SMALL_TEXT = '2 2\n2 2 0 3 1 5 1 1 2\n2 1 1 2 1 0 4\n'
VALID = {'operations': [
    {'id': 'j0o0', 'machine': 0, 'start': 0, 'end': 3},
    {'id': 'j0o1', 'machine': 1, 'start': 3, 'end': 5},
    {'id': 'j1o0', 'machine': 1, 'start': 0, 'end': 2},
    {'id': 'j1o1', 'machine': 0, 'start': 3, 'end': 7},
]}


class Fixture(unittest.TestCase):
    def setUp(self):
        (ROOT / 'data/raw/fjsp').mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'data/raw/fjsp')
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'hand.txt'
        self.source.write_text(SMALL_TEXT)
        self.problem = parse_fjs(self.source, instance_id='hand', family='manual')

    def parse_text(self, text):
        self.source.write_text(text)
        return parse_fjs(self.source)


class ParserTests(Fixture):
    def test_exact_hand_parse(self):
        self.assertEqual(self.problem['machines'], [0, 1])
        self.assertEqual(self.problem['jobs'][0]['operations'][0]['alternatives'], [{'machine': 0, 'duration': 3}, {'machine': 1, 'duration': 5}])
        self.assertEqual(self.problem['jobs'][1]['operations'][1]['id'], 'j1o1')
        self.assertEqual(set(self.problem['source']), {'format', 'sha256'})

    def test_blank_lines_are_whitespace_only(self):
        self.assertEqual(self.parse_text('\n' + SMALL_TEXT + '\n')['jobs'], self.problem['jobs'])

    def test_empty_source_rejected(self):
        with self.assertRaises(FJSParseError): self.parse_text('')

    def test_zero_counts_rejected(self):
        for text in ['0 2\n', '1 0\n1 1 0 3\n', '1 2\n0\n']:
            with self.subTest(text=text), self.assertRaises(FJSParseError): self.parse_text(text)

    def test_wrong_dialect_header_rejected(self):
        with self.assertRaises(FJSParseError): self.parse_text('2 2 1.5\n' + SMALL_TEXT.split('\n', 1)[1])

    def test_one_based_boundary_rejected(self):
        with self.assertRaises(FJSParseError): self.parse_text('1 2\n1 1 2 3\n')

    def test_missing_or_extra_rows_rejected(self):
        for text in ['2 2\n1 1 0 3\n', '1 2\n1 1 0 3\n1 1 1 2\n']:
            with self.subTest(text=text), self.assertRaises(FJSParseError): self.parse_text(text)

    def test_truncated_and_unconsumed_tokens_rejected(self):
        for text in ['1 2\n2 1 0 3\n', '1 2\n1 2 0 3\n', '1 2\n1 1 0 3 88\n']:
            with self.subTest(text=text), self.assertRaises(FJSParseError): self.parse_text(text)

    def test_empty_or_excess_alternatives_rejected(self):
        for text in ['1 2\n1 0\n', '1 2\n1 3 0 1 1 1 0 1\n']:
            with self.subTest(text=text), self.assertRaises(FJSParseError): self.parse_text(text)

    def test_duplicate_machine_rejected(self):
        with self.assertRaises(FJSParseError): self.parse_text('1 2\n1 2 0 3 0 4\n')

    def test_nonpositive_duration_rejected(self):
        for duration in ['0', '-1']:
            with self.subTest(duration=duration), self.assertRaises(FJSParseError): self.parse_text(f'1 2\n1 1 0 {duration}\n')

    def test_noninteger_tokens_rejected(self):
        for value in ['3.0', 'nan', 'Infinity', 'true', '+3', '3#comment']:
            with self.subTest(value=value), self.assertRaises(FJSParseError): self.parse_text(f'1 2\n1 1 0 {value}\n')

    def test_all_pinned_instances_parse(self):
        manifest = json.loads((ROOT / 'data/fjsp/manifest.json').read_text())
        self.assertEqual(len(manifest['instances']), 33)
        for record in manifest['instances']:
            with self.subTest(instance=record['instance_id']):
                problem = parse_fjs(ROOT / 'vendor/fjsp-instances' / record['sl_path'])
                self.assertEqual(sum(len(j['operations']) for j in problem['jobs']), record['operations'])
                self.assertEqual(len(problem['machines']), record['machines'])

    def test_hurink_split_by_base_and_runtime_has_no_reference_fields(self):
        data = json.loads((ROOT / 'data/fjsp/split.json').read_text())
        seen = set()
        forbidden = {'optimum', 'reported_optimum', 'upper_bound', 'lower_bound', 'bks', 'reference', 'references', 'url', 'reference_url'}
        def check(obj):
            if isinstance(obj, dict):
                self.assertFalse(forbidden.intersection(obj))
                for v in obj.values(): check(v)
            elif isinstance(obj, list):
                for v in obj: check(v)
        for split, families in data['splits'].items():
            bases = set(data['hurink_base_splits'][split])
            self.assertFalse(seen & bases)
            seen |= bases
            for family, ids in families.items():
                for i in ids:
                    problem = json.loads((ROOT / 'data/fjsp/instances' / (i + '.json')).read_text())
                    check(problem)
                    if family == 'hurink':
                        self.assertIn(problem['base_instance'], bases)
                        for job in problem['jobs']:
                            for op in job['operations']:
                                self.assertEqual(len({a['duration'] for a in op['alternatives']}), 1)


class ValidatorTests(Fixture):
    def assertInvalid(self, schedule, code):
        result = validate(self.problem, schedule)
        self.assertFalse(result['valid'])
        self.assertIsNone(result['makespan'])
        self.assertTrue(any(e.startswith(code + ':') for e in result['errors']), result)
        return result

    def test_hand_calculated_valid(self):
        self.assertEqual(validate(self.problem, VALID), {'valid': True, 'errors': [], 'makespan': 7})

    def test_alternative_machine_changes_duration(self):
        schedule = copy.deepcopy(VALID)
        schedule['operations'][0].update(machine=1, start=2, end=7)
        schedule['operations'][1].update(start=7, end=9)
        schedule['operations'][3].update(start=2, end=6)
        self.assertEqual(validate(self.problem, schedule)['makespan'], 9)
        schedule['operations'][0]['end'] = 5
        self.assertInvalid(schedule, 'processing_duration')

    def test_recomputes_instead_of_trusting_claimed_makespan(self):
        schedule = copy.deepcopy(VALID)
        schedule['makespan'] = 0
        self.assertEqual(validate(self.problem, schedule)['makespan'], 7)

    def test_row_order_does_not_change_feasibility(self):
        schedule = copy.deepcopy(VALID)
        schedule['operations'].reverse()
        self.assertEqual(validate(self.problem, schedule)['makespan'], 7)

    def test_missing_operation(self):
        schedule = copy.deepcopy(VALID)
        schedule['operations'].pop()
        self.assertInvalid(schedule, 'missing_operation')

    def test_duplicate_operation_even_on_another_machine(self):
        schedule = copy.deepcopy(VALID)
        schedule['operations'].append({'id': 'j0o0', 'machine': 1, 'start': 10, 'end': 15})
        self.assertInvalid(schedule, 'duplicate_operation')

    def test_unknown_operation(self):
        schedule = copy.deepcopy(VALID)
        schedule['operations'].append({'id': 'j99o0', 'machine': 0, 'start': 8, 'end': 9})
        self.assertInvalid(schedule, 'unknown_operation')

    def test_unqualified_machine(self):
        schedule = copy.deepcopy(VALID)
        schedule['operations'][1]['machine'] = 0
        self.assertInvalid(schedule, 'machine_qualification')

    def test_unique_scalar_machine_assignment(self):
        for value in [[0, 1], True, '0', 0.0, None]:
            schedule = copy.deepcopy(VALID)
            schedule['operations'][0]['machine'] = value
            with self.subTest(value=value): self.assertInvalid(schedule, 'machine_type')

    def test_duration_only(self):
        schedule = copy.deepcopy(VALID)
        schedule['operations'][1]['end'] = 6
        self.assertEqual(len(self.assertInvalid(schedule, 'processing_duration')['errors']), 1)

    def test_precedence_only(self):
        schedule = copy.deepcopy(VALID)
        schedule['operations'][1].update(start=2, end=4)
        self.assertEqual(len(self.assertInvalid(schedule, 'job_precedence')['errors']), 1)

    def test_machine_capacity_only(self):
        schedule = copy.deepcopy(VALID)
        schedule['operations'][3].update(start=2, end=6)
        self.assertEqual(len(self.assertInvalid(schedule, 'machine_capacity')['errors']), 1)

    def test_touching_intervals_allowed(self):
        self.assertTrue(validate(self.problem, VALID)['valid'])

    def test_negative_zero_length_and_noninteger_time(self):
        for start, end in [(-1, 2), (3, 3), (4, 3), (0.0, 3), (False, 3), (float('nan'), 3), (0, float('inf')), ('0', 3), (None, 3)]:
            schedule = copy.deepcopy(VALID)
            schedule['operations'][0].update(start=start, end=end)
            with self.subTest(start=start, end=end): self.assertInvalid(schedule, 'time_range')

    def test_waiting_is_allowed_no_artificial_horizon(self):
        schedule = copy.deepcopy(VALID)
        for row in schedule['operations']:
            row['start'] += 100000
            row['end'] += 100000
        self.assertEqual(validate(self.problem, schedule)['makespan'], 100007)

    def test_malformed_schedule_is_invalid_not_exception(self):
        for schedule in [None, [], {}, {'operations': None}, {'operations': [None]}, {'operations': [{'id': []}]}]:
            with self.subTest(schedule=schedule):
                result = validate(self.problem, schedule)
                self.assertFalse(result['valid'])
                self.assertIsNone(result['makespan'])

    def test_malformed_problem_is_invalid_not_exception(self):
        for problem in [None, {}, {'schema_version': 'fjsp-1', 'machines': [0, True], 'jobs': []}]:
            with self.subTest(problem=problem): self.assertFalse(validate(problem, VALID)['valid'])

    def test_checker_does_not_mutate_inputs(self):
        before_problem, before_schedule = copy.deepcopy(self.problem), copy.deepcopy(VALID)
        validate(self.problem, VALID)
        self.assertEqual(before_problem, self.problem)
        self.assertEqual(before_schedule, VALID)


if __name__ == '__main__':
    unittest.main()
