"""Scripted physical mechanism driver; no model/transport/experimental costs."""
from harness_v6.snapshot import decode_snapshot
import argparse
import gzip
from functools import lru_cache
from copy import deepcopy
import json
from pathlib import Path
import time
from build_public_fixture import scripted_plan, LABEL
from harness_v6.factory_v6 import capture, restore, prepare
from harness_v6.contracts import digest, encode
from harness_v6.cycle import CycleMachine, CycleConfig
from harness_v6.groups import config_for
from harness_v6.ledger import ledger_read_view, choose_batch
from harness_v6.audit_v6 import audit_opportunity_coverage, audit_plan_sources
from harness_v6.snapshot import stable_prefix, build_snapshot, tiktoken_counter
from harness_v6.plan_delta import SCHEMA, STATE_SCHEMA, ORDER_POLICY, anchor_hashes
from harness_v6.submit import Submitter
from harness_v6.checkpoint import capture_ledger, restore_ledger

SOURCE=digest('public-scripted-mechanism')

def checked_snapshot(env):
    snapshot=env.ledger_snapshot()
    ready={o['operation_id']:o for o in snapshot['problem']['operations']
        if not o.get('conditional') and not o.get('predecessor_ids')
        and o.get('release_time',env.t)<=env.t}
    qualified={}
    for oid,op in ready.items():
        for mid in op['eligible_machines']:qualified.setdefault(mid,{})[oid]=op
    differences=[]
    for machine in snapshot['problem']['machines']:
        public=not machine['currently_busy'] and not machine['currently_down'] and bool(choose_batch(qualified.get(machine['machine'],{}),machine))
        if public != env.has_legal(machine['machine']): differences.append(machine['machine'])
    assert not differences, ('public/physical mismatch',env.t,differences)
    return snapshot


def step(env, cycle, rows, prefix, counter, stop, event=None, evidence_path=None):
    snap=checked_snapshot(env);problem=snap['problem']
    ledger=ledger_read_view(problem,snap['plan'],snap['receipts'])
    record=cycle.begin(env.t,avoidable_idle=snap['metrics']['avoidable_idle'],invalid_tasks=env.invalidated_task_ids,
        valid_until=env.plan['valid_until'] if env.plan else None,event=event)
    payload=build_snapshot(prefix,ledger,state_version=cycle.cycles,running_jobs=[dict(job=jid,machine=j['machine'],lot_ids=j['lots'],started_at=j['start'],
        phase='processing' if jid in env.processing_by_machine[j['machine']] else 'transport')
        for jid,j in sorted(env.jobs.items()) if not j['done']],
        last_cycle_receipt=cycle.last_record,model_notes=LABEL,token_budget=10**8,token_counter=counter)
    current=decode_snapshot(payload)[1]
    rows.append(dict(time=env.t,tokens=counter(payload.decode()),prefix_tokens=counter(prefix.decode()),current_tokens=counter(payload[len(prefix):].decode()),bytes=len(payload),pending_tasks=len(current['pending_tasks']),
        unreserved_ready=len(current['unreserved_ready']),wip=sum(l['status'] not in ('done','unreleased') for l in env.lots.values()),session=record['session']))
    if record['session']:
        plan=scripted_plan(env,f'{cycle.config.trigger}-{cycle.cycles}')
        base=env.plan
        state=dict(schema=STATE_SCHEMA,time=env.t,observation_end=env.horizon,base_plan_version=base['version'],
            dispatched_task_ids=sorted(t for v,t in env.executed_tasks if v==base['version']),invalidated_task_ids=sorted(env.invalidated_task_ids))
        cancel=[t['id'] for t in base['tasks'] if t['id'] not in state['dispatched_task_ids']]
        delta=dict(schema=SCHEMA,anchors=anchor_hashes(base,problem,state,source_sha256=SOURCE),order_policy=ORDER_POLICY,
            plan_header={k:v for k,v in plan.items() if k not in ('tasks','holds')},
            tasks=dict(keep=dict(mode='all_pending_except',ids=cancel),cancel_ids=cancel,replace=[],add=plan['tasks']),
            machine_orders=[dict(machine=t['machine'],task_ids=[t['id']]) for t in plan['tasks']])
        def precheck(candidate,*_):
            prepare(env,candidate);return []
        submit=Submitter(base,problem,state,state_version=cycle.cycles,next_anchor=cycle.anchor,
            delta_seconds=cycle.config.delta,source_sha256=SOURCE,physical_precheck=precheck,trigger=cycle.config.trigger)
        receipt=submit.submit_plan(cycle.cycles,str(cycle.cycles),delta)
        assert receipt['accepted'],receipt['violations']
        env.commit_plan(submit.finalize(process_ok=True));cycle.finish(submitted=True,model_note=LABEL)
    # Audit and release each full observation immediately, rather than retaining
    # a whole 300-second interval of WIP tables in the private trace.
    pending=None; totals={}; steps=0
    with gzip.open(evidence_path,'ab') as stream:
        def finish_observation():
            nonlocal pending,steps
            if pending is None:return
            entries=[pending]
            index=pending['seq']+1
            if index<len(env.trace) and env.trace[index]['kind']=='time_advance':
                entries.append(env.trace[index])
            audit=audit_opportunity_coverage(entries)
            assert audit['valid'],audit['errors'][:10]
            steps+=audit['steps']
            for k,v in audit['integrals'].items():totals[k]=totals.get(k,0)+v
            stream.write(encode(pending)+b'\n')
            pending=None
        def observed(current):
            nonlocal pending
            finish_observation()
            raw=checked_snapshot(current)
            pending=dict(seq=len(current.trace),time=current.t,kind='ledger_snapshot',**raw)
            return dict(metrics=raw['metrics'],evidence_sha256=digest(pending))
        result=env.advance_cycle(min(stop,cycle.anchor) if cycle.anchor is not None else stop,
            trigger=cycle.config.trigger,decision_after=env.t,ledger_snapshot=observed)
        finish_observation()
    assert result['reason']!='plan_horizon'
    return result,dict(valid=True,integrals=totals,steps=steps)


