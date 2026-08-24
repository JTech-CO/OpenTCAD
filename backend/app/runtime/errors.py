"""Stable, locale-independent runtime error records."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """Codes shared by workers, brokers, and every runtime backend."""

    RUNTIME_UNAVAILABLE = "runtime-unavailable"
    CAPABILITY_MISSING = "capability-missing"
    IMAGE_NOT_APPROVED = "image-not-approved"
    IMAGE_IDENTITY_MISMATCH = "image-identity-mismatch"
    INVALID_SPEC = "invalid-spec"
    VOLUME_NOT_FOUND = "volume-not-found"
    CONTAINER_NOT_FOUND = "container-not-found"
    INVALID_STATE = "invalid-state"
    STALE_STATE = "stale-state"
    START_FAILED = "start-failed"
    WAIT_FAILED = "wait-failed"
    KILL_FAILED = "kill-failed"
    CLEANUP_FAILED = "cleanup-failed"
    INPUT_ARCHIVE_REJECTED = "input-archive-rejected"
    ARTIFACT_REJECTED = "artifact-rejected"


class RuntimePhase(StrEnum):
    VALIDATE = "validate"
    PROBE = "probe"
    IMAGE = "image"
    VOLUME = "volume"
    INPUT = "input"
    CREATE = "create"
    START = "start"
    WAIT = "wait"
    KILL = "kill"
    ARTIFACT = "artifact"
    CLEANUP = "cleanup"
    QUERY = "query"


class RetryDisposition(StrEnum):
    NEVER = "never"
    INFRASTRUCTURE = "infrastructure"
    SOLVER = "solver"


@dataclass(frozen=True, slots=True)
class ErrorRecord:
    code: ErrorCode
    phase: RuntimePhase
    retry: RetryDisposition
    backend: str | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "phase": self.phase.value,
            "retry": self.retry.value,
            "backend": self.backend,
            "detail": self.detail,
        }


class RuntimeBackendError(Exception):
    """An adapter-independent failure safe to persist as structured job state."""

    def __init__(
        self,
        code: ErrorCode,
        phase: RuntimePhase,
        *,
        retry: RetryDisposition = RetryDisposition.NEVER,
        backend: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.record = ErrorRecord(
            code=code,
            phase=phase,
            retry=retry,
            backend=backend,
            detail=detail,
        )
        super().__init__(f"{code.value}:{phase.value}")

    @property
    def code(self) -> ErrorCode:
        return self.record.code

    @property
    def phase(self) -> RuntimePhase:
        return self.record.phase

    def as_dict(self) -> dict[str, Any]:
        return self.record.as_dict()
