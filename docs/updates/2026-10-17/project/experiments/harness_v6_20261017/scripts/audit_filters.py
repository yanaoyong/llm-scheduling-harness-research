"""Read-only filter census on frozen public evidence and seed=0 physical state.

No dispatch, planner, model, database writes or private future outcomes. Counts
are overlapping predicates, not additive categories. Write only requested output.
"""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
from harness_v6.ledger import ledger_from_scratch, ready, idle, eligible, choose_batch
from harness_v6.normalize import active_holds
from harness_v6.snapshot import canonical, current_state


def load_states(fixture, database, public_ledger):
    from harness_v6.sealed_contexts import SQLiteContextReader
    bundle = json.loads(Path(fixture).read_bytes())
    states = {}
    for entry in SQLiteContextReader(database, 'SELECT group_name,payload FROM contexts').contexts():
        c = entry['context']
        if entry['group'] == 'G0' and abs(c['time']-1649.82) < .01:
            states['G0:1649.82'] = dict(problem=c['problem'], plan=c['base_plan'], receipts={'tasks':[
                dict(task_id=t, state='running') for t in c['execution_state']['dispatched_task_ids']]},
                running_jobs=bundle['g0_snapshot']['running_jobs'], context=c)
            break
    with gzip.open(public_ledger, 'rt') as stream:
        for line in stream:
            row = json.loads(line)
            if row['time'] in (702,1182,1602):
                # First observation at timestamp; preserve evidence sequence identity.
                states.setdefault('P2:'+str(int(row['time'])), row)
            if all('P2:'+str(t) in states for t in (702,1182,1602)):
                break
    if len(states) != 4:
        raise ValueError('missing required G0/public state')
    from harness_v6.env_adapter import FullFabEnvironment
    env = FullFabEnvironment(seed=0, data_dir=bundle['data_dir'])
    states['SMT2020:0'] = dict(env.ledger_snapshot(), running_jobs=[dict(job=i, machine=j['machine'], lot_ids=j['lots'], started_at=j['start']) for i,j in env.jobs.items() if not j['done']])
    from harness_v6.physical_window import frozen_operations
    for name, record in states.items():
        if name != 'SMT2020:0':
            record['problem']=frozen_operations(record['problem'],env.manifest,running_jobs=record.get('running_jobs',[]),dispatches=bundle['g0_trace'] if name.startswith('G0') else ())
    return states, env


