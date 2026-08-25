"""File-backed SQLite candidate for cross-process runtime fence authority."""

from __future__ import annotations

import asyncio
from contextlib import closing
from os import PathLike, fspath
from pathlib import Path
import sqlite3
import threading

from .errors import (
    ErrorCode,
    RetryDisposition,
    RuntimeBackendError,
    RuntimePhase,
)
from .fence_authority import _fenced, _validate_request
from .fencing import RuntimeFencingContext
from .models import JobIdentity, RuntimeKind


SQLITE_RUNTIME_FENCE_SCHEMA_VERSION = 1
SQLITE_RUNTIME_FENCE_PRODUCT_ENABLED = False

_CREATE_RUNTIME_FENCES = """
CREATE TABLE runtime_fences (
    job_id TEXT NOT NULL PRIMARY KEY,
    owner_id TEXT NOT NULL,
    fencing_token INTEGER NOT NULL CHECK (fencing_token >= 1)
)
""".strip()

_RUNTIME_FENCE_COLUMNS = ("job_id", "owner_id", "fencing_token")


def _normalize_sql(value: str) -> str:
    return " ".join(value.split()).casefold()


def _unavailable(
    phase: RuntimePhase,
    backend: RuntimeKind | None,
) -> RuntimeBackendError:
    return RuntimeBackendError(
        ErrorCode.RUNTIME_UNAVAILABLE,
        phase,
        retry=RetryDisposition.INFRASTRUCTURE,
        backend=None if backend is None else backend.value,
        detail="runtime-fence-authority-unavailable",
    )


