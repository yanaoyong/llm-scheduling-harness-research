"""Aggregate compatible trajectories; population SD is the reported spread."""
import argparse
import json
from pathlib import Path
import statistics
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from harness_v6.snapshot import canonical
from harness_v6.checkpoint import atomic_write

METRICS = ['uncached_equivalent_input_tokens_per_sim_hour', 'model_request_lower_bound_per_sim_hour',
           'weighted_tardiness','throughput','avoidable_idle_seconds','explicit_wait_idle_seconds',
           'failures','unknown_usage']


def summarize(directories, output):
    rows = [(json.loads((Path(d)/'run_manifest.json').read_text()),
             json.loads((Path(d)/'summary.json').read_text())) for d in directories]
    if not rows: raise ValueError('no runs')
    manifests = [m for m,s in rows]
    for key in ('registration_hash', 'dry_run', 'start', 'registered_end', 'fixture_hash', 'codex_version', 'model', 'snapshot_format'):
        if len({m[key] for m in manifests}) != 1: raise ValueError('cannot mix '+key)
    if len({(m['group'],m['trajectory']) for m in manifests}) != len(rows):
        raise ValueError('duplicate trajectory')
    if len({s['end'] for m,s in rows}) != 1: raise ValueError('unequal evaluation endpoints')
    reg = manifests[0]['registration']; groups = {}
    for manifest,summary in rows:
        summary['evaluation'] = summary.get('evaluation_totals', summary['totals'])
    for group in sorted({m['group'] for m in manifests}):
        selected = [s for m,s in rows if m['group']==group]
        stats = {}
        for metric in METRICS:
            values = [s['evaluation'].get(metric) for s in selected]
            stats[metric] = None if any(v is None for v in values) else dict(mean=statistics.mean(values), spread=statistics.pstdev(values))
        quality = {}
        for name,key in [('weighted_tardiness','weighted_tardiness'),('throughput','throughput'),('avoidable_idle_integral','avoidable_idle_seconds')]:
            rule = reg['quality'][name]
            quality[name] = None if rule['floor'] is None else all(
                s['evaluation'][key] >= rule['floor']-rule['tolerance'] if name=='throughput' else
                s['evaluation'][key] <= rule['floor']+rule['tolerance'] for s in selected)
        groups[group] = dict(trajectories=len(selected), metrics=stats, quality=quality,
            stop_reasons=[s['stop_reason'] for s in selected], steady_state=[s['steady_state'] for s in selected])
    comparison = {}
    if {'E1','P2'} <= groups.keys():
        for metric in METRICS[:2]:
            a,b=groups['E1']['metrics'][metric],groups['P2']['metrics'][metric]
            comparison[metric] = None if a is None or b is None else b['mean'] < a['mean']
        comparison['quality_vs_E1'] = {}
        for name,key in [('weighted_tardiness','weighted_tardiness'),('throughput','throughput'),('avoidable_idle_integral','avoidable_idle_seconds')]:
            tolerance=reg['quality'][name]['tolerance']
            a,b=groups['E1']['metrics'][key]['mean'],groups['P2']['metrics'][key]['mean']
            comparison['quality_vs_E1'][name] = None if tolerance is None else (b >= a-tolerance if name=='throughput' else b <= a+tolerance)
        comparison['quality_floors_held'] = all(v is True for v in groups['P2']['quality'].values())
    complete = all(s['stop_reason']=='registered_end' and not s['totals']['unknown_usage'] for m,s in rows)
    complete = complete and all(v['trajectories'] == reg['trajectories_per_group'] for v in groups.values())
    result = dict(registration_hash=manifests[0]['registration_hash'], dry_run=manifests[0]['dry_run'],
        is_result=not manifests[0]['dry_run'], complete=complete, groups=groups, comparison=comparison,
        spread='population standard deviation')
    lines = ['# 轨迹汇总', '', '非模型、仅机制测试' if result['dry_run'] else '模型实验', '',
             '均值 ± 总体标准差；失败、未知用量与提前停止保留，不作成功结果。', '',
             '| 指标 | E1 | P2 |', '|---|---:|---:|']
    for metric in METRICS:
        cells=[]
        for group in ('E1','P2'):
            value=groups.get(group,{}).get('metrics',{}).get(metric)
            cells.append('未知' if value is None else f"{value['mean']:.6g} ± {value['spread']:.6g}")
        lines.append('| '+metric+' | '+' | '.join(cells)+' |')
    lines += ['', ('结论：样本未齐、提前停止或用量未知，不能作正式成本/质量结论。' if not complete else '结论：按下表逐项判断成本下降和质量底线；机制测试仍不属于模型结果。'), 'P2 对 E1（true=减少）：'+json.dumps(comparison,ensure_ascii=False),
        '质量底线逐组判定：'+json.dumps({g:v['quality'] for g,v in groups.items()},ensure_ascii=False),
        '完整运行且用量已知：'+str(complete), '限制：CQT/Q-time 未实现；机制测试不证明模型质量或成本。']
    if comparison:
        for metric,label in zip(METRICS[:2], ('未缓存等价输入 token','请求数下界')):
            value=comparison[metric]
            lines.append('P2 的'+label+('低于 E1。' if value is True else '未低于 E1。' if value is False else '无法判断。'))
        lines.append('P2 质量底线'+('全部满足。' if comparison['quality_floors_held'] else '未全部证实满足。'))
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    atomic_write(output/'results.json', canonical(result))
    atomic_write(output/'results.md', ('\n'.join(lines)+'\n').encode())
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('runs',nargs='+');p.add_argument('--output',required=True)
    a=p.parse_args();summarize(a.runs,a.output)
