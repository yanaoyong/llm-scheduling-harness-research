"""Shared persistence and provenance; never silently replace run evidence."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def object_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                      separators=(',', ':')).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value, *, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive and path.exists():
        raise FileExistsError(path)
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if exclusive:
        with path.open('x') as f:
            f.write(data)
    else:
        tmp = path.with_name(path.name + '.tmp')
        tmp.write_text(data)
        tmp.replace(path)


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def code_files(domain=None):
    # Directly hashed source snapshot records uncommitted development changes too.
    paths=sorted(p for folder in ('src', 'prompts', 'configs', 'tests')
                  for p in (ROOT / folder).rglob('*')
                  if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.lock'
                  and 'freezes' not in p.parts)
    if domain=='fjsp':
        paths=[p for p in paths if '/smt/' not in str(p.relative_to(ROOT))
               and not p.name.startswith(('smt','test_smt'))]
    return paths


def provenance(problem, config, protocol, domain=None):
    return {'code_commit': git('rev-parse', 'HEAD'),
            'working_tree_dirty': bool(git('status', '--porcelain')),
            'source_sha256': {str(p.relative_to(ROOT)): digest(p) for p in code_files(domain)},
            'config_sha256': object_digest(config), 'data_sha256': object_digest(problem),
            'protocol_version': protocol}


def verify_freeze(name):
    frozen = read_json(ROOT / 'configs' / 'freezes' / f'{name}.json')
    errors = []
    for rel, expected in frozen['files'].items():
        p = ROOT / rel
        if not p.is_file() or digest(p) != expected:
            errors.append(rel)
    if git('rev-parse', frozen['tag'] + '^{commit}') != frozen['code_commit']:
        errors.append('tag commit mismatch')
    if errors:
        raise ValueError('Frozen files changed: ' + ', '.join(errors))
    return frozen
