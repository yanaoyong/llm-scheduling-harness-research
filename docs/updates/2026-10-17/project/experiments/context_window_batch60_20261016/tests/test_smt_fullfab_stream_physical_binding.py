"""Small handwritten fixtures only; no factory/model/solver/saved run input."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt.audit import audit_trace as oracle
from src.smt_fullfab.trace_source import IncompleteReadError, SourceChangedError, TraceSourceError, inspect_jsonl

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


binding = load('isolated_physical_binding', HERE.parent / 'src/smt_fullfab/stream_physical_binding.py')
probe = load('tiny_binding_fixture', HERE.parent / 'artifacts/smt_fullfab_review_drafts/stream_physical_checker_v1/probe_small_contract.py')


class PhysicalBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.source = self.path / 'source.jsonl'
        self.bundle = self.path / 'bundle'
        self.report = self.path / 'report.json'
        self.make_bundle()

    def make_bundle(self, events=None):
        self.events = probe.fixture() if events is None else events
        self.source.write_text(''.join(json.dumps(e) + '\n' for e in self.events))
        result = binding.projection.project_physical_trace(self.source, output_dir=self.bundle)
        self.evidence = {key: result[key] for key in binding.EVIDENCE_FIELDS}

    def run_binding(self, **kwargs):
        return binding.audit_projection_to_file(self.bundle, source=self.source,
            expected_evidence=self.evidence, report_path=self.report, **kwargs)

    def no_publication(self):
        self.assertFalse(os.path.lexists(self.report))
        self.assertEqual(list(self.path.glob('.report.json.*.partial')), [])

    def replace(self, path, raw=None):
        replacement = path.with_suffix(path.suffix + '.replacement')
        replacement.write_bytes(path.read_bytes() if raw is None else raw)
        replacement.replace(path)

    def test_complete_parity_receipts_scopes_and_exact_written_hash(self):
        descriptor = self.run_binding()
        raw = self.report.read_bytes()
        actual = json.loads(raw)
        physical = actual['physical_report']
        scope = physical.pop('_core_scope')
        physical['audit_version'] = binding.core.REFERENCE_VERSION
        self.assertEqual(json.dumps(physical, separators=(',', ':')), json.dumps(oracle(self.events), separators=(',', ':')))
        self.assertEqual(actual['core_scope'], scope)
        self.assertFalse(scope['projection_binding_verified'])  # Keep original core claim unchanged.
        self.assertTrue(actual['scope']['projection_complete_eof_verified'])
        self.assertTrue(actual['scope']['core_report_arrays_in_memory'])
        for name in ('plan_source_audit_performed', 'opportunity_audit_performed',
                     'model_attribution_verified', 'long_window_readiness_certified'):
            self.assertFalse(actual['scope'][name])
        evidence = actual['_source_evidence']
        self.assertTrue(evidence['complete_verified_context_exit'])
        self.assertEqual(evidence['source_receipt'], self.evidence['source_receipt'])
        self.assertEqual(evidence['consumption_receipt'], self.evidence['output_receipt'])
        self.assertEqual(evidence['expected_evidence'], self.evidence)
        self.assertEqual(evidence['projection_manifest'], json.loads((self.bundle / 'projection.json').read_bytes()))
        self.assertEqual(descriptor['report_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(descriptor['report_byte_count'], len(raw))
        self.assertTrue(descriptor['physical_valid'])
        self.assertTrue(descriptor['durable_publication_complete'])
        self.assertEqual(list(self.path.glob('.report.json.*.partial')), [])

    def test_supplied_seal_uses_same_complete_evidence(self):
        seal = inspect_jsonl(self.source)
        result = binding.audit_projection_to_file(self.bundle, source=seal,
            expected_evidence=self.evidence, report_path=self.report)
        self.assertTrue(result['physical_valid'])

    def test_publisher_runs_only_after_successful_context_receipt(self):
        seen = {}
        original = binding.projection.open_verified_projection
        publish = binding._publish_report
        @contextmanager
        def observe(*args, **kwargs):
            with original(*args, **kwargs) as reader:
                seen['reader'] = reader
                yield reader
                self.assertIsNone(reader.receipt)
            seen['context_exited'] = True
        def guarded_publish(*args, **kwargs):
            self.assertTrue(seen['context_exited'])
            self.assertIsNotNone(seen['reader'].receipt)
            return publish(*args, **kwargs)
        with patch.object(binding.projection, 'open_verified_projection', observe), patch.object(binding, '_publish_report', guarded_publish):
            self.run_binding()

    def test_unconsumed_core_result_never_publishes(self):
        def early(events, *args, **kwargs):
            next(events)
            return {'valid': True}
        with patch.object(binding.core, 'audit_events', early), self.assertRaises(IncompleteReadError):
            self.run_binding()
        self.no_publication()

    def test_exact_record_count_without_eof_is_insufficient(self):
        def exact_count(events, *args, **kwargs):
            for _ in range(self.evidence['output_receipt']['event_count']):next(events)
            return {'valid': True}
        with patch.object(binding.core, 'audit_events', exact_count), self.assertRaises(IncompleteReadError):
            self.run_binding()
        self.no_publication()

    def test_core_exception_preserved_without_final_file(self):
        def broken(events, *args, **kwargs):
            next(events)
            raise TypeError('physical primary exception')
        with patch.object(binding.core, 'audit_events', broken), self.assertRaisesRegex(TypeError, '^physical primary exception$'):
            self.run_binding()
        self.no_publication()

    def test_source_truncated_since_bundle_creation(self):
        self.source.write_bytes(self.source.read_bytes()[:-10])
        with self.assertRaises(TraceSourceError):self.run_binding()
        self.no_publication()

    def test_projection_truncated_since_bundle_creation(self):
        target = self.bundle / 'physical.jsonl'
        target.write_bytes(target.read_bytes()[:-10])
        with self.assertRaises(TraceSourceError):self.run_binding()
        self.no_publication()

    def test_invalid_last_json_line_never_certified(self):
        target = self.bundle / 'physical.jsonl'
        with target.open('ab') as stream:stream.write(b'{wrong final line\n')
        with self.assertRaises(TraceSourceError):self.run_binding()
        self.no_publication()

    def test_well_formed_changed_last_line_even_rehashed_manifest_rejected(self):
        target = self.bundle / 'physical.jsonl'
        events = [json.loads(line) for line in target.read_bytes().splitlines()]
        events[-1]['lot_statuses']['x'] = 'ready'
        target.write_text(''.join(json.dumps(event) + '\n' for event in events))
        seal = inspect_jsonl(target)
        receipt = {key: getattr(seal, key) for key in binding.RECEIPT_FIELDS}
        manifest_path = self.bundle / 'projection.json'
        manifest = json.loads(manifest_path.read_bytes());manifest['output_receipt'] = receipt
        raw = json.dumps(manifest).encode();manifest_path.write_bytes(raw)
        self.evidence['output_receipt'] = receipt
        self.evidence['manifest_sha256'] = hashlib.sha256(raw).hexdigest()
        with self.assertRaises(TraceSourceError):self.run_binding()
        self.no_publication()

    def test_complete_physically_invalid_source_publishes_invalid_diagnostics(self):
        for child in self.bundle.iterdir():child.unlink()
        self.bundle.rmdir()
        events = probe.fixture();events[-1]['lot_statuses']['x'] = 'ready'
        self.make_bundle(events)
        result = self.run_binding()
        actual = json.loads(self.report.read_bytes())['physical_report']
        self.assertFalse(result['physical_valid'])
        self.assertFalse(actual['valid'])
        self.assertEqual(actual['errors'], oracle(events)['errors'])
        self.assertTrue(json.loads(self.report.read_bytes())['_source_evidence']['complete_verified_context_exit'])

    def test_complete_source_missing_terminal_keeps_physical_error(self):
        for child in self.bundle.iterdir():child.unlink()
        self.bundle.rmdir()
        events = probe.fixture()[:-1];self.make_bundle(events)
        result = self.run_binding()
        self.assertFalse(result['physical_valid'])
        actual = json.loads(self.report.read_bytes())['physical_report']
        self.assertEqual(actual['errors'], oracle(events)['errors'])

    def _replace_during_core(self, target, raw=None):
        original = binding.core.audit_events
        def replacing(*args, **kwargs):
            result = original(*args, **kwargs)
            self.replace(target, raw)
            return result
        with patch.object(binding.core, 'audit_events', replacing), self.assertRaises(SourceChangedError):
            self.run_binding()
        self.no_publication()

    def test_same_bytes_source_replacement_during_core_rejected(self):
        self._replace_during_core(self.source)

    def test_same_bytes_manifest_replacement_during_core_rejected(self):
        self._replace_during_core(self.bundle / 'projection.json')

    def test_same_bytes_output_replacement_after_core_eof_rejected(self):
        self._replace_during_core(self.bundle / 'physical.jsonl')

    def test_forged_output_replacement_after_core_eof_rejected(self):
        self._replace_during_core(self.bundle / 'physical.jsonl', b'{"kind":"forged"}\n')

    def test_output_replaced_between_verification_and_consumer_is_rejected(self):
        original = binding.projection._verify_projection_bundle
        def replacing(*args, **kwargs):
            result = original(*args, **kwargs)
            self.replace(self.bundle / 'physical.jsonl')
            return result
        with patch.object(binding.projection, '_verify_projection_bundle', replacing), self.assertRaises(SourceChangedError):
            self.run_binding()
        self.no_publication()

    def test_source_replacement_during_publication_rolls_back(self):
        original = binding._fsync_directory
        def replacing(path):
            if self.report.exists():self.replace(self.source)
            return original(path)
        with patch.object(binding, '_fsync_directory', replacing), self.assertRaises(SourceChangedError):
            self.run_binding()
        self.no_publication()

    def test_expected_receipt_type_and_fields_are_not_coerced(self):
        saved = deepcopy(self.evidence)
        cases = []
        changed = deepcopy(saved);changed['source_receipt']['line_count'] = True;cases.append(changed)
        changed = deepcopy(saved);changed['output_receipt']['event_count'] += 1;cases.append(changed)
        changed = deepcopy(saved);del changed['source_receipt']['max_record_bytes'];cases.append(changed)
        changed = deepcopy(saved);changed['manifest_sha256'] = 'a' * 64;cases.append(changed)
        changed = deepcopy(saved);changed['undeclared'] = 1;cases.append(changed)
        for case in cases:
            with self.subTest(case=case):
                self.evidence = case
                with self.assertRaises(binding.BindingError):self.run_binding()
                self.no_publication()

    def test_dependency_hash_mismatch_is_not_silently_accepted(self):
        with patch.dict(binding.DEPENDENCIES, {'src/smt/source_check.py': 'a' * 64}), self.assertRaisesRegex(binding.BindingError, 'frozen dependency changed'):
            self.run_binding()
        self.no_publication()

    def test_existing_file_or_symlink_is_not_overwritten(self):
        self.report.write_bytes(b'original')
        with patch.object(binding.core, 'audit_events') as core_call, self.assertRaises(FileExistsError):self.run_binding()
        core_call.assert_not_called();self.assertEqual(self.report.read_bytes(), b'original')
        self.report.unlink();self.report.symlink_to(self.path / 'missing')
        with self.assertRaises(FileExistsError):self.run_binding()
        self.assertTrue(self.report.is_symlink())

    def test_target_created_during_serialization_is_not_overwritten(self):
        original = binding.os.link
        def raced_link(source, target):
            target.write_bytes(b'other publisher')
            return original(source, target)
        with patch.object(binding.os, 'link', raced_link), self.assertRaises(FileExistsError):self.run_binding()
        self.assertEqual(self.report.read_bytes(), b'other publisher')
        self.assertEqual(list(self.path.glob('.report.json.*.partial')), [])

    def test_file_fsync_failure_leaves_no_final_or_partial(self):
        with patch.object(binding.os, 'fsync', side_effect=OSError('file fsync failed')), self.assertRaisesRegex(OSError, 'file fsync failed'):
            self.run_binding()
        self.no_publication()

    def test_directory_fsync_failure_rolls_back_own_link(self):
        with patch.object(binding, '_fsync_directory', side_effect=OSError('directory fsync failed')), self.assertRaisesRegex(OSError, 'directory fsync failed'):
            self.run_binding()
        self.no_publication()

    def test_second_directory_fsync_failure_after_alias_removal_rolls_back(self):
        original = binding._fsync_directory
        calls = 0
        def second_failure(path):
            nonlocal calls
            calls += 1
            if calls == 2:raise OSError('second directory fsync failed')
            return original(path)
        with patch.object(binding, '_fsync_directory', second_failure), self.assertRaisesRegex(OSError, 'second directory fsync failed'):
            self.run_binding()
        self.no_publication()

    def test_serialization_interrupted_mid_record_never_publishes(self):
        def interrupted(encoder, value):
            yield '{"status":"complete",'
            raise KeyboardInterrupt('interrupted write')
        with patch.object(binding.json.JSONEncoder, 'iterencode', interrupted), self.assertRaises(KeyboardInterrupt):
            binding._publish_report({'irrelevant': True}, self.report, lambda: None)
        self.no_publication()

    def test_same_inode_report_mutation_during_last_directory_fsync_rejected(self):
        original = binding._fsync_directory
        calls = 0
        def changing(path):
            nonlocal calls
            calls += 1
            if calls == 2:
                with self.report.open('r+b') as stream:stream.write(b'X')
            return original(path)
        with patch.object(binding, '_fsync_directory', changing), self.assertRaises(SourceChangedError):
            self.run_binding()
        self.no_publication()

    def test_link_interruption_before_visibility_leaves_no_final(self):
        with patch.object(binding.os, 'link', side_effect=KeyboardInterrupt('before link')), self.assertRaises(KeyboardInterrupt):
            self.run_binding()
        self.no_publication()

    def test_link_interruption_after_visibility_rolls_back_complete_file(self):
        original = binding.os.link
        def interrupted(source, target):
            original(source, target)
            raise KeyboardInterrupt('after link')
        with patch.object(binding.os, 'link', interrupted), self.assertRaises(KeyboardInterrupt):
            self.run_binding()
        self.no_publication()

    def test_final_path_replacement_is_not_rehashed_or_certified_or_deleted(self):
        original = binding._fsync_directory
        replaced = False
        def replacing(path):
            nonlocal replaced
            if self.report.exists() and not replaced:
                self.replace(self.report, b'{"valid":true,"unrelated":true}\n')
                replaced = True
            return original(path)
        with patch.object(binding, '_fsync_directory', replacing), self.assertRaises(SourceChangedError):
            self.run_binding()
        self.assertEqual(self.report.read_bytes(), b'{"valid":true,"unrelated":true}\n')
        self.assertEqual(list(self.path.glob('.report.json.*.partial')), [])

    def test_non_json_serialization_failure_leaves_no_success_file(self):
        original = binding.core.audit_events
        def non_json(*args, **kwargs):
            result = original(*args, **kwargs);result['test_only'] = object();return result
        with patch.object(binding.core, 'audit_events', non_json), self.assertRaises(TypeError):
            self.run_binding()
        self.no_publication()


if __name__ == '__main__':
    unittest.main()
