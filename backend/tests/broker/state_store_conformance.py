"""Reusable durable-state adapter conformance tests.

Concrete adapters provide ``new_store`` and ``reopen_store``. Importing this
module does not register a standalone test case.
"""

import asyncio
from uuid import UUID

from backend.app.broker import (
    BrokerState,
    DurableJobEvent,
    DurableJobStateStore,
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


def conformance_event(
    *,
    job: int,
    event_number: int,
    operation: int,
    operation_sequence: int,
    state: BrokerState,
    phase: RuntimePhase,
    code: ErrorCode | None = None,
    owner: int | None = None,
    fencing_token: int = 1,
) -> DurableJobEvent:
    terminal = state in {
        BrokerState.SUCCEEDED,
        BrokerState.CANCELLED,
        BrokerState.FAILED,
    }
    classification = (
        TerminalClassification.SUCCEEDED
        if state in {BrokerState.COLLECTING, BrokerState.SUCCEEDED}
        else TerminalClassification.CANCELLED
        if state is BrokerState.CANCELLED
        else None
    )
    return DurableJobEvent(
        identity=JobIdentity(uuid_at(10_000 + job)),
        event_id=uuid_at(100_000 + event_number),
        operation_id=uuid_at(200_000 + operation),
        operation_sequence=operation_sequence,
        owner_id=uuid_at(300_000 + (operation if owner is None else owner)),
        fencing_token=fencing_token,
        state=state,
        phase=phase,
        code=code,
        retry=RetryDisposition.INFRASTRUCTURE if code is not None else None,
        backend=RuntimeKind.MOCK,
        classification=classification,
        cleanup_complete=terminal,
    )


class DurableStateStoreConformanceMixin:
    """Behavior every future durable adapter must pass unchanged."""

    def new_store(self) -> DurableJobStateStore:
        raise NotImplementedError

    def reopen_store(self) -> DurableJobStateStore:
        raise NotImplementedError

    async def test_protocol_empty_load_and_scan(self) -> None:
        store = self.new_store()
        self.assertIsInstance(store, DurableJobStateStore)
        identity = JobIdentity(uuid_at(10_001))
        self.assertIsNone(await store.load(identity))
        page = await store.scan_recoverable(limit=1)
        self.assertEqual(page.items, ())
        self.assertIsNone(page.next_cursor)

    async def test_monotonic_commit_is_visible_after_adapter_reopen(self) -> None:
        store = self.new_store()
        path = (
            (BrokerState.VALIDATING, RuntimePhase.VALIDATE),
            (BrokerState.PREPARING, RuntimePhase.IMAGE),
            (BrokerState.RUNNING, RuntimePhase.WAIT),
            (BrokerState.CLEANING, RuntimePhase.CLEANUP),
            (BrokerState.FAILED, RuntimePhase.WAIT),
        )
        snapshot = None
        for sequence, (state, phase) in enumerate(path, start=1):
            snapshot = await store.append(
                conformance_event(
                    job=2,
                    event_number=sequence,
                    operation=2,
                    operation_sequence=sequence,
                    state=state,
                    phase=phase,
                    code=ErrorCode.WAIT_FAILED if state is BrokerState.FAILED else None,
                ),
                expected_revision=sequence - 1,
            )
        reopened = self.reopen_store()
        self.assertEqual(await reopened.load(snapshot.identity), snapshot)
        self.assertFalse(snapshot.recoverable)

    async def test_identical_event_replay_survives_adapter_reopen(self) -> None:
        store = self.new_store()
        item = conformance_event(
            job=3,
            event_number=30,
            operation=3,
            operation_sequence=1,
            state=BrokerState.VALIDATING,
            phase=RuntimePhase.VALIDATE,
        )
        committed = await store.append(item, expected_revision=0)
        replayed = await self.reopen_store().append(item, expected_revision=999)
        self.assertEqual(replayed, committed)

    async def test_event_id_and_operation_slot_conflicts_fail_closed(self) -> None:
        store = self.new_store()
        first = conformance_event(
            job=4,
            event_number=40,
            operation=4,
            operation_sequence=1,
            state=BrokerState.VALIDATING,
            phase=RuntimePhase.VALIDATE,
        )
        await store.append(first, expected_revision=0)
        reused_id = DurableJobEvent(
            identity=first.identity,
            event_id=first.event_id,
            operation_id=uuid_at(299_001),
            operation_sequence=1,
            owner_id=uuid_at(399_001),
            fencing_token=2,
            state=BrokerState.PREPARING,
            phase=RuntimePhase.IMAGE,
        )
        with self.assertRaises(StateStoreError) as event_conflict:
            await store.append(reused_id, expected_revision=1)
        self.assertEqual(event_conflict.exception.code, StateStoreErrorCode.EVENT_CONFLICT)

        reused_slot = DurableJobEvent(
            identity=first.identity,
            event_id=uuid_at(199_002),
            operation_id=first.operation_id,
            operation_sequence=first.operation_sequence,
            owner_id=first.owner_id,
            fencing_token=first.fencing_token,
            state=BrokerState.PREPARING,
            phase=RuntimePhase.IMAGE,
        )
        with self.assertRaises(StateStoreError) as slot_conflict:
            await store.append(reused_slot, expected_revision=1)
        self.assertEqual(slot_conflict.exception.code, StateStoreErrorCode.EVENT_CONFLICT)

    async def test_concurrent_cas_allows_exactly_one_writer(self) -> None:
        store = self.new_store()
        await store.append(
            conformance_event(
                job=5,
                event_number=50,
                operation=5,
                operation_sequence=1,
                state=BrokerState.VALIDATING,
                phase=RuntimePhase.VALIDATE,
            ),
            expected_revision=0,
        )
        candidates = (
            conformance_event(
                job=5,
                event_number=51,
                operation=5,
                operation_sequence=2,
                state=BrokerState.PREPARING,
                phase=RuntimePhase.IMAGE,
            ),
            conformance_event(
                job=5,
                event_number=52,
                operation=52,
                operation_sequence=1,
                state=BrokerState.CANCELLING,
                phase=RuntimePhase.KILL,
                fencing_token=2,
            ),
        )
        results = await asyncio.gather(
            *(store.append(item, expected_revision=1) for item in candidates),
            return_exceptions=True,
        )
        self.assertEqual(sum(not isinstance(item, Exception) for item in results), 1)
        failures = [item for item in results if isinstance(item, StateStoreError)]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].code, StateStoreErrorCode.REVISION_CONFLICT)

    async def test_owner_takeover_fences_stale_token_after_reopen(self) -> None:
        store = self.new_store()
        first = await store.append(
            conformance_event(
                job=9,
                event_number=90,
                operation=9,
                operation_sequence=1,
                state=BrokerState.VALIDATING,
                phase=RuntimePhase.VALIDATE,
            ),
            expected_revision=0,
        )
        original = first.ownership
        self.assertEqual(original.fencing_token, 1)
        self.assertEqual(
            await self.reopen_store().verify_ownership(
                original,
                expected_revision=1,
            ),
            first,
        )

        takeover = await self.reopen_store().append(
            conformance_event(
                job=9,
                event_number=91,
                operation=91,
                operation_sequence=1,
                state=BrokerState.CANCELLING,
                phase=RuntimePhase.QUERY,
                fencing_token=2,
            ),
            expected_revision=1,
        )
        self.assertEqual(takeover.ownership.fencing_token, 2)
        self.assertNotEqual(takeover.ownership.owner_id, original.owner_id)

        with self.assertRaises(StateStoreError) as verify_error:
            await self.reopen_store().verify_ownership(
                original,
                expected_revision=1,
            )
        self.assertEqual(
            verify_error.exception.code,
            StateStoreErrorCode.OWNERSHIP_CONFLICT,
        )

        stale = conformance_event(
            job=9,
            event_number=92,
            operation=9,
            operation_sequence=2,
            state=BrokerState.CLEANING,
            phase=RuntimePhase.CLEANUP,
        )
        with self.assertRaises(StateStoreError) as stale_error:
            await store.append(stale, expected_revision=takeover.revision)
        self.assertEqual(
            stale_error.exception.code,
            StateStoreErrorCode.OWNERSHIP_CONFLICT,
        )

        continued = await store.append(
            conformance_event(
                job=9,
                event_number=93,
                operation=91,
                operation_sequence=2,
                state=BrokerState.CLEANING,
                phase=RuntimePhase.CLEANUP,
                fencing_token=2,
            ),
            expected_revision=takeover.revision,
        )
        self.assertEqual(continued.ownership, takeover.ownership)
        self.assertEqual(continued.revision, 3)

    async def test_recovery_scan_is_bounded_and_excludes_terminal_jobs(self) -> None:
        store = self.new_store()
        for job in (6, 7, 8):
            await store.append(
                conformance_event(
                    job=job,
                    event_number=60 + job,
                    operation=job,
                    operation_sequence=1,
                    state=BrokerState.VALIDATING,
                    phase=RuntimePhase.VALIDATE,
                ),
                expected_revision=0,
            )
        await store.append(
            conformance_event(
                job=7,
                event_number=77,
                operation=7,
                operation_sequence=2,
                state=BrokerState.CLEANING,
                phase=RuntimePhase.CLEANUP,
            ),
            expected_revision=1,
        )
        await store.append(
            conformance_event(
                job=7,
                event_number=78,
                operation=7,
                operation_sequence=3,
                state=BrokerState.FAILED,
                phase=RuntimePhase.WAIT,
                code=ErrorCode.WAIT_FAILED,
            ),
            expected_revision=2,
        )

        first = await self.reopen_store().scan_recoverable(limit=1)
        self.assertEqual(tuple(item.identity.job_id for item in first.items), (uuid_at(10_006),))
        self.assertEqual(first.next_cursor, uuid_at(10_006))
        second = await self.reopen_store().scan_recoverable(
            after=first.next_cursor,
            limit=1,
        )
        self.assertEqual(tuple(item.identity.job_id for item in second.items), (uuid_at(10_008),))
        self.assertIsNone(second.next_cursor)
