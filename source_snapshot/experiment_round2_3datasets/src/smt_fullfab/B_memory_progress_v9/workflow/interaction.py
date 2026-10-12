"""Pure review draft: original envelopes -> assembly -> explicit check/selection.

No transport, budget, SQLite, environment or physical execution imports. Local
call references and byte hashes are structural evidence, not authentication.
"""
from base64 import b64encode
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path

from src.smt_fullfab.delta_session import DeltaSession
from src.smt_fullfab.plan_delta import compile_plan_delta


def _dependency(filename, expected_sha):
    path = Path(__file__).resolve().parent / filename
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise RuntimeError('review dependency differs from the pinned bytes: ' + str(path))
    spec = importlib.util.spec_from_file_location('_smt_fullfab_' + Path(filename).stem, path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(raw, str(path), 'exec'), module.__dict__)  # Execute the same pinned bytes, not a second path read.
    return module


DEPENDENCIES = {
    'prompt_protocol.py': '806aa12b6d7d27d0772d7c8aa64145fe6fffbeab2f618f43f20adeaf6792fdac',
    'delta_assembly.py': '6e1086caa2e5446d97f78541e3978355da5e39876261051fbbed140c2c50ccdf',
    'feedback_admission.py': 'a4083ce974544d63f4e3de0c4e4a5e3aac793cc858d11941fc1a7eb5018a2f79',
}
prompt_layer = _dependency('B_delta_prompt.py', DEPENDENCIES['prompt_protocol.py'])
assembly_layer = _dependency('B_delta_assembly.py', DEPENDENCIES['delta_assembly.py'])
feedback_layer = _dependency('B_feedback_admission.py', DEPENDENCIES['feedback_admission.py'])
render, digest = prompt_layer.render, prompt_layer.digest
require, exact_keys = prompt_layer.require, prompt_layer.exact_keys
Error = prompt_layer.ProtocolError

