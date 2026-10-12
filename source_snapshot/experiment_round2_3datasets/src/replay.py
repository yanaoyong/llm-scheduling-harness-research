"""Read-only evidence replay: no model calls, solver calls, or result-file repairs."""
from __future__ import annotations
import argparse
import datetime as dt
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import subprocess
from src.experiment import ROOT, read_json, write_json, object_digest, now
from src.fjsp.validator import validate
from src.agents.static import decode_order, observed_problem, compact_problem
from src.agents.model_transport import read_events, summarize_events

TOKEN_KEYS=('input_tokens','cached_input_tokens','output_tokens','cache_write_input_tokens','reasoning_output_tokens')

def _sha(data): return hashlib.sha256(data).hexdigest()
def _safe_relative(relative): return not Path(relative).is_absolute() and '..' not in Path(relative).parts

@lru_cache(maxsize=4096)
def _git(root,*args):
    proc=subprocess.run(['git',*args],cwd=root,capture_output=True)
    if proc.returncode: raise ValueError('git evidence unavailable: '+' '.join(args))
    return proc.stdout

def _equal(a,b,tolerance=1e-6):
    if a is None or b is None: return a is b
    return type(a) in (int,float) and type(b) in (int,float) and math.isfinite(a) and math.isfinite(b) and abs(a-b)<=tolerance

def _sum(values):
    values=list(values)
    return None if any(v is None for v in values) else sum(values)

def _load_freeze(phase=None,tag=None,name=None):
    paths=[ROOT/'configs/freezes'/f'{name}.json'] if name else sorted((ROOT/'configs/freezes').glob('*.json'))
    found=[]
    for path in paths:
        data=read_json(path)
        if (phase is None or data.get('phase')==phase) and (tag is None or data.get('tag')==tag): found.append(data)
    if len(found)!=1: raise ValueError('No unique freeze for phase/tag; pass --freeze when necessary')
    return found[0]

def _provenance(path,r,cfg,p,errors,warnings):
    commit=r.get('code_commit');complete=True;initial_errors=len(errors)
    try:
        if not isinstance(commit,str) or len(commit)!=40 or any(c not in '0123456789abcdef' for c in commit): raise ValueError('Invalid commit identity')
        if _git(str(ROOT),'cat-file','-t',commit).decode().strip()!='commit': raise ValueError('Recorded object is not a commit')
    except (ValueError,OSError) as exc:
        errors.append('code_commit does not resolve to a real commit: '+str(exc));complete=False
    hashes=r.get('source_sha256',{});snapshot=path/'source_snapshot'
    if not hashes or not snapshot.exists():
        complete=False
        message='source snapshot missing: recorded development hashes alone cannot restore dirty source'
        (warnings if r.get('phase')=='development' else errors).append(message)
    else:
        for relative,expected in hashes.items():
            if not _safe_relative(relative): errors.append('unsafe source snapshot path');complete=False;continue
            saved=snapshot/relative
            if not saved.is_file() or _sha(saved.read_bytes())!=expected: errors.append('source snapshot hash mismatch: '+relative);complete=False
    if r.get('phase')!='development':
        try:
            frozen=read_json(path/'freeze.json')
            if _sha((path/'freeze.json').read_bytes())!=r.get('freeze_manifest_sha256'):
                errors.append('saved freeze manifest hash mismatch')
            if frozen.get('phase')!=r['phase'] or frozen.get('tag')!=r.get('freeze_tag'):
                errors.append('saved freeze phase/tag mismatch')
            tag_commit=_git(str(ROOT),'rev-parse',frozen['tag']+'^{commit}').decode().strip()
            if tag_commit!=commit or frozen['code_commit']!=commit: errors.append('formal freeze tag/commit mismatch')
            if r['protocol_version']!=frozen['protocol_version']: errors.append('formal protocol mismatch')
            key=[r['instance_id'],r['arm'],r['repeat']]
            if key not in frozen['matrix'] or r['run_id']!=f'{key[0]}_{key[1]}_r{key[2]}': errors.append('formal run outside frozen matrix')
            if r['config_sha256']!=frozen['effective_config_sha256'][str(r['repeat'])]: errors.append('formal effective config hash mismatch')
            for relative,expected in frozen['files'].items():
                if not _safe_relative(relative): errors.append('unsafe frozen path');continue
                blob=_git(str(ROOT),'show',commit+':'+relative)
                if _sha(blob)!=expected: errors.append('freeze manifest differs from committed file: '+relative)
                if relative in hashes and hashes[relative]!=expected: errors.append('run source differs from freeze: '+relative)
            for relative in hashes:
                if relative not in frozen['files']: errors.append('run source omitted from freeze manifest: '+relative)
            data_rel='data/fjsp/instances/'+r['instance_id']+'.json'
            if data_rel not in frozen['files'] or object_digest(json.loads(_git(str(ROOT),'show',commit+':'+data_rel)))!=object_digest(p): errors.append('run input differs from frozen data')
            config_rel=frozen['config_path']
            if config_rel not in frozen['files']: errors.append('runtime config omitted from freeze')
            else:
                base=json.loads(_git(str(ROOT),'show',commit+':'+config_rel))
                base['model']['phase']='formal';base['seed']=[11,22,33][r['repeat']-1]
                if base!=cfg: errors.append('effective config differs from frozen configuration')
        except (ValueError,OSError,KeyError,IndexError,json.JSONDecodeError) as exc:
            errors.append('formal provenance error: '+str(exc));complete=False
    return complete and len(errors)==initial_errors

