"""DRAFT: external-memory constructor evidence audit; no production integration.

Original check statements/order are retained. JSON records are read through the
caller's original reader, audited once, then individually stored in a disposable
SQLite workspace. This is memory placement, not a scheduler or new acceptance.
The scratch DB is not an authenticated/recoverable evidence database.
"""
from collections import Counter
from collections.abc import Mapping, MutableMapping, Sequence
import hashlib
import json
import math
from pathlib import Path
import sqlite3

LEGACY_AUDIT_SHA256 = "27c2b9252b95d90908156a12bbe4776ae732bfb8f58179e212bc8e594bb6c4e5"
DRAFT_SCHEMA = "smt-C8-constructor-stream-draft-v1"


# Exact copied pure legacy constants/helpers/admission replay.
MODULE='src.smt_fullfab.constructive_tool'
FUNCTION='solve_constructive_plan'
MODEL='fullfab-constructive-tool-v1'
VERSION='fullfab-C-explicit-constructive-v1'
FEEDBACK_FIELDS=('solver_status','objective','best_bound','planned_operations','wall_seconds','limitations',
                 'global_optimality_claim','selected_source','cp_sat','decomposition_status','heuristic_families')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def finite(value,minimum=0):
    return type(value) in (int,float) and math.isfinite(value) and value>=minimum


def audit_constructor_ledger(rows):
    """Replay constructor authority/accounting in order, supplementing base audit."""
    errors=[];pending={};seen=set();register={};starts={};ends={};model_run={}
    model_active=Counter();constructor_active=Counter();requested=Counter();counts=Counter()
    model_admissions={};constructor_admissions={};sources=set();research=None
    def check(ok,message):
        if not ok:errors.append(message)
    for row in rows:
        event=row.get('event');cid=row.get('call_id')
        if event=='research_limit_waiver':research=row.get('amendment')
        elif event=='stage_run_registered':
            r=row['registration'];register[r['registration_id']]=r
        elif event in ('reserve','solver_reserve','constructor_reserve'):
            check(cid not in seen,'duplicate identity across model/CP/constructor calls');seen.add(cid)
            if event=='constructor_reserve' or any(kind=='constructor_reserve' for kind in pending.values()):
                check(not pending,'admission while model/CP/constructor call is pending')
            pending[cid]=event;starts[cid]=row
            rid=row.get('registration_id');r=register.get(rid)
            if event=='reserve':
                model_run[cid]=rid
                model_admissions[cid]={'constructor_active_seconds_before':constructor_active[rid],
                    'constructor_requested_seconds_before':requested[rid],
                    'active_execution_seconds_before':model_active[rid]+constructor_active[rid]}
                if r and constructor_active[rid]:
                    timeout=row.get('metadata',{}).get('timeout_seconds')
                    check(finite(timeout,1) and timeout<=min(180,r['wall_seconds']-model_active[rid]-constructor_active[rid])+1e-9,
                          'model timeout ignores consumed constructor wall')
            elif event=='constructor_reserve':
                meta=row.get('metadata',{});source=meta.get('model_call_id');source_row=starts.get(source,{})
                sec=row.get('requested_seconds')
                check(research is not None and r is not None and r.get('arm')=='C' and row.get('arm')=='C',
                      'constructor lacks preceding research C registration')
                if r:
                    check(row.get('run_id')==r['run_id'] and row.get('amendment_id')==r['amendment_id'], 'constructor registration identity differs')
                    check(finite(sec) and 0<sec<=5 and sec<=r['wall_seconds']-model_active[rid]-constructor_active[rid]+1e-9,
                          'constructor request exceeds soft or registered wall cap')
                check(meta.get('actual_constructor_module')==MODULE and meta.get('actual_constructor_function')==FUNCTION and meta.get('method')=='constructive',
                      'constructor implementation differs from shared A tool')
                check(type(meta.get('max_candidate_evaluations')) is int and meta['max_candidate_evaluations']==250000 and
                      type(meta.get('max_slots_per_machine')) is int and 1<=meta['max_slots_per_machine']<=8,
                      'constructor candidate/slot bounds differ')
                check(source_row.get('event')=='reserve' and source_row.get('registration_id')==rid and
                      ends.get(source,{}).get('status')=='success', 'constructor source is not a prior completed model call in same run')
                check(source not in sources,'constructor automatically retries/reuses one model choice');sources.add(source)
                if r and type(meta.get('model_index')) is int:
                    check(source_row.get('run_id')==str(Path(r['run_id'])/f"model_{meta['model_index']:03d}"),'constructor model index differs from ledger')
                else:check(False,'constructor model index is missing')
                check(type(meta.get('plan_index')) is int and meta['plan_index']>=0,'constructor plan index invalid')
                for field,value in (('constructor_calls',counts[rid]),('constructor_requested_seconds',requested[rid]),
                    ('constructor_active_seconds',constructor_active[rid]),('active_execution_seconds',model_active[rid]+constructor_active[rid])):
                    check(row.get('run_account_before',{}).get(field)==value,'constructor prior account differs: '+field)
                constructor_admissions[cid]={'registration':r,'model_active_seconds_before':model_active[rid],
                    'constructor_active_seconds_before':constructor_active[rid],'constructor_requested_seconds_before':requested[rid]}
                counts[rid]+=1
                if finite(sec):requested[rid]+=sec
        elif event in ('finish','solver_finish','constructor_finish'):
            expected={'finish':'reserve','solver_finish':'solver_reserve','constructor_finish':'constructor_reserve'}[event]
            if event=='constructor_finish':check(pending.get(cid)==expected and cid not in ends,'constructor finish lacks unique preceding reservation')
            pending.pop(cid,None);ends[cid]=row
            rid=starts.get(cid,{}).get('registration_id');duration=row.get('details',{}).get('duration_seconds')
            if event=='finish' and finite(duration):model_active[rid]+=duration
            if event=='constructor_finish':
                check(finite(duration),'constructor finish loses measured outer duration')
                check(row.get('status') in ('success','failed'),'constructor finish lacks terminal status')
                details=row.get('details',{});sha=details.get('constructor_result_sha256')
                check(isinstance(sha,str) and len(sha)==64 and all(c in '0123456789abcdef' for c in sha),'constructor finish lacks result hash')
                if finite(duration):constructor_active[rid]+=duration
    return {'errors':errors,'model_admissions':model_admissions,'constructor_admissions':constructor_admissions,
            'constructor_active_seconds_by_registration':dict(constructor_active),
            'constructor_requested_seconds_by_registration':dict(requested),
            'pending_constructor_calls':[cid for cid,kind in pending.items() if kind=='constructor_reserve']}


