"""Plan-source audit plus independent physical replay and historical diagnostics.

No simulator/controller import is used. Old physical audit is deliberately reused
as a separately implemented event checker, after source validation and a clearly
labelled projection. It does not prove parity with AutoSched or upstream software.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
import hashlib
import json
import math
from pathlib import Path

def read_events(source):
    if isinstance(source, (str, Path)):
        return [json.loads(line) for line in Path(source).read_text().splitlines()]
    return list(source)


AUDIT_VERSION = "smt-fullfab-independent-plan-audit-v3"
PHYSICAL_KINDS = {"initial", "release", "ready", "skip", "dispatch", "downtime",
                  "operation_complete", "rework", "lot_complete", "terminal"}
CONTROL_KINDS = {"plan_committed", "coverage_gap", "plan_invalidated", "time_advance",
                 "decision_opportunity", "action", "plan_exhausted", "snapshot_loaded", "ledger_snapshot"}


def _number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def audit_plan_sources(source):
    """Prove exact source of every actual production dispatch from submitted plans.

    Declared control-domain coverage and actual dispatch provenance are different
    from proof of absence of omitted opportunities; that latter claim is withheld.
    """
    events = read_events(source)
    errors, plans, active, done, pending = [], {}, None, set(), defaultdict(list)
    invalidated = set()
    dispatches, virtual, gaps, opportunity_records = [], [], [], []

    def check(ok, message):
        if not ok:
            errors.append(message)

    if not events or events[0].get("kind") != "initial":
        return {"valid": False, "errors": ["missing initial manifest"], "audit_version": AUDIT_VERSION}
    manifest = events[0]["manifest"]
    machines = {m["id"]: m for m in manifest["machines"]}
    manifest_lots = {lot["id"]: lot for lot in manifest["lots"]}
    production = {mid for mid, m in machines.items() if m["group"] != "Delay_32"}
    declared = set(manifest["controlled_machine_ids"])
    check(declared == production, "declared controller domain does not exactly equal all production machines")
    previous = events[0]["time"]
    for index, event in enumerate(events):
        t, kind = event.get("time"), event.get("kind")
        check(event.get("seq") == index, f"{index}: sequence gap")
        if not _number(t):
            check(False, f"{index}: invalid time")
            continue
        check(t >= previous, f"{index}: time reversed")
        previous = t
        check(kind in PHYSICAL_KINDS | CONTROL_KINDS, f"{index}: unknown or unsupported event {kind}")
        try:
            if kind == "plan_invalidated":
                invalidated.add((event["plan_version"], event["task_id"]))
            elif kind == "plan_committed":
                plan = event["plan"]
                version = plan["version"]
                check(isinstance(version, (str, int)) and not isinstance(version, bool), f"{index}: invalid version")
                check(version not in plans, f"{index}: duplicate plan version")
                for key in ("created_at", "valid_until", "freeze_until"):
                    check(_number(plan[key]), f"{index}: invalid {key}")
                check(plan["created_at"] == t, f"{index}: commit time differs from creation time")
                check(t <= plan["freeze_until"] <= plan["valid_until"] <= manifest["horizon"] and t < plan["valid_until"], f"{index}: invalid plan/freeze interval")
                check(sorted(plan["scope"]) == sorted(production), f"{index}: plan scope does not explicitly include every production machine")
                check(isinstance(plan["reason"], str) and bool(plan["reason"].strip()), f"{index}: missing revision reason")
                tasks, new_pending = {}, defaultdict(list)
                identities = set()
                for task in plan["tasks"]:
                    tid, mid = task["id"], task["machine"]
                    check(isinstance(tid, (str, int)) and not isinstance(tid, bool), f"{index}: invalid task id")
                    check(tid not in tasks, f"{index}: duplicate task id")
                    check(mid in production, f"{index}: planned non-production/unknown machine")
                    check(bool(task["lot_ids"]) and len(set(task["lot_ids"])) == len(task["lot_ids"]), f"{index}: empty/duplicate task lots")
                    check(len(task["steps"]) == len(task["lot_ids"]) == len(task["visits"]), f"{index}: task operation arity")
                    planned_steps = []
                    for lid, step, visit in zip(task["lot_ids"], task["steps"], task["visits"]):
                        check(lid in manifest_lots, f"{index}: planned unknown lot")
                        check(type(step) is int and type(visit) is int and step > 0 and visit > 0, f"{index}: invalid planned step/visit")
                        if lid in manifest_lots and type(step) is int:
                            route = manifest["routes"][manifest_lots[lid]["route"]]
                            check(1 <= step <= len(route), f"{index}: planned step outside route")
                            if 1 <= step <= len(route):
                                s = route[step - 1]
                                planned_steps.append((manifest_lots[lid]["part"], s))
                                check(mid in machines and s["family"] == machines[mid]["family"], f"{index}: planned unqualified machine")
                    if planned_steps:
                        part, first = planned_steps[0]
                        check(first["batch_min"] <= len(task["lot_ids"]) <= first["batch_max"], f"{index}: planned batch outside bounds")
                        check(all((p, s["step"], s["name"]) == (part, first["step"], first["name"]) for p, s in planned_steps), f"{index}: planned incompatible batch")
                    check(_number(task.get("not_before", plan["created_at"])), f"{index}: invalid not_before")
                    frozen_carry = bool(active is not None and t < plans[active]["freeze_until"] and
                                        tid in pending[mid] and plans[active]["task_map"][tid] == task and
                                        task.get("not_before", plan["created_at"]) < plans[active]["freeze_until"])
                    check(task.get("not_before", plan["created_at"]) < plan["valid_until"],
                          f"{index}: task outside plan validity or not an exact frozen carry")
                    if task.get("latest_start") is not None:
                        check(_number(task["latest_start"]) and task["latest_start"] >= task.get("not_before", plan["created_at"]), f"{index}: invalid latest_start")
                    if task.get("expected_start") is not None:
                        check(_number(task["expected_start"]) and task["expected_start"] >= task.get("not_before", plan["created_at"]), f"{index}: invalid expected_start")
                    for identity in zip(task["lot_ids"], task["steps"], task["visits"]):
                        check(identity not in identities, f"{index}: duplicate planned lot operation")
                        identities.add(identity)
                    tasks[tid] = task
                    new_pending[mid].append(tid)
                if active is not None:
                    old = plans[active]
                    frozen_by_machine = defaultdict(list)
                    for mid, tids in pending.items():
                        for tid in tids:
                            task = old["task_map"][tid]
                            planned_start = task.get("not_before", old["created_at"])
                            if planned_start < old["freeze_until"] and t < old["freeze_until"] and (active, tid) not in invalidated:
                                frozen_by_machine[mid].append(tid)
                                check(tid in tasks and tasks[tid] == task, f"{index}: changed or dropped frozen task {tid}")
                    if frozen_by_machine:
                        check(plan["freeze_until"] >= old["freeze_until"],
                              f"{index}: shortened prior freeze interval with pending frozen tasks")
                    for mid, frozen_ids in frozen_by_machine.items():
                        check([tid for tid in new_pending[mid] if tid in frozen_ids] == frozen_ids,
                              f"{index}: reordered frozen tasks")
                holds = plan.get("holds", [])
                hold_keys = set()
                for hold in holds:
                    check(hold["machine"] in production, f"{index}: hold non-production machine")
                    hold_key = (hold["machine"], hold.get("after_task_id"))
                    check(hold_key not in hold_keys, f"{index}: duplicate hold activation condition")
                    check(_number(hold["until"]) and hold["until"] <= plan["valid_until"], f"{index}: invalid hold interval")
                    check(bool(hold.get("reason")), f"{index}: hold missing reason")
                    if hold["until"] > t and hold.get("after_task_id") is not None:
                        task = tasks.get(hold["after_task_id"])
                        check(task is not None and task["machine"] == hold["machine"], f"{index}: conditional hold refers to no task on its machine")
                    hold_keys.add(hold_key)
                plans[version] = {**plan, "task_map": tasks}
                active, pending = version, new_pending
            elif kind == "dispatch":
                mid = event["machine"]
                check(mid in machines, f"{index}: unknown dispatch machine")
                if mid not in production:
                    check(event.get("owner") == "environment", f"{index}: virtual process has controller ownership")
                    virtual.append(event)
                    continue
                dispatches.append(event)
                check(event.get("owner") == "plan", f"{index}: production dispatch missing plan ownership")
                version, tid = event.get("plan_version"), event.get("plan_task_id")
                check(version in plans, f"{index}: missing committed source plan")
                check(version == active, f"{index}: dispatch references superseded plan")
                if version not in plans:
                    continue
                plan = plans[version]
                check(tid in plan["task_map"], f"{index}: missing source task")
                if tid not in plan["task_map"]:
                    continue
                task = plan["task_map"][tid]
                check((version, tid) not in done, f"{index}: task dispatched twice")
                check(bool(pending[mid]) and pending[mid][0] == tid, f"{index}: machine task order changed")
                for trace_key, task_key in (("machine", "machine"), ("lots", "lot_ids"), ("steps", "steps"), ("visits", "visits")):
                    check(event[trace_key] == task[task_key], f"{index}: dispatch differs from plan {task_key}")
                check(plan["created_at"] <= t <= plan["valid_until"], f"{index}: dispatch outside plan interval")
                check(t >= task.get("not_before", plan["created_at"]), f"{index}: dispatch before start condition")
                if task.get("latest_start") is not None:
                    check(t <= task["latest_start"], f"{index}: dispatch after latest_start")
                for hold in plan.get("holds", []):
                    hold_active = hold.get("after_task_id") is None or ((version, hold["after_task_id"]) in done and not pending[hold["machine"]])
                    check(hold["machine"] != mid or not hold_active or t >= hold["until"], f"{index}: dispatch during explicit hold")
                done.add((version, tid))
                if tid in pending[mid]:
                    pending[mid].remove(tid)
            elif kind == "coverage_gap":
                gaps.append(event)
            elif kind == "decision_opportunity":
                opportunity_records.append(event)
            elif kind == "snapshot_loaded":
                check(events[0]["time"] == 0 and event.get("prefix_event_count") == index,
                      f"{index}: snapshot lacks complete prehistory prefix")
                sha = event.get("snapshot_sha256", "")
                check(isinstance(sha, str) and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha),
                      f"{index}: invalid snapshot state hash")
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            check(False, f"{index}: malformed plan/trace: {exc}")
    return {"valid": not errors, "errors": errors, "audit_version": AUDIT_VERSION,
            "production_machine_count": len(production), "declared_control_machine_count": len(declared),
            "declared_full_factory_domain": declared == production,
            "production_dispatches": len(dispatches), "virtual_process_dispatches": len(virtual),
            "production_machines_with_dispatch": len({e["machine"] for e in dispatches}),
            "plans_committed": len(plans), "coverage_gap_events": len(gaps),
            "coverage_gap_details": gaps, "decision_opportunity_events": len(opportunity_records),
            "explicit_hold_count": sum(len(plan.get("holds", [])) for plan in plans.values()),
            "actual_dispatch_provenance_complete": bool(dispatches) and not errors,
            "absence_of_unreported_legal_demand_certified": False,
            "scope": "exact production dispatch provenance and declared responsibility; legal-demand completeness requires additional independent opportunity replay"}


def audit_opportunity_coverage(source):
    """Independently enumerate recorded public ledger inputs at each clock step.

    Does not certify private readiness: physical replay must check observation inputs.
    """
    from .audit_ledger import audit_ledger
    events=read_events(source);errors=[];snapshot=None;integrals={};steps=0
    for index,e in enumerate(events):
        if e['kind']=='ledger_snapshot':
            snapshot=e
            expected={**audit_ledger(e['problem'],e.get('plan'),e.get('receipts')), **audit_reservations(e['problem'],e.get('plan'),e.get('receipts'))}
            for key,value in expected.items():
                if e['metrics'].get(key)!=value: errors.append(f'{index}: ledger mismatch {key}')
        elif e['kind']=='time_advance':
            steps+=1
            if snapshot is None or snapshot['time']!=e['time']:
                errors.append(f'{index}: missing ledger snapshot');continue
            dt=e['to']-e['time']
            if dt<0: errors.append(f'{index}: negative interval');continue
            for key in ('avoidable_idle','explicit_wait_idle'):
                integrals[key]=integrals.get(key,0)+dt*expected[key]
            reservations=expected
            integrals['reserved_but_earlier_startable']=integrals.get('reserved_but_earlier_startable',0)+dt*len(reservations['reserved_but_earlier_startable'])
            snapshot=None
    return {'valid':not errors,'errors':errors,'integrals':integrals,'steps':steps,
            'physical_readiness_certified':False}

def audit_reservations(problem, plan=None, receipts=None):
    """Independent reservation age and earlier-start witnesses, exhaustive batches."""
    import itertools
    plan=plan or {};receipts=receipts or {};now=problem['time']
    states={r['task_id']:r['state'] for r in receipts.get('tasks',[])}
    op_states={r['operation_id']:r['state'] for r in receipts.get('operations',[])}
    tasks=plan.get('tasks',[])
    pending=[t for t in tasks if states.get(t['id']) not in ('running','done')]
    machines={m['machine']:m for m in problem['machines']}
    owners={o['operation_id']:[t for t in tasks if o['operation_id'] in t['operation_ids']] for o in problem['operations']}
    def idle(m):
        return not (m.get('currently_busy') or m.get('currently_down') or not m.get('available',True) or any(a<=now<b for a,b in m.get('unavailable_intervals',[])))
    def held(mid):
        return any(h['machine']==mid and h['until']>now and (h.get('after_task_id') is None or (states.get(h['after_task_id']) in ('running','done') and not any(t['machine']==mid for t in pending))) for h in plan.get('holds',[]))
    def legal(o,m):
        return m['machine'] in o['eligible_machines'] and not o.get('qualification_uncertain') and not o.get('same_machine_as') and (m.get('min_left',0)<=0 or m.get('min_setup')==o.get('setup'))
    available=[];ages={};reserved=set()
    for o in problem['operations']:
        oid=o['operation_id'];ts=owners[oid];ss=[states.get(t['id']) for t in ts]
        state=op_states.get(oid) or next((s for s in ('done','running','invalid') if s in ss),'reserved_not_started' if ts else 'ready_unreserved')
        if state=='reserved_not_started':
            reserved.add(oid);ages[oid]=max([0]+[max(0,now-t.get('assigned_at',plan.get('created_at',0))) for t in ts if t in pending])
        if state in ('ready_unreserved','reserved_not_started') and not o.get('conditional') and not o.get('predecessor_ids') and o.get('release_time',now)<=now:available.append(o)
    witnesses=[]
    if not reserved:
        return {'assigned_not_started_age':ages,'reserved_but_earlier_startable':witnesses}
    for mid,m in sorted(machines.items()):
        if not idle(m) or held(mid):continue
        for o in sorted(available,key=lambda x:x['operation_id']):
            oid=o['operation_id']
            if oid not in reserved or not legal(o,m):continue
            compatible=[p for p in available if legal(p,m) and all(p[k]==o[k] for k in ('batch_key','batch_min','batch_max'))]
            if not 1<=o['batch_min']<=o['batch_max'] or not any(itertools.combinations(compatible,o['batch_min'])):continue
            for task in sorted(owners[oid],key=lambda t:t['id']):
                if task not in pending or task['machine']==mid:continue
                original=machines.get(task['machine'],{});queue=[t for t in pending if t['machine']==task['machine']]
                estimate=max(now,task.get('not_before',now),original.get('available_at',now))
                if estimate>now or not idle(original) or held(task['machine']) or (queue and queue[0]['id']!=task['id']):
                    witnesses.append({'operation_id':oid,'task_id':task['id'],'machine':mid,'assigned_machine':task['machine'],'potential_idle_seconds':estimate-now,'seconds_basis':'public_forecast_estimate'})
    return {'assigned_not_started_age':ages,'reserved_but_earlier_startable':witnesses}
