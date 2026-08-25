"""Reusable monotonic runtime fence authority conformance cases."""

from __future__ import annotations

import asyncio

from backend.app.runtime.errors import ErrorCode, RuntimeBackendError, RuntimePhase
from backend.app.runtime.fence_authority import RuntimeFenceAuthority
from backend.app.runtime.fencing import RuntimeFencingContext
from backend.app.runtime.models import JobIdentity, RuntimeKind


class RuntimeFenceAuthorityConformanceMixin:
    """Common cases for process-local and durable authority implementations."""

    def make_authority(self) -> RuntimeFenceAuthority:
        raise NotImplementedError

    @staticmethod
    def context(job_suffix: int, owner_suffix: int, token: int):
        return RuntimeFencingContext(
            JobIdentity(f"00000000-0000-4000-8000-{job_suffix:012d}"),
            f"00000000-0000-4000-8000-{owner_suffix:012d}",
            token,
        )

    @staticmethod
    async def activate(
        authority: RuntimeFenceAuthority,
        fence: RuntimeFencingContext,
    ) -> None:
        await authority.activate(
            fence,
            phase=RuntimePhase.QUERY,
            backend=RuntimeKind.MOCK,
        )

    async def test_authority_requires_activation_and_accepts_exact_replay(self) -> None:
        authority = self.make_authority()
        fence = self.context(810, 811, 1)
        with self.assertRaises(RuntimeBackendError) as absent:
            await authority.verify(
                fence,
                phase=RuntimePhase.QUERY,
                backend=RuntimeKind.MOCK,
            )
        self.assertEqual(absent.exception.code, ErrorCode.OPERATION_FENCED)

        await self.activate(authority, fence)
        await self.activate(authority, fence)
        await authority.verify(
            fence,
            phase=RuntimePhase.QUERY,
            backend=RuntimeKind.MOCK,
        )

    async def test_authority_higher_generation_permanently_fences_lower(self) -> None:
        authority = self.make_authority()
        lower = self.context(820, 821, 4)
        higher = self.context(820, 822, 5)
        await self.activate(authority, lower)
        await self.activate(authority, higher)

        for operation in (self.activate,):
            with self.subTest(operation=operation.__name__):
                with self.assertRaises(RuntimeBackendError) as stale:
                    await operation(authority, lower)
                self.assertEqual(stale.exception.code, ErrorCode.OPERATION_FENCED)
        with self.assertRaises(RuntimeBackendError) as stale_verify:
            await authority.verify(
                lower,
                phase=RuntimePhase.QUERY,
                backend=RuntimeKind.MOCK,
            )
        self.assertEqual(stale_verify.exception.code, ErrorCode.OPERATION_FENCED)

    async def test_authority_rejects_same_token_owner_ambiguity(self) -> None:
        authority = self.make_authority()
        first = self.context(830, 831, 7)
        ambiguous = self.context(830, 832, 7)
        await self.activate(authority, first)
        with self.assertRaises(RuntimeBackendError) as rejected:
            await self.activate(authority, ambiguous)
        self.assertEqual(rejected.exception.code, ErrorCode.OPERATION_FENCED)

    async def test_authority_serializes_concurrent_generations(self) -> None:
        authority = self.make_authority()
        fences = tuple(
            self.context(840, 840 + token, token)
            for token in range(1, 7)
        )
        results = await asyncio.gather(
            *(self.activate(authority, fence) for fence in reversed(fences)),
            return_exceptions=True,
        )
        self.assertTrue(
            all(
                result is None
                or (
                    isinstance(result, RuntimeBackendError)
                    and result.code is ErrorCode.OPERATION_FENCED
                )
                for result in results
            ),
        )
        await authority.verify(
            fences[-1],
            phase=RuntimePhase.QUERY,
            backend=RuntimeKind.MOCK,
        )
