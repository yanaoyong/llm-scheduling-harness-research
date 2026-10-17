"""Reviewed C8 capacity gate for one newly frozen serial research run.

Preparation freezes bytes without registering a model call. Actual execution
uses the frozen host launcher and common owner-pipe guards. The installed
controller public run() remains blocked; this gate owns final acceptance.
"""
from __future__ import annotations
import argparse
from contextlib import nullcontext
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import shutil
import signal
import stat
import subprocess
import sys
import time
import traceback

from .offline_pilot import ROOT, DATA, VENDOR, _runtime, _origin_git, _git_pointer, _serial_lock
from .offline_A_gate_v3 import AUDIT_DEPENDENCIES, _active_with_finalizers
from .B_delta_gate_v3 import _ledger_domain
from .model_process_guard import run_guarded, verify_lifecycle

SCHEMA = 'smt-fullfab-C-stream-gate-v1'
RUN_ID = 'C_1701_8h_stream_v1'
PROTOCOL = 'configs/smt_fullfab/C_stream_8h_v1.protocol.json'
AREA = 'runs/smt_fullfab_C_stream_gate'
LEDGER = 'progress/smt_fullfab/model_ledger.jsonl'
APPROVAL = 'configs/smt_fullfab/stage2_probe.approved.json'
WAIVER = 'configs/smt_fullfab/research_limit_waiver.approved.json'
CHILD_SECONDS, OUTER_SECONDS, READBACK_SECONDS, RESTORE_SECONDS = 43200, 46800, 600, 180
TRACE_BYTES, MAX_BYTES, MIN_FREE_BYTES, RSS_BYTES = 2*1024**3, 24*1024**3, 64*1024**3, 8*1024**3
PRIOR_ATTEMPTS, PRIOR_UNKNOWN = 260, 3
CLI_PATH = '/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex'
CLI_EXECUTABLE = '/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'
ATTRIBUTION_DIR = 'src/smt_fullfab/C_stream_attribution_v2'
ATTRIBUTION_SOURCES = {
    'audit_candidate.py': '80e201fa0849e1bdcdc26fb2b28e59dd8357f9938356db03f90479d9868de8df',
    'legacy_checks.py': '9288d4d630b921d39fc9775a40928e4a0109a9bdf579fe3409ea3550619471eb',
    'storage.py': 'bf2145395dc1e19371c0c64bdf165b4bf11356622ccec9551fb69e2f7642d17a',
    'constructor_stream.py': '181f9819bab37e0f60da03cd06f67505d9849336f0326632372903d41c896a60',
}
RECEIPT_KEYS = ('sha256', 'byte_count', 'line_count', 'event_count', 'max_record_bytes')
METRICS = ('window_start', 'window_end', 'weighted_tardy_lot_hours', 'throughput_lots',
           'terminal_wip_lots', 'terminal_tardy_wip_lots')
PARAMETERS = {'run_id': RUN_ID, 'arm': 'C', 'seed': 1701, 'seconds': 28800,
    'wall_seconds': 43200.0, 'max_log_bytes': MAX_BYTES, 'max_trace_bytes': TRACE_BYTES,
    'max_calls': None, 'max_tokens': None, 'per_call_timeout_seconds': 180,
    'solver_budget_seconds': 32.0, 'constructor_seconds_cap': 5.0,
    'constructor_evaluation_cap': 250000, 'page_chars': 45000,
    'plan_seconds': 14400, 'lookahead_depth': 2, 'period_seconds': 1800,
    'enable_constructive': True, 'audit_mode': 'stream', 'snapshot_mode': 'stream',
    'cold_start_only': True, 'formal': False}
LAUNCH_BLOCKERS = ()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)+'\n').encode('utf-8')


def same(a, b):
    return json.dumps(a, sort_keys=True, separators=(',', ':'), allow_nan=False) == json.dumps(b, sort_keys=True, separators=(',', ':'), allow_nan=False)


def number(value, *, minimum=0, maximum=None):
    return (type(value) in (int, float) and math.isfinite(value) and value >= minimum
            and (maximum is None or value <= maximum))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def strict(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, 'duplicate JSON key')
            value[key] = item
        return value
    value = json.loads(raw, object_pairs_hook=pairs)
    same(value, value)
    return value


def identity(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def read_file(path, *, expected_sha256=None, keep_bytes=False):
    """Hash the exact same complete FD bytes that a JSON caller will parse."""
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and identity(before) == identity(path.lstat()), 'nonregular/replaced evidence')
        hasher, count, chunks = hashlib.sha256(), 0, []
        while True:
            block = stream.read(1024*1024)
            if not block:
                break
            count += len(block)
            hasher.update(block)
            if keep_bytes:
                chunks.append(block)
        require(count == before.st_size and identity(before) == identity(os.fstat(stream.fileno())) == identity(path.lstat()), 'evidence changed during full read')
    sha = hasher.hexdigest()
    require(expected_sha256 is None or sha == expected_sha256, 'original SHA binding differs: '+str(path))
    return (b''.join(chunks) if keep_bytes else None), {'sha256': sha, 'bytes': count, 'file_identity': list(identity(before))}


def read_json(path, expected_sha256=None):
    raw, receipt = read_file(path, expected_sha256=expected_sha256, keep_bytes=True)
    return strict(raw), receipt


def write_new(path, value, *, raw=False):
    data = value if raw else encoded(value)
    with Path(path).open('xb') as stream:
        require(stream.write(data) == len(data), 'short evidence write')
        stream.flush(); os.fsync(stream.fileno())
    return hashlib.sha256(data).hexdigest()


def validate_protocol(protocol):
    require(protocol.get('schema') == SCHEMA+'-protocol' and protocol.get('formal') is False
            and protocol.get('execute_now') is False and same(protocol.get('run_parameters'), PARAMETERS), 'fixed cold C8 protocol differs')
    limits = {'child_seconds': CHILD_SECONDS, 'outer_seconds': OUTER_SECONDS,
        'readback_seconds': READBACK_SECONDS, 'restore_seconds_within_readback': RESTORE_SECONDS,
        'trace_bytes': TRACE_BYTES, 'run_scratch_campaign_bytes': MAX_BYTES,
        'minimum_free_bytes': MIN_FREE_BYTES, 'maximum_child_peak_rss_bytes': RSS_BYTES,
        'rss_is_hard_guard': False, 'minimum_preserved_prior_model_attempts': PRIOR_ATTEMPTS,
        'minimum_preserved_prior_unknown_calls': PRIOR_UNKNOWN, 'serial_only': True,
        'model': 'gpt-6-astra', 'reasoning_effort': 'medium', 'global_max_calls': None, 'global_max_tokens': None}
    require(same(protocol.get('limits'), limits), 'registered capacity/authorization limits differ')
    require(type(protocol.get('prerequisite_sha256')) is dict and protocol['prerequisite_sha256'], 'prerequisite receipts required')
    for name, sha in protocol['prerequisite_sha256'].items():
        require(type(name) is str and not Path(name).is_absolute() and '..' not in Path(name).parts
                and type(sha) is str and len(sha) == 64 and all(c in '0123456789abcdef' for c in sha), 'invalid prerequisite anchor')
    roles = protocol.get('prerequisite_roles')
    require(type(roles) is dict and set(roles) == {'parity_summary', 'parity_readback',
            'controller_tests', 'installed_tests', 'installation_manifest', 'resource_envelope',
            'guard_tests','transport_tests'}
            and all(path in protocol['prerequisite_sha256'] for path in roles.values()), 'complete prerequisite roles required')
    require(type(protocol.get('additional_frozen_files')) is list and all(type(name) is str
            and not Path(name).is_absolute() and '..' not in Path(name).parts
            for name in protocol['additional_frozen_files']), 'supplemental frozen scripts must be relative files')
    return dict(PARAMETERS)


