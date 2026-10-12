"""Complete synthetic raw-channel -> constructor -> explicit apply fixture."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tests.test_smt_fullfab_controller_audit import fixture,write,paging_v2_fixture
from src.smt_fullfab.budget import ROOT,record_sha256
from src.smt_fullfab.constructor_audit import digest,VERSION,MODEL,MODULE,FUNCTION,FEEDBACK_FIELDS
from src.smt_fullfab.controller_audit import audit_controller


def constructive_fixture(root):
    old,ledger=fixture(root)
    run=(root/'runs/smt_fullfab_stage2/C_fixture').resolve();run.parent.mkdir(parents=True);shutil.move(str(old),run)
    approval=json.loads((ROOT/'configs/smt_fullfab/stage2_probe.approved.json').read_text())
    amendment=json.loads((ROOT/'configs/smt_fullfab/research_limit_waiver.approved.json').read_text())
    cfg={'arm':'C','run_id':'C_fixture','seconds':3600,'seed':1901,'budget_id':approval['budget_id'],'amendment_id':amendment['amendment_id'],
         'max_calls':None,'wall_seconds':7200,'max_log_bytes':1000000,'solver_budget_seconds':60,'page_chars':45000,
         'enable_constructive':True,'controller_version':VERSION,'constructor_seconds_cap':5,'constructor_evaluation_cap':250000}
    registration={'run_id':str(run),'arm':'C','scenario':1901,'window_seconds':3600,'solver_seconds':60,'wall_seconds':7200,
                  'max_log_bytes':1000000,'amendment_id':amendment['amendment_id'],'budget_id':approval['budget_id'],'phase':'stage2_research','formal':False}
    registration['registration_id']=record_sha256(registration)
    write(run/'resource_registration.json',registration);write(run/'config.json',cfg)
    provenance=json.loads((run/'provenance.json').read_text())
    for name in ('controller.py','constructive_tool.py','incumbent.py'):
        relative='src/smt_fullfab/'+name;path=run/'source_snapshot'/relative
        path.write_text("C_CONSTRUCTIVE_PROMPT='Synthetic explicit constructor; no execution.'\n" if name=='controller.py' else '# Synthetic provenance fixture; never executed.\n')
        provenance['source_sha256'][relative]=hashlib.sha256(path.read_bytes()).hexdigest()
    write(run/'provenance.json',provenance)
    problem=json.loads((run/'problem_000.json').read_text());manifest,pages=paging_v2_fixture(problem);manifest['observation_end']=3600
    write(run/'page_manifest_000.json',manifest);write(run/'page_000_00.json',pages[0])
    weights={'completion':1,'flow':1,'tardiness':1,'setup':1}
    solve={'action':'solve','index':None,'method':'constructive','seconds':5,'seed':11,'slots':4,'weights':weights,'reason':'explicit construction'}
    apply={'action':'apply','index':0,'method':None,'seconds':None,'seed':None,'slots':None,'weights':weights,'reason':'explicit selection'}
    raw=json.loads((run/'raw_plan_000.json').read_text());raw['version']='C_fixture:0';write(run/'raw_plan_000.json',raw)
    solved={'model':MODEL,'solver_status':'FEASIBLE_HEURISTIC','requested_method':'constructive','plan':raw,'tasks':raw['tasks'],
        'selected_source':'classical_incumbent','nominal_audit':{'valid':True},'unplanned_operations':{},'best_bound':None,'global_optimality_claim':False,
        'cp_sat':{'status':'NOT_RUN_BY_POLICY','calls':0,'requested_seconds':0},'solver_calls':0,'solver_requested_seconds':0,
        'parameters':{'time_limit_seconds':5,'seed':11,'weights':weights,'max_slots_per_machine':4,'max_candidate_evaluations':250000,'rule':'gain_rate'},
        'seed_semantics':{'used':False,'meaning':'not_used_by_deterministic_constructor'},'invocation_duration_seconds':4,'constructor_call_id':'construct-0'}
    feedback={k:solved.get(k) for k in FEEDBACK_FIELDS}
    feedback.update(candidate_index=0,valid_candidate=True,task_count=1,plan_sha256=digest(raw),unplanned_operations_count=0,tasks_preview=raw['tasks'],
        method='constructive',constructor_index=0,constructor_call_id='construct-0',constructor_requested_seconds=5,constructor_duration_seconds=4,
        classical_construction_wall_seconds=None,nominal_audit=solved['nominal_audit'],seed_semantics=solved['seed_semantics'],error=None)
    history=[{'decision':solve,'result':feedback},{'decision':apply,'applied_candidate':0,'plan_sha256':digest(raw)}]
    write(run/'controller_history_000.json',history)
    write(run/'controller_history_events.jsonl',[{'plan_index':0,'model_index':i,'entry':entry} for i,entry in enumerate(history)],lines=True)
    meta={'model_call_id':'model-0','model_index':0,'plan_index':0,'problem_sha256':digest(problem),'max_candidate_evaluations':250000,
        'max_slots_per_machine':4,'method':'constructive','actual_constructor_module':MODULE,'actual_constructor_function':FUNCTION}
    request={**meta,'constructor_index':0,'constructor_call_id':'construct-0','call_id':'model-0','requested_seconds':5,
             'response':solve,'parameters':{'time_limit_seconds':5,'seed':11,'weights':weights,'max_slots_per_machine':4,'plan_version':'C_fixture:0'}}
    write(run/'constructor_request_000.json',request);write(run/'constructor_001.json',solved)
    outcome={k:v for k,v in request.items() if k not in ('response','parameters')}
    outcome.update(status='success',duration_seconds=4,constructor_result_sha256=digest(solved));write(run/'constructor_evidence.jsonl',[outcome],lines=True)
    rows=[{'event':'approval','approval':approval}]
    rows.append({'event':'research_limit_waiver','amendment':amendment,'original_approval_sha256':record_sha256(approval),'prefix_record_count':1,'prior_ledger_sha256':record_sha256(rows)})
    rows.append({'event':'stage_run_registered','registration':registration})
    decisions=[];usage={'input_tokens':11,'output_tokens':7,'cached_input_tokens':0,'cache_write_input_tokens':None,'reasoning_output_tokens':None}
    context={'purpose':'C','arm':'C','scenario':1901,'window_seconds':3600}
    config={'model':'gpt-6-astra','reasoning_effort':'medium','timeout_seconds':180,'grant_id':approval['budget_id'],'phase':'stage2_research','authorization_context':context}
    schema={'type':'object','required':['action','index','method','seconds','seed','slots','weights','reason']}
    summary={'time':0,'horizon_end':20,'observation_end':3600,'machines':1,'operations':1,'pages':1,
             'family_counts':[{'family':'F','machines':1,'operations':1}],'methods_available':['global','decomposed','constructive'],
             'problem_metadata':{k:v for k,v in problem.items() if k not in ('machines','operations')}}
    for i,output in enumerate((solve,apply)):
        account={'attempts':i,'reported_input_output_tokens':18*i,'unknown_completed':[],'pending':[],'model_active_seconds':i,
                 'constructor_calls':i,'constructor_requested_seconds':5*i,'constructor_active_seconds':4*i,'active_execution_seconds':5*i}
        limits={'responses':None,'solver_seconds':60,'model_active_seconds_remaining':7200-5*i,'per_request_solver_seconds':60,
                'per_request_constructor_seconds':5,'constructor_requested_seconds':5*i,'constructor_active_seconds':4*i,'constructor_evaluation_cap':250000}
        prompt='Synthetic explicit constructor; no execution.\nSTATE_DIRECTORY\n'+json.dumps(summary)+'\nOWN_HISTORY\n'+json.dumps(history[:i])+'\nLIMITS\n'+json.dumps(limits)
        directory=run/f'model_{i:03d}';directory.mkdir(exist_ok=True);(directory/'prompt.txt').write_text(prompt);write(directory/'schema.json',schema)
        fingerprint=hashlib.sha256((prompt+'\n'+json.dumps(schema,ensure_ascii=False,indent=2)+'\n'+'\n'+json.dumps(config,sort_keys=True)).encode()).hexdigest()
        request={'call_id':f'model-{i}','config':config,'request_fingerprint':fingerprint}
        write(directory/'request.json',request);write(directory/'result.json',{**request,'status':'success','output':output,'usage':usage,'duration_seconds':1,'native_tool_events':[],'timed_out':False})
        write(directory/'final.txt',output);write(directory/'events.jsonl',[{'type':'turn.completed','usage':{'input_tokens':11,'output_tokens':7,'cached_input_tokens':0}}],lines=True)
        decisions.append({'model_index':i,'call_id':f'model-{i}','plan_index':0,'arm':'C','stage':'C_action','input_problem_sha256':digest(problem),'response_sha256':digest(output),'status':'success'})
        rows.extend([{'event':'reserve','call_id':f'model-{i}','run_id':str(directory),'phase':'stage2_research','amendment_id':amendment['amendment_id'],'registration_id':registration['registration_id'],
            'account_before':account,'run_account_before':account,'metadata':{'model':'gpt-6-astra','reasoning_effort':'medium','timeout_seconds':180,'request_fingerprint':fingerprint,'authorization_context':context}},
            {'event':'finish','call_id':f'model-{i}','status':'success','details':{'usage':usage,'duration_seconds':1}}])
        if i==0:
            before={**account,'attempts':1,'reported_input_output_tokens':18,'model_active_seconds':1,'active_execution_seconds':1}
            rows.extend([{'event':'constructor_reserve','call_id':'construct-0','arm':'C','run_id':str(run),'requested_seconds':5,'metadata':meta,
                'registration_id':registration['registration_id'],'amendment_id':amendment['amendment_id'],'account_before':before,'run_account_before':before},
                {'event':'constructor_finish','call_id':'construct-0','status':'success','details':{'duration_seconds':4,'solver_status':'FEASIBLE_HEURISTIC','constructor_result_sha256':digest(solved)}}])
    write(ledger,rows,lines=True);write(run/'controller_decisions.jsonl',decisions,lines=True)
    trace=[json.loads(line) for line in (run/'trace.jsonl').read_text().splitlines()]
    trace[0]['manifest'].update(horizon=3600,seed=1901);trace[1]['plan']['version']='C_fixture:0';write(run/'trace.jsonl',trace,lines=True)
    write(run/'plan_commits.jsonl',[{'plan_index':0,'model_call_id':'model-1','raw_plan_sha256':digest(raw),'committed_plan_sha256':digest(trace[1]['plan'])}],lines=True)
    write(run/'result.json',{'identity':digest(cfg),'config':cfg,'status':'failed','full_window_completed':False,'model_calls':2,'model_call_ids':['model-0','model-1'],
        'solver_calls':0,'solver_requested_seconds':0,'constructor_calls':1,'constructor_requested_seconds':5,'constructor_active_seconds':4,'plans_committed':1})
    return run,ledger


class ConstructiveControllerAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='smt_fullfab_full_ctor_audit_');self.addCleanup(self.temp.cleanup)
        self.run,self.ledger=constructive_fixture(Path(self.temp.name))

    def audit(self):return audit_controller(self.run,self.ledger)

    def test_complete_explicit_construct_apply_chain_passes_failed_prefix(self):
        report=self.audit();self.assertTrue(report['valid'],report)
        self.assertFalse(report['successful_full_window']);self.assertEqual(report['attribution_checked_plans'],1)

    def test_constructor_plan_cannot_be_replaced_after_model_apply(self):
        path=self.run/'raw_plan_000.json';value=json.loads(path.read_text());value['tasks'][0]['not_before']=1;write(path,value)
        self.assertFalse(self.audit()['valid'])

    def test_missing_model_apply_never_certifies_committed_candidate(self):
        path=self.run/'controller_decisions.jsonl';rows=[json.loads(line) for line in path.read_text().splitlines()];write(path,rows[:1],lines=True)
        self.assertFalse(self.audit()['valid'])

    def test_constructor_cannot_claim_cp_time_or_hidden_feedback(self):
        path=self.run/'constructor_001.json';value=json.loads(path.read_text());value['cp_sat']['requested_seconds']=5;write(path,value)
        self.assertFalse(self.audit()['valid'])

    def add_unattributed_closed_cp(self):
        registration=json.loads((self.run/'resource_registration.json').read_text())
        rows=[json.loads(line) for line in self.ledger.read_text().splitlines()]
        rows.extend([{'event':'solver_reserve','call_id':'hidden-cp','arm':'C','run_id':str(self.run),'requested_seconds':1,
                      'registration_id':registration['registration_id'],'amendment_id':registration['amendment_id']},
                     {'event':'solver_finish','call_id':'hidden-cp','status':'success','details':{'solver_status':'FEASIBLE','wall_seconds':.1}}])
        write(self.ledger,rows,lines=True)
        path=self.run/'result.json';result=json.loads(path.read_text());result.update(solver_calls=1,solver_requested_seconds=1);write(path,result)

    def uncommitted_legacy_cp(self):
        # Use the existing independent complete old-C fixture; preserve both raw
        # model actions, but stop its synthetic physical trace before commit.
        from tests import test_smt_fullfab_controller_audit as old
        from types import SimpleNamespace
        self.run,self.ledger=fixture(Path(self.temp.name)/'legacy_cp')
        old.ControllerAuditTests._make_c_fixture(SimpleNamespace(run=self.run,ledger=self.ledger),redundant_commit_links=False)
        trace=[json.loads(line) for line in (self.run/'trace.jsonl').read_text().splitlines()]
        write(self.run/'trace.jsonl',trace[:1],lines=True);write(self.run/'plan_commits.jsonl',[],lines=True)
        result=json.loads((self.run/'result.json').read_text());result['plans_committed']=0;write(self.run/'result.json',result)

    def test_closed_extra_cp_reservation_without_model_evidence_is_rejected(self):
        self.add_unattributed_closed_cp()
        self.assertFalse(self.audit()['valid'])

    def test_failed_prefix_cannot_omit_solver_request(self):
        self.uncommitted_legacy_cp()
        self.assertTrue(self.audit()['valid'])
        (self.run/'solver_request_000.json').unlink()
        self.assertFalse(self.audit()['valid'])

    def test_duplicate_outcome_for_closed_cp_is_rejected(self):
        self.uncommitted_legacy_cp()
        self.assertTrue(self.audit()['valid'])
        path=self.run/'solver_evidence.jsonl';rows=[json.loads(line) for line in path.read_text().splitlines()]
        write(path,rows+rows,lines=True)
        self.assertFalse(self.audit()['valid'])

    def test_duplicate_outcome_without_request_is_rejected(self):
        self.add_unattributed_closed_cp()
        outcome={'solver_call_id':'hidden-cp','solver_index':0,'requested_seconds':1,'status':'success'}
        write(self.run/'solver_evidence.jsonl',[outcome,outcome],lines=True)
        self.assertFalse(self.audit()['valid'])

    def test_one_model_action_cannot_authorize_two_cp_invocations(self):
        self.uncommitted_legacy_cp();self.assertTrue(self.audit()['valid'])
        request=json.loads((self.run/'solver_request_000.json').read_text())
        request.update(solver_index=1,solver_call_id='synthetic-solver-1');write(self.run/'solver_request_001.json',request)
        solved=json.loads((self.run/'solver_001.json').read_text());write(self.run/'solver_002.json',solved)
        path=self.run/'solver_evidence.jsonl';outcomes=[json.loads(line) for line in path.read_text().splitlines()]
        outcomes.append({**outcomes[0],'solver_index':1,'solver_call_id':'synthetic-solver-1'});write(path,outcomes,lines=True)
        rows=[json.loads(line) for line in self.ledger.read_text().splitlines()]
        reserve=next(row for row in rows if row['event']=='solver_reserve')
        finish=next(row for row in rows if row['event']=='solver_finish')
        rows.extend([{**reserve,'call_id':'synthetic-solver-1'},{**finish,'call_id':'synthetic-solver-1'}]);write(self.ledger,rows,lines=True)
        result=json.loads((self.run/'result.json').read_text());result.update(solver_calls=2,solver_requested_seconds=2);write(self.run/'result.json',result)
        self.assertFalse(self.audit()['valid'])

    def test_orphan_solver_result_is_not_unattributed_evidence(self):
        write(self.run/'solver_001.json',{'solver_status':'FEASIBLE','model':'orphan'})
        self.assertFalse(self.audit()['valid'])

    def test_model_limit_prompt_must_include_actual_constructor_consumption(self):
        path=self.run/'model_001/prompt.txt';path.write_text(path.read_text().replace('7195','7199'))
        self.assertFalse(self.audit()['valid'])


if __name__=='__main__':unittest.main()
