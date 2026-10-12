#!/usr/bin/env python3
"""Prepare or execute one post-hoc, exact-request B channel recovery per eligible cell.

Default --inspect is read-only and NEVER invokes a model. --execute requires a
committed protocol/complete eligibility manifest, its tagged freeze, all 180
original cells finished, saved original phase audit, and an explicit remaining
formal grant. Do not use until the main agent has reviewed and authorized it.
"""
from __future__ import annotations
import argparse,dataclasses,datetime as dt,fcntl,json,shutil,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
import audit_static_recovery as audit
from src.agents.model_transport import ModelConfig,call_model,build_command,BASE_INSTRUCTIONS
from src.agents.static import decode_order
from src.fjsp.validator import validate


def preflight(freeze,manifest,entry,out):
    for prior in (ROOT/'runs').glob('recovery_static_*/*'):
        if prior.is_dir() and prior.name==entry['run_id']+'__channel_recovery_1' and prior.resolve()!=out.resolve():raise ValueError('A recovery opportunity already exists for this logical cell')
    original=ROOT/'runs'/entry['phase']/entry['run_id'];old=original/'agent/model_call_001';m=audit.read(old/'result.json');cfg=ModelConfig(**{**m['config'],'grant_id':manifest['grant_id']})
    if cfg.phase!='formal' or Path(cfg.ledger_path).resolve()!=ROOT/'progress/model_ledger.jsonl':raise ValueError('Must reuse original formal ledger')
    if cfg.model!='gpt-6-astra' or cfg.reasoning_effort!='medium' or cfg.timeout_seconds!=300:raise ValueError('Unexpected original runtime settings')
    original_freeze=audit.read(original/'freeze.json')
    for rel in ('src/agents/model_transport.py','src/agents/budget.py','src/agents/static.py','src/fjsp/validator.py','src/__init__.py','src/agents/__init__.py','src/fjsp/__init__.py'):
        if audit.digest(ROOT/rel)!=original_freeze['files'][rel]:raise ValueError('Original transport/decoder/validator implementation changed')
    runtime_bytes=audit.git('show',original_freeze['code_commit']+':docs/runtime-environment.json')
    import hashlib
    if hashlib.sha256(runtime_bytes).hexdigest()!=original_freeze['files']['docs/runtime-environment.json']:raise ValueError('Original runtime manifest hash differs')
    runtime=json.loads(runtime_bytes)
    if runtime['codex_binary']!=cfg.codex_binary:raise ValueError('Original runtime binary path differs')
    binary_sha=audit.digest(Path(cfg.codex_binary))
    if binary_sha!=runtime['codex_binary_sha256']:raise ValueError('CLI binary changed; same-request recovery refused')
    prompt=(old/'prompt.txt').read_bytes().decode('utf-8');schema=audit.read(old/'schema.json')
    if (json.dumps(schema,ensure_ascii=False,indent=2)+'\n').encode()!=(old/'schema.json').read_bytes():raise ValueError('Original schema cannot be reproduced byte-for-byte')
    if BASE_INSTRUCTIONS.encode()!=(old/'system-instructions.txt').read_bytes():raise ValueError('System instructions changed')
    new_command={'argv':build_command(out/'model_call_001',cfg),'stdin':'prompt.txt','proxy':cfg.proxy}
    if audit.normalized_command(new_command)!=audit.normalized_command(audit.read(old/'command.json')):raise ValueError('Original CLI tools/permissions/settings changed')
    ledger=audit.ledger_rows();budget=audit.budget_state(ledger);activity=audit.campaign_activity()
    grants=[g for g in ledger if g.get('event')=='grant' and g.get('grant_id')==manifest['grant_id']]
    if len(grants)!=1:raise ValueError('No unique explicitly allocated recovery grant')
    grant=grants[0];used=sum(x.get('event')=='reserve' and x.get('grant_id')==manifest['grant_id'] for x in ledger)
    if grant['phase']!='formal' or grant['phase_limit']!=300 or grant.get('phase_limit_tokens',3000000)!=3000000:raise ValueError('Recovery grant may not reset or expand formal budget')
    if not str(out/'model_call_001').startswith(grant['run_prefix']):raise ValueError('Recovery call outside explicit grant')
    if grant['max_calls']>len(manifest['eligible']) or grant['max_calls']-used>300-budget['model_attempts']:raise ValueError('Recovery grant exceeds eligible or remaining quota')
    if used>=grant['max_calls'] or budget['model_attempts']>=300 or budget['reported_tokens']>=3000000 or budget['unknown_completed']>=3 or budget['pending'] or budget['solver_requested_seconds']>4500:raise ValueError('Shared formal resource admission stopped')
    original_calls=[x for x in ledger if x.get('event')=='reserve' and Path(x['run_id']).parent.parent.resolve()==original.resolve()]
    if len(original_calls)!=1 or original_calls[0]['call_id']!=entry['original_call_id']:raise ValueError('Original logical attempt accounting differs')
    # Keep the original 300-second timeout; refuse rather than silently shortening it.
    reserve_seconds=cfg.timeout_seconds+25
    if entry['original_activity_seconds']+reserve_seconds>1000 or activity+reserve_seconds>14400:raise ValueError('Insufficient cumulative activity budget for unchanged timeout and cleanup')
    return cfg,prompt,schema,binary_sha,{'ledger':budget,'campaign_activity_seconds':activity,'logical_activity_seconds':entry['original_activity_seconds'],'logical_model_calls':len(original_calls),'reserved_activity_margin_seconds':reserve_seconds,'grant':grant}

