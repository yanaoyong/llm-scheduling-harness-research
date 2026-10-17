import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab.constructor_audit import audit_and_record_constructive
from src.smt_fullfab.status import constructive_acceptance


class ConstructiveAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='smt_fullfab_acceptance_');self.addCleanup(self.temp.cleanup)
        self.run=Path(self.temp.name).resolve();self.ledger=self.run.parent/(self.run.name+'_ledger.jsonl')
        self.ledger.write_text('{"event":"approval"}\n');self.addCleanup(self.ledger.unlink)
        self.result={'config':{'arm':'C','enable_constructive':True},'status':'success','audit_valid':True,'full_window_completed':True,'wall_seconds':1}
        self.write('result.json',self.result);self.write('trace.jsonl',{'kind':'terminal'})
        self.write('resource_registration.json',{'registration_id':'original','wall_seconds':100,'max_log_bytes':100000})
        self.write('model_raw.json',{'choice':'explicit'})

    def write(self,name,value): (self.run/name).write_text(json.dumps(value)+'\n')

    def record(self,valid=True):
        with patch('src.smt_fullfab.controller_audit.audit_controller',return_value={'valid':valid,'successful_full_window':valid}):
            return audit_and_record_constructive(self.run,self.ledger)

    def test_missing_attribution_never_passes_physical_success(self):
        self.assertFalse(constructive_acceptance(self.run,self.result)['accepted'])

    def test_exact_postrun_acceptance_passes_and_records_audit_cost(self):
        result=self.record()
        self.assertGreater(result['final_wall_seconds'],1)
        self.assertTrue(constructive_acceptance(self.run,self.result)['accepted'])
        with self.assertRaises(FileExistsError):self.record()

    def test_any_bound_raw_change_rejects(self):
        self.record();self.write('model_raw.json',{'choice':'other'})
        self.assertFalse(constructive_acceptance(self.run,self.result)['accepted'])

    def test_ledger_prefix_cannot_change_but_extension_is_allowed(self):
        self.record();old=self.ledger.read_text();self.ledger.write_text(old+'{"event":"later"}\n')
        self.assertTrue(constructive_acceptance(self.run,self.result)['accepted'])
        self.ledger.write_text(old.replace('approval','mutation'))
        self.assertFalse(constructive_acceptance(self.run,self.result)['accepted'])

    def test_pending_constructor_stops_gate_even_after_saved_acceptance(self):
        self.record()
        with self.ledger.open('a') as f:f.write(json.dumps({'event':'constructor_reserve','call_id':'open','run_id':str(self.run),'registration_id':'original'})+'\n')
        self.assertFalse(constructive_acceptance(self.run,self.result)['accepted'])

    def test_other_run_pending_does_not_invalidate_sealed_acceptance(self):
        self.record()
        with self.ledger.open('a') as f:f.write(json.dumps({'event':'constructor_reserve','call_id':'other','run_id':str(self.run)+'_other','registration_id':'other'})+'\n')
        self.assertTrue(constructive_acceptance(self.run,self.result)['accepted'])

    def test_closed_new_own_activity_cannot_escape_prefix_binding(self):
        self.record()
        for kind in ('reserve','solver_reserve','constructor_reserve'):
            old=self.ledger.read_text()
            with self.ledger.open('a') as f:
                f.write(json.dumps({'event':kind,'call_id':'later','run_id':str(self.run/'model_002') if kind=='reserve' else str(self.run),'registration_id':'original'})+'\n')
                f.write(json.dumps({'event':kind.replace('reserve','finish'),'call_id':'later'})+'\n')
            with self.subTest(kind=kind):self.assertFalse(constructive_acceptance(self.run,self.result)['accepted'])
            self.ledger.write_text(old)

    def test_failed_evidence_or_resource_overrun_never_passes(self):
        self.record(valid=False);self.assertFalse(constructive_acceptance(self.run,self.result)['accepted'])
        for name in ('controller_audit.json','controller_acceptance.json'):(self.run/name).unlink()
        self.write('resource_registration.json',{'registration_id':'original','wall_seconds':.5,'max_log_bytes':100000})
        self.assertFalse(self.record()['accepted'])
        self.assertFalse(constructive_acceptance(self.run,self.result)['accepted'])


if __name__=='__main__':unittest.main()
