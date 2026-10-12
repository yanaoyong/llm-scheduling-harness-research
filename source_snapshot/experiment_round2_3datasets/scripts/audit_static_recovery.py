#!/usr/bin/env python3
"""Offline audit and fail-closed gates for post-hoc static B channel recovery.
Never imports a runner or calls a model/solver. Original v1 records stay immutable.
"""
from __future__ import annotations
import argparse,datetime as dt,hashlib,json,math,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.fjsp.validator import validate

TOKEN_KEYS=('input_tokens','cached_input_tokens','output_tokens','cache_write_input_tokens','reasoning_output_tokens')
DEFAULT_FREEZES=('static-v1','smt-v1','static-aux-v2','smt-aux-v1')
BUDGETS={'phase':'formal','model_attempts':300,'reported_tokens':3000000,'solver_requested_seconds':4500,'campaign_activity_seconds':14400,'logical_model_attempts':3,'logical_activity_seconds':1000,'extra_attempts_per_cell':1,'request_timeout_seconds':300,'unknown_completed_limit':3}
REQUIRED_CODE=('scripts/recover_static_channel.py','scripts/audit_static_recovery.py','src/agents/model_transport.py','src/agents/budget.py','src/agents/static.py','src/fjsp/validator.py','src/__init__.py','src/agents/__init__.py','src/fjsp/__init__.py')

def read(path):return json.loads(Path(path).read_text())
def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda:f.read(1024*1024),b''):h.update(data)
    return h.hexdigest()
def json_digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n');temp.replace(path)
def safe_path(relative):
    p=Path(relative)
    if p.is_absolute() or '..' in p.parts:raise ValueError('Unsafe experiment-relative path')
    out=(ROOT/p).resolve()
    if ROOT not in out.parents:raise ValueError('Path escapes experiment')
    return out
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,stderr=subprocess.PIPE)
def close(a,b,tol=.01):return type(a) in (int,float) and type(b) in (int,float) and math.isfinite(a) and math.isfinite(b) and abs(a-b)<=tol

def events(path):
    values=[]
    for line in Path(path).read_text().splitlines():
        if line.strip():values.append(json.loads(line))
    completed=[x for x in values if x.get('type')=='turn.completed'];allowed={'agent_message','reasoning','error'}
    native=[x for x in values if x.get('type') in ('item.started','item.completed','item.updated') and x.get('item',{}).get('type') not in allowed]
    finals=[x['item']['text'] for x in values if x.get('type')=='item.completed' and x.get('item',{}).get('type')=='agent_message']
    usages=[x.get('usage') for x in completed if isinstance(x.get('usage'),dict)]
    usage={k:sum(x[k] for x in usages) if usages and all(type(x.get(k)) in (int,float) and x[k]>=0 for x in usages) else None for k in TOKEN_KEYS}
    return {'completed_turns':len(completed),'native':native,'finals':finals,'usage':usage,'events':values}

def normalized_command(command):
    args=list(command['argv']);out=[];i=0
    while i<len(args):
        token=args[i]
        if token in ('--cd','--output-schema','--output-last-message'):
            out.extend([token,'<isolated-path>']);i+=2;continue
        if token=='-c' and i+1<len(args):
            config=args[i+1];key=config.split('=',1)[0]
            if key in ('model_instructions_file','log_dir','sqlite_home'):config=key+'="<isolated-path>"'
            out.extend([token,config]);i+=2;continue
        out.append(token);i+=1
    return {'argv':out,'stdin':command['stdin'],'proxy':command.get('proxy')}

def command_paths_valid(command,directory):
    args=command['argv'];expected={'--cd':str(directory/'isolated-cwd'),'--output-schema':str(directory/'schema.json'),'--output-last-message':str(directory/'final.txt')}
    if command.get('cwd')!=str(directory/'isolated-cwd'):return False
    for flag,value in expected.items():
        if args.count(flag)!=1 or args[args.index(flag)+1]!=value:return False
    settings={args[i+1].split('=',1)[0]:args[i+1].split('=',1)[1] for i,x in enumerate(args[:-1]) if x=='-c'}
    for key,relative in {'model_instructions_file':'system-instructions.txt','log_dir':'runtime/log','sqlite_home':'runtime/state'}.items():
        if json.loads(settings[key])!=str(directory/relative):return False
    return True

