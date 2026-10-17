"""Replay the observed excess-read triggers; never generate new model outputs."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import zlib

from src.smt_fullfab.harness.contracts import ROOT, PROTOCOL, HarnessError, encode, strict_json
from src.smt_fullfab.harness.presentation import pack,unpack
from src.smt_fullfab.harness.facts import FactReader,build_facts
from src.smt_fullfab.harness.recovery import LiveEvidence
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.transport import prompt


class FeedbackFixTests(unittest.TestCase):
    def test_T11_T12_heterogeneous_layout_preserves_absence_types_and_collisions(self):
        variants=[{'x':None},{'x':False},{'x':0},{'x':0.0},{'x':{'nested':2}}, {'y':{}}, {'y':[]},
                  {'_record_table':'lossless-v2','layouts':[],'constants':[],'rows':[],'record_count':0}, {'_literal_object':[['x',1]]}]
        rows=[{'id':str(i),'same':'stable'*80,'value':deepcopy(v)} for i,v in enumerate(variants*30)]
        encoded=pack(rows)
        self.assertEqual(encoded['_record_table'],'lossless-v2')
        self.assertEqual(encode(unpack(encoded)),encode(rows))
        self.assertLess(len(encode(encoded)),len(encode(rows)))

    def test_T11_missing_ID_does_not_discard_requested_valid_ID_or_infer_completion(self):
        facts=build_facts({'machines':[],'operations':[{'operation_id':'valid2','x':None},{'operation_id':'valid1','x':False}]},{'tasks':[],'holds':[]})
        reader=FactReader('context',facts)
        result=reader.read({'kind':'operations','ids':['valid1','missing','valid2']})
        self.assertEqual([x['id'] for x in result['entities']],['valid1','valid2'])
        self.assertEqual([x['value'] for x in result['entities']],[{'operation_id':'valid1','x':False},{'operation_id':'valid2','x':None}])
        self.assertEqual(result['status'],'partial');self.assertFalse(result['complete_requested_slice'])
        self.assertEqual(result['missing_entities'],[{'kind':'operations','id':'missing','code':'entity_missing','context_ref':'context','meaning':'absent_from_current_catalog_only'}])
        with self.assertRaises(HarnessError):reader.read({'kind':'operations','ids':['valid1','valid1']})
        all_missing=reader.read({'kind':'operations','ids':['missing']})
        self.assertEqual(all_missing['entities'],[]);self.assertEqual(all_missing['returned'],0)
        self.assertEqual(reader.read({'kind':'operations','ids':['valid1']})['status'],'ok')

    def test_T12_T14_real_163_operation_reply_fits_complete_prompt_without_extra_read(self):
        root=ROOT/'artifacts/harness_p5_sol_release';original=LiveEvidence(root/'continuations/micro-20-limit30')
        attempt=next(a for a in original.rows('attempts').values() if a['index']==1)
        action=deepcopy(original.get(attempt['raw_ref'])['action'])
        cfg=strict_json((root/'micro-20.config.json').read_bytes());cfg['protocol_version']=PROTOCOL
        initial=strict_json(zlib.decompress((root/'micro-20.initial.json.z').read_bytes()))
        with tempfile.TemporaryDirectory() as d:
            r=Runtime.start_new(Path(d)/'run',cfg,experiment_id='offline-saved-micro20-read',initial=initial)
            try:
                action['context_ref']=r.head['context_ref'];result=r.record_output(action)
                self.assertEqual(result['results'][1]['returned'],163)
                text=prompt(r);frame=strict_json(text[text.index('\n{')+1:])
                self.assertEqual(encode(unpack(frame['last_tool_feedback'])),encode(result))
                self.assertNotIn('preview_complete',frame['last_tool_feedback'])
                self.assertLessEqual(len(text),cfg['limits']['context_chars'])
                self.assertIsInstance(unpack(frame)['context']['pending_tasks'],list)
                self.assertEqual(len(r.store.rows('attempts')),1)
                self.assertEqual(r.usage()['actual_model_attempts'],0)
                self.assertFalse(r.store.rows('commits'))
            finally:r.close()

    def test_T11_real_mixed_query_keeps_the_valid_operation_in_its_first_reply(self):
        root=ROOT/'artifacts/harness_p5_sol_release';view=LiveEvidence(root/'runs/micro-08')
        a=next(a for a in view.rows('attempts').values() if a['index']==0)
        action=deepcopy(view.get(a['raw_ref'])['action']);ctx=view.rows('contexts')[a['context_ref']]
        facts=build_facts(ctx['problem'],ctx['base_plan']);reader=FactReader(a['context_ref'],facts)
        result=reader.read(action['queries'][0])
        self.assertEqual(result['status'],'partial')
        self.assertEqual([e['id'] for e in result['entities']],['w738:43:1'])
        self.assertEqual([e['id'] for e in result['missing_entities']],['w2086:133:1'])
        self.assertEqual(result['entities'][0],reader.read({'kind':'operations','ids':['w738:43:1']})['entities'][0])

    def test_T22_P95_stops_before_second_sixth_call(self):
        from src.smt_fullfab.harness.p5 import micro
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'runs/micro-14';p.mkdir(parents=True)
            (p/'fragment_result.json').write_bytes(encode({'id':'micro-14','attempts':6,'accepted':True}))
            cases={f'micro-{i:02d}':{'group':'micro'} for i in range(1,21)};cases['B3600']={'group':'B3600'}
            caps={g:{'attempts':100,'tokens':10000,'model_seconds':1000,'wall_seconds':1000} for g in ('micro','B3600','combined')}
            reg={'schema':'offline_test','cases':cases,'execution_order':['micro-20'],'caps':caps,
                 'cli_binary':'unused','cli_sha256':'unused','model_catalog':'unused','model_catalog_sha256':'unused'}
            (root/'experiment.json').write_bytes(encode(reg));(root/'runs/micro-20').mkdir()
            head={'phase':'OBSERVED'}
            def stop(reason):head.update(phase='STOPPED',stop_reason=reason)
            r=SimpleNamespace(head=head,store=SimpleNamespace(rows=lambda name:[]),usage=lambda:{'actual_model_attempts':5,'unknown_usage':0},stop=stop,close=lambda:None)
            usage={g:{**{k:0 for k in caps[g]},'pending':0} for g in caps}
            with patch('src.smt_fullfab.harness.p5.open_case',return_value=r),patch('src.smt_fullfab.harness.transport.call') as call,patch('src.smt_fullfab.harness.p5.seal_evidence',return_value='retained'),patch('src.smt_fullfab.harness.p5.audit_run',return_value={'valid':False,'errors':['unfinished']}),patch('src.smt_fullfab.harness.p5.cumulative_usage',return_value=usage),patch('src.smt_fullfab.harness.p5.resource_status',return_value={'unexempt_unknown_usage':{g:0 for g in caps}}):
                gate=micro(root)
            call.assert_not_called();self.assertFalse(gate['pass'])
            self.assertEqual(head['stop_reason'],'registered_P95_impossible_before_next_call')
            self.assertEqual(strict_json((root/'runs/micro-20/fragment_result.json').read_bytes())['attempts'],5)


if __name__=='__main__':unittest.main()
