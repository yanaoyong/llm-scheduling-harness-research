"""Offline acceptance cases. Fixed replay actions are not new model output."""
from copy import deepcopy
import heapq
import json
import unittest
import uuid
import zlib

from .test_capacity_batch60_experiment import ToyFactory, LoadFactory, fixture_plan, policy
from src.smt_fullfab.harness.batch_window import observe_demands, capacity_measurement, decision, advance
from src.smt_fullfab.harness.planning_batches import open_batch, accept_batch
from src.smt_fullfab.harness.capacity_prompt import PublicPacket, INSTRUCTIONS
from src.smt_fullfab.harness.capacity_config import experiment_config
from src.smt_fullfab.harness.contracts import ROOT, HarnessError, digest
from src.smt_fullfab.harness.transport import PROTOCOL_TEXT, prompt
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.factory import capture
from src.smt_fullfab.plan_delta import ORDER_POLICY
from src.smt_fullfab.audit import audit_opportunity_coverage, audit_plan_sources


def context_for(env):
    problem = env.problem()
    observe_demands(env, problem, env._gaps())
    base = env.plan or fixture_plan(env)
    return {'problem':problem, 'base_plan':deepcopy(base),
            'execution_state':{'dispatched_task_ids':[t['id'] for t in base['tasks']
                if (base['version'],t['id']) in env.executed_tasks]},
            'batch_demands':list(deepcopy(env.batch_state['pending_demands']).values()),
            'problem_ref':'offline:problem','facts_ref':'offline:facts','base_plan_ref':'offline:base'}


class BatchLifecycleTests(unittest.TestCase):
    measurements = []

    def test_initial_2000_records_partition_completely_with_fewer_large_packets(self):
        counts = []
        for group in ('G1','G2'):
            env = LoadFactory(group); env.count = 2000; env.plan = None
            for machine in env.sample['problem']['machines']:
                machine.update(currently_busy=False, available_at=0)
            supplied, batches, tokens = set(), [], []
            while len(supplied) < 2000:
                context = context_for(env)
                batch = open_batch(env, context)
                self.assertEqual(batch['strategy'],'initial')
                ids = set(batch['operation_ids'])
                self.assertTrue(ids); self.assertFalse(ids & supplied)
                context['planning_batch'] = batch
                cfg = env.batch_state['capacity']
                packet = PublicPacket(context).fit({}, prefix=PROTOCOL_TEXT+INSTRUCTIONS,
                    budget=cfg['input_token_budget'], reserve=cfg['wrapper_reserve_tokens'])
                self.assertEqual(packet['inline_operations'],len(ids))
                self.assertLessEqual(packet['budgeted_input_tokens'],cfg['input_token_budget'])
                tokens.append(packet['budgeted_input_tokens']); batches.append(len(ids))
                # Empty fixture receipt exercises evidence progress ONLY, not scheduling success.
                env.plan = fixture_plan(env)
                receipt = accept_batch(env,batch)
                self.assertEqual(len(receipt['unassigned_operation_ids']),len(ids))
                supplied.update(ids)
                self.assertEqual(len(env.batch_state['pending_demands']),2000)
                self.assertLess(len(batches),20)
            self.assertEqual(supplied,{op['operation_id'] for op in env.sample['problem']['operations']})
            counts.append(len(batches))
            self.measurements.append({'group':group,'fixture':'synthetic_2000_initial',
                'batches':batches,'packet_budgeted_tokens':tokens,'unique_operations':len(supplied),
                'omitted_operations':0,'duplicate_operations':0,'model_calls':0,
                'production_tasks_selected':0,'all_demands_remain_unassigned':True})
        self.assertLess(counts[1],counts[0])

    def test_same_capacity_cohort_cannot_repeat_but_new_arrivals_can_trigger(self):
        e = LoadFactory('G1'); e.count=1000
        c = context_for(e)
        first = capacity_measurement(e,c['problem'])
        self.assertEqual(decision(e,c['problem'],[],first)['reason'],'capacity_limit')
        batch = open_batch(e,c); accept_batch(e,batch)
        after = capacity_measurement(e,c['problem'])
        self.assertEqual(after['incoming_operation_count'],0)
        self.assertIsNone(decision(e,c['problem'],[],after)['reason'])
        self.assertGreater(len(e.batch_state['pending_demands']),0)
        self.assertGreater(batch['not_yet_offered_count'],0)
        e.count=2000; c=context_for(e)
        new = capacity_measurement(e,c['problem'])
        self.assertEqual(new['incoming_operation_count'],1000)
        self.assertEqual(decision(e,c['problem'],[],new)['reason'],'capacity_limit')

    def test_overflow_precedes_previously_offered_work_and_preserves_dependencies(self):
        e = LoadFactory('G1'); e.count=2000
        ops=e.sample['problem']['operations']
        ops[-1]['predecessor_ids']=[ops[0]['operation_id']]
        c=context_for(e); first=open_batch(e,c)
        self.assertIn(ops[-1]['operation_id'],first['operation_ids'])
        accept_batch(e,first)
        second=open_batch(e,context_for(e))
        self.assertFalse(set(first['operation_ids']) & set(second['operation_ids']))

    def test_time_clamped_release_does_not_reintroduce_old_capacity(self):
        e=LoadFactory('G1');e.count=1000;c=context_for(e);accept_batch(e,open_batch(e,c))
        for op in e.sample['problem']['operations']:op['release_time']=123
        e.t=123;c=context_for(e)
        self.assertEqual(capacity_measurement(e,c['problem'])['incoming_operation_count'],0)
        e.sample['problem']['operations'][0]['eligible_machines']=[1]
        c=context_for(e)
        self.assertEqual(capacity_measurement(e,c['problem'])['incoming_operation_count'],1)

    def test_reviewed_forecast_does_not_loop_and_actual_ready_deadline_survives(self):
        e=ToyFactory(busy_until=300,events=[(300,'release')])
        self.assertEqual(advance(e,400)['reason'],'plan_runway');self.assertEqual(e.t,285)
        c=context_for(e);batch=open_batch(e,c);plan=deepcopy(e.plan)
        accept_batch(e,batch)
        self.assertEqual(e.plan,plan)
        stop=advance(e,400)
        self.assertEqual((stop['reason'],e.t),('ready_wait_limit',360))
        self.assertEqual(e.batch_state['ready_since'],{'2':300})

    def test_accepted_unassigned_batch_keeps_ready_clock_and_planned_dispatches(self):
        e=ToyFactory();c=context_for(e);batch=open_batch(e,c)
        receipt=accept_batch(e,batch)
        self.assertTrue(receipt['unassigned_operation_ids'])
        self.assertEqual(advance(e,180)['reason'],'ready_wait_limit')
        self.assertEqual(e.t,60)
        self.assertEqual([(r['time'],r['task']) for r in e.trace if r['kind']=='dispatch'],[(12,'a'),(24,'b')])
        self.assertEqual(e.batch_state['ready_since'],{'2':0})
        with self.assertRaises(HarnessError):accept_batch(e,batch)

    def test_forecast_clock_drift_is_not_a_new_busy_episode(self):
        e=ToyFactory(busy_until=300)
        advance(e,400);c=context_for(e);accept_batch(e,open_batch(e,c))
        # Actual work lasts longer than the forecast; both are still observably busy.
        e.t=310;e.machine_state[2]['ready']=400;e.public_available[2]=311
        c=context_for(e)
        self.assertIsNone(decision(e,c['problem'],[],capacity_measurement(e,c['problem']))['reason'])
        e._emit('downtime',machine=2)
        c=context_for(e)
        check=decision(e,c['problem'],[],capacity_measurement(e,c['problem']))
        self.assertIsNone(check['reason'])
        self.assertEqual(check['forecast_deadline'],345)  # new forecast also respects collection interval


