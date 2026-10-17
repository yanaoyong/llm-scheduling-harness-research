"""Small real-shape state fixtures; never construct a factory or advance time."""
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab import environment as legacy
from src.smt_fullfab import stream_snapshot as streamed


def fixture():
    env = legacy.FullFabEnvironment.__new__(legacy.FullFabEnvironment)
    env.seed=1701;env.horizon=28800.;env.t=7.5;env.seq=4;env.dispatch_id=2
    env.decisions=2;env.releases=2;env.completed=['w0'];env.finished=False;env.wait_until=8.
    env.lots={'w0':{'id':'w0','status':'done','step':2,'visits':{'1':1,'2':1},'dedications':{}},
              'w1':{'id':'w1','status':'processing','step':1,'visits':{'1':1,'2':2},'dedications':{'family':10}}}
    env.machine_state={10:{'ready':8.,'down_until':0.,'setup':'组 α','min_left':1,'min_setup':'组 α','last_token':2},
                       2:{'ready':-0.0,'down_until':9.,'setup':'','min_left':0,'min_setup':'','last_token':0}}
    env.jobs={2:{'lots':['w1'],'machine':10,'lot_end':8.,'operation':('part',2,'etch'),'slot_end':7.}}
    env.calendars={'10':[(1.,2.),(10.,11.)]};env.pm_counters=defaultdict(list,{10:[2,3],2:[]})
    env.queue_area=12.25;env.last_area_t=7.5
    env.manifest={'data_hashes':{'route.txt':'a'*64,'tool.txt':'b'*64},'fullfab_version':legacy.VERSION,
                  'machines':[{'id':10,'family':'组 α'},{'id':2,'family':'F'}], 'lots':[{'id':'w1'}]}
    env.plan={'version':'p1','created_at':7.5,'scope':[2,10],'freeze_until':8.,'valid_until':20.,
              'reason':'明确计划 😀','tasks':[{'id':'t1','machine':10,'lot_ids':['w1'],'steps':[2],'visits':[2],
                                          'not_before':7.5,'expected_end':8.,'sequence':0}],
              'holds':[{'machine':2,'until':9.,'reason':'停机'}]}
    env.observation_start=0.;env.q=[(9.,4,'down',{'machine':2}),(8.,3,'complete',2)]
    env.waiting=defaultdict(set,{'F':{'w2','w3'}});env.processing_by_machine=defaultdict(set,{10:{2},2:set()})
    env.stats=Counter({'dispatches':2,'controlled_dispatches':2});env.executed_tasks={('p1','t1'),('p0','t0')}
    env.plan_versions={'p1','p0'};env.trace=[{'seq':0,'time':0.,'kind':'initial','manifest':deepcopy(env.manifest)},
        {'seq':1,'time':7.5,'kind':'plan_committed','plan':deepcopy(env.plan)},
        {'seq':2,'time':7.5,'kind':'dispatch','machine':10,'lots':['w1'],'plan_version':'p1','plan_task_id':'t1'}]
    return env


class StreamSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.guard=patch.object(legacy.FullFabEnvironment,'__init__',side_effect=AssertionError('no factory initialization'))
        self.guard.start();self.addCleanup(self.guard.stop)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.env=fixture();self.dependencies={'synthetic-physics.py':'c'*64,'synthetic-observation.py':'d'*64}
        self.dep=patch.object(legacy,'snapshot_dependencies',return_value=self.dependencies);self.dep.start();self.addCleanup(self.dep.stop)
    def canonical(self,value):return b''.join(streamed._chunks(value))
    def test_full_document_and_state_hash_equal_legacy_snapshot(self):
        before=deepcopy(self.env.__dict__)
        old=self.root/'legacy.json';new=self.root/'stream.json'
        old_hash=self.env.snapshot(old);new_hash=streamed.write_snapshot(self.env,new)
        old_value=json.loads(old.read_text());new_value=json.loads(new.read_text())
        self.assertEqual(new_value,old_value);self.assertEqual(new_hash,old_hash)
        self.assertEqual(legacy.digest(new_value['state']),new_hash)
        self.assertEqual(self.env.__dict__,before)
        self.assertEqual(new_value['implementation_sha256'],self.dependencies)
    def test_legacy_restore_reads_stream_file_and_restores_fields(self):
        path=self.root/'stream.json';expected_hash=streamed.write_snapshot(self.env,path)
        def constructor(env,*,seed,window_seconds,data_dir):
            env.manifest={'data_hashes':deepcopy(self.env.manifest['data_hashes'])}
        with patch.object(legacy.FullFabEnvironment,'__init__',constructor), \
             patch.object(legacy.FullFabEnvironment,'_emit') as emit:
            restored=legacy.FullFabEnvironment.from_snapshot(path,data_dir='synthetic-not-loaded')
        self.assertEqual(restored.machine_state,self.env.machine_state)
        for field in ('seed','horizon','t','seq','dispatch_id','decisions','releases','completed','finished','wait_until',
                      'lots','manifest','plan','observation_start','queue_area','last_area_t'):
            self.assertEqual(getattr(restored,field),getattr(self.env,field),field)
        self.assertEqual(restored.jobs[2]['operation'],['part',2,'etch'])
        self.assertEqual(restored.waiting,self.env.waiting);self.assertEqual(restored.processing_by_machine,self.env.processing_by_machine)
        self.assertEqual(restored.pm_counters,self.env.pm_counters);self.assertEqual(restored.stats,self.env.stats)
        self.assertEqual(restored.executed_tasks,self.env.executed_tasks);self.assertEqual(restored.plan_versions,self.env.plan_versions)
        self.assertEqual(restored.q,sorted(self.env.q));self.assertEqual(restored.trace,self.env.trace)
        self.assertIsNone(restored.active_task);self.assertIsNone(restored.trace_path)
        emit.assert_called_once_with('snapshot_loaded',snapshot_sha256=expected_hash,prefix_event_count=len(self.env.trace))
    def test_integer_keys_sort_by_json_string_and_alias_last_value_wins(self):
        value={2:'two',10:'ten',1:'old-int','1':'new-string',True:'python-existing-int-key',
               None:'old-none','null':'new-null',False:'old-false','false':'new-false',1.5:'old-float','1.5':'new-float'}
        normalized=json.loads(json.dumps(value));expected=json.dumps(normalized,sort_keys=True,separators=(',',':')).encode()
        actual=self.canonical(value);self.assertEqual(actual,expected);self.assertLess(actual.index(b'"10"'),actual.index(b'"2"'))
        reverse={'1':'old-string',1:'new-int','true':'old-string-true',True:'new-bool'}
        self.assertEqual(self.canonical(reverse),json.dumps(json.loads(json.dumps(reverse)),sort_keys=True,separators=(',',':')).encode())
    def test_nested_tuple_unicode_escaping_and_finite_float_semantics(self):
        value={'中文😀':'a\\b\n\t"\u2028', 'v':(True,None,False,-0.0,1e-7,1e20,1.2345678901234567),
               'nested':[{False:{2:None,10:'x'},None:'null-key',1e-20:'float-key'}]}
        self.assertEqual(self.canonical(value),json.dumps(json.loads(json.dumps(value)),sort_keys=True,separators=(',',':')).encode())
        self.assertEqual(hashlib.sha256(self.canonical(value)).hexdigest(),legacy.digest(value))
    def test_unicode_surrogate_pair_key_aliases_normalize_before_collision_and_sort(self):
        # The legacy JSON round trip merges these initially distinct Python keys.
        for value in ({'\ud83d\ude00':'old','😀':'new','\ue000':1},
                      {'😀':'old','\ud83d\ude00':'new','\ue000':1},
                      {True:'old-bool','true':'new-string',False:False,None:None},
                      {'true':'old-string',True:'new-bool'},
                      {'lone':'\ud800','pairs':'\ud800\udc00'}):
            with self.subTest(value=repr(value)):
                expected=json.dumps(json.loads(json.dumps(value)),sort_keys=True,separators=(',',':')).encode()
                self.assertEqual(self.canonical(value),expected)
    def test_mid_document_write_failure_keeps_partial_file_and_never_reuses_path(self):
        self.env.trace*=2000;path=self.root/'partial.json';original=Path.open
        class FailingStream:
            def __init__(self,stream):self.stream=stream;self.writes=0
            def __enter__(self):self.stream.__enter__();return self
            def __exit__(self,*args):return self.stream.__exit__(*args)
            def write(self,raw):
                self.writes+=1
                if self.writes>1:raise OSError('synthetic second-chunk failure')
                return self.stream.write(raw)
            def flush(self):return self.stream.flush()
            def fileno(self):return self.stream.fileno()
        def opening(target,*args,**kwargs):
            stream=original(target,*args,**kwargs)
            return FailingStream(stream) if target==path and args==('xb',) else stream
        with patch.object(Path,'open',opening):
            with self.assertRaisesRegex(OSError,'second-chunk failure'):streamed.write_snapshot(self.env,path)
        self.assertGreater(path.stat().st_size,0)
        with self.assertRaises(json.JSONDecodeError):json.loads(path.read_bytes())
        before=path.read_bytes()
        with self.assertRaises(FileExistsError):streamed.write_snapshot(self.env,path)
        self.assertEqual(path.read_bytes(),before)
    def test_no_deepcopy_or_whole_json_dumps_even_for_history(self):
        self.env.trace*=2000  # Artificial references, not a factory run or memory-capacity claim.
        state=streamed._state_view(self.env);self.assertIs(state['trace'],self.env.trace);self.assertIs(state['lots'],self.env.lots)
        with patch('copy.deepcopy',side_effect=AssertionError('deepcopy forbidden')), \
             patch.object(legacy,'deepcopy',side_effect=AssertionError('legacy deepcopy forbidden')), \
             patch('json.dumps',side_effect=AssertionError('whole JSON dumps forbidden')), \
             patch('json.dump',side_effect=AssertionError('whole JSON dump forbidden')):
            result=streamed.write_snapshot(self.env,self.root/'stream.json')
        saved=json.loads((self.root/'stream.json').read_text());self.assertEqual(saved['state_sha256'],result)
        self.assertEqual(len(saved['state']['trace']),6000)
    def test_exclusive_create_never_overwrites_existing_or_symlink_target(self):
        path=self.root/'exists.json';path.write_bytes(b'preserve original')
        with self.assertRaises(FileExistsError):streamed.write_snapshot(self.env,path)
        self.assertEqual(path.read_bytes(),b'preserve original')
        link=self.root/'link.json';link.symlink_to(path)
        with self.assertRaises(FileExistsError):streamed.write_snapshot(self.env,link)
        self.assertEqual(path.read_bytes(),b'preserve original')
    def test_invalid_values_fail_and_retain_created_file(self):
        bad=[float('nan'),float('inf'),float('-inf'),object(),{('tuple','key'):1},{'set':{1,2}}]
        for index,value in enumerate(bad):
            with self.subTest(value=type(value).__name__):
                self.env.plan={'bad':value};path=self.root/f'failed-{index}.json'
                with self.assertRaises((TypeError,ValueError)):streamed.write_snapshot(self.env,path)
                self.assertTrue(path.exists())
                with self.assertRaises(FileExistsError):streamed.write_snapshot(self.env,path)
    def test_cycles_and_shadowed_invalid_values_are_not_hidden(self):
        cyclic=[];cyclic.append(cyclic)
        for value in (cyclic,{1:object(),'1':'replacement'},{1:{('invalid',):0},'1':None}):
            with self.subTest(kind=type(value).__name__),self.assertRaises((TypeError,ValueError)):
                self.canonical(value)
    def test_success_flushes_and_fsyncs_and_failure_preserves_full_written_bytes(self):
        path=self.root/'fsync-failed.json'
        with patch.object(streamed.os,'fsync',side_effect=OSError('synthetic fsync failure')) as sync:
            with self.assertRaisesRegex(OSError,'synthetic fsync failure'):streamed.write_snapshot(self.env,path)
        sync.assert_called_once();saved=json.loads(path.read_bytes());self.assertEqual(saved['state_sha256'],legacy.digest(saved['state']))
        with self.assertRaises(FileExistsError):streamed.write_snapshot(self.env,path)
    def test_large_history_is_emitted_as_bounded_chunks_not_one_document(self):
        values=[{'i':i,'name':'消息'} for i in range(4000)]
        sizes=[];hasher=hashlib.sha256()
        for chunk in streamed._chunks(values):sizes.append(len(chunk));hasher.update(chunk)
        self.assertGreater(len(sizes),1);self.assertLessEqual(max(sizes),streamed.BUFFER_BYTES)
        self.assertEqual(hasher.hexdigest(),legacy.digest(values))


    def inject_write_count(self, stage, mode):
        path=self.root/f'write-{stage}-{mode}.json';original=Path.open;calls=[]
        class ShortWriter:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):self.stream.__enter__();return self
            def __exit__(self,*args):return self.stream.__exit__(*args)
            def write(self,raw):
                target=(raw==b'\n') if stage=='newline' else raw!=b'\n'
                calls.append((len(raw),target))
                if not target:return self.stream.write(raw)
                if mode=='partial':
                    count=len(raw)-1;self.stream.write(raw[:count]);return count
                if mode=='zero':return 0
                if mode=='none':return None
                if mode=='bool':self.stream.write(raw);return True
                if mode=='float':self.stream.write(raw);return float(len(raw))
                if mode=='overcount':self.stream.write(raw);return len(raw)+1
                raise AssertionError('unknown synthetic write mode')
            def flush(self):return self.stream.flush()
            def fileno(self):return self.stream.fileno()
        def opening(target,*args,**kwargs):
            stream=original(target,*args,**kwargs)
            return ShortWriter(stream) if target==path and args==('xb',) else stream
        with patch.object(Path,'open',opening),patch.object(streamed.os,'fsync') as sync:
            with self.assertRaisesRegex(OSError,'byte count'):streamed.write_snapshot(self.env,path)
        sync.assert_not_called();self.assertTrue(path.exists())
        self.assertEqual(sum(target for _,target in calls),1)  # No retry after the first invalid count.
        self.assertEqual(calls[-1][1],True)
        before=path.read_bytes()
        with self.assertRaises(FileExistsError):streamed.write_snapshot(self.env,path)
        self.assertEqual(path.read_bytes(),before)
        return path
    def test_short_data_chunk_counts_zero_none_and_partial_fail_without_retry(self):
        for mode in ('zero','none','partial'):
            with self.subTest(mode=mode):self.inject_write_count('data',mode)
    def test_final_newline_short_counts_zero_none_and_partial_fail_without_retry(self):
        for mode in ('zero','none','partial'):
            with self.subTest(mode=mode):
                path=self.inject_write_count('newline',mode)
                # Complete JSON without its required newline is still a failed write.
                self.assertFalse(path.read_bytes().endswith(b'\n'))
                self.assertEqual(json.loads(path.read_bytes())['schema'],'smt-fullfab-snapshot-1')
    def test_write_count_must_be_exact_int_not_bool_float_or_overcount(self):
        for stage in ('data','newline'):
            for mode in ('bool','float','overcount'):
                with self.subTest(stage=stage,mode=mode):self.inject_write_count(stage,mode)


if __name__=='__main__':unittest.main()
