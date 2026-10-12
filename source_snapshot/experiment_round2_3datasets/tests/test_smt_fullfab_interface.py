"""Paging preserves the full problem and cannot supply a selected schedule."""
from copy import deepcopy
import json
import unittest
from src.smt_fullfab.interface import compact_pages,expand_pages,decode_plan,validate_choices
from tests.test_smt_fullfab_optimizer import machine,operation,problem


class InterfaceTests(unittest.TestCase):
    def fixture(self):
        p=problem([machine(0),machine(1)], [operation('lot:1:1',mid=0,lot_id='lot',visit=1)])
        p['scope']=[0,1]
        p['setup_transitions']=[]
        p['min_runs']={}
        p['operations'][0].setdefault('terminal',True)
        p['operations'][0].setdefault('setup_time',None)
        return p

    def test_paging_exact_coverage_no_mutation(self):
        p=self.fixture();before=deepcopy(p);c=compact_pages(p)
        ids=[r[0] for page in c['pages'] for g in page for r in g['operations']]
        self.assertEqual(ids,['lot:1:1']);self.assertEqual(p,before)
        self.assertEqual({m[0] for page in c['pages'] for g in page for m in g['machines']},{0,1})
        self.assertEqual(expand_pages(c),p)

    def test_complete_observation_and_future_fields_roundtrip(self):
        p=self.fixture()
        p.update(schema='smt-fullfab-problem-2',lookahead_depth=3,
                 frozen_tasks=[{'operation_ids':['lot:1:1'],'not_before':4}],
                 uncertainty={'historical_binding':'unknown'},unrevealed=['random_stream'],
                 forecast_limitations=['expected durations'],future_root={'nested':[False,None,0]})
        p['machines'][0].update(currently_busy=True,currently_down=False,
                               availability_basis='observed plus expectation',future_machine={'x':None})
        p['operations'][0].update(waiting_since=0,conditional=False,sampling_percent=25,
            rework_percent=3,qualification_basis='observed',qualification_uncertain=True,
            binding_origin_step=7,initial_virtual_predecessors=[{'sampling_percent':50}],
            conditional_virtual_successors=[{'family':'Delay_32','seconds':90}],
            same_machine_as='predecessor:id',future_operation={'new':[]})
        c=compact_pages(p);q=expand_pages(c)
        self.assertEqual(json.dumps(q,sort_keys=True),json.dumps(p,sort_keys=True))
        self.assertEqual(c['schema'],'fullfab-compact-paging-v2')
        self.assertEqual(c['problem_metadata']['frozen_tasks'],p['frozen_tasks'])
        self.assertIn('same_machine_as',c['pages'][0][0]['operation_extras'][0]['values'])

    def test_missing_null_empty_false_and_zero_are_distinct(self):
        p=self.fixture()
        p['machines'][0]['cascading']=None
        p['machines'][1]['currently_busy']=False
        ops=[]
        for i,eligible in enumerate(([0,1],[1,0],[],None,[False,1])):
            op=deepcopy(p['operations'][0]);op.update(operation_id=str(i),eligible_machines=eligible)
            op['waiting_since']=None if i else 0
            op['same_machine_as']=None
            ops.append(op)
        del ops[0]['waiting_since'];del ops[0]['same_machine_as'];del ops[0]['setup_time']
        del ops[-1]['eligible_machines'];del ops[-1]['lot_id']
        p['operations']=ops
        c=compact_pages(p);q=expand_pages(c)
        self.assertEqual(json.dumps(q,sort_keys=True),json.dumps(p,sort_keys=True))
        rows=c['pages'][0][0]['operations']
        self.assertEqual(rows[0][7],'all_family_machines')
        self.assertEqual(rows[1][7],[1,0])
        self.assertNotIn('cascading',q['machines'][1])
        self.assertIsNone(q['machines'][0]['cascading'])
        self.assertNotIn('waiting_since',q['operations'][0])

    def test_source_order_and_explicit_identity_are_preserved(self):
        p=self.fixture()
        p['machines']=[machine(8,'Z'),machine(2,'A'),machine(1,'Z')]
        base=p['operations'][0]
        p['operations']=[{**base,'operation_id':'arbitrary','lot_id':'lot:with:colons','step':71,
                          'visit':8,'family':'Z','eligible_machines':[8,1]},
                         {**base,'operation_id':'other','family':'A','eligible_machines':[2]}]
        self.assertEqual(expand_pages(compact_pages(p)),p)

    def test_stable_family_split_bounded_pages_and_complete_restore(self):
        p=self.fixture();base=p['operations'][0]
        p['operations']=[{**base,'operation_id':str(i),'lot_id':str(i)} for i in range(90)]
        c=compact_pages(p,3000)
        self.assertGreater(len(c['pages']),1)
        self.assertTrue(all(len(json.dumps(page,separators=(',',':')))<=3000 for page in c['pages']))
        self.assertEqual(c,compact_pages(p,3000))
        self.assertEqual(expand_pages(c),p)
        manifest={k:v for k,v in c.items() if k!='pages'}
        self.assertEqual(expand_pages(manifest,c['pages']),p)

    def test_large_catalog_or_indivisible_row_fails_without_truncation(self):
        p=self.fixture();before=deepcopy(p)
        with self.assertRaises(ValueError):compact_pages(p,30)
        self.assertEqual(p,before)
        p['operations'][0]['operation_id']='x'*10000
        with self.assertRaisesRegex(ValueError,'single operation'):compact_pages(p,3000)

    def test_family_without_machine_and_empty_problem_preserved(self):
        p=self.fixture();p['operations'][0]['family']='not_in_machine_array'
        self.assertEqual(expand_pages(compact_pages(p)),p)
        p['operations']=[];p['machines']=[]
        self.assertEqual(expand_pages(compact_pages(p)),p)

    def test_full_observation_tampering_and_duplicate_rows_rejected(self):
        c=compact_pages(self.fixture())
        mutations=[
            lambda x:x['problem_metadata'].update(new_unknown_field=True),
            lambda x:x['pages'][0][0]['operation_extras'][0]['values'].update(conditional=True),
            lambda x:x['pages'][0][0]['operations'].append(deepcopy(x['pages'][0][0]['operations'][0])),
            lambda x:x['pages'][0][0]['operations'].clear(),
            lambda x:x['pages'][0][0]['operations'][0].__setitem__(13,True),
            lambda x:x['pages'][0][0]['machine_extras'].append({'values':{'hidden':'hint'},'absent':[]}),
            lambda x:x['pages'][0][0]['operation_extras'][0]['values'].update(priority=999),
            lambda x:x.update(time=999),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                bad=deepcopy(c);mutation(bad)
                with self.assertRaises(ValueError):expand_pages(bad)

    def test_split_family_conflicting_catalog_rejected(self):
        p=self.fixture();base=p['operations'][0]
        p['operations']=[{**base,'operation_id':str(i)} for i in range(90)]
        c=compact_pages(p,3000)
        c['pages'][1][0]['machine_extras'][0]['values']['currently_busy']=True
        with self.assertRaisesRegex(ValueError,'catalogs differ'):expand_pages(c)

    def test_output_mutation_does_not_change_source_or_schema(self):
        p=self.fixture();before=deepcopy(p);c=compact_pages(p)
        c['problem_metadata']['scope'].append(999)
        c['pages'][0][0]['types'][0][0].append('changed')
        c['operation_fields'].append('changed')
        self.assertEqual(p,before)
        self.assertNotIn('changed',compact_pages(p)['operation_fields'])

    def test_no_decoder_choice_or_added_operation(self):
        p=self.fixture();output={'tasks':[{'machine':0,'operations':['lot:1:1'],'start':4,'sequence':2}],
            'holds':[{'machine':0,'until':10,'after_sequence':2,'reason':'explicit wait'}],'reason':'test fixture'}
        plan=decode_plan(p,output,version='v1')
        self.assertEqual(plan['tasks'][0]['not_before'],4)
        self.assertEqual(plan['tasks'][0]['machine'],0)
        self.assertEqual(plan['holds'][0]['after_task_id'],'0')
        self.assertEqual(len(plan['tasks']),1)
        with self.assertRaises(ValueError):validate_choices(p,output['tasks']+output['tasks'])


if __name__=='__main__':unittest.main()
