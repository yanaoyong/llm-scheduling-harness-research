"""Cold-start B delta development endpoint; no automatic recovery or planner.

Only the original model envelope can query, assemble, check and select. The
selected compiled plan is passed unchanged to the shared physical executor.
This module's audit verifies local original-call attribution, not remote backend
identity. An enclosing frozen gate must accept whole-process costs and resources.
The environment trace, one interaction export and report arrays still use RAM.
"""
from __future__ import annotations

import argparse
from base64 import b64decode
from copy import deepcopy
import dataclasses
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import time
import traceback

from . import B_delta_call_bridge_v4 as bridge
from . import B_delta_durable_v5 as durable
from . import B_delta_interaction_v3 as interaction
from .budget import ROOT, APPROVAL, DEFAULT_LEDGER, BudgetLedger, record_sha256
from .environment import FullFabEnvironment
from .interface import compact_pages
from .model_transport_supervised import ModelConfig, call_model, _disabled_skills
from .plan_delta import STATE_SCHEMA, anchor_hashes, json_sha256
from .runner import source_snapshot, include_result_bytes, stream_audit
from .stream_snapshot import write_snapshot
from .trace_source import inspect_jsonl, open_verified, scan_envelope

SCHEMA = 'smt-fullfab-B-delta-controller-v4'
INDEX_SCHEMA = SCHEMA + '-index'
DATA = 'data/smt/SMT2020_LVHM'
VENDOR = 'vendor/PySCFabSim-revised/simulation'
SOURCE_CONVENTION = 'sha256(json.dumps(relative_path_to_sha256,sort_keys=True,separators=(comma,colon),ensure_ascii=True,allow_nan=False).encode(utf-8))'
PREFIX_KEYS = ('journal_records', 'journal_tail_sha256', 'database_sha256')
COLD_REASON = 'Explicitly uncommitted empty cold-start base; no prior model plan exists.'


def require(value, message):
    if not value:
        raise ValueError(message)


