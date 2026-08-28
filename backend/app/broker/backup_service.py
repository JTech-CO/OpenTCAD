"""Authenticated SQLite export/import service and durable scheduled runner."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
from dataclasses import dataclass
from enum import StrEnum
from os import PathLike
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable
from uuid import UUID, uuid5

from .backup_control import (
    BackupControlError,
    BackupControlErrorCode,
    BackupScheduleClaim,
    BackupScheduleState,
    MaintenanceLease,
    MaintenanceRequest,
    RestoreFloor,
    SQLiteBackupControlStore,
    SnapshotSequenceReservation,
)
from .durability import (
    DurablePublicationError,
    is_link_like,
    publish_directory,
    sync_file,
)
from .sqlite_snapshot import (
    SQLITE_RESTORE_RECORD_NAME,
    SQLITE_SNAPSHOT_AUTHORITY_NAME,
    SQLITE_SNAPSHOT_MANIFEST_NAME,
    SQLITE_SNAPSHOT_STATE_NAME,
    SQLiteOfflineSnapshotManager,
    SQLiteOfflineSnapshotRequest,
    SQLiteSnapshotError,
    SQLiteSnapshotManifest,
    SQLiteSnapshotRestorePolicy,
    SQLiteSnapshotRestoreResult,
)


AUTHENTICATED_BACKUP_SERVICE_PRODUCT_ENABLED = False
AUTHENTICATED_BACKUP_EXPORT_FORMAT = "opentcad-authenticated-sqlite-export"
AUTHENTICATED_BACKUP_IMPORT_FORMAT = "opentcad-authenticated-sqlite-import"
AUTHENTICATED_BACKUP_SCHEMA_VERSION = 1
AUTHENTICATED_BACKUP_ALGORITHM = "hmac-sha256"
AUTHENTICATED_EXPORT_RECORD_NAME = "export.json"
AUTHENTICATED_EXPORT_SNAPSHOT_DIRECTORY = "snapshot"
AUTHENTICATED_IMPORT_RECORD_NAME = "import.json"
AUTHENTICATED_IMPORT_RESTORE_DIRECTORY = "restored"
_AUTH_RECORD_MAX_BYTES = 64 * 1024
_MAX_HASHED_FILE_BYTES = 1 << 30
_EXPORT_DOMAIN = b"OpenTCAD authenticated SQLite export v1\x00"
_IMPORT_DOMAIN = b"OpenTCAD authenticated SQLite import v1\x00"
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_EXPECTED_EXPORT_NAMES = frozenset(
    {AUTHENTICATED_EXPORT_RECORD_NAME, AUTHENTICATED_EXPORT_SNAPSHOT_DIRECTORY},
)
_EXPECTED_IMPORT_NAMES = frozenset(
    {AUTHENTICATED_IMPORT_RECORD_NAME, AUTHENTICATED_IMPORT_RESTORE_DIRECTORY},
)
_EXPECTED_RESTORE_NAMES = frozenset(
    {
        SQLITE_SNAPSHOT_STATE_NAME,
        SQLITE_SNAPSHOT_AUTHORITY_NAME,
        SQLITE_RESTORE_RECORD_NAME,
    },
)


class AuthenticatedBackupErrorCode(StrEnum):
    INVALID_REQUEST = "authenticated-backup-invalid-request"
    DESTINATION_EXISTS = "authenticated-backup-destination-exists"
    EXPORT_INCOMPLETE = "authenticated-export-incomplete"
    AUTHENTICATION_FAILED = "backup-authentication-failed"
    MAINTENANCE_FAILED = "backup-maintenance-failed"
    CONTROL_UNAVAILABLE = "backup-control-unavailable"
    SNAPSHOT_FAILED = "authenticated-export-snapshot-failed"
    RESTORE_FAILED = "authenticated-import-restore-failed"
    ROLLBACK_REJECTED = "authenticated-import-rollback-rejected"
    DURABILITY_FAILED = "backup-durability-barrier-failed"


class AuthenticatedBackupError(Exception):
    """Stable public failure without paths, keys, SQLite detail, or MACs."""

    def __init__(self, code: AuthenticatedBackupErrorCode) -> None:
        if not isinstance(code, AuthenticatedBackupErrorCode):
            raise TypeError(
                "AuthenticatedBackupError requires AuthenticatedBackupErrorCode.",
            )
        self.code = code
        super().__init__(code.value)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code.value}


class BackupServiceCheckpoint(StrEnum):
    AFTER_MAINTENANCE_OFFLINE = "after-maintenance-offline"
    AFTER_SEQUENCE_RESERVED = "after-sequence-reserved"
    AFTER_SNAPSHOT_CREATED = "after-snapshot-created"
    AFTER_EXPORT_RECORD_WRITE = "after-export-record-write"
    AFTER_EXPORT_PUBLISH = "after-export-publish"
    AFTER_RESTORE_FLOOR_ADVANCE = "after-restore-floor-advance"
    AFTER_PAIR_RESTORE = "after-pair-restore"
    AFTER_IMPORT_RECORD_WRITE = "after-import-record-write"
    AFTER_IMPORT_PUBLISH = "after-import-publish"


class BackupServiceInterrupted(Exception):
    def __init__(self, checkpoint: BackupServiceCheckpoint) -> None:
        if not isinstance(checkpoint, BackupServiceCheckpoint):
            raise TypeError("Backup interruption checkpoint is invalid.")
        self.checkpoint = checkpoint
        super().__init__(checkpoint.value)


@runtime_checkable
class BackupServiceCrashSignal(Protocol):
    def requested(
        self,
        checkpoint: BackupServiceCheckpoint,
        snapshot_id: str,
    ) -> bool: ...


def _checkpoint(
    signal: BackupServiceCrashSignal | None,
    checkpoint: BackupServiceCheckpoint,
    snapshot_id: str,
) -> None:
    if signal is None:
        return
    if not isinstance(signal, BackupServiceCrashSignal):
        raise TypeError("Backup crash signal has the wrong type.")
    requested = signal.requested(checkpoint, snapshot_id)
    if not isinstance(requested, bool):
        raise TypeError("Backup crash signal must return bool.")
    if requested:
        raise BackupServiceInterrupted(checkpoint)


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
        or value > (1 << 63) - 1
    ):
        raise TypeError(f"{label} must be a positive signed 64-bit integer.")


def _local_path(value: str | PathLike[str], label: str) -> Path:
    if not isinstance(value, (str, PathLike)):
        raise TypeError(f"{label} must be path-like.")
    raw = os.fspath(value)
    if (
        not isinstance(raw, str)
        or not raw
        or raw.casefold().startswith("file:")
        or "\x00" in raw
    ):
        raise TypeError(f"{label} requires a local path.")
    return Path(raw)


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


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _exact_keys(value: Any, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("record shape")
    return value


def _sha256_file(path: Path) -> tuple[int, str]:
    try:
        if not path.is_file() or is_link_like(path):
            raise OSError("not regular")
        size = path.stat().st_size
        if size < 1 or size > _MAX_HASHED_FILE_BYTES:
            raise OSError("invalid size")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return size, digest.hexdigest()
    except OSError:
        raise AuthenticatedBackupError(
            AuthenticatedBackupErrorCode.AUTHENTICATION_FAILED,
        ) from None


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class HMACBackupKeyring:
    """Bounded in-memory keyring with a single active signing key."""

    __slots__ = ("_active_key_id", "_keys")

    def __init__(
        self,
        active_key_id: str,
        keys: Mapping[str, bytes],
    ) -> None:
        if not isinstance(active_key_id, str) or not _KEY_ID.fullmatch(
            active_key_id,
        ):
            raise TypeError("Active backup key ID is invalid.")
        if not isinstance(keys, Mapping) or not 1 <= len(keys) <= 8:
            raise TypeError("Backup keyring must contain 1 to 8 keys.")
        copied: dict[str, bytes] = {}
        for key_id, secret in keys.items():
            if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
                raise TypeError("Backup key ID is invalid.")
            if not isinstance(secret, bytes) or not 32 <= len(secret) <= 128:
                raise TypeError("Backup HMAC keys must contain 32 to 128 bytes.")
            copied[key_id] = bytes(secret)
        if active_key_id not in copied:
            raise TypeError("Active backup key is absent from keyring.")
        self._active_key_id = active_key_id
        self._keys = copied

    @property
    def active_key_id(self) -> str:
        return self._active_key_id

    def __repr__(self) -> str:
        return (
            "HMACBackupKeyring(active_key_id="
            f"{self._active_key_id!r}, key_count={len(self._keys)}, secrets=<redacted>)"
        )

    def sign(self, domain: bytes, value: bytes) -> tuple[str, str]:
        if not isinstance(domain, bytes) or not domain or not isinstance(value, bytes):
            raise TypeError("Backup signing input is invalid.")
        secret = self._keys[self._active_key_id]
        return (
            self._active_key_id,
            hmac.new(secret, domain + value, hashlib.sha256).hexdigest(),
        )

    def verify(self, key_id: str, domain: bytes, value: bytes, mac: str) -> bool:
        if (
            not isinstance(key_id, str)
            or not isinstance(domain, bytes)
            or not isinstance(value, bytes)
            or not isinstance(mac, str)
            or len(mac) != 64
            or any(character not in "0123456789abcdef" for character in mac)
        ):
            return False
        secret = self._keys.get(key_id)
        if secret is None:
            probe = b"\x00" * 32
            expected = hmac.new(probe, domain + value, hashlib.sha256).hexdigest()
            hmac.compare_digest(expected, mac)
            return False
        expected = hmac.new(secret, domain + value, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, mac)


@dataclass(frozen=True, slots=True)
class AuthenticatedExportRecord:
    key_id: str
    snapshot_id: str
    source_instance_id: str
    snapshot_sequence: int
    snapshot_manifest_sha256: str
    authentication_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.key_id, str) or not _KEY_ID.fullmatch(self.key_id):
            raise TypeError("Export key ID is invalid.")
        _canonical_uuid(self.snapshot_id, "Export snapshot ID")
        _canonical_uuid(self.source_instance_id, "Export source instance ID")
        _positive_sequence(self.snapshot_sequence, "Export snapshot sequence")
        for value, label in (
            (self.snapshot_manifest_sha256, "manifest digest"),
            (self.authentication_code, "authentication code"),
        ):
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise TypeError(f"Export {label} is invalid.")

    def unsigned_dict(self) -> dict[str, str | int]:
        return {
            "format": AUTHENTICATED_BACKUP_EXPORT_FORMAT,
            "schema_version": AUTHENTICATED_BACKUP_SCHEMA_VERSION,
            "algorithm": AUTHENTICATED_BACKUP_ALGORITHM,
            "key_id": self.key_id,
            "snapshot_id": self.snapshot_id,
            "source_instance_id": self.source_instance_id,
            "snapshot_sequence": self.snapshot_sequence,
            "snapshot_manifest_sha256": self.snapshot_manifest_sha256,
        }

    def as_dict(self) -> dict[str, str | int]:
        return {**self.unsigned_dict(), "authentication_code": self.authentication_code}


@dataclass(frozen=True, slots=True)
class AuthenticatedFileRecord:
    name: str
    bytes: int
    sha256: str

    def __post_init__(self) -> None:
        if self.name not in _EXPECTED_RESTORE_NAMES:
            raise TypeError("Authenticated restored file name is invalid.")
        _positive_sequence(self.bytes, "Authenticated restored file size")
        if (
            not isinstance(self.sha256, str)
            or len(self.sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.sha256)
        ):
            raise TypeError("Authenticated restored file hash is invalid.")

    def as_dict(self) -> dict[str, str | int]:
        return {"name": self.name, "bytes": self.bytes, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class AuthenticatedImportRecord:
    key_id: str
    snapshot_id: str
    source_instance_id: str
    snapshot_sequence: int
    durable_restore_floor: int
    export_record_sha256: str
    files: tuple[AuthenticatedFileRecord, ...]
    authentication_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.key_id, str) or not _KEY_ID.fullmatch(self.key_id):
            raise TypeError("Import key ID is invalid.")
        _canonical_uuid(self.snapshot_id, "Import snapshot ID")
        _canonical_uuid(self.source_instance_id, "Import source instance ID")
        _positive_sequence(self.snapshot_sequence, "Import snapshot sequence")
        _positive_sequence(self.durable_restore_floor, "Import restore floor")
        if self.durable_restore_floor > self.snapshot_sequence:
            raise TypeError("Import restore floor exceeds snapshot sequence.")
        if (
            not isinstance(self.export_record_sha256, str)
            or len(self.export_record_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.export_record_sha256
            )
        ):
            raise TypeError("Import export-record hash is invalid.")
        files = tuple(self.files)
        if (
            tuple(item.name for item in files)
            != (
                SQLITE_SNAPSHOT_STATE_NAME,
                SQLITE_SNAPSHOT_AUTHORITY_NAME,
                SQLITE_RESTORE_RECORD_NAME,
            )
            or any(not isinstance(item, AuthenticatedFileRecord) for item in files)
        ):
            raise TypeError("Import restored file records are invalid.")
        object.__setattr__(self, "files", files)
        if (
            not isinstance(self.authentication_code, str)
            or len(self.authentication_code) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.authentication_code
            )
        ):
            raise TypeError("Import authentication code is invalid.")

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "format": AUTHENTICATED_BACKUP_IMPORT_FORMAT,
            "schema_version": AUTHENTICATED_BACKUP_SCHEMA_VERSION,
            "algorithm": AUTHENTICATED_BACKUP_ALGORITHM,
            "key_id": self.key_id,
            "snapshot_id": self.snapshot_id,
            "source_instance_id": self.source_instance_id,
            "snapshot_sequence": self.snapshot_sequence,
            "durable_restore_floor": self.durable_restore_floor,
            "export_record_sha256": self.export_record_sha256,
            "files": [item.as_dict() for item in self.files],
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "authentication_code": self.authentication_code}


@dataclass(frozen=True, slots=True)
class AuthenticatedExportRequest:
    snapshot_id: str
    source_instance_id: str
    maintenance_id: str
    owner_id: str
    quiescence_id: str
    maintenance_lease_duration_ms: int

    def __post_init__(self) -> None:
        for value, label in (
            (self.snapshot_id, "Export snapshot ID"),
            (self.source_instance_id, "Export source instance ID"),
            (self.maintenance_id, "Export maintenance ID"),
            (self.owner_id, "Export owner ID"),
            (self.quiescence_id, "Export quiescence ID"),
        ):
            _canonical_uuid(value, label)
        _positive_sequence(
            self.maintenance_lease_duration_ms,
            "Export maintenance lease duration",
        )

    def maintenance_request(self) -> MaintenanceRequest:
        return MaintenanceRequest(
            self.maintenance_id,
            self.owner_id,
            self.quiescence_id,
            self.maintenance_lease_duration_ms,
        )


@dataclass(frozen=True, slots=True)
class AuthenticatedImportRequest:
    expected_snapshot_id: str
    expected_source_instance_id: str
    minimum_snapshot_sequence: int
    maintenance_id: str
    owner_id: str
    quiescence_id: str
    maintenance_lease_duration_ms: int

    def __post_init__(self) -> None:
        for value, label in (
            (self.expected_snapshot_id, "Import snapshot ID"),
            (self.expected_source_instance_id, "Import source instance ID"),
            (self.maintenance_id, "Import maintenance ID"),
            (self.owner_id, "Import owner ID"),
            (self.quiescence_id, "Import quiescence ID"),
        ):
            _canonical_uuid(value, label)
        _positive_sequence(self.minimum_snapshot_sequence, "Import minimum sequence")
        _positive_sequence(
            self.maintenance_lease_duration_ms,
            "Import maintenance lease duration",
        )

    def maintenance_request(self) -> MaintenanceRequest:
        return MaintenanceRequest(
            self.maintenance_id,
            self.owner_id,
            self.quiescence_id,
            self.maintenance_lease_duration_ms,
        )


@dataclass(frozen=True, slots=True)
class AuthenticatedExportResult:
    destination: Path
    snapshot: SQLiteSnapshotManifest
    record: AuthenticatedExportRecord
    reservation: SnapshotSequenceReservation


@dataclass(frozen=True, slots=True)
class AuthenticatedImportResult:
    destination: Path
    restore: SQLiteSnapshotRestoreResult
    record: AuthenticatedImportRecord
    floor: RestoreFloor


@dataclass(frozen=True, slots=True)
class ScheduledBackupResult:
    export: AuthenticatedExportResult
    schedule: BackupScheduleState


def _export_record_from_bytes(raw: bytes) -> AuthenticatedExportRecord:
    try:
        if not raw or len(raw) > _AUTH_RECORD_MAX_BYTES:
            raise ValueError("record size")
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs)
        value = _exact_keys(
            decoded,
            {
                "format",
                "schema_version",
                "algorithm",
                "key_id",
                "snapshot_id",
                "source_instance_id",
                "snapshot_sequence",
                "snapshot_manifest_sha256",
                "authentication_code",
            },
        )
        if (
            value["format"] != AUTHENTICATED_BACKUP_EXPORT_FORMAT
            or value["schema_version"] != AUTHENTICATED_BACKUP_SCHEMA_VERSION
            or value["algorithm"] != AUTHENTICATED_BACKUP_ALGORITHM
        ):
            raise ValueError("record identity")
        record = AuthenticatedExportRecord(
            value["key_id"],
            value["snapshot_id"],
            value["source_instance_id"],
            value["snapshot_sequence"],
            value["snapshot_manifest_sha256"],
            value["authentication_code"],
        )
        if raw != _canonical_json(record.as_dict()):
            raise ValueError("record not canonical")
        return record
    except (KeyError, TypeError, UnicodeError, ValueError, json.JSONDecodeError):
        raise AuthenticatedBackupError(
            AuthenticatedBackupErrorCode.AUTHENTICATION_FAILED,
        ) from None


def _import_record_from_bytes(raw: bytes) -> AuthenticatedImportRecord:
    try:
        if not raw or len(raw) > _AUTH_RECORD_MAX_BYTES:
            raise ValueError("record size")
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs)
        value = _exact_keys(
            decoded,
            {
                "format",
                "schema_version",
                "algorithm",
                "key_id",
                "snapshot_id",
                "source_instance_id",
                "snapshot_sequence",
                "durable_restore_floor",
                "export_record_sha256",
                "files",
                "authentication_code",
            },
        )
        if (
            value["format"] != AUTHENTICATED_BACKUP_IMPORT_FORMAT
            or value["schema_version"] != AUTHENTICATED_BACKUP_SCHEMA_VERSION
            or value["algorithm"] != AUTHENTICATED_BACKUP_ALGORITHM
            or not isinstance(value["files"], list)
        ):
            raise ValueError("record identity")
        files = []
        for item in value["files"]:
            file_value = _exact_keys(item, {"name", "bytes", "sha256"})
            files.append(
                AuthenticatedFileRecord(
                    file_value["name"],
                    file_value["bytes"],
                    file_value["sha256"],
                ),
            )
        record = AuthenticatedImportRecord(
            value["key_id"],
            value["snapshot_id"],
            value["source_instance_id"],
            value["snapshot_sequence"],
            value["durable_restore_floor"],
            value["export_record_sha256"],
            tuple(files),
            value["authentication_code"],
        )
        if raw != _canonical_json(record.as_dict()):
            raise ValueError("record not canonical")
        return record
    except (KeyError, TypeError, UnicodeError, ValueError, json.JSONDecodeError):
        raise AuthenticatedBackupError(
            AuthenticatedBackupErrorCode.AUTHENTICATION_FAILED,
        ) from None


class AuthenticatedSQLiteBackupService:
    """Application service for signed offline exports and fresh-target imports."""

    def __init__(
        self,
        snapshot_manager: SQLiteOfflineSnapshotManager,
        control: SQLiteBackupControlStore,
        keyring: HMACBackupKeyring,
    ) -> None:
        if not isinstance(snapshot_manager, SQLiteOfflineSnapshotManager):
            raise TypeError("Backup service requires SQLiteOfflineSnapshotManager.")
        if not isinstance(control, SQLiteBackupControlStore):
            raise TypeError("Backup service requires SQLiteBackupControlStore.")
        if not isinstance(keyring, HMACBackupKeyring):
            raise TypeError("Backup service requires HMACBackupKeyring.")
        self._snapshot_manager = snapshot_manager
        self._control = control
        self._keyring = keyring

    def __repr__(self) -> str:
        return (
            "AuthenticatedSQLiteBackupService(schema_version=1, "
            "algorithm='hmac-sha256', product_enabled=False)"
        )

    @staticmethod
    def _stage(destination: Path, snapshot_id: str, operation: str) -> Path:
        return destination.parent / (
            f".{destination.name}.{snapshot_id}.{operation}-staging"
        )

    @staticmethod
    def _require_destination(destination: Path) -> None:
        if (
            not destination.parent.is_dir()
            or is_link_like(destination.parent)
            or is_link_like(destination)
        ):
            raise AuthenticatedBackupError(
                AuthenticatedBackupErrorCode.INVALID_REQUEST,
            )

    @staticmethod
    def _require_stage_available(stage: Path) -> None:
        if stage.exists() or is_link_like(stage):
            raise AuthenticatedBackupError(
                AuthenticatedBackupErrorCode.DESTINATION_EXISTS,
            )

    @staticmethod
    def _cleanup_stage(stage: Path) -> None:
        try:
            if is_link_like(stage):
                return
            if stage.is_dir():
                shutil.rmtree(stage)
        except OSError:
            pass

    @staticmethod
    def _map_control(error: BackupControlError) -> AuthenticatedBackupError:
        if error.code is BackupControlErrorCode.RESTORE_ROLLBACK_REJECTED:
            return AuthenticatedBackupError(
                AuthenticatedBackupErrorCode.ROLLBACK_REJECTED,
            )
        if error.code in {
            BackupControlErrorCode.MAINTENANCE_ACTIVE,
            BackupControlErrorCode.MAINTENANCE_NOT_OWNER,
            BackupControlErrorCode.MAINTENANCE_NOT_QUIESCENT,
            BackupControlErrorCode.ADMISSION_CONFLICT,
            BackupControlErrorCode.ADMISSION_EXPIRED,
        }:
            return AuthenticatedBackupError(
                AuthenticatedBackupErrorCode.MAINTENANCE_FAILED,
            )
        return AuthenticatedBackupError(
            AuthenticatedBackupErrorCode.CONTROL_UNAVAILABLE,
        )

    def _sign_export(
        self,
        manifest: SQLiteSnapshotManifest,
        manifest_hash: str,
    ) -> AuthenticatedExportRecord:
        key_id = self._keyring.active_key_id
        unsigned = AuthenticatedExportRecord(
            key_id,
            manifest.snapshot_id,
            manifest.source_instance_id,
            manifest.snapshot_sequence,
            manifest_hash,
            "0" * 64,
        )
        _, code = self._keyring.sign(
            _EXPORT_DOMAIN,
            _canonical_json(unsigned.unsigned_dict()),
        )
        return AuthenticatedExportRecord(
            key_id,
            manifest.snapshot_id,
            manifest.source_instance_id,
            manifest.snapshot_sequence,
            manifest_hash,
            code,
        )

    def _sign_import(
        self,
        manifest: SQLiteSnapshotManifest,
        floor: RestoreFloor,
        export_record_hash: str,
        files: tuple[AuthenticatedFileRecord, ...],
    ) -> AuthenticatedImportRecord:
        key_id = self._keyring.active_key_id
        unsigned = AuthenticatedImportRecord(
            key_id,
            manifest.snapshot_id,
            manifest.source_instance_id,
            manifest.snapshot_sequence,
            floor.minimum_snapshot_sequence,
            export_record_hash,
            files,
            "0" * 64,
        )
        _, code = self._keyring.sign(
            _IMPORT_DOMAIN,
            _canonical_json(unsigned.unsigned_dict()),
        )
        return AuthenticatedImportRecord(
            key_id,
            manifest.snapshot_id,
            manifest.source_instance_id,
            manifest.snapshot_sequence,
            floor.minimum_snapshot_sequence,
            export_record_hash,
            files,
            code,
        )

    def validate_export(
        self,
        export: str | PathLike[str],
        policy: SQLiteSnapshotRestorePolicy | None = None,
    ) -> tuple[AuthenticatedExportRecord, SQLiteSnapshotManifest]:
        export_path = _local_path(export, "Authenticated export")
        if policy is not None and not isinstance(policy, SQLiteSnapshotRestorePolicy):
            raise TypeError("Authenticated export policy has the wrong type.")
        try:
            if not export_path.is_dir() or is_link_like(export_path):
                raise AuthenticatedBackupError(
                    AuthenticatedBackupErrorCode.EXPORT_INCOMPLETE,
                )
            children = tuple(export_path.iterdir())
            if (
                frozenset(child.name for child in children) != _EXPECTED_EXPORT_NAMES
                or any(is_link_like(child) for child in children)
                or not (export_path / AUTHENTICATED_EXPORT_RECORD_NAME).is_file()
                or not (
                    export_path / AUTHENTICATED_EXPORT_SNAPSHOT_DIRECTORY
                ).is_dir()
            ):
                raise AuthenticatedBackupError(
                    AuthenticatedBackupErrorCode.EXPORT_INCOMPLETE,
                )
            record_bytes = (
                export_path / AUTHENTICATED_EXPORT_RECORD_NAME
            ).read_bytes()
            record = _export_record_from_bytes(record_bytes)
            if not self._keyring.verify(
                record.key_id,
                _EXPORT_DOMAIN,
                _canonical_json(record.unsigned_dict()),
                record.authentication_code,
            ):
                raise AuthenticatedBackupError(
                    AuthenticatedBackupErrorCode.AUTHENTICATION_FAILED,
                )
            snapshot_path = export_path / AUTHENTICATED_EXPORT_SNAPSHOT_DIRECTORY
            manifest_bytes = (
                snapshot_path / SQLITE_SNAPSHOT_MANIFEST_NAME
            ).read_bytes()
            if _sha256_bytes(manifest_bytes) != record.snapshot_manifest_sha256:
                raise AuthenticatedBackupError(
                    AuthenticatedBackupErrorCode.AUTHENTICATION_FAILED,
                )
            manifest = SQLiteOfflineSnapshotManager.validate_bundle(
                snapshot_path,
                policy,
            )
            if (
                manifest.snapshot_id,
                manifest.source_instance_id,
                manifest.snapshot_sequence,
            ) != (
                record.snapshot_id,
                record.source_instance_id,
                record.snapshot_sequence,
            ):
                raise AuthenticatedBackupError(
                    AuthenticatedBackupErrorCode.AUTHENTICATION_FAILED,
                )
            return record, manifest
        except AuthenticatedBackupError:
            raise
        except SQLiteSnapshotError:
            raise AuthenticatedBackupError(
                AuthenticatedBackupErrorCode.AUTHENTICATION_FAILED,
            ) from None
        except (OSError, TypeError, ValueError):
            raise AuthenticatedBackupError(
                AuthenticatedBackupErrorCode.EXPORT_INCOMPLETE,
            ) from None

    def validate_import(
        self,
        imported: str | PathLike[str],
        *,
        expected_snapshot_id: str | None = None,
        expected_source_instance_id: str | None = None,
        expected_export_record_sha256: str | None = None,
    ) -> AuthenticatedImportRecord:
        imported_path = _local_path(imported, "Authenticated import")
        for value, label in (
            (expected_snapshot_id, "Expected import snapshot ID"),
            (expected_source_instance_id, "Expected import source instance ID"),
        ):
            if value is not None:
                _canonical_uuid(value, label)
        try:
            if not imported_path.is_dir() or is_link_like(imported_path):
                raise AuthenticatedBackupError(
                    AuthenticatedBackupErrorCode.RESTORE_FAILED,
                )
            children = tuple(imported_path.iterdir())
            restore_path = imported_path / AUTHENTICATED_IMPORT_RESTORE_DIRECTORY
            if (
                frozenset(child.name for child in children) != _EXPECTED_IMPORT_NAMES
                or any(is_link_like(child) for child in children)
                or not (imported_path / AUTHENTICATED_IMPORT_RECORD_NAME).is_file()
                or not restore_path.is_dir()
                or is_link_like(restore_path)
            ):
                raise AuthenticatedBackupError(
                    AuthenticatedBackupErrorCode.RESTORE_FAILED,
                )
            restored = tuple(restore_path.iterdir())
            if (
                frozenset(child.name for child in restored) != _EXPECTED_RESTORE_NAMES
                or any(is_link_like(child) or not child.is_file() for child in restored)
            ):
                raise AuthenticatedBackupError(
                    AuthenticatedBackupErrorCode.RESTORE_FAILED,
                )
            raw = (imported_path / AUTHENTICATED_IMPORT_RECORD_NAME).read_bytes()
            record = _import_record_from_bytes(raw)
            if not self._keyring.verify(
                record.key_id,
                _IMPORT_DOMAIN,
                _canonical_json(record.unsigned_dict()),
                record.authentication_code,
            ):
                raise AuthenticatedBackupError(
                    AuthenticatedBackupErrorCode.AUTHENTICATION_FAILED,
                )
            if (
                expected_snapshot_id is not None
                and record.snapshot_id != expected_snapshot_id
            ) or (
                expected_source_instance_id is not None
                and record.source_instance_id != expected_source_instance_id
            ) or (
                expected_export_record_sha256 is not None
                and record.export_record_sha256 != expected_export_record_sha256
            ):
                raise AuthenticatedBackupError(
                    AuthenticatedBackupErrorCode.AUTHENTICATION_FAILED,
                )
            for item in record.files:
                if _sha256_file(restore_path / item.name) != (
                    item.bytes,
                    item.sha256,
                ):
                    raise AuthenticatedBackupError(
                        AuthenticatedBackupErrorCode.AUTHENTICATION_FAILED,
                    )
            return record
        except AuthenticatedBackupError:
            raise
        except (OSError, TypeError, ValueError):
            raise AuthenticatedBackupError(
                AuthenticatedBackupErrorCode.RESTORE_FAILED,
            ) from None

    def create_export(
        self,
        request: AuthenticatedExportRequest,
        destination: str | PathLike[str],
        *,
        reservation: SnapshotSequenceReservation | None = None,
        crash_signal: BackupServiceCrashSignal | None = None,
    ) -> AuthenticatedExportResult:
        if not isinstance(request, AuthenticatedExportRequest):
            raise TypeError("Authenticated export requires an export request.")
        destination_path = _local_path(destination, "Authenticated export destination")
        self._require_destination(destination_path)
        if request.source_instance_id != self._control.installation_id:
            raise AuthenticatedBackupError(
                AuthenticatedBackupErrorCode.CONTROL_UNAVAILABLE,
            )
        if reservation is not None and (
            not isinstance(reservation, SnapshotSequenceReservation)
            or reservation.snapshot_id != request.snapshot_id
            or reservation.source_instance_id != request.source_instance_id
        ):
            raise TypeError("Authenticated export reservation is invalid.")
        stage = self._stage(destination_path, request.snapshot_id, "export")
        lease: MaintenanceLease | None = None
        published = destination_path.exists()
        stage_owned = False
        if not published:
            self._require_stage_available(stage)
        try:
            lease = self._control.begin_maintenance(request.maintenance_request())
            lease = self._control.mark_offline(lease)
            quiescence = self._control.verify_offline(lease)
            _checkpoint(
                crash_signal,
                BackupServiceCheckpoint.AFTER_MAINTENANCE_OFFLINE,
                request.snapshot_id,
            )
            durable_reservation = self._control.reserve_snapshot(
                request.source_instance_id,
                request.snapshot_id,
            )
            if reservation is not None and (
                durable_reservation.snapshot_sequence
                != reservation.snapshot_sequence
            ):
                raise AuthenticatedBackupError(
                    AuthenticatedBackupErrorCode.CONTROL_UNAVAILABLE,
                )
            reservation = durable_reservation
            _checkpoint(
                crash_signal,
                BackupServiceCheckpoint.AFTER_SEQUENCE_RESERVED,
                request.snapshot_id,
            )
            policy = SQLiteSnapshotRestorePolicy(
                request.snapshot_id,
                request.source_instance_id,
                reservation.snapshot_sequence,
            )
            if destination_path.exists():
                record, manifest = self.validate_export(destination_path, policy)
                reservation = self._control.mark_snapshot_exported(reservation)
                self._control.end_maintenance(lease)
                lease = None
                return AuthenticatedExportResult(
                    destination_path,
                    manifest,
                    record,
                    reservation,
                )
            stage.mkdir()
            stage_owned = True
            snapshot_path = stage / AUTHENTICATED_EXPORT_SNAPSHOT_DIRECTORY
            manifest = self._snapshot_manager.create_bundle(
                SQLiteOfflineSnapshotRequest(
                    request.snapshot_id,
                    request.source_instance_id,
                    reservation.snapshot_sequence,
                    quiescence,
                ),
                snapshot_path,
            )
            _checkpoint(
                crash_signal,
                BackupServiceCheckpoint.AFTER_SNAPSHOT_CREATED,
                request.snapshot_id,
            )
            self._control.verify_offline(lease)
            manifest_bytes = (
                snapshot_path / SQLITE_SNAPSHOT_MANIFEST_NAME
            ).read_bytes()
            record = self._sign_export(manifest, _sha256_bytes(manifest_bytes))
            record_path = stage / AUTHENTICATED_EXPORT_RECORD_NAME
            record_path.write_bytes(_canonical_json(record.as_dict()))
            sync_file(record_path)
            _checkpoint(
                crash_signal,
                BackupServiceCheckpoint.AFTER_EXPORT_RECORD_WRITE,
                request.snapshot_id,
            )
            self._control.verify_offline(lease)
            publish_directory(stage, destination_path)
            published = True
            _checkpoint(
                crash_signal,
                BackupServiceCheckpoint.AFTER_EXPORT_PUBLISH,
                request.snapshot_id,
            )
            reservation = self._control.mark_snapshot_exported(reservation)
            self._control.end_maintenance(lease)
            lease = None
            return AuthenticatedExportResult(
                destination_path,
                manifest,
                record,
                reservation,
            )
        except BackupServiceInterrupted:
            raise
        except BackupControlError as error:
            raise self._map_control(error) from None
        except SQLiteSnapshotError:
            raise AuthenticatedBackupError(
                AuthenticatedBackupErrorCode.SNAPSHOT_FAILED,
            ) from None
        except DurablePublicationError:
            raise AuthenticatedBackupError(
                AuthenticatedBackupErrorCode.DURABILITY_FAILED,
            ) from None
        except AuthenticatedBackupError:
            raise
        except (OSError, TypeError, ValueError):
            raise AuthenticatedBackupError(
                AuthenticatedBackupErrorCode.SNAPSHOT_FAILED,
            ) from None
        finally:
            if not published and stage_owned:
                self._cleanup_stage(stage)
            if lease is not None:
                try:
                    self._control.end_maintenance(lease)
                except BackupControlError:
                    pass

    def import_export(
        self,
        export: str | PathLike[str],
        destination: str | PathLike[str],
        request: AuthenticatedImportRequest,
        *,
        crash_signal: BackupServiceCrashSignal | None = None,
    ) -> AuthenticatedImportResult:
        if not isinstance(request, AuthenticatedImportRequest):
            raise TypeError("Authenticated import requires an import request.")
        export_path = _local_path(export, "Authenticated import source")
        destination_path = _local_path(
            destination,
            "Authenticated import destination",
        )
        self._require_destination(destination_path)
        initial_policy = SQLiteSnapshotRestorePolicy(
            request.expected_snapshot_id,
            request.expected_source_instance_id,
            request.minimum_snapshot_sequence,
        )
        export_record, manifest = self.validate_export(export_path, initial_policy)
        export_record_bytes = (
            export_path / AUTHENTICATED_EXPORT_RECORD_NAME
        ).read_bytes()
        export_record_hash = _sha256_bytes(export_record_bytes)
        stage = self._stage(destination_path, manifest.snapshot_id, "import")
        lease: MaintenanceLease | None = None
        published = destination_path.exists()
        stage_owned = False
        if not published:
            self._require_stage_available(stage)
        try:
            lease = self._control.begin_maintenance(request.maintenance_request())
            lease = self._control.mark_offline(lease)
            quiescence = self._control.verify_offline(lease)
            _checkpoint(
                crash_signal,
                BackupServiceCheckpoint.AFTER_MAINTENANCE_OFFLINE,
                manifest.snapshot_id,
            )
            export_record, revalidated = self.validate_export(
                export_path,
                initial_policy,
            )
            if revalidated != manifest:
                raise AuthenticatedBackupError(
                    AuthenticatedBackupErrorCode.AUTHENTICATION_FAILED,
                )
            floor, restore_policy = self._control.advance_restore_floor(
                manifest.source_instance_id,
                manifest.snapshot_id,
                manifest.snapshot_sequence,
                requested_minimum_sequence=request.minimum_snapshot_sequence,
            )
            _checkpoint(
                crash_signal,
                BackupServiceCheckpoint.AFTER_RESTORE_FLOOR_ADVANCE,
                manifest.snapshot_id,
            )
            if destination_path.exists():
                record = self.validate_import(
                    destination_path,
                    expected_snapshot_id=manifest.snapshot_id,
                    expected_source_instance_id=manifest.source_instance_id,
                    expected_export_record_sha256=export_record_hash,
                )
                restore_root = (
                    destination_path / AUTHENTICATED_IMPORT_RESTORE_DIRECTORY
                )
                result = SQLiteSnapshotRestoreResult(
                    manifest.snapshot_id,
                    manifest.source_instance_id,
                    manifest.snapshot_sequence,
                    restore_root / SQLITE_SNAPSHOT_STATE_NAME,
                    restore_root / SQLITE_SNAPSHOT_AUTHORITY_NAME,
                    restore_root / SQLITE_RESTORE_RECORD_NAME,
                )
                self._control.end_maintenance(lease)
                lease = None
                return AuthenticatedImportResult(
                    destination_path,
                    result,
                    record,
                    floor,
                )
            stage.mkdir()
            stage_owned = True
            restore = SQLiteOfflineSnapshotManager.restore_bundle(
                export_path / AUTHENTICATED_EXPORT_SNAPSHOT_DIRECTORY,
                stage / AUTHENTICATED_IMPORT_RESTORE_DIRECTORY,
                restore_policy,
                quiescence,
            )
            _checkpoint(
                crash_signal,
                BackupServiceCheckpoint.AFTER_PAIR_RESTORE,
                manifest.snapshot_id,
            )
            self._control.verify_offline(lease)
            files = tuple(
                AuthenticatedFileRecord(name, *_sha256_file(restore.state_database.parent / name))
                for name in (
                    SQLITE_SNAPSHOT_STATE_NAME,
                    SQLITE_SNAPSHOT_AUTHORITY_NAME,
                    SQLITE_RESTORE_RECORD_NAME,
                )
            )
            import_record = self._sign_import(
                manifest,
                floor,
                export_record_hash,
                files,
            )
            import_path = stage / AUTHENTICATED_IMPORT_RECORD_NAME
            import_path.write_bytes(_canonical_json(import_record.as_dict()))
            sync_file(import_path)
            _checkpoint(
                crash_signal,
                BackupServiceCheckpoint.AFTER_IMPORT_RECORD_WRITE,
                manifest.snapshot_id,
            )
            self._control.verify_offline(lease)
            publish_directory(stage, destination_path)
            published = True
            _checkpoint(
                crash_signal,
                BackupServiceCheckpoint.AFTER_IMPORT_PUBLISH,
                manifest.snapshot_id,
            )
            self._control.end_maintenance(lease)
            lease = None
            return AuthenticatedImportResult(
                destination_path,
                SQLiteSnapshotRestoreResult(
                    restore.snapshot_id,
                    restore.source_instance_id,
                    restore.snapshot_sequence,
                    destination_path
                    / AUTHENTICATED_IMPORT_RESTORE_DIRECTORY
                    / SQLITE_SNAPSHOT_STATE_NAME,
                    destination_path
                    / AUTHENTICATED_IMPORT_RESTORE_DIRECTORY
                    / SQLITE_SNAPSHOT_AUTHORITY_NAME,
                    destination_path
                    / AUTHENTICATED_IMPORT_RESTORE_DIRECTORY
                    / SQLITE_RESTORE_RECORD_NAME,
                ),
                import_record,
                floor,
            )
        except BackupServiceInterrupted:
            raise
        except BackupControlError as error:
            raise self._map_control(error) from None
        except SQLiteSnapshotError:
            raise AuthenticatedBackupError(
                AuthenticatedBackupErrorCode.RESTORE_FAILED,
            ) from None
        except DurablePublicationError:
            raise AuthenticatedBackupError(
                AuthenticatedBackupErrorCode.DURABILITY_FAILED,
            ) from None
        except AuthenticatedBackupError:
            raise
        except (OSError, TypeError, ValueError):
            raise AuthenticatedBackupError(
                AuthenticatedBackupErrorCode.RESTORE_FAILED,
            ) from None
        finally:
            if not published and stage_owned:
                self._cleanup_stage(stage)
            if lease is not None:
                try:
                    self._control.end_maintenance(lease)
                except BackupControlError:
                    pass


class ScheduledSQLiteBackupRunner:
    """Single-tick runner; a local server owns wake-up and repeated invocation."""

    def __init__(
        self,
        service: AuthenticatedSQLiteBackupService,
        control: SQLiteBackupControlStore,
        destination_root: str | PathLike[str],
    ) -> None:
        if not isinstance(service, AuthenticatedSQLiteBackupService):
            raise TypeError("Scheduled runner requires backup service.")
        if not isinstance(control, SQLiteBackupControlStore):
            raise TypeError("Scheduled runner requires backup control store.")
        root = _local_path(destination_root, "Scheduled backup destination root")
        if not root.is_dir() or is_link_like(root):
            raise TypeError("Scheduled backup destination root must exist.")
        self._service = service
        self._control = control
        self._root = root

    @staticmethod
    def _derived(snapshot_id: str, label: str) -> str:
        return str(uuid5(UUID(snapshot_id), label))

    def run_due(
        self,
        schedule_id: str,
        owner_id: str,
        *,
        lease_duration_ms: int,
        crash_signal: BackupServiceCrashSignal | None = None,
    ) -> ScheduledBackupResult:
        claim: BackupScheduleClaim | None = None
        try:
            claim = self._control.claim_due_schedule(
                schedule_id,
                owner_id,
                lease_duration_ms=lease_duration_ms,
            )
            reservation = claim.reservation
            destination = self._root / (
                f"backup-{reservation.snapshot_sequence:020d}"
            )
            export = self._service.create_export(
                AuthenticatedExportRequest(
                    reservation.snapshot_id,
                    reservation.source_instance_id,
                    self._derived(reservation.snapshot_id, "scheduled-maintenance"),
                    owner_id,
                    self._derived(reservation.snapshot_id, "scheduled-quiescence"),
                    lease_duration_ms,
                ),
                destination,
                reservation=reservation,
                crash_signal=crash_signal,
            )
            schedule = self._control.complete_schedule(claim)
            claim = None
            return ScheduledBackupResult(export, schedule)
        finally:
            if claim is not None:
                try:
                    self._control.release_schedule_claim(claim)
                except BackupControlError:
                    pass
