"""Source binding and semantic boundary regression tests for the new namespace."""
import copy
import tempfile
import unittest
from pathlib import Path
from src.smt_fullfab.source_audit import ROOT, EXPECTED, audit_source, verify_hashes, sha256
from src.smt_fullfab.reference import reference_action


class SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = audit_source(ROOT)

    def test_locked_data_integrity_and_counts(self):
        self.assertTrue(self.report['source_integrity_passed'])
        self.assertEqual(self.report['counts'], EXPECTED)
        self.assertFalse(self.report['official_calibration_passed'])

    def test_changed_bytes_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'input.txt'
            p.write_bytes(b'locked input')
            hashes={'input.txt':sha256(p)}
            self.assertTrue(verify_hashes(d,hashes)[0]['ok'])
            p.write_bytes(b'changed input')
            self.assertFalse(verify_hashes(d,hashes)[0]['ok'])

    def test_no_silent_long_window_release_reuse(self):
        release=self.report['releases']['periodic_21_stream_counts']
        self.assertEqual(release['28800'],31)
        self.assertGreater(release['86400'],31)
        self.assertGreater(release[str(28*86400)],release[str(7*86400)])

    def test_non_equivalence_and_missing_history_are_exposed(self):
        semantics=self.report['semantics']
        self.assertEqual(semantics['cqt_segments'],264)
        self.assertEqual(semantics['dedication_rules'],73)
        self.assertEqual(semantics['initial_lots_with_missing_historical_bindings'],1311)
        self.assertEqual(semantics['periodic_hotlot_counts'],{'no':21})
        explicit=self.report['releases']['explicit_orders']['order_high_SL_92PCTL.txt']
        self.assertEqual(explicit['nonempty_lots'],167129)
        self.assertGreater(explicit['distinct_due_leads_per_order']['O_Lot_1'],1)
        self.assertIn('order_high_SL_92PCTL.txt',self.report['official_options_order_section'])

    def test_reference_is_explicit_and_no_mutation(self):
        from src.smt.environment import SmtEnvironment
        env=SmtEnvironment(window_seconds=3600,controlled_machine_ids=(),max_decisions=100000)
        before=copy.deepcopy((env.lots,env.machine_state,env.q,env.trace,env.waiting,env.processing_by_machine))
        response=reference_action(env,'cr')
        self.assertEqual((env.lots,env.machine_state,env.q,env.trace,env.waiting,env.processing_by_machine),before)
        action=response['action']
        self.assertGreater(len(action['dispatches']),2)
        seen=set()
        for dispatch in action['dispatches']:
            env._validate(dispatch['machine'],dispatch['lot_ids'])
            self.assertFalse(seen.intersection(dispatch['lot_ids']))
            seen.update(dispatch['lot_ids'])
        self.assertEqual(response['provenance']['production_machines_considered'],913)
        self.assertFalse(response['provenance']['official_calibrated'])
        with self.assertRaises(ValueError):
            reference_action(env,'unknown')

if __name__=='__main__':
    unittest.main()
