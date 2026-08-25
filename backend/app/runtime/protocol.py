"""RuntimeBackend protocol consumed by the future sandbox broker only."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .fencing import RuntimeFencingContext
from .models import (
    ContainerHandle,
    ImageIdentity,
    JobIdentity,
    ManagedObjects,
    RawArtifactArchive,
    RunResult,
    RuntimeKind,
    RuntimeProbe,
    TerminationReason,
    ValidatedInputArchive,
    ValidatedSandboxSpec,
    VolumeHandle,
)


@runtime_checkable
class RuntimeJobBackend(Protocol):
    """Job-bound lifecycle surface that enforces one fencing generation."""

    @property
    def fence(self) -> RuntimeFencingContext: ...

    async def create_volume(self) -> VolumeHandle: ...

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
    ) -> RawArtifactArchive: ...

    async def remove_container(self, container: ContainerHandle) -> None: ...

    async def remove_volume(self, volume: VolumeHandle) -> None: ...

    async def list_managed(self) -> ManagedObjects: ...


@runtime_checkable
class RuntimeBackend(Protocol):
    """Global runtime surface; job lifecycle is available only through bind_job."""

    @property
    def name(self) -> RuntimeKind: ...

    async def probe(self) -> RuntimeProbe: ...

    async def inspect_image(self, image: ImageIdentity) -> ImageIdentity: ...

    async def ensure_image(self, image: ImageIdentity) -> ImageIdentity: ...

    def bind_job(self, fence: RuntimeFencingContext) -> RuntimeJobBackend: ...

    async def list_managed(self) -> ManagedObjects: ...
