"""One explicitly approved, proven closed capacity refusal; costs stay unknown.

This subclass only extends admission for the named failed request. It inherits
all observation, proposal, commit, execution, transport and accounting methods.
"""
from copy import deepcopy
from pathlib import Path
import sqlite3,shutil,time
from src.smt_fullfab.harness.contracts import digest,encode,fingerprint,require,sha_bytes,strict_json,within_cap
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.store import Store
from src.smt_fullfab.harness.factory import restore
from src.smt_fullfab.harness.evaluation import Evidence,seal_evidence
from src.smt_fullfab.harness.recovery import LiveEvidence,failure_kind
from src.smt_fullfab.harness import capacity_pilot as pilot

ANSWER='允许重试一次，失败和未知用量照常保留'

def validate_grant(view,reg):
    grant=reg['approved_capacity_retry'];aid=grant['attempt_id']
    require(grant['user_answer']==ANSWER and grant['maximum_retries']==1 and grant['preserve_unknown_usage'] is True,
            'retry_grant','Exact bounded user approval required')
    attempt=view.rows('attempts')[aid]
    require(digest(attempt)==grant['attempt_sha256'] and failure_kind(view,attempt)=='capacity',
            'retry_evidence','Only the named terminated empty capacity response is exempt')
    require(sha_bytes(Path(__file__).read_bytes())==reg['retry_support_sha256'],'retry_source','Admission helper changed')
    return attempt

class ApprovedCapacityRuntime(Runtime):
    def check_admission(self,*,actual=False,reserve=0):
        # The standard phase, stop-file, wall-clock and storage checks still run.
        super().check_admission(actual=False,reserve=reserve)
        reg=pilot.registration(self.manifest['admission'],config=self.config)
        failed=validate_grant(LiveEvidence(self.store.path),reg)
        if not actual:return
        require(self.manifest['fingerprint']==fingerprint(),'retry_source','Registered source changed')
        usage=self.usage();limits=self.wall_budget()['limits']
        unknown=[a for _,a in self.store.rows('attempts') if a['channel']=='codex' and a['status'] not in ('reserved','not_sent') and a.get('usage') is None]
        require(len(unknown)==1 and unknown[0]['attempt_id']==failed['attempt_id'] and usage['pending_attempts']==0,
                'retry_unknown','Any additional unknown failure freezes new calls')
        require(time.time()>=failed['finished_epoch']+60,'retry_cooldown','Wait at least 60 seconds after the proven failure')
        require(self.manifest['mode']=='model' and within_cap(usage['actual_model_attempts']+1,limits['attempts']),
                'attempt_budget','All inherited calls and the retry count toward the same cap')
        require(within_cap(usage['input_tokens']+usage['output_tokens']+usage['reserved_tokens']+reserve,limits['tokens']),
                'token_budget','Known usage plus reservation exceeds cap; failed usage remains separately unknown')
        timeout=self.config['model']['timeout_seconds'];budget=self.wall_budget()
        require(usage['model_seconds']+timeout<=limits['model_seconds'] and
                time.time()+timeout+limits['cleanup_seconds']<budget['effective_deadline_epoch'],
                'time_budget','Original time and cleanup checks remain in force')
        from src.smt_fullfab.harness.experiment import check_experiment_budget
        check_experiment_budget(self,reserve,budget=budget)


