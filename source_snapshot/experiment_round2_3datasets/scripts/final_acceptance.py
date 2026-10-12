#!/usr/bin/env python3
"""Fail-closed gate over SAVED audits/reports; never replays, simulates or solves.

--prepare-index only inventories bytes. It is NOT a certification or a signoff.
See docs/final-acceptance-gate.md for the attestation and execution order.
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ['mk03', 'mk05', 'mk08'] + [f'la{n:02d}_{v}' for n in (2, 6, 11) for v in ('edata', 'rdata', 'vdata')]
PHASES = {
    'acceptance_static_v1': ('static-v1', False, False, 108),
    'auxiliary_static_v1': ('static-aux-v2', False, True, 36),
    'acceptance_smt_v1': ('smt-v1', True, False, 27),
    'auxiliary_smt_v1': ('smt-aux-v1', True, True, 9),
}
SIGNOFFS = ('full_offline_replay', 'raw_evidence_inventory', 'freeze_git_history',
            'historical_inputs_unchanged', 'report_integrity', 'visual_qa',
            'readme_reproduction', 'budget_integrity')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read(path):
    def bad_constant(value):
        raise ValueError('Nonfinite JSON constant: ' + value)
    return json.loads(Path(path).read_text(encoding='utf-8'), parse_constant=bad_constant)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def object_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def safe(root, relative):
    p = Path(relative)
    if p.is_absolute() or '..' in p.parts:
        raise ValueError('Expected experiment-relative path: ' + str(relative))
    resolved = (root / p).resolve()
    if root.resolve() not in resolved.parents:
        raise ValueError('Path escapes experiment: ' + str(relative))
    return resolved


def link(root, relative):
    return {'path': str(relative), 'sha256': sha(safe(root, relative))}


def timestamp(value):
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('Timestamp must include timezone')
    return parsed


def expected_matrix(smt, auxiliary):
    return {(item, arm, repeat) for item in ((801, 802, 803) if smt else STATIC)
            for arm in (('F',) if auxiliary else ('A', 'B', 'C')) for repeat in (1, 2, 3)}


def run_name(item, arm, repeat, smt):
    return f'{"smt" if smt else ""}{item}_{arm}_r{repeat}'


def unique(rows, key='run_id'):
    if not isinstance(rows, list):
        raise ValueError('Expected list of rows')
    result = {}
    for row in rows:
        ident = row[key]
        if ident in result:
            raise ValueError('Duplicate evidence identity: ' + str(ident))
        result[ident] = row
    return result


def equal(a, b):
    if type(a) in (int, float) and type(b) in (int, float):
        return math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6)
    return type(a) is type(b) and a == b


def cast(value):
    if value in ('', None):
        return None
    if value in ('True', 'False'):
        return value == 'True'
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


def csv_rows(path):
    with path.open(newline='', encoding='utf-8') as handle:
        return [{k: cast(v) for k, v in row.items()} for row in csv.DictReader(handle)]


def prepare_index(root, label='final', recovery_freeze=None, recovery_audit=None):
    """Collect only existing files. Raises on missing files; does not certify them."""
    result = {'schema_version': 'final-evidence-1', 'prepared_at': now(),
              'preparation_is_certification': False, 'phases': {},
              'original_results_sha256': {}, 'recovery': None}
    for phase, (freeze_name, smt, auxiliary, _) in PHASES.items():
        folder = f'artifacts/{phase}'
        freeze_ref = link(root, f'configs/freezes/{freeze_name}.json')
        freeze = read(safe(root, freeze_ref['path']))
        for item, arm, repeat in freeze['matrix']:
            path = f'runs/{phase}/{run_name(item, arm, repeat, smt)}/result.json'
            if path in result['original_results_sha256']:
                raise ValueError('Duplicate original result path')
            result['original_results_sha256'][path] = sha(safe(root, path))
        result['phases'][phase] = {
            'freeze': freeze_ref,
            'replay': link(root, f'{folder}/{"smt_" if smt else ""}replay_{label}.json'),
            'report_audit': link(root, f'{folder}/{"smt_" if smt else ""}report_evidence_audit.json'),
            'summary': link(root, f'{folder}/{"smt_" if smt else ""}summary.json'),
            'results_csv': link(root, f'{folder}/{"smt_" if smt else ""}results.csv'),
            'replay_source': link(root, f'src/{"smt_" if smt else ""}replay.py'),
            'report_source': link(root, f'src/{"smt_" if smt else ""}report.py'),
        }
        if smt:
            result['phases'][phase]['provenance'] = link(root, f'{folder}/smt_provenance.json')
    if bool(recovery_freeze) != bool(recovery_audit):
        raise ValueError('Supply both recovery freeze and saved recovery audit')
    if recovery_freeze:
        freeze = read(safe(root, recovery_freeze))
        manifest = read(safe(root, freeze['manifest_path']))
        result['recovery'] = {
            'freeze': link(root, recovery_freeze), 'manifest': link(root, freeze['manifest_path']),
            'audit': link(root, recovery_audit),
            'audit_source': link(root, 'scripts/audit_static_recovery.py'),
            'results_sha256': {
                f'runs/{manifest["recovery_phase"]}/{q["run_id"]}__channel_recovery_1/result.json':
                sha(safe(root, f'runs/{manifest["recovery_phase"]}/{q["run_id"]}__channel_recovery_1/result.json'))
                for q in manifest['eligible']},
        }
    return result


def unsigned_signoffs(index_sha256):
    return {'schema_version': 'final-signoffs-1', 'evidence_index_sha256': index_sha256,
            'signoffs': {name: {'status': 'pending', 'reviewer': '', 'reviewed_at': None,
                                 'statement': '', 'evidence': []} for name in SIGNOFFS}}


class Gate:
    def __init__(self, root):
        self.root = root
        self.errors = []
        self.sources = {}
        self.raw = {}
        self.latest_finish = None

    def check(self, condition, message):
        if not condition:
            self.errors.append(message)
        return bool(condition)

    def bound(self, ref, label, kind='json'):
        path = safe(self.root, ref['path'])
        actual = sha(path)
        if not self.check(actual == ref['sha256'], label + ': byte hash changed'):
            raise ValueError(label + ': invalid binding')
        self.sources[ref['path']] = actual
        if kind == 'json':
            return read(path)
        if kind == 'csv':
            return csv_rows(path)
        return path

    def audit(self, audit, phase, expected_ids, raw, smt, label):
        self.check(audit.get('phase') == phase, label + ': phase mismatch')
        self.check(audit.get('coverage_complete') is True and audit.get('expected_records') == len(expected_ids), label + ': incomplete coverage')
        for key in ('phase_errors', 'missing', 'unexpected', 'duplicates', 'incomplete'):
            self.check(key in audit and audit[key] == [], label + ': missing/nonempty ' + key)
        records = unique(audit.get('runs', []) + audit.get('auxiliary_runs', []))
        self.check(set(records) == expected_ids, label + ': run inventory differs')
        at = timestamp(audit['at'])
        self.check(all(at >= timestamp(r['finished_at']) for r in raw.values()), label + ': audit predates run completion')
        for rid, r in raw.items():
            a = records.get(rid, {})
            self.check(a.get('audit_pass') is True and a.get('provenance_complete') is True and a.get('errors') == [], label + ': evidence/provenance failed ' + rid)
            for key in ('arm', 'repeat', 'status', 'scenario' if smt else 'instance_id'):
                self.check(a.get(key) == r.get(key), label + ': identity/status differs ' + rid + '/' + key)
            valid = a.get('domain_valid' if smt else 'valid')
            if r['status'] == 'success':
                self.check(valid is True, label + ': success has invalid domain ' + rid)
            if not smt:
                self.check(equal(a.get('makespan'), r.get('metrics', {}).get('makespan')), label + ': objective differs ' + rid)
        # A failed original static attempt can have fully certified evidence.
        want_ready = all(r['status'] == 'success' for r in raw.values())
        self.check(audit.get('acceptance_ready') is want_ready, label + ': acceptance flag disagrees with original statuses')
        return records

    def phase(self, phase, spec, index, expected_hashes):
        freeze_name, smt, auxiliary, count = PHASES[phase]
        self.check(spec['freeze']['path'] == f'configs/freezes/{freeze_name}.json', phase + ': wrong freeze file')
        f = self.bound(spec['freeze'], phase + '/freeze')
        matrix = [tuple(row) for row in f['matrix']]
        expected = expected_matrix(smt, auxiliary)
        self.check(f['phase'] == phase and set(matrix) == expected and len(matrix) == count, phase + ': frozen matrix is not the required exact matrix')
        raw = {}
        for item, arm, repeat in sorted(expected):
            rid = run_name(item, arm, repeat, smt)
            rel = f'runs/{phase}/{rid}/result.json'
            expected_hashes.add(rel)
            try:
                r = self.bound({'path': rel, 'sha256': index['original_results_sha256'][rel]}, rel)
                raw[rid] = r
                self.raw[(phase, rid)] = r
                finish = timestamp(r['finished_at'])
                self.latest_finish = max(self.latest_finish, finish) if self.latest_finish else finish
                self.check(r.get('phase') == phase and r.get('run_id') == rid and r.get('arm') == arm and r.get('repeat') == repeat, rel + ': identity mismatch')
                self.check(r.get('scenario' if smt else 'instance_id') == item, rel + ': instance/scenario mismatch')
                self.check(r.get('status') in ('success', 'failed', 'timeout'), rel + ': not a completed original attempt')
                self.check(r.get('code_commit') == f['code_commit'] and r.get('freeze_tag') == f['tag'] and r.get('protocol_version') == f['protocol_version'], rel + ': frozen version mismatch')
                self.check(r.get('config_sha256') == f['effective_config_sha256'][str(repeat)], rel + ': frozen effective config mismatch')
                directory = safe(self.root, f'runs/{phase}/{rid}')
                self.check(read(directory/'freeze.json') == f and r['freeze_manifest_sha256'] == sha(directory/'freeze.json'), rel + ': saved freeze/hash mismatch')
                cfg = read(directory/'config.json')
                self.check(object_sha(cfg) == r['config_sha256'], rel + ': config bytes/content mismatch')
                if smt:
                    m = r.get('metrics', {})
                    self.check(r['status'] == 'success' and r.get('validation', {}).get('valid') is True and m.get('completed_window') is True and equal(m.get('simulation_seconds'), 28800), rel + ': SMT must complete a legal 8-hour window')
                    self.check(r.get('adapter_version') == 'smt-adapter-v2' and r.get('window_seconds') == 28800 and r.get('controlled_machine_ids') == [9, 790] and r.get('warmup_seconds') == 0 and r.get('outside_policy') == 'setup-aware-priority-FIFO-demand-v1', rel + ': SMT boundary differs')
                elif r['status'] != 'success':
                    self.check(r.get('schedule') is None and r.get('metrics', {}).get('makespan') is None, rel + ': failed original carries a successful quality value')
                elif r.get('validation', {}).get('valid') is not True:
                    self.check(False, rel + ': success without stored validation')
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.errors.append(rel + ': ' + str(exc))
        self.check(len(raw) == count, phase + ': original records missing')
        if auxiliary and not smt:
            self.check(all(r['status'] == 'success' and r.get('validation', {}).get('valid') is True for r in raw.values()), phase + ': auxiliary static final schedules must also be feasible; do not erase failures')
        ids = {run_name(*key, smt) for key in expected}
        replay = self.bound(spec['replay'], phase + '/replay')
        report_audit = self.bound(spec['report_audit'], phase + '/report-audit')
        self.audit(replay, phase, ids, raw, smt, phase + '/replay')
        ra = self.audit(report_audit, phase, ids, raw, smt, phase + '/report-audit')
        self.check(spec['replay']['path'] != spec['report_audit']['path'], phase + ': replay and report audit must be separately saved')
        for kind in ('replay', 'report'):
            self.check(spec[kind+'_source']['path'] == f'src/{"smt_" if smt else ""}{kind}.py', phase + ': unexpected audit/report source')
            self.bound(spec[kind+'_source'], phase + '/' + kind + '-source', 'file')
        s = self.bound(spec['summary'], phase + '/summary')
        rows = unique(self.bound(spec['results_csv'], phase + '/csv', 'csv'))
        self.check(set(rows) == ids, phase + ': CSV original denominator/inventory differs')
        successes = sum(r['status'] == 'success' for r in raw.values())
        self.check(s.get('phase') == phase and s.get('coverage_complete') is True and s.get('expected_records') == count and s.get('missing_records') == 0, phase + ': incomplete report summary')
        self.check(s.get('records_including_missing' if smt else 'records') == count and s.get('core_records') == (0 if auxiliary else count) and s.get('auxiliary_records') == (count if auxiliary else 0), phase + ': report denominators differ')
        self.check(s.get('certified_successes' if smt else 'successes') == successes and s.get('non_successes' if smt else 'failures') == count-successes, phase + ': report success/failure totals differ')
        self.check(s.get('acceptance_ready') is (successes == count), phase + ': report rewrites original acceptance status')
        self.check(timestamp(s['at']) >= timestamp(report_audit['at']), phase + ': summary predates report audit')
        if smt:
            self.check(s.get('report_source_sha256') == spec['report_source']['sha256'], phase + ': report generator hash differs')
            provenance = unique(self.bound(spec['provenance'], phase + '/provenance'))
            self.check(set(provenance) == ids, phase + ': provenance inventory differs')
        else:
            self.check(s.get('reference_sha256') == f['files']['docs/fjsp-reference-values.json'], phase + ': frozen reference hash differs')
            groups = unique([dict(x, run_id=(x['instance'], x['arm'])) for x in s['aggregates']])
            expected_groups = {(item, arm) for item, arm, _ in expected}
            self.check(set(groups) == expected_groups, phase + ': report aggregate inventory differs')
            for key in expected_groups:
                members = [r for r in raw.values() if (r['instance_id'], r['arm']) == key]
                values = [r['metrics']['makespan'] for r in members if r['status'] == 'success']
                g = groups.get(key, {})
                self.check(g.get('total') == 3 and g.get('successes') == len(values) and equal(g.get('success_rate'), len(values)/3) and equal(g.get('makespan_mean_conditional_success'), sum(values)/len(values) if values else None), phase + ': altered original quality aggregate ' + str(key))
        for rid, r in raw.items():
            row = rows.get(rid, {})
            self.check(row.get('raw_status' if smt else 'status') == r['status'], phase + ': CSV status differs ' + rid)
            for key in ('arm', 'repeat', 'code_commit', 'config_sha256', 'data_sha256'):
                self.check(row.get(key) == r.get(key), phase + ': CSV provenance differs ' + rid + '/' + key)
            self.check(row.get('scenario' if smt else 'instance') == r.get('scenario' if smt else 'instance_id'), phase + ': CSV instance/scenario differs ' + rid)
            if smt:
                self.check(row.get('certified_success') is True and row.get('evidence_audit_pass') is True and row.get('report_status') == 'success', phase + ': uncertified SMT report row ' + rid)
                for key in ('throughput_lots', 'initial_wip_lots', 'terminal_wip_lots', 'controlled_family_queue_area_lot_seconds'):
                    self.check(equal(row.get(key), ra.get(rid, {}).get('recomputed_metrics', {}).get(key)), phase + ': SMT report metric differs ' + rid + '/' + key)
                p = provenance.get(rid, {})
                self.check(p.get('evidence_audit_pass') is True and all(p.get(k) == r.get(k) for k in ('code_commit', 'config_sha256', 'data_sha256', 'freeze_manifest_sha256')), phase + ': SMT provenance row differs ' + rid)
            else:
                self.check(equal(row.get('makespan'), r['metrics']['makespan']), phase + ': CSV has replaced original quality ' + rid)
                if r['status'] != 'success':
                    self.check(row.get('feasible') is False and all(value is None for key, value in row.items() if key.startswith('gap_')), phase + ': failed original has feasible/gap values ' + rid)
        return {'expected': count, 'original_records': len(raw), 'original_successes': successes,
                'original_non_successes': count-successes, 'core': not auxiliary}

    def recovery(self, index):
        originals = {rid: r for (phase, rid), r in self.raw.items() if phase == 'acceptance_static_v1'}
        delivered = {rid for rid, r in originals.items() if r['status'] == 'success' and r.get('validation', {}).get('valid') is True}
        rec = index.get('recovery')
        if rec is None:
            self.check(len(delivered) == 108, 'Static delivery missing; saved recovery certification required for failed original cells')
            return {'logical_expected': 108, 'logical_delivered': len(delivered), 'recovery_records': 0}
        f = self.bound(rec['freeze'], 'recovery/freeze')
        m = self.bound(rec['manifest'], 'recovery/manifest')
        a = self.bound(rec['audit'], 'recovery/audit')
        self.check(rec['manifest']['path'] == f['manifest_path'] and f['files'].get(f['manifest_path']) == rec['manifest']['sha256'], 'Recovery manifest not bound by freeze')
        self.check(rec['audit_source']['path'] == 'scripts/audit_static_recovery.py', 'Unexpected recovery certifier')
        self.bound(rec['audit_source'], 'recovery/audit-source', 'file')
        self.check(f['files'].get('scripts/audit_static_recovery.py') == rec['audit_source']['sha256'], 'Recovery certifier differs from frozen implementation')
        self.check(m.get('original_total_cells') == 180 and m.get('posthoc_reliability_recovery') is True and m.get('draft_not_frozen') is not True, 'Recovery manifest is draft or has wrong original scope')
        self.check(m.get('original_results_sha256') == index['original_results_sha256'], 'Recovery original 180 byte hashes differ')
        expected_freezes = {spec['freeze']['path']: spec['freeze']['sha256'] for spec in index['phases'].values()}
        self.check({x['path']: x['sha256'] for x in m['original_freezes']} == expected_freezes, 'Recovery original freeze bindings differ')
        self.check(a.get('acceptance_ready') is True and a.get('original_records') == 180 and a.get('original_static_denominator') == 108 and a.get('logical_delivered') == 108 and a.get('unexpected_recovery_directories') == [], 'Saved recovery audit is not complete/certified')
        self.check(a.get('protocol_version') == m.get('protocol_version') and a.get('original_static_successes') == len(delivered), 'Recovery has rewritten original status denominator')
        eligible = unique(m['eligible'])
        reports = unique(a['recovery_records'])
        expected_recovery_ids = {rid+'__channel_recovery_1' for rid in eligible}
        self.check(set(reports) == expected_recovery_ids and a.get('eligible_count') == len(eligible), 'Recovery eligibility/certificate inventory differs')
        expected_paths = {f'runs/{m["recovery_phase"]}/{rid}/result.json' for rid in expected_recovery_ids}
        self.check(set(rec['results_sha256']) == expected_paths, 'Recovery result hash inventory differs')
        recovered = {}
        for rel, digest in rec['results_sha256'].items():
            r = self.bound({'path': rel, 'sha256': digest}, rel)
            audit = reports.get(r['run_id'], {})
            self.check(audit.get('audit_pass') is True and audit.get('valid') is True and audit.get('errors') == [] and audit.get('status') == 'success' and r.get('status') == 'success', rel + ': recovery is not certified successful')
            saved_freeze = safe(self.root, rel).parent/'freeze.json'
            self.check(r.get('code_commit') == f['code_commit'] and r.get('freeze_tag') == f['tag'] and read(saved_freeze) == f and r.get('freeze_manifest_sha256') == sha(saved_freeze), rel + ': recovery freeze mismatch')
            self.check(r.get('validation', {}).get('valid') is True and equal(audit.get('makespan'), r.get('metrics', {}).get('makespan')), rel + ': recovery objective/validation mismatch')
            self.check(timestamp(a['at']) >= timestamp(r['finished_at']), rel + ': recovery audit predates completion')
            key = r['original_run_id']
            self.check(key not in recovered and key in originals and originals[key]['status'] != 'success' and r.get('original_phase') == 'acceptance_static_v1', rel + ': invalid original/recovery association')
            recovered[key] = r
        delivery = unique(a['logical_delivery'], 'logical_run_id')
        self.check(set(delivery) == set(originals) and len(delivery) == 108, 'Recovery logical delivery inventory differs')
        for rid, old in originals.items():
            d = delivery.get(rid, {})
            source = 'original' if rid in delivered else 'recovery' if rid in recovered else None
            chosen = old if source == 'original' else recovered.get(rid, {})
            self.check(d.get('original_status') == old['status'] and d.get('original_path') == f'runs/acceptance_static_v1/{rid}' and d.get('delivery_source') == source and source is not None, rid + ': logical delivery status/source differs')
            self.check(equal(d.get('delivery_makespan'), chosen.get('metrics', {}).get('makespan')), rid + ': logical delivery makespan differs')
            self.check(d.get('recovery_run_id') == (recovered[rid]['run_id'] if rid in recovered else None), rid + ': selected recovery differs')
        return {'logical_expected': 108, 'logical_delivered': len(delivered | set(recovered)), 'recovery_records': len(recovered)}

    def signoffs(self, signoffs, index_sha, prepared_at):
        self.check(signoffs.get('schema_version') == 'final-signoffs-1' and signoffs.get('evidence_index_sha256') == index_sha, 'Signoffs are not bound to this exact evidence index')
        for name in SIGNOFFS:
            item = signoffs.get('signoffs', {}).get(name, {})
            self.check(item.get('status') == 'passed', 'Unfinished independent/manual gate: ' + name)
            self.check(isinstance(item.get('reviewer'), str) and bool(item['reviewer'].strip()) and isinstance(item.get('statement'), str) and bool(item['statement'].strip()), name + ': missing accountable reviewer/statement')
            if item.get('reviewed_at'):
                when = timestamp(item['reviewed_at'])
                self.check(self.latest_finish is not None and when >= max(self.latest_finish, timestamp(prepared_at)), name + ': signoff predates completion/evidence index')
                self.check(when <= dt.datetime.now(dt.timezone.utc), name + ': signoff is in the future')
            else:
                self.check(False, name + ': missing reviewed_at')
            refs = item.get('evidence', [])
            self.check(isinstance(refs, list) and len(refs) > 0, name + ': actual evidence references required')
            for ref in refs:
                self.bound(ref, 'signoff/' + name, 'file')


def evaluate(root, index, index_sha, signoffs):
    gate = Gate(root)
    totals = {}
    expected_hashes = set()
    gate.check(index.get('schema_version') == 'final-evidence-1' and index.get('preparation_is_certification') is False, 'Evidence index schema/preparation marker invalid')
    gate.check(set(index.get('phases', {})) == set(PHASES), 'All four and only four original phases required')
    for phase in PHASES:
        try:
            totals[phase] = gate.phase(phase, index['phases'][phase], index, expected_hashes)
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            gate.errors.append(phase + ': missing/malformed saved evidence: ' + str(exc))
    gate.check(len(expected_hashes) == 180 and set(index.get('original_results_sha256', {})) == expected_hashes, 'Original result hash inventory must equal all 180 frozen cells')
    try:
        delivery = gate.recovery(index)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        gate.errors.append('Recovery/delivery gate: ' + str(exc)); delivery = None
    try:
        gate.signoffs(signoffs, index_sha, index['prepared_at'])
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        gate.errors.append('Signoff evidence: ' + str(exc))
    return {'schema_version': 'final-acceptance-1', 'checked_at': now(),
            'acceptance_ready': not gate.errors, 'status': 'passed' if not gate.errors else 'blocked',
            'core_expected': 135, 'auxiliary_expected': 45, 'original_expected': 180,
            'original_phase_counts': totals, 'static_logical_delivery': delivery,
            'unfinished_items': gate.errors, 'evidence_index_sha256': index_sha,
            'verified_saved_sources_sha256': gate.sources,
            'scope': 'Saved evidence consistency plus explicit external signoffs; no fresh domain replay.',
            'model_calls': 0, 'solver_calls': 0, 'goal_status_update_performed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    preparation = parser.add_mutually_exclusive_group()
    preparation.add_argument('--prepare-index', action='store_true')
    preparation.add_argument('--prepare-signoffs', action='store_true')
    parser.add_argument('--replay-label', default='final')
    parser.add_argument('--recovery-freeze')
    parser.add_argument('--recovery-audit')
    parser.add_argument('--index', default='artifacts/final/evidence-index.json')
    parser.add_argument('--signoffs', default='artifacts/final/review-signoffs.json')
    parser.add_argument('--output', default='artifacts/final/acceptance.json')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    try:
        if args.prepare_index:
            result = prepare_index(ROOT, args.replay_label, args.recovery_freeze, args.recovery_audit)
        elif args.prepare_signoffs:
            result = unsigned_signoffs(sha(safe(ROOT, args.index)))
        else:
            index_path = safe(ROOT, args.index)
            signoff_path = safe(ROOT, args.signoffs)
            result = evaluate(ROOT, read(index_path), sha(index_path), read(signoff_path))
            result['signoffs_sha256'] = sha(signoff_path)
            result['checker_sha256'] = sha(Path(__file__))
            if not args.check_only:
                destination = safe(ROOT, args.output)
                if ROOT/'artifacts' not in destination.parents:
                    raise ValueError('Acceptance output must remain under artifacts')
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open('x', encoding='utf-8') as handle:
                    handle.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if args.prepare_index or args.prepare_signoffs or result['acceptance_ready'] else 2
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        print(json.dumps({'acceptance_ready': False, 'status': 'blocked',
                          'unfinished_items': [type(exc).__name__ + ': ' + str(exc)]}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