def prerequisite_proof(root, protocol):
    """Only small already-published reports; never rerun C1 to authorize C8."""
    objects = {}
    for relative, sha in protocol['prerequisite_sha256'].items():
        objects[relative] = read_json(root/relative, sha)[0]
    p = objects[protocol['prerequisite_roles']['parity_summary']]
    q = objects[protocol['prerequisite_roles']['parity_readback']]
    t = objects[protocol['prerequisite_roles']['controller_tests']]
    installed = objects[protocol['prerequisite_roles']['installed_tests']]
    installation = objects[protocol['prerequisite_roles']['installation_manifest']]
    r = objects[protocol['prerequisite_roles']['resource_envelope']]
    require(p.get('accepted') is True and p.get('old_valid') is True and p.get('new_valid') is True
            and p.get('full_field_difference_count') == 0 and p.get('real_C8_executions') == 0, 'saved C1 parity absent')
    require(q.get('valid') is True and q.get('both_reports_valid') is True
            and q.get('original_sources_and_certificate_prefix_unchanged') is True
            and q.get('inner_result_sha256') == p['evidence_sha256']['attempt_001/result.json'], 'independent bound parity readback differs')
    require(t.get('all_passed') is True and t.get('original_inputs_unchanged') is True
            and sum(row['tests_run'] for row in t['records']) == 52, 'controller draft tests absent')
    require(installed.get('schema')=='C8-installed-tests-reconciliation-v1'
            and installed.get('all_required_passed') is True and installed.get('distinct_required_tests')==77
            and installed.get('original_inputs_unchanged_within_each_attempt') is True
            and installed.get('actual_experiments')==installed.get('model_calls')==installed.get('solver_calls')==installed.get('actual_C8_runs')==0,
            'explicit installed-test reconciliation missing')
    def referenced(ref):
        require(type(ref)is dict and protocol['prerequisite_sha256'].get(ref['path'])==ref['sha256'], 'prerequisite reference lacks original external SHA')
        return objects[ref['path']]
    require(same(installed['source_manifest'],{'path':protocol['prerequisite_roles']['installation_manifest'],
            'sha256':protocol['prerequisite_sha256'][protocol['prerequisite_roles']['installation_manifest']]}), 'installed source manifest differs')
    referenced(installed['source_manifest']);referenced(installed['exact_change_record'])
    reports={'v2':referenced(installed['full_initial_attempt']),'v3':referenced(installed['selective_retest'])}
    for ref in installed['original_protocols']:referenced(ref)
    expected_groups={('v2',1,7),('v2',2,6),('v2',3,22),('v3',0,39),('v3',1,3)}
    groups=installed['selected_passed_groups']
    require(len(groups)==5 and {(x['version'],x['record_index'],x['tests_run']) for x in groups}==expected_groups,
            'selected distinct test groups differ; never claim first attempt all passed')
    for selected in groups:
        source=reports[selected['version']];row=source['records'][selected['record_index']]
        require(source['original_inputs_unchanged'] is True and row['returncode']==0 and row['timed_out'] is False
                and row['tests_run']==selected['tests_run'] and row['test']==selected['test'], 'selected installed test group did not pass')
    require(installed['current_controller_sha256']==next(item['sha256'] for item in installation['source_files']
            if item['path']=='src/smt_fullfab/C_stream_controller.py'),'reconciled current controller differs')
    validator='artifacts/smt_fullfab_diagnostics/C8_installation_v3/validate_test_evidence.py'
    read_file(root/validator,expected_sha256=installed['validator_sha256'])
    for role,count in (('guard_tests',21),('transport_tests',20)):
        tests=objects[protocol['prerequisite_roles'][role]]
        require(tests['all_passed'] is True and tests['original_inputs_unchanged'] is True
                and sum(item['tests_run'] for item in tests['records'])==count
                and all(item['returncode']==0 and item['timed_out'] is False for item in tests['records'])
                and tests['model_calls']==tests['solver_calls']==tests['actual_factory_runs']==0,
                'required benign lifecycle/transport tests missing')
    for item in installation['source_files']:
        read_file(root/item['path'], expected_sha256=item['sha256'])
    # The exact externally pinned resource document is authoritative; do not
    # convert its conditional extrapolation into an actual C8 observation.
    require(r.get('schema') == 'smt-fullfab-C8-resource-envelope-v2'
            and r['revised_unregistered_limits']['run_plus_scratch_plus_campaign_bytes'] == MAX_BYTES
            and r['revised_unregistered_limits']['minimum_free_disk_bytes'] == MIN_FREE_BYTES
            and r.get('actual_C8_runs') == 0, 'resource-envelope report differs')
    return {'verified_prerequisites': dict(protocol['prerequisite_sha256']),
            'saved_C1_only_not_C8_validation': True, 'launch_blockers': list(LAUNCH_BLOCKERS)}


def input_paths(root, protocol):
    paths = []
    for name in ('src', 'vendor', 'data'):
        base = root/name
        require(base.is_dir() and not base.is_symlink(), 'missing/linked frozen tree')
        for path in sorted(base.rglob('*')):
            if '__pycache__' in path.parts or path.suffix in ('.pyc', '.pyo'):
                continue
            require(not path.is_symlink(), 'linked source input')
            if path.is_file(): paths.append(path)
    paths += list(root.glob('requirements*'))+[root/PROTOCOL, root/APPROVAL, root/WAIVER]
    paths += [root/name for name in protocol['prerequisite_sha256']]
    paths += [root/name for name in protocol['additional_frozen_files']]
    require(root/'requirements.lock' in paths, 'requirements.lock required')
    return sorted(set(paths))


def inventory(root, protocol):
    return {p.relative_to(root).as_posix(): read_file(p)[1]['sha256'] for p in input_paths(root, protocol)}


def runtime_capture():
    return {'python': _runtime(), 'model_cli': {name: {'declared_path': path,
        'resolved_path': str(Path(path).resolve()), **read_file(Path(path).resolve())[1]}
        for name, path in (('wrapper', CLI_PATH), ('executable', CLI_EXECUTABLE))}}


def ledger_preflight(raw, root, *, require_unused=True):
    rows = [strict(line) for line in raw.splitlines() if line.strip()]
    require(all(type(row) is dict for row in rows), 'original ledger rows must be objects')
    approval = read_json(root/APPROVAL)[0]; waiver = read_json(root/WAIVER)[0]
    require(same([r['approval'] for r in rows if r.get('event') == 'approval'], [approval]), 'original approval differs')
    require(same([r['amendment'] for r in rows if r.get('event') == 'research_limit_waiver'], [waiver]), 'research waiver differs')
    starts = [r for r in rows if r.get('event') in ('reserve', 'solver_reserve', 'constructor_reserve')]
    ends = [r for r in rows if r.get('event') in ('finish', 'solver_finish', 'constructor_finish')]
    ids, done = [r['call_id'] for r in starts], [r['call_id'] for r in ends]
    require(len(ids) == len(set(ids)) and len(done) == len(set(done)) and set(ids) == set(done), 'pending/duplicate/orphan original resource calls')
    counts = sum(r['event'] == 'reserve' for r in starts)
    model_ids = {r['call_id'] for r in starts if r['event'] == 'reserve'}
    def known_usage(row):
        details = row.get('details')
        usage = details.get('usage') if type(details) is dict else None
        return type(usage) is dict and all(type(usage.get(k)) is int and usage[k] >= 0
            for k in ('input_tokens', 'output_tokens'))
    unknown = [r['call_id'] for r in ends if r['call_id'] in model_ids and not known_usage(r)]
    expected_finishes = {'reserve':'finish', 'solver_reserve':'solver_finish', 'constructor_reserve':'constructor_finish'}
    start_by_id = {r['call_id']:r for r in starts}
    require(all(r['event'] == expected_finishes[start_by_id[r['call_id']]['event']] for r in ends), 'resource finish type differs')
    require(counts >= PRIOR_ATTEMPTS and len(unknown) >= PRIOR_UNKNOWN, 'research model/unknown history reset or omitted')
    target = str((root/'runs/smt_fullfab_stage2'/RUN_ID).resolve())
    if require_unused:
        for row in rows:
            for record in [row]+[row[k] for k in ('registration', 'mapping', 'finalization') if type(row.get(k)) is dict]:
                for key in ('run_id', 'parent_run_id', 'segment_run_id'):
                    value = record.get(key)
                    if type(value) is str:
                        path = Path(value).resolve()
                        require(str(path) != target and Path(target) not in path.parents, 'new C8 target already registered; no retry')
    return {'prefix_sha256': hashlib.sha256(raw).hexdigest(), 'prefix_bytes': len(raw),
            'original_model_attempts': counts, 'original_unknown_call_ids': unknown}


