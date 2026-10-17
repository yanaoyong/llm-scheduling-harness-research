"""Pure encoding and error contracts; no simulator or runtime dependencies."""
import hashlib
import json

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
