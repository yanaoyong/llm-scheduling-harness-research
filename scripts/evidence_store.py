#!/usr/bin/env python3
"""SHA-256 archive of the public sanitized derivative. Requires Python 3 and zstd.

pack reads the local source map; verify and restore need only the archive.
No original experiment code is imported or executed.
"""
import argparse
import collections
import hashlib
import io
import json
import os
import posixpath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

BASE = Path(__file__).resolve().parent
METADATA = ['inventory.jsonl', 'excluded.jsonl', 'selection.json', 'critical_coverage.json', 'runtime_sidecar_coverage.json', 'transformations.jsonl', 'sqlite_exports.json', 'privacy_review.json', 'sqlite_verification.json', 'utf16_input_review.json', 'README.md', 'evidence_store.py']

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

def zstd():
    executable = shutil.which('zstd')
    if not executable:
        raise RuntimeError('Install the zstd command-line tool and add it to PATH')
    return executable

def safe_path(name):
    p = PurePosixPath(name)
    if p.is_absolute() or not p.parts or '..' in p.parts or str(p) != name:
        raise ValueError('Unsafe or noncanonical archive path: ' + name)
    return p

def inventories(raw):
    rows = [json.loads(line) for line in raw.decode().splitlines() if line]
    names = set()
    objects = collections.defaultdict(list)
    for row in rows:
        p = safe_path(row['path'])
        if p.parts[0] not in ('project', 'archive') or row['path'] in names:
            raise ValueError('Duplicate or unrecognized namespace')
        names.add(row['path'])
        if row['type'] == 'file':
            if not re.fullmatch('[0-9a-f]{64}', row['object']) or row['object'] != row['sha256']:
                raise ValueError('Invalid object hash')
            objects[row['object']].append(row)
        elif row['type'] not in ('directory', 'symlink'):
            raise ValueError('Invalid inventory type')
    for group in objects.values():
        if len({r['size'] for r in group}) != 1:
            raise ValueError('Object size conflict')
    # An inventory may not use an ordinary file or symlink as a parent.
    nondirs = {r['path'] for r in rows if r['type'] != 'directory'}
    for row in rows:
        if any(str(parent) in nondirs for parent in PurePosixPath(row['path']).parents):
            raise ValueError('Non-directory parent in inventory')
    return rows, objects

class CheckedReader:
    def __init__(self, stream):
        self.stream = stream
        self.hash = hashlib.sha256()
        self.bytes = 0

    def read(self, size=-1):
        data = self.stream.read(size)
        self.hash.update(data)
        self.bytes += len(data)
        return data

