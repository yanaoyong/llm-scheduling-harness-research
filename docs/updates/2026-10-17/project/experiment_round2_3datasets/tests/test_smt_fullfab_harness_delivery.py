"""Current-context delivery and multi-cohort accounting; no real inference."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from src.smt_fullfab.harness.contracts import ROOT, HarnessError, default_config, encode, sha_bytes, strict_json
from src.smt_fullfab.harness.experiment import sealed_prior
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.transport import prompt, response_schema
from tests.test_smt_fullfab_harness import wait_delta, propose, apply


class DeliveryTests(unittest.TestCase):
    def test_T12_model_wire_omits_redundant_delivery_without_choosing_production(self):
        original = response_schema('B')['properties']['action']['anyOf']
        fresh = response_schema('B', comparison_context_refs=[])['properties']['action']['anyOf']
        self.assertFalse(any(v['properties']['tool']['enum'] == ['get_context'] for v in fresh))
        self.assertEqual(fresh, [v for v in original if v['properties']['tool']['enum'] != ['get_context']])
        # All production actions and complete exact fact/artifact reads survive
        # byte-for-byte. No candidate, machine, wait or task is auto-selected.
        changed = response_schema('B', comparison_context_refs=['owned-old-context'])['properties']['action']['anyOf']
        delta = [v for v in changed if v['properties']['tool']['enum'] == ['get_context']]
        self.assertEqual(len(delta), 1)
        self.assertIn('since_context_ref', delta[0]['required'])
        self.assertEqual(delta[0]['properties']['since_context_ref']['enum'], ['owned-old-context'])

    def test_T12_gateway_rejects_duplicate_delivery_but_preserves_change_sets(self):
        root = Path(tempfile.mkdtemp(prefix='offline-context-delivery-'))
        cfg = default_config(seconds=60); cfg['period_seconds'] = 1
        r = Runtime.start_new(root / 'run', cfg, experiment_id='offline-context-delivery')
        try:
            old = r.context()['context_ref']
            self.assertIn(old, prompt(r))
            before = r.head.copy()
            for action in ({'tool': 'get_context', 'context_ref': old},
                           {'tool': 'get_context', 'context_ref': old, 'since_context_ref': old}):
                with self.assertRaisesRegex(HarnessError, 'redundant_context_read'):
                    with r.store.transaction(): r._execute(action, {'channel': 'codex'})
            self.assertEqual(r.head, before)
            self.assertEqual(r.store.rows('commits'), [])
            apply(r, propose(r, wait_delta(r))['candidate_ref']); r.advance(); r.observe()
            current = r.head['context_ref']
            self.assertNotEqual(old, current)
            with r.store.transaction():
                result = r._execute({'tool': 'get_context', 'context_ref': current, 'since_context_ref': old}, {'channel': 'codex'})
            self.assertEqual(result['status'], 'ok')
            self.assertGreater(result['context']['change_pages'], 0)
        finally: r.close()

    def test_T23_both_failed_cohorts_are_counted_once_without_missing_ancestors(self):
        path = ROOT / 'artifacts/harness_v1_2_offline/prior_cost_evidence.json'
        def ref(p): return {'path': str(p), 'sha256': sha_bytes(p.read_bytes())}
        value = strict_json(path.read_bytes())
        usage, starts, ids = sealed_prior({'prior_cost_evidence': ref(path)})
        self.assertEqual((usage['micro']['attempts'], usage['micro']['tokens'], len(ids), starts), (24, 977402, 4, 0))
        root = Path(tempfile.mkdtemp(prefix='offline-aggregate-cost-'))
        missing = deepcopy(value)
        missing['cohorts'] = missing['cohorts'][1:]
        leaf = strict_json(Path(missing['cohorts'][0]['path']).read_bytes())
        missing['cumulative_usage'] = leaf['cumulative_usage']
        p = root / 'omitted-old.json'; p.write_bytes(encode(missing))
        with self.assertRaisesRegex(HarnessError, 'carry_ancestor_missing'):
            sealed_prior({'prior_cost_evidence': ref(p)})
        duplicate = deepcopy(value); duplicate['cohorts'].append(duplicate['cohorts'][0])
        p = root / 'duplicate.json'; p.write_bytes(encode(duplicate))
        with self.assertRaisesRegex(HarnessError, 'carry_duplicate'):
            sealed_prior({'prior_cost_evidence': ref(p)})


if __name__ == '__main__': unittest.main()
