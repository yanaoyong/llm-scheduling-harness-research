"""Read-only post-evaluation diagnosis; never used to choose or tune formal runs."""
from pathlib import Path
import json
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from problem import load_instance
from validator import validate_schedule

runs = []
for directory in sorted((ROOT / 'runs/acceptance_v1').iterdir()):
    if not (directory / 'result.json').exists():
        continue
    result = json.loads((directory / 'result.json').read_text())
    instance_name, arm, repetition = directory.name.split('_')
    instance = load_instance(ROOT / f'vendor/FJSP-SMT2020/PADL-2023/instances/{instance_name}.lp')
    schedule = json.loads((directory / 'schedule.json').read_text())
    validation = validate_schedule(instance, schedule)
    assert validation['feasible'], directory.name
    by_id = {row['id']: row for row in schedule['operations']}
    definitions = {(pm['group'], pm['name']): pm for pm in instance['maintenance']}
    machines = []
    for machine in validation['machines']:
        sequence = [by_id[oid] for oid in machine['sequence']]
        processing = sum(row['end'] - row['start'] for row in sequence)
        pm_duration = sum(definitions[(machine['group'], name)]['duration']
                          for row in sequence[1:] for name in row['maintenance'])
        internal_setup = sum(machine['setup_durations'][1:])
        span = sequence[-1]['end'] - sequence[0]['start']
        internal_gap = span - processing - internal_setup - pm_duration
        assert internal_gap >= 0
        machines.append(dict(group=machine['group'], machine=machine['machine'],
            processing=processing, initial_setup=machine['setup_durations'][0],
            subsequent_setup=internal_setup, noninitial_pm=pm_duration,
            first_start=sequence[0]['start'], last_end=sequence[-1]['end'],
            remaining_internal_gap=internal_gap))
    candidates = []
    if arm == 'C':
        for path in sorted(directory.glob('feedback_*.json')):
            feedback = json.loads(path.read_text())
            if feedback.get('tool') == 'solve_and_validate':
                candidates.append(dict(candidate=feedback['candidate'],
                    makespan=feedback['validation']['objective']['makespan'],
                    status=feedback['solver_status']))
    runs.append(dict(run_id=directory.name, instance=instance_name, arm=arm,
                     repetition=repetition, objective=validation['objective'],
                     machines=machines, solver_candidates=candidates))
assert len(runs) == 27
by_name = {r['run_id']: r for r in runs}
out = ROOT / 'artifacts/acceptance_v1/posthoc_analysis.json'
out.write_text(json.dumps(dict(note='Post-evaluation descriptive analysis, no runtime tuning.', runs=runs),
                          ensure_ascii=False, indent=2) + '\n')
lines = ['# 首轮结果差异与最终核验补充', '',
    '本文件在27条正式记录全部完成后生成，只读取记录做描述性分析。没有修改冻结代码、提示词、参数或验收实例，也没有将这些诊断反馈给正式Agent。重算命令：`.venv/bin/python scripts/analyze_results.py`。', '',
    '## 跨实例均值掩盖了什么', '',
    '| 实例 | A平均makespan | B平均makespan | B配对平均差距 | C平均makespan | C配对平均差距 |',
    '|---|---:|---:|---:|---:|---:|']
for inst in ('instance02', 'instance05', 'instance08'):
    values = {arm: [by_name[f'{inst}_{arm}_r{rep}']['objective']['makespan'] for rep in (1, 2, 3)] for arm in 'ABC'}
    gap = {arm: statistics.mean((v-a)/a*100 for v,a in zip(values[arm], values['A'])) for arm in 'BC'}
    lines.append(f"| {inst} | {statistics.mean(values['A']):.2f} | {statistics.mean(values['B']):.2f} | {gap['B']:+.2f}% | {statistics.mean(values['C']):.2f} | {gap['C']:+.2f}% |")
lines += ['', 'B的跨实例平均值优于A，但在02和05上的平均值更差；05的三次结果202、203、166显示质量波动。正式运行没有可行性失败，当前薄弱点是排程质量和调用延迟。B在得到可行排程后结束，最多4轮的恢复能力本轮没有被正式失败触发，因此不能声称已验证对复杂失败的自动恢复率。', '',
    '## 机器时间分解：实例05的第一次运行', '',
    '固定查看每种方案的r1，避免按最好结果挑图。下表仅展开终端implant组；全部27条的逐机分解在 [posthoc_analysis.json](../artifacts/acceptance_v1/posthoc_analysis.json)。时间单位沿用题目，不冒称实际分钟。', '',
    '“内部剩余间隔”=末工序完成−首工序开始−加工−首工序之后的换型−非初始维护。它不含第一道加工前的时间；可能来自前置依赖等待或排程本身的空隙，不是已识别全部成因的因果指标。初始维护不收费，首换型另外列出，保持原语义。', '',
    '| 方案/implant机台 | 加工 | 首换型 | 后续换型 | 非初始维护 | 首开始 | 末完成 | 内部剩余间隔 |',
    '|---|---:|---:|---:|---:|---:|---:|---:|']