def pack(args):
    archive = Path(args.archive)
    partial = archive.with_name(archive.name + '.partial')
    if archive.exists() or partial.exists():
        raise ValueError('Refusing to overwrite a package or partial build')
    inv, objects = inventories((BASE / 'inventory.jsonl').read_bytes())
    sources = {r['path']: r for r in map(json.loads, (BASE / 'sources.local.jsonl').read_text().splitlines())}
    written, checked, bytes_in, last = set(), 0, 0, time.monotonic()
    started = time.monotonic()
    with partial.open('xb') as output, (BASE / 'compression.log').open('w') as log:
        proc = subprocess.Popen([zstd(), '-q', '-T2', '-8', '--long=27', '-c'], stdin=subprocess.PIPE, stdout=output, stderr=log)
        try:
            with tarfile.open(fileobj=proc.stdin, mode='w|', format=tarfile.PAX_FORMAT) as tar:
                for name in METADATA:
                    raw = (BASE / name).read_bytes()
                    info = tarfile.TarInfo('metadata/' + name)
                    info.size, info.mode, info.mtime = len(raw), 0o644, 0
                    tar.addfile(info, io.BytesIO(raw))
                for row in inv:
                    if row['type'] != 'file':
                        continue
                    source = Path(sources[row['path']]['source'])
                    info = source.lstat()
                    if not stat.S_ISREG(info.st_mode) or info.st_size != row['size']:
                        raise ValueError('Source type/size changed: ' + row['path'])
                    with source.open('rb') as stream:
                        reader = CheckedReader(stream)
                        if row['object'] not in written:
                            member = tarfile.TarInfo('objects/' + row['object'])
                            member.size, member.mode, member.mtime = row['size'], 0o444, 0
                            tar.addfile(member, reader)
                            written.add(row['object'])
                            bytes_in += row['size']
                        else:
                            while reader.read(4 * 1024 * 1024):
                                pass
                    if reader.bytes != row['size'] or reader.hash.hexdigest() != row['sha256']:
                        raise ValueError('Source changed from frozen manifest: ' + row['path'])
                    after = source.lstat()
                    if (info.st_ino, info.st_size, info.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                        raise ValueError('Source changed while reading: ' + row['path'])
                    checked += 1
                    if time.monotonic() - last >= 20:
                        print(json.dumps({'stage': 'pack', 'files_checked': checked, 'unique_objects': len(written), 'unique_bytes': bytes_in, 'compressed_bytes_so_far': partial.stat().st_size}), flush=True)
                        last = time.monotonic()
            proc.stdin.close()
            if proc.wait() != 0:
                raise RuntimeError('zstd compression failed; see compression.log')
        except BaseException:
            proc.kill()
            proc.wait()
            raise
    assert set(objects) == written
    partial.rename(archive)
    result = {'status': 'passed', 'stage': 'pack', 'created_at': datetime.now(timezone.utc).isoformat(), 'archive': archive.name, 'archive_sha256': digest(archive), 'compressed_bytes': archive.stat().st_size, 'selected_files_checked_against_frozen_hashes': checked, 'unique_objects': len(written), 'unique_content_bytes': bytes_in, 'elapsed_seconds': time.monotonic() - started}
    save(BASE / 'build_result.json', result)
    print(json.dumps(result), flush=True)

def unpack(archive, dest=None):
    if dest is not None:
        if dest.exists():
            raise ValueError('Restore destination must not exist')
        dest.mkdir(parents=True)
    metadata, seen = {}, set()
    rows = objects = None
    count, byte_count, last = 0, 0, time.monotonic()
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen([zstd(), '-q', '-d', '-c', str(archive)], stdout=subprocess.PIPE, stderr=err)
        try:
            with tarfile.open(fileobj=proc.stdout, mode='r|') as tar:
                for member in tar:
                    safe_path(member.name)
                    if not member.isfile():
                        raise ValueError('Only regular members are allowed in the object package')
                    if member.name.startswith('metadata/'):
                        name = member.name[len('metadata/'):]
                        if name not in METADATA or name in metadata or member.size > 128 * 1024 * 1024 or seen:
                            raise ValueError('Unexpected/duplicate/late metadata')
                        raw = tar.extractfile(member).read()
                        metadata[name] = raw
                        if name == 'inventory.jsonl':
                            rows, objects = inventories(raw)
                        continue
                    if rows is None or set(metadata) != set(METADATA):
                        raise ValueError('Missing metadata before objects')
                    if not re.fullmatch('objects/[0-9a-f]{64}', member.name):
                        raise ValueError('Unexpected object member')
                    key = member.name[8:]
                    if key not in objects or key in seen or member.size != objects[key][0]['size']:
                        raise ValueError('Unexpected, duplicate or incorrectly sized object')
                    group = objects[key]
                    target = dest / group[0]['path'] if dest is not None else None
                    if target is not None:
                        target.parent.mkdir(parents=True, exist_ok=True)
                    output = target.open('xb') if target is not None else None
                    h = hashlib.sha256()
                    n = 0
                    try:
                        with tar.extractfile(member) as stream:
                            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                                h.update(chunk)
                                n += len(chunk)
                                if output is not None:
                                    output.write(chunk)
                    finally:
                        if output is not None:
                            output.close()
                    if n != member.size or h.hexdigest() != key:
                        raise ValueError('Object integrity mismatch: ' + key)
                    if target is not None:
                        # Independent restored files prevent cross-path mutations.
                        for row in group[1:]:
                            copy = dest / row['path']
                            copy.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(target, copy)
                        for row in group:
                            path = dest / row['path']
                            path.chmod(stat.S_IMODE(row['mode']))
                            os.utime(path, ns=(row['mtime_ns'], row['mtime_ns']))
                    seen.add(key)
                    count += 1
                    byte_count += n
                    if time.monotonic() - last >= 20:
                        print(json.dumps({'stage': 'restore' if dest else 'verify', 'objects_verified': count, 'unique_bytes': byte_count}), flush=True)
                        last = time.monotonic()
            # Consume through zstd's end-of-frame checksum before accepting.
            if proc.stdout.read().strip(b'\0'):
                raise ValueError('Unexpected trailing uncompressed data')
            if proc.wait() != 0:
                raise ValueError('zstd checksum/decompression failure')
        except BaseException:
            proc.kill()
            proc.wait()
            raise
    if objects is None or seen != set(objects) or set(metadata) != set(METADATA):
        raise ValueError('Incomplete package')
    deferred = []
    if dest is not None:
        for row in rows:
            if row['type'] == 'directory':
                (dest / row['path']).mkdir(parents=True, exist_ok=True)
        for row in rows:
            if row['type'] != 'symlink':
                continue
            target_name = row.get('portable_target_path')
            if target_name is None:
                deferred.append(row)
                continue
            safe_path(target_name)
            link = dest / row['path']
            target = dest / target_name
            if not target.exists():
                raise ValueError('Missing restored symlink target: ' + target_name)
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(os.path.relpath(target, link.parent))
        # Apply restrictive directory modes only after writing every descendant.
        for row in sorted((r for r in rows if r['type'] == 'directory'), key=lambda r: len(PurePosixPath(r['path']).parts), reverse=True):
            directory = dest / row['path']
            directory.chmod(stat.S_IMODE(row['mode']))
            os.utime(directory, ns=(row['mtime_ns'], row['mtime_ns']))
        meta = dest / '_lean_store'
        meta.mkdir()
        for name, raw in metadata.items():
            (meta / name).write_bytes(raw)
        save(meta / 'deferred_external_symlinks.json', deferred)
    return rows, {'objects_verified': count, 'unique_content_bytes': byte_count, 'inventory_files': sum(r['type'] == 'file' for r in rows), 'deferred_external_symlinks': len(deferred)}

def check_tree(rows, dest):
    files, size, links, directories, last = 0, 0, 0, 0, time.monotonic()
    for row in rows:
        p = dest / row['path']
        if row['type'] == 'file':
            if not p.is_file() or p.is_symlink() or p.stat().st_size != row['size'] or digest(p) != row['sha256']:
                raise ValueError('Restored file differs: ' + row['path'])
            if stat.S_IMODE(p.stat().st_mode) != stat.S_IMODE(row['mode']):
                raise ValueError('Restored permissions differ: ' + row['path'])
            if p.stat().st_mtime_ns != row['mtime_ns']:
                raise ValueError('Restored file timestamp differs: ' + row['path'])
            files += 1
            size += row['size']
        elif row['type'] == 'directory':
            if not p.is_dir() or p.is_symlink() or stat.S_IMODE(p.stat().st_mode) != stat.S_IMODE(row['mode']):
                raise ValueError('Restored directory missing or permissions differ: ' + row['path'])
            if p.stat().st_mtime_ns != row['mtime_ns']:
                raise ValueError('Restored directory timestamp differs: ' + row['path'])
            directories += 1
        elif row['type'] == 'symlink' and row.get('portable_target_path') is not None:
            if not p.is_symlink() or p.resolve() != (dest / row['portable_target_path']).resolve():
                raise ValueError('Restored symlink mismatch')
            links += 1
        if time.monotonic() - last >= 20:
            print(json.dumps({'stage': 'rehash-restored-tree', 'files_verified': files, 'bytes': size}), flush=True)
            last = time.monotonic()
    return {'restored_files_rehashed': files, 'restored_bytes_rehashed': size, 'portable_symlinks_verified': links, 'directory_modes_and_mtimes_verified': directories}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command', choices=('pack', 'verify', 'restore', 'restore-check'))
    ap.add_argument('--archive', default=str(BASE / 'public-evidence.cas.tar.zst'))
    ap.add_argument('--dest')
    ap.add_argument('--report')
    ap.add_argument('--expected-sha256', help='Independent expected package hash; defaults to adjacent build_result.json when present')
    args = ap.parse_args()
    if args.command == 'pack':
        return pack(args)
    archive = Path(args.archive).resolve()
    started = time.monotonic()
    result = {'stage': args.command, 'checked_at': datetime.now(timezone.utc).isoformat(), 'archive_sha256': digest(archive)}
    expected = args.expected_sha256
    build_record = archive.parent / 'build_result.json'
    if expected is None and build_record.exists():
        record = json.loads(build_record.read_text())
        if record.get('archive') == archive.name:
            expected = record['archive_sha256']
    if expected is not None and expected != result['archive_sha256']:
        raise ValueError('Package differs from independent expected SHA-256')
    result['independent_package_hash_checked'] = expected is not None
    if args.command == 'restore-check':
        # The only deleted files are those created in this unique temporary dir.
        with tempfile.TemporaryDirectory(prefix='lean-evidence-restore-') as tmp:
            dest = Path(tmp) / 'restored'
            rows, checks = unpack(archive, dest)
            result.update(checks)
            result.update(check_tree(rows, dest))
        result['temporary_restoration_removed'] = True
    else:
        if args.command == 'restore' and not args.dest:
            raise ValueError('--dest is required for restore')
        dest = Path(args.dest).resolve() if args.command == 'restore' else None
        rows, checks = unpack(archive, dest)
        result.update(checks)
        if dest is not None:
            result.update(check_tree(rows, dest))
            result['destination'] = str(dest)
    result.update(status='passed', elapsed_seconds=time.monotonic() - started)
    if args.report:
        save(args.report, result)
    print(json.dumps(result), flush=True)

if __name__ == '__main__':
    main()
