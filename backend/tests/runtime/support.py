"""Deterministic fixtures containing no solver or runtime dependency."""

from backend.app.runtime.models import (
    ArtifactRecord,
    ImageIdentity,
    InputFile,
    JobKind,
    ResourceLimits,
    RunResult,
    SandboxSpec,
    TerminalClassification,
)
from backend.app.runtime.policy import EngineProfile, SandboxPolicy


IMAGE = ImageIdentity(
    reference="registry.invalid/opentcad/test@sha256:" + "a" * 64,
    index_digest="sha256:" + "a" * 64,
    platform_manifest_digest="sha256:" + "b" * 64,
    platform="linux/amd64",
)
INPUT = InputFile(name="input.in", sha256="c" * 64, bytes=128)
ARTIFACT = ArtifactRecord(name="result.str", sha256="d" * 64, bytes=256)
LIMITS = ResourceLimits(
    cpu_millis=500,
    memory_bytes=67_108_864,
    pids=32,
    timeout_ms=5_000,
    output_bytes=32_768,
    file_count=8,
    artifact_bytes=1_048_576,
    tmpfs_bytes=8_388_608,
)
MAXIMUM_LIMITS = ResourceLimits(
    cpu_millis=2_000,
    memory_bytes=268_435_456,
    pids=128,
    timeout_ms=60_000,
    output_bytes=1_048_576,
    file_count=64,
    artifact_bytes=16_777_216,
    tmpfs_bytes=67_108_864,
)
PROFILE = EngineProfile(
    profile_id="test-process",
    kind=JobKind.SUPREM,
    image=IMAGE,
    environment_profile="test-env",
    entrypoint_id="test-entrypoint",
    required_inputs=("input.in",),
    expected_outputs=("result.str",),
)
POLICY = SandboxPolicy(
    version="m2-contract-v1",
    engine_profiles=(PROFILE,),
    maximum_limits=MAXIMUM_LIMITS,
    maximum_input_bytes=1_048_576,
)


def make_spec(job_id: str) -> SandboxSpec:
    return SandboxSpec(
        job_id=job_id,
        profile_id=PROFILE.profile_id,
        kind=PROFILE.kind,
        image=IMAGE,
        input_manifest=(INPUT,),
        limits=LIMITS,
        environment_profile=PROFILE.environment_profile,
        expected_outputs=PROFILE.expected_outputs,
    )


def make_result(
    classification: TerminalClassification,
    *,
    exit_code: int | None,
    include_artifact: bool = False,
) -> RunResult:
    return RunResult(
        classification=classification,
        exit_code=exit_code,
        duration_ms=25,
        output_limit_bytes=LIMITS.output_bytes,
        observed_output_bytes=0,
        captured_output_bytes=0,
        output_truncated=False,
        stdout_sha256="e" * 64,
        stderr_sha256="f" * 64,
        artifacts=(ARTIFACT,) if include_artifact else (),
    )
