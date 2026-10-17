"""Offline dynamic collection fixtures; no model/scheduling-quality evidence."""
from copy import deepcopy
import heapq
import json
import unittest
import uuid
import zlib
from types import SimpleNamespace

from src.smt_fullfab.environment import FullFabEnvironment
from src.smt_fullfab.audit import audit_opportunity_coverage, audit_plan_sources
from src.smt_fullfab.harness.batch_window import configure, advance, observe_demands, capacity_measurement
from src.smt_fullfab.harness.capacity_config import experiment_config, POLICY
from src.smt_fullfab.harness.capacity_prompt import PublicPacket, INSTRUCTIONS
from src.smt_fullfab.harness.contracts import ROOT, HarnessError, validate_config, encode
from src.smt_fullfab.harness.factory import restore, capture
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.store import Store
from src.smt_fullfab.harness.transport import PROTOCOL_TEXT, prompt, command, call, _prepare_request
from src.smt_fullfab.harness.presentation import pack, unpack
from src.smt_fullfab.plan_delta import ORDER_POLICY


def fixture_context(key=2403):
    return json.loads(zlib.decompress((ROOT/'fixtures/contexts'/f'{key}.json.z').read_bytes()))


def fixture_initial():
    return json.loads(zlib.decompress((ROOT/'fixtures/initial/singleton_2403.json.z').read_bytes()))


def fixture_plan(env, *, version='offline-fixture', tasks=(), holds=(), until=None):
    return {'version':version,'created_at':env.t,'valid_until':until or env.horizon,'freeze_until':env.t,
            'reason':'Explicit offline fixture, not model output','scope':sorted(env.physical),
            'tasks':list(tasks),'holds':list(holds)}


def policy(env):
    cfg=env.batch_state['capacity']
    return {'policy':POLICY,'anchor':env.batch_state['anchor'],**{k:cfg[k] for k in
        ('max_ready_wait_seconds','planning_lead_seconds','input_token_budget','capacity_trigger_fraction',
         'forecast_min_interval_seconds','forecast_lookahead_seconds')}}


def isolated_gap_plan(env, version='offline-fixture'):
    return fixture_plan(env,version=version,holds=[{'machine':mid,'until':env.horizon,
        'reason':'Explicit fixture hold for isolating machine 856'} for mid in sorted(env.physical) if mid!=856])


def op(i, mid, payload=''):
    return {'operation_id':str(i)+':1:1','lot_id':str(i),'step':1,'visit':1,'family':'F',
            'eligible_machines':[mid],'predecessor_ids':[],'processing_seconds':30,
            'occupation_seconds':30,'transport_seconds':0,'release_time':0,'payload':payload}


