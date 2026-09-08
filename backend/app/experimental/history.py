"""Bounded local MVP history and checksum backups, not M3 durable authority."""
import sqlite3
from pathlib import Path
from uuid import UUID

from .contract import MODEL, canonical, digest, strict_json, validate_job_input
from .mos_contract import MODEL as MOS_MODEL

MAX_RECORDS = 32
MAX_RECORD_BYTES = 1_048_576
MAX_BACKUP_BYTES = 34_000_000


def validate_record(record):
    if not isinstance(record, dict):
        raise ValueError("history-record")
    required = {"requestId", "inputSha256", "state"}
    if not required <= set(record) or set(record) - required - {"result", "error"}:
        raise ValueError("history-shape")
    if str(UUID(record["requestId"])) != record["requestId"]:
        raise ValueError("history-id")
    fingerprint = record["inputSha256"]
    if not isinstance(fingerprint, str) or len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint):
        raise ValueError("history-input-hash")
    if record["state"] not in {"running", "complete", "failed", "cancelled"}:
        raise ValueError("history-state")
    if "error" in record and (record["state"] != "failed" or record["error"] not in {"solver-failed", "interrupted", "history-write-failed"}):
        raise ValueError("history-error")
    if record["state"] == "complete":
        result = record.get("result")
        if not isinstance(result, dict) or result.get("productApproved") is not False:
            raise ValueError("history-result")
        if (result.get("model"), result.get("format")) not in {(MODEL, "opentcad-solver-result"), (MOS_MODEL, "opentcad-mos-result")} or type(result.get("schemaVersion")) is not int or result["schemaVersion"] != 1:
            raise ValueError("history-result-format")
        payload = {k: v for k, v in result.items() if k != "resultSha256"}
        inputs = validate_job_input(result["input"])
        if digest(payload) != result.get("resultSha256") or digest(inputs) != fingerprint or result.get("inputSha256") != fingerprint:
            raise ValueError("history-result-integrity")
    elif "result" in record:
        raise ValueError("history-unfinished-result")
    if len(canonical(record)) > MAX_RECORD_BYTES:
        raise ValueError("history-size")
    return record


def read_backup(path):
    with Path(path).open("rb") as stream:
        value = strict_json(stream.read(MAX_BACKUP_BYTES + 1), MAX_BACKUP_BYTES)
    if not isinstance(value, dict) or set(value) != {"format", "schemaVersion", "records", "sha256"}:
        raise ValueError("backup-shape")
    if value["format"] != "opentcad-windows-mvp-backup" or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise ValueError("backup-format")
    if digest({k: v for k, v in value.items() if k != "sha256"}) != value["sha256"]:
        raise ValueError("backup-integrity")
    records = value["records"]
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise ValueError("backup-count")
    for record in records:
        validate_record(record)
    if len({r["requestId"] for r in records}) != len(records):
        raise ValueError("backup-duplicate-id")
    return records


class History:
    """Caller holds the local single-instance lock for this entire lifetime."""

    def __init__(self, path):
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValueError("history-symlink")
        self.db = sqlite3.connect(self.path)
        try:
            self.db.execute("PRAGMA trusted_schema=OFF")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA journal_mode=DELETE")
            if self.db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise ValueError("history-integrity")
            self.db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload BLOB NOT NULL, sha256 TEXT NOT NULL)")
            self.db.commit()
            self.load()
        except BaseException:
            self.db.close()
            raise

    def load(self, recover=False):
        rows = self.db.execute("SELECT id, payload, sha256 FROM jobs ORDER BY rowid LIMIT ?", (MAX_RECORDS + 1,)).fetchall()
        if len(rows) > MAX_RECORDS:
            raise ValueError("history-count")
        records = {}
        for identifier, source, fingerprint in rows:
            record = validate_record(strict_json(source, MAX_RECORD_BYTES))
            if record["requestId"] != identifier or digest(record) != fingerprint:
                raise ValueError("history-record-integrity")
            records[identifier] = record
        if recover:
            with self.db:
                for record in records.values():
                    if record["state"] == "running":
                        record.update(state="failed", error="interrupted")
                        self._save(record)
        return records

    def _save(self, record):
        validate_record(record)
        self.db.execute("INSERT INTO jobs VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, sha256=excluded.sha256",
                        (record["requestId"], canonical(record), digest(record)))

    def save(self, record):
        with self.db:
            count = self.db.execute("SELECT count(*) FROM jobs").fetchone()[0]
            exists = self.db.execute("SELECT 1 FROM jobs WHERE id=?", (record["requestId"],)).fetchone()
            if not exists and count >= MAX_RECORDS:
                raise ValueError("history-full")
            self._save(record)

    def backup(self, output):
        value = {"format": "opentcad-windows-mvp-backup", "schemaVersion": 1, "records": list(self.load().values())}
        value["sha256"] = digest(value)
        with Path(output).open("xb") as stream:
            import os
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        return value["sha256"]

    def restore(self, records):
        if self.load():
            raise ValueError("restore-requires-empty-history")
        if not isinstance(records, list) or len(records) > MAX_RECORDS:
            raise ValueError("restore-count")
        for record in records:
            validate_record(record)
        if len({r["requestId"] for r in records}) != len(records):
            raise ValueError("restore-duplicate-id")
        with self.db:
            for record in records:
                self._save(record)

    def close(self):
        self.db.close()
