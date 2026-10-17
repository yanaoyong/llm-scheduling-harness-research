"""Standard-library event accounting, independent of all project metric functions."""
from pathlib import Path
import json,hashlib,collections,math,ast,types
ROOT=Path(__file__).resolve().parents[1]/'experiment_round2_3datasets';OUT=Path(__file__).resolve().parent
paths={'A':'runs/smt_fullfab_development/A_1701_1h_hybrid_v1/trace.jsonl','B':'runs/smt_fullfab_stage2/B_1701_1h_delta_v15__authorized_extension_001/physical/trace.jsonl','C':'runs/smt_fullfab_stage2/C_1701_1h_constructive_v2/trace.jsonl'}
allresults={};manifests={};sources={}
def read(p):
 raw=p.read_bytes();sources[str(p.relative_to(ROOT))]=hashlib.sha256(raw).hexdigest();return json.loads(raw)
for arm,rel in paths.items():
 p=ROOT/rel;raw=p.read_bytes();sources[rel]=hashlib.sha256(raw).hexdigest();events=[json.loads(s) for s in raw.splitlines()];m=events[0]['manifest'];manifests[arm]=m
 machines={x['id']:x for x in m['machines']};lots={x['id']:x for x in m['lots']};prod={i for i,x in machines.items() if x['group']!='Delay_32'}
 counts=collections.Counter();waiting=set();jobs={};releases={};completed={};queue_area=0;prev=0;dispatch=started=ops=0;setup=0;fills=[]
 for i,e in enumerate(events):
  assert e['seq']==i and prev<=e['time']<=3600
  queue_area+=(e['time']-prev)*len(waiting);prev=e['time'];k=e['kind'];counts[k]+=1
  if k=='release':assert e['lot'] not in releases;releases[e['lot']]=e['time']
  elif k=='ready':
   s=m['routes'][lots[e['lot']]['route']][e['step']-1]
   if s['family'] in {machines[mid]['family'] for mid in prod}:assert e['lot'] not in waiting;waiting.add(e['lot'])
  elif k=='dispatch':
   jobs[e['job']]=e['machine'] in prod
   if jobs[e['job']]:
    dispatch+=1;started+=len(e['lots']);setup+=max(0,min(3600,e['time']+e['setup_seconds'])-e['time'])
    for lid in e['lots']:waiting.remove(lid)
    s=m['routes'][lots[e['lots'][0]]['route']][e['steps'][0]-1]
    if s['batch_max']>1:fills.append(len(e['lots'])/s['batch_max'])
  elif k=='operation_complete':ops+=int(jobs[e['job']])
  elif k=='lot_complete':assert e['lot'] not in completed;completed[e['lot']]=e['time']
 terminal=events[-1];assert counts['initial']==counts['terminal']==1 and terminal['kind']=='terminal' and terminal['time']==3600
 statuses=collections.Counter(terminal['lot_statuses'].values());wip=statuses['waiting']+statuses['processing']
 assert len(releases)==len(completed)+wip
 tardy=sum((lots[lid]['priority']/10)*max(0,min(3600,completed.get(lid,3600))-max(0,t,lots[lid]['due'])) for lid,t in releases.items())/3600
 a={'events':len(events),'simulation_start':events[0]['time'],'simulation_end':terminal['time'],'production_scope':len(prod),'initial_wip':sum(x['initial'] for x in lots.values()),'new_released':sum(not lots[lid]['initial'] for lid in releases),'complete_lots':len(completed),'terminal_wip':wip,'terminal_tardy_wip':sum(lots[lid]['due']<3600 for lid in releases if lid not in completed),'production_dispatches':dispatch,'production_operations_started':started,'production_operations_completed':ops,'plans_committed':counts['plan_committed'],'queue_wait_lot_hours':queue_area/3600,'declared_setup_machine_hours':setup/3600,'batch_fill_mean':sum(fills)/len(fills),'weighted_tardy_lot_hours':tardy,'completed':completed,'event_counts':dict(counts)}
 prior=json.loads((OUT/(arm+'_bundle')/'metrics.json').read_text())['metrics']
 assert prior['throughput_lots']==a['complete_lots'] and prior['terminal_wip_lots']==wip and prior['weighted_tardy_lot_hours']==tardy
 assert math.isclose(sum(x['queue_wait_lot_seconds'] for x in prior['production_family_statistics'].values()),queue_area,rel_tol=1e-12)
 allresults[arm]=a
# A: link original solver outputs and frozen implementation to all actual commits.
run=ROOT/'runs/smt_fullfab_development/A_1701_1h_hybrid_v1';prov=read(run/'provenance.json')
source_checked=[]
for rel,expected in prov['source_sha256'].items():
 p=run/'source_snapshot'/rel;actual=hashlib.sha256(p.read_bytes()).hexdigest();assert actual==expected;sources[str(p.relative_to(ROOT))]=actual;source_checked.append(rel)
# Extract the original pure clipping function by AST, without importing a runner or solver.
p=run/'source_snapshot/src/smt_fullfab/runner.py';tree=ast.parse(p.read_text());node=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='crop_plan');namespace={'json':json};exec(compile(ast.Module(body=[node],type_ignores=[]),str(p),'exec'),namespace)
events=[json.loads(s) for s in (ROOT/paths['A']).read_text().splitlines()];commits=[e for e in events if e['kind']=='plan_committed'];env=types.SimpleNamespace(physical=set(manifests['A']['controlled_machine_ids']),horizon=3600)
cp_calls=0
for i,e in enumerate(commits):
 solved=read(run/f'solver_{i:05d}.json');assert namespace['crop_plan'](solved['plan'],env)==e['plan'];assert solved['solver_status'] in ['FEASIBLE','FEASIBLE_HEURISTIC','OPTIMAL'];cp_calls+=solved.get('solver_calls',0)
result={'scope':'Independent arithmetic and A solver-output attribution; no simulator or model or project metrics imports.','arms':allresults,'A_source_snapshot_files_verified':len(source_checked),'A_solver_outputs_matched':len(commits),'A_cp_calls_from_solver_outputs':cp_calls,'manifest_differing_fields_vs_A':{a:[k for k in set(manifests['A'])|set(manifests[a]) if manifests['A'].get(k)!=manifests[a].get(k)] for a in ['B','C']},'sources':sources}
(OUT/'independent_counts.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ['sources']},ensure_ascii=False,indent=2))
