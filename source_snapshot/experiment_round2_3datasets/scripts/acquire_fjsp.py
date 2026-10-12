#!/usr/bin/env python3
"""Acquire and audit exact public source files. No solver/model is called."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
SOURCES = {
    'fjsp-instances': {'repo': 'SchedulingLab/fjsp-instances', 'commit': 'ac4c3402312bfbeafcf4472d78be567d4e6b46ab', 'license': 'MIT'},
    'scheduleopt': {'repo': 'ScheduleOpt/benchmarks', 'commit': 'f89e5b007c90a1c1a70fa48a28d657a72da05665', 'license': 'CC-BY-SA-4.0'},
}
BRANDIMARTE = {'development': ['mk01', 'mk02', 'mk10'], 'formal': ['mk03', 'mk05', 'mk08'], 'reserve': ['mk04', 'mk06', 'mk09']}
HURINK = {'development': ['la01', 'ft06'], 'formal': ['la02', 'la06', 'la11'], 'reserve': ['la03', 'la07', 'la12']}
VARIANTS = ['edata', 'rdata', 'vdata']


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def selected():
    for split, ids in BRANDIMARTE.items():
        for i in ids:
            yield {'instance_id': i, 'family': 'brandimarte', 'base_instance': i, 'split': split, 'sl_path': f'brandimarte/{i}.txt', 'so_path': f'flexible-jobshop/instances/fjsp/Brandimarte1993/{i}.txt'}
    for split, ids in HURINK.items():
        for i in ids:
            for v in VARIANTS:
                yield {'instance_id': f'{i}_{v}', 'family': 'hurink', 'base_instance': i, 'variant': v, 'split': split, 'sl_path': f'hurink/{v}/{"mt06" if i == "ft06" else i}.txt', 'so_path': f'flexible-jobshop/instances/fjsp/HurinkJurischThole1994/{v}/{i}.txt'}


def download(proxy):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({'https': proxy, 'http': proxy}) if proxy else urllib.request.ProxyHandler({}))
    jobs = []
    for name, s in SOURCES.items():
        dest = ROOT / 'vendor' / name
        dest.mkdir(parents=True, exist_ok=True)
        tree_file = dest / 'tree.json'
        if not tree_file.exists():
            url = f'https://api.github.com/repos/{s["repo"]}/git/trees/{s["commit"]}?recursive=1'
            with opener.open(url, timeout=60) as response:
                tree_file.write_bytes(response.read())
        tree = json.loads(tree_file.read_text())
        if tree['sha'] != s['commit'] or tree.get('truncated'):
            raise ValueError('Wrong or truncated repository tree')
        blobs = {x['path']: x['sha'] for x in tree['tree'] if x['type'] == 'blob'}
        paths = {'README.md', 'LICENSE'}
        if name == 'fjsp-instances':
            paths.add('instances.json')
            for i in selected():
                paths.update([i['sl_path'], i['sl_path'].replace('.txt', '.json')])
        else:
            paths.update(['flexible-jobshop/README.md', 'flexible-jobshop/solutions/bks.json'])
            for i in selected():
                paths.update([i['so_path'], f'flexible-jobshop/instances/json/{i["instance_id"]}.json'])
        for path in sorted(paths):
            jobs.append((name, path, blobs[path]))

    def fetch(job):
        name, path, blob = job
        s = SOURCES[name]
        dest = ROOT / 'vendor' / name / path
        url = f'https://raw.githubusercontent.com/{s["repo"]}/{s["commit"]}/{path}'
        if dest.exists():
            raw = dest.read_bytes()
        else:
            with opener.open(url, timeout=60) as response:
                raw = response.read()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
        actual = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        if actual != blob:
            raise ValueError(f'Git blob mismatch: {dest}')
        return {'source': name, 'path': path, 'local_path': str(dest.relative_to(ROOT)), 'url': url, 'git_blob_sha1': blob, 'sha256': sha256(raw), 'bytes': len(raw)}

    with ThreadPoolExecutor(max_workers=4) as pool:
        entries = list(pool.map(fetch, jobs))
    manifest = {'schema_version': 'fjsp-source-lock-1', 'downloaded_at_utc': datetime.now(timezone.utc).isoformat(), 'sources': SOURCES, 'files': entries}
    destination = ROOT / 'data/fjsp/source-lock.json'
    if destination.exists():
        existing = json.loads(destination.read_text())
        if existing['sources'] != SOURCES or existing['files'] != entries:
            raise ValueError('Source lock changed; preserve old lock and create explicit new version')
    else:
        destination.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'downloaded_or_verified_files': len(entries), 'source_commits': {n: s['commit'] for n, s in SOURCES.items()}}))



def _canonical(problem):
    return [[sorted((a['machine'], a['duration']) for a in op['alternatives']) for op in job['operations']] for job in problem['jobs']]


def _crosscheck(problem, selection):
    """Separate source representations, including complete chain edges."""
    canonical = _canonical(problem)
    sl_json = json.loads((ROOT / 'vendor/fjsp-instances' / selection['sl_path'].replace('.txt', '.json')).read_text())
    sl_canonical = [[sorted((a['machine'], a['processing']) for a in op) for op in job] for job in sl_json['jobs']]
    if sl_json['machines'] != len(problem['machines']) or sl_canonical != canonical:
        raise ValueError(f"SchedulingLab JSON differs: {selection['instance_id']}")
    so_json = json.loads((ROOT / 'vendor/scheduleopt/flexible-jobshop/instances/json' / (selection['instance_id'] + '.json')).read_text())
    expected_options = []
    expected_precedences = []
    global_id = 0
    for j, job in enumerate(canonical):
        for k, alternatives in enumerate(job):
            expected_options.extend((global_id, m, d) for m, d in alternatives)
            if k:
                expected_precedences.append((global_id - 1, global_id, j))
            global_id += 1
    actual_options = [(o['operation'], o['machine'], o['duration']) for o in so_json['operations']]
    actual_precedences = [(e['before'], e['after'], e['job']) for e in so_json['precedences']]
    if sorted(actual_options) != sorted(expected_options) or sorted(actual_precedences) != sorted(expected_precedences):
        raise ValueError(f"ScheduleOpt JSON differs: {selection['instance_id']}")
    rows = [r.split() for r in (ROOT / 'vendor/scheduleopt' / selection['so_path']).read_text().splitlines() if r.strip()]
    so_jobs, so_machines = map(int, rows[0][:2])
    if so_jobs != len(canonical) or len(rows) != len(canonical) + 1:
        raise ValueError('ScheduleOpt text job dimensions differ')
    if so_machines != len(problem['machines']):
        if not (selection['instance_id'] == 'mk06' and so_machines == 15 and len(problem['machines']) == 10):
            raise ValueError('Unexpected machine dimension difference')
    for j, row in enumerate(rows[1:]):
        nums = list(map(int, row))
        if nums[0] != len(canonical[j]):
            raise ValueError('ScheduleOpt text operation count differs')
        pos = 1
        parsed = []
        for _ in range(nums[0]):
            count = nums[pos]
            pos += 1
            parsed.append(sorted((nums[pos + 2*t] - 1, nums[pos + 2*t + 1]) for t in range(count)))
            pos += count * 2
        if pos != len(nums) or parsed != canonical[j]:
            raise ValueError(f"ScheduleOpt one-based text differs: {selection['instance_id']}")
    return {'schedulinglab_text_vs_json': True, 'scheduleopt_json_options_and_precedences': True, 'scheduleopt_one_based_text': True, 'schedulinglab_declared_machines': len(problem['machines']), 'scheduleopt_text_declared_machines': so_machines, 'declared_machine_count_matches': so_machines == len(problem['machines']), 'difference_note': None if so_machines == len(problem['machines']) else 'mk06: five extra declared machines have no eligible operations; all options and precedences match exactly'}


def _save_or_check(path, data, verify_only=False):
    raw = (json.dumps(data, indent=2, ensure_ascii=False) + '\n').encode()
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError(f'Existing output differs; do not overwrite frozen data: {path}')
    elif verify_only:
        raise FileNotFoundError(path)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return sha256(raw)


def prepare(verify_only=False):
    from fjsp.problem import parse_fjs
    lock = json.loads((ROOT / 'data/fjsp/source-lock.json').read_text())
    for item in lock['files']:
        if sha256((ROOT / item['local_path']).read_bytes()) != item['sha256']:
            raise ValueError(f"Source checksum mismatch: {item['local_path']}")
    sl_references = {r['path']: r for r in json.loads((ROOT / 'vendor/fjsp-instances/instances.json').read_text())}
    so_references = {r['instance']: r for r in json.loads((ROOT / 'vendor/scheduleopt/flexible-jobshop/solutions/bks.json').read_text())}
    records, references = [], []
    splits = {split: {'brandimarte': [], 'hurink': []} for split in BRANDIMARTE}
    for selection in selected():
        identifier = selection['instance_id']
        raw_path = ROOT / 'vendor/fjsp-instances' / selection['sl_path']
        problem = parse_fjs(raw_path, identifier, selection['family'])
        problem['base_instance'] = selection['base_instance']
        if 'variant' in selection:
            problem['variant'] = selection['variant']
        cross = _crosscheck(problem, selection)
        path = Path('data/fjsp/instances') / (identifier + '.json')
        checksum = _save_or_check(ROOT / path, problem, verify_only)
        operations = [op for job in problem['jobs'] for op in job['operations']]
        n_alts = sum(len(op['alternatives']) for op in operations)
        records.append({**selection, 'normalized_path': str(path), 'normalized_sha256': checksum,
            'raw_sha256': problem['source']['sha256'], 'jobs': len(problem['jobs']), 'machines': len(problem['machines']),
            'operations': len(operations), 'alternatives': n_alts, 'mean_alternatives': n_alts / len(operations),
            'machine_independent_durations': all(len({a['duration'] for a in op['alternatives']}) == 1 for op in operations),
            'crosscheck': cross})
        splits[selection['split']][selection['family']].append(identifier)
        sl, so = sl_references[selection['sl_path']], so_references[identifier]
        lb, ub = so.get('lower_bound'), so.get('upper_bound')
        reported_optimal = lb if lb is not None and lb == ub else None
        references.append({'instance_id': identifier, 'family': selection['family'], 'variant': selection.get('variant'),
            'base_instance': selection['base_instance'], 'independently_verified_optimum': None,
            'reported_optimum': reported_optimal,
            'reference_status': 'reported_optimal_unverified' if reported_optimal is not None else ('bks_and_lower_bound' if ub is not None and lb is not None else 'unknown'),
            'best_known_feasible_value_reported': ub, 'lower_bound_reported': lb,
            'proof_independently_checked': False, 'feasible_certificate_independently_checked': False,
            'chosen_source': 'scheduleopt', 'chosen_source_commit': SOURCES['scheduleopt']['commit'],
            'chosen_source_record': so, 'schedulinglab_record': sl,
            'comparison': {'schedulinglab_optimum': sl.get('optimum'),
                'schedulinglab_lower': sl.get('optimum') if sl.get('optimum') is not None else sl.get('bounds', {}).get('lower'),
                'schedulinglab_upper': sl.get('optimum') if sl.get('optimum') is not None else sl.get('bounds', {}).get('upper')},
            'caution': 'A maintenance-table claim, not an independently checked proof or schedule. Runtime agents must not read this file.'})
    _save_or_check(ROOT / 'data/fjsp/split.json', {'schema_version': 'fjsp-split-1', 'basis': 'preselected before any solver/model runs; Hurink grouped by base instance', 'splits': splits, 'hurink_base_splits': HURINK}, verify_only)
    _save_or_check(ROOT / 'data/fjsp/manifest.json', {'schema_version': 'fjsp-manifest-1', 'instances': records}, verify_only)
    _save_or_check(ROOT / 'docs/fjsp-reference-values.json', {'schema_version': 'fjsp-references-1', 'as_of_date': '2026-10-09', 'scope': 'offline evaluator only; never model input', 'references': references}, verify_only)
    print(json.dumps({'verified_source_files': len(lock['files']), 'crosschecked_instances': len(records), 'instance_counts': {split: {family: len(ids) for family, ids in families.items()} for split, families in splits.items()}, 'reference_status_counts': {status: sum(r['reference_status'] == status for r in references) for status in sorted({r['reference_status'] for r in references})}}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--download', action='store_true')
    p.add_argument('--proxy', default='http://127.0.0.1:7897')
    p.add_argument('--prepare', action='store_true')
    p.add_argument('--verify', action='store_true')
    args = p.parse_args()
    if args.download:
        download(args.proxy)
    if args.prepare or args.verify:
        prepare(verify_only=args.verify and not args.prepare)


if __name__ == '__main__':
    main()