def run(bundle,group,stop,delta,breakdowns,output):
    for suffix in ('','.ledger.jsonl.gz','.recovery-ledger.jsonl.gz','.checkpoint.json','.trace.json'):
        if Path(output+suffix).exists(): raise FileExistsError(output+suffix)
    begin=time.perf_counter();b=json.loads(Path(bundle).read_text());f=b['public_702']
    env=restore(f['state'],f['trace'],data_dir=b['data_dir']);env.breakdowns=breakdowns
    cycle=CycleMachine(origin=env.t,config=config_for(group,CycleConfig(delta=delta,breakdowns=breakdowns)))
    prefix=stable_prefix(tool_descriptions=['read_entities','validate_plan','submit_plan'],
        routing=env.manifest['routes'],machine_groups=env.manifest['machines'])
    counter=lru_cache(maxsize=4)(tiktoken_counter());rows=[];steps=0;integrals={};checkpoint=None;event=None
    while env.t<stop:
        result,audit=step(env,cycle,rows,prefix,counter,stop,event,output+'.ledger.jsonl.gz')
        steps+=audit['steps']
        for k,v in audit['integrals'].items():integrals[k]=integrals.get(k,0)+v
        event=result['reason'] if result['reason'] in ('plan_invalidated','expired_task','no_plan') else None
        if checkpoint is None and env.t>=(702+stop)/2:
            ls=env.ledger_snapshot()
            checkpoint=dict(state=capture(env),trace=deepcopy(env.trace),cycle=cycle.capture(),event=event,
                ledger=capture_ledger(ledger_read_view(ls['problem'],ls['plan'],ls['receipts'])),
                integrals=dict(integrals),steps=steps,rows=deepcopy(rows))
            # Persist outside repository, then deserialize, matching real recovery boundary.
            Path(output+'.checkpoint.json').write_bytes(encode(checkpoint))
        print(group,round(env.t,3),'cycles',cycle.cycles,'tokens',rows[-1]['tokens'],flush=True)
    final=digest(capture(env));source=audit_plan_sources(env.trace);assert source['valid'],source['errors'][:10]
    cp=json.loads(Path(output+'.checkpoint.json').read_text());clone=restore(cp['state'],cp['trace'],data_dir=b['data_dir'])
    c=CycleMachine.restore(cp['cycle']);ev=cp['event'];recovered=[]
    ls=clone.ledger_snapshot()
    current = ledger_read_view(ls['problem'],ls['plan'],ls['receipts'])
    restored = restore_ledger(cp['ledger'])
    assert restored.rows() == current.rows()
    assert restored.metrics() == current.metrics()
    assert capture_ledger(current) == cp['ledger']
    resumed_integrals=cp['integrals'];resumed_steps=cp['steps']
    while clone.t<stop:
        result,audit=step(clone,c,recovered,prefix,counter,stop,ev,output+'.recovery-ledger.jsonl.gz')
        resumed_steps+=audit['steps']
        for k,v in audit['integrals'].items():resumed_integrals[k]=resumed_integrals.get(k,0)+v
        ev=result['reason'] if result['reason'] in ('plan_invalidated','expired_task','no_plan') else None
    assert digest(capture(clone))==final
    assert digest(c.capture())==digest(cycle.capture())
    assert resumed_integrals==integrals and resumed_steps==steps
    assert cp['rows']+recovered==rows
    final=digest(dict(physical=final,cycle=cycle.capture(),integrals=integrals,steps=steps))
    result=dict(group=group,stop=stop,delta=delta,breakdowns=breakdowns,cycles=cycle.cycles,sessions=cycle.sessions,
        steps=steps,integrals=integrals,rows=rows,checkpoint_time=cp['state']['t'],recovery_equal=True,final_hash=final,
        plan_horizon_defects=cycle.defects,production_dispatches=source['production_dispatches'],
        downtime_events=sum(e['kind']=='downtime' and e['time']>=702 for e in env.trace),
        breakdown_invalidations=sum(e['kind']=='plan_invalidated' and e.get('reason')=='breakdown' for e in env.trace),
        wall_seconds=time.perf_counter()-begin)
    Path(output+'.trace.json').write_bytes(encode(env.trace))
    Path(output).write_bytes(encode(result));return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--fixture',required=True);p.add_argument('--group',choices=['P2','E1'],required=True)
    p.add_argument('--until',type=float,required=True);p.add_argument('--delta',type=float,default=60)
    p.add_argument('--breakdowns',action='store_true');p.add_argument('--output',required=True)
    a=p.parse_args();run(a.fixture,a.group,a.until,a.delta,a.breakdowns,a.output)
