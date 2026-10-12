"""Static-authored tiny shared-start tests, never a real factory or warm-up.

The original snapshot/runtime can only be exercised in a later registered serial
window. FakeEnv below tests storage, wrapper routing and full-state equality; it
is deliberately not an oracle for physical legality or observation causality.
"""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.smt_fullfab import shared_start as s


def raw(value):return json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()+b'\n'
def sha(value):return hashlib.sha256(value).hexdigest()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.source=self.root/'source';self.data=self.root/'data';self.data.mkdir()
        self.out=self.root/'package';self.snapshot_path=self.root/'original_snapshot.json';self.trace_path=self.root/'original_trace.jsonl'
        deps={}
        for name in ('src/smt_fullfab/environment.py','src/smt_fullfab/observation.py','src/smt/environment.py','vendor/tiny/physics.py'):
            p=self.source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'# tiny original dependency, never imported\n')
            deps[name]=sha(p.read_bytes())
        for name in s.WRAPPER_FILES:
            src=Path(s.__file__).resolve().parents[2]/name;p=self.source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(src.read_bytes())
        (self.data/'tiny.txt').write_bytes(b'original data, never loaded\n');data={'tiny.txt':sha((self.data/'tiny.txt').read_bytes())}
        self.contract={'schema':s.SCHEMA+'-generation-contract','shared_start_id':'tiny_shared_1701','seed':1701,
            'evaluation':{'absolute_start':17.0,'absolute_end':77.0,'physical_episode_end':77.0,
                          'period_anchor':17.0,'period_seconds':10.0,'plan_seconds':40.0,'lookahead_depth':2},
            'policy':'predeclared synthetic reference fixture only','steady_state_claim':False}
        machines=[{'id':mid,'group':'physical','family':'tiny'} for mid in range(913)]
        machines.append({'id':913,'group':'Delay_32','family':'delay'})
        manifest={'machines':machines,'physical_machines':913,'controlled_machine_ids':list(range(913)),
            'seed':1701,'horizon':77.0,'fullfab_version':s.SNAPSHOT_VERSION,
            'outside_policy':'virtual-delay-only; no background production','data_hashes':data}
        task={'id':'done_dispatch','machine':0,'not_before':0.,'lot_ids':['L'],'steps':[1],'visits':[1]}
        plan={'version':'warmup-1','created_at':0.,'valid_until':17.,'freeze_until':0.,'scope':list(range(913)),
              'tasks':[task],'holds':[],'reason':'original explicit warmup'}
        trace=[{'seq':0,'time':0.,'kind':'initial','manifest':manifest},
               {'seq':1,'time':0.,'kind':'plan_committed','plan':plan},
               {'seq':2,'time':1.,'kind':'dispatch','job':0,'machine':0,'lots':['L'],'plan_version':'warmup-1','plan_task_id':'done_dispatch'},
               {'seq':3,'time':1.,'kind':'time_advance','to':17.}]
        state={'seed':1701,'horizon':77.,'t':17.,'seq':5,'dispatch_id':1,'decisions':1,'releases':1,
            'completed':[],'finished':False,'wait_until':0.,'lots':{'L':{'status':'processing','visits':{'1':1},'dedications':{'2':0}}},
            'machine_state':{str(mid):{'ready':30. if mid==0 else 0.,'down_until':0.,'setup':'original','min_left':2,'min_setup':'original','last_token':4} for mid in range(914)},
            'jobs':{'0':{'machine':0,'lots':['L'],'start':1.,'process_end':30.,'lot_end':34.,'token':2,'done':False,'controlled':True}},
            'calendars':{'private-calendar':{'occurrence':7,'length':{'type':'constant','c':5}}},
            'pm_counters':{'0':[{'remaining':9,'occurrence':2}]},'queue_area':123.5,'last_area_t':0.,'manifest':manifest,
            'plan':plan,'observation_start':0.,'q':[[30.,2,'process_free',{'job':0,'token':2}],
                [34.,3,'lot_done',{'job':0,'token':2}],[31.,4,'process_free',{'job':0,'token':1}]],
            'waiting':{'tiny':[]},'processing_by_machine':{'0':[0]},'stats':{'dispatches':1},
            'executed_tasks':[['warmup-1','done_dispatch']],'plan_versions':['warmup-1'],'trace':trace}
        self.snapshot={'schema':s.SNAPSHOT_SCHEMA,'version':s.SNAPSHOT_VERSION,'implementation_sha256':deps,
            'physics_sha256':deps['src/smt/environment.py'],'data_hashes':data,'state':state,
            'state_sha256':s.digest(state),'random_mechanism':s.RANDOM_MECHANISM,
            'initialization':'official WIP cold start; any prehistory is retained, not asserted steady state'}
        self.update_inputs()
        self.load_count=0;self.environments=[];self.mutation=None;self.observe_mutation=None

    def update_inputs(self):
        self.snapshot['state_sha256']=s.digest(self.snapshot['state'])
        self.snapshot_path.write_bytes(b' '+raw(self.snapshot))
        self.trace_path.write_bytes(b''.join(b' '+raw(event) for event in self.snapshot['state']['trace']))
        self.snapshot_sha=sha(self.snapshot_path.read_bytes());self.trace_sha=sha(self.trace_path.read_bytes())
        evidence={
            'generation_contract':self.contract,
            'boundary':{'schema':s.SCHEMA+'-boundary','snapshot_sha256':self.snapshot_sha,'state_sha256':self.snapshot['state_sha256'],
                'trace_sha256':self.trace_sha,'time':17.,'drained_events_through':17.,'active_task':None,'inflight_actions':[],
                'phase':'paused_between_executor_calls','last_stop':{'reason':'periodic_replan','time':17.}},
            'shared_cost':{'shared_start_id':self.contract['shared_start_id'],'cost_scope':'shared_scenario_construction_once',
                           'resources':{'wall_seconds':None,'unknown_costs_retained':True}},
            'prehistory_audit':{'snapshot_sha256':self.snapshot_sha,'trace_sha256':self.trace_sha,'valid':True,'errors':[],
                                'fixture_only_not_physical_audit':True}}
        self.evidence={}
        for name,value in evidence.items():
            path=self.root/(name+'.json');path.write_bytes(raw(value));self.evidence[name]={'path':path,'sha256':sha(path.read_bytes())}

    def create(self):
        return s.create_shared_start(snapshot_path=self.snapshot_path,trace_path=self.trace_path,output_dir=self.out,
            contract=self.contract,expected_snapshot_sha256=self.snapshot_sha,expected_trace_sha256=self.trace_sha,
            evidence=self.evidence,source_root=self.source,data_dir=self.data)

    def runtime(self):
        owner=self
        class FakeEnv:
            @classmethod
            def from_snapshot(cls,path,*,trace_path=None,data_dir=None):
                owner.load_count+=1;env=cls();value=json.loads(Path(path).read_bytes())
                for name,item in deepcopy(value['state']).items():setattr(env,name,item)
                env.active_task=None;env.trace_path=Path(trace_path);env.advance_calls=[];env.commit_calls=[]
                env._emit('snapshot_loaded',snapshot_sha256=value['state_sha256'],prefix_event_count=len(env.trace))
                env.trace_path.write_bytes(b''.join(raw(event) for event in env.trace))
                if owner.mutation:owner.mutation(env)
                owner.environments.append(env);return env
            def _emit(self,kind,**kw):self.trace.append({'seq':len(self.trace),'time':self.t,'kind':kind,**kw})
            def commit_plan(self,plan):
                self.commit_calls.append(deepcopy(plan))
                if plan.get('reason')=='reject':raise ValueError('original executor rejected plan')
                self.plan=deepcopy(plan);self.plan_versions.append(plan['version']);self.decisions+=1
                self._emit('plan_committed',plan=deepcopy(plan))
                with self.trace_path.open('ab') as stream:stream.write(raw(self.trace[-1]))
                return s.digest(plan)
            def advance_plan(self,until):self.advance_calls.append(until);return {'original_executor_called':True,'until':until}
        envmodule=SimpleNamespace(VERSION=s.SNAPSHOT_VERSION,snapshot_dependencies=lambda:deepcopy(self.snapshot['implementation_sha256']),FullFabEnvironment=FakeEnv)
        writer=SimpleNamespace(_state_view=lambda env:{key:getattr(env,key) for key in s.STATE_FIELDS},_chunks=lambda view:iter([s.canonical(view)]))
        def observe(env,*,plan_seconds,lookahead_depth):
            if owner.observe_mutation:owner.observe_mutation(env)
            return {'schema':'smt-fullfab-problem-2','time':env.t,'scope':list(range(913)),'frozen_tasks':[],
                'machines':[{'machine':0,'currently_busy':True,'available_at':env.t+10.}],
                'operations':[],'horizon_end':env.t+plan_seconds,'lookahead_depth':lookahead_depth}
        return envmodule,writer,SimpleNamespace(build_problem=observe)

    def restore(self,ref,arm='A',name=None):
        with patch.object(s,'_runtime',side_effect=self.runtime):
            return s.restore_shared_start(self.out,expected_manifest_sha256=ref['manifest_sha256'],
                branch_dir=self.root/(name or 'branch_'+arm),branch_identity={'arm':arm,'run_id':'run_'+arm,'registration_sha256':'a'*64})

    def new_plan(self):
        plan=deepcopy(self.snapshot['state']['plan']);plan.update(version='new-arm-plan',created_at=17.,freeze_until=17.,valid_until=37.)
        plan['tasks']=[];plan['holds']=[];return plan


