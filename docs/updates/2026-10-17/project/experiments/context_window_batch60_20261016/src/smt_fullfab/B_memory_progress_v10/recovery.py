"""Read-only, one-boundary certification of V8 sources, store and ledger."""
from pathlib import Path
import hashlib,json,sqlite3,os
from contextlib import closing

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def read(path):return json.loads(Path(path).read_bytes())
def new(path,value):
    with Path(path).open('x') as f:
        json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
    return sha(path)
def need(value,message):
    if not value:raise ValueError(message)

def recover(root, source_root):
    root=Path(root);source_root=Path(source_root)
    h=read(root/'progress/smt_fullfab/STOP_HANDOFF_20261011.json')
    refs={**h['source_refs'],**{k:v for k,v in h['state'].items() if isinstance(v,dict) and 'path' in v}}
    for name,ref in refs.items():need(sha(ref['path'])==ref['sha256'],'handoff original changed: '+name)
    need(h['execution']['serial_occupancy_released'] and h['execution']['no_call237_started'],'old owner not closed')
    run=Path(h['run_segment']);campaign=Path(h['campaign']);m=read(campaign/'manifest.json')
    for path,expected in m['runtime_files'].items():
        need(sha(source_root/path)==expected,'old frozen source differs: '+path)
    from src.smt_fullfab import budget
    from src.smt_fullfab.B_direct_v8 import bridge
    from src.smt_fullfab.B_v8_launch_recovery import admission as original
    from src.smt_fullfab.B_v8_preserved_resume_v1 import admission,continuation_store
    budget.ROOT=root
    cfg=m['original_runtime_config'];runtime=bridge.durable
    bridge.binding.configure_admission(original,package_config=cfg['package'],
        dependency_paths=[source_root/p for p in cfg['runtime_files'] if p.endswith('.py')])
    expected=read(cfg['expected_runtime_manifest']['path'])
    need(runtime.same(runtime.runtime_manifest(),expected),'original complete runtime map differs')
    cm=h['source_refs']['continuation_manifest']
    proof=continuation_store.recover_read_only(run/'plan_00001/durable',runtime=runtime,
        expected_manifest_sha256=cm['sha256'],expected_prefix=h['state']['durable_prefix'])
    need(proof['valid'] and proof['pure_replay_verified'],'original continuation replay failed')
    raw=Path(h['state']['active_database']['path']).read_bytes()
    with closing(sqlite3.connect(':memory:')) as db:
        db.deserialize(raw);db.execute('PRAGMA query_only=ON')
        state,gj,gb=runtime.DurableInteractionStore._load(db)
        need(len(state['sessions'])==1,'multiple parent interactions')
        sid=next(iter(state['sessions']));session=state['sessions'][sid]
        need(all(state['attempts'][aid]['action'] is not None for aid in session['attempt_ids']), 'pending parent attempt')
        parent=runtime.replay_session(sid,state,gj,gb)
    ev=parent.export_evidence();need(runtime.same(ev,proof['interactions'][0]['evidence']),'full independent parent replay differs')
    need(parent._last_index==236 and parent._pending_prompt is None and parent._selection is None,'not processed 236 boundary')
    need(parent._drafts['recovery_01'].state_sha256==h['state']['draft_state_sha256_from_last_accepted_chunk'],'draft state differs')
    need(runtime.digest(parent._memory['memory'])==h['state']['last_memory_canonical_json_sha256'],'memory differs')
    ledger_raw=Path(h['source_refs']['ledger_snapshot']['path']).read_bytes()
    rows=[json.loads(x) for x in ledger_raw.splitlines()]
    approvals=[r['approval'] for r in rows if r.get('event')=='approval'];need(len(approvals)==1,'approval ambiguous')
    account=admission.audit_admissions(rows,approvals[0],root=root,package_config={
        'path':str(campaign/'recovery_package.json'),'sha256':sha(campaign/'recovery_package.json')})
    need(not account['errors'] and not account['missing_evidence'],'original ledger audit: '+repr(account['errors']))
    need(budget.BudgetLedger.account(rows)['pending']==[h['cost']['historical_unresolved_V4_call_id_preserved']], 'unrecognized pending predecessor call')
    return parent,{'valid':True,'parent_evidence_sha256':runtime.digest(ev),
        'original_runtime_sha256':runtime.digest(expected),'handoff_sha256':sha(root/'progress/smt_fullfab/STOP_HANDOFF_20261011.json'),
        'parent_database_sha256':sha(h['state']['active_database']['path']),
        'parent_context':parent.context(),'history_count':len(parent._history),'last_index':236,
        'next_index':237,'drafts':parent.runtime_references()['drafts'],
        'memory_serialized_characters':len(runtime.interaction.render(parent._memory['memory'])),
        'ledger_prefix_sha256':sha(h['source_refs']['ledger_snapshot']['path']),
        'ledger_prefix_bytes':len(ledger_raw),'ledger_prefix_records':len(rows),
        'research_account':budget.BudgetLedger.account(rows),'B_lineage_account':account['recovery_account'],
        'prior_registration':account['preserved_mapping']['original_registration']},h
