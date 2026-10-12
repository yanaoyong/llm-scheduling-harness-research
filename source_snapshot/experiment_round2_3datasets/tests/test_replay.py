"""Synthetic evidence mutation tests, offline only; no model/solver is invoked."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import src.replay as audit
from src.experiment import object_digest
from src.agents.static import observed_problem, compact_problem

ROOT=Path(__file__).resolve().parents[1]
COMMIT='a'*40
P={'schema_version':'fjsp-1','instance_id':'unit','family':'unit','machines':[0],
   'jobs':[{'id':0,'operations':[{'id':'j0o0','job':0,'index':0,'alternatives':[{'machine':0,'duration':2}]}]}]}
S={'operations':[{'id':'j0o0','machine':0,'start':0,'end':2}]}
OUTPUT={'order':[{'id':'j0o0','machine':0}],'rationale':'synthetic unit test only'}

def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

def sha(data): return hashlib.sha256(data).hexdigest()

class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='replay-unit-',dir=ROOT/'tests')
        self.root=Path(self.temp.name)
        self.patches=[patch('src.replay.ROOT',self.root),patch('src.replay._git',side_effect=self.git)]
        for p in self.patches:p.start()
        self.blobs={}
        self.build()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def git(self,root,*args):
        if args==('cat-file','-t',COMMIT):return b'commit\n'
        if args==('rev-parse','unit-freeze^{commit}'):return (COMMIT+'\n').encode()
        if len(args)==2 and args[0]=='show' and args[1].startswith(COMMIT+':'):
            return self.blobs[args[1].split(':',1)[1]]
        raise ValueError('unknown synthetic git evidence')
    def build(self,phase='development',compact=False):
        self.run=self.root/'runs'/phase/'unit_B_r1'
        self.model=self.run/'agent/model_call_001'
        self.model.mkdir(parents=True,exist_ok=True)
        modelcfg={'phase':'development' if phase=='development' else 'formal','grant_id':'unit','model':'gpt-6-astra','reasoning_effort':'medium','timeout_seconds':2}
        cfg={'model':modelcfg,'max_model_calls':1,'solver_budget_seconds':2,'protocol_version':'unit-v1','seed':11}
        if compact: cfg['compact_state']=True
        output={'order':[[0,0]],'rationale':'synthetic compact unit test'} if compact else OUTPUT
        prompt='UNIT TEST\nProblem:\n'+json.dumps(compact_problem(P) if compact else observed_problem(P))
        schema='{}\n'
        fingerprint=sha((prompt+'\n'+schema+'\n'+json.dumps(modelcfg,sort_keys=True)).encode())
        usage={'input_tokens':20,'cached_input_tokens':0,'output_tokens':10,'cache_write_input_tokens':0,'reasoning_output_tokens':2}
        events=[{'type':'thread.started','thread_id':'unit'},
                {'type':'item.completed','item':{'type':'agent_message','text':json.dumps(output)}},
                {'type':'turn.completed','usage':usage}]
        (self.model/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
        (self.model/'prompt.txt').write_text(prompt);(self.model/'schema.json').write_text(schema)
        dump(self.model/'final.txt',output)
        saved={'call_id':'model-unit','status':'success','returncode':0,'config':modelcfg,'request_fingerprint':fingerprint,
               'output':output,'usage':usage,'duration_seconds':1,'model_elapsed_seconds':1,
               'native_tool_events':[],'completed_turns':1,'thread_ids':['unit']}
        dump(self.model/'request.json',{'call_id':'model-unit','config':modelcfg,'request_fingerprint':fingerprint})
        dump(self.model/'result.json',saved)
        identity={'instance_id':'unit','arm':'B','repeat':1,'config_sha256':object_digest(cfg),'data_sha256':object_digest(P)}
        self.blobs={'src/unit.py':b'# synthetic source\n','configs/evaluation.json':(json.dumps(cfg,indent=2)+'\n').encode(),
                    'data/fjsp/instances/unit.json':(json.dumps(P,indent=2)+'\n').encode()}
        hashes={rel:sha(self.blobs[rel]) for rel in ('src/unit.py','configs/evaluation.json')}
        for rel in hashes:
            file=self.run/'source_snapshot'/rel;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(self.blobs[rel])
        r={'run_id':'unit_B_r1','instance_id':'unit','arm':'B','repeat':1,'phase':phase,'family':'unit','identity':identity,
           'code_commit':COMMIT,'source_sha256':hashes,'protocol_version':'unit-v1',
           'config_sha256':identity['config_sha256'],'data_sha256':identity['data_sha256'],
           'status':'success','schedule':S,'validation':{'valid':True,'errors':[],'makespan':2},
           'metrics':{'makespan':2},'actions':[output],'model_results':[saved],'solver_results':[],
           'costs':{'model_calls':1,'model_elapsed_seconds':1,'usage':usage,'solver_calls':0,'solver_budget_seconds':0,'end_to_end_seconds':2},
           'started_at':'2026-10-09T00:00:00+00:00','finished_at':'2026-10-09T00:00:02+00:00'}
        if phase!='development':r['freeze_tag']='unit-freeze'
        dump(self.run/'result.json',r);dump(self.run/'input.json',P);dump(self.run/'schedule.json',S);dump(self.run/'config.json',cfg)
        dump(self.run/'started.json',{k:r[k] for k in ('identity','code_commit','config_sha256','data_sha256','protocol_version','source_sha256')})
        ledger=[{'event':'reserve','call_id':'model-unit','run_id':str(self.model),'phase':modelcfg['phase'],'grant_id':'unit'},
                {'event':'finish','call_id':'model-unit','status':'success','details':{'usage':usage,'duration_seconds':1}}]
        (self.root/'progress').mkdir(exist_ok=True)
        (self.root/'progress/model_ledger.jsonl').write_text(''.join(json.dumps(v)+'\n' for v in ledger))
        if phase!='development':
            self.freeze={'phase':phase,'tag':'unit-freeze','code_commit':COMMIT,'protocol_version':'unit-v1',
                         'config_path':'configs/evaluation.json','effective_config_sha256':{'1':object_digest(cfg)},
                         'files':{rel:sha(blob) for rel,blob in self.blobs.items()},'matrix':[['unit','B',1]]}
            dump(self.root/'configs/freezes/unit.json',self.freeze)
            dump(self.run/'freeze.json',self.freeze)
            r['freeze_manifest_sha256']=sha((self.run/'freeze.json').read_bytes())
            dump(self.run/'result.json',r)
            started=json.loads((self.run/'started.json').read_text());started['freeze_manifest_sha256']=r['freeze_manifest_sha256'];dump(self.run/'started.json',started)
    def mutate(self,relative,fn):
        path=self.run/relative;value=json.loads(path.read_text());fn(value);dump(path,value)
    def rejects(self,needle):
        result=audit.replay(self.run)
        self.assertFalse(result['audit_pass'],result)
        self.assertTrue(any(needle in e for e in result['errors']),result['errors'])
    def test_baseline_full_evidence(self):
        r=audit.replay(self.run);self.assertTrue(r['audit_pass'],r);self.assertTrue(r['provenance_complete'])
    def test_compact_decisions_and_problem_are_audited(self):
        self.build(compact=True)
        r=audit.replay(self.run);self.assertTrue(r['audit_pass'],r)
        self.mutate('result.json',lambda r:r['actions'][0].update(order=[[0,99]]))
        self.rejects('ineligible')
    def test_aggregate_tokens_mutation_rejected(self):
        self.mutate('result.json',lambda r:r['costs']['usage'].update(input_tokens=999))
        self.rejects('aggregate input_tokens')
    def test_model_output_not_in_raw_event_rejected(self):
        self.mutate('agent/model_call_001/result.json',lambda r:r.update(output={'order':[]}))
        self.rejects('raw agent_message/final.txt/model output mismatch')
    def test_final_message_mutation_rejected(self):
        dump(self.model/'final.txt',{'order':[]});self.rejects('raw agent_message/final.txt/model output mismatch')
    def test_root_actions_mutation_rejected(self):
        self.mutate('result.json',lambda r:r['actions'][0].update(rationale='changed without model'))
        self.rejects('root actions differ')
    def test_unknown_commit_rejected(self):
        self.mutate('result.json',lambda r:r.update(code_commit='0'*40));self.rejects('code_commit does not resolve')
    def test_elapsed_and_call_count_mutation_rejected(self):
        self.mutate('result.json',lambda r:r['costs'].update(model_calls=0,model_elapsed_seconds=99))
        r=audit.replay(self.run);self.assertFalse(r['audit_pass']);self.assertIn('model request count differs',r['errors']);self.assertIn('aggregate model elapsed time differs',r['errors'])
    def test_snapshot_mutation_rejected(self):
        (self.run/'source_snapshot/src/unit.py').write_text('changed\n');self.rejects('source snapshot hash mismatch')
    def test_old_development_snapshot_limitation_is_explicit(self):
        import shutil
        shutil.rmtree(self.run/'source_snapshot')
        r=audit.replay(self.run);self.assertTrue(r['audit_pass'],r);self.assertFalse(r['provenance_complete']);self.assertTrue(r['warnings'])
    def test_formal_freeze_baseline_and_tampered_file_hash(self):
        self.build('acceptance-unit')
        r=audit.replay(self.run);self.assertTrue(r['audit_pass'],r)
        self.freeze['files']['src/unit.py']='0'*64;dump(self.run/'freeze.json',self.freeze)
        self.rejects('freeze manifest differs from committed file')
    def test_formal_missing_snapshot_fails(self):
        import shutil
        self.build('acceptance-unit');shutil.rmtree(self.run/'source_snapshot');self.rejects('source snapshot missing')
    def test_formal_config_and_matrix_mutation_rejected(self):
        self.build('acceptance-unit');self.freeze['effective_config_sha256']['1']='0'*64;self.freeze['matrix']=[]
        dump(self.run/'freeze.json',self.freeze)
        r=audit.replay(self.run);self.assertFalse(r['audit_pass']);self.assertIn('formal effective config hash mismatch',r['errors']);self.assertIn('formal run outside frozen matrix',r['errors'])
    def test_incomplete_and_missing_matrix_points_are_counted(self):
        self.build('acceptance-unit')
        self.freeze['matrix'] += [['unit','A',1],['unit','C',1]];dump(self.root/'configs/freezes/unit.json',self.freeze)
        dump(self.root/'runs/acceptance-unit/unit_C_r1/started.json',{'process_id':1234})
        summary=audit.audit_phase('acceptance-unit')
        self.assertEqual(summary['expected_records'],3);self.assertEqual(len(summary['missing']),2)
        self.assertEqual({r['state'] for r in summary['missing']},{'not_started','incomplete'})
        self.assertFalse(summary['coverage_complete']);self.assertFalse(summary['acceptance_ready'])
        self.assertNotIn('interrupted',summary)
    def test_missing_input_is_not_silently_omitted(self):
        (self.run/'input.json').unlink()
        summary=audit.audit_phase('development');self.assertEqual(summary['records'],1);self.assertEqual(summary['passed'],0)
    def test_damaged_json_does_not_abort_other_runs(self):
        (self.run/'result.json').write_text('{')
        summary=audit.audit_phase('development');self.assertEqual(summary['records'],1);self.assertEqual(summary['passed'],0)
    def test_fixed_portfolio_is_audited_and_kept_outside_core_counts(self):
        import shutil
        shutil.rmtree(self.run/'agent')
        r=json.loads((self.run/'result.json').read_text());cfg=json.loads((self.run/'config.json').read_text())
        r.update(arm='F',auxiliary=True,selected_candidate=0,model_results=[],actions=[])
        r['identity']['arm']='F'
        r['costs']={'model_calls':0,'model_seconds':0,'input_tokens':0,'cached_input_tokens':0,'output_tokens':0,
                    'solver_seconds':.3,'solver_budget_seconds':2,'end_to_end_seconds':2}
        candidates=[];ledger=[]
        for i,search in enumerate(('AUTOMATIC_SEARCH','FIXED_SEARCH','PORTFOLIO_SEARCH')):
            params={'time_limit':2/3,'seed':11+i,'workers':1,'search_branching':search,'randomize_search':False}
            candidates.append({'result':{'schedule':S,'parameters':params,'solver_seconds':.1},'validation':r['validation']})
            ledger.extend([{'event':'solver_reserve','call_id':f's{i}','run_id':str(self.run),'requested_seconds':2/3},
                           {'event':'finish','call_id':f's{i}','status':'success','details':{'solver_seconds':.1}}])
        dump(self.run/'fixed_portfolio.json',candidates);dump(self.run/'result.json',r)
        started=json.loads((self.run/'started.json').read_text());started['identity']=r['identity'];dump(self.run/'started.json',started)
        (self.root/'progress/model_ledger.jsonl').write_text(''.join(json.dumps(v)+'\n' for v in ledger))
        summary=audit.audit_phase('development')
        self.assertEqual(summary['records'],0);self.assertEqual(summary['auxiliary_records'],1)
        self.assertEqual(summary['auxiliary_passed'],1,summary)
        self.mutate('result.json',lambda record:record.update(selected_candidate=1))
        self.rejects('selection differs from predefined minimum')

if __name__=='__main__':unittest.main()
