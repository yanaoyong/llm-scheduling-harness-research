"""Saved-evidence attribution for one preserved V8 Interaction, then fresh plans.

Derived from B_v8_launch_recovery.acceptance. No launch/restore/commit/repair.
Caller must supply externally sealed inventories and the frozen original/new
reader implementations. A producer's inventory alone is not external evidence.
This full-RAM snapshot/index audit is not a streaming long-window implementation.
"""
from base64 import b64decode
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import time

SCHEMA = 'smt-B-v8-preserved-attribution-installed-v1'
REFS_SCHEMA = 'smt-B-v8-preserved-attribution-sealed-refs-v1'
INVENTORY_SCHEMA = 'smt-B-v8-preserved-attribution-inventory-v1'
LAUNCH_BLOCKERS = ('no standalone launch; complete external freeze, admission and actual resource acceptance required',)


def need(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(',', ':')).encode()


def same(left, right):
    return canonical(left) == canonical(right)


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _bound(path, expected):
    path = Path(path)
    need(path.is_absolute() and path == path.resolve(), 'canonical absolute evidence path required')
    before = _identity(path.stat())
    with path.open('rb') as stream:
        need(_identity(os.fstat(stream.fileno())) == before, 'evidence changed before open')
        raw = stream.read()
        need(_identity(os.fstat(stream.fileno())) == before, 'evidence changed during read')
    need(_identity(path.stat()) == before, 'evidence path replaced')
    need(hashlib.sha256(raw).hexdigest() == expected, 'original evidence SHA mismatch: ' + str(path))
    return raw, before


class Evidence:
    """Only external original hashes; never harvest current bytes as new anchors."""
    def __init__(self, refs_path, expected_refs_sha256):
        raw, identity = _bound(refs_path, expected_refs_sha256)
        self.refs = json.loads(raw)
        need(self.refs['schema'] == REFS_SCHEMA, 'unknown sealed references schema')
        self.anchors = {str(Path(refs_path)): (expected_refs_sha256, identity)}
        inv = self.refs['inventory']
        raw, identity = _bound(inv['path'], inv['sha256'])
        self.anchors[inv['path']] = (inv['sha256'], identity)
        inventory = json.loads(raw)
        need(inventory['schema'] == INVENTORY_SCHEMA and type(inventory['files']) is dict,
             'external full-run inventory required')
        self.files = inventory['files']
        for path, ref in self.files.items():
            need(type(ref) is dict and set(ref) == {'sha256', 'bytes'}, 'inventory entry shape')
            raw, identity = _bound(path, ref['sha256'])
            need(type(ref['bytes']) is int and len(raw) == ref['bytes'], 'inventory byte count')
            self.anchors[path] = (ref['sha256'], identity)

    def raw(self, path):
        key = str(Path(path))
        need(key in self.files, 'file missing from external inventory: ' + key)
        raw, identity = _bound(key, self.files[key]['sha256'])
        need(identity == self.anchors[key][1] and len(raw) == self.files[key]['bytes'],
             'original evidence identity changed')
        return raw

    def read(self, path):
        return json.loads(self.raw(path))

    def ref(self, ref):
        need(self.files.get(ref['path'], {}).get('sha256') == ref['sha256'],
             'reference differs from first external inventory')
        return self.read(ref['path'])

    def fence(self):
        for path, (sha, expected_identity) in self.anchors.items():
            _, identity = _bound(path, sha)
            need(identity == expected_identity, 'original evidence replaced before report')


def _index(rows, *, first_model_index, require_complete):
    need(type(first_model_index) is int and first_model_index >= 188, 'explicit first index required')
    need(rows and rows[0]['event'] == 'resume_started' and rows[-1]['event'] == 'resume_stopped',
         'unclosed segment index')
    opened, closed, calls, finishes, intents, receipts = {}, {}, {}, {}, {}, {}
    for row in rows[1:-1]:
        event, p = row['event'], row['payload']; pi = p['plan_index']
        if event == 'plan_opened':
            need(type(pi) is int and pi == len(opened)+1 and (pi == 1 or pi-1 in closed),
                 'segment plans not continuous from1')
            opened[pi] = p
        elif event == 'call_started':
            mi = p['model_index']
            need(type(mi) is int and mi == first_model_index+len(calls) and pi in opened and pi not in closed,
                 'global call reset/reuse')
            need(mi == first_model_index or mi-1 in finishes, 'unresolved preceding new call')
            need(p['attempt_id'] == opened[pi]['branch_id']+':model:'+str(mi), 'wrong call branch')
            calls[mi] = p
        elif event == 'call_finished':
            mi = p['model_index']
            need(type(mi) is int and mi in calls and mi not in finishes and calls[mi]['plan_index'] == pi,
                 'unmatched call finish')
            finishes[mi] = p
        elif event in ('commit_intent', 'commit_finished', 'plan_closed'):
            target = {'commit_intent': intents, 'commit_finished': receipts, 'plan_closed': closed}[event]
            need(pi in opened and pi not in closed and pi not in target, 'duplicate/stale plan completion')
            if event == 'commit_finished': need(pi in intents, 'receipt before intent')
            if event == 'plan_closed': need(pi in receipts, 'advance before explicit receipt')
            target[pi] = p
        else:
            raise ValueError('unexpected segment event: '+event)
    need(set(calls) == set(finishes), 'unclosed original call: no repair or replay')
    if require_complete:
        need(set(opened) == set(closed) == set(intents) == set(receipts), 'unfinished new plan')
    return opened, closed, calls, finishes, intents, receipts