for arm in 'ABC':
    for m in by_name[f'instance05_{arm}_r1']['machines']:
        if m['group'] == 'implant_128':
            lines.append(f"| {arm}/{m['machine']} | {m['processing']} | {m['initial_setup']} | {m['subsequent_setup']} | {m['noninitial_pm']} | {m['first_start']} | {m['last_end']} | {m['remaining_internal_gap']} |")
lines += ['', 'B把litho加工负荷分成63/65，并降低了implant的换型耗时，但implant机台2的内部剩余间隔达86，末完成202。A对应间隔23、末完成160；C对应间隔22、末完成156。这说明仅平衡上游负荷、按setup归组，仍可能留下较差的跨工序衔接；不能从setup违例为0直接推导makespan好。', '',
    '## 维护阈值：实例08的第一次运行', '',
    '| 方案 | 三台litho加工负荷 | 三台litho非初始维护耗时 | 最终makespan |',
    '|---|---|---|---:|']
for arm in 'ABC':
    run = by_name[f'instance08_{arm}_r1']
    ms = [m for m in run['machines'] if m['group'] == 'lithotrack_fe_95']
    lines.append(f"| {arm} | {', '.join(str(m['processing']) for m in ms)} | {', '.join(str(m['noninitial_pm']) for m in ms)} | {run['objective']['makespan']} |")
lines += ['', '该实例litho的wk维护阈值为50。B的50/50/50分配无需追加该维护，A的53/44/53触发两次23单位维护，这是与B较短排程一致的可观察结构。C保留一次追加维护仍取得114，说明避免维护次数本身并不是完整优化目标。此处是事后排程解释，没有做替换单一决策的因果实验。', '',
    '## C的第二次调用实际带来了什么', '',
    '| 运行 | 首次求解候选makespan | 第二次候选makespan | 改善量（首次−第二次） |',
    '|---|---:|---:|---:|']
for run in runs:
    if len(run['solver_candidates']) == 2:
        first, second = [c['makespan'] for c in run['solver_candidates']]
        lines.append(f"| {run['run_id']} | {first} | {second} | {first-second} |")
lines += ['', 'C在02的三次运行中，首次求解已证明makespan最优，模型直接确认；05/08中模型读取限时可行反馈后改参数再次求解，并明确选择候选2。这验证了反馈驱动的编排参与。A预先固定frumpy、种子11/22/33，C可选其他预设，因此质量差距同时包含预设/种子差异，尚不能归因于语言模型的自适应价值。', '',
    '下一轮最有价值的对照是：在未见实例上将C与“固定jumpy、固定两阶段预设组合、同累计40秒预算”比较，再与允许反馈的C消融。对B则单独比较“首次可行即结束”和“固定额外质量审查轮次”，保留各自完整调用成本。上述是后续建议，本轮未执行、未调参。', '',
    '## 交付核验与结论边界', '',
    '- 22项正确性测试通过；另对27条最终排程固定机台、维护和时间后交给原ASP验证，全部可满足且setup罚值一致。固定排程检查只证明这些排程可行，不证明它们的makespan全局最优。',
    '- [最终审计](../artifacts/formal_source_audit/final27/summary.json)重算全部表格数值，核对B动作回放与C参数/候选选择，33条模型请求的原生工具执行数为0。该审计发生在正式运行结束后，不参与B排程，其开销单独记录。',
    '- README批量恢复命令实跑得到27条SKIP，无覆盖、无额外模型请求；原冻结文件校验通过。',
    '- 输入269400、输出18721、缓存输入12800 token为正式排程33次请求可见用量；缓存是输入的子集。货币费用未知；主协作/实现和审查会话不在该账本内。',
    '- 单次端到端计时不含Python启动、初始解析与最终result文件写盘，精确边界见 [源码审计](source-audit.md)。实验环境未隔离桌面背景负载。',
    '- 只验证这个静态、小规模PADL版本。没有组批、动态插单、现场对照或真人排程实验，不宣称泛化到完整Fab或战胜人工。', '',
    '核心交付是三种真实可运行的决策流程、同题可复算的27条成功排程和可以继续扩展的审计基础。Agent质量优于这里的固定基线是首轮观察，不是普遍优势或因果证明。', '']
(ROOT / 'docs/RESULT_ANALYSIS_zh.md').write_text('\n'.join(lines), encoding='utf-8')
print(json.dumps({'runs': len(runs), 'output': str(out), 'report': 'docs/RESULT_ANALYSIS_zh.md'}))
