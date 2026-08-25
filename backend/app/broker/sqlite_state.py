"""File-backed SQLite candidate for the durable job-state adapter boundary."""

from __future__ import annotations

import asyncio
from os import PathLike, fspath
from pathlib import Path
import sqlite3
import threading
from typing import Callable, TypeVar

from backend.app.runtime.errors import (
    ErrorCode,
    RetryDisposition,
    RuntimeBackendError,
    RuntimePhase,
)
from backend.app.runtime.models import (
    JobIdentity,
    RuntimeKind,
    TerminalClassification,
)

from .lease import (
    DEFAULT_OWNER_LEASE_DURATION_MS,
    LeaseClock,
    require_lease_clock,
)
from .models import BrokerState
from .state import (
    TERMINAL_STATES,
    DurableJobEvent,
    DurableOperationOwnership,
    JobStateSnapshot,
    RecoverableStatePage,
    StateStoreError,
    StateStoreErrorCode,
    validate_operation_ownership,
    validate_state_transition,
)


SQLITE_STATE_SCHEMA_VERSION = 3
SQLITE_STATE_PREVIOUS_SCHEMA_VERSION = 2
SQLITE_STATE_LEGACY_SCHEMA_VERSION = 1
SQLITE_STATE_RETENTION_POLICY = "append-only-events-explicit-lease-renewal"
SQLITE_STATE_PRODUCT_ENABLED = False

_CREATE_JOB_EVENTS_V1 = """
CREATE TABLE job_events (
    job_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    event_id TEXT NOT NULL UNIQUE,
    operation_id TEXT NOT NULL,
    operation_sequence INTEGER NOT NULL CHECK (operation_sequence >= 1),
    state TEXT NOT NULL,
    phase TEXT NOT NULL,
    code TEXT,
    retry TEXT,
    backend TEXT,
    classification TEXT,
    cleanup_complete INTEGER NOT NULL CHECK (cleanup_complete IN (0, 1)),
    PRIMARY KEY (job_id, revision),
    UNIQUE (job_id, operation_id, operation_sequence)
)
""".strip()

_CREATE_JOB_EVENTS_V2 = """
CREATE TABLE job_events (
    job_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    event_id TEXT NOT NULL UNIQUE,
    operation_id TEXT NOT NULL,
    operation_sequence INTEGER NOT NULL CHECK (operation_sequence >= 1),
    owner_id TEXT NOT NULL,
    fencing_token INTEGER NOT NULL CHECK (fencing_token >= 1),
    state TEXT NOT NULL,
    phase TEXT NOT NULL,
    code TEXT,
    retry TEXT,
    backend TEXT,
    classification TEXT,
    cleanup_complete INTEGER NOT NULL CHECK (cleanup_complete IN (0, 1)),
    PRIMARY KEY (job_id, revision),
    UNIQUE (job_id, operation_id, operation_sequence)
)
""".strip()

_CREATE_JOB_EVENTS = """
CREATE TABLE job_events (
    job_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    event_id TEXT NOT NULL UNIQUE,
    operation_id TEXT NOT NULL,
    operation_sequence INTEGER NOT NULL CHECK (operation_sequence >= 1),
    owner_id TEXT NOT NULL,
    fencing_token INTEGER NOT NULL CHECK (fencing_token >= 1),
    lease_duration_ms INTEGER NOT NULL CHECK (lease_duration_ms >= 1 AND lease_duration_ms <= 300000),
    lease_expires_at_ms INTEGER NOT NULL CHECK (lease_expires_at_ms >= 1),
    state TEXT NOT NULL,
    phase TEXT NOT NULL,
    code TEXT,
    retry TEXT,
    backend TEXT,
    classification TEXT,
    cleanup_complete INTEGER NOT NULL CHECK (cleanup_complete IN (0, 1)),
    PRIMARY KEY (job_id, revision),
    UNIQUE (job_id, operation_id, operation_sequence)
)
""".strip()

_CREATE_JOB_LEASES = """
CREATE TABLE job_leases (
    job_id TEXT NOT NULL PRIMARY KEY,
    operation_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    fencing_token INTEGER NOT NULL CHECK (fencing_token >= 1),
    job_revision INTEGER NOT NULL CHECK (job_revision >= 1),
    lease_expires_at_ms INTEGER NOT NULL CHECK (lease_expires_at_ms >= 1)
)
""".strip()

