"""Lossless requested facts, real evicted prompts, and public-only capacity fallback."""
from copy import deepcopy
from contextlib import nullcontext
import unittest
from src.smt_fullfab.harness.contracts import ROOT, HarnessError, digest, encode, strict_json
from src.smt_fullfab.harness.fact_memory import FactMemory, INSTRUCTIONS, prompt_variants, restore_inline_values
from src.smt_fullfab.harness.presentation import unpack
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.transport import PROTOCOL_TEXT, fit_prompt, prompt
from tests.test_smt_fullfab_harness_source_revision import Projection

OUT = ROOT / 'artifacts/harness_B_fact_retention_repair_20261015'
BOUNDARY = strict_json((OUT / 'boundary.json').read_bytes())

class CheckpointProjection(Projection):
    def __init__(self):
        super().__init__()
        self.records = deepcopy(BOUNDARY['records'])
    def meta(self, key, default=None):
        return deepcopy(BOUNDARY['head'] if key == 'head' else default)


def fixture(value, *, absent=None, version='v1'):
    entity = {'kind':'machines','id':'7','original_ref':{'context_ref':'c1','kind':'machines','id':'7'},
              'entity_sha256':version,'value':deepcopy(value)}
    if absent is not None:
        entity.update(absent_fields=absent, projection_fields=list(value)+absent)
    action = {'tool':'read_entities','context_ref':'c1','queries':[{'kind':'machines','ids':['7']}]}
    result = {'status':'ok','context_ref':'c1','results':[{'entities':[entity],'total':1,'next_cursor':None}]}
    return action,result


