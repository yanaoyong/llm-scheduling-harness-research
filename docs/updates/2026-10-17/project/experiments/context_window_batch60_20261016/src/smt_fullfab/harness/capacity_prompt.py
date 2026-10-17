"""Capacity-bounded, lossless public packets shared by both treatments."""
from collections import OrderedDict, defaultdict, deque
from copy import deepcopy
import base64

from .contracts import encode, require, strict_json
from .local_tokens import count
from .presentation import pack, unpack

INSTRUCTIONS = '''
Dynamic collection has no fixed 60-second batch clock. Already submitted tasks keep
executing. Supported public forecasts are collected with at least 60 seconds between
forecast rounds; include the next 60 seconds of nearby forecasts. Plan renewal/invalidation,
input capacity, or 60 seconds of continuously executable uncovered demand triggers
planning. An unresolved ready-demand timer never resets merely on a new plan.
All production choices, including explicit holds and follow-up tasks on busy machines,
remain yours. This packet covers the pending demand and its complete operation
DEPENDENCY bundles; it does not assert that every machine or operation is inline.
Records use lossless tables and exact source indices. All omitted resource details,
base-plan tasks, constraints and catalogs remain readable via public_refs. Read missing
constraints before relying on them; absence from the packet is not absence from the
factory. The full execution state and demand ledger have their own exact references.
Existing accepted tasks outside the displayed slice still apply. The complete scope
is in the original public problem/base plan, never the displayed resource subset.
History records your decisions, not authoritative current state. No fixed 48-operation,
8-entry or 60k-result preview applies. Capacity diagnostics do not choose production
actions or automatically request another model response. Simulation pauses for decisions.
One system has two strategies: initial builds the first runnable segment, continuation
preserves confirmed tasks and adds follow-up work. planning_batch identifies the fixed
evidence scope for this observation. Overflow stays pending and is prioritized in later
batches; it is not silently resolved. Capacity notices are consumed for a known cohort
only on explicit accepted selection; the same old catalog cannot immediately re-trigger
capacity. Unresolved ready deadlines do NOT reset. Keep valid base tasks with explicit
all_pending_except/keep; cancel or replace only by your deliberate production choice.
Do not shorten validity below retained future starts. You may consult other public
records and choose tasks beyond this packet. Batch order never chooses production.
Focus machines caused this decision or have nearby needs. Their unresolved evidence
has priority even if previously shown. focus_coverage distinguishes complete, partial
and absent evidence; never treat an omitted machine as reviewed or resolved.
Optional machine_reviews can accompany apply_candidate (planned, deferred, or
insufficient_information, with reason and revisit_at). They record YOUR assessment,
not a task or hold, and cannot reset a ready timer or suppress the 60-second deadline.
The host computes coverage locally without another model call. Previously shown,
explicitly reviewed and actually scheduled are separate states.
machine_review_counts summarizes unreported entries; full machine_reviews_ref remains
readable. Requested revisit_at is advisory: it cannot override the forecast interval
or a real ready deadline. No annotation creates a machine hold.
'''



def instructions(capacity):
    from .capacity_config import DEADLINE_POLICY, is_original
    if capacity.get('policy') != DEADLINE_POLICY:return INSTRUCTIONS
    if is_original(capacity):
        rules = ('Execution uses the original rules: executable uncovered demand pauses immediately; '
                 'plan expiry/invalidation and original periodic boundaries also stop execution. '
                 'Forecasts and capacity are evidence organization only, not execution triggers.\n')
    else:
        rules = ('Executable uncovered demand triggers planning immediately, with no batching wait. '
                 'Forecast reminders are collected for up to 60 seconds but never after the latest '
                 'planning start. An earlier deadline overrides collection spacing. A delivered early '
                 'notice can be escalated once at its deadline if still unplanned; a delivered deadline '
                 'notice is not repeated for the same episode. A deadline round also covers included '
                 'deadlines in the next 60 seconds, avoiding separate notices seconds apart. '
                 'Actual executable demand always overrides it.\n')
    rules += ('Latest planning start = supported need time minus the declared planning/preparation budget '
              f"({capacity['planning_lead_seconds']} seconds, provisional offline setting). "
              'No fixed forecast lookahead cap: related future evidence is ordered by urgency and packed '
              'as complete dependency units up to the input budget. forecast_scope reports actual coverage. '
              'Notification delivery is not proof of review or production coverage.\n')
    common = INSTRUCTIONS[INSTRUCTIONS.index('All production choices,'):]
    common = common.replace('suppress the 60-second deadline','defer executable uncovered demand')
    common = common.replace('or a real ready deadline','or immediate executable-demand handling')
    common = common.replace('it cannot override the forecast interval',
                            'it cannot postpone the latest planning start')
    return '\n'+rules+common


