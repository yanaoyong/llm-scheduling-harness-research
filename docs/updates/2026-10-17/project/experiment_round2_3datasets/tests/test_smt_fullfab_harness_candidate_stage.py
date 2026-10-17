"""State-aware actions preserve alternatives and independent model selection."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from src.smt_fullfab.harness.contracts import ROOT, HarnessError, encode, sha_bytes, strict_json
from src.smt_fullfab.harness.transport import response_schema
from src.smt_fullfab.harness.evaluation import seal_evidence, audit_run
from src.smt_fullfab.harness.experiment import sealed_prior, BOUNDED_TIME_CAPS, continuation_authorization
from tests import test_smt_fullfab_harness_bounded_recovery as fixtures
from tests.test_smt_fullfab_harness import wait_delta


class CandidateStageTests(unittest.TestCase):
    def test_T06_stage_schema_keeps_all_candidates_and_alternative_decisions(self):
        def actions(refs, opened=False):
            return response_schema(comparison_context_refs=[],candidate_refs=refs,has_open_draft=opened)['properties']['action']['anyOf']
        first=actions([])
        self.assertIn('begin_proposal',[a['properties']['tool']['enum'][0] for a in first])
        self.assertNotIn('apply_candidate',[a['properties']['tool']['enum'][0] for a in first])
        refs=['candidate:older','candidate:newer'];checked=actions(refs)
        tools={a['properties']['tool']['enum'][0] for a in checked}
        self.assertFalse({'begin_proposal','write_notes','append_proposal','finalize_proposal'}&tools)
        self.assertTrue({'apply_candidate','propose_delta','read_entities','read_artifact','begin_alternative_proposal'}<=tools)
        for a in checked:
            if a['properties']['tool']['enum']==['apply_candidate']:
                self.assertEqual(a['properties']['candidate_ref']['enum'],refs)
        self.assertTrue(any('selection_note' in a['properties'] for a in checked))
        self.assertTrue({'append_proposal','finalize_proposal'}<={a['properties']['tool']['enum'][0] for a in actions(refs,True)})

    def fixture(self):
        helper=fixtures.BoundedRecoveryTests();helper.setUp();self.addCleanup(helper.doCleanups)
        return helper,helper.new()

    def test_T06_T09_old_extra_actions_blocked_alternative_and_explicit_commit_preserved(self):
        h,r=self.fixture();ctx=r.head['context_ref']
        checked=h.invoke(r,action={'tool':'propose_delta','context_ref':ctx,'request_id':'p','delta':wait_delta(r)})
        self.assertEqual(checked['status'],'candidate_checked')
        for action in [{'tool':'write_notes','context_ref':ctx,'request_id':'old-note','text':'unnecessary round','expected_version':0},
                       {'tool':'begin_proposal','context_ref':ctx,'request_id':'old-draft','proposal_id':'duplicate'}]:
            result=h.invoke(r,action=action)
            self.assertEqual(result['error']['code'],'candidate_stage')
        self.assertFalse(r.store.rows('drafts'));self.assertFalse(r.store.rows('commits'))
        alt=h.invoke(r,action={'tool':'begin_alternative_proposal','context_ref':ctx,'request_id':'different','proposal_id':'alternative',
                              'reviewed_candidate_ref':checked['candidate_ref'],'reason':'I explicitly want to consider a different large plan.'})
        self.assertEqual(alt['status'],'proposal_opened')
        self.assertEqual(len(r.store.rows('candidates')),1)
        selected=h.invoke(r,action={'tool':'apply_candidate','context_ref':ctx,'request_id':'select-older',
                                   'candidate_ref':checked['candidate_ref'],'selection_note':'Model-authored selection memory'})
        self.assertEqual(selected['status'],'accepted');self.assertEqual(selected['selection_note_status'],'saved')
        self.assertEqual(r.store.read('notes','current')['text'],'Model-authored selection memory')
        self.assertEqual(len(r.store.rows('commits')),1)
        r.advance();sha=seal_evidence(r);report=audit_run(r.store.path,expected_sha256=sha)
        self.assertTrue(report['valid'],report['errors'])
        self.assertEqual(report['decision_provenance']['algorithm_production_tasks'],0)

    def test_T06_invalid_optional_note_does_not_reject_valid_commit(self):
        h,r=self.fixture();ctx=r.head['context_ref']
        checked=h.invoke(r,action={'tool':'propose_delta','context_ref':ctx,'request_id':'p','delta':wait_delta(r)})
        selected=h.invoke(r,action={'tool':'apply_candidate','context_ref':ctx,'request_id':'apply','candidate_ref':checked['candidate_ref'],'selection_note':123})
        self.assertEqual(selected['status'],'accepted')
        self.assertEqual(selected['selection_note_status'],'rejected_invalid_note_commit_unaffected')
        self.assertIsNone(r.store.read('notes','current'))
        self.assertEqual(len(r.store.rows('commits')),1)

    def test_T23_finite_time_grant_retains_canary_and_rejects_further_expansion(self):
        path=ROOT/'artifacts/harness_v1_8_offline/authorization.json'
        def ref(p):return {'path':str(p),'sha256':sha_bytes(p.read_bytes())}
        grant=continuation_authorization(ref(path));self.assertEqual(grant['caps'],BOUNDED_TIME_CAPS)
        usage,starts,ids=sealed_prior({'authorization':ref(path),'prior_cost_evidence':grant['prior_cost_evidence']})
        self.assertEqual((usage['combined']['attempts'],usage['combined']['tokens'],usage['combined']['unknown_usage'],starts,len(ids)),(64,2431908,3,0,13))
        with tempfile.TemporaryDirectory() as d:
            bad=deepcopy(grant);bad['caps']['micro']['model_seconds']+=1;p=Path(d)/'bad.json';p.write_bytes(encode(bad))
            with self.assertRaisesRegex(HarnessError,'continuation_grant'):continuation_authorization(ref(p))


if __name__=='__main__':unittest.main()