def qualify_original(path):
    """Objective eligibility: first B request, transport failure, no complete output."""
    path=Path(path);r=read(path/'result.json');reasons=[]
    if r.get('arm')!='B' or r.get('family') not in ('brandimarte','hurink') or r.get('status') not in ('failed','timeout'):return None
    model_dirs=sorted(p for p in (path/'agent').glob('model_call_*') if p.is_dir())
    if len(model_dirs)!=1 or model_dirs[0].name!='model_call_001':return None
    model_path=model_dirs[0];m=read(model_path/'result.json');parsed=events(model_path/'events.jsonl')
    if m.get('failure_reason') not in ('model_call_timeout','model_transport_error') or m.get('status') not in ('failed','timeout'):return None
    if r.get('failure_type')!=m.get('failure_reason') or r.get('metrics',{}).get('first_output_valid') is True or r.get('metrics',{}).get('revisions',0)!=0:return None
    if r.get('actions') or r.get('solver_results') or r.get('schedule') is not None or r.get('validation',{}).get('valid') or r.get('metrics',{}).get('makespan') is not None:return None
    if parsed['completed_turns'] or parsed['native'] or parsed['finals'] or m.get('output') is not None:return None
    if (model_path/'final.txt').exists() and (model_path/'final.txt').read_bytes().strip():return None
    if m.get('completed_turns')!=0 or m.get('native_tool_events') or m.get('usage')!=parsed['usage']:raise ValueError('Original raw event summary mismatch: '+r['run_id'])
    messages='\n'.join(str(x.get('message','')) for x in parsed['events'] if x.get('type') in ('error','turn.failed'))+'\n'+(model_path/'stderr.log').read_text(errors='replace')
    if not re.search(r'tls.*(eof|close_notify)|connection (reset|closed)|stream disconnected|connect(?:ion)? (?:timed out|refused)|unexpected.eof',messages,re.I):return None
    if re.search(r'unauthorized|insufficient.quota|rate.limit|invalid.api.key',messages,re.I):return None
    cost=r.get('costs',{})
    if cost.get('model_calls')!=1 or cost.get('solver_calls')!=0 or cost.get('solver_budget_seconds')!=0 or r.get('model_results')!=[m]:raise ValueError('Original attempt/solver inventory mismatch')
    if m['config'].get('phase')!='formal' or m['config'].get('timeout_seconds')!=300:raise ValueError('Original model configuration outside protocol')
    if Path(m['config']['ledger_path']).resolve()!=ROOT/'progress/model_ledger.jsonl':raise ValueError('Original ledger differs')
    files=['result.json','input.json','config.json','freeze.json']
    files += ['agent/model_call_001/'+name for name in ('result.json','request.json','prompt.txt','schema.json','system-instructions.txt','command.json','events.jsonl','stderr.log')]
    evidence={rel:digest(path/rel) for rel in files}
    evidence['agent/model_call_001/final.txt']=digest(model_path/'final.txt') if (model_path/'final.txt').exists() else None
    return {'phase':r['phase'],'run_id':r['run_id'],'original_call_id':m['call_id'],'original_result_sha256':evidence['result.json'],
            'original_activity_seconds':cost['end_to_end_seconds'],'request_fingerprint':m['request_fingerprint'],
            'prompt_sha256':digest(model_path/'prompt.txt'),'schema_sha256':digest(model_path/'schema.json'),'system_sha256':digest(model_path/'system-instructions.txt'),'evidence_sha256':evidence}

