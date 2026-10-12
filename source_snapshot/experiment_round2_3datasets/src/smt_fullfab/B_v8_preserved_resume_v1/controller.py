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

from src.smt_fullfab.B_resume_v1 import fork_store, physical_resume
from . import continuation_bridge as api
from . import continuation_store

SCHEMA = 'smt-B-v8-preserved-segment-controller-v1'
FIRST_MODEL_INDEX = 221
ADMISSION_MARGIN_SECONDS = 660.0


class GracefulAdmissionStop(RuntimeError):
    """Known complete interaction boundary; no next model attempt was started."""


def check_admission_deadline(soft_deadline_monotonic, *, now=None):
    current = time.monotonic() if now is None else now
    if soft_deadline_monotonic-current < ADMISSION_MARGIN_SECONDS:
        raise GracefulAdmissionStop('no new request: less than 600+60 seconds before soft deadline')


def need(condition, message):
    fork_store.need(condition, message)


def config_from_admission(admission, *, segment_path, parent_contract, model, reasoning_effort):
    need(type(admission) is dict and str(Path(segment_path).resolve()) == str(segment_path), 'explicit admitted absolute segment required')
    need(admission['segment_run_id'] == str(segment_path) and admission['parent_run_id'] == parent_contract['parent_run_path'], 'admission run mapping differs')
    need(model == 'gpt-6-astra' and reasoning_effort == 'medium', 'this candidate preserves V7 model; a switch needs a new explicit version')
    remaining = admission['remaining_runner_wall_seconds']
    need(type(remaining) in (int, float) and math.isfinite(remaining) and 0 < remaining <= 86400, 'finite inherited wall remainder required')
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
        'cold_start_only': False, 'fresh_interaction': False, 'discard_uncommitted_drafts': False,
        'first_plan_preserved_interaction': True, 'later_plans_fresh_after_explicit_commit': True,
        'ancestor_model_attempts': FIRST_MODEL_INDEX, 'first_unique_model_index': FIRST_MODEL_INDEX,
        'technical_cumulative_wall_cap_seconds': 86400, 'admission_margin_seconds': 660,
        'protocol_source_separately_bound_by_manifest': True, 'parent_status_remains': 'failed', 'formal': False,
        'automatic_retry': False, 'accepted': False}


def normalize_mapping(value, *, ledger_path):
    """Preserve raw mapping separately; decimal-to-float only for API time limits."""
    from decimal import Decimal
    m = value['mapping']; remaining = m['remaining']
    seconds = Decimal(str(remaining['runner_wall_seconds']))
    need(seconds.is_finite() and seconds > 0, 'invalid inherited wall remainder')
    # Ledger parent remains original V7. Physical parent is the directly closed
    # V8 predecessor; keep the original mapping file unchanged with both fields.
    return {'segment_run_id': m['segment_run_id'], 'parent_run_id': m['predecessor_run_id'],
        'remaining_runner_wall_seconds': float(seconds), 'remaining_log_bytes': remaining['log_bytes'],
        'per_call_timeout_seconds': 600, 'registration': value['registration'], 'ledger_path': str(ledger_path)}


def prefix(store):
    p = store.verify_full(reason='resume_critical_or_terminal')
    return {k: p[k] for k in fork_store.PREFIX}


def export_current(store, store_id):
    proof = store.verify_full(reason='explicit_selection_complete_lineage')
    need(proof['valid'] and proof['pure_replay_verified'] and proof['lineage_verified']
         and proof['store_id'] == store_id and len(proof['interactions']) == 1,
         'complete continuation/fresh interaction selection evidence required')
    return proof['interactions'][0]['evidence']


def verified_reply(result, *, api, store, store_id, instance_id):
    need(result.get('errors') == [], 'new call rejected before processing: ' + repr(result.get('errors')))
    checked = api.verify_live_read_only(result['evidence_dir'], store=store,
        expected_intent_sha256=result['intent_sha256'], expected_outcome_sha256=result['outcome_sha256'])
    need(result.get('phase') in ('action_processed', 'envelope_rejected_recorded'),
         'Original call retained without action processing: phase=' + str(result.get('phase'))
         + ', transport=' + str(result.get('original_reported_status')) + ', call_id=' + str(result.get('call_id')))
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


def _file_ref(path, controller):
    path = Path(path)
    need(path.is_absolute() and str(path) == str(path.resolve()), 'absolute original file reference required')
    return {'path': str(path), 'sha256': controller.sha_file(path)}


