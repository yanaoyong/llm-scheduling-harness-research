"""User-authorized uncapped recovery of the SAME four context experiment accounts."""
from pathlib import Path
from .contracts import digest,encode,require,sha_bytes,strict_json,HarnessError
from .context_ablation import SCHEMA
POLICY={"max_retries_per_request":None,"max_failures_per_cohort":None,"cooldown_seconds":[60,120,300],"allowed_failure_kinds":["connection","stream_disconnect"],"unknown_usage":"retain_unknown"}
CONTROL_FILES={"src/smt_fullfab/harness/"+n+".py" for n in ("context_recovery","recovery","amendment","transport","wall_budget")}

def cooldown(ordinal):
    require(type(ordinal) is int and ordinal>=1,"recovery_ordinal","Positive failure ordinal required")
    return POLICY["cooldown_seconds"][min(ordinal-1,len(POLICY["cooldown_seconds"])-1)]

def is_context(manifest):
    return (manifest.get("admission") or {}).get("experiment_kind")==SCHEMA

def amendment(reg):
    from .experiment import checked_file
    root=Path(reg["experiment_directory"]);path=root/"recovery_amendment.json"
    if not path.exists():return None
    value=strict_json(path.read_bytes());grant=checked_file(value["authorization"])
    require(value["schema"]=="context-2x2-recovery-amendment-v1" and value["registration_sha256"]==sha_bytes((root/"experiment.json").read_bytes())==grant["registration_sha256"],"context_recovery_grant","Original registration binding")
    require(grant["user_reply"]=="允许，取消限制我们的目标是跑完完整的实验，继续完成四组，不要影响正在跑的 B。" and grant["policy"]==POLICY and all(grant[k] is True for k in ("same_original_runs","all_four_arms_same_policy","retain_every_cost_and_failure")) and all(grant[k] is False for k in ("change_model","change_physics","change_treatments","reset_costs","change_network","touch_live_B")),"context_recovery_grant","Exact continuation authorization required")
    require(grant["increase_limits"] is True and grant["count_caps_removed"] is True and grant["changed_limit_fields"]==["attempts"],"context_count_grant","Only call-count caps removed")
    before=checked_file(value["before_fingerprint"]);after=checked_file(value["after_fingerprint"]);proof=checked_file(value["verification"])
    require(before["sha256"]==reg["fingerprint_sha256"] and all(digest({k:v for k,v in fp.items() if k!="sha256"})==fp["sha256"] for fp in (before,after)),"context_recovery_source","Source proof corrupt")
    changed={p for p in before["files"].keys()|after["files"].keys() if before["files"].get(p)!=after["files"].get(p)}
    require(changed==CONTROL_FILES and {k:v for k,v in before.items() if k not in ("files","sha256")}=={k:v for k,v in after.items() if k not in ("files","sha256")},"context_recovery_source","Only recovery hooks may change; physical code/data/dependencies frozen")
    require(proof["all_pass"] and proof["source_unchanged"] and proof["remote_model_calls"]==0 and proof["fingerprint_sha256"]==after["sha256"],"context_recovery_tests","Tested control revision required")
    require(sha_bytes((root/"experiment.py").read_bytes())==value["runner_sha256"],"context_recovery_runner","Frozen round-robin runner changed")
    bound=checked_file(value["boundary"])
    require(bound["registration_sha256"]==value["registration_sha256"] and bound["total_model_calls"]==7 and bound["unknown_usage_calls"]==2 and bound["pending_attempts"]==0,"context_recovery_boundary","Retain original interruption")
    return value

def compatible_revision_hashes(reg,revision):
    from .experiment import checked_file
    allowed={digest(revision)};cursor=revision;seen=set()
    while cursor.get("previous_control_revision"):
        cursor=checked_file(cursor["previous_control_revision"]);h=digest(cursor)
        require(h not in seen and cursor["registration_sha256"]==revision["registration_sha256"],"context_revision_chain","Same registration and acyclic history required")
        seen.add(h)
        if checked_file(cursor["authorization"])["policy"]==POLICY:allowed.add(h)
    return allowed