def raw_json(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()


def sha_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def load_json(path):
    value = json.loads(Path(path).read_bytes(), object_pairs_hook=_pairs)
    json_sha256(value)  # Reject nonfinite JSON without normalizing types.
    return value


def bound_json(path, expected_sha256):
    """One FD snapshot; do not hash a path then decode different bytes."""
    raw, _ = bridge.binding.read_snapshot(path)
    require(hashlib.sha256(raw).hexdigest() == expected_sha256, 'bound evidence SHA mismatch')
    value = json.loads(raw, object_pairs_hook=_pairs)
    json_sha256(value)
    return value


def write_new(path, value):
    data = raw_json(value)
    return write_raw_new(path, data)


def write_raw_new(path, data):
    with Path(path).open('xb') as stream:
        require(stream.write(data) == len(data), 'short evidence write')
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(data).hexdigest()


def account_from_rows(rows, out):
    """Count real original reserves, including unfinished/unknown outcomes."""
    out = Path(out).resolve()
    def records(row):
        return [row] + [row[k] for k in ('registration', 'mapping', 'finalization') if type(row.get(k)) is dict]
    def own_path(row):
        for record in records(row):
            for key in ('run_id', 'parent_run_id', 'segment_run_id'):
                if type(record.get(key)) is str:
                    path = Path(record[key]).resolve()
                    if path == out or out in path.parents:
                        return True
        return False
    registration_ids = {record['registration_id'] for row in rows if own_path(row)
                        for record in records(row) if type(record.get('registration_id')) is str}
    def own_domain(row):
        return own_path(row) or any(record.get('registration_id') in registration_ids for record in records(row))
    starts = [r for r in rows if r.get('event') in ('reserve', 'solver_reserve', 'constructor_reserve') and own_domain(r)]
    ids = [r['call_id'] for r in starts]
    require(len(ids) == len(set(ids)), 'duplicate actual run reservation')
    id_set = set(ids)
    selected = [r for r in rows if r.get('call_id') in id_set or own_domain(r)]
    return {'account': BudgetLedger.account(selected),
            'reserve_call_ids': [r['call_id'] for r in starts if r['event'] == 'reserve'],
            'solver_call_ids': [r['call_id'] for r in starts if r['event'] == 'solver_reserve'],
            'constructor_call_ids': [r['call_id'] for r in starts if r['event'] == 'constructor_reserve'],
            'registration_ids': sorted(registration_ids), 'run_events_sha256': json_sha256(selected),
            'run_events_count': len(selected)}


def capture_account(out, ledger):
    """Archive real ledger bytes without repairing any missing finish/usage."""
    raw, proof = bridge.binding.read_snapshot(DEFAULT_LEDGER)
    rows = [row for row, _ in bridge.original_rows(raw)]
    value = account_from_rows(rows, out)
    require(same(value['account'], ledger.summary(run_id=str(out))), 'run summary differs from actual ledger snapshot')
    value.update(ledger_source_path=str(DEFAULT_LEDGER.resolve()), ledger_receipt=proof,
                 ledger_sha256=write_raw_new(out / 'ledger_final.jsonl', raw))
    value['account_report_sha256'] = write_new(out / 'ledger_final_account.json', value)
    return value


def read_account_evidence(out, expected_report_sha256):
    value = bound_json(out / 'ledger_final_account.json', expected_report_sha256)
    require(value['ledger_source_path'] == str(DEFAULT_LEDGER.resolve()), 'original ledger source path changed')
    raw, _ = bridge.binding.read_snapshot(out / 'ledger_final.jsonl')
    require(hashlib.sha256(raw).hexdigest() == value['ledger_sha256'], 'final original ledger snapshot differs')
    live, _ = bridge.binding.read_snapshot(DEFAULT_LEDGER)
    require(live.startswith(raw), 'actual original ledger no longer preserves final snapshot prefix')
    computed = account_from_rows([row for row, _ in bridge.original_rows(raw)], out)
    require(all(same(value[k], computed[k]) for k in computed), 'saved account differs from original reserve/finish bytes')
    live_computed = account_from_rows([row for row, _ in bridge.original_rows(live)], out)
    require(same(live_computed, computed), 'same run/registration/call identity acquired ledger suffix events after sealing; original account not re-anchored')
    return value


def same(left, right):
    return json_sha256(left) == json_sha256(right)


def source_manifest(root=ROOT):
    """All source/vendor/data files and requirements; no run or foreign results."""
    root = Path(root).resolve()
    paths = []
    for name in ('src', VENDOR, DATA):
        base = root / name
        require(base.is_dir() and not base.is_symlink(), 'missing/linked source directory: ' + name)
        for path in sorted(base.rglob('*')):
            if '__pycache__' in path.parts or path.suffix in ('.pyc', '.pyo'):
                continue
            require(not path.is_symlink(), 'linked source input: ' + str(path))
            if path.is_file():
                paths.append(path)
    paths.extend(sorted(root.glob('requirements*')))
    require(root / 'requirements.lock' in paths, 'requirements.lock required')
    files = {}
    for path in sorted(set(paths)):
        require(path.is_file() and not path.is_symlink(), 'nonregular source input')
        files[path.relative_to(root).as_posix()] = sha_file(path)
    return {'schema': SCHEMA + '-source', 'files': files,
            'source_sha256': json_sha256(files), 'canonical_hash_convention': SOURCE_CONVENTION}


def assert_source(expected, root=ROOT):
    actual = source_manifest(root)
    require(actual['source_sha256'] == expected, 'frozen source inventory differs from external expected hash')
    return actual


def cold_base(run_id, now, horizon, scope):
    return {'version': 'uncommitted-cold-start:' + run_id, 'created_at': now,
            'valid_until': horizon, 'freeze_until': now, 'reason': COLD_REASON,
            'scope': deepcopy(scope), 'tasks': [], 'holds': []}


def next_boundary(now, observation_start, horizon, period=1800):
    """Absolute shared period; an intervening event never postpones its edge."""
    require(all(type(v) in (int, float) and math.isfinite(v) for v in (now, observation_start, horizon, period))
            and period > 0 and observation_start <= now < horizon, 'invalid absolute period bounds')
    return min(horizon, observation_start + (math.floor((now - observation_start) / period) + 1) * period)


def bootstrap(env, *, run_id, source_sha256, page_chars=45000):
    problem = env.problem(plan_seconds=14400, lookahead_depth=2)
    require(type(problem['scope']) is list and len(problem['scope']) == 913
            and all(type(x) is int for x in problem['scope'])
            and set(problem['scope']) == set(env.physical)
            and len(problem['machines']) == 913
            and {m['machine'] for m in problem['machines']} == set(env.physical),
            'full 913 physical-machine observation required')
    base = deepcopy(env.plan) if env.plan is not None else cold_base(run_id, env.t, env.horizon, problem['scope'])
    state = {'schema': STATE_SCHEMA, 'time': env.t, 'observation_end': env.horizon,
             'base_plan_version': base['version'],
             'dispatched_task_ids': [t['id'] for t in base['tasks']
                                     if (base['version'], t['id']) in env.executed_tasks]}
    paging = compact_pages(problem, max_chars=page_chars)
    paging.update(page_count=len(paging['pages']), observation_end=env.horizon)
    return {'base_plan': base, 'problem': problem, 'execution_state': state,
            'source_sha256': source_sha256, 'paging': paging}


def response_schema():
    """Exact original feedback-v3 envelopes; no response projection or field defaults.

    Required task fields and optional latest_start are exposed in this transport
    grammar. Already retained base extras remain unchanged. Pure Interaction is
    still the authoritative stricter semantic validator of every original byte.
    """
    def obj(fields):
        return {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}
    def arr(item):
        return {'type': 'array', 'items': item}
    def const(value):
        return {'type': 'string', 'enum': [value]}
    text, number, integer = {'type': 'string'}, {'type': 'number'}, {'type': 'integer'}
    anchors = obj({k: text for k in ('base_plan_sha256', 'problem_sha256', 'state_sha256', 'source_sha256')})
    path = arr({'anyOf': [text, integer]})
    view = {'path': path, 'format': {'type': 'string', 'enum': ['value', 'page', 'text']}, 'offset': integer, 'count': integer}
    header = obj({'version': text, 'created_at': number, 'valid_until': number,
                  'freeze_until': number, 'reason': text, 'scope': arr(integer)})
    task_fields = {'id': text, 'machine': integer, 'lot_ids': arr(text), 'steps': arr(integer),
                   'visits': arr(integer), 'operation_ids': arr(text), 'not_before': number}
    task = {'anyOf': [obj(task_fields), obj({**task_fields, 'latest_start': {'type': ['number', 'null']}})]}
    hold_fields = {'machine': integer, 'until': number, 'reason': text}
    hold = {'anyOf': [obj(hold_fields), obj({**hold_fields, 'after_task_id': {'type': ['string', 'null']}})]}
    item = {'anyOf': [text, task, hold, obj({'ref': text, 'hold': hold}), obj({'machine': integer, 'task_ids': arr(text)})]}
    common = {'schema': const(interaction.assembly_layer.SCHEMA), 'draft_id': text,
              'anchors': anchors, 'previous_state_sha256': text}
    assembly = {'anyOf': [obj({**common, 'action': const('seal')}), obj({**common, 'action': const('chunk'),
        'sequence': integer, 'chunk_id': text,
        'set_fields': arr(obj({'path': arr(text), 'value': {'anyOf': [text, anchors, header]}})),
        'append_arrays': arr(obj({'path': arr(text), 'items': arr(item)}))})]}
    queries = []
    for action, field in (('read_page', 'page_index'), ('read_base_tasks', 'task_ids'),
                          ('read_base_holds', 'hold_refs'), ('read_operations', 'operation_ids')):
        queries.append(obj({'action': const(action), 'session_id': text, 'anchors': anchors,
                            field: integer if action == 'read_page' else arr(text)}))
    variants = {
        'catalog_page': {'path': path, 'offset': integer, 'count': integer},
        'catalog_text': {'offset': integer, 'count': integer},
        'session_query': {'action': {'anyOf': queries}}, 'create_draft': {'draft_id': text},
        'assembly_action': {'action': assembly},
        'check_assembly': {k: text for k in ('draft_id', 'sealed_state_sha256', 'seal_action_sha256', 'delta_sha256')},
        'read_draft': {'draft_id': text, 'state_sha256': text, **view},
        'read_candidate': {'candidate_id': text, 'candidate_sha256': text, **view},
        'read_candidates': {}, 'read_archive_feedback': {'history_index': integer, 'feedback_sha256': text, **view},
        'apply': {'candidate_id': text, 'candidate_sha256': text}}
    return obj({'schema': const(interaction.RESPONSE_SCHEMA), 'interaction_id': text, 'session_id': text,
                'anchors': anchors, 'catalog_sha256': text, 'prompt_body_sha256': text, 'memory': text,
                'request': {'anyOf': [obj({'kind': const(kind), **fields}) for kind, fields in variants.items()]}})


class RunIndex:
    """One create-new append-only run claim; never opens existing state for writes."""
    def __init__(self, path):
        self.path = Path(path)
        with self.path.open('xb') as stream:
            stream.flush()
            os.fsync(stream.fileno())
            self.identity = self._identity(os.fstat(stream.fileno()))
        self.seq, self.tail, self.poisoned = 0, None, False

    @staticmethod
    def _identity(info):
        require(stat.S_ISREG(info.st_mode), 'run index is not a regular file')
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def append(self, event, **payload):
        require(not self.poisoned, 'run index is poisoned; read-only diagnosis required')
        row = {'schema': INDEX_SCHEMA, 'seq': self.seq, 'event': event,
               'previous_sha256': self.tail, 'payload': payload}
        row['record_sha256'] = json_sha256(row)
        raw = raw_json(row)
        try:
            require(self._identity(os.stat(self.path, follow_symlinks=False)) == self.identity,
                    'run index identity changed before append')
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0))
            with os.fdopen(fd, 'ab') as stream:
                require(self._identity(os.fstat(stream.fileno())) == self.identity, 'run index changed while opening')
                require(stream.write(raw) == len(raw), 'short run index write')
                stream.flush()
                os.fsync(stream.fileno())
                after = self._identity(os.fstat(stream.fileno()))
                require(after[:2] == self.identity[:2] and after[2] == self.identity[2] + len(raw)
                        and self._identity(os.stat(self.path, follow_symlinks=False)) == after,
                        'run index changed during append')
        except BaseException:
            self.poisoned = True
            raise
        self.seq += 1
        self.tail = row['record_sha256']
        self.identity = after
        return row