def _markers(original_snapshot, direct_snapshot, original_events, direct_events, *, state_digest):
    """Narrow no-new-physical-action profile, exact original types and full state."""
    for snapshot, events in ((original_snapshot, original_events), (direct_snapshot, direct_events)):
        need(snapshot['schema'] == 'smt-fullfab-snapshot-1'
             and state_digest(snapshot['state']) == snapshot['state_sha256']
             and same(snapshot['state']['trace'], events), 'checkpoint/full trace differs')
    old, direct = original_snapshot['state'], direct_snapshot['state']
    need(old['finished'] is False and direct['finished'] is False
         and same(old['t'], 803.2499999999999) and same(old['horizon'], 3600.0)
         and same(old['observation_start'], 0.0), 'original physical profile differs')
    for key in ('schema', 'version', 'implementation_sha256', 'physics_sha256', 'data_hashes', 'random_mechanism'):
        need(same(original_snapshot[key], direct_snapshot[key]), 'physical dependency/type changed: '+key)
    first = {'seq':len(original_events), 'time':old['t'], 'kind':'snapshot_loaded',
             'snapshot_sha256':original_snapshot['state_sha256'], 'prefix_event_count':len(original_events)}
    need(not any(e['kind'] == 'snapshot_loaded' for e in original_events), 'V7 prefix already has restore marker')
    need(same(direct_events, original_events+[first]), 'direct parent is not exact original prefix plus one restore')
    state = deepcopy(direct); state['trace'].pop()
    need(same(state, old), 'zero-commit parent changed physical state')
    second = {'seq':len(direct_events), 'time':direct['t'], 'kind':'snapshot_loaded',
              'snapshot_sha256':direct_snapshot['state_sha256'], 'prefix_event_count':len(direct_events)}
    return {first['seq']:first, second['seq']:second}


def _history_prefix(inherited, combined, suffix_indices):
    need(same(combined[:len(inherited)], inherited), 'inherited history changed or reinterpreted')
    need(same([h['model_index'] for h in combined[len(inherited):]], suffix_indices),
         'new history omitted, duplicated or absorbed unprocessed call')
    need(len({h['model_index'] for h in combined}) == len(combined)
         and len({h['call_id'] for h in combined}) == len(combined), 'history identity reused')


def _parent_prefix(evidence, *, saved, preserved_parent, pdir, item, finishes, first_index):
    """Use the original last outcome/index and sealed cold proof, never edit result."""
    summary = evidence.ref(evidence.refs['parent_cold_proof'])
    need(summary['schema'] == 'smt-B-v8-preserved-parent-proof-v1' and summary['valid'] is True
         and summary['processed_boundary_eligible'] is True
         and summary['parent_run'] == str(preserved_parent)
         and summary['parent_store_id'] == item['store_id']
         and summary['next_unique_model_index'] == first_index
         and summary['pending_attempt_id'] is None and summary['selection'] is None
         and summary['intent_present'] is False and summary['receipt_present'] is False,
         'external complete processed parent boundary differs')
    last = max(finishes)
    need(type(last) is int and last + 1 == first_index
         and finishes[last]['phase'] in ('action_processed', 'envelope_rejected_recorded'),
         'last original processed call is not the exact continuation boundary')
    outcome = evidence.ref({'path':str(preserved_parent/f'call_{last:05d}'/'outcome.json'),
                            'sha256':finishes[last]['outcome_sha256']})
    prefix = outcome['durable_prefix']
    need(type(prefix) is dict and set(prefix) == {'journal_records','journal_tail_sha256','database_sha256'}
         and type(prefix['journal_records']) is int and prefix['journal_records'] >= 2
         and outcome['call_id'] == finishes[last]['call_id']
         and outcome['phase'] == finishes[last]['phase'] and outcome['errors'] == []
         and same(prefix, summary['expected_prefix'])
         and evidence.files[str(pdir/'durable'/'ledger.sqlite3')]['sha256'] == prefix['database_sha256'],
         'original last outcome/index/full database/cold proof differ')
    if 'final_active_prefix' in saved:
        need(same(saved['final_active_prefix'], prefix), 'saved parent prefix differs')
    else:
        need(summary['original_result_final_active_prefix_missing'] is True,
             'missing original prefix was not independently recorded')
    return deepcopy(prefix)


def _preserved_instances(parent_instances, new_instance, interaction_id):
    need(type(parent_instances) is dict and parent_instances
         and new_instance not in parent_instances
         and set(parent_instances.values()) == {interaction_id}, 'parent/new instance aliases differ')
    return {**parent_instances, new_instance:interaction_id}


def _ancestor_ledger(raw, terminal_raw):
    need(type(raw) is bytes and raw and raw.endswith(b'\n') and terminal_raw.startswith(raw),
         'original complete parent ledger is not the exact terminal byte prefix')
    rows = [json.loads(line) for line in raw.splitlines()]
    need(all(type(row) is dict for row in rows), 'original parent ledger rows differ')
    return rows


