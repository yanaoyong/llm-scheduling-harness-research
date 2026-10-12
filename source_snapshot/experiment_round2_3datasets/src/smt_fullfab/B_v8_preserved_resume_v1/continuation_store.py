"""Explicit V8 create-new continuation of a stopped fully verified interaction.

No transport, budget finish, or physical operation. The complete parent database
is retained byte-for-byte. Only an explicitly profiled terminal failed, unhandled trailing attempt
may be excluded from the *active* projection; it remains in the lineage archive.
The new store root has a new branch identity. Imported payload text is unchanged.
This is a candidate, not an authentication or cross-branch admission authority.
"""
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat

SCHEMA = 'smt-B-v8-preserved-continuation-v1'
PROFILES = ('processed_boundary', 'terminal_failed_no_final')
PREFIX = ('journal_records', 'journal_tail_sha256', 'database_sha256')


class ForkError(RuntimeError):
    pass


def need(value, message):
    if not value:
        raise ForkError(message)


def raw_json(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                       separators=(',', ':')) + '\n').encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def same(a, b):
    return raw_json(a) == raw_json(b)


def ident(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def read(path, expected=None):
    p = Path(path).absolute()
    with os.fdopen(os.open(p, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)), 'rb') as f:
        before = os.fstat(f.fileno())
        need(stat.S_ISREG(before.st_mode), 'regular immutable input required')
        raw = f.read()
        need(ident(before) == ident(os.fstat(f.fileno())) == ident(p.lstat()), 'input changed while reading')
    need(expected is None or sha(raw) == expected, 'original input hash differs: ' + str(p))
    return raw, {'path': str(p), 'sha256': sha(raw), 'bytes': len(raw), 'identity': list(ident(before))}


def fence(ref):
    need(list(ident(Path(ref['path']).lstat())) == ref['identity'], 'original input identity changed')


def write_new(path, raw):
    with Path(path).open('xb') as f:
        need(f.write(raw) == len(raw), 'short immutable write')
        f.flush(); os.fsync(f.fileno())
    return sha(raw)


def rows_of(db):
    return db.execute('SELECT sequence,kind,payload,previous_sha256,event_sha256 FROM journal ORDER BY sequence').fetchall()


def inspect_parent(raw, *, runtime, expected_store_id, expected_prefix, profile):
    """Whole original oracle on ONE exact parent DB byte snapshot, no mutation."""
    need(sha(raw) == expected_prefix['database_sha256'], 'parent DB raw hash differs')
    with closing(sqlite3.connect(':memory:')) as db:
        db.deserialize(raw); db.execute('PRAGMA query_only=ON')
        need(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'parent SQLite integrity')
        state, gj, gb = runtime.DurableInteractionStore._load(db)
        rows = rows_of(db); blobs = dict(db.execute('SELECT sha256,data FROM blobs'))
        need(state['store_id'] == expected_store_id and same(
            {k: v for k, v in zip(PREFIX, (state['records'], state['tail'], sha(raw)))}, expected_prefix),
            'parent exact prefix/store differs')
        need(len(state['sessions']) == 1 and len(state['instances']) == 1, 'one parent interaction required')
        sid, session = next(iter(state['sessions'].items()))
        need(session['selection_blob'] is None and session['intent'] is None and session['receipt'] is None,
             'selected/committed/unknown-commit interaction cannot fork')
        model = runtime.replay_session(sid, state, gj, gb)
        need(profile in PROFILES, 'explicit supported continuation profile required')
        attempts = [state['attempts'][aid] for aid in session['attempt_ids']]
        evidence = model.export_evidence()
        failed = None; result = None
        if profile == 'processed_boundary':
            need(all(a['action'] is not None for a in attempts),
                 'processed boundary cannot omit pending/successful-unprocessed/failed attempts')
            cut = len(rows)
        else:
            need(attempts and all(a['action'] is not None for a in attempts[:-1]),
                 'only one trailing unresolved action permitted')
            failed = attempts[-1]
            need(failed['request'] is not None and failed['completion'] is not None and failed['action'] is None,
                 'pending/unbound/successfully handled final attempt is not this recovery case')
            result = gj(failed['completion']['result_blob'])
            need(result['status'] in ('failed', 'timeout') and failed['completion']['final_blob'] is None,
                 'terminal failed no-final evidence required; successful unprocessed output cannot be skipped')
            cut = next(i for i, row in enumerate(rows) if row[1] == 'attempt_reserved'
                       and runtime.decode(row[2].encode())['attempt_id'] == failed['attempt_id'])
            need([r[1] for r in rows[cut:]] == ['attempt_reserved', 'transport_requested', 'transport_completed'],
                 'unexpected trailing events; cannot infer active prefix')
            need(cut >= 2 and (rows[cut-1][1] == 'action_recorded'
                 or (cut == 2 and rows[1][1] == 'session_created')),
                 'prefix must end at original handled action or exact empty registration')
        # On a comparison copy only: a clean boundary does not gain an issued
        # prompt; the failed profile already has the original pending prompt.
        next_prompt = deepcopy(model).next_prompt()
        schema = runtime.prompt_schema.schema_bytes(runtime.prompt_schema.schema_for_prompt(
            next_prompt['prompt'], model.context()))
        return {'rows': rows, 'blobs': blobs, 'cut': cut, 'state': state, 'sid': sid,
                'profile': profile, 'evidence': evidence, 'next_prompt': next_prompt,
                'next_schema_bytes': schema,
                'last_parent_model_index': max((a['model_index'] for a in attempts), default=-1),
                'failed_attempt_id': None if failed is None else failed['attempt_id'],
                'failed_call_id': None if failed is None else failed['request']['call_id'],
                'failed_model_index': None if failed is None else failed['model_index'],
                'failed_status': None if result is None else result['status'],
                'bootstrap': gj(session['bootstrap_blob'])}