def _ledger_rows():
    ledger=ROOT/'progress/model_ledger.jsonl'
    return [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()] if ledger.exists() else []

def _audit_models(path,r,p,cfg,errors):
    models=[];outputs=[];usages=[];ledger=_ledger_rows()
    reserved_paths={Path(v['run_id']).resolve() for v in ledger if v.get('event')=='reserve'}
    # A denied budget can leave an exclusive claim before reserve: that is not a CLI attempt.
    model_dirs=sorted(d for d in (path/'agent').glob('model_call_*') if d.is_dir() and
                      ((d/'request.json').exists() or d.resolve() in reserved_paths))
    for directory in model_dirs:
        label=directory.name+': '
        if not (directory/'result.json').exists(): errors.append(label+'model attempt incomplete; cannot assume zero cost');continue
        saved=read_json(directory/'result.json');models.append(saved)
        events,malformed=read_events(directory/'events.jsonl');parsed=summarize_events(events);usages.append(parsed['usage'])
        if malformed: errors.append(label+'malformed raw model events')
        for field in ('usage','native_tool_events','completed_turns','thread_ids'):
            if saved.get(field)!=parsed[field]: errors.append(label+field+' differs from raw events')
        if saved['status']=='success':
            if parsed['native_tool_events'] or parsed['completed_turns']!=1 or saved.get('returncode')!=0: errors.append(label+'successful model result without isolated completed turn')
            messages=[e['item'].get('text') for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='agent_message']
            if not messages: errors.append(label+'missing raw agent message')
            else:
                try:
                    raw=json.loads(messages[-1]);final=json.loads((directory/'final.txt').read_text())
                    if raw!=final or raw!=saved.get('output'): errors.append(label+'raw agent_message/final.txt/model output mismatch')
                except (ValueError,OSError,TypeError) as exc: errors.append(label+'cannot decode raw final message: '+str(exc))
            outputs.append(saved.get('output'))
        request=read_json(directory/'request.json');prompt=(directory/'prompt.txt').read_text();schema=(directory/'schema.json').read_text()
        fingerprint=_sha((prompt+'\n'+schema+'\n'+json.dumps(saved['config'],sort_keys=True)).encode())
        if saved.get('request_fingerprint')!=fingerprint or request.get('request_fingerprint')!=fingerprint: errors.append(label+'request fingerprint mismatch')
        if request.get('config')!=saved['config'] or request.get('call_id')!=saved.get('call_id'): errors.append(label+'request/result identity mismatch')
        for field in ('model','reasoning_effort','phase','grant_id'):
            if field in cfg.get('model',{}) and saved['config'].get(field)!=cfg['model'][field]:
                errors.append(label+'model configuration differs from run '+field)
        if 'timeout_seconds' in cfg.get('model',{}) and saved['config'].get('timeout_seconds',0)>cfg['model']['timeout_seconds']:
            errors.append(label+'model timeout exceeds frozen configuration')
        try:
            block=prompt.split('\nProblem:\n',1)[1].split('\nYour previous invalid decision',1)[0].split('\nRemaining limits:\n',1)[0]
            expected_problem=compact_problem(p) if cfg.get('compact_state') else observed_problem(p)
            if json.loads(block)!=expected_problem: errors.append(label+'prompt contains different problem/state fields')
        except (IndexError,ValueError): errors.append(label+'cannot audit prompt problem allowlist')
        reservations=[v for v in ledger if v.get('event')=='reserve' and v.get('call_id')==saved.get('call_id')]
        finishes=[v for v in ledger if v.get('event')=='finish' and v.get('call_id')==saved.get('call_id')]
        if len(reservations)!=1 or len(finishes)!=1: errors.append(label+'missing/duplicate ledger reserve or finish')
        else:
            reservation,finish=reservations[0],finishes[0]
            if Path(reservation['run_id']).resolve()!=directory.resolve() or reservation['phase']!=saved['config']['phase'] or reservation['grant_id']!=saved['config']['grant_id']: errors.append(label+'ledger reservation identity mismatch')
            detail=finish['details']
            if finish['status']!=saved['status'] or detail.get('usage')!=saved['usage'] or not _equal(detail.get('duration_seconds'),saved['duration_seconds']): errors.append(label+'ledger completion differs from model result')
        if not _equal(saved.get('model_elapsed_seconds'),saved.get('duration_seconds')): errors.append(label+'model elapsed fields disagree')
    costs=r.get('costs',{})
    if len(model_dirs)!=costs.get('model_calls',0): errors.append('model request count differs')
    if r.get('arm') in ('B','C'):
        if models!=r.get('model_results',[]): errors.append('root model_results differ from per-call evidence')
        actions=r.get('actions',[])
        # A completed model message arriving beyond the outer deadline is recorded but not acted on.
        late_unconsumed=(r.get('status')=='timeout' and r.get('failure_type')=='agent_wall_timeout'
                         and len(outputs)==len(actions)+1 and actions==outputs[:-1])
        if outputs!=actions and not late_unconsumed: errors.append('root actions differ from successful raw model outputs')
        if (path/'agent/agent_request.json').exists() and read_json(path/'agent/agent_request.json').get('problem')!=observed_problem(p): errors.append('agent request problem allowlist mismatch')
    totals={k:_sum(u.get(k) for u in usages) for k in TOKEN_KEYS}
    if not models and r.get('arm') in ('B','C'): totals={k:None for k in TOKEN_KEYS}
    reported=costs.get('usage',costs)
    for key in TOKEN_KEYS:
        if key in reported and reported[key]!=totals[key]: errors.append('aggregate '+key+' differs from raw events')
        elif key not in reported and r.get('arm') in ('B','C') and models: errors.append('aggregate '+key+' missing')
    duration=sum(m['duration_seconds'] for m in models)
    if not _equal(costs.get('model_elapsed_seconds',costs.get('model_seconds',0)),duration): errors.append('aggregate model elapsed time differs')
    if len(model_dirs)>cfg.get('max_model_calls',3): errors.append('model call limit exceeded')
    return model_dirs,models,totals

