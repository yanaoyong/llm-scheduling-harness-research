"""Independent post-run audit; never modifies frozen code, configs, or run logs.

Each submitted schedule is fixed in the original ASP program, which is then
used only as a SAT/soft-cost checker. These solver calls belong to audit costs,
not to arms A/B/C. A fresh audit directory preserves every audit invocation.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from problem import load_instance
from validator import validate_schedule
from dispatch import build_schedule

BINARY = ROOT / "vendor/clingo-dl/build/clingo-dl"
ENCODING = ROOT / "vendor/FJSP-SMT2020/PADL-2023/encoding_msw.lp"
TOKEN_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checked(condition, issues, message, **details):
    if not condition:
        issues.append(dict(error=message, **details))
    return bool(condition)


def sum_known(values):
    return sum(values) if all(v is not None for v in values) else None


def equal_number(actual, expected):
    if expected is None:
        return actual is None or actual == ""
    if isinstance(expected, bool):
        return actual is expected or actual == str(expected)
    try:
        return math.isclose(float(actual), float(expected), rel_tol=1e-9, abs_tol=1e-9)
    except (TypeError, ValueError):
        return actual == expected


def fixed_source_check(instance, schedule, source, directory, seconds):
    """No optimization search over decisions: all decisions/start values fixed."""
    directory.mkdir(parents=True, exist_ok=False)
    definitions = {op["id"]: op for op in instance["operations"]}
    fixed = ["% Audit only: fix submitted decisions and processing start values.",
             "#show use_setup/2.", "#show assign_setup/3."]
    for row in schedule["operations"]:
        op = definitions[row["id"]]
        identity = ",".join(str(op[k]) for k in ("lot", "product", "step", "priority"))
        term = f"({identity})"
        fixed.append(f":- not mach_assign({identity},{op['group']},{row['machine']}).")
        for pm in instance["maintenance"]:
            if pm["group"] == op["group"]:
                atom = f"assign({pm['name']},{op['group']},{term})"
                fixed.append(f":- {'not ' if pm['name'] in row['maintenance'] else ''}{atom}.")
        fixed.append(f"&diff{{{term} - 0}} <= {row['start']}.")
        fixed.append(f"&diff{{0 - {term}}} <= {-row['start']}.")
    fixed_path = directory / "fixed.lp"
    fixed_path.write_text("\n".join(fixed) + "\n", encoding="utf-8")
    command = [str(BINARY), str(ENCODING), str(source), str(fixed_path),
               "--const", "flex=1", "--outf=2", "--models=0", f"--time-limit={seconds}"]
    dump(directory / "command.json", dict(argv=command, cwd=str(ROOT),
        role="post_run_audit_only", decision_search="all machine/PM/start decisions fixed"))
    started = time.monotonic()
    try:
        process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=seconds + 5)
        stdout, stderr, code = process.stdout, process.stderr, process.returncode
        timeout = False
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else exc.stdout or ""
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else exc.stderr or ""
        code, timeout = None, True
    duration = time.monotonic() - started
    (directory / "solver.stdout.json").write_text(stdout, encoding="utf-8")
    (directory / "solver.stderr.log").write_text(stderr, encoding="utf-8")
    output = dict(audit_solver_seconds=duration, exit_code=code, timed_out=timeout,
                  source_sat=False, source_cost=None, result=None)
    try:
        parsed = json.loads(stdout)
        witnesses = [w for call in parsed.get("Call", []) for w in call.get("Witnesses", [])]
        output.update(result=parsed.get("Result"), source_sat=bool(witnesses),
                      source_cost=witnesses[-1].get("Costs", [0])[0] if witnesses else None,
                      witnesses=len(witnesses), source_reported_seconds=parsed.get("Time", {}).get("Total"))
    except (json.JSONDecodeError, IndexError) as exc:
        output["decode_error"] = str(exc)
    dump(directory / "result.json", output)
    return output


def model_and_decision_audit(directory, result, instance, schedule, config, issues):
    """Read actual event streams and decisions, not transport success flags only."""
    model_dirs = sorted(directory.glob("model_*"))
    checked(len(model_dirs) == result["model_calls"], issues, "model call count differs from directories")
    checked(len(model_dirs) <= config["max_model_calls"], issues, "model call cap exceeded")
    usage_by_call, elapsed, native_count, thread_ids = [], [], 0, []
    decisions = []
    for model_dir in model_dirs:
        number = int(model_dir.name.split("_")[-1])
        raw_result = read(model_dir / "result.json")
        request = read(model_dir / "request.json")
        checked(request["config"] == config["model"], issues, "model request differs from frozen configuration", call=number)
        event_records = []
        for line_number, line in enumerate((model_dir / "events.jsonl").read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                event_records.append(json.loads(line))
            except json.JSONDecodeError:
                issues.append(dict(error="malformed model event JSON", call=number, line=line_number))
        items = [e.get("item", {}) for e in event_records
                 if e.get("type") in {"item.started", "item.completed", "item.updated"}]
        forbidden = [item for item in items if item.get("type") not in {"agent_message", "reasoning", "error"}]
        native_count += len(forbidden)
        checked(not forbidden, issues, "native tool event in model raw log", call=number, events=forbidden)
        checked(not raw_result.get("native_tool_events"), issues, "transport records native tool use", call=number)
        usages = [e["usage"] for e in event_records if e.get("type") == "turn.completed" and isinstance(e.get("usage"), dict)]
        observed = {key: sum_known([u.get(key) for u in usages]) if usages else None for key in TOKEN_FIELDS}
        checked(all(observed[key] == raw_result.get("usage", {}).get(key) for key in TOKEN_FIELDS),
                issues, "token usage differs from raw events", call=number)
        usage_by_call.append(observed)
        elapsed.append(raw_result["duration_seconds"])
        thread_ids.extend(e["thread_id"] for e in event_records if e.get("type") == "thread.started" and "thread_id" in e)
        decision_path = directory / f"decision_{number:02d}.json"
        if decision_path.exists():
            decision = read(decision_path)
            decisions.append((number, decision))
            checked(decision == raw_result.get("output"), issues, "saved decision differs from model output", call=number)
            checked(decision == read(model_dir / "final.txt"), issues, "saved decision differs from raw final", call=number)
    aggregate = {key: sum_known([u[key] for u in usage_by_call]) for key in TOKEN_FIELDS}
    checked(aggregate == result["usage"], issues, "run token aggregate differs from raw events")
    checked(equal_number(sum(elapsed), result["model_elapsed_seconds"]), issues, "run model duration aggregate mismatch")
    checked(len(thread_ids) == len(set(thread_ids)), issues, "model thread reused within a run")
    checked(len(decisions) == result["decision_count"], issues, "decision count mismatch")
    checked(result["cost_usd"] is None if model_dirs else result["cost_usd"] == 0,
            issues, "unknown monetary cost incorrectly represented")
    if result["arm"] == "B":
        checked(not list(directory.glob("solver_*")), issues, "direct Agent has solver artifacts")
        checked(result["solver_calls"] == 0, issues, "direct Agent reports solver calls")
        if schedule and decisions:
            reproduced = build_schedule(instance, decisions[-1][1]["actions"])
            checked(reproduced == schedule, issues, "B saved schedule differs from replayed model decisions")
            try:
                first_schedule = build_schedule(instance, decisions[0][1]["actions"])
                first_feasible = validate_schedule(instance, first_schedule)["feasible"]
            except (ValueError, KeyError, TypeError):
                first_feasible = False
            checked(first_feasible == result["first_candidate_feasible"], issues, "B first-candidate feasibility mismatch")
    elif result["arm"] == "C":
        checked(result["solver_calls"] <= config["max_solver_calls"], issues, "C solver call cap exceeded")
        commands = sorted(directory.glob("solver_*/command.json"))
        checked(len(commands) == result["solver_calls"], issues, "solver command count mismatch")
        requested_seconds = 0
        solved = []
        for number, decision in decisions:
            if decision["action"] != "solve":
                continue
            feedback = read(directory / f"feedback_{number:02d}.json")
            if feedback.get("tool") == "solve_and_validate":
                solved.append(decision)
        checked(len(solved) == len(commands), issues, "solver executions not explained by accepted model actions")
        for decision, command_file in zip(solved, commands):
            argv = read(command_file)["argv"]
            requested_seconds += decision["time_limit"]
            for flag, value in [("time-limit", decision["time_limit"]), ("seed", decision["seed"]), ("configuration", decision["configuration"])]:
                checked(f"--{flag}={value}" in argv, issues, "C solver parameter differs from model action", flag=flag)
        checked(requested_seconds <= config["solver_total_seconds"], issues, "C total requested solver time exceeded")
        if commands:
            first_solver = read(commands[0].parent / "classical.json")
            first_schedule = first_solver.get("schedule")
            first_feasible = validate_schedule(instance, first_schedule)["feasible"] if first_schedule else False
            checked(first_feasible == result["first_candidate_feasible"], issues, "C first-candidate feasibility mismatch")
        if schedule and decisions:
            final = decisions[-1][1]
            checked(final["action"] == "finish", issues, "C did not explicitly finish")
            if final["action"] == "finish":
                selected = final["candidate"]
                checked(selected == result["selected_candidate"], issues, "C selected candidate identity mismatch")
                solver_schedule = read(directory / f"solver_{selected}" / "schedule.json")
                checked(solver_schedule == schedule, issues, "C final schedule differs from selected solver candidate")
    else:
        checked(not model_dirs, issues, "classical arm has model calls")
        first_solver_path = directory / "solver_1/classical.json"
        if first_solver_path.exists():
            first_solver = read(first_solver_path)
            first_schedule = first_solver.get("first_schedule")
            first_feasible = validate_schedule(instance, first_schedule)["feasible"] if first_schedule else None
            checked(first_feasible == result["first_candidate_feasible"], issues, "A first-witness feasibility mismatch")
    return dict(native_event_count=native_count, model_thread_ids=thread_ids,
                raw_usage=aggregate, model_calls=len(model_dirs))


def derived_metrics(rows, instances, repetitions):
    baseline = {(r["instance"], r["repetition"]): r["objective"]["makespan"]
                for r in rows if r["arm"] == "A" and r["status"] == "success" and r["objective"]}
    for row in rows:
        base = baseline.get((row["instance"], row["repetition"]))
        row["baseline_makespan"] = base
        row["baseline_gap_pct"] = 100 * (row["objective"]["makespan"] - base) / base if base and row["objective"] else None
    stats = {}
    for arm in "ABC":
        group = [r for r in rows if r["arm"] == arm]
        valid = [r for r in group if r["status"] == "success" and r["objective"]]
        average = lambda values: statistics.mean(values) if values else None
        stats[arm] = dict(runs=len(group), success=len(valid),
            first_candidate_feasible=sum(r["first_candidate_feasible"] is True for r in group),
            mean_makespan=average([r["objective"]["makespan"] for r in valid]),
            mean_setup_violations=average([r["objective"]["setup_violations"] for r in valid]),
            mean_baseline_gap_pct=average([r["baseline_gap_pct"] for r in valid if r["baseline_gap_pct"] is not None]),
            mean_end_to_end_seconds=average([r["end_to_end_seconds"] for r in group]),
            total_end_to_end_seconds=sum(r["end_to_end_seconds"] for r in group),
            total_model_elapsed_seconds=sum(r["model_elapsed_seconds"] for r in group),
            total_solver_seconds=sum(r["solver_seconds"] for r in group),
            total_model_calls=sum(r["model_calls"] for r in group),
            total_revisions=sum(r["revision_count"] for r in group),
            usage={key: sum_known([r["usage"].get(key) for r in group]) for key in TOKEN_FIELDS})
    return stats


def check_publications(phase, rows, stats, instances, issues):
    artifact = ROOT / "artifacts" / phase
    summary = read(artifact / "summary.json")
    checked(summary["total_runs"] == len(rows), issues, "published summary run count mismatch")
    checked(summary["success"] == sum(r["status"] == "success" for r in rows), issues, "published summary success count mismatch")
    checked(not summary["issues"], issues, "published replay already reports issues")
    checked(summary["arms"] == stats, issues, "published summary statistics mismatch")
    with (artifact / "results.csv").open(newline="", encoding="utf-8") as stream:
        csv_rows = list(csv.DictReader(stream))
    checked(Counter(r["run_id"] for r in csv_rows) == Counter(r["run_id"] for r in rows), issues, "CSV run set differs")
    csv_by_id = {r["run_id"]: r for r in csv_rows}
    for row in rows:
        exported = csv_by_id.get(row["run_id"], {})
        flat = dict(row, **(row["objective"] or dict(makespan=None, setup_violations=None)), **row["usage"])
        for key, value in exported.items():
            expected = flat.get(key)
            same = equal_number(value, expected) if expected is None or isinstance(expected, (int, float, bool)) else value == expected
            checked(same, issues, "CSV value mismatch", run_id=row["run_id"], field=key, expected=expected, actual=value)
    report = (ROOT / "docs/REPORT_zh.md").read_text(encoding="utf-8")
    lines = set(report.splitlines())
    fmt = lambda v: "未知" if v is None else f"{v:.2f}"
    labels = {"A": "A 经典原ASP", "B": "B 直接Agent", "C": "C 求解器增强Agent"}
    for arm in "ABC":
        s = stats[arm]
        expected = f'| {labels[arm]} | {s["success"]}/{s["runs"]} | {s["first_candidate_feasible"]}/{s["runs"]} | {fmt(s["mean_makespan"])} | {fmt(s["mean_baseline_gap_pct"])}% | {fmt(s["mean_end_to_end_seconds"])} | {s["total_model_calls"]} | {s["total_revisions"]} |'
        checked(expected in lines, issues, "Chinese report main metrics mismatch", arm=arm, expected=expected)
        u = s["usage"]
        expected = f'| {arm} | {fmt(s["total_model_elapsed_seconds"])} | {fmt(s["total_solver_seconds"])} | {u["input_tokens"]} | {u["cached_input_tokens"]} | {u["output_tokens"]} |'
        checked(expected in lines, issues, "Chinese report token/time metrics mismatch", arm=arm, expected=expected)
        for instance in instances:
            group = sorted([r for r in rows if r["instance"] == instance and r["arm"] == arm], key=lambda r: r["repetition"])
            objectives = ", ".join(str(r["objective"]["makespan"]) if r["objective"] else r["status"] for r in group)
            setups = ", ".join(str(r["objective"]["setup_violations"]) if r["objective"] else "—" for r in group)
            statuses = "; ".join("/".join(r["solver_statuses"]) or "直接生成" for r in group)
            expected = f"| {instance} | {arm} | {objectives} | {setups} | {statuses} |"
            checked(expected in lines, issues, "Chinese report per-instance mismatch", instance=instance, arm=arm)
    for row in rows:
        if row["arm"] != "C":
            continue
        decisions = [read(p) for p in sorted((ROOT / "runs" / phase / row["run_id"]).glob("decision_*.json"))]
        choices = [f'{d["time_limit"]}s / {d["configuration"]} / seed={d["seed"]}' for d in decisions if d.get("action") == "solve"]
        expected = f'| {row["run_id"]} | {"；".join(choices)} | {row["solver_calls"]} | {row["selected_candidate"]} |'
        checked(expected in lines, issues, "Chinese report C decision table mismatch", run_id=row["run_id"])
    # Rebuild the all-phase usage ledger from requests/results, preserving each
    # field's unknown count. This includes failed probes and unfinished calls.
    reconstructed = {}
    for request in (ROOT / "runs").rglob("request.json"):
        stage = request.relative_to(ROOT / "runs").parts[0]
        cost = reconstructed.setdefault(stage, dict(attempts=0, reported_calls=0, unreported_attempts=0,
            unknown_by_field={key: 0 for key in TOKEN_FIELDS}, **{"known_" + key: 0 for key in TOKEN_FIELDS}))
        cost["attempts"] += 1
        path = request.parent / "result.json"
        usage = read(path).get("usage", {}) if path.exists() else {}
        if all(usage.get(key) is not None for key in TOKEN_FIELDS):
            cost["reported_calls"] += 1
        else:
            cost["unreported_attempts"] += 1
        for key in TOKEN_FIELDS:
            if usage.get(key) is None:
                cost["unknown_by_field"][key] += 1
            else:
                cost["known_" + key] += usage[key]
    ledger = read(ROOT / "artifacts/model_usage_ledger.json")
    checked(set(reconstructed) == set(ledger), issues, "usage ledger stage set mismatch")
    for stage, cost in reconstructed.items():
        stored = ledger.get(stage, {})
        for key, value in cost.items():
            checked(stored.get(key) == value, issues, "usage ledger subtotal mismatch", stage=stage, field=key)
        for key in TOKEN_FIELDS:
            expected = None if cost["unknown_by_field"][key] else cost["known_" + key]
            checked(stored.get(key) == expected, issues, "usage ledger unknown handling mismatch", stage=stage, field=key)
        checked(stored.get("cost_usd") is None, issues, "usage ledger invents monetary cost", stage=stage)
        expected = f'| {stage} | {cost["attempts"]} | {cost["reported_calls"]} | {cost["known_input_tokens"]} | {cost["known_output_tokens"]} | {cost["unreported_attempts"]} |'
        checked(expected in lines, issues, "Chinese report stage cost mismatch", stage=stage)
    if len(rows) == 27 and all(r["status"] == "success" for r in rows):
        checked("27/27 条正式运行通过独立硬约束校验" in report, issues, "Chinese report completion assertion missing")
    return dict(summary_sha256=sha(artifact / "summary.json"), csv_sha256=sha(artifact / "results.csv"),
                report_sha256=sha(ROOT / "docs/REPORT_zh.md"))


def audit(phase="acceptance_v1", allow_partial=False, label=None, solver_seconds=10):
    started = time.monotonic()
    stamp = label or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    if not stamp or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in stamp):
        raise ValueError("Audit label must use letters, digits, underscores or hyphens")
    output = ROOT / "artifacts/formal_source_audit" / stamp
    output.mkdir(parents=True, exist_ok=False)
    issues, observations, audited_rows = [], [], []
    config = read(ROOT / "configs/run_config.json")
    split = read(ROOT / "configs/instance_split.json")
    instances = split[phase]
    repetitions = split["repetitions"]
    freeze = read(ROOT / "configs/freeze.json")
    for relative, digest in freeze["files"].items():
        checked((ROOT / relative).is_file() and sha(ROOT / relative) == digest, issues, "frozen file changed", file=relative)
    expected = {(instance, arm, repetition) for instance in instances for arm in "ABC" for repetition in range(1, repetitions + 1)}
    results = []
    for path in sorted((ROOT / "runs" / phase).glob("*/result.json")):
        result = read(path)
        if "arm" in result:
            results.append((path, result))
    actual = Counter((r["instance"], r["arm"], r["repetition"]) for _, r in results)
    duplicates = [list(k) for k, count in actual.items() if count > 1]
    missing = sorted(expected - actual.keys())
    unexpected = sorted(actual.keys() - expected)
    checked(not duplicates, issues, "duplicate formal grid cells", cells=duplicates)
    checked(not unexpected, issues, "unexpected formal grid cells", cells=unexpected)
    if not allow_partial:
        checked(not missing and len(results) == 27, issues, "formal grid incomplete", missing=missing, completed=len(results))
    incomplete = [p.parent.name for p in (ROOT / "runs" / phase).glob("*/started.json") if not (p.parent / "result.json").exists()]
    if not allow_partial:
        checked(not incomplete, issues, "started formal runs missing result", run_ids=incomplete)
    model_thread_ids = []
    for path, result in results:
        directory = path.parent
        local_issues = []
        source = ROOT / "vendor/FJSP-SMT2020/PADL-2023/instances" / f"{result['instance']}.lp"
        observation = dict(run_id=result["run_id"], arm=result["arm"], instance=result["instance"], repetition=result["repetition"])
        try:
            instance = load_instance(source)
            stored_input = read(directory / "input.json")
            checked({k: v for k, v in instance.items() if k != "source"} == {k: v for k, v in stored_input.items() if k != "source"}, local_issues, "cached input differs from original facts")
            checked(sha(source) == result["input_sha256"], local_issues, "input hash differs")
            checked(read(directory / "config.json") == config, local_issues, "run configuration differs from frozen configuration")
            checked(sha(directory / "config.json") == result["config_sha256"], local_issues, "run configuration hash differs")
            checked(result["status"] == "success", local_issues, "formal run is not successful", status=result["status"], reason=result["failure_reason"])
            checked(result["fallback"] is False, local_issues, "fallback used")
            schedule = read(directory / result["schedule_file"]) if result.get("schedule_file") else None
            if schedule:
                validation = validate_schedule(instance, schedule)
                checked(validation["feasible"], local_issues, "independent validator rejects schedule", violations=validation["violations"])
                checked(validation == result["validation"], local_issues, "saved independent validation differs")
                checked(validation["objective"] == result["objective"], local_issues, "saved objective differs")
                source_check = fixed_source_check(instance, schedule, source, output / result["run_id"], solver_seconds)
                observation["source_check"] = source_check
                checked(source_check["source_sat"] and source_check["result"] in {"SATISFIABLE", "OPTIMUM FOUND"}, local_issues, "original ASP rejects schedule or audit did not finish", original=source_check)
                checked(source_check["source_cost"] == validation["objective"]["setup_violations"], local_issues, "original ASP setup weak cost differs", source_cost=source_check["source_cost"], independent=validation["objective"]["setup_violations"])
                observation["objective"] = validation["objective"]
                audited_rows.append(dict(result, objective=validation["objective"]))
            else:
                local_issues.append(dict(error="no complete schedule"))
                audited_rows.append(dict(result, objective=None))
            model_audit = model_and_decision_audit(directory, result, instance, schedule, config, local_issues)
            observation["model_and_decisions"] = model_audit
            model_thread_ids.extend(model_audit["model_thread_ids"])
        except Exception as exc:
            local_issues.append(dict(error="audit exception", exception=f"{type(exc).__name__}: {exc}"))
        observation["issues"] = local_issues
        observation["passed"] = not local_issues
        observations.append(observation)
        issues.extend(dict(run_id=result["run_id"], **issue) for issue in local_issues)
        print(json.dumps(dict(run_id=result["run_id"], audit_passed=not local_issues, issues=local_issues), ensure_ascii=False), flush=True)
    checked(len(model_thread_ids) == len(set(model_thread_ids)), issues, "model context reused across formal runs")
    total_calls = sum(r["model_calls"] for r in audited_rows)
    checked(total_calls <= config["formal_model_call_cap"], issues, "formal total model budget exceeded")
    stats = derived_metrics(audited_rows, instances, repetitions)
    publications = None
    if not allow_partial:
        try:
            publications = check_publications(phase, audited_rows, stats, instances, issues)
        except Exception as exc:
            issues.append(dict(error="publication audit exception", exception=f"{type(exc).__name__}: {exc}"))
    complete = not allow_partial and not missing and not incomplete and len(results) == 27
    summary = dict(phase=phase, audit_created_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        audit_script_sha256=sha(__file__), freeze_sha256=sha(ROOT / "configs/freeze.json"),
        mode="partial_progress_check" if allow_partial else "full_final_audit",
        expected_runs=len(expected), completed_runs=len(results), missing_cells=missing,
        incomplete_attempts=incomplete, final_acceptance_audited=complete,
        passed=complete and not issues, observed_records_passed=not issues,
        issues=issues, records=observations, independently_recomputed_metrics=stats,
        publication_fingerprints=publications, model_calls=total_calls,
        native_event_count=sum(r.get("model_and_decisions", {}).get("native_event_count", 0) for r in observations),
        audit_solver_seconds=sum(r.get("source_check", {}).get("audit_solver_seconds", 0) for r in observations),
        audit_end_to_end_seconds=time.monotonic() - started,
        accounting="Post-run audit resource usage only; excluded from A/B/C execution times and budgets.")
    dump(output / "summary.json", summary)
    md = ["# 正式排程原 ASP 独立核验", "", f"模式：{summary['mode']}；完整验收：{summary['passed']}。",
          f"已核验 {len(observations)} 条记录，预期 {len(expected)} 条；问题 {len(issues)} 个。",
          "", "本次只固定已有排程后检查原 ASP，不产生替代排程，不改变任何正式决策或冻结文件。",
          f"审计 solver 总墙钟 {summary['audit_solver_seconds']:.3f} 秒，全部与正式求解成本分开。", "",
          "| 运行 | 原 ASP SAT | setup 代价 | 决策/日志/指标一致 |", "|---|---|---:|---|"]
    for record in observations:
        original = record.get("source_check", {})
        md.append(f"| {record['run_id']} | {original.get('source_sat')} | {original.get('source_cost')} | {record['passed']} |")
    if issues:
        md += ["", "问题："] + [f"- {json.dumps(issue, ensure_ascii=False)}" for issue in issues]
    (output / "REPORT_zh.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    dump(ROOT / "artifacts/formal_source_audit/latest.json", dict(directory=str(output.relative_to(ROOT)),
        summary=str((output / "summary.json").relative_to(ROOT)), passed=summary["passed"], mode=summary["mode"]))
    print(json.dumps(dict(audit_directory=str(output), passed=summary["passed"], issues=len(issues), completed_runs=len(results)), ensure_ascii=False), flush=True)
    return 0 if not issues and (allow_partial or complete) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", default="acceptance_v1")
    parser.add_argument("--allow-partial", action="store_true", help="Audit completed records only; never declares final acceptance")
    parser.add_argument("--label", help="Fresh output directory name; existing labels cannot be overwritten")
    parser.add_argument("--solver-seconds", type=int, default=10, choices=range(1, 31), metavar="1..30")
    args = parser.parse_args()
    raise SystemExit(audit(args.phase, args.allow_partial, args.label, args.solver_seconds))
