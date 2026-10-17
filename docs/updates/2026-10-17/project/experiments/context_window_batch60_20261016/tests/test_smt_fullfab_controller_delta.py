"""Synthetic endpoint/attribution fixtures only; no factory/model/solver calls.

Written during the A8 serial run. Execution requires the parent's later explicit
release of the no-tests constraint. Real transport compatibility is not proved
by mocks or schema shape tests.
"""
from base64 import b64encode
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.smt_fullfab import controller_delta as module
from src.smt_fullfab.plan_delta import anchor_hashes

SOURCE = 'a' * 64
PREFIX = {'journal_records': 10, 'journal_tail_sha256': 'b' * 64, 'database_sha256': 'c' * 64}


def full_problem():
    return {'schema': 'smt-fullfab-problem-2', 'time': 0.0, 'horizon_end': 14400.0,
            'scope': list(range(913)), 'machines': [{'machine': i, 'family': 'F'} for i in range(913)],
            'operations': [], 'uncertainty': ['complete untouched observation']}


def tiny_environment():
    problem = full_problem()
    env = SimpleNamespace(t=0.0, horizon=3600.0, physical=set(problem['scope']), plan=None,
                          executed_tasks=set(), trace=[], finished=False)
    env.problem = Mock(return_value=problem)
    return env


class PureInteractionDriver:
    """Original pure protocol replies, never normalized or given fake status."""
    def __init__(self, *, large_task=False):
        from tests.test_smt_fullfab_delta_session import fixture
        self.base, self.problem, self.state, self.paging, self.delta = fixture()
        if large_task:
            self.base['tasks'][1]['original_extra'] = 'x' * 25000
        self.session = module.interaction.Interaction(self.base, self.problem, self.state,
            source_sha256=SOURCE, paging=self.paging)
        self.requests, self.replies = [], []

    def send(self, request):
        prompt = self.session.next_prompt()
        envelope = {'schema': module.interaction.RESPONSE_SCHEMA, **self.session.context(),
            'prompt_body_sha256': prompt['prompt_body_sha256'], 'memory': '', 'request': deepcopy(request)}
        index = len(self.requests)
        handled = self.session.handle(module.raw_json(envelope), call_id='pure-call-' + str(index), model_index=index)
        self.requests.append(deepcopy(request))
        self.replies.append(handled)
        return handled

    def query(self, action, **fields):
        context = self.session.context()
        return {'kind': 'session_query', 'action': {'action': action, 'session_id': context['session_id'],
            'anchors': context['anchors'], **fields}}

    def draft_action(self, draft_id, action, **fields):
        draft = self.session.export_evidence()['drafts'][draft_id]
        return {'kind': 'assembly_action', 'action': {'schema': module.interaction.assembly_layer.SCHEMA,
            'action': action, 'draft_id': draft_id, 'anchors': self.session.context()['anchors'],
            'previous_state_sha256': draft['state_sha256'], **fields}}

    def complete_draft(self, draft_id='d', *, invalid=False):
        delta = deepcopy(self.delta)
        if invalid:
            delta['tasks']['keep'] = {'mode': 'ids', 'ids': []}  # Explicitly incomplete disposition.
        def at(path):
            value = delta
            for key in path:
                value = value[key]
            return value
        self.send({'kind': 'create_draft', 'draft_id': draft_id})
        self.send(self.draft_action(draft_id, 'chunk', sequence=0, chunk_id='original-0',
            set_fields=[{'path': list(p), 'value': deepcopy(at(p))} for p in module.interaction.assembly_layer.SET_PATHS],
            append_arrays=[{'path': list(p), 'items': deepcopy(at(p))} for p in module.interaction.assembly_layer.ARRAY_PATHS]))
        self.send(self.draft_action(draft_id, 'seal'))
        draft = self.session.export_evidence()['drafts'][draft_id]
        return {'kind': 'check_assembly', 'draft_id': draft_id, 'sealed_state_sha256': draft['state_sha256'],
            'seal_action_sha256': draft['sealed']['seal_action_sha256'], 'delta_sha256': draft['sealed']['delta_sha256']}


