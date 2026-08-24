"""Runs the common state-store conformance suite against the memory double."""

import unittest

from backend.app.broker import InMemoryJobStateStore, InMemoryStateStoreBacking

from .state_store_conformance import DurableStateStoreConformanceMixin


class InMemoryStateStoreConformanceTests(
    DurableStateStoreConformanceMixin,
    unittest.IsolatedAsyncioTestCase,
):
    """Fresh handles share only a process-local backing, not durable storage."""

    def setUp(self) -> None:
        self.backing = InMemoryStateStoreBacking()

    def new_store(self) -> InMemoryJobStateStore:
        return InMemoryJobStateStore(self.backing)

    def reopen_store(self) -> InMemoryJobStateStore:
        return InMemoryJobStateStore(self.backing)


if __name__ == "__main__":
    unittest.main()
