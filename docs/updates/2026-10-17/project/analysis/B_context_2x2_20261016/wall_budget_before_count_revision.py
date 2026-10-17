"""Explicit bounded time extensions, without changing the original manifest.

Only a durable third control-revision marker enables the extension. Older
sealed evidence therefore keeps its original budget. Model time and unknown
cost acceptance are unaffected by the third marker. A fourth marker may use
the separately reviewed total 10h wall / 4h model allowance for the same run.
A fifth marker may use the reviewed total 20h wall / 8h model allowance.
"""
from copy import deepcopy
from pathlib import Path

from .contracts import digest, require, strict_json

EXTENSION_SECONDS = 7200
REPAIR = ['approved_same_B_wall_extension']
FILES = {'src/smt_fullfab/harness/wall_budget.py',
         'src/smt_fullfab/harness/source_revision.py',
         'src/smt_fullfab/harness/runtime.py',
         'src/smt_fullfab/harness/experiment.py',
         'src/smt_fullfab/harness/evaluation.py'}
TIME_REPAIR = ['approved_same_B_time_extension']
TIME_FILES = {'src/smt_fullfab/harness/wall_budget.py',
              'src/smt_fullfab/harness/source_revision.py',
              'src/smt_fullfab/harness/evaluation.py'}
TOTAL_WALL_EXTENSION_SECONDS = 21600
MODEL_EXTENSION_SECONDS = 3600
RUNWAY_REPAIR = ['approved_same_B_time_runway_extension']
RUNWAY_FILES = {'src/smt_fullfab/harness/wall_budget.py',
                'src/smt_fullfab/harness/source_revision.py'}
RUNWAY_WALL_EXTENSION_SECONDS = 57600
RUNWAY_MODEL_EXTENSION_SECONDS = 18000
POST_NETWORK_REPAIR = ['approved_same_B_post_network_time_allowance']
POST_NETWORK_FILES = {'src/smt_fullfab/harness/wall_budget.py',
                      'src/smt_fullfab/harness/source_revision.py',
                      'src/smt_fullfab/harness/user_managed_network.py'}


def validate_post_network_grant(grant, manifest):
    require(grant['schema'] == 'harness-post-network-time-authorization-v1'
            and grant['user_instruction'] == '如何继续，批准需要的预算以及可能超标的预算'
            and grant['network_instruction'] == '不要管网络的问题了，我会人为的管理切换的'
            and grant['run_id'] == manifest['run_id']
            and grant['original_created_epoch'] == manifest['created_epoch']
            and grant['original_deadline_epoch'] == manifest['deadline_epoch']
            and grant['same_run_only'] is True and grant['preserve_all_costs_and_results'] is True
            and all(grant[k] is False for k in ('new_B_start','reset_time','reset_costs','change_model','change_production_decisions','change_network'))
            and grant['additional_wall_seconds'] == 21600 and grant['additional_model_seconds'] == 7200
            and grant['limits_before']['wall_seconds'] == 72000
            and grant['limits_before']['model_seconds'] == 28800
            and grant['limits_after'] == {**grant['limits_before'], 'wall_seconds':93600, 'model_seconds':36000},
            'post_network_time_grant', 'Bounded previously authorized allowance must preserve identity, clocks and every other limit')
    return grant


def validate_grant(grant, manifest, reg):
    before = manifest['config']['limits']
    after = {**before, 'wall_seconds': before['wall_seconds'] + EXTENSION_SECONDS}
    caps = deepcopy(reg['caps'])
    for group in ('B3600', 'combined'):
        caps[group]['wall_seconds'] += EXTENSION_SECONDS
    require(grant['schema'] == 'harness-user-B-wall-extension-v1'
            and grant['user_budget_instruction'] == '如何继续，批准需要的预算以及可能超标的预算'
            and grant['user_continuation_instruction'] == '取消异常额度这些限制，你的目标是不浪费的情况下测试推进B'
            and grant['registration_sha256'] == digest(reg) == manifest['admission']['experiment_sha256']
            and manifest['admission']['group'] == 'B3600'
            and grant['run_id'] == manifest['run_id']
            and grant['manifest_sha256'] == digest(manifest)
            and grant['same_run_only'] is True and grant['preserve_all_costs_and_results'] is True
            and grant['increase_limits'] is True and grant['strict_zero_unknown_audit_unchanged'] is True
            and all(grant[k] is False for k in ('new_B_start', 'reset_time', 'change_model', 'change_production_decisions'))
            and type(grant['wall_extension_seconds']) is int
            and grant['wall_extension_seconds'] == EXTENSION_SECONDS
            and before['wall_seconds'] == 14400 and before['model_seconds'] == 10800
            and manifest['deadline_epoch'] == manifest['created_epoch'] + before['wall_seconds']
            and grant['limits_before'] == before and grant['limits_after'] == after
            and grant['shared_caps_before'] == reg['caps'] and grant['shared_caps_after'] == caps,
            'wall_budget_grant', 'Only one bounded wall extension of this exact B is authorized')
    return grant


