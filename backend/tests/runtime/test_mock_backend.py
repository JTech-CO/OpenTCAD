"""Reusable RuntimeBackend lifecycle contract exercised against the mock backend."""

import unittest

from backend.app.runtime.errors import ErrorCode, RuntimeBackendError
from backend.app.runtime.mock_backend import MockRuntimeBackend, full_mock_capabilities
from backend.app.runtime.models import (
    RuntimeHealth,
    TerminalClassification,
    TerminationReason,
)
from backend.app.runtime.protocol import RuntimeBackend

from .support import ARTIFACT, IMAGE, POLICY, make_result, make_spec


class MockRuntimeContractTests(unittest.IsolatedAsyncioTestCase):
    def backend(self, **kwargs: object) -> MockRuntimeBackend:
        return MockRuntimeBackend(images=(IMAGE,), **kwargs)

    async def prepare(
        self,
        backend: MockRuntimeBackend,
        job_id: str,
    ):
        spec = make_spec(job_id)
        validated = POLICY.validate(spec, (await backend.probe()).capabilities)
        await backend.ensure_image(IMAGE)
        volume = await backend.create_volume(job_id)
        await backend.stage_inputs(volume, validated)
        container = await backend.create_container(validated, volume)
        return validated, volume, container

    async def test_mock_satisfies_protocol_and_success_lifecycle(self) -> None:
        backend = self.backend()
        self.assertIsInstance(backend, RuntimeBackend)
        probe = await backend.probe()
        self.assertEqual(probe.health, RuntimeHealth.AVAILABLE)
        job_id = "00000000-0000-4000-8000-000000000010"
        _, volume, container = await self.prepare(backend, job_id)
        backend.plan_result(
            job_id,
            make_result(
                TerminalClassification.SUCCEEDED,
                exit_code=0,
                include_artifact=True,
            ),
        )
        await backend.start(container)
        result = await backend.wait(container)
        self.assertEqual(result.classification, TerminalClassification.SUCCEEDED)
        self.assertEqual(await backend.collect_artifacts(container), (ARTIFACT,))
        await backend.remove_container(container)
        await backend.remove_volume(volume)
        managed = await backend.list_managed(job_id)
        self.assertEqual(managed.containers, ())
        self.assertEqual(managed.volumes, ())

        rejected_job_id = "00000000-0000-4000-8000-000000000014"
        _, rejected_volume, rejected_container = await self.prepare(backend, rejected_job_id)
        backend.plan_result(
            rejected_job_id,
            make_result(TerminalClassification.SUCCEEDED, exit_code=0),
        )
        await backend.start(rejected_container)
        await backend.wait(rejected_container)
        with self.assertRaises(RuntimeBackendError) as rejected:
            await backend.collect_artifacts(rejected_container)
        self.assertEqual(rejected.exception.code, ErrorCode.ARTIFACT_REJECTED)
        await backend.remove_container(rejected_container)
        await backend.remove_volume(rejected_volume)

    async def test_unvalidated_spec_and_invalid_state_fail_stably(self) -> None:
        backend = self.backend()
        job_id = "00000000-0000-4000-8000-000000000011"
        raw = make_spec(job_id)
        volume = await backend.create_volume(job_id)
        with self.assertRaises(RuntimeBackendError) as unvalidated:
            await backend.stage_inputs(volume, raw)  # type: ignore[arg-type]
        self.assertEqual(unvalidated.exception.code, ErrorCode.INVALID_SPEC)

        validated = POLICY.validate(raw, (await backend.probe()).capabilities)
        await backend.stage_inputs(volume, validated)
        container = await backend.create_container(validated, volume)
        await backend.start(container)
        with self.assertRaises(RuntimeBackendError) as invalid_reason:
            await backend.kill(container, "timeout")  # type: ignore[arg-type]
        self.assertEqual(invalid_reason.exception.code, ErrorCode.INVALID_SPEC)
        with self.assertRaises(RuntimeBackendError) as running:
            await backend.remove_container(container)
        self.assertEqual(running.exception.code, ErrorCode.INVALID_STATE)

    async def test_runtime_unavailable_is_structured(self) -> None:
        backend = self.backend(available=False)
        probe = await backend.probe()
        self.assertEqual(probe.health, RuntimeHealth.UNAVAILABLE)
        self.assertIsNone(probe.capabilities)
        with self.assertRaises(RuntimeBackendError) as context:
            await backend.create_volume("00000000-0000-4000-8000-000000000012")
        self.assertEqual(context.exception.code, ErrorCode.RUNTIME_UNAVAILABLE)
        self.assertEqual(context.exception.as_dict()["retry"], "infrastructure")
        self.assertEqual(str(context.exception), "runtime-unavailable:volume")

    async def test_every_termination_reason_has_stable_classification(self) -> None:
        mapping = {
            TerminationReason.TIMEOUT: TerminalClassification.TIMED_OUT,
            TerminationReason.CANCELLATION: TerminalClassification.CANCELLED,
            TerminationReason.OUTPUT_LIMIT: TerminalClassification.OUTPUT_LIMIT_EXCEEDED,
            TerminationReason.SHUTDOWN: TerminalClassification.RUNTIME_ERROR,
        }
        for index, (reason, expected) in enumerate(mapping.items(), start=20):
            with self.subTest(reason=reason):
                backend = self.backend()
                job_id = f"00000000-0000-4000-8000-{index:012d}"
                _, volume, container = await self.prepare(backend, job_id)
                await backend.start(container)
                result = await backend.kill(container, reason)
                self.assertEqual(result.classification, expected)
                await backend.remove_container(container)
                await backend.remove_volume(volume)
                self.assertEqual((await backend.list_managed()).containers, ())

    async def test_twenty_case_mixed_loop_ends_with_zero_managed_objects(self) -> None:
        backend = self.backend()
        for index in range(20):
            job_id = f"00000000-0000-4000-8000-{index + 100:012d}"
            _, volume, container = await self.prepare(backend, job_id)
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
                await backend.start(container)
                await backend.wait(container)
                self.assertEqual(await backend.collect_artifacts(container), (ARTIFACT,))
            elif mode == 1:
                backend.plan_result(
                    job_id,
                    make_result(TerminalClassification.NONZERO_EXIT, exit_code=1),
                )
                await backend.start(container)
                result = await backend.wait(container)
                self.assertEqual(result.classification, TerminalClassification.NONZERO_EXIT)
            else:
                await backend.start(container)
                result = await backend.kill(container, TerminationReason.CANCELLATION)
                self.assertEqual(result.classification, TerminalClassification.CANCELLED)
            await backend.remove_container(container)
            await backend.remove_volume(volume)
            managed = await backend.list_managed(job_id)
            self.assertEqual(managed.containers, ())
            self.assertEqual(managed.volumes, ())
        self.assertEqual((await backend.list_managed()).containers, ())
        self.assertEqual((await backend.list_managed()).volumes, ())

    async def test_capability_downgrade_is_rejected_before_lifecycle(self) -> None:
        backend = self.backend(
            capabilities=full_mock_capabilities(network_none=False),
        )
        capabilities = (await backend.probe()).capabilities
        with self.assertRaises(RuntimeBackendError) as context:
            POLICY.validate(
                make_spec("00000000-0000-4000-8000-000000000013"),
                capabilities,
            )
        self.assertEqual(context.exception.code, ErrorCode.CAPABILITY_MISSING)
        self.assertEqual((await backend.list_managed()).containers, ())


if __name__ == "__main__":
    unittest.main()
