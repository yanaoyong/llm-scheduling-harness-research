"""Two capacity treatments; every scheduling and serialization rule is shared."""
from .contracts import default_config, require

POLICY = 'capacity-forecast-collection-wait60-offline-v4'
DEADLINE_POLICY = 'capacity-deadline-collection-offline-v5'
GROUPS = {'G1': (272000, 220000), 'G2': (544000, 440000)}


def experiment_config(group, *, seconds=600, seed=1701):
    window, budget = GROUPS[group]
    cfg = default_config('B', seconds=seconds, seed=seed)
    cfg['semantic_profile_id'] = POLICY
    cfg['period_seconds'] = 60  # compatibility field; NOT a periodic collection clock
    cfg['limits']['context_chars'] = 4000000  # emergency size guard, not the input budget
    cfg['capacity_experiment'] = {
        'policy': POLICY, 'group': group, 'model_context_window': window,
        'input_token_budget': budget, 'wrapper_reserve_tokens': 10000,
        'model_auto_compact_token_limit': window * 9 // 10,
        'tokenizer': 'o200k_base', 'output_reserve_tokens': 32768,
        'history_budget_fraction': 0.10, 'model_calls_enabled': False,
        'collection_max_seconds': None, 'max_ready_wait_seconds': 60,
        'planning_lead_seconds': 15, 'capacity_trigger_fraction': 0.85,
        'forecast_min_interval_seconds': 60, 'forecast_lookahead_seconds': 60,
    }
    return cfg


def deadline_config(group, *, seconds=600, seed=1701):
    """G0 keeps original execution; G1/G2 use deadlines. Presentation is shared."""
    cfg = experiment_config('G1' if group == 'G0' else group, seconds=seconds, seed=seed)
    cfg['semantic_profile_id'] = DEADLINE_POLICY
    cfg['period_seconds'] = 1800  # original boundary; ignored by deadline execution
    cfg['capacity_experiment'].update(
        policy=DEADLINE_POLICY, group=group, execution_rule='original' if group=='G0' else 'deadline',
        max_ready_wait_seconds=0, forecast_lookahead_seconds=None,
        planning_lead_seconds=135, forecast_min_interval_seconds=60,
        decision_budget_seconds=120, publication_budget_seconds=0,
        preparation_budget_seconds=0, deadline_margin_seconds=15,
        deadline_budget_basis='offline provisional; 120 decision + 15 margin; not a measured service guarantee')
    return cfg


def is_original(capacity):
    return (capacity or {}).get('execution_rule') == 'original'


def audit_policy(capacity, anchor):
    keys = ('max_ready_wait_seconds','planning_lead_seconds','input_token_budget','capacity_trigger_fraction',
            'forecast_min_interval_seconds','forecast_lookahead_seconds')
    return {'policy':capacity['policy'],'anchor':anchor,**{k:capacity[k] for k in keys},
            **({'execution_rule':capacity['execution_rule']} if 'execution_rule' in capacity else {})}


def validate_capacity(cfg):
    value = cfg.get('capacity_experiment')
    if value is None:
        return
    require(type(value) is dict, 'capacity_config', 'Capacity settings must be an object')
    modern = value.get('policy') == DEADLINE_POLICY
    require(type(value) is dict and value.get('group') in (('G0','G1','G2') if modern else GROUPS), 'capacity_config', 'Known group required')
    expected = (deadline_config if modern else experiment_config)(value['group'])['capacity_experiment']
    require(type(value.get('model_calls_enabled')) is bool, 'capacity_config', 'Boolean live flag required')
    expected['model_calls_enabled'] = value['model_calls_enabled']
    require(value == expected, 'capacity_config', 'Frozen capacity treatment differs')
    require(cfg['arm'] == 'B' and cfg['period_seconds'] == (1800 if modern else 60) and
            cfg['limits']['context_chars'] == 4000000, 'capacity_config', 'Shared batching/input rules differ')