def _registered_revision(manifest):
    from .experiment import checked_file
    root = Path(manifest['admission']['experiment_directory'])
    reg = checked_file({'path': str(root / 'experiment.json'),
                        'sha256': manifest['admission']['experiment_sha256']})
    return strict_json((root / 'source_revision_3.json').read_bytes()), reg


def _registered_time_revision(manifest):
    root = Path(manifest['admission']['experiment_directory'])
    return strict_json((root / 'source_revision_4.json').read_bytes())


def validate_time_grant(grant, manifest, reg, previous):
    """Only this exact additional 4h wall / 1h model grant may follow revision 3."""
    from .experiment import checked_file
    require(previous['repairs'] == REPAIR, 'time_budget_grant', 'Retained wall grant required')
    validate_grant(checked_file(previous['user_authorization']), manifest, reg)
    original = manifest['config']['limits']
    before = {**original, 'wall_seconds': original['wall_seconds'] + EXTENSION_SECONDS}
    after = {**original, 'wall_seconds': original['wall_seconds'] + TOTAL_WALL_EXTENSION_SECONDS,
             'model_seconds': original['model_seconds'] + MODEL_EXTENSION_SECONDS}
    caps_before, caps_after = deepcopy(reg['caps']), deepcopy(reg['caps'])
    for group in ('B3600', 'combined'):
        caps_before[group]['wall_seconds'] += EXTENSION_SECONDS
        caps_after[group]['wall_seconds'] += TOTAL_WALL_EXTENSION_SECONDS
        caps_after[group]['model_seconds'] += MODEL_EXTENSION_SECONDS
    require(grant['schema'] == 'harness-user-B-time-extension-v1'
            and grant['user_budget_instruction'] == '如何继续，批准需要的预算以及可能超标的预算'
            and grant['user_continuation_instruction'] == '取消异常额度这些限制，你的目标是不浪费的情况下测试推进B'
            and grant['registration_sha256'] == digest(reg) == manifest['admission']['experiment_sha256']
            and manifest['admission']['group'] == 'B3600'
            and grant['run_id'] == manifest['run_id'] and grant['manifest_sha256'] == digest(manifest)
            and grant['previous_source_revision_sha256'] == digest(previous)
            and grant['same_run_only'] is True and grant['preserve_all_costs_and_results'] is True
            and grant['increase_limits'] is True and grant['strict_zero_unknown_audit_unchanged'] is True
            and all(grant[k] is False for k in ('new_B_start', 'reset_time', 'change_model', 'change_production_decisions'))
            and type(grant['wall_extension_seconds']) is int
            and type(grant['additional_wall_seconds']) is int and type(grant['model_extension_seconds']) is int
            and grant['wall_extension_seconds'] == TOTAL_WALL_EXTENSION_SECONDS
            and grant['additional_wall_seconds'] == TOTAL_WALL_EXTENSION_SECONDS - EXTENSION_SECONDS
            and grant['model_extension_seconds'] == MODEL_EXTENSION_SECONDS
            and grant['limits_original'] == original and grant['limits_before'] == before
            and grant['limits_after'] == after and grant['shared_caps_before'] == caps_before
            and grant['shared_caps_after'] == caps_after,
            'time_budget_grant', 'Only the exact bounded same-run time allowance is authorized')
    return grant


def _registered_runway_revision(manifest):
    root = Path(manifest['admission']['experiment_directory'])
    return strict_json((root / 'source_revision_5.json').read_bytes())


