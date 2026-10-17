"""Read-only import of a sealed pilot checkpoint, preserving every model decision.

Only the unsubmitted presentation at the old artificial cutoff is left off the
new physical branch. Its original context and events remain in the inherited
ledger and the exact removed suffix is bound in the extension marker.
"""
from copy import deepcopy
from pathlib import Path
import shutil
from src.smt_fullfab.harness.contracts import digest, encode, fingerprint, require, sha_bytes, strict_json
from src.smt_fullfab.harness.evaluation import Evidence
from src.smt_fullfab.harness.factory import restore, capture
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.store import Store
from src.smt_fullfab.harness import capacity_pilot as pilot


def checkpoint(old):
    require(old.value['head']['phase']=='CLOSED' and old.value['head']['time']==882,
            'extension_parent','Only a sealed 882-second observation can continue')
    executions=[old.get(e['payload_ref']) for e in old.value['events'] if e['kind']=='execution_batch']
    last=executions[-1]
    expected='periodic_replan' if old.manifest['admission']['group']=='G0' else 'collection_limit'
    require(last['to']==882 and last['stop_reason']['reason']==expected,
            'extension_cutoff','A real trigger or failure cannot be skipped')
    state=old.get(last['after_state_ref'])
    trace=[old.get(r) for r in old.value['physical']]
    suffix=trace[last['event_end']:]
    require(len(suffix)==1 and suffix[0]['kind']=='planning_batch_opened' and suffix[0]['time']==882,
            'extension_tail','Only one unsubmitted cutoff presentation may be omitted')
    commits=sorted(old.rows('commits').values(),key=lambda c:c['trace_start'])
    require(state['batch_state']['active_batch'] is None and digest(state['plan'])==commits[-1]['plan_sha256'],
            'extension_plan','Checkpoint must retain the last explicitly accepted model plan')
    require(len(old.rows('attempts'))==4 and all(a['channel']=='codex' and a.get('usage') is not None
            and a['status']=='processed' for a in old.rows('attempts').values()),
            'extension_cost','All four original actual requests must be reconciled')
    require(not any(c['time']>=882 for c in commits), 'extension_commit','No commit at cutoff may be discarded')
    return state,trace[:last['event_end']],suffix


def source_proof(old, current):
    a=old.manifest['fingerprint'];b=current
    changed={p for p in a['files'].keys()|b['files'].keys() if a['files'].get(p)!=b['files'].get(p)}
    require(changed=={'src/smt_fullfab/harness/capacity_pilot.py','src/smt_fullfab/harness/network.py'} and
            {k:v for k,v in a.items() if k not in ('files','sha256')}==
            {k:v for k,v in b.items() if k not in ('files','sha256')},
            'extension_source','Scheduling, execution, exporter, data and dependencies must be unchanged')
    return sorted(changed)


