"""Resume sealed per-group budget cutoffs, preserving every prior decision.

This is experiment resource bookkeeping only: same model, input budgets,
production rules, candidates, factory state, clock and accumulated costs.
"""
from pathlib import Path
from copy import deepcopy
import shutil
from src.smt_fullfab.harness.contracts import digest,encode,fingerprint,require,sha_bytes
from src.smt_fullfab.harness.evaluation import Evidence
from src.smt_fullfab.harness.store import Store
from src.smt_fullfab.harness.factory import restore
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness import capacity_pilot as pilot
from capacity_retry_support import ApprovedCapacityRuntime
from extended_lineage_audit import verify_records


def branch(directory,group,reg,cfg,admission):
    ref=reg['resource_continuation']['predecessors'][group];old=Evidence(ref['directory'],ref['evidence_sha256'])
    require(old.value['head']['phase']=='CLOSED' and old.value['head']['stop_reason']=='pilot_attempt_cap',
            'resource_checkpoint','Only a sealed call-cap stop can continue')
    attempts=old.rows('attempts')
    require(len(attempts)==64 and all(a['status'] not in ('reserved','started') for a in attempts.values()),
            'resource_attempts','Exact previous cap with no pending requests required')
    previous=deepcopy(old.manifest['config']);previous['limits']=cfg['limits']
    require(previous==cfg,'resource_treatment','Only resource limits may differ')
    before=old.manifest['fingerprint']['files'];after=fingerprint()['files']
    changed={p for p in set(before)|set(after) if before.get(p)!=after.get(p)}
    require(changed=={'src/smt_fullfab/harness/capacity_pilot.py'},'resource_source','Only continuation admission may change')
    directory=Path(directory);directory.mkdir(exist_ok=False);(directory/'objects').mkdir();(directory/'exports').mkdir()
    for obj in old.value['objects']:
        old.raw(obj);shutil.copyfile(old.path/'objects'/(obj+'.z'),directory/'objects'/(obj+'.z'))
    shutil.copyfile(old.path/'events.sqlite3',directory/'events.sqlite3')
    store=Store(directory)
    try:
        store.verify();manifest=deepcopy(old.manifest);manifest.update(config=cfg,admission=admission,fingerprint=fingerprint())
        head=deepcopy(old.value['head']);require(head['context_ref'] is not None,'resource_context','Keep the exact active decision context')
        head.update(phase='OBSERVED',stop_reason=None)
        marker={'predecessor':ref,'old_manifest_ref':old.value['manifest_ref'],'head_before':old.value['head'],
                'head_after':head,'only_config_change':'limits','only_source_change':sorted(changed),
                'all_prior_calls_and_costs_retained':True,'old_call_cap':64,'new_call_cap':96}
        with store.transaction():
            store.record('manifest','run',manifest,replace=True);store.set_meta('head',head)
            store.record('resource_continuations','64_to_96',marker);store.event('resource_continuation',marker)
        (directory/'manifest.json').write_bytes(encode(manifest)+b'\n')
        cls=ApprovedCapacityRuntime if group=='G1' else Runtime
        rt=cls(store,manifest,restore(store.get(head['state_ref']),store.trace()));pilot.register_run(rt)
        return rt
    except BaseException:store.close();raise


def audit(ev):
    marker=ev.rows('resource_continuations')['64_to_96'];ref=marker['predecessor'];old=Evidence(ref['directory'],ref['evidence_sha256'])
    require(ev.value['events'][:len(old.value['events'])]==old.value['events'] and
            ev.value['physical'][:len(old.value['physical'])]==old.value['physical'],'resource_audit','Inherited event prefix changed')
    notes=verify_records(old,ev)
    previous=deepcopy(old.manifest['config']);previous['limits']=ev.manifest['config']['limits']
    require(previous==ev.manifest['config'],'resource_audit','Production configuration changed')
    require(marker['head_after']['state_ref']==old.value['head']['state_ref'] and
            marker['head_after']['context_ref']==old.value['head']['context_ref'],'resource_audit','State or context changed')
    return {'valid':True,'inherited_calls':64,'same_factory_state_and_active_context':True,
            'same_production_configuration':True,'legitimate_note_updates':notes}
