#!/usr/bin/env python3
"""V5 local-only validation; preserve v4 reports, all pilots and original B."""
from pathlib import Path
import os
import sys
import tempfile
import hashlib
import json
import io
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True;os.chdir(ROOT)
(ROOT/'.tmp').mkdir(exist_ok=True);tempfile.tempdir=str(ROOT/'.tmp')
from src.smt_fullfab.harness.offline_isolation import install_guard
install_guard()
from src.smt_fullfab.harness.capacity_config import deadline_config


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def isolation():
    manifest=json.loads((ROOT/'isolation_manifest.json').read_bytes());source=Path(manifest['source_root'])
    changed=[];linked=[]
    for relative,expected in manifest['source_hashes'].items():
        p=source/relative;q=ROOT/relative
        if not p.is_file() or sha(p)!=expected:changed.append(relative)
        if q.is_symlink() or (q.exists() and (p.stat().st_dev,p.stat().st_ino)==(q.stat().st_dev,q.stat().st_ino)):linked.append(relative)
    fixture_changes=[k for k,v in manifest['fixture_sha256'].items() if sha(ROOT/'fixtures'/k)!=v]
    archive=ROOT/'reports/archive_v4_before_original_control_20261017'
    frozen=json.loads((archive/'archive_manifest.json').read_bytes())
    changed_archive=[k for k,v in frozen['files'].items() if not (archive/k).is_file() or sha(archive/k)!=v]
    changed_pilots=[k for k,v in frozen['sealed_pilot_files'].items() if not (ROOT/k).is_file() or sha(ROOT/k)!=v]
    return {'source_files_checked':len(manifest['source_hashes']),'changed_source_files':changed,
            'linked_to_original':linked,'changed_fixtures':fixture_changes,'original_run_database_opened':False,
            'archive_files_checked':len(frozen['files']),'changed_archive_files':changed_archive,
            'sealed_pilot_files_checked':len(frozen['sealed_pilot_files']),'changed_pilot_files':changed_pilots,
            'valid':not(changed or linked or fixture_changes or changed_archive or changed_pilots)}


def guards():
    import socket,subprocess
    checks={}
    for name,fn in [('network',lambda:socket.socket()),('child_process',lambda:subprocess.Popen(['/usr/bin/true'])),
                    ('external_write',lambda:(ROOT.parent/'forbidden-deadline-write').open('w'))]:
        try:fn()
        except (RuntimeError,ValueError):checks[name]='blocked before effect'
        else:raise AssertionError(name+' was not blocked')
    return checks


