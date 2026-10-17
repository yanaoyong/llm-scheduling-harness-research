"""Explicit same-run handoff of network management to the user.

No controller calls, node changes, connectivity probes or network persistence.
Earlier attempts retain their original binding. Later attempts record this
declared policy; they make no claim about an unobserved physical route.
"""
from pathlib import Path
from .contracts import digest, require, sha_bytes

REPAIR = ['user_managed_network_continuation']
FILES = {'src/smt_fullfab/harness/user_managed_network.py',
         'src/smt_fullfab/harness/network.py',
         'src/smt_fullfab/harness/source_revision.py',
         'src/smt_fullfab/harness/evaluation.py'}


def validate_grant(grant):
    require(grant['schema'] == 'harness-user-managed-network-authorization-v1'
            and grant['user_instruction'] == '不要管网络的问题了，我会人为的管理切换的'
            and grant['initial_network_instruction'] == '改用日本 aws 优化线路，记录网络配置变更后续跑'
            and grant['same_run_only'] is True and grant['preserve_all_costs_and_results'] is True
            and all(grant[k] is False for k in ('assistant_changes_network', 'node_pin_enforced',
                 'route_continuity_claim', 'new_B_start', 'reset_time', 'change_model',
                 'change_production_decisions', 'increase_limits')),
            'network_handoff_grant', 'Explicit user-managed same-run network authorization required')
    return grant


def reference(reg, admission, *, attempt=None, run_id=None):
    from .experiment import checked_file
    original = reg.get('transport_proxy')
    if admission.get('case_id') != 'B3600' or not (Path(reg['experiment_directory'])/'source_revision_8.json').exists():
        return original
    # for_admission supplies the already validated registration. Read its
    # immutable handoff directly rather than rewalking every prior revision
    # inside each historical cost audit. No live state or usage is cached.
    path = Path(reg['experiment_directory'])/'source_revision_8.json'
    revision = checked_file({'path': str(path), 'sha256': sha_bytes(path.read_bytes())})
    require(revision['repairs'] == REPAIR, 'network_handoff_source', 'Reviewed network handoff required')
    boundary = checked_file(revision['boundary'])
    grant = validate_grant(checked_file(revision['user_authorization']))
    if attempt is not None and (run_id != boundary['run_id'] or attempt['index'] < boundary['actual_attempts']):
        return original
    return {'mode': 'user_managed_host_network',
            'source_revision': {'path': str(path), 'sha256': sha_bytes(path.read_bytes())},
            'authorization': revision['user_authorization'],
            'run_id': boundary['run_id'], 'first_actual_call': boundary['actual_attempts']+1,
            'original_binding': original,
            'initial_user_selected_label': grant['initial_user_selected_label'],
            'live_route_sampled': False, 'route_continuity_claim': False,
            'assistant_changes_network': False, 'environment_policy': 'inherit_user_managed_host'}


def validate_reference(value):
    from .experiment import checked_file
    revision = checked_file(value['source_revision'])
    boundary = checked_file(revision['boundary'])
    require(revision['repairs'] == REPAIR and value['authorization'] == revision['user_authorization']
            and value['run_id'] == boundary['run_id']
            and value['first_actual_call'] == boundary['actual_attempts']+1
            and value['environment_policy'] == 'inherit_user_managed_host'
            and all(value[k] is False for k in ('live_route_sampled', 'route_continuity_claim', 'assistant_changes_network')),
            'network_handoff_reference', 'Recorded network policy differs from its frozen handoff')
    validate_grant(checked_file(value['authorization']))
    return value
