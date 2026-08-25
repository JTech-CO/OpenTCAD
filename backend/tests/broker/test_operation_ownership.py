"""Durable owner generation and cross-operation fencing contract tests."""

from __future__ import annotations

import asyncio
import unittest
from uuid import UUID

from backend.app.broker import (
    BrokerRequest,
    BrokerStartupRequest,
    BrokerState,
    CancellationRequest,
    CrashRecoveryCoordinator,
    DurableBrokerComposition,
    DurableJobEvent,
    DurableJobStateStore,
    InMemoryJobStateStore,
    LifecycleCheckpoint,
    PhaseCancellation,
    RecoveryRequest,
    RecoveryStatus,
    SandboxBroker,
    StateOperationContext,
)
from backend.app.runtime.errors import ErrorCode, RuntimePhase
from backend.app.runtime.mock_backend import MockRuntimeBackend
from backend.app.runtime.models import (
    ContainerHandle,
    JobIdentity,
    ManagedObjects,
    RunResult,
    RuntimeKind,
    RuntimeProbe,
    TerminalClassification,
    TerminationReason,
)
from backend.tests.broker.lease_support import ManualLeaseClock
from backend.tests.broker.state_store_conformance import conformance_event
from backend.tests.runtime.support import (
    ARCHIVE,
    ARCHIVE_BYTES,
    ARCHIVE_LIMITS,
    ARTIFACT_ARCHIVE,
    IMAGE,
    POLICY,
    make_result,
    make_spec,
)


def uuid_at(value: int) -> str:
    return str(UUID(int=value))


class BarrierLoadStore:
    """Lets two execution admissions observe the same empty revision."""

    def __init__(self, delegate: DurableJobStateStore) -> None:
        self.delegate = delegate
        self.enabled = False
        self.arrivals = 0
        self.release = asyncio.Event()

    async def load(self, identity: JobIdentity):
        snapshot = await self.delegate.load(identity)
        if self.enabled:
            self.arrivals += 1
            if self.arrivals == 2:
                self.release.set()
            await self.release.wait()
        return snapshot

    async def append(self, event: DurableJobEvent, *, expected_revision: int):
        return await self.delegate.append(event, expected_revision=expected_revision)

    async def renew_ownership(
        self,
        ownership,
        *,
        expected_revision,
        lease_duration_ms,
    ):
        return await self.delegate.renew_ownership(
            ownership,
            expected_revision=expected_revision,
            lease_duration_ms=lease_duration_ms,
        )

    async def verify_ownership(self, ownership, *, expected_revision=None):
        return await self.delegate.verify_ownership(
            ownership,
            expected_revision=expected_revision,
        )

    async def scan_recoverable(self, *, after=None, limit=100):
        return await self.delegate.scan_recoverable(after=after, limit=limit)


class BlockingVerifyStore:
    """Pauses the first post-intent ownership verification."""

    def __init__(self, delegate: DurableJobStateStore) -> None:
        self.delegate = delegate
        self.enabled = False
        self.blocked = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def load(self, identity: JobIdentity):
        return await self.delegate.load(identity)

    async def append(self, event: DurableJobEvent, *, expected_revision: int):
        return await self.delegate.append(event, expected_revision=expected_revision)

    async def renew_ownership(
        self,
        ownership,
        *,
        expected_revision,
        lease_duration_ms,
    ):
        if self.enabled and not self.blocked:
            self.blocked = True
            self.entered.set()
            await self.release.wait()
        return await self.delegate.renew_ownership(
            ownership,
            expected_revision=expected_revision,
            lease_duration_ms=lease_duration_ms,
        )

    async def verify_ownership(self, ownership, *, expected_revision=None):
        return await self.delegate.verify_ownership(
            ownership,
            expected_revision=expected_revision,
        )

    async def scan_recoverable(self, *, after=None, limit=100):
        return await self.delegate.scan_recoverable(after=after, limit=limit)