class _Store:
    """One new disposable DB. Only keys/row IDs/original payload hashes in RAM."""
    def __init__(self, directory):
        self.directory=Path(directory).resolve()
        self.directory.mkdir(parents=True,exist_ok=False)
        self.path=self.directory/'constructor_work.sqlite3'
        self.connection=None;self.closed=False
        try:
            self.connection=sqlite3.connect(self.path)
            self.connection.execute('PRAGMA journal_mode=DELETE')
            self.connection.execute('PRAGMA synchronous=FULL')
            self.connection.execute('CREATE TABLE payloads (id INTEGER PRIMARY KEY, value TEXT NOT NULL)')
            self.connection.commit()
            info=self.path.stat();self.identity=(info.st_dev,info.st_ino)
        except BaseException:
            if self.connection is not None:self.connection.close()
            self.closed=True
            raise

    def _open(self):
        if self.closed:raise RuntimeError('constructor audit candidate mapping is closed')
        info=self.path.lstat()
        if self.path.is_symlink() or (info.st_dev,info.st_ino)!=self.identity:
            raise ValueError('constructor audit scratch DB path replaced')

    def put(self,value):
        self._open()
        # One record only. Default JSON behavior intentionally matches the
        # legacy reader; no normalization, sorting or custom number policy.
        raw=json.dumps(value,ensure_ascii=True,separators=(',',':'))
        row=self.connection.execute('INSERT INTO payloads(value) VALUES (?)',(raw,))
        self.connection.commit()
        return (row.lastrowid,hashlib.sha256(raw.encode()).hexdigest())

    def get(self,reference):
        self._open();row=self.connection.execute('SELECT value FROM payloads WHERE id=?',(reference[0],)).fetchone()
        if row is None or type(row[0])is not str or hashlib.sha256(row[0].encode()).hexdigest()!=reference[1]:
            raise ValueError('constructor audit scratch payload differs from original stored bytes')
        value=json.loads(row[0]);self._open();return value

    def mapping(self):return _DiskMap(self)
    def histories(self):return _HistoryMap(self)
    def close(self):
        if not self.closed:
            self.connection.close();self.closed=True


