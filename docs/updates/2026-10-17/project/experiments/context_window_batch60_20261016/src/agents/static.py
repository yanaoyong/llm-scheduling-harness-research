"""Real-model B and C runners. No model stub or hidden B scheduling policy."""
from __future__ import annotations
import dataclasses
import datetime as dt
import hashlib
import json
from pathlib import Path
import time
from .budget import BudgetLedger, BudgetExceeded
from .model_transport import ModelConfig, call_model, _write_json

ROOT = Path(__file__).resolve().parents[2]

class ActionError(ValueError):
    pass

def observed_problem(problem):
    """Allowlist; source paths, reference values, family labels and other runs excluded."""
    return {'machines':list(problem['machines']), 'jobs':[
        {'id':j['id'],'operations':[
            {'id':o['id'],'job':o['job'],'index':o['index'],
             'alternatives':[{'machine':a['machine'],'duration':a['duration']} for a in o['alternatives']]}
            for o in j['operations']]} for j in problem['jobs']]}

def compact_problem(problem):
    return {'format':'jobs[j][operation_index] = eligible [machine,duration] pairs; all indices zero-based',
            'machines':problem['machines'],
            'jobs':[[[[a['machine'],a['duration']] for a in op['alternatives']]
                     for op in job['operations']] for job in problem['jobs']]}

def decode_order(problem, order):
    """Append-only max-time calculation; rejects instead of repairing every bad decision."""
    ops = {o['id']:o for j in problem['jobs'] for o in j['operations']}
    if not isinstance(order,list) or len(order) != len(ops):
        raise ActionError(f'order must contain exactly {len(ops)} operations')
    next_index = {j['id']:0 for j in problem['jobs']}
    job_ready = {j['id']:0 for j in problem['jobs']}
    machine_ready = {m:0 for m in problem['machines']}
    seen, out = set(), []
    compact=bool(order) and isinstance(order[0],list)
    for k, action in enumerate(order):
        if compact:
            if not isinstance(action,list) or len(action)!=2 or any(type(x) is not int for x in action):
                raise ActionError(f'entry {k}: exactly two integers [job,machine] required')
            job,machine=action
            if job not in next_index:
                raise ActionError(f'entry {k}: unknown job {job}')
            action={'id':f'j{job}o{next_index[job]}','machine':machine}
        if not isinstance(action,dict) or set(action) != {'id','machine'}:
            raise ActionError(f'entry {k}: exactly id and machine required')
        oid, machine = action['id'], action['machine']
        if not isinstance(oid,str) or oid not in ops or oid in seen:
            raise ActionError(f'entry {k}: unknown or duplicate operation {oid!r}')
        if type(machine) is not int:
            raise ActionError(f'entry {k}: machine must be integer')
        op = ops[oid]
        if op['index'] != next_index[op['job']]:
            raise ActionError(f'entry {k}: {oid} violates its job precedence; expected index {next_index[op["job"]]}')
        alternatives = {a['machine']:a['duration'] for a in op['alternatives']}
        if machine not in alternatives:
            raise ActionError(f'entry {k}: machine {machine} ineligible for {oid}')
        start = max(job_ready[op['job']],machine_ready[machine])
        end = start + alternatives[machine]
        out.append(dict(id=oid,machine=machine,start=start,end=end))
        job_ready[op['job']] = machine_ready[machine] = end
        next_index[op['job']] += 1
        seen.add(oid)
    return {'operations':out}

def b_schema(n,compact=False):
    if compact:
        return {'type':'object','properties':{
            'order':{'type':'array','minItems':n,'maxItems':n,'items':{'type':'array','minItems':2,'maxItems':2,'items':{'type':'integer'}}},
            'rationale':{'type':'string'}},'required':['order','rationale'],'additionalProperties':False}
    return {'type':'object','properties':{
        'order':{'type':'array','minItems':n,'maxItems':n,'items':{
            'type':'object','properties':{'id':{'type':'string'},'machine':{'type':'integer'}},
            'required':['id','machine'],'additionalProperties':False}},
        'rationale':{'type':'string'}},'required':['order','rationale'],'additionalProperties':False}

C_SCHEMA = {'type':'object','properties':{
    'action':{'type':'string','enum':['solve','finish']},
    'time_limit':{'type':['number','null']},'seed':{'type':['integer','null']},
    'search_branching':{'type':['string','null'],'enum':['AUTOMATIC_SEARCH','FIXED_SEARCH','PORTFOLIO_SEARCH',None]},
    'randomize_search':{'type':['boolean','null']},'candidate_index':{'type':['integer','null']},
    'rationale':{'type':'string'}},'required':['action','time_limit','seed','search_branching','randomize_search','candidate_index','rationale'],'additionalProperties':False}

