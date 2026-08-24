"""Fail-closed model and policy tests."""

from dataclasses import replace
import unittest

from backend.app.runtime.errors import ErrorCode, RuntimeBackendError, RuntimePhase
from backend.app.runtime.mock_backend import full_mock_capabilities
from backend.app.runtime.models import (
    ImageIdentity,
    InputFile,
    JobIdentity,
    ResourceLimits,
    SandboxSpec,
    ValidatedSandboxSpec,
)

from .support import IMAGE, LIMITS, POLICY, make_spec


JOB_ID = "00000000-0000-4000-8000-000000000001"


class ModelBoundaryTests(unittest.TestCase):
    def test_mutable_image_reference_is_rejected(self) -> None:
        digest = "sha256:" + "a" * 64
        for reference in (
            "registry.invalid/opentcad/test:latest",
            f"@{digest}",
            f"registry.invalid/open tcad/test@{digest}",
        ):
            with self.subTest(reference=reference), self.assertRaises(RuntimeBackendError) as context:
                ImageIdentity(
                    reference=reference,
                    index_digest=digest,
                    platform_manifest_digest="sha256:" + "b" * 64,
                    platform="linux/amd64",
                )
            self.assertEqual(context.exception.code, ErrorCode.INVALID_SPEC)

    def test_host_paths_and_archive_paths_are_not_file_names(self) -> None:
        for name in ("../input.in", "/tmp/input.in", "folder/input.in", "C:\\input.in"):
            with self.subTest(name=name), self.assertRaises(RuntimeBackendError):
                InputFile(name=name, sha256="c" * 64, bytes=1)
        with self.assertRaises(RuntimeBackendError) as context:
            replace(make_spec(JOB_ID), input_manifest=("input.in",))  # type: ignore[arg-type]
        self.assertEqual(context.exception.code, ErrorCode.INVALID_SPEC)

    def test_raw_command_is_not_a_sandbox_spec_field(self) -> None:
        source = make_spec(JOB_ID)
        values = {
            "job_id": JOB_ID,
            "profile_id": "test-process",
            "kind": source.kind,
            "image": IMAGE,
            "input_manifest": source.input_manifest,
            "limits": LIMITS,
            "environment_profile": "test-env",
            "expected_outputs": ("result.str",),
        }
        with self.assertRaises(TypeError):
            SandboxSpec(**values, command=("/bin/sh", "-c", "id"))

    def test_invalid_result_capture_cannot_exceed_limit(self) -> None:
        from backend.app.runtime.models import RunResult, TerminalClassification

        common = {
            "classification": TerminalClassification.SUCCEEDED,
            "exit_code": 0,
            "duration_ms": 1,
            "output_limit_bytes": 1,
            "observed_output_bytes": 0,
            "captured_output_bytes": 0,
            "output_truncated": False,
            "stdout_sha256": "e" * 64,
            "stderr_sha256": "f" * 64,
        }
        invalid = (
            {"observed_output_bytes": 2, "captured_output_bytes": 2},
            {"classification": TerminalClassification.TIMED_OUT, "exit_code": "137"},
            {"output_truncated": 0},
            {"artifacts": ("result.str",)},
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(RuntimeBackendError):
                RunResult(**(common | values))  # type: ignore[arg-type]


class SandboxPolicyTests(unittest.TestCase):
    def test_policy_creates_fixed_labels_and_entrypoint(self) -> None:
        validated = POLICY.validate(make_spec(JOB_ID), full_mock_capabilities())
        self.assertEqual(validated.entrypoint_id, "test-entrypoint")
        self.assertEqual(
            validated.labels,
            (
                ("tcad.job_id", JOB_ID),
                ("tcad.kind", "suprem"),
                ("tcad.version", "m2-contract-v1"),
            ),
        )

    def test_validated_spec_cannot_be_constructed_outside_policy(self) -> None:
        with self.assertRaises(RuntimeBackendError) as context:
            ValidatedSandboxSpec(
                make_spec(JOB_ID),
                "m2-contract-v1",
                "test-entrypoint",
                (),
                JobIdentity(JOB_ID),
                _marker=object(),
            )
        self.assertEqual(context.exception.code, ErrorCode.INVALID_SPEC)

    def test_missing_security_capability_fails_closed(self) -> None:
        capabilities = full_mock_capabilities(writable_tmpfs_control=False)
        with self.assertRaises(RuntimeBackendError) as context:
            POLICY.validate(make_spec(JOB_ID), capabilities)
        self.assertEqual(context.exception.code, ErrorCode.CAPABILITY_MISSING)
        self.assertEqual(context.exception.phase, RuntimePhase.VALIDATE)
        self.assertEqual(context.exception.as_dict()["detail"], "writable_tmpfs_control")

    def test_image_identity_and_environment_must_match_profile(self) -> None:
        drifted_image = replace(
            IMAGE,
            reference="registry.invalid/opentcad/test@sha256:" + "1" * 64,
            index_digest="sha256:" + "1" * 64,
        )
        for spec, expected in (
            (replace(make_spec(JOB_ID), image=drifted_image), ErrorCode.IMAGE_IDENTITY_MISMATCH),
            (replace(make_spec(JOB_ID), environment_profile="other-env"), ErrorCode.INVALID_SPEC),
        ):
            with self.subTest(expected=expected), self.assertRaises(RuntimeBackendError) as context:
                POLICY.validate(spec, full_mock_capabilities())
            self.assertEqual(context.exception.code, expected)

    def test_policy_maximum_cannot_be_silently_relaxed(self) -> None:
        over_limit = replace(
            LIMITS,
            memory_bytes=POLICY.maximum_limits.memory_bytes + 1,
        )
        with self.assertRaises(RuntimeBackendError) as context:
            POLICY.validate(replace(make_spec(JOB_ID), limits=over_limit), full_mock_capabilities())
        self.assertEqual(context.exception.code, ErrorCode.INVALID_SPEC)
        self.assertIn("memory_bytes", context.exception.as_dict()["detail"])


if __name__ == "__main__":
    unittest.main()
