"""Sixth presentation repair against the real 384-call checkpoint, without RPC."""
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
import shutil, sqlite3, tempfile, unittest
from unittest.mock import patch
from src.smt_fullfab.harness import experiment, source_revision, wall_budget
from src.smt_fullfab.harness.contracts import ROOT, HarnessError, digest, encode, fingerprint, sha_bytes, strict_json
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.transport import prompt, PROTOCOL_TEXT
from src.smt_fullfab.harness.fact_memory import INSTRUCTIONS
from tests.test_smt_fullfab_harness_fact_memory import BOUNDARY, OUT

LIVE=ROOT/'artifacts/harness_p5_astra_TUN_B_release'
RUN=LIVE/'continuations/B3600-no-exception-quota'

class FactRetentionRevisionTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix='offline-fact-retention-')
        self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.reg=strict_json((LIVE/'experiment.json').read_bytes())
        self.base=strict_json((LIVE/'exception_policy_amendment.json').read_bytes())
        self.previous=strict_json((LIVE/'source_revision_5.json').read_bytes())
        self.fp=strict_json(Path(strict_json((LIVE/'source_revision_6.json').read_bytes())['engineering_report']['path']).read_bytes())['fingerprint']
        frozen=patch('src.smt_fullfab.harness.runtime.fingerprint',return_value=self.fp)
        frozen.start();self.addCleanup(frozen.stop)
        self.grant={'schema':'harness-control-repair-authorization-v1',
                    'user_instruction':'取消异常额度这些限制，你的目标是不浪费的情况下测试推进B',
                    'same_run_only':True,'preserve_all_costs_and_results':True,'run_id':BOUNDARY['run_id'],
                    **{k:False for k in ('new_B_start','reset_time','change_model','change_production_decisions','increase_limits')}}
        self.value={'schema':source_revision.SCHEMA,'registration_sha256':digest(self.reg),
                    'base_amendment_sha256':digest(self.base),
                    'previous_source_revision':self.ref(LIVE/'source_revision_5.json'),
                    'base_source_sha256':self.previous['active_fingerprint_sha256'],
                    'repairs':source_revision.FACT_REPAIR,'boundary':self.ref(OUT/'boundary.json')}
        self.sync()
    def ref(self,path):return {'path':str(path),'sha256':sha_bytes(path.read_bytes())}
    def sync(self):
        grant=self.root/'grant.json';grant.write_bytes(encode(self.grant))
        tests=self.root/'test-only-proof.json';tests.write_bytes(encode({'test_only':True,'all_pass':True,
            'source_unchanged':True,'fingerprint_sha256':self.fp['sha256'],'remote_model_calls':0}))
        report=self.root/'test-only-report.json';report.write_bytes(encode({'test_only':True,'fingerprint':self.fp,
            'gates':{g:'pass' for g in ('G0','G1','G2','G3','G4')},'test_evidence':self.ref(tests)}))
        self.value.update(active_fingerprint_sha256=self.fp['sha256'],engineering_report=self.ref(report),
                          user_authorization=self.ref(grant))

    def test_T20_T23_sixth_is_presentation_only_and_cannot_authorize_seventh(self):
        source_revision.validate(self.value,self.reg,self.base)
        self.assertEqual(len(source_revision.revision_chain(self.value)),6)
        prior=strict_json(Path(self.previous['engineering_report']['path']).read_bytes())['fingerprint']
        changed={p for p in prior['files'].keys()|self.fp['files'].keys() if prior['files'].get(p)!=self.fp['files'].get(p)}
        self.assertEqual(changed,source_revision.FACT_FILES)
        sixth=self.root/'sixth.json';sixth.write_bytes(encode(self.value))
        with self.assertRaisesRegex(HarnessError,'source_revision_chain'):
            source_revision.validate({**self.value,'previous_source_revision':self.ref(sixth)},self.reg,self.base)
        with self.assertRaisesRegex(HarnessError,'source_revision_chain'):
            source_revision.validate({**self.value,'previous_source_revision':self.previous['previous_source_revision']},self.reg,self.base)
        with self.assertRaises(HarnessError):
            source_revision.validate({**self.value,'repairs':wall_budget.RUNWAY_REPAIR},self.reg,self.base)

    def test_T11_T20_T23_unauthorized_production_or_budget_source_and_grants_rejected(self):
        original=deepcopy(self.fp)
        for name in ('src/smt_fullfab/harness/factory.py','src/smt_fullfab/harness/wall_budget.py'):
            self.fp=deepcopy(original);self.fp['files'][name]='0'*64
            self.fp['sha256']=digest({k:v for k,v in self.fp.items() if k!='sha256'});self.sync()
            with self.assertRaisesRegex(HarnessError,'amendment_source'):source_revision.validate(self.value,self.reg,self.base)
        self.fp=original
        for name in ('increase_limits','reset_time','change_model','change_production_decisions','new_B_start'):
            self.grant[name]=True;self.sync()
            with self.assertRaisesRegex(HarnessError,'source_revision_grant'):source_revision.validate(self.value,self.reg,self.base)
            self.grant[name]=False

    def test_T20_T23_sixth_registration_requires_all_canonical_predecessors(self):
        path=LIVE/'source_revision_6.json';old_exists,old_read=Path.exists,Path.read_bytes
        selected=deepcopy(self.value)
        with patch.object(Path,'exists',lambda p:False if p==LIVE/'source_revision_7.json' else True if p==path else old_exists(p)),\
             patch.object(Path,'read_bytes',lambda p:encode(selected) if p==path else old_read(p)):
            self.assertEqual(source_revision.for_amendment(self.reg,self.base),self.value)
            copied=self.root/'copied-fifth.json';copied.write_bytes(encode(self.previous))
            selected['previous_source_revision']=self.ref(copied)
            source_revision.validate(selected,self.reg,self.base)
            with self.assertRaisesRegex(HarnessError,'source_revision_chain'):source_revision.for_amendment(self.reg,self.base)

    def test_T15_T21_T23_actual_checkpoint_install_resume_and_prompt_preserve_every_cost_and_decision(self):
        target=self.root/'run';target.mkdir();(target/'objects').mkdir();(target/'exports').mkdir()
        with sqlite3.connect(f'file:{RUN/"events.sqlite3"}?mode=ro',uri=True) as src,sqlite3.connect(target/'events.sqlite3') as dst:
            src.backup(dst);dst.execute('DELETE FROM records')
            for ns,rows in BOUNDARY['records'].items():dst.executemany('INSERT INTO records VALUES(?,?,?)',[(ns,k,r) for k,r in rows.items()])
            dst.execute('DELETE FROM events WHERE seq > ?',(BOUNDARY['event_count'],))
            dst.execute('DELETE FROM physical WHERE seq >= ?',(BOUNDARY['physical_count'],))
            dst.execute('UPDATE metadata SET value=? WHERE key=?',(encode(BOUNDARY['head']),'head'))
        for p in (RUN/'objects').iterdir():(target/'objects'/p.name).hardlink_to(p)
        shutil.copy2(RUN/'manifest.json',target/'manifest.json');(self.root/'experiment.json').write_bytes(encode(self.reg))
        manifest=strict_json((target/'manifest.json').read_bytes())
        original=source_revision.for_amendment
        from src.smt_fullfab.harness.amendment import case_directory
        def selected(reg,base):return source_revision.validate(self.value,reg,base) if digest(reg)==digest(self.reg) else original(reg,base)
        def directory(root,case):return target if Path(root).resolve() in (LIVE.resolve(),self.root.resolve()) else case_directory(root,case)
        before=source_revision.live_view(target)
        budget=wall_budget.effective_budget(manifest,before.rows('control_source_revisions'))
        with patch.object(source_revision,'for_amendment',side_effect=selected),\
             patch('src.smt_fullfab.harness.amendment.case_directory',side_effect=directory),\
             patch.object(experiment,'experiment_lock',return_value=nullcontext()),\
             patch('src.smt_fullfab.harness.transport.call',side_effect=AssertionError('No RPC in offline validation')):
            marker=source_revision.install(self.root);self.assertEqual(marker['new_model_calls'],0)
            view=source_revision.live_view(target);source_revision.validate_marker(view,self.reg,self.base,required=True)
            self.assertEqual(len(view.rows('control_source_revisions')),6)
            self.assertEqual(wall_budget.effective_budget(manifest,view.rows('control_source_revisions')),budget)
            with self.assertRaises(HarnessError):source_revision.install(self.root)
            runtime=Runtime.resume_run(target)
            try:
                self.assertEqual(runtime.manifest,manifest)
                self.assertEqual(runtime.head,{**BOUNDARY['head'],'segment':BOUNDARY['head']['segment']+1})
                usage=runtime.usage()
                self.assertEqual((usage['actual_model_attempts'],usage['unknown_usage'],usage['input_tokens']+usage['output_tokens']),
                                 (384,4,14938774))
                self.assertEqual(len(runtime.store.rows('commits')),114)
                text=prompt(runtime);self.assertLessEqual(len(text),120000)
                frame=strict_json(text[len(PROTOCOL_TEXT+INSTRUCTIONS)+1:])
                self.assertEqual(frame['same_context_fact_memory']['fact_count'],727)
                self.assertTrue(frame['same_context_fact_memory']['all_known_field_values_inline'])
                self.assertEqual(runtime.head,{**BOUNDARY['head'],'segment':BOUNDARY['head']['segment']+1})
                for key,value in usage.items():
                    if key!='elapsed_wall_seconds':self.assertEqual(runtime.usage()[key],value)
                after=source_revision.live_view(target);source_revision._check_prefix(after,BOUNDARY)
                self.assertEqual(len(after.value['physical']),BOUNDARY['physical_count'])
                self.assertEqual(len(after.value['events']),BOUNDARY['event_count']+2)
                self.assertEqual([e['kind'] for e in after.value['events'][-2:]],['control_source_revised','resumed'])
            finally:runtime.close()

if __name__=='__main__':unittest.main()
