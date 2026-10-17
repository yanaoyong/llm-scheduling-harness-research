"""Live admission/cutoff checks without model or network calls."""
import tempfile
import unittest
from pathlib import Path
from src.smt_fullfab.harness import capacity_pilot as p
from src.smt_fullfab.harness.capacity_config import experiment_config
from src.smt_fullfab.harness.contracts import ROOT, digest, encode, HarnessError
from src.smt_fullfab.harness.offline_isolation import authorize_model

class LiveAdmissionTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'live_pilots').mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'live_pilots')
        self.root=Path(self.tmp.name); self.cfg=experiment_config('G1')
        self.cfg['capacity_experiment']['model_calls_enabled']=True
        self.reg={'schema':p.SCHEMA,'user_instruction':p.INSTRUCTION,'model_calls_authorized':True,
                  'experiment_directory':str(self.root),'groups':['G1','G2'],
                  'config_sha256':{'G1':digest(self.cfg)},'evaluation_end':822,
                  'cli_binary':'unused','cli_sha256':'unused','model_catalog':str(self.root/'catalog.json'),
                  'model_catalog_sha256':'unused','fingerprint_sha256':'frozen',
                  'initial_state_sha256':digest({'t':702,'horizon':3600}), 'initial_trace_sha256':digest([])}
        (self.root/'registration.json').write_bytes(encode(self.reg))
        self.ad={'schema':p.SCHEMA,'group':'G1','experiment_directory':str(self.root),'experiment_sha256':digest(self.reg),
                 **{k:self.reg[k] for k in ('cli_binary','cli_sha256','model_catalog','model_catalog_sha256')}}
    def tearDown(self):self.tmp.cleanup()
    def test_flag_alone_is_not_authority(self):
        with self.assertRaises(HarnessError):authorize_model(self.cfg,None)
    def test_frozen_config_and_registration(self):
        authorize_model(self.cfg,self.ad)
        self.cfg['limits']['attempts']+=1
        with self.assertRaises(HarnessError):authorize_model(self.cfg,self.ad)
    def test_registration_tamper_rejected(self):
        self.reg['evaluation_end']=1000
        (self.root/'registration.json').write_bytes(encode(self.reg))
        with self.assertRaises(HarnessError):authorize_model(self.cfg,self.ad)
    def test_saved_state_and_source_are_bound(self):
        initial={'state':{'t':702,'horizon':3600},'trace':[]}
        p.validate_admission(self.ad,{'sha256':'frozen'},self.cfg,initial)
        initial['state']['t']=703
        with self.assertRaises(HarnessError):p.validate_admission(self.ad,{'sha256':'frozen'},self.cfg,initial)
    def test_cutoff_preserves_original_horizon_and_offline_default(self):
        self.assertEqual(p.evaluation_end({'admission':self.ad},3600),822)
        self.assertEqual(p.evaluation_end({'admission':None},3600),3600)
        cfg=experiment_config('G1')
        with self.assertRaises(HarnessError):authorize_model(cfg,self.ad)

    def test_current_instruction_has_separate_bound_authorization(self):
        self.reg['user_instruction']=p.FORECAST_COLLECTION_INSTRUCTION
        (self.root/'registration.json').write_bytes(encode(self.reg))
        self.ad['experiment_sha256']=digest(self.reg)
        authorize_model(self.cfg,self.ad)

    def test_live_pilot_exposes_reviews_on_existing_apply_action(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        saved={}
        class Store:
            def rows(self,kind):
                return [('checked',{'context_ref':'current'})] if kind=='candidates' else []
            def transaction(self):
                from contextlib import nullcontext
                return nullcontext()
            def record(self,*args):pass
        def reserve(text,schema):
            saved['schema']=schema
            return 'attempt'
        runtime=SimpleNamespace(config=self.cfg,head={'context_ref':'current'},store=Store(),
                                reserve_attempt=reserve,last_capacity_measurement={})
        with patch.object(p,'check_budget'), patch('src.smt_fullfab.harness.transport.prompt',return_value='offline'):
            p.prepare_request(runtime)
        actions=saved['schema']['properties']['action']['anyOf']
        reviews=[a for a in actions if 'machine_reviews' in a['properties']]
        self.assertTrue(reviews)
        self.assertTrue(all(a['properties']['tool']['enum']==['apply_candidate'] for a in reviews))
