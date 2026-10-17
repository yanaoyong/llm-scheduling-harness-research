"""Offline SMT controller/model/source/trace audit; never runs an environment or solver."""
from __future__ import annotations
import argparse
import ast
from collections import defaultdict
import datetime as dt
import json
from pathlib import Path
import re
from src.experiment import ROOT,read_json,write_json,object_digest,now
from src.replay import _git,_sha,_equal,TOKEN_KEYS
from src.agents.model_transport import read_events,summarize_events
from src.smt.audit import audit_trace

WEIGHTS=('priority_weight','waiting_weight','fill_weight','setup_weight')
PARAMETERS=('time_limit','seed',*WEIGHTS)
STATE_KEYS={'schema_version','time','horizon','finished','decision_count','machines','current_wip','completed_lots','action_contract'}
CONTRACT='dispatches specify exact machine and lot_ids; compatible part+step batch at min..max; wait_seconds 0..1800; no solver/rule selection for B'

def _same(a,b):
    if type(a) in (float,int) and type(b) in (float,int):return _equal(a,b,1e-6)
    if isinstance(a,dict) and isinstance(b,dict):return set(a)==set(b) and all(_same(a[k],b[k]) for k in a)
    if isinstance(a,list) and isinstance(b,list):return len(a)==len(b) and all(_same(x,y) for x,y in zip(a,b))
    return a==b

def _sum(values):
    values=list(values);return None if any(v is None for v in values) else sum(values)

def _ledger():
    p=ROOT/'progress/model_ledger.jsonl'
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()] if p.exists() else []

def _action_errors(state,action):
    errors=[]
    if not isinstance(action,dict) or set(action)!={'dispatches','wait_seconds'}:return ['action fields']
    wait=action['wait_seconds'];ds=action['dispatches']
    if type(wait) not in (int,float) or not 0<=wait<=1800:errors.append('wait bound')
    if not isinstance(ds,list):return errors+['dispatches type']
    if not ds and wait<=0:errors.append('empty action without wait')
    machines={m['machine']:m for m in state['machines']};used_m=set();used_l=set()
    for d in ds:
        if not isinstance(d,dict) or set(d)!={'machine','lot_ids'}:errors.append('dispatch fields');continue
        mid=d['machine'];ids=d['lot_ids']
        if type(mid) is not int or mid not in machines or mid in used_m:errors.append('machine identity');continue
        m=machines[mid];used_m.add(mid);cs={c['lot']:c for c in m['candidates']}
        if not m['ready_now']:errors.append('machine not ready')
        if not isinstance(ids,list) or not ids or any(type(x) is not str or x not in cs or x in used_l for x in ids):errors.append('lot identity');continue
        if len(ids)!=len(set(ids)):errors.append('duplicate lot')
        first=cs[ids[0]]
        if any(cs[x]['batch_key']!=first['batch_key'] for x in ids):errors.append('batch compatibility')
        if not first['batch_min']<=len(ids)<=first['batch_max']:errors.append('batch capacity')
        used_l.update(ids)
    return errors

