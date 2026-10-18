"""Pure anchor/interrupt state machine. No planner, I/O, or physical imports."""
from dataclasses import asdict, dataclass
import math


def next_anchor(now, origin, delta):
    return origin + (math.floor((now - origin) / delta) + 1) * delta


@dataclass(frozen=True)
class CycleConfig:
    stage: str = 'S0'
    delta: float = 60
    horizon: float | None = None
    breakdowns: bool = False
    k_fail: int = 2
    stall_cycles: int = 4
    unknown_usage_cap: int = 2
    segment_seconds: float = 3600
    segment_cycles: int = 60
    cost_cap: float | None = None
    hourly_cost_cap: float | None = None

    trigger: str = 'periodic'
    interaction: str = 'mcp_session'
    delta_min: float = 60

    def __post_init__(self):
        if self.trigger not in ('event', 'periodic') or self.interaction not in ('single_action', 'mcp_session'):
            raise ValueError('unknown experiment mode')
        if self.horizon is None:
            object.__setattr__(self, 'horizon', max(3 * self.delta, 900))
        if self.stage not in ('S0', 'S1', 'S2', 'S3', 'S4'):
            raise ValueError('unknown stage')
        for key in ('delta_min', 'delta', 'horizon', 'segment_seconds', 'segment_cycles', 'k_fail', 'stall_cycles', 'unknown_usage_cap'):
            value = getattr(self, key)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(key + ' must be positive and finite')
        for key in ('k_fail', 'stall_cycles', 'unknown_usage_cap', 'segment_cycles'):
            if type(getattr(self, key)) is not int:
                raise ValueError(key + ' must be an integer')
        for value in (self.cost_cap, self.hourly_cost_cap):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError('cost cap must be nonnegative and finite')

    @classmethod
    def for_stage(cls, stage, *, delta=None, horizon=None, **kwargs):
        # Later stages require an explicitly selected experimental period.
        if delta is None:
            if stage != 'S0':
                raise ValueError('register delta for S1–S4')
            delta = 60
        return cls(stage, delta, max(3 * delta, 900) if horizon is None else horizon,
                   **{'breakdowns': stage in ('S2', 'S3', 'S4'), **kwargs})


