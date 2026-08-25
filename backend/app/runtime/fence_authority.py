"""Runtime-level fencing authority contract with a process-local test candidate."""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

from .errors import ErrorCode, RetryDisposition, RuntimeBackendError, RuntimePhase
from .fencing import RuntimeFencingContext
from .models import RuntimeKind


RUNTIME_FENCE_AUTHORITY_PRODUCT_ENABLED = False


@runtime_checkable
class RuntimeFenceAuthority(Protocol):
    """Highest-generation authority consulted around every native operation."""

    async def activate(
        self,
        fence: RuntimeFencingContext,
        *,
        phase: RuntimePhase,
        backend: RuntimeKind,
    ) -> None: ...

    async def verify(
        self,
        fence: RuntimeFencingContext,
        *,
        phase: RuntimePhase,
        backend: RuntimeKind,
    ) -> None: ...


def _validate_request(
    fence: RuntimeFencingContext,
    phase: RuntimePhase,
    backend: RuntimeKind,
) -> None:
    if not isinstance(fence, RuntimeFencingContext):
        raise TypeError("Runtime fence authority requires RuntimeFencingContext.")
    if not isinstance(phase, RuntimePhase):
        raise TypeError("Runtime fence authority requires RuntimePhase.")
    if not isinstance(backend, RuntimeKind):
        raise TypeError("Runtime fence authority requires RuntimeKind.")


def _fenced(phase: RuntimePhase, backend: RuntimeKind) -> None:
    raise RuntimeBackendError(
        ErrorCode.OPERATION_FENCED,
        phase,
        retry=RetryDisposition.INFRASTRUCTURE,
        backend=backend.value,
        detail="runtime-fence-authority-rejected",
    )


class InMemoryRuntimeFenceAuthority:
    """Shared process-local reference authority for adapter conformance tests."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._current: dict[str, RuntimeFencingContext] = {}

    async def activate(
        self,
        fence: RuntimeFencingContext,
        *,
        phase: RuntimePhase,
        backend: RuntimeKind,
    ) -> None:
        _validate_request(fence, phase, backend)
        async with self._lock:
            current = self._current.get(fence.identity.job_id)
            if current is not None and (
                fence.fencing_token < current.fencing_token
                or (
                    fence.fencing_token == current.fencing_token
                    and fence.owner_id != current.owner_id
                )
            ):
                _fenced(phase, backend)
            if current is None or fence.fencing_token > current.fencing_token:
                self._current[fence.identity.job_id] = fence

    async def verify(
        self,
        fence: RuntimeFencingContext,
        *,
        phase: RuntimePhase,
        backend: RuntimeKind,
    ) -> None:
        _validate_request(fence, phase, backend)
        async with self._lock:
            if self._current.get(fence.identity.job_id) != fence:
                _fenced(phase, backend)

    async def current(self, job_id: str) -> RuntimeFencingContext | None:
        if not isinstance(job_id, str):
            raise TypeError("Runtime fence job ID must be text.")
        async with self._lock:
            return self._current.get(job_id)
