"""Explicit one-call bridge; no default transport and no CLI entry point.

Only an explicitly injected call function can invoke a transport. Recovery is
read-only and never retries, finishes a budget record, handles an action, or
commits a physical plan. Local evidence consistency is not backend authenticity.
"""
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from src.smt_fullfab import B_delta_durable as durable
from src.smt_fullfab import B_delta_transport_binding as binding

SCHEMA='draft-smt-fullfab-B-delta-call-bridge-v1'
FILES=(*binding.FILES,'stderr.log','result.json.tmp','request.json.tmp','command.json.tmp')
AUTH_FIELDS={'ledger_path','ledger_before_sha256','approval_sha256','registration_id','registration_sha256','disabled_skill_paths'}
FLAGS={'backend_invocation_independently_proven':False,'backend_identity_independently_proven':False,
       'physical_commit_performed':False,'physical_validation_performed':False,
       'automatic_retry_allowed':False,'budget_finish_repair_performed':False,
       'cross_store_deduplication_certified':False}


class BridgeError(ValueError):pass

def require(value,message):
    if not value:raise BridgeError(message)

def encode(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':'))+'\n').encode()
def sha(raw):return hashlib.sha256(raw).hexdigest()

def write_bytes(path,raw):
    with Path(path).open('xb') as stream:
        written=stream.write(raw)
        if type(written)is not int or written!=len(raw):raise OSError('bridge evidence short write')
        stream.flush();os.fsync(stream.fileno())

def save_json(path,value):
    raw=encode(value);write_bytes(path,raw);return sha(raw)

def error(exc):return {'type':type(exc).__name__,'message':str(exc)}

def original_rows(raw):
    rows=[(binding.parse(line),line) for line in raw.splitlines(keepends=True) if line.strip()]
    require(all(type(row)is dict for row,_ in rows),'ledger rows must be objects')
    return rows


def check_authority(raw,authorization,config,run_dir):
    """The transport still owns actual admission/reservation; this is no reserve."""
    require(type(authorization)is dict and set(authorization)==AUTH_FIELDS,'complete external authorization anchors required')
    require(sha(raw)==authorization['ledger_before_sha256'],'external ledger prefix hash mismatch')
    require(type(authorization['disabled_skill_paths'])is list and all(type(p)is str and Path(p).is_absolute() for p in authorization['disabled_skill_paths']),
            'explicit frozen disabled skill inventory required')
    require(config.get('ledger_path')==authorization['ledger_path']==str(Path(authorization['ledger_path']).resolve()),'original ledger path/config mismatch')
    require(config.get('model')=='gpt-6-astra' and config.get('reasoning_effort')=='medium' and binding.finite(config.get('timeout_seconds'))
            and 1<=config['timeout_seconds']<=180,'fixed model/effort and bounded timeout required')
    rows=[r for r,_ in original_rows(raw)]
    approvals=[r['approval'] for r in rows if r.get('event')=='approval']
    require(len(approvals)==1 and binding._record_digest(approvals[0])==authorization['approval_sha256'],'original approved record hash mismatch')
    replay=binding._audit_ledger_admission(rows,approvals[0]);ctor=binding.audit_constructor_ledger(rows)
    require(not replay['errors'] and not replay['missing_evidence'] and not ctor['errors'],'invalid preceding ledger authorization/account')
    registration=replay['registered_runs'].get(str(Path(run_dir).parent))
    require(registration is not None and registration['arm']=='B' and registration['registration_id']==authorization['registration_id']
            and binding._record_digest(registration)==authorization['registration_sha256'],'preceding B registration mismatch')
    require(config.get('phase')==registration['phase'] and config.get('grant_id')==registration['budget_id'],'phase/grant differs from registration')
    require(binding.same(config.get('authorization_context'),{'purpose':'B','arm':'B','scenario':registration['scenario'],'window_seconds':registration['window_seconds']}),
            'scenario/window/arm differs from registration')
    pending=set()
    for row in rows:
        if row.get('event') in ('reserve','solver_reserve','constructor_reserve'):pending.add(row['call_id'])
        elif row.get('event') in ('finish','solver_finish','constructor_finish'):pending.discard(row['call_id'])
    require(not pending,'preceding unresolved model/solver/constructor reservation forbids a new call')
    require(not any(r.get('event')=='reserve' and r.get('run_id')==run_dir for r in rows),'transport directory already used in original ledger')
    return registration


