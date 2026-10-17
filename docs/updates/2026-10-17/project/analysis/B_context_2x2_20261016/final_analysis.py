"""Produce a readable interpretation only after all four registered windows finish."""
from pathlib import Path
import json
O=Path(__file__).resolve().parent;s=json.loads((O/'summary.json').read_text());assert s['complete_comparison'] and s['pending_calls']==0
labels={'baseline':'现状','filter_projection':'只改过滤投影','targeted_recovery':'只改定向恢复','combined':'两者结合'}
lines=['四组上下文实验：完整窗口结果与解释','','四组均从同一保存状态 t=2403 跑到2703，共300秒。模型为 gpt-6-astra / medium；原排程提示词、仿真物理规则、事实记忆规则和模型配置一致，仅上下文工具呈现/定向恢复能力不同。外置门槛为原无损打包后的工具反馈超过12,000字符（不是12,000 token）；组合组先投影再判断门槛。正在跑的 B 未被本实验写入、暂停或重启。','','模型调用与上下文成本（全部传输失败和纠错保留）','方案 | 总调用 | 成功业务动作 | 业务拒绝 | 传输失败 | 已知token下界 | 首提案累计模型秒 | 规划轮次/新需求重排数']
for r in s['rows']:
 p=r['milestones']['first_proposal'];lines.append(f"{labels[r['variant']]} | {r['calls']} | {r['completed_business_calls']} | {r['rejections']} | {r['transport_failures']} | ≥{r['total_known_tokens']:,} | {p['cumulative_model_seconds']:.2f} | {r['plans']}/{r['demand_replan_triggers']}")
 lines.append(f"  首提案前已知成功响应进程耗时：{sum(a['duration_seconds'] or 0 for a in r['attempt_details'][:p['calls']] if a.get('usage') is not None):.2f}秒；未知用量请求{p['unknown_usage']}次；真实经过时间{p['wall_seconds_since_first_attempt_including_inter_arm_and_recovery_wait']:.2f}秒（包含轮转、确认与退避等待，不能当作该方案固有速度）。")
lines += ['',f"合计：{s['total_calls']}次模型调用，已知token至少{s['total_known_tokens']:,}，另有{s['unknown_usage']}次关闭的传输失败未报告用量。token采用CLI返回input+output，不能推算未知部分，不能把各下界差异当成精确总token节省。没有额外摘要模型调用。规划轮次包含起始规划；新需求重排数只计窗口内uncovered_demand。终点2703的periodic_replan是评价窗口截断，下一自然周期边界3600；不能把它归为120秒计划到期。",'原每组60次/共同240次调用上限及token总量硬上限已按用户授权统一取消；累计模型时长为每组7200秒/共享28800秒，运行时长57600秒。模型和单次600秒超时不变；所有原始限制、修订、调用与失败账本均保留。', '', '排程质量：共同300秒窗口','方案 | 加权拖期lot-seconds↓ | 完成lot数↑ | 生产工序完成lot数↑ | ready等待lot-seconds↓ | 物理/溯源审计']
for r in s['rows']:
 q=r['quality'];lines.append(f"{labels[r['variant']]} | {q['weighted_tardy_lot_seconds']:.6f} | {q['throughput_lots']} | {q['production_operation_lots_completed']} | {q['ready_wait_lot_seconds']:.6f} | {q['physical_valid']}/{q['provenance_valid']}")
for c in s['comparisons']:
 lines.append(f"{labels[c['variant']]}相对现状：总调用变化{-c['call_reduction_fraction']:.2%}，规划执行段数变化{-c['replan_reduction_fraction']:.2%}，新需求重排数变化{-c['demand_replan_reduction_fraction']:.2%}；注册指标全部无观测退化={c['no_observed_regression']}。逐项检查：{json.dumps(c['quality_checks'],ensure_ascii=False)}")
lines += ['', '机制证据与解释']
for r in s['rows']:
 u=r['uptake'];lines.append(f"{labels[r['variant']]}：平均输入提示字符{r['mean_prompt_chars']:.0f}（字符不是token）；外置反馈出现{u.get('prompts_with_offloaded_feedback',0)}次；精确恢复调用{u.get('batched_recovery_actions',0)}次/路径{u.get('exact_paths_recovered',0)}条；原文分页读取{u.get('artifact_page_read_actions',0)}次；新增谓词查询{u.get('queries_with_extended_predicates',0)}次。每轮新增任务数：{r['new_tasks_per_committed_plan']}；停止原因：{json.dumps(r['stop_counts'],ensure_ascii=False)}。")
