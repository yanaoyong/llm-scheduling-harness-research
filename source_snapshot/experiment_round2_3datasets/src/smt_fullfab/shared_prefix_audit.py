"""Independent nonterminal prefix closure at an externally declared T0 < H.

Reuses the unchanged source/opportunity/projection and physical Fold.event;
never invokes Fold.finish, constructs a simulator or invents a terminal event.
Snapshot bytes/trace bytes/state SHA are external anchors. A valid receipt is
legal-prefix and listed-state evidence, not a steady-state, policy-authorship,
whole-private-state, continuation, resource or completed-window certificate.
The full snapshot/current lots still reside in RAM; no long-window claim.
"""
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from . import stream_physical_binding as binding
from . import stream_physical_projection as projection
from . import stream_source_audit, stream_opportunity_audit
from .trace_source import inspect_jsonl, open_verified, scan_envelope
from src.smt.source_check import verify_source

SCHEMA = 'smt-fullfab-shared-prefix-audit-v1'
ROOT = Path(__file__).resolve().parents[2]
DEPENDENCIES = {**binding.DEPENDENCIES,
    'src/smt_fullfab/stream_physical_binding.py': 'db8ce98dccd7b004b9da595eab93d5eeac1b308ca50af62f961e9f23865877a2',
    'src/smt_fullfab/stream_source_audit.py': '1d2b55073b17d851239d0df0317447bed1b2e45176e882e514fee75b7f0f7463',
    'src/smt_fullfab/stream_opportunity_audit.py': 'f17b2648720f5a971849df1326a02fa457aca755f8ac8bfe6691f08d7ce45bcd'}
STATE_FIELDS = frozenset(('seed','horizon','t','seq','dispatch_id','decisions','releases',
    'completed','finished','wait_until','lots','machine_state','jobs','calendars','pm_counters',
    'queue_area','last_area_t','manifest','plan','observation_start','q','waiting',
    'processing_by_machine','stats','executed_tasks','plan_versions','trace'))
NOT_RECONSTRUCTED = [
    'q exact heap order and every stale-token/wake entry, including their sequence identities',
    'seq exact historical push count (only queue identity/domain constraints checked)',
    'empty defaultdict key membership in waiting/processing_by_machine/pm_counters',
    'machine_state.last_token, wait_until, last_area_t, observation_start',
    'snapshot implementation provenance/exclusive-owner boundary and reference-policy authorship',
]


class PrefixAuditError(ValueError): pass


def require(condition, message):
    if not condition: raise PrefixAuditError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def digest(value): return hashlib.sha256(canonical(value).encode('ascii')).hexdigest()


def number(value):
    try: return type(value) in (int, float) and math.isfinite(value)
    except OverflowError: return False


def strict(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs)
    canonical(value)
    return value


def _bound_file(path, expected=None, *, retain=False):
    # Keep the actual logical leaf used by consumers. Resolving it first could
    # hide a leaf symlink and fence its old target instead of the named member.
    # Parent aliases (for example macOS /var) remain allowed for regular leaves.
    path = Path(path).absolute()
    before = binding._regular_identity(path)
    hasher = hashlib.sha256(); chunks = []; count = 0
    with path.open('rb') as stream:
        require(binding._identity(os.fstat(stream.fileno())) == before, 'file replaced before read')
        for raw in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(raw); count += len(raw)
            if retain: chunks.append(raw)
        require(binding._identity(os.fstat(stream.fileno())) == before, 'file changed during read')
    binding._fence({path: before})
    sha = hasher.hexdigest()
    require(count == before[2] and (expected is None or sha == expected), 'original file SHA differs: ' + str(path))
    return (b''.join(chunks) if retain else None), {'sha256': sha, 'bytes': count}, {path: before}


def _dependencies():
    binding._dependencies()
    identities = {}
    for name, expected in DEPENDENCIES.items():
        identities.update(_bound_file(ROOT / name, expected)[2])
    return identities


