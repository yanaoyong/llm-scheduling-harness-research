"""Exact closed V12 replay across commits. No model invocation or physics mutation."""
import json,sqlite3
from base64 import b64decode
from pathlib import Path
from .recovery import need,read,sha
from .journal import digest as journal_digest
from src.smt_fullfab.B_commit_progress_v12.workflow.interaction import Interaction,digest
from src.smt_fullfab.B_commit_progress_v12 import policy,prompt_schema

def restore_v12(model,contract,*,source_root):
    refs=contract['refs']
    for ref in refs.values():need(sha(ref['path'])==ref['sha256'],'V12 predecessor reference changed')
    m=read(refs['manifest']['path']);r=Path(m['segment_path']);c=Path(refs['manifest']['path']).parent
    result=read(refs['result']['path']);outer=read(refs['outer']['path'])
    need(result['failure']['type']=='ValueError' and result['failure']['message']=='controlled stop requested at completed call boundary' and not result.get('finalization_error'),'not controlled closed V12')
    need(outer['guard']['lifecycle_complete'] and outer['guard']['command_returncode']==1,'V12 outer lifecycle incomplete')
    need('stop_request' in refs and read(refs['actual_exit']['path'])['exit_code']==1,'actual controlled stop closure required')
    for p,h in m['runtime_files'].items():need(sha(c/'frozen'/p)==h,'V12 frozen source changed')
    for p in ('policy.py','prompt_schema.py','workflow/interaction.py','workflow/B_delta_prompt.py','workflow/B_delta_assembly.py','workflow/B_feedback_admission.py'):
        rel='src/smt_fullfab/B_commit_progress_v12/'+p
        need(sha(Path(source_root)/rel)==m['runtime_files'][rel],'replayed V12 source differs')
    db=sqlite3.connect(Path(refs['database']['path']).resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
    need(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','V12 journal integrity')
    rows=list(db.execute('SELECT * FROM events ORDER BY seq'));db.close()
    ledger=[json.loads(x) for x in Path(refs['ledger']['path']).read_bytes().splitlines()]
    trace=[json.loads(x) for x in Path(refs['trace']['path']).read_bytes().splitlines()]
    progress=[json.loads(x) for x in Path(refs['progress']['path']).read_bytes().splitlines()]
    tail=None;processed=[];starts={};commits=0;previous=None;last_receipt=None;last_advance=None;plan_index=0
    from src.smt_fullfab import model_process_guard
    for expected,(seq,kind,raw,prev,h) in enumerate(rows):
        payload=json.loads(raw)
        need(seq==expected and prev==tail and journal_digest({'seq':seq,'kind':kind,'payload':payload,'previous':prev})==h,'V12 journal chain differs');tail=h
        if kind=='plan_opened':
            plan_index=payload['plan_index'];bootfile=r/f'plan_{plan_index:05d}/bootstrap.json';boot=read(bootfile)
            need(sha(bootfile)==payload['bootstrap_sha256'],'V12 bootstrap changed')
            if plan_index>1:
                need(previous is not None and last_advance is not None,'new plan lacks committed predecessor')
                model=Interaction(boot['base_plan'],boot['problem'],boot['execution_state'],source_sha256=boot['source_sha256'],paging=boot['paging'])
                model.bind_execution(previous,stop=last_advance['stop'],commit_receipt=last_receipt)
            need(digest(model._inputs)==digest(boot) and model.context()==payload['context'],'V12 exact plan context differs')
        elif kind=='call_started':starts[payload['model_index']]=payload
        elif kind=='action_processed':
            i=payload['model_index'];mdir=r/f'model_{i:05d}';record=read(payload['record_file'])
            need(sha(payload['record_file'])==payload['record_file_sha256'] and sha(payload['result_file'])==payload['result_file_sha256'],'V12 original record/result changed')
            p=model.next_prompt()
            if not (p['prompt_sha256']==starts[i]['prompt_sha256']==record['issued_prompt_sha256']):
                original_prompt=(mdir/'prompt.txt').read_text();original_frame=json.loads(original_prompt.split('\nINPUT_JSON\n',1)[1])
                diagnostic={'model_index':i,'plan_index':plan_index,'expected_sha256':starts[i]['prompt_sha256'],'actual_sha256':p['prompt_sha256'],'differing_top_level_fields':[k for k in p['body'] if p['body'][k]!=original_frame.get(k)],'expected_context':{k:original_frame[k] for k in model.context()},'actual_context':model.context()}
                raise ValueError('V12 replay prompt differs: '+json.dumps(diagnostic))
            need((mdir/'prompt.txt').read_text()==p['prompt'],'V12 original prompt changed')
            schema=prompt_schema.schema_for_prompt(p['prompt'],model.context());need((mdir/'schema.json').read_bytes()==prompt_schema.schema_bytes(schema),'V12 schema changed')
            original=read(mdir/'result.json');request=read(mdir/'request.json');command=read(mdir/'command.json')
            model_process_guard.verify_lifecycle(mdir,expected_command=command['argv'],expected_timeout=600,expected_call_id=payload['call_id'],expected_fingerprint=request['request_fingerprint'],expected_evidence=original['process_guard'])
            ends=[x for x in ledger if x.get('event')=='finish' and x['call_id']==payload['call_id']]
            need(len(ends)==1 and ends[0]['status']==original['status']=='success' and ends[0]['details']['usage']==original['usage'],'V12 exact cost/finish differs')
            output=(mdir/'final.txt').read_bytes();need(output==b64decode(record['raw_output_base64']),'V12 raw output differs')
            policy.classify(policy.strict_json(output),p['prompt'],model.context(),schema)
            reply=model.handle(output,call_id=payload['call_id'],model_index=i)
            need(reply['record_sha256']==record['record_sha256']==payload['record_sha256'],'V12 replayed action differs');processed.append(i)
        elif kind=='commit_intent':
            need(model._selection is not None and model._history[-1]['parsed_envelope']['request']['kind']=='apply','V12 commit lacks explicit apply')
            need(digest(model._selection)==payload['selection_sha256'],'V12 selection differs')
            previous=model.export_evidence();need(digest(previous)==digest(read(r/f'plan_{plan_index:05d}/interaction_evidence.json')),'V12 committed evidence differs')
        elif kind=='commit_receipt':
            event=trace[payload['trace_event_index_before']]
            need(payload['reported_outcome']=='accepted' and event['kind']=='plan_committed' and digest(event)==payload['trace_event_sha256'],'V12 commit receipt differs')
            need(digest(event['plan'])==payload['actual_plan_sha256']==digest(model._selection['candidate']['compiled']['plan']),'V12 committed plan differs')
            last_receipt=read(r/f'plan_{plan_index:05d}/commit_receipt.json')
            need(last_receipt==payload,'original ordered receipt differs from journal values');commits+=1
        elif kind=='physical_advance':
            checkpoint=read(r/f'plan_{plan_index:05d}/checkpoint_after.json')
            need(sha(r/f'plan_{plan_index:05d}/checkpoint_after.json')==payload['checkpoint_sha256'],'V12 advance checkpoint changed')
            need(checkpoint['state']['t']==payload['simulation_seconds'],'V12 actual time differs')
            end=checkpoint['state']['trace'][-1];stop=payload['stop']
            need(stop['reason']=='uncovered_demand' and end['kind']=='coverage_gap' and end['time']==stop['time'] and end['machines']==stop['machines'],'V12 exact journal stop differs from trace')
            need(trace[:len(checkpoint['state']['trace'])]==checkpoint['state']['trace'],'V12 trace prefix differs')
            ordered=[x for x in progress if x.get('event')=='plan_committed_and_advance_attempted' and x['plan_index']==plan_index]
            need(len(ordered)==1 and ordered[0]['advance']=={k:v for k,v in payload.items() if k not in ('from','checkpoint_sha256')},'original ordered advance differs from journal values')
            last_advance={'from':payload['from'],**ordered[0]['advance']}
    need(tail==result['durable_prefix']['journal_tail_sha256'] and len(rows)==result['durable_prefix']['journal_records'],'V12 terminal journal differs')
    need(processed==list(range(m['first_model_index'],result['next_model_index'])) and set(starts)==set(processed),'V12 has unprocessed or missing calls')
    need(commits==result['new_commits'] and model._selection is None and model._pending_prompt is None,'V12 not unselected closed boundary')
    need(digest(model.export_evidence())==digest(read(refs['interaction']['path'])),'V12 complete final state differs')
    return model,previous,last_receipt,last_advance,{'valid':True,'clean_controlled_stop':True,'processed_indices':processed,'commits_verified':commits,
        'next_model_index':result['next_model_index'],'original_outputs_reinvoked':False,'physics_reexecuted':False,'sources':refs}
