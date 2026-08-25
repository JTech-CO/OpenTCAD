"""Durable external cancellation and restart-safe arbitration contracts."""

from __future__ import annotations

import asyncio
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from backend.app.broker import (
    BrokerStartupRequest,
    BrokerState,
    BrokerStateMapper,
    CancellationOutcome,
    CancellationRequest,
    DurableBrokerComposition,
    DurableCancellationCheckpoint,
    DurableCancellationCrashInjection,
    DurableCancellationInterrupted,
    DurableJobEvent,
    DurableJobStateStore,
    InMemoryJobStateStore,
    SQLiteJobStateStore,
    SandboxBroker,
    StateCompositionError,
    StateCompositionErrorCode,
    StateMappingContext,
    StateOperationContext,
    StateStoreError,
    StateStoreErrorCode,
)
from backend.app.runtime.errors import ErrorCode, RuntimePhase
from backend.app.runtime.mock_backend import MockRuntimeBackend
from backend.app.runtime.models import (
    ContainerHandle,
    JobIdentity,
    ManagedObjects,
    RunResult,
    RuntimeKind,
    TerminalClassification,
    TerminationReason,
    VolumeHandle,
)
from backend.tests.broker.state_store_conformance import conformance_event, uuid_at
from backend.tests.runtime.support import ARCHIVE, ARCHIVE_LIMITS, IMAGE, POLICY, make_spec


class CancellationTracingBackend(MockRuntimeBackend):
    def __init__(self, trace: list[str]) -> None:
        super().__init__(images=(IMAGE,))
        self.trace = trace

    async def kill(
        self,
        container: ContainerHandle,
        reason: TerminationReason,
    ) -> RunResult:
        self.trace.append(f"runtime:kill:{reason.value}")
        return await super().kill(container, reason)

    async def remove_container(self, container: ContainerHandle) -> None:
        self.trace.append("runtime:remove-container")
        await super().remove_container(container)

    async def remove_volume(self, volume: VolumeHandle) -> None:
        self.trace.append("runtime:remove-volume")
        await super().remove_volume(volume)

    async def list_managed(self, job_id: str | None = None) -> ManagedObjects:
        self.trace.append("runtime:query")
        return await super().list_managed(job_id)


class CancellationTracingStore:
    def __init__(
        self,
        delegate: DurableJobStateStore,
        trace: list[str],
    ) -> None:
        self.delegate = delegate
        self.trace = trace
        self.append_count = 0
        self.fail_at: int | None = None

    async def load(self, identity: JobIdentity):
        self.trace.append("state:load")
        return await self.delegate.load(identity)

    async def append(self, event: DurableJobEvent, *, expected_revision: int):
        self.append_count += 1
        self.trace.append(f"state:{event.state.value}")
        if self.fail_at == self.append_count:
            raise StateStoreError(StateStoreErrorCode.STORE_UNAVAILABLE)
        return await self.delegate.append(event, expected_revision=expected_revision)

    async def scan_recoverable(self, *, after=None, limit=100):
        return await self.delegate.scan_recoverable(after=after, limit=limit)


class BarrierLoadStore:
    """Returns the same loaded revision to two independent cancellation callers."""

    def __init__(self, delegate: DurableJobStateStore, parties: int = 2) -> None:
        self.delegate = delegate
        self.parties = parties
        self.enabled = False
        self.arrivals = 0
        self.release = asyncio.Event()

    async def load(self, identity: JobIdentity):
        snapshot = await self.delegate.load(identity)
        if self.enabled:
            self.arrivals += 1
            if self.arrivals >= self.parties:
                self.release.set()
            await self.release.wait()
        return snapshot

    async def append(self, event: DurableJobEvent, *, expected_revision: int):
        return await self.delegate.append(event, expected_revision=expected_revision)

    async def scan_recoverable(self, *, after=None, limit=100):
        return await self.delegate.scan_recoverable(after=after, limit=limit)


class DurableCancellationContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._temporary.cleanup()

    @staticmethod
    def broker(backend: MockRuntimeBackend) -> SandboxBroker:
        return SandboxBroker(backend, POLICY, ARCHIVE_LIMITS)

    @classmethod
    async def open_composition(
        cls,
        backend: MockRuntimeBackend,
        store: DurableJobStateStore,
        startup: int,
    ) -> DurableBrokerComposition:
        composition = DurableBrokerComposition(cls.broker(backend), store)
        await composition.startup(BrokerStartupRequest(uuid_at(startup), page_limit=2))
        return composition

    @staticmethod
    async def seed_running(store: DurableJobStateStore, job: int):
        snapshot = None
        path = (
            (BrokerState.VALIDATING, RuntimePhase.VALIDATE),
            (BrokerState.PREPARING, RuntimePhase.IMAGE),
            (BrokerState.RUNNING, RuntimePhase.WAIT),
        )
        for sequence, (state, phase) in enumerate(path, start=1):
            snapshot = await store.append(
                conformance_event(
                    job=job,
                    event_number=job * 10 + sequence,
                    operation=job,
                    operation_sequence=sequence,
                    state=state,
                    phase=phase,
                ),
                expected_revision=sequence - 1,
            )
        return snapshot

    @staticmethod
    async def create_running_objects(
        backend: MockRuntimeBackend,
        identity: JobIdentity,
    ) -> None:
        capabilities = (await backend.probe()).capabilities
        validated = POLICY.validate(make_spec(identity.job_id), capabilities)
        volume = await backend.create_volume(validated.identity)
        await backend.stage_inputs(volume, validated, ARCHIVE)
        container = await backend.create_container(validated, volume)
        await backend.start(container)

    @staticmethod
    async def append_state(
        store: DurableJobStateStore,
        *,
        job: int,
        revision: int,
        operation: int,
        sequence: int,
        state: BrokerState,
        phase: RuntimePhase,
    ):
        return await store.append(
            conformance_event(
                job=job,
                event_number=job * 100 + revision,
                operation=operation,
                operation_sequence=sequence,
                state=state,
                phase=phase,
            ),
            expected_revision=revision - 1,
        )

    async def test_admission_rejects_unready_missing_terminal_and_active_intent(self) -> None:
        trace: list[str] = []
        backend = CancellationTracingBackend(trace)
        store = InMemoryJobStateStore()
        composition = DurableBrokerComposition(self.broker(backend), store)
        missing_identity = JobIdentity(uuid_at(10_401))

        with self.assertRaises(StateCompositionError) as unready:
            await composition.cancel(
                CancellationRequest(missing_identity),
                StateOperationContext(uuid_at(60_401)),
            )
        self.assertEqual(
            unready.exception.code,
            StateCompositionErrorCode.STARTUP_REQUIRED,
        )
        self.assertEqual(trace, [])

        await composition.startup(BrokerStartupRequest(uuid_at(50_401)))
        trace.clear()
        with self.assertRaises(StateCompositionError) as missing:
            await composition.cancel(
                CancellationRequest(missing_identity),
                StateOperationContext(uuid_at(60_402)),
            )
        self.assertEqual(
            missing.exception.code,
            StateCompositionErrorCode.JOB_STATE_MISSING,
        )

        terminal = await self.seed_running(store, 402)
        await self.append_state(
            store,
            job=402,
            revision=4,
            operation=40_402,
            sequence=1,
            state=BrokerState.CLEANING,
            phase=RuntimePhase.CLEANUP,
        )
        await self.append_state(
            store,
            job=402,
            revision=5,
            operation=40_402,
            sequence=2,
            state=BrokerState.FAILED,
            phase=RuntimePhase.CLEANUP,
        )
        with self.assertRaises(StateCompositionError) as terminal_error:
            await composition.cancel(
                CancellationRequest(terminal.identity),
                StateOperationContext(uuid_at(60_403)),
            )
        self.assertEqual(
            terminal_error.exception.code,
            StateCompositionErrorCode.JOB_STATE_TERMINAL,
        )

        cancelling = await self.seed_running(store, 403)
        await self.append_state(
            store,
            job=403,
            revision=4,
            operation=40_403,
            sequence=1,
            state=BrokerState.CANCELLING,
            phase=RuntimePhase.QUERY,
        )
        cleaning = await self.seed_running(store, 404)
        await self.append_state(
            store,
            job=404,
            revision=4,
            operation=40_404,
            sequence=1,
            state=BrokerState.CLEANING,
            phase=RuntimePhase.CLEANUP,
        )
        for offset, identity in enumerate(
            (cancelling.identity, cleaning.identity),
            start=4,
        ):
            with self.subTest(state=identity.job_id):
                with self.assertRaises(StateCompositionError) as active:
                    await composition.cancel(
                        CancellationRequest(identity),
                        StateOperationContext(uuid_at(60_400 + offset)),
                    )
                self.assertEqual(
                    active.exception.code,
                    StateCompositionErrorCode.CANCELLATION_IN_PROGRESS,
                )
        self.assertNotIn("runtime:query", trace)

    async def test_sqlite_intent_precedes_runtime_and_matches_complete_mapper(self) -> None:
        trace: list[str] = []
        backend = CancellationTracingBackend(trace)
        database = Path(self._temporary.name) / "durable-cancel.sqlite3"
        delegate = SQLiteJobStateStore(database)
        store = CancellationTracingStore(delegate, trace)
        composition = await self.open_composition(backend, store, 50_405)
        seeded = await self.seed_running(delegate, 405)
        await self.create_running_objects(backend, seeded.identity)
        trace.clear()
        store.append_count = 0
        operation_id = uuid_at(60_405)

        outcome = await composition.cancel(
            CancellationRequest(seeded.identity),
            StateOperationContext(operation_id),
        )

        self.assertEqual(outcome.state, BrokerState.CANCELLED)
        self.assertTrue(outcome.intent_persisted)
        self.assertEqual(
            outcome.result.classification,
            TerminalClassification.CANCELLED,
        )
        self.assertEqual(
            trace,
            [
                "state:load",
                "state:cancelling",
                "runtime:query",
                "state:cancelling",
                "runtime:kill:cancellation",
                "state:cleaning",
                "runtime:remove-container",
                "runtime:remove-volume",
                "runtime:query",
                "state:cancelled",
            ],
        )
        final = await delegate.load(seeded.identity)
        self.assertEqual((final.state, final.revision), (BrokerState.CANCELLED, 7))

        mapped = BrokerStateMapper().map_outcome(
            outcome,
            StateMappingContext(operation_id, RuntimeKind.MOCK),
        )
        with closing(sqlite3.connect(database)) as connection:
            rows = tuple(
                connection.execute(
                    "SELECT event_id, state, phase, operation_sequence, "
                    "classification, cleanup_complete FROM job_events "
                    "WHERE operation_id = ? ORDER BY operation_sequence",
                    (operation_id,),
                ),
            )
        self.assertEqual(
            rows,
            tuple(
                (
                    event.event_id,
                    event.state.value,
                    event.phase.value,
                    event.operation_sequence,
                    event.classification.value
                    if event.classification is not None
                    else None,
                    int(event.cleanup_complete),
                )
                for event in mapped.events
            ),
        )

    async def test_absent_and_volume_only_runtime_objects_converge_cancelled(self) -> None:
        backend = CancellationTracingBackend([])
        store = InMemoryJobStateStore()
        composition = await self.open_composition(backend, store, 50_406)

        absent = await self.seed_running(store, 406)
        absent_outcome = await composition.cancel(
            CancellationRequest(absent.identity),
            StateOperationContext(uuid_at(60_406)),
        )
        self.assertEqual(absent_outcome.state, BrokerState.CANCELLED)
        self.assertIsNone(absent_outcome.result)
        self.assertTrue(absent_outcome.intent_persisted)
        self.assertEqual(absent_outcome.as_dict()["classification"], "cancelled")
        self.assertEqual((await store.load(absent.identity)).revision, 6)

        volume_only = await self.seed_running(store, 407)
        capabilities = (await backend.probe()).capabilities
        validated = POLICY.validate(make_spec(volume_only.identity.job_id), capabilities)
        await backend.create_volume(validated.identity)
        volume_outcome = await composition.cancel(
            CancellationRequest(volume_only.identity),
            StateOperationContext(uuid_at(60_407)),
        )
        self.assertEqual(volume_outcome.state, BrokerState.CANCELLED)
        self.assertIsNone(volume_outcome.result)
        self.assertTrue(volume_outcome.cleanup_complete)
        managed = await backend.list_managed(volume_only.identity.job_id)
        self.assertEqual((managed.containers, managed.volumes), ((), ()))

    async def test_competing_operation_ids_have_one_cas_winner(self) -> None:
        trace: list[str] = []
        backend = CancellationTracingBackend(trace)
        delegate = InMemoryJobStateStore()
        store = BarrierLoadStore(delegate)
        first = await self.open_composition(backend, store, 50_408)
        second = await self.open_composition(backend, store, 50_409)
        seeded = await self.seed_running(delegate, 408)
        await self.create_running_objects(backend, seeded.identity)
        trace.clear()
        store.enabled = True

        results = await asyncio.gather(
            first.cancel(
                CancellationRequest(seeded.identity),
                StateOperationContext(uuid_at(60_408)),
            ),
            second.cancel(
                CancellationRequest(seeded.identity),
                StateOperationContext(uuid_at(60_409)),
            ),
            return_exceptions=True,
        )

        winners = [item for item in results if isinstance(item, CancellationOutcome)]
        conflicts = [item for item in results if isinstance(item, StateCompositionError)]
        self.assertEqual((len(winners), len(conflicts)), (1, 1))
        self.assertEqual(
            conflicts[0].code,
            StateCompositionErrorCode.CANCELLATION_CONFLICT,
        )
        self.assertEqual(winners[0].state, BrokerState.CANCELLED)
        self.assertEqual(store.arrivals, 2)
        self.assertEqual(trace.count("runtime:kill:cancellation"), 1)
        self.assertEqual(trace.count("runtime:query"), 2)
        final = await delegate.load(seeded.identity)
        self.assertEqual((final.state, final.revision), (BrokerState.CANCELLED, 7))

    async def test_intent_write_failure_prevents_runtime_contact(self) -> None:
        trace: list[str] = []
        backend = CancellationTracingBackend(trace)
        delegate = InMemoryJobStateStore()
        store = CancellationTracingStore(delegate, trace)
        composition = await self.open_composition(backend, store, 50_410)
        seeded = await self.seed_running(delegate, 410)
        await self.create_running_objects(backend, seeded.identity)
        trace.clear()
        store.append_count = 0
        store.fail_at = 1

        with self.assertRaises(StateCompositionError) as captured:
            await composition.cancel(
                CancellationRequest(seeded.identity),
                StateOperationContext(uuid_at(60_410)),
            )
        self.assertEqual(
            captured.exception.code,
            StateCompositionErrorCode.STORE_UNAVAILABLE,
        )
        self.assertNotIn("runtime:query", trace)
        self.assertFalse(any(item.startswith("runtime:kill:") for item in trace))
        pending = await delegate.load(seeded.identity)
        self.assertEqual((pending.state, pending.revision), (BrokerState.RUNNING, 3))

    async def test_phase_write_failure_cleans_and_restart_closes_cancelled(self) -> None:
        trace: list[str] = []
        backend = CancellationTracingBackend(trace)
        delegate = InMemoryJobStateStore()
        store = CancellationTracingStore(delegate, trace)
        composition = await self.open_composition(backend, store, 50_411)
        seeded = await self.seed_running(delegate, 411)
        await self.create_running_objects(backend, seeded.identity)
        trace.clear()
        store.append_count = 0
        store.fail_at = 2

        outcome = await composition.cancel(
            CancellationRequest(seeded.identity),
            StateOperationContext(uuid_at(60_411)),
        )
        self.assertEqual(outcome.state, BrokerState.FAILED)
        self.assertEqual(outcome.error.code, ErrorCode.INVALID_STATE)
        self.assertTrue(outcome.intent_persisted)
        self.assertTrue(outcome.cleanup_complete)
        self.assertNotIn("runtime:kill:cancellation", trace)
        self.assertIn("runtime:kill:shutdown", trace)
        pending = await delegate.load(seeded.identity)
        self.assertEqual((pending.state, pending.revision), (BrokerState.CANCELLING, 4))
        managed = await backend.list_managed(seeded.identity.job_id)
        self.assertEqual((managed.containers, managed.volumes), ((), ()))

        restarted = await self.open_composition(backend, delegate, 50_412)
        final = await delegate.load(seeded.identity)
        self.assertTrue(restarted.ready)
        self.assertEqual((final.state, final.revision), (BrokerState.CANCELLED, 6))
        self.assertEqual(
            final.last_event.classification,
            TerminalClassification.CANCELLED,
        )

    async def test_terminal_write_failure_is_public_failure_until_restart(self) -> None:
        trace: list[str] = []
        backend = CancellationTracingBackend(trace)
        delegate = InMemoryJobStateStore()
        store = CancellationTracingStore(delegate, trace)
        composition = await self.open_composition(backend, store, 50_413)
        seeded = await self.seed_running(delegate, 413)
        await self.create_running_objects(backend, seeded.identity)
        trace.clear()
        store.append_count = 0
        store.fail_at = 4

        outcome = await composition.cancel(
            CancellationRequest(seeded.identity),
            StateOperationContext(uuid_at(60_413)),
        )
        self.assertEqual(outcome.state, BrokerState.FAILED)
        self.assertEqual(outcome.error.code, ErrorCode.INVALID_STATE)
        self.assertEqual(
            outcome.result.classification,
            TerminalClassification.CANCELLED,
        )
        self.assertTrue(outcome.cleanup_complete)
        pending = await delegate.load(seeded.identity)
        self.assertEqual((pending.state, pending.revision), (BrokerState.CLEANING, 6))
        self.assertEqual(
            pending.last_event.classification,
            TerminalClassification.CANCELLED,
        )

        restarted = await self.open_composition(backend, delegate, 50_414)
        final = await delegate.load(seeded.identity)
        self.assertTrue(restarted.ready)
        self.assertEqual((final.state, final.revision), (BrokerState.CANCELLED, 8))

    async def test_each_crash_checkpoint_has_a_restart_safe_terminal_contract(self) -> None:
        expected_crash = {
            DurableCancellationCheckpoint.BEFORE_INTENT: (BrokerState.RUNNING, 3, 1),
            DurableCancellationCheckpoint.AFTER_INTENT: (
                BrokerState.CANCELLING,
                4,
                1,
            ),
            DurableCancellationCheckpoint.AFTER_CLEANING_STATE: (
                BrokerState.CLEANING,
                6,
                1,
            ),
            DurableCancellationCheckpoint.AFTER_CLEANUP: (
                BrokerState.CLEANING,
                6,
                0,
            ),
            DurableCancellationCheckpoint.AFTER_FINAL_STATE: (
                BrokerState.CANCELLED,
                7,
                0,
            ),
        }
        expected_restart = {
            DurableCancellationCheckpoint.BEFORE_INTENT: (BrokerState.FAILED, 5),
            DurableCancellationCheckpoint.AFTER_INTENT: (BrokerState.CANCELLED, 6),
            DurableCancellationCheckpoint.AFTER_CLEANING_STATE: (
                BrokerState.CANCELLED,
                8,
            ),
            DurableCancellationCheckpoint.AFTER_CLEANUP: (BrokerState.CANCELLED, 8),
            DurableCancellationCheckpoint.AFTER_FINAL_STATE: (
                BrokerState.CANCELLED,
                7,
            ),
        }

        for offset, checkpoint in enumerate(DurableCancellationCheckpoint):
            with self.subTest(checkpoint=checkpoint.value):
                database = (
                    Path(self._temporary.name) / f"crash-{checkpoint.value}.sqlite3"
                )
                backend = CancellationTracingBackend([])
                store = SQLiteJobStateStore(database)
                composition = await self.open_composition(
                    backend,
                    store,
                    50_420 + offset,
                )
                seeded = await self.seed_running(store, 420 + offset)
                await self.create_running_objects(backend, seeded.identity)

                with self.assertRaises(DurableCancellationInterrupted) as crash:
                    await composition.cancel(
                        CancellationRequest(seeded.identity),
                        StateOperationContext(uuid_at(60_420 + offset)),
                        DurableCancellationCrashInjection(
                            checkpoint,
                            seeded.identity.job_id,
                        ),
                    )
                self.assertEqual(crash.exception.checkpoint, checkpoint)
                crashed = await store.load(seeded.identity)
                state, revision, remaining = expected_crash[checkpoint]
                self.assertEqual((crashed.state, crashed.revision), (state, revision))
                managed = await backend.list_managed(seeded.identity.job_id)
                self.assertEqual(len(managed.containers), remaining)
                self.assertEqual(len(managed.volumes), remaining)

                reopened = SQLiteJobStateStore(database)
                restarted = DurableBrokerComposition(self.broker(backend), reopened)
                restart_report = await restarted.startup(
                    BrokerStartupRequest(uuid_at(50_430 + offset), page_limit=2),
                )
                final = await reopened.load(seeded.identity)
                self.assertEqual(
                    (final.state, final.revision),
                    expected_restart[checkpoint],
                )
                expected_items = (
                    0
                    if checkpoint is DurableCancellationCheckpoint.AFTER_FINAL_STATE
                    else 1
                )
                self.assertEqual(restart_report.recovered_items, expected_items)
                if checkpoint is DurableCancellationCheckpoint.BEFORE_INTENT:
                    self.assertEqual(final.last_event.code, ErrorCode.STALE_STATE)
                else:
                    self.assertEqual(
                        final.last_event.classification,
                        TerminalClassification.CANCELLED,
                    )
                final_managed = await backend.list_managed(seeded.identity.job_id)
                self.assertEqual(
                    (final_managed.containers, final_managed.volumes),
                    ((), ()),
                )


if __name__ == "__main__":
    unittest.main()
