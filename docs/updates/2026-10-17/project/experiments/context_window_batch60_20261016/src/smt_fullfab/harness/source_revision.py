"""Versioned presentation/validation repair of an unsealed B checkpoint."""
from pathlib import Path
import sqlite3
import time

from .contracts import digest, require, strict_json

SCHEMA = 'harness-live-control-source-revision-v1'
FACT_REPAIR = ['lossless_same_context_fact_retention']
FACT_FILES = {'src/smt_fullfab/harness/fact_memory.py', 'src/smt_fullfab/harness/transport.py',
              'src/smt_fullfab/harness/source_revision.py'}
FILES = {'src/smt_fullfab/harness/transport.py', 'src/smt_fullfab/harness/experiment.py',
         'src/smt_fullfab/harness/amendment.py', 'src/smt_fullfab/harness/source_revision.py'}


def validate(value, reg, base, *, _depth=0):
    from .experiment import checked_file
    from .amendment import _source_proof
    require(value['schema'] == SCHEMA and base is not None
            and base['schema'] == 'harness-B-exception-quota-removal-v1'
            and value['registration_sha256'] == digest(reg)
            and value['base_amendment_sha256'] == digest(base),
            'source_revision', 'Wrong original B or control boundary')
    require(_depth < 10, 'source_revision_chain', 'At most ten reviewed revisions')
    from .wall_budget import REPAIR as WALL_REPAIR, FILES as WALL_FILES, validate_grant
    from .wall_budget import TIME_REPAIR, TIME_FILES, validate_time_grant
    from .wall_budget import RUNWAY_REPAIR, RUNWAY_FILES, validate_runway_grant
    wall_extension = value['repairs'] == WALL_REPAIR
    time_extension = value['repairs'] == TIME_REPAIR
    runway_extension = value['repairs'] == RUNWAY_REPAIR
    from .transport_requalification import REPAIR as QUAL_REPAIR, FILES as QUAL_FILES
    requalification = value['repairs'] == QUAL_REPAIR
    from .user_managed_network import REPAIR as NETWORK_REPAIR, FILES as NETWORK_FILES, validate_grant as validate_network_grant
    user_network = value['repairs'] == NETWORK_REPAIR
    from .wall_budget import POST_NETWORK_REPAIR, POST_NETWORK_FILES, validate_post_network_grant
    post_network = value['repairs'] == POST_NETWORK_REPAIR
    from .transport_error_alias import REPAIR as ALIAS_REPAIR, FILES as ALIAS_FILES
    from .transport_error_alias import validate_boundary as validate_alias_boundary
    error_alias = value['repairs'] == ALIAS_REPAIR
    fact_retention = value['repairs'] == FACT_REPAIR
    previous = None
    if value.get('previous_source_revision'):
        previous = checked_file(value['previous_source_revision'])
        validate(previous, reg, base, _depth=_depth+1)
        require((error_alias and previous['repairs'] == POST_NETWORK_REPAIR) or
                (post_network and previous['repairs'] == NETWORK_REPAIR) or
                (user_network and previous['repairs'] == QUAL_REPAIR) or
                (requalification and previous['repairs'] == FACT_REPAIR) or
                (fact_retention and previous['repairs'] == RUNWAY_REPAIR) or
                (runway_extension and previous['repairs'] == TIME_REPAIR) or
                (time_extension and previous['repairs'] == WALL_REPAIR) or
                (wall_extension and previous['repairs'] == ['scoped_request_preparation_validation']
                 and previous.get('previous_source_revision')) or
                (not error_alias and not post_network and not user_network and not requalification and not fact_retention and not wall_extension and not time_extension and not runway_extension and not previous.get('previous_source_revision')
                 and value['repairs'] == ['scoped_request_preparation_validation']),
                'source_revision_chain', 'Only the explicit reviewed repair sequence is permitted')
    origin = previous or base
    require(value['base_source_sha256'] == origin['active_fingerprint_sha256'],
            'source_revision_chain', 'Source ancestry differs')
    grant = checked_file(value['user_authorization'])
    if user_network:
        validate_network_grant(grant)
    require(error_alias or post_network or user_network or wall_extension or time_extension or runway_extension or (grant['user_instruction'] == '取消异常额度这些限制，你的目标是不浪费的情况下测试推进B'
            and grant['same_run_only'] is True and grant['preserve_all_costs_and_results'] is True
            and all(grant[k] is False for k in ('new_B_start', 'reset_time', 'change_model',
                                               'change_production_decisions', 'increase_limits'))
            and (previous is not None or value['repairs'] == ['lossless_oversized_trigger', 'scoped_registration_validation'])),
            'source_revision_grant', 'Only lossless presentation and repeated validation may change')
    prior = {**reg, 'engineering_report':origin['engineering_report']['path'],
             'engineering_report_sha256':origin['engineering_report']['sha256'],
             'fingerprint_sha256':origin['active_fingerprint_sha256']}
    _source_proof(value, prior, allowed_files=ALIAS_FILES if error_alias else POST_NETWORK_FILES if post_network else NETWORK_FILES if user_network else QUAL_FILES if requalification else FACT_FILES if fact_retention else RUNWAY_FILES if runway_extension else TIME_FILES if time_extension else WALL_FILES if wall_extension else FILES)
    boundary = checked_file(value['boundary'])
    manifest = checked_file(boundary['manifest'])
    if error_alias:
        require(previous is not None and previous['repairs'] == POST_NETWORK_REPAIR,
                'source_revision_chain', 'The exact ninth revision must precede the alias repair')
        validate_alias_boundary(boundary, manifest, grant)
    if post_network:
        validate_post_network_grant(grant, manifest)
    if wall_extension:
        require(previous is not None, 'source_revision_chain', 'Wall extension must follow both retained repairs')
        validate_grant(grant, manifest, reg)
    if time_extension:
        require(previous is not None, 'source_revision_chain', 'Time extension must follow the wall revision')
        validate_time_grant(grant, manifest, reg, previous)
    if runway_extension:
        require(previous is not None, 'source_revision_chain', 'Fifth time extension must follow the fourth revision')
        validate_runway_grant(grant, manifest, reg, previous)
    require(boundary['schema'] == 'harness-unsealed-control-boundary-v1'
            and boundary['registration_sha256'] == digest(reg)
            and boundary['run_id'] == manifest['run_id'] == grant['run_id']
            and boundary['created_epoch'] == manifest['created_epoch']
            and boundary['deadline_epoch'] == manifest['deadline_epoch']
            and manifest['admission']['experiment_sha256'] == digest(reg)
            and ((boundary['head']['phase'] == 'OBSERVED' and (previous is None or boundary.get('unprocessed_attempts') == 0)) or
                 ((requalification or error_alias) and boundary['head']['phase'] == 'STOPPED' and
                  boundary['head']['stop_reason'] == 'model_transport_or_unknown_usage' and
                  boundary.get('unprocessed_attempts') == 1 and boundary.get('closed_terminal_failure_id')))
            and boundary['pending_attempts'] == 0
            and boundary['config_sha256'] == digest(manifest['config'])
            and boundary['context_chars'] == manifest['config']['limits']['context_chars'] == 120000,
            'source_revision_boundary', 'Run, clock, limits or unfinished requests differ')
    return value