def apply_count_budget(manifest,row,result):
    from .experiment import registration,checked_file
    require(is_context(manifest),"context_count_marker","Only this four-arm experiment")
    reg=registration(manifest["admission"]);revision=amendment(reg)
    require(revision is not None and row["amendment_sha256"]==digest(revision) and row["run_id"]==manifest["run_id"] and row["original_manifest_sha256"]==digest(manifest) and row["original_attempt_limit"]==manifest["config"]["limits"]["attempts"]==60 and row["effective_attempt_limit"] is None and row["new_model_calls"]==0,"context_count_marker","Exact original run and count-only authorization required")
    result["limits"]["attempts"]=None
    result.update(context_uncapped_counts=True,original_attempt_limit=60,source_revision_sha256=digest(revision))
    return result

def validate_source(manifest,current,reg):
    from .experiment import checked_file
    revision=amendment(reg)
    require(revision is not None and manifest["fingerprint"]["sha256"]==reg["fingerprint_sha256"] and current==checked_file(revision["after_fingerprint"]),"context_recovery_source","No authorized matching control revision")

def policy(reg):
    return POLICY.copy() if amendment(reg) else None

def validate_rows(view,records,reg,revision):
    from .recovery import failure_kind
    root=Path(reg["experiment_directory"]);admission=view.manifest["admission"]
    require(admission["experiment_kind"]==SCHEMA and admission["experiment_sha256"]==revision["registration_sha256"] and Path(admission["experiment_directory"]).resolve()==root.resolve(),"context_recovery_identity","Original run account only")
    require(view.manifest["config"]["unknown_usage_policy"]=="freeze_new_calls" and digest(view.manifest["config"])==reg["cases"][admission["case_id"]]["config_sha256"],"context_recovery_config","Original config/caps must remain byte-equivalent")
    attempts=sorted((a for a in view.rows("attempts").values() if a["channel"]=="codex" and a["status"]!="not_sent"),key=lambda a:a["index"])
    require(set(records)<={a["attempt_id"] for a in attempts},"context_recovery_identity","No unmatched exception")
    result={};ordinal=0
    for i,a in enumerate(attempts):
        aid=a["attempt_id"]
        if aid not in records:continue
        row=records[aid];previous=attempts[i-1]["attempt_id"] if i else None
        ordinal=result[previous]["request_failure_ordinal"]+1 if previous in result else 1
        require(row["attempt_id"]==aid and row["attempt_sha256"]==digest(a) and row["context_ref"]==a["context_ref"] and row["usage"] is None and row["business_action_replayed"] is False and row["request_failure_ordinal"]==ordinal,"context_recovery_evidence","Original unknown attempt cannot be changed")
        require(row["failure_kind"]==failure_kind(view,a) and row["failure_kind"] in POLICY["allowed_failure_kinds"] and row["policy_sha256"]==digest(POLICY) and row["amendment_sha256"] in compatible_revision_hashes(reg,revision),"context_recovery_evidence","Closed transport failure and exact policy required")
        require(row["not_before_epoch"]==a["finished_epoch"]+cooldown(ordinal) and type(row["cohort_failure_ordinal"]) is int and row["cohort_failure_ordinal"]>=1,"recovery_limit","Progressive cooldown and monotonic cohort ordinal")
        if i+1<len(attempts):
            nxt=attempts[i+1]
            require(nxt["reserved_epoch"]>=row["not_before_epoch"] and nxt["prompt_ref"]==a["prompt_ref"] and nxt["schema_ref"]==a["schema_ref"] and nxt["context_ref"]==a["context_ref"],"context_recovery_retry","Retry must bind exact original prompt/schema/context after cooldown")
        result[aid]=row
    return result

def validate(view):
    records=view.rows("transport_recoveries")
    if not records:return {}
    from .experiment import registration
    reg=registration(view.manifest["admission"]);revision=amendment(reg)
    require(revision is not None,"context_recovery_grant","No grant")
    return validate_rows(view,records,reg,revision)

def validate_ordinals(ordinals):
    require(sorted(ordinals)==list(range(1,len(ordinals)+1)),"recovery_limit","Global recovery ordinals omitted or duplicated")

