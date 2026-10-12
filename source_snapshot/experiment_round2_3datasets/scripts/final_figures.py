#!/usr/bin/env python3
"""Create three final static figures from saved, certified ORIGINAL evidence only.

Run AFTER offline replay, per-phase reports, and analysis_tables.py have finished:
    .venv/bin/python scripts/final_figures.py
    .venv/bin/python scripts/final_figures.py --check-only

This program never imports a runner, replay, simulator, optimizer, or model client.
No provisional metric is used. Recovery/supplementary phases are deliberately out
of scope. A legitimate audited failure remains in n/3 and is never replaced.
Missing/uncertified evidence blocks all final PNG generation. Plot labels use
portable Latin fonts; the output manifest supplies Chinese report captions.
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT/'artifacts/final'
PHASES = ('acceptance_static_v1', 'auxiliary_static_v1')
ARMS = ('A', 'B', 'C', 'F')
COLORS = {'A':'#0072B2', 'B':'#D55E00', 'C':'#009E73', 'F':'#777777'}
MARKERS = {'A':'o', 'B':'s', 'C':'^', 'F':'D'}
NAMES = {'A':'A', 'B':'B', 'C':'C', 'F':'F (auxiliary)'}
VARIANTS = ('edata', 'rdata', 'vdata')
FILES = ('brandimarte_quality.png', 'hurink_variant_gaps.png', 'static_quality_cost.png')


class EvidenceNotReady(ValueError):
    pass


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cast(value):
    if value in ('', None):
        return None
    if value in ('True', 'true'):
        return True
    if value in ('False', 'false'):
        return False
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


def csv_rows(path):
    with path.open(newline='', encoding='utf-8') as handle:
        return [{k:cast(v) for k,v in row.items()} for row in csv.DictReader(handle)]


def equal(a, b):
    if number(a) and number(b):
        return abs(a-b) <= 1e-6*max(1., abs(a), abs(b))
    return a == b


def index_unique(rows, key, description):
    result = {}
    for row in rows:
        identity = row[key]
        if identity in result:
            raise EvidenceNotReady(f'Duplicate {description}: {identity}')
        result[identity] = row
    return result


def load_certified(analysis_path):
    """Read saved evidence only; fail closed before importing matplotlib."""
    data = read(analysis_path)
    if data.get('schema_version') != 'analysis-tables-1':
        raise EvidenceNotReady('Expected analysis-tables-1 schema')
    all_rows = data.get('run_rows')
    if not isinstance(all_rows, list):
        raise EvidenceNotReady('analysis.json has no run_rows list')
    source_hashes = {str(analysis_path.relative_to(ROOT)):sha(analysis_path)}
    selected, failures = [], []
    for phase in PHASES:
        freezes = []
        for path in sorted((ROOT/'configs/freezes').glob('*.json')):
            frozen = read(path)
            if frozen.get('phase') == phase:
                freezes.append((path, frozen))
        if len(freezes) != 1:
            raise EvidenceNotReady(f'{phase}: no unique original freeze')
        freeze_path, frozen = freezes[0]
        source_hashes[str(freeze_path.relative_to(ROOT))] = sha(freeze_path)
        expected = {f'{instance}_{arm}_r{repeat}':(instance,arm,repeat)
                    for instance,arm,repeat in frozen['matrix']}
        if len(expected) != len(frozen['matrix']):
            raise EvidenceNotReady(f'{phase}: duplicate frozen matrix cell')
        allowed_arms = {'F'} if phase.startswith('auxiliary_') else {'A','B','C'}
        cells = set(expected.values())
        instances = {x[0] for x in cells}
        if cells != {(instance,arm,repeat) for instance in instances
                     for arm in allowed_arms for repeat in (1,2,3)}:
            raise EvidenceNotReady(f'{phase}: incomplete original three-repeat matrix')
        rows = index_unique([r for r in all_rows if r.get('phase')==phase], 'run_id', 'analysis row')
        if set(rows) != set(expected):
            raise EvidenceNotReady(f'{phase}: analysis must contain exactly original frozen cells')
        unfinished = [key for key,row in rows.items() if row.get('completed_record') is not True]
        if unfinished:
            raise EvidenceNotReady(f'{phase}: {len(unfinished)} original runs are unfinished; first={unfinished[0]}')
        audit_path = ROOT/'artifacts'/phase/'report_evidence_audit.json'
        table_path = ROOT/'artifacts'/phase/'results.csv'
        if not audit_path.is_file() or not table_path.is_file():
            raise EvidenceNotReady(f'{phase}: final saved report audit/CSV is missing')
        audit = read(audit_path)
        if audit.get('phase') != phase or audit.get('coverage_complete') is not True:
            raise EvidenceNotReady(f'{phase}: final audit coverage is incomplete')
        if any(audit.get(key) for key in ('phase_errors','missing','unexpected','duplicates','incomplete')):
            raise EvidenceNotReady(f'{phase}: final audit contains matrix/evidence errors')
        proofs = index_unique(audit.get('runs',[])+audit.get('auxiliary_runs',[]), 'run_id', 'audit row')
        table = index_unique(csv_rows(table_path), 'run_id', 'phase CSV row')
        if set(table) != set(expected) or not set(expected).issubset(proofs):
            raise EvidenceNotReady(f'{phase}: final audit/CSV does not cover the original matrix')
        for path in (audit_path, table_path):
            source_hashes[str(path.relative_to(ROOT))] = sha(path)
        for run_id, identity in sorted(expected.items()):
            row, proof, saved = rows[run_id], proofs[run_id], table[run_id]
            if row.get('planned') is not True or row.get('family') not in ('brandimarte','hurink'):
                raise EvidenceNotReady(f'{run_id}: unplanned or nonstatic row')
            if (row.get('instance'),row.get('arm'),row.get('repeat')) != identity:
                raise EvidenceNotReady(f'{run_id}: analysis identity mismatch')
            if proof.get('audit_pass') is not True or proof.get('provenance_complete') is not True:
                raise EvidenceNotReady(f'{run_id}: original evidence has not passed audit/provenance')
            if (proof.get('instance_id'),proof.get('arm'),proof.get('repeat')) != identity:
                raise EvidenceNotReady(f'{run_id}: saved audit identity mismatch')
            for key in ('instance','arm','repeat','status','code_commit','config_sha256','data_sha256'):
                if not equal(saved.get(key),row.get(key)):
                    raise EvidenceNotReady(f'{run_id}: CSV/analysis mismatch in {key}')
            if proof.get('status') != row.get('status'):
                raise EvidenceNotReady(f'{run_id}: audit/analysis status mismatch')
            if row.get('status') != 'success':
                if row.get('certified_success') is True or saved.get('makespan') is not None:
                    raise EvidenceNotReady(f'{run_id}: failed attempt has certified quality')
                failures.append({'phase':phase,'run_id':run_id,'status':row.get('status'),
                                 'failure_type':row.get('failure_type')})
                selected.append(dict(row, figure_quality=None, figure_gap=None, figure_cost=None))
                continue
            if row.get('certified_success') is not True:
                raise EvidenceNotReady(f'{run_id}: success is not certified; regenerate analysis after final replay')
            value = row.get('certified_makespan')
            cost = row.get('end_to_end_seconds')
            ref = saved.get('reported_optimum')
            if not number(value) or not number(cost) or cost < 0 or not number(ref) or ref <= 0:
                raise EvidenceNotReady(f'{run_id}: certified quality/cost/reported optimum missing')
            if proof.get('valid') is not True or saved.get('feasible') is not True:
                raise EvidenceNotReady(f'{run_id}: saved success lacks validated feasibility')
            for other in (proof.get('makespan'),saved.get('makespan')):
                if not equal(value,other):
                    raise EvidenceNotReady(f'{run_id}: certified makespan disagrees with independent evidence')
            if not equal(cost,saved.get('end_to_end_seconds')) or not equal(ref,row.get('reported_optimum')):
                raise EvidenceNotReady(f'{run_id}: cost/reference differs from phase CSV')
            selected.append(dict(row, figure_quality=value, figure_gap=100*(value-ref)/ref,
                                 figure_cost=cost, figure_reference=ref,
                                 figure_reference_status=saved.get('reference_status')))
    core_instances = {r['instance'] for r in selected if r['arm']!='F'}
    auxiliary_instances = {r['instance'] for r in selected if r['arm']=='F'}
    if core_instances != auxiliary_instances:
        raise EvidenceNotReady('Original core and F auxiliary instance sets differ')
    return selected, {'analysis_generated_at':data.get('generated_at'),
                      'source_sha256':source_hashes, 'original_phases':list(PHASES),
                      'planned_records':len(selected),
                      'certified_successes':sum(r.get('certified_success') is True for r in selected),
                      'audited_original_failures':failures}


def summarize(rows, metric):
    valid = [r[metric] for r in rows if r.get('certified_success') is True and number(r.get(metric))]
    return {'n':len(valid), 'planned':len(rows), 'mean':statistics.mean(valid) if valid else None,
            'min':min(valid) if valid else None, 'max':max(valid) if valid else None}


def point_range(ax, x, summary, arm):
    if summary['n'] == 0:
        ax.text(x, .04, 'no success', transform=ax.get_xaxis_transform(), ha='center', fontsize=7, rotation=90)
        return
    mean = summary['mean']
    ax.errorbar([x], [mean], yerr=[[mean-summary['min']],[summary['max']-mean]],
                fmt=MARKERS[arm], color=COLORS[arm], markersize=6, capsize=4,
                elinewidth=1.3, markeredgewidth=1.1, linestyle='none')


def decorate(ax):
    ax.grid(axis='y', alpha=.23, linewidth=.6)
    ax.spines[['top','right']].set_visible(False)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=9)


def save(fig, path, plt):
    fig.savefig(path, dpi=200, bbox_inches='tight', facecolor='white')
    plt.close(fig)


def brandimarte(rows, output, plt):
    instances = sorted({r['instance'] for r in rows if r['family']=='brandimarte'})
    if not instances:
        raise EvidenceNotReady('No Brandimarte instances')
    fig, axes = plt.subplots(len(instances),2,figsize=(9.5,2.65*len(instances)+.9),
                             sharey='row', squeeze=False, width_ratios=[3.2,1.3], layout='constrained')
    plotted = []
    for index, instance in enumerate(instances):
        members = [r for r in rows if r['instance']==instance]
        for column, arms in enumerate((('A','B','C'),('F',))):
            ax = axes[index,column]
            ticks = []
            for x,arm in enumerate(arms):
                summary = summarize([r for r in members if r['arm']==arm], 'figure_quality')
                point_range(ax,x,summary,arm)
                ticks.append(f'{arm}\nn={summary["n"]}/{summary["planned"]}')
                plotted.append({'instance':instance,'arm':arm,'makespan':summary})
            ax.set_xticks(range(len(arms)),ticks)
            ax.set_xlim(-.55,len(arms)-.45)
            decorate(ax)
            if column == 0:
                ax.set_ylabel(f'{instance}\nMakespan (benchmark units)',fontsize=10)
            if index == 0:
                ax.set_title('Core comparison: A / B / C' if column==0 else 'F: auxiliary only',fontsize=11)
    fig.suptitle('Brandimarte | original formal runs\nCertified-success means; bars = min–max across repeats (not CI)',fontsize=12)
    save(fig,output/FILES[0],plt)
    return plotted


def hurink(rows, output, plt):
    members = [r for r in rows if r['family']=='hurink']
    bases = sorted({r['base_instance'] for r in members})
    if not bases:
        raise EvidenceNotReady('No Hurink base instances')
    expected = {(base,variant) for base in bases for variant in VARIANTS}
    if {(r['base_instance'],r['variant']) for r in members} != expected:
        raise EvidenceNotReady('Hurink base × variant coverage differs from edata/rdata/vdata')
    fig,axes = plt.subplots(len(bases),len(VARIANTS),figsize=(12,2.75*len(bases)+.7),
                            sharey='row',squeeze=False,layout='constrained')
    plotted = []
    for i,base in enumerate(bases):
        for j,variant in enumerate(VARIANTS):
            ax = axes[i,j]
            cell = [r for r in members if r['base_instance']==base and r['variant']==variant]
            ticks = []
            for x,arm in enumerate(ARMS):
                summary = summarize([r for r in cell if r['arm']==arm], 'figure_gap')
                point_range(ax,x,summary,arm)
                ticks.append(f'{arm if arm!="F" else "F aux"}\nn={summary["n"]}/{summary["planned"]}')
                plotted.append({'base_instance':base,'variant':variant,'arm':arm,'gap_percent':summary})
            ax.set_xticks(range(4),ticks)
            ax.set_xlim(-.6,3.6)
            ax.axhline(0,color='#555555',linewidth=.7,alpha=.65)
            ax.set_title(f'{base} / {variant}',fontsize=11)
            if j == 0:
                ax.set_ylabel('Gap to own reported optimum (%)',fontsize=9)
            decorate(ax)
    fig.suptitle('Hurink | each variant uses its own reported optimum\nCertified-success means; bars = min–max across repeats (not CI); F is auxiliary',fontsize=12)
    save(fig,output/FILES[1],plt)
    return plotted


def quality_cost(rows, output, plt):
    fig,axes = plt.subplots(1,2,figsize=(12,5.2),layout='constrained')
    plotted = []
    offsets = {'A':(-12,16),'B':(12,16),'C':(12,-22),'F':(-12,-36)}
    for ax,family in zip(axes,('brandimarte','hurink')):
        members = [r for r in rows if r['family']==family]
        all_instances = {r['instance'] for r in members}
        for arm in ARMS:
            arm_rows = [r for r in members if r['arm']==arm]
            successes = [r for r in arm_rows if r.get('certified_success') is True]
            by_instance = defaultdict(list)
            for row in successes:
                by_instance[row['instance']].append(row)
            summary = {'family':family,'arm':arm,'certified_repeats':len(successes),
                       'planned_repeats':len(arm_rows),'instances_with_success':len(by_instance),
                       'planned_instances':len(all_instances),'equal_instance_mean_gap_percent':None,
                       'equal_instance_mean_end_to_end_seconds':None}
            if by_instance:
                x = statistics.mean(statistics.mean(r['figure_cost'] for r in group) for group in by_instance.values())
                y = statistics.mean(statistics.mean(r['figure_gap'] for r in group) for group in by_instance.values())
                summary.update(equal_instance_mean_gap_percent=y,equal_instance_mean_end_to_end_seconds=x)
                ax.scatter([x],[y],color=COLORS[arm],marker=MARKERS[arm],s=65,zorder=3)
                label = f'{arm if arm!="F" else "F aux"}: n={len(successes)}/{len(arm_rows)}'
                if len(by_instance) != len(all_instances):
                    label += f'\ninstances={len(by_instance)}/{len(all_instances)}'
                dx,dy = offsets[arm]
                ax.annotate(label,(x,y),xytext=(dx,dy),textcoords='offset points',fontsize=8,
                            ha='right' if dx<0 else 'left',va='bottom' if dy>0 else 'top',
                            arrowprops={'arrowstyle':'-','linewidth':.5,'color':COLORS[arm]})
            else:
                ax.text(.02,.97-.065*ARMS.index(arm),f'{NAMES[arm]}: n=0/{len(arm_rows)} (not plotted)',
                        transform=ax.transAxes,va='top',fontsize=8,color=COLORS[arm])
            plotted.append(summary)
        ax.set_title('Brandimarte' if family=='brandimarte' else 'Hurink',fontsize=12)
        ax.set_xlabel('End-to-end wall time (seconds)',fontsize=10)
        ax.set_ylabel('Gap to own reported optimum (%)',fontsize=10)
        ax.margins(x=.35,y=.35)
        decorate(ax)
    fig.suptitle('Static quality and cost | original certified successes only\nInstance means receive equal weight within each dataset; separate panels, no pooled ranking',fontsize=12)
    save(fig,output/FILES[2],plt)
    return plotted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis',type=Path,default=OUTPUT/'analysis.json')
    parser.add_argument('--check-only',action='store_true',help='Read readiness only; do not import plotting or write artifacts')
    args = parser.parse_args()
    analysis_path = args.analysis.resolve()
    if ROOT not in analysis_path.parents:
        raise ValueError('Analysis input must remain within this experiment')
    status = {'schema_version':'final-figures-1','generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),
              'original_phases':list(PHASES),'script_sha256':sha(Path(__file__)),
              'model_calls':0,'solver_calls':0,'simulation_calls':0,'replay_calls':0}
    try:
        rows,evidence = load_certified(analysis_path)
    except (EvidenceNotReady,OSError,ValueError,KeyError,TypeError) as exc:
        status.update(ready=False,state='blocked',reason=str(exc),png_generated=False,
                      next_step='Complete original phase runs, saved offline audits and phase reports; then regenerate analysis.json. No provisional or recovery replacement is permitted.')
        if not args.check_only:
            OUTPUT.mkdir(parents=True,exist_ok=True)
            (OUTPUT/'final_figures_status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(status,ensure_ascii=False))
        return 2
    status.update(evidence,ready=True,state='ready',png_generated=False)
    if args.check_only:
        print(json.dumps(status,ensure_ascii=False))
        return 0
    OUTPUT.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault('MPLCONFIGDIR',str(OUTPUT/'.matplotlib'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.titlesize':11,
                         'savefig.pad_inches':.15,'axes.unicode_minus':True})
    status['plotted_statistics'] = {'brandimarte':brandimarte(rows,OUTPUT,plt),
                                  'hurink':hurink(rows,OUTPUT,plt),
                                  'quality_cost':quality_cost(rows,OUTPUT,plt)}
    status.update(state='generated',png_generated=True,files=list(FILES),
        captions_zh={FILES[0]:'Brandimarte 各实例的原首次正式结果。A/B/C 为主比较，F 在单独辅助面板。点为认证成功重复的均值，误差条为最小值至最大值，非置信区间；n/3 显示成功样本数。各行使用各自 makespan 刻度。',
                     FILES[1]:'Hurink 按 base×variant 展示相对该变体自身文献报告最优值的 gap。各 arm 使用认证成功重复的条件均值及最小—最大范围（非置信区间），失败不填零，n/3 保留失败分母。报告最优值不冒充本实验独立证明最优；F 为辅助策略。',
                     FILES[2]:'静态质量—端到端成本分数据集展示，不作跨数据集总排名。两轴都先在每实例的认证成功原首次重复中求均值，再按有成功样本的实例等权平均；标注成功重复数/原计划数。失败及恢复补充均不进入该图，失败的完整成本仍须见总表。图中无置信区间或 Pareto 最优声明。'},
        caveats=['Only original frozen phase records; no recovery substitution.',
                 'Successful rows require certified_success=true; failed/unaudited values are never zero-filled.',
                 'Figure 1/2 error bars show repeated-run min–max, not confidence intervals.',
                 'Figure 3 both axes condition on the same successful repeats, then equally weight instance means.',
                 'Reported-optimum gaps are not independently verified optimality gaps.'])
    (OUTPUT/'final_figures_status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:status[k] for k in ('ready','state','files','planned_records','certified_successes')},ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
