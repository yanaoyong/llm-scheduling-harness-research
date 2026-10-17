"""Explicit same-run recovery after a closed burst and independent route check.

No failure is erased. Two retries remain the limit within each request burst.
A new burst needs a stopped checkpoint, complete no-answer process proofs, a
15-minute quiet interval and an independently completed same-model/TUN request.
All diagnostic costs are retained in the same shared account.
"""
from pathlib import Path
import time
from .contracts import digest, require, sha_bytes, strict_json

REPAIR = ['verified_same_B_transport_requalification']
FILES = {'src/smt_fullfab/harness/transport_requalification.py',
         'src/smt_fullfab/harness/recovery.py', 'src/smt_fullfab/harness/source_revision.py',
         'src/smt_fullfab/harness/experiment.py', 'src/smt_fullfab/harness/evaluation.py'}
QUIET_SECONDS = 900
SCHEMA = 'harness-same-B-transport-requalification-v1'


def snapshot(boundary):
    return {'attempts_sha256': digest(boundary['records']['attempts']),
            'commits_sha256': digest(boundary['records']['commits']),
            'events_sha256': boundary['events_sha256'], 'physical_sha256': boundary['physical_sha256']}


def stopped_boundary(evidence, boundary, policy):
    from .recovery import failure_kind
    require(boundary['run_id'] == evidence.manifest['run_id'] and
            boundary['created_epoch'] == evidence.manifest['created_epoch'] and
            boundary['deadline_epoch'] == evidence.manifest['deadline_epoch'] and
            boundary['config_sha256'] == digest(evidence.manifest['config']) and
            boundary['head']['phase'] == 'STOPPED' and
            boundary['head']['stop_reason'] == 'model_transport_or_unknown_usage' and
            boundary['pending_attempts'] == 0 and boundary['unprocessed_attempts'] == 1,
            'requalification_boundary', 'Only a stopped closed no-answer burst qualifies')
    attempts = sorted((evidence.get(ref) for ref in boundary['records']['attempts'].values()), key=lambda a:a['index'])
    require(len(attempts) == boundary['actual_attempts'] and len(attempts) >= policy['max_retries_per_request']+1 and
            not any(a['status'] in ('reserved','started','unknown') for a in attempts),
            'requalification_pending', 'Every process must be settled')
    tail = attempts[-(policy['max_retries_per_request']+1):]
    require(policy['max_retries_per_request'] == 2 and tail[-1]['attempt_id'] == boundary['closed_terminal_failure_id'] and
            all(a['context_ref'] == boundary['head']['context_ref'] for a in tail),
            'requalification_burst', 'Exact same-context three-failure burst required')
    for ordinal, attempt in enumerate(tail, 1):
        require(failure_kind(evidence, attempt) in policy['allowed_failure_kinds'],
                'requalification_failure', 'Only an already authorized failure kind qualifies')
        if ordinal <= 2:
            ref = boundary['records']['transport_recoveries'].get(attempt['attempt_id'])
            require(ref is not None and evidence.get(ref)['request_failure_ordinal'] == ordinal,
                    'requalification_burst', 'Preserve both original retries')
        else:
            require(attempt['attempt_id'] not in boundary['records']['transport_recoveries'],
                    'requalification_duplicate', 'Final failed attempt already reconciled')
    return tail[-1]


