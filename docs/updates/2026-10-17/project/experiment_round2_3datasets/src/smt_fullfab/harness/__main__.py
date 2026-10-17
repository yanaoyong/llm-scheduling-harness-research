"""Run `python -m src.smt_fullfab.harness --help` for the controlled entry points."""
import argparse
import os
from pathlib import Path
import sys
import time

from .contracts import HarnessError, default_config, encode, require, sha_bytes, strict_json
from .runtime import Runtime


def show(value):
    print(encode(value).decode(), flush=True)


def run_loop(runtime, *, steps=None, task=None):
    count = 0
    while runtime.head["phase"] not in ("AUDITING", "STOPPED", "CLOSED") and (steps is None or count < steps):
        if runtime.head["phase"] == "COMMITTED":
            show({"execution": runtime.advance()})
            continue
        runtime.check_admission()
        if runtime.manifest["mode"] == "policy":
            from .adapters import frozen_policy_action
            result = runtime.record_output(frozen_policy_action(runtime), channel="policy")
        else:
            require(runtime.manifest["mode"] == "model", "run_mode", "Replay uses explicit action files")
            from .transport import call
            result = call(runtime, task=task)
        show({"result": result, "usage": runtime.usage()})
        count += 1
    return count


def main(argv=None):
    parser = argparse.ArgumentParser(description="Versioned full-fab Harness; no implicit decisions or model retries")
    sub = parser.add_subparsers(dest="command", required=True)
    config = sub.add_parser("config", help="Print an exact default configuration")
    config.add_argument("--arm", choices=("A", "B", "C", "C-fixed"), default="B")
    config.add_argument("--seconds", type=float, default=3600)
    for name in ("start_new", "fork_scenario"):
        p = sub.add_parser(name)
        p.add_argument("directory", type=Path)
        p.add_argument("--config", type=Path, required=True)
        p.add_argument("--experiment-id", required=True)
        p.add_argument("--mode", choices=("replay", "policy", "model"), default="replay")
        if name == "start_new":
            p.add_argument("--admission", type=Path)
        else:
            p.add_argument("--parent", type=Path, required=True)
    for name in ("resume_run", "run", "action", "stop", "audit", "status"):
        p = sub.add_parser(name)
        p.add_argument("directory", type=Path)
        if name == "run":
            p.add_argument("--steps", type=int)
            p.add_argument("--task")
            p.add_argument("--seal", action="store_true")
        if name == "action":
            p.add_argument("--file", type=Path, required=True)
            p.add_argument("--advance", action="store_true")
        if name == "stop":
            p.add_argument("--reason", default="user_stop")
        if name == "audit":
            p.add_argument("--evidence-sha256")
            p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "config":
        show(default_config(args.arm, seconds=args.seconds))
        return 0
    if args.command == "stop":
        # The marker is checked before each new action. An in-flight guarded call
        # remains owned and its outcome is reconciled; it is never called unsent.
        target = args.directory.resolve() / "stop_requested.json"
        with target.open("x") as stream:
            stream.write(encode({"reason": args.reason, "requested_epoch": time.time()}).decode())
            stream.flush()
            os.fsync(stream.fileno())
        try:
            runtime = Runtime.resume_run(args.directory)
        except HarnessError as exc:
            if exc.code != "writer_busy":
                raise
            show({"status": "stop_requested", "reason": args.reason, "active_writer_will_reconcile": True})
            return 0
        runtime.stop(args.reason)
        runtime.close()
        show({"status": "stopped", "reason": args.reason})
        return 0
    if args.command == "audit":
        from .evaluation import audit_run, seal_evidence
        manifest = args.directory / "evidence_manifest.json"
        if manifest.exists():
            expected = args.evidence_sha256 or sha_bytes(manifest.read_bytes())
        else:
            runtime = Runtime.resume_run(args.directory)
            try:
                expected = seal_evidence(runtime)
            finally:
                runtime.close()
        report = audit_run(args.directory, expected_sha256=expected, output_dir=args.output)
        show(report)
        return 0 if report["valid"] else 2
    runtime = None
    try:
        if args.command == "start_new":
            admission = strict_json(args.admission.read_bytes()) if args.admission else None
            runtime = Runtime.start_new(args.directory, strict_json(args.config.read_bytes()), experiment_id=args.experiment_id, mode=args.mode, admission=admission)
        elif args.command == "fork_scenario":
            runtime = Runtime.fork_scenario(args.parent, args.directory, strict_json(args.config.read_bytes()), experiment_id=args.experiment_id, mode=args.mode)
        else:
            runtime = Runtime.resume_run(args.directory)
        if args.command == "action":
            show(runtime.record_output(args.file.read_bytes(), channel="replay"))
            if args.advance:
                show(runtime.advance())
        elif args.command == "run":
            try:
                run_loop(runtime, steps=args.steps, task=args.task)
            except HarnessError as exc:
                runtime.stop(exc.code)
                show(exc.response())
            if args.seal and runtime.head["phase"] in ("AUDITING", "STOPPED"):
                from .evaluation import audit_run, seal_evidence
                sha = seal_evidence(runtime)
                show(audit_run(args.directory, expected_sha256=sha, output_dir=args.directory / "audit"))
        show({"run_id": runtime.manifest["run_id"], "head": runtime.head, "usage": runtime.usage()})
        return 0
    finally:
        if runtime is not None:
            runtime.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except HarnessError as exc:
        show(exc.response())
        sys.exit(2)
