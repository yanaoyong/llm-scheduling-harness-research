"""Public protocol and host-owned identities; no scheduling decisions."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sys
import importlib.metadata

PROTOCOL = "scheduling-harness-v1.10"
SEMANTICS = "smt-fullfab-development-paused-cold-v1"
ROOT = Path(__file__).resolve().parents[3]
STATES = ("INIT", "OBSERVED", "DECIDING", "CANDIDATE", "SELECTED",
          "COMMITTING", "COMMITTED", "EXECUTING", "RECONCILING",
          "STOPPED", "AUDITING", "CLOSED")
TOOLS = {
    "get_context": ("context_ref",),
    "read_entities": ("context_ref", "queries"),
    "read_artifact": ("artifact_ref", "path", "format", "offset", "count"),
    "propose_delta": ("context_ref", "request_id", "delta"),
    "apply_candidate": ("context_ref", "request_id", "candidate_ref"),
    "write_notes": ("context_ref", "request_id", "text", "expected_version"),
    "begin_proposal": ("context_ref", "request_id", "proposal_id"),
    "begin_alternative_proposal": ("context_ref", "request_id", "proposal_id", "reviewed_candidate_ref", "reason"),
    "append_proposal": ("context_ref", "request_id", "proposal_ref", "expected_version", "chunk_id", "set_fields", "append_arrays"),
    "finalize_proposal": ("context_ref", "request_id", "proposal_ref", "expected_version"),
    "construct_candidate": ("context_ref", "request_id", "algorithm_id", "parameters", "budget_seconds"),
    "optimize_candidate": ("context_ref", "request_id", "algorithm_id", "candidate_ref", "parameters", "budget_seconds"),
}
CLASSICAL = {"construct_candidate", "optimize_candidate"}
CAPABILITIES = {arm: sorted(set(TOOLS) - (CLASSICAL if arm == "B" else set()))
                for arm in ("A", "B", "C", "C-fixed")}
SEMANTIC_COVERAGE = [
    {"constraint": "identity_qualification_batch_freeze_physics_opportunity",
     "implementation": "implemented", "evidence_availability": "available",
     "verdict": "not_evaluated", "scope": SEMANTICS},
    {"constraint": "cqt", "implementation": "not_implemented",
     "evidence_availability": "partial", "verdict": "not_evaluated",
     "scope": SEMANTICS, "reason": "Historical CQT timer starts and full runtime semantics are absent"},
    {"constraint": "historical_binding", "implementation": "partial",
     "evidence_availability": "partial", "verdict": "undetermined",
     "scope": SEMANTICS, "reason": "Known bindings checked; missing history is not defaulted"},
    {"constraint": "official_calibration_and_online", "implementation": "not_implemented",
     "evidence_availability": "partial", "verdict": "not_evaluated", "scope": SEMANTICS},
]


class HarnessError(ValueError):
    def __init__(self, code, detail, **evidence):
        self.code, self.detail, self.evidence = code, detail, evidence
        super().__init__(f"{code}: {detail}")

    def response(self):
        return {"status": "rejected", "error": {"code": self.code, "detail": self.detail,
                                               "evidence": self.evidence}}


def require(condition, code, detail, **evidence):
    if not condition:
        raise HarnessError(code, detail, **evidence)


def encode(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def encode_model_schema(value):
    """Preserve decoding order; canonical state hashing must not sort schemas."""
    return json.dumps(value, ensure_ascii=True, sort_keys=False, separators=(",", ":"), allow_nan=False).encode()


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def digest(value):
    return sha_bytes(encode(value))


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, val in items:
            require(key not in result, "duplicate_json_key", key)
            result[key] = val
        return result
    def invalid(value):
        raise HarnessError("nonfinite_json", value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def within_cap(value, cap):
    """None explicitly removes a count/token ceiling; usage is still measured."""
    return cap is None or value <= cap


def fingerprint(root=ROOT):
    """Bind executable Python, dependencies and source data; no run outputs."""
    files = {}
    for relative in ("src", "vendor/PySCFabSim-revised/simulation"):
        for path in sorted((root / relative).rglob("*.py")):
            files[str(path.relative_to(root))] = sha_bytes(path.read_bytes())
    lock = root / "requirements.lock"
    files["requirements.lock"] = sha_bytes(lock.read_bytes())
    packages = {}
    for line in lock.read_text().splitlines():
        if "==" in line:
            name = line.split("==")[0]
            try:
                packages[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                packages[name] = None
    data = {str(p.relative_to(root)): sha_bytes(p.read_bytes())
            for p in sorted((root / "data/smt/SMT2020_LVHM").rglob("*")) if p.is_file()}
    value = {"files": files, "data": data, "python": sys.version,
             "packages": packages, "protocol": PROTOCOL, "semantics": SEMANTICS}
    return {**value, "sha256": digest(value)}


def default_config(arm="B", *, seconds=3600, seed=1701):
    return {"protocol_version": PROTOCOL, "semantic_profile_id": SEMANTICS,
            "arm": arm, "seed": seed, "window_seconds": seconds, "period_seconds": 1800,
            "plan_seconds": 14400, "lookahead_depth": 2, "time_mode": "paused_during_decision",
            "initialization": "registered_cold_start", "scope": "all_physical_machines",
            "priority_weights": {"10": 1, "20": 2, "30": 3},
            "model": {"name": "gpt-6-astra", "reasoning_effort": "medium", "timeout_seconds": 600,
                      "automatic_retries": 0},
            "limits": {"attempts": 250, "tokens": 6000000, "model_seconds": 10800,
                       "wall_seconds": 14400, "cleanup_seconds": 900, "storage_bytes": 4 * 1024**3,
                       "token_reserve_per_call": 100000, "classical_seconds": 720,
                       "classical_requests": 250, "context_chars": 120000,
                       "same_error_limit": 3, "same_read_limit": 3, "zero_progress_limit": 3},
            "unknown_usage_policy": "freeze_new_calls", "fallback": "none", "capacity_experiment": None,
            "capabilities": CAPABILITIES[arm], "semantic_coverage": deepcopy(SEMANTIC_COVERAGE)}


def validate_config(config):
    expected = set(default_config())
    require(type(config) is dict and set(config) == expected, "config_schema", "Exact v1 configuration required")
    from .capacity_config import POLICY, DEADLINE_POLICY
    semantic = (config['capacity_experiment'].get('policy') if config.get('capacity_experiment') else SEMANTICS)
    require(semantic in (POLICY, DEADLINE_POLICY, SEMANTICS) and config["protocol_version"] == PROTOCOL and config["semantic_profile_id"] == semantic,
            "version", "Unsupported protocol or semantics")
    arm = config["arm"]
    require(arm in CAPABILITIES and config["capabilities"] == CAPABILITIES[arm], "capabilities", "Frozen arm capability set differs")
    require(config["scope"] == "all_physical_machines" and config["time_mode"] == "paused_during_decision"
            and config["fallback"] == "none" and config["unknown_usage_policy"] in ("freeze_new_calls", "bounded_terminated_failures"),
            "semantic_change", "Full responsibility, paused time and no fallback required")
    for key in ("window_seconds", "period_seconds", "plan_seconds"):
        require(number(config[key]) and config[key] > 0, "config_value", key)
    require(type(config["seed"]) is int and type(config["lookahead_depth"]) is int and config["lookahead_depth"] > 0,
            "config_value", "Exact integer seed/depth required")
    require(config["semantic_coverage"] == SEMANTIC_COVERAGE, "semantic_change", "Coverage cannot be silently upgraded")
    require(config["initialization"] in ("registered_cold_start", "registered_saved_state", "registered_common_snapshot"), "initialization", "Explicit initialization profile required")
    require(config["priority_weights"] == {"10": 1, "20": 2, "30": 3}, "priority_weights", "Frozen evaluation weights differ")
    require(type(config["model"]) is dict and set(config["model"]) == set(default_config()["model"]), "model_config", "Exact model configuration required")
    require(type(config["model"]["name"]) is str and bool(config["model"]["name"])
            and config["model"]["reasoning_effort"] in ("low", "medium", "high", "xhigh", "max"), "model_config", "Explicit model and effort required")
    require(number(config["model"]["timeout_seconds"]), "model_config", "Finite timeout required")
    require(type(config["limits"]) is dict, "limits", "Resource account required")
    require(set(config["limits"]) == set(default_config()["limits"]), "limits", "Every resource limit must be explicit")
    for key, value in config["limits"].items():
        if key in ("attempts", "tokens") and value is None:
            continue
        require(number(value) and value > 0, "limits", key)
    for key in ("attempts", "tokens", "storage_bytes", "token_reserve_per_call", "classical_requests", "context_chars", "same_error_limit", "same_read_limit", "zero_progress_limit"):
        require(type(config["limits"][key]) is int or (key in ("attempts", "tokens") and config["limits"][key] is None), "limits", key + " must be an integer or an explicitly uncapped model account")
    require(config["limits"]["cleanup_seconds"] < config["limits"]["wall_seconds"], "limits", "Cleanup must fit inside wall budget")
    require(config["model"]["automatic_retries"] == 0 and 0 < config["model"]["timeout_seconds"] <= 600,
            "model_config", "No automatic retries; timeout <= 600 seconds")
    from .capacity_config import validate_capacity
    validate_capacity(config)
    return deepcopy(config)


def validate_action(action, arm):
    require(type(action) is dict and type(action.get("tool")) is str, "action_schema", "One action object per output")
    tool = action["tool"]
    require(tool in CAPABILITIES[arm], "capability", "Tool forbidden or unknown", tool=tool, arm=arm)
    allowed = set(TOOLS[tool]) | {"tool"}
    if tool == "get_context":
        allowed |= {"since_context_ref"}
    if tool == "apply_candidate":
        allowed |= {"selection_note", "machine_reviews"}
    require(set(TOOLS[tool]) | {"tool"} <= set(action) <= allowed, "action_schema", "Missing or additional fields", tool=tool)
    for key in ("context_ref", "request_id", "candidate_ref", "artifact_ref", "proposal_ref", "proposal_id"):
        if key in action:
            require(type(action[key]) is str and 0 < len(action[key]) <= 200, "identity", key)
    encode(action)
    return tool
