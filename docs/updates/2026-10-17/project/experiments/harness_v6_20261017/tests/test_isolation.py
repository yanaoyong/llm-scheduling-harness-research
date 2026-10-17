import hashlib
import json
from pathlib import Path


def test_copy_manifest_hashes():
    root=Path(__file__).resolve().parents[1]
    repo=next(p for p in root.parents if (p/'.git').exists())
    manifest=json.loads((root/'isolation_manifest.json').read_text())
    for entry in manifest['files']:
        source=(repo/entry['source_path']).read_bytes()
        target=(root/entry['path']).read_bytes()
        assert hashlib.sha256(source).hexdigest()==entry['source_sha256']==entry['initial_copy_sha256']
        assert hashlib.sha256(target).hexdigest()==entry['copy_sha256']
        assert (source!=target)==entry['modified']
