"""Fail-closed bridge from durable ownership to runtime fence activation."""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.runtime.errors import RuntimePhase
from backend.app.runtime.fence_authority import RuntimeFenceAuthority
from backend.app.runtime.fencing import RuntimeFencingContext
from backend.app.runtime.models import RuntimeKind

from .state import (
    DurableJobStateStore,
    DurableOperationOwnership,
)


RUNTIME_FENCE_ACTIVATION_PRODUCT_ENABLED = False


@dataclass(frozen=True, slots=True)
class DurableRuntimeFenceActivator:
    """Double-checks durable ownership around monotonic authority activation."""

    store: DurableJobStateStore
    authority: RuntimeFenceAuthority
    backend: RuntimeKind

    def __post_init__(self) -> None:
        if not isinstance(self.store, DurableJobStateStore):
            raise TypeError("DurableRuntimeFenceActivator requires state store.")
        if not isinstance(self.authority, RuntimeFenceAuthority):
            raise TypeError("DurableRuntimeFenceActivator requires fence authority.")
        if not isinstance(self.backend, RuntimeKind):
            raise TypeError("DurableRuntimeFenceActivator requires RuntimeKind.")

    async def activate_owned(
        self,
        ownership: DurableOperationOwnership,
        *,
        expected_revision: int,
        phase: RuntimePhase,
    ) -> RuntimeFencingContext:
        if not isinstance(ownership, DurableOperationOwnership):
            raise TypeError("Runtime fence activation requires ownership.")
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 1
        ):
            raise TypeError("Runtime fence activation revision is invalid.")
        if not isinstance(phase, RuntimePhase):
            raise TypeError("Runtime fence activation requires RuntimePhase.")

        await self.store.verify_ownership(
            ownership,
            expected_revision=expected_revision,
        )
        fence = RuntimeFencingContext(
            ownership.identity,
            ownership.owner_id,
            ownership.fencing_token,
        )
        await self.authority.activate(
            fence,
            phase=phase,
            backend=self.backend,
        )
        await self.store.verify_ownership(
            ownership,
            expected_revision=expected_revision,
        )
        await self.authority.verify(
            fence,
            phase=phase,
            backend=self.backend,
        )
        return fence
