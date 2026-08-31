"""OS-credential-backed monotonic restore floor outside SQLite backups."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
import threading
from uuid import UUID

from .credentials import (
    CredentialStore,
    CredentialStoreError,
    CredentialStoreErrorCode,
)


NATIVE_ANTI_ROLLBACK_FLOOR_PRODUCT_ENABLED = True


class AntiRollbackErrorCode(StrEnum):
    ROLLBACK_REJECTED = "native-rollback-rejected"
    FLOOR_CONFLICT = "native-floor-conflict"
    FLOOR_UNAVAILABLE = "native-floor-unavailable"


class AntiRollbackError(Exception):
    def __init__(self, code: AntiRollbackErrorCode) -> None:
        if not isinstance(code, AntiRollbackErrorCode):
            raise TypeError("AntiRollbackError requires a stable code.")
        self.code = code
        super().__init__(code.value)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code.value}


@dataclass(frozen=True, slots=True)
class NativeRestoreFloor:
    source_instance_id: str
    minimum_snapshot_sequence: int
    snapshot_id: str

    def __post_init__(self) -> None:
        for value in (self.source_instance_id, self.snapshot_id):
            try:
                parsed = UUID(value)
            except (AttributeError, TypeError, ValueError) as error:
                raise TypeError("Native floor IDs must be UUIDs.") from error
            if str(parsed) != value:
                raise TypeError("Native floor IDs must be canonical UUIDs.")
        if (
            not isinstance(self.minimum_snapshot_sequence, int)
            or isinstance(self.minimum_snapshot_sequence, bool)
            or self.minimum_snapshot_sequence < 1
            or self.minimum_snapshot_sequence > (1 << 63) - 1
        ):
            raise TypeError("Native floor sequence is invalid.")

    def as_dict(self) -> dict[str, str | int]:
        return {
            "schemaVersion": 1,
            "sourceInstanceId": self.source_instance_id,
            "minimumSnapshotSequence": self.minimum_snapshot_sequence,
            "snapshotId": self.snapshot_id,
        }


class NativeRestoreFloorStore:
    """Single-local-service monotonic floor persisted by the host credential API."""

    def __init__(
        self,
        credentials: CredentialStore,
        *,
        service: str = "opentcad",
    ) -> None:
        if not isinstance(credentials, CredentialStore):
            raise TypeError("Native floor store requires CredentialStore.")
        self._credentials = credentials
        self._service = service
        self._lock = threading.Lock()

    @staticmethod
    def _credential_id(source_instance_id: str) -> str:
        try:
            parsed = UUID(source_instance_id)
        except (AttributeError, TypeError, ValueError) as error:
            raise TypeError("Native floor source ID must be UUID.") from error
        if str(parsed) != source_instance_id:
            raise TypeError("Native floor source ID must be canonical UUID.")
        return f"restore-floor.{source_instance_id}"

    @staticmethod
    def _decode(raw: bytes) -> NativeRestoreFloor:
        try:
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict) or set(value) != {
                "schemaVersion",
                "sourceInstanceId",
                "minimumSnapshotSequence",
                "snapshotId",
            } or value["schemaVersion"] != 1:
                raise ValueError
            return NativeRestoreFloor(
                value["sourceInstanceId"],
                value["minimumSnapshotSequence"],
                value["snapshotId"],
            )
        except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            raise AntiRollbackError(AntiRollbackErrorCode.FLOOR_UNAVAILABLE) from None

    def current(self, source_instance_id: str) -> NativeRestoreFloor | None:
        credential_id = self._credential_id(source_instance_id)
        try:
            return self._decode(
                self._credentials.get(self._service, credential_id),
            )
        except CredentialStoreError as error:
            if error.code is CredentialStoreErrorCode.NOT_FOUND:
                return None
            raise AntiRollbackError(AntiRollbackErrorCode.FLOOR_UNAVAILABLE) from None

    def advance(
        self,
        source_instance_id: str,
        snapshot_id: str,
        snapshot_sequence: int,
        *,
        requested_minimum_sequence: int,
    ) -> NativeRestoreFloor:
        candidate = NativeRestoreFloor(
            source_instance_id,
            snapshot_sequence,
            snapshot_id,
        )
        if (
            not isinstance(requested_minimum_sequence, int)
            or isinstance(requested_minimum_sequence, bool)
            or requested_minimum_sequence < 1
        ):
            raise TypeError("Requested native floor is invalid.")
        with self._lock:
            current = self.current(source_instance_id)
            required = max(
                requested_minimum_sequence,
                current.minimum_snapshot_sequence if current is not None else 1,
            )
            if snapshot_sequence < required:
                raise AntiRollbackError(
                    AntiRollbackErrorCode.ROLLBACK_REJECTED,
                )
            if (
                current is not None
                and snapshot_sequence == current.minimum_snapshot_sequence
                and snapshot_id != current.snapshot_id
            ):
                raise AntiRollbackError(AntiRollbackErrorCode.FLOOR_CONFLICT)
            if current is not None and snapshot_sequence == current.minimum_snapshot_sequence:
                return current
            raw = json.dumps(
                candidate.as_dict(),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            try:
                self._credentials.set(
                    self._service,
                    self._credential_id(source_instance_id),
                    raw,
                )
            except CredentialStoreError:
                raise AntiRollbackError(
                    AntiRollbackErrorCode.FLOOR_UNAVAILABLE,
                ) from None
            recovered = self.current(source_instance_id)
            if recovered != candidate:
                raise AntiRollbackError(
                    AntiRollbackErrorCode.FLOOR_UNAVAILABLE,
                )
            return recovered