dispatch=json.loads((O/'dispatch_diagnostics.json').read_text())
for r in dispatch['rows']:
 for item in r['future_tasks']:
  task=item['task'];events=item['matching_dispatch_events'];lines.append(f"{labels[r['variant']]}预排任务{task['id']}：创建于{item['created_at']:.6f}，not_before={task['not_before']}；真实派工记录={[{'time':e['time'],'machine':e['machine'],'lots':e['lots']} for e in events]}。没有派工记录时不得记为已执行收益。")
lines.append('预排任务若在机组实际释放时直接执行，可以减少该时刻的重排；这是具体执行链条的证据。单次非确定性轨迹不能证明上下文压缩必然促使模型预排更多任务。新增筛选算子与精确恢复的使用次数也应结合解读，不能把未充分使用的能力认定为无效。')
lines += ['过滤投影会直接移除重复包装；定向恢复需模型按需取回原文，可能增加一次读取。两者结合时先投影，结果低于外置阈值就不会再次外置，因此效果不应期待简单相加。','本试验新增的数值/集合谓词与精确恢复均由模型自选，没有自动排序任务或代替模型编排；基线本来已支持批量查询、字段投影和基础等值/包含筛选。','多数模型决策仍沿用读取、提案、提交的三次调用链。短结果主要降低每次输入，未必改变计划覆盖范围。原提示词示例会筛选conditional=false，默认未来工序虽可查询但模型经常只查询当前可做任务；这是可检验的覆盖偏向，不能由本次未改变提示词的实验单独证明因果。','两组发生过完整scope列表重复ID而被拒绝。可另测由宿主绑定不可变scope引用，减少复制大量ID引起的纠错；本次没有修改这一协议。', '', '建议的下一步（本次未实施）','先依据完整窗口质量与真实调用结果选择有收益的呈现方式；若要进一步减少重排，应单独测试默认提供有限未来可行任务，以及清晰的覆盖目标和执行反馈。若要减少固定提交调用，可另测在既有校验通过后由宿主执行明确授权的提交，保持风险与质量指标单独验证。不要仅凭输入缩短直接推广到 B。', '', '结论边界','每组仅一条非确定性轨迹、同一300秒样本，不是统计非劣实验。仿真在模型思考/网络等待时暂停，质量指标不包含现实车间因此产生的延迟。物料占机观测比例含原引擎停机延长，不能等同纯加工利用率。原语义覆盖未增加CQT等未建模能力。未知用量导致严格零未知成本审计为false；物理与溯源审计、已知用量及获授权关闭失败的完整性分别报告。','用量审计的展示字段original_model_seconds缺失已通过只读适配补齐，值来自原始sealed manifest。原报错.result.json与证据未覆盖；.audited.result.json仅替换重算的成本审计及授权未知用量核验，原模型调用/仿真/质量/限额均保持。\n证据索引：实验结果.txt（详细统计）、summary.json、completion_verification.json、behavior_diagnostics.json、dispatch_diagnostics.json、context_input_breakdown.json、各组原始.result.json、补充.audited.result.json及不可变对象账本。']
base=next(r for r in s['rows'] if r['variant']=='baseline');filtered=next(r for r in s['rows'] if r['variant']=='filter_projection')
lines[2:2]=[f"核心结果：四组均完整结束，但实测总模型调用没有低于现状。过滤投影的新需求重排从{base['demand_replan_triggers']}次降为{filtered['demand_replan_triggers']}次；扣除传输失败后的调用从{base['calls']-base['transport_failures']}次降为{filtered['calls']-filtered['transport_failures']}次（含业务纠错），但传输失败多{filtered['transport_failures']-base['transport_failures']}次，最终总调用从{base['calls']}次增为{filtered['calls']}次。",'本窗口登记的排程质量指标四组完全一致，物理与溯源审计均通过。总token只能报告已知下界，不能给出精确总耗用降幅。','']
(O/'完整实验结论.txt').write_text('\n'.join(lines)+'\n');print(str(O/'完整实验结论.txt'))
