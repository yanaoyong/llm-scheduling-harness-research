"""Installed private-flow fault injection; temporary synthetic evidence only.

Authored statically. No actual transport/factory/solver is called by these
fixtures. Shared accounting/archives/period/byte checks stay real. Boundary
engines are explicit mocks except the early rejection cases that enter the
actual installed stream attribution stage.
"""
from copy import deepcopy
import json
from pathlib import Path
import types
import unittest
from unittest.mock import patch

from tests.test_smt_fullfab_C_stream_private_wire import fixture
from src.smt_fullfab import C_stream_attribution_stage as stage

c, a = fixture.c, fixture.a


def literal_action(action, *, index=None, method=None, seconds=None, seed=None):
    return {'action': action, 'index': index, 'method': method, 'seconds': seconds,
            'seed': seed, 'slots': 1 if action == 'solve' else None,
            'weights': {'completion': 1, 'flow': 1, 'tardiness': 1, 'setup': 1},
            'reason': 'explicit synthetic action; never an automatic fallback'}


class TerminalBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.f = self.fresh_fixture()

    def fresh_fixture(self):
        value = fixture.PrivateWireTests('test_complete_query_two_tools_inspect_explicit_old_apply_and_costs')
        value.setUp()
        self.addCleanup(value.doCleanups)
        return value

    def failed(self, result, text=None):
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['accepted'])
        self.assertFalse(result['real_C8_launch_authorized'])
        self.assertEqual(result['launch_authority_scope'], 'controller_does_not_self_authorize')
        self.assertEqual(result['acceptance_authority'], 'external_frozen_gate')
        self.assertFalse(result['direct_public_execution_enabled'])
        self.assertNotIn('remaining_blocker', result)
        if text:
            self.assertIn(text, result['failure'])
        self.assertTrue((self.f.run / 'execution_result.json').exists())

    def exact_final_bytes(self, result):
        actual = c.byte_count(self.f.run) + c.byte_count(self.f.scratch)
        self.assertEqual(actual, result['cumulative_log_bytes_including_result'])
        self.assertEqual((self.f.run / 'result.json').read_bytes(), a.encode(result))

    def scripted_model(self, actions, *, unknown_usage=False):
        f = self.f
        def model(prompt, schema, directory, config):
            history = json.loads(prompt.split('\nOWN_HISTORY\n', 1)[1].split('\nLIMITS\n', 1)[0])
            response = deepcopy(actions[len(history)])
            index = len(f.prompts)
            f.prompts.append(prompt)
            directory = Path(directory)
            directory.mkdir()
            cid = 'scripted-tiny-' + str(index)
            f.ledger.append({'event': 'reserve', 'call_id': cid, 'run_id': str(directory),
                'registration_id': f.ledger.registration['registration_id'],
                'metadata': {'timeout_seconds': config.timeout_seconds}})
            usage = {} if unknown_usage else {'input_tokens': 10, 'output_tokens': 2}
            result = {'call_id': cid, 'output': response, 'status': 'success', 'usage': usage,
                      'duration_seconds': 1.0, 'failure_reason': None}
            f.ledger.append({'event': 'finish', 'call_id': cid, 'status': 'success',
                             'details': {'usage': usage, 'duration_seconds': 1.0}})
            (directory / 'prompt.txt').write_text(prompt)
            a.write_new(directory / 'request.json', {'call_id': cid, 'synthetic_transport': True})
            a.write_new(directory / 'schema.json', schema)
            a.write_new(directory / 'result.json', result)
            a.write_new(directory / 'final.txt', response)
            (directory / 'events.jsonl').write_bytes(a.encode({'type': 'turn.completed', 'usage': usage}))
            return result
        f.model = model

    def constructor_sequence(self, *, unknown_usage=False):
        self.scripted_model([literal_action('read_page', index=0),
            literal_action('solve', method='constructive', seconds=5, seed=11),
            literal_action('apply', index=0)], unknown_usage=unknown_usage)

    def replace_trace(self, *, same_bytes):
        path = self.f.run / 'trace.jsonl'
        replacement = path.with_name('trace-replacement.tmp')
        raw = path.read_bytes()
        replacement.write_bytes(raw if same_bytes else raw + b'\n')
        replacement.replace(path)

    def test_scratch_overrun_is_failed_and_counted_in_actual_final_bytes(self):
        normal = self.f.attribution
        cap = 16 * 1024 * 1024  # Sparse capacity probe, not 24 GiB allocation.
        def overflow(run, **kwargs):
            value = normal(run, **kwargs)
            with (Path(kwargs['scratch_dir']) / 'sparse-capacity-probe').open('xb') as stream:
                stream.truncate(cap)
            return value
        self.f.attribution = overflow
        with patch.dict(c.PROPOSAL, {'max_log_bytes': cap}):
            result = self.f.invoke()
        self.assertEqual(len(self.f.stage_calls), 1)
        self.failed(result, 'log cap')
        self.assertGreaterEqual(result['attribution_scratch']['bytes'], cap)
        self.exact_final_bytes(result)

    def test_only_final_result_encoding_crosses_registered_log_cap(self):
        # Obtain a same-fixture size, not a runtime prediction. The second run
        # is a separate temporary synthetic run, with no actual budget ledger.
        baseline = self.f.invoke()
        self.assertEqual(baseline['status'], 'success', baseline['failure'])
        result_size = (self.f.run / 'result.json').stat().st_size
        existing = c.byte_count(self.f.run) + c.byte_count(self.f.scratch) - result_size
        cap = existing + result_size // 2
        self.f = self.fresh_fixture()
        with patch.dict(c.PROPOSAL, {'max_log_bytes': cap}):
            result = self.f.invoke()
        self.assertEqual(result['plans_committed'], 16)
        self.assertEqual(len(self.f.stage_calls), 1)
        self.failed(result, 'final log volume cap including result publication')
        final_size = (self.f.run / 'result.json').stat().st_size
        self.assertLess(result['cumulative_log_bytes_including_result'] - final_size, cap)
        self.assertGreater(result['cumulative_log_bytes_including_result'], cap)
        self.exact_final_bytes(result)

    def test_audit_wall_overrun_is_failed_without_new_calls(self):
        clock = [0.0]
        normal = self.f.attribution
        def late(run, **kwargs):
            value = normal(run, **kwargs)
            clock[0] = c.PROPOSAL['wall_seconds'] + 1
            return value
        self.f.attribution = late
        with patch.object(c, 'time', types.SimpleNamespace(monotonic=lambda: clock[0])):
            result = self.f.invoke()
        self.failed(result, 'wall cap')
        self.assertEqual(result['model_calls'], 64)
        self.exact_final_bytes(result)

    def test_wall_crossing_during_first_result_encoding_rejects(self):
        clock = [0.0]
        original = c.include_result_bytes
        def encode_then_expire(result, **kwargs):
            original(result, **kwargs)
            clock[0] = c.PROPOSAL['wall_seconds'] + 1
        with patch.object(c, 'time', types.SimpleNamespace(monotonic=lambda: clock[0])), \
                patch.object(c, 'include_result_bytes', encode_then_expire):
            result = self.f.invoke()
        self.failed(result, 'final wall cap')
        self.exact_final_bytes(result)

    def test_trace_growth_at_final_resource_check_rejects(self):
        original = c.check_resources
        injected = False
        def check(out, cfg, started, **kwargs):
            nonlocal injected
            if self.f.stage_calls and not injected:
                injected = True
                with (Path(out) / 'trace.jsonl').open('ab') as stream:
                    stream.write(b' ' * (cfg['max_trace_bytes'] + 1))
            return original(out, cfg, started, **kwargs)
        with patch.dict(c.PROPOSAL, {'max_trace_bytes': 65536}), patch.object(c, 'check_resources', check):
            result = self.f.invoke()
        self.assertTrue(injected)
        self.failed(result, 'raw trace cap')
        self.exact_final_bytes(result)

    def test_trace_different_bytes_after_physical_are_not_reanchored(self):
        normal = self.f.physical
        def replaced(*args, **kwargs):
            value = normal(*args, **kwargs)
            self.replace_trace(same_bytes=False)
            return value
        self.f.physical = replaced
        result = self.f.invoke()
        self.failed(result, 'terminal independent audit')
        self.assertFalse(result['terminal_trace_binding_valid'])

    def test_trace_same_bytes_new_inode_after_physical_are_rejected(self):
        normal = self.f.physical
        def replaced(*args, **kwargs):
            value = normal(*args, **kwargs)
            self.replace_trace(same_bytes=True)
            return value
        self.f.physical = replaced
        result = self.f.invoke()
        self.failed(result, 'identity changed')
        self.assertFalse(result['terminal_trace_binding_valid'])

    def test_trace_same_bytes_new_inode_after_attribution_are_rejected(self):
        normal = self.f.attribution
        def replaced(*args, **kwargs):
            value = normal(*args, **kwargs)
            self.replace_trace(same_bytes=True)
            return value
        self.f.attribution = replaced
        result = self.f.invoke()
        self.failed(result, 'identity changed')
        self.assertFalse(result['terminal_trace_binding_valid'])

    def test_actual_stage_rejects_execution_changed_after_first_stage_read(self):
        self.f.attribution = stage.audit_execution_stage
        original = stage.snapshot
        changed = False
        def snapshot(path, expected=None):
            nonlocal changed
            value = original(path, expected)
            if Path(path).name == 'execution_result.json' and not changed:
                changed = True
                Path(path).write_bytes(b'{"replaced_after_stage_read":true}\n')
            return value
        with patch.object(stage, 'snapshot', snapshot):
            result = self.f.invoke()
        self.assertTrue(changed)
        self.failed(result, 'execution-stage anchor differs')
        self.assertFalse(result['terminal_trace_binding_valid'])

    def test_actual_stage_rejects_dependency_modified_after_source_snapshot(self):
        self.f.attribution = stage.audit_execution_stage
        normal = self.f.physical
        def replaced(*args, **kwargs):
            value = normal(*args, **kwargs)
            path = self.f.run / 'source_snapshot/attribution_stream_v2/storage.py'
            with path.open('ab') as stream:
                stream.write(b'\nUNREVIEWED_LATE_CHANGE = True\n')
            return value
        self.f.physical = replaced
        result = self.f.invoke()
        self.failed(result, 'hash changed')
        self.assertFalse(result['terminal_trace_binding_valid'])

    def test_zero_cp_allows_explicit_constructor_read_and_apply(self):
        self.constructor_sequence()
        self.f.ledger.solver_remaining_seconds = lambda *args, **kwargs: 0
        result = self.f.invoke()
        self.assertEqual(result['status'], 'success', result['failure'])
        self.assertEqual(result['solver_calls'], 0)
        self.assertEqual(result['constructor_calls'], 16)
        self.assertEqual(result['model_calls'], 48)

    def test_zero_cp_rejects_explicit_cp_request_before_solver_reserve(self):
        self.f.ledger.solver_remaining_seconds = lambda *args, **kwargs: 0
        result = self.f.invoke()
        self.failed(result, 'cumulative solve budget')
        self.assertEqual(result['model_calls'], 3)
        self.assertEqual(result['constructor_calls'], 1)
        self.assertEqual(result['solver_calls'], 0)
        self.assertEqual(result['plans_committed'], 0)

    def test_active_exhaustion_stops_before_any_model_reserve(self):
        self.f.ledger.constructor_remaining_seconds = lambda *args, **kwargs: 0
        result = self.f.invoke()
        self.failed(result, 'no remaining registered')
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(self.f.prompts, [])
        self.assertFalse(any(row['event'].endswith('reserve') for row in fixture.rows(self.f.ledger.path)))

    def test_insufficient_constructor_balance_rejects_before_tool_reserve(self):
        self.f.ledger.constructor_remaining_seconds = lambda *args, **kwargs: 1
        result = self.f.invoke()
        self.failed(result, 'construction request budget')
        self.assertEqual(result['model_calls'], 2)
        self.assertEqual(result['constructor_calls'], 0)
        self.assertEqual(result['solver_calls'], 0)

    def test_unknown_constructor_status_cannot_be_explicitly_applied(self):
        self.constructor_sequence()
        original = self.f.tool
        def invalid(*args, **kwargs):
            value = original(*args, **kwargs)
            value['solver_status'] = 'UNKNOWN'
            return value
        self.f.tool = invalid
        result = self.f.invoke()
        self.failed(result, 'candidate is invalid')
        self.assertEqual(result['plans_committed'], 0)
        self.assertEqual(result['model_calls'], 3)
        self.assertEqual(result['constructor_calls'], 1)

    def test_invalid_nominal_constructor_cannot_be_explicitly_applied(self):
        self.constructor_sequence()
        original = self.f.tool
        def invalid(*args, **kwargs):
            value = original(*args, **kwargs)
            value['nominal_audit'] = {'valid': False}
            return value
        self.f.tool = invalid
        result = self.f.invoke()
        self.failed(result, 'candidate is invalid')
        self.assertEqual(result['plans_committed'], 0)
        self.assertEqual(result['constructor_calls'], 1)

    def test_successful_unknown_usage_stays_unknown_and_does_not_add_a_cap(self):
        self.constructor_sequence(unknown_usage=True)
        result = self.f.invoke()
        self.assertEqual(result['status'], 'success', result['failure'])
        account = a.snapshot(self.f.run / 'ledger_final_account.json')[0]['account']
        self.assertEqual(len(account['unknown_completed']), 48)
        self.assertEqual(account['reported_input_output_tokens'], 0)
        self.assertEqual(result['model_calls'], 48)
        self.assertEqual(result['plans_committed'], 16)
        self.assertFalse(account['pending'])

    def test_snapshot_partial_failure_preserves_partial_and_failed_result(self):
        def partial(env, path):
            Path(path).write_bytes(b'{"partial":')
            raise OSError('synthetic snapshot short write')
        self.f.snapshot = partial
        result = self.f.invoke()
        self.failed(result, 'snapshot short write')
        self.assertEqual((self.f.run / 'checkpoint.json').read_bytes(), b'{"partial":')
        self.assertIsNone(result['checkpoint'])
        self.assertEqual(result['plans_committed'], 16)
        self.assertEqual(self.f.stage_calls, [])

    def test_ledger_snapshot_failure_does_not_invent_account_or_retry(self):
        original = c.raw_snapshot
        def fail(path, expected=None):
            if Path(path) == self.f.ledger.path:
                raise OSError('synthetic ledger snapshot failure')
            return original(path, expected)
        with patch.object(c, 'raw_snapshot', fail):
            result = self.f.invoke()
        self.failed(result, 'ledger snapshot failure')
        self.assertIsNone(result['model_calls'])
        self.assertEqual(len(self.f.prompts), 64)
        self.assertFalse((self.f.run / 'ledger_final_account.json').exists())
        self.assertEqual(len([row for row in fixture.rows(self.f.ledger.path) if row['event'] == 'reserve']), 64)

    def test_attribution_exception_keeps_completed_execution_and_raw_costs(self):
        def fail(run, **kwargs):
            raise RuntimeError('synthetic complete attribution exception')
        self.f.attribution = fail
        result = self.f.invoke()
        self.failed(result, 'attribution exception')
        self.assertFalse(result['audit_valid'])
        self.assertFalse((self.f.run / 'controller_attribution_stage.json').exists())
        self.assertEqual(result['plans_committed'], 16)
        self.assertEqual(result['model_calls'], 64)

    def test_result_fixed_point_exception_leaves_no_success_result(self):
        with patch.object(c, 'include_result_bytes', side_effect=RuntimeError('synthetic fixed point failure')):
            with self.assertRaisesRegex(RuntimeError, 'fixed point failure'):
                self.f.invoke()
        self.assertFalse((self.f.run / 'result.json').exists())
        self.assertEqual(a.snapshot(self.f.run / 'execution_result.json')[0]['status'], 'awaiting_attribution')
        self.assertTrue((self.f.run / 'ledger_final_account.json').exists())

    def test_actual_final_writer_short_write_leaves_partial_without_returned_hash(self):
        original = Path.open
        class ShortWriter:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                self.stream.__enter__()
                return self
            def __exit__(self, *args):
                return self.stream.__exit__(*args)
            def __getattr__(self, name):
                return getattr(self.stream, name)
            def write(self, raw):
                return self.stream.write(raw[:5])
        def open_path(path, mode='r', *args, **kwargs):
            stream = original(path, mode, *args, **kwargs)
            if Path(path) == self.f.run / 'result.json' and mode == 'xb':
                return ShortWriter(stream)
            return stream
        with patch.object(Path, 'open', open_path):
            with self.assertRaisesRegex(OSError, 'short original evidence write'):
                self.f.invoke()
        self.assertEqual((self.f.run / 'result.json').stat().st_size, 5)
        with self.assertRaises(ValueError):
            a.snapshot(self.f.run / 'result.json')
        self.assertTrue((self.f.run / 'execution_result.json').exists())
        self.assertEqual(len(self.f.prompts), 64)


if __name__ == '__main__':
    unittest.main()