def read_index(path, *, expected_sha256):
    seal = inspect_jsonl(path, expected_sha256=expected_sha256)
    rows, tail = [], None
    with open_verified(seal) as reader:
        for record in reader:
            row = record.event
            require(set(row) == {'schema', 'seq', 'event', 'previous_sha256', 'payload', 'record_sha256'}
                    and row['schema'] == INDEX_SCHEMA and type(row['seq']) is int and row['seq'] == len(rows)
                    and row['previous_sha256'] == tail, 'run index envelope/hash chain differs')
            original = {k: v for k, v in row.items() if k != 'record_sha256'}
            require(row['record_sha256'] == json_sha256(original), 'run index row digest differs')
            rows.append(row)
            tail = row['record_sha256']
    return rows


def proof_prefix(store, store_id):
    proof = durable.recover_read_only(store.directory, expected_store_id=store_id)
    require(proof['valid'] and proof['pure_replay_verified'], 'durable recovery verification failed')
    return {k: proof[k] for k in PREFIX_KEYS}


def export_one(directory, *, store_id, prefix, instance_id):
    report = durable.export_verified_interaction(directory, expected_store_id=store_id, expected_prefix=prefix)
    require(report['valid'] and report['pure_replay_verified'], 'exact durable interaction export failed')
    require(len(report['interactions']) == len(report['sessions']) == 1
            and report['instances'] == {instance_id: report['interactions'][0]['interaction_id']},
            'one registered interaction per plan store required')
    return report, report['interactions'][0]['evidence']


def commit_selection(env, *, store, store_id, instance_id, selection, expected_bootstrap,
                     run_id, source_sha256, page_chars, index, plan_index, directory):
    """Record intent before the one common commit; never retry an unknown result."""
    current = bootstrap(env, run_id=run_id, source_sha256=source_sha256, page_chars=page_chars)
    require(same(current, expected_bootstrap), 'current physical observation/base/execution anchors changed')
    anchors = anchor_hashes(current['base_plan'], current['problem'], current['execution_state'], source_sha256=source_sha256)
    require(same(selection['anchors'], anchors), 'selection does not bind current four anchors')
    plan = selection['candidate']['compiled']['plan']
    require(selection['status'] == 'selection_for_external_commit', 'no explicit model selection')
    selected_plan_file_sha = write_new(directory / 'selected_plan.json', plan)
    before = len(env.trace)
    intent_id = run_id + ':plan:' + str(plan_index) + ':physical-commit'
    intent = store.record_commit_intent(instance_id, intent_id=intent_id,
        selection_sha256=json_sha256(selection), plan_sha256=json_sha256(plan), current_anchors=anchors,
        external_validation_reference={'trace_event_index_before': before, 'plan_index': plan_index,
                                       'common_commit_not_yet_performed': True})
    write_new(directory / 'commit_intent.json', intent)
    require(intent['accepted'], 'durable commit intent rejected; no physical commit attempted')
    index.append('commit_intent', plan_index=plan_index, intent_id=intent_id,
                 selection_sha256=json_sha256(selection), plan_sha256=json_sha256(plan),
                 selected_plan_file_sha256=selected_plan_file_sha,
                 trace_event_index=before, durable_prefix=proof_prefix(store, store_id))
    outcome = 'unknown'
    receipt = {'plan_index': plan_index, 'intent_id': intent_id, 'plan_sha256': json_sha256(plan),
               'trace_event_index_before': before, 'retry_permitted': False}
    try:
        returned = env.commit_plan(plan)  # EXACT compiled plan; no crop/decode/default/repair.
        require(len(env.trace) == before + 1 and env.trace[before]['kind'] == 'plan_committed'
                and same(env.trace[before]['plan'], plan) and same(env.plan, plan)
                and returned == json_sha256(plan), 'common commit returned without exact plan/trace agreement')
        outcome = 'accepted'
        receipt.update(trace_event_index=before, trace_event_sha256=json_sha256(env.trace[before]),
                       trace_seq=env.trace[before]['seq'], actual_plan_sha256=returned)
    except BaseException as exc:
        receipt.update(error={'type': type(exc).__name__, 'message': str(exc)}, reported_outcome='unknown')
        # A validator may have rejected before mutation, but unknown is safer than
        # inferring transactionality after arbitrary exceptions or I/O failures.
        write_new(directory / 'commit_receipt.json', receipt)
        recorded = store.record_commit_receipt(instance_id, intent_id=intent_id, reported_outcome='unknown',
            receipt_bytes=raw_json(receipt), external_reference={'path': 'commit_receipt.json'})
        write_new(directory / 'commit_receipt_record.json', recorded)
        index.append('commit_finished', plan_index=plan_index, reported_outcome='unknown',
                     receipt_sha256=sha_file(directory / 'commit_receipt.json'), durable_prefix=proof_prefix(store, store_id))
        raise
    receipt['reported_outcome'] = outcome
    receipt_sha = write_new(directory / 'commit_receipt.json', receipt)
    recorded = store.record_commit_receipt(instance_id, intent_id=intent_id, reported_outcome=outcome,
        receipt_bytes=raw_json(receipt), external_reference={'path': 'commit_receipt.json', 'sha256': receipt_sha})
    write_new(directory / 'commit_receipt_record.json', recorded)
    require(recorded['accepted'], 'physical commit exists but durable receipt failed; stop without replay')
    index.append('commit_finished', plan_index=plan_index, reported_outcome=outcome,
                 receipt_sha256=receipt_sha, durable_prefix=proof_prefix(store, store_id))
    return receipt


def _tree_bytes(out):
    return sum(p.stat().st_size for p in out.rglob('*') if p.is_file())


def resource_check(out, *, started, wall_seconds, max_log_bytes, max_trace_bytes):
    require(time.monotonic() - started < wall_seconds, 'complete endpoint wall limit')
    require(_tree_bytes(out) < max_log_bytes, 'complete run log byte limit')
    trace = out / 'trace.jsonl'
    require(not trace.exists() or trace.stat().st_size <= max_trace_bytes, 'complete raw trace byte limit')