def _snapshot(raw, expected_state_sha256, t0):
    doc = strict(raw)
    require(type(doc) is dict and set(doc) == {'schema','version','implementation_sha256','physics_sha256',
        'data_hashes','state','state_sha256','random_mechanism','initialization'}, 'complete snapshot-1 document required')
    state = doc['state']
    require(doc['schema'] == 'smt-fullfab-snapshot-1' and doc['version'] == 'smt-fullfab-env-0.3'
        and doc['random_mechanism'] == 'event-keyed SHA256; no mutable global RNG', 'unsupported snapshot contract')
    require(type(state) is dict and set(state) == STATE_FIELDS
        and doc['state_sha256'] == expected_state_sha256 == digest(state), 'original state SHA differs')
    require(state['finished'] is False and number(state['t']) and state['t'] == t0
        and number(state['horizon']) and 0 < t0 < state['horizon'], 'require unfinished snapshot at external 0<T0<H')
    require(type(state['seed']) is int and state['seed'] == state['manifest']['seed']
        and state['manifest']['horizon'] == state['horizon'] and doc['data_hashes'] == state['manifest']['data_hashes'], 'snapshot/manifest identity differs')
    return doc


def _raw_prefix(seal, state, t0):
    """Prove the raw clock reached T0 even when the last physical event did not."""
    trace = state['trace']; require(type(trace) is list and trace, 'snapshot trace absent')
    plans = []; executed = []; last_plan = None; declared_end = 0
    with open_verified(seal) as reader:
        for record in reader:
            event = strict(record.raw_line); index = record.event_index
            require(index < len(trace) and canonical(event) == canonical(trace[index]), 'raw trace/snapshot prefix differs')
            require(number(event['time']) and event['time'] <= t0 and event['kind'] != 'terminal', 'trace crosses nonterminal T0')
            if index == 0:
                require(event['time'] == 0 and canonical(event['manifest']) == canonical(state['manifest']), 'initial manifest differs')
            if event['kind'] == 'time_advance':
                require(number(event['to']) and event['time'] < event['to'] <= t0, 'declared advance crosses T0')
                declared_end = event['to']
            if event['kind'] == 'plan_committed':
                last_plan = event['plan']; plans.append(last_plan['version'])
            if event['kind'] == 'dispatch' and event['machine'] in state['manifest']['controlled_machine_ids']:
                executed.append([event['plan_version'], event['plan_task_id']])
    require(reader.receipt.event_count == len(trace), 'snapshot has additional history')
    require(declared_end == t0, 'raw time_advance must explicitly reach external T0')
    return {'source_receipt': asdict(reader.receipt), 'declared_clock_end': declared_end,
        'last_plan': last_plan, 'plan_versions': plans, 'executed_tasks': executed}


def _same(actual, expected, path, check):
    """Independent arithmetic uses the existing core's tolerance, never edits state."""
    if type(expected) is dict:
        check(type(actual) is dict and set(actual) == set(expected), 'snapshot ' + path + ' keys differ')
        if type(actual) is dict:
            for key, value in expected.items():
                if key in actual: _same(actual[key], value, path + '.' + str(key), check)
    elif type(expected) is list:
        check(type(actual) is list and len(actual) == len(expected), 'snapshot ' + path + ' length differs')
        if type(actual) is list:
            for i, (a, b) in enumerate(zip(actual, expected)): _same(a, b, path + '[' + str(i) + ']', check)
    elif type(expected) is int:
        check(type(actual) is int and actual == expected, 'snapshot ' + path + ' integer identity/value differs')
    elif type(expected) is float:
        check(number(actual) and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-6), 'snapshot ' + path + ' value differs')
    else: check(type(actual) is type(expected) and actual == expected, 'snapshot ' + path + ' differs')


def _indexes(actual, expected, allowed, name, check):
    check(type(actual) is dict, 'snapshot ' + name + ' is not a mapping')
    if type(actual) is not dict: return
    check(set(actual) <= set(allowed), 'snapshot ' + name + ' unknown key')
    normalized = {}
    for key, values in actual.items():
        check(type(values) is list and len(values) == len(set(values)), 'snapshot ' + name + ' invalid/duplicate members')
        if values: normalized[key] = sorted(values)
    _same(normalized, {k: sorted(v) for k, v in expected.items() if v}, name, check)


