"""Private resume-segment loop. No CLI or implicit registration/model fallback.

Root supplies a separately audited admission mapping and the explicitly frozen
bridge/transport with that mapping's ledger adapter. This module never resets
parent costs or modifies parent evidence. Whole resumed acceptance is external.
"""
from copy import deepcopy
import dataclasses
import math
from pathlib import Path
import time

from . import fork_store, physical_resume, resume_bridge

SCHEMA = 'smt-B-v7-resume-segment-v1'


def need(condition, message):
    fork_store.need(condition, message)


def config_from_admission(admission, *, segment_path, parent_contract, model, reasoning_effort):
    need(type(admission) is dict and str(Path(segment_path).resolve()) == str(segment_path), 'explicit admitted absolute segment required')
    need(admission['segment_run_id'] == str(segment_path) and admission['parent_run_id'] == parent_contract['parent_run_path'], 'admission run mapping differs')
    need(model == 'gpt-6-astra' and reasoning_effort == 'medium', 'this candidate preserves V7 model; a switch needs a new explicit version')
    remaining = admission['remaining_runner_wall_seconds']
    need(type(remaining) in (int, float) and math.isfinite(remaining) and 0 < remaining <= 21600, 'finite inherited wall remainder required')
    need(type(admission['remaining_log_bytes']) is int and 0 < admission['remaining_log_bytes'] <= 17179869184, 'inherited log remainder required')
    need(admission['per_call_timeout_seconds'] == 600 and type(admission['per_call_timeout_seconds']) is int,
         'explicit 600-second authority required')
    return {'schema': SCHEMA, 'arm': 'B', 'run_id': Path(segment_path).name, 'seed': 1701, 'seconds': 3600,
        'parent_run_id': parent_contract['parent_run_path'], 'simulation_start': parent_contract['simulation_start'],
        'absolute_target': 3600.0, 'period_anchor': 0.0, 'period_seconds': 1800, 'plan_seconds': 14400,
        'lookahead_depth': 2, 'page_chars': parent_contract['page_chars'], 'model': model,
        'reasoning_effort': reasoning_effort, 'per_call_timeout_seconds': 600, 'max_calls': None, 'max_tokens': None,
        'remaining_runner_wall_seconds': remaining, 'remaining_log_bytes': admission['remaining_log_bytes'],
        'max_trace_bytes': 2147483648, 'solver_budget_seconds': 0, 'constructor_enabled': False,
        'parent_source_sha256': parent_contract['parent_source_sha256'],
        'cold_start_only': False, 'parent_status_remains': 'failed', 'formal': False,
        'automatic_retry': False, 'accepted': False}


def normalize_mapping(value, *, ledger_path):
    """Preserve raw mapping separately; decimal-to-float only for API time limits."""
    from decimal import Decimal
    m = value['mapping']; remaining = m['remaining']
    seconds = Decimal(str(remaining['runner_wall_seconds']))
    need(seconds.is_finite() and seconds > 0, 'invalid inherited wall remainder')
    return {'segment_run_id': m['segment_run_id'], 'parent_run_id': m['parent_run_id'],
        'remaining_runner_wall_seconds': float(seconds), 'remaining_log_bytes': remaining['log_bytes'],
        'per_call_timeout_seconds': 600, 'registration': value['registration'], 'ledger_path': str(ledger_path)}


def prefix(store):
    p = store.verify_full(reason='resume_critical_or_terminal')
    return {k: p[k] for k in fork_store.PREFIX}


def export_current(store, store_id):
    p = prefix(store)
    if type(store) is fork_store.ForkOwner:
        full = fork_store.recover_read_only(store.fork_directory, runtime=store.runtime,
            expected_manifest_sha256=store.fork_manifest_sha256, expected_prefix=p)
    else:
        # Same original complete oracle; no hot-cache claim at critical selection.
        full = resume_bridge.durable.export_verified_interaction(store.directory, expected_store_id=store_id, expected_prefix=p)
    need(full['valid'] and full['pure_replay_verified'] and len(full['interactions']) == 1, 'complete selection evidence required')
    return full['interactions'][0]['evidence']


def verified_reply(result, *, api, store, store_id, instance_id):
    checked = api.verify_live_read_only(result['evidence_dir'], store=store,
        expected_intent_sha256=result['intent_sha256'], expected_outcome_sha256=result['outcome_sha256'])
    # Original route classifier is unchanged; failed/unknown calls stop here.
    from src.smt_fullfab.B_incremental_v3 import controller as original
    kind = original.verified_processed_kind(checked, result['phase'])
    proof = result['durable_prefix']
    ev = store.export_live(expected_store_id=store_id, expected_prefix=proof)['interactions'][0]['evidence']
    record = ev['history'][-1]
    need(record['call_id'] == checked['original_call_id'] == result['call_id']
         and record['record_sha256'] == result['interaction_response']['record_sha256'], 'reply differs from exact original pure record')
    original.verify_history_kind(record, kind)
    return deepcopy(record['full_response'])


