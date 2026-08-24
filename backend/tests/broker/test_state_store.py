"""Durable state interface, CAS, idempotency, and recovery scan tests."""

import asyncio
from dataclasses import fields
import json
import unittest
from uuid import UUID

from backend.app.broker import (
    BrokerState,
    DurableJobEvent,
    DurableJobStateStore,
    InMemoryJobStateStore,
    StateStoreError,
    StateStoreErrorCode,
)
from backend.app.runtime.errors import ErrorCode, RetryDisposition, RuntimePhase
from backend.app.runtime.models import (
    JobIdentity,
    RuntimeKind,
    TerminalClassification,
)


def uuid_at(value: int) -> str:
    return str(UUID(int=value))


def event(
    job: int,
    event_number: int,
    state: BrokerState,
    phase: RuntimePhase,
    *,
    operation: int = 1,
    code: ErrorCode | None = None,
    classification: TerminalClassification | None = None,
) -> DurableJobEvent:
    return DurableJobEvent(
        identity=JobIdentity(uuid_at(10_000 + job)),
        event_id=uuid_at(100_000 + event_number),
        operation_id=uuid_at(200_000 + operation),
        state=state,
        phase=phase,
        code=code,
        retry=RetryDisposition.NEVER if code is not None else None,
        backend=RuntimeKind.MOCK,
        classification=(
            TerminalClassification.SUCCEEDED
            if state in {BrokerState.COLLECTING, BrokerState.SUCCEEDED}
            else TerminalClassification.CANCELLED
            if state is BrokerState.CANCELLED
            else classification
        ),
        cleanup_complete=state
        in {BrokerState.SUCCEEDED, BrokerState.CANCELLED, BrokerState.FAILED},
    )


class DurableStateContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_protocol_and_monotonic_success_path(self) -> None:
        store = InMemoryJobStateStore()
        self.assertIsInstance(store, DurableJobStateStore)
        transitions = (
            (BrokerState.VALIDATING, RuntimePhase.VALIDATE),
            (BrokerState.PREPARING, RuntimePhase.IMAGE),
            (BrokerState.RUNNING, RuntimePhase.WAIT),
            (BrokerState.COLLECTING, RuntimePhase.ARTIFACT),
            (BrokerState.CLEANING, RuntimePhase.CLEANUP),
            (BrokerState.SUCCEEDED, RuntimePhase.WAIT),
        )
        snapshot = None
        for index, (state, phase) in enumerate(transitions, start=1):
            snapshot = await store.append(
                event(1, index, state, phase),
                expected_revision=index - 1,
            )
            self.assertEqual(snapshot.revision, index)
            self.assertEqual(snapshot.state, state)
        self.assertFalse(snapshot.recoverable)
        self.assertEqual(await store.load(snapshot.identity), snapshot)

    async def test_identical_event_replay_is_idempotent(self) -> None:
        store = InMemoryJobStateStore()
        first_event = event(2, 20, BrokerState.VALIDATING, RuntimePhase.VALIDATE)
        first = await store.append(first_event, expected_revision=0)
        replay = await store.append(first_event, expected_revision=999)
        self.assertEqual(replay, first)
        self.assertEqual((await store.load(first_event.identity)).revision, 1)

    async def test_event_id_reuse_with_different_content_fails_closed(self) -> None:
        store = InMemoryJobStateStore()
        first_event = event(3, 30, BrokerState.VALIDATING, RuntimePhase.VALIDATE)
        await store.append(first_event, expected_revision=0)
        conflicting = DurableJobEvent(
            identity=first_event.identity,
            event_id=first_event.event_id,
            operation_id=uuid_at(300_001),
            state=BrokerState.PREPARING,
            phase=RuntimePhase.IMAGE,
        )
        with self.assertRaises(StateStoreError) as captured:
            await store.append(conflicting, expected_revision=1)
        self.assertEqual(captured.exception.code, StateStoreErrorCode.EVENT_CONFLICT)

    async def test_concurrent_compare_and_swap_allows_exactly_one_writer(self) -> None:
        store = InMemoryJobStateStore()
        await store.append(
            event(4, 40, BrokerState.VALIDATING, RuntimePhase.VALIDATE),
            expected_revision=0,
        )
        candidates = (
            event(4, 41, BrokerState.PREPARING, RuntimePhase.IMAGE, operation=41),
            event(4, 42, BrokerState.CANCELLING, RuntimePhase.KILL, operation=42),
        )
        results = await asyncio.gather(
            *(store.append(item, expected_revision=1) for item in candidates),
            return_exceptions=True,
        )
        snapshots = [item for item in results if not isinstance(item, Exception)]
        failures = [item for item in results if isinstance(item, StateStoreError)]
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].code, StateStoreErrorCode.REVISION_CONFLICT)
        self.assertEqual((await store.load(candidates[0].identity)).revision, 2)

    async def test_invalid_transition_and_terminal_mutation_are_rejected(self) -> None:
        store = InMemoryJobStateStore()
        with self.assertRaises(StateStoreError) as invalid_initial:
            await store.append(
                event(5, 50, BrokerState.RUNNING, RuntimePhase.WAIT),
                expected_revision=0,
            )
        self.assertEqual(
            invalid_initial.exception.code,
            StateStoreErrorCode.INVALID_TRANSITION,
        )

        await store.append(
            event(5, 51, BrokerState.VALIDATING, RuntimePhase.VALIDATE),
            expected_revision=0,
        )
        await store.append(
            event(5, 52, BrokerState.CLEANING, RuntimePhase.CLEANUP),
            expected_revision=1,
        )
        await store.append(
            event(
                5,
                53,
                BrokerState.FAILED,
                RuntimePhase.WAIT,
                code=ErrorCode.WAIT_FAILED,
            ),
            expected_revision=2,
        )
        with self.assertRaises(StateStoreError) as terminal:
            await store.append(
                event(5, 54, BrokerState.CLEANING, RuntimePhase.CLEANUP),
                expected_revision=3,
            )
        self.assertEqual(terminal.exception.code, StateStoreErrorCode.INVALID_TRANSITION)

    async def test_recovery_scan_is_bounded_paginated_and_excludes_terminal_jobs(self) -> None:
        store = InMemoryJobStateStore()
        for job in (6, 7, 8):
            await store.append(
                event(job, 60 + job, BrokerState.VALIDATING, RuntimePhase.VALIDATE),
                expected_revision=0,
            )
        await store.append(
            event(9, 69, BrokerState.VALIDATING, RuntimePhase.VALIDATE),
            expected_revision=0,
        )
        await store.append(
            event(9, 79, BrokerState.CLEANING, RuntimePhase.CLEANUP),
            expected_revision=1,
        )
        await store.append(
            event(9, 89, BrokerState.SUCCEEDED, RuntimePhase.WAIT),
            expected_revision=2,
        )

        first = await store.scan_recoverable(limit=2)
        second = await store.scan_recoverable(after=first.next_cursor, limit=2)
        self.assertEqual(len(first.items), 2)
        self.assertIsNotNone(first.next_cursor)
        self.assertEqual(len(second.items), 1)
        self.assertIsNone(second.next_cursor)
        self.assertEqual(
            {item.identity.job_id for item in (*first.items, *second.items)},
            {uuid_at(10_006), uuid_at(10_007), uuid_at(10_008)},
        )

    async def test_persisted_shape_is_redacted_and_terminal_requires_cleanup(self) -> None:
        public_event = event(
            10,
            100,
            BrokerState.VALIDATING,
            RuntimePhase.VALIDATE,
        )
        names = {field.name for field in fields(DurableJobEvent)}
        self.assertNotIn("detail", names)
        self.assertNotIn("payload", names)
        self.assertNotIn("host_path", names)
        self.assertIn("retry", names)
        self.assertIn("backend", names)
        self.assertIn("classification", names)
        public = json.dumps(public_event.as_dict(), sort_keys=True)
        self.assertNotIn("detail", public)
        self.assertNotIn("payload", public)

        with self.assertRaises(StateStoreError) as captured:
            DurableJobEvent(
                identity=public_event.identity,
                event_id=uuid_at(100_101),
                operation_id=uuid_at(200_101),
                state=BrokerState.CANCELLED,
                phase=RuntimePhase.CLEANUP,
                cleanup_complete=False,
            )
        self.assertEqual(captured.exception.code, StateStoreErrorCode.INVALID_EVENT)


if __name__ == "__main__":
    unittest.main()