class ToyFactory:
    _pending=FullFabEnvironment._pending;_active_holds=FullFabEnvironment._active_holds
    _run_planned_now=FullFabEnvironment._run_planned_now;_gaps=FullFabEnvironment._gaps
    def __init__(self, *, gap=True, events=(), busy_until=0, horizon=600, group='G1'):
        self.t=0.;self.horizon=float(horizon);self.finished=False;self.trace=[];self.gap=gap
        self.physical={1,2};self.machines={i:SimpleNamespace(family='F') for i in self.physical}
        self.machine_state={1:{'ready':12,'down_until':0},2:{'ready':busy_until,'down_until':0}}
        self.public_available={1:12,2:busy_until}
        self.lots={lid:{'status':'waiting','step':0,'visits':{'1':1}} for lid in ['a','b']}
        self.executed_tasks=set();self.active_task=None;self.last_stop=None
        self.q=[(12,'release'),(24,'release'),*events];heapq.heapify(self.q)
        tasks=[{'id':lid,'machine':1,'lot_ids':[lid],'steps':[1],'visits':[1],
                'operation_ids':[lid+':1:1'],'not_before':0} for lid in ['a','b']]
        self.plan=fixture_plan(self,tasks=tasks)
        configure(self,anchor=0,capacity=experiment_config(group)['capacity_experiment'])
    def problem(self,**kwargs):
        ops=[op(lid,1) for lid,lot in self.lots.items() if lot['status']=='waiting']
        if self.gap: ops.append(op('unplanned',2))
        return {'time':self.t,'horizon_end':self.horizon,'scope':sorted(self.physical),
                'machines':[{'machine':mid,'family':'F','currently_busy':self.machine_state[mid]['ready']>self.t,
                             'currently_down':False,'available_at':max(self.t,self.public_available[mid])} for mid in sorted(self.physical)],
                'operations':ops}
    def _emit(self,kind,**kw): self.trace.append({'kind':kind,'time':self.t,**kw})
    def _outside(self):pass
    def _validate(self,mid,lids):
        assert self.machine_state[mid]['ready']<=self.t
        assert all(self.lots[lid]['status']=='waiting' for lid in lids)
    def _dispatch(self,mid,lids,source):
        self._emit('dispatch',machine=mid,lots=lids,task=self.active_task['id'])
        for lid in lids:self.lots[lid]['status']='processing'
        self.machine_state[mid]['ready']=self.t+12;self.public_available[mid]=self.t+12
    def has_legal(self,mid):return mid==2 and self.gap and self.machine_state[mid]['ready']<=self.t
    def eligible(self,mid):return ['unplanned'] if self.has_legal(mid) else []
    def _events_to(self,t):
        self.t=t
        while self.q and self.q[0][0]<=t:
            _,kind=heapq.heappop(self.q)
            if kind=='invalidate':self.lots['b']['status']='done'
            if kind=='resolve_gap':self.gap=False
            if kind=='open_gap':self.gap=True
    def metrics(self):return {}


def scaled_context(n=2000):
    machines=[{'machine':i,'family':'F','available_at':10000,'currently_busy':True,'currently_down':False,
               'qualification':{'serial':i,'observed':True}} for i in range(n)]
    ops=[op(i,i,' '.join(f'constraint_{i}_{j}' for j in range(35))) for i in range(n)]
    # Independent IDs/records stress capacity; not a validated 2,000-machine factory.
    return {'problem':{'time':0,'horizon_end':20000,'scope':list(range(n)),'machines':machines,'operations':ops},
            'base_plan':{'version':'fixture','created_at':0,'valid_until':20000,'freeze_until':0,'reason':'fixture','scope':list(range(n)),'tasks':[],'holds':[]},
            'execution_state':{'dispatched_task_ids':[]},'problem_ref':'fixture:problem',
            'facts_ref':'fixture:facts','base_plan_ref':'fixture:base',
            'batch_demands':[{'machine':i,'family':'F','first_seen':0,'ready_since':None,
                'forecast_available_at':10000,'operation_ids':[ops[i]['operation_id']]} for i in range(n)]}


class LoadFactory:
    """Observed demand arrives every 40 seconds. Existing production is busy."""
    def __init__(self,group):
        self.t=0.;self.horizon=20000.;self.finished=False;self.trace=[];self.last_stop=None
        self.sample=scaled_context();self.physical=set(range(2000));self.plan=self.sample['base_plan']
        self.executed_tasks=set();self.lots={};self.count=0
        self.q=[(40*i,i) for i in range(1,11)]
        configure(self,anchor=0,capacity=experiment_config(group)['capacity_experiment'])
    def _pending(self):return {}
    def _active_holds(self):return {}
    def _gaps(self):return []
    def _outside(self):pass
    def _run_planned_now(self):pass
    def _emit(self,kind,**kw):self.trace.append({'kind':kind,'time':self.t,**kw})
    def problem(self,**kw):return {**self.sample['problem'],'time':self.t,'operations':self.sample['problem']['operations'][:self.count]}
    def _events_to(self,t):
        self.t=t
        while self.q and self.q[0][0]<=t:
            _,index=heapq.heappop(self.q);self.count=index*200
    def metrics(self):return {}


