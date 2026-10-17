"""Explicit B-only model switch; previous micro scores retain their model identity."""
from copy import deepcopy
from pathlib import Path

from .contracts import digest, require, sha_bytes, strict_json, validate_config

SCHEMA = "harness-B-model-switch-registration-v1"
GRANT = "harness-B-model-switch-authorization-v1"
MODEL = {"name": "gpt-6-astra", "reasoning_effort": "medium"}
USER_INSTRUCTION = "先试试astra是否正常可以使用，如果可以使用使用astra来做B 实验"
ADDITIONAL = {"attempts": None, "tokens": None, "model_seconds": 10800, "wall_seconds": 14400}
CONTROL_FILES = {"src/smt_fullfab/harness/B_model_switch.py", "src/smt_fullfab/harness/experiment.py", "src/smt_fullfab/harness/recovery.py"}


def probe_cost(reference):
    """Verify the successful real probe from original guard and channel records."""
    from .experiment import checked_file, empty_usage
    from ..model_process_guard import INPUT_FILES, OUTPUT_FILES, verify_lifecycle
    from ..model_transport import summarize_events
    result = checked_file(reference)
    path = Path(reference["path"]).parent
    plan = strict_json((path / "plan.json").read_bytes())
    argv = strict_json((path / "command.json").read_bytes())["argv"]
    require(plan["user_instruction"] == USER_INSTRUCTION and plan["model"] == MODEL["name"]
            and plan["reasoning_effort"] == MODEL["reasoning_effort"] and plan["max_actual_calls"] == 1
            and plan["automatic_retries"] == 0 and plan["timeout_seconds"] == 90, "B_probe", "Probe differs from authorized model")
    require(argv[argv.index("--model") + 1] == MODEL["name"] and
            'model_reasoning_effort="medium"' in argv and sha_bytes(Path(argv[0]).read_bytes()) == plan["cli_sha256"],
            "B_probe", "Probe command differs")
    inputs = {n: sha_bytes((path / n).read_bytes()) for n in plan["inputs_sha256"]}
    require(inputs == plan["inputs_sha256"] and digest({"argv": argv, "inputs": inputs}) == plan["request_fingerprint"],
            "B_probe", "Probe inputs changed")
    io = {"cwd": str(path / "isolated-cwd"), "stdin": str(path / "prompt.txt"),
          "stdout": str(path / "events.jsonl"), "stderr": str(path / "stderr.log"),
          "inputs": {n: str(path / n) for n in (*INPUT_FILES, "model-catalog.json", "network.json")},
          "outputs": {n: str(path / n) for n in OUTPUT_FILES}}
    guard = verify_lifecycle(path, expected_command=argv, expected_timeout=90,
                             expected_call_id=plan["call_id"], expected_fingerprint=plan["request_fingerprint"], expected_io_spec=io)
    events = [strict_json(line) for line in (path / "events.jsonl").read_bytes().splitlines() if line.strip()]
    summary = summarize_events(events)
    usage = summary["usage"]
    require(guard["command_returncode"] == 0 and not guard["timed_out"] and summary["completed_turns"] == 1
            and not summary["native_tool_events"] and not summary["errors"]
            and all(type(usage.get(k)) is int for k in ("input_tokens", "output_tokens"))
            and strict_json((path / "final.txt").read_bytes()) == {"status": "ok", "value": 2},
            "B_probe", "A successful completed probe is required before Astra B")
    require(result["channel_success"] is True and result["unknown_usage"] is False
            and result["usage"] == usage and result["duration_seconds"] == guard["parent_wait_wall_seconds"]
            and result["call_id"] == plan["call_id"] and result["actual_calls"] == 1,
            "B_probe", "Probe summary differs from raw evidence")
    started = strict_json((path / "launch_once.json").read_bytes())["started_epoch"]
    require(result["ended_epoch"] >= started, "B_probe", "Probe clock reversed")
    totals = empty_usage()
    for group in ("B3600", "combined"):
        totals[group].update(attempts=1, tokens=usage["input_tokens"] + usage["output_tokens"],
                             model_seconds=result["duration_seconds"], wall_seconds=result["ended_epoch"] - started)
    return totals, plan["call_id"]


