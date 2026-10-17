"""Preregistered, serial P5 runner. Preparation never calls a model."""
import argparse
from pathlib import Path
import time
import zlib

from .contracts import ROOT, default_config, digest, encode, fingerprint, require, sha_bytes, strict_json, within_cap
from .evaluation import audit_run, microbenchmark_gate, seal_evidence
from .experiment import CAPS, checked_file, continuation_authorization, cumulative_usage, sealed_prior, resource_status
from .legacy import load_fragment
from .runtime import Runtime

LEGACY_ROOT = ROOT / "runs/smt_fullfab_stage2/B_1701_1h_delta_v14__candidate_paths_001"
CASE_NUMBERS = (1, 2, 3, 4, 5, 7, 9, 10, 13, 14, 15, 21, 22, 24, 25, 26, 27, 28, 29, 30)
TASK = "Revise the existing full-responsibility plan in response to the recorded trigger, using only current public facts. Preserve valid commitments. Make your own explicit production decisions, then explicitly select the checked candidate. The task ends when one revised plan is accepted."


def prepare(directory, authorization=None, prior_cost_evidence=None):
    directory = Path(directory).resolve()
    auth_ref = ({"path": str(Path(authorization).resolve()), "sha256": sha_bytes(Path(authorization).read_bytes())}
                if authorization is not None else None)
    grant = continuation_authorization(auth_ref) if auth_ref else None
    caps = grant["caps"] if grant else CAPS
    directory.mkdir(parents=True, exist_ok=False)
    cases = {}
    for index, number in enumerate(CASE_NUMBERS, 1):
        case = "micro-" + str(index).zfill(2)
        fragment = load_fragment(LEGACY_ROOT / ("plan_" + str(number).zfill(5)))
        require(fragment["edits"] <= 5, "sampling_rule", "Preregistered historical small revision differs")
        initial = fragment["initial"]
        config = default_config(seconds=initial["state"]["horizon"] - initial["state"]["t"])
        config["initialization"] = "registered_saved_state"
        if grant:
            config["unknown_usage_policy"] = grant.get("unknown_usage_policy", "freeze_new_calls")
            if grant["schema"] in ("harness-user-continuation-20261014-v5", "harness-user-continuation-20261014-v6", "harness-user-continuation-20261014-v7"):
                config["model"]["timeout_seconds"] = 180
        config["limits"].update(caps["micro"])
        config["limits"]["cleanup_seconds"] = 600
        (directory / (case + ".initial.json.z")).write_bytes(zlib.compress(encode(initial), 6))
        (directory / (case + ".config.json")).write_bytes(encode(config))
        cases[case] = {"group": "micro", "config_sha256": digest(config), "initial_state_sha256": digest(initial["state"]),
                       "initial_trace_sha256": digest(initial["trace"]), "sources": fragment["sources"],
                       "legacy_plan_number": number, "preexisting_expected_edits": fragment["edits"],
                       "task": TASK, "max_attempts_per_fragment": grant.get("max_attempts_per_fragment", 10) if grant else 10}
        print(encode({"prepared": case, "time": initial["state"]["t"]}).decode(), flush=True)
    config = default_config()
    if grant:
        config["unknown_usage_policy"] = grant.get("unknown_usage_policy", "freeze_new_calls")
    config["limits"].update(caps["B3600"])
    (directory / "B3600.config.json").write_bytes(encode(config))
    cases["B3600"] = {"group": "B3600", "config_sha256": digest(config), "initial_state_sha256": None}
    manifest = {"schema": "harness-p5-preparation-v1", "cases": cases, "prepared_epoch": time.time(),
                "sampling_rule": "First 20 chronological V14 fragments with a saved existing baseline and preexisting explicit adjustment of at most five task/hold edits. Selection uses archived task/trigger/decision difficulty before any new model result; all new outcomes retained.",
                "new_model_calls": 0, "answers_to_model": False}
    if grant:
        manifest["authorization"] = auth_ref
        manifest["prior_cost_evidence"] = ({"path": str(Path(prior_cost_evidence).resolve()), "sha256": sha_bytes(Path(prior_cost_evidence).read_bytes())}
                                           if prior_cost_evidence else grant["prior_cost_evidence"])
        sealed_prior(manifest)
        validate_same_cohort(directory, manifest)
    (directory / "preparation.json").write_bytes(encode(manifest))
    return manifest


