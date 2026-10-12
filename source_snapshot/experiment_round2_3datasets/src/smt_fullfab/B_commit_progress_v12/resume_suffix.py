"""Resume a closed uncommitted V11 suffix, retaining a terminal failed prompt.

The failed invocation is never rerun/reconciled or converted into model output.
Its original issued prompt remains pending for a separately budgeted new index.
"""
import json,sqlite3
from base64 import b64decode
from pathlib import Path
from .recovery import need,read,sha
from .workflow.interaction import digest
from .journal import digest as journal_digest
from . import policy,prompt_schema

def restore_suffix(model,contract,*,source_root):
    refs=contract['refs']
    for ref in refs.values():need(sha(ref['path'])==ref['sha256'],'closed V11 reference changed')
    m=read(refs['manifest']['path']);r=Path(m['segment_path']);c=Path(refs['manifest']['path']).parent
    result=read(refs['result']['path']);outer=read(refs['outer']['path']);ancestor=None
    need(result['new_commits']==0 and result.get('finalization_error') is None,'only fully closed uncommitted V11 suffix supported')
    need(outer['guard']['lifecycle_complete'] and outer['guard']['command_returncode']==1,'original V11 outer termination incomplete')
    for p,h in m['runtime_files'].items():need(sha(c/'frozen'/p)==h,'original V11 source changed')
    for p in ('policy.py','prompt_schema.py','workflow/interaction.py','workflow/B_delta_prompt.py','workflow/B_delta_assembly.py','workflow/B_feedback_admission.py'):
        rel='src/smt_fullfab/B_commit_progress_v12/'+p
        need(sha(Path(source_root)/rel)==m['runtime_files'][rel],'pure V11 protocol cannot change on transport continuation')
    if m.get('resume_v11'):model,ancestor=restore_suffix(model,m['resume_v11'],source_root=source_root)
    db=sqlite3.connect(Path(refs['database']['path']).resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
    need(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','V11 journal integrity differs')
    events=list(db.execute('SELECT * FROM events ORDER BY seq'));db.close()
    tail=None;starts={};processed={}
    for count,(seq,kind,raw,prev,h) in enumerate(events):
        payload=json.loads(raw)
        need(seq==count and prev==tail and journal_digest({'seq':seq,'kind':kind,'payload':payload,'previous':prev})==h,'V11 journal chain differs');tail=h
        need(kind not in ('commit_intent','commit_receipt','physical_advance'),'V11 suffix has physical activity')
        if kind=='call_started':starts[payload['model_index']]=payload
        if kind=='action_processed':processed[payload['model_index']]=payload
    need(tail==result['durable_prefix']['journal_tail_sha256'] and len(events)==result['durable_prefix']['journal_records'],'V11 terminal prefix differs')
    indices=list(range(m['first_model_index'],result['next_model_index']))
    clean_stop=(result['failure']['type']=='ValueError' and result['failure']['message']=='controlled stop requested at completed call boundary')
    if clean_stop:
        need('stop_request' in refs and sorted(starts)==indices and sorted(processed)==indices,'controlled stop must have every original action processed')
    else:
        need(sorted(starts)==indices and sorted(processed)==indices[:-1],'only one final output-less failed invocation may be pending')
    ledger=[json.loads(x) for x in Path(refs['ledger']['path']).read_bytes().splitlines()]
    from src.smt_fullfab import model_process_guard
    failure=None;last_processed_index=model._last_index
    for i in indices:
        md=r/f'model_{i:05d}';original=read(md/'result.json');request=read(md/'request.json');command=read(md/'command.json')
        prompt=model.next_prompt();need(prompt['prompt_sha256']==starts[i]['prompt_sha256'],'V11 continuation replay prompt differs')
        need((md/'prompt.txt').read_text()==prompt['prompt'],'original V11 issued prompt changed')
        schema=prompt_schema.schema_for_prompt(prompt['prompt'],model.context());need((md/'schema.json').read_bytes()==prompt_schema.schema_bytes(schema),'V11 original schema differs')
        model_process_guard.verify_lifecycle(md,expected_command=command['argv'],expected_timeout=600,expected_call_id=original['call_id'],expected_fingerprint=request['request_fingerprint'],expected_evidence=original['process_guard'])
        ends=[x for x in ledger if x.get('event')=='finish' and x['call_id']==original['call_id']]
        need(len(ends)==1 and ends[0]['status']==original['status'] and ends[0]['details']['usage']==original['usage'],'V11 terminal cost differs')
        if i in processed:
            event=processed[i];record=read(event['record_file'])
            need(sha(event['record_file'])==event['record_file_sha256'] and sha(event['result_file'])==event['result_file_sha256'],'V11 processed evidence differs')
            raw=(md/'final.txt').read_bytes();need(raw==b64decode(record['raw_output_base64']),'V11 exact original final differs')
            need(original['status']=='success','processed V11 invocation unsuccessful')
            policy.classify(policy.strict_json(raw),prompt['prompt'],model.context(),schema)
            answer=model.handle(raw,call_id=original['call_id'],model_index=i)
            need(answer['record_sha256']==record['record_sha256']==event['record_sha256'],'V11 exact action replay differs')
            last_processed_index=i
        else:
            need(original['status']=='failed' and original['failure_reason']=='model_transport_error' and original['completed_turns']==0,'unsupported V11 terminal failure')
            need(original['output'] is None and not (md/'final.txt').exists() and original['process_guard']['output_files_sha256']['final.txt'] is None,'failed invocation has unprocessed output')
            need(any(x.get('message')=='workspace routing discovery failed' for x in original['errors']),'not the evidenced routing failure')
            failure={'model_index':i,'call_id':original['call_id'],'status':original['status'],'usage':original['usage'],
                'original_result':refs['result'],'model_result_sha256':sha(md/'result.json'),'issued_prompt_sha256':prompt['prompt_sha256'],
                'pending_prompt_retained':True,'new_model_index_required':result['next_model_index'],'failed_attempt_reinvoked':False}
    need(digest(model.export_evidence())==digest(read(refs['interaction']['path'])),'V11 full final interaction differs')
    need((model._pending_prompt is None if clean_stop else model._pending_prompt is not None)
        and model._selection is None and model._last_index==last_processed_index,'not the exact closed boundary')
    return model,{'valid':True,'ancestor':ancestor,'processed_indices':sorted(processed),'failed_invocation':failure,
        'next_model_index':result['next_model_index'],'clean_controlled_stop':clean_stop,'pure_protocol_changed':False,'sources':refs}