def _ledger_for_owner(owner, preserved_parent, *, parent_ref, terminal_ref, parent_rows, call_id):
    if owner == preserved_parent:
        need(sum(r.get('event') == 'reserve' and r.get('call_id') == call_id for r in parent_rows) == 1
             and sum(r.get('event') == 'finish' and r.get('call_id') == call_id for r in parent_rows) == 1,
             'ancestor call lacks original unique reserve/finish in closed parent snapshot')
        return parent_ref
    return terminal_ref


def _parent_channel_calls(evidence, *, preserved_parent, inherited, parent_ledger_ref, interaction_evidence_sha256):
    """Consume the externally sealed original-namespace check, not a producer bool."""
    proof = evidence.ref(evidence.refs['parent_channel_proof'])
    need(proof['schema'] == 'smt-B-v8-preserved-parent-channel-proof-v1'
         and proof['valid'] is True and proof['accepted'] is False and proof['errors'] == []
         and proof['parent_run'] == str(preserved_parent)
         and same(proof['parent_cold_proof'], evidence.refs['parent_cold_proof'])
         and same(proof['parent_ledger_snapshot'], parent_ledger_ref)
         and proof['interaction_evidence_sha256'] == interaction_evidence_sha256
         and proof['history_count'] == len(inherited)
         and proof['model_calls'] == proof['ledger_writes'] == proof['physical_operations'] == 0,
         'external original-parent channel proof differs')
    need(set(proof['calls']) == {str(h['model_index']) for h in inherited},
         'parent channel proof omits or adds original actions')
    for path, ref in proof['input_files'].items():
        need(evidence.files.get(path) == ref, 'parent channel input differs from original whole inventory')
        evidence.raw(path)
    return proof['calls']


def _certified_parent_call(evidence, certified, *, h, record, prompt, schema_raw, intent, outcome, finished):
    expected = {'model_index':h['model_index'], 'call_id':h['call_id'],
        'history_record_sha256':h['record_sha256'], 'prompt_sha256':hashlib.sha256(prompt).hexdigest(),
        'schema_sha256':hashlib.sha256(schema_raw).hexdigest(), 'raw_output_sha256':h['raw_output_sha256'],
        'result_sha256':record, 'intent_sha256':intent, 'outcome_sha256':outcome, 'phase':finished['phase']}
    need(all(same(certified.get(k), v) for k,v in expected.items()),
         'certified original-parent call bytes/history differ')
    report = evidence.ref(certified['binding_report'])
    need(report['local_channel_files_and_ledger_verified'] is True and report['errors'] == [],
         'original-source parent binder did not verify the call')
    for file_ref in report['files'].values():
        need(evidence.files.get(file_ref['path']) == {'sha256':file_ref['sha256'], 'bytes':file_ref['bytes']},
             'certified original raw channel changed')
        evidence.raw(file_ref['path'])
    return certified['kind']


