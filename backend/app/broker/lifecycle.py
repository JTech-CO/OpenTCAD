"""Deterministic, engine-independent execution cancellation checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from backend.app.runtime.errors import RuntimePhase
from backend.app.runtime.models import JobIdentity


class LifecycleCheckpoint(StrEnum):
    """Broker-owned points at which an execution cancellation may be observed."""

    PROBE = "probe"
    POLICY = "policy"
    INPUT_ARCHIVE = "input-archive"
    IMAGE = "image"
    VOLUME = "volume"
    INPUT_STAGE = "input-stage"
    CONTAINER_CREATE = "container-create"
    START = "start"
    WAIT = "wait"
    ARTIFACT_COLLECTION = "artifact-collection"
    CLEANUP = "cleanup"

    @property
    def phase(self) -> RuntimePhase:
        return {
            LifecycleCheckpoint.PROBE: RuntimePhase.PROBE,
            LifecycleCheckpoint.POLICY: RuntimePhase.VALIDATE,
            LifecycleCheckpoint.INPUT_ARCHIVE: RuntimePhase.INPUT,
            LifecycleCheckpoint.IMAGE: RuntimePhase.IMAGE,
            LifecycleCheckpoint.VOLUME: RuntimePhase.VOLUME,
            LifecycleCheckpoint.INPUT_STAGE: RuntimePhase.INPUT,
            LifecycleCheckpoint.CONTAINER_CREATE: RuntimePhase.CREATE,
            LifecycleCheckpoint.START: RuntimePhase.START,
            LifecycleCheckpoint.WAIT: RuntimePhase.WAIT,
            LifecycleCheckpoint.ARTIFACT_COLLECTION: RuntimePhase.ARTIFACT,
            LifecycleCheckpoint.CLEANUP: RuntimePhase.CLEANUP,
        }[self]


@runtime_checkable
class CancellationSignal(Protocol):
    """In-process signal polled by the broker at fixed lifecycle checkpoints."""

    @property
    def identity(self) -> JobIdentity: ...

    def requested(self, checkpoint: LifecycleCheckpoint) -> bool: ...


@dataclass(frozen=True, slots=True)
class PhaseCancellation:
    """Deterministic one-checkpoint cancellation used by contract tests."""

    identity: JobIdentity
    checkpoint: LifecycleCheckpoint

    def __post_init__(self) -> None:
        if not isinstance(self.identity, JobIdentity):
            raise TypeError("PhaseCancellation requires JobIdentity.")
        if not isinstance(self.checkpoint, LifecycleCheckpoint):
            raise TypeError("PhaseCancellation requires LifecycleCheckpoint.")

    def requested(self, checkpoint: LifecycleCheckpoint) -> bool:
        if not isinstance(checkpoint, LifecycleCheckpoint):
            raise TypeError("Cancellation checkpoint must be LifecycleCheckpoint.")
        return checkpoint is self.checkpoint
