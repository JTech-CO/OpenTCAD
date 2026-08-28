"""Offline snapshot and fresh-target restore contract for the two SQLite stores."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
from os import PathLike, fspath
import os
from pathlib import Path
import shutil
import sqlite3
import threading
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from backend.app.runtime.errors import RuntimeBackendError
from backend.app.runtime.fencing import RuntimeFencingContext
from backend.app.runtime.models import JobIdentity
from backend.app.runtime.sqlite_fence_authority import (
    SQLITE_RUNTIME_FENCE_SCHEMA_VERSION,
    SQLiteRuntimeFenceAuthority,
)

from .durability import DurablePublicationError, publish_directory, sync_file
from .sqlite_state import SQLITE_STATE_SCHEMA_VERSION, SQLiteJobStateStore
from .state import JobStateSnapshot, StateStoreError, validate_state_transition


SQLITE_OFFLINE_SNAPSHOT_PRODUCT_ENABLED = False
SQLITE_OFFLINE_SNAPSHOT_LIVE_WRITES_SUPPORTED = False
SQLITE_OFFLINE_SNAPSHOT_SCHEMA_VERSION = 1
SQLITE_OFFLINE_SNAPSHOT_FORMAT = "opentcad-sqlite-offline-snapshot"
SQLITE_OFFLINE_RESTORE_FORMAT = "opentcad-sqlite-offline-restore"
SQLITE_OFFLINE_SNAPSHOT_MAX_DATABASE_BYTES = 1 << 30

SQLITE_SNAPSHOT_MANIFEST_NAME = "snapshot.json"
SQLITE_SNAPSHOT_STATE_NAME = "broker-state.sqlite3"
SQLITE_SNAPSHOT_AUTHORITY_NAME = "runtime-fence.sqlite3"
SQLITE_RESTORE_RECORD_NAME = "restore.json"

_MANIFEST_MAX_BYTES = 64 * 1024
_HASH_CHUNK_BYTES = 1024 * 1024
_MAX_SEQUENCE = (1 << 63) - 1
_EXPECTED_BUNDLE_NAMES = frozenset(
    {
        SQLITE_SNAPSHOT_MANIFEST_NAME,
        SQLITE_SNAPSHOT_STATE_NAME,
        SQLITE_SNAPSHOT_AUTHORITY_NAME,
    },
)


class SQLiteSnapshotErrorCode(StrEnum):
    INVALID_REQUEST = "invalid-request"
    OFFLINE_REQUIRED = "offline-required"
    SOURCE_UNAVAILABLE = "source-unavailable"
    SOURCE_SCHEMA_MISMATCH = "source-schema-mismatch"
    DESTINATION_EXISTS = "destination-exists"
    BUNDLE_INCOMPLETE = "bundle-incomplete"
    BUNDLE_INTEGRITY_FAILED = "bundle-integrity-failed"
    BUNDLE_SCHEMA_MISMATCH = "bundle-schema-mismatch"
    STATE_AUTHORITY_CONFLICT = "state-authority-conflict"
    SNAPSHOT_IDENTITY_MISMATCH = "snapshot-identity-mismatch"
    SNAPSHOT_ROLLBACK_REJECTED = "snapshot-rollback-rejected"
    RESTORE_TARGET_EXISTS = "restore-target-exists"
    RESTORE_FAILED = "restore-failed"


class SQLiteSnapshotError(Exception):
    """Stable snapshot failure that does not expose a local path or SQLite detail."""

    def __init__(self, code: SQLiteSnapshotErrorCode) -> None:
        if not isinstance(code, SQLiteSnapshotErrorCode):
            raise TypeError("SQLiteSnapshotError requires SQLiteSnapshotErrorCode.")
        self.code = code
        super().__init__(code.value)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code.value}


class SQLiteSnapshotCheckpoint(StrEnum):
    AFTER_STATE_BACKUP = "after-state-backup"
    AFTER_AUTHORITY_BACKUP = "after-authority-backup"
    AFTER_MANIFEST_WRITE = "after-manifest-write"
    AFTER_BUNDLE_PUBLISH = "after-bundle-publish"
    AFTER_STATE_RESTORE = "after-state-restore"
    AFTER_AUTHORITY_RESTORE = "after-authority-restore"
    AFTER_RESTORE_RECORD_WRITE = "after-restore-record-write"
    AFTER_RESTORE_PUBLISH = "after-restore-publish"


class SQLiteSnapshotInterrupted(Exception):
    """Deterministic process-crash surrogate used only by contract tests."""

    def __init__(self, checkpoint: SQLiteSnapshotCheckpoint) -> None:
        if not isinstance(checkpoint, SQLiteSnapshotCheckpoint):
            raise TypeError(
                "SQLiteSnapshotInterrupted requires SQLiteSnapshotCheckpoint.",
            )
        self.checkpoint = checkpoint
        super().__init__(checkpoint.value)


@runtime_checkable
class SQLiteSnapshotCrashSignal(Protocol):
    def requested(
        self,
        checkpoint: SQLiteSnapshotCheckpoint,
        snapshot_id: str,
    ) -> bool: ...


def _canonical_uuid(value: str, label: str) -> None:
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise TypeError(f"{label} must be a canonical UUID.") from error
    if str(parsed) != value:
        raise TypeError(f"{label} must be a canonical UUID.")


def _positive_sequence(value: int, label: str) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
        or value > _MAX_SEQUENCE
    ):
        raise TypeError(f"{label} must be a positive signed 64-bit integer.")


@dataclass(frozen=True, slots=True)
class SQLiteSnapshotQuiescence:
    """Caller assertion that broker, runtime, and database writers are stopped."""

    quiescence_id: str
    broker_stopped: bool
    runtime_operations_stopped: bool
    database_writers_stopped: bool

    def __post_init__(self) -> None:
        _canonical_uuid(self.quiescence_id, "Snapshot quiescence ID")
        for value in (
            self.broker_stopped,
            self.runtime_operations_stopped,
            self.database_writers_stopped,
        ):
            if not isinstance(value, bool):
                raise TypeError("Snapshot quiescence markers must be bool.")

    @property
    def asserted(self) -> bool:
        return (
            self.broker_stopped
            and self.runtime_operations_stopped
            and self.database_writers_stopped
        )


@dataclass(frozen=True, slots=True)
class SQLiteOfflineSnapshotRequest:
    snapshot_id: str
    source_instance_id: str
    snapshot_sequence: int
    quiescence: SQLiteSnapshotQuiescence

    def __post_init__(self) -> None:
        _canonical_uuid(self.snapshot_id, "Snapshot ID")
        _canonical_uuid(self.source_instance_id, "Snapshot source instance ID")
        _positive_sequence(self.snapshot_sequence, "Snapshot sequence")
        if not isinstance(self.quiescence, SQLiteSnapshotQuiescence):
            raise TypeError("Offline snapshot requires SQLiteSnapshotQuiescence.")


@dataclass(frozen=True, slots=True)
class SQLiteSnapshotRestorePolicy:
    expected_snapshot_id: str
    expected_source_instance_id: str
    minimum_snapshot_sequence: int

    def __post_init__(self) -> None:
        _canonical_uuid(self.expected_snapshot_id, "Expected snapshot ID")
        _canonical_uuid(
            self.expected_source_instance_id,
            "Expected snapshot source instance ID",
        )
        _positive_sequence(
            self.minimum_snapshot_sequence,
            "Minimum snapshot sequence",
        )


@dataclass(frozen=True, slots=True)
class SQLiteSnapshotFileRecord:
    role: str
    name: str
    schema_version: int
    bytes: int
    sha256: str

    def __post_init__(self) -> None:
        expected = {
            "broker-state": (
                SQLITE_SNAPSHOT_STATE_NAME,
                SQLITE_STATE_SCHEMA_VERSION,
            ),
            "runtime-fence-authority": (
                SQLITE_SNAPSHOT_AUTHORITY_NAME,
                SQLITE_RUNTIME_FENCE_SCHEMA_VERSION,
            ),
        }
        if self.role not in expected:
            raise TypeError("Snapshot file role is unsupported.")
        if (self.name, self.schema_version) != expected[self.role]:
            raise TypeError("Snapshot file identity is invalid.")
        if (
            not isinstance(self.bytes, int)
            or isinstance(self.bytes, bool)
            or self.bytes < 1
            or self.bytes > SQLITE_OFFLINE_SNAPSHOT_MAX_DATABASE_BYTES
        ):
            raise TypeError("Snapshot file byte length is invalid.")
        if (
            not isinstance(self.sha256, str)
            or len(self.sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.sha256)
        ):
            raise TypeError("Snapshot file SHA-256 is invalid.")

    def as_dict(self) -> dict[str, str | int]:
        return {
            "role": self.role,
            "name": self.name,
            "schema_version": self.schema_version,
            "bytes": self.bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class SQLiteSnapshotCoherence:
    state_jobs: int
    authority_jobs: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.state_jobs, int)
            or isinstance(self.state_jobs, bool)
            or self.state_jobs < 0
            or not isinstance(self.authority_jobs, int)
            or isinstance(self.authority_jobs, bool)
            or self.authority_jobs < 0
            or self.authority_jobs > self.state_jobs
        ):
            raise TypeError("Snapshot coherence counts are invalid.")

    def as_dict(self) -> dict[str, int]:
        return {
            "state_jobs": self.state_jobs,
            "authority_jobs": self.authority_jobs,
        }


@dataclass(frozen=True, slots=True)
class SQLiteSnapshotManifest:
    snapshot_id: str
    source_instance_id: str
    snapshot_sequence: int
    quiescence_id: str
    files: tuple[SQLiteSnapshotFileRecord, ...]
    coherence: SQLiteSnapshotCoherence

    def __post_init__(self) -> None:
        _canonical_uuid(self.snapshot_id, "Manifest snapshot ID")
        _canonical_uuid(self.source_instance_id, "Manifest source instance ID")
        _canonical_uuid(self.quiescence_id, "Manifest quiescence ID")
        _positive_sequence(self.snapshot_sequence, "Manifest snapshot sequence")
        files = tuple(self.files)
        if (
            len(files) != 2
            or any(not isinstance(item, SQLiteSnapshotFileRecord) for item in files)
            or tuple(item.role for item in files)
            != ("broker-state", "runtime-fence-authority")
        ):
            raise TypeError("Snapshot manifest requires the two ordered database files.")
        if not isinstance(self.coherence, SQLiteSnapshotCoherence):
            raise TypeError("Snapshot manifest requires coherence counts.")
        object.__setattr__(self, "files", files)

    def as_dict(self) -> dict[str, Any]:
        return {
            "format": SQLITE_OFFLINE_SNAPSHOT_FORMAT,
            "schema_version": SQLITE_OFFLINE_SNAPSHOT_SCHEMA_VERSION,
            "snapshot_id": self.snapshot_id,
            "source_instance_id": self.source_instance_id,
            "snapshot_sequence": self.snapshot_sequence,
            "quiescence_id": self.quiescence_id,
            "offline_asserted": True,
            "files": [item.as_dict() for item in self.files],
            "coherence": self.coherence.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class SQLiteSnapshotRestoreResult:
    snapshot_id: str
    source_instance_id: str
    snapshot_sequence: int
    state_database: Path
    authority_database: Path
    restore_record: Path


class _SchemaFailure(Exception):
    pass


class _IntegrityFailure(Exception):
    pass


class _CoherenceFailure(Exception):
    pass


def _local_file_path(value: str | PathLike[str], label: str) -> Path:
    if not isinstance(value, (str, PathLike)):
        raise TypeError(f"{label} must be path-like.")
    raw = fspath(value)
    if (
        not isinstance(raw, str)
        or not raw
        or raw == ":memory:"
        or raw.casefold().startswith("file:")
        or "\x00" in raw
    ):
        raise TypeError(f"{label} requires a local filesystem path.")
    return Path(raw)


def _same_path(first: Path, second: Path) -> bool:
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(
        os.path.abspath(second),
    )


def _canonical_json(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _hash_file(path: Path) -> tuple[int, str]:
    size = path.stat().st_size
    if size < 1 or size > SQLITE_OFFLINE_SNAPSHOT_MAX_DATABASE_BYTES:
        raise _IntegrityFailure()
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return size, digest.hexdigest()


def _fsync_file(path: Path) -> None:
    try:
        sync_file(path)
    except DurablePublicationError:
        raise OSError("durability barrier failed") from None


def _publish_directory(stage: Path, destination: Path) -> None:
    try:
        publish_directory(stage, destination)
    except DurablePublicationError:
        raise OSError("durable publication failed") from None


def _open_read_only(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA trusted_schema = OFF")
    connection.execute("PRAGMA query_only = ON")
    return connection


def _require_integrity(connection: sqlite3.Connection) -> None:
    rows = tuple(row[0] for row in connection.execute("PRAGMA integrity_check"))
    if rows != ("ok",):
        raise _IntegrityFailure()


def _require_state_schema(connection: sqlite3.Connection) -> None:
    try:
        version = connection.execute("PRAGMA user_version").fetchone()
        if version is None or version[0] != SQLITE_STATE_SCHEMA_VERSION:
            raise _SchemaFailure()
        SQLiteJobStateStore._validate_schema(connection)
    except _SchemaFailure:
        raise
    except (StateStoreError, sqlite3.Error, TypeError, ValueError):
        raise _SchemaFailure() from None


def _require_authority_schema(connection: sqlite3.Connection) -> None:
    try:
        version = connection.execute("PRAGMA user_version").fetchone()
        if (
            version is None
            or version[0] != SQLITE_RUNTIME_FENCE_SCHEMA_VERSION
        ):
            raise _SchemaFailure()
        SQLiteRuntimeFenceAuthority._validate_schema(connection)
    except _SchemaFailure:
        raise
    except (sqlite3.Error, TypeError, ValueError):
        raise _SchemaFailure() from None


def _state_generations(
    connection: sqlite3.Connection,
) -> tuple[
    dict[str, JobStateSnapshot],
    dict[str, dict[int, str]],
]:
    rows = tuple(
        connection.execute(
            "SELECT job_id, revision, event_id, operation_id, "
            "operation_sequence, owner_id, fencing_token, lease_duration_ms, "
            "lease_expires_at_ms, state, phase, code, retry, backend, "
            "classification, cleanup_complete "
            "FROM job_events ORDER BY job_id, revision",
        ),
    )
    latest: dict[str, JobStateSnapshot] = {}
    generations: dict[str, dict[int, str]] = {}
    try:
        for row in rows:
            snapshot = SQLiteJobStateStore._decode_snapshot(row)
            job_id = snapshot.identity.job_id
            previous = latest.get(job_id)
            if snapshot.revision != (1 if previous is None else previous.revision + 1):
                raise _IntegrityFailure()
            validate_state_transition(
                None if previous is None else previous.state,
                snapshot.state,
            )
            owners = generations.setdefault(job_id, {})
            observed_owner = owners.get(snapshot.ownership.fencing_token)
            if observed_owner is not None and observed_owner != snapshot.ownership.owner_id:
                raise _IntegrityFailure()
            owners[snapshot.ownership.fencing_token] = snapshot.ownership.owner_id
            if previous is None:
                if snapshot.ownership.fencing_token != 1:
                    raise _IntegrityFailure()
            elif snapshot.ownership.owner_id == previous.ownership.owner_id:
                if (
                    snapshot.ownership.operation_id
                    != previous.ownership.operation_id
                    or snapshot.ownership.fencing_token
                    != previous.ownership.fencing_token
                ):
                    raise _IntegrityFailure()
            elif (
                snapshot.ownership.fencing_token
                != previous.ownership.fencing_token + 1
                or snapshot.state.value not in {"cancelling", "cleaning"}
            ):
                raise _IntegrityFailure()
            latest[job_id] = snapshot

        leases = {
            row["job_id"]: row
            for row in connection.execute(
                "SELECT job_id, operation_id, owner_id, fencing_token, "
                "job_revision, lease_expires_at_ms FROM job_leases",
            )
        }
        if len(leases) != len(latest):
            raise _IntegrityFailure()
        for job_id, snapshot in latest.items():
            lease = leases.get(job_id)
            if lease is None:
                raise _IntegrityFailure()
            JobIdentity(lease["job_id"])
            if (
                lease["operation_id"] != snapshot.ownership.operation_id
                or lease["owner_id"] != snapshot.ownership.owner_id
                or lease["fencing_token"] != snapshot.ownership.fencing_token
                or lease["job_revision"] != snapshot.revision
                or not isinstance(lease["lease_expires_at_ms"], int)
                or lease["lease_expires_at_ms"] < 1
            ):
                raise _IntegrityFailure()
    except (_IntegrityFailure,):
        raise
    except (KeyError, RuntimeError, StateStoreError, TypeError, ValueError):
        raise _IntegrityFailure() from None
    return latest, generations


def _authority_generations(
    connection: sqlite3.Connection,
) -> dict[str, RuntimeFencingContext]:
    current: dict[str, RuntimeFencingContext] = {}
    try:
        for row in connection.execute(
            "SELECT job_id, owner_id, fencing_token "
            "FROM runtime_fences ORDER BY job_id",
        ):
            context = RuntimeFencingContext(
                JobIdentity(row["job_id"]),
                row["owner_id"],
                row["fencing_token"],
            )
            if context.identity.job_id in current:
                raise _IntegrityFailure()
            current[context.identity.job_id] = context
    except _IntegrityFailure:
        raise
    except (KeyError, RuntimeBackendError, TypeError, ValueError):
        raise _IntegrityFailure() from None
    return current


def _validate_pair_connections(
    state: sqlite3.Connection,
    authority: sqlite3.Connection,
) -> SQLiteSnapshotCoherence:
    _require_state_schema(state)
    _require_authority_schema(authority)
    _require_integrity(state)
    _require_integrity(authority)
    latest, generations = _state_generations(state)
    fences = _authority_generations(authority)
    for job_id, fence in fences.items():
        snapshot = latest.get(job_id)
        if snapshot is None or fence.fencing_token > snapshot.ownership.fencing_token:
            raise _CoherenceFailure()
        if generations[job_id].get(fence.fencing_token) != fence.owner_id:
            raise _CoherenceFailure()
    return SQLiteSnapshotCoherence(len(latest), len(fences))


def _validate_pair_paths(
    state_path: Path,
    authority_path: Path,
) -> SQLiteSnapshotCoherence:
    try:
        with closing(_open_read_only(state_path)) as state, closing(
            _open_read_only(authority_path),
        ) as authority:
            return _validate_pair_connections(state, authority)
    except (_SchemaFailure, _IntegrityFailure, _CoherenceFailure):
        raise
    except (OSError, sqlite3.Error, ValueError):
        raise _IntegrityFailure() from None


def _file_record(role: str, path: Path) -> SQLiteSnapshotFileRecord:
    size, digest = _hash_file(path)
    if role == "broker-state":
        return SQLiteSnapshotFileRecord(
            role,
            SQLITE_SNAPSHOT_STATE_NAME,
            SQLITE_STATE_SCHEMA_VERSION,
            size,
            digest,
        )
    return SQLiteSnapshotFileRecord(
        role,
        SQLITE_SNAPSHOT_AUTHORITY_NAME,
        SQLITE_RUNTIME_FENCE_SCHEMA_VERSION,
        size,
        digest,
    )


def _backup_database(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise SQLiteSnapshotError(SQLiteSnapshotErrorCode.DESTINATION_EXISTS)
    with closing(sqlite3.connect(source, isolation_level=None)) as source_connection:
        source_connection.execute("PRAGMA trusted_schema = OFF")
        source_connection.execute("PRAGMA query_only = ON")
        with closing(sqlite3.connect(destination, isolation_level=None)) as target:
            target.execute("PRAGMA trusted_schema = OFF")
            source_connection.backup(target, pages=256, sleep=0.01)
            target.execute("PRAGMA journal_mode = DELETE")
            target.execute("PRAGMA synchronous = FULL")
    _fsync_file(destination)


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _exact_keys(value: Any, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise TypeError("snapshot manifest object shape is invalid")
    return value


def _manifest_from_bytes(raw: bytes) -> SQLiteSnapshotManifest:
    try:
        if not raw or len(raw) > _MANIFEST_MAX_BYTES:
            raise ValueError("manifest size")
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs)
        root = _exact_keys(
            decoded,
            {
                "format",
                "schema_version",
                "snapshot_id",
                "source_instance_id",
                "snapshot_sequence",
                "quiescence_id",
                "offline_asserted",
                "files",
                "coherence",
            },
        )
        if (
            root["format"] != SQLITE_OFFLINE_SNAPSHOT_FORMAT
            or root["schema_version"] != SQLITE_OFFLINE_SNAPSHOT_SCHEMA_VERSION
            or root["offline_asserted"] is not True
            or not isinstance(root["files"], list)
            or len(root["files"]) != 2
        ):
            raise TypeError("manifest root values are invalid")
        records = []
        for item in root["files"]:
            record = _exact_keys(
                item,
                {"role", "name", "schema_version", "bytes", "sha256"},
            )
            records.append(
                SQLiteSnapshotFileRecord(
                    record["role"],
                    record["name"],
                    record["schema_version"],
                    record["bytes"],
                    record["sha256"],
                ),
            )
        coherence_value = _exact_keys(
            root["coherence"],
            {"state_jobs", "authority_jobs"},
        )
        manifest = SQLiteSnapshotManifest(
            root["snapshot_id"],
            root["source_instance_id"],
            root["snapshot_sequence"],
            root["quiescence_id"],
            tuple(records),
            SQLiteSnapshotCoherence(
                coherence_value["state_jobs"],
                coherence_value["authority_jobs"],
            ),
        )
        if raw != _canonical_json(manifest.as_dict()):
            raise ValueError("manifest is not canonical")
        return manifest
    except (KeyError, TypeError, UnicodeError, ValueError, json.JSONDecodeError):
        raise SQLiteSnapshotError(
            SQLiteSnapshotErrorCode.BUNDLE_SCHEMA_MISMATCH,
        ) from None


def _checkpoint(
    signal: SQLiteSnapshotCrashSignal | None,
    checkpoint: SQLiteSnapshotCheckpoint,
    snapshot_id: str,
) -> None:
    if signal is None:
        return
    if not isinstance(signal, SQLiteSnapshotCrashSignal):
        raise TypeError("SQLite snapshot crash signal has the wrong type.")
    requested = signal.requested(checkpoint, snapshot_id)
    if not isinstance(requested, bool):
        raise TypeError("SQLite snapshot crash signal must return bool.")
    if requested:
        raise SQLiteSnapshotInterrupted(checkpoint)


def _require_offline(quiescence: SQLiteSnapshotQuiescence) -> None:
    if not isinstance(quiescence, SQLiteSnapshotQuiescence):
        raise TypeError("SQLite snapshot operation requires quiescence assertion.")
    if not quiescence.asserted:
        raise SQLiteSnapshotError(SQLiteSnapshotErrorCode.OFFLINE_REQUIRED)


def _require_publish_target(
    destination: Path,
    exists_code: SQLiteSnapshotErrorCode,
) -> Path:
    parent = destination.parent
    if (
        destination.exists()
        or destination.is_symlink()
        or not parent.is_dir()
        or parent.is_symlink()
    ):
        code = exists_code if destination.exists() or destination.is_symlink() else (
            SQLiteSnapshotErrorCode.INVALID_REQUEST
        )
        raise SQLiteSnapshotError(code)
    return parent


def _staging_path(destination: Path, snapshot_id: str, operation: str) -> Path:
    return destination.parent / f".{destination.name}.{snapshot_id}.{operation}-staging"


def _cleanup_staging(path: Path) -> None:
    try:
        if path.is_symlink():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
    except OSError:
        pass


class SQLiteOfflineSnapshotManager:
    """Product-disabled coordinator for a locked, offline SQLite database pair."""

    def __init__(
        self,
        state_database: str | PathLike[str],
        authority_database: str | PathLike[str],
        *,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        self._state_database = _local_file_path(
            state_database,
            "Snapshot state database",
        )
        self._authority_database = _local_file_path(
            authority_database,
            "Snapshot authority database",
        )
        if _same_path(self._state_database, self._authority_database):
            raise TypeError("Snapshot source databases must be distinct.")
        if (
            not isinstance(busy_timeout_ms, int)
            or isinstance(busy_timeout_ms, bool)
            or busy_timeout_ms < 1
            or busy_timeout_ms > 60_000
        ):
            raise TypeError("Snapshot busy timeout must be 1 to 60000 ms.")
        self._busy_timeout_ms = busy_timeout_ms
        self._operation_lock = threading.Lock()

    def __repr__(self) -> str:
        return (
            "SQLiteOfflineSnapshotManager("
            "schema_version=1, product_enabled=False, live_writes=False)"
        )

    def _connect_source(self, path: Path) -> sqlite3.Connection:
        if not path.is_file() or path.is_symlink():
            raise SQLiteSnapshotError(SQLiteSnapshotErrorCode.SOURCE_UNAVAILABLE)
        connection = sqlite3.connect(
            path,
            timeout=self._busy_timeout_ms / 1_000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        connection.execute("PRAGMA trusted_schema = OFF")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    @staticmethod
    def _require_source_wal(connection: sqlite3.Connection) -> None:
        mode = connection.execute("PRAGMA journal_mode").fetchone()
        synchronous = connection.execute("PRAGMA synchronous").fetchone()
        if (
            mode is None
            or str(mode[0]).casefold() != "wal"
            or synchronous is None
            or synchronous[0] != 2
        ):
            raise _SchemaFailure()

    def create_bundle(
        self,
        request: SQLiteOfflineSnapshotRequest,
        destination: str | PathLike[str],
        crash_signal: SQLiteSnapshotCrashSignal | None = None,
    ) -> SQLiteSnapshotManifest:
        if not isinstance(request, SQLiteOfflineSnapshotRequest):
            raise TypeError("create_bundle requires SQLiteOfflineSnapshotRequest.")
        _require_offline(request.quiescence)
        destination_path = _local_file_path(destination, "Snapshot destination")
        _require_publish_target(
            destination_path,
            SQLiteSnapshotErrorCode.DESTINATION_EXISTS,
        )
        stage = _staging_path(destination_path, request.snapshot_id, "create")
        if stage.exists() or stage.is_symlink():
            raise SQLiteSnapshotError(SQLiteSnapshotErrorCode.DESTINATION_EXISTS)

        published = False
        with self._operation_lock:
            try:
                stage.mkdir()
                state_copy = stage / SQLITE_SNAPSHOT_STATE_NAME
                authority_copy = stage / SQLITE_SNAPSHOT_AUTHORITY_NAME
                try:
                    with closing(
                        self._connect_source(self._state_database),
                    ) as state, closing(
                        self._connect_source(self._authority_database),
                    ) as authority:
                        state.execute("BEGIN IMMEDIATE")
                        try:
                            authority.execute("BEGIN IMMEDIATE")
                            self._require_source_wal(state)
                            self._require_source_wal(authority)
                            source_coherence = _validate_pair_connections(
                                state,
                                authority,
                            )
                            _backup_database(self._state_database, state_copy)
                            _checkpoint(
                                crash_signal,
                                SQLiteSnapshotCheckpoint.AFTER_STATE_BACKUP,
                                request.snapshot_id,
                            )
                            _backup_database(
                                self._authority_database,
                                authority_copy,
                            )
                            _checkpoint(
                                crash_signal,
                                SQLiteSnapshotCheckpoint.AFTER_AUTHORITY_BACKUP,
                                request.snapshot_id,
                            )
                        finally:
                            if authority.in_transaction:
                                authority.rollback()
                            if state.in_transaction:
                                state.rollback()
                except SQLiteSnapshotError:
                    raise
                except _SchemaFailure:
                    raise SQLiteSnapshotError(
                        SQLiteSnapshotErrorCode.SOURCE_SCHEMA_MISMATCH,
                    ) from None
                except _IntegrityFailure:
                    raise SQLiteSnapshotError(
                        SQLiteSnapshotErrorCode.SOURCE_UNAVAILABLE,
                    ) from None
                except _CoherenceFailure:
                    raise SQLiteSnapshotError(
                        SQLiteSnapshotErrorCode.STATE_AUTHORITY_CONFLICT,
                    ) from None
                except (OSError, sqlite3.Error, ValueError):
                    raise SQLiteSnapshotError(
                        SQLiteSnapshotErrorCode.SOURCE_UNAVAILABLE,
                    ) from None

                copied_coherence = _validate_pair_paths(state_copy, authority_copy)
                if copied_coherence != source_coherence:
                    raise SQLiteSnapshotError(
                        SQLiteSnapshotErrorCode.BUNDLE_INTEGRITY_FAILED,
                    )
                manifest = SQLiteSnapshotManifest(
                    request.snapshot_id,
                    request.source_instance_id,
                    request.snapshot_sequence,
                    request.quiescence.quiescence_id,
                    (
                        _file_record("broker-state", state_copy),
                        _file_record("runtime-fence-authority", authority_copy),
                    ),
                    copied_coherence,
                )
                manifest_path = stage / SQLITE_SNAPSHOT_MANIFEST_NAME
                manifest_path.write_bytes(_canonical_json(manifest.as_dict()))
                _fsync_file(manifest_path)
                _checkpoint(
                    crash_signal,
                    SQLiteSnapshotCheckpoint.AFTER_MANIFEST_WRITE,
                    request.snapshot_id,
                )
                _publish_directory(stage, destination_path)
                published = True
                _checkpoint(
                    crash_signal,
                    SQLiteSnapshotCheckpoint.AFTER_BUNDLE_PUBLISH,
                    request.snapshot_id,
                )
                return manifest
            except SQLiteSnapshotInterrupted:
                raise
            except SQLiteSnapshotError:
                if not published:
                    _cleanup_staging(stage)
                raise
            except (_SchemaFailure, _IntegrityFailure):
                if not published:
                    _cleanup_staging(stage)
                raise SQLiteSnapshotError(
                    SQLiteSnapshotErrorCode.BUNDLE_INTEGRITY_FAILED,
                ) from None
            except _CoherenceFailure:
                if not published:
                    _cleanup_staging(stage)
                raise SQLiteSnapshotError(
                    SQLiteSnapshotErrorCode.STATE_AUTHORITY_CONFLICT,
                ) from None
            except (OSError, sqlite3.Error, ValueError):
                if not published:
                    _cleanup_staging(stage)
                raise SQLiteSnapshotError(
                    SQLiteSnapshotErrorCode.SOURCE_UNAVAILABLE,
                ) from None

    @staticmethod
    def validate_bundle(
        bundle: str | PathLike[str],
        policy: SQLiteSnapshotRestorePolicy | None = None,
    ) -> SQLiteSnapshotManifest:
        bundle_path = _local_file_path(bundle, "Snapshot bundle")
        if policy is not None and not isinstance(policy, SQLiteSnapshotRestorePolicy):
            raise TypeError("validate_bundle policy has the wrong type.")
        if (
            not bundle_path.is_dir()
            or bundle_path.is_symlink()
        ):
            raise SQLiteSnapshotError(SQLiteSnapshotErrorCode.BUNDLE_INCOMPLETE)
        try:
            children = tuple(bundle_path.iterdir())
        except OSError:
            raise SQLiteSnapshotError(
                SQLiteSnapshotErrorCode.BUNDLE_INCOMPLETE,
            ) from None
        if (
            frozenset(child.name for child in children) != _EXPECTED_BUNDLE_NAMES
            or any(child.is_symlink() or not child.is_file() for child in children)
        ):
            raise SQLiteSnapshotError(SQLiteSnapshotErrorCode.BUNDLE_INCOMPLETE)
        manifest_path = bundle_path / SQLITE_SNAPSHOT_MANIFEST_NAME
        try:
            raw_manifest = manifest_path.read_bytes()
        except OSError:
            raise SQLiteSnapshotError(
                SQLiteSnapshotErrorCode.BUNDLE_INCOMPLETE,
            ) from None
        manifest = _manifest_from_bytes(raw_manifest)
        if policy is not None:
            if (
                manifest.snapshot_id != policy.expected_snapshot_id
                or manifest.source_instance_id
                != policy.expected_source_instance_id
            ):
                raise SQLiteSnapshotError(
                    SQLiteSnapshotErrorCode.SNAPSHOT_IDENTITY_MISMATCH,
                )
            if manifest.snapshot_sequence < policy.minimum_snapshot_sequence:
                raise SQLiteSnapshotError(
                    SQLiteSnapshotErrorCode.SNAPSHOT_ROLLBACK_REJECTED,
                )
        for record in manifest.files:
            path = bundle_path / record.name
            try:
                size, digest = _hash_file(path)
            except (OSError, _IntegrityFailure):
                raise SQLiteSnapshotError(
                    SQLiteSnapshotErrorCode.BUNDLE_INTEGRITY_FAILED,
                ) from None
            if (size, digest) != (record.bytes, record.sha256):
                raise SQLiteSnapshotError(
                    SQLiteSnapshotErrorCode.BUNDLE_INTEGRITY_FAILED,
                )
        try:
            coherence = _validate_pair_paths(
                bundle_path / SQLITE_SNAPSHOT_STATE_NAME,
                bundle_path / SQLITE_SNAPSHOT_AUTHORITY_NAME,
            )
        except _SchemaFailure:
            raise SQLiteSnapshotError(
                SQLiteSnapshotErrorCode.BUNDLE_SCHEMA_MISMATCH,
            ) from None
        except _IntegrityFailure:
            raise SQLiteSnapshotError(
                SQLiteSnapshotErrorCode.BUNDLE_INTEGRITY_FAILED,
            ) from None
        except _CoherenceFailure:
            raise SQLiteSnapshotError(
                SQLiteSnapshotErrorCode.STATE_AUTHORITY_CONFLICT,
            ) from None
        if coherence != manifest.coherence:
            raise SQLiteSnapshotError(
                SQLiteSnapshotErrorCode.BUNDLE_INTEGRITY_FAILED,
            )
        return manifest

    @staticmethod
    def restore_bundle(
        bundle: str | PathLike[str],
        destination: str | PathLike[str],
        policy: SQLiteSnapshotRestorePolicy,
        quiescence: SQLiteSnapshotQuiescence,
        crash_signal: SQLiteSnapshotCrashSignal | None = None,
    ) -> SQLiteSnapshotRestoreResult:
        if not isinstance(policy, SQLiteSnapshotRestorePolicy):
            raise TypeError("restore_bundle requires SQLiteSnapshotRestorePolicy.")
        _require_offline(quiescence)
        manifest = SQLiteOfflineSnapshotManager.validate_bundle(bundle, policy)
        bundle_path = _local_file_path(bundle, "Snapshot bundle")
        destination_path = _local_file_path(destination, "Restore destination")
        _require_publish_target(
            destination_path,
            SQLiteSnapshotErrorCode.RESTORE_TARGET_EXISTS,
        )
        stage = _staging_path(destination_path, manifest.snapshot_id, "restore")
        if stage.exists() or stage.is_symlink():
            raise SQLiteSnapshotError(SQLiteSnapshotErrorCode.RESTORE_TARGET_EXISTS)
        published = False
        try:
            stage.mkdir()
            state_target = stage / SQLITE_SNAPSHOT_STATE_NAME
            authority_target = stage / SQLITE_SNAPSHOT_AUTHORITY_NAME
            _backup_database(
                bundle_path / SQLITE_SNAPSHOT_STATE_NAME,
                state_target,
            )
            _checkpoint(
                crash_signal,
                SQLiteSnapshotCheckpoint.AFTER_STATE_RESTORE,
                manifest.snapshot_id,
            )
            _backup_database(
                bundle_path / SQLITE_SNAPSHOT_AUTHORITY_NAME,
                authority_target,
            )
            _checkpoint(
                crash_signal,
                SQLiteSnapshotCheckpoint.AFTER_AUTHORITY_RESTORE,
                manifest.snapshot_id,
            )
            revalidated = SQLiteOfflineSnapshotManager.validate_bundle(
                bundle_path,
                policy,
            )
            if revalidated != manifest:
                raise SQLiteSnapshotError(
                    SQLiteSnapshotErrorCode.BUNDLE_INTEGRITY_FAILED,
                )
            coherence = _validate_pair_paths(state_target, authority_target)
            if coherence != manifest.coherence:
                raise SQLiteSnapshotError(
                    SQLiteSnapshotErrorCode.BUNDLE_INTEGRITY_FAILED,
                )
            manifest_hash = sha256(
                _canonical_json(manifest.as_dict()),
            ).hexdigest()
            restore_record = {
                "format": SQLITE_OFFLINE_RESTORE_FORMAT,
                "schema_version": SQLITE_OFFLINE_SNAPSHOT_SCHEMA_VERSION,
                "snapshot_id": manifest.snapshot_id,
                "source_instance_id": manifest.source_instance_id,
                "snapshot_sequence": manifest.snapshot_sequence,
                "restore_quiescence_id": quiescence.quiescence_id,
                "snapshot_manifest_sha256": manifest_hash,
            }
            record_path = stage / SQLITE_RESTORE_RECORD_NAME
            record_path.write_bytes(_canonical_json(restore_record))
            _fsync_file(record_path)
            _checkpoint(
                crash_signal,
                SQLiteSnapshotCheckpoint.AFTER_RESTORE_RECORD_WRITE,
                manifest.snapshot_id,
            )
            _publish_directory(stage, destination_path)
            published = True
            _checkpoint(
                crash_signal,
                SQLiteSnapshotCheckpoint.AFTER_RESTORE_PUBLISH,
                manifest.snapshot_id,
            )
            return SQLiteSnapshotRestoreResult(
                manifest.snapshot_id,
                manifest.source_instance_id,
                manifest.snapshot_sequence,
                destination_path / SQLITE_SNAPSHOT_STATE_NAME,
                destination_path / SQLITE_SNAPSHOT_AUTHORITY_NAME,
                destination_path / SQLITE_RESTORE_RECORD_NAME,
            )
        except SQLiteSnapshotInterrupted:
            raise
        except SQLiteSnapshotError:
            if not published:
                _cleanup_staging(stage)
            raise
        except _SchemaFailure:
            if not published:
                _cleanup_staging(stage)
            raise SQLiteSnapshotError(
                SQLiteSnapshotErrorCode.BUNDLE_SCHEMA_MISMATCH,
            ) from None
        except _IntegrityFailure:
            if not published:
                _cleanup_staging(stage)
            raise SQLiteSnapshotError(
                SQLiteSnapshotErrorCode.BUNDLE_INTEGRITY_FAILED,
            ) from None
        except _CoherenceFailure:
            if not published:
                _cleanup_staging(stage)
            raise SQLiteSnapshotError(
                SQLiteSnapshotErrorCode.STATE_AUTHORITY_CONFLICT,
            ) from None
        except (OSError, sqlite3.Error, ValueError):
            if not published:
                _cleanup_staging(stage)
            raise SQLiteSnapshotError(
                SQLiteSnapshotErrorCode.RESTORE_FAILED,
            ) from None
