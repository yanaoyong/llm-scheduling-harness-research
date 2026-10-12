"""Evaluated B/C runtime. The only decision inputs are a whitelisted problem,
the current arm's own choices/feedback and shared tool specifications.
"""
from __future__ import annotations
import argparse
import dataclasses
import json
import math
import os
from pathlib import Path
import time
import traceback

from .budget import ROOT,APPROVAL,DEFAULT_LEDGER,BudgetLedger
from .model_transport import ModelConfig,call_model
from .environment import FullFabEnvironment,write_new,digest
from .interface import compact_pages,validate_choices,decode_plan
from .runner import source_snapshot,crop_plan
from .audit import audit_trace

C_CONSTRUCTIVE_VERSION='fullfab-C-explicit-constructive-v1'
CONSTRUCTOR_SECONDS_CAP=5.0
CONSTRUCTOR_EVALUATION_CAP=250000

B_SCHEMA={'type':'object','properties':{
    'tasks':{'type':'array','items':{'type':'object','properties':{
        'machine':{'type':'integer'},'operations':{'type':'array','items':{'type':'string'}},
        'start':{'type':'number'},'sequence':{'type':'integer'}},'required':['machine','operations','start','sequence'],'additionalProperties':False}},
    'holds':{'type':'array','items':{'type':'object','properties':{'machine':{'type':'integer'},'until':{'type':'number'},'reason':{'type':'string'},'after_sequence':{'type':['integer','null']}},'required':['machine','until','reason','after_sequence'],'additionalProperties':False}},
    'commit':{'type':'boolean'},'reason':{'type':'string'}},
    'required':['tasks','holds','commit','reason'],'additionalProperties':False}
C_SCHEMA={'type':'object','properties':{
    'action':{'type':'string','enum':['read_page','solve','apply']},'index':{'type':['integer','null']},
    'method':{'type':['string','null'],'enum':['global','decomposed',None]},
    'seconds':{'type':['number','null']},'seed':{'type':['integer','null']},
    'slots':{'type':['integer','null']},
    'weights':{'type':'object','properties':{k:{'type':'integer'} for k in ['completion','flow','tardiness','setup']},'required':['completion','flow','tardiness','setup'],'additionalProperties':False},
    'reason':{'type':'string'}},'required':['action','index','method','seconds','seed','slots','weights','reason'],'additionalProperties':False}
C_CONSTRUCTIVE_SCHEMA={**C_SCHEMA,'properties':{**C_SCHEMA['properties'],
    'method':{'type':['string','null'],'enum':['global','decomposed','constructive',None]}}}
BASE='''You are responsible for ALL 913 production machines in a semiconductor simulation.
Minimize priority weighted integral of overdue unfinished lots over the observation window; also preserve throughput and avoid WIP growth.
All production starts require your explicit submitted plan. No default policy fills omissions.
Times are seconds. Route successors are conditional nominal expectations; actual sampling/rework or disruption triggers revision.
Do not use native tools, external sources, shells or other runs. All choices are JSON data for this runner.
Current machine state and operation expectations are paged without quality filtering. Raw priority10/20/30 has evaluation weight1/2/3.
Compact v2 preserves the full observation. Read extras.values as additional fields, extras.absent as absent fields, and source_index as original array order.
The eligible_override string all_family_machines means every machine in that family; any other value is explicit eligibility.
Unknown future random outcomes are not available. A submitted task identifies exact operation IDs, machine, and start condition.
Tasks may finish after the observation endpoint, but only starts before it execute. Already started work cannot be revised.
'''


def append_record(path,row):
    with Path(path).open('a') as f:
        f.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
        f.flush();os.fsync(f.fileno())


def validate_solver_request(response,remaining):
    if response['method'] not in ('global','decomposed') or response['index'] is not None:
        raise ValueError('solve requires a whitelisted method and null candidate index')
    if type(response['seconds']) not in (int,float) or not math.isfinite(response['seconds']) or not 0.05<=response['seconds']<=min(60,remaining):
        raise ValueError('invalid cumulative solve budget')
    validate_plan_parameters(response)


def validate_plan_parameters(response):
    if type(response['seed']) is not int or not 0<=response['seed']<=2147483647:
        raise ValueError('invalid solver seed')
    if type(response['slots']) is not int or not 1<=response['slots']<=8:
        raise ValueError('invalid solver slot bound')
    weights=response['weights']
    if not isinstance(weights,dict) or set(weights)!={'completion','flow','tardiness','setup'} or not any(weights.values()) or any(type(v)is not int or not 0<=v<=100000 for v in weights.values()):
        raise ValueError('invalid solver weights')


