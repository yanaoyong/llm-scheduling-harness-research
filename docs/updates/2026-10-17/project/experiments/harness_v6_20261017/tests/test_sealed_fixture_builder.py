"""Synthetic archive checks: public refs are lookup IDs, never content hashes."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import zlib
import pytest

spec = importlib.util.spec_from_file_location('sealed_builder', Path(__file__).resolve().parents[1]/'scripts/build_sealed_fixture.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_builder_rejects_data_overlap_before_writing(tmp_path):
    data = tmp_path/'data'; data.mkdir()
    public = tmp_path/'public.json'; public.write_text(json.dumps({'data_dir': str(data)}))
    with pytest.raises(ValueError, match='overlap'):
        module.build(tmp_path/'evidence', public, data/'generated', work_root=tmp_path)
    assert list(data.iterdir()) == []


def test_builder_preserves_existing_failed_run(tmp_path):
    public = tmp_path/'public.json'; public.write_text(json.dumps({'data_dir': str(tmp_path/'data')}))
    output = tmp_path/'sealed'; output.mkdir()
    evidence = output/'contexts.sqlite'; evidence.write_bytes(b'previous failed run')
    with pytest.raises(FileExistsError):
        module.build(tmp_path/'evidence', public, output, work_root=tmp_path)
    assert evidence.read_bytes() == b'previous failed run'


def test_public_archive_hashes_and_export_order(tmp_path):
    source = tmp_path/'G0';source.mkdir();(source/'objects').mkdir();(source/'exports').mkdir()
    conn=sqlite3.connect(':memory:')
    conn.executescript('CREATE TABLE records(namespace TEXT,key TEXT,ref TEXT); CREATE TABLE physical(seq INTEGER,object_ref TEXT);')
    conn.execute("INSERT INTO records VALUES ('contexts','context:old','historical')")
    conn.execute("INSERT INTO physical VALUES (0,'old-event')")
    (source/'events.sqlite3.public.sql').write_text('\n'.join(conn.iterdump()))
    raw=zlib.compress(b'{"public":"redacted"}')
    (source/'objects/historical.z.public.json.z').write_bytes(raw)
    (source/'exports/trace.jsonl').write_text('{"seq":0,"kind":"initial","time":0}\n')
    scratch=tmp_path/'scratch';scratch.mkdir();provenance={}
    archive=module.Archive(source,scratch,provenance)
    assert archive.records('contexts')==[{'public':'redacted'}]
    assert archive.trace()==[{'seq':0,'kind':'initial','time':0}]
    import hashlib
    assert provenance[str(source/'objects/historical.z.public.json.z')]['public_sha256']==hashlib.sha256(raw).hexdigest()
    assert archive.obj('historical')=={'public':'redacted'}
    (source/'exports/trace.jsonl').write_text('{"seq":1}\n')
    import pytest
    with pytest.raises(AssertionError):archive.trace()
    archive.db.close()