def _preserved_contract(value, *, parent_contract):
    keys = {'parent_directory', 'parent_store_id', 'parent_prefix', 'expected_bootstrap_sha256',
            'profile', 'first_new_model_index', 'parent_interaction_evidence_sha256'}
    need(type(value) is dict and set(value) == keys, 'complete fixed preserved-interaction contract required')
    need(value['profile'] == 'processed_boundary'
         and type(value['first_new_model_index']) is int and value['first_new_model_index'] == FIRST_MODEL_INDEX,
         'this installed segment starts only from the sealed processed boundary at index221')
    need(Path(value['parent_directory']) == Path(parent_contract['parent_run_path'])/'plan_00001/durable'
         and str(Path(value['parent_directory']).resolve()) == value['parent_directory'],
         'preserved DB must be the direct closed parent plan1 original')
    need(type(value['parent_prefix']) is dict and set(value['parent_prefix']) == set(fork_store.PREFIX),
         'full exact parent prefix required')


def prepare_fresh_transition(physical, *, previous, previous_prefix, boot, directory,
                             branch_id, instance_id, model_index, segment_path,
                             external_authorization_sha256, physical_source_manifest, controller):
    """Bind a new public observation to an actual prior explicit commit/checkpoint.

    Does not advance, select, alter a plan, or register another budget account.
    The continuation store validates the original full receipt and snapshot.
    """
    checkpoint_path = directory/'start_checkpoint.json'
    state_sha = controller.write_snapshot(physical.env, checkpoint_path)
    transition = {'schema': continuation_store.TRANSITION_SCHEMA,
        'segment_run_path': str(segment_path), 'external_authorization_sha256': external_authorization_sha256,
        'previous_directory': str(previous.continuation_directory),
        'previous_manifest_sha256': previous.continuation_manifest_sha256,
        'previous_prefix': deepcopy(previous_prefix), 'branch_id': branch_id, 'instance_id': instance_id,
        'first_new_model_index': model_index, 'bootstrap': _file_ref(directory/'bootstrap.json', controller),
        'checkpoint': _file_ref(checkpoint_path, controller), 'checkpoint_state_sha256': state_sha,
        'commit_receipt': _file_ref(previous.continuation_directory.parent/'commit_receipt.json', controller),
        'physical_source_manifest': deepcopy(physical_source_manifest), 'physical_source_sha256': boot['source_sha256']}
    transition_path = directory/'fresh_transition.json'
    transition_sha = controller.write_new(transition_path, transition)
    return continuation_store.create_fresh_after_commit(directory/'durable', runtime=api.durable,
        transition_path=transition_path, expected_transition_sha256=transition_sha)


