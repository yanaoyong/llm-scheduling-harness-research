"""Lossless facts, actual hard-fragment queries, and retained recovery costs."""
from copy import deepcopy
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zlib

from src.smt_fullfab.harness.contracts import ROOT, PROTOCOL, HarnessError, encode, sha_bytes, strict_json
from src.smt_fullfab.harness.presentation import pack, unpack
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.transport import prompt
from src.smt_fullfab.harness.experiment import sealed_prior, resource_status, continuation_authorization, PRESENTATION_TIME_CAPS, PRESENTATION_EXECUTION_ORDER


def ref(p): return {'path':str(p), 'sha256':sha_bytes(p.read_bytes())}


class LosslessPresentationTests(unittest.TestCase):
    def test_T11_T12_roundtrip_types_absence_order_and_marker_collisions(self):
        values=[False, 0, 0.0, None, {}, [], {'x':None}, {'_record_table':'lossless-v1','columns':[],'constants':[],'rows':[],'record_count':0}, {'_literal_object':[['x',1]]}]
        rows=[{'id':str(i),'nested':{'same':'constant'*50,'value':v},'array':[v,None],'empty':{}} for i,v in enumerate(values*20)]
        for value in [rows, {'rows':rows}, [{'x':1},{'y':1}], [False,0,0.0], *values]:
            self.assertEqual(encode(unpack(pack(value))),encode(value))
        uniform=[{'id':str(i),'nested':{'same':'constant'*50,'value':i}} for i in range(100)]
        self.assertLess(len(encode(pack(uniform))),len(encode(uniform)))
        encoded=pack(rows)
        self.assertEqual([r['id'] for r in unpack(encoded)],[r['id'] for r in rows])

    def test_T12_T14_every_retained_real_feedback_has_exact_roundtrip(self):
        roots=ROOT/'artifacts/harness_p5_v1_9_release/runs'
        tested=0
        for p in sorted(roots.glob('micro-*')):
            with sqlite3.connect(f'file:{p}/events.sqlite3?mode=ro',uri=True) as db:
                refs=[r[0] for r in db.execute("SELECT ref FROM records WHERE namespace='attempts'")]
            for key in refs:
                a=strict_json(zlib.decompress((p/'objects'/(key+'.z')).read_bytes()))
                if 'response_ref' not in a:continue
                raw=strict_json(zlib.decompress((p/'objects'/(a['response_ref']+'.z')).read_bytes()))
                packed=pack(raw);self.assertEqual(encode(unpack(packed)),encode(raw));tested+=1
                if p.name=='micro-11' and a['index']==1:
                    self.assertGreater(len(encode(raw)),160000);self.assertLess(len(encode(packed)),45000)
        self.assertEqual(tested,42)

    def test_T11_T14_hard_fragment_complete_query_fits_without_reread(self):
        release=ROOT/'artifacts/harness_p5_v1_9_release';case='micro-11'
        config=strict_json((release/(case+'.config.json')).read_bytes());config['protocol_version']=PROTOCOL
        initial=strict_json(zlib.decompress((release/(case+'.initial.json.z')).read_bytes()))
        with tempfile.TemporaryDirectory() as d:
            r=Runtime.start_new(Path(d)/'run',config,experiment_id='offline-exact-hard-fragment',initial=initial)
            try:
                old=release/'runs'/case
                with sqlite3.connect(f'file:{old}/events.sqlite3?mode=ro',uri=True) as db:
                    aa=[strict_json(zlib.decompress((old/'objects'/(x[0]+'.z')).read_bytes())) for x in db.execute("SELECT ref FROM records WHERE namespace='attempts'")]
                for a in sorted(aa,key=lambda x:x['index'])[:2]:
                    raw=strict_json(zlib.decompress((old/'objects'/(a['raw_ref']+'.z')).read_bytes()))
                    action=deepcopy(raw.get('action',raw));action['context_ref']=r.head['context_ref'];last=r.record_output(action)
                text=prompt(r);frame=strict_json(text[text.index('\n{')+1:]);decoded=unpack(frame)
                self.assertEqual(encode(decoded['last_tool_feedback']),encode(last))
                self.assertNotIn('preview_complete',frame['last_tool_feedback'])
                self.assertEqual(frame['interaction_history']['entries'][-1]['result_inline_at'],'last_tool_feedback')
                self.assertNotIn('result',frame['interaction_history']['entries'][-1])
                self.assertIsInstance(decoded['context']['pending_tasks'],list)
                self.assertLessEqual(len(text),config['limits']['context_chars'])
                self.assertFalse(r.store.rows('commits'))
            finally:r.close()

    def test_T01_T23_prior_bounded_unknown_carry_requires_original_proofs_and_finite_grant(self):
        out=ROOT/'artifacts/harness_v1_10_offline';value={'authorization':ref(out/'authorization.json'),'prior_cost_evidence':ref(out/'prior_cost_evidence.json')}
        recovered={};usage,starts,ids=sealed_prior(value,recovered=recovered)
        self.assertEqual((usage['combined']['attempts'],usage['combined']['tokens'],usage['combined']['unknown_usage'],starts,len(ids),len(recovered)),(122,4642089,5,0,26,2))
        disclosure=resource_status(value,usage);self.assertEqual(disclosure['unexempt_unknown_usage']['combined'],0);self.assertFalse(disclosure['cumulative_cost_closed'])
        self.assertEqual(disclosure['authorized_prior_bounded_unknown_usage']['combined'],2)
        with patch('src.smt_fullfab.harness.recovery.validate_recoveries',return_value={}):
            # The live cohort still reconstructs the original proofs, so the
            # fabricated empty sealed result must fail the cross-check first.
            with self.assertRaisesRegex(HarnessError,'carry_live_change'):sealed_prior(value)
        grant=continuation_authorization(value['authorization']);self.assertEqual(grant['caps'],PRESENTATION_TIME_CAPS)
        self.assertEqual(PRESENTATION_EXECUTION_ORDER[:11],[f'micro-{i:02d}' for i in [8,11,*range(12,21)]]);self.assertEqual(sorted(PRESENTATION_EXECUTION_ORDER),[f'micro-{i:02d}' for i in range(1,21)])
        with tempfile.TemporaryDirectory() as d:
            for change in ['budget','order']:
                bad=deepcopy(grant)
                if change=='budget':bad['caps']['micro']['model_seconds']+=1
                else:bad['micro_execution_order']=bad['micro_execution_order'][:-1]
                p=Path(d)/(change+'.json');p.write_bytes(encode(bad))
                with self.assertRaises(HarnessError):continuation_authorization(ref(p))


if __name__=='__main__':unittest.main()
