"""Independent append-only full-fab resource account. No legacy budget is reused."""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import datetime
import fcntl
import hashlib
import json
import math
import os
import uuid

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_LEDGER=ROOT/'progress/smt_fullfab/model_ledger.jsonl'
APPROVAL=ROOT/'configs/smt_fullfab/stage2_probe.approved.json'

# An inactive-by-default capability. Only a separate append-only user approval
# can waive count/token admission for the C one-hour pilot; history stays intact.
SCOPED_WAIVER_BUDGET_ID='smt-fullfab-stage2-probe-v1'
SCOPED_WAIVER_APPROVAL_TEXT='豁免次数与用量限制'
SCOPED_WAIVED_LIMITS=('attempt_count','reported_tokens','unknown_usage_admission')
_NONWAIVED_LIMITS={'per_call_timeout_seconds':180,
                  'total_active_wall_seconds':2700,
                  'max_solver_requested_seconds_per_arm':60}
_WAIVER_FIELDS={'amendment_id','budget_id','authorization','approval_text',
                'allowed_purpose','waived_limits','scenario','window_seconds'}
RESEARCH_APPROVAL_TEXT='记得将调用次数与额度放开'
RESEARCH_WAIVED_LIMITS=('attempt_count','reported_tokens','unknown_usage_admission','total_active_wall_seconds')
_RESEARCH_FIELDS={'amendment_id','budget_id','authorization','approval_text','allowed_purposes','waived_limits',
                  'model','reasoning_effort','per_call_timeout_seconds','allowed_stage2_window_seconds','formal_requires_preregistration'}


def _finite_positive(value):
    return type(value) in (int,float) and math.isfinite(value) and value>0


def _stage_path(run_id,arm):
    path=Path(run_id)
    base=ROOT/'runs'/('smt_fullfab_development' if arm=='A' else 'smt_fullfab_stage2')
    if len(path.parts)==1 and not path.is_absolute():path=base/path
    path=path.resolve()
    if path.parent!=base.resolve() or not path.name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in path.name):
        raise ValueError('registered run must be one new named stage run directory')
    return str(path)


