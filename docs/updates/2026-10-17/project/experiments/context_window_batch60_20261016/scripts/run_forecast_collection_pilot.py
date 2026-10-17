#!/usr/bin/env python3
"""Bounded actual-model comparison in the independent copy only."""
from pathlib import Path
import collections
import json
import os
import shutil
import sys
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.dont_write_bytecode = True
os.chdir(ROOT)
from src.smt_fullfab.harness.contracts import digest, encode, fingerprint, sha_bytes, strict_json, HarnessError
from src.smt_fullfab.harness.capacity_config import experiment_config
from src.smt_fullfab.harness import capacity_pilot as pilot
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.transport import call, prompt
from src.smt_fullfab.harness.evaluation import seal_evidence, Evidence, audit_provenance, audit_physical_prefix
from src.smt_fullfab.metrics import compute_metrics
from src.smt_fullfab.harness.planning_batches import revisions

RUN = ROOT / 'live_pilots/forecast_collection_20261017'
FIXTURE = ROOT / 'fixtures/initial/mixed_702.json.z'
MAX_CALLS = 8
EVALUATION_END = 882
TASK = ('Run this small paired experiment with your own production choices. Optimize the declared objectives. '
        'Use the current fixed planning_batch and consult exact missing public details as needed. '
        'Choose feasible ready work and useful follow-up work on busy machines. Preserve valid commitments. '
        'Do not use holds merely to hide demand. A checked candidate still needs your explicit apply_candidate. '
        'Each read, proposal, apply, correction and failed request counts toward eight calls for this group. '
        'The shared observation interval is 702 through 882 simulated seconds, NOT the plan validity interval. '
        'The factory horizon remains 3600; choose a plan validity that includes every retained and added task. '
        'Unassigned work remains pending and ready deadlines do not reset. No algorithm chooses tasks for you.')


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def isolation():
    manifest = strict_json((ROOT/'isolation_manifest.json').read_bytes())
    source = Path(manifest['source_root'])
    changed = [rel for rel, sha in manifest['source_hashes'].items() if sha_bytes((source/rel).read_bytes()) != sha]
    fixtures = [rel for rel, sha in manifest['fixture_sha256'].items() if sha_bytes((ROOT/'fixtures'/rel).read_bytes()) != sha]
    return {'files_checked':len(manifest['source_hashes']), 'changed_source_files':changed, 'changed_fixtures':fixtures,
            'original_run_database_opened':False, 'valid':not changed and not fixtures}


def load_initial():
    return strict_json(zlib.decompress(FIXTURE.read_bytes()))


def prepare():
    before = isolation()
    assert before['valid'], before
    RUN.mkdir(parents=True, exist_ok=False)
    initial = load_initial()
    assert initial['state']['t'] == 702
    configs = {}
    for group in ('G1','G2'):
        cfg = experiment_config(group, seconds=initial['state']['horizon']-initial['state']['t'])
        cfg['capacity_experiment']['model_calls_enabled'] = True
        cfg['model']['timeout_seconds'] = 240
        cfg['limits'].update(attempts=MAX_CALLS, tokens=4500000, model_seconds=1920,
                             wall_seconds=5400, cleanup_seconds=60)
        configs[group] = cfg
        write(RUN/(group+'.config.json'), cfg)
    # Metadata only; never copy login credentials or account identity.
    cache = strict_json((Path.home()/'.codex/models_cache.json').read_bytes())
    models = [m for m in cache['models'] if m['slug'] == configs['G1']['model']['name']]
    assert len(models) == 1
    write(RUN/'model-catalog.json', {'models':models})
    binary = Path('/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex').resolve()
    value = {'schema':pilot.SCHEMA, 'user_instruction':pilot.FORECAST_COLLECTION_INSTRUCTION, 'model_calls_authorized':True,
             'experiment_directory':str(RUN), 'groups':['G1','G2'], 'execution_order':'alternate G1 then G2, at most eight requests per group',
             'evaluation_end':EVALUATION_END, 'model_calls_maximum_total':2*MAX_CALLS, 'per_group_call_cap':MAX_CALLS, 'automatic_retries':0,
             'initial_fixture':str(FIXTURE), 'initial_fixture_sha256':sha_bytes(FIXTURE.read_bytes()),
             'initial_state_sha256':digest(initial['state']), 'initial_trace_sha256':digest(initial['trace']),
             'config_sha256':{g:digest(c) for g,c in configs.items()}, 'fingerprint_sha256':fingerprint()['sha256'],
             'cli_binary':str(binary), 'cli_sha256':sha_bytes(binary.read_bytes()),
             'model_catalog':str(RUN/'model-catalog.json'), 'model_catalog_sha256':sha_bytes((RUN/'model-catalog.json').read_bytes()),
             'catalog_default_context_window':models[0]['context_window'],
             'task':TASK, 'script_sha256':sha_bytes(Path(__file__).read_bytes()),
             'isolation_before':before, 'prepared_epoch':time.time(),
             'analysis_policy':'All attempts counted; no retries after unknown usage. Quality compared on a common observed prefix; no invented terminal or advance without a model commit.'}
    write(RUN/'registration.json',value)
    print(json.dumps({'prepared':str(RUN),'registered_source':value['fingerprint_sha256'],'max_total_calls':2*MAX_CALLS, 'evaluation_end':EVALUATION_END}),flush=True)


