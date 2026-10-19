"""Export full production-contract snapshots and cycle prompts, without a model.

    These are archived-state pressure samples, not production trajectories.
    Delta and deadline parameters must be supplied explicitly and recorded.
"""
import argparse
import hashlib
import json
from pathlib import Path
from ab_comprehension import load_real_states
from harness_v6.compact import decode_snapshot
from harness_v6.snapshot import canonical, tiktoken_counter
from harness_v6.prompt_rules import cycle_footer


def export(states, output, *, delta, delta_min, wall_seconds, valid_until_maximum, max_tool_calls, counter):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    rows = []
    for state, formats in states.items():
        directory = root / state.replace(':', '-')
        directory.mkdir()
        for fmt, payload in formats.items():
            prefix, current = decode_snapshot(payload)
            from harness_v6.mcp_server import TOOLS
            if {tool['name'] for tool in prefix['tools']} != set(TOOLS):
                raise ValueError('recording snapshot must use the production tool contract')
            path = directory / (fmt+'-snapshot.txt')
            path.write_bytes(payload)
            row = dict(state=state, format=fmt, snapshot=str(path.relative_to(root)),
                snapshot_sha256=hashlib.sha256(payload).hexdigest(), tokens=counter(payload.decode()), prompts={})
            for interaction in ('single_action', 'mcp_session'):
                trigger = 'event' if interaction == 'single_action' else 'periodic'
                footer = cycle_footer(state_version=current['state_version'], submission_id='recording',
                    now=current['time'], next_anchor=current['time'], delta=delta,
                    delta_min=delta_min, trigger=trigger, interaction=interaction, wall_seconds=wall_seconds,
                    valid_until_maximum=valid_until_maximum, max_tool_calls=max_tool_calls)
                prompt = payload + footer.encode()
                target = directory / (fmt+'-'+interaction+'-prompt.txt')
                target.write_bytes(prompt)
                row['prompts'][interaction] = dict(path=str(target.relative_to(root)),
                    sha256=hashlib.sha256(prompt).hexdigest(), tokens=counter(prompt.decode()))
            rows.append(row)
    report = dict(contract='production_prefix/full_snapshot/cycle_footer-v3', real_model_requests=0,
        purpose='offline archived-state pressure samples; not a registered production run',
        delta=delta, delta_min=delta_min, wall_seconds=wall_seconds, valid_until_maximum=valid_until_maximum, max_tool_calls=max_tool_calls,
        triggers=dict(single_action='event', mcp_session='periodic'),
        next_anchor='sample current_time (initial periodic cycle)', samples=rows)
    (root/'manifest.json').write_bytes(canonical(report)+b'\n')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixture', required=True)
    p.add_argument('--database', required=True)
    p.add_argument('--public-ledger', required=True)
    p.add_argument('--states', nargs='+', default=['g0','public:702','public:1182','public:1602'])
    p.add_argument('--delta', type=json.loads, required=True)
    p.add_argument('--delta-min', type=json.loads, required=True)
    p.add_argument('--wall-seconds', type=json.loads, required=True)
    p.add_argument('--horizon-seconds', type=json.loads, required=True)
    p.add_argument('--valid-until-maximum', type=json.loads, required=True,
        help='Explicit host plan boundary for these archived pressure samples; not the snapshot lookahead')
    p.add_argument('--max-tool-calls',type=int,required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    if min(a.delta, a.delta_min, a.wall_seconds, a.horizon_seconds) <= 0:
        p.error('timing parameters must be positive')
    count = tiktoken_counter()
    states = load_real_states(a.fixture, a.database, a.states, count,
        public_ledger=a.public_ledger, horizon_seconds=a.horizon_seconds)
    export(states, a.output, delta=a.delta, delta_min=a.delta_min, wall_seconds=a.wall_seconds,
        valid_until_maximum=a.valid_until_maximum, max_tool_calls=a.max_tool_calls, counter=count)