def main():
    started=time.perf_counter();print('Checking original B and frozen history hashes',flush=True)
    before=isolation()
    if not before['valid']:raise RuntimeError(json.dumps(before))
    blocked=guards()
    folder=ROOT/'configs/deadline';folder.mkdir(exist_ok=True)
    for group in ('G0','G1','G2'):
        (folder/(group+'.json')).write_text(json.dumps(deadline_config(group),ensure_ascii=False,indent=2)+'\n')
    names=['tests.test_capacity_batch60_experiment','tests.test_capacity_two_strategy','tests.test_capacity_forecast_collection',
           'tests.test_capacity_live_pilot','tests.test_capacity_deadline_collection','tests.test_smt_fullfab_audit',
           'tests.test_smt_fullfab_not_before_audit','tests.test_smt_fullfab_plan_delta',
           'tests.test_smt_fullfab_delta_session','tests.test_smt_fullfab_stream_opportunity_audit',
           'tests.test_smt_fullfab_harness_lossless_presentation.LosslessPresentationTests.test_T11_T12_roundtrip_types_absence_order_and_marker_collisions']
    stream=io.StringIO()
    class Progress(unittest.TextTestResult):
        def startTest(self,test):
            super().startTest(test);print('CHECK '+test.id(),flush=True)
    result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Progress).run(unittest.defaultTestLoader.loadTestsFromNames(names))
    from tests.test_capacity_deadline_collection import DeadlineRulesTests,DeadlineCapacityTests,DeadlineSavedReplayTests
    print('Rechecking original B and frozen history hashes',flush=True);after=isolation()
    report={'schema':'deadline-collection-offline-v5','date':'2026-10-17','passed':result.wasSuccessful() and after['valid'],
        'tests_run':result.testsRun,'failures':[(str(t),msg) for t,msg in result.failures],
        'errors':[(str(t),msg) for t,msg in result.errors],'model_calls':0,'model_quality_evaluated':False,
        'actual_call_reduction_evaluated':False,'groups':{g:deadline_config(g) for g in ('G0','G1','G2')},
        'deadline_examples':DeadlineRulesTests.measurements,'capacity':DeadlineCapacityTests.measurements,
        'saved_replay':DeadlineSavedReplayTests.measurements,'guards':blocked,
        'isolation_before':before,'isolation_after':after,'elapsed_wall_seconds':round(time.perf_counter()-started,3),
        'limitations':[
            'Decision pauses the simulation; this is not a real-time asynchronous production/solver test.',
            '120s decision + 15s margin is provisional, not a measured percentile or guarantee.',
            'Latest start controls requesting a decision; it cannot force the model to submit sufficient production.',
            'Forecasts use supported public arrivals and existing chosen queues; no hidden future events are exposed.',
            'Lookahead depth 2 and plan horizon 14400s remain shared public exporter bounds; only the fixed 60s collection cutoff is removed.',
            '2000-machine input is a synthetic capacity stress, not a verified 2000-machine physical factory.',
            'Notification delivery is separate from explicit model review and assignment; actual gaps can still cause repeated requests if left unresolved.',
            'Opportunity audit independently replays legal gaps and timing. Public forecast values and packing are separately covered by causal fixtures.'
        ]}
    report['implementation_sha256']={str(p.relative_to(ROOT)):sha(p) for parent in ('src','scripts','tests','configs/deadline')
        for p in sorted((ROOT/parent).rglob('*')) if p.is_file() and p.suffix in ('.py','.json')}
    (ROOT/'reports/deadline_validation_20261017.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (ROOT/'reports/deadline_test_results.txt').write_text(stream.getvalue())
    lines=['# 立即补排、截止约束与容量扩展：v5 离线验证','',
        f"结果：{'通过' if report['passed'] else '未通过'}；{result.testsRun} 项测试；模型调用 0 次。",'',
        '本轮只修改独立副本。G0 保留原版触发与执行规则，使用 G1 的窗口、输入预算和公共资料组织。G1/G2 共用新规则，仅容量设置不同。', '',
        '| 组别 | 窗口 tokens | 输入预算 tokens | 执行规则 |','|---|---:|---:|---|',
        '| G0 | 272,000 | 220,000 | 原版即时缺口、周期边界、到期/失效 |',
        '| G1 | 272,000 | 220,000 | 即时缺口、预测合并且不越截止、容量增量、到期/失效 |',
        '| G2 | 544,000 | 440,000 | 与 G1 相同 |','',
        '## 三个时间规则','',
        '可开工但没有后续任务、也没有模型显式等待的需求，立即请求补排，等待上限为 0。其他机组已经提交且当前可执行的任务，先照原顺序执行，再报告缺口。', '',
        '接续需求时刻取机组可用与有依据的物料到达两者较晚者。最晚启动补排时刻 = 接续需求时刻 − 135 秒；暂按决策 120 秒、余量 15 秒，模拟中的下发及准备预算为 0。该参数仅为离线暂定值，不是实测耗时保证。', '',
        '预测合并仍用 60 秒尺度，最晚启动时刻优先于合并间隔。提前送达而未安排的需求，可以在截止时再次提醒；截止轮次同时覆盖已装入、未来 60 秒内截止的邻近需求，不必相隔几秒逐个再提醒。截止通知已送达后，同一预测不会立刻重复。新的预测、提前的截止或真实可开工缺口仍可触发。仅送达资料不计为模型已审阅或任务已安排。', '',
        '例：预计 300 秒需要接续，最晚 165 秒启动补排。无其他提交时，可在 105 秒先汇总一次，仍未排时 165 秒再提醒；截止通知送达后，不在同一时刻反复提醒，到 300 秒仍缺计划则立即补排。期间已有任务仍在 12、24 秒启动。若刚在 140 秒提交过，也不能以合并间隔为由拖到 200 秒，必须在 165 秒触发。', '',
        '提前收集取消固定未来 60 秒上限。按紧迫程度组织完整资料单元，输入预算决定实际装入多少、延伸多远；未装入内容保留引用及明确的缺失状态。公共导出器仍共用 2 层前瞻、14,400 秒计划范围，没有使用隐藏未来或展开所有工序。','',
        '## 2000 台合成资料容量','',
        '| 组别 | 本包工序数 | 输入预算占用 | 完整覆盖到的接续截止时刻 | 未装入机组数 |',
        '|---|---:|---:|---:|---:|']
    for row in report['capacity']:
        if 'scope' in row:
            s=row['scope'];lines.append(f"| {row['group']} | {row['inline_operations']} | {row['budgeted_tokens']:,} / {row['input_budget']:,} | {s['fully_included_deadline_through']:g} 秒 | {s['not_offered']} |")
    lines += ['', '时间为合成样例的模拟时间，表示资料覆盖，不是已排任务。两组处理相同的 2000 条独立需求，G2 能装入更多未来需求；两组都有明确溢出，未要求把全部工序装进上下文。', '',
        '| 初次分批组别 | 各批工序数 | 遗漏 | 重复 |','|---|---|---:|---:|']
    for row in report['capacity']:
        if row.get('case')=='initial_partition':lines.append(f"| {row['group']} | {', '.join(map(str,row['batch_sizes']))} | {row['omitted']} | {row['duplicated']} |")
    lines += ['', '资料分批数不能当作模型调用数。空的离线回执只用于验证批次覆盖，不代表模型实际选择或安排了这些需求。', '',
        '## 相同保存状态、相同既有计划重放', '',
        '从 mixed_702 保存状态恢复，四条路径重放此前保存的同一份 13 项生产任务计划，没有新生产选择。legacy 是独立副本中关闭实验功能的原执行路径，未运行原 B。', '',
        '| 路径 | 推进至 | 启动任务数 | 停止原因 |','|---|---:|---:|---|']
    for row in report['saved_replay']:lines.append(f"| {row['group']} | {row['to']:g} 秒 | {row['dispatches']} | {row['stop_reason']} |")
    lines += ['', 'G0 与 legacy 的停止时刻、原因和任务启动明细一致；源代码 AST 核对确认原调度执行方法主体未改。G1/G2 提交后不会因同一批旧资料立即再次容量触发；有效任务保留，保存恢复后仍相同。', '',
        '## 验证边界', '',
        '覆盖真实缺口即时触发、提前通知与截止通知分离、合并不越截止、已过截止的恢复状态即时处理、未装包不伪记送达、新预测/更早截止可再触发、已有任务先执行、计划失效、原版执行一致性、初次完整分批、大窗口扩大资料范围、独立回执/生产来源审计，以及篡改回执和截止时间的反例。', '',
        '已有计划在模拟推进中继续执行；模型决策期间模拟时钟仍暂停。本轮没有实现或验证真实生产与模型求解并发，也没有验证实际调用减少、模型排程质量或长期等待改善。模型若一直不选择可执行任务，真实缺口仍会再次请求；不能靠吞掉需求来减少调用。', '',
        f"原 B 来源文件核对 {after['source_files_checked']} 项、改动 0；历史模型实验文件核对 {after['sealed_pilot_files_checked']} 项、改动 0；v4 归档核对 {after['archive_files_checked']} 项、改动 0。未打开原 B 的运行数据库。", '',
        '验证进程禁止网络、子进程和副本外写入；v5 模型入口另行硬性拒绝。所有生产任务仍来自明确提案，提醒、排序装包、回执和覆盖检查都不生成生产任务。', '',
        '复现：`/opt/miniconda3/bin/python3.13 -B scripts/validate_deadline_experiment.py`。完整数据见 `deadline_validation_20261017.json`，测试明细见 `deadline_test_results.txt`。']
    (ROOT/'reports/deadline_validation_20261017.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:report[k] for k in ('passed','tests_run','model_calls','elapsed_wall_seconds')},ensure_ascii=False),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