def commit_selected(physical, *, store, store_id, instance_id, selection, boot, directory,
                    branch_id, plan_index, index, controller):
    need(selection['status'] == 'selection_for_external_commit', 'only explicit later apply can commit')
    plan = selection['candidate']['compiled']['plan']
    current_anchors = controller.anchor_hashes(boot['base_plan'], boot['problem'], boot['execution_state'], source_sha256=boot['source_sha256'])
    need(controller.same(selection['anchors'], current_anchors), 'selected four anchors differ')
    selected_sha = controller.write_new(directory/'selected_plan.json', plan)
    def one_commit():
        before = len(physical.env.trace); intent_id = branch_id + ':commit:' + str(plan_index)
        intended = store.record_commit_intent(instance_id, intent_id=intent_id,
            selection_sha256=controller.json_sha256(selection), plan_sha256=controller.json_sha256(plan),
            current_anchors=current_anchors, external_validation_reference={'trace_event_index_before': before, 'plan_index': plan_index})
        controller.write_new(directory/'commit_intent.json', intended)
        need(intended['accepted'], 'intent failed; common executor not called')
        index.append('commit_intent', plan_index=plan_index, branch_id=branch_id, intent_id=intent_id,
            selected_plan_file_sha256=selected_sha, selection_sha256=controller.json_sha256(selection),
            plan_sha256=controller.json_sha256(plan), trace_event_index=before, durable_prefix=prefix(store))
        receipt = {'intent_id': intent_id, 'plan_index': plan_index, 'branch_id': branch_id,
            'plan_sha256': controller.json_sha256(plan), 'trace_event_index_before': before, 'retry_permitted': False}
        try:
            returned = physical.env.commit_plan(plan)
            event = physical.env.trace[before]
            need(len(physical.env.trace) == before+1 and event['kind'] == 'plan_committed'
                 and controller.same(event['plan'], plan) and controller.same(physical.env.plan, plan)
                 and returned == controller.json_sha256(plan), 'actual commit is not exact selected plan')
            receipt.update(reported_outcome='accepted', actual_plan_sha256=returned,
                trace_event_index=before, trace_seq=event['seq'], trace_event_sha256=controller.json_sha256(event))
        except BaseException as exc:
            receipt.update(reported_outcome='unknown', error={'type': type(exc).__name__, 'message': str(exc)})
            try:
                controller.write_new(directory/'commit_receipt.json', receipt)
                store.record_commit_receipt(instance_id, intent_id=intent_id, reported_outcome='unknown',
                    receipt_bytes=controller.raw_json(receipt), external_reference={'path': 'commit_receipt.json'})
            except BaseException as secondary: exc.add_note('unknown physical receipt: ' + repr(secondary))
            raise
        receipt_sha = controller.write_new(directory/'commit_receipt.json', receipt)
        recorded = store.record_commit_receipt(instance_id, intent_id=intent_id, reported_outcome='accepted',
            receipt_bytes=controller.raw_json(receipt), external_reference={'path': 'commit_receipt.json', 'sha256': receipt_sha})
        controller.write_new(directory/'commit_receipt_record.json', recorded)
        need(recorded['accepted'], 'physical commit exists but receipt failed; never retry')
        index.append('commit_finished', plan_index=plan_index, branch_id=branch_id, reported_outcome='accepted',
            receipt_sha256=receipt_sha, durable_prefix=prefix(store))
        return receipt
    return physical.commit_once(plan, expected_bootstrap=boot, record_intent_and_commit=one_commit)


def actual_new_commits(physical):
    if physical is None: return 0
    return sum(e['kind'] == 'plan_committed' for e in physical.env.trace[physical.initial_trace_length:])


def check_trace_limit(out, limit):
    path = Path(out)/'physical/trace.jsonl'
    need(not path.exists() or path.stat().st_size <= limit, 'resumed full trace exceeded original byte cap')