def _audit_solvers(path,r,p,cfg,errors):
    costs=r.get('costs',{})
    if r['arm']=='B':
        if r.get('solver_results') or list((path/'agent').glob('solver_*.json')): errors.append('B contains forbidden solver call')
        if costs.get('solver_calls',0)!=0 or costs.get('solver_budget_seconds',0)!=0: errors.append('B reports solver use')
        return
    if r['arm']=='F':
        if not r.get('auxiliary'): errors.append('F must be explicitly auxiliary')
        candidates=read_json(path/'fixed_portfolio.json')
        searches=('AUTOMATIC_SEARCH','FIXED_SEARCH','PORTFOLIO_SEARCH')
        if len(candidates)!=3: errors.append('fixed portfolio must contain three recorded solves')
        feasible=[];ledger=_ledger_rows()
        reservations=[v for v in ledger if v.get('event')=='solver_reserve' and Path(v['run_id']).resolve()==path.resolve()]
        if len(reservations)!=len(candidates): errors.append('fixed portfolio solver reservation count differs')
        for i,candidate in enumerate(candidates):
            solver=candidate['result'];actual=validate(p,solver.get('schedule'))
            if actual!=candidate['validation']: errors.append('fixed candidate independent validation differs')
            if actual['valid']: feasible.append((actual['makespan'],i))
            expected={'time_limit':cfg['solver_budget_seconds']/3,'seed':cfg['seed']+i,'workers':1,
                      'search_branching':searches[i],'randomize_search':False}
            if solver.get('parameters')!=expected: errors.append('fixed portfolio parameters differ from predefined policy')
            if i<len(reservations):
                reserve=reservations[i]
                finishes=[v for v in ledger if v.get('event')=='finish' and v.get('call_id')==reserve['call_id']]
                if not _equal(reserve['requested_seconds'],expected['time_limit']) or len(finishes)!=1:
                    errors.append('fixed portfolio ledger budget/completion mismatch')
                elif not _equal(finishes[0]['details'].get('solver_seconds'),solver.get('solver_seconds')):
                    errors.append('fixed portfolio ledger elapsed differs')
        selected=min(feasible)[1] if feasible else None
        if selected!=r.get('selected_candidate'): errors.append('fixed portfolio selection differs from predefined minimum')
        if selected is not None and candidates[selected]['result']['schedule']!=r.get('schedule'): errors.append('fixed portfolio selected schedule differs')
        if not _equal(costs.get('solver_seconds'),sum(c['result']['solver_seconds'] for c in candidates)): errors.append('fixed portfolio aggregate solver elapsed differs')
        if not _equal(costs.get('solver_budget_seconds'),cfg['solver_budget_seconds']): errors.append('fixed portfolio aggregate requested budget differs')
        return
    if r['arm'] not in ('A','C'):
        errors.append('unrecognized experiment arm');return
    if r['arm']=='A':
        ledger=_ledger_rows()
        reservations=[v for v in ledger if v.get('event')=='solver_reserve' and Path(v['run_id']).resolve()==path.resolve()]
        if (path/'solver.json').exists():
            solver=read_json(path/'solver.json')
            if solver.get('schedule')!=r.get('schedule'): errors.append('A schedule differs from raw solver result')
            if not _equal(costs.get('solver_seconds'),solver.get('solver_seconds')): errors.append('A solver elapsed differs')
            if not _equal(costs.get('solver_budget_seconds'),cfg['solver_budget_seconds']): errors.append('A requested solver budget differs')
            if len(reservations)!=1: errors.append('A missing/duplicate solver reservation')
            else:
                finishes=[v for v in ledger if v.get('event')=='finish' and v.get('call_id')==reservations[0]['call_id']]
                if len(finishes)!=1 or not _equal(reservations[0]['requested_seconds'],cfg['solver_budget_seconds']):
                    errors.append('A ledger solver budget/completion mismatch')
                elif not _equal(finishes[0]['details'].get('solver_seconds'),solver.get('solver_seconds')):
                    errors.append('A ledger solver elapsed differs')
        elif r['status']=='success': errors.append('successful A missing solver evidence')
        return
    candidates=r.get('solver_results',[]);solve_actions=[a for a in r.get('actions',[]) if isinstance(a,dict) and a.get('action')=='solve'];cursor=0;ledger=_ledger_rows()
    for index,candidate in enumerate(candidates):
        raw=path/'agent'/f'solver_{index+1:03d}.json'
        if raw.exists() and read_json(raw)!=candidate: errors.append('C candidate differs from raw solver file')
        elif not raw.exists() and not candidate['result'].get('exception'): errors.append('C missing raw solver file')
        actual=validate(p,candidate['result'].get('schedule'));recorded=candidate['validation']
        if actual['valid']!=recorded['valid'] or actual['makespan']!=recorded['makespan']: errors.append('C candidate independent validation differs')
        parameters=candidate['parameters'];match=None
        for j in range(cursor,len(solve_actions)):
            selected={k:solve_actions[j].get(k) for k in ('time_limit','seed','search_branching','randomize_search')};selected['workers']=1
            if selected==parameters: match=j;break
        if match is None: errors.append('C solver parameters have no corresponding model decision')
        else: cursor=match+1
        if candidate['result'].get('parameters',parameters)!=parameters: errors.append('C solver executed different parameters')
        if parameters.get('workers')!=1 or not _equal(parameters.get('time_limit'),candidate['requested_seconds']): errors.append('C solver workers/time budget mismatch')
        reservations=[v for v in ledger if v.get('event')=='solver_reserve' and v.get('call_id')==candidate.get('solver_call_id')]
        finishes=[v for v in ledger if v.get('event')=='finish' and v.get('call_id')==candidate.get('solver_call_id')]
        if len(reservations)!=1 or len(finishes)!=1: errors.append('C missing/duplicate solver ledger entries')
        else:
            if not _equal(reservations[0]['requested_seconds'],candidate['requested_seconds']): errors.append('C ledger solver seconds mismatch')
            if Path(reservations[0]['run_id']).resolve()!=(path/'agent').resolve(): errors.append('C solver ledger run identity mismatch')
            if finishes[0]['status']!=('success' if recorded['valid'] else 'failed'): errors.append('C solver ledger status mismatch')
            if not candidate['result'].get('exception') and not _equal(finishes[0]['details'].get('wall_seconds'),candidate['result'].get('wall_seconds')):
                errors.append('C solver ledger elapsed differs')
    requested=sum(c['requested_seconds'] for c in candidates);wall=_sum(c['result'].get('wall_seconds') for c in candidates)
    if requested>cfg['solver_budget_seconds']+1e-8: errors.append('C solver budget exceeded')
    if len(candidates)>cfg.get('max_solver_calls',2): errors.append('C solver call limit exceeded')
    if costs.get('solver_calls')!=len(candidates): errors.append('C solver call count differs')
    if not _equal(costs.get('solver_budget_seconds'),requested): errors.append('C aggregate solver budget differs')
    if not _equal(costs.get('solver_wall_seconds'),wall): errors.append('C aggregate solver elapsed differs')
    if r['status']=='success':
        k=r['selected_candidate'];last=r['actions'][-1]
        if type(k) is not int or not 0<=k<len(candidates): errors.append('C candidate selection outside range')
        elif last.get('action')!='finish' or last.get('candidate_index')!=k or candidates[k]['result']['schedule']!=r['schedule']: errors.append('C missing explicit selection or selected schedule differs')

