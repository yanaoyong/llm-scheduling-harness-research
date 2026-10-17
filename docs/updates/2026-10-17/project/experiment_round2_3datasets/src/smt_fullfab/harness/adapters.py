"""Registered A/C/C-fixed tool boundary. B is refused before execution."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from .contracts import ROOT, digest, encode, number, require, strict_json

ALGORITHMS = {"constructive-gain-rate-v1": "construct_candidate",
              "cp-global-explicit-baseline-v1": "optimize_candidate"}
PARAMETERS = {"seed", "weights", "max_slots_per_machine", "plan_version", "valid_until", "freeze_until"}


def execute_classical(runtime, action, attempt):
    """Durable attempt before launching a bounded separate worker; no retries."""
    require(runtime.config["arm"] != "B", "capability", "B cannot invoke algorithms")
    existing = runtime.store.read("classical_attempts", attempt["attempt_id"])
    if existing is not None:
        # In-flight computation has no physical effect, but consumed resources
        # are unknown. Preserve the original attempt, never compute it twice.
        return existing
    context = runtime._bound_context(action)
    require(ALGORITHMS.get(action["algorithm_id"]) == action["tool"], "algorithm_id", "Unregistered tool implementation")
    parameters = action["parameters"]
    require(type(parameters) is dict and set(parameters) == PARAMETERS, "algorithm_parameters", "Complete registered parameters required")
    require(type(parameters["seed"]) is int and type(parameters["max_slots_per_machine"]) is int and 0 < parameters["max_slots_per_machine"] <= 128,
            "algorithm_parameters", "Explicit integer seed and slot cap required")
    require(type(parameters["plan_version"]) is str and bool(parameters["plan_version"]), "algorithm_parameters", "Explicit plan version required")
    require(type(parameters["weights"]) is dict and set(parameters["weights"]) == {"tardiness", "completion", "flow", "setup"}
            and all(number(v) and v >= 0 for v in parameters["weights"].values()), "algorithm_parameters", "Complete finite nonnegative weights required")
    seconds = action["budget_seconds"]
    require(number(seconds) and 0 < seconds <= 60, "classical_budget", "Budget must be in (0,60]")
    records = [r for _, r in runtime.store.rows("classical_attempts")]
    require(len(records) < runtime.config["limits"]["classical_requests"] and
            sum(max(r["budget_seconds"], r.get("duration_seconds", 0)) for r in records) + seconds <= runtime.config["limits"]["classical_seconds"],
            "classical_budget", "Cumulative classical budget does not fit")
    require(not any(r["status"] in ("started", "unknown") for r in records), "classical_unknown", "Unsettled classical attempt")
    require(number(parameters["valid_until"]) and context["time"] < parameters["valid_until"] <= runtime.manifest["end_time"]
            and number(parameters["freeze_until"]) and context["time"] <= parameters["freeze_until"] <= parameters["valid_until"],
            "algorithm_window", "Explicit algorithm window required")
    start_candidate = None
    if action["tool"] == "optimize_candidate":
        candidate = runtime.store.read("candidates", action["candidate_ref"])
        require(candidate is not None and candidate["context_ref"] == context["context_ref"], "stale_candidate", "Explicit checked baseline required")
        start_candidate = candidate["compiled"]["plan"]
    request = {"problem": context["problem"], "parameters": parameters,
               "algorithm_id": action["algorithm_id"], "budget_seconds": seconds,
               "start_candidate": start_candidate,
               "baseline_semantics": "Recorded comparison baseline; CP performs a fresh search, no hidden incumbent constructor or fallback"}
    directory = runtime.store.path / "classical" / attempt["attempt_id"].replace(":", "-")
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "request.json").write_bytes(encode(request))
    record = {"attempt_id": attempt["attempt_id"], "request_ref": runtime.store.put(request),
              "budget_seconds": seconds, "status": "started", "started_epoch": time.time(),
              "decision_owner": "algorithm", "algorithm_id": action["algorithm_id"], "automatic_retries": 0}
    with runtime.store.transaction():
        runtime.store.record("classical_attempts", attempt["attempt_id"], record)
        runtime.store.event("classical_started", record)
    started = time.monotonic()
    try:
        completed = subprocess.run([sys.executable, "-m", "src.smt_fullfab.harness.adapters", str(directory)],
                                   cwd=ROOT, capture_output=True, timeout=seconds + 2, check=False)
        record["stderr_ref"] = runtime.store.put_bytes(completed.stderr)
        record["stdout_ref"] = runtime.store.put_bytes(completed.stdout)
        record["returncode"] = completed.returncode
        output = directory / "result.json"
        result = strict_json(output.read_bytes()) if output.exists() else {"solver_status": "NO_RESULT", "plan": None}
        record["status"] = "finished" if completed.returncode == 0 else "failed"
    except subprocess.TimeoutExpired as exc:
        record.update(status="timeout", returncode=None)
        record["stderr_ref"] = runtime.store.put_bytes(exc.stderr or b"")
        record["stdout_ref"] = runtime.store.put_bytes(exc.stdout or b"")
        result = {"solver_status": "TIMEOUT", "plan": None, "partial_result": "not_available", "fallback": "none"}
    except Exception as exc:
        record["status"] = "failed"
        result = {"solver_status": "EXCEPTION", "plan": None, "error": str(exc), "fallback": "none"}
    record["duration_seconds"] = time.monotonic() - started
    record["result_ref"] = runtime.store.put(result)
    with runtime.store.transaction():
        runtime.store.record("classical_attempts", attempt["attempt_id"], record, replace=True)
        runtime.store.event("classical_finished", record)
    return record


def classical_candidate(runtime, action, attempt, context):
    record = runtime.store.read("classical_attempts", attempt["attempt_id"])
    require(record is not None, "classical_not_started", "Missing durable classical attempt")
    if record["status"] in ("started", "unknown"):
        return {"status": "unknown", "solver_status": "UNKNOWN", "attempt_id": attempt["attempt_id"], "candidate_created": False}
    result = runtime.store.get(record["result_ref"])
    if result.get("plan") is None or result.get("solver_status") not in ("FEASIBLE_HEURISTIC", "FEASIBLE", "OPTIMAL"):
        return {"status": "tool_failed", "solver_status": result.get("solver_status", "UNKNOWN"), "candidate_created": False,
                "result_ref": runtime._publish(result, "algorithm_result"), "duration_seconds": record["duration_seconds"]}
    plan = result["plan"]
    from .factory import prepare
    prepare(runtime.env, plan)
    ref = "candidate:" + uuid.uuid4().hex[:24]
    summary = {"task_count": len(plan["tasks"]), "hold_count": len(plan["holds"]), "plan_sha256": digest(plan),
               "valid_until": plan["valid_until"], "solver_status": result["solver_status"],
               "algorithm_id": action["algorithm_id"], "decision_owner": "algorithm", "global_optimality": False}
    candidate = {"candidate_ref": ref, "context_ref": context["context_ref"], "revision": context["state_revision"],
                 "attempt_id": attempt["attempt_id"], "attempt_index": attempt["index"], "raw_ref": attempt["raw_ref"],
                 "decision_owner": "algorithm", "transformation_kind": "registered_algorithm_output",
                 "algorithm_result_ref": record["result_ref"], "compiled": {"plan": plan}, "summary": summary,
                 "plan_ref": runtime._publish(plan, "candidate_plan")}
    runtime.store.record("candidates", ref, candidate)
    runtime.store.event("candidate_checked", {"candidate_ref": ref, "candidate_sha256": digest(candidate), "attempt_id": attempt["attempt_id"]})
    return {"status": "candidate_checked", "candidate_ref": ref, "summary": summary, "plan_ref": candidate["plan_ref"]}


def frozen_policy_action(runtime):
    """Explicit reproducible policy. Same tools as C; no model attribution."""
    require(runtime.config["arm"] in ("A", "C-fixed"), "policy_arm", "Fixed policy cannot stand in for B/C")
    context = runtime.context()
    candidates = context["candidates"]
    if candidates:
        # This is a disclosed frozen POLICY choice, never a B/C host default.
        return {"tool": "apply_candidate", "context_ref": context["context_ref"],
                "request_id": "fixed-apply-" + context["context_ref"], "candidate_ref": candidates[0]["candidate_ref"]}
    return {"tool": "construct_candidate", "context_ref": context["context_ref"],
            "request_id": "fixed-construct-" + context["context_ref"], "algorithm_id": "constructive-gain-rate-v1",
            "parameters": {"seed": 11, "weights": {"tardiness": 100, "completion": 10, "flow": 1, "setup": 1},
                           "max_slots_per_machine": 8, "plan_version": "fixed-" + context["context_ref"],
                           "valid_until": min(runtime.manifest["end_time"], context["time"] + 1800), "freeze_until": context["time"]},
            "budget_seconds": 5}


def worker(directory):
    directory = Path(directory)
    request = strict_json((directory / "request.json").read_bytes())
    params = request["parameters"]
    problem = deepcopy(request["problem"])
    problem["horizon_end"] = params["valid_until"]
    common = {k: params[k] for k in ("seed", "weights", "max_slots_per_machine", "plan_version")}
    if request["algorithm_id"] == "constructive-gain-rate-v1":
        from ..constructive_tool import solve_constructive_plan
        result = solve_constructive_plan(problem, time_limit_seconds=request["budget_seconds"], **common)
    else:
        from ..optimizer import solve_plan
        result = solve_plan(problem, time_limit_seconds=request["budget_seconds"], freeze_until=params["freeze_until"], use_incumbent=False, **common)
        result["baseline_sha256"] = digest(request["start_candidate"])
        result["baseline_semantics"] = request["baseline_semantics"]
    if result.get("plan") is not None:
        # Header is an explicit tool parameter, not a host repair after selection.
        result["plan"]["freeze_until"] = params["freeze_until"]
    result["transformation_kind"] = "algorithm_explicit_window_and_freeze_parameters"
    with (directory / "result.json").open("xb") as stream:
        stream.write(encode(result))
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == "__main__":
    worker(sys.argv[1])
