"""Guarded B delta 1h development gate candidate. No real launch is enabled yet.

Preparation freezes bytes and never imports a factory/model transport. The
private execution/readback code is supplied for review and tiny fixtures only.
The new protocol lacks actual installation/test anchors, so preparation and execution
remain unavailable until root binds those real results. No automatic launch occurs.
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
import shutil
import stat
import sys
import time
import traceback

from .offline_pilot import ROOT, DATA, VENDOR, _runtime, _origin_git, _git_pointer, _serial_lock
from .offline_A_gate_v3 import AUDIT_DEPENDENCIES, _active_with_finalizers
from .B_delta_gate_v3 import _ledger_domain
from .model_process_guard import run_guarded, verify_lifecycle

SCHEMA = 'smt-fullfab-B-delta-gate-v6'
RUN_ID = 'B_1701_1h_delta_v6'
PROTOCOL = 'configs/smt_fullfab/B_delta_1h_v6.protocol.json'
AREA = 'runs/smt_fullfab_B_delta_gate'
LEDGER = 'progress/smt_fullfab/model_ledger.jsonl'
APPROVAL = 'configs/smt_fullfab/stage2_probe.approved.json'
WAIVER = 'configs/smt_fullfab/research_limit_waiver.approved.json'
CHILD_SECONDS, OUTER_SECONDS, READBACK_SECONDS, RESTORE_SECONDS = 21600, 22200, 600, 180
TRACE_BYTES, MAX_BYTES, MIN_FREE_BYTES, RSS_BYTES = 2*1024**3, 16*1024**3, 40*1024**3, 8*1024**3
PRIOR_ATTEMPTS, PRIOR_UNKNOWN = 584, 4
ORIGINAL_LEDGER_SHA256 = 'e407386eef8364b19dcd4f1d0ec7814d915514e851baa15648d801b730e397f3'
HISTORICAL_STOP_PREFLIGHT_SHA256 = 'f6db0e85a945ec390a256fedca1c11400bbda096dc06ca852a1e775f0c780eed'
MEASURED_DECISION_SHA256 = 'cebda1aecae6b8a648b2509f70a194dc7957a3be1846fa56cda31c76cd6a1ddf'
CLI_PATH = '/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex'
CLI_EXECUTABLE = '/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'
SOURCE_CONVENTION = 'sha256(json.dumps(relative_path_to_sha256,sort_keys=True,separators=(comma,colon),ensure_ascii=True,allow_nan=False).encode(utf-8))'
PARAMETERS = {'run_id': RUN_ID, 'scenario': 1701, 'seconds': 3600,
    'wall_seconds': 21600.0, 'max_log_bytes': MAX_BYTES,
    'max_trace_bytes': TRACE_BYTES, 'page_chars': 45000}
LAUNCH_BLOCKERS = ()  # Root-approved integration; unfilled actual prerequisite anchors still prohibit prepare/execute.


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
            and protocol.get('execute_now') is False and same(protocol.get('run_parameters'), PARAMETERS), 'fixed cold B1h protocol differs')
    limits = {'child_seconds': CHILD_SECONDS, 'outer_seconds': OUTER_SECONDS,
        'readback_seconds': READBACK_SECONDS, 'restore_seconds_within_readback': RESTORE_SECONDS,
        'trace_bytes': TRACE_BYTES, 'run_scratch_campaign_bytes': MAX_BYTES,
        'minimum_free_bytes': MIN_FREE_BYTES, 'maximum_child_peak_rss_bytes': RSS_BYTES,
        'rss_is_hard_guard': False, 'minimum_preserved_prior_model_attempts': PRIOR_ATTEMPTS,
        'minimum_preserved_prior_unknown_calls': PRIOR_UNKNOWN, 'serial_only': True,
        'model': 'gpt-6-astra', 'reasoning_effort': 'medium', 'global_max_calls': None, 'global_max_tokens': None,
        'per_call_timeout_seconds': 180, 'solver_seconds': 0, 'constructor_seconds': 0,
        'plan_seconds': 14400, 'lookahead_depth': 2, 'period_seconds': 1800, 'period_is_absolute': True}
    require(same(protocol.get('limits'), limits), 'registered capacity/authorization limits differ')
    anchors=protocol.get('prerequisite_sha256');roles=protocol.get('prerequisite_roles')
    require(type(anchors) is dict and anchors, 'prerequisite receipts required')
    require(protocol.get('original_ledger_sha256')==ORIGINAL_LEDGER_SHA256,'fixed original ledger prefix differs')
    require(anchors.get(roles.get('measured_decision'))==MEASURED_DECISION_SHA256,'measured decision original SHA differs')
    for name,sha in anchors.items():
        require(type(name)is str and not Path(name).is_absolute() and '..' not in Path(name).parts
                and type(sha)is str and len(sha)==64 and all(x in '0123456789abcdef' for x in sha), 'invalid prerequisite anchor')
    require(type(roles)is dict and set(roles)=={'endpoint_tests','installation_manifest','installation_review','guard_tests','transport_tests','component_first_checks','component_remaining','performance_entry_tests','measured_decision','admission_tests','admission_readonly'}
            and all(name in anchors for name in roles.values()), 'complete prerequisite roles required')
    require(type(protocol.get('additional_frozen_files'))is list and all(type(name)is str
            and not Path(name).is_absolute() and '..' not in Path(name).parts
            for name in protocol['additional_frozen_files']), 'supplemental frozen scripts must be relative files')
    return dict(PARAMETERS)


def prerequisite_proof(root, protocol):
    """Bind previous component evidence; never treat it as this gate's tests."""
    objects={name:read_json(root/name,sha)[0] for name,sha in protocol['prerequisite_sha256'].items()}
    roles=protocol['prerequisite_roles']
    counts=protocol.get('prerequisite_test_counts',{})
    require(set(counts)=={'endpoint_tests','guard_tests','transport_tests'} and all(type(n)is int and n>0 for n in counts.values()),'new installed integration test counts must be preregistered')
    for role,count in counts.items():
        tests=objects[roles[role]]
        require(tests.get('all_passed')is True and tests.get('original_inputs_unchanged')is True
                and sum(row['tests_run'] for row in tests['records'])==count
                and all(row['returncode']==0 and row['timed_out']is False for row in tests['records'])
                and all(tests.get(key)==0 for key in ('model_calls','solver_calls','actual_factory_runs')),
                'previous component tests missing/failed')
    verify_component_basis(objects,roles)
    installation=objects[roles['installation_manifest']];review=objects[roles['installation_review']]
    require(review.get('blocking_findings')==[] and review['candidate_handoff']=={
        'path':roles['installation_manifest'],'sha256':protocol['prerequisite_sha256'][roles['installation_manifest']]}, 'installation review is unbound/blocked')
    for name,record in installation['owned_files'].items():
        if name.startswith('src/'):
            read_file(root/name,expected_sha256=record['sha256'])
            require(review['candidate_files'][name]['sha256']==record['sha256'], 'reviewed installed source differs')
    for name,sha in review['observed_external_dependencies'].items():
        read_file(root/name,expected_sha256=sha)
    return {'verified_prerequisites':dict(protocol['prerequisite_sha256']),
            'component_tests_only_not_new_gate_validation':True,'launch_blockers':list(LAUNCH_BLOCKERS)}


