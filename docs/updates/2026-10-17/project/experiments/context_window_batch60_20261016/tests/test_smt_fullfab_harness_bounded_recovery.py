"""Actual local child processes, persistent recovery, no remote model inference."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from src.smt_fullfab.harness.contracts import ROOT, HarnessError, default_config, digest, encode, fingerprint, sha_bytes, strict_json
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.transport import call, prompt, response_schema
from src.smt_fullfab.harness.experiment import RECOVERY_POLICY, UNCAPPED_MODEL_CAPS, sealed_prior, resource_status, cumulative_usage
from src.smt_fullfab.harness.recovery import LiveEvidence, current_recoveries, schedule_recovery, validate_recoveries, wait_for_cooldown
from src.smt_fullfab.harness.evaluation import Evidence, audit_cost, audit_run, seal_evidence
from tests.test_smt_fullfab_harness import wait_delta, propose, apply


class BoundedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='offline-bounded-recovery-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.auth_path = ROOT/'artifacts/harness_v1_7_offline/authorization.json'
        self.auth = strict_json(self.auth_path.read_bytes())
        self.runtimes = []
        self.addCleanup(lambda: [r.close() for r in self.runtimes])
        self.clock = time.time()

    def ref(self, path):
        return {'path': str(path), 'sha256': sha_bytes(path.read_bytes())}

    def new(self, initial=None):
        cfg = default_config(seconds=60)
        cfg['limits'].update(UNCAPPED_MODEL_CAPS['micro'])
        cfg['unknown_usage_policy'] = 'bounded_terminated_failures'
        if initial is not None:
            cfg['initialization']='registered_saved_state'
        fp = fingerprint()
        proof = self.root/'proof.json'
        proof.write_bytes(encode({'fingerprint_sha256': fp['sha256'], 'gates': {g:'pass' for g in ['G0','G1','G2','G3','G4']}, 'test_only': True}))
        case = 'fixture-' + str(len(self.runtimes))
        if not self.runtimes:
            self.reg = {'schema':'harness-p5-registration-v7', 'caps':UNCAPPED_MODEL_CAPS, 'full_B_new_run_limit':1,
                        'authorization':self.ref(self.auth_path), 'prior_cost_evidence':self.auth['prior_cost_evidence'],
                        'experiment_directory':str(self.root), 'recovery_policy':RECOVERY_POLICY,
                        'cases':{f'fixture-{i}':{'group':'micro','config_sha256':digest(cfg),
                                  'initial_state_sha256':digest(initial['state']) if initial else None,
                                  'initial_trace_sha256':digest(initial['trace']) if initial else None} for i in range(6)},
                        'fingerprint_sha256':fp['sha256'], 'engineering_report':str(proof),'engineering_report_sha256':sha_bytes(proof.read_bytes()),
                        'cli_binary':sys.executable,'cli_sha256':sha_bytes(Path(sys.executable).read_bytes())}
            (self.root/'experiment.json').write_bytes(encode(self.reg))
        catalog=ROOT/'configs/smt_fullfab/harness_v1/model_catalog.json'
        adm={'experiment_directory':str(self.root),'experiment_sha256':digest(self.reg),'case_id':case,'group':'micro',
             'cli_binary':sys.executable,'cli_sha256':self.reg['cli_sha256'],'model_catalog':str(catalog),'model_catalog_sha256':sha_bytes(catalog.read_bytes())}
        r=Runtime.start_new(self.root/case,cfg,experiment_id='offline-no-remote-inference',mode='model',admission=adm,initial=initial)
        self.runtimes.append(r)
        return r

    def invoke(self, r, *, error='Selected model is at capacity. Please try a different model.', action=None, final_on_error=False):
        def command(directory, **kwargs):
            if action is None:
                program = "import json,sys; from pathlib import Path; "
                if final_on_error:
                    program += f"Path({str(directory/'final.txt')!r}).write_text('{{}}'); "
                program += f"print(json.dumps({{'type':'turn.failed','error':{{'message':{error!r}}}}})); sys.exit(1)"
            else:
                raw=encode({'action':action}).decode()
                program=f"import json;from pathlib import Path;Path({str(directory/'final.txt')!r}).write_text({raw!r});print(json.dumps({{'type':'turn.completed','usage':{{'input_tokens':100,'output_tokens':10,'cached_input_tokens':0}}}}))"
            return [sys.executable,'-c',program]
        # Advance the epoch clock explicitly; process ownership/exit/hash evidence
        # comes from the actual production process guard, not a mocked receipt.
        self.clock=max(self.clock,time.time())
        with patch('src.smt_fullfab.harness.recovery.time.time',return_value=self.clock), patch('src.smt_fullfab.harness.transport.command',side_effect=command):
            return call(r)

    def cool(self):
        self.clock += 200

    def test_T23_third_exact_exception_and_costs_are_retained(self):
        value={'authorization':self.ref(self.auth_path),'prior_cost_evidence':self.auth['prior_cost_evidence']}
        usage,starts,ids=sealed_prior(value)
        self.assertEqual((usage['combined']['attempts'],usage['combined']['tokens'],usage['combined']['unknown_usage'],starts,len(ids)),(53,1992747,3,0,10))
        self.assertFalse(resource_status(value,usage)['cumulative_cost_closed'])
        changed=deepcopy(self.auth);changed['recovery_policy']['max_failures_per_cohort']=6
        bad=self.root/'bad.json';bad.write_bytes(encode(changed))
        with self.assertRaisesRegex(HarnessError,'continuation_grant'):
            sealed_prior({**value,'authorization':self.ref(bad)})

    def test_T15_T21_failure_recovery_survives_restart_and_keeps_unknown(self):
        r=self.new();before=r.head['state_ref']
        result=self.invoke(r)
        self.assertEqual(result['status'],'transport_cooldown')
        self.assertEqual(r.usage()['unknown_usage'],1)
        self.assertEqual(r.head['state_ref'],before)
        with self.assertRaisesRegex(HarnessError,'recovery_cooldown'):
            r.reserve_attempt('too early',{})
        r.close();r=Runtime.resume_run(r.store.path);self.runtimes[0]=r
        self.assertNotEqual(r.head['phase'],'STOPPED')
        self.assertEqual(len(current_recoveries(r)),1)
        self.cool()
        result=self.invoke(r,action={'tool':'write_notes','context_ref':r.head['context_ref'],'request_id':'note','text':'local deterministic fixture','expected_version':0})
        self.assertEqual(result['status'],'ok')
        self.assertEqual(r.usage()['actual_model_attempts'],2)
        self.assertEqual(r.usage()['unknown_usage'],1)
        self.assertEqual(len(r.store.rows('commits')),0)
        usage=cumulative_usage(r.manifest['admission'])
        status=resource_status(self.reg,usage)
        self.assertEqual((usage['combined']['unknown_usage'],status['authorized_bounded_unknown_usage']['combined'],status['unexempt_unknown_usage']['combined']),(4,1,0))
        r.stop('fixture');sha=seal_evidence(r)
        e=Evidence(r.store.path,sha)
        self.assertEqual(audit_cost(e)['unknown_usage'],1)
        self.assertFalse(audit_cost(e)['valid'])
        self.assertEqual(len(validate_recoveries(e)),1)
        report=audit_run(r.store.path,expected_sha256=sha,scope='full_window')
        self.assertFalse(report['valid'])
        self.assertIsNone(report['bounded_recovery_exception'])

    def test_T22_two_retries_then_stop_and_shared_cohort_limit(self):
        r=self.new()
        for ordinal in (1,2):
            result=self.invoke(r)
            self.assertEqual(result['recovery']['request_failure_ordinal'],ordinal)
            self.cool()
        self.assertEqual(self.invoke(r)['status'],'stopped')
        self.assertEqual(r.usage()['unknown_usage'],3)
        self.assertEqual(len(current_recoveries(r)),2)

    def test_T18_T23_recovered_micro_commits_once_and_audit_discloses_exception(self):
        from src.smt_fullfab.harness.factory import capture
        source=Runtime.start_new(self.root/'initial',default_config(seconds=60),experiment_id='offline-initial')
        initial={'state':capture(source.env),'trace':source.store.trace(),'parent':{'fixture':'offline-saved-state'}}
        source.close()
        r=self.new(initial)
        self.assertEqual(self.invoke(r)['status'],'transport_cooldown')
        self.cool()
        checked=self.invoke(r,action={'tool':'propose_delta','context_ref':r.head['context_ref'],'request_id':'explicit-proposal','delta':wait_delta(r)})
        self.assertEqual(checked['status'],'candidate_checked')
        selected=self.invoke(r,action={'tool':'apply_candidate','context_ref':r.head['context_ref'],'request_id':'explicit-apply','candidate_ref':checked['candidate_ref']})
        self.assertEqual(selected['status'],'accepted')
        r.advance();r.stop('registered_fragment_accepted')
        self.assertEqual(len(r.store.rows('commits')),1)
        sha=seal_evidence(r)
        report=audit_run(r.store.path,expected_sha256=sha,scope='accepted_fragment')
        self.assertTrue(report['valid'],report['errors'])
        self.assertFalse(report['cost_accounting']['valid'])
        self.assertEqual(report['cost_accounting']['actual_attempts'],3)
        self.assertTrue(report['bounded_recovery_exception']['authorized_for_fragment_completion'])

    def test_T22_shared_limit_counts_other_runs_without_reset(self):
        for index in range(6):
            r=self.new()
            result=self.invoke(r)
            self.assertEqual(result['status'],'transport_cooldown' if index<5 else 'stopped')
            r.stop('fixture')
            self.cool()
        self.assertEqual(sum(len(current_recoveries(r)) for r in self.runtimes),5)

    def test_T16_T23_unregistered_error_never_retried(self):
        r=self.new()
        self.assertEqual(self.invoke(r,error='invalid authentication')['status'],'stopped')
        self.assertFalse(current_recoveries(r))

    def test_T16_T23_partial_output_never_retried(self):
        r=self.new()
        self.assertEqual(self.invoke(r,final_on_error=True)['status'],'stopped')
        self.assertFalse(current_recoveries(r))

    def test_T21_crash_after_response_before_recovery_can_be_reconciled_once(self):
        r=self.new()
        def fault(point):
            if point=='after_response_saved':raise RuntimeError('simulated owner crash')
        r.store.fault=fault
        with self.assertRaisesRegex(RuntimeError,'simulated owner crash'):self.invoke(r)
        self.assertEqual(r.usage()['unknown_usage'],1)
        path=r.store.path;r.close()
        r=Runtime.resume_run(path);self.runtimes[0]=r
        self.assertEqual(len(current_recoveries(r)),1)
        r.reconcile()
        self.assertEqual(len(current_recoveries(r)),1)
        self.assertEqual(r.usage()['actual_model_attempts'],1)

    def test_T21_cooldown_is_interruptible_and_tamper_is_rejected(self):
        r=self.new();self.invoke(r)
        (r.store.path/'stop_requested.json').write_text('{}')
        with self.assertRaisesRegex(HarnessError,'user_stop'):wait_for_cooldown(r)
        aid,row=r.store.rows('transport_recoveries')[0]
        row['not_before_epoch']-=1
        with r.store.transaction():r.store.record('transport_recoveries',aid,row,replace=True)
        with self.assertRaisesRegex(HarnessError,'recovery_cooldown'):current_recoveries(r)


class CandidateProgressTests(unittest.TestCase):
    def test_T06_atomic_check_needs_only_independent_selection_and_retains_alternatives(self):
        with tempfile.TemporaryDirectory() as directory:
            r=Runtime.start_new(Path(directory)/'run',default_config(seconds=60),experiment_id='offline-candidate-progress')
            try:
                a=propose(r,wait_delta(r,version='a'),request='a')
                b=propose(r,wait_delta(r,version='b'),request='b')
                self.assertEqual(a['protocol_stage'],'proposal_complete_awaiting_explicit_selection')
                self.assertFalse(a['draft_required'])
                text=prompt(r)
                self.assertIn(a['candidate_ref'],text);self.assertIn(b['candidate_ref'],text)
                self.assertEqual(len(r.store.rows('drafts')),0)
                self.assertEqual(len(r.store.rows('commits')),0)
                self.assertEqual(apply(r,a['candidate_ref'])['status'],'accepted')
                self.assertEqual(r.store.rows('commits')[0][1]['candidate_ref'],a['candidate_ref'])
                tools={a['properties']['tool']['enum'][0] for a in response_schema(comparison_context_refs=[])['properties']['action']['anyOf']}
                self.assertTrue({'propose_delta','apply_candidate','begin_proposal','read_entities'}<=tools)
            finally:r.close()


if __name__=='__main__':unittest.main()
