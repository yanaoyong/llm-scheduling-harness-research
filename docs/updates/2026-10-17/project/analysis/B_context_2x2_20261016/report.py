"""Read-only analysis of the isolated cohort, including unfinished/failed arms."""
from pathlib import Path
from collections import Counter
import json,sqlite3,zlib,time,sys
O=Path(__file__).resolve().parent
sys.path.insert(0,str(O/'workspace'))
from src.smt_fullfab.harness.contracts import sha_bytes,strict_json
reg=json.loads((O/'experiment.json').read_text());rows=[]
for case in reg['execution_order']:
 entry=reg['cases'][case]
 root=O/'runs'/case
 if not (root/'events.sqlite3').exists():
  rows.append({'case':case,'variant':entry['variant'],'started':False,'complete':False});continue
 db=sqlite3.connect(f'file:{root}/events.sqlite3?mode=ro',uri=True);db.execute('BEGIN')
 def raw(h):
  value=zlib.decompress((root/'objects'/(h+'.z')).read_bytes());assert sha_bytes(value)==h;return value
 def get(h):return strict_json(raw(h))
 def records(ns):return {k:get(h) for k,h in db.execute('SELECT key,ref FROM records WHERE namespace=? ORDER BY rowid',(ns,))}
 attempts=sorted(records('attempts').values(),key=lambda a:a['index']);head=strict_json(db.execute("SELECT value FROM metadata WHERE key='head'").fetchone()[0]);feedback=list(records('feedback').values());commits=list(records('commits').values());candidates=records('candidates');manifest=records('manifest')['run']
 actual=[a for a in attempts if a['channel']=='codex' and a['status'] not in ('reserved','not_sent')];known=[a for a in actual if a.get('usage') is not None]
 tools=Counter();uptake=Counter();milestones={};seconds=0.;tokens=0;unknown=0;promptchars=[];promptfeedbackchars=[];attempt_details=[]
 for n,a in enumerate(actual,1):
  seconds+=a.get('duration_seconds',0);u=a.get('usage');tokens+=u['input_tokens']+u['output_tokens'] if u else 0;unknown+=u is None
  try:
   action=get(a['raw_ref']);action=action.get('action',action);tool=action.get('tool','invalid')
  except Exception:action={};tool='in_flight' if a['status']=='started' else 'transport_failure' if a.get('usage') is None and (a.get('transport') or {}).get('returncode') else 'invalid'
  tools[tool]+=1
  if tool=='read_entities':
   uptake['entity_queries']+=len(action.get('queries',[]))
   for q in action.get('queries',[]):
    uptake['operation_queries_excluding_conditional_future']+=q.get('kind')=='operations' and any(p.get('field')=='conditional' and p.get('op')=='eq' and p.get('value') is False for p in q.get('where',[]))
    uptake['operation_queries_explicitly_requesting_conditional_future']+=q.get('kind')=='operations' and any(p.get('field')=='conditional' and p.get('op')=='eq' and p.get('value') is True for p in q.get('where',[]))
    uptake['queries_with_fields']+='fields' in q
    uptake['queries_with_filter']+='where' in q
    uptake['queries_with_extended_predicates']+=any(p.get('op') not in ('eq','contains') for p in q.get('where',[]))
  if tool=='read_artifact':
   uptake['artifact_page_read_actions']+=action.get('format')=='page'
   uptake['batched_recovery_actions']+='lookups' in action
   uptake['exact_paths_recovered']+=len(action.get('lookups',[]))
  response=get(a['response_ref']) if 'response_ref' in a else {}
  if 'prompt_ref' in a:
   p=raw(a['prompt_ref']).decode();promptchars.append(len(p))
   try:
    frame=strict_json(p[p.index('\n{')+1:]);f=frame.get('last_tool_feedback') or {};uptake['prompts_with_offloaded_feedback']+=f.get('offloaded') is True;uptake['prompts_with_fact_memory']+='same_context_fact_memory' in frame;promptfeedbackchars.append(len(json.dumps(f,separators=(',',':'))))
   except Exception:pass
  point={'attempt_id':a['attempt_id'],'calls':n,'cumulative_model_seconds':seconds,'wall_seconds_since_first_attempt_including_inter_arm_and_recovery_wait':a.get('finished_epoch',time.time())-actual[0].get('started_epoch',actual[0]['reserved_epoch']),'known_reported_tokens':tokens,'unknown_usage':unknown,'finished_epoch':a.get('finished_epoch')}
  if tool in ('propose_delta','finalize_proposal'):milestones.setdefault('first_proposal',point.copy())
  if response.get('status')=='candidate_checked':milestones.setdefault('first_checked_proposal',point.copy())
  attempt_details.append({**point,'tool':tool,'status':a['status'],'result_status':response.get('status'),'duration_seconds':a.get('duration_seconds'),'usage':u,'queries':action.get('queries'),'recovery_lookups':action.get('lookups'),'artifact_read':({k:v for k,v in action.items() if k!='tool'} if tool=='read_artifact' else None)})
 plans=[candidates[c['candidate_ref']]['compiled']['plan'] for c in commits]
 candidate_summaries={}
 for a in actual:
  if 'response_ref' in a:
   response=get(a['response_ref'])
   if response.get('status')=='candidate_checked':candidate_summaries[response['candidate_ref']]=response.get('summary',{})
 new_tasks=[len(candidate_summaries.get(c['candidate_ref'],{}).get('added',[])) for c in commits]
 resultpath=O/(case+'.audited.result.json') if (O/(case+'.audited.result.json')).exists() else O/(case+'.result.json');result=json.loads(resultpath.read_text()) if resultpath.exists() else {}
 m=result.get('metrics') or {};families=list(m.get('production_family_statistics',{}).values())
 quality=None
 if m:
  trace=[get(h) for seq,h in db.execute('SELECT seq,object_ref FROM physical ORDER BY seq')];jobs={e['job']:e['machine'] for e in trace if e['kind']=='dispatch'};production={x['id'] for x in trace[0]['manifest']['machines'] if x['group']!='Delay_32'}
  quality={'weighted_tardy_lot_seconds':m['weighted_tardy_lot_seconds'],'throughput_lots':m['throughput_lots'],'production_operation_lots_completed':sum(e['kind']=='operation_complete' and result['start']<e['time']<=result['end'] and jobs.get(e.get('job')) in production for e in trace),'ready_wait_lot_seconds':sum(f['queue_wait_lot_seconds'] for f in families),'material_present_fraction':sum(f['material_present_observed_fraction']*f['machine_count'] for f in families)/sum(f['machine_count'] for f in families),'reserved_fraction':sum(f['reserved_observed_fraction']*f['machine_count'] for f in families)/sum(f['machine_count'] for f in families),'physical_valid':result['physical_audit']['prefix_valid_except_expected_missing_terminal'],'provenance_valid':result['provenance'].get('valid'),'cost_valid':result['cost'].get('valid'),'known_accounting_verified_with_authorized_unknown':result.get('known_accounting_verified_with_authorized_unknown',False)}
 row={'case':case,'variant':entry['variant'],'started':True,'complete':result.get('complete_common_window',False),'time':head['time'],'advanced_seconds':head['time']-entry['start'],'phase':head['phase'],'calls':len(actual),'input_tokens':sum(a['usage']['input_tokens'] for a in known),'cached_input_tokens':sum(a['usage'].get('cached_input_tokens',0) for a in known),'output_tokens':sum(a['usage']['output_tokens'] for a in known),'total_known_tokens':tokens,'unknown_usage':sum(a.get('usage') is None and a['status'] not in ('started','reserved') for a in actual),'pending_calls':sum(a['status'] in ('started','reserved') for a in actual),'closed_unknown_usage':sum(a.get('usage') is None and a['status'] not in ('started','reserved') for a in actual),'model_seconds':seconds,'failed_transport_seconds':sum(a.get('duration_seconds',0) for a in actual if a.get('usage') is None and a['status'] not in ('started','reserved')),'successful_model_seconds':sum(a.get('duration_seconds',0) for a in actual if a['status']=='processed'),'replans':len(feedback),'planning_rounds':len(plans),'demand_replan_triggers':sum(f['stop_reason']['reason']=='uncovered_demand' for f in feedback),'plans':len(plans),'plan_task_counts':[len(p['tasks']) for p in plans],'new_tasks_per_committed_plan':new_tasks,'actual_plan_seconds':[f['advanced_seconds'] for f in feedback],'stop_counts':dict(Counter(f['stop_reason']['reason'] for f in feedback)),'milestones':milestones,'tools':dict(tools),'transport_failures':tools['transport_failure'],'processed_response_calls':sum(a['status']=='processed' for a in actual),'completed_business_calls':sum(a['status']=='processed' and a['result_status'] not in ('rejected',None) for a in attempt_details),'uptake':dict(uptake),'mean_prompt_chars':sum(promptchars)/len(promptchars) if promptchars else None,'max_prompt_chars':max(promptchars,default=0),'quality':quality,'rejections':sum(x['result_status']=='rejected' for x in attempt_details),'attempt_details':attempt_details}
 rows.append(row);db.close()