class CapacityAndIsolationTests(unittest.TestCase):
    measurements=[]
    def test_only_capacity_treatments_differ(self):
        a,b=experiment_config('G1'),experiment_config('G2')
        for cfg in (a,b):
            validate_config(cfg)
            self.assertIsNone(cfg['capacity_experiment']['collection_max_seconds'])
            for k in ('group','model_context_window','input_token_budget','model_auto_compact_token_limit'):cfg['capacity_experiment'].pop(k)
        self.assertEqual(a,b)
    def test_explicit_cli_window_overrides(self):
        for group in ('G1','G2'):
            c=experiment_config(group)['capacity_experiment']
            argv=command(ROOT/'.tmp/dry-command',binary='DO-NOT-EXECUTE',model='gpt-6-astra',effort='medium',
                context_window=c['model_context_window'],auto_compact=c['model_auto_compact_token_limit'])
            self.assertIn('--ignore-user-config',argv)
            self.assertIn('model_context_window='+str(c['model_context_window']),argv)
            self.assertIn('model_auto_compact_token_limit='+str(c['model_auto_compact_token_limit']),argv)
    def test_model_and_original_store_rejected_before_effects(self):
        for fn in (call,_prepare_request):
            with self.assertRaises(HarnessError) as caught:fn(None)
            self.assertEqual(caught.exception.code,'offline_only')
        p=ROOT/'.tmp'/('forbidden-'+uuid.uuid4().hex)
        with self.assertRaises(HarnessError):Runtime.start_new(p,experiment_config('G1'),experiment_id='forbidden',mode='model')
        self.assertFalse(p.exists())
        with self.assertRaises(HarnessError):Store(ROOT.parent.parent/'experiment_round2_3datasets/artifacts/never-open')
    def test_2000_machine_overflow_preserves_more_demand_in_larger_packet(self):
        c=scaled_context();builder=PublicPacket(c);results=[]
        for group in ('G1','G2'):
            budget=experiment_config(group)['capacity_experiment']['input_token_budget']
            out=builder.fit({},prefix=PROTOCOL_TEXT+INSTRUCTIONS,budget=budget,reserve=10000)
            self.assertLessEqual(out['budgeted_input_tokens'],budget)
            self.assertGreater(out['inline_operations'],0);self.assertLess(out['inline_operations'],2000)
            builder.verify(out['frame']);results.append(out)
            self.measurements.append({'fixture':'synthetic_2000_machines','group':group,
                **{k:v for k,v in out.items() if k not in ('text','frame')}})
        self.assertGreater(results[1]['inline_operations'],results[0]['inline_operations'])
        self.assertGreater(results[1]['local_prompt_tokens'],272000)
    def test_saved_states_select_demand_and_preserve_dependency_bundles(self):
        for key in (702,1800,2403,2598):
            c=fixture_context(key)
            gaps=(c.get('trigger') or {}).get('machines',[])
            mid=gaps[0]['machine'] if gaps else c['problem']['operations'][0]['eligible_machines'][0]
            ids=[o['operation_id'] for o in c['problem']['operations'] if mid in o['eligible_machines']]
            c['batch_demands']=[{'machine':mid,'operation_ids':ids,'first_seen':c['time']}]
            builder=PublicPacket(c)
            out=builder.fit({},prefix=PROTOCOL_TEXT+INSTRUCTIONS,budget=220000,reserve=10000)
            self.assertLess(out['demand_operations'],len(c['problem']['operations']))
            builder.verify(out['frame'])
    def test_single_oversized_bundle_uses_readable_reference(self):
        c=scaled_context(1);c['problem']['operations'][0]['payload']=' '.join(str(i) for i in range(100000))
        out=PublicPacket(c).fit({},prefix='',budget=3000,reserve=100)
        self.assertTrue(out['oversized_bundle_requires_paged_read'])
        self.assertEqual(out['frame']['public_refs']['problem_ref'],'fixture:problem')
        self.assertLessEqual(out['budgeted_input_tokens'],3000)
    def test_oversized_resource_details_do_not_require_all_machines_inline(self):
        c=scaled_context(2000);c['problem']['operations']=c['problem']['operations'][:1]
        c['problem']['operations'][0]['eligible_machines']=list(range(2000));c['batch_demands']=c['batch_demands'][:1]
        out=PublicPacket(c).fit({},prefix='',budget=20000,reserve=1000)
        self.assertTrue(out['paged_details']);self.assertEqual(out['inline_operations'],1)
        self.assertLess(out['inline_machines'],2000)
    def test_essential_capacity_failure_is_explicit(self):
        with self.assertRaises(HarnessError):PublicPacket(scaled_context(1)).fit({},prefix='',budget=100,reserve=10)
    def test_value_tampering_detected(self):
        b=PublicPacket(scaled_context(2));p=b.frame(2,{})
        p['base_plan']['header']['version']='corrupt'
        with self.assertRaises(HarnessError):b.verify(p)
    def test_boolean_and_integer_cannot_alias_in_lossless_verification(self):
        b=PublicPacket(scaled_context(2));p=b.frame(2,{})
        rows=unpack(p['public_problem']['machines']);rows[0]['currently_busy']=1
        p['public_problem']['machines']=pack(rows)
        with self.assertRaises(HarnessError):b.verify(p)
        p=b.frame(2,{});p['public_problem']['machine_source_indices'][0]=False
        with self.assertRaises(HarnessError):b.verify(p)


