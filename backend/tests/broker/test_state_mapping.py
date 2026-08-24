"""Broker outcome to durable-state mapping and recording contract tests."""

from dataclasses import replace
import unittest
from uuid import UUID

from backend.app.broker import (
    BrokerRequest,
    BrokerState,
    BrokerStateMapper,
    InMemoryJobStateStore,
    LifecycleCheckpoint,
    PhaseCancellation,
    SandboxBroker,
    StateEventRecorder,
    StateMappingContext,
    StateMappingError,
    StateMappingErrorCode,
)
from backend.app.runtime.errors import ErrorCode, RuntimeBackendError, RuntimePhase
from backend.app.runtime.mock_backend import MockRuntimeBackend
from backend.app.runtime.models import (
    ContainerHandle,
    JobIdentity,
    RuntimeKind,
    RunResult,
    TerminalClassification,
)
from backend.tests.runtime.support import (
    ARCHIVE_BYTES,
    ARCHIVE_LIMITS,
    ARTIFACT_ARCHIVE,
    IMAGE,
    POLICY,
    make_result,
    make_spec,
)


def uuid_at(value: int) -> str:
    return str(UUID(int=value))


class LeakyBackend(MockRuntimeBackend):
    async def remove_container(self, container: ContainerHandle) -> None:
        return None

    async def remove_volume(self, volume) -> None:
        return None


class WaitFailureBackend(MockRuntimeBackend):
    async def wait(self, container: ContainerHandle) -> RunResult:
        raise RuntimeBackendError(
            ErrorCode.WAIT_FAILED,
            RuntimePhase.WAIT,
            backend=self.name.value,
        )