def _iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def _costs(models, solvers):
    keys = ('input_tokens','cached_input_tokens','output_tokens','cache_write_input_tokens','reasoning_output_tokens')
    return {'model_calls':len(models),'model_elapsed_seconds':sum(r.get('duration_seconds',0) for r in models),
            'usage':{k:sum(r['usage'][k] for r in models) if models and all(r.get('usage',{}).get(k) is not None for r in models) else None for k in keys},
            'cost_usd':None,'cost_status':'unknown: CLI returns no monetary bill',
            'pure_model_seconds':None,'backend_http_requests':None,
            'solver_calls':len(solvers),'solver_budget_seconds':sum(r['requested_seconds'] for r in solvers),
            'solver_wall_seconds':sum(r['result']['wall_seconds'] for r in solvers) if all(r['result'].get('wall_seconds') is not None for r in solvers) else None}

def _prepare(problem, run_dir, config, arm):
    config = dict(config or {})
    cfg = config.get('model',{})
    cfg = dataclasses.asdict(cfg) if isinstance(cfg,ModelConfig) else dict(cfg)
    model_config = ModelConfig(**cfg)
    if model_config.model != 'gpt-6-astra' or model_config.reasoning_effort != 'medium':
        raise ValueError('B/C protocol requires gpt-6-astra / medium')
    run_dir = Path(run_dir).resolve()
    run_dir.mkdir(parents=True,exist_ok=True)
    fingerprint = hashlib.sha256(json.dumps({'problem':problem,'config':{k:v for k,v in config.items() if k != 'resume'},'arm':arm},sort_keys=True,default=str).encode()).hexdigest()
    result_path = run_dir/'agent_result.json'
    if result_path.exists() and config.get('resume'):
        old = json.loads(result_path.read_text())
        if old['request_fingerprint'] != fingerprint:
            raise ValueError('Cannot replay changed agent request')
        return old
    with (run_dir/'agent.claim').open('x') as stream:
        stream.write(fingerprint+'\n')
    state = {'run_id':run_dir.name,'arm':arm,'instance_id':problem.get('instance_id'),
             'family':problem.get('family'),'request_fingerprint':fingerprint,'started_at':_iso(),
             'status':'failed','failure_type':None,'schedule':None,'validation':None,
             'actions':[],'model_results':[],'solver_results':[],'selected_candidate':None,
             'first_output_valid':False,'first_action_valid':False,'first_candidate_valid':None,
             'first_valid_output_seconds':None,'revision_success':False,'revisions':0}
    _write_json(run_dir/'agent_request.json',{'config':config,'problem':observed_problem(problem),'arm':arm,'request_fingerprint':fingerprint})
    max_calls = config.get('max_model_calls',2 if arm=='B' else 3)
    if type(max_calls) is not int or not 1 <= max_calls <= 8:
        raise ValueError('max_model_calls must be 1..8')
    wall_seconds = float(config.get('wall_seconds',600))
    if not 1 <= wall_seconds <= 1800:
        raise ValueError('wall_seconds must be 1..1800')
    return run_dir,config,model_config,state,max_calls,time.monotonic()+wall_seconds

def _invoke(prompt,schema,run_dir,model_cfg,state,deadline):
    remaining = deadline-time.monotonic()
    if remaining < 1:
        raise TimeoutError('Agent wall time exhausted')
    cfg = dataclasses.replace(model_cfg,timeout_seconds=min(model_cfg.timeout_seconds,remaining))
    result = call_model(prompt,schema,run_dir/f'model_call_{len(state["model_results"])+1:03d}',cfg)
    state['model_results'].append(result)
    if time.monotonic() > deadline:
        raise TimeoutError('Model response arrived after the agent wall deadline')
    if result['status'] != 'success':
        state['failure_type'] = result['failure_reason']
        return None
    return result['output']

def _finish(run_dir,state,begun):
    state['finished_at'] = _iso()
    state['metrics'] = {'makespan':state['validation']['makespan'] if state['status']=='success' else None,
                        'first_output_valid':state['first_output_valid'],'revisions':state['revisions'],
                        'first_action_valid':state['first_action_valid'],'first_candidate_valid':state['first_candidate_valid'],
                        'first_valid_output_seconds':state['first_valid_output_seconds'],
                        'revision_success':state['revision_success'],
                        'elapsed_seconds':time.monotonic()-begun}
    state['costs'] = _costs(state['model_results'],state['solver_results'])
    _write_json(run_dir/'agent_result.json',state)
    return state

