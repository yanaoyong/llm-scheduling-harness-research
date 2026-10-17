"""Standalone streaming equivalent of audit.py::audit_opportunity_coverage.

Only immutable JSONL storage and independent opportunity replay are checked.
Neither physical values, event-sequence validity, snapshot-prefix validity nor a
terminal/full-window boundary is certified by this reference contract. Existing
consumers are unchanged. Historical indexes live in ephemeral SQLite; the full
report is published create-new with an embedded verified complete-read receipt.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import asdict
import hashlib
from itertools import chain
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile

from .trace_source import TraceSeal, inspect_jsonl, open_verified

VERSION = "smt-fullfab-stream-opportunity-audit-v1"
REFERENCE_VERSION = "smt-fullfab-opportunity-audit-v2"


def _number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _key(value):
    """Exact Python equality keys for JSON scalars and identity tuples.

    Integer 1 and string '1' stay distinct; bool/int/equal-float alias exactly as
    in the reference dictionaries/sets. Invalid lists/dicts retain their original
    unhashable-type exception instead of being coerced into an admissible key.
    """
    hash(value)
    if isinstance(value, tuple):
        return 't:' + json.dumps([_key(item) for item in value], separators=(',', ':'))
    if isinstance(value, str):
        return 's:' + json.dumps(value)
    if value is None:
        return 'null'
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return 'n:' + repr(value)
        numerator, denominator = value.as_integer_ratio()
        return f'n:{numerator}/{denominator}'
    raise TypeError('unsupported non-JSON identity')


class _DiskSet:
    def __init__(self, db, name):
        self.db, self.name = db, name

    def __contains__(self, value):
        return self.db.execute('SELECT 1 FROM identities WHERE name=? AND key=?',
                               (self.name, _key(value))).fetchone() is not None

    def add(self, value):
        self.db.execute('INSERT OR IGNORE INTO identities(name,key) VALUES(?,?)',
                        (self.name, _key(value)))

    def update(self, values):
        # Keep reference set.update partial-state behavior when a later identity
        # is malformed; do not turn this into an all-or-nothing bulk operation.
        for value in values:
            self.add(value)

    def __len__(self):
        return self.db.execute('SELECT count(*) FROM identities WHERE name=?',
                               (self.name,)).fetchone()[0]

    def difference_count(self, other):
        return self.db.execute('SELECT count(*) FROM identities AS a WHERE a.name=? '
                               'AND NOT EXISTS(SELECT 1 FROM identities AS b '
                               'WHERE b.name=? AND b.key=a.key)',
                               (self.name, other.name)).fetchone()[0]


class _Jobs:
    """Never discard old jobs: later downtime may still reference them."""
    def __init__(self, db):
        self.db = db

    def __getitem__(self, jid):
        row = self.db.execute('SELECT payload FROM jobs WHERE key=?', (_key(jid),)).fetchone()
        if row is None:
            raise KeyError(jid)
        return json.loads(row[0])

    def __setitem__(self, jid, value):
        self.db.execute('INSERT INTO jobs(key,payload) VALUES(?,?) '
                        'ON CONFLICT(key) DO UPDATE SET payload=excluded.payload',
                        (_key(jid), json.dumps(value, separators=(',', ':'))))


class _MachineJobs:
    """Disk memberships plus current production-slot sets in reference order.

    Keep the actual production set objects, not repeated JSON-to-set rebuilds:
    reconstructing a set can change collision iteration order and which malformed
    job raises first. Production sets are filtered exactly as in reference;
    virtual-resource history is never cached/materialized by opportunity replay.
    Pruning removes only those memberships the reference removes at the observed
    previous time; the corresponding job rows are always retained.
    """
    def __init__(self, db, production=()):
        self.db, self.production = db, production
        self.current = {}

    def __getitem__(self, mid):
        if mid in self.production:
            return self.current.setdefault(mid, set())
        return {json.loads(row[0]) for row in self.db.execute(
            'SELECT payload FROM machine_jobs WHERE machine=? ORDER BY ordinal', (_key(mid),))}

    def __setitem__(self, mid, values):
        key = _key(mid)
        self.db.execute('DELETE FROM machine_jobs WHERE machine=?', (key,))
        for jid in values:
            self._store(mid, jid)
        if mid in self.production:
            self.current[mid] = values

    def add(self, mid, jid):
        if mid in self.production:
            self.current.setdefault(mid, set()).add(jid)
        self._store(mid, jid)

    def _store(self, mid, jid):
        self.db.execute('INSERT OR IGNORE INTO machine_jobs(machine,job,payload) VALUES(?,?,?)',
                        (_key(mid), _key(jid), json.dumps(jid, separators=(',', ':'))))


def _replay(reader, db):
    first = next(reader, None)
    if first is None or first.event.get("kind") != "initial":
        for _ in reader:
            pass
        return {"valid": False, "errors": ["opportunity replay missing initial manifest"]}
    manifest = first.event["manifest"]
    machines = {m["id"]: m for m in manifest["machines"]}
    production = {mid for mid, m in machines.items() if m["group"] != "Delay_32"}
    production_families = {machines[mid]["family"] for mid in production}
    lots = {lot["id"]: dict(lot, dedication={}) for lot in manifest["lots"]}
    waiting, ready = defaultdict(set), {}
    ms = {mid: {"ready": 0, "down": 0, "setup": "", "min_left": 0, "min_setup": ""} for mid in machines}
    jobs, machine_jobs = _Jobs(db), _MachineJobs(db, production)
    pending, plan, holds = defaultdict(list), None, {}
    executed_tasks = _DiskSet(db, "executed")
    errors, family = [], defaultdict(Counter)
    advances, advance_seconds, intervals_checked, maximum_combinations = 0, 0.0, 0, 0
    permitted_until, previous = first.event["time"], first.event["time"]
    ever_ready_ops, ever_planned_ops = _DiskSet(db, "ready"), _DiskSet(db, "planned")
    completed_lots = _DiskSet(db, "completed")
    unplanned_since, unplanned_wait = {}, 0.0

    def check(ok, message):
        if not ok and len(errors) < 200:
            errors.append(message)

    def step_for(lid, step):
        return manifest["routes"][lots[lid]["route"]][step - 1]

    def planned_ops():
        return {identity for tasks in pending.values() for task in tasks
                for identity in zip(task["lot_ids"], task["steps"], task["visits"])}

    def hold_until(mid, t):
        active_holds = [hold["until"] for hold in holds.get(mid, []) if hold.get("after_task_id") is None or
                        ((plan["version"], hold["after_task_id"]) in executed_tasks and not pending[mid])]
        return max(active_holds, default=t)

    def sync_unplanned(t):
        nonlocal unplanned_wait
        covered = planned_ops()
        active = {(lid, value["step"], value["visit"]) for lid, value in ready.items()
                  if value["family"] in production_families}
        needed = active - covered
        for identity in list(unplanned_since):
            if identity not in needed:
                unplanned_wait += max(0, t - unplanned_since.pop(identity))
        for identity in needed:
            unplanned_since.setdefault(identity, t)

    def candidates(mid, t):
        m, state = machines[mid], ms[mid]
        # Discard physically freed slots at the current observed event time;
        # hypothetical later boundaries must not mutate the replay into future.
        machine_jobs[mid] = {jid for jid in machine_jobs[mid] if jobs[jid]["process_end"] > previous}
        if max(state["ready"], state["down"]) > t:
            return {}, 0, 0
        if sum(jobs[jid]["process_end"] > t for jid in machine_jobs[mid]) >= (2 if m["cascading"] else 1):
            return {}, 0, 0
        groups = defaultdict(list)
        for lid in waiting[m["family"]]:
            value = ready[lid]
            s = step_for(lid, value["step"])
            if lots[lid]["dedication"].get(str(value["step"]), mid) != mid:
                continue
            if state["min_left"] > 0 and state["min_setup"] != s["setup"]:
                continue
            groups[(lots[lid]["part"], s["step"], s["name"])].append(lid)
        count = sum(len(g) for g in groups.values())
        combinations = 0
        for group in groups.values():
            s = step_for(group[0], ready[group[0]]["step"])
            combinations += sum(math.comb(len(group), size) for size in range(s["batch_min"], min(s["batch_max"], len(group)) + 1))
        return groups, count, combinations

    def dispatch_opportunity(mid, t):
        nonlocal maximum_combinations
        groups, count, combinations = candidates(mid, t)
        stats = family[machines[mid]["family"]]
        stats["actual_dispatch_checks"] += 1
        stats["candidate_lot_memberships_at_dispatch"] += count
        stats["legal_machine_batch_combinations_at_dispatch"] += combinations
        stats["singleton_immediate_dispatches"] += combinations == 1
        stats["multiple_choice_immediate_dispatches"] += combinations > 1
        maximum_combinations = max(maximum_combinations, combinations)
        processing, setups = set(), set()
        for group in groups.values():
            s = step_for(group[0], ready[group[0]]["step"])
            if len(group) < s["batch_min"]:
                continue
            d = s["processing"]
            processing.add(d.get("c", d.get("m", d.get("mean"))) + machines[mid]["load"] + machines[mid]["unload"])
            setup = 0
            if s["setup"] and s["setup"] != ms[mid]["setup"]:
                setup = s["setup_time"]
                if setup is None:
                    table = {(x["old"], x["new"]): x["seconds"] for x in manifest["setups"]}
                    setup = table.get((ms[mid]["setup"], s["setup"]), table.get(("", s["setup"]), 0))
            setups.add(setup)
        stats["dispatch_checks_with_processing_variation"] += len(processing) > 1
        stats["dispatch_checks_with_setup_variation"] += len(setups) > 1
        stats["dispatch_checks_with_nonzero_setup_option"] += any(x > 0 for x in setups)
        check(combinations > 0, f"time {t}: production dispatch on machine {mid} had no independent legal batch")

    for record in chain((first,), reader):
        index, event = record.event_index, record.event
        if index % 256 == 0:
            db.commit()
        try:
            t, kind = event["time"], event["kind"]
            check(t >= previous, f"{index}: opportunity time reversed")
            if t > previous:
                check(t <= permitted_until + 1e-6, f"{index}: clock changed without declared time_advance coverage")
            previous = t
            if kind == "ready":
                lid = event["lot"]
                s = step_for(lid, event["step"])
                ready[lid] = {"step": event["step"], "visit": event["visit"], "family": s["family"], "since": t}
                waiting[s["family"]].add(lid)
                if s["family"] in production_families:
                    ever_ready_ops.add((lid, event["step"], event["visit"]))
                sync_unplanned(t)
            elif kind == "plan_committed":
                plan = event["plan"]
                pending = defaultdict(list)
                for task in plan["tasks"]:
                    pending[task["machine"]].append(task)
                    ever_planned_ops.update(zip(task["lot_ids"], task["steps"], task["visits"]))
                    for lid, step in zip(task["lot_ids"], task["steps"]):
                        check(lots[lid]["dedication"].get(str(step), task["machine"]) == task["machine"],
                              f"{index}: plan violates independently reconstructed historical binding")
                holds = defaultdict(list)
                for hold in plan.get("holds", []):
                    holds[hold["machine"]].append(hold)
                sync_unplanned(t)
            elif kind == "dispatch":
                mid, jid = event["machine"], event["job"]
                if mid in production:
                    dispatch_opportunity(mid, t)
                    pending[mid] = [task for task in pending[mid] if task["id"] != event.get("plan_task_id")]
                    executed_tasks.add((event.get("plan_version"), event.get("plan_task_id")))
                s = step_for(event["lots"][0], event["steps"][0])
                if event["setup_seconds"] > 0 and s["setup"] in manifest["min_runs"] and ms[mid]["min_left"] == 0:
                    ms[mid]["min_left"] = manifest["min_runs"][s["setup"]]
                    ms[mid]["min_setup"] = s["setup"]
                ms[mid]["min_left"] = max(0, ms[mid]["min_left"] - len(event["lots"]))
                ms[mid].update(ready=event["machine_ready"], setup=event["setup_after"])
                jobs[jid] = {"process_end": event["process_end"], "machine": mid}
                machine_jobs.add(mid, jid)
                for lid, step in zip(event["lots"], event["steps"]):
                    value = ready.pop(lid)
                    waiting[value["family"]].remove(lid)
                    dedicated = step_for(lid, step)["dedicate_for"]
                    if dedicated is not None:
                        lots[lid]["dedication"][str(dedicated)] = mid
                sync_unplanned(t)
            elif kind == "downtime":
                mid = event["machine"]
                ms[mid].update(ready=event["machine_ready"], down=event["blocked_until"], setup="")
                for jid in event["affected_jobs"]:
                    job = jobs[jid]
                    job["process_end"] += event["duration"]
                    jobs[jid] = job
            elif kind == "coverage_gap":
                expected = []
                for mid in sorted(production):
                    active = plan is not None and t <= plan["valid_until"]
                    if active and (pending[mid] or hold_until(mid, t) > t):
                        continue
                    _, count, combinations = candidates(mid, t)
                    if combinations:
                        expected.append({"machine": mid, "family": machines[mid]["family"], "candidate_count": count})
                check(event.get("machines") == expected, f"{index}: reported coverage gap differs from independently reconstructed legal demand")
                db.execute("INSERT INTO gaps(event_index,payload) VALUES(?,?)",
                           (index, json.dumps({"time": t, "independent_machine_count": len(expected)},
                                              separators=(",", ":"))))
            elif kind == "time_advance":
                target = event["to"]
                check(_number(target) and t < target <= manifest["horizon"], f"{index}: invalid time_advance target")
                check(t >= permitted_until - 1e-6, f"{index}: overlapping or unfinished time_advance interval")
                permitted_until = target
                advances += 1
                advance_seconds += target - t
                boundaries = {t}
                # A fabricated large jump must not skip machine release, slot
                # release, task start condition, plan expiry, or hold expiry.
                for mid in production:
                    boundaries.update(x for x in (ms[mid]["ready"], ms[mid]["down"], hold_until(mid, t)) if t < x < target)
                    boundaries.update(jobs[jid]["process_end"] for jid in machine_jobs[mid] if t < jobs[jid]["process_end"] < target)
                    # Only the submitted head task may execute. Crossing its
                    # not_before can make it executable without a physical event.
                    if pending[mid] and t < pending[mid][0]["not_before"] < target:
                        boundaries.add(pending[mid][0]["not_before"])
                if plan and t < plan["valid_until"] < target:
                    boundaries.add(plan["valid_until"])
                for at in sorted(boundaries):
                    intervals_checked += 1
                    for mid in sorted(production):
                        groups, count, combinations = candidates(mid, at)
                        stats = family[machines[mid]["family"]]
                        stats["clock_boundary_machine_checks"] += 1
                        if not combinations:
                            continue
                        stats["legal_demand_clock_checks"] += 1
                        active = plan is not None and at < plan["valid_until"]
                        planned = active and bool(pending[mid])
                        held = active and hold_until(mid, at) > at
                        stats["explicit_pending_task_clock_checks"] += bool(planned)
                        stats["explicit_hold_clock_checks"] += bool(held)
                        check(planned or held,
                              f"{index}: unplanned legal demand on machine {mid} at {at} while advancing to {target}; candidates={count}, combinations={combinations}")
                        if planned and not held:
                            task = pending[mid][0]
                            eligible_lots = {lid for group in groups.values() for lid in group}
                            exact_ready = all(lid in ready and ready[lid]["step"] == step and ready[lid]["visit"] == visit
                                              for lid, step, visit in zip(task["lot_ids"], task["steps"], task["visits"]))
                            executable = exact_ready and set(task["lot_ids"]) <= eligible_lots and task["not_before"] <= at
                            check(not executable, f"{index}: executable submitted task {task['id']} on machine {mid} not run before clock advance at {at}")
                            obsolete = any(lid in completed_lots or
                                           (lid in ready and (ready[lid]["step"] > step or
                                            (ready[lid]["step"] == step and ready[lid]["visit"] > visit)))
                                           for lid, step, visit in zip(task["lot_ids"], task["steps"], task["visits"]))
                            check(not obsolete, f"{index}: obsolete pending task masks uncovered legal demand on machine {mid}")
            elif kind == "lot_complete":
                completed_lots.add(event["lot"])
            elif kind == "terminal":
                check(t <= permitted_until + 1e-6, f"{index}: terminal without complete clock advance declaration")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            check(False, f"{index}: malformed opportunity evidence: {exc}")
    end = event["time"]
    unplanned_wait += sum(max(0, end - since) for since in unplanned_since.values())
    current = {(lid, value["step"], value["visit"]) for lid, value in ready.items() if value["family"] in production_families}
    for name in sorted(production_families):
        family[name]["production_machine_count"] = sum(machines[mid]["family"] == name for mid in production)
    return {"valid": not errors, "errors": errors, "audit_version": VERSION,
            "time_advance_events": advances, "automatic_simulation_advance_seconds": advance_seconds,
            "clock_boundary_sweeps": intervals_checked,
            "physical_event_values_require_independent_replay": True,
            "unreported_uncovered_legal_demand_absent": not errors,
            "family_opportunities": {name: dict(stats) for name, stats in sorted(family.items())},
            "max_immediate_machine_batch_combinations_at_dispatch": maximum_combinations,
            "reported_coverage_gaps_rechecked": None,
            "production_ready_operation_visits": len(ever_ready_ops),
            "ready_operation_visits_never_in_any_plan": ever_ready_ops.difference_count(ever_planned_ops),
            "terminal_ready_operation_visits_never_in_any_plan": sum(identity not in ever_planned_ops for identity in current),
            "terminal_ready_unplanned_operation_visits": (list(identity) for identity in sorted(unplanned_since)),
            "ready_wait_without_current_plan_lot_seconds": unplanned_wait,
            "max_terminal_unplanned_ready_seconds": max((end - since for since in unplanned_since.values()), default=0),
            "count_interpretation": "dispatch-time legal choices and clock-boundary sweeps are descriptive repeated observations, not independent statistical samples or model decisions"}


class _HashingTextWriter:
    """Encode once and hash exactly the bytes written to the private report."""
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()

    def write(self, text):
        data = text.encode('utf-8')
        if self.stream.write(data) != len(data):
            raise OSError('short report write')
        self.digest.update(data)
        return len(text)


def _write_report(path, result, db):
    """Create-new publish and return the hash of the bytes we actually wrote.

    Do not reopen the published path to construct its evidence: another writer
    could replace it in that interval. As with any saved content address, callers
    must compare this hash before trusting later reads of report_path.
    """
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.partial', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as binary:
            stream = _HashingTextWriter(binary)
            stream.write('{')
            for number, (key, value) in enumerate(result.items()):
                if number:
                    stream.write(',')
                stream.write(json.dumps(key) + ':')
                if key == 'reported_coverage_gaps_rechecked':
                    stream.write('[')
                    for gap_index, (payload,) in enumerate(db.execute('SELECT payload FROM gaps ORDER BY event_index')):
                        if gap_index:
                            stream.write(',')
                        stream.write(payload)
                    stream.write(']')
                elif key == 'terminal_ready_unplanned_operation_visits':
                    stream.write('[')
                    for item_index, item in enumerate(value):
                        if item_index:
                            stream.write(',')
                        json.dump(item, stream, separators=(',', ':'))
                    stream.write(']')
                else:
                    json.dump(value, stream, separators=(',', ':'))
            stream.write('}\n')
            binary.flush()
            os.fsync(binary.fileno())
            report_sha256 = stream.digest.hexdigest()
        # link() is atomic create-new on the same filesystem; unlike replace(),
        # it cannot overwrite an existing report even if a race creates one.
        os.link(temporary, path)
        return report_sha256
    finally:
        Path(temporary).unlink(missing_ok=True)


def audit_opportunity_coverage(source, *, report_path, work_dir=None):
    """Verify an entire source and persist the complete opportunity-only report.

    This preserves the reference treatment of nonterminal prefixes and ignored
    event kinds: valid is not a sequence/snapshot/terminal/physical certificate.
    The manifest, current lots/dedications, ready/waiting, pending/holds and current
    production-slot ID sets remain in RAM. Invalid evidence can overfill the slot
    sets; no constant-memory claim is made for arbitrary corrupt traces. Virtual
    machine history, all jobs and historical identities remain on disk. SQLite
    history and raw output still grow; this does not establish long-window readiness.

    Input mutation, incomplete reads and pre-publication storage errors raise
    without a report. Errors after atomic publication can leave a complete report
    with its source receipt embedded, even if no descriptor was returned. Later
    readers must verify report_sha256 against the bytes they actually consume.
    """
    output = Path(report_path).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    seal = source if isinstance(source, TraceSeal) else inspect_jsonl(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='smt-opportunity-audit-', dir=work_dir) as temporary:
        with closing(sqlite3.connect(str(Path(temporary) / 'index.sqlite'))) as db:
            db.execute('PRAGMA cache_size=-2048')
            db.execute('PRAGMA temp_store=FILE')
            db.executescript(
                'CREATE TABLE identities(name TEXT,key TEXT,PRIMARY KEY(name,key));'
                'CREATE TABLE jobs(key TEXT PRIMARY KEY,payload TEXT NOT NULL);'
                'CREATE TABLE machine_jobs(ordinal INTEGER PRIMARY KEY,machine TEXT,job TEXT,payload TEXT NOT NULL,'
                'UNIQUE(machine,job));'
                'CREATE TABLE gaps(event_index INTEGER PRIMARY KEY,payload TEXT NOT NULL);')
            with open_verified(seal) as reader:
                result = _replay(reader, db)
            db.commit()
            evidence = {
                'implementation_version': VERSION,
                'reference_contract_version': REFERENCE_VERSION,
                'reference_function': 'src.smt_fullfab.audit.audit_opportunity_coverage',
                'source_receipt': asdict(reader.receipt),
                'complete_jsonl_pass': True,
                'event_sequence_certified': False,
                'snapshot_prefix_certified': False,
                'terminal_boundary_certified': False,
                'complete_physical_window_certified': False,
                'physical_audit_performed': False,
                'plan_source_audit_performed': False,
                'physical_event_values_require_independent_replay': True}
            result['_source_evidence'] = evidence
            report_sha256 = _write_report(output, result, db)
    return {**evidence, 'report_path': str(output), 'report_sha256': report_sha256,
            'valid': result['valid'], 'errors': result['errors'],
            'unreported_uncovered_legal_demand_absent': result.get('unreported_uncovered_legal_demand_absent', False)}