def projected_rows(parent, *, runtime, branch_id):
    """Only store-created ID and chain links/hashes change; original text survives."""
    need(type(branch_id) is str and branch_id and branch_id != parent['state']['store_id'], 'new branch/store identity required')
    result = []; previous = None
    for seq, kind, text, _, _ in parent['rows'][:parent['cut']]:
        payload = runtime.decode(text.encode())
        if seq == 0:
            payload = {**payload, 'store_id': branch_id}
            text = runtime.encode(payload).decode()
        hashed = runtime.digest({'sequence': seq, 'kind': kind, 'payload': payload, 'previous_sha256': previous})
        result.append((seq, kind, text, previous, hashed)); previous = hashed
    return result


def verify_projection(db, parent, *, runtime, branch_id, instance_id, run_path, first_new_model_index):
    rows = rows_of(db); wanted = projected_rows(parent, runtime=runtime, branch_id=branch_id)
    need(rows[:len(wanted)] == wanted, 'mechanical original action prefix was rewritten')
    blobs = dict(db.execute('SELECT sha256,data FROM blobs'))
    need(all(blobs.get(k) == v for k, v in parent['blobs'].items()), 'original parent blob missing/rewritten, including failure evidence')
    state, gj, gb = runtime.DurableInteractionStore._load(db)
    sid = parent['sid']
    need(set(state['sessions']) == {sid}, 'fork cannot substitute another logical interaction')
    new = rows[len(wanted):]
    need(new and new[0][1] == 'instance_attached'
         and runtime.decode(new[0][2].encode()) == {'interaction_id': sid, 'instance_id': instance_id},
         'explicit new branch owner must be first new event')
    parent_ids = set(parent['state']['attempts']); parent_cids = parent['state']['call_ids']
    new_model_indices = []
    for aid, a in state['attempts'].items():
        if aid in parent_ids:
            need(a['action'] is not None, 'failed parent attempt reintroduced as active')
            continue
        i = a['model_index']; spec = gj(a['spec_blob'])
        need(type(i) is int and i >= first_new_model_index and aid == branch_id + ':model:' + str(i), 'new attempt must bind branch and advance global index')
        new_model_indices.append(i)
        need(a['instance_id'] == instance_id and spec['run_dir'] == str(Path(run_path) / f'model_{i:05d}'), 'new attempt owner/path differs')
        if a['request'] is not None:
            need(a['request']['call_id'] not in parent_cids, 'original call ID cannot be reused')
    need(new_model_indices == list(range(first_new_model_index, first_new_model_index + len(new_model_indices))),
         'new global model sequence must be exact, unique and continuous')
    for _, kind, text, _, _ in new:
        p = runtime.decode(text.encode())
        if kind in ('session_created', 'instance_attached'):
            need(kind == 'instance_attached' and p == {'interaction_id': sid, 'instance_id': instance_id}, 'extra owner/session forbidden')
        if kind in ('external_commit_intent', 'external_commit_receipt'):
            need(p['instance_id'] == instance_id and p['intent_id'].startswith(branch_id + ':commit:'), 'commit identity lacks new branch')
    need(sum(r[1] == 'instance_attached' for r in new) == 1, 'duplicate branch owner')
    return state, gj, gb