def record_sha256(row):
    """Canonical UTF-8 SHA256 of the entire immutable ledger record, including at."""
    return hashlib.sha256(json.dumps(row,ensure_ascii=False,sort_keys=True,
                                   separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _evidence_inventory(directory):
    inventory={}
    for path in sorted(Path(directory).rglob('*')):
        if path.is_symlink():raise ValueError('recovery evidence must not contain symbolic links')
        if path.is_file():
            inventory[str(path.relative_to(directory))]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}
    return inventory


def _read_json(path):
    return json.loads(Path(path).read_text())


def sha_file_local(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class BudgetExceeded(RuntimeError):
    pass


class BudgetLedger:
    def __init__(self,path=DEFAULT_LEDGER):
        self.path=Path(path).resolve()
        if self.path != DEFAULT_LEDGER.resolve():
            # Tests may pass a temp path, but no old/default account may be touched.
            if 'smt_fullfab' not in str(self.path):
                raise ValueError('new research ledger must be in a smt_fullfab namespace')

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.with_suffix('.jsonl.lock').open('a+') as f:
            fcntl.flock(f,fcntl.LOCK_EX)
            try:
                rows=[json.loads(x) for x in self.path.read_text().splitlines() if x.strip()] if self.path.exists() else []
                yield rows
            finally:
                fcntl.flock(f,fcntl.LOCK_UN)

    def _append(self,row):
        row={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),**row}
        with self.path.open('a') as f:
            f.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n')
            f.flush();os.fsync(f.fileno())
        return row

    def approve(self,approval):
        if approval.get('authorization') != 'approved_by_user':
            raise ValueError('explicit user approval required')
        with self._locked() as rows:
            old=[r for r in rows if r['event']=='approval']
            if old:
                if old[0]['approval'] != approval:
                    raise ValueError('immutable approval; cannot reset allowance')
                return old[0]
            return self._append({'event':'approval','approval':approval})

    @staticmethod
    def _validate_scoped_limit_waiver(amendment,approval):
        if not isinstance(amendment,dict) or set(amendment)!=_WAIVER_FIELDS:
            raise ValueError('waiver must use exactly the scoped amendment schema')
        aid=amendment['amendment_id']
        if not isinstance(aid,str) or not aid.strip() or aid==approval['budget_id']:
            raise ValueError('independent nonempty amendment_id required')
        if amendment['authorization']!='approved_by_user' or amendment['approval_text']!=SCOPED_WAIVER_APPROVAL_TEXT:
            raise ValueError('exact explicit user waiver approval text required')
        if amendment['budget_id']!=approval['budget_id'] or approval['budget_id']!=SCOPED_WAIVER_BUDGET_ID:
            raise ValueError('waiver cannot change the original budget identity')
        if approval.get('authorization')!='approved_by_user':
            raise ValueError('original budget was not explicitly approved')
        if any(approval.get(k)!=v for k,v in _NONWAIVED_LIMITS.items()):
            raise ValueError('nonwaived time and solver limits must remain unchanged')
        limits=amendment['waived_limits']
        if not isinstance(limits,list) or len(limits)!=len(SCOPED_WAIVED_LIMITS) or set(limits)!=set(SCOPED_WAIVED_LIMITS):
            raise ValueError('only count, reported tokens and unknown-usage admission may be waived')
        if amendment['allowed_purpose']!='C':
            raise ValueError('waiver can only permit C')
        if type(amendment['scenario']) is not int or amendment['scenario']!=1701 or approval.get('scenario')!=1701:
            raise ValueError('waiver is restricted to scenario 1701')
        if type(amendment['window_seconds']) is not int or amendment['window_seconds']!=3600 or approval.get('window_seconds')!=3600:
            raise ValueError('waiver is restricted to the 3600-second pilot')

    @classmethod
    def _validated_scoped_waiver(cls,rows,approval):
        entries=[(index,row) for index,row in enumerate(rows) if row['event']=='scoped_limit_waiver']
        if len(entries)>1:
            raise ValueError('duplicate scoped waivers cannot reset accounting')
        if not entries:
            return None
        index,row=entries[0]
        if row.get('original_approval_sha256')!=record_sha256(approval):
            raise ValueError('original immutable approval differs from waiver anchor')
        cls._validate_scoped_limit_waiver(row['amendment'],approval)
        # Approval-time unknown completions remain immutable evidence, even though
        # their C admission stop is waived. Later unknown finishes remain unknown.
        prefix=rows[:index]
        original_unknown=cls.account(prefix)['unknown_completed']
        expected={r['call_id']:record_sha256(r) for r in prefix
                  if r['event']=='finish' and r['call_id'] in original_unknown}
        if row.get('unknown_finishes_at_approval')!=expected:
            raise ValueError('approval-time unknown completion evidence changed')
        return row['amendment']

    def approve_scoped_limit_waiver(self,amendment):
        """Record a separately approved C-only count/token admission waiver.

        Required keys: amendment_id, budget_id, authorization='approved_by_user',
        approval_text='豁免次数与用量限制', allowed_purpose='C',
        waived_limits=['attempt_count','reported_tokens','unknown_usage_admission'],
        scenario=1701, window_seconds=3600. No original record or counter is edited.
        A proposal alone must not call this method. Actual approval is a caller duty.
        """
        with self._locked() as rows:
            approvals=[r['approval'] for r in rows if r['event']=='approval']
            if len(approvals)!=1:
                raise ValueError('a unique original explicit approval is required')
            approval=approvals[0]
            self._validate_scoped_limit_waiver(amendment,approval)
            existing=self._validated_scoped_waiver(rows,approval)
            if existing:
                if existing!=amendment:
                    raise ValueError('immutable waiver; cannot replace or reset it')
                return next(r for r in rows if r['event']=='scoped_limit_waiver')
            unknown=self.account(rows)['unknown_completed']
            evidence={r['call_id']:record_sha256(r) for r in rows
                      if r['event']=='finish' and r['call_id'] in unknown}
            return self._append({'event':'scoped_limit_waiver',
                'original_approval_sha256':record_sha256(approval),
                'unknown_finishes_at_approval':evidence,'amendment':amendment})

    def scoped_limit_waiver(self,purpose):
        """Read the valid original scoped amendment, or None for other purposes."""
        with self._locked() as rows:
            approvals=[r['approval'] for r in rows if r['event']=='approval']
            if len(approvals)!=1:
                return None
            amendment=self._validated_scoped_waiver(rows,approvals[0])
            if amendment is None or amendment['allowed_purpose']!=purpose:
                return None
            return json.loads(json.dumps(amendment))

    @staticmethod
    def _validate_research_amendment(amendment,approval):
        if not isinstance(amendment,dict) or set(amendment)!=_RESEARCH_FIELDS:
            raise ValueError('research waiver requires exact amendment schema')
        aid=amendment.get('amendment_id')
        if not isinstance(aid,str) or not aid.strip() or aid==approval.get('budget_id'):
            raise ValueError('research amendment requires independent nonempty identity')
        if amendment['budget_id']!=approval['budget_id'] or approval['budget_id']!=SCOPED_WAIVER_BUDGET_ID:
            raise ValueError('research waiver must retain original new-study budget identity')
        if approval.get('authorization')!='approved_by_user' or amendment['authorization']!='approved_by_user' or amendment['approval_text']!=RESEARCH_APPROVAL_TEXT:
            raise ValueError('explicit latest user research waiver approval required')
        for key,expected in (('allowed_purposes',['B','C']),('waived_limits',list(RESEARCH_WAIVED_LIMITS)),
                             ('allowed_stage2_window_seconds',[3600,28800,86400])):
            if amendment[key]!=expected:raise ValueError('research waiver scope/gates differ: '+key)
        if (amendment['model']!='gpt-6-astra' or amendment['reasoning_effort']!='medium' or
                amendment['per_call_timeout_seconds']!=180 or amendment['formal_requires_preregistration'] is not True):
            raise ValueError('model, per-call timeout and formal-stage gate are not waived')

    @classmethod
    def _validated_research_waiver(cls,rows,approval):
        entries=[(i,row) for i,row in enumerate(rows) if row['event']=='research_limit_waiver']
        if len(entries)>1:raise ValueError('research waiver is immutable; duplicate amendments cannot reset history')
        if not entries:return None
        index,row=entries[0]
        cls._validate_research_amendment(row['amendment'],approval)
        if (row.get('original_approval_sha256')!=record_sha256(approval) or row.get('prefix_record_count')!=index or
                row.get('prior_ledger_sha256')!=record_sha256(rows[:index])):
            raise ValueError('research waiver immutable prior-history anchor mismatch')
        if not any(r.get('event')=='approval' and r.get('approval')==approval for r in rows[:index]):
            raise ValueError('research waiver precedes original approval')
        return row['amendment']

    def approve_research_limit_waiver(self,amendment):
        """Append only after explicit user approval; never modifies prior rows."""
        with self._locked() as rows:
            approvals=[r['approval'] for r in rows if r['event']=='approval']
            if len(approvals)!=1:raise ValueError('unique original approval required')
            approval=approvals[0];self._validate_research_amendment(amendment,approval)
            existing=self._validated_research_waiver(rows,approval)
            if existing:
                if existing!=amendment:raise ValueError('immutable research waiver; cannot replace it')
                return next(r for r in rows if r['event']=='research_limit_waiver')
            return self._append({'event':'research_limit_waiver','amendment':amendment,
                                 'original_approval_sha256':record_sha256(approval),
                                 'prefix_record_count':len(rows),'prior_ledger_sha256':record_sha256(rows)})

    def research_limit_waiver(self):
        with self._locked() as rows:
            approvals=[r['approval'] for r in rows if r['event']=='approval']
            if len(approvals)!=1:return None
            result=self._validated_research_waiver(rows,approvals[0])
            return json.loads(json.dumps(result)) if result else None

    @staticmethod
    def _validate_registration(registration,amendment):
        expected={'registration_id','amendment_id','budget_id','run_id','arm','scenario','window_seconds','solver_seconds',
                  'wall_seconds','max_log_bytes','phase','formal'}
        if not isinstance(registration,dict) or set(registration)!=expected:raise ValueError('stage registration schema mismatch')
        r=registration
        if r['arm'] not in ('A','B','C') or r['run_id']!=_stage_path(r['run_id'],r['arm']):raise ValueError('invalid registered arm/path')
        if r['amendment_id']!=amendment['amendment_id'] or r['budget_id']!=amendment['budget_id']:
            raise ValueError('registration authority differs from preceding research waiver')
        if type(r['scenario']) is not int or r['scenario']<0 or type(r['window_seconds']) is not int or r['window_seconds'] not in amendment['allowed_stage2_window_seconds']:
            raise ValueError('registration scenario/window outside stage2 research scope')
        if r['phase']!='stage2_research' or r['formal'] is not False:raise ValueError('formal stage requires separate frozen preregistration')
        if not _finite_positive(r['wall_seconds']) or type(r['max_log_bytes']) is not int or r['max_log_bytes']<=0:
            raise ValueError('finite positive run wall/log limits required')
        if (r['arm']=='B' and (type(r['solver_seconds']) not in (int,float) or r['solver_seconds']!=0)) or (r['arm']!='B' and not _finite_positive(r['solver_seconds'])):
            raise ValueError('B has zero solver budget; A/C require explicit finite positive allowance')
        if r['registration_id']!=record_sha256({k:v for k,v in r.items() if k!='registration_id'}):
            raise ValueError('stage registration identity hash mismatch')

    @classmethod
    def _registrations(cls,rows,approval):
        amendment=cls._validated_research_waiver(rows,approval)
        registrations={};seen_amendment=False
        for row in rows:
            if row['event']=='research_limit_waiver':seen_amendment=True
            if row['event']=='stage_run_registered':
                if not amendment or not seen_amendment:raise ValueError('run registration precedes research approval')
                r=row['registration'];cls._validate_registration(r,amendment)
                if r['run_id'] in registrations:raise ValueError('duplicate stage registration cannot reset consumed resources')
                registrations[r['run_id']]=r
        return registrations

    def register_stage_run(self,run_id,arm,scenario,window_seconds,solver_seconds,wall_seconds,max_log_bytes):
        with self._locked() as rows:
            approvals=[r['approval'] for r in rows if r['event']=='approval']
            if len(approvals)!=1:raise BudgetExceeded('unique original approval required')
            amendment=self._validated_research_waiver(rows,approvals[0])
            if not amendment:raise BudgetExceeded('research waiver must precede stage run registration')
            run_id=_stage_path(run_id,arm)
            if '__recovery_' in Path(run_id).name:
                raise ValueError('recovery segments inherit an original account; they cannot receive a fresh allowance')
            registration={'amendment_id':amendment['amendment_id'],'budget_id':amendment['budget_id'],
                          'run_id':run_id,'arm':arm,'scenario':scenario,'window_seconds':window_seconds,
                          'solver_seconds':solver_seconds,'wall_seconds':wall_seconds,'max_log_bytes':max_log_bytes,
                          'phase':'stage2_research','formal':False}
            registration['registration_id']=record_sha256(registration)
            self._validate_registration(registration,amendment)
            old=self._registrations(rows,approvals[0]).get(run_id)
            if old:
                if old!=registration:raise ValueError('immutable registered run allowance; use a genuinely new preregistered run')
                return json.loads(json.dumps(old))
            if any(r.get('event') in ('reserve','solver_reserve','constructor_reserve') and
                   (Path(r.get('run_id','/')).resolve()==Path(run_id) or Path(run_id) in Path(r.get('run_id','/')).resolve().parents) for r in rows):
                raise ValueError('cannot retroactively register or reset a previously used run')
            if any((Path(run_id)/name).exists() for name in ('result.json','checkpoint.json','trace.jsonl','resources.jsonl')):
                raise ValueError('cannot relabel existing execution evidence as a fresh registered run')
            self._append({'event':'stage_run_registered','registration':registration})
            return json.loads(json.dumps(registration))

    @staticmethod
    def _run_rows(rows,run_id):
        path=str(Path(run_id).resolve())
        mappings=[r['mapping'] for r in rows if r.get('event')=='recovery_segment_registered']
        parent=next((m['parent_run_id'] for m in mappings if m['segment_run_id']==path),path)
        paths={parent}|{m['segment_run_id'] for m in mappings if m['parent_run_id']==parent}
        ids={r['call_id'] for r in rows if (r.get('event')=='reserve' and str(Path(r['run_id']).resolve().parent) in paths) or
             (r.get('event')=='constructor_reserve' and str(Path(r['run_id']).resolve()) in paths)}
        return [r for r in rows if r.get('call_id') in ids]

    @staticmethod
    def _recovery_mappings(rows,registrations):
        mappings={};closed={}
        for row in rows:
            if row.get('event')=='recovery_segment_registered':
                m=row['mapping'];parent=m['parent_run_id'];segment=m['segment_run_id']
                if parent not in registrations or registrations[parent]['arm']!='B':raise ValueError('recovery has no original B registration')
                expected=registrations[parent]
                if m.get('recovery_segment_id')!=record_sha256({k:v for k,v in m.items() if k!='recovery_segment_id'}):raise ValueError('recovery mapping hash mismatch')
                if (m.get('registration_id')!=expected['registration_id'] or m.get('original_registration')!=expected or
                    m.get('amendment_id')!=expected['amendment_id'] or m.get('budget_id')!=expected['budget_id'] or m.get('phase')!='stage2_research'):
                    raise ValueError('recovery cannot change original allowance or authority')
                prior=[v for v in mappings.values() if v['parent_run_id']==parent]
                if prior:raise ValueError('later recovery mapping requires an unsupported accepted-prefix chain')
                if segment in mappings or segment in registrations or m.get('segment_index')!=len(prior)+1:
                    raise ValueError('duplicate or out-of-order recovery segment')
                if segment!=str(Path(parent).with_name(Path(parent).name+f'__recovery_{len(prior)+1:03d}')):
                    raise ValueError('recovery segment path differs from direct sibling identity')
                if any(v['segment_run_id'] not in closed for v in prior):raise ValueError('previous recovery segment is not closed')
                mappings[segment]=m
            elif row.get('event')=='recovery_segment_finished':
                completion=row['completion'];segment=completion['segment_run_id']
                if segment not in mappings or segment in closed:raise ValueError('unregistered or duplicate recovery close')
                if completion.get('finish_id')!=record_sha256({k:v for k,v in completion.items() if k!='finish_id'}):raise ValueError('recovery completion hash mismatch')
                if any(completion.get(key)!=mappings[segment][key] for key in ('recovery_segment_id','parent_run_id','registration_id')):
                    raise ValueError('recovery completion identity mismatch')
                closed[segment]=completion
        return mappings,closed

    @classmethod
    def _resolve_registration(cls,rows,approval,path):
        registrations=cls._registrations(rows,approval)
        mappings,_=cls._recovery_mappings(rows,registrations)
        mapping=mappings.get(str(Path(path).resolve()))
        return registrations.get(mapping['parent_run_id'] if mapping else str(Path(path).resolve())),mapping

    @classmethod
    def _recovery_resources(cls,rows,registration):
        registrations={r['registration']['run_id']:r['registration'] for r in rows if r.get('event')=='stage_run_registered'}
        mappings,closed=cls._recovery_mappings(rows,registrations)
        finalized={}
        for row in rows:
            if row.get('event')!='recovery_segment_finalized':continue
            f=row['finalization'];sid=f['segment_run_id']
            if sid not in closed or sid in finalized or f.get('finalization_id')!=record_sha256({k:v for k,v in f.items() if k!='finalization_id'}):
                raise ValueError('invalid or duplicate final recovery resource closure')
            if f.get('finish_id')!=closed[sid]['finish_id'] or f['segment_final_wall_seconds']<closed[sid]['segment_wall_seconds']:
                raise ValueError('final recovery closure reset pre-audit resources')
            if hashlib.sha256(Path(f['acceptance_path']).read_bytes()).hexdigest()!=f['acceptance_sha256']:
                raise ValueError('final recovery acceptance changed')
            finalized[sid]=f
        relevant=[m for m in mappings.values() if m['registration_id']==registration['registration_id']]
        if not relevant:return None
        first=min(relevant,key=lambda m:m['segment_index'])
        parent=registration['run_id'];parent_result=_read_json(Path(parent)/'result.json')
        if hashlib.sha256((Path(parent)/'result.json').read_bytes()).hexdigest()!=first['parent_result_sha256']:
            raise ValueError('original failed parent result changed')
        wall=parent_result['wall_seconds'];log_bytes=sum(v['bytes'] for v in _evidence_inventory(parent).values())
        open_segments=[]
        for m in relevant:
            segment=m['segment_run_id']
            log_bytes+=sum(v['bytes'] for v in _evidence_inventory(Path(segment)).values())
            if segment in closed:
                c=closed[segment]
                if hashlib.sha256(Path(c['result_path']).read_bytes()).hexdigest()!=c['result_sha256']:
                    raise ValueError('closed recovery result changed')
                wall+=finalized.get(segment,{}).get('segment_final_wall_seconds',c['segment_wall_seconds'])
            else:open_segments.append(segment)
        account=cls.account(cls._run_rows(rows,parent))
        return {'parent_run_id':parent,'registration_id':registration['registration_id'],
                'runner_wall_seconds':wall,'log_bytes':log_bytes,'open_recovery_segments':open_segments,
                'remaining_runner_wall_seconds':max(0.,registration['wall_seconds']-wall),
                'remaining_model_active_seconds':max(0.,registration['wall_seconds']-account['model_active_seconds']),
                'remaining_log_bytes':max(0,registration['max_log_bytes']-log_bytes)}

    def register_recovery_segment(self,parent_run_id,segment_run_id,recovery_package_path):
        """Append a segment→original-account binding; never grants new resources."""
        parent=_stage_path(parent_run_id,'B');segment=_stage_path(segment_run_id,'B')
        package_path=Path(recovery_package_path).resolve()
        with self._locked() as rows:
            approvals=[r['approval'] for r in rows if r.get('event')=='approval']
            if len(approvals)!=1:raise BudgetExceeded('unique original approval required')
            registrations=self._registrations(rows,approvals[0]);registration=registrations.get(parent)
            if not registration or registration['arm']!='B':raise BudgetExceeded('original registered B account required')
            mappings,closed=self._recovery_mappings(rows,registrations)
            package_bytes=package_path.read_bytes();package=json.loads(package_bytes)
            package_hash=hashlib.sha256(package_bytes).hexdigest()
            existing=mappings.get(segment)
            if existing:
                if existing['parent_run_id']!=parent or existing['recovery_package_sha256']!=package_hash or existing['recovery_package_path']!=str(package_path):
                    raise ValueError('immutable recovery segment mapping differs')
                return json.loads(json.dumps(existing))
            account=self.account(rows)
            if account['pending'] or account['pending_solver_calls'] or account['pending_constructor_calls']:raise BudgetExceeded('pending attempt requires authoritative reconciliation before recovery')
            if (package.get('status')!='prepared' or package.get('package_sha256')!=record_sha256({k:v for k,v in package.items() if k!='package_sha256'}) or
                package.get('parent_run')!=parent or package.get('original_registration')!=registration or package.get('plan_index')!=0 or
                type(package.get('next_page')) is not int or package['next_page']<0 or
                package.get('errors') or package.get('controller_evidence_audit',{}).get('valid') is not True or
                package.get('checkpoint_verification',{}).get('valid') is not True or package['checkpoint_verification'].get('simulation_seconds')!=0):
                raise ValueError('recovery package is not an intact prepared first-plan B package')
            prefix=package['ledger_prefix'];ledger_bytes=self.path.read_bytes();n=prefix['bytes']
            if (Path(prefix['path']).resolve()!=self.path or type(n)is not int or n<1 or n>len(ledger_bytes) or
                hashlib.sha256(ledger_bytes[:n]).hexdigest()!=prefix['sha256']):raise ValueError('original ledger byte prefix changed')
            prefix_rows=[json.loads(line) for line in ledger_bytes[:n].splitlines() if line.strip()]
            if len(prefix_rows)!=prefix['records'] or record_sha256(prefix_rows)!=prefix['canonical_sha256']:
                raise ValueError('original ledger logical prefix changed')
            if _evidence_inventory(Path(parent))!=package['parent_evidence']:
                raise ValueError('original parent evidence bytes changed since preparation')
            result=_read_json(Path(parent)/'result.json');claim=_read_json(Path(parent)/'claim.json')
            if result.get('status')!='failed' or result.get('full_window_completed') is not False or result.get('simulation_seconds')!=0 or result.get('plans_committed')!=0:
                raise ValueError('only failed first-plan t=0 parents are recoverable')
            if (package.get('next_model_index')!=result.get('model_calls') or
                [p.get('page_index') for p in package.get('accepted_pages',[])]!=list(range(package['next_page']))):
                raise ValueError('prepared recovery cursor does not preserve every accepted parent page')
            if type(claim.get('pid'))is not int or claim['pid']<=0:raise ValueError('invalid parent process claim')
            try:os.kill(claim['pid'],0)
            except ProcessLookupError:pass
            else:raise ValueError('parent process is still alive')
            prior=[m for m in mappings.values() if m['parent_run_id']==parent]
            if any(m['segment_run_id'] not in closed for m in prior):raise BudgetExceeded('prior recovery segment must be closed')
            if prior:
                raise ValueError('only the first recovery segment is supported; later segments require a newly certified accepted-prefix chain')
            index=len(prior)+1
            if segment!=str(Path(parent).with_name(Path(parent).name+f'__recovery_{index:03d}')):
                raise ValueError('recovery segment must use the next direct sibling sequence')
            if segment in registrations or Path(segment).exists():raise ValueError('recovery segment must be a fresh unregistered directory')
            run_account=self.account(self._run_rows(rows,parent))
            consumed=package.get('consumption',{})
            if any(consumed.get(k)!=v for k,v in (
                ('model_attempts',run_account['attempts']),('model_call_ids',result['model_call_ids']),
                ('reported_input_output_tokens',run_account['reported_input_output_tokens']),('unknown_usage_call_ids',run_account['unknown_completed']),
                ('model_active_seconds',run_account['model_active_seconds']),('runner_wall_seconds',result['wall_seconds']),
                ('parent_log_bytes',sum(v['bytes'] for v in package['parent_evidence'].values())))):
                raise ValueError('prepared package consumption differs from unchanged original account')
            resources=self._recovery_resources(rows,registration)
            wall=resources['runner_wall_seconds'] if resources else result['wall_seconds']
            logs=resources['log_bytes'] if resources else sum(v['bytes'] for v in package['parent_evidence'].values())
            if not _finite_positive(wall) or wall<run_account['model_active_seconds']:raise ValueError('parent/segment wall evidence omits prior model consumption')
            inherited={'model_attempts':run_account['attempts'],'reported_input_output_tokens':run_account['reported_input_output_tokens'],
                'unknown_usage_call_ids':run_account['unknown_completed'],'model_active_seconds':run_account['model_active_seconds'],
                'runner_wall_seconds':wall,'log_bytes':logs}
            remaining={'runner_wall_seconds':max(0.,registration['wall_seconds']-wall),
                'model_active_seconds':max(0.,registration['wall_seconds']-run_account['model_active_seconds']),
                'log_bytes':max(0,registration['max_log_bytes']-logs)}
            if min(remaining['runner_wall_seconds'],remaining['model_active_seconds'])<1 or remaining['log_bytes']<=0:
                raise BudgetExceeded('original registered wall/log resources exhausted')
            mapping={'parent_run_id':parent,'segment_run_id':segment,'registration_id':registration['registration_id'],
                'amendment_id':registration['amendment_id'],'budget_id':registration['budget_id'],'phase':'stage2_research',
                'original_registration':registration,'segment_index':index,'recovery_package_path':str(package_path),
                'recovery_package_sha256':package_hash,'package_identity_sha256':package['package_sha256'],
                'parent_result_sha256':hashlib.sha256((Path(parent)/'result.json').read_bytes()).hexdigest(),
                'inherited':inherited,'remaining':remaining}
            mapping['recovery_segment_id']=record_sha256(mapping)
            self._append({'event':'recovery_segment_registered','mapping':mapping})
            return json.loads(json.dumps(mapping))

    def report_recovery_segment_finish(self,segment_run_id,result_path):
        """Close one segment with immutable result evidence, preserving parent failure."""
        segment=_stage_path(segment_run_id,'B');result_path=Path(result_path).resolve()
        if result_path!=Path(segment)/'result.json':raise ValueError('segment result must be its direct result.json')
        with self._locked() as rows:
            approvals=[r['approval'] for r in rows if r.get('event')=='approval']
            if len(approvals)!=1:raise BudgetExceeded('unique original approval required')
            registrations=self._registrations(rows,approvals[0]);mappings,closed=self._recovery_mappings(rows,registrations)
            if segment not in mappings:raise ValueError('unknown recovery segment')
            result=_read_json(result_path);result_hash=hashlib.sha256(result_path.read_bytes()).hexdigest()
            if segment in closed:
                if closed[segment]['result_sha256']!=result_hash:raise ValueError('immutable recovery finish result changed')
                return json.loads(json.dumps(closed[segment]))
            m=mappings[segment];account=self.account(rows)
            if account['pending'] or account['pending_solver_calls'] or account['pending_constructor_calls']:raise BudgetExceeded('cannot close recovery with unresolved attempts')
            if (any(result.get(k)!=m[k] for k in ('parent_run_id','segment_run_id','recovery_segment_id','registration_id')) or
                result.get('status') not in ('success','failed') or type(result.get('full_window_completed'))is not bool or
                not _finite_positive(result.get('wall_seconds')) or type(result.get('simulation_seconds')) not in (int,float) or
                not math.isfinite(result['simulation_seconds']) or not 0<=result['simulation_seconds']<=m['original_registration']['window_seconds']):
                raise ValueError('invalid recovery terminal identity/resources')
            own=[r for r in rows if r.get('event')=='reserve' and str(Path(r['run_id']).resolve().parent)==segment]
            ids=[r['call_id'] for r in own]
            own_account=self.account([r for r in rows if r.get('call_id') in ids])
            if result.get('model_call_ids')!=ids or result.get('model_calls')!=len(ids) or result['wall_seconds']<own_account['model_active_seconds']:
                raise ValueError('segment result omits attempts or prior model time')
            if result['status']=='success' and (not result['full_window_completed'] or result['simulation_seconds']!=m['original_registration']['window_seconds']):
                raise ValueError('successful segment must complete the original window')
            inventory=_evidence_inventory(Path(segment));log_bytes=sum(v['bytes'] for v in inventory.values())
            completion={'segment_run_id':segment,'parent_run_id':m['parent_run_id'],'recovery_segment_id':m['recovery_segment_id'],
                'registration_id':m['registration_id'],'result_path':str(result_path),'result_sha256':result_hash,
                'status':result['status'],'full_window_completed':result['full_window_completed'],'simulation_seconds':result['simulation_seconds'],
                'segment_wall_seconds':result['wall_seconds'],'segment_log_bytes':log_bytes,
                'segment_model_call_ids':ids,'segment_model_active_seconds':own_account['model_active_seconds'],'evidence_sha256':inventory,
                'resource_overrun':result['wall_seconds']>m['remaining']['runner_wall_seconds'] or log_bytes>m['remaining']['log_bytes']}
            completion['finish_id']=record_sha256(completion)
            self._append({'event':'recovery_segment_finished','completion':completion})
            return json.loads(json.dumps(completion))

    def report_recovery_segment_finalization(self,segment_run_id,acceptance_path):
        """Charge final independent-audit/acceptance overhead without rewriting finish."""
        segment=_stage_path(segment_run_id,'B');acceptance_path=Path(acceptance_path).resolve()
        if acceptance_path!=Path(segment)/'acceptance.json':raise ValueError('acceptance must be the segment direct acceptance.json')
        with self._locked() as rows:
            approvals=[r['approval'] for r in rows if r.get('event')=='approval']
            if len(approvals)!=1:raise BudgetExceeded('unique original approval required')
            registrations=self._registrations(rows,approvals[0]);mappings,closed=self._recovery_mappings(rows,registrations)
            if segment not in closed:raise ValueError('immutable result/finish must precede finalization')
            acceptance=_read_json(acceptance_path);ahash=hashlib.sha256(acceptance_path.read_bytes()).hexdigest()
            old=[r['finalization'] for r in rows if r.get('event')=='recovery_segment_finalized' and r['finalization']['segment_run_id']==segment]
            if old:
                if len(old)!=1 or old[0]['acceptance_sha256']!=ahash:raise ValueError('immutable recovery finalization changed')
                return json.loads(json.dumps(old[0]))
            m=mappings[segment];c=closed[segment];r=m['original_registration']
            audit_path=Path(segment)/'recovery_audit.json';audit=_read_json(audit_path);result=_read_json(Path(segment)/'result.json')
            if any(acceptance.get(k)!=m[k] for k in ('parent_run_id','segment_run_id','registration_id','recovery_segment_id')):
                raise ValueError('acceptance changed inherited identity')
            if (acceptance.get('result_sha256')!=c['result_sha256'] or sha_file_local(Path(segment)/'result.json')!=c['result_sha256'] or
                acceptance.get('recovery_audit_sha256')!=sha_file_local(audit_path)):
                raise ValueError('acceptance result/audit hash mismatch')
            wall=acceptance.get('segment_final_wall_seconds');total_wall=acceptance.get('cumulative_final_wall_seconds')
            log_bytes=m['inherited']['log_bytes']+sum(v['bytes'] for v in _evidence_inventory(Path(segment)).values())
            if not _finite_positive(wall) or wall<c['segment_wall_seconds'] or total_wall!=m['inherited']['runner_wall_seconds']+wall:
                raise ValueError('final acceptance omits audit wall time or resets parent consumption')
            if acceptance.get('cumulative_log_bytes_including_acceptance')!=log_bytes:
                raise ValueError('acceptance omitted final audit/acceptance log bytes')
            overrun=total_wall>r['wall_seconds'] or log_bytes>r['max_log_bytes'] or c.get('resource_overrun') is True
            if acceptance.get('resource_overrun') is not overrun or type(acceptance.get('accepted'))is not bool:
                raise ValueError('acceptance resource outcome differs from original bounds')
            eligible=(result.get('status')=='success' and result.get('full_window_completed') is True and result.get('audit_valid') is True
                      and audit.get('valid') is True and audit.get('successful_full_window') is True and not overrun)
            if acceptance['accepted']!=eligible or acceptance.get('successful_full_window')!=eligible or acceptance.get('status')!=('success' if eligible else 'failed'):
                raise ValueError('acceptance does not require full physical, attribution and resource evidence')
            finalization={'segment_run_id':segment,'parent_run_id':m['parent_run_id'],'recovery_segment_id':m['recovery_segment_id'],
                'registration_id':m['registration_id'],'finish_id':c['finish_id'],'acceptance_path':str(acceptance_path),'acceptance_sha256':ahash,
                'result_sha256':c['result_sha256'],'recovery_audit_sha256':acceptance['recovery_audit_sha256'],
                'segment_final_wall_seconds':wall,'cumulative_final_wall_seconds':total_wall,
                'cumulative_log_bytes_including_acceptance':log_bytes,'resource_overrun':overrun,'accepted':eligible}
            finalization['finalization_id']=record_sha256(finalization)
            self._append({'event':'recovery_segment_finalized','finalization':finalization})
            return json.loads(json.dumps(finalization))

    def stage_registration(self,run_id,arm=None):
        with self._locked() as rows:
            approvals=[r['approval'] for r in rows if r['event']=='approval']
            if len(approvals)!=1:return None
            if arm is None:
                path=str(Path(run_id).resolve())
            else:path=_stage_path(run_id,arm)
            value,_=self._resolve_registration(rows,approvals[0],path)
            return json.loads(json.dumps(value)) if value else None

    @staticmethod
    def account(rows):
        starts=[r for r in rows if r['event']=='reserve']
        ends={r['call_id']:r for r in rows if r['event']=='finish'}
        if len(ends)!=sum(r['event']=='finish' for r in rows):
            raise ValueError('duplicate finish')
        tokens=0;unknown=[];wall=0.
        for r in starts:
            e=ends.get(r['call_id'])
            if not e:continue
            usage=e['details'].get('usage',{})
            if not all(type(usage.get(k)) is int and usage[k]>=0 for k in ('input_tokens','output_tokens')):
                unknown.append(r['call_id'])
            else:tokens+=usage['input_tokens']+usage['output_tokens']
            wall+=e['details'].get('duration_seconds',0)
        amended={}
        for r in starts:
            if r.get('amendment_id'):
                amended[r['amendment_id']]=amended.get(r['amendment_id'],0)+1
        solver_starts=[r['call_id'] for r in rows if r['event']=='solver_reserve']
        solver_finishes={r['call_id'] for r in rows if r['event']=='solver_finish'}
        constructor_starts=[r for r in rows if r['event']=='constructor_reserve']
        constructor_ends={r['call_id']:r for r in rows if r['event']=='constructor_finish'}
        if len(constructor_ends)!=sum(r['event']=='constructor_finish' for r in rows):
            raise ValueError('duplicate constructor finish')
        constructor_wall=0.
        for r in constructor_starts:
            if r['call_id'] not in constructor_ends:continue
            duration=constructor_ends[r['call_id']]['details'].get('duration_seconds')
            if type(duration) not in (int,float) or not math.isfinite(duration) or duration<0:
                raise ValueError('invalid constructor duration')
            constructor_wall+=duration
        return {'attempts':len(starts),'reported_input_output_tokens':tokens,'unknown_completed':unknown,
                'pending':[r['call_id'] for r in starts if r['call_id'] not in ends],
                'pending_solver_calls':[sid for sid in solver_starts if sid not in solver_finishes],
                'model_active_seconds':wall,'constructor_calls':len(constructor_starts),
                'constructor_requested_seconds':sum(r['requested_seconds'] for r in constructor_starts),
                'constructor_active_seconds':constructor_wall,'active_execution_seconds':wall+constructor_wall,
                'pending_constructor_calls':[r['call_id'] for r in constructor_starts if r['call_id'] not in constructor_ends],
                'cost_usd':None,'development_collaboration_cost_usd':None,
                'amendment_attempts':amended}

    def reserve(self,*,phase,run_id,grant_id,call_id=None,metadata=None):
        with self._locked() as rows:
            approvals=[r['approval'] for r in rows if r['event']=='approval']
            if len(approvals)!=1:raise BudgetExceeded('no unique explicit approval')
            a=approvals[0];s=self.account(rows)
            if grant_id!=a['budget_id'] or not str(Path(run_id).resolve()).startswith(str(ROOT/'runs/smt_fullfab_stage2')+'/'):
                raise BudgetExceeded('attempt outside approved research scope')
            context=(metadata or {}).get('authorization_context') or {}
            purpose=context.get('purpose')
            if purpose not in ('channel_probe','B','C'):
                raise BudgetExceeded('explicit authorized attempt purpose required')
            research=self._validated_research_waiver(rows,a)
            if research and purpose in ('B','C'):
                registration,recovery=self._resolve_registration(rows,a,str(Path(run_id).resolve().parent))
                if registration is None:raise BudgetExceeded('research model calls require prior immutable run registration')
                if not recovery and any(r.get('event')=='recovery_segment_registered' and r['mapping']['parent_run_id']==registration['run_id'] for r in rows):
                    raise BudgetExceeded('sealed parent account may only continue through its registered recovery segment')
                if (registration['arm']!=purpose or phase!=registration['phase'] or
                        context.get('arm')!=purpose or type(context.get('scenario')) is not int or context['scenario']!=registration['scenario'] or
                        context.get('window_seconds')!=registration['window_seconds']):
                    raise BudgetExceeded('model reservation differs from registered arm/scenario/window/phase')
                metadata=metadata or {}
                if metadata.get('model')!=research['model'] or metadata.get('reasoning_effort')!=research['reasoning_effort']:
                    raise BudgetExceeded('research waiver retains the approved model and reasoning effort')
                run_account=self.account(self._run_rows(rows,registration['run_id']))
                timeout=metadata.get('timeout_seconds')
                remaining=registration['wall_seconds']-run_account['active_execution_seconds']
                resources=None
                if recovery:
                    _,closed=self._recovery_mappings(rows,self._registrations(rows,a))
                    if recovery['segment_run_id'] in closed:raise BudgetExceeded('closed recovery segment cannot reserve another call')
                    resources=self._recovery_resources(rows,registration)
                    segment_ids={r['call_id'] for r in rows if r.get('event')=='reserve' and str(Path(r['run_id']).resolve().parent)==recovery['segment_run_id']}
                    active_here=self.account([r for r in rows if r.get('call_id') in segment_ids])['model_active_seconds']
                    remaining=min(remaining,resources['remaining_runner_wall_seconds']-active_here)
                    if resources['remaining_log_bytes']<=0:raise BudgetExceeded('inherited recovery log allowance exhausted')
                if not _finite_positive(timeout) or not 1<=timeout<=min(research['per_call_timeout_seconds'],remaining):
                    raise BudgetExceeded('model timeout exceeds single-call or registered-run remaining time')
                if s['pending'] or s['pending_solver_calls'] or s['pending_constructor_calls']:raise BudgetExceeded('pending attempt requires diagnosis, not automatic retry')
                call_id=call_id or str(uuid.uuid4())
                if any(r.get('call_id')==call_id for r in rows):raise ValueError('duplicate reservation')
                row={'event':'reserve','call_id':call_id,'phase':phase,'run_id':str(Path(run_id).resolve()),'grant_id':grant_id,
                              'metadata':metadata,'account_before':s,'run_account_before':run_account,
                              'amendment_id':research['amendment_id'],'registration_id':registration['registration_id']}
                if recovery:row.update(recovery_segment_id=recovery['recovery_segment_id'],parent_run_id=recovery['parent_run_id'],recovery_resources_before=resources)
                self._append(row)
                return call_id
            if purpose in ('B','C') and (context.get('arm')!=purpose or context.get('window_seconds')!=a['window_seconds']):
                raise BudgetExceeded('arm/window outside approved scope')
            def category(row):
                c=row.get('metadata',{}).get('authorization_context') or {}
                if c.get('purpose'):return c['purpose']
                # Initial calls were already authorized before context hardening.
                # Their saved immutable run IDs identify the historical category.
                rel=Path(row['run_id']).relative_to(ROOT/'runs/smt_fullfab_stage2').parts[0]
                if rel=='channel_probe_v1':return 'channel_probe'
                if rel=='B_1701_1h_probe_v1':return 'B'
                raise BudgetExceeded('unclassified existing reservation; manual audit required')
            amendment=self._validated_scoped_waiver(rows,a)
            applied_amendment=None
            waived=set()
            if amendment and purpose==amendment['allowed_purpose']:
                if phase!='stage2_probe' or type(context.get('scenario')) is not int or context['scenario']!=amendment['scenario']:
                    raise BudgetExceeded('C waiver requires the explicit approved scenario and stage')
                if context.get('window_seconds')!=amendment['window_seconds']:
                    raise BudgetExceeded('C waiver window differs from approved scope')
                timeout=(metadata or {}).get('timeout_seconds')
                if type(timeout) not in (int,float) or not 1<=timeout<=a['per_call_timeout_seconds']:
                    raise BudgetExceeded('C waiver requires a bounded explicit per-call timeout')
                if timeout>a['total_active_wall_seconds']-s['model_active_seconds']+1e-9:
                    raise BudgetExceeded('C waiver call timeout exceeds remaining active time')
                if (metadata or {}).get('model')!=a['model']:
                    raise BudgetExceeded('C waiver does not authorize a different model')
                waived=set(amendment['waived_limits'])
                applied_amendment=amendment['amendment_id']
            if 'attempt_count' not in waived:
                if sum(category(r)==purpose for r in rows if r['event']=='reserve')>=a['allocation'][purpose]:
                    raise BudgetExceeded('approved cumulative category allowance exhausted')
                if s['attempts']>=a['max_model_attempts']:
                    raise BudgetExceeded('attempt allowance exhausted')
            if 'reported_tokens' not in waived and s['reported_input_output_tokens']>=a['observed_input_output_token_admission_limit']:
                raise BudgetExceeded('observed token admission limit reached')
            if 'unknown_usage_admission' not in waived and len(s['unknown_completed'])>=a['max_completed_unknown_usage']:
                raise BudgetExceeded('unknown usage stop rule')
            if s['pending'] or s['pending_constructor_calls']:
                raise BudgetExceeded('pending attempt requires diagnosis, not automatic retry')
            if s['model_active_seconds']>=a['total_active_wall_seconds']:raise BudgetExceeded('stage active time exhausted')
            call_id=call_id or str(uuid.uuid4())
            if any(r.get('call_id')==call_id for r in rows):raise ValueError('duplicate reservation')
            self._append({'event':'reserve','call_id':call_id,'phase':phase,'run_id':run_id,'grant_id':grant_id,
                          'metadata':metadata or {},'account_before':s,'amendment_id':applied_amendment})
            return call_id

    def finish(self,call_id,status,details=None):
        with self._locked() as rows:
            if not any(r['event']=='reserve' and r['call_id']==call_id for r in rows):raise ValueError('unreserved finish')
            if any(r['event']=='finish' and r['call_id']==call_id for r in rows):raise ValueError('attempt already finished')
            return self._append({'event':'finish','call_id':call_id,'status':status,'details':details or {}})

    def summary(self,run_id=None):
        with self._locked() as rows:
            if run_id is None:return self.account(rows)
            path=str(Path(run_id).resolve());account=self.account(self._run_rows(rows,path))
            approvals=[r['approval'] for r in rows if r.get('event')=='approval']
            if len(approvals)==1:
                registration,_=self._resolve_registration(rows,approvals[0],path)
                if registration:
                    resources=self._recovery_resources(rows,registration)
                    if resources:account.update(resources)
            return account

    def solver_remaining_seconds(self,arm,run_id=None):
        with self._locked() as rows:
            approvals=[r['approval'] for r in rows if r['event']=='approval']
            if len(approvals)!=1:raise BudgetExceeded('no unique solver approval')
            if run_id is not None:
                registration,_=self._resolve_registration(rows,approvals[0],_stage_path(run_id,arm))
                if registration is None or registration['arm']!=arm:raise BudgetExceeded('no matching registered run solver allowance')
                used=sum(r['requested_seconds'] for r in rows if r['event']=='solver_reserve' and r.get('registration_id')==registration['registration_id'])
                return max(0.,registration['solver_seconds']-used)
            used=sum(r['requested_seconds'] for r in rows if r['event']=='solver_reserve' and r['arm']==arm and not r.get('registration_id'))
            return max(0.,approvals[0]['max_solver_requested_seconds_per_arm']-used)

    def reserve_solver(self,*,arm,run_id,requested_seconds):
        if arm not in ('A','C') or not _finite_positive(requested_seconds):
            raise BudgetExceeded('invalid solver allocation')
        with self._locked() as rows:
            approved=[r['approval'] for r in rows if r['event']=='approval']
            if len(approved)!=1:raise BudgetExceeded('no solver approval')
            registrations=self._registrations(rows,approved[0])
            try:registration=registrations.get(_stage_path(run_id,arm))
            except ValueError:registration=None
            if registration:
                account=self.account(rows)
                if account['pending'] or account['pending_solver_calls'] or account['pending_constructor_calls']:raise BudgetExceeded('pending model/solver attempt requires diagnosis')
                run_account=self.account(self._run_rows(rows,registration['run_id']))
                if requested_seconds>registration['wall_seconds']-run_account['active_execution_seconds']+1e-9:
                    raise BudgetExceeded('registered run activity wall exhausted')
                used=sum(r['requested_seconds'] for r in rows if r['event']=='solver_reserve' and r.get('registration_id')==registration['registration_id'])
                if used+requested_seconds>registration['solver_seconds']+1e-9:raise BudgetExceeded('registered run solver allowance exhausted')
                sid=str(uuid.uuid4())
                self._append({'event':'solver_reserve','call_id':sid,'arm':arm,'run_id':registration['run_id'],'requested_seconds':requested_seconds,
                              'registration_id':registration['registration_id'],'amendment_id':registration['amendment_id']})
                return sid
            if self._validated_research_waiver(rows,approved[0]):raise BudgetExceeded('new research solver calls require a registered run')
            if requested_seconds>60:raise BudgetExceeded('invalid legacy solver allocation')
            used=sum(r['requested_seconds'] for r in rows if r['event']=='solver_reserve' and r['arm']==arm and not r.get('registration_id'))
            if used+requested_seconds>approved[0]['max_solver_requested_seconds_per_arm']+1e-9:
                raise BudgetExceeded('cumulative stage solver allowance exhausted')
            sid=str(uuid.uuid4())
            self._append({'event':'solver_reserve','call_id':sid,'arm':arm,'run_id':run_id,'requested_seconds':requested_seconds})
            return sid

    def finish_solver(self,call_id,status,details):
        with self._locked() as rows:
            if not any(r['event']=='solver_reserve' and r['call_id']==call_id for r in rows):raise ValueError('solver finish without reserve')
            if any(r['event']=='solver_finish' and r['call_id']==call_id for r in rows):raise ValueError('duplicate solver finish')
            return self._append({'event':'solver_finish','call_id':call_id,'status':status,'details':details})


    def constructor_remaining_seconds(self,arm,run_id):
        """Remaining registered activity wall; this is never a CP allowance."""
        if arm!='C':raise BudgetExceeded('only explicit research C may reserve construction')
        with self._locked() as rows:
            approvals=[r['approval'] for r in rows if r['event']=='approval']
            if len(approvals)!=1:raise BudgetExceeded('unique original approval required')
            registration,recovery=self._resolve_registration(rows,approvals[0],_stage_path(run_id,arm))
            if not registration or registration['arm']!='C' or recovery:
                raise BudgetExceeded('constructor requires an original registered research C run')
            account=self.account(self._run_rows(rows,registration['run_id']))
            return max(0.,registration['wall_seconds']-account['active_execution_seconds'])

    def reserve_constructor(self,*,arm='C',run_id,requested_seconds,metadata):
        """Reserve one explicit shared deterministic constructor invocation.

        Soft request time is recorded separately from CP reservations. The outer
        invocation's actual duration must be closed even after an exception; an
        unresolved call blocks every subsequent admission and cannot be retried.
        """
        if arm!='C' or not _finite_positive(requested_seconds) or requested_seconds>5:
            raise BudgetExceeded('construction requires C and a soft request in (0, 5] seconds')
        if (not isinstance(metadata,dict) or metadata.get('method')!='constructive' or
            metadata.get('actual_constructor_module')!='src.smt_fullfab.constructive_tool' or
            metadata.get('actual_constructor_function')!='solve_constructive_plan' or
            type(metadata.get('max_candidate_evaluations')) is not int or metadata['max_candidate_evaluations']!=250000 or
            type(metadata.get('max_slots_per_machine')) is not int or not 1<=metadata['max_slots_per_machine']<=8 or
            any(type(metadata.get(k)) is not int or metadata[k]<0 for k in ('model_index','plan_index')) or
            not isinstance(metadata.get('problem_sha256'),str) or len(metadata['problem_sha256'])!=64 or
            any(c not in '0123456789abcdef' for c in metadata['problem_sha256'])):
            raise ValueError('constructor metadata must bind the explicit bounded shared tool request')
        with self._locked() as rows:
            approvals=[r['approval'] for r in rows if r['event']=='approval']
            if len(approvals)!=1:raise BudgetExceeded('unique original approval required')
            registration,recovery=self._resolve_registration(rows,approvals[0],_stage_path(run_id,arm))
            if not registration or registration['arm']!='C' or recovery:
                raise BudgetExceeded('constructor requires an original registered research C run')
            account=self.account(rows)
            if account['pending'] or account['pending_solver_calls'] or account['pending_constructor_calls']:
                raise BudgetExceeded('pending attempt requires diagnosis, not automatic retry')
            source=metadata.get('model_call_id')
            reserves=[r for r in rows if r['event']=='reserve' and r['call_id']==source]
            finishes=[r for r in rows if r['event']=='finish' and r['call_id']==source]
            if (len(reserves)!=1 or len(finishes)!=1 or finishes[0]['status']!='success' or
                reserves[0].get('registration_id')!=registration['registration_id'] or
                str(Path(reserves[0]['run_id']).resolve())!=str(Path(registration['run_id'])/f"model_{metadata['model_index']:03d}")):
                raise ValueError('constructor source must be a successful model call in this registered run')
            if any(r['event']=='constructor_reserve' and r.get('metadata',{}).get('model_call_id')==source for r in rows):
                raise ValueError('one explicit model action cannot invoke or retry a constructor twice')
            run_account=self.account(self._run_rows(rows,registration['run_id']))
            if requested_seconds>registration['wall_seconds']-run_account['active_execution_seconds']+1e-9:
                raise BudgetExceeded('registered run activity wall exhausted')
            cid=str(uuid.uuid4())
            self._append({'event':'constructor_reserve','call_id':cid,'arm':arm,'run_id':registration['run_id'],
                          'requested_seconds':requested_seconds,'metadata':metadata,
                          'registration_id':registration['registration_id'],'amendment_id':registration['amendment_id'],
                          'account_before':account,'run_account_before':run_account})
            return cid

    def finish_constructor(self,call_id,status,details):
        if (status not in ('success','failed') or not isinstance(details,dict) or
            type(details.get('duration_seconds')) not in (int,float) or not math.isfinite(details['duration_seconds']) or details['duration_seconds']<0 or
            not isinstance(details.get('solver_status'),str) or not details['solver_status'] or
            not isinstance(details.get('constructor_result_sha256'),str) or len(details['constructor_result_sha256'])!=64 or
            any(c not in '0123456789abcdef' for c in details['constructor_result_sha256'])):
            raise ValueError('constructor finish must preserve measured duration and result hash/status')
        with self._locked() as rows:
            if not any(r['event']=='constructor_reserve' and r['call_id']==call_id for r in rows):raise ValueError('constructor finish without reserve')
            if any(r['event']=='constructor_finish' and r['call_id']==call_id for r in rows):raise ValueError('duplicate constructor finish')
            return self._append({'event':'constructor_finish','call_id':call_id,'status':status,'details':details})