def _relative(out, value):
    require(type(value) is str and value and not Path(value).is_absolute()
            and '..' not in Path(value).parts, 'unsafe evidence relative path')
    path = out / value
    require(path.resolve().is_relative_to(out.resolve()) and not path.is_symlink(), 'evidence path escaped run')
    return path


def audit_delta_run(out, *, expected_index_sha256, expected_source_sha256, expected_trace_sha256):
    """Read-only original-call -> pure replay -> actual physical commit binding.

    Independently consumes the entire saved raw trace. Common streaming bundle
    remains necessary for physics, legal opportunities and per-dispatch sources.
    This checks local evidence consistency, never provider-side authenticity.
    One plan's complete durable export and the run index remain memory resident.
    """
    out = Path(out).resolve()
    errors, details = [], []
    try:
        manifest = load_json(out / 'source_manifest.json')
        require(manifest['source_sha256'] == expected_source_sha256 == json_sha256(manifest['files'])
                and manifest['canonical_hash_convention'] == SOURCE_CONVENTION, 'source inventory anchor mismatch')
        rows = read_index(out / 'delta_index.jsonl', expected_sha256=expected_index_sha256)
        require(rows and rows[0]['event'] == 'run_started' and rows[-1]['event'] == 'run_stopped', 'unclosed run index')
        cfg = load_json(out / 'config.json')
        require(same(rows[0]['payload']['config'], cfg) and cfg['source_sha256'] == expected_source_sha256,
                'configuration/source differs from original claim')
        opened, closed, calls, finishes, intents, receipts = {}, {}, {}, {}, {}, {}
        for row in rows[1:-1]:
            name, p = row['event'], row['payload']
            pi = p['plan_index']
            require(type(pi) is int and pi >= 0, 'invalid plan index')
            if name == 'plan_opened':
                require(pi == len(opened) and (not opened or pi - 1 in closed), 'nonsequential plan store or unclosed predecessor')
                opened[pi] = p
            elif name == 'plan_closed':
                require(pi in opened and pi not in closed, 'duplicate/unregistered plan closure')
                closed[pi] = p
            elif name == 'call_started':
                mi = p['model_index']
                require(type(mi) is int and mi == len(calls) and pi in opened and pi not in closed,
                        'global call index reset/reuse or stale plan')
                require(mi == 0 or mi - 1 in finishes, 'new call after unresolved original call')
                calls[mi] = p
            elif name == 'call_finished':
                mi = p['model_index']
                require(mi in calls and mi not in finishes and calls[mi]['plan_index'] == pi, 'call completion has no unique original issue')
                finishes[mi] = p
            elif name in ('commit_intent', 'commit_finished'):
                target = intents if name == 'commit_intent' else receipts
                require(pi in opened and pi not in target and pi not in closed, 'duplicate/unregistered commit')
                if name == 'commit_finished':
                    require(pi in intents, 'receipt without preceding intent')
                target[pi] = p
            else:
                raise ValueError('unknown run index event: ' + str(name))
        require(set(opened) == set(closed) == set(intents) == set(receipts), 'unfinished plan or unknown commit outcome')
        require(set(calls) == set(finishes), 'pending call; never repeat or infer success')
        resources = read_account_evidence(out, rows[-1]['payload']['account_report_sha256'])
        account = resources['account']
        require(account['attempts'] == len(calls) and not account['pending']
                and not resources['solver_call_ids'] and not resources['constructor_call_ids'],
                'original ledger is not closed or contains unattributed/model-external work')
        require(len({p['store_id'] for p in opened.values()}) == len(opened)
                and len({p['store'] for p in opened.values()}) == len(opened), 'store identity reused across plans')
        call_ids = set()
        plan_records = {}
        for pi, item in opened.items():
            directory = _relative(out, item['directory'])
            require(item['directory'] == f'plan_{pi:05d}' and item['store'] == item['directory'] + '/durable', 'plan store remapping')
            require(item['store_id'] == cfg['run_id'] + ':store:' + str(pi)
                    and item['instance_id'] == cfg['run_id'] + ':instance:' + str(pi)
                    and item['base_was_committed'] is (pi > 0), 'plan store/instance or cold base identity remapping')
            boot_path = directory / 'bootstrap.json'
            boot = bound_json(boot_path, item['bootstrap_file_sha256'])
            require(boot['source_sha256'] == expected_source_sha256 and len(boot['problem']['scope']) == 913
                    and len(set(boot['problem']['scope'])) == 913, 'full-factory bootstrap/source required')
            report, evidence = export_one(_relative(out, item['store']), store_id=item['store_id'],
                prefix=closed[pi]['durable_prefix'], instance_id=item['instance_id'])
            require(report['sessions'][0]['phase'] == 'external_receipt_reported_accepted', 'durable external outcome not accepted')
            require(same(evidence['bootstrap'], boot) and same({k: evidence[k] for k in item['context']}, item['context']), 'durable bootstrap/context differs')
            histories = evidence['history']
            originals = [calls[mi] for mi in calls if calls[mi]['plan_index'] == pi]
            require(len(originals) == len(histories), 'unattributed or omitted original action')
            for issued, history in zip(originals, histories):
                mi = issued['model_index']
                finished = finishes[mi]
                require(issued['transport'] == f'model_{mi:05d}' and issued['evidence'] == f'call_{mi:05d}'
                        and issued['attempt_id'] == cfg['run_id'] + ':model:' + str(mi), 'call path/identity remapping')
                recovered = bridge.recover_read_only(_relative(out, issued['evidence']),
                    expected_intent_sha256=finished['intent_sha256'], expected_outcome_sha256=finished['outcome_sha256'])
                processing_kind = verified_processed_kind(recovered, finished['phase'])
                verify_history_kind(history, processing_kind)
                intent = bound_json(_relative(out, issued['evidence']) / 'intent.json', finished['intent_sha256'])
                require(intent['expected_store_id'] == item['store_id'] and intent['instance_id'] == item['instance_id']
                        and intent['store_directory'] == str(_relative(out, item['store']))
                        and intent['model_index'] == mi and intent['attempt_id'] == issued['attempt_id']
                        and intent['transport_run_dir'] == str(_relative(out, issued['transport']))
                        and same(intent['expected_context'], item['context'])
                        and same(intent['schema_json'], response_schema())
                        and bridge.intent_schema_bytes(intent) == (json.dumps(response_schema(), ensure_ascii=False, indent=2) + '\n').encode(),
                        'bridge intent differs from run ownership or original response-schema wire order')
                require(same(intent['config']['authorization_context'], {'purpose': 'B', 'arm': 'B',
                    'scenario': cfg['seed'], 'window_seconds': cfg['seconds']})
                    and intent['config']['grant_id'] == cfg['budget_id'], 'call does not belong to registered configuration')
                cid = recovered['original_call_id']
                require(cid not in call_ids and history['call_id'] == cid == finished['call_id']
                        and type(history['model_index']) is int and history['model_index'] == mi, 'call reuse or action attribution differs')
                call_ids.add(cid)
                final, _ = bridge.binding.read_snapshot(_relative(out, issued['transport']) / 'final.txt')
                require(b64decode(history['raw_output_base64'], validate=True) == final
                        and history['raw_output_sha256'] == hashlib.sha256(final).hexdigest(), 'original model output differs from replayed action')
            selection = evidence['selection']
            require(selection is not None and selection['status'] == 'selection_for_external_commit', 'no original explicit apply')
            plan = selection['candidate']['compiled']['plan']
            require(intents[pi]['selection_sha256'] == json_sha256(selection)
                    and intents[pi]['plan_sha256'] == json_sha256(plan), 'physical intent selected another plan')
            selected_path = directory / 'selected_plan.json'
            require(same(bound_json(selected_path, intents[pi]['selected_plan_file_sha256']), plan),
                    'saved selected plan differs from original compiled plan')
            receipt_path = directory / 'commit_receipt.json'
            require(receipts[pi]['reported_outcome'] == 'accepted', 'commit receipt outcome mismatch')
            receipt = bound_json(receipt_path, receipts[pi]['receipt_sha256'])
            require(receipt['reported_outcome'] == 'accepted' and receipt['plan_sha256'] == json_sha256(plan)
                    and receipt['trace_event_index'] == intents[pi]['trace_event_index'], 'receipt does not bind original intent')
            event_index = receipt['trace_event_index']
            require(type(event_index) is int and event_index not in plan_records, 'physical commit event reused')
            # Retain only exact file references/hashes across observations, not
            # every full problem/paging/export. One plan is loaded at its commit.
            plan_records[event_index] = (pi, boot_path, item['bootstrap_file_sha256'],
                selected_path, intents[pi]['selected_plan_file_sha256'], receipt_path, receipts[pi]['receipt_sha256'])
            details.append({'plan_index': pi, 'original_calls': len(histories), 'plan_sha256': json_sha256(plan),
                            'selection_sha256': json_sha256(selection), 'store_prefix': closed[pi]['durable_prefix']})
        report = evidence = selection = boot = plan = histories = originals = None
        seal = inspect_jsonl(out / 'trace.jsonl', expected_sha256=expected_trace_sha256)
        envelope = scan_envelope(seal, require_terminal=True)
        require(envelope.snapshot_count == 0 and envelope.first_time == 0 and envelope.horizon == cfg['seconds'],
                'cold-start endpoint cannot certify restored or different-window trace')
        previous, executed, commits, production = None, set(), 0, 0
        with open_verified(seal) as reader:
            for record in reader:
                event = record.event
                if record.event_index == 0:
                    physical = event['manifest']['controlled_machine_ids']
                    require(len(physical) == len(set(physical)) == 913, 'trace initial full-factory scope missing')
                    horizon = event['manifest']['horizon']
                if event['kind'] == 'plan_committed':
                    require(record.event_index in plan_records, 'physical commit lacks original model selection')
                    pi, boot_path, boot_sha, selected_path, selected_sha, receipt_path, receipt_sha = plan_records[record.event_index]
                    boot, plan, receipt = bound_json(boot_path, boot_sha), bound_json(selected_path, selected_sha), bound_json(receipt_path, receipt_sha)
                    require(pi == commits and same(event['plan'], plan) and json_sha256(event) == receipt['trace_event_sha256']
                            and event['seq'] == receipt['trace_seq'], 'physical commit bytes/order differ from model-selected plan')
                    state = boot['execution_state']
                    expected_base = previous if previous is not None else cold_base(cfg['run_id'], event['time'], horizon, boot['problem']['scope'])
                    require(same(boot['base_plan'], expected_base) and state['time'] == event['time']
                            and state['observation_end'] == cfg['seconds'] and state['base_plan_version'] == expected_base['version']
                            and same(state['dispatched_task_ids'], [t['id'] for t in expected_base['tasks']
                                if (expected_base['version'], t['id']) in executed]), 'bootstrap base or executed-state anchor is not actual trace history')
                    require(set(boot['problem']['scope']) == set(physical), 'problem scope differs from actual manifest')
                    require(closed[pi]['advance_from'] == event['time']
                            and closed[pi]['advance_target'] == next_boundary(event['time'], 0.0, horizon, cfg['period_seconds'])
                            and event['time'] <= closed[pi]['simulation_seconds'] <= closed[pi]['advance_target'],
                            'absolute periodic execution target differs or was overrun')
                    if pi > 0:
                        require(closed[pi - 1]['simulation_seconds'] == event['time'], 'replan observation differs from preceding executor stop')
                    previous = event['plan']
                    commits += 1
                elif event['kind'] == 'dispatch' and event['machine'] in physical:
                    require(previous is not None and event.get('owner') == 'plan'
                            and event.get('plan_version') == previous['version'], 'production dispatch outside selected current plan')
                    key = (event['plan_version'], event.get('plan_task_id'))
                    require(key not in executed, 'same plan task dispatched twice')
                    executed.add(key)
                    production += 1
        require(commits == len(plan_records), 'model commit receipt absent from actual complete trace')
        require(resources['reserve_call_ids'] == [finishes[i]['call_id'] for i in range(len(calls))]
                and call_ids == set(resources['reserve_call_ids']), 'real reserve identities/count/order differ from original model actions')
        require(rows[-1]['payload']['finished'] is True and rows[-1]['payload']['simulation_seconds'] == cfg['seconds'], 'runtime stopped without full window')
        require(commits > 0 and closed[commits - 1]['simulation_seconds'] == cfg['seconds'], 'final executor stop is not terminal')
        return {'schema': SCHEMA + '-attribution-audit', 'valid': True, 'errors': [], 'plans': details,
                'source_sha256': expected_source_sha256, 'index_sha256': expected_index_sha256,
                'source_receipt': dataclasses.asdict(envelope.receipt), 'production_dispatches': production,
                'model_calls': account['attempts'], 'reserve_call_ids': resources['reserve_call_ids'],
                'unknown_usage_call_ids': account['unknown_completed'],
                'local_original_call_attribution_verified': True, 'backend_identity_independently_proven': False,
                'physical_validation_performed': False, 'requires_separate_stream_audit_bundle': True,
                'automatic_recovery_or_retry_performed': False}
    except Exception as exc:
        errors.append({'type': type(exc).__name__, 'message': str(exc)})
    return {'schema': SCHEMA + '-attribution-audit', 'valid': False, 'errors': errors, 'plans': details,
            'source_sha256': expected_source_sha256, 'index_sha256': expected_index_sha256,
            'local_original_call_attribution_verified': False, 'backend_identity_independently_proven': False,
            'physical_validation_performed': False, 'automatic_recovery_or_retry_performed': False}



