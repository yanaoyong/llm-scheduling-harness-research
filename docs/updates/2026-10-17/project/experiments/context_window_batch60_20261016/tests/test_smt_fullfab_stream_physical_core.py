"""Handwritten event dictionaries only; old audit is exclusively the test oracle."""
from copy import deepcopy
import gc
import importlib.util
import json
import math
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.smt.audit import audit_trace as oracle, sampled as oracle_sampled

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('draft_physical_core', HERE.parent / 'src/smt_fullfab/stream_physical_core.py')
core = importlib.util.module_from_spec(spec);spec.loader.exec_module(core)
probe_spec = importlib.util.spec_from_file_location('physical_contract_fixture', HERE.parent / 'artifacts/smt_fullfab_review_drafts/stream_physical_checker_v1/probe_small_contract.py')
probe = importlib.util.module_from_spec(probe_spec);probe_spec.loader.exec_module(probe)


def renumber(events):
    for index, event in enumerate(events):event['seq'] = index
    return events


def terminal(events, time, statuses):
    events[-1].update(time=time, lot_statuses=statuses)
    events[0]['manifest']['horizon'] = time
    return events


class PhysicalCoreTests(unittest.TestCase):
    def exact(self, actual, expected, path='root'):
        self.assertIs(type(actual), type(expected), path)
        if isinstance(expected, dict):
            self.assertEqual(list(actual), list(expected), path)
            for key in expected:self.exact(actual[key], expected[key], path + '.' + str(key))
        elif isinstance(expected, list):
            self.assertEqual(len(actual), len(expected), path)
            for index, (a, b) in enumerate(zip(actual, expected)):self.exact(a, b, path + f'[{index}]')
        elif isinstance(expected, float):
            self.assertEqual(actual.hex(), expected.hex(), path)
        else:self.assertEqual(actual, expected, path)

    def parity(self, events, valid=None):
        expected = oracle(deepcopy(events))
        actual = core.audit_events(iter(deepcopy(events)))
        if '_core_scope' in actual:
            scope = actual.pop('_core_scope')
            self.assertFalse(scope['projection_binding_verified'])
            self.assertFalse(scope['atomic_report_published'])
            self.assertFalse(scope['long_window_readiness_certified'])
            self.assertEqual(actual['audit_version'], core.VERSION)
            actual['audit_version'] = core.REFERENCE_VERSION
        self.exact(actual, expected)
        if valid is not None:self.assertEqual(actual['valid'], valid, actual['errors'])
        return actual

    def test_baseline_single_and_two_lots_exact_all_fields_and_types(self):
        self.parity(probe.fixture(), True)
        self.parity(probe.fixture(two_lots=True), True)

    def test_duplicate_completion_joins_latest_lot_state(self):
        events = probe.fixture();events.insert(-1, {'time': 15, 'kind': 'lot_complete', 'lot': 'x'})
        result = self.parity(renumber(events), False)
        self.assertEqual(result['metrics']['mean_cycle_seconds_completed'], 115)
        self.assertEqual(result['errors'], ['7: incomplete route marked done', 'lot conservation'])

    def test_closed_duplicate_job_preserves_identity_and_latest_value(self):
        result = self.parity(probe.fixture(two_lots=True, duplicate_job=True), False)
        self.assertEqual(result['errors'], ['10: duplicate job'])
        self.assertEqual(result['metrics']['controlled_completed_operation_lots'], 2)
        self.assertEqual(result['metrics']['controlled_machine_utilization']['0']['completed_operation_lots'], 1)

    def test_terminal_nonfinal_and_200_errors_keep_old_order(self):
        events = probe.fixture();events.append({'seq': 8, 'time': 20, 'kind': 'unknown'})
        result = self.parity(events, False)
        self.assertEqual(result['errors'], ['terminal must be last', '8: unknown event unknown', 'missing terminal event'])
        events += [{'seq': -1, 'time': 20, 'kind': 'unknown'} for _ in range(130)]
        self.assertEqual(len(self.parity(events, False)['errors']), 200)

    def test_snapshot_prefix_not_implicitly_certified_and_missing_terminal(self):
        self.parity(probe.fixture()[:-1], False)
        events = probe.fixture();events.insert(3, {'time': 0, 'kind': 'snapshot_loaded', 'prefix_event_count': 3})
        self.parity(renumber(events), False)  # Raw physical core does not perform fullfab adaptation.

    def test_missing_initial_empty_and_duplicate_initial(self):
        self.parity([], False);self.parity([{'kind': 'ready'}], False)
        events = probe.fixture();events.insert(1, deepcopy(events[0]))
        self.parity(renumber(events), False)

    def test_calendar_and_overlapping_downtime_extend_jobs_in_order(self):
        events = probe.fixture();manifest = events[0]['manifest']
        manifest['calendars'] = {key: {'machine': 0, 'first_time': time, 'length': {'type': 'constant', 'c': duration},
            'repeat': {'type': 'constant', 'c': 100}, 'breakdown': True} for key, time, duration in [('a', 5, 3), ('b', 6, 2)]}
        events[5]['time'] = events[6]['time'] = 15
        events[5:5] = [
            {'time': 5, 'kind': 'downtime', 'machine': 0, 'calendar': 'a', 'occurrence': 0, 'breakdown': True,
             'duration': 3, 'affected_jobs': [0], 'machine_ready': 13, 'blocked_until': 8},
            {'time': 6, 'kind': 'downtime', 'machine': 0, 'calendar': 'b', 'occurrence': 0, 'breakdown': True,
             'duration': 2, 'affected_jobs': [0], 'machine_ready': 15, 'blocked_until': 10}]
        self.parity(renumber(events), True)
        bad = deepcopy(events);bad[5]['affected_jobs'] = []
        self.parity(bad, False)
        bad = deepcopy(events);del bad[5]['machine_ready']
        self.parity(bad, False)  # Partial branch changes remain visible to later events.

    def test_missing_calendar_due_and_wrong_sample_are_rejected(self):
        events = probe.fixture();events[0]['manifest']['calendars']['a'] = {
            'machine': 0, 'first_time': 5, 'length': {'type': 'constant', 'c': 1},
            'repeat': {'type': 'constant', 'c': 100}, 'breakdown': False}
        result = self.parity(events, False)
        self.assertIn('missing due calendar event: a', result['errors'])
        events = probe.fixture();events[4]['processing_seconds'] = 99
        self.parity(events, False)

    def test_piece_pm_setup_and_min_runs(self):
        events = probe.fixture();manifest = events[0]['manifest'];step = manifest['routes']['r'][0]
        step.update(setup='A', setup_time=2);manifest['min_runs'] = {'A': 3}
        manifest['piece_pm'] = {'0': [{'key': 'pieces', 'remaining': 25, 'repeat': 100,
                                       'occurrence': 0, 'length': {'type': 'constant', 'c': 3}}]}
        events[4].update(setup_seconds=2, machine_ready=15, process_end=12, lot_end=12, min_runs_left=2,
                         piece_pm=[{'key': 'pieces', 'duration': 3, 'occurrence': 0}])
        events[5]['time'] = events[6]['time'] = 12
        self.parity(events, True)
        for field, value in [('piece_pm', []), ('min_runs_left', 0), ('setup_after', 'A')]:
            bad = deepcopy(events);bad[4][field] = value;self.parity(bad, False)

    def test_sampling_skip_and_seeded_rework(self):
        events = probe.fixture();events[0]['manifest']['routes']['r'][0]['sampling_percent'] = 0
        draw = oracle_sampled(701, ['sample', 'x', 1, 1], {'type': 'uniform', 'm': 50, 'offset': 50})
        events = [events[0], events[1], {'time': 0, 'kind': 'skip', 'lot': 'x', 'step': 1, 'visit': 1, 'draw': draw},
                  {'time': 0, 'kind': 'lot_complete', 'lot': 'x'}, events[-1]]
        self.parity(renumber(events), True)
        events[2]['draw'] += 1;self.parity(events, False)
        events = probe.fixture();events[0]['manifest']['routes']['r'][0].update(rework_percent=100, rework_step=1)
        draw = oracle_sampled(701, ['rework', 'x', 1, 1], {'type': 'uniform', 'm': 50, 'offset': 50})
        action, dispatch = deepcopy(events[3]), deepcopy(events[4])
        action.update(time=10, decision=1);dispatch.update(time=10, job=1, visits=[2], machine_ready=20, process_end=20, lot_end=20)
        events = events[:6] + [dict(time=10, kind='rework', lot='x', step=1, visit=1, target=1, draw=draw),
            dict(time=10, kind='ready', lot='x', step=1, visit=2), action, dispatch, events[-1]]
        terminal(events, 15, {'x': 'processing'});self.parity(renumber(events), True)
        bad = deepcopy(events);bad[6]['target'] = 2;self.parity(bad, False)

    def two_step(self):
        events = probe.fixture();manifest = events[0]['manifest'];first = manifest['routes']['r'][0]
        first['dedicate_for'] = 2
        second = deepcopy(first);second.update(step=2, name='second', dedicate_for=None, transport={'type': 'constant', 'c': 4})
        manifest['routes']['r'].append(second)
        machine = deepcopy(manifest['machines'][0]);machine['id'] = 1;manifest['machines'].append(machine)
        manifest['controlled_machine_ids'] = [0, 1];manifest['physical_machines'] = 2
        events[4].update(transport_seconds=4, lot_end=14);events[5]['time'] = 14
        action, dispatch = deepcopy(events[3]), deepcopy(events[4]);action.update(time=14, decision=1)
        dispatch.update(time=14, job=1, steps=[2], machine_ready=24, process_end=24, lot_end=24, transport_seconds=0)
        events = events[:6] + [dict(time=14, kind='ready', lot='x', step=2, visit=1), action, dispatch,
            dict(time=24, kind='operation_complete', job=1, lot='x', step=2), dict(time=24, kind='lot_complete', lot='x'), events[-1]]
        return renumber(terminal(events, 30, {'x': 'done'}))

    def test_transport_predecessors_dedication_and_qualification(self):
        events = self.two_step();self.parity(events, True)
        bad = deepcopy(events);bad[7]['action']['dispatches'][0]['machine'] = 1;bad[8]['machine'] = 1
        result = self.parity(bad, False);self.assertIn('8: dedication violation', result['errors'])
        bad = deepcopy(events);bad[0]['manifest']['machines'][0]['family'] = 'wrong';self.parity(bad, False)

    def test_cascading_two_slots_and_non_cascading_overlap_rejection(self):
        events = probe.fixture(two_lots=True)
        manifest = events[0]['manifest'];manifest['machines'][0]['cascading'] = True
        manifest['routes']['r'][0]['cadence'] = {'type': 'constant', 'c': 5}
        a1,d1,c1,l1,a2,d2,c2,l2 = events[5:13]
        d1.update(cadence_seconds=5, machine_ready=5)
        a2.update(time=5);d2.update(time=5, cadence_seconds=5, machine_ready=10, process_end=15, lot_end=15)
        c2['time']=l2['time']=15
        events = renumber(events[:5] + [a1,d1,a2,d2,c1,l1,c2,l2,events[-1]])
        self.parity(events, True)
        bad=deepcopy(events);bad[0]['manifest']['machines'][0]['cascading']=False
        self.parity(bad, False)

    def test_third_cascading_job_exceeds_physical_capacity(self):
        events=probe.fixture(two_lots=True);manifest=events[0]['manifest']
        third=deepcopy(manifest['lots'][0]);third.update(id='z',name='z');manifest['lots'].append(third)
        manifest['initial_wip']=3;manifest['machines'][0]['cascading']=True
        manifest['routes']['r'][0]['cadence']={'type':'constant','c':1}
        first_action,first_dispatch=deepcopy(events[5]),deepcopy(events[6])
        first_dispatch.update(cadence_seconds=1,machine_ready=1)
        prefix=events[:5]+[dict(time=0,kind='release',lot='z'),dict(time=0,kind='ready',lot='z',step=1,visit=1)]
        running=[]
        for n,lid in enumerate(['x','y','z']):
            action,dispatch=deepcopy(first_action),deepcopy(first_dispatch)
            action.update(time=n,decision=n);action['action']['dispatches'][0]['lot_ids']=[lid]
            dispatch.update(time=n,job=n,lots=[lid],machine_ready=n+1,process_end=n+10,lot_end=n+10)
            running.extend([action,dispatch])
        ending=[]
        for n,lid in enumerate(['x','y','z']):
            ending.extend([dict(time=n+10,kind='operation_complete',job=n,lot=lid,step=1),dict(time=n+10,kind='lot_complete',lot=lid)])
        result=self.parity(renumber(terminal(prefix+running+ending+[events[-1]],20,{'x':'done','y':'done','z':'done'})),False)
        self.assertEqual(result['errors'],['12: physical processing-slot capacity'])

    def test_setup_fallback_table_and_unfinished_minimum_run(self):
        events=probe.fixture(two_lots=True);manifest=events[0]['manifest']
        manifest['routes']['r'][0].update(setup='A',setup_time=None)
        manifest['setups']=[{'old':'','new':'A','seconds':2}];manifest['min_runs']={'A':3}
        events[6].update(setup_after='A',setup_seconds=2,machine_ready=12,process_end=12,lot_end=12,min_runs_left=2)
        events[7]['time']=events[8]['time']=12
        events[10].update(setup_before='A',setup_after='A',min_runs_left=1)
        self.parity(events,True)
        # A different route can demand another setup before the first minimum
        # run finishes; this is a real constraint check, not state pre-seeding.
        manifest['routes']['r2']=[{**deepcopy(manifest['routes']['r'][0]),'setup':'B','setup_time':0}]
        manifest['lots'][1]['route']='r2'
        events[10].update(setup_after='B')
        result=self.parity(events,False)
        self.assertIn('10: minimum setup runs',result['errors'])

    def test_batch_fill_arrays_and_identity_order(self):
        events = probe.fixture(two_lots=True);events[0]['manifest']['routes']['r'][0].update(batch_max=2, batching=True)
        action, dispatch = deepcopy(events[5]), deepcopy(events[6]);action['action']['dispatches'][0]['lot_ids']=['y','x']
        dispatch.update(lots=['y','x'],steps=[1,1],visits=[1,1])
        events = events[:5] + [action,dispatch,
            dict(time=10,kind='operation_complete',job=0,lot='y',step=1),
            dict(time=10,kind='lot_complete',lot='y'),
            dict(time=10,kind='operation_complete',job=0,lot='x',step=1),
            dict(time=10,kind='lot_complete',lot='x'),events[-1]]
        result=self.parity(renumber(events), True)
        self.assertEqual(result['metrics']['controlled_batch_fill_ratios'],[1.0])
        bad=deepcopy(events);bad[0]['manifest']['routes']['r'][0]['batch_min']=3;self.parity(bad,False)

    def test_virtual_resource_dispatch_and_production_denominator(self):
        events=probe.fixture();manifest=events[0]['manifest']
        physical=deepcopy(manifest['machines'][0]);physical.update(id=1,family='other')
        manifest['machines'][0]['group']='Delay_32';manifest['machines'].append(physical)
        manifest['controlled_machine_ids']=[1];manifest['virtual_delay_resources']=1
        events[4]['owner']='environment';del events[3]
        self.parity(renumber(events),True)

    def test_python_numeric_keys_alias_but_string_keys_do_not(self):
        for first,second in [(1,'1'),(1,True),(0,False),(1,1.0),(None,None),('z','a')]:
            with self.subTest(first=first,second=second):
                events=probe.fixture(two_lots=True)
                events[6]['job']=events[7]['job']=first
                events[10]['job']=events[11]['job']=second
                self.parity(events,first!=second)
        events=probe.fixture();events[4]['job']=[];events[5]['job']=[]
        self.parity(events,False)

    def test_disk_history_first_key_order_and_repeated_machine_refs(self):
        with tempfile.TemporaryDirectory() as td, sqlite3.connect(Path(td)/'h.sqlite') as db:
            history=core.History(db)
            for key in (2,1,True,2):
                history.put_job(key,dict(pending={'x'},process_end=30,done=False))
            self.assertEqual([key for key,_ in history.jobs()],[2,1])
            stream=history.machine_stream(0)
            history.append(stream,2);history.append(stream,2)
            self.assertEqual(sum(history.job(key)['process_end']>20 for key in history.records(stream)),2)
            self.assertEqual(db.execute('SELECT count(*) FROM records').fetchone()[0],2)

    def test_partial_errors_keep_prior_mutations_and_full_raw_downtime_metrics(self):
        events=probe.fixture();del events[4]['processing_seconds'];self.parity(events,False)
        events=probe.fixture();events.insert(5,dict(time=5,kind='downtime',machine=0,calendar='absent',blocked_until=7))
        result=self.parity(renumber(events),False)
        self.assertEqual(result['metrics']['production_group_statistics']['production']['calendar_downtime_exposure_fraction'],0.1)

    def test_action_wait_pending_and_terminal_metric_comparison(self):
        for change in ('wait','duplicate','owner','metrics'):
            with self.subTest(change=change):
                events=probe.fixture()
                if change=='wait':events[3]['action']['wait_seconds']=1801
                elif change=='duplicate':events[3]['action']['dispatches']*=2
                elif change=='owner':events[4]['owner']='environment'
                else:events[-1]['metrics']={'throughput_lots':99,'controlled_batch_fill_ratios':[0.5]}
                self.parity(events,False)

    def test_rng_exact_constant_uniform_legacy_width_and_exponential(self):
        for distribution in [{'type':'constant','c':10},{'type':'uniform','m':5,'offset':2},
                             {'type':'uniform','m':5,'width':4},{'type':'exponential','mean':8}]:
            self.exact(core.sampled(701,['probe',1],distribution),oracle_sampled(701,['probe',1],distribution))

    def test_no_oracle_delegation_and_no_sized_or_repeatable_input_required(self):
        class OnePass:
            def __init__(self):self.used=False
            def __iter__(self):
                if self.used:raise AssertionError('iterable replayed')
                self.used=True;yield from probe.fixture()
            def __len__(self):raise AssertionError('input sized/materialized')
        with patch('src.smt.audit.audit_trace',side_effect=AssertionError('oracle delegation')):
            result=core.audit_events(OnePass())
        self.assertTrue(result['valid'],result['errors'])

    def test_generator_failure_and_unsupported_identity_cannot_certify(self):
        def broken():
            yield from probe.fixture()
            raise OSError('untrusted iterable ended with error')
        with self.assertRaisesRegex(OSError,'untrusted iterable'):core.audit_events(broken())
        events=probe.fixture();events[4]['job']=float('nan')
        with self.assertRaises(core.UnsupportedIdentity):core.audit_events(iter(events))
        with self.assertRaises(TypeError):core.audit_events('path.jsonl')

    def test_source_helper_is_optional_and_diagnostics_append_in_order(self):
        # Pure CSV verifier integration is mocked, not a real source-table/factory run.
        events=probe.fixture()
        with patch('src.smt.source_check.verify_source',return_value=['source: first','source: second']):
            expected=oracle(deepcopy(events),'synthetic-dir')
            actual=core.audit_events(iter(deepcopy(events)),'synthetic-dir')
        actual.pop('_core_scope');actual['audit_version']=core.REFERENCE_VERSION
        self.exact(actual,expected)

    def test_required_field_deletions_and_wrong_shapes_exact_oracle_outcomes(self):
        fixtures=[]
        base=probe.fixture()
        for index,event in enumerate(base):
            for key in event:
                if key=='manifest':continue
                changed=deepcopy(base);del changed[index][key];fixtures.append((f'delete {index}.{key}',changed))
        for index,key,values in [(4,'job',[[],{},False,'0']), (4,'machine',[99,None]),
                                 (4,'lots',[[],['missing'],['x','x']]), (4,'steps',[[],[2]]),
                                 (3,'action',[{},[],None]), (5,'step',[0,2])]:
            for value in values:
                changed=deepcopy(base);changed[index][key]=value;fixtures.append((f'shape {index}.{key}={value!r}',changed))
        changed=deepcopy(base);changed[4]['machine']=99;del changed[4]['lots'];fixtures.append(('lookup error order',changed))
        for name,events in fixtures:
            with self.subTest(name=name):
                try:expected=oracle(deepcopy(events))
                except Exception as exc:
                    with self.assertRaises(type(exc)) as raised:core.audit_events(iter(deepcopy(events)))
                    self.assertEqual(str(raised.exception),str(exc))
                else:
                    actual=core.audit_events(iter(deepcopy(events)))
                    if '_core_scope' in actual:
                        actual.pop('_core_scope');actual['audit_version']=core.REFERENCE_VERSION
                    self.exact(actual,expected)

    def test_malformed_downtime_keeps_primary_typeerror_without_unraisable_cleanup(self):
        evidence=HERE.parent/'artifacts/smt_fullfab_diagnostics/stream_physical_core_review_v1/cleanup_evidence.json'
        events=json.loads(evidence.read_text())['events']
        def capture(function):
            gc.collect();errors=[]
            with patch.object(sys,'unraisablehook',lambda item:errors.append((item.exc_type.__name__,str(item.exc_value)))):
                try:function(deepcopy(events))
                except Exception as exc:primary=(type(exc).__name__,str(exc))
                else:self.fail('malformed metric produced a report')
                gc.collect()
            return primary,errors
        expected=capture(oracle)
        actual=capture(lambda values:core.audit_events(iter(values)))
        self.assertEqual(expected,(('TypeError',"'<' not supported between instances of 'str' and 'float'"),[]))
        self.assertEqual(actual,expected)

    def test_suspended_jobs_and_records_are_released_before_database_close(self):
        db=sqlite3.connect(':memory:');history=core.History(db)
        history.put_job(0,{'pending':{'x'}});history.append('probe',{'exact':True})
        jobs,records=history.jobs(),history.records('probe')
        next(jobs);next(records);self.assertEqual(len(history._active_cursors),2)
        errors=[]
        with patch.object(sys,'unraisablehook',lambda item:errors.append(str(item.exc_value))):
            history.close();self.assertEqual(len(history._active_cursors),0)
            db.close();jobs.close();records.close();history.close();gc.collect()
        self.assertEqual(errors,[])

    def test_actual_cursor_cleanup_errors_are_not_swallowed_or_retried(self):
        class FailingCursor:
            attempts=0
            def close(self):
                self.attempts+=1
                raise sqlite3.OperationalError('explicit SQL cleanup failure')
        with sqlite3.connect(':memory:') as db:
            history=core.History(db);cursor=FailingCursor();history._active_cursors.add(cursor)
            with self.assertRaisesRegex(sqlite3.OperationalError,'explicit SQL cleanup failure'):history.close()
            self.assertEqual(history._active_cursors,set());history.close();self.assertEqual(cursor.attempts,1)


if __name__=='__main__':unittest.main()