class TakeoverOnRunningStore:
    """Transfers ownership immediately after the stale owner records RUNNING."""

    def __init__(self, delegate: DurableJobStateStore) -> None:
        self.delegate = delegate
        self.claimed = False

    async def load(self, identity: JobIdentity):
        return await self.delegate.load(identity)

    async def append(self, event: DurableJobEvent, *, expected_revision: int):
        snapshot = await self.delegate.append(event, expected_revision=expected_revision)
        if event.state is BrokerState.RUNNING and not self.claimed:
            self.claimed = True
            await self.delegate.append(
                DurableJobEvent(
                    identity=event.identity,
                    event_id=uuid_at(990_001),
                    operation_id=uuid_at(990_002),
                    operation_sequence=1,
                    owner_id=uuid_at(990_003),
                    fencing_token=event.fencing_token + 1,
                    state=BrokerState.CANCELLING,
                    phase=RuntimePhase.KILL,
                    backend=event.backend,
                ),
                expected_revision=snapshot.revision,
            )
        return snapshot

    async def renew_ownership(
        self,
        ownership,
        *,
        expected_revision,
        lease_duration_ms,
    ):
        return await self.delegate.renew_ownership(
            ownership,
            expected_revision=expected_revision,
            lease_duration_ms=lease_duration_ms,
        )

    async def verify_ownership(self, ownership, *, expected_revision=None):
        return await self.delegate.verify_ownership(
            ownership,
            expected_revision=expected_revision,
        )

    async def scan_recoverable(self, *, after=None, limit=100):
        return await self.delegate.scan_recoverable(after=after, limit=limit)


class CountingBackend(MockRuntimeBackend):
    def __init__(self) -> None:
        super().__init__(images=(IMAGE,))
        self.probe_calls = 0

    async def probe(self) -> RuntimeProbe:
        self.probe_calls += 1
        return await super().probe()


class KillTrackingBackend(MockRuntimeBackend):
    def __init__(self) -> None:
        super().__init__(images=(IMAGE,))
        self.kill_reasons: list[TerminationReason] = []

    async def kill(
        self,
        container: ContainerHandle,
        reason: TerminationReason,
    ) -> RunResult:
        self.kill_reasons.append(reason)
        return await super().kill(container, reason)


class StartBarrierBackend(KillTrackingBackend):
    """Leaves a running container visible while execution is still in start()."""

    def __init__(self) -> None:
        super().__init__()
        self.start_entered = asyncio.Event()
        self.start_release = asyncio.Event()
        self.wait_calls = 0

    async def start(self, container: ContainerHandle) -> None:
        await super().start(container)
        self.start_entered.set()
        await self.start_release.wait()

    async def wait(self, container: ContainerHandle) -> RunResult:
        self.wait_calls += 1
        return await super().wait(container)


class FirstQueryBarrierBackend(KillTrackingBackend):
    """Pauses one recovery after its claim but before any cleanup mutation."""

    def __init__(self) -> None:
        super().__init__()
        self.enabled = False
        self.blocked = False
        self.query_entered = asyncio.Event()
        self.query_release = asyncio.Event()

    async def list_managed(self, job_id: str | None = None) -> ManagedObjects:
        managed = await super().list_managed(job_id)
        if self.enabled and not self.blocked:
            self.blocked = True
            self.query_entered.set()
            await self.query_release.wait()
        return managed


class DurableOperationOwnershipTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def broker(backend: MockRuntimeBackend) -> SandboxBroker:
        return SandboxBroker(backend, POLICY, ARCHIVE_LIMITS)

    @classmethod
    async def composition(
        cls,
        backend: MockRuntimeBackend,
        store: DurableJobStateStore,
        startup_id: int,
    ) -> DurableBrokerComposition:
        composition = DurableBrokerComposition(cls.broker(backend), store)
        await composition.startup(BrokerStartupRequest(uuid_at(startup_id), page_limit=2))
        return composition

    @staticmethod
    async def seed_running(store: DurableJobStateStore, job: int):
        snapshot = None
        path = (
            (BrokerState.VALIDATING, RuntimePhase.VALIDATE),
            (BrokerState.PREPARING, RuntimePhase.IMAGE),
            (BrokerState.RUNNING, RuntimePhase.WAIT),
        )
        for sequence, (state, phase) in enumerate(path, start=1):
            snapshot = await store.append(
                conformance_event(
                    job=job,
                    event_number=job * 10 + sequence,
                    operation=job,
                    operation_sequence=sequence,
                    state=state,
                    phase=phase,
                ),
                expected_revision=sequence - 1,
            )
        return snapshot

    @staticmethod
    async def create_running_objects(
        backend: MockRuntimeBackend,
        identity: JobIdentity,
    ) -> None:
        capabilities = (await backend.probe()).capabilities
        validated = POLICY.validate(make_spec(identity.job_id), capabilities)
        volume = await backend.create_volume(validated.identity)
        await backend.stage_inputs(volume, validated, ARCHIVE)
        container = await backend.create_container(validated, volume)
        await backend.start(container)

    async def test_same_logical_execution_has_one_owner_and_one_runtime_caller(self) -> None:
        backend = CountingBackend()
        delegate = InMemoryJobStateStore()
        store = BarrierLoadStore(delegate)
        first = await self.composition(backend, store, 70_001)
        second = await self.composition(backend, store, 70_002)
        identity = JobIdentity(uuid_at(10_501))
        backend.plan_result(
            identity.job_id,
            make_result(
                TerminalClassification.SUCCEEDED,
                exit_code=0,
                include_artifact=True,
            ),
            ARTIFACT_ARCHIVE,
        )
        store.enabled = True
        context = StateOperationContext(uuid_at(80_001))

        outcomes = await asyncio.gather(
            first.execute(
                BrokerRequest(make_spec(identity.job_id), ARCHIVE_BYTES),
                context,
            ),
            second.execute(
                BrokerRequest(make_spec(identity.job_id), ARCHIVE_BYTES),
                context,
            ),
        )

        succeeded = [item for item in outcomes if item.state is BrokerState.SUCCEEDED]
        fenced = [item for item in outcomes if item.error is not None]
        self.assertEqual((len(succeeded), len(fenced)), (1, 1))
        self.assertEqual(fenced[0].error.code, ErrorCode.OPERATION_FENCED)
        self.assertEqual(fenced[0].cleanup_error.code, ErrorCode.OPERATION_FENCED)
        self.assertEqual(backend.probe_calls, 1)
        self.assertEqual(store.arrivals, 2)
        final = await delegate.load(identity)
        self.assertEqual((final.state, final.ownership.fencing_token), (BrokerState.SUCCEEDED, 1))

    async def test_cancellation_takeover_fences_live_execution_before_wait(self) -> None:
        backend = StartBarrierBackend()
        store = InMemoryJobStateStore()
        execution = await self.composition(backend, store, 70_010)
        cancellation = await self.composition(backend, store, 70_011)
        identity = JobIdentity(uuid_at(10_510))
        execution_task = asyncio.create_task(
            execution.execute(
                BrokerRequest(make_spec(identity.job_id), ARCHIVE_BYTES),
                StateOperationContext(uuid_at(80_010)),
            ),
        )
        await asyncio.wait_for(backend.start_entered.wait(), timeout=2)
        try:
            cancelled = await cancellation.cancel(
                CancellationRequest(identity),
                StateOperationContext(uuid_at(80_011)),
            )
        finally:
            backend.start_release.set()
        stale_execution = await asyncio.wait_for(execution_task, timeout=2)

        self.assertEqual(cancelled.state, BrokerState.CANCELLED)
        self.assertEqual(stale_execution.state, BrokerState.FAILED)
        self.assertEqual(stale_execution.error.code, ErrorCode.OPERATION_FENCED)
        self.assertEqual(
            stale_execution.cleanup_error.code,
            ErrorCode.OPERATION_FENCED,
        )
        self.assertEqual(backend.wait_calls, 0)
        self.assertEqual(backend.kill_reasons, [TerminationReason.CANCELLATION])
        final = await store.load(identity)
        self.assertEqual(
            (final.state, final.ownership.fencing_token),
            (BrokerState.CANCELLED, 2),
        )
        managed = await backend.list_managed(identity.job_id)
        self.assertEqual((managed.containers, managed.volumes), ((), ()))

    async def test_takeover_during_local_cancellation_fences_kill_and_cleanup(self) -> None:
        backend = KillTrackingBackend()
        delegate = InMemoryJobStateStore()
        store = TakeoverOnRunningStore(delegate)
        execution = await self.composition(backend, store, 70_015)
        identity = JobIdentity(uuid_at(10_515))

        outcome = await execution.execute(
            BrokerRequest(make_spec(identity.job_id), ARCHIVE_BYTES),
            StateOperationContext(uuid_at(80_015)),
            PhaseCancellation(identity, LifecycleCheckpoint.WAIT),
        )

        self.assertTrue(store.claimed)
        self.assertEqual(outcome.state, BrokerState.FAILED)
        self.assertEqual(outcome.error.code, ErrorCode.OPERATION_FENCED)
        self.assertEqual(outcome.cleanup_error.code, ErrorCode.OPERATION_FENCED)
        self.assertEqual(backend.kill_reasons, [])
        final = await delegate.load(identity)
        self.assertEqual(
            (final.state, final.revision, final.ownership.fencing_token),
            (BrokerState.CANCELLING, 4, 2),
        )
        managed = await backend.list_managed(identity.job_id)
        self.assertEqual((len(managed.containers), len(managed.volumes)), (1, 1))

    async def test_recovery_takeover_fences_cancellation_before_runtime_query(self) -> None:
        backend = KillTrackingBackend()
        clock = ManualLeaseClock()
        delegate = InMemoryJobStateStore(clock=clock)
        store = BlockingVerifyStore(delegate)
        cancellation = await self.composition(backend, store, 70_020)
        seeded = await self.seed_running(delegate, 520)
        await self.create_running_objects(backend, seeded.identity)
        store.enabled = True
        cancellation_task = asyncio.create_task(
            cancellation.cancel(
                CancellationRequest(seeded.identity),
                StateOperationContext(uuid_at(80_020)),
            ),
        )
        await asyncio.wait_for(store.entered.wait(), timeout=2)
        try:
            live_owner = await CrashRecoveryCoordinator(
                delegate,
                self.broker(backend),
                RuntimeKind.MOCK,
            ).recover(RecoveryRequest(uuid_at(90_020), limit=1))
            self.assertEqual(live_owner.items[0].status, RecoveryStatus.OWNER_ACTIVE)
            clock.advance(30_001)
            recovered = await CrashRecoveryCoordinator(
                delegate,
                self.broker(backend),
                RuntimeKind.MOCK,
            ).recover(RecoveryRequest(uuid_at(90_021), limit=1))
        finally:
            store.release.set()
        stale_cancellation = await asyncio.wait_for(cancellation_task, timeout=2)

        self.assertEqual(
            recovered.items[0].status,
            RecoveryStatus.RECOVERED_CANCELLED,
        )
        self.assertEqual(stale_cancellation.state, BrokerState.FAILED)
        self.assertEqual(stale_cancellation.error.code, ErrorCode.OPERATION_FENCED)
        self.assertEqual(
            stale_cancellation.cleanup_error.code,
            ErrorCode.OPERATION_FENCED,
        )
        self.assertNotIn(TerminationReason.CANCELLATION, backend.kill_reasons)
        self.assertEqual(backend.kill_reasons, [TerminationReason.SHUTDOWN])
        final = await delegate.load(seeded.identity)
        self.assertEqual(
            (final.state, final.ownership.fencing_token),
            (BrokerState.CANCELLED, 3),
        )

    async def test_newer_recovery_fences_older_reconciler_before_mutation(self) -> None:
        backend = FirstQueryBarrierBackend()
        clock = ManualLeaseClock()
        store = InMemoryJobStateStore(clock=clock)
        seeded = await self.seed_running(store, 530)
        clock.advance(30_001)
        await self.create_running_objects(backend, seeded.identity)
        backend.enabled = True
        first_task = asyncio.create_task(
            CrashRecoveryCoordinator(
                store,
                self.broker(backend),
                RuntimeKind.MOCK,
            ).recover(RecoveryRequest(uuid_at(90_030), limit=1)),
        )
        await asyncio.wait_for(backend.query_entered.wait(), timeout=2)
        try:
            clock.advance(30_001)
            newer = await CrashRecoveryCoordinator(
                store,
                self.broker(backend),
                RuntimeKind.MOCK,
            ).recover(RecoveryRequest(uuid_at(90_031), limit=1))
        finally:
            backend.query_release.set()
        older = await asyncio.wait_for(first_task, timeout=2)

        self.assertEqual(newer.items[0].status, RecoveryStatus.RECOVERED_FAILED)
        self.assertEqual(older.items[0].status, RecoveryStatus.OWNERSHIP_CONFLICT)
        self.assertEqual(older.items[0].code, ErrorCode.OPERATION_FENCED)
        self.assertEqual(backend.kill_reasons, [TerminationReason.SHUTDOWN])
        final = await store.load(seeded.identity)
        self.assertEqual(
            (final.state, final.revision, final.ownership.fencing_token),
            (BrokerState.FAILED, 6, 3),
        )
        managed = await backend.list_managed(seeded.identity.job_id)
        self.assertEqual((managed.containers, managed.volumes), ((), ()))


if __name__ == "__main__":
    unittest.main()