def prepare(*, root=ROOT):
    """Create-new byte freeze only. It does not register any budget or model call."""
    root = Path(root).resolve(); campaign = root/AREA/RUN_ID
    require(not campaign.exists(), 'campaign already exists; inspect it, never prepare over it')
    protocol = read_json(root/PROTOCOL)[0]; validate_protocol(protocol)
    with _serial_lock(root):
        require(not _active_with_finalizers(root), 'active run/finalizer blocks freeze')
        require(not (root/'runs/smt_fullfab_stage2'/RUN_ID).exists(), 'original target already exists')
        require(shutil.disk_usage(root).free >= MIN_FREE_BYTES, 'insufficient free disk')
        started = time.monotonic(); prior, _ = read_file(root/LEDGER, keep_bytes=True)
        prior_proof = ledger_preflight(prior, root); prerequisite = prerequisite_proof(root, protocol)
        inputs, runtime, head = inventory(root, protocol), runtime_capture(), _origin_git(root)
        for name, expected in ATTRIBUTION_SOURCES.items():
            require(inputs.get(ATTRIBUTION_DIR+'/'+name) == expected, 'installed attribution bytes differ from C1-parity source')
        for name in ('C_stream_controller.py', 'C_plan_archive.py', 'C_stream_attribution_stage.py'):
            require('src/smt_fullfab/'+name in inputs, 'installed C runtime missing')
        campaign.mkdir(parents=True, exist_ok=False); frozen = campaign/'frozen'; frozen.mkdir()
        try:
            for name, expected in inputs.items():
                raw, _ = read_file(root/name, expected_sha256=expected, keep_bytes=True)
                dest = frozen/name; dest.parent.mkdir(parents=True, exist_ok=True)
                write_new(dest, raw, raw=True); dest.chmod(0o444)
            require(inputs == inventory(root, protocol) and runtime == runtime_capture(), 'freeze input/runtime changed')
            write_new(campaign/'ledger_at_prepare.jsonl', prior, raw=True)
            for name in ('runs', 'progress'):
                require((root/name).is_dir(), 'original run/ledger directory missing')
                (frozen/name).symlink_to(root/name, target_is_directory=True)
            _git_pointer(frozen, head)
            manifest = {'schema': SCHEMA+'-frozen', 'run_id': RUN_ID, 'origin_root': str(root),
                'origin_git_head': head, 'config': dict(PARAMETERS), 'protocol_sha256': inputs[PROTOCOL],
                'frozen_input_sha256': inputs, 'runtime': runtime, 'launcher_executable': sys.executable,
                'actual_ledger_path': str(root/LEDGER), 'output_directory': str(root/'runs/smt_fullfab_stage2'/RUN_ID),
                'attribution_scratch_directory': str(campaign/'attribution_scratch'), 'prior_ledger': prior_proof,
                'prerequisite_proof': prerequisite, 'prepare_wall_seconds': time.monotonic()-started,
                'launch_blockers': list(LAUNCH_BLOCKERS), 'formal': False}
            manifest['identity'] = digest(manifest)
            write_new(campaign/'manifest.json', manifest)
            return campaign, manifest
        except BaseException as exc:
            write_new(campaign/'freeze_failure.json', {'type': type(exc).__name__, 'message': str(exc)})
            raise


def verify_frozen(campaign, manifest, *, for_execution=False):
    campaign = Path(campaign).resolve(); root = Path(manifest['origin_root']); frozen = campaign/'frozen'
    require(campaign == root/AREA/RUN_ID and manifest['schema'] == SCHEMA+'-frozen'
            and manifest['identity'] == digest({k:v for k,v in manifest.items() if k != 'identity'}), 'frozen identity/path differs')
    actual, _ = read_json(campaign/'manifest.json')
    require(same(actual, manifest), 'supplied manifest no longer equals original manifest')
    protocol = read_json(frozen/PROTOCOL, manifest['protocol_sha256'])[0]; validate_protocol(protocol)
    require(inventory(frozen, protocol) == manifest['frozen_input_sha256'], 'frozen complete input inventory changed')
    require(all(not (frozen/name).stat().st_mode & 0o222 for name in manifest['frozen_input_sha256']), 'frozen input became writable')
    require(same(manifest['config'], PARAMETERS), 'fixed C8 config differs')
    for name in ('runs', 'progress'):
        require((frozen/name).is_symlink() and (frozen/name).resolve() == root/name, 'actual run/ledger mapping changed')
    require(manifest['actual_ledger_path'] == str(root/LEDGER), 'actual shared ledger changed')
    prior, receipt = read_file(campaign/'ledger_at_prepare.jsonl', expected_sha256=manifest['prior_ledger']['prefix_sha256'], keep_bytes=True)
    require(receipt['bytes'] == manifest['prior_ledger']['prefix_bytes'], 'historical prefix truncated')
    live, _ = read_file(root/LEDGER, keep_bytes=True); require(live.startswith(prior), 'global research ledger reset')
    prerequisite_proof(frozen, protocol)
    if for_execution:
        require(runtime_capture() == manifest['runtime'] and sys.executable == manifest['launcher_executable'], 'runtime changed')
        require(read_file(__file__)[1]['sha256'] == manifest['frozen_input_sha256']['src/smt_fullfab/C_stream_gate.py'], 'gate must use frozen reviewed implementation')


def files(base, *, campaign=False):
    base = Path(base)
    if not base.exists(): return []
    result = []
    for path in sorted(base.rglob('*')):
        if path.is_symlink():
            require(campaign and path in (base/'frozen/runs', base/'frozen/progress'), 'unexpected evidence symlink')
            continue
        if path.is_file(): result.append(path)
    return result


def evidence(campaign, run, *, include_outer=False):
    return {prefix+'/'+p.relative_to(base).as_posix(): read_file(p)[1]['sha256']
            for prefix,base in (('campaign', Path(campaign)), ('run', Path(run)))
            for p in files(base, campaign=prefix == 'campaign') if p != Path(campaign)/'acceptance.json'
            and (include_outer or prefix!='campaign' or (base/'outer_process') not in p.parents)}


def total_bytes(campaign, run):
    return sum(p.stat().st_size for p in files(campaign, campaign=True)+files(run))


def bind_first(verified, final):
    """Original verified anchors remain authoritative; never adopt later bytes."""
    require(type(verified) is dict and verified, 'original verification anchors missing')
    require(all(final.get(k) == v for k,v in verified.items()), 'verified evidence changed before acceptance')
    require({k:v for k,v in final.items() if k.startswith('run/')} ==
            {k:v for k,v in verified.items() if k.startswith('run/')}, 'raw run inventory changed after verification')


def bind_receipts(verified, final):
    """Small late-produced proofs must retain their first parsed raw SHA too."""
    require(all(final.get(name) == sha for name,sha in verified.items()), 'first parsed phase proof changed before acceptance')


def validate_terminal(result, execution):
    require(result.get('status') == 'success' and result.get('failure') is None and result.get('failure_details') is None
            and result.get('accepted') is False and result.get('real_C8_launch_authorized') is False
            and result.get('launch_authority_scope') == 'controller_does_not_self_authorize'
            and result.get('acceptance_authority') == 'external_frozen_gate'
            and result.get('direct_public_execution_enabled') is False
            and result.get('audit_valid') is True and result.get('terminal_trace_binding_valid') is True
            and result.get('full_window_completed') is True
            and number(result.get('simulation_seconds')) and result['simulation_seconds'] == 28800
            and execution.get('status') == 'awaiting_attribution' and execution.get('failure') is None
            and execution.get('full_window_completed') is True
            and number(execution.get('simulation_seconds')) and execution['simulation_seconds'] == 28800,
            'C execution/result is incomplete or failed')
    require(number(execution.get('wall_seconds')) and number(result.get('wall_seconds'), maximum=CHILD_SECONDS)
            and execution['wall_seconds'] <= result['wall_seconds'], 'C child internal time cap/missing cost')


def validate_attribution_stage(stage):
    report = stage['attribution_report']
    require(stage.get('valid') is True and report.get('valid') is True and report.get('errors') == []
            and report.get('missing_evidence') == [] and report.get('audit_status') == 'passed'
            and report.get('run_status') == 'awaiting_attribution' and report.get('successful_full_window') is False
            and report.get('all_saved_problem_pages_lossless_certified') is True
            and stage.get('complete_original_attribution_checks') is True and stage.get('legacy_whole_history_adapter_used') is False,
            'complete independent attribution report missing/invalid')
    return report


def _pending_empty(account):
    return all(account.get(k) == [] for k in ('pending', 'pending_solver_calls', 'pending_constructor_calls'))


def _final_ledger(run, manifest, expected_sha, registration_id):
    saved, _ = read_file(run/'ledger_final.jsonl', expected_sha256=expected_sha, keep_bytes=True)
    live, _ = read_file(manifest['actual_ledger_path'], keep_bytes=True)
    require(live.startswith(saved), 'real ledger no longer preserves final historical prefix')
    parse_rows = lambda raw: [strict(line) for line in raw.splitlines() if line.strip()]
    require(same(_ledger_domain(parse_rows(saved), run, registration_id),
                 _ledger_domain(parse_rows(live), run, registration_id)), 'same run/registration/call acquired suffix; do not re-anchor')