complete=len(rows)==4 and all(r['complete'] for r in rows);comparisons=[]
if complete:
 base=next(r for r in rows if r['variant']=='baseline')
 for r in rows:
  if r==base:continue
  q,b=r['quality'],base['quality']
  checks={'weighted_tardiness_not_higher':q['weighted_tardy_lot_seconds']<=b['weighted_tardy_lot_seconds']+1e-6,'throughput_not_lower':q['throughput_lots']>=b['throughput_lots'],'completed_operations_not_lower':q['production_operation_lots_completed']>=b['production_operation_lots_completed'],'ready_wait_not_higher':q['ready_wait_lot_seconds']<=b['ready_wait_lot_seconds']+1e-6,'physical_and_provenance_valid':all(x[k] for x in (q,b) for k in ['physical_valid','provenance_valid']),'accounting_known_or_authorized_unknown_only':all(x['cost_valid'] or x['known_accounting_verified_with_authorized_unknown'] for x in (q,b))}
  comparisons.append({'variant':r['variant'],'call_reduction_fraction':1-r['calls']/base['calls'],'token_reduction_fraction':(1-r['total_known_tokens']/base['total_known_tokens']) if r['unknown_usage']==base['unknown_usage']==0 else None,'replan_reduction_fraction':1-r['replans']/base['replans'] if base['replans'] else None,'demand_replan_reduction_fraction':1-r['demand_replan_triggers']/base['demand_replan_triggers'] if base['demand_replan_triggers'] else None,'quality_checks':checks,'no_observed_regression':all(checks.values())})
