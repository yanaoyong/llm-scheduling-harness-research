"""Exact read-only replay of a closed V9 suffix; never invokes transport/physics."""
from pathlib import Path
from base64 import b64decode
import sqlite3,json,hashlib
from .recovery import need,read,sha
from .journal import digest as journal_digest
from .workflow.interaction import digest,render
from . import prompt_schema,policy

def restore_suffix(model,contract,*,source_root):
    refs=contract['refs']
    for ref in refs.values():need(sha(ref['path'])==ref['sha256'],'V9 predecessor evidence changed')
    m=read(refs['manifest']['path']);r=Path(m['segment_path']);c=Path(refs['manifest']['path']).parent
    result=read(refs['result']['path']);need(result['new_commits']==0 and result['next_model_index']>=238,'only closed uncommitted V9 continuation supported')
    ancestor=None
    if m.get('resume_suffix'):
        model,ancestor=restore_suffix(model,m['resume_suffix'],source_root=source_root)
    need(result.get('finalization_error') is None,'predecessor finalization incomplete')
    outer=read(refs['outer']['path']);need(outer['guard']['lifecycle_complete'] and outer['guard']['command_returncode']==1,'actual failed parent lifecycle incomplete')
    for p,h in m['runtime_files'].items():need(sha(c/'frozen'/p)==h,'predecessor frozen source changed')
    # Pure interaction/protocol modules must remain exact. Host/admission suffix is separately versioned.
    for p in ('policy.py','prompt_schema.py','workflow/interaction.py','workflow/B_delta_prompt.py','workflow/B_delta_assembly.py','workflow/B_feedback_admission.py'):
        rel='src/smt_fullfab/B_memory_progress_v9/'+p
        need(sha(Path(source_root)/rel)==m['runtime_files'][rel],'pure V9 protocol changed across continuation')
    db=sqlite3.connect(Path(refs['database']['path']).resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
    need(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','predecessor journal invalid')
    tail=None;records=0;processed=[];starts={}
    for seq,kind,text,prev,h in db.execute('SELECT * FROM events ORDER BY seq'):
        payload=json.loads(text);need(seq==records and prev==tail and journal_digest({'seq':seq,'kind':kind,'payload':payload,'previous':prev})==h,'predecessor suffix chain differs')
        if kind=='call_started':starts[payload['model_index']]=payload
        if kind=='action_processed':processed.append(payload)
        need(kind not in ('commit_intent','commit_receipt'),'cannot continue possibly committed suffix')
        tail=h;records+=1
    db.close();need(records==result['durable_prefix']['journal_records'] and tail==result['durable_prefix']['journal_tail_sha256'],'predecessor prefix differs')
    expected_indices=list(range(m.get('first_model_index',237),result['next_model_index']))
    need([x['model_index'] for x in processed]==expected_indices and set(starts)==set(expected_indices),'not exact complete processed boundary')
    ledger=[json.loads(x) for x in Path(refs['ledger']['path']).read_bytes().splitlines()]
    from src.smt_fullfab import model_process_guard
    for event in processed:
        i=event['model_index'];mdir=r/f'model_{i:05d}';record=read(event['record_file'])
        need(sha(event['record_file'])==event['record_file_sha256'] and sha(event['result_file'])==event['result_file_sha256'],'original action record/result hash differs')
        p=model.next_prompt();need(p['prompt_sha256']==starts[i]['prompt_sha256']==record['issued_prompt_sha256'],'replayed prompt differs')
        need((mdir/'prompt.txt').read_text()==p['prompt'],'raw issued prompt differs')
        s=prompt_schema.schema_for_prompt(p['prompt'],model.context());need((mdir/'schema.json').read_bytes()==prompt_schema.schema_bytes(s),'schema differs')
        original=read(mdir/'result.json');request=read(mdir/'request.json');command=read(mdir/'command.json')
        model_process_guard.verify_lifecycle(mdir,expected_command=command['argv'],expected_timeout=600,expected_call_id=event['call_id'],expected_fingerprint=request['request_fingerprint'],expected_evidence=original['process_guard'])
        ends=[x for x in ledger if x.get('event')=='finish' and x['call_id']==event['call_id']];need(len(ends)==1 and ends[0]['status']==original['status']=='success','original finish mismatch')
        need(ends[0]['details']['usage']==original['usage'],'original cost differs')
        raw=(mdir/'final.txt').read_bytes();need(raw==b64decode(record['raw_output_base64']),'raw final differs')
        policy.classify(policy.strict_json(raw),p['prompt'],model.context(),s)
        reply=model.handle(raw,call_id=event['call_id'],model_index=i)
        need(reply['record_sha256']==event['record_sha256']==record['record_sha256'],'exact suffix replay differs')
    evidence=read(refs['interaction']['path']);need(digest(model.export_evidence())==digest(evidence),'all retained state/history/memory differs')
    need(model._pending_prompt is None and model._selection is None and model._last_index==result['next_model_index']-1,'not clean new boundary')
    return model,{'valid':True,'replayed_model_indices':expected_indices,'next_model_index':result['next_model_index'],'ancestor':ancestor,'original_output_reinvoked':False,
        'parent_database_sha256':refs['database']['sha256'],'complete_interaction_sha256':digest(evidence),
        'memory_serialized_characters':len(render(model._memory['memory'])),'sources':refs}