def validate_same_cohort(directory, prep):
    snapshot = checked_file(prep["prior_cost_evidence"])
    previous = checked_file(snapshot["original_registration"])
    old_root = Path(snapshot["original_registration"]["path"]).parent
    old_cases = {k: v for k, v in previous["cases"].items() if v["group"] == "micro"}
    new_cases = {k: v for k, v in prep["cases"].items() if v["group"] == "micro"}
    require(len(old_cases) == 20 and set(old_cases) == set(new_cases), "same_cohort", "Exactly the same twenty fragment identities required")
    for case, entry in new_cases.items():
        omitted = {"config_sha256"}
        grant = continuation_authorization(prep["authorization"]) if "authorization" in prep else None
        if grant and grant["schema"] in ("harness-user-continuation-20261014-v2", "harness-user-continuation-20261014-v3", "harness-user-continuation-20261014-v4", "harness-user-continuation-20261014-v5", "harness-user-continuation-20261014-v6", "harness-user-continuation-20261014-v7"):
            require(entry["max_attempts_per_fragment"] is None, "case_budget", "Removed fragment count ceiling must be explicit")
            omitted.add("max_attempts_per_fragment")
        require({k: v for k, v in entry.items() if k not in omitted} ==
                {k: v for k, v in old_cases[case].items() if k not in omitted},
                "same_cohort", "Initial state, trace, task or selection changed: " + case)
        require(zlib.decompress((Path(directory) / (case + ".initial.json.z")).read_bytes()) ==
                zlib.decompress((old_root / (case + ".initial.json.z")).read_bytes()),
                "same_cohort", "Full initial artifact differs: " + case)


