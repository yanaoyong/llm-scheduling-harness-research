"""Static diagnostic candidate. No scheduling, replay, authentication or I/O.

The caller supplies an append-only sink and existing evidence identities. This
module certifies none of them. Time is a non-overlapping wall-time partition,
not CPU profiling. No current B runtime imports this file.
"""
from contextlib import contextmanager
from time import monotonic_ns

VERSION = "B-incremental-performance-observations-v1"
STAGES = frozenset({"transport", "replay", "validation", "io", "prompt",
                    "commit", "physical", "other"})
WORK_KEYS = frozenset({"bytes_read", "bytes_written", "events_replayed",
                       "records_validated", "historical_actions_replayed"})


def _text(value, name):
    if type(value) is not str or not value:
        raise ValueError(name + " must be a nonempty string")
    return value


def _count(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(name + " must be an exact nonnegative integer")
    return value


def _hash(value):
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("evidence_sha256 must be lowercase SHA256")
    return value


class StageTimer:
    """One process/thread; leaf spans cannot nest or overlap.

    Sink work occurs outside the measured leaf and is counted in unattributed
    wall time at the next boundary. A sink exception cannot mask an exception
    already raised by the observed code. `finish` stops its scope before the
    final sink publication; a surrounding real process wait remains necessary.
    """
    def __init__(self, emit, *, clock_ns=monotonic_ns):
        self.emit, self.clock = emit, clock_ns
        self.start_ns = _count(clock_ns(), "clock")
        self.last_ns = self.start_ns
        self.active = None
        self.serial = 0
        self.closed = False
        self.stage_ns = {name: 0 for name in sorted(STAGES)}
        self.unattributed_ns = 0

    def _now(self):
        now = _count(self.clock(), "clock")
        if now < self.last_ns:
            raise ValueError("monotonic clock moved backwards")
        self.last_ns = now
        return now

    def begin(self, stage, *, operation_id, call_id=None, reason):
        if self.closed or self.active is not None:
            raise ValueError("closed timer or overlapping leaf span")
        if stage not in STAGES:
            raise ValueError("unknown stage")
        _text(operation_id, "operation_id"); _text(reason, "reason")
        if call_id is not None:
            _text(call_id, "call_id")
        previous = self.last_ns
        now = self._now()
        self.unattributed_ns += now - previous
        self.serial += 1
        self.active = {"span_id": self.serial, "stage": stage,
                       "operation_id": operation_id, "call_id": call_id,
                       "reason": reason, "start_ns": now}
        return self.serial

    def end(self, token, *, work=None, outcome="ok", error_type=None):
        if self.active is None or type(token) is not int or token != self.active["span_id"]:
            raise ValueError("span token does not match active leaf")
        if outcome not in {"ok", "error"}:
            raise ValueError("outcome must be ok or error")
        work = {} if work is None else dict(work)
        if not set(work) <= WORK_KEYS:
            raise ValueError("unknown work counter")
        for name, value in work.items():
            _count(value, name)
        now = self._now()
        row = {**self.active, "schema": VERSION + "-span", "end_ns": now,
               "duration_ns": now - self.active["start_ns"], "work": work,
               "outcome": outcome, "error_type": error_type}
        self.stage_ns[row["stage"]] += row["duration_ns"]
        self.active = None
        self.emit(row)
        return row

    @contextmanager
    def measure(self, stage, *, operation_id, call_id=None, reason):
        token = self.begin(stage, operation_id=operation_id, call_id=call_id, reason=reason)
        work = {}
        try:
            yield work
        except BaseException as primary:
            try:
                self.end(token, work=work, outcome="error", error_type=type(primary).__name__)
            except BaseException as secondary:
                primary.add_note("diagnostic timer close failed: " + type(secondary).__name__)
            raise
        else:
            self.end(token, work=work)

    def finish(self):
        if self.closed or self.active is not None:
            raise ValueError("cannot finish twice or with an active leaf")
        previous = self.last_ns
        end = self._now()
        self.unattributed_ns += end - previous
        self.closed = True
        total = end - self.start_ns
        if sum(self.stage_ns.values()) + self.unattributed_ns != total:
            raise ValueError("time partition is not complete")
        report = {"schema": VERSION + "-timing", "start_ns": self.start_ns,
                  "end_ns": end, "scope_wall_ns": total,
                  "leaf_stage_ns": dict(self.stage_ns),
                  "unattributed_ns": self.unattributed_ns,
                  "span_count": self.serial, "cpu_time_measured": False,
                  "child_reported_time_additive": False,
                  "final_sink_publication_included": False}
        self.emit(report)
        return report


class ProgressObservations:
    """Diagnostic events from already accepted producer receipts, never a gate.

    Chunk/task counts describe appearance in accepted assembly input. They are
    neither current candidate coverage nor dispatch. Task identities are scoped
    by plan/draft and counted independently of task payload size or machine count.
    A repeated task observation increments raw occurrences, not distinct IDs.
    The source verifier, not this collector, decides whether any chunk is valid.
    """
    MILESTONES = frozenset({"check_requested", "valid_check", "invalid_check",
                            "apply_requested", "durable_selection", "physical_commit"})

    def __init__(self, emit, *, start_ns, clock_ns=monotonic_ns):
        self.emit, self.clock = emit, clock_ns
        self.start_ns = _count(start_ns, "start_ns")
        self.last_ns = self.start_ns
        self.reads = set()
        self.chunks = set()
        self.task_ids = set()
        self.task_occurrences = 0
        self.first = {name: None for name in self.MILESTONES}

    def _time(self):
        now = _count(self.clock(), "clock")
        if now < self.last_ns:
            raise ValueError("monotonic clock moved backwards")
        self.last_ns = now
        return now

    def read(self, *, scope, request_sha256, content_sha256, call_id,
             evidence_sha256, reason="unknown", reason_evidence_sha256=None):
        """Record only a successful returned query, not a rejected read request.

        scope must include bootstrap/plan identity. Exact request+content forms
        the repeat key. A changed draft result is a new content read even if the
        request is byte-identical. Reasons are observations, never inferred intent.
        """
        _text(scope, "scope"); _text(call_id, "call_id"); _text(reason, "reason")
        for value in (request_sha256, content_sha256, evidence_sha256):
            _hash(value)
        if reason != "unknown" and reason_evidence_sha256 is None:
            raise ValueError("a non-unknown reason needs its original evidence hash")
        if reason_evidence_sha256 is not None:
            _hash(reason_evidence_sha256)
        key = (scope, request_sha256, content_sha256)
        row = {"schema": VERSION + "-read", "at_ns": self._time(),
               "scope": scope, "request_sha256": request_sha256,
               "content_sha256": content_sha256, "call_id": call_id,
               "evidence_sha256": evidence_sha256,
               "classification": "read_again" if key in self.reads else "new",
               "reason": reason, "reason_evidence_sha256": reason_evidence_sha256,
               "model_intent_inferred": False}
        self.reads.add(key)
        self.emit(row)
        return row

    def accepted_chunk(self, *, scope, chunk_id, sequence, task_ids, call_id,
                       evidence_sha256):
        _text(scope, "scope"); _text(chunk_id, "chunk_id"); _text(call_id, "call_id")
        _count(sequence, "sequence"); _hash(evidence_sha256)
        ids = list(task_ids)
        for value in ids:
            _text(value, "task_id")
        key = (scope, chunk_id, sequence, evidence_sha256)
        if key in self.chunks:
            raise ValueError("same accepted chunk receipt observed twice")
        self.chunks.add(key)
        before = len(self.task_ids)
        self.task_ids.update((scope, value) for value in ids)
        self.task_occurrences += len(ids)
        row = {"schema": VERSION + "-accepted-chunk", "at_ns": self._time(),
               "scope": scope, "chunk_id": chunk_id, "sequence": sequence,
               "call_id": call_id, "evidence_sha256": evidence_sha256,
               "task_occurrences": len(ids), "new_distinct_task_ids": len(self.task_ids) - before,
               "cumulative_task_occurrences": self.task_occurrences,
               "cumulative_distinct_task_ids": len(self.task_ids),
               "accepted_chunk_observations": len(self.chunks),
               "current_plan_coverage_certified": False, "physical_dispatch_certified": False}
        self.emit(row)
        return row

    def milestone(self, name, *, scope, call_id, evidence_sha256):
        if name not in self.MILESTONES:
            raise ValueError("unknown milestone")
        _text(scope, "scope"); _text(call_id, "call_id"); _hash(evidence_sha256)
        now = self._time()
        elapsed = now - self.start_ns
        if self.first[name] is None:
            self.first[name] = elapsed
        row = {"schema": VERSION + "-milestone", "name": name,
               "at_ns": now, "elapsed_ns": elapsed, "scope": scope,
               "call_id": call_id, "evidence_sha256": evidence_sha256}
        self.emit(row)
        return row

    def summary(self):
        """Read-only observation; missing milestones remain censored, never zero."""
        return {"schema": VERSION + "-progress", "accepted_chunk_observations": len(self.chunks),
                "task_occurrences": self.task_occurrences,
                "distinct_scoped_task_ids": len(self.task_ids),
                "milestones": {k: {"first_elapsed_ns": v, "censored": v is None}
                               for k, v in sorted(self.first.items())},
                "producer_receipts_authenticated_by_this_module": False,
                "current_plan_coverage_certified": False, "physical_dispatch_certified": False}
