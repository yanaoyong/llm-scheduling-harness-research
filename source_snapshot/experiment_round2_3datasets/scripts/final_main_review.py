#!/usr/bin/env python3
"""Reproducible final read-only checks; does not sign acceptance automatically."""
import argparse
import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / 'artifacts/final/qa'

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

def history():
    before_path = ROOT / 'progress/history-integrity-before.json'
    before = json.loads(before_path.read_text())
    after, errors = [], []
    for old in before:
        p = ROOT.parent / old['path']
        if not p.is_file():
            errors.append({'missing': old['path']})
            continue
        row = {'path': old['path'], 'bytes': p.stat().st_size, 'sha256': sha(p)}
        after.append(row)
        if row != old:
            errors.append({'changed': old['path'], 'before': old, 'after': row})
    # All originally inventoried files are verified, with added files separately visible.
    known = {x['path'] for x in before}
    added = []
    for name in ['inputs', 'm0.5_research', 'summary.md', 'relocation.json', 'experiment_round1']:
        top = ROOT.parent / name
        paths = [top] if top.is_file() else top.rglob('*')
        for p in paths:
            if p.is_file() and not any(x in p.parts for x in ['.git', '.venv', '__pycache__', '.pytest_cache', '.cache']):
                rel = str(p.relative_to(ROOT.parent))
                if rel not in known:
                    added.append(rel)
    after_path = ROOT / 'progress/history-integrity-after.json'
    save(after_path, after)
    out = {'at': dt.datetime.now(dt.timezone.utc).isoformat(), 'reviewer': 'main agent, actual filesystem hash comparison',
           'before': {'path': str(before_path.relative_to(ROOT)), 'sha256': sha(before_path)},
           'after': {'path': str(after_path.relative_to(ROOT)), 'sha256': sha(after_path)},
           'original_files': len(before), 'verified_files': len(after), 'original_bytes': sum(x['bytes'] for x in before),
           'errors': errors, 'additional_paths_under_protected_roots': sorted(added), 'passed': not errors and not added}
    save(QA / 'history_integrity.json', out)
    print(json.dumps({k: v for k, v in out.items() if k not in ('before', 'after')}, ensure_ascii=False))
    return 0 if out['passed'] else 1

def contacts():
    from PIL import Image, ImageDraw
    groups = {'static': [], 'dynamics': [], 'service': []}
    for phase in ['acceptance_static_v1', 'auxiliary_static_v1', 'acceptance_smt_v1', 'auxiliary_smt_v1', 'static_recovery']:
        for p in sorted((ROOT / 'artifacts' / phase).glob('*.png')):
            key = 'static' if 'gantt' in p.name else 'dynamics' if 'dynamics' in p.name else 'service'
            groups[key].append(p)
    records, sheets = [], []
    for group, paths in groups.items():
        per = 3 if group != 'dynamics' else 2
        for offset in range(0, len(paths), per):
            subset = paths[offset:offset + per]
            images = [Image.open(p).convert('RGB') for p in subset]
            w = max(i.width for i in images)
            h = sum(i.height + 26 for i in images)
            sheet = Image.new('RGB', (w, h), '#ffffff')
            draw = ImageDraw.Draw(sheet)
            y = 0
            target = QA / 'contacts' / f'{group}_{offset // per + 1:02d}.png'
            target.parent.mkdir(parents=True, exist_ok=True)
            for p, im in zip(subset, images):
                draw.text((8, y + 4), str(p.relative_to(ROOT)), fill='#111111')
                sheet.paste(im, (0, y + 26)); y += im.height + 26
                records.append({'path': str(p.relative_to(ROOT)), 'sha256': sha(p), 'width': im.width, 'height': im.height,
                                'contact_sheet': str(target.relative_to(ROOT))})
            sheet.save(target)
            sheets.append(str(target.relative_to(ROOT)))
    for p in sorted((ROOT / 'artifacts/final').glob('*.png')):
        im = Image.open(p)
        records.append({'path': str(p.relative_to(ROOT)), 'sha256': sha(p), 'width': im.width, 'height': im.height,
                        'contact_sheet': None})
    save(QA / 'figure_inventory.json', {'prepared_at': dt.datetime.now(dt.timezone.utc).isoformat(),
         'status': 'awaiting_actual_visual_review', 'figures': records, 'sheets': sheets})
    print(json.dumps({'figures': len(records), 'sheets': sheets}))
    return 0

def readme():
    commands = [
        ['.venv/bin/python', 'scripts/acquire_fjsp.py', '--prepare'],
        ['.venv/bin/python', 'scripts/acquire_smt.py', '--inspect-only'],
        ['/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex', 'login', 'status'],
        ['.venv/bin/python', 'scripts/probe_model.py', '--run-dir', 'runs/development/channel_probe_authorized', '--resume'],
        ['.venv/bin/python', '-m', 'src.runner', 'run', '--instance', 'mk10', '--arm', 'B', '--run-id', 'dev_mk10_B_compact_v2', '--config', 'configs/development-v2.json'],
        ['.venv/bin/python', '-m', 'src.smt_control', '--arm', 'B', '--run-id', 'dev_smt701_B'],
    ]
    for name in ['static-v1', 'static-aux-v2', 'smt-v1', 'smt-aux-v1']:
        commands.append(['.venv/bin/python', '-m', 'src.batch', '--freeze', name])
    for smt, phase in [(False, 'development'), (True, 'development'), (False, 'acceptance_static_v1'),
                       (False, 'auxiliary_static_v1'), (True, 'acceptance_smt_v1'), (True, 'auxiliary_smt_v1')]:
        commands.append(['.venv/bin/python', '-m', 'src.smt_replay' if smt else 'src.replay', '--phase', phase, '--label', 'readme'])
    ledger = ROOT / 'progress/model_ledger.jsonl'
    before = sha(ledger)
    rows = []
    for n, command in enumerate(commands, 1):
        target = QA / 'readme' / f'command_{n:02d}.txt'
        target.parent.mkdir(parents=True, exist_ok=True)
        start = dt.datetime.now(dt.timezone.utc)
        with target.open('w') as f:
            result = subprocess.run(command, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT)
        row = {'command': command, 'cwd': str(ROOT), 'started_at': start.isoformat(),
               'finished_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'exit_code': result.returncode,
               'log': str(target.relative_to(ROOT)), 'sha256': sha(target)}
        rows.append(row)
        print(json.dumps(row), flush=True)
    out = {'at': dt.datetime.now(dt.timezone.utc).isoformat(), 'commands': rows,
           'ledger_before_sha256': before, 'ledger_after_sha256': sha(ledger),
           'no_new_model_or_solver_reservations': sha(ledger) == before,
           'note': 'Development replay can retain known historical failures/incomplete provenance; inspect actual outputs separately.',
           'exit_codes': [r['exit_code'] for r in rows]}
    save(QA / 'readme_commands.json', out)
    return 0 if out['no_new_model_or_solver_reservations'] else 1

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['history', 'contacts', 'readme'])
    a = p.parse_args()
    raise SystemExit(globals()[a.mode]())
