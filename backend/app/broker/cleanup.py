"""Process-local serialization for idempotent job cleanup attempts."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from backend.app.runtime.models import JobIdentity


@dataclass(slots=True)
class _LeaseEntry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class JobCleanupCoordinator:
    """Serializes cleanup per job within one process without claiming durability."""

    def __init__(self) -> None:
        self._guard = asyncio.Lock()
        self._entries: dict[str, _LeaseEntry] = {}

    @asynccontextmanager
    async def lease(self, identity: JobIdentity) -> AsyncIterator[None]:
        if not isinstance(identity, JobIdentity):
            raise TypeError("Cleanup lease requires JobIdentity.")
        async with self._guard:
            entry = self._entries.setdefault(identity.job_id, _LeaseEntry())
            entry.users += 1
        try:
            async with entry.lock:
                yield
        finally:
            async with self._guard:
                entry.users -= 1
                if entry.users == 0 and self._entries.get(identity.job_id) is entry:
                    del self._entries[identity.job_id]

    @property
    def tracked_jobs(self) -> int:
        """Diagnostic count used to prove that completed leases are released."""

        return len(self._entries)
