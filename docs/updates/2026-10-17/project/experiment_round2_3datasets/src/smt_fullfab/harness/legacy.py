"""Read-only historical fixture adapter. Never edits historical evidence."""
import base64
from copy import deepcopy
from pathlib import Path

from ..B_delta_assembly import DeltaAssembly
from ..plan_delta import compile_plan_delta
from .contracts import digest, require, sha_bytes, strict_json


def load_fragment(plan_dir):
    path = Path(plan_dir).resolve()
    boot_path, interaction_path = path / "bootstrap.json", path / "interaction_evidence.json"
    boot, interaction = (strict_json(p.read_bytes()) for p in (boot_path, interaction_path))
    candidate = interaction["selection"]["candidate"]
    chosen = candidate["draft_id"]
    assembly = DeltaAssembly(chosen, candidate["anchors"])
    raw_sources = []
    for row in interaction["history"]:
        raw = base64.b64decode(row["raw_output_base64"], validate=True)
        require(sha_bytes(raw) == row["raw_output_sha256"], "legacy_raw_hash", str(path))
        response = strict_json(raw)
        request = response["request"]
        if request["kind"] == "assembly_action" and request["action"]["draft_id"] == chosen:
            result = assembly.submit(request["action"])
            raw_sources.append({"call_id": row["call_id"], "model_index": row["model_index"], "raw_sha256": sha_bytes(raw), "assembly_status": result["status"]})
    sealed = assembly.export_evidence()["sealed"]
    require(sealed is not None and digest(sealed["delta"]) == digest(candidate["delta"]), "legacy_delta_source", "Historical raw chunks do not reproduce selected delta")
    # This is the historical pure interface. The new tool is checked separately
    # against this canonical result under an equivalent saved physical state.
    old = compile_plan_delta(boot["base_plan"], boot["problem"], boot["execution_state"], sealed["delta"], source_sha256=boot["source_sha256"])
    require(digest(old["plan"]) == digest(candidate["compiled"]["plan"]), "legacy_plan_mismatch", "Saved plan and raw decisions differ")
    index = int(path.name.split("_")[-1])
    snapshot = path.parent / (f"plan_{index - 1:05d}/checkpoint_after.json" if index > 1 else "physical/restored_initial.json")
    value = strict_json(snapshot.read_bytes())
    require(digest(value["state"]) == value["state_sha256"], "legacy_snapshot_hash", str(snapshot))
    state = deepcopy(value["state"])
    trace = state.pop("trace")
    require(state["t"] == boot["problem"]["time"] and digest(state["plan"]) == digest(boot["base_plan"]), "legacy_start", "Snapshot and public bootstrap differ")
    # Loading a historical snapshot appends a bookkeeping marker after the real
    # coverage/invalidity trigger. It must not become a fabricated periodic event.
    last = next(e for e in reversed(trace) if e["kind"] != "snapshot_loaded")
    if last["kind"] == "coverage_gap":
        stop = {"reason": "uncovered_demand", "machines": last["machines"], "time": state["t"]}
    elif last["kind"] == "plan_invalidated":
        stop = {"reason": "plan_invalidated", "task": last["task_id"]}
    else:
        stop = {"reason": "periodic_replan", "time": state["t"]}
    state["last_stop"] = stop
    sources = {str(p): sha_bytes(p.read_bytes()) for p in (boot_path, interaction_path, snapshot)}
    return {"initial": {"state": state, "trace": trace, "parent": {"kind": "historical_B_saved_state", "sources": sources}},
            "bootstrap": boot, "delta": sealed["delta"], "old_compiled": old,
            "raw_sources": raw_sources, "sources": sources,
            "edits": sum(len(sealed["delta"][kind][op]) for kind in ("tasks", "holds") for op in ("cancel_ids", "replace", "add"))}


def public_delta(fragment):
    # Only technical context anchors are rebound by the new run. Production
    # fields, empty arrays, order policy and all numeric values remain exact.
    return {k: deepcopy(v) for k, v in fragment["delta"].items() if k not in ("schema", "anchors")}
