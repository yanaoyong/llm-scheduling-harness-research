"""Tiny saved-event transformations only; no physical replay/model/solver."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab import audit as reference
from src.smt_fullfab import stream_physical_projection as projection
from src.smt_fullfab.trace_source import (IncompleteReadError, SourceChangedError, TraceSourceError,
                                          TraceRecord, inspect_jsonl)
from tests.test_smt_fullfab_audit import trace_fixture, renumber


def reference_projection(events):
    """Capture the actual old adapter loop; replace all audits with explicit stubs."""
    captured = []
    def capture(projected, *_):
        captured.extend(deepcopy(projected))
        return {'valid': True, 'errors': [], 'verified_input_hashes': False}
    with (patch.object(reference, 'audit_plan_sources', return_value={'errors': []}),
          patch.object(reference, 'audit_opportunity_coverage', return_value={'valid': True, 'errors': []}),
          patch.object(reference, 'compute_metrics', return_value={}),
          patch('src.smt.audit.audit_trace', side_effect=capture)):
        reference.audit_trace(events)
    return captured


class StreamPhysicalProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='smt_fullfab_projection_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'source.jsonl'
        self.bundle = self.root / 'projection'
        self.events = trace_fixture()
        self.write_source(self.events)

    def write_source(self, events):
        self.source.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n\n' for e in events))

    def project(self):
        return projection.project_physical_trace(self.source, output_dir=self.bundle)

    def verify(self, expected=None):
        return projection.verify_projection_bundle(self.bundle, source=self.source, expected_manifest_sha256=expected)

    def read_events(self):
        return [json.loads(line) for line in (self.bundle / 'physical.jsonl').read_text().splitlines() if line.strip()]

    def read_manifest(self):
        return json.loads((self.bundle / 'projection.json').read_text())

    def rewrite(self, name, value):
        (self.bundle / name).write_text(json.dumps(value, ensure_ascii=False) + '\n')

    def assert_unfinished(self):
        self.assertTrue(self.bundle.is_dir())
        self.assertFalse((self.bundle / 'projection.json').exists())
        with self.assertRaises(projection.ProjectionError):
            self.verify()
        with self.assertRaises(FileExistsError):
            self.project()

    def test_exact_old_projection_and_complete_durable_receipts(self):
        before = self.source.read_bytes()
        created = self.project()
        expected = reference_projection(self.events)
        actual = self.read_events()
        self.assertEqual(actual, expected)
        self.assertEqual([e['seq'] for e in actual], list(range(len(actual))))
        self.assertEqual(self.source.read_bytes(), before)
        self.assertNotIn('physical_path', created)
        self.assertTrue(created['verification_required_before_use'])
        verified = self.verify(created['manifest_sha256'])
        self.assertTrue(verified['projection_verified'])
        self.assertEqual(verified['physical_path'], str(self.bundle / 'physical.jsonl'))
        self.assertEqual(verified['source_receipt']['sha256'], hashlib.sha256(before).hexdigest())
        raw = (self.bundle / 'physical.jsonl').read_bytes()
        self.assertEqual(verified['output_receipt']['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(verified['output_receipt']['event_count'], len(actual))
        self.assertEqual(verified['conversion_counts']['synthetic_action_count'], 1)
        self.assertEqual(self.read_manifest()['source_receipt'], created['source_receipt'])
        self.assertFalse(verified['scope']['synthetic_actions_are_model_decisions'])
        self.assertFalse(verified['scope']['physical_audit_performed'])
        self.assertFalse(verified['scope']['legacy_physical_checker_streamed'])

    def test_all_physical_kinds_and_opaque_data_preserved_controls_removed(self):
        events = self.events[:1]
        for i, kind in enumerate(sorted(projection.PHYSICAL_KINDS - {'initial', 'dispatch'})):
            events.append({'seq': 999, 'time': i, 'kind': kind, 'opaque': {'中文': [None, False, 1, 1.0]}, 'metrics': {'must_reset_only_terminal': 7}})
        for kind in ('action', 'plan_committed', 'time_advance', 'unrecognized'):
            events.append({'seq': -1, 'time': 19, 'kind': kind, 'opaque': 'excluded'})
        self.write_source(events);self.project()
        self.assertEqual(self.read_events(), reference_projection(events))
        self.assertTrue(self.verify()['projection_verified'])

    def test_production_and_virtual_owner_handling_matches_reference(self):
        events = deepcopy(self.events)
        virtual = deepcopy(events[4]);virtual.update(machine=99, owner='environment')
        events.insert(5, virtual)
        second = deepcopy(events[4]);second['time'] = 1;events.insert(6, second)
        events[-1]['metrics'] = {'irrelevant_reported_number': 987}
        self.write_source(renumber(events));self.project()
        actual = self.read_events()
        self.assertEqual(actual, reference_projection(events))
        self.assertEqual([e['decision'] for e in actual if e['kind'] == 'action'], [0, 1])
        self.assertEqual(next(e for e in actual if e.get('machine') == 99)['owner'], 'environment')
        self.assertEqual(actual[-1]['metrics'], {})
        self.assertEqual(self.verify()['conversion_counts']['synthetic_action_count'], 2)

    def test_decoded_records_are_deepcopied_before_transformation(self):
        original = deepcopy(self.events)
        records = [TraceRecord(i, i + 1, 0, b'', e) for i, e in enumerate(self.events)]
        converted = list(projection._project_records(iter(records), projection._counts()))
        converted[0]['manifest']['machines'][0]['family'] = 'changed copy'
        self.assertEqual(self.events, original)

    def test_nonterminal_prefix_is_only_a_projection_not_a_window_certificate(self):
        events = self.events[:5];self.write_source(events)
        self.project();self.assertEqual(self.read_events(), reference_projection(events))
        verified = self.verify()
        self.assertFalse(verified['scope']['physical_audit_performed'])
        self.assertNotIn('successful_full_window', verified)

    def test_valid_snapshot_prehistory_is_filtered_without_cold_substitution(self):
        events = deepcopy(self.events)
        events.insert(5, {'seq': 5, 'kind': 'snapshot_loaded', 'time': 0, 'prefix_event_count': 5, 'snapshot_sha256': 'a' * 64})
        renumber(events);self.write_source(events);self.project()
        self.assertEqual(self.read_events(), reference_projection(events))
        self.assertTrue(self.verify()['projection_verified'])

    def test_snapshot_root_and_missing_initial_cannot_publish(self):
        cases = [[], [{'kind': 'ready', 'time': 0, 'seq': 0}], deepcopy(self.events)]
        cases[-1].insert(5, {'seq': 5, 'kind': 'snapshot_loaded', 'time': 0, 'prefix_event_count': 4})
        for i, events in enumerate(cases):
            self.bundle = self.root / f'failed{i}';self.write_source(events)
            with self.subTest(case=i), self.assertRaises(projection.ProjectionError):
                self.project()
            self.assert_unfinished()
        self.bundle = self.root / 'nonzero-root';events = deepcopy(self.events)
        events[0]['time'] = 1
        events.insert(5, {'seq': 5, 'kind': 'snapshot_loaded', 'time': 1, 'prefix_event_count': 5})
        self.write_source(renumber(events))
        with self.assertRaises(projection.ProjectionError):self.project()
        self.assert_unfinished()

    def test_malformed_source_retains_unfinished_diagnostic_directory(self):
        self.source.write_bytes(b'{"unfinished":')
        with self.assertRaises(TraceSourceError):self.project()
        self.assert_unfinished()

    def test_existing_empty_directory_or_symlink_is_never_overwritten(self):
        self.bundle.mkdir()
        with self.assertRaises(FileExistsError):self.project()
        self.assertEqual(list(self.bundle.iterdir()), [])
        self.bundle.rmdir();self.bundle.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(FileExistsError):self.project()
        with self.assertRaises(projection.ProjectionError):self.verify()

    def test_early_projection_return_cannot_skip_verified_eof(self):
        with patch.object(projection, '_project_records', return_value=iter(())), self.assertRaises(IncompleteReadError):
            self.project()
        self.assert_unfinished()

    def test_input_changed_after_iteration_cannot_publish_completion(self):
        real = projection._project_records
        def mutate(reader, counts):
            yield from real(reader, counts)
            with self.source.open('ab') as stream:stream.write(b'\n')
        with patch.object(projection, '_project_records', mutate), self.assertRaises(SourceChangedError):
            self.project()
        self.assert_unfinished()

    def test_stale_input_seal_is_rejected(self):
        seal = inspect_jsonl(self.source)
        with self.source.open('ab') as stream:stream.write(b'\n')
        with self.assertRaises(SourceChangedError):
            projection.project_physical_trace(seal, output_dir=self.bundle)
        self.assert_unfinished()

    def test_prepublication_storage_error_has_no_completion_marker(self):
        with patch.object(projection.os, 'fsync', side_effect=OSError('disk full')), self.assertRaises(OSError):
            self.project()
        self.assert_unfinished()

    def test_published_manifest_survives_return_exception_and_is_recoverable(self):
        link = projection.os.link
        def published_then_failed(a, b):
            link(a, b);raise OSError('after marker publication')
        with patch.object(projection.os, 'link', published_then_failed), self.assertRaises(OSError):self.project()
        self.assertTrue(self.verify()['projection_verified'])
        self.assertEqual(self.read_manifest()['source_receipt']['sha256'], hashlib.sha256(self.source.read_bytes()).hexdigest())
        with self.assertRaises(FileExistsError):self.project()

    def test_private_cleanup_failure_leaves_complete_verifiable_marker(self):
        unlink = Path.unlink
        def fail_private(path, *args, **kwargs):
            if path.suffix == '.partial':raise OSError('cleanup failed')
            return unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', fail_private), self.assertRaises(OSError):self.project()
        self.assertTrue(self.verify()['projection_verified'])
        self.assertEqual(len(list(self.bundle.glob('*.partial'))), 1)

    def test_publication_path_replacement_never_changes_returned_hash(self):
        link = projection.os.link;written = []
        def replace(a, b):
            written.append(Path(a).read_bytes());link(a, b)
            replacement = self.root / 'unrelated.json';replacement.write_text('{"unrelated":true}')
            replacement.replace(b)
        with patch.object(projection.os, 'link', replace):created = self.project()
        self.assertEqual(created['manifest_sha256'], hashlib.sha256(written[0]).hexdigest())
        self.assertNotEqual(created['manifest_sha256'], hashlib.sha256((self.bundle / 'projection.json').read_bytes()).hexdigest())
        with self.assertRaises(projection.ProjectionError):self.verify(created['manifest_sha256'])

    def test_marker_creation_race_does_not_overwrite_prior_evidence(self):
        link = projection.os.link
        def racing(a, b):
            Path(b).write_text('prior evidence');link(a, b)
        with patch.object(projection.os, 'link', racing), self.assertRaises(FileExistsError):self.project()
        self.assertEqual((self.bundle / 'projection.json').read_text(), 'prior evidence')
        with self.assertRaises(projection.ProjectionError):self.verify()

    def test_manifest_or_output_symlinks_cannot_be_consumed(self):
        self.project()
        for name in ('physical.jsonl', 'projection.json'):
            path = self.bundle / name;content = path.read_bytes();outside = self.root / ('external_' + name)
            outside.write_bytes(content);path.unlink();path.symlink_to(outside)
            with self.subTest(member=name), self.assertRaises(projection.ProjectionError):self.verify()
            path.unlink();path.write_bytes(content)
        (self.bundle / '.projection.other.partial').symlink_to(self.source)
        with self.assertRaises(projection.ProjectionError):self.verify()

    def test_input_receipt_mismatch_and_false_scope_are_rejected(self):
        self.project();original = self.read_manifest()
        for change in ('source_hash', 'count', 'scope', 'member', 'version'):
            manifest = deepcopy(original)
            if change == 'source_hash':manifest['source_receipt']['sha256'] = 'b' * 64
            elif change == 'count':manifest['output_receipt']['event_count'] += 1
            elif change == 'scope':manifest['scope']['physical_audit_performed'] = True
            elif change == 'member':manifest['physical_member'] = '../source.jsonl'
            else:manifest['projection_version'] = 'other'
            self.rewrite('projection.json', manifest)
            with self.subTest(change=change), self.assertRaises(TraceSourceError):self.verify()
        self.rewrite('projection.json', original)

    def test_jointly_rewritten_output_and_receipt_cannot_forge_projection(self):
        self.project();original_events = self.read_events();original_manifest = self.read_manifest()
        for change in ('owner', 'lot', 'type', 'order', 'drop', 'extra'):
            events = deepcopy(original_events)
            dispatch = next(e for e in events if e['kind'] == 'dispatch')
            if change == 'owner':dispatch['owner'] = 'plan'
            elif change == 'lot':dispatch['lots'] = ['forged']
            elif change == 'type':dispatch['machine'] = False  # False == 0, but type differs
            elif change == 'order':events[1], events[2] = events[2], events[1]
            elif change == 'drop':events.pop()
            else:events.append(deepcopy(events[-1]))
            path = self.bundle / 'physical.jsonl';path.write_text(''.join(json.dumps(e) + '\n' for e in events))
            seal = inspect_jsonl(path)
            manifest = deepcopy(original_manifest)
            manifest['output_receipt'] = {key: getattr(seal, key) for key in projection.RECEIPT_FIELDS}
            manifest['conversion_counts']['output_event_count'] = len(events)
            self.rewrite('projection.json', manifest)
            with self.subTest(change=change), self.assertRaises(projection.ProjectionError):self.verify()

    def test_wrong_expected_manifest_hash_is_rejected(self):
        self.project()
        with self.assertRaises(SourceChangedError):self.verify('0' * 64)
        with self.assertRaises(projection.ProjectionError):self.verify('invalid')

    def test_conversion_does_not_read_whole_source_or_output_back(self):
        with (patch.object(Path, 'read_text', side_effect=AssertionError('whole text read')),
              patch.object(Path, 'read_bytes', side_effect=AssertionError('whole byte read'))):
            created = self.project()
            verified = self.verify(created['manifest_sha256'])
        self.assertTrue(verified['projection_verified'])

    def test_output_replacement_at_final_layout_is_rejected_before_return(self):
        created = self.project();real_layout = projection._layout;calls = []
        def replaced_after_readers_close(bundle):
            calls.append(bundle)
            if len(calls) == 2:
                (bundle / projection.PHYSICAL_NAME).write_text('{"seq":0,"time":0,"kind":"forged"}\n')
            return real_layout(bundle)
        with patch.object(projection, '_layout', replaced_after_readers_close), self.assertRaises(SourceChangedError):
            self.verify(created['manifest_sha256'])

    def test_verification_descriptor_is_json_point_in_time_diagnostics_only(self):
        self.project();verified = self.verify()
        self.assertEqual(json.loads(json.dumps(verified)), verified)
        self.assertEqual(verified['verification_version'], projection.VERIFICATION_VERSION)
        self.assertTrue(verified['physical_path_is_diagnostic'])
        self.assertTrue(verified['verified_consumption_required'])
        self.assertIn('point-in-time', verified['verification_scope'])
        self.assertTrue(verified['consumption_api'].endswith('.open_verified_projection'))
        self.assertEqual(self.read_manifest()['projection_version'], projection.VERSION)

    def test_verified_consumption_binds_original_seal_after_internal_return(self):
        # Both altered content and same-byte/inode replacement must fail between
        # the comparison pass and consumption; neither gets freshly inspected.
        for same_bytes in (False, True):
            self.bundle = self.root / ('same_bytes' if same_bytes else 'forged_bytes')
            created = self.project();real_verify = projection._verify_projection_bundle
            def replaced_after_verify(*args, **kwargs):
                descriptor, seal = real_verify(*args, **kwargs)
                target = self.bundle / projection.PHYSICAL_NAME
                content = target.read_bytes() if same_bytes else b'{"kind":"forged"}\n'
                replacement = self.root / 'replacement.jsonl';replacement.write_bytes(content);replacement.replace(target)
                return descriptor, seal
            with (patch.object(projection, '_verify_projection_bundle', replaced_after_verify),
                  patch.object(projection, 'inspect_jsonl', wraps=projection.inspect_jsonl) as inspect,
                  self.subTest(same_bytes=same_bytes), self.assertRaises(SourceChangedError)):
                with projection.open_verified_projection(self.bundle, source=self.source,
                        expected_manifest_sha256=created['manifest_sha256']):
                    self.fail('replaced output cannot enter consumption context')
            output_inspections = [call for call in inspect.call_args_list if Path(call.args[0]).name == projection.PHYSICAL_NAME]
            self.assertEqual(len(output_inspections), 1, 'consumption must reuse the original seal, not inspect a changed path')

    def test_consumption_receipt_exists_only_after_successful_eof_and_context_exit(self):
        created = self.project();count = 0
        with projection.open_verified_projection(self.bundle, source=self.source,
                expected_manifest_sha256=created['manifest_sha256']) as reader:
            self.assertIsNone(reader.receipt)
            for record in reader:
                self.assertEqual(record.event['seq'], count);count += 1
            self.assertIsNone(reader.receipt)
        self.assertEqual(asdict(reader.receipt), created['output_receipt'])
        self.assertEqual(count, created['output_receipt']['event_count'])

    def test_consumption_early_exit_cannot_publish_a_partial_receipt(self):
        self.project()
        with self.assertRaises(IncompleteReadError):
            with projection.open_verified_projection(self.bundle, source=self.source) as reader:
                next(reader)
        self.assertIsNone(reader.receipt)

    def test_consumer_error_is_preserved_without_a_receipt(self):
        self.project()
        with self.assertRaisesRegex(RuntimeError, 'consumer failure'):
            with projection.open_verified_projection(self.bundle, source=self.source) as reader:
                next(reader)
                raise RuntimeError('consumer failure')
        self.assertIsNone(reader.receipt)

    def test_replacement_during_consumption_fails_even_with_old_open_descriptor(self):
        self.project()
        with self.assertRaises(SourceChangedError):
            with projection.open_verified_projection(self.bundle, source=self.source) as reader:
                next(reader)
                replacement = self.root / 'midread.jsonl';replacement.write_text('{"kind":"forged"}\n')
                replacement.replace(self.bundle / projection.PHYSICAL_NAME)
                for _ in reader:pass
        self.assertIsNone(reader.receipt)

    def test_replacement_after_consumption_eof_before_context_exit_is_rejected(self):
        self.project()
        with self.assertRaises(SourceChangedError):
            with projection.open_verified_projection(self.bundle, source=self.source) as reader:
                for _ in reader:pass
                (self.bundle / projection.PHYSICAL_NAME).write_text('{"kind":"forged"}\n')
        self.assertIsNone(reader.receipt)

    def test_short_output_write_is_not_accepted(self):
        class Short:
            def write(self, raw):return len(raw) - 1
        with self.assertRaisesRegex(OSError, 'short physical'):
            projection._JsonlWriter(Short()).write({'kind': 'initial'})


if __name__ == '__main__':unittest.main()