def verification_payload(campaign, manifest, first):
    """Frozen saved-evidence readback; no model/tool or simulation advancement."""
    from . import C_stream_controller as c
    from .stream_audit_bundle import read_bundle
    from .trace_source import inspect_jsonl
    campaign = Path(campaign); run = Path(manifest['output_directory']); inputs = manifest['frozen_input_sha256']
    def bound(name, expected=None):
        original = first['run/'+name]
        require(expected is None or original == expected, 'external expected original hash differs: '+name)
        return read_json(run/name, original)[0]
    result = bound('result.json'); cfg = bound('config.json'); execution = bound('execution_result.json', result['execution_result_sha256'])
    require(all(k in cfg and same(cfg[k],v) for k,v in PARAMETERS.items()), 'C config differs from registered capacity/semantics')
    expected_cfg = {k:v for k,v in c.PROPOSAL.items() if k not in ('outer_wall_seconds','minimum_free_bytes','peak_rss_bytes','peak_rss_is_final_acceptance_not_hard_guard')}
    approval = read_json(campaign/'frozen'/APPROVAL)[0]; waiver = read_json(campaign/'frozen'/WAIVER)[0]
    expected_cfg.update(run_id=RUN_ID, budget_id=approval['budget_id'], amendment_id=waiver['amendment_id'])
    require(same(cfg, expected_cfg) and same(result['config'], cfg) and same(execution['config'], cfg)
            and result['identity'] == execution['identity'] == digest(cfg), 'full C config/identity differs')
    validate_terminal(result, execution)
    provenance = bound('provenance.json')
    shallow = {k:v for k,v in inputs.items() if Path(k).parent.as_posix() in ('src/smt','src/smt_fullfab') and k.endswith('.py')}
    added = {'attribution_stream_v2/'+name:sha for name,sha in ATTRIBUTION_SOURCES.items()}
    require(provenance['source_sha256'] == {**shallow, **added}
            and provenance['git_commit'] == manifest['origin_git_head']
            and provenance['requirements_sha256'] == inputs['requirements.lock'], 'raw source provenance differs')
    for name,sha in {**provenance['source_sha256'], 'src/__init__.py': inputs['src/__init__.py']}.items():
        require(first.get('run/source_snapshot/'+name) == sha, 'recoverable raw source missing/changed')
    anchor = bound('terminal_trace_anchor.json'); receipt = anchor['source_receipt']
    require(type(receipt) is dict and set(receipt) == set(RECEIPT_KEYS)
            and same(result['first_terminal_trace_receipt'], receipt), 'original first trace receipt missing')
    seal = inspect_jsonl(run/'trace.jsonl', expected_sha256=receipt['sha256'])
    require(same({k:getattr(seal,k) for k in RECEIPT_KEYS}, receipt)
            and list(seal.file_identity) == anchor['file_identity']
            and receipt['sha256'] == first['run/trace.jsonl'] and receipt['byte_count'] <= TRACE_BYTES,
            'complete source or original trace identity changed')
    ref = result['audit_bundle']
    require(set(ref) == {'path','manifest_sha256'} and ref['path'] == 'audit_bundle', 'unsafe physical bundle reference')
    bundle = bound('audit_bundle/audit_bundle.json', ref['manifest_sha256'])
    checked = read_bundle(run/'audit_bundle', expected_manifest_sha256=ref['manifest_sha256'])
    require(checked['storage_verified'] is True and checked['semantic_replay_performed'] is False
            and same(checked['source_receipt'], receipt) and same(bundle['source_receipt'], receipt)
            and same(checked['summary'], bundle['summary']), 'full physical storage readback differs')
    for name,item in bundle['members'].items():
        require(first.get('run/audit_bundle/'+name) == item['sha256'], 'physical member changed from first verification anchor')
    require(bundle['dependency_sha256'] == {k:inputs[k] for k in AUDIT_DEPENDENCIES}
            and bundle['bundle_source_sha256'] == inputs['src/smt_fullfab/stream_audit_bundle.py'], 'physical audit implementation differs')
    envelope, summary = bundle['envelope'], bundle['summary']
    require(envelope['terminal_at_eof'] is True and envelope['first_time'] == 0
            and envelope['last_time'] == envelope['horizon'] == 28800 and same(envelope['receipt'], receipt)
            and bundle['configuration'] == {'window_start':0,'priority_weights':None,'require_terminal':True,'verify_data_dir_supplied':True},
            'prefix/warm/incomplete physical window cannot pass')
    require(all(summary.get(k) is True for k in ('valid','source_valid','opportunity_valid','physical_valid',
        'actual_dispatch_provenance_complete','absence_of_unreported_legal_demand_certified',
        'complete_physical_window_certified','verified_input_hashes')), 'full factory physical/coverage proof missing')
    source = bound('audit_bundle/source.json', bundle['members']['source.json']['sha256'])
    require(source.get('valid') is True and source.get('errors') == [] and source.get('declared_full_factory_domain') is True
            and type(source.get('production_machine_count')) is int and source['production_machine_count'] == 913
            and type(source.get('declared_control_machine_count')) is int and source['declared_control_machine_count'] == 913
            and same(source['_source_evidence']['source_receipt'], receipt)
            and source['_source_evidence']['complete_jsonl_pass'] is True, 'complete 913-machine source audit absent')
    require(set(result['metrics']) == set(METRICS) and same(result['metrics'], summary['metrics']), 'six metric mirror differs from full report')
    periods = bound('period_audit.json')
    rows_raw, _ = read_file(run/'period_receipts.jsonl', expected_sha256=first['run/period_receipts.jsonl'], keep_bytes=True)
    rows = [strict(line) for line in rows_raw.splitlines() if line.strip()]
    replay = c.audit_periods(run/'trace.jsonl', rows, expected_trace_sha256=receipt['sha256'], horizon=28800, period=1800)
    require(periods.get('valid') is True and same(periods, replay) and same(periods['source_receipt'],receipt), 'absolute period full-EOF audit differs')
    stage = bound('controller_attribution_stage.json'); report = validate_attribution_stage(stage)
    require(stage['execution_result_sha256'] == first['run/execution_result.json'] == result['execution_result_sha256']
            and stage['stage_config_identity'] == result['identity']
            and stage['first_terminal_trace_anchor_sha256'] == first['run/terminal_trace_anchor.json']
            and all(same(stage[k], receipt) for k in ('original_trace_receipt','first_terminal_trace_receipt')),
            'stage changed original execution or first trace anchor')
    require(report['evidence_sha256'].get('execution_result.json') == first['run/execution_result.json']
            and report['evidence_sha256'].get('trace.jsonl') == receipt['sha256'], 'attribution aliases/trace binding differ')
    for name,sha in report['evidence_sha256'].items():
        if not Path(name).is_absolute(): require(first.get('run/'+name) == sha, 'full attribution member changed: '+name)
        else: require(name == manifest['actual_ledger_path'] and sha == first['run/ledger_final.jsonl'], 'unrecognized external attribution evidence')
    initial_binding = bound('attribution_source_binding.json')
    require(same(initial_binding,result['attribution_source_binding']), 'initial attribution source binding changed')
    for binding,base in ((initial_binding,campaign/'frozen'/ATTRIBUTION_DIR),
                         (stage['attribution_source_binding'],run/'source_snapshot/attribution_stream_v2')):
        require(set(binding['files']) == set(ATTRIBUTION_SOURCES)
                and same(binding['expected_attribution_sources'],{k:v for k,v in ATTRIBUTION_SOURCES.items() if k!='constructor_stream.py'})
                and binding['constructor_sha256'] == ATTRIBUTION_SOURCES['constructor_stream.py'], 'full attribution implementation manifest differs')
        for name,sha in ATTRIBUTION_SOURCES.items():
            entry=binding['files'][name]
            require(entry['path']==str(base/name) and entry['sha256']==sha
                    and entry['bytes']==(base/name).stat().st_size
                    and entry['file_identity']==list(identity((base/name).lstat())), 'attribution implementation source identity changed')
    trace_report = report['_source_evidence']['receipts'][str(run/'trace.jsonl')]
    require(trace_report['sha256'] == receipt['sha256'] and trace_report['bytes'] == receipt['byte_count'], 'attribution incomplete raw trace receipt')
    registration = bound('resource_registration.json'); c.validate_registration(cfg, run, registration)
    account_ref = result['ledger_final_account_sha256']
    bound('ledger_final_account.json', account_ref)
    account = c.read_account_evidence(run, ledger_path=manifest['actual_ledger_path'], expected_report_sha256=account_ref)
    values = account['account']
    require(_pending_empty(values) and account['solver_requested_seconds'] <= 32
            and account['ledger_sha256'] == first['run/ledger_final.jsonl'], 'pending or changed resource account')
    mirrors = {'model_calls':values['attempts'],'model_call_ids':account['reserve_call_ids'],
        'solver_calls':len(account['solver_call_ids']),'solver_requested_seconds':account['solver_requested_seconds'],
        'constructor_calls':values['constructor_calls'],'constructor_requested_seconds':values['constructor_requested_seconds'],
        'constructor_active_seconds':values['constructor_active_seconds']}
    require(all(same(result.get(k),v) and same(execution.get(k),v) for k,v in mirrors.items()), 'actual ledger cost differs from execution/final result')
    require(type(result.get('plans_committed')) is int and result['plans_committed'] > 0
            and result['plans_committed'] == periods['committed_plans'] == report['committed_plans'] == report['attribution_checked_plans']
            and report['model_call_ids'] == account['reserve_call_ids'] and report['model_attempt_directories'] == values['attempts'], 'original calls/plans omitted')
    lifecycle_evidence = {}
    for index in range(values['attempts']):
        request = bound(f'model_{index:03d}/request.json')
        config = request['config']
        require(config['model'] == 'gpt-6-astra' and config['reasoning_effort'] == 'medium'
                and number(config['timeout_seconds'],minimum=1,maximum=180)
                and config['codex_binary'] == CLI_PATH and config['ledger_path'] == manifest['actual_ledger_path'], 'model/runtime budget settings differ')
        model_result=bound(f'model_{index:03d}/result.json')
        command=bound(f'model_{index:03d}/command.json')['argv']
        guarded=verify_lifecycle(run/f'model_{index:03d}',expected_command=command,
            expected_timeout=config['timeout_seconds'],expected_call_id=request['call_id'],
            expected_fingerprint=request['request_fingerprint'],expected_evidence=model_result['process_guard'])
        require(guarded['guard_source_sha256']==inputs['src/smt_fullfab/model_process_guard.py']
                and same(guarded['command_returncode'],model_result['returncode'])
                and same(guarded['timed_out'],model_result['timed_out'])
                and guarded['launch_error']==model_result['launch_error'],'model lifecycle differs from original result/frozen guard')
        for name,sha in guarded['files_sha256'].items():
            key=f'run/model_{index:03d}/process_guard/{name}'
            require(first.get(key)==sha,'original lifecycle member changed')
            lifecycle_evidence[key]=sha
        for name,sha in guarded['output_files_sha256'].items():
            key=f'run/model_{index:03d}/'+name
            require(first.get(key)==sha,'model raw output differs from original lifecycle')
    scratch = result['attribution_scratch']
    require(scratch['path'] == manifest['attribution_scratch_directory'] and scratch['retained'] is True
            and scratch['bytes'] == sum(p.stat().st_size for p in files(Path(scratch['path']))), 'external attribution scratch omitted from costs')
    checkpoint = result['checkpoint']
    require(set(checkpoint) == {'path','state_sha256','file_sha256'} and checkpoint['path'] == 'checkpoint.json'
            and first['run/checkpoint.json'] == checkpoint['file_sha256'], 'exact checkpoint reference missing')
    _final_ledger(run, manifest, account['ledger_sha256'], registration['registration_id'])
    bind_first(first, evidence(campaign,run))
    return {'valid': True, 'verified_evidence_sha256': first, 'result_sha256':first['run/result.json'],
        'execution_sha256': first['run/execution_result.json'], 'first_trace_receipt':receipt,
        'checkpoint': checkpoint, 'registration_id':registration['registration_id'],
        'model_lifecycle_evidence_sha256':lifecycle_evidence,
        'ledger_sha256':account['ledger_sha256'], 'account':values, 'result_wall_seconds':result['wall_seconds'],
        'model_attribution_rerun':False,'full_saved_attribution_bound':True,'physical_reexecution':False}


