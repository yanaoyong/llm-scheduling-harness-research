"""Atomic session-local acceptance; publish only after a successful session exit.

The physical precheck is read-only and returns a list of violations. The host
must serialize calls to this object and persist its capture with the cycle WAL.
"""
from copy import deepcopy
from .plan_delta import (compile_plan_delta, DeltaError, json_sha256)
from .normalize import validate_plan, number


def coverage_report(plan, problem):
    assigned = {o for task in plan['tasks'] for o in task['operation_ids']}
    observed = {o['operation_id'] for o in problem['operations']}
    return {'observed_operations': len(observed), 'reserved_operations': len(assigned & observed),
            'uncovered_operation_ids': sorted(observed - assigned), 'report_only': True}


class Submitter:
    def __init__(self, base_plan, problem, execution_state, *, state_version, next_anchor,
                 delta_seconds=60, source_sha256, physical_precheck=None):
        self.base_plan = deepcopy(base_plan)
        self.problem = deepcopy(problem)
        self.execution_state = deepcopy(execution_state)
        self.state_version = state_version
        self.next_anchor = next_anchor
        self.delta_seconds = delta_seconds
        self.source_sha256 = source_sha256
        self.physical_precheck = physical_precheck
        self.receipts = {}
        self.candidate = None
        self.closed = False
        self.finalized = False
        self.adopted = False

    def submit_plan(self, expected_state_version, submission_id, delta):
        if not isinstance(submission_id, str) or not submission_id:
            return {'accepted': False, 'violations': [{'code': 'submission_id', 'detail': 'nonempty ID required'}]}
        signature = json_sha256([expected_state_version, delta])
        if submission_id in self.receipts:
            old = self.receipts[submission_id]
            if old['request_sha256'] == signature:
                return deepcopy(old)
            return {'accepted': False, 'violations': [{'code': 'submission_id_conflict', 'detail': submission_id}]}
        errors = []
        if self.closed or self.finalized:
            errors.append({'code': 'cycle_closed', 'detail': 'one successful submit per cycle'})
        if expected_state_version != self.state_version:
            errors.append({'code': 'stale_state_version', 'detail': 'state version differs'})
        plan = None
        evidence = None
        if not errors:
            if delta == {}:
                # No-change is an explicit commit of the old production payload.
                plan = deepcopy(self.base_plan)
                projection = deepcopy(plan)
                projection['tasks'] = [t for t in plan['tasks'] if t['id'] not in self.execution_state['dispatched_task_ids']]
                projection['created_at'] = self.execution_state['time']
                projection['freeze_until'] = max(projection['freeze_until'], self.execution_state['time'])
                errors.extend(validate_plan(projection, self.problem, self.execution_state, base_plan=self.base_plan))
            else:
                supplied = deepcopy(delta)
                if isinstance(supplied, dict):
                    for name, mode in [('tasks', 'all_pending_except'), ('holds', 'all_except')]:
                        if name not in supplied:
                            supplied[name] = {'keep': {'mode': mode, 'ids': []}, 'cancel_ids': [], 'replace': [], 'add': []}
                        elif isinstance(supplied[name], dict) and 'keep' not in supplied[name]:
                            supplied[name]['keep'] = {'mode': mode, 'ids': []}
                try:
                    compiled = compile_plan_delta(self.base_plan, self.problem, self.execution_state,
                                                  supplied, source_sha256=self.source_sha256)
                    plan, evidence = compiled['plan'], compiled['evidence']
                except DeltaError as exc:
                    errors.extend(exc.violations)
            end = plan.get('valid_until') if plan is not None else (
                delta.get('plan_header', {}).get('valid_until') if isinstance(delta, dict)
                and isinstance(delta.get('plan_header', {}), dict) else None)
            if not number(end) or end < self.next_anchor + self.delta_seconds:
                errors.append({'code': 'valid_until_lower_bound', 'detail': 'requires next_anchor + delta'})
            if plan is not None and self.physical_precheck is not None:
                errors.extend(self.physical_precheck(deepcopy(plan), deepcopy(self.problem), deepcopy(self.execution_state)))
        receipt = {'submission_id': submission_id, 'request_sha256': signature,
                   'accepted': not errors, 'violations': errors, 'no_change': delta == {},
                   'coverage': coverage_report(plan, self.problem) if plan is not None else None,
                   'plan_sha256': json_sha256(plan) if plan is not None else None, 'evidence': evidence}
        if not errors:
            self.candidate = plan
            self.closed = True
        self.receipts[submission_id] = deepcopy(receipt)
        return deepcopy(receipt)

    def finalize(self, *, process_ok, usage_known=True):
        if not self.finalized:
            self.adopted = bool(process_ok and usage_known and self.candidate is not None)
            self.finalized = True
            self.closed = True
        return deepcopy(self.candidate if self.adopted else self.base_plan)

    def capture(self):
        return deepcopy({k: v for k, v in vars(self).items() if k != 'physical_precheck'})

    @classmethod
    def restore(cls, state, *, physical_precheck=None):
        obj = cls.__new__(cls)
        obj.__dict__.update(deepcopy(state))
        obj.physical_precheck = physical_precheck
        return obj