def run_segment(segment_path, *, parent_contract, preserved_contract, admission,
                external_authorization_sha256, controller, transport_call, authorization_for_call,
                register_after_continuation, started_monotonic, soft_deadline_monotonic,
                physical_source_manifest, model='gpt-6-astra', reasoning_effort='medium'):
    """One explicitly installed continuation, never a cold restart or implicit retry.

    Host configures the original frozen V8 runtime separately from the new binder
    and admission. Callback registers the first continuation manifest once. Later
    plans share that account and use exact fresh public observations after commit.
    soft_deadline is externally anchored; it does not reset the inherited clock.
    """
    now = time.monotonic()
    need(type(started_monotonic) in (int, float) and math.isfinite(started_monotonic)
         and 0 < started_monotonic <= now, 'original outer first-clock required')
    started = started_monotonic; out = Path(segment_path)
    cfg = config_from_admission(admission, segment_path=str(out), parent_contract=parent_contract,
                                model=model, reasoning_effort=reasoning_effort)
    need(out.name == 'B_1701_1h_delta_v8__preserved_001', 'unique explicitly authorized preserved segment required')
    need(type(soft_deadline_monotonic) in (int, float) and math.isfinite(soft_deadline_monotonic)
         and started < soft_deadline_monotonic <= started+cfg['remaining_runner_wall_seconds'],
         'soft deadline must be inside original cumulative remaining wall')
    _preserved_contract(preserved_contract, parent_contract=parent_contract)
    need(type(physical_source_manifest) is dict and set(physical_source_manifest) == {'path', 'sha256'},
         'original physical source manifest reference required')
    source_raw, source_ref = continuation_store.read(physical_source_manifest['path'], physical_source_manifest['sha256'])
    source = api.durable.decode(source_raw)
    need(source['source_sha256'] == controller.json_sha256(source['files']) == cfg['parent_source_sha256'],
         'physical source manifest differs from original observation source')
    need(callable(transport_call) and callable(authorization_for_call) and callable(register_after_continuation),
         'explicit original transport/authority and preserved-registration callbacks required')
    api.runtime_ready()
    need(api.binding.authorization_package_sha256() == external_authorization_sha256,
         'continuation admission package differs from controller authorization')
    out.mkdir(parents=False, exist_ok=False)
    controller.write_new(out/'config.json', cfg); controller.write_new(out/'resource_envelope.json', admission)
    controller.write_new(out/'parent_contract.json', parent_contract)
    controller.write_new(out/'preserved_contract.json', preserved_contract)
    controller.write_new(out/'execution_deadlines.json', {'started_monotonic': started,
        'soft_deadline_monotonic': soft_deadline_monotonic, 'admission_margin_seconds': 660,
        'outer_hard_deadline_not_owned_here': True})
    index = controller.RunIndex(out/'resume_index.jsonl')
    index.append('resume_started', config=cfg, external_authorization_sha256=external_authorization_sha256)
    physical = None; active = None; previous = None; previous_prefix = None
    primary = None; failure = None; registered_admission = None
    call_count = 0; commit_count = 0; model_index = FIRST_MODEL_INDEX; plan_index = 1
    def resources():
        controller.resource_check(out, started=started, wall_seconds=cfg['remaining_runner_wall_seconds'],
            max_log_bytes=cfg['remaining_log_bytes'], max_trace_bytes=cfg['max_trace_bytes'])
        check_trace_limit(out, cfg['max_trace_bytes'])
        continuation_store.fence(source_ref)
    try:
        physical = physical_resume.restore(parent_contract, directory=out/'physical', controller=controller,
                                             snapshot_writer=controller.write_snapshot)
        resources()
        while not physical.env.finished:
            resources(); check_admission_deadline(soft_deadline_monotonic)
            directory = out/f'plan_{plan_index:05d}'; directory.mkdir()
            branch_id = cfg['run_id'] + ':branch:' + str(plan_index); instance_id = branch_id + ':instance'
            boot = controller.bootstrap(physical.env, run_id=parent_contract['parent_run_name'],
                source_sha256=cfg['parent_source_sha256'], page_chars=cfg['page_chars'])
            boot_sha = controller.write_new(directory/'bootstrap.json', boot)
            if plan_index == 1:
                need(controller.same(boot, physical.bootstrap)
                     and controller.json_sha256(boot) == preserved_contract['expected_bootstrap_sha256'],
                     'first resumed physical/public observation differs from preserved interaction')
                store = continuation_store.create_continuation(directory/'durable', runtime=api.durable,
                    parent_directory=preserved_contract['parent_directory'],
                    parent_store_id=preserved_contract['parent_store_id'], parent_prefix=preserved_contract['parent_prefix'],
                    branch_id=branch_id, instance_id=instance_id, segment_run_path=str(out),
                    external_authorization_sha256=external_authorization_sha256,
                    expected_bootstrap_sha256=preserved_contract['expected_bootstrap_sha256'],
                    profile=preserved_contract['profile'], first_new_model_index=model_index)
                active = store
                need(store.manifest['parent_interaction_evidence_sha256'] == preserved_contract['parent_interaction_evidence_sha256'],
                     'preserved full history/draft/memory differs from external cold proof')
                registered_admission = register_after_continuation(
                    store.continuation_directory/'continuation_manifest.json', store.continuation_manifest_sha256)
                controller.write_new(out/'recovery_mapping.json', registered_admission)
                mapped = normalize_mapping(registered_admission, ledger_path=admission['ledger_path'])
                need(controller.same(config_from_admission(mapped, segment_path=str(out), parent_contract=parent_contract,
                    model=model, reasoning_effort=reasoning_effort), cfg)
                    and controller.same(mapped['registration'], admission['registration']), 'registered preserved mapping differs')
            else:
                need(previous is not None and previous_prefix is not None and registered_admission is not None,
                     'fresh logical plan requires the previous explicit commit and same registered account')
                store = prepare_fresh_transition(physical, previous=previous, previous_prefix=previous_prefix,
                    boot=boot, directory=directory, branch_id=branch_id, instance_id=instance_id,
                    model_index=model_index, segment_path=out, external_authorization_sha256=external_authorization_sha256,
                    physical_source_manifest=physical_source_manifest, controller=controller)
                active = store
            store_id = branch_id
            _, _, contexts = store.inspect_live(expected_store_id=store_id)
            need(len(contexts) == 1, 'one original pure interaction expected')
            context = next(iter(contexts.values()))
            index.append('plan_opened', plan_index=plan_index, branch_id=branch_id, store_id=store_id,
                instance_id=instance_id, directory=directory.name, bootstrap_file_sha256=boot_sha,
                continuation_manifest_sha256=store.continuation_manifest_sha256,
                parent_fork=plan_index == 1, fresh_interaction=plan_index != 1,
                logical_plan_kind='preserved' if plan_index == 1 else 'fresh_after_commit', context=context)
            while True:
                resources(); check_admission_deadline(soft_deadline_monotonic)
                need(registered_admission is not None, 'actual preserved mapping must precede model reservation')
                registration = registered_admission['registration']
                mcfg = controller.ModelConfig(model=model, reasoning_effort=reasoning_effort,
                    timeout_seconds=600.0, ledger_path=admission['ledger_path'],
                    phase=registration['phase'], grant_id=registration['budget_id'],
                    authorization_context={'purpose': 'B', 'arm': 'B', 'scenario': 1701, 'window_seconds': 3600})
                transport = out/f'model_{model_index:05d}'; evidence_path = out/f'call_{model_index:05d}'
                attempt_id = branch_id + ':model:' + str(model_index)
                # Preview is read-only; if it consumes the margin, no attempt starts.
                response_schema = store.preview_schema(instance_id)
                check_admission_deadline(soft_deadline_monotonic)
                index.append('call_started', plan_index=plan_index, branch_id=branch_id, model_index=model_index,
                    attempt_id=attempt_id, transport=transport.name, evidence=evidence_path.name)
                call_count += 1
                call_result = api.execute_once(store, expected_store_id=store_id, instance_id=instance_id, attempt_id=attempt_id,
                    model_index=model_index, transport_run_dir=str(transport), evidence_dir=evidence_path,
                    config=dataclasses.asdict(mcfg), schema=response_schema, expected_context=context,
                    authorization=authorization_for_call(), transport_call=transport_call, process_success=True)
                index.append('call_finished', plan_index=plan_index, branch_id=branch_id, model_index=model_index,
                    intent_sha256=call_result['intent_sha256'], outcome_sha256=call_result['outcome_sha256'],
                    call_id=call_result.get('call_id'), phase=call_result['phase'], durable_prefix=call_result.get('durable_prefix'))
                model_index += 1
                response = verified_reply(call_result, api=api, store=store, store_id=store_id, instance_id=instance_id)
                if not controller.is_selection_response(response): continue
                evidence = export_current(store, store_id)
                need(evidence['selection'] is not None and controller.same(evidence['selection'], response),
                     'apply response differs from original selected candidate')
                resources()
                commit_selected(physical, store=store, store_id=store_id, instance_id=instance_id,
                    selection=evidence['selection'], boot=boot, directory=directory, branch_id=branch_id,
                    plan_index=plan_index, index=index, controller=controller)
                commit_count += 1; break
            start = physical.env.t; advanced = physical.advance_once()
            closed_prefix = prefix(store)
            index.append('plan_closed', plan_index=plan_index, branch_id=branch_id, durable_prefix=closed_prefix,
                advance_from=start, **advanced)
            previous = store; previous_prefix = closed_prefix
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
            'failure': failure, 'parent_model_attempts': FIRST_MODEL_INDEX, 'model_usage_not_synthesized': True,
            'graceful_admission_stop': isinstance(primary, GracefulAdmissionStop),
            'scope': 'segment execution only; inherited+suffix attribution, original costs, physics and actual outer resources required'}
        try:
            if physical is not None:
                checkpoint_state = controller.write_snapshot(physical.env, out/'checkpoint.json')
                result.update(simulation_seconds=physical.env.t, horizon_seconds=physical.env.horizon,
                    checkpoint_state_sha256=checkpoint_state, checkpoint_sha256=controller.sha_file(out/'checkpoint.json'),
                    trace_sha256=controller.sha_file(out/'physical/trace.jsonl'),
                    full_window_completed=not failure and physical.env.finished and physical.env.t == 3600.0)
            if active is not None:
                # Poison is a hard failure; never replace this with a guessed prefix.
                result['final_active_prefix'] = prefix(active)
            resources()
        except BaseException as secondary:
            result.update(status='failed', full_window_completed=False,
                finalization_error={'type': type(secondary).__name__, 'message': str(secondary)})
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


