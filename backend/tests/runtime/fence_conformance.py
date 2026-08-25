"""Reusable job-bound runtime fencing conformance cases."""

from __future__ import annotations

from backend.app.runtime.errors import ErrorCode, RuntimeBackendError
from backend.app.runtime.fence_authority import (
    InMemoryRuntimeFenceAuthority,
    RuntimeFenceAuthority,
)
from backend.app.runtime.fencing import RuntimeFencingContext
from backend.app.runtime.models import JobIdentity, TerminationReason
from backend.app.runtime.protocol import RuntimeBackend, RuntimeJobBackend

from .support import ARCHIVE, IMAGE, POLICY, make_spec


class RuntimeFenceConformanceMixin:
    """Common cases that every future product adapter must inherit unchanged."""

    def make_backend(
        self,
        authority: RuntimeFenceAuthority,
    ) -> RuntimeBackend:
        raise NotImplementedError

    @staticmethod
    def context(job_id: str, owner_suffix: int, token: int) -> RuntimeFencingContext:
        return RuntimeFencingContext(
            JobIdentity(job_id),
            f"00000000-0000-4000-8000-{owner_suffix:012d}",
            token,
        )

    async def prepare(
        self,
        backend: RuntimeBackend,
        fence: RuntimeFencingContext,
    ):
        capabilities = (await backend.probe()).capabilities
        validated = POLICY.validate(make_spec(fence.identity.job_id), capabilities)
        await backend.ensure_image(IMAGE)
        runtime = backend.bind_job(fence)
        self.assertIsInstance(runtime, RuntimeJobBackend)
        volume = await runtime.create_volume()
        await runtime.stage_inputs(volume, validated, ARCHIVE)
        container = await runtime.create_container(validated, volume)
        return runtime, volume, container

    async def test_bound_objects_persist_and_inspect_exact_fence(self) -> None:
        authority = InMemoryRuntimeFenceAuthority()
        backend = self.make_backend(authority)
        fence = self.context("00000000-0000-4000-8000-000000000700", 701, 1)
        runtime, volume, container = await self.prepare(backend, fence)

        self.assertEqual(await runtime.inspect_fence(volume), fence)
        self.assertEqual(await runtime.inspect_fence(container), fence)
        self.assertEqual(dict((await runtime.inspect_fence(volume)).labels), dict(fence.labels))

        await runtime.remove_container(container)
        await runtime.remove_volume(volume)

    async def test_shared_authority_fences_an_older_backend_instance(self) -> None:
        authority = InMemoryRuntimeFenceAuthority()
        first = self.make_backend(authority)
        second = self.make_backend(authority)
        job_id = "00000000-0000-4000-8000-000000000710"
        first_fence = self.context(job_id, 711, 1)
        second_fence = self.context(job_id, 712, 2)

        await first.bind_job(first_fence).list_managed()
        await second.bind_job(second_fence).list_managed()

        with self.assertRaises(RuntimeBackendError) as stale:
            await first.bind_job(first_fence).list_managed()
        self.assertEqual(stale.exception.code, ErrorCode.OPERATION_FENCED)
        self.assertEqual(await authority.current(job_id), second_fence)

    async def test_same_token_with_another_owner_fails_closed(self) -> None:
        authority = InMemoryRuntimeFenceAuthority()
        backend = self.make_backend(authority)
        job_id = "00000000-0000-4000-8000-000000000720"
        first = self.context(job_id, 721, 4)
        ambiguous = self.context(job_id, 722, 4)

        await backend.bind_job(first).list_managed()
        with self.assertRaises(RuntimeBackendError) as rejected:
            await backend.bind_job(ambiguous).list_managed()
        self.assertEqual(rejected.exception.code, ErrorCode.OPERATION_FENCED)

    async def test_takeover_can_only_query_kill_and_clean_predecessor_objects(self) -> None:
        authority = InMemoryRuntimeFenceAuthority()
        backend = self.make_backend(authority)
        job_id = "00000000-0000-4000-8000-000000000730"
        first = self.context(job_id, 731, 1)
        takeover = self.context(job_id, 732, 2)
        first_runtime, volume, container = await self.prepare(backend, first)
        await first_runtime.start(container)

        takeover_runtime = backend.bind_job(takeover)
        managed = await takeover_runtime.list_managed()
        self.assertEqual(managed.containers, (container,))
        self.assertEqual(await takeover_runtime.inspect_fence(container), first)
        with self.assertRaises(RuntimeBackendError) as continued:
            await takeover_runtime.wait(container)
        self.assertEqual(continued.exception.code, ErrorCode.OPERATION_FENCED)

        await takeover_runtime.kill(container, TerminationReason.CANCELLATION)
        await takeover_runtime.remove_container(container)
        await takeover_runtime.remove_volume(volume)
        self.assertEqual((await takeover_runtime.list_managed()).containers, ())
        self.assertEqual((await takeover_runtime.list_managed()).volumes, ())

    async def test_cross_job_fence_cannot_inspect_or_mutate_a_handle(self) -> None:
        authority = InMemoryRuntimeFenceAuthority()
        backend = self.make_backend(authority)
        first = self.context("00000000-0000-4000-8000-000000000740", 741, 1)
        other = self.context("00000000-0000-4000-8000-000000000750", 751, 1)
        first_runtime, volume, container = await self.prepare(backend, first)
        other_runtime = backend.bind_job(other)

        with self.assertRaises(RuntimeBackendError) as inspected:
            await other_runtime.inspect_fence(container)
        self.assertEqual(inspected.exception.code, ErrorCode.IDENTITY_MISMATCH)
        with self.assertRaises(RuntimeBackendError) as removed:
            await other_runtime.remove_volume(volume)
        self.assertEqual(removed.exception.code, ErrorCode.IDENTITY_MISMATCH)

        await first_runtime.remove_container(container)
        await first_runtime.remove_volume(volume)
