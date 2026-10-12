import copy
import json
from pathlib import Path
import unittest

from tests.test_smt_fullfab_constructor_budget import ConstructorBudgetTests
from src.smt_fullfab.constructor_audit import audit_constructor_ledger, audit_constructor_evidence, digest, MODULE, FUNCTION, MODEL, VERSION, FEEDBACK_FIELDS


class ConstructorAuditTests(unittest.TestCase):
    setUp=ConstructorBudgetTests.setUp
    model=ConstructorBudgetTests.model
    construct=ConstructorBudgetTests.construct
    finish=ConstructorBudgetTests.finish

    def rows(self):return [json.loads(line) for line in self.ledger.path.read_text().splitlines()]

    def test_sequential_ledger_preserves_old_scope_and_actual_cost(self):
        cid=self.construct();self.finish(cid)
        self.model()
        report=audit_constructor_ledger(self.rows())
        self.assertEqual(report['errors'],[])
        self.assertEqual(list(report['model_admissions'].values())[-1]['constructor_active_seconds_before'],4)

    def test_ctor_before_authority_and_auto_retry_are_rejected(self):
        cid=self.construct();self.finish(cid);rows=self.rows()
        constructor=next(r for r in rows if r['event']=='constructor_reserve')
        without=[r for r in rows if r['event'] not in ('research_limit_waiver','stage_run_registered')]
        self.assertTrue(audit_constructor_ledger(without)['errors'])
        duplicate=copy.deepcopy(constructor);duplicate['call_id']='new-id'
        self.assertTrue(audit_constructor_ledger(rows+[duplicate])['errors'])

    def test_pending_finish_duration_and_timeout_tampering(self):
        cid=self.construct();self.finish(cid);self.model()
        original=self.rows()
        for case in ('pending','duration','timeout','cp_identity'):
            rows=copy.deepcopy(original)
            if case=='pending':rows=[r for r in rows if r['event']!='constructor_finish']
            elif case=='duration':next(r for r in rows if r['event']=='constructor_finish')['details']['duration_seconds']=-1
            elif case=='timeout':
                next(r for r in reversed(rows) if r['event']=='reserve')['metadata']['timeout_seconds']=200
            else:rows.append({'event':'solver_reserve','call_id':cid,'arm':'C'})
            with self.subTest(case=case):self.assertTrue(audit_constructor_ledger(rows)['errors'])

    def fixture(self):
        run=Path(self.temp.name)/'evidence';run.mkdir();source=self.model();cid=self.construct(source)
        response={'action':'solve','index':None,'method':'constructive','seconds':5,'seed':11,'slots':4,
                  'weights':{'completion':1,'flow':1,'tardiness':2,'setup':1},'reason':'explicit'}
        problem={'time':0,'horizon_end':10,'machines':[],'operations':[]}
        plan={'version':'sample:0','created_at':0,'valid_until':10,'freeze_until':0,'tasks':[],'holds':[]}
        parameters={'time_limit_seconds':5,'seed':11,'weights':response['weights'],'max_slots_per_machine':4,'plan_version':'sample:0'}
        solved={'model':MODEL,'selected_source':'classical_incumbent','solver_status':'FEASIBLE_HEURISTIC','requested_method':'constructive',
            'plan':plan,'tasks':[],'nominal_audit':{'valid':True},'unplanned_operations':{},'best_bound':None,'global_optimality_claim':False,
            'cp_sat':{'status':'NOT_RUN_BY_POLICY','calls':0,'requested_seconds':0},'solver_calls':0,'solver_requested_seconds':0,
            'parameters':{k:v for k,v in parameters.items() if k!='plan_version'}|{'max_candidate_evaluations':250000,'rule':'gain_rate'},
            'seed_semantics':{'used':False,'meaning':'not_used_by_deterministic_constructor'},'invocation_duration_seconds':4,'constructor_call_id':cid}
        self.ledger.finish_constructor(cid,'success',{'duration_seconds':4,'solver_status':'FEASIBLE_HEURISTIC','constructor_result_sha256':digest(solved)})
        ledger=self.rows();reservation=next(r for r in ledger if r['event']=='constructor_reserve')
        reservation['run_id']=str(run);reservation['metadata']['problem_sha256']=digest(problem)
        request={**reservation['metadata'],'constructor_index':0,'constructor_call_id':cid,'call_id':source[0],'requested_seconds':5,
                 'response':response,'parameters':parameters}
        evidence={k:v for k,v in request.items() if k not in ('response','parameters')}
        evidence.update(status='success',duration_seconds=4,constructor_result_sha256=digest(solved))
        feedback={k:solved.get(k) for k in FEEDBACK_FIELDS}
        feedback.update(candidate_index=0,valid_candidate=True,task_count=0,plan_sha256=digest(plan),unplanned_operations_count=0,tasks_preview=[],
            method='constructive',constructor_index=0,constructor_call_id=cid,constructor_requested_seconds=5,constructor_duration_seconds=4,
            classical_construction_wall_seconds=None,nominal_audit=solved['nominal_audit'],seed_semantics=solved['seed_semantics'],error=None)
        entry={'decision':response,'result':feedback}
        values={'constructor_request_000.json':request,'constructor_001.json':solved,'problem_000.json':problem,
            'constructor_evidence.jsonl':[evidence], 'controller_history_events.jsonl':[{'plan_index':0,'model_index':0,'entry':entry}],
            'result.json':{'constructor_calls':1,'constructor_requested_seconds':5,'constructor_active_seconds':4}}
        for name,value in values.items():
            (run/name).write_text('\n'.join(json.dumps(v) for v in value) if name.endswith('jsonl') else json.dumps(value))
        cfg={'arm':'C','enable_constructive':True,'controller_version':VERSION,'constructor_seconds_cap':5,'constructor_evaluation_cap':250000,'run_id':'sample'}
        models={0:{'result':{'status':'success','call_id':source[0],'output':response},'sections':{'OWN_HISTORY':[]}}}
        def read(path,optional=False,lines=False):
            if not path.exists():return None
            text=path.read_text();return [json.loads(line) for line in text.splitlines()] if lines else json.loads(text)
        return run,cfg,models,ledger,read

    def test_complete_synthetic_attempt_passes_independent_evidence(self):
        report=audit_constructor_evidence(*self.fixture())
        self.assertEqual(report['errors'],[]);self.assertEqual(report['missing_evidence'],[])
        self.assertTrue(report['candidates'][0]['valid'])

    def test_source_duration_feedback_and_cp_tamper_fail(self):
        args=self.fixture();run=args[0]
        for file,mutate in (
            ('constructor_request_000.json',lambda x:x['parameters'].update(seed=12)),
            ('constructor_001.json',lambda x:x.update(invocation_duration_seconds=0)),
            ('constructor_001.json',lambda x:x['cp_sat'].update(calls=1)),
            ('controller_history_events.jsonl',lambda x:x['entry']['result'].update(candidate_index=2))):
            original=(run/file).read_text();value=json.loads(original);mutate(value);(run/file).write_text(json.dumps(value))
            with self.subTest(file=file):self.assertTrue(audit_constructor_evidence(*args)['errors'])
            (run/file).write_text(original)

    def test_unsupported_constructor_in_b_never_passes(self):
        args=list(self.fixture());args[1]={'arm':'B'}
        self.assertTrue(audit_constructor_evidence(*args)['errors'])

    def test_missing_finish_cannot_certify_partial_tool(self):
        args=list(self.fixture());args[3]=[r for r in args[3] if r['event']!='constructor_finish']
        self.assertTrue(audit_constructor_evidence(*args)['missing_evidence'])


if __name__=='__main__':unittest.main()