def verified_processed_kind(recovered, saved_phase):
    """Only two exact completed phases may supply the next explicit request.

    The bridge reader independently binds original guard, raw output, ledger and
    pure replay. An unprocessed completion, timeout, unknown outcome or generic
    rejection can never be promoted to one of these phases by this controller.
    """
    require(type(recovered) is dict and recovered.get('valid') is True
            and recovered.get('errors') == [] and recovered.get('saved_phase') == saved_phase,
            'original transport/replay outcome does not bind saved phase')
    choices = {
        'action_processed': ('action_already_processed_no_replay', True, False, 'action'),
        'envelope_rejected_recorded': ('envelope_rejection_already_recorded_no_replay', False, True, 'memory_size_rejection'),
    }
    require(saved_phase in choices, 'unprocessed/failed/pending call cannot continue')
    phase, action, rejection, kind = choices[saved_phase]
    require(recovered.get('phase') == phase and recovered.get('success_action_eligible') is action
            and recovered.get('rejection_record_eligible') is rejection,
            'action/rejection exact phase or eligibility differs')
    bound = recovered.get('read_only_success_binding', {})
    require(bound.get('local_channel_files_and_ledger_verified') is True and bound.get('errors') == []
            and bound.get('success_action_eligible') is action and bound.get('rejection_record_eligible') is rejection
            and bound.get('envelope', {}).get('kind') == kind
            and bound.get('process_guard', {}).get('lifecycle_complete') is True,
            'completed phase lacks its original supervised envelope binding')
    return kind


