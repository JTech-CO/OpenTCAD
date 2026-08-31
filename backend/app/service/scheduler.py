"""Restart-safe wake-up loop for durable scheduled backup claims."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from uuid import UUID, uuid5

from backend.app.broker.backup_control import (
    BackupControlError,
    BackupControlErrorCode,
)
from backend.app.broker.backup_service import (
    AuthenticatedBackupError,
    AuthenticatedBackupErrorCode,
    ScheduledSQLiteBackupRunner,
)


SCHEDULED_BACKUP_AUTOMATION_PRODUCT_ENABLED = True
SchedulerFailureCode = BackupControlErrorCode | AuthenticatedBackupErrorCode
SchedulerErrorSink = Callable[
    [str, BackupControlError | AuthenticatedBackupError],
    None,
]


@dataclass(frozen=True, slots=True)
class ScheduledBackupLoopConfiguration:
    schedule_ids: tuple[str, ...]
    installation_id: str
    poll_interval_ms: int = 10_000
    claim_lease_ms: int = 300_000

    def __post_init__(self) -> None:
        try:
            installation = UUID(self.installation_id)
        except (AttributeError, TypeError, ValueError) as error:
            raise TypeError("Scheduler installation ID must be UUID.") from error
        if str(installation) != self.installation_id:
            raise TypeError("Scheduler installation ID must be canonical UUID.")
        identifiers = tuple(self.schedule_ids)
        if not identifiers:
            raise TypeError("Scheduler requires at least one schedule.")
        for value in identifiers:
            try:
                parsed = UUID(value)
            except (AttributeError, TypeError, ValueError) as error:
                raise TypeError("Schedule ID must be UUID.") from error
            if str(parsed) != value:
                raise TypeError("Schedule ID must be canonical UUID.")
        if len(set(identifiers)) != len(identifiers):
            raise TypeError("Schedule IDs must be unique.")
        if (
            not isinstance(self.poll_interval_ms, int)
            or isinstance(self.poll_interval_ms, bool)
            or not 100 <= self.poll_interval_ms <= 60_000
            or not isinstance(self.claim_lease_ms, int)
            or isinstance(self.claim_lease_ms, bool)
            or not 1_000 <= self.claim_lease_ms <= 86_400_000
        ):
            raise TypeError("Scheduled backup loop timing is invalid.")
        object.__setattr__(self, "schedule_ids", identifiers)

    @property
    def owner_id(self) -> str:
        return str(uuid5(UUID(self.installation_id), "scheduled-backup-owner"))


class ScheduledBackupLoop:
    """Repeatedly claims due occurrences; durable control handles restart replay."""

    _EXPECTED_IDLE_CODES = {
        BackupControlErrorCode.SCHEDULE_NOT_DUE,
        BackupControlErrorCode.SCHEDULE_LEASED,
        BackupControlErrorCode.SCHEDULE_BUSY,
    }

    def __init__(
        self,
        runner: ScheduledSQLiteBackupRunner,
        configuration: ScheduledBackupLoopConfiguration,
        *,
        error_sink: SchedulerErrorSink | None = None,
    ) -> None:
        if not isinstance(runner, ScheduledSQLiteBackupRunner):
            raise TypeError("Scheduled loop requires ScheduledSQLiteBackupRunner.")
        if not isinstance(configuration, ScheduledBackupLoopConfiguration):
            raise TypeError("Scheduled loop requires configuration.")
        if error_sink is not None and not callable(error_sink):
            raise TypeError("Scheduler error sink must be callable.")
        self._runner = runner
        self._configuration = configuration
        self._error_sink = error_sink
        self._failures: dict[str, SchedulerFailureCode] = {}
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def failures(self) -> dict[str, SchedulerFailureCode]:
        return dict(self._failures)

    def _record_failure(
        self,
        schedule_id: str,
        error: BackupControlError | AuthenticatedBackupError,
    ) -> None:
        self._failures[schedule_id] = error.code
        if self._error_sink:
            try:
                self._error_sink(schedule_id, error)
            except Exception:
                pass

    async def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._task = asyncio.create_task(
            self._run(),
            name="opentcad-scheduled-backups",
        )

    async def run_once(self) -> int:
        completed = 0
        for schedule_id in self._configuration.schedule_ids:
            try:
                await asyncio.to_thread(
                    self._runner.run_due,
                    schedule_id,
                    self._configuration.owner_id,
                    lease_duration_ms=self._configuration.claim_lease_ms,
                )
                self._failures.pop(schedule_id, None)
                completed += 1
            except BackupControlError as error:
                if error.code in self._EXPECTED_IDLE_CODES:
                    self._failures.pop(schedule_id, None)
                else:
                    self._record_failure(schedule_id, error)
            except AuthenticatedBackupError as error:
                self._record_failure(schedule_id, error)
        return completed

    async def _run(self) -> None:
        while not self._stop.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._configuration.poll_interval_ms / 1_000,
                )
            except TimeoutError:
                continue

    async def close(self) -> None:
        self._stop.set()
        task = self._task
        if task is not None:
            await task
        self._task = None
