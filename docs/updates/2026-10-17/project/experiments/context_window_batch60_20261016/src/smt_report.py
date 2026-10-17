"""Offline SMT evidence summaries and fixed-repeat plots. No model or solver calls."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import statistics
import time
from collections import Counter, defaultdict
from src.experiment import ROOT, read_json, write_json, now

QUALITY = (
    'throughput_lots', 'throughput_wafers', 'mean_cycle_seconds_completed',
    'tardy_completed_lots', 'total_tardiness_completed_seconds', 'initial_wip_lots',
    'released_new_lots', 'terminal_wip_lots', 'wip_change', 'terminal_tardy_wip_lots',
    'controlled_completed_operation_lots', 'controlled_family_queue_area_lot_seconds',
    'controlled_decisions', 'controlled_dispatches', 'dispatches',
    'unfinished_controlled_batches', 'controlled_batch_fill_mean',
    'controlled_batch_count', 'time_average_wip_lots',
    'time_average_controlled_family_queue_lots', 'throughput_lots_per_hour',
    'queue_area_delta_paired_A_percent', 'throughput_lots_delta_paired_A',
)
COSTS = ('end_to_end_seconds', 'model_calls', 'model_elapsed_seconds', 'solver_calls',
         'solver_wall_seconds', 'solver_budget_seconds', 'input_tokens',
         'cached_input_tokens', 'output_tokens', 'cost_usd')


def _csv(path, rows):
    if not rows:
        path.write_text('', encoding='utf-8')
        return
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows({k: json.dumps(v, ensure_ascii=False, sort_keys=True)
                    if isinstance(v, (list, dict)) else v for k, v in row.items()}
                   for row in rows)


def _number(x):
    return type(x) in (int, float) and math.isfinite(x)


def _stats(values):
    values = [v for v in values if _number(v)]
    return {'n': len(values), 'mean': statistics.mean(values) if values else None,
            'median': statistics.median(values) if values else None,
            'min': min(values) if values else None, 'max': max(values) if values else None}


def _union(intervals, end):
    merged = []
    for a, b in sorted((max(0., a), min(end, b)) for a, b in intervals if b > 0 and a < end):
        if b <= a:
            continue
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


def _length(intervals):
    return sum(b-a for a, b in intervals)


def _intersection_length(a, b):
    i = j = 0
    total = 0.
    while i < len(a) and j < len(b):
        total += max(0., min(a[i][1], b[j][1])-max(a[i][0], b[j][0]))
        if a[i][1] <= b[j][1]:
            i += 1
        else:
            j += 1
    return total


def trace_metrics(path):
    """Descriptive replay of certified event fields; not a feasibility certifier."""
    with path.open() as f:
        events = [json.loads(line) for line in f if line.strip()]
    if not events or events[0].get('kind') != 'initial':
        raise ValueError('Trace lacks initial manifest')
    manifest = events[0]['manifest']
    horizon = float(manifest['horizon'])
    end = min(horizon, max(float(e['time']) for e in events))
    machines = {m['id']: m for m in manifest['machines']}
    lots = {lot['id']: lot for lot in manifest['lots']}
    routes = manifest['routes']
    controls = set(manifest['controlled_machine_ids'])
    families = sorted({machines[mid]['family'] for mid in controls})
    queued = {}
    queues = Counter()
    wip = completed = 0
    series = []
    dispatches = Counter()
    reservations = defaultdict(list)
    downtime = defaultdict(list)
    jobs = {}
    decisions = []
    wip_area = queue_area = 0.
    previous = 0.
    for e in events:
        t = min(end, float(e['time']))
        if t < previous:
            raise ValueError('Trace time is not monotone')
        wip_area += wip*(t-previous)
        queue_area += sum(queues.values())*(t-previous)
        previous = t
        kind = e['kind']
        if kind == 'release':
            wip += 1
        elif kind == 'lot_complete':
            wip -= 1
            completed += 1
        elif kind == 'ready':
            family = routes[lots[e['lot']]['route']][e['step']-1]['family']
            if family in families:
                queued[e['lot']] = family
                queues[family] += 1
        elif kind == 'dispatch':
            mid = e['machine']
            dispatches[mid] += 1
            reservations[mid].append([t, float(e['machine_ready'])])
            jobs[e['job']] = {'machine': mid, 'start': t, 'end': float(e['process_end'])}
            for lid in e['lots']:
                family = queued.pop(lid, None)
                if family:
                    queues[family] -= 1
        elif kind == 'downtime':
            mid = e['machine']
            # Simultaneous/overlapping downtime is serialized by the event model.
            downtime[mid].append([e['blocked_until']-e['duration'], e['blocked_until']])
            if reservations[mid] and reservations[mid][-1][1] > t:
                reservations[mid][-1][1] = e['machine_ready']
            for jid in e['affected_jobs']:
                jobs[jid]['end'] += e['duration']
        elif kind == 'action':
            decisions.append({'decision': e['decision'], 'simulation_seconds': t,
                              'wait_seconds': e['action']['wait_seconds'],
                              'machine_ids': [d['machine'] for d in e['action']['dispatches']],
                              'selected_lots': sum(len(d['lot_ids']) for d in e['action']['dispatches'])})
        point = {'simulation_seconds': t, 'wip_lots': wip, 'cumulative_completed_lots': completed,
                 'controlled_family_queue_lots': sum(queues.values()),
                 **{'queue_'+family: queues[family] for family in families}}
        # Plot post-event state at each timestamp; no artificial order across t=0 events.
        if series and series[-1]['simulation_seconds'] == t:
            series[-1] = point
        else:
            series.append(point)
    material = defaultdict(list)
    for job in jobs.values():
        material[job['machine']].append([job['start'], job['end']])
    equipment = []
    for mid, m in sorted(machines.items()):
        if m['group'] == 'Delay_32':
            continue
        down = _union(downtime[mid], end)
        reserved = _union(reservations[mid], end)
        present = _union(material[mid], end)
        unavailable = _union(reserved+down, end)
        row = {'machine': mid, 'family': m['family'], 'group': m['group'],
               'controlled': mid in controls, 'cascading': m['cascading'],
               'observed_seconds': end, 'dispatches': dispatches[mid],
               'reserved_observed_seconds': _length(reserved),
               'calendar_down_observed_seconds': _length(down),
               'reserved_or_calendar_down_observed_seconds': _length(unavailable),
               'material_present_observed_seconds': _length(present),
               'material_present_excluding_calendar_down_proxy_seconds':
                   _length(present)-_intersection_length(present, down)}
        for name in ('reserved', 'calendar_down', 'reserved_or_calendar_down', 'material_present'):
            row[name+'_observed_fraction'] = row[name+'_observed_seconds']/end if end else None
        row['material_present_excluding_calendar_down_proxy_fraction'] = (
            row['material_present_excluding_calendar_down_proxy_seconds']/end if end else None)
        equipment.append(row)
    return {'manifest': manifest, 'horizon_seconds': horizon, 'observed_seconds': end,
            'full_window': events[-1].get('kind') == 'terminal' and abs(end-horizon) < 1e-6,
            'series': series, 'equipment': equipment, 'decisions': decisions,
            'time_average_wip_lots': wip_area/end if end else None,
            'wip_area_lot_seconds': wip_area,
            'controlled_family_queue_area_lot_seconds': queue_area,
            'time_average_controlled_family_queue_lots': queue_area/end if end else None}


def decision_costs(path, result):
    """Actual observation→apply latency is separate from model+solver service time."""
    rows = {}
    for action in result.get('actions', []):
        d = action['decision']
        rows[d] = {'decision': d, 'simulation_seconds': action['time'], 'committed': True,
                   'model_channel_seconds': 0., 'solver_seconds': 0., 'model_calls': 0,
                   'solver_calls': 0, 'solver_time_attribution_complete': True,
                   'observation_to_action_seconds': action.get('decision_elapsed_seconds')}
    for directory in sorted(path.glob('model_*_*')):
        if not (directory/'result.json').exists():
            continue
        decision = int(directory.name.split('_')[1])
        row = rows.setdefault(decision, {'decision': decision, 'simulation_seconds': None,
              'committed': False, 'model_channel_seconds': 0., 'solver_seconds': 0.,
              'model_calls': 0, 'solver_calls': 0, 'solver_time_attribution_complete': True,
              'observation_to_action_seconds': None})
        r = read_json(directory/'result.json')
        row['model_channel_seconds'] += r['duration_seconds']
        row['model_calls'] += 1
    solvers = result.get('solver_results', [])
    for index, solver in enumerate(solvers):
        decision = solver.get('decision')
        # Legacy A has exactly one ordered solver call per committed decision.
        if decision is None and result['arm'] in ('A', 'F') and len(solvers) == len(result.get('actions', [])):
            decision = result['actions'][index]['decision']
        if decision is None or decision not in rows:
            for row in rows.values():
                row['solver_time_attribution_complete'] = False
            continue
        rows[decision]['solver_seconds'] += solver['wall_seconds']
        rows[decision]['solver_calls'] += 1
    for row in rows.values():
        row['model_plus_solver_service_seconds'] = (row['model_channel_seconds']+row['solver_seconds']
            if row['solver_time_attribution_complete'] else None)
    return [rows[d] for d in sorted(rows)]


def _audit(phase):
    try:
        from src.smt_replay import audit_phase
    except ImportError as exc:
        return {'phase': phase, 'phase_errors': ['SMT evidence replay unavailable: '+str(exc)],
                'runs': [], 'auxiliary_runs': [], 'missing': [], 'coverage_complete': False,
                'acceptance_ready': False, 'expected_records': None}
    return audit_phase(phase)


def _incomplete_identity(path, evidence):
    identity = dict(evidence)
    for filename in ('claim.json', 'started.json'):
        try:
            saved = read_json(path/filename)
            identity.update(saved.get('identity', saved))
            if all(k in identity for k in ('scenario', 'arm', 'repeat')):
                break
        except (OSError, ValueError):
            continue
    return {k: identity.get(k) for k in ('scenario', 'arm', 'repeat')}


def _plot(out, run, trace, latency):
    import matplotlib.pyplot as plt
    x = [v['simulation_seconds']/3600 for v in trace['series']]
    fig, axes = plt.subplots(4, 1, figsize=(11, 10), sharex=True)
    specs = [('wip_lots', 'WIP (lots)'), ('cumulative_completed_lots', 'Completed lots'),
             ('controlled_family_queue_lots', 'Controlled-family queue (lots)')]
    for ax, (key, label) in zip(axes, specs):
        ax.step(x, [v[key] for v in trace['series']], where='post', label='total')
        ax.set_ylabel(label)
        ax.grid(alpha=.2)
    for key in trace['series'][0]:
        if key.startswith('queue_'):
            axes[2].step(x, [v[key] for v in trace['series']], where='post', alpha=.65, label=key[6:])
    axes[2].legend(fontsize=8)
    ids = trace['manifest']['controlled_machine_ids']
    for d in trace['decisions']:
        for mid in d['machine_ids']:
            axes[3].scatter(d['simulation_seconds']/3600, ids.index(mid), marker='|', s=150, color='C0')
        if d['wait_seconds']:
            axes[3].broken_barh([(d['simulation_seconds']/3600, d['wait_seconds']/3600)],
                                 (len(ids)-.3, .6), color='C1')
    axes[3].set(yticks=list(range(len(ids)+1)), yticklabels=[str(i) for i in ids]+['explicit wait'],
                ylabel='Control decisions', xlabel='Simulation time (hours)',
                xlim=(0, trace['horizon_seconds']/3600))
    axes[3].grid(alpha=.2)
    fig.suptitle(f'SMT2020 LVHM / scenario {run["scenario"]} / {run["arm"]} / fixed r1\n'
                 'Event trace; state changes are not wall-clock model latency')
    fig.tight_layout()
    fig.savefig(out/(run['run_id']+'_smt_dynamics.png'), dpi=135)
    plt.close(fig)
    if latency:
        fig, ax = plt.subplots(figsize=(9, 3.5))
        ix = [r['decision'] for r in latency]
        model = [r['model_channel_seconds'] for r in latency]
        ax.bar(ix, model, label='Model channel incl. CLI')
        if all(r['solver_time_attribution_complete'] for r in latency):
            ax.bar(ix, [r['solver_seconds'] for r in latency], bottom=model, label='Attributed solver')
        else:
            ax.text(.01, .96, 'Legacy solver-to-decision attribution unavailable; solver bars omitted',
                    transform=ax.transAxes, va='top', fontsize=8)
        ax.set(xlabel='Decision index', ylabel='Wall seconds (service only)',
               title=f'{run["run_id"]}: decision service time; excludes simulation and IO')
        ax.set_xticks(ix)
        ax.legend()
        fig.tight_layout()
        fig.savefig(out/(run['run_id']+'_smt_decision_service.png'), dpi=135)
        plt.close(fig)


def _aggregate(rows, keys):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row.get(k) for k in keys)].append(row)
    result = []
    for identity, members in sorted(groups.items(), key=lambda item: str(item[0])):
        successes = [m for m in members if m['certified_success']]
        statuses = Counter(m['report_status'] for m in members)
        item = {**dict(zip(keys, identity)), 'denominator': len(members),
                'certified_successes': len(successes), 'non_successes': len(members)-len(successes),
                'success_rate': len(successes)/len(members), 'status_counts': dict(statuses),
                'unique_external_scenarios': len({m['scenario'] for m in members}),
                'quality_conditional_success': {k: _stats(m.get(k) for m in successes) for k in QUALITY},
                'cost_all_records': {k: {**_stats(m.get(k) for m in members),
                    'sum_observed': sum(m[k] for m in members if _number(m.get(k))),
                    'unknown_records': sum(not _number(m.get(k)) for m in members)} for k in COSTS}}
        for key, value in item['cost_all_records'].items():
            if value['n'] == 0:
                value['sum_observed'] = None
        item['decision_service_seconds_mean_per_run_all'] = _stats(m.get('decision_service_seconds_mean') for m in members)
        item['observation_to_action_seconds_mean_per_run_all'] = _stats(m.get('observation_to_action_seconds_mean') for m in members)
        result.append(item)
    return result


def report(phase='development', plots=True):
    begun = time.process_time()
    child_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    out = ROOT/'artifacts'/phase
    out.mkdir(parents=True, exist_ok=True)
    audit = _audit(phase)
    write_json(out/'smt_report_evidence_audit.json', audit)
    certified = {r['run_id']: r for r in audit.get('runs', [])+audit.get('auxiliary_runs', [])}
    rows, decision_rows, machine_rows, series_rows, provenance = [], [], [], [], []
    plot_data = []
    warnings = []
    existing = set()
    for path in sorted((ROOT/'runs'/phase).glob('*/result.json')):
        try:
            r = read_json(path)
        except (OSError, ValueError) as exc:
            warnings.append('Unreadable result retained through audit inventory: '+str(path)+': '+str(exc))
            continue
        if r.get('family') != 'smt2020':
            continue
        existing.add(r['run_id'])
        evidence = certified.get(r['run_id'], {})
        verified = bool(evidence.get('audit_pass')) and not audit.get('phase_errors')
        success = (r.get('status') == 'success' and verified and evidence.get('domain_valid') is True
                   and (phase == 'development' or evidence.get('provenance_complete') is True))
        local_warnings = list(evidence.get('warnings', []))
        for key in ('adapter_version', 'window_seconds', 'controlled_machine_ids', 'warmup_seconds', 'outside_policy'):
            if key not in r:
                local_warnings.append('legacy result missing '+key+'; trace value remains descriptive, not a repaired result')
        m = evidence.get('recomputed_metrics') or evidence.get('metrics') or r.get('metrics') or {}
        costs = r.get('costs') or {}
        usage = costs.get('usage') or {}
        row = {'run_id': r['run_id'], 'scenario': r['scenario'], 'arm': r['arm'],
               'repeat': r['repeat'], 'auxiliary': r['arm'] == 'F', 'raw_status': r['status'],
               'certified_success': success, 'evidence_audit_pass': verified,
               'report_status': 'success' if success else ('uncertified' if r['status']=='success' else r['status']),
               'failure_type': r.get('failure_type'), 'audit_errors': evidence.get('errors', ['No run evidence audit']),
               'warnings': local_warnings,
               **{k: m.get(k) if success else None for k in QUALITY},
               **{k: usage.get(k) if k.endswith('tokens') else costs.get(k) for k in COSTS},
               'code_commit': r.get('code_commit'), 'config_sha256': r.get('config_sha256'),
               'data_sha256': r.get('data_sha256'), 'protocol_version': r.get('protocol_version'),
               'freeze_tag': r.get('freeze_tag'), 'freeze_manifest_sha256': r.get('freeze_manifest_sha256')}
        latency = decision_costs(path.parent, r)
        for d in latency:
            decision_rows.append({k: row[k] for k in ('run_id','scenario','arm','repeat','certified_success')} | d)
        row['decision_service_seconds_mean'] = _stats(d['model_plus_solver_service_seconds'] for d in latency)['mean']
        row['decision_service_seconds_max'] = _stats(d['model_plus_solver_service_seconds'] for d in latency)['max']
        row['observation_to_action_seconds_mean'] = _stats(d['observation_to_action_seconds'] for d in latency)['mean']
        if row['observation_to_action_seconds_mean'] is None:
            local_warnings.append('observation-to-action wall latency not recorded; service time excludes simulation/IO')
        if (path.parent/'trace.jsonl').exists():
            try:
                trace = trace_metrics(path.parent/'trace.jsonl')
                row['observed_seconds'] = trace['observed_seconds']
                row['window_seconds'] = trace['horizon_seconds']
                row['trace_full_window'] = trace['full_window']
                if success:
                    expected = m.get('controlled_family_queue_area_lot_seconds')
                    if not trace['full_window'] or not _number(expected) or abs(trace['controlled_family_queue_area_lot_seconds']-expected) > .01:
                        raise ValueError('Report trace area/full-window disagrees with certified metrics')
                    row.update(time_average_wip_lots=trace['time_average_wip_lots'],
                        time_average_controlled_family_queue_lots=trace['time_average_controlled_family_queue_lots'],
                        throughput_lots_per_hour=m['throughput_lots']/(trace['horizon_seconds']/3600),
                        controlled_batch_fill_mean=statistics.mean(m['controlled_batch_fill_ratios']) if m.get('controlled_batch_fill_ratios') else None,
                        controlled_batch_count=len(m.get('controlled_batch_fill_ratios', [])))
                ident = {k: row[k] for k in ('run_id','scenario','arm','repeat','certified_success')}
                machine_rows.extend(ident | v for v in trace['equipment'])
                if r['repeat'] == 1:
                    series_rows.extend(ident | v for v in trace['series'])
                    if success:
                        plot_data.append((r, trace, latency))
            except (ValueError, KeyError, TypeError) as exc:
                row.update(certified_success=False, report_status='report_trace_error')
                row['audit_errors'] = row['audit_errors']+['Descriptive trace extraction failed: '+str(exc)]
                for key in QUALITY:
                    row[key] = None
        rows.append(row)
        provenance.append({'run_id': r['run_id'], **{k: r.get(k) for k in (
            'code_commit','working_tree_dirty','config_sha256','data_sha256','source_sha256',
            'protocol_version','freeze_tag','freeze_manifest_sha256','adapter_version',
            'window_seconds','controlled_machine_ids','warmup_seconds','outside_policy')},
            'evidence_audit_pass': verified, 'warnings': local_warnings})
    # Retain interrupted/unreadable development attempts when a saved claim identifies them.
    for evidence in list(certified.values())+audit.get('incomplete', []):
        run_id = evidence['run_id']
        if run_id in existing:
            continue
        identity = _incomplete_identity(ROOT/'runs'/phase/run_id, evidence)
        if any(v is None for v in identity.values()):
            warnings.append('Unidentified attempt cannot be assigned to a matrix cell: '+run_id)
            continue
        rows.append({'run_id':run_id, **identity, 'auxiliary':identity['arm']=='F',
                     'raw_status':evidence.get('status'), 'certified_success':False,
                     'evidence_audit_pass':False, 'report_status':evidence.get('status','incomplete'),
                     'failure_type':'unreadable_or_incomplete_result',
                     'audit_errors':evidence.get('errors',[])})
        existing.add(run_id)
    # Missing frozen matrix entries remain in the denominator, never as zero quality/cost.
    for missing in audit.get('missing', []):
        if isinstance(missing, dict):
            key = [missing.get('scenario'), missing.get('arm'), missing.get('repeat')]
            run_id = missing.get('run_id', f'smt{key[0]}_{key[1]}_r{key[2]}')
        else:
            key = list(missing)
            run_id = f'smt{key[0]}_{key[1]}_r{key[2]}'
        if run_id in existing:
            continue
        rows.append({'run_id':run_id, 'scenario':key[0], 'arm':key[1], 'repeat':key[2],
                     'auxiliary':key[1]=='F', 'raw_status':None, 'certified_success':False,
                     'evidence_audit_pass':False, 'report_status':'missing', 'failure_type':'missing_result'})
    baseline = {(r['scenario'], r['repeat']): r for r in rows
                if r['arm'] == 'A' and r['certified_success']}
    for row in rows:
        base = baseline.get((row['scenario'], row['repeat']))
        if row['certified_success'] and base:
            area = base['controlled_family_queue_area_lot_seconds']
            row['queue_area_delta_paired_A_percent'] = (
                100*(row['controlled_family_queue_area_lot_seconds']-area)/area if area else None)
            row['throughput_lots_delta_paired_A'] = row['throughput_lots']-base['throughput_lots']
    final_success = {row['run_id']: row['certified_success'] for row in rows}
    for child_row in decision_rows+machine_rows+series_rows:
        child_row['certified_success'] = final_success[child_row['run_id']]
    group_rows = []
    groups = defaultdict(list)
    for m in machine_rows:
        groups[(m['run_id'],m['group'])].append(m)
    fractions = [k for k in machine_rows[0] if k.endswith('_fraction')] if machine_rows else []
    for (run_id, group), members in sorted(groups.items()):
        group_rows.append({'run_id':run_id,'group':group,'physical_machines':len(members),
            'certified_success':members[0]['certified_success'],
            **{k:statistics.mean(m[k] for m in members) if all(m[k] is not None for m in members) else None for k in fractions}})
    _csv(out/'smt_results.csv', rows)
    _csv(out/'smt_decisions.csv', decision_rows)
    _csv(out/'smt_machine_observation.csv', machine_rows)
    _csv(out/'smt_group_observation.csv', group_rows)
    _csv(out/'smt_timeseries_r1.csv', series_rows)
    write_json(out/'smt_provenance.json', provenance)
    summary = {'at':now(), 'phase':phase, 'records_including_missing':len(rows),
        'certified_successes':sum(r['certified_success'] for r in rows),
        'non_successes':sum(not r['certified_success'] for r in rows),
        'core_records':sum(r['arm'] in ('A','B','C') for r in rows),
        'auxiliary_records':sum(r['arm']=='F' for r in rows),
        'unique_external_scenarios':len({r['scenario'] for r in rows}),
        'scenario_values':sorted({r['scenario'] for r in rows}),
        'core_arms':['A','B','C'], 'auxiliary_arm':'F',
        'per_scenario_arm':_aggregate(rows, ('scenario','arm')),
        'per_arm':_aggregate(rows, ('arm',)),
        'coverage_complete':audit.get('coverage_complete',False),
        'acceptance_ready':audit.get('acceptance_ready',False) and all(
            r['evidence_audit_pass'] and r['report_status'] != 'report_trace_error' for r in rows),
        'expected_records':audit.get('expected_records'), 'missing_records':len(audit.get('missing',[])),
        'incomplete_attempts':audit.get('incomplete',[]),
        'phase_errors':audit.get('phase_errors',[]), 'warnings':warnings,
        'quality_population':'Only raw success plus independent evidence audit; failure/missing retained in denominators.',
        'repeat_interpretation':'External seed is scenario; repeats reuse that scenario and are not independent factory scenarios.',
        'monetary_cost':'Unknown unless actual billing is present; null is never converted to zero.',
        'plot_selection':'Fixed repeat 1, certified successes only; never select the best repeat.',
        'plot_files':[],
        'utilization_interpretation':'Observed reservation and calendar-down intervals; material-presence is a proxy, not pure production utilization.',
        'model_calls_for_reporting':0,'solver_calls_for_reporting':0}
    if plots and plot_data:
        os.environ.setdefault('MPLCONFIGDIR',str(out/'.matplotlib'))
        import matplotlib
        matplotlib.use('Agg')
        for run, trace, latency in plot_data:
            _plot(out, run, trace, latency)
            summary['plot_files'].append(run['run_id']+'_smt_dynamics.png')
            if latency:
                summary['plot_files'].append(run['run_id']+'_smt_decision_service.png')
    summary['report_process_cpu_seconds'] = time.process_time()-begun
    child_end = resource.getrusage(resource.RUSAGE_CHILDREN)
    summary['report_child_cpu_seconds'] = child_end.ru_utime+child_end.ru_stime-child_start.ru_utime-child_start.ru_stime
    summary['report_total_cpu_seconds'] = summary['report_process_cpu_seconds']+summary['report_child_cpu_seconds']
    summary['report_source_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    write_json(out/'smt_summary.json', summary)
    print(json.dumps({k:v for k,v in summary.items() if k not in ('per_arm','per_scenario_arm')}, ensure_ascii=False))
    return summary


if __name__ == '__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--phase',default='development')
    ap.add_argument('--no-plots',action='store_true')
    args=ap.parse_args()
    report(args.phase,not args.no_plots)
