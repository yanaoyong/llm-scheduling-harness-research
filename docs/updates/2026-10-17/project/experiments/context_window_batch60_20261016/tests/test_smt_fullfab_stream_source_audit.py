"""Small saved-event parity tests; no environment/model/solver execution."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab.audit import audit_plan_sources as legacy
from src.smt_fullfab import stream_source_audit as streamed
from src.smt_fullfab.trace_source import IncompleteReadError, SourceChangedError, TraceSourceError, inspect_jsonl
from tests.test_smt_fullfab_audit import renumber, trace_fixture


class StreamSourceAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / 'trace.jsonl'
        self.work = self.root / 'work'
        self.work.mkdir()
        self.reports = 0

    def write(self, events):
        self.path.write_text(''.join(json.dumps(event, ensure_ascii=False) + '\n\n'
                                     for event in events), encoding='utf-8')

    def report_path(self):
        self.reports += 1
        return self.root / f'report-{self.reports}.json'

    def parity(self, events, *, expected_valid=None, sealed=False):
        self.write(events)
        raw = self.path.read_bytes()
        reference = legacy(self.path)
        path = self.report_path()
        source = inspect_jsonl(self.path) if sealed else self.path
        # Runtime implementation may not silently call the legacy auditor/read-all.
        with (patch('src.smt_fullfab.audit.audit_plan_sources', side_effect=AssertionError('legacy audit')),
              patch('src.smt_fullfab.metrics.read_events', side_effect=AssertionError('full events read')),
              patch.object(Path, 'read_text', side_effect=AssertionError('read whole text')),
              patch.object(Path, 'read_bytes', side_effect=AssertionError('read whole bytes'))):
            descriptor = streamed.audit_plan_sources(source, report_path=path, work_dir=self.work)
        actual = json.loads(path.read_text())
        self.assertEqual(actual['audit_version'], streamed.VERSION)
        comparable = dict(actual, audit_version=reference['audit_version'])
        evidence = comparable.pop('_source_evidence')
        self.assertEqual(json.dumps(comparable, sort_keys=True), json.dumps(reference, sort_keys=True))
        self.assertEqual(evidence, {key: descriptor[key] for key in (
            'implementation_version', 'reference_contract_version', 'reference_function',
            'source_receipt', 'absence_of_unreported_legal_demand_certified',
            'physical_audit_performed', 'complete_jsonl_pass')})
        if expected_valid is not None:
            self.assertIs(actual['valid'], expected_valid)
        self.assertEqual(descriptor['valid'], actual['valid'])
        self.assertEqual(descriptor['errors'], actual['errors'])
        self.assertEqual(descriptor['report_sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(descriptor['source_receipt']['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(descriptor['source_receipt']['event_count'], len(events))
        self.assertTrue(descriptor['complete_jsonl_pass'])
        self.assertFalse(descriptor['physical_audit_performed'])
        self.assertFalse(descriptor['absence_of_unreported_legal_demand_certified'])
        self.assertEqual(list(self.work.iterdir()), [])
        self.assertEqual(self.path.read_bytes(), raw)
        return actual, descriptor

    def test_valid_plan_source_and_nonterminal_prefix(self):
        self.parity(trace_fixture(), expected_valid=True, sealed=True)
        result, _ = self.parity(trace_fixture()[:4], expected_valid=True)
        self.assertFalse(result['actual_dispatch_provenance_complete'])
        # Source provenance alone does not reject a physical processing forgery.
        sample = trace_fixture()
        sample[4]['processing_seconds'] = 999
        self.parity(sample, expected_valid=True)

    def test_missing_initial_still_reads_all_source_bytes(self):
        self.parity([], expected_valid=False)
        self.parity([{'seq': 0, 'time': 0, 'kind': 'ready'},
                     {'seq': 1, 'time': 20, 'kind': 'terminal'}], expected_valid=False)

    def test_scope_plan_times_and_reason_negative_parity(self):
        changes = [
            lambda e: e[0]['manifest'].update(controlled_machine_ids=[]),
            lambda e: e[3]['plan'].update(scope=[]),
            lambda e: e[3]['plan'].update(scope=[0, 0]),
            lambda e: e[3]['plan'].update(created_at=1),
            lambda e: e[3]['plan'].update(freeze_until=30),
            lambda e: e[3]['plan'].update(valid_until=0),
            lambda e: e[3]['plan'].update(reason='  '),
            lambda e: e[3]['plan'].pop('reason'),
            lambda e: e[3]['plan'].update(created_at=None),
        ]
        for number, change in enumerate(changes):
            sample = trace_fixture()
            change(sample)
            with self.subTest(number=number):
                self.parity(sample, expected_valid=False)

    def test_tasks_qualification_batch_identity_and_start_parity(self):
        changes = [
            lambda e: e[3]['plan']['tasks'].append(deepcopy(e[3]['plan']['tasks'][0])),
            lambda e: e[3]['plan']['tasks'][0].update(machine=9),
            lambda e: e[3]['plan']['tasks'][0].update(lot_ids=[]),
            lambda e: e[3]['plan']['tasks'][0].update(lot_ids=['unknown']),
            lambda e: e[3]['plan']['tasks'][0].update(lot_ids=['x', 'x']),
            lambda e: e[3]['plan']['tasks'][0].update(steps=[]),
            lambda e: e[3]['plan']['tasks'][0].update(steps=[True]),
            lambda e: e[3]['plan']['tasks'][0].update(steps=[2]),
            lambda e: e[3]['plan']['tasks'][0].update(visits=[0]),
            lambda e: e[0]['manifest']['routes']['r'][0].update(family='other'),
            lambda e: e[0]['manifest']['routes']['r'][0].update(batch_min=2),
            lambda e: e[3]['plan']['tasks'][0].update(not_before=1),
            lambda e: e[3]['plan']['tasks'][0].update(not_before=30),
            lambda e: e[3]['plan']['tasks'][0].update(latest_start=-1),
            lambda e: e[3]['plan']['tasks'][0].update(expected_start=-1),
        ]
        for number, change in enumerate(changes):
            sample = trace_fixture()
            change(sample)
            with self.subTest(number=number):
                self.parity(sample, expected_valid=False)

    def test_incompatible_batch_and_duplicate_operation(self):
        sample = trace_fixture()
        manifest = sample[0]['manifest']
        manifest['lots'].append(dict(manifest['lots'][0], id='y', part='different'))
        manifest['routes']['r'][0]['batch_max'] = 2
        sample[3]['plan']['tasks'][0].update(lot_ids=['x', 'y'], steps=[1, 1], visits=[1, 1])
        self.parity(sample, expected_valid=False)
        sample = trace_fixture()
        sample[3]['plan']['tasks'].append(dict(sample[3]['plan']['tasks'][0], id='other'))
        self.parity(sample, expected_valid=False)

    def test_dispatch_owner_source_order_exact_steps_visits_and_time(self):
        changes = [
            lambda e: e[4].update(owner='environment'),
            lambda e: e[4].update(plan_version='missing'),
            lambda e: e[4].update(plan_task_id='missing'),
            lambda e: e[4].update(lots=['y']),
            lambda e: e[4].update(steps=[2]),
            lambda e: e[4].update(visits=[2]),
            lambda e: e[4].update(machine=99),
            lambda e: e[4].update(time=21),
            lambda e: e.insert(5, deepcopy(e[4])),
        ]
        for number, change in enumerate(changes):
            sample = trace_fixture()
            change(sample)
            with self.subTest(number=number):
                self.parity(renumber(sample), expected_valid=False)
        sample = trace_fixture()
        sample[3]['plan']['tasks'][0]['latest_start'] = 0
        sample[4]['time'] = 1
        self.parity(sample, expected_valid=False)

    def test_frozen_exact_carry_drop_change_and_reorder(self):
        sample = trace_fixture()[:4]
        sample[3]['plan']['freeze_until'] = 5
        revision = deepcopy(sample[3])
        revision['time'] = 2
        revision['plan'].update(version='v2', created_at=2, freeze_until=5)
        sample.append(revision)
        self.parity(renumber(sample), expected_valid=True)
        for change in ('drop', 'change', 'not_frozen'):
            bad = deepcopy(sample)
            if change == 'drop':
                bad[-1]['plan']['tasks'] = []
            elif change == 'change':
                bad[-1]['plan']['tasks'][0]['not_before'] = 2
            else:
                bad[3]['plan']['freeze_until'] = 1
            with self.subTest(change=change):
                self.parity(bad, expected_valid=False)
        sample = trace_fixture()[:4]
        sample[0]['manifest']['lots'].append(dict(sample[0]['manifest']['lots'][0], id='y'))
        sample[3]['plan']['tasks'].append(dict(sample[3]['plan']['tasks'][0], id='t2', lot_ids=['y']))
        sample[3]['plan']['freeze_until'] = 5
        revision = deepcopy(sample[3])
        revision['plan']['version'] = 'v2'
        revision['plan']['tasks'].reverse()
        self.parity(renumber(sample + [revision]), expected_valid=False)

    def test_explicit_and_conditional_holds_and_invalid_hold_fields(self):
        sample = trace_fixture()
        conditional = {'machine': 0, 'until': 20, 'reason': 'after dispatch', 'after_task_id': 't1'}
        sample[3]['plan']['holds'] = [conditional]
        self.parity(sample, expected_valid=True)
        changes = [lambda h: h.pop('after_task_id'), lambda h: h.update(machine=99),
                   lambda h: h.update(until=0), lambda h: h.update(until=21),
                   lambda h: h.update(reason=''), lambda h: h.update(after_task_id='missing')]
        for number, change in enumerate(changes):
            bad = deepcopy(sample)
            change(bad[3]['plan']['holds'][0])
            with self.subTest(number=number):
                self.parity(bad, expected_valid=False)
        duplicate = deepcopy(sample)
        duplicate[3]['plan']['holds'].append(deepcopy(conditional))
        self.parity(duplicate, expected_valid=False)
        after = deepcopy(sample)
        after.insert(5, deepcopy(after[4]))
        result, _ = self.parity(renumber(after), expected_valid=False)
        self.assertTrue(any('dispatch during explicit hold' in e for e in result['errors']))

    def test_integer_and_string_versions_and_tasks_remain_distinct(self):
        sample = trace_fixture()[:5]
        sample[3]['plan']['version'] = 1
        sample[3]['plan']['tasks'][0]['id'] = 1
        sample[4].update(plan_version=1, plan_task_id=1)
        revision = deepcopy(sample[3])
        revision['plan']['version'] = '1'
        revision['plan']['tasks'][0]['id'] = '1'
        dispatch = deepcopy(sample[4])
        dispatch.update(plan_version='1', plan_task_id='1')
        result, _ = self.parity(renumber(sample + [revision, dispatch]), expected_valid=True)
        self.assertEqual(result['plans_committed'], 2)
        sample = trace_fixture()[:4]
        sample[0]['manifest']['lots'].append(dict(sample[0]['manifest']['lots'][0], id='y'))
        sample[3]['plan']['tasks'][0]['id'] = 1
        sample[3]['plan']['tasks'].append(dict(sample[3]['plan']['tasks'][0], id='1', lot_ids=['y']))
        first, second = deepcopy(trace_fixture()[4]), deepcopy(trace_fixture()[4])
        first['plan_task_id'] = 1
        second.update(plan_task_id='1', lots=['y'])
        self.parity(renumber(sample + [first, second]), expected_valid=True)
        # Force a disk reload of v1. It remains invalid because it is superseded,
        # but each exact task identity must still resolve to its own lot list.
        revision = deepcopy(sample[3])
        revision['plan'].update(version='v2', tasks=[])
        result, _ = self.parity(renumber(sample + [revision, first, second]), expected_valid=False)
        self.assertFalse(any('missing source task' in e or 'differs from plan' in e for e in result['errors']))

    def test_invalid_identity_keys_do_not_become_accepted_by_sqlite(self):
        for key in (True, False, None, 1.0, 1.5, float('nan'), [], {}):
            for field in ('version', 'task'):
                sample = trace_fixture()
                if field == 'version':
                    sample[3]['plan']['version'] = key
                    sample[4]['plan_version'] = key
                else:
                    sample[3]['plan']['tasks'][0]['id'] = key
                    sample[4]['plan_task_id'] = key
                with self.subTest(key=key, field=field):
                    self.parity(sample, expected_valid=False)
        # Invalid numeric versions alias the same Python-dict identity as 1.
        sample = trace_fixture()[:4]
        sample[3]['plan'].update(version=True, tasks=[])
        revision = deepcopy(sample[3])
        revision['plan']['version'] = 1
        result, _ = self.parity(renumber(sample + [revision]), expected_valid=False)
        self.assertEqual(result['plans_committed'], 1)
        self.assertTrue(any('duplicate plan version' in e for e in result['errors']))

    def test_duplicate_versions_keep_reference_overwrite_and_hold_count(self):
        sample = trace_fixture()[:4]
        sample[3]['plan'].update(tasks=[], holds=[{'machine': 0, 'until': 20, 'reason': 'wait'}])
        revision = deepcopy(sample[3])
        revision['plan']['holds'] = []
        result, _ = self.parity(renumber(sample + [revision]), expected_valid=False)
        self.assertEqual(result['plans_committed'], 1)
        self.assertEqual(result['explicit_hold_count'], 0)

    def test_virtual_dispatch_counts_and_owner(self):
        sample = trace_fixture()
        sample[0]['manifest']['machines'].append(dict(sample[0]['manifest']['machines'][0], id=9, group='Delay_32'))
        virtual = deepcopy(sample[4])
        virtual.update(machine=9, owner='environment')
        sample.insert(5, virtual)
        result, _ = self.parity(renumber(sample), expected_valid=True)
        self.assertEqual(result['virtual_process_dispatches'], 1)
        virtual['owner'] = 'plan'
        self.parity(renumber(sample), expected_valid=False)

    def test_gap_order_json_types_and_opportunity_counts_are_lossless(self):
        sample = trace_fixture()
        extra = [
            {'kind': 'coverage_gap', 'time': 0, 'machines': [], 'tag': [None, False, 1, '1', 1.0]},
            {'kind': 'decision_opportunity', 'time': 0, 'opaque': '保存'},
            {'kind': 'coverage_gap', 'time': 0, 'machines': [{'machine': 0, 'candidate_count': 1}],
             'tag': {'unknown': ['保留', None]}},
        ]
        sample[4:4] = extra
        result, descriptor = self.parity(renumber(sample), expected_valid=True)
        self.assertEqual(result['coverage_gap_details'], [sample[4], sample[6]])
        self.assertEqual(result['decision_opportunity_events'], 1)
        self.assertNotIn('coverage_gap_details', descriptor)

    def test_error_limit_does_not_stop_reading_or_drop_later_details(self):
        sample = trace_fixture()[:1]
        sample.extend({'kind': 'unsupported', 'time': 0} for _ in range(240))
        sample.extend(deepcopy(trace_fixture()[3:5]))
        sample.extend({'kind': 'coverage_gap', 'time': 0, 'order': i} for i in range(5))
        result, descriptor = self.parity(renumber(sample), expected_valid=False)
        self.assertEqual(len(result['errors']), 200)
        self.assertEqual([gap['order'] for gap in result['coverage_gap_details']], list(range(5)))
        self.assertEqual(result['production_dispatches'], 1)
        self.assertEqual(result['plans_committed'], 1)
        self.assertEqual(descriptor['source_receipt']['event_count'], len(sample))

    def test_snapshot_prefix_sequence_and_time_rejections_match(self):
        sample = trace_fixture()
        sample.insert(6, {'kind': 'snapshot_loaded', 'time': 2,
                          'prefix_event_count': 6, 'snapshot_sha256': 'a' * 64})
        self.parity(renumber(sample), expected_valid=True)
        for change in ('prefix', 'sha', 'seq', 'time', 'nan'):
            bad = deepcopy(sample)
            if change == 'prefix': bad[6]['prefix_event_count'] = 99
            elif change == 'sha': bad[6]['snapshot_sha256'] = 'bad'
            elif change == 'seq': bad[6]['seq'] = -1
            elif change == 'time': bad[6]['time'] = -1
            else: bad[6]['time'] = float('nan')
            with self.subTest(change=change):
                self.parity(bad, expected_valid=False)

    def test_sqlite_contains_history_and_report_streams_all_details(self):
        sample = trace_fixture()[:1]
        template = trace_fixture()[3]
        for number in range(64):
            plan = deepcopy(template)
            plan['plan'].update(version=str(number), tasks=[])
            sample.extend([plan, {'kind': 'coverage_gap', 'time': 0, 'ordinal': number}])
        real_write = streamed._write_report
        seen = []
        def inspect_storage(path, result, db):
            seen.append((db.execute('SELECT count(*) FROM plans').fetchone()[0],
                         db.execute('SELECT count(*) FROM gaps').fetchone()[0]))
            self.assertIsNone(result['coverage_gap_details'])
            self.assertTrue(any(self.work.iterdir()))
            return real_write(path, result, db)
        with patch.object(streamed, '_write_report', inspect_storage):
            result, _ = self.parity(renumber(sample), expected_valid=True)
        self.assertEqual(seen, [(64, 64)])
        self.assertEqual(len(result['coverage_gap_details']), 64)

    def test_existing_report_is_never_overwritten_including_publish_race(self):
        self.write(trace_fixture())
        output = self.report_path()
        output.write_text('prior evidence')
        with self.assertRaises(FileExistsError):
            streamed.audit_plan_sources(self.path, report_path=output, work_dir=self.work)
        self.assertEqual(output.read_text(), 'prior evidence')
        race_output = self.report_path()
        actual_link = streamed.os.link
        def raced(source, destination):
            Path(destination).write_text('concurrent evidence')
            actual_link(source, destination)
        with patch.object(streamed.os, 'link', raced), self.assertRaises(FileExistsError):
            streamed.audit_plan_sources(self.path, report_path=race_output, work_dir=self.work)
        self.assertEqual(race_output.read_text(), 'concurrent evidence')
        self.assertEqual(list(self.root.glob('.*.partial')), [])
        self.assertEqual(list(self.work.iterdir()), [])

    def test_changed_input_or_failed_publish_has_no_success_report(self):
        self.write(trace_fixture())
        output = self.report_path()
        original = streamed._replay
        def changed(reader, db):
            result = original(reader, db)
            with self.path.open('ab') as stream:
                stream.write(b'\n')
            return result
        with patch.object(streamed, '_replay', changed), self.assertRaises(SourceChangedError):
            streamed.audit_plan_sources(self.path, report_path=output, work_dir=self.work)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.work.iterdir()), [])
        self.write(trace_fixture())
        with patch.object(streamed.os, 'fsync', side_effect=OSError('disk full')), self.assertRaises(OSError):
            streamed.audit_plan_sources(self.path, report_path=output, work_dir=self.work)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.glob('.*.partial')), [])
        self.assertEqual(list(self.work.iterdir()), [])
        self.path.write_bytes(b'{"unfinished":')
        with self.assertRaises(TraceSourceError):
            streamed.audit_plan_sources(self.path, report_path=output, work_dir=self.work)
        self.assertFalse(output.exists())

    def test_published_path_replacement_cannot_rebind_report_hash(self):
        self.write(trace_fixture())
        output = self.report_path()
        actual_link = streamed.os.link
        published = []

        def replace_after_publish(source, destination):
            # Capture the bytes about to be published, then replace only the
            # destination path in the same interval that used to precede reread.
            published.append(Path(source).read_bytes())
            actual_link(source, destination)
            replacement = self.root / 'unrelated.json'
            replacement.write_bytes(b'{"unrelated":true}\n')
            replacement.replace(destination)

        with patch.object(streamed.os, 'link', replace_after_publish):
            descriptor = streamed.audit_plan_sources(self.path, report_path=output, work_dir=self.work)
        self.assertTrue(descriptor['valid'])
        self.assertEqual(descriptor['report_sha256'], hashlib.sha256(published[0]).hexdigest())
        self.assertNotEqual(descriptor['report_sha256'], hashlib.sha256(output.read_bytes()).hexdigest())
        intended = json.loads(published[0])
        self.assertEqual(intended['_source_evidence']['source_receipt'], descriptor['source_receipt'])
        self.assertEqual(json.loads(output.read_bytes()), {'unrelated': True})
        self.assertEqual(list(self.root.glob('.*.partial')), [])
        self.assertEqual(list(self.work.iterdir()), [])

    def test_report_is_not_reopened_after_publication(self):
        self.write(trace_fixture())
        output = self.report_path()
        actual_open = Path.open

        def forbid_report_reopen(path, *args, **kwargs):
            if path == output:
                raise OSError('published path unreadable')
            return actual_open(path, *args, **kwargs)

        with patch.object(Path, 'open', forbid_report_reopen):
            descriptor = streamed.audit_plan_sources(self.path, report_path=output, work_dir=self.work)
        report = json.loads(output.read_bytes())
        self.assertTrue(report['valid'])
        self.assertEqual(report['_source_evidence']['source_receipt'], descriptor['source_receipt'])
        self.assertEqual(descriptor['report_sha256'], hashlib.sha256(output.read_bytes()).hexdigest())

    def test_publication_then_error_leaves_complete_self_contained_report(self):
        self.write(trace_fixture())
        output = self.report_path()
        actual_link = streamed.os.link

        def publish_then_raise(source, destination):
            actual_link(source, destination)
            raise OSError('failure after atomic publication')

        with patch.object(streamed.os, 'link', publish_then_raise), self.assertRaisesRegex(OSError, 'after atomic'):
            streamed.audit_plan_sources(self.path, report_path=output, work_dir=self.work)
        report = json.loads(output.read_bytes())
        self.assertTrue(report['valid'])
        self.assertEqual(report['_source_evidence']['source_receipt']['sha256'],
                         hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertTrue(report['_source_evidence']['complete_jsonl_pass'])
        self.assertEqual(list(self.root.glob('.*.partial')), [])
        self.assertEqual(list(self.work.iterdir()), [])
        with self.assertRaises(FileExistsError):
            streamed.audit_plan_sources(self.path, report_path=output, work_dir=self.work)

    def test_post_publish_cleanup_error_preserves_source_receipt(self):
        self.write(trace_fixture())
        output = self.report_path()
        actual_unlink = Path.unlink

        def fail_report_cleanup(path, *args, **kwargs):
            if path.suffix == '.partial':
                self.assertTrue(output.exists())
                raise OSError('temporary link cleanup failed')
            return actual_unlink(path, *args, **kwargs)

        with patch.object(Path, 'unlink', fail_report_cleanup), self.assertRaisesRegex(OSError, 'cleanup failed'):
            streamed.audit_plan_sources(self.path, report_path=output, work_dir=self.work)
        report = json.loads(output.read_bytes())
        self.assertTrue(report['valid'])
        evidence = report['_source_evidence']
        self.assertEqual(evidence['implementation_version'], streamed.VERSION)
        self.assertEqual(evidence['source_receipt']['sha256'], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(evidence['source_receipt']['event_count'], len(trace_fixture()))
        self.assertTrue(evidence['complete_jsonl_pass'])
        self.assertFalse(evidence['physical_audit_performed'])
        self.assertEqual(list(self.work.iterdir()), [])
        partials = list(self.root.glob('.*.partial'))
        self.assertEqual(len(partials), 1)
        self.assertEqual(partials[0].read_bytes(), output.read_bytes())
        partials[0].unlink()
        with self.assertRaises(FileExistsError):
            streamed.audit_plan_sources(self.path, report_path=output, work_dir=self.work)

    def test_hashing_writer_rejects_short_write_before_publication(self):
        class ShortWriter:
            def write(self, data):
                return len(data) - 1

        with self.assertRaisesRegex(OSError, 'short report write'):
            streamed._HashingTextWriter(ShortWriter()).write('来源')

    def test_internal_early_exit_cannot_publish_partial_success(self):
        self.write(trace_fixture())
        output = self.report_path()
        with (patch.object(streamed, '_replay', return_value={'valid': True, 'errors': []}),
              self.assertRaises(IncompleteReadError)):
            streamed.audit_plan_sources(self.path, report_path=output, work_dir=self.work)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.work.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
