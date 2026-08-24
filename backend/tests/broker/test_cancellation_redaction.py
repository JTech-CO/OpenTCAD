"""Cancellation identity, output transfer, and public redaction tests."""

import json
import unittest

from backend.app.broker import (
    ArtifactPayload,
    BrokerRequest,
    BrokerState,
    CancellationRequest,
    SandboxBroker,
    build_canonical_output_archive,
)
from backend.app.runtime.errors import ErrorCode, RuntimeBackendError, RuntimePhase
from backend.app.runtime.mock_backend import MockRuntimeBackend
from backend.app.runtime.models import (
    ContainerHandle,
    JobIdentity,
    ManagedObjects,
    RunResult,
    RuntimeKind,
    TerminalClassification,
)
from backend.tests.runtime.support import (
    ARCHIVE,
    ARCHIVE_BYTES,
    ARCHIVE_LIMITS,
    ARTIFACT,
    ARTIFACT_ARCHIVE,
    ARTIFACT_ARCHIVE_LIMITS,
    IMAGE,
    POLICY,
    make_result,
    make_spec,
)


SECRET = "token=opentcad-secret C:\\Users\\operator\\private.deck"


class SecretWaitBackend(MockRuntimeBackend):
    async def wait(self, container: ContainerHandle) -> RunResult:
        raise RuntimeBackendError(
            ErrorCode.WAIT_FAILED,
            RuntimePhase.WAIT,
            backend=f"docker:{SECRET}",
            detail=SECRET,
        )


class CrossJobQueryBackend(MockRuntimeBackend):
    async def list_managed(self, job_id: str | None = None) -> ManagedObjects:
        if job_id is None:
            return await super().list_managed(job_id)
        foreign = ContainerHandle(
            RuntimeKind.MOCK,
            "foreign-container",
            "00000000-0000-4000-8000-000000009999",
        )
        return ManagedObjects(volumes=(), containers=(foreign,))