def project_states(events,saved_states,errors):
    """Derive model observations using only events preceding each action; no simulator import."""
    manifest=events[0]['manifest'];routes=manifest['routes'];controls=manifest['controlled_machine_ids']
    machines={m['id']:m for m in manifest['machines']}
    ms={m:dict(ready=0,down=0,setup='',min_left=0,min_setup='') for m in machines}
    lots={l['id']:{**l,'status':'unreleased','current_step':l['step']+1,'ready':None,'dedications':{}} for l in manifest['lots']}
    jobs={};setups={(s['old'],s['new']):s['seconds'] for s in manifest['setups']};checked=set()
    def expected(t,decision):
        output=[]
        for mid in sorted(controls):
            m=machines[mid];s=ms[mid];cs=[]
            ready=max(s['ready'],s['down'])<=t
            slots=sum(j['machine']==mid and j['process_end']>t for j in jobs.values())
            if ready and slots<(2 if m['cascading'] else 1):
                for lid,l in sorted(lots.items()):
                    if l['status']!='waiting':continue
                    step=routes[l['route']][l['current_step']-1]
                    if step['family']!=m['family'] or l['dedications'].get(str(step['step']),mid)!=mid:continue
                    if s['min_left']>0 and s['min_setup']!=step['setup']:continue
                    setup=0 if not step['setup'] or s['setup']==step['setup'] else step['setup_time'] if step['setup_time'] is not None else setups.get((s['setup'],step['setup']),setups.get(('',step['setup']),0))
                    spec=step['processing'];mean=spec.get('c',spec.get('m',spec.get('mean')))
                    cs.append({'lot':lid,'part':l['part'],'step':step['step'],'priority':l['priority'],'due':l['due'],
                               'waiting_seconds':t-l['ready'],'batch_key':[l['part'],step['step'],step['name']],
                               'batch_min':step['batch_min'],'batch_max':step['batch_max'],'setup':step['setup'],
                               'setup_seconds':setup,'expected_processing_seconds':mean+m['load']+m['unload']})
            output.append({'machine':mid,'family':m['family'],'ready_now':ready,'current_setup':s['setup'],'min_runs_left':s['min_left'],'candidates':cs})
        return {'schema_version':'smt-state-1','time':t,'horizon':manifest['horizon'],'finished':False,'decision_count':decision,
                'machines':output,'current_wip':sum(l['status'] not in ('done','unreleased') for l in lots.values()),
                'completed_lots':sum(l['status']=='done' for l in lots.values()),'action_contract':CONTRACT}
    for e in events:
        kind=e['kind'];t=e['time']
        if kind=='release':lots[e['lot']]['status']='released'
        elif kind=='ready':lots[e['lot']].update(status='waiting',current_step=e['step'],ready=t)
        elif kind=='skip':lots[e['lot']].update(status='transition',current_step=e['step']+1)
        elif kind=='operation_complete':lots[e['lot']].update(status='transition',current_step=e['step']+1)
        elif kind=='rework':lots[e['lot']].update(current_step=e['target'])
        elif kind=='lot_complete':lots[e['lot']]['status']='done'
        elif kind=='dispatch':
            mid=e['machine'];s=ms[mid];step=routes[lots[e['lots'][0]]['route']][e['steps'][0]-1]
            if e['setup_seconds']>0 and step['setup'] in manifest['min_runs'] and s['min_left']==0:s['min_setup']=step['setup']
            s.update(ready=e['machine_ready'],setup=e['setup_after'],min_left=e['min_runs_left'])
            jobs[e['job']]={'machine':mid,'process_end':e['process_end']}
            for lid in e['lots']:
                lots[lid]['status']='processing'
                if step['dedicate_for'] is not None:lots[lid]['dedications'][str(step['dedicate_for'])]=mid
        elif kind=='downtime':
            ms[e['machine']].update(ready=e['machine_ready'],down=e['blocked_until'],setup='')
            for jid in e['affected_jobs']:jobs[jid]['process_end']+=e['duration']
        elif kind=='action':
            decision=e['decision'];checked.add(decision)
            if decision not in saved_states:errors.append(f'decision {decision}: state file absent')
            elif not _same(saved_states[decision],expected(t,decision)):errors.append(f'decision {decision}: state differs from preceding trace observations')
    # A failed model decision can leave one unexecuted final state. It is still audited.
    for decision,state in saved_states.items():
        if decision not in checked:
            if events[-1]['kind']=='terminal':errors.append('extra state after complete window')
            elif state['time']<events[-1]['time'] or not _same(state,expected(state['time'],decision)):
                errors.append(f'decision {decision}: unexecuted state differs from trace prefix')

def _source_binding(path,r,cfg,manifest,data_dir,errors,warnings):
    if manifest['seed']!=r['scenario']:errors.append('exogenous scenario/manifest seed mismatch')
    if not _equal(manifest['horizon'],cfg['window_seconds']):errors.append('window/horizon mismatch')
    if sorted(manifest['controlled_machine_ids'])!=sorted(cfg['controlled_machine_ids']):errors.append('controlled machine IDs mismatch')
    required={'adapter_version':manifest['version'],'warmup_seconds':manifest.get('warmup_seconds'),'outside_policy':manifest.get('outside_policy')}
    for key,value in required.items():
        if key in r and r[key]!=value:errors.append('root/manifest '+key+' mismatch')
        if key in cfg and cfg[key]!=value:errors.append('configuration/manifest '+key+' mismatch')
        elif key not in cfg:(warnings if r['phase']=='development' else errors).append('configuration does not explicitly freeze '+key)
    for key,value in {'window_seconds':manifest['horizon'],'controlled_machine_ids':manifest['controlled_machine_ids']}.items():
        if key in r and r[key]!=value:errors.append('root/manifest '+key+' mismatch')
    if cfg.get('seed')!=[11,22,33][r['repeat']-1]:errors.append('solver repeat seed differs from frozen repeat mapping')
    if manifest['version']!='smt-adapter-v2':errors.append('unsupported pre-v2 semantics cannot pass this acceptance')
    hashes=manifest['data_hashes']
    if object_digest(hashes)!=r['data_sha256']:errors.append('root data_sha256 differs from manifest data hashes')
    inventory={p.name:_sha(p.read_bytes()) for p in data_dir.iterdir() if p.is_file()}
    if inventory!=hashes:errors.append('source data file inventory/hash mismatch')
    conversion=(json.loads(_git(str(ROOT),'show',r['code_commit']+':data/smt/conversion-manifest.json'))
                if r['phase']!='development' else read_json(ROOT/'data/smt/conversion-manifest.json'))
    expected={Path(row['output']).name:row['output_sha256'] for row in conversion if Path(row['output']).parent==Path('data/smt/SMT2020_LVHM')}
    if expected!=hashes:errors.append('source data is not the complete locked official conversion')
    return {'file_count':len(inventory),'data_directory':str(data_dir),'inventory_matches':inventory==hashes,
            'conversion_matches':expected==hashes,'source_data_sha256':object_digest(hashes)}

