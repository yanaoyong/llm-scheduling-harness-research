#!/usr/bin/env python3
"""Verify this publication against its manifest; no external dependencies."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / "publication/manifest.json").read_text())
errors = []
for item in manifest["files"]:
    p = root / item["path"]
    if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != item["public_sha256"]:
        errors.append(item["path"])
print(json.dumps({"status": "passed" if not errors else "failed", "files_checked": len(manifest["files"]), "mismatches": errors}))
raise SystemExit(bool(errors))