class BrokerStateMappingTests(unittest.IsolatedAsyncioTestCase):
    def broker(self, backend: MockRuntimeBackend) -> SandboxBroker:
        return SandboxBroker(backend, POLICY, ARCHIVE_LIMITS)

    async def successful_outcome(self, job_id: str):
        backend = MockRuntimeBackend(images=(IMAGE,))
        backend.plan_result(
            job_id,
            make_result(
                TerminalClassification.SUCCEEDED,
                exit_code=0,
                include_artifact=True,
            ),
            ARTIFACT_ARCHIVE,
        )
        return await self.broker(backend).execute(
            BrokerRequest(make_spec(job_id), ARCHIVE_BYTES),
        )

    async def test_success_mapping_is_deterministic_and_records_terminal_state(self) -> None:
        outcome = await self.successful_outcome(uuid_at(701))
        context = StateMappingContext(uuid_at(801), RuntimeKind.MOCK)
        mapper = BrokerStateMapper()
        batch = mapper.map_outcome(outcome, context)
        self.assertEqual(batch, mapper.map_outcome(outcome, context))
        self.assertEqual(
            tuple(event.operation_sequence for event in batch.events),
            tuple(range(1, len(outcome.events) + 1)),
        )
        self.assertEqual(batch.events[-1].state, BrokerState.SUCCEEDED)
        self.assertTrue(batch.events[-1].cleanup_complete)
        self.assertEqual(batch.events[-1].backend, RuntimeKind.MOCK)

        snapshot = await StateEventRecorder(InMemoryJobStateStore()).record(
            batch,
            expected_revision=0,
        )
        self.assertEqual(snapshot.revision, len(batch.events))
        self.assertEqual(snapshot.state, BrokerState.SUCCEEDED)
        self.assertFalse(snapshot.recoverable)

    async def test_early_cancellation_persists_cancellation_intent(self) -> None:
        job_id = uuid_at(702)
        outcome = await self.broker(MockRuntimeBackend(images=(IMAGE,))).execute(
            BrokerRequest(make_spec(job_id), ARCHIVE_BYTES),
            PhaseCancellation(JobIdentity(job_id), LifecycleCheckpoint.PROBE),
        )
        batch = BrokerStateMapper().map_outcome(
            outcome,
            StateMappingContext(uuid_at(802), RuntimeKind.MOCK),
        )
        cleaning = next(event for event in batch.events if event.state is BrokerState.CLEANING)
        self.assertEqual(cleaning.classification, TerminalClassification.CANCELLED)
        self.assertEqual(batch.events[-1].state, BrokerState.CANCELLED)
        self.assertEqual(batch.events[-1].classification, TerminalClassification.CANCELLED)

    async def test_incomplete_cleanup_stays_recoverable_instead_of_terminal(self) -> None:
        job_id = uuid_at(703)
        backend = LeakyBackend(images=(IMAGE,))
        backend.plan_result(
            job_id,
            make_result(
                TerminalClassification.SUCCEEDED,
                exit_code=0,
                include_artifact=True,
            ),
            ARTIFACT_ARCHIVE,
        )
        outcome = await self.broker(backend).execute(
            BrokerRequest(make_spec(job_id), ARCHIVE_BYTES),
        )
        self.assertFalse(outcome.cleanup_complete)
        batch = BrokerStateMapper().map_outcome(
            outcome,
            StateMappingContext(uuid_at(803), RuntimeKind.MOCK),
        )
        last = batch.events[-1]
        self.assertEqual(last.state, BrokerState.CLEANING)
        self.assertEqual(last.phase, RuntimePhase.CLEANUP)
        self.assertEqual(last.code, ErrorCode.CLEANUP_FAILED)
        self.assertFalse(last.cleanup_complete)
        snapshot = await StateEventRecorder(InMemoryJobStateStore()).record(
            batch,
            expected_revision=0,
        )
        self.assertTrue(snapshot.recoverable)

    async def test_partial_batch_replay_converges_without_duplicate_revisions(self) -> None:
        outcome = await self.successful_outcome(uuid_at(704))
        batch = BrokerStateMapper().map_outcome(
            outcome,
            StateMappingContext(uuid_at(804), RuntimeKind.MOCK),
        )
        store = InMemoryJobStateStore()
        await store.append(batch.events[0], expected_revision=0)
        await store.append(batch.events[1], expected_revision=1)
        snapshot = await StateEventRecorder(store).record(batch, expected_revision=0)
        self.assertEqual(snapshot.revision, len(batch.events))
        replay = await StateEventRecorder(store).record(batch, expected_revision=0)
        self.assertEqual(replay, snapshot)

    async def test_malformed_sequence_and_backend_mismatch_fail_closed(self) -> None:
        outcome = await self.successful_outcome(uuid_at(705))
        malformed = replace(
            outcome,
            events=(replace(outcome.events[0], sequence=2), *outcome.events[1:]),
        )
        with self.assertRaises(StateMappingError) as sequence_error:
            BrokerStateMapper().map_outcome(
                malformed,
                StateMappingContext(uuid_at(805), RuntimeKind.MOCK),
            )
        self.assertEqual(sequence_error.exception.code, StateMappingErrorCode.INVALID_SEQUENCE)

        failed = await self.broker(WaitFailureBackend(images=(IMAGE,))).execute(
            BrokerRequest(make_spec(uuid_at(706)), ARCHIVE_BYTES),
        )
        malformed_error = replace(
            failed,
            events=(
                *failed.events[:-1],
                replace(failed.events[-1], code=ErrorCode.KILL_FAILED),
            ),
        )
        with self.assertRaises(StateMappingError) as missing_error:
            BrokerStateMapper().map_outcome(
                malformed_error,
                StateMappingContext(uuid_at(807), RuntimeKind.MOCK),
            )
        self.assertEqual(
            missing_error.exception.code,
            StateMappingErrorCode.ERROR_MAPPING_MISSING,
        )

        with self.assertRaises(StateMappingError) as backend_error:
            BrokerStateMapper().map_outcome(
                failed,
                StateMappingContext(uuid_at(806), RuntimeKind.DOCKER),
            )
        self.assertEqual(backend_error.exception.code, StateMappingErrorCode.BACKEND_MISMATCH)


if __name__ == "__main__":
    unittest.main()