class PublicPacket:
    """Whole dependency bundles, scoped to demand; exact overflow references.

    Complete related resource/plan records are preferred. A single oversized
    bundle uses explicit detail paging instead of requiring all resources inline.
    The bundle order organizes evidence only; it never chooses production work.
    """
    def __init__(self, context, *, requested_ids=(), deprioritized_ids=(), urgent_ids=(), priority_by_operation=None):
        self.context = context; self.problem = context['problem']; self.ops = self.problem['operations']
        self.index = {o['operation_id']:i for i,o in enumerate(self.ops)}
        require(len(self.index) == len(self.ops), 'public_operation_ids', 'Unique operation IDs required')
        self.families = OrderedDict(); lots = OrderedDict()
        for i,op in enumerate(self.ops):
            self.families.setdefault(op['family'], []).append(i)
            lots.setdefault(op['lot_id'], []).append(i)
        parent = list(range(len(self.ops)))
        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]; i = parent[i]
            return i
        def union(a,b):
            a,b = find(a),find(b)
            if a != b: parent[b] = a
        for indices in lots.values():
            for i in indices[1:]: union(indices[0],i)
        for i,op in enumerate(self.ops):
            for oid in [*op.get('predecessor_ids',[]), *([op['same_machine_as']] if 'same_machine_as' in op else [])]:
                require(oid in self.index, 'public_dependency_gap', 'Exported dependency is missing', operation_id=oid)
                union(i,self.index[oid])
        components = OrderedDict()
        for i in range(len(self.ops)): components.setdefault(find(i),[]).append(i)
        demands = context.get('batch_demands')
        self.demands = demands or []
        wanted = set(requested_ids)
        if context.get('planning_batch') is not None:
            wanted.update(context['planning_batch']['operation_ids'])
        elif demands is None: wanted.update(self.index)  # explicit full-snapshot codec probe / legacy fixture
        else:
            for d in demands: wanted.update(d['operation_ids'])
        roots = {find(self.index[oid]) for oid in wanted if oid in self.index}
        requested_roots = {find(self.index[oid]) for oid in requested_ids if oid in self.index}
        age = {}
        for d in self.demands:
            for oid in d['operation_ids']:
                if oid in self.index:
                    root = find(self.index[oid]); age[root] = min(age.get(root,float('inf')),d['first_seen'])
        # Chronological collection order, stable original order at equal time.
        seen = set(deprioritized_ids)
        urgent_roots = {find(self.index[oid]) for oid in urgent_ids if oid in self.index}
        priorities = dict(priority_by_operation or {})
        for demand in (context.get('planning_batch') or {}).get('focus_demands',[]):
            for oid in demand['operation_ids']:
                priorities[oid] = min(priorities.get(oid,(3,0)),(demand['rank'],demand['deadline']))
        rank = lambda root:min((priorities.get(self.ops[i]['operation_id'],(3,0)) for i in components[root]),default=(3,0))
        ordered = sorted(roots, key=lambda root:(root not in requested_roots,rank(root),
            root not in urgent_roots,
            all(self.ops[i]['operation_id'] not in wanted or self.ops[i]['operation_id'] in seen for i in components[root]),
            age.get(root,0),components[root][0]))
        self.bundles = [components[root] for root in ordered]
        self.order,self.ends = [],[0]
        for indices in self.bundles:
            self.order.extend(indices); self.ends.append(len(self.order))
        self.tables = {f:pack([self.ops[i] for i in indices]) for f,indices in self.families.items()}
        self.total_machines = len(self.problem['machines'])

    def selected(self, prefix): return set(self.order[:self.ends[prefix]])

    def frame(self, prefix, controls, *, paged_details=False, minimal_metadata=False, machine_limit=None):
        from .deadline_collection import forecast_scope
        selected = self.selected(prefix); groups = []
        for family,indices in self.families.items():
            positions = [j for j,i in enumerate(indices) if i in selected]
            if not positions: continue
            table = self.tables[family]
            if isinstance(table,list): part = [table[j] for j in positions]
            else: part = {**table,'rows':[table['rows'][j] for j in positions],'record_count':len(positions)}
            groups.append({'family':family,'source_indices':[indices[j] for j in positions],'records':part})
        mids = {mid for i in selected for mid in self.ops[i]['eligible_machines']}
        machines = [(i,m) for i,m in enumerate(self.problem['machines']) if m['machine'] in mids]
        if paged_details: machines = machines[:machine_limit or 0]
        inline_mids = {m['machine'] for _,m in machines}
        base = self.context['base_plan']; tasks = base['tasks']; holds = base['holds']
        task_rows = [(i,t) for i,t in enumerate(tasks) if t['machine'] in mids] if not paged_details else []
        hold_rows = [(i,h) for i,h in enumerate(holds) if h['machine'] in mids] if not paged_details else []
        metadata = {k:v for k,v in self.problem.items() if k not in ('machines','operations')}
        if minimal_metadata:
            metadata = {k:self.problem[k] for k in ('schema','time','horizon_end','lookahead_depth') if k in self.problem}
        execution = self.context['execution_state']
        dispatched = set(execution.get('dispatched_task_ids',[]))
        header = {k:v for k,v in base.items() if k not in ('tasks','holds','scope')}
        batch = self.context.get('planning_batch')
        focus_demands = batch.get('focus_demands',[]) if batch else self.context.get('packet_focus_demands',[])
        focus = []
        reviews = list(self.context.get('machine_reviews',{}).values())
        explicit_reviews = [r for r in reviews if r.get('model_review') is not None or r['production_status']=='planned']
        if focus_demands:
            chosen = {self.ops[i]['operation_id'] for i in selected}
            for row in focus_demands:
                offered = len(chosen.intersection(row['operation_ids'])); total = len(row['operation_ids'])
                focus.append({k:v for k,v in row.items() if k!='operation_ids'} | {
                    'candidate_count':total,'inline_candidates':offered,
                    'information_status':'complete' if offered==total else 'partial' if offered else 'not_offered'})
        return {**controls,
            **({'forecast_scope':forecast_scope(focus)} if any('forecast_latest_start' in row for row in focus) else {}),
            **({'planning_batch':{k:batch[k] for k in ('batch_id','strategy','opened_at',
                'offered_operation_count','cohort_operation_count','not_yet_offered_count','requires_paged_read')}} if batch else {}),
            **({'focus_coverage':pack(focus), 'machine_reviews':pack(explicit_reviews),
                'machine_review_counts':{'total':len(reviews),'inline':len(explicit_reviews),
                                         'unreported':sum(r.get('review_status')=='unreported' for r in reviews)}} if batch or focus_demands else {}),
            'demand_details':pack([{k:v for k,v in d.items() if k != 'operation_ids'} for d in self.demands if d['machine'] in inline_mids]),
            'public_problem': {**metadata,'machines':pack([m for _,m in machines]),
                               'machine_source_indices':[i for i,_ in machines], 'operation_groups':groups},
            'base_plan': {'header':header,'scope_ref':{'artifact_ref':self.context['base_plan_ref'],'path':['scope']},
                          'tasks':pack([t for _,t in task_rows]),'task_source_indices':[i for i,_ in task_rows],
                          'holds':pack([h for _,h in hold_rows]),'hold_source_indices':[i for i,_ in hold_rows],
                          'total_tasks':len(tasks),'total_holds':len(holds)},
            'execution_state': {k:v for k,v in execution.items() if k != 'dispatched_task_ids'} | {
                'dispatched_task_ids':[t['id'] for _,t in task_rows if t['id'] in dispatched],
                'total_dispatched_tasks':len(dispatched), 'complete':len(task_rows)==len(tasks)},
            'public_refs':{k:self.context[k] for k in ('problem_ref','facts_ref','base_plan_ref','execution_state_ref','batch_demands_ref','planning_batch_ref','machine_reviews_ref') if k in self.context},
            'capacity_coverage':{'total_operations':len(self.ops),'demand_operations':len(self.order),
                'inline_operations':len(selected),'omitted_demand_operations':len(self.order)-len(selected),
                'total_machines':self.total_machines,'inline_machines':len(machines),
                'omitted_related_machines':len(mids)-len(machines),'pending_demand_machines':len(self.demands),
                'metadata_complete':not minimal_metadata,'paged_details':paged_details,
                'full_catalog':{'artifact_ref':self.context['facts_ref'],'path':['catalogs']},
                'order':'ready deadline, triggering machine, nearby forecast, unoffered evidence, age/source order; no production scoring',
                'overflow_rule':'All omitted records remain at public_refs; absence from this packet is not absence from the factory.'}}

    def fit(self, controls, *, prefix, budget, reserve):
        limit = budget-reserve; paged = False; minimal = False; cache = {}
        def render(n, machine_limit=None):
            key=(n,paged,minimal,machine_limit)
            if key not in cache:
                frame=self.frame(n,controls,paged_details=paged,minimal_metadata=minimal,machine_limit=machine_limit)
                text=prefix+'\n'+encode(frame).decode();cache[key]=(count(text),text,frame)
            return cache[key]
        if render(0)[0] > limit: minimal = True
        require(render(0)[0] <= limit,'context_capacity','Essential references and feedback do not fit; no silent cut')
        if self.bundles and render(1)[0] > limit:
            paged = True
            if render(1)[0] > limit: minimal = True
        lo,hi=0,len(self.bundles)
        while lo<hi:
            mid=(lo+hi+1)//2
            if render(mid)[0] <= limit: lo=mid
            else: hi=mid-1
        machine_limit=None
        if paged:
            left,right=0,self.total_machines
            while left<right:
                mid=(left+right+1)//2
                if render(lo,mid)[0] <= limit:left=mid
                else:right=mid-1
            machine_limit=left
        tokens,text,frame=render(lo,machine_limit)
        self.verify(frame)
        return {'text':text,'frame':frame,'local_prompt_tokens':tokens,'wrapper_reserve_tokens':reserve,
                'budgeted_input_tokens':tokens+reserve,'input_budget':budget,
                'inline_operations':self.ends[lo],'demand_operations':len(self.order),'total_operations':len(self.ops),
                'inline_machines':frame['capacity_coverage']['inline_machines'],
                'paged_details':paged,'oversized_bundle_requires_paged_read':bool(self.bundles and lo==0),
                'encoding':'o200k_base','server_model_mapping_confirmed':False}

    def verify(self, frame):
        p=frame['public_problem'];base=frame['base_plan'];source=self.context['base_plan']
        require(encode(base['header'])==encode({k:v for k,v in source.items() if k not in ('tasks','holds','scope')}),'lossless_packet','Base header changed')
        for kind,index_key,original,container in (
            ('machines','machine_source_indices',self.problem['machines'],p),
            ('tasks','task_source_indices',source['tasks'],base),('holds','hold_source_indices',source['holds'],base)):
            rows=unpack(container[kind]);indices=container[index_key]
            require(len(rows)==len(indices) and len(indices)==len(set(indices)),'lossless_packet','Record indices differ')
            require(all(type(i) is int and 0<=i<len(original) for i in indices),'lossless_packet','Invalid source index')
            require(all(encode(row)==encode(original[i]) for i,row in zip(indices,rows)),'lossless_packet','Record field/type changed')
        restored={}
        for group in p['operation_groups']:
            rows=unpack(group['records'])
            require(len(rows)==len(group['source_indices']),'lossless_packet','Row indices differ')
            for i,row in zip(group['source_indices'],rows):
                require(type(i) is int and 0<=i<len(self.ops) and i not in restored and encode(row)==encode(self.ops[i]),'lossless_packet','Operation value/type changed')
                restored[i]=row
        ids={row['operation_id'] for row in restored.values()}
        for row in restored.values():
            require(set(row.get('predecessor_ids',[]))<=ids and row.get('same_machine_as',row['operation_id']) in ids,
                    'lossless_packet','Truncation split a dependency bundle')