def verify_component_basis(objects,roles):
    """Use only the named successful rows; earlier failed attempts stay archived."""
    first=objects[roles['component_first_checks']]; remaining=objects[roles['component_remaining']]
    require(first.get('sources_unchanged')is True and remaining.get('sources_unchanged')is True,
            'original component source fence missing')
    total=0
    for report,expected in ((first,{'workflow':24,'store':33}),
                            (remaining,{'bridge_controller_corrected_fixture':26,'telemetry':17,'timed_runtime':21,'original_task_benchmark':35})):
        for suite,count in expected.items():
            selected=[r for r in report['rows'] if r['suite']==suite]
            require(len(selected)==1,'missing/duplicate original component suite')
            row=selected[0]
            require(row.get('passed')is True and row.get('returncode')==0 and row.get('timed_out')is False
                    and row.get('expected_tests')==count and len(row['unittest_reports'])==1
                    and row['unittest_reports'][0][0]==str(count),'component suite not actually passed')
            total+=count
    def tiny(report,count):
        require(report.get('passed')is True and report.get('returncode')==0 and report.get('timed_out')is False
                and len(report['unittest_reports'])==1 and report['unittest_reports'][0][0]==str(count), 'tiny evidence failed/count differs')
    tiny(objects[roles['performance_entry_tests']],8);total+=8
    require(total==164,'original distinct component total differs')
    decision=objects[roles['measured_decision']]
    require(decision.get('schema')=='smt-B-incremental-measured-integration-decision-v1'
            and decision.get('all_new_distinct_tests_passed')==164 and decision.get('new_B_started')is False
            and {x['completed_original_requests'] for x in decision['measurements']}=={1,8,16}
            and all(x.get('equivalent')is True for x in decision['measurements']), 'engineering decision does not bind original-TASK equivalence')
    tiny(objects[roles['admission_tests']],26)
    pre=objects[roles['admission_readonly']]
    require(pre.get('valid')is True and pre.get('ledger_unchanged')is True and pre.get('new_registration')is False
            and pre.get('new_models')==pre.get('ledger_writes')==0 and pre.get('ledger_sha256')==HISTORICAL_STOP_PREFLIGHT_SHA256
            and pre['original_full_prefix_audit']=={**pre['original_full_prefix_audit'],'errors':[],'missing_evidence':[]}, 'actual original stopped-prefix preflight is absent')
    return total


def input_paths(root, protocol):
    paths = []
    for name in ('src', VENDOR, DATA):
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


def source_inputs(inputs):
    return {name:sha for name,sha in inputs.items() if name.startswith(('src/',VENDOR+'/',DATA+'/'))
            or (Path(name).parent==Path('.') and Path(name).name.startswith('requirements'))}


# Small names retained by the copied B verifier; all reads use the bound reader.
def _sha(path): return read_file(path)[1]['sha256']
def _read_bound_json(path, expected): return read_json(path, expected)[0]
def _read(path): return read_json(path)[0]
_digest = digest
_strict = strict