def _provenance(path,r,cfg,manifest,errors,warnings):
    before=len(errors);complete=True;commit=r.get('code_commit')
    try:
        if not isinstance(commit,str) or len(commit)!=40 or _git(str(ROOT),'cat-file','-t',commit).decode().strip()!='commit':raise ValueError('not a commit')
    except (ValueError,OSError):errors.append('code commit cannot be resolved');complete=False
    hashes=r.get('source_sha256',{})
    if not hashes or not (path/'source_snapshot').exists():
        (warnings if r['phase']=='development' else errors).append('source snapshot absent; dirty source cannot be restored');complete=False
    for relative,sha in hashes.items():
        if Path(relative).is_absolute() or '..' in Path(relative).parts:errors.append('unsafe snapshot path');continue
        saved=path/'source_snapshot'/relative
        if not (path/'source_snapshot').exists() and r['phase']=='development':continue
        if not saved.exists() or _sha(saved.read_bytes())!=sha:errors.append('source snapshot mismatch: '+relative)
    started=read_json(path/'started.json')
    for key in ('identity','code_commit','source_sha256','config_sha256','data_sha256','protocol_version','adapter_version','window_seconds','controlled_machine_ids','warmup_seconds','outside_policy','config_path'):
        if key not in started:(warnings if r['phase']=='development' else errors).append('started metadata missing '+key);complete=False
        elif started[key]!=r.get(key):errors.append('started/root '+key+' mismatch')
    if r['phase']!='development':
        frozen=read_json(path/'freeze.json')
        if _sha((path/'freeze.json').read_bytes())!=r.get('freeze_manifest_sha256'):errors.append('freeze manifest hash mismatch')
        if frozen['phase']!=r['phase'] or frozen['tag']!=r.get('freeze_tag'):errors.append('freeze phase/tag mismatch')
        if _git(str(ROOT),'rev-parse',frozen['tag']+'^{commit}').decode().strip()!=commit or frozen['code_commit']!=commit:errors.append('freeze tag/commit mismatch')
        if r['run_id']!=f'smt{r["scenario"]}_{r["arm"]}_r{r["repeat"]}' or [r['scenario'],r['arm'],r['repeat']] not in frozen['matrix']:errors.append('run outside frozen SMT matrix')
        if r['protocol_version']!=frozen['protocol_version'] or r['config_sha256']!=frozen['effective_config_sha256'][str(r['repeat'])]:errors.append('protocol/effective configuration differs from freeze')
        if frozen['config_path']!=r.get('config_path'):errors.append('root config path differs from freeze')
        for relative,sha in frozen['files'].items():
            if Path(relative).is_absolute() or '..' in Path(relative).parts:errors.append('unsafe frozen file path');continue
            if _sha(_git(str(ROOT),'show',commit+':'+relative))!=sha:errors.append('frozen Git file hash mismatch: '+relative)
        expected_sources={relative:sha for relative,sha in frozen['files'].items() if Path(relative).parts[0] in ('src','prompts','configs','tests')}
        if hashes!=expected_sources:errors.append('source snapshot inventory differs from frozen code inventory')
        for relative,sha in hashes.items():
            if frozen['files'].get(relative)!=sha:errors.append('source snapshot not represented by freeze: '+relative)
        base=json.loads(_git(str(ROOT),'show',commit+':'+frozen['config_path']));base['model']['phase']='formal';base['seed']=[11,22,33][r['repeat']-1]
        if base!=cfg:errors.append('run config differs from committed frozen configuration')
        expected={'data/smt/SMT2020_LVHM/'+name:sha for name,sha in manifest['data_hashes'].items()}
        if frozen.get('source_data')!=expected:errors.append('frozen source data inventory/hash mismatch')
        for required in ('data/smt/source-manifest.json','data/smt/conversion-manifest.json'):
            if required not in frozen['files']:errors.append('frozen source metadata missing: '+required)
        if started.get('freeze_manifest_sha256')!=r.get('freeze_manifest_sha256'):errors.append('started freeze hash mismatch')
    return complete and len(errors)==before