class CollectionMechanismTests(unittest.TestCase):
    measurements=[]
    def test_busy_machine_runs_two_tasks_during_ready_demand_wait(self):
        e=ToyFactory();stop=advance(e,180)
        self.assertEqual((stop['reason'],e.t),('ready_wait_limit',60))
        self.assertEqual([(r['time'],r['task']) for r in e.trace if r['kind']=='dispatch'],[(12,'a'),(24,'b')])
        self.assertEqual(sum(r.get('unplanned_machine_seconds',0) for r in e.trace),60)
    def test_demand_clock_starts_at_arrival_not_a_60_second_grid(self):
        e=ToyFactory(gap=False,events=[(7,'open_gap')]);stop=advance(e,180)
        self.assertEqual((stop['reason'],e.t),('ready_wait_limit',67))
    def test_empty_replan_does_not_reset_unresolved_wait(self):
        e=ToyFactory();advance(e,180)
        e.plan=fixture_plan(e,version='still-empty')
        stop=advance(e,180)
        self.assertEqual((stop['reason'],e.t),('ready_wait_limit',60))
        self.assertEqual(e.batch_state['ready_since'],{'2':0})
    def test_no_fixed_60_second_interruption(self):
        e=ToyFactory(gap=False);version=e.plan['version'];stop=advance(e,180)
        self.assertEqual((stop['reason'],e.t),('collection_limit',180))
        self.assertEqual(e.plan['version'],version)
        self.assertFalse(any(r['reason'] for r in e.trace if r['kind']=='batch_check'))
    def test_busy_followup_is_requested_before_public_forecast_release(self):
        e=ToyFactory(busy_until=300);stop=advance(e,400)
        self.assertEqual((stop['reason'],e.t),('plan_runway',285))
        self.assertEqual(e.batch_state['ready_since'],{})
    def test_capacity_can_collect_beyond_60_and_larger_group_collects_more(self):
        stops=[]
        for group in ('G1','G2'):
            e=LoadFactory(group);stop=advance(e,500)
            self.assertEqual(stop['reason'],'capacity_limit');self.assertGreater(e.t,60)
            stops.append((e.t,e.count))
            self.measurements.append({'group':group,'stop_time':e.t,'observed_demands':e.count,'capacity':stop['capacity']})
        self.assertGreater(stops[1][0],stops[0][0]);self.assertGreater(stops[1][1],stops[0][1])
    def test_forecast_does_not_read_private_future_event_time(self):
        a=ToyFactory(busy_until=300);b=ToyFactory(busy_until=300)
        b.machine_state[2]['ready']=9876  # still publicly busy, same public forecast
        b.q.append((9876,'release'));heapq.heapify(b.q)
        for e in (a,b):
            p=e.problem();observe_demands(e,p,e._gaps())
        self.assertEqual(a.batch_state['pending_demands'],b.batch_state['pending_demands'])
        self.assertEqual(capacity_measurement(a,a.problem()),capacity_measurement(b,b.problem()))
    def test_true_invalidation_remains_immediate(self):
        e=ToyFactory(events=[(15,'invalidate')]);stop=advance(e,180)
        self.assertEqual((stop['reason'],e.t),('plan_invalidated',15))
    def test_plan_renewal_uses_validity_not_fake_queue_coverage(self):
        e=ToyFactory(gap=False);e.plan['valid_until']=100
        self.assertEqual(advance(e,180)['reason'],'plan_renewal');self.assertEqual(e.t,85)
    def test_expired_plan_stops_without_time_advance(self):
        e=ToyFactory(gap=False);e.plan['valid_until']=0
        self.assertEqual(advance(e,180)['reason'],'plan_horizon');self.assertEqual(e.t,0)
    def test_resolved_gap_removes_wait_deadline(self):
        e=ToyFactory(events=[(15,'resolve_gap')]);stop=advance(e,180)
        self.assertEqual((stop['reason'],e.t),('collection_limit',180))
        self.assertEqual(e.batch_state['ready_since'],{})


