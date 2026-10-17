"""C8 file-only attribution candidate; not installed and not a launch gate.

The original validation body is copied visibly, with only storage/reader access
replacements. Pure checks are in legacy_checks.py; no AST-based check removal or
runtime controller, environment, transport, constructor or solver import occurs.
"""
from collections import Counter
from contextlib import ExitStack, contextmanager
import hashlib
import json
import math
from pathlib import Path
import re
import types

from .legacy_checks import (SOLVERS, FEASIBLE_STATUSES, FEEDBACK_FIELDS, digest,
    _audit_ledger_admission, audit_constructor_ledger, _heuristic_errors, _schema_errors,
    _sections, _strict_prompt_sections, _literal_prompt_constants, _crop, _verify_pages, _page_fidelity)
from .storage import AuditStorage, PriorOutputs

VERSION = 'draft-C8-stream-attribution-v2'
ORIGINAL_CONTROLLER_AUDIT_SHA256 = 'bb3e85716ca799d016836dad73959d6d2c53fd534a26047e76b28c12dc049137'
ORIGINAL_CONSTRUCTOR_AUDIT_SHA256 = '27c2b9252b95d90908156a12bbe4776ae732bfb8f58179e212bc8e594bb6c4e5'
CONSTRUCTOR_COMPONENT_SHA256 = '181f9819bab37e0f60da03cd06f67505d9849336f0326632372903d41c896a60'


def _load_constructor(storage, path, expected_sha256):
    path = Path(path).absolute()
    if expected_sha256 != CONSTRUCTOR_COMPONENT_SHA256 or storage.sha_file(path) != expected_sha256:
        raise ValueError('explicit constructor attribution source SHA differs')
    with storage.text_stream(path) as stream:
        raw = stream.buffer.read()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('constructor attribution bytes differ during load')
    namespace = types.ModuleType('_isolated_C8_constructor_attribution')
    namespace.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), namespace.__dict__)
    return namespace.audit_constructor_evidence


@contextmanager
def _closing_constructor(candidates):
    """Keep a primary failure; ordinary close errors remain visible as notes.

    On a successful body, any close failure prevents report return. A close-time
    KeyboardInterrupt/SystemExit is not downgraded or swallowed; it propagates
    with any earlier primary failure retained as its exception context.
    """
    try:
        yield candidates
    except BaseException as primary:
        try:
            candidates.close()
        except Exception as cleanup:
            primary.add_note('constructor candidate cleanup also failed: ' + repr(cleanup))
        raise
    else:
        candidates.close()


def audit_controller(run_dir, ledger_path=None, *, scratch_dir,
                     constructor_module_path, expected_constructor_sha256, result_stage=None):
    """Read-only whole-run audit with external private scratch; no original writes.

    result_stage=None audits the unchanged original result.json (C1 oracle mode).
    An explicit (execution_result_path, raw_sha256) pair aliases only that read
    for a future C8 stage. This does not certify final cost/production success.
    The constructor module/hash are required external frozen inputs, no fallback.
    """
    run = Path(run_dir).resolve()
    scratch = Path(scratch_dir).resolve()
    if scratch == run or scratch in run.parents or run in scratch.parents:
        raise ValueError('scratch must be outside the immutable raw run tree')
    with AuditStorage(scratch) as storage, ExitStack() as resources:
        if result_stage is not None:
            path, expected = result_stage
            path = Path(path).absolute()
            if path != run / 'execution_result.json' or storage.sha_file(path) != expected:
                raise ValueError('explicit immutable execution-stage anchor differs')
            result_stage = (path, expected)
        constructor_checker = _load_constructor(storage, constructor_module_path, expected_constructor_sha256)
        report = _audit_controller_body(run, ledger_path, storage=storage,
            constructor_checker=constructor_checker, resources=resources, result_stage=result_stage)
        # Private SQL contains exact decoded cache rows, never authoritative
        # replacement raw events. Both source-hash and final identity fences are
        # required; original files are never edited/deleted to limit memory.
        receipts = storage.receipts()
        report['_source_evidence'] = {
            'schema': VERSION + '-sources', 'receipts': receipts,
            'original_controller_audit_sha256': ORIGINAL_CONTROLLER_AUDIT_SHA256,
            'original_constructor_audit_sha256': ORIGINAL_CONSTRUCTOR_AUDIT_SHA256,
            'constructor_component_sha256': expected_constructor_sha256,
            'scratch_directory': str(scratch), 'scratch_is_private_exclusive_cache': True,
            'full_original_check_order_intended': True, 'oracle_parity_verified': False,
            'real_C8_launch_authorized': False, 'physical_audit_performed': False,
            'final_resource_acceptance_performed': False,
            'remaining_RAM': ['one observation/page set and current model/history',
                'all lightweight keys/row hashes/ledger admission state/report arrays',
                'materialized ledger prefixes for unchanged original prefix JSON hashing',
                'largest individual JSON or logical JSONL record'],
        }
        return report