def diagnostics(reference, boundary, manifest, reg):
    """Read original independently guarded diagnostic files; never launch a process."""
    from .experiment import checked_file
    from ..model_process_guard import INPUT_FILES, OUTPUT_FILES, verify_lifecycle
    audit = checked_file(reference)
    require(audit['schema'] == 'harness-minimal-path-diagnostic-audit-v1' and
            audit['B_run_id'] == manifest['run_id'] == boundary['run_id'] and
            audit['B_snapshot_unchanged'] is True and audit['formal_B_started'] is False,
            'requalification_probe', 'Diagnostic must belong to this unchanged B checkpoint')
    hashes = audit['evidence_sha256']
    require(hashes and all(sha_bytes(Path(path).read_bytes()) == value for path,value in hashes.items()),
            'requalification_probe', 'Original diagnostic evidence changed')
    result_paths = [Path(p) for p in hashes if Path(p).name == 'result.json']
    require(len(result_paths) == audit['actual_diagnostic_calls'] == len(audit['results']) and 1 <= len(result_paths) <= 2,
            'requalification_probe', 'One or two fully recorded probes required per bundle')
    rows = []
    for result_path in sorted(result_paths):
        directory = result_path.parent
        read = lambda name: strict_json((directory/name).read_bytes())
        result, plan, command = read('result.json'), read('plan.json'), read('command.json')
        require(result in audit['results'] and plan['B_snapshot'] == snapshot(boundary) and
                plan['model'] == result['model'] == reg['model']['name'] == 'gpt-6-astra' and
                plan['reasoning_effort'] == reg['model']['reasoning_effort'] and
                plan['max_actual_calls'] == result['actual_calls'] == 1 and plan['automatic_retries'] == result['automatic_retries'] == 0 and
                result['business_actions_executed'] is False and result['formal_B_started'] is False,
                'requalification_probe', 'Diagnostic identity, scope or retry policy differs')
        inputs = {name:sha_bytes((directory/name).read_bytes()) for name in plan['inputs_sha256']}
        argv = command['argv']
        require(inputs == plan['inputs_sha256'] and digest({'argv':argv,'inputs':inputs}) == plan['request_fingerprint'] and
                argv[0] == reg['cli_binary'] and plan['cli_sha256'] == reg['cli_sha256'] and
                argv[argv.index('--model')+1] == reg['model']['name'] and
                all(setting in argv for setting in ('model_providers.harness-openai.request_max_retries=0',
                                                    'model_providers.harness-openai.stream_max_retries=0')) and
                inputs['model-catalog.json'] == manifest['admission']['model_catalog_sha256'],
                'requalification_probe', 'Frozen command/catalog and no hidden retries required')
        network = read('network.json')
        require(network['frozen_underlying_binding'] == reg['transport_proxy'] and
                network['global_configuration_changed'] is False and result['route_observed'] is True,
                'requalification_route', 'The original route must remain bound and observed')
        io = {'cwd':str(directory/'isolated-cwd'),'stdin':str(directory/'prompt.txt'),
              'stdout':str(directory/'events.jsonl'),'stderr':str(directory/'stderr.log'),
              'inputs':{n:str(directory/n) for n in (*INPUT_FILES,'model-catalog.json','network.json')},
              'outputs':{n:str(directory/n) for n in OUTPUT_FILES}}
        guard = verify_lifecycle(directory, expected_command=argv, expected_timeout=plan['timeout_seconds'],
                                 expected_call_id=plan['call_id'], expected_fingerprint=plan['request_fingerprint'], expected_io_spec=io)
        events = [strict_json(line) for line in (directory/'events.jsonl').read_bytes().splitlines() if line.strip()]
        completed = [e for e in events if e.get('type') == 'turn.completed']
        require(not any(e.get('type') in ('item.started','item.completed','item.updated') and
                        e.get('item',{}).get('type') not in ('agent_message','reasoning','error') for e in events) and
                not result['native_tool_events'] and result['call_id'] == plan['call_id'] and
                result['duration_seconds'] == guard['parent_wait_wall_seconds'] and
                result['returncode'] == guard['command_returncode'] and result['lifecycle_complete'] is True and
                result['started_epoch'] == read('launch_once.json')['started_epoch'] and
                result['ended_epoch'] >= result['started_epoch'],
                'requalification_probe', 'Complete original process and usage evidence required')
        known = len(completed) == 1 and all(type(completed[0]['usage'].get(k)) is int for k in ('input_tokens','output_tokens'))
        if known:
            require(result['usage'] == completed[0]['usage'] and result['unknown_usage'] is False and
                    result['channel_success'] is True and guard['command_returncode'] == 0 and
                    not guard['timed_out'] and read('final.txt') == {'ok':True} and
                    not any(e.get('type') in ('error','turn.failed') for e in events),
                    'requalification_probe', 'Exact successful short response required')
        else:
            require(not completed and result['usage'] is None and result['unknown_usage'] is True and
                    result['channel_success'] is False and guard['command_returncode'] != 0 and
                    guard['output_files_sha256']['final.txt'] is None and
                    not any(e.get('item',{}).get('type') == 'agent_message' for e in events),
                    'requalification_probe', 'Unknown diagnostic must have terminated without an answer')
        require(all(str(directory/name) in hashes for name in (*INPUT_FILES,'model-catalog.json','network.json',
                    'events.jsonl','stderr.log','plan.json','result.json','launch_once.json','connection_observations.json')) and
                all(hashes.get(str(directory/'process_guard'/name)) == value
                    for name,value in guard['files_sha256'].items() if name.endswith('.json')),
                'requalification_probe', 'Every input and process proof must be frozen')
        observations = read('connection_observations.json')
        categories = {key:sum(o['category']==key for o in observations) for key in result['connection_categories']}
        require(categories == result['connection_categories'] and observations and
                all(o['command_pid']==guard['command_pid'] and result['started_epoch']<=o['epoch']<=result['ended_epoch']
                    for o in observations) and network['diagnostic_route']==result['route'] and
                ((result['route']=='system_TUN' and network['explicit_proxy'] is None and network['NO_PROXY']=='*' and
                  categories['non_loopback']>0 and categories['explicit_loopback_7897']==0) or
                 (result['route']=='explicit_loopback' and network['explicit_proxy']=='http://127.0.0.1:7897' and
                  categories['explicit_loopback_7897']>0 and categories['non_loopback']==0)),
                'requalification_route','Original process socket observations must prove the claimed route')
        rows.append(result)
    require(len({r['call_id'] for r in rows}) == len(rows), 'requalification_probe', 'Duplicate diagnostic')
    return rows


