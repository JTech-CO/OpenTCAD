"""Concurrent and already-absent cleanup idempotence tests."""

import asyncio
import unittest

from backend.app.broker import (
    CancellationRequest,
    JobCleanupCoordinator,
    SandboxBroker,
)
from backend.app.runtime.errors import ErrorCode, RuntimeBackendError, RuntimePhase
from backend.app.runtime.mock_backend import MockRuntimeBackend
from backend.app.runtime.models import ContainerHandle, JobIdentity, VolumeHandle
from backend.tests.runtime.support import (
    ARCHIVE,
    ARCHIVE_LIMITS,
    IMAGE,
    POLICY,
    make_spec,
)


class YieldingBackend(MockRuntimeBackend):
    async def list_managed(self, job_id: str | None = None):
        await asyncio.sleep(0)
        return await super().list_managed(job_id)

    async def remove_container(self, container: ContainerHandle) -> None:
        await asyncio.sleep(0)
        await super().remove_container(container)

    async def remove_volume(self, volume: VolumeHandle) -> None:
        await asyncio.sleep(0)
        await super().remove_volume(volume)


class AlreadyAbsentBackend(MockRuntimeBackend):
    async def remove_container(self, container: ContainerHandle) -> None:
        await super().remove_container(container)
        raise RuntimeBackendError(
            ErrorCode.CONTAINER_NOT_FOUND,
            RuntimePhase.CLEANUP,
            backend=self.name.value,
        )

    async def remove_volume(self, volume: VolumeHandle) -> None:
        await super().remove_volume(volume)
        raise RuntimeBackendError(
            ErrorCode.VOLUME_NOT_FOUND,
            RuntimePhase.CLEANUP,
            backend=self.name.value,
        )


class ConcurrentCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def prepare_running(self, backend: MockRuntimeBackend, job_id: str) -> JobIdentity:
        spec = make_spec(job_id)
        validated = POLICY.validate(spec, (await backend.probe()).capabilities)
        volume = await backend.create_volume(validated.identity)
        await backend.stage_inputs(volume, validated, ARCHIVE)
        container = await backend.create_container(validated, volume)
        await backend.start(container)
        return validated.identity

    async def test_shared_coordinator_serializes_concurrent_reconciliation(self) -> None:
        backend = YieldingBackend(images=(IMAGE,))
        job_id = "00000000-0000-4000-8002-000000000001"
        await self.prepare_running(backend, job_id)
        coordinator = JobCleanupCoordinator()
        brokers = tuple(
            SandboxBroker(
                backend,
                POLICY,
                ARCHIVE_LIMITS,
                cleanup_coordinator=coordinator,
            )
            for _ in range(4)
        )

        reports = await asyncio.gather(*(broker.reconcile(job_id) for broker in brokers))

        self.assertTrue(all(report.complete for report in reports))
        self.assertEqual(sum(report.containers_removed for report in reports), 1)
        self.assertEqual(sum(report.volumes_removed for report in reports), 1)
        self.assertEqual((await backend.list_managed(job_id)).containers, ())
        self.assertEqual((await backend.list_managed(job_id)).volumes, ())
        self.assertEqual(coordinator.tracked_jobs, 0)

    async def test_runtime_not_found_after_observed_handle_is_idempotent_success(self) -> None:
        backend = AlreadyAbsentBackend(images=(IMAGE,))
        job_id = "00000000-0000-4000-8002-000000000002"
        await self.prepare_running(backend, job_id)

        report = await SandboxBroker(backend, POLICY, ARCHIVE_LIMITS).reconcile(job_id)

        self.assertTrue(report.complete)
        self.assertEqual(report.containers_removed, 1)
        self.assertEqual(report.volumes_removed, 1)
        self.assertEqual(report.errors, ())

    async def test_concurrent_cancel_and_reconcile_converge_to_zero(self) -> None:
        backend = YieldingBackend(images=(IMAGE,))
        job_id = "00000000-0000-4000-8002-000000000003"
        identity = await self.prepare_running(backend, job_id)
        coordinator = JobCleanupCoordinator()
        broker = SandboxBroker(
            backend,
            POLICY,
            ARCHIVE_LIMITS,
            cleanup_coordinator=coordinator,
        )

        cancellation, reconciliation = await asyncio.gather(
            broker.cancel(CancellationRequest(identity)),
            broker.reconcile(job_id),
        )

        self.assertTrue(cancellation.cleanup_complete)
        self.assertTrue(reconciliation.complete)
        self.assertEqual((await backend.list_managed(job_id)).containers, ())
        self.assertEqual((await backend.list_managed(job_id)).volumes, ())
        self.assertEqual(coordinator.tracked_jobs, 0)


if __name__ == "__main__":
    unittest.main()
