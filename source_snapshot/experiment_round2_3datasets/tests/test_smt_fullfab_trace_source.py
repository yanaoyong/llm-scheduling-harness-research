"""Tiny archived JSONL fixtures only; no simulation, model or solver imports."""
from dataclasses import replace
import gc
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import weakref

from src.smt_fullfab.trace_source import (
    IncompleteReadError, SourceChangedError, TraceSourceError,
    inspect_jsonl, open_verified, scan_envelope,
)


def events():
    return [
        {'seq': 0, 'kind': 'initial', 'time': 0, 'manifest': {'horizon': 20}},
        {'seq': 1, 'kind': 'plan_committed', 'time': 0,
         'plan': {'version': '中文', 'tasks': [{'id': 't', 'not_before': 10}],
                  'unknown': [None, False, 1, 1.0, {'preserve': '顺序'}]}},
        {'seq': 2, 'kind': 'snapshot_loaded', 'time': 10,
         'prefix_event_count': 2, 'snapshot_sha256': 'a' * 64},
        {'seq': 3, 'kind': 'terminal', 'time': 20},
    ]


class TraceSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'trace.jsonl'

    def write(self, values=None, *, blanks=False, final_newline=True):
        values = events() if values is None else values
        lines = [json.dumps(value, ensure_ascii=False).encode('utf-8') for value in values]
        raw = (b'\n \t\n' if blanks else b'\n').join(lines)
        if final_newline:
            raw += b'\n'
        self.path.write_bytes(raw)
        return raw

    def test_seal_and_repeated_passes_preserve_raw_bytes_and_objects(self):
        raw = self.write(blanks=True)
        expected_hash = hashlib.sha256(raw).hexdigest()
        seal = inspect_jsonl(self.path, expected_sha256=expected_hash)
        self.assertEqual(seal.sha256, expected_hash)
        self.assertEqual(seal.byte_count, len(raw))
        self.assertEqual(seal.line_count, 7)
        self.assertEqual(seal.event_count, 4)
        for _ in range(2):
            with open_verified(seal) as reader:
                rows = list(reader)  # Small test oracle only; production API is an iterator.
                self.assertIsNone(reader.receipt)
            self.assertEqual(reader.receipt.sha256, expected_hash)
            self.assertEqual([row.event for row in rows], events())
            self.assertEqual([row.event_index for row in rows], [0, 1, 2, 3])
            self.assertEqual([row.line_number for row in rows], [1, 3, 5, 7])
            for row in rows:
                self.assertEqual(raw[row.byte_offset:row.byte_offset + len(row.raw_line)], row.raw_line)
            self.assertEqual(seal.max_record_bytes, max(len(row.raw_line) for row in rows))
            rows[1].event['plan']['tasks'].clear()
        self.assertEqual(self.path.read_bytes(), raw)

    def test_envelope_is_explicitly_not_a_semantic_certificate(self):
        self.write()
        result = scan_envelope(inspect_jsonl(self.path))
        self.assertTrue(result.terminal_at_eof)
        self.assertEqual((result.first_time, result.last_time, result.horizon), (0, 20, 20))
        self.assertEqual(result.snapshot_count, 1)
        self.assertEqual(result.receipt.event_count, 4)
        self.assertFalse(result.physical_audit_performed)
        self.assertFalse(result.plan_source_audit_performed)
        self.assertFalse(result.opportunity_audit_performed)
        self.assertFalse(hasattr(result, 'valid'))

    def test_complete_final_json_without_newline_and_partial_mode(self):
        self.write(final_newline=False)
        self.assertTrue(scan_envelope(inspect_jsonl(self.path)).terminal_at_eof)
        self.write(events()[:-1], final_newline=False)
        seal = inspect_jsonl(self.path)
        self.assertFalse(scan_envelope(seal, require_terminal=False).terminal_at_eof)
        with self.assertRaisesRegex(TraceSourceError, 'missing terminal'):
            scan_envelope(seal)
        with self.assertRaises(TypeError):
            scan_envelope(seal, require_terminal=0)

    def test_early_break_or_exact_record_count_without_eof_has_no_receipt(self):
        self.write()
        seal = inspect_jsonl(self.path)
        for read_count in (0, 1, seal.event_count):
            reader = open_verified(seal)
            with self.subTest(read_count=read_count):
                with self.assertRaises(IncompleteReadError):
                    with reader:
                        for _ in range(read_count):
                            next(reader)
                        self.assertIsNone(reader.receipt)
                self.assertIsNone(reader.receipt)
        reader = open_verified(seal)
        with self.assertRaises(IncompleteReadError):
            with reader:
                for _ in reader:
                    break
        self.assertIsNone(reader.receipt)

    def test_consumer_exception_is_not_masked_and_clears_receipt(self):
        self.write()
        for after_eof in (False, True):
            reader = open_verified(inspect_jsonl(self.path))
            with self.assertRaisesRegex(RuntimeError, 'consumer failed'):
                with reader:
                    if after_eof:
                        for _ in reader:
                            pass
                    else:
                        next(reader)
                    raise RuntimeError('consumer failed')
            self.assertIsNone(reader.receipt)

    def test_file_changed_between_passes_is_rejected(self):
        for change in ('append', 'truncate', 'same_length'):
            original = self.write()
            seal = inspect_jsonl(self.path)
            if change == 'append':
                self.path.write_bytes(original + b'\n')
            elif change == 'truncate':
                self.path.write_bytes(original[:-3])
            else:
                self.path.write_bytes(original.replace(b'20', b'21'))
            reader = open_verified(seal)
            with self.subTest(change=change), self.assertRaises(SourceChangedError):
                with reader:
                    for _ in reader:
                        pass
            self.assertIsNone(reader.receipt)

    def test_failed_context_close_does_not_publish_receipt(self):
        self.write()
        reader = open_verified(inspect_jsonl(self.path))
        with self.assertRaisesRegex(OSError, 'close failed'):
            with reader:
                for _ in reader:
                    pass
                original_close = reader._stream.close
                def failed_close():
                    original_close()
                    raise OSError('close failed')
                reader._stream.close = failed_close
        self.assertIsNone(reader.receipt)

    def test_file_changed_during_pass_or_after_eof_has_no_receipt(self):
        for after_eof in (False, True):
            for change in ('append', 'truncate', 'same_length'):
                raw = self.write()
                reader = open_verified(inspect_jsonl(self.path))
                with (self.subTest(after_eof=after_eof, change=change),
                      self.assertRaises(SourceChangedError)):
                    with reader:
                        if after_eof:
                            for _ in reader:
                                pass
                        else:
                            next(reader)
                        changed = {'append': raw + b'\n', 'truncate': raw[:-3],
                                   'same_length': raw.replace(b'20', b'21')}[change]
                        self.path.write_bytes(changed)
                        if not after_eof:
                            for _ in reader:
                                pass
                self.assertIsNone(reader.receipt)

    def test_replacing_path_during_pass_is_rejected(self):
        raw = self.write()
        reader = open_verified(inspect_jsonl(self.path))
        with self.assertRaises(SourceChangedError):
            with reader:
                next(reader)
                replacement = self.path.with_name('replacement.jsonl')
                replacement.write_bytes(raw)
                replacement.replace(self.path)
                for _ in reader:
                    pass
        self.assertIsNone(reader.receipt)

    def test_content_hash_and_record_counts_verified_at_eof(self):
        self.write()
        seal = inspect_jsonl(self.path)
        wrong_seals = [replace(seal, sha256='0' * 64),
                       replace(seal, event_count=seal.event_count + 1),
                       replace(seal, byte_count=seal.byte_count + 1),
                       replace(seal, line_count=seal.line_count + 1),
                       replace(seal, max_record_bytes=seal.max_record_bytes + 1)]
        for wrong in wrong_seals:
            reader = open_verified(wrong)
            with self.assertRaises(SourceChangedError):
                with reader:
                    for _ in reader:
                        pass
            self.assertIsNone(reader.receipt)
        with self.assertRaises(SourceChangedError):
            inspect_jsonl(self.path, expected_sha256='0' * 64)
        with self.assertRaises(TraceSourceError):
            inspect_jsonl(self.path, expected_sha256='bad')

    def test_invalid_json_utf8_and_non_object_records_are_rejected(self):
        for raw in (b'{"kind":', b'\xff\n', b'[]\n', b'null\n', b'1\n'):
            self.path.write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(TraceSourceError):
                inspect_jsonl(self.path)
        self.path.write_bytes(b'\n \t\n')
        seal = inspect_jsonl(self.path)
        self.assertEqual(seal.event_count, 0)
        with self.assertRaisesRegex(TraceSourceError, 'missing initial'):
            scan_envelope(seal)

    def test_invalid_sequences_initial_and_time_are_rejected(self):
        bad = []
        for seq in (True, 1.0, -1, 0, 2, None):
            sample = events()
            sample[1]['seq'] = seq
            bad.append(sample)
        for time in (True, float('nan'), float('inf'), -1, 21, 10**400):
            sample = events()
            sample[1]['time'] = time
            bad.append(sample)
        sample = events()
        sample[1]['time'] = 11
        bad.append(sample)
        sample = events()
        sample[1]['kind'] = 'initial'
        bad.append(sample)
        sample = events()
        sample[0]['kind'] = 'ready'
        bad.append(sample)
        for index, sample in enumerate(bad):
            self.write(sample)
            with self.subTest(index=index), self.assertRaises(TraceSourceError):
                scan_envelope(inspect_jsonl(self.path))

    def test_terminal_must_be_last_and_reach_horizon(self):
        bad = []
        for kind in ('terminal', 'time_advance', 'plan_committed'):
            sample = events() + [{'seq': 4, 'kind': kind, 'time': 20}]
            bad.append(sample)
        for t in (19, 21):
            sample = events()
            sample[-1]['time'] = t
            bad.append(sample)
        for sample in bad:
            self.write(sample)
            for required in (False, True):
                with self.assertRaises(TraceSourceError):
                    scan_envelope(inspect_jsonl(self.path), require_terminal=required)

    def test_snapshot_prefix_count_and_hash_syntax(self):
        bad = []
        for count in (True, 0, 1, 2.0, None):
            sample = events()
            sample[2]['prefix_event_count'] = count
            bad.append(sample)
        sample = events()
        sample[0]['time'] = sample[1]['time'] = 1
        bad.append(sample)
        sample = events()
        sample[2]['snapshot_sha256'] = 'not-a-hash'
        bad.append(sample)
        for sample in bad:
            self.write(sample)
            with self.assertRaises(TraceSourceError):
                scan_envelope(inspect_jsonl(self.path))

    def test_no_whole_file_helpers_no_input_mutation_and_no_record_history(self):
        # 2,050 small records, under 200 KiB; this is not a historical trace benchmark.
        sample = [events()[0]]
        sample.extend({'seq': i, 'kind': 'plan_committed', 'time': 0,
                       'plan': {'tasks': [i], 'unknown': None}} for i in range(1, 2049))
        sample.append({'seq': 2049, 'kind': 'terminal', 'time': 20})
        raw = self.write(sample)
        self.assertLess(len(raw), 256 * 1024)
        with (patch.object(Path, 'read_text', side_effect=AssertionError('whole-file text')),
              patch.object(Path, 'read_bytes', side_effect=AssertionError('whole-file bytes'))):
            seal = inspect_jsonl(self.path)
            references = []
            with open_verified(seal) as reader:
                for row in reader:
                    references.append(weakref.ref(row))
                    if row.event_index % 256 == 0:
                        gc.collect()
                        self.assertLessEqual(sum(ref() is not None for ref in references), 1)
            self.assertEqual(reader.receipt.event_count, 2050)
            self.assertTrue(scan_envelope(seal).terminal_at_eof)
        self.assertEqual(self.path.read_bytes(), raw)

    def test_pass_lifecycle_and_sticky_failure(self):
        self.write()
        seal = inspect_jsonl(self.path)
        reader = open_verified(seal)
        with self.assertRaises(TraceSourceError):
            next(reader)
        with reader:
            for _ in reader:
                pass
        with self.assertRaises(TraceSourceError):
            next(reader)
        with self.assertRaises(TraceSourceError):
            with reader:
                pass
        failed = open_verified(replace(seal, sha256='0' * 64))
        with self.assertRaisesRegex(TraceSourceError, 'failed pass'):
            with failed:
                with self.assertRaises(SourceChangedError):
                    for _ in failed:
                        pass
                with self.assertRaisesRegex(TraceSourceError, 'failed pass'):
                    next(failed)
        self.assertIsNone(failed.receipt)
        with self.assertRaises(TypeError):
            open_verified(self.path)


if __name__ == '__main__':
    unittest.main()
