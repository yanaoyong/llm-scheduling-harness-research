#!/usr/bin/env python3
"""Checksums of locally retained non-Git evidence; no credentials or environments."""
import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.experiment import digest,read_json,write_json,now

def paths():
    roots=[ROOT/x for x in ['runs','vendor','data/raw','artifacts/smt_development',
                          'artifacts/large','data/smt/SMT2020_LVHM']]
    evidence={p for root in roots if root.exists() for p in root.rglob('*') if p.is_file()
              and '__pycache__' not in p.parts and '.git' not in p.parts and p.suffix!='.lock'}
    # Validation/acquisition logs are intentionally ignored by Git too.
    evidence.update((ROOT/'progress').glob('*.log'))
    evidence.update((ROOT/'artifacts/review_static').glob('*.log'))
    return sorted(evidence)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--verify',action='store_true');a=ap.parse_args()
    target=ROOT/'progress/evidence-manifest.json'
    if a.verify:
        manifest=read_json(target);errors=[]
        for entry in manifest['files']:
            path=ROOT/entry['path']
            if not path.is_file() or path.stat().st_size!=entry['bytes'] or digest(path)!=entry['sha256']:errors.append(entry['path'])
        print('evidence files',len(manifest['files']),'mismatches',len(errors))
        if errors:print('\n'.join(errors));raise SystemExit(1)
    else:
        items=[{'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':digest(p)} for p in paths()]
        write_json(target,{'created_at':now(),'files':items,'total_bytes':sum(p['bytes'] for p in items),
            'data_recovery':'scripts/acquire_fjsp.py --prepare; scripts/acquire_smt.py --inspect-only (see source manifests for downloads)',
            'log_recovery':'Exact model outputs cannot be regenerated. These complete logs are retained locally; copy the listed files with their relative paths when archiving/restoring. No remote log backup was created.',
            'excluded':'virtual environment, Python caches, Git internals; recreate environment from requirements.lock'})
        print('inventoried',len(items),'files',sum(p['bytes'] for p in items),'bytes')

if __name__=='__main__':main()
