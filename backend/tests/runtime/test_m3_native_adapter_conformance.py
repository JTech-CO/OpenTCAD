from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from backend.app.runtime.errors import ErrorCode, RuntimeBackendError, RuntimePhase
from backend.app.runtime.models import RuntimeKind, TerminalClassification
from validation.native.m3_adapter_conformance import (
    CommandObservation,
    ContractError,
    ENTRYPOINTS,
    FIXTURE_FILES,
    FIXTURE_ROOT,
    NON_PROMOTION_FIELDS,
    NativeAdapterObserver,
    RuntimeTransport,
    ScenarioResources,
    _temporary_activation,
    fixture_source_sha256,
    image_from_arguments,
    local_image_inspection_proof,
    load_reviewed_plan,
    prepare_external_output,
    stable_error,
)


INDEX_DIGEST = "sha256:" + "a" * 64
PLATFORM_DIGEST = "sha256:" + "b" * 64
REFERENCE_BASE = "localhost:5001/opentcad-m3-runtime-fixture"
REFERENCE = f"{REFERENCE_BASE}@{INDEX_DIGEST}"


class M3NativeAdapterConformanceContractTests(unittest.TestCase):
    def test_temporary_activation_satisfies_dual_backend_gate_without_promoting(self) -> None:
        plan = load_reviewed_plan()
        image = image_from_arguments(
            REFERENCE,
            INDEX_DIGEST,
            PLATFORM_DIGEST,
            "linux/amd64",
            plan,
        )
        with TemporaryDirectory() as directory:
            activation = _temporary_activation(
                image,
                RuntimeKind.DOCKER,
                "2026-09-04T06:43:40.209209Z",
                Path(directory),
            )
        self.assertEqual(
            set(activation.approved_backends),
            {RuntimeKind.DOCKER, RuntimeKind.PODMAN},
        )
        for runtime in (RuntimeKind.DOCKER, RuntimeKind.PODMAN):
            for entrypoint in ENTRYPOINTS:
                self.assertTrue(
                    activation.permits(runtime, image, entrypoint.entrypoint_id),
                )

    def test_reviewed_plan_binds_fixture_and_never_promotes(self) -> None:
        plan = load_reviewed_plan()
        self.assertEqual(plan["fixture"]["files"], list(FIXTURE_FILES))
        self.assertEqual(plan["fixture"]["sourceSha256"], fixture_source_sha256())
        self.assertFalse(plan["fixture"]["observerPullsImage"])
        self.assertFalse(plan["fixture"]["observerBuildsImage"])
        self.assertFalse(plan["fixture"]["observerRemovesImage"])
        self.assertIs(
            plan["scenarios"][4]["streamingOutputTerminationProven"],
            True,
        )
        self.assertEqual(
            plan["requiredProofs"],
            {
                "streamingOutputTerminationProven": True,
                "offlineLocalImageInspectionProven": True,
                "manifestInspectCommands": 0,
            },
        )
        for field_name in (
            "qualified",
            "approvalGranted",
            "baselinePromotionAllowed",
            "releaseImageApproved",
            "solverApprovalGranted",
            "platformApprovalGranted",
        ):
            self.assertIs(plan[field_name], False)
        self.assertTrue(all(value is False for key, value in NON_PROMOTION_FIELDS.items() if key != "usesProductRuntimeAdapter"))
        self.assertIs(NON_PROMOTION_FIELDS["usesProductRuntimeAdapter"], True)

    def test_output_bomb_fixture_cannot_exit_naturally_after_overflow(self) -> None:
        source = (FIXTURE_ROOT / "workload-output-bomb").read_text(encoding="utf-8")
        self.assertIn("while [ \"$index\" -lt 8192 ]", source)
        self.assertIn("exec /usr/bin/sleep 86400", source)
        self.assertLess(
            source.index("while [ \"$index\" -lt 8192 ]"),
            source.index("exec /usr/bin/sleep 86400"),
        )

    def test_archive_import_does_not_combine_incompatible_tar_flags(self) -> None:
        source = (FIXTURE_ROOT / "archive-import").read_text(encoding="utf-8")
        self.assertIn("--keep-old-files", source)
        self.assertNotIn("--no-overwrite-dir", source)

    def test_archive_export_writes_python_canonical_ustar_fields(self) -> None:
        source = (FIXTURE_ROOT / "archive-export").read_text(encoding="utf-8")
        self.assertIn(
            '/usr/bin/dd if=/dev/zero of="$header" bs=512 count=1',
            source,
        )
        self.assertIn("write_field 257 'ustar\\00000'", source)
        self.assertNotIn("write_field 329", source)
        self.assertIn("write_field 148 '%06o\\000 '", source)
        self.assertNotIn("/usr/bin/tar", source)

    def test_runtime_backend_error_uses_stable_record_detail(self) -> None:
        error = RuntimeBackendError(
            ErrorCode.CLEANUP_FAILED,
            RuntimePhase.CLEANUP,
            detail="fixture-cleanup-rejected",
        )
        self.assertEqual(
            stable_error(error),
            {
                "type": "runtime-backend-error",
                "code": "cleanup-failed",
                "phase": "cleanup",
                "detail": "fixture-cleanup-rejected",
            },
        )

    def test_local_image_proof_requires_inspection_without_manifest_or_pull(self) -> None:
        image_inspect = CommandObservation(
            1,
            "image inspect",
            "a" * 64,
            0,
            None,
            "completed",
        )
        proof = local_image_inspection_proof((image_inspect,))
        self.assertIs(proof["offlineLocalImageInspectionProven"], True)
        self.assertEqual(proof["imageInspectCommands"], 1)
        self.assertEqual(proof["manifestInspectCommands"], 0)
        self.assertEqual(proof["imagePullCommands"], 0)

        manifest_inspect = CommandObservation(
            2,
            "manifest inspect",
            "b" * 64,
            0,
            None,
            "completed",
        )
        with_manifest = local_image_inspection_proof(
            (image_inspect, manifest_inspect),
        )
        self.assertIs(
            with_manifest["offlineLocalImageInspectionProven"],
            False,
        )
        self.assertEqual(with_manifest["manifestInspectCommands"], 1)

    def test_output_bomb_requires_streaming_command_termination_observation(self) -> None:
        async def run_case(record_termination: bool) -> dict[str, object]:
            observer = object.__new__(NativeAdapterObserver)
            observer.plan = {"resourceLimits": {"normalTimeoutMs": 10_000}}
            observer.runner = SimpleNamespace(command_count=0, observations=[])
            result = SimpleNamespace(
                classification=TerminalClassification.OUTPUT_LIMIT_EXCEEDED,
                output_truncated=True,
                captured_output_bytes=32_768,
                observed_output_bytes=32_769,
                output_limit_bytes=32_768,
            )

            class Bound:
                async def wait(self, container):
                    if record_termination:
                        observer.runner.observations.append(
                            CommandObservation(
                                1,
                                "container logs",
                                "c" * 64,
                                0,
                                None,
                                "output-limit-exceeded",
                            ),
                        )
                    return result

            async def prepare(resources, entrypoint_id, *, timeout_ms):
                self.assertEqual(entrypoint_id, "fixture-output-bomb")
                self.assertEqual(timeout_ms, 10_000)
                resources.container = object()
                return Bound(), object()

            observer._prepare_workload = prepare
            return await observer._output_bomb(ScenarioResources())

        proven = asyncio.run(run_case(True))
        unproven = asyncio.run(run_case(False))
        self.assertIs(proven["pass"], True)
        self.assertIs(proven["streamingOutputTerminationProven"], True)
        self.assertEqual(proven["outputLimitTerminationCommands"], 1)
        self.assertIs(unproven["pass"], False)
        self.assertIs(unproven["streamingOutputTerminationProven"], False)

    def test_cleanup_cannot_pass_when_adapter_cleanup_reports_errors(self) -> None:
        observer = object.__new__(NativeAdapterObserver)
        observer._shielded_emergency_cleanup = AsyncMock(
            return_value={
                "pass": True,
                "finalContainers": 0,
                "finalVolumes": 0,
            },
        )

        class FailingBound:
            async def remove_container(self, container):
                raise RuntimeBackendError(
                    ErrorCode.CLEANUP_FAILED,
                    RuntimePhase.CLEANUP,
                    detail="adapter-remove-rejected",
                )

        cleanup = asyncio.run(
            observer._cleanup_resources(
                ScenarioResources(
                    job_id="00000000-0000-4000-8000-000000000001",
                    bound=FailingBound(),
                    container=object(),
                ),
            ),
        )
        self.assertIs(cleanup["pass"], False)
        self.assertEqual(len(cleanup["adapterErrors"]), 2)
        self.assertEqual(
            cleanup["adapterErrors"][0]["detail"],
            "adapter-remove-rejected",
        )
        self.assertIs(cleanup["exactEmergencyCleanup"]["pass"], True)

    def test_windows_podman_transport_is_exact_wsl_debian_prefix(self) -> None:
        transport = RuntimeTransport.select(
            RuntimeKind.PODMAN,
            system_name="Windows",
            wsl_distribution="Debian",
        )
        self.assertEqual(transport.executable, "wsl.exe")
        self.assertEqual(
            transport.prefix,
            ("-d", "Debian", "--", "podman", "--cgroup-manager=cgroupfs"),
        )
        self.assertEqual(transport.distribution, "Debian")
        with self.assertRaises(ContractError):
            RuntimeTransport.select(
                RuntimeKind.PODMAN,
                system_name="Windows",
                wsl_distribution="Ubuntu",
            )

    def test_docker_and_posix_podman_have_no_operator_prefix(self) -> None:
        docker = RuntimeTransport.select(RuntimeKind.DOCKER, system_name="Windows")
        podman = RuntimeTransport.select(RuntimeKind.PODMAN, system_name="Linux")
        self.assertEqual((docker.executable, docker.prefix), ("docker.exe", ()))
        self.assertEqual((podman.executable, podman.prefix), ("podman", ()))
        with self.assertRaises(ContractError):
            RuntimeTransport.select(
                RuntimeKind.DOCKER,
                system_name="Windows",
                wsl_distribution="Debian",
            )

    def test_image_identity_requires_exact_loopback_repository_and_digest_pair(self) -> None:
        plan = load_reviewed_plan()
        image = image_from_arguments(
            REFERENCE,
            INDEX_DIGEST,
            PLATFORM_DIGEST,
            "linux/amd64",
            plan,
        )
        self.assertEqual(image.reference, REFERENCE)
        for reference, index_digest in (
            (f"localhost:5002/opentcad-m3-runtime-fixture@{INDEX_DIGEST}", INDEX_DIGEST),
            (f"user@localhost:5001/opentcad-m3-runtime-fixture@{INDEX_DIGEST}", INDEX_DIGEST),
            (f"{REFERENCE_BASE}:latest", INDEX_DIGEST),
            (REFERENCE, "sha256:" + "c" * 64),
        ):
            with self.subTest(reference=reference, index_digest=index_digest):
                with self.assertRaises(ContractError):
                    image_from_arguments(
                        reference,
                        index_digest,
                        PLATFORM_DIGEST,
                        "linux/amd64",
                        plan,
                    )

    def test_external_output_rejects_repository_and_existing_directory(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            repository.mkdir()
            outside = root / "external-observation"
            created = prepare_external_output(outside, repository)
            self.assertEqual(created, outside)
            self.assertTrue((created / "state").is_dir())
            with self.assertRaises(ContractError):
                prepare_external_output(created, repository)
            inside = repository / "raw-observation"
            with self.assertRaises(ContractError):
                prepare_external_output(inside, repository)


if __name__ == "__main__":
    unittest.main()