def runtime_capture():
    return {'python': _runtime(), 'model_cli': {name: {'declared_path': path,
        'resolved_path': str(Path(path).resolve()), **read_file(Path(path).resolve())[1]}
        for name, path in (('wrapper', CLI_PATH), ('executable', CLI_EXECUTABLE))}}


def ledger_preflight(raw, root, *, require_unused=True):
    require(hashlib.sha256(raw).hexdigest()==ORIGINAL_LEDGER_SHA256,'original pre-admission ledger bytes changed; no re-anchoring')
    rows = [strict(line) for line in raw.splitlines() if line.strip()]
    require(all(type(row) is dict for row in rows), 'original ledger rows must be objects')
    approval = read_json(root/APPROVAL)[0]; waiver = read_json(root/WAIVER)[0]
    require(same([r['approval'] for r in rows if r.get('event') == 'approval'], [approval]), 'original approval differs')
    require(same([r['amendment'] for r in rows if r.get('event') == 'research_limit_waiver'], [waiver]), 'research waiver differs')
    starts = [r for r in rows if r.get('event') in ('reserve', 'solver_reserve', 'constructor_reserve')]
    ends = [r for r in rows if r.get('event') in ('finish', 'solver_finish', 'constructor_finish')]
    ids, done = [r['call_id'] for r in starts], [r['call_id'] for r in ends]
    require(len(ids)==len(set(ids)) and len(done)==len(set(done)) and set(done)<=set(ids), 'duplicate/orphan original resource calls')
    from .B_incremental_v2 import stopped_admission
    target=str((root/'runs/smt_fullfab_stage2'/RUN_ID).resolve())
    stopped=stopped_admission.preflight_stopped_pending(rows,root=root,target_run_id=target)
    require(set(ids)-set(done)==set(stopped['allowed_pending_call_ids']), 'pending outside original stopped evidence')
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
                        require(str(path) != target and Path(target) not in path.parents, 'new B1h target already registered; no retry')
    return {'prefix_sha256': hashlib.sha256(raw).hexdigest(), 'prefix_bytes': len(raw),
            'original_model_attempts': counts, 'original_unknown_call_ids': unknown,
            'stopped_pending':stopped,'original_raw_pending_call_ids':sorted(set(ids)-set(done))}


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
        campaign.mkdir(parents=True, exist_ok=False); frozen = campaign/'frozen'; frozen.mkdir()
        try:
            stop_copies=freeze_stop_sources(campaign,prior_proof['stopped_pending']['stop_evidence'])
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
                'source_sha256': digest(source_inputs(inputs)), 'source_hash_convention': SOURCE_CONVENTION,
                'prior_ledger': prior_proof, 'stopped_source_copies':stop_copies,
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
    require(same(manifest['config'], PARAMETERS)
            and manifest.get('source_sha256')==digest(source_inputs(manifest['frozen_input_sha256']))
            and manifest.get('source_hash_convention')==SOURCE_CONVENTION
            and manifest.get('run_id')==RUN_ID and manifest.get('output_directory')==str(root/'runs/smt_fullfab_stage2'/RUN_ID)
            and number(manifest.get('prepare_wall_seconds')), 'fixed B1h config/source/path differs')
    for name in ('runs', 'progress'):
        require((frozen/name).is_symlink() and (frozen/name).resolve() == root/name, 'actual run/ledger mapping changed')
    require(manifest['actual_ledger_path'] == str(root/LEDGER) and _origin_git(frozen)==manifest['origin_git_head'], 'actual shared ledger/git pointer changed')
    verify_stop_sources(campaign,manifest)
    require(manifest['prior_ledger']['prefix_sha256']==ORIGINAL_LEDGER_SHA256,'frozen prefix lost its original authority')
    prior, receipt = read_file(campaign/'ledger_at_prepare.jsonl', expected_sha256=manifest['prior_ledger']['prefix_sha256'], keep_bytes=True)
    require(receipt['bytes'] == manifest['prior_ledger']['prefix_bytes'], 'historical prefix truncated')
    live, _ = read_file(root/LEDGER, keep_bytes=True); require(live.startswith(prior), 'global research ledger reset')
    prerequisite_proof(frozen, protocol)
    if for_execution:
        require(runtime_capture() == manifest['runtime'] and sys.executable == manifest['launcher_executable'], 'runtime changed')
        for name in ('B_delta_gate_v6.py','B_delta_gate_v3.py','offline_pilot.py','offline_A_gate_v3.py','model_process_guard.py'):
            require(read_file(Path(__file__).with_name(name))[1]['sha256']==manifest['frozen_input_sha256']['src/smt_fullfab/'+name], 'gate must use frozen reviewed implementation/helpers')


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


def freeze_stop_sources(campaign,proof):
    copies={};base=Path(campaign)/'stopped_source';base.mkdir()
    for index,(name,ref) in enumerate(sorted(proof['refs'].items())):
        raw,observed=read_file(name,expected_sha256=ref['sha256'],keep_bytes=True)
        require(same(observed,ref),'original stopped source identity changed before copy')
        relative='stopped_source/'+str(index).zfill(3)+'.json'
        write_new(Path(campaign)/relative,raw,raw=True);(Path(campaign)/relative).chmod(0o444)
        copies[name]={'copy':relative,**ref}
    return copies


