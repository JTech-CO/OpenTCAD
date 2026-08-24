"""Crash injection, restart convergence, and recovery claim contract tests."""

import asyncio
import unittest
from uuid import UUID

from backend.app.broker import (
    BrokerError,
    BrokerState,
    CrashRecoveryCoordinator,
    DurableJobEvent,
    InMemoryJobStateStore,
    InMemoryStateStoreBacking,
    RecoveryCheckpoint,
    RecoveryCrashInjection,
    RecoveryInterrupted,
    RecoveryRequest,
    RecoveryStatus,
    ReconciliationReport,
)
from backend.app.runtime.errors import ErrorCode, RetryDisposition, RuntimePhase
from backend.app.runtime.models import JobIdentity, RuntimeKind


def uuid_at(value: int) -> str:
    return str(UUID(int=value))


def recovery_event(
    job: int,
    event_number: int,
    operation_sequence: int,
    state: BrokerState,
    phase: RuntimePhase,
) -> DurableJobEvent:
    return DurableJobEvent(
        identity=JobIdentity(uuid_at(20_000 + job)),
        event_id=uuid_at(300_000 + event_number),
        operation_id=uuid_at(400_000 + job),
        operation_sequence=operation_sequence,
        state=state,
        phase=phase,
        backend=RuntimeKind.MOCK,
    )


class ObjectReconciler:
    """Small runtime-object model independent of any Docker or Podman socket."""

    def __init__(self, objects: dict[str, int], *, failures: int = 0) -> None:
        self.objects = objects
        self.failures = failures

    async def reconcile(self, job_id: str | None = None) -> ReconciliationReport:
        if job_id is None:
            raise TypeError("ObjectReconciler requires an exact job id.")
        found = self.objects.get(job_id, 0)
        if self.failures:
            self.failures -= 1
            return ReconciliationReport(
                containers_found=found,
                containers_removed=0,
                volumes_found=0,
                volumes_removed=0,
                remaining_containers=found,
                remaining_volumes=0,
                errors=(
                    BrokerError(
                        ErrorCode.CLEANUP_FAILED,
                        RuntimePhase.CLEANUP,
                        RetryDisposition.INFRASTRUCTURE,
                        RuntimeKind.MOCK.value,
                    ),
                ),
            )
        self.objects[job_id] = 0
        return ReconciliationReport(
            containers_found=found,
            containers_removed=found,
            volumes_found=0,
            volumes_removed=0,
            remaining_containers=0,
            remaining_volumes=0,
            errors=(),
        )


class BarrierScanStore:
    """Returns the same pre-claim page to two concurrent recovery coordinators."""

    def __init__(self, delegate: InMemoryJobStateStore) -> None:
        self.delegate = delegate
        self._guard = asyncio.Lock()
        self._arrived = 0
        self._released = asyncio.Event()

    async def load(self, identity):
        return await self.delegate.load(identity)

    async def append(self, event, *, expected_revision):
        return await self.delegate.append(event, expected_revision=expected_revision)

    async def scan_recoverable(self, *, after=None, limit=100):
        page = await self.delegate.scan_recoverable(after=after, limit=limit)
        async with self._guard:
            self._arrived += 1
            if self._arrived == 2:
                self._released.set()
        await self._released.wait()
        return page


