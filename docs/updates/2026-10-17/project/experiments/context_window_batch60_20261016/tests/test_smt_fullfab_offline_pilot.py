"""Frozen-source launcher tests using only a tiny synthetic runner, no simulation."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab import offline_pilot as pilot

FAKE_RUNNER='''# TEST FIXTURE ONLY: writes synthetic records, never runs a simulation.
import argparse,hashlib,json,pathlib,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[2]
MODE="success"
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x))
p=argparse.ArgumentParser()
for k in ['arm','run_id','solver_method']:p.add_argument('--'+k.replace('_','-'),required=True)
for k in ['seconds','seed','max_plans','plan_seconds','period_seconds','lookahead_depth','max_slots','max_log_bytes','max_candidate_evaluations']:p.add_argument('--'+k.replace('_','-'),type=int,required=True)
for k in ['wall_seconds','solver_seconds','solver_budget_seconds','constructor_seconds']:p.add_argument('--'+k.replace('_','-'),type=float,required=True)
cfg=vars(p.parse_args());cfg['snapshot_path']=None
out=ROOT/'runs/smt_fullfab_development'/cfg['run_id'];out.mkdir(parents=True)
sources={}
for base in ['src/smt_fullfab','src/smt']:
 for path in sorted((ROOT/base).glob('*.py')):
  rel=path.relative_to(ROOT);dest=out/'source_snapshot'/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(path.read_bytes());sources[str(rel)]=sha(path)
dest=out/'source_snapshot/src/__init__.py';dest.write_bytes((ROOT/'src/__init__.py').read_bytes())
prov={'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'source_sha256':sources,'requirements_sha256':sha(ROOT/'requirements.lock')}
write(out/'config.json',cfg);write(out/'provenance.json',prov)
valid=MODE=='success'
write(out/'audit.json',{'valid':valid,'fixture':'not-a-simulation'})
write(out/'trace.jsonl',{'kind':'initial','manifest':{'data_hashes':{p.name:sha(p) for p in (ROOT/'data/smt/SMT2020_LVHM').iterdir() if p.is_file()}},'fixture':'not-a-simulation'})
result={'config':cfg,'identity':hashlib.sha256(json.dumps(cfg,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'provenance':prov,'model_calls':0,'solver_calls':0,'status':MODE,'failure':None if valid else 'synthetic-failure','full_window_completed':valid,'simulation_seconds':cfg['seconds'] if valid else 0,'audit_valid':valid,'metrics':{'fixture':'not-a-simulation'}}
write(out/'result.json',result)
raise SystemExit(0 if valid else 1)
'''


class OfflinePilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        for relative in ['src/smt_fullfab','src/smt',pilot.DATA,pilot.VENDOR,'configs/smt_fullfab']:
            (self.root/relative).mkdir(parents=True)
        for relative in ['src/__init__.py','src/smt/__init__.py','src/smt_fullfab/__init__.py']:
            (self.root/relative).write_text('')
        (self.root/'src/smt_fullfab/runner.py').write_text(FAKE_RUNNER)
        (self.root/'src/smt_fullfab/offline_pilot.py').write_bytes(Path(pilot.__file__).read_bytes())
        (self.root/pilot.DATA/'input.txt').write_text('synthetic-data-only\n')
        (self.root/pilot.VENDOR/'read.py').write_text('# synthetic vendor\n')
        (self.root/'requirements.lock').write_text('# synthetic lock\n')
        self.prereg=json.loads((pilot.ROOT/pilot.PREREG).read_text())
        (self.root/pilot.PREREG).write_text(json.dumps(self.prereg))
        pilot._git_pointer(self.root,'1'*40)

    def prepare(self):return pilot.prepare(root=self.root,campaign_id='fixture')

    def test_prepare_freezes_inputs_matrix_and_origin_without_running(self):
        with patch.object(pilot,'_launch',side_effect=AssertionError('no execution during preparation')):
            campaign,manifest=self.prepare()
        self.assertEqual(len(manifest['configs']),10)
        self.assertEqual(manifest['origin_git_head'],'1'*40)
        self.assertEqual(pilot._origin_git(campaign/'frozen'),'1'*40)
        self.assertFalse(Path(manifest['output_root']).exists())
        self.assertEqual(manifest['configs'][0]['run_id'],'ref_cr_1702_8h_discrimination_v1')
        self.assertEqual(manifest['configs'][-1]['run_id'],'ref_fifo_1706_8h_discrimination_v1')
        for row in manifest['configs']:
            self.assertEqual((row['wall_seconds'],row['max_log_bytes'],row['max_plans']),(180,536870912,20000))
        again,loaded=self.prepare();self.assertEqual(again,campaign);self.assertEqual(loaded,manifest)

    def test_frozen_execution_serial_ten_outcomes_and_verified_skip(self):
        campaign,manifest=self.prepare()
        (self.root/'src/smt_fullfab/runner.py').write_text('raise RuntimeError("LIVE SOURCE MUST NOT RUN")')
        (self.root/pilot.DATA/'input.txt').write_text('changed live data must not be used')
        real=pilot._launch;order=[]
        def tracked(command,frozen,attempt,timeout):
            order.append(command[command.index('--run-id')+1]);return real(command,frozen,attempt,timeout)
        with patch.object(pilot,'_launch',tracked):result=pilot.execute(campaign,manifest)
        self.assertEqual(result['status'],'complete');self.assertEqual(result['not_run'],[])
        self.assertEqual(order,[c['run_id'] for c in manifest['configs']])
        self.assertEqual(len(result['records']),10)
        self.assertTrue(all(r['mode']=='executed' for r in result['records']))
        with patch.object(pilot,'_launch',side_effect=AssertionError('completed outcomes must never rerun')):
            resumed=pilot.execute(campaign,json.loads((campaign/'manifest.json').read_text()))
        self.assertEqual(resumed['status'],'complete');self.assertTrue(all(r['mode']=='SKIP' for r in resumed['records']))
        self.assertEqual(len(list((campaign/'records').glob('*/attempt.json'))),10)

    def test_failed_outcome_stops_and_is_never_retried(self):
        (self.root/'src/smt_fullfab/runner.py').write_text(FAKE_RUNNER.replace('MODE="success"','MODE="failed"'))
        campaign,manifest=self.prepare();result=pilot.execute(campaign,manifest)
        self.assertEqual(result['status'],'stopped_failure');self.assertEqual(len(result['not_run']),9)
        first=result['records'][0];self.assertEqual(first['runner_failure'],'synthetic-failure')
        with patch.object(pilot,'_launch',side_effect=AssertionError('no retries')):
            again=pilot.execute(campaign,manifest)
        self.assertEqual(again['status'],'stopped_prior_failure')
        self.assertEqual(len(list((campaign/'records').glob('*/attempt.json'))),1)

    def test_watchdog_timeout_has_machine_readable_failure_and_not_run(self):
        campaign,manifest=self.prepare()
        with patch.object(pilot,'_launch',return_value={'returncode':-9,'timed_out':True,'wall_seconds':180.01,'pid':999999}):
            result=pilot.execute(campaign,manifest)
        self.assertEqual(result['status'],'stopped_failure');self.assertEqual(len(result['not_run']),9)
        outcome=json.loads((campaign/'records/00/outcome.json').read_text())
        self.assertTrue(outcome['process']['timed_out']);self.assertFalse(outcome['audit_valid'])
        self.assertFalse(outcome['runner_result_present'])
        self.assertFalse((Path(manifest['output_root'])/manifest['configs'][0]['run_id']/'result.json').exists())

    def test_real_watchdog_only_kills_a_sleeping_synthetic_process(self):
        attempt=self.root/'sleep-test';attempt.mkdir()
        result=pilot._launch([sys.executable,'-c','import time;time.sleep(5)'],self.root,attempt,.02)
        self.assertTrue(result['timed_out']);self.assertLess(result['wall_seconds'],2)

    def test_frozen_tamper_and_runtime_changes_rejected(self):
        campaign,manifest=self.prepare()
        path=campaign/'frozen'/pilot.DATA/'input.txt';path.chmod(0o644);path.write_text('tampered')
        with self.assertRaisesRegex(ValueError,'source/data changed'):pilot.verify_frozen(campaign,manifest)
        path.write_bytes((self.root/pilot.DATA/'input.txt').read_bytes())
        with patch.object(pilot,'_runtime',return_value={}):
            with self.assertRaisesRegex(ValueError,'environment differs'):pilot.verify_frozen(campaign,manifest)

    def test_existing_configuration_or_evidence_mismatch_not_skipped(self):
        campaign,manifest=self.prepare();self.assertEqual(pilot.execute(campaign,manifest)['status'],'complete')
        run=Path(manifest['output_root'])/manifest['configs'][0]['run_id']
        data=json.loads((run/'config.json').read_text());data['seed']=999;(run/'config.json').write_text(json.dumps(data))
        with patch.object(pilot,'_launch',side_effect=AssertionError('must not overwrite mismatch')):
            result=pilot.execute(campaign,manifest)
        self.assertEqual(result['status'],'stopped_evidence_mismatch')
        self.assertEqual(json.loads((run/'config.json').read_text())['seed'],999)

    def test_interrupted_attempt_and_incomplete_run_retained(self):
        campaign,manifest=self.prepare();pilot._write(campaign/'records/00/attempt.json',{'interrupted':True})
        with patch.object(pilot,'_launch',side_effect=AssertionError('no implicit retry')):
            result=pilot.execute(campaign,manifest)
        self.assertEqual(result['status'],'stopped_failure')
        self.assertIn('interrupted attempt',result['records'][0]['failure'])

    def test_active_run_guard_and_exclusive_launcher_lock(self):
        import os
        campaign,manifest=self.prepare()
        claim=self.root/'runs/smt_fullfab_stage2/fixture_active/claim.json';pilot._write(claim,{'pid':os.getpid()})
        with patch.object(pilot,'_launch',side_effect=AssertionError('active run blocks launch')):
            result=pilot.execute(campaign,manifest)
        self.assertEqual(result['status'],'blocked_active_runs');self.assertEqual(len(result['not_run']),10)
        with pilot._serial_lock(self.root):
            with self.assertRaisesRegex(RuntimeError,'serial lock'):
                with pilot._serial_lock(self.root):pass

    def test_preregistration_drift_and_freeze_race_fail_closed(self):
        bad=deepcopy(self.prereg);bad['reference_discrimination_8h']['seeds'][0]=1
        with self.assertRaises(ValueError):pilot._configs(bad)
        original=pilot._inventory;calls=0
        def changing(root):
            nonlocal calls
            calls+=1
            if calls==2:(self.root/pilot.DATA/'input.txt').write_text('changed-during-freeze')
            return original(root)
        with patch.object(pilot,'_inventory',changing):
            with self.assertRaisesRegex(ValueError,'changed during freeze'):self.prepare()
        campaign=self.root/'runs/smt_fullfab_offline_pilot/fixture'
        self.assertTrue((campaign/'freeze_failure.json').exists());self.assertFalse((campaign/'manifest.json').exists())


if __name__=='__main__':unittest.main()
