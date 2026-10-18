"""Offline snapshot comprehension kit. No subprocess, network, or model calls.

Generate: --fixture F --database DB --states g0 public:702 public:703 --output DIR
Score: --questions DIR/questions.json --answers RESPONSES --output summary.json
Each response JSON: {request_id, format, state, repetition, answers: {id: value},
usage: {...}}. Missing answers score zero; missing requests are reported separately.
The answer key defaults to questions.json's sibling answer_key.json; never include
it in model prompts. --output-schema selects the generated answer schema path.
--per-type N (default 12, minimum 2) controls questions per type per state.
Sampling cycles only when a stratum is exhausted; coverage.json reports distinct
identities separately from count. Absent answer classes are not fabricated.
Interpretation selection requires different raw cell spellings, not merely a
changed table header. Non-default numeric cells with identical spellings are
therefore excluded. Answers always come from the canonical decoded objects.
"""
import argparse
import json
import random
from pathlib import Path

from harness_v6.compact import decode_snapshot
from harness_v6.snapshot import canonical

FORMATS = ('explicit', 'dense')


def write_json(path, value):
    Path(path).write_bytes(canonical(value) + b'\n')


def object_schema(properties):
    return dict(type='object', properties=properties, required=sorted(properties), additionalProperties=False)


# Defined from the question contract, never from an answer or sampled state.
ANY_JSON = {'type': ['null', 'boolean', 'number', 'string', 'array', 'object']}
NUMBER = {'type': 'number'}
BOUNDS = {k: NUMBER for k in ('batch_min', 'batch_max')}
ROUTE_FIELDS = ('processing', 'cadence', 'batch_min', 'batch_max', 'setup')
SCHEMAS = {
    'eligible': {'type': 'array', 'items': {'type': 'integer'}},
    'batch_bounds': object_schema(BOUNDS),
    'batch_compatible': {'type': 'boolean'},
    'available_time': NUMBER,
    'queue': object_schema(dict(pending={'type': 'array', 'items': {'type': 'string'}},
        head={'type': ['null', 'string']}, running={'type': 'array', 'items': {'type': 'integer'}})),
    'value_semantics': object_schema(dict(present={'type': 'boolean'},
        kind={'type': 'string', 'enum': ['absent', 'null', 'empty_string', 'value']}, value=ANY_JSON)),
    'route_step': object_schema({k: ANY_JSON if k in ('processing', 'cadence') else
                               NUMBER if k in BOUNDS else {'type': 'string'} for k in ROUTE_FIELDS}),
}


def wire_tables(payload):
    """Retain raw cells and column conventions for selection/auditing, not keys."""
    from harness_v6.compact import sections
    result = {}
    for part in payload.decode().split('CURRENT\n'):
        if part.startswith('SNAPSHOT_'):
            part = part.split('\n', 1)[1]
        decoded = sections(part)
        lines = iter(part.removesuffix('\n').split('\n'))
        for line in lines:
            bits = line.split('\t')
            name = bits[0][1:]
            if bits[1] == 'value':
                result[name] = dict(value=decoded[name])
                continue
            columns = json.loads(bits[3])
            defaults = json.loads(bits[4][9:]) if len(bits) > 4 else {}
            aliases = json.loads(bits[5][7:]) if len(bits) > 5 else {}
            raw = [dict(zip(columns, next(lines).split('\t'))) for _ in range(int(bits[2]))]
            result[name] = dict(rows=decoded[name] if bits[1] == 'table' else [decoded[name]],
                                raw=raw, defaults=defaults, aliases=aliases)
    return result