class CrashRecoveryContractTests(unittest.IsolatedAsyncioTestCase):
    async def seed(
        self,
        store: InMemoryJobStateStore,
        job: int,
        *,
        cancelling: bool = False,
    ):
        first = await store.append(
            recovery_event(
                job,
                job * 10 + 1,
                1,
                BrokerState.VALIDATING,
                RuntimePhase.VALIDATE,
            ),
            expected_revision=0,
        )
        if cancelling:
            return await store.append(
                recovery_event(
                    job,
                    job * 10 + 2,
                    2,
                    BrokerState.CANCELLING,
                    RuntimePhase.KILL,
                ),
                expected_revision=first.revision,
            )
        prepared = await store.append(
            recovery_event(
                job,
                job * 10 + 2,
                2,
                BrokerState.PREPARING,
                RuntimePhase.IMAGE,
            ),
            expected_revision=first.revision,
        )
        return await store.append(
            recovery_event(
                job,
                job * 10 + 3,
                3,
                BrokerState.RUNNING,
                RuntimePhase.WAIT,
            ),
            expected_revision=prepared.revision,
        )

    async def test_all_crash_points_converge_after_fresh_adapter_handle_restart(self) -> None:
        expected = {
            RecoveryCheckpoint.BEFORE_CLAIM: (BrokerState.RUNNING, 3, 1),
            RecoveryCheckpoint.AFTER_CLAIM: (BrokerState.CLEANING, 4, 1),
            RecoveryCheckpoint.AFTER_RECONCILE: (BrokerState.CLEANING, 4, 0),
            RecoveryCheckpoint.AFTER_TERMINAL_APPEND: (BrokerState.FAILED, 5, 0),
        }
        for offset, checkpoint in enumerate(RecoveryCheckpoint, start=1):
            with self.subTest(checkpoint=checkpoint.value):
                backing = InMemoryStateStoreBacking()
                store = InMemoryJobStateStore(backing)
                seeded = await self.seed(store, 100 + offset)
                objects = {seeded.identity.job_id: 1}
                reconciler = ObjectReconciler(objects)
                request = RecoveryRequest(uuid_at(500_000 + offset), limit=1)
                coordinator = CrashRecoveryCoordinator(
                    store,
                    reconciler,
                    RuntimeKind.MOCK,
                )
                with self.assertRaises(RecoveryInterrupted) as interrupted:
                    await coordinator.recover(
                        request,
                        RecoveryCrashInjection(checkpoint, seeded.identity.job_id),
                    )
                self.assertEqual(interrupted.exception.checkpoint, checkpoint)
                state, revision, remaining = expected[checkpoint]
                crashed = await store.load(seeded.identity)
                self.assertEqual((crashed.state, crashed.revision), (state, revision))
                self.assertEqual(objects[seeded.identity.job_id], remaining)

                reopened = InMemoryJobStateStore(backing)
                report = await CrashRecoveryCoordinator(
                    reopened,
                    reconciler,
                    RuntimeKind.MOCK,
                ).recover(request)
                final = await reopened.load(seeded.identity)
                self.assertEqual(final.state, BrokerState.FAILED)
                self.assertFalse(final.recoverable)
                self.assertEqual(objects[seeded.identity.job_id], 0)
                if checkpoint is RecoveryCheckpoint.AFTER_TERMINAL_APPEND:
                    self.assertEqual(report.items, ())
                else:
                    self.assertEqual(report.items[0].status, RecoveryStatus.RECOVERED_FAILED)

    async def test_cancellation_intent_closes_as_cancelled(self) -> None:
        store = InMemoryJobStateStore()
        seeded = await self.seed(store, 110, cancelling=True)
        reconciler = ObjectReconciler({seeded.identity.job_id: 1})
        report = await CrashRecoveryCoordinator(
            store,
            reconciler,
            RuntimeKind.MOCK,
        ).recover(RecoveryRequest(uuid_at(500_110), limit=1))
        final = await store.load(seeded.identity)
        self.assertEqual(final.state, BrokerState.CANCELLED)
        self.assertEqual(report.items[0].status, RecoveryStatus.RECOVERED_CANCELLED)

    async def test_concurrent_recoverers_from_one_revision_have_one_cas_winner(self) -> None:
        delegate = InMemoryJobStateStore()
        seeded = await self.seed(delegate, 120)
        store = BarrierScanStore(delegate)
        reconciler = ObjectReconciler({seeded.identity.job_id: 1})
        coordinators = (
            CrashRecoveryCoordinator(store, reconciler, RuntimeKind.MOCK),
            CrashRecoveryCoordinator(store, reconciler, RuntimeKind.MOCK),
        )
        reports = await asyncio.gather(
            coordinators[0].recover(RecoveryRequest(uuid_at(500_120), limit=1)),
            coordinators[1].recover(RecoveryRequest(uuid_at(500_121), limit=1)),
        )
        statuses = {report.items[0].status for report in reports}
        self.assertEqual(
            statuses,
            {RecoveryStatus.RECOVERED_FAILED, RecoveryStatus.REVISION_CONFLICT},
        )
        self.assertEqual((await delegate.load(seeded.identity)).state, BrokerState.FAILED)

    async def test_incomplete_cleanup_remains_recoverable_for_next_pass(self) -> None:
        backing = InMemoryStateStoreBacking()
        first_store = InMemoryJobStateStore(backing)
        seeded = await self.seed(first_store, 130)
        objects = {seeded.identity.job_id: 1}
        reconciler = ObjectReconciler(objects, failures=1)
        first = await CrashRecoveryCoordinator(
            first_store,
            reconciler,
            RuntimeKind.MOCK,
        ).recover(RecoveryRequest(uuid_at(500_130), limit=1))
        pending = await first_store.load(seeded.identity)
        self.assertEqual(first.items[0].status, RecoveryStatus.CLEANUP_PENDING)
        self.assertEqual(pending.state, BrokerState.CLEANING)
        self.assertTrue(pending.recoverable)
        self.assertEqual(objects[seeded.identity.job_id], 1)

        reopened = InMemoryJobStateStore(backing)
        second = await CrashRecoveryCoordinator(
            reopened,
            reconciler,
            RuntimeKind.MOCK,
        ).recover(RecoveryRequest(uuid_at(500_131), limit=1))
        final = await reopened.load(seeded.identity)
        self.assertEqual(second.items[0].status, RecoveryStatus.RECOVERED_FAILED)
        self.assertEqual(final.state, BrokerState.FAILED)
        self.assertFalse(final.recoverable)
        self.assertEqual(objects[seeded.identity.job_id], 0)


if __name__ == "__main__":
    unittest.main()
