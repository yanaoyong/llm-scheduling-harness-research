"""Read the public derivative only; all generated evidence stays in scratch.

Historical object names are lookup keys, NOT hashes of public bytes. The provenance
index records compressed public SHA256 and canonical decoded SHA256 separately.
No archived production task is rewritten. Context anchors are recomputed separately.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import zlib
from harness_v6.contracts import encode, digest
from harness_v6.work_paths import checked_output


class Archive:
    def __init__(self, directory, scratch, provenance):
        self.directory = directory
        self.provenance = provenance
        sql = directory / 'events.sqlite3.public.sql'
        self.db = sqlite3.connect(scratch / (directory.name + '.sqlite'))
        # Re-import on every invocation: never silently reuse a stale scratch DB.
        with sqlite3.connect(':memory:') as imported:
            imported.executescript(self.read(sql).decode())
            imported.backup(self.db)

    def read(self, path):
        raw = path.read_bytes()
        self.provenance[str(path)] = {'public_sha256': hashlib.sha256(raw).hexdigest()}
        return raw

    def obj(self, ref):
        path = self.directory / 'objects' / (ref + '.z.public.json.z')
        value = json.loads(zlib.decompress(self.read(path)))
        self.provenance[str(path)]['decoded_sha256'] = digest(value)
        return value

    def records(self, namespace):
        return [self.obj(ref) for (ref,) in self.db.execute(
            'SELECT ref FROM records WHERE namespace=? ORDER BY key', (namespace,))]

    def trace(self):
        rows = [json.loads(line) for line in self.read(self.directory / 'exports/trace.jsonl').splitlines()]
        assert [e['seq'] for e in rows] == [r[0] for r in self.db.execute('SELECT seq FROM physical ORDER BY seq')]
        return rows


def add_common_endpoints(root, output, data_dir):
    """Reconstruct only within an archived execution batch, then verify physics.

    Derived observations carry a measured: ref and never count as model contexts.
    """
    from harness_v6.factory_v6 import restore
    from harness_v6.replay import physical_events
    end = 1603.1013031725258
    provenance = json.loads((output/'provenance.json').read_bytes())
    db = sqlite3.connect(output/'contexts.sqlite')
    db.execute("DELETE FROM contexts WHERE json_extract(payload,'$.measurement') = 'common_endpoint'")
    for group in ('G0', 'G1', 'G2'):
        archive = Archive(root/'live_pilots/extended_three_group_final_segment_20261017'/group, output, provenance)
        trace = archive.trace()
        batches = [archive.obj(ref) for (ref,) in archive.db.execute("SELECT payload_ref FROM events WHERE kind='execution_batch' ORDER BY seq")]
        batch = next(b for b in batches if b['from'] < end <= b['to'])
        if abs(batch['to'] - end) < 1e-7:
            state = archive.obj(batch['after_state_ref']); prefix = trace[:batch['event_end']]
            env = restore(state, prefix, data_dir=data_dir)
        else:
            state = archive.obj(batch['before_state_ref']); prefix = trace[:batch['event_start']]
            env = restore(state, prefix, data_dir=data_dir)
            env.advance_plan(end)
            assert env.t == end
            assert physical_events(env.trace[len(prefix):], start=state['t'], end=end) == physical_events(trace[batch['event_start']:batch['event_end']], start=state['t'], end=end)
        observed = env.ledger_snapshot()
        ctx = dict(context_ref='measured:'+group+':common_endpoint', measurement='common_endpoint',
                   time=end, state_revision=None, problem=observed['problem'], base_plan=env.plan,
                   ledger_receipts=observed['receipts'], execution_state={}, trigger=None)
        db.execute('INSERT INTO contexts VALUES (?,?)', (group, encode(ctx).decode()))
    db.commit(); db.close()
    (output/'provenance.json').write_bytes(encode(provenance))


def build(root, public, output, *, work_root):
    bundle = json.loads(public.read_bytes())
    output = checked_output(output, work_root, inputs=(root, public, bundle['data_dir']))
    output.mkdir(parents=True, exist_ok=False)
    provenance = {}
    segment = root / 'live_pilots/extended_three_group_final_segment_20261017'
    db = sqlite3.connect(output / 'contexts.sqlite')
    db.execute('CREATE TABLE IF NOT EXISTS contexts(group_name TEXT, payload TEXT)')
    db.execute('DELETE FROM contexts')
    seed_path = root / 'fixtures/initial/mixed_702.json.z.public.json.z'
    seed_raw = seed_path.read_bytes(); seed = json.loads(zlib.decompress(seed_raw))
    provenance[str(seed_path)] = {'public_sha256': hashlib.sha256(seed_raw).hexdigest(), 'decoded_sha256': digest(seed)}
    bundle['mixed_702'] = {k: seed[k] for k in ('state', 'trace')}
    summary = {'contexts': {}, 'd34_candidates': [], 'anchor_recomputations': []}
    for group in ('G0', 'G1', 'G2'):
        archive = Archive(segment / group, output, provenance)
        contexts = sorted(archive.records('contexts'), key=lambda c: (c['time'], c['state_revision'], c['context_ref']))
        trace = archive.trace()
        commits = sorted(archive.records('commits'), key=lambda c: (c['time'], c['actual_revision']))
        if group == 'G0':
            head = json.loads(archive.db.execute("SELECT value FROM metadata WHERE key='head'").fetchone()[0])
            state = archive.obj(head['state_ref'])
            snapshot_ctx = next(c for c in contexts if abs(c['time'] - 1649.82) < .01)
            assert state['t'] == snapshot_ctx['time']
            bundle['g0_snapshot'] = {
                'context_ref': snapshot_ctx['context_ref'], 'time': state['t'],
                'running_jobs': [dict(job=int(i), machine=j['machine'], lot_ids=j['lots'], started_at=j['start'])
                                 for i, j in sorted(state['jobs'].items(), key=lambda item: int(item[0]))
                                 if not j['done']]}
            bundle['g0_trace'] = trace
            candidates = {c['candidate_ref']: c for c in archive.records('candidates')}
            bundle['g0_committed_plans'] = [{'time': c['time'], 'plan': candidates[c['candidate_ref']]['compiled']['plan']} for c in commits]
        states = {}
        wanted = {(c['time'], digest(c['base_plan'])) for c in contexts
                  if any(t['id'] == 'd34-421' and t['id'] not in c['execution_state']['dispatched_task_ids'] and t.get('not_before', c['time']) < c['time']
                         for t in c['base_plan']['tasks'])}
        for kind, ref in archive.db.execute("SELECT kind,payload_ref FROM events WHERE kind IN ('execution_batch','commit_accepted','stopped') ORDER BY seq"):
            if not wanted:
                break
            event = archive.obj(ref)
            for key in ('before_state_ref', 'after_state_ref', 'state_ref'):
                time_key = {'before_state_ref': 'from', 'after_state_ref': 'to', 'state_ref': 'time'}[key]
                if key in event and event.get(time_key) in {time for time, _ in wanted}:
                    state = archive.obj(event[key]); identity = (state['t'], digest(state['plan']))
                    if identity in wanted: states[identity] = state
        for ctx in contexts:
            # Store original refs for historical lookup; refreshed anchors are explicit metadata.
            summary['anchor_recomputations'].append({'group': group, 'context_ref': ctx['context_ref'],
                'public_anchors': {key: digest(ctx[key]) for key in ('problem', 'base_plan', 'execution_state')}})
            db.execute('INSERT INTO contexts VALUES (?,?)', (group, encode(ctx).decode()))
            past = [t for t in ctx['base_plan']['tasks'] if t['id'] == 'd34-421' and t['id'] not in ctx['execution_state']['dispatched_task_ids'] and t.get('not_before', ctx['time']) < ctx['time']]
            if past:
                summary['d34_candidates'].append({'group': group, 'context_ref': ctx['context_ref'], 'time': ctx['time']})
                if 'd34_421' not in bundle:
                    state = states.get((ctx['time'], digest(ctx['base_plan'])))
                    if state is not None:
                        plan = deepcopy(ctx['base_plan'])
                        # A new submission envelope at the original context; every task stays verbatim.
                        plan.update(version='v6-retain-d34-421', created_at=ctx['time'], freeze_until=ctx['time'])
                        dispatched = set(ctx['execution_state']['dispatched_task_ids'])
                        plan['tasks'] = [t for t in plan['tasks'] if t['id'] not in dispatched]
                        bundle['d34_421'] = {'state': state, 'trace': [e for e in trace if e['seq'] < state['seq']],
                                             'plan': plan, 'context_ref': ctx['context_ref']}
        summary['contexts'][group] = len(contexts)
        print(group, len(contexts), len(trace), len(commits), flush=True)
    config_path = segment / 'G0.config.json'
    raw = config_path.read_bytes(); provenance[str(config_path)] = {'public_sha256': hashlib.sha256(raw).hexdigest()}
    bundle['sealed_input_budget'] = json.loads(raw)['capacity_experiment']['input_token_budget']
    case_path = segment / 'already_planned_replan_case.json'
    raw = case_path.read_bytes(); provenance[str(case_path)] = {'public_sha256': hashlib.sha256(raw).hexdigest()}
    bundle['w1462_case'] = json.loads(raw)
    db.commit(); db.close()
    (output / 'fixture.json').write_bytes(encode(bundle))
    (output / 'provenance.json').write_bytes(encode(provenance))
    (output / 'build_summary.json').write_bytes(encode(summary))
    add_common_endpoints(root, output, bundle['data_dir'])
    print('built', output, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence-root', type=Path, required=True)
    parser.add_argument('--public-fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--work-root', type=Path, required=True)
    args = parser.parse_args()
    build(args.evidence_root, args.public_fixture, args.output, work_root=args.work_root)
