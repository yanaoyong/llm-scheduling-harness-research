"""Explicit fixed-model continuation registration; history is cost, never samples."""
from copy import deepcopy
from pathlib import Path
import sqlite3
import zlib

from .contracts import digest, require, sha_bytes, strict_json, validate_config

SCHEMA = 'harness-model-switch-registration-v1'
GRANT = 'harness-model-switch-authorization-v1'
REVISED_GRANT = 'harness-model-switch-authorization-v2'
MODEL = {'name': 'gpt-6.1-sol', 'reasoning_effort': 'medium'}
ADDITIONAL = {
    'micro': {'attempts': None, 'tokens': None, 'model_seconds': 7200, 'wall_seconds': 14400},
    'B3600': {'attempts': None, 'tokens': None, 'model_seconds': 10800, 'wall_seconds': 14400},
    'combined': {'attempts': None, 'tokens': None, 'model_seconds': 18000, 'wall_seconds': 28800},
}


def validate_grant(grant):
    from .experiment import RECOVERY_POLICY
    require(grant['schema'] in (GRANT, REVISED_GRANT) and grant['model'] == MODEL, 'model_switch', 'Exact requested model/effort required')
    require(grant['additional_caps'] == ADDITIONAL and grant['full_B_new_run_limit'] == 1,
            'model_switch', 'Finite additional time and one B start required')
    expected_policy = RECOVERY_POLICY
    if grant['schema'] == REVISED_GRANT:
        from .experiment import checked_file
        authorization = checked_file(grant['limit_authorization'])
        require(authorization['user_instruction'] == '异常额度放宽到30次' and
                authorization['new_cohort_limit'] == 30 and authorization['already_used_failures_retained'] is True,
                'recovery_grant', 'Explicit cumulative limit30 authorization required')
        expected_policy = {**RECOVERY_POLICY, 'max_failures_per_cohort':30}
        require(grant['recovery_count_reset'] is False and grant['revision_reason'] == 'verified_feedback_and_connection_repairs',
                'recovery_grant', 'Repair cannot reset exceptions or replace scored outcomes')
    require(grant['recovery_policy'] == expected_policy and grant['unknown_usage_policy'] == 'bounded_terminated_failures',
            'model_switch', 'Bounded recovery policy changed')
    require(grant['retain_failures_and_costs'] is True and grant['same_twenty_fragments'] is True
            and grant['failures_excluded'] is False and grant['historical_results_are_new_samples'] is False,
            'model_switch', 'No erased cost or mixed-model score')
    require(isinstance(grant.get('user_instruction'), str) and 'gpt-6.1-sol' in grant['user_instruction'],
            'model_switch', 'Explicit model switch instruction required')
    return grant


class CheckpointEvidence:
    def __init__(self, directory, value):
        self.path, self.value = Path(directory), value
        self.allowed = set(value['objects'])
        self.manifest = self.get(value['manifest_ref'])

    def raw(self, ref):
        require(ref in self.allowed, 'carry_object', 'Object outside retained boundary')
        raw = zlib.decompress((self.path / 'objects' / (ref + '.z')).read_bytes())
        require(sha_bytes(raw) == ref, 'carry_object', 'Retained object changed')
        return raw

    def get(self, ref):
        return strict_json(self.raw(ref))

    def rows(self, namespace):
        return {key:self.get(ref) for key,ref in self.value['records'].get(namespace, {}).items()}