class SQLiteRuntimeFenceAuthority:
    """Inactive monotonic authority shared by processes through one local file."""

    def __init__(
        self,
        database: str | PathLike[str],
        *,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        if not isinstance(database, (str, PathLike)):
            raise TypeError("SQLiteRuntimeFenceAuthority database must be path-like.")
        raw_path = fspath(database)
        if not isinstance(raw_path, str):
            raise TypeError(
                "SQLiteRuntimeFenceAuthority database must resolve to text.",
            )
        if (
            not raw_path
            or raw_path == ":memory:"
            or raw_path.casefold().startswith("file:")
            or "\x00" in raw_path
        ):
            raise TypeError(
                "SQLiteRuntimeFenceAuthority requires a local file path.",
            )
        if (
            not isinstance(busy_timeout_ms, int)
            or isinstance(busy_timeout_ms, bool)
            or busy_timeout_ms < 1
            or busy_timeout_ms > 60_000
        ):
            raise TypeError(
                "SQLiteRuntimeFenceAuthority busy timeout must be 1 to 60000 ms.",
            )
        self._database = Path(raw_path)
        self._busy_timeout_ms = busy_timeout_ms
        self._schema_lock = threading.Lock()
        self._schema_ready = False

    def __repr__(self) -> str:
        return (
            "SQLiteRuntimeFenceAuthority("
            "schema_version=1, product_enabled=False)"
        )

    @staticmethod
    def _schema_sql(connection: sqlite3.Connection) -> str | None:
        row = connection.execute(
            "SELECT sql FROM sqlite_schema "
            "WHERE type = 'table' AND name = 'runtime_fences'",
        ).fetchone()
        return None if row is None else row[0]

    @classmethod
    def _validate_schema(cls, connection: sqlite3.Connection) -> None:
        schema_sql = cls._schema_sql(connection)
        if (
            schema_sql is None
            or _normalize_sql(schema_sql) != _normalize_sql(_CREATE_RUNTIME_FENCES)
        ):
            raise ValueError("runtime fence schema mismatch")
        columns = tuple(
            row[1]
            for row in connection.execute("PRAGMA table_info(runtime_fences)")
        )
        if columns != _RUNTIME_FENCE_COLUMNS:
            raise ValueError("runtime fence columns mismatch")

    @classmethod
    def _configure_connection(cls, connection: sqlite3.Connection) -> None:
        mode = connection.execute("PRAGMA journal_mode").fetchone()
        if mode is None or str(mode[0]).casefold() != "wal":
            raise ValueError("runtime fence journal mode mismatch")
        connection.execute("PRAGMA synchronous = FULL")
        synchronous = connection.execute("PRAGMA synchronous").fetchone()
        version = connection.execute("PRAGMA user_version").fetchone()
        if synchronous is None or synchronous[0] != 2:
            raise ValueError("runtime fence synchronization mismatch")
        if (
            version is None
            or version[0] != SQLITE_RUNTIME_FENCE_SCHEMA_VERSION
        ):
            raise ValueError("runtime fence schema version mismatch")
        cls._validate_schema(connection)

    @classmethod
    def _initialize_schema(cls, connection: sqlite3.Connection) -> None:
        mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()
        if mode is None or str(mode[0]).casefold() != "wal":
            raise ValueError("runtime fence WAL unavailable")
        connection.execute("PRAGMA synchronous = FULL")
        try:
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            schema_sql = cls._schema_sql(connection)
            if version == 0 and schema_sql is None:
                connection.execute(_CREATE_RUNTIME_FENCES)
            elif (
                version not in (0, SQLITE_RUNTIME_FENCE_SCHEMA_VERSION)
                or schema_sql is None
                or _normalize_sql(schema_sql)
                != _normalize_sql(_CREATE_RUNTIME_FENCES)
            ):
                raise ValueError("runtime fence schema is unsupported")
            connection.execute(
                f"PRAGMA user_version = {SQLITE_RUNTIME_FENCE_SCHEMA_VERSION}",
            )
            cls._validate_schema(connection)
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        cls._configure_connection(connection)

    def _connect(
        self,
        phase: RuntimePhase,
        backend: RuntimeKind | None,
    ) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(
                self._database,
                timeout=self._busy_timeout_ms / 1_000,
                isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
            connection.execute("PRAGMA trusted_schema = OFF")
            with self._schema_lock:
                if not self._schema_ready:
                    self._initialize_schema(connection)
                    self._schema_ready = True
                else:
                    self._configure_connection(connection)
            return connection
        except (OSError, sqlite3.Error, TypeError, ValueError):
            if "connection" in locals():
                connection.close()
            raise _unavailable(phase, backend) from None

    @staticmethod
    def _decode_row(
        job_id: str,
        row: sqlite3.Row,
        phase: RuntimePhase,
        backend: RuntimeKind | None,
    ) -> RuntimeFencingContext:
        try:
            return RuntimeFencingContext(
                JobIdentity(job_id),
                row["owner_id"],
                row["fencing_token"],
            )
        except RuntimeBackendError:
            raise _unavailable(phase, backend) from None

    def _activate_sync(
        self,
        fence: RuntimeFencingContext,
        phase: RuntimePhase,
        backend: RuntimeKind,
    ) -> None:
        try:
            with closing(self._connect(phase, backend)) as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    current = connection.execute(
                        "SELECT owner_id, fencing_token FROM runtime_fences "
                        "WHERE job_id = ?",
                        (fence.identity.job_id,),
                    ).fetchone()
                    observed = (
                        None
                        if current is None
                        else self._decode_row(
                            fence.identity.job_id,
                            current,
                            phase,
                            backend,
                        )
                    )
                    if observed is not None and (
                        fence.fencing_token < observed.fencing_token
                        or (
                            fence.fencing_token == observed.fencing_token
                            and fence.owner_id != observed.owner_id
                        )
                    ):
                        _fenced(phase, backend)
                    if observed is None:
                        connection.execute(
                            "INSERT INTO runtime_fences VALUES (?, ?, ?)",
                            (
                                fence.identity.job_id,
                                fence.owner_id,
                                fence.fencing_token,
                            ),
                        )
                    elif fence.fencing_token > observed.fencing_token:
                        connection.execute(
                            "UPDATE runtime_fences "
                            "SET owner_id = ?, fencing_token = ? "
                            "WHERE job_id = ?",
                            (
                                fence.owner_id,
                                fence.fencing_token,
                                fence.identity.job_id,
                            ),
                        )
                    connection.commit()
                except Exception:
                    if connection.in_transaction:
                        connection.rollback()
                    raise
        except RuntimeBackendError:
            raise
        except (OSError, sqlite3.Error, TypeError, ValueError):
            raise _unavailable(phase, backend) from None

    async def activate(
        self,
        fence: RuntimeFencingContext,
        *,
        phase: RuntimePhase,
        backend: RuntimeKind,
    ) -> None:
        _validate_request(fence, phase, backend)
        await asyncio.to_thread(self._activate_sync, fence, phase, backend)

    def _verify_sync(
        self,
        fence: RuntimeFencingContext,
        phase: RuntimePhase,
        backend: RuntimeKind,
    ) -> None:
        try:
            with closing(self._connect(phase, backend)) as connection:
                current = connection.execute(
                    "SELECT owner_id, fencing_token FROM runtime_fences "
                    "WHERE job_id = ?",
                    (fence.identity.job_id,),
                ).fetchone()
                if current is None:
                    _fenced(phase, backend)
                observed = self._decode_row(
                    fence.identity.job_id,
                    current,
                    phase,
                    backend,
                )
                if observed != fence:
                    _fenced(phase, backend)
        except RuntimeBackendError:
            raise
        except (OSError, sqlite3.Error, TypeError, ValueError):
            raise _unavailable(phase, backend) from None

    async def verify(
        self,
        fence: RuntimeFencingContext,
        *,
        phase: RuntimePhase,
        backend: RuntimeKind,
    ) -> None:
        _validate_request(fence, phase, backend)
        await asyncio.to_thread(self._verify_sync, fence, phase, backend)

    def _current_sync(self, job_id: str) -> RuntimeFencingContext | None:
        try:
            with closing(
                self._connect(RuntimePhase.QUERY, None),
            ) as connection:
                current = connection.execute(
                    "SELECT job_id, owner_id, fencing_token "
                    "FROM runtime_fences WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
                if current is None:
                    return None
                return self._decode_row(
                    current["job_id"],
                    current,
                    RuntimePhase.QUERY,
                    None,
                )
        except RuntimeBackendError as error:
            if error.code is ErrorCode.RUNTIME_UNAVAILABLE:
                raise
            raise _unavailable(RuntimePhase.QUERY, None) from None
        except (OSError, sqlite3.Error, TypeError, ValueError):
            raise _unavailable(RuntimePhase.QUERY, None) from None

    async def current(self, job_id: str) -> RuntimeFencingContext | None:
        if not isinstance(job_id, str):
            raise TypeError("Runtime fence job ID must be text.")
        return await asyncio.to_thread(self._current_sync, job_id)