def inspect_store(store,expected_store_id,attempt_id=None):
    """One verified DB snapshot supplies attempt state, not executable candidates."""
    proof=durable.recover_read_only(store.directory,expected_store_id=expected_store_id)
    require(proof['valid'] and proof['pure_replay_verified'],'durable pure recovery failed')
    with store._lock(False):
        store._ready();raw,ident=durable.database_snapshot(store)
        require(sha(raw)==proof['database_sha256'],'durable state changed during inspection')
        with closing(sqlite3.connect(':memory:')) as db:
            db.deserialize(raw);db.execute('PRAGMA query_only=ON');state,gj,get_blob=store._load(db)
            contexts={sid:durable.fresh_session(gj(s['bootstrap_blob'])).context() for sid,s in state['sessions'].items()}
            if attempt_id in state['attempts']:
                attempt=state['attempts'][attempt_id]
                spec=gj(attempt['spec_blob'])
                state['_inspected_attempt']={'spec':spec,'prompt':gj(attempt['prompt_blob']),
                    'schema_bytes':get_blob(spec['schema_blob']),'attached_bytes':{}}
                attached=state['_inspected_attempt']['attached_bytes']
                for stage,fields in (('request',{'request.json':'request_blob','reserve_line':'reserve_blob',
                        'attempt.claim':'claim_blob','prompt.txt':'prompt_file_blob','schema.json':'schema_file_blob'}),
                        ('completion',{'result.json':'result_blob','finish_line':'finish_blob',
                        'events.jsonl':'events_blob','final.txt':'final_blob'})):
                    if attempt[stage] is not None:
                        for name,key in fields.items():
                            ref=attempt[stage][key]
                            if ref is not None:attached[name]=get_blob(ref)
        require(durable.identity(os.stat(store.path,follow_symlinks=False))==ident,'durable path changed during inspection')
    return proof,state,contexts


def capture_originals(run_dir,ledger_path):
    raw={};descriptors={};missing=[];errors=[]
    for name,path in [('ledger',Path(ledger_path)),*((name,Path(run_dir)/name) for name in FILES)]:
        try:
            data,proof=binding.read_snapshot(path)
            raw[name]=data;descriptors[name]=proof
        except FileNotFoundError:missing.append(name)
        except Exception as exc:errors.append({'name':name,**error(exc)})
    require(sum(map(len,raw.values()))<=binding.MAX_TOTAL_BYTES,'original evidence exceeds capture cap; originals retained')
    return raw,{'files':descriptors,'missing':missing,'errors':errors}


def archive_originals(directory,raw,receipt):
    target=directory/'raw';target.mkdir()
    for name,data in raw.items():write_bytes(target/(name+'.bin'),data)
    return save_json(directory/'capture.json',receipt)


def ledger_lines(raw):
    request=binding.parse(raw['request.json']);cid=request.get('call_id')
    require(type(cid)is str and cid,'original request has no call ID')
    rows=original_rows(raw['ledger'])
    reserves=[line for row,line in rows if row.get('event')=='reserve' and row.get('call_id')==cid]
    finishes=[line for row,line in rows if row.get('event')=='finish' and row.get('call_id')==cid]
    require(len(reserves)==1 and len(finishes)<=1,'ambiguous original reserve/finish identity')
    return cid,reserves[0],finishes[0] if finishes else None


def bind_success(intent,prompt,ledger_snapshot_path,raw):
    auth=intent['authorization'];config=intent['config']
    result=binding.bind_original_call(run_dir=intent['transport_run_dir'],expected_run_dir=intent['transport_run_dir'],
        expected_prompt=prompt,expected_schema=intent['schema_json'],expected_config=config,
        ledger_snapshot_path=ledger_snapshot_path,ledger_source_path=auth['ledger_path'],expected_ledger_sha256=sha(raw['ledger']),
        expected_approval_record_sha256=auth['approval_sha256'],expected_registration_id=auth['registration_id'],
        expected_registration_record_sha256=auth['registration_sha256'],expected_interaction_context=intent['expected_context'],
        expected_disabled_skill_paths=auth['disabled_skill_paths'])
    if result.report['success_action_eligible']:
        require(all(result.raw_artifacts[name]==raw[name] for name in binding.FILES),'original files changed after archival capture')
        require(result.raw_artifacts['ledger_snapshot']==raw['ledger'],'original ledger snapshot mismatch')
    return result


def _phase(store_state,aid):
    attempt=store_state['attempts'].get(aid)
    if attempt is None:return 'local_reservation_absent'
    if attempt['action'] is not None:return 'action_already_processed'
    if attempt['completion'] is not None:return 'terminal_original_attached_unprocessed'
    if attempt['request'] is not None:return 'pending_original_call'
    return 'local_reserved_transport_outcome_unknown'


