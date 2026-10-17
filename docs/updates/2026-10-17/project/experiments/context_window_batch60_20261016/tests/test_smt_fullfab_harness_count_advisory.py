"""User-authorized advisory counts, retained checkpoints, and bounded timeouts."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from contextlib import nullcontext
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab.harness.contracts import ROOT, HarnessError, digest, encode, fingerprint, sha_bytes, strict_json
from src.smt_fullfab.harness.amendment import (amendment_for, validate_amendment,
    continue_sealed_failure, validate_continuation, validate_advisory_B_gate)
from src.smt_fullfab.harness.evaluation import microbenchmark_gate
from src.smt_fullfab.harness.recovery import LiveEvidence, failure_kind, schedule_recovery


class CountAdvisoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='offline-count-advisory-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.live = ROOT/'artifacts/harness_p5_sol_feedback_release'
        self.out = ROOT/'artifacts/harness_sol_count_metrics'
        self.reg = strict_json((self.live/'experiment.json').read_bytes())
        # This fixture exercises the already frozen advisory-only revision.
        # A later, separately authorized model-switch controller must not be
        # represented as part of that older amendment's allowed file changes.
        self.fp = strict_json((self.out/'engineering_acceptance.json').read_bytes())['fingerprint']
        test = self.root/'tests.json'
        test.write_bytes(encode({'all_pass':True,'source_unchanged':True,'fingerprint_sha256':self.fp['sha256'],'remote_model_calls':0}))
        report = self.root/'engineering.json'
        report.write_bytes(encode({'fingerprint':self.fp,'fingerprint_sha256':self.fp['sha256'],'test_evidence':self.ref(test),'gates':{g:'pass' for g in ('G0','G1','G2','G3','G4')}}))
        self.metrics = {**self.reg['micro_metrics'],'enforcement':'advisory'}
        self.value = {'schema':'harness-call-count-amendment-v1','base_registration_sha256':digest(self.reg),
            'user_authorization':self.ref(self.out/'authorization.json'),
            'timeout_authorization':self.ref(self.out/'timeout_authorization.json'),
            'original_policy':deepcopy(self.reg['recovery_policy']),
            'policy':{**self.reg['recovery_policy'],'allowed_failure_kinds':self.reg['recovery_policy']['allowed_failure_kinds']+['guarded_timeout']},
            'metrics':self.metrics,'active_fingerprint_sha256':self.fp['sha256'],
            'engineering_report':self.ref(report),'recovery_boundary':self.ref(self.out/'boundary.json'),
            'sealed_failure':self.ref(self.live/'runs/micro-12/evidence_manifest.json'),
            'continuation_directory':str(self.root/'continuations/micro-12-count-advisory')}

    def ref(self, path):
        return {'path':str(path), 'sha256':sha_bytes(path.read_bytes())}

    def amended(self, reg):
        return self.value if digest(reg) == digest(self.reg) else amendment_for(reg)

    def test_T20_registration_preserves_correctness_time_model_and_recovery_limits(self):
        self.assertEqual(validate_amendment(self.value,self.reg),self.value)
        for field in ('max_retries_per_request','cooldown_seconds','max_failures_per_cohort','full_B_requires_zero_unknown'):
            bad=deepcopy(self.value)
            bad['policy'][field]={'max_retries_per_request':3,'cooldown_seconds':[0,0],'max_failures_per_cohort':31,'full_B_requires_zero_unknown':False}[field]
            with self.subTest(field=field),self.assertRaises(HarnessError):validate_amendment(bad,self.reg)
        bad=deepcopy(self.value);bad['metrics']['n_min']=19
        with self.assertRaises(HarnessError):validate_amendment(bad,self.reg)
        bad=deepcopy(self.value);bad['metrics']['failures_excluded']=True
        with self.assertRaises(HarnessError):validate_amendment(bad,self.reg)
        bad=deepcopy(self.value);bad['base_registration_sha256']='0'*64
        with self.assertRaises(HarnessError):validate_amendment(bad,self.reg)

    def test_T22_counts_are_advisory_but_all_twenty_correct_cases_are_required(self):
        rows=[{'id':f'micro-{i:02d}','attempts':10+i,'accepted':True} for i in range(1,21)]
        self.assertFalse(microbenchmark_gate(rows)['pass'])
        gate=microbenchmark_gate(rows,metrics=self.metrics)
        self.assertTrue(gate['pass']);self.assertFalse(gate['efficiency_target_pass'])
        self.assertEqual(gate['median'],20.5);self.assertEqual(gate['p95_nearest_rank'],29)
        self.assertEqual(gate['n'],20);self.assertTrue(gate['warnings'])
        rows[-1].update(attempts=0,accepted=False,not_completed=True)
        gate=microbenchmark_gate(rows,metrics=self.metrics)
        self.assertFalse(gate['pass']);self.assertEqual(gate['n'],20)
        self.assertIsNone(gate['median']);self.assertIsNone(gate['p95_nearest_rank'])
        self.assertFalse(microbenchmark_gate(rows[:-1],metrics=self.metrics)['pass'])

    def test_T22_advisory_runner_dispatches_second_sixth_call_and_keeps_unstarted_rows(self):
        from src.smt_fullfab.harness.p5 import micro
        root=self.root/'cohort';p=root/'runs/micro-14';p.mkdir(parents=True)
        (p/'fragment_result.json').write_bytes(encode({'id':'micro-14','attempts':6,'accepted':True}))
        cases={f'micro-{i:02d}':{'group':'micro','max_attempts_per_fragment':None,'task':'offline fixture'} for i in range(1,21)};cases['B3600']={'group':'B3600'}
        caps={g:{'attempts':None,'tokens':None,'model_seconds':1000,'wall_seconds':1000} for g in ('micro','B3600','combined')}
        reg={'schema':'offline_test','cases':cases,'execution_order':['micro-20'],'caps':caps,'cli_binary':'unused','cli_sha256':'unused','model_catalog':'unused','model_catalog_sha256':'unused'}
        (root/'experiment.json').write_bytes(encode(reg));(root/'runs/micro-20').mkdir()
        head={'phase':'OBSERVED'};commits=[];calls=[]
        def call(runtime,**kwargs):
            calls.append('call');commits.append(('commit',{}));head['phase']='COMMITTED';return {'status':'accepted'}
        r=SimpleNamespace(head=head,store=SimpleNamespace(rows=lambda name:commits if name=='commits' else []),
            usage=lambda:{'actual_model_attempts':5+len(calls),'unknown_usage':0},stop=lambda reason:head.update(phase='STOPPED',stop_reason=reason),
            advance=lambda:head.update(phase='OBSERVED'),close=lambda:None)
        usage={g:{**{k:0 for k in caps[g]},'pending':0} for g in caps}
        with patch('src.smt_fullfab.harness.amendment.effective_micro_metrics',return_value=self.metrics),patch('src.smt_fullfab.harness.p5.open_case',return_value=r),patch('src.smt_fullfab.harness.transport.call',side_effect=call),patch('src.smt_fullfab.harness.p5.seal_evidence',return_value='retained'),patch('src.smt_fullfab.harness.p5.audit_run',return_value={'valid':True,'errors':[]}),patch('src.smt_fullfab.harness.p5.cumulative_usage',return_value=usage),patch('src.smt_fullfab.harness.p5.resource_status',return_value={'unexempt_unknown_usage':{g:0 for g in caps}}):
            gate=micro(root)
        self.assertEqual(calls,['call']);self.assertEqual(len(gate['fragments']),20)
        self.assertEqual(head['stop_reason'],'registered_fragment_accepted');self.assertFalse(gate['pass'])

    def test_T15_T21_continue_exact_sealed_checkpoint_without_clock_or_cost_reset(self):
        (self.root/'experiment.json').write_bytes(encode(self.reg))
        source=self.live/'runs/micro-12';old=LiveEvidence(source);m=old.manifest
        with sqlite3.connect(self.root/'account.sqlite3') as db:
            db.execute('CREATE TABLE runs(case_id TEXT PRIMARY KEY,group_name TEXT,run_id TEXT UNIQUE,directory TEXT,created REAL)')
            db.execute('INSERT INTO runs VALUES(?,?,?,?,?)',('micro-12','micro',m['run_id'],str(source),m['created_epoch']))
        original_sha=sha_bytes((source/'evidence_manifest.json').read_bytes())
        with patch('src.smt_fullfab.harness.amendment.amendment_for',side_effect=self.amended),patch('src.smt_fullfab.harness.experiment.experiment_lock',return_value=nullcontext()),patch('src.smt_fullfab.harness.contracts.fingerprint',return_value=self.fp):
            target=continue_sealed_failure(self.root)
            view=LiveEvidence(target)
            with sqlite3.connect(f'file:{target}/events.sqlite3?mode=ro',uri=True) as db:
                db.row_factory=sqlite3.Row
                view.value={'events':[dict(x) for x in db.execute('SELECT * FROM events ORDER BY seq')], 'physical':[x[0] for x in db.execute('SELECT object_ref FROM physical ORDER BY seq')]}
            validate_continuation(view)
            self.assertEqual(view.manifest,m);self.assertEqual(view.rows('attempts'),old.rows('attempts'))
            self.assertEqual(view.rows('transport_recoveries'),old.rows('transport_recoveries'))
            self.assertFalse((target/'stop_requested.json').exists());self.assertFalse((target/'audit_closure.json').exists())
            with self.assertRaises(HarnessError):continue_sealed_failure(self.root)
        self.assertEqual(sha_bytes((source/'evidence_manifest.json').read_bytes()),original_sha)

    def test_T23_guarded_timeout_requires_no_answer_and_complete_deadline_cleanup(self):
        view=LiveEvidence(self.live/'runs/micro-12');a=list(view.rows('attempts').values())[-1]
        with patch('src.smt_fullfab.harness.recovery.policy_for',return_value=self.value['policy']):
            self.assertEqual(failure_kind(view,a),'guarded_timeout')
            original=view.raw;ref=a['transport']['original_guard_files']['receipt.json']
            with patch.object(view,'raw',side_effect=lambda key:encode({**strict_json(original(key)),'owner_eof':True}) if key==ref else original(key)):
                with self.assertRaises(HarnessError):failure_kind(view,a)
        with patch('src.smt_fullfab.harness.recovery.policy_for',return_value=self.reg['recovery_policy']):
            with self.assertRaises(HarnessError):failure_kind(view,a)

    def test_T22_timeout_uses_ninth_slot_and_second_retry_without_an_extra_call(self):
        source=self.live/'runs/micro-12';view=LiveEvidence(source);a=list(view.rows('attempts').values())[-1];saved={}
        fake=SimpleNamespace(path=source,transaction=lambda:nullcontext(),record=lambda ns,k,row:saved.update({k:row}),event=lambda *args:None)
        runtime=SimpleNamespace(config=view.manifest['config'],manifest=view.manifest,store=fake)
        # Bind this ordinal assertion to the retained failure boundary, before
        # later fragment/B failures consumed additional slots in the live cohort.
        from src.smt_fullfab.harness.recovery import cohort_recoveries
        def boundary_cohort(reg):
            return {view.manifest['run_id']:('micro',view.rows('transport_recoveries'))} if digest(reg)==digest(self.reg) else cohort_recoveries(reg)
        with patch('src.smt_fullfab.harness.amendment.amendment_for',side_effect=self.amended),patch('src.smt_fullfab.harness.recovery.cohort_recoveries',side_effect=boundary_cohort):
            row=schedule_recovery(runtime,a['attempt_id'])
        self.assertEqual(row['cohort_failure_ordinal'],9);self.assertEqual(row['request_failure_ordinal'],2)
        self.assertEqual(row['not_before_epoch'],a['finished_epoch']+180)
        self.assertEqual(row['attempt_sha256'],digest(a));self.assertEqual(len(saved),1)

    def test_T20_T23_B_requires_twenty_matching_audits_and_retained_resource_limits(self):
        reg=deepcopy(self.reg);reg['experiment_directory']=str(self.root)
        value=deepcopy(self.value);value['base_registration_sha256']=digest(reg)
        rows=[]
        for case,entry in reg['cases'].items():
            if entry['group']!='micro':continue
            p=self.root/'runs'/case;p.mkdir(parents=True)
            (p/'evidence_manifest.json').write_bytes(encode({'synthetic_test':case}))
            sha=sha_bytes((p/'evidence_manifest.json').read_bytes())
            row={'id':case,'attempts':9,'accepted':True,'evidence_sha256':sha};rows.append(row)
            (p/'fragment_result.json').write_bytes(encode(row))
            (p/'audit').mkdir();(p/'audit/acceptance.json').write_bytes(encode({'valid':True,'evidence_sha256':sha,'cost_accounting':{'actual_attempts':9}}))
        gate={**microbenchmark_gate(rows,metrics=self.metrics),'registered_count':20,'fragments':rows,'experiment_sha256':digest(reg),'control_amendment_sha256':digest(value),'resource_pass':True}
        usage={g:{'attempts':180,'tokens':10000,'model_seconds':100,'wall_seconds':100,'pending':0} for g in ('micro','combined')}
        with patch('src.smt_fullfab.harness.amendment.amendment_for',return_value=value),patch('src.smt_fullfab.harness.experiment.cumulative_usage',return_value=usage),patch('src.smt_fullfab.harness.experiment.resource_status',return_value={'unexempt_unknown_usage':{'micro':0,'combined':0}}):
            validate_advisory_B_gate(reg,gate)
            bad=deepcopy(gate);bad['registered_count']=19
            with self.assertRaises(HarnessError):validate_advisory_B_gate(reg,bad)
            usage['micro']['wall_seconds']=reg['caps']['micro']['wall_seconds']+1
            with self.assertRaises(HarnessError):validate_advisory_B_gate(reg,gate)
            usage['micro']['wall_seconds']=100
            (self.root/'runs/micro-01/fragment_result.json').unlink()
            with self.assertRaises(HarnessError):validate_advisory_B_gate(reg,gate)


if __name__=='__main__':unittest.main()