def revision_chain(value, *, _depth=0):
    if value is None:
        return []
    require(_depth < 10, 'source_revision_chain', 'At most ten reviewed revisions')
    from .experiment import checked_file
    previous = value.get('previous_source_revision')
    return (revision_chain(checked_file(previous), _depth=_depth+1) if previous else []) + [value]


def for_amendment(reg, base):
    if not base or base.get('schema') != 'harness-B-exception-quota-removal-v1':
        return None
    root = Path(reg['experiment_directory'])
    path = root / 'source_revision_10.json'
    if path.exists():
        value = validate(strict_json(path.read_bytes()), reg, base)
        from .contracts import sha_bytes
        from .transport_error_alias import REPAIR
        chain = revision_chain(value)
        names = ('source_revision.json', *(f'source_revision_{i}.json' for i in range(2, 10)))
        require(len(chain) == 10 and value['repairs'] == REPAIR and all(
                chain[i+1]['previous_source_revision'] == {'path': str(root/name), 'sha256': sha_bytes((root/name).read_bytes())}
                for i, name in enumerate(names)), 'source_revision_chain', 'Alias repair must retain all nine predecessors')
        return value
    path = root / 'source_revision_9.json'
    if path.exists():
        value = validate(strict_json(path.read_bytes()), reg, base)
        from .contracts import sha_bytes
        from .wall_budget import POST_NETWORK_REPAIR
        chain = revision_chain(value)
        names = ('source_revision.json', *(f'source_revision_{i}.json' for i in range(2,9)))
        require(len(chain) == 9 and value['repairs'] == POST_NETWORK_REPAIR and all(
                chain[i+1]['previous_source_revision'] == {'path':str(root/name),'sha256':sha_bytes((root/name).read_bytes())}
                for i,name in enumerate(names)), 'source_revision_chain', 'Allowance must retain all eight predecessors')
        return value
    path = root / 'source_revision_8.json'
    if path.exists():
        value = validate(strict_json(path.read_bytes()), reg, base)
        from .contracts import sha_bytes
        from .user_managed_network import REPAIR
        chain = revision_chain(value)
        names = ('source_revision.json', *(f'source_revision_{i}.json' for i in range(2,8)))
        require(len(chain) == 8 and value['repairs'] == REPAIR and all(
                chain[i+1]['previous_source_revision'] == {'path':str(root/name),'sha256':sha_bytes((root/name).read_bytes())}
                for i,name in enumerate(names)), 'source_revision_chain', 'Network handoff must retain all seven predecessors')
        return value
    path = root / 'source_revision_7.json'
    if path.exists():
        value = validate(strict_json(path.read_bytes()), reg, base)
        from .contracts import sha_bytes
        from .transport_requalification import REPAIR
        chain = revision_chain(value)
        names = ('source_revision.json', *('source_revision_'+str(i)+'.json' for i in range(2,7)))
        require(len(chain)==7 and value['repairs']==REPAIR and all(chain[i+1]['previous_source_revision']==
                {'path':str(root/name),'sha256':sha_bytes((root/name).read_bytes())} for i,name in enumerate(names)),
                'source_revision_chain','Requalification must retain all six immutable predecessors')
        return value
    path = root / 'source_revision_6.json'
    if path.exists():
        value = validate(strict_json(path.read_bytes()), reg, base)
        from .contracts import sha_bytes
        chain = revision_chain(value)
        require(len(chain) == 6 and value['repairs'] == FACT_REPAIR and all(
                chain[i+1]['previous_source_revision'] ==
                {'path':str(root / name), 'sha256':sha_bytes((root / name).read_bytes())}
                for i,name in enumerate(('source_revision.json', 'source_revision_2.json',
                                         'source_revision_3.json', 'source_revision_4.json', 'source_revision_5.json'))),
                'source_revision_chain', 'Fact retention must retain all five immutable predecessors')
        return value
    path = root / 'source_revision_5.json'
    if path.exists():
        value = validate(strict_json(path.read_bytes()), reg, base)
        from .contracts import sha_bytes
        chain = revision_chain(value)
        require(len(chain) == 5 and all(chain[i+1]['previous_source_revision'] ==
                {'path':str(root / name), 'sha256':sha_bytes((root / name).read_bytes())}
                for i,name in enumerate(('source_revision.json', 'source_revision_2.json', 'source_revision_3.json', 'source_revision_4.json'))),
                'source_revision_chain', 'Fifth revision must retain all four immutable predecessors')
        return value
    path = root / 'source_revision_4.json'
    if path.exists():
        value = validate(strict_json(path.read_bytes()), reg, base)
        from .contracts import sha_bytes
        chain = revision_chain(value)
        require(len(chain) == 4 and all(chain[i+1]['previous_source_revision'] ==
                {'path':str(root / name), 'sha256':sha_bytes((root / name).read_bytes())}
                for i,name in enumerate(('source_revision.json', 'source_revision_2.json', 'source_revision_3.json'))),
                'source_revision_chain', 'Fourth revision must retain all three immutable predecessors')
        return value
    path = root / 'source_revision_3.json'
    if path.exists():
        value = validate(strict_json(path.read_bytes()), reg, base)
        from .contracts import sha_bytes
        chain = revision_chain(value)
        require(len(chain) == 3 and all(chain[i+1]['previous_source_revision'] ==
                {'path':str(root / name), 'sha256':sha_bytes((root / name).read_bytes())}
                for i,name in enumerate(('source_revision.json', 'source_revision_2.json'))),
                'source_revision_chain', 'Third revision must retain both immutable predecessors')
        return value
    path = root / 'source_revision_2.json'
    if path.exists():
        value = validate(strict_json(path.read_bytes()), reg, base)
        from .contracts import sha_bytes
        require(value.get('previous_source_revision') == {'path':str(root / 'source_revision.json'),
                    'sha256':sha_bytes((root / 'source_revision.json').read_bytes())},
                'source_revision_chain', 'Second revision must retain the original immutable revision')
        return value
    path = root / 'source_revision.json'
    return validate(strict_json(path.read_bytes()), reg, base) if path.exists() else None


