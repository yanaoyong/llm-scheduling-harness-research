"""Analyze saved mac_probe request JSONL; never launch a runner or endpoint.

Use --requests explicit=FILE --requests dense=FILE --snapshot explicit=FILE
--snapshot dense=FILE --context-token-budget N --output-reserve-tokens N --output FILE.
Each log must contain sequential, fully materialized requests from ONE session.
Counts are o200k_base over serialized API fields, not undocumented server framing.
The recommendation conservatively includes all request metadata and later rounds;
real server-added prompt overhead remains a Mac validation requirement.
"""
import argparse
import importlib.metadata
import json
from pathlib import Path

from harness_v6.snapshot import canonical, tiktoken_counter


def fail(field, message):
    raise ValueError(f'unsupported Responses request field {field}: {message}')


def validate_input(value):
    if isinstance(value, str):
        return
    if not isinstance(value, list):
        fail('input', 'expected string or array')
    for i, item in enumerate(value):
        path = f'input[{i}]'
        if not isinstance(item, dict):
            fail(path, 'expected object')
        kind = item.get('type', 'message' if 'role' in item else None)
        if kind == 'message':
            if item.get('role') not in ('user', 'assistant', 'system', 'developer'):
                fail(path + '.role', 'missing or unknown role')
            content = item.get('content')
            if isinstance(content, str):
                continue
            if not isinstance(content, list):
                fail(path + '.content', 'missing text string or content array')
            for j, part in enumerate(content):
                p = f'{path}.content[{j}]'
                if not isinstance(part, dict) or part.get('type') not in ('input_text', 'output_text'):
                    fail(p + '.type', 'only input_text/output_text supported; image/audio tokens cannot be inferred')
                if not isinstance(part.get('text'), str):
                    fail(p + '.text', 'missing text string')
        elif kind in ('function_call', 'function_call_output'):
            fields = ('call_id', 'name', 'arguments') if kind == 'function_call' else ('call_id', 'output')
            for field in fields:
                if not isinstance(item.get(field), str):
                    fail(path + '.' + field, 'missing string')
        elif kind == 'reasoning':
            if item.get('encrypted_content'):
                fail(path + '.encrypted_content', 'opaque reasoning tokens cannot be measured')
            if not isinstance(item.get('summary'), list):
                fail(path + '.summary', 'missing array')
            for part in item['summary']:
                if not isinstance(part, dict) or part.get('type') != 'summary_text' or not isinstance(part.get('text'), str):
                    fail(path + '.summary', 'expected summary_text objects')
        else:
            fail(path + '.type', f'unknown or missing type {kind!r}')


def strip_snapshot(value, snapshot):
    """Remove exact payload only from input strings; preserve all other values."""
    if isinstance(value, str):
        return value.replace(snapshot, ''), value.count(snapshot)
    if isinstance(value, list):
        pairs = [strip_snapshot(v, snapshot) for v in value]
        return [v for v, _ in pairs], sum(n for _, n in pairs)
    if isinstance(value, dict):
        pairs = {k: strip_snapshot(v, snapshot) for k, v in value.items()}
        return {k: v for k, (v, _) in pairs.items()}, sum(n for _, n in pairs.values())
    return value, 0


