#!/usr/bin/env python3
"""Independent final version review: Git, frozen bytes and 180+1 run bindings.
Only reads evidence and Git; never imports replay, model, solver or simulation.
Writes its own QA JSON, preserving every frozen material and original report.
"""
from __future__ import annotations
import argparse,copy,datetime as dt,hashlib,json,subprocess,time
from collections import Counter
from functools import lru_cache
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ORIGINAL_FREEZES=('configs/freezes/static-v1.json','configs/freezes/static-aux-v2.json','configs/freezes/smt-v1.json','configs/freezes/smt-aux-v1.json')
RECOVERY_FREEZE='progress/freezes/static-channel-recovery-v1.json'
EXPECTED_RECOVERY_COMMIT='c6c37905cf512c208d48521664ab3386a8772abe'
EXPECTED_COUNTS={'acceptance_static_v1':108,'auxiliary_static_v1':36,'acceptance_smt_v1':27,'auxiliary_smt_v1':9}


def sha(data):return hashlib.sha256(data).hexdigest()
def object_sha(value):return sha(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode())
def read(path):return json.loads(Path(path).read_text())
def checked_path(relative):
    p=Path(relative)
    if p.is_absolute() or '..' in p.parts:raise ValueError('Unsafe relative path: '+str(relative))
    resolved=(ROOT/p).resolve()
    if ROOT not in resolved.parents:raise ValueError('Path outside experiment: '+str(relative))
    return resolved
@lru_cache(maxsize=None)
def file_sha(path):return sha(Path(path).read_bytes())
@lru_cache(maxsize=None)
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,stderr=subprocess.PIPE)
@lru_cache(maxsize=None)
def git_file_sha(commit,relative):return sha(git('show',commit+':'+relative))
def issue(errors,condition,message):
    if not condition:errors.append(message)

def frozen_review(relative):
    errors=[];report={'path':relative,'errors':errors,'pass':False};f=None
    try:
        path=checked_path(relative);f=read(path);commit=f['code_commit'];report.update(tag=f['tag'],code_commit=commit,manifest_sha256=file_sha(path),file_count=len(f['files']))
        issue(errors,git('cat-file','-t',commit).strip()==b'commit','code_commit is not a Git commit')
        report['tag_object_type']=git('cat-file','-t',f['tag']).decode().strip()
        issue(errors,git('rev-parse',f['tag']+'^{commit}').decode().strip()==commit,'tag points to a different commit')
        files=[]
        for rel,expected in sorted(f['files'].items()):
            row={'path':rel,'frozen_sha256':expected}
            try:
                actual=file_sha(checked_path(rel));committed=git_file_sha(commit,rel);row.update(current_sha256=actual,commit_sha256=committed,**{'pass':actual==expected==committed})
                issue(errors,row['pass'],'frozen/current/Git byte mismatch: '+rel)
            except (OSError,ValueError,subprocess.SubprocessError) as exc:row.update(error=str(exc),**{'pass':False});errors.append('cannot verify frozen file '+rel+': '+str(exc))
            files.append(row)
        report['files']=files
        data=f.get('source_data',{})
        if data:
            actual={str(p.relative_to(ROOT)):file_sha(p) for p in sorted((ROOT/'data/smt/SMT2020_LVHM').iterdir()) if p.is_file()}
            issue(errors,actual==data,'SMT external source data inventory/hash differs')
            report['external_source_files']=len(actual)
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:errors.append(type(exc).__name__+': '+str(exc))
    report['pass']=not errors;return f,report

def snapshot_review(path,expected,errors):
    folder=path/'source_snapshot';actual={str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file()} if folder.exists() else set()
    issue(errors,actual==set(expected),'source_snapshot inventory differs from required version files')
    for rel,expected_sha in expected.items():
        try:issue(errors,file_sha(folder/rel)==expected_sha,'source_snapshot SHA differs: '+rel)
        except OSError:errors.append('source_snapshot file missing: '+rel)
    return len(actual)

