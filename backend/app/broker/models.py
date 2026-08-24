"""Typed broker requests and redacted state-machine outcomes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from backend.app.runtime.errors import (
    ErrorCode,
    RetryDisposition,
    RuntimeBackendError,
    RuntimePhase,
)
from backend.app.runtime.models import ArtifactRecord, RunResult, SandboxSpec, TerminalClassification


def _invalid(detail: str) -> None:
    raise RuntimeBackendError(
        ErrorCode.INVALID_SPEC,
        RuntimePhase.VALIDATE,
        detail=detail,
    )


class BrokerState(StrEnum):
    VALIDATING = "validating"
    PREPARING = "preparing"
    RUNNING = "running"
    COLLECTING = "collecting"
    CLEANING = "cleaning"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BrokerRequest:
    spec: SandboxSpec
    input_archive: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.spec, SandboxSpec):
            _invalid("broker_request.spec:sandbox-spec-required")
        if not isinstance(self.input_archive, bytes) or not self.input_archive:
            _invalid("broker_request.input_archive:non-empty-bytes-required")


@dataclass(frozen=True, slots=True)
class BrokerError:
    code: ErrorCode
    phase: RuntimePhase
    retry: RetryDisposition
    backend: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.code, ErrorCode):
            _invalid("broker_error.code:enum-required")
        if not isinstance(self.phase, RuntimePhase):
            _invalid("broker_error.phase:enum-required")
        if not isinstance(self.retry, RetryDisposition):
            _invalid("broker_error.retry:enum-required")
        if self.backend is not None and not isinstance(self.backend, str):
            _invalid("broker_error.backend:string-or-null-required")

    @classmethod
    def from_exception(cls, error: RuntimeBackendError) -> BrokerError:
        record = error.record
        return cls(record.code, record.phase, record.retry, record.backend)


@dataclass(frozen=True, slots=True)
class BrokerEvent:
    sequence: int
    state: BrokerState
    phase: RuntimePhase
    code: ErrorCode | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence < 1:
            _invalid("broker_event.sequence:positive-integer-required")
        if not isinstance(self.state, BrokerState):
            _invalid("broker_event.state:enum-required")
        if not isinstance(self.phase, RuntimePhase):
            _invalid("broker_event.phase:enum-required")
        if self.code is not None and not isinstance(self.code, ErrorCode):
            _invalid("broker_event.code:enum-or-null-required")


@dataclass(frozen=True, slots=True)
class BrokerOutcome:
    job_id: str
    state: BrokerState
    result: RunResult | None
    artifacts: tuple[ArtifactRecord, ...]
    error: BrokerError | None
    cleanup_error: BrokerError | None
    cleanup_complete: bool
    events: tuple[BrokerEvent, ...]

    def __post_init__(self) -> None:
        artifacts = tuple(self.artifacts)
        events = tuple(self.events)
        object.__setattr__(self, "artifacts", artifacts)
        object.__setattr__(self, "events", events)
        if self.state not in {BrokerState.SUCCEEDED, BrokerState.FAILED}:
            _invalid("broker_outcome.state:terminal-required")
        if any(not isinstance(item, ArtifactRecord) for item in artifacts):
            _invalid("broker_outcome.artifacts:records-required")
        if not events or any(not isinstance(item, BrokerEvent) for item in events):
            _invalid("broker_outcome.events:records-required")
        if self.result is not None and not isinstance(self.result, RunResult):
            _invalid("broker_outcome.result:run-result-or-null-required")
        if self.error is not None and not isinstance(self.error, BrokerError):
            _invalid("broker_outcome.error:broker-error-or-null-required")
        if self.cleanup_error is not None and not isinstance(self.cleanup_error, BrokerError):
            _invalid("broker_outcome.cleanup_error:broker-error-or-null-required")
        if not isinstance(self.cleanup_complete, bool):
            _invalid("broker_outcome.cleanup_complete:boolean-required")
        if self.state is BrokerState.SUCCEEDED and (
            self.result is None
            or self.result.classification is not TerminalClassification.SUCCEEDED
            or self.error is not None
            or self.cleanup_error is not None
            or not self.cleanup_complete
        ):
            _invalid("broker_outcome:success-invariant")


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    containers_found: int
    containers_removed: int
    volumes_found: int
    volumes_removed: int
    remaining_containers: int
    remaining_volumes: int
    errors: tuple[BrokerError, ...]

    def __post_init__(self) -> None:
        errors = tuple(self.errors)
        counts = (
            self.containers_found,
            self.containers_removed,
            self.volumes_found,
            self.volumes_removed,
            self.remaining_containers,
            self.remaining_volumes,
        )
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counts):
            _invalid("reconciliation.counts:non-negative-integers-required")
        if any(not isinstance(error, BrokerError) for error in errors):
            _invalid("reconciliation.errors:broker-errors-required")
        object.__setattr__(self, "errors", errors)

    @property
    def complete(self) -> bool:
        return (
            not self.errors
            and self.containers_found == self.containers_removed
            and self.volumes_found == self.volumes_removed
            and self.remaining_containers == 0
            and self.remaining_volumes == 0
        )
