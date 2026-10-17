"""Static inspection of a saved B decision. No runtime, solver, transport or DB access.

Only reads hash-addressed objects listed in the pre-existing snapshot. Writes
derived evidence here. It never loads private simulator state or advances time.
"""
from collections import Counter
from pathlib import Path
import hashlib
import json
import sys
import zlib

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "analysis/B_coverage_ablation_20261015/workspace"))
from src.smt_fullfab.harness.presentation import unpack


def sha(b):
    return hashlib.sha256(b).hexdigest()


def read(p):
    return json.loads(p.read_bytes())


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


snapshot_path = ROOT / "analysis/replan_frequency_20261015/snapshot_index.json"
snapshot = read(snapshot_path)
source = Path(snapshot["run_directory"])
records = {(ns, key): ref for ns, key, ref in snapshot["records"]}
objects_read = set()


def raw(ref):
    b = zlib.decompress((source / "objects" / (ref + ".z")).read_bytes())
    assert sha(b) == ref
    objects_read.add(ref)
    return b


def get(ref):
    return json.loads(raw(ref))


def walk(x, path=()):
    if isinstance(x, dict):
        yield path, x
        for k, value in x.items():
            yield from walk(value, (*path, k))
    elif isinstance(x, list):
        for i, value in enumerate(x):
            yield from walk(value, (*path, i))


intervals = read(ROOT / "analysis/replan_frequency_20261015/execution_intervals.json")
row = next(r for r in intervals if r["ordinal"] == 136)
context_ref = records["contexts", row["context_ref"]]
full = get(context_ref)
next_ref = records["contexts", snapshot["head"]["context_ref"]]
next_full = get(next_ref)
assert full["time"] == row["from"] and next_full["time"] == row["to"]
problem = full["problem"]
now = full["time"]
machines = {m["machine"]: m for m in problem["machines"]}
ops = problem["operations"]
op_by_id = {o["operation_id"]: o for o in ops}
calls = []

for (ns, key), ref in records.items():
    if ns != "attempts":
        continue
    a = get(ref)
    number = a["index"] + 1
    if number not in row["call_numbers"]:
        continue
    prompt = raw(a["prompt_ref"]).decode()
    frame = unpack(json.loads(prompt[prompt.index("\n{") + 1:]))
    ctx = frame["context"]
    assert ctx["pending_base_task_ids"] == [] and ctx["pending_tasks"] == []
    action = get(a["raw_ref"])
    action = action.get("action", action)
    response = get(a["response_ref"])
    inline = ctx["pertinent_operations"]
    family_hits = [{"path": list(path), "value": value} for path, value in walk(frame)
                   if value.get("family") == "Dielectric_BE_27" or value.get("machine") == 747]
    assert not family_hits
    assert len(inline) == 48 and all(o["family"] == "DefMet_BE_33" for o in inline)
    (OUT / f"call_{number}.prompt.txt").write_bytes(prompt.encode())
    save(f"call_{number}.action.json", action)
    save(f"call_{number}.response.json", response)
    save(f"call_{number}.frame_unpacked.json", frame)
    calls.append({
        "call": number, "attempt_id": a["attempt_id"], "tool": action["tool"],
        "prompt_sha256": a["prompt_ref"], "raw_action_sha256": a["raw_ref"],
        "response_sha256": a["response_ref"], "characters": len(prompt),
        "usage": a["usage"], "duration_seconds": a["duration_seconds"],
        "inline_operations": len(inline), "inline_ready": sum(not o["conditional"] for o in inline),
        "inline_conditional": sum(o["conditional"] for o in inline),
        "inline_families": dict(Counter(o["family"] for o in inline)),
        "pertinent_total": ctx["pertinent_operations_total"],
        "pertinent_omitted": ctx["pertinent_operations_omitted"],
        "dielectric_catalog_only": ctx["families"]["Dielectric_BE_27"],
        "dielectric_detail_hits_anywhere_in_frame": family_hits,
        "has_same_context_fact_memory": "same_context_fact_memory" in frame,
        "has_advanced_seconds_feedback": "advanced_seconds" in prompt,
        "queries": action.get("queries"),
        "example_visibility": {oid: [list(path) for path, value in walk(frame)
                                     if value.get("operation_id") == oid]
                               for oid in ["w1093:312:1", "w1098:296:1", "w1460:146:1",
                                           "w1091:315:1", "w1090:314:1"]},
        "inline_conditional_examples": [o for o in inline if o["operation_id"] in
                                        ["w1090:314:1", "w1758:324:1", "w1953:361:1"]],
    })
