"""Read-only, standard-library audit of the locked full-fab sources.

This module does not import the simulator, run a policy or update old manifests.
The report distinguishes source integrity from official numerical calibration.
"""
from __future__ import annotations
import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
DATE_FORMAT = '%m/%d/%y %H:%M:%S'
EXPECTED = {'production_groups': 11, 'production_families': 105,
            'production_machines': 913, 'virtual_families': 1,
            'virtual_resources': 400, 'routes': 10, 'route_steps': 4013,
            'initial_lots': 2156, 'pieces_per_lot': [25], 'release_streams': 21}


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def rows(path, encoding='utf-8'):
    with Path(path).open(encoding=encoding, newline='') as f:
        return [r for r in csv.DictReader(f, delimiter='\t') if any(r.values())]


def verify_hashes(base, expected):
    checks = []
    for name, value in sorted(expected.items()):
        target = Path(base) / name
        actual = sha256(target) if target.is_file() else None
        checks.append({'file': name, 'expected': value, 'actual': actual,
                       'ok': actual == value})
    return checks


def release_counts(streams, horizons):
    origin = min(datetime.strptime(r['START'], DATE_FORMAT) for r in streams)
    answer = {}
    for horizon in horizons:
        count = 0
        for r in streams:
            start = (datetime.strptime(r['START'], DATE_FORMAT) - origin).total_seconds()
            interval = float(r['REPEAT']) * {'min': 60, 'hr': 3600, 'day': 86400}[r['RUNITS']]
            count += max(0, min(int(r['RPT#']), math.ceil((horizon - start) / interval))) * int(r['LOTSPERRPT'])
        answer[str(horizon)] = count
    return answer