summary={'schema':'context-2x2-analysis-v1','updated_epoch':time.time(),'complete_comparison':complete,'rows':rows,'comparisons':comparisons,'total_calls':sum(r.get('calls',0) for r in rows),'total_known_tokens':sum(r.get('total_known_tokens',0) for r in rows),'unknown_usage':sum(r.get('unknown_usage',0) for r in rows),'pending_calls':sum(r.get('pending_calls',0) for r in rows),'closed_unknown_usage':sum(r.get('closed_unknown_usage',0) for r in rows),'interpretation':'Same-window pilot only; incomplete arms do not establish savings. Model durations exclude inter-arm waiting. No exact currency estimate without verified applicable billing.'}
blocked_path=O/'recovery_exhaustion_audit.json'
blocked=json.loads(blocked_path.read_text()) if blocked_path.exists() else None
uncapped=(O/'recovery_activation_uncapped.json').exists()
if uncapped:blocked=None
if blocked and blocked['total_model_calls']==summary['total_calls'] and blocked['unknown_usage_calls']==summary['closed_unknown_usage'] and not summary['pending_calls']:
 summary['recovery_block']={k:blocked[k] for k in ['status','authorized_retries_used','global_recovery_slots_remaining','same_request_retries_remaining','same_request_retry_exact_bytes','original_attempts_and_physical_state_unchanged']}
