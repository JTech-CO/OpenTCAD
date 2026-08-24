"""SandboxBroker state, cleanup, and reconciliation contract tests."""

import unittest

from backend.app.broker import BrokerRequest, BrokerState, SandboxBroker
from backend.app.runtime.errors import ErrorCode, RuntimeBackendError, RuntimePhase
from backend.app.runtime.mock_backend import MockRuntimeBackend, full_mock_capabilities
from backend.app.runtime.models import ContainerHandle, RunResult, TerminalClassification

from backend.tests.runtime.support import (
    ARCHIVE,
    ARCHIVE_BYTES,
    ARCHIVE_LIMITS,
    ARTIFACT,
    IMAGE,
    POLICY,
    make_result,
    make_spec,
)


class WaitFailureBackend(MockRuntimeBackend):
    async def wait(self, container: ContainerHandle) -> RunResult:
        raise RuntimeBackendError(
            ErrorCode.WAIT_FAILED,
            RuntimePhase.WAIT,
            backend=self.name.value,
        )


class LeakyBackend(MockRuntimeBackend):
    async def remove_container(self, container: ContainerHandle) -> None:
        return None

    async def remove_volume(self, volume) -> None:
        return None


class BrokerOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    def backend(self, **kwargs: object) -> MockRuntimeBackend:
        return MockRuntimeBackend(images=(IMAGE,), **kwargs)

    def broker(self, backend: MockRuntimeBackend) -> SandboxBroker:
        return SandboxBroker(backend, POLICY, ARCHIVE_LIMITS)

    async def test_success_is_redacted_and_leaves_zero_managed_objects(self) -> None:
        backend = self.backend()
        broker = self.broker(backend)
        job_id = "00000000-0000-4000-8000-000000000200"
        backend.plan_result(
            job_id,
            make_result(
                TerminalClassification.SUCCEEDED,
                exit_code=0,
                include_artifact=True,
            ),
        )
        outcome = await broker.execute(BrokerRequest(make_spec(job_id), ARCHIVE_BYTES))
        self.assertEqual(outcome.state, BrokerState.SUCCEEDED)
        self.assertEqual(outcome.artifacts, (ARTIFACT,))
        self.assertTrue(outcome.cleanup_complete)
        self.assertIsNone(outcome.error)
        self.assertEqual(outcome.events[-1].state, BrokerState.SUCCEEDED)
        self.assertEqual((await backend.list_managed()).containers, ())
        self.assertEqual((await backend.list_managed()).volumes, ())

    async def test_invalid_archive_fails_before_runtime_objects_exist(self) -> None:
        backend = self.backend()
        outcome = await self.broker(backend).execute(
            BrokerRequest(
                make_spec("00000000-0000-4000-8000-000000000201"),
                ARCHIVE_BYTES + b"\0" * 512,
            ),
        )
        self.assertEqual(outcome.state, BrokerState.FAILED)
        self.assertEqual(outcome.error.code, ErrorCode.INPUT_ARCHIVE_REJECTED)
        self.assertTrue(outcome.cleanup_complete)
        self.assertEqual((await backend.list_managed()).volumes, ())

    async def test_wait_failure_kills_then_cleans_container_and_volume(self) -> None:
        backend = WaitFailureBackend(images=(IMAGE,))
        outcome = await self.broker(backend).execute(
            BrokerRequest(
                make_spec("00000000-0000-4000-8000-000000000202"),
                ARCHIVE_BYTES,
            ),
        )
        self.assertEqual(outcome.error.code, ErrorCode.WAIT_FAILED)
        self.assertTrue(outcome.cleanup_complete)
        self.assertEqual((await backend.list_managed()).containers, ())
        self.assertEqual((await backend.list_managed()).volumes, ())

    async def test_missing_artifact_is_stable_and_cleanup_still_completes(self) -> None:
        backend = self.backend()
        job_id = "00000000-0000-4000-8000-000000000203"
        outcome = await self.broker(backend).execute(BrokerRequest(make_spec(job_id), ARCHIVE_BYTES))
        self.assertEqual(outcome.error.code, ErrorCode.ARTIFACT_REJECTED)
        self.assertTrue(outcome.cleanup_complete)
        self.assertEqual((await backend.list_managed()).containers, ())

    async def test_twenty_mixed_outcomes_end_with_zero_managed_objects(self) -> None:
        backend = self.backend()
        broker = self.broker(backend)
        for index in range(20):
            job_id = f"00000000-0000-4000-8000-{index + 300:012d}"
            mode = index % 3
            if mode == 0:
                backend.plan_result(
                    job_id,
                    make_result(
                        TerminalClassification.SUCCEEDED,
                        exit_code=0,
                        include_artifact=True,
                    ),
                )
            elif mode == 1:
                backend.plan_result(
                    job_id,
                    make_result(TerminalClassification.NONZERO_EXIT, exit_code=1),
                )
            else:
                backend.plan_result(
                    job_id,
                    make_result(TerminalClassification.CANCELLED, exit_code=None),
                )
            outcome = await broker.execute(BrokerRequest(make_spec(job_id), ARCHIVE_BYTES))
            expected = BrokerState.SUCCEEDED if mode == 0 else BrokerState.FAILED
            self.assertEqual(outcome.state, expected)
            self.assertTrue(outcome.cleanup_complete)
            self.assertEqual((await backend.list_managed(job_id)).containers, ())
            self.assertEqual((await backend.list_managed(job_id)).volumes, ())
        self.assertEqual((await backend.list_managed()).containers, ())
        self.assertEqual((await backend.list_managed()).volumes, ())

    async def test_reconcile_removes_preexisting_running_job(self) -> None:
        backend = self.backend()
        broker = self.broker(backend)
        job_id = "00000000-0000-4000-8000-000000000204"
        spec = make_spec(job_id)
        capabilities = (await backend.probe()).capabilities
        validated = POLICY.validate(spec, capabilities)
        volume = await backend.create_volume(job_id)
        await backend.stage_inputs(volume, validated, ARCHIVE)
        container = await backend.create_container(validated, volume)
        await backend.start(container)

        report = await broker.reconcile(job_id)
        self.assertTrue(report.complete)
        self.assertEqual(report.containers_removed, 1)
        self.assertEqual(report.volumes_removed, 1)
        self.assertEqual((await backend.list_managed(job_id)).containers, ())

    async def test_residual_objects_turn_cleanup_into_stable_failure(self) -> None:
        backend = LeakyBackend(images=(IMAGE,))
        job_id = "00000000-0000-4000-8000-000000000206"
        backend.plan_result(
            job_id,
            make_result(
                TerminalClassification.SUCCEEDED,
                exit_code=0,
                include_artifact=True,
            ),
        )
        outcome = await self.broker(backend).execute(
            BrokerRequest(make_spec(job_id), ARCHIVE_BYTES),
        )
        self.assertFalse(outcome.cleanup_complete)
        self.assertEqual(outcome.cleanup_error.code, ErrorCode.CLEANUP_FAILED)
        self.assertEqual(len((await backend.list_managed(job_id)).containers), 1)

    async def test_capability_downgrade_fails_before_archive_staging(self) -> None:
        backend = self.backend(capabilities=full_mock_capabilities(network_none=False))
        outcome = await self.broker(backend).execute(
            BrokerRequest(
                make_spec("00000000-0000-4000-8000-000000000205"),
                ARCHIVE_BYTES,
            ),
        )
        self.assertEqual(outcome.error.code, ErrorCode.CAPABILITY_MISSING)
        self.assertEqual((await backend.list_managed()).volumes, ())


if __name__ == "__main__":
    unittest.main()
