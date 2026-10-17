"""Admission for the separately approved, closed G1 call-70 connection failure.

No production, observation, proposal, execution or transport method is changed.
Both named failures remain unknown; a third unknown freezes new calls.
"""
from copy import deepcopy
from pathlib import Path
import shutil,time
from src.smt_fullfab.harness.contracts import digest,encode,fingerprint,require,sha_bytes,within_cap
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.store import Store
from src.smt_fullfab.harness.factory import restore
from src.smt_fullfab.harness.evaluation import Evidence
from src.smt_fullfab.harness.recovery import LiveEvidence,failure_kind
from src.smt_fullfab.harness import capacity_pilot as pilot
from capacity_retry_support import validate_grant
from extended_lineage_audit import verify_records

ANSWER='允许这次连接失败重试一次，保留全部失败和用量记录'

def validate_connection_grant(view,reg):
    grant=reg['approved_connection_retry']
    require(grant['user_answer']==ANSWER and grant['maximum_retries']==1 and grant['preserve_unknown_usage'] is True,
            'connection_grant','Exact second, separately approved one-time retry required')
    attempt=view.rows('attempts')[grant['attempt_id']]
    require(attempt['index']==69 and digest(attempt)==grant['attempt_sha256'] and failure_kind(view,attempt)=='connection',
            'connection_evidence','Only the named closed empty connection failure is exempt')
    require(sha_bytes(Path(__file__).read_bytes())==reg['connection_retry_support_sha256'],
            'connection_source','Retry admission helper changed')
    return attempt

class ConnectionRetryRuntime(Runtime):
    def check_admission(self,*,actual=False,reserve=0):
        super().check_admission(actual=False,reserve=reserve)
        reg=pilot.registration(self.manifest['admission'],config=self.config)
        view=LiveEvidence(self.store.path);first=validate_grant(view,reg);second=validate_connection_grant(view,reg)
        if not actual:return
        require(self.manifest['fingerprint']==fingerprint(),'connection_source','Registered source changed')
        usage=self.usage();budget=self.wall_budget();limits=budget['limits']
        unknown=[a for _,a in self.store.rows('attempts') if a['channel']=='codex' and a['status'] not in ('reserved','not_sent') and a.get('usage') is None]
        require(len(unknown)==2 and {a['attempt_id'] for a in unknown}=={first['attempt_id'],second['attempt_id']} and usage['pending_attempts']==0,
                'connection_unknown','Any further unknown failure freezes new calls')
        require(time.time()>=second['finished_epoch']+60,'connection_cooldown','Proven failure cooldown required')
        require(self.manifest['mode']=='model' and within_cap(usage['actual_model_attempts']+1,limits['attempts']),
                'attempt_budget','Every inherited call and retry counts against the same cap')
        require(within_cap(usage['input_tokens']+usage['output_tokens']+usage['reserved_tokens']+reserve,limits['tokens']),
                'token_budget','Known usage plus reservation exceeds cap')
        timeout=self.config['model']['timeout_seconds']
        require(usage['model_seconds']+timeout<=limits['model_seconds'] and time.time()+timeout+limits['cleanup_seconds']<budget['effective_deadline_epoch'],
                'time_budget','Original time and cleanup checks remain in force')
        from src.smt_fullfab.harness.experiment import check_experiment_budget
        check_experiment_budget(self,reserve,budget=budget)

def branch(directory,reg,admission):
    ref=reg['connection_retry_checkpoint'];old=Evidence(ref['directory'],ref['evidence_sha256'])
    validate_grant(old,reg);validate_connection_grant(old,reg)
    require(old.value['head']['phase']=='CLOSED','connection_checkpoint','Sealed checkpoint required')
    directory=Path(directory);directory.mkdir(exist_ok=False);(directory/'objects').mkdir();(directory/'exports').mkdir()
    for obj in old.value['objects']:
        old.raw(obj);shutil.copyfile(old.path/'objects'/(obj+'.z'),directory/'objects'/(obj+'.z'))
    shutil.copyfile(old.path/'events.sqlite3',directory/'events.sqlite3');store=Store(directory)
    try:
        store.verify();manifest=deepcopy(old.manifest);manifest['admission']=admission
        require(manifest['fingerprint']==fingerprint(),'connection_source','Source differs from stopped run')
        head=deepcopy(old.value['head']);head.update(phase='OBSERVED',stop_reason=None)
        marker={'checkpoint':ref,'head_before':old.value['head'],'head_after':head,
                'grant':reg['approved_connection_retry'],'all_prior_records_retained':True,'old_manifest_ref':old.value['manifest_ref']}
        with store.transaction():
            store.record('manifest','run',manifest,replace=True);store.set_meta('head',head)
            store.record('approved_connection_retry','one',marker);store.event('approved_connection_retry',marker)
        (directory/'manifest.json').write_bytes(encode(manifest)+b'\n')
        runtime=ConnectionRetryRuntime(store,manifest,restore(store.get(head['state_ref']),store.trace()))
        pilot.register_run(runtime);return runtime
    except BaseException:store.close();raise

def audit(ev):
    marker=ev.rows('approved_connection_retry')['one'];ref=marker['checkpoint'];old=Evidence(ref['directory'],ref['evidence_sha256'])
    reg=pilot.registration(ev.manifest['admission'],config=ev.manifest['config']);failed=validate_connection_grant(ev,reg);validate_grant(ev,reg)
    require(ev.value['events'][:len(old.value['events'])]==old.value['events'] and ev.value['physical'][:len(old.value['physical'])]==old.value['physical'],
            'connection_audit','Prior event or physical prefix changed')
    notes=verify_records(old,ev)
    require(ev.manifest['config']==old.manifest['config'] and ev.manifest['fingerprint']==old.manifest['fingerprint'],
            'connection_audit','Model, budgets, production rules or source changed')
    require(marker['head_after']['state_ref']==old.value['head']['state_ref'] and marker['head_after']['context_ref']==old.value['head']['context_ref'],
            'connection_audit','Factory state or active context was reset')
    newer=[a for a in ev.rows('attempts').values() if a['index']>failed['index']]
    if newer:require(min(a['reserved_epoch'] for a in newer)>=failed['finished_epoch']+60,'connection_audit','Cooldown violated')
    return {'valid':True,'failed_attempt_retained':failed['attempt_id'],'unknown_usage_retained':failed['usage'] is None,
            'same_state_context_model_and_production_rules':True,'new_actual_calls':len(newer),'legitimate_note_updates':notes}
