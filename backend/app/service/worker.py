"""Single-owner local worker transport for every durable lifecycle operation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import re
from typing import Any
from uuid import UUID

from backend.app.broker.backup_control import (
    BackupControlError,
    MaintenanceLease,
    MaintenanceRequest,
    OperationAdmission,
    SQLiteBackupControlStore,
)
from backend.app.broker.backup_service import (
    AuthenticatedExportRequest,
    AuthenticatedImportRequest,
    AuthenticatedSQLiteBackupService,
    ScheduledSQLiteBackupRunner,
)
from backend.app.broker.cancellation import CancellationRequest
from backend.app.broker.lifecycle import LifecycleCheckpoint
from backend.app.broker.models import BrokerRequest
from backend.app.broker.state_composition import (
    BrokerStartupRequest,
    DurableBrokerComposition,
    StateOperationContext,
)
from backend.app.broker.sqlite_snapshot import SQLiteSnapshotRestorePolicy
from backend.app.runtime.models import JobIdentity

from .anti_rollback import NativeRestoreFloorStore


LOCAL_WORKER_TRANSPORT_PRODUCT_ENABLED = True
_HASH = re.compile(r"^[0-9a-f]{64}$")
_CANCELLATION_ADMISSION_LEASE_MS = 60_000


class WorkerOperation(StrEnum):
    STARTUP_RECOVERY = "startup-recovery"
    EXECUTE = "execute"
    CANCEL = "cancel"
    MAINTENANCE_BEGIN = "maintenance-begin"
    MAINTENANCE_OFFLINE = "maintenance-offline"
    MAINTENANCE_END = "maintenance-end"
    BACKUP_EXPORT = "backup-export"
    BACKUP_IMPORT = "backup-import"
    BACKUP_SCHEDULE_RUN = "backup-schedule-run"


class WorkerErrorCode(StrEnum):
    NOT_STARTED = "worker-not-started"
    CLOSED = "worker-closed"
    REQUEST_CONFLICT = "worker-request-conflict"
    CAPACITY_REACHED = "worker-capacity-reached"
    INVALID_REQUEST = "worker-invalid-request"


class WorkerError(Exception):
    def __init__(self, code: WorkerErrorCode) -> None:
        if not isinstance(code, WorkerErrorCode):
            raise TypeError("WorkerError requires WorkerErrorCode.")
        self.code = code
        super().__init__(code.value)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code.value}


@dataclass(frozen=True, slots=True)
class ExecuteWork:
    request: BrokerRequest
    context: StateOperationContext
    owner_id: str
    admission_lease_ms: int

    def __post_init__(self) -> None:
        if not isinstance(self.request, BrokerRequest):
            raise TypeError("Execute work requires BrokerRequest.")
        if not isinstance(self.context, StateOperationContext):
            raise TypeError("Execute work requires StateOperationContext.")
        _uuid(self.owner_id)
        _lease(self.admission_lease_ms)


@dataclass(frozen=True, slots=True)
class CancelWork:
    request: CancellationRequest
    context: StateOperationContext

    def __post_init__(self) -> None:
        if not isinstance(self.request, CancellationRequest):
            raise TypeError("Cancel work requires CancellationRequest.")
        if not isinstance(self.context, StateOperationContext):
            raise TypeError("Cancel work requires StateOperationContext.")


@dataclass(frozen=True, slots=True)
class BackupExportWork:
    request: AuthenticatedExportRequest
    destination: Path

    def __post_init__(self) -> None:
        if not isinstance(self.request, AuthenticatedExportRequest):
            raise TypeError("Backup export work requires an authenticated request.")
        if not isinstance(self.destination, Path):
            raise TypeError("Backup export destination must be Path.")


@dataclass(frozen=True, slots=True)
class BackupImportWork:
    request: AuthenticatedImportRequest
    source: Path
    destination: Path

    def __post_init__(self) -> None:
        if not isinstance(self.request, AuthenticatedImportRequest):
            raise TypeError("Backup import work requires an authenticated request.")
        if not isinstance(self.source, Path) or not isinstance(self.destination, Path):
            raise TypeError("Backup import paths must be Path.")


@dataclass(frozen=True, slots=True)
class ScheduledBackupWork:
    schedule_id: str
    owner_id: str
    lease_duration_ms: int

    def __post_init__(self) -> None:
        _uuid(self.schedule_id)
        _uuid(self.owner_id)
        _lease(self.lease_duration_ms)


@dataclass(frozen=True, slots=True)
class WorkerEnvelope:
    request_id: str
    request_hash: str
    operation: WorkerOperation
    payload: object

    def __post_init__(self) -> None:
        _uuid(self.request_id)
        if not isinstance(self.request_hash, str) or _HASH.fullmatch(self.request_hash) is None:
            raise TypeError("Worker request hash must be lowercase SHA-256.")
        if not isinstance(self.operation, WorkerOperation):
            raise TypeError("Worker operation is invalid.")


@dataclass(frozen=True, slots=True)
class _AdmissionCancellationSignal:
    identity: JobIdentity
    lost: asyncio.Event

    def requested(self, checkpoint: LifecycleCheckpoint) -> bool:
        if not isinstance(checkpoint, LifecycleCheckpoint):
            raise TypeError("Cancellation checkpoint must be LifecycleCheckpoint.")
        return self.lost.is_set()


def _uuid(value: str) -> None:
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise TypeError("Canonical UUID required.") from error
    if str(parsed) != value:
        raise TypeError("Canonical UUID required.")


def _lease(value: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
        or value > 86_400_000
    ):
        raise TypeError("Lease must be 1 to 86400000 ms.")


class LocalLifecycleCoordinator:
    """Connects execution, cancellation, recovery, maintenance, and backup."""

    def __init__(
        self,
        composition: DurableBrokerComposition,
        control: SQLiteBackupControlStore,
        backup_service: AuthenticatedSQLiteBackupService,
        scheduled_backups: ScheduledSQLiteBackupRunner,
        anti_rollback: NativeRestoreFloorStore,
    ) -> None:
        if not isinstance(composition, DurableBrokerComposition):
            raise TypeError("Lifecycle coordinator requires durable composition.")
        if not isinstance(control, SQLiteBackupControlStore):
            raise TypeError("Lifecycle coordinator requires backup control.")
        if not isinstance(backup_service, AuthenticatedSQLiteBackupService):
            raise TypeError("Lifecycle coordinator requires backup service.")
        if not isinstance(scheduled_backups, ScheduledSQLiteBackupRunner):
            raise TypeError("Lifecycle coordinator requires scheduled backup runner.")
        if not isinstance(anti_rollback, NativeRestoreFloorStore):
            raise TypeError("Lifecycle coordinator requires native restore floor.")
        self._composition = composition
        self._control = control
        self._backup_service = backup_service
        self._scheduled_backups = scheduled_backups
        self._anti_rollback = anti_rollback

    async def _renew_admission(
        self,
        admission: OperationAdmission,
        lease_duration_ms: int,
        lost: asyncio.Event,
        failures: list[Exception],
    ) -> None:
        current = admission
        interval = max(0.01, min(30.0, lease_duration_ms / 3_000))
        while True:
            await asyncio.sleep(interval)
            try:
                current = await asyncio.to_thread(
                    self._control.renew_operation,
                    current,
                    lease_duration_ms=lease_duration_ms,
                )
            except Exception as error:
                failures.append(error)
                lost.set()
                return

    async def _execute(self, payload: ExecuteWork) -> object:
        admission = await asyncio.to_thread(
            self._control.admit_operation,
            payload.context.operation_id,
            payload.owner_id,
            lease_duration_ms=payload.admission_lease_ms,
        )
        lost = asyncio.Event()
        failures: list[Exception] = []
        heartbeat = asyncio.create_task(
            self._renew_admission(
                admission,
                payload.admission_lease_ms,
                lost,
                failures,
            ),
            name="opentcad-operation-admission-heartbeat",
        )
        try:
            result = await self._composition.execute(
                payload.request,
                payload.context,
                _AdmissionCancellationSignal(
                    JobIdentity(payload.request.spec.job_id),
                    lost,
                ),
            )
            if failures:
                raise failures[0]
            return result
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
            await asyncio.to_thread(
                self._control.release_operation,
                admission,
            )

    async def _import(self, payload: BackupImportWork) -> object:
        policy = SQLiteSnapshotRestorePolicy(
            payload.request.expected_snapshot_id,
            payload.request.expected_source_instance_id,
            payload.request.minimum_snapshot_sequence,
        )
        _, manifest = await asyncio.to_thread(
            self._backup_service.validate_export,
            payload.source,
            policy,
        )
        lease: MaintenanceLease | None = None
        try:
            lease = await asyncio.to_thread(
                self._control.begin_maintenance,
                payload.request.maintenance_request(),
            )
            lease = await asyncio.to_thread(
                self._control.mark_offline,
                lease,
            )
            await asyncio.to_thread(
                self._anti_rollback.advance,
                manifest.source_instance_id,
                manifest.snapshot_id,
                manifest.snapshot_sequence,
                requested_minimum_sequence=(
                    payload.request.minimum_snapshot_sequence
                ),
            )
            return await asyncio.to_thread(
                self._backup_service.import_export,
                payload.source,
                payload.destination,
                payload.request,
            )
        finally:
            if lease is not None:
                try:
                    await asyncio.to_thread(
                        self._control.end_maintenance,
                        lease,
                    )
                except BackupControlError:
                    pass

    async def _cancel(self, payload: CancelWork) -> object:
        """Keep cancellation inside the same maintenance quiescence boundary."""

        owner_id = payload.request.identity.job_id
        admission = await asyncio.to_thread(
            self._control.admit_operation,
            payload.context.operation_id,
            owner_id,
            lease_duration_ms=_CANCELLATION_ADMISSION_LEASE_MS,
        )
        lost = asyncio.Event()
        failures: list[Exception] = []
        heartbeat = asyncio.create_task(
            self._renew_admission(
                admission,
                _CANCELLATION_ADMISSION_LEASE_MS,
                lost,
                failures,
            ),
            name="opentcad-cancellation-admission-heartbeat",
        )
        operation = asyncio.create_task(
            self._composition.cancel(
                payload.request,
                payload.context,
            ),
            name="opentcad-durable-cancellation",
        )
        admission_lost = asyncio.create_task(
            lost.wait(),
            name="opentcad-cancellation-admission-loss",
        )
        try:
            completed, _ = await asyncio.wait(
                (operation, admission_lost),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if admission_lost in completed and not operation.done():
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)
                if failures:
                    raise failures[0]
                raise WorkerError(WorkerErrorCode.CLOSED)
            result = await operation
            if failures:
                raise failures[0]
            return result
        finally:
            admission_lost.cancel()
            if not operation.done():
                operation.cancel()
            await asyncio.gather(
                admission_lost,
                operation,
                return_exceptions=True,
            )
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
            try:
                await asyncio.to_thread(
                    self._control.release_operation,
                    admission,
                )
            except Exception:
                if not failures:
                    raise

    async def dispatch(self, operation: WorkerOperation, payload: object) -> object:
        if operation is WorkerOperation.STARTUP_RECOVERY:
            if not isinstance(payload, BrokerStartupRequest):
                raise WorkerError(WorkerErrorCode.INVALID_REQUEST)
            return await self._composition.startup(payload)
        if operation is WorkerOperation.EXECUTE:
            if not isinstance(payload, ExecuteWork):
                raise WorkerError(WorkerErrorCode.INVALID_REQUEST)
            return await self._execute(payload)
        if operation is WorkerOperation.CANCEL:
            if not isinstance(payload, CancelWork):
                raise WorkerError(WorkerErrorCode.INVALID_REQUEST)
            return await self._cancel(payload)
        if operation is WorkerOperation.MAINTENANCE_BEGIN:
            if not isinstance(payload, MaintenanceRequest):
                raise WorkerError(WorkerErrorCode.INVALID_REQUEST)
            return await asyncio.to_thread(
                self._control.begin_maintenance,
                payload,
            )
        if operation is WorkerOperation.MAINTENANCE_OFFLINE:
            if not isinstance(payload, MaintenanceLease):
                raise WorkerError(WorkerErrorCode.INVALID_REQUEST)
            return await asyncio.to_thread(
                self._control.mark_offline,
                payload,
            )
        if operation is WorkerOperation.MAINTENANCE_END:
            if not isinstance(payload, MaintenanceLease):
                raise WorkerError(WorkerErrorCode.INVALID_REQUEST)
            await asyncio.to_thread(self._control.end_maintenance, payload)
            return None
        if operation is WorkerOperation.BACKUP_EXPORT:
            if not isinstance(payload, BackupExportWork):
                raise WorkerError(WorkerErrorCode.INVALID_REQUEST)
            return await asyncio.to_thread(
                self._backup_service.create_export,
                payload.request,
                payload.destination,
            )
        if operation is WorkerOperation.BACKUP_IMPORT:
            if not isinstance(payload, BackupImportWork):
                raise WorkerError(WorkerErrorCode.INVALID_REQUEST)
            return await self._import(payload)
        if operation is WorkerOperation.BACKUP_SCHEDULE_RUN:
            if not isinstance(payload, ScheduledBackupWork):
                raise WorkerError(WorkerErrorCode.INVALID_REQUEST)
            return await asyncio.to_thread(
                self._scheduled_backups.run_due,
                payload.schedule_id,
                payload.owner_id,
                lease_duration_ms=payload.lease_duration_ms,
            )
        raise WorkerError(WorkerErrorCode.INVALID_REQUEST)


@dataclass(slots=True)
class _QueuedWork:
    envelope: WorkerEnvelope
    future: asyncio.Future[object]


class LocalBrokerWorker:
    """Bounded transport with concurrent execution and a reserved control lane."""

    def __init__(
        self,
        coordinator: LocalLifecycleCoordinator,
        *,
        queue_capacity: int = 128,
        control_capacity: int = 16,
        result_capacity: int = 1_024,
        execution_concurrency: int = 4,
    ) -> None:
        if not isinstance(coordinator, LocalLifecycleCoordinator):
            raise TypeError("Local worker requires LocalLifecycleCoordinator.")
        if (
            not isinstance(queue_capacity, int)
            or isinstance(queue_capacity, bool)
            or not 1 <= queue_capacity <= 4_096
            or not isinstance(control_capacity, int)
            or isinstance(control_capacity, bool)
            or not 1 <= control_capacity <= 256
            or not isinstance(result_capacity, int)
            or isinstance(result_capacity, bool)
            or not 1 <= result_capacity <= 65_536
            or not isinstance(execution_concurrency, int)
            or isinstance(execution_concurrency, bool)
            or not 1 <= execution_concurrency <= 64
        ):
            raise TypeError("Local worker capacities are invalid.")
        self._coordinator = coordinator
        self._queue_capacity = queue_capacity
        self._control_capacity = control_capacity
        self._queue: asyncio.Queue[_QueuedWork | None] = asyncio.Queue(
            queue_capacity + control_capacity,
        )
        self._result_capacity = result_capacity
        self._completed: dict[str, tuple[str, object]] = {}
        self._order: list[str] = []
        self._inflight: dict[
            str,
            tuple[str, asyncio.Future[object], bool],
        ] = {}
        self._execution_gate = asyncio.Semaphore(execution_concurrency)
        self._control_gate = asyncio.Semaphore(1)
        self._active: set[asyncio.Task[None]] = set()
        self._task: asyncio.Task[None] | None = None
        self._closed = False
        self._lock = asyncio.Lock()

    @property
    def started(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        async with self._lock:
            if self._closed:
                raise WorkerError(WorkerErrorCode.CLOSED)
            if self._task is None:
                self._task = asyncio.create_task(
                    self._run(),
                    name="opentcad-local-broker-worker",
                )

    async def submit(self, envelope: WorkerEnvelope) -> object:
        if not isinstance(envelope, WorkerEnvelope):
            raise WorkerError(WorkerErrorCode.INVALID_REQUEST)
        async with self._lock:
            if self._closed:
                raise WorkerError(WorkerErrorCode.CLOSED)
            if not self.started:
                raise WorkerError(WorkerErrorCode.NOT_STARTED)
            completed = self._completed.get(envelope.request_id)
            if completed is not None:
                if completed[0] != envelope.request_hash:
                    raise WorkerError(WorkerErrorCode.REQUEST_CONFLICT)
                return completed[1]
            inflight = self._inflight.get(envelope.request_id)
            if inflight is not None:
                if inflight[0] != envelope.request_hash:
                    raise WorkerError(WorkerErrorCode.REQUEST_CONFLICT)
                future = inflight[1]
            else:
                control = self._control_operation(envelope.operation)
                active_same_class = sum(
                    1
                    for _, _, candidate_control in self._inflight.values()
                    if candidate_control is control
                )
                capacity = (
                    self._control_capacity
                    if control
                    else self._queue_capacity
                )
                if active_same_class >= capacity:
                    raise WorkerError(WorkerErrorCode.CAPACITY_REACHED)
                future = asyncio.get_running_loop().create_future()
                self._inflight[envelope.request_id] = (
                    envelope.request_hash,
                    future,
                    control,
                )
                await self._queue.put(_QueuedWork(envelope, future))
        return await asyncio.shield(future)

    @staticmethod
    def _control_operation(operation: WorkerOperation) -> bool:
        return operation in {
            WorkerOperation.STARTUP_RECOVERY,
            WorkerOperation.CANCEL,
            WorkerOperation.MAINTENANCE_BEGIN,
            WorkerOperation.MAINTENANCE_OFFLINE,
            WorkerOperation.MAINTENANCE_END,
        }

    async def _process(self, queued: _QueuedWork) -> None:
        envelope = queued.envelope
        gate = (
            self._control_gate
            if self._control_operation(envelope.operation)
            else self._execution_gate
        )
        try:
            async with gate:
                try:
                    result = await self._coordinator.dispatch(
                        envelope.operation,
                        envelope.payload,
                    )
                except Exception as error:
                    if not queued.future.done():
                        queued.future.set_exception(error)
                else:
                    async with self._lock:
                        self._completed[envelope.request_id] = (
                            envelope.request_hash,
                            result,
                        )
                        self._order.append(envelope.request_id)
                        while len(self._order) > self._result_capacity:
                            expired = self._order.pop(0)
                            self._completed.pop(expired, None)
                    if not queued.future.done():
                        queued.future.set_result(result)
                finally:
                    async with self._lock:
                        self._inflight.pop(envelope.request_id, None)
        finally:
            self._queue.task_done()

    async def _run(self) -> None:
        while True:
            queued = await self._queue.get()
            if queued is None:
                self._queue.task_done()
                if self._active:
                    await asyncio.gather(*tuple(self._active))
                return
            task = asyncio.create_task(
                self._process(queued),
                name=f"opentcad-worker-{queued.envelope.operation.value}",
            )
            self._active.add(task)
            task.add_done_callback(self._active.discard)

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                task = self._task
            else:
                self._closed = True
                task = self._task
                if task is not None and not task.done():
                    await self._queue.put(None)
        if task is not None:
            await task
