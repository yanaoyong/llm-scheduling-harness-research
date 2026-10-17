"""Authored static-only. Tiny file/mocked process contracts; no actual factory/CP/model."""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from src.smt_fullfab import offline_A_gate_v4 as gate


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(gate.encoded(value))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class A24GateTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.root=Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.campaign=self.root/'campaign';self.campaign.mkdir()
        self.run=self.root/'run';self.run.mkdir()
        self.protocol=json.loads((gate.ROOT/gate.PROTOCOL).read_text())

    def anchors(self):return gate.evidence(self.campaign,self.run)

    def fixture(self,*,event=False):
        """Synthetic saved audit report, never claimed to be a physical simulation."""
        source_names={'src/__init__.py','src/smt_fullfab/runner.py','src/smt/environment.py',
            'src/smt_fullfab/stream_audit_bundle.py',*gate.AUDIT_DEPENDENCIES}
        inputs={}
        for name in source_names:
            p=self.run/'source_snapshot'/name;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text('# synthetic source only\n'+name);inputs[name]=sha(p)
        inputs['requirements.lock']='a'*64;inputs[gate.DATA+'/tiny.txt']='b'*64
        self.manifest={'config':deepcopy(gate.EXPECTED),'frozen_input_sha256':inputs,
            'origin_git_head':'c'*40,'output_directory':str(self.run),'identity':'d'*64,'protocol_sha256':'e'*64}
        provenance={'source_sha256':{k:v for k,v in inputs.items() if Path(k).parent.as_posix()
            in ('src/smt','src/smt_fullfab') and k.endswith('.py')},
            'requirements_sha256':inputs['requirements.lock'],'git_commit':'c'*40}
        save(self.run/'config.json',gate.EXPECTED);save(self.run/'provenance.json',provenance)
        save(self.run/'trace.jsonl',{'kind':'initial','manifest':{'data_hashes':{'tiny.txt':'b'*64}}})
        receipt=dict(sha256=sha(self.run/'trace.jsonl'),byte_count=(self.run/'trace.jsonl').stat().st_size,
            line_count=1,event_count=1,max_record_bytes=(self.run/'trace.jsonl').stat().st_size)
        metrics=dict(window_start=0,window_end=86400,weighted_tardy_lot_hours=0.,throughput_lots=1,
            terminal_wip_lots=2,terminal_tardy_wip_lots=0)
        summary={k:True for k in ('valid','source_valid','opportunity_valid','physical_valid',
            'actual_dispatch_provenance_complete','complete_physical_window_certified',
            'absence_of_unreported_legal_demand_certified','verified_input_hashes')}
        summary.update(metrics=metrics,source_errors=[],opportunity_errors=[])
        source=dict(valid=True,errors=[],production_machine_count=913,declared_control_machine_count=913,
            declared_full_factory_domain=True,_source_evidence=dict(complete_jsonl_pass=True,source_receipt=receipt))
        bundle=dict(schema='smt-saved-trace-audit-bundle-v1',status='complete',summary=summary,
            source_receipt=receipt,envelope=dict(first_time=0,last_time=86400,horizon=86400,terminal_at_eof=True,receipt=receipt),
            configuration=dict(window_start=0,priority_weights=None,require_terminal=True,verify_data_dir_supplied=True),
            dependency_sha256={k:inputs[k] for k in gate.AUDIT_DEPENDENCIES},bundle_source_sha256=inputs['src/smt_fullfab/stream_audit_bundle.py'])
        for name,value in [('source.json',source),('opportunity.json',{'valid':True}),('physical.json',{'physical':{'valid':True}}),
            ('metrics.json',{'metrics':metrics}),('projection/projection.json',{'synthetic':True}),('projection/physical.jsonl',{'synthetic':True})]:
            save(self.run/'audit_bundle'/name,value)
        bundle['members']={str(p.relative_to(self.run/'audit_bundle')):{'sha256':sha(p),'bytes':p.stat().st_size}
            for p in (self.run/'audit_bundle').rglob('*') if p.is_file()}
        save(self.run/'audit_bundle/audit_bundle.json',bundle)
        timings=[(i*1800,'periodic_cp') for i in range(48)]
        if event:timings.insert(1,(600,'event_classical'))
        rows=[]
        for i,(now,mode) in enumerate(timings):
            request=2 if mode=='periodic_cp' else 0
            rows.extend([dict(event='solver_reserve',arm='A',plan=i,planner_mode=mode,requested_seconds=request,
                constructor_seconds_limit=5 if not request else None,max_candidate_evaluations=250000 if not request else None),
                dict(event='solver_finish',plan=i,planner_mode=mode,solver_status='FEASIBLE_HEURISTIC',wall_seconds=1.,
                    solve_wall_seconds=.125 if request else 0.,classical_construction_wall_seconds=.25)])
            save(self.run/f'problem_{i:05d}.json',dict(time=now,horizon_end=now+14400))
            save(self.run/f'solver_{i:05d}.json',dict(solver_status='FEASIBLE_HEURISTIC',hybrid_mode=mode,nominal_audit={'valid':True},
                wall_seconds=1.,solve_wall_seconds=.125 if request else 0.,classical_construction_wall_seconds=.25))
        (self.run/'resources.jsonl').write_bytes(b''.join(gate.encoded(row) for row in rows))
        save(self.run/'checkpoint.json',{'fixture_only':True})
        save(self.run/'checkpoint_resources.json',dict(parent_checkpoint=None,solver_method='hybrid',solver_budget_seconds=96,
            scenario_seed=1701,model_calls=0,log_bytes_in_earlier_runs=0,
            hybrid_resource_limits=dict(runner_wall_seconds=10800.,max_plans=3600,max_log_bytes=gate.MAX_BYTES,
                max_trace_bytes=gate.TRACE_BYTES,audit_mode='stream',snapshot_mode='stream'),
            cumulative_solver_requested_seconds=96,cumulative_planner_calls=len(timings)))
        self.result=dict(config=deepcopy(gate.EXPECTED),identity=gate.digest(gate.EXPECTED),provenance=provenance,
            status='success',audit_valid=True,full_window_completed=True,simulation_seconds=86400,model_calls=0,formal=False,
            metrics=metrics,wall_seconds=5.,checkpoint='runs/smt_fullfab_development/'+gate.RUN_ID+'/checkpoint.json',
            audit_bundle=dict(path='audit_bundle',manifest_sha256=sha(self.run/'audit_bundle/audit_bundle.json')),
            planner_calls=len(timings),cumulative_planner_calls=len(timings),plans=len(timings),solver_calls=48,
            classical_event_calls=int(event),solver_requested_seconds=96,actual_cp_solve_seconds=6.,
            planner_wall_seconds=float(len(timings)),classical_construction_wall_seconds=len(timings)*.25)
        save(self.run/'result.json',self.result)
        return self.manifest

    def validate(self):return gate._validate_run(self.run,self.manifest,self.anchors())
    def mutate(self,name,update):
        path=self.run/name;v=json.loads(path.read_text());update(v);save(path,v)
    def bundle_mutate(self,update):
        self.mutate('audit_bundle/audit_bundle.json',update)
        self.mutate('result.json',lambda v:v['audit_bundle'].update(manifest_sha256=sha(self.run/'audit_bundle/audit_bundle.json')))
    def phase(self):return dict(returncode=0,primary_failure=None,cleanup_errors=[],wall_seconds=2.,peak_rss_bytes=100,
        limit_seconds=10.,guard_evidence=dict(command_peak_rss_bytes=100,guard_peak_rss_bytes=50))

    def test_protocol_exact(self):self.assertEqual(gate.validate_protocol(self.protocol),gate.EXPECTED)
    def test_protocol_algorithm_hash_cannot_change(self):
        self.protocol['algorithm_sha256']['src/smt_fullfab/hybrid.py']='0'*64
        with self.assertRaises(ValueError):gate.validate_protocol(self.protocol)
    def test_protocol_each_numeric_cap_fixed(self):
        for key in ('outer_seconds','child_seconds','readback_seconds','restore_seconds_within_readback','trace_bytes','all_retained_bytes','maximum_per_pid_peak_rss_bytes','cp_requested_seconds','max_plans'):
            with self.subTest(key=key):
                changed=deepcopy(self.protocol);changed['limits'][key]+=1
                with self.assertRaises(ValueError):gate.validate_protocol(changed)
    def test_protocol_no_model_or_resume(self):
        for key,val in [('snapshot_path','other.json'),('arm','C'),('solver_budget_seconds',98)]:
            changed=deepcopy(self.protocol);changed['run_parameters'][key]=val
            with self.assertRaises(ValueError):gate.validate_protocol(changed)
    def test_prepare_blocked_before_any_side_effect(self):
        with patch.object(gate,'read_json',side_effect=AssertionError('no reads')),self.assertRaisesRegex(ValueError,'preparation blocked'):gate.prepare(root=self.root)
        self.assertFalse((self.root/gate.AREA).exists())
    def test_execute_blocked_before_any_side_effect(self):
        with patch.object(gate,'run_guarded',side_effect=AssertionError('no spawn')),self.assertRaisesRegex(ValueError,'launch blocked'):gate.execute(None,None)
    def test_private_supervisor_blocked(self):
        with self.assertRaisesRegex(ValueError,'launch blockers'):gate._execute_reviewed(None,None,_under_outer_guard=True)
    def test_all_private_workers_blocked(self):
        for kind in ('run','verify','restore','supervise'):
            with self.assertRaisesRegex(ValueError,'worker blocked'):gate._worker(kind,None,'x')
    def test_complete_48_requests(self):
        self.fixture();result,totals,anchors=self.validate()
        self.assertEqual(totals['solver_requested_seconds'],96);self.assertEqual(totals['solver_calls'],48)
        self.assertEqual(set(anchors),gate.AUDIT_EVIDENCE_KEYS)
    def test_event_plan_keeps_absolute_period(self):
        self.fixture(event=True);self.assertEqual(self.validate()[1]['classical_event_calls'],1)
    def test_periodic_shift_rejected(self):
        self.fixture();self.mutate('problem_00001.json',lambda v:v.update(time=1801,horizon_end=16201))
        with self.assertRaisesRegex(ValueError,'periodic boundary'):self.validate()
    def test_event_at_boundary_rejected(self):
        self.fixture(event=True);self.mutate('problem_00001.json',lambda v:v.update(time=1800,horizon_end=16200))
        with self.assertRaisesRegex(ValueError,'postpone'):self.validate()
    def test_planning_horizon_cannot_shrink(self):
        self.fixture();self.mutate('problem_00000.json',lambda v:v.update(horizon_end=3600))
        with self.assertRaisesRegex(ValueError,'planning horizon'):self.validate()
    def test_missing_problem_rejected(self):
        self.fixture();(self.run/'problem_00000.json').unlink()
        with self.assertRaisesRegex(ValueError,'problem files'):self.validate()
    def test_orphan_response_rejected(self):
        self.fixture();save(self.run/'solver_99999.json',{})
        with self.assertRaisesRegex(ValueError,'solver files'):self.validate()
    def test_missing_finish_rejected(self):
        self.fixture();p=self.run/'resources.jsonl';p.write_bytes(b'\n'.join(p.read_bytes().splitlines()[:-1])+b'\n')
        with self.assertRaisesRegex(ValueError,'reservations/finishes'):self.validate()
    def test_reported_request_cost_cannot_override_resources(self):
        self.fixture();self.mutate('result.json',lambda v:v.update(solver_requested_seconds=0))
        with self.assertRaisesRegex(ValueError,'totals differ'):self.validate()
    def test_nominal_failure_cannot_pass(self):
        self.fixture();self.mutate('solver_00000.json',lambda v:v.update(nominal_audit={'valid':False}))
        with self.assertRaisesRegex(ValueError,'nominal'):self.validate()
    def test_checkpoint_resource_budget_cannot_reset(self):
        self.fixture();self.mutate('checkpoint_resources.json',lambda v:v.update(solver_budget_seconds=32))
        with self.assertRaisesRegex(ValueError,'inheritance'):self.validate()
    def test_short_window_cannot_pass(self):
        self.fixture();self.mutate('result.json',lambda v:v.update(simulation_seconds=28800))
        with self.assertRaisesRegex(ValueError,'full-window'):self.validate()
    def test_missing_checkpoint_cannot_pass(self):
        self.fixture();(self.run/'checkpoint.json').unlink()
        with self.assertRaisesRegex(ValueError,'physical checkpoint'):self.validate()
    def test_partial_terminal_bundle_cannot_pass(self):
        self.fixture();self.bundle_mutate(lambda v:v['envelope'].update(terminal_at_eof=False))
        with self.assertRaisesRegex(ValueError,'terminal'):self.validate()
    def test_physical_flag_cannot_be_ignored(self):
        self.fixture();self.bundle_mutate(lambda v:v['summary'].update(physical_valid=False))
        with self.assertRaisesRegex(ValueError,'full-window'):self.validate()
    def test_original_result_hash_not_reanchored(self):
        self.fixture();first=self.anchors();self.mutate('result.json',lambda v:v.update(wall_seconds=6.))
        with self.assertRaisesRegex(ValueError,'SHA'):gate._validate_run(self.run,self.manifest,first)
    def test_new_run_file_after_verification_rejected(self):
        self.fixture();first=self.anchors();save(self.run/'unexpected.json',{})
        with self.assertRaisesRegex(ValueError,'raw run inventory'):gate.bind_first(first,self.anchors())
    def test_campaign_receipt_late_replacement_rejected(self):
        save(self.campaign/'process.json',{'returncode':0});first=self.anchors()
        save(self.campaign/'process.json',{'returncode':1})
        with self.assertRaisesRegex(ValueError,'phase proof'):gate.bind_receipts(first,self.anchors())
    def test_per_pid_peak_rss_exact_domain_and_cap(self):
        for key in ('command_peak_rss_bytes','guard_peak_rss_bytes'):
            for bad in (None,True,-1,gate.RSS_BYTES+1):
                with self.subTest(key=key,bad=bad):
                    p=self.phase();p['guard_evidence'][key]=bad
                    with self.assertRaises(ValueError):gate._process_ok(p,10.)
        gate._process_ok(self.phase(),10.)
    def test_complete_child_tail_time_cap(self):
        p=self.phase();p['wall_seconds']=10800.1
        with self.assertRaises(ValueError):gate._process_ok(p,gate.CHILD_SECONDS)
    def test_nonzero_exit_and_cleanup_fail_closed(self):
        for field,value in [('returncode',1),('cleanup_errors',['unknown']),('primary_failure',{'error':'lost'})]:
            p=self.phase();p[field]=value
            with self.assertRaises(ValueError):gate._process_ok(p,10.)
    def test_terminal_exact_encoded_bytes(self):
        value={'errors':[],'final_total_bytes_including_acceptance':0}
        raw=gate._terminal_encoding(value,500,lambda:10.)
        self.assertEqual(len(raw)+500,value['final_total_bytes_including_acceptance']);self.assertTrue(value['accepted'])
    def test_terminal_encoding_after_cap_fails(self):
        ticks=iter([12600.,12600.1,12600.2,12600.3,12600.4,12600.5,12600.6,12600.7])
        value={'errors':[],'final_total_bytes_including_acceptance':0}
        gate._terminal_encoding(value,0,lambda:next(ticks))
        self.assertFalse(value['accepted']);self.assertIn('OuterTimeLimit',[x['type'] for x in value['errors']])
    def test_terminal_counts_own_bytes(self):
        value={'errors':[],'final_total_bytes_including_acceptance':0}
        gate._terminal_encoding(value,gate.MAX_BYTES,lambda:1.)
        self.assertFalse(value['accepted'])
    def test_frozen_command_routes_own_worker(self):
        cmd=gate._phase_command(self.campaign,{'launcher_executable':'/fake/python','identity':'a'*64},'verify',first_sha='b'*64)
        self.assertIn('offline_A_gate_v4',cmd[4]);self.assertIn('verify',cmd);self.assertEqual(cmd[-2],'b'*64)
    def test_unsafe_extra_freeze_path_rejected(self):
        self.protocol['additional_frozen_files']=['../escape']
        with self.assertRaises(ValueError):gate.validate_protocol(self.protocol)
    def test_duplicate_json_keys_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):gate.strict(b'{"a":1,"a":2}')
    def test_original_hash_read_rejects_replacement(self):
        path=self.root/'original.json';save(path,{'value':1});original=sha(path);save(path,{'value':2})
        with self.assertRaisesRegex(ValueError,'SHA'):gate.read_json(path,original)
    def test_create_new_preserves_existing_bytes(self):
        path=self.root/'saved.json';save(path,{'one':1});before=path.read_bytes()
        with self.assertRaises(FileExistsError):gate.write_new(path,{'one':2})
        self.assertEqual(path.read_bytes(),before)
    def test_restore_full_state_and_trace_without_advancement(self):
        self._restore_case()
    def test_restore_private_event_mutation_rejected(self):
        with self.assertRaisesRegex(ValueError,'full restored state'):self._restore_case(mutate_state=True)
    def test_restore_extra_marker_rejected(self):
        with self.assertRaisesRegex(ValueError,'snapshot restore mutation'):self._restore_case(extra_marker=True)

    def success(self):
        phase=self.phase()
        value=dict(schema=gate.SCHEMA+'-acceptance',run_id=gate.RUN_ID,manifest_identity='m',protocol_sha256='p',
            accepted=True,status='success',errors=[],formal=False,automatic_retry=False,
            outer_wall_seconds_through_receipt_preparation=100.,final_total_bytes_including_acceptance=100,
            child_process=deepcopy(phase),readback_process=deepcopy(phase),restoration_process=deepcopy(phase),
            readback_wall_seconds=4.,restoration=dict(valid=True,simulation_seconds=86400,production_scope=913,
                simulation_advancement_performed=False,model_calls=0,solver_calls=0),
            verified_evidence_sha256={'run/result.json':'h'},runner_result_sha256='h',
            full_supervisor_exit_verified=True,outer_process=deepcopy(phase))
        return value,{'identity':'m','protocol_sha256':'p'}
    def test_complete_phase_predicates(self):
        value,manifest=self.success();gate.validate_success(value,manifest)
    def test_combined_readback_restore_limit(self):
        value,manifest=self.success();value['readback_wall_seconds']=1200.1
        with self.assertRaisesRegex(ValueError,'combined readback'):gate.validate_success(value,manifest)
    def test_restore_phase_cannot_receive_1200_seconds(self):
        value,manifest=self.success();value['restoration_process']['limit_seconds']=1200.
        with self.assertRaisesRegex(ValueError,'remaining deadline'):gate.validate_success(value,manifest)
    def test_phase_cannot_exceed_admitted_remainder(self):
        value,manifest=self.success();value['child_process']['limit_seconds']=1.
        with self.assertRaisesRegex(ValueError,'remaining deadline'):gate.validate_success(value,manifest)
    def test_restore_must_be_entire_913_scope(self):
        value,manifest=self.success();value['restoration']['production_scope']=912
        with self.assertRaisesRegex(ValueError,'exact restoration'):gate.validate_success(value,manifest)
    def test_restore_must_not_advance_simulation(self):
        value,manifest=self.success();value['restoration']['simulation_advancement_performed']=True
        with self.assertRaisesRegex(ValueError,'exact restoration'):gate.validate_success(value,manifest)
    def test_success_requires_actual_outer_wait(self):
        value,manifest=self.success();value['full_supervisor_exit_verified']=False
        with self.assertRaisesRegex(ValueError,'actual original wait'):gate.validate_success(value,manifest)
    def test_restore_report_cannot_substitute_state_sha(self):
        proof={'checkpoint':{'file_sha256':'a'*64,'state_sha256':'b'*64}}
        result=dict(valid=True,checkpoint_sha256='a'*64,restored_state_sha256='c'*64)
        with self.assertRaisesRegex(ValueError,'restored state'):gate.validate_restoration(result,proof,self.campaign)

    def _restore_case(self,*,mutate_state=False,extra_marker=False):
        original_trace=[dict(seq=0,time=86400.,kind='terminal',fixture_only=True)]
        state=dict(seed=1701,t=86400.,horizon=86400.,finished=True,observation_start=0,
            q=[[86500.,10,'physical_event',{'lot':'x'}]],trace=original_trace)
        state_sha=gate.digest(state);snapshot={'state':state,'state_sha256':state_sha}
        save(self.run/'checkpoint.json',snapshot);save(self.run/'trace.jsonl',original_trace[0])
        marker=dict(seq=1,time=86400.,kind='snapshot_loaded',snapshot_sha256=state_sha,prefix_event_count=1)
        restored=deepcopy(state);restored['trace'].append(marker)
        if mutate_state:restored['q'][0][0]+=1
        if extra_marker:restored['trace'].append(marker)
        env=SimpleNamespace(**restored,physical=list(range(913)))
        environment=ModuleType('src.smt_fullfab.environment')
        environment.FullFabEnvironment=SimpleNamespace(from_snapshot=lambda *a,**k:env)
        serializer=ModuleType('src.smt_fullfab.stream_snapshot')
        serializer._state_view=lambda e:{key:getattr(e,key) for key in state}
        serializer._chunks=lambda value:iter([json.dumps(value,sort_keys=True,separators=(',',':')).encode()])
        def write_snapshot(e,path):
            v=serializer._state_view(e);save(path,{'state':v});return gate.digest(v)
        serializer.write_snapshot=write_snapshot
        trace=ModuleType('src.smt_fullfab.trace_source');trace.inspect_jsonl=lambda *a,**k:None
        class Reader:
            def __enter__(self):return iter([SimpleNamespace(event=original_trace[0])])
            def __exit__(self,*args):return False
        trace.open_verified=lambda seal:Reader()
        proof=dict(checkpoint=dict(file_sha256=sha(self.run/'checkpoint.json'),state_sha256=state_sha),
            first_trace_receipt={'sha256':sha(self.run/'trace.jsonl')},verified_evidence_sha256=self.anchors())
        with patch.dict(sys.modules,{m.__name__:m for m in (environment,serializer,trace)}):
            result=gate.restoration_payload(self.campaign,{'output_directory':str(self.run)},proof)
        self.assertTrue(result['valid']);self.assertEqual(result['restored_state_sha256'],state_sha)
        self.assertFalse(result['simulation_advancement_performed']);self.assertEqual(env.trace[-1],marker)


if __name__=='__main__':unittest.main()