def verify_stop_sources(campaign,manifest):
    refs=manifest['prior_ledger']['stopped_pending']['stop_evidence']['refs']
    copies=manifest['stopped_source_copies'];require(set(copies)==set(refs),'stopped source inventory differs')
    result={}
    for name,ref in refs.items():
        copy=copies[name];require(same({k:copy[k] for k in ref},ref),'copied original stop receipt differs')
        require(type(copy['copy'])is str and Path(copy['copy']).parent==Path('stopped_source'),'unsafe stopped copy path')
        _,original=read_file(name,expected_sha256=ref['sha256'])
        require(same(original,ref),'original stopped source identity/bytes changed')
        _,retained=read_file(Path(campaign)/copy['copy'],expected_sha256=ref['sha256'])
        require(retained['bytes']==ref['bytes'],'stopped copy byte count differs')
        result['stopped_original/'+Path(name).relative_to(manifest['origin_root']).as_posix()]=ref['sha256']
    return result


def evidence(campaign, run, *, include_outer=False):
    result={prefix+'/'+p.relative_to(base).as_posix(): read_file(p)[1]['sha256']
            for prefix,base in (('campaign', Path(campaign)), ('run', Path(run)))
            for p in files(base, campaign=prefix == 'campaign') if p != Path(campaign)/'acceptance.json'
            and (include_outer or prefix!='campaign' or (base/'outer_process') not in p.parents)}
    manifest=read_json(Path(campaign)/'manifest.json',result['campaign/manifest.json'])[0]
    result.update(verify_stop_sources(campaign,manifest))
    return result


def total_bytes(campaign, run):
    manifest=read_json(Path(campaign)/'manifest.json')[0]
    verify_stop_sources(campaign,manifest)
    external=sum(ref['bytes'] for ref in manifest['prior_ledger']['stopped_pending']['stop_evidence']['refs'].values())
    return external+sum(p.stat().st_size for p in files(campaign, campaign=True)+files(run))


def bind_first(verified, final):
    """Original verified anchors remain authoritative; never adopt later bytes."""
    require(type(verified) is dict and verified, 'original verification anchors missing')
    require(all(final.get(k) == v for k,v in verified.items()), 'verified evidence changed before acceptance')
    require({k:v for k,v in final.items() if k.startswith('run/')} ==
            {k:v for k,v in verified.items() if k.startswith('run/')}, 'raw run inventory changed after verification')


def bind_receipts(verified, final):
    """Small late-produced proofs must retain their first parsed raw SHA too."""
    require(all(final.get(name) == sha for name,sha in verified.items()), 'first parsed phase proof changed before acceptance')


def _final_ledger(run, manifest, expected_sha, registration_id):
    saved, _ = read_file(run/'ledger_final.jsonl', expected_sha256=expected_sha, keep_bytes=True)
    live, _ = read_file(manifest['actual_ledger_path'], keep_bytes=True)
    require(live.startswith(saved), 'real ledger no longer preserves final historical prefix')
    parse_rows = lambda raw: [strict(line) for line in raw.splitlines() if line.strip()]
    require(same(_ledger_domain(parse_rows(saved), run, registration_id),
                 _ledger_domain(parse_rows(live), run, registration_id)), 'same run/registration/call acquired suffix; do not re-anchor')


def _checkpoint(run,reference,inputs):
    from .environment import VERSION,snapshot_dependencies
    require(type(reference)is dict and set(reference)=={'path','state_sha256','file_sha256'} and reference['path']=='checkpoint.json','checkpoint reference invalid')
    checkpoint=_read_bound_json(run/'checkpoint.json',reference['file_sha256']);state=checkpoint['state']
    require(checkpoint.get('schema')=='smt-fullfab-snapshot-1' and checkpoint.get('version')==VERSION
        and checkpoint.get('state_sha256')==reference['state_sha256']==_digest(state)
        and checkpoint.get('implementation_sha256')==snapshot_dependencies()
        and checkpoint.get('physics_sha256')==inputs['src/smt/environment.py'],'checkpoint schema/state/dependencies differ')
    require(set(state)==set(('seed','horizon','t','seq','dispatch_id','decisions','releases','completed','finished','wait_until',
        'lots','machine_state','jobs','calendars','pm_counters','queue_area','last_area_t','manifest','plan','observation_start',
        'q','waiting','processing_by_machine','stats','executed_tasks','plan_versions','trace')),'checkpoint state fields incomplete/extra')
    require(type(state['seed'])is int and state['finished'] is True and state['t']==state['horizon']==3600 and state['seed']==1701 and state['observation_start']==0,'checkpoint is not original full cold window')
    data={Path(k).name:v for k,v in inputs.items() if k.startswith(DATA+'/')}
    require(checkpoint['data_hashes']==state['manifest']['data_hashes']==data,'checkpoint source data differs')
    count=0
    with (run/'trace.jsonl').open('rb') as stream:
        for line in stream:
            if not line.strip():continue
            require(count<len(state['trace']) and same(_strict(line),state['trace'][count]),'checkpoint history differs from raw trace')
            count+=1
    require(count==len(state['trace']) and count>0 and state['trace'][-1]['kind']=='terminal','checkpoint omits/adds raw trace')
    return {'state_sha256':checkpoint['state_sha256'],'file_sha256':reference['file_sha256'],'trace_events':count,'restoration_executed':False}