def run_b(problem,run_dir,config=None):
    from src.fjsp.validator import validate
    begun = time.monotonic()
    prepared = _prepare(problem,run_dir,config,'B')
    if isinstance(prepared,dict):
        return prepared
    run_dir,config,model_cfg,state,max_calls,deadline = prepared
    header = (ROOT/'prompts/static_b.txt').read_text()
    compact=config.get('compact_state',False)
    problem_text = json.dumps(compact_problem(problem) if compact else observed_problem(problem),ensure_ascii=False,separators=(',',':'))
    schema = b_schema(sum(len(j['operations']) for j in problem['jobs']),compact)
    if compact:
        header=(ROOT/'prompts/static_b_compact.txt').read_text()
    feedback = None
    try:
        for i in range(max_calls):
            prompt = header+'\nProblem:\n'+problem_text
            if feedback is not None:
                prompt += '\nYour previous invalid decision and constraint feedback:\n'+json.dumps(feedback,ensure_ascii=False)
            output = _invoke(prompt,schema,run_dir,model_cfg,state,deadline)
            if output is None:
                break
            state['actions'].append(output)
            _write_json(run_dir/f'action_{i+1:03d}.json',output)
            try:
                if not isinstance(output,dict) or set(output) != {'order','rationale'} or not isinstance(output['rationale'],str):
                    raise ActionError('Expected exactly order and rationale')
                schedule = decode_order(problem,output['order'])
                validation = validate(problem,schedule)
                if not validation['valid']:
                    raise ActionError(json.dumps(validation['errors'],ensure_ascii=False))
                state.update(status='success',failure_type=None,schedule=schedule,validation=validation,
                             first_output_valid=i==0,first_action_valid=i==0,revisions=i,
                             first_valid_output_seconds=time.monotonic()-begun,revision_success=i>0)
                break
            except ActionError as exc:
                state.update(failure_type='invalid_direct_schedule',revisions=i)
                feedback = {'decision':output,'errors':[str(exc)]}
                _write_json(run_dir/f'feedback_{i+1:03d}.json',feedback)
    except BudgetExceeded as exc:
        state.update(failure_type='budget_exhausted',failure_details=str(exc))
    except TimeoutError as exc:
        state.update(status='timeout',failure_type='agent_wall_timeout',failure_details=str(exc))
    except Exception as exc:
        state.update(failure_type='runner_error',failure_details=f'{type(exc).__name__}: {exc}')
    return _finish(run_dir,state,begun)

def _check_c(output, remaining_seconds, remaining_solves, candidates):
    if not isinstance(output,dict) or set(output) != set(C_SCHEMA['required']) or not isinstance(output['rationale'],str):
        raise ActionError('Invalid C action fields')
    if output['action'] == 'finish':
        k = output['candidate_index']
        if any(output[x] is not None for x in ('time_limit','seed','search_branching','randomize_search')):
            raise ActionError('finish requires null solve fields')
        if type(k) is not int or not 0 <= k < len(candidates) or not candidates[k]['validation']['valid']:
            raise ActionError('finish must select an existing independently valid candidate')
        return
    if output['action'] != 'solve' or output['candidate_index'] is not None:
        raise ActionError('Expected solve with null candidate_index, or finish')
    if remaining_solves <= 0:
        raise ActionError('Solver call budget exhausted; finish a valid candidate')
    if type(output['time_limit']) not in (int,float) or not 0 < output['time_limit'] <= min(300,remaining_seconds):
        raise ActionError('time_limit must be positive and within remaining solver seconds')
    if type(output['seed']) is not int or not 0 <= output['seed'] <= 2147483647:
        raise ActionError('seed must be integer 0..2147483647')
    if output['search_branching'] not in ('AUTOMATIC_SEARCH','FIXED_SEARCH','PORTFOLIO_SEARCH') or type(output['randomize_search']) is not bool:
        raise ActionError('Invalid search parameters')