def _load_lineage(directory, expected_manifest_sha256, runtime):
    directory = Path(directory).absolute()
    raw, ref = read(directory / 'continuation_manifest.json', expected_manifest_sha256)
    m = json.loads(raw)
    need(m['schema'] == SCHEMA and m['not_a_parent_success'] is True and m['automatic_retry'] is False, 'fork manifest schema')
    need(m['fork_code_sha256'] == sha(Path(__file__).read_bytes()), 'fork verifier source differs')
    parent_raw, archive = read(directory / 'parent_complete.sqlite3', m['parent_prefix']['database_sha256'])
    original, original_ref = read(m['parent_database_path'], m['parent_prefix']['database_sha256'])
    need(original == parent_raw, 'original full parent and preserved archive differ')
    parent = inspect_parent(parent_raw, runtime=runtime, expected_store_id=m['parent_store_id'], expected_prefix=m['parent_prefix'], profile=m['profile'])
    need(parent['cut'] == m['projected_parent_records'] and parent['failed_attempt_id'] == m['failed_attempt_id']
         and parent['failed_call_id'] == m['failed_call_id'] and parent['failed_model_index'] == m['failed_model_index']
         and parent['failed_status'] == m['failed_status'], 'failed-tail boundary differs')
    need(runtime.digest(parent['evidence']) == m['parent_interaction_evidence_sha256']
         and runtime.digest(parent['next_prompt']) == m['next_prompt_sha256']
         and sha(parent['next_schema_bytes']) == m['next_schema_sha256']
         and parent['last_parent_model_index'] == m['last_parent_model_index']
         and runtime.digest(parent['bootstrap']) == m['parent_bootstrap_sha256'],
         'parent pure evidence, bootstrap or original dynamic schema differs')
    need(type(m['first_new_model_index']) is int and m['first_new_model_index'] > parent['last_parent_model_index'],
         'external first model index must exceed all original parent attempts')
    return m, parent, [ref, archive, original_ref]


def recover_read_only(directory, *, runtime, expected_manifest_sha256, expected_prefix=None):
    """Complete parent oracle + active projection/oracle. No attach/handle/commit."""
    header_raw, header_ref = read(Path(directory) / 'continuation_manifest.json', expected_manifest_sha256)
    header = runtime.decode(header_raw)
    if header.get('schema') == FRESH_SCHEMA:
        result = _recover_fresh(directory, runtime=runtime, expected_manifest_sha256=expected_manifest_sha256, expected_prefix=expected_prefix)
        fence(header_ref); return result
    m, parent, refs = _load_lineage(directory, expected_manifest_sha256, runtime)
    refs.append(header_ref)
    store = runtime.DurableInteractionStore(Path(directory) / 'active')
    with store._lock(False):
        store._ready(); raw, identity = runtime.database_snapshot(store)
        with closing(sqlite3.connect(':memory:')) as db:
            db.deserialize(raw); db.execute('PRAGMA query_only=ON')
            state, gj, gb = verify_projection(db, parent, runtime=runtime, branch_id=m['branch_id'],
                                               instance_id=m['instance_id'], run_path=m['segment_run_path'], first_new_model_index=m['first_new_model_index'])
            model = runtime.replay_session(parent['sid'], state, gj, gb)
            if expected_prefix is not None:
                n = expected_prefix['journal_records']; rows = rows_of(db)
                need(type(n) is int and 1 <= n <= len(rows) and rows[n-1][4] == expected_prefix['journal_tail_sha256'], 'original descendant prefix differs')
                if n == len(rows):
                    need(sha(raw) == expected_prefix['database_sha256'], 'exact descendant snapshot differs')
            proof = {**{k:v for k,v in zip(PREFIX, (state['records'], state['tail'], sha(raw)))},
                'valid': True, 'pure_replay_verified': True, 'lineage_verified': True,
                'store_id': m['branch_id'], 'parent_store_id': m['parent_store_id'],
                'continuation_manifest_sha256': expected_manifest_sha256,
                'verification_mode': 'full_parent_and_descendant_reference', 'logical_plan_kind': 'preserved',
                'lineage_call_ids': sorted(set(parent['state']['call_ids']) | state['call_ids']),
                'lineage_store_ids': [m['parent_store_id'], m['branch_id']],
                'last_model_index': max([parent['last_parent_model_index'], *[a['model_index'] for a in state['attempts'].values()]]),
                'instances': deepcopy(state['instances']), 'interactions': [{'interaction_id': parent['sid'], 'evidence': model.export_evidence()}],
                'automatic_retry': False, 'physical_commit_verified': False, 'transport_authenticated': False}
        need(runtime.identity(store.path.lstat()) == identity, 'descendant DB changed during full replay')
        for ref in refs: fence(ref)
    return proof