def inspect_originals(freeze_links=None):
    links=freeze_links or [{'path':f'configs/freezes/{name}.json','sha256':digest(ROOT/f'configs/freezes/{name}.json')} for name in DEFAULT_FREEZES]
    rows=[];eligible=[];pending=[];errors=[];seen=set();result_hashes={}
    for link in links:
        p=safe_path(link['path'])
        if digest(p)!=link['sha256']:raise ValueError('Original freeze hash mismatch')
        f=read(p);smt=f.get('dataset')=='smt2020'
        for item,arm,repeat in f['matrix']:
            run_id=f'smt{item}_{arm}_r{repeat}' if smt else f'{item}_{arm}_r{repeat}';key=(f['phase'],run_id)
            if key in seen:raise ValueError('Duplicate original cell')
            seen.add(key);path=ROOT/'runs'/f['phase']/run_id
            if not (path/'result.json').exists():pending.append({'phase':f['phase'],'run_id':run_id,'state':'incomplete' if path.exists() else 'not_started'});continue
            r=read(path/'result.json');result_hashes[str((path/'result.json').relative_to(ROOT))]=digest(path/'result.json')
            if r.get('status') not in ('success','failed','timeout'):errors.append('nonterminal original '+str(key))
            if r.get('phase')!=f['phase'] or r.get('run_id')!=run_id or r.get('arm')!=arm or r.get('repeat')!=repeat:errors.append('original identity mismatch '+str(key))
            if r.get('freeze_tag')!=f['tag'] or r.get('code_commit')!=f['code_commit']:errors.append('original freeze identity mismatch '+str(key))
            rows.append({'phase':f['phase'],'run_id':run_id,'status':r['status'],'end_to_end_seconds':r.get('costs',{}).get('end_to_end_seconds'),'finished_at':r.get('finished_at'),'path':str(path.relative_to(ROOT))})
            if not smt and arm=='B':
                q=qualify_original(path)
                if q is not None:eligible.append(q)
    return {'at':now(),'original_freezes':links,'total_cells':len(seen),'completed_cells':len(rows),'all_completed':len(seen)==180 and len(rows)==180 and not pending and not errors,
            'original_results_sha256':dict(sorted(result_hashes.items())),'eligible':sorted(eligible,key=lambda x:(x['phase'],x['run_id'])),'pending':pending,'errors':errors,'rows':rows}

def ledger_rows():return [json.loads(line) for line in (ROOT/'progress/model_ledger.jsonl').read_text().splitlines() if line.strip()]
def budget_state(rows):
    reserves=[x for x in rows if x.get('event')=='reserve' and x.get('phase')=='formal'];solvers=[x for x in rows if x.get('event')=='solver_reserve' and x.get('phase')=='formal'];finishes={};tokens=0;unknown=0;pending=[]
    for x in rows:
        if x.get('event')=='finish':
            if x['call_id'] in finishes:raise ValueError('Duplicate ledger finish')
            finishes[x['call_id']]=x
    for reserve in reserves:
        finish=finishes.get(reserve['call_id'])
        if finish is None:pending.append(reserve['call_id']);continue
        usage=finish.get('details',{}).get('usage') or {};values=[usage.get(k) for k in ('input_tokens','output_tokens')]
        known=[type(v) is int and v>=0 for v in values];tokens+=sum(v for v,k in zip(values,known) if k);unknown+=not all(known)
    for reserve in solvers:
        if reserve['call_id'] not in finishes:pending.append(reserve['call_id'])
    return {'model_attempts':len(reserves),'reported_tokens':tokens,'unknown_completed':unknown,'pending':pending,'solver_requested_seconds':sum(x['requested_seconds'] for x in solvers)}

def campaign_activity():
    total=0
    for folder in (ROOT/'runs').iterdir():
        if not folder.is_dir() or folder.name=='development':continue
        for p in folder.glob('*/result.json'):
            value=read(p).get('costs',{}).get('end_to_end_seconds')
            if type(value) not in (int,float) or value<0:raise ValueError('Unknown campaign activity cost: '+str(p))
            total+=value
    return total

def check_original_result_binding(manifest,original):
    expected=manifest.get('original_results_sha256');actual=original.get('original_results_sha256')
    if not isinstance(expected,dict) or len(expected)!=180 or expected!=actual:
        raise ValueError('Complete 180 original result byte-hash binding is missing or changed')