def validate_constructor_request(response,remaining):
    if response['method']!='constructive' or response['index'] is not None:
        raise ValueError('constructive solve requires its explicit method and null candidate index')
    if type(response['seconds']) not in (int,float) or not math.isfinite(response['seconds']) or not 0<response['seconds']<=min(CONSTRUCTOR_SECONDS_CAP,remaining):
        raise ValueError('invalid construction request budget')
    validate_plan_parameters(response)


def write_constructor_result(path,value):
    """An actual result marker is durable before its ledger completion."""
    if path.exists():raise FileExistsError('constructor result already exists; never repeat a completed attempt')
    temporary=path.with_name(path.name+'.tmp')
    write_new(temporary,value)
    with temporary.open('rb') as handle:os.fsync(handle.fileno())
    temporary.replace(path)
    directory=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(directory)
    finally:os.close(directory)


def candidate_feedback(result,index,*,strict_nominal=False):
    plan=result.get('plan')
    valid=result.get('solver_status') in ('OPTIMAL','FEASIBLE','FEASIBLE_HEURISTIC') and isinstance(plan,dict)
    nominal=result.get('nominal_audit')
    if strict_nominal:valid=valid and isinstance(nominal,dict) and nominal.get('valid') is True
    tasks=plan.get('tasks',[]) if isinstance(plan,dict) else []
    feedback={k:result.get(k) for k in ('solver_status','objective','best_bound','planned_operations','wall_seconds','limitations','global_optimality_claim','selected_source','cp_sat','decomposition_status','heuristic_families')}
    feedback.update(candidate_index=index,valid_candidate=valid,task_count=len(tasks),
                    plan_sha256=digest(plan) if isinstance(plan,dict) else None,
                    unplanned_operations_count=len(result.get('unplanned_operations',{})),tasks_preview=tasks[:12])
    return valid,feedback
B_PROMPT=BASE+'''You directly choose exact lot operations, machines, order, compatible batches, and explicit waiting.
Read the compact row-field schema and extra-field dictionaries carefully, including conditional paths, sampling, uncertain qualification and frozen commitments.
This is a sequence of state pages in stable family order. Each operation appears on exactly one page; no preferred candidates are selected for you.
Return a plan patch for THIS page. Choose sequence integers defining the intended order on each machine across your patches.
The runner only orders by your explicit sequence numbers, checks choices and calculates no priority or optimization.
Use distinct sequence values on each machine. A machine appears only in its family's page, except an oversized family may span pages.
Operations not chosen remain unplanned. On the final page set commit=true only to explicitly apply the entire collection of your patches.
Before the final page use commit=false. An omitted idle machine with legal demand triggers another request; no automatic fallback.
You may plan conditional future steps. Respect predecessor completion, setup/minrun, availability, exact batches and eligibility.
For a hold after the end of your chosen machine sequence, set after_sequence to its last task sequence; null means hold immediately.
Provide exact explicit holds only when you intend to wait, bounded by observation_end. Do not invent a heuristic or rule selector.
'''
C_PROMPT=BASE+'''You choose shared CP-SAT rolling optimization actions, inspect the actual result, then explicitly apply a candidate.
Allowed actions: read_page(index) to inspect current data; solve(method,seconds,seed,slots,weights); apply(index) to commit a saved candidate.
Global method models cross-family precedence and machine batch slots. Decomposed method propagates explicit predecessor completion between per-family subproblems.
Neither method claims full-fab global optimality. Weights control operation progress, flow, predicted tardiness and setup surrogate.
Choose seconds within remaining cumulative budget (at most60 per request), seed0..2147483647,slots1..8, nonnegative integer weights0..100000.
Inspect solver status, validation, unplanned work and plan summary. You may request another solve; reserve a response to apply.
No candidate is automatically applied. Use null index for solve; non-solve parameter fields may be null; weights are ignored outside solve.
'''
C_CONSTRUCTIVE_PROMPT=BASE+'''You explicitly choose shared planning tools, inspect each candidate, then explicitly apply a candidate.
Allowed actions: read_page(index); solve(method,seconds,seed,slots,weights); apply(index).
Methods global and decomposed use the shared CP-SAT tools. Their seconds consume the remaining cumulative CP request budget, at most60 per request.
Method constructive directly uses the same full-factory gain-rate multi-step constructor as A event plans, including cross-family precedence, batches and nominal validation.
For constructive, seconds is a soft construction wall budget, at most5 per request, with a fixed250000 candidate-evaluation cap. Preprocessing and validation may exceed that soft cap; actual construction wall is charged separately. CP requests and CP calls are zero.
The constructive seed is recorded but not used by its deterministic algorithm. Wall-clock truncation can change the candidate prefix.
All methods accept seed0..2147483647,slots1..8,nonnegative integer weights0..100000 with at least one positive weight. A hybrid event's total slots default to8.
Zero CP balance forbids CP solves; constructive,read_page and explicit apply remain available within wall/log limits.
No method claims full-fab global optimality. Inspect status, nominal validation, unplanned work and source. Failed attempts retain an invalid candidate index; they cannot be applied.
No candidate is automatically applied. Use null index for solve; non-solve parameter fields may be null; weights are ignored outside solve.
You may explicitly choose another action after a constructor failure. The runner never substitutes another algorithm or fills missing production choices.
'''