def verify_history_kind(history, kind):
    """Extra explicit route cross-check; durable replay checks all state effects."""
    require(type(history) is dict, 'missing original attempted-output row')
    if kind == 'memory_size_rejection':
        require(history.get('parsed_envelope') is None and history.get('projection') is None
                and same(history['memory_before'], history['memory_after'])
                and history['full_response'].get('status') == 'rejected'
                and history['full_response'].get('error', {}).get('code') == 'memory_size',
                'wrapper rejection acquired an action, memory change or other failure kind')
    else:
        require(kind == 'action' and type(history.get('parsed_envelope')) is dict
                and type(history.get('projection')) is dict, 'action phase lacks original request projection')


def verified_bridge_response(result, *, directory, store_id, instance_id, store_directory):
    """Read-only post-call gate. Never retries, processes or repairs a response."""
    require(type(result) is dict and result.get('errors') == [], 'original model call/processing failed; no retry')
    recovered = bridge.recover_read_only(directory, expected_intent_sha256=result['intent_sha256'],
        expected_outcome_sha256=result['outcome_sha256'])
    kind = verified_processed_kind(recovered, result.get('phase'))
    require(result.get('success_action_eligible') is (kind == 'action')
            and result.get('rejection_record_eligible') is (kind == 'memory_size_rejection')
            and result.get('call_id') == recovered['original_call_id'], 'returned bridge route differs from original outcome')
    _, evidence = export_one(store_directory, store_id=store_id, prefix=result['durable_prefix'], instance_id=instance_id)
    require(bool(evidence['history']), 'processed phase has no durable original row')
    row = evidence['history'][-1]
    verify_history_kind(row, kind)
    reply = result['interaction_response']
    require(row['call_id'] == recovered['original_call_id'] and row['record_sha256'] == reply['record_sha256']
            and row['history_index'] == reply['history_index'] and same(row['full_response'], reply['response'])
            and same(row['feedback'], reply['feedback']), 'returned response differs from verified durable original row')
    if kind == 'memory_size_rejection':
        require(evidence['selection'] is None, 'wrapper rejection cannot select a plan')
    return reply['response']


def is_selection_response(response):
    """Route only the explicit selection marker to the existing verifier.

    Catalog replies are valid dictionaries without a status field. This test
    does not authenticate a selection; durable export/equality and common commit
    validation remain mandatory in the caller.
    """
    require(type(response) is dict, 'processed interaction response must be a dictionary')
    return response.get('status') == 'selection_for_external_commit'