def original_run_review(f,cell):
    item,arm,repeat=cell;smt=f.get('dataset')=='smt2020';run_id=f'smt{item}_{arm}_r{repeat}' if smt else f'{item}_{arm}_r{repeat}'
    path=ROOT/'runs'/f['phase']/run_id;errors=[];out={'phase':f['phase'],'run_id':run_id,'path':str(path.relative_to(ROOT)),'errors':errors,'pass':False}
    try:
        r=read(path/'result.json');cfg=read(path/'config.json');started=read(path/'started.json');saved_freeze=read(path/'freeze.json')
        out.update(status=r['status'],code_commit=r.get('code_commit'),freeze_tag=r.get('freeze_tag'),result_sha256=file_sha(path/'result.json'))
        issue(errors,saved_freeze==f,'run freeze.json differs from selected frozen manifest')
        issue(errors,r.get('freeze_manifest_sha256')==file_sha(path/'freeze.json'),'run freeze_manifest_sha256 differs from saved bytes')
        for key,value in {'phase':f['phase'],'run_id':run_id,'arm':arm,'repeat':repeat,'code_commit':f['code_commit'],'freeze_tag':f['tag'],'protocol_version':f['protocol_version']}.items():issue(errors,r.get(key)==value,'root '+key+' differs from frozen identity')
        issue(errors,r.get('scenario' if smt else 'instance_id')==item,'frozen scenario/instance identity differs')
        identity={'arm':arm,'repeat':repeat,'scenario' if smt else 'instance_id':item,'config_sha256':r['config_sha256']}
        if not smt:identity['data_sha256']=r['data_sha256']
        issue(errors,r.get('identity')==identity,'root identity object differs')
        expected_cfg=json.loads(git('show',f['code_commit']+':'+f['config_path']));expected_cfg['model']['phase']='formal';expected_cfg['seed']=(11,22,33)[repeat-1]
        issue(errors,cfg==expected_cfg,'effective config differs from committed configuration plus fixed repeat seed')
        issue(errors,object_sha(cfg)==r['config_sha256']==f['effective_config_sha256'][str(repeat)],'effective configuration SHA binding differs')
        if smt:issue(errors,r.get('config_path')==f['config_path'],'SMT config_path differs')
        expected_sources={rel:value for rel,value in f['files'].items() if Path(rel).parts[0] in ('src','prompts','configs','tests')}
        issue(errors,r.get('source_sha256')==expected_sources,'source_sha256 inventory differs from frozen execution-source subset')
        out['source_snapshot_files']=snapshot_review(path,expected_sources,errors)
        for key in ('identity','code_commit','source_sha256','config_sha256','data_sha256','protocol_version','freeze_manifest_sha256'):
            issue(errors,started.get(key)==r.get(key),'started/root provenance differs: '+key)
        if smt:
            manifest=read(path/'input_manifest.json');bound={'data/smt/SMT2020_LVHM/'+name:value for name,value in manifest['data_hashes'].items()}
            issue(errors,bound==f['source_data'],'input manifest source-data binding differs')
            issue(errors,object_sha(manifest['data_hashes'])==r['data_sha256'],'SMT data_sha256 differs')
            issue(errors,manifest['seed']==item and manifest['horizon']==cfg['window_seconds'] and sorted(manifest['controlled_machine_ids'])==sorted(cfg['controlled_machine_ids']),'SMT scenario/window/control binding differs')
            for key,mkey in (('adapter_version','version'),('window_seconds','horizon'),('warmup_seconds','warmup_seconds'),('outside_policy','outside_policy')):
                issue(errors,r.get(key)==manifest[mkey] and started.get(key)==r.get(key),'SMT started/root/input mismatch: '+key)
        else:
            problem=read(path/'input.json');committed_problem=json.loads(git('show',f['code_commit']+f':data/fjsp/instances/{item}.json'))
            issue(errors,problem==committed_problem and object_sha(problem)==r['data_sha256'],'static input differs from committed instance/data_sha256')
    except (OSError,ValueError,KeyError,TypeError,IndexError,subprocess.SubprocessError) as exc:errors.append(type(exc).__name__+': '+str(exc))
    out['pass']=not errors;return out

