"""One bounded paired live pilot, separate from historical B registrations.

No scheduling policy, credential storage, retries, or original-run access.
The user-authorized registration binds both configs, source, saved state, CLI,
catalog and the shared observation cutoff before either run is created.
"""
from pathlib import Path
import time

from .contracts import ROOT, digest, encode, require, sha_bytes, strict_json
from .offline_isolation import local_path

SCHEMA = 'capacity-paired-live-pilot-v1'
INSTRUCTION = '那就在独立副本里做一轮小规模实际模型对比，两组使用相同的保存状态和负载，重点看总调用次数、未处理需求、机组等待和排程质量，不要动原B。'
TWO_STRATEGY_INSTRUCTION = '那就在独立副本里做一轮小规模实际模型对比，两组使用相同的保存状态和负载，重点看总调用次数、未处理需求、机组等待和排程质量，以及是否还会频繁重排，不要动原B。'
FORECAST_COLLECTION_INSTRUCTION = '那就在独立副本里再做一轮小规模实际模型对比，两组使用相同的保存状态、负载和观察区间，重点看总调用次数、未处理需求、机组等待、排程质量，以及是否还会频繁重排。生产任务仍全部由模型选择，不要动原B。还有要和之前对比一下。'
DEADLINE_INSTRUCTION = '那就在独立副本里做一轮 G0、G1、G2 的小规模实际模型对比，使用相同保存状态、负载和观察区间，比较总调用次数、未处理需求、机组等待、排程质量和重排频率，并和上一轮结果对比。生产任务仍全部由模型选择，不要动原 B。'
EXTENDED_INSTRUCTION = '那就把观察区间延长一些，在独立副本里继续比较 G0、G1、G2，看看提前安排的后续任务能不能减少后面的调用，同时比较未处理需求、机组等待、排程质量和重排频率。三组使用相同保存状态、负载和观察区间，生产任务仍全部由模型选择，不要动原 B。'


def is_pilot(admission):
    return isinstance(admission, dict) and admission.get('schema') == SCHEMA


def registration(admission, *, config=None):
    require(is_pilot(admission), 'pilot_admission', 'Frozen pilot admission required')
    root = local_path(admission['experiment_directory'])
    require(root.is_relative_to(ROOT / 'live_pilots'), 'pilot_path', 'Dedicated local pilot root required')
    value = strict_json((root / 'registration.json').read_bytes())
    require(digest(value) == admission['experiment_sha256'] and value['schema'] == SCHEMA,
            'pilot_registration', 'Registration changed')
    require(value['user_instruction'] in (INSTRUCTION, TWO_STRATEGY_INSTRUCTION, FORECAST_COLLECTION_INSTRUCTION, DEADLINE_INSTRUCTION, EXTENDED_INSTRUCTION) and value['model_calls_authorized'] is True,
            'pilot_authorization', 'Explicit live-pilot instruction required')
    extended = value['user_instruction'] == EXTENDED_INSTRUCTION
    deadline = value['user_instruction'] in (DEADLINE_INSTRUCTION, EXTENDED_INSTRUCTION)
    require(value['experiment_directory'] == str(root) and value['groups'] == (['G0','G1','G2'] if deadline else ['G1','G2']),
            'pilot_registration', 'Group set differs from explicit authorization')
    extended_cap = 28
    if extended and value.get('resource_continuation') is not None:
        resource = value['resource_continuation']
        require((resource.get('from_cap'), resource.get('to_cap')) in ((28, 64), (64, 96))
                and resource.get('target_unchanged') == 1800
                and set(resource.get('predecessors', {})) == {'G0', 'G1', 'G2'},
                'pilot_resources', 'Only preserved 28 to 64 or 64 to 96 call allowance continuations are supported')
        extended_cap = resource['to_cap']
    if extended:
        require(value.get('per_group_call_cap')==extended_cap and value.get('model_calls_maximum_total')==3*extended_cap
                and value.get('evaluation_end')==1800 and value.get('extension_start')==882
                and set(value.get('predecessors',{}))=={'G0','G1','G2'},
                'pilot_bounds', 'Only the registered 882 to 1800 continuation is authorized')
    elif deadline:
        require(value.get('per_group_call_cap')==8 and value.get('model_calls_maximum_total')==24
                and value.get('evaluation_end')==882, 'pilot_bounds', 'Only the bounded three-group observation is authorized')
    group = admission['group']
    require(group in value['groups'], 'pilot_group', 'Unknown group')
    for key in ('cli_binary', 'cli_sha256', 'model_catalog', 'model_catalog_sha256'):
        require(admission[key] == value[key], 'pilot_binding', key)
    local_path(value['model_catalog'])
    if config is not None:
        require(digest(config) == value['config_sha256'][group], 'pilot_config', 'Configuration differs from registration')
        from .capacity_config import DEADLINE_POLICY
        cap=config.get('capacity_experiment') or {}
        require((cap.get('policy')==DEADLINE_POLICY)==deadline, 'pilot_policy', 'Deadline policy requires its own current authorization')
        if deadline:
            require(cap.get('group')==group and cap.get('execution_rule')==('original' if group=='G0' else 'deadline')
                    and config['limits']['attempts']==(extended_cap if extended else 8), 'pilot_treatment', 'Frozen treatment/call limit differs')
    return value


