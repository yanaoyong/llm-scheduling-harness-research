"""V5 offline contracts. Fixed historical choices are replay, never new model output."""
from copy import deepcopy
from types import SimpleNamespace
import ast
import json
import unittest
import uuid

from .test_capacity_batch60_experiment import ToyFactory, LoadFactory, fixture_plan
from .test_capacity_two_strategy import context_for
from . import test_capacity_two_strategy as saved
from src.smt_fullfab.environment import FullFabEnvironment
from src.smt_fullfab.audit import audit_opportunity_coverage
from src.smt_fullfab.harness.capacity_config import deadline_config, audit_policy
from src.smt_fullfab.harness.batch_window import configure, advance, capacity_measurement, decision
from src.smt_fullfab.harness.deadline_collection import forecast_notice, delivery_receipts
from src.smt_fullfab.harness.planning_batches import open_batch, accept_batch
from src.smt_fullfab.harness.capacity_prompt import PublicPacket, instructions
from src.smt_fullfab.harness.contracts import ROOT, validate_config, default_config, HarnessError
from src.smt_fullfab.harness.transport import PROTOCOL_TEXT, prompt
from src.smt_fullfab.harness.factory import capture
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.evaluation import Evidence, seal_evidence, audit_provenance
from src.smt_fullfab.harness.offline_isolation import authorize_model


def upgrade(env, group='G1'):
    del env.batch_state
    env.trace=[e for e in env.trace if e['kind']!='batching_enabled']
    configure(env,anchor=env.t,capacity=deadline_config(group)['capacity_experiment'])
    return env


def accept_current(env):
    context=context_for(env);batch=open_batch(env,context)
    return accept_batch(env,batch)