def recovery_review(f,original_freezes,original_runs):
    errors=[];out={'errors':errors,'pass':False,'runs':[],'audit_links':[]}
    try:
        issue(errors,f['code_commit']==EXPECTED_RECOVERY_COMMIT,'recovery commit differs from required c6c3790')
        manifest_path=checked_path(f['manifest_path']);m=read(manifest_path)
        issue(errors,f['files'].get(f['manifest_path'])==file_sha(manifest_path),'recovery manifest itself is not frozen')
        original_files=original_freezes['configs/freezes/static-v1.json']['files']
        added={'docs/PROTOCOL_STATIC_CHANNEL_RECOVERY_v1.md',f['manifest_path'],'scripts/recover_static_channel.py','scripts/audit_static_recovery.py'}
        issue(errors,len(original_files)==72 and len(f['files'])==76 and set(f['files'])==set(original_files)|added,'recovery source scope is not exactly 72 original static + 4 recovery files')
        issue(errors,all(f['files'].get(rel)==value for rel,value in original_files.items()),'recovery changed an original static frozen file SHA')
        expected_results={r['path']+'/result.json':r.get('result_sha256') for r in original_runs}
        issue(errors,len(expected_results)==180 and m['original_total_cells']==180 and m['original_results_sha256']==expected_results,'manifest complete 180 original result byte binding differs')
        links={x['path']:x['sha256'] for x in m['original_freezes']}
        issue(errors,set(links)==set(ORIGINAL_FREEZES),'manifest does not bind exactly four original freezes')
        for rel,value in links.items():issue(errors,file_sha(checked_path(rel))==value==git_file_sha(f['code_commit'],rel),'original freeze SHA/Git binding differs: '+rel)
        issue(errors,set(m['original_audits'])==set(EXPECTED_COUNTS),'manifest does not bind all four final original audits')
        for phase,link in m['original_audits'].items():
            path=checked_path(link['path']);a=read(path);current=file_sha(path);committed=git_file_sha(f['code_commit'],link['path'])
            row={'phase':phase,'path':link['path'],'manifest_sha256':link['sha256'],'current_sha256':current,'recovery_commit_sha256':committed,'copied_into_runtime_snapshot':False}
            row['pass']=link['sha256']==current==committed;issue(errors,row['pass'],'original final audit SHA/Git binding differs: '+phase)
            entries=a.get('runs',[])+a.get('auxiliary_runs',[]);expected={r['run_id'] for r in original_runs if r['phase']==phase}
            issue(errors,a.get('phase')==phase and a.get('coverage_complete') is True and not a.get('phase_errors') and {r['run_id'] for r in entries}==expected,'bound original audit coverage/phase differs: '+phase)
            issue(errors,all(r.get('audit_pass') is True and r.get('provenance_complete') is True for r in entries),'bound original audit reports a provenance/evidence error: '+phase)
            for r in entries:
                for key in ('result_sha256','result_sha'):
                    if key in r:issue(errors,r[key]==expected_results[f'runs/{phase}/{r["run_id"]}/result.json'],'saved audit result SHA differs: '+phase+'/'+r['run_id'])
            out['audit_links'].append(row)
        issue(errors,len(m['eligible'])==1 and m['eligible'][0]['run_id']=='mk08_B_r1','final recovery manifest is not the one recorded mk08_B_r1 failure')
        base=ROOT/'runs'/m['recovery_phase'];expected_dirs={e['run_id']+'__channel_recovery_1' for e in m['eligible']}
        issue(errors,{p.name for p in base.iterdir() if p.is_dir()}==expected_dirs,'recovery directory coverage differs')
        for entry in m['eligible']:
            run_id=entry['run_id']+'__channel_recovery_1';path=base/run_id;local=[];r=read(path/'result.json');claim=read(path/'claim.json');old=ROOT/'runs'/entry['phase']/entry['run_id'];old_result=read(old/'result.json')
            model=read(path/'model_call_001/result.json');old_model=read(old/'agent/model_call_001/result.json');cfg=read(path/'config.json')
            row={'run_id':run_id,'path':str(path.relative_to(ROOT)),'status':r['status'],'code_commit':r.get('code_commit'),'freeze_tag':r.get('freeze_tag'),'result_sha256':file_sha(path/'result.json'),'errors':local}
            issue(local,r['code_commit']==f['code_commit'] and r['freeze_tag']==f['tag'],'recovery root Git identity differs')
            issue(local,read(path/'freeze.json')==f and file_sha(path/'freeze.json')==r['freeze_manifest_sha256'],'recovery saved freeze binding differs')
            issue(local,r['phase']==m['recovery_phase'] and r['protocol_version']==m['protocol_version'] and r['run_id']==run_id,'recovery manifest identity differs')
            issue(local,r['original']==entry==read(path/'original_link.json'),'recovery original link differs')
            issue(local,r['original_phase']==entry['phase'] and r['original_run_id']==entry['run_id'] and r['original_call_id']==entry['original_call_id']==old_model['call_id'],'recovery original call identity differs')
            issue(local,file_sha(old/'result.json')==entry['original_result_sha256'] and old_result['status']=='failed' and r['original_outcome_unchanged'] is True,'original failure changed or reclassified')
            for rel,value in entry['evidence_sha256'].items():
                file=old/rel;actual=file_sha(file) if file.exists() else None;issue(local,actual==value,'recovery eligible original evidence SHA differs: '+rel)
            row['source_snapshot_files']=snapshot_review(path,f['files'],local)
            for link in m['original_audits'].values():issue(local,not (path/'source_snapshot'/link['path']).exists(),'original final audit unexpectedly copied into evaluated recovery snapshot')
            for key in ('original','original_call_id','started_at','code_commit','freeze_tag','freeze_manifest_sha256','cli_binary_sha256','admission'):
                issue(local,claim.get(key)==r.get(key),'recovery claim/root binding differs: '+key)
            issue(local,(path/'input.json').read_bytes()==(old/'input.json').read_bytes(),'recovery input copy differs')
            expected_cfg={**old_model['config'],'grant_id':m['grant_id']}
            issue(local,cfg==model['config']==expected_cfg,'recovery model config differs beyond explicit grant')
            issue(local,model['call_id']!=old_model['call_id'],'recovery reused original call ID')
            runtime=json.loads(git('show',old_result['code_commit']+':docs/runtime-environment.json'))
            issue(local,r['cli_binary_sha256']==runtime['codex_binary_sha256'],'recovery CLI binary SHA differs from original runtime pin')
            row.update(original_run_id=entry['run_id'],original_status=old_result['status'],config_sha256_derived=object_sha(cfg),input_sha256_derived=object_sha(read(path/'input.json')),pass_=not local)
            row['pass']=row.pop('pass_');out['runs'].append(row);errors.extend(run_id+': '+x for x in local)
        out.update(manifest_path=f['manifest_path'],manifest_sha256=file_sha(manifest_path),original_result_bindings=len(expected_results),runtime_snapshot_policy=m.get('audit_snapshot_policy'),recovery_source_files=len(f['files']))
    except (OSError,ValueError,KeyError,TypeError,IndexError,subprocess.SubprocessError) as exc:errors.append(type(exc).__name__+': '+str(exc))
    out['pass']=not errors;return out

