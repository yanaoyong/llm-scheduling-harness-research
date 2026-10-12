#!/usr/bin/env python3
"""Final presentation fixes from certified saved data; frozen runtime untouched."""
import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('MPLCONFIGDIR', str(ROOT / 'artifacts/.matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def read(p):
    return json.loads(p.read_text())

rows = []
for phase, arms in [('acceptance_static_v1', ['A', 'B', 'C']), ('auxiliary_static_v1', ['F']),
                    ('recovery_static_channel_v1', ['B'])]:
    recovery = phase.startswith('recovery_')
    for arm in arms:
        rid = 'mk08_B_r1__channel_recovery_1' if recovery else f'mk05_{arm}_r1'
        source = ROOT / 'runs' / phase / rid / 'result.json'
        r = read(source)
        audit_path = ROOT / 'artifacts' / ('static_recovery/audit.json' if recovery else phase + '/replay_final.json')
        audit = read(audit_path)
        cert = next(x for x in (audit['recovery_records'] if recovery else audit['runs'] + audit['auxiliary_runs']) if x['run_id'] == rid)
        assert cert['audit_pass'] and cert['valid'] and cert['makespan'] == r['metrics']['makespan']
        fig, ax = plt.subplots(figsize=(12, 4))
        for op in r['schedule']['operations']:
            job = int(op['id'].split('o')[0][1:])
            ax.broken_barh([(op['start'], op['end'] - op['start'])], (op['machine'] - .35, .7),
                           facecolors=plt.get_cmap('tab20')(job % 20), linewidth=.1, edgecolor='white')
        machines = read(source.parent / 'input.json')['machines']
        count = machines if isinstance(machines, int) else len(machines)
        ax.set_yticks(range(count))
        ax.set_ylim(-.6, count - .4)
        ax.set(xlabel='Benchmark time unit', ylabel='Machine (zero-based)',
               title=f'{r["instance_id"]} / {arm} / ' + ('supplementary channel recovery' if recovery else 'r1') + f' — makespan {r["metrics"]["makespan"]}')
        ax.grid(axis='x', alpha=.2); fig.tight_layout()
        out = ROOT / 'artifacts' / ('static_recovery' if recovery else phase) / (rid + '_gantt.png')
        fig.savefig(out, dpi=140); plt.close(fig)
        rows.append({'output': str(out.relative_to(ROOT)), 'sha256': sha(out),
                     'sources': {str(p.relative_to(ROOT)): sha(p) for p in [source, audit_path]},
                     'change': 'integer machine ticks; saved operations unchanged'})
for phase in ['acceptance_smt_v1', 'auxiliary_smt_v1']:
    source = ROOT / 'artifacts' / phase / 'smt_decisions.csv'
    decisions = list(csv.DictReader(source.open()))
    ids = sorted({r['run_id'] for r in decisions if r['repeat'] == '1'})
    for rid in ids:
        d = [r for r in decisions if r['run_id'] == rid]
        assert all(r['certified_success'] == 'True' and r['solver_time_attribution_complete'] == 'True' for r in d)
        model = [float(r['model_channel_seconds']) for r in d]
        solver = [float(r['solver_seconds']) for r in d]
        ix = [int(r['decision']) for r in d]
        fig, ax = plt.subplots(figsize=(9, 3.8))
        ax.bar(ix, model, label='Model channel incl. CLI')
        ax.bar(ix, solver, bottom=model, label='Attributed solver')
        ax.set_ylim(0, max(a+b for a,b in zip(model, solver)) * 1.32)
        ax.set(xlabel='Decision index', ylabel='Wall seconds (service only)',
               title=f'{rid}: decision service time\nExcludes simulation and IO; axes differ between panels')
        ax.set_xticks(ix); ax.legend(loc='upper right', fontsize=9)
        fig.tight_layout()
        out = ROOT / 'artifacts' / phase / (rid + '_smt_decision_service.png')
        fig.savefig(out, dpi=135); plt.close(fig)
        rows.append({'output': str(out.relative_to(ROOT)), 'sha256': sha(out),
                     'sources': {str(source.relative_to(ROOT)): sha(source)},
                     'change': 'explicit positive y headroom prevents zero-height stacked bars clipping model maxima'})
out = ROOT / 'artifacts/final/plot_polish_manifest.json'
out.write_text(json.dumps({'at': dt.datetime.now(dt.timezone.utc).isoformat(), 'script_sha256': sha(Path(__file__)),
    'scope': 'presentation only; no run, metric, frozen source or certification changed', 'plots': rows}, ensure_ascii=False, indent=2)+'\n')
print(json.dumps({'plots': len(rows), 'manifest': str(out.relative_to(ROOT))}))
