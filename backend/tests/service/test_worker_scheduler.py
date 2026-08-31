from __future__ import annotations

import asyncio
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from backend.app.broker.backup_control import (
    BackupControlError,
    BackupControlErrorCode,
    MaintenancePhase,
    MaintenanceRequest,
    SQLiteBackupControlStore,
)
from backend.app.broker.backup_service import (
    AuthenticatedBackupError,
    AuthenticatedBackupErrorCode,
    AuthenticatedImportRequest,
    AuthenticatedSQLiteBackupService,
    ScheduledSQLiteBackupRunner,
)
from backend.app.broker.models import BrokerRequest
from backend.app.broker.cancellation import CancellationRequest
from backend.app.runtime.models import JobIdentity
from backend.app.broker.state_composition import (
    DurableBrokerComposition,
    StateOperationContext,
)
from backend.app.service.scheduler import (
    ScheduledBackupLoop,
    ScheduledBackupLoopConfiguration,
    SchedulerError,
    SchedulerErrorCode,
)
from backend.app.service.anti_rollback import NativeRestoreFloorStore
from backend.app.service.credentials import InMemoryCredentialStore
from backend.app.service.worker import (
    BackupImportWork,
    CancelWork,
    ExecuteWork,
    LocalBrokerWorker,
    LocalLifecycleCoordinator,
    WorkerEnvelope,
    WorkerError,
    WorkerErrorCode,
    WorkerOperation,
)
from backend.tests.runtime.support import ARCHIVE_BYTES, make_spec


class RecordingCoordinator(LocalLifecycleCoordinator):
    def __init__(self) -> None:
        self.calls = 0
        self.active = 0
        self.maximum_active = 0

    async def dispatch(self, operation, payload):
        self.calls += 1
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return (operation.value, payload)


class BlockingCoordinator(LocalLifecycleCoordinator):
    def __init__(self) -> None:
        self.execution_started = asyncio.Event()
        self.release_execution = asyncio.Event()
        self.cancel_seen = asyncio.Event()

    async def dispatch(self, operation, payload):
        if operation is WorkerOperation.EXECUTE:
            self.execution_started.set()
            await self.release_execution.wait()
            return "executed"
        if operation is WorkerOperation.CANCEL:
            self.cancel_seen.set()
            return "cancelled"
        raise AssertionError(operation)


class DummyComposition(DurableBrokerComposition):
    def __init__(self) -> None:
        self.executions = 0

    async def execute(self, request, context, cancellation=None):
        self.executions += 1
        return {"operation": context.operation_id}


class SlowComposition(DurableBrokerComposition):
    def __init__(self) -> None:
        self.signal = None

    async def execute(self, request, context, cancellation=None):
        self.signal = cancellation
        await asyncio.sleep(0.45)
        return {"operation": context.operation_id}


class BlockingCancelComposition(DurableBrokerComposition):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def cancel(self, request, context):
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        return {"operation": context.operation_id}


class CountingControlStore(SQLiteBackupControlStore):
    def __init__(self, path, installation_id) -> None:
        super().__init__(path, installation_id)
        self.renewals = 0

    def renew_operation(self, admission, *, lease_duration_ms):
        self.renewals += 1
        return super().renew_operation(
            admission,
            lease_duration_ms=lease_duration_ms,
        )


class FailingRenewControlStore(SQLiteBackupControlStore):
    def renew_operation(self, admission, *, lease_duration_ms):
        raise BackupControlError(BackupControlErrorCode.CONTROL_UNAVAILABLE)


class DummyBackupService(AuthenticatedSQLiteBackupService):
    def __init__(self) -> None:
        pass


class RecordingImportService(DummyBackupService):
    def __init__(self, control, manifest) -> None:
        self.control = control
        self.manifest = manifest
        self.observed_phase = None

    def validate_export(self, source, policy):
        return object(), self.manifest

    def import_export(self, source, destination, request):
        lease = self.control.begin_maintenance(request.maintenance_request())
        self.observed_phase = lease.phase
        return "imported"


class DummyScheduledRunner(ScheduledSQLiteBackupRunner):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_due(self, schedule_id, owner_id, *, lease_duration_ms, crash_signal=None):
        self.calls.append(schedule_id)
        if schedule_id.endswith("1"):
            raise BackupControlError(BackupControlErrorCode.SCHEDULE_NOT_DUE)
        if schedule_id.endswith("3"):
            raise BackupControlError(BackupControlErrorCode.SCHEDULE_NOT_FOUND)
        if schedule_id.endswith("4"):
            raise AuthenticatedBackupError(
                AuthenticatedBackupErrorCode.AUTHENTICATION_FAILED,
            )
        return schedule_id


