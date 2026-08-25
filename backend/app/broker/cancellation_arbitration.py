"""Deterministic crash seams for durable external cancellation arbitration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from backend.app.runtime.models import JobIdentity


class DurableCancellationCheckpoint(StrEnum):
    BEFORE_INTENT = "before-intent"
    AFTER_INTENT = "after-intent"
    AFTER_CLEANING_STATE = "after-cleaning-state"
    AFTER_CLEANUP = "after-cleanup"
    AFTER_FINAL_STATE = "after-final-state"


class DurableCancellationInterrupted(Exception):
    """Deterministic process-crash surrogate used only by contract tests."""

    def __init__(self, checkpoint: DurableCancellationCheckpoint) -> None:
        if not isinstance(checkpoint, DurableCancellationCheckpoint):
            raise TypeError(
                "DurableCancellationInterrupted requires a cancellation checkpoint.",
            )
        self.checkpoint = checkpoint
        super().__init__(checkpoint.value)


@runtime_checkable
class DurableCancellationCrashSignal(Protocol):
    def requested(
        self,
        checkpoint: DurableCancellationCheckpoint,
        identity: JobIdentity,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class DurableCancellationCrashInjection:
    checkpoint: DurableCancellationCheckpoint
    job_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.checkpoint, DurableCancellationCheckpoint):
            raise TypeError(
                "DurableCancellationCrashInjection requires a cancellation checkpoint.",
            )
        if self.job_id is not None:
            JobIdentity(self.job_id)

    def requested(
        self,
        checkpoint: DurableCancellationCheckpoint,
        identity: JobIdentity,
    ) -> bool:
        return checkpoint is self.checkpoint and (
            self.job_id is None or identity.job_id == self.job_id
        )


def cancellation_checkpoint(
    signal: DurableCancellationCrashSignal | None,
    checkpoint: DurableCancellationCheckpoint,
    identity: JobIdentity,
) -> None:
    if signal is None:
        return
    if not isinstance(signal, DurableCancellationCrashSignal):
        raise TypeError("Durable cancellation crash signal has the wrong type.")
    requested = signal.requested(checkpoint, identity)
    if not isinstance(requested, bool):
        raise TypeError("Durable cancellation crash signal must return bool.")
    if requested:
        raise DurableCancellationInterrupted(checkpoint)