class RuntimeIntegrationTests(unittest.TestCase):
    def setUp(self):
        initial=fixture_initial();cfg=experiment_config('G1',seconds=initial['state']['horizon']-initial['state']['t'])
        self.directory=ROOT/'.tmp'/('runtime-'+uuid.uuid4().hex)
        self.r=Runtime.start_new(self.directory,cfg,experiment_id='offline-fixture-only',initial=initial)
    def tearDown(self):self.r.close()
    def action(self,obj):return self.r.record_output({'context_ref':self.r.head['context_ref'],**obj})
    def delta(self,version='fixture'):
        c=self.r.store.read('contexts',self.r.head['context_ref']);base=c['base_plan'];p=isolated_gap_plan(self.r.env,version)
        return {'plan_header':{k:v for k,v in p.items() if k not in ('tasks','holds')},'order_policy':ORDER_POLICY,
                'tasks':{'keep':{'mode':'ids','ids':[]},'cancel_ids':[t['id'] for t in base['tasks'] if t['id'] not in c['execution_state']['dispatched_task_ids']],'replace':[],'add':[]},
                'holds':{'keep':{'mode':'ids','ids':[]},'cancel_ids':['h:'+str(i) for i in range(len(base['holds']))],'replace':[],'add':p['holds']},'machine_orders':[]}
    def commit_fixture(self,version):
        out=self.action({'tool':'propose_delta','request_id':'proposal-'+version,'delta':self.delta(version)})
        self.assertEqual(out['status'],'candidate_checked',out)
        out=self.action({'tool':'apply_candidate','request_id':'apply-'+version,'candidate_ref':out['candidate_ref']})
        self.assertEqual(out['status'],'accepted',out)
    def test_propose_apply_advance_and_resume_preserve_original_wait(self):
        self.commit_fixture('one');f=self.r.advance()
        self.assertEqual(f['advanced_seconds'],60);self.assertEqual(f['stop_reason']['reason'],'ready_wait_limit')
        before=capture(self.r.env);self.r.close();self.r=Runtime.resume_run(self.directory)
        self.assertEqual(capture(self.r.env),before)
        self.commit_fixture('two');f=self.r.advance()
        self.assertEqual(f['advanced_seconds'],0);self.assertEqual(f['stop_reason']['reason'],'ready_wait_limit')
        self.assertEqual(self.r.usage()['actual_model_attempts'],0)
    def test_short_plan_rejected_without_extension(self):
        d=self.delta();d['plan_header']['valid_until']=self.r.env.t+10
        self.assertEqual(self.action({'tool':'propose_delta','request_id':'short','delta':d})['status'],'rejected')
        self.assertEqual(self.r.store.rows('commits'),[])
    def test_large_feedback_full_and_local_budget_enforced(self):
        c=self.r.store.read('contexts',self.r.head['context_ref']);ids=[str(m['machine']) for m in c['problem']['machines']]
        result=self.action({'tool':'read_entities','queries':[{'kind':'machines','ids':ids}]})
        self.assertEqual(result['status'],'ok')
        frame=json.loads(prompt(self.r).splitlines()[-1])
        self.assertEqual(unpack(frame['last_tool_feedback']['result']),result)
        self.assertGreater(len(encode(pack(result))),60000)
        self.assertLessEqual(self.r.last_capacity_measurement['budgeted_input_tokens'],220000)
        self.assertIn('full_context_metadata_ref',frame['context'])
    def test_small_history_not_cut_at_eight(self):
        c=self.r.store.read('contexts',self.r.head['context_ref'])
        for m in c['problem']['machines'][:11]:self.action({'tool':'read_entities','queries':[{'kind':'machines','ids':[str(m['machine'])],'fields':['machine']}]})
        frame=json.loads(prompt(self.r).splitlines()[-1])
        self.assertEqual(len(frame['interaction_history']['entries']),10)
        self.assertEqual(frame['interaction_history']['omitted'],0)
    def test_production_entrypoint_cannot_reserve_model_attempt(self):
        with self.assertRaises(HarnessError):self.r.reserve_attempt('no model',{})
        self.assertEqual(self.r.usage()['actual_model_attempts'],0)
    def test_both_real_prompt_paths_use_the_registered_token_budget(self):
        prompt(self.r);small=self.r.last_capacity_measurement
        initial=fixture_initial();cfg=experiment_config('G2',seconds=initial['state']['horizon']-initial['state']['t'])
        other=Runtime.start_new(ROOT/'.tmp'/('runtime-G2-'+uuid.uuid4().hex),cfg,experiment_id='offline-paired-prompt',initial=initial)
        try:
            prompt(other);large=other.last_capacity_measurement
            self.assertEqual((small['input_budget'],large['input_budget']),(220000,440000))
            self.assertGreater(large['inline_operations'],small['inline_operations'])
            self.assertEqual(other.usage()['actual_model_attempts'],0)
            from src.smt_fullfab.harness.contracts import digest
            self.assertEqual(digest(other.store.trace()[:other.manifest['prefix_events']]),other.manifest['initial_trace_sha256'])
        finally:other.close()


class IndependentBatchAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initial=fixture_initial();e=restore(initial['state'],initial['trace'])
        configure(e,anchor=e.t);e.commit_plan(isolated_gap_plan(e));e.advance_plan(e.t+90)
        cls.trace=e.trace;cls.policy=policy(e);cls.end=e.t
    def test_independent_demand_and_physical_prefix_audit(self):
        from src.smt_fullfab.harness.evaluation import audit_physical_prefix
        self.assertTrue(audit_plan_sources(self.trace)['valid'])
        report=audit_opportunity_coverage(self.trace,batching_policy=self.policy)
        self.assertTrue(report['valid'],report['errors'][:5])
        self.assertEqual(report['max_ready_wait_seconds'],60)
        self.assertEqual(report['batch_decisions'],1)
        physical=audit_physical_prefix(self.trace,self.end,{10:1,20:2,30:3},batching_policy=self.policy)
        self.assertEqual(physical['errors'],['physical: missing terminal event'])
    def test_default_audit_rejects_experimental_wait_semantics(self):
        self.assertFalse(audit_opportunity_coverage(self.trace)['valid'])
    def test_forged_timer_gap_and_decision_detected(self):
        for kind in ('omit_gap','extend_wait','reset_timer','skip_decision'):
            trace=deepcopy(self.trace)
            row=next(r for r in trace if r['kind']=='time_advance' and r.get('deferred_gap_machines'))
            if kind=='omit_gap':row['deferred_gap_machines']=[]
            elif kind=='extend_wait':row['to']=row['ready_deadline']+1
            else:
                row=[r for r in trace if r['kind']=='batch_check'][-1]
                if kind=='reset_timer':row['ready_since']={k:v+60 for k,v in row['ready_since'].items()}
                else:row['reason']=None
            report=audit_opportunity_coverage(trace,batching_policy=self.policy)
            self.assertFalse(report['valid'],kind)


if __name__=='__main__':unittest.main()
