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

from .models import BrokerState
from .state import (
    TERMINAL_STATES,
    DurableJobEvent,
    JobStateSnapshot,
    RecoverableStatePage,
    StateStoreError,
    StateStoreErrorCode,
    validate_state_transition,
)


SQLITE_STATE_SCHEMA_VERSION = 1
SQLITE_STATE_RETENTION_POLICY = "append-only-no-automatic-deletion"
SQLITE_STATE_PRODUCT_ENABLED = False

_CREATE_JOB_EVENTS = """
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

_ROW_COLUMNS = (
    "job_id",
    "revision",
    "event_id",
    "operation_id",
    "operation_sequence",
    "state",
    "phase",
    "code",
    "retry",
    "backend",
    "classification",
    "cleanup_complete",
)
_SELECT_COLUMNS = ", ".join(_ROW_COLUMNS)
_QUALIFIED_SELECT_COLUMNS = ", ".join(
    f"events.{column}" for column in _ROW_COLUMNS
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
        self._schema_lock = threading.Lock()
        self._schema_ready = False

    def __repr__(self) -> str:
        return "SQLiteJobStateStore(schema_version=1, product_enabled=False)"

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
    def _schema_sql(connection: sqlite3.Connection) -> str | None:
        row = connection.execute(
            "SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = 'job_events'",
        ).fetchone()
        return None if row is None else row[0]

    @classmethod
    def _validate_schema(cls, connection: sqlite3.Connection) -> None:
        schema_sql = cls._schema_sql(connection)
        if schema_sql is None or _normalize_sql(schema_sql) != _normalize_sql(
            _CREATE_JOB_EVENTS,
        ):
            raise _store_unavailable()
        columns = tuple(
            row[1] for row in connection.execute("PRAGMA table_info(job_events)")
        )
        if columns != _ROW_COLUMNS:
            raise _store_unavailable()

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
                existing = cls._schema_sql(connection)
                if existing is None:
                    connection.execute(_CREATE_JOB_EVENTS)
                elif _normalize_sql(existing) != _normalize_sql(_CREATE_JOB_EVENTS):
                    raise _store_unavailable()
                connection.execute(
                    f"PRAGMA user_version = {SQLITE_STATE_SCHEMA_VERSION}",
                )
            elif version != SQLITE_STATE_SCHEMA_VERSION:
                raise _store_unavailable()
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
            )
            return JobStateSnapshot(event.identity, row["revision"], event)
        except (
            KeyError,
            TypeError,
            ValueError,
            RuntimeBackendError,
            StateStoreError,
        ):
            raise _store_unavailable() from None

    @staticmethod
    def _event_values(event: DurableJobEvent, revision: int) -> tuple[object, ...]:
        return (
            event.identity.job_id,
            revision,
            event.event_id,
            event.operation_id,
            event.operation_sequence,
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

    def _load_sync(self, identity: JobIdentity) -> JobStateSnapshot | None:
        def operation() -> JobStateSnapshot | None:
            connection = self._connect()
            try:
                row = connection.execute(
                    f"SELECT {_SELECT_COLUMNS} FROM job_events "
                    "WHERE job_id = ? ORDER BY revision DESC LIMIT 1",
                    (identity.job_id,),
                ).fetchone()
                return None if row is None else self._decode_snapshot(row)
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

                current_row = connection.execute(
                    f"SELECT {_SELECT_COLUMNS} FROM job_events "
                    "WHERE job_id = ? ORDER BY revision DESC LIMIT 1",
                    (event.identity.job_id,),
                ).fetchone()
                current = (
                    None if current_row is None else self._decode_snapshot(current_row)
                )
                revision = 0 if current is None else current.revision
                if revision != expected_revision:
                    raise StateStoreError(StateStoreErrorCode.REVISION_CONFLICT)
                validate_state_transition(
                    None if current is None else current.state,
                    event.state,
                )
                next_revision = revision + 1
                placeholders = ", ".join("?" for _ in _ROW_COLUMNS)
                connection.execute(
                    f"INSERT INTO job_events ({_SELECT_COLUMNS}) VALUES ({placeholders})",
                    self._event_values(event, next_revision),
                )
                connection.commit()
                return JobStateSnapshot(event.identity, next_revision, event)
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
                    WITH latest AS (
                        SELECT {_QUALIFIED_SELECT_COLUMNS}
                        FROM job_events AS events
                        INNER JOIN (
                            SELECT job_id, MAX(revision) AS revision
                            FROM job_events
                            GROUP BY job_id
                        ) AS revisions
                        ON revisions.job_id = events.job_id
                        AND revisions.revision = events.revision
                    )
                    SELECT {_SELECT_COLUMNS}
                    FROM latest
                    WHERE state NOT IN (?, ?, ?)
                    AND (? IS NULL OR job_id > ?)
                    ORDER BY job_id
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
