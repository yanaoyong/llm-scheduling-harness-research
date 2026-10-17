"""Harness acceptance cases. Offline only, with real durable stores/physics.

Test-generated decisions are explicitly replay fixtures, never real B results.
"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from src.smt_fullfab.plan_delta import ORDER_POLICY, SCHEMA, anchor_hashes
from src.smt_fullfab.B_delta_assembly import SET_PATHS, ARRAY_PATHS
from src.smt_fullfab.harness.contracts import ROOT, SEMANTIC_COVERAGE, HarnessError, default_config, digest, encode
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.store import Store, InjectedCrash
from src.smt_fullfab.harness.facts import FactReader, build_facts, changes, apply_changes, reconstruct
from src.smt_fullfab.harness.evaluation import seal_evidence, audit_run, Evidence, audit_provenance, microbenchmark_gate
from src.smt_fullfab.harness.legacy import load_fragment, public_delta
from src.smt_fullfab.harness.adapters import frozen_policy_action


def at(value, path):
    for key in path:
        value = value[key]
    return value


def wait_delta(runtime, *, version="fixture-plan", tasks=None, until=None):
    context = runtime.store.read("contexts", runtime.head["context_ref"])
    tasks = tasks or []
    until = runtime.env.horizon if until is None else until
    base = context["base_plan"]
    pending = [t["id"] for t in base["tasks"] if t["id"] not in context["execution_state"]["dispatched_task_ids"]]
    by_machine = {t["machine"]: t["id"] for t in tasks}
    return {"plan_header": {"version": version, "created_at": runtime.env.t, "valid_until": until,
                             "freeze_until": runtime.env.t, "reason": "Offline explicit test choice", "scope": list(context["problem"]["scope"])},
            "order_policy": ORDER_POLICY,
            "tasks": {"keep": {"mode": "ids", "ids": []}, "cancel_ids": pending, "replace": [], "add": tasks},
            "holds": {"keep": {"mode": "ids", "ids": []}, "cancel_ids": ["h:" + str(i) for i in range(len(base["holds"]))], "replace": [],
                      "add": [{"machine": mid, "until": until, "reason": "Offline explicit wait", "after_task_id": by_machine.get(mid)} for mid in context["problem"]["scope"]]},
            "machine_orders": [{"machine": mid, "task_ids": [t["id"] for t in tasks if t["machine"] == mid]} for mid in by_machine]}


def one_task(runtime):
    # Test fixture selection only. The runtime never invokes this helper.
    context = runtime.store.read("contexts", runtime.head["context_ref"])
    op = next(o for o in context["problem"]["operations"] if o["lot_id"] == "w1387" and not o["conditional"] and o["batch_min"] == 1)
    return {"id": "fixture-w1387", "machine": op["eligible_machines"][0], "lot_ids": [op["lot_id"]],
            "steps": [op["step"]], "visits": [op["visit"]], "operation_ids": [op["operation_id"]], "not_before": runtime.env.t}


def propose(runtime, delta, request="proposal"):
    return runtime.record_output({"tool": "propose_delta", "context_ref": runtime.head["context_ref"], "request_id": request, "delta": delta})


def apply(runtime, ref, request="apply", context=None):
    return runtime.record_output({"tool": "apply_candidate", "context_ref": context or runtime.head["context_ref"], "request_id": request, "candidate_ref": ref})


def crash_at(point):
    def fault(actual):
        if actual == point:
            raise InjectedCrash(point)
    return fault


class HarnessAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = Path(tempfile.mkdtemp(prefix="harness-tests-"))
        cls.template = cls.folder / "template"
        config = default_config(seconds=1800)
        # This suite batches independent negative examples. The default limit=3
        # is tested separately with an uninterrupted repeated-error sequence.
        config["limits"]["same_error_limit"] = 10
        cls.base_config = config
        runtime = Runtime.start_new(cls.template, config, experiment_id="offline-T01-T28")
        runtime.close()

    def setUp(self):
        self.path = self.folder / self._testMethodName
        shutil.copytree(self.template, self.path)
        self.r = Runtime.resume_run(self.path)

    def tearDown(self):
        self.r.close()

    def restart(self):
        self.r.close()
        self.r = Runtime.resume_run(self.path)
        return self.r

    def test_T01_saved_raw_decision_new_tool_equivalence(self):
        fixture = load_fragment(ROOT / "runs/smt_fullfab_stage2/B_1701_1h_delta_v14__candidate_paths_001/plan_00002")
        self.r.close()
        config = default_config(seconds=3600 - fixture["initial"]["state"]["t"])
        self.path = self.folder / "saved-fragment"
        self.r = Runtime.start_new(self.path, config, experiment_id="offline-historical-equivalence", initial=fixture["initial"])
        context = self.r.store.read("contexts", self.r.head["context_ref"])
        self.assertEqual(digest(context["problem"]), digest(fixture["bootstrap"]["problem"]))
        result = propose(self.r, public_delta(fixture))
        self.assertEqual(result["status"], "candidate_checked", result)
        candidate = self.r.store.read("candidates", result["candidate_ref"])
        self.assertEqual(digest(candidate["compiled"]["plan"]), digest(fixture["old_compiled"]["plan"]))
        self.assertGreater(len(candidate["field_sources"]), 100)
        self.assertEqual(apply(self.r, result["candidate_ref"])["status"], "accepted")
        feedback = self.r.advance()
        self.assertGreater(feedback["advanced_seconds"], 0)
        self.assertGreater(feedback["dispatch_count_delta"], 0)

    def test_T02_missing_fields_atomic_rejection(self):
        task = one_task(self.r)
        for i, field in enumerate(("machine", "lot_ids", "not_before", "operation_ids")):
            bad = deepcopy(task)
            del bad[field]
            delta = wait_delta(self.r, tasks=[task])
            delta["tasks"]["add"] = [bad]
            result = propose(self.r, delta, str(i))
            self.assertEqual(result["status"], "rejected")
        delta = wait_delta(self.r, tasks=[task])
        delta["machine_orders"] = []
        self.assertEqual(propose(self.r, delta, "order")["error"]["code"], "missing_machine_order")
        self.assertEqual(self.r.head["revision"], 0)
        self.assertEqual(self.r.store.rows("candidates"), [])

    def test_T03_duplicate_operation_rejected(self):
        task = one_task(self.r)
        duplicate = {**deepcopy(task), "id": "duplicate"}
        result = propose(self.r, wait_delta(self.r, tasks=[task, duplicate]))
        self.assertEqual(result["error"]["code"], "operation_reuse")
        self.assertEqual(len(self.r.store.rows("commits")), 0)

    def test_T04_nonzero_freeze_preserved(self):
        task = one_task(self.r)
        task["not_before"] = 10
        delta = wait_delta(self.r, tasks=[task])
        delta["plan_header"]["freeze_until"] = 100
        result = propose(self.r, delta)
        self.assertEqual(apply(self.r, result["candidate_ref"])["status"], "accepted")
        self.r.observe()
        bad = wait_delta(self.r, version="delete-frozen")
        self.assertEqual(propose(self.r, bad, "bad")["error"]["code"], "frozen_horizon")
        self.assertEqual(self.r.env.plan["tasks"], [task])

    def test_T05_full_batch_and_eligibility_checked(self):
        task = one_task(self.r)
        context = self.r.store.read("contexts", self.r.head["context_ref"])
        op = next(o for o in context["problem"]["operations"] if o["operation_id"] == task["operation_ids"][0])
        bad_machine = next(m for m in context["problem"]["scope"] if m not in op["eligible_machines"])
        task["machine"] = bad_machine
        self.assertEqual(propose(self.r, wait_delta(self.r, tasks=[task]))["error"]["code"], "eligibility")
        # Cross-page compatibility/max-size coverage is additionally exercised by
        # the complete legacy compiler batch tests, never approved per page.
        self.assertEqual(self.r.head["revision"], 0)

    def test_T06_independent_apply_and_explicit_older_candidate(self):
        context = self.r.head["context_ref"]
        first = propose(self.r, wait_delta(self.r, version="first"), "p1")
        second = propose(self.r, wait_delta(self.r, version="second"), "p2")
        result = self.r.record_output({"actions": [{"tool": "propose_delta"}, {"tool": "apply_candidate"}]})
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(self.r.env.plan, None)
        self.assertEqual(apply(self.r, first["candidate_ref"], context=context)["status"], "accepted")
        self.assertEqual(self.r.env.plan["version"], "first")
        self.assertNotEqual(first["candidate_ref"], second["candidate_ref"])

    def test_T07_stale_candidate_rejected(self):
        context = self.r.head["context_ref"]
        first = propose(self.r, wait_delta(self.r), "p1")
        second = propose(self.r, wait_delta(self.r, version="second"), "p2")
        apply(self.r, first["candidate_ref"], context=context)
        result = apply(self.r, second["candidate_ref"], request="late", context=context)
        self.assertEqual(result["error"]["code"], "stale_context")
        self.assertEqual(len(self.r.store.rows("commits")), 1)

    def test_T08_idempotency_payload_conflict(self):
        delta = wait_delta(self.r)
        first = propose(self.r, delta)
        self.assertEqual(propose(self.r, delta), first)
        delta["plan_header"]["reason"] = "changed"
        self.assertEqual(propose(self.r, delta)["error"]["code"], "request_conflict")
        context = self.r.head["context_ref"]
        accepted = apply(self.r, first["candidate_ref"], context=context)
        self.assertEqual(apply(self.r, first["candidate_ref"], context=context), accepted)
        self.assertEqual(len(self.r.store.rows("commits")), 1)

    def test_T09_chunk_crash_duplicate_conflict_and_finalize(self):
        ctx = self.r.head["context_ref"]
        opened = self.r.record_output({"tool": "begin_proposal", "context_ref": ctx, "request_id": "begin", "proposal_id": "draft"})
        ref = opened["proposal_ref"]
        delta = wait_delta(self.r)
        source = self.r.store.read("contexts", ctx)
        delta.update(schema=SCHEMA, anchors=anchor_hashes(source["base_plan"], source["problem"], source["execution_state"], source_sha256=source["source_sha256"]))
        action = {"tool": "append_proposal", "context_ref": ctx, "request_id": "chunk", "proposal_ref": ref,
                  "expected_version": 0, "chunk_id": "chunk-1", "set_fields": [{"path": list(p), "value": at(delta, p)} for p in SET_PATHS], "append_arrays": []}
        self.assertEqual(self.r.record_output(action)["status"], "chunk_accepted")
        self.restart()
        self.assertEqual(self.r.record_output({**action, "request_id": "chunk-retry"})["version"], 1)
        bad = deepcopy(action)
        bad["request_id"] = "conflict"
        bad["set_fields"][0]["value"] = "wrong"
        self.assertEqual(self.r.record_output(bad)["error"]["code"], "chunk_conflict")
        finalize = {"tool": "finalize_proposal", "context_ref": ctx, "request_id": "incomplete", "proposal_ref": ref, "expected_version": 1}
        self.assertEqual(self.r.record_output(finalize)["error"]["code"], "proposal_incomplete")
        action.update(request_id="arrays", expected_version=1, chunk_id="chunk-2", set_fields=[], append_arrays=[{"path": list(p), "items": at(delta, p)} for p in ARRAY_PATHS])
        self.assertEqual(self.r.record_output(action)["status"], "chunk_accepted")
        result = self.r.record_output({**finalize, "request_id": "complete", "expected_version": 2})
        self.assertEqual(result["status"], "candidate_checked", result)
        self.assertEqual(apply(self.r, result["candidate_ref"])["status"], "accepted")

    def test_T10_multiple_exact_entity_batches_remain_available(self):
        ctx = self.r.store.read("contexts", self.r.head["context_ref"])
        reader = FactReader(ctx["context_ref"], ctx["facts"])
        ids = [o["operation_id"] for o in ctx["problem"]["operations"][:2]]
        first = reader.read({"kind": "operations", "ids": [ids[0]]})
        reader.read({"kind": "operations", "ids": [ids[1]]})
        self.assertEqual(reader.read({"kind": "operations", "ids": [ids[0]]}), first)
        self.assertEqual(len(reader.cache), 2)
        self.assertEqual(reconstruct(ctx["facts"]), (ctx["problem"], ctx["base_plan"]))

    def test_T11_clock_dependency_invalidates_unchanged_entity(self):
        ctx = self.r.store.read("contexts", self.r.head["context_ref"])
        old = ctx["facts"]
        problem = deepcopy(ctx["problem"])
        problem["time"] += 1
        new = build_facts(problem, ctx["base_plan"])
        key = next(iter(old["entities"]))
        self.assertEqual(old["entities"][key]["source_version"], new["entities"][key]["source_version"])
        self.assertNotEqual(old["entities"][key]["entity_revision"], new["entities"][key]["entity_revision"])
        self.assertEqual(apply_changes(old, changes(old, new)), new)

    def test_T12_missing_change_page_or_competitor_dependency_detected(self):
        ctx = self.r.store.read("contexts", self.r.head["context_ref"])
        old = ctx["facts"]
        problem = deepcopy(ctx["problem"])
        problem["machines"][-1]["currently_down"] = True
        new = build_facts(problem, ctx["base_plan"])
        delta = changes(old, new)
        self.assertEqual(apply_changes(old, delta), new)
        bad = deepcopy(delta)
        bad["pages"].pop()
        with self.assertRaises(HarnessError):
            apply_changes(old, bad)
        bad = deepcopy(delta)
        bad["pages"][0].pop()
        bad["page_hashes"][0] = digest(bad["pages"][0])
        with self.assertRaises(HarnessError):
            apply_changes(old, bad)

    def test_T13_unknown_semantics_and_null_preserved(self):
        cqt = next(r for r in self.r.context()["semantic_coverage"] if r["constraint"] == "cqt")
        self.assertEqual(cqt["implementation"], "not_implemented")
        self.assertEqual(cqt["verdict"], "not_evaluated")
        ctx = self.r.store.read("contexts", self.r.head["context_ref"])
        ops = ctx["problem"]["operations"]
        unknown = [o for o in ops if o.get("qualification_uncertain")]
        self.assertTrue(unknown)
        self.assertTrue(all("unknown" in o["qualification_basis"] for o in unknown))

    def test_T14_private_cross_run_and_algorithm_forbidden(self):
        result = self.r.record_output({"tool": "construct_candidate", "context_ref": self.r.head["context_ref"], "request_id": "no", "algorithm_id": "constructive-gain-rate-v1", "parameters": {}, "budget_seconds": 1})
        self.assertEqual(result["error"]["code"], "capability")
        for ref in (self.r.head["state_ref"], "../../manifest.json", "other-run:plan"):
            result = self.r.record_output({"tool": "read_artifact", "artifact_ref": ref, "path": [], "format": "value", "offset": 0, "count": 0})
            self.assertEqual(result["error"]["code"], "private_or_cross_run")
        self.assertEqual(self.r.store.rows("classical_attempts"), [])

    def test_T15_sent_unknown_attempt_freezes_after_resume(self):
        aid = self.r.reserve_attempt("offline channel timeout injection", {}, channel="replay")
        self.r.mark_started(aid)
        self.restart()
        attempt = self.r.store.read("attempts", aid)
        self.assertEqual(attempt["status"], "unknown")
        self.assertIsNone(attempt["usage"])
        self.assertEqual(self.r.head["phase"], "STOPPED")
        with self.assertRaises(HarnessError):
            self.r.record_output({"tool": "get_context", "context_ref": self.r.head["context_ref"]})

    def test_T16_response_saved_crash_replays_no_new_call(self):
        self.r.store.fault = crash_at("after_response_saved")
        with self.assertRaises(InjectedCrash):
            propose(self.r, wait_delta(self.r))
        self.restart()
        self.assertEqual(len(self.r.store.rows("attempts")), 1)
        candidate = self.r.store.rows("candidates")[0][0]
        apply(self.r, candidate)
        self.assertGreater(self.r.advance()["advanced_seconds"], 0)
        self.assertEqual(self.r.usage()["actual_model_attempts"], 0)

    def test_T17_commit_receipt_lost_no_second_acceptance(self):
        result = propose(self.r, wait_delta(self.r, tasks=[one_task(self.r)]))
        context = self.r.head["context_ref"]
        self.r.store.fault = crash_at("after_commit_before_receipt")
        with self.assertRaises(InjectedCrash):
            apply(self.r, result["candidate_ref"], context=context)
        self.restart()
        receipt = apply(self.r, result["candidate_ref"], context=context)
        self.assertEqual(receipt["status"], "accepted")
        self.assertEqual(len(self.r.store.rows("commits")), 1)
        self.assertGreater(self.r.advance()["dispatch_count_delta"], 0)

    def test_T18_physical_batch_rollback_and_projection_recovery(self):
        result = propose(self.r, wait_delta(self.r, tasks=[one_task(self.r)]))
        apply(self.r, result["candidate_ref"])
        for point in ("after_physical_compute", "during_physical_persist"):
            before = self.r.head["state_ref"]
            self.r.store.fault = crash_at(point)
            with self.assertRaises(InjectedCrash):
                self.r.advance()
            self.restart()
            self.assertEqual(self.r.head["state_ref"], before)
        self.r.store.fault = crash_at("during_trace_export")
        with self.assertRaises(InjectedCrash):
            self.r.advance()
        self.restart()
        trace = self.r.store.trace()
        dispatches = [e for e in trace if e["kind"] == "dispatch" and e.get("plan_task_id") == "fixture-w1387"]
        self.assertEqual(len(dispatches), 1)
        self.assertEqual([e["seq"] for e in trace], list(range(len(trace))))
        self.assertEqual(len((self.path / "exports/trace.jsonl").read_text().splitlines()), len(trace))

    def test_T19_single_writer_and_fencing(self):
        completed = subprocess.run([sys.executable, "-c", "from src.smt_fullfab.harness.store import Store; import sys; Store(sys.argv[1])", str(self.path)], cwd=ROOT, capture_output=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(b"writer_busy", completed.stderr)
        self.r.store.db.execute("UPDATE metadata SET value=? WHERE key='fence'", (encode(self.r.store.token + 1),))
        with self.assertRaisesRegex(HarnessError, "fenced_writer"):
            with self.r.store.transaction():
                self.r.store.event("stale_write", {})

    def test_T20_resume_manifest_budget_and_source_conflict(self):
        propose(self.r, wait_delta(self.r))
        count = len(self.r.store.rows("attempts"))
        self.restart()
        self.assertEqual(len(self.r.store.rows("attempts")), count)
        self.r.close()
        with self.assertRaisesRegex(HarnessError, "manifest_changed"):
            Runtime.resume_run(self.path, expected_manifest="0" * 64)
        self.r = Runtime.resume_run(self.path)
        self.r.close()
        original = (self.path / "manifest.json").read_bytes()
        changed = json.loads(original)
        changed["config"]["limits"]["attempts"] += 1
        (self.path / "manifest.json").write_text(json.dumps(changed))
        with self.assertRaisesRegex(HarnessError, "manifest_changed"):
            Runtime.resume_run(self.path)
        (self.path / "manifest.json").write_bytes(original)
        self.r = Runtime.resume_run(self.path)

    def test_T21_disk_failure_and_corrupt_object_fail_closed(self):
        def disk_full(point):
            if point == "before_object_write":
                raise OSError(28, "No space left on device")
        self.r.store.fault = disk_full
        with self.assertRaises(OSError):
            propose(self.r, wait_delta(self.r))
        self.assertEqual(len(self.r.store.rows("candidates")), 0)
        self.r.close()
        ref = json.loads((self.path / "manifest.json").read_bytes())["initial_state_sha256"]
        # Corrupt the actual private state content-addressed object.
        store = Store(self.path)
        ref = store.meta("head")["state_ref"]
        store.close()
        object_path = self.path / "objects" / (ref + ".z")
        object_path.write_bytes(b"corrupted")
        with self.assertRaisesRegex(HarnessError, "object_corrupt"):
            Runtime.resume_run(self.path)

    def test_T22_zero_progress_not_commit_progress(self):
        delta = wait_delta(self.r)
        delta["holds"]["add"] = []
        result = propose(self.r, delta)
        self.assertEqual(apply(self.r, result["candidate_ref"])["status"], "accepted")
        feedback = self.r.advance()
        self.assertEqual(feedback["advanced_seconds"], 0)
        self.assertEqual(feedback["stop_reason"]["reason"], "uncovered_demand")
        self.assertGreater(len(feedback["stop_reason"]["machines"]), 0)

    def test_T23_independent_audit_and_source_tamper(self):
        result = propose(self.r, wait_delta(self.r, tasks=[one_task(self.r)]))
        apply(self.r, result["candidate_ref"])
        self.r.advance()
        if self.r.head["phase"] != "AUDITING":
            self.r.stop("unexpected_fixture_boundary")
        sha = seal_evidence(self.r)
        report = audit_run(self.path, expected_sha256=sha)
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["decision_provenance"]["B_algorithm_calls"], 0)
        evidence = Evidence(self.path, sha)
        trace = [evidence.get(ref) for ref in evidence.value["physical"]]
        changed = deepcopy(trace)
        committed = next(e for e in changed if e["kind"] == "plan_committed")
        committed["plan"]["tasks"][0]["not_before"] += 1
        with self.assertRaises(HarnessError):
            audit_provenance(evidence, changed)
        from src.smt_fullfab.audit import audit_trace
        for kind in ("missing_terminal", "processing", "time_boundary", "success"):
            bad = deepcopy(trace)
            if kind == "missing_terminal":
                bad.pop()
            elif kind == "processing":
                next(e for e in bad if e["kind"] == "dispatch")["processing_seconds"] += 10
            elif kind == "time_boundary":
                next(e for e in bad if e["kind"] == "time_advance")["to"] += 100
            else:
                bad[-1]["success"] = True
                next(e for e in bad if e["kind"] == "dispatch" and e.get("owner") == "plan")["plan_version"] = "invented"
            self.assertFalse(audit_trace(bad)["valid"], kind)

    def test_T24_fixed_evidence_ignores_shared_ledger_append(self):
        result = propose(self.r, wait_delta(self.r))
        apply(self.r, result["candidate_ref"])
        self.r.advance()
        sha = seal_evidence(self.r)
        before = audit_run(self.path, expected_sha256=sha)
        (self.folder / "shared_model_ledger.jsonl").write_text('{"run_id":"another-arm","unknown_usage":999}\n')
        after = audit_run(self.path, expected_sha256=sha)
        for key in ("valid", "errors", "decision_provenance", "metrics", "evidence_sha256", "cost_accounting"):
            self.assertEqual(before[key], after[key])

    def test_T25_all_machine_wait_is_legal_quality_visible(self):
        result = propose(self.r, wait_delta(self.r))
        apply(self.r, result["candidate_ref"])
        feedback = self.r.advance()
        self.assertEqual(feedback["dispatch_count_delta"], 0)
        sha = seal_evidence(self.r)
        report = audit_run(self.path, expected_sha256=sha)
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["metrics"]["throughput_lots"], 0)
        self.assertGreater(report["metrics"]["terminal_wip_lots"], 2000)
        self.assertEqual(report["quality_evaluation"], "not_evaluated_no_paired_experiment")

    def test_T26_classical_adapter_real_worker_and_no_candidate(self):
        self.r.close()
        self.path = self.folder / "classical-worker"
        self.r = Runtime.start_new(self.path, default_config("C-fixed", seconds=60), experiment_id="offline-classical", mode="policy")
        action = frozen_policy_action(self.r)
        result = self.r.record_output(action, channel="policy")
        self.assertEqual(result["status"], "candidate_checked", result)
        self.assertEqual(self.r.record_output(frozen_policy_action(self.r), channel="policy")["status"], "accepted")
        self.assertGreater(self.r.advance()["dispatch_count_delta"], 0)
        self.assertEqual(len(self.r.store.rows("classical_attempts")), 1)

    def test_T27_common_in_process_branch_no_memory_leak(self):
        result = propose(self.r, wait_delta(self.r, tasks=[one_task(self.r)]))
        apply(self.r, result["candidate_ref"])
        # Prepare an actual in-process common snapshot at non-period T0=61.
        from src.smt_fullfab.harness.factory import capture
        self.r.env.advance_plan(61)
        initial = {"state": capture(self.r.env), "trace": self.r.env.trace, "parent": {"kind": "offline-common-snapshot-fixture"}}
        self.assertGreater(len([j for j in self.r.env.jobs.values() if not j["done"]]), 0)
        branches = []
        for arm in ("A", "B", "C", "C-fixed"):
            config = default_config(arm, seconds=1800 - 61)
            branch = Runtime.start_new(self.folder / ("branch-" + arm), config, experiment_id="offline-pair", initial=initial)
            branches.append((branch.manifest["initial_state_sha256"], branch.store.read("contexts", branch.head["context_ref"])["problem"], branch.manifest["period_anchor"]))
            self.assertEqual(branch.context()["notes"]["text"], "")
            self.assertEqual(branch.env.t, 61)
            self.assertEqual(len(branch.env.trace), len(initial["trace"]))
            branch.close()
        self.assertTrue(all(item == branches[0] for item in branches))

    def test_T28_user_stop_and_resource_caps(self):
        before = len(self.r.store.rows("attempts"))
        (self.path / "stop_requested.json").write_text('{"reason":"user"}')
        with self.assertRaisesRegex(HarnessError, "user_stop"):
            propose(self.r, wait_delta(self.r))
        self.assertEqual(len(self.r.store.rows("attempts")), before)
        self.r.stop("user_stop")
        self.assertLess(self.r.env.t, self.r.env.horizon)
        sha = seal_evidence(self.r)
        report = audit_run(self.path, expected_sha256=sha)
        self.assertFalse(report["valid"])
        self.assertEqual(report["execution_window"], "fail")


class PerformanceGateTests(unittest.TestCase):
    def test_nearest_rank_and_incomplete_denominator(self):
        rows = [{"id": str(i), "attempts": 2 if i < 19 else 5, "accepted": True} for i in range(20)]
        self.assertTrue(microbenchmark_gate(rows)["pass"])
        self.assertEqual(microbenchmark_gate(rows)["p95_nearest_rank"], 2)
        rows[0]["accepted"] = False
        self.assertFalse(microbenchmark_gate(rows)["pass"])
        self.assertEqual(microbenchmark_gate(rows)["n"], 20)
        self.assertFalse(microbenchmark_gate(rows[1:])["pass"])


if __name__ == "__main__":
    unittest.main()