def validate_admission(admission, fingerprint, config, initial):
    value = registration(admission, config=config)
    require(value['user_instruction'] != EXTENDED_INSTRUCTION, 'pilot_continuation',
            'Extended pilots must import their sealed predecessor, not restart from initial state')
    require(value['fingerprint_sha256'] == fingerprint['sha256'], 'pilot_source', 'Frozen source changed')
    require(initial is not None and digest(initial['state']) == value['initial_state_sha256']
            and digest(initial['trace']) == value['initial_trace_sha256'], 'pilot_initial', 'Initial snapshot/prefix differs')
    require(initial['state']['t'] < value['evaluation_end'] <= initial['state']['horizon'],
            'pilot_cutoff', 'Cutoff outside original simulation horizon')
    require(config['unknown_usage_policy'] == 'freeze_new_calls' and config['fallback'] == 'none'
            and config['model']['automatic_retries'] == 0, 'pilot_policy', 'No retries or fallback authorized')


def register_run(runtime):
    admission = runtime.manifest['admission']
    value = registration(admission, config=runtime.config)
    root = local_path(value['experiment_directory'])
    require(runtime.store.path.resolve() == root / admission['group'], 'pilot_run_path', 'Exact group directory required')
    # Exclusive creation prevents restarting a group to discard earlier costs.
    with (root / (admission['group'] + '.started.json')).open('xb') as stream:
        stream.write(encode({'run_id': runtime.manifest['run_id'], 'directory': str(runtime.store.path)}))


def check_budget(runtime):
    from .offline_isolation import authorize_model
    authorize_model(runtime.config, runtime.manifest.get('admission'))
    value = registration(runtime.manifest['admission'], config=runtime.config)
    require(runtime.manifest['fingerprint']['sha256'] == value['fingerprint_sha256'],
            'pilot_source', 'Run must use registered source')
    require(runtime.env.t < value['evaluation_end'], 'pilot_complete', 'Observation cutoff reached')
    root = local_path(value['experiment_directory'])
    started = strict_json((root / (runtime.manifest['admission']['group'] + '.started.json')).read_bytes())
    require(started['run_id'] == runtime.manifest['run_id'] and local_path(started['directory']) == runtime.store.path,
            'pilot_identity', 'Group already belongs to another run')
    return value


def evaluation_end(manifest, horizon):
    admission = manifest.get('admission')
    return min(horizon, registration(admission)['evaluation_end']) if is_pilot(admission) else horizon


def prepare_request(runtime, *, task=None):
    from .transport import prompt, response_schema
    from .contracts import encode_model_schema
    from .local_tokens import count
    check_budget(runtime)
    text = prompt(runtime, task=task)
    current = runtime.head['context_ref']
    previous = [ref for ref, _ in runtime.store.rows('contexts') if ref != current]
    candidates = [ref for ref, c in runtime.store.rows('candidates') if c['context_ref'] == current]
    draft = any(d['context_ref'] == current and not d['sealed'] for _, d in runtime.store.rows('drafts'))
    schema = response_schema('B', comparison_context_refs=previous, candidate_refs=candidates, has_open_draft=draft,
                             planning_reviews=bool(runtime.config.get('capacity_experiment')))
    from .transport import BASE_INSTRUCTIONS
    wrapper = count(encode_model_schema(schema).decode()) + count(BASE_INSTRUCTIONS)
    require(wrapper < runtime.config['capacity_experiment']['wrapper_reserve_tokens'],
            'pilot_wrapper', 'Measured schema/system exceed the reserved wrapper budget')
    aid = runtime.reserve_attempt(text, schema)
    with runtime.store.transaction():
        runtime.store.record('pilot_packet_measurements', aid, {
            **runtime.last_capacity_measurement, 'schema_and_system_tokens': wrapper,
            'measured_epoch': time.time(), 'server_tokenizer_verified': False})
    # Existing transport uses the user's loopback proxy, without altering host settings.
    return None, text, schema, aid