def restoration_payload(campaign, manifest, proof):
    """Existing exact snapshot-1 restoration semantics, retained scratch, no advance."""
    from .environment import FullFabEnvironment, digest as state_digest
    from .trace_source import inspect_jsonl, open_verified
    run = Path(manifest['output_directory']); ref = proof['checkpoint']
    original = read_json(run/'checkpoint.json', ref['file_sha256'])[0]
    require(original['state_sha256'] == ref['state_sha256'], 'original state SHA differs')
    env = FullFabEnvironment.from_snapshot(run/'checkpoint.json')
    output = Path(campaign)/'restoration_scratch'; output.mkdir(exist_ok=False)
    env.snapshot(output/'restored.json')
    restored = read_json(output/'restored.json')[0]['state']
    loaded = restored['trace'].pop()
    require(loaded['kind'] == 'snapshot_loaded' and state_digest(restored) == ref['state_sha256'], 'restored full state differs')
    require(env.seed == 1701 and env.t == env.horizon == 28800 and env.finished is True and env.observation_start == 0
            and len(env.physical) == 913, 'restored checkpoint is not the full cold C8 window')
    seal = inspect_jsonl(run/'trace.jsonl', expected_sha256=proof['first_trace_receipt']['sha256'])
    count = 0
    with open_verified(seal) as reader:
        for record in reader:
            require(count < len(restored['trace']) and same(record.event, restored['trace'][count]), 'checkpoint trace differs from complete raw events')
            count += 1
    require(count == len(restored['trace']), 'checkpoint has missing/additional raw events')
    read_file(run/'checkpoint.json', expected_sha256=ref['file_sha256'])
    return {'valid':True,'checkpoint_sha256':ref['file_sha256'],'restored_state_sha256':ref['state_sha256'],
        'trace_events':count,'simulation_seconds':env.t,'production_scope':len(env.physical),
        'simulation_advancement_performed':False,'model_calls':0,'solver_calls':0,'restoration_scratch_retained':True}


