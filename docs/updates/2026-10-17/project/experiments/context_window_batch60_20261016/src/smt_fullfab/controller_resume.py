"""Execute one explicitly registered B cold-state recovery segment.

Accepted parent pages are immutable references. Revisions replace only a failed
page with a new model response; no code repairs choices or invokes an optimizer.
Existing segments, including interrupted ones, are never automatically resumed.
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import traceback

from .audit import audit_trace
from .budget import BudgetLedger, ROOT
from .controller_audit import _record_digest, _schema_errors, sha_file
from .controller_recovery import _choice_errors, _dead_claim, _inventory, _schema_from_frozen_source
from .environment import FullFabEnvironment, digest, write_new
from .interface import compact_pages, decode_plan, expand_pages, validate_choices
from .model_transport import ModelConfig, call_model
from .runner import crop_plan, source_snapshot

VERSION = "smt-fullfab-B-cold-recovery-executor-v1"
FEEDBACK_SECTION = "VALIDATION_FEEDBACK"


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _append(path, row):
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def frozen_B_contract(parent):
    """Interpret only literal schema and string concatenation, never source code."""
    path = Path(parent) / "source_snapshot/src/smt_fullfab/controller.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values = {}

    def literal_string(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return literal_string(node.left) + literal_string(node.right)
        raise ValueError("frozen B prompt is not a safe literal string expression")

    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ("BASE", "B_PROMPT"):
                if name in values:
                    raise ValueError("duplicate frozen prompt assignment")
                values[name] = literal_string(node.value)
    if "B_PROMPT" not in values:
        raise ValueError("frozen B_PROMPT missing")
    return _schema_from_frozen_source(Path(parent)), values["B_PROMPT"]


def _verify_runtime_compatibility(parent):
    provenance = _read(parent / "provenance.json")
    if provenance["requirements_sha256"] != sha_file(ROOT / "requirements.lock"):
        raise ValueError("runtime dependencies differ from parent")
    # Physical dependency hashes are checked again by from_snapshot. Paging and
    # decoding must also be identical; only the controller orchestration changes.
    interface = "src/smt_fullfab/interface.py"
    if sha_file(ROOT / interface) != provenance["source_sha256"][interface]:
        raise ValueError("paging/decoding runtime differs from parent")
    def function_ast(path, name):
        nodes = [node for node in ast.parse(path.read_text()).body
                 if isinstance(node, ast.FunctionDef) and node.name == name]
        if len(nodes) != 1:
            raise ValueError("missing unique projection function")
        return ast.dump(nodes[0], include_attributes=False)
    if function_ast(ROOT / "src/smt_fullfab/runner.py", "crop_plan") != function_ast(
            parent / "source_snapshot/src/smt_fullfab/runner.py", "crop_plan"):
        raise ValueError("observation projection differs from parent")


def verify_recovery_package(package_path, ledger_path=None):
    """Recheck the package, entire parent inventory and immutable ledger prefix."""
    package_path = Path(package_path).resolve()
    package = _read(package_path)
    identity = package.get("package_sha256")
    if _record_digest({k: v for k, v in package.items() if k != "package_sha256"}) != identity:
        raise ValueError("recovery package identity mismatch")
    if (package.get("status") != "prepared" or package.get("errors")
            or package.get("plan_index") != 0 or package.get("resource_exhausted")
            or not package.get("controller_evidence_audit", {}).get("valid")
            or not package.get("checkpoint_verification", {}).get("valid")):
        raise ValueError("package is not a certified available cold-plan recovery")
    parent = Path(package["parent_run"]).resolve()
    if _inventory(parent) != package["parent_evidence"]:
        raise ValueError("parent evidence inventory changed")
    prefix = package["ledger_prefix"]
    ledger_path = Path(ledger_path or prefix["path"]).resolve()
    if ledger_path != Path(prefix["path"]).resolve():
        raise ValueError("recovery must retain its original ledger")
    ledger_bytes = ledger_path.read_bytes()
    saved_prefix = ledger_bytes[:prefix["bytes"]]
    rows = [json.loads(line) for line in saved_prefix.splitlines() if line.strip()]
    if (len(saved_prefix) != prefix["bytes"] or hashlib.sha256(saved_prefix).hexdigest() != prefix["sha256"]
            or len(rows) != prefix["records"] or _record_digest(rows) != prefix["canonical_sha256"]):
        raise ValueError("ledger prefix differs from recovery package")
    cfg, result = _read(parent / "config.json"), _read(parent / "result.json")
    _dead_claim(parent, cfg)
    if (cfg.get("arm") != "B" or result.get("identity") != digest(cfg)
            or result.get("status") != "failed" or result.get("full_window_completed") is not False
            or result.get("simulation_seconds") != 0 or result.get("plans_committed") != 0):
        raise ValueError("only a terminated failed first B plan at t=0 is supported")
    if (cfg.get("plan_seconds"), cfg.get("lookahead_depth"), cfg.get("period_seconds")) != (14400, 2, 1800):
        raise ValueError("parent rolling configuration differs from supported recovery")
    registration = package["original_registration"]
    registered = [row["registration"] for row in rows if row.get("event") == "stage_run_registered"
                  and row["registration"].get("run_id") == str(parent)]
    if registered != [registration] or registration.get("arm") != "B":
        raise ValueError("original registration differs from ledger prefix")
    snapshot = _read(parent / "checkpoint.json")
    state = snapshot["state"]
    if (digest(state) != snapshot["state_sha256"] or snapshot["state_sha256"] != package["checkpoint_state_sha256"]
            or state.get("t") != 0 or state.get("finished") is not False or state.get("plan") is not None
            or state.get("executed_tasks") or state.get("plan_versions")):
        raise ValueError("checkpoint is not the original untouched cold state")
    problem, manifest = _read(parent / "problem_000.json"), _read(parent / "page_manifest_000.json")
    if digest(problem) != package["problem_sha256"] or digest(manifest) != package["manifest_sha256"]:
        raise ValueError("first observation identity differs")
    pages = [_read(parent / f"page_000_{index:02d}.json") for index in range(package["page_count"])]
    if expand_pages(manifest, pages) != problem:
        raise ValueError("original pages do not reconstruct the full problem")
    schema, prompt = frozen_B_contract(parent)
    accepted = package["accepted_pages"]
    next_page = package["next_page"]
    if (type(next_page) is not int or not 0 <= next_page < len(pages)
            or [row["page_index"] for row in accepted] != list(range(next_page))
            or package["next_model_index"] != result["model_calls"]):
        raise ValueError("unsupported complete-plan or noncontiguous recovery cursor")
    staged, holds = [], []
    for row in accepted:
        path = parent / f"patch_000_{row['page_index']:02d}.json"
        response = _read(path)
        model = _read(parent / f"model_{row['model_index']:03d}/result.json")
        errors = validate_page(problem, pages[row["page_index"]], response, staged, holds,
                               schema, row["page_index"], len(pages), manifest["observation_end"])
        if (errors or response != model.get("output") or row["call_id"] != model.get("call_id")
                or row["patch_sha256"] != digest(response) or row["patch_file_sha256"] != sha_file(path)):
            raise ValueError("accepted parent page differs from validated original response")
        staged += response["tasks"]
        holds += response["holds"]
        if row["cumulative_staged_sha256"] != digest(staged) or row["cumulative_holds_sha256"] != digest(holds):
            raise ValueError("accepted parent cumulative hash mismatch")
    if (staged != package["staged_tasks"] or holds != package["staged_holds"]
            or digest(staged) != package["staged_sha256"] or digest(holds) != package["holds_sha256"]):
        raise ValueError("package staged choices differ from accepted pages")
    _verify_runtime_compatibility(parent)
    return package, parent, cfg, problem, manifest, pages, schema, prompt, ledger_path


def validate_page(problem, page, response, staged, holds, schema, page_index, page_count, observation_end):
    errors = _schema_errors(response, schema)
    if errors:
        return errors
    allowed = {row[0] for group in page for row in group["operations"]}
    outside = sorted({oid for task in response["tasks"] for oid in task["operations"] if oid not in allowed})
    if outside:
        errors.append("patch references operations outside the supplied page: " + json.dumps(outside))
    if response["commit"] != (page_index == page_count - 1):
        errors.append("explicit commit before all pages" if response["commit"] else "final page lacks explicit commit")
    errors += _choice_errors(problem, staged + response["tasks"], holds + response["holds"], observation_end)
    return sorted(set(errors))


def page_prompt(base, manifest, page, staged, index, remaining_responses, feedback=None):
    metadata = {**manifest, "page_index": index, "last_page": index == manifest["page_count"] - 1,
                "remaining_model_responses": remaining_responses}
    predecessors = {oid for group in page for row in group["operations"] for oid in row[3]}
    mids = {row[0] for group in page for row in group["machines"]}
    prior = [task for task in staged if task["machine"] in mids or any(oid in predecessors for oid in task["operations"])]
    prompt = base + "\nSCHEMA_AND_LIMITS\n" + json.dumps(metadata, separators=(",", ":"))
    prompt += "\nPAGE\n" + json.dumps(page, separators=(",", ":"))
    prompt += "\nYOUR_PRIOR_PREDECESSOR_CHOICES\n" + json.dumps(prior, separators=(",", ":"))
    if feedback is not None:
        prompt += "\n" + FEEDBACK_SECTION + "\n" + json.dumps(feedback, separators=(",", ":"))
    return prompt


def revision_feedback(page_index, call_id, output, errors):
    return {"revision_scope": "replace_this_page_only", "page_index": page_index,
            "rejected_call_id": call_id, "rejected_output_sha256": digest(output),
            "rejected_output": output, "validation_errors": errors,
            "instruction": "Return a fresh complete patch for this page; do not edit prior accepted pages."}


def _segment_call_ids(ledger, out):
    with ledger._locked() as rows:
        return [row["call_id"] for row in rows if row.get("event") == "reserve"
                and Path(row.get("run_id", "")).parent.resolve() == out]


def _directory_bytes(out):
    return sum(path.stat().st_size for path in out.rglob("*") if path.is_file())


def _audit_completed_segment(out, ledger_path):
    # Independent implementation owned by the audit module; imported only when
    # the immutable result and segment-finish ledger event are available.
    from .controller_resume_audit import audit_controller_resume
    return audit_controller_resume(out, ledger_path)


def _verify_protocol(path, package_path, package, parent, out, cfg, page_cap, plan_cap):
    if path is None:
        raise ValueError("an explicit preregistered recovery protocol is required")
    protocol = _read(path)
    expected = {"schema": "smt-fullfab-B-recovery-protocol-v1", "parent_run_id": str(parent),
                "segment_run_id": str(out), "package_identity_sha256": package["package_sha256"],
                "recovery_package_sha256": sha_file(package_path), "model": "gpt-6-astra",
                "reasoning_effort": "medium", "per_call_timeout_seconds": 180,
                "plan_seconds": cfg["plan_seconds"], "lookahead_depth": cfg["lookahead_depth"],
                "period_seconds": cfg["period_seconds"], "wall_seconds": cfg["wall_seconds"],
                "max_log_bytes": cfg["max_log_bytes"], "max_calls": cfg["max_calls"],
                "max_reported_tokens": None, "max_revisions_per_page": page_cap,
                "max_revisions_per_plan": plan_cap}
    if any(protocol.get(key) != value or key not in protocol for key, value in expected.items()):
        raise ValueError("preregistered recovery protocol differs from original scope or requested caps")
    return protocol


def run(recovery_package_path, segment_run_id, *, ledger_path=None, protocol_path=None,
        max_revisions_per_page=1, max_revisions_per_plan=3):
    """Start one new segment; no in-place rerun/retry or nonzero-state resume."""
    started = time.monotonic()
    for value, cap in ((max_revisions_per_page, 1), (max_revisions_per_plan, 3)):
        if type(value) is not int or not 0 <= value <= cap:
            raise ValueError("revision limits must be integer <=1 per page and <=3 per plan")
    if not segment_run_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in segment_run_id):
        raise ValueError("invalid recovery segment name")
    out = (ROOT / "runs/smt_fullfab_stage2" / segment_run_id).resolve()
    if out.exists():
        raise FileExistsError("existing recovery segment preserved; repeated calls and later-state resume are unsupported")
    package, parent, original_cfg, first_problem, first_manifest, first_pages, schema, base, ledger_path = verify_recovery_package(recovery_package_path, ledger_path)
    if segment_run_id != parent.name + "__recovery_001":
        raise ValueError("only the first direct recovery segment is supported; later segments need new verified prefix support")
    protocol = _verify_protocol(protocol_path, recovery_package_path, package, parent, out, original_cfg,
                                max_revisions_per_page, max_revisions_per_plan)
    ledger = BudgetLedger(ledger_path)
    mapping = ledger.register_recovery_segment(str(parent), str(out), str(Path(recovery_package_path).resolve()))
    out.mkdir(parents=True)
    cfg = {**original_cfg, "run_id": segment_run_id, "parent_run_id": str(parent),
           "recovery_version": VERSION, "recovery_package_sha256": sha_file(recovery_package_path),
           "package_identity_sha256": package["package_sha256"],
           "max_revisions_per_page": max_revisions_per_page, "max_revisions_per_plan": max_revisions_per_plan,
           "protocol_path": str(Path(protocol_path).resolve()), "protocol_sha256": sha_file(protocol_path),
           "frozen_B_schema_sha256": digest(schema), "frozen_B_prompt_sha256": hashlib.sha256(base.encode()).hexdigest(),
           "continuation_support": "one new cold segment only; existing/nonzero segments cannot be resumed"}
    identity = digest(cfg)
    write_new(out / "config.json", cfg)
    write_new(out / "claim.json", {"pid": os.getpid(), "identity": identity})
    write_new(out / "recovery_mapping.json", mapping)
    write_new(out / "recovery_package.json", package)
    write_new(out / "protocol.json", protocol)
    env = None
    plan_count = 0
    next_model = package["next_model_index"]
    state_serial = 0
    status, failure, audit = "failed", None, None
    models, accepted, staged, holds = [], [], [], []
    page_index, revisions, page_revisions = package["next_page"], 0, {}
    stage = "registered"

    def elapsed():
        return time.monotonic() - started

    def check_resources():
        account = ledger.summary(run_id=str(out))
        remaining = min(original_cfg["wall_seconds"] - mapping["inherited"]["runner_wall_seconds"] - elapsed(),
                        original_cfg["wall_seconds"] - account["model_active_seconds"])
        if remaining < 1:
            raise TimeoutError("inherited cumulative runner/model wall limit exhausted")
        if mapping["inherited"]["log_bytes"] + _directory_bytes(out) >= original_cfg["max_log_bytes"]:
            raise RuntimeError("inherited cumulative log byte cap")
        if original_cfg.get("max_calls") is not None and package["consumption"]["model_attempts"] + len(models) >= original_cfg["max_calls"]:
            raise RuntimeError("inherited model attempt cap")
        return remaining

    def progress(label):
        nonlocal state_serial
        row = {"schema": VERSION, "stage": label, "plan_index": plan_count, "next_page": page_index,
               "next_model_index": next_model, "simulation_seconds": env.t if env is not None else 0,
               "accepted_pages": deepcopy(accepted), "staged_sha256": digest(staged), "holds_sha256": digest(holds),
               "plan_revisions": revisions, "page_revisions": page_revisions,
               "segment_wall_seconds": elapsed(), "inherited": mapping["inherited"],
               "resume_supported": False, "purpose": "inspection only; later-state execution not implemented"}
        write_new(out / f"recovery_state_{state_serial:05d}.json", row)
        state_serial += 1
        return row

    try:
        write_new(out / "provenance.json", source_snapshot(out))
        write_new(out / "frozen_B_contract.json", {"schema": schema, "prompt": base,
                   "parent_controller_sha256": sha_file(parent / "source_snapshot/src/smt_fullfab/controller.py")})
        check_resources()
        env = FullFabEnvironment.from_snapshot(parent / "checkpoint.json", trace_path=out / "trace.jsonl")
        env.snapshot(out / "restored_cold_checkpoint.json")
        restored = _read(out / "restored_cold_checkpoint.json")["state"]
        event = restored["trace"].pop()
        if event.get("kind") != "snapshot_loaded" or digest(restored) != package["checkpoint_state_sha256"]:
            raise ValueError("restoration changed original complete physical state")
        if digest(env.problem(plan_seconds=14400, lookahead_depth=2)) != package["problem_sha256"]:
            raise ValueError("restored public observation differs from parent")
        saved_config = _read(parent / "model_000/request.json")["config"]
        mcfg = ModelConfig(**saved_config)
        if (mcfg.ledger_path != str(ledger_path) or mcfg.phase != mapping["phase"]
                or mcfg.grant_id != mapping["budget_id"]
                or mcfg.model != protocol["model"] or mcfg.reasoning_effort != protocol["reasoning_effort"]
                or mcfg.timeout_seconds != protocol["per_call_timeout_seconds"]
                or mcfg.authorization_context != {"purpose": "B", "arm": "B", "window_seconds": cfg["seconds"], "scenario": cfg["seed"]}):
            raise ValueError("original model configuration does not match registered recovery scope")
        while not env.finished:
            check_resources()
            problem = first_problem if plan_count == 0 else env.problem(plan_seconds=14400, lookahead_depth=2)
            if plan_count == 0:
                manifest, pages = deepcopy(first_manifest), deepcopy(first_pages)
                staged, holds = deepcopy(package["staged_tasks"]), deepcopy(package["staged_holds"])
                accepted = []
                for original in package["accepted_pages"]:
                    row = {**original, "event": "page_accepted", "plan_index": 0, "source_parent": True,
                           "patch_path": str(parent / f"patch_000_{original['page_index']:02d}.json")}
                    accepted.append(row)
                    _append(out / "page_accepted.jsonl", row)
                page_index = package["next_page"]
            else:
                manifest = compact_pages(problem, max_chars=cfg["page_chars"])
                pages = manifest.pop("pages")
                manifest["observation_end"] = env.horizon
                staged, holds, accepted = [], [], []
                page_index = 0
            if expand_pages(manifest, pages) != problem:
                raise ValueError("new observation pages are not lossless")
            write_new(out / f"problem_{plan_count:03d}.json", problem)
            write_new(out / f"page_manifest_{plan_count:03d}.json", manifest)
            for index, page in enumerate(pages):
                write_new(out / f"page_{plan_count:03d}_{index:02d}.json", page)
            revisions, page_revisions = 0, {}
            feedback = None
            if plan_count == 0 and package["failed_page_feedback"]:
                failed = package["failed_page_feedback"]
                if len(failed) != 1 or failed[0].get("page_index") != page_index or failed[0].get("kind") != "explicit_model_revision_required":
                    raise ValueError("this executor requires one diagnosed semantic page failure")
                old = _read(parent / f"model_{package['next_model_index']-1:03d}/result.json")
                if old["call_id"] != failed[0]["call_id"] or digest(old["output"]) != failed[0]["failed_output_sha256"]:
                    raise ValueError("failed output differs from explicit recovery feedback")
                errors = validate_page(problem, pages[page_index], old["output"], staged, holds, schema,
                                       page_index, len(pages), env.horizon)
                if not errors:
                    raise ValueError("original rejected page unexpectedly validates")
                feedback = revision_feedback(page_index, old["call_id"], old["output"], errors)
            progress("pages_ready")
            reason = ""
            while page_index < len(pages):
                stage = "page_request"
                remaining = check_resources()
                is_revision = feedback is not None
                if is_revision:
                    if page_revisions.get(page_index, 0) >= max_revisions_per_page or revisions >= max_revisions_per_plan:
                        raise RuntimeError("explicit model page/plan revision limit exhausted")
                    revisions += 1
                    page_revisions[page_index] = page_revisions.get(page_index, 0) + 1
                remaining_calls = None if cfg.get("max_calls") is None else cfg["max_calls"] - package["consumption"]["model_attempts"] - len(models)
                prompt = page_prompt(base, manifest, pages[page_index], staged, page_index, remaining_calls, feedback)
                model_index = next_model
                next_model += 1
                progress("model_attempt_pending")
                result = call_model(prompt, schema, out / f"model_{model_index:03d}",
                                    dataclasses.replace(mcfg, timeout_seconds=min(mcfg.timeout_seconds, remaining)))
                models.append(result)
                response = result.get("output")
                errors = (["model_channel:" + str(result.get("failure_reason"))] if result.get("status") != "success" else
                          validate_page(problem, pages[page_index], response, staged, holds, schema, page_index, len(pages), env.horizon))
                proposed_tasks = staged if errors else staged + response["tasks"]
                proposed_holds = holds if errors else holds + response["holds"]
                patch_path = out / f"patch_{plan_count:03d}_{page_index:02d}_{model_index:03d}.json"
                row = {"model_index": model_index, "call_id": result["call_id"], "plan_index": plan_count,
                       "page_index": page_index, "arm": "B", "stage": "B_page", "revision": is_revision,
                       "revision_number": page_revisions.get(page_index, 0), "input_problem_sha256": digest(problem),
                       "response_sha256": digest(response), "status": result["status"], "accepted": not errors,
                       "validation_errors": errors, "patch_sha256": digest(response) if not errors else None,
                       "cumulative_staged_sha256": digest(proposed_tasks), "cumulative_holds_sha256": digest(proposed_holds)}
                _append(out / "recovery_decisions.jsonl", row)
                if errors:
                    _append(out / "page_rejected.jsonl", {**row, "event": "page_rejected"})
                    progress("page_rejected")
                    if result["status"] != "success":
                        raise RuntimeError(errors[0])
                    feedback = revision_feedback(page_index, result["call_id"], response, errors)
                    continue
                write_new(patch_path, response)
                staged, holds = proposed_tasks, proposed_holds
                accepted_row = {**row, "event": "page_accepted", "source_parent": False,
                                "patch_path": str(patch_path), "patch_file_sha256": sha_file(patch_path)}
                _append(out / "page_accepted.jsonl", accepted_row)
                accepted.append(accepted_row)
                reason = response["reason"]
                page_index += 1
                feedback = None
                progress("page_accepted")
            stage = "plan_commit"
            check_resources()
            validate_choices(problem, staged)
            ordered = sorted(staged, key=lambda task: (task["machine"], task["sequence"]))
            plan = decode_plan(problem, {"tasks": ordered, "holds": holds, "reason": reason},
                               version=segment_run_id + ":" + str(plan_count))
            write_new(out / f"raw_plan_{plan_count:03d}.json", plan)
            committed = crop_plan(plan, env)
            write_new(out / f"committed_plan_{plan_count:03d}.json", committed)
            env.commit_plan(committed)
            _append(out / "plan_commits.jsonl", {"plan_index": plan_count,
                    "final_model_call_id": accepted[-1]["call_id"], "model_call_id": accepted[-1]["call_id"],
                    "source_page_call_ids": [row["call_id"] for row in accepted],
                    "raw_plan_sha256": digest(plan), "committed_plan_sha256": digest(committed)})
            plan_count += 1
            progress("plan_committed")
            stage = "physical_execution"
            env.advance_plan(min(env.horizon, env.t + cfg["period_seconds"]))
            progress("physical_execution_stopped")
            check_resources()
        status = "success"
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
        (out / "exception.txt").write_text(traceback.format_exc(), encoding="utf-8")
    checkpoint_error = None
    try:
        if env is not None:
            env.snapshot(out / "checkpoint.json")
        else:
            shutil.copyfile(parent / "checkpoint.json", out / "checkpoint.json")
    except Exception as exc:
        checkpoint_error = f"{type(exc).__name__}: {exc}"
        status, failure = "failed", failure or "checkpoint_failed:" + checkpoint_error
    progress("finished" if status == "success" else "failed:" + stage)
    if env is not None and (out / "trace.jsonl").exists():
        try:
            audit = audit_trace(out / "trace.jsonl", verify_data_dir=env.data_dir)
        except Exception as exc:
            audit = {"valid": False, "errors": [f"{type(exc).__name__}: {exc}"], "metrics": None}
        write_new(out / "audit.json", audit)
    if status == "success" and not (audit and audit.get("valid")):
        status, failure = "failed", "independent_physical_audit_failed"
    if (mapping["inherited"]["runner_wall_seconds"] + elapsed() > original_cfg["wall_seconds"]
            or mapping["inherited"]["log_bytes"] + _directory_bytes(out) > original_cfg["max_log_bytes"]):
        status, failure = "failed", failure or "inherited resource limit exceeded during finalization"
    calls = _segment_call_ids(ledger, out)
    result = {"schema": "smt-fullfab-B-recovery-result-v1", "identity": identity, "config": cfg, "status": status, "failure": failure,
              "parent_run_id": str(parent), "segment_run_id": str(out),
              "recovery_segment_id": mapping["recovery_segment_id"], "registration_id": mapping["registration_id"],
              "plans_committed": plan_count, "simulation_seconds": env.t if env is not None else 0,
              "full_window_completed": bool(env is not None and env.finished),
              "model_calls": len(calls), "model_call_ids": calls, "solver_calls": 0, "solver_requested_seconds": 0,
              "wall_seconds": elapsed(), "inherited_consumption": mapping["inherited"],
              "cumulative_model_account": ledger.summary(run_id=str(out)),
              "cumulative_runner_wall_seconds": mapping["inherited"]["runner_wall_seconds"] + elapsed(),
              "cumulative_log_bytes_before_result": mapping["inherited"]["log_bytes"] + _directory_bytes(out),
              "audit_valid": bool(audit and audit.get("valid")), "metrics": audit.get("metrics") if audit else None,
              "checkpoint_error": checkpoint_error, "controller_evidence_audit_status": "pending_post_finish_audit",
              "later_state_resume_supported": False, "cost_usd": None, "formal": False}
    write_new(out / "result.json", result)
    finish_error = None
    try:
        ledger.report_recovery_segment_finish(str(out), str(out / "result.json"))
    except Exception as exc:
        finish_error = f"{type(exc).__name__}: {exc}"
    try:
        recovered_audit = _audit_completed_segment(out, ledger_path) if finish_error is None else {
            "valid": False, "errors": ["segment finish failed: " + finish_error], "missing_evidence": []}
    except Exception as exc:
        recovered_audit = {"valid": False, "errors": [f"{type(exc).__name__}: {exc}"], "missing_evidence": []}
    write_new(out / "recovery_audit.json", recovered_audit)
    physical_success = status == "success" and result["full_window_completed"] and result["audit_valid"]
    final_wall = elapsed()
    accepted_success = bool(physical_success and recovered_audit.get("valid")
                            and recovered_audit.get("successful_full_window"))
    acceptance = {"schema": "smt-fullfab-recovery-acceptance-v1",
                  "parent_run_id": str(parent), "segment_run_id": str(out),
                  "registration_id": mapping["registration_id"], "recovery_segment_id": mapping["recovery_segment_id"],
                  "accepted": accepted_success,
                  "status": "success" if accepted_success else "failed",
                  "successful_full_window": accepted_success,
                  "physical_success": physical_success, "controller_evidence_valid": bool(recovered_audit.get("valid")),
                  "result_sha256": sha_file(out / "result.json"), "recovery_audit_sha256": sha_file(out / "recovery_audit.json"),
                  "segment_finish_error": finish_error,
                  "segment_final_wall_seconds": final_wall,
                  "cumulative_final_wall_seconds": mapping["inherited"]["runner_wall_seconds"] + final_wall,
                  "cumulative_log_bytes_including_acceptance": 0, "resource_overrun": False}
    prior_bytes = mapping["inherited"]["log_bytes"] + _directory_bytes(out)
    for _ in range(6):
        total = prior_bytes + len((json.dumps(acceptance, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
        overrun = (total > cfg["max_log_bytes"] or acceptance["cumulative_final_wall_seconds"] > cfg["wall_seconds"])
        if total == acceptance["cumulative_log_bytes_including_acceptance"] and overrun == acceptance["resource_overrun"]:
            break
        acceptance["cumulative_log_bytes_including_acceptance"] = total
        acceptance["resource_overrun"] = overrun
        if overrun:
            acceptance.update(status="failed", accepted=False, successful_full_window=False)
    write_new(out / "acceptance.json", acceptance)
    finalization_error = None
    try:
        ledger.report_recovery_segment_finalization(str(out), str(out / "acceptance.json"))
    except Exception as exc:
        finalization_error = f"{type(exc).__name__}: {exc}"
        write_new(out / "resource_finalization_error.json", {"error": finalization_error})
    return {**result, "physical_result_status": result["status"],
            "status": "failed" if finalization_error else acceptance["status"],
            "acceptance": acceptance, "resource_finalization_error": finalization_error}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recovery_package_path")
    parser.add_argument("--segment-run-id", required=True)
    parser.add_argument("--ledger", dest="ledger_path")
    parser.add_argument("--protocol", dest="protocol_path", required=True)
    parser.add_argument("--max-revisions-per-page", type=int, default=1)
    parser.add_argument("--max-revisions-per-plan", type=int, default=3)
    result = run(**vars(parser.parse_args()))
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
