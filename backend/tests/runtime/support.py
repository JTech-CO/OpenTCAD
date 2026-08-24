"""Deterministic fixtures containing no solver or runtime dependency."""

from hashlib import sha256

from backend.app.broker.archive import (
    ArchiveLimits,
    InputPayload,
    build_canonical_input_archive,
    validate_canonical_input_archive,
)
from backend.app.broker.output_archive import (
    ArtifactPayload,
    build_canonical_output_archive,
    output_archive_limits,
)
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
INPUT_CONTENT = b"i" * 128
INPUT = InputFile(
    name="input.in",
    sha256=sha256(INPUT_CONTENT).hexdigest(),
    bytes=len(INPUT_CONTENT),
)
ARCHIVE_LIMITS = ArchiveLimits(
    max_archive_bytes=1_048_576,
    max_file_count=8,
    max_total_bytes=1_048_576,
)
ARCHIVE_BYTES = build_canonical_input_archive(
    (InputPayload(INPUT.name, INPUT_CONTENT),),
    (INPUT,),
    ARCHIVE_LIMITS,
)
ARCHIVE = validate_canonical_input_archive(ARCHIVE_BYTES, (INPUT,), ARCHIVE_LIMITS)
ARTIFACT_CONTENT = b"r" * 256
ARTIFACT = ArtifactRecord(
    name="result.str",
    sha256=sha256(ARTIFACT_CONTENT).hexdigest(),
    bytes=len(ARTIFACT_CONTENT),
)
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
ARTIFACT_ARCHIVE_LIMITS = output_archive_limits(
    LIMITS.artifact_bytes,
    LIMITS.file_count,
)
ARTIFACT_ARCHIVE = build_canonical_output_archive(
    (ArtifactPayload(ARTIFACT.name, ARTIFACT_CONTENT),),
    (ARTIFACT.name,),
    ARTIFACT_ARCHIVE_LIMITS,
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