else:blocked=None
if uncapped:summary['recovery_policy']='user_authorized_no_retry_count_cap; retain_all_unknown_usage; backoff_60_120_300_seconds'
(O/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
labels={'baseline':'现状','filter_projection':'只改过滤投影','targeted_recovery':'只改定向恢复','combined':'两者结合'}
lines=['B 上下文机制 2×2 实验结果', '状态：'+('四组均完成相同300秒窗口' if complete else '未形成完整四组比较；不得将未完成视为节省'),'','配置：t=2403→2703，gpt-6-astra / medium，原排程提示词与物理规则不变。基线对应已保存状态及此前隔离版本。外置门槛为原无损打包后12,000字符；组合组先投影再判断门槛。','']
for r in rows:
 if not r.get('started'):lines.append(labels[r['variant']]+'：尚未启动');continue
 p=r['milestones'].get('first_proposal');c=r['milestones'].get('first_checked_proposal')
 lines += [f"{labels[r['variant']]}：推进 {r['advanced_seconds']:.3f}/300秒；模型调用 {r['calls']}；已报告token {r['total_known_tokens']:,}；未知用量 {r['unknown_usage']}；规划执行段 {r['replans']}；窗口内新需求触发重排 {r['demand_replan_triggers']}。",'  首次提案：'+(f"第{p['calls']}次调用，累计模型耗时{p['cumulative_model_seconds']:.2f}秒，累计已知{p['known_reported_tokens']:,}token；此前未知用量{p['unknown_usage']}次" if p else '未产生'),'  首次静态检查通过的候选（不等于已执行或动态可行）：'+(f"第{c['calls']}次调用，累计模型耗时{c['cumulative_model_seconds']:.2f}秒" if c else '未产生'),f"  成功业务动作：{r['completed_business_calls']}；业务拒绝：{r['rejections']}；传输失败：{r['transport_failures']}；失败模型进程累计耗时：{r['failed_transport_seconds']:.2f}秒。",f"  工具分布：{json.dumps(r['tools'],ensure_ascii=False)}；计划总任务数（含沿用队列）：{r['plan_task_counts']}；每次新增任务数：{r['new_tasks_per_committed_plan']}。",f"  实际采用处理能力：{json.dumps(r['uptake'],ensure_ascii=False)}。"]
 if p:lines.append(f"  首提案实际经过时间：{p['wall_seconds_since_first_attempt_including_inter_arm_and_recovery_wait']:.2f}秒，包含组间轮转、人工恢复确认和退避等待，不能当作方案本身的速度比较。上方累计模型耗时包含失败进程耗时，但不含这些等待。")
 if r['quality']:lines.append('  质量/审计：'+json.dumps(r['quality'],ensure_ascii=False))
for c in comparisons:
 token_text=f"{c['token_reduction_fraction']:.1%}" if c['token_reduction_fraction'] is not None else '不可精确计算：保留未知用量'
 lines.append(f"{labels[c['variant']]}相对基线：调用减少 {c['call_reduction_fraction']:.1%}；token减少 {token_text}；规划执行段减少 {c['replan_reduction_fraction']:.1%}；新需求触发重排减少 {c['demand_replan_reduction_fraction']:.1%}；注册质量指标无观测退化：{c['no_observed_regression']}；详细检查：{json.dumps(c['quality_checks'],ensure_ascii=False)}。")
lines+=['',f"本实验累计实际模型调用 {summary['total_calls']}；已报告token {summary['total_known_tokens']:,}；未知用量 {summary['unknown_usage']}。","计数口径：规划执行段包括起始规划；uncovered_demand才是窗口中新需求触发的重排。终点2703处periodic_replan来自评价窗口截断，下一自然周期边界为3600，不是模型计划到期。\n限制：每组只有一次非确定性模型轨迹，只是300秒保存状态试验。原time_mode=paused_during_decision，模型调用和恢复等待期间仿真暂停；质量指标不包含这些现实延迟对车间的影响。不能据此证明统计非劣或长期全厂质量。material_present_fraction 是在制物料占机观测比例，含原引擎定义的停机延长，并非纯加工利用率。物理审计沿用原 semantic_coverage，未扩展CQT等未建模能力。","证据：experiment.json、verification.json/log、recovery_verification_v2.json/log、summary.json、interruption_audit.json、recovery_exhaustion_audit.json，以及 runs 下不可变对象/事件账本。完整窗口结果文件仅在各组实际完成后生成。","隔离：原先实验和正在运行的 B 没有被本试验写入或重启。"]
if blocked:
 lines += ['', '本次恢复结果：只新增了1次实际模型调用；原失败请求与重试的提示词、schema、上下文完全相同。重试在40.04秒后再次响应流断开，进程已退出，输出为空，用量未知。未重置原有账本或预算。', '恢复限制：同请求最多1次的额度已用尽。全实验剩余1次额度目前不能用于同一请求的第二次重试，因此全组冻结，没有正在运行的实验模型进程。', '结论：累计7次实际模型调用，已知token下界102,777，另有2次未知用量；四组均未推进300秒评价窗口，不能比较节省或判定质量无下降。网络响应流错误无法单独证明是过滤投影设计造成，也不能定位具体网络或服务端故障环节。', '已核对：两次失败原始对象哈希、进程退出证明、首次中断前的所有attempt哈希、四组state_ref/time/revision/context_ref与物理事件序列均保留。第二次只读快照位于recovery_exhaustion_evidence，第一次中断证据未覆盖。']
if uncapped:lines += ['', '后续授权：用户明确取消恢复次数限制并要求完成四组。连续失败等待60/120/300秒，之后保持300秒；每次请求独立计账，未知用量保留。两次历史冻结证据仅代表当时边界，不代表当前仍按旧次数上限冻结。', '验证：recovery_verification_v3.json 保留24项恢复规则验证；recovery_activation_uncapped.json 证明首次取消恢复次数限制时保留7次调用、2次未知。调用次数修订阶段recovery_verification_v4.json有26项通过验证；count_revision_activation.json证明解除每组60次/共同240次调用上限时保留175次调用和9次未知，四组状态及全部attempt/恢复记录未改变。在v4阶段原调用上限仅作参考，其他资源上限尚未改变。']
if (O/'completion_budget_activation.json').exists():lines += ['', '完成预算修订：recovery_verification_v5.json为当前26项通过验证；completion_budget_activation.json保留255次既有调用及10次未知。按用户授权，四组统一取消次数与token总量硬上限，累计模型时长改为每组7200秒/共享28800秒，运行时长改为57600秒。原配置和所有成本保留，模型、单次600秒超时、四组处理及物理规则不变。前述v4是历史阶段。']
if any((O/(case+'.audited.result.json')).exists() for case in reg['execution_order']):lines += ['', '用量审计补充：原始.result.json保留预算展示标签original_model_seconds缺失的报错；只读repair_cost_audit_view.py从原sealed manifest补齐这一标签，未改变任何限额、用量、原始记录或仿真。重新执行原audit_cost并校验已知用量与全部授权失败，结果另存.audited.result.json。未知用量仍使严格零未知成本审计为false。']
(O/'实验结果.txt').write_text('\n'.join(lines)+'\n');print(json.dumps({k:v for k,v in summary.items() if k!='rows'},ensure_ascii=False))
for r in rows:print(json.dumps({k:v for k,v in r.items() if k not in ('attempt_details','quality')},ensure_ascii=False))