class PackageTests(Fixture):
    def test_original_raw_snapshot_trace_dependencies_and_unknown_cost_are_kept(self):
        with patch.object(s,'_runtime',side_effect=AssertionError('packaging must not construct/import runtime')):ref=self.create()
        manifest=s.read_shared_start(self.out,expected_manifest_sha256=ref['manifest_sha256'])
        self.assertEqual((self.out/'snapshot.json').read_bytes(),self.snapshot_path.read_bytes())
        self.assertEqual((self.out/'prehistory.jsonl').read_bytes(),self.trace_path.read_bytes())
        for name,expected in self.snapshot['implementation_sha256'].items():self.assertEqual(sha((self.out/'source'/name).read_bytes()),expected)
        self.assertEqual(manifest['boundary_summary']['processing_production_job_ids'],[0])
        self.assertEqual(manifest['boundary_summary']['original_observation_start'],0.)
        self.assertTrue(manifest['adapter_integration_pending']);self.assertFalse(manifest['steady_state_certified'])
        self.assertFalse(manifest['prior_physical_audit_independently_replayed'])
        self.assertIsNone(s.read_json(self.out/'evidence/shared_cost.json')[0]['resources']['wall_seconds'])

    def test_terminal_or_horizon_extension_is_rejected_not_rewritten(self):
        self.snapshot['state']['finished']=True;self.update_inputs()
        with self.assertRaises(s.SharedStartError):self.create()
        self.assertFalse(self.out.exists());self.assertTrue(self.snapshot['state']['finished'])

    def test_T1_less_than_H_or_T0_zero_is_outside_v1(self):
        for field,value in (('physical_episode_end',78.),('absolute_start',0.)):
            c=deepcopy(self.contract);c['evaluation'][field]=value
            with self.subTest(field=field),self.assertRaises(s.SharedStartError):s.validate_contract(c)

    def test_seed_or_snapshot_hash_changes_are_rejected(self):
        self.snapshot['state']['seed']=1702;self.update_inputs()
        with self.assertRaises(s.SharedStartError):self.create()

    def test_nonempty_cross_boundary_frozen_commitment_has_specific_refusal(self):
        plan=self.snapshot['state']['plan'];plan['freeze_until']=18.;plan['valid_until']=20.
        plan['tasks'].append({'id':'not-started','machine':1,'not_before':17.,'lot_ids':['Q'],'steps':[1],'visits':[1]})
        self.update_inputs()
        with self.assertRaisesRegex(s.SharedStartError,'cross-boundary frozen'):self.create()
        self.assertEqual(plan['freeze_until'],18.);self.assertEqual(len(plan['tasks']),2)

    def test_live_nonfrozen_plan_is_not_silently_expired_or_held(self):
        self.snapshot['state']['plan']['valid_until']=20.;self.update_inputs()
        with self.assertRaisesRegex(s.SharedStartError,'naturally expire'):self.create()

    def test_undrained_or_reordered_queue_is_not_cleaned(self):
        self.snapshot['state']['q'][0][0]=17.;self.update_inputs()
        with self.assertRaisesRegex(s.SharedStartError,'undrained'):self.create()
        self.assertEqual(self.snapshot['state']['q'][0][0],17.)

    def test_invalid_heap_and_duplicate_sequence_are_rejected(self):
        original=deepcopy(self.snapshot['state']['q'])
        for queue in ([original[1],original[0],original[2]],[original[0],original[0]]):
            self.snapshot['state']['q']=queue;self.update_inputs()
            with self.subTest(queue=queue),self.assertRaises(s.SharedStartError):self.create()

    def test_idle_or_missing_real_processing_job_is_not_accepted_as_nonidle(self):
        self.snapshot['state']['processing_by_machine']={};self.update_inputs()
        with self.assertRaisesRegex(s.SharedStartError,'real indexed'):self.create()

    def test_job_history_missing_or_lot_contradiction_is_rejected(self):
        self.snapshot['state']['jobs']={};self.update_inputs()
        with self.assertRaises(s.SharedStartError):self.create()

    def test_original_trace_replacement_or_extra_terminal_is_rejected(self):
        self.snapshot['state']['trace'].append({'seq':4,'time':17.,'kind':'terminal'});self.update_inputs()
        with self.assertRaisesRegex(s.SharedStartError,'terminal'):self.create()

    def test_boundary_atomic_action_attestation_must_be_empty(self):
        p=self.evidence['boundary']['path'];value=s.read_json(p)[0];value['active_task']={'id':'unfinished-dispatch'};p.write_bytes(raw(value))
        self.evidence['boundary']['sha256']=sha(p.read_bytes())
        with self.assertRaisesRegex(s.SharedStartError,'non-atomic'):self.create()

    def test_physical_audit_reference_cannot_be_another_snapshot(self):
        p=self.evidence['prehistory_audit']['path'];value=s.read_json(p)[0];value['snapshot_sha256']='0'*64;p.write_bytes(raw(value))
        self.evidence['prehistory_audit']['sha256']=sha(p.read_bytes())
        with self.assertRaisesRegex(s.SharedStartError,'audit evidence'):self.create()

    def test_original_source_or_data_mismatch_leaves_failed_new_package(self):
        (self.data/'tiny.txt').write_bytes(b'replaced data')
        with self.assertRaises(s.SharedStartError):self.create()
        self.assertTrue((self.out/'failure.json').exists())
        with self.assertRaises(FileExistsError):self.create()

    def test_existing_package_is_not_recreated(self):
        ref=self.create();before=(self.out/'manifest.json').read_bytes()
        with self.assertRaises(FileExistsError):self.create()
        self.assertEqual((self.out/'manifest.json').read_bytes(),before)

    def test_member_change_after_packaging_rejects_original_readback(self):
        ref=self.create();p=self.out/'snapshot.json';p.chmod(0o644);p.write_bytes(b'{}')
        with self.assertRaises(s.SharedStartError):s.read_shared_start(self.out,expected_manifest_sha256=ref['manifest_sha256'])

    def test_manifest_replacement_after_first_bound_read_is_not_reanchored(self):
        ref=self.create();original_read=s.read_json;path=self.out/'manifest.json';seen=[]
        def replaced_read(p,*args,**kwargs):
            value,receipt=original_read(p,*args,**kwargs)
            if Path(p)==path and not seen:
                seen.append(deepcopy(value));changed=deepcopy(value)
                changed['package_wall_seconds_before_publication']+=1.
                replacement=self.root/'replacement.json';replacement.write_bytes(raw(changed));replacement.replace(path)
            return value,receipt
        with patch.object(s,'read_json',side_effect=replaced_read),self.assertRaisesRegex(s.SharedStartError,'original membership/hash'):
            s.read_shared_start(self.out,expected_manifest_sha256=ref['manifest_sha256'])
        self.assertEqual(len(seen),1);self.assertNotEqual(sha(path.read_bytes()),ref['manifest_sha256'])
        self.assertEqual({k:v for k,v in s._files(self.out).items() if k!='manifest.json'},seen[0]['members'])

    def test_manifest_replacement_before_final_readback_inventory_is_rejected(self):
        ref=self.create();original_check=s._check_evidence;path=self.out/'manifest.json'
        manifest=s.read_json(path)[0];changed=deepcopy(manifest);changed['package_wall_seconds_before_publication']+=1.
        def replaced_check(*args,**kwargs):
            result=original_check(*args,**kwargs)
            replacement=self.root/'replacement.json';replacement.write_bytes(raw(changed));replacement.replace(path)
            return result
        with patch.object(s,'_check_evidence',side_effect=replaced_check),self.assertRaisesRegex(s.SharedStartError,'complete readback'):
            s.read_shared_start(self.out,expected_manifest_sha256=ref['manifest_sha256'])
        self.assertNotEqual(sha(path.read_bytes()),ref['manifest_sha256'])
        self.assertEqual({k:v for k,v in s._files(self.out).items() if k!='manifest.json'},manifest['members'])

    def test_manifest_replacement_after_publish_retains_failure_without_success(self):
        original_publish=s.publish;published=[]
        def replaced_publish(path,value):
            original_sha=original_publish(path,value)
            if Path(path)==self.out/'manifest.json':
                published.append((original_sha,deepcopy(value)));changed=deepcopy(value)
                changed['package_wall_seconds_before_publication']+=1.
                replacement=self.root/'replacement.json';replacement.write_bytes(raw(changed));replacement.replace(path)
            return original_sha
        with patch.object(s,'publish',side_effect=replaced_publish),self.assertRaisesRegex(s.SharedStartError,'during publication'):
            self.create()
        self.assertEqual(len(published),1);self.assertTrue((self.out/'failure.json').is_file())
        self.assertNotEqual(sha((self.out/'manifest.json').read_bytes()),published[0][0])
        self.assertEqual({k:v for k,v in s._files(self.out).items() if k not in ('manifest.json','failure.json')},published[0][1]['members'])
        with self.assertRaisesRegex(s.SharedStartError,'creation failed'):
            s.read_shared_start(self.out,expected_manifest_sha256=published[0][0])

    def test_missing_wrappers_or_rehashed_data_cannot_certify_parallel_manifest_fields(self):
        ref=self.create();manifest=s.read_json(self.out/'manifest.json')[0]
        p=self.out/'data/tiny.txt';p.chmod(0o644);p.write_bytes(b'replacement')
        manifest['members']['data/tiny.txt']={'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size}
        path=self.out/'manifest.json';path.write_bytes(raw(manifest))
        with self.assertRaisesRegex(s.SharedStartError,'dependency/data hashes'):
            s.read_shared_start(self.out,expected_manifest_sha256=sha(path.read_bytes()))

    def test_strict_JSON_rejects_duplicate_and_exponent_overflow(self):
        for value in (b'{"x":1,"x":2}',b'{"x":1e999}',b'{"x":NaN}'):
            with self.subTest(value=value),self.assertRaises((s.SharedStartError,ValueError)):s.strict(value)


class BranchTests(Fixture):
    def test_three_independent_exact_restores_and_same_public_problem(self):
        ref=self.create();branches=[self.restore(ref,arm) for arm in ('A','B','C')]
        self.assertEqual(self.load_count,3)
        self.assertEqual(len({b.receipt['first_public_problem_sha256'] for b in branches}),1)
        self.assertEqual(branches[0].problem(),branches[1].problem())
        self.environments[0].jobs['0']['token']=99
        self.assertEqual(self.environments[1].jobs['0']['token'],2)
        for branch in branches:
            self.assertEqual(branch.receipt['original_state_sha256'],self.snapshot['state_sha256'])
            self.assertEqual(branch.receipt['source_observation_start'],0.)
            self.assertEqual(branch.receipt['evaluation_window']['period_anchor'],17.)
            self.assertFalse(branch.receipt['restored_prefix_bytes_equal_original'])
            self.assertTrue(branch.receipt['prehistory_event_content_order_equal'])
            self.assertFalse(branch.receipt['branch_cost']['shared_cost_included_in_branch_increment'])
        self.assertEqual((self.out/'snapshot.json').read_bytes(),self.snapshot_path.read_bytes())

    def test_first_commit_gate_no_virtual_or_production_advance_before_model_plan(self):
        ref=self.create();branch=self.restore(ref)
        with self.assertRaisesRegex(s.SharedStartError,'first explicit'):branch.advance_plan(27.)
        self.assertEqual(self.environments[0].advance_calls,[])
        self.assertEqual(self.environments[0].plan,self.snapshot['state']['plan'])

    def test_original_executor_gets_exact_plan_and_advance_without_defaults(self):
        ref=self.create();branch=self.restore(ref);plan=self.new_plan();before=deepcopy(plan)
        branch.commit_plan(plan);result=branch.advance_plan(27.)
        env=self.environments[0];self.assertEqual(env.commit_calls,[before]);self.assertEqual(plan,before)
        self.assertEqual(env.advance_calls,[27.]);self.assertTrue(result['original_executor_called'])
        self.assertEqual(env.trace[:4],self.snapshot['state']['trace'])
        receipt=s.read_json(self.root/'branch_A/first_commit.json')[0]
        self.assertEqual(receipt['trace_event_index'],5);self.assertEqual(receipt['plan_sha256'],s.digest(plan))
        self.assertEqual(env.executed_tasks,[['warmup-1','done_dispatch']])

    def test_no_hidden_plan_is_created_on_problem_query(self):
        ref=self.create();branch=self.restore(ref);before=deepcopy(self.environments[0].plan)
        for _ in range(3):branch.problem()
        self.assertEqual(self.environments[0].commit_calls,[]);self.assertEqual(self.environments[0].plan,before)
        self.assertNotIn('q',branch.problem());self.assertNotIn('snapshot',branch.problem())

    def test_existing_branch_claim_never_replays_restore(self):
        ref=self.create();self.restore(ref)
        with self.assertRaises(FileExistsError):self.restore(ref)
        self.assertEqual(self.load_count,1)

    def test_wrong_live_dependency_rejects_before_constructing(self):
        ref=self.create();runtime=self.runtime();runtime[0].snapshot_dependencies=lambda:{'wrong':'0'*64}
        with patch.object(s,'_runtime',return_value=runtime),self.assertRaises(s.SharedStartError):
            s.restore_shared_start(self.out,expected_manifest_sha256=ref['manifest_sha256'],branch_dir=self.root/'branch',
                branch_identity={'arm':'A','run_id':'run_A','registration_sha256':'a'*64})
        self.assertEqual(self.load_count,0)

    def test_original_rng_identity_heap_jobs_horizon_finished_and_history_cannot_change(self):
        changes=[lambda e:setattr(e,'finished',True),lambda e:setattr(e,'horizon',88.),lambda e:setattr(e,'q',[]),
            lambda e:e.jobs['0'].__setitem__('token',0),lambda e:e.lots['L']['visits'].__setitem__('1',0),
            lambda e:e.pm_counters['0'][0].__setitem__('occurrence',0),lambda e:setattr(e,'executed_tasks',[])]
        ref=self.create()
        for i,change in enumerate(changes):
            self.mutation=change
            with self.subTest(i=i),self.assertRaisesRegex(s.SharedStartError,'full original restored state'):
                self.restore(ref,name='bad_'+str(i))

    def test_observation_may_not_mutate_restored_physics(self):
        ref=self.create();self.observe_mutation=lambda e:e.jobs['0'].__setitem__('token',99)
        with self.assertRaisesRegex(s.SharedStartError,'altered original'):self.restore(ref)

    def test_before_first_commit_detects_out_of_band_state_changes(self):
        ref=self.create();branch=self.restore(ref);self.environments[0].q.clear()
        with self.assertRaisesRegex(s.SharedStartError,'changed before first'):branch.commit_plan(self.new_plan())
        self.assertEqual(self.environments[0].commit_calls,[])

    def test_rejected_or_unknown_commit_never_silently_retries(self):
        ref=self.create();branch=self.restore(ref);plan=self.new_plan();plan['reason']='reject'
        with self.assertRaises(ValueError):branch.commit_plan(plan)
        with self.assertRaisesRegex(s.SharedStartError,'unknown'):branch.commit_plan(self.new_plan())
        self.assertEqual(len(self.environments[0].commit_calls),1)

    def test_commit_occurs_before_receipt_failure_and_is_not_replayed(self):
        ref=self.create();branch=self.restore(ref);publish=s.publish
        def failing(path,value):
            if Path(path).name=='first_commit.json':raise OSError('tiny publication failure')
            return publish(path,value)
        with patch.object(s,'publish',side_effect=failing),self.assertRaises(OSError):branch.commit_plan(self.new_plan())
        self.assertEqual(self.environments[0].plan['version'],'new-arm-plan')
        with self.assertRaises(s.SharedStartError):branch.advance_plan(27.)
        with self.assertRaises(s.SharedStartError):branch.commit_plan(self.new_plan())
        self.assertEqual(len(self.environments[0].commit_calls),1)

    def test_absolute_period_anchor_is_nonzero_and_events_do_not_move_it(self):
        ref=self.create();branch=self.restore(ref);self.assertEqual(branch.next_period_boundary(),27.)
        self.environments[0].t=22.;self.assertEqual(branch.next_period_boundary(),27.)
        self.environments[0].t=27.;self.assertEqual(branch.next_period_boundary(),37.)


if __name__=='__main__':unittest.main()
