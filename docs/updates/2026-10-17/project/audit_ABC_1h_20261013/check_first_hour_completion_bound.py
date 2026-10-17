"""Optimistic serial route lower bounds; no simulation or solver required."""
import json,hashlib,collections,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'experiment_round2_3datasets';OUT=Path(__file__).resolve().parent
trace=ROOT/'runs/smt_fullfab_development/A_1701_1h_hybrid_v1/trace.jsonl'
with trace.open() as f:m=json.loads(next(f))['manifest']
family=collections.defaultdict(list)
for x in m['machines']:family[x['family']].append(x)
def minimum(d):
 if d['type']=='constant':return d['c']
 if d['type']=='uniform':return max(0,d['m']-d.get('offset',d.get('width',0)/2))
 if d['type']=='exponential':return 0
 raise ValueError(d)
assert all(s['rework_step']<=s['step'] for route in m['routes'].values() for s in route if s['rework_percent']>0), 'forward rework needs different bounds'
rows=[]
for l in m['lots']:
 rest=m['routes'][l['route']][l['step']:]
 process_min=sum(minimum(s['processing'])+min(x['load']+x['unload'] for x in family[s['family']]) for s in rest if s['sampling_percent']==100)
 # Include only transfers between adjacent mandatory steps; ignore all others.
 transfer_min=sum(minimum(b['transport']) for a,b in zip(rest,rest[1:]) if a['sampling_percent']==100 and b['sampling_percent']==100)
 rows.append({'lot':l['id'],'initial':l['initial'],'route':l['route'],'completed_step_at_start':l['step'],'route_steps':len(m['routes'][l['route']]),'remaining_steps':len(rest),'processing_loading_lower_bound_seconds':process_min,'mandatory_transfer_lower_bound_seconds':transfer_min,'earliest_possible_finish_lower_bound_seconds':max(0,l['release'])+process_min+transfer_min})
possible=[x for x in rows if x['earliest_possible_finish_lower_bound_seconds']<=3600]
assert len(possible)==1 and possible[0]['lot']=='w1387'
completions=[];lot_dispatches=[]
for line in trace.open():
 e=json.loads(line)
 if e['kind']=='lot_complete':completions.append({'lot':e['lot'],'time':e['time']})
 if e['kind']=='dispatch' and 'w1387' in e['lots']:lot_dispatches.append(e)
assert len(completions)==1 and completions[0]['lot']=='w1387'
reference=[]
for name in ['ref_cr_1701_1h_v1','ref_cr_1701_8h_v1','ref_fifo_1701_8h_v1','ref_cr_1701_24h_v1']:
 p=ROOT/'runs/smt_fullfab_development'/name/'result.json';d=json.loads(p.read_text());reference.append({'run':name,'saved_status':d['status'],'window_end':d['metrics']['window_end'],'throughput_lots':d['metrics']['throughput_lots'],'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'fresh_full_audit_in_this_followup':False})
source=ROOT/'artifacts/smt_fullfab_semantics/source_audit.json';official=json.loads(source.read_text())['reference_reports']['perf.rep'];year=next(x for x in official['rows'] if x['PERIOD']=='Period_1')
result={'valid_upper_bound_under_current_model':True,'trace_sha256':hashlib.sha256(trace.read_bytes()).hexdigest(),'total_lots':len(rows),'method':'Each lot must serially complete all remaining 100-percent sampling steps. Use minimum processing plus minimum family loading/unloading, and minimum transfers between adjacent mandatory steps. Ignore all optional work, setup, queues, downtime, capacity competition and rework. Source has no forward rework. Thus this is an optimistic lower bound, not a predicted schedule.','cold_start_assumption':'All initial WIP starts before its next uncompleted step, with no already-progressed processing residual carried in.','one_hour_completed_lots_upper_bound':len(possible),'one_hour_candidate_lots':possible,'nearest_excluded_lots':sorted((x for x in rows if x not in possible),key=lambda x:x['earliest_possible_finish_lower_bound_seconds'])[:12],'achieved_completion_events':completions,'achieved_w1387_dispatches':lot_dispatches,'initial_remaining_steps_median':statistics.median(x['remaining_steps'] for x in rows if x['initial']),'saved_reference_results':reference,'official_archived_reference':{'source_path':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'perf_rep_sha256':official['sha256'],'Period_1':year,'annual_completed_lots':int(year['LOTCOMPS']),'mean_lots_per_hour':int(year['LOTCOMPS'])/365/24,'mean_lots_per_day':int(year['LOTCOMPS'])/365,'current_simulator_official_calibrated':False,'not_a_first_hour_target':True},'all_lot_bounds':rows}
p=OUT/'first_hour_completion_bound.json';p.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ['all_lot_bounds','achieved_w1387_dispatches','official_archived_reference','nearest_excluded_lots']},ensure_ascii=False,indent=2))
print('NEAREST_EXCLUDED',result['nearest_excluded_lots'][0])