def _check_prefix(evidence, boundary):
    require(digest(evidence.value['events'][:boundary['event_count']]) == boundary['events_sha256']
            and digest(evidence.value['physical'][:boundary['physical_count']]) == boundary['physical_sha256'],
            'source_revision_prefix', 'Original workflow or physical history changed')
    for ns in ('attempts', 'commits'):
        require(all(evidence.records[ns].get(k) == ref for k, ref in boundary['records'][ns].items()),
                'source_revision_prefix', 'Existing calls, costs or decisions changed')


def validate_marker(evidence, reg, base, *, required=False, through_revision=None):
    rows = evidence.rows('control_source_revisions')
    if not rows and not required:
        return
    versions = revision_chain(for_amendment(reg, base))
    if through_revision is not None:
        matches = [i for i,v in enumerate(versions) if digest(v) == through_revision]
        require(len(matches) == 1, 'source_revision_marker', 'Unregistered active source revision')
        versions = versions[:matches[0]+1]
    require(versions and 0 < len(rows) <= len(versions)
            and (not required or len(rows) == len(versions)),
            'source_revision_marker', 'Missing or duplicate source boundary')
    by_revision = {r['revision_sha256']:r for r in rows.values()}
    require(len(by_revision) == len(rows) and set(by_revision) == {digest(v) for v in versions[:len(rows)]},
            'source_revision_marker', 'Source markers must form the original revision prefix')
    from .experiment import checked_file
    for value in versions[:len(rows)]:
        boundary = checked_file(value['boundary'])
        row = by_revision[digest(value)]
        require(row['boundary'] == value['boundary'] and row['head_before'] == boundary['head']
                and row['new_model_calls'] == 0 and row['source_before'] == value['base_source_sha256']
                and row['source_after'] == value['active_fingerprint_sha256'],
                'source_revision_marker', 'Source marker differs')
        _check_prefix(evidence, boundary)
        require(len(evidence.value['events']) > boundary['event_count'], 'source_revision_marker', 'Missing transition event')
        marker = evidence.value['events'][boundary['event_count']]
        require(marker['kind'] == 'control_source_revised' and evidence.get(marker['payload_ref']) == row,
                'source_revision_marker', 'Missing original transition event')
        from .transport_error_alias import REPAIR as ALIAS_REPAIR, validate_activation
        if value['repairs'] == ALIAS_REPAIR:
            validate_activation(evidence, value, boundary)