def _audit_controller_body(run_dir, ledger_path, *, storage, constructor_checker, resources, result_stage):
    run = Path(run_dir).resolve()
    errors, missing, warnings, hashes = [], [], [], {}

    def check(ok, message):
        if not ok and len(errors) < 200:
            errors.append(message)

    def read(path, *, optional=False, lines=False):
        path = Path(path)
        if result_stage is not None and path == run / "result.json":
            path = result_stage[0]
        if not path.exists():
            if not optional:
                missing.append(str(path))
            return None
        try:
            hashes[str(path.relative_to(run)) if path.is_relative_to(run) else str(path)] = storage.sha_file(path)
            return storage.read(path, lines=lines)
        except (ValueError, OSError) as exc:
            check(False, f"cannot parse {path.name}: {type(exc).__name__}")
            return None

    cfg = read(run / "config.json") or {}
    result = read(run / "result.json")
    arm = cfg.get("arm")
    check(arm in ("B", "C"), "controller audit requires an evaluated B/C run")
    if result is not None:
        check(result.get("identity") == digest(cfg), "result identity differs from saved config")
        check(result.get("config") == cfg, "result config differs from saved config")
    provenance = read(run / "provenance.json")
    prompt_constants = {}
    if provenance:
        for relative, expected in provenance.get("source_sha256", {}).items():
            path = run / "source_snapshot" / relative
            if not path.exists():
                missing.append(str(path))
            else:
                check(storage.sha_file(path) == expected, "source snapshot hash mismatch: " + relative)
        for name in ("controller.py", "interface.py", "model_transport.py", "budget.py"):
            if "src/smt_fullfab/" + name not in provenance.get("source_sha256", {}):
                missing.append("source snapshot inventory: " + name)
        source = run / "source_snapshot/src/smt_fullfab/controller.py"
        if source.exists():
            try:
                prompt_constants = _literal_prompt_constants(source)
            except (ValueError, SyntaxError):
                missing.append("parseable frozen controller prompt constants")
    if cfg.get("enable_constructive") is True:
        for name in ("constructive_tool.py", "incumbent.py"):
            if "src/smt_fullfab/" + name not in (provenance or {}).get("source_sha256", {}):
                missing.append("source snapshot inventory: " + name)
    trace = read(run / "trace.jsonl", lines=True) or []
    commits = storage.collect("commits", (e for e in trace if e.get("kind") == "plan_committed"))
    trace_manifest = trace[0].get("manifest", {}) if trace else {}
    if ledger_path is None:
        ledger_path = run.parents[2] / "progress/smt_fullfab/model_ledger.jsonl"
    ledger = read(ledger_path, lines=True) or []
    reserves = {row["call_id"]: row for row in ledger if row.get("event") == "reserve"}
    finishes = {row["call_id"]: row for row in ledger if row.get("event") == "finish"}
    check(len(reserves) == sum(row.get("event") == "reserve" for row in ledger), "duplicate model reservation identity")
    check(len(finishes) == sum(row.get("event") == "finish" for row in ledger), "duplicate model completion identity")
    approvals = [row["approval"] for row in ledger if row.get("event") == "approval" and row["approval"].get("budget_id") == cfg.get("budget_id")]
    approval = approvals[0] if len(approvals) == 1 else None
    check(len(approvals) == 1, "no unique approved ledger grant for this run")
    budget_replay = _audit_ledger_admission(ledger, approval) if approval else {"admissions": {}, "errors": [], "missing_evidence": []}
    constructor_replay = audit_constructor_ledger(ledger)
    budget_replay["constructor_replay"] = constructor_replay
    for cid, fields in constructor_replay["model_admissions"].items():
        if cid in budget_replay["admissions"]:
            budget_replay["admissions"][cid].update(fields)
    errors.extend(constructor_replay["errors"])
    errors.extend(budget_replay["errors"])
    missing.extend(budget_replay["missing_evidence"])
    run_registration = budget_replay.get("registered_runs", {}).get(str(run))
    if cfg.get("enable_constructive") is True:
        check(arm == "C" and run_registration is not None, "constructive requires a preceding research C registration")
    if approval:
        check(approval.get("authorization") == "approved_by_user", "ledger grant was not explicitly approved")
        if run_registration:
            check(read(run / "resource_registration.json") == run_registration, "saved resource registration differs from prior ledger registration")
            for ckey, rkey in (("arm", "arm"), ("seconds", "window_seconds"), ("seed", "scenario"), ("wall_seconds", "wall_seconds"), ("max_log_bytes", "max_log_bytes"), ("amendment_id", "amendment_id")):
                check(cfg.get(ckey) == run_registration[rkey], "run config differs from immutable registration: " + ckey)
            check(run_registration["solver_seconds"] == (cfg.get("solver_budget_seconds") if arm == "C" else 0), "run solver allowance differs from immutable registration")
            check(trace_manifest.get("seed") == run_registration["scenario"] and trace_manifest.get("horizon") == run_registration["window_seconds"],
                  "actual trace scenario/window differs from run registration")
        else:
            check(cfg.get("seconds") == approval.get("window_seconds"), "run window exceeds/differs from approved stage")
        own_ids = [call_id for call_id, row in reserves.items() if Path(row["run_id"]).resolve().is_relative_to(run)]
        effective = budget_replay.get("effective_amendment")
        unlimited = bool(arm == "C" and effective and cfg.get("amendment_id") == effective["amendment_id"] and
                         all(budget_replay["admissions"].get(call_id, {}).get("waiver_applied") for call_id in own_ids))
        if run_registration:
            unlimited = bool(cfg.get("amendment_id") == run_registration["amendment_id"] and all(
                budget_replay["admissions"].get(call_id, {}).get("registration", {}).get("registration_id") == run_registration["registration_id"] for call_id in own_ids))
        check((cfg.get("max_calls") is None and unlimited) or
              (type(cfg.get("max_calls")) is int and cfg["max_calls"] > 0 and (unlimited or cfg["max_calls"] <= approval.get("allocation", {}).get(arm, 0))),
              "per-run attempts exceed approved arm allocation without a preceding scoped waiver")
        if own_ids and any(budget_replay["admissions"].get(call_id, {}).get("waiver_applied") for call_id in own_ids):
            check(unlimited, "run config amendment differs from its effective reservation authority")
    links = read(run / "controller_decisions.jsonl", optional=True, lines=True) or []
    by_model = {}
    for link in links:
        index = link.get("model_index")
        check(index not in by_model, "duplicate controller model linkage index")
        by_model[index] = link
    models, model_directories = storage.mapping("models"), {}
    model_outputs = storage.mapping("model-outputs")
    for directory in sorted(run.glob("model_*")):
        if not directory.is_dir() or not re.fullmatch(r"model_\d+", directory.name):
            continue
        index = int(directory.name.split("_")[1])
        model_directories[index] = directory
        request = read(directory / "request.json")
        model = read(directory / "result.json")
        events = read(directory / "events.jsonl", lines=True)
        schema = read(directory / "schema.json")
        prompt_path, final_path = directory / "prompt.txt", directory / "final.txt"
        if not prompt_path.exists():
            missing.append(str(prompt_path))
        prompt = storage.read_text(prompt_path) if prompt_path.exists() else ""
        if prompt_path.exists():
            hashes[str(prompt_path.relative_to(run))] = storage.sha_file(prompt_path)
        if request is None or model is None or schema is None or events is None:
            continue
        parsed_sections = _sections(prompt)
        prompt_name = "C_CONSTRUCTIVE_PROMPT" if cfg.get("enable_constructive") is True else str(arm) + "_PROMPT"
        prefix = prompt_constants.get(prompt_name)
        if prefix is None:
            missing.append("literal frozen " + prompt_name)
        else:
            try:
                parsed_sections = _strict_prompt_sections(prompt, prefix)
                allowed = {"SCHEMA_AND_LIMITS", "PAGE"} if arm == "B" else {"STATE_DIRECTORY", "OWN_HISTORY", "LIMITS"}
                check(all(name in allowed or (arm == "B" and name.startswith("YOUR_")) for name in parsed_sections), f"model {index}: undeclared input section")
            except (ValueError, json.JSONDecodeError) as exc:
                check(False, f"model {index}: {exc}")
        models[index] = {"result": model, "request": request, "prompt": prompt, "sections": parsed_sections}
        model_outputs[index] = model.get("output")
        call_id = model.get("call_id")
        check(call_id == request.get("call_id") and call_id in reserves, f"model {index}: call ID lacks matching request/reservation")
        config = request.get("config", {})
        check(config == model.get("config"), f"model {index}: request/result config mismatch")
        expected = hashlib.sha256((prompt + "\n" + json.dumps(schema, ensure_ascii=False, indent=2) + "\n" + "\n" + json.dumps(config, sort_keys=True)).encode()).hexdigest()
        check(model.get("request_fingerprint") == expected == request.get("request_fingerprint"), f"model {index}: prompt/schema/config fingerprint mismatch")
        if approval:
            check(config.get("model") == approval["model"] and config.get("reasoning_effort") == approval["reasoning_effort"], f"model {index}: unapproved model/config change")
            check(config.get("grant_id") == approval["budget_id"], f"model {index}: wrong budget grant")
            check(config.get("timeout_seconds", 0) <= approval["per_call_timeout_seconds"], f"model {index}: timeout exceeds approval")
        if call_id in reserves:
            reserve = reserves[call_id]
            check(Path(reserve["run_id"]).resolve() == directory, f"model {index}: reservation points to another model attempt")
            check(reserve.get("metadata", {}).get("request_fingerprint") == expected, f"model {index}: reservation fingerprint mismatch")
            admission = budget_replay["admissions"].get(call_id, {})
            if admission.get("waiver_applied"):
                check(config.get("timeout_seconds") == admission.get("timeout_seconds"), f"model {index}: actual timeout differs from scoped reservation")
                context = config.get("authorization_context", {})
                check(context == reserve.get("metadata", {}).get("authorization_context"), f"model {index}: actual authorization context differs from scoped reservation")
                if admission.get("waiver_scope") == "registered_research":
                    check(config.get("phase") == admission["registration"]["phase"], f"model {index}: actual phase differs from research registration")
                if arm == "C":
                    limits = parsed_sections.get("LIMITS")
                    expected_limits = {"responses": None if cfg.get("max_calls") is None else cfg["max_calls"] - index,
                                       "solver_seconds": approval["max_solver_requested_seconds_per_arm"] - admission["solver_requested_seconds_before_by_arm"].get(arm, 0),
                                       "model_active_seconds_remaining": approval["total_active_wall_seconds"] - admission["active_seconds_before"]}
                    if admission.get("waiver_scope") == "registered_research":
                        expected_limits.update(solver_seconds=admission["registration"]["solver_seconds"] - admission["run_solver_requested_seconds_before"],
                            model_active_seconds_remaining=admission["registration"]["wall_seconds"] - admission["run_active_seconds_before"])
                    if "per_request_solver_seconds" in (limits or {}) or admission.get("waiver_scope") == "registered_research":
                        expected_limits["per_request_solver_seconds"] = min(60, expected_limits["solver_seconds"])
                    if cfg.get("enable_constructive") is True:
                        expected_limits["model_active_seconds_remaining"] -= admission.get("constructor_active_seconds_before", 0)
                        expected_limits.update(per_request_constructor_seconds=min(5., max(0., expected_limits["model_active_seconds_remaining"])),
                            constructor_requested_seconds=admission.get("constructor_requested_seconds_before", 0),
                            constructor_active_seconds=admission.get("constructor_active_seconds_before", 0), constructor_evaluation_cap=250000)
                    check(limits == expected_limits, f"model {index}: C prompt LIMITS differ from prior applicable ledger consumption")
        if call_id not in finishes:
            missing.append(f"ledger finish for {call_id}")
        else:
            finish = finishes[call_id]
            check(finish["status"] == model.get("status"), f"model {index}: ledger/model status mismatch")
            check(finish.get("details", {}).get("usage") == model.get("usage"), f"model {index}: token usage differs from ledger")
            check(finish.get("details", {}).get("duration_seconds") == model.get("duration_seconds"), f"model {index}: duration differs from ledger")
        native = [e.get("item", {}) for e in events if e.get("type") in ("item.started", "item.updated", "item.completed") and e.get("item", {}).get("type") not in {"agent_message", "reasoning", "error"}]
        completed = [e for e in events if e.get("type") == "turn.completed"]
        check(model.get("native_tool_events") == native, f"model {index}: native tool evidence differs from summary")
        usages = [e["usage"] for e in completed if isinstance(e.get("usage"), dict)]
        for key in ("input_tokens", "cached_input_tokens", "output_tokens", "cache_write_input_tokens", "reasoning_output_tokens"):
            actual_usage = sum(u[key] for u in usages) if usages and all(type(u.get(key)) in (int, float) for u in usages) else None
            check(model.get("usage", {}).get(key) == actual_usage, f"model {index}: {key} differs from raw completed-turn events")
        if model.get("status") == "success":
            check(not native and len(completed) == 1 and not model.get("timed_out"), f"model {index}: successful call violates isolation/completion contract")
            final = read(final_path)
            check(final == model.get("output"), f"model {index}: saved final JSON differs from decoded model output")
            errors.extend(f"model {index}: {error}" for error in _schema_errors(model.get("output"), schema))
        if index in by_model:
            link = by_model[index]
            check(link.get("call_id") == call_id, f"model {index}: controller linkage points to another call")
            check(link.get("response_sha256") == digest(model.get("output")), f"model {index}: controller response hash mismatch")
            check(link.get("status") == model.get("status"), f"model {index}: controller linkage status mismatch")
        if model.get("cost_usd") is not None:
            warnings.append(f"model {index}: non-null monetary cost requires separate billing source verification")

    call_ids = [models[i]["result"]["call_id"] for i in sorted(models)]
    check(len(call_ids) == len(set(call_ids)), "call identity reused across model directories")
    # Verify inputs even for failed attempts before any plan was committed.
    # Legacy failed probes can bind a page by exact saved content without
    # pretending that an accepted plan has an absent decision linkage.
    page_sets, page_fidelity = storage.mapping("page-sets"), []
    for manifest_path in sorted(run.glob("page_manifest_*.json")):
        try:
            plan_index = int(manifest_path.stem.rsplit("_", 1)[1])
            pm = read(manifest_path)
            problem = read(run / f"problem_{plan_index:03d}.json")
            if pm is None or problem is None:
                continue
            pages = [read(run / f"page_{plan_index:03d}_{i:02d}.json") for i in range(pm["page_count"])]
            if any(page is None for page in pages):
                continue
            check(pm.get("observation_end") == trace_manifest.get("horizon"), f"plan {plan_index}: page observation endpoint differs from trace")
            if "page_chars" in cfg:
                check(type(cfg["page_chars"]) is int and 10000 <= cfg["page_chars"] <= 90000 and
                      all(len(json.dumps(page, separators=(",", ":"), allow_nan=False)) <= cfg["page_chars"] for page in pages),
                      f"plan {plan_index}: saved page exceeds declared character limit")
            errors.extend(f"plan {plan_index}: {message}" for message in _verify_pages(problem, pm, pages))
            fidelity = {"plan_index": plan_index, **_page_fidelity(problem, pm, pages)}
            page_fidelity.append(fidelity)
            if pm.get("schema") == "fullfab-compact-paging-v1":
                warnings.append(f"plan {plan_index}: legacy compact v1 omits full-problem metadata/presence; passed evidence does not certify lossless input")
            page_sets[plan_index] = (pm, problem, pages)
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            check(False, f"malformed saved observation pages: {type(exc).__name__}")
    for index in sorted(models):
        model = models[index]
        sections = model["sections"]
        prior = PriorOutputs(model_outputs, index)
        own_tasks = [task for output in prior if isinstance(output, dict) for task in output.get("tasks", [])]
        own_holds = [hold for output in prior if isinstance(output, dict) for hold in output.get("holds", [])]
        if arm == "B":
            metadata, page = sections.get("SCHEMA_AND_LIMITS", {}), sections.get("PAGE")
            page_index = metadata.get("page_index")
            matches = [(pindex, pm, problem, pages) for pindex, (pm, problem, pages) in page_sets.items()
                       if type(page_index) is int and 0 <= page_index < len(pages) and pages[page_index] == page
                       and all(metadata.get(key) == value for key, value in pm.items())]
            check(bool(matches), f"model {index}: B prompt state is not an exact saved full-fab page")
            for name, records in sections.items():
                if name.startswith("YOUR_"):
                    check(isinstance(records, list) and all(record in own_tasks or record in own_holds for record in records),
                          f"model {index}: B own-history input contains unchosen/external advice")
            if matches:
                expected_keys = set(matches[0][1]) | {"page_index", "last_page", "remaining_model_responses"}
                check(set(metadata) == expected_keys, f"model {index}: B input contains undeclared schema/limit metadata")
                check(metadata.get("remaining_model_responses") == (None if cfg.get("max_calls") is None else cfg["max_calls"] - index),
                      f"model {index}: B response allowance differs from run config and completed attempts")
        elif arm == "C":
            summary = sections.get("STATE_DIRECTORY", {})
            matches = []
            for pindex, (pm, problem, pages) in page_sets.items():
                expected = {"time": problem["time"], "horizon_end": problem["horizon_end"], "observation_end": trace_manifest.get("horizon"),
                            "machines": len(problem["machines"]), "operations": len(problem["operations"]), "pages": len(pages),
                            "family_counts": [{"family": group["family"], "machines": len(group["machines"]), "operations": len(group["operations"])} for page in pages for group in page],
                            "methods_available": ["global", cfg.get("solver_method_available", "decomposed")] + (["constructive"] if cfg.get("enable_constructive") is True else [])}
                if pm.get("schema") == "fullfab-compact-paging-v2":
                    expected["problem_metadata"] = {key: value for key, value in problem.items() if key not in ("machines", "operations")}
                if summary == expected:
                    matches.append(pindex)
            check(bool(matches), f"model {index}: C state directory differs from saved full-fab observation")
            own_history = sections.get("OWN_HISTORY", [])
            check(isinstance(own_history, list), f"model {index}: C own-history is not a list")
            if isinstance(own_history, list):
                for entry in own_history:
                    check(isinstance(entry, dict) and entry.get("decision") in prior, f"model {index}: C history contains a decision not made by its prior model calls")
                    if isinstance(entry, dict) and entry.get("decision", {}).get("action") == "read_page":
                        page_index = entry["decision"].get("index")
                        faithful = any(type(page_index) is int and 0 <= page_index < len(page_sets[pindex][2]) and
                                       entry.get("page") == page_sets[pindex][2][page_index] and entry.get("schema") == page_sets[pindex][0]
                                       for pindex in matches)
                        check(faithful, f"model {index}: C page/schema feedback omits or alters complete observation metadata")
    if result:
        check(result.get("model_calls") == len(model_directories), "run model count omits/invents an attempt directory")
        check(result.get("model_call_ids") == call_ids, "run model call IDs differ from durable attempts")
        check(result.get("plans_committed") == len(commits), "run plan count differs from trace")
    own_reserves = [row for row in reserves.values() if Path(row["run_id"]).resolve().is_relative_to(run)]
    check(len(own_reserves) == len(model_directories), "attempt directories and budget reservations differ")
    if commits and not links:
        missing.append("controller_decisions.jsonl required to bind accepted plans to exact model rounds")

    constructor_report = constructor_checker(run, cfg, models, ledger, read, scratch_dir=storage.directory / "constructor")
    resources.enter_context(_closing_constructor(constructor_report["candidates"]))
    errors.extend(constructor_report["errors"])
    missing.extend(constructor_report["missing_evidence"])
    if cfg.get("enable_constructive") is True:
        check(bool(page_fidelity) and all(row["full_problem_lossless_certified"] for row in page_fidelity), "constructive controller requires lossless v2 observations")
    checked_plans, solver_request_count, plan_attributions = 0, 0, []
    solver_requests = sorted(run.glob("solver_request_*.json"))
    solver_files = sorted(run.glob("solver_[0-9]*.json"))
    if arm == "B":
        check(not solver_requests and not solver_files, "B contains solver request/result evidence")
        check(not any(row.get("event") == "solver_reserve" and Path(row.get("run_id", "/")).resolve() == run for row in ledger), "B consumed solver budget")
        if result:
            check(result.get("solver_calls") == 0 and result.get("solver_requested_seconds") == 0, "B reports solver use")
    commit_links = read(run / "plan_commits.jsonl", optional=True, lines=True) or []
    solver_metadata = read(run / "solver_evidence.jsonl", optional=True, lines=True) or []
    solver_reserves = {row["call_id"]: row for row in ledger if row.get("event") == "solver_reserve"}
    solver_finishes = {row["call_id"]: row for row in ledger if row.get("event") == "solver_finish"}
    check(len(solver_reserves) == sum(row.get("event") == "solver_reserve" for row in ledger), "duplicate solver reservation identity")
    check(len(solver_finishes) == sum(row.get("event") == "solver_finish" for row in ledger), "duplicate solver finish identity")
    own_solver_reserves = [row for row in solver_reserves.values() if Path(row.get("run_id", "/")).resolve() == run]
    # Every CP invocation, including failed/unselected attempts, needs exactly
    # one preceding reservation, one immutable model request and one outcome.
    # Without this bijection a closed extra reservation or a dropped request in
    # an uncommitted plan could escape the per-request checks below.
    request_records = [(path, read(path)) for path in solver_requests]
    expected_solver_ids = Counter(row["call_id"] for row in own_solver_reserves)
    request_ids, outcome_ids, request_model_ids = [], [], []
    for path, record in request_records:
        if not isinstance(record, dict):
            continue
        sid = record.get("solver_call_id")
        check(isinstance(sid, str) and bool(sid), "solver request lacks a unique string call identity")
        if isinstance(sid, str):
            request_ids.append(sid)
        model_id = record.get("call_id")
        check(isinstance(model_id, str) and bool(model_id), "solver request lacks explicit model call identity")
        if isinstance(model_id, str):
            request_model_ids.append(model_id)
        suffix = path.stem.rsplit("_", 1)[-1]
        check(suffix.isdigit() and type(record.get("solver_index")) is int and record.get("solver_index") == int(suffix),
              "solver request index differs from its immutable file identity")
    for record in solver_metadata:
        sid = record.get("solver_call_id")
        check(isinstance(sid, str) and bool(sid), "solver outcome lacks a unique string call identity")
        if isinstance(sid, str):
            outcome_ids.append(sid)
    check(len(solver_requests) == len(own_solver_reserves) and Counter(request_ids) == expected_solver_ids,
          "solver requests do not correspond one-to-one with own durable reservations")
    check(len(solver_metadata) == len(own_solver_reserves) and Counter(outcome_ids) == expected_solver_ids,
          "solver outcomes do not correspond one-to-one with own durable reservations")
    check(len(request_model_ids) == len(set(request_model_ids)), "one model solve action was used for repeated CP invocations")
    expected_result_names = {f"solver_{record['solver_index'] + 1:03d}.json" for record in solver_metadata
                             if record.get("status") == "success" and type(record.get("solver_index")) is int}
    check({path.name for path in solver_files} == expected_result_names,
          "solver result files do not match successful invocation outcomes")
    if result and arm == "C":
        check(result.get("solver_calls") == len(own_solver_reserves), "C reported solver count differs from durable reservations")
        check(result.get("solver_requested_seconds") == sum(row["requested_seconds"] for row in own_solver_reserves), "C reported solver budget differs from durable reservations")
    if approval and "max_solver_requested_seconds_per_arm" in approval:
        used_solver = sum(row["requested_seconds"] for row in solver_reserves.values() if row.get("arm") == arm and not row.get("registration_id"))
        check(used_solver <= approval["max_solver_requested_seconds_per_arm"] + 1e-6, "cumulative arm solver reservation exceeds grant")
    for metadata in solver_metadata:
        sid = metadata.get("solver_call_id")
        if sid not in solver_reserves or sid not in solver_finishes:
            missing.append(f"solver {metadata.get('solver_index')}: reservation/finish identity")
            continue
        reservation, finish = solver_reserves[sid], solver_finishes[sid]
        check(reservation.get("arm") == arm and Path(reservation["run_id"]).resolve() == run, "solver ledger reservation belongs to another arm/run")
        check(reservation.get("requested_seconds") == metadata.get("requested_seconds"), "solver requested seconds differ from ledger")
        check(finish.get("status") == metadata.get("status"), "solver status differs from ledger")
    # Failed or unselected solver attempts still have provenance and cost; do
    # not hide them merely because no final plan was ever committed.
    for path in solver_requests:
        request = read(path)
        if request is None:
            continue
        solver_index = int(path.stem.rsplit("_", 1)[1])
        model_index, plan_index = request.get("model_index"), request.get("plan_index")
        if model_index not in models or type(plan_index) is not int:
            missing.append(f"solver {solver_index}: request/model/plan linkage")
            continue
        try:
            model = models[model_index]["result"]
            response = model.get("output")
            check(model.get("status") == "success" and response.get("action") == "solve", "solver request did not originate in a successful model solve action")
            check(request.get("call_id") == model["call_id"] and request.get("response") == response, "solver request differs from exact model choice")
            problem = read(run / f"problem_{plan_index:03d}.json")
            if problem is None:
                continue
            expected_parameters = {"time_limit_seconds": response["seconds"], "seed": response["seed"], "weights": response["weights"],
                                   "max_slots_per_machine": response["slots"], "plan_version": cfg["run_id"] + ":" + str(plan_index)}
            check(request.get("parameters") == expected_parameters and request.get("problem_sha256") == digest(problem),
                  "solver request parameters/problem differ from chosen observed solve")
            meta = [m for m in solver_metadata if m.get("solver_index") == solver_index]
            if len(meta) != 1:
                missing.append(f"solver {solver_index}: exactly one attempt outcome evidence")
                continue
            outcome = meta[0]
            for key in ("solver_call_id", "solver_index", "actual_solver_module", "actual_solver_function", "method", "requested_seconds"):
                if key not in request:
                    missing.append(f"solver {solver_index}: solver_request {key} linkage")
                else:
                    check(request[key] == outcome.get(key), "solver request/outcome linkage differs: " + key)
            check(outcome.get("model_index") == model_index and outcome.get("call_id") == model["call_id"] and outcome.get("plan_index") == plan_index,
                  "solver attempt outcome differs from model/plan identity")
            check(outcome.get("requested_seconds") == response["seconds"] and outcome.get("method") == response["method"], "solver attempt method/budget differs from model choice")
            if outcome.get("status") == "success":
                solved = read(run / f"solver_{solver_index + 1:03d}.json")
                if solved is None:
                    continue
                module, function, version = SOLVERS[response["method"]]
                check(solved.get("model") == version and solved.get("requested_method") == response["method"], "saved solver result is not the chosen shared solver method")
                check(outcome.get("actual_solver_module") == module and outcome.get("actual_solver_function") == function, "solver attempt used a different implementation")
                check(outcome.get("solver_result_sha256") == digest(solved), "solver attempt result hash mismatch")
                errors.extend(f"solver {solver_index}: {message}" for message in _heuristic_errors(solved, response["method"]))
                finish = solver_finishes.get(outcome.get("solver_call_id"), {})
                check(finish.get("details", {}).get("solver_status") == solved.get("solver_status") and
                      finish.get("details", {}).get("wall_seconds") == solved.get("wall_seconds"), "solver ledger outcome differs from saved result")
            elif outcome.get("status") == "failed":
                check(bool(outcome.get("error")), "failed solver outcome has no preserved failure reason")
            else:
                missing.append(f"solver {solver_index}: terminal solver attempt outcome")
        except (KeyError, TypeError, ValueError) as exc:
            check(False, f"solver {solver_index}: malformed evidence ({type(exc).__name__})")

    for plan_index, commit in enumerate(commits):
        try:
            problem = read(run / f"problem_{plan_index:03d}.json")
            page_manifest = read(run / f"page_manifest_{plan_index:03d}.json")
            raw = read(run / f"raw_plan_{plan_index:03d}.json")
            if problem is None or page_manifest is None or raw is None:
                continue
            pages = [read(run / f"page_{plan_index:03d}_{i:02d}.json") for i in range(page_manifest["page_count"])]
            if any(page is None for page in pages):
                continue
            errors.extend(f"plan {plan_index}: {message}" for message in _verify_pages(problem, page_manifest, pages))
            decisions = sorted((link for link in links if link.get("plan_index") == plan_index), key=lambda x: x["model_index"])
            for link in decisions:
                check(link.get("input_problem_sha256") == digest(problem), f"plan {plan_index}: decision linked to another problem")
            if not decisions:
                missing.append(f"plan {plan_index}: no model decision links")
                continue
            source_call, source_candidate, source_solver = None, None, None
            if arm == "B":
                staged, holds, reason = [], [], ""
                check(len(decisions) == len(pages), f"plan {plan_index}: B did not explicitly receive all full-fab pages")
                for page_index, page in enumerate(pages):
                    matched = [link for link in decisions if link.get("page_index") == page_index]
                    check(len(matched) == 1, f"plan {plan_index} page {page_index}: missing/duplicate model binding")
                    if len(matched) != 1 or matched[0]["model_index"] not in models:
                        continue
                    model = models[matched[0]["model_index"]]
                    response = model["result"].get("output")
                    check(model["result"].get("status") == "success", "accepted B patch from unsuccessful model call")
                    patch = read(run / f"patch_{plan_index:03d}_{page_index:02d}.json")
                    check(patch == response, f"plan {plan_index} page {page_index}: patch differs from exact model output")
                    if patch is None:
                        continue
                    check(model["sections"].get("PAGE") == page, f"plan {plan_index} page {page_index}: model was shown different state")
                    metadata = model["sections"].get("SCHEMA_AND_LIMITS", {})
                    check(metadata.get("page_index") == page_index and metadata.get("last_page") == (page_index == len(pages) - 1), "B page position in prompt differs from applied patch")
                    for key, value in page_manifest.items():
                        check(metadata.get(key) == value, "B prompt schema/limit differs from saved page manifest: " + key)
                    allowed = {row[0] for group in page for row in group["operations"]}
                    check(all(oid in allowed for task in patch["tasks"] for oid in task["operations"]), "B patch chooses unobserved operations outside its page")
                    check(patch["commit"] == (page_index == len(pages) - 1), "B lacks final explicit commit or committed before observing all pages")
                    for name, records in model["sections"].items():
                        if name.startswith("YOUR_") and isinstance(records, list):
                            check(all(record in staged or record in holds for record in records), "B supplied own-history context contains a task/hold not previously chosen by B")
                    staged.extend(patch["tasks"])
                    holds.extend(patch["holds"])
                    reason = patch["reason"]
                    source_call = model["result"]["call_id"]
                sequence = [(task["machine"], task["sequence"]) for task in staged]
                check(all(type(t["sequence"]) is int for t in staged) and len(sequence) == len(set(sequence)), "B lacks unique explicit integer machine sequence")
                ordered = sorted(staged, key=lambda task: (task["machine"], task["sequence"]))
                operations = {o["operation_id"]: o for o in problem["operations"]}
                tasks = []
                for i, task in enumerate(ordered):
                    selected = [operations[oid] for oid in task["operations"]]
                    tasks.append({"id": str(i), "machine": task["machine"], "lot_ids": [o["lot_id"] for o in selected],
                                  "steps": [o["step"] for o in selected], "visits": [o["visit"] for o in selected],
                                  "operation_ids": task["operations"], "not_before": task["start"]})
                decoded_holds = []
                for hold in holds:
                    decoded = {key: value for key, value in hold.items() if key != "after_sequence"}
                    if hold.get("after_sequence") is not None:
                        indices = [i for i, task in enumerate(ordered) if task["machine"] == hold["machine"] and task["sequence"] == hold["after_sequence"]]
                        check(len(indices) == 1, "B conditional hold has no unique explicitly chosen machine sequence")
                        if len(indices) == 1:
                            decoded["after_task_id"] = str(indices[0])
                    decoded_holds.append(decoded)
                expected_raw = {"version": cfg["run_id"] + ":" + str(plan_index), "created_at": problem["time"],
                                "valid_until": problem["horizon_end"], "freeze_until": problem["time"],
                                "reason": reason, "scope": problem["scope"], "tasks": tasks, "holds": decoded_holds}
                check(raw == expected_raw, f"plan {plan_index}: B raw plan is not an exact deterministic decoding of model choices")
            elif arm == "C":
                history = read(run / f"controller_history_{plan_index:03d}.json")
                if history is None:
                    continue
                check(len(history) == len(decisions), "C saved history omits a model decision, including explicit apply")
                candidates = storage.sequence("plan-candidates")
                for offset, link in enumerate(decisions):
                    model_index = link["model_index"]
                    if model_index not in models or offset >= len(history):
                        continue
                    model = models[model_index]
                    response = model["result"].get("output")
                    check(model["result"].get("status") == "success", "C used an unsuccessful model response")
                    check(history[offset].get("decision") == response, "C history decision differs from exact model output")
                    check(model["sections"].get("OWN_HISTORY") == history[:offset], "C model was shown different own decision/solver history")
                    if response["action"] == "read_page":
                        check(history[offset].get("page") == pages[response["index"]], "C page feedback differs from full-fab page")
                        check(history[offset].get("schema") == page_manifest, "C page feedback schema differs from saved complete observation metadata")
                    elif response["action"] == "solve" and response.get("method") == "constructive":
                        candidate = constructor_report["candidates"].get(model_index)
                        if candidate is None:
                            missing.append(f"C model {model_index}: exact constructor candidate evidence")
                            candidates.append((None, None))
                        else:
                            check(candidate["plan_index"] == plan_index, "constructor candidate belongs to another plan")
                            candidates.append((candidate["solved"] if candidate["valid"] else None, None))
                    elif response["action"] == "solve":
                        matches = []
                        for path in solver_requests:
                            request = read(path)
                            if request and request.get("model_index") == model_index:
                                matches.append((path, request))
                        if len(matches) != 1:
                            missing.append(f"C model {model_index}: exact solver_request linkage")
                            continue
                        path, request = matches[0]
                        solver_index = int(path.stem.rsplit("_", 1)[1])
                        solver_request_count += 1
                        check(request.get("response") == response and request.get("call_id") == model["result"]["call_id"], "C solve request differs from chosen model action")
                        check(request.get("problem_sha256") == digest(problem), "C solver used a different observed problem")
                        parameters = {"time_limit_seconds": response["seconds"], "seed": response["seed"], "weights": response["weights"],
                                      "max_slots_per_machine": response["slots"], "plan_version": cfg["run_id"] + ":" + str(plan_index)}
                        check(request.get("parameters") == parameters, "C solver parameters differ from model choices")
                        solved = read(run / f"solver_{solver_index + 1:03d}.json")
                        if solved is None:
                            continue
                        check(response["method"] in SOLVERS, "C requested unknown solver method")
                        module, function, version = SOLVERS[response["method"]]
                        check(solved.get("requested_method") == response["method"] and solved.get("model") == version, "C requested method differs from executed shared solver model")
                        meta = [m for m in solver_metadata if m.get("solver_index") == solver_index]
                        if len(meta) != 1:
                            missing.append(f"solver {solver_index}: solver_evidence linkage")
                        else:
                            m = meta[0]
                            check(m.get("actual_solver_module") == module and m.get("actual_solver_function") == function, "C solver implementation differs from model-selected method")
                            check(m.get("solver_result_sha256") == digest(solved), "C solver evidence hash differs from saved candidate")
                            check(m.get("model_index") == model_index and m.get("call_id") == model["result"]["call_id"] and m.get("plan_index") == plan_index,
                                  "solver evidence is not linked to this model decision/plan")
                            check(m.get("method") == response["method"] and m.get("requested_seconds") == response["seconds"], "solver evidence differs from chosen method/budget")
                        valid = solved.get("solver_status") in FEASIBLE_STATUSES
                        candidates.append((solved if valid else None, solver_index))
                        feedback = history[offset].get("result", {})
                        for key in FEEDBACK_FIELDS:
                            check(feedback.get(key) == solved.get(key), "C solver feedback differs from saved solver: " + key)
                        check(feedback.get("candidate_index") == len(candidates) - 1 and feedback.get("valid_candidate") == valid, "C candidate index/status feedback differs from saved solver")
                        check(feedback.get("plan_sha256") == digest(solved["plan"]), "C inspected candidate hash differs from actual candidate")
                        check(feedback.get("tasks_preview") == solved["plan"]["tasks"][:12], "C inspected task preview differs from actual candidate")
                        check(feedback.get("task_count") == len(solved["plan"]["tasks"]) and feedback.get("unplanned_operations_count") == len(solved.get("unplanned_operations", {})), "C candidate coverage feedback differs from saved solver")
                    elif response["action"] == "apply":
                        candidate = response["index"]
                        check(offset == len(decisions) - 1, "C apply was not final decision for this plan")
                        check(type(candidate) is int and 0 <= candidate < len(candidates), "C applied missing/uninspected candidate")
                        if type(candidate) is int and 0 <= candidate < len(candidates):
                            chosen, source_solver = candidates[candidate]
                            check(chosen is not None, "C applied infeasible/failed candidate")
                            if chosen:
                                check(raw == chosen["plan"], "C raw plan differs from explicitly selected candidate")
                            check(history[offset].get("applied_candidate") == candidate and history[offset].get("plan_sha256") == digest(raw), "C explicit apply history differs from raw plan")
                            source_candidate = candidate
                            source_call = model["result"]["call_id"]
                check(source_call is not None, "C plan has no explicit model apply")
            expected_commit = _crop(raw, trace_manifest["horizon"], trace_manifest["controlled_machine_ids"])
            check(commit["plan"] == expected_commit, f"plan {plan_index}: trace commitment differs from disclosed raw plan clipping")
            linked_commit = [item for item in commit_links if item.get("plan_index") == plan_index]
            if len(linked_commit) != 1:
                missing.append(f"plan {plan_index}: plan_commits.jsonl exact commit linkage")
            else:
                item = linked_commit[0]
                check(item.get("model_call_id") == source_call, "plan commit was not attributed to final explicit model commit/apply")
                check(item.get("raw_plan_sha256") == digest(raw) and item.get("committed_plan_sha256") == digest(commit["plan"]), "plan commit hash mismatch")
                if arm == "C":
                    # These redundant fields were not emitted by the original
                    # controller. The complete explicit apply chain above is
                    # sufficient; if present, they must agree with that chain.
                    for key, inferred in (("source_candidate_index", source_candidate), ("source_solver_index", source_solver)):
                        if key in item:
                            check(item[key] == inferred, "C commit candidate/solver attribution mismatch")
            plan_attributions.append({"plan_index": plan_index, "model_call_id": source_call,
                                      "source_candidate_index": source_candidate, "source_solver_index": source_solver,
                                      "raw_plan_sha256": digest(raw), "committed_plan_sha256": digest(commit["plan"])})
            checked_plans += 1
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            check(False, f"plan {plan_index}: malformed controller evidence ({type(exc).__name__}: {exc})")

    if result and result.get("status") == "success":
        check(bool(result.get("full_window_completed")) and bool(trace) and trace[-1].get("kind") == "terminal", "run claims success without a complete terminal trace")
    if any(path.name.startswith("solver_") for path in solver_requests) and not solver_metadata:
        missing.append("solver_evidence.jsonl for executed solver attempts")
    status = "failed" if errors else "partial" if missing else "passed"
    return {"audit_version": VERSION, "audit_status": status, "valid": status == "passed",
            "errors": errors, "missing_evidence": sorted(set(missing)), "warnings": warnings,
            "arm": arm, "run_status": result.get("status") if result else "unfinished",
            "successful_full_window": bool(status == "passed" and result and result.get("status") == "success" and result.get("full_window_completed")),
            "model_attempt_directories": len(model_directories), "completed_model_records": len(models),
            "committed_plans": len(commits), "attribution_checked_plans": checked_plans,
            "model_call_ids": call_ids, "controller_decision_links": len(links),
            "checked_solver_requests_for_committed_plans": solver_request_count,
            "checked_constructor_attempts": constructor_report["attempts"],
            "reconstructed_plan_attributions": plan_attributions,
            "budget_admission_replay": budget_replay,
            "page_representation_audits": page_fidelity,
            "all_saved_problem_pages_lossless_certified": bool(page_fidelity) and all(row["full_problem_lossless_certified"] for row in page_fidelity),
            "monetary_cost_certified": False, "physics_and_opportunity_replay_required_separately": True,
            "evidence_sha256": hashes,
            "scope": "independent saved-evidence attribution, not a successful-production or official-simulator-equivalence certificate"}