class CycleMachine:
    def __init__(self, origin=0, config=None):
        self.config = config or CycleConfig()
        self.origin = origin
        self.now = origin
        self.anchor = origin if self.config.trigger == 'periodic' else None
        self.cycles = self.sessions = self.empty_cycles = self.interrupts = 0
        self.failures = self.idle_streak = self.unknown_usage = 0
        self.previous_idle = None
        self.unresolved_failure = False
        self.cost = self.wall_seconds = 0.0
        self.segment = 0
        self.segment_start = origin
        self.segment_cycle_start = 0
        self.stop_reason = None
        self.inflight = None
        self.last_record = None
        self.defects = 0

    def begin(self, now, *, avoidable_idle=0, invalid_tasks=(), valid_until=None, event=None):
        if self.stop_reason:
            return {'kind': 'stopped', 'reason': self.stop_reason, 'session': False}
        if self.inflight is not None or now < self.now:
            raise ValueError('inflight cycle or backwards time')
        self.now = now
        if event == 'plan_horizon':
            self.defects += 1
            self.stop_reason = 'plan_horizon_defect'
            return {'kind': 'defect', 'reason': self.stop_reason, 'session': False}
        if event == 'breakdown':
            event = 'plan_invalidated' if self.config.breakdowns and invalid_tasks else None
            if event is None and self.anchor is not None and now < self.anchor:
                return {'kind': 'ignored', 'session': False}
        if event == 'no_plan' and (valid_until is not None and valid_until > now or avoidable_idle <= 0):
            return {'kind': 'ignored', 'session': False}
        if event is not None and event not in ('plan_invalidated', 'expired_task', 'no_plan', 'terminal'):
            raise ValueError('unsupported interrupt')
        if self.config.trigger == 'event':
            # Observe every physical event, never manufacture periodic anchors or
            # retry a failed process at the same paused simulation instant.
            if self.last_record and now == self.last_record['time'] and event != 'terminal':
                return {'kind': 'waiting', 'session': False}
            if not event and avoidable_idle <= 0 and not invalid_tasks:
                self.idle_streak = 0
                self.previous_idle = avoidable_idle
                self._boundary(now)
                return {'kind': 'waiting', 'session': False}
            self.cycles += 1
            self.sessions += 1
            self.interrupts += bool(event)
            self.inflight = {'cycle': self.cycles, 'time': now, 'kind': 'interrupt' if event else 'event',
                             'event': event, 'session': True, 'avoidable_idle': avoidable_idle,
                             'next_anchor': None, 'merged_anchor': None}
            return dict(self.inflight)
        if event is None and now < self.anchor:
            return {'kind': 'waiting', 'session': False}
        if event is None and now != self.anchor:
            raise ValueError('host skipped an anchor')
        upcoming = next_anchor(now, self.origin, self.config.delta)
        merged = upcoming if event and upcoming - now < self.config.delta / 2 else None
        self.anchor = upcoming + self.config.delta if merged is not None else upcoming
        needed = bool(event or avoidable_idle > 0 or invalid_tasks or
                      (valid_until is not None and valid_until < upcoming) or self.unresolved_failure)
        self.cycles += 1
        record = {'cycle': self.cycles, 'time': now, 'kind': 'interrupt' if event else 'anchor',
                  'event': event, 'session': needed, 'avoidable_idle': avoidable_idle,
                  'next_anchor': self.anchor, 'merged_anchor': merged}
        if needed:
            self.sessions += 1
            self.interrupts += bool(event)
            self.inflight = record
        else:
            self.empty_cycles += 1
            self.idle_streak = 0
            self.previous_idle = avoidable_idle
            self.last_record = record
            self._boundary(now)
        return dict(record)

    def finish(self, *, submitted, process_ok=True, usage_known=True, cost=0, wall_seconds=0,
               model_note=''):
        if self.inflight is None:
            raise ValueError('no active cycle')
        if cost < 0 or wall_seconds < 0 or not math.isfinite(cost + wall_seconds):
            raise ValueError('invalid usage')
        record = self.inflight
        now = record['time']
        success = bool(submitted and process_ok and usage_known)
        self.cost += cost
        self.wall_seconds += wall_seconds
        self.unknown_usage += not usage_known
        self.failures = 0 if success else self.failures + 1
        idle = record['avoidable_idle']
        self.idle_streak = (self.idle_streak + 1 if idle > 0 and not model_note.strip()
                            and (self.previous_idle is None or idle >= self.previous_idle) else 0)
        self.previous_idle = idle
        self.unresolved_failure = not success
        if self.config.trigger == 'periodic' and record['event'] and record['merged_anchor'] is None and self.anchor - now < self.config.delta / 2:
            record['merged_anchor'] = self.anchor
            self.anchor += self.config.delta
        record.update(success=success, cost=cost, wall_seconds=wall_seconds, usage_known=usage_known)
        self.now = now
        self.inflight = None
        self.last_record = record
        if self.unknown_usage >= self.config.unknown_usage_cap:
            self.stop_reason = 'unknown_usage_cap'
        elif self.failures >= self.config.k_fail:
            self.stop_reason = 'consecutive_failures'
        elif self.idle_streak >= self.config.stall_cycles:
            self.stop_reason = 'stall'
        elif record['event'] == 'terminal':
            self.stop_reason = 'terminal'
        self._boundary(now)
        return dict(record)

    def _boundary(self, now):
        boundary = (now - self.segment_start >= self.config.segment_seconds or
                    self.cycles - self.segment_cycle_start >= self.config.segment_cycles)
        if boundary:
            self.segment += 1
            self.segment_start = now
            self.segment_cycle_start = self.cycles
            caps = [self.config.cost_cap]
            if self.config.hourly_cost_cap is not None:
                caps.append(self.config.hourly_cost_cap * (now - self.origin) / 3600)
            if any(cap is not None and self.cost > cap for cap in caps):
                self.stop_reason = self.stop_reason or 'budget_cap'
        if self.last_record is not None:
            self.last_record['segment_boundary'] = boundary
        return boundary

    def capture(self):
        from copy import deepcopy
        return deepcopy({**vars(self), 'config': asdict(self.config)})

    @classmethod
    def restore(cls, state):
        from copy import deepcopy
        state = deepcopy(state)
        obj = cls(state['origin'], CycleConfig(**state.pop('config')))
        obj.__dict__.update(state)
        return obj


@dataclass(frozen=True)
class DriftRule:
    """Registered absolute hourly ceilings, consecutive bad hours, any metric."""
    limits: dict
    consecutive_hours: int = 3

    def __post_init__(self):
        allowed = {'input_per_request', 'requests', 'submit_rejection_rate', 'avoidable_idle'}
        if not self.limits or not set(self.limits) <= allowed or self.consecutive_hours < 1:
            raise ValueError('invalid registered drift rule')
        if any(not math.isfinite(v) or v < 0 for v in self.limits.values()):
            raise ValueError('invalid drift ceiling')


class DriftMonitor:
    def __init__(self, rule):
        self.rule = rule
        self.streak = 0
        self.last_hour = None

    def observe(self, hour, metrics):
        if self.last_hour is not None and hour <= self.last_hour:
            raise ValueError('hour must increase')
        if self.last_hour is not None and hour != self.last_hour + 1:
            self.streak = 0
        self.last_hour = hour
        bad = any(metrics[k] > v for k, v in self.rule.limits.items())
        self.streak = self.streak + 1 if bad else 0
        return self.streak >= self.rule.consecutive_hours
