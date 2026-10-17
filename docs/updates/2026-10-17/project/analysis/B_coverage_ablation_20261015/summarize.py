from pathlib import Path
import json,math,sqlite3,zlib
O=Path(__file__).resolve().parent
reg=json.loads((O/'experiment.json').read_text())
rows={}; comparisons=[]
for case,entry in reg['cases'].items():
 p=O/(case+'.result.json')
 if not p.exists():continue
 r=json.loads(p.read_text());m=r.get('metrics') or {};u=r['usage'];families=list(m.get('production_family_statistics',{}).values())
 row={'case':case,'state':entry['state_id'],'variant':entry['variant'],'complete':r['complete_common_window'],'seconds':r['advanced_seconds'],'replans':r['replans'],'mean_executed_seconds_per_plan':r['advanced_seconds']/r['replans'] if r['replans'] else None,'calls':u['actual_model_attempts'],'input_tokens':u['input_tokens'],'output_tokens':u['output_tokens'],'tokens':u['input_tokens']+u['output_tokens'],'model_seconds':u['model_seconds'],'mean_tasks':sum(r['plan_task_counts'])/len(r['plan_task_counts']) if r['plan_task_counts'] else None,'max_queue_depth':max(r['plan_max_queue_depths'],default=0),'weighted_tardy_lot_seconds':m.get('weighted_tardy_lot_seconds'),'throughput_lots':m.get('throughput_lots'),'ready_wait_lot_seconds':sum(f['queue_wait_lot_seconds'] for f in families),'operation_lots_dispatched':sum(f['operation_lots_dispatched'] for f in families),'physical_valid':r['physical_audit']['prefix_valid_except_expected_missing_terminal'],'provenance_valid':r['provenance'].get('valid'),'cost_valid':r['cost'].get('valid'),'rejections':r['rejections'],'stop_counts':r['stop_counts']}
 trace=[json.loads(x) for x in (O/'runs'/case/'exports/trace.jsonl').read_text().splitlines()];jobs={e['job']:e['machine'] for e in trace if e['kind']=='dispatch'};production={m['id'] for m in trace[0]['manifest']['machines'] if m['group']!='Delay_32'}
 row['operation_lots_completed']=sum(e['kind']=='operation_complete' and r['start']<e['time']<=r['end'] and jobs.get(e.get('job')) in production for e in trace)
 row['material_observed_fraction']=sum(f['material_present_observed_fraction']*f['machine_count'] for f in families)/sum(f['machine_count'] for f in families) if families else None
 tools={}
 for f in (O/'runs'/case/'model').glob('*/final.txt'):
  try:
   a=json.loads(f.read_text());a=a.get('action',a);tools[a.get('tool','unparsed')]=tools.get(a.get('tool','unparsed'),0)+1
  except (ValueError,KeyError):tools['unparsed']=tools.get('unparsed',0)+1
 row['tool_calls']=tools
 c=sqlite3.connect(f'file:{O}/runs/{case}/events.sqlite3?mode=ro',uri=True)
 def obj(h):return json.loads(zlib.decompress((O/'runs'/case/'objects'/(h+'.z')).read_bytes()))
 feedback=[obj(h) for (h,) in c.execute("select ref from records where namespace='feedback'")]
 commits=[obj(h) for (h,) in c.execute("select ref from records where namespace='commits'")]
 candidates={k:obj(h) for k,h in c.execute("select key,ref from records where namespace='candidates'")}
 plans=[candidates[x['candidate_ref']]['compiled']['plan'] for x in commits]
 c.close()
 row['actual_dispatches']=sum(f['dispatch_count_delta'] for f in feedback)
 row['nominal_valid_seconds']=[p['valid_until']-p['created_at'] for p in plans]
 row['actual_round_seconds']=[f['advanced_seconds'] for f in feedback]
 row['zero_advance_rounds']=sum(f['advanced_seconds']==0 for f in feedback)
 row['calls_per_simulated_minute']=row['calls']*60/row['seconds'] if row['seconds'] else None
 rows[case]=row
