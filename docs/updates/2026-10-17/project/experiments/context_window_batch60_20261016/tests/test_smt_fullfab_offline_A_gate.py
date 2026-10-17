"""Tiny saved-evidence mocks only: no model, factory, CP or real A child."""
from contextlib import ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.smt_fullfab import offline_A_gate as gate


class OfflineAGateTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        for relative in ['src/smt_fullfab', 'src/smt', gate.DATA, gate.VENDOR, 'configs/smt_fullfab']:
            (self.root / relative).mkdir(parents=True)
        for relative in ['src/__init__.py', 'src/smt/__init__.py', 'src/smt_fullfab/__init__.py']:
            (self.root / relative).write_text('')
        for name in ('offline_A_gate.py', 'offline_pilot.py'):
            (self.root / 'src/smt_fullfab' / name).write_bytes(Path(gate.__file__).with_name(name).read_bytes())
        (self.root / 'src/smt_fullfab/runner.py').write_text('# fixture only; never executed\n')
        (self.root / gate.DATA / 'input.txt').write_text('tiny synthetic data')
        (self.root / gate.VENDOR / 'read.py').write_text('# tiny synthetic vendor')
        (self.root / 'requirements.lock').write_text('# fixture lock')
        self.protocol = gate._read(gate.ROOT / gate.PROTOCOL)
        gate._write(self.root / gate.PROTOCOL, self.protocol)
        gate._git_pointer(self.root, '1' * 40)
        self.stack.enter_context(patch.object(gate, '_runtime', return_value={'fixture_runtime_only': True}))
        self.stack.enter_context(patch.object(gate.shutil, 'disk_usage', return_value=SimpleNamespace(free=30 * 1024**3)))
        self.clock = [0.0]
        self.stack.enter_context(patch.object(gate.time, 'monotonic', side_effect=lambda: self.clock[0]))
        self.launch = self.stack.enter_context(patch.object(gate, '_launch', side_effect=self.fake_child))
        self.child_wall = 20.0
        self.post_hook = None
        self.run_mutation = None

    def prepare(self):
        return gate.prepare(root=self.root)

    def fake_child(self, command, frozen, campaign, timeout):
        """Synthesize evidence from the exact frozen manifest, not live source."""
        manifest = gate._read(campaign / 'manifest.json')
        config = manifest['config']
        self.assertEqual(command, gate._command(campaign, config))
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 4200)
        self.clock[0] += self.child_wall
        gate._write(campaign / 'child_started.json', {'pid': 7654321, 'started_at': 'fixture'})
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
        audit = dict(valid=True, metrics={'fixture_only': True},
                     plan_source_audit=dict(valid=True, production_machine_count=913,
                         declared_control_machine_count=913, declared_full_factory_domain=True),
                     opportunity_audit=dict(valid=True))
        gate._write(run / 'audit.json', audit)
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
            hybrid_resource_limits=dict(runner_wall_seconds=3600.0, max_plans=1200, max_log_bytes=8 * 1024**3)))
        result = dict(config=config, identity=gate._digest(config), provenance=provenance,
            status='success', full_window_completed=True, simulation_seconds=28800, audit_valid=True,
            model_calls=0, formal=False, metrics=audit['metrics'], wall_seconds=19.0,
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

    def test_status_must_reject_runner_success_until_outer_acceptance_exists(self):
        campaign, manifest = self.prepare()
        gate._write(campaign / 'attempt.json', {'interrupted': True})
        self.fake_child(gate._command(campaign, manifest['config']), campaign / 'frozen', campaign, 4200)
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
            self.clock[0] += 4200.1
            return dict(pid=42, returncode=-9, timed_out=True, wall_seconds=4200.1)
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
        for key, value in [('arm', 'B'), ('seconds', 3600), ('solver_budget_seconds', 60.0),
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
        self.child_wall = 4201
        outcome = gate.execute(campaign, manifest)
        self.assertFalse(outcome['accepted'])
        self.assertIn('outer final wall exceeds4200 seconds', outcome['errors'])
        self.assertEqual(gate._read(Path(manifest['output_directory']) / 'result.json')['status'], 'success')

    def test_stdout_and_frozen_files_count_toward_eight_gib(self):
        campaign, manifest = self.prepare()
        original = gate._bytes
        with patch.object(gate, '_bytes', side_effect=lambda c, r: original(c, r) + gate.EXPECTED['max_log_bytes']):
            outcome = gate.execute(campaign, manifest)
        self.assertFalse(outcome['accepted'])
        self.assertIn('final total evidence exceeds8GiB', outcome['errors'])

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
            path = run / 'result.json';data = gate._read(path);data['wall_seconds'] = 3601;path.write_text(json.dumps(data))
        self.run_mutation = mutate
        self.assertFalse(gate.execute(campaign, manifest)['accepted'])

    def test_child_exit_after_3600_is_not_hidden_by_earlier_runner_timestamp(self):
        campaign, manifest = self.prepare()
        self.child_wall = 3600.1
        outcome = gate.execute(campaign, manifest)
        self.assertFalse(outcome['accepted'])
        self.assertTrue(any('measured wall' in e for e in outcome['errors']))
        self.assertLess(gate._read(Path(manifest['output_directory']) / 'result.json')['wall_seconds'], 3600)

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
        def grow_sparse_trace(run):
            with (run / 'trace.jsonl').open('r+b') as stream:stream.truncate(gate.TRACE_BYTES + 1)
        # A sparse file avoids allocating/scanning a real 256MiB trace. Hashing
        # this one synthetic path is replaced; production validation is real.
        self.run_mutation = grow_sparse_trace
        real_sha = gate._sha
        with patch.object(gate, '_sha', side_effect=lambda p: '0' * 64 if Path(p).name == 'trace.jsonl' else real_sha(p)):
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


if __name__ == '__main__':unittest.main()
