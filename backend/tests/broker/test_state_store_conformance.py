"""Runs the common state-store conformance suite against the memory double."""

import unittest

from backend.app.broker import InMemoryJobStateStore, InMemoryStateStoreBacking

from .lease_support import ManualLeaseClock
from .state_store_conformance import DurableStateStoreConformanceMixin


class InMemoryStateStoreConformanceTests(
    DurableStateStoreConformanceMixin,
    unittest.IsolatedAsyncioTestCase,
):
    """Fresh handles share only a process-local backing, not durable storage."""

    def setUp(self) -> None:
        self.clock = ManualLeaseClock()
        self.backing = InMemoryStateStoreBacking(self.clock)

    def new_store(self) -> InMemoryJobStateStore:
        return InMemoryJobStateStore(self.backing)

    def reopen_store(self) -> InMemoryJobStateStore:
        return InMemoryJobStateStore(self.backing)

    def advance_lease_clock(self, milliseconds: int) -> None:
        self.clock.advance(milliseconds)


if __name__ == "__main__":
    unittest.main()