def verify_timing_evidence(run,result,verified,version):
    original=verified['run/timing.jsonl']
    raw,_=read_file(run/'timing.jsonl',expected_sha256=original,keep_bytes=True)
    rows=[strict(line) for line in raw.splitlines() if line.strip()]
    require(rows and rows[-1].get('schema')==version+'-timing','complete final timing summary required')
    timing=result.get('timing',{});summary=rows[-1];spans=rows[:-1]
    require(timing.get('sha256')==original and same(timing.get('summary'),summary)
            and timing.get('state',{}).get('failed')is False and timing['state'].get('closed')is True
            and timing.get('model_guard_time_not_added_again')is True,'timing result/original summary differs')
    require(type(summary.get('span_count'))is int and summary['span_count']==len(spans),'timing span count differs')
    for key in ('start_ns','end_ns','scope_wall_ns','unattributed_ns'):
        require(type(summary.get(key))is int and summary[key]>=0,'timing integer boundary required')
    totals={key:0 for key in summary['leaf_stage_ns']};previous=summary['start_ns']
    for index,row in enumerate(spans,1):
        require(row.get('schema')==version+'-span' and type(row.get('span_id'))is int and row['span_id']==index,'timing span identity/order differs')
        require(row.get('stage')in totals and all(type(row.get(k))is int and row[k]>=0 for k in ('start_ns','end_ns','duration_ns')),'invalid leaf stage/time')
        require(previous<=row['start_ns']<=row['end_ns']<=summary['end_ns'] and row['duration_ns']==row['end_ns']-row['start_ns'],'overlapping/inconsistent leaf span')
        totals[row['stage']]+=row['duration_ns'];previous=row['end_ns']
    require(all(type(v)is int and v>=0 for v in summary['leaf_stage_ns'].values()) and same(totals,summary['leaf_stage_ns']),'leaf sum differs')
    require(summary['end_ns']-summary['start_ns']==summary['scope_wall_ns']==sum(totals.values())+summary['unattributed_ns'],'wall partition differs')
    require(summary.get('cpu_time_measured')is False and summary.get('child_reported_time_additive')is False and summary.get('final_sink_publication_included')is False,'timing scope misrepresented')
    return summary


