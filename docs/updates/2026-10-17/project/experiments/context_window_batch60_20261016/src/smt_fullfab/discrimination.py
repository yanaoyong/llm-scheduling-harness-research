"""Analyze a preregistered, paired offline pilot without dropping failures.

These are five cold-start development seeds, not a formal ranking. No model calls.
"""
from __future__ import annotations
import itertools
import json
import math
from pathlib import Path
import statistics

from .environment import digest, write_new
from .budget import ROOT

METRICS=('weighted_tardy_lot_hours','throughput_lots','terminal_wip_lots','terminal_tardy_wip_lots')


def paired_summary(differences):
    if len(differences)!=5:
        raise ValueError('This preregistered exploratory analysis requires all five pairs')
    mean=statistics.mean(differences)
    sd=statistics.stdev(differences)
    se=sd/math.sqrt(5)
    # Exact df=4 CDF inversion: F(t)=1/2+3u/4-u^3/4, u=t/sqrt(t^2+4).
    lo,hi=0.0,100.0
    for _ in range(100):
        mid=(lo+hi)/2;u=mid/math.sqrt(mid*mid+4)
        if .5+.75*u-.25*u**3 < .975:lo=mid
        else:hi=mid
    critical=(lo+hi)/2
    permutations=[statistics.mean([sign*x for sign,x in zip(signs,differences)])
                  for signs in itertools.product((-1,1),repeat=5)]
    p=sum(abs(x)>=abs(mean)-1e-12 for x in permutations)/len(permutations)
    z=statistics.NormalDist()
    return {'paired_difference_definition':'CR minus FIFO', 'independent_seed_count':5,
            'differences':differences,'mean':mean,'sample_sd':sd,'standard_error':se,
            't_interval_95':[mean-critical*se,mean+critical*se],
            't_interval_assumption':'independent approximately normal seed-level paired differences; five-pair exploratory interval',
            'exact_sign_flip_two_sided_p':p,
            'sign_flip_assumption':'exchangeable signs under the sharp paired null; smallest attainable two-sided p with five nonzero pairs is 0.0625',
            'normal_approx_mde_80pct_power_two_sided_5pct':(z.inv_cdf(.975)+z.inv_cdf(.8))*se,
            'mde_limitation':'normal approximation using noisy five-seed pilot variance; not verified power for a formal sample design'}


def analyze(*,output):
    prereg_path=ROOT/'configs/smt_fullfab/offline_development_next_v1.json'
    cfg=json.loads(prereg_path.read_text())['reference_discrimination_8h']
    records=[];pairs=[];failures=[];versions=set()
    for seed in cfg['seeds']:
        pair={}
        for policy in cfg['policies']:
            path=ROOT/f'runs/smt_fullfab_development/ref_{policy}_{seed}_8h_discrimination_v1/result.json'
            if not path.exists():raise ValueError('Missing preregistered outcome: '+str(path))
            r=json.loads(path.read_text())
            if r['config']['seed']!=seed or r['config']['seconds']!=cfg['seconds'] or r['config']['arm']!='reference_'+policy:
                raise ValueError('Run identity does not match preregistration')
            versions.add(digest(r['provenance']['source_sha256']))
            records.append({'seed':seed,'policy':policy,'path':str(path.relative_to(ROOT)),
                            'sha256':digest(r),'status':r['status'],'failure':r['failure'],
                            'full_window_completed':r['full_window_completed'],'audit_valid':r['audit_valid'],
                            'wall_seconds':r['wall_seconds'],'metrics':r.get('metrics')})
            if r['status']!='success' or not r['audit_valid'] or not r['full_window_completed']:
                failures.append(records[-1])
            else:pair[policy]=r['metrics']
        pairs.append(pair)
    same_version=len(versions)==1
    valid=not failures and same_version
    summaries={k:paired_summary([p['cr'][k]-p['fifo'][k] for p in pairs]) for k in METRICS} if valid else None
    result={'schema':'smt-fullfab-discrimination-pilot-1','formal':False,'preregistration':str(prereg_path.relative_to(ROOT)),
            'preregistration_sha256':digest(json.loads(prereg_path.read_text())),
            'all_preregistered_outcomes_retained':True,'same_implementation':same_version,
            'implementation_digests':sorted(versions),'all_pairs_usable':valid,'records':records,
            'failures':failures,'paired_summaries':summaries,
            'scope':'Full 913-machine CR/FIFO references, five independent exogenous seeds, common cold-start WIP, 8h. Not A/B/C comparison or steady-state evidence.',
            'limitations':['Tiny pilot sample; variance and required formal sample size are uncertain.',
                           'Correlated within-run dispatches are not independent samples.',
                           'No official-reference equivalence or online decision-latency claim.',
                           'No failure, seed or metric is removed after observing outcomes.']}
    write_new(Path(output),result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('records','failures')},ensure_ascii=False,indent=2))
    return result

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',required=True)
    analyze(**vars(p.parse_args()))
