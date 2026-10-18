"""Preregistration gates. Unfilled quality/budget fields cannot authorize results."""
import math
from pathlib import Path
from .contracts import strict_json
from .groups import GROUPS, validate_mapping
LABEL='非模型、仅机制测试'

def validate(value, *, results=False):
    errors=[]
    def check(ok,name):
        if not ok: errors.append(name)
    def positive(x): return type(x) in (int,float) and math.isfinite(x) and x>0
    check(value.get('snapshot_format') in ('explicit', 'dense'), 'snapshot_format')
    check(value.get('stage') in ('S0','S1','S2','S3','S4'),'stage')
    check(positive(value.get('delta_seconds')),'delta_seconds')
    check(positive(value.get('horizon_seconds')),'horizon_seconds')
    check(value.get('primary_metrics')==['uncached_equivalent_input_tokens_per_sim_hour','model_request_lower_bound_per_sim_hour'],'primary_metrics')
    groups = value.get('groups', [])
    if not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
        errors.append('groups')
        groups = []
    check(isinstance(groups, list) and bool(groups) and all(g in GROUPS for g in groups)
          and len(set(groups)) == len(groups), 'groups')
    mappings = value.get('group_configs', {})
    if not isinstance(mappings, dict):
        errors.append('group_configs')
        mappings = {}
    for group in groups:
        check(validate_mapping(group, mappings.get(group, {})), 'group_config:' + group)
    check(positive(value.get('delta_min_seconds')), 'delta_min_seconds')
    f=value.get('failure',{})
    check(f.get('keep_old_plan') is True and f.get('adopt_crashed_submission') is False and f.get('retry') is False,'failure_semantics')
    check(type(f.get('k_fail')) is int and f['k_fail']>0,'k_fail')
    check(type(f.get('unknown_usage_cap')) is int and f['unknown_usage_cap']>0,'unknown_usage_cap')
    check(value.get('counting_basis')=='cumulative_session_usage; requests >= tool_rounds + 1','counting_basis')
    check(type(value.get('cached_input_weight')) in (int,float) and 0<=value['cached_input_weight']<=1,'cache_weight')
    window=value.get('steady_state_window',{})
    check(type(window.get('exclude_first_hours')) in (int,float) and window['exclude_first_hours']>=0,'steady_state_window')
    if value.get('dry_run'):
        check(value.get('plan_source')=='scripted' and value.get('label')==LABEL,'dry_run_label')
        check(not results and value.get('is_result') is False,'scripted_not_results')
    else:
        check(value.get('plan_source')=='model','model_source')
    if results or not value.get('dry_run'):
        check(positive(value.get('per_sim_hour_token_cap')),'token_cap')
        check(positive(value.get('per_sim_hour_request_cap')),'request_cap')
        q=value.get('quality',{})
        for key in ('weighted_tardiness','throughput','avoidable_idle_integral'):
            row=q.get(key,{})
            check(type(row.get('floor')) in (int,float) and math.isfinite(row['floor']),'quality_floor:'+key)
            check(type(row.get('tolerance')) in (int,float) and math.isfinite(row['tolerance']) and row['tolerance']>=0,'quality_tolerance:'+key)
    return errors

def load(path, *, results=False):
    value=strict_json(Path(path).read_bytes());errors=validate(value,results=results)
    if errors: raise ValueError(errors)
    return value