class RealInteractionReplyTests(unittest.TestCase):
    """Exercise actual query/assembly/compiler responses; no model or physics."""
    def assert_continues(self, handled):
        response = handled['response']
        original = module.raw_json(response)
        self.assertFalse(module.is_selection_response(response))
        self.assertEqual(module.raw_json(response), original)

    def test_catalog_page_and_text_really_have_no_status(self):
        driver = PureInteractionDriver()
        for request in ({'kind': 'catalog_page', 'path': ['paging_metadata'], 'offset': 0, 'count': 2},
                        {'kind': 'catalog_text', 'offset': 0, 'count': 80}):
            with self.subTest(kind=request['kind']):
                handled = driver.send(request)
                self.assertNotIn('status', handled['response'])
                self.assert_continues(handled)
                self.assertEqual(driver.session.next_prompt()['body']['feedback'], handled['feedback'])
        self.assertIsNone(driver.session.export_evidence()['selection'])

    def test_all_four_session_queries_keep_original_return_types(self):
        driver = PureInteractionDriver()
        queries = [('read_page', {'page_index': 0}), ('read_base_tasks', {'task_ids': ['a', 'z']}),
                   ('read_base_holds', {'hold_refs': ['h:2', 'h:0']}), ('read_operations', {'operation_ids': ['op-a', 'op-z']})]
        for action, fields in queries:
            with self.subTest(action=action):
                handled = driver.send(driver.query(action, **fields))
                self.assertEqual(handled['response']['status'], 'query_result')
                self.assert_continues(handled)
        self.assertIsNone(driver.session.export_evidence()['selection'])

    def test_draft_chunk_seal_check_and_every_read_continue_until_explicit_apply(self):
        driver = PureInteractionDriver()
        check_request = driver.complete_draft()
        self.assertEqual([row['response']['status'] for row in driver.replies], ['draft_created', 'chunk_accepted', 'sealed_delta'])
        draft = driver.session.export_evidence()['drafts']['d']
        driver.send({'kind': 'read_draft', 'draft_id': 'd', 'state_sha256': draft['state_sha256'],
                     'path': [], 'format': 'page', 'offset': 0, 'count': 2})
        checked = driver.send(check_request)
        self.assertEqual(checked['response']['status'], 'candidate_checked')
        candidate = checked['response']['candidate']
        ref = {k: candidate[k] for k in ('candidate_id', 'candidate_sha256')}
        driver.send({'kind': 'read_candidates'})
        driver.send({'kind': 'read_candidate', **ref, 'path': ['compiled', 'plan'], 'format': 'value', 'offset': 0, 'count': 1})
        original_feedback = driver.replies[0]['response']
        driver.send({'kind': 'read_archive_feedback', 'history_index': 0,
                     'feedback_sha256': module.json_sha256(original_feedback), 'path': [], 'format': 'page', 'offset': 0, 'count': 2})
        for row in driver.replies:
            self.assert_continues(row)
        self.assertIsNone(driver.session.export_evidence()['selection'])
        selected = driver.send({'kind': 'apply', **ref})['response']
        self.assertTrue(module.is_selection_response(selected))
        self.assertTrue(module.same(selected, driver.session.export_evidence()['selection']))
        self.assertFalse(selected['physical_commit_performed'])
        self.assertEqual({r['kind'] for r in driver.requests},
                         set(module.interaction.REQUEST_FIELDS) - {'catalog_page', 'catalog_text', 'session_query'})

    def test_actual_query_and_assembly_rejections_are_feedback_not_selection(self):
        driver = PureInteractionDriver()
        for request in ({'kind': 'catalog_page', 'path': ['missing'], 'offset': 0, 'count': 1},
                        driver.query('read_base_tasks', task_ids=['missing']),
                        {'kind': 'apply', 'candidate_id': 'missing', 'candidate_sha256': '0' * 64}):
            handled = driver.send(request)
            self.assertEqual(handled['response']['status'], 'rejected')
            self.assert_continues(handled)
        driver.send({'kind': 'create_draft', 'draft_id': 'bad-chunk'})
        rejected = driver.send(driver.draft_action('bad-chunk', 'chunk', sequence=9, chunk_id='wrong-sequence', set_fields=[], append_arrays=[]))
        self.assertEqual(rejected['response']['status'], 'rejected')
        self.assert_continues(rejected)
        self.assertIsNone(driver.session.export_evidence()['selection'])

    def test_actual_compiler_rejection_cannot_implicitly_select(self):
        driver = PureInteractionDriver()
        rejected = driver.send(driver.complete_draft(invalid=True))
        self.assertEqual(rejected['response']['status'], 'rejected')
        self.assertEqual(rejected['response']['error']['code'], 'partition')
        self.assert_continues(rejected)
        self.assertIsNone(driver.session.export_evidence()['selection'])
        self.assertEqual(driver.session.export_evidence()['candidates'], [])

    def test_real_oversized_feedback_diagnostic_does_not_become_selection(self):
        driver = PureInteractionDriver(large_task=True)
        handled = driver.send(driver.query('read_base_tasks', task_ids=['z']))
        self.assertEqual(handled['response']['status'], 'query_result')
        self.assertEqual(handled['feedback']['status'], 'feedback_size')
        self.assert_continues(handled)
        self.assertFalse(module.is_selection_response(handled['feedback']))
        self.assertEqual(driver.session.next_prompt()['body']['feedback'], handled['feedback'])

    def test_non_dictionary_payload_rejected_not_silently_continued(self):
        for value in (None, [], 'selection_for_external_commit', True, 1):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'dictionary'):
                module.is_selection_response(value)


class BootstrapAndSchemaTests(unittest.TestCase):
    def test_period_is_absolute_not_shifted_after_event_replan(self):
        self.assertEqual(module.next_boundary(0.0, 0.0, 3600.0), 1800.0)
        self.assertEqual(module.next_boundary(1485.66, 0.0, 3600.0), 1800.0)
        self.assertEqual(module.next_boundary(1800.0, 0.0, 3600.0), 3600.0)
        self.assertEqual(module.next_boundary(0.5, 0.5, 3600.5), 1800.5)
        with self.assertRaises(ValueError):
            module.next_boundary(3600.0, 0.0, 3600.0)

    def test_cold_start_is_empty_and_uncommitted_full_scope(self):
        env = tiny_environment()
        boot = module.bootstrap(env, run_id='B_test', source_sha256=SOURCE)
        self.assertIsNone(env.plan)
        self.assertEqual(env.trace, [])
        self.assertEqual(boot['base_plan']['tasks'], [])
        self.assertEqual(boot['base_plan']['holds'], [])
        self.assertEqual(boot['base_plan']['version'], 'uncommitted-cold-start:B_test')
        self.assertEqual(boot['execution_state']['dispatched_task_ids'], [])
        self.assertEqual(boot['paging']['page_count'], len(boot['paging']['pages']))
        self.assertEqual(boot['paging']['observation_end'], 3600.0)
        self.assertEqual(module.interaction.DeltaSession(**boot).export_evidence()['inputs']['problem'], full_problem())

    def test_real_base_and_executed_identity_keep_original_order(self):
        env = tiny_environment()
        env.plan = {**module.cold_base('B_test', 0.0, 3600.0, list(range(913))),
                    'version': 'previous-model-plan',
                    'tasks': [{'id': 'z', 'opaque': [None, 1.0]}, {'id': 'a', 'opaque': 1}, {'id': 'x'}]}
        env.executed_tasks = {('previous-model-plan', 'z'), ('previous-model-plan', 'x'), ('other-version', 'a')}
        saved = deepcopy(env.plan)
        boot = module.bootstrap(env, run_id='B_test', source_sha256=SOURCE)
        self.assertEqual(boot['execution_state']['dispatched_task_ids'], ['z', 'x'])
        self.assertTrue(module.same(boot['base_plan'], saved))
        boot['base_plan']['tasks'][0]['opaque'].clear()
        self.assertEqual(env.plan, saved)

    def test_subset_or_duplicate_machine_observation_refused(self):
        for corrupt in ('scope', 'machines', 'duplicate'):
            with self.subTest(corrupt=corrupt):
                env = tiny_environment()
                if corrupt == 'duplicate':
                    env.problem.return_value['machines'][-1]['machine'] = 0
                else:
                    env.problem.return_value[corrupt].pop()
                with self.assertRaisesRegex(ValueError, '913'):
                    module.bootstrap(env, run_id='B_test', source_sha256=SOURCE)

    def test_schema_has_each_original_action_and_no_rule_or_solver(self):
        schema = module.response_schema()
        requests = schema['properties']['request']['anyOf']
        self.assertEqual([x['properties']['kind']['enum'][0] for x in requests], list(module.interaction.REQUEST_FIELDS))
        for item in requests:
            kind = item['properties']['kind']['enum'][0]
            self.assertEqual(set(item['required']), {'kind', *module.interaction.REQUEST_FIELDS[kind]})
            self.assertFalse(item['additionalProperties'])
        self.assertEqual(set(schema['required']), {'schema', 'interaction_id', 'session_id', 'anchors',
                          'catalog_sha256', 'prompt_body_sha256', 'memory', 'request'})
        self.assertNotIn('solver', json.dumps(schema))
        self.assertNotIn('heuristic', json.dumps(schema))


class EvidenceStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_index_create_new_chain_and_exact_hash(self):
        path = self.root / 'index.jsonl'
        index = module.RunIndex(path)
        index.append('run_started', config={'max_calls': None})
        index.append('run_stopped', finished=False)
        rows = module.read_index(path, expected_sha256=module.sha_file(path))
        self.assertEqual([r['seq'] for r in rows], [0, 1])
        self.assertEqual(rows[1]['previous_sha256'], rows[0]['record_sha256'])
        with self.assertRaises(FileExistsError):
            module.RunIndex(path)
        with self.assertRaises(Exception):
            module.read_index(path, expected_sha256='0' * 64)

    def test_index_replacement_poisoned_and_not_adopted(self):
        path = self.root / 'index.jsonl'
        index = module.RunIndex(path)
        index.append('run_started')
        replacement = self.root / 'replacement'
        replacement.write_bytes(path.read_bytes())
        replacement.replace(path)
        with self.assertRaisesRegex(ValueError, 'identity'):
            index.append('call_started')
        self.assertTrue(index.poisoned)
        with self.assertRaisesRegex(ValueError, 'poisoned'):
            index.append('call_started')

    def test_index_append_of_foreign_bytes_refused(self):
        path = self.root / 'index.jsonl'
        index = module.RunIndex(path)
        with path.open('ab') as stream:
            stream.write(b'{}\n')
        with self.assertRaisesRegex(ValueError, 'identity'):
            index.append('run_started')
        self.assertTrue(index.poisoned)

    def test_source_inventory_has_full_files_and_canonical_digest(self):
        for name in ('src/a.py', module.VENDOR + '/physics.py', module.DATA + '/tool.txt', 'requirements.lock'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture\n')
        manifest = module.source_manifest(self.root)
        self.assertEqual(len(manifest['files']), 4)
        self.assertEqual(manifest['source_sha256'], module.json_sha256(manifest['files']))
        self.assertEqual(module.assert_source(manifest['source_sha256'], self.root), manifest)
        (self.root / 'src/a.py').write_text('changed\n')
        with self.assertRaisesRegex(ValueError, 'differs'):
            module.assert_source(manifest['source_sha256'], self.root)

    def test_source_symlink_refused(self):
        for name in ('src', module.VENDOR, module.DATA):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        (self.root / 'requirements.lock').write_text('x')
        (self.root / 'src/alias.py').symlink_to(self.root / 'requirements.lock')
        with self.assertRaisesRegex(ValueError, 'linked'):
            module.source_manifest(self.root)

    def test_bound_json_preserves_types_and_rejects_duplicate_keys(self):
        path = self.root / 'value.json'
        module.write_new(path, {'x': [1, 1.0, None, True]})
        self.assertTrue(module.same(module.bound_json(path, module.sha_file(path)), {'x': [1, 1.0, None, True]}))
        path.write_bytes(b'{"x":1,"x":2}\n')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            module.bound_json(path, module.sha_file(path))

    def test_actual_reserves_include_pending_and_unknown_not_bridge_returns(self):
        rows = [
            {'event': 'reserve', 'call_id': 'pending', 'run_id': str(self.root / 'model_00000')},
            {'event': 'reserve', 'call_id': 'unknown', 'run_id': str(self.root / 'model_00001')},
            {'event': 'finish', 'call_id': 'unknown', 'details': {'usage': {}, 'duration_seconds': 4.0}},
            {'event': 'reserve', 'call_id': 'other', 'run_id': str(self.root.parent / 'other/model_00000')}]
        result = module.account_from_rows(rows, self.root)
        self.assertEqual(result['account']['attempts'], 2)
        self.assertEqual(result['reserve_call_ids'], ['pending', 'unknown'])
        self.assertEqual(result['account']['pending'], ['pending'])
        self.assertEqual(result['account']['unknown_completed'], ['unknown'])
        self.assertEqual(result['account']['reported_input_output_tokens'], 0)
        self.assertEqual(result['account']['model_active_seconds'], 4.0)

    def test_final_account_snapshot_is_bound_to_original_ledger_prefix(self):
        namespace = self.root / 'smt_fullfab'
        namespace.mkdir()
        ledger_path = namespace / 'synthetic.jsonl'
        rows = [{'event': 'reserve', 'call_id': 'one', 'run_id': str(self.root / 'model_00000')},
                {'event': 'finish', 'call_id': 'one', 'details': {'usage': {}, 'duration_seconds': 2.0}}]
        ledger_path.write_bytes(b''.join(module.raw_json(row) for row in rows))
        ledger = module.BudgetLedger(ledger_path)
        with patch.object(module, 'DEFAULT_LEDGER', ledger_path):
            captured = module.capture_account(self.root, ledger)
            checked = module.read_account_evidence(self.root, captured['account_report_sha256'])
            self.assertEqual(checked['account']['attempts'], 1)
            self.assertEqual(checked['account']['unknown_completed'], ['one'])
            self.assertEqual(checked['reserve_call_ids'], ['one'])
            ledger_path.write_bytes(b'{"event":"altered"}\n')
            with self.assertRaisesRegex(ValueError, 'preserves final snapshot'):
                module.read_account_evidence(self.root, captured['account_report_sha256'])

    def test_same_run_registration_or_call_suffix_rejected_other_run_allowed(self):
        for case in ('model', 'model_finish', 'solver', 'constructor', 'registration', 'call_identity', 'other_run'):
            with self.subTest(case=case):
                namespace = self.root / ('smt_fullfab_' + case)
                namespace.mkdir()
                out = namespace / 'run'
                out.mkdir()
                ledger_path = namespace / 'ledger.jsonl'
                rows = [{'event': 'stage_run_registered', 'registration': {'run_id': str(out), 'registration_id': 'R'}},
                        {'event': 'reserve', 'call_id': 'one', 'run_id': str(out / 'model_00000'), 'registration_id': 'R'},
                        {'event': 'finish', 'call_id': 'one', 'details': {'usage': {'input_tokens': 1, 'output_tokens': 2}, 'duration_seconds': 1.0}}]
                ledger_path.write_bytes(b''.join(module.raw_json(row) for row in rows))
                ledger = module.BudgetLedger(ledger_path)
                with patch.object(module, 'DEFAULT_LEDGER', ledger_path):
                    saved = module.capture_account(out, ledger)
                    if case == 'call_identity':
                        suffix = [{'event': 'extra_call_note', 'call_id': 'one', 'value': 'cannot be silently ignored'}]
                    elif case == 'registration':
                        suffix = [{'event': 'extra_registration_note', 'registration_id': 'R', 'run_id': str(namespace / 'other')}]
                    else:
                        kind = {'solver': 'solver_reserve', 'constructor': 'constructor_reserve'}.get(case, 'reserve')
                        run_path = namespace / 'other/model_00000' if case == 'other_run' else out / 'model_00001'
                        suffix = [{'event': kind, 'call_id': 'later', 'run_id': str(run_path),
                                   'registration_id': 'elsewhere' if case == 'other_run' else 'R', 'requested_seconds': 1.0}]
                        if case == 'model_finish':
                            suffix.append({'event': 'finish', 'call_id': 'later', 'details': {'usage': {'input_tokens': 3, 'output_tokens': 4}, 'duration_seconds': 2.0}})
                    with ledger_path.open('ab') as stream:
                        stream.write(b''.join(module.raw_json(row) for row in suffix))
                    if case == 'other_run':
                        actual = module.read_account_evidence(out, saved['account_report_sha256'])
                        self.assertEqual(actual['account']['attempts'], 1)
                        self.assertEqual(actual['run_events_count'], 3)
                    else:
                        with self.assertRaisesRegex(ValueError, 'suffix events'):
                            module.read_account_evidence(out, saved['account_report_sha256'])


class CommitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.env = tiny_environment()
        self.boot = module.bootstrap(self.env, run_id='B_test', source_sha256=SOURCE)
        self.plan = {**module.cold_base('B_test', 0.0, 3600.0, list(range(913))),
                     'version': 'model-v1', 'reason': 'explicit choice', 'opaque': {'preserve': [1, 1.0, None]},
                     'tasks': [{'id': 't', 'machine': 0, 'lot_ids': ['l'], 'steps': [1], 'visits': [1],
                                'operation_ids': ['op'], 'not_before': 2.0}]}
        self.selection = {'status': 'selection_for_external_commit',
                          'anchors': anchor_hashes(self.boot['base_plan'], self.boot['problem'], self.boot['execution_state'], source_sha256=SOURCE),
                          'candidate': {'compiled': {'plan': self.plan}}}
        self.store = Mock()
        self.store.record_commit_intent.return_value = {'accepted': True}
        self.store.record_commit_receipt.return_value = {'accepted': True}
        self.index = Mock()
        self.prefix_patch = patch.object(module, 'proof_prefix', return_value=PREFIX)
        self.prefix_patch.start()
        self.addCleanup(self.prefix_patch.stop)

    def invoke(self):
        return module.commit_selection(self.env, store=self.store, store_id='store', instance_id='instance',
            selection=self.selection, expected_bootstrap=self.boot, run_id='B_test', source_sha256=SOURCE,
            page_chars=45000, index=self.index, plan_index=0, directory=self.path)

    def successful_commit(self, value):
        self.env.plan = deepcopy(value)
        self.env.trace.append({'seq': len(self.env.trace), 'kind': 'plan_committed', 'time': self.env.t, 'plan': deepcopy(value)})
        return module.json_sha256(value)

    def test_exact_compiled_plan_passed_without_cropping_or_normalization(self):
        self.env.commit_plan = Mock(side_effect=self.successful_commit)
        before = deepcopy(self.plan)
        result = self.invoke()
        self.assertIs(self.env.commit_plan.call_args.args[0], self.plan)
        self.assertTrue(module.same(before, self.env.plan))
        self.assertEqual(result['reported_outcome'], 'accepted')
        self.assertEqual(result['trace_event_index'], 0)
        self.assertEqual(self.store.record_commit_receipt.call_args.kwargs['reported_outcome'], 'accepted')
        self.assertEqual([c.args[0] for c in self.index.append.call_args_list], ['commit_intent', 'commit_finished'])

    def test_stale_actual_state_refused_before_intent_or_commit(self):
        self.env.t = 1.0
        self.env.commit_plan = Mock()
        with self.assertRaisesRegex(ValueError, 'anchors changed'):
            self.invoke()
        self.store.record_commit_intent.assert_not_called()
        self.env.commit_plan.assert_not_called()

    def test_durable_intent_refusal_never_commits(self):
        self.store.record_commit_intent.return_value = {'accepted': False}
        self.env.commit_plan = Mock()
        with self.assertRaisesRegex(ValueError, 'intent rejected'):
            self.invoke()
        self.env.commit_plan.assert_not_called()

    def test_validator_error_retained_as_unknown_never_retried(self):
        self.env.commit_plan = Mock(side_effect=ValueError('precise original validator failure'))
        with self.assertRaisesRegex(ValueError, 'precise original validator failure'):
            self.invoke()
        self.env.commit_plan.assert_called_once()
        self.assertEqual(self.store.record_commit_receipt.call_args.kwargs['reported_outcome'], 'unknown')
        self.assertEqual(module.load_json(self.path / 'commit_receipt.json')['error']['message'], 'precise original validator failure')

    def test_trace_or_return_mismatch_is_unknown(self):
        def corrupt(value):
            self.successful_commit(value)
            self.env.trace[-1]['plan']['reason'] = 'tool repaired'
            return module.json_sha256(value)
        self.env.commit_plan = Mock(side_effect=corrupt)
        with self.assertRaisesRegex(ValueError, 'agreement'):
            self.invoke()
        self.assertEqual(self.store.record_commit_receipt.call_args.kwargs['reported_outcome'], 'unknown')
        self.env.commit_plan.assert_called_once()

    def test_failed_receipt_after_actual_commit_stops(self):
        self.env.commit_plan = Mock(side_effect=self.successful_commit)
        self.store.record_commit_receipt.return_value = {'accepted': False}
        with self.assertRaisesRegex(ValueError, 'durable receipt failed'):
            self.invoke()
        self.env.commit_plan.assert_called_once()
        self.assertEqual(len(self.env.trace), 1)


class AttributionTests(unittest.TestCase):
    """Mock only external-call/durable proofs; audit index/trace checks are real."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name).resolve()
        self.run_id = 'B_synthetic'
        files = {'src/fixture.py': '0' * 64}
        self.source = module.json_sha256(files)
        module.write_new(self.out / 'source_manifest.json', {'source_sha256': self.source, 'files': files,
                         'canonical_hash_convention': module.SOURCE_CONVENTION})
        self.cfg = {'run_id': self.run_id, 'source_sha256': self.source, 'seconds': 1800,
                    'seed': 1701, 'budget_id': 'budget', 'max_calls': None, 'max_tokens': None}
        self.cfg['period_seconds'] = 1800
        module.write_new(self.out / 'config.json', self.cfg)
        env = tiny_environment()
        env.horizon = 1800.0  # One-period synthetic audit fixture, not an executable run allowance.
        self.boot = module.bootstrap(env, run_id=self.run_id, source_sha256=self.source)
        self.context = {'interaction_id': 'interaction', 'session_id': 'session', 'catalog_sha256': 'd' * 64,
                        'anchors': anchor_hashes(self.boot['base_plan'], self.boot['problem'], self.boot['execution_state'], source_sha256=self.source)}
        self.plan = {**module.cold_base(self.run_id, 0.0, 1800.0, list(range(913))),
                     'version': 'explicit-v1', 'reason': 'chosen', 'tasks': [{'id': 'one', 'machine': 0,
                     'lot_ids': ['lot'], 'steps': [1], 'visits': [1], 'operation_ids': ['op'], 'not_before': 0.0}]}
        self.selection = {'status': 'selection_for_external_commit', **self.context,
                          'candidate': {'compiled': {'plan': self.plan}}}
        self.raw = b'{"fixture":"original model bytes"}\n'
        self.history = [{'call_id': 'call-0', 'model_index': 0, 'raw_output_base64': b64encode(self.raw).decode(),
                         'raw_output_sha256': hashlib.sha256(self.raw).hexdigest()}]
        self.evidence = {**self.context, 'bootstrap': self.boot, 'history': self.history, 'selection': self.selection}
        self.report = {'sessions': [{'phase': 'external_receipt_reported_accepted'}]}
        self.events = [
            {'seq': 0, 'kind': 'initial', 'time': 0.0, 'manifest': {'horizon': 1800.0, 'controlled_machine_ids': list(range(913))}},
            {'seq': 1, 'kind': 'plan_committed', 'time': 0.0, 'plan': deepcopy(self.plan)},
            {'seq': 2, 'kind': 'dispatch', 'time': 0.0, 'machine': 0, 'owner': 'plan', 'plan_version': 'explicit-v1', 'plan_task_id': 'one'},
            {'seq': 3, 'kind': 'terminal', 'time': 1800.0}]
        self.pdir = self.out / 'plan_00000'
        self.pdir.mkdir()
        (self.pdir / 'durable').mkdir()
        boot_sha = module.write_new(self.pdir / 'bootstrap.json', self.boot)
        selected_sha = module.write_new(self.pdir / 'selected_plan.json', self.plan)
        (self.out / 'model_00000').mkdir()
        (self.out / 'model_00000/final.txt').write_bytes(self.raw)
        (self.out / 'call_00000').mkdir()
        self.intent = {'expected_store_id': self.run_id + ':store:0', 'instance_id': self.run_id + ':instance:0',
            'store_directory': str(self.pdir / 'durable'), 'model_index': 0, 'attempt_id': self.run_id + ':model:0',
            'transport_run_dir': str(self.out / 'model_00000'), 'expected_context': self.context,
            'schema_json': module.response_schema(), 'config': {'authorization_context': {'purpose': 'B', 'arm': 'B', 'scenario': 1701, 'window_seconds': 1800}, 'grant_id': 'budget'}}
        intent_sha = module.write_new(self.out / 'call_00000/intent.json', self.intent)
        receipt = {'reported_outcome': 'accepted', 'plan_sha256': module.json_sha256(self.plan),
                   'trace_event_index': 1, 'trace_event_sha256': module.json_sha256(self.events[1]), 'trace_seq': 1}
        receipt_sha = module.write_new(self.pdir / 'commit_receipt.json', receipt)
        self.rows = [
            ('run_started', {'config': self.cfg}),
            ('plan_opened', {'plan_index': 0, 'directory': 'plan_00000', 'store': 'plan_00000/durable',
                'store_id': self.run_id + ':store:0', 'instance_id': self.run_id + ':instance:0',
                'bootstrap_file_sha256': boot_sha, 'base_was_committed': False, 'context': self.context}),
            ('call_started', {'plan_index': 0, 'model_index': 0, 'transport': 'model_00000', 'evidence': 'call_00000', 'attempt_id': self.run_id + ':model:0'}),
            ('call_finished', {'plan_index': 0, 'model_index': 0, 'intent_sha256': intent_sha, 'outcome_sha256': 'f' * 64, 'call_id': 'call-0'}),
            ('commit_intent', {'plan_index': 0, 'selection_sha256': module.json_sha256(self.selection), 'plan_sha256': module.json_sha256(self.plan), 'selected_plan_file_sha256': selected_sha, 'trace_event_index': 1}),
            ('commit_finished', {'plan_index': 0, 'receipt_sha256': receipt_sha, 'reported_outcome': 'accepted'}),
            ('plan_closed', {'plan_index': 0, 'durable_prefix': PREFIX, 'advance_from': 0.0, 'advance_target': 1800.0, 'simulation_seconds': 1800.0}),
            ('run_stopped', {'finished': True, 'simulation_seconds': 1800.0, 'account_report_sha256': '0' * 64})]
        self.export_patch = patch.object(module, 'export_one', return_value=(self.report, self.evidence))
        self.bridge_patch = patch.object(module.bridge, 'recover_read_only', return_value={'valid': True, 'success_action_eligible': True,
            'phase': 'action_already_processed_no_replay', 'original_call_id': 'call-0'})
        self.export_patch.start()
        self.bridge_mock = self.bridge_patch.start()
        self.resource_patch = patch.object(module, 'read_account_evidence', return_value={
            'account': {'attempts': 1, 'pending': [], 'unknown_completed': []},
            'reserve_call_ids': ['call-0'], 'solver_call_ids': [], 'constructor_call_ids': []})
        self.resource_mock = self.resource_patch.start()
        self.addCleanup(self.export_patch.stop)
        self.addCleanup(self.bridge_patch.stop)
        self.addCleanup(self.resource_patch.stop)

    def audit(self):
        index = module.RunIndex(self.out / 'delta_index.jsonl')
        for event, payload in self.rows:
            index.append(event, **payload)
        (self.out / 'trace.jsonl').write_bytes(b''.join(module.raw_json(e) for e in self.events))
        return module.audit_delta_run(self.out, expected_index_sha256=module.sha_file(self.out / 'delta_index.jsonl'),
            expected_source_sha256=self.source, expected_trace_sha256=module.sha_file(self.out / 'trace.jsonl'))

    def test_exact_original_call_selected_plan_and_complete_trace(self):
        result = self.audit()
        self.assertTrue(result['valid'], result)
        self.assertEqual(result['production_dispatches'], 1)
        self.assertFalse(result['backend_identity_independently_proven'])
        self.assertFalse(result['physical_validation_performed'])
        self.assertTrue(result['requires_separate_stream_audit_bundle'])

    def test_unattributed_extra_physical_commit_rejected(self):
        self.events.insert(2, {'seq': 2, 'kind': 'plan_committed', 'time': 0.0, 'plan': self.plan})
        for i, event in enumerate(self.events):
            event['seq'] = i
        self.assertFalse(self.audit()['valid'])

    def test_model_selected_plan_cannot_be_cropped_at_commit(self):
        self.events[1]['plan']['tasks'] = []
        self.assertFalse(self.audit()['valid'])

    def test_cross_store_or_call_index_reset_rejected(self):
        self.rows[2][1]['model_index'] = 1
        self.assertFalse(self.audit()['valid'])

    def test_omitted_original_call_rejected(self):
        del self.rows[2:4]
        self.assertFalse(self.audit()['valid'])

    def test_raw_model_bytes_not_trusted_from_status_only(self):
        (self.out / 'model_00000/final.txt').write_bytes(b'{"forged":true}\n')
        self.assertFalse(self.audit()['valid'])

    def test_bridge_read_only_binding_failure_rejected(self):
        self.bridge_mock.return_value = {'valid': False}
        self.assertFalse(self.audit()['valid'])

    def test_nonterminal_trace_cannot_return_attribution_success(self):
        self.events.pop()
        self.assertFalse(self.audit()['valid'])

    def test_unknown_commit_not_reclassified_from_trace(self):
        self.rows[5][1]['reported_outcome'] = 'unknown'
        self.assertFalse(self.audit()['valid'])

    def test_second_dispatch_of_same_plan_task_rejected(self):
        self.events.insert(3, deepcopy(self.events[2]))
        for i, event in enumerate(self.events):
            event['seq'] = i
        self.assertFalse(self.audit()['valid'])

    def test_store_selection_phase_is_not_itself_original_call_proof(self):
        self.history[0]['call_id'] = 'made-up-call'
        self.assertFalse(self.audit()['valid'])

    def test_shifted_period_record_rejected(self):
        self.rows[6][1]['advance_target'] = 1801.0
        self.assertFalse(self.audit()['valid'])

    def test_saved_plan_replacement_is_not_adopted(self):
        (self.pdir / 'selected_plan.json').write_bytes(b'{"replacement":true}\n')
        self.assertFalse(self.audit()['valid'])

    def test_real_reserve_count_or_pending_mismatch_rejected(self):
        self.resource_mock.return_value['account']['pending'] = ['call-0']
        self.assertFalse(self.audit()['valid'])


class AdmissionTests(unittest.TestCase):
    def test_existing_claim_never_resumes_or_reissues(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'runs/smt_fullfab_stage2/B_existing').mkdir(parents=True)
            ledger = Mock()
            ledger.research_limit_waiver.return_value = {'amendment_id': 'waiver'}
            with patch.object(module, 'ROOT', root), patch.object(module, 'assert_source', return_value={}), \
                 patch.object(module, 'load_json', return_value={'budget_id': 'budget'}), \
                 patch.object(module, 'BudgetLedger', return_value=ledger), \
                 patch.object(module, 'FullFabEnvironment') as environment, patch.object(module.bridge, 'execute_once') as transport:
                with self.assertRaises(FileExistsError):
                    module.run('B_existing', expected_source_sha256=SOURCE)
                environment.assert_not_called()
                transport.assert_not_called()
                ledger.register_stage_run.assert_not_called()

    def test_no_waiver_no_registration_or_factory(self):
        ledger = Mock()
        ledger.research_limit_waiver.return_value = None
        with patch.object(module, 'assert_source', return_value={}), patch.object(module, 'load_json', return_value={}), \
             patch.object(module, 'BudgetLedger', return_value=ledger), patch.object(module, 'FullFabEnvironment') as environment:
            with self.assertRaisesRegex(ValueError, 'waiver'):
                module.run('B_never', expected_source_sha256=SOURCE)
            ledger.register_stage_run.assert_not_called()
            environment.assert_not_called()

    def test_endpoint_has_no_automatic_8h_or_old_run_resume(self):
        with patch.object(module, 'FullFabEnvironment') as environment:
            with self.assertRaisesRegex(ValueError, '1h only'):
                module.run('B_never', expected_source_sha256=SOURCE, seconds=28800)
            environment.assert_not_called()


class MockEndpointTests(unittest.TestCase):
    """Two rolling plans through the real endpoint loop with explicit fake I/O.

    This deliberately does not certify real model transport, SQL replay, factory
    physics or the separate real attribution auditor (covered by other tests).
    """
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan_commits, self.model_indices, self.advance_targets = [], [], []
        self.fail_transport = False
        self.preflight_failure = False
        self.interrupt_after_reserve = False
        self.real_call_ids = []
        owner = self

        class FakeEnvironment:
            def __init__(self, *, seed, window_seconds, trace_path):
                self.t, self.horizon, self.observation_start = 0.0, float(window_seconds), 0.0
                self.physical, self.plan, self.executed_tasks = set(range(913)), None, set()
                self.finished, self.trace, self.trace_path, self.data_dir = False, [], trace_path, owner.root
                self.emit('initial', manifest={'horizon': self.horizon, 'controlled_machine_ids': list(range(913))})

            def emit(self, kind, **values):
                row = {'seq': len(self.trace), 'kind': kind, 'time': self.t, **values}
                self.trace.append(row)
                with self.trace_path.open('ab') as stream:
                    stream.write(module.raw_json(row))

            def problem(self, **kwargs):
                value = full_problem()
                value.update(time=self.t, horizon_end=self.t + 14400.0)
                return value

            def commit_plan(self, plan):
                owner.plan_commits.append(deepcopy(plan))
                self.plan = deepcopy(plan)
                self.emit('plan_committed', plan=deepcopy(plan))
                return module.json_sha256(plan)

            def advance_plan(self, target):
                owner.advance_targets.append(target)
                self.emit('time_advance', to=target)
                self.t = target
                self.finished = target == self.horizon
                if self.finished:
                    self.emit('terminal')
                return {'reason': 'terminal' if self.finished else 'periodic_replan', 'time': self.t}

        class FakeStore:
            def __init__(self, directory):
                self.directory, self.selection, self.calls = directory, None, 0

            def register(self, instance_id, boot):
                self.boot = deepcopy(boot)
                self.context = {'interaction_id': instance_id + ':interaction', 'session_id': instance_id + ':session',
                    'catalog_sha256': 'd' * 64, 'anchors': anchor_hashes(boot['base_plan'], boot['problem'], boot['execution_state'], source_sha256=boot['source_sha256'])}
                return {'accepted': True, 'value': self.context}

            def record_commit_intent(self, *args, **kwargs):
                return {'accepted': True}

            def record_commit_receipt(self, *args, **kwargs):
                return {'accepted': True}

        self.stores = {}
        def create_store(directory, *, store_id):
            directory.mkdir()
            store = FakeStore(directory)
            self.stores[directory] = store
            return store

        def invoke(store, **kwargs):
            self.model_indices.append(kwargs['model_index'])
            if not self.preflight_failure:
                self.ledger.summary.return_value['attempts'] += 1
                self.real_call_ids.append('call-' + str(kwargs['model_index']))
            if self.interrupt_after_reserve:
                self.ledger.summary.return_value['pending'] = list(self.real_call_ids)
                raise KeyboardInterrupt('fixture interrupt after actual reserve')
            self.assertEqual(kwargs['config']['timeout_seconds'], 180.0)
            self.assertTrue(kwargs['process_success'])
            self.assertEqual(kwargs['transport_call'], self.transport)
            status = ['query_result', 'draft_created', 'sealed_delta', 'candidate_checked', 'selection_for_external_commit'][store.calls]
            store.calls += 1
            response = {'status': status}
            if status == 'selection_for_external_commit':
                now = store.boot['execution_state']['time']
                plan = {'version': 'model-plan-' + str(len(self.plan_commits)), 'created_at': now,
                        'valid_until': 3600.0, 'freeze_until': now, 'reason': 'model explicit mock',
                        'scope': list(range(913)), 'tasks': [], 'holds': [], 'preserve_extra': [1, 1.0, None]}
                response = {'status': status, **store.context, 'candidate': {'compiled': {'plan': plan}}}
                store.selection = deepcopy(response)
            return {'phase': 'diagnosis_required' if self.preflight_failure else 'terminal_failed_preserved' if self.fail_transport else 'action_processed',
                    'errors': [], 'intent_sha256': '1' * 64, 'outcome_sha256': '2' * 64,
                    'call_id': 'call-' + str(kwargs['model_index']), 'durable_prefix': PREFIX,
                    'interaction_response': {'response': response}}

        def exported(directory, **kwargs):
            return {}, {'selection': deepcopy(self.stores[directory].selection)}

        def snapshot(env, path):
            module.write_new(path, {'fixture_snapshot': True, 'time': env.t})
            return 'e' * 64

        ledger = Mock()
        ledger.research_limit_waiver.return_value = {'amendment_id': 'waiver'}
        ledger.register_stage_run.return_value = {'phase': 'stage2_research', 'registration_id': 'reg'}
        ledger.summary.return_value = {'model_active_seconds': 10.0, 'attempts': 0, 'pending': [], 'unknown_completed': []}
        (self.root / 'ledger.jsonl').write_text('{}\n')
        self.transport = Mock(side_effect=AssertionError('no actual model transport allowed in this test'))
        self.audit = Mock(return_value={'valid': True})
        def capture(out, original_ledger):
            return {'account': deepcopy(original_ledger.summary.return_value),
                    'reserve_call_ids': list(self.real_call_ids),
                    'solver_call_ids': [], 'constructor_call_ids': [], 'account_report_sha256': '0' * 64}
        patches = [patch.object(module, 'ROOT', self.root),
            patch.object(module, 'DEFAULT_LEDGER', self.root / 'ledger.jsonl'),
            patch.object(module, 'assert_source', return_value={'files': {}, 'source_sha256': SOURCE}),
            patch.object(module, 'load_json', return_value={'budget_id': 'budget'}),
            patch.object(module, 'BudgetLedger', return_value=ledger),
            patch.object(module, 'FullFabEnvironment', FakeEnvironment),
            patch.object(module, 'source_snapshot', return_value={'fixture_only': True}),
            patch.object(module, '_disabled_skills', return_value=[]),
            patch.object(module.durable.DurableInteractionStore, 'create', side_effect=create_store),
            patch.object(module, 'proof_prefix', return_value=PREFIX),
            patch.object(module, 'export_one', side_effect=exported),
            patch.object(module.bridge, 'execute_once', side_effect=invoke),
            patch.object(module, 'call_model', self.transport),
            patch.object(module, 'audit_delta_run', self.audit),
            patch.object(module, 'capture_account', side_effect=capture),
            patch.object(module, 'stream_audit', return_value=({'valid': True, 'complete_physical_window_certified': True, 'metrics': {}}, {'path': 'audit_bundle', 'manifest_sha256': '9' * 64})),
            patch.object(module, 'write_snapshot', side_effect=snapshot)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.ledger = ledger

    def test_two_plans_keep_global_model_indices_and_resource_account(self):
        result = module.run('B_mock', expected_source_sha256=SOURCE)
        self.assertEqual(result['status'], 'completed', result)
        self.assertFalse(result['accepted'])
        self.assertEqual(self.model_indices, list(range(10)))
        self.assertEqual(self.advance_targets, [1800.0, 3600.0])
        self.assertEqual(len(self.plan_commits), 2)
        self.assertEqual([p['preserve_extra'] for p in self.plan_commits], [[1, 1.0, None], [1, 1.0, None]])
        self.assertEqual(result['config']['max_calls'], None)
        self.assertEqual(result['config']['max_tokens'], None)
        self.assertEqual(result['solver_calls'], 0)
        self.assertEqual(result['constructor_calls'], 0)
        self.ledger.register_stage_run.assert_called_once()
        self.transport.assert_not_called()
        run = self.root / 'runs/smt_fullfab_stage2/B_mock'
        rows = module.read_index(run / 'delta_index.jsonl', expected_sha256=module.sha_file(run / 'delta_index.jsonl'))
        self.assertEqual([r['payload']['base_was_committed'] for r in rows if r['event'] == 'plan_opened'], [False, True])

    def test_real_statusless_catalog_reply_reaches_the_next_original_call(self):
        # Only transport/storage/physics are fake. The first reply is generated
        # by the real pure Interaction and is passed through without adding status.
        driver = PureInteractionDriver()
        handled = driver.send({'kind': 'catalog_page', 'path': ['paging_metadata'], 'offset': 0, 'count': 2})
        self.assertNotIn('status', handled['response'])
        original_invoke = module.bridge.execute_once.side_effect
        def invoke(store, **kwargs):
            if kwargs['model_index'] > 0:
                self.fail_transport = True  # Explicit independent second-call failure, never a retry.
            result = original_invoke(store, **kwargs)
            if kwargs['model_index'] == 0:
                result['interaction_response'] = handled
            return result
        with patch.object(module.bridge, 'execute_once', side_effect=invoke), \
             patch.object(module, 'export_one', side_effect=AssertionError('catalog must not request selection export')):
            result = module.run('B_real_query_reply', expected_source_sha256=SOURCE)
        self.assertEqual(self.model_indices, [0, 1])
        self.assertEqual(result['model_calls'], 2)
        self.assertIn('original model call/processing failed', result['failure'])
        self.assertNotIn('KeyError', result['failure'])
        self.assertEqual(self.plan_commits, [])
        self.transport.assert_not_called()

    def test_real_selection_marker_still_requires_verified_durable_selection(self):
        driver = PureInteractionDriver()
        checked = driver.send(driver.complete_draft())['response']['candidate']
        handled = driver.send({'kind': 'apply', 'candidate_id': checked['candidate_id'],
                               'candidate_sha256': checked['candidate_sha256']})
        self.assertTrue(module.is_selection_response(handled['response']))
        original_invoke = module.bridge.execute_once.side_effect
        def invoke(store, **kwargs):
            result = original_invoke(store, **kwargs)
            result['interaction_response'] = handled
            return result
        # Fake durable export still has no selection. A real marker alone must
        # not reach even the mocked common commit, let alone physical execution.
        with patch.object(module.bridge, 'execute_once', side_effect=invoke):
            result = module.run('B_unverified_real_selection', expected_source_sha256=SOURCE)
        self.assertEqual(self.model_indices, [0])
        self.assertIn('returned apply differs from verified durable selection', result['failure'])
        self.assertEqual(self.plan_commits, [])
        self.assertEqual(self.advance_targets, [])
        self.transport.assert_not_called()

    def test_failed_original_call_stops_without_second_call_or_commit(self):
        self.fail_transport = True
        result = module.run('B_failure', expected_source_sha256=SOURCE)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.model_indices, [0])
        self.assertEqual(self.plan_commits, [])
        self.assertEqual(self.advance_targets, [])
        self.audit.assert_not_called()
        self.transport.assert_not_called()
        self.assertIn('no retry', result['failure'])
        self.assertIsNotNone(result['checkpoint'])

    def test_bridge_preflight_is_not_counted_as_real_model_attempt(self):
        self.preflight_failure = True
        result = module.run('B_preflight', expected_source_sha256=SOURCE)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['local_bridge_attempts'], 1)
        self.assertEqual(result['returned_bridge_attempts'], 1)
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(result['reserve_call_ids'], [])
        self.assertEqual(self.model_indices, [0])

    def test_interrupt_after_actual_reserve_is_counted_and_pending(self):
        self.interrupt_after_reserve = True
        with self.assertRaises(KeyboardInterrupt):
            module.run('B_interrupt', expected_source_sha256=SOURCE)
        result = json.loads((self.root / 'runs/smt_fullfab_stage2/B_interrupt/result.json').read_bytes())
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['model_calls'], 1)
        self.assertEqual(result['local_bridge_attempts'], 1)
        self.assertEqual(result['returned_bridge_attempts'], 0)
        self.assertEqual(result['pending_call_ids'], ['call-0'])
        self.assertEqual(result['reserve_call_ids'], ['call-0'])
        self.assertEqual(self.plan_commits, [])


if __name__ == '__main__':
    unittest.main()