def audit_source(root=ROOT):
    root = Path(root)
    locked = json.loads((root / 'data/smt/source-manifest.json').read_text())
    normalized = root / 'data/smt/SMT2020_LVHM'
    raw = root / 'data/raw/smt'
    official = raw / 'official_dataset2'
    archive_checks = verify_hashes(raw, {n: v['sha256'] for n, v in locked['archives'].items()})
    input_checks = verify_hashes(normalized, locked['normalized_inputs'])
    vendor_checks = verify_hashes(root / 'vendor/PySCFabSim-revised', locked['vendor_files'])
    for check in archive_checks:
        check['size_ok'] = (raw / check['file']).stat().st_size == locked['archives'][check['file']]['size'] if check['actual'] else False
    tool = rows(normalized / 'tool.txt.1l')
    production = [r for r in tool if r['STNGRP'] != 'Delay_32']
    virtual = [r for r in tool if r['STNGRP'] == 'Delay_32']
    routes = {p.name: rows(p) for p in sorted(normalized.glob('route_*.txt'))}
    steps = [r for rs in routes.values() for r in rs]
    wip = rows(normalized / 'WIP.txt')
    streams = rows(normalized / 'order.txt')
    counts = {'production_groups': len({r['STNGRP'] for r in production}),
              'production_families': len(production), 'production_machines': sum(int(r['STNQTY']) for r in production),
              'virtual_families': len(virtual), 'virtual_resources': sum(int(r['STNQTY']) for r in virtual),
              'routes': len(routes), 'route_steps': len(steps), 'initial_lots': len(wip),
              'pieces_per_lot': sorted({int(r['PIECES']) for r in wip + streams}), 'release_streams': len(streams)}
    origins = {p['PART']: p['ROUTEFILE'] for p in rows(normalized / 'part.txt')}
    unresolved = []
    unresolved_cqt = []
    for lot in wip:
        cur = int(lot['CURSTEP'])
        prior = [{'start': int(r['STEP']), 'target': int(r['FORSTEP'])} for r in routes[origins[lot['PART']]]
                 if r['SVESTN'] == 'yes' and int(r['STEP']) < cur <= int(r['FORSTEP'])]
        if prior:
            unresolved.append({'lot': lot['LOT'], 'current_step': cur, 'historical_bindings_required': prior})
        segments = [{'start': int(r['STEP']), 'target': int(r['STEP_CQT'])}
                    for r in routes[origins[lot['PART']]]
                    if r['STEP_CQT'] and int(r['STEP']) < cur <= int(r['STEP_CQT'])]
        if segments:
            unresolved_cqt.append({'lot':lot['LOT'],'current_step':cur,'unknown_cqt_start_times':segments})
    seconds = {'sec':1,'min':60,'hr':3600,'day':86400}
    loading = {r['STNFAM']:(float(r['LTIME'])*seconds[r['LTUNITS']]+float(r['ULTIME'])*seconds[r['ULTUNITS']]) for r in tool}
    cascade = defaultdict(list)
    for step in steps:
        if step['BatchInterval']:
            upper=(float(step['PTIME'])+float(step['PTIME2'] or 0))*seconds[step['PTUNITS']]
            cadence=float(step['BatchInterval'])*seconds[step['BatchIntUnits']]
            cascade[step['STNFAM']].append((upper+loading[step['STNFAM']]-cadence,cadence))
    cascade_bounds = {family:{'maximum_slot2_seconds':max(p[0] for p in values),
                     'minimum_next_cadence_seconds':min(p[1] for p in values),
                     'slot2_blocking_not_required_by_processing_bounds':max(p[0] for p in values)<=min(p[1] for p in values)+1e-8}
                     for family,values in cascade.items()}
    horizons = [3600, 28800, 86400, 7*86400, 14*86400, 28*86400, 365*86400, 1460*86400]
    periodic_counts = release_counts(streams, horizons)
    origin = min(datetime.strptime(r['START'], DATE_FORMAT) for r in streams)
    stream_by_order = {r['ORDER']:r for r in streams}
    explicit = {}
    for filename in ['order_high_SL_92PCTL.txt', 'order_medium_SL_50PCTL.txt', 'order_low_SL_25PCTL.txt']:
        rs = rows(official / filename, 'utf-16')
        starts = [(datetime.strptime(r['START'], DATE_FORMAT)-origin).total_seconds() for r in rs]
        lead = [(datetime.strptime(r['DUE'], DATE_FORMAT)-datetime.strptime(r['START'], DATE_FORMAT)).total_seconds()/86400 for r in rs]
        byorder = defaultdict(list)
        for r in rs:
            byorder[r['ORDER']].append((datetime.strptime(r['DUE'], DATE_FORMAT)-datetime.strptime(r['START'], DATE_FORMAT)).total_seconds())
        indices=Counter(); lead_ratios=[]; release_deltas=[]
        for r in rs:
            base=stream_by_order[r['ORDER']]
            index=indices[r['ORDER']]; indices[r['ORDER']]+=1
            actual=(datetime.strptime(r['START'],DATE_FORMAT)-datetime.strptime(base['START'],DATE_FORMAT)).total_seconds()
            release_deltas.append(actual-index*float(base['REPEAT'])*60)
            lead_ratios.append((datetime.strptime(r['DUE'],DATE_FORMAT)-datetime.strptime(r['START'],DATE_FORMAT)).total_seconds()/
                               (datetime.strptime(base['DUE'],DATE_FORMAT)-datetime.strptime(base['START'],DATE_FORMAT)).total_seconds())
        explicit[filename] = {'sha256': sha256(official/filename), 'nonempty_lots': len(rs),
            'order_identities': len(byorder), 'priority_counts': dict(Counter(r['PRIOR'] for r in rs)),
            'hotlot_counts': dict(Counter(r.get('HOTLOT','') for r in rs)),
            'release_counts_half_open': {str(h): sum(0<=v<h for v in starts) for h in horizons},
            'due_lead_days_min_max': [min(lead),max(lead)],
            'distinct_due_leads_per_order': {k:len(set(v)) for k,v in byorder.items()},
            'release_time_difference_seconds_vs_periodic_min_max':[min(release_deltas),max(release_deltas)],
            'due_lead_ratio_vs_periodic_min_max':[min(lead_ratios),max(lead_ratios)],
            'first_lot': rs[0], 'last_lot': rs[-1]}
    options = (official / 'options.def').read_text(encoding='utf-16')
    section = options[options.index('ORDER_FILES'): options.index('PMORDER_FILES')]
    reference_reports = {}
    evidence = {}
    with zipfile.ZipFile(raw / 'SMT2020.zip') as z:
        prefix = 'SMT_2020 - Final/AutoSched/dataset 2/LVHM_Model/'
        for suffix in ['perf.rep','part.rep','order.rep','stngrp.rep','LVHM_Model.output','LVHM_Model.warning','options.sav']:
            name = prefix+suffix
            data = z.read(name)
            text = data.decode('utf-16')
            item = {'archive_member': name,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
            if suffix.endswith('.rep'):
                lines=[line for line in text.splitlines() if line and not line.startswith('~')]
                item['rows']=list(csv.DictReader(io.StringIO('\n'.join(lines)),delimiter='\t'))
            if suffix=='LVHM_Model.output':
                item['first_line']=text.splitlines()[0]
                item['relevant_lines']=[line for line in text.splitlines() if any(x in line for x in ['ORDER file','DAY 1460','Simulation Complete','seed','Seed'])]
            if suffix=='options.sav':
                item['order_files_section']=text[text.index('ORDER_FILES'):text.index('PMORDER_FILES')]
            reference_reports[suffix]=item
        conversions=json.loads((root/'data/smt/conversion-manifest.json').read_text())
        conversion_checks=[]
        for c in conversions:
            source_data=z.read(c['source'])
            disk=official/Path(c['source']).name
            conversion_checks.append({'file':str(disk.relative_to(root)),
               'archive_sha256':hashlib.sha256(source_data).hexdigest(),
               'raw_matches_archive':disk.read_bytes()==source_data,
               'source_hash_matches_manifest':hashlib.sha256(source_data).hexdigest()==c['source_sha256'],
               'normalized_hash_matches_manifest':sha256(root/c['output'])==c['output_sha256']})
    relevant_files = {'official_options':official/'options.def','official_periods':official/'period.txt',
       'official_runcontrol':official/'runcntrl.def','upstream_runner':root/'vendor/PySCFabSim-revised/simulation/greedy.py',
       'upstream_dispatcher':root/'vendor/PySCFabSim-revised/simulation/dispatching/dispatcher.py',
       'upstream_kernel':root/'vendor/PySCFabSim-revised/simulation/instance.py'}
    for k,p in relevant_files.items():
        encoding='utf-16' if k.startswith('official_') else 'utf-8'
        text=p.read_text(encoding=encoding)
        terms=['ORDER_FILES','order_','snaplen','WarmUp','Period_','a.dataset =','a.dispatcher =','a.seed =','seed = random','a.days =','ResetEvent','CQT handling','cr_ptuple','get_setup','-lot.priority']
        evidence[k]={'file':str(p.relative_to(root)),'sha256':sha256(p),
            'lines':[{'line':i,'text':line} for i,line in enumerate(text.splitlines(),1) if any(t in line for t in terms)]}
    checks_ok = (all(x['ok'] for x in archive_checks+input_checks+vendor_checks)
                 and all(x['size_ok'] for x in archive_checks)
                 and counts == EXPECTED
                 and all(x['raw_matches_archive'] and x['source_hash_matches_manifest'] and x['normalized_hash_matches_manifest'] for x in conversion_checks))
    return {'schema_version':'smt-fullfab-source-audit-v1','source_integrity_passed':checks_ok,
        'official_calibration_passed':False,'counts':counts,'expected_counts':EXPECTED,
        'archive_checks':archive_checks,'normalized_input_checks':input_checks,'vendor_checks':vendor_checks,
        'conversion_checks':conversion_checks,'production_group_names':sorted({r['STNGRP'] for r in production}),
        'semantics':{'cqt_segments':sum(bool(r['STEP_CQT']) for r in steps),
            'dedication_rules':sum(r['SVESTN']=='yes' for r in steps),
            'initial_lots_with_missing_historical_bindings':len(unresolved),
            'missing_historical_bindings':unresolved,
            'initial_lots_with_unknown_cqt_history':len(unresolved_cqt),
            'unknown_initial_cqt_history':unresolved_cqt,
            'lot_cascading_domain_checks':cascade_bounds,
            'lot_cascading_steps':sum(bool(r['BatchInterval']) for r in steps),
            'wafer_cascading_steps':sum(bool(r['PartInterval']) for r in steps),
            'tool_rules':dict(Counter(r['RULE'] for r in tool)),
            'tool_rankings':dict(Counter(r['FWLRANK'] for r in tool)),
            'periodic_hotlot_counts':dict(Counter(r['HOTLOT'] for r in streams))},
        'releases':{'horizon_seconds_half_open':horizons,'periodic_21_stream_counts':periodic_counts,'explicit_orders':explicit},
        'official_options_order_section':section,'evidence':evidence,'reference_reports':reference_reports,
        'calibration_blockers':[
            'Official options selects an explicit high-service-level lot file; experiment uses 21 periodic streams with fixed lead times.',
            'Archived reports carry a saved options filename differing from packaged options; exact report input and seed provenance unresolved.',
            'Pinned upstream runner overrides requested dataset, dispatcher and seed after parsing arguments.',
            'Official HP then setup then CR differs from pinned upstream setup then HP then CR; batch ranking also differs.',
            'No full matched AutoSched or upstream long-horizon run and uncertainty-based tolerance has been completed.',
            'CQT monitoring/enforcement and true wafer-level cascading equivalence are not established by adapter-v2.',
            'Initial historical bindings and machine/processing state are absent from WIP source; cold-start is not a recovered production snapshot.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    report=audit_source(args.root)
    data=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(data)
    print(json.dumps({'source_integrity_passed':report['source_integrity_passed'],
        'official_calibration_passed':False,'counts':report['counts'],
        'missing_historical_binding_lots':report['semantics']['initial_lots_with_missing_historical_bindings'],
        'output':str(args.output) if args.output else None},ensure_ascii=False))
    if not report['source_integrity_passed']:
        raise SystemExit(1)

if __name__=='__main__':
    main()
