"""Offline per-instance summaries; no references are ever supplied to runtime agents."""
from __future__ import annotations
import argparse
import csv
import json
import os
import statistics
from collections import defaultdict
from src.experiment import ROOT,read_json,write_json,now,git,digest
from src.replay import audit_phase,_load_freeze


def gap(value,ref):
    return 100*(value-ref)/ref if value is not None and ref else None


def report(phase,plots=True):
    out=ROOT/'artifacts'/phase
    out.mkdir(parents=True,exist_ok=True)
    reference_path='docs/fjsp-reference-values.json'
    if phase=='development':
        reference=read_json(ROOT/reference_path);reference_hash=digest(ROOT/reference_path)
    else:
        frozen=_load_freeze(phase=phase)
        reference=json.loads(git('show',frozen['code_commit']+':'+reference_path))
        reference_hash=frozen['files'][reference_path]
    refs={r['instance_id']:r for r in reference['references']}
    audit=audit_phase(phase)
    write_json(out/'report_evidence_audit.json',audit)
    if audit['phase_errors'] or any(not x['audit_pass'] for x in audit['runs']+audit['auxiliary_runs']):
        raise ValueError('Evidence audit failed; report cannot certify these records')
    results=[read_json(p) for p in sorted((ROOT/'runs'/phase).glob('*/result.json')) if (p.parent/'input.json').exists()]
    baseline={(r['instance_id'],r['repeat']):r['metrics'].get('makespan') for r in results if r['arm']=='A' and r['status']=='success'}
    fixed_results=[r for r in results if r['arm']=='F']
    if phase.startswith('acceptance_'):
        fixed_results=[read_json(p) for p in (ROOT/'runs'/phase.replace('acceptance_','auxiliary_',1)).glob('*/result.json')]
    fixed={(r['instance_id'],r['repeat']):r['metrics'].get('makespan') for r in fixed_results if r['arm']=='F' and r['status']=='success'}
    rows=[]
    for r in results:
        metrics=r['metrics'];costs=r['costs'];ref=refs[r['instance_id']]
        value=metrics.get('makespan') if r['status']=='success' else None
        usage=costs.get('usage',costs)
        rows.append({'run_id':r['run_id'],'family':r['family'],'instance':r['instance_id'],
            'base_instance':r['base_instance'],'variant':r['variant'],'arm':r['arm'],'repeat':r['repeat'],
            'status':r['status'],'failure_type':r.get('failure_type'),'feasible':r['validation']['valid'],
            'makespan':value,'first_output_valid':metrics.get('first_output_valid',r.get('first_output_valid')),
            'revisions':metrics.get('revisions',r.get('revisions')),
            'reference_status':ref['reference_status'],'verified_optimum':ref['independently_verified_optimum'],
            'reported_optimum':ref['reported_optimum'],'reported_BKS':ref['best_known_feasible_value_reported'],
            'reported_lower_bound':ref['lower_bound_reported'],
            'gap_verified_optimum_pct':gap(value,ref['independently_verified_optimum']),
            'gap_reported_optimum_pct':gap(value,ref['reported_optimum']),
            'gap_reported_BKS_pct':gap(value,ref['best_known_feasible_value_reported']),
            'gap_reported_lower_bound_pct':gap(value,ref['lower_bound_reported']),
            'gap_paired_A_pct':gap(value,baseline.get((r['instance_id'],r['repeat']))),
            'gap_fixed_F_pct':gap(value,fixed.get((r['instance_id'],r['repeat']))),
            'end_to_end_seconds':costs.get('end_to_end_seconds'),'model_calls':costs.get('model_calls'),
            'model_seconds':costs.get('model_elapsed_seconds',costs.get('model_seconds')),
            'solver_seconds':costs.get('solver_wall_seconds'),
            'solver_internal_seconds':costs.get('solver_seconds'),
            'solver_budget_seconds':costs.get('solver_budget_seconds'),
            'input_tokens':usage.get('input_tokens'),'cached_input_tokens':usage.get('cached_input_tokens'),
            'output_tokens':usage.get('output_tokens'),'cost_usd':costs.get('cost_usd'),
            'code_commit':r['code_commit'],'config_sha256':r['config_sha256'],'data_sha256':r['data_sha256']})
    if rows:
        with (out/'results.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    groups=defaultdict(list)
    for row in rows:groups[(row['instance'],row['arm'])].append(row)
    aggregates=[]
    for (instance,arm),members in sorted(groups.items()):
        valid=[m for m in members if m['status']=='success']
        aggregates.append({'instance':instance,'arm':arm,'total':len(members),'successes':len(valid),
            'success_rate':len(valid)/len(members),
            'makespan_mean_conditional_success':statistics.mean(m['makespan'] for m in valid) if valid else None,
            'makespan_range_conditional_success':[min(m['makespan'] for m in valid),max(m['makespan'] for m in valid)] if valid else None,
            'wall_seconds_mean_all':statistics.mean(m['end_to_end_seconds'] for m in members)})
    summary={'at':now(),'phase':phase,'records':len(rows),'successes':sum(r['status']=='success' for r in rows),
             'failures':sum(r['status']!='success' for r in rows),'aggregates':aggregates,
             'core_records':sum(r['arm'] in ('A','B','C') for r in rows),
             'auxiliary_records':sum(r['arm']=='F' for r in rows),
             'coverage_complete':audit['coverage_complete'],'acceptance_ready':audit['acceptance_ready'],
             'reference_sha256':reference_hash,
             'expected_records':audit['expected_records'],'missing_records':len(audit['missing']),
             'monetary_cost':'unknown; no actual per-call billing available',
             'quality_statistics':'conditional on success; failures remain in denominators'}
    write_json(out/'summary.json',summary)
    if plots and results:
        os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'artifacts/.matplotlib'))
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        selected=[r for r in results if r['repeat']==1 and r['status']=='success']
        for r in selected:
            fig,ax=plt.subplots(figsize=(12,4))
            for op in r['schedule']['operations']:
                job=int(op['id'].split('o')[0][1:])
                ax.broken_barh([(op['start'],op['end']-op['start'])],(op['machine']-.35,.7),
                              facecolors=plt.get_cmap('tab20')(job%20),linewidth=0.1,edgecolor='white')
            ax.set(xlabel='Benchmark time unit',ylabel='Machine (zero-based)',
                   title=f'{r["instance_id"]} / {r["arm"]} / r1 — makespan {r["metrics"]["makespan"]}')
            ax.grid(axis='x',alpha=.2);fig.tight_layout()
            fig.savefig(out/(r['run_id']+'_gantt.png'),dpi=140);plt.close(fig)
    print(json.dumps({k:v for k,v in summary.items() if k!='aggregates'},ensure_ascii=False))
    return summary


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--phase',default='development');ap.add_argument('--no-plots',action='store_true');a=ap.parse_args();report(a.phase,not a.no_plots)