def census(record, horizon_seconds):
    p = record['problem']; now = p['time']; ops=p['operations']; ms=p['machines']
    ledger=ledger_from_scratch(p, record.get('plan'), record.get('receipts'))
    current=current_state(ledger,horizon_seconds=horizon_seconds,state_version='audit',running_jobs=record.get('running_jobs',[]),last_cycle_receipt=None,model_notes='')
    rows=ledger.rows(); pending=ledger.pending_tasks(); metrics=ledger.metrics()
    def count(predicate): return sum(bool(predicate(o)) for o in ops)
    candidates={o['operation_id']:o for o in ops if ready(o,now)}
    reserved={oid for t in pending for oid in t['operation_ids']}
    result=dict(time=now,sequence=record.get('seq'),operations=len(ops),lots_with_export=len({o['lot_id'] for o in ops}),
        operations_per_lot=dict(sorted(Counter(Counter(o['lot_id'] for o in ops).values()).items())),
        lookahead_depth=p.get('lookahead_depth'),readiness_basis=dict(sorted(Counter(o.get('readiness_basis','absent') for o in ops).items())),
        ready=count(lambda o:ready(o,now)),not_ready=count(lambda o:not ready(o,now)),
        ready_unreserved=len(current['unreserved_ready']),upcoming=len(current['upcoming_operations']),
        executing_within_h=count(lambda o:o.get('readiness_basis')=='executing_predecessor' and o['release_time']<=now+horizon_seconds),
        executing_beyond_h=count(lambda o:o.get('readiness_basis')=='executing_predecessor' and o['release_time']>now+horizon_seconds),
        executing_reserved=count(lambda o:o.get('readiness_basis')=='executing_predecessor' and o['operation_id'] in reserved),
        conditional=count(lambda o:o.get('conditional')),sampling_below_100=count(lambda o:o.get('sampling_percent',100)<100),
        qualification_uncertain=count(lambda o:o.get('qualification_uncertain')),same_machine_as=count(lambda o:o.get('same_machine_as')),
        predecessor_ids=count(lambda o:o.get('predecessor_ids')),future_release=count(lambda o:o.get('release_time',now)>now),
        placeholder_now=count(lambda o:o.get('readiness_basis')=='exported_predecessor' and o['release_time']==now),
        virtual_predecessors=count(lambda o:o.get('initial_virtual_predecessors')),
        virtual_successors=count(lambda o:o.get('conditional_virtual_successors')),
        observed_binding=count(lambda o:o.get('qualification_basis')=='observed binding'),
        machines=len(ms),busy=sum(m.get('currently_busy',False) for m in ms),down=sum(m.get('currently_down',False) for m in ms),
        unavailable_flag=sum(not m.get('available',True) for m in ms),interval_blocked=sum(any(a<=now<b for a,b in m.get('unavailable_intervals',[])) for m in ms),
        nonempty_intervals=sum(bool(m.get('unavailable_intervals')) for m in ms),idle=sum(idle(m,now) for m in ms),
        processing_capacity_full=sum(len(m.get('processing_until',[])) >= (2 if m.get('cascading') else 1) for m in ms),
        idle_processing_capacity_full=sum(idle(m,now) and len(m.get('processing_until',[])) >= (2 if m.get('cascading') else 1) for m in ms),
        setup_change_ops=count(lambda o:any(m['machine'] in o['eligible_machines'] and o.get('setup') and m.get('current_setup')!=o.get('setup') for m in ms)),
        min_left_positive=sum(m.get('min_left',0)>0 for m in ms),
        min_setup_excluded_ops=count(lambda o:any(m['machine'] in o['eligible_machines'] and m.get('min_left',0)>0 and m.get('min_setup')!=o.get('setup') for m in ms)),
        ready_qualification_excluded=count(lambda o:ready(o,now) and o.get('qualification_uncertain')),
        ready_same_machine_excluded=count(lambda o:ready(o,now) and o.get('same_machine_as')),
        pending_tasks=len(pending),invalid_tasks=len(current['invalid_tasks']),holds=len(ledger.holds),
        expired_holds=sum(h['until']<=now for h in ledger.holds.values()),
        held_machines=sum(bool(active_holds(ledger.holds.values(),machine=m['machine'],now=now,pending_tasks=[t for t in pending if t['machine']==m['machine']],dispatched_task_ids=[t for t,r in ledger.task_receipts.items() if r['state'] in ('running','done')])) for m in ms),
        avoidable_idle=metrics['avoidable_idle'],explicit_wait_idle=metrics['explicit_wait_idle'],opportunities=len(metrics['reserved_but_earlier_startable']),
        ready_without_any_eligible_machine=count(lambda o:ready(o,now) and not any(eligible(o,m) for m in ms)),
        idle_with_ready_candidates_but_no_batch=sum(idle(m,now) and any(eligible(o,m) for o in candidates.values()) and not choose_batch(candidates,m) for m in ms),
        omitted_operation_fields=sorted(set().union(*(set(o) for o in ops))-set().union(*(set(o) for o in current['unreserved_ready']))),
        problem_metadata_not_in_current=sorted(set(p)-set(current)-{'operations'}),
        running_job_fields=sorted(set().union(*(set(j) for j in record.get('running_jobs',[])))),
        running_jobs=len(record['running_jobs']) if 'running_jobs' in record else None,
        base_operations_absent=0)
    observed=set(ledger.operations)
    result['base_operations_absent']=len({oid for t in pending for oid in t['operation_ids'] if oid not in observed})
    return result


def run(fixture,database,public_ledger,horizon_seconds):
    states,env=load_states(fixture,database,public_ledger)
    result={name:census(row,horizon_seconds) for name,row in states.items()}
    # Nominal remaining physical steps are inventory, not forecasts of rework visits.
    static={m['id']:m for m in env.manifest['machines']}
    routes=env.manifest['routes']; physical_families={m.family for m in env.machines if m.idx in env.physical}
    for name,row in states.items():
        bylot={}
        for op in row['problem']['operations']: bylot.setdefault(op['lot_id'],[]).append(op)
        hidden=0
        for lid,ops in bylot.items():
            route=routes[env.lots[lid]['route']]
            last=max(o['step'] for o in ops)
            hidden+=sum(s['step']>last and s['family'] in physical_families for s in route)
        result[name].update(nominal_later_physical_steps_beyond_export=hidden,
            static_total_machines=len(static),physical_machines=len(env.physical),
            virtual_delay_resources=len(static)-len(env.physical),controlled_physical=len(env.controlled),uncontrolled_physical=len(env.physical-env.controlled))
    result['SMT2020:0']['lot_statuses']=dict(Counter(l['status'] for l in env.lots.values()))
    return dict(horizon_seconds=horizon_seconds,states=result,
        limitations=['P2 uses first frozen ledger observation per timestamp; no replay or new scheduling.',
        'Later-step inventory counts nominal physical route steps after each exported lot tail, not future rework visits.',
        'P2 ledger has no running_jobs/private lot state; absent data reported null, never zero.',
        'Global static machine inventory uses identical SMT2020 source manifest at seed 0; only dynamic counts come from frozen contexts.'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('fixture','database','public-ledger','output'):p.add_argument('--'+name,required=True)
    p.add_argument('--horizon-seconds',type=float,required=True)
    a=p.parse_args(); result=run(a.fixture,a.database,a.public_ledger,a.horizon_seconds)
    Path(a.output).write_bytes(canonical(result)+b'\n')
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2))