def live_view(path):
    from .recovery import LiveEvidence
    view = LiveEvidence(path)
    with sqlite3.connect(f'file:{Path(path) / "events.sqlite3"}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        view.value = {'events':[dict(r) for r in db.execute('SELECT * FROM events ORDER BY seq')],
                      'physical':[r[0] for r in db.execute('SELECT object_ref FROM physical ORDER BY seq')]}
    return view


def install(directory):
    from .amendment import amendment_for, case_directory
    from .experiment import checked_file, experiment_lock
    from .store import Store
    root = Path(directory).resolve()
    reg = strict_json((root / 'experiment.json').read_bytes())
    base = amendment_for(reg)
    value = for_amendment(reg, base)
    require(value is not None, 'source_revision', 'No tested source revision')
    boundary = checked_file(value['boundary'])
    target = case_directory(root, 'B3600')
    with experiment_lock({'experiment_directory':str(root)}):
        store = Store(target)
        try:
            require(len(store.rows('control_source_revisions')) == len(revision_chain(value))-1
                    and store.meta('head') == boundary['head'],
                    'source_revision_boundary', 'Already revised or checkpoint moved')
            view = live_view(target)
            validate_marker(view, reg, base)
            _check_prefix(view, boundary)
            require(len(view.value['events']) == boundary['event_count']
                    and len(view.value['physical']) == boundary['physical_count'],
                    'source_revision_boundary', 'Checkpoint advanced before installation')
            row = {'revision_sha256':digest(value), 'boundary':value['boundary'],
                   'head_before':store.meta('head'), 'source_before':value['base_source_sha256'],
                   'source_after':value['active_fingerprint_sha256'], 'new_model_calls':0,
                   'installed_epoch':time.time()}
            with store.transaction():
                key = ('terminal-error-alias-runway' if value['repairs'] == ['closed_request_error_alias_and_bounded_runway'] else
                       'post-network-time' if value['repairs'] == ['approved_same_B_post_network_time_allowance'] else
                       'user-managed-network' if value['repairs'] == ['user_managed_network_continuation'] else
                       'transport-requalification' if value['repairs'] == ['verified_same_B_transport_requalification'] else
                       'fact-retention' if value['repairs'] == FACT_REPAIR else
                       'time-runway-budget' if value['repairs'] == ['approved_same_B_time_runway_extension'] else
                       'time-budget' if value['repairs'] == ['approved_same_B_time_extension'] else
                       'wall-budget' if value['repairs'] == ['approved_same_B_wall_extension'] else
                       'request-preparation' if value.get('previous_source_revision') else 'context-and-validation')
                store.record('control_source_revisions', key, row)
                store.event('control_source_revised', row)
            store.verify()
        finally:
            store.close()
    validate_marker(live_view(target), reg, base, required=True)
    return row