def _admission(ledger, call_id, errors):
    """Independently check the append-only prefix at admission, including failures."""
    positions=[i for i,x in enumerate(ledger) if x.get('event') in ('reserve','solver_reserve') and x.get('call_id')==call_id]
    if len(positions)!=1:errors.append('nonunique reservation '+str(call_id));return
    i=positions[0];r=ledger[i];prior=ledger[:i];is_model=r['event']=='reserve'
    grants=[x for x in prior if x.get('event')==('grant' if is_model else 'solver_grant') and x.get('grant_id')==r.get('grant_id')]
    if len(grants)!=1:errors.append('missing unique prior grant '+str(call_id));return
    g=grants[0];phase=r['phase'];reserves=[x for x in prior if x.get('event')==r['event']]
    if g['phase']!=phase or not r['run_id'].startswith(g['run_prefix']):errors.append('reservation outside grant scope')
    if is_model:
        if sum(x['phase']==phase for x in reserves)>=g['phase_limit'] or sum(x['grant_id']==g['grant_id'] for x in reserves)>=g['max_calls']:errors.append('model admission exceeds attempt budget')
        finishes={x['call_id']:x for x in prior if x.get('event')=='finish'};tokens=0;unknown=0;pending=0
        for old in reserves:
            if old['phase']!=phase:continue
            finish=finishes.get(old['call_id'])
            if finish is None:pending+=1;continue
            usage=finish.get('details',{}).get('usage') or {};values=[usage.get(k) for k in ('input_tokens','output_tokens')]
            known=[type(v) is int and v>=0 for v in values];tokens+=sum(v for v,ok in zip(values,known) if ok);unknown+=not all(known)
        threshold=g.get('phase_limit_tokens',400000 if phase=='development' else 3000000)
        if tokens>=threshold or unknown>=3:errors.append('model admission after token/unknown threshold')
        recorded=r.get('token_admission')
        expected={'phase_limit_tokens':threshold,'reported_tokens_before':tokens,'unknown_completed_before':unknown,'pending_before':pending}
        if recorded is not None and recorded!=expected:errors.append('token admission prefix totals mismatch')
    else:
        seconds=r['requested_seconds']
        if sum(x['requested_seconds'] for x in reserves if x['phase']==phase)+seconds>g['phase_limit']+1e-6 or sum(x['requested_seconds'] for x in reserves if x['grant_id']==g['grant_id'])+seconds>g['max_seconds']+1e-6:errors.append('solver admission exceeds requested budget')

def _prompt_prefix(path,arm):
    """Read string constants without importing or executing historical controller code."""
    file=path/'source_snapshot/src/smt_control.py'
    if not file.exists():return None
    strings={}
    for node in ast.parse(file.read_text()).body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            value=node.value
            if isinstance(value,ast.Constant) and isinstance(value.value,str):strings[node.targets[0].id]=value.value
            elif isinstance(value,ast.BinOp) and isinstance(value.op,ast.Add) and isinstance(value.left,ast.Name) and value.left.id in strings and isinstance(value.right,ast.Constant) and isinstance(value.right.value,str):strings[node.targets[0].id]=strings[value.left.id]+value.right.value
    return strings.get(arm+'_PROMPT')

def _history(path,r,cfg,decision,attempt,prompt,prior,errors,call_id):
    """Check feedback contains only previous outputs/candidates from this decision."""
    prefix=_prompt_prefix(path,r['arm'])
    if prefix is not None and prompt.split('\nCurrent state:\n',1)[0]!=prefix:errors.append('prompt differs from snapshot instruction')
    rejects=[x for x in r.get('rejected_actions',[]) if x.get('state')==decision]
    if r['arm']=='B':
        feedback=json.loads(prompt.split('\nPrior rejected actions at this state:\n',1)[1])
        expected=[{k:v for k,v in row.items() if k!='state'} for row in rejects[:attempt]]
        if feedback!=expected or [x['decision'] for x in feedback]!=[x['output'] for x in prior]:errors.append('B feedback not linked to preceding same-state outputs')
    elif r['arm']=='C':
        history_text,limit_text=prompt.split('\nThis state history:\n',1)[1].split('\nRemaining:\n',1)
        history=json.loads(history_text);limits=json.loads(limit_text)
        if [x.get('decision') for x in history]!=[x['output'] for x in prior]:errors.append('C history not linked to preceding same-state outputs')
        successful=[]
        for row in history:
            if 'result' in row:
                if row.get('candidate_index')!=len(successful) or row['result'] not in r.get('solver_results',[]) or row['result'].get('decision',decision)!=decision:errors.append('C feedback candidate is not own recorded solver output')
                successful.append(row['result'])
            elif {'state':decision,**row} not in rejects:errors.append('C feedback error not preserved in rejected actions')
        ledger=_ledger();position=next((i for i,x in enumerate(ledger) if x.get('event')=='reserve' and x.get('call_id')==call_id),len(ledger))
        prior_seconds=sum(x['requested_seconds'] for x in ledger[:position] if x.get('event')=='solver_reserve' and Path(x['run_id']).resolve()==path.resolve())
        if limits.get('responses_including_this')!=cfg['responses_per_decision']['C']-attempt or not _equal(limits.get('solver_seconds'),cfg['solver_budget_seconds']-prior_seconds):errors.append('C displayed remaining budgets differ')