def create_continuation(directory, *, runtime, parent_directory, parent_store_id, parent_prefix,
                branch_id, instance_id, segment_run_path, external_authorization_sha256,
                expected_bootstrap_sha256, profile, first_new_model_index, timing_observer=None):
    """One create-new lifetime only. Authority SHA is a binding, not authenticated here."""
    directory = Path(directory).absolute(); run = Path(segment_run_path)
    need(str(run) == str(run.resolve()) and directory.is_relative_to(run), 'fork must be inside one absolute new segment')
    need(type(branch_id) is str and branch_id.startswith(run.name + ':') and instance_id == branch_id + ':instance', 'explicit branch identities required')
    need(runtime.hash_string(external_authorization_sha256), 'external unique-fork registration hash required')
    source = runtime.DurableInteractionStore(parent_directory)
    with source._lock(False):
        source._ready(); raw, original_identity = runtime.database_snapshot(source)
        parent = inspect_parent(raw, runtime=runtime, expected_store_id=parent_store_id, expected_prefix=parent_prefix, profile=profile)
        need(runtime.digest(parent['bootstrap']) == expected_bootstrap_sha256, 'parent full bootstrap differs')
        need(type(first_new_model_index) is int and first_new_model_index > parent['last_parent_model_index'],
             'new index must exceed every parent attempt including omitted terminal failure')
        need(runtime.identity(source.path.lstat()) == original_identity, 'parent changed during validation')
    directory.mkdir(parents=False, exist_ok=False)
    write_new(directory / 'parent_complete.sqlite3', raw)
    store = runtime.IncrementalStore.create(directory / 'active', store_id=branch_id, timing_observer=timing_observer)
    try:
        wanted = projected_rows(parent, runtime=runtime, branch_id=branch_id)
        with store._lock(True):
            with closing(sqlite3.connect(store.path)) as db:
                db.execute('PRAGMA synchronous=FULL'); db.execute('BEGIN IMMEDIATE')
                try:
                    need(rows_of(db) == wanted[:1], 'new empty root differs from projection root')
                    for data in parent['blobs'].values(): runtime.DurableInteractionStore._put(db, data)
                    for row in wanted[1:]: db.execute('INSERT INTO journal VALUES(?,?,?,?,?)', row)
                    db.commit()
                except BaseException:
                    db.rollback(); raise
            store._sync()
            # One initialization transplant into this already-create-new owner;
            # never changes _recovered/_created_live of an existing object.
            store._cache = None
            store._oracle_locked('explicit_new_branch_mechanical_import', require_prior=False)
        attached = store.attach(instance_id, parent['sid'])
        need(attached['accepted'], 'explicit fork owner attachment failed')
        state = store._cache['state']; imported = deepcopy(store._cache['models'][parent['sid']])
        if profile == 'processed_boundary':
            need(same(imported.export_evidence(), parent['evidence']),
                 'clean prefix changed exact draft/memory/history or issued prompt state')
            compared = deepcopy(imported)
        else:
            compared = imported
            compared.next_prompt()
            need(same(compared.export_evidence(), parent['evidence']),
                 'failed prefix changed exact draft/memory/history or failed-issued next prompt')
        need(same(compared.next_prompt(), parent['next_prompt'])
             and runtime.prompt_schema.schema_bytes(runtime.prompt_schema.schema_for_prompt(
                 compared.next_prompt()['prompt'], compared.context())) == parent['next_schema_bytes'],
             'projected prompt or V8 dynamic schema differs')
        manifest = {'schema': SCHEMA, 'branch_id': branch_id, 'instance_id': instance_id,
            'segment_run_path': str(run), 'parent_store_id': parent_store_id,
            'parent_database_path': str(source.path.resolve()), 'parent_prefix': deepcopy(parent_prefix),
            'projected_parent_records': parent['cut'], 'profile': profile,
            'first_new_model_index': first_new_model_index, 'last_parent_model_index': parent['last_parent_model_index'],
            'next_prompt_sha256': runtime.digest(parent['next_prompt']),
            'next_schema_sha256': sha(parent['next_schema_bytes']), 'failed_attempt_id': parent['failed_attempt_id'],
            'failed_call_id': parent['failed_call_id'], 'failed_model_index': parent['failed_model_index'],
            'failed_status': parent['failed_status'], 'not_a_parent_success': True, 'automatic_retry': False,
            'parent_interaction_evidence_sha256': runtime.digest(parent['evidence']),
            'parent_bootstrap_sha256': expected_bootstrap_sha256,
            'external_authorization_sha256': external_authorization_sha256,
            'fork_code_sha256': sha(Path(__file__).read_bytes()),
            'projection': 'new store-created ID; rechain only; original accepted payload text/blobs unchanged; full failed parent DB retained',
            'original_prompt_reused_only_by_new_explicit_attempt': True,
            'cross_branch_uniqueness_authenticated': False}
        need(runtime.identity(source.path.lstat()) == original_identity, 'parent changed before fork publication')
        hashed = write_new(directory / 'continuation_manifest.json', raw_json(manifest))
        owner = ContinuationOwner(store, runtime, directory, hashed, manifest, parent)
        owner.verify_full(reason='new_fork_complete_reference')
        return owner
    except BaseException as exc:
        store._poison = repr(exc)
        try: write_new(directory / 'fork_failure.json', raw_json({'error': type(exc).__name__, 'detail': str(exc), 'retry_allowed': False}))
        except BaseException as secondary: exc.add_note('fork failure evidence: ' + repr(secondary))
        raise


