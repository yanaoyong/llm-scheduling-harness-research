#!/usr/bin/env python3
"""Independent read-only budget reconstruction; never imports experiment runtime code."""
from __future__ import annotations
import collections
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import time

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/final/qa/budget_audit.json'
DOC=ROOT/'docs/review-final-budget.md'
TOKENS=('input_tokens','output_tokens','cached_input_tokens','cache_write_input_tokens','reasoning_output_tokens')
LIMITS={'development':{'calls':24,'tokens':400000,'unknown':3,'solver_seconds':600},
        'formal':{'calls':300,'tokens':3000000,'unknown':3,'solver_seconds':4500,'activity_seconds':14400}}
FREEZES=('static-v1','smt-v1','static-aux-v2','smt-aux-v1')


def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def stamp(s):return dt.datetime.fromisoformat(s)
def numeric(v):return type(v) in (int,float) and math.isfinite(v)
def known(v):return type(v) is int and v>=0

def main():
    begun=time.process_time();errors=[];warnings=[];checks=collections.Counter();sources={}
    def check(ok,message,category):
        checks[category]+=1
        if not ok:errors.append({'category':category,'message':message})
    def near(a,b,message,category='cost',tol=1e-6):
        check(numeric(a) and numeric(b) and abs(a-b)<=tol,message,category)
    def loaded(p):
        sources[str(p.relative_to(ROOT))]=sha(p);return read(p)
    ledger_path=ROOT/'progress/model_ledger.jsonl';sources[str(ledger_path.relative_to(ROOT))]=sha(ledger_path)
    ledger=[json.loads(line) for line in ledger_path.read_text().splitlines() if line.strip()]
    grants={};reserves={};finishes={};phasecalls=collections.Counter();grantcalls=collections.Counter()
    phasesolver=collections.Counter();grantsolver=collections.Counter();phaseusage=collections.defaultdict(collections.Counter)
    unknown=collections.defaultdict(list);pending=collections.defaultdict(set);admissions=[];solver_admissions=[]
    missing_admission=[];previous=None
    for line,row in enumerate(ledger,1):
        current=stamp(row['at']);check(previous is None or current>=previous,f'Ledger line {line}: timestamp went backwards','ledger_order');previous=current
        event=row['event']
        if event in ('grant','solver_grant'):
            gid=row['grant_id'];phase=row['phase'];check(gid not in grants,f'Duplicate grant {gid}','grant');grants[gid]=row
            expected=LIMITS[phase]['calls' if event=='grant' else 'solver_seconds']
            near(row['phase_limit'],expected,f'{gid}: global limit differs from protocol','grant')
            if event=='grant':near(row.get('phase_limit_tokens',LIMITS[phase]['tokens']),LIMITS[phase]['tokens'],f'{gid}: token threshold differs','grant')
        elif event in ('reserve','solver_reserve'):
            cid=row['call_id'];gid=row['grant_id'];phase=row['phase'];g=grants.get(gid)
            check(cid not in reserves and cid not in finishes,f'Duplicate reservation ID {cid}','ledger_unique')
            check(g is not None,f'{cid}: no preceding grant','grant')
            if not g:continue
            check(g['event']==('grant' if event=='reserve' else 'solver_grant') and g['phase']==phase and row['run_id'].startswith(g['run_prefix']),f'{cid}: grant resource/scope mismatch','grant')
            if event=='reserve':
                total=phaseusage[phase]['input_tokens']+phaseusage[phase]['output_tokens']
                before={'phase_limit_tokens':g.get('phase_limit_tokens',LIMITS[phase]['tokens']),
                        'reported_tokens_before':total,'unknown_completed_before':len(unknown[phase]),'pending_before':len(pending[phase])}
                check(phasecalls[phase]<g['phase_limit'] and grantcalls[gid]<g['max_calls'],f'{cid}: model count admission exceeded','model_admission')
                check(total<before['phase_limit_tokens'] and len(unknown[phase])<LIMITS[phase]['unknown'],f'{cid}: token/unknown threshold admission exceeded','model_admission')
                if 'token_admission' in row:check(row['token_admission']==before,f'{cid}: stored admission snapshot mismatch','model_admission')
                else:missing_admission.append({'line':line,'call_id':cid,'phase':phase})
                admissions.append({'line':line,'call_id':cid,'phase':phase,'grant_id':gid,'phase_calls_before':phasecalls[phase],
                                   'grant_calls_before':grantcalls[gid],**before,'snapshot_present':'token_admission' in row})
                phasecalls[phase]+=1;grantcalls[gid]+=1;pending[phase].add(cid)
            else:
                amount=row['requested_seconds'];check(numeric(amount) and 0<amount<=3600,f'{cid}: invalid solver reservation','solver_admission')
                check(phasesolver[phase]+amount<=g['phase_limit']+1e-9 and grantsolver[gid]+amount<=g['max_seconds']+1e-9,f'{cid}: solver admission exceeded','solver_admission')
                solver_admissions.append({'line':line,'call_id':cid,'phase':phase,'grant_id':gid,'requested_seconds':amount,
                    'phase_reserved_before':phasesolver[phase],'grant_reserved_before':grantsolver[gid]})
                phasesolver[phase]+=amount;grantsolver[gid]+=amount
            reserves[cid]={**row,'ledger_line':line}
        elif event=='finish':
            cid=row['call_id'];check(cid in reserves,f'{cid}: finish without preceding reserve','ledger_unique');check(cid not in finishes,f'{cid}: duplicate finish','ledger_unique')
            finishes[cid]=row
            if cid in reserves and reserves[cid]['event']=='reserve':
                phase=reserves[cid]['phase'];pending[phase].discard(cid);usage=row.get('details',{}).get('usage') or {}
                for key in TOKENS:
                    if known(usage.get(key)):phaseusage[phase][key]+=usage[key]
                if not all(known(usage.get(k)) for k in ('input_tokens','output_tokens')):unknown[phase].append(cid)
        else:check(False,f'Unexpected ledger event {event}','ledger_structure')
    check(set(reserves)==set(finishes),'Ledger has pending or orphan finishes','ledger_unique')
    if missing_admission:warnings.append(f'{len(missing_admission)} legacy development model reserves omit token_admission; reconstructed checks pass/fail independently below, original records unchanged.')
    # Read pinned budgets/protocols without importing runtime code or re-running audits.
    original=[];freezes={};frozen_budget_hashes=set()
    for name in FREEZES:
        f=loaded(ROOT/f'configs/freezes/{name}.json');freezes[f['phase']]=f
        for relative in ('src/agents/budget.py','docs/PROTOCOL_STATIC_v1.md','docs/PROTOCOL_SMT_v1.md'):
            if relative in f['files']:
                check(sha(ROOT/relative)==f['files'][relative],f'{name}: frozen budget/protocol file changed: {relative}','frozen_budget')
                sources[relative]=sha(ROOT/relative)
        for target,arm,repeat in f['matrix']:
            run_id=f'smt{target}_{arm}_r{repeat}' if f.get('dataset')=='smt2020' else f'{target}_{arm}_r{repeat}'
            p=ROOT/'runs'/f['phase']/run_id
            r=loaded(p/'result.json');original.append((p,r));cfg=loaded(p/'config.json')
            snapshot=p/'source_snapshot/src/agents/budget.py'
            check(sha(snapshot)==f['files']['src/agents/budget.py']==r['source_sha256']['src/agents/budget.py'],f'{run_id}: budget implementation snapshot not frozen','frozen_budget')
            frozen_budget_hashes.add(sha(snapshot))
    check(len(original)==180,'Original matrix not exactly 180 records','coverage')
    recovery_freeze=loaded(ROOT/'progress/freezes/static-channel-recovery-v1.json')
    manifest_path=ROOT/recovery_freeze['manifest_path'];manifest=loaded(manifest_path)
    check(sha(manifest_path)==recovery_freeze['files'][recovery_freeze['manifest_path']],'Recovery manifest hash differs from freeze','recovery')
    for relative in ('docs/PROTOCOL_STATIC_CHANNEL_RECOVERY_v1.md','src/agents/budget.py'):
        check(sha(ROOT/relative)==recovery_freeze['files'][relative],'Recovery frozen budget/protocol changed: '+relative,'frozen_budget')
        sources[relative]=sha(ROOT/relative)
    recovery_limits={'phase':'formal','model_attempts':300,'reported_tokens':3000000,'solver_requested_seconds':4500,
                     'campaign_activity_seconds':14400,'logical_model_attempts':3,'logical_activity_seconds':1000,
                     'extra_attempts_per_cell':1,'request_timeout_seconds':300,'unknown_completed_limit':3}
    check(manifest['budgets']==recovery_limits,'Recovery manifest changed shared limits or logical resource rules','recovery')
    for relative,expected in manifest['original_results_sha256'].items():check(sha(ROOT/relative)==expected,'Original result changed: '+relative,'recovery')
    for link in manifest['original_freezes']:check(sha(ROOT/link['path'])==link['sha256'],'Original freeze changed: '+link['path'],'recovery')
    recovery=[(p.parent,loaded(p)) for p in sorted((ROOT/'runs'/manifest['recovery_phase']).glob('*/result.json'))]
    check(len(recovery)==len(manifest['eligible'])==1,'Recovery inventory/eligibility differs','recovery')
    all_runs=original+recovery
    expected_paths={p.resolve() for p,r in all_runs}
    actual_paths={p.parent.resolve() for folder in (ROOT/'runs').iterdir() if folder.is_dir() and folder.name!='development' for p in folder.glob('*/result.json')}
    check(actual_paths==expected_paths,'Nondevelopment run inventory differs from original+recovery','coverage')
    # Saved proof gates are read, not rerun.
    proof_sources=[]
    for phase in freezes:
        name='smt_report_evidence_audit.json' if 'smt' in phase else 'report_evidence_audit.json'
        p=ROOT/'artifacts'/phase/name;a=loaded(p);proof_sources.append(str(p.relative_to(ROOT)))
        reports=a.get('runs',[])+a.get('auxiliary_runs',[])
        check(a.get('coverage_complete') is True and not a.get('phase_errors'),'Saved audit incomplete: '+phase,'saved_audit')
        check(all(x.get('audit_pass') is True and x.get('provenance_complete') is True for x in reports),'Saved evidence/provenance audit failed: '+phase,'saved_audit')
        planned=[r for p,r in original if r['phase']==phase]
        check({x['run_id'] for x in reports}=={r['run_id'] for r in planned},'Saved audit run coverage differs: '+phase,'saved_audit')
        check(stamp(a['at'])>=max(stamp(r['finished_at']) for r in planned),'Saved audit predates completed phase: '+phase,'saved_audit')
    recovery_audit=loaded(ROOT/'artifacts/static_recovery/audit.json')
    check(recovery_audit.get('acceptance_ready') is True and not recovery_audit.get('unexpected_recovery_directories'),
          'Saved recovery audit incomplete or unexpected directories','saved_audit')
    check({x['run_id'] for x in recovery_audit['recovery_records']}=={r['run_id'] for p,r in recovery}
          and all(x.get('audit_pass') is True and x.get('valid') is True for x in recovery_audit['recovery_records']),
          'Saved recovery evidence audit does not cover successful supplemental record','saved_audit')
    recovery_grant=grants[manifest['grant_id']]
    check(recovery_grant['max_calls']==len(manifest['eligible']) and stamp(recovery_grant['at'])>=stamp(manifest['registered_at']),
          'Recovery grant does not follow registered eligible-count allocation','recovery')
    # Independent cost link for EVERY ledger model request, including development probes.
    model_rows=[]
    for cid,reserve in reserves.items():
        if reserve['event']!='reserve':continue
        finish=finishes[cid];directory=Path(reserve['run_id']);m=loaded(directory/'result.json');request=loaded(directory/'request.json')
        check(m['call_id']==request['call_id']==cid,f'{cid}: request/result ID differs','model_link')
        check(m['config']['phase']==reserve['phase'] and m['config']['grant_id']==reserve['grant_id'],f'{cid}: call config grant/phase differs','model_link')
        check(Path(finish['details']['result_path']).resolve()==(directory/'result.json').resolve(),f'{cid}: finish result path differs','model_link')
        check(m['status']==finish['status'] and m['usage']==finish['details'].get('usage'),f'{cid}: status/usage differs from finish','model_link')
        near(m['duration_seconds'],finish['details']['duration_seconds'],f'{cid}: duration differs from finish')
        near((stamp(m['finished_at'])-stamp(m['started_at'])).total_seconds(),m['duration_seconds'],
             f'{cid}: model timestamps/duration differ','model_time',1.)
        check(stamp(reserve['at'])<=stamp(m['started_at'])<=stamp(m['finished_at'])<=stamp(finish['at']),
              f'{cid}: model reserve/finish timestamp ordering differs','model_time')
        usages=[]
        events_path=directory/'events.jsonl';sources[str(events_path.relative_to(ROOT))]=sha(events_path)
        for line in events_path.read_text().splitlines():
            try:event=json.loads(line)
            except ValueError:check(False,f'{cid}: malformed raw model event','raw_usage');continue
            if event.get('type')=='turn.completed' and isinstance(event.get('usage'),dict):usages.append(event['usage'])
        recomputed={key:sum(u[key] for u in usages) if usages and all(numeric(u.get(key)) for u in usages) else None for key in TOKENS}
        check(recomputed==m['usage'],f'{cid}: usage differs from raw turn.completed','raw_usage')
        check(m.get('cost_usd') is None and finish['details'].get('cost_usd') is None,f'{cid}: undocumented monetary cost','unknown_cost')
        if reserve['phase']=='formal':check('token_admission' in reserve,f'{cid}: formal missing admission snapshot','model_admission')
        model_rows.append({'call_id':cid,'phase':reserve['phase'],'path':str(directory.relative_to(ROOT)),
                           'status':m['status'],'duration_seconds':m['duration_seconds'],'timeout_seconds':m['config']['timeout_seconds'],
                           'timeout_cleanup_excess_seconds':max(0,m['duration_seconds']-m['config']['timeout_seconds']),
                           'usage':recomputed,'cost_usd':None})
    model_by_id={r['call_id']:r for r in model_rows}
    run_rows=[];assigned=set();legacy_count_fields=[]
    for path,r in all_runs:
        key=str(path.relative_to(ROOT));cost=r['costs'];is_recovery=r.get('posthoc_reliability_recovery') is True
        linked=[x for x in reserves.values() if x['phase']=='formal' and Path(x['run_id']).resolve().is_relative_to(path.resolve())]
        models=[x for x in linked if x['event']=='reserve'];solvers=[x for x in linked if x['event']=='solver_reserve']
        for x in linked:check(x['call_id'] not in assigned,f'Duplicate run assignment {x["call_id"]}','run_link');assigned.add(x['call_id'])
        check(cost.get('model_calls')==len(models),key+': model count mismatch','run_cost')
        model_records=[read(Path(x['run_id'])/'result.json') for x in models]
        if models:
            root_models=[r['model_result']] if is_recovery else r.get('model_results',[])
            check(root_models==model_records,key+': embedded model records differ','run_link')
        elif r.get('arm') in ('A','F'):check(not r.get('model_results'),key+': nonmodel arm includes model result','run_link')
        model_seconds=sum(model_by_id[x['call_id']]['duration_seconds'] for x in models)
        near(cost.get('model_elapsed_seconds',cost.get('model_seconds',0)),model_seconds,key+': aggregate model duration differs','run_cost')
        usage=cost.get('usage',cost)
        for token in TOKENS:
            vals=[model_by_id[x['call_id']]['usage'].get(token) for x in models]
            total=sum(vals) if all(known(v) for v in vals) else None
            if token in usage:check(usage[token]==total,key+': aggregate '+token+' differs','run_cost')
        requested=sum(x['requested_seconds'] for x in solvers)
        near(cost.get('solver_budget_seconds'),requested,key+': solver reservation total differs','run_cost')
        if 'solver_calls' in cost:check(cost['solver_calls']==len(solvers),key+': solver call count differs','run_cost')
        else:legacy_count_fields.append(key)
        if r['family']=='smt2020':entries=[{'id':s['solver_call_id'],'result':s,'requested':s['parameters']['time_limit']} for s in r.get('solver_results',[])]
        elif r['arm']=='C':entries=[{'id':s['solver_call_id'],'result':s['result'],'requested':s['requested_seconds']} for s in r.get('solver_results',[])]
        elif r['arm']=='A':entries=[{'id':solvers[0]['call_id'],'result':loaded(path/'solver.json'),'requested':read(path/'config.json')['solver_budget_seconds']}] if len(solvers)==1 else []
        elif r['arm']=='F':entries=[{'id':s['call_id'],'result':v['result'],'requested':read(path/'config.json')['solver_budget_seconds']/3} for s,v in zip(solvers,loaded(path/'fixed_portfolio.json'))]
        else:entries=[]
        check({e['id'] for e in entries}=={s['call_id'] for s in solvers},key+': solver ID inventory mismatch','solver_link')
        for e in entries:
            sr=reserves[e['id']];details=finishes[e['id']]['details'];result=e['result']
            near(e['requested'],sr['requested_seconds'],key+': solver requested seconds mismatch','solver_link')
            if 'wall_seconds' in details:near(result.get('wall_seconds'),details['wall_seconds'],key+': solver wall finish mismatch','solver_link')
            if 'solver_seconds' in details:near(result.get('solver_seconds'),details['solver_seconds'],key+': solver internal finish mismatch','solver_link')
        wall=sum(e['result']['wall_seconds'] for e in entries)
        near(cost.get('solver_wall_seconds'),wall,key+': solver wall total mismatch','run_cost')
        e2e=cost['end_to_end_seconds'];check(numeric(e2e) and e2e>=0,key+': invalid activity duration','run_cost')
        near((stamp(r['finished_at'])-stamp(r['started_at'])).total_seconds(),e2e,key+': timestamp/activity duration mismatch','run_time',1.)
        check(model_seconds+wall<=e2e+1,key+': component durations exceed activity','run_time')
        check(cost.get('cost_usd') is None,key+': undocumented dollar value','unknown_cost')
        if not is_recovery:
            cfg=read(path/'config.json');limit=cfg.get('max_model_calls',0);limit=limit.get(r['arm'],0) if isinstance(limit,dict) else limit
            if r['arm'] in ('B','C'):check(len(models)<=limit,key+': per-run model limit exceeded','run_budget')
            check(requested<=cfg['solver_budget_seconds']+1e-9,key+': per-run solver budget exceeded','run_budget')
            for call in model_records:check(call['config']['timeout_seconds']<=cfg['model']['timeout_seconds'],key+': request timeout raised','run_budget')
        else:
            check(len(models)==1 and len(solvers)==0,key+': recovery may issue one model and no solver','recovery')
            check(sha(path/'source_snapshot/src/agents/budget.py')==recovery_freeze['files']['src/agents/budget.py'],
                  'Recovery budget source snapshot differs','frozen_budget')
            original_record=read(ROOT/'runs'/r['original_phase']/r['original_run_id']/'result.json')
            near(r['logical_costs']['activity_seconds'],original_record['costs']['end_to_end_seconds']+e2e,'Recovery logical activity sum mismatch','recovery')
            check(r['logical_costs']['model_calls']==original_record['costs']['model_calls']+len(models)<=manifest['budgets']['logical_model_attempts'],'Recovery logical model budget exceeded','recovery')
            check(r['logical_costs']['activity_seconds']<=manifest['budgets']['logical_activity_seconds'],'Recovery logical activity budget exceeded','recovery')
            check(all(v is None for v in r['logical_costs']['usage'].values()),'Recovery combined unknown original tokens erased','recovery')
        run_rows.append({'phase':r['phase'],'run_id':r['run_id'],'path':key,'arm':r['arm'],'status':r['status'],
            'supplementary_recovery':is_recovery,'started_at':r['started_at'],'finished_at':r['finished_at'],
            'model_calls':len(models),'model_seconds':model_seconds,'solver_calls_reconstructed':len(solvers),
            'solver_requested_seconds':requested,'solver_wall_seconds':wall,'end_to_end_seconds':e2e,
            'cost_usd':None,'ledger_call_ids':[x['call_id'] for x in linked]})
    formal_ids={cid for cid,x in reserves.items() if x['phase']=='formal'}
    check(assigned==formal_ids,'Formal ledger requests not bijective with 181 run directories','run_link')
    # Reconstruct campaign admission from completed records before each start.
    cumulative=0.;admission_runs=[];last_finish=None
    for r in sorted(run_rows,key=lambda x:x['started_at']):
        check(last_finish is None or stamp(r['started_at'])>=last_finish,f'{r["run_id"]}: formal activity overlaps previous run','serial_run')
        check(cumulative<LIMITS['formal']['activity_seconds'],f'{r["run_id"]}: cumulative activity threshold reached before admission','run_budget')
        admission_runs.append({'run_id':r['run_id'],'phase':r['phase'],'prior_activity_seconds':cumulative})
        if r['supplementary_recovery']:
            result=read(ROOT/r['path']/'result.json');a=result['admission'];near(a['campaign_activity_seconds'],cumulative,'Recovery recorded prior campaign activity mismatch','recovery')
            check(cumulative+325<=14400 and a['logical_activity_seconds']+325<=1000,'Recovery lacks reserved 325-second margin','recovery')
            formal_prior=[x for x in admissions if x['phase']=='formal' and x['call_id']!=result['model_result']['call_id']]
            check(a['ledger']['model_attempts']==len(formal_prior),'Recovery prior model count mismatch','recovery')
            admission=next(x for x in admissions if x['call_id']==result['model_result']['call_id'])
            check(a['ledger']['reported_tokens']==admission['reported_tokens_before'] and a['ledger']['unknown_completed']==admission['unknown_completed_before'] and not a['ledger']['pending'],'Recovery token/unknown/pending state differs','recovery')
            near(a['ledger']['solver_requested_seconds'],phasesolver['formal'],'Recovery prior solver reservations differ','recovery')
        cumulative+=r['end_to_end_seconds'];last_finish=stamp(r['finished_at'])
    grant_summary=[{**g,'used_model_calls':grantcalls[gid] if g['event']=='grant' else None,
                    'reserved_solver_seconds':grantsolver[gid] if g['event']=='solver_grant' else None} for gid,g in grants.items()]
    def aggregate(rs):
        return {'runs':len(rs),'status_counts':dict(collections.Counter(r['status'] for r in rs)),
                **{k:sum(r[k] for r in rs) for k in ('model_calls','model_seconds','solver_calls_reconstructed','solver_requested_seconds','solver_wall_seconds','end_to_end_seconds')},
                'cost_usd':None,'unknown_monetary_run_count':len(rs)}
    phases={phase:{'model_calls':phasecalls[phase],'known_usage':dict(phaseusage[phase]),
        'known_input_plus_output_tokens':phaseusage[phase]['input_tokens']+phaseusage[phase]['output_tokens'],
        'unknown_completed_calls':unknown[phase],'pending_model_calls':sorted(pending[phase]),
        'solver_reservations':sum(x['event']=='solver_reserve' and x['phase']==phase for x in reserves.values()),
        'solver_requested_seconds':phasesolver[phase],'limits':LIMITS[phase]} for phase in LIMITS}
    if legacy_count_fields:warnings.append(f'{len(legacy_count_fields)} original static A/F records omit solver_calls; count reconstructed from the uniquely linked ledger and solver artifacts, original results unchanged.')
    # Development review reservations may have no top-level experiment run and are not formal costs.
    development_resources=[{'call_id':cid,'resource':x['event'],'run_id':x['run_id'],'grant_id':x['grant_id'],
                            'requested_seconds':x.get('requested_seconds'),'finish':finishes[cid]} for cid,x in reserves.items() if x['phase']=='development']
    limitations=['No new full trace, feasibility, Git, or model-isolation replay: saved independent audits are read and hash-recorded.',
        'The ledger counts outer CLI requests, not unobservable service-side HTTP requests/retries; collaboration-agent costs are unavailable.',
        'Input/output totals are known reported partial sums; missing usage is not zero. Cached input and reasoning output are subsets, not added again.',
        'Token admission is an observed-completed-usage threshold, not a hard server-side token cap; one in-flight request can overshoot.',
        'Solver reserved seconds, internal solve seconds, solver wall seconds, and run activity seconds are different quantities.',
        'Campaign wall budget is the sum of active run end-to-end durations, including original failed attempts and recovery, excluding idle waiting gaps and offline review.',
        'Early development calls lack stored token-admission snapshots; their historical prefix is reconstructed, not a claim that later code existed then.',
        'Ledger hash and event ordering certify the inspected snapshot internally; they are not an external signed billing/time-attestation service.',
        'Development ledger resources include independent solver review; earlier unledgered non-model SMT pilots/test CPU remain in artifacts/smt_development usage records, not this formal-request ledger.']
    result={'schema_version':'independent-budget-review-1','at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'valid':not errors,'errors':errors,'warnings':warnings,'checks_by_category':dict(checks),'ledger_lines':len(ledger),
        'unique_reservations':len(reserves),'unique_finishes':len(finishes),'grants':grant_summary,
        'phase_totals':phases,'original_180':aggregate([r for r in run_rows if not r['supplementary_recovery']]),
        'supplementary_recovery':aggregate([r for r in run_rows if r['supplementary_recovery']]),'formal_total':aggregate(run_rows),
        'by_formal_phase':{phase:aggregate([r for r in run_rows if r['phase']==phase]) for phase in sorted({r['phase'] for r in run_rows})},
        'formal_model_max_cleanup_excess_seconds':max(x['timeout_cleanup_excess_seconds'] for x in model_rows if x['phase']=='formal'),
        'formal_remaining_observed_budgets':{'model_calls':300-phasecalls['formal'],
            'known_token_threshold_margin':3000000-phases['formal']['known_input_plus_output_tokens'],
            'unknown_completed_before_stop':3-len(unknown['formal']),
            'solver_reserved_seconds':4500-phasesolver['formal'],'activity_seconds':14400-cumulative},
        'model_admissions':admissions,'solver_admissions':solver_admissions,'run_admissions':admission_runs,
        'runs':run_rows,'model_calls':model_rows,'development_resources':development_resources,
        'legacy_missing_token_admission':missing_admission,'legacy_missing_solver_call_count':legacy_count_fields,
        'saved_proof_sources':proof_sources+['artifacts/static_recovery/audit.json'],
        'recovery_saved_audit_summary':{k:v for k,v in recovery_audit.items() if k not in ('originals','original_rows','original_results_sha256')},
        'frozen_budget_code_sha256':sorted(frozen_budget_hashes),'source_sha256':sources,'limitations':limitations,
        'audit_cpu_seconds':time.process_time()-begun,'new_model_calls':0,'new_solver_calls':0,'new_simulations':0}
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    formal=phases['formal'];dev=phases['development'];f=result['formal_total'];o=result['original_180'];rec=result['supplementary_recovery']
    lines=['# 最终独立预算与成本审计','',f'结论：{"通过本次预算与成本核对" if not errors else "存在待处理差异"}。不代替主 Agent 的最终交付签署。',
        '',f'独立按账本事件顺序重建 {len(ledger)} 行，{len(reserves)} 个唯一 reservation 与 {len(finishes)} 个 finish；错误 {len(errors)} 项。审计脚本不导入运行器、BudgetLedger 或求解器，不发起模型/solver/仿真，不重跑全轨迹。',
        '', '| 范围 | 运行数 | 模型外层请求 | solver 预留秒 | 活动执行墙秒 |', '|---|---:|---:|---:|---:|',
        f'| 原正式矩阵（含原失败） | {o["runs"]} | {o["model_calls"]} | {o["solver_requested_seconds"]:.6f} | {o["end_to_end_seconds"]:.6f} |',
        f'| 独立恢复补充 | {rec["runs"]} | {rec["model_calls"]} | {rec["solver_requested_seconds"]:.6f} | {rec["end_to_end_seconds"]:.6f} |',
        f'| 正式合计 | {f["runs"]} | {f["model_calls"]} | {f["solver_requested_seconds"]:.6f} | {f["end_to_end_seconds"]:.6f} |',
        '',f'正式已知 input+output 为 {formal["known_input_plus_output_tokens"]:,} token；未知用量完成请求 {len(formal["unknown_completed_calls"])} 个，真实总 token 仍未知，不能称为精确总量。缓存输入、reasoning 输出不重复累加。费用字段全部 null，不把未知账单计为 $0。',
        '',f'开发账本独立记录：{dev["model_calls"]} 个模型请求、已知 input+output {dev["known_input_plus_output_tokens"]:,}、未知完成请求 {len(dev["unknown_completed_calls"])} 个、solver 预留 {dev["solver_requested_seconds"]:.6f} 秒。开发资源不混入正式 181 条成本；独立审查 solver 的开发 reservation 也保留。',
        '', '## 核对方式', '',
        '逐行检查 grant 先于请求、ID 唯一、finish 唯一、phase/prefix/resource 相符；用此前已完成 usage 重新计算每个模型请求准入时的调用数、input+output 阈值、未知用量计数及 pending；与每份 token_admission 比对。每次 solver 预留检查单 grant 与共享 phase 的累计上限，失败不退还预算。',
        '', '正式 300 请求、300 万已报告 token、未知完成 3 次停止、4500 solver 预留秒和14400累计活动墙秒按冻结协议核查；授予各子预算的 max_calls 可以相加超过全局上限，但每个请求仍必须通过同一全局准入。恢复未重置账本或预算。',
        '', '模型逐次比对 request/result、原始 turn.completed usage、ledger finish、运行聚合；solver 逐次比对 reservation、finish 和已保存候选。A/F 计数从账本与 solver.json/fixed_portfolio.json重建，内部solver秒与含建模wall秒分别核查，未混作同一指标。181条根记录与全部formal账本请求双向关联，无遗漏或重复归属。',
        '', '按 started_at 排序重建每条运行准入前已完成活动耗时并核查串行；原通道失败仍在原180条，恢复只额外增加自身活动时间。logical_costs用于关联检查，不再次计入正式总和；恢复同时核查325秒准入余量、逻辑请求≤3、逻辑活动≤1000秒。',
        '', '## 边界及保留缺口', '']
    lines += ['- '+w for w in warnings]+['- '+x for x in limitations]
    if errors:lines+=['','## 差异','']+['- '+e['message'] for e in errors]
    lines += ['', '## 复现与证据', '',
        '运行 `.venv/bin/python scripts/final_budget_review.py`，只覆盖本审计的 JSON/Markdown 产物。',
        '', '详细逐请求/逐运行准入、每项检查、输入哈希、未知 call ID 和全部成本见 `artifacts/final/qa/budget_audit.json`。核心原始证据为 `progress/model_ledger.jsonl`、四份 `configs/freezes/*.json`、恢复冻结与manifest、各原始run/model/solver文件及已保存离线audit。',
        '', f'本次离线核对 CPU {result["audit_cpu_seconds"]:.6f} 秒，新增模型/solver/仿真均为0。']
    DOC.write_text('\n'.join(lines)+'\n')
    print(json.dumps({'valid':result['valid'],'error_count':len(errors),'errors_first_10':errors[:10],'phase_totals':phases,'formal_total':f,'cpu_seconds':result['audit_cpu_seconds']},ensure_ascii=False))
    return 0 if not errors else 1


if __name__=='__main__':raise SystemExit(main())