def runtime_prompt(runtime, *, task=None):
    from .transport import PROTOCOL_TEXT, pending_start_validation
    from .contracts import digest
    cfg = runtime.config['capacity_experiment']
    context = runtime.context()
    full = runtime.store.read('contexts', context['context_ref'])
    context['pending_start_validation'] = pending_start_validation(full['base_plan'], set(context['pending_base_task_ids']), context['time'], context['base_plan_ref'])
    # No separate 64-row preview: all already-public validation rows are retained.
    context['pending_start_validation']['rows'] = [
        {'task_id':t['id'],'not_before':t['not_before'],'current_time':context['time'],'original_path':['tasks',i]}
        for i,t in enumerate(full['base_plan']['tasks']) if t['id'] in set(context['pending_base_task_ids']) and
        t['not_before'] < context['time'] and not (context['time'] < full['base_plan']['freeze_until'] and t['not_before'] < full['base_plan']['freeze_until'])]
    context['pending_start_validation']['omitted'] = 0
    history, latest, requested = [], None, []
    with runtime.store.transaction():
        for attempt_id, attempt in runtime.store.rows('attempts'):
            if attempt.get('status') != 'processed' or not attempt.get('response_ref'): continue
            raw = runtime.store.bytes(attempt['raw_ref'])
            try:
                action = strict_json(raw)
                if type(action) is dict and set(action) == {'action'}: action = action['action']
            except (ValueError, UnicodeError): action = None
            result = runtime.store.get(attempt['response_ref'])
            entry = runtime.store.read('capacity_interaction_entries', attempt_id)
            if entry is None:
                raw_view = {'encoding':'base64','data':base64.b64encode(raw).decode('ascii')}
                entry = {'attempt_id':attempt_id, 'context_ref':attempt['context_ref'], 'action':pack(action),
                         'raw_output_ref':runtime._publish(raw_view, 'own_output'),
                         'status':result.get('status'), 'result_ref':runtime._publish(result, 'own_tool_result'),
                         **{k:result[k] for k in ('candidate_ref','error','protocol_progress') if k in result}}
                runtime.store.record('capacity_interaction_entries', attempt_id, entry)
            history.append(entry)
            latest = {'entry':entry, 'result':pack(result)}
            if attempt['context_ref'] == context['context_ref'] and type(action) is dict and action.get('tool') == 'read_entities':
                requested.extend(e['id'] for q in result.get('results',[]) for e in q.get('entities',[]) if e.get('kind') == 'operations')
        history_ref = None
        if history:
            key = digest(history)
            cached = runtime.store.read('capacity_history_refs', key)
            history_ref = cached['ref'] if cached else runtime._publish(history, 'own_interaction_history')
            if cached is None: runtime.store.record('capacity_history_refs', key, {'ref':history_ref})
        metadata_ref = runtime._publish(context, 'public_context_metadata')
    metadata = context
    context = {k:metadata[k] for k in ('protocol_version','context_ref','state_revision','time','window_end',
                                     'base_plan_ref','base_task_count','base_hold_count','problem_ref','facts_ref')}
    context['full_context_metadata_ref'] = metadata_ref
    context['trigger_reason'] = (metadata.get('trigger') or {}).get('reason')
    for key in ('pending_start_validation','notes'):
        value = metadata[key]
        if count(encode(value).decode()) <= int(cfg['input_token_budget']*0.05): context[key] = value
        else: context[key] = {'inline':False,'artifact_ref':metadata_ref,'path':[key]}
    if latest and count(encode(latest['entry']).decode()) > int(cfg['input_token_budget']*cfg['history_budget_fraction']):
        latest['entry'] = {k:v for k,v in latest['entry'].items() if k in
                          ('attempt_id','context_ref','raw_output_ref','result_ref','status','candidate_ref')}
    tail = []
    history_limit = int(cfg['input_token_budget'] * cfg['history_budget_fraction'])
    for entry in reversed(history[:-1]):
        candidate = [entry, *tail]
        if count(encode(candidate).decode()) > history_limit: break
        tail = candidate
    controls = {'context':context, 'task':task, 'last_tool_feedback':latest,
                'interaction_history':{'count':len(history), 'entries':tail,
                                       'omitted':max(0,len(history)-len(tail)-(1 if latest else 0)), 'full_history_ref':history_ref}}
    builder = PublicPacket(full, requested_ids=requested)
    prefix = PROTOCOL_TEXT + instructions(cfg)
    while True:
        try:
            result = builder.fit(controls, prefix=prefix, budget=cfg['input_token_budget'], reserve=cfg['wrapper_reserve_tokens'])
            break
        except Exception as exc:
            from .contracts import HarnessError
            if not isinstance(exc, HarnessError) or exc.code != 'context_capacity': raise
            if controls['interaction_history']['entries']:
                controls['interaction_history']['entries'].pop(0)
                controls['interaction_history']['omitted'] += 1
            elif latest and 'result' in controls['last_tool_feedback']:
                # No small hardcoded preview; capacity fallback is explicit and addressable.
                controls['last_tool_feedback'] = {'entry':latest['entry'], 'inline':False,
                    'reason':'Full result exceeds remaining input capacity; read entry.result_ref with an explicit page.'}
            else: raise
    require(len(result['text']) <= runtime.config['limits']['context_chars'], 'context_capacity', 'Emergency character ceiling reached')
    runtime.last_capacity_measurement = {k:v for k,v in result.items() if k not in ('text','frame')}
    return result['text']