class ContinuationOwner:
    """Finite explicit wrapper; never exposes a recovered owner for writing."""
    def __init__(self, store, runtime, directory, hashed, manifest, parent):
        self._store, self.runtime = store, runtime
        self.directory = store.directory; self.path = store.path
        self.continuation_directory = Path(directory); self.continuation_manifest_sha256 = hashed
        self.manifest, self.parent = manifest, parent
        self._timing = store._timing; self._poison = None
        self._refs = [read(p)[1] for p in (self.continuation_directory / 'continuation_manifest.json',
                      self.continuation_directory / 'parent_complete.sqlite3', Path(manifest['parent_database_path']))]

    def _healthy(self, *, write=False):
        need(self._poison is None, 'fork poisoned: ' + str(self._poison))
        try:
            self._store._healthy(write=write)
            for ref in self._refs: fence(ref)
        except BaseException as exc:
            self._poison = repr(exc); raise

    def _invoke(self, name, *args, **kwargs):
        self._healthy(write=True)
        try:
            result = getattr(self._store, name)(*args, **kwargs)
            self._healthy(write=True); return result
        except BaseException as exc:
            self._poison = repr(exc); raise

    def reserve_attempt(self, instance_id, **kwargs):
        i = kwargs['model_index']; m = self.manifest
        need(instance_id == m['instance_id'] and type(i) is int and i >= m['first_new_model_index'], 'old owner/index cannot reserve')
        self._healthy(write=True)
        new_indices = [a['model_index'] for a in self._store._cache['state']['attempts'].values()
                       if a['instance_id'] == instance_id]
        need(i == (max(new_indices) + 1 if new_indices else m['first_new_model_index']),
             'next new global model index required; no duplicate/gap/retry')
        need(kwargs['attempt_id'] == m['branch_id'] + ':model:' + str(i)
             and kwargs['run_dir'] == str(Path(m['segment_run_path']) / f'model_{i:05d}'), 'branch/run/attempt identity differs')
        return self._invoke('reserve_attempt', instance_id, **kwargs)

    def _new_attempt_owner(self, instance_id, attempt_id):
        self._healthy(write=True)
        need(instance_id == self.manifest['instance_id'], 'parent/foreign instance cannot write this fork')
        begin = self.manifest['branch_id'] + ':model:'
        need(type(attempt_id) is str and attempt_id.startswith(begin), 'parent/foreign attempt cannot write this fork')
        suffix = attempt_id[len(begin):]
        need(suffix.isascii() and suffix.isdigit() and str(int(suffix)) == suffix
             and int(suffix) >= self.manifest['first_new_model_index'], 'new exact global attempt index required')

    def preview_schema(self, instance_id):
        need(instance_id == self.manifest['instance_id'], 'parent/foreign instance cannot preview this continuation')
        return self._invoke('preview_schema', instance_id)

    def bind_transport_request(self, instance_id, **kwargs):
        self._new_attempt_owner(instance_id, kwargs['attempt_id'])
        req = self.runtime.decode(kwargs['request_bytes'])
        need(req['call_id'] not in self.parent['state']['call_ids'], 'parent call cannot be reused')
        return self._invoke('bind_transport_request', instance_id, **kwargs)

    def bind_transport_completion(self, instance_id, **kwargs):
        self._new_attempt_owner(instance_id, kwargs['attempt_id'])
        return self._invoke('bind_transport_completion', instance_id, **kwargs)

    def process_completed(self, instance_id, **kwargs):
        self._new_attempt_owner(instance_id, kwargs['attempt_id'])
        return self._invoke('process_completed', instance_id, **kwargs)

    def record_commit_intent(self, instance_id, **kwargs):
        need(instance_id == self.manifest['instance_id'] and kwargs['intent_id'].startswith(self.manifest['branch_id'] + ':commit:'), 'commit lacks branch identity')
        self.verify_full(reason='before_external_intent')
        result = self._invoke('record_commit_intent', instance_id, **kwargs)
        self.verify_full(reason='after_external_intent'); return result

    def record_commit_receipt(self, instance_id, **kwargs):
        need(instance_id == self.manifest['instance_id'] and kwargs['intent_id'].startswith(self.manifest['branch_id'] + ':commit:'), 'receipt lacks branch owner/identity')
        self.verify_full(reason='before_external_receipt')
        result = self._invoke('record_commit_receipt', instance_id, **kwargs)
        self.verify_full(reason='after_external_receipt'); return result

    def inspect_live(self, **kwargs):
        return self._invoke('inspect_live', **kwargs)

    def export_live(self, **kwargs):
        return self._invoke('export_live', **kwargs)

    def verify_full(self, *, reason):
        self._healthy(write=True)
        try:
            original = self._store.verify_full(reason=reason)
            proof = recover_read_only(self.continuation_directory, runtime=self.runtime,
                expected_manifest_sha256=self.continuation_manifest_sha256,
                expected_prefix={k: original[k] for k in PREFIX})
            self._healthy(write=True); return proof
        except BaseException as exc:
            self._poison = repr(exc); raise


