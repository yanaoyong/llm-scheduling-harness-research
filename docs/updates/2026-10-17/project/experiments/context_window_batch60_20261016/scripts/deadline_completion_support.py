"""Reconcile a continuation's deadline with its already registered wall limit."""
from copy import deepcopy
from pathlib import Path
import shutil,time
from src.smt_fullfab.harness.contracts import encode,fingerprint,require,strict_json
from src.smt_fullfab.harness.evaluation import Evidence
from src.smt_fullfab.harness.store import Store
from src.smt_fullfab.harness.factory import restore
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness import capacity_pilot as pilot
from connection_retry_support import ConnectionRetryRuntime,validate_connection_grant
from capacity_retry_support import validate_grant
from extended_lineage_audit import verify_records

def branch(directory,group,reg,admission):
    ref=reg['deadline_reconciliation']['predecessors'][group];old=Evidence(ref['directory'],ref['evidence_sha256'])
    require(old.value['head']['phase']=='CLOSED' and old.value['head']['context_ref'] is not None,'deadline_checkpoint','Sealed observed decision context required')
    if group=='G1':
        require(old.value['head']['stop_reason']=='model_transport_or_unknown_usage','deadline_checkpoint','Exact failed G1 state required')
        validate_grant(old,reg);validate_connection_grant(old,reg)
    else:
        failure=strict_json((Path(ref['directory']).parent/(group+'.failure.json')).read_bytes())
        require(old.value['head']['stop_reason']=='final_exception:HarnessError' and failure['detail']=='time_budget: Call plus cleanup cannot fit',
                'deadline_checkpoint','Only the recorded deadline preflight stop may continue')
    attempts=old.rows('attempts');require(not any(a['status'] in ('reserved','started','unknown') for a in attempts.values()),'deadline_pending','No pending process may continue')
    directory=Path(directory);directory.mkdir(exist_ok=False);(directory/'objects').mkdir();(directory/'exports').mkdir()
    for obj in old.value['objects']:
        old.raw(obj);shutil.copyfile(old.path/'objects'/(obj+'.z'),directory/'objects'/(obj+'.z'))
    shutil.copyfile(old.path/'events.sqlite3',directory/'events.sqlite3');store=Store(directory)
    try:
        store.verify();manifest=deepcopy(old.manifest);manifest['admission']=admission
        require(manifest['fingerprint']==fingerprint(),'deadline_source','No source changes allowed')
        deadline=manifest['created_epoch']+manifest['config']['limits']['wall_seconds']
        require(deadline>manifest['deadline_epoch'] and deadline>time.time()+manifest['config']['model']['timeout_seconds']+manifest['config']['limits']['cleanup_seconds'],
                'deadline_bound','Use only the already registered remaining wall allowance')
        manifest['deadline_epoch']=deadline
        head=deepcopy(old.value['head']);head.update(phase='OBSERVED',stop_reason=None)
        marker={'checkpoint':ref,'head_before':old.value['head'],'head_after':head,'old_manifest_ref':old.value['manifest_ref'],
                'old_deadline_epoch':old.manifest['deadline_epoch'],'new_deadline_epoch':deadline,
                'basis':'original created_epoch + unchanged registered config.limits.wall_seconds',
                'config_source_state_candidates_and_costs_unchanged':True}
        with store.transaction():
            store.record('manifest','run',manifest,replace=True);store.set_meta('head',head)
            store.record('deadline_reconciliations','registered_limit',marker);store.event('deadline_reconciled',marker)
            if group=='G1':
                grant_marker={'checkpoint':ref,'head_before':old.value['head'],'head_after':head,'grant':reg['approved_connection_retry'],
                              'all_prior_records_retained':True,'old_manifest_ref':old.value['manifest_ref']}
                store.record('approved_connection_retry','one',grant_marker);store.event('approved_connection_retry',grant_marker)
        (directory/'manifest.json').write_bytes(encode(manifest)+b'\n')
        cls=ConnectionRetryRuntime if group=='G1' else Runtime
        rt=cls(store,manifest,restore(store.get(head['state_ref']),store.trace()));pilot.register_run(rt);return rt
    except BaseException:store.close();raise

def audit(ev):
    marker=ev.rows('deadline_reconciliations')['registered_limit'];ref=marker['checkpoint'];old=Evidence(ref['directory'],ref['evidence_sha256'])
    require(ev.value['events'][:len(old.value['events'])]==old.value['events'] and ev.value['physical'][:len(old.value['physical'])]==old.value['physical'],
            'deadline_audit','Prior event prefix changed')
    notes=verify_records(old,ev)
    expected=deepcopy(old.manifest);expected['admission']=ev.manifest['admission'];expected['deadline_epoch']=old.manifest['created_epoch']+old.manifest['config']['limits']['wall_seconds']
    require(expected==ev.manifest and marker['new_deadline_epoch']==expected['deadline_epoch'],'deadline_audit','Only the already declared absolute deadline may change')
    require(marker['head_after']['state_ref']==old.value['head']['state_ref'] and marker['head_after']['context_ref']==old.value['head']['context_ref'],
            'deadline_audit','Decision state or context changed')
    return {'valid':True,'only_manifest_changes':['admission','deadline_epoch'],'all_prior_calls_and_candidates_retained':True,
            'old_deadline_epoch':marker['old_deadline_epoch'],'new_deadline_epoch':marker['new_deadline_epoch'],'legitimate_note_updates':notes}