SCHEMA = 'draft-smt-fullfab-delta-interaction-v9-memory-progress-v1'
RESPONSE_SCHEMA = SCHEMA + '-response'
MEMORY_SCHEMA = SCHEMA + '-memory'
PROMPT_LIMIT = 120_000
MAX_OUTPUT_BYTES = 150_000
MAX_TOTAL_OUTPUT_BYTES = 16_000_000
MAX_ATTEMPTS = 1024
MAX_DRAFTS = 16
MAX_CANDIDATES = 32
MAX_PROMPT_FAILURES = 32
QUERY_ACTIONS = {
    'read_page': ['page_index'], 'read_base_tasks': ['task_ids'],
    'read_base_holds': ['hold_refs'], 'read_operations': ['operation_ids'],
}
VIEW_FIELDS = ['path', 'format', 'offset', 'count']
REQUEST_FIELDS = {
    'catalog_page': ['path', 'offset', 'count'], 'catalog_text': ['offset', 'count'],
    'session_query': ['action'], 'create_draft': ['draft_id'], 'assembly_action': ['action'],
    'check_assembly': ['draft_id', 'sealed_state_sha256', 'seal_action_sha256', 'delta_sha256'],
    'read_draft': ['draft_id', 'state_sha256', *VIEW_FIELDS],
    'read_candidate': ['candidate_id', 'candidate_sha256', *VIEW_FIELDS],
    'read_candidates': [],
    'read_archive_feedback': ['history_index', 'feedback_sha256', *VIEW_FIELDS],
    'apply': ['candidate_id', 'candidate_sha256'],
}
TASK_TEXT = '''You directly schedule the full declared production scope of SMT2020 Dataset 2 (913 production machines in the full experiment).
Minimize priority-weighted integral of overdue unfinished lots over the observation window; preserve throughput and avoid WIP growth. Raw priority 10/20/30 has evaluation weight 1/2/3. All production starts need your explicit plan; omitted work has no default dispatch or automatic planner.
Choose exact lot/operation/visit identities, machines, compatible batches, per-machine order, not_before start conditions, holds, freeze interval and revision reason. Times are seconds. Respect route precedence, processing/occupation, setup/minrun, availability, maintenance/down state, qualifications and known machine bindings, batch bounds, conditional future routes and frozen commitments from the complete observation. Unknown future random outcomes are unavailable; actual sampling/rework/disruption needs a new observation and a new externally registered session. Already dispatched work cannot be resubmitted or revised.
The current base and observation are authoritative inputs. Keep, cancel, replace and add are explicit model choices. Unchanged retained tasks keep their exact values, including old not_before; expired starts require an explicit replacement, never an automatic max(now,start). Pending frozen work forbids shortening freeze_until; preserve the complete pending machine prefix through its last frozen task without insertion or migration. Holds anchored to executed/deleted tasks cannot be retargeted automatically. Scope remains the full declared factory scope, and every base pending task/hold needs a complete explicit disposition. Do not permanently exclude difficult lots or machines.
Compact v2 is lossless: extras.values gives additional fields, extras.absent means absent, source_index preserves original array order, and eligible_override=all_family_machines means all machines in that family. Use explicit queries for all needed data; no page, reference, task or candidate is quality-ranked. Current catalog contains legacy action documentation as source data; ONLY the current request contract is executable here.
Declare a draft, explicitly submit all chunk fields and arrays, seal, then issue a separate check_assembly. A check runs only the pure constraint compiler; it does not certify physical execution. Inspect candidates with explicit queries. Apply must be another later output choosing an exact checked candidate/hash under the same four anchors. It returns one-time selection_for_external_commit only; a future outer common validator must still commit. No tool chooses a candidate, fills a missing field, optimizes or repairs the plan.
Incremental page workflow (any needed page may be reread with explicit read_reason): after reading a page, you may persist the decisions you have explicitly made as an assembly_action chunk before requesting another page. A chunk need not finish the plan. Never treat an unread page as a reason to exclude work. Cross-page machines, batches, order and the final global check remain your choices; do not finalize an indivisible machine_orders item until you have decided that machine's complete resulting order. No tool fills omitted decisions.
Use the existing exact queries to retrieve identities instead of rereading a whole production page only to recover work you already saved. A successful chunk returns assembly_result.state_sha256 and next_sequence. Keep the model-declared draft_id and that exact current SHA in your own memory if useful; the tool does not compress or rewrite memory. read_draft with that draft_id/state_sha256, path=["state","delta","tasks","add"] or ["state","delta","tasks","replace"], format="page", offset and count returns the original accepted task array slice in its original order. Append an exact array index to the path and use format="value",offset=0,count=1 to read one complete original task including all fields. format="text" exposes exact serialized characters for any oversized target. tasks.keep.ids are declarations of references, not copied task values; use session_query/read_base_tasks with explicit IDs for retained base values. Unavailable/undeclared paths are errors, not empty defaults.
For public input, session_query/read_operations accepts exact operation_ids in your requested order and returns all original fields. session_query/read_page returns the full original page for an explicit page_index; catalog_page/catalog_text provide unchanged metadata and reference arrays. read_archive_feedback with its original history_index and feedback_sha256 supports exact path/page/text access when an oversized-feedback diagnostic exposes that archive reference. That reference is local to this interaction and is not a new observation. Repeated reads can be reasonable for cross-page validation, exact identifiers, changed draft state or an earlier rejected query; no repeated-read quota or automatic next-page choice is imposed.
Only your explicit chunks save decisions. Query responses and memory do not add tasks. A draft remains uncompiled until your later explicit seal followed by a separate check_assembly; after inspecting the feedback, a still-later apply must select an exact checked candidate. Every scalar, empty array, base-task/hold disposition, and final machine order required by the existing contract must still be explicitly supplied. You may select an older checked candidate; no tool favors the latest one.
Keep memory for compact scheduling intentions, ideally below 2048 ASCII-escaped JSON characters including enclosing quotes and escapes; do not rewrite complete pages or accepted tasks in memory. You may write your own memory string, including empty, in each response envelope. The program returns that exact string with its source binding; it never summarizes previous feedback. Invalid identity/JSON wrappers cannot update memory. Oversize memory updates are rejected independently of otherwise valid actions. Complete outputs, queries and original feedback remain archived. The whole next prompt has a 120000-character limit: full original feedback is returned whenever that complete prompt fits. No separate 24000-character feedback limit applies. An oversized feedback diagnostic is NOT the complete original feedback; request its saved content using exact paths/slices or text chunks. Do not use shells, external sources, native tools, reference answers or other runs. Return only the exact JSON envelope described in INPUT_JSON.
'''
TASK_TEXT += """Current response_contract.runtime_references lists every current draft and candidate in creation order, without ranking or a default. Use these exact identities for existing read_draft/read_candidate actions. A dynamic response schema binds known context identifiers and the current prompt hash; you still directly choose memory, request, draft or candidate, all chunks, and every scheduling decision. No reference listing adds, replaces, cancels, orders or commits work. A new observation or new protocol version requires a separately recorded interaction.
"""
TASK_TEXT += """Progress is persistent external state derived only from successful original query responses and accepted draft contents. It is bound to this exact session, catalog and four anchors. It lists every successfully read page with exact archive reference, read counts and the first unread page index in catalog order (information, never an automatic query). A requested page rejected before dispatch is not read. Original full page responses remain available through read_archive_feedback using their history_index/full_response_sha256. On a repeated page request provide read_reason; it is logged and the exact same snapshot response is returned from cache with a separate cache receipt. No model output is rewritten. Use read_draft or read_operations for exact saved task values. Progress includes accepted task IDs, draft phase, next sequence and declared/missing paths; these are mechanical facts, never task recommendations. A prior V8 memory remains exact until you replace it yourself. Memory overflow must not cause you to repeat a successfully completed page read. Persist chosen decisions as chunks; a page read alone does not schedule work.
"""
TASK_TEXT_SHA256 = hashlib.sha256(TASK_TEXT.encode()).hexdigest()
ASSURANCE = {'model_called': False, 'transport_authenticated': False, 'model_attribution_certified': False,
             'budget_reserved': False, 'physical_validation_performed': False, 'physical_commit_performed': False,
             'cross_instance_deduplication': False}