def _models(path,r,cfg,states,errors,warnings):
    ledger=_ledger();all_dirs=sorted(path.glob('model_*_*'));models=[];by_decision=defaultdict(list);usages=[]
    for directory in all_dirs:
        match=re.fullmatch(r'model_(\d+)_(\d+)',directory.name)
        if not directory.is_dir() or not match:continue
        decision,attempt=map(int,match.groups());prefix=directory.name+': '
        if not (directory/'result.json').exists():errors.append(prefix+'incomplete model attempt');continue
        saved=read_json(directory/'result.json');models.append(saved)
        events,bad=read_events(directory/'events.jsonl');parsed=summarize_events(events);usages.append(parsed['usage'])
        if bad:errors.append(prefix+'malformed raw model events')
        for k in ('usage','native_tool_events','completed_turns','thread_ids'):
            if saved.get(k)!=parsed[k]:errors.append(prefix+k+' differs from raw events')
        if saved['status']=='success':
            finals=[e['item'].get('text') for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='agent_message']
            if saved.get('returncode')!=0 or len(finals)==0 or parsed['native_tool_events'] or parsed['completed_turns']!=1:errors.append(prefix+'not an isolated successful turn')
            elif json.loads(finals[-1])!=saved['output'] or read_json(directory/'final.txt')!=saved['output']:errors.append(prefix+'raw model output chain differs')
            # Append after checking feedback against only earlier responses.
        request=read_json(directory/'request.json');prompt=(directory/'prompt.txt').read_text();schema=(directory/'schema.json').read_text()
        fingerprint=_sha((prompt+'\n'+schema+'\n'+json.dumps(saved['config'],sort_keys=True)).encode())
        if fingerprint!=saved['request_fingerprint'] or fingerprint!=request['request_fingerprint'] or request['config']!=saved['config']:errors.append(prefix+'request fingerprint/config mismatch')
        block=prompt.split('\nCurrent state:\n',1)[1].split('\nPrior rejected actions at this state:\n',1)[0].split('\nThis state history:\n',1)[0]
        if decision not in states or json.loads(block)!=states[decision]:errors.append(prefix+'prompt differs from saved current state')
        _history(path,r,cfg,decision,attempt,prompt,by_decision[decision],errors,saved['call_id'])
        if saved['status']=='success':by_decision[decision].append({'attempt':attempt,'output':saved['output']})
        for k in ('model','reasoning_effort','phase','grant_id'):
            if saved['config'].get(k)!=cfg['model'].get(k):errors.append(prefix+'run/model configuration mismatch: '+k)
        if saved['config']['timeout_seconds']>cfg['model']['timeout_seconds']:errors.append(prefix+'timeout limit exceeded')
        reserve=[x for x in ledger if x.get('event')=='reserve' and x.get('call_id')==saved.get('call_id')]
        finish=[x for x in ledger if x.get('event')=='finish' and x.get('call_id')==saved.get('call_id')]
        if len(reserve)!=1 or len(finish)!=1:errors.append(prefix+'ledger identity missing/duplicate')
        else:
            _admission(ledger,saved['call_id'],errors)
            if reserve[0].get('phase')!=saved['config']['phase'] or reserve[0].get('grant_id')!=saved['config']['grant_id']:errors.append(prefix+'ledger phase/grant mismatch')
            if Path(reserve[0]['run_id']).resolve()!=directory.resolve():errors.append(prefix+'ledger run mismatch')
            details=finish[0]['details']
            if finish[0]['status']!=saved['status'] or details.get('usage')!=saved['usage'] or not _equal(details.get('duration_seconds'),saved['duration_seconds']):errors.append(prefix+'ledger completion mismatch')
        if len(prompt)>120000:errors.append(prefix+'prompt exceeds input character bound')
        if attempt>=cfg.get('responses_per_decision',{}).get(r['arm'],0):errors.append(prefix+'response-per-decision limit exceeded')
    if r['arm'] in ('A','F') and models:errors.append('fixed strategy used model calls')
    observed_ids=[m['call_id'] for m in models]
    reserved_ids=[x['call_id'] for x in ledger if x.get('event')=='reserve' and Path(x['run_id']).parent.resolve()==path.resolve()]
    if sorted(observed_ids)!=sorted(reserved_ids):errors.append('model ledger reservations not fully represented in per-call results')
    if models!=r.get('model_results',[]):errors.append('root models differ from raw per-call records')
    costs=r['costs']
    if len(models)!=costs['model_calls']:errors.append('model call cost count mismatch')
    if len(models)>cfg.get('max_model_calls',{}).get(r['arm'],0):errors.append('run model call budget exceeded')
    totals={k:_sum(u[k] for u in usages) for k in TOKEN_KEYS}
    for k in TOKEN_KEYS:
        if k in costs.get('usage',{}) and costs['usage'][k]!=totals[k]:errors.append('aggregate model token mismatch: '+k)
        elif k not in costs.get('usage',{}) and models:(warnings if r['phase']=='development' else errors).append('aggregate token detail absent: '+k)
    if not _equal(costs['model_elapsed_seconds'],sum(m['duration_seconds'] for m in models)):errors.append('aggregate model elapsed mismatch')
    return by_decision,totals