_ROW_COLUMNS_V2 = (
    "job_id", "revision", "event_id", "operation_id", "operation_sequence",
    "owner_id", "fencing_token", "state", "phase", "code", "retry",
    "backend", "classification", "cleanup_complete",
)
_SELECT_COLUMNS_V2 = ", ".join(_ROW_COLUMNS_V2)
_ROW_COLUMNS = (
    "job_id", "revision", "event_id", "operation_id", "operation_sequence",
    "owner_id", "fencing_token", "lease_duration_ms", "lease_expires_at_ms",
    "state", "phase", "code", "retry", "backend", "classification",
    "cleanup_complete",
)
_LEASE_COLUMNS = (
    "job_id", "operation_id", "owner_id", "fencing_token", "job_revision",
    "lease_expires_at_ms",
)
_SELECT_COLUMNS = ", ".join(_ROW_COLUMNS)
_QUALIFIED_SELECT_COLUMNS = ", ".join(
    f"events.{column}" for column in _ROW_COLUMNS
)
_CURRENT_SELECT_COLUMNS = (
    f"{_QUALIFIED_SELECT_COLUMNS}, "
    "leases.lease_expires_at_ms AS current_lease_expires_at_ms"
)

_Result = TypeVar("_Result")


def _store_unavailable() -> StateStoreError:
    return StateStoreError(StateStoreErrorCode.STORE_UNAVAILABLE)


def _invalid_event() -> None:
    raise StateStoreError(StateStoreErrorCode.INVALID_EVENT)


def _normalize_sql(value: str) -> str:
    return " ".join(value.split()).casefold()


def _optional_enum(enum_type, value):
    return None if value is None else enum_type(value)