class BrokerSecurityContractTests(unittest.IsolatedAsyncioTestCase):
    def backend(self, **kwargs: object) -> MockRuntimeBackend:
        return MockRuntimeBackend(images=(IMAGE,), **kwargs)

    def broker(self, backend: MockRuntimeBackend, diagnostics=None) -> SandboxBroker:
        return SandboxBroker(backend, POLICY, ARCHIVE_LIMITS, diagnostics)

    async def prepare_running(self, backend: MockRuntimeBackend, job_id: str):
        spec = make_spec(job_id)
        validated = POLICY.validate(spec, (await backend.probe()).capabilities)
        volume = await backend.create_volume(validated.identity)
        await backend.stage_inputs(volume, validated, ARCHIVE)
        container = await backend.create_container(validated, volume)
        await backend.start(container)
        return validated, volume, container

    async def test_success_outcome_contains_only_validated_output_archive(self) -> None:
        backend = self.backend()
        job_id = "00000000-0000-4000-8000-000000000410"
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
        self.assertEqual(outcome.state, BrokerState.SUCCEEDED)
        self.assertEqual(outcome.artifact_archive.manifest, (ARTIFACT,))
        self.assertNotIn("r" * ARTIFACT.bytes, repr(outcome))
        self.assertNotIn("payload", json.dumps(outcome.as_dict()))

    async def test_substituted_output_bytes_fail_before_success_is_reported(self) -> None:
        backend = self.backend()
        job_id = "00000000-0000-4000-8000-000000000411"
        substituted = build_canonical_output_archive(
            (ArtifactPayload(ARTIFACT.name, b"x" * ARTIFACT.bytes),),
            (ARTIFACT.name,),
            ARTIFACT_ARCHIVE_LIMITS,
        )
        backend.plan_result(
            job_id,
            make_result(
                TerminalClassification.SUCCEEDED,
                exit_code=0,
                include_artifact=True,
            ),
            substituted,
        )
        outcome = await self.broker(backend).execute(
            BrokerRequest(make_spec(job_id), ARCHIVE_BYTES),
        )
        self.assertEqual(outcome.state, BrokerState.FAILED)
        self.assertEqual(outcome.error.code, ErrorCode.OUTPUT_ARCHIVE_REJECTED)
        self.assertIsNone(outcome.artifact_archive)
        self.assertTrue(outcome.cleanup_complete)
        self.assertEqual((await backend.list_managed(job_id)).containers, ())

    async def test_cancellation_uses_exact_identity_and_leaves_zero_objects(self) -> None:
        backend = self.backend()
        job_id = "00000000-0000-4000-8000-000000000412"
        validated, _, _ = await self.prepare_running(backend, job_id)
        outcome = await self.broker(backend).cancel(
            CancellationRequest(validated.identity),
        )
        self.assertEqual(outcome.state, BrokerState.CANCELLED)
        self.assertEqual(outcome.result.classification, TerminalClassification.CANCELLED)
        self.assertEqual(outcome.identity, JobIdentity(job_id))
        self.assertEqual(outcome.events[-1].state, BrokerState.CANCELLED)
        self.assertTrue(outcome.cleanup_complete)
        self.assertEqual((await backend.list_managed(job_id)).containers, ())
        self.assertEqual((await backend.list_managed(job_id)).volumes, ())

    async def test_missing_and_cross_job_cancellation_fail_closed(self) -> None:
        job_id = "00000000-0000-4000-8000-000000000413"
        missing_backend = self.backend()
        missing = await self.broker(missing_backend).cancel(
            CancellationRequest(JobIdentity(job_id)),
        )
        self.assertEqual(missing.state, BrokerState.FAILED)
        self.assertEqual(missing.error.code, ErrorCode.CONTAINER_NOT_FOUND)
        self.assertTrue(missing.cleanup_complete)

        volume_only_backend = self.backend()
        validated = POLICY.validate(
            make_spec(job_id),
            (await volume_only_backend.probe()).capabilities,
        )
        await volume_only_backend.create_volume(validated.identity)
        volume_only = await self.broker(volume_only_backend).cancel(
            CancellationRequest(validated.identity),
        )
        self.assertEqual(volume_only.error.code, ErrorCode.CONTAINER_NOT_FOUND)
        self.assertFalse(volume_only.cleanup_complete)
        self.assertEqual(len((await volume_only_backend.list_managed(job_id)).volumes), 1)

        cross_backend = CrossJobQueryBackend(images=(IMAGE,))
        cross = await self.broker(cross_backend).cancel(
            CancellationRequest(JobIdentity(job_id)),
        )
        self.assertEqual(cross.state, BrokerState.FAILED)
        self.assertEqual(cross.error.code, ErrorCode.IDENTITY_MISMATCH)
        self.assertEqual(cross.events[-1].phase, RuntimePhase.QUERY)
        self.assertFalse(cross.cleanup_complete)

    async def test_hostile_raw_diagnostic_is_internal_only(self) -> None:
        diagnostics = []
        backend = SecretWaitBackend(images=(IMAGE,))
        job_id = "00000000-0000-4000-8000-000000000414"
        outcome = await self.broker(backend, diagnostics.append).execute(
            BrokerRequest(make_spec(job_id), ARCHIVE_BYTES),
        )
        public = json.dumps(outcome.as_dict(), sort_keys=True)
        self.assertEqual(outcome.error.code, ErrorCode.WAIT_FAILED)
        self.assertIsNone(outcome.error.backend)
        self.assertNotIn(SECRET, public)
        self.assertNotIn(SECRET, repr(outcome))
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].raw_detail, SECRET)
        self.assertEqual(diagnostics[0].raw_backend, f"docker:{SECRET}")
        self.assertNotIn(SECRET, repr(diagnostics[0]))
        self.assertTrue(outcome.cleanup_complete)


if __name__ == "__main__":
    unittest.main()
