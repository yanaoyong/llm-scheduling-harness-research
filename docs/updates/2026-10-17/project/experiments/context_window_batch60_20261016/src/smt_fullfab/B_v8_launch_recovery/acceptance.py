"""Independent attribution for one failed V7 prefix plus an explicit recovery.

Never rewrites the failed parent as successful. Full streaming physics audit and
the original outer-process resource receipt are additionally required.
"""
from base64 import b64decode
import hashlib
import json
from pathlib import Path
import time


def need(value, message):
    if not value: raise ValueError(message)


def attribution(out, *, parent, controller, api, transport, ledger_path):
    """Read actual original files. No model calls, physical advance or ledger fix."""
    out, parent, ledger_path = Path(out), Path(parent), Path(ledger_path)
    class ReadOnlyLedger(transport.BudgetLedger):
        def reserve(self, **kwargs):
            raise ValueError('acceptance cannot reserve a model request')
        def finish(self, *args, **kwargs):
            raise ValueError('acceptance cannot repair a missing ledger completion')
    begun = time.monotonic(); raw_ledger = ledger_path.read_bytes()
    ledger = [json.loads(line) for line in raw_ledger.splitlines()]
    same, digest, read = controller.same, controller.json_sha256, controller.load_json
    result = read(out/'result.json'); prior = read(parent/'result.json')
    need(prior['status']=='failed' and prior['accepted'] is False, 'failed parent changed')
    need(result['status']=='completed_pending_external_audit' and result['full_window_completed'] is True
         and result['simulation_seconds']==result['horizon_seconds']==3600.0, 'recovery not terminal at original absolute target')
    need(result['config']['model']=='gpt-6-astra' and result['config']['reasoning_effort']=='medium', 'model changed')
    rows = controller.read_index(out/'resume_index.jsonl', expected_sha256=result['index_sha256'])
    oldrows = controller.read_index(parent/'delta_index.jsonl', expected_sha256=prior['index_sha256'])
    need(rows[0]['event']=='resume_started' and rows[-1]['event']=='resume_stopped', 'unclosed recovery index')
    opened, closed, calls, finishes, intents, receipts = {}, {}, {}, {}, {}, {}
    for row in rows[1:-1]:
        event, p = row['event'], row['payload']; pi = p['plan_index']
        if event=='plan_opened':
            need(pi==len(opened)+1 and (pi==1 or pi-1 in closed), 'recovery plans not continuous from1')
            need(p['store_id']==p['branch_id']==out.name+':branch:'+str(pi)
                 and p['instance_id']==p['branch_id']+':instance', 'branch identity differs')
            opened[pi]=p
        elif event=='call_started':
            mi=p['model_index'];need(mi==188+len(calls) and pi in opened and pi not in closed, 'global call reset/reuse')
            need(mi==188 or mi-1 in finishes, 'unresolved new prior call')
            need(p['attempt_id']==opened[pi]['branch_id']+':model:'+str(mi), 'call lacks new branch identity')
            calls[mi]=p
        elif event=='call_finished':
            mi=p['model_index'];need(mi in calls and mi not in finishes and calls[mi]['plan_index']==pi, 'unmatched call finish')
            finishes[mi]=p
        elif event in ('commit_intent','commit_finished','plan_closed'):
            target={'commit_intent':intents,'commit_finished':receipts,'plan_closed':closed}[event]
            need(pi in opened and pi not in closed and pi not in target, 'duplicate or stale plan completion')
            if event=='commit_finished':need(pi in intents, 'receipt before intent')
            if event=='plan_closed':need(pi in receipts, 'advance before explicit receipt')
            target[pi]=p
        else:raise ValueError('unexpected recovery event: '+event)
    need(set(opened)==set(closed)==set(intents)==set(receipts) and set(calls)==set(finishes), 'unfinished recovery action')
    need(result['new_commits']==len(opened) and result['new_attempts_entered']==len(calls), 'actual counts differ')
    old = {name:{r['payload']['plan_index']:r['payload'] for r in oldrows if r['event']==name}
           for name in ('plan_opened','plan_closed','commit_intent','commit_finished')}
    need(set(old['commit_finished'])=={0}, 'parent committed prefix differs')
    plans = {}
    checked_calls = {}
    for pi in [0, *opened]:
        owner=parent if pi==0 else out
        item=old['plan_opened'][0] if pi==0 else opened[pi]
        close=old['plan_closed'][0] if pi==0 else closed[pi]
        intent=old['commit_intent'][0] if pi==0 else intents[pi]
        receipt_ref=old['commit_finished'][0] if pi==0 else receipts[pi]
        directory=owner/f'plan_{pi:05d}'
        need(item['directory']==directory.name, 'plan directory remapping')
        boot=controller.bound_json(directory/'bootstrap.json',item['bootstrap_file_sha256'])
        if pi == 0:
            proof, ev = controller.export_one(directory/'durable', store_id=item['store_id'],
                prefix=close['durable_prefix'], instance_id=item['instance_id'])
        else:
            proof = api.durable.export_verified_interaction(directory/'durable',
                expected_store_id=item['store_id'], expected_prefix=close['durable_prefix'])
            need(proof['valid'] and proof['pure_replay_verified'] and len(proof['interactions']) == 1,
                 'full fresh protocol evidence required')
            interaction = proof['interactions'][0]
            need(proof['instances'] == {item['instance_id']: interaction['interaction_id']},
                 'fresh instance differs')
            ev = interaction['evidence']
        need(proof['valid'] and proof['pure_replay_verified'] and same(ev['bootstrap'],boot), 'complete pure interaction differs')
        histories=ev['history']
        expected_old=list(range(79)) if pi==0 else []
        expected_new=[mi for mi,p in calls.items() if p['plan_index']==pi] if pi else []
        need([h['model_index'] for h in histories]==expected_old+expected_new, 'history omitted, duplicated or absorbed failed131')
        for h in histories:
            mi=h['model_index'];call_owner=parent if mi<188 else out;d=call_owner/f'model_{mi:05d}'
            raw_result=(d/'result.json').read_bytes();record=json.loads(raw_result)
            need(record['status']=='success' and record['call_id']==h['call_id'], 'processed history lacks actual successful transport')
            need(sum(r.get('event')=='finish' and r.get('call_id')==record['call_id'] for r in ledger)==1,
                 'read-only verification forbids completion repair')
            verified=transport.call_model((d/'prompt.txt').read_text(),read(d/'schema.json'),d,record['config'],resume=True,
                                          ledger_factory=ReadOnlyLedger)
            need(same(verified,record) and (d/'result.json').read_bytes()==raw_result, 'original transport verification differs')
            final=(d/'final.txt').read_bytes();prompt=(d/'prompt.txt').read_bytes()
            need(b64decode(h['raw_output_base64'],validate=True)==final
                 and hashlib.sha256(final).hexdigest()==h['raw_output_sha256']
                 and hashlib.sha256(prompt).hexdigest()==h['issued_prompt_sha256'], 'pure history differs from actual output/prompt')
            if mi>=188:
                finished=finishes[mi];issued=calls[mi]
                need(issued['transport']==d.name and issued['evidence']==f'call_{mi:05d}' and finished['call_id']==h['call_id'], 'new call attribution remapped')
                evidence=out/issued['evidence'];bi=controller.bound_json(evidence/'intent.json',finished['intent_sha256'])
                bo=controller.bound_json(evidence/'outcome.json',finished['outcome_sha256'])
                need(bi['expected_store_id']==item['store_id'] and bi['instance_id']==item['instance_id']
                     and bi['attempt_id']==issued['attempt_id'] and bi['transport_run_dir']==str(d)
                     and same(bi['config'],record['config']) and same(bi['expected_context'],item['context']), 'original bridge identity differs')
                classified=api.binding.verify_envelope(record['output'],prompt.decode(),item['context'],read(d/'schema.json'))
                kind=classified['kind']
                need(finished['phase']==('action_processed' if kind=='action' else 'envelope_rejected_recorded'),
                     'actual wrapper classification differs from saved processing route')
                controller.verify_history_kind(h,kind)
                need(bo['call_id']==h['call_id'] and bo['phase']==finished['phase'] and not bo['errors'], 'bridge outcome conflicts')
            need(mi not in checked_calls, 'model action reused across plan histories')
            checked_calls[mi]=record['call_id']
        selection=ev['selection'];need(selection and selection['status']=='selection_for_external_commit', 'missing explicit model apply')
        plan=selection['candidate']['compiled']['plan']
        need(intent['selection_sha256']==digest(selection) and intent['plan_sha256']==digest(plan), 'intent selected different plan')
        need(same(controller.bound_json(directory/'selected_plan.json',intent['selected_plan_file_sha256']),plan), 'selected plan changed')
        receipt=controller.bound_json(directory/'commit_receipt.json',receipt_ref['receipt_sha256'])
        need(receipt['reported_outcome']==receipt_ref['reported_outcome']=='accepted'
             and receipt['plan_sha256']==digest(plan) and receipt['trace_event_index']==intent['trace_event_index'], 'physical receipt differs')
        idx=receipt['trace_event_index'];need(idx not in plans, 'commit event reused')
        plans[idx]=(pi,boot,plan,receipt,close)
    expected_reserves=[r['call_id'] for r in ledger if r.get('event')=='reserve' and str(Path(r['run_id']).parent)==str(out)]
    need(expected_reserves==[finishes[i]['call_id'] for i in calls], 'new ledger call count/order differs')
    # Failed parent131 remains recorded, with no synthesized output/action.
    failed=read(parent/'model_00131/result.json')
    need(failed['status']=='failed' and failed['usage_status']=='unknown' and failed['output'] is None
         and not (parent/'model_00131/final.txt').exists(), 'failed parent request was repaired/reclassified')
    raw_parent_trace=(parent/'trace.jsonl').read_bytes();trace_path=out/'physical/trace.jsonl'
    seal=controller.inspect_jsonl(trace_path,expected_sha256=result['trace_sha256'])
    envelope=controller.scan_envelope(seal,require_terminal=True)
    need(envelope.snapshot_count==1 and envelope.first_time==0 and envelope.horizon==3600, 'trace is not original continuous one-hour window')
    prior_events=[json.loads(x) for x in raw_parent_trace.splitlines()]
    previous=None;executed=set();operations=set();commits=0;last_stop=0;dispatches=0
    with controller.open_verified(seal) as reader:
        for rec in reader:
            event=rec.event;idx=rec.event_index
            if idx<len(prior_events):need(same(event,prior_events[idx]), 'complete original trace prefix changed')
            if idx==0:
                physical=set(event['manifest']['controlled_machine_ids']);need(len(physical)==913,'production scope differs')
                horizon=event['manifest']['horizon'];need(horizon==3600.0,'original horizon differs')
            if event['kind']=='snapshot_loaded':
                checkpoint=read(parent/'checkpoint.json')
                need(idx==len(prior_events) and event['prefix_event_count']==idx
                     and event['snapshot_sha256']==checkpoint['state_sha256'] and event['time']==803.2499999999999,'restore lineage differs')
            elif event['kind']=='plan_committed':
                need(idx in plans,'unattributed physical commit');pi,boot,plan,receipt,close=plans[idx]
                need(pi==commits and same(event['plan'],plan) and digest(event)==receipt['trace_event_sha256'], 'physical commit not exact selected plan')
                base=previous if previous is not None else controller.cold_base(parent.name,event['time'],horizon,sorted(physical))
                state=boot['execution_state']
                need(same(boot['base_plan'],base) and state['time']==event['time'] and state['observation_end']==3600
                     and state['base_plan_version']==base['version'] and same(state['dispatched_task_ids'],
                     [t['id'] for t in base['tasks'] if (base['version'],t['id']) in executed]),'base/executed state not actual history')
                need(set(boot['problem']['scope'])==physical and close['advance_from']==event['time']
                     and close['advance_target']==controller.next_boundary(event['time'],0,3600,1800)
                     and event['time']<=close['simulation_seconds']<=close['advance_target'],'absolute execution target changed')
                if pi:need(last_stop==event['time'],'resume skipped physical interval')
                last_stop=close['simulation_seconds'];previous=plan;commits+=1
            elif event['kind']=='dispatch' and event['machine'] in physical:
                need(previous is not None and event.get('owner')=='plan' and event.get('plan_version')==previous['version'],'unplanned production dispatch')
                key=(event['plan_version'],event.get('plan_task_id'));need(key not in executed,'same task executed twice');executed.add(key)
                identities=list(zip(event['lots'],event['steps'],event['visits']))
                need(not operations.intersection(identities),'original or resumed operation executed twice');operations.update(identities);dispatches+=1
    need(commits==len(plans) and last_stop==3600 and ledger_path.read_bytes()==raw_ledger,'terminal closure or original ledger changed')
    return {'schema':'smt-B-v8-launch-recovery-attribution-v1','valid':True,'parent_status':'failed',
        'resumed_continuous_window_seconds':3600,'start_of_recovery':803.2499999999999,'new_model_calls_during_audit':0,
        'original_and_new_committed_branch_action_count':len(checked_calls), 'preserved_ancestor_attempts':188,'new_attempts':len(calls),'plans':commits,
        'production_dispatches':dispatches,'new_call_ids':expected_reserves,'snapshot_count':1,
        'physical_audit_still_required':True,'actual_outer_resource_acceptance_still_required':True,
        'wall_seconds':time.monotonic()-begun,'trace_sha256':result['trace_sha256']}