def validate_runway_grant(grant, manifest, reg, previous):
    """A bounded additional 10h wall / 4h model grant after revision 4 only."""
    from .experiment import checked_file
    require(previous['repairs'] == TIME_REPAIR, 'time_runway_grant', 'Retained fourth time grant required')
    validate_time_grant(checked_file(previous['user_authorization']), manifest, reg,
                        checked_file(previous['previous_source_revision']))
    original = manifest['config']['limits']
    before = {**original, 'wall_seconds': original['wall_seconds'] + TOTAL_WALL_EXTENSION_SECONDS,
              'model_seconds': original['model_seconds'] + MODEL_EXTENSION_SECONDS}
    after = {**original, 'wall_seconds': original['wall_seconds'] + RUNWAY_WALL_EXTENSION_SECONDS,
             'model_seconds': original['model_seconds'] + RUNWAY_MODEL_EXTENSION_SECONDS}
    caps_before, caps_after = deepcopy(reg['caps']), deepcopy(reg['caps'])
    for group in ('B3600', 'combined'):
        caps_before[group]['wall_seconds'] += TOTAL_WALL_EXTENSION_SECONDS
        caps_before[group]['model_seconds'] += MODEL_EXTENSION_SECONDS
        caps_after[group]['wall_seconds'] += RUNWAY_WALL_EXTENSION_SECONDS
        caps_after[group]['model_seconds'] += RUNWAY_MODEL_EXTENSION_SECONDS
    require(grant['schema'] == 'harness-user-B-time-runway-extension-v1'
            and grant['user_budget_instruction'] == '如何继续，批准需要的预算以及可能超标的预算'
            and grant['user_continuation_instruction'] == '取消异常额度这些限制，你的目标是不浪费的情况下测试推进B'
            and grant['registration_sha256'] == digest(reg) == manifest['admission']['experiment_sha256']
            and manifest['admission']['group'] == 'B3600'
            and grant['run_id'] == manifest['run_id'] and grant['manifest_sha256'] == digest(manifest)
            and grant['previous_source_revision_sha256'] == digest(previous)
            and grant['same_run_only'] is True and grant['preserve_all_costs_and_results'] is True
            and grant['increase_limits'] is True and grant['strict_zero_unknown_audit_unchanged'] is True
            and all(grant[k] is False for k in ('new_B_start', 'reset_time', 'change_model', 'change_production_decisions'))
            and all(type(grant[k]) is int for k in ('wall_extension_seconds', 'additional_wall_seconds',
                                                  'model_extension_seconds', 'additional_model_seconds'))
            and grant['wall_extension_seconds'] == RUNWAY_WALL_EXTENSION_SECONDS
            and grant['additional_wall_seconds'] == RUNWAY_WALL_EXTENSION_SECONDS - TOTAL_WALL_EXTENSION_SECONDS
            and grant['model_extension_seconds'] == RUNWAY_MODEL_EXTENSION_SECONDS
            and grant['additional_model_seconds'] == RUNWAY_MODEL_EXTENSION_SECONDS - MODEL_EXTENSION_SECONDS
            and grant['limits_original'] == original and grant['limits_before'] == before
            and grant['limits_after'] == after and grant['shared_caps_before'] == caps_before
            and grant['shared_caps_after'] == caps_after,
            'time_runway_grant', 'Only the exact bounded fifth same-run time allowance is authorized')
    return grant


