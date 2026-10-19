"""One process, one final JSON action, no tools. Runner is always injected.

Evidence retains the raw JSONL, its hash, final arguments, receipt and compiled
plan. Recompilation binds every production value to the final delta or trusted
frozen base, following the legacy raw_delta / audit_provenance semantics.
"""
from copy import deepcopy
from pathlib import Path
from .contracts import encode, digest, strict_json
from .mcp_server import TOOLS
from .session import Budget, RunResult, command as session_command, classify
from .submit import Submitter
from .structured_schema import validate_strict_schema

OUTPUT_SCHEMA = deepcopy(TOOLS['submit_plan'])


def write_schema(path):
    validate_strict_schema(OUTPUT_SCHEMA)
    Path(path).write_bytes(encode(OUTPUT_SCHEMA))


def command(input_dir, schema_path, *, model, budget=Budget(), binary='codex',
            context_token_budget=None, output_reserve_tokens=None, model_config=None):
    argv = session_command(input_dir, input_dir, model=model, budget=budget, binary=binary,
        context_token_budget=context_token_budget, output_reserve_tokens=output_reserve_tokens, model_config=model_config)
    result = []
    index = 0
    while index < len(argv) - 1:
        if argv[index] == '-c' and argv[index + 1].startswith('mcp_servers.'):
            index += 2
        elif argv[index] == '-c' and argv[index + 1].startswith('harness_max_inference_requests='):
            result.extend(['-c', 'harness_max_inference_requests=1'])
            index += 2
        else:
            result.append(argv[index])
            index += 1
    return result + ['-c', 'mcp_servers={}', '--output-schema', str(schema_path), '-']


def parse(jsonl):
    parsed = classify(jsonl, interaction='single_action')
    messages = []
    for line in jsonl.splitlines():
        try:
            event = strict_json(line)
            if event.get('type') == 'item.completed' and event.get('item', {}).get('type') == 'agent_message':
                messages.append(event['item']['text'])
        except (ValueError, KeyError, TypeError, AttributeError):
            parsed['errors'].append('malformed_message')
    args = None
    try:
        # Commentary may precede the final message; only the final completed
        # agent_message is authoritative, never an earlier valid JSON candidate.
        args = strict_json(messages[-1])
        if not isinstance(args, dict) or set(args) != set(OUTPUT_SCHEMA['required']):
            raise ValueError('submit payload keys')
        if not isinstance(args['delta'], dict) or not isinstance(args['submission_id'], str):
            raise ValueError('submit payload types')
    except (ValueError, TypeError, IndexError):
        parsed['errors'].append('invalid_final_action')
    return {**parsed, 'arguments': args}


def raw_delta(jsonl):
    parsed = parse(jsonl)
    if parsed['errors']:
        raise ValueError(parsed['errors'])
    return deepcopy(parsed['arguments']['delta'])


def audit_provenance(evidence, initial_state):
    errors = []
    parsed = parse(evidence['jsonl'])
    errors.extend(parsed['errors'])
    if digest(evidence['jsonl']) != evidence.get('jsonl_sha256'):
        errors.append('jsonl_hash')
    if parsed['arguments'] != evidence.get('arguments'):
        errors.append('final_output_mismatch')
    replay = Submitter.restore(initial_state)
    try:
        receipt = replay.submit_plan(**parsed['arguments'])
        if (not receipt['accepted'] or receipt != evidence.get('receipt')
                or replay.candidate != evidence.get('plan')):
            errors.append('production_not_from_model')
    except (ValueError, TypeError, KeyError):
        errors.append('production_not_from_model')
    return errors


def finish(result, *, submitter, commit, metrics, now, budget=Budget(), cycle=None, model_note=''):
    initial = submitter.capture()
    parsed = parse(result.jsonl)
    errors = list(parsed['errors'])
    usage = parsed['usage']
    if result.returncode or result.timed_out:
        errors.append('process_failed')
    if result.wall_seconds > budget.wall_seconds:
        errors.append('wall_budget')
    if usage and usage['input_tokens'] + usage['output_tokens'] > budget.token_cap:
        errors.append('token_budget')
    evidence = None
    receipt = None
    if not errors:
        receipt = submitter.submit_plan(**parsed['arguments'])
        if not receipt['accepted']:
            errors.extend(v['code'] for v in receipt['violations'])
        else:
            evidence = {'jsonl': result.jsonl, 'jsonl_sha256': digest(result.jsonl),
                        'arguments': parsed['arguments'], 'receipt': receipt,
                        'plan': deepcopy(submitter.candidate)}
            errors.extend(audit_provenance(evidence, initial))
    adopted = False
    if not errors:
        try:
            adopted = bool(commit(initial['state_version'], deepcopy(submitter.candidate)))
            if not adopted:
                errors.append('stale_state_version')
        except Exception as exc:
            errors.append('commit_failed:' + str(exc))
    submitter.finalize(process_ok=adopted, usage_known=usage is not None)
    u = usage or {}
    metrics.session(now, input_tokens=u.get('input_tokens', 0), cached_tokens=u.get('cached_input_tokens', 0),
                    output_tokens=u.get('output_tokens', 0), model_seconds=result.model_seconds,
                    wall_seconds=result.wall_seconds, failed=not adopted, usage_known=usage is not None,
                    submit_attempts=int(receipt is not None),
                    submit_rejections=int(receipt is not None and not receipt['accepted']))
    if cycle is not None:
        cost = u.get('input_tokens', 0) - u.get('cached_input_tokens', 0) * (1 - metrics.cached_input_weight)
        cycle.finish(submitted=adopted, process_ok=not errors, usage_known=usage is not None,
                     cost=cost, wall_seconds=result.wall_seconds, model_note=model_note)
    return {'adopted': adopted, 'errors': errors, 'usage_unknown': usage is None, 'evidence': evidence}


def run(runner, argv, prompt, *, budget=Budget(), checkpoint=None,
        inflight_bundle=None, persist_completed=None, **finish_args):
    if checkpoint is not None:
        if inflight_bundle is None or persist_completed is None:
            raise ValueError('durable decision requires in-flight and completed checkpoint')
        checkpoint.mark_inflight(inflight_bundle)
    try:
        result = runner.run(argv, prompt, timeout=budget.wall_seconds)
    except (TimeoutError, OSError):
        result = RunResult('', returncode=1, wall_seconds=budget.wall_seconds, timed_out=True)
    outcome = finish(result, budget=budget, **finish_args)
    if checkpoint is not None:
        persist_completed(outcome)
        checkpoint.clear_inflight()
    return outcome
