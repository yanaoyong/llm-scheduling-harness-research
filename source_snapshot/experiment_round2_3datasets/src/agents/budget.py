"""Process-safe append-only shared attempt ledger. Failed/reserved calls consume budget.

Token admission uses completed calls' reported input + output; cached input and
reasoning output are subsets, never added again. This is an observed threshold,
not a server-side output limit: a bounded call can cross it before the next
admission check. Serial formal batches therefore can overshoot by one call;
concurrent development can overshoot by the calls already in flight. Missing
usage in completed attempts is counted separately from pending reservations.
"""
from __future__ import annotations
import contextlib
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER = ROOT / 'progress/model_ledger.jsonl'
DEVELOPMENT_HARD_LIMIT = 24
PHASE_TOKEN_LIMITS = {'development':400_000, 'formal':3_000_000}
UNKNOWN_COMPLETED_ATTEMPT_LIMIT = 3

def _token_account(records, phase):
    reservations=[r for r in records if r.get('event')=='reserve' and r.get('phase')==phase]
    completed={}
    for row in records:
        if row.get('event')=='finish':
            if row['call_id'] in completed:
                raise ValueError('Duplicate finish record; token admission fails closed')
            completed[row['call_id']]=row
    inputs=outputs=0
    unknown=[];pending=[];finished=0
    for reserve in reservations:
        call_id=reserve['call_id']
        if call_id not in completed:
            pending.append(call_id)
            continue
        finished+=1
        usage=completed[call_id].get('details',{}).get('usage')
        usage=usage if isinstance(usage,dict) else {}
        incoming,outgoing=usage.get('input_tokens'),usage.get('output_tokens')
        input_known=type(incoming) is int and incoming>=0
        output_known=type(outgoing) is int and outgoing>=0
        if input_known: inputs+=incoming
        if output_known: outputs+=outgoing
        if not input_known or not output_known: unknown.append(call_id)
    return {'reported_input_tokens':inputs,'reported_output_tokens':outputs,
            'reported_total_tokens':inputs+outputs,'completed_attempts':finished,
            'unknown_completed_attempts':len(unknown),'unknown_completed_call_ids':unknown,
            'pending_attempts':len(pending),'pending_call_ids':pending}

class BudgetExceeded(RuntimeError):
    pass

