"""Offline verification, derived metrics, and exportable SVG Gantt charts."""
from __future__ import annotations
import argparse,csv,hashlib,html,json,statistics
from pathlib import Path
from validator import validate_schedule
ROOT=Path(__file__).resolve().parents[1]
def read(p):return json.loads(p.read_text())
def dump(p,o):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(o,ensure_ascii=False,indent=2)+'\n')
def mean(v):return statistics.mean(v) if v else None

def gantt(inst,schedule,target,title):
    ops={o['id']:o for o in inst['operations']};rows=schedule['operations']
    machine_keys=sorted({(ops[r['id']]['group'],r['machine']) for r in rows})
    mx=max(r['end'] for r in rows);width=1240;left=220;scale=(width-left-35)/max(mx,1);height=120+len(machine_keys)*66
    colors=['#3171a8','#d78732','#539971','#8f68b5','#c25e6b','#569fa3','#a59b4f','#8f6e59']
    lots=sorted({(o['lot'],o['product']) for o in ops.values()});palette={lot:colors[i%len(colors)] for i,lot in enumerate(lots)}
    svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">', '<rect width="100%" height="100%" fill="#ffffff"/>', f'<text x="24" y="30" font-size="19" font-family="sans-serif" fill="#172b42">{html.escape(title)} | Cmax={mx}</text>','<text x="24" y="53" font-size="12" font-family="sans-serif" fill="#536273">Blocks: lot/product/step; gray: required setup + later maintenance. Initial PM is a state marker.</text>']
    ticks=10
    for t in range(ticks+1):
        value=round(mx*t/ticks);x=left+value*scale
        svg.append(f'<path d="M{x} 72 V{height-33}" stroke="#e5e9ef"/><text x="{x}" y="{height-12}" text-anchor="middle" font-size="11" font-family="sans-serif">{value}</text>')
    for k,(group,machine) in enumerate(machine_keys):
        y=83+k*66
        svg.append(f'<text x="12" y="{y+23}" font-family="sans-serif" font-size="12">{html.escape(group)} / {machine}</text>')
        sequence=sorted([r for r in rows if ops[r['id']]['group']==group and r['machine']==machine],key=lambda r:r['start'])
        last_setup=0
        for i,r in enumerate(sequence):
            o=ops[r['id']];setup=o['setup'] or last_setup;change=(i==0 or setup!=last_setup)
            setup_t=inst['setups'].get(group,{}).get(setup,{}).get('duration',0) if change else 0
            pm_t=sum(m['duration'] for m in inst['maintenance'] if m['group']==group and m['name'] in r['maintenance']) if i else 0
            overhead=setup_t+pm_t
            if overhead:
                a=max(0,r['start']-overhead);svg.append(f'<rect x="{left+a*scale:.2f}" y="{y+9}" width="{(r["start"]-a)*scale:.2f}" height="28" fill="#b9c0c8"><title>setup={setup_t}, PM={pm_t}; drawn immediately before process</title></rect>')
            x=left+r['start']*scale;w=(r['end']-r['start'])*scale;label=f'{o["lot"]}/{o["product"]}/{o["step"]}'
            svg.append(f'<rect x="{x:.2f}" y="{y}" width="{w:.2f}" height="44" rx="3" fill="{palette[o["lot"],o["product"]]}"><title>{label}; [{r["start"]},{r["end"]}); PM={html.escape(str(r["maintenance"]))}</title></rect>')
            if w>24:svg.append(f'<text x="{x+w/2:.2f}" y="{y+25}" text-anchor="middle" font-size="9" font-family="sans-serif" fill="white">{label}</text>')
            last_setup=setup
    svg.append('</svg>');target.parent.mkdir(parents=True,exist_ok=True);target.write_text('\n'.join(svg))