def _solvers(path,r,cfg,states,model_decisions,actions,errors,warnings):
    ledger=_ledger();reservations=[x for x in ledger if x.get('event')=='solver_reserve' and Path(x['run_id']).resolve()==path.resolve()]
    files=sorted(path.glob('solver_*.json'));solvers=[read_json(p) for p in files]
    if solvers!=r.get('solver_results',[]):errors.append('root solver results differ from raw files')
    if r['arm']=='B' and (solvers or reservations):errors.append('direct B used a forbidden solver')
    by_decision=defaultdict(list)
    for i,s in enumerate(solvers):
        sid=s.get('solver_call_id')
        matches=[x for x in reservations if x['call_id']==sid] if sid else reservations[i:i+1]
        if not sid:(warnings if r['phase']=='development' else errors).append(f'solver {i}: legacy record lacks explicit call_id')
        if len(matches)!=1:errors.append(f'solver {i}: missing/duplicate ledger reservation');continue
        reserve=matches[0];_admission(ledger,reserve['call_id'],errors);decision=reserve.get('metadata',{}).get('decision')
        if reserve.get('phase')!=cfg['model']['phase'] or reserve.get('grant_id')!=cfg['solver_grant_id']:errors.append('solver ledger phase/grant mismatch')
        if s.get('decision',decision)!=decision:errors.append('solver decision/ledger mismatch')
        finish=[x for x in ledger if x.get('event')=='finish' and x.get('call_id')==reserve['call_id']]
        if len(finish)!=1 or finish[0]['status']!=s.get('status','success') or not _equal(finish[0]['details'].get('wall_seconds'),s['wall_seconds']):errors.append('solver completion/elapsed ledger mismatch')
        if s['parameters']!=reserve.get('metadata',{}).get('parameters') or not _equal(s['parameters']['time_limit'],reserve['requested_seconds']):errors.append('solver parameters/budget ledger mismatch')
        if decision not in states:errors.append('solver missing decision state');continue
        by_decision[decision].append(s)
    if len(reservations)!=len(solvers):
        (warnings if r['status']!='success' else errors).append('solver reservations include an incomplete/failed call without a raw result')
    for decision,state in states.items():
        chosen=actions.get(decision,{}).get('action')
        if chosen is not None and _action_errors(state,chosen):errors.append(f'decision {decision}: applied action violates observable state')
        outputs=[x['output'] for x in model_decisions.get(decision,[])]
        if r['arm']=='B':
            if chosen is not None and (not outputs or {k:outputs[-1].get(k) for k in ('dispatches','wait_seconds')}!=chosen):errors.append(f'decision {decision}: B action not explicitly selected by model')
        elif r['arm']=='C':
            candidates=[];remaining=by_decision.get(decision,[]).copy()
            for output in outputs:
                if output.get('action')=='solve':
                    params={k:output.get(k) for k in PARAMETERS}
                    if remaining and remaining[0]['parameters']==params:
                        candidate=remaining.pop(0)
                        if not _action_errors(state,candidate['action']):candidates.append(candidate)
                elif output.get('action')=='apply' and output is outputs[-1]:
                    k=output.get('candidate_index')
                    if type(k) is not int or not 0<=k<len(candidates) or (chosen is not None and candidates[k]['action']!=chosen):errors.append(f'decision {decision}: C candidate apply chain differs')
                    if any(output.get(x) is not None for x in PARAMETERS):errors.append('C apply contains nonnull solver parameters')
            if chosen is not None and (not outputs or outputs[-1].get('action')!='apply'):errors.append(f'decision {decision}: C lacks explicit apply')
            if remaining:errors.append(f'decision {decision}: solver used parameters never selected by C')
        elif r['arm'] in ('A','F'):
            candidates=by_decision.get(decision,[])
            params={**cfg.get('classical_parameters' if r['arm']=='A' else 'fixed_auxiliary_parameters',{}),'seed':cfg['seed']}
            if candidates and (len(candidates)!=1 or candidates[0]['parameters']!=params or (chosen is not None and candidates[0]['action']!=chosen)) or (chosen is not None and not candidates):errors.append(f'decision {decision}: fixed strategy parameters/action mismatch')
    cost=r['costs'];requested=sum(s['parameters']['time_limit'] for s in solvers)
    if cost['solver_calls']!=len(solvers) or not _equal(cost['solver_wall_seconds'],sum(s['wall_seconds'] for s in solvers)) or not _equal(cost['solver_budget_seconds'],requested):errors.append('aggregate solver costs differ')
    if requested>cfg['solver_budget_seconds']+1e-8:errors.append('solver run budget exceeded')