def verification_payload(campaign,manifest,first):
    """Frozen subprocess: read-only audits, no recovery/model/physical execution."""
    from .B_incremental_v2 import controller as d
    from . import budget
    from .stream_audit_bundle import read_bundle
    root=Path(manifest['origin_root']);run=Path(manifest['output_directory']).resolve();inputs=manifest['frozen_input_sha256']
    d.ROOT=root;budget.ROOT=root;d.DEFAULT_LEDGER=root/LEDGER
    verified=first
    bind_first(first,evidence(campaign,run))
    result_sha=verified['run/result.json'];result=_read_bound_json(run/'result.json',result_sha)
    def bound(name,expected=None):
        digest=expected or verified['run/'+name]
        require(verified.get('run/'+name)==digest,'validated file differs from initial readback anchor')
        return _read_bound_json(run/name,digest)
    cfg=bound('config.json');source=bound('source_manifest.json');provenance=bound('provenance.json')
    expected={'schema':d.SCHEMA,'arm':'B','run_id':RUN_ID,'seed':1701,'seconds':3600,'source_sha256':manifest['source_sha256'],
        'max_calls':None,'max_tokens':None,'per_call_timeout_seconds':180,'wall_seconds':float(CHILD_SECONDS),
        'max_log_bytes':MAX_BYTES,'max_trace_bytes':TRACE_BYTES,'page_chars':45000,'plan_seconds':14400,'lookahead_depth':2,
        'period_seconds':1800,'solver_budget_seconds':0,'constructor_enabled':False,'audit_mode':'stream','snapshot_mode':'stream',
        'cold_start_only':True,'automatic_retry':False,'formal':False,'budget_id':_read(Path(__file__).parents[2]/APPROVAL)['budget_id'],
        'amendment_id':_read(Path(__file__).parents[2]/WAIVER)['amendment_id'],'resource_acceptance_requires_external_gate':True,
        'timing_schema':d.durable.timing.telemetry.VERSION,'timing_file':'timing.jsonl',
        'timing_scope_start':'after create-new config/claim/source/index; before original budget registration and environment',
        'timing_is_partial_leaf_wall_partition_not_cpu_or_whole_process':True,
        'stopped_pending_admission_schema':d.stopped_admission.SCHEMA}
    require(same(cfg,expected) and same(result.get('config'),cfg) and result.get('identity')==_digest(cfg),'controller config/identity differs')
    verify_timing_evidence(run,result,verified,d.durable.timing.telemetry.VERSION)
    diagnosis=bound('stopped_admission.json')
    require(source.get('files')==source_inputs(inputs) and source.get('source_sha256')==manifest['source_sha256']
        and source.get('canonical_hash_convention')==SOURCE_CONVENTION,'controller source inventory differs')
    sources={k:v for k,v in inputs.items() if (Path(k).parent.as_posix() in ('src/smt','src/smt_fullfab') or k.startswith('src/smt_fullfab/B_incremental_v2/') or k in ('src/smt_fullfab/B_incremental_v1/stopped_admission.py','src/smt_fullfab/B_incremental_v1/__init__.py')) and k.endswith('.py')}
    require(provenance.get('source_sha256')==sources and provenance.get('requirements_sha256')==inputs['requirements.lock']
        and provenance.get('git_commit')==manifest['origin_git_head'],'controller provenance differs')
    for name,digest in {**sources,'src/__init__.py':inputs['src/__init__.py']}.items():
        require(verified.get('run/source_snapshot/'+name)==digest and _sha(run/'source_snapshot'/name)==digest,'saved source bytes differ')
    require(result.get('status')=='completed' and result.get('failure') is None and result.get('finalization_errors')==[]
        and result.get('accepted') is False and result.get('formal') is False and result.get('simulation_seconds')==3600
        and result.get('audit_valid') is True and result.get('delta_attribution_valid') is True
        and result.get('solver_calls')==result.get('constructor_calls')==0,'controller terminal is not complete/valid B')
    require(type(result.get('end_to_end_wall_seconds'))in(int,float) and math.isfinite(result['end_to_end_wall_seconds'])
        and 0<=result['end_to_end_wall_seconds']<=CHILD_SECONDS and result.get('resource_overrun') is not True,'controller resource result invalid')
    bundle_ref=result['audit_bundle'];require(set(bundle_ref)=={'path','manifest_sha256'} and bundle_ref['path']=='audit_bundle','unsafe/missing audit reference')
    checked=read_bundle(run/'audit_bundle',expected_manifest_sha256=bundle_ref['manifest_sha256'])
    bundle=bound('audit_bundle/audit_bundle.json',bundle_ref['manifest_sha256'])
    for name,metadata in bundle['members'].items():require(verified.get('run/audit_bundle/'+name)==metadata['sha256'],'bundle member differs from initial anchor')
    receipt=bundle['source_receipt'];trace_sha=receipt['sha256'];require(verified.get('run/trace.jsonl')==trace_sha,'trace differs from initial anchor')
    require(_sha(run/'trace.jsonl')==trace_sha and (run/'trace.jsonl').stat().st_size==receipt['byte_count']<=TRACE_BYTES,'trace source receipt/cap differs')
    summary=bundle['summary'];envelope=bundle['envelope']
    require(checked.get('storage_verified') is True and checked.get('semantic_replay_performed') is False
        and checked['summary']==summary and checked['source_receipt']==receipt
        and bundle['dependency_sha256']=={k:inputs[k] for k in AUDIT_DEPENDENCIES}
        and bundle['bundle_source_sha256']==inputs['src/smt_fullfab/stream_audit_bundle.py']
        and envelope.get('terminal_at_eof') is True and envelope.get('first_time')==0 and envelope.get('last_time')==envelope.get('horizon')==3600
        and envelope.get('receipt')==receipt and bundle.get('configuration')=={'window_start':0,'priority_weights':None,'require_terminal':True,'verify_data_dir_supplied':True},'audit bundle terminal/dependencies differ')
    source_report=bound('audit_bundle/source.json',bundle['members']['source.json']['sha256'])
    require(all(summary.get(k)is True for k in ('valid','source_valid','opportunity_valid','physical_valid','actual_dispatch_provenance_complete',
        'complete_physical_window_certified','absence_of_unreported_legal_demand_certified','verified_input_hashes'))
        and source_report.get('valid')is True and source_report.get('errors')==[]
        and source_report.get('production_machine_count')==source_report.get('declared_control_machine_count')==913
        and type(source_report.get('production_machine_count'))is int and type(source_report.get('declared_control_machine_count'))is int
        and source_report.get('declared_full_factory_domain')is True
        and source_report.get('_source_evidence',{}).get('source_receipt')==receipt
        and source_report.get('_source_evidence',{}).get('complete_jsonl_pass')is True
        and result['metrics']==summary['metrics'],'complete 913-machine physical/opportunity/source audit absent')
    audit=bound('delta_attribution_audit.json');index_sha=result['index_sha256'];require(verified.get('run/delta_index.jsonl')==index_sha,'index differs from initial anchor')
    replayed=d.audit_delta_run(run,expected_index_sha256=index_sha,expected_source_sha256=manifest['source_sha256'],expected_trace_sha256=trace_sha)
    require(audit.get('valid')is True and same(replayed,audit) and audit.get('source_receipt')==receipt
        and audit.get('index_sha256')==index_sha and audit.get('source_sha256')==manifest['source_sha256'],'independent delta attribution replay differs')
    rows=d.read_index(run/'delta_index.jsonl',expected_sha256=index_sha)
    resources=d.read_account_evidence(run,rows[-1]['payload']['account_report_sha256'])
    account=resources['account'];registration=bound('resource_registration.json')
    ledger_raw,_=read_file(run/'ledger_final.jsonl',expected_sha256=resources['ledger_sha256'],keep_bytes=True)
    diagnoses=[strict(line) for line in ledger_raw.splitlines() if line.strip() and strict(line).get('event')==d.stopped_admission.EVENT]
    require(len(diagnoses)==1 and same(diagnosis,diagnoses[0]) and diagnosis.get('run_id')==str(run),'saved stopped diagnosis differs from original ledger')
    for name,digest in (('ledger_final_account.json',rows[-1]['payload']['account_report_sha256']),('ledger_final.jsonl',resources['ledger_sha256'])):
        require(verified.get('run/'+name)==digest and _sha(run/name)==digest,'final real ledger account changed')
    require(registration['run_id']==str(run) and registration['arm']=='B' and registration['scenario']==1701
        and registration['window_seconds']==3600 and registration['solver_seconds']==0 and registration['wall_seconds']==CHILD_SECONDS
        and registration['max_log_bytes']==MAX_BYTES,'original registration scope differs')
    count=account['attempts'];require(type(count)is int and count>0 and all(result.get(k)==count for k in ('model_calls','local_bridge_attempts','returned_bridge_attempts','next_local_model_index'))
        and result.get('model_account')==account and result.get('pending_call_ids')==account['pending']==[]
        and result.get('unknown_usage_call_ids')==account['unknown_completed']==audit['unknown_usage_call_ids']
        and result.get('reserve_call_ids')==resources['reserve_call_ids']==audit['reserve_call_ids']
        and audit['model_calls']==count and result['plans']==len(audit['plans'])>0,'original model/cost counts differ')
    require(not resources['solver_call_ids'] and not resources['constructor_call_ids'],'B used forbidden optimization/construction')
    require({p.name for p in run.glob('model_*')}=={f'model_{i:05d}' for i in range(count)}
        and {p.name for p in run.glob('call_*')}=={f'call_{i:05d}' for i in range(count)}
        and {p.name for p in run.glob('plan_*')}=={f'plan_{i:05d}' for i in range(result['plans'])},'orphan/missing call or plan directories')
    for row in rows:
        if row['event']=='call_finished':
            item=row['payload'];intent=bound(f"call_{item['model_index']:05d}/intent.json",item['intent_sha256'])
            require(intent['config']['codex_binary']==CLI_PATH,'call used a different model CLI runtime')
        if row['event']=='plan_closed':
            p=row['payload'];require(verified.get(f"run/plan_{p['plan_index']:05d}/durable/ledger.sqlite3")==p['durable_prefix']['database_sha256'],'store differs from original final prefix')
    checkpoint=_checkpoint(run,result['checkpoint'],inputs);require(verified.get('run/checkpoint.json')==checkpoint['file_sha256'],'checkpoint differs from initial anchor')
    lifecycle=verify_model_lifecycles(run,manifest,first,count)
    bind_first(first,evidence(campaign,run))
    _final_ledger(run,manifest,resources['ledger_sha256'],registration['registration_id'])
    return {'valid':True,'result':result,'verified_evidence_sha256':verified,'registration_id':registration['registration_id'],
        'checkpoint':checkpoint,'first_trace_receipt':receipt,'ledger_sha256':resources['ledger_sha256'],
        'result_wall_seconds':result['end_to_end_wall_seconds'],'model_lifecycle_evidence_sha256':lifecycle,
        'backend_identity_independently_proven':False,'physical_reexecution_performed':False}


