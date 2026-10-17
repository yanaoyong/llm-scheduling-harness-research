"""Three-layer additive metrics, split exactly at simulated-hour boundaries."""
from copy import deepcopy
import math


class Metrics:
    def __init__(self, origin=0, *, exclude_first_hours=0, cached_input_weight=0.1):
        if exclude_first_hours < 0 or not 0 <= cached_input_weight <= 1:
            raise ValueError('invalid registered metric settings')
        self.origin = origin
        self.exclude_first_hours = exclude_first_hours
        self.cached_input_weight = cached_input_weight
        self.buckets = {}

    def _hour(self, time):
        if time < self.origin:
            raise ValueError('time before origin')
        return math.floor((time - self.origin) / 3600)

    def add(self, time, **values):
        bucket = self.buckets.setdefault(self._hour(time), {})
        for key, value in values.items():
            if not math.isfinite(value):
                raise ValueError('nonfinite metric')
            bucket[key] = bucket.get(key, 0) + value

    def integrate(self, start, end, **gauges):
        if end < start:
            raise ValueError('backwards interval')
        while start < end:
            boundary = self.origin + (self._hour(start) + 1) * 3600
            stop = min(end, boundary)
            self.add(start, simulated_seconds=stop-start,
                     **{k + '_seconds': v * (stop-start) for k, v in gauges.items()})
            start = stop

    def production(self, time, *, throughput=0, tardiness=0, weight=1, queue_wait=0, setups=0):
        self.add(time, throughput=throughput, tardiness=tardiness,
                 weighted_tardiness=tardiness*weight, queue_wait=queue_wait, setups=setups)

    def execution(self, time, *, start_offset=0, starts=0, machine_changes=0, compared_assignments=0, invalid_tasks=0):
        self.add(time, start_offset=start_offset, starts=starts, machine_changes=machine_changes,
                 compared_assignments=compared_assignments, invalid_tasks=invalid_tasks)

    def session(self, time, *, tool_calls=0, tool_rounds=0, input_tokens=0, cached_tokens=0,
                output_tokens=0, model_seconds=0, wall_seconds=0, failed=False, usage_known=True,
                submit_attempts=0, submit_rejections=0):
        if not 0 <= cached_tokens <= input_tokens:
            raise ValueError('cached tokens must be part of input')
        if min(tool_calls, tool_rounds, input_tokens, output_tokens, model_seconds, wall_seconds,
               submit_attempts, submit_rejections) < 0 or submit_rejections > submit_attempts:
            raise ValueError('invalid usage counters')
        self.add(time, sessions=1, tool_calls=tool_calls, model_request_lower_bound=tool_rounds+1,
                 input_tokens=input_tokens, cached_tokens=cached_tokens, output_tokens=output_tokens,
                 uncached_equivalent_input_tokens=input_tokens-cached_tokens+self.cached_input_weight*cached_tokens,
                 model_seconds=model_seconds, wall_seconds=wall_seconds, failures=int(failed),
                 unknown_usage=int(not usage_known), submit_attempts=submit_attempts, submit_rejections=submit_rejections)

    @staticmethod
    def derived(bucket):
        row = deepcopy(bucket)
        def ratio(num, den):
            return row.get(num, 0) / row[den] if row.get(den, 0) else 0
        row['machine_change_ratio'] = ratio('machine_changes', 'compared_assignments')
        row['mean_start_offset'] = ratio('start_offset', 'starts')
        row['input_per_request'] = ratio('input_tokens', 'model_request_lower_bound')
        row['requests'] = row.get('model_request_lower_bound', 0)
        row['submit_rejection_rate'] = ratio('submit_rejections', 'submit_attempts')
        row['avoidable_idle'] = ratio('avoidable_idle_seconds', 'simulated_seconds')
        hours = row.get('simulated_seconds', 0) / 3600
        for key in ('uncached_equivalent_input_tokens', 'model_request_lower_bound'):
            row[key + '_per_sim_hour'] = row.get(key, 0) / hours if hours else None
        return row

    def report(self, *, steady_only=False):
        return {hour: self.derived(row) for hour, row in sorted(self.buckets.items())
                if not steady_only or hour >= self.exclude_first_hours}

    def capture(self):
        return deepcopy(vars(self))

    @classmethod
    def restore(cls, state):
        obj = cls()
        obj.__dict__.update(deepcopy(state))
        obj.buckets = {int(k): v for k, v in obj.buckets.items()}
        return obj