class _DiskMap(MutableMapping):
    def __init__(self,store):self.store=store;self.references={}
    def __getitem__(self,key):return self.store.get(self.references[key])
    def __setitem__(self,key,value):
        # Probe hashability before storing, preserving dict key/alias semantics.
        hash(key);self.references[key]=self.store.put(value)
    def __delitem__(self,key):del self.references[key]
    def __iter__(self):return iter(self.references)
    def __len__(self):return len(self.references)
    def __contains__(self,key):return key in self.references


class _DiskHistory(Sequence):
    def __init__(self,store):self.store=store;self.references=[]
    def append(self,value):self.references.append(self.store.put(value))
    def __len__(self):return len(self.references)
    def __getitem__(self,key):
        if isinstance(key,slice):return [self.store.get(r) for r in self.references[key]]
        return self.store.get(self.references[key])
    def __iter__(self):
        for reference in self.references:yield self.store.get(reference)
    def __eq__(self,other):
        # Legacy operands are lists or the caller's JSON-array Sequence.
        # Strings/dicts were not equal to the original history list either.
        if isinstance(other,(str,bytes,bytearray,Mapping)) or not isinstance(other,Sequence):return False
        if len(other)!=len(self):return False
        return all(left==right for left,right in zip(self,other))


class _HistoryMap(MutableMapping):
    def __init__(self,store):self.store=store;self.values={}
    def __getitem__(self,key):return self.values[key]
    def __setitem__(self,key,value):
        hash(key)
        history=_DiskHistory(self.store)
        for item in value:history.append(item)
        self.values[key]=history
    def setdefault(self,key,default=None):
        # MutableMapping.setdefault returns the supplied default, but this
        # representation must return the stored disk sequence on first use.
        if key not in self.values:self[key]=default
        return self.values[key]
    def __delitem__(self,key):del self.values[key]
    def __iter__(self):return iter(self.values)
    def __len__(self):return len(self.values)


class CandidateMapping(Mapping):
    """Read-only legacy candidate values; no cached loaded candidate objects.

    get/item access returns one detached JSON record. Call close after all plan
    attribution checks; close retains scratch files for diagnosis. Closed views
    never reopen or reconstruct a candidate. This is not source authentication.
    """
    def __init__(self,values,store):self._values=values;self._store=store
    def __getitem__(self,key):return self._values[key]
    def __iter__(self):return iter(self._values)
    def __len__(self):return len(self._values)
    def __contains__(self,key):return key in self._values
    def close(self):self._store.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


def audit_constructor_evidence(run,cfg,models,ledger,read,*,scratch_dir):
    """Same checks/return keys, with an explicitly lazy candidates Mapping.

    models may be a lazy Mapping. read(lines=True) may return a repeatable
    disk-backed Sequence with complete old parsing/error/hash semantics. A list
    remains accepted, but memory for that caller-owned list is not eliminated.
    Constructor ledger replay is unchanged and still belongs to the outer audit.
    """
    run=Path(run);resolved_run=run.resolve();scratch=Path(scratch_dir).resolve()
    if scratch==resolved_run or resolved_run in scratch.parents:
        raise ValueError('scratch must be outside original raw evidence run')
    store=_Store(scratch)
    try:
        report=_audit_evidence(run,cfg,models,ledger,read,store)
        report['candidates']=CandidateMapping(report['candidates'],store)
        return report
    except BaseException:
        store.close();raise


def materialize_report(report):
    """Explicit legacy dict conversion for small tests/export; allocates all.

    Production streaming callers should consume candidates by key and close;
    calling this function intentionally gives up the candidate memory saving.
    """
    return {key:({k:value[k] for k in value} if key=='candidates' else value)
            for key,value in report.items()}


