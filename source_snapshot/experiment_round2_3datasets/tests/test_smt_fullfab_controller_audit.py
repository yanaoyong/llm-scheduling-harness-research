"""Synthetic file-only fixtures; no model, solver, or simulation is invoked."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from src.smt_fullfab.controller_audit import (audit_controller, digest, _crop, _audit_ledger_admission, _record_digest,
    _verify_pages, _decode_pages_v2, _page_fidelity, MACHINE_FIELDS, MACHINE_FIELDS_V2, TYPE_FIELDS, OP_FIELDS_V2,
    V2_IDENTITY, V2_DICTIONARY_SEMANTICS)


def write(path, value, lines=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if lines:
        path.write_text("".join(json.dumps(row) + "\n" for row in value))
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def fixture(root):
    run = root / "B_fixture"
    ledger = root / "smt_fullfab_ledger.jsonl"
    cfg = {"arm": "B", "run_id": "B_fixture", "seconds": 20, "max_calls": 1, "budget_id": "synthetic-test-grant"}
    write(run / "config.json", cfg)
    source_hashes = {}
    for name in ("controller.py", "interface.py", "model_transport.py", "budget.py"):
        relative = "src/smt_fullfab/" + name
        path = run / "source_snapshot" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("B_PROMPT = 'Synthetic unit fixture, not a model call.'\nC_PROMPT = 'Synthetic C fixture; no call.'\n" if name == "controller.py" else "# Synthetic test evidence only; never executed.\n")
        source_hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    write(run / "provenance.json", {"source_sha256": source_hashes})
    machine = {"machine": 0, "family": "F", "available_at": 0, "current_setup": "", "min_left": 0,
               "min_setup": "", "cascading": False, "processing_until": [], "unavailable_intervals": []}
    operation = {"operation_id": "x:1:1", "lot_id": "x", "step": 1, "visit": 1, "family": "F", "batch_key": ["p", 1],
                 "processing_seconds": 10, "occupation_seconds": 10, "transport_seconds": 0, "batch_min": 1, "batch_max": 1,
                 "setup": "", "setup_time": None, "terminal": True, "release_time": 0, "predecessor_ids": [],
                 "priority": 10, "due": 5, "remaining_work_seconds": 10, "eligible_machines": [0]}
    problem = {"time": 0, "horizon_end": 20, "machines": [machine], "operations": [operation], "scope": [0],
               "setup_transitions": [], "min_runs": {}}
    write(run / "problem_000.json", problem)
    page = [{"family": "F", "machines": [[0, 0, "", 0, "", False, [], []]],
             "types": [[["p", 1], 10, 10, 0, 1, 1, "", None, True]],
             "operations": [["x:1:1", 0, 0, [], 10, 5, 10, None]]}]
    manifest = {"schema": "fullfab-compact-paging-v1", "time": 0, "horizon_end": 20,
                "machine_fields": ["machine", "available_at", "current_setup", "min_left", "min_setup", "cascading", "processing_until", "unavailable_intervals"],
                "type_fields": ["batch_key", "processing_seconds", "occupation_seconds", "transport_seconds", "batch_min", "batch_max", "setup", "setup_time", "terminal"],
                "operation_fields": ["operation_id", "type_index", "release_time", "predecessor_ids", "priority", "due", "remaining_work_seconds", "eligible_override", "optional_same_machine_as"],
                "operation_count": 1, "page_count": 1, "scope": [0], "setup_transitions": [], "min_runs": {}, "observation_end": 20}
    write(run / "page_manifest_000.json", manifest)
    write(run / "page_000_00.json", page)
    output = {"tasks": [{"machine": 0, "operations": ["x:1:1"], "start": 0, "sequence": 4}],
              "holds": [], "commit": True, "reason": "synthetic explicit choice"}
    metadata = {**manifest, "page_index": 0, "last_page": True, "remaining_model_responses": 1}
    prompt = "Synthetic unit fixture, not a model call.\nSCHEMA_AND_LIMITS\n" + json.dumps(metadata) + "\nPAGE\n" + json.dumps(page) + "\nYOUR_PRIOR_PREDECESSOR_CHOICES\n[]"
    schema = {"type": "object", "properties": {"tasks": {"type": "array"}, "holds": {"type": "array"}, "commit": {"type": "boolean"}, "reason": {"type": "string"}},
              "required": ["tasks", "holds", "commit", "reason"], "additionalProperties": False}
    config = {"model": "gpt-6-astra", "reasoning_effort": "medium", "timeout_seconds": 10, "grant_id": cfg["budget_id"]}
    model_dir = run / "model_000"
    model_dir.mkdir()
    (model_dir / "prompt.txt").write_text(prompt)
    write(model_dir / "schema.json", schema)
    fingerprint = hashlib.sha256((prompt + "\n" + json.dumps(schema, ensure_ascii=False, indent=2) + "\n" + "\n" + json.dumps(config, sort_keys=True)).encode()).hexdigest()
    usage = {"input_tokens": 11, "output_tokens": 7, "cached_input_tokens": 0, "cache_write_input_tokens": None, "reasoning_output_tokens": None}
    request = {"call_id": "synthetic-call-0", "config": config, "request_fingerprint": fingerprint}
    model = {**request, "status": "success", "output": output, "usage": usage, "duration_seconds": 1,
             "native_tool_events": [], "timed_out": False, "cost_usd": None}
    write(model_dir / "request.json", request)
    write(model_dir / "result.json", model)
    write(model_dir / "final.txt", output)
    write(model_dir / "events.jsonl", [{"type": "turn.completed", "usage": {"input_tokens": 11, "output_tokens": 7, "cached_input_tokens": 0}}], lines=True)
    approval = {"budget_id": cfg["budget_id"], "authorization": "approved_by_user", "window_seconds": 20,
                "allocation": {"B": 1, "C": 2}, "max_model_attempts": 3, "model": "gpt-6-astra", "reasoning_effort": "medium", "per_call_timeout_seconds": 10}
    rows = [{"event": "approval", "approval": approval},
            {"event": "reserve", "call_id": request["call_id"], "run_id": str(model_dir), "metadata": {"request_fingerprint": fingerprint, "authorization_context": {"purpose": "B", "arm": "B", "window_seconds": 20}}},
            {"event": "finish", "call_id": request["call_id"], "status": "success", "details": {"usage": usage, "duration_seconds": 1}}]
    write(ledger, rows, lines=True)
    write(run / "controller_decisions.jsonl", [{"model_index": 0, "call_id": request["call_id"], "plan_index": 0, "arm": "B", "stage": "B_page", "page_index": 0,
          "input_problem_sha256": digest(problem), "response_sha256": digest(output), "status": "success"}], lines=True)
    write(run / "patch_000_00.json", output)
    raw = {"version": "B_fixture:0", "created_at": 0, "valid_until": 20, "freeze_until": 0, "reason": output["reason"],
           "scope": [0], "tasks": [{"id": "0", "machine": 0, "lot_ids": ["x"], "steps": [1], "visits": [1], "operation_ids": ["x:1:1"], "not_before": 0}], "holds": []}
    write(run / "raw_plan_000.json", raw)
    committed = {**copy.deepcopy(raw), "prediction_horizon_end": 20, "unobserved_future_task_ids": [], "observation_projection": "ordered-machine-prefix-and-equivalent-waits-v1"}
    write(run / "trace.jsonl", [{"kind": "initial", "time": 0, "manifest": {"horizon": 20, "controlled_machine_ids": [0]}},
                                {"kind": "plan_committed", "time": 0, "plan": committed}], lines=True)
    write(run / "plan_commits.jsonl", [{"plan_index": 0, "model_call_id": request["call_id"], "raw_plan_sha256": digest(raw), "committed_plan_sha256": digest(committed)}], lines=True)
    result = {"identity": digest(cfg), "config": cfg, "status": "failed", "full_window_completed": False,
              "failure": "synthetic stop after commit", "model_calls": 1, "model_call_ids": [request["call_id"]],
              "solver_calls": 0, "solver_requested_seconds": 0, "plans_committed": 1}
    write(run / "result.json", result)
    return run, ledger


class ControllerAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="smt_fullfab_controller_audit_test_")
        self.addCleanup(self.temp.cleanup)
        self.run, self.ledger = fixture(Path(self.temp.name))

    def audit(self):
        return audit_controller(self.run, self.ledger)

    def test_preserved_failed_run_can_pass_evidence_but_not_production(self):
        result = self.audit()
        self.assertEqual(result["audit_status"], "passed", result)
        self.assertFalse(result["successful_full_window"])
        self.assertEqual(result["attribution_checked_plans"], 1)

    def test_changed_patch_cannot_be_attributed_to_model(self):
        path = self.run / "patch_000_00.json"
        patch = json.loads(path.read_text());patch["tasks"][0]["start"] = 1
        write(path, patch)
        result = self.audit()
        self.assertFalse(result["valid"])
        self.assertTrue(any("patch differs" in error for error in result["errors"]))

    def test_b_solver_artifact_is_rejected(self):
        write(self.run / "solver_request_000.json", {"synthetic": True})
        self.assertTrue(any("B contains solver" in error for error in self.audit()["errors"]))

    def test_missing_commit_link_is_partial_never_valid(self):
        (self.run / "plan_commits.jsonl").unlink()
        result = self.audit()
        self.assertEqual(result["audit_status"], "partial")
        self.assertFalse(result["valid"])

    def test_changed_model_prompt_fingerprint_is_rejected(self):
        path = self.run / "model_000/prompt.txt"
        path.write_text(path.read_text() + "\nunrecorded advice")
        self.assertTrue(any("fingerprint mismatch" in error for error in self.audit()["errors"]))

    def test_raw_token_events_must_match_ledger_and_summary(self):
        path = self.run / "model_000/events.jsonl"
        write(path, [{"type": "turn.completed", "usage": {"input_tokens": 999, "output_tokens": 7, "cached_input_tokens": 0}}], lines=True)
        self.assertTrue(any("input_tokens differs from raw" in error for error in self.audit()["errors"]))

    def test_incomplete_attempt_is_partial(self):
        (self.run / "result.json").unlink()
        (self.run / "model_000/result.json").unlink()
        # No accepted plan exists in this interrupted-at-first-call scenario.
        write(self.run / "trace.jsonl", [{"kind": "initial", "time": 0, "manifest": {"horizon": 20, "controlled_machine_ids": [0]}}], lines=True)
        result = self.audit()
        self.assertEqual(result["audit_status"], "partial", result)
        self.assertFalse(result["valid"])

    def test_future_head_blocks_later_earlier_start_in_projection(self):
        raw = {"version": "v", "created_at": 0, "valid_until": 100, "freeze_until": 0, "reason": "explicit order", "scope": [0], "holds": [],
               "tasks": [{"id": "future_head", "machine": 0, "lot_ids": ["x"], "steps": [1], "visits": [1], "not_before": 50},
                         {"id": "blocked_tail", "machine": 0, "lot_ids": ["y"], "steps": [1], "visits": [1], "not_before": 5}]}
        clipped = _crop(raw, 20, [0])
        self.assertEqual(clipped["tasks"], [])
        self.assertEqual(clipped["unobserved_future_task_ids"], ["future_head", "blocked_tail"])
        self.assertEqual(clipped["holds"][0]["until"], 20)

    def _make_c_fixture(self, *, heuristic=False, redundant_commit_links=True):
        cfg = json.loads((self.run / "config.json").read_text())
        cfg.update(arm="C", max_calls=2)
        write(self.run / "config.json", cfg)
        raw = json.loads((self.run / "raw_plan_000.json").read_text())
        problem = json.loads((self.run / "problem_000.json").read_text())
        weights = {"completion": 1, "flow": 1, "tardiness": 1, "setup": 1}
        choose = {"action": "solve", "index": None, "method": "decomposed", "seconds": 1, "seed": 1, "slots": 1, "weights": weights, "reason": "synthetic solve"}
        apply = {"action": "apply", "index": 0, "method": None, "seconds": None, "seed": None, "slots": None, "weights": weights, "reason": "synthetic explicit apply"}
        solved = {"model": "fullfab-family-frontier-cpsat-v1", "solver_status": "FEASIBLE", "requested_method": "decomposed", "plan": raw,
                  "objective": None, "best_bound": None, "planned_operations": 1, "wall_seconds": 0.2, "limitations": ["synthetic test"],
                  "global_optimality_claim": False, "unplanned_operations": {}}
        if heuristic:
            local = {"solver_status": "FEASIBLE_HEURISTIC", "selected_source": "classical_incumbent", "best_bound": None,
                     "global_optimality_claim": False, "cp_sat": {"status": "UNKNOWN"}, "nominal_audit": {"valid": True}, "plan": raw,
                     "classical_incumbent": {"status": "FEASIBLE_HEURISTIC", "tasks": raw["tasks"]}}
            solved.update(solver_status="FEASIBLE_HEURISTIC", nominal_audit={"valid": True},
                          heuristic_families=[{"wave": 0, "family": "F", "cp_sat_status": "UNKNOWN"}],
                          family_solves=[{"wave": 0, "family": "F", "response": local}])
        feedback = {k: solved.get(k) for k in ("solver_status", "objective", "best_bound", "planned_operations", "wall_seconds", "limitations", "global_optimality_claim",
                                               "selected_source", "cp_sat", "decomposition_status", "heuristic_families")}
        feedback.update(candidate_index=0, valid_candidate=True, task_count=1, plan_sha256=digest(raw), unplanned_operations_count=0, tasks_preview=raw["tasks"])
        history = [{"decision": choose, "result": feedback}, {"decision": apply, "applied_candidate": 0, "plan_sha256": digest(raw)}]
        write(self.run / "controller_history_000.json", history)
        write(self.run / "solver_request_000.json", {"model_index": 0, "call_id": "synthetic-c-call-0", "plan_index": 0, "response": choose,
              "solver_call_id": "synthetic-solver-0", "solver_index": 0, "method": "decomposed", "requested_seconds": 1,
              "actual_solver_module": "src.smt_fullfab.decomposition", "actual_solver_function": "solve_decomposed_plan",
              "problem_sha256": digest(problem), "parameters": {"time_limit_seconds": 1, "seed": 1, "weights": weights, "max_slots_per_machine": 1, "plan_version": cfg["run_id"] + ":0"}})
        write(self.run / "solver_001.json", solved)
        write(self.run / "solver_evidence.jsonl", [{"solver_index": 0, "solver_call_id": "synthetic-solver-0", "model_index": 0, "call_id": "synthetic-c-call-0", "plan_index": 0,
              "method": "decomposed", "requested_seconds": 1, "status": "success", "actual_solver_module": "src.smt_fullfab.decomposition", "actual_solver_function": "solve_decomposed_plan",
              "solver_result_sha256": digest(solved)}], lines=True)
        approval = json.loads(self.ledger.read_text().splitlines()[0])
        approval["approval"]["max_solver_requested_seconds_per_arm"] = 2
        rows = [approval]
        decisions = []
        schema = {"type": "object", "required": ["action", "index", "method", "seconds", "seed", "slots", "weights", "reason"]}
        usage = {"input_tokens": 11, "output_tokens": 7, "cached_input_tokens": 0, "cache_write_input_tokens": None, "reasoning_output_tokens": None}
        config = {"model": "gpt-6-astra", "reasoning_effort": "medium", "timeout_seconds": 10, "grant_id": cfg["budget_id"]}
        for index, output in enumerate((choose, apply)):
            model_dir = self.run / f"model_{index:03d}"
            model_dir.mkdir(exist_ok=True)
            summary = {"time": 0, "horizon_end": 20, "observation_end": 20, "machines": 1, "operations": 1, "pages": 1,
                       "family_counts": [{"family": "F", "machines": 1, "operations": 1}], "methods_available": ["global", "decomposed"]}
            prompt = "Synthetic C fixture; no call.\nSTATE_DIRECTORY\n" + json.dumps(summary) + "\nOWN_HISTORY\n" + json.dumps(history[:index])
            (model_dir / "prompt.txt").write_text(prompt)
            write(model_dir / "schema.json", schema)
            fingerprint = hashlib.sha256((prompt + "\n" + json.dumps(schema, ensure_ascii=False, indent=2) + "\n" + "\n" + json.dumps(config, sort_keys=True)).encode()).hexdigest()
            call_id = f"synthetic-c-call-{index}"
            request = {"call_id": call_id, "config": config, "request_fingerprint": fingerprint}
            model = {**request, "status": "success", "output": output, "usage": usage, "duration_seconds": 1, "native_tool_events": [], "timed_out": False, "cost_usd": None}
            write(model_dir / "request.json", request)
            write(model_dir / "result.json", model)
            write(model_dir / "final.txt", output)
            write(model_dir / "events.jsonl", [{"type": "turn.completed", "usage": {"input_tokens": 11, "output_tokens": 7, "cached_input_tokens": 0}}], lines=True)
            decisions.append({"model_index": index, "call_id": call_id, "plan_index": 0, "arm": "C", "stage": "C_action", "input_problem_sha256": digest(problem), "response_sha256": digest(output), "status": "success"})
            rows.extend([{"event": "reserve", "call_id": call_id, "run_id": str(model_dir), "metadata": {"request_fingerprint": fingerprint, "authorization_context": {"purpose": "C", "arm": "C", "window_seconds": 20}}},
                         {"event": "finish", "call_id": call_id, "status": "success", "details": {"usage": usage, "duration_seconds": 1}}])
        rows.extend([{"event": "solver_reserve", "call_id": "synthetic-solver-0", "arm": "C", "run_id": str(self.run), "requested_seconds": 1},
                     {"event": "solver_finish", "call_id": "synthetic-solver-0", "status": "success", "details": {"solver_status": solved["solver_status"], "wall_seconds": 0.2}}])
        write(self.ledger, rows, lines=True)
        write(self.run / "controller_decisions.jsonl", decisions, lines=True)
        commit = json.loads((self.run / "plan_commits.jsonl").read_text())
        commit.update(model_call_id="synthetic-c-call-1")
        if redundant_commit_links:
            commit.update(source_candidate_index=0, source_solver_index=0)
        write(self.run / "plan_commits.jsonl", [commit], lines=True)
        result = json.loads((self.run / "result.json").read_text())
        result.update(config=cfg, identity=digest(cfg), model_calls=2, model_call_ids=["synthetic-c-call-0", "synthetic-c-call-1"], solver_calls=1, solver_requested_seconds=1)
        write(self.run / "result.json", result)

    def test_c_exact_solve_and_apply_attribution(self):
        self._make_c_fixture()
        result = self.audit()
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["checked_solver_requests_for_committed_plans"], 1)

    def test_c_infers_unambiguous_apply_source_without_redundant_commit_fields(self):
        self._make_c_fixture(redundant_commit_links=False)
        result = self.audit()
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["reconstructed_plan_attributions"][0]["source_solver_index"], 0)
        self.assertEqual(result["reconstructed_plan_attributions"][0]["source_candidate_index"], 0)

    def test_c_wrong_redundant_candidate_link_is_rejected(self):
        self._make_c_fixture()
        path = self.run / "plan_commits.jsonl"
        commit = json.loads(path.read_text());commit["source_candidate_index"] = 99
        write(path, [commit], lines=True)
        self.assertTrue(any("candidate/solver attribution mismatch" in e for e in self.audit()["errors"]))

    def test_c_disclosed_feasible_heuristic_is_accepted_without_optimality(self):
        self._make_c_fixture(heuristic=True, redundant_commit_links=False)
        result = self.audit()
        self.assertTrue(result["valid"], result)
        self.assertFalse(result["successful_full_window"])

    def test_c_heuristic_claiming_global_bound_is_rejected(self):
        self._make_c_fixture(heuristic=True)
        path = self.run / "solver_001.json"
        solved = json.loads(path.read_text());solved["best_bound"] = 1
        write(path, solved)
        metadata = json.loads((self.run / "solver_evidence.jsonl").read_text())
        metadata["solver_result_sha256"] = digest(solved)
        write(self.run / "solver_evidence.jsonl", [metadata], lines=True)
        self.assertTrue(any("global bound/optimality" in e for e in self.audit()["errors"]))

    def test_c_altered_solver_feedback_is_rejected(self):
        self._make_c_fixture()
        path = self.run / "controller_history_000.json"
        history = json.loads(path.read_text());history[0]["result"]["objective"] = -999
        write(path, history)
        self.assertTrue(any("feedback differs from saved solver: objective" in e for e in self.audit()["errors"]))

    def test_c_wrong_solver_method_is_rejected_even_with_updated_hash(self):
        self._make_c_fixture()
        path = self.run / "solver_001.json"
        solved = json.loads(path.read_text());solved["model"] = "fullfab-batch-slots-cross-family-v1"
        write(path, solved)
        metadata = json.loads((self.run / "solver_evidence.jsonl").read_text())
        metadata["solver_result_sha256"] = digest(solved)
        write(self.run / "solver_evidence.jsonl", [metadata], lines=True)
        self.assertTrue(any("executed shared solver model" in e for e in self.audit()["errors"]))

    def test_c_altered_solver_weights_are_rejected(self):
        self._make_c_fixture()
        path = self.run / "solver_request_000.json"
        request = json.loads(path.read_text());request["parameters"]["weights"]["tardiness"] = 999
        write(path, request)
        self.assertTrue(any("parameters differ from model choices" in e for e in self.audit()["errors"]))

    def test_c_missing_apply_history_is_rejected(self):
        self._make_c_fixture()
        path = self.run / "controller_history_000.json"
        history = json.loads(path.read_text())[:-1];write(path, history)
        self.assertTrue(any("no explicit model apply" in e for e in self.audit()["errors"]))

    def test_complete_registered_b_evidence_accepts_unlimited_count_without_rewriting_prior_rules(self):
        # Hand-written complete file fixture, using the actual new public schema.
        from src.smt_fullfab.budget import ROOT
        new_run = (Path(self.temp.name) / "runs/smt_fullfab_stage2/B_fixture").resolve()
        new_run.parent.mkdir(parents=True)
        shutil.move(str(self.run), new_run);self.run = new_run
        approval = json.loads((ROOT / "configs/smt_fullfab/stage2_probe.approved.json").read_text())
        amendment = json.loads((ROOT / "configs/smt_fullfab/research_limit_waiver.approved.json").read_text())
        cfg = json.loads((self.run / "config.json").read_text())
        cfg.update(seconds=3600, seed=1901, budget_id=approval["budget_id"], amendment_id=amendment["amendment_id"],
                   max_calls=None, wall_seconds=7200, max_log_bytes=1000000, solver_budget_seconds=0, page_chars=45000)
        write(self.run / "config.json", cfg)
        registration = {"run_id": str(self.run), "arm": "B", "scenario": 1901, "window_seconds": 3600, "solver_seconds": 0,
                        "wall_seconds": 7200, "max_log_bytes": 1000000, "amendment_id": amendment["amendment_id"], "budget_id": approval["budget_id"],
                        "phase": "stage2_research", "formal": False}
        registration["registration_id"] = _record_digest(registration)
        write(self.run / "resource_registration.json", registration)
        manifest = json.loads((self.run / "page_manifest_000.json").read_text());manifest["observation_end"] = 3600
        write(self.run / "page_manifest_000.json", manifest)
        page = json.loads((self.run / "page_000_00.json").read_text())
        metadata = {**manifest, "page_index": 0, "last_page": True, "remaining_model_responses": None}
        prompt = "Synthetic unit fixture, not a model call.\nSCHEMA_AND_LIMITS\n" + json.dumps(metadata) + "\nPAGE\n" + json.dumps(page) + "\nYOUR_PRIOR_PREDECESSOR_CHOICES\n[]"
        model_dir = self.run / "model_000";(model_dir / "prompt.txt").write_text(prompt)
        schema = json.loads((model_dir / "schema.json").read_text())
        request = json.loads((model_dir / "request.json").read_text())
        context = {"purpose": "B", "arm": "B", "scenario": 1901, "window_seconds": 3600}
        request["config"].update(grant_id=approval["budget_id"], phase="stage2_research", authorization_context=context, timeout_seconds=180)
        fingerprint = hashlib.sha256((prompt + "\n" + json.dumps(schema, ensure_ascii=False, indent=2) + "\n" + "\n" + json.dumps(request["config"], sort_keys=True)).encode()).hexdigest()
        request["request_fingerprint"] = fingerprint;write(model_dir / "request.json", request)
        model = json.loads((model_dir / "result.json").read_text());model.update(request);write(model_dir / "result.json", model)
        trace = [json.loads(line) for line in (self.run / "trace.jsonl").read_text().splitlines()]
        trace[0]["manifest"].update(horizon=3600, seed=1901);write(self.run / "trace.jsonl", trace, lines=True)
        result = json.loads((self.run / "result.json").read_text());result.update(config=cfg, identity=digest(cfg));write(self.run / "result.json", result)
        rows = [{"event": "approval", "approval": approval}]
        rows.append({"event": "research_limit_waiver", "amendment": amendment, "original_approval_sha256": _record_digest(approval),
                     "prefix_record_count": len(rows), "prior_ledger_sha256": _record_digest(rows)})
        rows.append({"event": "stage_run_registered", "registration": registration})
        account = {"attempts": 0, "reported_input_output_tokens": 0, "unknown_completed": [], "pending": [], "model_active_seconds": 0}
        rows.extend([{"event": "reserve", "call_id": request["call_id"], "run_id": str(model_dir), "phase": "stage2_research",
                      "amendment_id": amendment["amendment_id"], "registration_id": registration["registration_id"], "account_before": account, "run_account_before": account,
                      "metadata": {"model": "gpt-6-astra", "reasoning_effort": "medium", "timeout_seconds": 180,
                                   "request_fingerprint": fingerprint, "authorization_context": context}},
                     {"event": "finish", "call_id": request["call_id"], "status": "success", "details": {"usage": model["usage"], "duration_seconds": 1}}])
        write(self.ledger, rows, lines=True)
        audited = self.audit()
        self.assertTrue(audited["valid"], audited)
        self.assertFalse(audited["successful_full_window"])
        cfg["wall_seconds"] = 99999;write(self.run / "config.json", cfg)
        self.assertTrue(any("immutable registration: wall_seconds" in e for e in self.audit()["errors"]))


def paging_v2_fixture(problem):
    """Hand-written one-family schema fixture, independent of the encoder."""
    machine, operation = problem["machines"][0], problem["operations"][0]
    mcore = MACHINE_FIELDS + ["family"]
    ocore = ["operation_id", "release_time", "predecessor_ids", "priority", "due", "remaining_work_seconds", "eligible_machines",
             "lot_id", "step", "visit", "waiting_since", "family"] + TYPE_FIELDS
    metadata = {key: value for key, value in problem.items() if key not in ("machines", "operations")}
    manifest = {"schema": "fullfab-compact-paging-v2", "problem_metadata": copy.deepcopy(metadata),
                "source_problem_sha256": _record_digest(problem), "machine_fields": MACHINE_FIELDS_V2, "type_fields": TYPE_FIELDS,
                "operation_fields": OP_FIELDS_V2, "machine_count": 1, "operation_count": 1, "page_count": 1,
                "operation_identity": V2_IDENTITY, "dictionary_semantics": V2_DICTIONARY_SEMANTICS,
                "eligible_override_sentinel": "all_family_machines", "observation_end": 20,
                **{key: problem[key] for key in ("time", "horizon_end", "scope", "setup_transitions", "min_runs")}}
    group = {"family": "F", "machines": [[machine.get(key) for key in MACHINE_FIELDS] + [0, 0]],
             "machine_extras": [{"values": {k: v for k, v in machine.items() if k not in mcore}, "absent": [k for k in mcore if k not in machine]}],
             "types": [[operation.get(key) for key in TYPE_FIELDS]],
             "operations": [[operation["operation_id"], 0, operation["release_time"], operation["predecessor_ids"], operation["priority"], operation["due"],
                             operation["remaining_work_seconds"], "all_family_machines", 0, operation["lot_id"], operation["step"], operation["visit"], operation.get("waiting_since"), 0]],
             "operation_extras": [{"values": {k: v for k, v in operation.items() if k not in ocore}, "absent": [k for k in ocore if k not in operation]}]}
    return manifest, [[group]]


class FullFieldPagingAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="smt_fullfab_paging_audit_test_")
        self.addCleanup(self.temp.cleanup)
        self.run, self.ledger = fixture(Path(self.temp.name))
        self.problem = json.loads((self.run / "problem_000.json").read_text())
        self.problem.update(uncertainty="unknown future failures", frozen_tasks=[], forecast_limitations=["未观测的状态不应伪造"], future_extension={"null": None, "nested": [1, False]})
        self.problem["machines"][0].update(currently_down=False, availability_basis="causal observation")
        del self.problem["machines"][0]["min_setup"]
        self.problem["operations"][0].update(sampling_percent=15, rework_percent=3, qualification_basis="observed binding", same_machine_as=None,
                                             conditional_virtual_successors=[{"sampling_percent": 20}], waiting_since=None)
        self.manifest, self.pages = paging_v2_fixture(self.problem)

    def errors(self):
        return _verify_pages(self.problem, self.manifest, self.pages)

    def test_all_fields_and_missing_null_survive_independent_decode(self):
        self.assertEqual(self.errors(), [])
        decoded = _decode_pages_v2(self.manifest, self.pages)
        self.assertEqual(decoded, self.problem)
        self.assertNotIn("min_setup", decoded["machines"][0])
        self.assertIsNone(decoded["operations"][0]["waiting_since"])
        self.assertTrue(_page_fidelity(self.problem, self.manifest, self.pages)["full_problem_lossless_certified"])

    def test_top_level_uncertainty_cannot_be_dropped_even_with_original_hash(self):
        del self.manifest["problem_metadata"]["uncertainty"]
        self.assertTrue(any("every original problem field" in e for e in self.errors()))

    def test_machine_state_or_operation_rework_extras_cannot_be_omitted(self):
        for table, key in (("machine_extras", "currently_down"), ("operation_extras", "rework_percent")):
            with self.subTest(key=key):
                pages = copy.deepcopy(self.pages)
                del pages[0][0][table][0]["values"][key]
                self.assertTrue(_verify_pages(self.problem, self.manifest, pages))

    def test_explicit_null_cannot_be_silently_replaced_by_absence(self):
        self.pages[0][0]["operation_extras"][0]["absent"].append("waiting_since")
        self.assertTrue(self.errors())

    def test_extras_cannot_override_core_or_hide_structural_identity(self):
        self.pages[0][0]["operation_extras"][0]["values"]["due"] = 999
        self.assertTrue(any("overwrite" in e for e in self.errors()))
        self.pages[0][0]["operation_extras"][0]["values"].pop("due")
        self.pages[0][0]["operation_extras"][0]["absent"].append("operation_id")
        self.assertTrue(any("required" in e for e in self.errors()))

    def test_unreferenced_dictionary_advice_and_undeclared_metadata_are_rejected(self):
        self.pages[0][0]["operation_extras"].append({"values": {"advice": "choose lot X"}, "absent": []})
        self.assertTrue(any("unused" in e for e in self.errors()))
        self.pages[0][0]["operation_extras"].pop()
        self.manifest["advice"] = "choose lot X"
        self.assertTrue(any("undeclared" in e for e in self.errors()))

    def test_original_order_restored_from_indices_across_split_pages(self):
        other = copy.deepcopy(self.problem["operations"][0]);other.update(operation_id="y:1:1", lot_id="y")
        self.problem["operations"].append(other)
        self.manifest.update(operation_count=2, page_count=2, source_problem_sha256=_record_digest(self.problem))
        second = copy.deepcopy(self.pages[0]);second[0]["operations"][0][0] = "y:1:1"
        second[0]["operations"][0][8:10] = [1, "y"]
        self.pages.insert(0, second)
        self.assertEqual(self.errors(), [])
        self.pages[0][0]["operations"][0][8] = 0
        self.assertTrue(any("duplicated" in e for e in self.errors()))

    def test_repeated_family_dictionary_and_top_mirror_must_match(self):
        self.pages.append(copy.deepcopy(self.pages[0]));self.pages[1][0]["operations"] = []
        self.pages[1][0]["machine_extras"][0]["values"]["currently_down"] = True
        self.manifest["page_count"] = 2
        self.assertTrue(any("dictionaries differ" in e for e in self.errors()))
        self.pages.pop();self.manifest["page_count"] = 1;self.manifest["time"] = 3
        self.assertTrue(any("mirror differs" in e for e in self.errors()))

    def test_v1_consistency_is_not_upgraded_to_full_lossless_certification(self):
        old = json.loads((self.run / "problem_000.json").read_text())
        old.update(uncertainty="omitted in v1")
        manifest = json.loads((self.run / "page_manifest_000.json").read_text())
        pages = [json.loads((self.run / "page_000_00.json").read_text())]
        fidelity = _page_fidelity(old, manifest, pages)
        self.assertTrue(fidelity["declared_representation_consistent"])
        self.assertFalse(fidelity["full_problem_lossless_certified"])
        self.assertIn("uncertainty", fidelity["legacy_v1_limitations"]["unrepresented_problem_fields"])

    def _install_v2(self):
        write(self.run / "problem_000.json", self.problem)
        write(self.run / "page_manifest_000.json", self.manifest)
        write(self.run / "page_000_00.json", self.pages[0])
        cfg = json.loads((self.run / "config.json").read_text())
        ledger = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        decisions = [json.loads(line) for line in (self.run / "controller_decisions.jsonl").read_text().splitlines()]
        for directory in sorted(self.run.glob("model_*")):
            request = json.loads((directory / "request.json").read_text())
            result = json.loads((directory / "result.json").read_text())
            schema = json.loads((directory / "schema.json").read_text())
            if cfg["arm"] == "B":
                metadata = {**self.manifest, "page_index": 0, "last_page": True, "remaining_model_responses": 1}
                prompt = "Synthetic unit fixture, not a model call.\nSCHEMA_AND_LIMITS\n" + json.dumps(metadata) + "\nPAGE\n" + json.dumps(self.pages[0]) + "\nYOUR_PRIOR_PREDECESSOR_CHOICES\n[]"
            else:
                old = (directory / "prompt.txt").read_text()
                start, tail = old.split("\nSTATE_DIRECTORY\n")
                summary_text, tail = tail.split("\nOWN_HISTORY\n")
                summary = json.loads(summary_text);summary["problem_metadata"] = self.manifest["problem_metadata"]
                prompt = start + "\nSTATE_DIRECTORY\n" + json.dumps(summary) + "\nOWN_HISTORY\n" + tail
            (directory / "prompt.txt").write_text(prompt)
            fingerprint = hashlib.sha256((prompt + "\n" + json.dumps(schema, ensure_ascii=False, indent=2) + "\n" + "\n" + json.dumps(request["config"], sort_keys=True)).encode()).hexdigest()
            request["request_fingerprint"] = result["request_fingerprint"] = fingerprint
            write(directory / "request.json", request);write(directory / "result.json", result)
            for row in ledger:
                if row["event"] == "reserve" and row["call_id"] == result["call_id"]:
                    row["metadata"]["request_fingerprint"] = fingerprint
        for row in decisions:
            row["input_problem_sha256"] = digest(self.problem)
        write(self.ledger, ledger, lines=True)
        write(self.run / "controller_decisions.jsonl", decisions, lines=True)
        for path in self.run.glob("solver_request_*.json"):
            request = json.loads(path.read_text());request["problem_sha256"] = digest(self.problem);write(path, request)

    def test_complete_b_evidence_v2_is_certified_without_model_or_solver(self):
        self._install_v2()
        result = audit_controller(self.run, self.ledger)
        self.assertTrue(result["valid"], result)
        self.assertTrue(result["all_saved_problem_pages_lossless_certified"])

    def test_c_state_directory_exposes_exact_complete_top_metadata(self):
        ControllerAuditTests._make_c_fixture(self)
        self._install_v2()
        result = audit_controller(self.run, self.ledger)
        self.assertTrue(result["valid"], result)
        self.assertTrue(result["all_saved_problem_pages_lossless_certified"])
        path = self.run / "model_001/prompt.txt"
        path.write_text(path.read_text().replace('"uncertainty": "unknown future failures", ', ''))
        result = audit_controller(self.run, self.ledger)
        self.assertTrue(any("state directory differs" in e for e in result["errors"]))


class ScopedWaiverAuditTests(unittest.TestCase):
    """Authorization history fixtures only; never append to the real ledger."""
    def setUp(self):
        self.approval = {"budget_id": "smt-fullfab-stage2-probe-v1", "authorization": "approved_by_user", "scenario": 1701,
                         "window_seconds": 3600, "model": "gpt-6-astra", "max_model_attempts": 1,
                         "allocation": {"B": 1, "C": 1}, "observed_input_output_token_admission_limit": 10,
                         "max_completed_unknown_usage": 1, "per_call_timeout_seconds": 180,
                         "total_active_wall_seconds": 2700, "max_solver_requested_seconds_per_arm": 60}
        self.rows = [{"event": "approval", "approval": self.approval}, self.reserve("old-B", "B"), self.finish("old-B", unknown=True)]
        self.waiver = {"event": "scoped_limit_waiver", "original_approval_sha256": _record_digest(self.approval),
                       "unknown_finishes_at_approval": {"old-B": _record_digest(self.rows[-1])},
                       "amendment": {"amendment_id": "explicit-C-waiver", "budget_id": self.approval["budget_id"],
                                     "authorization": "approved_by_user", "approval_text": "豁免次数与用量限制", "allowed_purpose": "C",
                                     "waived_limits": ["attempt_count", "reported_tokens", "unknown_usage_admission"], "scenario": 1701, "window_seconds": 3600}}

    def reserve(self, call_id, arm="C", *, timeout=180):
        return {"event": "reserve", "call_id": call_id, "phase": "stage2_probe", "run_id": "/synthetic/smt_fullfab/" + call_id,
                "amendment_id": "explicit-C-waiver" if arm == "C" else None,
                "metadata": {"model": "gpt-6-astra", "timeout_seconds": timeout,
                             "authorization_context": {"purpose": arm, "arm": arm, "scenario": 1701, "window_seconds": 3600}}}

    def finish(self, call_id, *, unknown=False, duration=10):
        return {"event": "finish", "call_id": call_id, "status": "failed" if unknown else "success",
                "details": {"usage": {"input_tokens": None, "output_tokens": None} if unknown else {"input_tokens": 20, "output_tokens": 10},
                            "duration_seconds": duration}}

    def audit(self, rows=None):
        return _audit_ledger_admission(rows or self.rows, self.approval)

    def test_explicit_c_only_waiver_keeps_all_counters_and_unknown_history(self):
        self.rows.extend([self.waiver, self.reserve("C-1"), self.finish("C-1", unknown=True), self.reserve("C-2"), self.finish("C-2")])
        result = self.audit()
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["unknown_usage_call_ids"], ["old-B", "C-1"])
        self.assertEqual(result["model_active_seconds"], 30)
        self.assertTrue(result["admissions"]["C-2"]["waiver_applied"])

    def test_later_waiver_does_not_retroactively_authorize_c(self):
        self.rows.extend([self.reserve("premature-C"), self.finish("premature-C"), self.waiver])
        self.assertTrue(any("after global cap" in e for e in self.audit()["errors"]))
        self.assertFalse(self.audit()["admissions"]["premature-C"]["waiver_applied"])

    def test_b_remains_subject_to_original_gates(self):
        self.rows.extend([self.waiver, self.reserve("extra-B", "B")])
        result = self.audit()
        self.assertTrue(any("after global cap" in e for e in result["errors"]))
        self.assertTrue(any("unknown-usage stop" in e for e in result["errors"]))

    def test_waiver_cannot_clear_old_unknown_finish(self):
        self.waiver["unknown_finishes_at_approval"] = {}
        self.rows.extend([self.waiver, self.reserve("C-1")])
        self.assertTrue(any("unknown completion evidence anchor" in e for e in self.audit()["errors"]))

    def test_waiver_cannot_change_original_time_limit(self):
        self.approval["total_active_wall_seconds"] = 99999
        self.waiver["original_approval_sha256"] = _record_digest(self.approval)
        self.rows.extend([self.waiver, self.reserve("C-1")])
        self.assertTrue(any("nonwaived time/solver" in e for e in self.audit()["errors"]))

    def test_waiver_cannot_change_window_or_purpose(self):
        for key, value in (("window_seconds", 86400), ("allowed_purpose", "B")):
            with self.subTest(key=key):
                waiver = copy.deepcopy(self.waiver);waiver["amendment"][key] = value
                self.assertTrue(self.audit(self.rows + [waiver, self.reserve("C-1")])["errors"])

    def test_waiver_still_stops_at_pending_call(self):
        self.rows.extend([self.waiver, self.reserve("C-1"), self.reserve("C-2")])
        self.assertTrue(any("unresolved previous" in e for e in self.audit()["errors"]))

    def test_dynamic_timeout_cannot_exceed_remaining_model_active_time(self):
        self.rows.extend([self.waiver, self.reserve("C-1"), self.finish("C-1", duration=2680), self.reserve("C-2", timeout=11)])
        self.assertTrue(any("remaining active/per-call budget" in e for e in self.audit()["errors"]))
        self.rows[-1]["metadata"]["timeout_seconds"] = 10
        self.assertEqual(self.audit()["errors"], [])

    def test_duplicate_or_premature_waiver_is_rejected(self):
        self.assertTrue(self.audit(self.rows + [self.waiver, self.waiver])["errors"])
        self.assertTrue(self.audit([self.waiver] + self.rows)["errors"])

    def test_reservation_cannot_reset_account_before(self):
        reserve = self.reserve("C-1")
        reserve["account_before"] = {"attempts": 0, "reported_input_output_tokens": 0, "unknown_completed": [], "pending": [], "model_active_seconds": 0}
        self.rows.extend([self.waiver, reserve])
        self.assertTrue(any("historical consumption" in e for e in self.audit()["errors"]))

    def test_c_solver_budget_is_cumulative_across_runs_and_not_waived(self):
        self.rows.extend([self.waiver, {"event": "solver_reserve", "call_id": "s1", "arm": "C", "requested_seconds": 40},
                          {"event": "solver_reserve", "call_id": "s2", "arm": "C", "requested_seconds": 21}, self.reserve("C-1")])
        result = self.audit()
        self.assertTrue(any("unchanged arm budget" in e for e in result["errors"]))
        self.assertEqual(result["admissions"]["C-1"]["solver_requested_seconds_before_by_arm"]["C"], 61)


class ResearchBudgetAuditTests(unittest.TestCase):
    """Replay temporary registration ledgers; no actual account is touched."""
    def setUp(self):
        from src.smt_fullfab.budget import BudgetLedger, ROOT
        self.temp = tempfile.TemporaryDirectory(prefix="smt_fullfab_research_audit_")
        self.addCleanup(self.temp.cleanup)
        self.ledger = BudgetLedger(Path(self.temp.name) / "smt_fullfab.jsonl")
        self.approval = json.loads((ROOT / "configs/smt_fullfab/stage2_probe.approved.json").read_text())
        self.amendment = json.loads((ROOT / "configs/smt_fullfab/research_limit_waiver.approved.json").read_text())
        self.ledger.approve(self.approval)
        self.run = ROOT / "runs/smt_fullfab_stage2" / ("synthetic_" + Path(self.temp.name).name)
        old = self.ledger.reserve(phase="stage2_probe", run_id=str(self.run.parent / "old_unknown" / "model_000"),
            grant_id=self.approval["budget_id"], metadata={"authorization_context": {"purpose": "B", "arm": "B", "window_seconds": 3600}})
        self.ledger.finish(old, "failed", {"usage": {"input_tokens": None, "output_tokens": None}, "duration_seconds": 2701})
        self.ledger.approve_research_limit_waiver(self.amendment)
        self.registration = self.ledger.register_stage_run(str(self.run), "C", 1901, 28800, 120, 5000, 1000000)

    def rows(self):
        return [json.loads(line) for line in self.ledger.path.read_text().splitlines()]

    def call(self, *, unknown=False):
        cid = self.ledger.reserve(phase="stage2_research", run_id=str(self.run / "model_000"), grant_id=self.approval["budget_id"],
            metadata={"model": "gpt-6-astra", "reasoning_effort": "medium", "timeout_seconds": 180,
                      "authorization_context": {"purpose": "C", "arm": "C", "scenario": 1901, "window_seconds": 28800}})
        self.ledger.finish(cid, "failed" if unknown else "success", {"usage": {"input_tokens": None, "output_tokens": None} if unknown else
            {"input_tokens": 250000, "output_tokens": 10000}, "duration_seconds": 20})
        return cid

    def audit(self, rows=None):
        return _audit_ledger_admission(self.rows() if rows is None else rows, self.approval)

    def test_new_authority_applies_only_to_registered_calls_after_approval(self):
        first = self.call(unknown=True);last = self.call()
        result = self.audit()
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["admissions"][last]["registration"], self.registration)
        self.assertIn(first, result["unknown_usage_call_ids"])
        self.assertEqual(result["model_active_seconds"], 2741)

    def test_ledger_prefix_and_original_unknown_cannot_be_rewritten(self):
        self.call();rows = self.rows()
        next(row for row in rows if row["event"] == "finish")["details"]["duration_seconds"] = 0
        self.assertTrue(any("immutable ledger anchor" in error for error in self.audit(rows)["errors"]))

    def test_later_registration_does_not_authorize_earlier_call(self):
        self.call();rows = self.rows()
        position = next(i for i,r in enumerate(rows) if r["event"] == "stage_run_registered")
        registration = rows.pop(position);rows.append(registration)
        self.assertTrue(any("preceding run registration" in error for error in self.audit(rows)["errors"]))

    def test_run_context_and_reasoning_effort_cannot_drift(self):
        self.call();rows = self.rows();reserve = [r for r in rows if r["event"] == "reserve"][-1]
        reserve["metadata"]["reasoning_effort"] = "high"
        reserve["metadata"]["authorization_context"]["scenario"] = 999
        errors = self.audit(rows)["errors"]
        self.assertTrue(any("scenario/window/phase" in e for e in errors))
        self.assertTrue(any("model/reasoning" in e for e in errors))

    def test_registered_solver_120_does_not_expand_legacy_60_account(self):
        for _ in range(2):
            sid = self.ledger.reserve_solver(arm="C", run_id=str(self.run), requested_seconds=60)
            self.ledger.finish_solver(sid, "failed", {})
        self.call();result = self.audit()
        self.assertEqual(result["errors"], [])
        last = next(reversed(result["admissions"].values()))
        self.assertEqual(last["run_solver_requested_seconds_before"], 120)
        self.assertEqual(last["solver_requested_seconds_before_by_arm"].get("C", 0), 0)
        rows = self.rows();[r for r in rows if r["event"] == "solver_reserve"][-1]["requested_seconds"] = 61
        self.assertTrue(any("registered run allowance" in error for error in self.audit(rows)["errors"]))

    def test_duplicate_registration_and_formal_stage_cannot_reset_limits(self):
        rows = self.rows();registration = next(r for r in rows if r["event"] == "stage_run_registered")
        self.assertTrue(self.audit(rows + [registration])["errors"])
        changed = copy.deepcopy(rows);r = next(r for r in changed if r["event"] == "stage_run_registered")["registration"]
        r["formal"] = True;r["registration_id"] = _record_digest({k:v for k,v in r.items() if k != "registration_id"})
        self.assertTrue(any("formal preregistration" in e for e in self.audit(changed)["errors"]))


if __name__ == "__main__":
    unittest.main()