def diagnostic_usage(evidence, reg=None):
    total = {'attempts':0,'tokens':0,'input_tokens':0,'output_tokens':0,'cached_input_tokens':0,
             'model_seconds':0,'unknown_usage':0,'pending':0,'reserved_tokens':0,'wall_seconds':0}
    rows = evidence.rows('transport_requalifications')
    if not rows:
        return total
    from .experiment import registration, checked_file
    reg = reg or registration(evidence.manifest['admission'])
    seen = set()
    for row in rows.values():
        boundary = checked_file(row['boundary'])
        for reference in row['diagnostic_bundles']:
            for result in diagnostics(reference, boundary, evidence.manifest, reg):
                require(result['call_id'] not in seen, 'diagnostic_duplicate', 'Diagnostic cost must be counted once')
                seen.add(result['call_id']);total['attempts'] += 1
                total['model_seconds'] += result['duration_seconds']
                if result['usage'] is None:
                    total['unknown_usage'] += 1
                else:
                    for key in ('input_tokens','output_tokens','cached_input_tokens'):
                        total[key] += result['usage'].get(key,0)
                    total['tokens'] += result['usage']['input_tokens'] + result['usage']['output_tokens']
    return total


def validate_records(evidence, reg, policy):
    rows = evidence.rows('transport_requalifications')
    if not rows:
        return {}
    from .experiment import checked_file
    from .amendment import amendment_for
    from .source_revision import for_amendment, revision_chain, live_view, _check_prefix, validate_marker
    versions = [v for v in revision_chain(for_amendment(reg,amendment_for(reg))) if v['repairs'] == REPAIR]
    require(len(versions) == 1, 'requalification_source', 'Explicit reviewed requalification source required')
    version = versions[0]
    view = evidence if hasattr(evidence,'value') else live_view(evidence.path)
    if not hasattr(view,'records'):
        view.records = view.value['records']
    validate_marker(view,reg,amendment_for(reg),required=True)
    result, probe_ids = {}, set()
    for key,row in rows.items():
        require(row['schema'] == SCHEMA and row['run_id'] == evidence.manifest['run_id'] and
                row['registration_sha256'] == digest(reg) and row['source_revision_sha256'] == digest(version) and
                row['new_model_calls'] == 0 and row['reset_costs'] is False and row['reset_time'] is False,
                'requalification_identity', 'Original run, source and accounting required')
        boundary = checked_file(row['boundary']);_check_prefix(view,boundary)
        require(boundary['registration_sha256']==digest(reg), 'requalification_identity','Wrong registered checkpoint')
        last = stopped_boundary(evidence,boundary,policy)
        require(key == row['closed_failure_id'] == last['attempt_id'] and row['head_before'] == boundary['head'] and
                row['next_attempt_index'] == last['index']+1 and row['quiet_seconds'] == QUIET_SECONDS and
                row['qualified_epoch'] >= last['finished_epoch']+QUIET_SECONDS,
                'requalification_cooldown', 'No resetting or premature new burst')
        probes = []
        for reference in row['diagnostic_bundles']:
            probes += diagnostics(reference,boundary,evidence.manifest,reg)
        require(probes and all(p['call_id'] not in probe_ids for p in probes),
                'requalification_probe', 'A diagnostic cannot qualify multiple bursts')
        probe_ids.update(p['call_id'] for p in probes)
        require(any(p['route']=='system_TUN' and p['channel_success'] and
                    p['started_epoch'] >= last['finished_epoch']+QUIET_SECONDS and
                    p['ended_epoch'] <= row['qualified_epoch'] for p in probes),
                'requalification_health', 'Independent successful original-route request after the quiet interval required')
        event = view.value['events'][row['event_index']]
        intervening = view.value['events'][boundary['event_count']:row['event_index']]
        require(row['event_index'] >= boundary['event_count'] and
                all(e['kind']=='control_source_revised' for e in intervening) and
                event['kind']=='transport_requalified' and
                evidence.get(event['payload_ref']) == row,
                'requalification_event', 'Durable original transition event required')
        later = [a for a in evidence.rows('attempts').values() if a['index']==row['next_attempt_index']]
        require(not later or later[0]['reserved_epoch'] >= row['qualified_epoch'],
                'requalification_cooldown', 'Next request predates independent qualification')
        result[key] = row
    diagnostic_usage(evidence,reg)
    return result