class PairedSavedStateTests(unittest.TestCase):
    measurements = []

    @classmethod
    def setUpClass(cls):
        cls.initial=json.loads(zlib.decompress((ROOT/'fixtures/initial/mixed_702.json.z').read_bytes()))
        path=ROOT/'live_pilots/paired_20261016_cli_fix/G1/exports/trace.jsonl'
        commits=[json.loads(line)['plan'] for line in path.read_text().splitlines()
                 if json.loads(line)['kind']=='plan_committed']
        cls.fixed_plan=commits[-1]
        assert cls.fixed_plan['created_at']==702 and len(cls.fixed_plan['tasks'])==13

    def make_runtime(self,group):
        cfg=experiment_config(group,seconds=self.initial['state']['horizon']-702)
        return Runtime.start_new(ROOT/'.tmp'/('two-strategy-'+group+'-'+uuid.uuid4().hex),cfg,
            experiment_id='offline-identical-prior-plan-replay',initial=self.initial)

    def submit(self,r,delta):
        return r.record_output({'tool':'propose_delta','context_ref':r.head['context_ref'],
                                'request_id':'fixed-proposal','delta':delta})

    def fixed_delta(self,r):
        context=r.store.read('contexts',r.head['context_ref']);base=context['base_plan']
        pending={t['id'] for t in base['tasks']} - set(context['execution_state']['dispatched_task_ids'])
        plan=self.fixed_plan
        return {'plan_header':{k:v for k,v in plan.items() if k not in ('tasks','holds')},
            'order_policy':ORDER_POLICY,
            'tasks':{'keep':{'mode':'all_pending_except','ids':[]},'cancel_ids':[],'replace':[],
                     'add':[deepcopy(t) for t in plan['tasks'] if t['id'] not in pending]},
            'holds':{'keep':{'mode':'all_except','ids':[]},'cancel_ids':[],'replace':[],'add':[]},
            'machine_orders':[{'machine':mid,'task_ids':[t['id'] for t in plan['tasks'] if t['machine']==mid]}
                for mid in sorted({t['machine'] for t in plan['tasks'] if t['id'] not in pending})]}

    def test_identical_702_plan_executes_in_both_groups_without_old_capacity_stop(self):
        outcomes=[]
        for group in ('G1','G2'):
            r=self.make_runtime(group)
            try:
                self.assertEqual(r.env.batch_state['active_batch']['strategy'],'continuation')
                prompt(r)
                self.assertLessEqual(r.last_capacity_measurement['budgeted_input_tokens'],r.config['capacity_experiment']['input_token_budget'])
                before=capture(r.env); proposal=self.submit(r,self.fixed_delta(r))
                self.assertEqual(proposal['status'],'candidate_checked',proposal)
                self.assertEqual(capture(r.env),before)  # Checking is NOT batch acceptance.
                result=r.record_output({'tool':'apply_candidate','context_ref':r.head['context_ref'],
                    'request_id':'fixed-apply','candidate_ref':proposal['candidate_ref']})
                self.assertEqual(result['status'],'accepted',result)
                self.assertEqual(r.env.plan,self.fixed_plan)
                self.assertEqual(r.env.batch_state['capacity_watermark'],before['batch_state']['active_batch']['cohort_revisions'])
                self.assertIsNone(r.env.batch_state['active_batch'])
                committed=capture(r.env);directory=r.store.path
                r.close();r=Runtime.resume_run(directory)
                self.assertEqual(capture(r.env),committed)
                feedback=r.advance()
                self.assertGreater(feedback['advanced_seconds'],0)
                self.assertNotEqual(feedback['stop_reason']['reason'],'capacity_limit')
                self.assertGreaterEqual(feedback['dispatch_count_delta'],1)
                self.assertEqual(r.env.plan,self.fixed_plan)
                checks=[event for event in r.env.trace if event['kind']=='batch_check']
                self.assertIsNone(checks[0]['reason'])
                # Dispatch may legitimately reveal new successors. The old thousands
                # of unchanged records must not be re-counted as capacity arrivals.
                self.assertLess(checks[0]['capacity']['incoming_operation_count'],10)
                audit=audit_opportunity_coverage(r.env.trace,batching_policy=policy(r.env))
                self.assertTrue(audit['valid'],audit['errors'][:8])
                self.assertTrue(audit_plan_sources(r.env.trace)['valid'])
                self.assertEqual(r.usage()['actual_model_attempts'],0)
                outcome={'group':group,'initial_state_sha256':digest(self.initial['state']),
                    'fixed_plan_sha256':digest(self.fixed_plan),'plan_tasks':13,
                    'from':702,'to':r.env.t,'advanced_seconds':feedback['advanced_seconds'],
                    'dispatches':feedback['dispatch_count_delta'],'stop_reason':feedback['stop_reason']['reason'],
                    'same_time_capacity_retrigger':False,'existing_plan_unchanged':True,
                    'incoming_operations_after_dispatch':checks[0]['capacity']['incoming_operation_count'],
                    'independent_audit_valid':audit['valid'],'model_calls':0,
                    'pending_demand_machines':len(r.env.batch_state['pending_demands'])}
                outcomes.append(outcome);self.measurements.append(outcome)
                # A forged receipt must not make omitted work disappear in audit.
                bad=deepcopy(r.env.trace)
                receipt=next(e for e in bad if e['kind']=='planning_batch_accepted')
                receipt['unassigned_operation_ids']=[]
                self.assertFalse(audit_opportunity_coverage(bad,batching_policy=policy(r.env))['valid'])
            finally:r.close()
        self.assertEqual(outcomes[0]['to'],outcomes[1]['to'])
        self.assertEqual(outcomes[0]['dispatches'],outcomes[1]['dispatches'])

    def test_rejected_plan_cannot_consume_batch_or_change_existing_plan(self):
        r=self.make_runtime('G1')
        try:
            before=capture(r.env);delta=self.fixed_delta(r)
            delta['plan_header']['valid_until']=822
            self.assertEqual(self.submit(r,delta)['status'],'rejected')
            self.assertEqual(capture(r.env),before)
            self.assertEqual(r.env.batch_state['capacity_watermark'],{})
        finally:r.close()

    def test_genuine_cold_runtime_enters_initial_strategy(self):
        r=Runtime.start_new(ROOT/'.tmp'/('cold-'+uuid.uuid4().hex),experiment_config('G1'),
                            experiment_id='offline-cold-start')
        try:
            self.assertIsNone(r.env.plan)
            self.assertEqual(r.env.batch_state['active_batch']['strategy'],'initial')
            self.assertEqual(r.usage()['actual_model_attempts'],0)
            self.assertEqual(r.env.t,0)
        finally:r.close()