def replay(path):
    path=Path(path);errors=[];warnings=[]
    result={'run_id':path.name,'status':'unreadable','valid':False,'makespan':None,'provenance_complete':False}
    try:
        r=read_json(path/'result.json');p=read_json(path/'input.json');cfg=read_json(path/'config.json')
        result.update(run_id=r['run_id'],status=r['status'],instance_id=r['instance_id'],arm=r['arm'],repeat=r['repeat'],auxiliary=bool(r.get('auxiliary')) or r['arm']=='F')
        if object_digest(p)!=r['data_sha256']: errors.append('input hash mismatch')
        if object_digest(cfg)!=r['config_sha256']: errors.append('config hash mismatch')
        for key in ('instance_id','arm','repeat','config_sha256','data_sha256'):
            if r.get('identity',{}).get(key)!=r.get(key): errors.append('identity differs from root '+key)
        actual=validate(p,r.get('schedule'));result.update(valid=actual['valid'],makespan=actual['makespan'])
        if actual!=r['validation']: errors.append('independent validation differs')
        if r['status']=='success' and not actual['valid']: errors.append('claimed success without feasible schedule')
        if r['metrics'].get('makespan')!=actual['makespan']: errors.append('makespan mismatch')
        if r['status']!='success' and r['metrics'].get('makespan') is not None: errors.append('failed run has numeric objective')
        if r.get('schedule') is not None:
            if not (path/'schedule.json').exists() or read_json(path/'schedule.json')!=r['schedule']: errors.append('schedule file missing or differs')
        if r['arm']=='B' and r['status']=='success' and decode_order(p,r['actions'][-1]['order'])!=r['schedule']: errors.append('B schedule differs from actual model decision')
        model_dirs,models,totals=_audit_models(path,r,p,cfg,errors);result.update(model_calls=len(model_dirs),recomputed_usage=totals)
        _audit_solvers(path,r,p,cfg,errors)
        result['provenance_complete']=_provenance(path,r,cfg,p,errors,warnings)
        started=read_json(path/'started.json')
        for field in ('identity','code_commit','config_sha256','data_sha256','protocol_version','source_sha256'):
            if started.get(field)!=r.get(field): errors.append('started/root provenance differs: '+field)
        if r.get('phase')!='development' and started.get('freeze_manifest_sha256')!=r.get('freeze_manifest_sha256'):
            errors.append('started/root freeze manifest hash differs')
        wall=(dt.datetime.fromisoformat(r['finished_at'])-dt.datetime.fromisoformat(r['started_at'])).total_seconds()
        if not _equal(wall,r['costs'].get('end_to_end_seconds'),tolerance=1): errors.append('end-to-end elapsed differs from timestamps')
        if sum(m['duration_seconds'] for m in models)>r['costs'].get('end_to_end_seconds',0)+1: errors.append('model elapsed exceeds end-to-end wall time')
    except (OSError,ValueError,KeyError,IndexError,TypeError,AttributeError) as exc:
        errors.append(f'evidence read/structure error: {type(exc).__name__}: {exc}')
    result.update(audit_pass=not errors,errors=errors,warnings=warnings)
    return result