def admission(group, reg):
    return {'schema':pilot.SCHEMA, 'group':group, 'experiment_directory':str(RUN), 'experiment_sha256':digest(reg),
            **{k:reg[k] for k in ('cli_binary','cli_sha256','model_catalog','model_catalog_sha256')}}


def backlog(runtime):
    from src.smt_fullfab.harness.batch_window import observe_demands
    problem = runtime.env.problem(plan_seconds=runtime.config['plan_seconds'],lookahead_depth=runtime.config['lookahead_depth'])
    gaps = runtime.env._gaps()
    # Read-only on a clone: measurement must not change stored timer/state.
    from copy import deepcopy
    env = deepcopy(runtime.env)
    demands = observe_demands(env, problem, gaps)
    ledger = env.batch_state['pending_demands']
    pending = [t for tasks in env._pending().values() for t in tasks]
    return {'uncovered_executable_machine_count':len(gaps), 'pending_demand_machine_count':len(ledger),
            'pending_demand_operation_count':len({oid for d in ledger.values() for oid in d['operation_ids']}),
            'uncovered_executable_machines':[g['machine'] for g in gaps],
            'ready_wait_ages':{mid:env.t-since for mid,since in env.batch_state['ready_since'].items()},
            'accepted_pending_task_count':len(pending), 'active_hold_count':len(env._active_holds()),
            'public_operations_total':len(problem['operations']),
            'unoffered_operation_count':sum(env.batch_state['presented_revisions'].get(oid)!=rev for oid,rev in revisions(problem,list(ledger.values())).items()),
            'last_batch_id':(env.batch_state.get('last_batch_receipt') or {}).get('batch_id')}


def outcome(runtime):
    attempts = sorted((a for _,a in runtime.store.rows('attempts')),key=lambda a:a['index'])
    rows=[]
    for a in attempts:
        raw = runtime.store.bytes(a['raw_ref']) if a.get('raw_ref') else b''
        try:
            action=strict_json(raw); action=action.get('action',action)
        except (ValueError,TypeError):action={}
        result=runtime.store.get(a['response_ref']) if a.get('response_ref') else {}
        rows.append({'index':a['index'],'attempt_id':a['attempt_id'],'tool':action.get('tool'),
                     'status':a['status'],'result_status':result.get('status'),'error':result.get('error'),
                     'usage':a['usage'],'duration_seconds':a['duration_seconds'],
                     'packet':runtime.store.read('pilot_packet_measurements',a['attempt_id']),
                     'transport_valid':(a.get('transport') or {}).get('channel_valid')})
    trace=runtime.store.trace(); new=trace[runtime.manifest['prefix_events']:]
    commits=[e for e in new if e['kind']=='plan_committed']
    dispatch=[e for e in new if e['kind']=='dispatch' and e['machine'] in runtime.env.physical]
    return {'group':runtime.manifest['admission']['group'],'head':runtime.head,'usage':runtime.usage(),
            'attempts':rows,'call_types':dict(collections.Counter(r['tool'] or 'transport_failure' for r in rows)),
            'model_commits':len(commits),'production_dispatches':len(dispatch),
            'committed_task_counts':[len(e['plan']['tasks']) for e in commits],
            'stop_reasons':dict(collections.Counter(str(v['stop_reason'].get('reason')) for _,v in runtime.store.rows('feedback'))),
            'backlog':backlog(runtime),'observed_seconds':runtime.env.t-runtime.manifest['start_time']}