class SQLiteJobStateStore:
    """Inactive local-server candidate with transactional, file-backed state."""

    def __init__(
        self,
        database: str | PathLike[str],
        *,
        busy_timeout_ms: int = 5_000,
        clock: LeaseClock | None = None,
    ) -> None:
        if not isinstance(database, (str, PathLike)):
            raise TypeError("SQLiteJobStateStore database must be path-like.")
        raw_path = fspath(database)
        if not isinstance(raw_path, str):
            raise TypeError("SQLiteJobStateStore database must resolve to text.")
        if (
            not raw_path
            or raw_path == ":memory:"
            or raw_path.casefold().startswith("file:")
            or "\x00" in raw_path
        ):
            raise TypeError("SQLiteJobStateStore requires a local file path.")
        if (
            not isinstance(busy_timeout_ms, int)
            or isinstance(busy_timeout_ms, bool)
            or busy_timeout_ms < 1
            or busy_timeout_ms > 60_000
        ):
            raise TypeError("SQLiteJobStateStore busy timeout must be 1 to 60000 ms.")
        self._database = Path(raw_path)
        self._busy_timeout_ms = busy_timeout_ms
        self._clock = require_lease_clock(clock)
        self._schema_lock = threading.Lock()
        self._schema_ready = False

    def __repr__(self) -> str:
        return "SQLiteJobStateStore(schema_version=3, product_enabled=False)"

    def _connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(
                self._database,
                timeout=self._busy_timeout_ms / 1_000,
                isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            with self._schema_lock:
                if not self._schema_ready:
                    self._initialize_schema(connection)
                    self._schema_ready = True
                else:
                    self._configure_connection(connection)
            return connection
        except StateStoreError:
            if "connection" in locals():
                connection.close()
            raise
        except (OSError, sqlite3.Error, ValueError):
            if "connection" in locals():
                connection.close()
            raise _store_unavailable() from None

    @classmethod
    def _configure_connection(cls, connection: sqlite3.Connection) -> None:
        mode = connection.execute("PRAGMA journal_mode").fetchone()
        if mode is None or str(mode[0]).casefold() != "wal":
            raise _store_unavailable()
        connection.execute("PRAGMA synchronous = FULL")
        synchronous = connection.execute("PRAGMA synchronous").fetchone()
        version = connection.execute("PRAGMA user_version").fetchone()
        if synchronous is None or synchronous[0] != 2:
            raise _store_unavailable()
        if version is None or version[0] != SQLITE_STATE_SCHEMA_VERSION:
            raise _store_unavailable()
        cls._validate_schema(connection)

    @staticmethod
    def _schema_sql(connection: sqlite3.Connection, table: str) -> str | None:
        row = connection.execute(
            "SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        return None if row is None else row[0]

    @classmethod
    def _validate_schema(cls, connection: sqlite3.Connection) -> None:
        definitions = (
            ("job_events", _CREATE_JOB_EVENTS, _ROW_COLUMNS),
            ("job_leases", _CREATE_JOB_LEASES, _LEASE_COLUMNS),
        )
        for table, expected_sql, expected_columns in definitions:
            schema_sql = cls._schema_sql(connection, table)
            if schema_sql is None or _normalize_sql(schema_sql) != _normalize_sql(expected_sql):
                raise _store_unavailable()
            columns = tuple(
                row[1] for row in connection.execute(f"PRAGMA table_info({table})")
            )
            if columns != expected_columns:
                raise _store_unavailable()

    @classmethod
    def _migrate_v1_to_v2(cls, connection: sqlite3.Connection) -> None:
        schema_sql = cls._schema_sql(connection, "job_events")
        if schema_sql is None or _normalize_sql(schema_sql) != _normalize_sql(_CREATE_JOB_EVENTS_V1):
            raise _store_unavailable()
        connection.execute("ALTER TABLE job_events RENAME TO job_events_v1")
        connection.execute(_CREATE_JOB_EVENTS_V2)
        connection.execute(
            f"""
            INSERT INTO job_events ({_SELECT_COLUMNS_V2})
            WITH ownership AS (
                SELECT job_id, operation_id, MIN(revision) AS first_revision
                FROM job_events_v1
                GROUP BY job_id, operation_id
            ),
            ranked AS (
                SELECT job_id, operation_id,
                    DENSE_RANK() OVER (
                        PARTITION BY job_id ORDER BY first_revision
                    ) AS fencing_token
                FROM ownership
            )
            SELECT legacy.job_id, legacy.revision, legacy.event_id,
                legacy.operation_id, legacy.operation_sequence,
                legacy.operation_id, ranked.fencing_token, legacy.state,
                legacy.phase, legacy.code, legacy.retry, legacy.backend,
                legacy.classification, legacy.cleanup_complete
            FROM job_events_v1 AS legacy
            INNER JOIN ranked
                ON ranked.job_id = legacy.job_id
                AND ranked.operation_id = legacy.operation_id
            ORDER BY legacy.job_id, legacy.revision
            """,
        )
        connection.execute("DROP TABLE job_events_v1")

    @classmethod
    def _migrate_v2_to_v3(cls, connection: sqlite3.Connection) -> None:
        schema_sql = cls._schema_sql(connection, "job_events")
        if schema_sql is None or _normalize_sql(schema_sql) != _normalize_sql(_CREATE_JOB_EVENTS_V2):
            raise _store_unavailable()
        connection.execute("ALTER TABLE job_events RENAME TO job_events_v2")
        connection.execute(_CREATE_JOB_EVENTS)
        connection.execute(
            f"""
            INSERT INTO job_events ({_SELECT_COLUMNS})
            SELECT job_id, revision, event_id, operation_id, operation_sequence,
                owner_id, fencing_token, {DEFAULT_OWNER_LEASE_DURATION_MS}, 1,
                state, phase, code, retry, backend, classification,
                cleanup_complete
            FROM job_events_v2
            ORDER BY job_id, revision
            """,
        )
        connection.execute("DROP TABLE job_events_v2")
        connection.execute(_CREATE_JOB_LEASES)
        connection.execute(
            """
            INSERT INTO job_leases (
                job_id, operation_id, owner_id, fencing_token,
                job_revision, lease_expires_at_ms
            )
            SELECT events.job_id, events.operation_id, events.owner_id,
                events.fencing_token, events.revision, 1
            FROM job_events AS events
            INNER JOIN (
                SELECT job_id, MAX(revision) AS revision
                FROM job_events GROUP BY job_id
            ) AS latest
                ON latest.job_id = events.job_id
                AND latest.revision = events.revision
            """,
        )

    @classmethod
    def _create_v3(cls, connection: sqlite3.Connection) -> None:
        connection.execute(_CREATE_JOB_EVENTS)
        connection.execute(_CREATE_JOB_LEASES)

    @classmethod
    def _initialize_schema(cls, connection: sqlite3.Connection) -> None:
        mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()
        if mode is None or str(mode[0]).casefold() != "wal":
            raise _store_unavailable()
        connection.execute("PRAGMA synchronous = FULL")
        try:
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                existing = cls._schema_sql(connection, "job_events")
                if existing is None:
                    cls._create_v3(connection)
                elif _normalize_sql(existing) == _normalize_sql(_CREATE_JOB_EVENTS_V1):
                    cls._migrate_v1_to_v2(connection)
                    cls._migrate_v2_to_v3(connection)
                elif _normalize_sql(existing) == _normalize_sql(_CREATE_JOB_EVENTS_V2):
                    cls._migrate_v2_to_v3(connection)
                elif _normalize_sql(existing) != _normalize_sql(_CREATE_JOB_EVENTS):
                    raise _store_unavailable()
            elif version == SQLITE_STATE_LEGACY_SCHEMA_VERSION:
                cls._migrate_v1_to_v2(connection)
                cls._migrate_v2_to_v3(connection)
            elif version == SQLITE_STATE_PREVIOUS_SCHEMA_VERSION:
                cls._migrate_v2_to_v3(connection)
            elif version != SQLITE_STATE_SCHEMA_VERSION:
                raise _store_unavailable()
            connection.execute(f"PRAGMA user_version = {SQLITE_STATE_SCHEMA_VERSION}")
            cls._validate_schema(connection)
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        cls._configure_connection(connection)

    @staticmethod
    def _decode_snapshot(row: sqlite3.Row) -> JobStateSnapshot:
        try:
            cleanup = row["cleanup_complete"]
            if cleanup not in (0, 1):
                raise ValueError("invalid cleanup marker")
            event = DurableJobEvent(
                identity=JobIdentity(row["job_id"]),
                event_id=row["event_id"],
                operation_id=row["operation_id"],
                operation_sequence=row["operation_sequence"],
                owner_id=row["owner_id"],
                fencing_token=row["fencing_token"],
                state=BrokerState(row["state"]),
                phase=RuntimePhase(row["phase"]),
                code=_optional_enum(ErrorCode, row["code"]),
                retry=_optional_enum(RetryDisposition, row["retry"]),
                backend=_optional_enum(RuntimeKind, row["backend"]),
                classification=_optional_enum(
                    TerminalClassification,
                    row["classification"],
                ),
                cleanup_complete=bool(cleanup),
                lease_duration_ms=row["lease_duration_ms"],
            )
            expiry_column = (
                "current_lease_expires_at_ms"
                if "current_lease_expires_at_ms" in row.keys()
                else "lease_expires_at_ms"
            )
            return JobStateSnapshot(
                event.identity,
                row["revision"],
                event,
                row[expiry_column],
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            RuntimeBackendError,
            StateStoreError,
        ):
            raise _store_unavailable() from None

    @staticmethod
    def _event_values(
        event: DurableJobEvent,
        revision: int,
        lease_expires_at_ms: int,
    ) -> tuple[object, ...]:
        return (
            event.identity.job_id,
            revision,
            event.event_id,
            event.operation_id,
            event.operation_sequence,
            event.owner_id,
            event.fencing_token,
            event.lease_duration_ms,
            lease_expires_at_ms,
            event.state.value,
            event.phase.value,
            event.code.value if event.code is not None else None,
            event.retry.value if event.retry is not None else None,
            event.backend.value if event.backend is not None else None,
            event.classification.value if event.classification is not None else None,
            int(event.cleanup_complete),
        )

    def _run(self, operation: Callable[[], _Result]) -> _Result:
        try:
            return operation()
        except StateStoreError:
            raise
        except (OSError, sqlite3.Error, ValueError):
            raise _store_unavailable() from None

    def _now_ms(self) -> int:
        try:
            value = self._clock.now_ms()
        except Exception:
            raise _store_unavailable() from None
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise _store_unavailable()
        return value

    @staticmethod
    def _load_current(
        connection: sqlite3.Connection,
        identity: JobIdentity,
    ) -> JobStateSnapshot | None:
        row = connection.execute(
            f"""
            SELECT {_CURRENT_SELECT_COLUMNS}
            FROM job_events AS events
            INNER JOIN job_leases AS leases ON leases.job_id = events.job_id
            WHERE events.job_id = ?
            ORDER BY events.revision DESC
            LIMIT 1
            """,
            (identity.job_id,),
        ).fetchone()
        return None if row is None else SQLiteJobStateStore._decode_snapshot(row)

    def _load_sync(self, identity: JobIdentity) -> JobStateSnapshot | None:
        def operation() -> JobStateSnapshot | None:
            connection = self._connect()
            try:
                return self._load_current(connection, identity)
            finally:
                connection.close()

        return self._run(operation)

    async def load(self, identity: JobIdentity) -> JobStateSnapshot | None:
        if not isinstance(identity, JobIdentity):
            _invalid_event()
        return await asyncio.to_thread(self._load_sync, identity)

    def _append_sync(
        self,
        event: DurableJobEvent,
        expected_revision: int,
    ) -> JobStateSnapshot:
        def operation() -> JobStateSnapshot:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                replay_row = connection.execute(
                    f"SELECT {_SELECT_COLUMNS} FROM job_events WHERE event_id = ?",
                    (event.event_id,),
                ).fetchone()
                if replay_row is not None:
                    replay = self._decode_snapshot(replay_row)
                    if replay.last_event == event:
                        connection.rollback()
                        return replay
                    raise StateStoreError(StateStoreErrorCode.EVENT_CONFLICT)

                occupied = connection.execute(
                    "SELECT 1 FROM job_events WHERE job_id = ? "
                    "AND operation_id = ? AND operation_sequence = ?",
                    (
                        event.identity.job_id,
                        event.operation_id,
                        event.operation_sequence,
                    ),
                ).fetchone()
                if occupied is not None:
                    raise StateStoreError(StateStoreErrorCode.EVENT_CONFLICT)

                current = self._load_current(connection, event.identity)
                revision = 0 if current is None else current.revision
                if revision != expected_revision:
                    raise StateStoreError(StateStoreErrorCode.REVISION_CONFLICT)
                validate_state_transition(
                    None if current is None else current.state,
                    event.state,
                )
                now_ms = self._now_ms()
                validate_operation_ownership(current, event, now_ms=now_ms)
                next_revision = revision + 1
                lease_expires_at_ms = now_ms + event.lease_duration_ms
                placeholders = ", ".join("?" for _ in _ROW_COLUMNS)
                connection.execute(
                    f"INSERT INTO job_events ({_SELECT_COLUMNS}) VALUES ({placeholders})",
                    self._event_values(event, next_revision, lease_expires_at_ms),
                )
                connection.execute(
                    """
                    INSERT INTO job_leases (
                        job_id, operation_id, owner_id, fencing_token,
                        job_revision, lease_expires_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_id) DO UPDATE SET
                        operation_id = excluded.operation_id,
                        owner_id = excluded.owner_id,
                        fencing_token = excluded.fencing_token,
                        job_revision = excluded.job_revision,
                        lease_expires_at_ms = excluded.lease_expires_at_ms
                    """,
                    (
                        event.identity.job_id,
                        event.operation_id,
                        event.owner_id,
                        event.fencing_token,
                        next_revision,
                        lease_expires_at_ms,
                    ),
                )
                connection.commit()
                return JobStateSnapshot(
                    event.identity,
                    next_revision,
                    event,
                    lease_expires_at_ms,
                )
            except StateStoreError:
                if connection.in_transaction:
                    connection.rollback()
                raise
            except sqlite3.IntegrityError:
                if connection.in_transaction:
                    connection.rollback()
                raise StateStoreError(StateStoreErrorCode.EVENT_CONFLICT) from None
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
            finally:
                connection.close()

        return self._run(operation)

    async def append(
        self,
        event: DurableJobEvent,
        *,
        expected_revision: int,
    ) -> JobStateSnapshot:
        if not isinstance(event, DurableJobEvent):
            _invalid_event()
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 0
        ):
            _invalid_event()
        return await asyncio.to_thread(self._append_sync, event, expected_revision)

    def _renew_ownership_sync(
        self,
        ownership: DurableOperationOwnership,
        expected_revision: int,
        lease_duration_ms: int,
    ) -> JobStateSnapshot:
        def operation() -> JobStateSnapshot:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                current = self._load_current(connection, ownership.identity)
                if (
                    current is None
                    or current.ownership != ownership
                    or current.revision != expected_revision
                ):
                    raise StateStoreError(StateStoreErrorCode.OWNERSHIP_CONFLICT)
                now_ms = self._now_ms()
                if not current.lease_live_at(now_ms):
                    raise StateStoreError(StateStoreErrorCode.LEASE_EXPIRED)
                lease_expires_at_ms = now_ms + lease_duration_ms
                cursor = connection.execute(
                    """
                    UPDATE job_leases SET lease_expires_at_ms = ?
                    WHERE job_id = ? AND operation_id = ? AND owner_id = ?
                    AND fencing_token = ? AND job_revision = ?
                    """,
                    (
                        lease_expires_at_ms,
                        ownership.identity.job_id,
                        ownership.operation_id,
                        ownership.owner_id,
                        ownership.fencing_token,
                        expected_revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise StateStoreError(StateStoreErrorCode.OWNERSHIP_CONFLICT)
                connection.commit()
                return JobStateSnapshot(
                    current.identity,
                    current.revision,
                    current.last_event,
                    lease_expires_at_ms,
                )
            except StateStoreError:
                if connection.in_transaction:
                    connection.rollback()
                raise
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
            finally:
                connection.close()

        return self._run(operation)

    async def renew_ownership(
        self,
        ownership: DurableOperationOwnership,
        *,
        expected_revision: int,
        lease_duration_ms: int,
    ) -> JobStateSnapshot:
        if not isinstance(ownership, DurableOperationOwnership):
            _invalid_event()
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 1
            or not isinstance(lease_duration_ms, int)
            or isinstance(lease_duration_ms, bool)
            or lease_duration_ms < 1
            or lease_duration_ms > 300_000
        ):
            _invalid_event()
        return await asyncio.to_thread(
            self._renew_ownership_sync,
            ownership,
            expected_revision,
            lease_duration_ms,
        )

    def _verify_ownership_sync(
        self,
        ownership: DurableOperationOwnership,
        expected_revision: int | None,
    ) -> JobStateSnapshot:
        current = self._load_sync(ownership.identity)
        if (
            current is None
            or current.ownership != ownership
            or (
                expected_revision is not None
                and current.revision != expected_revision
            )
        ):
            raise StateStoreError(StateStoreErrorCode.OWNERSHIP_CONFLICT)
        if not current.lease_live_at(self._now_ms()):
            raise StateStoreError(StateStoreErrorCode.LEASE_EXPIRED)
        return current

    async def verify_ownership(
        self,
        ownership: DurableOperationOwnership,
        *,
        expected_revision: int | None = None,
    ) -> JobStateSnapshot:
        if not isinstance(ownership, DurableOperationOwnership):
            _invalid_event()
        if expected_revision is not None and (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 1
        ):
            _invalid_event()
        return await asyncio.to_thread(
            self._verify_ownership_sync,
            ownership,
            expected_revision,
        )

    def _scan_sync(
        self,
        after: str | None,
        limit: int,
    ) -> RecoverableStatePage:
        def operation() -> RecoverableStatePage:
            connection = self._connect()
            try:
                terminal_values = tuple(state.value for state in TERMINAL_STATES)
                rows = connection.execute(
                    f"""
                    SELECT {_CURRENT_SELECT_COLUMNS}
                    FROM job_events AS events
                    INNER JOIN (
                        SELECT job_id, MAX(revision) AS revision
                        FROM job_events GROUP BY job_id
                    ) AS revisions
                        ON revisions.job_id = events.job_id
                        AND revisions.revision = events.revision
                    INNER JOIN job_leases AS leases
                        ON leases.job_id = events.job_id
                    WHERE events.state NOT IN (?, ?, ?)
                    AND (? IS NULL OR events.job_id > ?)
                    ORDER BY events.job_id
                    LIMIT ?
                    """,
                    (*terminal_values, after, after, limit + 1),
                ).fetchall()
                snapshots = tuple(self._decode_snapshot(row) for row in rows)
                items = snapshots[:limit]
                next_cursor = (
                    items[-1].identity.job_id if len(snapshots) > limit else None
                )
                return RecoverableStatePage(items, next_cursor)
            finally:
                connection.close()

        return self._run(operation)

    async def scan_recoverable(
        self,
        *,
        after: str | None = None,
        limit: int = 100,
    ) -> RecoverableStatePage:
        if after is not None:
            try:
                JobIdentity(after)
            except RuntimeBackendError:
                _invalid_event()
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 1
            or limit > 1_000
        ):
            _invalid_event()
        return await asyncio.to_thread(self._scan_sync, after, limit)