def wire_cell(tables, target):
    field = target['field']
    if 'route' in target:
        route = next(r for r in tables['routes']['rows'] if r['route'] == target['route'])
        defs = tables['step_definitions']['rows']
        if tables['step_number_is_position']['value']:
            index = route['definitions'][target['step'] - 1]
        else:
            index = next(i for i in route['definitions'] if defs[i]['step'] == target['step'])
        table = tables['step_definitions']
    elif 'machine' in target:
        table = tables['machines']
        index = next(i for i, r in enumerate(table['rows']) if r['machine'] == target['machine'])
    else:
        table = tables['ready_groups']
        index = next(i for i, r in enumerate(table['rows']) if target['operation_id'] in r['$operations'])
    return dict(cell=table['raw'][index].get(field, '!'),
                default={field: table['defaults'][field]} if field in table['defaults'] else {},
                alias={field: table['aliases'][field]} if field in table['aliases'] else {},
                release_is_time=table['rows'][index].get('$release_time_is_time', False)
                if field == 'release_time' else False)


def questions_for(state, prefix, current, rng, snapshots, per_type):
    """Canonical objects supply keys; wire conventions only stratify selection."""
    rows = []
    def add(kind, text, answer, target, answer_class):
        rows.append(dict(id=f'{state}/q{len(rows):03d}', type=kind, state=state,
                         text=text, answer_schema=SCHEMAS[kind], target=target,
                         answer=answer, answer_class=answer_class))
    def sample(pool, n):
        if not pool:
            raise ValueError(f'{state}: no candidates for required question class')
        pool = list({canonical(item): item for item in pool}.values())
        rng.shuffle(pool)
        return [pool[i % len(pool)] for i in range(n)]
    def stratified(groups, n):
        pools = [sample(v, n) for k, v in sorted(groups.items()) if v]
        if not pools:
            raise ValueError(f'{state}: no convention-sensitive interpretation candidates')
        return [pools[i % len(pools)][i // len(pools)] for i in range(n)]
    ops = sorted(current['unreserved_ready'], key=lambda r: r['operation_id'])
    machines = sorted(current['machines'], key=lambda r: r['machine'])
    for kind in ('eligible', 'batch_bounds'):
        for op in sample(ops, per_type):
            oid = op['operation_id']
            answer = sorted(op['eligible_machines']) if kind == 'eligible' else {k: op[k] for k in BOUNDS}
            add(kind, f'For operation {oid}, give ' + ('the complete eligible machine set sorted ascending.'
                if kind == 'eligible' else 'batch_min and batch_max.'), answer, {'operation_id': oid},
                'nonempty' if kind == 'eligible' and answer else 'bounds' if kind == 'batch_bounds' else 'empty')
    buckets = {}
    for op in ops:
        buckets.setdefault(canonical([op[k] for k in ('batch_key', 'batch_min', 'batch_max')]), []).append(op)
    positives, negatives = [], {'same_key_no_common_machine': [], 'same_machines_different_key': [], 'other_false': []}
    for bucket in buckets.values():
        by_machine = {}
        for op in bucket:
            for mid in op['eligible_machines']:
                by_machine.setdefault(mid, []).append(op)
        for eligible in by_machine.values():
            size = max(2, eligible[0]['batch_min'])
            if size <= eligible[0]['batch_max'] and len(eligible) >= size:
                positives.append(eligible[:size])
        for i, left in enumerate(bucket):
            for right in bucket[i+1:]:
                if not set(left['eligible_machines']) & set(right['eligible_machines']):
                    size = max(2, left['batch_min'])
                    if size <= left['batch_max'] and len(bucket) >= size:
                        rest = [r for r in bucket if r is not left and r is not right]
                        negatives['same_key_no_common_machine'].append([left, right] + rest[:size-2])
                    break
    # Near misses violate only the named condition, including valid batch size.
    machine_buckets = {}
    for op in ops:
        signature = canonical([op['eligible_machines'], op['batch_min'], op['batch_max']])
        machine_buckets.setdefault(signature, []).append(op)
    for bucket in machine_buckets.values():
        size = max(2, bucket[0]['batch_min'])
        if not bucket[0]['eligible_machines'] or size > bucket[0]['batch_max'] or len(bucket) < size:
            continue
        for left in bucket:
            right = next((r for r in bucket if r['batch_key'] != left['batch_key']), None)
            if right is not None:
                rest = [r for r in bucket if r is not left and r is not right]
                negatives['same_machines_different_key'].append([left, right] + rest[:size-2])
    for i, left in enumerate(ops):
        right = next((r for r in ops[i+1:] if r['batch_key'] != left['batch_key']), None)
        if right is not None:
            negatives['other_false'].append([left, right])
    for batch in sample(positives, (per_type + 1)//2):
        ids = [r['operation_id'] for r in batch]
        add('batch_compatible', batch_text(ids), True, {'operation_ids': ids}, 'true')
    choices = {k: [(k, v) for v in values] for k, values in negatives.items()}
    for cls, batch in stratified(choices, per_type//2):
        ids = [r['operation_id'] for r in batch]
        add('batch_compatible', batch_text(ids), False, {'operation_ids': ids}, cls)
    orders = {r['machine']: r['task_ids'] for r in current['machine_orders']}
    groups = {}
    for machine in machines:
        mid = machine['machine']
        pending = orders.get(mid, [])
        running = sorted(r['job'] for r in current['running_jobs'] if r['machine'] == mid)
        cls = ('pending' if pending else 'no_pending') + ('_running' if running else '_idle')
        groups.setdefault(cls, []).append((mid, pending, running, cls))
    for mid, pending, running, cls in stratified(groups, per_type):
        add('queue', f'For machine {mid}, give pending task IDs in queue order, head task ID (null if none), '
            'and running job IDs sorted ascending. Running jobs are not pending tasks.',
            dict(pending=pending, head=pending[0] if pending else None, running=running), {'machine': mid}, cls)
    for machine in sample(machines, per_type):
        add('available_time', f"Give the available_at value for machine {machine['machine']}.",
            machine['available_at'], {'machine': machine['machine']}, 'number')
    steps = [(route, step) for route, values in sorted(prefix['routing'].items()) for step in values]
    for route, step in sample(steps, per_type):
        add('route_step', f"For route {route} step {step['step']}, give processing distribution, cadence, "
            'batch_min, batch_max and setup from the static prefix.', {k: step[k] for k in ROUTE_FIELDS},
            {'route': route, 'step': step['step']}, 'route_definition')
    wires = {fmt: wire_tables(snapshots[fmt]) for fmt in FORMATS}
    candidates = []
    for route, step in steps:
        for field in ('setup_time', 'setup', 'sampling_percent', 'batch_min', 'batch_max', 'cadence'):
            if field in step:
                candidates.append((dict(route=route, step=step['step'], field=field), step[field]))
    for machine in machines:
        for field in ('current_setup', 'processing_until'):
            if field in machine:
                candidates.append((dict(machine=machine['machine'], field=field), machine[field]))
    candidates.extend((dict(operation_id=op['operation_id'], field='release_time'), op['release_time'])
                      for op in ops if 'release_time' in op)
    groups = {}
    for target, value in candidates:
        explicit, dense = [wire_cell(wires[fmt], target) for fmt in FORMATS]
        if explicit['cell'] == dense['cell']:
            continue
        convention = ('release_omission' if dense['release_is_time'] else 'alias' if dense['cell'] == '=' else
                      'default' if dense['cell'] == '' else 'non_default' if dense['default'] else 'literal')
        if convention == 'literal':
            continue
        kind = 'null' if value is None else 'empty_string' if value == '' else 'value'
        cls = target['field'] + ':' + convention + ':' + kind
        groups.setdefault(cls, []).append((target, value, kind, cls))
    # Cover every field first, then contrast default/non-default values.
    fields = ('setup_time', 'current_setup', 'sampling_percent', 'setup', 'batch_min',
              'batch_max', 'cadence', 'processing_until', 'release_time')
    ordered = []
    for field in fields:
        classes = sorted(k for k in groups if k.startswith(field + ':'))
        if classes:
            ordered.append(classes[0])
    for field in fields:
        ordered.extend(k for k in sorted(groups) if k.startswith(field + ':') and k not in ordered)
    pools = [sample(groups[k], per_type) for k in ordered]
    if not pools:
        raise ValueError(f'{state}: no convention-sensitive interpretation candidates')
    selected = [pools[i % len(pools)][i // len(pools)] for i in range(per_type)]
    for target, value, kind, cls in selected:
        entity = ', '.join(f'{k} {v}' for k, v in target.items() if k != 'field')
        add('value_semantics', f"Interpret {target['field']} for {entity}. Report present, kind "
            '(absent/null/empty_string/value), and decoded value (null if absent). Resolve declared '
            'defaults, aliases and omission conventions.', dict(present=True, kind=kind, value=value), target, cls)
    return rows


def batch_text(ids):
    return (f'Can operations {ids} form one batch considering ONLY identical batch_key, identical '
            'batch_min/max, batch size bounds and a common eligible machine? Ignore current availability, '
            'setup, dedication, holds and timing; this is not a dispatch-feasibility question.')


def coverage(questions):
    from collections import Counter
    return {state: {kind: dict(count=len(rows), unique_targets=len({canonical(q['target']) for q in rows}),
                answer_classes=dict(sorted(Counter(q['answer_class'] for q in rows).items())))
            for kind in sorted(SCHEMAS)
            for rows in [[q for q in questions if q['state'] == state and q['type'] == kind]]}
            for state in sorted({q['state'] for q in questions})}


def generate(states, output, *, seed=0, repetitions=2, output_schema=None, per_type=12):
    """states maps stable names to explicit/dense snapshot bytes."""
    if repetitions < 2 or repetitions % 2:
        raise ValueError('repetitions must be a positive even number (>=2) for exact counterbalancing')
    if per_type < 2:
        raise ValueError('per_type must be >= 2 for balanced boolean questions')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    questions, answers = [], {}
    for state in sorted(states):
        if set(states[state]) != set(FORMATS):
            raise ValueError(f'{state}: both explicit and dense snapshots required')
        a, b = [decode_snapshot(states[state][fmt]) for fmt in FORMATS]
        if a[1] != b[1] or any(a[0][k] != b[0][k] for k in ('routing', 'machine_groups', 'tools')):
            raise ValueError(f'{state}: formats decode to different production objects')
        for row in questions_for(state, a[0], a[1], rng, states[state], per_type):
            answers[row['id']] = row.pop('answer')
            questions.append(row)
    if not questions:
        raise ValueError('no states supplied')
    plan = []
    state_order = sorted(states)
    rng.shuffle(state_order)
    for index, state in enumerate(state_order):
        subset = [q for q in questions if q['state'] == state]
        properties = {q['id']: q['answer_schema'] for q in subset}
        response_schema = dict(type='object', properties=properties, required=sorted(properties), additionalProperties=False)
        state_file = f'state-{index:03d}'
        write_json(output / f'{state_file}.schema.json', response_schema)
        for fmt in FORMATS:
            prompt = ('Answer every question as a JSON object keyed by question ID. Use only this snapshot. '
                      'Do not use tools.\n' + states[state][fmt].decode() + '\nQUESTIONS\n' +
                      canonical([{k: q[k] for k in ('id', 'text', 'answer_schema')} for q in subset]).decode() + '\n')
            (output / f'{state_file}-{fmt}.txt').write_text(prompt, encoding='utf-8')
        first = list(FORMATS)
        rng.shuffle(first)
        for repetition in range(repetitions):
            order = first if repetition % 2 == 0 else first[::-1]
            for fmt in order:
                plan.append(dict(request_id=f'{state_file}-r{repetition}-{fmt}', state=state,
                    format=fmt, repetition=repetition, prompt=f'{state_file}-{fmt}.txt',
                    output_schema=f'{state_file}.schema.json'))
    write_json(output / 'questions.json', dict(seed=seed, repetitions=repetitions, per_type=per_type, questions=[{k: v for k, v in q.items() if k != 'answer_class'} for q in questions],
                                               presentation_plan=plan))
    write_json(output / 'answer_key.json', answers)
    write_json(output / 'coverage.json', coverage(questions))
    all_schema = dict(type='object', properties={q['id']: q['answer_schema'] for q in questions},
                      required=[q['id'] for q in questions], additionalProperties=False)
    write_json(output_schema or output / 'output-schema.json', all_schema)
    write_json(output / 'presentation_plan.json', plan)
    return questions, answers, plan


def load_real_states(fixture, database, selectors, counter):
    """Thin fixture adapter; public states retain existing plan, add no tasks.

    g0 selects the archived G0 1649.82 snapshot. public:T advances the restored
    mixed_702 state to T without planning (decision interrupts suppressed to T).
    These are public-physics states, not archived model trajectories.
    """
    from harness_v6.factory_v6 import restore
    from harness_v6.ledger import ledger_from_scratch
    from harness_v6.sealed_contexts import SQLiteContextReader
    from harness_v6.snapshot import stable_prefix, build_snapshot
    bundle = json.loads(Path(fixture).read_bytes())
    seed = bundle['mixed_702']
    env = restore(seed['state'], seed['trace'], data_dir=bundle['data_dir'])
    prefixes = {fmt: stable_prefix(tool_descriptions=[], routing=env.manifest['routes'],
                machine_groups=env.manifest['machines'], snapshot_format=fmt, token_counter=counter) for fmt in FORMATS}
    states = {}
    if len(selectors) != len(set(selectors)):
        raise ValueError('duplicate state selector')
    public_times = set()
    for selector in selectors:
        if selector == 'g0':
            matches = [r['context'] for r in SQLiteContextReader(database, 'SELECT group_name,payload FROM contexts').contexts()
                       if r['group'] == 'G0' and abs(r['context']['time'] - 1649.82) < .01]
            if len(matches) != 1:
                raise ValueError('expected exactly one G0 t=1649.82 context')
            ctx = matches[0]
            ledger = ledger_from_scratch(ctx['problem'], ctx['base_plan'], {'tasks': [
                dict(task_id=t, state='running') for t in ctx['execution_state']['dispatched_task_ids']]})
            g0 = bundle['g0_snapshot']
            if g0['context_ref'] != ctx['context_ref'] or g0['time'] != ctx['time']:
                raise ValueError('G0 running-job fixture context_ref/time mismatch')
            jobs = g0['running_jobs']
            version = ctx['state_revision']
        elif selector.startswith('public:'):
            target = float(selector.split(':', 1)[1])
            if target in public_times:
                raise ValueError('duplicate public time')
            public_times.add(target)
            public = restore(seed['state'], seed['trace'], data_dir=bundle['data_dir'])
            if not public.t <= target <= public.horizon:
                raise ValueError(f'{selector}: time outside restored state horizon')
            public.advance_cycle(target, decision_after=target)
            if abs(public.t - target) > 1e-8:
                raise ValueError(f'{selector}: physics stopped at {public.t}: {public.last_stop}')
            observed = public.ledger_snapshot()
            ledger = ledger_from_scratch(observed['problem'], observed['plan'], observed['receipts'])
            jobs = [dict(job=i, machine=j['machine'], lot_ids=j['lots'], started_at=j['start'])
                    for i, j in sorted(public.jobs.items()) if not j['done']]
            version = selector
        else:
            raise ValueError(f'unknown state {selector}; use g0 or public:SECONDS')
        states[selector] = {fmt: build_snapshot(prefixes[fmt], ledger, state_version=version,
            running_jobs=jobs, last_cycle_receipt=None, model_notes='', token_budget=10**9,
            token_counter=counter, snapshot_format=fmt) for fmt in FORMATS}
    if 'g0' not in states or len(public_times) < 2:
        raise ValueError('require g0 and at least two distinct public time points')
    return states


def score(questions_path, answers_dir, output, answer_key=None):
    questions_path = Path(questions_path)
    kit = json.loads(questions_path.read_bytes())
    key = json.loads(Path(answer_key or questions_path.with_name('answer_key.json')).read_bytes())
    expected = {r['request_id']: r for r in kit['presentation_plan']}
    received, details, requests = set(), [], []
    for file in sorted(Path(answers_dir).glob('*.json')):
        record = json.loads(file.read_bytes())
        rid = record.get('request_id')
        if rid not in expected or rid in received:
            raise ValueError(f'{file}: unknown or duplicate request_id {rid}')
        planned = expected[rid]
        for field in ('format', 'state', 'repetition'):
            if record.get(field) != planned[field]:
                raise ValueError(f'{file}: mismatched {field}')
        actual = record.get('answers')
        if not isinstance(actual, dict):
            raise ValueError(f'{file}: missing answers object')
        subset = [q for q in kit['questions'] if q['state'] == planned['state']]
        if set(actual) - {q['id'] for q in subset}:
            raise ValueError(f'{file}: unknown answer IDs')
        received.add(rid)
        requests.append(dict(request_id=rid, format=planned['format'], usage=record.get('usage')))
        for q in subset:
            details.append(dict(request_id=rid, id=q['id'], type=q['type'], format=planned['format'],
                correct=q['id'] in actual and canonical(actual[q['id']]) == canonical(key[q['id']])))
    # Missing requests count as wrong, so dropping a failed request cannot inflate accuracy.
    for rid in sorted(set(expected) - received):
        p = expected[rid]
        for q in kit['questions']:
            if q['state'] == p['state']:
                details.append(dict(request_id=rid, id=q['id'], type=q['type'], format=p['format'], correct=False))
    def aggregate(rows):
        return dict(correct=sum(r['correct'] for r in rows), total=len(rows),
                    accuracy=sum(r['correct'] for r in rows) / len(rows) if rows else None)
    summary = {fmt: dict(overall=aggregate([r for r in details if r['format'] == fmt]),
        by_type={kind: aggregate([r for r in details if r['format'] == fmt and r['type'] == kind])
                 for kind in sorted({q['type'] for q in kit['questions']})}) for fmt in FORMATS}
    result = dict(summary=summary, per_question=details, requests=requests,
                  expected_requests=len(expected), received_requests=len(received),
                  missing_requests=sorted(set(expected) - received))
    write_json(output, result)
    lines = ['| 格式 | 题型 | 正确 / 总数 | 准确率 |', '|---|---|---:|---:|']
    for fmt in FORMATS:
        for kind, value in [('全部', summary[fmt]['overall']), *summary[fmt]['by_type'].items()]:
            accuracy = '无题目' if value['accuracy'] is None else f"{value['accuracy']:.2%}"
            lines.append(f"| {fmt} | {kind} | {value['correct']} / {value['total']} | {accuracy} |")
    lines += ['', f'请求数：{len(received)} / {len(expected)}。缺失请求按错误计分。',
              '逐请求 token 用量保留在 JSON requests[].usage；null 表示未知，不能记为零。']
    Path(output).with_suffix('.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    gen = sub.add_parser('generate')
    for name in ('fixture', 'database', 'output'):
        gen.add_argument('--' + name, required=True)
    gen.add_argument('--states', nargs='+', default=['g0', 'public:702', 'public:703'])
    gen.add_argument('--per-type', type=int, default=12)
    gen.add_argument('--seed', type=int, default=0)
    gen.add_argument('--repetitions', type=int, default=2)
    gen.add_argument('--output-schema')
    scoring = sub.add_parser('score')
    for name in ('questions', 'answers', 'output'):
        scoring.add_argument('--' + name, required=True)
    scoring.add_argument('--answer-key')
    sub.add_parser('run', help='not yet available; requires the later Codex runner')
    args = parser.parse_args()
    if args.command == 'run':
        parser.error('run is not yet available: Phase P must integrate the Codex runner')
    if args.command == 'generate':
        from harness_v6.snapshot import tiktoken_counter
        states = load_real_states(args.fixture, args.database, args.states, tiktoken_counter())
        generate(states, args.output, seed=args.seed, repetitions=args.repetitions, output_schema=args.output_schema, per_type=args.per_type)
    else:
        score(args.questions, args.answers, args.output, args.answer_key)


if __name__ == '__main__':
    main()
