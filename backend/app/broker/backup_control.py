"""Durable local control plane for maintenance, backup ordering, and schedules."""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass
from enum import StrEnum
from os import PathLike
from pathlib import Path
from uuid import UUID, uuid4

from .durability import is_link_like
from .lease import LeaseClock, SystemLeaseClock, require_lease_clock
from .sqlite_snapshot import SQLiteSnapshotQuiescence, SQLiteSnapshotRestorePolicy


SQLITE_BACKUP_CONTROL_SCHEMA_VERSION = 1
SQLITE_BACKUP_CONTROL_PRODUCT_ENABLED = False
SQLITE_BACKUP_CONTROL_RETENTION_POLICY = "monotonic-no-automatic-delete"
MAX_MAINTENANCE_LEASE_MS = 86_400_000
MAX_BACKUP_SCHEDULE_INTERVAL_MS = 31_536_000_000
MIN_BACKUP_SCHEDULE_INTERVAL_MS = 60_000
_MAX_SEQUENCE = (1 << 63) - 1


class BackupControlErrorCode(StrEnum):
    CONTROL_UNAVAILABLE = "backup-control-unavailable"
    INSTALLATION_ID_MISMATCH = "backup-installation-id-mismatch"
    MAINTENANCE_ACTIVE = "maintenance-active"
    MAINTENANCE_NOT_OWNER = "maintenance-not-owner"
    MAINTENANCE_NOT_QUIESCENT = "maintenance-not-quiescent"
    ADMISSION_CONFLICT = "maintenance-admission-conflict"
    ADMISSION_EXPIRED = "maintenance-admission-expired"
    SNAPSHOT_IDENTITY_CONFLICT = "snapshot-identity-conflict"
    SNAPSHOT_SEQUENCE_EXHAUSTED = "snapshot-sequence-exhausted"
    RESTORE_ROLLBACK_REJECTED = "restore-rollback-rejected"
    SCHEDULE_NOT_FOUND = "backup-schedule-not-found"
    SCHEDULE_NOT_DUE = "backup-schedule-not-due"
    SCHEDULE_LEASED = "backup-schedule-leased"
    SCHEDULE_CONFLICT = "backup-schedule-conflict"
    SCHEDULE_BUSY = "backup-schedule-busy"


class BackupControlError(Exception):
    """Stable path-redacted control-plane error."""

    def __init__(self, code: BackupControlErrorCode) -> None:
        if not isinstance(code, BackupControlErrorCode):
            raise TypeError("BackupControlError requires BackupControlErrorCode.")
        self.code = code
        super().__init__(code.value)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code.value}


class MaintenancePhase(StrEnum):
    OPEN = "open"
    DRAINING = "draining"
    OFFLINE = "offline"


def _canonical_uuid(value: str, label: str) -> None:
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise TypeError(f"{label} must be a canonical UUID.") from error
    if str(parsed) != value:
        raise TypeError(f"{label} must be a canonical UUID.")


def _bounded_positive(value: int, label: str, maximum: int = _MAX_SEQUENCE) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
        or value > maximum
    ):
        raise TypeError(f"{label} is out of range.")


def _non_negative(value: int, label: str) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value > _MAX_SEQUENCE
    ):
        raise TypeError(f"{label} must be a non-negative signed 64-bit integer.")


def _local_database_path(value: str | PathLike[str]) -> Path:
    if not isinstance(value, (str, PathLike)):
        raise TypeError("Backup control database must be path-like.")
    raw = os.fspath(value)
    if (
        not isinstance(raw, str)
        or not raw
        or raw == ":memory:"
        or raw.casefold().startswith("file:")
        or "\x00" in raw
    ):
        raise TypeError("Backup control requires a local database path.")
    return Path(raw)


@dataclass(frozen=True, slots=True)
class MaintenanceRequest:
    maintenance_id: str
    owner_id: str
    quiescence_id: str
    lease_duration_ms: int

    def __post_init__(self) -> None:
        _canonical_uuid(self.maintenance_id, "Maintenance ID")
        _canonical_uuid(self.owner_id, "Maintenance owner ID")
        _canonical_uuid(self.quiescence_id, "Maintenance quiescence ID")
        _bounded_positive(
            self.lease_duration_ms,
            "Maintenance lease duration",
            MAX_MAINTENANCE_LEASE_MS,
        )


@dataclass(frozen=True, slots=True)
class MaintenanceLease:
    maintenance_id: str
    owner_id: str
    quiescence_id: str
    generation: int
    phase: MaintenancePhase
    lease_expires_at_ms: int

    def __post_init__(self) -> None:
        _canonical_uuid(self.maintenance_id, "Maintenance lease ID")
        _canonical_uuid(self.owner_id, "Maintenance lease owner ID")
        _canonical_uuid(self.quiescence_id, "Maintenance lease quiescence ID")
        _bounded_positive(self.generation, "Maintenance generation")
        if not isinstance(self.phase, MaintenancePhase):
            raise TypeError("Maintenance lease phase is invalid.")
        _bounded_positive(self.lease_expires_at_ms, "Maintenance expiry")


@dataclass(frozen=True, slots=True)
class OperationAdmission:
    operation_id: str
    owner_id: str
    maintenance_generation: int
    lease_expires_at_ms: int

    def __post_init__(self) -> None:
        _canonical_uuid(self.operation_id, "Admission operation ID")
        _canonical_uuid(self.owner_id, "Admission owner ID")
        _non_negative(self.maintenance_generation, "Admission generation")
        _bounded_positive(self.lease_expires_at_ms, "Admission expiry")


@dataclass(frozen=True, slots=True)
class SnapshotSequenceReservation:
    source_instance_id: str
    snapshot_id: str
    snapshot_sequence: int
    exported: bool

    def __post_init__(self) -> None:
        _canonical_uuid(self.source_instance_id, "Reservation source instance ID")
        _canonical_uuid(self.snapshot_id, "Reservation snapshot ID")
        _bounded_positive(self.snapshot_sequence, "Reservation sequence")
        if not isinstance(self.exported, bool):
            raise TypeError("Reservation exported marker must be bool.")


@dataclass(frozen=True, slots=True)
class RestoreFloor:
    source_instance_id: str
    minimum_snapshot_sequence: int
    snapshot_id: str
    updated_at_ms: int

    def __post_init__(self) -> None:
        _canonical_uuid(self.source_instance_id, "Restore floor source instance ID")
        _canonical_uuid(self.snapshot_id, "Restore floor snapshot ID")
        _bounded_positive(self.minimum_snapshot_sequence, "Restore floor sequence")
        _non_negative(self.updated_at_ms, "Restore floor update time")


