"""Independent trace audit. Does not import simulator or its success/metrics code.

Reconstructs lot states, machine occupation, setups, commitments, calendar delays,
conservation and fixed metrics from explicit events plus immutable input manifest.
"""
from collections import defaultdict,Counter
from pathlib import Path
import hashlib,json,math,random

def sampled(seed,key,d):
    seed_bytes=hashlib.sha256(json.dumps([seed,key],separators=(',',':')).encode()).digest()
    generator=random.Random(int.from_bytes(seed_bytes,'big'))
    if d['type']=='constant':return d['c']
    if d['type']=='uniform':
        offset=d['offset'] if 'offset' in d else d['width']/2  # retain v1 development trace replay
        return generator.uniform(d['m']-offset,d['m']+offset)
    if d['type']=='exponential':return generator.expovariate(1/d['mean'])
    raise ValueError('unknown distribution')
def audit_trace(path_or_events,verify_data_dir=None):
    events=[json.loads(x) for x in Path(path_or_events).read_text().splitlines()] if isinstance(path_or_events,(str,Path)) else path_or_events
    errors=[]
    def check(ok,msg):
        if not ok and len(errors)<200:errors.append(msg)
    def near(a,b,msg):check(math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-6),f'{msg}: {a} != {b}')
    if not events or events[0].get('kind')!='initial':return {'valid':False,'errors':['missing initial manifest']}
    manifest=events[0]['manifest'];seed=manifest['seed'];horizon=manifest['horizon'];controls=set(manifest['controlled_machine_ids'])
    routes=manifest['routes'];machines={m['id']:m for m in manifest['machines']};lots={l['id']:dict(l,status='unreleased',next_step=l['step']+1,visits={},dedications={},ready=None,done=None) for l in manifest['lots']}
    ms={mid:dict(ready=0.,down=0.,setup='',min_left=0,min_setup='') for mid in machines};jobs={};completed=[];released=set();queue_area=0.;waiting_control=0;prev=0.;counts=Counter();dispatch_list=[];actions=[];last_action=None;pending_dispatches=[];controller_wait_until=0.;machine_jobs=defaultdict(list)
    setups={(x['old'],x['new']):x['seconds'] for x in manifest['setups']};cal=manifest['calendars'];nextcal={key:(c['first_time'],0) for key,c in cal.items()}
    piece={int(mid):[dict(c) for c in cs] for mid,cs in manifest['piece_pm'].items()}
    control_families={machines[mid]['family'] for mid in controls}
    for i,e in enumerate(events):
        t=e['time'];kind=e['kind'];check(e['seq']==i,f'{i}: sequence gap');check(t>=prev,f'{i}: time reversed');check(0<=t<=horizon,f'{i}: time outside window')
        queue_area+=(t-prev)*waiting_control
        prev=t
        try:
            if kind=='initial':check(i==0,'duplicate initial')
            elif kind=='release':
                lid=e['lot'];l=lots[lid];check(lid not in released,f'{i}: duplicate release');check(l['status']=='unreleased',f'{i}: invalid release state');near(t,max(0,l['release']) if l['initial'] else l['release'],f'{i}: release time');released.add(lid);l['status']='released'
            elif kind in ['ready','skip']:
                l=lots[e['lot']];check(l['status'] in ['released','transition'] and not l.get('required_rework'),f'{i}: ready/skip while not transitioning or missing rework');check(e['step']==l['next_step'],f'{i}: illegal route transition');s=routes[l['route']][l['next_step']-1];v=l['visits'].get(str(s['step']),0)+1;check(e['visit']==v,f'{i}: visit count');l['visits'][str(s['step'])]=v
                draw=sampled(seed,['sample',l['id'],s['step'],v],{'type':'uniform','m':50,'offset':50})
                if kind=='skip':check(draw>s['sampling_percent'],f'{i}: illegal sampling skip');near(draw,e['draw'],f'{i}: sample draw');l['next_step']+=1;l['status']='transition'
                else:check(draw<=s['sampling_percent'],f'{i}: missed sampling skip');l['status']='waiting';l['ready']=t;waiting_control+=s['family'] in control_families
            elif kind=='action':
                check(not pending_dispatches,f'{i}: previous action has unexecuted dispatch');check(t>=controller_wait_until,f'{i}: controlled action during explicit wait')
                check(e['decision']==len(actions),f'{i}: action index');a=e['action'];check(0<=a['wait_seconds']<=1800,f'{i}: wait bound');actions.append(e);last_action=e;pending_dispatches=list(a['dispatches']);controller_wait_until=t+a['wait_seconds']
                check(bool(a['dispatches']) or a['wait_seconds']>0,f'{i}: empty action without wait')
                declared_lots=[]
                for d in a['dispatches']:
                    check(d['machine'] in controls,f'{i}: action uncontrolled machine');check(bool(d['lot_ids']),f'{i}: action empty lot batch');declared_lots+=d['lot_ids']
                    for lid in d['lot_ids']:check(lid in lots and lots[lid]['status']=='waiting',f'{i}: action lot not currently waiting')
                check(len(declared_lots)==len(set(declared_lots)),f'{i}: duplicate lot in action')
                check(len({d['machine'] for d in a['dispatches']})==len(a['dispatches']),f'{i}: duplicate machine in action')
            elif kind=='dispatch':
                jid=e['job'];mid=e['machine'];m=machines[mid];machine=ms[mid];ids=e['lots'];check(jid not in jobs,f'{i}: duplicate job');check(bool(ids) and len(ids)==len(set(ids)),f'{i}: duplicate/empty lot batch');check(machine['ready']<=t+1e-6 and machine['down']<=t+1e-6,f'{i}: machine overlap/downtime')
                check(sum(jobs[jid]['process_end']>t for jid in machine_jobs[mid])<(2 if m['cascading'] else 1),f'{i}: physical processing-slot capacity');ls=[lots[lid] for lid in ids];s=routes[ls[0]['route']][ls[0]['next_step']-1]
                check(s['batch_min']<=len(ls)<=s['batch_max'],f'{i}: batch min/max')
                for n,l in enumerate(ls):
                    check(l['status']=='waiting',f'{i}: lot not waiting');check(l['next_step']==e['steps'][n],f'{i}: dispatched wrong step');ss=routes[l['route']][l['next_step']-1]
                    check(ss['family']==m['family'],f'{i}: machine qualification');check((l['part'],ss['step'],ss['name'])==(ls[0]['part'],s['step'],s['name']),f'{i}: batch incompatible');check(l['dedications'].get(str(ss['step']),mid)==mid,f'{i}: dedication violation');check(e['visits'][n]==l['visits'][str(ss['step'])],f'{i}: dispatch visit mismatch')
                    if ss['dedicate_for'] is not None:l['dedications'][str(ss['dedicate_for'])]=mid
                    waiting_control-=int(l['status']=='waiting' and ss['family'] in control_families);l['status']='processing';l['job']=jid
                check(e['owner']==('controller' if mid in controls else 'environment'),f'{i}: unlabelled controller takeover')
                if mid in controls:
                    check(last_action is not None and last_action['time']==t and {'machine':mid,'lot_ids':ids} in last_action['action']['dispatches'],f'{i}: controlled dispatch missing exact explicit action')
                    declared={'machine':mid,'lot_ids':ids};check(declared in pending_dispatches,f'{i}: repeated or unclaimed controlled dispatch')
                    if declared in pending_dispatches:pending_dispatches.remove(declared)
                check(machine['min_left']==0 or machine['min_setup']==s['setup'],f'{i}: minimum setup runs')
                expected_setup=0
                if s['setup'] and machine['setup']!=s['setup']:
                    expected_setup=s['setup_time'] if s['setup_time'] is not None else setups.get((machine['setup'],s['setup']),setups.get(('',s['setup']),0))
                check(machine['setup']==e['setup_before'],f'{i}: setup state');near(e['setup_seconds'],expected_setup,f'{i}: setup duration')
                keys=sorted([[l['id'],s['step'],l['visits'][str(s['step'])]] for l in ls]);proc=sampled(seed,['processing',keys],s['processing'])
                cadence=proc if s['cadence']==s['processing'] else sampled(seed,['cadence',keys],s['cadence'])
                nextstep=routes[ls[0]['route']][s['step']] if s['step']<len(routes[ls[0]['route']]) else None
                trans=sampled(seed,['transport',keys],nextstep['transport']) if nextstep else 0
                near(e['processing_seconds'],proc,f'{i}: processing sample');near(e['cadence_seconds'],cadence,f'{i}: cadence sample');near(e['transport_seconds'],trans,f'{i}: transport sample')
                process_time=proc+m['load']+m['unload'];occupation=cadence+(0 if m['cascading'] else m['load']+m['unload']);pm_total=0;pm_events=[]
                for counter in piece.get(mid,[]):
                    counter['remaining']-=sum(l['pieces'] for l in ls)
                    if counter['remaining']<=0:
                        dur=sampled(seed,['piece_pm',counter['key'],counter['occurrence']],counter['length']);pm_events.append({'key':counter['key'],'duration':dur,'occurrence':counter['occurrence']});counter['occurrence']+=1;counter['remaining']=counter['repeat'];pm_total+=dur
                check(pm_events==e['piece_pm'],f'{i}: piece maintenance obligation')
                expected_ready=t+expected_setup+(max(process_time,occupation) if pm_events else occupation)+pm_total
                near(e['machine_ready'],expected_ready,f'{i}: machine completion');near(e['process_end'],t+expected_setup+process_time,f'{i}: process end');near(e['lot_end'],t+expected_setup+process_time+trans,f'{i}: lot completion')
                machine['ready']=expected_ready;machine['setup']='' if pm_events else s['setup'];check(machine['setup']==e['setup_after'],f'{i}: setup after dispatch')
                if expected_setup>0 and s['setup'] in manifest['min_runs'] and machine['min_left']==0:machine['min_left']=manifest['min_runs'][s['setup']];machine['min_setup']=s['setup']
                machine['min_left']=max(0,machine['min_left']-len(ls));check(machine['min_left']==e['min_runs_left'],f'{i}: min runs counter')
                jobs[jid]={'machine':mid,'lots':ids,'pending':set(ids),'process_end':e['process_end'],'lot_end':e['lot_end'],'controlled':mid in controls,'done':False};dispatch_list.append(e);machine_jobs[mid].append(jid)
            elif kind=='downtime':
                key=e['calendar'];c=cal[key];mid=c['machine'];machine=ms[mid];ct,cn=nextcal[key];near(t,ct,f'{i}: calendar occurrence time');check(e['occurrence']==cn,f'{i}: calendar occurrence index');check(e['machine']==mid and e['breakdown']==c['breakdown'],f'{i}: calendar identity')
                duration=sampled(seed,['calendar',key,'length',cn],c['length']);near(duration,e['duration'],f'{i}: downtime draw');end=max(t,machine['down'])+duration
                affected=[]
                for jid,j in jobs.items():
                    if j['machine']==mid and not j['done'] and j['process_end']>t:
                        affected.append(jid);j['process_end']+=duration;j['lot_end']+=duration
                check(affected==e['affected_jobs'],f'{i}: downtime affected jobs');machine['ready']=max(t,machine['ready'],machine['down'])+duration;machine['down']=end;machine['setup']='';near(machine['ready'],e['machine_ready'],f'{i}: downtime ready');near(end,e['blocked_until'],f'{i}: downtime block')
                repeat=sampled(seed,['calendar',key,'repeat',cn],c['repeat']);nextcal[key]=(t+duration+repeat if c['breakdown'] else t+repeat,cn+1)
            elif kind=='operation_complete':
                jid=e['job'];j=jobs[jid];lid=e['lot'];l=lots[lid];check(lid in j['pending'],f'{i}: duplicated/unassigned operation completion');near(t,j['lot_end'],f'{i}: wrong operation completion time');check(l['status']=='processing' and l['job']==jid,f'{i}: wrong lot processing state');check(l['next_step']==e['step'],f'{i}: completion wrong step');j['pending'].discard(lid);j['done']=not j['pending'];l['next_step']+=1;l['status']='transition';counts['controlled_completed_operation_lots']+=j['controlled'];ss=routes[l['route']][e['step']-1];rw=sampled(seed,['rework',l['id'],ss['step'],l['visits'][str(ss['step'])]],{'type':'uniform','m':50,'offset':50});l['required_rework']=rw<=ss['rework_percent']
            elif kind=='rework':
                l=lots[e['lot']];s=routes[l['route']][e['step']-1];check(l['status']=='transition' and l['next_step']==e['step']+1,f'{i}: rework ordering');draw=sampled(seed,['rework',l['id'],s['step'],e['visit']],{'type':'uniform','m':50,'offset':50});check(draw<=s['rework_percent'],f'{i}: unsupported rework');near(draw,e['draw'],f'{i}: rework draw');check(e['target']==s['rework_step'],f'{i}: wrong rework target');l['next_step']=e['target'];l['required_rework']=False
            elif kind=='lot_complete':
                l=lots[e['lot']];check(l['status']=='transition' and not l.get('required_rework') and l['next_step']==len(routes[l['route']])+1,f'{i}: incomplete route marked done');l['status']='done';l['done']=t;completed.append(l['id'])
            elif kind=='terminal':
                check(not pending_dispatches,'terminal contains unexecuted declared dispatch');check(i==len(events)-1,'terminal must be last');near(t,horizon,'unfinished window');check(e['lot_statuses']=={lid:l['status'] for lid,l in lots.items()},'terminal inventory mismatch');check(all(l['status'] in ['waiting','processing','done','unreleased'] for l in lots.values()),'terminal unresolved transition')
            else:check(False,f'{i}: unknown event {kind}')
        except (KeyError,IndexError,TypeError,ValueError) as exc:check(False,f'{i}: malformed trace {exc}')
    check(events[-1]['kind']=='terminal','missing terminal event')
    for key,(t,n) in nextcal.items():check(t>horizon,f'missing due calendar event: {key}')
    # No processing completion scheduled within the window may disappear.
    for jid,j in jobs.items():check(j['done'] or j['lot_end']>horizon,f'unfinished due operation {jid}')
    for lid,l in lots.items():check(l['status']!='unreleased' or (not l['initial'] and l['release']>=horizon),f'missing lot release {lid}')
    initial=sum(l['initial'] for l in lots.values());new=sum(not lots[lid]['initial'] for lid in released);terminal=sum(l['status'] not in ['done','unreleased'] for l in lots.values())
    check(initial==manifest['initial_wip'],'initial WIP count');check(initial+new==len(completed)+terminal,'lot conservation')
    done=[lots[lid] for lid in completed];controlled=[e for e in dispatch_list if e['machine'] in controls];batch=[e for e in controlled if len(e['lots'])>1]
    metrics={'throughput_lots':len(done),'throughput_wafers':sum(l['pieces'] for l in done),'mean_cycle_seconds_completed':sum(l['done']-l['release'] for l in done)/len(done) if done else None,'tardy_completed_lots':sum(l['done']>l['due'] for l in done),'total_tardiness_completed_seconds':sum(max(0,l['done']-l['due']) for l in done),'initial_wip_lots':initial,'released_new_lots':new,'terminal_wip_lots':terminal,'wip_change':terminal-initial,'terminal_tardy_wip_lots':sum(l['status'] not in ['done','unreleased'] and l['due']<horizon for l in lots.values()),'controlled_completed_operation_lots':counts['controlled_completed_operation_lots'],'controlled_family_queue_area_lot_seconds':queue_area,'controlled_decisions':len(actions),'controlled_dispatches':len(controlled),'dispatches':len(dispatch_list),'unfinished_controlled_batches':sum(j['controlled'] and len(j['lots'])>1 and j['lot_end']>horizon for j in jobs.values()),'controlled_batch_fill_ratios':[len(e['lots'])/routes[lots[e['lots'][0]]['route']][e['steps'][0]-1]['batch_max'] for e in batch]}
    utilization={}
    for mid in controls:
        es=[e for e in controlled if e['machine']==mid];busy=sum(max(0,min(horizon,e['machine_ready'])-e['time']) for e in es)
        utilization[str(mid)]={'scheduled_occupation_fraction':busy/horizon,'dispatches':len(es),'completed_operation_lots':sum(len(j['lots']) for j in jobs.values() if j['machine']==mid and j['done'])}
    metrics['controlled_machine_utilization']=utilization
    # Full-factory resource reporting. Occupation is the scheduled processing/setup/PM
    # reservation measure; downtime is a separate observed calendar exposure metric.
    group_stats={}
    for group in sorted({m['group'] for m in machines.values() if m['group']!='Delay_32'}):
        members={mid for mid,m in machines.items() if m['group']==group};ds=[e for e in dispatch_list if e['machine'] in members]
        scheduled=sum(max(0,min(horizon,e['machine_ready'])-e['time']) for e in ds)
        downtime=sum(max(0,min(horizon,e['blocked_until'])-e['time']) for e in events if e['kind']=='downtime' and e['machine'] in members)
        group_stats[group]={'physical_machine_count':len(members),'dispatches':len(ds),'operation_lots_dispatched':sum(len(e['lots']) for e in ds),'scheduled_occupation_fraction':scheduled/(len(members)*horizon),'calendar_downtime_exposure_fraction':downtime/(len(members)*horizon)}
    metrics['production_group_statistics']=group_stats
    metrics['controlled_dispatch_share']=len(controlled)/len(dispatch_list) if dispatch_list else 0
    metrics['controlled_machine_fraction']=len(controls)/sum(m['group']!='Delay_32' for m in machines.values())
    if events[-1]['kind']=='terminal':
        original=events[-1]['metrics']
        for k,v in metrics.items():
            if k in original:
                if isinstance(v,(float,int)) and v is not None:near(v,original[k],'metric '+k)
                else:check(v==original[k],'metric '+k)
    if verify_data_dir:
        from .source_check import verify_source
        for error in verify_source(manifest,verify_data_dir):check(False,error)
    return {'valid':not errors,'errors':errors,'event_count':len(events),'metrics':metrics,'audit_version':'smt-independent-audit-v2','verified_input_hashes':bool(verify_data_dir),'verified_source_semantics':bool(verify_data_dir)}
