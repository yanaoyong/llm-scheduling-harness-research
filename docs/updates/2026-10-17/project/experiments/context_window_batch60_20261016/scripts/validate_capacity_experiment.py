#!/usr/bin/env python3
"""Guarded local validation. No model transport, child process, network, or B run."""
from pathlib import Path
import sys
import os
import tempfile
import json
import hashlib
import io
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
os.chdir(ROOT)
(ROOT/'.tmp').mkdir(exist_ok=True)
os.environ['TMPDIR']=str(ROOT/'.tmp');tempfile.tempdir=str(ROOT/'.tmp')
from src.smt_fullfab.harness.offline_isolation import install_guard
install_guard()
from src.smt_fullfab.harness.capacity_config import experiment_config
from src.smt_fullfab.harness.contracts import encode_model_schema
from src.smt_fullfab.harness.transport import response_schema, BASE_INSTRUCTIONS
from src.smt_fullfab.harness.local_tokens import count


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def source_verification():
    manifest=json.loads((ROOT/'isolation_manifest.json').read_bytes());source=Path(manifest['source_root'])
    changed=[];linked=[]
    for relative,expected in manifest['source_hashes'].items():
        p=source/relative;q=ROOT/relative
        if not p.is_file() or sha(p)!=expected:changed.append(relative)
        if q.is_symlink() or (p.stat().st_dev,p.stat().st_ino)==(q.stat().st_dev,q.stat().st_ino):linked.append(relative)
    fixture_changes=[k for k,v in manifest['fixture_sha256'].items() if sha(ROOT/'fixtures'/k)!=v]
    archive=ROOT/'reports/archive_v3_before_forecast_v4_20261017/archive_manifest.json'
    sealed=json.loads(archive.read_bytes())['sealed_pilot_files']
    changed_sealed=[k for k,v in sealed.items() if not (ROOT/k).is_file() or sha(ROOT/k)!=v]
    return {'source_files_checked':len(manifest['source_hashes']),'changed_source_files':changed,
            'linked_to_source':linked,'changed_fixtures':fixture_changes,
            'original_run_database_opened':False,
            'sealed_pilot_files_checked':len(sealed),'changed_sealed_pilot_files':changed_sealed,
            'valid':not(changed or linked or fixture_changes or changed_sealed)}


def guard_verification():
    import socket,subprocess
    checks={}
    for name,fn in [('network',lambda:socket.socket()),('child_process',lambda:subprocess.Popen(['/usr/bin/true'])),
                    ('external_write',lambda:(ROOT.parent/'forbidden-validation-write').open('w'))]:
        try:fn()
        except (RuntimeError,ValueError) as exc:checks[name]=type(exc).__name__+': blocked before effect'
        else:raise AssertionError(name+' was not blocked')
    return checks


