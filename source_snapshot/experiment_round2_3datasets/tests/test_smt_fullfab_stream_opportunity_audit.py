"""Small file-only opportunity parity tests; no simulator/model/solver work."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab.audit import audit_opportunity_coverage as legacy
from src.smt_fullfab import stream_opportunity_audit as streamed
from src.smt_fullfab.trace_source import IncompleteReadError, SourceChangedError, TraceSourceError, inspect_jsonl
from tests.test_smt_fullfab_audit import renumber, trace_fixture
from tests import test_smt_fullfab_not_before_audit as not_before_cases


def waiting_trace(*, hold=None, pending=False):
    sample = not_before_cases.waiting_trace(not_before=0, hold=hold)
    if not pending:
        sample[3]['plan']['tasks'] = []
    return sample


class StreamOpportunityAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / 'trace.jsonl'
        self.work = self.root / 'work'
        self.work.mkdir()
        self.reports = 0

    def write(self, events):
        self.path.write_text(''.join(json.dumps(event, ensure_ascii=False) + '\n\n' for event in events), encoding='utf-8')

    def report_path(self):
        self.reports += 1
        return self.root / f'report-{self.reports}.json'

    def parity(self, events, *, expected_valid=None, sealed=False):
        self.write(events)
        raw = self.path.read_bytes()
        reference = legacy(self.path)
        output = self.report_path()
        source = inspect_jsonl(self.path) if sealed else self.path
        with (patch('src.smt_fullfab.audit.audit_opportunity_coverage', side_effect=AssertionError('legacy audit')),
              patch('src.smt_fullfab.metrics.read_events', side_effect=AssertionError('full events read')),
              patch.object(Path, 'read_text', side_effect=AssertionError('read whole text')),
              patch.object(Path, 'read_bytes', side_effect=AssertionError('read whole bytes'))):
            descriptor = streamed.audit_opportunity_coverage(source, report_path=output, work_dir=self.work)
        report = json.loads(output.read_bytes())
        comparable = dict(report)
        evidence = comparable.pop('_source_evidence')
        if 'audit_version' in reference:
            self.assertEqual(comparable['audit_version'], streamed.VERSION)
            comparable['audit_version'] = reference['audit_version']
        # Exact numeric equality, key presence, arrays and error order; no tolerance.
        self.assertEqual(json.dumps(comparable, sort_keys=True), json.dumps(reference, sort_keys=True))
        self.assertEqual(evidence, {key: descriptor[key] for key in evidence})
        self.assertEqual(descriptor['valid'], report['valid'])
        self.assertEqual(descriptor['errors'], report['errors'])
        self.assertEqual(descriptor['report_sha256'], hashlib.sha256(output.read_bytes()).hexdigest())
        self.assertEqual(evidence['source_receipt']['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(evidence['source_receipt']['event_count'], len(events))
        self.assertTrue(evidence['complete_jsonl_pass'])
        for field in ('event_sequence_certified', 'snapshot_prefix_certified', 'terminal_boundary_certified',
                      'complete_physical_window_certified', 'physical_audit_performed', 'plan_source_audit_performed'):
            self.assertIs(descriptor[field], False)
        self.assertIs(descriptor['physical_event_values_require_independent_replay'], True)
        if expected_valid is not None:
            self.assertIs(report['valid'], expected_valid)
        self.assertEqual(list(self.work.iterdir()), [])
        self.assertEqual(self.path.read_bytes(), raw)
        return report, descriptor

    def test_valid_singleton_and_nonterminal_prefix_contract(self):
        report, _ = self.parity(trace_fixture(), expected_valid=True, sealed=True)
        self.assertEqual(report['family_opportunities']['G']['singleton_immediate_dispatches'], 1)
        self.parity(trace_fixture()[:4], expected_valid=True)
        self.parity(trace_fixture()[:-1], expected_valid=True)
        physical_forgery = trace_fixture()
        physical_forgery[4]['processing_seconds'] = 999
        self.parity(physical_forgery, expected_valid=True)

    def test_missing_initial_drains_and_binds_complete_source(self):
        self.parity([], expected_valid=False)
        self.parity([{'kind': 'ready', 'time': 0}, {'kind': 'terminal', 'time': 10}], expected_valid=False)

    def test_unicode_line_separator_is_an_explicit_legacy_reader_boundary(self):
        # JSON permits this character inside strings. The legacy splitlines()
        # reader treats it as a record boundary; the LF JSONL reader does not.
        # Do not claim arbitrary-byte input compatibility with that old reader.
        sample = trace_fixture()
        sample[0]['reader_boundary_note'] = 'before\u2028after'
        self.write(sample)
        with self.assertRaises(json.JSONDecodeError):
            legacy(self.path)
        output = self.report_path()
        descriptor = streamed.audit_opportunity_coverage(self.path, report_path=output, work_dir=self.work)
        self.assertTrue(descriptor['valid'])
        self.assertEqual(descriptor['source_receipt']['event_count'], len(sample))
        self.assertFalse(descriptor['complete_physical_window_certified'])

    def test_sequence_snapshot_and_terminal_validation_are_separate_contracts(self):
        sample = trace_fixture()
        sample[4]['seq'] = 99
        sample.insert(6, {'kind': 'snapshot_loaded', 'time': 2, 'prefix_event_count': -99, 'snapshot_sha256': 'invalid'})
        self.parity(sample, expected_valid=True)
        sample = trace_fixture()
        sample[-1]['time'] = 11
        self.parity(sample, expected_valid=True)

    def test_all_six_not_before_regressions_use_streamed_contract(self):
        def checked(events):
            report, _ = self.parity(events)
            return dict(report, opportunity_audit=report)
        for name in unittest.defaultTestLoader.getTestCaseNames(not_before_cases.NotBeforeAuditTests):
            with self.subTest(case=name):
                with (patch.object(not_before_cases, 'audit_trace', checked),
                      patch.object(not_before_cases, 'audit_opportunity_coverage', checked)):
                    not_before_cases.NotBeforeAuditTests(name).debug()

    def test_wait_hold_expiry_plan_expiry_and_uncovered_demand(self):
        self.parity(waiting_trace(), expected_valid=False)
        held, _ = self.parity(waiting_trace(hold=20), expected_valid=True)
        self.assertEqual(held['ready_wait_without_current_plan_lot_seconds'], 20)
        self.assertEqual(held['terminal_ready_unplanned_operation_visits'], [['x', 1, 1]])
        self.parity(waiting_trace(hold=10), expected_valid=False)
        self.parity(waiting_trace(pending=True), expected_valid=False)
        sample = waiting_trace(hold=20)
        sample[3]['plan']['valid_until'] = 10
        self.parity(sample, expected_valid=False)
        sample[3]['plan']['valid_until'] = 20
        sample[4]['to'] = 0
        self.parity(sample, expected_valid=False)

    def test_clock_coverage_overlap_and_malformed_order(self):
        self.parity(renumber([event for event in trace_fixture() if event['kind'] != 'time_advance']), expected_valid=False)
        sample = waiting_trace(hold=20)
        sample.insert(5, {'kind': 'time_advance', 'time': 1, 'to': 10})
        self.parity(renumber(sample), expected_valid=False)
        sample = trace_fixture()
        sample.insert(4, {'kind': 'ready', 'time': 0, 'lot': 'unknown', 'step': 1, 'visit': 1})
        sample.insert(5, {'kind': 'ready', 'time': 0, 'lot': 'x', 'step': 99, 'visit': 1})
        sample.insert(6, {'kind': 'downtime', 'time': 0, 'machine': 0, 'machine_ready': 0,
                          'blocked_until': 0, 'affected_jobs': ['unknown'], 'duration': 1})
        self.parity(renumber(sample), expected_valid=False)

    def test_gap_details_preserve_source_order_and_exact_expected_demand(self):
        sample = waiting_trace(hold=20)
        sample[3:3] = [
            {'kind': 'coverage_gap', 'time': 0, 'machines': [{'machine': 0, 'family': 'G', 'candidate_count': 1}]},
            {'kind': 'coverage_gap', 'time': 0, 'machines': []},
        ]
        sample.insert(-1, {'kind': 'coverage_gap', 'time': 20, 'machines': [{'machine': 0, 'family': 'G', 'candidate_count': 1}]})
        report, _ = self.parity(renumber(sample), expected_valid=False)
        self.assertEqual(report['reported_coverage_gaps_rechecked'], [
            {'time': 0, 'independent_machine_count': 1}, {'time': 0, 'independent_machine_count': 1},
            {'time': 20, 'independent_machine_count': 1}])

    def test_candidate_batch_groups_processing_setup_and_minimum_run(self):
        sample = trace_fixture()[:5]
        manifest = sample[0]['manifest']
        step2 = deepcopy(manifest['routes']['r'][0])
        step2.update(name='other recipe', setup='Q', setup_time=None)
        step2['processing']['c'] = 12
        manifest['routes']['r2'] = [step2]
        manifest['setups'] = [{'old': '', 'new': 'Q', 'seconds': 3}]
        manifest['min_runs'] = {'Q': 2}
        manifest['lots'].append(dict(manifest['lots'][0], id='y', route='r2'))
        sample[3:3] = [{'kind': 'ready', 'time': 0, 'lot': 'y', 'step': 1, 'visit': 1}]
        report, _ = self.parity(renumber(sample), expected_valid=True)
        stats = report['family_opportunities']['G']
        self.assertEqual(stats['multiple_choice_immediate_dispatches'], 1)
        self.assertEqual(stats['dispatch_checks_with_processing_variation'], 1)
        self.assertEqual(stats['dispatch_checks_with_setup_variation'], 1)
        self.assertEqual(stats['dispatch_checks_with_nonzero_setup_option'], 1)
        # Same physical family, insufficient second batch: it remains a candidate
        # membership but supplies no legal batch and no viable variation option.
        step2['batch_min'] = step2['batch_max'] = 2
        self.parity(renumber(sample), expected_valid=True)
        step2['batch_min'] = step2['batch_max'] = 1
        sample[-1].update(lots=['y'], setup_seconds=3, setup_after='Q')
        sample += [{'kind': 'time_advance', 'time': 0, 'to': 20},
                   {'kind': 'terminal', 'time': 20}]
        self.parity(renumber(sample), expected_valid=True)

    def test_historical_dedication_blocks_reassignment_and_candidates(self):
        sample = trace_fixture()[:6]
        manifest = sample[0]['manifest']
        manifest['routes']['r'][0]['dedicate_for'] = 1
        manifest['machines'].append(dict(manifest['machines'][0], id=1))
        manifest['controlled_machine_ids'] = [0, 1]
        sample[3]['plan']['scope'] = [0, 1]
        revision = deepcopy(sample[3])
        revision['time'] = 10
        revision['plan'].update(version='v2', created_at=10)
        revision['plan']['tasks'][0].update(machine=1, visits=[2], not_before=10)
        sample.extend([{'kind': 'ready', 'time': 10, 'lot': 'x', 'step': 1, 'visit': 2}, revision,
                       {'kind': 'time_advance', 'time': 10, 'to': 20}, {'kind': 'terminal', 'time': 20}])
        report, _ = self.parity(renumber(sample), expected_valid=False)
        self.assertTrue(any('historical binding' in error for error in report['errors']))

    def test_cascading_slots_machine_release_and_downtime_boundaries(self):
        sample = trace_fixture()
        sample[0]['manifest']['machines'][0]['cascading'] = True
        sample[4].update(machine_ready=5)
        sample.insert(5, {'kind': 'downtime', 'time': 0, 'machine': 0, 'machine_ready': 7,
                          'blocked_until': 6, 'affected_jobs': [0], 'duration': 2})
        sample[6]['to'] = 12
        sample[7]['time'] = sample[8]['time'] = sample[9]['time'] = 12
        self.parity(renumber(sample), expected_valid=True)
        sample[5]['affected_jobs'] = ['0']
        self.parity(renumber(sample), expected_valid=False)

    def test_obsolete_completed_and_later_visit_tasks_do_not_mask_demand(self):
        sample = waiting_trace(pending=True)
        sample.insert(4, {'kind': 'lot_complete', 'time': 0, 'lot': 'x'})
        report, _ = self.parity(renumber(sample), expected_valid=False)
        self.assertTrue(any('obsolete pending task' in error for error in report['errors']))
        sample = waiting_trace(pending=True)
        sample.insert(4, {'kind': 'ready', 'time': 0, 'lot': 'x', 'step': 1, 'visit': 2})
        self.parity(renumber(sample), expected_valid=False)

    def conditional_fixture(self, old_version=1, old_task=1, new_version='1', after_task='1'):
        sample = trace_fixture()[:5]
        manifest = sample[0]['manifest']
        manifest['lots'].append(dict(manifest['lots'][0], id='y'))
        sample[3]['plan']['version'] = old_version
        sample[3]['plan']['tasks'][0]['id'] = old_task
        sample[4].update(plan_version=old_version, plan_task_id=old_task, machine_ready=0, process_end=0)
        revision = deepcopy(sample[3])
        revision['plan'].update(version=new_version, tasks=[], holds=[
            {'machine': 0, 'until': 20, 'after_task_id': after_task}])
        sample += [{'kind': 'ready', 'time': 0, 'lot': 'y', 'step': 1, 'visit': 1}, revision,
                   {'kind': 'time_advance', 'time': 0, 'to': 20}, {'kind': 'terminal', 'time': 20}]
        return renumber(sample)

    def test_executed_version_task_keys_preserve_types_and_numeric_equality(self):
        for old_version, old_task, new_version, after, valid in (
                (1, 1, '1', '1', False), (1, 1, 1, '1', False),
                (1, '1', '1', '1', False), (1, '1', 1, '1', True),
                (1, 1, 1.0, True, True), (None, None, None, None, True)):
            with self.subTest(ids=(old_version, old_task, new_version, after)):
                self.parity(self.conditional_fixture(old_version, old_task, new_version, after), expected_valid=valid)
        self.parity(self.conditional_fixture(new_version=[]), expected_valid=False)
        self.parity(self.conditional_fixture(old_task=[]), expected_valid=False)

    def test_unhashable_operation_and_job_ids_stay_rejected(self):
        for mutate in (lambda e: e[2].update(visit=[]),
                       lambda e: e[3]['plan']['tasks'][0].update(visits=[[]]),
                       lambda e: e[4].update(job={})):
            sample = trace_fixture()
            mutate(sample)
            self.parity(sample, expected_valid=False)

    def test_historical_ready_planned_sets_and_terminal_sort_order(self):
        sample = waiting_trace(hold=20)
        manifest = sample[0]['manifest']
        for lid in ('z', 'a', 'm'):
            manifest['lots'].append(dict(manifest['lots'][0], id=lid))
            sample.insert(3, {'kind': 'ready', 'time': 0, 'lot': lid, 'step': 1, 'visit': 1})
        report, _ = self.parity(renumber(sample), expected_valid=True)
        self.assertEqual(report['production_ready_operation_visits'], 4)
        self.assertEqual(report['ready_operation_visits_never_in_any_plan'], 4)
        self.assertEqual(report['terminal_ready_unplanned_operation_visits'], [[lid, 1, 1] for lid in ('a', 'm', 'x', 'z')])
        sample = trace_fixture()
        sample.insert(6, {'kind': 'ready', 'time': 10, 'lot': 'x', 'step': 1, 'visit': '1'})
        self.parity(renumber(sample))

    def test_unplanned_wait_float_accumulation_matches_exactly(self):
        sample = waiting_trace(hold=20)
        sample[2]['time'] = 0.1
        sample[3]['time'] = 0.1
        sample[4]['time'] = 0.1
        sample.insert(2, {'kind': 'time_advance', 'time': 0, 'to': 0.1})
        # Several observation updates close/open entries in the reference's
        # Python set/dict order; no SQL SUM or reordered floating reduction.
        sample.insert(-1, {'kind': 'ready', 'time': 20, 'lot': 'x', 'step': 1, 'visit': 2})
        self.parity(renumber(sample), expected_valid=True)

    def test_sqlite_preserves_all_jobs_and_virtual_machine_history(self):
        sample = trace_fixture()[:1]
        manifest = sample[0]['manifest']
        manifest['machines'][0]['group'] = 'Delay_32'
        manifest['controlled_machine_ids'] = []
        template = trace_fixture()[4]
        for jid in range(64):
            sample.append({'kind': 'ready', 'time': 0, 'lot': 'x', 'step': 1, 'visit': jid + 1})
            sample.append(dict(deepcopy(template), job=jid, visits=[jid + 1], owner='virtual'))
        sample.append({'kind': 'downtime', 'time': 0, 'machine': 0, 'machine_ready': 0,
                       'blocked_until': 0, 'affected_jobs': [0], 'duration': 5})
        sample.append({'kind': 'terminal', 'time': 0})
        real_write = streamed._write_report
        seen = []

        def inspect_storage(path, result, db):
            seen.append((db.execute('SELECT count(*) FROM jobs').fetchone()[0],
                         db.execute('SELECT count(*) FROM machine_jobs').fetchone()[0]))
            self.assertEqual(streamed._Jobs(db)[0]['process_end'], 15)
            self.assertIsNone(result['reported_coverage_gaps_rechecked'])
            self.assertNotIsInstance(result['terminal_ready_unplanned_operation_visits'], list)
            return real_write(path, result, db)

        # Virtual Delay_32 history must stay on disk throughout replay, even
        # though its old jobs remain available to later downtime by identity.
        with (patch.object(streamed, '_write_report', inspect_storage),
              patch.object(streamed._MachineJobs, '__getitem__', side_effect=AssertionError('virtual history read'))):
            self.parity(renumber(sample), expected_valid=True)
        self.assertEqual(seen, [(64, 64)])

    def test_error_limit_keeps_reading_and_preserves_later_gap_details(self):
        sample = trace_fixture()[:1]
        for index in range(205):
            sample.append({'kind': 'ready', 'time': 0, 'lot': f'unknown-{index}', 'step': 1, 'visit': 1})
        for index in range(3):
            sample.append({'kind': 'coverage_gap', 'time': 0, 'machines': []})
        report, descriptor = self.parity(renumber(sample), expected_valid=False)
        self.assertEqual(len(report['errors']), 200)
        self.assertEqual(len(report['reported_coverage_gaps_rechecked']), 3)
        self.assertEqual(descriptor['source_receipt']['event_count'], 209)

    def test_freed_membership_does_not_delete_job_needed_by_later_downtime(self):
        sample = trace_fixture()[:8]
        sample.extend([
            {'kind': 'coverage_gap', 'time': 10, 'machines': []},
            {'kind': 'downtime', 'time': 10, 'machine': 0, 'machine_ready': 10,
             'blocked_until': 10, 'affected_jobs': [0], 'duration': 5},
            {'kind': 'time_advance', 'time': 10, 'to': 20},
            {'kind': 'terminal', 'time': 20},
        ])
        real_write = streamed._write_report

        def inspect_storage(path, result, db):
            self.assertEqual(db.execute('SELECT count(*) FROM machine_jobs').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0], 1)
            self.assertEqual(streamed._Jobs(db)[0]['process_end'], 15)
            return real_write(path, result, db)

        with patch.object(streamed, '_write_report', inspect_storage):
            self.parity(renumber(sample), expected_valid=True)

    def test_integer_and_string_job_ids_do_not_alias_in_downtime(self):
        sample = trace_fixture()[:1]
        sample[0]['manifest']['machines'][0]['group'] = 'Delay_32'
        template = trace_fixture()[4]
        for jid in (1, '1'):
            sample.extend([
                {'kind': 'ready', 'time': 0, 'lot': 'x', 'step': 1, 'visit': 1},
                dict(deepcopy(template), job=jid),
            ])
        sample.append({'kind': 'downtime', 'time': 0, 'machine': 0, 'machine_ready': 0,
                       'blocked_until': 0, 'affected_jobs': [1], 'duration': 3})
        real_write = streamed._write_report

        def inspect_storage(path, result, db):
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0], 2)
            self.assertEqual(streamed._Jobs(db)[1]['process_end'], 13)
            self.assertEqual(streamed._Jobs(db)['1']['process_end'], 10)
            self.assertEqual(streamed._MachineJobs(db)[0], {1, '1'})
            return real_write(path, result, db)

        with patch.object(streamed, '_write_report', inspect_storage):
            self.parity(renumber(sample), expected_valid=True)

    def test_malformed_partial_updates_keep_reference_error_order(self):
        changes = (
            lambda e: e[5].update(to=None),
            lambda e: e[5].update(to='bad'),
            lambda e: e[4].update(process_end='bad'),
            lambda e: e[4].update(machine_ready=[]),
            lambda e: e[3]['plan']['tasks'][0].update(not_before=[]),
            lambda e: e[2].update(time='bad'),
        )
        for index, change in enumerate(changes):
            sample = trace_fixture()
            change(sample)
            with self.subTest(change=index):
                # Source validation owns task field types: a dispatched task is
                # already gone before opportunity replay reads its not_before.
                self.parity(sample, expected_valid=(index == 4))
        sample = trace_fixture()
        sample.insert(5, {'kind': 'downtime', 'time': 0, 'machine': 0, 'machine_ready': 0,
                          'blocked_until': 0, 'affected_jobs': [0], 'duration': 'bad'})
        self.parity(renumber(sample), expected_valid=False)

    def test_reference_fatal_final_boundary_error_never_publishes_success(self):
        sample = trace_fixture()
        sample[-1].pop('time')
        self.write(sample)
        output = self.report_path()
        with self.assertRaises(KeyError):
            legacy(self.path)
        with self.assertRaises(KeyError):
            streamed.audit_opportunity_coverage(self.path, report_path=output, work_dir=self.work)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.work.iterdir()), [])

    def test_existing_report_and_publish_race_are_never_overwritten(self):
        self.write(trace_fixture())
        output = self.report_path()
        output.write_text('old evidence')
        with self.assertRaises(FileExistsError):
            streamed.audit_opportunity_coverage(self.path, report_path=output, work_dir=self.work)
        self.assertEqual(output.read_text(), 'old evidence')
        raced = self.report_path()
        real_link = streamed.os.link

        def race(source, destination):
            Path(destination).write_text('concurrent evidence')
            real_link(source, destination)

        with patch.object(streamed.os, 'link', race), self.assertRaises(FileExistsError):
            streamed.audit_opportunity_coverage(self.path, report_path=raced, work_dir=self.work)
        self.assertEqual(raced.read_text(), 'concurrent evidence')
        self.assertEqual(list(self.root.glob('.*.partial')), [])
        self.assertEqual(list(self.work.iterdir()), [])

    def test_changed_truncated_input_and_internal_early_exit_do_not_publish(self):
        self.write(trace_fixture())
        output = self.report_path()
        real_replay = streamed._replay

        def changed(reader, db):
            result = real_replay(reader, db)
            with self.path.open('ab') as stream:
                stream.write(b'\n')
            return result

        with patch.object(streamed, '_replay', changed), self.assertRaises(SourceChangedError):
            streamed.audit_opportunity_coverage(self.path, report_path=output, work_dir=self.work)
        self.assertFalse(output.exists())
        self.write(trace_fixture())
        with (patch.object(streamed, '_replay', return_value={'valid': True, 'errors': []}),
              self.assertRaises(IncompleteReadError)):
            streamed.audit_opportunity_coverage(self.path, report_path=output, work_dir=self.work)
        self.assertFalse(output.exists())
        self.path.write_bytes(b'{"partial":')
        with self.assertRaises(TraceSourceError):
            streamed.audit_opportunity_coverage(self.path, report_path=output, work_dir=self.work)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.work.iterdir()), [])

    def test_published_path_replacement_cannot_rebind_report_digest(self):
        self.write(trace_fixture())
        output = self.report_path()
        real_link = streamed.os.link
        intended = []

        def replace_after_link(source, destination):
            intended.append(Path(source).read_bytes())
            real_link(source, destination)
            replacement = self.root / 'unrelated.json'
            replacement.write_bytes(b'{"unrelated":true}\n')
            replacement.replace(destination)

        with patch.object(streamed.os, 'link', replace_after_link):
            descriptor = streamed.audit_opportunity_coverage(self.path, report_path=output, work_dir=self.work)
        self.assertEqual(descriptor['report_sha256'], hashlib.sha256(intended[0]).hexdigest())
        self.assertNotEqual(descriptor['report_sha256'], hashlib.sha256(output.read_bytes()).hexdigest())
        self.assertEqual(json.loads(intended[0])['_source_evidence']['source_receipt'], descriptor['source_receipt'])

    def test_report_reopen_is_unnecessary_and_fsync_failure_has_no_report(self):
        self.write(trace_fixture())
        output = self.report_path()
        real_open = Path.open

        def forbid_report(path, *args, **kwargs):
            if path == output:
                raise OSError('report unreadable')
            return real_open(path, *args, **kwargs)

        with patch.object(Path, 'open', forbid_report):
            descriptor = streamed.audit_opportunity_coverage(self.path, report_path=output, work_dir=self.work)
        self.assertEqual(descriptor['report_sha256'], hashlib.sha256(output.read_bytes()).hexdigest())
        output = self.report_path()
        with patch.object(streamed.os, 'fsync', side_effect=OSError('disk full')), self.assertRaises(OSError):
            streamed.audit_opportunity_coverage(self.path, report_path=output, work_dir=self.work)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.glob('.*.partial')), [])
        self.assertEqual(list(self.work.iterdir()), [])

    def test_cleanup_failure_leaves_complete_embedded_receipt(self):
        self.write(trace_fixture())
        output = self.report_path()
        real_unlink = Path.unlink

        def fail_cleanup(path, *args, **kwargs):
            if path.suffix == '.partial':
                raise OSError('cleanup failed')
            return real_unlink(path, *args, **kwargs)

        with patch.object(Path, 'unlink', fail_cleanup), self.assertRaisesRegex(OSError, 'cleanup failed'):
            streamed.audit_opportunity_coverage(self.path, report_path=output, work_dir=self.work)
        report = json.loads(output.read_bytes())
        self.assertTrue(report['valid'])
        self.assertEqual(report['_source_evidence']['source_receipt']['sha256'], hashlib.sha256(self.path.read_bytes()).hexdigest())
        for temporary in self.root.glob('.*.partial'):
            self.assertEqual(temporary.read_bytes(), output.read_bytes())
            temporary.unlink()
        self.assertEqual(list(self.work.iterdir()), [])

    def test_publication_followed_by_error_keeps_complete_evidence(self):
        self.write(trace_fixture())
        output = self.report_path()
        real_link = streamed.os.link

        def publish_then_raise(source, destination):
            real_link(source, destination)
            raise OSError('failure after publication')

        with patch.object(streamed.os, 'link', publish_then_raise), self.assertRaisesRegex(OSError, 'after publication'):
            streamed.audit_opportunity_coverage(self.path, report_path=output, work_dir=self.work)
        report = json.loads(output.read_bytes())
        self.assertTrue(report['valid'])
        self.assertEqual(report['_source_evidence']['source_receipt']['sha256'], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(list(self.root.glob('.*.partial')), [])
        self.assertEqual(list(self.work.iterdir()), [])

    def test_short_write_is_rejected(self):
        class ShortWriter:
            def write(self, data):
                return len(data) - 1

        with self.assertRaisesRegex(OSError, 'short report write'):
            streamed._HashingTextWriter(ShortWriter()).write('来源')


if __name__ == '__main__':
    unittest.main()