@dataclass(frozen=True, slots=True)
class BackupScheduleDefinition:
    schedule_id: str
    source_instance_id: str
    interval_ms: int
    next_due_at_ms: int
    enabled: bool = True

    def __post_init__(self) -> None:
        _canonical_uuid(self.schedule_id, "Backup schedule ID")
        _canonical_uuid(self.source_instance_id, "Backup schedule source ID")
        _bounded_positive(
            self.interval_ms,
            "Backup schedule interval",
            MAX_BACKUP_SCHEDULE_INTERVAL_MS,
        )
        if self.interval_ms < MIN_BACKUP_SCHEDULE_INTERVAL_MS:
            raise TypeError("Backup schedule interval is below the minimum.")
        _non_negative(self.next_due_at_ms, "Backup schedule due time")
        if not isinstance(self.enabled, bool):
            raise TypeError("Backup schedule enabled marker must be bool.")


@dataclass(frozen=True, slots=True)
class BackupScheduleState:
    definition: BackupScheduleDefinition
    revision: int
    pending_snapshot_id: str | None
    pending_snapshot_sequence: int | None
    pending_scheduled_for_ms: int | None
    claim_token: str | None
    claim_owner_id: str | None
    claim_expires_at_ms: int | None
    last_completed_snapshot_id: str | None
    last_completed_sequence: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.definition, BackupScheduleDefinition):
            raise TypeError("Backup schedule state requires a definition.")
        _bounded_positive(self.revision, "Backup schedule revision")
        pending = (
            self.pending_snapshot_id,
            self.pending_snapshot_sequence,
            self.pending_scheduled_for_ms,
        )
        if any(value is None for value in pending) != all(
            value is None for value in pending
        ):
            raise TypeError("Backup schedule pending tuple is incomplete.")
        if self.pending_snapshot_id is not None:
            _canonical_uuid(self.pending_snapshot_id, "Pending snapshot ID")
            _bounded_positive(self.pending_snapshot_sequence, "Pending sequence")
            _non_negative(self.pending_scheduled_for_ms, "Pending due time")
        claim = (self.claim_token, self.claim_owner_id, self.claim_expires_at_ms)
        if any(value is None for value in claim) != all(value is None for value in claim):
            raise TypeError("Backup schedule claim tuple is incomplete.")
        if self.claim_token is not None:
            _canonical_uuid(self.claim_token, "Schedule claim token")
            _canonical_uuid(self.claim_owner_id, "Schedule claim owner")
            _bounded_positive(self.claim_expires_at_ms, "Schedule claim expiry")
        completed = (
            self.last_completed_snapshot_id,
            self.last_completed_sequence,
        )
        if any(value is None for value in completed) != all(
            value is None for value in completed
        ):
            raise TypeError("Backup schedule completion tuple is incomplete.")
        if self.last_completed_snapshot_id is not None:
            _canonical_uuid(
                self.last_completed_snapshot_id,
                "Completed snapshot ID",
            )
            _bounded_positive(
                self.last_completed_sequence,
                "Completed snapshot sequence",
            )


@dataclass(frozen=True, slots=True)
class BackupScheduleClaim:
    schedule_id: str
    claim_token: str
    owner_id: str
    scheduled_for_ms: int
    lease_expires_at_ms: int
    reservation: SnapshotSequenceReservation

    def __post_init__(self) -> None:
        _canonical_uuid(self.schedule_id, "Schedule claim schedule ID")
        _canonical_uuid(self.claim_token, "Schedule claim token")
        _canonical_uuid(self.owner_id, "Schedule claim owner ID")
        _non_negative(self.scheduled_for_ms, "Scheduled occurrence")
        _bounded_positive(self.lease_expires_at_ms, "Schedule claim expiry")
        if not isinstance(self.reservation, SnapshotSequenceReservation):
            raise TypeError("Schedule claim requires a snapshot reservation.")


_SCHEMA = (
    "CREATE TABLE control_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID",
    "CREATE TABLE maintenance_state (singleton INTEGER PRIMARY KEY CHECK (singleton = 1), generation INTEGER NOT NULL CHECK (generation >= 0), phase TEXT NOT NULL CHECK (phase IN ('open', 'draining', 'offline')), maintenance_id TEXT, owner_id TEXT, quiescence_id TEXT, lease_expires_at_ms INTEGER, updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0), CHECK ((phase = 'open' AND maintenance_id IS NULL AND owner_id IS NULL AND quiescence_id IS NULL AND lease_expires_at_ms IS NULL) OR (phase <> 'open' AND maintenance_id IS NOT NULL AND owner_id IS NOT NULL AND quiescence_id IS NOT NULL AND lease_expires_at_ms > 0)))",
    "CREATE TABLE operation_admissions (operation_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, maintenance_generation INTEGER NOT NULL CHECK (maintenance_generation >= 0), lease_expires_at_ms INTEGER NOT NULL CHECK (lease_expires_at_ms > 0)) WITHOUT ROWID",
    "CREATE TABLE snapshot_sequences (source_instance_id TEXT PRIMARY KEY, high_water_sequence INTEGER NOT NULL CHECK (high_water_sequence > 0)) WITHOUT ROWID",
    "CREATE TABLE snapshot_reservations (snapshot_id TEXT PRIMARY KEY, source_instance_id TEXT NOT NULL, snapshot_sequence INTEGER NOT NULL CHECK (snapshot_sequence > 0), exported INTEGER NOT NULL CHECK (exported IN (0, 1)), UNIQUE (source_instance_id, snapshot_sequence), FOREIGN KEY (source_instance_id) REFERENCES snapshot_sequences(source_instance_id)) WITHOUT ROWID",
    "CREATE TABLE restore_floors (source_instance_id TEXT PRIMARY KEY, minimum_snapshot_sequence INTEGER NOT NULL CHECK (minimum_snapshot_sequence > 0), snapshot_id TEXT NOT NULL, updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0)) WITHOUT ROWID",
    "CREATE TABLE backup_schedules (schedule_id TEXT PRIMARY KEY, source_instance_id TEXT NOT NULL, interval_ms INTEGER NOT NULL CHECK (interval_ms >= 60000), next_due_at_ms INTEGER NOT NULL CHECK (next_due_at_ms >= 0), enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)), revision INTEGER NOT NULL CHECK (revision > 0), pending_snapshot_id TEXT, pending_snapshot_sequence INTEGER, pending_scheduled_for_ms INTEGER, claim_token TEXT, claim_owner_id TEXT, claim_expires_at_ms INTEGER, last_completed_snapshot_id TEXT, last_completed_sequence INTEGER, CHECK ((pending_snapshot_id IS NULL AND pending_snapshot_sequence IS NULL AND pending_scheduled_for_ms IS NULL) OR (pending_snapshot_id IS NOT NULL AND pending_snapshot_sequence > 0 AND pending_scheduled_for_ms >= 0)), CHECK ((claim_token IS NULL AND claim_owner_id IS NULL AND claim_expires_at_ms IS NULL) OR (claim_token IS NOT NULL AND claim_owner_id IS NOT NULL AND claim_expires_at_ms > 0)), CHECK ((last_completed_snapshot_id IS NULL AND last_completed_sequence IS NULL) OR (last_completed_snapshot_id IS NOT NULL AND last_completed_sequence > 0))) WITHOUT ROWID",
)