class AdmissionError(ValueError):
    def __init__(self, detail, raw_output):
        self.raw_output = raw_output
        super().__init__(detail)


def raw_record(raw):
    return {'raw_output_base64': b64encode(raw).decode('ascii'),
            'raw_output_sha256': hashlib.sha256(raw).hexdigest(), 'raw_output_bytes': len(raw)}


def view(root, request):
    """Neutral complete access. Text mode covers otherwise indivisible values."""
    path = request['path']
    require(type(path) is list and all(type(k) is str or (type(k) is int and k >= 0) for k in path), 'path', 'exact string keys/nonnegative integer indices required')
    value = root
    for key in path:
        if type(value) is dict:
            require(type(key) is str and key in value, 'path', 'unknown object key')
        elif type(value) is list:
            require(type(key) is int and 0 <= key < len(value), 'path', 'unknown array index')
        else:
            raise Error('path', 'cannot descend into a scalar or string')
        value = value[key]
    offset, count, form = request['offset'], request['count'], request['format']
    require(type(offset) is int and offset >= 0 and type(count) is int and count > 0, 'slice', 'explicit exact offset/count required')
    require(type(form) is str and form in ('value', 'page', 'text'), 'view', 'explicit value/page/text format required')
    if form == 'value':
        require(offset == 0 and count == 1, 'slice', 'whole value requires offset=0,count=1')
        payload, total, returned = deepcopy(value), 1, 1
    else:
        if form == 'text':
            value = render(value)
        total = prompt_layer.extent(value)
        require(offset <= total, 'slice', 'offset exceeds exact source extent')
        if type(value) is dict:
            payload = [{'key': key, 'kind': prompt_layer.kind(item), 'extent': prompt_layer.extent(item)}
                       for key, item in list(value.items())[offset:offset + count]]
        elif type(value) in (list, str):
            payload = deepcopy(value[offset:offset + count])
        else:
            require(offset == 0 and count == 1, 'slice', 'scalar requires offset=0,count=1')
            payload = deepcopy(value)
        returned = min(count, max(0, total - offset))
    return {'status': 'query_result', 'query': deepcopy(request), 'root_sha256': digest(root),
            'payload': payload, 'total_extent': total, 'returned_extent': returned,
            'next_offset': offset + returned if offset + returned < total else None,
            'complete_for_requested_slice': True, 'no_quality_ranking': True}


