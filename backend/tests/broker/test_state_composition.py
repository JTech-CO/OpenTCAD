"""Startup ordering and phase-time durable broker composition tests."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from backend.app.broker import (
    BROKER_STATE_COMPOSITION_PRODUCT_ENABLED,
    BrokerRequest,
    BrokerStartupRequest,
    BrokerState,
    BrokerStateMapper,
    DurableBrokerComposition,
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
    ImageIdentity,
    JobIdentity,
    ManagedObjects,
    RunResult,
    RuntimeKind,
    RuntimeProbe,
    TerminalClassification,
    ValidatedSandboxSpec,
    ValidatedInputArchive,
    VolumeHandle,
)
from backend.tests.broker.state_store_conformance import conformance_event, uuid_at
from backend.tests.runtime.support import (
    ARCHIVE,
    ARCHIVE_BYTES,
    ARCHIVE_LIMITS,
    ARTIFACT_ARCHIVE,
    IMAGE,
    POLICY,
    make_result,
    make_spec,
)


class TracingBackend(MockRuntimeBackend):
    def __init__(self, trace: list[str]) -> None:
        super().__init__(images=(IMAGE,))
        self.trace = trace

    async def probe(self) -> RuntimeProbe:
        self.trace.append("runtime:probe")
        return await super().probe()

    async def ensure_image(self, image: ImageIdentity) -> ImageIdentity:
        self.trace.append("runtime:image")
        return await super().ensure_image(image)

    async def create_volume(self, identity: JobIdentity) -> VolumeHandle:
        self.trace.append("runtime:volume")
        return await super().create_volume(identity)

    async def stage_inputs(
        self,
        volume: VolumeHandle,
        spec: ValidatedSandboxSpec,
        archive: ValidatedInputArchive,
    ) -> None:
        self.trace.append("runtime:input")
        await super().stage_inputs(volume, spec, archive)

    async def create_container(
        self,
        spec: ValidatedSandboxSpec,
        volume: VolumeHandle,
    ) -> ContainerHandle:
        self.trace.append("runtime:container")
        return await super().create_container(spec, volume)

    async def start(self, container: ContainerHandle) -> None:
        self.trace.append("runtime:start")
        await super().start(container)

    async def wait(self, container: ContainerHandle) -> RunResult:
        self.trace.append("runtime:wait")
        return await super().wait(container)

    async def collect_artifacts(self, container: ContainerHandle) -> bytes:
        self.trace.append("runtime:artifact")
        return await super().collect_artifacts(container)

    async def remove_container(self, container: ContainerHandle) -> None:
        self.trace.append("runtime:remove-container")
        await super().remove_container(container)

    async def remove_volume(self, volume: VolumeHandle) -> None:
        self.trace.append("runtime:remove-volume")
        await super().remove_volume(volume)

    async def list_managed(self, job_id: str | None = None) -> ManagedObjects:
        self.trace.append("runtime:query")
        return await super().list_managed(job_id)


class LeakyTracingBackend(TracingBackend):
    async def remove_container(self, container: ContainerHandle) -> None:
        self.trace.append("runtime:remove-container-leaked")

    async def remove_volume(self, volume: VolumeHandle) -> None:
        self.trace.append("runtime:remove-volume-leaked")


class ProductKindBackend(MockRuntimeBackend):
    @property
    def name(self) -> RuntimeKind:
        return RuntimeKind.DOCKER


class TracingStateStore:
    def __init__(
        self,
        delegate: DurableJobStateStore,
        trace: list[str],
    ) -> None:
        self.delegate = delegate
        self.trace = trace
        self.fail_at: int | None = None
        self.append_count = 0

    async def load(self, identity: JobIdentity):
        return await self.delegate.load(identity)

    async def append(self, event: DurableJobEvent, *, expected_revision: int):
        self.append_count += 1
        self.trace.append(f"state:{event.state.value}")
        if self.fail_at == self.append_count:
            raise StateStoreError(StateStoreErrorCode.STORE_UNAVAILABLE)
        return await self.delegate.append(event, expected_revision=expected_revision)

    async def scan_recoverable(self, *, after=None, limit=100):
        return await self.delegate.scan_recoverable(after=after, limit=limit)


class StateCompositionContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._temporary.cleanup()

    @staticmethod
    def broker(backend: MockRuntimeBackend) -> SandboxBroker:
        return SandboxBroker(backend, POLICY, ARCHIVE_LIMITS)

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
        spec = make_spec(identity.job_id)
        capabilities = (await backend.probe()).capabilities
        validated = POLICY.validate(spec, capabilities)
        volume = await backend.create_volume(validated.identity)
        await backend.stage_inputs(volume, validated, ARCHIVE)
        container = await backend.create_container(validated, volume)
        await backend.start(container)

    @staticmethod
    async def open_composition(
        backend: MockRuntimeBackend,
        store: DurableJobStateStore,
        startup: int,
    ) -> DurableBrokerComposition:
        composition = DurableBrokerComposition(
            SandboxBroker(backend, POLICY, ARCHIVE_LIMITS),
            store,
        )
        await composition.startup(BrokerStartupRequest(uuid_at(startup), page_limit=2))
        return composition

    async def test_execute_requires_completed_startup_before_runtime_contact(self) -> None:
        trace: list[str] = []
        backend = TracingBackend(trace)
        composition = DurableBrokerComposition(
            self.broker(backend),
            InMemoryJobStateStore(),
        )
        with self.assertRaises(StateCompositionError) as captured:
            await composition.execute(
                BrokerRequest(make_spec(uuid_at(30_001)), ARCHIVE_BYTES),
                StateOperationContext(uuid_at(40_001)),
            )
        self.assertEqual(
            captured.exception.code,
            StateCompositionErrorCode.STARTUP_REQUIRED,
        )
        self.assertEqual(trace, [])
        self.assertFalse(BROKER_STATE_COMPOSITION_PRODUCT_ENABLED)

    async def test_product_runtime_kind_is_rejected_at_composition_boundary(self) -> None:
        broker = self.broker(ProductKindBackend(images=(IMAGE,)))
        with self.assertRaises(StateCompositionError) as captured:
            DurableBrokerComposition(broker, InMemoryJobStateStore())
        self.assertEqual(
            captured.exception.code,
            StateCompositionErrorCode.PRODUCT_RUNTIME_DISABLED,
        )

    async def test_sqlite_live_events_precede_runtime_boundaries_and_match_mapper(self) -> None:
        trace: list[str] = []
        backend = TracingBackend(trace)
        database = Path(self._temporary.name) / "live.sqlite3"
        store = TracingStateStore(SQLiteJobStateStore(database), trace)
        composition = await self.open_composition(backend, store, 50_001)
        trace.clear()
        job_id = uuid_at(30_002)
        operation_id = uuid_at(40_002)
        backend.plan_result(
            job_id,
            make_result(
                TerminalClassification.SUCCEEDED,
                exit_code=0,
                include_artifact=True,
            ),
            ARTIFACT_ARCHIVE,
        )
        outcome = await composition.execute(
            BrokerRequest(make_spec(job_id), ARCHIVE_BYTES),
            StateOperationContext(operation_id),
        )
        self.assertEqual(outcome.state, BrokerState.SUCCEEDED)
        ordered = (
            "state:validating",
            "runtime:probe",
            "state:preparing",
            "runtime:image",
            "runtime:volume",
            "runtime:input",
            "runtime:container",
            "runtime:start",
            "state:running",
            "runtime:wait",
            "state:collecting",
            "runtime:artifact",
            "state:cleaning",
            "runtime:remove-container",
            "runtime:remove-volume",
            "state:succeeded",
        )
        positions = tuple(trace.index(item) for item in ordered)
        self.assertEqual(positions, tuple(sorted(positions)))

        mapped = BrokerStateMapper().map_outcome(
            outcome,
            StateMappingContext(operation_id, RuntimeKind.MOCK),
        )
        with closing(sqlite3.connect(database)) as connection:
            rows = tuple(
                connection.execute(
                    "SELECT event_id, state, operation_sequence "
                    "FROM job_events ORDER BY revision",
                ),
            )
        self.assertEqual(
            rows,
            tuple(
                (event.event_id, event.state.value, event.operation_sequence)
                for event in mapped.events
            ),
        )

    async def test_preparing_write_failure_stops_before_runtime_allocation(self) -> None:
        trace: list[str] = []
        backend = TracingBackend(trace)
        delegate = InMemoryJobStateStore()
        store = TracingStateStore(delegate, trace)
        composition = await self.open_composition(backend, store, 50_003)
        trace.clear()
        store.append_count = 0
        store.fail_at = 2
        job_id = uuid_at(30_003)
        outcome = await composition.execute(
            BrokerRequest(make_spec(job_id), ARCHIVE_BYTES),
            StateOperationContext(uuid_at(40_003)),
        )
        self.assertEqual(outcome.state, BrokerState.FAILED)
        self.assertEqual(outcome.error.code, ErrorCode.INVALID_STATE)
        self.assertNotIn("runtime:image", trace)
        self.assertNotIn("runtime:volume", trace)
        snapshot = await delegate.load(JobIdentity(job_id))
        self.assertEqual((snapshot.state, snapshot.revision), (BrokerState.VALIDATING, 1))
        self.assertTrue(snapshot.recoverable)

    async def test_running_write_failure_cleans_allocated_runtime_objects(self) -> None:
        trace: list[str] = []
        backend = TracingBackend(trace)
        delegate = InMemoryJobStateStore()
        store = TracingStateStore(delegate, trace)
        composition = await self.open_composition(backend, store, 50_004)
        trace.clear()
        store.append_count = 0
        store.fail_at = 3
        job_id = uuid_at(30_004)
        outcome = await composition.execute(
            BrokerRequest(make_spec(job_id), ARCHIVE_BYTES),
            StateOperationContext(uuid_at(40_004)),
        )
        self.assertEqual(outcome.state, BrokerState.FAILED)
        self.assertEqual(outcome.error.code, ErrorCode.INVALID_STATE)
        self.assertIn("runtime:start", trace)
        self.assertIn("runtime:remove-container", trace)
        managed = await backend.list_managed(job_id)
        self.assertEqual((managed.containers, managed.volumes), ((), ()))
        snapshot = await delegate.load(JobIdentity(job_id))
        self.assertEqual((snapshot.state, snapshot.revision), (BrokerState.PREPARING, 2))

    async def test_terminal_write_failure_downgrades_success_and_restart_closes_prefix(self) -> None:
        trace: list[str] = []
        backend = TracingBackend(trace)
        delegate = InMemoryJobStateStore()
        store = TracingStateStore(delegate, trace)
        composition = await self.open_composition(backend, store, 50_005)
        store.append_count = 0
        store.fail_at = 6
        job_id = uuid_at(30_005)
        backend.plan_result(
            job_id,
            make_result(
                TerminalClassification.SUCCEEDED,
                exit_code=0,
                include_artifact=True,
            ),
            ARTIFACT_ARCHIVE,
        )
        outcome = await composition.execute(
            BrokerRequest(make_spec(job_id), ARCHIVE_BYTES),
            StateOperationContext(uuid_at(40_005)),
        )
        self.assertEqual(outcome.state, BrokerState.FAILED)
        self.assertEqual(outcome.error.code, ErrorCode.INVALID_STATE)
        self.assertEqual(outcome.artifacts, ())
        pending = await delegate.load(JobIdentity(job_id))
        self.assertEqual((pending.state, pending.revision), (BrokerState.CLEANING, 5))

        restarted = await self.open_composition(backend, delegate, 50_006)
        final = await delegate.load(JobIdentity(job_id))
        self.assertTrue(restarted.ready)
        self.assertEqual((final.state, final.revision), (BrokerState.FAILED, 7))
        self.assertEqual(final.last_event.code, ErrorCode.STALE_STATE)

    async def test_existing_job_state_is_rejected_before_runtime_contact(self) -> None:
        trace: list[str] = []
        backend = TracingBackend(trace)
        store = InMemoryJobStateStore()
        composition = await self.open_composition(backend, store, 50_007)
        trace.clear()
        job = 307
        event = conformance_event(
            job=job,
            event_number=3_071,
            operation=job,
            operation_sequence=1,
            state=BrokerState.VALIDATING,
            phase=RuntimePhase.VALIDATE,
        )
        await store.append(event, expected_revision=0)
        with self.assertRaises(StateCompositionError) as captured:
            await composition.execute(
                BrokerRequest(make_spec(event.identity.job_id), ARCHIVE_BYTES),
                StateOperationContext(uuid_at(40_007)),
            )
        self.assertEqual(
            captured.exception.code,
            StateCompositionErrorCode.JOB_STATE_EXISTS,
        )
        self.assertNotIn("runtime:probe", trace)

    async def test_startup_reconciles_stale_objects_before_opening_admission(self) -> None:
        trace: list[str] = []
        backend = TracingBackend(trace)
        store = InMemoryJobStateStore()
        seeded = await self.seed_running(store, 308)
        await self.create_running_objects(backend, seeded.identity)
        trace.clear()
        composition = DurableBrokerComposition(self.broker(backend), store)
        report = await composition.startup(
            BrokerStartupRequest(uuid_at(50_008), page_limit=1),
        )
        final = await store.load(seeded.identity)
        managed = await backend.list_managed(seeded.identity.job_id)
        self.assertTrue(composition.ready)
        self.assertEqual(report.recovered_items, 1)
        self.assertEqual(final.state, BrokerState.FAILED)
        self.assertEqual(final.last_event.code, ErrorCode.STALE_STATE)
        self.assertEqual((managed.containers, managed.volumes), ((), ()))

    async def test_incomplete_startup_recovery_keeps_admission_closed(self) -> None:
        trace: list[str] = []
        backend = LeakyTracingBackend(trace)
        store = InMemoryJobStateStore()
        seeded = await self.seed_running(store, 309)
        await self.create_running_objects(backend, seeded.identity)
        composition = DurableBrokerComposition(self.broker(backend), store)
        with self.assertRaises(StateCompositionError) as captured:
            await composition.startup(BrokerStartupRequest(uuid_at(50_009)))
        self.assertEqual(
            captured.exception.code,
            StateCompositionErrorCode.RECOVERY_INCOMPLETE,
        )
        self.assertFalse(composition.ready)
        pending = await store.load(seeded.identity)
        self.assertEqual(pending.state, BrokerState.CLEANING)
        with self.assertRaises(StateCompositionError) as admission:
            await composition.execute(
                BrokerRequest(make_spec(uuid_at(30_009)), ARCHIVE_BYTES),
                StateOperationContext(uuid_at(40_009)),
            )
        self.assertEqual(
            admission.exception.code,
            StateCompositionErrorCode.STARTUP_REQUIRED,
        )


if __name__ == "__main__":
    unittest.main()