class DeadlineRulesTests(unittest.TestCase):
    measurements=[]

    def test_configs_preserve_capacity_and_only_expected_treatment_differences(self):
        configs=[deadline_config(g) for g in ('G0','G1','G2')]
        for cfg in configs:validate_config(cfg)
        self.assertEqual([(c['capacity_experiment']['model_context_window'],c['capacity_experiment']['input_token_budget'])
                          for c in configs],[(272000,220000),(272000,220000),(544000,440000)])
        for cfg in configs:
            for k in ('group','execution_rule','model_context_window','input_token_budget','model_auto_compact_token_limit'):
                cfg['capacity_experiment'].pop(k)
        self.assertEqual(configs[0],configs[1]);self.assertEqual(configs[1],configs[2])

    def test_v5_cannot_enter_model_transport_even_with_flag(self):
        cfg=deadline_config('G1');cfg['capacity_experiment']['model_calls_enabled']=True
        with self.assertRaises(HarnessError):authorize_model(cfg,{'pilot':'forged'})

    def test_actual_gap_is_immediate_and_does_not_erase_existing_tasks(self):
        env=upgrade(ToyFactory());before=deepcopy(env.plan)
        accept_current(env)
        stop=advance(env,600)
        self.assertEqual((env.t,stop['reason']),(0,'uncovered_demand'))
        self.assertEqual(env.plan,before)
        self.assertEqual(len(env._pending()[1]),2)
        self.assertEqual(env.batch_state['ready_since'],{'2':0})
        self.assertFalse(any(e['kind']=='time_advance' for e in env.trace))

    def test_submitted_executable_task_runs_before_another_machine_gap_stops(self):
        env=upgrade(ToyFactory());env.t=12
        stop=advance(env,600)
        self.assertEqual(stop['reason'],'uncovered_demand')
        self.assertEqual([e['task'] for e in env.trace if e['kind']=='dispatch'],['a'])
        self.assertEqual([t['id'] for t in env._pending()[1]],['b'])

    def test_early_delivery_deadline_and_real_ready_are_distinct(self):
        env=upgrade(ToyFactory(busy_until=300,events=[(300,'release')]))
        # Consume only the capacity cohort. No notification has yet been delivered.
        c=context_for(env)
        from src.smt_fullfab.harness.planning_batches import revisions
        env.batch_state['capacity_watermark']=revisions(c['problem'],c['batch_demands'])
        first=advance(env,600);self.assertEqual((env.t,first['reason']),(105,'plan_runway'))
        accept_current(env)
        self.assertEqual(env.batch_state['forecast_notifications']['2']['stage'],'early')
        second=advance(env,600);self.assertEqual((env.t,second['reason']),(165,'plan_runway'))
        receipt=accept_current(env)
        self.assertTrue(receipt['unassigned_operation_ids'])
        self.assertEqual(receipt['machine_reviews'][0]['review_status'],'unreported')
        third=advance(env,600);self.assertEqual((env.t,third['reason']),(300,'uncovered_demand'))
        starts=[(e['time'],e['task']) for e in env.trace if e['kind']=='dispatch']
        self.assertEqual(starts,[(12,'a'),(24,'b')])
        self.measurements.append({'case':'early_deadline_ready','stops':[105,165,300],
            'reasons':[first['reason'],second['reason'],third['reason']], 'existing_task_starts':starts,
            'unassigned_after_notification':len(receipt['unassigned_operation_ids'])})

    def test_recent_commit_cannot_push_reminder_beyond_deadline(self):
        env=upgrade(ToyFactory(busy_until=300));env.batch_state['last_planning_at']=140
        notice=forecast_notice(env.batch_state['pending_demands']['2'],env.batch_state)
        self.assertEqual(notice['normal_collection_at'],200)
        self.assertEqual(notice['due_at'],165)

    def test_nearby_deadlines_are_delivered_together_without_seconds_apart_retrigger(self):
        from .test_capacity_batch60_experiment import op
        env=upgrade(ToyFactory(busy_until=300,events=[(300,'release'),(306.75,'release')]))
        env.physical.add(3);env.machines[3]=SimpleNamespace(family='F')
        env.machine_state[3]={'ready':306.75,'down_until':0};env.public_available[3]=306.75
        original_problem=env.problem
        def problem(**kw):
            p=original_problem(**kw);p['operations'].append(op('nearby',3));return p
        env.problem=problem
        env.t=105;accept_current(env)
        self.assertEqual((advance(env,600)['reason'],env.t),('plan_runway',165))
        receipt=accept_current(env)
        self.assertEqual({r['stage'] for r in receipt['forecast_notifications'].values()},{'deadline'})
        self.assertEqual((advance(env,600)['reason'],env.t),('uncovered_demand',300))
        self.assertFalse(any(e['kind']=='batch_check' and e['time']==171.75 and e['reason'] for e in env.trace))
        self.measurements.append({'case':'nearby_deadlines','deadlines':[165,171.75],
            'merged_deadline_notice_at':165,'next_stop':300,'same_notice_retrigger_at_171_75':False})

    def test_deadline_delivery_suppresses_same_episode_but_not_earlier_or_new_episode(self):
        env=upgrade(ToyFactory(busy_until=300));env.t=165;accept_current(env)
        d=env.batch_state['pending_demands']['2']
        self.assertIsNone(forecast_notice(d,env.batch_state))
        earlier={**d,'forecast_latest_start':150,'forecast_need_at':285}
        self.assertEqual(forecast_notice(earlier,env.batch_state)['due_at'],150)
        changed={**d,'forecast_notice_key':'new-observed-episode'}
        self.assertEqual(forecast_notice(changed,env.batch_state)['due_at'],165)
        drift={**d,'forecast_latest_start':200,'forecast_need_at':335}
        self.assertIsNone(forecast_notice(drift,env.batch_state))

    def test_overdue_restore_handles_immediately_without_claiming_deadline_met(self):
        env=upgrade(ToyFactory(busy_until=100));stop=advance(env,600)
        self.assertEqual((env.t,stop['reason']),(0,'plan_runway'))
        self.assertEqual(stop['forecast_notifications'][0]['latest_start'],-35)

    def test_unoffered_machine_is_never_acknowledged(self):
        env=upgrade(ToyFactory(busy_until=300));batch=open_batch(env,context_for(env))
        batch['operation_ids']=[]
        self.assertEqual(delivery_receipts(batch,165),{})

    def test_paging_address_alone_cannot_acknowledge_delivery(self):
        env=upgrade(ToyFactory(busy_until=300));batch=open_batch(env,context_for(env))
        self.assertTrue(batch['operation_ids'])
        batch['requires_paged_read']=True
        self.assertEqual(delivery_receipts(batch,165),{})

    def test_redisplaying_a_final_notice_cannot_downgrade_it_to_early(self):
        row={'machine':3,'forecast_notice_key':'same-episode','forecast_latest_start':171.75,'operation_ids':['x']}
        batch={'operation_ids':['x'],'focus_demands':[row],'notification_merge_seconds':60}
        previous={'3':{'notice_key':'same-episode','latest_start':171.75,'stage':'deadline','delivered_at':165}}
        # An unrelated capacity round at 168 must not recreate a 171.75 reminder.
        self.assertEqual(delivery_receipts(batch,168,previous)['3']['stage'],'deadline')
        self.assertEqual(delivery_receipts(batch,168)['3']['stage'],'early')

    def test_invalid_plan_still_stops_immediately(self):
        env=upgrade(ToyFactory(gap=False,events=[(20,'invalidate')]))
        self.assertEqual((advance(env,600)['reason'],env.t),('plan_invalidated',20))

    def test_original_dispatch_and_gap_methods_are_unchanged(self):
        manifest=json.loads((ROOT/'isolation_manifest.json').read_text())
        from pathlib import Path
        def methods(path):
            tree=ast.parse(path.read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='FullFabEnvironment')
            return {n.name:n for n in cls.body if isinstance(n,ast.FunctionDef)}
        old=methods(Path(manifest['source_root'])/'src/smt_fullfab/environment.py')
        new=methods(ROOT/'src/smt_fullfab/environment.py')
        for name in ('_pending','_active_holds','_run_planned_now','_gaps'):
            self.assertEqual(ast.dump(new[name]),ast.dump(old[name]))
        # The only new advance statement is the explicit dynamic-policy dispatch.
        self.assertEqual(ast.dump(ast.Module(body=[new['advance_plan'].body[0],*new['advance_plan'].body[2:]],type_ignores=[])),
                         ast.dump(ast.Module(body=old['advance_plan'].body,type_ignores=[])))

    def test_original_ignores_forecast_and_capacity_but_stops_for_real_gap(self):
        env=upgrade(ToyFactory(busy_until=300,events=[(300,'release')]),'G0')
        stop=FullFabEnvironment.advance_plan(env,600)
        self.assertEqual((env.t,stop['reason']),(300,'uncovered_demand'))
        self.assertFalse(any(e['kind']=='batch_check' for e in env.trace))
        self.assertEqual([e['task'] for e in env.trace if e['kind']=='dispatch'],['a','b'])