class UnexpectedThenSuccessScheduledRunner(ScheduledSQLiteBackupRunner):
    def __init__(self) -> None:
        self.calls = 0

    def run_due(self, schedule_id, owner_id, *, lease_duration_ms, crash_signal=None):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("sensitive path: C:/private/backup-control.sqlite3")
        return schedule_id


class WorkerTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_capacity_bounds_active_and_queued_requests(self) -> None:
        coordinator = BlockingCoordinator()
        worker = LocalBrokerWorker(
            coordinator,
            queue_capacity=1,
            execution_concurrency=1,
        )
        await worker.start()
        first = WorkerEnvelope(
            str(uuid4()),
            sha256(b"first").hexdigest(),
            WorkerOperation.EXECUTE,
            object(),
        )
        task = asyncio.create_task(worker.submit(first))
        await coordinator.execution_started.wait()
        second = WorkerEnvelope(
            str(uuid4()),
            sha256(b"second").hexdigest(),
            WorkerOperation.EXECUTE,
            object(),
        )
        with self.assertRaises(WorkerError) as raised:
            await worker.submit(second)
        self.assertEqual(raised.exception.code, WorkerErrorCode.CAPACITY_REACHED)
        coordinator.release_execution.set()
        self.assertEqual(await task, "executed")
        await worker.close()

    async def test_single_owner_and_idempotent_result_cache(self) -> None:
        coordinator = RecordingCoordinator()
        worker = LocalBrokerWorker(coordinator, queue_capacity=4)
        request_id = str(uuid4())
        envelope = WorkerEnvelope(
            request_id,
            sha256(b"same").hexdigest(),
            WorkerOperation.STARTUP_RECOVERY,
            "payload",
        )
        with self.assertRaises(WorkerError) as before_start:
            await worker.submit(envelope)
        self.assertEqual(before_start.exception.code, WorkerErrorCode.NOT_STARTED)
        await worker.start()
        first, duplicate = await asyncio.gather(
            worker.submit(envelope),
            worker.submit(envelope),
        )
        self.assertEqual(first, duplicate)
        self.assertEqual(coordinator.calls, 1)
        values = [
            WorkerEnvelope(
                str(uuid4()),
                sha256(str(index).encode()).hexdigest(),
                WorkerOperation.STARTUP_RECOVERY,
                index,
            )
            for index in range(3)
        ]
        await asyncio.gather(*(worker.submit(value) for value in values))
        self.assertEqual(coordinator.maximum_active, 1)
        conflict = WorkerEnvelope(
            request_id,
            sha256(b"different").hexdigest(),
            WorkerOperation.STARTUP_RECOVERY,
            "payload",
        )
        with self.assertRaises(WorkerError) as raised:
            await worker.submit(conflict)
        self.assertEqual(raised.exception.code, WorkerErrorCode.REQUEST_CONFLICT)
        await worker.close()

    async def test_execution_admission_is_released_before_maintenance(self) -> None:
        with TemporaryDirectory() as directory:
            installation = str(uuid4())
            control = SQLiteBackupControlStore(
                Path(directory) / "control.sqlite3",
                installation,
            )
            composition = DummyComposition()
            coordinator = LocalLifecycleCoordinator(
                composition,
                control,
                DummyBackupService(),
                DummyScheduledRunner(),
                NativeRestoreFloorStore(InMemoryCredentialStore()),
            )
            operation_id = str(uuid4())
            owner_id = str(uuid4())
            request = BrokerRequest(make_spec(str(uuid4())), ARCHIVE_BYTES)
            result = await coordinator.dispatch(
                WorkerOperation.EXECUTE,
                ExecuteWork(
                    request,
                    StateOperationContext(operation_id),
                    owner_id,
                    60_000,
                ),
            )
            self.assertEqual(result, {"operation": operation_id})
            maintenance = MaintenanceRequest(
                str(uuid4()),
                str(uuid4()),
                str(uuid4()),
                60_000,
            )
            lease = await coordinator.dispatch(
                WorkerOperation.MAINTENANCE_BEGIN,
                maintenance,
            )
            offline = await coordinator.dispatch(
                WorkerOperation.MAINTENANCE_OFFLINE,
                lease,
            )
            await coordinator.dispatch(
                WorkerOperation.MAINTENANCE_END,
                offline,
            )

    async def test_cancellation_admission_blocks_offline_snapshot_transition(self) -> None:
        with TemporaryDirectory() as directory:
            installation = str(uuid4())
            control = SQLiteBackupControlStore(
                Path(directory) / "control.sqlite3",
                installation,
            )
            composition = BlockingCancelComposition()
            coordinator = LocalLifecycleCoordinator(
                composition,
                control,
                DummyBackupService(),
                DummyScheduledRunner(),
                NativeRestoreFloorStore(InMemoryCredentialStore()),
            )
            operation_id = str(uuid4())
            cancel_task = asyncio.create_task(
                coordinator.dispatch(
                    WorkerOperation.CANCEL,
                    CancelWork(
                        CancellationRequest(JobIdentity(str(uuid4()))),
                        StateOperationContext(operation_id),
                    ),
                ),
            )
            await composition.started.wait()
            lease = control.begin_maintenance(
                MaintenanceRequest(
                    str(uuid4()),
                    str(uuid4()),
                    str(uuid4()),
                    60_000,
                ),
            )
            with self.assertRaises(BackupControlError) as raised:
                control.mark_offline(lease)
            self.assertEqual(
                raised.exception.code,
                BackupControlErrorCode.MAINTENANCE_NOT_QUIESCENT,
            )
            composition.release.set()
            self.assertEqual(
                await cancel_task,
                {"operation": operation_id},
            )
            offline = control.mark_offline(lease)
            control.end_maintenance(offline)

    async def test_cancellation_stops_when_maintenance_admission_is_lost(self) -> None:
        with TemporaryDirectory() as directory:
            installation = str(uuid4())
            control = FailingRenewControlStore(
                Path(directory) / "control.sqlite3",
                installation,
            )
            composition = BlockingCancelComposition()
            coordinator = LocalLifecycleCoordinator(
                composition,
                control,
                DummyBackupService(),
                DummyScheduledRunner(),
                NativeRestoreFloorStore(InMemoryCredentialStore()),
            )
            with patch(
                "backend.app.service.worker._CANCELLATION_ADMISSION_LEASE_MS",
                300,
            ):
                task = asyncio.create_task(
                    coordinator.dispatch(
                        WorkerOperation.CANCEL,
                        CancelWork(
                            CancellationRequest(JobIdentity(str(uuid4()))),
                            StateOperationContext(str(uuid4())),
                        ),
                    ),
                )
                await composition.started.wait()
                with self.assertRaises(BackupControlError) as raised:
                    await asyncio.wait_for(task, timeout=1)
            self.assertEqual(
                raised.exception.code,
                BackupControlErrorCode.CONTROL_UNAVAILABLE,
            )
            self.assertTrue(composition.cancelled.is_set())

    async def test_long_execution_renews_maintenance_admission(self) -> None:
        with TemporaryDirectory() as directory:
            installation = str(uuid4())
            control = CountingControlStore(
                Path(directory) / "control.sqlite3",
                installation,
            )
            composition = SlowComposition()
            coordinator = LocalLifecycleCoordinator(
                composition,
                control,
                DummyBackupService(),
                DummyScheduledRunner(),
                NativeRestoreFloorStore(InMemoryCredentialStore()),
            )
            operation_id = str(uuid4())
            result = await coordinator.dispatch(
                WorkerOperation.EXECUTE,
                ExecuteWork(
                    BrokerRequest(make_spec(str(uuid4())), ARCHIVE_BYTES),
                    StateOperationContext(operation_id),
                    str(uuid4()),
                    600,
                ),
            )
            self.assertEqual(result, {"operation": operation_id})
            self.assertGreaterEqual(control.renewals, 1)
            self.assertIsNotNone(composition.signal)

    async def test_import_advances_native_floor_only_after_offline(self) -> None:
        with TemporaryDirectory() as directory:
            installation = str(uuid4())
            control = SQLiteBackupControlStore(
                Path(directory) / "control.sqlite3",
                installation,
            )
            snapshot_id = str(uuid4())
            manifest = SimpleNamespace(
                source_instance_id=installation,
                snapshot_id=snapshot_id,
                snapshot_sequence=2,
            )
            service = RecordingImportService(control, manifest)
            floor = NativeRestoreFloorStore(InMemoryCredentialStore())
            coordinator = LocalLifecycleCoordinator(
                DummyComposition(),
                control,
                service,
                DummyScheduledRunner(),
                floor,
            )
            request = AuthenticatedImportRequest(
                snapshot_id,
                installation,
                1,
                str(uuid4()),
                str(uuid4()),
                str(uuid4()),
                60_000,
            )
            result = await coordinator.dispatch(
                WorkerOperation.BACKUP_IMPORT,
                BackupImportWork(
                    request,
                    Path(directory) / "source",
                    Path(directory) / "destination",
                ),
            )
            self.assertEqual(result, "imported")
            self.assertEqual(service.observed_phase, MaintenancePhase.OFFLINE)
            self.assertEqual(
                floor.current(installation).minimum_snapshot_sequence,
                2,
            )
            reopened = control.begin_maintenance(
                MaintenanceRequest(
                    str(uuid4()),
                    str(uuid4()),
                    str(uuid4()),
                    60_000,
                ),
            )
            control.end_maintenance(reopened)

    async def test_cancel_control_lane_runs_while_execution_is_blocked(self) -> None:
        coordinator = BlockingCoordinator()
        worker = LocalBrokerWorker(
            coordinator,
            queue_capacity=1,
            control_capacity=1,
            execution_concurrency=1,
        )
        await worker.start()
        execute = WorkerEnvelope(
            str(uuid4()),
            sha256(b"execute").hexdigest(),
            WorkerOperation.EXECUTE,
            object(),
        )
        cancel = WorkerEnvelope(
            str(uuid4()),
            sha256(b"cancel").hexdigest(),
            WorkerOperation.CANCEL,
            object(),
        )
        execute_task = asyncio.create_task(worker.submit(execute))
        await coordinator.execution_started.wait()
        self.assertEqual(await worker.submit(cancel), "cancelled")
        self.assertTrue(coordinator.cancel_seen.is_set())
        self.assertFalse(execute_task.done())
        coordinator.release_execution.set()
        self.assertEqual(await execute_task, "executed")
        await worker.close()


class ScheduledBackupLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_background_loop_redacts_unexpected_failure_and_retries(self) -> None:
        runner = UnexpectedThenSuccessScheduledRunner()
        schedule_id = "00000000-0000-0000-0000-000000000005"
        observed: list[tuple[str, SchedulerError]] = []
        loop = ScheduledBackupLoop(
            runner,
            ScheduledBackupLoopConfiguration(
                (schedule_id,),
                str(uuid4()),
                poll_interval_ms=100,
                claim_lease_ms=1_000,
            ),
            error_sink=lambda value, error: observed.append((value, error)),
        )
        await loop.start()
        try:
            async with asyncio.timeout(1):
                while runner.calls < 2:
                    await asyncio.sleep(0.01)
            self.assertTrue(loop.running)
        finally:
            await loop.close()

        self.assertEqual(len(observed), 1)
        observed_id, error = observed[0]
        self.assertEqual(observed_id, schedule_id)
        self.assertIsInstance(error, SchedulerError)
        self.assertEqual(error.code, SchedulerErrorCode.UNEXPECTED_FAILURE)
        self.assertEqual(
            error.as_dict(),
            {"code": "scheduled-backup-unexpected-failure"},
        )
        self.assertNotIn("private", str(error))
        self.assertEqual(loop.failures, {})

    async def test_run_once_treats_not_due_as_idle(self) -> None:
        runner = DummyScheduledRunner()
        first = "00000000-0000-0000-0000-000000000001"
        second = "00000000-0000-0000-0000-000000000002"
        configuration = ScheduledBackupLoopConfiguration(
            (first, second),
            str(uuid4()),
            poll_interval_ms=100,
            claim_lease_ms=1_000,
        )
        loop = ScheduledBackupLoop(runner, configuration)
        self.assertEqual(await loop.run_once(), 1)
        self.assertEqual(runner.calls, [first, second])
        await loop.start()
        await asyncio.sleep(0.02)
        await loop.close()
        self.assertFalse(loop.running)

    async def test_unexpected_schedule_failure_is_retained_and_reported(self) -> None:
        runner = DummyScheduledRunner()
        schedule_id = "00000000-0000-0000-0000-000000000003"
        backup_failure_id = "00000000-0000-0000-0000-000000000004"
        observed = []
        loop = ScheduledBackupLoop(
            runner,
            ScheduledBackupLoopConfiguration(
                (schedule_id, backup_failure_id),
                str(uuid4()),
                poll_interval_ms=100,
                claim_lease_ms=1_000,
            ),
            error_sink=lambda value, error: observed.append((value, error.code)),
        )
        self.assertEqual(await loop.run_once(), 0)
        self.assertEqual(
            loop.failures,
            {
                schedule_id: BackupControlErrorCode.SCHEDULE_NOT_FOUND,
                backup_failure_id: (
                    AuthenticatedBackupErrorCode.AUTHENTICATION_FAILED
                ),
            },
        )
        self.assertEqual(
            observed,
            [
                (schedule_id, BackupControlErrorCode.SCHEDULE_NOT_FOUND),
                (
                    backup_failure_id,
                    AuthenticatedBackupErrorCode.AUTHENTICATION_FAILED,
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