def execute_one(freeze,manifest,entry,out):
    started=audit.now();begun=time.monotonic()
    cfg,prompt,schema,binary_sha,admission=preflight(freeze,manifest,entry,out)
    # mkdir is exclusive; claim prevents a crash from triggering another fresh attempt.
    out.mkdir(parents=True,exist_ok=False);old=ROOT/'runs'/entry['phase']/entry['run_id'];original=audit.read(old/'result.json')
    base={'run_id':out.name,'phase':manifest['recovery_phase'],'family':original['family'],'instance_id':original['instance_id'],'arm':'B','repeat':original['repeat'],
          'protocol_version':manifest['protocol_version'],'posthoc_reliability_recovery':True,'original_phase':entry['phase'],'original_run_id':entry['run_id'],'original_call_id':entry['original_call_id'],'original':entry,
          'started_at':started,'code_commit':freeze['code_commit'],'freeze_tag':freeze['tag'],'cli_binary_sha256':binary_sha,'admission':admission,
          'original_outcome_unchanged':True,'solver_results':[],'actions':[],'schedule':None,'validation':{'valid':False,'errors':['No recovered schedule'],'makespan':None}}
    audit.write(out/'freeze.json',freeze);base['freeze_manifest_sha256']=audit.digest(out/'freeze.json');audit.write(out/'claim.json',base)
    for rel in freeze['files']:
        target=out/'source_snapshot'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/rel,target)
    audit.write(out/'original_link.json',entry);audit.write(out/'config.json',dataclasses.asdict(cfg));shutil.copyfile(old/'input.json',out/'input.json')
    model=None;status='failed';failure=None
    try:
        # Exactly one call; no retry, feedback, solver, fallback or candidate selection.
        model=call_model(prompt,schema,out/'model_call_001',cfg)
        if model['status']!='success':status=model['status'];failure=model.get('failure_reason')
        else:
            base['actions']=[model['output']]
            try:
                if set(model['output'])!={'order','rationale'} or not isinstance(model['output']['rationale'],str):raise ValueError('B response schema fields differ')
                schedule=decode_order(audit.read(old/'input.json'),model['output']['order']);checked=validate(audit.read(old/'input.json'),schedule)
                base.update(schedule=schedule,validation=checked)
                if checked['valid']:status='success';audit.write(out/'schedule.json',schedule)
                else:failure='invalid_recovery_schedule'
            except (ValueError,KeyError,TypeError) as exc:failure='invalid_recovery_output: '+str(exc)
    except Exception as exc:failure=type(exc).__name__+': '+str(exc)
    finished=audit.now();elapsed=time.monotonic()-begun
    if elapsed+entry['original_activity_seconds']>1000:status='failed';failure='cumulative_activity_budget_exceeded'
    usage=model['usage'] if model else {k:None for k in audit.TOKEN_KEYS};old_usage=original['costs']['usage']
    costs={'end_to_end_seconds':elapsed,'model_calls':1 if model else None,'model_elapsed_seconds':model['duration_seconds'] if model else None,'usage':usage,'solver_calls':0,'solver_budget_seconds':0,'solver_wall_seconds':0,'cost_usd':None}
    logical={'model_calls':original['costs']['model_calls']+1 if model else None,'activity_seconds':entry['original_activity_seconds']+elapsed,
             'usage':{k:old_usage.get(k)+usage.get(k) if old_usage.get(k) is not None and usage.get(k) is not None else None for k in audit.TOKEN_KEYS}}
    result={**base,'finished_at':finished,'status':status,'failure_type':failure,'model_result':model,'costs':costs,'logical_costs':logical,
            'recovery_wait_seconds':(dt.datetime.fromisoformat(started)-dt.datetime.fromisoformat(original['finished_at'])).total_seconds(),
            'calendar_span_seconds':(dt.datetime.fromisoformat(finished)-dt.datetime.fromisoformat(original['started_at'])).total_seconds(),
            'first_attempt_latency_seconds':original['costs']['end_to_end_seconds'],'metrics':{'makespan':base['validation']['makespan'] if status=='success' else None}}
    audit.write(out/'result.json',result)
    checked=audit.audit_recovery(out,freeze,manifest);audit.write(out/'audit.json',checked)
    return result,checked

