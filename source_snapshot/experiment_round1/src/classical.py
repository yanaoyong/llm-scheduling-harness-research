"""Run the upstream PADL ASP encoding and unchanged native optimizer.

No heuristic scheduler or alternate constraint model is used here.  JSON witness
atoms are translated into the common schedule and independently checked by the
caller's validator. The raw CLI result can be UNSATISFIABLE after the optimizer
has proved the final *stricter bound* unsatisfiable; saved witnesses still exist.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import subprocess
import time

import clingo

ROOT = Path(__file__).resolve().parents[1]
ENCODING = ROOT / "vendor/FJSP-SMT2020/PADL-2023/encoding_msw.lp"
BINARY = ROOT / "vendor/clingo-dl/build/clingo-dl"
SHOW = ROOT / "src/show.lp"
CONFIGURATIONS = {"auto", "frumpy", "jumpy", "tweety", "handy", "crafty", "trendy"}


def _op_id(symbol) -> str:
    return ":".join(str(a) for a in symbol.arguments)


def witness_schedule(witness: dict, instance_path: str | Path) -> dict:
    durations = {}
    for match in re.finditer(r"^\s*product\(([^\n]+)\)\.", Path(instance_path).read_text(), re.M):
        symbol = clingo.parse_term("product(" + match.group(1) + ")")
        args = symbol.arguments
        durations[(args[0].number, args[1].number)] = args[4].number
    assignments, starts, maintenance = {}, {}, {}
    for text in witness["Value"]:
        symbol = clingo.parse_term(text)
        args = symbol.arguments
        if symbol.match("mach_assign", 6):
            key = ":".join(str(a) for a in args[:4])
            assignments[key] = (args[5].number, args[1].number, args[2].number)
        elif symbol.match("assign", 3):
            maintenance.setdefault(_op_id(args[2]), []).append(str(args[0]))
        elif symbol.match("dl", 2) and args[0].type == clingo.SymbolType.Function and len(args[0].arguments) == 4:
            starts[_op_id(args[0])] = args[1].number
    operations = []
    for key in sorted(assignments, key=lambda v: tuple(map(int, v.split(":")))):
        machine, product, step = assignments[key]
        if key not in starts:
            raise ValueError(f"No theory start time for {key}")
        start = starts[key]
        operations.append({"id": key, "machine": machine, "start": start,
                           "end": start + durations[(product, step)],
                           "maintenance": sorted(maintenance.get(key, []))})
    if not operations:
        raise ValueError("No operation assignment atoms in solver witness")
    return {"operations": operations}


def solve(instance_path, run_dir, time_limit=20, seed=1, configuration="frumpy") -> dict:
    instance_path = Path(instance_path).resolve()
    run_dir = Path(run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    if configuration not in CONFIGURATIONS:
        raise ValueError(f"Unsupported solver configuration: {configuration}")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**31 - 1:
        raise ValueError("seed must be a non-negative 31-bit integer")
    if isinstance(time_limit, bool) or not isinstance(time_limit, (float, int)) or not 0 < time_limit <= 120:
        raise ValueError("time_limit must be in (0,120]")
    if not BINARY.is_file():
        raise RuntimeError("Native solver missing: run .venv/bin/python src/build_solver.py")
    command = [str(BINARY), str(ENCODING), str(instance_path), str(SHOW), "--const", "flex=1",
               "--minimize-variable=makespan", f"--time-limit={math.ceil(time_limit)}",
               f"--seed={seed}", f"--configuration={configuration}", "--outf=2", "--stats=2"]
    (run_dir / "command.json").write_text(json.dumps({"argv": command, "cwd": str(ROOT)}, ensure_ascii=False, indent=2) + "\n")
    start = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True,
                                   timeout=math.ceil(time_limit) + 10)
        stdout, stderr, exit_code = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else exc.stdout or ""
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else exc.stderr or ""
        exit_code = None
    elapsed = time.monotonic() - start
    raw_path = run_dir / "solver.stdout.json"
    raw_path.write_text(stdout)
    (run_dir / "solver.stderr.log").write_text(stderr)
    result = {"schedule": None, "first_schedule": None, "solver_status": "error",
              "solver_seconds": elapsed, "raw_record": str(raw_path), "exit_code": exit_code,
              "configuration": configuration, "seed": seed, "time_limit": time_limit,
              "timed_out": timed_out, "fallback_used": False}
    try:
        record = json.loads(stdout)
    except json.JSONDecodeError as exc:
        result["solver_status"] = "timeout" if timed_out else "error"
        result["error"] = f"Incomplete solver JSON: {exc}"
    else:
        witnesses = [w for call in record.get("Call", []) for w in call.get("Witnesses", [])]
        raw_status = record.get("Result", "UNKNOWN")
        result["raw_solver_status"] = raw_status
        result["solver_reported_seconds"] = record.get("Time", {}).get("Total")
        result["solver_search_seconds"] = record.get("Time", {}).get("Solve")
        result["witness_count"] = len(witnesses)
        result["solver_calls"] = record.get("Calls")
        result["timed_out"] = timed_out or "INTERRUPTED" in raw_status or bool(exit_code is not None and exit_code & 1)
        if witnesses:
            try:
                result["first_schedule"] = witness_schedule(witnesses[0], instance_path)
                result["schedule"] = witness_schedule(witnesses[-1], instance_path)
                result["solver_status"] = "optimal" if raw_status == "UNSATISFIABLE" and not result["timed_out"] else "feasible"
                result["setup_cost_from_solver"] = witnesses[-1].get("Costs")
                result["makespan_from_solver"] = record.get("Stats", {}).get("DifferenceLogic", {}).get("Optimization")
                result["first_witness_seconds"] = witnesses[0].get("Time")
            except (KeyError, ValueError, RuntimeError) as exc:
                result["solver_status"] = "error"
                result["error"] = f"Witness conversion failed: {exc}"
        else:
            result["solver_status"] = "unsatisfiable" if raw_status == "UNSATISFIABLE" else "timeout" if result["timed_out"] else "unknown"
    (run_dir / "classical.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    if result["schedule"]:
        (run_dir / "schedule.json").write_text(json.dumps(result["schedule"], ensure_ascii=False, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("instance")
    parser.add_argument("run_dir")
    parser.add_argument("--time-limit", type=float, default=20)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--configuration", default="frumpy")
    args = parser.parse_args()
    output = solve(args.instance, args.run_dir, args.time_limit, args.seed, args.configuration)
    print(json.dumps({k: v for k, v in output.items() if k not in {"schedule", "first_schedule"}}, ensure_ascii=False, indent=2))