def snapshot_stopped(source,destination):
    """Back up a stopped independent run through a read-only SQLite connection."""
    source=Path(source);destination=Path(destination)
    destination.mkdir(exist_ok=False);(destination/'objects').mkdir();(destination/'exports').mkdir()
    with sqlite3.connect(f'file:{source / "events.sqlite3"}?mode=ro',uri=True) as original:
        with sqlite3.connect(destination/'events.sqlite3') as copied:original.backup(copied)
    # The source is STOPPED; later sealing may add objects but cannot alter them.
    for p in (source/'objects').glob('*.z'):shutil.copyfile(p,destination/'objects'/p.name)
    store=Store(destination)
    try:
        store.verify();manifest=store.read('manifest','run');head=store.meta('head')
        require(head['phase']=='STOPPED' and head['stop_reason']=='model_transport_or_unknown_usage',
                'retry_snapshot','Only the stopped transport failure may be copied')
        runtime=Runtime(store,manifest,restore(store.get(head['state_ref']),store.trace()))
        with store.transaction():
            store.record('capacity_retry_snapshot','origin',{'directory':str(source.resolve()),
                'head':head,'last_source_event':dict(store.db.execute('SELECT * FROM events ORDER BY seq DESC LIMIT 1').fetchone()),
                'source_database_opened_read_only':True,'new_model_calls':0})
        return seal_evidence(runtime)
    finally:store.close()


def retry_branch(directory,reg,admission):
    old=Evidence(reg['retry_checkpoint']['directory'],reg['retry_checkpoint']['evidence_sha256'])
    validate_grant(old,reg)
    require(old.value['head']['phase']=='CLOSED','retry_checkpoint','Sealed checkpoint required')
    directory=Path(directory);directory.mkdir(exist_ok=False);(directory/'objects').mkdir();(directory/'exports').mkdir()
    for ref in old.value['objects']:
        old.raw(ref);shutil.copyfile(old.path/'objects'/(ref+'.z'),directory/'objects'/(ref+'.z'))
    shutil.copyfile(old.path/'events.sqlite3',directory/'events.sqlite3')
    store=Store(directory)
    try:
        store.verify();manifest=deepcopy(old.manifest);manifest['admission']=admission
        require(manifest['fingerprint']==fingerprint(),'retry_source','Source differs from frozen stopped run')
        head=deepcopy(old.value['head']);head.update(phase='OBSERVED',stop_reason=None)
        marker={'checkpoint':reg['retry_checkpoint'],'head_before':old.value['head'],'head_after':head,
                'grant':reg['approved_capacity_retry'],'all_prior_records_retained':True,
                'state_and_physical_trace_unchanged':True,'old_manifest_ref':old.value['manifest_ref']}
        with store.transaction():
            store.record('manifest','run',manifest,replace=True);store.set_meta('head',head)
            store.record('approved_capacity_retry','one',marker);store.event('approved_capacity_retry',marker)
        (directory/'manifest.json').write_bytes(encode(manifest)+b'\n')
        runtime=ApprovedCapacityRuntime(store,manifest,restore(store.get(head['state_ref']),store.trace()))
        pilot.register_run(runtime);return runtime
    except BaseException:store.close();raise


def audit_retry(ev):
    marker=ev.rows('approved_capacity_retry')['one'];ref=marker['checkpoint'];old=Evidence(ref['directory'],ref['evidence_sha256'])
    reg=pilot.registration(ev.manifest['admission'],config=ev.manifest['config']);failed=validate_grant(ev,reg)
    require(ev.value['events'][:len(old.value['events'])]==old.value['events'] and
            ev.value['physical'][:len(old.value['physical'])]==old.value['physical'],
            'retry_audit','Prior workflow or physical prefix changed')
    from extended_lineage_audit import verify_records
    note_updates=verify_records(old,ev)
    newer=[a for a in ev.rows('attempts').values() if a['index']>failed['index']]
    if newer:require(min(a['reserved_epoch'] for a in newer)>=failed['finished_epoch']+60,'retry_audit','Cooldown violated')
    require(ev.get(marker['head_after']['state_ref'])==old.get(old.value['head']['state_ref']),
            'retry_audit','Factory or batch state was reset')
    return {'valid':True,'failed_attempt_retained':failed['attempt_id'],'unknown_usage_retained':failed['usage'] is None,
            'source_checkpoint_unchanged':True,'new_actual_calls':len(newer),'same_model_and_production_rules':True,'legitimate_note_updates':note_updates}