def branch(directory, group, reg, config, admission):
    root=Path(directory); entry=reg['predecessors'][group]
    old=Evidence(entry['directory'],entry['evidence_sha256'])
    state,trace,suffix=checkpoint(old);fp=fingerprint();changed=source_proof(old,fp)
    require(digest(config)==reg['config_sha256'][group], 'extension_config','Config differs')
    before=deepcopy(old.manifest['config']);after=deepcopy(config)
    before.pop('limits');after.pop('limits')
    require(before==after,'extension_treatment','Only resource allowances may change')
    allowed={'attempts','tokens','model_seconds','wall_seconds'}
    require(all(old.manifest['config']['limits'][k]==v for k,v in config['limits'].items() if k not in allowed),
            'extension_limits','Unrelated resource limits changed')
    require(fp['sha256']==reg['fingerprint_sha256'], 'extension_source','Unregistered source')
    require(old.manifest['initial_trace_sha256']==reg['initial_trace_sha256'] and
            old.manifest['start_time']==old.manifest['period_anchor']==702,
            'extension_origin','Original common start or periodic anchor changed')
    # Source database is never opened. A closed WAL-free file is copied, then its
    # full contents are checked against the sealed read-only evidence.
    require(not (old.path/'events.sqlite3-wal').exists(), 'extension_wal','Closed database required')
    root.mkdir(exist_ok=False);(root/'objects').mkdir();(root/'exports').mkdir()
    for ref in old.value['objects']:
        old.raw(ref)
        shutil.copyfile(old.path/'objects'/(ref+'.z'),root/'objects'/(ref+'.z'))
    shutil.copyfile(old.path/'events.sqlite3',root/'events.sqlite3')
    store=Store(root)
    try:
        store.verify()
        require(store.meta('head')==old.value['head'] and store.read('manifest','run')==old.manifest,
                'extension_database','Copied database does not match seal')
        require([dict(r) for r in store.db.execute('SELECT * FROM events ORDER BY seq')]==old.value['events'],
                'extension_database','Workflow ledger differs from seal')
        require(store.trace()==[old.get(r) for r in old.value['physical']], 'extension_database','Physical ledger differs')
        records={}
        for ns,key,ref in store.db.execute('SELECT namespace,key,ref FROM records'):
            records.setdefault(ns,{})[key]=ref
        require(records==old.value['records'],'extension_database','Record ledger differs')
        manifest=deepcopy(old.manifest)
        manifest.update(config=config,admission=admission,fingerprint=fp,
                        deadline_epoch=manifest['created_epoch']+config['limits']['wall_seconds'])
        manifest['observation_extension']={'predecessor':entry,'start':882,'end':1800,
            'origin_start':702,'inherited_actual_calls':4,'new_actual_calls_maximum':24}
        head=deepcopy(old.value['head'])
        head.update(phase='COMMITTED',context_ref=None,stop_reason=None,state_ref=store.put(state))
        marker={'predecessor':entry,'old_manifest_ref':old.value['manifest_ref'],
                'head_before':old.value['head'],'head_after':head,'checkpoint_state_sha256':digest(state),
                'retained_trace_sha256':digest(trace),'omitted_cutoff_presentation':suffix,
                'production_decisions_changed':False,'new_model_calls':0,'source_changed_files':changed,
                'original_costs_retained':True,'registration_sha256':digest(reg)}
        with store.transaction():
            store.db.execute('DELETE FROM physical WHERE seq>=?',(len(trace),))
            store.record('manifest','run',manifest,replace=True)
            store.set_meta('head',head)
            store.record('observation_extensions','882_to_1800',marker)
            store.event('observation_extension',marker)
        (root/'manifest.json').write_bytes(encode(manifest)+b'\n')
        runtime=Runtime(store,manifest,restore(state,trace))
        require(capture(runtime.env)==state,'extension_restore','Restored checkpoint differs')
        pilot.register_run(runtime)
        return runtime
    except BaseException:
        store.close();raise


def verify_inheritance(ev):
    marker=ev.rows('observation_extensions')['882_to_1800'];entry=marker['predecessor']
    old=Evidence(entry['directory'],entry['evidence_sha256']);state,trace,suffix=checkpoint(old)
    require(ev.value['events'][:len(old.value['events'])]==old.value['events'],'extension_audit','Original events changed')
    require(ev.value['physical'][:len(trace)]==old.value['physical'][:len(trace)],'extension_audit','Original physical prefix changed')
    require(marker['omitted_cutoff_presentation']==suffix and marker['checkpoint_state_sha256']==digest(state)
            and marker['retained_trace_sha256']==digest(trace),'extension_audit','Checkpoint proof changed')
    for ns,rows in old.value['records'].items():
        if ns=='manifest':continue
        require(all(ev.value['records'].get(ns,{}).get(k)==v for k,v in rows.items()),
                'extension_audit','Inherited '+ns+' changed')
    require(ev.manifest['run_id']==old.manifest['run_id'] and
            all(ev.manifest[k]==old.manifest[k] for k in ('created_epoch','initial_state_sha256',
                'initial_trace_sha256','start_time','end_time','period_anchor','prefix_events','parent')),
            'extension_audit','Original identity or clock changed')
    return {'valid':True,'inherited_calls':4,'inherited_commits':len(old.rows('commits')),
            'physical_prefix_events':len(trace),'omitted_presentation_events':len(suffix),
            'production_decisions_changed':False,'source_changed_files':source_proof(old,ev.manifest['fingerprint'])}