def owned_phase(command, *, cwd, output, timeout, output_paths=None, inputs=None):
    """One explicit generic owner-pipe phase, with original returned SHA anchors.

    run_guarded owns the actual child/session and reaps it. All complete phase
    records are create-new; failures leave partial evidence and never retry.
    """
    output=Path(output).resolve();output.mkdir(exist_ok=False)
    started=time.monotonic();guarded=None;primary=None
    request={'schema':SCHEMA+'-phase-request','command':list(command),'cwd':str(Path(cwd).resolve()),
        'timeout_seconds':timeout,'phase_directory':str(output),'call_id':RUN_ID+':'+output.name,
        'output_paths':{k:str(Path(v).resolve()) for k,v in (output_paths or {}).items()},
        'additional_inputs':{k:str(Path(v).resolve()) for k,v in (inputs or {}).items()}}
    request_sha=write_new(output/'phase_request.json',request)
    fingerprint=digest(request)
    io={'cwd':request['cwd'],'stdin':None,'stdout':str(output/'stdout.log'),'stderr':str(output/'stderr.log'),
        'inputs':{'approved_phase_request':str(output/'phase_request.json'),**request['additional_inputs']},
        'outputs':{'stdout':str(output/'stdout.log'),'stderr':str(output/'stderr.log'),**request['output_paths']}}
    require(all(not Path(path).exists() for path in io['outputs'].values()),'a declared phase output already exists; never reuse it')
    env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME','GIT_DIR','GIT_WORK_TREE','GIT_INDEX_FILE')}
    env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull)
    try:
        guarded=run_guarded(list(command),run_dir=output,timeout_seconds=timeout,env=env,
            call_id=request['call_id'],request_fingerprint=fingerprint,io_spec=io)
        if guarded['command_returncode']!=0 or guarded['timed_out'] or guarded['launch_error'] is not None:
            primary={'type':'GuardedCommandFailed','message':str({k:guarded[k] for k in ('command_returncode','timed_out','launch_error')})}
    except BaseException as exc:
        primary={'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()}
    rss=None if guarded is None else max(guarded['command_peak_rss_bytes'] or 0,guarded['guard_peak_rss_bytes'] or 0)
    result={'schema':SCHEMA+'-phase','phase_directory':str(output),'phase_request_sha256':request_sha,
        'request_fingerprint':fingerprint,'io_spec':io,'guard_evidence':guarded,
        'returncode':None if guarded is None else guarded['command_returncode'],
        'primary_failure':primary,'cleanup_errors':[] if guarded is not None else ['lifecycle incomplete; inspect original guard records'],
        'wall_seconds':time.monotonic()-started,'limit_seconds':timeout,'peak_rss_bytes':rss,
        'rss_is_hard_guard':False,'automatic_retry':False,'detached_model_guard_integrated':True}
    result_sha=write_new(output/'process.json',result)
    return {**result,'process_sha256':result_sha}


def phase_anchors(campaign, process, run=None):
    """Original write/parse receipts, never an inventory taken after validation."""
    phase=Path(process['phase_directory']);prefix='campaign/'+phase.relative_to(campaign).as_posix()+'/'
    result={prefix+'phase_request.json':process['phase_request_sha256'],prefix+'process.json':process['process_sha256']}
    guard=process.get('guard_evidence')
    if guard is not None:
        result.update({prefix+'process_guard/'+name:sha for name,sha in guard['files_sha256'].items()})
        for label,sha in guard['output_files_sha256'].items():
            if sha is None:continue
            path=Path(process['io_spec']['outputs'][label])
            if path.is_relative_to(campaign):result['campaign/'+path.relative_to(campaign).as_posix()]=sha
            else:
                require(run is not None and path.is_relative_to(run),'phase output lies outside original campaign/run')
                result['run/'+path.relative_to(run).as_posix()]=sha
    return result


def check_storage(campaign, run):
    require(total_bytes(campaign,run)<=MAX_BYTES,'checkpoint-detected combined storage cap exceeded')
    trace=Path(run)/'trace.jsonl'
    require(not trace.exists() or trace.stat().st_size<=TRACE_BYTES,'checkpoint-detected trace cap exceeded')


def verify_phase(campaign,manifest,process,*,command,maximum):
    """Independent readback of one original phase record and actual guard wait."""
    phase=Path(process['phase_directory'])
    require(phase.parent==Path(campaign) and phase.name in ('child_process','readback_process','restoration_process','outer_process'), 'unexpected phase directory')
    saved=read_json(phase/'process.json',process['process_sha256'])[0]
    require(same(saved,{k:v for k,v in process.items() if k!='process_sha256'}),'phase in-memory record differs from original bytes')
    request=read_json(phase/'phase_request.json',process['phase_request_sha256'])[0]
    require(request['command']==command and request['cwd']==str(Path(campaign)/'frozen')
            and number(request['timeout_seconds'],minimum=0,maximum=maximum) and request['timeout_seconds']>0
            and same(request['timeout_seconds'],process['limit_seconds'])
            and process['request_fingerprint']==digest(request),'phase original command/deadline differs')
    guard=verify_lifecycle(phase,expected_command=command,expected_timeout=request['timeout_seconds'],
        expected_call_id=request['call_id'],expected_fingerprint=process['request_fingerprint'],
        expected_evidence=process['guard_evidence'],expected_io_spec=process['io_spec'])
    require(guard['guard_source_sha256']==manifest['frozen_input_sha256']['src/smt_fullfab/model_process_guard.py']
            and same(guard['command_returncode'],process['returncode'])
            and number(guard.get('parent_wait_wall_seconds')) and guard['parent_wait_wall_seconds']<=process['wall_seconds']
            and process['peak_rss_bytes']==max(guard['command_peak_rss_bytes'] or 0,guard['guard_peak_rss_bytes'] or 0),
            'phase guard source/exit/measured RSS differs')
    _process_ok(process,maximum)
    return phase_anchors(Path(campaign),process,Path(manifest['output_directory']))


def _phase_command(campaign, manifest, kind, first_path=None, proof_path=None, *, first_sha='', proof_sha=''):
    code = "import sys;sys.path.insert(0,sys.argv[1]);from src.smt_fullfab.C_stream_gate import _worker;raise SystemExit(_worker(*sys.argv[2:]))"
    return [manifest['launcher_executable'],'-I','-B','-c',code,str(Path(campaign)/'frozen'),
            kind,str(campaign),manifest['identity'],str(first_path or ''),str(proof_path or ''),first_sha,proof_sha]


def _worker(kind, campaign, expected_identity, first_path='', proof_path='', first_sha='', proof_sha=''):
    campaign = Path(campaign); manifest = read_json(campaign/'manifest.json')[0]
    require(manifest['identity'] == expected_identity
            and expected_identity == digest({k:v for k,v in manifest.items() if k!='identity'}), 'worker original manifest differs')
    if kind == 'supervise':
        result=_execute_reviewed(campaign,manifest,_under_outer_guard=True)
        return 0 if result['accepted'] else 1
    if kind == 'run':
        # This private entry is blocked too: importing this draft cannot bypass
        # public execute merely by calling a hidden argv or helper.
        require(not LAUNCH_BLOCKERS, 'C8 launch blocked: '+'; '.join(LAUNCH_BLOCKERS))
        from . import C_stream_controller as c
        from . import budget
        root = Path(manifest['origin_root']); budget.ROOT = root
        result = c._implementation_draft(run_id=RUN_ID, root=root, ledger_path=root/LEDGER,
            approval_path=campaign/'frozen'/APPROVAL,
            attribution_source_dir=campaign/'frozen'/ATTRIBUTION_DIR,
            expected_attribution_sources={k:v for k,v in ATTRIBUTION_SOURCES.items() if k != 'constructor_stream.py'},
            constructor_source=campaign/'frozen'/ATTRIBUTION_DIR/'constructor_stream.py',
            expected_constructor_sha256=ATTRIBUTION_SOURCES['constructor_stream.py'],
            attribution_scratch_dir=manifest['attribution_scratch_directory'])
        return 0 if result['status'] == 'success' else 1
    require(len(first_sha)==64, 'worker requires externally passed first-anchor SHA')
    first = read_json(first_path,first_sha)[0]
    if kind == 'verify':
        result = verification_payload(campaign, manifest, first)
        write_new(campaign/'verification_payload.json', result)
    elif kind == 'restore':
        require(len(proof_sha)==64, 'restoration requires original parsed verification SHA')
        proof = read_json(proof_path,proof_sha)[0]
        require(proof['verified_evidence_sha256']==first,'restore received a different first-anchor map')
        result = restoration_payload(campaign, manifest, proof)
        write_new(campaign/'restoration_payload.json', result)
    else: raise ValueError('unknown owned phase')
    return 0 if result['valid'] else 1


def _process_ok(process, limit):
    require(type(process.get('returncode')) is int and process['returncode'] == 0
            and process.get('primary_failure') is None and process.get('cleanup_errors') == []
            and type(process.get('wall_seconds')) in (int,float) and math.isfinite(process['wall_seconds'])
            and 0 <= process['wall_seconds'] <= limit and type(process.get('peak_rss_bytes')) is int
            and 0 < process['peak_rss_bytes'] <= RSS_BYTES, 'child/readback exit, complete time or measured RSS failed')


def validate_success(value, manifest, *, supervisor=False):
    """Recompute acceptance predicates; a self-consistent accepted flag is insufficient."""
    require(value.get('schema')==SCHEMA+('-supervisor-result' if supervisor else '-acceptance')
            and value.get('run_id')==RUN_ID and value.get('manifest_identity')==manifest['identity']
            and value.get('protocol_sha256')==manifest['protocol_sha256']
            and value.get('accepted') is True and value.get('status')=='success' and value.get('errors')==[]
            and value.get('formal') is False and value.get('automatic_retry') is False,
            'terminal flags/errors/identity do not establish success')
    require(number(value.get('outer_wall_seconds_through_receipt_preparation'),maximum=OUTER_SECONDS)
            and type(value.get('final_total_bytes_including_acceptance')) is int
            and 0<value['final_total_bytes_including_acceptance']<=MAX_BYTES,
            'outer wall or complete retained byte bound failed')
    for key,limit in (('child_process',CHILD_SECONDS),('readback_process',READBACK_SECONDS),('restoration_process',RESTORE_SECONDS)):
        require(type(value.get(key))is dict,'required completed phase missing')
        _process_ok(value[key],limit)
        require(number(value[key].get('limit_seconds'),minimum=0,maximum=limit)
                and value[key]['limit_seconds']>0 and value[key]['wall_seconds']<=value[key]['limit_seconds'],
                'recorded phase failed its own admitted remaining deadline')
    require(number(value.get('readback_wall_seconds'),maximum=READBACK_SECONDS),'combined readback and restore deadline failed')
    restored=value.get('restoration')
    require(type(restored)is dict and restored.get('valid') is True
            and number(restored.get('simulation_seconds')) and restored['simulation_seconds']==28800
            and type(restored.get('production_scope'))is int and restored['production_scope']==913
            and restored.get('simulation_advancement_performed') is False
            and all(type(restored.get(k))is int and restored[k]==0 for k in ('model_calls','solver_calls')),
            'complete exact restoration missing')
    require(type(value.get('verified_evidence_sha256'))is dict and value['verified_evidence_sha256']
            and value.get('runner_result_sha256')==value['verified_evidence_sha256'].get('run/result.json'),
            'original verified run result anchor missing')
    if not supervisor:
        require(value.get('full_supervisor_exit_verified') is True,'supervisor exit lacks actual original wait')
        _process_ok(value['outer_process'],OUTER_SECONDS)
        require(number(value['outer_process'].get('limit_seconds'),maximum=OUTER_SECONDS)
                and 0<value['outer_process']['limit_seconds']
                and value['outer_process']['wall_seconds']<=value['outer_process']['limit_seconds'],
                'outer supervisor exceeded its admitted remaining deadline')


def _terminal_encoding(result, base_size, elapsed, *, success_validator=None):
    """Prepare exact terminal bytes, refreshing/checking time in every pass.

    Only byte count and failure state must converge, not the changing clock.
    The recorded timestamp precedes the last encoding pass. The deadline is
    checked again after that pass and its success predicates; publication and
    process exit belong to the enclosing guard/host measurement.
    """
    errors=result['errors']
    for _ in range(32):
        wall=elapsed();require(number(wall),'invalid terminal elapsed time')
        result['outer_wall_seconds_through_receipt_preparation']=wall
        if wall>OUTER_SECONDS and not any(e['type']=='OuterTimeLimit' for e in errors):
            errors.append({'type':'OuterTimeLimit','message':'terminal preparation or encoding exceeds original outer cap'})
        result.update(accepted=not errors,status='failed' if errors else 'success')
        result['identity']=digest({k:v for k,v in result.items() if k!='identity'})
        raw=encoded(result);final_size=base_size+len(raw)
        if final_size>MAX_BYTES and not any(e['type']=='TotalBytesLimit' for e in errors):
            errors.append({'type':'TotalBytesLimit','message':'retained run+scratch+campaign exceeds24GiB'})
        stable=(final_size==result['final_total_bytes_including_acceptance']
                and result['accepted']==(not errors))
        if stable and result['accepted'] and success_validator is not None:
            success_validator(result)
        checked_wall=elapsed();require(number(checked_wall),'invalid post-encoding elapsed time')
        if checked_wall>OUTER_SECONDS and not any(e['type']=='OuterTimeLimit' for e in errors):
            errors.append({'type':'OuterTimeLimit','message':'terminal encoding or validation crosses original outer cap'})
            stable=False
        if stable:return raw
        result['final_total_bytes_including_acceptance']=final_size
    raise ValueError('terminal receipt byte accounting did not converge within 32 passes')


def execute(campaign, manifest):
    require(not LAUNCH_BLOCKERS, 'C8 launch blocked: '+'; '.join(LAUNCH_BLOCKERS))
    campaign=Path(campaign).resolve();root=Path(manifest['origin_root']);run=Path(manifest['output_directory'])
    started=time.monotonic();elapsed=lambda:manifest['prepare_wall_seconds']+time.monotonic()-started
    with _serial_lock(root):
        verify_frozen(campaign,manifest,for_execution=True)
        require(not run.exists() and not (campaign/'attempt.json').exists()
                and not (campaign/'outer_process').exists(),'existing original attempt; no retry')
        require(not _active_with_finalizers(root),'active experiment/finalizer')
        require(shutil.disk_usage(root).free>=MIN_FREE_BYTES,'insufficient launch disk margin')
        current,_=read_file(root/LEDGER,keep_bytes=True);ledger_preflight(current,root)
        before=evidence(campaign,run);check_storage(campaign,run)
        remaining=OUTER_SECONDS-elapsed();require(remaining>0,'outer budget already depleted')
        outer=owned_phase(_phase_command(campaign,manifest,'supervise'),cwd=campaign/'frozen',
            output=campaign/'outer_process',timeout=remaining,
            inputs={'manifest':campaign/'manifest.json'},output_paths={'supervisor_result':campaign/'supervisor_result.json'})
        errors=[];supervisor=None;original=phase_anchors(campaign,outer,run)
        try:
            verify_phase(campaign,manifest,outer,command=_phase_command(campaign,manifest,'supervise'),maximum=OUTER_SECONDS)
            expected=outer['guard_evidence']['output_files_sha256']['supervisor_result']
            require(type(expected)is str,'guard did not observe supervisor terminal result')
            supervisor=read_json(campaign/'supervisor_result.json',expected)[0]
            validate_success(supervisor,manifest,supervisor=True)
            original.update(supervisor['first_parsed_phase_proof_sha256'])
            require(supervisor['outer_wall_seconds_through_receipt_preparation']<=elapsed(),'supervisor wall exceeds enclosing measured wall')
        except BaseException as exc:errors.append({'stage':'supervisor','type':type(exc).__name__,'message':str(exc)})
        try:verify_frozen(campaign,manifest,for_execution=True)
        except BaseException as exc:errors.append({'stage':'final_runtime','type':type(exc).__name__,'message':str(exc)})
        final=evidence(campaign,run,include_outer=True)
        try:
            bind_receipts(before,final);bind_receipts(original,final)
            if supervisor is not None:
                bind_first(supervisor['verified_evidence_sha256'],final)
                bound=read_json(campaign/'verification_payload.json',original['campaign/verification_payload.json'])[0]
                _final_ledger(run,manifest,bound['ledger_sha256'],bound['registration_id'])
        except BaseException as exc:errors.append({'stage':'final_original_binding','type':type(exc).__name__,'message':str(exc)})
        result={'schema':SCHEMA+'-acceptance','run_id':RUN_ID,'manifest_identity':manifest['identity'],
            'protocol_sha256':manifest['protocol_sha256'],'evidence_sha256':final,
            'first_parsed_phase_proof_sha256':original,'supervisor_result_sha256':original.get('campaign/supervisor_result.json'),
            'verified_evidence_sha256':None if supervisor is None else supervisor.get('verified_evidence_sha256'),
            'runner_result_sha256':final.get('run/result.json'),'outer_process':outer,
            'child_process':None if supervisor is None else supervisor.get('child_process'),
            'readback_process':None if supervisor is None else supervisor.get('readback_process'),
            'restoration_process':None if supervisor is None else supervisor.get('restoration_process'),
            'restoration':None if supervisor is None else supervisor.get('restoration'),
            'readback_wall_seconds':None if supervisor is None else supervisor.get('readback_wall_seconds'),
            'prepare_wall_seconds':manifest['prepare_wall_seconds'],'errors':errors,'formal':False,
            'automatic_retry':False,'full_supervisor_exit_verified':outer['guard_evidence'] is not None,
            'model_backend_independently_authenticated':False,
            'outer_wall_seconds_through_receipt_preparation':elapsed(),
            'wall_scope':'prepare plus all guarded supervisor phases, supervisor result publication and exit, guard cleanup/wait/readback and final evidence binding; timestamp resampled before the final encoding pass, deadline checked again after encoding and acceptance predicates; final certificate write/fsync/return measured separately by launching host',
            'final_total_bytes_including_acceptance':0}
        raw=_terminal_encoding(result,total_bytes(campaign,run),elapsed,
                               success_validator=lambda value:validate_success(value,manifest))
        acceptance_sha=write_new(campaign/'acceptance.json',raw,raw=True)
        return {'status':result['status'],'accepted':result['accepted'],
            'acceptance_path':str(campaign/'acceptance.json'),'acceptance_sha256':acceptance_sha,
            'manifest_identity':manifest['identity'],
            'outer_wall_seconds_through_receipt_preparation':result['outer_wall_seconds_through_receipt_preparation'],
            'full_supervisor_exit_verified':result['full_supervisor_exit_verified']}


def _execute_reviewed(campaign, manifest, *, _under_outer_guard=False):
    """Complete supervised terminal flow, pending this integration's validation."""
    require(not LAUNCH_BLOCKERS, 'private execution cannot bypass unresolved launch blockers')
    require(_under_outer_guard is True,'supervisor requires the enclosing common guard and serial lock')
    campaign = Path(campaign).resolve(); root = Path(manifest['origin_root']); run = Path(manifest['output_directory'])
    started = time.monotonic(); elapsed = lambda:manifest['prepare_wall_seconds']+time.monotonic()-started
    # The real outer parent holds the original flock for this entire worker and
    # its final resource/receipt verification. Reacquiring in a new process would
    # deadlock. Owner loss closes the chain and terminates this worker.
    with nullcontext():
        verify_frozen(campaign, manifest, for_execution=True)
        require(not run.exists() and not (campaign/'attempt.json').exists(), 'original attempt exists; no retry')
        require(not _active_with_finalizers(root), 'active experiment/finalizer')
        require(shutil.disk_usage(root).free >= MIN_FREE_BYTES, 'insufficient free disk at launch')
        current, _ = read_file(root/LEDGER, keep_bytes=True); ledger_preflight(current, root)
        write_new(campaign/'attempt.json', {'manifest_identity':manifest['identity'],'supervisor_pid':os.getpid(),
            'child_command':_phase_command(campaign,manifest,'run'),'outer_limit':OUTER_SECONDS,'automatic_retry':False})
        original_campaign = evidence(campaign,run); errors=[]; proof=None; child=None; restored=None; parsed_proofs={};verification_process=None;restoration_process=None;readback_wall=None
        try:
            check_storage(campaign,run)
            child=owned_phase(_phase_command(campaign,manifest,'run'),cwd=campaign/'frozen',output=campaign/'child_process',
                              timeout=min(CHILD_SECONDS,max(.001,OUTER_SECONDS-elapsed())),
                              inputs={'manifest':campaign/'manifest.json'},output_paths={'result':run/'result.json'})
            parsed_proofs.update(phase_anchors(campaign,child,run))
            verify_phase(campaign,manifest,child,command=_phase_command(campaign,manifest,'run'),maximum=CHILD_SECONDS)
            check_storage(campaign,run)
            verify_frozen(campaign,manifest,for_execution=True)
            first=evidence(campaign,run);require(all(first.get(k)==v for k,v in original_campaign.items()),'original campaign changed')
            first_sha=write_new(campaign/'first_verification_anchors.json',first)
            parsed_proofs['campaign/first_verification_anchors.json']=first_sha
            validation_started=time.monotonic()
            remaining=min(READBACK_SECONDS,OUTER_SECONDS-elapsed());require(remaining>0,'no remaining readback budget')
            process=owned_phase(_phase_command(campaign,manifest,'verify',campaign/'first_verification_anchors.json',first_sha=first_sha),
                cwd=campaign/'frozen',output=campaign/'readback_process',timeout=remaining,
                inputs={'manifest':campaign/'manifest.json','first':campaign/'first_verification_anchors.json'},
                output_paths={'verification':campaign/'verification_payload.json'})
            verification_process=process;parsed_proofs.update(phase_anchors(campaign,process,run));check_storage(campaign,run)
            _process_ok(process,remaining);proof,proof_receipt=read_json(campaign/'verification_payload.json')
            require(proof_receipt['sha256']==process['guard_evidence']['output_files_sha256']['verification'],'readback payload differs from original guarded bytes')
            parsed_proofs['campaign/verification_payload.json']=proof_receipt['sha256']
            require(proof.get('valid') is True and proof['verified_evidence_sha256']==first,'readback changed first anchors')
            remain=min(RESTORE_SECONDS,READBACK_SECONDS-(time.monotonic()-validation_started),OUTER_SECONDS-elapsed())
            require(remain>0,'readback/outer budget depleted before exact restore')
            process=owned_phase(_phase_command(campaign,manifest,'restore',campaign/'first_verification_anchors.json',campaign/'verification_payload.json',
                first_sha=first_sha,proof_sha=proof_receipt['sha256']),
                cwd=campaign/'frozen',output=campaign/'restoration_process',timeout=remain,
                inputs={'manifest':campaign/'manifest.json','first':campaign/'first_verification_anchors.json','proof':campaign/'verification_payload.json'},
                output_paths={'restoration':campaign/'restoration_payload.json'})
            restoration_process=process;parsed_proofs.update(phase_anchors(campaign,process,run));check_storage(campaign,run)
            _process_ok(process,remain);restored,restored_receipt=read_json(campaign/'restoration_payload.json')
            require(restored_receipt['sha256']==process['guard_evidence']['output_files_sha256']['restoration'],'restoration payload differs from original guarded bytes')
            parsed_proofs['campaign/restoration_payload.json']=restored_receipt['sha256']
            require(restored.get('valid') is True and restored['checkpoint_sha256']==proof['checkpoint']['file_sha256'],'exact restore failed')
            require(proof['result_wall_seconds']<=child['wall_seconds'],'child tail time missing')
            readback_wall=time.monotonic()-validation_started
            require(readback_wall<=READBACK_SECONDS,'combined readback/restore elapsed cap')
        except BaseException as exc:errors.append({'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()})
        try:verify_frozen(campaign,manifest,for_execution=True)
        except BaseException as exc:errors.append({'stage':'post_freeze','type':type(exc).__name__,'message':str(exc)})
        final=evidence(campaign,run)
        try:
            require(all(final.get(k)==v for k,v in original_campaign.items()),'final campaign replaced original anchors')
            bind_receipts(parsed_proofs,final)
            if proof is not None:
                bind_first(proof['verified_evidence_sha256'],final)
                _final_ledger(run,manifest,proof['ledger_sha256'],proof['registration_id'])
        except BaseException as exc:errors.append({'stage':'final_binding','type':type(exc).__name__,'message':str(exc)})
        wall=elapsed()
        if wall>OUTER_SECONDS:errors.append({'type':'OuterTimeLimit','message':'all gate phases exceed original outer cap'})
        result={'schema':SCHEMA+'-supervisor-result','run_id':RUN_ID,'manifest_identity':manifest['identity'],
            'protocol_sha256':manifest['protocol_sha256'],'evidence_sha256':final,
            'first_parsed_phase_proof_sha256':parsed_proofs,
            'verified_evidence_sha256':None if proof is None else proof['verified_evidence_sha256'],
            'runner_result_sha256':final.get('run/result.json'),'outer_wall_seconds_through_receipt_preparation':wall,
            'full_supervisor_exit_requires_external_guard':True,'prepare_wall_seconds':manifest['prepare_wall_seconds'],
            'child_process':child,'readback_process':verification_process,'restoration_process':restoration_process,
            'readback_wall_seconds':readback_wall,
            'restoration':restored,'errors':errors,'final_total_bytes_including_acceptance':0,
            'formal':False,'model_backend_independently_authenticated':False,'automatic_retry':False}
        result['wall_scope']='timestamp resampled before final terminal encoding pass, deadline checked again afterward; publication and exit measured by enclosing guard'
        raw=_terminal_encoding(result,total_bytes(campaign,run),elapsed)
        write_new(campaign/'supervisor_result.json',raw,raw=True)
        return result


def read_acceptance(*,root=ROOT):
    """Read original terminal evidence and recompute its resource predicates.

    This does not rerun physical/attribution algorithms or start/resume calls.
    Root runs this saved readback inside its separately registered 600s guard.
    """
    try:
        root=Path(root).resolve();campaign=root/AREA/RUN_ID
        manifest=read_json(campaign/'manifest.json')[0];verify_frozen(campaign,manifest)
        acceptance,receipt=read_json(campaign/'acceptance.json')
        require(acceptance.get('identity')==digest({k:v for k,v in acceptance.items() if k!='identity'})
                and acceptance.get('manifest_identity')==manifest['identity'],'saved acceptance identity differs')
        run=Path(manifest['output_directory']);actual=evidence(campaign,run,include_outer=True)
        require(actual==acceptance['evidence_sha256'] and total_bytes(campaign,run)==acceptance['final_total_bytes_including_acceptance'],'saved complete evidence changed')
        bind_receipts(acceptance['first_parsed_phase_proof_sha256'],actual)
        if acceptance.get('accepted') is True:
            require(not LAUNCH_BLOCKERS,'success cannot be certified by an unresolved gate draft')
            validate_success(acceptance,manifest)
            bind_first(acceptance['verified_evidence_sha256'],actual)
            proof=read_json(campaign/'verification_payload.json',actual['campaign/verification_payload.json'])[0]
            supervisor=read_json(campaign/'supervisor_result.json',acceptance['supervisor_result_sha256'])[0]
            require(supervisor['identity']==digest({k:v for k,v in supervisor.items() if k!='identity'}),'supervisor identity differs')
            validate_success(supervisor,manifest,supervisor=True)
            require(same(proof['verified_evidence_sha256'],supervisor['verified_evidence_sha256'])
                    and same(supervisor['verified_evidence_sha256'],acceptance['verified_evidence_sha256'])
                    and proof.get('valid') is True,'original verification proof differs')
            for key in ('child_process','readback_process','restoration_process','restoration','readback_wall_seconds'):
                require(same(acceptance[key],supervisor[key]),'outer receipt changed supervisor phase fact')
            first_sha=acceptance['first_parsed_phase_proof_sha256']['campaign/first_verification_anchors.json']
            proof_sha=acceptance['first_parsed_phase_proof_sha256']['campaign/verification_payload.json']
            commands={
                'outer_process':_phase_command(campaign,manifest,'supervise'),
                'child_process':_phase_command(campaign,manifest,'run'),
                'readback_process':_phase_command(campaign,manifest,'verify',campaign/'first_verification_anchors.json',first_sha=first_sha),
                'restoration_process':_phase_command(campaign,manifest,'restore',campaign/'first_verification_anchors.json',campaign/'verification_payload.json',first_sha=first_sha,proof_sha=proof_sha)}
            for key,limit in (('outer_process',OUTER_SECONDS),('child_process',CHILD_SECONDS),('readback_process',READBACK_SECONDS),('restoration_process',RESTORE_SECONDS)):
                anchors=verify_phase(campaign,manifest,acceptance[key],command=commands[key],maximum=limit)
                bind_receipts(anchors,actual)
            restored=read_json(campaign/'restoration_payload.json',actual['campaign/restoration_payload.json'])[0]
            require(same(restored,acceptance['restoration']) and restored['checkpoint_sha256']==proof['checkpoint']['file_sha256'], 'restored proof changed')
            _final_ledger(run,manifest,proof['ledger_sha256'],proof['registration_id'])
        else:
            require(acceptance.get('accepted') is False and acceptance.get('status')=='failed'
                    and type(acceptance.get('errors'))is list and acceptance['errors'],'failed receipt has inconsistent flags/errors')
        return {'valid':True,'accepted':acceptance.get('accepted') is True,'acceptance_sha256':receipt['sha256'],
                'status':acceptance['status'],'semantic_audits_rerun':False,'errors':[]}
    except Exception as exc:
        return {'valid':False,'accepted':False,'status':'unverified','errors':[str(exc)]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare',action='store_true');parser.add_argument('--execute',action='store_true')
    parser.add_argument('--read-acceptance',action='store_true')
    args=parser.parse_args();require(sum((args.prepare,args.execute,args.read_acceptance))<=1,'choose one operation')
    if args.read_acceptance:result=read_acceptance()
    elif args.execute:
        require(not LAUNCH_BLOCKERS,'C8 launch blocked: '+'; '.join(LAUNCH_BLOCKERS))
        campaign=ROOT/AREA/RUN_ID;result=execute(campaign,read_json(campaign/'manifest.json')[0])
    elif args.prepare:
        campaign,manifest=prepare();result={'status':'prepared_blocked' if LAUNCH_BLOCKERS else 'prepared','campaign':str(campaign),'identity':manifest['identity'],'launch_blockers':list(LAUNCH_BLOCKERS)}
    else:result={'status':'static_plan_only','run_id':RUN_ID,'parameters':PARAMETERS,'launch_blockers':list(LAUNCH_BLOCKERS),'actual_execution_performed':False}
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result.get('accepted') is True or result['status'] in ('static_plan_only','prepared_blocked','prepared') else 1


if __name__=='__main__':raise SystemExit(main())