def review():
    begun=time.process_time();freezes={};reports=[];run_reports=[];errors=[]
    for relative in ORIGINAL_FREEZES:
        frozen,report=frozen_review(relative);reports.append(report)
        if frozen is None:continue
        freezes[relative]=frozen
        expected_count=EXPECTED_COUNTS[frozen['phase']]
        issue(report['errors'],len(frozen['matrix'])==expected_count and len({tuple(x) for x in frozen['matrix']})==expected_count,'original frozen matrix count/uniqueness differs')
        expected_ids={f'smt{x}_{a}_r{r}' if frozen.get('dataset')=='smt2020' else f'{x}_{a}_r{r}' for x,a,r in frozen['matrix']}
        paths={p.name for p in (ROOT/'runs'/frozen['phase']).iterdir() if p.is_dir()}
        issue(report['errors'],paths==expected_ids,'original run directory set differs from frozen matrix')
        for cell in frozen['matrix']:run_reports.append(original_run_review(frozen,cell))
        report['pass']=not report['errors']
    recovered,frozen_report=frozen_review(RECOVERY_FREEZE);reports.append(frozen_report)
    recovery=recovery_review(recovered,freezes,run_reports) if recovered else {'pass':False,'errors':['Recovery freeze unavailable'],'runs':[]}
    for report in reports:errors.extend(report['path']+': '+x for x in report['errors'])
    for report in run_reports:errors.extend(report['path']+': '+x for x in report['errors'])
    errors.extend('recovery: '+x for x in recovery['errors'])
    issue(errors,len(run_reports)==180 and len(recovery.get('runs',[]))==1,'must review exactly 180 original + 1 recovery records')
    return {'schema_version':'final-freeze-review-1','at':dt.datetime.now(dt.timezone.utc).isoformat(),'scope':'Independent version and byte-binding review only; no feasibility/quality rerun and no new model, solver or simulation.',
            'review_script_sha256':file_sha(Path(__file__).resolve()),'cpu_seconds':time.process_time()-begun,'pass':not errors,'errors':errors,'freeze_reviews':reports,
            'original_run_count':len(run_reports),'original_run_passed':sum(r['pass'] for r in run_reports),'original_status_counts':dict(Counter(r.get('status','unreadable') for r in run_reports)),
            'original_runs':run_reports,'recovery':recovery,'notes':['Original v1 failure remains failed; recovery is a separately versioned delivery.','The four original final audit JSON bodies are hash-bound through the committed recovery manifest and Git, not part of its 76-file runtime source_snapshot.']}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=ROOT/'artifacts/final/qa/freeze_git_review.json');args=parser.parse_args();output=args.output.resolve()
    if output!=ROOT/'artifacts/final/qa/freeze_git_review.json':raise ValueError('This review writes only its own authorized QA artifact')
    result=review();output.parent.mkdir(parents=True,exist_ok=True);temp=output.with_suffix('.json.tmp');temp.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n');temp.replace(output)
    print(json.dumps({k:result[k] for k in ('pass','cpu_seconds','original_run_count','original_run_passed','original_status_counts','errors')},ensure_ascii=False));return 0 if result['pass'] else 1

if __name__=='__main__':raise SystemExit(main())