for state in reg['states']:
 b=rows.get(state+'__baseline')
 for variant in ['prompt','prompt_context_feedback']:
  v=rows.get(state+'__'+variant)
  if not b or not v or not b['complete'] or not v['complete']:continue
  quality={'weighted_tardiness_not_higher':v['weighted_tardy_lot_seconds']<=b['weighted_tardy_lot_seconds']+1e-6,'throughput_not_lower':v['throughput_lots']>=b['throughput_lots'],'completed_operations_not_lower':v['operation_lots_completed']>=b['operation_lots_completed'],'ready_wait_not_higher':v['ready_wait_lot_seconds']<=b['ready_wait_lot_seconds']+1e-6,'legal_and_model_owned':v['physical_valid'] and v['provenance_valid']}
  quality['both_arms_audit_valid']=all(x[k] for x in [b,v] for k in ['physical_valid','provenance_valid','cost_valid'])
  comparisons.append({'state':state,'variant':variant,'replan_reduction_fraction':1-v['replans']/b['replans'] if b['replans'] else None,'call_reduction_fraction':1-v['calls']/b['calls'] if b['calls'] else None,'token_reduction_fraction':1-v['tokens']/b['tokens'] if b['tokens'] else None,'quality_checks':quality,'no_observed_regression_on_registered_metrics':all(quality.values())})
aggregates=[]
if len(rows)==len(reg['cases']) and all(r['complete'] for r in rows.values()):
 for variant in ['baseline','prompt','prompt_context_feedback']:
  cells=[r for r in rows.values() if r['variant']==variant]
  item={'variant':variant,'states':len(cells),'simulated_seconds':sum(r['seconds'] for r in cells)}
  for k in ['calls','replans','tokens','input_tokens','output_tokens','model_seconds','weighted_tardy_lot_seconds','throughput_lots','operation_lots_completed','ready_wait_lot_seconds','actual_dispatches','rejections']:
   item[k]=sum(r[k] for r in cells)
  item['calls_per_simulated_minute']=item['calls']*60/item['simulated_seconds']
  aggregates.append(item)
 for item in aggregates[1:]:
  item['call_reduction_fraction']=1-item['calls']/aggregates[0]['calls']
  item['replan_reduction_fraction']=1-item['replans']/aggregates[0]['replans']
  item['all_paired_quality_checks_pass']=all(c['no_observed_regression_on_registered_metrics'] for c in comparisons if c['variant']==item['variant'])
summary={'finished_cells':len(rows),'completed_cells':sum(r['complete'] for r in rows.values()),'planned_cells':len(reg['cases']),'rows':list(rows.values()),'paired_comparisons':comparisons,'aggregates_all_three_complete_states_only':aggregates,'limitations':['One model trajectory per cell; model output is not seed controlled.','Three short 300-second windows cannot establish long-run non-inferiority.','Inherited physical state, plan, trace, event queue and RNG are exact; original horizon and period anchor preserved.','Prior selection notes inherited equally; old tool-history/fact cache reset equally.','Any unknown usage is retained, never set to zero.','Wall time includes an external accidental file-cleanup interruption and exact-byte recovery; do not treat it as a model-efficiency comparison.']}
summary['status']='complete' if summary['completed_cells']==summary['planned_cells'] else 'incomplete'
if (O/'interim_snapshot.json').exists() and summary['finished_cells']<summary['planned_cells']:
 interim=json.loads((O/'interim_snapshot.json').read_text())
 summary.update(status=interim['status'],interim_evidence_file='interim_snapshot.json',interim_total_model_calls=interim['total_model_calls'],interim_unknown_usage_calls=interim['unknown_usage_calls'],no_valid_effect_conclusion=True)
(O/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False,indent=2))
