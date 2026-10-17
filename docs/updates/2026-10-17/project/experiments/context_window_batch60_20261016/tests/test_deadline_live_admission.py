"""Current bounded three-group authorization, tested without network/model calls."""
import tempfile
import unittest
from pathlib import Path
from src.smt_fullfab.harness import capacity_pilot as p
from src.smt_fullfab.harness.capacity_config import deadline_config
from src.smt_fullfab.harness.contracts import ROOT, digest, encode, HarnessError
from src.smt_fullfab.harness.offline_isolation import authorize_model


class DeadlineAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'live_pilots');self.root=Path(self.tmp.name)
        self.configs={g:deadline_config(g) for g in ('G0','G1','G2')}
        for cfg in self.configs.values():
            cfg['capacity_experiment']['model_calls_enabled']=True;cfg['limits']['attempts']=8
        self.reg={'schema':p.SCHEMA,'user_instruction':p.DEADLINE_INSTRUCTION,'model_calls_authorized':True,
            'experiment_directory':str(self.root),'groups':['G0','G1','G2'],'per_group_call_cap':8,
            'model_calls_maximum_total':24,'evaluation_end':882,
            'config_sha256':{g:digest(c) for g,c in self.configs.items()},
            'cli_binary':'unused','cli_sha256':'unused','model_catalog':str(self.root/'catalog.json'),
            'model_catalog_sha256':'unused','fingerprint_sha256':'frozen',
            'initial_state_sha256':digest({'t':702,'horizon':3600}),'initial_trace_sha256':digest([])}
    def tearDown(self):self.tmp.cleanup()
    def admission(self,g):
        (self.root/'registration.json').write_bytes(encode(self.reg))
        return {'schema':p.SCHEMA,'group':g,'experiment_directory':str(self.root),'experiment_sha256':digest(self.reg),
                **{k:self.reg[k] for k in ('cli_binary','cli_sha256','model_catalog','model_catalog_sha256')}}
    def test_all_three_current_groups_are_authorized_and_bound(self):
        for g,cfg in self.configs.items():
            ad=self.admission(g);authorize_model(cfg,ad)
            p.validate_admission(ad,{'sha256':'frozen'},cfg,{'state':{'t':702,'horizon':3600},'trace':[]})
    def test_old_two_group_instruction_cannot_authorize_deadline_policy(self):
        self.reg.update(user_instruction=p.FORECAST_COLLECTION_INSTRUCTION,groups=['G1','G2'])
        with self.assertRaises(HarnessError):authorize_model(self.configs['G1'],self.admission('G1'))
    def test_original_group_cannot_silently_use_new_execution(self):
        cfg=self.configs['G0'];cfg['capacity_experiment']['execution_rule']='deadline'
        self.reg['config_sha256']['G0']=digest(cfg)
        with self.assertRaises(HarnessError):authorize_model(cfg,self.admission('G0'))
    def test_cannot_extend_observation_or_call_cap(self):
        for key,value in [('evaluation_end',900),('per_group_call_cap',9),('model_calls_maximum_total',25)]:
            old=self.reg[key];self.reg[key]=value
            with self.assertRaises(HarnessError):authorize_model(self.configs['G1'],self.admission('G1'))
            self.reg[key]=old
    def test_model_flag_and_current_config_remain_required(self):
        ad=self.admission('G2');cfg=self.configs['G2'];cfg['capacity_experiment']['model_calls_enabled']=False
        with self.assertRaises(HarnessError):authorize_model(cfg,ad)
    def test_no_model_or_cli_run_in_offline_admission_checks(self):
        from scripts import run_deadline_three_group_pilot as runner
        from scripts import run_forecast_collection_pilot as prior
        self.assertEqual(runner.TASK,prior.TASK)
        self.assertEqual((runner.MAX_CALLS,runner.EVALUATION_END),(8,882))