def execute_once(store,*,expected_store_id,instance_id,attempt_id,model_index,transport_run_dir,evidence_dir,
                 config,schema,expected_context,authorization,transport_call,process_success=False):
    """One explicitly injected call; any reuse/missing stage stops, never retries.

    process_success=True explicitly permits this invocation to perform only the
    pure Interaction action after strict original-file binding. Default leaves
    the successful completion unprocessed. No physical commit method is called.
    """
    require(callable(transport_call) and type(process_success)is bool,'explicit injected transport and processing choice required')
    run=str(Path(transport_run_dir).resolve());directory=Path(evidence_dir).resolve()
    require(str(transport_run_dir)==run,'explicit normalized transport path required')
    require(not Path(run).exists(),'existing transport directory is preserved; never call again')
    directory.mkdir(parents=False,exist_ok=False)  # One attempt record cannot be reused across processes.
    intent={'schema':SCHEMA,'expected_store_id':expected_store_id,'store_directory':str(store.directory.resolve()),
            'instance_id':instance_id,'attempt_id':attempt_id,'model_index':model_index,'transport_run_dir':run,
            'config':deepcopy(config),'schema_json':schema,'expected_context':deepcopy(expected_context),
            'authorization':deepcopy(authorization),'process_success':process_success}
    # Use schema_json for the transport schema; schema identifies this bridge record.
    intent['schema']=SCHEMA
    report={'schema':SCHEMA+'-outcome','phase':'preflight','errors':[],**FLAGS}
    intent_sha=save_json(directory/'intent.json',intent);report['intent_sha256']=intent_sha
    invoked=False;transport_error=None
    try:
        before,proof=binding.read_snapshot(authorization['ledger_path']);write_bytes(directory/'ledger_before.jsonl',before)
        check_authority(before,authorization,config,run)
        durable_proof,state,contexts=inspect_store(store,expected_store_id)
        sid=state['instances'].get(instance_id)
        require(sid is not None and binding.same(contexts[sid],expected_context),'registered current interaction context mismatch')
        save_json(directory/'preflight.json',{'ledger':proof,'durable_prefix':{k:durable_proof[k] for k in ('journal_records','journal_tail_sha256','database_sha256')}})
        schema_raw=(json.dumps(schema,ensure_ascii=False,indent=2)+'\n').encode()
        reserved=store.reserve_attempt(instance_id,attempt_id=attempt_id,model_index=model_index,run_dir=run,config=config,schema_bytes=schema_raw)
        save_json(directory/'local_reservation.json',reserved)
        require(reserved['accepted'],'durable local reservation rejected')
        prepared=reserved['value'];prompt=prepared['prompt']['prompt']
        write_bytes(directory/'issued_prompt.txt',prompt.encode());write_bytes(directory/'issued_schema.json',schema_raw)
        save_json(directory/'invocation_intent.json',{'attempt_id':attempt_id,'request_fingerprint':prepared['request_fingerprint'],
            'full_prompt_sha256':sha(prompt.encode()),'prompt_body_sha256':prepared['prompt']['prompt_body_sha256'],
            'original_call_id_available':False,'resume':False})
        invoked=True
        try:
            transport_call(prompt,deepcopy(schema),run,deepcopy(config),resume=False)
            # The returned Python object is intentionally ignored, even if it says success.
            save_json(directory/'invocation_return.json',{'returned':True,'return_value_used_as_evidence':False})
        except BaseException as exc:
            transport_error=exc;save_json(directory/'invocation_exception.json',error(exc))
        raw,capture=capture_originals(run,authorization['ledger_path'])
        report['capture_sha256']=archive_originals(directory,raw,capture)
        require(not capture['errors'],'one or more original files could not be captured safely')
        require(raw.get('ledger',b'').startswith(before),'original ledger prefix changed during call')
        cid,reserve,finish=ledger_lines(raw);report['call_id']=cid
        request_args={'request_bytes':raw['request.json'],'reserve_bytes':reserve,'claim_bytes':raw['attempt.claim'],
                      'prompt_bytes':raw['prompt.txt'],'schema_bytes':raw['schema.json']}
        attached=store.bind_transport_request(instance_id,attempt_id=attempt_id,**request_args)
        save_json(directory/'request_attachment.json',attached);require(attached['accepted'],'original request attachment rejected')
        if 'result.json' not in raw or finish is None:
            report['phase']='pending_original_call'
        else:
            original_result=binding.parse(raw['result.json'])
            report['original_reported_status']=original_result.get('status')
            usage_valid=False
            try:
                usage_summary=binding.summarize_events(raw['events.jsonl']);usage_valid=True
                report['usage_known']=all(type(usage_summary['usage'][key])is int for key in ('input_tokens','output_tokens'))
            except Exception as exc:
                report['usage_known']=False;report['raw_usage_validation_error']=error(exc)
            successful=original_result.get('status')=='success'
            verified=None
            if successful:
                verified=bind_success(intent,prompt,directory/'raw/ledger.bin',raw);save_json(directory/'success_binding.json',verified.report)
                require(usage_valid and verified.report['success_action_eligible'],'successful output failed strict original-file/ledger/envelope binding')
            completion=store.bind_transport_completion(instance_id,attempt_id=attempt_id,result_bytes=raw['result.json'],
                finish_bytes=finish,events_bytes=raw['events.jsonl'],final_bytes=raw.get('final.txt'))
            save_json(directory/'completion_attachment.json',completion);require(completion['accepted'],'terminal original completion attachment rejected')
            if not successful:
                report['phase']='terminal_failed_preserved'
            elif transport_error is not None or not process_success:
                report['phase']='terminal_successful_unprocessed'
            else:
                handled=store.process_completed(instance_id,attempt_id=attempt_id);save_json(directory/'action_processing.json',handled)
                require(handled['accepted'],'explicit pure processing rejected')
                report['phase']='action_processed';report['interaction_response']=handled['value']['response']
    except Exception as exc:
        report['errors'].append(error(exc))
        report['phase']='diagnosis_required'
    report['transport_function_entered']=invoked
    if transport_error is not None:report['transport_exception']=error(transport_error)
    # Refresh only via read-only verification; no recovery/attachment side effects.
    try:
        proof,state,_=inspect_store(store,expected_store_id);report['durable_phase']=_phase(state,attempt_id)
        report['durable_prefix']={k:proof[k] for k in ('journal_records','journal_tail_sha256','database_sha256')}
    except Exception as exc:report['errors'].append(error(exc))
    report_sha=save_json(directory/'outcome.json',report)
    if transport_error is not None and not isinstance(transport_error,Exception):raise transport_error
    return {**report,'outcome_sha256':report_sha,'evidence_dir':str(directory)}