def register(directory, report, cli_binary, preflight):
    directory, report, cli_binary, preflight = map(lambda p: Path(p).resolve(), (directory, report, cli_binary, preflight))
    prep = strict_json((directory / "preparation.json").read_bytes())
    grant = continuation_authorization(prep["authorization"]) if "authorization" in prep else None
    if grant:
        validate_same_cohort(directory, prep)
    gates = strict_json(report.read_bytes())
    fp = fingerprint()
    require(gates["fingerprint_sha256"] == fp["sha256"] and all(gates["gates"][g] == "pass" for g in ("G0", "G1", "G2", "G3", "G4")), "P5_admission", "Frozen G0-G4 proof required")
    probe = strict_json(preflight.read_bytes())
    require(probe["returncode"] == 0 and probe["tools"] == [] and probe["requests"] == 1, "cli_preflight", "Offline actual CLI request must demonstrate no native tools")
    require(probe["cli_sha256"] == sha_bytes(cli_binary.read_bytes()) and
            probe["transport_source_sha256"] == fp["files"]["src/smt_fullfab/harness/transport.py"],
            "cli_preflight_version", "CLI or transport changed since the actual local probe")
    value = {"schema": "harness-p5-registration-v1", "registered_epoch": time.time(), "cases": prep["cases"],
             "sampling_rule": prep["sampling_rule"], "preparation_sha256": digest(prep), "caps": CAPS, "full_B_new_run_limit": 1,
             "fingerprint_sha256": fp["sha256"], "engineering_report": str(report), "engineering_report_sha256": sha_bytes(report.read_bytes()),
             "cli_binary": str(cli_binary), "cli_sha256": sha_bytes(cli_binary.read_bytes()),
             "cli_preflight": str(preflight), "cli_preflight_sha256": sha_bytes(preflight.read_bytes()),
             "model_catalog": str(ROOT / "configs/smt_fullfab/harness_v1/model_catalog.json"),
             "model_catalog_sha256": sha_bytes((ROOT / "configs/smt_fullfab/harness_v1/model_catalog.json").read_bytes()),
             "micro_metrics": {"n_min": 20, "median_max": 3, "p95_max": 5, "p95_method": "sorted ceil(0.95*n), one-based", "failures_excluded": False},
             "provider_policy": "Existing Codex login to official ChatGPT Codex endpoint; custom provider alias solely to set request/stream retries=0; no credentials copied",
             "token_cap": "reported usage plus conservative reservations, not an exact server token cap",
             "frozen_version_policy": "Source changes stop the experiment; no new full B run after a failed start"}
    if grant:
        schema = ("harness-p5-registration-v9" if grant["schema"] == "harness-user-continuation-20261014-v7" else
                  "harness-p5-registration-v8" if grant["schema"] == "harness-user-continuation-20261014-v6" else
                  "harness-p5-registration-v7" if grant["schema"] == "harness-user-continuation-20261014-v5" else
                  "harness-p5-registration-v6" if grant["schema"] == "harness-user-continuation-20261014-v4" else
                  "harness-p5-registration-v5" if grant["schema"] == "harness-user-continuation-20261014-v3" else
                  "harness-p5-registration-v4" if grant["schema"] == "harness-user-continuation-20261014-v2" else
                  "harness-p5-registration-v3" if prep["prior_cost_evidence"] != grant["prior_cost_evidence"] else "harness-p5-registration-v2")
        if schema == "harness-p5-registration-v9":
            value["execution_order"] = grant["micro_execution_order"]
        value.update(schema=schema, caps=grant["caps"],
                     authorization=prep["authorization"], prior_cost_evidence=prep["prior_cost_evidence"])
        if schema in ("harness-p5-registration-v7", "harness-p5-registration-v8", "harness-p5-registration-v9", "harness-model-switch-registration-v1"):
            value["experiment_directory"] = str(directory)
            value["recovery_policy"] = grant["recovery_policy"]
        carried, used_full_starts, _ = sealed_prior(value)
        require(used_full_starts == 0, "full_run_quota", "The authorized single fresh B run is already used")
        value["carried_usage_at_registration"] = carried
    with (directory / "experiment.json").open("xb") as stream:
        stream.write(encode(value))
    return value


def admission_for(directory, case):
    directory = Path(directory).resolve()
    raw = (directory / "experiment.json").read_bytes()
    reg = strict_json(raw)
    return {"experiment_directory": str(directory), "experiment_sha256": sha_bytes(raw), "group": reg["cases"][case]["group"],
            "case_id": case, "cli_binary": reg["cli_binary"], "cli_sha256": reg["cli_sha256"],
            "model_catalog": reg["model_catalog"], "model_catalog_sha256": reg["model_catalog_sha256"]}


def open_case(directory, case):
    directory = Path(directory).resolve()
    from .amendment import case_directory
    target = case_directory(directory, case)
    target.parent.mkdir(exist_ok=True)
    if target.exists():
        return Runtime.resume_run(target)
    initial_path = directory / (case + ".initial.json.z")
    initial = strict_json(zlib.decompress(initial_path.read_bytes())) if initial_path.exists() else None
    config = strict_json((directory / (case + ".config.json")).read_bytes())
    return Runtime.start_new(target, config, experiment_id=directory.name, mode="model", initial=initial, admission=admission_for(directory, case))