FRESH_SCHEMA = 'smt-B-v8-fresh-after-preserved-commit-v1'
TRANSITION_SCHEMA = 'smt-B-v8-fresh-plan-transition-v1'


def _bound_file(ref):
    need(type(ref) is dict and set(ref) == {'path', 'sha256'}
         and str(Path(ref['path']).resolve()) == ref['path'], 'exact absolute transition input ref required')
    return read(ref['path'], ref['sha256'])


def _previous(directory, manifest_sha256, prefix, runtime):
    proof = recover_read_only(directory, runtime=runtime, expected_manifest_sha256=manifest_sha256,
                              expected_prefix=prefix)
    need(same({k: proof[k] for k in PREFIX}, prefix), 'previous plan requires its exact final prefix')
    store = runtime.DurableInteractionStore(Path(directory) / 'active')
    with store._lock(False):
        store._ready(); raw, db_ref = read(store.path, prefix['database_sha256'])
        with closing(sqlite3.connect(':memory:')) as db:
            db.deserialize(raw); db.execute('PRAGMA query_only=ON')
            state, gj, gb = runtime.DurableInteractionStore._load(db)
            need(len(state['sessions']) == 1, 'one previous logical plan required')
            sid, session = next(iter(state['sessions'].items()))
            need(all(state['attempts'][a]['action'] is not None for a in session['attempt_ids'])
                 and session['selection_blob'] is not None and session['intent'] is not None
                 and session['receipt'] is not None and session['receipt']['reported_outcome'] == 'accepted',
                 'new observation cannot follow unresolved call/selection/commit or unaccepted receipt')
            out = {'proof': proof, 'state': state, 'selection': gj(session['selection_blob']),
                   'intent': session['intent'], 'receipt': session['receipt'],
                   'receipt_bytes': gb(session['receipt']['receipt_blob']),
                   'bootstrap': gj(session['bootstrap_blob'])}
        fence(db_ref)
    return out, db_ref


def _fresh_transition(path, expected_sha256, runtime):
    raw, transition_ref = read(path, expected_sha256); t = runtime.decode(raw)
    required = {'schema', 'segment_run_path', 'external_authorization_sha256', 'previous_directory',
        'previous_manifest_sha256', 'previous_prefix', 'branch_id', 'instance_id', 'first_new_model_index',
        'bootstrap', 'checkpoint', 'checkpoint_state_sha256', 'commit_receipt', 'physical_source_manifest',
        'physical_source_sha256'}
    need(type(t) is dict and set(t) == required and t['schema'] == TRANSITION_SCHEMA,
         'exact external fresh transition fields required')
    previous, previous_ref = _previous(t['previous_directory'], t['previous_manifest_sha256'], t['previous_prefix'], runtime)
    oldraw, oldref = read(Path(t['previous_directory']) / 'continuation_manifest.json', t['previous_manifest_sha256'])
    old = runtime.decode(oldraw)
    need(t['segment_run_path'] == old['segment_run_path']
         and t['external_authorization_sha256'] == old['external_authorization_sha256'],
         'fresh logical plan cannot change recovery segment or account package')
    need(type(t['branch_id']) is str and t['branch_id'].startswith(Path(t['segment_run_path']).name + ':')
         and t['branch_id'] not in previous['proof']['lineage_store_ids']
         and t['instance_id'] == t['branch_id'] + ':instance',
         'new explicit branch/instance required')
    need(type(t['first_new_model_index']) is int
         and t['first_new_model_index'] == previous['proof']['last_model_index'] + 1,
         'fresh plan must continue the exact next model index')
    bootstrap_raw, boot_ref = _bound_file(t['bootstrap']); boot = runtime.decode(bootstrap_raw)
    checkpoint_raw, checkpoint_ref = _bound_file(t['checkpoint']); checkpoint = runtime.decode(checkpoint_raw)
    receipt_raw, receipt_ref = _bound_file(t['commit_receipt']); receipt = runtime.decode(receipt_raw)
    source_raw, source_ref = _bound_file(t['physical_source_manifest']); source = runtime.decode(source_raw)
    need(receipt_raw == previous['receipt_bytes'], 'physical receipt bytes differ from original durable receipt')
    selection = previous['selection']; plan = selection['candidate']['compiled']['plan']; s = checkpoint['state']
    need(checkpoint['schema'] == 'smt-fullfab-snapshot-1'
         and runtime.digest(s) == checkpoint['state_sha256'] == t['checkpoint_state_sha256'],
         'original full snapshot state hash differs')
    need(source['source_sha256'] == runtime.digest(source['files']) == t['physical_source_sha256']
         == boot['source_sha256'] == previous['bootstrap']['source_sha256'], 'physical source changed')
    need(all(source['files'].get(k) == v for k,v in checkpoint['implementation_sha256'].items())
         and checkpoint['implementation_sha256']
         and checkpoint['physics_sha256'] == source['files']['src/smt/environment.py'],
         'snapshot physical implementation differs from original source manifest')
    need(receipt['reported_outcome'] == 'accepted' and receipt['intent_id'] == previous['intent']['intent_id']
         and receipt['plan_sha256'] == receipt['actual_plan_sha256'] == runtime.digest(plan)
         and receipt['retry_permitted'] is False, 'receipt is not the exact prior selected-plan commit')
    index = receipt['trace_event_index']
    need(type(index) is int and 0 <= index < len(s['trace']), 'original commit trace index missing')
    event = s['trace'][index]
    need(event['kind'] == 'plan_committed' and same(event['plan'], plan)
         and same(event['seq'], receipt['trace_seq']) and runtime.digest(event) == receipt['trace_event_sha256']
         and not any(e['kind'] == 'plan_committed' for e in s['trace'][index + 1:]),
         'new observation checkpoint lost/replaced the actual latest commit')
    need(s['finished'] is False and same(s['plan'], plan) and same(boot['base_plan'], plan)
         and same(s['horizon'], previous['bootstrap']['execution_state']['observation_end'])
         and same(boot['execution_state']['observation_end'], s['horizon'])
         and same(boot['execution_state']['time'], s['t']) and s['t'] >= event['time']
         and same(boot['problem']['time'], s['t']) and boot['execution_state']['base_plan_version'] == plan['version'],
         'fresh public observation changed physical H/time/current committed plan')
    executed = {tuple(x) for x in s['executed_tasks']}
    need(boot['execution_state']['dispatched_task_ids'] == [task['id'] for task in plan['tasks']
         if (plan['version'], task['id']) in executed], 'fresh observation dispatched identities differ')
    model = runtime.fresh_session(boot)  # Original full public/page/anchor validator, no model action.
    need(not same(model.context()['anchors'], previous['proof']['interactions'][0]['evidence']['anchors']),
         'fresh logical plan cannot reuse the old four anchors')
    refs = [transition_ref, previous_ref, oldref, boot_ref, checkpoint_ref, receipt_ref, source_ref]
    for ref in refs: fence(ref)
    return t, previous, boot, refs