def main():
    started=time.perf_counter();before=source_verification()
    if not before['valid']:raise RuntimeError('Source/fixture isolation mismatch: '+json.dumps(before))
    guards=guard_verification()
    for group in ('G1','G2'):
        (ROOT/'configs/capacity'/f'{group}.json').write_text(json.dumps(experiment_config(group),ensure_ascii=False,indent=2)+'\n')
    names=['tests.test_capacity_batch60_experiment','tests.test_capacity_two_strategy','tests.test_capacity_forecast_collection',
           'tests.test_capacity_live_pilot','tests.test_smt_fullfab_audit',
           'tests.test_smt_fullfab_not_before_audit','tests.test_smt_fullfab_plan_delta',
           'tests.test_smt_fullfab_delta_session','tests.test_smt_fullfab_stream_opportunity_audit',
           'tests.test_smt_fullfab_harness_lossless_presentation.LosslessPresentationTests.test_T11_T12_roundtrip_types_absence_order_and_marker_collisions']
    suite=unittest.defaultTestLoader.loadTestsFromNames(names)
    stream=io.StringIO()
    class ProgressResult(unittest.TextTestResult):
        def startTest(self,test):
            super().startTest(test)
            print('CHECK '+test.id(),flush=True)
    result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=ProgressResult).run(suite)
    from tests.test_capacity_batch60_experiment import CapacityAndIsolationTests,CollectionMechanismTests
    from tests.test_capacity_two_strategy import BatchLifecycleTests,PairedSavedStateTests
    from tests.test_capacity_forecast_collection import ForecastCollectionTests,SavedEvidencePacketTests
    schema_tokens=count(encode_model_schema(response_schema('B',planning_reviews=True)).decode())
    system_tokens=count(BASE_INSTRUCTIONS)
    wrapper={'schema_tokens':schema_tokens,'system_instruction_tokens':system_tokens,
             'configured_reserve_tokens':10000,'remaining_for_cli_framing':10000-schema_tokens-system_tokens,
             'server_alias_mapping_verified':False,'server_framing_measured':False}
    after=source_verification()
    # All models remain disabled; injected replay actions are explicitly fixtures.
    report={'schema':'forecast-collection-offline-validation-v4','date':'2026-10-17',
            'passed':result.wasSuccessful() and after['valid'] and wrapper['remaining_for_cli_framing']>0,
            'tests_run':result.testsRun,'failures':[(str(t),msg) for t,msg in result.failures],
            'errors':[(str(t),msg) for t,msg in result.errors],
            'model_calls':0,'model_quality_evaluated':False,'actual_call_reduction_evaluated':False,
            'groups':{g:experiment_config(g)['capacity_experiment'] for g in ('G1','G2')},
            'packet_capacity':CapacityAndIsolationTests.measurements,
            'dynamic_collection':CollectionMechanismTests.measurements,
            'initial_partition':BatchLifecycleTests.measurements,
            'paired_continuation':PairedSavedStateTests.measurements,
            'forecast_collection':ForecastCollectionTests.measurements,
            'trigger_packet_regression':SavedEvidencePacketTests.measurements,
            'wrapper_measurement':wrapper,'isolation_before':before,'isolation_after':after,'guards':guards,
            'scope':'Saved-state replay plus synthetic 2000-machine public-input stress; no claim of a validated 2000-machine physical factory.',
            'audit_scope':'Independent source/ready-demand/physical-prefix checks; prefix has no invented terminal. Capacity packing and forecast causality tested separately.',
            'elapsed_wall_seconds':round(time.perf_counter()-started,3)}
    report['implementation_sha256']={str(p.relative_to(ROOT)):sha(p) for parent in ('src','scripts')
                                    for p in sorted((ROOT/parent).rglob('*.py'))}
    (ROOT/'reports/offline_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (ROOT/'reports/test_results.txt').write_text(stream.getvalue())
    rows=report['packet_capacity'];stops=report['dynamic_collection']
    lines=['# 预测提醒合并、触发资料优先：v4 离线验证','',f"结果：{'通过' if report['passed'] else '未通过'}；{result.testsRun} 项测试；模型调用 0 次。",'',
           '窗口/输入预算保持 G1 272000/220000，G2 544000/440000。两组规则相同。', '',
           '## 初次需求分批', '', '| 组别 | 2000 条需求的各批条数 | 批数 | 遗漏 | 重复 |', '|---|---|---:|---:|---:|']
    for row in report['initial_partition']:
        lines.append(f"| {row['group']} | {', '.join(map(str,row['batches']))} | {len(row['batches'])} | {row['omitted_operations']} | {row['duplicate_operations']} |")
    lines += ['', '这是资料批次，不是实测模型调用次数。该测试不生成生产任务，全部需求仍标为未安排。', '',
              '## 相同保存状态和既有计划重放', '',
              '从 702 秒恢复，两组都重放此前已保存的同一份 13 项任务计划；没有新模型输出，没有算法补排。', '',
              '| 组别 | 推进区间 | 启动任务数 | 下次停止原因 | 同批容量立即重触发 |', '|---|---|---:|---|---|']
    for row in report['paired_continuation']:
        lines.append(f"| {row['group']} | {row['from']:g} → {row['to']:g} 秒 | {row['dispatches']} | {row['stop_reason']} | 否 |")
    lines += ['', '已确认计划保持不变；下一次真实接续需求仍会触发。未处理需求没有被删除，60 秒等待也未重置。', '',
           '## 单包容量和连续到达回归', '',
           '| 组别 | 输入预算 | 2000 台合成资料：本包工序数 | 本包预算占用 tokens |', '|---|---:|---:|---:|']
    for row in rows:lines.append(f"| {row['group']} | {row['input_budget']:,} | {row['inline_operations']:,} | {row['budgeted_input_tokens']:,} |")
    lines += ['', '| 组别 | 连续到达样例的首次容量触发时刻 | 已观察需求数 |','|---|---:|---:|']
    for row in stops:lines.append(f"| {row['group']} | {row['stop_time']:g} 秒 | {row['observed_demands']} |")
    lines += ['', '## 预测提醒合并与既有任务', '',
        '预测类决策距上次成功提交至少 60 秒，单次纳入未来 60 秒的相关预测；无需求不按整点调用。真实可开工等待 60 秒、计划续期和失效不受预测合并间隔拖延。',
        '物料到达依据只来自公开已就绪状态、正在执行的前序及已确认任务顺序；没有前序计划支撑的远期候选保留但不独自制造紧急提醒。条件工序不被一律排除。']
    for row in report['forecast_collection']:
        if row['fixture']=='nearby_100_and_106_75':
            lines += ['',f"- 合成机组预计 100、106.75 秒空闲：85 秒同批包含两台机组，91.75 秒不再次触发；下一次在 {row['next_stop_at']} 秒因真实等待期限停止。已有任务仍在 12、24 秒启动。"]
        elif row['fixture']=='2000_focus_overflow':
            lines += ['',f"- {row['group']} 同时有 2000 台重点机组：装入 {row['inline_operations']} 条，{row['unoffered_focus_machines']} 台资料未装入且明确列出；预算占用 {row['budgeted_input_tokens']}/{row['input_budget']} tokens。未装入或未说明的需求不伪记为已处理。"]
    lines += ['', '## 768 秒封存公共资料重新装包', '',
        '两组都固定使用上一轮 G2 在 768 秒的同一份触发信息和公开资料，只验证装包；其中旧 G2 包对两台机组各包含 0 条。此处不是与上一轮各组分别比较，也不代表新机制仍会在 768 秒请求模型。', '',
        '| 组别 | 1295 候选：同一旧 G2 包 → 新包 | 1296 候选：同一旧 G2 包 → 新包 | 本地预算占用 | 输入预算 |',
        '|---|---:|---:|---:|---:|']
    for row in report['trigger_packet_regression']:
        lines += [f"| {row['group']} | 0 → {row['new_inline_candidates']['1295']} | 0 → {row['new_inline_candidates']['1296']} | {row['budgeted_input_tokens']} | {row['input_budget']} |"]
    lines += ['', '这 188 条是各机组关联候选，可能重叠，不能相加当作独立订单数。优先装入旧的未安排资料；新资料随后填充剩余空间。超量焦点需求逐项显示完整、部分或未装入状态，仍保留完整公共引用。',
        '', '## 回执与生产选择边界', '',
        '资料范围、本轮模型明确说明、已提交任务分开记录。machine_reviews 可随既有 apply_candidate 一起提交，无单独模型检查轮次。未提供说明记为 unreported；无效说明仅记录错误，不改生产任务。建议复查时刻只是模型说明，实际预测触发仍遵守共用最小间隔及真实等待期限；它不是机组等待指令。重复字段用无损表组织，未说明记录以数量和完整引用提供，避免状态包装挤占工序资料。',
        '独立审计检查计划来自原始明确动作、回执与计划同事务保存、提醒间隔和真实等待期限。固定重放不调用模型；不自动选任务、排序、取消或创建等待。']
    lines += ['', '上述数量是资料容量和触发机制测试，不能当作模型调用减少或排程质量提升的结果。',
        '', '验证覆盖：无固定 60 秒整点；需求自可开工时计时；重排/恢复不重置未解决计时；已排任务持续执行；公开预测提前续排；真实失效立即停止；超预算引用；完整依赖与字段恢复；默认旧审计不接受新等待语义。',
        '', f"原来源文件校验 {after['source_files_checked']} 项，变更 {len(after['changed_source_files'])} 项；未打开原 B 的运行数据库。",
        '', f"历史封存实验文件校验 {after['sealed_pilot_files_checked']} 项，变更 {len(after['changed_sealed_pilot_files'])} 项。v3 源码和报告已另存到 archive_v3_before_forecast_v4_20261017。",
        '', '本轮仅用本地 o200k_base 计数，无新服务端核验。历史 G2 首请求 393402 tokens 的证据仍封存，不代表本轮调用。输入预算包含 10,000 tokens 包装预留。',
        '', '完整结果见 offline_validation.json，测试明细见 test_results.txt。']
    (ROOT/'reports/offline_validation.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:report[k] for k in ('passed','tests_run','model_calls','elapsed_wall_seconds')},ensure_ascii=False),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
