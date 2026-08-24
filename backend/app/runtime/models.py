"""Immutable models crossing the worker, broker, and runtime boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from hmac import compare_digest
import re
from uuid import UUID

from .errors import ErrorCode, RuntimeBackendError, RuntimePhase


SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
HANDLE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
FILE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _invalid(detail: str) -> None:
    raise RuntimeBackendError(
        ErrorCode.INVALID_SPEC,
        RuntimePhase.VALIDATE,
        detail=detail,
    )


def _require_digest(value: str, field: str) -> None:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        _invalid(f"{field}:sha256-required")


def _require_hash(value: str, field: str) -> None:
    if not isinstance(value, str) or HASH_PATTERN.fullmatch(value) is None:
        _invalid(f"{field}:sha256-hex-required")


def _require_identifier(value: str, field: str) -> None:
    if not isinstance(value, str) or IDENTIFIER_PATTERN.fullmatch(value) is None:
        _invalid(f"{field}:identifier-required")


def _require_uuid(value: str, field: str) -> None:
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError):
        _invalid(f"{field}:uuid-required")
    if str(parsed) != value:
        _invalid(f"{field}:canonical-uuid-required")


def _require_file_name(value: str, field: str) -> None:
    if (
        not isinstance(value, str)
        or FILE_NAME_PATTERN.fullmatch(value) is None
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        _invalid(f"{field}:single-file-name-required")


def _require_handle(value: str, field: str) -> None:
    if not isinstance(value, str) or HANDLE_PATTERN.fullmatch(value) is None:
        _invalid(f"{field}:opaque-handle-required")


class RuntimeKind(StrEnum):
    DOCKER = "docker"
    PODMAN = "podman"
    MOCK = "mock"


class RuntimeHealth(StrEnum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class JobKind(StrEnum):
    SUPREM = "suprem"
    REMESH = "remesh"
    DEVSIM = "devsim"


class TerminalClassification(StrEnum):
    SUCCEEDED = "succeeded"
    NONZERO_EXIT = "nonzero-exit"
    TIMED_OUT = "timed-out"
    CANCELLED = "cancelled"
    OUTPUT_LIMIT_EXCEEDED = "output-limit-exceeded"
    OOM_KILLED = "oom-killed"
    RUNTIME_ERROR = "runtime-error"


class TerminationReason(StrEnum):
    TIMEOUT = "timeout"
    CANCELLATION = "cancellation"
    OUTPUT_LIMIT = "output-limit"
    SHUTDOWN = "shutdown"


@dataclass(frozen=True, slots=True)
class JobIdentity:
    """One policy-derived identity shared by every job kind and lifecycle phase."""

    job_id: str

    def __post_init__(self) -> None:
        _require_uuid(self.job_id, "identity.job_id")

    @property
    def label(self) -> tuple[str, str]:
        return ("tcad.job_id", self.job_id)

    @property
    def object_name(self) -> str:
        return f"opentcad-job-{self.job_id}"

    @property
    def volume_name(self) -> str:
        return f"{self.object_name}-data"


@dataclass(frozen=True, slots=True)
class ImageIdentity:
    reference: str
    index_digest: str
    platform_manifest_digest: str
    platform: str

    def __post_init__(self) -> None:
        _require_digest(self.index_digest, "image.index_digest")
        _require_digest(self.platform_manifest_digest, "image.platform_manifest_digest")
        reference_base = self.reference.split("@", maxsplit=1)[0]
        if (
            not reference_base
            or any(character.isspace() for character in reference_base)
            or self.reference != f"{reference_base}@{self.index_digest}"
        ):
            _invalid("image.reference:digest-pinned-reference-required")
        if self.platform not in {"linux/amd64", "linux/arm64"}:
            _invalid("image.platform:unsupported")


@dataclass(frozen=True, slots=True)
class InputFile:
    name: str
    sha256: str
    bytes: int

    def __post_init__(self) -> None:
        _require_file_name(self.name, "input.name")
        _require_hash(self.sha256, "input.sha256")
        if not isinstance(self.bytes, int) or isinstance(self.bytes, bool) or self.bytes < 1:
            _invalid("input.bytes:positive-integer-required")


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    cpu_millis: int
    memory_bytes: int
    pids: int
    timeout_ms: int
    output_bytes: int
    file_count: int
    artifact_bytes: int
    tmpfs_bytes: int

    def __post_init__(self) -> None:
        ranges = {
            "cpu_millis": (1, 64_000),
            "memory_bytes": (1_048_576, 274_877_906_944),
            "pids": (1, 4_096),
            "timeout_ms": (100, 86_400_000),
            "output_bytes": (1_024, 1_073_741_824),
            "file_count": (1, 100_000),
            "artifact_bytes": (1_024, 1_099_511_627_776),
            "tmpfs_bytes": (1_024, 17_179_869_184),
        }
        for field, (minimum, maximum) in ranges.items():
            value = getattr(self, field)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < minimum
                or value > maximum
            ):
                _invalid(f"limits.{field}:out-of-contract-range")

    def exceeds(self, maximum: ResourceLimits) -> tuple[str, ...]:
        return tuple(
            field
            for field in self.__dataclass_fields__
            if getattr(self, field) > getattr(maximum, field)
        )


@dataclass(frozen=True, slots=True)
class SandboxSpec:
    job_id: str
    profile_id: str
    kind: JobKind
    image: ImageIdentity
    input_manifest: tuple[InputFile, ...]
    limits: ResourceLimits
    environment_profile: str
    expected_outputs: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_uuid(self.job_id, "job_id")
        _require_identifier(self.profile_id, "profile_id")
        if not isinstance(self.kind, JobKind):
            _invalid("kind:enum-required")
        _require_identifier(self.environment_profile, "environment_profile")
        inputs = tuple(self.input_manifest)
        outputs = tuple(self.expected_outputs)
        object.__setattr__(self, "input_manifest", inputs)
        object.__setattr__(self, "expected_outputs", outputs)
        if not inputs:
            _invalid("input_manifest:non-empty-required")
        if not outputs:
            _invalid("expected_outputs:non-empty-required")
        for index, item in enumerate(inputs):
            if not isinstance(item, InputFile):
                _invalid(f"input_manifest[{index}]:input-file-required")
        for index, output in enumerate(outputs):
            _require_file_name(output, f"expected_outputs[{index}]")
        input_names = [item.name for item in inputs]
        if len(set(input_names)) != len(input_names):
            _invalid("input_manifest:duplicate-name")
        if len({name.casefold() for name in input_names}) != len(input_names):
            _invalid("input_manifest:case-collision")
        if len(set(outputs)) != len(outputs):
            _invalid("expected_outputs:duplicate-name")
        if len({name.casefold() for name in outputs}) != len(outputs):
            _invalid("expected_outputs:case-collision")


CAPABILITY_FIELDS = (
    "image_inspect",
    "image_pull",
    "image_digest",
    "managed_volumes",
    "validated_input_transfer",
    "container_lifecycle",
    "bounded_output",
    "cpu_limit",
    "memory_limit",
    "pids_limit",
    "timeout",
    "network_none",
    "cap_drop_all",
    "no_new_privileges",
    "read_only_root",
    "writable_tmpfs_control",
    "fixed_non_root_user",
    "labels",
    "orphan_query",
    "validated_artifact_transfer",
)


@dataclass(frozen=True, slots=True)
class RuntimeCapabilities:
    backend: RuntimeKind
    version: str
    operating_system: str
    architecture: str
    rootless: bool
    image_inspect: bool
    image_pull: bool
    image_digest: bool
    managed_volumes: bool
    validated_input_transfer: bool
    container_lifecycle: bool
    bounded_output: bool
    cpu_limit: bool
    memory_limit: bool
    pids_limit: bool
    timeout: bool
    network_none: bool
    cap_drop_all: bool
    no_new_privileges: bool
    read_only_root: bool
    writable_tmpfs_control: bool
    fixed_non_root_user: bool
    labels: bool
    orphan_query: bool
    validated_artifact_transfer: bool

    def __post_init__(self) -> None:
        if not isinstance(self.backend, RuntimeKind):
            _invalid("capabilities.backend:enum-required")
        if not isinstance(self.version, str) or not self.version:
            _invalid("capabilities.version:required")
        if self.operating_system != "linux":
            _invalid("capabilities.operating_system:linux-required")
        if self.architecture not in {"amd64", "arm64"}:
            _invalid("capabilities.architecture:unsupported")
        if not isinstance(self.rootless, bool):
            _invalid("capabilities.rootless:boolean-required")
        for field in CAPABILITY_FIELDS:
            if not isinstance(getattr(self, field), bool):
                _invalid(f"capabilities.{field}:boolean-required")

    def missing(self, required: tuple[str, ...] = CAPABILITY_FIELDS) -> tuple[str, ...]:
        unknown = tuple(field for field in required if field not in CAPABILITY_FIELDS)
        if unknown:
            _invalid("capabilities.required:unknown-field")
        return tuple(field for field in required if not getattr(self, field))


@dataclass(frozen=True, slots=True)
class RuntimeProbe:
    health: RuntimeHealth
    capabilities: RuntimeCapabilities | None

    def __post_init__(self) -> None:
        if not isinstance(self.health, RuntimeHealth):
            _invalid("probe.health:enum-required")
        if self.health is RuntimeHealth.AVAILABLE and self.capabilities is None:
            _invalid("probe.capabilities:required-when-available")
        if self.health is RuntimeHealth.UNAVAILABLE and self.capabilities is not None:
            _invalid("probe.capabilities:forbidden-when-unavailable")


@dataclass(frozen=True, slots=True)
class VolumeHandle:
    backend: RuntimeKind
    opaque_id: str
    job_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.backend, RuntimeKind):
            _invalid("volume.backend:enum-required")
        _require_handle(self.opaque_id, "volume.opaque_id")
        _require_uuid(self.job_id, "volume.job_id")


@dataclass(frozen=True, slots=True)
class ContainerHandle:
    backend: RuntimeKind
    opaque_id: str
    job_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.backend, RuntimeKind):
            _invalid("container.backend:enum-required")
        _require_handle(self.opaque_id, "container.opaque_id")
        _require_uuid(self.job_id, "container.job_id")


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    name: str
    sha256: str
    bytes: int

    def __post_init__(self) -> None:
        _require_file_name(self.name, "artifact.name")
        _require_hash(self.sha256, "artifact.sha256")
        if not isinstance(self.bytes, int) or isinstance(self.bytes, bool) or self.bytes < 0:
            _invalid("artifact.bytes:non-negative-integer-required")


@dataclass(frozen=True, slots=True)
class RawArtifactArchive:
    """Untrusted runtime bytes. The payload is intentionally absent from repr."""

    _payload: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self._payload, bytes):
            _invalid("raw_artifact_archive.payload:bytes-required")

    @property
    def payload(self) -> bytes:
        return self._payload


@dataclass(frozen=True, slots=True)
class RunResult:
    classification: TerminalClassification
    exit_code: int | None
    duration_ms: int
    output_limit_bytes: int
    observed_output_bytes: int
    captured_output_bytes: int
    output_truncated: bool
    stdout_sha256: str
    stderr_sha256: str
    artifacts: tuple[ArtifactRecord, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.classification, TerminalClassification):
            _invalid("result.classification:enum-required")
        if self.exit_code is not None and (
            not isinstance(self.exit_code, int)
            or isinstance(self.exit_code, bool)
            or self.exit_code < 0
            or self.exit_code > 255
        ):
            _invalid("result.exit_code:integer-or-null-required")
        if self.classification is TerminalClassification.SUCCEEDED and self.exit_code != 0:
            _invalid("result.exit_code:success-requires-zero")
        if self.classification is TerminalClassification.NONZERO_EXIT and (
            not isinstance(self.exit_code, int)
            or isinstance(self.exit_code, bool)
            or self.exit_code < 1
            or self.exit_code > 255
        ):
            _invalid("result.exit_code:nonzero-required")
        for field in (
            "duration_ms",
            "output_limit_bytes",
            "observed_output_bytes",
            "captured_output_bytes",
        ):
            value = getattr(self, field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                _invalid(f"result.{field}:non-negative-integer-required")
        if self.output_limit_bytes < 1:
            _invalid("result.output_limit_bytes:positive-required")
        if self.captured_output_bytes > self.output_limit_bytes:
            _invalid("result.captured_output_bytes:over-limit")
        if self.captured_output_bytes > self.observed_output_bytes:
            _invalid("result.captured_output_bytes:over-observed")
        if not isinstance(self.output_truncated, bool):
            _invalid("result.output_truncated:boolean-required")
        if self.output_truncated != (self.observed_output_bytes > self.captured_output_bytes):
            _invalid("result.output_truncated:inconsistent")
        _require_hash(self.stdout_sha256, "result.stdout_sha256")
        _require_hash(self.stderr_sha256, "result.stderr_sha256")
        artifacts = tuple(self.artifacts)
        object.__setattr__(self, "artifacts", artifacts)
        for index, artifact in enumerate(artifacts):
            if not isinstance(artifact, ArtifactRecord):
                _invalid(f"result.artifacts[{index}]:artifact-record-required")
        names = [artifact.name for artifact in artifacts]
        if len(set(names)) != len(names):
            _invalid("result.artifacts:duplicate-name")


@dataclass(frozen=True, slots=True)
class ManagedObjects:
    volumes: tuple[VolumeHandle, ...]
    containers: tuple[ContainerHandle, ...]

    def __post_init__(self) -> None:
        volumes = tuple(self.volumes)
        containers = tuple(self.containers)
        if any(not isinstance(item, VolumeHandle) for item in volumes):
            _invalid("managed.volumes:volume-handle-required")
        if any(not isinstance(item, ContainerHandle) for item in containers):
            _invalid("managed.containers:container-handle-required")
        object.__setattr__(self, "volumes", volumes)
        object.__setattr__(self, "containers", containers)


_ARTIFACT_ARCHIVE_MARKER = object()


@dataclass(frozen=True, slots=True, init=False)
class ValidatedArtifactArchive:
    manifest: tuple[ArtifactRecord, ...]
    archive_sha256: str
    bytes: int
    _payload: bytes = field(repr=False)

    def __init__(
        self,
        manifest: tuple[ArtifactRecord, ...],
        archive_sha256: str,
        byte_count: int,
        payload: bytes,
        *,
        _marker: object,
    ) -> None:
        if _marker is not _ARTIFACT_ARCHIVE_MARKER:
            _invalid("validated_artifact_archive:validator-construction-required")
        records = tuple(manifest)
        if not records or any(not isinstance(item, ArtifactRecord) for item in records):
            _invalid("validated_artifact_archive.manifest:artifact-records-required")
        _require_hash(archive_sha256, "validated_artifact_archive.archive_sha256")
        if (
            not isinstance(byte_count, int)
            or isinstance(byte_count, bool)
            or byte_count < 1
        ):
            _invalid("validated_artifact_archive.bytes:positive-integer-required")
        if not isinstance(payload, bytes) or len(payload) != byte_count:
            _invalid("validated_artifact_archive.payload:exact-bytes-required")
        if not compare_digest(sha256(payload).hexdigest(), archive_sha256):
            _invalid("validated_artifact_archive.payload:hash-mismatch")
        object.__setattr__(self, "manifest", records)
        object.__setattr__(self, "archive_sha256", archive_sha256)
        object.__setattr__(self, "bytes", byte_count)
        object.__setattr__(self, "_payload", payload)

    @property
    def payload(self) -> bytes:
        return self._payload


def _make_validated_artifact_archive(
    manifest: tuple[ArtifactRecord, ...],
    archive_sha256: str,
    byte_count: int,
    payload: bytes,
) -> ValidatedArtifactArchive:
    return ValidatedArtifactArchive(
        manifest,
        archive_sha256,
        byte_count,
        payload,
        _marker=_ARTIFACT_ARCHIVE_MARKER,
    )


_INPUT_ARCHIVE_MARKER = object()


@dataclass(frozen=True, slots=True, init=False)
class ValidatedInputArchive:
    manifest: tuple[InputFile, ...]
    archive_sha256: str
    bytes: int
    _payload: bytes = field(repr=False)

    def __init__(
        self,
        manifest: tuple[InputFile, ...],
        archive_sha256: str,
        byte_count: int,
        payload: bytes,
        *,
        _marker: object,
    ) -> None:
        if _marker is not _INPUT_ARCHIVE_MARKER:
            _invalid("validated_archive:validator-construction-required")
        records = tuple(manifest)
        if not records or any(not isinstance(item, InputFile) for item in records):
            _invalid("validated_archive.manifest:input-files-required")
        _require_hash(archive_sha256, "validated_archive.archive_sha256")
        if (
            not isinstance(byte_count, int)
            or isinstance(byte_count, bool)
            or byte_count < 1
        ):
            _invalid("validated_archive.bytes:positive-integer-required")
        if not isinstance(payload, bytes) or len(payload) != byte_count:
            _invalid("validated_archive.payload:exact-bytes-required")
        if not compare_digest(sha256(payload).hexdigest(), archive_sha256):
            _invalid("validated_archive.payload:hash-mismatch")
        object.__setattr__(self, "manifest", records)
        object.__setattr__(self, "archive_sha256", archive_sha256)
        object.__setattr__(self, "bytes", byte_count)
        object.__setattr__(self, "_payload", payload)

    @property
    def payload(self) -> bytes:
        return self._payload


def _make_validated_input_archive(
    manifest: tuple[InputFile, ...],
    archive_sha256: str,
    byte_count: int,
    payload: bytes,
) -> ValidatedInputArchive:
    return ValidatedInputArchive(
        manifest,
        archive_sha256,
        byte_count,
        payload,
        _marker=_INPUT_ARCHIVE_MARKER,
    )


_VALIDATION_MARKER = object()


@dataclass(frozen=True, slots=True, init=False)
class ValidatedSandboxSpec:
    spec: SandboxSpec
    policy_version: str
    entrypoint_id: str
    labels: tuple[tuple[str, str], ...]
    identity: JobIdentity

    def __init__(
        self,
        spec: SandboxSpec,
        policy_version: str,
        entrypoint_id: str,
        labels: tuple[tuple[str, str], ...],
        identity: JobIdentity,
        *,
        _marker: object,
    ) -> None:
        if _marker is not _VALIDATION_MARKER:
            _invalid("validated_spec:policy-construction-required")
        if not isinstance(spec, SandboxSpec):
            _invalid("validated_spec.spec:sandbox-spec-required")
        if not isinstance(identity, JobIdentity) or identity.job_id != spec.job_id:
            _invalid("validated_spec.identity:job-identity-required")
        normalized_labels = tuple(labels)
        if identity.label not in normalized_labels:
            _invalid("validated_spec.labels:job-identity-required")
        object.__setattr__(self, "spec", spec)
        object.__setattr__(self, "policy_version", policy_version)
        object.__setattr__(self, "entrypoint_id", entrypoint_id)
        object.__setattr__(self, "labels", normalized_labels)
        object.__setattr__(self, "identity", identity)


def _make_validated_spec(
    spec: SandboxSpec,
    policy_version: str,
    entrypoint_id: str,
    labels: tuple[tuple[str, str], ...],
    identity: JobIdentity,
) -> ValidatedSandboxSpec:
    return ValidatedSandboxSpec(
        spec,
        policy_version,
        entrypoint_id,
        labels,
        identity,
        _marker=_VALIDATION_MARKER,
    )
