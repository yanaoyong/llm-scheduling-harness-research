"""Raw counter validation, with no transport launch or real ledger access."""
from copy import deepcopy
import unittest
from src.smt_fullfab.model_transport import summarize_events


class TransportUsageTests(unittest.TestCase):
    def event(self,usage):return {'type':'turn.completed','usage':usage}

    def test_exact_nonnegative_integers_and_large_values_keep_old_shape(self):
        summary=summarize_events([self.event({'input_tokens':2**64+17,'output_tokens':0})])
        self.assertEqual(summary['usage']['input_tokens'],2**64+17)
        self.assertEqual(summary['usage']['output_tokens'],0)
        self.assertEqual(summary['usage_status'],'reported')
        self.assertNotIn('usage_validation_errors',summary)

    def test_invalid_values_never_become_known_counters_or_mutate_raw_input(self):
        for value in (True,False,-1,1.0,.5,float('nan'),float('inf'),float('-inf'),'1',[],{}):
            with self.subTest(value=value):
                event=self.event({'input_tokens':value,'output_tokens':3})
                result=summarize_events([event])
                self.assertIsNone(result['usage']['input_tokens'])
                self.assertEqual(result['usage']['output_tokens'],3)
                self.assertEqual(result['usage_status'],'invalid')
                self.assertEqual(result['usage_validation_errors'][0]['field'],'input_tokens')
                self.assertIs(event['usage']['input_tokens'],value)

    def test_missing_or_null_retains_unknown_without_inventing_validation_error(self):
        for event in ({'type':'turn.completed'},self.event(None),self.event({}),self.event({'input_tokens':None})):
            with self.subTest(event=event):
                summary=summarize_events([event]);self.assertIsNone(summary['usage']['input_tokens'])
                self.assertIsNone(summary['usage']['output_tokens']);self.assertNotIn('usage_validation_errors',summary)

    def test_mixed_complete_and_unknown_turn_does_not_report_partial_sum_as_complete(self):
        for unknown in ({'type':'turn.completed'},self.event(None)):
            summary=summarize_events([self.event({'input_tokens':20,'output_tokens':5}),unknown])
            self.assertEqual(summary['completed_turns'],2)
            self.assertIsNone(summary['usage']['input_tokens']);self.assertIsNone(summary['usage']['output_tokens'])

    def test_bad_usage_container_and_optional_counter_are_reported(self):
        for raw in (1,True,'wrong',[],{'input_tokens':2,'output_tokens':1,'cached_input_tokens':True}):
            with self.subTest(raw=raw):
                summary=summarize_events([self.event(raw)])
                self.assertEqual(summary['usage_status'],'invalid');self.assertTrue(summary['usage_validation_errors'])


if __name__=='__main__':unittest.main()