calls.sort(key=lambda c: c["call"])
assert [c["tool"] for c in calls] == ["read_entities", "propose_delta", "apply_candidate"]

backlog = [o for o in ops if 747 in o["eligible_machines"] and not o["conditional"]]
next_backlog = [o for o in next_full["problem"]["operations"]
                if 747 in o["eligible_machines"] and not o["conditional"]]
assert len(backlog) == len(next_backlog) == 74
assert {o["operation_id"] for o in backlog} == {o["operation_id"] for o in next_backlog}
for o in backlog:
    assert not o["predecessor_ids"] and not o["initial_virtual_predecessors"]
    assert o["batch_min"] == o["batch_max"] == 1
    assert o["setup"] == "" and o["sampling_percent"] == 100 and o["rework_percent"] == 0
    assert o["qualification_basis"] == "source family eligibility" and not o.get("qualification_uncertain")
    assert o["release_time"] <= now and o["lot_id"] != "w1091"

near_family_machines = [m for m in problem["machines"] if m["family"] == "Dielectric_BE_27"
                        and m["currently_busy"] and not m["currently_down"]
                        and m["available_at"] <= now + 120]
assert [m["machine"] for m in near_family_machines] == [738, 739, 741, 744, 746, 747]
assert all(m["min_left"] == 0 and m["current_setup"] == "" and len(m["processing_until"]) == 1
           for m in near_family_machines)
assert all(all(m["machine"] in o["eligible_machines"] for m in near_family_machines) for o in backlog)

related_examples = [op_by_id[k] for k in ["w1460:146:1", "w1091:315:1", "w1090:314:1"]]
source_hashes = read(ROOT / "analysis/B_planning_diagnosis_20261015/evidence.json")["summary"]["source_sha256"]
source_checks = {p: sha((ROOT / p).read_bytes()) == h for p, h in source_hashes.items()}
assert all(source_checks.values())

evidence = {
    "scope": "Saved original B round 136; static public-state/prompt/action inspection only",
    "snapshot_captured_local": snapshot["captured_local"],
    "not_a_current_live_snapshot": True,
    "new_model_calls": 0, "new_simulation_runs": 0, "live_writes": 0,
    "snapshot_sha256": sha(snapshot_path.read_bytes()),
    "context_object_sha256": context_ref, "next_context_object_sha256": next_ref,
    "interval": row, "calls": calls,
    "current_trigger_machines": [machines[x] for x in [312, 313]],
    "current_trigger_ready_ops": [o for o in ops if not o["conditional"] and o["family"] == "DefMet_BE_33"],
    "backlog_747": backlog, "backlog_747_unchanged_at_next_trigger": True,
    "nearby_dielectric_machines": near_family_machines,
    "next_observed_747": next(m for m in next_full["problem"]["machines"] if m["machine"] == 747),
    "other_public_examples": related_examples,
    "other_example_machines": [machines[x] for x in [1026, 1055]],
    "base_pending_tasks": [],
    "base_dispatched_task_ids": full["execution_state"]["dispatched_task_ids"],
    "forecast_limitations": problem["forecast_limitations"],
    "interpretation_limits": [
        "74 alternatives share machines; this is not 74 simultaneous tasks or a quality ranking.",
        "Six public forecasts support considering six distinct waiting lots, not guaranteed release times.",
        "The 0.087-second actual release is hindsight used to explain the observed stop, not advance information.",
        "No alternative plan was compiled, applied, simulated or optimized; no counterfactual savings or quality claim.",
        "Input presence/absence is observable; internal model attention or motivation is not.",
        "Known inherited CQT/binding semantic limitations are not repaired by this analysis.",
    ],
    "source_hashes_match_previous_diagnosis": source_checks,
    "read_object_sha256": sorted(objects_read),
}
save("evidence.json", evidence)
print(json.dumps({"round": row["ordinal"], "calls": [{k: c[k] for k in
      ["call", "tool", "characters", "inline_ready", "inline_conditional", "dielectric_detail_hits_anywhere_in_frame"]}
      for c in calls], "backlog747": len(backlog), "near_machines": [m["machine"] for m in near_family_machines],
      "backlog_examples": [o["operation_id"] for o in backlog[:6]],
      "other_examples": [{k:o[k] for k in ["operation_id", "conditional", "eligible_machines", "sampling_percent", "setup"]} for o in related_examples],
      "source_hashes_unchanged": all(source_checks.values())}, ensure_ascii=False, indent=2))