class FactMemoryTests(unittest.TestCase):
    def test_T11_T12_projections_null_absence_and_literal_types_restore_exactly(self):
        memory = FactMemory('c1')
        values = [False,0,0.0,None,{},[],{'_record_table':'lossless-v1'}, {'_literal_object':[['x',1]]}]
        original=[]
        for i,value in enumerate(values):
            action,result=fixture({f'f{i}':value},absent=['absent'])
            memory.add(i,action,result);original.append(result)
        for i,result in enumerate(original):
            self.assertEqual(encode(memory.restore(i)),encode(result))
        inline=memory.inline('artifact:test')
        restored=restore_inline_values(inline)
        self.assertEqual(encode(restored[0]['value']),encode({f'f{i}':v for i,v in enumerate(values)}))
        self.assertEqual(inline['confirmed_absent_fields'],[{'fact_index':0,'fields':['absent']}])
        self.assertNotIn('never_requested',restored[0]['value'])

    def test_T11_T12_conflicting_values_and_absence_cannot_merge(self):
        for first,second in [(fixture({'x':False}),fixture({'x':0})),
                             (fixture({'x':0}),fixture({'x':0.0})),
                             (fixture({},absent=['x']),fixture({'x':None})),
                             (fixture({'x':None}),fixture({},absent=['x']))]:
            with self.subTest(second=second):
                memory=FactMemory('c1');memory.add(1,*first)
                with self.assertRaisesRegex(HarnessError,'fact_memory_conflict'):memory.add(2,*second)

    def test_T11_T12_context_and_immutable_version_boundaries(self):
        memory=FactMemory('c1');memory.add(1,*fixture({'x':1}))
        memory.add(2,*fixture({'x':2},version='v2'))
        self.assertEqual(len(memory.facts),2)
        action,result=fixture({'x':1});result['results'][0]['entities'][0]['original_ref']['context_ref']='other'
        with self.assertRaisesRegex(HarnessError,'fact_memory_context'):memory.add(3,action,result)
        action,result=fixture({'x':1});action['context_ref']='other'
        with self.assertRaisesRegex(HarnessError,'fact_memory'):memory.add(3,action,result)

    def test_T11_T12_shared_tables_preserve_order_and_marker_collisions(self):
        memory=FactMemory('c1');a,r=fixture({})
        r['results'][0]['entities']=[]
        for i in range(100):
            _,one=fixture({'label':'repeated'*200,'literal':{'_record_table':'lossless-v1'},'id':i})
            e=one['results'][0]['entities'][0];e['id']=e['original_ref']['id']=str(i)
            e['value']['array']=[None,'x'*200,i%2]
            r['results'][0]['entities'].append(e)
        memory.add(1,a,r);inline=memory.inline('artifact:test');restored=restore_inline_values(inline)
        self.assertTrue(inline['shared_values'])
        for i,e in enumerate(r['results'][0]['entities']):self.assertEqual(encode(restored[i]['value']),encode(e['value']))
        self.assertEqual(encode(memory.restore(0)),encode(r))

    def runtime(self):
        store=CheckpointProjection();return Runtime(store,store.read('manifest','run'),None)

    def recorded(self, call):
        runtime=self.runtime();attempts=runtime.store.rows('attempts')
        current=next(a for _,a in attempts if a['index']+1==call)
        raw=runtime.store.bytes(current['prompt_ref']).decode()
        self.assertTrue(raw.startswith(PROTOCOL_TEXT+'\n'))
        frame=strict_json(raw[len(PROTOCOL_TEXT)+1:])
        return runtime,[(k,a) for k,a in attempts if a['index']+1<call],frame,len(raw)

    def verify_full(self,runtime,attempts,view):
        full=runtime.store.get(runtime.store.read('public',view['full_memory_ref'])['object_ref'])
        decoded=restore_inline_values(view)
        self.assertEqual(encode(decoded),encode({i:{'kind':f['identity']['kind'],'id':f['identity']['id'],'value':f['value']}
                                                for i,f in enumerate(full['facts'])}))
        expected=[]
        memory=FactMemory(view['context_ref'])
        for _,a in attempts:
            if a['context_ref']!=view['context_ref'] or a['status']!='processed':continue
            action=strict_json(runtime.store.bytes(a['raw_ref']));action=action.get('action',action)
            result=runtime.store.get(a['response_ref'])
            if action.get('tool')=='read_entities' and result['status']=='ok':
                memory.add(a['index']+1,action,result);expected.append(result)
        for i,result in enumerate(expected):self.assertEqual(encode(memory.restore(i)),encode(result))
        for q in unpack(view['queries']):
            original=full['reads'][q['read_index']]['result']['results'][q['query_index']]
            metadata={**view['common_result_metadata'],**q['result_metadata']}
            if q.get('result_where_equals_request_where'):metadata['where']=q['request']['where']
            indices=view['fact_index_sets'][q['fact_index_set']] if 'fact_index_set' in q else q['fact_indices']
            self.assertEqual(metadata,{k:v for k,v in original.items() if k!='entities'})
            self.assertEqual(indices,[d['fact_index'] for d in original['entities']])
        return full

    def test_T12_T14_T20_actual_evicted_prompts_restore_all_prior_facts_without_calls(self):
        for call,count in [(370,200),(377,727),(381,727),(384,727)]:
            with self.subTest(call=call):
                runtime,attempts,frame,size=self.recorded(call)
                original=deepcopy(frame)
                variants=prompt_variants(runtime,attempts,frame,size)
                self.assertEqual(frame,original)
                if call == 370:
                    # Both exact responses are still inline: do not add redundant memory.
                    self.assertEqual(variants,[])
                    self.assertLessEqual(size,120000)
                    continue
                self.assertEqual(variants[0]['context'],frame['context'])
                rendered=fit_prompt(variants[0],PROTOCOL_TEXT+INSTRUCTIONS,120000)
                self.assertIsNotNone(rendered);self.assertLessEqual(len(rendered),120000)
                decoded=strict_json(rendered[len(PROTOCOL_TEXT+INSTRUCTIONS)+1:])
                self.assertEqual(decoded['same_context_fact_memory']['fact_count'],count)
                self.verify_full(runtime,attempts,decoded['same_context_fact_memory'])
                self.assertEqual(len(runtime.store.rows('attempts')),384)

    def test_T11_T12_public_gateway_exact_values_reuse_and_cross_run_rejection(self):
        r,attempts,frame,size=self.recorded(377)
        variants=prompt_variants(r,attempts,frame,size)
        view=variants[0]['same_context_fact_memory'];ref=view['full_memory_ref']
        action={'tool':'read_artifact','artifact_ref':ref,'path':['facts',0,'value'],'format':'value','offset':0,'count':0}
        result=r._execute(action,{'channel':'replay'})
        self.assertEqual(result['value'],restore_inline_values(view)[0]['value'])
        self.assertEqual(prompt_variants(r,attempts,frame,size)[0]['same_context_fact_memory']['full_memory_ref'],ref)
        with self.assertRaisesRegex(HarnessError,'private_or_cross_run'):r._execute({**action,'artifact_ref':BOUNDARY['head']['state_ref']},{'channel':'replay'})
        public=r.store.read('public',ref);public['run_id']='other'
        r.store.records['public'][ref]=r.store.put(public)
        with self.assertRaisesRegex(HarnessError,'private_or_cross_run'):r._execute(action,{'channel':'replay'})

    def test_T12_T20_explicit_catalog_and_reference_fallback_never_fill_missing_values(self):
        r,attempts,frame,size=self.recorded(384);full,catalog,refonly=prompt_variants(r,attempts,frame,size)
        prefix=PROTOCOL_TEXT+INSTRUCTIONS
        self.assertIsNone(fit_prompt(full,prefix,60000))
        self.assertIsNotNone(fit_prompt(catalog,prefix,60000))
        self.assertFalse(catalog['same_context_fact_memory']['all_known_field_values_inline'])
        self.assertNotIn('groups',catalog['same_context_fact_memory'])
        self.assertEqual(sum(len(g['rows']) for g in catalog['same_context_fact_memory']['catalog']),727)
        self.assertIsNone(fit_prompt(catalog,prefix,40000))
        self.assertIsNotNone(fit_prompt(refonly,prefix,40000))
        self.assertFalse(refonly['same_context_fact_memory']['queries_inline'])
        self.assertIsNone(fit_prompt(refonly,prefix,100))
        self.assertEqual(full['context'],frame['context'])

    def test_T12_T14_current_prompt_retains_727_entities_and_no_production_or_cost_writes(self):
        r=self.runtime();before=deepcopy(r.store.records)
        text=prompt(r,task='same B checkpoint');self.assertIn(INSTRUCTIONS,text)
        self.assertLessEqual(len(text),120000)
        frame=strict_json(text[len(PROTOCOL_TEXT+INSTRUCTIONS)+1:]);memory=frame['same_context_fact_memory']
        self.assertTrue(memory['all_known_field_values_inline']);self.assertEqual(memory['fact_count'],727)
        full=self.verify_full(r,r.store.rows('attempts'),memory)
        self.assertEqual(len(full['reads']),15)
        self.assertEqual(frame['context']['time'],2200)
        self.assertEqual(frame['task'],'same B checkpoint')
        self.assertIn('pending_start_validation',frame['context'])
        for namespace in set(before)|set(r.store.records):
            if namespace not in ('public','interaction_entries'):self.assertEqual(before.get(namespace),r.store.records.get(namespace))

    def test_T11_T12_other_context_failed_and_malformed_outputs_do_not_supply_facts(self):
        r,attempts,frame,size=self.recorded(377)
        baseline=prompt_variants(r,attempts,frame,size)[0]['same_context_fact_memory']
        old=next(a for _,a in attempts if a['context_ref']==frame['context']['context_ref'])
        bad={**old,'attempt_id':'malformed','index':999,'raw_ref':r.store.put('not an action')}
        malformed_ref=digest('invalid');r.store.objects[malformed_ref]=b'not json';bad['raw_ref']=malformed_ref
        extras=[('malformed',bad),('failed',{**bad,'status':'transport_failed'}),('other',{**bad,'context_ref':'other'})]
        actual=prompt_variants(r,attempts+extras,frame,size)[0]['same_context_fact_memory']
        self.assertEqual(actual,baseline)


if __name__=='__main__':unittest.main()
