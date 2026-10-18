"""Offline G0 representation comparison; configured SMT2020 evidence only."""
import argparse
import importlib.metadata
import json
from pathlib import Path
from harness_v6.compact import CURRENT, decode_snapshot, section, sections
from harness_v6.snapshot import stable_prefix, current_state, build_snapshot, canonical, tiktoken_counter
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
    prefix_obj = dict(rules=V6_RULES, tools=tools, routing=env.manifest['routes'], machine_groups=env.manifest['machines'])
    prefix = stable_prefix(tool_descriptions=tools, routing=prefix_obj['routing'], machine_groups=prefix_obj['machine_groups'])
    for entry in SQLiteContextReader(database, 'SELECT group_name,payload FROM contexts').contexts():
        ctx = entry['context']
        if entry['group'] != 'G0' or abs(ctx['time'] - 1649.82) > .01:
            continue
        dispatched = ctx['execution_state']['dispatched_task_ids']
        ledger = ledger_from_scratch(ctx['problem'], ctx['base_plan'],
            {'tasks': [dict(task_id=t, state='running') for t in dispatched]})
        args = dict(state_version=ctx['state_revision'], running_jobs=bundle['g0_snapshot']['running_jobs'],
                    last_cycle_receipt=None, model_notes='')
        current = current_state(ledger, **args)
        payload = build_snapshot(prefix, ledger, token_budget=10**9, **args)
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
            'machine_state': dict(old=old(current['machines']),new=new(['machines','machine_constants','machine_inheritance'],dynamic_sections)),
            'running_jobs': dict(old=old(current['running_jobs']),new=new(['running_jobs'],dynamic_sections)),
            'prefix': dict(old=old(prefix_obj),new=counter(prefix.decode())),
            'current': dict(old=old(current),new=counter(payload[len(prefix):].decode())),
            'total': dict(old=counter((canonical(prefix_obj)+b'\n'+canonical(current)).decode()),new=counter(payload.decode())),
        }
        return dict(context_ref=ctx['context_ref'],time=ctx['time'],tokenizer='o200k_base',
                    tiktoken_version=importlib.metadata.version('tiktoken'),tokens=rows,
                    note='Old column is raw JSON with the same current rules/three tools; pre-L production total was 756359 (prefix 563837). Section token counts are standalone and need not sum exactly.',
                    counts=dict(pending_tasks=len(current['pending_tasks']),running_jobs=len(current['running_jobs']),
                                ready=len(current['unreserved_ready']),machines=len(current['machines']),
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
