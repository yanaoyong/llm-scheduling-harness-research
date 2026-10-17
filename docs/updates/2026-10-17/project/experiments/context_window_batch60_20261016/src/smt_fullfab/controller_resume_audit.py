"""Independent saved-evidence audit for B recovery segments.

No runtime controller, transport, budget manager, environment or optimizer is
imported. Preparation alone never certifies execution or a complete experiment.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import math
from pathlib import Path

from .controller_audit import (audit_controller, digest, sha_file, _record_digest,
    _audit_ledger_admission, _schema_errors, _literal_prompt_constants,
    _strict_prompt_sections, _verify_pages, _crop)

VERSION='smt-fullfab-B-recovery-evidence-audit-v2'


def _page_errors(problem,page,response,staged,holds,schema,index,count,end):
    errors=_schema_errors(response,schema)
    if errors:return errors
    allowed={row[0] for group in page for row in group['operations']}
    outside=sorted({oid for task in response['tasks'] for oid in task['operations'] if oid not in allowed})
    if outside:errors.append('patch references operations outside the supplied page: '+json.dumps(outside))
    if response['commit']!=(index==count-1):
        errors.append('explicit commit before all pages' if response['commit'] else 'final page lacks explicit commit')
    operations={op['operation_id']:op for op in problem['operations']}
    machines={m['machine'] for m in problem['machines']};used=set();sequences=set();hold_keys=set()
    for task in staged+response['tasks']:
        mid,start,seq=task['machine'],task['start'],task['sequence']
        if type(mid)is not int or mid not in machines or type(start) not in (int,float) or not math.isfinite(start) or start<problem['time']:
            errors.append('invalid explicit machine/start')
        if type(seq)is not int or (mid,seq) in sequences:errors.append('repeated or invalid explicit machine sequence')
        sequences.add((mid,seq));selected=[]
        if not isinstance(task['operations'],list) or not task['operations']:
            errors.append('empty or invalid explicit batch');continue
        for oid in task['operations']:
            if oid not in operations:errors.append('unknown operation: '+str(oid));continue
            if oid in used:errors.append('duplicate operation: '+oid)
            used.add(oid);selected.append(operations[oid])
        if selected:
            if any(mid not in op['eligible_machines'] for op in selected):errors.append('ineligible explicit machine')
            if any(op['batch_key']!=selected[0]['batch_key'] for op in selected):errors.append('incompatible explicit batch')
            if not selected[0]['batch_min']<=len(selected)<=selected[0]['batch_max']:errors.append('explicit batch min/max')
    for hold in holds+response['holds']:
        mid,until,after=hold['machine'],hold['until'],hold.get('after_sequence')
        if type(mid)is not int or mid not in machines or type(until) not in (int,float) or not math.isfinite(until) or not problem['time']<until<=end:
            errors.append('invalid explicit hold machine/time')
        if not isinstance(hold['reason'],str):errors.append('invalid hold reason')
        if after is not None and (type(after)is not int or (mid,after) not in sequences):
            errors.append('hold after_sequence is not in already chosen tasks; explicit model revision required')
        if (mid,after) in hold_keys:errors.append('duplicate explicit hold key requires model revision')
        hold_keys.add((mid,after))
    return sorted(set(errors))


def _decode(problem,tasks,holds,reason,version):
    ordered=sorted(tasks,key=lambda task:(task['machine'],task['sequence']))
    ops={op['operation_id']:op for op in problem['operations']};decoded=[];waiting=[]
    for index,task in enumerate(ordered):
        selected=[ops[oid] for oid in task['operations']]
        decoded.append({'id':str(index),'machine':task['machine'],'lot_ids':[o['lot_id'] for o in selected],
            'steps':[o['step'] for o in selected],'visits':[o['visit'] for o in selected],
            'operation_ids':task['operations'],'not_before':task['start']})
    for hold in holds:
        item={k:v for k,v in hold.items() if k!='after_sequence'}
        if hold.get('after_sequence') is not None:
            item['after_task_id']=str(next(i for i,t in enumerate(ordered) if t['machine']==hold['machine'] and t['sequence']==hold['after_sequence']))
        waiting.append(item)
    return {'version':version,'created_at':problem['time'],'valid_until':problem['horizon_end'],'freeze_until':problem['time'],
            'reason':reason,'scope':problem['scope'],'tasks':decoded,'holds':waiting}


def _feedback(index,cid,output,errors):
    return {'revision_scope':'replace_this_page_only','page_index':index,'rejected_call_id':cid,
            'rejected_output_sha256':digest(output),'rejected_output':output,'validation_errors':errors,
            'instruction':'Return a fresh complete patch for this page; do not edit prior accepted pages.'}


def _registered_physical_horizon(registration, trace):
    """Validate the registered endpoint, preserving the recorded JSON number type.

    runner.crop_plan uses env.horizon, whose exact representation is recorded in
    the initial manifest. Numeric equality alone is insufficient for hash parity;
    do not coerce other plan values or globally normalize numeric JSON values.
    """
    if not isinstance(registration, dict):
        raise ValueError('missing original window registration')
    if (not isinstance(trace, list) or not trace or not isinstance(trace[0], dict)
            or trace[0].get('kind') != 'initial'
            or not isinstance(trace[0].get('manifest'), dict)):
        raise ValueError('missing original physical initial manifest')
    registered = registration.get('window_seconds')
    recorded = trace[0]['manifest'].get('horizon')
    for name, value in (('registered window', registered), ('physical horizon', recorded)):
        if (type(value) not in (int, float) or value <= 0
                or (type(value) is float and not math.isfinite(value))):
            raise ValueError(name + ' must be a positive finite JSON number')
    if registered != recorded:
        raise ValueError('physical horizon differs from original registered window')
    return recorded


def audit_controller_resume(segment_dir,ledger_path=None):
    segment=Path(segment_dir).resolve();errors=[];missing=[];evidence={};parent_audit=None;physical=None
    checked=0;accepted_count=0;rejected_count=0;checked_plans=0;result={};mapping={}
    def check(ok,message):
        if not ok:errors.append(message)
    def read(path,lines=False,optional=False):
        path=Path(path)
        if not path.exists():
            if not optional:missing.append(str(path))
            return [] if lines else None
        evidence[str(path)]=sha_file(path)
        raw=path.read_text()
        return [json.loads(line) for line in raw.splitlines() if line.strip()] if lines else json.loads(raw)
    def inventory(path):
        answer={}
        for p in sorted(path.rglob('*')):
            check(not p.is_symlink(),'symbolic link in evidence: '+str(p))
            if p.is_file():answer[str(p.relative_to(path))]={'sha256':sha_file(p),'bytes':p.stat().st_size}
        return answer
    try:
        result=read(segment/'result.json') or {};cfg=read(segment/'config.json') or {}
        mapping=read(segment/'recovery_mapping.json') or {};package=read(segment/'recovery_package.json') or {}
        parent=Path(mapping['parent_run_id']).resolve()
        check(str(segment)==mapping['segment_run_id'],'segment directory differs from immutable mapping')
        check(result.get('identity')==digest(cfg) and result.get('config')==cfg,'segment result/config identity mismatch')
        for key in ('parent_run_id','segment_run_id','recovery_segment_id','registration_id'):
            check(result.get(key)==mapping[key],'result recovery identity mismatch: '+key)
        check(mapping['recovery_segment_id']==_record_digest({k:v for k,v in mapping.items() if k!='recovery_segment_id'}),'mapping hash mismatch')
        check(package.get('package_sha256')==_record_digest({k:v for k,v in package.items() if k!='package_sha256'}),'preparation package hash mismatch')
        check(package.get('package_sha256')==mapping['package_identity_sha256'] and package.get('parent_run')==str(parent),'mapping refers to another package/parent')
        original_package=read(mapping['recovery_package_path'])
        check(original_package==package and sha_file(mapping['recovery_package_path'])==mapping['recovery_package_sha256'],'original preparation artifact changed')
        check(inventory(parent)==package.get('parent_evidence'),'sealed parent evidence changed')
        ledger_path=Path(ledger_path or package['ledger_prefix']['path']).resolve();ledger=read(ledger_path,lines=True)
        raw_ledger=ledger_path.read_bytes();prefix=package['ledger_prefix'];raw_prefix=raw_ledger[:prefix['bytes']]
        check(str(ledger_path)==prefix['path'] and len(raw_prefix)==prefix['bytes'] and hashlib.sha256(raw_prefix).hexdigest()==prefix['sha256'],'original ledger byte prefix changed')
        prefix_rows=[json.loads(line) for line in raw_prefix.splitlines() if line.strip()]
        check(len(prefix_rows)==prefix['records'] and _record_digest(prefix_rows)==prefix['canonical_sha256'],'original ledger logical prefix changed')
        approvals=[r['approval'] for r in ledger if r.get('event')=='approval']
        if len(approvals)!=1:raise ValueError('unique original approval missing')
        replay=_audit_ledger_admission(ledger,approvals[0]);errors.extend(replay['errors']);missing.extend(replay['missing_evidence'])
        check(replay['recovery_mappings'].get(str(segment))==mapping,'saved mapping differs from effective ledger mapping')
        finish=replay['recovery_closures'].get(str(segment))
        if finish is None:missing.append('authoritative recovery_segment_finished event')
        else:
            check(finish['result_sha256']==sha_file(segment/'result.json') and finish['result_path']==str(segment/'result.json'),'closed segment result differs from immutable finish')
            check(finish.get('resource_overrun') is False,'segment completion exceeded original wall/log allowance')
            for relative,info in finish['evidence_sha256'].items():
                path=segment/relative
                check(path.is_file() and sha_file(path)==info['sha256'] and path.stat().st_size==info['bytes'],'closed segment evidence changed: '+relative)
            check(finish['segment_wall_seconds']==result['wall_seconds'],'closed segment wall differs from result')
        registration=mapping['original_registration']
        check(package['original_registration']==registration,'recovery changed original stage registration')
        check(mapping['inherited']['runner_wall_seconds']+result['wall_seconds']<=registration['wall_seconds'],'cumulative runner wall overrun')
        check(mapping['inherited']['log_bytes']+sum(v['bytes'] for v in inventory(segment).values())<=registration['max_log_bytes'],'cumulative log cap exceeded including later audit artifacts')
        finalized=replay.get('recovery_finalizations',{}).get(str(segment))
        if finalized:
            acceptance=read(finalized['acceptance_path'])
            check(sha_file(finalized['acceptance_path'])==finalized['acceptance_sha256'],'final acceptance changed after resource closure')
            check(finalized.get('resource_overrun') is False and finalized['cumulative_final_wall_seconds']<=registration['wall_seconds'],
                  'post-audit finalization exceeded original resource allowance')
            check(acceptance.get('segment_final_wall_seconds')==finalized['segment_final_wall_seconds'] and
                  acceptance.get('cumulative_final_wall_seconds')==finalized['cumulative_final_wall_seconds'] and
                  acceptance.get('accepted')==finalized['accepted'],'final acceptance differs from authoritative final resource closure')
            check(acceptance.get('result_sha256')==sha_file(segment/'result.json') and
                  acceptance.get('recovery_audit_sha256')==sha_file(segment/'recovery_audit.json'),'final acceptance result/audit binding changed')
        parent_audit=audit_controller(parent,ledger_path)
        check(parent_audit['valid'],'parent controller attribution no longer passes independent audit')
        check(parent_audit['all_saved_problem_pages_lossless_certified'],'parent compact pages are not fully lossless')
        provenance=read(segment/'provenance.json') or {}
        for relative,expected in provenance.get('source_sha256',{}).items():
            path=segment/'source_snapshot'/relative
            check(path.is_file() and sha_file(path)==expected,'recovery source snapshot mismatch: '+relative)
        for name in ('controller_resume.py','controller_resume_audit.py','budget.py','model_transport.py','environment.py','interface.py'):
            check('src/smt_fullfab/'+name in provenance.get('source_sha256',{}),'recovery source inventory missing '+name)
        frozen=parent/'source_snapshot/src/smt_fullfab/controller.py'
        constants=_literal_prompt_constants(frozen);base=constants['B_PROMPT']
        nodes=[n.value for n in ast.parse(frozen.read_text()).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='B_SCHEMA' for t in n.targets)]
        if len(nodes)!=1:raise ValueError('unique original literal B schema missing')
        schema=ast.literal_eval(nodes[0]);contract=read(segment/'frozen_B_contract.json')
        check(contract=={'schema':schema,'prompt':base,'parent_controller_sha256':sha_file(frozen)},'recovery prompt/schema differs from frozen B contract')
        original_cfg=read(parent/'config.json');original_model_cfg=read(parent/'model_000/request.json')['config']
        for key,value in original_cfg.items():
            if key!='run_id':check(cfg.get(key)==value,'recovery silently changed original controller configuration: '+key)
        check(cfg.get('run_id')==segment.name and cfg.get('parent_run_id')==str(parent),'recovery config lineage mismatch')
        protocol=read(segment/'protocol.json');original_protocol=read(cfg['protocol_path'])
        check(protocol==original_protocol and sha_file(cfg['protocol_path'])==cfg.get('protocol_sha256'),'recovery protocol changed after configuration freeze')
        expected_protocol={'schema':'smt-fullfab-B-recovery-protocol-v1','parent_run_id':str(parent),'segment_run_id':str(segment),
            'package_identity_sha256':package['package_sha256'],'recovery_package_sha256':mapping['recovery_package_sha256'],
            'model':'gpt-6-astra','reasoning_effort':'medium','per_call_timeout_seconds':180,'plan_seconds':14400,'lookahead_depth':2,
            'period_seconds':1800,'wall_seconds':registration['wall_seconds'],'max_log_bytes':registration['max_log_bytes'],
            'max_calls':None,'max_reported_tokens':None,'max_revisions_per_page':cfg.get('max_revisions_per_page'),'max_revisions_per_plan':cfg.get('max_revisions_per_plan')}
        check(all(protocol.get(key)==value for key,value in expected_protocol.items()),'recovery protocol silently changes original scope or revision limits')
        check(type(cfg.get('max_revisions_per_page'))is int and 0<=cfg['max_revisions_per_page']<=1 and
              type(cfg.get('max_revisions_per_plan'))is int and 0<=cfg['max_revisions_per_plan']<=3,'revision limits exceed frozen bounded repair contract')
        trace=read(segment/'trace.jsonl',lines=True);parent_trace=read(parent/'trace.jsonl',lines=True)
        physical_horizon=_registered_physical_horizon(registration,trace)
        check(trace[:len(parent_trace)]==parent_trace,'recovery lost/changed parent prehistory')
        if len(trace)>len(parent_trace):
            loaded=trace[len(parent_trace)]
            check(loaded.get('kind')=='snapshot_loaded' and loaded.get('prefix_event_count')==len(parent_trace) and
                  loaded.get('snapshot_sha256')==package['checkpoint_state_sha256'],'recovery begins with wrong snapshot identity')
        else:missing.append('explicit restored snapshot trace event')
        checkpoint=read(segment/'checkpoint.json')
        if checkpoint:
            check(checkpoint.get('state_sha256')==digest(checkpoint['state']) and checkpoint['state'].get('trace')==trace,'final checkpoint/trace hash mismatch')
            check(checkpoint['state'].get('t')==result.get('simulation_seconds'),'final checkpoint/result physical time mismatch')
        decisions=read(segment/'recovery_decisions.jsonl',lines=True,optional=True)
        accepted_records=read(segment/'page_accepted.jsonl',lines=True,optional=True)
        rejected_records=read(segment/'page_rejected.jsonl',lines=True,optional=True)
        commit_records=read(segment/'plan_commits.jsonl',lines=True,optional=True)
        trace_commits=[e for e in trace if e.get('kind')=='plan_committed']
        check(result.get('plans_committed')==len(trace_commits)==len(commit_records),'committed plan count differs from trace/links')
        reserves={r['call_id']:r for r in ledger if r.get('event')=='reserve'};finishes={r['call_id']:r for r in ledger if r.get('event')=='finish'}
        own_reserves=[r for r in ledger if r.get('event')=='reserve' and Path(r['run_id']).resolve().parent==segment]
        dirs=sorted([p for p in segment.glob('model_*') if p.is_dir()],key=lambda p:int(p.name.split('_')[1]))
        indices=[int(p.name.split('_')[1]) for p in dirs]
        check(indices==list(range(package['next_model_index'],package['next_model_index']+len(dirs))),'new model indexes repeated/omitted parent or segment attempts')
        check([d.get('model_index') for d in decisions]==indices,'every new raw attempt requires exactly one ordered decision link')
        check(result.get('model_call_ids')==[r['call_id'] for r in own_reserves] and result.get('model_calls')==len(dirs)==len(own_reserves),'segment result omits/invents model attempts')
        check(not list(segment.glob('solver*')) and result.get('solver_calls')==0 and result.get('solver_requested_seconds')==0,'B recovery contains solver use')
        check(not any(r.get('event')=='solver_reserve' and Path(r.get('run_id','/')).resolve()==segment for r in ledger),'B recovery consumed solver account')
        models={}
        for directory in dirs:
            index=int(directory.name.split('_')[1]);model=read(directory/'result.json');request=read(directory/'request.json');saved_schema=read(directory/'schema.json')
            prompt=(directory/'prompt.txt').read_text();evidence[str(directory/'prompt.txt')]=sha_file(directory/'prompt.txt')
            call_id=model['call_id'];reserve=reserves.get(call_id);finished=finishes.get(call_id)
            check(saved_schema==schema,'recovery response schema changed')
            check(request.get('call_id')==call_id and request.get('config')==model.get('config'),'request/result identity mismatch')
            config=request['config'];expected_cfg={**original_model_cfg,'timeout_seconds':config['timeout_seconds']}
            check(config==expected_cfg,'new model configuration changed beyond remaining-time timeout')
            fingerprint=hashlib.sha256((prompt+'\n'+json.dumps(saved_schema,ensure_ascii=False,indent=2)+'\n'+'\n'+json.dumps(config,sort_keys=True)).encode()).hexdigest()
            check(request.get('request_fingerprint')==model.get('request_fingerprint')==fingerprint,'recovery raw prompt/schema/config fingerprint mismatch')
            claim=directory/'attempt.claim';check(claim.is_file() and claim.read_text()==fingerprint+'\n','recovery model attempt claim changed')
            check(reserve is not None and Path(reserve['run_id']).resolve()==directory and reserve.get('metadata',{}).get('request_fingerprint')==fingerprint,'new model attempt lacks exact prior reservation')
            admission=replay['admissions'].get(call_id,{})
            check(admission.get('registration')==registration and admission.get('timeout_seconds')==config.get('timeout_seconds'),'new attempt was not admitted under inherited registration/timeout')
            if finished is None:missing.append('ledger finish for '+call_id)
            else:check(finished['status']==model['status'] and all(finished.get('details',{}).get(k)==model.get(k) for k in ('usage','duration_seconds')),'model/ledger terminal consumption mismatch')
            events=[];malformed=[]
            event_path=directory/'events.jsonl';evidence[str(event_path)]=sha_file(event_path)
            for line in event_path.read_text(errors='replace').splitlines():
                if not line.strip():continue
                try:events.append(json.loads(line))
                except json.JSONDecodeError:malformed.append(line)
            native=[e.get('item',{}) for e in events if e.get('type') in ('item.started','item.updated','item.completed') and e.get('item',{}).get('type') not in ('agent_message','reasoning','error')]
            completed=[e for e in events if e.get('type')=='turn.completed'];usages=[e['usage'] for e in completed if isinstance(e.get('usage'),dict)]
            check(model.get('native_tool_events')==native and model.get('malformed_event_lines',[])==malformed,'raw isolation/event evidence differs from model summary')
            for key in ('input_tokens','cached_input_tokens','output_tokens','cache_write_input_tokens','reasoning_output_tokens'):
                total=sum(u[key] for u in usages) if usages and all(type(u.get(key)) in (int,float) for u in usages) else None
                check(model.get('usage',{}).get(key)==total,'raw reported usage differs: '+key)
            if model['status']=='success':
                check(not native and not malformed and len(completed)==1 and model.get('returncode')==0 and model.get('timed_out') is False,'successful raw attempt violates completion/isolation contract')
                check(read(directory/'final.txt')==model.get('output'),'new model output differs from saved final JSON')
            sections=_strict_prompt_sections(prompt,base)
            models[index]=(model,sections);checked+=1
        page_sets={}
        for path in sorted(segment.glob('page_manifest_*.json')):
            pindex=int(path.stem.rsplit('_',1)[1]);manifest=read(path);problem=read(segment/f'problem_{pindex:03d}.json')
            pages=[read(segment/f'page_{pindex:03d}_{i:02d}.json') for i in range(manifest['page_count'])]
            check(manifest.get('schema')=='fullfab-compact-paging-v2','recovery page set is not lossless v2')
            errors.extend(f'plan {pindex}: '+e for e in _verify_pages(problem,manifest,pages))
            check(manifest.get('observation_end')==registration['window_seconds'],'recovery page window changed')
            check(all(len(json.dumps(page,separators=(',',':'),allow_nan=False))<=cfg['page_chars'] for page in pages),'recovery page exceeds original declared page bound')
            if pindex==0:
                check(digest(problem)==package['problem_sha256'] and digest(manifest)==package['manifest_sha256'],'first recovered observation differs from parent')
            page_sets[pindex]=(problem,manifest,pages)
        check(sorted(page_sets)==list(range(len(page_sets))),'recovery plan observation indexes are not contiguous')
        observed_accepts=[];observed_rejects=[];used_patch_paths=[];all_call_ids=[]
        for pindex,(problem,manifest,pages) in sorted(page_sets.items()):
            staged=[];holds=[];sources=[];page_index=0;feedback=None;page_revisions={};plan_revisions=0;reason=''
            if pindex==0:
                for source in package['accepted_pages']:
                    page_index=source['page_index'];patch_path=parent/f'patch_000_{page_index:02d}.json';response=read(patch_path)
                    old_model=read(parent/f"model_{source['model_index']:03d}/result.json")
                    check(old_model.get('status')=='success' and old_model.get('output')==response and old_model.get('call_id')==source['call_id'],'parent accepted page lacks original successful output')
                    check(not _page_errors(problem,pages[page_index],response,staged,holds,schema,page_index,len(pages),manifest['observation_end']),'parent preparation retained an invalid page')
                    staged+=response['tasks'];holds+=response['holds'];reason=response['reason']
                    check(source['patch_sha256']==digest(response) and source['patch_file_sha256']==sha_file(patch_path) and source['cumulative_staged_sha256']==digest(staged) and source['cumulative_holds_sha256']==digest(holds),'parent accepted prefix hashes mismatch')
                    observed_accepts.append({**source,'event':'page_accepted','plan_index':0,'source_parent':True,'patch_path':str(patch_path)})
                    sources.append(source['call_id']);page_index+=1
                check(page_index==package['next_page'] and staged==package['staged_tasks'] and holds==package['staged_holds'],'recovery prefix cursor/payload differs from accepted parent pages')
                failed=package.get('failed_page_feedback',[])
                if failed:
                    prior=read(parent/f"model_{package['next_model_index']-1:03d}/result.json")
                    why=_page_errors(problem,pages[page_index],prior['output'],staged,holds,schema,page_index,len(pages),manifest['observation_end']) if prior['status']=='success' else ['model_channel:'+str(prior.get('failure_reason'))]
                    check(bool(why) and len(failed)==1 and failed[0]['call_id']==prior['call_id'] and failed[0]['failed_output_sha256']==digest(prior['output']),'initial recovery failure diagnosis differs from raw parent attempt')
                    feedback=_feedback(page_index,prior['call_id'],prior['output'],why)
            own=[d for d in decisions if d.get('plan_index')==pindex]
            for d in own:
                index=d['model_index'];model,sections=models[index];response=model.get('output')
                check(d.get('page_index')==page_index and 0<=page_index<len(pages),'recovery repeated a completed page or skipped page order')
                if not 0<=page_index<len(pages):raise ValueError('model call after full page collection')
                meta={**manifest,'page_index':page_index,'last_page':page_index==len(pages)-1,
                      'remaining_model_responses':None if cfg.get('max_calls') is None else cfg['max_calls']-index}
                preds={x for g in pages[page_index] for row in g['operations'] for x in row[3]};mids={m[0] for g in pages[page_index] for m in g['machines']}
                prior=[t for t in staged if t['machine'] in mids or any(oid in preds for oid in t['operations'])]
                expected_sections={'SCHEMA_AND_LIMITS':meta,'PAGE':pages[page_index],'YOUR_PRIOR_PREDECESSOR_CHOICES':prior}
                if feedback is not None:expected_sections['VALIDATION_FEEDBACK']=feedback
                check(sections==expected_sections,'new model saw altered page, prior accepted choices or failure feedback')
                revision=feedback is not None
                if revision:plan_revisions+=1;page_revisions[page_index]=page_revisions.get(page_index,0)+1
                check(plan_revisions<=cfg['max_revisions_per_plan'] and page_revisions.get(page_index,0)<=cfg['max_revisions_per_page'],'recovery exceeded explicit page/plan revision bound')
                why=['model_channel:'+str(model.get('failure_reason'))] if model['status']!='success' else _page_errors(problem,pages[page_index],response,staged,holds,schema,page_index,len(pages),manifest['observation_end'])
                new_tasks=staged if why else staged+response['tasks'];new_holds=holds if why else holds+response['holds']
                expected={'model_index':index,'call_id':model['call_id'],'plan_index':pindex,'page_index':page_index,'arm':'B','stage':'B_page',
                    'revision':revision,'revision_number':page_revisions.get(page_index,0),'input_problem_sha256':digest(problem),'response_sha256':digest(response),
                    'status':model['status'],'accepted':not why,'validation_errors':why,'patch_sha256':digest(response) if not why else None,
                    'cumulative_staged_sha256':digest(new_tasks),'cumulative_holds_sha256':digest(new_holds)}
                check(d==expected,'accepted/rejected decision differs from independent page validation')
                if why:
                    observed_rejects.append({**expected,'event':'page_rejected'});rejected_count+=1
                    feedback=_feedback(page_index,model['call_id'],response,why)
                    if model['status']!='success':check(d==own[-1],'controller continued after a failed transport')
                else:
                    path=segment/f'patch_{pindex:03d}_{page_index:02d}_{index:03d}.json';check(read(path)==response,'accepted patch differs from raw model output')
                    observed_accepts.append({**expected,'event':'page_accepted','source_parent':False,'patch_path':str(path),'patch_file_sha256':sha_file(path)})
                    used_patch_paths.append(path.name);staged,holds=new_tasks,new_holds;sources.append(model['call_id']);reason=response['reason']
                    page_index+=1;feedback=None;accepted_count+=1
                all_call_ids.append(model['call_id'])
            raw_path=segment/f'raw_plan_{pindex:03d}.json';linked=[r for r in commit_records if r.get('plan_index')==pindex]
            if raw_path.exists():
                check(page_index==len(pages),'raw plan written before all pages explicitly accepted')
                expected=_decode(problem,staged,holds,reason,segment.name+':'+str(pindex));raw=read(raw_path)
                check(raw==expected,'recovery raw plan differs from exact explicit model sequences/choices')
                committed=_crop(raw,physical_horizon,problem['scope'])
                check(read(segment/f'committed_plan_{pindex:03d}.json')==committed,'saved projected plan differs from disclosed projection')
                if linked:
                    expected_link={'plan_index':pindex,'final_model_call_id':sources[-1],'model_call_id':sources[-1],
                        'source_page_call_ids':sources,'raw_plan_sha256':digest(raw),'committed_plan_sha256':digest(committed)}
                    check(linked==[expected_link],'plan commit omitted/replaced an original explicit page source')
                    check(pindex<len(trace_commits) and trace_commits[pindex]['plan']==committed,'trace execution plan differs from explicit raw choice')
                    checked_plans+=1
            else:check(not linked,'plan commitment lacks saved explicit raw plan')
        check(observed_accepts==accepted_records,'page_accepted journal omitted/invented/changed parent or new accepted pages')
        check(observed_rejects==rejected_records,'page_rejected journal omitted/invented failed attempts')
        check(sorted(used_patch_paths)==sorted(p.name for p in segment.glob('patch_*.json')),'unattributed or missing accepted patch artifact')
        check(all_call_ids==result.get('model_call_ids'),'decision page reconstruction did not account for every new call')
        check(checked_plans==len(trace_commits),'not every execution plan has a complete explicit page attribution chain')
        check(all(int(p.stem.rsplit('_',1)[1]) in page_sets for p in segment.glob('raw_plan_*.json')),'raw plan artifact lacks a corresponding observed problem')
        from .audit import audit_trace
        physical=audit_trace(trace,verify_data_dir=Path(__file__).resolve().parents[2]/'data/smt/SMT2020_LVHM')
        saved_physical=read(segment/'audit.json')
        if saved_physical:
            check(saved_physical.get('valid')==physical['valid'],'saved physical audit valid flag differs from replay')
            check(saved_physical.get('metrics')==physical.get('metrics'),'saved physical audit metrics differ from independent replay')
        check(result.get('metrics')==physical.get('metrics'),'result metrics differ from independent physical replay')
        allowed_end_errors=('physical: missing terminal event','physical: missing due calendar event:','physical: unfinished due operation ','physical: missing lot release ')
        prefix_errors=[e for e in physical['errors'] if not any(e.startswith(prefix) for prefix in allowed_end_errors)
                       and not (result.get('simulation_seconds')==0 and e.startswith('metric reconstruction: metric window must be positive'))]
        errors.extend('physical prefix: '+e for e in prefix_errors)
        if result.get('status')=='success' or result.get('full_window_completed'):
            check(physical['valid'] and trace[-1].get('kind')=='terminal' and result.get('audit_valid') is True,'claimed completed recovery failed independent physical/source/opportunity replay')
            check(result.get('simulation_seconds')==registration['window_seconds'],'successful recovery shortened original observation window')
    except (KeyError,ValueError,TypeError,IndexError,OSError,SyntaxError,StopIteration) as exc:
        errors.append(f'malformed recovery evidence: {type(exc).__name__}: {exc}')
    status='failed' if errors else 'partial' if missing else 'passed'
    complete=bool(status=='passed' and result.get('status')=='success' and result.get('full_window_completed') and physical and physical.get('valid'))
    return {'audit_version':VERSION,'audit_status':status,'valid':status=='passed','errors':errors,'missing_evidence':sorted(set(missing)),
            'parent_run_id':mapping.get('parent_run_id'),'segment_run_id':str(segment),'registration_id':mapping.get('registration_id'),
            'recovery_segment_id':mapping.get('recovery_segment_id'),'successful_full_window':complete,
            'model_attempts_checked':checked,'new_accepted_pages':accepted_count,'new_rejected_pages':rejected_count,'attribution_checked_plans':checked_plans,
            'parent_controller_evidence_valid':bool(parent_audit and parent_audit.get('valid')),
            'complete_physical_audit_valid':bool(physical and physical.get('valid')),
            'monetary_cost_certified':False,'evidence_sha256':evidence,
            'scope':'independent inherited budget, exact page acceptance/rejection and execution attribution; partial traces do not certify a completed study window'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('segment_dir');p.add_argument('--ledger');a=p.parse_args()
    result=audit_controller_resume(a.segment_dir,a.ledger);print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['valid'] else 1


if __name__=='__main__':raise SystemExit(main())