def execute(freeze_path):
    # Same lock as src.batch: no overlap with any original formal run or other recovery.
    with (ROOT/'progress/formal_execution.lock').open('a') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        freeze,manifest,original=audit.load_gate(freeze_path)
        base=ROOT/'runs'/manifest['recovery_phase'];records=[]
        for entry in manifest['eligible']:
            out=base/(entry['run_id']+'__channel_recovery_1')
            if out.exists():
                if not (out/'result.json').exists():raise RuntimeError('Interrupted recovery preserved; no fresh attempt: '+out.name)
                checked=audit.audit_recovery(out,freeze,manifest)
                if not checked['audit_pass']:raise RuntimeError('Existing recovery evidence fails audit: '+out.name)
                records.append(checked);continue
            result,checked=execute_one(freeze,manifest,entry,out);records.append(checked)
            if not checked['audit_pass']:raise RuntimeError('Recovery evidence audit failed; stop before further requests')
        summary=audit.audit_all(freeze_path);audit.write(ROOT/'artifacts/static_recovery/audit.json',summary)
        return summary

def main():
    ap=argparse.ArgumentParser(description=__doc__);mode=ap.add_mutually_exclusive_group();mode.add_argument('--inspect',action='store_true');mode.add_argument('--execute',action='store_true');ap.add_argument('--freeze',type=Path);ap.add_argument('--output',type=Path);args=ap.parse_args()
    if args.execute:
        if args.freeze is None:ap.error('--execute requires a tagged recovery --freeze')
        result=execute(args.freeze)
    else:result=audit.inspect_originals()
    if args.output:
        output=args.output.resolve()
        if ROOT/'artifacts' not in output.parents:raise ValueError('Inspection output must remain under artifacts')
        audit.write(output,result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('rows','logical_delivery')},ensure_ascii=False))
    return 0

if __name__=='__main__':raise SystemExit(main())