class BudgetLedger:
    def __init__(self, path=DEFAULT_LEDGER):
        self.path = Path(path).resolve()

    @contextlib.contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(self.path.suffix + '.lock').open('a+') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                records = []
                if self.path.exists():
                    # Any truncated/corrupted record fails closed, never silently resets usage.
                    records = [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]
                yield records
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _append(self, item):
        item = {'at':dt.datetime.now(dt.timezone.utc).isoformat(), **item}
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        return item

    def grant(self, grant_id, phase, max_calls, run_prefix, *, phase_limit=None, phase_limit_tokens=None):
        """Explicit operator allocation; does not itself make model calls."""
        if phase not in ('development', 'formal') or type(max_calls) is not int or max_calls < 1:
            raise ValueError('Invalid grant')
        if phase == 'development':
            phase_limit = DEVELOPMENT_HARD_LIMIT
        elif type(phase_limit) is not int or phase_limit < 1:
            raise ValueError('Formal grants require a predeclared phase_limit')
        if phase_limit_tokens is None:
            phase_limit_tokens=PHASE_TOKEN_LIMITS[phase]
        if type(phase_limit_tokens) is not int or not 1<=phase_limit_tokens<=PHASE_TOKEN_LIMITS[phase]:
            raise ValueError('Token threshold must be a positive integer within the phase maximum')
        value = dict(event='grant', grant_id=grant_id, phase=phase, max_calls=max_calls,
                     run_prefix=str(run_prefix), phase_limit=phase_limit,phase_limit_tokens=phase_limit_tokens)
        with self._locked() as records:
            old = [r for r in records if r.get('event') == 'grant' and r.get('grant_id') == grant_id]
            if old:
                # Legacy grants remain byte-for-byte unchanged and receive the documented default.
                normalized={**old[0],'phase_limit_tokens':old[0].get('phase_limit_tokens',PHASE_TOKEN_LIMITS[old[0]['phase']])}
                if all(normalized.get(k) == v for k,v in value.items()):
                    return old[0]
                raise ValueError('Grant IDs are immutable')
            limits = {r['phase_limit'] for r in records if r.get('event') == 'grant' and r.get('phase') == phase}
            if limits and limits != {phase_limit}:
                raise ValueError('Phase limit already frozen; use a new explicit protocol phase')
            token_limits={r.get('phase_limit_tokens',PHASE_TOKEN_LIMITS[phase]) for r in records
                          if r.get('event')=='grant' and r.get('phase')==phase}
            if token_limits and token_limits!={phase_limit_tokens}:
                raise ValueError('Phase token threshold already frozen')
            return self._append(value)

    def reserve(self, *, phase, run_id, grant_id, call_id=None, metadata=None):
        call_id = call_id or str(uuid.uuid4())
        with self._locked() as records:
            grants = [r for r in records if r.get('event') == 'grant' and r.get('grant_id') == grant_id]
            if len(grants) != 1:
                raise BudgetExceeded('No unique explicit grant for this call')
            grant = grants[0]
            if grant['phase'] != phase or not run_id.startswith(grant['run_prefix']):
                raise BudgetExceeded('Call does not match its grant phase/run prefix')
            calls = [r for r in records if r.get('event') == 'reserve']
            if any(r['call_id'] == call_id for r in calls):
                raise ValueError('Duplicate call_id')
            if sum(r['phase'] == phase for r in calls) >= grant['phase_limit']:
                raise BudgetExceeded('Phase model-attempt budget exhausted')
            if sum(r['grant_id'] == grant_id for r in calls) >= grant['max_calls']:
                raise BudgetExceeded('Allocated model-attempt budget exhausted')
            tokens=_token_account(records,phase)
            token_limit=grant.get('phase_limit_tokens',PHASE_TOKEN_LIMITS[phase])
            if tokens['reported_total_tokens']>=token_limit:
                raise BudgetExceeded(f'Observed phase token threshold reached: {tokens["reported_total_tokens"]} >= {token_limit}; no further call admitted')
            if tokens['unknown_completed_attempts']>=UNKNOWN_COMPLETED_ATTEMPT_LIMIT:
                raise BudgetExceeded('Completed calls with unknown usage reached the phase limit of 3; diagnose before further admission')
            self._append(dict(event='reserve',call_id=call_id,phase=phase,run_id=run_id,
                              grant_id=grant_id,resource='model_call',metadata=metadata or {},
                              token_admission={'phase_limit_tokens':token_limit,
                                               'reported_tokens_before':tokens['reported_total_tokens'],
                                               'unknown_completed_before':tokens['unknown_completed_attempts'],
                                               'pending_before':tokens['pending_attempts']}))
        return call_id

    def finish(self, call_id, status, details=None):
        with self._locked() as records:
            if not any(r.get('event') in ('reserve','solver_reserve') and r.get('call_id') == call_id for r in records):
                raise ValueError('Finish without reserve')
            if any(r.get('event') == 'finish' and r.get('call_id') == call_id for r in records):
                raise ValueError('Call already finished')
            return self._append(dict(event='finish',call_id=call_id,status=status,details=details or {}))

    def grant_solver(self, grant_id, phase, max_seconds, run_prefix, *, phase_limit=None):
        if phase not in ('development','formal') or not 0 < max_seconds:
            raise ValueError('Invalid solver grant')
        phase_limit = 600.0 if phase == 'development' else phase_limit
        if phase_limit is None or phase_limit <= 0:
            raise ValueError('Formal solver phase limit required')
        value = dict(event='solver_grant',grant_id=grant_id,phase=phase,max_seconds=float(max_seconds),
                     run_prefix=str(run_prefix),phase_limit=float(phase_limit))
        with self._locked() as records:
            old = [r for r in records if r.get('event') == 'solver_grant' and r.get('grant_id') == grant_id]
            if old:
                if all(old[0].get(k) == v for k,v in value.items()):
                    return old[0]
                raise ValueError('Solver grant IDs are immutable')
            limits = {r['phase_limit'] for r in records if r.get('event') == 'solver_grant' and r.get('phase') == phase}
            if limits and limits != {float(phase_limit)}:
                raise ValueError('Solver phase limit already frozen')
            return self._append(value)

    def reserve_solver(self, *, phase, run_id, grant_id, requested_seconds, call_id=None, metadata=None):
        if isinstance(requested_seconds,bool) or not 0 < requested_seconds <= 3600:
            raise ValueError('Invalid requested solver seconds')
        call_id = call_id or str(uuid.uuid4())
        with self._locked() as records:
            grants = [r for r in records if r.get('event') == 'solver_grant' and r.get('grant_id') == grant_id]
            if len(grants) != 1:
                raise BudgetExceeded('No unique solver grant')
            grant = grants[0]
            if grant['phase'] != phase or not run_id.startswith(grant['run_prefix']):
                raise BudgetExceeded('Solver call outside grant scope')
            reserved = [r for r in records if r.get('event') == 'solver_reserve']
            if any(r.get('call_id') == call_id for r in records):
                raise ValueError('Duplicate call_id')
            if sum(r['requested_seconds'] for r in reserved if r['phase'] == phase) + requested_seconds > grant['phase_limit'] + 1e-9:
                raise BudgetExceeded('Phase solver budget exhausted')
            if sum(r['requested_seconds'] for r in reserved if r['grant_id'] == grant_id) + requested_seconds > grant['max_seconds'] + 1e-9:
                raise BudgetExceeded('Allocated solver budget exhausted')
            self._append(dict(event='solver_reserve',call_id=call_id,phase=phase,run_id=run_id,
                              grant_id=grant_id,resource='solver_seconds',requested_seconds=float(requested_seconds),metadata=metadata or {}))
        return call_id

    def summary(self):
        with self._locked() as records:
            reservations = [r for r in records if r.get('event') == 'reserve']
            finished = {r['call_id'] for r in records if r.get('event') == 'finish'}
            return {'attempts': len(reservations), 'unfinished_call_ids': [r['call_id'] for r in reservations if r['call_id'] not in finished],
                    'by_phase': {p:sum(r['phase']==p for r in reservations) for p in ('development','formal')},
                    'tokens_by_phase':{p:{**_token_account(records,p),
                        'phase_limit_tokens':next((r.get('phase_limit_tokens',PHASE_TOKEN_LIMITS[p]) for r in records if r.get('event')=='grant' and r.get('phase')==p),PHASE_TOKEN_LIMITS[p]),
                        'unknown_completed_attempt_limit':UNKNOWN_COMPLETED_ATTEMPT_LIMIT}
                        for p in ('development','formal')}}