def micro(directory, count=None):
    directory = Path(directory).resolve()
    reg = strict_json((directory / "experiment.json").read_bytes())
    from .amendment import case_directory, amendment_for, effective_micro_metrics
    metrics = effective_micro_metrics(reg)
    hard_counts = metrics['enforcement'] == 'hard'
    ran = 0
    def latency_impossible():
        if not hard_counts:
            return False
        if reg.get("schema") not in ("harness-p5-registration-v7", "harness-p5-registration-v8", "harness-p5-registration-v9", "harness-model-switch-registration-v1"):
            return False
        paths = [case_directory(directory, c) / "fragment_result.json" for c,e in reg["cases"].items() if e["group"] == "micro"]
        completed = [strict_json(p.read_bytes()) for p in paths if p.exists()]
        return sum(r["attempts"] > 5 for r in completed) >= 2 or sum(r["attempts"] > 3 for r in completed) >= 11
    for case in reg.get("execution_order", list(reg["cases"])):
        entry = reg["cases"][case]
        if entry["group"] != "micro":
            continue
        target = case_directory(directory, case)
        if (target / "fragment_result.json").exists():
            if reg.get("schema") != "harness-p5-registration-v1" and not strict_json((target / "fragment_result.json").read_bytes())["accepted"]:
                break  # an explicit resume cannot skip a failed cohort member
            continue
        if (target / "evidence_manifest.json").exists():
            # Crash after sealing: independently finish the audit, never reopen
            # the run or allocate a second model account.
            sha = sha_bytes((target / "evidence_manifest.json").read_bytes())
            audit_path = target / "audit" / "acceptance.json"
            report = strict_json(audit_path.read_bytes()) if audit_path.exists() else audit_run(target, expected_sha256=sha, output_dir=target / "audit-recovered", scope="accepted_fragment")
            row = {"id": case, "attempts": report["cost_accounting"]["actual_attempts"], "accepted": report["valid"],
                   "commit_accepted": report["fragment_acceptance"], "audit_valid": report["valid"], "evidence_sha256": sha,
                   "recovered_after_seal": True, "error": report["errors"]}
            (target / "fragment_result.json").write_bytes(encode(row))
            if not row["accepted"]:
                break
            continue
        if count is not None and ran >= count:
            break
        if latency_impossible():
            break
        runtime = open_case(directory, case)
        try:
            from .transport import call
            while not runtime.store.rows("commits") and runtime.head["phase"] not in ("COMMITTED", "STOPPED", "CLOSED", "AUDITING"):
                # Include the next actual call before dispatch, not only sealed
                # fragments. One existing >5 plus a second sixth call makes the
                # registered 19th order statistic impossible regardless of output.
                completed_paths = [case_directory(directory, c) / "fragment_result.json"
                                   for c,e in reg["cases"].items() if e["group"] == "micro" and c != case]
                counts = [strict_json(p.read_bytes())["attempts"] for p in completed_paths if p.exists()]
                if hard_counts and len(reg["cases"]) == 21 and sum(n > 5 for n in counts) + (runtime.usage()["actual_model_attempts"] + 1 > 5) >= 2:
                    runtime.stop("registered_P95_impossible_before_next_call")
                    break
                if hard_counts and not within_cap(runtime.usage()["actual_model_attempts"] + 1, entry["max_attempts_per_fragment"]):
                    runtime.stop("fragment_attempt_limit")
                    break
                try:
                    result = call(runtime, task=entry["task"])
                    print(encode({"case": case, "result": result, "usage": runtime.usage()}).decode(), flush=True)
                except Exception as exc:
                    runtime.stop("fragment_error:" + str(exc))
                    break
            accepted = len(runtime.store.rows("commits")) == 1
            if accepted:
                if runtime.head["phase"] == "COMMITTED":
                    runtime.advance()  # separate post-acceptance physical evidence, no model attempt
                runtime.stop("registered_fragment_accepted")
            elif runtime.head["phase"] not in ("STOPPED", "CLOSED"):
                runtime.stop("fragment_incomplete")
            usage = runtime.usage()
            sha = seal_evidence(runtime)
            report = audit_run(target, expected_sha256=sha, output_dir=target / "audit", scope="accepted_fragment")
            row = {"id": case, "attempts": usage["actual_model_attempts"], "accepted": accepted and report["valid"],
                   "commit_accepted": accepted, "audit_valid": report["valid"], "evidence_sha256": sha,
                   "usage": usage, "error": report["errors"]}
            (target / "fragment_result.json").write_bytes(encode(row))
            print(encode({"fragment": row}).decode(), flush=True)
            ran += 1
            if (usage["unknown_usage"] and reg.get("schema") not in ("harness-p5-registration-v7", "harness-p5-registration-v8", "harness-p5-registration-v9", "harness-model-switch-registration-v1")) or (reg.get("schema") != "harness-p5-registration-v1" and not row["accepted"]):
                break
            # With 20 retained samples, two counts above five already make the
            # registered nearest-rank P95 impossible. Do not spend on the rest.
            if latency_impossible():
                break
        finally:
            runtime.close()
    rows = []
    for case, entry in reg["cases"].items():
        if entry["group"] == "micro":
            result = case_directory(directory, case) / "fragment_result.json"
            rows.append(strict_json(result.read_bytes()) if result.exists() else {"id": case, "attempts": 0, "accepted": False, "not_completed": True})
    gate = {**microbenchmark_gate(rows, metrics=metrics), "fragments": rows, "registered_count": len(rows),
            "experiment_sha256": sha_bytes((directory / "experiment.json").read_bytes()),
            "usage": cumulative_usage(admission_for(directory, rows[0]["id"]))}
    revision = amendment_for(reg)
    if revision:
        gate["control_amendment_sha256"] = digest(revision)
        gate["retained_failed_segment"] = revision["sealed_failure"]
        gate["micro_metrics"] = metrics
    gate["cost_disclosure"] = resource_status(reg, gate["usage"])
    gate["resource_pass"] = all(all(within_cap(gate["usage"][group][k], v) for k, v in reg["caps"][group].items()) and
                                gate["cost_disclosure"]["unexempt_unknown_usage"][group] == 0 and gate["usage"][group]["pending"] == 0
                                for group in ("micro", "combined"))
    gate["completion_latency"] = {"median": gate["median"] if gate["complete"] else None,
                                  "p95": gate["p95_nearest_rank"] if gate["complete"] else None,
                                  "note": "All twenty must complete; failed/unstarted counts are not completion latencies"}
    gate["pass"] = gate["pass"] and gate["resource_pass"]
    if reg.get("schema") in ("harness-p5-registration-v7", "harness-p5-registration-v8", "harness-p5-registration-v9", "harness-model-switch-registration-v1"):
        gate["latency_gate_already_impossible"] = latency_impossible()
    # Atomic projection from retained fragment reports; later runs can complete
    # pending fragments, but can never replace a recorded failed fragment.
    temporary = directory / "micro_gate.next.json"
    temporary.write_bytes(encode(gate))
    temporary.replace(directory / "micro_gate.json")
    return gate