def replay(path,verify_data_dir=None):
    path=Path(path);errors=[];warnings=[]
    result={'run_id':path.name,'audit_pass':False,'domain_valid':False,'provenance_complete':False,'status':'unreadable','auxiliary':bool(re.search(r'_F(?:_|$)',path.name))}
    try:
        r=read_json(path/'result.json');cfg=read_json(path/'config.json');manifest=read_json(path/'input_manifest.json')
        result.update(run_id=r['run_id'],phase=r['phase'],metrics=r.get('metrics'),costs=r.get('costs'),failure_type=r.get('failure_type'),status=r['status'],scenario=r['scenario'],arm=r['arm'],repeat=r['repeat'],auxiliary=r.get('auxiliary',False) or r['arm']=='F')
        if object_digest(cfg)!=r['config_sha256'] or r['identity']['config_sha256']!=r['config_sha256']:errors.append('config hash/identity mismatch')
        for key in ('scenario','arm','repeat'):
            if r[key]!=r['identity'][key]:errors.append('root identity mismatch: '+key)
        events=[json.loads(line) for line in (path/'trace.jsonl').read_text().splitlines() if line.strip()]
        if not events or events[0].get('manifest')!=manifest:errors.append('trace/input manifest mismatch')
        data_dir=Path(verify_data_dir) if verify_data_dir else ROOT/'data/smt/SMT2020_LVHM'
        result['source_data']=_source_binding(path,r,cfg,manifest,data_dir,errors,warnings)
        domain=audit_trace(events,verify_data_dir=data_dir);result.update(domain_valid=domain['valid'],domain_errors=domain['errors'],recomputed_metrics=domain.get('metrics'))
        if r['status']=='success':
            if not domain['valid']:errors.append('successful run fails independent domain audit')
            if not r['validation']['valid']:errors.append('success with failed stored validation')
            for key,value in domain.get('metrics',{}).items():
                if key not in r['metrics'] and r['phase']=='development':warnings.append('legacy stored metric absent; independently recomputed: '+key)
                elif not _same(r['metrics'].get(key),value):errors.append('independent metric mismatch: '+key)
            if not r['metrics'].get('completed_window') or not _equal(r['metrics'].get('simulation_seconds'),cfg['window_seconds']):errors.append('success before full configured window')
        states={int(p.stem.split('_')[1]):read_json(p) for p in path.glob('state_*.json')}
        for state in states.values():
            if set(state)!=STATE_KEYS:errors.append('state has missing or unapproved observable fields')
        project_states(events,states,errors)
        trace_actions=[{'decision':e['decision'],'time':e['time'],'action':e['action']} for e in events if e['kind']=='action']
        root_actions=[{k:e[k] for k in ('decision','time','action')} for e in r.get('actions',[])]
        if trace_actions!=root_actions:errors.append('root actions differ from executed trace actions')
        action_files={int(p.stem.split('_')[1]):read_json(p) for p in path.glob('action_*.json')}
        for entry in trace_actions:
            if action_files.get(entry['decision'])!=entry['action']:errors.append('action file differs from executed trace')
        if set(action_files)!={e['decision'] for e in trace_actions}:errors.append('unexecuted or missing action file')
        if len(trace_actions)>cfg['max_decisions']:errors.append('decision budget exceeded')
        decisions,usage=_models(path,r,cfg,states,errors,warnings);result['recomputed_usage']=usage
        for entry in r.get('actions',[]):
            decision=entry['decision'];nm=len([m for m in path.glob(f'model_{decision:02d}_*') if (m/'result.json').exists()])
            ns=sum(x.get('decision')==decision for x in r.get('solver_results',[]))
            if 'model_calls' in entry and entry['model_calls']!=nm:errors.append('decision model count mismatch')
            if 'solver_calls' in entry and all('decision' in x for x in r.get('solver_results',[])) and entry['solver_calls']!=ns:errors.append('decision solver count mismatch')
            if 'decision_elapsed_seconds' in entry and not 0<=entry['decision_elapsed_seconds']<=r['costs']['end_to_end_seconds']:errors.append('decision latency invalid')
        _solvers(path,r,cfg,states,decisions,{e['decision']:e for e in trace_actions},errors,warnings)
        result['provenance_complete']=_provenance(path,r,cfg,manifest,errors,warnings)
        elapsed=(dt.datetime.fromisoformat(r['finished_at'])-dt.datetime.fromisoformat(r['started_at'])).total_seconds()
        if not _equal(elapsed,r['costs']['end_to_end_seconds'],1):errors.append('end-to-end time differs from timestamps')
        if r['costs']['model_elapsed_seconds']+r['costs']['solver_wall_seconds']>r['costs']['end_to_end_seconds']+1:errors.append('component time exceeds end-to-end time')
    except (OSError,ValueError,KeyError,IndexError,TypeError,AttributeError) as exc:errors.append(f'evidence error: {type(exc).__name__}: {exc}')
    result.update(audit_pass=not errors,errors=errors,warnings=warnings);return result

