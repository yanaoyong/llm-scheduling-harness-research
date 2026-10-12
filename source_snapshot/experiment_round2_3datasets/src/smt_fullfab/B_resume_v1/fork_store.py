"""Explicit create-new fork of a stopped, fully verified pure interaction.

No transport, budget finish, or physical operation. The complete parent database
is retained byte-for-byte. Only one terminal failed, unhandled trailing attempt
is excluded from the *active* projection; it remains in the lineage archive.
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

SCHEMA = 'smt-B-v7-explicit-fork-v1'
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


def inspect_parent(raw, *, runtime, expected_store_id, expected_prefix):
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
        attempts = [state['attempts'][aid] for aid in session['attempt_ids']]
        need(attempts and all(a['action'] is not None for a in attempts[:-1]), 'only one trailing unresolved action permitted')
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
        need(cut >= 2 and rows[cut-1][1] == 'action_recorded', 'prefix must end at original handled action')
        return {'rows': rows, 'blobs': blobs, 'cut': cut, 'state': state, 'sid': sid,
                'evidence': model.export_evidence(), 'next_prompt': model.next_prompt(),
                'failed_attempt_id': failed['attempt_id'], 'failed_call_id': failed['request']['call_id'],
                'failed_model_index': failed['model_index'], 'failed_status': result['status'],
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


def verify_projection(db, parent, *, runtime, branch_id, instance_id, run_path):
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
    for aid, a in state['attempts'].items():
        if aid in parent_ids:
            need(a['action'] is not None, 'failed parent attempt reintroduced as active')
            continue
        i = a['model_index']; spec = gj(a['spec_blob'])
        need(type(i) is int and i > parent['failed_model_index'] and aid == branch_id + ':model:' + str(i), 'new attempt must bind branch and advance global index')
        need(a['instance_id'] == instance_id and spec['run_dir'] == str(Path(run_path) / f'model_{i:05d}'), 'new attempt owner/path differs')
        if a['request'] is not None:
            need(a['request']['call_id'] not in parent_cids, 'original call ID cannot be reused')
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
    raw, ref = read(directory / 'fork_manifest.json', expected_manifest_sha256)
    m = json.loads(raw)
    need(m['schema'] == SCHEMA and m['not_a_parent_success'] is True and m['automatic_retry'] is False, 'fork manifest schema')
    need(m['fork_code_sha256'] == sha(Path(__file__).read_bytes()), 'fork verifier source differs')
    parent_raw, archive = read(directory / 'parent_complete.sqlite3', m['parent_prefix']['database_sha256'])
    original, original_ref = read(m['parent_database_path'], m['parent_prefix']['database_sha256'])
    need(original == parent_raw, 'original full parent and preserved archive differ')
    parent = inspect_parent(parent_raw, runtime=runtime, expected_store_id=m['parent_store_id'], expected_prefix=m['parent_prefix'])
    need(parent['cut'] == m['projected_parent_records'] and parent['failed_attempt_id'] == m['failed_attempt_id']
         and parent['failed_call_id'] == m['failed_call_id'] and parent['failed_model_index'] == m['failed_model_index'], 'failed-tail boundary differs')
    need(runtime.digest(parent['evidence']) == m['parent_interaction_evidence_sha256'], 'parent pure evidence differs')
    return m, parent, [ref, archive, original_ref]


def recover_read_only(directory, *, runtime, expected_manifest_sha256, expected_prefix=None):
    """Complete parent oracle + active projection/oracle. No attach/handle/commit."""
    m, parent, refs = _load_lineage(directory, expected_manifest_sha256, runtime)
    store = runtime.DurableInteractionStore(Path(directory) / 'active')
    with store._lock(False):
        store._ready(); raw, identity = runtime.database_snapshot(store)
        with closing(sqlite3.connect(':memory:')) as db:
            db.deserialize(raw); db.execute('PRAGMA query_only=ON')
            state, gj, gb = verify_projection(db, parent, runtime=runtime, branch_id=m['branch_id'],
                                               instance_id=m['instance_id'], run_path=m['segment_run_path'])
            model = runtime.replay_session(parent['sid'], state, gj, gb)
            if expected_prefix is not None:
                n = expected_prefix['journal_records']; rows = rows_of(db)
                need(type(n) is int and 1 <= n <= len(rows) and rows[n-1][4] == expected_prefix['journal_tail_sha256'], 'original descendant prefix differs')
                if n == len(rows):
                    need(sha(raw) == expected_prefix['database_sha256'], 'exact descendant snapshot differs')
            proof = {**{k:v for k,v in zip(PREFIX, (state['records'], state['tail'], sha(raw)))},
                'valid': True, 'pure_replay_verified': True, 'lineage_verified': True,
                'store_id': m['branch_id'], 'parent_store_id': m['parent_store_id'],
                'fork_manifest_sha256': expected_manifest_sha256,
                'verification_mode': 'full_parent_and_descendant_reference',
                'instances': deepcopy(state['instances']), 'interactions': [{'interaction_id': parent['sid'], 'evidence': model.export_evidence()}],
                'automatic_retry': False, 'physical_commit_verified': False, 'transport_authenticated': False}
        need(runtime.identity(store.path.lstat()) == identity, 'descendant DB changed during full replay')
        for ref in refs: fence(ref)
    return proof


def create_fork(directory, *, runtime, parent_directory, parent_store_id, parent_prefix,
                branch_id, instance_id, segment_run_path, external_authorization_sha256,
                expected_bootstrap_sha256, timing_observer=None):
    """One create-new lifetime only. Authority SHA is a binding, not authenticated here."""
    directory = Path(directory).absolute(); run = Path(segment_run_path)
    need(str(run) == str(run.resolve()) and directory.is_relative_to(run), 'fork must be inside one absolute new segment')
    need(type(branch_id) is str and branch_id.startswith(run.name + ':') and instance_id == branch_id + ':instance', 'explicit branch identities required')
    need(runtime.hash_string(external_authorization_sha256), 'external unique-fork registration hash required')
    source = runtime.DurableInteractionStore(parent_directory)
    with source._lock(False):
        source._ready(); raw, original_identity = runtime.database_snapshot(source)
        parent = inspect_parent(raw, runtime=runtime, expected_store_id=parent_store_id, expected_prefix=parent_prefix)
        need(runtime.digest(parent['bootstrap']) == expected_bootstrap_sha256, 'parent full bootstrap differs')
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
        need(same(imported.next_prompt(), parent['next_prompt']) and same(imported.export_evidence(), parent['evidence']),
             'fork changed exact draft/memory/history or failed-issued next prompt')
        manifest = {'schema': SCHEMA, 'branch_id': branch_id, 'instance_id': instance_id,
            'segment_run_path': str(run), 'parent_store_id': parent_store_id,
            'parent_database_path': str(source.path.resolve()), 'parent_prefix': deepcopy(parent_prefix),
            'projected_parent_records': parent['cut'], 'failed_attempt_id': parent['failed_attempt_id'],
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
        hashed = write_new(directory / 'fork_manifest.json', raw_json(manifest))
        owner = ForkOwner(store, runtime, directory, hashed, manifest, parent)
        owner.verify_full(reason='new_fork_complete_reference')
        return owner
    except BaseException as exc:
        store._poison = repr(exc)
        try: write_new(directory / 'fork_failure.json', raw_json({'error': type(exc).__name__, 'detail': str(exc), 'retry_allowed': False}))
        except BaseException as secondary: exc.add_note('fork failure evidence: ' + repr(secondary))
        raise


class ForkOwner:
    """Finite explicit wrapper; never exposes a recovered owner for writing."""
    def __init__(self, store, runtime, directory, hashed, manifest, parent):
        self._store, self.runtime = store, runtime
        self.directory = store.directory; self.path = store.path
        self.fork_directory = Path(directory); self.fork_manifest_sha256 = hashed
        self.manifest, self.parent = manifest, parent
        self._timing = store._timing; self._poison = None
        self._refs = [read(p)[1] for p in (self.fork_directory / 'fork_manifest.json',
                      self.fork_directory / 'parent_complete.sqlite3', Path(manifest['parent_database_path']))]

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
        need(instance_id == m['instance_id'] and type(i) is int and i > m['failed_model_index'], 'old owner/index cannot reserve')
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
             and int(suffix) > self.manifest['failed_model_index'], 'new exact global attempt index required')

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
            proof = recover_read_only(self.fork_directory, runtime=self.runtime,
                expected_manifest_sha256=self.fork_manifest_sha256,
                expected_prefix={k: original[k] for k in PREFIX})
            self._healthy(write=True); return proof
        except BaseException as exc:
            self._poison = repr(exc); raise