def recover_read_only(evidence_dir,*,expected_intent_sha256,expected_outcome_sha256=None):
    """Only classify existing evidence. No transport, attach, finish, or handle."""
    directory=Path(evidence_dir).resolve();report={'schema':SCHEMA+'-readonly-recovery','valid':False,'errors':[],**FLAGS}
    try:
        raw,proof=binding.read_snapshot(directory/'intent.json');require(sha(raw)==expected_intent_sha256,'external bridge intent hash mismatch')
        intent=binding.parse(raw);require(intent['schema']==SCHEMA,'bridge schema mismatch')
        store=durable.DurableInteractionStore(intent['store_directory'])
        durable_proof,state,contexts=inspect_store(store,intent['expected_store_id'],intent['attempt_id'])
        sid=state['instances'].get(intent['instance_id']);require(sid is not None and binding.same(contexts[sid],intent['expected_context']),'stored current context mismatch')
        report['durable_phase']=_phase(state,intent['attempt_id']);report['durable_recovery']=durable_proof
        aid=intent['attempt_id']
        if aid in state['attempts']:
            attempt=state['attempts'][aid];stored=state['_inspected_attempt'];spec=stored['spec']
            require(attempt['interaction_id']==sid and attempt['instance_id']==intent['instance_id']
                    and type(attempt['model_index'])is type(intent['model_index']) and attempt['model_index']==intent['model_index'],
                    'bridge attempt identity differs from durable registration')
            require(spec['run_dir']==intent['transport_run_dir'] and binding.same(spec['config'],intent['config']),
                    'bridge config/directory differs from durable reservation')
            require(stored['schema_bytes']==(json.dumps(intent['schema_json'],ensure_ascii=False,indent=2)+'\n').encode(),
                    'bridge schema differs from durable reservation')
            for name,expected in (('issued_prompt.txt',stored['prompt']['prompt'].encode()),('issued_schema.json',stored['schema_bytes'])):
                if (directory/name).exists():
                    original,_=binding.read_snapshot(directory/name);require(original==expected,'issued bridge bytes differ from durable reservation')
        if (directory/'invocation_intent.json').exists():
            marker,_=binding.read_snapshot(directory/'invocation_intent.json');marker=binding.parse(marker)
            require(aid in state['attempts'],'invocation intent has no local durable reservation')
            require(marker=={'attempt_id':aid,'request_fingerprint':durable.expected_fingerprint(stored['prompt']['prompt'],stored['schema_bytes'],spec['config']),
                'full_prompt_sha256':sha(stored['prompt']['prompt'].encode()),'prompt_body_sha256':stored['prompt']['prompt_body_sha256'],
                'original_call_id_available':False,'resume':False},'invocation marker differs from exact original reserved request')
        before,_=binding.read_snapshot(directory/'ledger_before.jsonl')
        check_authority(before,intent['authorization'],intent['config'],intent['transport_run_dir'])
        archived={}
        if expected_outcome_sha256 is not None:
            require((directory/'outcome.json').exists(),
                    'externally known outcome is missing; cannot downgrade to pre-outcome recovery')
        if (directory/'outcome.json').exists():
            require(expected_outcome_sha256 is not None,'completed bridge recovery requires external outcome hash')
            saved,_=binding.read_snapshot(directory/'outcome.json');require(sha(saved)==expected_outcome_sha256,'outcome hash mismatch')
            outcome=binding.parse(saved);require(outcome['intent_sha256']==expected_intent_sha256,'outcome intent differs')
            report['saved_phase']=outcome['phase']
            if outcome.get('durable_prefix'):
                prefix_check=durable.recover_read_only(store.directory,expected_store_id=intent['expected_store_id'],expected_prefix=outcome['durable_prefix'])
                require(prefix_check['valid'],'durable recorded outcome prefix changed')
            if 'capture_sha256' in outcome:
                capture_raw,_=binding.read_snapshot(directory/'capture.json');require(sha(capture_raw)==outcome['capture_sha256'],'capture receipt differs')
                capture=binding.parse(capture_raw)
                for name,desc in capture['files'].items():
                    require(name in {'ledger',*FILES},'unexpected original artifact name')
                    blob,_=binding.read_snapshot(directory/'raw'/(name+'.bin'));require(sha(blob)==desc['sha256'] and len(blob)==desc['bytes'],'archived original bytes differ')
                    archived[name]=blob
        # A crash before capture/outcome still permits read-only observation of original files.
        originals,capture=capture_originals(intent['transport_run_dir'],intent['authorization']['ledger_path'])
        require(not capture['errors'],'live original file read failed')
        require(originals.get('ledger',b'').startswith(before),'original ledger prefix changed')
        original_status=None;cid=None;reserve=finish=None
        if 'request.json' in originals:
            cid,reserve,finish=ledger_lines(originals)
            if 'result.json' in originals and finish is not None:original_status=binding.parse(originals['result.json']).get('status')
        # The original ledger may append. Bound request/terminal records may not change.
        compared={**originals,'reserve_line':reserve,'finish_line':finish}
        if aid in state['attempts']:
            for name,attached in stored['attached_bytes'].items():
                require(compared.get(name)==attached,'live original differs from durable attached bytes: '+name)
        immutable={'request.json','attempt.claim','prompt.txt','schema.json','system-instructions.txt','command.json'}
        if 'request.json' in archived and 'ledger' in archived:
            _,_,archived_finish=ledger_lines(archived)
            if archived_finish is not None and 'result.json' in archived:
                immutable.update({'result.json','events.jsonl','final.txt','stderr.log'})
        for name in immutable & archived.keys():
            require(originals.get(name)==archived[name],'live original differs from archived bytes: '+name)
        if 'ledger' in archived:
            require(originals['ledger'].startswith(archived['ledger']),'original ledger no longer extends captured prefix')
        success_eligible=False
        if original_status=='success':
            require(aid in state['attempts'],'original success has no durable local reservation')
            bound=bind_success(intent,stored['prompt']['prompt'],intent['authorization']['ledger_path'],originals)
            report['read_only_success_binding']=bound.report
            success_eligible=bound.report['success_action_eligible']
        if report['durable_phase']=='action_already_processed':
            require(success_eligible,'previously processed action no longer has strictly valid original evidence')
            phase='action_already_processed_no_replay'
        elif original_status in ('failed','timeout'):phase='terminal_failed_requires_diagnosis'
        elif original_status=='success':
            phase=('terminal_successful_unprocessed_requires_explicit_processing' if success_eligible
                   else 'terminal_reported_success_rejected_requires_diagnosis')
        elif cid is not None:phase='pending_original_call'
        else:phase='local_reservation_transport_outcome_unknown'
        report.update(valid=True,phase=phase,original_call_id=cid,original_reported_status=original_status,
                      success_action_eligible=success_eligible,
                      original_status_is_not_success_validation=True,automatic_action_performed=False,
                      evidence_files_changed=False)
    except Exception as exc:report['errors'].append(error(exc))
    return report
