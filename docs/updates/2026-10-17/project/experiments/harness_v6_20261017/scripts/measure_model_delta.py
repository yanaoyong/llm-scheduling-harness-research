"""Offline o200k comparison: decision delta versus the previous redundant form."""
import argparse
import json
from copy import deepcopy
from harness_v6.contracts import encode
from harness_v6.delta_schema import model_task
from harness_v6.plan_delta import SCHEMA, ORDER_POLICY, anchor_hashes, compile_plan_delta
from harness_v6.synthetic import SyntheticFactory, scripted_delta, SOURCE
from harness_v6.snapshot import tiktoken_counter
from harness_v6.sealed_contexts import SQLiteContextReader


def measure(database):
    count = tiktoken_counter('o200k_base')
    factory = SyntheticFactory()
    delta = scripted_delta(factory, 1)
    compiled = compile_plan_delta(factory.plan, factory.problem(), factory.execution_state(), delta, source_sha256=SOURCE)['plan']
    old = deepcopy(delta)
    old.update(schema=SCHEMA, order_policy=ORDER_POLICY,
               anchors=anchor_hashes(factory.plan, factory.problem(), factory.execution_state(), source_sha256=SOURCE))
    old['plan_header'] = dict(version='v1', created_at=factory.now, scope=[1,2], **delta['plan_header'])
    old['tasks']['add'] = compiled['tasks']
    for name, mode in [('tasks','all_pending_except'), ('holds','all_except')]:
        old[name]['keep'] = dict(mode=mode, ids=[])
    rows = {}
    def record(name, before, after):
        rows[name] = dict(old_tokens=count(encode(before).decode()), new_tokens=count(encode(after).decode()),
                          old_bytes=len(encode(before)),new_bytes=len(encode(after)))
    record('scripted_delta', old, delta)
    for entry in SQLiteContextReader(database, 'SELECT group_name,payload FROM contexts').contexts():
        ctx = entry['context']
        if entry['group'] != 'G0' or abs(ctx['time'] - 1649.82) > .01: continue
        plan = ctx['base_plan']
        # Entire G0 base expressed as additions, for a controlled size comparison.
        new = dict(plan_header={k:plan[k] for k in ('valid_until','freeze_until','reason')},
                   tasks=dict(cancel_ids=[],replace=[],add=[model_task(t) for t in plan['tasks']]),
                   holds=dict(cancel_ids=[],replace=[],add=plan['holds']),
                   machine_orders=[dict(machine=m,task_ids=[t['id'] for t in plan['tasks'] if t['machine']==m])
                                   for m in sorted({t['machine'] for t in plan['tasks']})])
        old = deepcopy(new)
        old.update(schema=SCHEMA,order_policy=ORDER_POLICY,
                   anchors=anchor_hashes(plan,ctx['problem'],ctx['execution_state'],source_sha256=SOURCE))
        old['plan_header'] = {k:v for k,v in plan.items() if k not in ('tasks','holds')}
        old['tasks']['add'] = plan['tasks']
        for name, mode in [('tasks','all_pending_except'),('holds','all_except')]:
            old[name]['keep'] = dict(mode=mode,ids=[])
        record('g0_base_as_delta',old,new)
        rows['g0_context'] = dict(time=ctx['time'],tasks=len(plan['tasks']))
        return rows
    raise ValueError('G0 1649.82 context missing')


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--database',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();result=measure(args.database)
    from pathlib import Path
    Path(args.output).write_bytes(encode(result))
    print(json.dumps(result,indent=2))