def run_segment(segment_path, *, parent_contract, admission, external_authorization_sha256,
                controller, fork_bridge, fresh_bridge, transport_call, authorization_for_call,
                register_after_fork, started_monotonic,
                model='gpt-6-astra', reasoning_effort='medium'):
    """Explicit installed-host entry. Callback authority is outer frozen code, not a bool.

    No call is automatic on import or read-only recovery. A failed segment cannot
    be reused: all paths are create-new. Root must retain original account/guard
    receipts and run the dedicated inherited+suffix audit before accepting.
    """
    now = time.monotonic()
    need(type(started_monotonic) in (int, float) and math.isfinite(started_monotonic)
         and 0 < started_monotonic <= now, 'original outer first-clock required')
    started = started_monotonic; out = Path(segment_path)
    cfg = config_from_admission(admission, segment_path=str(out), parent_contract=parent_contract,
                                model=model, reasoning_effort=reasoning_effort)
    need(callable(transport_call) and callable(authorization_for_call), 'explicit original transport/authority bindings required')
    out.mkdir(parents=False, exist_ok=False)
    controller.write_new(out/'config.json', cfg); controller.write_new(out/'resource_envelope.json', admission)
    controller.write_new(out/'parent_contract.json', parent_contract)
    index = controller.RunIndex(out/'resume_index.jsonl')
    index.append('resume_started', config=cfg, external_authorization_sha256=external_authorization_sha256)
    physical = None; active = None; primary = None; failure = None
    registered_admission = None
    call_count = 0; commit_count = 0; model_index = parent_contract['next_model_index']; plan_index = 1
    need(type(model_index) is int and model_index == 132, 'fixed next global V7 call index required')
    def resources():
        controller.resource_check(out, started=started, wall_seconds=cfg['remaining_runner_wall_seconds'],
            max_log_bytes=cfg['remaining_log_bytes'], max_trace_bytes=cfg['max_trace_bytes'])
        check_trace_limit(out, cfg['max_trace_bytes'])
    try:
        physical = physical_resume.restore(parent_contract, directory=out/'physical', controller=controller,
                                             snapshot_writer=controller.write_snapshot)
        resources()
        while not physical.env.finished:
            resources(); directory = out/f'plan_{plan_index:05d}'; directory.mkdir()
            branch_id = cfg['run_id'] + ':branch:' + str(plan_index); instance_id = branch_id + ':instance'
            boot = controller.bootstrap(physical.env, run_id=parent_contract['parent_run_name'],
                source_sha256=cfg['parent_source_sha256'], page_chars=cfg['page_chars'])
            boot_sha = controller.write_new(directory/'bootstrap.json', boot)
            if plan_index == 1:
                need(controller.same(boot, physical.bootstrap), 'first resumed observation differs')
                store = fork_store.create_fork(directory/'fork', runtime=fork_bridge.durable,
                    parent_directory=parent_contract['parent_store_directory'], parent_store_id=parent_contract['parent_store_id'],
                    parent_prefix=parent_contract['parent_store_prefix'], branch_id=branch_id, instance_id=instance_id,
                    segment_run_path=str(out), external_authorization_sha256=external_authorization_sha256,
                    expected_bootstrap_sha256=controller.json_sha256(boot))
                # The only mapping is appended AFTER exact restore/fork, BEFORE
                # any model reserve. Initial resource_envelope is not admission.
                registered_admission = register_after_fork(store.fork_directory/'fork_manifest.json', store.fork_manifest_sha256)
                controller.write_new(out/'recovery_mapping.json', registered_admission)
                mapped = normalize_mapping(registered_admission, ledger_path=admission['ledger_path'])
                need(controller.same(config_from_admission(mapped, segment_path=str(out), parent_contract=parent_contract,
                    model=model, reasoning_effort=reasoning_effort), cfg)
                    and controller.same(mapped['registration'], admission['registration']), 'actual registered mapping differs from frozen resource/identity envelope')
                api = fork_bridge
            else:
                store = fresh_bridge.durable.IncrementalStore.create(directory/'durable', store_id=branch_id)
                registered = store.register(instance_id, boot)
                controller.write_new(directory/'registration.json', registered)
                need(registered['accepted'], 'new physical state interaction registration rejected')
                api = fresh_bridge
            active = store
            store_id = branch_id
            _, _, contexts = store.inspect_live(expected_store_id=store_id)
            context = next(iter(contexts.values()))
            index.append('plan_opened', plan_index=plan_index, branch_id=branch_id, store_id=store_id,
                instance_id=instance_id, directory=directory.name, bootstrap_file_sha256=boot_sha,
                parent_fork=plan_index == 1, fork_manifest_sha256=getattr(store, 'fork_manifest_sha256', None), context=context)
            while True:
                resources(); remaining = cfg['remaining_runner_wall_seconds'] - (time.monotonic()-started)
                need(remaining >= 1, 'inherited runtime budget exhausted')
                need(registered_admission is not None, 'actual recovery mapping must precede model reservation')
                registration = registered_admission['registration']
                mcfg = controller.ModelConfig(model=model, reasoning_effort=reasoning_effort,
                    timeout_seconds=min(600.0, remaining), ledger_path=admission['ledger_path'],
                    phase=registration['phase'], grant_id=registration['budget_id'],
                    authorization_context={'purpose': 'B', 'arm': 'B', 'scenario': 1701, 'window_seconds': 3600})
                transport = out/f'model_{model_index:05d}'; evidence = out/f'call_{model_index:05d}'
                attempt_id = branch_id + ':model:' + str(model_index)
                index.append('call_started', plan_index=plan_index, branch_id=branch_id, model_index=model_index,
                    attempt_id=attempt_id, transport=transport.name, evidence=evidence.name)
                call_count += 1
                result = api.execute_once(store, expected_store_id=store_id, instance_id=instance_id, attempt_id=attempt_id,
                    model_index=model_index, transport_run_dir=str(transport), evidence_dir=evidence,
                    config=dataclasses.asdict(mcfg), schema=controller.response_schema(), expected_context=context,
                    authorization=authorization_for_call(), transport_call=transport_call, process_success=True)
                index.append('call_finished', plan_index=plan_index, branch_id=branch_id, model_index=model_index,
                    intent_sha256=result['intent_sha256'], outcome_sha256=result['outcome_sha256'],
                    call_id=result.get('call_id'), phase=result['phase'], durable_prefix=result.get('durable_prefix'))
                model_index += 1
                response = verified_reply(result, api=api, store=store, store_id=store_id, instance_id=instance_id)
                if not controller.is_selection_response(response): continue
                evidence = export_current(store, store_id)
                need(evidence['selection'] is not None and controller.same(evidence['selection'], response), 'apply response differs from original selected candidate')
                resources()
                commit_selected(physical, store=store, store_id=store_id, instance_id=instance_id,
                    selection=evidence['selection'], boot=boot, directory=directory, branch_id=branch_id,
                    plan_index=plan_index, index=index, controller=controller)
                commit_count += 1; break
            start = physical.env.t; advanced = physical.advance_once()
            index.append('plan_closed', plan_index=plan_index, branch_id=branch_id, durable_prefix=prefix(store),
                advance_from=start, **advanced)
            plan_index += 1; active = None
    except BaseException as exc:
        primary = exc; failure = {'type': type(exc).__name__, 'message': str(exc)}
        try: controller.write_new(out/'failure.json', {**failure, 'retry_permitted': False})
        except BaseException as secondary: exc.add_note('failure publication: ' + repr(secondary))
    finally:
        result = {'schema': SCHEMA+'-result', 'config': cfg, 'status': 'failed' if failure else 'completed_pending_external_audit',
            'accepted': False, 'full_window_completed': False, 'parent_status_remains': 'failed',
            'new_attempts_entered': call_count, 'new_commits': actual_new_commits(physical),
            'complete_commit_receipts': commit_count, 'next_global_model_index': model_index,
            'failure': failure, 'parent_model_attempts': 132, 'model_usage_not_synthesized': True,
            'scope': 'segment execution record only; original account, inherited+suffix attribution, physics and actual outer resources required'}
        try:
            if physical is not None:
                checkpoint_state = controller.write_snapshot(physical.env, out/'checkpoint.json')
                result.update(simulation_seconds=physical.env.t, horizon_seconds=physical.env.horizon,
                    checkpoint_state_sha256=checkpoint_state, checkpoint_sha256=controller.sha_file(out/'checkpoint.json'),
                    trace_sha256=controller.sha_file(out/'physical/trace.jsonl'),
                    full_window_completed=not failure and physical.env.finished and physical.env.t == 3600.0)
            if active is not None:
                result['final_active_prefix'] = prefix(active)
            resources()
        except BaseException as secondary:
            result.update(status='failed', full_window_completed=False, finalization_error={'type': type(secondary).__name__, 'message': str(secondary)})
            if primary is not None: primary.add_note('resume finalization: ' + repr(secondary))
            else: primary = secondary
        result['segment_wall_seconds_before_publication'] = time.monotonic()-started
        try:
            index.append('resume_stopped', **{k:result[k] for k in ('status','full_window_completed','new_attempts_entered','new_commits')})
            result['index_sha256'] = controller.sha_file(out/'resume_index.jsonl')
            controller.write_new(out/'result.json', result)
        except BaseException as secondary:
            if primary is not None: primary.add_note('resume result publication: ' + repr(secondary))
            else: primary = secondary
    if primary is not None: raise primary
    return result