def create_fresh_after_commit(directory, *, runtime, transition_path, expected_transition_sha256,
                              timing_observer=None):
    """Same segment/new logical observation; no restore, advance or registration of budget."""
    t, previous, boot, refs = _fresh_transition(transition_path, expected_transition_sha256, runtime)
    directory = Path(directory).absolute()
    need(directory.is_relative_to(Path(t['segment_run_path'])), 'new fresh store must remain inside the same segment')
    directory.mkdir(parents=False, exist_ok=False)
    store = runtime.IncrementalStore.create(directory / 'active', store_id=t['branch_id'], timing_observer=timing_observer)
    try:
        registered = store.register(t['instance_id'], boot)
        need(registered['accepted'], 'new public bootstrap registration rejected')
        original = store.verify_full(reason='fresh_after_actual_commit_registration')
        m = {'schema': FRESH_SCHEMA, 'branch_id': t['branch_id'], 'instance_id': t['instance_id'],
             'segment_run_path': t['segment_run_path'], 'external_authorization_sha256': t['external_authorization_sha256'],
             'parent_store_id': previous['proof']['store_id'], 'previous_directory': t['previous_directory'],
             'previous_manifest_sha256': t['previous_manifest_sha256'], 'previous_prefix': t['previous_prefix'],
             'first_new_model_index': t['first_new_model_index'], 'transition_path': str(Path(transition_path).absolute()),
             'transition_sha256': expected_transition_sha256, 'bootstrap_sha256': runtime.digest(boot),
             'initial_prefix': {k: original[k] for k in PREFIX}, 'fork_code_sha256': sha(Path(__file__).read_bytes()),
             'fresh_plan_not_cold_physical_run': True, 'automatic_retry': False,
             'account_registration_performed': False, 'physical_commit_verified': False}
        for ref in refs: fence(ref)
        hashed = write_new(directory / 'continuation_manifest.json', raw_json(m))
        owner = FreshPlanOwner(store, runtime, directory, hashed, m, previous, refs)
        owner.verify_full(reason='fresh_after_commit_full_reference')
        return owner
    except BaseException as exc:
        store._poison = repr(exc)
        try: write_new(directory / 'fork_failure.json', raw_json({'error': type(exc).__name__, 'detail': str(exc), 'retry_allowed': False}))
        except BaseException as secondary: exc.add_note('fresh-plan failure evidence: ' + repr(secondary))
        raise


