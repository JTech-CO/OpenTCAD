"""Concrete and focused native-object runtime fencing contract tests."""

from __future__ import annotations

import asyncio
import unittest

from backend.app.runtime.errors import ErrorCode, RuntimeBackendError, RuntimePhase
from backend.app.runtime.fence_authority import InMemoryRuntimeFenceAuthority
from backend.app.runtime.fencing import RuntimeFencingContext
from backend.app.runtime.mock_backend import MockRuntimeBackend
from backend.app.runtime.models import ContainerHandle, RuntimeKind

from .fence_conformance import RuntimeFenceConformanceMixin
from .support import ARCHIVE, IMAGE, POLICY, make_spec


class MockRuntimeFenceConformanceTests(
    RuntimeFenceConformanceMixin,
    unittest.IsolatedAsyncioTestCase,
):
    def make_backend(self, authority):
        return MockRuntimeBackend(images=(IMAGE,), fence_authority=authority)


class PostMutationBarrierBackend(MockRuntimeBackend):
    def __init__(self, authority: InMemoryRuntimeFenceAuthority) -> None:
        super().__init__(images=(IMAGE,), fence_authority=authority)
        self.mutated = asyncio.Event()
        self.release = asyncio.Event()

    async def wait(self, container: ContainerHandle):
        result = await super().wait(container)
        self.mutated.set()
        await self.release.wait()
        return result


class RuntimeFenceAuthorityFocusedTests(unittest.IsolatedAsyncioTestCase):
    def context(self, job_suffix: int, owner_suffix: int, token: int):
        return RuntimeFenceConformanceMixin.context(
            f"00000000-0000-4000-8000-{job_suffix:012d}",
            owner_suffix,
            token,
        )

    async def test_label_parser_rejects_missing_noncanonical_and_invalid_values(self) -> None:
        valid = self.context(760, 761, 3)
        self.assertEqual(RuntimeFencingContext.from_labels(dict(valid.labels)), valid)

        invalid_labels = (
            {"tcad.job_id": valid.identity.job_id},
            {**dict(valid.labels), "tcad.fencing_token": "03"},
            {**dict(valid.labels), "tcad.fencing_token": "0"},
            {
                **dict(valid.labels),
                "tcad.owner_id": "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
            },
        )
        for labels in invalid_labels:
            with self.subTest(labels=labels):
                with self.assertRaises(RuntimeBackendError) as rejected:
                    RuntimeFencingContext.from_labels(labels)
                self.assertEqual(rejected.exception.code, ErrorCode.INVALID_SPEC)

    async def test_verify_requires_prior_activation(self) -> None:
        authority = InMemoryRuntimeFenceAuthority()
        fence = self.context(770, 771, 1)
        with self.assertRaises(RuntimeBackendError) as rejected:
            await authority.verify(
                fence,
                phase=RuntimePhase.QUERY,
                backend=RuntimeKind.MOCK,
            )
        self.assertEqual(rejected.exception.code, ErrorCode.OPERATION_FENCED)

    async def test_completed_stale_native_result_is_suppressed_then_converged(self) -> None:
        authority = InMemoryRuntimeFenceAuthority()
        backend = PostMutationBarrierBackend(authority)
        first = self.context(780, 781, 1)
        takeover = self.context(780, 782, 2)
        capabilities = (await backend.probe()).capabilities
        validated = POLICY.validate(make_spec(first.identity.job_id), capabilities)
        await backend.ensure_image(IMAGE)
        first_runtime = backend.bind_job(first)
        volume = await first_runtime.create_volume()
        await first_runtime.stage_inputs(volume, validated, ARCHIVE)
        container = await first_runtime.create_container(validated, volume)
        await first_runtime.start(container)

        stale_wait = asyncio.create_task(first_runtime.wait(container))
        await backend.mutated.wait()
        takeover_runtime = backend.bind_job(takeover)
        self.assertEqual((await takeover_runtime.list_managed()).containers, (container,))
        backend.release.set()

        with self.assertRaises(RuntimeBackendError) as rejected:
            await stale_wait
        self.assertEqual(rejected.exception.code, ErrorCode.OPERATION_FENCED)
        await takeover_runtime.remove_container(container)
        await takeover_runtime.remove_volume(volume)
        managed = await takeover_runtime.list_managed()
        self.assertEqual(managed.containers, ())
        self.assertEqual(managed.volumes, ())


if __name__ == "__main__":
    unittest.main()
