"""Tiny saved-evidence mocks only: no model, factory, CP or real A child."""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.smt_fullfab import offline_A_gate_v3 as gate


class OfflineAGateV3Tests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        for relative in ['src/smt_fullfab', 'src/smt', gate.DATA, gate.VENDOR, 'configs/smt_fullfab']:
            (self.root / relative).mkdir(parents=True)
        for relative in ['src/__init__.py', 'src/smt/__init__.py', 'src/smt_fullfab/__init__.py']:
            (self.root / relative).write_text('')
        for name in ('offline_A_gate_v3.py', 'offline_pilot.py'):
            (self.root / 'src/smt_fullfab' / name).write_bytes(Path(gate.__file__).with_name(name).read_bytes())
        # Pure saved-byte readers only. No environment, optimizer or factory.
        for relative in gate.AUDIT_DEPENDENCIES | {'src/smt_fullfab/stream_audit_bundle.py'}:
            (self.root / relative).write_bytes((gate.ROOT / relative).read_bytes())
        (self.root / 'src/smt_fullfab/runner.py').write_text('# fixture only; never executed\n')
        (self.root / gate.DATA / 'input.txt').write_text('tiny synthetic data')
        (self.root / gate.VENDOR / 'read.py').write_text('# tiny synthetic vendor')
        (self.root / 'requirements.lock').write_text('# fixture lock')
        self.protocol = gate._read(gate.ROOT / gate.PROTOCOL)
        gate._write(self.root / gate.PROTOCOL, self.protocol)
        gate._git_pointer(self.root, '1' * 40)
        self.stack.enter_context(patch.object(gate, '_runtime', return_value={'fixture_runtime_only': True}))
        self.stack.enter_context(patch.object(gate.shutil, 'disk_usage', return_value=SimpleNamespace(free=50 * 1024**3)))
        self.clock = [0.0]
        self.stack.enter_context(patch.object(gate.time, 'monotonic', side_effect=lambda: self.clock[0]))
        self.launch = self.stack.enter_context(patch.object(gate, '_launch', side_effect=self.fake_child))
        self.child_wall = 20.0
        self.post_hook = None
        self.run_mutation = None

    def prepare(self):
        return gate.prepare(root=self.root)

    @contextmanager
    def separate_fixture(self):
        helper=OfflineAGateV3Tests();helper.setUp()
        try:yield helper
        finally:helper.doCleanups()

    def saved_fixture(self):
        campaign,manifest=self.prepare()
        self.fake_child(gate._command(campaign,manifest['config']),campaign/'frozen',campaign,6000)
        return campaign,manifest,Path(manifest['output_directory'])

    def rehash_bundle(self,run,mutate=None):
        """Rebind synthetic metadata; this is not a semantic audit certificate."""
        path=run/'audit_bundle/audit_bundle.json'
        data=gate._read(path)
        if mutate:mutate(data)
        for name in data['members']:
            member=run/'audit_bundle'/name
            data['members'][name]={'bytes':member.stat().st_size,'sha256':gate._sha(member)}
        path.write_text(json.dumps(data)+'\n')
        result=gate._read(run/'result.json')
        result['audit_bundle']['manifest_sha256']=gate._sha(path)
        (run/'result.json').write_text(json.dumps(result)+'\n')

    def fake_child(self, command, frozen, campaign, timeout):
        """Synthesize evidence from the exact frozen manifest, not live source."""
        manifest = gate._read(campaign / 'manifest.json')
        config = manifest['config']
        self.assertEqual(command, gate._command(campaign, config))
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 6000)
        self.clock[0] += self.child_wall
        gate._write(campaign / 'child_started.json', {'pid': 7654321, 'started_at': 'fixture'})
        gate._write(campaign / 'child_usage.json', dict(schema='smt-child-peak-rss-v1', pid=7654321,
            platform='darwin', source='resource.getrusage(RUSAGE_SELF).ru_maxrss',
            raw_maxrss=123456, raw_unit='bytes', peak_rss_bytes=123456, hard_memory_guard=False))
        (campaign / 'stdout.log').write_text('synthetic child output\n')
        (campaign / 'stderr.log').write_text('')
        run = Path(manifest['output_directory'])
        run.mkdir(parents=True)
        inputs = manifest['frozen_input_sha256']
        sources = {k: v for k, v in inputs.items() if Path(k).parent.as_posix() in ('src/smt', 'src/smt_fullfab') and k.endswith('.py')}
        for relative in {**sources, 'src/__init__.py': inputs['src/__init__.py']}:
            target = run / 'source_snapshot' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((frozen / relative).read_bytes())
        provenance = dict(git_commit=manifest['origin_git_head'], source_sha256=sources,
                          requirements_sha256=inputs['requirements.lock'])
        gate._write(run / 'config.json', config)
        gate._write(run / 'provenance.json', provenance)
        gate._write(run / 'trace.jsonl', dict(kind='initial', fixture=True,
            manifest={'data_hashes': {Path(k).name: v for k, v in inputs.items() if k.startswith(gate.DATA + '/')}}))
        # Synthetic report protocol evidence; intentionally not a physical audit.
        # The real frozen read_bundle below verifies all member bytes, without
        # replaying this tiny fixture as a factory simulation.
        receipt=dict(sha256=gate._sha(run/'trace.jsonl'),byte_count=(run/'trace.jsonl').stat().st_size,
            line_count=1,event_count=1,max_record_bytes=(run/'trace.jsonl').stat().st_size)
        metrics=dict(window_start=0,window_end=28800,weighted_tardy_lot_hours=0.0,
            throughput_lots=1,terminal_wip_lots=2,terminal_tardy_wip_lots=0)
        source=dict(valid=True,errors=[],production_machine_count=913,
            declared_control_machine_count=913,declared_full_factory_domain=True,
            _source_evidence={'complete_jsonl_pass':True,'source_receipt':receipt})
        summary={key:True for key in ('valid','source_valid','opportunity_valid','physical_valid',
            'actual_dispatch_provenance_complete','absence_of_unreported_legal_demand_certified',
            'complete_physical_window_certified','verified_input_hashes')}
        summary.update(metrics=metrics,source_errors=[],opportunity_errors=[],physical_error_details_member='physical.json')
        bundle=dict(schema='smt-saved-trace-audit-bundle-v1',status='complete',summary=summary,
            source_receipt=receipt,envelope=dict(first_time=0,last_time=28800,horizon=28800,terminal_at_eof=True,receipt=receipt),
            configuration=dict(window_start=0,priority_weights=None,require_terminal=True,verify_data_dir_supplied=True),
            dependency_sha256={k:inputs[k] for k in gate.AUDIT_DEPENDENCIES},
            bundle_source_sha256=inputs['src/smt_fullfab/stream_audit_bundle.py'])
        for name,content in [('source.json',source),('opportunity.json',{'valid':True}),
                ('physical.json',{'physical':{'valid':True}}),('metrics.json',{'metrics':metrics}),
                ('projection/projection.json',{'synthetic':True}),('projection/physical.jsonl',{'synthetic':True})]:
            gate._write(run/'audit_bundle'/name,content)
        bundle['members']={str(p.relative_to(run/'audit_bundle')):{'sha256':gate._sha(p),'bytes':p.stat().st_size}
            for p in (run/'audit_bundle').rglob('*') if p.is_file()}
        gate._write(run/'audit_bundle/audit_bundle.json',bundle)
        rows = []
        for i in range(16):
            rows += [dict(event='solver_reserve', arm='A', plan=i, planner_mode='periodic_cp', requested_seconds=2,
                          constructor_seconds_limit=None, max_candidate_evaluations=None),
                     dict(event='solver_finish', plan=i, planner_mode='periodic_cp', solver_status='FEASIBLE_HEURISTIC',
                          wall_seconds=1.0, solve_wall_seconds=.125, classical_construction_wall_seconds=.25)]
            response = dict(solver_status='FEASIBLE_HEURISTIC', hybrid_mode='periodic_cp', nominal_audit={'valid': True},
                            wall_seconds=1.0, solve_wall_seconds=.125, classical_construction_wall_seconds=.25)
            gate._write(run / f'problem_{i:05d}.json', {'time': i * 1800, 'fixture_only': True})
            gate._write(run / f'solver_{i:05d}.json', response)
        (run / 'resources.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
        gate._write(run / 'checkpoint.json', {'fixture': 'not a physical simulation'})
        gate._write(run / 'checkpoint_resources.json', dict(parent_checkpoint=None, solver_method='hybrid',
            cumulative_solver_requested_seconds=32, cumulative_planner_calls=16, solver_budget_seconds=32,
            scenario_seed=1701, model_calls=0, log_bytes_in_earlier_runs=0,
            hybrid_resource_limits=dict(runner_wall_seconds=5400.0, max_plans=1200, max_log_bytes=16 * 1024**3,
                max_trace_bytes=gate.TRACE_BYTES,audit_mode='stream',snapshot_mode='stream')))
        result = dict(config=config, identity=gate._digest(config), provenance=provenance,
            status='success', full_window_completed=True, simulation_seconds=28800, audit_valid=True,
            model_calls=0, formal=False, metrics=metrics, wall_seconds=19.0,
            audit_bundle={'path':'audit_bundle','manifest_sha256':gate._sha(run/'audit_bundle/audit_bundle.json')},
            checkpoint='runs/smt_fullfab_development/'+gate.RUN_ID+'/checkpoint.json',
            planner_calls=16, cumulative_planner_calls=16, plans=16, solver_calls=16, classical_event_calls=0,
            solver_requested_seconds=32, actual_cp_solve_seconds=2.0, planner_wall_seconds=16.0,
            classical_construction_wall_seconds=4.0)
        gate._write(run / 'result.json', result)
        if self.run_mutation:self.run_mutation(run)
        if self.post_hook:self.post_hook(campaign)
        return dict(pid=7654321, returncode=0, timed_out=False, wall_seconds=self.child_wall)

    def test_default_prepare_is_readonly_execution_and_fixed_configuration(self):
        campaign, manifest = self.prepare()
        self.launch.assert_not_called()
        self.assertEqual(manifest['config'], gate.EXPECTED)
        self.assertEqual(manifest['cp_requested_seconds_permitted'], 32)
        self.assertFalse(Path(manifest['output_directory']).exists())
        self.assertEqual(gate._origin_git(campaign / 'frozen'), '1' * 40)
        again, loaded = self.prepare()
        self.assertEqual((again, loaded), (campaign, manifest))
        self.assertFalse(gate.read_acceptance(root=self.root)['accepted'])

    def test_frozen_child_success_binds_pid_hashes_all_bytes_and_readback(self):
        campaign, manifest = self.prepare()
        (self.root / gate.DATA / 'input.txt').write_text('live data must never be read by child')
        outcome = gate.execute(campaign, manifest)
        self.assertTrue(outcome['accepted'], outcome)
        self.assertEqual(outcome['final_total_bytes_including_acceptance'], gate._bytes(campaign, Path(manifest['output_directory'])))
        checked = gate.read_acceptance(root=self.root)
        self.assertTrue(checked['valid'], checked)
        self.assertTrue(checked['accepted'])
        self.assertEqual(gate.execute(campaign, manifest), outcome)
        self.assertEqual(self.launch.call_count, 1)
        self.assertIn('campaign/stdout.log', outcome['evidence_sha256'])
        self.assertIn('run/checkpoint.json', outcome['evidence_sha256'])
        self.assertEqual(set(outcome['verified_audit_evidence_sha256']),gate.AUDIT_EVIDENCE_KEYS)
        self.assertEqual(outcome['verified_audit_evidence_sha256'],
            {key:outcome['evidence_sha256'][key] for key in gate.AUDIT_EVIDENCE_KEYS})

    def test_status_must_reject_runner_success_until_outer_acceptance_exists(self):
        campaign, manifest = self.prepare()
        gate._write(campaign / 'attempt.json', {'interrupted': True})
        self.fake_child(gate._command(campaign, manifest['config']), campaign / 'frozen', campaign, 6000)
        self.assertEqual(gate._read(Path(manifest['output_directory']) / 'result.json')['status'], 'success')
        self.assertFalse(gate.read_acceptance(root=self.root)['accepted'])
        with self.assertRaisesRegex(FileExistsError, 'no automatic restart'):
            gate.execute(campaign, manifest)
        self.launch.assert_not_called()

    def test_existing_target_or_partial_attempt_cannot_restart(self):
        campaign, manifest = self.prepare()
        gate._write(campaign / 'attempt.json', {'interrupted': True})
        with self.assertRaises(FileExistsError):gate.execute(campaign, manifest)
        self.launch.assert_not_called()
        self.assertFalse(gate.read_acceptance(root=self.root)['accepted'])

    def test_unrelated_existing_run_cannot_be_adopted_during_prepare(self):
        target = self.root / 'runs/smt_fullfab_development' / gate.RUN_ID
        target.mkdir(parents=True)
        gate._write(target / 'result.json', {'status': 'success'})
        with self.assertRaisesRegex(FileExistsError, 'cannot be adopted'):self.prepare()

    def test_timeout_retains_partial_evidence_and_never_invents_checkpoint(self):
        campaign, manifest = self.prepare()
        def timeout(command, frozen, output, seconds):
            run = Path(manifest['output_directory']);run.mkdir(parents=True)
            (run / 'trace.jsonl').write_text('partial fixture trace')
            gate._write(output / 'child_started.json', {'pid': 42})
            self.clock[0] += 6000.1
            return dict(pid=42, returncode=-9, timed_out=True, wall_seconds=6000.1)
        self.launch.side_effect = timeout
        outcome = gate.execute(campaign, manifest)
        self.assertFalse(outcome['accepted'])
        self.assertTrue(any('watchdog' in e for e in outcome['errors']))
        self.assertFalse((Path(manifest['output_directory']) / 'checkpoint.json').exists())
        self.assertFalse((Path(manifest['output_directory']) / 'result.json').exists())
        self.assertEqual(gate.execute(campaign, manifest), outcome)
        self.assertEqual(self.launch.call_count, 1)

    def test_active_claim_and_disk_preflight_do_not_consume_attempt(self):
        campaign, manifest = self.prepare()
        claim = self.root / 'runs/smt_fullfab_stage2/active/claim.json'
        gate._write(claim, {'pid': os.getpid()})
        self.assertEqual(gate.execute(campaign, manifest)['status'], 'blocked_active_runs')
        gate._write(claim.with_name('result.json'), {'status': 'success'})
        self.assertEqual(gate.execute(campaign, manifest)['status'], 'blocked_active_runs')
        claim.unlink()
        with patch.object(gate.shutil, 'disk_usage', return_value=SimpleNamespace(free=gate.MIN_FREE_BYTES - 1)):
            self.assertEqual(gate.execute(campaign, manifest)['status'], 'blocked_disk_capacity')
        self.assertFalse((campaign / 'attempt.json').exists())
        self.launch.assert_not_called()
        with gate._serial_lock(self.root), self.assertRaisesRegex(RuntimeError, 'serial lock'):
            gate.execute(campaign, manifest)

    def test_only_exact_registered_limits_and_argv_are_allowed(self):
        for key, value in [('arm', 'B'), ('seconds', 5400), ('solver_budget_seconds', 60.0),
                           ('max_log_bytes', 2**40), ('snapshot_path', '/old/checkpoint'), ('seed', True)]:
            bad = deepcopy(self.protocol);bad['run_config'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):gate._config(bad)
        bad = deepcopy(self.protocol);bad['argv'][-1] = '1073741824'
        with self.assertRaises(ValueError):gate._config(bad)

    def test_freeze_tamper_permissions_runtime_or_mapping_fail_closed(self):
        campaign, manifest = self.prepare()
        path = campaign / 'frozen' / gate.DATA / 'input.txt'
        path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'writable'):gate.verify_frozen(campaign, manifest)
        path.write_text('different');path.chmod(0o444)
        with self.assertRaisesRegex(ValueError, 'changed'):gate.verify_frozen(campaign, manifest)
        self.launch.assert_not_called()

    def test_post_run_freeze_tamper_vetoes_success(self):
        campaign, manifest = self.prepare()
        def tamper(output):
            p = output / 'frozen' / gate.VENDOR / 'read.py';p.chmod(0o644);p.write_text('tampered')
        self.post_hook = tamper
        outcome = gate.execute(campaign, manifest)
        self.assertFalse(outcome['accepted'])
        self.assertTrue(any('frozen source/data changed' in e for e in outcome['errors']))

    def test_final_outer_wall_and_all_output_bytes_can_veto_runner_success(self):
        campaign, manifest = self.prepare()
        self.child_wall = 6001
        outcome = gate.execute(campaign, manifest)
        self.assertFalse(outcome['accepted'])
        self.assertIn('outer final wall exceeds6000 seconds', outcome['errors'])
        self.assertEqual(gate._read(Path(manifest['output_directory']) / 'result.json')['status'], 'success')

    def test_stdout_and_frozen_files_count_toward_sixteen_gib(self):
        campaign, manifest = self.prepare()
        original = gate._bytes
        with patch.object(gate, '_bytes', side_effect=lambda c, r: original(c, r) + gate.EXPECTED['max_log_bytes']):
            outcome = gate.execute(campaign, manifest)
        self.assertFalse(outcome['accepted'])
        self.assertIn('final total evidence exceeds16GiB', outcome['errors'])

    def test_resource_ledger_cp_overrun_or_missing_finish_rejected(self):
        campaign, manifest = self.prepare()
        def mutate(run):
            path = run / 'resources.jsonl';rows = path.read_text().splitlines();rows.pop();path.write_text('\n'.join(rows) + '\n')
        self.run_mutation = mutate
        outcome = gate.execute(campaign, manifest)
        self.assertFalse(outcome['accepted'])
        self.assertTrue(any('incomplete or duplicated' in e for e in outcome['errors']))

    def test_pid_returncode_and_nominal_evidence_are_not_optional(self):
        campaign, manifest = self.prepare()
        def mutate(run):
            p = run / 'solver_00000.json';r = gate._read(p);r['nominal_audit'] = None;p.write_text(json.dumps(r))
        self.run_mutation = mutate
        outcome = gate.execute(campaign, manifest)
        self.assertFalse(outcome['accepted'])
        self.assertTrue(any('nominal plan' in e for e in outcome['errors']))

    def test_nonzero_exit_cannot_pass_even_when_runner_claims_success(self):
        campaign, manifest = self.prepare()
        def failed_process(*args):
            outcome = self.fake_child(*args);outcome['returncode'] = 7;return outcome
        self.launch.side_effect = failed_process
        outcome = gate.execute(campaign, manifest)
        self.assertFalse(outcome['accepted'])
        self.assertTrue(any('nonzero' in e for e in outcome['errors']))

    def test_child_pid_must_match_record_written_before_runner_start(self):
        campaign, manifest = self.prepare()
        def different_pid(*args):
            outcome = self.fake_child(*args);outcome['pid'] = 99;return outcome
        self.launch.side_effect = different_pid
        self.assertFalse(gate.execute(campaign, manifest)['accepted'])

    def test_final_runner_wall_overrun_vetoes_saved_success(self):
        campaign, manifest = self.prepare()
        def mutate(run):
            path = run / 'result.json';data = gate._read(path);data['wall_seconds'] = 5401;path.write_text(json.dumps(data))
        self.run_mutation = mutate
        self.assertFalse(gate.execute(campaign, manifest)['accepted'])

    def test_child_exit_after_5400_is_not_hidden_by_earlier_runner_timestamp(self):
        campaign, manifest = self.prepare()
        self.child_wall = 5400.1
        outcome = gate.execute(campaign, manifest)
        self.assertFalse(outcome['accepted'])
        self.assertTrue(any('measured wall' in e for e in outcome['errors']))
        self.assertLess(gate._read(Path(manifest['output_directory']) / 'result.json')['wall_seconds'], 5400)

    def test_missing_problem_rejected_even_when_resource_counts_match(self):
        campaign, manifest = self.prepare()
        self.run_mutation = lambda run: (run / 'problem_00003.json').unlink()
        outcome = gate.execute(campaign, manifest)
        self.assertFalse(outcome['accepted'])
        self.assertTrue(any('problem files' in e for e in outcome['errors']))

    def test_orphan_solver_result_rejected(self):
        campaign, manifest = self.prepare()
        self.run_mutation = lambda run: gate._write(run / 'solver_00016.json', {'orphan': True})
        outcome = gate.execute(campaign, manifest)
        self.assertFalse(outcome['accepted'])
        self.assertTrue(any('solver files' in e for e in outcome['errors']))

    def test_trace_limit_remains_separate_from_total_limit(self):
        campaign, manifest = self.prepare()
        # No large/sparse artifact: only the stat-derived admission value is mocked.
        with patch.object(gate, '_trace_size', return_value=gate.TRACE_BYTES+1):
            outcome = gate.execute(campaign, manifest)
        self.assertFalse(outcome['accepted'])
        self.assertTrue(any('resource limit' in e for e in outcome['errors']))

    def test_acceptance_tamper_after_success_is_not_read_as_a_gate_pass(self):
        campaign, manifest = self.prepare()
        self.assertTrue(gate.execute(campaign, manifest)['accepted'])
        run = Path(manifest['output_directory'])
        (run / 'trace.jsonl').write_text('different trace')
        checked = gate.read_acceptance(root=self.root)
        self.assertFalse(checked['valid'])
        self.assertFalse(checked['accepted'])
        with self.assertRaisesRegex(ValueError, 'evidence changed'):gate.execute(campaign, manifest)
        self.assertEqual(self.launch.call_count, 1)

    def test_historical_readback_does_not_require_current_live_code_or_runtime(self):
        campaign, manifest = self.prepare()
        outcome = gate.execute(campaign, manifest)
        self.assertTrue(outcome['accepted'])
        real_sha = gate._sha
        live = {Path(gate.__file__), Path(gate.__file__).with_name('offline_pilot.py')}
        with patch.object(gate, '_sha', side_effect=lambda p: '0' * 64 if Path(p) in live else real_sha(p)), \
             patch.object(gate, '_runtime', return_value={'later_runtime': True}):
            self.assertTrue(gate.read_acceptance(root=self.root)['accepted'])
            self.assertEqual(gate.execute(campaign, manifest), outcome)
            with self.assertRaisesRegex(ValueError, 'runtime differs'):
                gate.verify_frozen(campaign, manifest)
        self.assertEqual(self.launch.call_count, 1)

    def test_new_execution_still_requires_exact_supervisor_version(self):
        campaign, manifest = self.prepare()
        real_sha = gate._sha
        with patch.object(gate, '_sha', side_effect=lambda p: '0' * 64 if Path(p) == Path(gate.__file__) else real_sha(p)):
            with self.assertRaisesRegex(ValueError, 'live code differs'):
                gate.execute(campaign, manifest)
        self.launch.assert_not_called()

    def test_all_new_storage_options_are_fixed_and_inherited_together(self):
        campaign,manifest,run=self.saved_fixture()
        path=run/'checkpoint_resources.json';original=gate._read(path)
        for key,value in [('max_trace_bytes',268435456),('audit_mode','legacy'),('snapshot_mode','legacy')]:
            bad=deepcopy(original);bad['hybrid_resource_limits'][key]=value
            path.write_text(json.dumps(bad))
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'resource inheritance'):
                gate._validate_run(run,manifest)
            bad=deepcopy(self.protocol);bad['run_config'][key]=value
            with self.assertRaises(ValueError):gate._config(bad)
        path.write_text(json.dumps(original))
        self.assertEqual(gate._validate_run(run,manifest)[0]['status'],'success')

    def test_gate_requires_every_member_hash_even_when_summary_says_valid(self):
        campaign,manifest,run=self.saved_fixture()
        for name in ('source.json','opportunity.json','physical.json','metrics.json',
                     'projection/projection.json','projection/physical.jsonl'):
            member=run/'audit_bundle'/name;original=member.read_bytes()
            member.write_bytes(original+b' ')
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'member differs'):
                gate._validate_run(run,manifest)
            member.write_bytes(original)

    def test_legacy_audit_or_missing_unsafe_bundle_ref_cannot_pass(self):
        campaign,manifest,run=self.saved_fixture()
        result_path=run/'result.json';original=gate._read(result_path)
        for ref in (None,{'path':'../audit_bundle','manifest_sha256':'0'*64},
                    {'path':'audit_bundle','manifest_sha256':'G'*64},
                    {**original['audit_bundle'],'extra':'ambiguous'}):
            changed=deepcopy(original);changed['audit_bundle']=ref
            result_path.write_text(json.dumps(changed))
            with self.subTest(ref=ref),self.assertRaisesRegex(ValueError,'bundle reference'):
                gate._validate_run(run,manifest)
        result_path.write_text(json.dumps(original))
        gate._write(run/'audit.json',{'valid':True})
        with self.assertRaisesRegex(ValueError,'legacy full audit'):
            gate._validate_run(run,manifest)

    def test_all_three_semantic_flags_and_complete_terminal_are_required(self):
        campaign,manifest,run=self.saved_fixture()
        path=run/'audit_bundle/audit_bundle.json';original=gate._read(path)
        cases=[('summary',key,False) for key in ('valid','source_valid','opportunity_valid','physical_valid',
            'actual_dispatch_provenance_complete','absence_of_unreported_legal_demand_certified',
            'complete_physical_window_certified','verified_input_hashes')]
        cases += [('envelope','terminal_at_eof',False),('envelope','last_time',28799),
                  ('envelope','horizon',3600),('envelope','first_time',1)]
        for section,key,value in cases:
            path.write_text(json.dumps(original))
            self.rehash_bundle(run,lambda d:d[section].update({key:value}))
            with self.subTest(section=section,key=key),self.assertRaises(ValueError):
                gate._validate_run(run,manifest)

    def test_complete_source_report_913_machines_and_own_receipt_are_required(self):
        campaign,manifest,run=self.saved_fixture()
        path=run/'audit_bundle/source.json';original=gate._read(path)
        cases=[{'production_machine_count':912},{'declared_control_machine_count':913.0},
            {'declared_full_factory_domain':False},{'valid':False},{'errors':['retained finding']},
            {'_source_evidence':{'complete_jsonl_pass':False}},
            {'_source_evidence':{'complete_jsonl_pass':True,'source_receipt':{'sha256':'0'*64}}}]
        for change in cases:
            path.write_text(json.dumps({**original,**change}))
            self.rehash_bundle(run)
            with self.subTest(change=change),self.assertRaises(ValueError):gate._validate_run(run,manifest)

    def test_source_nested_fields_do_not_substitute_for_top_level(self):
        campaign,manifest,run=self.saved_fixture()
        path=run/'audit_bundle/source.json';data=gate._read(path)
        data['nested']={'production_machine_count':data.pop('production_machine_count')}
        path.write_text(json.dumps(data));self.rehash_bundle(run)
        with self.assertRaisesRegex(ValueError,'evidence does not pass'):gate._validate_run(run,manifest)

    def test_source_duplicate_keys_and_truncation_fail_closed_after_valid_hashes(self):
        campaign,manifest,run=self.saved_fixture()
        path=run/'audit_bundle/source.json';raw=path.read_text().strip()
        for bad in (raw[:-1]+',"production_machine_count":913}',
                    raw[:-1]+',"nested":{"x":1,"x":2}}',raw[:-1]):
            path.write_text(bad);self.rehash_bundle(run)
            with self.subTest(bad=bad[-70:]),self.assertRaises((ValueError,json.JSONDecodeError)):
                gate._validate_run(run,manifest)

    def test_source_parsed_bytes_must_match_storage_verified_hash(self):
        campaign,manifest,run=self.saved_fixture()
        real=gate._bundle_storage_readback
        def replace_after_readback(*args):
            checked=real(*args)
            path=run/'audit_bundle/source.json'
            path.write_bytes(path.read_bytes()+b' ')
            return checked
        with patch.object(gate,'_bundle_storage_readback',side_effect=replace_after_readback),\
                self.assertRaisesRegex(ValueError,'identity/hash differs'):
            gate._validate_run(run,manifest)

    def test_raw_trace_and_frozen_dependencies_must_match_bundle(self):
        campaign,manifest,run=self.saved_fixture()
        path=run/'audit_bundle/audit_bundle.json';original=gate._read(path)
        mutations=[lambda d:d['source_receipt'].update(sha256='0'*64),
                   lambda d:d['source_receipt'].update(byte_count=1),
                   lambda d:d['dependency_sha256'].update({'src/smt_fullfab/metrics.py':'0'*64}),
                   lambda d:d.update(bundle_source_sha256='0'*64),
                   lambda d:d['configuration'].update(require_terminal=False)]
        for mutate in mutations:
            path.write_text(json.dumps(original));self.rehash_bundle(run,mutate)
            with self.assertRaisesRegex(ValueError,'binding differs'):gate._validate_run(run,manifest)

    def test_result_mirrors_only_six_summary_metrics_not_full_metric_report(self):
        campaign,manifest,run=self.saved_fixture()
        original=gate._read(run/'audit_bundle/audit_bundle.json')
        for metrics in ({'fixture_only':True},{**original['summary']['metrics'],'extra':42},
                        {**original['summary']['metrics'],'window_end':3600}):
            self.rehash_bundle(run,lambda d:d['summary'].update(metrics=metrics))
            result=gate._read(run/'result.json');result['metrics']=metrics
            (run/'result.json').write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError,'six-field contract'):gate._validate_run(run,manifest)

    def test_missing_usage_never_admits_runner_success(self):
        campaign,manifest=self.prepare()
        self.post_hook=lambda c:(c/'child_usage.json').unlink()
        outcome=gate.execute(campaign,manifest)
        self.assertFalse(outcome['accepted']);self.assertIsNone(outcome['child_peak_rss_bytes'])
        self.assertTrue(any('child_usage.json' in e for e in outcome['errors']))

    def test_partial_checkpoint_does_not_substitute_for_writer_completion(self):
        campaign,manifest,run=self.saved_fixture()
        path=run/'result.json';original=gate._read(path)
        for change in ({'checkpoint':None},{'checkpoint':'../checkpoint.json'},
                       {'checkpoint_failure':'OSError: interrupted write'}):
            path.write_text(json.dumps({**original,**change}))
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'checkpoint reference'):
                gate._validate_run(run,manifest)

    def test_fixed_protocol_rejects_boolean_numeric_aliases(self):
        for field,change in [('model_calls_authorized',False),('execution_constraints',
                              {**self.protocol['execution_constraints'],'solver_workers':True})]:
            bad=deepcopy(self.protocol);bad[field]=change
            with self.subTest(field=field),self.assertRaises(ValueError):gate._config(bad)

    def test_bundle_readback_has_fixed_timeout_charged_to_outer_and_no_retry(self):
        campaign,manifest=self.prepare()
        self.assertEqual(manifest['bundle_readback_timeout_seconds'],180)
        actual_run=gate.subprocess.run;readbacks=[]
        def timeout(command,**kwargs):
            if command[1:3]!=['-I','-B']:return actual_run(command,**kwargs)
            readbacks.append(command)
            self.assertEqual(kwargs['timeout'],180)
            self.clock[0]+=180.1
            raise subprocess.TimeoutExpired(command,kwargs['timeout'])
        with patch.object(gate.subprocess,'run',side_effect=timeout) as reader:
            outcome=gate.execute(campaign,manifest)
            self.assertFalse(outcome['accepted'])
            self.assertTrue(any('TimeoutExpired' in e for e in outcome['errors']))
            self.assertAlmostEqual(outcome['outer_wall_seconds'],self.child_wall+180.1)
            self.assertTrue((Path(manifest['output_directory'])/'audit_bundle/source.json').exists())
            self.assertEqual(gate.execute(campaign,manifest),outcome)
            self.assertEqual(len(readbacks),1)
        self.assertEqual(self.launch.call_count,1)
        for value in (181,180.0,True):
            bad=deepcopy(self.protocol);bad['execution_constraints']['bundle_readback_timeout_seconds']=value
            with self.subTest(value=value),self.assertRaises(ValueError):gate._config(bad)

    def test_original_five_post_readback_replacements_fail_current_acceptance(self):
        # Independent reviewer timing: genuine frozen read_bundle has passed,
        # then one ordinary rewrite occurs before gate final evidence collection.
        for name in ('opportunity.json','physical.json','metrics.json',
                     'projection/projection.json','projection/physical.jsonl'):
            with self.subTest(name=name),self.separate_fixture() as h:
                campaign,manifest=h.prepare();real=gate._bundle_storage_readback;calls=[]
                def replaced(*args):
                    checked=real(*args);calls.append(1)
                    (args[0]/'audit_bundle'/name).write_text('{"valid":false,"errors":["post-readback replacement"]}\n')
                    return checked
                with patch.object(gate,'_bundle_storage_readback',side_effect=replaced):
                    outcome=gate.execute(campaign,manifest)
                key='run/audit_bundle/'+name
                self.assertFalse(outcome['accepted']);self.assertEqual(outcome['status'],'failed')
                self.assertTrue(any('final audit evidence differs' in e and key in e for e in outcome['errors']))
                self.assertNotEqual(outcome['verified_audit_evidence_sha256'][key],outcome['evidence_sha256'][key])
                self.assertEqual(gate.execute(campaign,manifest),outcome)
                self.assertFalse(gate.read_acceptance(root=h.root)['accepted'])
                self.assertEqual(h.launch.call_count,1);self.assertEqual(len(calls),1)

    def test_all_eight_checked_hashes_survive_until_final_evidence_collection(self):
        # Later timing also exercises source, bundle manifest and trace: all have
        # passed their own parser/checks already. Do not refresh expected hashes.
        for key in sorted(gate.AUDIT_EVIDENCE_KEYS):
            with self.subTest(key=key),self.separate_fixture() as h:
                campaign,manifest=h.prepare();real=gate._validate_run;seen={}
                def replaced(run,frozen):
                    checked=real(run,frozen);seen.update(checked[2])
                    target=run/key.removeprefix('run/')
                    replacement=target.with_name(target.name+'.replacing')
                    replacement.write_bytes(target.read_bytes()+b' ')
                    replacement.replace(target)
                    return checked
                with patch.object(gate,'_validate_run',side_effect=replaced):
                    outcome=gate.execute(campaign,manifest)
                self.assertFalse(outcome['accepted'])
                self.assertEqual(outcome['verified_audit_evidence_sha256'],seen)
                self.assertNotEqual(seen[key],outcome['evidence_sha256'][key])
                self.assertTrue(any('final audit evidence differs' in e and key in e for e in outcome['errors']))
                self.assertEqual(gate.execute(campaign,manifest),outcome)
                self.assertEqual(h.launch.call_count,1)

    def test_replay_rejects_all_eight_replacements_after_its_validation(self):
        for key in sorted(gate.AUDIT_EVIDENCE_KEYS):
            with self.subTest(key=key),self.separate_fixture() as h:
                campaign,manifest=h.prepare();outcome=gate.execute(campaign,manifest)
                self.assertTrue(outcome['accepted'],outcome)
                prior=(campaign/'acceptance.json').read_bytes();real=gate._validate_run
                def replaced(run,frozen):
                    checked=real(run,frozen)
                    path=run/key.removeprefix('run/');path.write_bytes(path.read_bytes()+b' ')
                    return checked
                with patch.object(gate,'_validate_run',side_effect=replaced):
                    replay=gate.read_acceptance(root=h.root)
                self.assertFalse(replay['valid']);self.assertFalse(replay['accepted'])
                self.assertTrue(any('final audit evidence differs' in e and key in e for e in replay['errors']))
                self.assertEqual((campaign/'acceptance.json').read_bytes(),prior)
                with self.assertRaisesRegex(ValueError,'saved acceptance evidence changed'):
                    gate.execute(campaign,manifest)
                self.assertEqual(h.launch.call_count,1)

    def test_final_binding_requires_complete_original_eight_key_map(self):
        campaign,manifest,run=self.saved_fixture()
        result,totals,verified=gate._validate_run(run,manifest)
        self.assertEqual(set(verified),gate.AUDIT_EVIDENCE_KEYS)
        actual=gate._evidence(campaign,run)
        gate._check_audit_binding(verified,actual)
        for missing in sorted(verified):
            incomplete={k:v for k,v in verified.items() if k!=missing}
            with self.subTest(missing=missing),self.assertRaisesRegex(ValueError,'incomplete'):
                gate._check_audit_binding(incomplete,actual)
        altered={**actual,'run/trace.jsonl':'0'*64}
        with self.assertRaisesRegex(ValueError,'verified hashes'):gate._check_audit_binding(verified,altered)

    def test_mac_and_linux_rss_normalization_and_inclusive_limit(self):
        campaign,manifest,run=self.saved_fixture()
        path=campaign/'child_usage.json';data=gate._read(path)
        for platform,unit,factor in [('darwin','bytes',1),('linux','KiB',1024)]:
            value={**data,'platform':platform,'raw_unit':unit,'raw_maxrss':gate.PEAK_RSS_BYTES//factor,
                   'peak_rss_bytes':gate.PEAK_RSS_BYTES}
            path.write_text(json.dumps(value))
            self.assertEqual(gate._validate_peak_rss(campaign,{'pid':7654321})['peak_rss_bytes'],gate.PEAK_RSS_BYTES)
            value.update(raw_maxrss=value['raw_maxrss']+1,peak_rss_bytes=gate.PEAK_RSS_BYTES+factor)
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'8GiB'):gate._validate_peak_rss(campaign,{'pid':7654321})

    def test_rss_wrong_pid_units_platform_and_claimed_hard_guard_rejected(self):
        campaign,manifest,run=self.saved_fixture()
        path=campaign/'child_usage.json';data=gate._read(path)
        for change in ({'pid':7654322},{'raw_maxrss':True},{'raw_maxrss':0},{'raw_unit':'KiB'},
                       {'platform':'unmeasured'},{'peak_rss_bytes':1},{'hard_memory_guard':True}):
            path.write_text(json.dumps({**data,**change}))
            with self.subTest(change=change),self.assertRaises(ValueError):gate._validate_peak_rss(campaign,{'pid':7654321})

    def test_actual_bootstrap_records_same_process_rss_even_on_dummy_module_failure(self):
        # Only a one-line temporary dummy module executes; never the real runner.
        for exit_code in (0,7):
            campaign=self.root/('bootstrap_'+str(exit_code));module=campaign/'frozen/src/smt_fullfab'
            module.mkdir(parents=True)
            (module/'runner.py').write_text('raise SystemExit('+str(exit_code)+')\n')
            for parent in (module,module.parent): (parent/'__init__.py').write_text('')
            outcome=subprocess.run(gate._command(campaign,gate.EXPECTED),capture_output=True,text=True)
            self.assertEqual(outcome.returncode,exit_code,outcome.stderr)
            started=gate._read(campaign/'child_started.json')
            usage=gate._validate_peak_rss(campaign,started)
            self.assertGreater(usage['peak_rss_bytes'],0)
            self.assertFalse(usage['hard_memory_guard'])


if __name__ == '__main__':unittest.main()