def _run_registered(run_id, *, expected_source_sha256, scenario=1701, seconds=3600,
        wall_seconds=21600.0, max_log_bytes=17179869184, max_trace_bytes=2147483648, page_chars=45000):
    """Explicit fresh execution only. Existing run directories always refuse."""
    started = time.monotonic()
    require(type(run_id) is str and run_id.startswith('B_') and all(c.isascii() and (c.isalnum() or c in '_-') for c in run_id), 'new B run ID required')
    require(type(scenario) is int and scenario == 1701 and type(seconds) is int and seconds == 3600, 'this endpoint is registered cold-start scenario1701/1h only')
    require(type(wall_seconds) in (int, float) and math.isfinite(wall_seconds) and wall_seconds > 0
            and type(max_log_bytes) is int and max_log_bytes > 0 and type(max_trace_bytes) is int and max_trace_bytes > 0
            and type(page_chars) is int and 10000 <= page_chars <= 90000, 'invalid explicit resource parameters')
    manifest = assert_source(expected_source_sha256)
    approval = load_json(APPROVAL)
    # A frozen launcher may explicitly bind this to the one original ledger;
    # never use BudgetLedger's import-time default from a copied source tree.
    ledger = BudgetLedger(DEFAULT_LEDGER)
    waiver = ledger.research_limit_waiver()
    require(waiver is not None, 'explicit research call/token waiver required')
    out = (ROOT / 'runs/smt_fullfab_stage2' / run_id).resolve()
    out.mkdir(parents=True, exist_ok=False)  # A crash/failure is never a resume invitation.
    cfg = {'schema': SCHEMA, 'arm': 'B', 'run_id': run_id, 'seed': scenario, 'seconds': seconds,
           'source_sha256': expected_source_sha256, 'max_calls': None, 'max_tokens': None,
           'per_call_timeout_seconds': 180, 'wall_seconds': wall_seconds, 'max_log_bytes': max_log_bytes,
           'max_trace_bytes': max_trace_bytes, 'page_chars': page_chars, 'plan_seconds': 14400,
           'lookahead_depth': 2, 'period_seconds': 1800, 'solver_budget_seconds': 0,
           'constructor_enabled': False, 'audit_mode': 'stream', 'snapshot_mode': 'stream',
           'cold_start_only': True, 'automatic_retry': False, 'formal': False,
           'budget_id': approval['budget_id'], 'amendment_id': waiver['amendment_id'],
           'resource_acceptance_requires_external_gate': True}
    write_new(out / 'claim.json', {'identity': json_sha256(cfg), 'pid': os.getpid(), 'cold_start_only': True})
    write_new(out / 'config.json', cfg)
    write_new(out / 'source_manifest.json', manifest)
    index = RunIndex(out / 'delta_index.jsonl')
    index.append('run_started', config=cfg)
    env, registration, active = None, None, None
    model_index, plan_index, failure = 0, 0, None
    local_bridge_attempts, returned_bridge_attempts, resource_account = 0, 0, None
    finalization_errors, interrupted = [], None
    bundle, summary, attribution, checkpoint = None, None, None, None
    try:
        registration = ledger.register_stage_run(run_id=str(out), arm='B', scenario=scenario,
            window_seconds=seconds, solver_seconds=0, wall_seconds=wall_seconds, max_log_bytes=max_log_bytes)
        write_new(out / 'resource_registration.json', registration)
        write_new(out / 'provenance.json', source_snapshot(out))
        write_new(out / 'response_schema.json', response_schema())
        disabled = [str(p) for p in _disabled_skills()]
        write_new(out / 'transport_isolation.json', {'disabled_skill_paths': disabled})
        env = FullFabEnvironment(seed=scenario, window_seconds=seconds, trace_path=out / 'trace.jsonl')
        while not env.finished:
            resource_check(out, started=started, wall_seconds=wall_seconds, max_log_bytes=max_log_bytes, max_trace_bytes=max_trace_bytes)
            assert_source(expected_source_sha256)
            boot = bootstrap(env, run_id=run_id, source_sha256=expected_source_sha256, page_chars=page_chars)
            directory = out / f'plan_{plan_index:05d}'
            directory.mkdir()
            boot_sha = write_new(directory / 'bootstrap.json', boot)
            store_id, instance_id = run_id + ':store:' + str(plan_index), run_id + ':instance:' + str(plan_index)
            store = durable.DurableInteractionStore.create(directory / 'durable', store_id=store_id)
            registered = store.register(instance_id, boot)
            write_new(directory / 'registration.json', registered)
            require(registered['accepted'], 'new plan interaction registration rejected')
            context = registered['value']
            active = (store, store_id, instance_id, directory)
            index.append('plan_opened', plan_index=plan_index, directory=directory.name,
                store=directory.name + '/durable', store_id=store_id, instance_id=instance_id,
                bootstrap_file_sha256=boot_sha, base_was_committed=env.plan is not None, context=context)
            while True:
                resource_check(out, started=started, wall_seconds=wall_seconds, max_log_bytes=max_log_bytes, max_trace_bytes=max_trace_bytes)
                remaining = wall_seconds - (time.monotonic() - started)
                require(remaining >= 1, 'insufficient remaining run wall for bounded model call')
                mcfg = ModelConfig(model='gpt-6-astra', reasoning_effort='medium', timeout_seconds=min(180.0, remaining),
                    ledger_path=str(DEFAULT_LEDGER.resolve()), phase=registration['phase'], grant_id=approval['budget_id'],
                    authorization_context={'purpose': 'B', 'arm': 'B', 'scenario': scenario, 'window_seconds': seconds})
                attempt_id = run_id + ':model:' + str(model_index)
                transport, evidence_dir = out / f'model_{model_index:05d}', out / f'call_{model_index:05d}'
                index.append('call_started', plan_index=plan_index, model_index=model_index, attempt_id=attempt_id,
                             transport=transport.name, evidence=evidence_dir.name)
                local_bridge_attempts += 1
                result = bridge.execute_once(store, expected_store_id=store_id, instance_id=instance_id,
                    attempt_id=attempt_id, model_index=model_index, transport_run_dir=str(transport), evidence_dir=evidence_dir,
                    config=dataclasses.asdict(mcfg), schema=response_schema(), expected_context=context,
                    authorization={'ledger_path': str(DEFAULT_LEDGER.resolve()), 'ledger_before_sha256': sha_file(DEFAULT_LEDGER),
                        'approval_sha256': record_sha256(approval), 'registration_id': registration['registration_id'],
                        'registration_sha256': record_sha256(registration), 'disabled_skill_paths': disabled},
                    transport_call=call_model, process_success=True)
                returned_bridge_attempts += 1
                index.append('call_finished', plan_index=plan_index, model_index=model_index,
                    intent_sha256=result['intent_sha256'], outcome_sha256=result['outcome_sha256'],
                    call_id=result.get('call_id'), phase=result['phase'], durable_prefix=result.get('durable_prefix'))
                model_index += 1
                response = verified_bridge_response(result, directory=evidence_dir, store_id=store_id,
                    instance_id=instance_id, store_directory=store.directory)
                if not is_selection_response(response):
                    # Queries (including status-less catalog replies), checks and
                    # rejections continue unchanged; only an explicit apply can
                    # enter the verified durable selection/commit path below.
                    continue
                prefix = proof_prefix(store, store_id)
                _, exported = export_one(store.directory, store_id=store_id, prefix=prefix, instance_id=instance_id)
                selection = exported['selection']
                require(selection is not None and same(selection, response), 'returned apply differs from verified durable selection')
                resource_check(out, started=started, wall_seconds=wall_seconds, max_log_bytes=max_log_bytes, max_trace_bytes=max_trace_bytes)
                assert_source(expected_source_sha256)
                commit_selection(env, store=store, store_id=store_id, instance_id=instance_id, selection=selection,
                    expected_bootstrap=boot, run_id=run_id, source_sha256=expected_source_sha256, page_chars=page_chars,
                    index=index, plan_index=plan_index, directory=directory)
                break
            advance_from = env.t
            advance_target = next_boundary(env.t, env.observation_start, env.horizon, cfg['period_seconds'])
            stop = env.advance_plan(advance_target)
            index.append('plan_closed', plan_index=plan_index, durable_prefix=proof_prefix(store, store_id),
                         simulation_seconds=env.t, stop=stop, advance_from=advance_from, advance_target=advance_target)
            active = None
            plan_index += 1
    except BaseException as exc:
        failure = {'type': type(exc).__name__, 'message': str(exc)}
        if not isinstance(exc, Exception):
            interrupted = exc
        write_new(out / 'failure.json', {**failure, 'traceback': traceback.format_exc(),
            'automatic_retry_permitted': False, 'pending_requires_read_only_diagnosis': True})
    finally:
        # No fresh call, action processing or physical commit occurs in finalization.
        if registration is not None:
            try:
                resource_account = capture_account(out, ledger)
                require(not resource_account['solver_call_ids'] and not resource_account['constructor_call_ids'],
                        'B original ledger contains solver/constructor work')
                if env is not None and env.finished:
                    require(resource_account['account']['attempts'] == local_bridge_attempts == returned_bridge_attempts
                            and not resource_account['account']['pending'], 'completed run original ledger does not close all calls')
            except Exception as exc:
                finalization_errors.append({'stage': 'original_ledger_capture', 'type': type(exc).__name__, 'message': str(exc)})
                failure = failure or {'type': type(exc).__name__, 'message': 'original ledger capture: ' + str(exc)}
        if not index.poisoned:
            try:
                active_proof = None if active is None else proof_prefix(active[0], active[1])
                index.append('run_stopped', finished=bool(env is not None and env.finished),
                    simulation_seconds=None if env is None else env.t, failure=failure, active_durable_prefix=active_proof,
                    account_report_sha256=None if resource_account is None else resource_account['account_report_sha256'])
            except Exception as exc:
                finalization_errors.append({'stage': 'run_index_close', 'type': type(exc).__name__, 'message': str(exc)})
                failure = failure or {'type': type(exc).__name__, 'message': str(exc)}
        if env is not None:
            try:
                checkpoint = {'path': 'checkpoint.json', 'state_sha256': write_snapshot(env, out / 'checkpoint.json')}
                checkpoint['file_sha256'] = sha_file(out / 'checkpoint.json')
            except Exception as exc:
                finalization_errors.append({'stage': 'snapshot', 'type': type(exc).__name__, 'message': str(exc)})
                failure = failure or {'type': type(exc).__name__, 'message': 'snapshot: ' + str(exc)}
        if env is not None and env.finished:
            try:
                trace_sha = sha_file(out / 'trace.jsonl')
                attribution = audit_delta_run(out, expected_index_sha256=sha_file(out / 'delta_index.jsonl'),
                    expected_source_sha256=expected_source_sha256, expected_trace_sha256=trace_sha)
                write_new(out / 'delta_attribution_audit.json', attribution)
                summary, bundle = stream_audit(out / 'trace.jsonl', out, data_dir=env.data_dir, window_start=env.observation_start)
                require(attribution['valid'] and summary['valid'] and summary['complete_physical_window_certified'], 'terminal independent audits rejected')
            except Exception as exc:
                finalization_errors.append({'stage': 'final_audit', 'type': type(exc).__name__, 'message': str(exc)})
                failure = failure or {'type': type(exc).__name__, 'message': 'final audit: ' + str(exc)}
        try:
            assert_source(expected_source_sha256)
            resource_check(out, started=started, wall_seconds=wall_seconds, max_log_bytes=max_log_bytes, max_trace_bytes=max_trace_bytes)
        except Exception as exc:
            finalization_errors.append({'stage': 'final_resources_source', 'type': type(exc).__name__, 'message': str(exc)})
            failure = failure or {'type': type(exc).__name__, 'message': 'final resources/source: ' + str(exc)}
        try:
            account = ledger.summary(run_id=str(out)) if registration else None
            if resource_account is not None:
                require(same(account, resource_account['account']), 'actual run account changed during final audits')
        except Exception as exc:
            account = None
            finalization_errors.append({'stage': 'budget_readback', 'type': type(exc).__name__, 'message': str(exc)})
            failure = failure or {'type': type(exc).__name__, 'message': 'budget readback: ' + str(exc)}
        result = {'schema': SCHEMA + '-result', 'config': cfg, 'identity': json_sha256(cfg),
            'status': 'completed' if env is not None and env.finished and not failure else 'failed',
            'failure': None if failure is None else failure['type'] + ': ' + failure['message'],
            'finalization_errors': finalization_errors,
            'simulation_seconds': None if env is None else env.t, 'plans': plan_index,
            'model_calls': None if account is None else account['attempts'],
            'local_bridge_attempts': local_bridge_attempts, 'returned_bridge_attempts': returned_bridge_attempts,
            'next_local_model_index': model_index,
            'reserve_call_ids': None if resource_account is None else resource_account['reserve_call_ids'],
            'pending_call_ids': None if account is None else account['pending'],
            'unknown_usage_call_ids': None if account is None else account['unknown_completed'],
            'model_account': account, 'solver_calls': 0, 'constructor_calls': 0,
            'audit_valid': bool(summary and summary['valid'] and attribution and attribution['valid']),
            'audit_bundle': bundle, 'metrics': None if summary is None else summary['metrics'],
            'delta_attribution_valid': bool(attribution and attribution['valid']), 'checkpoint': checkpoint,
            'index_sha256': sha_file(out / 'delta_index.jsonl'), 'source_sha256': expected_source_sha256,
            'end_to_end_wall_seconds': time.monotonic() - started, 'formal': False,
            'end_to_end_wall_scope': 'sample through snapshot, audits, source/resource checks and initial result encoding; excludes final encoding/publication/hash/stdout/process exit, measured by enclosing child supervisor',
            'accepted': False, 'acceptance_scope': 'execution report only; frozen outer gate must accept complete process costs and evidence',
            'remaining_memory_limits': ['environment trace/jobs in RAM', 'one complete durable interaction export', 'audit output arrays'],
            'automatic_recovery_or_retry': False}
        include_result_bytes(result, existing_bytes=_tree_bytes(out), limit=max_log_bytes)
        # Include audit/snapshot/result construction and encoding in measured wall;
        # publication, final file hashing and process exit belong to the outer gate.
        result['end_to_end_wall_seconds'] = time.monotonic() - started
        if result['end_to_end_wall_seconds'] > wall_seconds:
            result['status'] = 'failed'
            result['failure'] = (result['failure'] + '; ' if result['failure'] else '') + 'final complete endpoint wall limit'
        include_result_bytes(result, existing_bytes=_tree_bytes(out), limit=max_log_bytes)
        write_new(out / 'result.json', result)
    if interrupted is not None:
        raise interrupted
    return result