def carried_costs(reg):
    """Verify the old account, every preserved run, and the imported Sol call once."""
    from .experiment import checked_file, sealed_prior, account_records, empty_usage, finish_usage, validate_closed_unknown
    from .evaluation import audit_cost
    snapshot = checked_file(reg['prior_cost_evidence'])
    require(snapshot['schema'] == 'harness-model-switch-cost-boundary-v1', 'carry_boundary', 'Explicit stopped boundary required')
    previous = checked_file(snapshot['previous_registration'])
    require(previous['schema'] in ('harness-p5-registration-v9', SCHEMA), 'carry_boundary', 'Expected frozen predecessor')
    totals, starts, ids = sealed_prior(previous)
    require(snapshot['prior_cumulative_usage'] == totals, 'carry_totals', 'Ancestor costs changed')
    totals, ids = deepcopy(totals), set(ids)
    expected_accounts = {str(Path(x['path']).parent):checked_file(x) for x in snapshot['additional_registrations']}
    require(str(Path(snapshot['previous_registration']['path']).parent) in expected_accounts,
            'carry_ancestor_missing', 'Predecessor current cohort omitted')
    all_rows = {str(Path(directory)): (root, case, group, run_id, created)
                for root in expected_accounts for case,group,run_id,directory,created in account_records(root)}
    require(set(all_rows) == {x['directory'] for x in snapshot['runs']} and len(snapshot['runs']) == len(all_rows),
            'carry_runs', 'Added, omitted or duplicate historical run')
    cohorts, clocks, unknown_ids, call_ids = {}, {}, [], set()
    for row in snapshot['runs']:
        root, case, group, run_id, created = all_rows[row['directory']]
        boundary = checked_file(row['boundary'])
        ev = CheckpointEvidence(row['directory'], boundary)
        require(ev.manifest['run_id'] == run_id and run_id not in ids and ev.manifest['created_epoch'] == created,
                'carry_identity', 'Duplicated or replaced run')
        require(ev.manifest['admission']['experiment_sha256'] == digest(expected_accounts[root]),
                'carry_identity', 'Run registration changed')
        ids.add(run_id)
        if row['unsealed_checkpoint']:
            require(boundary['head']['phase'] == 'STOPPED' and row['accounting_end_epoch'] == snapshot['transition_started_epoch'],
                    'carry_checkpoint', 'Only explicit stopped migration boundary is allowed')
            with sqlite3.connect(f"file:{row['directory']}/events.sqlite3?mode=ro", uri=True) as db:
                current = {}
                for ns,key,ref in db.execute('SELECT namespace,key,ref FROM records'):
                    current.setdefault(ns,{})[key] = ref
                require(current == boundary['records'], 'carry_live_change', 'Stopped source was modified')
        else:
            closure = checked_file(row['audit_closure']) if 'audit_closure' in row else None
            if previous['schema'] == SCHEMA:
                require(boundary['head']['phase'] == 'CLOSED' and closure is not None and
                        closure['evidence_sha256'] == row['boundary']['sha256'] and
                        closure['completed_epoch'] == row['accounting_end_epoch'],
                        'carry_closed', 'Revised acceptance requires each predecessor to be sealed and clock-closed')
                from .amendment import validate_continuation
                validate_continuation(ev)
        cost = audit_cost(ev)
        require(cost == row['costs'] and cost['pending_attempts'] == 0, 'carry_totals', 'Costs changed or pending')
        for aid, attempt in ev.rows('attempts').items():
            if attempt['channel'] != 'codex' or attempt['status'] in ('reserved','not_sent'):
                continue
            require(aid not in call_ids, 'carry_duplicate', 'Imported response counted twice')
            call_ids.add(aid)
            if attempt.get('usage') is None:
                validate_closed_unknown(ev, attempt)
                unknown_ids.append({'run_id':run_id,'attempt_id':aid,'attempt_sha256':digest(attempt)})
        meter = cohorts.setdefault(root, empty_usage())[group]
        for dest, source in [('attempts','actual_attempts'),('tokens','total_reported_tokens'),('model_seconds','model_seconds'),('unknown_usage','unknown_usage')]:
            meter[dest] += cost[source]
        key = (root, group)
        first,last = clocks.get(key,(created,row['accounting_end_epoch']))
        clocks[key] = (min(first,created),max(last,row['accounting_end_epoch']))
        starts += group == 'B3600'
    for root,meter in cohorts.items():
        finish_usage(meter,{g:t for (r,g),t in clocks.items() if r==root})
        for g in totals:
            for k in totals[g]: totals[g][k] += meter[g][k]
    require(sorted(unknown_ids,key=lambda x:x['attempt_id']) == snapshot['additional_unknown_attempts'],
            'carry_unknown', 'Unknown failures must retain exact identities')
    require(totals == snapshot['cumulative_usage'] and starts == snapshot['full_B_starts_used'],
            'carry_totals', 'Historical totals were discounted')
    return totals, starts, ids