def load_gate(freeze_path,*,current_files=True):
    freeze_path=Path(freeze_path).resolve();f=read(freeze_path);commit=f['code_commit'];manifest_path=safe_path(f['manifest_path']);m=read(manifest_path)
    if git('cat-file','-t',commit).strip()!=b'commit' or git('rev-parse',f['tag']+'^{commit}').decode().strip()!=commit:raise ValueError('Recovery Git commit/tag mismatch')
    if f['files'].get(f['manifest_path'])!=digest(manifest_path):raise ValueError('Recovery manifest not bound by freeze')
    for rel,sha in f['files'].items():
        safe_path(rel)
        if hashlib.sha256(git('show',commit+':'+rel)).hexdigest()!=sha:raise ValueError('Recovery committed file mismatch: '+rel)
        if current_files and digest(safe_path(rel))!=sha:raise ValueError('Recovery live file changed: '+rel)
    if any(rel not in f['files'] for rel in REQUIRED_CODE):raise ValueError('Recovery freeze omits required implementation files')
    if not any(rel.startswith('docs/') and 'recovery' in rel.lower() for rel in f['files']):raise ValueError('Recovery protocol document must be committed and frozen')
    if m.get('draft_not_frozen') is True:raise ValueError('Draft recovery manifest cannot execute')
    if m.get('budgets')!=BUDGETS or m.get('original_total_cells')!=180 or m.get('posthoc_reliability_recovery') is not True:raise ValueError('Recovery protocol budgets/scope differ')
    if not re.fullmatch(r'recovery_static_[A-Za-z0-9_-]+',m['recovery_phase']):raise ValueError('Unsafe recovery phase')
    if {x['path'] for x in m['original_freezes']}!={f'configs/freezes/{name}.json' for name in DEFAULT_FREEZES}:raise ValueError('Recovery must preserve all four original frozen matrices')
    for link in m['original_freezes']:
        old_freeze=read(safe_path(link['path']))
        if git('rev-parse',old_freeze['tag']+'^{commit}').decode().strip()!=old_freeze['code_commit']:raise ValueError('Original freeze tag changed')
    original=inspect_originals(m['original_freezes'])
    if not original['all_completed']:raise ValueError('All 180 original planned records must finish first')
    check_original_result_binding(m,original)
    if original['eligible']!=m['eligible']:raise ValueError('Recovery eligibility list is incomplete or changed')
    # Reuse saved whole-phase audits. Failure evidence can pass while its schedule is invalid.
    phases={'acceptance_static_v1'}|{q['phase'] for q in m['eligible']}
    for phase in phases:
        link=m['original_audits'][phase];audit_path=safe_path(link['path'])
        if digest(audit_path)!=link['sha256']:raise ValueError('Original audit digest differs')
        a=read(audit_path);reports=a.get('runs',[])+a.get('auxiliary_runs',[]);planned=[r for r in original['rows'] if r['phase']==phase]
        if a.get('phase')!=phase or not a.get('coverage_complete') or a.get('phase_errors') or a.get('incomplete') or {r['run_id'] for r in reports}!={r['run_id'] for r in planned}:raise ValueError('Saved original phase audit is incomplete')
        if any(not r.get('audit_pass') or not r.get('provenance_complete') for r in reports):raise ValueError('Original phase has uncertified evidence')
        for report in reports:
            key=f'runs/{phase}/{report["run_id"]}/result.json'
            for field in ('result_sha256','result_sha'):
                if field in report and report[field]!=m['original_results_sha256'][key]:raise ValueError('Saved audit result hash differs from original byte binding')
        if dt.datetime.fromisoformat(a['at'])<max(dt.datetime.fromisoformat(r['finished_at']) for r in planned):raise ValueError('Original audit predates completed phase')
    return f,m,original

def independent_decode(problem,order):
    """Independent literal model-order decoder; never sorts, repairs or chooses."""
    ops={o['id']:o for j in problem['jobs'] for o in j['operations']};next_op={j['id']:0 for j in problem['jobs']};jr={j:0 for j in next_op};mr={m:0 for m in problem['machines']};result=[];seen=set()
    if not isinstance(order,list) or len(order)!=len(ops):raise ValueError('Recovery order does not cover all operations')
    for item in order:
        if isinstance(item,list):
            if len(item)!=2 or any(type(x) is not int for x in item):raise ValueError('Invalid compact action')
            job,machine=item
            if job not in next_op:raise ValueError('Unknown job')
            oid=f'j{job}o{next_op[job]}'
        elif isinstance(item,dict) and set(item)=={'id','machine'}:oid,machine=item['id'],item['machine']
        else:raise ValueError('Invalid model action fields')
        if oid not in ops or oid in seen or type(machine) is not int:raise ValueError('Unknown/duplicate operation or machine')
        o=ops[oid];job=o['job'];alternatives={a['machine']:a['duration'] for a in o['alternatives']}
        if o['index']!=next_op[job] or machine not in alternatives:raise ValueError('Precedence/eligibility violation')
        start=max(jr[job],mr[machine]);end=start+alternatives[machine];result.append({'id':oid,'machine':machine,'start':start,'end':end});jr[job]=mr[machine]=end;next_op[job]+=1;seen.add(oid)
    return {'operations':result}