class Interaction:
    def __init__(self, base_plan, problem, execution_state, *, source_sha256, paging):
        self._session = DeltaSession(base_plan, problem, execution_state, source_sha256=source_sha256, paging=paging)
        self._pager = prompt_layer.CatalogPager(self._session.describe())
        self._inputs = self._session.export_evidence()['inputs']
        identity = {'schema': SCHEMA, **self._pager.context(), 'dependencies': DEPENDENCIES, 'task_text_sha256': TASK_TEXT_SHA256}
        self._interaction_id = 'delta-interaction:' + digest(identity)
        self._drafts, self._draft_origins, self._draft_events = {}, {}, {}
        self._candidates = {}
        self._history, self._prompts, self._prompt_failures = [], [], []
        self._seen_calls, self._last_index, self._total_bytes = set(), -1, 0
        self._memory, self._feedback, self._pending_prompt, self._selection = None, None, None, None

    def context(self):
        return {'interaction_id': self._interaction_id, **self._pager.context()}

    def runtime_references(self):
        """Complete neutral metadata only; no preferred draft/candidate or tasks."""
        drafts = []
        for draft_id, draft in self._drafts.items():
            snapshot = draft.snapshot()
            state = snapshot['state']
            sealed = draft._sealed
            drafts.append({'draft_id': draft_id, 'state_sha256': snapshot['state_sha256'],
                'phase': state['phase'], 'next_sequence': state['next_sequence'],
                'seal_action_sha256': None if sealed is None else sealed['seal_action_sha256'],
                'delta_sha256': None if sealed is None else sealed['delta_sha256']})
        return {'schema': SCHEMA + '-references', 'order': 'creation_order_no_ranking',
                'drafts': drafts, 'candidates': [{'candidate_id': cid, 'candidate_sha256': digest(candidate)}
                    for cid, candidate in self._candidates.items()]}

    @classmethod
    def migrate(cls, parent, *, parent_evidence_sha256):
        require(parent._pending_prompt is None and parent._selection is None,
                'migration_boundary', 'only a completed, unselected interaction can migrate')
        require(digest(parent.export_evidence()) == parent_evidence_sha256,
                'migration_binding', 'original replayed evidence differs')
        self = cls.__new__(cls)
        self.__dict__ = deepcopy(parent.__dict__)
        self._migration = {'schema': SCHEMA+'-migration', 'parent_context': parent.context(),
            'parent_evidence_sha256': parent_evidence_sha256, 'history_count':len(parent._history),
            'preserved_draft_hashes': {k:d.state_sha256 for k,d in parent._drafts.items()},
            'preserved_memory_sha256': digest(parent._memory), 'pending_prompt_discarded': False}
        self._interaction_id = 'delta-interaction:' + digest({'schema': SCHEMA,
            'migration':self._migration, 'task_text_sha256':TASK_TEXT_SHA256})
        # Original history and sources keep original identities; only NEW envelopes use V9.
        return self

    def _page_records(self):
        pages = {}
        for row in self._history:
            env = row.get('parsed_envelope') or {}
            req = env.get('request', {})
            action = req.get('action', {})
            response = row['full_response']
            if (req.get('kind') == 'session_query' and action.get('action') == 'read_page'
                    and response.get('status') != 'rejected' and row.get('projection') is not None):
                idx = action['page_index']
                # A cache response preserves the original full_response payload below.
                p = pages.setdefault(idx, {'page_index':idx, 'history_index':row['history_index'],
                    'full_response_sha256':row['full_response_sha256'], 'successful_reads':0,
                    'last_model_index':row['model_index']})
                p['successful_reads'] += 1; p['last_model_index'] = row['model_index']
        return pages

    def progress(self):
        pages = self._page_records()
        catalog = self._pager.archive_catalog()
        # page_count is the unchanged public catalog page directory length.
        page_count = len(self._session.describe()['page_indices'])
        drafts = []
        for did,d in self._drafts.items():
            state=d.snapshot()['state']; delta=state['delta']
            def get(path):
                x=delta
                for key in path:
                    if not isinstance(x,dict) or key not in x:return None
                    x=x[key]
                return x
            drafts.append({'draft_id':did,'state_sha256':d.state_sha256,
                'phase':state['phase'],'next_sequence':state['next_sequence'],
                'declared_paths':[x['path'] for x in state['sources']],
                'missing_paths':[list(p) for p in (*assembly_layer.SET_PATHS,*assembly_layer.ARRAY_PATHS) if list(p) not in [x['path'] for x in state['sources']]],
                'task_add_ids':[x['id'] for x in (get(('tasks','add')) or [])],
                'task_replace_ids':[x['id'] for x in (get(('tasks','replace')) or [])],
                'task_cancel_ids':get(('tasks','cancel_ids')), 'task_keep':get(('tasks','keep')),
                'machine_order_ids':[x['machine'] for x in (get(('machine_orders',)) or [])]})
        return {'schema':SCHEMA+'-progress', 'snapshot_context':self.context(),
            'successful_pages':[pages[i] for i in sorted(pages)], 'page_count':page_count,
            'first_unread_page_index':next((i for i in range(page_count) if i not in pages),None),
            'drafts':drafts, 'migration':deepcopy(getattr(self,'_migration',None)),
            'no_quality_ranking':True,'automatic_page_advance':False}

    def _dispatch_with_progress(self, request, binding, reason):
        action=request.get('action',{}) if isinstance(request,dict) else {}
        if request.get('kind')=='session_query' and action.get('action')=='read_page':
            # Validate exact request and context even for a cache hit.
            exact_keys(request,('kind','action'))
            exact_keys(action,('action','session_id','anchors','page_index'))
            require(action['session_id']==self.context()['session_id'] and action['anchors']==self.context()['anchors'],
                    'stale_context','cached page snapshot differs')
            require(type(action['page_index']) is int,'page_index','exact integer page required')
            prior=self._page_records().get(action['page_index'])
            if prior is not None:
                require(bool(reason.strip()),'repeat_reason_required',
                        'this page was already read successfully; state a reason or choose an explicit different action')
                response=deepcopy(self._history[prior['history_index']]['full_response'])
                response['page_cache_receipt']={'hit':True,'snapshot_context':self.context(),
                    'original_history_index':prior['history_index'],
                    'original_full_response_sha256':prior['full_response_sha256'],
                    'read_reason':reason,'underlying_query_reexecuted':False}
                return response
        return self._dispatch(request,binding)

    def _contract(self):
        return {'schema': RESPONSE_SCHEMA, **self.context(), 'runtime_references': self.runtime_references(),
                'exact_envelope_fields': ['schema', 'interaction_id', 'session_id', 'anchors', 'catalog_sha256', 'prompt_body_sha256', 'memory', 'read_reason', 'request'],
                'memory': 'Exact model-authored string. Aim <=2048 ASCII-escaped JSON characters, including quotes. Update limit8192. Oversize updates are archived and rejected independently; a valid request still executes once. Previous accepted memory stays unchanged; empty is allowed.',
                'read_reason': 'Empty for a first read/non-page action; a repeated page read requires a nonempty explanation (e.g. cross-page validation or recovering exact values). Every request remains archived.',
                'prompt_body_sha256': 'Echo the visible PROMPT_BODY_SHA256 header. It hashes all task text plus INPUT_JSON below that header; the final prompt also has a separate archived full-text hash.',
                'request_exact_fields': {k: ['kind', *v] for k, v in REQUEST_FIELDS.items()},
                'session_query': {'exact_action_fields': {k: ['action', 'session_id', 'anchors', *v] for k, v in QUERY_ACTIONS.items()},
                                  'identity': 'The complete original action must use this session_id and four anchors.'},
                'create_draft': 'Nonempty new model-declared draft_id; unique in this object, never an automatic default.',
                'assembly_action': {'schema': assembly_layer.SCHEMA,
                    'chunk_exact_fields': ['schema', 'action', 'draft_id', 'anchors', 'previous_state_sha256', 'sequence', 'chunk_id', 'set_fields', 'append_arrays'],
                    'seal_exact_fields': ['schema', 'action', 'draft_id', 'anchors', 'previous_state_sha256'],
                    'chunk': 'action=chunk; sequence is the next successful integer sequence; chunk_id unique; set_fields=[{path,value}], append_arrays=[{path,items}]. Array append preserves original order; no overwrite. All paths must be explicitly declared, including empty arrays.',
                    'set_paths': [list(p) for p in assembly_layer.SET_PATHS], 'array_paths': [list(p) for p in assembly_layer.ARRAY_PATHS],
                    'delta_schema': assembly_layer.DELTA_SCHEMA, 'order_policy': assembly_layer.ORDER_POLICY,
                    'plan_header_exact_fields': ['version', 'created_at', 'valid_until', 'freeze_until', 'reason', 'scope'],
                    'task_required_fields': ['id', 'machine', 'lot_ids', 'steps', 'visits', 'operation_ids', 'not_before'],
                    'task_types': 'id nonempty string; machine exact integer; lot_ids/operation_ids nonempty unique string arrays; steps/visits positive exact integers of equal lengths; not_before finite number; extra fields preserved.',
                    'hold_required_fields': ['machine', 'until', 'reason'], 'hold_optional_anchor': 'after_task_id:string or null; never inferred',
                    'hold_replace': '{ref:exact base hold ref,hold:complete hold}',
                    'keep_modes': {'tasks': ['ids', 'all_pending_except'], 'holds': ['ids', 'all_except']},
                    'machine_orders': 'Each item exactly {machine:integer,task_ids:unique string array}; full resulting order for one machine is indivisible. A machine may be declared once.',
                    'seal': 'action=seal; reference current complete draft state SHA256; all 15 paths required; one-time; never compile/apply.'},
                'check_assembly': 'Reference draft_id plus its current sealed_state_sha256, original seal_action_sha256 and complete delta_sha256; only this later action calls the pure compiler.',
                'views': 'read_draft/read_candidate/read_archive_feedback require exact root hash, path of string keys/integer indices, format=value/page/text, offset>=0,count>0 exact ints. value returns full target (offset0,count1); page returns original-order object descriptors/array slice/string slice/scalar; text returns exact serialized target character slice.',
                'read_candidates': 'Creation-order summaries only; no default/preferred candidate.',
                'apply': 'Later separate output must name a checked candidate_id and exact candidate_sha256. One-time selection_for_external_commit; no physical execution.'}

    def _frame(self, turn_index):
        """Read-only complete next-turn frame; no issuing/query/action mutation."""
        return {'schema': SCHEMA, **self.context(), 'turn_index': turn_index,
                'task_text_sha256': TASK_TEXT_SHA256, 'directory': self._pager.directory(),
                'memory': '' if self._memory is None else self._memory['memory'],
                'memory_binding': {'kind': 'initial_empty'} if self._memory is None else {k: deepcopy(v) for k, v in self._memory.items() if k != 'memory'},
                'memory_policy': 'Exact most recent accepted memory including preserved V8 source binding. An oversized update never replaces it and does not reject the action. No truncation or automatic summary.',
                'progress': self.progress(),
                'memory_budget': {'current_serialized_characters': len(render('' if self._memory is None else self._memory['memory'])), 'update_limit':8192, 'recommended_target':2048},
                'feedback': None, 'response_contract': self._contract(),
                'limits': {'prompt_characters': PROMPT_LIMIT, 'memory_serialized_characters': 8192,
                           'feedback_admission_policy': feedback_layer.VERSION, 'raw_output_bytes': MAX_OUTPUT_BYTES,
                           'assembly_action_characters': assembly_layer.MAX_ACTION_CHARS}}

    def next_prompt(self):
        require(self._selection is None, 'selected', 'session has already selected; no next prompt or automatic revision')
        if self._pending_prompt is not None:
            return deepcopy(self._pending_prompt)
        try:
            row = feedback_layer.build_prompt(TASK_TEXT, self._frame(len(self._history)), self._feedback)
        except feedback_layer.PromptTooLarge as error:
            row = error.row
            if len(self._prompt_failures) < MAX_PROMPT_FAILURES:
                self._prompt_failures.append(deepcopy(row))
            raise Error('prompt_size', 'exact prompt exceeds 120000 characters; no content truncated or sent', archive=row) from error
        self._pending_prompt = deepcopy(row)
        self._prompts.append(deepcopy(row))
        return deepcopy(row)

    def _validate(self, raw):
        envelope = prompt_layer.strict_json(raw)
        render(envelope)  # Reject e.g. JSON exponent 1e999 parsed as infinity before storing a parsed envelope.
        exact_keys(envelope, ('schema', 'interaction_id', 'session_id', 'anchors', 'catalog_sha256', 'prompt_body_sha256', 'memory', 'read_reason', 'request'))
        require(envelope['schema'] == RESPONSE_SCHEMA, 'schema', 'unsupported interaction envelope')
        for key, value in self.context().items():
            require(type(envelope[key]) is type(value) and envelope[key] == value, 'stale_context', 'interaction/session/anchors/catalog must match')
        require(self._pending_prompt is not None and envelope['prompt_body_sha256'] == self._pending_prompt['prompt_body_sha256'], 'prompt_binding', 'output must reference this currently issued prompt body')
        require(type(envelope['memory']) is str, 'memory_type', 'memory must be a string')
        require(type(envelope['read_reason']) is str, 'read_reason', 'explicit read reason string required')
        return envelope

    def _binding(self, context, envelope):
        return {**deepcopy(context), 'envelope_sha256': digest(envelope),
                'request_sha256': digest(envelope['request']), 'projection_pointer': '/request',
                'prompt_body_sha256': envelope['prompt_body_sha256'],
                'issued_prompt_sha256': self._pending_prompt['prompt_sha256']}

    def _draft(self, draft_id):
        require(type(draft_id) is str and draft_id in self._drafts, 'unknown_draft', 'explicit existing draft required')
        return self._drafts[draft_id]

    def _candidate(self, request):
        cid = request['candidate_id']
        require(type(cid) is str and cid in self._candidates, 'unknown_candidate', 'explicit checked candidate required')
        candidate = self._candidates[cid]
        require(request['candidate_sha256'] == digest(candidate), 'candidate_hash', 'complete candidate hash mismatch')
        require(candidate['anchors'] == self.context()['anchors'] and candidate['interaction_id'] == self._interaction_id, 'stale_context', 'candidate belongs to another observation')
        return candidate

    @staticmethod
    def _summary(candidate):
        return {'candidate_id': candidate['candidate_id'], 'candidate_sha256': digest(candidate),
                'delta_sha256': candidate['delta_sha256'],
                'compiled_plan_sha256': candidate['compiled']['evidence']['compiled_plan_sha256'],
                'task_count': len(candidate['compiled']['plan']['tasks']), 'hold_count': len(candidate['compiled']['plan']['holds']),
                'check_binding': deepcopy(candidate['provenance']['check']), 'compiler_accepted': True,
                'physical_validation_performed': False, 'selected_for_external_commit': False}

    def _dispatch(self, request, binding):
        require(self._selection is None, 'selected', 'session already selected; no subsequent action')
        require(type(request) is dict and type(request.get('kind')) is str and request['kind'] in REQUEST_FIELDS, 'request', 'unknown explicit request')
        kind = request['kind']
        exact_keys(request, ['kind', *REQUEST_FIELDS[kind]], 'request')
        if kind in ('catalog_page', 'catalog_text'):
            return self._pager.query(request)
        if kind == 'session_query':
            action = request['action']
            require(type(action) is dict and type(action.get('action')) is str and action['action'] in QUERY_ACTIONS,
                    'query_only', 'only four original read-only session actions are allowed; no fabricated check_delta/apply')
            exact_keys(action, ['action', 'session_id', 'anchors', *QUERY_ACTIONS[action['action']]], 'query_only')
            require(action['session_id'] == self.context()['session_id'] and action['anchors'] == self.context()['anchors'], 'stale_context', 'original query anchors/session differ')
            return self._session.handle(deepcopy(action), call_id=binding['call_id'], model_index=binding['model_index'])
        if kind == 'create_draft':
            did = request['draft_id']
            require(type(did) is str and did not in self._drafts, 'draft_id', 'draft ID must be a new explicit string')
            require(len(self._drafts) < MAX_DRAFTS, 'draft_limit', 'draft capacity exhausted; no eviction/reset')
            draft = assembly_layer.DeltaAssembly(did, self.context()['anchors'])
            self._drafts[did] = draft;self._draft_origins[did] = deepcopy(binding);self._draft_events[did] = []
            return {'status': 'draft_created', 'draft_id': did, **draft.snapshot()}
        if kind == 'assembly_action':
            action = request['action']
            require(type(action) is dict, 'assembly', 'complete original assembly action required')
            draft = self._draft(action.get('draft_id'))
            response = draft.submit(deepcopy(action))
            if response['status'] in ('chunk_accepted', 'sealed_delta'):
                self._draft_events[action['draft_id']].append({**deepcopy(binding), 'action_sha256': digest(action),
                    'projection_pointer': '/request/action', 'assembly_action': action['action'],
                    'chunk_id': action.get('chunk_id'), 'result_state_sha256': draft.state_sha256})
            return {'status': response['status'], 'draft_id': action['draft_id'], 'assembly_result': response}
        if kind == 'read_draft':
            draft = self._draft(request['draft_id'])
            require(request['state_sha256'] == draft.state_sha256, 'draft_hash', 'draft state changed or hash mismatched')
            return view(draft.export_evidence(), request)
        if kind == 'check_assembly':
            draft = self._draft(request['draft_id']);evidence = draft.export_evidence();sealed = evidence['sealed']
            require(sealed is not None, 'unsealed', 'model must explicitly seal before check')
            require(request['sealed_state_sha256'] == draft.state_sha256
                    and request['seal_action_sha256'] == sealed['seal_action_sha256']
                    and request['delta_sha256'] == sealed['delta_sha256'], 'assembly_binding', 'check must identify exact sealed draft/action/delta hashes')
            require(self._draft_events[request['draft_id']][-1]['model_index'] < binding['model_index'], 'check_order', 'check must be a later original output than seal')
            require(len(self._candidates) < MAX_CANDIDATES, 'candidate_limit', 'candidate capacity exhausted')
            # This is an explicit check_assembly invocation. Never fabricate a raw check_delta model action.
            compiled = compile_plan_delta(self._inputs['base_plan'], self._inputs['problem'], self._inputs['execution_state'],
                                          deepcopy(sealed['delta']), source_sha256=self._inputs['source_sha256'])
            cid = self._interaction_id + ':candidate:' + str(len(self._candidates))
            candidate = {'schema': SCHEMA + '-candidate', 'candidate_id': cid, **self.context(),
                         'draft_id': request['draft_id'], 'sealed_state_sha256': draft.state_sha256,
                         'delta_sha256': sealed['delta_sha256'], 'delta': deepcopy(sealed['delta']), 'compiled': compiled,
                         'provenance': {'create': deepcopy(self._draft_origins[request['draft_id']]),
                                        'assembly_actions': deepcopy(self._draft_events[request['draft_id']]),
                                        'check': deepcopy(binding), 'original_delta_field_sources': deepcopy(sealed['sources']),
                                        'delta_origin': 'assembled exact model chunks, not a single original check_delta output',
                                        'transport_authenticated': False}}
            self._candidates[cid] = candidate
            return {'status': 'candidate_checked', 'candidate': self._summary(candidate)}
        if kind == 'read_candidates':
            return {'status': 'query_result', 'candidates': [self._summary(c) for c in self._candidates.values()],
                    'order': 'successful check creation order; no preferred/default candidate'}
        if kind == 'read_candidate':
            return view(self._candidate(request), request)
        if kind == 'read_archive_feedback':
            index = request['history_index']
            require(type(index) is int and 0 <= index < len(self._history), 'feedback_index', 'exact earlier history index required')
            feedback = self._history[index]['full_response']
            require(request['feedback_sha256'] == digest(feedback), 'feedback_hash', 'complete archived feedback hash mismatch')
            return view(feedback, request)
        candidate = self._candidate(request)
        require(candidate['provenance']['check']['model_index'] < binding['model_index']
                and candidate['provenance']['check']['history_index'] < binding['history_index'], 'apply_order', 'apply must be a later separate output than check')
        selection = {'status': 'selection_for_external_commit', **self.context(),
                     'candidate_id': candidate['candidate_id'], 'candidate_sha256': digest(candidate),
                     'candidate': deepcopy(candidate), 'selection_binding': deepcopy(binding),
                     'external_common_validation_required': True, **deepcopy(ASSURANCE)}
        self._selection = deepcopy(selection)
        return selection

    def handle(self, raw_output, *, call_id, model_index):
        """Every bounded attempted output is preserved; no transport authenticity claimed."""
        if type(raw_output) is not bytes or len(raw_output) > MAX_OUTPUT_BYTES or self._total_bytes + len(raw_output) > MAX_TOTAL_OUTPUT_BYTES or len(self._history) >= MAX_ATTEMPTS:
            raise AdmissionError('raw output/attempt admission cap exceeded; archive supplied bytes externally, no existing evidence evicted', raw_output)
        archive = raw_record(raw_output)
        # Attribution references must themselves be finite JSON to remain exportable.
        try:
            render(call_id);render(model_index)
        except Error:
            raise AdmissionError('call references must be JSON values; raw output preserved in exception', raw_output) from None
        context = {'history_index': len(self._history), 'call_id': deepcopy(call_id), 'model_index': deepcopy(model_index),
                   'raw_output_sha256': archive['raw_output_sha256']}
        envelope = None;binding = None;projection = None
        pending = deepcopy(self._pending_prompt)
        memory_before = deepcopy(self._memory)
        try:
            require(type(call_id) is str and call_id and type(model_index) is int and model_index >= 0, 'call_identity', 'new nonempty call ID and exact nonnegative model index required')
            fresh = call_id not in self._seen_calls and model_index > self._last_index
            self._seen_calls.add(call_id);self._last_index = max(self._last_index, model_index)
            require(fresh, 'call_reuse', 'identity already attempted or index not strictly increasing')
            envelope = self._validate(raw_output);binding = self._binding(context, envelope)
            request = envelope['request']
            projection = {'pointer': '/request', 'value': deepcopy(request), 'value_sha256': digest(request),
                          'raw_output_sha256': archive['raw_output_sha256'], 'envelope_sha256': digest(envelope)}
            if type(request) is dict and request.get('kind') in ('assembly_action', 'session_query') and 'action' in request:
                projection['nested_action'] = {'pointer': '/request/action', 'value': deepcopy(request['action']), 'value_sha256': digest(request['action'])}
            memory_size = len(render(envelope['memory']))
            memory_update = {'status': 'accepted' if memory_size <= 8192 else 'rejected_oversize',
                'serialized_characters': memory_size, 'limit': 8192, 'recommended_target': 2048,
                'raw_memory_sha256': digest(envelope['memory']), 'action_not_rejected_by_memory': True}
            if memory_size <= 8192:
                self._memory = {'schema': MEMORY_SCHEMA, **self.context(), 'memory': envelope['memory'],
                                'memory_sha256': digest(envelope['memory']), 'source': deepcopy(binding)}
            full_response = self._dispatch_with_progress(request, binding, envelope['read_reason'])
            full_response['memory_update'] = memory_update
        except Exception as error:
            full_response = {'status': 'rejected', 'error': {'type': type(error).__name__, 'code': getattr(error, 'code', 'unexpected_exception'),
                                                           'detail': str(error)}, **deepcopy(ASSURANCE)}
            if envelope is not None and binding is not None and 'memory_update' in locals():
                full_response['memory_update'] = memory_update
            if getattr(error, 'archive', None) is not None:
                full_response['original_error_archive'] = deepcopy(error.archive)
        if self._selection is not None:
            self._selection = deepcopy(full_response)
            # Terminal selection has no next model call or admission preview.
            feedback = deepcopy(full_response)
            admission = {'schema': feedback_layer.VERSION + '-terminal',
                         'decision': 'terminal_no_next_prompt', 'next_prompt_built': False}
        else:
            measured = feedback_layer.admit_feedback(TASK_TEXT, self._frame(len(self._history) + 1),
                full_response, history_index=len(self._history))
            feedback = deepcopy(measured['feedback'])
            # These exact originals already have dedicated fields in this one
            # attempted-output row. Retain every measurement without duplicating
            # whole feedback/text/prompt payloads in the receipt.
            admission = {k: deepcopy(v) for k, v in measured.items()
                         if k not in ('full_response', 'full_response_serialized_text', 'feedback', 'preview')}
        row = {**context, **archive, 'issued_prompt_sha256': None if pending is None else pending['prompt_sha256'],
               'issued_prompt_body_sha256': None if pending is None else pending['prompt_body_sha256'],
               'parsed_envelope': deepcopy(envelope), 'projection': deepcopy(projection),
               'memory_before': memory_before, 'memory_after': deepcopy(self._memory),
               'full_response': deepcopy(full_response), 'full_response_sha256': digest(full_response),
               'full_response_serialized_text': render(full_response),
               'feedback': deepcopy(feedback), 'feedback_sha256': digest(feedback),
               'feedback_admission': admission,
               'previous_record_sha256': self._history[-1]['record_sha256'] if self._history else None}
        row['record_sha256'] = digest(row)
        self._history.append(row);self._feedback = deepcopy(feedback)
        self._pending_prompt = None;self._total_bytes += len(raw_output)
        return {'response': deepcopy(full_response), 'feedback': deepcopy(feedback), 'history_index': row['history_index'],
                'record_sha256': row['record_sha256'], **deepcopy(ASSURANCE)}

    def export_evidence(self):
        return {'schema': SCHEMA + '-evidence', **self.context(), 'bootstrap': deepcopy(self._inputs),
                'protocol': {'task_text': TASK_TEXT, 'task_text_sha256': TASK_TEXT_SHA256,
                             'dependency_sha256': deepcopy(DEPENDENCIES), 'contract': self._contract()},
                'full_catalog': self._pager.archive_catalog(), 'prompts': deepcopy(self._prompts),
                'prompt_failures': deepcopy(self._prompt_failures), 'history': deepcopy(self._history),
                'drafts': {key: draft.export_evidence() for key, draft in self._drafts.items()},
                'candidates': [{'candidate_sha256': digest(c), 'candidate': deepcopy(c)} for c in self._candidates.values()],
                'query_session_evidence': self._session.export_evidence(), 'selection': deepcopy(self._selection),
                'current_memory': deepcopy(self._memory), 'total_output_bytes': self._total_bytes,
                'assurance': deepcopy(ASSURANCE), 'progress': self.progress(),
                'external_requirements': 'Persistently register instances; replay exact bootstrap/prompts/raw outputs against frozen code; verify real transport/request/ledger; recheck actual anchors and common commit/independent physical audit. No auto replay/commit is implemented.'}
