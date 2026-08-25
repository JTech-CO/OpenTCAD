"""Subprocess helper that hard-exits at SQLite snapshot publication seams."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from backend.app.broker.sqlite_snapshot import (
    SQLiteOfflineSnapshotManager,
    SQLiteOfflineSnapshotRequest,
    SQLiteSnapshotCheckpoint,
    SQLiteSnapshotQuiescence,
    SQLiteSnapshotRestorePolicy,
)


HARD_EXIT_CODE = 93


class HardExitAtCheckpoint:
    def __init__(self, checkpoint: SQLiteSnapshotCheckpoint) -> None:
        self._checkpoint = checkpoint

    def requested(
        self,
        checkpoint: SQLiteSnapshotCheckpoint,
        snapshot_id: str,
    ) -> bool:
        if checkpoint is self._checkpoint:
            os._exit(HARD_EXIT_CODE)
        return False


def _quiescence(value: str) -> SQLiteSnapshotQuiescence:
    return SQLiteSnapshotQuiescence(value, True, True, True)


def _create(arguments: list[str]) -> None:
    if len(arguments) != 8:
        raise ValueError("create helper argument count")
    state, authority, destination, snapshot_id, instance_id, sequence, token, seam = (
        arguments
    )
    SQLiteOfflineSnapshotManager(state, authority).create_bundle(
        SQLiteOfflineSnapshotRequest(
            snapshot_id,
            instance_id,
            int(sequence),
            _quiescence(token),
        ),
        destination,
        HardExitAtCheckpoint(SQLiteSnapshotCheckpoint(seam)),
    )


def _restore(arguments: list[str]) -> None:
    if len(arguments) != 7:
        raise ValueError("restore helper argument count")
    bundle, destination, snapshot_id, instance_id, sequence, token, seam = arguments
    SQLiteOfflineSnapshotManager.restore_bundle(
        bundle,
        destination,
        SQLiteSnapshotRestorePolicy(snapshot_id, instance_id, int(sequence)),
        _quiescence(token),
        HardExitAtCheckpoint(SQLiteSnapshotCheckpoint(seam)),
    )


def main() -> int:
    if len(sys.argv) < 2:
        return 64
    try:
        if sys.argv[1] == "create":
            _create(sys.argv[2:])
        elif sys.argv[1] == "restore":
            _restore(sys.argv[2:])
        else:
            return 64
    except (TypeError, ValueError):
        return 65
    return 70


if __name__ == "__main__":
    raise SystemExit(main())