def carried_costs(reg):
    from .model_switch import carried_costs as historical_costs
    totals, starts, ids = historical_costs(reg)
    diagnostic, call_id = probe_cost(reg["successful_probe"])
    require(call_id not in ids, "B_probe_duplicate", "Probe already charged")
    totals, ids = deepcopy(totals), set(ids)
    for group in totals:
        for field in totals[group]:
            totals[group][field] += diagnostic[group][field]
    ids.add(call_id)
    return totals, starts, ids


def validate_grant(grant):
    from .experiment import checked_file
    from .amendment import effective_policy
    require(grant["schema"] == GRANT and grant["user_instruction"] == USER_INSTRUCTION
            and grant["model"] == MODEL and grant["additional_B_caps"] == ADDITIONAL,
            "B_model_grant", "Explicit conditional Astra B instruction required")
    previous = checked_file(grant["previous_registration"])
    require(previous["schema"] == "harness-model-switch-registration-v1", "B_model_grant", "Fixed predecessor required")
    require(grant["retain_failures_and_costs"] is True and grant["prior_micro_scores_are_target_model_scores"] is False
            and grant["new_micro_runs"] == 0 and grant["additional_B_starts"] == 1
            and grant["reset_recovery_count"] is False and grant["full_B_requires_zero_unknown"] is True
            and grant["unknown_usage_policy"] == "bounded_terminated_failures"
            and grant["recovery_policy"] == effective_policy(previous, previous["recovery_policy"])
            and grant["recovery_policy"]["max_failures_per_cohort"] == 30,
            "B_model_grant", "History, exception policy, or B scope changed")
    probe_cost(grant["successful_probe"])
    return grant


def validate_entry_gate(reg, gate):
    """An explicitly authorized cross-model entry, never an Astra micro score."""
    from .experiment import checked_file
    from .amendment import case_directory, validate_advisory_B_gate
    previous = checked_file(reg["previous_registration"])
    oldroot = Path(reg["previous_registration"]["path"]).parent
    oldgate = checked_file(reg["previous_micro_gate"])
    validate_advisory_B_gate(previous, oldgate)
    require(oldgate["complete"] and oldgate["correctness_pass"] and oldgate["pass"]
            and oldgate["registered_count"] == oldgate["n"] == 20,
            "B_entry", "All twenty original correctness results required")
    expected = {k for k, v in previous["cases"].items() if v["group"] == "micro"}
    require(set(gate["cases"]) == expected and len(expected) == 20 and gate["pass"] is True
            and gate["schema"] == "harness-cross-model-B-entry-v1"
            and gate["prior_micro_scores_are_target_model_scores"] is False
            and gate["micro_model"] == previous["model"] and gate["target_B_model"] == MODEL
            and gate["previous_micro_gate"] == reg["previous_micro_gate"],
            "B_entry", "Cross-model result attribution changed")
    for case in sorted(expected):
        directory = case_directory(oldroot, case)
        row = gate["cases"][case]
        fragment = checked_file(row["fragment"])
        audit = checked_file(row["audit"])
        seal = checked_file(row["evidence"])
        closure = checked_file(row["audit_closure"])
        require(Path(row["fragment"]["path"]).resolve() == directory / "fragment_result.json"
                and Path(row["audit"]["path"]).resolve() == directory / "audit/acceptance.json"
                and Path(row["evidence"]["path"]).resolve() == directory / "evidence_manifest.json"
                and Path(row["audit_closure"]["path"]).resolve() == directory / "audit_closure.json"
                and fragment["accepted"] is True and audit["valid"] is True
                and fragment["evidence_sha256"] == audit["evidence_sha256"] == closure["evidence_sha256"] == row["evidence"]["sha256"]
                and seal["head"]["phase"] == "CLOSED"
                and closure["completed_epoch"] <= reg["registered_epoch"],
                "B_entry", "Missing, replaced, failed, or later micro evidence")
    return gate


