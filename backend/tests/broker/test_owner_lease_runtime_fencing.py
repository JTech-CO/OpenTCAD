"""Owner heartbeat and runtime-adapter fencing enforcement contracts."""

from __future__ import annotations

import asyncio
import unittest

from backend.app.broker import (
    BrokerState,
    DurableJobEvent,
    DurableOperationGuard,
    InMemoryJobStateStore,
    OperationOwnershipError,
    OwnerLeasePolicy,
    StateStoreErrorCode,
)
from backend.app.runtime.errors import ErrorCode, RuntimeBackendError, RuntimePhase
from backend.app.runtime.fencing import RuntimeFencingContext
from backend.app.runtime.mock_backend import MockRuntimeBackend
from backend.app.runtime.models import JobIdentity
from backend.app.runtime.protocol import RuntimeJobBackend
from backend.tests.broker.lease_support import ManualLeaseClock
from backend.tests.broker.state_store_conformance import conformance_event, uuid_at
from backend.tests.runtime.support import IMAGE


class RenewTracingStore:
    def __init__(self, delegate: InMemoryJobStateStore) -> None:
        self.delegate = delegate
        self.renewals = 0
        self.first_renewal = asyncio.Event()
        self.second_renewal = asyncio.Event()

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
        renewed = await self.delegate.renew_ownership(
            ownership,
            expected_revision=expected_revision,
            lease_duration_ms=lease_duration_ms,
        )
        self.renewals += 1
        self.first_renewal.set()
        if self.renewals >= 2:
            self.second_renewal.set()
        return renewed

    async def verify_ownership(self, ownership, *, expected_revision=None):
        return await self.delegate.verify_ownership(
            ownership,
            expected_revision=expected_revision,
        )

    async def scan_recoverable(self, *, after=None, limit=100):
        return await self.delegate.scan_recoverable(after=after, limit=limit)


class OwnerLeaseRuntimeFencingTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    async def committed_guard(
        clock: ManualLeaseClock,
        policy: OwnerLeasePolicy,
    ):
        delegate = InMemoryJobStateStore(clock=clock)
        committed = await delegate.append(
            conformance_event(
                job=701,
                event_number=701,
                operation=701,
                operation_sequence=1,
                state=BrokerState.VALIDATING,
                phase=RuntimePhase.VALIDATE,
                lease_duration_ms=policy.duration_ms,
            ),
            expected_revision=0,
        )
        tracing = RenewTracingStore(delegate)
        return delegate, committed, tracing, DurableOperationGuard(
            tracing,
            committed.ownership,
            committed.revision,
            policy,
        )

    async def test_heartbeat_extends_lease_without_advancing_job_revision(self) -> None:
        clock = ManualLeaseClock()
        policy = OwnerLeasePolicy(duration_ms=20, heartbeat_interval_ms=1)
        delegate, committed, tracing, guard = await self.committed_guard(clock, policy)
        release = asyncio.Event()
        task = asyncio.create_task(
            guard.run_owned(RuntimePhase.WAIT, release.wait),
        )
        await asyncio.wait_for(tracing.first_renewal.wait(), timeout=1)
        clock.advance(5)
        await asyncio.wait_for(tracing.second_renewal.wait(), timeout=1)
        release.set()
        await asyncio.wait_for(task, timeout=1)

        renewed = await delegate.load(committed.identity)
        self.assertEqual(renewed.revision, committed.revision)
        self.assertEqual(renewed.last_event, committed.last_event)
        self.assertGreater(renewed.lease_expires_at_ms, committed.lease_expires_at_ms)
        self.assertGreaterEqual(tracing.renewals, 3)

    async def test_expiry_cancels_an_inflight_owned_operation(self) -> None:
        clock = ManualLeaseClock()
        policy = OwnerLeasePolicy(duration_ms=20, heartbeat_interval_ms=1)
        _, _, tracing, guard = await self.committed_guard(clock, policy)
        operation_cancelled = asyncio.Event()

        async def blocked() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                operation_cancelled.set()

        task = asyncio.create_task(guard.run_owned(RuntimePhase.WAIT, blocked))
        await asyncio.wait_for(tracing.first_renewal.wait(), timeout=1)
        clock.advance(20)
        with self.assertRaises(OperationOwnershipError) as captured:
            await asyncio.wait_for(task, timeout=1)
        self.assertEqual(captured.exception.code, StateStoreErrorCode.LEASE_EXPIRED)
        self.assertEqual(captured.exception.phase, RuntimePhase.WAIT)
        self.assertTrue(operation_cancelled.is_set())

    async def test_bound_runtime_rejects_stale_and_ambiguous_generations(self) -> None:
        backend = MockRuntimeBackend(images=(IMAGE,))
        identity = JobIdentity(uuid_at(10_702))
        first_fence = RuntimeFencingContext(identity, uuid_at(70_201), 1)
        first = backend.bind_job(first_fence)
        self.assertIsInstance(first, RuntimeJobBackend)
        volume = await first.create_volume()

        second_fence = RuntimeFencingContext(identity, uuid_at(70_202), 2)
        second = backend.bind_job(second_fence)
        self.assertEqual((await second.list_managed()).volumes, (volume,))

        with self.assertRaises(RuntimeBackendError) as stale:
            await first.list_managed()
        self.assertEqual(stale.exception.code, ErrorCode.OPERATION_FENCED)
        self.assertEqual(stale.exception.phase, RuntimePhase.QUERY)

        ambiguous = backend.bind_job(
            RuntimeFencingContext(identity, uuid_at(70_203), 2),
        )
        with self.assertRaises(RuntimeBackendError) as same_token:
            await ambiguous.list_managed()
        self.assertEqual(same_token.exception.code, ErrorCode.OPERATION_FENCED)

        await second.remove_volume(volume)
        with self.assertRaises(RuntimeBackendError) as stale_after_cleanup:
            await first.list_managed()
        self.assertEqual(stale_after_cleanup.exception.code, ErrorCode.OPERATION_FENCED)

    async def test_bound_runtime_rejects_cross_job_handle_context(self) -> None:
        backend = MockRuntimeBackend(images=(IMAGE,))
        first_identity = JobIdentity(uuid_at(10_703))
        second_identity = JobIdentity(uuid_at(10_704))
        first = backend.bind_job(
            RuntimeFencingContext(first_identity, uuid_at(70_301), 1),
        )
        volume = await first.create_volume()
        other = backend.bind_job(
            RuntimeFencingContext(second_identity, uuid_at(70_302), 1),
        )
        with self.assertRaises(RuntimeBackendError) as mismatch:
            await other.remove_volume(volume)
        self.assertEqual(mismatch.exception.code, ErrorCode.IDENTITY_MISMATCH)
        self.assertEqual(
            first.fence.labels,
            (
                ("tcad.job_id", first_identity.job_id),
                ("tcad.owner_id", uuid_at(70_301)),
                ("tcad.fencing_token", "1"),
            ),
        )


if __name__ == "__main__":
    unittest.main()