def full(directory):
    from .__main__ import run_loop
    target = Path(directory) / "runs/B3600"
    if (target / "evidence_manifest.json").exists():
        sha = sha_bytes((target / "evidence_manifest.json").read_bytes())
        return audit_run(target, expected_sha256=sha)
    runtime = open_case(directory, "B3600")
    try:
        try:
            run_loop(runtime)
        except Exception as exc:
            runtime.stop("full_run_error:" + str(exc))
        sha = seal_evidence(runtime)
        return audit_run(runtime.store.path, expected_sha256=sha, output_dir=runtime.store.path / "audit")
    finally:
        runtime.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("prepare", "register", "micro", "full"))
    p.add_argument("directory", type=Path)
    p.add_argument("--engineering-report", type=Path)
    p.add_argument("--cli-binary", type=Path)
    p.add_argument("--preflight", type=Path)
    p.add_argument("--count", type=int)
    p.add_argument("--authorization", type=Path, help="Explicit continuation grant, frozen with prior closed costs")
    p.add_argument("--prior-cost-evidence", type=Path, help="All already closed cohorts; cannot omit the grant's original costs")
    args = p.parse_args()
    if args.command == "prepare": result = prepare(args.directory, args.authorization, args.prior_cost_evidence)
    elif args.command == "register": result = register(args.directory, args.engineering_report, args.cli_binary, args.preflight)
    elif args.command == "micro": result = micro(args.directory, args.count)
    else: result = full(args.directory)
    print(encode(result).decode(), flush=True)


if __name__ == "__main__":
    main()