def cohort(reg):
    from .experiment import account_records
    from .recovery import LiveEvidence
    revision=amendment(reg)
    if revision is None:return {}
    result={};ordinals=[]
    for case,group,rid,path,_ in account_records(reg["experiment_directory"]):
        view=LiveEvidence(path);require(view.manifest["run_id"]==rid and view.manifest["admission"]["case_id"]==case,"context_recovery_identity","Account differs")
        records=view.rows("transport_recoveries");rows=validate_rows(view,records,reg,revision) if records else {}
        result[rid]=(group,rows);ordinals.extend(r["cohort_failure_ordinal"] for r in rows.values())
    validate_ordinals(ordinals)
    return result

def schedule(runtime,attempt_id):
    from .experiment import registration
    from .recovery import LiveEvidence,failure_kind
    reg=registration(runtime.manifest["admission"]);revision=amendment(reg)
    if revision is None:return None
    view=LiveEvidence(runtime.store.path);existing=validate(view)
    if attempt_id in existing:return existing[attempt_id]
    attempts=sorted((a for a in view.rows("attempts").values() if a["channel"]=="codex" and a["status"]!="not_sent"),key=lambda a:a["index"])
    require(attempts and attempts[-1]["attempt_id"]==attempt_id,"recovery_order","Latest failed request only")
    a=attempts[-1]
    previous=existing.get(attempts[-2]["attempt_id"]) if len(attempts)>1 else None
    ordinal=previous["request_failure_ordinal"]+1 if previous else 1
    used=sum(len(rows) for _,rows in cohort(reg).values())
    try:kind=failure_kind(view,a)
    except (HarnessError,KeyError,TypeError,ValueError):return None
    if kind not in POLICY["allowed_failure_kinds"]:return None
    row={"attempt_id":attempt_id,"attempt_sha256":digest(a),"context_ref":a["context_ref"],"failure_kind":kind,"request_failure_ordinal":ordinal,"cohort_failure_ordinal":used+1,"not_before_epoch":a["finished_epoch"]+cooldown(ordinal),"policy_sha256":digest(POLICY),"amendment_sha256":digest(revision),"usage":None,"business_action_replayed":False}
    with runtime.store.transaction():
        runtime.store.record("transport_recoveries",attempt_id,row);runtime.store.event("transport_recovery_scheduled",row)
    return row

def activate(runtime):
    """Preserve head/time/state/history; reopen only the proven failed transport stop."""
    from .experiment import registration,experiment_lock
    reg=registration(runtime.manifest["admission"]);revision=amendment(reg)
    if revision is None:return
    with experiment_lock(runtime.manifest["admission"]):
        attempts=runtime.store.rows("attempts");last=attempts[-1][1] if attempts else None
        recovery=schedule(runtime,last["attempt_id"]) if last and last.get("usage") is None else None
        with runtime.store.transaction():
            if runtime.store.read("context_recovery_control","active") is None:
                runtime.store.record("context_recovery_control","active",{"amendment_sha256":digest(revision),"original_manifest_sha256":digest(runtime.manifest),"no_model_request_sent":True})
            if runtime.head["phase"]=="STOPPED" and recovery:
                head=runtime.head;require(head["context_ref"]==recovery["context_ref"] and head.get("stop_reason") in ("model_transport_or_unknown_usage","unverified_model_response"),"context_recovery_stop","Do not override user or resource stop")
                old=dict(head);head["phase"]="OBSERVED";head["stop_reason"]=None
                runtime.store.set_meta("head",head);runtime.store.event("context_recovery_resumed",{"head_before":old,"head_after":head,"amendment_sha256":digest(revision),"physical_state_unchanged":True})

def exact_retry(runtime,text,schema):
    """Same bytes, new metered model attempt. Never replay a business action."""
    rows=validate(__import__("src.smt_fullfab.harness.recovery",fromlist=["LiveEvidence"]).LiveEvidence(runtime.store.path))
    attempts=runtime.store.rows("attempts")
    if not attempts or attempts[-1][0] not in rows:return text,schema
    a=attempts[-1][1];require(a["context_ref"]==runtime.head["context_ref"],"context_recovery_retry","Physical context changed")
    return runtime.store.bytes(a["prompt_ref"]).decode(),strict_json(runtime.store.bytes(a["schema_ref"]))
