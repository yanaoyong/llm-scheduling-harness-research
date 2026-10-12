"""Frozen preserved-interaction host; explicit original clock, no automatic retry.

This host publishes evidence only. Actual outer wait, complete process resources
and cumulative root acceptance remain outside this process.
"""
import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
import time
import traceback


def need(value, message):
    if not value:
        raise ValueError(message)


def bound(path, *, keep=False):
    path = Path(path)
    ident = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    parts = []; h = hashlib.sha256()
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode), 'regular original evidence file required')
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
            if keep:
                parts.append(block)
        identity = ident(before)
        need(identity == ident(os.fstat(stream.fileno())) == ident(path.stat()),
             'evidence changed during original read: ' + str(path))
    return h.hexdigest(), identity, b''.join(parts) if keep else None


def sha(path):
    return bound(path)[0]


def write_bytes_new(path, raw):
    with Path(path).open('xb') as stream:
        n = stream.write(raw)
        if type(n) is not int or n != len(raw):
            raise OSError('host evidence short write')
        stream.flush(); os.fsync(stream.fileno())
    expected = hashlib.sha256(raw).hexdigest()
    need(sha(path) == expected, 'published host bytes differ')
    return expected


def new(path, value):
    return write_bytes_new(path, (json.dumps(value, ensure_ascii=False, indent=2,
                                            allow_nan=False) + '\n').encode())


