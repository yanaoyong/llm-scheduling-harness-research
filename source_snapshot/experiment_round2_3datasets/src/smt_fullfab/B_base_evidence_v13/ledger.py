"""One new versioned segment: immutable old prefix, audited new cost suffix."""
from pathlib import Path
import hashlib,json,math,time,uuid
from .recovery import need,sha

EVENT='B_v13_base_evidence_segment_registered'

def combine(old,new):
    out=dict(old)
    for k in ('attempts','reported_input_output_tokens','model_active_seconds','active_execution_seconds',
              'constructor_calls','constructor_requested_seconds','constructor_active_seconds'):
        out[k]=old[k]+new[k]
    for k in ('unknown_completed','pending','pending_solver_calls','pending_constructor_calls'):
        out[k]=old[k]+new[k]
    out['cost_usd']=None;out['development_collaboration_cost_usd']=None
    out['amendment_attempts']=dict(old['amendment_attempts'])
    for k,v in new['amendment_attempts'].items():out['amendment_attempts'][k]=out['amendment_attempts'].get(k,0)+v
    return out

def make_ledger_class(b, *, manifest, manifest_sha256, campaign, started, soft_deadline, retained_bytes):
    prefix=Path(manifest['ledger_prefix']['path']).read_bytes()
    need(hashlib.sha256(prefix).hexdigest()==manifest['ledger_prefix']['sha256'],'original ledger prefix changed')
    oldrows=[json.loads(x) for x in prefix.splitlines()]; n=len(oldrows)
    segment=Path(manifest['segment_path']);reg=manifest['recovery']['prior_registration']
    registration={'event':EVENT,'run_id':str(segment),'manifest_sha256':manifest_sha256,
        'manifest_path':str(Path(campaign)/'manifest.json'),'original_prefix_sha256':hashlib.sha256(prefix).hexdigest(),
        'parent_run_id':manifest['parent_run'],'first_model_index':manifest.get('first_model_index',237),'model':'gpt-6-astra','effort':'medium',
        'absolute_target':3600,'costs_inherited':manifest['inherited_cost'],
        'per_call_timeout_seconds':600,'count_token_waiver_inherited':True,'new_budget_granted':False}
    class Ledger(b.BudgetLedger):
        def _suffix(self,rows, *, registered=True):
            with self.path.open('rb') as f:need(f.read(len(prefix))==prefix,'append-only ledger prefix changed')
            need(rows[:n]==oldrows,'old parsed ledger changed')
            suffix=rows[n:]
            if not suffix:
                need(not registered,'segment not registered');return []
            r={k:v for k,v in suffix[0].items() if k!='at'}
            need(r==registration,'wrong segment registration')
            pending={};seen=set();indices=[]
            for row in suffix[1:]:
                cid=row.get('call_id')
                if row['event']=='reserve':
                    need(not pending and cid not in seen,'new pending or reused call')
                    need(all(cid!=x.get('call_id') for x in oldrows),'inherited call id reuse')
                    path=Path(row['run_id']);i=int(path.name.removeprefix('model_'))
                    need(path.parent==segment and path.name==f'model_{i:05d}' and i==manifest.get('first_model_index',237)+len(indices),'noncontiguous call path')
                    need(row['phase']==reg['phase'] and row['grant_id']==reg['budget_id'],'inherited grant mismatch')
                    md=row['metadata']
                    need(md['model']=='gpt-6-astra' and md['reasoning_effort']=='medium' and md['timeout_seconds']==600,'model policy changed')
                    need(md['authorization_context']=={'purpose':'B','arm':'B','scenario':1701,'window_seconds':3600},'wrong experiment scope')
                    pending[cid]=row;seen.add(cid);indices.append(i)
                elif row['event']=='finish':
                    need(cid in pending and row['status'] in ('success','failed','timeout'),'unknown/duplicate finish')
                    need(row['details']['result_path']==str(Path(pending[cid]['run_id'])/'result.json'),'finish path differs')
                    pending.pop(cid)
                else:raise ValueError('unexpected ledger suffix event '+row['event'])
            return suffix[1:]
        def register(self):
            with self._locked() as rows:
                need(len(rows)==n,'unique segment registration only');self._suffix(rows,registered=False)
                return self._append(registration)
        def reserve(self, *,phase,run_id,grant_id,call_id=None,metadata=None):
            with self._locked() as rows:
                suffix=self._suffix(rows);account=self.account(suffix)
                need(not account['pending'],'pending suffix blocks another call')
                need(not (segment/'result.json').exists(),'terminal segment cannot reopen')
                need(time.monotonic()+660<soft_deadline,'insufficient call/cleanup deadline margin')
                size=retained_bytes();need(size<manifest['remaining_log_bytes'],'inherited byte budget exhausted')
                row={'event':'reserve','call_id':call_id or str(uuid.uuid4()),'phase':phase,'run_id':str(Path(run_id).resolve()),
                    'grant_id':grant_id,'metadata':metadata or {},'amendment_id':reg['amendment_id'],
                    'registration_id':reg['registration_id'],'versioned_segment_manifest_sha256':manifest_sha256,
                    'account_before':self.account(rows),'segment_account_before':account,
                    'run_account_before':combine(manifest['inherited_cost']['B_lineage_cumulative'],account),
                    'resources_before':{'elapsed_seconds':time.monotonic()-started,'retained_bytes':size}}
                # Validate exact next suffix without writing it.
                self._suffix(rows+[row]);self._append(row);return row['call_id']
        def finish(self,call_id,status,details=None):
            with self._locked() as rows:
                self._suffix(rows)
                row={'event':'finish','call_id':call_id,'status':status,'details':details or {}}
                self._suffix(rows+[row]);return self._append(row)
        def summary(self,run_id=None):
            with self._locked() as rows:
                suffix=self._suffix(rows);local=self.account(suffix)
                return {'research_account':self.account(rows),'segment_account':local,
                    'B_lineage_cumulative':combine(manifest['inherited_cost']['B_lineage_cumulative'],local),
                    'independent_channel_diagnostic_separate':manifest['inherited_cost']['independent_channel_diagnostic_separate']}
        def reserve_solver(self,*a,**k):raise ValueError('B direct decisions only')
        def reserve_constructor(self,*a,**k):raise ValueError('B direct decisions only')
    return Ledger
