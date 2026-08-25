"""Subprocess helper that hard-exits after a committed recovery claim."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys

from backend.app.broker import (
    CrashRecoveryCoordinator,
    OwnerLeasePolicy,
    RecoveryCheckpoint,
    RecoveryRequest,
    ReconciliationReport,
    SQLiteJobStateStore,
)
from backend.app.runtime.models import JobIdentity, RuntimeKind


HARD_EXIT_CODE = 91


class UnreachableReconciler:
    async def reconcile(
        self,
        job_id: str | None = None,
        *,
        ownership_guard=None,
    ) -> ReconciliationReport:
        raise AssertionError("hard exit must happen before reconciliation")


class HardExitAfterClaim:
    def __init__(self, identity: JobIdentity) -> None:
        self._identity = identity

    def requested(
        self,
        checkpoint: RecoveryCheckpoint,
        identity: JobIdentity,
    ) -> bool:
        if (
            checkpoint is RecoveryCheckpoint.AFTER_CLAIM
            and identity == self._identity
        ):
            os._exit(HARD_EXIT_CODE)
        return False


async def _run(database: Path, recovery_id: str, job_id: str) -> None:
    identity = JobIdentity(job_id)
    coordinator = CrashRecoveryCoordinator(
        SQLiteJobStateStore(database),
        UnreachableReconciler(),
        RuntimeKind.MOCK,
        OwnerLeasePolicy(duration_ms=2, heartbeat_interval_ms=1),
    )
    await coordinator.recover(
        RecoveryRequest(recovery_id, limit=1),
        HardExitAfterClaim(identity),
    )
    raise AssertionError("hard-exit checkpoint was not reached")


def main() -> int:
    if len(sys.argv) != 4:
        return 64
    asyncio.run(_run(Path(sys.argv[1]), sys.argv[2], sys.argv[3]))
    return 70


if __name__ == "__main__":
    raise SystemExit(main())