def install(directory, boundary_reference, diagnostic_bundles):
    """Atomically acknowledge the terminal failure and reopen its unchanged state."""
    from .experiment import checked_file, experiment_lock
    from .amendment import amendment_for, case_directory
    from .source_revision import for_amendment, validate_marker, live_view, _check_prefix
    from .recovery import policy_for, failure_kind, cohort_recoveries
    from .model_switch import carried_recovery_count
    from .store import Store
    from .contracts import fingerprint
    from .network import validate_binding
    root=Path(directory).resolve();reg=strict_json((root/'experiment.json').read_bytes());base=amendment_for(reg)
    version=for_amendment(reg,base)
    require(version['repairs']==REPAIR and fingerprint()['sha256']==version['active_fingerprint_sha256'],
            'requalification_source','Tested active requalification source required')
    target=case_directory(root,'B3600');boundary=checked_file(boundary_reference)
    validate_binding(reg['transport_proxy'],live=True)
    with experiment_lock({'experiment_directory':str(root)}):
        store=Store(target)
        try:
            view=live_view(target);validate_marker(view,reg,base,required=True);_check_prefix(view,boundary)
            policy=policy_for(view.manifest['admission']);last=stopped_boundary(view,boundary,policy)
            require(store.meta('head')==boundary['head'] and last['attempt_id'] not in view.rows('transport_requalifications') and
                    len(view.rows('attempts'))==boundary['actual_attempts'] and len(view.value['physical'])==boundary['physical_count'] and
                    all(e['kind']=='control_source_revised' for e in view.value['events'][boundary['event_count']:]),
                    'requalification_boundary','Stopped checkpoint moved or already qualified')
            probes=[p for ref in diagnostic_bundles for p in diagnostics(ref,boundary,view.manifest,reg)]
            now=time.time()
            require(len({p['call_id'] for p in probes})==len(probes) and
                    any(p['route']=='system_TUN' and p['channel_success'] and
                        p['started_epoch']>=last['finished_epoch']+QUIET_SECONDS and p['ended_epoch']<=now for p in probes),
                    'requalification_health','Independent successful original-route request required')
            require(now>=last['finished_epoch']+QUIET_SECONDS,'requalification_cooldown','Quiet interval not complete')
            used=carried_recovery_count(reg)+sum(len(r) for _,r in cohort_recoveries(reg).values())
            row={'schema':SCHEMA,'run_id':view.manifest['run_id'],'registration_sha256':digest(reg),
                 'source_revision_sha256':digest(version),'boundary':boundary_reference,'head_before':store.meta('head'),
                 'closed_failure_id':last['attempt_id'],'next_attempt_index':last['index']+1,
                 'quiet_seconds':QUIET_SECONDS,'qualified_epoch':now,'diagnostic_bundles':diagnostic_bundles,
                 'event_index':len(view.value['events']),'new_model_calls':0,'reset_time':False,'reset_costs':False}
            closed={'attempt_id':last['attempt_id'],'attempt_sha256':digest(last),'context_ref':last['context_ref'],
                    'failure_kind':failure_kind(view,last),'request_failure_ordinal':3,'cohort_failure_ordinal':used+1,
                    'not_before_epoch':last['finished_epoch']+QUIET_SECONDS,'policy_sha256':digest(policy),
                    'usage':None,'business_action_replayed':False,'closed_for_requalification':digest(row)}
            with store.transaction():
                store.record('transport_requalifications',last['attempt_id'],row)
                store.record('transport_recoveries',last['attempt_id'],closed)
                store.event('transport_requalified',row)
                head=store.meta('head');head.update(phase='OBSERVED',stop_reason=None);store.set_meta('head',head)
            store.verify()
        finally:store.close()
    validate_records(live_view(target),reg,policy)
    return row