def attribution(out, *, parent, preserved_parent, controller, parent_api, continuation_api,
                continuation_store, continuation_runtime, fresh_api, transport, ledger_path,
                admission_module, admission_kwargs, sealed_refs_path, expected_sealed_refs_sha256):
    """Complete saved-evidence read. Returns evidence only, never accepted or repairs.

    parent is original V7. preserved_parent is closed corrected-permission V8.
    APIs are explicit frozen dependencies; parent_api keeps its ORIGINAL admission
    configuration. continuation_api is only for the new first logical plan.
    """
    need(fresh_api is not None, 'later observations require implemented fresh bridge')
    out, parent, preserved_parent, ledger_path = map(Path, (out, parent, preserved_parent, ledger_path))
    evidence = Evidence(sealed_refs_path, expected_sealed_refs_sha256); refs = evidence.refs
    need(same(refs['run_paths'], {'original':str(parent), 'preserved':str(preserved_parent), 'new':str(out)}),
         'sealed ancestry/run paths differ')
    class ReadOnlyLedger(transport.BudgetLedger):
        def reserve(self, **kwargs): raise ValueError('audit cannot reserve a model request')
        def finish(self, *args, **kwargs): raise ValueError('audit cannot repair a ledger completion')
    for role, module in (('controller', controller), ('parent_api', parent_api),
                         ('continuation_api', continuation_api), ('continuation_store', continuation_store),
                         ('continuation_runtime', continuation_runtime),
                         ('fresh_api', fresh_api), ('transport', transport), ('admission_module', admission_module)):
        ref = refs['runtime_modules'][role]
        need(str(Path(module.__file__).resolve()) == ref['path']
             and evidence.files.get(ref['path'], {}).get('sha256') == ref['sha256'],
             'frozen checker module identity differs: '+role)
        evidence.raw(ref['path'])
    begun = time.monotonic(); raw_ledger = ledger_path.read_bytes()
    ledger = [json.loads(line) for line in raw_ledger.splitlines()]
    ledger_ref = refs['ledger_snapshot']; saved_ledger = evidence.raw(ledger_ref['path'])
    need(hashlib.sha256(saved_ledger).hexdigest() == ledger_ref['sha256'] and saved_ledger == raw_ledger,
         'full actual terminal ledger differs from external original snapshot')
    parent_ledger_ref = refs['parent_ledger_snapshot']
    parent_ledger_raw = evidence.raw(parent_ledger_ref['path'])
    need(hashlib.sha256(parent_ledger_raw).hexdigest() == parent_ledger_ref['sha256'],
         'original closed parent ledger SHA differs')
    parent_ledger_rows = _ancestor_ledger(parent_ledger_raw, raw_ledger)
    approvals = [r['approval'] for r in ledger if r.get('event') == 'approval']
    need(len(approvals) == 1, 'original unique approval missing')
    account = admission_module.audit_admissions(ledger, approvals[0], **admission_kwargs)
    need(not account['errors'] and not account['missing_evidence']
         and str(out) in account['registered_runs'] and account['segment_account']['pending'] == []
         and account['segment_account']['pending_solver_calls'] == []
         and account['segment_account']['pending_constructor_calls'] == [], 'full original admission/account not closed')
    read = evidence.read; strict_same, state_digest = controller.same, controller.json_sha256
    result, prior, saved = read(out/'result.json'), read(parent/'result.json'), read(preserved_parent/'result.json')
    need(prior['status'] == 'failed' and prior['accepted'] is False and saved['status'] == 'failed'
         and saved['accepted'] is False and saved['new_commits'] == saved['complete_commit_receipts'] == 0
         and strict_same(saved['simulation_seconds'], 803.2499999999999), 'closed zero-commit parent profile differs')
    need(result['status'] == 'completed_pending_external_audit' and result['full_window_completed'] is True
         and result['simulation_seconds'] == result['horizon_seconds'] == 3600.0, 'new segment not terminal')
    need(result['config']['model'] == 'gpt-6-astra' and result['config']['reasoning_effort'] == 'medium', 'model changed')
    first_index = refs['first_new_model_index']
    need(type(first_index) is int and first_index > 188 and strict_same(saved['next_global_model_index'], first_index),
         'sealed terminal next index differs')
    def load_index(path, sha):
        need(hashlib.sha256(evidence.raw(path)).hexdigest() == sha, 'index external anchor differs')
        return controller.read_index(path, expected_sha256=sha)
    rows = load_index(out/'resume_index.jsonl', result['index_sha256'])
    parentrows = load_index(preserved_parent/'resume_index.jsonl', saved['index_sha256'])
    oldrows = load_index(parent/'delta_index.jsonl', prior['index_sha256'])
    opened, closed, calls, finishes, intents, receipts = _index(rows, first_model_index=first_index, require_complete=True)
    popen, pclose, pcalls, pfinishes, pintents, preceipts = _index(parentrows, first_model_index=188, require_complete=False)
    need(set(popen) == {1} and not pclose and not pintents and not preceipts and pcalls
         and first_index == max(pcalls)+1, 'preserved first Interaction is not the no-commit profile')
    need(saved['new_attempts_entered'] == len(pcalls) and result['new_commits'] == len(opened)
         and result['new_attempts_entered'] == len(calls), 'actual index counts differ')
    for pi, item in opened.items():
        need(item['store_id'] == item['branch_id'] == out.name+':branch:'+str(pi)
             and item['instance_id'] == item['branch_id']+':instance', 'new branch identity differs')
    pitem = popen[1]; pdir = preserved_parent/'plan_00001'
    pboot = read(pdir/'bootstrap.json')
    need(state_digest(pboot) == state_digest(evidence.ref({'path':str(pdir/'bootstrap.json'),
         'sha256':pitem['bootstrap_file_sha256']})), 'parent bootstrap anchor differs')
    parent_prefix = _parent_prefix(evidence, saved=saved, preserved_parent=preserved_parent, pdir=pdir,
                                  item=pitem, finishes=pfinishes, first_index=first_index)
    pproof = parent_api.durable.export_verified_interaction(pdir/'durable', expected_store_id=pitem['store_id'],
                                                           expected_prefix=parent_prefix)
    need(pproof['valid'] and pproof['pure_replay_verified'] and len(pproof['interactions']) == 1,
         'complete original parent pure replay required')
    pev = pproof['interactions'][0]['evidence']
    need(pproof['instances'] == {pitem['instance_id']:pproof['interactions'][0]['interaction_id']}
         and strict_same(pev['bootstrap'], pboot)
         and strict_same({k:pev[k] for k in pitem['context']}, pitem['context']) and pev['selection'] is None,
         'original Interaction/bootstrap or uncommitted selection differs')
    need(strict_same({k:pproof[k] for k in ('journal_records','journal_tail_sha256','database_sha256')},
                     parent_prefix)
         and evidence.files[str(pdir/'durable'/'ledger.sqlite3')]['sha256'] == pproof['database_sha256'],
         'parent complete DB differs from original final prefix/inventory')
    inherited = pev['history']; inherited_by_index = {h['model_index']:h for h in inherited}
    need(len(inherited_by_index) == len(inherited), 'duplicate parent history index')
    processed_indices = [mi for mi, f in pfinishes.items() if f['phase'] in ('action_processed', 'envelope_rejected_recorded')]
    need(list(inherited_by_index) == processed_indices, 'all accepted and rejected parent actions must be inherited exactly')
    certified_parent_calls = _parent_channel_calls(evidence, preserved_parent=preserved_parent,
        inherited=inherited, parent_ledger_ref=parent_ledger_ref,
        interaction_evidence_sha256=continuation_runtime.digest(pev))
    plan_refs = refs['plan_manifests']
    need(set(plan_refs) == {str(pi) for pi in opened}, 'each and only committed new plan needs original manifest')
    cmref = plan_refs['1']; cmanifest = evidence.ref(cmref)
    need(Path(cmref['path']) == out/'plan_00001'/'durable'/'continuation_manifest.json', 'continuation manifest outside first store')
    need(cmanifest['schema'] == continuation_store.SCHEMA
         and cmanifest['parent_store_id'] == pitem['store_id']
         and cmanifest['parent_database_path'] == str(pdir/'durable'/'ledger.sqlite3')
         and strict_same(cmanifest['parent_prefix'], parent_prefix)
         and cmanifest['parent_interaction_evidence_sha256'] == continuation_runtime.digest(pev)
         and cmanifest['parent_bootstrap_sha256'] == continuation_runtime.digest(pboot)
         and cmanifest['first_new_model_index'] == first_index
         and cmanifest['last_parent_model_index'] == max(pcalls)
         and cmanifest['segment_run_path'] == str(out)
         and cmanifest['external_authorization_sha256'] == refs['external_authorization_sha256'],
         'continuation is not bound to this complete original parent and new identity')
    need(cmanifest['profile'] == refs['continuation_profile'], 'externally selected continuation profile differs')
    unprocessed = [mi for mi in pcalls if mi not in inherited_by_index]
    if cmanifest['profile'] == 'processed_boundary':
        need(not unprocessed and all(cmanifest[k] is None for k in
             ('failed_attempt_id', 'failed_call_id', 'failed_model_index', 'failed_status')), 'clean boundary hides failed tail')
    else:
        need(cmanifest['profile'] == 'terminal_failed_no_final' and unprocessed == [max(pcalls)]
             and cmanifest['failed_model_index'] == unprocessed[0]
             and cmanifest['failed_attempt_id'] == pcalls[unprocessed[0]]['attempt_id']
             and cmanifest['failed_call_id'] == pfinishes[unprocessed[0]]['call_id'], 'failed-tail original identity differs')
    def replay_transport(owner, mi, h=None):
        d = owner/f'model_{mi:05d}'; raw_result = evidence.raw(d/'result.json'); record = json.loads(raw_result)
        need(sum(r.get('event') == 'finish' and r.get('call_id') == record['call_id'] for r in ledger) == 1,
             'exact original finish required; audit cannot repair it')
        prompt = evidence.raw(d/'prompt.txt'); schema = read(d/'schema.json')
        verified = transport.call_model(prompt.decode(), schema, d, record['config'], resume=True, ledger_factory=ReadOnlyLedger)
        need(strict_same(verified, record) and evidence.raw(d/'result.json') == raw_result, 'original transport verification differs')
        if h is not None:
            final = evidence.raw(d/'final.txt')
            need(record['status'] == 'success' and record['call_id'] == h['call_id']
                 and b64decode(h['raw_output_base64'], validate=True) == final
                 and hashlib.sha256(final).hexdigest() == h['raw_output_sha256']
                 and hashlib.sha256(prompt).hexdigest() == h['issued_prompt_sha256'], 'history differs from original channel bytes')
        return d, record, prompt, schema
    def verify_processed(owner, mi, h, item, issued, finished, api):
        d, record, prompt, schema = replay_transport(owner, mi, h)
        need(issued['transport'] == d.name and issued['evidence'] == f'call_{mi:05d}'
             and finished['call_id'] == h['call_id'], 'call attribution remapped')
        ed = owner/issued['evidence']; bi = evidence.ref({'path':str(ed/'intent.json'), 'sha256':finished['intent_sha256']})
        bo = evidence.ref({'path':str(ed/'outcome.json'), 'sha256':finished['outcome_sha256']})
        need(bi['expected_store_id'] == item['store_id'] and bi['instance_id'] == item['instance_id']
             and bi['attempt_id'] == issued['attempt_id'] and bi['transport_run_dir'] == str(d)
             and strict_same(bi['config'], record['config']) and strict_same(bi['expected_context'], item['context']),
             'original bridge identity/config/context differs')
        need(api.intent_schema_bytes(bi) == evidence.raw(d/'schema.json'), 'original dynamic schema bytes differ')
        auth = bi['authorization']
        call_ledger_ref = _ledger_for_owner(owner, preserved_parent, parent_ref=parent_ledger_ref,
            terminal_ref=ledger_ref, parent_rows=parent_ledger_rows, call_id=h['call_id'])
        if owner == preserved_parent:
            certified_kind = _certified_parent_call(evidence, certified_parent_calls[str(mi)], h=h,
                record=hashlib.sha256(evidence.raw(d/'result.json')).hexdigest(), prompt=prompt,
                schema_raw=evidence.raw(d/'schema.json'), intent=finished['intent_sha256'],
                outcome=finished['outcome_sha256'], finished=finished)
        else:
            bound = api.binding.bind_original_call(run_dir=str(d), expected_run_dir=str(d), expected_prompt=prompt.decode(),
                expected_schema=schema, expected_config=record['config'], ledger_snapshot_path=call_ledger_ref['path'],
                ledger_source_path=auth['ledger_path'], expected_ledger_sha256=call_ledger_ref['sha256'],
                expected_approval_record_sha256=auth['approval_sha256'], expected_registration_id=auth['registration_id'],
                expected_registration_record_sha256=auth['registration_sha256'], expected_interaction_context=item['context'],
                expected_disabled_skill_paths=auth['disabled_skill_paths'])
            need(bound.report['local_channel_files_and_ledger_verified'] and not bound.report['errors'], 'original guarded channel/authority failed')
            certified_kind = None
        classified = api.binding.verify_envelope(record['output'], prompt.decode(), item['context'], schema)
        kind = classified['kind']
        if owner == preserved_parent:
            need(kind == certified_kind, 'original parent envelope classification changed')
        need(finished['phase'] == ('action_processed' if kind == 'action' else 'envelope_rejected_recorded'), 'wrong saved route')
        controller.verify_history_kind(h, kind)
        need(bo['call_id'] == h['call_id'] and bo['phase'] == finished['phase'] and not bo['errors'], 'bridge outcome conflicts')
        return record['call_id'], bi
    # All direct-parent calls remain accountable, including the terminal unprocessed tail.
    parent_verified = {}
    for mi in pcalls:
        if mi in inherited_by_index:
            cid, _ = verify_processed(preserved_parent, mi, inherited_by_index[mi], pitem, pcalls[mi], pfinishes[mi], parent_api)
            parent_verified[mi] = cid
        else:
            d, record, _, _ = replay_transport(preserved_parent, mi)
            finish = pfinishes[mi]; ed = preserved_parent/pcalls[mi]['evidence']
            outcome = evidence.ref({'path':str(ed/'outcome.json'), 'sha256':finish['outcome_sha256']})
            checked = parent_api.recover_read_only(ed, expected_intent_sha256=finish['intent_sha256'],
                                                   expected_outcome_sha256=finish['outcome_sha256'])
            need(record['status'] in ('failed', 'timeout') and record['output'] is None
                 and not (d/'final.txt').exists() and cmanifest['failed_status'] == record['status'],
                 'only sealed original terminal failed/no-final tail can be excluded')
            need(checked['valid'] and checked['original_call_id'] == record['call_id'] == finish['call_id']
                 and checked['phase'] not in ('action_already_processed_no_replay', 'envelope_rejection_already_recorded_no_replay')
                 and outcome['phase'] == finish['phase'], 'unprocessed parent tail was repaired or omitted')
    old = {name:{r['payload']['plan_index']:r['payload'] for r in oldrows if r['event'] == name}
           for name in ('plan_opened', 'plan_closed', 'commit_intent', 'commit_finished')}
    need(set(old['commit_finished']) == {0}, 'V7 committed prefix differs')
    plans = {}; checked_calls = {}
    for pi in [0, *opened]:
        owner = parent if pi == 0 else out
        item = old['plan_opened'][0] if pi == 0 else opened[pi]
        close = old['plan_closed'][0] if pi == 0 else closed[pi]
        intent = old['commit_intent'][0] if pi == 0 else intents[pi]
        receipt_ref = old['commit_finished'][0] if pi == 0 else receipts[pi]
        directory = owner/f'plan_{pi:05d}'
        need(item['directory'] == directory.name, 'plan directory remapping')
        boot = evidence.ref({'path':str(directory/'bootstrap.json'), 'sha256':item['bootstrap_file_sha256']})
        if pi == 0:
            proof, ev = controller.export_one(directory/'durable', store_id=item['store_id'], prefix=close['durable_prefix'], instance_id=item['instance_id'])
        elif pi == 1:
            proof = continuation_store.recover_read_only(directory/'durable', runtime=continuation_runtime,
                expected_manifest_sha256=cmref['sha256'], expected_prefix=close['durable_prefix'])
            need(proof['valid'] and proof['pure_replay_verified'] and proof['lineage_verified']
                 and proof['verification_mode'] == 'full_parent_and_descendant_reference'
                 and proof['parent_store_id'] == pitem['store_id'] and proof['store_id'] == item['store_id']
                 and proof['continuation_manifest_sha256'] == cmref['sha256'], 'complete continuation lineage failed')
            need(proof['logical_plan_kind'] == 'preserved', 'first plan must preserve the original Interaction')
            need(len(proof['interactions']) == 1, 'ambiguous continuation interaction')
            ev = proof['interactions'][0]['evidence']
            need(proof['instances'] == _preserved_instances(pproof['instances'], item['instance_id'],
                                                          proof['interactions'][0]['interaction_id'])
                 and strict_same(boot, pboot), 'preserved first observation/instance differs')
        else:
            current_ref = plan_refs[str(pi)]; current_manifest = evidence.ref(current_ref)
            need(Path(current_ref['path']) == directory/'durable'/'continuation_manifest.json'
                 and current_manifest['schema'] == continuation_store.FRESH_SCHEMA,
                 'later plan lacks frozen fresh-after-commit manifest')
            proof = continuation_store.recover_read_only(directory/'durable', runtime=continuation_runtime,
                expected_manifest_sha256=current_ref['sha256'], expected_prefix=close['durable_prefix'])
            need(proof['valid'] and proof['pure_replay_verified'] and proof['lineage_verified']
                 and proof['verification_mode'] == 'full_fresh_after_commit_reference'
                 and proof['logical_plan_kind'] == 'fresh_after_commit'
                 and proof['store_id'] == item['store_id']
                 and proof['parent_store_id'] == opened[pi-1]['store_id']
                 and proof['previous_directory'] == str(out/f'plan_{pi-1:05d}'/'durable')
                 and proof['previous_manifest_sha256'] == plan_refs[str(pi-1)]['sha256']
                 and proof['continuation_manifest_sha256'] == current_ref['sha256']
                 and strict_same(current_manifest['previous_prefix'], closed[pi-1]['durable_prefix'])
                 and len(proof['interactions']) == 1, 'complete later fresh-after-commit lineage failed')
            ev = proof['interactions'][0]['evidence']
            need(proof['instances'] == {item['instance_id']:proof['interactions'][0]['interaction_id']}, 'later fresh instance differs')
        if pi:
            need(strict_same({k:proof[k] for k in ('journal_records','journal_tail_sha256','database_sha256')},
                             close['durable_prefix']), 'final plan proof must be exact complete DB, not an older prefix')
        need(proof['valid'] and proof['pure_replay_verified'] and strict_same(ev['bootstrap'], boot)
             and strict_same({k:ev[k] for k in item['context']}, item['context']), 'complete pure interaction differs')
        histories = ev['history']; suffix = [mi for mi,p in calls.items() if p['plan_index'] == pi] if pi else []
        expected_inherited = inherited if pi == 1 else []
        if pi == 0: need([h['model_index'] for h in histories] == list(range(79)), 'original 79-history committed plan changed')
        else: _history_prefix(expected_inherited, histories, suffix)
        for h in histories:
            mi = h['model_index']
            if pi == 0:
                _, record, _, _ = replay_transport(parent, mi, h); cid = record['call_id']
            elif mi in inherited_by_index:
                need(pi == 1 and strict_same(h, inherited_by_index[mi]), 'ancestor action moved to another observation')
                cid = parent_verified[mi]
            else:
                api = continuation_api if pi == 1 else fresh_api
                cid, bi = verify_processed(out, mi, h, item, calls[mi], finishes[mi], api)
                need(bi['continuation_manifest_sha256'] == plan_refs[str(pi)]['sha256']
                     and bi['external_authorization_sha256'] == refs['external_authorization_sha256'],
                     'new continuation/fresh authorization remapped')
            need(mi not in checked_calls and cid not in checked_calls.values(), 'model action reused across observations')
            checked_calls[mi] = cid
        selection = ev['selection']; need(selection and selection['status'] == 'selection_for_external_commit', 'missing explicit apply')
        plan = selection['candidate']['compiled']['plan']
        need(intent['selection_sha256'] == state_digest(selection) and intent['plan_sha256'] == state_digest(plan), 'intent selected different plan')
        need(strict_same(evidence.ref({'path':str(directory/'selected_plan.json'), 'sha256':intent['selected_plan_file_sha256']}), plan), 'selected plan changed')
        receipt = evidence.ref({'path':str(directory/'commit_receipt.json'), 'sha256':receipt_ref['receipt_sha256']})
        need(receipt['reported_outcome'] == receipt_ref['reported_outcome'] == 'accepted'
             and receipt['plan_sha256'] == state_digest(plan) and receipt['trace_event_index'] == intent['trace_event_index'], 'physical receipt differs')
        idx = receipt['trace_event_index']; need(idx not in plans, 'commit event reused')
        plans[idx] = (pi, boot, plan, receipt, close)
    for owner, starts, ends in ((out, calls, finishes), (preserved_parent, pcalls, pfinishes)):
        actual = [r['call_id'] for r in ledger if r.get('event') == 'reserve' and str(Path(r['run_id']).parent) == str(owner)]
        need(actual == [ends[i]['call_id'] for i in starts], 'all original/new ledger call order differs')
    failed = read(parent/'model_00131/result.json')
    need(failed['status'] == 'failed' and failed['usage_status'] == 'unknown' and failed['output'] is None
         and not (parent/'model_00131/final.txt').exists(), 'original failed request repaired')
    original_trace = [json.loads(x) for x in evidence.raw(parent/'trace.jsonl').splitlines()]
    preserved_trace = [json.loads(x) for x in evidence.raw(preserved_parent/'physical/trace.jsonl').splitlines()]
    original_snapshot, direct_snapshot = read(parent/'checkpoint.json'), read(preserved_parent/'checkpoint.json')
    need(prior['checkpoint']['path'] == 'checkpoint.json'
         and prior['checkpoint']['file_sha256'] == evidence.files[str(parent/'checkpoint.json')]['sha256']
         and prior['checkpoint']['state_sha256'] == original_snapshot['state_sha256'], 'V7 original checkpoint receipt differs')
    need(saved['checkpoint_state_sha256'] == direct_snapshot['state_sha256']
         and saved['checkpoint_sha256'] == evidence.files[str(preserved_parent/'checkpoint.json')]['sha256']
         and saved['trace_sha256'] == evidence.files[str(preserved_parent/'physical/trace.jsonl')]['sha256'], 'direct-parent original result anchors differ')
    markers = _markers(original_snapshot, direct_snapshot, original_trace, preserved_trace, state_digest=state_digest)
    final_snapshot = read(out/'checkpoint.json'); final_state = final_snapshot['state']
    for key in ('schema', 'version', 'implementation_sha256', 'physics_sha256', 'data_hashes', 'random_mechanism'):
        need(strict_same(final_snapshot[key], direct_snapshot[key]), 'final checkpoint physical dependency differs: '+key)
    need(final_snapshot['state_sha256'] == state_digest(final_state) == result['checkpoint_state_sha256']
         and result['checkpoint_sha256'] == evidence.files[str(out/'checkpoint.json')]['sha256']
         and final_state['finished'] is True and strict_same(final_state['t'], 3600.0)
         and strict_same(final_state['horizon'], 3600.0) and strict_same(final_state['observation_start'], 0.0), 'final full checkpoint hash/state differs')
    trace_path = out/'physical/trace.jsonl'
    need(evidence.files[str(trace_path)]['sha256'] == result['trace_sha256'], 'new trace external anchor differs')
    seal = controller.inspect_jsonl(trace_path, expected_sha256=result['trace_sha256'])
    envelope = controller.scan_envelope(seal, require_terminal=True)
    need(envelope.snapshot_count == len(markers) and envelope.first_time == 0 and envelope.horizon == 3600,
         'complete original one-hour window/restore count differs')
    need(len(final_state['trace']) == envelope.receipt.event_count, 'checkpoint omits trace events')
    previous = None; executed = set(); operations = set(); commits = 0; last_stop = 0; dispatches = 0; seen_markers = set()
    with controller.open_verified(seal) as reader:
        for rec in reader:
            event, idx = rec.event, rec.event_index
            need(strict_same(event, final_state['trace'][idx]), 'embedded final trace differs')
            if idx < len(preserved_trace): need(strict_same(event, preserved_trace[idx]), 'complete direct-parent prefix changed')
            if idx == len(preserved_trace): need(strict_same(event, markers[idx]), 'new restore must precede suffix')
            if idx == 0:
                physical = set(event['manifest']['controlled_machine_ids']); need(len(physical) == 913, 'full scope differs')
                horizon = event['manifest']['horizon']; need(horizon == 3600.0, 'original horizon differs')
            if event['kind'] == 'snapshot_loaded':
                need(idx in markers and strict_same(event, markers[idx]), 'restore lineage differs')
                seen_markers.add(idx)
            elif event['kind'] == 'plan_committed':
                need(idx in plans, 'unattributed physical commit'); pi, boot, plan, receipt, close = plans[idx]
                need(pi == commits and strict_same(event['plan'], plan) and state_digest(event) == receipt['trace_event_sha256'], 'physical commit not exact selection')
                base = previous if previous is not None else controller.cold_base(parent.name, event['time'], horizon, sorted(physical))
                state = boot['execution_state']
                need(strict_same(boot['base_plan'], base) and state['time'] == event['time'] and state['observation_end'] == 3600
                     and state['base_plan_version'] == base['version'] and strict_same(state['dispatched_task_ids'],
                     [t['id'] for t in base['tasks'] if (base['version'], t['id']) in executed]), 'base/executed state differs')
                need(set(boot['problem']['scope']) == physical and close['advance_from'] == event['time']
                     and close['advance_target'] == controller.next_boundary(event['time'], 0, 3600, 1800)
                     and event['time'] <= close['simulation_seconds'] <= close['advance_target'], 'absolute target changed')
                if pi: need(last_stop == event['time'], 'resume skipped physical interval')
                last_stop = close['simulation_seconds']; previous = plan; commits += 1
            elif event['kind'] == 'dispatch' and event['machine'] in physical:
                need(previous is not None and event.get('owner') == 'plan' and event.get('plan_version') == previous['version'], 'unplanned dispatch')
                key = (event['plan_version'], event.get('plan_task_id')); need(key not in executed, 'same task dispatched twice'); executed.add(key)
                identities = list(zip(event['lots'], event['steps'], event['visits']))
                need(not operations.intersection(identities), 'original/resumed operation executed twice'); operations.update(identities); dispatches += 1
    need(seen_markers == set(markers) and commits == len(plans) and last_stop == 3600, 'terminal/restore/commit closure differs')
    evidence.fence()
    need(ledger_path.read_bytes() == raw_ledger, 'original actual ledger changed during audit')
    return {'schema':SCHEMA, 'valid':True, 'accepted':False, 'parent_status':'failed', 'preserved_parent_status':'failed',
        'resumed_continuous_window_seconds':3600, 'start_of_recovery':direct_snapshot['state']['t'],
        'new_model_calls_during_audit':0, 'original_and_new_committed_branch_action_count':len(checked_calls),
        'inherited_action_count':len(inherited), 'new_attempts':len(calls), 'first_new_model_index':first_index,
        'plans':commits, 'production_dispatches':dispatches, 'new_call_ids':[finishes[i]['call_id'] for i in calls],
        'snapshot_count':len(markers), 'restore_markers':[markers[i] for i in sorted(markers)],
        'continuation_manifest_sha256':cmref['sha256'], 'sealed_refs_sha256':expected_sealed_refs_sha256,
        'full_ledger_sha256':hashlib.sha256(raw_ledger).hexdigest(), 'original_admission_report':account,
        'physical_audit_still_required':True, 'actual_outer_resource_acceptance_still_required':True,
        'snapshot_restoration_certified':False, 'backend_identity_independently_proven':False,
        'parent_channel_proof_sha256':refs['parent_channel_proof']['sha256'],
        'channel_replay_scope':'original V7 committed plan0 79 readonly transport calls; corrected-permission V8 parent calls use external original-frozen binder proof plus exact raw/history and readonly transport recheck; every new call fully bound in new namespace. Other older uncommitted runs rely on preserved complete admission/closure evidence.',
        'scope':'saved attribution only; frozen injected checker dependencies and external original inventory trust required',
        'whole_snapshots_and_indices_loaded_in_memory':True, 'wall_seconds':time.monotonic()-begun,
        'trace_sha256':result['trace_sha256']}
