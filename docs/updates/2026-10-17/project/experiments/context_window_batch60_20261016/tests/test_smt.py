import copy,json,math,unittest
from pathlib import Path
from src.smt.environment import SmtEnvironment,draw,dist_spec
from src.smt.audit import audit_trace,sampled
from src.smt.optimizer import solve_action
ROOT=Path(__file__).resolve().parents[1]

class SmtTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.env=SmtEnvironment(seed=701,window_seconds=28800)
  cls.trace=[json.loads(x) for x in (ROOT/'artifacts/smt_development/official_v2_pilot701/trace.jsonl').read_text().splitlines()]
 def test_official_full_input(self):
  e=self.env
  self.assertEqual(len(e.machines),1313);self.assertEqual(len(e.physical),913);self.assertEqual(e.initial_wip,2156);self.assertEqual(len(e.routes),10);self.assertEqual(sum(len(x.steps) for x in e.routes.values()),4013)
  self.assertTrue(any(l['name']=='SuperHotLot_3' for l in e.lots.values()))
 def test_state_no_future(self):
  s=self.env.state();j=json.dumps(s)
  self.assertNotIn('calendar',j);self.assertNotIn('breakdown',j);self.assertNotIn('rework',j);self.assertNotIn('seed',j);self.assertNotIn('random',j)
 def test_keyed_random_order_independent(self):
  spec={'type':'uniform','m':10,'offset':1};a=draw(701,['lot','x'],spec)
  for i in range(30):draw(701,['unrelated',i],spec)
  self.assertEqual(a,draw(701,['lot','x'],spec));self.assertEqual(a,sampled(701,['lot','x'],spec));self.assertNotEqual(a,draw(702,['lot','x'],spec))
 def test_official_transport_offset_endpoints(self):
  from unittest.mock import patch
  from tools import get_distribution
  d=dist_spec(get_distribution('uniform','min',7.5,2.5))
  self.assertEqual(d,{'type':'uniform','m':450.,'offset':150.})
  with patch('src.smt.environment.random.Random') as mock:
   mock.return_value.uniform.side_effect=lambda a,b:(a,b)
   self.assertEqual(draw(701,['transport'],d),(300.,600.))
  with patch('src.smt.audit.random.Random') as mock:
   mock.return_value.uniform.side_effect=lambda a,b:(a,b)
   self.assertEqual(sampled(701,['transport'],d),(300.,600.))
 def test_constant_crosscheck_upstream(self):
  from tools import ConstantDistribution
  from instance import Instance
  from types import SimpleNamespace
  s=SimpleNamespace(processing_time=ConstantDistribution(10),setup_needed='S',setup_time=3);s.cascading_time=s.processing_time
  lot=SimpleNamespace(actual_step=s,remaining_steps=[],processing_time=0,transport_time=0)
  machine=SimpleNamespace(load_time=2,unload_time=1,cascading=False,current_setup='',min_runs_left=None,utilized_time=0,setuped_time=0)
  inst=SimpleNamespace(setup_min_run={})
  lot_time,machine_time,setup=Instance.get_times(inst,{},[lot],machine)
  self.assertEqual((lot_time,machine_time,setup),(13,13,3))
 def test_full_trace(self):self.assertTrue(audit_trace(self.trace,ROOT/'data/smt/SMT2020_LVHM')['valid'])
 def mutate(self,kind,change):
  es=copy.deepcopy(self.trace);event=next(x for x in es if x['kind']==kind);change(event);return audit_trace(es)
 def test_illegal_machine(self):self.assertFalse(self.mutate('dispatch',lambda e:e.update(machine=10000))['valid'])
 def test_wrong_duration(self):self.assertFalse(self.mutate('dispatch',lambda e:e.update(processing_seconds=e['processing_seconds']+1))['valid'])
 def test_duplicate_lot(self):self.assertFalse(self.mutate('dispatch',lambda e:e['lots'].append(e['lots'][0]))['valid'])
 def test_wrong_batch(self):
  es=copy.deepcopy(self.trace);e=next(x for x in es if x['kind']=='dispatch' and len(x['lots'])>1);e['lots']=e['lots'][:1];e['steps']=e['steps'][:1];e['visits']=e['visits'][:1]
  self.assertFalse(audit_trace(es)['valid'])
 def test_early_completion(self):self.assertFalse(self.mutate('operation_complete',lambda e:e.update(time=e['time']-1))['valid'])
 def test_downtime_delay(self):self.assertFalse(self.mutate('downtime',lambda e:e.update(duration=e['duration']+1))['valid'])
 def test_missing_release(self):
  es=copy.deepcopy(self.trace);es.pop(next(i for i,e in enumerate(es) if e['kind']=='release'))
  for i,e in enumerate(es):e['seq']=i
  self.assertFalse(audit_trace(es)['valid'])
 def test_terminal_conservation(self):self.assertFalse(self.mutate('terminal',lambda e:e['lot_statuses'].pop(next(iter(e['lot_statuses']))))['valid'])
 def test_no_silent_takeover(self):
  es=copy.deepcopy(self.trace);e=next(x for x in es if x['kind']=='dispatch' and x['owner']=='controller');e['owner']='environment';self.assertFalse(audit_trace(es)['valid'])
 def test_invalid_action_atomic(self):
  e=SmtEnvironment(seed=701,window_seconds=28800);before=e.state();n=len(e.trace)
  with self.assertRaises(ValueError):e.apply({'dispatches':[{'machine':790,'lot_ids':['nonexistent']}],'wait_seconds':0})
  self.assertEqual(before,e.state());self.assertEqual(n,len(e.trace))
 def test_batch_capacity_action(self):
  e=SmtEnvironment(seed=701,window_seconds=28800);g=next(g for g in e._groups(790) if len(g)>=5)
  with self.assertRaises(ValueError):e.apply({'dispatches':[{'machine':790,'lot_ids':g[:1]}],'wait_seconds':0})
 def test_idle_breakdown_blocks_dispatch(self):
  e=SmtEnvironment(seed=701,window_seconds=28800);key=next(k for k,c in e.calendars.items() if c['machine']==9 and c['breakdown']);self.assertTrue(e.eligible(9));e._calendar({'key':key,'n':0});self.assertFalse(e.eligible(9));self.assertGreater(e.machine_state[9]['down_until'],0)
 def test_active_breakdown_delays_material(self):
  e=SmtEnvironment(seed=701,window_seconds=28800);lid=e.eligible(9)[0];e._dispatch(9,[lid],'controller');old=e.jobs[0]['lot_end'];key=next(k for k,c in e.calendars.items() if c['machine']==9 and c['breakdown']);e._calendar({'key':key,'n':0});duration=e.trace[-1]['duration'];self.assertAlmostEqual(e.jobs[0]['lot_end'],old+duration);self.assertGreater(e.jobs[0]['token'],0)
 def test_hand_calculated_batch_trace(self):
  step={'step':1,'family':'G','name':'heat','batch_min':2,'batch_max':3,'batching':True,'processing':{'type':'constant','c':10},'cadence':{'type':'constant','c':10},'cascading':False,'setup':'S','setup_time':3,'sampling_percent':100,'rework_percent':0,'rework_step':'','dedicate_for':None,'transport':{'type':'constant','c':0}}
  lot=lambda lid:{'id':lid,'name':lid,'part':'p','route':'r','priority':10,'pieces':25,'release':0,'due':10,'step':0,'initial':False}
  manifest={'version':'smt-adapter-v2','seed':701,'horizon':20,'controlled_machine_ids':[0],'initial_wip':0,'physical_machines':1,'virtual_delay_resources':0,'routes':{'r':[step]},'machines':[{'id':0,'family':'G','group':'production','load':2,'unload':1,'cascading':False}],'lots':[lot('x'),lot('y')],'setups':[],'min_runs':{},'calendars':{},'piece_pm':{},'data_hashes':{}}
  events=[]
  def emit(t,kind,**data):events.append(dict(seq=len(events),time=t,kind=kind,**data))
  emit(0,'initial',manifest=manifest)
  for lid in ['x','y']:emit(0,'release',lot=lid,initial=False);emit(0,'ready',lot=lid,step=1,visit=1)
  emit(0,'action',decision=0,action={'dispatches':[{'machine':0,'lot_ids':['x','y']}],'wait_seconds':0})
  emit(0,'dispatch',job=0,machine=0,lots=['x','y'],steps=[1,1],visits=[1,1],owner='controller',setup_before='',setup_after='S',setup_seconds=3,processing_seconds=10,cadence_seconds=10,transport_seconds=0,process_end=16,lot_end=16,machine_ready=16,piece_pm=[],min_runs_left=0,processing_key=['processing',[['x',1,1],['y',1,1]]])
  for lid in ['x','y']:emit(16,'operation_complete',job=0,lot=lid,step=1);emit(16,'lot_complete',lot=lid)
  emit(20,'terminal',metrics={},lot_statuses={'x':'done','y':'done'})
  result=audit_trace(events);self.assertTrue(result['valid'],result['errors']);self.assertEqual(result['metrics']['throughput_wafers'],50);self.assertEqual(result['metrics']['mean_cycle_seconds_completed'],16);self.assertEqual(result['metrics']['total_tardiness_completed_seconds'],12);self.assertEqual(result['metrics']['controlled_batch_fill_ratios'],[2/3])
  # Same hand example with a 5-second post-process piece PM: lots finish at16,
  # machine remains reserved until21, including the uncompleted maintenance tail.
  pm=copy.deepcopy(events);pm[0]['manifest']['piece_pm']={'0':[{'key':'counter0','remaining':25,'repeat':100,'length':{'type':'constant','c':5},'occurrence':0}]}
  de=next(x for x in pm if x['kind']=='dispatch');de['piece_pm']=[{'key':'counter0','duration':5,'occurrence':0}];de['machine_ready']=21;de['setup_after']=''
  self.assertTrue(audit_trace(pm)['valid'])
  # Force rework with probability100 after the operation; both lots return tostep1.
  rw=copy.deepcopy(events);rw[0]['manifest']['routes']['r'][0]['rework_percent']=100;rw[0]['manifest']['routes']['r'][0]['rework_step']=1
  revised=[]
  for ev in rw:
   if ev['kind']=='lot_complete':continue
   if ev['kind']=='terminal':ev['lot_statuses']={'x':'waiting','y':'waiting'}
   revised.append(ev)
   if ev['kind']=='operation_complete':
    lid=ev['lot'];value=sampled(701,['rework',lid,1,1],{'type':'uniform','m':50,'offset':50});revised.append({'time':16,'kind':'rework','lot':lid,'step':1,'target':1,'visit':1,'draw':value});revised.append({'time':16,'kind':'ready','lot':lid,'step':1,'visit':2})
  for i,ev in enumerate(revised):ev['seq']=i
  checked=audit_trace(revised);self.assertTrue(checked['valid'],checked['errors']);self.assertEqual(checked['metrics']['terminal_wip_lots'],2)
  revised.pop(next(i for i,e in enumerate(revised) if e['kind']=='rework'))
  for i,ev in enumerate(revised):ev['seq']=i
  self.assertFalse(audit_trace(revised)['valid'])
 def test_unexecuted_declared_action(self):
  es=copy.deepcopy(self.trace);next(x for x in es if x['kind']=='action' and x['decision']==1)['action']['dispatches'].append({'machine':790,'lot_ids':['w999999-not-a-lot']})
  r=audit_trace(es,ROOT/'data/smt/SMT2020_LVHM');self.assertFalse(r['valid']);self.assertTrue(any('unexecuted' in e for e in r['errors']))
 def test_manifest_source_binding(self):
  from src.smt.source_check import verify_source
  m=copy.deepcopy(self.trace[0]['manifest']);m['physical_machines']=-17;m['routes']['route_1.txt'][0]['batch_min']=0
  errors=verify_source(m,ROOT/'data/smt/SMT2020_LVHM');self.assertTrue(any('physical machine' in x for x in errors));self.assertTrue(any('routes/' in x for x in errors))
 def test_piece_pm_after_processing_and_rework_runtime(self):
  e=SmtEnvironment(seed=701,window_seconds=28800);lid=e.eligible(9)[0];l=e.lots[lid];step=e._step(l);step.rework_percent=100;step.rework_step=step.order
  e.pm_counters[9]=[{'key':'manual_counter','remaining':25,'repeat':100,'length':{'type':'constant','c':5},'occurrence':0}]
  e._dispatch(9,[lid],'controller');job=e.jobs[0];self.assertEqual(e.pm_counters[9][0]['remaining'],100);self.assertAlmostEqual(e.machine_state[9]['ready'],job['process_end']+5)
  end=job['lot_end'];e._events_to(end);self.assertEqual(l['status'],'waiting');self.assertEqual(e._step(l).order,step.order);self.assertEqual(l['visits'][str(step.order)],2)
 def test_cascading_occupancy_guard(self):
  e=SmtEnvironment(seed=701,window_seconds=28800);mid=next(m.idx for m in e.machines if m.cascading and e.eligible(m.idx));e.processing_by_machine[mid].update({123456,234567});self.assertEqual(e.eligible(mid),[])
 def test_asymmetric_cascading_rejected(self):
  from tools import ConstantDistribution
  e=SmtEnvironment(seed=701,window_seconds=28800)
  rn=next(rn for rn,rows in e.files.items() if rn.startswith('route_') and any(isinstance(r['BatchInterval'],(int,float)) for r in rows))
  idx=next(i for i,r in enumerate(e.files[rn]) if isinstance(r['BatchInterval'],(int,float)))
  e.routes[rn].steps[idx].processing_time=ConstantDistribution(10000000)
  with self.assertRaisesRegex(ValueError,'slot2 blocking'):e._check_cascading_domain()
 def test_closedloop_both_machine_types(self):
  ds=[x for x in self.trace if x['kind']=='dispatch' and x['owner']=='controller'];self.assertEqual({x['machine'] for x in ds},{9,790});self.assertGreater(sum(x['machine']==790 for x in ds),1);self.assertGreater(sum(x['machine']==9 for x in ds),1);self.assertEqual(self.trace[-1]['time'],28800)
if __name__=='__main__':unittest.main()
