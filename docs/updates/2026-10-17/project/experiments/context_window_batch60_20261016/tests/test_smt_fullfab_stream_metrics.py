"""Read-only metric parity; no simulator, optimizer, or model is imported/run."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import tracemalloc
import unittest
from unittest.mock import patch

from src.smt_fullfab.metrics import compute_metrics as legacy
from src.smt_fullfab import stream_metrics
from tests.test_smt_fullfab_metrics import metric_events


def physical_events():
    lots=[{'id':lid,'release':release,'due':due,'priority':priority,'pieces':25,'part':part,'route':route}
          for lid,release,due,priority,part,route in
          [('a',-10,1,10,'p','R'),('b',0,10,20,'p','R'),('c',0,6,30,'q','R'),
           ('d',10,18,10,'q','R'),('v',0,3,10,'v','V'),('future',30,40,10,'p','R')]]
    manifest={'lots':lots,'machines':[{'id':1,'family':'F','group':'G'},
              {'id':2,'family':'F','group':'G'},{'id':3,'family':'Delay_32','group':'Delay_32'},
              {'id':4,'family':'idle','group':'G'}],
              'routes':{'R':[{'family':'F','batch_max':2}],'V':[{'family':'Delay_32','batch_max':1}]},'horizon':20}
    events=[{'kind':'initial','time':0,'manifest':manifest}]
    for lid in ('a','b','c','v'):
        events.extend([{'kind':'release','time':0,'lot':lid},{'kind':'ready','time':0,'lot':lid,'step':1}])
    events.extend([
        {'kind':'plan_committed','time':0,'plan':{'opaque_data':[{'tasks':[1,2,3]}]}},
        {'kind':'dispatch','time':1,'machine':3,'job':0,'lots':['v'],'steps':[1],
         'process_end':3,'machine_ready':3,'setup_seconds':0},
        {'kind':'dispatch','time':2,'machine':1,'job':1,'lots':['a','b'],'steps':[1,1],
         'process_end':8,'machine_ready':7,'setup_seconds':2},
        {'kind':'lot_complete','time':3,'lot':'v'},
        {'kind':'dispatch','time':4,'machine':2,'job':2,'lots':['c'],'steps':[1],
         'process_end':6,'machine_ready':5,'setup_seconds':1},
        {'kind':'downtime','time':5,'machine':1,'duration':4,'blocked_until':9,'machine_ready':12,'affected_jobs':[1]},
        {'kind':'lot_complete','time':6,'lot':'c'},
        {'kind':'downtime','time':7,'machine':1,'duration':2,'blocked_until':11,'machine_ready':14,'affected_jobs':[1]},
        {'kind':'downtime','time':8,'machine':2,'duration':2,'blocked_until':10,'machine_ready':10,'affected_jobs':[]},
        {'kind':'snapshot_loaded','time':9,'prefix_event_count':18},
        {'kind':'release','time':10,'lot':'d'},{'kind':'ready','time':10,'lot':'d','step':1},
        {'kind':'lot_complete','time':15,'lot':'a'},{'kind':'lot_complete','time':15,'lot':'b'},
        {'kind':'dispatch','time':20,'machine':2,'job':3,'lots':['d'],'steps':[1],
         'process_end':23,'machine_ready':23,'setup_seconds':0},
        {'kind':'terminal','time':20},
    ])
    for i,e in enumerate(events):
        if e['kind']=='snapshot_loaded':e['prefix_event_count']=i
    return events


class StreamMetricTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'trace.jsonl'

    def write(self,events):
        with self.path.open('w') as stream:
            for event in events:stream.write(json.dumps(event)+'\n\n')
        return self.path

    def parity(self,events,**kwargs):
        self.write(events)
        expected=legacy(events,**kwargs);actual=stream_metrics.compute_metrics(self.path,**kwargs)
        # Canonical serialization also distinguishes missing keys, null and int/float.
        self.assertEqual(json.dumps(actual,sort_keys=True),json.dumps(expected,sort_keys=True))
        return actual

    def test_all_lot_metrics_and_subwindows_exact(self):
        for start,end in [(0,10),(5,10),(6,7),(7,10),(0,6)]:
            for details in (False,True):
                with self.subTest(start=start,end=end,details=details):
                    self.parity(metric_events(),window_start=start,window_end=end,include_lot_details=details,
                                priority_weights={'10':1.5,'20':2.25,'30':4})
        self.parity([e for e in metric_events() if e['kind']!='lot_complete'])

    def test_machine_batch_queue_downtime_and_boundary_metrics_exact(self):
        for start,end in [(0,20),(5,11),(6,10),(10,20),(0,6)]:
            with self.subTest(start=start,end=end):
                r=self.parity(physical_events(),window_start=start,window_end=end,include_lot_details=True)
                self.assertEqual(set(r['production_family_statistics']),{'F','idle'})
        r=self.parity(physical_events())
        self.assertEqual(r['batch_fill_ratios'],[1.0,0.5])
        self.assertEqual(r['production_family_statistics']['F']['dispatches'],2)
        self.assertEqual(r['setup_loss_seconds'],3.0)
        self.assertEqual(r['production_family_statistics']['idle']['reserved_observed_fraction'],0.0)

    def test_full_file_last_terminal_and_partial_trace(self):
        self.assertTrue(self.parity(metric_events())['completed_declared_window'])
        self.assertFalse(self.parity(metric_events()[:-1])['completed_declared_window'])
        self.assertFalse(self.parity(metric_events()+[{'kind':'time_advance','time':10}])['completed_declared_window'])
        self.assertFalse(self.parity(metric_events(),window_end=8)['completed_declared_window'])

    def test_fractional_queue_sums_use_only_the_declared_float_tolerance(self):
        manifest={'horizon':60,'machines':[{'id':1,'family':'F','group':'G'}],
                  'routes':{'R':[{'family':'F','batch_max':1}]},
                  'lots':[{'id':str(i),'route':'R','release':0,'due':20,'priority':10,'pieces':25,'part':'p'} for i in range(500)]}
        events=[{'kind':'initial','time':0,'manifest':manifest}]
        for i in range(500):
            events.extend([{'kind':'release','time':0,'lot':str(i)},
                           {'kind':'ready','time':0,'lot':str(i),'step':1}])
        for i in range(500):
            t=(i+1)/10
            events.append({'kind':'dispatch','time':t,'machine':1,'job':i,'lots':[str(i)],'steps':[1],
                           'process_end':t+0.05,'machine_ready':t+0.05,'setup_seconds':0.013})
        events.append({'kind':'terminal','time':60})
        expected=legacy(events,window_start=0.33,window_end=59.9)
        actual=stream_metrics.compute_metrics(self.write(events),window_start=0.33,window_end=59.9)
        field='queue_wait_lot_seconds'
        a=actual['production_family_statistics']['F'][field]
        b=expected['production_family_statistics']['F'][field]
        self.assertTrue(math.isclose(a,b,rel_tol=stream_metrics.QUEUE_SUM_REL_TOLERANCE,
                                    abs_tol=stream_metrics.QUEUE_SUM_ABS_TOLERANCE))
        actual['production_family_statistics']['F'][field]=b
        self.assertEqual(json.dumps(actual,sort_keys=True),json.dumps(expected,sort_keys=True))

    def test_snapshot_prefix_verified_even_after_requested_endpoint(self):
        events=physical_events();self.parity(events,window_end=6)
        for change in ('count','initial_time','root'):
            bad=deepcopy(events)
            if change=='count':next(e for e in bad if e['kind']=='snapshot_loaded')['prefix_event_count']+=1
            elif change=='initial_time':bad[0]['time']=1
            else:bad=bad[18:]
            self.write(bad)
            with self.subTest(change=change):
                with self.assertRaises(ValueError):legacy(bad,window_end=6)
                with self.assertRaises(ValueError):stream_metrics.compute_metrics(self.path,window_end=6)

    def test_rejection_parity_lot_and_event_failures(self):
        cases=[]
        cases.append([])
        for extra in [{'kind':'release','time':6,'lot':'new'},{'kind':'release','time':6,'lot':'unknown'},
                      {'kind':'lot_complete','time':6,'lot':'future'},
                      {'kind':'ready','time':6,'lot':'old','step':1}]:
            events=metric_events();events.insert(4,extra)
            if extra['kind']=='ready':events.insert(4,deepcopy(extra))
            cases.append(events)
        events=metric_events();events.insert(5,deepcopy(events[4]));cases.append(events)
        events=metric_events();events[3]['time']=-1;cases.append(events)
        events=metric_events();events[0]['manifest']['lots'].append(deepcopy(events[0]['manifest']['lots'][0]));cases.append(events)
        for bad_time in (True,float('nan'),float('inf')):
            events=metric_events();events[-1]['time']=bad_time;cases.append(events)
        for index,events in enumerate(cases):
            self.write(events)
            with self.subTest(case=index):
                with self.assertRaises(ValueError):legacy(events)
                with self.assertRaises(ValueError):stream_metrics.compute_metrics(self.path)
        for kwargs in ({'window_end':11},{'window_start':-1},{'window_start':10},
                       {'priority_weights':{10:1}}, {'priority_weights':{10:False,20:1,30:1}},
                       {'priority_weights':{10:0,20:1,30:1}}):
            self.write(metric_events())
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):legacy(metric_events(),**kwargs)
                with self.assertRaises(ValueError):stream_metrics.compute_metrics(self.path,**kwargs)

    def test_rejection_parity_dispatch_and_downtime_failures(self):
        for change in ('not_ready','duplicate_job','unknown_affected'):
            events=physical_events()
            if change=='not_ready':next(e for e in events if e['kind']=='dispatch')['lots']=['future']
            elif change=='duplicate_job':[e for e in events if e['kind']=='dispatch'][1]['job']=0
            else:next(e for e in events if e['kind']=='downtime')['affected_jobs']=[999]
            self.write(events)
            with self.subTest(change=change):
                with self.assertRaises(ValueError):legacy(events)
                with self.assertRaises(ValueError):stream_metrics.compute_metrics(self.path)

    def test_two_passes_no_read_text_or_legacy_compute_and_no_file_mutation(self):
        self.write(physical_events());before=hashlib.sha256(self.path.read_bytes()).digest()
        original=stream_metrics._events;passes=[]
        def counted(path,hasher):
            passes.append(path)
            yield from original(path,hasher)
        with (patch.object(stream_metrics,'_events',counted),
              patch.object(Path,'read_text',side_effect=AssertionError('whole-file read')),
              patch('src.smt_fullfab.metrics.read_events',side_effect=AssertionError('legacy event retention'))):
            stream_metrics.compute_metrics(self.path)
        self.assertEqual(passes,[self.path,self.path])
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).digest(),before)

    def test_changed_file_between_passes_rejected(self):
        self.write(metric_events());original=stream_metrics._events;calls=0
        def changed(path,hasher):
            nonlocal calls
            calls+=1
            yield from original(path,hasher)
            if calls==1:
                with path.open('a') as stream:stream.write('{"kind":"time_advance","time":10}\n')
        with patch.object(stream_metrics,'_events',changed):
            with self.assertRaisesRegex(ValueError,'changed between'):stream_metrics.compute_metrics(self.path)

    def test_json_suffix_errors_and_input_path_contract(self):
        self.write(metric_events())
        with self.path.open('a') as stream:stream.write('{bad-json}\n')
        with self.assertRaises(ValueError):stream_metrics.compute_metrics(self.path,window_end=6)
        self.write([])
        with self.assertRaises(ValueError):stream_metrics.compute_metrics(self.path)
        with self.assertRaises(TypeError):stream_metrics.compute_metrics(metric_events())

    def test_ignored_plan_history_not_retained(self):
        line=json.dumps({'kind':'plan_committed','time':0,'plan':{'tasks':list(range(500))}})+'\n'
        peaks=[]
        for repeats in (32,2048):
            with self.path.open('w') as stream:
                stream.write(json.dumps(metric_events()[0])+'\n')
                for _ in range(repeats):stream.write(line)
                stream.write('{"kind":"terminal","time":10}\n')
            tracemalloc.start()
            result=stream_metrics.compute_metrics(self.path)
            _,peak=tracemalloc.get_traced_memory();tracemalloc.stop();peaks.append(peak)
            self.assertEqual(result['throughput_lots'],0)
        self.assertLess(peaks[1],peaks[0]+250000)


if __name__=='__main__':unittest.main()
