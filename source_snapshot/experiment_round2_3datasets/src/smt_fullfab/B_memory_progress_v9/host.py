"""Frozen V9 host: explicit original model decisions, suffix journal, exact physics."""
import argparse,copy,fcntl,hashlib,json,os,sqlite3,sys,time,traceback
from pathlib import Path

def response_status(response):
    # Observation label only. Keep the original response bytes and shape intact.
    if 'status' in response:return response['status']
    if response.get('complete_for_requested_slice') is True:return 'catalog_slice'
    return 'status_not_declared'

def progress_signature(progress,references,selection,digest):
    return digest({'pages':[p['page_index'] for p in progress['successful_pages']],
        'drafts':[[d['draft_id'],d['state_sha256']] for d in progress['drafts']],
        'candidates':references['candidates'],'selection':selection})

def main(campaign,expected,first,hard,soft):
    campaign=Path(campaign).resolve();frozen=campaign/'frozen';sys.path.insert(0,str(frozen))
    from src.smt_fullfab.B_memory_progress_v9.recovery import recover,need,read,new,sha
    from src.smt_fullfab.B_memory_progress_v9.workflow.interaction import Interaction,digest,render
    from src.smt_fullfab.B_memory_progress_v9 import policy,prompt_schema
    from src.smt_fullfab.B_memory_progress_v9.ledger import make_ledger_class
    from src.smt_fullfab.B_memory_progress_v9.journal import Journal
    need(sha(campaign/'manifest.json')==expected,'manifest hash mismatch');m=read(campaign/'manifest.json')
    need(Path(__file__).resolve()==frozen/'src/smt_fullfab/B_memory_progress_v9/host.py','frozen host required')
    need(hard==first+m['remaining_wall_seconds']-m['prepare_wall_seconds']-30 and soft==hard-900,'deadline ordering differs')
    source_ids={}
    for path,want in m['runtime_files'].items():
        p=frozen/path;need(sha(p)==want,'frozen source changed: '+path);s=p.stat();source_ids[p]=(s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    for ref in m['input_refs'].values():need(sha(ref['path'])==ref['sha256'],'pinned predecessor input changed')
    root=Path(m['root']);out=Path(m['segment_path'])
    serial=(root/'progress/smt_fullfab/B_v9.serial.lock').open('a+')
    fcntl.flock(serial,fcntl.LOCK_EX|fcntl.LOCK_NB)
    for ref in m['executable_refs'].values():need(sha(ref['path'])==ref['sha256'],'executable changed')
    out.mkdir(exist_ok=False)
    new(out/'config.json',m);new(campaign/'first_clock.json',{'started_monotonic':first,'hard':hard,'soft':soft})
    physical=None;journal=None;model=None;calls=0;commits=0;next_index=m.get('first_model_index',237);failure=None;ledger=None;plan_index=1
    progress_rows=[];source_changed=False
    def retained():return sum(p.stat().st_size for base in (campaign,out) for p in base.rglob('*') if p.is_file())
    def fence():
        nonlocal source_changed
        for p,identity in source_ids.items():
            s=p.stat()
            if (s.st_size,s.st_mtime_ns,s.st_ctime_ns)!=identity:source_changed=True;raise ValueError('source identity changed: '+str(p))
        need(time.monotonic()<hard,'host hard deadline reached')
        need(retained()<m['remaining_log_bytes'],'cumulative bytes exceeded')
    def save_progress(row):
        progress_rows.append(row)
        with (out/'progress.jsonl').open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
        tmp=out/'live.json.tmp';tmp.write_text(json.dumps(row,ensure_ascii=False,indent=2));tmp.replace(out/'live.json')
        print(json.dumps(row,ensure_ascii=False),flush=True)
    try:
        parent,proof,h=recover(root,frozen)
        need(proof['parent_evidence_sha256']==m['recovery']['parent_evidence_sha256'],'recovery changed since tested boundary')
        new(out/'recovery_verification.json',proof)
        from src.smt_fullfab import budget,model_process_guard
        from src.smt_fullfab.B_incremental_v3 import controller,transport
        from src.smt_fullfab.B_resume_v1 import physical_resume
        budget.ROOT=root;controller.ROOT=root
        physical=physical_resume.restore(m['parent_contract'],directory=out/'physical',controller=controller,snapshot_writer=controller.write_snapshot)
        need(physical.env.t==803.2499999999999 and physical.env.horizon==3600,'wrong restored clock')
        need(digest(physical.bootstrap)==digest(parent._inputs),'restored snapshot differs from preserved interaction')
        model=Interaction.migrate(parent,parent_evidence_sha256=proof['parent_evidence_sha256'])
        if m.get('resume_suffix'):
            from src.smt_fullfab.B_memory_progress_v9.resume_suffix import restore_suffix
            model,suffix_proof=restore_suffix(model,m['resume_suffix'],source_root=frozen)
            new(out/'suffix_recovery_verification.json',suffix_proof)
        initial_model=copy.deepcopy(model)
        new(out/'migration.json',model._migration)
        journal=Journal(out/'durable/ledger.sqlite3',migration={'parent_database':h['state']['active_database'],
            'proof':proof,'preserved_v9_suffix':m.get('resume_suffix'),'new_context':model.context(),'version_manifest_sha256':expected})
        Ledger=make_ledger_class(budget,manifest=m,manifest_sha256=expected,campaign=campaign,
            started=first,soft_deadline=soft,retained_bytes=retained)
        ledger=Ledger(root/'progress/smt_fullfab/model_ledger.jsonl');registration=ledger.register();new(out/'registration.json',registration)
        model_config=transport.ModelConfig(model='gpt-6-astra',reasoning_effort='medium',timeout_seconds=600,
            ledger_path=str(ledger.path),phase=m['recovery']['prior_registration']['phase'],
            grant_id=m['recovery']['prior_registration']['budget_id'],
            authorization_context={'purpose':'B','arm':'B','scenario':1701,'window_seconds':3600})
        need([str(p) for p in transport._disabled_skills()]==m['disabled_skill_paths'],'tool isolation inventory changed')
        no_progress=0;last_signature=None;repeated_pages={};error_counts={}
        while not physical.env.finished:
            plan_dir=out/f'plan_{plan_index:05d}';plan_dir.mkdir()
            boot=controller.bootstrap(physical.env,run_id=m['parent_contract']['parent_run_name'],source_sha256=m['parent_contract']['parent_source_sha256'],page_chars=m['parent_contract']['page_chars'])
            need(digest(boot)==digest(model._inputs),'current model/physical snapshot differs')
            new(plan_dir/'bootstrap.json',boot)
            journal.append('plan_opened',{'plan_index':plan_index,'bootstrap_sha256':sha(plan_dir/'bootstrap.json'),'context':model.context()})
            while model._selection is None:
                fence();need(time.monotonic()+660<soft,'no new call: insufficient soft deadline margin')
                p=model.next_prompt();schema=prompt_schema.schema_for_prompt(p['prompt'],model.context())
                model_dir=out/f'model_{next_index:05d}';call_dir=out/f'call_{next_index:05d}';call_dir.mkdir()
                journal.append('call_started',{'model_index':next_index,'plan_index':plan_index,'prompt_sha256':p['prompt_sha256'],
                    'schema_sha256':hashlib.sha256(prompt_schema.schema_bytes(schema)).hexdigest(),'context':model.context()})
                calls+=1
                result=transport.call_model(p['prompt'],schema,model_dir,model_config,ledger_factory=Ledger)
                i=next_index;next_index+=1
                # An unsuccessful transport is retained and stops this segment; never rerun its index.
                need(result['status']=='success','original transport failed: '+str(result['failure_reason']))
                raw=(model_dir/'final.txt').read_bytes();output=policy.strict_json(raw)
                need(output==result['output'],'raw final differs from saved parsed output')
                need((model_dir/'prompt.txt').read_text()==p['prompt'],'issued prompt changed')
                need((model_dir/'schema.json').read_bytes()==prompt_schema.schema_bytes(schema),'issued schema changed')
                req=read(model_dir/'request.json');command=read(model_dir/'command.json')
                model_process_guard.verify_lifecycle(model_dir,expected_command=command['argv'],expected_timeout=600,
                    expected_call_id=result['call_id'],expected_fingerprint=req['request_fingerprint'],expected_evidence=result['process_guard'])
                kind=policy.classify(output,p['prompt'],model.context(),schema)
                need(not journal.processed(i,result['call_id']),'model action already processed')
                response=model.handle(raw,call_id=result['call_id'],model_index=i)
                row=model._history[-1];new(call_dir/'record.json',row);new(call_dir/'outcome.json',response)
                # Durable original action, exact hash and channel refs are written before any next call or commit.
                journal.append('action_processed',{'model_index':i,'call_id':result['call_id'],'record_sha256':row['record_sha256'],
                    'record_file':str(call_dir/'record.json'),'record_file_sha256':sha(call_dir/'record.json'),
                    'result_file':str(model_dir/'result.json'),'result_file_sha256':sha(model_dir/'result.json'),
                    'raw_output_sha256':hashlib.sha256(raw).hexdigest(),'classification':kind})
                prog=model.progress();new(call_dir/'progress.json',prog)
                f=response['response'];sig=progress_signature(prog,model.runtime_references(),model._selection,digest)
                material=sig!=last_signature
                if material:no_progress=0;repeated_pages={};error_counts={}
                else:no_progress+=1
                last_signature=sig
                rq=output['request'];a=rq.get('action',{});pi=a.get('page_index') if rq['kind']=='session_query' and a.get('action')=='read_page' else None
                repeat=pi is not None and any(x['page_index']==pi and x['successful_reads']>1 for x in prog['successful_pages'])
                if repeat:repeated_pages[pi]=repeated_pages.get(pi,0)+1
                code=f.get('error',{}).get('code')
                if code:error_counts[code]=error_counts.get(code,0)+1
                observations={'model_index':i,'call_id':result['call_id'],'plan_index':plan_index,'simulation_seconds':physical.env.t,
                    'action':rq['kind'],'nested_action':a.get('action'),'response_status':response_status(f),'error_code':code,
                    'memory_update':f.get('memory_update'),'memory_serialized_characters':len(render(model._memory['memory'])) if model._memory else 2,
                    'page_index':pi,'repeat_page':repeat,'read_reason':output['read_reason'],'cache_hit':bool(f.get('page_cache_receipt',{}).get('hit')),
                    'pages_read':len(prog['successful_pages']),'first_unread_page':prog['first_unread_page_index'],
                    'drafts':[{'draft_id':d['draft_id'],'phase':d['phase'],'next_sequence':d['next_sequence'],'added_tasks':len(d['task_add_ids'])} for d in prog['drafts']],
                    'new_commits':commits,'material_progress':material,'calls_without_material_progress':no_progress,'next_model_index':next_index}
                save_progress(observations)
                need(max(repeated_pages.values(),default=0)<3,'stagnation: same snapshot page repeated three times without draft/query/check progress')
                need(max(error_counts.values(),default=0)<3,'stagnation: same action error three times without material progress')
                need(no_progress<8,'stagnation: eight calls without new page, accepted draft, seal/check or apply')
            selection=model._selection
            need(selection['status']=='selection_for_external_commit' and model._history[-1]['parsed_envelope']['request']['kind']=='apply','explicit apply required')
            selected=selection['candidate']['compiled']['plan'];new(plan_dir/'selected_plan.json',selected)
            need(selection['anchors']==controller.anchor_hashes(boot['base_plan'],boot['problem'],boot['execution_state'],source_sha256=boot['source_sha256']),'selected anchors changed')
            new(plan_dir/'interaction_evidence.json',model.export_evidence())
            # Rebuild all V9 outputs from this plan's starting state at commit, not every model call.
            if plan_index==1:replayed=copy.deepcopy(initial_model)
            else:replayed=Interaction(boot['base_plan'],boot['problem'],boot['execution_state'],source_sha256=boot['source_sha256'],paging=boot['paging'])
            start_count=len(initial_model._history) if plan_index==1 else 0
            from base64 import b64decode
            for record in model._history[start_count:]:
                issued=replayed.next_prompt();need(issued['prompt_sha256']==record['issued_prompt_sha256'],'commit replay prompt differs')
                r=replayed.handle(b64decode(record['raw_output_base64']),call_id=record['call_id'],model_index=record['model_index'])
                need(r['record_sha256']==record['record_sha256'],'commit replay record differs')
            need(digest(replayed._selection)==digest(selection),'commit replay selection differs')
            journal.verify();fence()
            def commit():
                before=len(physical.env.trace);intent={'plan_index':plan_index,'selection_sha256':digest(selection),'plan_sha256':digest(selected),'trace_event_index_before':before,'no_retry':True}
                new(plan_dir/'commit_intent.json',intent);journal.append('commit_intent',intent)
                try:
                    returned=physical.env.commit_plan(selected)
                    need(returned==digest(selected) and physical.env.trace[before]['kind']=='plan_committed' and len(physical.env.trace)==before+1,'common commit differs')
                    receipt={**intent,'reported_outcome':'accepted','actual_plan_sha256':returned,'trace_event_sha256':digest(physical.env.trace[before])}
                except BaseException as e:
                    receipt={**intent,'reported_outcome':'unknown','error':repr(e)};new(plan_dir/'commit_receipt.json',receipt);journal.append('commit_receipt',receipt);raise
                new(plan_dir/'commit_receipt.json',receipt);journal.append('commit_receipt',receipt);return receipt
            physical.commit_once(selected,expected_bootstrap=boot,record_intent_and_commit=commit);commits+=1
            before_t=physical.env.t;advanced=physical.advance_once()
            controller.write_snapshot(physical.env,plan_dir/'checkpoint_after.json');journal.append('physical_advance',{'from':before_t,**advanced,'checkpoint_sha256':sha(plan_dir/'checkpoint_after.json')})
            save_progress({'event':'plan_committed_and_advanced','plan_index':plan_index,'new_commits':commits,'from_seconds':before_t,
                'simulation_seconds':physical.env.t,'commit_receipt':str(plan_dir/'commit_receipt.json'),'next_model_index':next_index,'advance':advanced})
            if physical.env.finished:break
            boot=controller.bootstrap(physical.env,run_id=m['parent_contract']['parent_run_name'],source_sha256=m['parent_contract']['parent_source_sha256'],page_chars=m['parent_contract']['page_chars'])
            model=Interaction(boot['base_plan'],boot['problem'],boot['execution_state'],source_sha256=boot['source_sha256'],paging=boot['paging'])
            plan_index+=1;no_progress=0;last_signature=None;repeated_pages={};error_counts={}
        audit,bundle=controller.stream_audit(out/'physical/trace.jsonl',out/'physical',data_dir=physical.env.data_dir,window_start=0)
        new(out/'physical_audit_summary.json',{'audit':audit,'bundle':bundle})
        need(audit['valid'],'independent full physical audit failed')
    except BaseException as e:
        failure={'type':type(e).__name__,'message':str(e),'traceback':traceback.format_exc()}
        new(out/'failure.json',failure)
    finally:
        result={'schema':'smt-B-memory-progress-v9-result','status':'failed' if failure else 'completed_pending_outer_resource_check',
            'accepted':False,'formal':False,'failure':failure,'new_attempts':calls,'next_model_index':next_index,'new_commits':commits,
            'simulation_seconds':None if physical is None else physical.env.t,'absolute_target':3600,
            'full_window_completed':physical is not None and physical.env.finished and physical.env.t==3600 and failure is None,
            'cost_usd':None,'previous_failures_unchanged':True,'elapsed_seconds_before_publication':time.monotonic()-first}
        try:
            if model is not None:new(out/'final_interaction.json',model.export_evidence())
            if physical is not None:
                controller.write_snapshot(physical.env,out/'checkpoint.json');result['checkpoint_sha256']=sha(out/'checkpoint.json');result['trace_sha256']=sha(out/'physical/trace.jsonl')
            if journal is not None:result['durable_prefix']=journal.verify();journal.close()
            if ledger is not None:
                result['account']=ledger.summary();new(campaign/'ledger_final_account.json',result['account'])
                with (campaign/'ledger_final.jsonl').open('xb') as f:f.write(ledger.path.read_bytes())
            fence()
        except BaseException as e:result['status']='failed';result['finalization_error']={'type':type(e).__name__,'message':str(e),'traceback':traceback.format_exc()}
        result['retained_bytes_before_publication']=retained();new(out/'result.json',result);new(campaign/'host_result.json',result)
    return 0 if result['status']=='completed_pending_outer_resource_check' else 1

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--campaign',required=True);p.add_argument('--manifest-sha256',required=True)
    for k in ('first-monotonic','hard-deadline-monotonic','soft-deadline-monotonic'):p.add_argument('--'+k,type=float,required=True)
    a=p.parse_args();raise SystemExit(main(a.campaign,a.manifest_sha256,a.first_monotonic,a.hard_deadline_monotonic,a.soft_deadline_monotonic))
