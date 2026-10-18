"""Offline physical-window and field-cost measurement. No production mutations.

Requires explicitly supplied local SMT2020 fixtures and o200k_base cache. JSON
output is the full reproducible measurement; no model/network calls are made.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from audit_filters import load_states
from phase_s_helpers import distribution_bounds, phase_duration, lower_bound_walk, depth_distribution
from harness_v6.compact import (encode_current, decode_prefix, decode_snapshot, normalize,
                                section, dense_section, sections)
from harness_v6.snapshot import canonical, current_state, stable_prefix, tiktoken_counter
from harness_v6.ledger import ledger_read_view

WINDOWS = (900, 1800, 3600)


def get_current(record):
    return current_state(ledger_read_view(record['problem'], record.get('plan'), record.get('receipts')),
                         horizon_seconds=900, state_version=record.get('context', {}).get('state_revision', 'measurement'),
                         running_jobs=record.get('running_jobs', []), last_cycle_receipt=None, model_notes='')


def family_table(manifest):
    result = defaultdict(list)
    for m in manifest['machines']:
        result[m['family']].append(m)
    return result


def window_rows(record, manifest, *, private_lots=None, dispatches=(), weak_start=False):
    """Frozen states use public operations + manifest, never future event samples.

    Private t=0 status/visits are current observations, not random future values.
    G0 job identity is joined to past dispatch step/visit evidence; P2 falls back
    to now. Absent historical visit counts beyond exports use nominal visit=1.
    """
    now = record['problem']['time']; routes = manifest['routes']; machines = family_table(manifest)
    lots = {l['id']: l for l in manifest['lots']}
    exported = {o['operation_id']: o for o in record['problem']['operations']}
    bylot = defaultdict(list)
    for op in exported.values():
        bylot[op['lot_id']].append(op)
    jobs = {lid: j for j in record.get('running_jobs', []) for lid in j['lot_ids']}
    public_dispatch = {e['job']: e for e in dispatches if e['kind'] == 'dispatch' and e['time'] <= now}
    rows = []; all_bounds = {}; depths_lots = set(); counts = Counter()
    # Public manifest releases after now are unreleased; other absent lots at a
    # frozen state have unknown status and cannot be guessed from seed=0 state.
    candidate_ids = set(bylot) | {lid for lid, l in lots.items() if now < l['release'] <= now + max(WINDOWS)}
    if private_lots is not None:
        candidate_ids |= {lid for lid, l in private_lots.items() if l['status'] not in ('done', 'unreleased')}
    for lid in sorted(candidate_ids):
        lot = lots[lid]; route = routes[lot['route']]; ops = sorted(bylot[lid], key=lambda o: o['step'])
        lookup = {o['step']: o for o in ops}; first = ops[0] if ops else None
        priv = private_lots.get(lid) if private_lots is not None else None
        unreleased = (priv['status'] == 'unreleased') if priv else lot['release'] > now
        executing = None; first_bound = now; nominal = now; observed = False
        if unreleased:
            start = 0; first_bound = nominal = lot['release']; basis = 'unreleased_first_step'
        elif priv:
            start = priv['step']; observed = priv['status'] == 'waiting'; basis = 'observed_ready' if observed and any(m['group'] != 'Delay_32' for m in machines[route[start]['family']]) else 'later_chain_step'
        elif first:
            start = first['step'] - 1; observed = first.get('readiness_basis') == 'observed_ready'
            basis = 'observed_ready' if observed else 'executing_successor' if first.get('readiness_basis') == 'executing_predecessor' else 'later_chain_step'
            nominal = max(now, first['release_time'])
            job = jobs.get(lid); evidence = public_dispatch.get(job['job']) if job else None
            if basis == 'executing_successor' and job and evidence and not weak_start:
                i = evidence['lots'].index(lid); current_index = evidence['steps'][i] - 1
                # Advance from the actually executing step, including any virtual
                # steps between it and the first exported physical successor.
                executing = (job['started_at'], phase_duration(route, current_index, machines)[0])
                start = current_index + 1
                nominal = max(now, job['started_at'] + evidence['setup_seconds'] + phase_duration(route, current_index, machines)[1])
                counts['executing_lots_with_public_start_and_step'] += 1
            elif basis == 'executing_successor':
                counts['executing_lots_using_now'] += 1
        else:
            continue
        depths_lots.add(lid)
        walked = lower_bound_walk(route, start, now=now, first_bound=first_bound, first_nominal=nominal,
                                  machines=machines, executing=executing, release=lot['release'] if unreleased else None,
                                  observed_first=observed)
        physical_rank = 0
        for w in walked:
            step = route[w['step'] - 1]; group = [m for m in machines[step['family']] if m['group'] != 'Delay_32']
            old = lookup.get(w['step'])
            visit = old['visit'] if old else ((priv['visits'].get(str(w['step']), 0) + (0 if observed and w['step'] == route[start]['step'] else 1)) if priv else 1)
            oid = f"{lid}:{w['step']}:{visit}"
            all_bounds[oid] = w['earliest_start']
            if not group:
                continue
            if w['earliest_start'] <= now + max(WINDOWS):
                row = dict(operation_id=oid, earliest_start=w['earliest_start'], nominal_start=w['nominal_start'],
                           batch_key=[lot['part'], step['step'], step['name']], batch_min=step['batch_min'], batch_max=step['batch_max'],
                           setup=step['setup'], eligible_machines=old['eligible_machines'] if old else [m['id'] for m in group],
                           sampling_percent=step['sampling_percent'], conditional=w['conditional'],
                           readiness_basis=basis if physical_rank == 0 else 'later_chain_step')
                rows.append(row)
            physical_rank += 1
    return rows, all_bounds, depths_lots, dict(counts)


def wire_cost(rows, manifest, counter):
    # Reuse actual compact grouping and family/set references, strip basis only
    # because it is a measurement category, not part of the requested section.
    requested = [{k: v for k, v in r.items() if k != 'readiness_basis'} for r in rows]
    result = {}
    for fmt in ('explicit', 'dense'):
        wire = encode_current({'machine_groups': manifest['machines']}, {'upcoming_operations': requested, 'machines': []}, snapshot_format=fmt, token_counter=counter)
        vals = sections(wire.decode().split('\n', 1)[1])
        writer = section if fmt == 'explicit' else lambda n, v: dense_section(n, v, counter)
        text = writer('upcoming_operations', vals['upcoming_operations']) + writer('eligible_sets', vals['eligible_sets'])
        result[fmt] = counter(text)
    return result


def qualification_probe(env, record):
    ops = [o for o in record['problem']['operations'] if o.get('qualification_uncertain') and o['readiness_basis'] == 'observed_ready']
    pairs = accepted = bindings = 0
    cache = {m: set(env.eligible(m)) for o in ops for m in o['eligible_machines']}
    for o in ops:
        bindings += bool(env.lots[o['lot_id']]['dedications'])
        for mid in o['eligible_machines']:
            pairs += 1; accepted += o['lot_id'] in cache[mid]
    return dict(uncertain_observed_ready=len(ops), lots_with_any_recorded_dedication=bindings,
                family_machine_pairs=pairs, env_eligible_accepted=accepted, rejected=pairs-accepted)


def validate_forward(record, manifest, bundle, bounds, rows):
    # A separate base simulator has no controlled machines, so its unchanged
    # built-in background policy schedules all machines. FullFab is NOT patched.
    from src.smt.environment import SmtEnvironment
    env = SmtEnvironment(seed=0, window_seconds=86400, controlled_machine_ids=(), data_dir=bundle['data_dir'])
    assert env.manifest['routes'] == manifest['routes']
    assert env.manifest['lots'] == manifest['lots']
    env.horizon = max(WINDOWS)
    env.advance()
    current = get_current(record)
    visible = {r['operation_id'] for r in current['unreserved_ready'] + current['upcoming_operations']}
    exported = {o['operation_id'] for o in record['problem']['operations']}
    all_starts = [dict(time=e['time'], operation_id=f'{lid}:{s}:{v}', machine=e['machine'])
              for e in env.trace if e['kind'] == 'dispatch' and 0 < e['time'] <= max(WINDOWS)
              for lid, s, v in zip(e['lots'], e['steps'], e['visits'])]
    starts = [s for s in all_starts if s['machine'] in env.physical]
    virtual_starts = [s for s in all_starts if s['machine'] not in env.physical]
    violations = [dict(s, bound=bounds[s['operation_id']]) for s in all_starts if s['operation_id'] in bounds and s['time'] + 1e-8 < bounds[s['operation_id']]]
    result = dict(policy=env.manifest['outside_policy'], physical_starts=starts, virtual_starts=virtual_starts, violations=violations,
                  all_actual_starts=len(all_starts), all_bounds_comparable=sum(s['operation_id'] in bounds for s in all_starts),
                  rework_events=sum(e['kind'] == 'rework' for e in env.trace), windows=[])
    for w in WINDOWS:
        actual = [s for s in starts if s['time'] <= w]; window = {r['operation_id'] for r in rows if r['earliest_start'] <= w}
        result['windows'].append(dict(window=w, actual_starts=len(actual), virtual_starts=sum(s['time']<=w for s in virtual_starts), bounds_comparable=sum(s['operation_id'] in bounds for s in actual),
            window_covered=sum(s['operation_id'] in window for s in actual), visible_covered=sum(s['operation_id'] in visible for s in actual),
            exported_covered=sum(s['operation_id'] in exported for s in actual),
            missing_from_window=[s for s in actual if s['operation_id'] not in window]))
    return result


def field_payload(current, record, manifest, variant):
    """Lossless additions; decoded reconstruction asserted by caller."""
    result = deepcopy(current); lookup = {o['operation_id']: o for o in record['problem']['operations']}
    lots = {l['id']: l for l in manifest['lots']}; machines = family_table(manifest)
    lot_table = {}; templates = {}; expected = {}
    for row in result['unreserved_ready']:
        op = lookup[row['operation_id']]; lot = lots[op['lot_id']]; route = manifest['routes'][lot['route']]
        step = route[op['step']-1]; lo, _, hi = distribution_bounds(step['processing'])
        group = [m for m in machines[step['family']] if m['id'] in op['eligible_machines']]
        fields = dict(due=op['due'], priority=op['priority'], waiting_since=op['waiting_since'],
                      processing_seconds_min=lo + min(m['load']+m['unload'] for m in group),
                      processing_seconds_max=None if hi is None else hi + max(m['load']+m['unload'] for m in group))
        expected[row['operation_id']] = fields
        if variant == 'per_row':
            row.update(fields)
        else:
            lid = op['lot_id']; row['$lot'] = lid
            lot_table[lid] = dict(lot_id=lid, due=fields['due'], priority=fields['priority'], waiting_since=fields['waiting_since'])
            if variant == 'per_lot':
                row.update({k:v for k,v in fields.items() if k.startswith('processing_')})
            else:
                row['$route'] = lot['route']
                row['$step'] = op['step']
    if variant != 'per_row':
        result['lot_information'] = [lot_table[k] for k in sorted(lot_table)]
    return result, expected


def check_field_roundtrip(decoded, expected, variant, manifest):
    lots = {r['lot_id']: r for r in decoded.get('lot_information', [])}
    templates = {r['reference']: r for r in decoded.get('processing_templates', [])}
    got = {}
    for row in decoded['unreserved_ready']:
        values = dict(row)
        if variant != 'per_row':
            values.update(lots[row['$lot']])
        if variant == 'route_reference':
            step = manifest['routes'][row['$route']][row['$step']-1]
            lo, _, hi = distribution_bounds(step['processing'])
            group = [m for m in manifest['machines'] if m['id'] in row['eligible_machines']]
            values.update(processing_seconds_min=lo+min(m['load']+m['unload'] for m in group),
                          processing_seconds_max=None if hi is None else hi+max(m['load']+m['unload'] for m in group))
        got[row['operation_id']] = normalize({k: values[k] for k in expected[row['operation_id']]})
    assert got == normalize(expected)


def job_additions(record, manifest, dispatches):
    if 'running_jobs' not in record:
        return None
    now = record['problem']['time']; events = {e['job']: e for e in dispatches if e['kind'] == 'dispatch' and e['time'] <= now}
    lots = {l['id']: l for l in manifest['lots']}; machines = family_table(manifest); result = []
    for job in record['running_jobs']:
        e = events.get(job['job']); row = dict(job)
        if not e:
            row.update(current_steps=None, current_visits=None, earliest_finish=None, latest_finish=None, intrinsic_latest_finish=None)
        else:
            route = manifest['routes'][lots[job['lot_ids'][0]]['route']]
            mid = job['machine']; fixed_machine = {k: [m for m in v if m['id'] == mid] for k,v in machines.items()}
            lo, _, hi = phase_duration(route, e['steps'][0]-1, fixed_machine)
            # Known setup and elapsed observed pauses may tighten lower bound.
            # For a conservative reproducible support omit all downtime/setup.
            row.update(current_steps=e['steps'], current_visits=e['visits'],
                       earliest_finish=max(now, job['started_at'] + lo), latest_finish=None,
                       intrinsic_latest_finish=None if hi is None else job['started_at'] + e['setup_seconds'] + hi)
        result.append(row)
    return result


def field_costs(states, manifest, bundle, counter):
    from harness_v6.mcp_server import TOOLS, TOOL_DESCRIPTIONS
    tools = [dict(name=n, description=TOOL_DESCRIPTIONS[n], inputSchema=s) for n,s in TOOLS.items()]
    prefixes = {fmt: stable_prefix(tool_descriptions=tools, routing=manifest['routes'], machine_groups=manifest['machines'], snapshot_format=fmt, token_counter=counter) for fmt in ('explicit','dense')}
    output = {}
    for name, record in states.items():
        if name == 'SMT2020:0':
            continue
        current = get_current(record); result = {}
        for fmt, prefix in prefixes.items():
            pobj = decode_prefix(prefix)
            baseline = encode_current(pobj, current, snapshot_format=fmt, token_counter=counter)
            base = counter(baseline.decode()); static = counter(prefix.decode())
            row = dict(current_tokens=base, prefix_tokens=static, uncached_equivalent=base+.1*static, additions={})
            for variant in ('per_row','per_lot','route_reference'):
                payload, expected = field_payload(current, record, manifest, variant)
                wire = encode_current(pobj, payload, snapshot_format=fmt, token_counter=counter)
                _, decoded = decode_snapshot(prefix + wire)
                check_field_roundtrip(decoded, expected, variant, dict(routes=pobj['routing'], machines=pobj['machine_groups']))
                delta = counter(wire.decode()) - base
                row['additions'][variant] = dict(current_delta=delta, equivalent_delta=delta, roundtrip=True)
            full, expected = field_payload(current, record, manifest, 'per_row')
            for label, keys in [('due', ('due',)), ('priority', ('priority',)),
                                ('waiting_since', ('waiting_since',)),
                                ('processing_min_max', ('processing_seconds_min', 'processing_seconds_max'))]:
                payload = deepcopy(current)
                for ready_row in payload['unreserved_ready']:
                    ready_row.update({k: expected[ready_row['operation_id']][k] for k in keys})
                wire = encode_current(pobj, payload, snapshot_format=fmt, token_counter=counter)
                _, decoded = decode_snapshot(prefix + wire)
                assert decoded == normalize(payload)
                delta = counter(wire.decode()) - base
                row['additions']['only_' + label] = dict(current_delta=delta, equivalent_delta=delta, roundtrip=True)
            jobs = job_additions(record, manifest, bundle['g0_trace'])
            if jobs is None:
                row['additions']['running_jobs'] = None
            else:
                wire = encode_current(pobj, dict(current, running_jobs=jobs), snapshot_format=fmt, token_counter=counter)
                _, decoded = decode_snapshot(prefix + wire)
                assert decoded['running_jobs'] == normalize(jobs)
                delta = counter(wire.decode())-base
                row['additions']['running_jobs'] = dict(current_delta=delta, equivalent_delta=delta,
                    known_step_jobs=sum(j['current_steps'] is not None for j in jobs), jobs=len(jobs), roundtrip=True)
            writer = section if fmt == 'explicit' else lambda n,v: dense_section(n,v,counter)
            extra = writer('setup_transitions', record['problem']['setup_transitions']) + writer('min_runs', record['problem']['min_runs'])
            assert sections(extra) == normalize(dict(setup_transitions=record['problem']['setup_transitions'], min_runs=record['problem']['min_runs']))
            delta = counter(prefix.decode()+extra) - static
            row['additions']['setup_transitions_min_runs'] = dict(prefix_delta=delta,equivalent_delta=.1*delta)
            result[fmt] = row
        output[name] = result
    return output


def run(args):
    states, env = load_states(args.fixture, args.database, args.public_ledger)
    bundle = json.loads(Path(args.fixture).read_bytes()); manifest = env.manifest; counter = tiktoken_counter()
    distributions = {key: dict(Counter(s[key]['type'] for r in manifest['routes'].values() for s in r)) for key in ('processing','transport','cadence')}
    distributions['nonpositive_processing_minima'] = sum(distribution_bounds(s['processing'])[0] <= 0 for r in manifest['routes'].values() for s in r)
    distributions['virtual_processing'] = dict(Counter(s['processing']['type'] for r in manifest['routes'].values() for s in r if all(m['group']=='Delay_32' for m in family_table(manifest)[s['family']])))
    distributions['load_unload_extrema'] = {k:[min(m[k] for m in manifest['machines']),max(m[k] for m in manifest['machines'])] for k in ('load','unload')}
    result = dict(generated_at=datetime.now(timezone.utc).isoformat(), distributions=distributions, qualification_probe=qualification_probe(env,states['SMT2020:0']), states={})
    for name, record in states.items():
        print('measuring',name,flush=True)
        rows, bounds, lots, sources = window_rows(record, manifest, private_lots=env.lots if name=='SMT2020:0' else None, dispatches=bundle['g0_trace'] if name.startswith('G0') else ())
        current = get_current(record); exported = {o['operation_id'] for o in record['problem']['operations']}
        beyond_h = {o['operation_id'] for o in record['problem']['operations'] if o.get('readiness_basis')=='executing_predecessor' and o['release_time']>record['problem']['time']+900}
        windows=[]
        weak_rows = window_rows(record,manifest,weak_start=True)[0] if name.startswith('G0') else rows
        for w in WINDOWS:
            selected=[r for r in rows if r['earliest_start']<=record['problem']['time']+w]; ids={r['operation_id'] for r in selected}
            tokens=wire_cost(selected,manifest,counter)
            windows.append(dict(window=w,operations=len(selected),basis=dict(Counter(r['readiness_basis'] for r in selected)),depth_distribution=depth_distribution(selected,lots),
                beyond_export=len(ids-exported),executing_beyond_h_shown=len(ids & beyond_h),tokens=tokens,
                delta_vs_g0_upcoming={f:tokens[f]-b for f,b in [('explicit',3536),('dense',2919)]},
                weak_now_operations=sum(r['earliest_start']<=record['problem']['time']+w for r in weak_rows)))
        result['states'][name]=dict(time=record['problem']['time'],sequence=record.get('seq'),sources=sources,windows=windows)
        if name=='SMT2020:0':
            result['validity']=validate_forward(record,manifest,bundle,bounds,rows)
            if result['validity']['violations']:
                result['stopped_on_bound_violation']=True
                return result
    result['field_costs']=field_costs(states,manifest,bundle,counter)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('fixture','database','public-ledger','output'):
        parser.add_argument('--'+key,required=True)
    args=parser.parse_args(); result=run(args)
    Path(args.output).write_bytes(canonical(result)+b'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='validity'},ensure_ascii=False,sort_keys=True,indent=2))
    if 'validity' in result:
        print(json.dumps({k:v for k,v in result['validity'].items() if k not in ('physical_starts','virtual_starts')},sort_keys=True,indent=2))
    if result.get('stopped_on_bound_violation'):
        raise SystemExit(2)
