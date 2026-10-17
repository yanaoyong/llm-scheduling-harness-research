"""Offline checkpoint, lineage and admission checks; transport is disabled."""
from pathlib import Path
import json,sys,tempfile,copy
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
tempfile.tempdir=str(ROOT/'.tmp')
from src.smt_fullfab.harness.offline_isolation import install_guard
install_guard()
from src.smt_fullfab.harness.contracts import digest,encode,HarnessError
from src.smt_fullfab.harness import capacity_pilot as pilot
from src.smt_fullfab.harness.evaluation import seal_evidence,Evidence,audit_provenance,audit_physical_prefix,audit_cost
from src.smt_fullfab.harness.capacity_config import audit_policy
from extended_pilot_support import branch,verify_inheritance,checkpoint
RUN=ROOT/'live_pilots/extended_three_group_20261017'
reg=json.loads((RUN/'registration.json').read_text()); rows={}
with tempfile.TemporaryDirectory(dir=ROOT/'live_pilots',prefix='offline_extension_check_') as directory:
    root=Path(directory);testreg=copy.deepcopy(reg);testreg['experiment_directory']=str(root)
    (root/'registration.json').write_bytes(encode(testreg))
    for group in reg['groups']:
        cfg=json.loads((RUN/(group+'.config.json')).read_text())
        ad={'schema':pilot.SCHEMA,'group':group,'experiment_directory':str(root),'experiment_sha256':digest(testreg),
            **{k:reg[k] for k in ('cli_binary','cli_sha256','model_catalog','model_catalog_sha256')}}
        pilot.registration(ad,config=cfg)
        try:pilot.validate_admission(ad,{'sha256':reg['fingerprint_sha256']},cfg,{'state':{},'trace':[]})
        except HarnessError as exc:assert exc.code=='pilot_continuation'
        else:raise AssertionError('Restart was not rejected')
        runtime=branch(root/group,group,testreg,cfg,ad)
        try:
            before=runtime.usage();pending_before={t['id'] for tasks in runtime.env._pending().values() for t in tasks}
            feedback=runtime.advance();after=runtime.usage()
            assert before['actual_model_attempts']==after['actual_model_attempts']==4
            assert before['offline_outputs']==after['offline_outputs']==0
            assert feedback['from']==882 and feedback['to']>882
            runtime.stop('offline_extension_checkpoint_check');sha=seal_evidence(runtime)
        finally:runtime.close()
        ev=Evidence(root/group,sha);trace=[ev.get(r) for r in ev.value['physical']]
        inh=verify_inheritance(ev);prov=audit_provenance(ev,trace)
        physics=audit_physical_prefix(trace,feedback['to'],cfg['priority_weights'],batching_policy=audit_policy(cfg['capacity_experiment'],702))
        cost=audit_cost(ev)
        assert physics['errors'] in ([],['physical: missing terminal event']),physics['errors']
        assert cost['valid'] and prov['algorithm_production_tasks']==0
        dispatch=[e for e in trace if e['kind']=='dispatch' and e['time']>=882 and e.get('task_id') in pending_before]
        rows[group]={'feedback':feedback,'inheritance':inh,'provenance':prov,'physical_errors':physics['errors'],
            'actual_calls_before':4,'actual_calls_after':4,'new_actual_calls':0,'cost_valid':cost['valid'],
            'pending_tasks_before':len(pending_before),'known_pending_dispatches':len(dispatch)}
        print(json.dumps({'group':group,'continued_to':feedback['to'],'reason':feedback['stop_reason']['reason'],
                          'new_calls':0,'physical_errors':physics['errors']}),flush=True)
    # The old grant cannot authorize this larger cutoff or the extended cap.
    bad=copy.deepcopy(testreg);bad['user_instruction']=pilot.DEADLINE_INSTRUCTION
    (root/'registration.json').write_bytes(encode(bad));ad['experiment_sha256']=digest(bad)
    try:pilot.registration(ad,config=cfg)
    except HarnessError:pass
    else:raise AssertionError('Old authorization extended silently')
value={'all_pass':True,'remote_model_calls':0,'groups':rows,'registered_source':reg['fingerprint_sha256']}
(RUN/'offline_validation.json').write_text(json.dumps(value,ensure_ascii=False,indent=2))
print('ALL OFFLINE EXTENSION CHECKS PASSED',flush=True)
