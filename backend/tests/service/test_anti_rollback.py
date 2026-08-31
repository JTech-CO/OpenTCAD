from __future__ import annotations

import unittest
from uuid import uuid4

from backend.app.service.anti_rollback import (
    AntiRollbackError,
    AntiRollbackErrorCode,
    NativeRestoreFloorStore,
)
from backend.app.service.credentials import InMemoryCredentialStore


class NativeAntiRollbackFloorTests(unittest.TestCase):
    def test_floor_is_monotonic_idempotent_and_outside_sqlite(self) -> None:
        credentials = InMemoryCredentialStore()
        store = NativeRestoreFloorStore(credentials)
        source = str(uuid4())
        first_snapshot = str(uuid4())
        second_snapshot = str(uuid4())
        first = store.advance(
            source,
            first_snapshot,
            4,
            requested_minimum_sequence=1,
        )
        self.assertEqual(first.minimum_snapshot_sequence, 4)
        self.assertEqual(
            store.advance(
                source,
                first_snapshot,
                4,
                requested_minimum_sequence=4,
            ),
            first,
        )
        with self.assertRaises(AntiRollbackError) as rollback:
            store.advance(
                source,
                str(uuid4()),
                3,
                requested_minimum_sequence=1,
            )
        self.assertEqual(
            rollback.exception.code,
            AntiRollbackErrorCode.ROLLBACK_REJECTED,
        )
        with self.assertRaises(AntiRollbackError) as conflict:
            store.advance(
                source,
                second_snapshot,
                4,
                requested_minimum_sequence=1,
            )
        self.assertEqual(
            conflict.exception.code,
            AntiRollbackErrorCode.FLOOR_CONFLICT,
        )
        advanced = store.advance(
            source,
            second_snapshot,
            5,
            requested_minimum_sequence=1,
        )
        self.assertEqual(advanced.minimum_snapshot_sequence, 5)


if __name__ == "__main__":
    unittest.main()
