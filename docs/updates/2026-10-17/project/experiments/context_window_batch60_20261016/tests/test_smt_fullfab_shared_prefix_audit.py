"""Tiny files and original pure auditors; no factory/model/solver/warm-up.

Only independent CSV verification is stubbed in integration fixtures, explicitly
not evidence of real dataset validity. Core/source/opportunity/projection and
their actual EOF/storage checks run unchanged when root authorizes these tests.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab import shared_prefix_audit as p


def encoded(value): return (json.dumps(value, separators=(',', ':')) + '\n').encode()
def sha(raw): return hashlib.sha256(raw).hexdigest()


def fixture(*, t0=5.0, duration=10.0, complete=False, downtime=False, future_initial=None):
    step = {'step':1,'family':'G','name':'process','batch_min':1,'batch_max':1,
        'batching':False,'processing':{'type':'constant','c':duration},
        'cadence':{'type':'constant','c':duration},'cascading':False,'setup':'','setup_time':None,
        'sampling_percent':100.0,'rework_percent':0.0,'rework_step':'','dedicate_for':None,
        'transport':{'type':'constant','c':0}}
    lot = {'id':'x','name':'x','part':'p','route':'r','priority':10,'pieces':25,
        'release':-100.0,'due':15.0,'step':0,'initial':True}
    manifest = {'version':'smt-adapter-v2','fullfab_version':'smt-fullfab-env-0.3',
        'seed':1701,'horizon':20.0,'controlled_machine_ids':list(range(913)),
        'physical_machines':913,'virtual_delay_resources':0,'initial_wip':1,
        'outside_policy':'virtual-delay-only; no background production','warmup_seconds':0,
        'machines':[{'id':i,'family':'G','group':'production','load':0.0,'unload':0.0,'cascading':False} for i in range(913)],
        'routes':{'r':[step]},'lots':[lot],'setups':[],'min_runs':{},'calendars':{},'piece_pm':{},
        'data_hashes':{'tiny.txt':sha(b'tiny fixture data\n')}}
    if downtime:
        manifest['calendars']['cal'] = {'machine':0,'name':'cal','breakdown':True,
            'length':{'type':'constant','c':3.0},'repeat':{'type':'constant','c':100.0},'first_time':2.0}
    plan = {'version':'warmup','created_at':0.0,'valid_until':t0,'freeze_until':0.0,
        'scope':list(range(913)),'reason':'synthetic explicit plan', 'holds':[],
        'tasks':[{'id':'t','machine':0,'lot_ids':['x'],'steps':[1],'visits':[1],'not_before':0.0}]}
    events = []
    def emit(time, kind, **kw): events.append({'seq':len(events),'time':time,'kind':kind,**kw})
    emit(0.0,'initial',manifest=manifest); emit(0.0,'release',lot='x',initial=True)
    emit(0.0,'ready',lot='x',step=1,visit=1); emit(0.0,'plan_committed',plan=plan)
    emit(0.0,'dispatch',job=0,machine=0,lots=['x'],steps=[1],visits=[1],owner='plan',
        plan_version='warmup',plan_task_id='t',setup_before='',setup_after='',setup_seconds=0,
        processing_seconds=duration,cadence_seconds=duration,transport_seconds=0,
        process_end=duration,lot_end=duration,machine_ready=duration,piece_pm=[],min_runs_left=0,
        processing_key=['processing',[['x',1,1]]])
    end = duration; token = 0; down = 0.0
    if downtime:
        emit(0.0,'time_advance',to=2.0)
        end += 3.0; token = 1; down = 5.0
        emit(2.0,'downtime',calendar='cal',machine=0,occurrence=0,breakdown=True,
            duration=3.0,blocked_until=down,machine_ready=end,affected_jobs=[0])
        emit(2.0,'time_advance',to=t0)
    else: emit(0.0,'time_advance',to=t0)
    if complete:
        emit(duration,'operation_complete',job=0,lot='x',step=1)
        emit(duration,'lot_complete',lot='x')
    lots = {'x':{**deepcopy(lot),'status':'done' if complete else 'processing','step':1 if complete else 0,
        'visits':{'1':1},'dedications':{},'ready_since':0.0,'done':duration if complete else None}}
    q = []
    def queued(when, kind, payload): q.append([when,len(q)+2,kind,payload])
    if not complete:
        queued(duration,'process_free',{'job':0,'token':0})
        queued(duration,'lot_done',{'job':0,'token':0}); queued(duration,'wake',None)
        if downtime:
            queued(end,'lot_done',{'job':0,'token':1}); queued(end,'process_free',{'job':0,'token':1})
            queued(end,'wake',None); queued(105.0,'calendar',{'key':'cal','n':1})
    if future_initial is not None:
        future = dict(lot,id='y',name='y',release=future_initial)
        manifest['lots'].append(future); manifest['initial_wip'] += 1
        lots['y'] = {**deepcopy(future),'status':'unreleased','visits':{},'dedications':{},'ready_since':None,'done':None}
        queued(future_initial,'release','y')
    q.sort(key=lambda entry:entry[:2])
    machines = {str(i):{'ready':end if i == 0 else 0.0,'down_until':down if i == 0 else 0.0,
        'setup':'','min_left':0,'min_setup':'','last_token':0} for i in range(913)}
    state = {'seed':1701,'horizon':20.0,'t':t0,'seq':max((e[1] for e in q),default=4),
        'dispatch_id':1,'decisions':1,'releases':1,'completed':['x'] if complete else [],
        'finished':False,'wait_until':0.0,'lots':lots,'machine_state':machines,
        'jobs':{'0':{'machine':0,'lots':['x'],'start':0.0,'process_end':end,'lot_end':end,
            'token':token,'done':complete,'controlled':True}},
        'calendars':deepcopy(manifest['calendars']),'pm_counters':{'0':[]},'queue_area':0.0,'last_area_t':0.0,
        'manifest':manifest,'plan':plan,'observation_start':0.0,'q':q,'waiting':{'G':[]},
        'processing_by_machine':{'0':[] if complete else [0]},
        'stats':{'dispatches':1,'controlled_dispatches':1,'batch_dispatches':0},
        'executed_tasks':[['warmup','t']],'plan_versions':['warmup'],'trace':events}
    snapshot = {'schema':'smt-fullfab-snapshot-1','version':'smt-fullfab-env-0.3',
        'implementation_sha256':{'not-executed-fixture.py':'a'*64},'physics_sha256':'b'*64,
        'data_hashes':manifest['data_hashes'],'state':state,'state_sha256':p.digest(state),
        'random_mechanism':'event-keyed SHA256; no mutable global RNG',
        'initialization':'official WIP cold start; any prehistory is retained, not asserted steady state'}
    return snapshot


def no_dispatch_fixture():
    """Explicit holds for all eligible machines, with no job/queue history."""
    value = fixture(); state = value['state']
    state['trace'] = [event for event in state['trace'] if event['kind'] != 'dispatch']
    for index, event in enumerate(state['trace']): event['seq'] = index
    state['plan']['tasks'] = []
    state['plan']['holds'] = [{'machine':i, 'until':state['t'], 'reason':'synthetic explicit wait'}
        for i in range(913)]
    state['lots']['x']['status'] = 'waiting'
    state.update(jobs={}, dispatch_id=0, stats={}, processing_by_machine={}, executed_tasks=[],
        q=[], seq=0, waiting={'G':['x']}, queue_area=state['t'])
    state['machine_state']['0']['ready'] = 0.0
    value['state_sha256'] = p.digest(state)
    return value


class PrefixAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.index = 0
        self.data = self.root/'data'; self.data.mkdir(); (self.data/'tiny.txt').write_bytes(b'tiny fixture data\n')

    def run_case(self, snapshot=None, *, source_errors=(), mutate_kwargs=None):
        snapshot = snapshot or fixture(); self.index += 1; at = self.root/str(self.index); at.mkdir()
        snapshot['state_sha256'] = p.digest(snapshot['state'])
        sp = at/'snapshot.json'; tp = at/'trace.jsonl'
        sp.write_bytes(encoded(snapshot)); tp.write_bytes(b''.join(encoded(e) for e in snapshot['state']['trace']))
        original = (sp.read_bytes(), tp.read_bytes())
        kw = {'expected_snapshot_sha256':sha(original[0]),'expected_state_sha256':snapshot['state_sha256'],
            'expected_trace_sha256':sha(original[1]),'boundary_time':snapshot['state']['t'],
            'verify_data_dir':self.data,'output_dir':at/'audit'}
        if mutate_kwargs: kw.update(mutate_kwargs)
        with patch.object(p,'verify_source',return_value=list(source_errors)) as source:
            result = p.audit_prefix(sp,tp,**kw)
        report = json.loads(Path(result['report_path']).read_bytes())
        self.assertEqual(result['report_sha256'],sha(Path(result['report_path']).read_bytes()))
        self.assertEqual(report['snapshot_sha256'],sha(original[0])); self.assertEqual(report['trace_sha256'],sha(original[1]))
        self.assertEqual(report['state_sha256'],snapshot['state_sha256']); self.assertEqual(result['valid'],report['valid'])
        self.assertEqual((sp.read_bytes(),tp.read_bytes()),original); source.assert_called_once()
        self.assertFalse(report['complete_physical_window_certified']); self.assertFalse(report['new_terminal_event_inserted'])
        self.assertFalse(report['whole_private_state_independently_certified'])
        return report, result, at

    def invalid(self, snapshot, fragment):
        report, _, _ = self.run_case(snapshot)
        self.assertFalse(report['valid'],report)
        self.assertTrue(any(fragment in error for error in report['errors']),report['errors'])
        return report

    def test_nonidle_prefix_checks_to_raw_declared_T0_not_last_physical_event(self):
        with patch.object(p.binding.core.Fold,'finish',side_effect=AssertionError('terminal finish forbidden')):
            report, result, _ = self.run_case()
        self.assertTrue(report['valid'],report['errors']); self.assertTrue(result['durable_publication_complete'])
        self.assertEqual(report['physical_prefix']['last_physical_event_time'],0.0)
        self.assertEqual(report['boundary_time'],5.0); self.assertEqual(report['original_horizon'],20.0)
        self.assertEqual(report['physical_prefix']['processing_jobs'],1)
        self.assertEqual(set(report['members']),{'source.json','opportunity.json','projection/projection.json','projection/physical.jsonl'})

    def test_all_same_time_completion_transitions_at_T0_are_drained(self):
        report, _, _ = self.run_case(fixture(duration=5.0,complete=True))
        self.assertTrue(report['valid'],report['errors']); self.assertEqual(report['physical_prefix']['completed_lots'],1)

    def test_missing_due_operation_at_exact_T0_fails_despite_source_and_opportunity(self):
        report = self.invalid(fixture(duration=5.0),'unfinished due operation')
        self.assertTrue(report['source_valid']); self.assertTrue(report['opportunity_valid'])

    def test_missing_same_timestamp_transition_rejected(self):
        value = fixture(duration=5.0,complete=True); value['state']['trace'].pop()
        value['state']['lots']['x'].update(status='transition',done=None); value['state']['completed']=[]
        self.invalid(value,'unresolved transition')

    def test_missing_required_rework_rejected_at_boundary(self):
        value = fixture(duration=5.0,complete=True); value['state']['trace'].pop()
        value['state']['manifest']['routes']['r'][0]['rework_percent']=100.0
        value['state']['lots']['x'].update(status='transition',done=None); value['state']['completed']=[]
        self.invalid(value,'unresolved transition/rework')

    def test_due_calendar_exact_T0_cannot_hide_after_last_physical_event(self):
        value = fixture(); cal = {'machine':0,'name':'c','breakdown':True,'length':{'type':'constant','c':1.0},
            'repeat':{'type':'constant','c':100.0},'first_time':5.0}
        value['state']['manifest']['calendars']['c']=cal; value['state']['calendars']['c']=deepcopy(cal)
        value['state']['q'].insert(0,[5.0,5,'calendar',{'key':'c','n':0}]); value['state']['seq']=5
        self.invalid(value,'missing due calendar')

    def test_due_release_exact_T0_rejected_but_future_initial_release_conserved(self):
        self.invalid(fixture(future_initial=5.0),'missing lot release y')
        report, _, _ = self.run_case(fixture(future_initial=6.0))
        self.assertTrue(report['valid'],report['errors'])

    def test_downtime_tokens_and_updated_future_obligations_match(self):
        report, _, _ = self.run_case(fixture(downtime=True))
        self.assertTrue(report['valid'],report['errors'])
        value = fixture(downtime=True); value['state']['jobs']['0']['token']=0
        self.invalid(value,'jobs.0.token')

    def test_physical_sample_failure_never_inherits_other_valid_flags(self):
        value = fixture(); value['state']['trace'][4]['processing_seconds']=999.0
        report = self.invalid(value,'processing sample')
        self.assertTrue(report['source_valid']); self.assertTrue(report['opportunity_valid'])

    def test_snapshot_physical_fields_and_bool_visit_are_checked(self):
        changes=[('lots.x.visits.1',lambda s:s['lots']['x']['visits'].__setitem__('1',True)),
            ('jobs.0.done',lambda s:s['jobs']['0'].__setitem__('done',True)),
            ('machine_state',lambda s:s['machine_state']['0'].__setitem__('ready',999.0)),
            ('executed_tasks',lambda s:s.__setitem__('executed_tasks',[])),
            ('queue_area',lambda s:s.__setitem__('queue_area',1.0)),
            ('releases',lambda s:s.__setitem__('releases',0))]
        for text, change in changes:
            with self.subTest(field=text):
                value=fixture(); change(value['state']); self.invalid(value,text)

    def test_missing_active_future_job_obligation_is_rejected(self):
        value=fixture(); value['state']['q']=[e for e in value['state']['q'] if e[2]!='lot_done']
        self.invalid(value,'current-token processing/completion obligations')

    def test_source_data_verifier_failure_and_missing_data_are_not_waived(self):
        report, _, _=self.run_case(source_errors=['deliberate input mismatch'])
        self.assertFalse(report['valid']); self.assertIn('source inputs: deliberate input mismatch',report['errors'])
        with self.assertRaises(p.PrefixAuditError): self.run_case(mutate_kwargs={'verify_data_dir':None})

    def test_unreconstructed_fields_are_explicit_not_silently_certified(self):
        value=fixture(); value['state']['machine_state']['0']['last_token']=91
        value['state']['wait_until']=123.0; value['state']['last_area_t']=2.0
        report, _, _=self.run_case(value)
        self.assertTrue(report['valid'],report['errors'])
        self.assertTrue(any('last_token' in x for x in report['physical_prefix']['not_independently_reconstructed']))
        self.assertFalse(report['whole_private_state_independently_certified'])

    def test_terminal_or_wrong_external_state_anchor_fails_closed(self):
        value=fixture(); value['state']['finished']=True
        with self.assertRaises(p.PrefixAuditError): self.run_case(value)
        with self.assertRaises(p.PrefixAuditError): self.run_case(mutate_kwargs={'expected_state_sha256':'0'*64})
        value=fixture(); value['state']['trace'].append({'seq':6,'time':20.0,'kind':'terminal'})
        with self.assertRaises(p.PrefixAuditError): self.run_case(value)

    def test_original_raw_trace_must_match_snapshot_and_reach_T0(self):
        value=fixture(); value['state']['trace'][-1]['to']=4.0
        with self.assertRaisesRegex(p.PrefixAuditError,'explicitly reach'): self.run_case(value)
        value=fixture(); value['state']['trace'][-1]['to']=6.0
        with self.assertRaisesRegex(p.PrefixAuditError,'crosses T0'): self.run_case(value)

    def test_raw_trace_separately_rehashed_cannot_replace_snapshot_history(self):
        value=fixture(); sp=self.root/'original.json'; tp=self.root/'different.jsonl'
        sp.write_bytes(encoded(value)); events=deepcopy(value['state']['trace'])
        events[-1]['to']=4.0; tp.write_bytes(b''.join(encoded(e) for e in events))
        with self.assertRaisesRegex(p.PrefixAuditError,'raw trace/snapshot prefix'):
            p.audit_prefix(sp,tp,expected_snapshot_sha256=sha(sp.read_bytes()),expected_state_sha256=value['state_sha256'],
                expected_trace_sha256=sha(tp.read_bytes()),boundary_time=5.0,verify_data_dir=self.data,output_dir=self.root/'bad')

    def test_final_publication_preserves_original_snapshot_anchor(self):
        publish=p.binding._publish_report
        def replaced(report, destination, fence):
            path=Path(destination).parent.parent/'snapshot.json'
            path.write_bytes(path.read_bytes()+b' ')
            return publish(report,destination,fence)
        with patch.object(p.binding,'_publish_report',side_effect=replaced),self.assertRaises(p.binding.SourceChangedError): self.run_case()
        self.assertFalse((self.root/'1/audit/prehistory_audit.json').exists())

    def test_bound_file_rejects_leaf_symlink_even_with_exact_target_hash(self):
        target = self.root/'target.json'; target.write_bytes(b'original bytes\n')
        logical = self.root/'logical.json'; logical.symlink_to(target)
        with self.assertRaisesRegex(p.binding.SourceChangedError, 'non-symlink'):
            p._bound_file(logical, sha(target.read_bytes()), retain=True)
        self.assertEqual(target.read_bytes(), b'original bytes\n')

    def test_regular_leaf_accepts_parent_alias_and_fences_logical_path(self):
        first = self.root/'first'; second = self.root/'second'; first.mkdir(); second.mkdir()
        (first/'member').write_bytes(b'original\n'); (second/'member').write_bytes(b'changed\n')
        alias = self.root/'parent_alias'; alias.symlink_to(first, target_is_directory=True)
        logical = alias/'member'
        raw, receipt, refs = p._bound_file(logical, sha(b'original\n'), retain=True)
        self.assertEqual(raw, b'original\n'); self.assertEqual(receipt['sha256'], sha(raw))
        self.assertIn(logical.absolute(), refs)
        p.binding._fence(refs)
        alias.unlink(); alias.symlink_to(second, target_is_directory=True)
        with self.assertRaises(p.binding.SourceChangedError): p.binding._fence(refs)
        self.assertEqual((first/'member').read_bytes(), b'original\n')

    def test_source_member_leaf_symlink_rejected_before_member_binding(self):
        source_audit = p.stream_source_audit.audit_plan_sources
        def aliased(*args, **kwargs):
            result = source_audit(*args, **kwargs)
            member = Path(kwargs['report_path']); target = member.with_name('source_original.json')
            member.rename(target); member.symlink_to(target)
            self.assertEqual(sha(target.read_bytes()), result['report_sha256'])
            return result
        with patch.object(p.stream_source_audit, 'audit_plan_sources', side_effect=aliased), \
                self.assertRaises(p.binding.SourceChangedError):
            self.run_case()
        self.assertFalse((self.root/'1/audit/prehistory_audit.json').exists())

    def test_source_member_replaced_before_publication_keeps_original_fence(self):
        publish = p.binding._publish_report
        def replaced(report, destination, fence):
            member = Path(destination).parent/'source.json'; original = member.read_bytes()
            target = member.with_name('source_original.json'); target.write_bytes(original)
            member.unlink(); member.symlink_to(target)
            self.assertEqual(sha(target.read_bytes()), report['members']['source.json']['sha256'])
            return publish(report, destination, fence)
        with patch.object(p.binding, '_publish_report', side_effect=replaced), \
                self.assertRaises(p.binding.SourceChangedError):
            self.run_case()
        self.assertFalse((self.root/'1/audit/prehistory_audit.json').exists())

    def test_trace_logical_leaf_replacement_during_inspection_is_rejected(self):
        inspect = p.inspect_jsonl
        def replaced(path, **kwargs):
            path = Path(path); original = path.read_bytes(); target = path.with_name('trace_original.jsonl')
            path.rename(target); path.symlink_to(target)
            seal = inspect(path, **kwargs)
            self.assertEqual(target.read_bytes(), original)
            return seal
        with patch.object(p, 'inspect_jsonl', side_effect=replaced), \
                self.assertRaises((p.PrefixAuditError, p.binding.SourceChangedError)):
            self.run_case()
        self.assertFalse((self.root/'1/audit/prehistory_audit.json').exists())

    def test_zero_dispatch_and_empty_queue_counter_baseline_is_valid(self):
        report, _, _ = self.run_case(no_dispatch_fixture())
        self.assertTrue(report['valid'], report['errors'])
        self.assertEqual(report['physical_prefix']['jobs'], 0)
        self.assertEqual(report['physical_prefix']['processing_jobs'], 0)

    def test_empty_histories_reject_invalid_dispatch_and_seq_counters(self):
        for field, values, message in (
                ('dispatch_id', (-1, True, 0.0, 1), 'dispatch/job identity'),
                ('seq', (-1, False, 0.0), 'invalid queued-event domain')):
            for value in values:
                with self.subTest(field=field, value=value):
                    snapshot = no_dispatch_fixture(); snapshot['state'][field] = value
                    self.invalid(snapshot, message)

    def test_added_data_file_before_final_publication_is_not_reanchored(self):
        publish=p.binding._publish_report
        def added(report,destination,fence):
            (self.data/'late.txt').write_bytes(b'late')
            return publish(report,destination,fence)
        with patch.object(p.binding,'_publish_report',side_effect=added),self.assertRaises(p.PrefixAuditError): self.run_case()
        self.assertFalse((self.root/'1/audit/prehistory_audit.json').exists())

    def test_existing_output_is_never_reused(self):
        _, result, at=self.run_case(); before=Path(result['report_path']).read_bytes()
        sp=at/'snapshot.json'; tp=at/'trace.jsonl'; value=json.loads(sp.read_bytes())
        with patch.object(p,'verify_source',return_value=[]),self.assertRaises(FileExistsError):
            p.audit_prefix(sp,tp,expected_snapshot_sha256=sha(sp.read_bytes()),expected_state_sha256=value['state_sha256'],
                expected_trace_sha256=sha(tp.read_bytes()),boundary_time=5.0,verify_data_dir=self.data,output_dir=at/'audit')
        self.assertEqual(Path(result['report_path']).read_bytes(),before)

    def test_empty_or_executable_plan_cannot_mask_missed_dispatch(self):
        value=fixture(); s=value['state']; s['trace']=[e for e in s['trace'] if e['kind']!='dispatch']
        for i,e in enumerate(s['trace']):e['seq']=i
        s['lots']['x']['status']='waiting'; s['jobs']={}; s['dispatch_id']=0; s['stats']={}
        s['processing_by_machine']={}; s['executed_tasks']=[]; s['q']=[]; s['waiting']={'G':['x']}
        s['machine_state']['0']['ready']=0.0; s['queue_area']=5.0
        self.invalid(value,'executable submitted task')

    def test_strict_json_and_integer_identity_domains(self):
        for raw in (b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":1e999}'):
            with self.subTest(raw=raw),self.assertRaises((ValueError,p.PrefixAuditError)):p.strict(raw)
        value=fixture(); value['state']['processing_by_machine']['0']=[False]
        self.invalid(value,'integer identity')


if __name__ == '__main__': unittest.main()
