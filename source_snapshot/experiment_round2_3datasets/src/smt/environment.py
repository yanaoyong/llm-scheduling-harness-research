"""Explicitly patched SMT2020 DES using pinned PySCFabSim data classes.

All official LV/HM routes, resources, WIP, release streams and calendars are loaded.
Only selected physical machine IDs are controlled. No future event is in state().
The event loop is reimplemented to make downtime, traceability and keyed randomness
consistent. This is adapter-v2, NOT an unmodified upstream reproduction.
"""
from __future__ import annotations
from collections import Counter,defaultdict
from pathlib import Path
import hashlib,heapq,json,math,random,sys,time
ROOT=Path(__file__).resolve().parents[2]
VENDOR=ROOT/'vendor/PySCFabSim-revised'
sys.path.insert(0,str(VENDOR/'simulation'))
from read import read_all
from classes import Machine,FileRoute
from tools import get_interval,get_distribution,date_time_parse

VERSION='smt-adapter-v2'
def dist_spec(d):
    if hasattr(d,'c'):return {'type':'constant','c':d.c}
    if hasattr(d,'m'):return {'type':'uniform','m':d.m,'offset':d.l}
    if hasattr(d,'p'):return {'type':'exponential','mean':d.p}
    raise TypeError(type(d))
def draw(seed,key,spec):
    h=hashlib.sha256(json.dumps([seed,key],separators=(',',':')).encode()).digest()
    r=random.Random(int.from_bytes(h,'big'))
    if spec['type']=='constant':return spec['c']
    if spec['type']=='uniform':return r.uniform(spec['m']-spec['offset'],spec['m']+spec['offset'])
    return r.expovariate(1/spec['mean'])
def average(spec):return spec.get('c',spec.get('m',spec.get('mean')))
def route_key(s,part):return (part,s.order,s.step_name)