class DeadlineCapacityTests(unittest.TestCase):
    measurements=[]

    def test_more_future_content_fits_large_budget_with_honest_overflow(self):
        rows=[]
        for group in ('G1','G2'):
            env=LoadFactory(group);env.count=2000
            for i,m in enumerate(env.sample['problem']['machines']):m['available_at']=300+i
            upgrade(env,group)
            context=context_for(env);batch=open_batch(env,context);context['planning_batch']=batch
            cfg=env.batch_state['capacity']
            packet=PublicPacket(context).fit({},prefix=PROTOCOL_TEXT+instructions(cfg),budget=cfg['input_token_budget'],reserve=10000)
            scope=packet['frame']['forecast_scope']
            self.assertEqual(scope['known_forecast_machines'],2000)
            self.assertGreater(scope['fully_included_deadline_through'],60)
            self.assertGreater(scope['not_offered'],0)
            self.assertLessEqual(packet['budgeted_input_tokens'],cfg['input_token_budget'])
            receipt=accept_batch(env,batch)
            self.assertEqual(len(receipt['forecast_notifications']),packet['inline_operations'])
            after=capacity_measurement(env,context['problem'])
            self.assertEqual(after['incoming_operation_count'],0)
            self.assertIsNone(decision(env,context['problem'],[],after)['reason'])
            self.assertEqual(len(env.batch_state['pending_demands']),2000)
            self.assertEqual(env.plan['tasks'],[])
            row={'group':group,'input_budget':cfg['input_token_budget'],'budgeted_tokens':packet['budgeted_input_tokens'],
                 'inline_operations':packet['inline_operations'],'scope':scope,'same_capacity_retrigger':False}
            rows.append(row);self.measurements.append(row)
        self.assertGreater(rows[1]['inline_operations'],rows[0]['inline_operations'])
        self.assertGreater(rows[1]['scope']['fully_included_deadline_through'],rows[0]['scope']['fully_included_deadline_through'])

    def test_cold_start_partitions_all_2000_without_loss_or_duplicate(self):
        counts=[]
        for group in ('G1','G2'):
            env=LoadFactory(group);env.count=2000;env.plan=None
            for machine in env.sample['problem']['machines']:machine.update(currently_busy=False,available_at=0)
            upgrade(env,group);seen=set();sizes=[]
            while len(seen)<2000:
                c=context_for(env);batch=open_batch(env,c);ids=set(batch['operation_ids'])
                self.assertTrue(ids);self.assertFalse(ids & seen)
                self.assertEqual(batch['strategy'],'initial')
                seen.update(ids);sizes.append(len(ids));env.plan=fixture_plan(env);accept_batch(env,batch)
                self.assertLess(len(sizes),20)
            self.assertEqual(seen,{o['operation_id'] for o in env.sample['problem']['operations']})
            counts.append(len(sizes));self.measurements.append({'group':group,'case':'initial_partition','batch_sizes':sizes,
                'unique_operations':len(seen),'omitted':0,'duplicated':0,'production_choices':0})
        self.assertLess(counts[1],counts[0])


