"""Public SMT2020 only. 非模型预热，仅机制验证; never sealed mixed_702.

Rule: ascending physical machine ID, first lexicographic lot-ID batch, ascending lot ID,
batch_min members, consuming lots once. Warmup dispatches at every physical event.
Expected dispatches use direct _dispatch/_events_to, never the v6 executor.
"""
import argparse
from copy import deepcopy
from pathlib import Path
import json
from harness_v6.env_adapter import FullFabEnvironment
from harness_v6.factory_v6 import capture, restore
from harness_v6.contracts import encode

LABEL = '非模型预热，仅机制验证'


def scripted_plan(env, version):
    used=set(); tasks=[]
    for mid in sorted(env.physical):
        groups=sorted(env._groups(mid), key=lambda g: tuple(g))
        for group in groups:
            group=[lid for lid in group if lid not in used]
            if not group: continue
            step=env._step(env.lots[group[0]])
            if len(group)<step.batch_min: continue
            ids=group[:step.batch_min]; used.update(ids)
            steps=[env.lots[lid]['step']+1 for lid in ids]
            visits=[env.lots[lid]['visits'][str(s)] for lid,s in zip(ids,steps)]
            tasks.append(dict(id=f'{version}-{mid}',machine=mid,lot_ids=ids,steps=steps,visits=visits,
                operation_ids=[f'{l}:{s}:{v}' for l,s,v in zip(ids,steps,visits)],start_mode='when_ready'))
            break
    return dict(version=str(version),created_at=env.t,freeze_until=env.t,valid_until=env.horizon,
                scope=sorted(env.physical),reason=LABEL,tasks=tasks,holds=[])


def direct_dispatch(env, plan):
    env.commit_plan(plan)
    for task in plan['tasks']:
        env.active_task=task
        env._dispatch(task['machine'],task['lot_ids'],'plan')
        env.active_task=None
        env.executed_tasks.add((plan['version'],task['id']))


def build(data_dir, output):
    env=FullFabEnvironment(data_dir=data_dir,window_seconds=10000)
    n=0
    while env.t<702:
        env._outside(); direct_dispatch(env,scripted_plan(env,f'w{n}'));n+=1
        env._events_to(min(702,env.q[0][0]))
    base=dict(state=capture(env),trace=deepcopy(env.trace))
    print('warmup',n,len(env.trace),flush=True)
    b=dict(data_dir=str(data_dir),label=LABEL,public_702=base,documented_public_physical_differences=[],
        mechanism_results={name:str(Path(output).resolve().parent/(name+'.json')) for name in ('p2','e1','hour')})
    # No aliases to sealed mixed_702 or d34_421.
    plan=scripted_plan(env,'ready')
    if not plan['tasks']:
        env._events_to(env.q[0][0]);base=dict(state=capture(env),trace=deepcopy(env.trace));plan=scripted_plan(env,'ready')
    expected=deepcopy(env);direct_dispatch(expected,plan)
    b['when_ready']={**base,'plan':plan,'until':env.t+0.01,'expected_dispatches':[e for e in expected.trace[len(base['trace']):] if e['kind']=='dispatch']}
    empty={**plan,'version':'empty','tasks':[]}
    b['advance_cycle']={**base,'plan':empty,'until':env.t+1,'expected_reason':'periodic_replan','expected_time':env.t+1}
    b['event_trigger']={**base,'plan':empty,'until':env.t+1,'expected_time':env.t}
    past=deepcopy(plan);past['version']='past'
    for t in past['tasks']:t['not_before']=env.t-1
    past['holds']=[dict(machine=plan['tasks'][0]['machine'],until=env.t-1,reason=LABEL)]
    b['public_time_semantics']={**base,'plan':past}
    frozen=deepcopy(env);old=deepcopy(plan);old['freeze_until']=env.t+10;frozen.commit_plan(old)
    for task in old['tasks']:frozen._emit('plan_invalidated',plan_version=old['version'],task_id=task['id'],reason='public fixture host invalidation')
    b['frozen_invalidated']=dict(state=capture(frozen),trace=frozen.trace,plan=empty,until=env.t+1)
    check=deepcopy(env);check.commit_plan(past);check.advance_cycle(env.t+1)
    b['v6_time_semantics_trace']=check.trace
    idle=deepcopy(env);idle.commit_plan(empty);start=len(idle.trace);idle.advance_cycle(env.t+1)
    b['v6_trace']=idle.trace[start:]
    # Independent physical greedy matching at the constant 1s interval (no events).
    reference=deepcopy(env);count=len(scripted_plan(reference,'oracle')['tasks'])
    assert not reference.q or reference.q[0][0]>env.t+1
    b['independent_idle_integrals']=dict(avoidable_idle=float(count),explicit_wait_idle=0.,reserved_but_earlier_startable=0.)
    Path(output).write_bytes(encode(b));print('fixture',output,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-dir',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();build(a.data_dir,a.output)
