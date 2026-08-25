"""In-memory RuntimeBackend used only for contract and broker tests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from .fence_authority import (
    InMemoryRuntimeFenceAuthority,
    RuntimeFenceAuthority,
)
from .fencing import RuntimeFencingContext, enforce_runtime_object_fence
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
    JobIdentity,
    ManagedObjects,
    RawArtifactArchive,
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
        "runtime_fencing": True,
    }
    values.update(overrides)
    return RuntimeCapabilities(**values)  # type: ignore[arg-type]


@dataclass(slots=True)
class _MockVolume:
    handle: VolumeHandle
    fence_labels: dict[str, str]
    inputs_staged: bool = False
    archive_sha256: str | None = None


@dataclass(slots=True)
class _MockContainer:
    handle: ContainerHandle
    volume: VolumeHandle
    validated_spec: ValidatedSandboxSpec
    fence_labels: dict[str, str]
    state: str = "created"
    result: RunResult | None = None



_ACTIVE_RUNTIME_FENCE: ContextVar[RuntimeFencingContext | None] = ContextVar(
    "opentcad_mock_runtime_fence",
    default=None,
)


class _MockRuntimeJobBackend:
    """Bound mock adapter view that rechecks its token around every call."""

    def __init__(
        self,
        backend: MockRuntimeBackend,
        fence: RuntimeFencingContext,
    ) -> None:
        self._backend = backend
        self._fence = fence

    @property
    def fence(self) -> RuntimeFencingContext:
        return self._fence

    async def _invoke(
        self,
        phase: RuntimePhase,
        operation: Callable[[], Awaitable[Any]],
    ) -> Any:
        await self._backend._activate_fence(self._fence, phase)
        token = _ACTIVE_RUNTIME_FENCE.set(self._fence)
        try:
            result = await operation()
            await self._backend._verify_fence(self._fence, phase)
            return result
        finally:
            _ACTIVE_RUNTIME_FENCE.reset(token)

    async def create_volume(self) -> VolumeHandle:
        return await self._invoke(
            RuntimePhase.VOLUME,
            lambda: self._backend.create_volume(self._fence.identity),
        )

    async def stage_inputs(
        self,
        volume: VolumeHandle,
        spec: ValidatedSandboxSpec,
        archive: ValidatedInputArchive,
    ) -> None:
        await self._invoke(
            RuntimePhase.INPUT,
            lambda: self._backend.stage_inputs(volume, spec, archive),
        )

    async def create_container(
        self,
        spec: ValidatedSandboxSpec,
        volume: VolumeHandle,
    ) -> ContainerHandle:
        return await self._invoke(
            RuntimePhase.CREATE,
            lambda: self._backend.create_container(spec, volume),
        )

    async def start(self, container: ContainerHandle) -> None:
        await self._invoke(RuntimePhase.START, lambda: self._backend.start(container))

    async def wait(self, container: ContainerHandle) -> RunResult:
        return await self._invoke(RuntimePhase.WAIT, lambda: self._backend.wait(container))

    async def kill(
        self,
        container: ContainerHandle,
        reason: TerminationReason,
    ) -> RunResult:
        return await self._invoke(
            RuntimePhase.KILL,
            lambda: self._backend.kill(container, reason),
        )

    async def collect_artifacts(
        self,
        container: ContainerHandle,
    ) -> RawArtifactArchive:
        return await self._invoke(
            RuntimePhase.ARTIFACT,
            lambda: self._backend.collect_artifacts(container),
        )

    async def inspect_fence(
        self,
        handle: ContainerHandle | VolumeHandle,
    ) -> RuntimeFencingContext:
        return await self._invoke(
            RuntimePhase.QUERY,
            lambda: self._backend.inspect_fence(handle),
        )

    async def remove_container(self, container: ContainerHandle) -> None:
        await self._invoke(
            RuntimePhase.CLEANUP,
            lambda: self._backend.remove_container(container),
        )

    async def remove_volume(self, volume: VolumeHandle) -> None:
        await self._invoke(
            RuntimePhase.CLEANUP,
            lambda: self._backend.remove_volume(volume),
        )

    async def list_managed(self) -> ManagedObjects:
        return await self._invoke(
            RuntimePhase.QUERY,
            lambda: self._backend.list_managed(self._fence.identity.job_id),
        )


class MockRuntimeBackend:
    """Strict lifecycle model. It never invokes a process or opens a runtime socket."""

    def __init__(
        self,
        *,
        images: tuple[ImageIdentity, ...],
        capabilities: RuntimeCapabilities | None = None,
        available: bool = True,
        fence_authority: RuntimeFenceAuthority | None = None,
    ) -> None:
        self._capabilities = capabilities or full_mock_capabilities()
        if self._capabilities.backend is not RuntimeKind.MOCK:
            raise ValueError("Mock backend requires mock capabilities.")
        self._available = available
        authority = fence_authority or InMemoryRuntimeFenceAuthority()
        if not isinstance(authority, RuntimeFenceAuthority):
            raise TypeError("Mock backend requires RuntimeFenceAuthority.")
        self._fence_authority = authority
        self._images = {image.reference: image for image in images}
        self._volumes: dict[str, _MockVolume] = {}
        self._containers: dict[str, _MockContainer] = {}
        self._planned_results: dict[str, RunResult] = {}
        self._planned_artifact_archives: dict[str, RawArtifactArchive] = {}

    @property
    def name(self) -> RuntimeKind:
        return RuntimeKind.MOCK

    def bind_job(self, fence: RuntimeFencingContext) -> _MockRuntimeJobBackend:
        if not isinstance(fence, RuntimeFencingContext):
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.VALIDATE,
                backend=self.name.value,
                detail="runtime-fencing-context-required",
            )
        return _MockRuntimeJobBackend(self, fence)

    async def _activate_fence(
        self,
        fence: RuntimeFencingContext,
        phase: RuntimePhase,
    ) -> None:
        await self._fence_authority.activate(
            fence,
            phase=phase,
            backend=self.name,
        )

    async def _verify_fence(
        self,
        fence: RuntimeFencingContext,
        phase: RuntimePhase,
    ) -> None:
        await self._fence_authority.verify(
            fence,
            phase=phase,
            backend=self.name,
        )

    async def _enforce_active_fence(
        self,
        job_id: str,
        phase: RuntimePhase,
    ) -> None:
        fence = _ACTIVE_RUNTIME_FENCE.get()
        if fence is None:
            return
        if fence.identity.job_id != job_id:
            raise RuntimeBackendError(
                ErrorCode.IDENTITY_MISMATCH,
                phase,
                backend=self.name.value,
                detail="runtime-fence-job-identity-mismatch",
            )
        await self._verify_fence(fence, phase)

    @staticmethod
    def _fence_labels(identity: JobIdentity) -> dict[str, str]:
        fence = _ACTIVE_RUNTIME_FENCE.get()
        if fence is None:
            fence = RuntimeFencingContext(identity, identity.job_id, 1)
        return dict(fence.labels)

    async def _enforce_object_fence(
        self,
        job_id: str,
        labels: dict[str, str],
        phase: RuntimePhase,
    ) -> RuntimeFencingContext:
        await self._enforce_active_fence(job_id, phase)
        observed = RuntimeFencingContext.from_labels(labels)
        requested = _ACTIVE_RUNTIME_FENCE.get()
        if requested is not None:
            enforce_runtime_object_fence(requested, observed, phase, self.name)
        return observed

    def plan_result(
        self,
        job_id: str,
        result: RunResult,
        artifact_archive: RawArtifactArchive | None = None,
    ) -> None:
        _require_uuid(job_id, "mock.plan_result.job_id")
        if not isinstance(result, RunResult):
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.VALIDATE,
                backend=self.name.value,
                detail="mock.plan_result:run-result-required",
            )
        if artifact_archive is not None and not isinstance(artifact_archive, RawArtifactArchive):
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.VALIDATE,
                backend=self.name.value,
                detail="mock.plan_result:raw-artifact-archive-required",
            )
        self._planned_results[job_id] = result
        if artifact_archive is None:
            self._planned_artifact_archives.pop(job_id, None)
        else:
            self._planned_artifact_archives[job_id] = artifact_archive

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

    async def create_volume(self, identity: JobIdentity) -> VolumeHandle:
        self._require_available(RuntimePhase.VOLUME)
        if isinstance(identity, JobIdentity):
            await self._enforce_active_fence(identity.job_id, RuntimePhase.VOLUME)
        if not isinstance(identity, JobIdentity):
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.VOLUME,
                backend=self.name.value,
                detail="job-identity-required",
            )
        opaque_id = identity.volume_name
        if opaque_id in self._volumes:
            raise RuntimeBackendError(
                ErrorCode.STALE_STATE,
                RuntimePhase.VOLUME,
                retry=RetryDisposition.INFRASTRUCTURE,
                backend=self.name.value,
            )
        handle = VolumeHandle(self.name, opaque_id, identity.job_id)
        self._volumes[opaque_id] = _MockVolume(handle, self._fence_labels(identity))
        return handle

    async def stage_inputs(
        self,
        volume: VolumeHandle,
        spec: ValidatedSandboxSpec,
        archive: ValidatedInputArchive,
    ) -> None:
        self._require_available(RuntimePhase.INPUT)
        if isinstance(volume, VolumeHandle):
            await self._enforce_active_fence(volume.job_id, RuntimePhase.INPUT)
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
        await self._enforce_object_fence(
            volume.job_id,
            managed.fence_labels,
            RuntimePhase.INPUT,
        )
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
        if isinstance(volume, VolumeHandle):
            await self._enforce_active_fence(volume.job_id, RuntimePhase.CREATE)
        if not isinstance(spec, ValidatedSandboxSpec):
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.CREATE,
                backend=self.name.value,
                detail="validated-spec-required",
            )
        managed_volume = self._volume(volume, RuntimePhase.CREATE)
        await self._enforce_object_fence(
            volume.job_id,
            managed_volume.fence_labels,
            RuntimePhase.CREATE,
        )
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
        opaque_id = spec.identity.object_name
        if opaque_id in self._containers:
            raise RuntimeBackendError(
                ErrorCode.STALE_STATE,
                RuntimePhase.CREATE,
                retry=RetryDisposition.INFRASTRUCTURE,
                backend=self.name.value,
            )
        handle = ContainerHandle(self.name, opaque_id, spec.spec.job_id)
        self._containers[opaque_id] = _MockContainer(
            handle,
            volume,
            spec,
            self._fence_labels(spec.identity),
        )
        return handle

    async def start(self, container: ContainerHandle) -> None:
        self._require_available(RuntimePhase.START)
        if isinstance(container, ContainerHandle):
            await self._enforce_active_fence(container.job_id, RuntimePhase.START)
        managed = self._container(container, RuntimePhase.START)
        await self._enforce_object_fence(
            container.job_id,
            managed.fence_labels,
            RuntimePhase.START,
        )
        if managed.state != "created":
            raise self._invalid_state(RuntimePhase.START, "container-not-created")
        managed.state = "running"

    async def wait(self, container: ContainerHandle) -> RunResult:
        self._require_available(RuntimePhase.WAIT)
        if isinstance(container, ContainerHandle):
            await self._enforce_active_fence(container.job_id, RuntimePhase.WAIT)
        managed = self._container(container, RuntimePhase.WAIT)
        await self._enforce_object_fence(
            container.job_id,
            managed.fence_labels,
            RuntimePhase.WAIT,
        )
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
        if isinstance(container, ContainerHandle):
            await self._enforce_active_fence(container.job_id, RuntimePhase.KILL)
        managed = self._container(container, RuntimePhase.KILL)
        await self._enforce_object_fence(
            container.job_id,
            managed.fence_labels,
            RuntimePhase.KILL,
        )
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
    ) -> RawArtifactArchive:
        self._require_available(RuntimePhase.ARTIFACT)
        if isinstance(container, ContainerHandle):
            await self._enforce_active_fence(container.job_id, RuntimePhase.ARTIFACT)
        managed = self._container(container, RuntimePhase.ARTIFACT)
        await self._enforce_object_fence(
            container.job_id,
            managed.fence_labels,
            RuntimePhase.ARTIFACT,
        )
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
        archive = self._planned_artifact_archives.pop(container.job_id, None)
        if archive is None:
            raise RuntimeBackendError(
                ErrorCode.ARTIFACT_REJECTED,
                RuntimePhase.ARTIFACT,
                backend=self.name.value,
                detail="artifact-archive-missing",
            )
        return archive

    async def remove_container(self, container: ContainerHandle) -> None:
        self._require_available(RuntimePhase.CLEANUP)
        if isinstance(container, ContainerHandle):
            await self._enforce_active_fence(container.job_id, RuntimePhase.CLEANUP)
        managed = self._container(container, RuntimePhase.CLEANUP)
        await self._enforce_object_fence(
            container.job_id,
            managed.fence_labels,
            RuntimePhase.CLEANUP,
        )
        if managed.state == "running":
            raise self._invalid_state(RuntimePhase.CLEANUP, "running-container")
        del self._containers[container.opaque_id]
        self._planned_results.pop(container.job_id, None)
        self._planned_artifact_archives.pop(container.job_id, None)

    async def remove_volume(self, volume: VolumeHandle) -> None:
        self._require_available(RuntimePhase.CLEANUP)
        if isinstance(volume, VolumeHandle):
            await self._enforce_active_fence(volume.job_id, RuntimePhase.CLEANUP)
        managed = self._volume(volume, RuntimePhase.CLEANUP)
        await self._enforce_object_fence(
            volume.job_id,
            managed.fence_labels,
            RuntimePhase.CLEANUP,
        )
        if any(item.volume == volume for item in self._containers.values()):
            raise self._invalid_state(RuntimePhase.CLEANUP, "container-still-managed")
        del self._volumes[volume.opaque_id]

    async def inspect_fence(
        self,
        handle: ContainerHandle | VolumeHandle,
    ) -> RuntimeFencingContext:
        self._require_available(RuntimePhase.QUERY)
        if isinstance(handle, ContainerHandle):
            managed = self._container(handle, RuntimePhase.QUERY)
        elif isinstance(handle, VolumeHandle):
            managed = self._volume(handle, RuntimePhase.QUERY)
        else:
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.QUERY,
                backend=self.name.value,
                detail="managed-handle-required",
            )
        return await self._enforce_object_fence(
            handle.job_id,
            managed.fence_labels,
            RuntimePhase.QUERY,
        )

    async def list_managed(self, job_id: str | None = None) -> ManagedObjects:
        self._require_available(RuntimePhase.QUERY)
        if job_id is not None:
            _require_uuid(job_id, "query.job_id")
            await self._enforce_active_fence(job_id, RuntimePhase.QUERY)
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
        if _ACTIVE_RUNTIME_FENCE.get() is not None:
            for item in self._volumes.values():
                if job_id is None or item.handle.job_id == job_id:
                    await self._enforce_object_fence(
                        item.handle.job_id,
                        item.fence_labels,
                        RuntimePhase.QUERY,
                    )
            for item in self._containers.values():
                if job_id is None or item.handle.job_id == job_id:
                    await self._enforce_object_fence(
                        item.handle.job_id,
                        item.fence_labels,
                        RuntimePhase.QUERY,
                    )
        return ManagedObjects(volumes=volumes, containers=containers)
