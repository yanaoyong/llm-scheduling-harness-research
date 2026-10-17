"""Single-writer transactional authority; exports are disposable projections.

Objects are durable before their references enter SQLite. Unreferenced objects
after a failed transaction are retained for diagnosis. No overwrite or GC of
original evidence is performed here.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
import zlib

from .contracts import HarnessError, digest, encode, require, sha_bytes, strict_json


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class InjectedCrash(BaseException):
    """Deliberate process-like interruption, never a business rejection."""


class Store:
    def __init__(self, directory, *, create=False, fault=None):
        self.path = Path(directory).resolve()
        self.fault = fault or (lambda point: None)
        if create:
            self.path.mkdir(parents=True, exist_ok=False)
            (self.path / "objects").mkdir()
            (self.path / "exports").mkdir()
        require((self.path / "objects").is_dir(), "missing_run", str(self.path))
        self.lock = (self.path / "writer.lock").open("a+b")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise HarnessError("writer_busy", "Another process owns this run") from None
        try:
            self.db = sqlite3.connect(self.path / "events.sqlite3", isolation_level=None)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA journal_mode=WAL")
            if create:
                self.db.executescript("""
                    CREATE TABLE metadata(key TEXT PRIMARY KEY, value BLOB NOT NULL);
                    CREATE TABLE records(namespace TEXT, key TEXT, ref TEXT NOT NULL,
                                         PRIMARY KEY(namespace,key));
                    CREATE TABLE events(seq INTEGER PRIMARY KEY, kind TEXT NOT NULL,
                                        payload_ref TEXT NOT NULL, previous TEXT, sha256 TEXT UNIQUE NOT NULL);
                    CREATE TABLE physical(seq INTEGER PRIMARY KEY, object_ref TEXT NOT NULL);
                """)
                self.db.execute("INSERT INTO metadata VALUES('fence', ?)", (encode(0),))
            require(self.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "corrupt_db", "SQLite integrity failure")
            self.token = self.meta("fence") + 1
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute("UPDATE metadata SET value=? WHERE key='fence'", (encode(self.token),))
            self.db.execute("COMMIT")
            self.closed = False
        except BaseException:
            self.lock.close()
            raise

    def meta(self, key, default=None):
        row = self.db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return strict_json(row[0]) if row else default

    def set_meta(self, key, value):
        require(self.db.in_transaction, "transaction_required", key)
        self.db.execute("INSERT INTO metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, encode(value)))

    @contextmanager
    def transaction(self, *, revision=None):
        require(not self.closed, "writer_closed", "Writer is closed")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            require(self.meta("fence") == self.token, "fenced_writer", "Stale writer token")
            if revision is not None:
                require(self.meta("head")["revision"] == revision, "stale_revision", "Physical head changed")
            yield self
            self.fault("before_sql_commit")
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def put_bytes(self, raw):
        require(type(raw) is bytes, "object_type", "Object must be exact bytes")
        sha = sha_bytes(raw)
        path = self.path / "objects" / (sha + ".z")
        if path.exists():
            require(self.bytes(sha) == raw, "object_corrupt", sha)
            return sha
        self.fault("before_object_write")
        temporary = path.with_name(".pending-" + uuid.uuid4().hex)
        with temporary.open("xb") as stream:
            compressed = zlib.compress(raw, level=6)
            written = stream.write(compressed)
            require(written == len(compressed), "short_write", str(temporary))
            stream.flush()
            os.fsync(stream.fileno())
        self.fault("after_object_fsync")
        os.link(temporary, path)
        temporary.unlink()
        fsync_dir(path.parent)
        return sha

    def put(self, value):
        return self.put_bytes(encode(value))

    def bytes(self, ref):
        require(type(ref) is str and len(ref) == 64 and set(ref) <= set("0123456789abcdef"), "object_ref", "Invalid object identity")
        try:
            raw = zlib.decompress((self.path / "objects" / (ref + ".z")).read_bytes())
        except (OSError, zlib.error) as exc:
            raise HarnessError("object_corrupt", ref) from exc
        require(sha_bytes(raw) == ref, "object_corrupt", ref)
        return raw

    def get(self, ref):
        return strict_json(self.bytes(ref))

    def record(self, namespace, key, value, *, replace=False):
        require(self.db.in_transaction, "transaction_required", namespace)
        ref = self.put(value)
        old = self.ref(namespace, key)
        require(old is None or replace or old == ref, "immutable_conflict", namespace + ":" + key)
        self.db.execute("INSERT INTO records VALUES(?,?,?) ON CONFLICT(namespace,key) DO UPDATE SET ref=excluded.ref", (namespace, key, ref))
        return ref

    def ref(self, namespace, key):
        row = self.db.execute("SELECT ref FROM records WHERE namespace=? AND key=?", (namespace, key)).fetchone()
        return row[0] if row else None

    def read(self, namespace, key, default=None):
        ref = self.ref(namespace, key)
        return self.get(ref) if ref else default

    def rows(self, namespace):
        return [(row[0], self.get(row[1])) for row in self.db.execute("SELECT key,ref FROM records WHERE namespace=? ORDER BY rowid", (namespace,))]

    def event(self, kind, payload):
        require(self.db.in_transaction, "transaction_required", kind)
        last = self.db.execute("SELECT seq,sha256 FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        seq, previous = (last[0] + 1, last[1]) if last else (1, None)
        ref = self.put(payload)
        value = {"seq": seq, "kind": kind, "payload_ref": ref, "previous": previous}
        sha = digest(value)
        self.db.execute("INSERT INTO events VALUES(?,?,?,?,?)", (seq, kind, ref, previous, sha))
        return {**value, "sha256": sha}

    def physical(self, events):
        require(self.db.in_transaction, "transaction_required", "physical events")
        n = self.db.execute("SELECT COUNT(*) FROM physical").fetchone()[0]
        for event in events:
            require(event["seq"] == n, "physical_discontinuity", "Event sequence must be continuous")
            self.db.execute("INSERT INTO physical VALUES(?,?)", (n, self.put(event)))
            n += 1

    def trace(self):
        return [self.get(row[0]) for row in self.db.execute("SELECT object_ref FROM physical ORDER BY seq")]

    def export_trace(self):
        path = self.path / "exports/trace.jsonl"
        temporary = path.with_suffix(".tmp")
        with temporary.open("wb") as stream:
            for row in self.db.execute("SELECT object_ref FROM physical ORDER BY seq"):
                self.fault("during_trace_export")
                stream.write(self.bytes(row[0]) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        fsync_dir(path.parent)
        return path

    def verify(self):
        require(self.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "corrupt_db", "SQLite integrity failure")
        previous = None
        n = 0
        for row in self.db.execute("SELECT * FROM events ORDER BY seq"):
            n += 1
            event = dict(row)
            sha = event.pop("sha256")
            require(event["seq"] == n and event["previous"] == previous and digest(event) == sha,
                    "event_corrupt", "Broken workflow event chain")
            self.bytes(event["payload_ref"])
            previous = sha
        for row in self.db.execute("SELECT ref FROM records UNION SELECT object_ref FROM physical"):
            self.bytes(row[0])
        for i, event in enumerate(self.trace()):
            require(event["seq"] == i, "physical_discontinuity", "Broken physical sequence")
        return {"events": n, "event_head": previous, "fence": self.token}

    def close(self):
        if not self.closed:
            self.db.close()
            self.lock.close()
            self.closed = True
