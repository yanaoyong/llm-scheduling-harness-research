from pathlib import Path
import json
O=Path(__file__).resolve().parent;s=json.loads((O/'summary.json').read_text())
labels={'baseline':'现状','prompt':'只改提示词','prompt_context_feedback':'提示词＋上下文＋效率反馈'}
lines=['排程覆盖三组对照实验', '',f"已结束 {s['finished_cells']}/9；完整完成统一 300 秒窗口 {s['completed_cells']}/9。",'同一保存状态的三个分支使用完全相同的私有状态、原有计划、事件前缀和随机状态；共采用 t=702、1800、2403 三个保存状态。模型、工具协议、物理执行规则相同。原 B 未切换到实验版本。','', '每个状态的结果（调用包含所有读取、提案、检查后的应用及失败；重排按已应用并执行的计划轮次计）：']
for r in s['rows']:
 lines += [f"{r['state']} | {labels[r['variant']]} | {'完整' if r['complete'] else '未完成'} | 推进 {r['seconds']:.3f} 秒 | 重排 {r['replans']} | 调用 {r['calls']} | token {r['tokens']:,}",f"  平均计划任务 {r['mean_tasks']}；最大机组队列 {r['max_queue_depth']}；生产工序完成 {r['operation_lots_completed']}；整批完工 {r['throughput_lots']}；加权延期 {r['weighted_tardy_lot_seconds']}；ready 等待面积 {r['ready_wait_lot_seconds']:.3f}。",f"  物理约束 {r['physical_valid']}；模型决策来源 {r['provenance_valid']}；调用用量审计 {r['cost_valid']}；读取/决策工具分布 {json.dumps(r['tool_calls'],ensure_ascii=False)}。"]
lines += ['', '同状态配对结果：']
for c in s['paired_comparisons']:
 lines += [f"{c['state']} | {labels[c['variant']]} | 重排减少 {c['replan_reduction_fraction']:.1%} | 调用减少 {c['call_reduction_fraction']:.1%} | token 减少 {c['token_reduction_fraction']:.1%} | 注册质量指标全部不退化 {c['no_observed_regression_on_registered_metrics']}",f"  {json.dumps(c['quality_checks'],ensure_ascii=False)}"]
if not s['paired_comparisons']:lines += ['尚无完整共同窗口，不能给出节省比例或质量不下降的结论。']
lines += ['', '三个完整状态合计（仅全部完整时计算，负的“减少”表示增加）：']
for a in s['aggregates_all_three_complete_states_only']:
 lines += [f"{labels[a['variant']]} | 重排 {a['replans']} | 调用 {a['calls']} | token {a['tokens']:,} | 调用/模拟分钟 {a['calls_per_simulated_minute']:.3f}"]
 if a['variant']!='baseline':lines += [f"  重排减少 {a['replan_reduction_fraction']:.1%}；调用减少 {a['call_reduction_fraction']:.1%}；各状态质量检查全部通过 {a['all_paired_quality_checks_pass']}。"]
lines += ['', '实现内容：提示词将一次决策明确为未来 300 秒的滚动全厂计划；允许一次提交多机组、多任务及明确排序，要求兼顾近期变为可用的资源。增强上下文提供各机组公开可用时间、就绪与条件工序数量、排队覆盖，并反馈已完成轮次推进时间、任务数、调用数和单位推进成本。效率目标低于合法性、延期、产出和等待指标。', '原工具仍要求模型明确选择批次、工序、机组和顺序；没有加入算法代排、自动补任务或静默修复。新的实验入口、继承状态和评估截点仅存在于隔离副本，原始物理规则未改变。', '', '已发现的读取开销：一次 read_entities 即使包含多个查询，现有事实记忆仍在第二次 read_entities 后才启用；大结果压缩为预览后，模型可能转而用 read_artifact 逐页补读。仅强调扩大覆盖范围会增加读取工作，新增概览不等于无需读取具体工序事实。该机制本轮保持冻结，没有中途改工具来改变对照。', '', '边界：每个单元格只有一条模型轨迹，模型输出不可固定随机种子；三个短窗口不能证明长期质量非劣。三组均继承同一条上轮 selection_note，旧工具历史与事实缓存统一清空；增强组额外看到前八轮公开效率记录。', '执行中发生用户误清理重复文件。实验按原哈希恢复缺失文件并继续同一账本，未重复请求已有模型结果、未重置调用预算。墙钟时间包含该中断，因此效率结论采用实际模型调用、报告 token 和模拟推进时间，不把外部恢复耗时计为模型效果。', '', '复核入口：summary.json 为结构化结果；*.result.json 为每个分支审计及指标；runs/*/evidence_manifest.json 为封存证据；isolated_changes.patch 为代码差异；verification.json 记录 98 项离线检查通过；recovery_completed.json 记录恢复校验。']
lines += ['', '读取阶段快照的进一步证据（memory_pressure_preview.json）：六个改动分支在第 10 至 12 次调用附近，完整已读事实连同输入需要约 14.7 万至 20.1 万字符，超过 12 万字符上限，均已转为事实目录加外部值引用。移除新增覆盖概览和效率反馈后仍超限，不能将全部分页开销归因于新增概览。现有查询过滤只支持 eq / contains，不能直接用 available_at <= 窗口结束筛选；这也是默认近期资源概览的用途。该快照只用于解释读取机制，不替代完整窗口效果。']
(O/'实验结果.txt').write_text('\n'.join(lines)+'\n')
print(O/'实验结果.txt')
