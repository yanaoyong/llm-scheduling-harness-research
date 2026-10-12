#!/usr/bin/env python3
"""Freeze full-factory source files, simulator, controller and prespecified scenarios."""
import argparse,copy,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.experiment import code_files,digest,git,read_json,write_json,object_digest,now

def freeze(name,phase,config_path,auxiliary=False):
    cfg_path=(ROOT/config_path).resolve();cfg=read_json(cfg_path)
    paths=code_files()+[ROOT/'requirements.lock',ROOT/'docs/PROTOCOL_SMT_v1.md',
        ROOT/'docs/runtime-environment.json',ROOT/'scripts/freeze_smt.py',
        ROOT/'data/smt/source-manifest.json',ROOT/'data/smt/conversion-manifest.json',ROOT/'configs/smt-scenarios-v1.json']
    paths=sorted(set(paths))
    for p in paths:
        rel=str(p.relative_to(ROOT));raw=subprocess.run(['git','show','HEAD:'+rel],cwd=ROOT,capture_output=True)
        if raw.returncode or raw.stdout!=p.read_bytes():raise ValueError('Commit before freeze: '+rel)
    matrix=[[seed,arm,repeat] for seed in read_json(ROOT/'configs/smt-scenarios-v1.json')['formal']
            for repeat in (1,2,3) for arm in (('F',) if auxiliary else ('A','B','C'))]
    effective={}
    for repeat in (1,2,3):
        c=copy.deepcopy(cfg);c['model']['phase']='formal';c['seed']=[11,22,33][repeat-1]
        effective[str(repeat)]=object_digest(c)
    tag='freeze-'+name;value={'created_at':now(),'name':name,'dataset':'smt2020','phase':phase,'tag':tag,
        'code_commit':git('rev-parse','HEAD'),'protocol_version':cfg['protocol_version'],
        'config_path':str(cfg_path.relative_to(ROOT)),'effective_config_sha256':effective,'matrix':matrix,
        'core':not auxiliary,'files':{str(p.relative_to(ROOT)):digest(p) for p in paths},
        'source_data':{str(p.relative_to(ROOT)):digest(p) for p in sorted((ROOT/'data/smt/SMT2020_LVHM').iterdir()) if p.is_file()}}
    write_json(ROOT/'configs/freezes'/f'{name}.json',value,exclusive=True)
    subprocess.run(['git','tag','-a',tag,value['code_commit'],'-m',f'Frozen {phase}: {len(matrix)} scenarios/arm/repeat cells'],cwd=ROOT,check=True)
    print(name,len(matrix))

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--name',required=True);a.add_argument('--phase',required=True)
    a.add_argument('--config',required=True);a.add_argument('--auxiliary',action='store_true');x=a.parse_args();freeze(x.name,x.phase,x.config,x.auxiliary)