def audit_recovery(path,freeze,manifest):
    path=Path(path);errors=[];report={'run_id':path.name,'audit_pass':False,'valid':False,'status':'unreadable'}
    try:
        r=read(path/'result.json');report['status']=r['status'];key=(r['original_phase'],r['original_run_id']);eligible=next(q for q in manifest['eligible'] if (q['phase'],q['run_id'])==key);old=ROOT/'runs'/key[0]/key[1];om=old/'agent/model_call_001';new=path/'model_call_001'
        if r['original']!=eligible or qualify_original(old)!=eligible:errors.append('Original failure evidence or eligibility differs')
        if read(path/'original_link.json')!=eligible or (path/'input.json').read_bytes()!=(old/'input.json').read_bytes():errors.append('Original input/link copy differs')
        claim=read(path/'claim.json')
        for key in ('original','original_call_id','started_at','code_commit','freeze_tag','freeze_manifest_sha256','cli_binary_sha256','admission'):
            if claim.get(key)!=r.get(key):errors.append('Claim/root association differs: '+key)
        if r['phase']!=manifest['recovery_phase'] or r['protocol_version']!=manifest['protocol_version']:errors.append('Recovery identity/protocol differs')
        if read(path/'freeze.json')!=freeze or r['freeze_manifest_sha256']!=digest(path/'freeze.json') or r['code_commit']!=freeze['code_commit'] or r['freeze_tag']!=freeze['tag']:errors.append('Recovery freeze association differs')
        for rel,sha in freeze['files'].items():
            if digest(path/'source_snapshot'/rel)!=sha:errors.append('Recovery source snapshot differs '+rel)
        for name in ('prompt.txt','schema.json','system-instructions.txt'):
            if (om/name).read_bytes()!=(new/name).read_bytes():errors.append('Exact request bytes differ: '+name)
        original_model=read(om/'result.json');model=read(new/'result.json');raw=events(new/'events.jsonl');report['usage']=raw['usage']
        if r.get('model_result')!=model or model.get('usage')!=raw['usage'] or model.get('completed_turns')!=raw['completed_turns'] or bool(model.get('native_tool_events'))!=bool(raw['native']):errors.append('Raw model summary/root association differs')
        if read(path/'config.json')!=model['config']:errors.append('Recovery saved config differs')
        left=dict(original_model['config']);right=dict(model['config']);left.pop('grant_id');right.pop('grant_id')
        if left!=right or model['config']['grant_id']!=manifest['grant_id']:errors.append('Recovery model configuration differs beyond grant')
        if normalized_command(read(om/'command.json'))!=normalized_command(read(new/'command.json')) or not command_paths_valid(read(new/'command.json'),new):errors.append('CLI permissions/configuration/isolated paths changed')
        request=read(new/'request.json');fingerprint=hashlib.sha256(((new/'prompt.txt').read_text()+'\n'+(new/'schema.json').read_text()+'\n'+json.dumps(model['config'],sort_keys=True)).encode()).hexdigest()
        if model['request_fingerprint']!=fingerprint or request['request_fingerprint']!=fingerprint or request['config']!=model['config'] or request['call_id']!=model['call_id']:errors.append('Request fingerprint/config/call identity differs')
        if model['call_id']==original_model['call_id'] or r['original_call_id']!=original_model['call_id']:errors.append('Recovery call ID linkage invalid')
        runtime=json.loads(git('show',read(old/'freeze.json')['code_commit']+':docs/runtime-environment.json'))
        if r['cli_binary_sha256']!=runtime['codex_binary_sha256']:errors.append('CLI binary hash differs from original freeze')
        if r['solver_results'] or r['costs']['solver_calls']!=0:errors.append('Recovery used solver')
        ledger=ledger_rows();res=[x for x in ledger if x.get('event')=='reserve' and x.get('call_id')==model['call_id']];fin=[x for x in ledger if x.get('event')=='finish' and x.get('call_id')==model['call_id']]
        if len(res)!=1 or len(fin)!=1:errors.append('Recovery call ledger not unique')
        else:
            if res[0]['phase']!='formal' or res[0]['grant_id']!=manifest['grant_id'] or Path(res[0]['run_id']).resolve()!=new.resolve():errors.append('Recovery ledger scope differs')
            if fin[0]['status']!=model['status'] or fin[0]['details'].get('usage')!=raw['usage'] or not close(fin[0]['details'].get('duration_seconds'),model['duration_seconds']):errors.append('Recovery ledger costs differ')
            prior=ledger[:ledger.index(res[0])];before=budget_state(prior);recorded=res[0].get('token_admission') or {}
            grants=[x for x in prior if x.get('event')=='grant' and x.get('grant_id')==manifest['grant_id']]
            if len(grants)!=1:errors.append('Recovery lacks a unique prior grant')
            else:
                g=grants[0];used=sum(x.get('event')=='reserve' and x.get('grant_id')==g['grant_id'] for x in prior)
                if g['phase']!='formal' or g['phase_limit']!=300 or g.get('phase_limit_tokens',3000000)!=3000000 or not res[0]['run_id'].startswith(g['run_prefix']) or used>=g['max_calls'] or g['max_calls']>len(manifest['eligible']):errors.append('Recovery grant admission differs')
            if r['admission']['ledger']!=before:errors.append('Admission ledger snapshot differs from actual prefix')
            if before['model_attempts']>=300 or before['reported_tokens']>=3000000 or before['unknown_completed']>=3 or before['pending']:errors.append('Recovery admitted after shared budget/pending gate')
            if recorded.get('phase_limit_tokens')!=3000000 or recorded.get('pending_before')!=0 or recorded.get('reported_tokens_before')!=before['reported_tokens'] or recorded.get('unknown_completed_before')!=before['unknown_completed']:errors.append('Recovery token admission totals differ')
        expected_calls=[x for x in ledger if x.get('event')=='reserve' and Path(x['run_id']).parent.resolve()==path.resolve()]
        if len(expected_calls)!=1 or len(list(path.glob('model_call_*')))!=1:errors.append('Recovery made more than one request')
        if any(x.get('event')=='solver_reserve' and str(path.resolve()) in x.get('run_id','') for x in ledger):errors.append('Recovery solver ledger forbidden')
        if model['status']=='success':
            if model.get('timed_out') or raw['completed_turns']!=1 or raw['native'] or not raw['finals'] or json.loads(raw['finals'][-1])!=model['output'] or read(new/'final.txt')!=model['output'] or model['returncode']!=0:errors.append('Raw final/model output chain differs')
            try:
                if not isinstance(model['output'],dict) or set(model['output'])!={'order','rationale'} or not isinstance(model['output']['rationale'],str):raise ValueError('Recovery B response schema differs')
                decoded=independent_decode(read(old/'input.json'),model['output']['order']);checked=validate(read(old/'input.json'),decoded)
            except (ValueError,KeyError,TypeError) as exc:decoded=None;checked={'valid':False,'errors':[str(exc)],'makespan':None}
            if r['status']=='success' and (not checked['valid'] or decoded!=r['schedule'] or checked!=r['validation']):errors.append('Recovery schedule/independent validation differs')
            report.update(valid=bool(checked['valid'] and r['status']=='success'),makespan=checked['makespan'] if r['status']=='success' else None)
        elif r['status']=='success':errors.append('Failed model recorded as successful recovery')
        if r['status']=='success' and (read(path/'schedule.json')!=r['schedule'] or r['actions']!=[model['output']]):errors.append('Saved action/schedule chain differs')
        cost=r['costs'];old_cost=read(old/'result.json')['costs'];logical=r['logical_costs']
        if cost['model_calls']!=1 or cost['usage']!=raw['usage'] or not close(cost['model_elapsed_seconds'],model['duration_seconds']):errors.append('Recovery aggregate model costs differ')
        if logical['model_calls']!=old_cost['model_calls']+1 or not close(logical['activity_seconds'],old_cost['end_to_end_seconds']+cost['end_to_end_seconds']):errors.append('Logical cumulative cost differs')
        combined={k:old_cost['usage'].get(k)+raw['usage'].get(k) if old_cost['usage'].get(k) is not None and raw['usage'].get(k) is not None else None for k in TOKEN_KEYS}
        if logical['usage']!=combined:errors.append('Logical unknown token accounting differs')
        if logical['model_calls']>3 or logical['activity_seconds']>1000:errors.append('Logical cumulative budget exceeded')
        if r['admission']['campaign_activity_seconds']+r['admission']['reserved_activity_margin_seconds']>14400 or r['admission']['logical_activity_seconds']+r['admission']['reserved_activity_margin_seconds']>1000:errors.append('Recovery admitted without cumulative activity room')
        if r['metrics']['makespan']!=(r['validation']['makespan'] if r['status']=='success' else None):errors.append('Failed recovery has a quality value or metric mismatch')
        start=dt.datetime.fromisoformat(r['started_at']);finish=dt.datetime.fromisoformat(r['finished_at']);old_r=read(old/'result.json')
        activity_before=0
        for folder in (ROOT/'runs').iterdir():
            if not folder.is_dir() or folder.name=='development':continue
            for file in folder.glob('*/result.json'):
                previous=read(file)
                if dt.datetime.fromisoformat(previous['finished_at'])<=start:activity_before+=previous['costs']['end_to_end_seconds']
        if not close(activity_before,r['admission']['campaign_activity_seconds']):errors.append('Campaign prior activity differs from completed records')
        if not close((finish-start).total_seconds(),cost['end_to_end_seconds'],1):errors.append('Recovery wall clock differs')
        if not close((start-dt.datetime.fromisoformat(old_r['finished_at'])).total_seconds(),r['recovery_wait_seconds'],1) or not close((finish-dt.datetime.fromisoformat(old_r['started_at'])).total_seconds(),r['calendar_span_seconds'],1):errors.append('Recovery wait/calendar span differs')
    except (OSError,ValueError,KeyError,TypeError,StopIteration,subprocess.SubprocessError) as exc:errors.append(type(exc).__name__+': '+str(exc))
    report.update(audit_pass=not errors,errors=errors);return report

