"""Candidate shared-start host adapter; no controller/model/ledger authority.

Install as a NEW src/smt_fullfab/shared_controller.py only after review/tests.
The trusted host owns Branch exclusively. This is not a model sandbox or an
automatic resume API. Original physics, observation_start and horizon are kept.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from src.smt_fullfab import shared_start as ss
from src.smt_fullfab import stream_snapshot

SCHEMA = 'smt-shared-controller-context-v1'
CLOCK_SCHEMA = SCHEMA + '-clock'
BINDING_SCHEMA = SCHEMA + '-binding'
ADMISSION_SCHEMA = SCHEMA + '-offline-A-admission'
WINDOWS = (3600, 28800, 86400)
PERIODIC = 'periodic_cp'  # Exact existing hybrid.solve_hybrid_plan mode names.
EVENT = 'event_classical'
REGISTRATION_KEYS = frozenset(('registration_id', 'amendment_id', 'budget_id',
    'run_id', 'arm', 'scenario', 'window_seconds', 'solver_seconds',
    'wall_seconds', 'max_log_bytes', 'phase', 'formal'))
BINDING_KEYS = frozenset(('schema', 'shared_start_id', 'package_path',
    'package_manifest_sha256', 'snapshot_sha256', 'state_sha256',
    'prehistory_sha256', 'arm', 'run_name', 'run_path', 'registration_kind',
    'registration_path', 'registration_document_sha256', 'registration_id',
    'source_sha256', 'config_sha256', 'evaluation', 'window_seconds'))
WINDOW_KEYS = frozenset(('absolute_start', 'absolute_end', 'physical_episode_end',
    'period_anchor', 'period_seconds', 'plan_seconds', 'lookahead_depth'))


class ContextError(ValueError):
    pass


def require(value, message):
    if not value:
        raise ContextError(message)


def same(a, b):
    return ss.canonical(a) == ss.canonical(b)


def _absolute(value):
    require(type(value) is str and Path(value).is_absolute(), 'absolute path required')
    path = Path(value)
    require(str(path.resolve()) == value, 'canonical absolute path required')
    require(not path.is_symlink(), 'leaf symlink is forbidden')
    return path


def _window(value):
    require(type(value) is dict and set(value) == WINDOW_KEYS, 'window fields differ')
    require(all(ss.number(value[k]) for k in WINDOW_KEYS - {'lookahead_depth'}),
            'finite non-bool window numbers required')
    require(0 < value['absolute_start'] < value['absolute_end'] == value['physical_episode_end']
            and value['period_anchor'] == value['absolute_start']
            and value['period_seconds'] == 1800 and value['plan_seconds'] == 14400
            and type(value['lookahead_depth']) is int and value['lookahead_depth'] == 2,
            'shared M1 window/planning contract differs')
    return deepcopy(value)


class AnchoredPeriodClock:
    """No physical clock writes: every successful commit records one due edge."""

    def __init__(self, evaluation, *, state=None):
        self.window = _window(evaluation)
        self.next_period_index = 0
        self.last_commit_time = None
        self.last_periodic_commit_time = None
        if state is not None:
            require(type(state) is dict and set(state) == {'schema', 'evaluation',
                'next_period_index', 'last_commit_time', 'last_periodic_commit_time'},
                'complete clock state required')
            require(state['schema'] == CLOCK_SCHEMA and same(state['evaluation'], self.window),
                    'clock configuration differs')
            self.next_period_index = state['next_period_index']
            self.last_commit_time = state['last_commit_time']
            self.last_periodic_commit_time = state['last_periodic_commit_time']
        self._validate()

    @property
    def next_period_at(self):
        return self.window['period_anchor'] + self.next_period_index * self.window['period_seconds']

    def _validate(self):
        i = self.next_period_index
        w = self.window
        require(type(i) is int and 0 <= i <= math.ceil(
            (w['absolute_end'] - w['absolute_start']) / w['period_seconds']), 'invalid period index')
        if i == 0:
            require(self.last_commit_time is None and self.last_periodic_commit_time is None,
                    'uncommitted clock cannot have commit history')
        else:
            expected = w['period_anchor'] + (i - 1) * w['period_seconds']
            require(ss.number(self.last_commit_time) and ss.number(self.last_periodic_commit_time)
                    and self.last_periodic_commit_time == expected
                    and expected <= self.last_commit_time < min(self.next_period_at, w['absolute_end']),
                    'clock history differs from its exact prior edge')

    def mode(self, now):
        w = self.window
        require(ss.number(now) and w['absolute_start'] <= now < w['absolute_end'],
                'clock is outside evaluation window')
        require(self.last_commit_time is None or now >= self.last_commit_time, 'clock moved backwards')
        require(now <= self.next_period_at, 'missed required absolute period; no catch-up')
        return PERIODIC if now == self.next_period_at else EVENT

    def committed(self, now, mode=None):
        actual = self.mode(now)
        require(mode is None or mode == actual, 'commit mode differs from due edge')
        if actual == PERIODIC:
            self.next_period_index += 1
            self.last_periodic_commit_time = now
        self.last_commit_time = now
        self._validate()
        return actual

    def advance_target(self, now):
        require(self.mode(now) == EVENT, 'required period has not been committed')
        return min(self.window['absolute_end'], self.next_period_at)

    def snapshot(self):
        return {'schema': CLOCK_SCHEMA, 'evaluation': deepcopy(self.window),
                'next_period_index': self.next_period_index,
                'last_commit_time': self.last_commit_time,
                'last_periodic_commit_time': self.last_periodic_commit_time}


class SharedHybridClock(AnchoredPeriodClock):
    """Pure A request mode helper. Does not reserve budgets or invoke algorithms."""

    def request(self, now, *, remaining_cp_seconds, periodic_request_seconds):
        require(ss.number(remaining_cp_seconds) and remaining_cp_seconds >= 0
                and ss.number(periodic_request_seconds) and periodic_request_seconds >= .05,
                'finite explicit CP balances required')
        mode = self.mode(now)
        if mode == EVENT:
            return mode, 0.0
        require(remaining_cp_seconds >= .05, 'required periodic CP budget exhausted')
        return mode, min(remaining_cp_seconds, periodic_request_seconds)


def _registration(binding, registration, seed):
    arm, duration = binding['arm'], binding['window_seconds']
    if arm in ('B', 'C'):
        require(binding['registration_kind'] == 'stage2_research_registration'
                and type(registration) is dict and set(registration) == REGISTRATION_KEYS,
                'original exact B/C stage registration required')
        unsigned = {k: v for k, v in registration.items() if k != 'registration_id'}
        # Exact BudgetLedger.record_sha256 convention, including non-ASCII paths.
        rid = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
        require(registration['registration_id'] == binding['registration_id'] == rid,
                'stage registration identity differs')
        require(registration['run_id'] == binding['run_path'] and registration['arm'] == arm
                and type(registration['scenario']) is int and registration['scenario'] == seed
                and type(registration['window_seconds']) is int and registration['window_seconds'] == duration
                and registration['phase'] == 'stage2_research' and registration['formal'] is False,
                'stage registration run/arm/scenario/window differs')
        require(all(type(registration[k]) is str and registration[k] for k in ('amendment_id', 'budget_id')),
                'original authority identifiers absent')
        cp = registration['solver_seconds']
        require(ss.number(cp) and (cp == 0 if arm == 'B' else cp > 0), 'arm CP admission differs')
    else:
        keys = {'schema', 'arm', 'run_path', 'run_name', 'seed', 'window_seconds',
                'source_sha256', 'config_sha256', 'solver_budget_seconds', 'wall_seconds',
                'max_log_bytes', 'model_calls'}
        require(binding['registration_kind'] == 'offline_A_admission' and binding['registration_id'] is None
                and type(registration) is dict and set(registration) == keys
                and registration['schema'] == ADMISSION_SCHEMA and registration['arm'] == 'A',
                'explicit offline A admission required, not a stage registration')
        require(registration['run_path'] == binding['run_path'] and registration['run_name'] == binding['run_name']
                and type(registration['seed']) is int and registration['seed'] == seed
                and type(registration['window_seconds']) is int and registration['window_seconds'] == duration
                and registration['source_sha256'] == binding['source_sha256']
                and registration['config_sha256'] == binding['config_sha256']
                and type(registration['model_calls']) is int and registration['model_calls'] == 0
                and ss.number(registration['solver_budget_seconds']) and registration['solver_budget_seconds'] > 0,
                'offline A admission differs')
    require(ss.number(registration['wall_seconds']) and registration['wall_seconds'] > 0
            and type(registration['max_log_bytes']) is int and registration['max_log_bytes'] > 0,
            'positive wall/log admission limits required')


def _binding(value, manifest, *, package, output, manifest_sha, source_sha):
    require(type(value) is dict and set(value) == BINDING_KEYS and value['schema'] == BINDING_SCHEMA,
            'exact shared binding required')
    require(value['arm'] in ('A', 'B', 'C') and ss.name_string(value['run_name'])
            and _absolute(value['run_path']) == output and output.name == value['run_name'],
            'short run name and actual absolute directory differ')
    require(_absolute(value['package_path']) == package and value['package_manifest_sha256'] == manifest_sha
            and value['source_sha256'] == source_sha and ss.sha_string(value['config_sha256']),
            'external package/source/config anchors differ')
    require(value['shared_start_id'] == manifest['shared_start_id']
            and value['snapshot_sha256'] == manifest['snapshot_sha256']
            and value['state_sha256'] == manifest['state_sha256']
            and value['prehistory_sha256'] == manifest['prehistory_receipt']['sha256'],
            'original shared state or prehistory differs')
    w = _window(value['evaluation'])
    require(same(w, manifest['evaluation_window']) and type(value['window_seconds']) is int
            and value['window_seconds'] in WINDOWS
            and value['window_seconds'] == w['absolute_end'] - w['absolute_start'],
            'registration duration must be delta, not absolute H')
    require(ss.sha_string(value['registration_document_sha256']), 'original registration bytes SHA required')
    return w


def _ref(path, sha):
    require(ss.sha_string(sha), 'external original SHA required')
    path = _absolute(str(path))
    ss.read_bytes(path, sha, retain=False)
    return {'path': str(path), 'sha256': sha}


class SharedRunContext:
    """Construct via open_shared_run. An exclusive host capability, not authority."""

    def __init__(self, branch, binding, references):
        self._branch = branch
        self._env = branch._env  # Deliberate version-pinned trusted-host adaptation.
        self._binding = deepcopy(binding)
        self._refs = deepcopy(references)
        self._directory = Path(binding['run_path'])
        self._clock = AnchoredPeriodClock(binding['evaluation'])
        self._origin_observation_start = self._env.observation_start
        self._origin_horizon = self._env.horizon
        self._origin_manifest_horizon = self._env.manifest['horizon']
        self._origin_seed = self._env.seed
        self._scope = sorted(self._env.physical)
        self._commits = 0
        self._advances = 0
        self._poisoned = False
        self._check_physics()

    def _check_physics(self):
        w = self._binding['evaluation']
        e = self._env
        require(e.seed == self._origin_seed and type(e.seed) is int
                and same(e.observation_start, self._origin_observation_start)
                and same(e.horizon, self._origin_horizon)
                and same(e.manifest['horizon'], self._origin_manifest_horizon)
                and ss.number(e.horizon) and e.horizon == w['physical_episode_end'] == e.manifest['horizon']
                and ss.number(e.t) and w['absolute_start'] <= e.t <= e.horizon
                and type(e.finished) is bool and e.finished == (e.t == e.horizon)
                and sorted(e.physical) == self._scope and len(self._scope) == 913
                and all(type(mid) is int for mid in self._scope),
                'original physics horizon/clock/scope/observation fields changed')

    def _live(self):
        require(not self._poisoned and not self._branch._poisoned, 'poisoned context; read-only diagnosis only')
        try:
            self._check_physics()
        except BaseException as exc:
            self._poison(exc)
            raise

    def _fence(self):
        for ref in self._refs:
            ss.read_bytes(ref['path'], ref['sha256'], retain=False)

    def _poison(self, exc):
        self._poisoned = True
        self._branch._poisoned = True
        try:
            ss.publish(self._directory / 'context_failure.json', {'schema': SCHEMA + '-failure',
                'type': type(exc).__name__, 'message': str(exc), 'commits_observed': self._commits,
                'advances_observed': self._advances, 'automatic_retry': False})
        except BaseException as secondary:
            if hasattr(exc, 'add_note'):
                exc.add_note('context failure publication also failed: ' + repr(secondary))

    def status(self):
        self._live()
        return {'absolute_time': self._env.t, 'physical_horizon': self._env.horizon,
                'finished': self._env.finished, 'physical_scope': deepcopy(self._scope)}

    def problem(self):
        self._live()
        try:
            problem = self._branch.problem()
            self._branch._before_first()
            self._check_physics()
            return problem
        except BaseException as exc:
            self._poison(exc)
            raise

    def prior_plan_state(self):
        self._live()
        try:
            self._branch._before_first()
            plan = deepcopy(self._env.plan)
            require(type(plan) is dict, 'original shared plan must be present; no cold_base')
            return {'base_plan': plan, 'base_plan_version': plan['version'],
                    'dispatched_task_ids': [deepcopy(t['id']) for t in plan['tasks']
                        if (plan['version'], t['id']) in self._env.executed_tasks]}
        except BaseException as exc:
            self._poison(exc)
            raise

    def commit_exact(self, plan, *, decision_evidence_ref):
        self._live()
        try:
            require(type(plan) is dict and type(decision_evidence_ref) is dict
                    and set(decision_evidence_ref) == {'path', 'sha256'}, 'explicit plan/evidence reference required')
            ref = _ref(decision_evidence_ref['path'], decision_evidence_ref['sha256'])
            require(Path(ref['path']).is_relative_to(self._directory), 'decision evidence must belong to this run')
            raw_plan = deepcopy(plan)
            plan_sha = ss.digest(raw_plan)
            now, index = self._env.t, len(self._env.trace)
            mode = self._clock.mode(now)
            self._fence()
            folder = self._directory / 'context_commits'
            folder.mkdir(exist_ok=True)
            prefix = folder / f'{self._commits:06d}'
            intent = {'schema': SCHEMA + '-commit-intent', 'index': self._commits,
                'time': now, 'trace_event_index': index, 'plan': raw_plan, 'plan_sha256': plan_sha,
                'decision_evidence_ref': ref, 'binding_sha256': self._refs[0]['sha256'],
                'clock_before': self._clock.snapshot(), 'decision_authentication_performed': False}
            intent_sha = ss.publish(prefix.with_suffix('.intent.json'), intent)
            returned = self._branch.commit_plan(plan)
            require(same(plan, raw_plan) and returned == plan_sha and ss.digest(self._env.plan) == plan_sha
                    and len(self._env.trace) == index + 1 and same(self._env.trace[index].get('plan'), raw_plan)
                    and self._env.trace[index].get('kind') == 'plan_committed'
                    and self._env.trace[index].get('time') == now
                    and type(self._env.trace[index].get('seq')) is int
                    and self._env.trace[index]['seq'] == index, 'exact commit result/trace differs')
            self._commits += 1  # The physical commit already happened; never repeat on I/O failure.
            self._clock.committed(now, mode)
            self._check_physics()
            self._fence()
            ss.read_bytes(ref['path'], ref['sha256'], retain=False)
            receipt = {'schema': SCHEMA + '-commit-receipt', 'intent_sha256': intent_sha,
                'trace_event_index': index, 'plan_sha256': plan_sha, 'executor_result': returned,
                'clock_after': self._clock.snapshot(), 'mode_at_commit': mode,
                'physical_commit_observed': True, 'arm_attribution_certified': False}
            receipt_sha = ss.publish(prefix.with_suffix('.receipt.json'), receipt)
            return {**receipt, 'receipt_sha256': receipt_sha}
        except BaseException as exc:
            self._poison(exc)
            raise

    def advance_to_boundary(self):
        self._live()
        require(self._commits > 0, 'first explicit commit required before advance')
        try:
            now = self._env.t
            target = self._clock.advance_target(now)
            require(target == self._branch.next_period_boundary(), 'branch and host absolute boundaries differ')
            self._fence()
            folder = self._directory / 'context_advances'
            folder.mkdir(exist_ok=True)
            prefix = folder / f'{self._advances:06d}'
            intent_sha = ss.publish(prefix.with_suffix('.intent.json'), {'schema': SCHEMA + '-advance-intent',
                'start_time': now, 'advance_target': target, 'clock': self._clock.snapshot()})
            stop = self._branch.advance_plan(target)
            self._advances += 1
            self._check_physics()
            observed_stop_time = self._env.t
            require(type(stop) is dict and ss.number(observed_stop_time) and now <= observed_stop_time <= target,
                    'executor stop differs from physical time/boundary')
            if 'time' in stop:
                require(ss.number(stop['time']) and stop['time'] == observed_stop_time,
                        'explicit executor stop time differs from observed physical time')
                stop_time_source = 'original_executor_time_checked_against_environment'
            else:
                # These are the only original environment stops without time.
                # Preserve their exact object; the observed clock is separate.
                require(set(stop) == {'reason', 'task'}
                        and stop['reason'] in ('plan_invalidated', 'expired_task')
                        and type(stop['task']) is str and type(self._env.plan) is dict
                        and sum(same(task.get('id'), stop['task']) for task in self._env.plan['tasks']) == 1,
                        'unrecognized untimed executor stop or current plan task identity')
                stop_time_source = 'observed_environment_for_known_untimed_executor_stop'
            self._fence()
            receipt = {'schema': SCHEMA + '-advance-receipt', 'intent_sha256': intent_sha,
                'start_time': now, 'advance_target': target, 'stop': deepcopy(stop),
                'observed_stop_time': observed_stop_time, 'stop_time_source': stop_time_source,
                'clock': self._clock.snapshot()}
            sha = ss.publish(prefix.with_suffix('.receipt.json'), receipt)
            return {**receipt, 'receipt_sha256': sha}
        except BaseException as exc:
            self._poison(exc)
            raise

    def write_checkpoint(self, new_path):
        """Allowed for stopped poisoned diagnosis; never authorizes further execution."""
        path = _absolute(str(new_path))
        require(path.is_relative_to(self._directory) and not path.exists(), 'new checkpoint inside own run required')
        require(self._env.active_task is None, 'cannot checkpoint an active dispatch')
        try:
            self._check_physics()
            state_sha = stream_snapshot.write_snapshot(self._env, path)
            require(ss.sha_string(state_sha), 'snapshot writer did not return original state SHA')
            _, file_receipt = ss.read_bytes(path, retain=False)
            return {'path': str(path), **file_receipt, 'state_sha256': state_sha,
                'context_poisoned': self._poisoned or self._branch._poisoned,
                'clock': self._clock.snapshot(), 'execution_resume_authorized': False}
        except BaseException as exc:
            self._poison(exc)
            raise

    def evidence(self):
        return {'schema': SCHEMA + '-evidence', 'binding': deepcopy(self._binding),
            'references': deepcopy(self._refs), 'restore_receipt': self._branch.receipt,
            'clock': self._clock.snapshot(), 'commits_observed': self._commits,
            'advances_observed': self._advances, 'poisoned': self._poisoned or self._branch._poisoned,
            'ledger_admission_verified': False, 'arm_attribution_certified': False,
            'execution_resume_authorized': False}


def open_shared_run(package_dir, *, expected_manifest_sha256, branch_binding_path,
                    expected_binding_sha256, output_dir, expected_source_sha256):
    """Validate external file identities, then restore once; never register a run."""
    require(ss.sha_string(expected_manifest_sha256) and ss.sha_string(expected_source_sha256),
            'external original manifest/source SHA required')
    package, output = _absolute(str(package_dir)), _absolute(str(output_dir))
    require(not output.exists() and not output.is_relative_to(package)
            and not package.is_relative_to(output), 'new independent output directory required')
    binding_ref = _ref(branch_binding_path, expected_binding_sha256)
    binding, _ = ss.read_json(binding_ref['path'], binding_ref['sha256'])
    manifest = ss.read_shared_start(package, expected_manifest_sha256=expected_manifest_sha256)
    _binding(binding, manifest, package=package, output=output,
             manifest_sha=expected_manifest_sha256, source_sha=expected_source_sha256)
    registration_ref = _ref(binding['registration_path'], binding['registration_document_sha256'])
    registration, _ = ss.read_json(registration_ref['path'], registration_ref['sha256'])
    _registration(binding, registration, manifest['contract']['seed'])
    refs = [binding_ref, registration_ref,
            _ref(package / 'manifest.json', expected_manifest_sha256)]
    branch = None
    try:
        branch = ss.restore_shared_start(package, expected_manifest_sha256=expected_manifest_sha256,
            branch_dir=output, branch_identity={'arm': binding['arm'], 'run_id': binding['run_name'],
                'registration_sha256': binding['registration_document_sha256']})
        context = SharedRunContext(branch, binding, refs)
        receipt = branch.receipt
        require(receipt['package_manifest_sha256'] == expected_manifest_sha256
                and receipt['original_state_sha256'] == binding['state_sha256']
                and receipt['snapshot_sha256'] == binding['snapshot_sha256']
                and receipt['branch_identity'] == {'arm': binding['arm'], 'run_id': binding['run_name'],
                    'registration_sha256': binding['registration_document_sha256']}
                and context._env.seed == manifest['contract']['seed']
                and same(receipt['evaluation_window'], binding['evaluation']), 'restore receipt differs')
        problem = context.problem()
        require(ss.digest(problem) == receipt['first_public_problem_sha256'], 'first public problem differs')
        context._fence()
        binding_copy_sha = ss.publish(output / 'shared_branch_binding.json', binding)
        problem_file_sha = ss.publish(output / 'first_public_problem.json', problem)
        open_sha = ss.publish(output / 'context_open.json', {'schema': SCHEMA + '-open',
            'binding_sha256': expected_binding_sha256, 'registration_document_sha256': registration_ref['sha256'],
            'source_sha256': expected_source_sha256, 'restore_receipt_sha256': receipt['receipt_sha256'],
            'first_problem_sha256': ss.digest(problem), 'clock': context._clock.snapshot(),
            'registration_file_consistency_checked': True, 'ledger_admission_verified': False,
            'metrics_window': deepcopy(binding['evaluation']), 'physical_observation_start_unchanged': True})
        context._refs.extend([_ref(output / 'start_receipt.json', receipt['receipt_sha256']),
            _ref(output / 'shared_branch_binding.json', binding_copy_sha),
            _ref(output / 'first_public_problem.json', problem_file_sha),
            _ref(output / 'context_open.json', open_sha)])
        context._fence()
        return context
    except BaseException as exc:
        if branch is not None:
            branch._poisoned = True
            ss._failure(output, exc)
        raise