def carried_recovery_count(reg):
    """Validate exact prior recovery identities; the 30-slot counter never resets."""
    if reg.get('schema') == 'harness-B-network-restart-registration-v1':
        from .B_network_restart import carried_recovery_count as network_count
        return network_count(reg)
    if 'recovery_carry' not in reg:
        return 0
    from .experiment import checked_file
    from .recovery import cohort_recoveries
    proof = checked_file(reg['recovery_carry'])
    snapshot = checked_file(reg['prior_cost_evidence'])
    require(proof['schema'] == 'harness-recovery-carry-v1' and
            proof['previous_registration'] == snapshot['previous_registration'],
            'recovery_carry', 'Recovery chain differs from cost chain')
    previous = checked_file(proof['previous_registration'])
    rows = [{'run_id':rid, 'attempt_id':aid, 'recovery_sha256':digest(row)}
            for rid, (_, records) in cohort_recoveries(previous).items() for aid,row in records.items()]
    rows.sort(key=lambda x:(x['run_id'],x['attempt_id']))
    offset = carried_recovery_count(previous)
    require(proof['recoveries'] == rows and proof['prior_count'] == offset and
            proof['total_count'] == offset + len(rows) and proof['total_count'] <= 30,
            'recovery_carry', 'Exception identities or consumed allowance changed')
    return proof['total_count']


def validate_registration(reg, root):
    from .experiment import checked_file
    grant = validate_grant(checked_file(reg['authorization']))
    require(reg['full_B_new_run_limit'] == 1, 'model_switch', 'Single fresh B quota changed')
    require(Path(reg['experiment_directory']).resolve() == root.resolve() and reg['recovery_policy'] == grant['recovery_policy'],
            'model_switch', 'Recovery account changed')
    require(reg['prior_cost_evidence'] == grant['prior_cost_evidence'], 'carry_boundary', 'Cost boundary changed')
    snapshot = checked_file(reg['prior_cost_evidence'])
    require(reg['carried_usage_at_registration'] == snapshot['cumulative_usage'], 'carry_totals', 'Carry summary changed')
    expected = {g:{k:None if v is None else snapshot['cumulative_usage'][g][k]+v for k,v in cap.items()}
                for g,cap in ADDITIONAL.items()}
    require(reg['caps'] == grant['caps'] == expected, 'model_switch', 'Historical usage plus additional quota required')
    require(reg['model'] == MODEL and reg['micro_metrics'] == {'n_min':20,'median_max':3,'p95_max':5,
            'p95_method':'sorted ceil(0.95*n), one-based','failures_excluded':False}, 'model_switch', 'Acceptance gate changed')
    previous = checked_file(snapshot['previous_registration'])
    if grant['schema'] == REVISED_GRANT:
        require(previous['schema'] == SCHEMA and reg['recovery_carry'] == grant['recovery_carry'] and
                reg['transport_proxy'] == grant['transport_proxy'], 'model_switch', 'Revised cost, recovery and route bindings required')
        carried_recovery_count(reg)
        from .network import validate_binding
        validate_binding(reg['transport_proxy'])
    else:
        require('recovery_carry' not in reg and 'transport_proxy' not in reg,
                'model_switch', 'Earlier grants do not authorize amended routing or recovery counters')
    oldroot = Path(snapshot['previous_registration']['path']).parent
    require(set(reg['cases']) == set(previous['cases']) and len(reg['cases']) == 21,
            'same_cohort', 'Exact same twenty plus B required')
    require(set(reg['execution_order']) == {k for k in reg['cases'] if k!='B3600'} and len(reg['execution_order']) == 20,
            'same_cohort', 'One occurrence of each fragment required')
    for case,entry in reg['cases'].items():
        cfg = strict_json((root/(case+'.config.json')).read_bytes())
        validate_config(cfg)
        require(digest(cfg) == entry['config_sha256'] and all(cfg['model'][k]==v for k,v in MODEL.items()),
                'case_config', 'Exact fixed Sol configuration required')
        oldcfg = strict_json((oldroot/(case+'.config.json')).read_bytes())
        require({k:v for k,v in cfg.items() if k not in ('model','limits')} ==
                {k:v for k,v in oldcfg.items() if k not in ('model','limits')}, 'same_cohort', 'Decision conditions changed')
        require(cfg['model']['timeout_seconds'] == (600 if case=='B3600' else 180), 'case_config', 'Timeout changed')
        require(all(cfg['limits'][k] == v for k,v in ADDITIONAL[entry['group']].items()),
                'case_config', 'Per-phase additional budget changed')
        if case!='B3600':
            require({k:v for k,v in entry.items() if k!='config_sha256'} ==
                    {k:v for k,v in previous['cases'][case].items() if k!='config_sha256'}, 'same_cohort', 'Task or initial identity changed')
            require((root/(case+'.initial.json.z')).read_bytes() == (oldroot/(case+'.initial.json.z')).read_bytes(),
                    'same_cohort', 'Saved original inputs changed')
    return reg