class SmtEnvironment:
    def __init__(self,seed=701,window_seconds=28800,controlled_machine_ids=(790,9),data_dir=None,trace_path=None,max_decisions=16):
        self.seed=int(seed);self.horizon=float(window_seconds);self.controlled=set(controlled_machine_ids);self.max_decisions=max_decisions
        self.data_dir=Path(data_dir) if data_dir else ROOT/'data/smt/SMT2020_LVHM'
        if not self.data_dir.exists():raise FileNotFoundError('Run scripts/acquire_smt.py and extract official Dataset2 LVHM; simulator copy is not the official input.')
        self.files=read_all(str(self.data_dir),preprocessors=[])
        self.t=0.;self.trace=[];self.trace_path=Path(trace_path) if trace_path else None
        if self.trace_path and self.trace_path.exists():raise FileExistsError(self.trace_path)
        if self.trace_path:self.trace_path.parent.mkdir(parents=True,exist_ok=True)
        self.q=[];self.seq=0;self.dispatch_id=0;self.decisions=0;self.releases=0;self.completed=[];self.finished=False;self.wait_until=0.
        self.lots={};self.machine_state={};self.waiting=defaultdict(set);self.jobs={};self.processing_by_machine=defaultdict(set);self.calendars={};self.pm_counters=defaultdict(list)
        self.stats=Counter();self.queue_area=0.;self.last_area_t=0.;self.started_wall=time.perf_counter()
        self.machines=[]
        for row in self.files['tool.txt.1l']:
            for _ in range(int(row['STNQTY'])):
                m=Machine(len(self.machines),row,1);self.machines.append(m)
                self.machine_state[m.idx]={'ready':0.,'down_until':0.,'setup':'','min_left':0,'min_setup':'','last_token':0}
        self.physical={m.idx for m in self.machines if m.group!='Delay_32'}
        if not self.controlled <= self.physical:raise ValueError('Control IDs must be physical machines')
        locations={m.family:m.loc for m in self.machines}
        self.routes={name:FileRoute(name,25,rows,False) for name,rows in self.files.items() if name.startswith('route_') and name.endswith('.txt')}
        transport={(r['FROMLOC'],r['TOLOC']):get_distribution(r['DDIST'],r['DUNITS'],r['DTIME'],r['DTIME2']) for r in self.files['fromto.txt']}
        for route in self.routes.values():
            for i,s in enumerate(route.steps):
                s.transport_time=transport.get((locations[route.steps[i-1].family],locations[s.family])) if i else None
        self._check_cascading_domain()
        self.parts={p['PART']:p['ROUTEFILE'] for p in self.files['part.txt']}
        self.setups={(r['CURSETUP'],r['NEWSETUP']):get_interval(r['STIME'],r['STUNITS']) for r in self.files['setup.txt']}
        self.min_runs={r['SETUP']:int(r['MINRUN']) for r in self.files['setupgrp.txt']}
        self.origin=min(date_time_parse(o['START']) for o in self.files['order.txt'])
        self.initial_wip=len(self.files['WIP.txt'])
        lead={o['LOT']:(date_time_parse(o['DUE'])-date_time_parse(o['START'])).total_seconds() for o in self.files['order.txt']}
        for i,w in enumerate(self.files['WIP.txt']):
            name=w['LOT'][5:].rsplit('_',1)[0] if w['LOT'].startswith('Init_') else w['LOT']
            due=(date_time_parse(w['DUE'])-self.origin).total_seconds()
            release=due-lead[name]
            self._new_lot('w'+str(i),w,release,due,int(w['CURSTEP'])-1,True)
        for oi,o in enumerate(self.files['order.txt']):
            interval=get_interval(o['REPEAT'],o['RUNITS']);start=(date_time_parse(o['START'])-self.origin).total_seconds()
            deadline=(date_time_parse(o['DUE'])-date_time_parse(o['START'])).total_seconds()
            for n in range(min(int(o['RPT#']),int(max(0,self.horizon-start)/interval)+1)):
                for k in range(int(o['LOTSPERRPT'])):
                    rel=start+n*interval
                    if rel<self.horizon:self._new_lot(f'o{oi}r{n}l{k}',o,rel,rel+deadline,0,False)
        self._load_calendars()
        self.manifest=json.loads(json.dumps(self._manifest()))
        self._emit('initial',manifest=self.manifest)
        self._events_to(0)

    def _check_cascading_domain(self):
        # Domain proof for this fixed dataset: after stage1 cadence a lot's remaining
        # stage2 work finishes within the shortest following stage1 cadence.
        # Do not pretend an occupancy guard implements arbitrary two-stage blocking.
        bounds=defaultdict(list)
        load={m.family:m.load_time+m.unload_time for m in self.machines}
        for rn,route in self.routes.items():
            for s in route.steps:
                row=self.files[rn][s.idx]
                if isinstance(row['BatchInterval'],(int,float)):
                    p=dist_spec(s.processing_time);hi=p.get('c',p.get('m',0)+p.get('offset',0));cad=average(dist_spec(s.cascading_time))
                    bounds[s.family].append((hi+load[s.family]-cad,cad))
        for family,b in bounds.items():
            if max(x[0] for x in b)>min(x[1] for x in b)+1e-8:
                raise ValueError('unsupported cascading slot2 blocking domain: '+family)

    def _emit(self,kind,**kw):
        r={'seq':len(self.trace),'time':self.t,'kind':kind,**kw};self.trace.append(r)
        if self.trace_path:
            with self.trace_path.open('a') as f:f.write(json.dumps(r,separators=(',',':'))+'\n')
    def _push(self,t,kind,payload):
        self.seq+=1;heapq.heappush(self.q,(float(t),self.seq,kind,payload))
    def _new_lot(self,lid,row,release,due,step,initial):
        route=self.parts[row['PART']]
        lot={'id':lid,'name':row['LOT'],'part':row['PART'],'route':route,'priority':row['PRIOR'],'pieces':row['PIECES'],'release':release,'due':due,'step':step,'initial':initial,'status':'unreleased','visits':{},'dedications':{},'ready_since':None,'done':None}
        self.lots[lid]=lot;self._push(max(0,release) if initial else release,'release',lid)
    def _load_calendars(self):
        downs={r['DOWNCALNAME']:r for r in self.files['downcal.txt']};pms={r['PMCALNAME']:r for r in self.files['pmcal.txt']}
        for ai,a in enumerate(self.files['attach.txt']):
            matches=[m for m in self.machines if (m.group if a['RESTYPE']=='stngrp' else m.family)==a['RESNAME']]
            isdown=a['CALTYPE']=='down';d=downs[a['CALNAME']] if isdown else pms[a['CALNAME']]
            length=dist_spec(get_distribution(d['MTTRDIST'],d['MTTRUNITS'],d['MTTR'],d['MTTR2']))
            repeat=dist_spec(get_distribution(d['MTTFDIST'],d['MTTFUNITS'],d['MTTF'])) if isdown else dist_spec(get_distribution('constant',d['MTBPMUNITS'],d['MTBPM']))
            for n,m in enumerate(matches):
                key=f'{ai}:{m.idx}:{a["CALNAME"]}'
                if a['FOAUNITS']=='':
                    self.pm_counters[m.idx].append({'key':key,'remaining':a['FOA']/len(matches)*(n+1),'repeat':average(repeat),'length':length,'occurrence':0});continue
                first=dist_spec(get_distribution(a['FOADIST'],a['FOAUNITS'],a['FOA']))
                firsttime=draw(self.seed,['calendar',key,'first'],first)
                if a['FOADIST']=='constant':firsttime=firsttime/len(matches)*(n+1)
                self.calendars[key]={'machine':m.idx,'name':a['CALNAME'],'breakdown':isdown,'length':length,'repeat':repeat,'first_time':firsttime}
                self._push(firsttime,'calendar',{'key':key,'n':0})
    def _manifest(self):
        steps={rn:[{'step':s.order,'family':s.family,'name':s.step_name,'batch_min':s.batch_min,'batch_max':s.batch_max,'batching':s.batching,'processing':dist_spec(s.processing_time),'cadence':dist_spec(s.cascading_time),'cascading':s.cascading,'setup':s.setup_needed,'setup_time':s.setup_time,'sampling_percent':s.sampling_percent,'rework_percent':s.rework_percent,'rework_step':s.rework_step,'dedicate_for':s.lot_to_lens_dedication,'transport':dist_spec(s.transport_time) if s.transport_time else {'type':'constant','c':0}} for s in route.steps] for rn,route in self.routes.items()}
        return {'version':VERSION,'seed':self.seed,'horizon':self.horizon,'controlled_machine_ids':sorted(self.controlled),'initial_wip':self.initial_wip,'physical_machines':len(self.physical),'virtual_delay_resources':len(self.machines)-len(self.physical),'warmup_seconds':0,'outside_policy':'setup-aware-priority-FIFO-demand-v1','routes':steps,'machines':[{'id':m.idx,'family':m.family,'group':m.group,'load':m.load_time,'unload':m.unload_time,'cascading':m.cascading} for m in self.machines],'lots':[{k:v for k,v in l.items() if k not in ['visits','dedications','status','ready_since','done']} for l in self.lots.values()],'setups':[{'old':x,'new':y,'seconds':v} for (x,y),v in self.setups.items()],'min_runs':self.min_runs,'calendars':self.calendars,'piece_pm':dict(self.pm_counters),'data_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(self.data_dir.iterdir()) if p.is_file()}}
    def _step(self,l):return self.routes[l['route']].steps[l['step']]
    def _ready(self,l):
        route=self.routes[l['route']].steps
        while l['step']<len(route):
            s=self._step(l);n=l['visits'].get(str(s.order),0)+1;l['visits'][str(s.order)]=n
            sample=draw(self.seed,['sample',l['id'],s.order,n],{'type':'uniform','m':50,'offset':50})
            if sample>s.sampling_percent:
                self._emit('skip',lot=l['id'],step=s.order,visit=n,draw=sample);l['step']+=1;continue
            l['status']='waiting';l['ready_since']=self.t;self.waiting[s.family].add(l['id'])
            self._emit('ready',lot=l['id'],step=s.order,visit=n);return
        l['status']='done';l['done']=self.t;self.completed.append(l['id']);self._emit('lot_complete',lot=l['id'])
    def _area(self,to):
        families={self.machines[m].family for m in self.controlled}
        self.queue_area+=(to-self.t)*sum(len(self.waiting[f]) for f in families)
    def _events_to(self,to):
        while self.q and self.q[0][0]<=to:
            t,_,kind,p=heapq.heappop(self.q);self._area(t);self.t=t
            if kind=='release':
                l=self.lots[p];l['status']='released';self.releases+=1;self._emit('release',lot=p,initial=l['initial']);self._ready(l)
            elif kind=='lot_done':
                job=self.jobs[p['job']]
                if p['token']!=job['token']:continue
                for lid in job['lots']:
                    l=self.lots[lid];s=self._step(l);n=l['visits'][str(s.order)]
                    self._emit('operation_complete',job=p['job'],lot=lid,step=s.order)
                    rw=draw(self.seed,['rework',lid,s.order,n],{'type':'uniform','m':50,'offset':50})
                    if rw<=s.rework_percent:
                        self._emit('rework',lot=lid,step=s.order,target=s.rework_step,visit=n,draw=rw);l['step']=int(s.rework_step)-1
                    else:l['step']+=1
                    self._ready(l)
                job['done']=True
            elif kind=='calendar':self._calendar(p)
            elif kind=='process_free':
                job=self.jobs[p['job']]
                if p['token']==job['token']:self.processing_by_machine[job['machine']].discard(p['job'])
            elif kind=='wake':pass
        self._area(to);self.t=to
    def _calendar(self,p):
        key=p['key'];n=p['n'];c=self.calendars[key];mid=c['machine'];ms=self.machine_state[mid]
        length=draw(self.seed,['calendar',key,'length',n],c['length'])
        begin=max(self.t,ms['down_until']);end=begin+length;extension=end-max(self.t,ms['down_until'])
        # Serialized overlapping downtimes, preempt/resume all material still processing.
        affected=[]
        for jid,job in self.jobs.items():
            if job['machine']==mid and not job['done'] and job['process_end']>self.t:
                job['process_end']+=length;job['lot_end']+=length;job['token']+=1;affected.append(jid)
                self._push(job['lot_end'],'lot_done',{'job':jid,'token':job['token']});self._push(job['process_end'],'process_free',{'job':jid,'token':job['token']})
        ms['ready']=max(self.t,ms['ready'],ms['down_until'])+length;ms['down_until']=end;ms['setup']=''
        self._push(ms['ready'],'wake',None)
        self._emit('downtime',machine=mid,calendar=key,occurrence=n,breakdown=c['breakdown'],duration=length,blocked_until=end,machine_ready=ms['ready'],affected_jobs=affected)
        repeat=draw(self.seed,['calendar',key,'repeat',n],c['repeat'])
        nxt=self.t+length+repeat if c['breakdown'] else self.t+repeat
        self._push(nxt,'calendar',{'key':key,'n':n+1})
    def _setup(self,mid,s):
        old=self.machine_state[mid]['setup'];new=s.setup_needed
        if not new or old==new:return 0.
        if s.setup_time is not None:return s.setup_time
        return self.setups.get((old,new),self.setups.get(('',new),0.))
    def eligible(self,mid):
        m=self.machines[mid];ms=self.machine_state[mid]
        if max(ms['ready'],ms['down_until'])>self.t:return []
        if len(self.processing_by_machine[mid])>=(2 if m.cascading else 1):return []
        result=[]
        for lid in sorted(self.waiting[m.family]):
            l=self.lots[lid];s=self._step(l)
            if str(s.order) in l['dedications'] and l['dedications'][str(s.order)]!=mid:continue
            if ms['min_left']>0 and ms['min_setup']!=s.setup_needed:continue
            result.append(lid)
        return result
    def _groups(self,mid):
        groups=defaultdict(list)
        for lid in self.eligible(mid):
            l=self.lots[lid];groups[route_key(self._step(l),l['part'])].append(lid)
        return list(groups.values())
    def has_legal(self,mid):return any(len(g)>=self._step(self.lots[g[0]]).batch_min for g in self._groups(mid))
    def _validate(self,mid,ids):
        if mid not in range(len(self.machines)):raise ValueError('unknown machine')
        if not ids or len(ids)!=len(set(ids)):raise ValueError('empty or duplicate lots')
        eligible=set(self.eligible(mid))
        if not set(ids)<=eligible:raise ValueError('lot not eligible/ready, machine busy/down or min-run/dedication violation')
        ls=[self.lots[x] for x in ids];s=self._step(ls[0]);key=route_key(s,ls[0]['part'])
        if any(route_key(self._step(l),l['part'])!=key for l in ls):raise ValueError('incompatible batch (part,route step)')
        if not s.batch_min<=len(ls)<=s.batch_max:raise ValueError('batch capacity/minimum violated')
        return ls,s
    def _dispatch(self,mid,ids,owner):
        ls,s=self._validate(mid,ids);m=self.machines[mid];ms=self.machine_state[mid];setup=self._setup(mid,s)
        old=ms['setup'];keys=sorted([[l['id'],s.order,l['visits'][str(s.order)]] for l in ls]);key=['processing',keys]
        proc=draw(self.seed,key,dist_spec(s.processing_time));cadence=proc if s.processing_time is s.cascading_time else draw(self.seed,['cadence',keys],dist_spec(s.cascading_time))
        process=proc+m.load_time+m.unload_time;occupation=cadence+(0 if m.cascading else m.load_time+m.unload_time)
        nextstep=self.routes[ls[0]['route']].steps[ls[0]['step']+1] if ls[0]['step']+1<len(self.routes[ls[0]['route']].steps) else None
        transport=draw(self.seed,['transport',keys],dist_spec(nextstep.transport_time)) if nextstep and nextstep.transport_time else 0.
        piecepm=[];pm_seconds=0.
        for counter in self.pm_counters[mid]:
            counter['remaining']-=sum(l['pieces'] for l in ls)
            if counter['remaining']<=0:
                length=draw(self.seed,['piece_pm',counter['key'],counter['occurrence']],counter['length']);counter['occurrence']+=1;counter['remaining']=counter['repeat'];pm_seconds+=length;piecepm.append({'key':counter['key'],'duration':length,'occurrence':counter['occurrence']-1})
        jid=self.dispatch_id;self.dispatch_id+=1
        job={'machine':mid,'lots':list(ids),'start':self.t,'process_end':self.t+setup+process,'lot_end':self.t+setup+process+transport,'token':0,'done':False,'controlled':mid in self.controlled}
        self.jobs[jid]=job;self.processing_by_machine[mid].add(jid)
        ms['ready']=self.t+setup+(max(occupation,process) if piecepm else occupation)+pm_seconds;ms['setup']='' if piecepm else s.setup_needed
        if setup>0 and s.setup_needed in self.min_runs and ms['min_left']==0:ms['min_left']=self.min_runs[s.setup_needed];ms['min_setup']=s.setup_needed
        ms['min_left']=max(0,ms['min_left']-len(ls))
        for l in ls:
            self.waiting[s.family].remove(l['id']);l['status']='processing'
            if s.lot_to_lens_dedication is not None:l['dedications'][str(s.lot_to_lens_dedication)]=mid
        self._push(job['process_end'],'process_free',{'job':jid,'token':0});self._push(job['lot_end'],'lot_done',{'job':jid,'token':0});self._push(ms['ready'],'wake',None)
        self._emit('dispatch',job=jid,machine=mid,lots=list(ids),steps=[s.order]*len(ls),visits=[l['visits'][str(s.order)] for l in ls],owner=owner,setup_before=old,setup_after=ms['setup'],setup_seconds=setup,processing_seconds=proc,cadence_seconds=cadence,transport_seconds=transport,process_end=job['process_end'],lot_end=job['lot_end'],machine_ready=ms['ready'],piece_pm=piecepm,min_runs_left=ms['min_left'],processing_key=key)
        self.stats['dispatches']+=1;self.stats['controlled_dispatches']+=mid in self.controlled
        self.stats['batch_dispatches']+=s.batch_max>1
    def _outside(self):
        # Fixed independent policy, same for all experimental arms. Never used for controlled machines.
        changed=False
        for m in self.machines:
            if m.idx in self.controlled:continue
            groups=[]
            for g in self._groups(m.idx):
                s=self._step(self.lots[g[0]])
                if len(g)<s.batch_min:continue
                g.sort(key=lambda lid:(-self.lots[lid]['priority'],self.lots[lid]['ready_since'],self.lots[lid]['due'],lid))
                l=self.lots[g[0]];key=(self._setup(m.idx,s),-min(1,len(g)/s.batch_max),-l['priority'],l['ready_since'],l['due'],g[0])
                groups.append((key,g[:s.batch_max]))
            if groups:self._dispatch(m.idx,min(groups)[1],'environment');changed=True
        return changed
    def advance(self):
        if self.finished:return self.state()
        while self.t<self.horizon:
            if self.t>=self.wait_until and any(self.has_legal(mid) for mid in self.controlled):return self.state()
            self._outside()
            if self.t>=self.wait_until and any(self.has_legal(mid) for mid in self.controlled):return self.state()
            nxt=min(self.q[0][0] if self.q else self.horizon,self.horizon)
            if self.wait_until>self.t:nxt=min(nxt,self.wait_until)
            if nxt<=self.t:raise RuntimeError('nonadvancing simulation clock')
            self._events_to(nxt)
        self.finished=True;self._emit('terminal',metrics=self.metrics(),lot_statuses={lid:l['status'] for lid,l in self.lots.items()});return self.state()
    def state(self):
        machines=[]
        for mid in sorted(self.controlled):
            m=self.machines[mid];ms=self.machine_state[mid];candidates=[]
            for lid in self.eligible(mid):
                l=self.lots[lid];s=self._step(l)
                candidates.append({'lot':lid,'part':l['part'],'step':s.order,'priority':l['priority'],'due':l['due'],'waiting_seconds':self.t-l['ready_since'],'batch_key':list(route_key(s,l['part'])),'batch_min':s.batch_min,'batch_max':s.batch_max,'setup':s.setup_needed,'setup_seconds':self._setup(mid,s),'expected_processing_seconds':average(dist_spec(s.processing_time))+m.load_time+m.unload_time})
            machines.append({'machine':mid,'family':m.family,'ready_now':max(ms['ready'],ms['down_until'])<=self.t,'current_setup':ms['setup'],'min_runs_left':ms['min_left'],'candidates':candidates})
        return {'schema_version':'smt-state-1','time':self.t,'horizon':self.horizon,'finished':self.finished,'decision_count':self.decisions,'machines':machines,'current_wip':sum(l['status'] not in ['done','unreleased'] for l in self.lots.values()),'completed_lots':len(self.completed),'action_contract':'dispatches specify exact machine and lot_ids; compatible part+step batch at min..max; wait_seconds 0..1800; no solver/rule selection for B'}
    def apply(self,action):
        if self.finished:raise ValueError('window finished')
        if self.decisions>=self.max_decisions:raise RuntimeError('controlled_decision_budget_exhausted')
        ds=action.get('dispatches',[]);wait=float(action.get('wait_seconds',0))
        if not 0<=wait<=1800:raise ValueError('wait_seconds outside [0,1800]')
        if not ds and wait<=0:raise ValueError('empty action requires positive explicit wait')
        mids=[];lids=[]
        for d in ds:
            mid=d['machine'];ids=d['lot_ids']
            if mid not in self.controlled:raise ValueError('model may only dispatch controlled machines')
            self._validate(mid,ids);mids.append(mid);lids+=ids
        if len(mids)!=len(set(mids)) or len(lids)!=len(set(lids)):raise ValueError('duplicate resource in action')
        self._emit('action',decision=self.decisions,action=action);self.decisions+=1
        for d in ds:self._dispatch(d['machine'],d['lot_ids'],'controller')
        self.wait_until=self.t+wait
        # All background assignments at the current clock are drained after the controller's explicit decisions.
        self._outside()
        return self.advance()
    def metrics(self):
        done=[self.lots[lid] for lid in self.completed];initial_active=sum(l['initial'] for l in self.lots.values());active=sum(l['status'] not in ['done','unreleased'] for l in self.lots.values())
        controls=[j for j in self.jobs.values() if j['controlled']]
        completed_ops=sum(len(j['lots']) for j in controls if j['lot_end']<=self.t)
        return {'completed_window':self.finished or self.t==self.horizon,'simulation_seconds':self.t,'throughput_lots':len(done),'throughput_wafers':sum(l['pieces'] for l in done),'mean_cycle_seconds_completed':sum(l['done']-l['release'] for l in done)/len(done) if done else None,'tardy_completed_lots':sum(l['done']>l['due'] for l in done),'total_tardiness_completed_seconds':sum(max(0,l['done']-l['due']) for l in done),'initial_wip_lots':initial_active,'released_new_lots':sum(not l['initial'] and l['status']!='unreleased' for l in self.lots.values()),'terminal_wip_lots':active,'wip_change':active-initial_active,'terminal_tardy_wip_lots':sum(l['status'] not in ['done','unreleased'] and l['due']<self.t for l in self.lots.values()),'controlled_completed_operation_lots':completed_ops,'controlled_dispatched_operation_lots':sum(len(j['lots']) for j in controls),'controlled_family_queue_area_lot_seconds':self.queue_area,'controlled_decisions':self.decisions,'controlled_machine_fraction':len(self.controlled)/len(self.physical),'dispatches':self.stats['dispatches'],'controlled_dispatches':self.stats['controlled_dispatches'],'batch_dispatches':self.stats['batch_dispatches'],'unfinished_controlled_batches':sum(j['lot_end']>self.t and len(j['lots'])>1 for j in controls),'end_to_end_seconds':time.perf_counter()-self.started_wall}
    def finish(self):
        if not self.finished:raise RuntimeError('must complete entire window, cannot silently finish early')
        return self.metrics()
