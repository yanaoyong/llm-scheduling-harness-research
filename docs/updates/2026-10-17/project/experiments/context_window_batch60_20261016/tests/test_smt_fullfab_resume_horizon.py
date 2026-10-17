"""Exact recorded crop types; genuine attribution changes remain failures."""
from copy import deepcopy
import math
import unittest

from src.smt_fullfab.controller_audit import _crop, digest
from src.smt_fullfab.controller_resume_audit import _registered_physical_horizon


def horizon(registered, recorded):
    return _registered_physical_horizon({'window_seconds': registered},
        [{'kind': 'initial', 'manifest': {'horizon': recorded}}])


class RecordedHorizonTests(unittest.TestCase):
    def test_registered_numeric_equality_preserves_recorded_json_type(self):
        for registered in (3600, 3600.0):
            for recorded in (3600, 3600.0):
                with self.subTest(registered=registered, recorded=recorded):
                    result = horizon(registered, recorded)
                    self.assertIs(type(result), type(recorded))
                    self.assertEqual(result, recorded)

    def test_invalid_or_really_different_window_is_rejected(self):
        for value in (None, True, False, '3600', 0, -1, float('nan'),
                      float('inf'), math.nextafter(3600.0, math.inf)):
            for registered, recorded in ((3600, value), (value, 3600.0)):
                with self.subTest(registered=registered, recorded=recorded):
                    with self.assertRaises(ValueError):horizon(registered, recorded)

    def test_original_initial_manifest_is_required(self):
        for trace in (None, [], [{}], [{'kind': 'initial'}],
                      [{'kind': 'initial', 'manifest': {}}],
                      [{'kind': 'snapshot_loaded', 'manifest': {'horizon': 3600}}]):
            with self.subTest(trace=trace), self.assertRaises(ValueError):
                _registered_physical_horizon({'window_seconds': 3600}, trace)

    def test_crop_hash_reproduces_float_horizon_without_normalizing_tasks(self):
        raw = {'version': 'explicit', 'created_at': 0.0, 'valid_until': 14400.0,
               'freeze_until': 0.0, 'scope': [1], 'reason': 'model choice',
               'tasks': [{'id': 'task', 'machine': 1, 'not_before': 10.0,
                          'lot_ids': ['lot'], 'steps': [1], 'visits': [1],
                          'operation_ids': ['operation']}], 'holds': []}
        saved = _crop(raw, 3600.0, [1])
        wrong_type = _crop(raw, 3600, [1])
        self.assertEqual(saved, wrong_type)  # Python equality hid the defect.
        self.assertNotEqual(digest(saved), digest(wrong_type))
        actual = _crop(raw, horizon(3600, 3600.0), [1])
        self.assertEqual(digest(actual), digest(saved))
        changed = deepcopy(raw);changed['tasks'][0]['not_before'] = 10
        self.assertNotEqual(digest(_crop(changed, horizon(3600, 3600.0), [1])), digest(saved))

    def test_shorter_or_equal_raw_endpoint_retains_original_min_semantics(self):
        for endpoint in (1000, 1000.0, 3600, 3600.0):
            raw = {'version': 'p', 'created_at': 0, 'valid_until': endpoint,
                   'freeze_until': 0, 'scope': [1], 'tasks': [], 'holds': []}
            output = _crop(raw, horizon(3600, 3600.0), [1])
            self.assertIs(type(output['valid_until']), type(endpoint))


if __name__ == '__main__':unittest.main()
