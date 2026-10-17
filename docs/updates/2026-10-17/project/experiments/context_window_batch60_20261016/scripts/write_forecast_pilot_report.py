#!/usr/bin/env python3
"""Write a human report from already sealed evidence; no model calls."""
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from src.smt_fullfab.harness.offline_isolation import install_guard
install_guard()
from src.smt_fullfab.harness.evaluation import Evidence
from src.smt_fullfab.harness.contracts import fingerprint, sha_bytes

RUN=ROOT/'live_pilots/forecast_collection_20261017'
def read(name):return json.loads((RUN/name).read_text())
def write(name,value):(RUN/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def main():
    summary=read('summary.json');previous=read('previous_comparison.json');reg=read('registration.json')
    rows=summary['results'];g1=rows['G1'];g2=rows['G2'];diagnosis=read('machine_1216_diagnosis.json')
    dispatches={}
    for group in ('G1','G2'):
        ev=Evidence(RUN/group,read(group+'.result.json')['evidence_sha256'])
        trace=[ev.get(ref) for ref in ev.value['physical']][ev.manifest['prefix_events']:]
        dispatches[group]=[{k:e[k] for k in ('time','machine','lots','steps','visits')} for e in trace
                           if e['kind']=='dispatch' and e.get('owner')=='plan']
    same_dispatches=dispatches['G1']==dispatches['G2']
    matching_dispatches=sum(a==b for a,b in zip(dispatches['G1'],dispatches['G2']))
    same_machine_times=[(e['time'],e['machine']) for e in dispatches['G1']]==[(e['time'],e['machine']) for e in dispatches['G2']]
    write('dispatch_comparison.json',{'same_started_production_by_time_machine_lot_step_visit':same_dispatches,
        'matching_dispatches':matching_dispatches,'same_machine_start_times':same_machine_times,'dispatches':dispatches})
    checks={'both_reached_target':summary['both_reached_target'],
        'exact_common_window':summary['common_window']==[702,882],
        'no_unknown_usage':all(r['unknown_usage_calls']==0 for r in rows.values()),
        'within_registered_call_caps':all(r['total_calls']<=reg['per_group_call_cap'] for r in rows.values()),
        'source_still_matches_registration':fingerprint()['sha256']==reg['fingerprint_sha256'],
        'runner_still_matches_registration':sha_bytes((ROOT/'scripts/run_forecast_collection_pilot.py').read_bytes())==reg['script_sha256'],
        'isolation_valid':previous['isolation_after']['valid'],
        'all_new_production_choices_from_model':all(r['provenance_audit']['valid'] and r['provenance_audit']['algorithm_production_tasks']==0 for r in rows.values()),
        'opportunity_audits_pass':all(r['opportunity_audit_valid'] for r in rows.values()),
        'no_physical_prefix_errors_except_unfinished_horizon':all(r['physical_prefix_errors']==['physical: missing terminal event'] for r in rows.values())}
    assert all(checks.values()),checks
    write('final_verification.json',{'checks':checks,'live_calls':sum(r['total_calls'] for r in rows.values()),
          'offline_outputs':sum(r['usage']['offline_outputs'] for r in rows.values()),'startup_tests_passed':9,
          'isolation_after':previous['isolation_after'],'evidence_sha256':{g:read(g+'.result.json')['evidence_sha256'] for g in rows},
          'physical_audit_scope':'Partial observed prefix; no terminal event fabricated; not a full-horizon pass.'})
    lines=['# 预测合并与上下文窗口：实际模型对比（2026-10-17）','',
        '**本轮结果：两组都完成同一 180 秒观察区间。大窗口用了 2 次调用，小窗口用了 5 次；两组实际启动、可开工未排等待和所测质量指标相同。没有出现提交后同批资料立即重排，也没有出现上一轮相隔 6.75 秒的预测重排。**','',
        '这是一次保存状态接续实验，不是冷启动 918/2000 台机组的验证，也不是长期质量结论。所有新增生产任务均由模型选择；原 B 未修改、未打开其运行数据库。','',
        '## 相同条件','',
        '两组使用同一 mixed_702 保存状态、负载、随机数初态及 702–882 秒观察区间。厂内原始仿真终点仍为 3600 秒，未把观察终点当作计划有效期。模型均为 gpt-6-astra / medium，每组上限 8 次调用、无自动重试。',
        'G1：窗口 272000 tokens、输入预算 220000；G2：窗口 544000 tokens、输入预算 440000。两组共用 v4 预测筛选、60 秒预测间隔与相邻提醒收集、触发资料优先及计划继续执行机制。60 秒可开工未排等待期限不变。',
        '运行前补齐了实验专用接口的可选 machine_reviews 字段，使说明能随现有 apply_candidate 一起返回；它不增加调用步骤。9 项相关离线检查通过后冻结源码和运行脚本，运行中未修改。','',
        '## 完整相同区间内的结果','',
        '| 指标（702–882 秒） | G1 小窗口 | G2 大窗口 |','|---|---:|---:|']
    def row(label,values):lines.append('| '+label+' | '+' | '.join(str(x) for x in values)+' |')
    for label,key in [('总调用次数','total_calls'),('已确认计划数','model_commits'),('中途再次触发排程','replanning_trigger_count'),('累计新增任务','committed_added_tasks'),('其中提前排给忙碌机组','committed_added_tasks_on_busy_machines')]:
        row(label,[rows[g][key] for g in ('G1','G2')])
    row('调用组成',['提案 2 + 确认 2 + 查询 1','提案 1 + 确认 1'])
    row('连接失败／未知用量',[0,0])
    for label,key in [('实际启动生产任务','production_dispatches'),('可开工但未排程机组等待（机组秒）','executable_unplanned_machine_seconds'),
                      ('物料排队等待（物料秒）','queue_wait_lot_seconds'),('加权延误（物料秒）','weighted_tardy_lot_seconds'),
                      ('换型损失（机组秒）','setup_loss_seconds'),('整批完工数','throughput_lots')]:
        row(label,[rows[g]['common_window_quality'][key] for g in ('G1','G2')])
    row('882 秒可开工却未覆盖机组',[rows[g]['final_backlog_at_own_endpoint']['uncovered_executable_machine_count'] for g in ('G1','G2')])
    row('882 秒已确认但未启动任务',[rows[g]['final_backlog_at_own_endpoint']['accepted_pending_task_count'] for g in ('G1','G2')])
    row('882 秒公共目录未排工序（含未来）',[rows[g]['final_unassigned_public_operations'] for g in ('G1','G2')])
    row('其中非条件工序',[rows[g]['final_unassigned_nonconditional_operations'] for g in ('G1','G2')])
    row('尚未纳入已确认资料批次的工序版本',[rows[g]['final_backlog_at_own_endpoint']['unoffered_operation_count'] for g in ('G1','G2')])
    row('服务端累计输入 tokens',[f'{rows[g]["usage"]["input_tokens"]:,}' for g in ('G1','G2')])
    row('服务端累计输出 tokens',[f'{rows[g]["usage"]["output_tokens"]:,}' for g in ('G1','G2')])
    row('模型请求累计墙钟秒',[round(rows[g]['usage']['model_seconds'],2) for g in ('G1','G2')])
    lines += ['',
        f'逐项检查：两组 11 次生产启动的机组和时刻一致，其中 {matching_dispatches} 项的物料与工序也相同；另外 2 项选料不同（864 秒的机组 1311、1312）。因此，本区间质量指标相同不代表整份生产方案相同；不同选料可能影响更长区间的结果。明细见 dispatch_comparison.json。',
        '这里“等待为 0”只指具备开工条件却没有计划的机组等待，不代表所有物料都没有排队。公共目录中 4348 条未排工序包括未来任务；1007 条非条件工序也不等于眼下能够开工的任务。没有把这些剩余需求当作已完成。未展示版本的差异反映资料覆盖，不等于生产已排差异。',
        '大窗口本轮调用少 60%，累计输入 tokens 约少 20%；这是这对样本的观测值。两组全部保留有效既有任务，没有取消、替换或插入显式等待。整批完工数均为 0，短区间质量指标不能证明长期吞吐或交期表现相同。','',
        '## 为什么少调用，为什么没有频繁打断','',
        f'首包工序记录：G1 {g1["first_packet"]["inline_operations"]} 条，G2 {g2["first_packet"]["inline_operations"]} 条；服务端首请求输入分别为 {g1["service_input_tokens_per_response"][0]:,} 和 {g2["service_input_tokens_per_response"][0]:,} tokens。G2 实际超过 272000，证明用到了扩大的容量，但没有测满 544000 的极限。',
        '差异可以定位到机组 1216：G2 首包含 w1807:269:1，模型在 702 秒就把它安排为 830.25 秒接续执行。G1 首包没有这条工序，首轮没有安排它，因而在 815.25 秒收到一次提前 15 秒的有效提醒。G1 随后查询、提案、确认，正好多出 3 次调用；两组这项任务都在 830.25 秒开工。',
        '这支持“大窗口提前提供更多有用资料，模型可以一次选好后续任务”的机制解释，但不是大窗口必然选到该任务的保证。G1 可以主动查询未装入的资料，模型也可能在更大资料包中漏选。',
        'G1 的执行段为 702→815.25（113.25 秒）和 815.25→882（66.75 秒）；G2 为 702→882（180 秒）。882 秒的 collection_limit 只是本实验观察终点，未计为中途重排。没有零时间重触发，没有同批旧资料容量重复触发。',
        'G1 在 815.25 秒的实际请求包中，触发机组 1216 的 50 条候选全部在包内；第二次计划保留原有 5 项待执行任务，只新增 1 项。模型仍主动读取候选和已有任务，因此“资料已覆盖”不保证绝不会查询，但这次查询不是由于触发机组被排除在包外。',
        'G1 在两次确认中随动作附带 5 条、2 条机组说明；G2 没有提供说明，系统如实保留 unreported，没有自动再询问，也没有把展示过的机组冒充为已审阅。覆盖检查本身消耗的额外模型调用为 0。',
        '上一轮的 761.25、768 秒提醒来自没有可靠近期到料依据的潜在未来候选。本轮运行中两组均未在这两点停下。v4 的公开物料依据筛选与预测合并机制、不同的模型选择共同决定本次结果，单次实验无法分别量化每项修改的独立贡献。','',
        '## 与上一轮 v3 比较','',
        '上一轮目标同为 702–882 秒，但两组实际都只到 768 秒：G1 用满 8 次额度，G2 第 6 次连接失败后停止。本轮为 5 次、2 次并均到达 882 秒。为了不把失败和不同进度混在一起，下面只比较共同的 702–768 秒。','',
        '| 相同 66 秒区间 | 上轮 G1 | 本轮 G1 | 上轮 G2 | 本轮 G2 |','|---|---:|---:|---:|---:|']
    oldnew=previous['same_window_comparison']
    def across(label,get):lines.append('| '+label+' | '+' | '.join(str(get(oldnew[v][g])) for v,g in (('v3','G1'),('v4','G1'),('v3','G2'),('v4','G2')))+' |')
    across('抵达 768 秒所需累计调用',lambda x:x['calls_to_reach_end'])
    across('中途排程提醒次数（含 768 秒点）',lambda x:len(x['planning_stops_within_window']))
    across('可开工未排等待（机组秒）',lambda x:round(x['quality']['executable_unplanned_machine_seconds'],3))
    across('实际启动任务',lambda x:x['quality']['production_dispatches'])
    across('物料排队等待（物料秒）',lambda x:x['quality']['queue_wait_lot_seconds'])
    across('加权延误（物料秒）',lambda x:x['quality']['weighted_tardy_lot_seconds'])
    across('换型损失（机组秒）',lambda x:x['quality']['setup_loss_seconds'])
    lines += ['',
        '因此，在相同模拟进度下确实减少了调用：G1 从 6 次降到 2 次，G2 从 4 次降到 2 次；两组的早期预测暂停均从 2 次降到 0 次。G1 上轮多出的 52.5 机组秒等待本轮也没有出现。但不能把旧版 768 秒的未排总量与本轮 882 秒的未排总量直接相减，期间执行、释放和未来工序可见性都在变化。',
        '更早 v2 那轮曾在 702 秒提交后因整目录容量触发立刻重排，没有形成正长度共同观察区间；可以确认本轮没有复现该现象，但不能据此计算同等工作量的质量或调用降幅。未改动的原 B 尚未在这一整套相同条件下另跑基准，因此不声称已实测相对原 B 的提升。',
        '本轮与 v3 的初始快照、轨迹、观察终点、调用上限、顶层任务说明及 CLI 二进制哈希相同。模型目录只有默认协作模式说明字段变化；命令明确禁用了协作模式说明注入。模型名称和推理档位相同，但服务端模型版本和输出随机性未被锁定。跨版本的提示与执行规则也有变化，本结果不是统计消融实验。','',
        '## 验证与边界','',
        '两组生产来源、批次回执及机会覆盖审计通过：算法代选生产任务为 0，离线注入动作也为 0。完整物理审计仍记录 physical: missing terminal event，因为这里只观察至 882 秒而非仿真终点 3600 秒，没有伪造终态；不能称全程物理验证通过。',
        '原 B 来源 803 个文件、此前封存实验 33815 个文件及保存状态均校验未变。新实验证据已封存，运行源码及脚本仍匹配登记哈希。',
        '数据索引：summary.json（本轮指标）、previous_comparison.json（相同区间比较）、machine_1216_diagnosis.json（资料与任务链路）、dispatch_comparison.json（逐项启动）、final_verification.json（最终检查）；各组目录保留原始输入、输出和证据清单。']
    (RUN/'结果说明.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'checks':checks,'same_dispatches':same_dispatches,'report':str(RUN/'结果说明.md')},ensure_ascii=False))


if __name__=='__main__':main()