_EXPECTED_COLUMNS = {
    "control_meta": ("key", "value"),
    "maintenance_state": (
        "singleton",
        "generation",
        "phase",
        "maintenance_id",
        "owner_id",
        "quiescence_id",
        "lease_expires_at_ms",
        "updated_at_ms",
    ),
    "operation_admissions": (
        "operation_id",
        "owner_id",
        "maintenance_generation",
        "lease_expires_at_ms",
    ),
    "snapshot_sequences": ("source_instance_id", "high_water_sequence"),
    "snapshot_reservations": (
        "snapshot_id",
        "source_instance_id",
        "snapshot_sequence",
        "exported",
    ),
    "restore_floors": (
        "source_instance_id",
        "minimum_snapshot_sequence",
        "snapshot_id",
        "updated_at_ms",
    ),
    "backup_schedules": (
        "schedule_id",
        "source_instance_id",
        "interval_ms",
        "next_due_at_ms",
        "enabled",
        "revision",
        "pending_snapshot_id",
        "pending_snapshot_sequence",
        "pending_scheduled_for_ms",
        "claim_token",
        "claim_owner_id",
        "claim_expires_at_ms",
        "last_completed_snapshot_id",
        "last_completed_sequence",
    ),
}


class SQLiteBackupControlStore:
    """Cross-process local control DB deliberately excluded from backup payloads."""

    def __init__(
        self,
        database: str | PathLike[str],
        installation_id: str,
        *,
        clock: LeaseClock | None = None,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        self._database = _local_database_path(database)
        _canonical_uuid(installation_id, "Backup installation ID")
        if (
            not isinstance(busy_timeout_ms, int)
            or isinstance(busy_timeout_ms, bool)
            or busy_timeout_ms < 1
            or busy_timeout_ms > 60_000
        ):
            raise TypeError("Backup control busy timeout must be 1 to 60000 ms.")
        if not self._database.parent.is_dir() or is_link_like(self._database.parent):
            raise BackupControlError(BackupControlErrorCode.CONTROL_UNAVAILABLE)
        if self._database.exists() and (
            not self._database.is_file() or is_link_like(self._database)
        ):
            raise BackupControlError(BackupControlErrorCode.CONTROL_UNAVAILABLE)
        self._installation_id = installation_id
        self._clock = require_lease_clock(clock)
        self._busy_timeout_ms = busy_timeout_ms
        self._process_lock = threading.Lock()
        try:
            with closing(self._connect(validate=False)) as connection:
                self._initialize(connection)
        except BackupControlError:
            raise
        except (OSError, sqlite3.Error, TypeError, ValueError):
            raise BackupControlError(
                BackupControlErrorCode.CONTROL_UNAVAILABLE,
            ) from None

    @property
    def installation_id(self) -> str:
        return self._installation_id

    def __repr__(self) -> str:
        return "SQLiteBackupControlStore(schema_version=1, product_enabled=False)"

    def _connect(self, *, validate: bool = True) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._database,
            timeout=self._busy_timeout_ms / 1_000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        connection.execute("PRAGMA trusted_schema = OFF")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        if validate:
            self._validate_schema(connection)
            row = connection.execute(
                "SELECT value FROM control_meta WHERE key = 'installation_id'",
            ).fetchone()
            if row is None or row["value"] != self._installation_id:
                raise BackupControlError(
                    BackupControlErrorCode.INSTALLATION_ID_MISMATCH,
                )
        return connection

    def _initialize(self, connection: sqlite3.Connection) -> None:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = tuple(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'",
            )
        )
        if version == 0 and not tables:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for statement in _SCHEMA:
                    connection.execute(statement)
                now = self._now_ms()
                connection.execute(
                    "INSERT INTO control_meta (key, value) VALUES (?, ?)",
                    ("installation_id", self._installation_id),
                )
                connection.execute(
                    "INSERT INTO maintenance_state "
                    "(singleton, generation, phase, maintenance_id, owner_id, "
                    "quiescence_id, lease_expires_at_ms, updated_at_ms) "
                    "VALUES (1, 0, 'open', NULL, NULL, NULL, NULL, ?)",
                    (now,),
                )
                connection.execute(
                    f"PRAGMA user_version = {SQLITE_BACKUP_CONTROL_SCHEMA_VERSION}",
                )
                connection.commit()
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
        self._validate_schema(connection)
        row = connection.execute(
            "SELECT value FROM control_meta WHERE key = 'installation_id'",
        ).fetchone()
        if row is None or row["value"] != self._installation_id:
            raise BackupControlError(
                BackupControlErrorCode.INSTALLATION_ID_MISMATCH,
            )

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version != SQLITE_BACKUP_CONTROL_SCHEMA_VERSION:
            raise BackupControlError(BackupControlErrorCode.CONTROL_UNAVAILABLE)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'",
            )
        }
        if tables != set(_EXPECTED_COLUMNS):
            raise BackupControlError(BackupControlErrorCode.CONTROL_UNAVAILABLE)
        for table, expected in _EXPECTED_COLUMNS.items():
            observed = tuple(
                row[1] for row in connection.execute(f"PRAGMA table_info({table})")
            )
            if observed != expected:
                raise BackupControlError(
                    BackupControlErrorCode.CONTROL_UNAVAILABLE,
                )
        if tuple(row[0] for row in connection.execute("PRAGMA integrity_check")) != (
            "ok",
        ):
            raise BackupControlError(BackupControlErrorCode.CONTROL_UNAVAILABLE)

    def _now_ms(self) -> int:
        observed = self._clock.now_ms()
        _non_negative(observed, "Backup control clock")
        return observed

    def _run(self, operation):
        with self._process_lock:
            try:
                return operation()
            except BackupControlError:
                raise
            except (OSError, sqlite3.Error, TypeError, ValueError):
                raise BackupControlError(
                    BackupControlErrorCode.CONTROL_UNAVAILABLE,
                ) from None

    @staticmethod
    def _decode_maintenance(row: sqlite3.Row) -> MaintenanceLease:
        return MaintenanceLease(
            row["maintenance_id"],
            row["owner_id"],
            row["quiescence_id"],
            row["generation"],
            MaintenancePhase(row["phase"]),
            row["lease_expires_at_ms"],
        )

    @staticmethod
    def _maintenance_row(connection: sqlite3.Connection) -> sqlite3.Row:
        row = connection.execute(
            "SELECT generation, phase, maintenance_id, owner_id, quiescence_id, "
            "lease_expires_at_ms FROM maintenance_state WHERE singleton = 1",
        ).fetchone()
        if row is None:
            raise BackupControlError(BackupControlErrorCode.CONTROL_UNAVAILABLE)
        return row

    @staticmethod
    def _delete_expired_admissions(
        connection: sqlite3.Connection,
        now_ms: int,
    ) -> None:
        connection.execute(
            "DELETE FROM operation_admissions WHERE lease_expires_at_ms <= ?",
            (now_ms,),
        )

    def admit_operation(
        self,
        operation_id: str,
        owner_id: str,
        *,
        lease_duration_ms: int,
    ) -> OperationAdmission:
        _canonical_uuid(operation_id, "Admission operation ID")
        _canonical_uuid(owner_id, "Admission owner ID")
        _bounded_positive(
            lease_duration_ms,
            "Admission lease duration",
            MAX_MAINTENANCE_LEASE_MS,
        )

        def operation() -> OperationAdmission:
            now = self._now_ms()
            expiry = now + lease_duration_ms
            if expiry > _MAX_SEQUENCE:
                raise TypeError("Admission expiry exceeds signed 64-bit range.")
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    self._delete_expired_admissions(connection, now)
                    maintenance = self._maintenance_row(connection)
                    if maintenance["phase"] != MaintenancePhase.OPEN.value:
                        raise BackupControlError(
                            BackupControlErrorCode.MAINTENANCE_ACTIVE,
                        )
                    existing = connection.execute(
                        "SELECT owner_id, maintenance_generation, "
                        "lease_expires_at_ms FROM operation_admissions "
                        "WHERE operation_id = ?",
                        (operation_id,),
                    ).fetchone()
                    if existing is not None:
                        if existing["owner_id"] != owner_id:
                            raise BackupControlError(
                                BackupControlErrorCode.ADMISSION_CONFLICT,
                            )
                        result = OperationAdmission(
                            operation_id,
                            owner_id,
                            existing["maintenance_generation"],
                            existing["lease_expires_at_ms"],
                        )
                        connection.commit()
                        return result
                    generation = maintenance["generation"]
                    connection.execute(
                        "INSERT INTO operation_admissions "
                        "(operation_id, owner_id, maintenance_generation, "
                        "lease_expires_at_ms) VALUES (?, ?, ?, ?)",
                        (operation_id, owner_id, generation, expiry),
                    )
                    connection.commit()
                    return OperationAdmission(
                        operation_id,
                        owner_id,
                        generation,
                        expiry,
                    )
                except Exception:
                    if connection.in_transaction:
                        connection.rollback()
                    raise

        return self._run(operation)

    def renew_operation(
        self,
        admission: OperationAdmission,
        *,
        lease_duration_ms: int,
    ) -> OperationAdmission:
        if not isinstance(admission, OperationAdmission):
            raise TypeError("Operation renewal requires OperationAdmission.")
        _bounded_positive(
            lease_duration_ms,
            "Admission lease duration",
            MAX_MAINTENANCE_LEASE_MS,
        )

        def operation() -> OperationAdmission:
            now = self._now_ms()
            expiry = now + lease_duration_ms
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    row = connection.execute(
                        "SELECT owner_id, maintenance_generation, "
                        "lease_expires_at_ms FROM operation_admissions "
                        "WHERE operation_id = ?",
                        (admission.operation_id,),
                    ).fetchone()
                    if (
                        row is None
                        or row["owner_id"] != admission.owner_id
                        or row["maintenance_generation"]
                        != admission.maintenance_generation
                    ):
                        raise BackupControlError(
                            BackupControlErrorCode.ADMISSION_CONFLICT,
                        )
                    if row["lease_expires_at_ms"] <= now:
                        raise BackupControlError(
                            BackupControlErrorCode.ADMISSION_EXPIRED,
                        )
                    connection.execute(
                        "UPDATE operation_admissions SET lease_expires_at_ms = ? "
                        "WHERE operation_id = ?",
                        (expiry, admission.operation_id),
                    )
                    connection.commit()
                    return OperationAdmission(
                        admission.operation_id,
                        admission.owner_id,
                        admission.maintenance_generation,
                        expiry,
                    )
                except Exception:
                    if connection.in_transaction:
                        connection.rollback()
                    raise

        return self._run(operation)

    def release_operation(self, admission: OperationAdmission) -> None:
        if not isinstance(admission, OperationAdmission):
            raise TypeError("Operation release requires OperationAdmission.")

        def operation() -> None:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    row = connection.execute(
                        "SELECT owner_id, maintenance_generation "
                        "FROM operation_admissions WHERE operation_id = ?",
                        (admission.operation_id,),
                    ).fetchone()
                    if row is None:
                        connection.commit()
                        return
                    if (
                        row["owner_id"] != admission.owner_id
                        or row["maintenance_generation"]
                        != admission.maintenance_generation
                    ):
                        raise BackupControlError(
                            BackupControlErrorCode.ADMISSION_CONFLICT,
                        )
                    connection.execute(
                        "DELETE FROM operation_admissions WHERE operation_id = ?",
                        (admission.operation_id,),
                    )
                    connection.commit()
                except Exception:
                    if connection.in_transaction:
                        connection.rollback()
                    raise

        self._run(operation)

    def begin_maintenance(self, request: MaintenanceRequest) -> MaintenanceLease:
        if not isinstance(request, MaintenanceRequest):
            raise TypeError("Maintenance begin requires MaintenanceRequest.")

        def operation() -> MaintenanceLease:
            now = self._now_ms()
            expiry = now + request.lease_duration_ms
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    row = self._maintenance_row(connection)
                    if row["phase"] != MaintenancePhase.OPEN.value:
                        if (
                            row["maintenance_id"] == request.maintenance_id
                            and row["owner_id"] == request.owner_id
                            and row["quiescence_id"] == request.quiescence_id
                            and row["lease_expires_at_ms"] > now
                        ):
                            result = self._decode_maintenance(row)
                            connection.commit()
                            return result
                        if row["lease_expires_at_ms"] > now:
                            raise BackupControlError(
                                BackupControlErrorCode.MAINTENANCE_ACTIVE,
                            )
                    generation = row["generation"] + 1
                    if generation > _MAX_SEQUENCE:
                        raise BackupControlError(
                            BackupControlErrorCode.CONTROL_UNAVAILABLE,
                        )
                    connection.execute(
                        "UPDATE maintenance_state SET generation = ?, "
                        "phase = 'draining', maintenance_id = ?, owner_id = ?, "
                        "quiescence_id = ?, lease_expires_at_ms = ?, "
                        "updated_at_ms = ? WHERE singleton = 1",
                        (
                            generation,
                            request.maintenance_id,
                            request.owner_id,
                            request.quiescence_id,
                            expiry,
                            now,
                        ),
                    )
                    connection.commit()
                    return MaintenanceLease(
                        request.maintenance_id,
                        request.owner_id,
                        request.quiescence_id,
                        generation,
                        MaintenancePhase.DRAINING,
                        expiry,
                    )
                except Exception:
                    if connection.in_transaction:
                        connection.rollback()
                    raise

        return self._run(operation)

    @staticmethod
    def _require_maintenance_owner(
        row: sqlite3.Row,
        lease: MaintenanceLease,
    ) -> None:
        if (
            row["maintenance_id"] != lease.maintenance_id
            or row["owner_id"] != lease.owner_id
            or row["quiescence_id"] != lease.quiescence_id
            or row["generation"] != lease.generation
        ):
            raise BackupControlError(BackupControlErrorCode.MAINTENANCE_NOT_OWNER)

    def mark_offline(self, lease: MaintenanceLease) -> MaintenanceLease:
        if not isinstance(lease, MaintenanceLease):
            raise TypeError("Maintenance offline transition requires a lease.")

        def operation() -> MaintenanceLease:
            now = self._now_ms()
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    row = self._maintenance_row(connection)
                    self._require_maintenance_owner(row, lease)
                    if row["lease_expires_at_ms"] <= now:
                        raise BackupControlError(
                            BackupControlErrorCode.MAINTENANCE_NOT_OWNER,
                        )
                    self._delete_expired_admissions(connection, now)
                    active = connection.execute(
                        "SELECT COUNT(*) FROM operation_admissions",
                    ).fetchone()[0]
                    if active:
                        raise BackupControlError(
                            BackupControlErrorCode.MAINTENANCE_NOT_QUIESCENT,
                        )
                    if row["phase"] not in {
                        MaintenancePhase.DRAINING.value,
                        MaintenancePhase.OFFLINE.value,
                    }:
                        raise BackupControlError(
                            BackupControlErrorCode.MAINTENANCE_NOT_OWNER,
                        )
                    connection.execute(
                        "UPDATE maintenance_state SET phase = 'offline', "
                        "updated_at_ms = ? WHERE singleton = 1",
                        (now,),
                    )
                    connection.commit()
                    return MaintenanceLease(
                        lease.maintenance_id,
                        lease.owner_id,
                        lease.quiescence_id,
                        lease.generation,
                        MaintenancePhase.OFFLINE,
                        row["lease_expires_at_ms"],
                    )
                except Exception:
                    if connection.in_transaction:
                        connection.rollback()
                    raise

        return self._run(operation)

    def renew_maintenance(
        self,
        lease: MaintenanceLease,
        *,
        lease_duration_ms: int,
    ) -> MaintenanceLease:
        if not isinstance(lease, MaintenanceLease):
            raise TypeError("Maintenance renewal requires a lease.")
        _bounded_positive(
            lease_duration_ms,
            "Maintenance lease duration",
            MAX_MAINTENANCE_LEASE_MS,
        )

        def operation() -> MaintenanceLease:
            now = self._now_ms()
            expiry = now + lease_duration_ms
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    row = self._maintenance_row(connection)
                    self._require_maintenance_owner(row, lease)
                    if row["lease_expires_at_ms"] <= now:
                        raise BackupControlError(
                            BackupControlErrorCode.MAINTENANCE_NOT_OWNER,
                        )
                    connection.execute(
                        "UPDATE maintenance_state SET lease_expires_at_ms = ?, "
                        "updated_at_ms = ? WHERE singleton = 1",
                        (expiry, now),
                    )
                    connection.commit()
                    return MaintenanceLease(
                        lease.maintenance_id,
                        lease.owner_id,
                        lease.quiescence_id,
                        lease.generation,
                        MaintenancePhase(row["phase"]),
                        expiry,
                    )
                except Exception:
                    if connection.in_transaction:
                        connection.rollback()
                    raise

        return self._run(operation)

    def verify_offline(self, lease: MaintenanceLease) -> SQLiteSnapshotQuiescence:
        if not isinstance(lease, MaintenanceLease):
            raise TypeError("Offline verification requires a maintenance lease.")

        def operation() -> SQLiteSnapshotQuiescence:
            now = self._now_ms()
            with closing(self._connect()) as connection:
                row = self._maintenance_row(connection)
                self._require_maintenance_owner(row, lease)
                if (
                    row["phase"] != MaintenancePhase.OFFLINE.value
                    or row["lease_expires_at_ms"] <= now
                ):
                    raise BackupControlError(
                        BackupControlErrorCode.MAINTENANCE_NOT_OWNER,
                    )
                active = connection.execute(
                    "SELECT COUNT(*) FROM operation_admissions "
                    "WHERE lease_expires_at_ms > ?",
                    (now,),
                ).fetchone()[0]
                if active:
                    raise BackupControlError(
                        BackupControlErrorCode.MAINTENANCE_NOT_QUIESCENT,
                    )
                return SQLiteSnapshotQuiescence(
                    lease.quiescence_id,
                    broker_stopped=True,
                    runtime_operations_stopped=True,
                    database_writers_stopped=True,
                )

        return self._run(operation)

    def end_maintenance(self, lease: MaintenanceLease) -> None:
        if not isinstance(lease, MaintenanceLease):
            raise TypeError("Maintenance end requires a lease.")

        def operation() -> None:
            now = self._now_ms()
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    row = self._maintenance_row(connection)
                    self._require_maintenance_owner(row, lease)
                    if row["lease_expires_at_ms"] <= now:
                        raise BackupControlError(
                            BackupControlErrorCode.MAINTENANCE_NOT_OWNER,
                        )
                    connection.execute(
                        "UPDATE maintenance_state SET phase = 'open', "
                        "maintenance_id = NULL, owner_id = NULL, "
                        "quiescence_id = NULL, lease_expires_at_ms = NULL, "
                        "updated_at_ms = ? WHERE singleton = 1",
                        (now,),
                    )
                    connection.commit()
                except Exception:
                    if connection.in_transaction:
                        connection.rollback()
                    raise

        self._run(operation)

    def _reserve_snapshot_tx(
        self,
        connection: sqlite3.Connection,
        source_instance_id: str,
        snapshot_id: str,
    ) -> SnapshotSequenceReservation:
        existing = connection.execute(
            "SELECT source_instance_id, snapshot_sequence, exported "
            "FROM snapshot_reservations WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if existing is not None:
            if existing["source_instance_id"] != source_instance_id:
                raise BackupControlError(
                    BackupControlErrorCode.SNAPSHOT_IDENTITY_CONFLICT,
                )
            return SnapshotSequenceReservation(
                source_instance_id,
                snapshot_id,
                existing["snapshot_sequence"],
                bool(existing["exported"]),
            )
        sequence_row = connection.execute(
            "SELECT high_water_sequence FROM snapshot_sequences "
            "WHERE source_instance_id = ?",
            (source_instance_id,),
        ).fetchone()
        sequence = 1 if sequence_row is None else sequence_row[0] + 1
        if sequence > _MAX_SEQUENCE:
            raise BackupControlError(
                BackupControlErrorCode.SNAPSHOT_SEQUENCE_EXHAUSTED,
            )
        if sequence_row is None:
            connection.execute(
                "INSERT INTO snapshot_sequences "
                "(source_instance_id, high_water_sequence) VALUES (?, ?)",
                (source_instance_id, sequence),
            )
        else:
            connection.execute(
                "UPDATE snapshot_sequences SET high_water_sequence = ? "
                "WHERE source_instance_id = ?",
                (sequence, source_instance_id),
            )
        connection.execute(
            "INSERT INTO snapshot_reservations "
            "(snapshot_id, source_instance_id, snapshot_sequence, exported) "
            "VALUES (?, ?, ?, 0)",
            (snapshot_id, source_instance_id, sequence),
        )
        return SnapshotSequenceReservation(
            source_instance_id,
            snapshot_id,
            sequence,
            False,
        )

    def reserve_snapshot(
        self,
        source_instance_id: str,
        snapshot_id: str,
    ) -> SnapshotSequenceReservation:
        _canonical_uuid(source_instance_id, "Snapshot source instance ID")
        _canonical_uuid(snapshot_id, "Snapshot ID")
        if source_instance_id != self._installation_id:
            raise BackupControlError(
                BackupControlErrorCode.INSTALLATION_ID_MISMATCH,
            )

        def operation() -> SnapshotSequenceReservation:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    result = self._reserve_snapshot_tx(
                        connection,
                        source_instance_id,
                        snapshot_id,
                    )
                    connection.commit()
                    return result
                except Exception:
                    if connection.in_transaction:
                        connection.rollback()
                    raise

        return self._run(operation)

    def mark_snapshot_exported(
        self,
        reservation: SnapshotSequenceReservation,
    ) -> SnapshotSequenceReservation:
        if not isinstance(reservation, SnapshotSequenceReservation):
            raise TypeError("Export completion requires a snapshot reservation.")

        def operation() -> SnapshotSequenceReservation:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    row = connection.execute(
                        "SELECT source_instance_id, snapshot_sequence "
                        "FROM snapshot_reservations WHERE snapshot_id = ?",
                        (reservation.snapshot_id,),
                    ).fetchone()
                    if row is None or (
                        row["source_instance_id"],
                        row["snapshot_sequence"],
                    ) != (
                        reservation.source_instance_id,
                        reservation.snapshot_sequence,
                    ):
                        raise BackupControlError(
                            BackupControlErrorCode.SNAPSHOT_IDENTITY_CONFLICT,
                        )
                    connection.execute(
                        "UPDATE snapshot_reservations SET exported = 1 "
                        "WHERE snapshot_id = ?",
                        (reservation.snapshot_id,),
                    )
                    connection.commit()
                    return SnapshotSequenceReservation(
                        reservation.source_instance_id,
                        reservation.snapshot_id,
                        reservation.snapshot_sequence,
                        True,
                    )
                except Exception:
                    if connection.in_transaction:
                        connection.rollback()
                    raise

        return self._run(operation)

    def current_restore_floor(self, source_instance_id: str) -> RestoreFloor | None:
        _canonical_uuid(source_instance_id, "Restore floor source instance ID")

        def operation() -> RestoreFloor | None:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT minimum_snapshot_sequence, snapshot_id, updated_at_ms "
                    "FROM restore_floors WHERE source_instance_id = ?",
                    (source_instance_id,),
                ).fetchone()
                if row is None:
                    return None
                return RestoreFloor(
                    source_instance_id,
                    row["minimum_snapshot_sequence"],
                    row["snapshot_id"],
                    row["updated_at_ms"],
                )

        return self._run(operation)

    def advance_restore_floor(
        self,
        source_instance_id: str,
        snapshot_id: str,
        snapshot_sequence: int,
        *,
        requested_minimum_sequence: int,
    ) -> tuple[RestoreFloor, SQLiteSnapshotRestorePolicy]:
        _canonical_uuid(source_instance_id, "Restore source instance ID")
        _canonical_uuid(snapshot_id, "Restore snapshot ID")
        _bounded_positive(snapshot_sequence, "Restore snapshot sequence")
        _bounded_positive(
            requested_minimum_sequence,
            "Requested restore minimum sequence",
        )

        def operation() -> tuple[RestoreFloor, SQLiteSnapshotRestorePolicy]:
            now = self._now_ms()
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    row = connection.execute(
                        "SELECT minimum_snapshot_sequence, snapshot_id, updated_at_ms "
                        "FROM restore_floors WHERE source_instance_id = ?",
                        (source_instance_id,),
                    ).fetchone()
                    durable_minimum = 0 if row is None else row[0]
                    effective_minimum = max(
                        durable_minimum,
                        requested_minimum_sequence,
                    )
                    if snapshot_sequence < effective_minimum:
                        raise BackupControlError(
                            BackupControlErrorCode.RESTORE_ROLLBACK_REJECTED,
                        )
                    if (
                        row is not None
                        and snapshot_sequence == durable_minimum
                        and snapshot_id != row["snapshot_id"]
                    ):
                        raise BackupControlError(
                            BackupControlErrorCode.SNAPSHOT_IDENTITY_CONFLICT,
                        )
                    if row is None:
                        connection.execute(
                            "INSERT INTO restore_floors "
                            "(source_instance_id, minimum_snapshot_sequence, "
                            "snapshot_id, updated_at_ms) VALUES (?, ?, ?, ?)",
                            (source_instance_id, snapshot_sequence, snapshot_id, now),
                        )
                    elif snapshot_sequence > durable_minimum:
                        connection.execute(
                            "UPDATE restore_floors SET "
                            "minimum_snapshot_sequence = ?, snapshot_id = ?, "
                            "updated_at_ms = ? WHERE source_instance_id = ?",
                            (snapshot_sequence, snapshot_id, now, source_instance_id),
                        )
                    persisted_snapshot_id = (
                        snapshot_id
                        if row is None or snapshot_sequence > durable_minimum
                        else row["snapshot_id"]
                    )
                    persisted_updated_at_ms = (
                        now
                        if row is None or snapshot_sequence > durable_minimum
                        else row["updated_at_ms"]
                    )
                    floor = RestoreFloor(
                        source_instance_id,
                        max(durable_minimum, snapshot_sequence),
                        persisted_snapshot_id,
                        persisted_updated_at_ms,
                    )
                    connection.commit()
                    return (
                        floor,
                        SQLiteSnapshotRestorePolicy(
                            snapshot_id,
                            source_instance_id,
                            floor.minimum_snapshot_sequence,
                        ),
                    )
                except Exception:
                    if connection.in_transaction:
                        connection.rollback()
                    raise

        return self._run(operation)

    @staticmethod
    def _decode_schedule(row: sqlite3.Row) -> BackupScheduleState:
        return BackupScheduleState(
            BackupScheduleDefinition(
                row["schedule_id"],
                row["source_instance_id"],
                row["interval_ms"],
                row["next_due_at_ms"],
                bool(row["enabled"]),
            ),
            row["revision"],
            row["pending_snapshot_id"],
            row["pending_snapshot_sequence"],
            row["pending_scheduled_for_ms"],
            row["claim_token"],
            row["claim_owner_id"],
            row["claim_expires_at_ms"],
            row["last_completed_snapshot_id"],
            row["last_completed_sequence"],
        )

    def configure_schedule(
        self,
        definition: BackupScheduleDefinition,
        *,
        expected_revision: int | None = None,
    ) -> BackupScheduleState:
        if not isinstance(definition, BackupScheduleDefinition):
            raise TypeError("Schedule configuration requires a definition.")
        if definition.source_instance_id != self._installation_id:
            raise BackupControlError(
                BackupControlErrorCode.INSTALLATION_ID_MISMATCH,
            )
        if expected_revision is not None:
            _bounded_positive(expected_revision, "Expected schedule revision")

        def operation() -> BackupScheduleState:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    row = connection.execute(
                        "SELECT * FROM backup_schedules WHERE schedule_id = ?",
                        (definition.schedule_id,),
                    ).fetchone()
                    if row is None:
                        if expected_revision is not None:
                            raise BackupControlError(
                                BackupControlErrorCode.SCHEDULE_CONFLICT,
                            )
                        revision = 1
                        connection.execute(
                            "INSERT INTO backup_schedules "
                            "(schedule_id, source_instance_id, interval_ms, "
                            "next_due_at_ms, enabled, revision) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                definition.schedule_id,
                                definition.source_instance_id,
                                definition.interval_ms,
                                definition.next_due_at_ms,
                                int(definition.enabled),
                                revision,
                            ),
                        )
                    else:
                        if expected_revision != row["revision"]:
                            raise BackupControlError(
                                BackupControlErrorCode.SCHEDULE_CONFLICT,
                            )
                        if (
                            row["pending_snapshot_id"] is not None
                            or row["claim_token"] is not None
                        ):
                            raise BackupControlError(
                                BackupControlErrorCode.SCHEDULE_BUSY,
                            )
                        revision = row["revision"] + 1
                        connection.execute(
                            "UPDATE backup_schedules SET source_instance_id = ?, "
                            "interval_ms = ?, next_due_at_ms = ?, enabled = ?, "
                            "revision = ? WHERE schedule_id = ?",
                            (
                                definition.source_instance_id,
                                definition.interval_ms,
                                definition.next_due_at_ms,
                                int(definition.enabled),
                                revision,
                                definition.schedule_id,
                            ),
                        )
                    result = connection.execute(
                        "SELECT * FROM backup_schedules WHERE schedule_id = ?",
                        (definition.schedule_id,),
                    ).fetchone()
                    connection.commit()
                    return self._decode_schedule(result)
                except Exception:
                    if connection.in_transaction:
                        connection.rollback()
                    raise

        return self._run(operation)

    def current_schedule(self, schedule_id: str) -> BackupScheduleState:
        _canonical_uuid(schedule_id, "Backup schedule ID")

        def operation() -> BackupScheduleState:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT * FROM backup_schedules WHERE schedule_id = ?",
                    (schedule_id,),
                ).fetchone()
                if row is None:
                    raise BackupControlError(
                        BackupControlErrorCode.SCHEDULE_NOT_FOUND,
                    )
                return self._decode_schedule(row)

        return self._run(operation)

    def claim_due_schedule(
        self,
        schedule_id: str,
        owner_id: str,
        *,
        lease_duration_ms: int,
    ) -> BackupScheduleClaim:
        _canonical_uuid(schedule_id, "Backup schedule ID")
        _canonical_uuid(owner_id, "Backup schedule owner ID")
        _bounded_positive(
            lease_duration_ms,
            "Backup schedule lease duration",
            MAX_MAINTENANCE_LEASE_MS,
        )

        def operation() -> BackupScheduleClaim:
            now = self._now_ms()
            expiry = now + lease_duration_ms
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    row = connection.execute(
                        "SELECT * FROM backup_schedules WHERE schedule_id = ?",
                        (schedule_id,),
                    ).fetchone()
                    if row is None:
                        raise BackupControlError(
                            BackupControlErrorCode.SCHEDULE_NOT_FOUND,
                        )
                    if not bool(row["enabled"]):
                        raise BackupControlError(
                            BackupControlErrorCode.SCHEDULE_NOT_DUE,
                        )
                    if (
                        row["claim_token"] is not None
                        and row["claim_expires_at_ms"] > now
                    ):
                        raise BackupControlError(
                            BackupControlErrorCode.SCHEDULE_LEASED,
                        )
                    snapshot_id = row["pending_snapshot_id"]
                    sequence = row["pending_snapshot_sequence"]
                    scheduled_for = row["pending_scheduled_for_ms"]
                    if snapshot_id is None:
                        if row["next_due_at_ms"] > now:
                            raise BackupControlError(
                                BackupControlErrorCode.SCHEDULE_NOT_DUE,
                            )
                        snapshot_id = str(uuid4())
                        scheduled_for = row["next_due_at_ms"]
                        reservation = self._reserve_snapshot_tx(
                            connection,
                            row["source_instance_id"],
                            snapshot_id,
                        )
                        sequence = reservation.snapshot_sequence
                    else:
                        reservation = self._reserve_snapshot_tx(
                            connection,
                            row["source_instance_id"],
                            snapshot_id,
                        )
                        if reservation.snapshot_sequence != sequence:
                            raise BackupControlError(
                                BackupControlErrorCode.SNAPSHOT_IDENTITY_CONFLICT,
                            )
                    claim_token = str(uuid4())
                    connection.execute(
                        "UPDATE backup_schedules SET pending_snapshot_id = ?, "
                        "pending_snapshot_sequence = ?, pending_scheduled_for_ms = ?, "
                        "claim_token = ?, claim_owner_id = ?, claim_expires_at_ms = ?, "
                        "revision = revision + 1 WHERE schedule_id = ?",
                        (
                            snapshot_id,
                            sequence,
                            scheduled_for,
                            claim_token,
                            owner_id,
                            expiry,
                            schedule_id,
                        ),
                    )
                    connection.commit()
                    return BackupScheduleClaim(
                        schedule_id,
                        claim_token,
                        owner_id,
                        scheduled_for,
                        expiry,
                        reservation,
                    )
                except Exception:
                    if connection.in_transaction:
                        connection.rollback()
                    raise

        return self._run(operation)

    @staticmethod
    def _require_schedule_claim(
        row: sqlite3.Row,
        claim: BackupScheduleClaim,
        *,
        now_ms: int,
    ) -> None:
        if (
            row["claim_token"] != claim.claim_token
            or row["claim_owner_id"] != claim.owner_id
            or row["pending_snapshot_id"] != claim.reservation.snapshot_id
            or row["pending_snapshot_sequence"]
            != claim.reservation.snapshot_sequence
            or row["pending_scheduled_for_ms"] != claim.scheduled_for_ms
            or row["claim_expires_at_ms"] != claim.lease_expires_at_ms
            or row["claim_expires_at_ms"] <= now_ms
        ):
            raise BackupControlError(BackupControlErrorCode.SCHEDULE_CONFLICT)

    def complete_schedule(self, claim: BackupScheduleClaim) -> BackupScheduleState:
        if not isinstance(claim, BackupScheduleClaim):
            raise TypeError("Schedule completion requires BackupScheduleClaim.")

        def operation() -> BackupScheduleState:
            now = self._now_ms()
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    row = connection.execute(
                        "SELECT * FROM backup_schedules WHERE schedule_id = ?",
                        (claim.schedule_id,),
                    ).fetchone()
                    if row is None:
                        raise BackupControlError(
                            BackupControlErrorCode.SCHEDULE_NOT_FOUND,
                        )
                    self._require_schedule_claim(row, claim, now_ms=now)
                    interval = row["interval_ms"]
                    scheduled_for = row["pending_scheduled_for_ms"]
                    elapsed = max(0, now - scheduled_for)
                    periods = elapsed // interval + 1
                    next_due = scheduled_for + periods * interval
                    connection.execute(
                        "UPDATE backup_schedules SET next_due_at_ms = ?, "
                        "pending_snapshot_id = NULL, "
                        "pending_snapshot_sequence = NULL, "
                        "pending_scheduled_for_ms = NULL, claim_token = NULL, "
                        "claim_owner_id = NULL, claim_expires_at_ms = NULL, "
                        "last_completed_snapshot_id = ?, "
                        "last_completed_sequence = ?, revision = revision + 1 "
                        "WHERE schedule_id = ?",
                        (
                            next_due,
                            claim.reservation.snapshot_id,
                            claim.reservation.snapshot_sequence,
                            claim.schedule_id,
                        ),
                    )
                    result = connection.execute(
                        "SELECT * FROM backup_schedules WHERE schedule_id = ?",
                        (claim.schedule_id,),
                    ).fetchone()
                    connection.commit()
                    return self._decode_schedule(result)
                except Exception:
                    if connection.in_transaction:
                        connection.rollback()
                    raise

        return self._run(operation)

    def release_schedule_claim(self, claim: BackupScheduleClaim) -> None:
        if not isinstance(claim, BackupScheduleClaim):
            raise TypeError("Schedule release requires BackupScheduleClaim.")

        def operation() -> None:
            now = self._now_ms()
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    row = connection.execute(
                        "SELECT * FROM backup_schedules WHERE schedule_id = ?",
                        (claim.schedule_id,),
                    ).fetchone()
                    if row is None:
                        raise BackupControlError(
                            BackupControlErrorCode.SCHEDULE_NOT_FOUND,
                        )
                    self._require_schedule_claim(row, claim, now_ms=now)
                    connection.execute(
                        "UPDATE backup_schedules SET claim_token = NULL, "
                        "claim_owner_id = NULL, claim_expires_at_ms = NULL, "
                        "revision = revision + 1 WHERE schedule_id = ?",
                        (claim.schedule_id,),
                    )
                    connection.commit()
                except Exception:
                    if connection.in_transaction:
                        connection.rollback()
                    raise

        self._run(operation)