def run(arm,run_id,*,seconds=3600,max_calls=None,solver_method='decomposed',
        scenario=1701,solver_budget_seconds=60,wall_seconds=7200,max_log_bytes=1073741824,page_chars=45000,
        enable_constructive=False):
    run_started=time.monotonic()
    approval=json.loads(APPROVAL.read_text())
    ledger=BudgetLedger()
    research_waiver=ledger.research_limit_waiver()
    if type(enable_constructive)is not bool or (enable_constructive and (arm!='C' or not research_waiver)):
        raise ValueError('constructive capability requires an explicit registered research C run')
    waiver=research_waiver or ledger.scoped_limit_waiver(arm)
    if max_calls is None and not waiver:max_calls=approval['allocation'][arm]
    allowed_windows=research_waiver['allowed_stage2_window_seconds'] if research_waiver else [approval['window_seconds']]
    if seconds not in allowed_windows or (not research_waiver and scenario!=approval['scenario']) or (max_calls is not None and (type(max_calls)is not int or max_calls<1 or (not waiver and max_calls>approval['allocation'][arm]))):
        raise ValueError('run exceeds approved arm/window scope')
    if type(page_chars)is not int or not 10000<=page_chars<=90000:
        raise ValueError('page_chars must be between 10000 and 90000')
    if not research_waiver:
        wall_seconds=approval['total_active_wall_seconds']
        max_log_bytes=approval['max_log_bytes']
        solver_budget_seconds=approval['max_solver_requested_seconds_per_arm']
    cfg={'arm':arm,'run_id':run_id,'seconds':seconds,'max_calls':max_calls,'solver_method_available':solver_method,
         'plan_seconds':14400,'lookahead_depth':2,'period_seconds':1800,'budget_id':approval['budget_id'],
         'amendment_id':waiver['amendment_id'] if waiver else None,
         'seed':scenario,'solver_budget_seconds':solver_budget_seconds,'wall_seconds':wall_seconds,
         'max_log_bytes':max_log_bytes,'page_chars':page_chars}
    if enable_constructive:
        cfg.update(enable_constructive=True,controller_version=C_CONSTRUCTIVE_VERSION,
                   constructor_seconds_cap=CONSTRUCTOR_SECONDS_CAP,constructor_evaluation_cap=CONSTRUCTOR_EVALUATION_CAP)
    out=ROOT/'runs/smt_fullfab_stage2'/run_id
    if not run_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in run_id):raise ValueError('invalid run_id')
    identity=digest(cfg)
    if out.exists():
        if (out/'result.json').exists():
            old=json.loads((out/'result.json').read_text())
            if old['identity']==identity:print('SKIP',run_id,old['status']);return old
        raise FileExistsError('claimed run preserved; never re-call automatically')
    registration=None
    if research_waiver:
        registration=ledger.register_stage_run(run_id=str(out),arm=arm,scenario=scenario,window_seconds=seconds,
            solver_seconds=solver_budget_seconds if arm=='C' else 0,wall_seconds=wall_seconds,max_log_bytes=max_log_bytes)
    out.mkdir(parents=True);write_new(out/'config.json',cfg);write_new(out/'claim.json',{'pid':os.getpid(),'identity':identity})
    write_new(out/'provenance.json',source_snapshot(out))
    if registration:write_new(out/'resource_registration.json',registration)
    mcfg=ModelConfig(model=approval['model'],reasoning_effort=approval['reasoning_effort'],timeout_seconds=approval['per_call_timeout_seconds'],
                     ledger_path=str(DEFAULT_LEDGER),phase='stage2_research' if research_waiver else 'stage2_probe',grant_id=approval['budget_id'],
                     authorization_context={'purpose':arm,'arm':arm,'window_seconds':seconds,'scenario':scenario})
    env=FullFabEnvironment(seed=scenario,window_seconds=seconds,trace_path=out/'trace.jsonl')
    models=[];solvers=[];constructors=[];plan_count=0;started=run_started if enable_constructive else time.monotonic();failure=None;audit=None;status='failed'

    def solver_remaining():
        return ledger.solver_remaining_seconds('C',run_id=str(out) if registration else None)

    def model_time_remaining():
        if enable_constructive:return ledger.constructor_remaining_seconds('C',run_id=str(out))
        account=ledger.summary(run_id=str(out)) if registration else ledger.summary()
        return wall_seconds-account['model_active_seconds']

    def check_resources():
        if time.monotonic()-started>=wall_seconds:raise TimeoutError('active run wall limit')
        if sum(p.stat().st_size for p in out.rglob('*') if p.is_file())>=max_log_bytes:
            raise RuntimeError('log byte cap')

    def invoke(prompt,schema,*,stage,page_index=None):
        if max_calls is not None and len(models)>=max_calls:raise RuntimeError('per-arm attempt limit')
        if time.monotonic()-started>=wall_seconds:raise TimeoutError('active run wall limit')
        remaining_time=min(model_time_remaining(),wall_seconds-(time.monotonic()-started))
        if remaining_time<1:raise TimeoutError('cumulative model activity budget exhausted')
        total_bytes=sum(p.stat().st_size for p in out.rglob('*') if p.is_file())
        if total_bytes>=max_log_bytes:raise RuntimeError('log byte cap')
        current_config=dataclasses.replace(mcfg,timeout_seconds=min(mcfg.timeout_seconds,remaining_time))
        r=call_model(prompt,schema,out/f'model_{len(models):03d}',current_config)
        models.append(r)
        append_record(out/'controller_decisions.jsonl',{'model_index':len(models)-1,'call_id':r['call_id'],
                      'plan_index':plan_count,'arm':arm,'stage':stage,'page_index':page_index,
                      'input_problem_sha256':digest(problem),'response_sha256':digest(r['output']),'status':r['status']})
        if r['status']!='success':raise RuntimeError('model_channel:'+str(r['failure_reason']))
        return r['output']

    try:
        while not env.finished:
            if arm=='C' and not enable_constructive and solver_remaining()<0.05:
                raise RuntimeError('C cumulative solver budget exhausted')
            problem=env.problem(plan_seconds=cfg['plan_seconds'],lookahead_depth=cfg['lookahead_depth'])
            write_new(out/f'problem_{plan_count:03d}.json',problem)
            compact=compact_pages(problem,max_chars=page_chars)
            pages=compact.pop('pages');compact['page_count']=len(pages);compact['observation_end']=env.horizon
            write_new(out/f'page_manifest_{plan_count:03d}.json',compact)
            for i,page in enumerate(pages):write_new(out/f'page_{plan_count:03d}_{i:02d}.json',page)
            if arm=='B':
                staged=[];holds=[];reason='';commit=False
                for i,page in enumerate(pages):
                    metadata={**compact,'page_index':i,'last_page':i==len(pages)-1,'remaining_model_responses':None if max_calls is None else max_calls-len(models)}
                    # Prior user-chosen assignments needed for this page's predecessors
                    # are returned as exact identities, without best-candidate filtering.
                    predecessors={x for g in page for row in g['operations'] for x in row[3]}
                    page_machines={m[0] for g in page for m in g['machines']}
                    own_prior=[t for t in staged if t['machine'] in page_machines or any(x in predecessors for x in t['operations'])]
                    prompt=B_PROMPT+'\nSCHEMA_AND_LIMITS\n'+json.dumps(metadata,separators=(',',':'))+'\nPAGE\n'+json.dumps(page,separators=(',',':'))+'\nYOUR_PRIOR_PREDECESSOR_CHOICES\n'+json.dumps(own_prior,separators=(',',':'))
                    response=invoke(prompt,B_SCHEMA,stage='B_page',page_index=i)
                    allowed={r[0] for g in page for r in g['operations']}
                    if any(oid not in allowed for t in response['tasks'] for oid in t['operations']):raise ValueError('B patch references an operation outside its supplied page')
                    staged.extend(response['tasks']);holds.extend(response['holds']);reason=response['reason'];commit=response['commit']
                    validate_choices(problem,staged)
                    write_new(out/f'patch_{plan_count:03d}_{i:02d}.json',response)
                    if commit and i!=len(pages)-1:raise ValueError('explicit commit before all full-fab pages observed')
                if not commit:raise RuntimeError('missing B explicit commit')
                ordering=[(t['machine'],t['sequence']) for t in staged]
                if len(ordering)!=len(set(ordering)):raise ValueError('B repeated explicit machine sequence')
                # Ordering is entirely provided by B; no heuristic chooses order.
                staged.sort(key=lambda t:(t['machine'],t['sequence']))
                plan=decode_plan(problem,{'tasks':staged,'holds':holds,'reason':reason},version=run_id+':'+str(plan_count))
            else:
                history=[];candidates=[];plan=None
                summary={'time':problem['time'],'horizon_end':problem['horizon_end'],'observation_end':env.horizon,
                         'problem_metadata':compact['problem_metadata'],
                         'machines':len(problem['machines']),'operations':len(problem['operations']),
                         'pages':len(pages),'family_counts':[{ 'family':g['family'],'machines':len(g['machines']),'operations':len(g['operations'])} for page in pages for g in page],
                         'methods_available':['global',solver_method]+(['constructive'] if enable_constructive else [])}
                while plan is None:
                    remaining=solver_remaining()
                    limits={'responses':None if max_calls is None else max_calls-len(models),'solver_seconds':remaining,
                            'model_active_seconds_remaining':model_time_remaining(),'per_request_solver_seconds':min(60,remaining)}
                    if enable_constructive:
                        account=ledger.summary(run_id=str(out))
                        limits.update(per_request_constructor_seconds=min(CONSTRUCTOR_SECONDS_CAP,max(0,model_time_remaining())),
                                      constructor_requested_seconds=account.get('constructor_requested_seconds',0),
                                      constructor_active_seconds=account.get('constructor_active_seconds',0),
                                      constructor_evaluation_cap=CONSTRUCTOR_EVALUATION_CAP)
                    response=invoke((C_CONSTRUCTIVE_PROMPT if enable_constructive else C_PROMPT)+'\nSTATE_DIRECTORY\n'+json.dumps(summary,separators=(',',':'))+'\nOWN_HISTORY\n'+json.dumps(history,separators=(',',':'))+'\nLIMITS\n'+json.dumps(limits),
                                    C_CONSTRUCTIVE_SCHEMA if enable_constructive else C_SCHEMA,stage='C_action')
                    if response['action']=='read_page':
                        i=response['index']
                        if type(i)is not int or not 0<=i<len(pages):raise ValueError('invalid page')
                        history.append({'decision':response,'page':pages[i],'schema':compact})
                    elif response['action']=='solve':
                        if response['method']=='constructive':
                            if not enable_constructive:raise ValueError('constructive method is not enabled for this run')
                            validate_constructor_request(response,min(model_time_remaining(),wall_seconds-(time.monotonic()-started)))
                            from .constructive_tool import solve_constructive_plan
                            request=response['seconds'];constructor_index=len(constructors)
                            params=dict(time_limit_seconds=request,seed=response['seed'],weights=response['weights'],
                                        max_slots_per_machine=response['slots'],plan_version=run_id+':'+str(plan_count))
                            metadata={'model_call_id':models[-1]['call_id'],'model_index':len(models)-1,'plan_index':plan_count,
                                      'problem_sha256':digest(problem),'max_candidate_evaluations':CONSTRUCTOR_EVALUATION_CAP,
                                      'max_slots_per_machine':response['slots'],'method':'constructive',
                                      'actual_constructor_module':'src.smt_fullfab.constructive_tool',
                                      'actual_constructor_function':'solve_constructive_plan'}
                            cid=ledger.reserve_constructor(arm=arm,run_id=str(out),requested_seconds=request,metadata=metadata)
                            evidence={**metadata,'constructor_index':constructor_index,'constructor_call_id':cid,
                                      'call_id':models[-1]['call_id'],'requested_seconds':request}
                            write_new(out/f'constructor_request_{constructor_index:03d}.json',{'response':response,'parameters':params,**evidence})
                            entry={'requested_seconds':request};constructors.append(entry)
                            constructor_started=time.monotonic()
                            outcome='success'
                            try:
                                constructed=solve_constructive_plan(problem,**params)
                            except Exception as exc:
                                outcome='failed'
                                constructed={'record_type':'constructor_exception','solver_status':'CONSTRUCTOR_EXCEPTION',
                                             'plan':None,'tasks':[],'unplanned_operations':{o['operation_id']:'constructor_exception' for o in problem['operations']},
                                             'error':f'{type(exc).__name__}: {exc}','nominal_audit':None,
                                             'best_bound':None,'global_optimality_claim':False,
                                             'cp_sat':{'status':'NOT_RUN_BY_POLICY','calls':0,'requested_seconds':0},
                                             'classical_construction_wall_seconds':None}
                            duration=time.monotonic()-constructor_started
                            constructed.update(requested_method='constructive',constructor_call_id=cid,
                                               invocation_duration_seconds=duration)
                            entry.update(duration_seconds=duration,result=constructed)
                            write_constructor_result(out/f'constructor_{constructor_index+1:03d}.json',constructed)
                            result_hash=digest(constructed)
                            ledger.finish_constructor(cid,outcome,{'duration_seconds':duration,'solver_status':constructed['solver_status'],
                                                                  'constructor_result_sha256':result_hash})
                            append_record(out/'constructor_evidence.jsonl',{**evidence,'status':outcome,'duration_seconds':duration,
                                                                         'constructor_result_sha256':result_hash})
                            valid,feedback=candidate_feedback(constructed,len(candidates),strict_nominal=True)
                            candidates.append(constructed if valid else None)
                            feedback.update(method='constructive',constructor_index=constructor_index,constructor_call_id=cid,
                                            constructor_requested_seconds=request,constructor_duration_seconds=duration,
                                            classical_construction_wall_seconds=constructed.get('classical_construction_wall_seconds'),
                                            nominal_audit=constructed.get('nominal_audit'),seed_semantics=constructed.get('seed_semantics'),
                                            error=constructed.get('error'))
                            history.append({'decision':response,'result':feedback})
                            append_record(out/'controller_history_events.jsonl',{'plan_index':plan_count,'model_index':len(models)-1,'entry':history[-1]})
                            continue
                        validate_solver_request(response,min(remaining,model_time_remaining(),wall_seconds-(time.monotonic()-started)) if enable_constructive else remaining)
                        request=response['seconds']
                        params=dict(time_limit_seconds=request,seed=response['seed'],weights=response['weights'],max_slots_per_machine=response['slots'],plan_version=run_id+':'+str(plan_count))
                        if response['method']=='global':
                            from .optimizer import solve_plan
                            module,function='src.smt_fullfab.optimizer','solve_plan'
                        elif response['method']=='decomposed':
                            from .decomposition import solve_decomposed_plan as solve_plan
                            module,function='src.smt_fullfab.decomposition','solve_decomposed_plan'
                        solver_id=BudgetLedger().reserve_solver(arm=arm,run_id=str(out),requested_seconds=request)
                        evidence={'solver_index':len(solvers),'solver_call_id':solver_id,'model_index':len(models)-1,
                                  'call_id':models[-1]['call_id'],'plan_index':plan_count,'requested_seconds':request,
                                  'method':response['method'],'actual_solver_module':module,'actual_solver_function':function}
                        write_new(out/f'solver_request_{len(solvers):03d}.json',{'response':response,'parameters':params,'problem_sha256':digest(problem),**evidence})
                        entry={'requested_seconds':request};solvers.append(entry)
                        solve_started=time.monotonic()
                        try:
                            result=solve_plan(problem,**params)
                        except Exception as exc:
                            failed={'error':str(exc),'duration_seconds':time.monotonic()-solve_started}
                            BudgetLedger().finish_solver(solver_id,'failed',failed)
                            append_record(out/'solver_evidence.jsonl',{**evidence,'status':'failed','solver_result_sha256':None,**failed})
                            raise
                        result['requested_method']=response['method']
                        BudgetLedger().finish_solver(solver_id,'success',{'solver_status':result['solver_status'],'wall_seconds':result['wall_seconds']})
                        append_record(out/'solver_evidence.jsonl',{**evidence,'status':'success','solver_result_sha256':digest(result)})
                        entry.update(result);write_new(out/f'solver_{len(solvers):03d}.json',result)
                        # CP result contracts predate constructive nominal_audit;
                        # retain their existing status/plan acceptance semantics.
                        valid,feedback=candidate_feedback(result,len(candidates))
                        candidates.append(result if valid else None)
                        history.append({'decision':response,'result':feedback})
                    elif response['action']=='apply':
                        i=response['index']
                        if type(i)is not int or not 0<=i<len(candidates) or candidates[i] is None:raise ValueError('invalid explicit candidate apply')
                        plan=candidates[i]['plan']
                        history.append({'decision':response,'applied_candidate':i,'plan_sha256':digest(plan)})
                    else:raise ValueError('unknown C action')
                    if enable_constructive:
                        append_record(out/'controller_history_events.jsonl',{'plan_index':plan_count,'model_index':len(models)-1,'entry':history[-1]})
                write_new(out/f'controller_history_{plan_count:03d}.json',history)
            if enable_constructive:check_resources()
            write_new(out/f'raw_plan_{plan_count:03d}.json',plan)
            committed=crop_plan(plan,env)
            env.commit_plan(committed)
            append_record(out/'plan_commits.jsonl',{'plan_index':plan_count,'model_call_id':models[-1]['call_id'],
                           'raw_plan_sha256':digest(plan),'committed_plan_sha256':digest(committed)})
            plan_count+=1
            env.advance_plan(min(env.horizon,env.t+cfg['period_seconds']))
        audit=audit_trace(out/'trace.jsonl',verify_data_dir=env.data_dir)
        write_new(out/'audit.json',audit)
        if enable_constructive:check_resources()
        status='success' if audit['valid'] else 'failed'
        if not audit['valid']:failure='independent_audit_failed'
    except Exception as exc:
        failure=f'{type(exc).__name__}: {exc}';(out/'exception.txt').write_text(traceback.format_exc())
    env.snapshot(out/'checkpoint.json')
    result={'identity':identity,'config':cfg,'status':status,'failure':failure,'plans_committed':plan_count,
            'simulation_seconds':env.t,'full_window_completed':env.finished,'model_calls':len(models),
            'model_call_ids':[x['call_id'] for x in models],'solver_calls':len(solvers),
            'solver_requested_seconds':sum(s['requested_seconds'] for s in solvers),
            'wall_seconds':time.monotonic()-started,'audit_valid':bool(audit and audit['valid']),
            'metrics':audit['metrics'] if audit else None,'cost_usd':None,'formal':False}
    if enable_constructive:
        result.update(constructor_calls=len(constructors),
                      constructor_requested_seconds=sum(entry['requested_seconds'] for entry in constructors),
                      constructor_active_seconds=sum(entry.get('duration_seconds',0) for entry in constructors),
                      constructor_inner_wall_seconds=[entry.get('result',{}).get('classical_construction_wall_seconds') for entry in constructors],
                      controller_version=C_CONSTRUCTIVE_VERSION)
        # Terminal checkpoint/result evidence is part of the same run cap.
        # Preserve it on an overrun, but never label that run successful.
        existing_bytes=sum(p.stat().st_size for p in out.rglob('*') if p.is_file())
        result.update(resource_overrun=False,log_bytes_including_result=0)
        for _ in range(10):
            total=existing_bytes+len((json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n').encode('utf-8'))
            overrun=result['wall_seconds']>wall_seconds or total>max_log_bytes
            if result['log_bytes_including_result']==total and result['resource_overrun']==overrun:break
            result.update(log_bytes_including_result=total,resource_overrun=overrun)
            if overrun:
                result.update(status='failed',failure=result['failure'] or 'terminal_resource_limit')
    write_new(out/'result.json',result);print(json.dumps(result,ensure_ascii=False),flush=True)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--arm',choices=['B','C'],required=True);p.add_argument('--run-id',required=True)
    p.add_argument('--seconds',type=int,default=3600);p.add_argument('--max-calls',type=int)
    p.add_argument('--scenario',type=int,default=1701);p.add_argument('--solver-budget-seconds',type=float,default=60)
    p.add_argument('--wall-seconds',type=float,default=7200);p.add_argument('--max-log-bytes',type=int,default=1073741824)
    p.add_argument('--page-chars',type=int,default=45000)
    p.add_argument('--enable-constructive',action='store_true')
    a=p.parse_args();raise SystemExit(0 if run(**vars(a))['status']=='success' else 1)
