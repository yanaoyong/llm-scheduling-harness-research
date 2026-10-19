"""Offline G0 representation comparison; configured SMT2020 evidence only."""
import argparse
import importlib.metadata
import json
from pathlib import Path
from harness_v6.compact import CURRENT, decode_snapshot, section, sections
from harness_v6.snapshot import production_prefix, current_state, build_snapshot, canonical, tiktoken_counter
from harness_v6.prompt_rules import V6_RULES
from harness_v6.mcp_server import TOOLS, TOOL_DESCRIPTIONS
from harness_v6.factory_v6 import restore
from harness_v6.ledger import ledger_from_scratch
from harness_v6.sealed_contexts import SQLiteContextReader


def measure(fixture, database):
    bundle = json.loads(Path(fixture).read_bytes())
    seed = bundle['mixed_702']
    env = restore(seed['state'], seed['trace'], data_dir=bundle['data_dir'])
    tools = [{'name': n, 'description': TOOL_DESCRIPTIONS[n], 'inputSchema': s} for n, s in TOOLS.items()]
    prefix_obj = dict(rules=V6_RULES, tools=tools, routing=env.manifest['routes'], machine_groups=env.manifest['machines'],setup_transitions=env.manifest['setups'],min_runs=dict(env.min_runs))
    prefix = production_prefix(routing=prefix_obj['routing'], machine_groups=prefix_obj['machine_groups'],setup_transitions=env.manifest['setups'],min_runs=dict(env.min_runs))
    for entry in SQLiteContextReader(database, 'SELECT group_name,payload FROM contexts').contexts():
        ctx = entry['context']
        if entry['group'] != 'G0' or abs(ctx['time'] - 1649.82) > .01:
            continue
        from harness_v6.physical_window import frozen_operations
        ctx['problem']=frozen_operations(ctx['problem'],env.manifest,running_jobs=bundle['g0_snapshot']['running_jobs'],dispatches=bundle['g0_trace'])
        dispatched = ctx['execution_state']['dispatched_task_ids']
        ledger = ledger_from_scratch(ctx['problem'], ctx['base_plan'],
            {'tasks': [dict(task_id=t, state='running') for t in dispatched]})
        args = dict(state_version=ctx['state_revision'], running_jobs=bundle['g0_snapshot']['running_jobs'],
                    last_cycle_receipt=None, model_notes='')
        current = current_state(ledger, horizon_seconds=900, **args)
        payload = build_snapshot(prefix, ledger, horizon_seconds=900, token_budget=10**9, **args)
        decoded_prefix, decoded_current = decode_snapshot(payload)
        # Exact normalized comparison plus type checks are exercised in configured tests.
        from harness_v6.compact import normalize
        assert normalize(prefix_obj) == decoded_prefix and normalize(current) == decoded_current
        counter = tiktoken_counter()
        static_sections = sections(prefix.decode().split('\n', 1)[1])
        dynamic_sections = sections(payload[len(prefix)+len(CURRENT):].decode())
        def new(names, values):
            return sum(counter(section(name, values[name])) for name in names)
        def old(value):
            return counter(canonical(value).decode())
        rows = {
            'routes': dict(old=old(prefix_obj['routing']), new=new(['routes','step_definitions','step_number_is_position'],static_sections)),
            'static_machines': dict(old=old(prefix_obj['machine_groups']),new=new(['machine_groups_compact'],static_sections)),
            'unreserved_ready': dict(old=old(current['unreserved_ready']),new=new(['ready_groups','eligible_sets'],dynamic_sections)),
            'upcoming_operations': dict(old=old(current['upcoming_operations']),new=new(['upcoming_operations'],dynamic_sections)),
            'machine_state': dict(old=old(current['machines']),new=new(['machines','machine_constants','machine_inheritance'],dynamic_sections)),
            'running_jobs': dict(old=old(current['running_jobs']),new=new(['running_jobs'],dynamic_sections)),
            'prefix': dict(old=old(prefix_obj),new=counter(prefix.decode())),
            'current': dict(old=old(current),new=counter(payload[len(prefix):].decode())),
            'total': dict(old=counter((canonical(prefix_obj)+b'\n'+canonical(current)).decode()),new=counter(payload.decode())),
        }
        dense_prefix = production_prefix(routing=prefix_obj['routing'],
                                     machine_groups=prefix_obj['machine_groups'], setup_transitions=env.manifest['setups'],min_runs=dict(env.min_runs),snapshot_format='dense', token_counter=counter)
        dense_payload = build_snapshot(dense_prefix, ledger, horizon_seconds=900, snapshot_format='dense', token_counter=counter, token_budget=10**9, **args)
        # Attribute shared eligible-set overhead by removing only this section.
        from harness_v6.compact import encode_current, decode_prefix
        without = dict(current)
        without.pop('upcoming_operations')
        incremental = {}
        for fmt, pref, full in [('explicit',prefix,payload),('dense',dense_prefix,dense_payload)]:
            baseline = pref + encode_current(decode_prefix(pref), without, snapshot_format=fmt, token_counter=counter)
            incremental[fmt] = counter(full.decode()) - counter(baseline.decode())
        dp, dc = decode_snapshot(dense_payload)
        assert dc == decoded_current
        assert all(dp[k] == decoded_prefix[k] for k in ('tools', 'routing', 'machine_groups'))
        from harness_v6.compact import dense_section
        ds = sections(dense_prefix.decode().split('\n',1)[1])
        dd = sections(dense_payload[len(dense_prefix)+len(CURRENT):].decode())
        groups = {'routes':['routes','step_definitions','step_number_is_position'],
                  'static_machines':['machine_groups_compact'], 'unreserved_ready':['ready_groups','eligible_sets'],
                  'upcoming_operations':['upcoming_operations'], 'machine_state':['machines','machine_constants','machine_inheritance'], 'running_jobs':['running_jobs']}
        used = set(sum(groups.values(), [])) | {'rules'}
        for name, names in groups.items():
            values = ds if name in ('routes','static_machines') else dd
            rows[name]['dense'] = sum(counter(dense_section(k, values[k], counter)) for k in names)
        rows['legend'] = dict(new=counter(section('rules', static_sections['rules'])),
                              dense=counter(dense_section('rules', ds['rules'], counter)))
        rows['rest'] = dict(new=sum(counter(section(k,val)) for values in (static_sections,dynamic_sections) for k,val in values.items() if k not in used),
                            dense=sum(counter(dense_section(k,val,counter)) for values in (ds,dd) for k,val in values.items() if k not in used))
        for name, raw in [('prefix',dense_prefix),('current',dense_payload[len(dense_prefix):]),('total',dense_payload)]:
            rows[name]['dense'] = counter(raw.decode())
        for row in rows.values():
            row['explicit'] = row.pop('new')
        due_cost = {}
        from harness_v6.snapshot import due_values
        due=due_values(ledger,current)
        for fmt,pref in [('explicit',prefix),('dense',dense_prefix)]:
            due_cost[fmt] = counter(encode_current(decode_prefix(pref),dict(current,lot_due=due),snapshot_format=fmt,token_counter=counter).decode()) - counter(encode_current(decode_prefix(pref),current,snapshot_format=fmt,token_counter=counter).decode())
        return dict(due_incremental_tokens=due_cost, context_ref=ctx['context_ref'],time=ctx['time'],tokenizer='o200k_base',
                    tiktoken_version=importlib.metadata.version('tiktoken'),tokens=rows, upcoming_incremental_tokens=incremental,
                    note='Old column is raw JSON with the same current rules/three tools; pre-L production total was 756359 (prefix 563837). Section token counts are standalone and need not sum exactly.',
                    counts=dict(pending_tasks=len(current['pending_tasks']),running_jobs=len(current['running_jobs']),
                                ready=len(current['unreserved_ready']),upcoming=len(current['upcoming_operations']),machines=len(current['machines']),
                                base_tasks=len(ctx['base_plan']['tasks'])))
    raise ValueError('G0 1649.82 absent')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture', required=True)
    parser.add_argument('--database', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = measure(args.fixture, args.database)
    args.output.write_bytes(canonical(result)+b'\n')
    print(json.dumps(result, indent=2, sort_keys=True))