def analyze(records, snapshot, counter):
    """Injected counter keeps synthetic tests stdlib-only; CLI always uses o200k."""
    if not isinstance(snapshot, str) or not snapshot:
        raise ValueError('snapshot must be nonempty text')
    rows = []
    def count(value):
        return counter(canonical(value).decode())
    for number, record in enumerate(records, 1):
        if not isinstance(record, dict) or 'body' not in record:
            fail('body', 'missing mac_probe body')
        if not isinstance(record.get('path'), str) or record['path'].split('?')[0].rstrip('/') not in ('/responses', '/v1/responses'):
            fail('path', 'expected /responses or /v1/responses')
        body = record['body']
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except ValueError as error:
                fail('body', f'invalid JSON: {error}')
        if not isinstance(body, dict):
            fail('body', 'expected object or JSON object string')
        if body.get('previous_response_id') or body.get('conversation'):
            fail('previous_response_id/conversation', 'server-side history is unavailable; record fully materialized input')
        if 'input' not in body:
            fail('input', 'missing required field')
        validate_input(body['input'])
        instructions = body.get('instructions', '')
        if instructions is None:
            instructions = ''
        if not isinstance(instructions, str):
            fail('instructions', 'expected string or null')
        tools = body.get('tools', [])
        if not isinstance(tools, list):
            fail('tools', 'expected array')
        for index, tool in enumerate(tools):
            if not isinstance(tool, dict) or tool.get('type') != 'function':
                fail(f'tools[{index}].type', 'only explicit function schemas supported')
            for field, expected_type in (('name', str), ('parameters', dict)):
                if not isinstance(tool.get(field), expected_type):
                    fail(f'tools[{index}].{field}', 'missing field or invalid type')
        stripped, occurrences = strip_snapshot(body['input'], snapshot)
        if occurrences != 1:
            fail('input.snapshot', f'expected exactly one exact snapshot occurrence, found {occurrences}')
        system, other = [], []
        if isinstance(stripped, str):
            other = stripped
        else:
            for item in stripped:
                (system if item.get('role') in ('system', 'developer') else other).append(item)
        system_tokens = counter(instructions) + (count(system) if system else 0)
        tool_tokens = count(tools) if tools else 0
        other_tokens = count(other)
        metadata = {k: v for k, v in body.items() if k not in ('input', 'instructions', 'tools')}
        metadata_tokens = count(metadata)
        raw_tokens = count(body)
        snapshot_tokens = counter(snapshot)
        without = dict(body, input=stripped)
        # Whole serialization preserves field wrappers; additive partition guards
        # against BPE boundary effects and JSON escaping of the snapshot string.
        overhead = max(count(without), raw_tokens - snapshot_tokens,
                       system_tokens + tool_tokens + other_tokens + metadata_tokens)
        rows.append(dict(round=number, instructions_system_tokens=system_tokens,
            tool_schema_tokens=tool_tokens, snapshot_tokens=snapshot_tokens,
            other_input_tokens=other_tokens, metadata_tokens=metadata_tokens,
            serialized_request_tokens=raw_tokens, non_snapshot_input_tokens=overhead,
            conservative_input_tokens=snapshot_tokens + overhead,
            growth_from_first_round=0 if not rows else overhead - rows[0]['non_snapshot_input_tokens'],
            growth_from_previous_round=0 if not rows else overhead - rows[-1]['non_snapshot_input_tokens']))
    if not rows:
        raise ValueError('request log is empty')
    return dict(rounds=rows, request_count=len(rows),
                request_overhead_tokens=max(r['non_snapshot_input_tokens'] for r in rows))


def measure(logs, snapshots, counter, *, context_token_budget, output_reserve_tokens):
    if set(logs) != {'explicit', 'dense'} or set(snapshots) != set(logs):
        raise ValueError('both explicit and dense logs and snapshots are required')
    if context_token_budget <= 0 or output_reserve_tokens < 0:
        raise ValueError('context budget must be positive and output reserve nonnegative')
    results = {fmt: analyze(logs[fmt], snapshots[fmt], counter) for fmt in sorted(logs)}
    recommended = max(r['request_overhead_tokens'] for r in results.values())
    for fmt, result in results.items():
        needed = counter(snapshots[fmt]) + recommended + output_reserve_tokens
        result['budget_check'] = dict(snapshot_tokens=counter(snapshots[fmt]),
            request_overhead_tokens=recommended, output_reserve_tokens=output_reserve_tokens,
            required_tokens=needed, context_token_budget=context_token_budget,
            remaining_tokens=context_token_budget-needed, passed=needed <= context_token_budget)
    return dict(formats=results, request_overhead_tokens=recommended,
                counting_basis='Conservative o200k counts of serialized recorded fields; server-added framing is not observable.',
                passed=all(r['budget_check']['passed'] for r in results.values()))


def named_files(values):
    result = {}
    for value in values:
        name, sep, path = value.partition('=')
        if not sep or name not in ('explicit', 'dense') or name in result:
            raise ValueError('use exactly one explicit=PATH and dense=PATH')
        result[name] = Path(path)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--requests', action='append', required=True)
    parser.add_argument('--snapshot', action='append', required=True)
    parser.add_argument('--context-token-budget', type=int, required=True)
    parser.add_argument('--output-reserve-tokens', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    logs = {fmt: [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            for fmt, path in named_files(args.requests).items()}
    snapshots = {fmt: path.read_text() for fmt, path in named_files(args.snapshot).items()}
    result = measure(logs, snapshots, tiktoken_counter('o200k_base'),
                     context_token_budget=args.context_token_budget, output_reserve_tokens=args.output_reserve_tokens)
    result.update(tokenizer='o200k_base', tiktoken_version=importlib.metadata.version('tiktoken'))
    args.output.write_bytes(canonical(result) + b'\n')
    print(json.dumps(dict(request_overhead_tokens=result['request_overhead_tokens'], passed=result['passed']), sort_keys=True))


if __name__ == '__main__':
    main()
