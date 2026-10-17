"""Reuse certified lineage; replay only the two unfinished-plan outputs."""
from base64 import b64decode
from pathlib import Path
from src.smt_fullfab.B_candidate_paths_v14.recovery import need,read,sha
from src.smt_fullfab.B_candidate_paths_v14.workflow.interaction import Interaction,digest
from src.smt_fullfab.B_candidate_paths_v14 import policy,prompt_schema

def restore(contract):
    refs=contract['refs']
    for ref in refs.values():need(sha(ref['path'])==ref['sha256'],'certified boundary input changed')
    proof=read(refs['certification']['path'])
    need(proof['valid'] and proof['clean_controlled_stop'] and proof['commits_verified']==71 and proof['total_lineage_commits']==86,'uncertified lineage')
    for ref in proof['sources']:need(sha(ref['path'])==ref['sha256'],'certified lineage source changed')
    need(read(refs['certification_actual_exit']['path'])['exit_code']==0,'certification did not actually finish')
    final=read(refs['interaction']['path']);boot=read(refs['bootstrap']['path']);previous=read(refs['previous']['path'])
    receipt=read(refs['receipt']['path']);advance=contract['last_advance']
    need(digest(final['bootstrap'])==digest(boot),'final bootstrap differs')
    model=Interaction(boot['base_plan'],boot['problem'],boot['execution_state'],source_sha256=boot['source_sha256'],paging=boot['paging'])
    model.bind_execution(previous,stop=advance['stop'],commit_receipt=receipt)
    run=Path(refs['interaction']['path']).parent
    indices=[]
    for record in final['history']:
        i=record['model_index'];mdir=run/f'model_{i:05d}'
        need(record==read(run/f'call_{i:05d}/record.json'),'current-plan output differs')
        issued=model.next_prompt()
        need(issued['prompt_sha256']==record['issued_prompt_sha256'] and (mdir/'prompt.txt').read_text()==issued['prompt'],'current-plan prompt differs')
        schema=prompt_schema.schema_for_prompt(issued['prompt'],model.context())
        need((mdir/'schema.json').read_bytes()==prompt_schema.schema_bytes(schema),'current-plan schema differs')
        raw=b64decode(record['raw_output_base64']);need(raw==(mdir/'final.txt').read_bytes(),'current-plan raw output differs')
        policy.classify(policy.strict_json(raw),issued['prompt'],model.context(),schema)
        outcome=model.handle(raw,call_id=record['call_id'],model_index=i)
        need(outcome==read(run/f'call_{i:05d}/outcome.json'),'current-plan full outcome differs');indices.append(i)
    need(indices==[1288,1289] and digest(model.export_evidence())==digest(final),'complete restored interaction differs')
    need(model._selection is None and model._pending_prompt is None,'boundary not clean')
    return model,advance,{'valid':True,'lineage_certification':refs['certification'],'replayed_only_current_plan_indices':indices,
        'complete_original_final_evidence_sha256':digest(final),'model_calls':0,'physical_advance':False,'protocol_changed':False}