def identities(paths):
    result = {}
    for path in paths:
        s = Path(path).stat()
        result[str(path)] = (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    return result


def validate_deadlines(manifest, first, hard, soft, *, now):
    remaining = float(manifest['remaining_wall_seconds'])
    prepare = manifest['prepare_wall_seconds']
    need(all(type(v) in (int, float) and math.isfinite(v)
             for v in (first, hard, soft, now, remaining, prepare)), 'finite original deadlines required')
    need(0 < first <= now and prepare >= 0 and remaining > prepare,
         'invalid original clock/preparation/remainder')
    need(hard == first + remaining - prepare - 30.0 and soft == hard - 900.0,
         'deadlines differ from original outer contract')
    need(now + 660.0 < soft, 'insufficient remaining time; no restore or request started')
    return {'first_monotonic': first, 'hard_deadline_monotonic': hard,
            'soft_deadline_monotonic': soft, 'prepare_wall_seconds': prepare,
            'remaining_wall_seconds': remaining, 'terminal_cleanup_reserve_seconds': 900.0,
            'outer_publication_reserve_seconds': 30.0}


def merge_files(*groups):
    """Keep every original hash; overlap is allowed only when exactly identical."""
    result = {}
    for group in groups:
        for path, ref in group.items():
            need(Path(path).is_absolute() and str(Path(path).resolve()) == path,
                 'canonical absolute inventory path required')
            need(type(ref) is dict and set(ref) == {'sha256', 'bytes'}
                 and type(ref['bytes']) is int and ref['bytes'] >= 0,
                 'inventory SHA/byte pair required')
            need(path not in result or result[path] == ref, 'original inventory collision: ' + path)
            result[path] = dict(ref)
    return result


def main(campaign, expected_manifest, *, first_monotonic, hard_deadline_monotonic,
         soft_deadline_monotonic):
    campaign = Path(campaign).resolve(); manifest_path = campaign/'manifest.json'
    actual, manifest_identity, manifest_raw = bound(manifest_path, keep=True)
    need(actual == expected_manifest, 'original manifest SHA differs')
    manifest = json.loads(manifest_raw); root = Path(manifest['root']).resolve(); frozen = campaign/'frozen'
    need(Path(__file__).resolve().is_relative_to(frozen), 'only registered frozen host may run')
    deadlines = validate_deadlines(manifest, first_monotonic, hard_deadline_monotonic,
                                   soft_deadline_monotonic, now=time.monotonic())
    sys.path.insert(0, str(frozen))
    pins = {str(manifest_path): (expected_manifest, manifest_identity)}
    for name, expected in manifest['runtime_files'].items():
        path = frozen/name; actual, identity, _ = bound(path)
        need(actual == expected, 'frozen source differs: ' + name)
        pins[str(path)] = (actual, identity)
    for name, expected in manifest['parent_inputs'].items():
        path = root/name; actual, identity, _ = bound(path)
        need(actual == expected, 'original parent input differs: ' + name)
        pins[str(path)] = (actual, identity)

    def read_ref(ref):
        path = Path(ref['path']); path = path if path.is_absolute() else root/path
        path = path.resolve(); actual, identity, raw = bound(path, keep=True)
        need(actual == ref['sha256'], 'original reference differs: ' + str(path))
        if str(path) in pins:
            need(pins[str(path)] == (actual, identity), 'original reference was replaced')
        pins[str(path)] = (actual, identity)
        return json.loads(raw)

    def fence():
        need(identities([Path(x) for x in pins]) == {p: v[1] for p, v in pins.items()},
             'frozen runtime or original evidence identity changed')

    original = root/manifest['original_parent']; parent = root/manifest['parent']; segment = root/manifest['segment']
    need(not segment.exists(), 'new preserved segment must not already exist')
    need(segment.parent == root/'runs/smt_fullfab_stage2'
         and segment.name == 'B_1701_1h_delta_v8__preserved_001', 'unique direct stage2 identity required')
    inventory = read_ref(manifest['ancestor_inventory'])
    need(inventory['schema'] == 'smt-B-v8-preserved-attribution-inventory-v1', 'ancestor inventory schema differs')
    ancestors = merge_files(inventory['files'])
    # Exact original hashes remain the anchors. Never replace them with a new read.
    for path, ref in ancestors.items():
        actual, identity, _ = bound(path)
        need(actual == ref['sha256'] and identity[2] == ref['bytes'], 'original ancestor changed: ' + path)
        if path in pins:
            need(pins[path] == (actual, identity), 'original ancestor identity replaced')
        pins[path] = (actual, identity)
    cold = read_ref(manifest['parent_cold_proof'])
    need(cold['valid'] is True and cold['processed_boundary_eligible'] is True
         and cold['parent_run'] == str(parent) and cold['next_unique_model_index'] == 221,
         'original complete parent boundary required')
    channel = read_ref(manifest['parent_channel_proof'])
    need(channel['schema'] == 'smt-B-v8-preserved-parent-channel-proof-v1'
         and channel['valid'] is True and channel['accepted'] is False and channel['errors'] == []
         and channel['parent_run'] == str(parent)
         and channel['parent_cold_proof'] == manifest['parent_cold_proof']
         and channel['parent_ledger_snapshot'] == manifest['parent_ledger_snapshot']
         and channel['interaction_evidence_sha256'] == cold['interaction_evidence_sha256']
         and channel['history_count'] == 33 and set(channel['calls']) == {str(i) for i in range(188,221)},
         'original-source parent channel certificate required before new execution')
    need(all(ancestors.get(path) == ref for path,ref in channel['input_files'].items()),
         'certified original channel input missing from frozen ancestor inventory')
    pc = manifest['preserved_contract']
    need(pc['parent_prefix'] == cold['expected_prefix']
         and pc['parent_store_id'] == cold['parent_store_id']
         and pc['parent_interaction_evidence_sha256'] == cold['interaction_evidence_sha256']
         and pc['expected_bootstrap_sha256'] == cold['bootstrap_canonical_sha256']
         and pc['first_new_model_index'] == 221 and pc['profile'] == 'processed_boundary',
         'preserved contract differs from sealed full original proof')
    need(manifest['attribution_refs_static'] == {'first_new_model_index': 221,
         'continuation_profile': 'processed_boundary'}, 'narrow original attribution profile differs')
    from src.smt_fullfab import budget as original_budget
    from src.smt_fullfab.B_incremental_v3 import controller, transport
    from src.smt_fullfab.B_direct_v8 import bridge as parent_api
    from src.smt_fullfab.B_v8_launch_recovery import admission as original_admission
    from src.smt_fullfab.B_v8_preserved_resume_v1 import admission, controller as segment_controller
    from src.smt_fullfab.B_v8_preserved_resume_v1 import continuation_bridge as api, continuation_store
    from src.smt_fullfab.B_v8_preserved_resume_v1 import continuation_acceptance as acceptance
    original_budget.ROOT = root; controller.ROOT = root
    controller.DEFAULT_LEDGER = root/'progress/smt_fullfab/model_ledger.jsonl'
    ledger_path = controller.DEFAULT_LEDGER
    need(str(ledger_path) not in ancestors, 'mutable actual ledger cannot be an immutable ancestor input')
    # The old pure runtime must remain byte-for-byte its original 243-file config.
    old = manifest['original_runtime_config']
    for name, expected in old['runtime_files'].items():
        need(manifest['runtime_files'].get(name) == expected, 'old runtime byte replaced in new freeze')
    read_ref(old['package'])
    expected_runtime = read_ref(old['expected_runtime_manifest'])
    parent_api.binding.configure_admission(original_admission, package_config=old['package'],
        dependency_paths=[frozen/name for name in old['runtime_files'] if name.endswith('.py')])
    api.configure_runtime(expected_runtime_manifest=expected_runtime)
    clock = {'schema': 'smt-B-v8-preserved-first-clock-v1', 'segment_run_id': str(segment),
             'started_monotonic_seconds': first_monotonic,
             'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    clock_sha = new(campaign/'first_clock.json', clock)
    sources_sha = new(campaign/'runtime_source_manifest.json', manifest['runtime_files'])
    package = {**manifest['package_static'],
        'first_clock': {'path': str(campaign/'first_clock.json'), 'sha256': clock_sha},
        'runtime_source_manifest': {'path': str(campaign/'runtime_source_manifest.json'), 'sha256': sources_sha}}
    package_sha = new(campaign/'recovery_package.json', package)
    package_config = {'path': str(campaign/'recovery_package.json'), 'sha256': package_sha}
    api.binding.configure_admission(admission, package_config=package_config,
        dependency_paths=[frozen/name for name in manifest['runtime_files'] if name.endswith('.py')])
    retained = lambda: sum(p.stat().st_size for base in (campaign, segment) if base.exists()
                           for p in base.rglob('*') if p.is_file())
    Ledger = admission.make_ledger_class(original_budget, package_config=package_config,
        started_monotonic=first_monotonic, retained_bytes_provider=retained)
    ledger = Ledger(ledger_path)
    with ledger._locked() as ledger_rows:
        approvals = [r['approval'] for r in ledger_rows if r['event'] == 'approval']
        need(len(approvals) == 1, 'one original approval required')
        approval = approvals[0]
        checked = admission.preflight_recovery(ledger_rows, approval, root=root, package_config=package_config)
    new(campaign/'admission_preflight.json', checked)
    registration = checked['registration']; remaining = checked['remaining']
    need(float(remaining['runner_wall_seconds']) == float(manifest['remaining_wall_seconds'])
         and remaining['log_bytes'] == manifest['remaining_log_bytes'], 'root and admission resource remainder differ')
    envelope = {'segment_run_id': str(segment), 'parent_run_id': str(parent),
        'remaining_runner_wall_seconds': float(remaining['runner_wall_seconds']),
        'remaining_log_bytes': remaining['log_bytes'], 'per_call_timeout_seconds': 600,
        'registration': registration, 'ledger_path': str(ledger_path)}
    disabled = [str(p) for p in transport._disabled_skills()]
    need(disabled == manifest['disabled_skill_paths'], 'native isolation inventory changed')

    def authority():
        fence()
        return {'ledger_path': str(ledger_path), 'ledger_before_sha256': sha(ledger_path),
            'approval_sha256': original_budget.record_sha256(approval),
            'registration_id': registration['registration_id'],
            'registration_sha256': original_budget.record_sha256(registration), 'disabled_skill_paths': disabled}

    def register(path, expected):
        fence()
        need(Path(path) == segment/'plan_00001/durable/continuation_manifest.json',
             'one first-plan preserved registration only')
        return ledger.register_preserved_segment(str(segment), continuation_manifest_path=path,
                                                expected_continuation_manifest_sha256=expected)

    def invoke(*args, **kwargs):
        fence()
        segment_controller.check_admission_deadline(soft_deadline_monotonic)
        try:
            return transport.call_model(*args, **kwargs, ledger_factory=Ledger)
        finally:
            fence()

    record = {'schema': 'smt-B-v8-preserved-host-result-v1', 'accepted': False, 'parent_status': 'failed',
        'preserved_parent_status': 'failed', 'goal_complete': False, 'manifest_sha256': expected_manifest,
        'package_sha256': package_sha, 'status': 'failed', 'errors': [], 'cost_usd': None,
        'automatic_retry': False, 'deadlines': deadlines, 'prepare_wall_seconds': manifest['prepare_wall_seconds'],
        'resource_measurement_scope': 'prepare once plus original outer clock through host publication; actual outer wait/publication tail remain root-owned'}
    captured = None; account = None

    def capture_account():
        nonlocal captured, account
        raw_sha, identity, raw = bound(ledger_path, keep=True)
        if captured is None:
            write_bytes_new(campaign/'ledger_final.jsonl', raw)
            captured = (raw_sha, identity, raw)
        else:
            need(captured == (raw_sha, identity, raw), 'actual ledger changed after original terminal snapshot')
        rows = [json.loads(x) for x in raw.splitlines()]
        current = admission.audit_admissions(rows, approval, root=root, package_config=package_config)
        if account is None:
            new(campaign/'ledger_final_account.json', current)
            account = current
        else:
            need(acceptance.same(account, current), 'closed terminal admission report changed')
        record.update(ledger_final_sha256=raw_sha, account_sha256=sha(campaign/'ledger_final_account.json'),
            segment_account=current.get('segment_account'), cumulative_parent_segment_account=current.get('recovery_account'))
        need(not current['errors'] and not current['missing_evidence'], 'complete terminal account rejected')
        return current

    try:
        # All cold proof/registration costs already consumed the same original clock.
        segment_controller.check_admission_deadline(soft_deadline_monotonic)
        result = segment_controller.run_segment(str(segment), parent_contract=manifest['parent_contract'],
            preserved_contract=pc, admission=envelope, external_authorization_sha256=package_sha,
            controller=controller, transport_call=invoke, authorization_for_call=authority,
            register_after_continuation=register, started_monotonic=first_monotonic,
            soft_deadline_monotonic=soft_deadline_monotonic,
            physical_source_manifest=manifest['physical_source_manifest'])
        fence(); capture_account()
        need(result['full_window_completed'] and result['status'] == 'completed_pending_external_audit',
             'segment stopped without a complete physical window')
        terminal_files = {}; terminal_identity = {}
        for path in sorted(segment.rglob('*')):
            if path.is_file():
                digest, identity, _ = bound(path)
                terminal_files[str(path)] = {'sha256': digest, 'bytes': identity[2]}
                terminal_identity[str(path)] = identity
        new(campaign/'first_terminal_inventory.json',
            {'schema': acceptance.INVENTORY_SCHEMA, 'files': terminal_files})
        extra = {}
        for path in (manifest_path, campaign/'first_clock.json', campaign/'runtime_source_manifest.json',
                     campaign/'recovery_package.json', campaign/'ledger_final.jsonl',
                     campaign/'ledger_final_account.json'):
            digest, identity, _ = bound(path); extra[str(path)] = {'sha256': digest, 'bytes': identity[2]}
        combined = merge_files(ancestors, terminal_files, extra)
        combined_path = campaign/'attribution_inventory.json'
        combined_sha = new(combined_path, {'schema': acceptance.INVENTORY_SCHEMA, 'files': combined})
        roles = {'controller': controller, 'parent_api': parent_api, 'continuation_api': api,
                 'continuation_store': continuation_store, 'continuation_runtime': parent_api.durable,
                 'fresh_api': api, 'transport': transport, 'admission_module': admission}
        runtime_roles = {}
        for role, module in roles.items():
            path = str(Path(module.__file__).resolve())
            need(path in combined, 'frozen audit source missing from original inventory: ' + role)
            runtime_roles[role] = {'path': path, 'sha256': combined[path]['sha256']}
        indexed = controller.read_index(segment/'resume_index.jsonl', expected_sha256=result['index_sha256'])
        plans = {}
        for row in indexed:
            if row['event'] == 'plan_opened':
                item = row['payload']; path = segment/item['directory']/'durable/continuation_manifest.json'
                digest = item['continuation_manifest_sha256']
                need(combined[str(path)]['sha256'] == digest, 'first original plan manifest anchor differs')
                plans[str(item['plan_index'])] = {'path': str(path), 'sha256': digest}
        refs = {**manifest['attribution_refs_static'], 'schema': acceptance.REFS_SCHEMA,
            'inventory': {'path': str(combined_path), 'sha256': combined_sha},
            'run_paths': {'original': str(original), 'preserved': str(parent), 'new': str(segment)},
            'ledger_snapshot': {'path': str(campaign/'ledger_final.jsonl'), 'sha256': captured[0]},
            'plan_manifests': plans, 'external_authorization_sha256': package_sha,
            'runtime_modules': runtime_roles, 'parent_cold_proof': manifest['parent_cold_proof'],
            'parent_ledger_snapshot': manifest['parent_ledger_snapshot'],
            'parent_channel_proof': manifest['parent_channel_proof']}
        refs_path = campaign/'attribution_sealed_refs.json'; refs_sha = new(refs_path, refs)
        a = acceptance.attribution(segment, parent=original, preserved_parent=parent, controller=controller,
            parent_api=parent_api, continuation_api=api, continuation_store=continuation_store,
            continuation_runtime=parent_api.durable, fresh_api=api, transport=transport,
            ledger_path=ledger_path, admission_module=admission,
            admission_kwargs={'root': root, 'package_config': package_config},
            sealed_refs_path=refs_path, expected_sealed_refs_sha256=refs_sha)
        new(campaign/'attribution.json', a)
        summary, bundle = controller.stream_audit(segment/'physical/trace.jsonl', campaign,
            data_dir=frozen/'data/smt/SMT2020_LVHM', window_start=0.0)
        new(campaign/'physical_audit.json', {'summary': summary, 'bundle': bundle})
        need(a['valid'] and summary['valid'] and summary['complete_physical_window_certified'],
             'complete attribution and full physical audit required')
        need(identities([Path(x) for x in terminal_files]) == terminal_identity,
             'terminal evidence identity changed during independent audits')
        need(all(sha(path) == ref['sha256'] for path, ref in terminal_files.items()),
             'terminal evidence hash changed during independent audits')
        fence()
        record.update(status='completed_pending_outer_resource_check', full_window_completed=True,
            attribution_sha256=sha(campaign/'attribution.json'),
            attribution_sealed_refs_sha256=refs_sha, physical_audit_sha256=sha(campaign/'physical_audit.json'),
            metrics=summary['metrics'], simulation_seconds=3600.0)
    except BaseException as exc:
        record['errors'].append({'type': type(exc).__name__, 'message': str(exc), 'traceback': traceback.format_exc()})
        record['status'] = 'failed'
    finally:
        try:
            # After all expensive terminal reads, recheck exact actual cost-domain bytes.
            capture_account(); fence()
        except BaseException as exc:
            record['status'] = 'failed'
            record['errors'].append({'stage': 'account_or_source_fence', 'type': type(exc).__name__, 'message': str(exc)})
        elapsed = time.monotonic() - first_monotonic
        record['host_wall_seconds_before_publication'] = elapsed
        record['whole_new_stage_seconds_before_publication'] = elapsed + manifest['prepare_wall_seconds']
        record['retained_bytes_before_publication'] = retained()
        if time.monotonic() >= hard_deadline_monotonic or retained() >= manifest['remaining_log_bytes']:
            record['status'] = 'failed'
            record['errors'].append({'stage': 'resources', 'message': 'original cumulative hard deadline or log remainder exhausted'})
        raw = (json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
        if retained() + len(raw) >= manifest['remaining_log_bytes'] or time.monotonic() >= hard_deadline_monotonic:
            record['status'] = 'failed'
            record['errors'].append({'stage': 'publication_resources', 'message': 'result bytes or encoding crossed original allowance'})
            raw = (json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
        write_bytes_new(campaign/'host_result.json', raw)
    print(json.dumps({'status': record['status'], 'accepted': False,
                      'host_result_sha256': sha(campaign/'host_result.json')}), flush=True)
    return 0 if record['status'] == 'completed_pending_outer_resource_check' else 1


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--campaign', required=True)
    p.add_argument('--manifest-sha256', required=True); p.add_argument('--first-monotonic', required=True, type=float)
    p.add_argument('--hard-deadline-monotonic', required=True, type=float)
    p.add_argument('--soft-deadline-monotonic', required=True, type=float)
    args = p.parse_args()
    raise SystemExit(main(args.campaign, args.manifest_sha256, first_monotonic=args.first_monotonic,
        hard_deadline_monotonic=args.hard_deadline_monotonic,
        soft_deadline_monotonic=args.soft_deadline_monotonic))
