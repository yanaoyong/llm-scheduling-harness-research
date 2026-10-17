"""Synthetic byte artifacts and temporary SQLite files; no model or factory calls."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab import B_delta_durable as module
from src.smt_fullfab.B_delta_durable import DurableInteractionStore, recover_read_only, encode, decode, digest, sha
from tests.test_smt_fullfab_delta_session import fixture, SOURCE


CONFIG = {'model': 'gpt-6-astra', 'reasoning_effort': 'medium', 'timeout_seconds': 180.0,
          'codex_binary': '/synthetic/no-call', 'proxy': None, 'ledger_path': '/synthetic/ledger',
          'phase': 'stage2_research', 'grant_id': 'synthetic-grant',
          'authorization_context': {'purpose': 'B', 'arm': 'B', 'scenario': 1701, 'window_seconds': 3600}}
SCHEMA_BYTES = (json.dumps({'type': 'object'}, ensure_ascii=False, indent=2) + '\n').encode()


class DurableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / 'store'
        self.store = DurableInteractionStore.create(self.directory, store_id='store-test')
        base, problem, state, paging, self.delta = fixture()
        self.inputs = dict(base_plan=base, problem=problem, execution_state=state, source_sha256=SOURCE, paging=paging)
        row = self.store.register('i0', self.inputs);self.assertTrue(row['accepted'], row)
        self.context = row['value'];self.counter = 0

    def reserve(self, instance='i0', index=None, attempt=None):
        index = self.counter if index is None else index
        attempt = 'a' + str(index) if attempt is None else attempt
        row = self.store.reserve_attempt(instance, attempt_id=attempt, model_index=index,
                                         run_dir='/synthetic/' + attempt, config=CONFIG, schema_bytes=SCHEMA_BYTES)
        return row

    def artifacts(self, reservation, request, *, call_id=None, memory='model exact memory'):
        value = reservation['value'];aid = value['attempt_id'];cid = call_id or 'call-' + aid
        prompt = value['prompt'];fingerprint = value['request_fingerprint']
        envelope = {'schema': module.interaction.RESPONSE_SCHEMA, **self.context,
                    'prompt_body_sha256': prompt['prompt_body_sha256'], 'memory': memory, 'request': request}
        final = json.dumps(envelope, ensure_ascii=False, indent=2).encode() + b'\n'
        req = {'call_id': cid, 'started_at': '2026-10-10T00:00:00+00:00', 'request_fingerprint': fingerprint, 'config': CONFIG}
        metadata = {'request_fingerprint': fingerprint, 'model': CONFIG['model'], 'reasoning_effort': CONFIG['reasoning_effort'],
                    'timeout_seconds': CONFIG['timeout_seconds'], 'prompt_characters': len(prompt['prompt']),
                    'prompt_character_limit': 120000, 'authorization_context': CONFIG['authorization_context']}
        reserve = {'event': 'reserve', 'call_id': cid, 'phase': CONFIG['phase'], 'run_id': '/synthetic/' + aid,
                   'grant_id': CONFIG['grant_id'], 'metadata': metadata}
        events = encode({'type': 'turn.completed', 'usage': {'input_tokens': 10, 'output_tokens': 20}}) + b'\n'
        result = {'call_id': cid, 'status': 'success', 'failure_reason': None, 'request_fingerprint': fingerprint,
                  'started_at': req['started_at'], 'finished_at': '2026-10-10T00:00:01+00:00', 'config': CONFIG,
                  'returncode': 0, 'timed_out': False, 'launch_error': None, 'decode_error': None,
                  'duration_seconds': 1.0, 'model_elapsed_seconds': 1.0, 'model_calls': 1, 'automatic_retries': 0,
                  'cost_usd': None, 'output': envelope, **module.event_summary(events)}
        finish = {'event': 'finish', 'call_id': cid, 'status': result['status'],
                  'details': {'result_path': '/synthetic/' + aid + '/result.json', 'failure_reason': None,
                              'usage': result['usage'], 'duration_seconds': 1.0, 'cost_usd': None, 'completed_turns': 1}}
        return {'request_bytes': encode(req), 'reserve_bytes': encode(reserve), 'claim_bytes': (fingerprint + '\n').encode(),
                'prompt_bytes': prompt['prompt'].encode(), 'schema_bytes': SCHEMA_BYTES,
                'result_bytes': encode(result), 'finish_bytes': encode(finish), 'events_bytes': events, 'final_bytes': final}

    def bind_request(self, aid, artifacts, instance='i0'):
        return self.store.bind_transport_request(instance, attempt_id=aid,
            **{k: artifacts[k] for k in ('request_bytes', 'reserve_bytes', 'claim_bytes', 'prompt_bytes', 'schema_bytes')})

    def bind_completion(self, aid, artifacts, instance='i0'):
        return self.store.bind_transport_completion(instance, attempt_id=aid,
            **{k: artifacts[k] for k in ('result_bytes', 'finish_bytes', 'events_bytes', 'final_bytes')})

    def send(self, request, instance='i0'):
        index = self.counter;self.counter += 1
        reserved = self.reserve(instance, index=index);self.assertTrue(reserved['accepted'], reserved)
        aid = reserved['value']['attempt_id'];artifacts = self.artifacts(reserved, request)
        self.assertTrue(self.bind_request(aid, artifacts, instance)['accepted'])
        self.assertTrue(self.bind_completion(aid, artifacts, instance)['accepted'])
        mapped = self.store.process_completed(instance, attempt_id=aid)
        self.assertTrue(mapped['accepted'], mapped)
        return mapped['value']['response']['response']

    def checked(self):
        response = self.send({'kind': 'create_draft', 'draft_id': 'd'})
        current = response['state_sha256']
        layer = module.interaction.assembly_layer
        def at(path):
            value = self.delta
            for key in path:value = value[key]
            return deepcopy(value)
        action = {'schema': layer.SCHEMA, 'action': 'chunk', 'draft_id': 'd', 'anchors': self.context['anchors'],
                  'previous_state_sha256': current, 'sequence': 0, 'chunk_id': 'chunk-0',
                  'set_fields': [{'path': list(p), 'value': at(p)} for p in layer.SET_PATHS],
                  'append_arrays': [{'path': list(p), 'items': at(p)} for p in layer.ARRAY_PATHS]}
        chunk = self.send({'kind': 'assembly_action', 'action': action})
        seal = {'schema': layer.SCHEMA, 'action': 'seal', 'draft_id': 'd', 'anchors': self.context['anchors'],
                'previous_state_sha256': chunk['assembly_result']['state_sha256']}
        sealed = self.send({'kind': 'assembly_action', 'action': seal})
        checked = self.send({'kind': 'check_assembly', 'draft_id': 'd',
                             'sealed_state_sha256': sealed['assembly_result']['state_sha256'],
                             'seal_action_sha256': digest(seal), 'delta_sha256': digest(self.delta)})
        self.assertEqual(checked['status'], 'candidate_checked')
        return checked['candidate']

    def selected(self):
        candidate = self.checked()
        return self.send({'kind': 'apply', 'candidate_id': candidate['candidate_id'], 'candidate_sha256': candidate['candidate_sha256']})

    def report(self):
        report = recover_read_only(self.directory, expected_store_id='store-test')
        self.assertTrue(report['valid'], report)
        return report

    def test_complete_explicit_chain_is_durable_pure_replay_verified_not_authenticated(self):
        selection = self.selected();report = self.report()
        self.assertEqual(report['sessions'][0]['phase'], 'selection_recorded')
        self.assertTrue(report['pure_replay_verified'])
        self.assertEqual(report['sessions'][0]['selection_sha256'], digest(selection))
        self.assertFalse(report['transport_authenticated']);self.assertFalse(report['external_commit_ready'])
        self.assertEqual(report['database_sha256'], sha(self.store.path.read_bytes()))
        with sqlite3.connect(self.store.path) as db:
            blobs = dict(db.execute('SELECT sha256,data FROM blobs'))
            self.assertTrue(any(b'"prompt_body_sha256"' in raw and b'\n' in raw for raw in blobs.values()))
            records = [decode(raw) for raw in blobs.values() if raw.startswith(b'{')]
            self.assertFalse(any('history' in r and 'drafts' in r for r in records))

    def test_reserved_request_and_completed_unmapped_stages_never_auto_execute(self):
        reserved = self.reserve();aid = reserved['value']['attempt_id']
        self.assertEqual(self.report()['sessions'][0]['phase'], 'reserved_transport_unknown')
        self.assertFalse(self.reserve(index=1)['accepted'])
        artifacts = self.artifacts(reserved, {'kind': 'create_draft', 'draft_id': 'd'})
        self.assertTrue(self.bind_request(aid, artifacts)['accepted'])
        self.assertEqual(self.report()['sessions'][0]['phase'], 'transport_pending')
        self.assertTrue(self.bind_completion(aid, artifacts)['accepted'])
        before = self.store.path.read_bytes();report = self.report()
        self.assertEqual(report['sessions'][0]['phase'], 'completed_unprocessed')
        self.assertEqual(report['sessions'][0]['action_count'], 0)
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertTrue(self.store.attach('i1', self.context['interaction_id'])['accepted'])
        self.assertEqual(self.report()['sessions'][0]['action_count'], 0)
        self.assertTrue(self.store.process_completed('i1', attempt_id=aid)['accepted'])
        self.assertEqual(self.report()['sessions'][0]['action_count'], 1)
        self.assertFalse(self.store.process_completed('i0', attempt_id=aid)['accepted'])

    def test_duplicate_logical_bootstrap_cannot_reset_history(self):
        self.send({'kind': 'read_candidates'})
        duplicate = self.store.register('fresh', self.inputs)
        self.assertFalse(duplicate['accepted']);self.assertEqual(duplicate['error']['code'], 'session_exists')
        self.assertTrue(self.store.attach('i1', self.context['interaction_id'])['accepted'])
        self.assertFalse(self.reserve('i1', index=0, attempt='new-old-index')['accepted'])
        self.assertEqual(self.send({'kind': 'read_candidates'}, instance='i1')['status'], 'query_result')
        self.assertEqual(self.report()['sessions'][0]['action_count'], 2)

    def test_two_instances_racing_reserve_have_one_winner(self):
        self.store.attach('i1', self.context['interaction_id'])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda pair: self.reserve(pair[0], index=0, attempt=pair[1]), [('i0', 'race-0'), ('i1', 'race-1')]))
        self.assertEqual(sum(r['accepted'] for r in results), 1)
        self.assertEqual(self.report()['sessions'][0]['phase'], 'reserved_transport_unknown')

    def test_actual_prompt_schema_config_and_reserve_are_bound(self):
        reserved = self.reserve();aid = reserved['value']['attempt_id']
        artifacts = self.artifacts(reserved, {'kind': 'read_candidates'})
        for field in ('prompt_bytes', 'schema_bytes', 'claim_bytes'):
            changed = deepcopy(artifacts);changed[field] += b' '
            self.assertFalse(self.bind_request(aid, changed)['accepted'])
        changed = deepcopy(artifacts);reserve = decode(changed['reserve_bytes']);reserve['metadata']['timeout_seconds'] = 99
        changed['reserve_bytes'] = encode(reserve)
        self.assertFalse(self.bind_request(aid, changed)['accepted'])
        self.assertTrue(self.bind_request(aid, artifacts)['accepted'])
        self.assertFalse(self.bind_request(aid, artifacts)['accepted'])

    def test_call_id_is_unique_across_different_sessions_and_instances(self):
        first = self.reserve(attempt='one', index=0)
        artifacts = self.artifacts(first, {'kind': 'read_candidates'}, call_id='one-global-id')
        self.assertTrue(self.bind_request('one', artifacts)['accepted'])
        other = deepcopy(self.inputs);other['base_plan']['reason'] = 'different logical base'
        registered = self.store.register('other', other);self.assertTrue(registered['accepted'])
        second = self.reserve('other', attempt='two', index=0)
        artifacts = self.artifacts(second, {'kind': 'read_candidates'}, call_id='one-global-id')
        rejected = self.bind_request('two', artifacts, 'other')
        self.assertFalse(rejected['accepted']);self.assertEqual(rejected['error']['code'], 'call_id')
        report = self.report()
        self.assertEqual(len(report['sessions']), 2)

    def test_bool_index_and_reused_transport_directory_are_rejected(self):
        self.assertFalse(self.reserve(index=True, attempt='bool-index')['accepted'])
        self.send({'kind': 'read_candidates'})
        rejected = self.store.reserve_attempt('i0', attempt_id='new-attempt', model_index=5,
                                              run_dir='/synthetic/a0', config=CONFIG, schema_bytes=SCHEMA_BYTES)
        self.assertFalse(rejected['accepted']);self.assertEqual(rejected['error']['code'], 'run_dir')

    def test_missing_finish_mismatched_final_and_event_usage_never_map_output(self):
        reserved = self.reserve();aid = reserved['value']['attempt_id']
        artifacts = self.artifacts(reserved, {'kind': 'read_candidates'});self.bind_request(aid, artifacts)
        for field, value in [('finish_bytes', encode({})), ('final_bytes', b'{}'), ('events_bytes', b'')]:
            changed = deepcopy(artifacts);changed[field] = value
            self.assertFalse(self.bind_completion(aid, changed)['accepted'])
        self.assertEqual(self.report()['sessions'][0]['phase'], 'transport_pending')
        self.assertFalse(self.store.process_completed('i0', attempt_id=aid)['accepted'])
        self.assertTrue(self.bind_completion(aid, artifacts)['accepted'])
        self.assertFalse(self.bind_completion(aid, artifacts)['accepted'])

    def test_failed_transport_is_retained_and_blocks_new_calls(self):
        reserved = self.reserve();aid = reserved['value']['attempt_id']
        artifacts = self.artifacts(reserved, {'kind': 'read_candidates'});self.bind_request(aid, artifacts)
        result = decode(artifacts['result_bytes']);result.update(status='timeout', failure_reason='model_call_timeout', timed_out=True)
        finish = decode(artifacts['finish_bytes']);finish.update(status='timeout');finish['details']['failure_reason'] = result['failure_reason']
        artifacts.update(result_bytes=encode(result), finish_bytes=encode(finish))
        self.assertTrue(self.bind_completion(aid, artifacts)['accepted'])
        self.assertFalse(self.store.process_completed('i0', attempt_id=aid)['accepted'])
        self.assertFalse(self.reserve(index=1)['accepted'])
        self.assertEqual(self.report()['sessions'][0]['phase'], 'failed_transport_preserved')

    def test_invalid_interaction_wrapper_is_preserved_as_original_action_rejection(self):
        reserved = self.reserve();aid = reserved['value']['attempt_id']
        artifacts = self.artifacts(reserved, {'kind': 'read_candidates'})
        output = decode(artifacts['final_bytes']);output['anchors']['state_sha256'] = 'f' * 64
        artifacts['final_bytes'] = encode(output)
        result = decode(artifacts['result_bytes']);result['output'] = output;artifacts['result_bytes'] = encode(result)
        self.bind_request(aid, artifacts);self.bind_completion(aid, artifacts)
        processed = self.store.process_completed('i0', attempt_id=aid)
        self.assertTrue(processed['accepted'])
        self.assertEqual(processed['value']['response']['response']['error']['code'], 'stale_context')
        self.assertEqual(self.report()['sessions'][0]['action_count'], 1)

    def test_only_one_commit_intent_and_receipt_across_instances(self):
        selection = self.selected();self.store.attach('i1', self.context['interaction_id'])
        kwargs = {'intent_id': 'intent-1', 'selection_sha256': digest(selection),
                  'plan_sha256': digest(selection['candidate']['compiled']['plan']), 'current_anchors': selection['anchors'],
                  'external_validation_reference': {'status': 'unverified synthetic reference'}}
        result = self.store.record_commit_intent('i0', **kwargs);self.assertTrue(result['accepted'])
        self.assertFalse(result['value']['external_commit_ready'])
        self.assertEqual(self.report()['sessions'][0]['phase'], 'external_commit_outcome_unknown')
        self.assertFalse(self.store.record_commit_intent('i1', **kwargs)['accepted'])
        self.assertFalse(self.reserve('i1', index=100, attempt='after-select')['accepted'])
        receipt = self.store.record_commit_receipt('i1', intent_id='intent-1', reported_outcome='unknown',
                                                  receipt_bytes=b'unknown original receipt', external_reference={})
        self.assertTrue(receipt['accepted'])
        self.assertFalse(self.store.record_commit_receipt('i0', intent_id='intent-1', reported_outcome='accepted',
                                                         receipt_bytes=b'changed', external_reference={})['accepted'])
        self.assertEqual(self.report()['sessions'][0]['phase'], 'external_receipt_reported_unknown')

    def test_commit_wrong_anchor_or_plan_and_missing_selection_rejected(self):
        args = dict(intent_id='x', selection_sha256='a' * 64, plan_sha256='a' * 64,
                    current_anchors=self.context['anchors'], external_validation_reference={})
        self.assertFalse(self.store.record_commit_intent('i0', **args)['accepted'])
        selection = self.selected();args['selection_sha256'] = digest(selection)
        self.assertFalse(self.store.record_commit_intent('i0', **args)['accepted'])

    def test_store_id_external_prefix_and_runtime_are_verified(self):
        prefix = self.report()
        self.send({'kind': 'read_candidates'})
        proof = {'journal_records': prefix['journal_records'], 'journal_tail_sha256': prefix['journal_tail_sha256']}
        self.assertTrue(recover_read_only(self.directory, expected_prefix=proof)['valid'])
        proof['journal_tail_sha256'] = '0' * 64
        self.assertFalse(recover_read_only(self.directory, expected_prefix=proof)['valid'])
        self.assertFalse(recover_read_only(self.directory, expected_store_id='other')['valid'])
        with patch.object(module, 'runtime_manifest', return_value={'different': 'code'}):
            self.assertFalse(recover_read_only(self.directory)['valid'])

    def test_sqlite_sidecar_blocks_without_recovery_or_mutation(self):
        sidecar = Path(str(self.store.path) + '-journal');sidecar.write_bytes(b'preserve interrupted transaction')
        before = self.store.path.read_bytes()
        report = recover_read_only(self.directory)
        self.assertFalse(report['valid']);self.assertEqual(report['errors'][0]['code'], 'storage_unresolved')
        self.assertEqual(before, self.store.path.read_bytes());self.assertTrue(sidecar.exists())

    def test_database_path_replaced_during_replay_cannot_claim_old_rows_new_hash(self):
        replacement = DurableInteractionStore.create(Path(self.tmp.name) / 'other', store_id='other')
        original = module.replay_session
        def swap(*args):
            result = original(*args)
            replacement.path.replace(self.store.path)
            return result
        with patch.object(module, 'replay_session', side_effect=swap):
            report = recover_read_only(self.directory)
        self.assertFalse(report['valid']);self.assertEqual(report['errors'][0]['code'], 'storage_changed')

    def test_transaction_failure_rolls_back_new_blobs_and_event(self):
        before = self.store.path.read_bytes()
        with patch.object(self.store, '_append', side_effect=RuntimeError('crash before commit')):
            with self.assertRaises(RuntimeError):self.reserve()
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertEqual(self.report()['sessions'][0]['phase'], 'idle')

    def test_forged_candidate_with_rehashed_blobs_and_journal_fails_semantic_replay(self):
        self.checked()
        with sqlite3.connect(self.store.path) as db:
            rows = db.execute('SELECT sequence,kind,payload,previous_sha256,event_sha256 FROM journal ORDER BY sequence').fetchall()
            target = next(row for row in rows if row[1] == 'action_recorded' and decode(row[2].encode())['candidate_blobs'])
            payload = decode(target[2].encode());oldref = payload['candidate_blobs'][0]
            candidate = decode(db.execute('SELECT data FROM blobs WHERE sha256=?', (oldref,)).fetchone()[0])
            candidate['candidate']['compiled']['plan']['reason'] = 'forged, same original model output'
            raw = encode(candidate);newref = sha(raw);db.execute('INSERT INTO blobs VALUES(?,?)', (newref, raw))
            payload['candidate_blobs'] = [newref]
            db.execute('DROP TRIGGER no_update_journal')
            previous = None
            for seq, kind, text, _, _ in rows:
                p = payload if seq == target[0] else decode(text.encode())
                event = {'sequence': seq, 'kind': kind, 'payload': p, 'previous_sha256': previous}
                hashed = digest(event)
                db.execute('UPDATE journal SET payload=?,previous_sha256=?,event_sha256=? WHERE sequence=?', (encode(p).decode(), previous, hashed, seq))
                previous = hashed
            db.commit()
        report = recover_read_only(self.directory)
        self.assertFalse(report['valid']);self.assertEqual(report['errors'][0]['code'], 'candidate_replay')


    def rewrite_journal(self, mutate):
        # Deliberately attack only this test's temporary DB. Old review evidence is untouched.
        with sqlite3.connect(self.store.path) as db:
            rows = db.execute('SELECT sequence,kind,payload FROM journal ORDER BY sequence').fetchall()
            db.execute('DROP TRIGGER no_update_journal');previous = None
            for sequence, kind, text in rows:
                payload = decode(text.encode());mutate(db, kind, payload)
                hashed = digest({'sequence': sequence, 'kind': kind, 'payload': payload, 'previous_sha256': previous})
                db.execute('UPDATE journal SET payload=?,previous_sha256=?,event_sha256=? WHERE sequence=?',
                           (encode(payload).decode(), previous, hashed, sequence));previous = hashed

    def assert_recovery_rejected(self, code, prefix=None):
        before = self.store.path.read_bytes()
        report = recover_read_only(self.directory, expected_store_id='store-test', expected_prefix=prefix)
        self.assertFalse(report['valid'], report);self.assertFalse(report['pure_replay_verified'])
        self.assertEqual(report['errors'][0]['code'], code, report)
        self.assertEqual(before, self.store.path.read_bytes())
        return report

    def committed_unknown_receipt(self):
        selection = self.selected()
        self.assertTrue(self.store.record_commit_intent('i0', intent_id='only-intent', selection_sha256=digest(selection),
            plan_sha256=digest(selection['candidate']['compiled']['plan']), current_anchors=selection['anchors'],
            external_validation_reference={'synthetic': True})['accepted'])
        receipt = b'original opaque unknown receipt'
        self.assertTrue(self.store.record_commit_receipt('i0', intent_id='only-intent', reported_outcome='unknown',
            receipt_bytes=receipt, external_reference={'synthetic': True})['accepted'])
        return receipt

    def test_rehashed_pending_journal_call_id_must_equal_original_request_and_reserve(self):
        reserved = self.reserve();parts = self.artifacts(reserved, {'kind': 'read_candidates'})
        prefix = self.report();self.assertTrue(self.bind_request('a0', parts)['accepted'])
        def mutate(db, kind, payload):
            if kind == 'transport_requested':payload['call_id'] = 'unrelated'
        self.rewrite_journal(mutate)
        self.assert_recovery_rejected('transport_binding', {k: prefix[k] for k in ('journal_records', 'journal_tail_sha256')})
        with self.assertRaises(module.StoreError):self.store.attach('new-instance', self.context['interaction_id'])

    def test_rehashed_receipt_reference_must_resolve_original_blob(self):
        self.committed_unknown_receipt()
        def mutate(db, kind, payload):
            if kind == 'external_commit_receipt':payload['receipt_blob'] = 'f' * 64
        self.rewrite_journal(mutate);self.assert_recovery_rejected('blob_reference')

    def test_original_receipt_blob_loss_rejected_with_entire_trusted_journal_unchanged(self):
        receipt = self.committed_unknown_receipt();report = self.report()
        prefix = {k: report[k] for k in ('journal_records', 'journal_tail_sha256')}
        with sqlite3.connect(self.store.path) as db:
            journal_before = db.execute('SELECT * FROM journal ORDER BY sequence').fetchall()
            db.execute('DROP TRIGGER no_delete_blobs');db.execute('DELETE FROM blobs WHERE sha256=?', (sha(receipt),))
            self.assertEqual(journal_before, db.execute('SELECT * FROM journal ORDER BY sequence').fetchall())
        self.assert_recovery_rejected('blob_reference', prefix)

    def test_rehashed_pending_spec_cannot_reuse_completed_transport_directory(self):
        self.send({'kind': 'read_candidates'});prefix = self.report();self.assertTrue(self.reserve(index=1)['accepted'])
        def mutate(db, kind, payload):
            if kind == 'attempt_reserved' and payload['attempt_id'] == 'a1':
                spec = decode(db.execute('SELECT data FROM blobs WHERE sha256=?', (payload['spec_blob'],)).fetchone()[0])
                spec['run_dir'] = '/synthetic/a0';raw = encode(spec);ref = sha(raw)
                db.execute('INSERT OR IGNORE INTO blobs VALUES(?,?)', (ref, raw));payload['spec_blob'] = ref
        self.rewrite_journal(mutate)
        self.assert_recovery_rejected('run_dir', {k: prefix[k] for k in ('journal_records', 'journal_tail_sha256')})

    def test_rehashed_spec_cannot_reuse_another_sessions_pending_directory(self):
        self.assertTrue(self.reserve()['accepted'])
        other = deepcopy(self.inputs);other['base_plan']['reason'] = 'another logical bootstrap'
        self.assertTrue(self.store.register('other', other)['accepted'])
        self.assertTrue(self.reserve('other', index=0, attempt='other-attempt')['accepted'])
        def mutate(db, kind, payload):
            if kind == 'attempt_reserved' and payload['attempt_id'] == 'other-attempt':
                spec = decode(db.execute('SELECT data FROM blobs WHERE sha256=?', (payload['spec_blob'],)).fetchone()[0])
                spec['run_dir'] = '/synthetic/a0';raw = encode(spec);ref = sha(raw)
                db.execute('INSERT OR IGNORE INTO blobs VALUES(?,?)', (ref, raw));payload['spec_blob'] = ref
        self.rewrite_journal(mutate);self.assert_recovery_rejected('run_dir')

    def test_all_event_blob_references_including_rejected_inputs_are_closed(self):
        self.committed_unknown_receipt()
        # A rejected receipt attempt must preserve its original opaque bytes too.
        self.assertFalse(self.store.record_commit_receipt('i0', intent_id='only-intent', reported_outcome='accepted',
            receipt_bytes=b'original rejected input', external_reference={})['accepted'])
        report = self.report();prefix = {k: report[k] for k in ('journal_records', 'journal_tail_sha256')}
        original = self.store.path.read_bytes();references = {}
        with sqlite3.connect(self.store.path) as db:
            for kind, text in db.execute('SELECT kind,payload FROM journal ORDER BY sequence'):
                payload = decode(text.encode())
                for name, value in payload.items():
                    if name.endswith('_blob') and value is not None:references.setdefault(kind + '.' + name, value)
                if kind == 'action_recorded' and payload['candidate_blobs']:references['action_recorded.candidate_blobs'] = payload['candidate_blobs'][0]
                if kind == 'write_rejected':references['write_rejected.original_blob_refs'] = payload['original_blob_refs']['receipt']
                if kind == 'attempt_reserved':
                    spec = decode(db.execute('SELECT data FROM blobs WHERE sha256=?', (payload['spec_blob'],)).fetchone()[0])
                    references['spec.schema_blob'] = spec['schema_blob']
        self.assertGreaterEqual(len(references), 18)
        for label, ref in references.items():
            with self.subTest(reference=label):
                self.store.path.write_bytes(original)
                with sqlite3.connect(self.store.path) as db:
                    db.execute('DROP TRIGGER no_delete_blobs');db.execute('DELETE FROM blobs WHERE sha256=?', (ref,))
                self.assert_recovery_rejected('blob_reference', prefix)
        self.store.path.write_bytes(original);self.assertTrue(self.report()['valid'])

    def test_blob_stored_as_sql_text_fails_even_with_same_visible_content_and_key(self):
        receipt = self.committed_unknown_receipt()
        with sqlite3.connect(self.store.path) as db:
            db.execute('DROP TRIGGER no_update_blobs')
            db.execute('UPDATE blobs SET data=? WHERE sha256=?', (receipt.decode(), sha(receipt)))
        self.assert_recovery_rejected('blob_hash')

    def test_unknown_event_field_cannot_smuggle_ignored_blob_reference(self):
        self.reserve()
        def mutate(db, kind, payload):
            if kind == 'attempt_reserved':payload['unverified_extra_blob'] = 'f' * 64
        self.rewrite_journal(mutate);self.assert_recovery_rejected('journal_schema')


if __name__ == '__main__':unittest.main()