def replay(phase):
    dirs=sorted((ROOT/'runs'/phase).glob('*/result.json'));rows=[];issues=[]
    incomplete=[]
    for started in (ROOT/'runs'/phase).glob('*/started.json'):
        if not (started.parent/'result.json').exists():
            incomplete.append(started.parent.name)
            issues.append({'run_id':started.parent.name,'error':'started run missing result; interrupted attempt must be preserved and diagnosed'})
    for result_path in dirs:
        r=read(result_path)
        if 'arm' not in r:continue
        d=result_path.parent;inst=read(d/'input.json');checked=None
        from problem import load_instance
        source=ROOT/'data/smoke.lp' if r['instance']=='smoke' else ROOT/'vendor/FJSP-SMT2020/PADL-2023/instances'/f'{r["instance"]}.lp'
        if not source.exists() or hashlib.sha256(source.read_bytes()).hexdigest()!=r['input_sha256']:
            issues.append({'run_id':r['run_id'],'error':'source input hash differs'})
        else:
            actual=load_instance(source)
            if {k:v for k,v in actual.items() if k!='source'}!={k:v for k,v in inst.items() if k!='source'}:issues.append({'run_id':r['run_id'],'error':'normalized input differs from original facts'})
        if hashlib.sha256((d/'config.json').read_bytes()).hexdigest()!=r['config_sha256']:issues.append({'run_id':r['run_id'],'error':'config hash differs'})
        started=read(d/'started.json')
        if any(started.get(k)!=r.get(k) for k in ['arm','instance','input_sha256']):issues.append({'run_id':r['run_id'],'error':'run identity differs from start record'})
        if r.get('schedule_file'):
            schedule=read(d/r['schedule_file']);checked=validate_schedule(inst,schedule)
            if checked!=r['validation']:issues.append({'run_id':r['run_id'],'error':'validation replay differs'})
            if r['status']=='success' and not checked['feasible']:issues.append({'run_id':r['run_id'],'error':'false success'})
            if checked['feasible']:gantt(inst,schedule,ROOT/'artifacts'/phase/f'{r["run_id"]}.svg',r['run_id'])
        elif r['status']=='success':issues.append({'run_id':r['run_id'],'error':'success missing schedule'})
        reqs=sorted(d.glob('model_*/request.json'))
        if len(reqs)!=r['model_calls']:issues.append({'run_id':r['run_id'],'error':'model request count mismatch'})
        for req in reqs:
            cr=read(req.parent/'result.json')
            if cr.get('native_tool_events'):issues.append({'run_id':r['run_id'],'error':'native tool event'})
        rows.append(dict(r,objective=checked['objective'] if checked and checked['feasible'] else None))
    if phase.startswith('acceptance'):
        split=read(ROOT/'configs/instance_split.json')
        expected={(inst,arm,rep) for inst in split.get(phase,[]) for arm in 'ABC' for rep in range(1,4)}
        actual=[(r['instance'],r['arm'],r['repetition']) for r in rows]
        if len(actual)!=len(set(actual)) or set(actual)!=expected:issues.append({'error':'formal Cartesian grid missing, duplicate or unexpected cell','expected':len(expected),'actual':len(actual)})
        from runner import check_freeze
        try:check_freeze()
        except Exception as error:issues.append({'error':'freeze verification failed','detail':str(error)})
    baseline={(r['instance'],r['repetition']):r['objective']['makespan'] for r in rows if r['arm']=='A' and r['status']=='success'}
    for r in rows:
        base=baseline.get((r['instance'],r['repetition']))
        r['baseline_makespan']=base
        r['baseline_gap_pct']=100*(r['objective']['makespan']-base)/base if base and r['objective'] else None
    armstats={}
    for arm in ['A','B','C']:
        subset=[r for r in rows if r['arm']==arm];success=[r for r in subset if r['status']=='success'];usage={}
        for key in ['input_tokens','cached_input_tokens','output_tokens']:
            usage[key]=sum(r['usage'][key] for r in subset) if all(r['usage'].get(key) is not None for r in subset) else None
        armstats[arm]={'runs':len(subset),'success':len(success),'first_candidate_feasible':sum(r['first_candidate_feasible'] is True for r in subset),
            'mean_makespan':mean([r['objective']['makespan'] for r in success]),'mean_setup_violations':mean([r['objective']['setup_violations'] for r in success]),
            'mean_baseline_gap_pct':mean([r['baseline_gap_pct'] for r in success if r['baseline_gap_pct'] is not None]),
            'mean_end_to_end_seconds':mean([r['end_to_end_seconds'] for r in subset]),
            'total_end_to_end_seconds':sum(r['end_to_end_seconds'] for r in subset),
            'total_model_elapsed_seconds':sum(r['model_elapsed_seconds'] for r in subset),'total_solver_seconds':sum(r['solver_seconds'] for r in subset),
            'total_model_calls':sum(r['model_calls'] for r in subset),'total_revisions':sum(r['revision_count'] for r in subset),'usage':usage}
    out=ROOT/'artifacts'/phase
    summary={'phase':phase,'total_runs':len(rows),'success':sum(r['status']=='success' for r in rows),'issues':issues,'incomplete_attempts':incomplete,'total_attempts':len(rows)+len(incomplete),'arms':armstats,'runs':rows}
    dump(out/'summary.json',summary)
    fields=['run_id','instance','repetition','arm','status','failure_reason','makespan','setup_violations','baseline_makespan','baseline_gap_pct','first_candidate_feasible','revision_count','fallback','end_to_end_seconds','model_elapsed_seconds','pure_model_seconds','solver_seconds','model_calls','solver_calls','solver_time_limit_reached','input_tokens','cached_input_tokens','output_tokens','cost_usd']
    with (out/'results.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fields);writer.writeheader()
        for r in rows:
            flat=dict(r,**(r['objective'] or {'makespan':None,'setup_violations':None}),**r['usage']);writer.writerow({k:flat.get(k) for k in fields})
    # Costs of channel probes and failed invocations are counted separately too.
    costs={}
    for request in (ROOT/'runs').rglob('request.json'):
        phase_name=request.relative_to(ROOT/'runs').parts[0];cost=costs.setdefault(phase_name,{'attempts':0,'reported_calls':0,'input_tokens':0,'cached_input_tokens':0,'output_tokens':0,'elapsed_seconds':0,'unreported_attempts':0,'unknown_by_field':{k:0 for k in ['input_tokens','cached_input_tokens','output_tokens']},'cost_usd':None})
        cost['attempts']+=1
        category='channel_probe' if any(part.startswith('channel_probe') for part in request.parts) else 'scheduling'
        categories=cost.setdefault('attempts_by_category',{})
        categories[category]=categories.get(category,0)+1
        res=request.parent/'result.json'
        c=read(res) if res.exists() else {}
        cost['elapsed_seconds']+=c.get('duration_seconds',0)
        u=c.get('usage',{})
        if all(u.get(k) is not None for k in ['input_tokens','cached_input_tokens','output_tokens']):cost['reported_calls']+=1
        else:cost['unreported_attempts']+=1
        for key in ['input_tokens','cached_input_tokens','output_tokens']:
            if u.get(key) is None:cost['unknown_by_field'][key]+=1
            else:cost[key]+=u[key]
    for cost in costs.values():
        cost['usage_complete']=cost['unreported_attempts']==0
        for key in ['input_tokens','cached_input_tokens','output_tokens']:
            cost['known_'+key]=cost[key]
            if cost['unknown_by_field'][key]:cost[key]=None
    dump(ROOT/'artifacts'/'model_usage_ledger.json',costs)
    html_parts=['<!doctype html><meta charset="utf-8"><title>半导体排程实验</title><style>body{font:16px system-ui;max-width:1300px;margin:36px auto;padding:20px;background:#f2f5f8}section{background:white;padding:16px;margin:24px 0;border-radius:12px}img{width:100%}a{color:#245f91}</style>',f'<h1>半导体排程实验 · {phase}</h1><p>{summary["success"]}/{len(rows)} 条成功；每条图均来自完整原始排程。灰条为换型与非初始维护。</p>']
    for r in rows:
        if r['status']=='success':html_parts.append(f'<section><h2>{r["run_id"]}</h2><p>makespan {r["objective"]["makespan"]}；相对配对A差距 {r["baseline_gap_pct"] if r["baseline_gap_pct"] is not None else "未知"}%</p><img src="{r["run_id"]}.svg"></section>')
        else:html_parts.append(f'<section><h2>{r["run_id"]}</h2><p>{html.escape(str(r["failure_reason"]))}</p></section>')
    (out/'gantt.html').write_text('\n'.join(html_parts))
    print(json.dumps({k:summary[k] for k in ['total_runs','success','issues','arms']},ensure_ascii=False,indent=2))
    if issues:raise SystemExit(1)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--phase',default='acceptance_v1');a=p.parse_args();replay(a.phase)
