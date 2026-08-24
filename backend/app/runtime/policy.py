"""Fail-closed policy validation shared by every runtime backend."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ErrorCode, RuntimeBackendError, RuntimePhase
from .models import (
    ImageIdentity,
    JobKind,
    ResourceLimits,
    RuntimeCapabilities,
    SandboxSpec,
    ValidatedSandboxSpec,
    _make_validated_spec,
    _require_file_name,
    _require_identifier,
)


REQUIRED_EXECUTION_CAPABILITIES = (
    "image_inspect",
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


def _reject(code: ErrorCode, detail: str) -> None:
    raise RuntimeBackendError(code, RuntimePhase.VALIDATE, detail=detail)


@dataclass(frozen=True, slots=True)
class EngineProfile:
    profile_id: str
    kind: JobKind
    image: ImageIdentity
    environment_profile: str
    entrypoint_id: str
    required_inputs: tuple[str, ...]
    expected_outputs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.kind, JobKind):
            _reject(ErrorCode.INVALID_SPEC, "engine_profile.kind:enum-required")
        _require_identifier(self.profile_id, "engine_profile.profile_id")
        _require_identifier(self.environment_profile, "engine_profile.environment_profile")
        _require_identifier(self.entrypoint_id, "engine_profile.entrypoint_id")
        inputs = tuple(self.required_inputs)
        outputs = tuple(self.expected_outputs)
        object.__setattr__(self, "required_inputs", inputs)
        object.__setattr__(self, "expected_outputs", outputs)
        if not inputs or not outputs:
            _reject(ErrorCode.INVALID_SPEC, "engine_profile:file-contract-required")
        for index, name in enumerate(inputs):
            _require_file_name(name, f"engine_profile.required_inputs[{index}]")
        for index, name in enumerate(outputs):
            _require_file_name(name, f"engine_profile.expected_outputs[{index}]")
        if len(set(inputs)) != len(inputs) or len(set(outputs)) != len(outputs):
            _reject(ErrorCode.INVALID_SPEC, "engine_profile:duplicate-file-name")


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    version: str
    engine_profiles: tuple[EngineProfile, ...]
    maximum_limits: ResourceLimits
    maximum_input_bytes: int

    def __post_init__(self) -> None:
        _require_identifier(self.version, "policy.version")
        profiles = tuple(self.engine_profiles)
        object.__setattr__(self, "engine_profiles", profiles)
        if not profiles:
            _reject(ErrorCode.INVALID_SPEC, "policy:engine-profile-required")
        if any(not isinstance(profile, EngineProfile) for profile in profiles):
            _reject(ErrorCode.INVALID_SPEC, "policy:engine-profile-type-required")
        if not isinstance(self.maximum_limits, ResourceLimits):
            _reject(ErrorCode.INVALID_SPEC, "policy.maximum_limits:resource-limits-required")
        ids = [profile.profile_id for profile in profiles]
        if len(set(ids)) != len(ids):
            _reject(ErrorCode.INVALID_SPEC, "policy:duplicate-profile")
        if (
            not isinstance(self.maximum_input_bytes, int)
            or isinstance(self.maximum_input_bytes, bool)
            or self.maximum_input_bytes < 1
            or self.maximum_input_bytes > self.maximum_limits.artifact_bytes
        ):
            _reject(ErrorCode.INVALID_SPEC, "policy.maximum_input_bytes:out-of-range")

    def validate(
        self,
        spec: SandboxSpec,
        capabilities: RuntimeCapabilities,
    ) -> ValidatedSandboxSpec:
        if not isinstance(spec, SandboxSpec):
            _reject(ErrorCode.INVALID_SPEC, "spec:sandbox-spec-required")
        if not isinstance(capabilities, RuntimeCapabilities):
            _reject(ErrorCode.INVALID_SPEC, "capabilities:runtime-capabilities-required")
        missing = capabilities.missing(REQUIRED_EXECUTION_CAPABILITIES)
        if missing:
            _reject(ErrorCode.CAPABILITY_MISSING, ",".join(missing))

        profile = next(
            (
                candidate
                for candidate in self.engine_profiles
                if candidate.profile_id == spec.profile_id
            ),
            None,
        )
        if profile is None:
            _reject(ErrorCode.IMAGE_NOT_APPROVED, "profile:not-approved")
        if spec.kind is not profile.kind:
            _reject(ErrorCode.INVALID_SPEC, "kind:profile-mismatch")
        if spec.image != profile.image:
            _reject(ErrorCode.IMAGE_IDENTITY_MISMATCH, "image:profile-mismatch")
        if spec.environment_profile != profile.environment_profile:
            _reject(ErrorCode.INVALID_SPEC, "environment_profile:profile-mismatch")

        input_names = tuple(item.name for item in spec.input_manifest)
        if input_names != profile.required_inputs:
            _reject(ErrorCode.INVALID_SPEC, "input_manifest:profile-mismatch")
        if spec.expected_outputs != profile.expected_outputs:
            _reject(ErrorCode.INVALID_SPEC, "expected_outputs:profile-mismatch")
        if len(spec.input_manifest) > spec.limits.file_count:
            _reject(ErrorCode.INVALID_SPEC, "input_manifest:file-count-limit")
        if sum(item.bytes for item in spec.input_manifest) > self.maximum_input_bytes:
            _reject(ErrorCode.INVALID_SPEC, "input_manifest:byte-limit")

        exceeded = spec.limits.exceeds(self.maximum_limits)
        if exceeded:
            _reject(ErrorCode.INVALID_SPEC, "limits:" + ",".join(exceeded))

        labels = (
            ("tcad.job_id", spec.job_id),
            ("tcad.kind", spec.kind.value),
            ("tcad.version", self.version),
        )
        return _make_validated_spec(
            spec,
            self.version,
            profile.entrypoint_id,
            labels,
        )