def validate_registration(reg, root):
    from .experiment import checked_file
    from .model_switch import carried_recovery_count
    grant = validate_grant(checked_file(reg["authorization"]))
    require(reg["schema"] == SCHEMA and Path(reg["experiment_directory"]).resolve() == root.resolve()
            and Path(grant["experiment_directory"]).resolve() == root.resolve()
            and reg["model"] == MODEL and set(reg["cases"]) == {"B3600"}, "B_registration", "B-only fixed-model registration required")
    for field in ("previous_registration", "successful_probe", "prior_cost_evidence", "recovery_carry", "caps", "recovery_policy", "full_B_new_run_limit"):
        require(reg[field] == grant[field], "B_registration", "Registration differs from grant: " + field)
    previous = checked_file(reg["previous_registration"])
    probe_plan = strict_json((Path(reg["successful_probe"]["path"]).parent / "plan.json").read_bytes())
    require(probe_plan["prior_registration_sha256"] == reg["previous_registration"]["sha256"]
            and reg["model_catalog_sha256"] == sha_bytes(Path(reg["model_catalog"]).read_bytes())
            == probe_plan["inputs_sha256"]["model-catalog.json"], "B_probe", "Probe and B inputs differ")
    require(checked_file(reg["prior_cost_evidence"])["previous_registration"] == reg["previous_registration"],
            "B_registration", "Cost and model ancestry differ")
    cfg = strict_json((root / "B3600.config.json").read_bytes())
    validate_config(cfg)
    oldcfg = strict_json((Path(reg["previous_registration"]["path"]).parent / "B3600.config.json").read_bytes())
    expected = deepcopy(oldcfg)
    expected["model"].update(MODEL)
    require(cfg == expected and reg["cases"]["B3600"] == {"group": "B3600", "config_sha256": digest(cfg), "initial_state_sha256": None}
            and cfg["window_seconds"] == 3600 and cfg["model"]["timeout_seconds"] == 600,
            "B_case", "Only the model may differ from the prior cold-start B")
    usage, starts, _ = carried_costs(reg)
    require(reg["carried_usage_at_registration"] == usage and reg["full_B_new_run_limit"] == starts + 1
            and reg["full_B_new_run_limit"] == 2 and carried_recovery_count(reg) == grant["prior_exception_count"],
            "B_budget", "Prior B or exception counters were reset")
    expected_caps = {g: {k: None if v is None else usage[g][k] + (v if g != "micro" else 0)
                          for k, v in ADDITIONAL.items()} for g in usage}
    require(reg["caps"] == expected_caps and reg["B_early_stop_on_new_unknown_usage"] is True,
            "B_budget", "Time limits or zero-unknown B policy changed")
    gate = checked_file(reg["entry_gate"])
    require(strict_json((root / "micro_gate.json").read_bytes()) == gate
            and gate["authorization"] == reg["authorization"], "B_entry", "Entry gate differs")
    validate_entry_gate(reg, gate)
    report = checked_file({"path": reg["engineering_report"], "sha256": reg["engineering_report_sha256"]})
    before, after = checked_file(reg["base_fingerprint"]), report["fingerprint"]
    from .evaluation import Evidence
    prior_B = Evidence(Path(reg["previous_registration"]["path"]).parent / "runs/B3600", probe_plan["prior_B_evidence_sha256"])
    require(before == prior_B.manifest["fingerprint"] and before["sha256"] == probe_plan["source_sha256"],
            "B_source", "Source comparison is not anchored to the closed predecessor")
    changed = {p for p in before["files"].keys() | after["files"].keys() if before["files"].get(p) != after["files"].get(p)}
    require(changed <= CONTROL_FILES and {k:v for k,v in before.items() if k not in ("files", "sha256")} ==
            {k:v for k,v in after.items() if k not in ("files", "sha256")}
            and digest({k:v for k,v in after.items() if k != "sha256"}) == after["sha256"] == reg["fingerprint_sha256"],
            "B_source", "Model switch changed physical decisions, protocol, dependencies or data")
    tests = checked_file(report["test_evidence"])
    require(tests["all_pass"] is True and tests["source_unchanged"] is True and tests["remote_model_calls"] == 0
            and tests["fingerprint_sha256"] == after["sha256"]
            and all(report["gates"][g] == "pass" for g in ("G0", "G1", "G2", "G3", "G4")),
            "B_source", "Passing current-source engineering checks required")
    require(reg["transport_proxy"] == previous["transport_proxy"] and reg["cli_binary"] == previous["cli_binary"]
            and reg["cli_sha256"] == previous["cli_sha256"], "B_transport", "Frozen channel changed")
    return reg
