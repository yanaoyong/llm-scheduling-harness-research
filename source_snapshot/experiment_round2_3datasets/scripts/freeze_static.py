#!/usr/bin/env python3
"""Freeze committed execution files, dataset split and config; refuse overwrites."""
import argparse
import copy
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.experiment import code_files,digest,git,read_json,write_json,object_digest,now


def freeze(name,phase,config_path,auxiliary=False):
    cfg_path=(ROOT/config_path).resolve();cfg=read_json(cfg_path)
    paths=code_files('fjsp')+[ROOT/'requirements.lock',ROOT/'docs/PROTOCOL_STATIC_v1.md',
        ROOT/'docs/fjsp-reference-values.json',ROOT/'scripts/freeze_static.py',ROOT/'docs/runtime-environment.json']
    paths+=list((ROOT/'data/fjsp').rglob('*.json'))
    paths=sorted(set(paths))
    for p in paths:
        rel=str(p.relative_to(ROOT))
        raw=subprocess.run(['git','show','HEAD:'+rel],cwd=ROOT,capture_output=True)
        if raw.returncode or raw.stdout!=p.read_bytes():raise ValueError('Must commit execution file before freezing: '+rel)
    split=read_json(ROOT/'data/fjsp/split.json')['splits']['formal']
    instances=split['brandimarte']+split['hurink']
    matrix=[[i,arm,repeat] for i in instances for repeat in (1,2,3) for arm in (('F',) if auxiliary else ('A','B','C'))]
    hashes={}
    for repeat in (1,2,3):
        c=copy.deepcopy(cfg);c['model']['phase']='formal';c['seed']=[11,22,33][repeat-1]
        hashes[str(repeat)]=object_digest(c)
    tag='freeze-'+name
    value={'created_at':now(),'name':name,'phase':phase,'tag':tag,'code_commit':git('rev-parse','HEAD'),
           'protocol_version':cfg['protocol_version'],'config_path':str(cfg_path.relative_to(ROOT)),
           'effective_config_sha256':hashes,'matrix':matrix,'core':not auxiliary,
           'files':{str(p.relative_to(ROOT)):digest(p) for p in paths}}
    path=ROOT/'configs/freezes'/f'{name}.json'
    write_json(path,value,exclusive=True)
    subprocess.run(['git','tag','-a',tag,value['code_commit'],'-m',f'Frozen {phase}: {len(matrix)} prespecified records'],cwd=ROOT,check=True)
    print(path)


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--name',required=True);a.add_argument('--phase',required=True)
    a.add_argument('--config',required=True);a.add_argument('--auxiliary',action='store_true');x=a.parse_args()
    freeze(x.name,x.phase,x.config,x.auxiliary)