def verify_model_lifecycles(run, manifest, first, count):
    """Additional per-call guard verification, independently bound to first bytes."""
    anchors={};inputs=manifest['frozen_input_sha256']
    def bound(name): return read_json(Path(run)/name,first['run/'+name])[0]
    for index in range(count):
        relative=f'model_{index:05d}'
        request=bound(relative+'/request.json');result=bound(relative+'/result.json')
        config=request['config'];command=bound(relative+'/command.json')['argv']
        require(config['model']=='gpt-6-astra' and config['reasoning_effort']=='medium'
                and number(config['timeout_seconds'],minimum=1,maximum=180)
                and config['codex_binary']==CLI_PATH and config['ledger_path']==manifest['actual_ledger_path'], 'model runtime/config differs')
        guard=verify_lifecycle(Path(run)/relative,expected_command=command,
            expected_timeout=config['timeout_seconds'],expected_call_id=request['call_id'],
            expected_fingerprint=request['request_fingerprint'],expected_evidence=result['process_guard'])
        require(guard['guard_source_sha256']==inputs['src/smt_fullfab/model_process_guard.py']
                and same(guard['command_returncode'],result['returncode'])
                and same(guard['timed_out'],result['timed_out']) and guard['launch_error']==result['launch_error'], 'model lifecycle/result differs')
        for name,sha in guard['files_sha256'].items():
            key='run/'+relative+'/process_guard/'+name
            require(first.get(key)==sha,'model lifecycle changed from first anchor');anchors[key]=sha
        for name,sha in guard['output_files_sha256'].items():
            key='run/'+relative+'/'+name
            require(first.get(key)==sha,'model raw output changed from first anchor')
            if sha is not None:anchors[key]=sha
    return anchors


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
    require(env.seed == 1701 and env.t == env.horizon == 3600 and env.finished is True and env.observation_start == 0
            and len(env.physical) == 913, 'restored checkpoint is not the full cold B1h window')
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
    code = "import sys;sys.path.insert(0,sys.argv[1]);from src.smt_fullfab.B_delta_gate_v6 import _worker;raise SystemExit(_worker(*sys.argv[2:]))"
    return [manifest['launcher_executable'],'-I','-B','-c',code,str(Path(campaign)/'frozen'),
            kind,str(campaign),manifest['identity'],str(first_path or ''),str(proof_path or ''),first_sha,proof_sha]


