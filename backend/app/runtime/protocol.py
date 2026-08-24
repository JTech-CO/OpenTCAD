"""RuntimeBackend protocol consumed by the future sandbox broker only."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import (
    ArtifactRecord,
    ContainerHandle,
    ImageIdentity,
    ManagedObjects,
    RunResult,
    RuntimeKind,
    RuntimeProbe,
    TerminationReason,
    ValidatedInputArchive,
    ValidatedSandboxSpec,
    VolumeHandle,
)


@runtime_checkable
class RuntimeBackend(Protocol):
    """Typed OCI lifecycle operations with no raw command or host-path surface."""

    @property
    def name(self) -> RuntimeKind: ...

    async def probe(self) -> RuntimeProbe: ...

    async def inspect_image(self, image: ImageIdentity) -> ImageIdentity: ...

    async def ensure_image(self, image: ImageIdentity) -> ImageIdentity: ...

    async def create_volume(self, job_id: str) -> VolumeHandle: ...

    async def stage_inputs(
        self,
        volume: VolumeHandle,
        spec: ValidatedSandboxSpec,
        archive: ValidatedInputArchive,
    ) -> None: ...

    async def create_container(
        self,
        spec: ValidatedSandboxSpec,
        volume: VolumeHandle,
    ) -> ContainerHandle: ...

    async def start(self, container: ContainerHandle) -> None: ...

    async def wait(self, container: ContainerHandle) -> RunResult: ...

    async def kill(
        self,
        container: ContainerHandle,
        reason: TerminationReason,
    ) -> RunResult: ...

    async def collect_artifacts(
        self,
        container: ContainerHandle,
    ) -> tuple[ArtifactRecord, ...]: ...

    async def remove_container(self, container: ContainerHandle) -> None: ...

    async def remove_volume(self, volume: VolumeHandle) -> None: ...

    async def list_managed(self, job_id: str | None = None) -> ManagedObjects: ...