def audit_phase(phase,freeze=None):
    root=ROOT/'runs'/phase
    all_reports=[replay(p.parent) for p in sorted(root.glob('*/result.json'))
             if ((p.parent/'input.json').exists() or (p.parent/'started.json').exists())
             and not ((p.parent/'input_manifest.json').exists() and read_json(p).get('family')=='smt2020')]
    reports=[r for r in all_reports if not r.get('auxiliary')]
    auxiliary=[r for r in all_reports if r.get('auxiliary')]
    incomplete=[{'run_id':p.parent.name,'path':str(p.parent.relative_to(ROOT)),'state':'incomplete','process_state':'unknown; may still be active'} for p in sorted(root.glob('*/started.json')) if not (p.parent/'result.json').exists()]
    errors=[];missing=[];unexpected=[];duplicates=[];expected=None;coverage_reports=reports;coverage_scope='core'
    if phase!='development' or freeze:
        try:
            frozen=_load_freeze(phase=phase,name=freeze);expected=[tuple(item) for item in frozen['matrix']]
            if not expected: errors.append('freeze matrix must not be empty')
            if expected and all(key[1]=='F' for key in expected): coverage_reports=auxiliary;coverage_scope='auxiliary'
            if len(expected)!=len(set(expected)): errors.append('freeze contains duplicate matrix entries')
            actual={}
            for report in coverage_reports:
                key=(report.get('instance_id'),report.get('arm'),report.get('repeat'));actual.setdefault(key,[]).append(report['run_id'])
                saved_freeze=root/report['run_id']/'freeze.json'
                if not saved_freeze.exists() or read_json(saved_freeze)!=frozen:
                    errors.append('run uses different or absent phase freeze: '+report['run_id'])
            for key,ids in actual.items():
                if key not in expected: unexpected.extend(ids)
                if len(ids)>1: duplicates.append({'key':list(key),'run_ids':ids})
            active={item['run_id'] for item in incomplete}
            for key in expected:
                if key not in actual:
                    run_id=f'{key[0]}_{key[1]}_r{key[2]}'
                    missing.append({'instance_id':key[0],'arm':key[1],'repeat':key[2],'run_id':run_id,'state':'incomplete' if run_id in active else 'not_started'})
            if unexpected or duplicates: errors.append('unexpected or duplicate formal matrix records')
        except (OSError,ValueError,KeyError,TypeError) as exc: errors.append('phase freeze unavailable: '+str(exc))
    complete=expected is not None and not missing and not unexpected and not duplicates
    summary={'at':now(),'phase':phase,'records':len(reports),'passed':sum(r['audit_pass'] for r in reports),'feasible':sum(r['valid'] for r in reports),'successes':sum(r['status']=='success' for r in reports),'failures':sum(r['status']!='success' for r in reports),'incomplete':incomplete,'expected_records':len(expected) if expected is not None else None,'missing':missing,'unexpected':unexpected,'duplicates':duplicates,'coverage_complete':complete,'coverage_scope':coverage_scope,'phase_errors':errors,'runs':reports,
             'auxiliary_records':len(auxiliary),'auxiliary_passed':sum(r['audit_pass'] for r in auxiliary),'auxiliary_runs':auxiliary}
    summary['acceptance_ready']=complete and not errors and not incomplete and all(r['audit_pass'] and r['status']=='success' and r['provenance_complete'] for r in coverage_reports)
    return summary

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--phase',default='development');ap.add_argument('--label',default='latest');ap.add_argument('--freeze');a=ap.parse_args()
    summary=audit_phase(a.phase,a.freeze)
    write_json(ROOT/'artifacts'/a.phase/f'replay_{a.label}.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k not in ('runs','auxiliary_runs')},ensure_ascii=False))
    if summary['phase_errors'] or any(not r['audit_pass'] for r in summary['runs']+summary['auxiliary_runs']): raise SystemExit(1)
    if a.phase!='development' and not summary['coverage_complete']: raise SystemExit(2)

if __name__=='__main__': main()
