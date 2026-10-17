"""V4 offline regression: explicit fixtures and sealed evidence, zero model calls."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import unittest

from .test_capacity_batch60_experiment import ToyFactory, LoadFactory, op, policy
from .test_capacity_two_strategy import context_for
from . import test_capacity_two_strategy as lifecycle_fixtures
from src.smt_fullfab.harness.batch_window import observe_demands, decision, capacity_measurement, advance
from src.smt_fullfab.harness.planning_batches import open_batch, accept_batch, revisions
from src.smt_fullfab.harness.forecast_collection import supported_arrivals, forecast_fields
from src.smt_fullfab.harness.capacity_config import experiment_config
from src.smt_fullfab.harness.capacity_prompt import PublicPacket, INSTRUCTIONS
from src.smt_fullfab.harness.presentation import unpack
from src.smt_fullfab.harness.transport import PROTOCOL_TEXT, prompt, response_schema
from src.smt_fullfab.harness.contracts import ROOT, HarnessError
from src.smt_fullfab.harness.evaluation import Evidence, seal_evidence, audit_provenance
from src.smt_fullfab.audit import audit_opportunity_coverage


class NearbyFactory(ToyFactory):
    def __init__(self):
        super().__init__(busy_until=100,events=[(100,'release'),(106.75,'release')])
        self.physical.add(3);self.machines[3]=SimpleNamespace(family='F')
        self.machine_state[3]={'ready':106.75,'down_until':0};self.public_available[3]=106.75
    def problem(self,**kwargs):
        value=super().problem(**kwargs)
        if 3 in self.physical:value['operations'].append(op('nearby',3))
        return value


class ForecastCollectionTests(unittest.TestCase):
    measurements=[]

    def test_nearby_forecasts_share_one_batch_while_committed_tasks_execute(self):
        env=NearbyFactory();c=context_for(env);accept_batch(env,open_batch(env,c))
        stop=advance(env,180)
        self.assertEqual((stop['reason'],env.t),('plan_runway',85))
        env.last_stop=stop;c=context_for(env);batch=open_batch(env,c)
        self.assertEqual({d['machine'] for d in batch['focus_demands']},{2,3})
        original=deepcopy(env.plan)
        receipt=accept_batch(env,batch,[{'machine':mid,'disposition':'deferred','reason':'Offline review fixture',
                                       'revisit_at':145} for mid in (2,3)])
        self.assertEqual({r['review_status'] for r in receipt['machine_reviews']},{'explicit'})
        self.assertTrue(receipt['unassigned_operation_ids'])
        second=advance(env,180)
        self.assertEqual((second['reason'],env.t),('ready_wait_limit',160))
        self.assertFalse(any(e['kind']=='batch_check' and e['time']==91.75 and e['reason'] for e in env.trace))
        self.assertEqual(env.plan,original)
        self.assertEqual([(e['time'],e['task']) for e in env.trace if e['kind']=='dispatch'],[(12,'a'),(24,'b')])
        self.measurements.append({'fixture':'nearby_100_and_106_75','first_forecast_call_at':85,
            'focus_machines':[2,3],'next_stop_at':160,'next_stop_reason':second['reason'],
            'planned_task_starts':[12,24],'model_calls':0})

    def test_ready_deadline_overrides_recent_planning_clock(self):
        env=ToyFactory();advance(env,30)
        c=context_for(env);accept_batch(env,open_batch(env,c))
        stop=advance(env,180)
        self.assertEqual((stop['reason'],env.t),('ready_wait_limit',60))
        self.assertEqual(env.batch_state['last_planning_at'],30)
        self.assertEqual(env.batch_state['ready_since'],{'2':0})
        self.assertEqual(env.batch_state['reviewed_forecasts'],{})

    def test_unsupported_nominal_future_is_not_an_urgent_forecast(self):
        env=ToyFactory(busy_until=100);p=env.problem()
        row=next(o for o in p['operations'] if o['eligible_machines']==[2])
        row.update(conditional=True,readiness_basis='nominal_unplanned_route')
        observe_demands(env,p,[])
        self.assertIsNone(env.batch_state['pending_demands']['2']['forecast_due_at'])
        self.assertIn(row['operation_id'],env.batch_state['pending_demands']['2']['operation_ids'])
        self.assertIsNone(decision(env,p,[],capacity_measurement(env,p))['forecast_deadline'])
        row.update(readiness_basis='executing_predecessor',release_time=200)
        observe_demands(env,p,[])
        self.assertEqual(env.batch_state['pending_demands']['2']['forecast_due_at'],185)

    def test_material_forecast_follows_only_already_committed_predecessors(self):
        parent=op('parent',1);parent.update(conditional=False,transport_seconds=10)
        child=op('child',2);child.update(conditional=True,predecessor_ids=[parent['operation_id']])
        p={'time':0,'operations':[parent,child],'machines':[{'machine':i,'available_at':0} for i in (1,2)]}
        self.assertNotIn(child['operation_id'],supported_arrivals(p,{}))
        task={'id':'explicit-parent','machine':1,'operation_ids':[parent['operation_id']],'not_before':100}
        eta=supported_arrivals(p,{1:[task]})
        self.assertEqual(eta[child['operation_id']],140)
        machine={'machine':2,'available_at':105,'currently_busy':True}
        self.assertEqual(forecast_fields(machine,[child],eta,15)['forecast_due_at'],125)
        # A cyclic or missing chain remains unknown, never invented work.
        parent['predecessor_ids']=[child['operation_id']]
        self.assertNotIn(child['operation_id'],supported_arrivals(p,{1:[task]}))

    def test_invalid_review_does_not_change_tasks_or_turn_unoffered_into_reviewed(self):
        env=ToyFactory();c=context_for(env);batch=open_batch(env,c);original=deepcopy(env.plan)
        receipt=accept_batch(env,batch,[{'machine':2,'disposition':'planned','reason':'false fixture','revisit_at':1000}])
        self.assertEqual(env.plan,original)
        self.assertTrue(receipt['review_errors'])
        self.assertEqual(receipt['machine_reviews'][0]['review_status'],'unreported')
        self.assertEqual(receipt['machine_reviews'][0]['production_status'],'unplanned')
        self.assertEqual(env.batch_state['ready_since'],{'2':0})

    def test_old_trigger_evidence_precedes_fresh_records_and_overflow_stays_explicit(self):
        env=LoadFactory('G1');env.count=2000;c=context_for(env)
        env.batch_state['presented_revisions']=revisions(c['problem'],c['batch_demands'])
        env.sample['problem']['operations'][0]['payload']='new public fact'
        env.last_stop={'reason':'plan_runway','forecast_trigger_machines':[1999]}
        c=context_for(env);batch=open_batch(env,c)
        self.assertIn('1999:1:1',batch['operation_ids'])
        self.assertIn('0:1:1',batch['operation_ids'])
        self.assertLess(len(batch['operation_ids']),2000)
        self.assertEqual(batch['focus_demands'][0]['machine'],1999)

    def test_2000_focus_overflow_is_visible_and_never_falsely_reviewed(self):
        for group in ('G1','G2'):
            env=LoadFactory(group);env.count=2000
            env.last_stop={'reason':'plan_runway','forecast_trigger_machines':list(range(2000))}
            context=context_for(env);batch=open_batch(env,context);context['planning_batch']=batch
            cfg=env.batch_state['capacity']
            packet=PublicPacket(context).fit({},prefix=PROTOCOL_TEXT+INSTRUCTIONS,budget=cfg['input_token_budget'],reserve=10000)
            focus=unpack(packet['frame']['focus_coverage']);before=deepcopy(env.plan)
            expected={d['machine']:{k:v for k,v in d.items() if k!='operation_ids'} for d in context['batch_demands']}
            for row in unpack(packet['frame']['demand_details']):self.assertEqual(row,expected[row['machine']])
            receipt=accept_batch(env,batch)
            self.assertEqual(env.plan,before);self.assertEqual(len(focus),2000)
            self.assertLessEqual(packet['budgeted_input_tokens'],cfg['input_token_budget'])
            self.assertTrue(any(x['information_status']=='not_offered' for x in focus))
            self.assertTrue(all(x['review_status']=='unreported' and x['production_status']=='unplanned' for x in receipt['machine_reviews']))
            self.measurements.append({'fixture':'2000_focus_overflow','group':group,'focus_machines':len(focus),
                'inline_operations':packet['inline_operations'],'unoffered_focus_machines':sum(x['information_status']=='not_offered' for x in focus),
                'budgeted_input_tokens':packet['budgeted_input_tokens'],'input_budget':cfg['input_token_budget'],
                'invented_tasks':0,'invented_reviews':0,'model_calls':0})


class SavedEvidencePacketTests(unittest.TestCase):
    measurements=[]

    def test_768_trigger_material_is_in_both_packets_despite_already_seen_status(self):
        run=ROOT/'live_pilots/two_strategy_20261016';result=json.loads((run/'G2.result.json').read_text())
        evidence=Evidence(run/'G2',result['evidence_sha256'])
        original=evidence.rows('contexts')[result['head']['context_ref']]
        state=evidence.get(result['head']['state_ref'])
        self.assertEqual(original['time'],768)
        due=original['trigger']['forecast_deadline']
        mids=[d['machine'] for d in original['batch_demands'] if d['forecast_available_at'] is not None and abs(d['forecast_available_at']-15-due)<1e-6]
        self.assertEqual(mids,[1295,1296])
        for group in ('G1','G2'):
            context=deepcopy(original);context.pop('planning_batch');context.pop('planning_batch_ref',None)
            context['trigger']['forecast_trigger_machines']=mids
            env=SimpleNamespace(t=768,plan=context['base_plan'],horizon=3600,last_stop=context['trigger'],trace=[],
                batch_state={**deepcopy(state['batch_state']),'active_batch':None,
                             'capacity':experiment_config(group)['capacity_experiment']})
            env._pending=lambda:{t['machine']:[t] for t in env.plan['tasks']}
            env._emit=lambda kind,**data:env.trace.append({'kind':kind,'time':768,**data})
            batch=open_batch(env,context);context['planning_batch']=batch
            cfg=env.batch_state['capacity']
            packet=PublicPacket(context).fit({},prefix=PROTOCOL_TEXT+INSTRUCTIONS,budget=cfg['input_token_budget'],reserve=10000)
            indices=[i for family in packet['frame']['public_problem']['operation_groups'] for i in family['source_indices']]
            actual={context['problem']['operations'][i]['operation_id'] for i in indices}
            counts={str(mid):len(actual.intersection(next(d for d in context['batch_demands'] if d['machine']==mid)['operation_ids'])) for mid in mids}
            self.assertEqual(counts,{'1295':188,'1296':188})
            self.assertLessEqual(packet['budgeted_input_tokens'],cfg['input_token_budget'])
            self.measurements.append({'group':group,'fixture':'sealed_G2_768_public_context_repack',
                'old_inline_candidates':{'1295':0,'1296':0},'new_inline_candidates':counts,
                'budgeted_input_tokens':packet['budgeted_input_tokens'],'input_budget':cfg['input_token_budget'],'model_calls':0})


class ReceiptAuditTests(unittest.TestCase):
    def test_explicit_review_is_atomic_and_independently_audited_without_extra_round(self):
        helper=lifecycle_fixtures.PairedSavedStateTests();helper.setUpClass();r=helper.make_runtime('G1')
        try:
            batch=r.env.batch_state['active_batch'];mid=batch['focus_demands'][0]['machine']
            proposal=helper.submit(r,helper.fixed_delta(r))
            review={'machine':mid,'disposition':'deferred','reason':'Offline annotation fixture','revisit_at':1000}
            result=r.record_output({'tool':'apply_candidate','context_ref':r.head['context_ref'],'request_id':'apply-reviewed',
                                   'candidate_ref':proposal['candidate_ref'],'machine_reviews':[review]})
            self.assertEqual(result['status'],'accepted',result)
            self.assertEqual(r.usage()['offline_outputs'],2)
            self.assertEqual(r.usage()['actual_model_attempts'],0)
            self.assertEqual(r.env.batch_state['last_planning_at'],702)
            self.assertEqual(r.env.batch_state['reviewed_forecasts'],{})
            review_row=next(x for x in result['batch_coverage']['machine_reviews'] if x['machine']==mid)
            self.assertEqual(review_row['forecast_eligible_again_at'],762)
            r.advance()
            context=r.store.read('contexts',r.head['context_ref'])
            reference=r.store.read('public',context['machine_reviews_ref'])
            self.assertEqual(r.store.get(reference['object_ref']),r.env.batch_state['machine_reviews'])
            r.stop('offline-receipt-audit');sha=seal_evidence(r)
            ev=Evidence(r.store.path,sha);trace=[ev.get(ref) for ref in ev.value['physical']]
            self.assertTrue(audit_provenance(ev,trace)['valid'])
            self.assertTrue(audit_opportunity_coverage(trace,batching_policy=policy(r.env))['valid'])
            bad=deepcopy(trace);receipt=next(e for e in bad if e['kind']=='planning_batch_accepted')
            receipt['machine_reviews'][0]['review_status']='invented'
            with self.assertRaises(HarnessError):audit_provenance(ev,bad)
            bad=deepcopy(trace);check=next(e for e in bad if e['kind']=='batch_check')
            check['forecast_not_before']=0
            self.assertFalse(audit_opportunity_coverage(bad,batching_policy=policy(r.env))['valid'])
        finally:r.close()

    def test_review_schema_uses_existing_confirmation_action(self):
        schema=response_schema('B',candidate_refs=['checked'],planning_reviews=True)
        rows=[a for a in schema['properties']['action']['anyOf'] if 'machine_reviews' in a['properties']]
        self.assertTrue(rows)
        self.assertTrue(all(a['properties']['tool']['enum']==['apply_candidate'] for a in rows))
