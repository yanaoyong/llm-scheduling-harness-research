#!/usr/bin/env python3
"""Cross-phase fixed-control pairs and logical recovery delivery, kept separate."""
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/final'
sources = {}

def csv_read(relative):
    p = ROOT / relative
    sources[relative] = hashlib.sha256(p.read_bytes()).hexdigest()
    return list(csv.DictReader(p.open()))

def csv_write(path, rows):
    with path.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)

core = csv_read('artifacts/acceptance_smt_v1/smt_results.csv')
aux = csv_read('artifacts/auxiliary_smt_v1/smt_results.csv')
a = {(x['scenario'], x['repeat']): x for x in core if x['arm'] == 'A'}
pairs = []
for f in aux:
    base = a[f['scenario'], f['repeat']]
    assert f['arm'] == 'F' and base['certified_success'] == f['certified_success'] == 'True'
    q = 'controlled_family_queue_area_lot_seconds'
    pairs.append({'scenario': f['scenario'], 'repeat': f['repeat'], 'a_run_id': base['run_id'],
       'f_run_id': f['run_id'], 'A_queue_area': base[q], 'F_queue_area': f[q],
       'gap_F_vs_A_pct': 100 * (float(f[q]) / float(base[q]) - 1),
       'A_phase': 'acceptance_smt_v1', 'F_phase': 'auxiliary_smt_v1', 'both_certified': True})
assert len(pairs) == 9
csv_write(OUT / 'smt_fixed_pairing.csv', pairs)
group_rows = csv_read('artifacts/acceptance_smt_v1/smt_group_observation.csv')
groups = []
for group in sorted({x['group'] for x in group_rows}):
    members = [x for x in group_rows if x['group'] == group]
    assert len(members) == 27 and all(x['certified_success'] == 'True' for x in members)
    groups.append({'group': group, 'physical_machines': int(members[0]['physical_machines']),
         'records': len(members), **{f'{key}_{extreme}_pct': 100 * fn(float(x[key]) for x in members)
         for key in ['reserved_observed_fraction', 'calendar_down_observed_fraction']
         for extreme, fn in [('min', min), ('max', max)]}})
csv_write(OUT / 'smt_group_ranges.csv', groups)
p = ROOT / 'artifacts/static_recovery/audit.json'
audit = json.loads(p.read_text())
assert audit['acceptance_ready'] and audit['logical_delivered'] == 108
sources[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
csv_write(ROOT / 'artifacts/static_recovery/logical_delivery.csv', audit['logical_delivery'])
manifest = {'at': dt.datetime.now(dt.timezone.utc).isoformat(), 'source_sha256': sources,
 'formula': '100 * (F.queue_area / A.queue_area - 1); pair same scenario/repeat; no causal matching claim',
 'recovery_scope': 'logical delivery only; original reports unchanged',
 'groups_scope': 'range across 27 original core runs, not confidence intervals',
 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
(OUT / 'smt_fixed_pairing_sources.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
print(json.dumps({'smt_pairs': len(pairs), 'groups': len(groups), 'static_logical_delivery': 108}))