def run(*args, **kwargs):
    """New endpoint awaits a separately reviewed supervised gate/protocol."""
    raise RuntimeError('B delta v4 public execution blocked: a reviewed new guard/gate must explicitly call _run_registered; no old run/store migration')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    execute = sub.add_parser('run', help='explicit new cold-start B development execution; refuses every existing run')
    execute.add_argument('--run-id', required=True)
    execute.add_argument('--expected-source-sha256', required=True)
    execute.add_argument('--wall-seconds', type=float, default=21600)
    execute.add_argument('--max-log-bytes', type=int, default=17179869184)
    execute.add_argument('--max-trace-bytes', type=int, default=2147483648)
    inspect = sub.add_parser('audit', help='read-only original-evidence attribution; no recovery execution')
    inspect.add_argument('--run-dir', type=Path, required=True)
    inspect.add_argument('--expected-source-sha256', required=True)
    inspect.add_argument('--expected-index-sha256', required=True)
    inspect.add_argument('--expected-trace-sha256', required=True)
    args = parser.parse_args()
    if args.command == 'run':
        result = run(args.run_id, expected_source_sha256=args.expected_source_sha256, wall_seconds=args.wall_seconds,
                     max_log_bytes=args.max_log_bytes, max_trace_bytes=args.max_trace_bytes)
    else:
        result = audit_delta_run(args.run_dir, expected_source_sha256=args.expected_source_sha256,
            expected_index_sha256=args.expected_index_sha256, expected_trace_sha256=args.expected_trace_sha256)
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
    return 0 if result.get('status') == 'completed' or result.get('valid') is True else 1


if __name__ == '__main__':
    raise SystemExit(main())