class DeadlineSavedReplayTests(unittest.TestCase):
    measurements=[]

    @classmethod
    def setUpClass(cls):
        saved.PairedSavedStateTests.setUpClass()
        cls.fixture=saved.PairedSavedStateTests()

    def make_runtime(self,group):
        cfg=deadline_config(group,seconds=self.fixture.initial['state']['horizon']-702) if group!='legacy' else default_config('B',seconds=self.fixture.initial['state']['horizon']-702,seed=1701)
        return Runtime.start_new(ROOT/'.tmp'/('deadline-'+group+'-'+uuid.uuid4().hex),cfg,
            experiment_id='offline-deadline-fixed-plan',initial=self.fixture.initial)

    def commit(self,r):
        result=self.fixture.submit(r,self.fixture.fixed_delta(r))
        self.assertEqual(result['status'],'candidate_checked',result)
        result=r.record_output({'tool':'apply_candidate','context_ref':r.head['context_ref'],
            'request_id':'fixed-apply','candidate_ref':result['candidate_ref']})
        self.assertEqual(result['status'],'accepted',result)

    def test_same_saved_plan_replay_restore_and_independent_audits(self):
        original_outcomes=[]
        for group in ('legacy','G0','G1','G2'):
            r=self.make_runtime(group)
            try:
                if group!='legacy':
                    prompt(r);self.assertLessEqual(r.last_capacity_measurement['budgeted_input_tokens'],r.config['capacity_experiment']['input_token_budget'])
                self.commit(r);self.assertEqual(r.env.plan,self.fixture.fixed_plan)
                before=capture(r.env);path=r.store.path;r.close();r=Runtime.resume_run(path)
                self.assertEqual(capture(r.env),before)
                feedback=r.advance()
                self.assertNotEqual(feedback['stop_reason']['reason'],'capacity_limit')
                self.assertGreater(feedback['dispatch_count_delta'],0)
                self.assertEqual(r.env.plan,self.fixture.fixed_plan)
                ap=audit_policy(r.config['capacity_experiment'],702) if group!='legacy' else None
                audit=audit_opportunity_coverage(r.env.trace,batching_policy=ap)
                self.assertTrue(audit['valid'],audit['errors'][:8])
                self.assertEqual(r.usage()['actual_model_attempts'],0)
                row={'group':group,'from':702,'to':r.env.t,'dispatches':feedback['dispatch_count_delta'],
                     'stop_reason':feedback['stop_reason']['reason'],'independent_audit_valid':True,
                     'existing_plan_unchanged':True,'model_calls':0}
                self.measurements.append(row)
                if group in ('legacy','G0'):
                    original_outcomes.append({'feedback':feedback['stop_reason'],'dispatches':[(e['time'],e['machine'],e['lots'])
                        for e in r.env.trace if e['kind']=='dispatch'],'time':r.env.t})
                if group in ('G1','G2'):
                    bad=deepcopy(r.env.trace);receipt=next(e for e in bad if e['kind']=='planning_batch_accepted')
                    receipt['forecast_notifications']['forged']={'stage':'deadline'}
                    self.assertFalse(audit_opportunity_coverage(bad,batching_policy=ap)['valid'])
                    check=next((e for e in r.env.trace if e['kind']=='batch_check' and e.get('forecast_notifications')),None)
                    if check:
                        bad=deepcopy(r.env.trace);target=next(e for e in bad if e['kind']=='batch_check' and e.get('forecast_notifications'))
                        target['forecast_notifications'][0]['due_at']+=60
                        self.assertFalse(audit_opportunity_coverage(bad,batching_policy=ap)['valid'])
                r.stop('offline-deadline-audit');sha=seal_evidence(r)
                ev=Evidence(r.store.path,sha);trace=[ev.get(ref) for ref in ev.value['physical']]
                self.assertTrue(audit_provenance(ev,trace)['valid'])
            finally:r.close()
        self.assertEqual(original_outcomes[0],original_outcomes[1])