def run():
    reg=strict_json((RUN/'registration.json').read_bytes())
    assert sha_bytes(Path(__file__).read_bytes())==reg['script_sha256'], 'Runner changed after registration'
    assert fingerprint()['sha256']==reg['fingerprint_sha256'], 'Source changed after registration'
    runtimes={}; results={}
    try:
        for group in reg['groups']:
            cfg=strict_json((RUN/(group+'.config.json')).read_bytes())
            runtimes[group]=Runtime.start_new(RUN/group,cfg,experiment_id='forecast-collection-paired-live-pilot',
                                             mode='model',initial=load_initial(),admission=admission(group,reg))
            write(RUN/(group+'.initial_backlog.json'),backlog(runtimes[group]))
        for round_number in range(MAX_CALLS):
            for group,runtime in runtimes.items():
                if runtime.head['phase'] in ('STOPPED','AUDITING','CLOSED'):continue
                if runtime.env.t>=reg['evaluation_end']:
                    runtime.stop('pilot_evaluation_end');continue
                print(json.dumps({'event':'call_start','group':group,'round':round_number+1,'sim_time':runtime.env.t}),flush=True)
                try:
                    result=call(runtime,task=reg['task'])
                    print(json.dumps({'event':'call_end','group':group,'round':round_number+1,
                                      'status':result.get('status'),'error':result.get('error'),'usage':runtime.usage()},ensure_ascii=False),flush=True)
                    if runtime.head['phase']=='COMMITTED':
                        feedback=runtime.advance()
                        print(json.dumps({'event':'advance','group':group,'from':feedback['from'],'to':feedback['to'],'dispatches':feedback['dispatch_count_delta'],'reason':feedback['stop_reason']['reason']},ensure_ascii=False),flush=True)
                    if runtime.env.t>=reg['evaluation_end'] and runtime.head['phase'] not in ('STOPPED','AUDITING'):
                        runtime.stop('pilot_evaluation_end')
                except Exception as exc:
                    write(RUN/(group+'.failure.json'),{'type':type(exc).__name__,'detail':str(exc)})
                    if runtime.head['phase'] not in ('STOPPED','CLOSED'):runtime.stop('pilot_exception:'+type(exc).__name__)
                    print(json.dumps({'event':'group_stopped','group':group,'error':str(exc)},ensure_ascii=False),flush=True)
                write(RUN/(group+'.progress.json'),outcome(runtime))
        for group,runtime in runtimes.items():
            if runtime.head['phase'] not in ('STOPPED','AUDITING'):runtime.stop('pilot_attempt_cap')
            result=outcome(runtime)
            result['evidence_sha256']=seal_evidence(runtime)
            results[group]=result
            write(RUN/(group+'.result.json'),result)
    finally:
        for runtime in runtimes.values():runtime.close()
    report()


def report():
    results={g:strict_json((RUN/(g+'.result.json')).read_bytes()) for g in ('G1','G2')}
    start=702.; common_end=min(r['head']['time'] for r in results.values())
    for group,result in results.items():
        ev=Evidence(RUN/group,result['evidence_sha256'])
        trace=[ev.get(ref) for ref in ev.value['physical']]
        cfg=ev.manifest['config']; cap=cfg['capacity_experiment']
        policy={'policy':cap['policy'],'anchor':start,**{k:cap[k] for k in
                 ('max_ready_wait_seconds','planning_lead_seconds','input_token_budget','capacity_trigger_fraction','forecast_min_interval_seconds','forecast_lookahead_seconds')}}
        result['provenance_audit']=audit_provenance(ev,trace)
        audit=audit_physical_prefix(trace,result['head']['time'],cfg['priority_weights'],batching_policy=policy)
        result['physical_prefix_errors']=audit['errors']
        result['opportunity_audit']=audit['opportunity_audit']
        if result['head']['time']>start:
            result['own_observed_metrics']=compute_metrics(trace,window_start=start,window_end=result['head']['time'],priority_weights=cfg['priority_weights'])
        else:result['own_observed_metrics']=None
        result['common_metrics']=compute_metrics(trace,window_start=start,window_end=common_end,priority_weights=cfg['priority_weights']) if common_end>start else None
        result['initial_backlog']=strict_json((RUN/(group+'.initial_backlog.json')).read_bytes())
    value={'schema':pilot.SCHEMA,'common_window':[start,common_end],'target_window':[702,EVALUATION_END],
           'results':results,'isolation_after':isolation(),'limitations':[
               'One paired saved-state pilot; not a statistical quality conclusion.',
               'Production choices affect random draw order, so the shared initial RNG is not a guarantee of identical realized processing times.',
               'Simulation pauses for decisions; model latency is reported separately from simulated machine waiting.',
               'A 60-second demand deadline triggers planning; it does not guarantee a successful model schedule within 60 seconds.',
               'No terminal is fabricated for a partial observation; original horizon is retained.',
               'Local o200k token estimates and requested windows are distinct from service-reported input tokens.']}
    write(RUN/'comparison.json',value)
    print(json.dumps({'event':'complete','common_window':value['common_window'], 'groups':{g:{k:r[k] for k in ('usage','observed_seconds','model_commits','production_dispatches','stop_reasons','physical_prefix_errors')} for g,r in results.items()},'isolation':value['isolation_after']},ensure_ascii=False),flush=True)


if __name__=='__main__':
    {'prepare':prepare,'run':run,'report':report}[sys.argv[1]]()
