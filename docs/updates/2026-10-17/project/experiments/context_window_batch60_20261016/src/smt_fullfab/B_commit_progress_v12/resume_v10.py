"""Exact closed V10 replay across commits. No model invocation or physics mutation."""
import json,sqlite3
from base64 import b64decode
from pathlib import Path
from .recovery import need,read,sha
from .journal import digest as journal_digest
from src.smt_fullfab.B_memory_progress_v10.workflow.interaction import Interaction,digest
from src.smt_fullfab.B_memory_progress_v10 import policy,prompt_schema
from src.smt_fullfab.B_memory_progress_v9.resume_suffix import restore_suffix

def restore_v10(parent,contract,*,source_root):
    refs=contract['refs']
    for ref in refs.values():need(sha(ref['path'])==ref['sha256'],'V10 predecessor reference changed')
    m=read(refs['manifest']['path']);r=Path(m['segment_path']);c=Path(refs['manifest']['path']).parent
    result=read(refs['result']['path']);outer=read(refs['outer']['path'])
    need(result['failure']['type']=='KeyboardInterrupt' and not result.get('finalization_error'),'not controlled closed V10')
    need(outer['guard']['lifecycle_complete'] and outer['guard']['command_returncode']==1,'V10 outer lifecycle incomplete')
    stop=read(refs['controlled_stop']['path']);need(stop['boundary']['last_model_index']+1==result['next_model_index'],'stop boundary differs')
    for p,h in m['runtime_files'].items():need(sha(c/'frozen'/p)==h,'V10 frozen source changed')
    for p in ('policy.py','prompt_schema.py','workflow/interaction.py','workflow/B_delta_prompt.py','workflow/B_delta_assembly.py','workflow/B_feedback_admission.py'):
        rel='src/smt_fullfab/B_memory_progress_v10/'+p
        need(sha(Path(source_root)/rel)==m['runtime_files'][rel],'replayed V10 source differs')
    parent,ancestor=restore_suffix(parent,m['resume_suffix'],source_root=source_root)
    model=Interaction.migrate(parent,parent_evidence_sha256=digest(parent.export_evidence()))
    db=sqlite3.connect(Path(refs['database']['path']).resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
    need(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','V10 journal integrity')
    rows=list(db.execute('SELECT * FROM events ORDER BY seq'));db.close()
    ledger=[json.loads(x) for x in Path(refs['ledger']['path']).read_bytes().splitlines()]
    trace=[json.loads(x) for x in Path(refs['trace']['path']).read_bytes().splitlines()]
    tail=None;processed=[];starts={};commits=0;previous=None;last_receipt=None;last_advance=None;plan_index=0
    from src.smt_fullfab import model_process_guard
    for expected,(seq,kind,raw,prev,h) in enumerate(rows):
        payload=json.loads(raw)
        need(seq==expected and prev==tail and journal_digest({'seq':seq,'kind':kind,'payload':payload,'previous':prev})==h,'V10 journal chain differs');tail=h
        if kind=='plan_opened':
            plan_index=payload['plan_index'];bootfile=r/f'plan_{plan_index:05d}/bootstrap.json';boot=read(bootfile)
            need(sha(bootfile)==payload['bootstrap_sha256'],'V10 bootstrap changed')
            if plan_index>1:
                need(previous is not None and last_advance is not None,'new plan lacks committed predecessor')
                model=Interaction(boot['base_plan'],boot['problem'],boot['execution_state'],source_sha256=boot['source_sha256'],paging=boot['paging'])
            need(digest(model._inputs)==digest(boot) and model.context()==payload['context'],'V10 exact plan context differs')
        elif kind=='call_started':starts[payload['model_index']]=payload
        elif kind=='action_processed':
            i=payload['model_index'];mdir=r/f'model_{i:05d}';record=read(payload['record_file'])
            need(sha(payload['record_file'])==payload['record_file_sha256'] and sha(payload['result_file'])==payload['result_file_sha256'],'V10 original record/result changed')
            p=model.next_prompt();need(p['prompt_sha256']==starts[i]['prompt_sha256']==record['issued_prompt_sha256'],'V10 replay prompt differs')
            need((mdir/'prompt.txt').read_text()==p['prompt'],'V10 original prompt changed')
            schema=prompt_schema.schema_for_prompt(p['prompt'],model.context());need((mdir/'schema.json').read_bytes()==prompt_schema.schema_bytes(schema),'V10 schema changed')
            original=read(mdir/'result.json');request=read(mdir/'request.json');command=read(mdir/'command.json')
            model_process_guard.verify_lifecycle(mdir,expected_command=command['argv'],expected_timeout=600,expected_call_id=payload['call_id'],expected_fingerprint=request['request_fingerprint'],expected_evidence=original['process_guard'])
            ends=[x for x in ledger if x.get('event')=='finish' and x['call_id']==payload['call_id']]
            need(len(ends)==1 and ends[0]['status']==original['status']=='success' and ends[0]['details']['usage']==original['usage'],'V10 exact cost/finish differs')
            output=(mdir/'final.txt').read_bytes();need(output==b64decode(record['raw_output_base64']),'V10 raw output differs')
            policy.classify(policy.strict_json(output),p['prompt'],model.context(),schema)
            reply=model.handle(output,call_id=payload['call_id'],model_index=i)
            need(reply['record_sha256']==record['record_sha256']==payload['record_sha256'],'V10 replayed action differs');processed.append(i)
        elif kind=='commit_intent':
            need(model._selection is not None and model._history[-1]['parsed_envelope']['request']['kind']=='apply','V10 commit lacks explicit apply')
            need(digest(model._selection)==payload['selection_sha256'],'V10 selection differs')
            previous=model.export_evidence();need(digest(previous)==digest(read(r/f'plan_{plan_index:05d}/interaction_evidence.json')),'V10 committed evidence differs')
        elif kind=='commit_receipt':
            event=trace[payload['trace_event_index_before']]
            need(payload['reported_outcome']=='accepted' and event['kind']=='plan_committed' and digest(event)==payload['trace_event_sha256'],'V10 commit receipt differs')
            need(digest(event['plan'])==payload['actual_plan_sha256']==digest(model._selection['candidate']['compiled']['plan']),'V10 committed plan differs')
            last_receipt=payload;commits+=1
        elif kind=='physical_advance':
            checkpoint=read(r/f'plan_{plan_index:05d}/checkpoint_after.json')
            need(sha(r/f'plan_{plan_index:05d}/checkpoint_after.json')==payload['checkpoint_sha256'],'V10 advance checkpoint changed')
            need(checkpoint['state']['t']==payload['simulation_seconds'],'V10 actual time differs')
            end=checkpoint['state']['trace'][-1];stop=payload['stop']
            need(stop['reason']=='uncovered_demand' and end['kind']=='coverage_gap' and end['time']==stop['time'] and end['machines']==stop['machines'],'V10 exact journal stop differs from trace')
            need(trace[:len(checkpoint['state']['trace'])]==checkpoint['state']['trace'],'V10 trace prefix differs');last_advance=payload
    need(tail==result['durable_prefix']['journal_tail_sha256'] and len(rows)==result['durable_prefix']['journal_records'],'V10 terminal journal differs')
    need(processed==list(range(m['first_model_index'],result['next_model_index'])) and set(starts)==set(processed),'V10 has unprocessed or missing calls')
    need(commits==result['new_commits'] and model._selection is None and model._pending_prompt is None,'V10 not unselected closed boundary')
    need(digest(model.export_evidence())==digest(read(refs['interaction']['path'])),'V10 complete final state differs')
    return model,previous,last_receipt,last_advance,{'valid':True,'ancestor':ancestor,'processed_indices':processed,'commits_verified':commits,
        'next_model_index':result['next_model_index'],'original_outputs_reinvoked':False,'physics_reexecuted':False,'sources':refs}
