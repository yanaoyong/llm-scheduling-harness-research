"""Bounded rolling immediate-dispatch CP-SAT, shared only by arms A/C.

Selects exact eligible lots and batch on each presently idle controlled machine.
It never plans from future releases, failure draws or other arms' outputs.
"""
from collections import defaultdict
import time
from ortools.sat.python import cp_model

def solve_action(state,time_limit=1.0,seed=11,priority_weight=100,waiting_weight=1,fill_weight=1000,setup_weight=1):
    if type(time_limit) not in (int,float) or not 0.05<=time_limit<=5:raise ValueError('time_limit must be 0.05..5 seconds')
    if type(seed) is not int or not 0<=seed<2**31:raise ValueError('seed must be nonnegative int32')
    for x in [priority_weight,waiting_weight,fill_weight,setup_weight]:
        if type(x) is not int or not 0<=x<=10000:raise ValueError('weights must be integers 0..10000')
    started=time.perf_counter();model=cp_model.CpModel();xs={};select={};rewards=[];all_lots=defaultdict(list)
    for m in state['machines']:
        groups=defaultdict(list)
        for c in m['candidates']:groups[tuple(c['batch_key'])].append(c)
        selected=[]
        for gi,cs in enumerate(groups.values()):
            if len(cs)<cs[0]['batch_min']:continue
            y=model.new_bool_var(f'm{m["machine"]}g{gi}');selected.append(y);terms=[]
            for c in cs:
                x=model.new_bool_var(f'm{m["machine"]}lot{c["lot"]}');xs[m['machine'],c['lot']]=x;terms.append(x);all_lots[c['lot']].append(x)
                # Fixed immediate horizon reward: lots selected, priority, queue age; setup penalized once/batch.
                score=fill_weight+priority_weight*int(c['priority'])+waiting_weight*int(c['waiting_seconds']/60)
                rewards.append(score*x)
            model.add(sum(terms)>=cs[0]['batch_min']*y);model.add(sum(terms)<=cs[0]['batch_max']*y)
            rewards.append(-setup_weight*int(cs[0]['setup_seconds']/60)*y)
        if selected:model.add(sum(selected)<=1)
    for vs in all_lots.values():model.add(sum(vs)<=1)
    model.maximize(sum(rewards));solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=time_limit;solver.parameters.num_search_workers=1;solver.parameters.random_seed=seed
    status=solver.solve(model);dispatches=[]
    if status in [cp_model.OPTIMAL,cp_model.FEASIBLE]:
        for m in state['machines']:
            ids=[lid for (mid,lid),x in xs.items() if mid==m['machine'] and solver.value(x)]
            if ids:dispatches.append({'machine':m['machine'],'lot_ids':sorted(ids)})
    if not dispatches and xs:raise RuntimeError('optimizer produced no dispatch despite legal candidate')
    return {'action':{'dispatches':dispatches,'wait_seconds':0 if dispatches else 900},'solver_status':solver.status_name(status),'objective':solver.objective_value if status in [cp_model.OPTIMAL,cp_model.FEASIBLE] else None,'best_bound':solver.best_objective_bound,'wall_seconds':time.perf_counter()-started,'parameters':{'time_limit':time_limit,'seed':seed,'priority_weight':priority_weight,'waiting_weight':waiting_weight,'fill_weight':fill_weight,'setup_weight':setup_weight},'model':'rolling-immediate-lot-batch-selection-v1','global_optimality_claim':False}
