"""Two-pass JSONL metric reconstruction with no retained event/plan history.

The returned metric schema is identical to metrics.compute_metrics. This is not
physical validation or a streaming replacement for the independent audit. Memory
still grows with lot metadata, job/occupancy intervals and batch-fill output; one
JSONL record is parsed at a time, so the largest record also bounds transient RAM.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re

from .metrics import DEFAULT_PRIORITY_WEIGHTS, METRICS_VERSION, _finite, _union_seconds, weighted_tardy_seconds

STREAM_IMPLEMENTATION_VERSION = 'smt-fullfab-stream-metrics-v2'
# Queue interval sums use incremental += instead of Python 3.12's compensated
# sum(generator). Compare this floating field with these declared tolerances;
# integer counts, identities, classifications and all other values stay exact.
QUEUE_SUM_REL_TOLERANCE = 1e-12
QUEUE_SUM_ABS_TOLERANCE = 1e-7


def _events(path, hasher):
    """Yield individual records; blank lines count in the hash, not event indexes."""
    with path.open('rb') as stream:
        for line in stream:
            hasher.update(line)
            if line.strip():
                event=json.loads(line)
                if not isinstance(event,dict):
                    raise ValueError('metric JSONL records must be objects')
                yield event


def compute_metrics(source, *, window_start=0.0, window_end=None,
                    priority_weights=None, include_lot_details=False,
                    expected_source_sha256=None):
    """Read a stable JSONL path twice and reproduce the legacy observed metrics.

    All records are parsed and hashed in both passes. The first pass checks the
    full-file observed endpoint and snapshot-prefix contract; the second folds
    events up to the requested endpoint. Prefix history is required even for a
    subwindow. A file changed between passes is rejected, never silently mixed.
    No environment, solver, model, or legacy compute_metrics call is involved.
    An optional externally recorded SHA binds both complete raw-byte passes to
    that source, not merely to each other. This is content binding only, not
    authentication of the caller's expected hash or a physical certificate.
    """
    if not isinstance(source,(str,Path)):
        raise TypeError('stream metrics requires a JSONL file path')
    if expected_source_sha256 is not None and (type(expected_source_sha256) is not str
            or re.fullmatch('[0-9a-f]{64}',expected_source_sha256) is None):
        raise ValueError('expected_source_sha256 must be 64 lowercase hexadecimal characters')
    path=Path(source)
    first_hash=hashlib.sha256();manifest=None;first_time=None;last_kind=None;observed_end=-math.inf
    for index,event in enumerate(_events(path,first_hash)):
        if index==0:
            if event.get('kind')!='initial':
                raise ValueError('missing initial manifest and replayable event history')
            manifest=event['manifest'];first_time=event['time']
        if event.get('kind')=='snapshot_loaded' and (first_time!=0 or event.get('prefix_event_count')!=index):
            raise ValueError('snapshot root requires complete prehistory before metric computation')
        observed_end=max(observed_end,_finite(event['time'],'event time'))
        last_kind=event.get('kind')
    if expected_source_sha256 is not None and first_hash.hexdigest()!=expected_source_sha256:
        raise ValueError('metric source differs from externally expected SHA-256')
    if manifest is None:
        raise ValueError('missing initial manifest and replayable event history')
    start=_finite(window_start,'window_start')
    end=observed_end if window_end is None else _finite(window_end,'window_end')
    if start<first_time or end>observed_end or end<=start:
        raise ValueError('metric window must be positive and within observed event history')
    weights={int(k):_finite(v,'priority weight') for k,v in
             (DEFAULT_PRIORITY_WEIGHTS if priority_weights is None else priority_weights).items()}
    if any(v<=0 for v in weights.values()):raise ValueError('priority weights must be positive')
    lots={lot['id']:lot for lot in manifest['lots']}
    if len(lots)!=len(manifest['lots']):raise ValueError('duplicate lot in manifest')
    machines={m['id']:m for m in manifest['machines']}
    production={mid for mid,m in machines.items() if m['group']!='Delay_32'}
    releases,completions,ready={},{},{}
    reservations,materials,calendar=defaultdict(list),{},defaultdict(list)
    jobs_by_machine=defaultdict(list)
    queue_wait=defaultdict(int);family_dispatches=defaultdict(int);family_operation_lots=defaultdict(int)
    fills=[];setup_seconds=0.0;previous=first_time;past_window=False
    second_hash=hashlib.sha256()
    for event in _events(path,second_hash):
        # Still consume/hash the suffix; its timestamps/JSON were checked above.
        if past_window:continue
        t,kind=_finite(event['time'],'event time'),event['kind']
        if t<previous:raise ValueError('time reversed')
        previous=t
        if t>end:
            past_window=True
            continue
        if kind=='release':
            lid=event['lot']
            if lid not in lots or lid in releases:raise ValueError('unknown or duplicate release')
            releases[lid]=t
        elif kind=='lot_complete':
            lid=event['lot']
            if lid not in releases or lid in completions:raise ValueError('unknown or duplicate completion')
            completions[lid]=t
        elif kind=='ready':
            if event['lot'] in ready:raise ValueError('duplicate ready state')
            ready[event['lot']]=(t,event['step'])
        elif kind=='dispatch':
            mid,jid=event['machine'],event['job']
            for lid in event['lots']:
                if lid not in ready:raise ValueError('dispatch without ready event')
                rt,step=ready.pop(lid)
                family=manifest['routes'][lots[lid]['route']][step-1]['family']
                queue_wait[family]+=max(0,min(t,end)-max(rt,start))
            if jid in materials:raise ValueError('duplicate job')
            materials[jid]=[t,event['process_end']]
            reservations[mid].append([t,event['machine_ready']])
            jobs_by_machine[mid].append(jid)
            if mid in production:
                dispatch_time=event['time']
                if start<=dispatch_time<end:
                    family=machines[mid]['family'];family_dispatches[family]+=1
                    family_operation_lots[family]+=len(event['lots'])
                setup_seconds+=max(0.0,min(end,dispatch_time+event['setup_seconds'])-max(start,dispatch_time))
                step=manifest['routes'][lots[event['lots'][0]]['route']][event['steps'][0]-1]
                if step['batch_max']>1 and start<=dispatch_time<end:
                    fills.append(len(event['lots'])/step['batch_max'])
        elif kind=='downtime':
            mid=event['machine']
            calendar[mid].append((event['blocked_until']-event['duration'],event['blocked_until']))
            for jid in event['affected_jobs']:
                if jid not in materials:raise ValueError('downtime references unknown job')
                materials[jid][1]+=event['duration']
            if reservations[mid] and reservations[mid][-1][1]>t:
                reservations[mid][-1][1]=event['machine_ready']
    if first_hash.digest()!=second_hash.digest():
        raise ValueError('metric source changed between streaming passes')
    for lid,(rt,step) in ready.items():
        family=manifest['routes'][lots[lid]['route']][step-1]['family']
        queue_wait[family]+=max(0,min(end,end)-max(rt,start))
    population=[lid for lid,rt in releases.items() if rt<=end and completions.get(lid,math.inf)>start]
    done=[lid for lid,ct in completions.items() if start<ct<=end]
    initial=[lid for lid,rt in releases.items() if rt<=start and completions.get(lid,math.inf)>start]
    arrivals=[lid for lid,rt in releases.items() if start<rt<=end]
    terminal=[lid for lid,rt in releases.items() if rt<=end and lid not in completions]
    details=[]
    for lid in population:
        lot=lots[lid]
        if lot['priority'] not in weights:raise ValueError(f"unmapped priority {lot['priority']}")
        contribution=weighted_tardy_seconds(release=releases[lid],due=lot['due'],completion=completions.get(lid),
            window_start=start,window_end=end,weight=weights[lot['priority']])
        details.append({'lot':lid,'priority':lot['priority'],'weight':weights[lot['priority']],
                        'completed_in_window':lid in completions,'weighted_tardy_seconds':contribution})
    total=sum(row['weighted_tardy_seconds'] for row in details)
    weight_sum=sum(row['weight'] for row in details)
    exposure=sum(weights[lots[lid]['priority']]*max(0.0,end-max(start,releases[lid])) for lid in population)
    summary={}
    for field in ('part','priority'):
        summary[field]={}
        for value in sorted({lots[lid][field] for lid in population},key=str):
            group_done=[lid for lid in done if lots[lid][field]==value]
            group_wip=[lid for lid in terminal if lots[lid][field]==value]
            ontime=sum(completions[lid]<=lots[lid]['due'] for lid in group_done)
            summary[field][str(value)]={
                'completed_lots':len(group_done),'ontime_completed_lots':ontime,
                'ontime_fraction_completed_only':ontime/len(group_done) if group_done else None,
                'terminal_wip_lots':len(group_wip),
                'terminal_tardy_wip_lots':sum(lots[lid]['due']<end for lid in group_wip)}
    family_statistics={}
    for family in sorted({machines[mid]['family'] for mid in production}):
        mids={mid for mid in production if machines[mid]['family']==family}
        family_statistics[family]={
            'machine_count':len(mids),'dispatches':family_dispatches[family],
            'operation_lots_dispatched':family_operation_lots[family],
            'queue_wait_lot_seconds':queue_wait[family],
            'reserved_observed_fraction':sum(_union_seconds(reservations[mid],start,end) for mid in mids)/(len(mids)*(end-start)),
            'calendar_down_observed_fraction':sum(_union_seconds(calendar[mid],start,end) for mid in mids)/(len(mids)*(end-start)),
            'material_present_observed_fraction':sum(_union_seconds([materials[jid] for jid in jobs_by_machine[mid]],start,end) for mid in mids)/(len(mids)*(end-start))}
    result={
        'metrics_version':METRICS_VERSION,'window_start':start,'window_end':end,'observed_seconds':end-start,
        'completed_declared_window':bool(last_kind=='terminal' and end==manifest['horizon']),
        'priority_weights':{str(k):v for k,v in weights.items()},
        'priority_weight_status':'development_proposal_requires_prefreeze',
        'weighted_tardy_lot_seconds':total,'weighted_tardy_lot_hours':total/3600,
        'weighted_tardy_seconds_completed_contribution':sum(r['weighted_tardy_seconds'] for r in details if r['completed_in_window']),
        'weighted_tardy_seconds_unfinished_contribution':sum(r['weighted_tardy_seconds'] for r in details if not r['completed_in_window']),
        'normalization_population_weight':weight_sum,
        'mean_tardy_seconds_per_weighted_lot':total/weight_sum if weight_sum else None,
        'tardy_fraction_of_exogenous_weighted_exposure':total/exposure if exposure else None,
        'exogenous_weighted_exposure_seconds':exposure,'throughput_lots':len(done),
        'throughput_wafers':sum(lots[lid]['pieces'] for lid in done),'initial_window_wip_lots':len(initial),
        'released_in_window_lots':len(arrivals),'terminal_wip_lots':len(terminal),
        'lot_conservation_valid':len(initial)+len(arrivals)==len(done)+len(terminal),
        'terminal_tardy_wip_lots':sum(lots[lid]['due']<end for lid in terminal),
        'window_start_already_tardy_wip_lots':sum(lots[lid]['due']<start for lid in initial),
        'mean_cycle_seconds_completed':sum(completions[lid]-lots[lid]['release'] for lid in done)/len(done) if done else None,
        'completion_groups':summary,'setup_loss_seconds':setup_seconds,'batch_dispatch_count':len(fills),
        'batch_fill_mean':sum(fills)/len(fills) if fills else None,'batch_fill_ratios':fills,
        'production_family_statistics':family_statistics,
        'interpretation':'observed-window metrics, not a steady-state or physical-validity certificate'}
    if include_lot_details:result['lot_contributions']=details
    return result
