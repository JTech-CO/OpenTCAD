"""In-memory RuntimeBackend used only for contract and broker tests."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from .errors import (
    ErrorCode,
    RetryDisposition,
    RuntimeBackendError,
    RuntimePhase,
)
from .models import (
    ArtifactRecord,
    ContainerHandle,
    ImageIdentity,
    ManagedObjects,
    RunResult,
    RuntimeCapabilities,
    RuntimeHealth,
    RuntimeKind,
    RuntimeProbe,
    TerminalClassification,
    TerminationReason,
    ValidatedInputArchive,
    ValidatedSandboxSpec,
    VolumeHandle,
    _require_uuid,
)


EMPTY_SHA256 = sha256(b"").hexdigest()


def full_mock_capabilities(**overrides: bool) -> RuntimeCapabilities:
    values: dict[str, object] = {
        "backend": RuntimeKind.MOCK,
        "version": "contract-v1",
        "operating_system": "linux",
        "architecture": "amd64",
        "rootless": True,
        "image_inspect": True,
        "image_pull": True,
        "image_digest": True,
        "managed_volumes": True,
        "validated_input_transfer": True,
        "container_lifecycle": True,
        "bounded_output": True,
        "cpu_limit": True,
        "memory_limit": True,
        "pids_limit": True,
        "timeout": True,
        "network_none": True,
        "cap_drop_all": True,
        "no_new_privileges": True,
        "read_only_root": True,
        "writable_tmpfs_control": True,
        "fixed_non_root_user": True,
        "labels": True,
        "orphan_query": True,
        "validated_artifact_transfer": True,
    }
    values.update(overrides)
    return RuntimeCapabilities(**values)  # type: ignore[arg-type]


@dataclass(slots=True)
class _MockVolume:
    handle: VolumeHandle
    inputs_staged: bool = False
    archive_sha256: str | None = None


@dataclass(slots=True)
class _MockContainer:
    handle: ContainerHandle
    volume: VolumeHandle
    validated_spec: ValidatedSandboxSpec
    state: str = "created"
    result: RunResult | None = None


class MockRuntimeBackend:
    """Strict lifecycle model. It never invokes a process or opens a runtime socket."""

    def __init__(
        self,
        *,
        images: tuple[ImageIdentity, ...],
        capabilities: RuntimeCapabilities | None = None,
        available: bool = True,
    ) -> None:
        self._capabilities = capabilities or full_mock_capabilities()
        if self._capabilities.backend is not RuntimeKind.MOCK:
            raise ValueError("Mock backend requires mock capabilities.")
        self._available = available
        self._images = {image.reference: image for image in images}
        self._volumes: dict[str, _MockVolume] = {}
        self._containers: dict[str, _MockContainer] = {}
        self._planned_results: dict[str, RunResult] = {}
        self._next_container = 1

    @property
    def name(self) -> RuntimeKind:
        return RuntimeKind.MOCK

    def plan_result(self, job_id: str, result: RunResult) -> None:
        _require_uuid(job_id, "mock.plan_result.job_id")
        self._planned_results[job_id] = result

    def _require_available(self, phase: RuntimePhase) -> None:
        if not self._available:
            raise RuntimeBackendError(
                ErrorCode.RUNTIME_UNAVAILABLE,
                phase,
                retry=RetryDisposition.INFRASTRUCTURE,
                backend=self.name.value,
            )

    def _volume(self, handle: VolumeHandle, phase: RuntimePhase) -> _MockVolume:
        if not isinstance(handle, VolumeHandle):
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                phase,
                backend=self.name.value,
                detail="volume-handle-required",
            )
        volume = self._volumes.get(handle.opaque_id)
        if volume is None or volume.handle != handle:
            raise RuntimeBackendError(
                ErrorCode.VOLUME_NOT_FOUND,
                phase,
                backend=self.name.value,
            )
        return volume

    def _container(self, handle: ContainerHandle, phase: RuntimePhase) -> _MockContainer:
        if not isinstance(handle, ContainerHandle):
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                phase,
                backend=self.name.value,
                detail="container-handle-required",
            )
        container = self._containers.get(handle.opaque_id)
        if container is None or container.handle != handle:
            raise RuntimeBackendError(
                ErrorCode.CONTAINER_NOT_FOUND,
                phase,
                backend=self.name.value,
            )
        return container

    @staticmethod
    def _invalid_state(phase: RuntimePhase, detail: str) -> RuntimeBackendError:
        return RuntimeBackendError(
            ErrorCode.INVALID_STATE,
            phase,
            backend=RuntimeKind.MOCK.value,
            detail=detail,
        )

    async def probe(self) -> RuntimeProbe:
        if not self._available:
            return RuntimeProbe(RuntimeHealth.UNAVAILABLE, None)
        return RuntimeProbe(RuntimeHealth.AVAILABLE, self._capabilities)

    async def inspect_image(self, image: ImageIdentity) -> ImageIdentity:
        self._require_available(RuntimePhase.IMAGE)
        observed = self._images.get(image.reference)
        if observed is None:
            raise RuntimeBackendError(
                ErrorCode.IMAGE_NOT_APPROVED,
                RuntimePhase.IMAGE,
                backend=self.name.value,
            )
        if observed != image:
            raise RuntimeBackendError(
                ErrorCode.IMAGE_IDENTITY_MISMATCH,
                RuntimePhase.IMAGE,
                backend=self.name.value,
            )
        return observed

    async def ensure_image(self, image: ImageIdentity) -> ImageIdentity:
        return await self.inspect_image(image)

    async def create_volume(self, job_id: str) -> VolumeHandle:
        self._require_available(RuntimePhase.VOLUME)
        _require_uuid(job_id, "volume.job_id")
        opaque_id = f"mock-volume-{job_id}"
        if opaque_id in self._volumes:
            raise RuntimeBackendError(
                ErrorCode.STALE_STATE,
                RuntimePhase.VOLUME,
                retry=RetryDisposition.INFRASTRUCTURE,
                backend=self.name.value,
            )
        handle = VolumeHandle(self.name, opaque_id, job_id)
        self._volumes[opaque_id] = _MockVolume(handle)
        return handle

    async def stage_inputs(
        self,
        volume: VolumeHandle,
        spec: ValidatedSandboxSpec,
        archive: ValidatedInputArchive,
    ) -> None:
        self._require_available(RuntimePhase.INPUT)
        if not isinstance(spec, ValidatedSandboxSpec):
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.INPUT,
                backend=self.name.value,
                detail="validated-spec-required",
            )
        if not isinstance(archive, ValidatedInputArchive):
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.INPUT,
                backend=self.name.value,
                detail="validated-input-archive-required",
            )
        if archive.manifest != spec.spec.input_manifest:
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.INPUT,
                backend=self.name.value,
                detail="input-archive-manifest-mismatch",
            )
        managed = self._volume(volume, RuntimePhase.INPUT)
        if volume.job_id != spec.spec.job_id:
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.INPUT,
                backend=self.name.value,
                detail="job-id-mismatch",
            )
        if managed.inputs_staged:
            raise self._invalid_state(RuntimePhase.INPUT, "inputs-already-staged")
        managed.inputs_staged = True
        managed.archive_sha256 = archive.archive_sha256

    async def create_container(
        self,
        spec: ValidatedSandboxSpec,
        volume: VolumeHandle,
    ) -> ContainerHandle:
        self._require_available(RuntimePhase.CREATE)
        if not isinstance(spec, ValidatedSandboxSpec):
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.CREATE,
                backend=self.name.value,
                detail="validated-spec-required",
            )
        managed_volume = self._volume(volume, RuntimePhase.CREATE)
        if not managed_volume.inputs_staged:
            raise self._invalid_state(RuntimePhase.CREATE, "inputs-not-staged")
        if volume.job_id != spec.spec.job_id:
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.CREATE,
                backend=self.name.value,
                detail="job-id-mismatch",
            )
        await self.inspect_image(spec.spec.image)
        if any(item.handle.job_id == spec.spec.job_id for item in self._containers.values()):
            raise RuntimeBackendError(
                ErrorCode.STALE_STATE,
                RuntimePhase.CREATE,
                retry=RetryDisposition.INFRASTRUCTURE,
                backend=self.name.value,
            )
        opaque_id = f"mock-container-{self._next_container:04d}"
        self._next_container += 1
        handle = ContainerHandle(self.name, opaque_id, spec.spec.job_id)
        self._containers[opaque_id] = _MockContainer(handle, volume, spec)
        return handle

    async def start(self, container: ContainerHandle) -> None:
        self._require_available(RuntimePhase.START)
        managed = self._container(container, RuntimePhase.START)
        if managed.state != "created":
            raise self._invalid_state(RuntimePhase.START, "container-not-created")
        managed.state = "running"

    async def wait(self, container: ContainerHandle) -> RunResult:
        self._require_available(RuntimePhase.WAIT)
        managed = self._container(container, RuntimePhase.WAIT)
        if managed.state != "running":
            raise self._invalid_state(RuntimePhase.WAIT, "container-not-running")
        result = self._planned_results.pop(
            container.job_id,
            RunResult(
                classification=TerminalClassification.SUCCEEDED,
                exit_code=0,
                duration_ms=1,
                output_limit_bytes=managed.validated_spec.spec.limits.output_bytes,
                observed_output_bytes=0,
                captured_output_bytes=0,
                output_truncated=False,
                stdout_sha256=EMPTY_SHA256,
                stderr_sha256=EMPTY_SHA256,
            ),
        )
        if result.output_limit_bytes != managed.validated_spec.spec.limits.output_bytes:
            raise RuntimeBackendError(
                ErrorCode.WAIT_FAILED,
                RuntimePhase.WAIT,
                backend=self.name.value,
                detail="output-limit-mismatch",
            )
        managed.result = result
        managed.state = "exited"
        return result

    async def kill(
        self,
        container: ContainerHandle,
        reason: TerminationReason,
    ) -> RunResult:
        self._require_available(RuntimePhase.KILL)
        managed = self._container(container, RuntimePhase.KILL)
        if not isinstance(reason, TerminationReason):
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.KILL,
                backend=self.name.value,
                detail="termination-reason-enum-required",
            )
        if managed.state != "running":
            raise self._invalid_state(RuntimePhase.KILL, "container-not-running")
        classifications = {
            TerminationReason.TIMEOUT: TerminalClassification.TIMED_OUT,
            TerminationReason.CANCELLATION: TerminalClassification.CANCELLED,
            TerminationReason.OUTPUT_LIMIT: TerminalClassification.OUTPUT_LIMIT_EXCEEDED,
            TerminationReason.SHUTDOWN: TerminalClassification.RUNTIME_ERROR,
        }
        classification = classifications[reason]
        output_limit = managed.validated_spec.spec.limits.output_bytes
        observed = output_limit + 1 if reason is TerminationReason.OUTPUT_LIMIT else 0
        captured = output_limit if reason is TerminationReason.OUTPUT_LIMIT else 0
        result = RunResult(
            classification=classification,
            exit_code=None,
            duration_ms=1,
            output_limit_bytes=output_limit,
            observed_output_bytes=observed,
            captured_output_bytes=captured,
            output_truncated=observed > captured,
            stdout_sha256=EMPTY_SHA256,
            stderr_sha256=EMPTY_SHA256,
        )
        managed.result = result
        managed.state = "exited"
        return result

    async def collect_artifacts(
        self,
        container: ContainerHandle,
    ) -> tuple[ArtifactRecord, ...]:
        self._require_available(RuntimePhase.ARTIFACT)
        managed = self._container(container, RuntimePhase.ARTIFACT)
        if managed.state != "exited" or managed.result is None:
            raise self._invalid_state(RuntimePhase.ARTIFACT, "container-not-terminal")
        artifacts = managed.result.artifacts
        expected = managed.validated_spec.spec.expected_outputs
        if tuple(item.name for item in artifacts) != expected:
            raise RuntimeBackendError(
                ErrorCode.ARTIFACT_REJECTED,
                RuntimePhase.ARTIFACT,
                backend=self.name.value,
                detail="output-manifest-mismatch",
            )
        limits = managed.validated_spec.spec.limits
        if len(artifacts) > limits.file_count or sum(item.bytes for item in artifacts) > limits.artifact_bytes:
            raise RuntimeBackendError(
                ErrorCode.ARTIFACT_REJECTED,
                RuntimePhase.ARTIFACT,
                backend=self.name.value,
                detail="artifact-limit-exceeded",
            )
        return artifacts

    async def remove_container(self, container: ContainerHandle) -> None:
        self._require_available(RuntimePhase.CLEANUP)
        managed = self._container(container, RuntimePhase.CLEANUP)
        if managed.state == "running":
            raise self._invalid_state(RuntimePhase.CLEANUP, "running-container")
        del self._containers[container.opaque_id]

    async def remove_volume(self, volume: VolumeHandle) -> None:
        self._require_available(RuntimePhase.CLEANUP)
        self._volume(volume, RuntimePhase.CLEANUP)
        if any(item.volume == volume for item in self._containers.values()):
            raise self._invalid_state(RuntimePhase.CLEANUP, "container-still-managed")
        del self._volumes[volume.opaque_id]

    async def list_managed(self, job_id: str | None = None) -> ManagedObjects:
        self._require_available(RuntimePhase.QUERY)
        if job_id is not None:
            _require_uuid(job_id, "query.job_id")
        volumes = tuple(
            item.handle
            for item in self._volumes.values()
            if job_id is None or item.handle.job_id == job_id
        )
        containers = tuple(
            item.handle
            for item in self._containers.values()
            if job_id is None or item.handle.job_id == job_id
        )
        return ManagedObjects(volumes=volumes, containers=containers)