def _future_obligations(state, fold, jobs, t0, check):
    """Validate active obligations, without certifying every stale heap entry."""
    q = state['q']; check(type(q) is list and type(state['seq']) is int and state['seq'] >= 0, 'invalid queued-event domain')
    if type(q) is not list: return
    sequences = []; active = Counter(); calendars = Counter(); releases = Counter()
    for i, entry in enumerate(q):
        if not (type(entry) is list and len(entry) == 4):
            check(False, 'malformed queued entry'); continue
        when, seq, kind, payload = entry
        check(number(when) and when > t0, 'queued event due at/before T0 remains undrained')
        check(type(seq) is int and type(state['seq']) is int and 0 < seq <= state['seq'], 'queued sequence domain')
        sequences.append(seq)
        if i: check(tuple(q[(i-1)//2][:2]) <= tuple(entry[:2]), 'queued heap order invalid')
        if kind == 'calendar': calendars[canonical([when, payload])] += 1
        elif kind == 'release': releases[canonical([when, payload])] += 1
        elif kind in ('process_free', 'lot_done'):
            check(type(payload) is dict and set(payload) == {'job','token'}, 'queued job payload shape')
            if type(payload) is not dict or set(payload) != {'job','token'}: continue
            jid = payload['job']; token = payload['token']
            known = type(jid) is int and str(jid) in jobs
            check(known, 'queued job is unknown')
            if known:
                check(type(token) is int and 0 <= token <= jobs[str(jid)]['token'], 'queued job token outside retained history')
                if token == jobs[str(jid)]['token']: active[canonical([kind, when, payload])] += 1
        else: check(kind == 'wake' and payload is None, 'unknown queued event kind/payload')
    check(len(sequences) == len(set(sequences)), 'duplicate queued sequence identity')
    expected = Counter()
    for jid, job in jobs.items():
        for kind, field in (('process_free','process_end'), ('lot_done','lot_end')):
            if job[field] > t0:
                expected[canonical([kind, job[field], {'job': int(jid), 'token': job['token']}])] += 1
    check(active == expected, 'queued current-token processing/completion obligations differ')
    check(calendars == Counter(canonical([when, {'key': key, 'n': occurrence}]) for key, (when, occurrence) in fold.nextcal.items()), 'queued calendar obligations differ')
    check(releases == Counter(canonical([max(0, lot['release']) if lot['initial'] else lot['release'], lid])
        for lid, lot in fold.lots.items() if lot['status'] == 'unreleased'), 'queued release obligations differ')


def _finish_prefix(fold, state, raw, metadata, t0, event_count):
    """New boundary only; original H and every Fold.event check remain unchanged."""
    check = fold.check
    check(not fold.pending, 'prefix contains unexecuted declared dispatch')
    check(fold.previous <= t0 < fold.horizon, 'physical fold crosses external T0')
    for key, (when, _) in fold.nextcal.items(): check(when > t0, 'missing due calendar event: ' + key)
    for jid, job in fold.history.jobs(): check(job['done'] or job['lot_end'] > t0, 'unfinished due operation ' + str(jid))
    for lid, lot in fold.lots.items():
        release = max(0, lot['release']) if lot['initial'] else lot['release']
        check(lot['status'] != 'unreleased' or release > t0, 'missing lot release ' + lid)
        check(lot['status'] in ('waiting','processing','done','unreleased') and not lot.get('required_rework'), 'prefix unresolved transition/rework ' + lid)
    initial = sum(lot['initial'] for lot in fold.lots.values())
    completed = list(fold.history.records('completed'))
    current = sum(lot['status'] not in ('done','unreleased') for lot in fold.lots.values())
    check(initial == fold.manifest['initial_wip'], 'initial WIP count')
    # Initial WIP with a future declared release is not yet active at T0.
    # The horizon-only finish assumes all initial releases have happened; this
    # boundary instead conserves exactly the independently observed releases.
    check(len(fold.released) == len(completed) + current, 'prefix lot conservation')
    check(type(state['releases']) is int and state['releases'] == len(fold.released), 'snapshot releases differ')
    _same(state['completed'], completed, 'completed', check)
    area = fold.queue_area + (t0 - fold.previous) * fold.waiting_control
    _same(state['queue_area'], area, 'queue_area through T0', check)
    expected_lots = {}; waiting = defaultdict(list)
    originals = {lot['id']: lot for lot in fold.manifest['lots']}
    for lid, lot in fold.lots.items():
        expected_lots[lid] = {key: lot[key] for key in originals[lid] if key != 'step'}
        expected_lots[lid].update(step=lot['next_step']-1, status=lot['status'], visits=lot['visits'],
            dedications=lot['dedications'], ready_since=lot['ready'], done=lot['done'])
        if lot['status'] == 'waiting': waiting[fold.routes[lot['route']][lot['next_step']-1]['family']].append(lid)
    _same(state['lots'], expected_lots, 'lots', check)
    families = {m['family'] for m in fold.machines.values()}
    _indexes(state['waiting'], waiting, families, 'waiting', check)
    jobs = {}; processing = defaultdict(list)
    for jid, job in fold.history.jobs():
        check(type(jid) is int and jid in metadata, 'missing job start/token reconstruction')
        if jid not in metadata: continue
        jobs[str(jid)] = {key: job[key] for key in ('machine','lots','process_end','lot_end','controlled','done')}
        jobs[str(jid)].update(metadata[jid])
        if not job['done'] and job['process_end'] > t0: processing[str(job['machine'])].append(jid)
    check(type(state['dispatch_id']) is int and state['dispatch_id'] == len(jobs)
        and set(jobs) == {str(i) for i in range(state['dispatch_id'])}, 'snapshot dispatch/job identity history differs')
    _same(state['jobs'], jobs, 'jobs', check)
    _indexes(state['processing_by_machine'], processing, map(str, fold.machines), 'processing_by_machine', check)
    machine_state = {str(mid): {'ready': ms['ready'], 'down_until': ms['down'], 'setup': ms['setup'],
        'min_left': ms['min_left'], 'min_setup': ms['min_setup']} for mid, ms in fold.ms.items()}
    actual_ms = {key: {field: value for field, value in ms.items() if field != 'last_token'} for key, ms in state['machine_state'].items()}
    _same(actual_ms, machine_state, 'machine_state except last_token', check)
    _same({k: v for k, v in state['pm_counters'].items() if v}, {str(k): v for k, v in fold.piece.items() if v}, 'pm_counters nonempty', check)
    _same(state['calendars'], fold.calendars, 'calendars', check)
    _same(state['plan'], raw['last_plan'], 'plan', check)
    check(type(state['decisions']) is int and state['decisions'] == len(raw['plan_versions']), 'snapshot plan commit count differs')
    _same(state['plan_versions'], sorted(raw['plan_versions']), 'plan_versions', check)
    _same(state['executed_tasks'], sorted(raw['executed_tasks']), 'executed_tasks', check)
    dispatches = fold.history.stream_counts['dispatch']
    stats = {'dispatches': dispatches, 'controlled_dispatches': fold.action_count,
        'batch_dispatches': sum(fold.routes[fold.lots[e['lots'][0]]['route']][e['steps'][0]-1]['batch_max'] > 1 for e in fold.dispatches())}
    _same(state['stats'], stats if dispatches else {}, 'stats', check)
    _future_obligations(state, fold, jobs, t0, check)
    return {'valid': not fold.errors, 'errors': list(fold.errors), 'physical_event_count': event_count,
        'boundary_time': t0, 'original_horizon': fold.horizon, 'last_physical_event_time': fold.previous,
        'queue_area_through_boundary': area, 'released_lots': len(fold.released), 'completed_lots': len(completed),
        'active_lots': current, 'jobs': len(jobs), 'processing_jobs': sum(map(len, processing.values())),
        'not_independently_reconstructed': NOT_RECONSTRUCTED,
        'whole_private_state_independently_certified': False, 'terminal_inserted': False}


def _fold_projection(directory, seal, created, state, raw, t0, work_dir):
    with TemporaryDirectory(prefix='shared_prefix_', dir=work_dir) as temp:
        with closing(sqlite3.connect(Path(temp) / 'history.sqlite3')) as db:
            db.execute('PRAGMA temp_store=FILE'); db.execute('PRAGMA cache_size=-2048')
            with closing(binding.core.History(db)) as history:
                with projection.open_verified_projection(directory, source=seal,
                        expected_manifest_sha256=created['manifest_sha256']) as reader:
                    fold = None; count = 0; metadata = {}
                    for record in reader:
                        event = record.event
                        if fold is None:
                            require(event['kind'] == 'initial', 'physical projection lacks initial')
                            fold = binding.core.Fold(event['manifest'], history)
                        if event['kind'] == 'terminal': raise PrefixAuditError('terminal is forbidden in prefix')
                        fold.event(count, event, False); count += 1
                        if event['kind'] == 'dispatch':
                            jid = event['job']
                            fold.check(type(jid) is int and jid == len(metadata), 'physical dispatch IDs not original consecutive integers')
                            metadata[jid] = {'start': event['time'], 'token': 0}
                        elif event['kind'] == 'downtime':
                            for jid in event['affected_jobs']:
                                if jid in metadata: metadata[jid]['token'] += 1
                    require(fold is not None, 'empty physical projection')
                    report = _finish_prefix(fold, state, raw, metadata, t0, count)
                require(canonical(asdict(reader.receipt)) == canonical(created['output_receipt']), 'physical consumption receipt differs')
    return report


def audit_prefix(snapshot_path, trace_path, *, expected_snapshot_sha256, expected_state_sha256,
                 expected_trace_sha256, boundary_time, verify_data_dir, output_dir, work_dir=None):
    """Publish a create-new, original-byte-bound prehistory receipt last.

    verify_data_dir is mandatory; real CSV-to-manifest verification is performed.
    Semantic rejection produces valid=False; malformed/changed/incomplete inputs
    raise and retain new diagnostics without a successful final receipt. Nothing
    is resumed, repaired, simulated, selected, committed or written to a ledger.
    """
    require(all(binding._sha(x) for x in (expected_snapshot_sha256, expected_state_sha256, expected_trace_sha256)), 'three external original SHA anchors required')
    require(number(boundary_time) and boundary_time > 0 and verify_data_dir is not None, 'external positive T0 and original data directory required')
    dependency_identities = _dependencies()
    _, implementation_receipt, self_identity = _bound_file(__file__)
    snapshot_raw, snapshot_receipt, identities = _bound_file(snapshot_path, expected_snapshot_sha256, retain=True)
    identities.update(dependency_identities); identities.update(self_identity)
    doc = _snapshot(snapshot_raw, expected_state_sha256, boundary_time); state = doc['state']
    # inspect_jsonl canonicalizes its own path; retain the caller's regular
    # logical leaf as an additional original fence rather than losing it.
    trace_logical = Path(trace_path).absolute()
    trace_identity = binding._regular_identity(trace_logical)
    seal = inspect_jsonl(trace_logical, expected_sha256=expected_trace_sha256)
    require(seal.file_identity == trace_identity, 'trace changed before inspection')
    identities[trace_logical] = trace_identity; identities[seal.path] = seal.file_identity
    binding._fence(identities)
    envelope = scan_envelope(seal, require_terminal=False)
    require(not envelope.terminal_at_eof and envelope.horizon == state['horizon'], 'nonterminal original horizon required')
    raw = _raw_prefix(seal, state, boundary_time)
    physical = [m['id'] for m in state['manifest']['machines'] if m['group'] != 'Delay_32']
    require(len(physical) == 913 and len(set(physical)) == 913 and all(type(x) is int for x in physical)
        and sorted(physical) == state['manifest']['controlled_machine_ids'], 'complete original 913 production domain required')
    data = Path(verify_data_dir).resolve(strict=True); data_receipts = {}
    require(set(p.name for p in data.iterdir() if p.is_file()) == set(doc['data_hashes']), 'original data inventory differs')
    for name, expected in doc['data_hashes'].items():
        require(type(name) is str and Path(name).name == name and binding._sha(expected), 'invalid original data member')
        _, receipt, refs = _bound_file(data / name, expected); identities.update(refs); data_receipts[name] = receipt
    def fence():
        binding._fence(identities)
        require(set(p.name for p in data.iterdir() if p.is_file()) == set(data_receipts), 'original data inventory changed')
    source_errors = verify_source(state['manifest'], data)
    fence()
    output = Path(output_dir).absolute(); output = output.parent.resolve(strict=True) / output.name
    output.mkdir()  # Never reuse any partial/completed directory.
    members = {}
    def member(name, expected):
        _, receipt, refs = _bound_file(output / name, expected)
        members[name] = receipt; identities.update(refs)
    provenance = stream_source_audit.audit_plan_sources(seal, report_path=output / 'source.json', work_dir=work_dir)
    member('source.json', provenance['report_sha256'])
    opportunity = stream_opportunity_audit.audit_opportunity_coverage(seal, report_path=output / 'opportunity.json', work_dir=work_dir)
    member('opportunity.json', opportunity['report_sha256'])
    for component in (provenance, opportunity):
        require(component['complete_jsonl_pass'] and canonical(component['source_receipt']) == canonical(raw['source_receipt']), 'component source receipt differs')
    created = projection.project_physical_trace(seal, output_dir=output / 'projection')
    require(canonical(created['source_receipt']) == canonical(raw['source_receipt']), 'projection source receipt differs')
    member('projection/projection.json', created['manifest_sha256'])
    member('projection/physical.jsonl', created['output_receipt']['sha256'])
    checked = _fold_projection(output / 'projection', seal, created, state, raw, boundary_time, work_dir)
    fence(); _dependencies()
    errors = ([f'source inputs: {e}' for e in source_errors] + [f'plan source: {e}' for e in provenance['errors']]
        + [f'opportunity: {e}' for e in opportunity['errors']] + [f'physical prefix/state: {e}' for e in checked['errors']])
    require(provenance['valid'] == (not provenance['errors']) and opportunity['valid'] == (not opportunity['errors']), 'inconsistent component validity')
    report = {'schema': SCHEMA, 'status': 'complete', 'valid': not errors, 'errors': errors,
        'snapshot_sha256': expected_snapshot_sha256, 'state_sha256': expected_state_sha256,
        'trace_sha256': expected_trace_sha256, 'snapshot_receipt': snapshot_receipt,
        'source_receipt': raw['source_receipt'], 'boundary_time': boundary_time, 'original_horizon': state['horizon'],
        'declared_clock_end': raw['declared_clock_end'], 'production_machine_count': len(physical),
        'physical_prefix': checked, 'source_valid': provenance['valid'], 'opportunity_valid': opportunity['valid'],
        'verified_source_inputs': not source_errors, 'data_receipts': data_receipts, 'members': members,
        'projection_evidence': {key: created[key] for key in ('manifest_sha256','source_receipt','output_receipt')},
        'dependency_sha256': dict(DEPENDENCIES), 'implementation_sha256': implementation_receipt['sha256'],
        'complete_physical_window_certified': False, 'steady_state_certified': False,
        'model_attribution_certified': False, 'reference_policy_authorship_certified': False,
        'snapshot_implementation_execution_certified': False, 'exclusive_owner_boundary_certified': False,
        'whole_private_state_independently_certified': False, 'new_terminal_event_inserted': False,
        'source_of_T0': 'externally supplied; not inferred from last physical event',
        'scope': 'complete raw-prefix source/opportunity and independent physics through T0; listed reconstructed state only; external anchors are caller trust'}
    # Keep every original input/member anchor through the publication fence.
    published = binding._publish_report(report, output / 'prehistory_audit.json', fence)
    return {**published, 'valid': report['valid'], 'errors': errors, 'snapshot_sha256': expected_snapshot_sha256,
        'state_sha256': expected_state_sha256, 'trace_sha256': expected_trace_sha256, 'boundary_time': boundary_time,
        'complete_physical_window_certified': False, 'whole_private_state_independently_certified': False}