def run_c(problem,run_dir,config=None):
    from src.fjsp.validator import validate
    from src.fjsp.solver import solve
    begun = time.monotonic()
    prepared = _prepare(problem,run_dir,config,'C')
    if isinstance(prepared,dict):
        return prepared
    run_dir,config,model_cfg,state,max_calls,deadline = prepared
    total_budget = float(config.get('solver_budget_seconds',30))
    max_solves = config.get('max_solver_calls',2)
    if not 0 < total_budget <= 600 or type(max_solves) is not int or not 1 <= max_solves <= 6:
        raise ValueError('Invalid solver budgets')
    ledger = BudgetLedger(model_cfg.ledger_path)
    header = (ROOT/'prompts/static_c.txt').read_text()
    problem_text = json.dumps(compact_problem(problem) if config.get('compact_state',False) else observed_problem(problem),ensure_ascii=False,separators=(',',':'))
    feedback = []
    candidates = []
    consumed = 0.0
    try:
        for i in range(max_calls):
            limits = {'model_responses_including_this':max_calls-i,'solver_calls':max_solves-len(state['solver_results']),
                      'solver_seconds':total_budget-consumed,'wall_seconds':max(0,deadline-time.monotonic())}
            prompt = header+'\nProblem:\n'+problem_text+'\nRemaining limits:\n'+json.dumps(limits)+'\nThis run history:\n'+json.dumps(feedback,ensure_ascii=False)
            output = _invoke(prompt,C_SCHEMA,run_dir,model_cfg,state,deadline)
            if output is None:
                break
            state['actions'].append(output)
            _write_json(run_dir/f'action_{i+1:03d}.json',output)
            try:
                _check_c(output,total_budget-consumed,max_solves-len(state['solver_results']),candidates)
            except ActionError as exc:
                feedback.append({'decision':output,'error':str(exc)})
                state['failure_type'] = 'invalid_solver_action'
                state['revisions'] += 1
                continue
            if i == 0:
                state['first_action_valid'] = True
            if output['action'] == 'finish':
                k = output['candidate_index']
                state.update(status='success',failure_type=None,selected_candidate=k,
                             schedule=candidates[k]['result']['schedule'],validation=candidates[k]['validation'],
                             revision_success=state['revisions']>0)
                break
            requested = float(output['time_limit'])
            if requested > deadline-time.monotonic():
                raise TimeoutError('Requested solve exceeds remaining wall time')
            params = {k:output[k] for k in ('time_limit','seed','search_branching','randomize_search')}
            params['workers'] = 1
            sid = ledger.reserve_solver(phase=model_cfg.phase,run_id=str(run_dir),grant_id=config.get('solver_grant_id','unallocated'),
                                        requested_seconds=requested,metadata={'arm':'C','parameters':params})
            consumed += requested
            try:
                result = solve(problem,**params)
                validation = validate(problem,result['schedule']) if result.get('schedule') else {'valid':False,'errors':['Solver returned no schedule'],'makespan':None}
                entry = {'solver_call_id':sid,'requested_seconds':requested,'parameters':params,'result':result,'validation':validation}
                ledger.finish(sid,'success' if validation['valid'] else 'failed',{'wall_seconds':result.get('wall_seconds'),'solver_status':result.get('solver_status')})
            except Exception as exc:
                ledger.finish(sid,'failed',{'exception':f'{type(exc).__name__}: {exc}'})
                state['solver_results'].append({'solver_call_id':sid,'requested_seconds':requested,
                    'parameters':params,'result':{'wall_seconds':None,'exception':f'{type(exc).__name__}: {exc}'},
                    'validation':{'valid':False,'errors':['solver_exception'],'makespan':None}})
                raise
            state['solver_results'].append(entry)
            candidates.append(entry)
            if len(candidates) == 1:
                state['first_candidate_valid'] = bool(validation['valid'])
                state['first_output_valid'] = i == 0 and bool(validation['valid'])
            if validation['valid'] and state['first_valid_output_seconds'] is None:
                state['first_valid_output_seconds'] = time.monotonic()-begun
            _write_json(run_dir/f'solver_{len(candidates):03d}.json',entry)
            feedback.append({'decision':output,'candidate_index':len(candidates)-1,
                             'solver_status':result['solver_status'],'objective':result.get('objective'),
                             'best_bound':result.get('best_bound'),'wall_seconds':result.get('wall_seconds'),'validation':validation})
            _write_json(run_dir/f'feedback_{i+1:03d}.json',feedback[-1])
        if state['status'] != 'success' and state['failure_type'] is None:
            state['failure_type'] = 'missing_explicit_finish'
    except BudgetExceeded as exc:
        state.update(failure_type='budget_exhausted',failure_details=str(exc))
    except TimeoutError as exc:
        state.update(status='timeout',failure_type='agent_wall_timeout',failure_details=str(exc))
    except Exception as exc:
        state.update(failure_type='solver_or_runner_error',failure_details=f'{type(exc).__name__}: {exc}')
    return _finish(run_dir,state,begun)