def _recover_fresh(directory, *, runtime, expected_manifest_sha256, expected_prefix=None):
    raw, mref = read(Path(directory) / 'continuation_manifest.json', expected_manifest_sha256); m = runtime.decode(raw)
    need(m['schema'] == FRESH_SCHEMA and m['fork_code_sha256'] == sha(Path(__file__).read_bytes())
         and m['automatic_retry'] is False and m['account_registration_performed'] is False,
         'fresh plan manifest/source differs')
    t, previous, boot, refs = _fresh_transition(m['transition_path'], m['transition_sha256'], runtime)
    for key in ('branch_id', 'instance_id', 'segment_run_path', 'external_authorization_sha256',
                'first_new_model_index', 'previous_directory', 'previous_manifest_sha256', 'previous_prefix'):
        need(same(m[key], t[key]), 'fresh manifest differs from original transition: ' + key)
    need(m['parent_store_id'] == previous['proof']['store_id'] and m['bootstrap_sha256'] == runtime.digest(boot),
         'fresh parent/bootstrap differs')
    store = runtime.DurableInteractionStore(Path(directory) / 'active')
    with store._lock(False):
        store._ready(); db_raw, db_ref = read(store.path)
        with closing(sqlite3.connect(':memory:')) as db:
            db.deserialize(db_raw); db.execute('PRAGMA query_only=ON')
            state, gj, gb = runtime.DurableInteractionStore._load(db); rows = rows_of(db)
            need(state['store_id'] == m['branch_id'] and len(state['sessions']) == len(state['instances']) == 1
                 and m['instance_id'] in state['instances'], 'fresh store contains inherited/foreign instance')
            sid = state['instances'][m['instance_id']]; session = state['sessions'][sid]
            need(same(gj(session['bootstrap_blob']), boot) and m['initial_prefix']['journal_records'] == 2
                 and rows[1][4] == m['initial_prefix']['journal_tail_sha256'], 'original fresh registration changed')
            if len(rows) == 2: need(sha(db_raw) == m['initial_prefix']['database_sha256'], 'exact initial fresh snapshot changed')
            indices = []; old_cids = set(previous['proof']['lineage_call_ids'])
            for aid in session['attempt_ids']:
                a = state['attempts'][aid]; i = a['model_index']; spec = gj(a['spec_blob']); indices.append(i)
                need(type(i) is int and a['instance_id'] == m['instance_id'] and aid == m['branch_id'] + ':model:' + str(i)
                     and spec['run_dir'] == str(Path(m['segment_run_path']) / f'model_{i:05d}'), 'fresh attempt owner/path differs')
                if a['request'] is not None: need(a['request']['call_id'] not in old_cids, 'ancestor call reused in fresh plan')
            need(indices == list(range(m['first_new_model_index'], m['first_new_model_index'] + len(indices))),
                 'fresh indices are not exact contiguous continuation')
            for payload in (session['intent'], session['receipt']):
                if payload is not None: need(payload['instance_id'] == m['instance_id']
                    and payload['intent_id'].startswith(m['branch_id'] + ':commit:'), 'fresh commit identity differs')
            model = runtime.replay_session(sid, state, gj, gb)
            if expected_prefix is not None:
                n = expected_prefix['journal_records']
                need(type(n) is int and 1 <= n <= len(rows) and rows[n-1][4] == expected_prefix['journal_tail_sha256'], 'fresh original prefix differs')
                if n == len(rows): need(sha(db_raw) == expected_prefix['database_sha256'], 'exact fresh snapshot differs')
            proof = {'valid': True, 'pure_replay_verified': True, 'lineage_verified': True,
                'verification_mode': 'full_fresh_after_commit_reference', 'logical_plan_kind': 'fresh_after_commit',
                'store_id': m['branch_id'], 'parent_store_id': m['parent_store_id'],
                'previous_directory': m['previous_directory'], 'previous_manifest_sha256': m['previous_manifest_sha256'],
                'continuation_manifest_sha256': expected_manifest_sha256,
                'journal_records': state['records'], 'journal_tail_sha256': state['tail'], 'database_sha256': sha(db_raw),
                'instances': deepcopy(state['instances']), 'interactions': [{'interaction_id': sid, 'evidence': model.export_evidence()}],
                'lineage_call_ids': sorted(old_cids | state['call_ids']),
                'lineage_store_ids': [*previous['proof']['lineage_store_ids'], m['branch_id']],
                'last_model_index': max(indices, default=previous['proof']['last_model_index']),
                'automatic_retry': False, 'physical_commit_verified': False, 'transport_authenticated': False}
        for ref in [mref, db_ref, *refs]: fence(ref)
    return proof


class FreshPlanOwner(ContinuationOwner):
    """Same segment authority, original V8 fresh store; never adopts a recovered DB."""
    def __init__(self, store, runtime, directory, hashed, manifest, previous, refs):
        self._store, self.runtime = store, runtime
        self.directory = store.directory; self.path = store.path
        self.continuation_directory = Path(directory); self.continuation_manifest_sha256 = hashed
        self.manifest = manifest
        self.parent = {'state': {'call_ids': set(previous['proof']['lineage_call_ids'])}}
        self._timing = store._timing; self._poison = None
        self._refs = [read(self.continuation_directory / 'continuation_manifest.json')[1], *refs]