def audit_phase(phase,freeze=None,verify_data_dir=None):
    """freeze is an optional freeze basename or JSON Path; core and F never pool."""
    root=ROOT/'runs'/phase;all_reports=[];incomplete=[];paths={}
    for path in sorted(root.iterdir()) if root.exists() else []:
        if not path.is_dir():continue
        identifiable=(path/'input_manifest.json').exists() or path.name.startswith(('smt','dev_smt'))
        if (path/'result.json').exists():
            try:raw=read_json(path/'result.json')
            except (OSError,ValueError):raw={}
            if raw.get('family')=='smt2020' or identifiable:
                report=replay(path,verify_data_dir);all_reports.append(report);paths[report['run_id']]=path
        elif identifiable:
            incomplete.append({'run_id':path.name,'state':'incomplete','process_state':'unknown; may still be active'})
    core=[r for r in all_reports if not r['auxiliary']];aux=[r for r in all_reports if r['auxiliary']]
    expected=None;missing=[];extra=[];duplicates=[];errors=[];scope_name='core';scope=core
    if phase!='development' or freeze:
        if freeze:
            supplied=Path(freeze);files=[supplied if supplied.suffix=='.json' or supplied.is_absolute() else ROOT/'configs/freezes'/f'{freeze}.json']
        else:files=list((ROOT/'configs/freezes').glob('*.json'))
        manifests=[]
        for p in files:
            try:
                f=read_json(p)
                if f.get('phase')==phase:manifests.append(f)
            except (OSError,ValueError):errors.append('unreadable phase freeze: '+str(p))
        if len(manifests)!=1:errors.append('no unique phase freeze')
        else:
            f=manifests[0];expected=[tuple(k) for k in f['matrix']];actual=defaultdict(list)
            auxiliary=bool(expected) and all(k[1]=='F' for k in expected);scope=aux if auxiliary else core;scope_name='auxiliary' if auxiliary else 'core'
            scenarios={k[0] for k in expected};arms={'F'} if auxiliary else {'A','B','C'}
            planned={(scenario,arm,repeat) for scenario in scenarios for arm in arms for repeat in (1,2,3)}
            if len(scenarios)!=3 or set(expected)!=planned or len(expected)!=len(planned):errors.append('frozen matrix must contain exactly 27 core or 9 auxiliary cells across three scenarios')
            if any(type(k[0]) is not int or type(k[2]) is not int for k in expected):errors.append('frozen SMT scenario/repeat types invalid')
            for r in scope:
                actual[(r.get('scenario'),r.get('arm'),r.get('repeat'))].append(r['run_id'])
                saved=paths[r['run_id']]/'freeze.json'
                try:matches=saved.exists() and read_json(saved)==f
                except (OSError,ValueError):matches=False
                if not matches:
                    r['audit_pass']=False;r['provenance_complete']=False;r['errors'].append('saved freeze differs from selected phase freeze')
            for key,ids in actual.items():
                if key not in expected:extra+=ids
                if len(ids)>1:duplicates.append({'key':key,'run_ids':ids})
            for key in expected:
                if key not in actual:
                    run_id=f'smt{key[0]}_{key[1]}_r{key[2]}'
                    missing.append({'scenario':key[0],'arm':key[1],'repeat':key[2],'run_id':run_id,'state':'incomplete' if any(x['run_id']==run_id for x in incomplete) else 'not_started'})
    complete=expected is not None and not missing and not extra and not duplicates and not errors
    certified=lambda r:r['status']=='success' and r['audit_pass'] and r['domain_valid']
    return {'at':now(),'phase':phase,'records':len(core),'passed':sum(r['audit_pass'] for r in core),'successes':sum(r['status']=='success' for r in core),
            'certified_successes':sum(certified(r) for r in core),'failures':sum(r['status']!='success' for r in core),'runs':core,
            'auxiliary_records':len(aux),'auxiliary_passed':sum(r['audit_pass'] for r in aux),'auxiliary_certified_successes':sum(certified(r) for r in aux),'auxiliary_runs':aux,
            'matrix_scope':scope_name,'expected_records':len(expected) if expected is not None else None,'missing':missing,'unexpected':extra,'duplicates':duplicates,'phase_errors':errors,
            'incomplete':incomplete,'coverage_complete':complete,'acceptance_ready':complete and not incomplete and all(certified(r) and r['provenance_complete'] for r in scope)}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--phase',default='development');ap.add_argument('--freeze');ap.add_argument('--label',default='latest');ap.add_argument('--data-dir',type=Path);a=ap.parse_args()
    s=audit_phase(a.phase,a.freeze,a.data_dir);write_json(ROOT/'artifacts'/a.phase/f'smt_replay_{a.label}.json',s)
    print(json.dumps({k:v for k,v in s.items() if k not in ('runs','auxiliary_runs')},ensure_ascii=False))
    if s['phase_errors'] or any(not r['audit_pass'] for r in s['runs']+s['auxiliary_runs']):raise SystemExit(1)
    if a.phase!='development' and not s['coverage_complete']:raise SystemExit(2)

if __name__=='__main__':main()
