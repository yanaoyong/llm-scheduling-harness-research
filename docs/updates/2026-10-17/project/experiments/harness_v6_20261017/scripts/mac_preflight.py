#!/usr/bin/env python3
"""Read-only Mac preflight. --version is not an authentication test."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
from harness_v6.codex_runner import CodexRunner


def hashes(manifest, roots):
    """Manifest paths are relative to named physical/data/vendor/evidence roots."""
    rows = []
    for category, root in roots.items():
        root = Path(root).resolve()
        expected = manifest.get(category)
        if not isinstance(expected, dict) or not expected:
            rows.append((category+' hashes', False, 'missing nonempty trusted SHA256 map')); continue
        for name, wanted in sorted(expected.items()):
            path = (root/name).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                rows.append((category+'/'+name, False, 'missing file or path outside root')); continue
            h = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024*1024), b''): h.update(block)
            rows.append((category+'/'+name, h.hexdigest() == wanted, h.hexdigest()))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('physical-root','data-dir','vendor-dir','evidence-root','hash-manifest',
                'codex-binary','codex-version','tiktoken-version','output'):
        parser.add_argument('--'+key, required=True)
    parser.add_argument('--branch', default='feat/harness-v6-codex-runner')
    args = parser.parse_args()
    rows = []
    def check(name, fn):
        try:
            passed, detail = fn(); rows.append((name, bool(passed), str(detail)))
        except Exception as exc: rows.append((name, False, str(exc)))
    check('Python', lambda: (sys.version_info[:2] in ((3,12),(3,13)), sys.version))
    check('venv', lambda: (sys.prefix != sys.base_prefix, sys.prefix))
    def branch():
        actual = subprocess.check_output(['git','branch','--show-current'], text=True).strip()
        return actual == args.branch, actual
    check('branch', branch)
    check('physical environment', lambda: ((Path(args.physical_root)/'src/smt/environment.py').is_file(), args.physical_root))
    check('tiktoken version', lambda: (importlib.metadata.version('tiktoken') == args.tiktoken_version, importlib.metadata.version('tiktoken')))
    def tokenizer():
        cache = Path(os.environ['TIKTOKEN_CACHE_DIR'])
        # Verify a populated cache before calling tiktoken (no implicit download).
        if not cache.is_dir() or not any(p.is_file() and p.stat().st_size for p in cache.iterdir()):
            return False, 'prepopulate trusted o200k cache before preflight'
        import tiktoken
        # Loading is permitted only with the known o200k URL cache key present.
        key = hashlib.sha1(b'https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken').hexdigest()
        if not (cache/key).is_file(): return False, 'o200k cache file missing: '+key
        import inspect, re
        from tiktoken_ext.openai_public import o200k_base
        expected = re.search(r'expected_hash=[\"\']([0-9a-f]{64})', inspect.getsource(o200k_base))
        if expected is None or hashlib.sha256((cache/key).read_bytes()).hexdigest() != expected.group(1):
            return False, 'o200k cache hash invalid or tokenizer source unsupported; no download attempted'
        return bool(tiktoken.get_encoding('o200k_base').encode('preflight')), str(cache)
    check('o200k cache', tokenizer)
    roots = dict(physical=args.physical_root, data=args.data_dir, vendor=args.vendor_dir, evidence=args.evidence_root)
    try: rows += hashes(json.loads(Path(args.hash_manifest).read_bytes()), roots)
    except Exception as exc: rows.append(('hash manifest', False, str(exc)))
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    def version():
        runner = CodexRunner(args.codex_binary, workdir=Path.cwd(), env_allowlist=['PATH','HOME'], stderr_path=out.with_suffix('.stderr.log'))
        runner.env['PYTHONPATH'] = os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p)
        actual = runner.version(args.codex_version)
        return True, actual+'; authentication NOT tested (--version only)'
    check('Codex pin', version)
    report = dict(passed=all(row[1] for row in rows), checks=[dict(name=n, passed=p, detail=d) for n,p,d in rows],
                  authentication='not tested; user-owned login must already work')
    out.write_text(json.dumps(report, sort_keys=True, separators=(',',':'))+'\n')
    for name, passed, detail in rows: print(('PASS' if passed else 'FAIL')+' | '+name+' | '+detail)
    return 0 if report['passed'] else 1

if __name__ == '__main__': raise SystemExit(main())
