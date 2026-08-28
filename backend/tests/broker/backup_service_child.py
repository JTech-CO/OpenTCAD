"""Subprocess helper that hard-exits at authenticated backup service seams."""

from __future__ import annotations

import os
import sys

from backend.app.broker.backup_control import SQLiteBackupControlStore
from backend.app.broker.backup_service import (
    AuthenticatedExportRequest,
    AuthenticatedImportRequest,
    AuthenticatedSQLiteBackupService,
    BackupServiceCheckpoint,
    HMACBackupKeyring,
)
from backend.app.broker.sqlite_snapshot import SQLiteOfflineSnapshotManager


HARD_EXIT_CODE = 94
TEST_KEY_ID = "test-primary"
TEST_KEY = b"OpenTCAD-test-authentication-key-0001"


class HardExitAtCheckpoint:
    def __init__(self, checkpoint: BackupServiceCheckpoint) -> None:
        self._checkpoint = checkpoint

    def requested(
        self,
        checkpoint: BackupServiceCheckpoint,
        snapshot_id: str,
    ) -> bool:
        if checkpoint is self._checkpoint:
            os._exit(HARD_EXIT_CODE)
        return False


def _service(state: str, authority: str, control: str, instance: str):
    store = SQLiteBackupControlStore(control, instance)
    return AuthenticatedSQLiteBackupService(
        SQLiteOfflineSnapshotManager(state, authority),
        store,
        HMACBackupKeyring(TEST_KEY_ID, {TEST_KEY_ID: TEST_KEY}),
    )


def _export(arguments: list[str]) -> None:
    if len(arguments) != 10:
        raise ValueError("export helper argument count")
    (
        state,
        authority,
        control,
        destination,
        snapshot,
        instance,
        maintenance,
        owner,
        quiescence,
        seam,
    ) = arguments
    _service(state, authority, control, instance).create_export(
        AuthenticatedExportRequest(
            snapshot,
            instance,
            maintenance,
            owner,
            quiescence,
            60_000,
        ),
        destination,
        crash_signal=HardExitAtCheckpoint(BackupServiceCheckpoint(seam)),
    )


def _import(arguments: list[str]) -> None:
    if len(arguments) != 12:
        raise ValueError("import helper argument count")
    (
        state,
        authority,
        control,
        export,
        destination,
        snapshot,
        instance,
        maintenance,
        owner,
        quiescence,
        minimum,
        seam,
    ) = arguments
    _service(state, authority, control, instance).import_export(
        export,
        destination,
        AuthenticatedImportRequest(
            snapshot,
            instance,
            int(minimum),
            maintenance,
            owner,
            quiescence,
            60_000,
        ),
        crash_signal=HardExitAtCheckpoint(BackupServiceCheckpoint(seam)),
    )


def main() -> int:
    if len(sys.argv) < 2:
        return 64
    try:
        if sys.argv[1] == "export":
            _export(sys.argv[2:])
        elif sys.argv[1] == "import":
            _import(sys.argv[2:])
        else:
            return 64
    except (TypeError, ValueError):
        return 65
    return 70


if __name__ == "__main__":
    raise SystemExit(main())