def audit_all(freeze_path):
    freeze,manifest,original=load_gate(freeze_path,current_files=False);base=ROOT/'runs'/manifest['recovery_phase'];reports=[];delivery=[];expected={q['run_id']+'__channel_recovery_1':q for q in manifest['eligible']}
    for name,q in expected.items():
        path=base/name
        reports.append(audit_recovery(path,freeze,manifest) if (path/'result.json').exists() else {'run_id':name,'audit_pass':False,'valid':False,'status':'incomplete' if path.exists() else 'not_started','errors':[]})
    extras=[p.name for p in base.iterdir() if p.is_dir() and p.name not in expected] if base.exists() else []
    extras += [str(p.relative_to(ROOT)) for p in (ROOT/'runs').glob('recovery_static_*/*') if p.is_dir() and p.parent!=base and p.name in expected]
    recovered={expected[r['run_id']]['run_id']:r for r in reports if r['audit_pass'] and r['valid']}
    for cell in original['rows']:
        if cell['phase']!='acceptance_static_v1':continue
        r=read(ROOT/cell['path']/'result.json');recovery=recovered.get(r['run_id']);original_ok=r['status']=='success' and r.get('validation',{}).get('valid')
        delivery.append({'logical_run_id':r['run_id'],'original_status':r['status'],'original_path':cell['path'],'recovery_run_id':recovery['run_id'] if recovery else None,'delivery_source':'original' if original_ok else 'recovery' if recovery else None,'delivery_makespan':r['metrics']['makespan'] if original_ok else recovery.get('makespan') if recovery else None})
    return {'at':now(),'protocol_version':manifest['protocol_version'],'original_records':original['completed_cells'],'eligible_count':len(expected),'recovery_records':reports,'unexpected_recovery_directories':extras,'original_static_denominator':len(delivery),'original_static_successes':sum(x['original_status']=='success' for x in delivery),'logical_delivery':delivery,'logical_delivered':sum(x['delivery_source'] is not None for x in delivery),'acceptance_ready':len(delivery)==108 and not extras and all(x['delivery_source'] is not None for x in delivery) and all(x['audit_pass'] and x['valid'] for x in reports)}

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--freeze',type=Path,required=True);ap.add_argument('--output',type=Path,default=ROOT/'artifacts/static_recovery/audit.json');args=ap.parse_args();output=args.output.resolve()
    if ROOT/'artifacts' not in output.parents:raise ValueError('Audit output must remain under artifacts')
    result=audit_all(args.freeze);write(output,result);print(json.dumps({k:v for k,v in result.items() if k not in ('logical_delivery','recovery_records')},ensure_ascii=False));return 0 if result['acceptance_ready'] else 2

if __name__=='__main__':raise SystemExit(main())
