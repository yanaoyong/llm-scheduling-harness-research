"""Anchor-only descriptive replay on one frozen P2 plan history; no scheduling."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
from phase_s_helpers import persistent_idle, slot_available
from harness_v6.cycle import CycleConfig, CycleMachine
from harness_v6.ledger import ledger_read_view
from harness_v6.snapshot import canonical


def variant_metrics(record, variant, now=None):
    p=record['problem']; time=p['time'] if now is None else now
    ops=p['operations']; machines=p['machines']
    if variant in ('b','c','d'):
        ops=[dict(o,qualification_uncertain=False) if o.get('qualification_uncertain') else o for o in ops]
    if variant in ('c','d'):
        machines=[dict(m,currently_busy=True) if not slot_available(m) else m for m in machines]
    ledger=ledger_read_view(dict(p,time=time,operations=ops,machines=machines),record.get('plan'),record.get('receipts'))
    metrics=ledger.metrics(); rows=ledger.rows()
    invalid=[tid for tid,t in ledger.tasks.items() if ledger.task_receipts.get(tid,{}).get('state')=='invalid' or any(rows.get(o,{}).get('state')=='invalid' for o in t['operation_ids'])]
    return {m['machine'] for m in metrics['avoidable_idle_matches']},invalid


def anchor_decision(now,origin,delta,*,idle_machines,previous=(),persistence=False,invalid_tasks=(),valid_until=None,unresolved_failure=False):
    # Evaluate the exact production begin predicate without inventing session
    # results, failures, finish/stall behavior or between-anchor interrupts.
    machine=CycleMachine(origin,CycleConfig(delta=delta,trigger='periodic'))
    machine.anchor=now; machine.unresolved_failure=unresolved_failure
    ids=persistent_idle(idle_machines,previous) if persistence else set(idle_machines)
    return machine.begin(now,avoidable_idle=len(ids),invalid_tasks=invalid_tasks,valid_until=valid_until)


def carry_is_exact(events):
    return all(e['kind'] == 'time_advance' for e in events)


def public_machines_match_carry(before, after, dispatch_counts):
    """Catch silent wake/process_free transitions omitted from the event trace.

    Before/after refer to the last pre-anchor and first post-dispatch public
    observations. Each new dispatch adds exactly one active processing job.
    """
    right={m['machine']:m for m in after}
    fields=('currently_busy','currently_down','available','current_setup','min_left','min_setup','cascading')
    for m in before:
        other=right[m['machine']]; count=dispatch_counts.get(m['machine'],0)
        if len(other.get('processing_until',[]))-len(m.get('processing_until',[]))!=count:
            return False
        if count:
            if m.get('currently_busy') or m.get('currently_down') or not m.get('available',True):
                return False
        elif any(m.get(k)!=other.get(k) for k in fields):
            return False
    return len(before)==len(after)


def run(args):
    measurement=json.loads(Path(args.measurement).read_bytes())
    probe=measurement['qualification_probe']
    if probe['rejected'] or probe['lots_with_any_recorded_dedication']:
        raise ValueError('qualification variant empirical precondition failed')
    trace=json.loads(Path(args.trace).read_bytes())
    commits={e['time']:e['seq'] for e in trace if e['kind']=='plan_committed'}
    from harness_v6.factory_v6 import restore
    bundle=json.loads(Path(args.initial_fixture).read_bytes())
    initial=bundle['public_702']
    env=restore(initial['state'],initial['trace'],data_dir=bundle['data_dir'])
    initial_record=dict(env.ledger_snapshot(),time=env.t,seq=len(env.trace),kind='initial_public_702')
    del bundle,env
    versions=Counter(); observations=0; mismatches=0; kinds=Counter(); distinct=set()
    last_record=None; last_metrics=None; last_time=None; origin=None
    integrals={v:0. for v in 'abc'}; anchors={d:[] for d in (60,300)}; next_times={}
    previous={d:{v:set() for v in 'abcd'} for d in anchors}
    def anchor(record,at,delta):
        for v in 'abcd':
            ids,invalid=variant_metrics(record,v,now=at); valid=(record.get('plan') or {}).get('valid_until')
            dec=anchor_decision(at,origin,delta,idle_machines=ids,previous=previous[delta][v],persistence=v=='d',invalid_tasks=invalid,valid_until=valid)
            anchors[delta].append(dict(variant=v,time=at,observation_time=record['time'],seq=record['seq'],idle_machines=sorted(ids),observation_basis=record.get('measurement_basis','previous_observation_trace_verified'),session=dec['session'],invalid_tasks=len(invalid),expiry_before_next=valid is not None and valid<dec['next_anchor'],valid_until=valid,unresolved_failure=None))
            previous[delta][v]=ids
    with gzip.open(args.public_ledger,'rt') as stream:
        for line in stream:
            r=json.loads(line); observations+=1; kinds[r['kind']]+=1; t=r['time']; distinct.add(t)
            versions[(r.get('plan') or {}).get('version')]+=1
            if origin is None:
                origin=t; next_times={d:t for d in anchors}
            if last_time is not None and t<last_time:
                raise ValueError('ledger time moved backwards')
            # First observation at exact anchor; otherwise last known state.
            if t!=last_time:
                for d in anchors:
                    while next_times[d]<t:
                        intervening=[e for e in trace if e['seq']>last_record['seq'] and e['time']<=next_times[d] and e['kind']!='plan_committed']
                        if not carry_is_exact(intervening): raise ValueError('missing pre-anchor physical observation')
                        anchor(last_record,next_times[d],d); next_times[d]+=d
                    if next_times[d]==t:
                        if last_record is None:
                            if initial_record['time']!=t: raise ValueError('initial fixture time mismatch')
                            anchor(dict(initial_record,measurement_basis='restored_public_702_before_first_plan'),t,d)
                        else:
                            cutoff=commits.get(t,r['seq'])
                            intervening=[e for e in trace if last_record['seq']<e['seq']<cutoff]
                            if not carry_is_exact(intervening): raise ValueError('missing pre-anchor physical observation')
                            dispatched=Counter(e['machine'] for e in trace if cutoff<e['seq']<r['seq'] and e['kind']=='dispatch' and e['machine'] in {m['machine'] for m in r['problem']['machines']})
                            if not public_machines_match_carry(last_record['problem']['machines'],r['problem']['machines'],dispatched):
                                raise ValueError('silent machine transition prevents exact pre-anchor carry')
                            anchor(last_record,t,d)
                        next_times[d]+=d
            metrics={v:variant_metrics(r,v)[0] for v in 'abc'}
            mismatches+=len(metrics['a'])!=r['metrics']['avoidable_idle']
            if last_time is not None:
                for v in 'abc': integrals[v]+=len(last_metrics[v])*(t-last_time)
            last_metrics=metrics; last_time=t; last_record=r
            if observations%100==0: print('observations',observations,'time',t,flush=True)
    duration=last_time-origin
    costs=measurement['field_costs']['G0:1649.82']
    table=[]
    for d,rows in anchors.items():
        for v in 'abcd':
            selected=[r for r in rows if r['variant']==v]; n=sum(r['session'] for r in selected)
            table.append(dict(delta=d,variant=v,anchors=len(selected),sessions=n,share=n/len(selected),sessions_per_hour=n*3600/duration,
                uncached_equivalent_per_hour={fmt:n*3600/duration*costs[fmt]['uncached_equivalent'] for fmt in costs},
                avoidable_idle_machine_seconds=integrals['c' if v=='d' else v],expiry_driven_anchors=sum(r['expiry_before_next'] for r in selected),invalid_task_anchors=sum(r['invalid_tasks']>0 for r in selected)))
    trace_evidence=None
    if args.trace:
        trace=json.loads(Path(args.trace).read_bytes())
        selected=[e for e in trace if origin<=e['time']<=last_time]
        trace_evidence=dict(path=args.trace,time_start=trace[0]['time'],time_end=trace[-1]['time'],events_in_ledger_span=len(selected),rework_events_in_ledger_span=sum(e['kind']=='rework' for e in selected),rework_events_all=sum(e['kind']=='rework' for e in trace))
    return dict(measurement_source=args.measurement,session_costs={f:c['uncached_equivalent'] for f,c in costs.items()},trace_evidence=trace_evidence,generated_at=datetime.now(timezone.utc).isoformat(),time_start=origin,time_end=last_time,duration=duration,observations=observations,distinct_times=len(distinct),kinds=dict(kinds),plan_versions=dict(versions),single_observed_trajectory=True,baseline_metric_mismatches=mismatches,table=table,anchors=anchors,
        limitations=['One realized plan history, not causal counterfactual outcomes.',
        'Pre-decision anchors: public_702 restored for origin; later preceding ledger observations carried only when trace proves no intervening physical event before plan commit. Exact-anchor ledger snapshots are post-dispatch and cannot measure decision needs.',
        'Unresolved session failures absent: assumed false; no counterfactual finish/stall or interrupt replay.',
        'Machine-seconds use left rectangle integration over all observations (last at duplicate times).',
        'Persistence d leaves quality integral equal to c; no new between-anchor wake condition.',
        'Costs assume one G0-sized request/session and fully cached prefix at 0.1; tool rounds and first uncached prefix excluded.',
        'Ledger contains observations, not rework events; optional companion trace supplies the rework census.'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('public-ledger','measurement','output'): p.add_argument('--'+key,required=True)
    p.add_argument('--trace',required=True)
    p.add_argument('--initial-fixture',required=True)
    a=p.parse_args(); result=run(a); Path(a.output).write_bytes(canonical(result)+b'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='anchors'},ensure_ascii=False,sort_keys=True,indent=2))
