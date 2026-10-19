"""Independent CSV-to-manifest binding, used only in offline auditing.
No simulator classes or normalization functions are imported.
"""
import csv,hashlib,math,random,json
from collections import defaultdict
from pathlib import Path
from datetime import datetime

def verify_source(manifest,data_dir):
    root=Path(data_dir);errors=[]
    def check(ok,msg):
        if not ok:errors.append('source: '+msg)
    def number(x):
        try:return int(x)
        except (ValueError,TypeError):
            try:return float(x)
            except (ValueError,TypeError):return x
    def read(name):
        with (root/name).open() as f:return [{k:number(v) for k,v in row.items()} for row in csv.DictReader(f,delimiter='\t')]
    def interval(x,u):return x*{'sec':1,'s':1,'min':60,'hr':3600,'day':86400,'pieces':1,'':1}[u]
    def distribution(t,u,a,b=None,mult=1):
        if t=='constant':return {'type':t,'c':mult*interval(a,u)}
        if t=='exponential':return {'type':t,'mean':mult*interval(a,u)}
        return {'type':t,'m':mult*interval(a,u),('offset' if manifest['version']!='smt-adapter-v1' else 'width'):mult*interval(b,u)}
    expected_names={p.name for p in root.iterdir() if p.is_file()}
    check(set(manifest['data_hashes'])==expected_names,'input hash inventory')
    for name,sha in manifest['data_hashes'].items():check((root/name).exists() and hashlib.sha256((root/name).read_bytes()).hexdigest()==sha,'hash '+name)
    expected_machines=[];locations={}
    for row in read('tool.txt.1l'):
        locations[row['STNFAM']]=row['STNFAMLOC']
        for _ in range(int(row['STNQTY'])):expected_machines.append({'id':len(expected_machines),'family':row['STNFAM'],'group':row['STNGRP'],'load':interval(row['LTIME'],row['LTUNITS']),'unload':interval(row['ULTIME'],row['ULTUNITS']),'cascading':row['STNCAP']==2})
    check(expected_machines==manifest['machines'],'machine table/IDs/capacity');check(manifest['physical_machines']==sum(m['group']!='Delay_32' for m in expected_machines),'physical machine count');check(manifest['virtual_delay_resources']==sum(m['group']=='Delay_32' for m in expected_machines),'virtual resource count')
    transport={(r['FROMLOC'],r['TOLOC']):distribution(r['DDIST'],r['DUNITS'],r['DTIME'],r['DTIME2']) for r in read('fromto.txt')}
    expected_routes={};cascading_bounds=defaultdict(list)
    for f in sorted(root.glob('route_*.txt')):
        steps=[];previous_loc=None
        for row in read(f.name):
            pieces=25;spec=distribution(row['PDIST'],row['PTUNITS'],row['PTIME'],row['PTIME2'],pieces if row['PTPER']=='per_piece' and not isinstance(row['PartInterval'],(int,float)) else 1)
            if isinstance(row['PartInterval'],(int,float)):
                cadence={'type':'constant','c':interval(row['PartInterval'],row['PartIntUnits'])*pieces};spec['m']+=interval(row['PartInterval'],row['PartIntUnits'])*(pieces-1);cascading=True
            elif isinstance(row['BatchInterval'],(int,float)):cadence={'type':'constant','c':interval(row['BatchInterval'],row['BatchIntUnits'])};cascading=True
            else:cadence=spec.copy();cascading=False
            trans=transport.get((previous_loc,locations[row['STNFAM']]),{'type':'constant','c':0});previous_loc=locations[row['STNFAM']]
            if isinstance(row['BatchInterval'],(int,float)):
                family=row['STNFAM'];loading=next(m['load']+m['unload'] for m in expected_machines if m['family']==family);upper=spec.get('c',spec.get('m',0)+spec.get('offset',spec.get('width',0)/2));cascading_bounds[family].append((upper+loading-cadence['c'],cadence['c']))
            steps.append({'step':row['STEP'],'family':row['STNFAM'],'name':row['DESC'],'batch_min':int(row['BATCHMN']/25) if row['BATCHMN']!='' else 1,'batch_max':int(row['BATCHMX']/25) if row['BATCHMX']!='' else 1,'batching':row['PTPER']=='per_batch','processing':spec,'cadence':cadence,'cascading':cascading,'setup':row['SETUP'],'setup_time':interval(row['STIME'],row['STUNITS']) if type(row['STIME']) is int else None,'sampling_percent':float(row['StepPercent']) if row['StepPercent']!='' else 100,'rework_percent':float(row['REWORK']) if row['REWORK']!='' else 0,'rework_step':row['RWKSTEP'],'dedicate_for':row['FORSTEP'] if row['SVESTN']=='yes' else None,'transport':trans})
        expected_routes[f.name]=steps
    check(expected_routes==manifest['routes'],'routes/processing/sampling/rework/transport')
    for family,pairs in cascading_bounds.items():check(max(a for a,b in pairs)<=min(b for a,b in pairs)+1e-8,'cascading domain needing unsupported slot2 blocking '+family)
    date=lambda x:datetime.strptime(x,'%m/%d/%y %H:%M:%S')
    orders=read('order.txt');wip=read('WIP.txt');parts={r['PART']:r['ROUTEFILE'] for r in read('part.txt')};origin=min(date(r['START']) for r in orders);lead={o['LOT']:(date(o['DUE'])-date(o['START'])).total_seconds() for o in orders};expected_lots=[]
    def lot(lid,row,release,due,step,initial):return {'id':lid,'name':row['LOT'],'part':row['PART'],'route':parts[row['PART']],'priority':row['PRIOR'],'pieces':row['PIECES'],'release':release,'due':due,'step':step,'initial':initial}
    for i,r in enumerate(wip):
        name=r['LOT'][5:].rsplit('_',1)[0] if r['LOT'].startswith('Init_') else r['LOT'];due=(date(r['DUE'])-origin).total_seconds();expected_lots.append(lot('w'+str(i),r,due-lead[name],due,r['CURSTEP']-1,True))
    for oi,o in enumerate(orders):
        gap=interval(o['REPEAT'],o['RUNITS']);start=(date(o['START'])-origin).total_seconds();deadline=(date(o['DUE'])-date(o['START'])).total_seconds()
        for n in range(min(int(o['RPT#']),int(max(0,manifest['horizon']-start)/gap)+1)):
            for k in range(int(o['LOTSPERRPT'])):
                rel=start+n*gap
                if rel<manifest['horizon']:expected_lots.append(lot(f'o{oi}r{n}l{k}',o,rel,rel+deadline,0,False))
    check(expected_lots==manifest['lots'],'lot identities/initial WIP/release/deadline');check(manifest['initial_wip']==len(wip),'initial WIP total')
    setups=[{'old':r['CURSETUP'],'new':r['NEWSETUP'],'seconds':interval(r['STIME'],r['STUNITS'])} for r in read('setup.txt')];check(setups==manifest['setups'],'setup matrix');check({r['SETUP']:r['MINRUN'] for r in read('setupgrp.txt')}==manifest['min_runs'],'minimum setup runs')
    # Calendar identities, repeat distributions, durations and staggered first times.
    def sample(key,spec):
        r=random.Random(int.from_bytes(hashlib.sha256(json.dumps([manifest['seed'],key],separators=(',',':')).encode()).digest(),'big'))
        if spec['type']=='constant':return spec['c']
        if spec['type']=='uniform':
            offset=spec.get('offset',spec.get('width',0)/2);return r.uniform(spec['m']-offset,spec['m']+offset)
        return r.expovariate(1/spec['mean'])
    downs={r['DOWNCALNAME']:r for r in read('downcal.txt')};pms={r['PMCALNAME']:r for r in read('pmcal.txt')};expected_cal={};expected_piece={}
    for ai,a in enumerate(read('attach.txt')):
        matches=[m for m in expected_machines if (m['group'] if a['RESTYPE']=='stngrp' else m['family'])==a['RESNAME']]
        isdown=a['CALTYPE']=='down';d=downs[a['CALNAME']] if isdown else pms[a['CALNAME']]
        duration=distribution(d['MTTRDIST'],d['MTTRUNITS'],d['MTTR'],d.get('MTTR2'));repeat=distribution(d['MTTFDIST'],d['MTTFUNITS'],d['MTTF']) if isdown else distribution('constant',d['MTBPMUNITS'],d['MTBPM'])
        for i,m in enumerate(matches):
            key=f'{ai}:{m["id"]}:{a["CALNAME"]}'
            if a['FOAUNITS']=='':
                expected_piece.setdefault(str(m['id']),[]).append({'key':key,'remaining':a['FOA']/len(matches)*(i+1),'repeat':repeat['c'],'length':duration,'occurrence':0});continue
            first=distribution(a['FOADIST'],a['FOAUNITS'],a['FOA']);at=sample(['calendar',key,'first'],first)
            if a['FOADIST']=='constant':at=at/len(matches)*(i+1)
            expected_cal[key]={'machine':m['id'],'name':a['CALNAME'],'breakdown':isdown,'length':duration,'repeat':repeat,'first_time':at}
    check(expected_cal==manifest['calendars'],'calendar distributions/occurrences')
    # defaultdict access during old manifests can create empty arrays; they carry no obligations.
    actual_piece={str(k):v for k,v in manifest['piece_pm'].items() if v}
    check(expected_piece==actual_piece,'counter-based PM obligations')
    return errors
