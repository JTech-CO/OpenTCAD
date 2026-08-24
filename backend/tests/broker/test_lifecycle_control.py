"""Phase-addressable execution cancellation contract tests."""

import json
import unittest

from backend.app.broker import (
    BrokerRequest,
    BrokerState,
    LifecycleCheckpoint,
    PhaseCancellation,
    SandboxBroker,
)
from backend.app.runtime.errors import ErrorCode, RuntimeBackendError
from backend.app.runtime.mock_backend import MockRuntimeBackend
from backend.app.runtime.models import (
    ContainerHandle,
    JobIdentity,
    RunResult,
    TerminalClassification,
    TerminationReason,
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


class RecordingBackend(MockRuntimeBackend):
    def __init__(self) -> None:
        super().__init__(images=(IMAGE,))
        self.kill_reasons: list[TerminationReason] = []

    async def kill(
        self,
        container: ContainerHandle,
        reason: TerminationReason,
    ) -> RunResult:
        self.kill_reasons.append(reason)
        return await super().kill(container, reason)


class NonBooleanSignal:
    def __init__(self, identity: JobIdentity) -> None:
        self.identity = identity

    def requested(self, checkpoint: LifecycleCheckpoint) -> str:
        return checkpoint.value


class LifecycleCancellationTests(unittest.IsolatedAsyncioTestCase):
    def broker(self, backend: MockRuntimeBackend) -> SandboxBroker:
        return SandboxBroker(backend, POLICY, ARCHIVE_LIMITS)

    async def test_all_lifecycle_checkpoints_cancel_and_leave_zero_objects(self) -> None:
        for index, checkpoint in enumerate(LifecycleCheckpoint):
            with self.subTest(checkpoint=checkpoint.value):
                backend = RecordingBackend()
                job_id = f"00000000-0000-4000-8001-{index + 1:012d}"
                identity = JobIdentity(job_id)
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
                    PhaseCancellation(identity, checkpoint),
                )

                self.assertEqual(outcome.state, BrokerState.CANCELLED)
                self.assertEqual(outcome.cancellation_checkpoint, checkpoint)
                self.assertTrue(outcome.cleanup_complete)
                self.assertIsNone(outcome.error)
                self.assertIsNone(outcome.cleanup_error)
                self.assertEqual(outcome.artifacts, ())
                self.assertIsNone(outcome.artifact_archive)
                self.assertIn(BrokerState.CANCELLING, {event.state for event in outcome.events})
                self.assertEqual(
                    backend.kill_reasons,
                    [TerminationReason.CANCELLATION]
                    if checkpoint is LifecycleCheckpoint.WAIT
                    else [],
                )
                if checkpoint is LifecycleCheckpoint.WAIT:
                    self.assertEqual(
                        outcome.result.classification,
                        TerminalClassification.CANCELLED,
                    )
                else:
                    self.assertIsNone(outcome.result)
                self.assertEqual((await backend.list_managed(job_id)).containers, ())
                self.assertEqual((await backend.list_managed(job_id)).volumes, ())
                public = json.dumps(outcome.as_dict(), sort_keys=True)
                self.assertIn(checkpoint.value, public)
                self.assertNotIn("payload", public)

    async def test_mismatched_signal_identity_is_rejected_before_allocation(self) -> None:
        backend = RecordingBackend()
        job_id = "00000000-0000-4000-8001-000000000020"
        foreign = JobIdentity("00000000-0000-4000-8001-000000000021")
        with self.assertRaises(RuntimeBackendError) as captured:
            await self.broker(backend).execute(
                BrokerRequest(make_spec(job_id), ARCHIVE_BYTES),
                PhaseCancellation(foreign, LifecycleCheckpoint.PROBE),
            )
        self.assertEqual(captured.exception.code, ErrorCode.IDENTITY_MISMATCH)
        self.assertEqual((await backend.list_managed()).containers, ())
        self.assertEqual((await backend.list_managed()).volumes, ())

    async def test_signal_must_return_a_boolean_and_cleanup_is_still_verified(self) -> None:
        backend = RecordingBackend()
        job_id = "00000000-0000-4000-8001-000000000022"
        outcome = await self.broker(backend).execute(
            BrokerRequest(make_spec(job_id), ARCHIVE_BYTES),
            NonBooleanSignal(JobIdentity(job_id)),
        )
        self.assertEqual(outcome.state, BrokerState.FAILED)
        self.assertEqual(outcome.error.code, ErrorCode.INVALID_SPEC)
        self.assertTrue(outcome.cleanup_complete)
        self.assertEqual((await backend.list_managed()).containers, ())
        self.assertEqual((await backend.list_managed()).volumes, ())


if __name__ == "__main__":
    unittest.main()