def effective_budget(manifest, markers):
    """Read immutable, hash-bound policy; never cache mutable usage or clocks."""
    limits = deepcopy(manifest['config']['limits'])
    original = limits['wall_seconds']
    result = {'limits': limits, 'original_wall_seconds': original,
              'wall_extension_seconds': 0, 'effective_deadline_epoch': manifest['deadline_epoch'],
              'source_revision_sha256': None}
    row = markers.get('wall-budget')
    if row is None:
        require('time-budget' not in markers and 'time-runway-budget' not in markers and 'post-network-time' not in markers,
                'time_budget_marker', 'Later time markers cannot skip the third')
        return result
    from .experiment import checked_file
    revision, reg = _registered_revision(manifest)
    require(revision['repairs'] == REPAIR and digest(revision) == row['revision_sha256']
            and row['boundary'] == revision['boundary'] and row['new_model_calls'] == 0
            and row['source_before'] == revision['base_source_sha256']
            and row['source_after'] == revision['active_fingerprint_sha256'],
            'wall_budget_marker', 'Wall allowance requires the registered source boundary')
    boundary = checked_file(revision['boundary'])
    require(row['head_before'] == boundary['head']
            and checked_file(boundary['manifest']) == manifest,
            'wall_budget_marker', 'Wall allowance belongs to another checkpoint')
    grant = validate_grant(checked_file(revision['user_authorization']), manifest, reg)
    limits['wall_seconds'] += grant['wall_extension_seconds']
    result.update(wall_extension_seconds=grant['wall_extension_seconds'],
                  effective_deadline_epoch=manifest['deadline_epoch'] + grant['wall_extension_seconds'],
                  source_revision_sha256=digest(revision))
    time_row = markers.get('time-budget')
    require(time_row is not None or 'time-runway-budget' not in markers,
            'time_runway_marker', 'Fifth marker cannot skip the fourth')
    if time_row is not None:
        time_revision = _registered_time_revision(manifest)
        require(time_revision['repairs'] == TIME_REPAIR and digest(time_revision) == time_row['revision_sha256']
                and checked_file(time_revision['previous_source_revision']) == revision
                and time_row['boundary'] == time_revision['boundary'] and time_row['new_model_calls'] == 0
                and time_row['source_before'] == time_revision['base_source_sha256']
                and time_row['source_after'] == time_revision['active_fingerprint_sha256'],
                'time_budget_marker', 'Time allowance requires the registered fourth boundary')
        time_boundary = checked_file(time_revision['boundary'])
        require(time_row['head_before'] == time_boundary['head']
                and checked_file(time_boundary['manifest']) == manifest,
                'time_budget_marker', 'Time allowance belongs to another checkpoint')
        time_grant = validate_time_grant(checked_file(time_revision['user_authorization']), manifest, reg, revision)
        result.update(limits=deepcopy(time_grant['limits_after']),
                      original_model_seconds=manifest['config']['limits']['model_seconds'],
                      model_extension_seconds=time_grant['model_extension_seconds'],
                      wall_extension_seconds=time_grant['wall_extension_seconds'],
                      effective_deadline_epoch=manifest['deadline_epoch'] + time_grant['wall_extension_seconds'],
                      source_revision_sha256=digest(time_revision))
    runway_row = markers.get('time-runway-budget')
    if runway_row is not None:
        runway_revision = _registered_runway_revision(manifest)
        require(runway_revision['repairs'] == RUNWAY_REPAIR and digest(runway_revision) == runway_row['revision_sha256']
                and checked_file(runway_revision['previous_source_revision']) == time_revision
                and runway_row['boundary'] == runway_revision['boundary'] and runway_row['new_model_calls'] == 0
                and runway_row['source_before'] == runway_revision['base_source_sha256']
                and runway_row['source_after'] == runway_revision['active_fingerprint_sha256'],
                'time_runway_marker', 'Time allowance requires the registered fifth boundary')
        runway_boundary = checked_file(runway_revision['boundary'])
        require(runway_row['head_before'] == runway_boundary['head']
                and checked_file(runway_boundary['manifest']) == manifest,
                'time_runway_marker', 'Time allowance belongs to another checkpoint')
        runway_grant = validate_runway_grant(checked_file(runway_revision['user_authorization']),
                                           manifest, reg, time_revision)
        result.update(limits=deepcopy(runway_grant['limits_after']),
                      original_model_seconds=manifest['config']['limits']['model_seconds'],
                      model_extension_seconds=runway_grant['model_extension_seconds'],
                      wall_extension_seconds=runway_grant['wall_extension_seconds'],
                      effective_deadline_epoch=manifest['deadline_epoch'] + runway_grant['wall_extension_seconds'],
                      source_revision_sha256=digest(runway_revision))
    post_row = markers.get('post-network-time')
    if post_row is not None:
        require(runway_row is not None and 'user-managed-network' in markers,
                'post_network_time_marker', 'Allowance follows original runway and network handoff')
        from .source_revision import for_amendment
        from .amendment import amendment_for
        post = for_amendment(reg, amendment_for(reg))
        require(post['repairs'] == POST_NETWORK_REPAIR and digest(post) == post_row['revision_sha256']
                and post_row['new_model_calls'] == 0 and post_row['boundary'] == post['boundary']
                and post_row['source_before'] == post['base_source_sha256']
                and post_row['source_after'] == post['active_fingerprint_sha256'],
                'post_network_time_marker', 'Exact reviewed same-run allowance marker required')
        bound = checked_file(post['boundary'])
        require(post_row['head_before'] == bound['head'] and checked_file(bound['manifest']) == manifest,
                'post_network_time_boundary', 'Original checkpoint and manifest required')
        grant = validate_post_network_grant(checked_file(post['user_authorization']), manifest)
        require(result['limits'] == grant['limits_before'], 'post_network_time_limits', 'Earlier limits changed')
        result.update(limits=deepcopy(grant['limits_after']),
                      wall_extension_seconds=result['wall_extension_seconds']+21600,
                      model_extension_seconds=result['model_extension_seconds']+7200,
                      effective_deadline_epoch=result['effective_deadline_epoch']+21600,
                      source_revision_sha256=digest(post))
    return result


def shared_caps(reg, budget):
    caps = deepcopy(reg['caps'])
    for group in ('B3600', 'combined'):
        caps[group]['wall_seconds'] += budget['wall_extension_seconds']
        caps[group]['model_seconds'] += budget.get('model_extension_seconds', 0)
    return caps