def _audit_evidence(run,cfg,models,ledger,read,store):
    """Validate every attempt, including rejected/unselected and incomplete plans."""
    run=Path(run);errors=[];missing=[];candidates=store.mapping();requests=store.mapping();outcomes=store.mapping()
    def check(ok,message):
        if not ok:errors.append(message)
    enabled=cfg.get('enable_constructive') is True
    paths=sorted(run.glob('constructor_request_*.json'))
    files=sorted(run.glob('constructor_[0-9]*.json'))
    own=[r for r in ledger if r.get('event')=='constructor_reserve' and Path(r.get('run_id','/')).resolve()==run.resolve()]
    if not enabled:
        check(not paths and not files and not own,'constructor evidence exists without explicit enabled C configuration')
        return {'errors':errors,'missing_evidence':missing,'candidates':candidates,'attempts':0}
    check(cfg.get('arm')=='C' and cfg.get('controller_version')==VERSION and cfg.get('constructor_seconds_cap')==5 and
          cfg.get('constructor_evaluation_cap')==250000,'constructive controller scope/version/caps differ')
    check(len(paths)==len(own),'constructor request files and reservations differ')
    check(len(files)==len(paths),'constructor request/result files differ')
    events=read(run/'constructor_evidence.jsonl',optional=True,lines=True) or []
    check(len(events)==len(paths),'constructor outcome evidence omits or duplicates an attempt')
    finishes={r['call_id']:r for r in ledger if r.get('event')=='constructor_finish'}
    reserves={r['call_id']:r for r in own}
    for index,path in enumerate(paths):
        request=read(path)
        if not isinstance(request,dict):continue
        check(path.name==f'constructor_request_{index:03d}.json','constructor request indices are not contiguous')
        cid=request.get('constructor_call_id');mi=request.get('model_index');pi=request.get('plan_index')
        try:
            model=models[mi]['result'];response=model['output'];problem=read(run/f'problem_{pi:03d}.json')
            check(model.get('status')=='success' and response.get('action')=='solve' and response.get('method')=='constructive',
                  'constructor did not originate from explicit successful model choice')
            check(request.get('response')==response and request.get('call_id')==request.get('model_call_id')==model['call_id'],
                  'constructor request differs from exact model output/call')
            parameters={'time_limit_seconds':response['seconds'],'seed':response['seed'],'weights':response['weights'],
                        'max_slots_per_machine':response['slots'],'plan_version':cfg['run_id']+':'+str(pi)}
            check(request.get('parameters')==parameters and request.get('problem_sha256')==digest(problem),'constructor parameters/observed problem differ')
            check(response.get('index') is None and finite(response.get('seconds')) and 0<response['seconds']<=5 and
                type(response.get('slots')) is int and 1<=response['slots']<=8 and type(response.get('seed')) is int and 0<=response['seed']<2**31,
                'constructor model parameters outside bounded tool schema')
            weights=response.get('weights',{})
            check(set(weights)=={'completion','flow','tardiness','setup'} and any(weights.values()) and
                all(type(v)is int and 0<=v<=100000 for v in weights.values()),'constructor objective weights differ from shared specification')
            reservation=reserves.get(cid);finish=finishes.get(cid)
            if not reservation or not finish:
                missing.append(f'constructor {index}: reservation and terminal finish required');continue
            meta=reservation['metadata']
            check(all(request.get(k)==v for k,v in meta.items()),'constructor metadata differs from prior reservation')
            check(request.get('constructor_index')==index and request.get('requested_seconds')==response['seconds']==reservation['requested_seconds'],
                  'constructor requested seconds/index differs')
            matches=[e for e in events if e.get('constructor_index')==index]
            if len(matches)!=1:missing.append(f'constructor {index}: unique outcome');continue
            evidence=matches[0]
            check(all(evidence.get(k)==v for k,v in request.items() if k not in ('response','parameters')),'constructor outcome/request linkage differs')
            solved=read(run/f'constructor_{index+1:03d}.json')
            if not isinstance(solved,dict):continue
            details=finish.get('details',{})
            check(evidence.get('status')==finish.get('status') and evidence.get('duration_seconds')==details.get('duration_seconds'),
                  'constructor outcome differs from ledger duration/status')
            check(digest(solved)==evidence.get('constructor_result_sha256')==details.get('constructor_result_sha256'),
                  'constructor immutable result hash differs')
            check(solved.get('invocation_duration_seconds')==details.get('duration_seconds') and solved.get('constructor_call_id')==cid,
                  'durable constructor result loses outer duration/call identity')
            check(details.get('solver_status')==solved.get('solver_status') and solved.get('requested_method')=='constructive',
                  'constructor terminal tool status differs')
            cp=solved.get('cp_sat',{})
            check(cp.get('status')=='NOT_RUN_BY_POLICY' and cp.get('requested_seconds')==0 and cp.get('calls')==0 and
                  solved.get('best_bound') is None and solved.get('global_optimality_claim') is False,
                  'constructor improperly charged/claimed CP or global optimality')
            if finish['status']=='success':
                check(solved.get('model')==MODEL and solved.get('selected_source')=='classical_incumbent','constructor is not the shared A method')
                check(solved.get('solver_requested_seconds')==0 and solved.get('solver_calls')==0,'constructor result charges CP budget')
                check(solved.get('parameters')=={k:v for k,v in parameters.items() if k!='plan_version'}|{'max_candidate_evaluations':250000,'rule':'gain_rate'},
                      'constructor result parameters differ from chosen tool call')
                check(solved.get('seed_semantics',{}).get('used') is False and solved.get('seed_semantics',{}).get('meaning')=='not_used_by_deterministic_constructor',
                      'constructor seed behavior not disclosed')
            else:
                check(solved.get('record_type')=='constructor_exception' and solved.get('solver_status')=='CONSTRUCTOR_EXCEPTION' and bool(solved.get('error')) and solved.get('plan') is None,
                      'failed constructor lacks preserved exception candidate')
            plan=solved.get('plan');nominal=solved.get('nominal_audit') or {}
            valid=solved.get('solver_status') in ('OPTIMAL','FEASIBLE','FEASIBLE_HEURISTIC') and isinstance(plan,dict) and nominal.get('valid') is True
            if solved.get('solver_status')=='FEASIBLE_HEURISTIC':
                check(valid and solved.get('tasks')==plan.get('tasks'),'heuristic constructor lacks nominal-valid task sequence')
            requests[mi]=request;outcomes[mi]=evidence
            candidates[mi]={'solved':solved,'valid':valid,'constructor_index':index,'plan_index':pi,'constructor_call_id':cid}
        except (KeyError,TypeError,ValueError,IndexError) as exc:
            errors.append(f'constructor {index}: malformed evidence ({type(exc).__name__})')
    result=read(run/'result.json',optional=True)
    if result:
        check(result.get('constructor_calls')==len(own) and result.get('constructor_requested_seconds')==sum(r['requested_seconds'] for r in own),
              'result omits constructor count/requested seconds')
        actual=sum(finishes[r['call_id']]['details']['duration_seconds'] for r in own if r['call_id'] in finishes)
        check(result.get('constructor_active_seconds')==actual,'result omits constructor measured activity')
    history_events=read(run/'controller_history_events.jsonl',optional=True,lines=True) or []
    history_by_plan=store.histories();seen_indices=set()
    for event in history_events:
        mi=event.get('model_index');pi=event.get('plan_index');entry=event.get('entry',{})
        try:
            check(mi not in seen_indices,'duplicate controller history action');seen_indices.add(mi)
            model=models[mi];response=model['result']['output'];history=history_by_plan.setdefault(pi,[])
            if mi in candidates:check(candidates[mi]['plan_index']==pi,'constructor feedback attached to another plan')
            check(model['result'].get('status')=='success' and entry.get('decision')==response,'history event invents/changes a model decision')
            check(model['sections'].get('OWN_HISTORY')==history,'history prompt differs from accepted prior actions')
            if mi in candidates:
                candidate=candidates[mi];solved=candidate['solved'];feedback=entry.get('result',{});plan=solved.get('plan');tasks=plan.get('tasks',[]) if isinstance(plan,dict) else []
                expected={k:solved.get(k) for k in FEEDBACK_FIELDS}
                expected.update(candidate_index=sum(e.get('decision',{}).get('action')=='solve' for e in history),valid_candidate=candidate['valid'],
                    task_count=len(tasks),plan_sha256=digest(plan) if isinstance(plan,dict) else None,
                    unplanned_operations_count=len(solved.get('unplanned_operations',{})),tasks_preview=tasks[:12],method='constructive',
                    constructor_index=candidate['constructor_index'],constructor_call_id=candidate['constructor_call_id'],
                    constructor_requested_seconds=requests[mi]['requested_seconds'],constructor_duration_seconds=outcomes[mi]['duration_seconds'],
                    classical_construction_wall_seconds=solved.get('classical_construction_wall_seconds'),nominal_audit=solved.get('nominal_audit'),
                    seed_semantics=solved.get('seed_semantics'),error=solved.get('error'))
                check(feedback==expected,'constructor feedback differs from immutable result and explicit candidate index')
            history.append(entry)
        except (KeyError,TypeError,ValueError):errors.append('malformed controller history event')
    check(all(mi in seen_indices for mi in candidates),'constructor outcome missing durable controller feedback event')
    for pi,history in history_by_plan.items():
        path=run/f'controller_history_{pi:03d}.json'
        if path.exists():check(read(path)==history,'committed history differs from durable action events')
    return {'errors':errors,'missing_evidence':missing,'candidates':candidates,'attempts':len(paths)}