def _worker(kind, campaign, expected_identity, first_path='', proof_path='', first_sha='', proof_sha=''):
    campaign = Path(campaign); manifest = read_json(campaign/'manifest.json')[0]
    require(manifest['identity'] == expected_identity
            and expected_identity == digest({k:v for k,v in manifest.items() if k!='identity'}), 'worker original manifest differs')
    verify_frozen(campaign,manifest,for_execution=True)
    if kind == 'supervise':
        result=_execute_reviewed(campaign,manifest,_under_outer_guard=True)
        return 0 if result['accepted'] else 1
    if kind == 'run':
        # This private entry is blocked too: importing this draft cannot bypass
        # public execute merely by calling a hidden argv or helper.
        require(not LAUNCH_BLOCKERS, 'B1h launch blocked: '+'; '.join(LAUNCH_BLOCKERS))
        from .B_incremental_v2 import controller as d
        from . import budget
        root=Path(manifest['origin_root'])
        # Only runtime routing globals are changed. assert_source's frozen
        # default argument continues to point at the actual frozen checkout.
        d.ROOT=root; budget.ROOT=root; d.DEFAULT_LEDGER=root/LEDGER
        d.APPROVAL=campaign/'frozen'/APPROVAL
        result=d._run_registered(expected_source_sha256=manifest['source_sha256'],**PARAMETERS)
        return 0 if result['status']=='completed' else 1
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
            and number(restored.get('simulation_seconds')) and restored['simulation_seconds']==3600
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
            errors.append({'type':'TotalBytesLimit','message':'retained run+scratch+campaign exceeds16GiB'})
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
    require(not LAUNCH_BLOCKERS, 'B1h launch blocked: '+'; '.join(LAUNCH_BLOCKERS))
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
            'wall_scope':'prepare plus all guarded supervisor phases, supervisor result publication and exit, guard cleanup/wait/readback, final evidence binding; timestamp resampled before final encoding, deadline checked again afterward; final certificate fsync/return measured separately by launching host',
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
            bind_receipts(parsed_proofs,first)
            first_sha=write_new(campaign/'first_verification_anchors.json',first)
            parsed_proofs['campaign/first_verification_anchors.json']=first_sha
            validation_started=time.monotonic()
            remaining=min(READBACK_SECONDS,OUTER_SECONDS-elapsed());require(remaining>0,'no remaining readback budget')
            process=owned_phase(_phase_command(campaign,manifest,'verify',campaign/'first_verification_anchors.json',first_sha=first_sha),
                cwd=campaign/'frozen',output=campaign/'readback_process',timeout=remaining,
                inputs={'manifest':campaign/'manifest.json','first':campaign/'first_verification_anchors.json'},
                output_paths={'verification':campaign/'verification_payload.json'})
            verification_process=process;parsed_proofs.update(phase_anchors(campaign,process,run));check_storage(campaign,run)
            verify_phase(campaign,manifest,process,command=_phase_command(campaign,manifest,'verify',campaign/'first_verification_anchors.json',first_sha=first_sha),maximum=remaining)
            proof,proof_receipt=read_json(campaign/'verification_payload.json')
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
            verify_phase(campaign,manifest,process,command=_phase_command(campaign,manifest,'restore',campaign/'first_verification_anchors.json',campaign/'verification_payload.json',first_sha=first_sha,proof_sha=proof_receipt['sha256']),maximum=remain)
            restored,restored_receipt=read_json(campaign/'restoration_payload.json')
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
        raw=_terminal_encoding(result,total_bytes(campaign,run),elapsed,
            success_validator=lambda value:validate_success(value,manifest,supervisor=True))
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
        require(evidence(campaign,run,include_outer=True)==actual
                and total_bytes(campaign,run)==acceptance['final_total_bytes_including_acceptance'], 'evidence changed during complete acceptance readback')
        read_file(campaign/'acceptance.json',expected_sha256=receipt['sha256'])
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
        require(not LAUNCH_BLOCKERS,'B1h launch blocked: '+'; '.join(LAUNCH_BLOCKERS))
        campaign=ROOT/AREA/RUN_ID;result=execute(campaign,read_json(campaign/'manifest.json')[0])
    elif args.prepare:
        campaign,manifest=prepare();result={'status':'prepared_blocked','campaign':str(campaign),'identity':manifest['identity'],'launch_blockers':list(LAUNCH_BLOCKERS)}
    else:result={'status':'static_plan_only','run_id':RUN_ID,'parameters':PARAMETERS,'launch_blockers':list(LAUNCH_BLOCKERS),'actual_execution_performed':False}
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result.get('accepted') is True or result['status'] in ('static_plan_only','prepared_blocked') else 1


if __name__=='__main__':raise SystemExit(main())
