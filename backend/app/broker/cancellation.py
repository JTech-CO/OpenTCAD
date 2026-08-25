"""Typed cancellation identity and redacted cancellation outcome."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.runtime.errors import RuntimePhase
from backend.app.runtime.models import JobIdentity, RunResult, TerminalClassification

from .models import BrokerError, BrokerEvent, BrokerState


@dataclass(frozen=True, slots=True)
class CancellationRequest:
    identity: JobIdentity

    def __post_init__(self) -> None:
        if not isinstance(self.identity, JobIdentity):
            raise TypeError("CancellationRequest requires JobIdentity.")


@dataclass(frozen=True, slots=True)
class CancellationOutcome:
    identity: JobIdentity
    state: BrokerState
    result: RunResult | None
    error: BrokerError | None
    cleanup_error: BrokerError | None
    cleanup_complete: bool
    events: tuple[BrokerEvent, ...]
    intent_persisted: bool = False

    def __post_init__(self) -> None:
        events = tuple(self.events)
        object.__setattr__(self, "events", events)
        if not isinstance(self.identity, JobIdentity):
            raise TypeError("CancellationOutcome requires JobIdentity.")
        if self.state not in {BrokerState.CANCELLED, BrokerState.FAILED}:
            raise TypeError("CancellationOutcome requires a terminal cancellation state.")
        if self.result is not None and not isinstance(self.result, RunResult):
            raise TypeError("CancellationOutcome result must be RunResult or None.")
        if self.error is not None and not isinstance(self.error, BrokerError):
            raise TypeError("CancellationOutcome error must be BrokerError or None.")
        if self.cleanup_error is not None and not isinstance(self.cleanup_error, BrokerError):
            raise TypeError("CancellationOutcome cleanup_error must be BrokerError or None.")
        if not isinstance(self.cleanup_complete, bool):
            raise TypeError("CancellationOutcome cleanup_complete must be bool.")
        if not isinstance(self.intent_persisted, bool):
            raise TypeError("CancellationOutcome intent_persisted must be bool.")
        if not events or any(not isinstance(event, BrokerEvent) for event in events):
            raise TypeError("CancellationOutcome requires BrokerEvent records.")
        if self.intent_persisted and (
            events[0].state is not BrokerState.CANCELLING
            or events[0].phase is not RuntimePhase.QUERY
        ):
            raise TypeError("CancellationOutcome durable intent invariant failed.")
        if self.state is BrokerState.CANCELLED and (
            (self.result is None and not self.intent_persisted)
            or (
                self.result is not None
                and self.result.classification
                is not TerminalClassification.CANCELLED
            )
            or self.error is not None
            or self.cleanup_error is not None
            or not self.cleanup_complete
        ):
            raise TypeError("CancellationOutcome cancelled invariant failed.")

    def as_dict(self) -> dict[str, Any]:
        result = self.result
        classification = (
            result.classification
            if result is not None
            else TerminalClassification.CANCELLED
            if self.state is BrokerState.CANCELLED and self.intent_persisted
            else None
        )
        return {
            "identity": {
                "job_id": self.identity.job_id,
                "label": list(self.identity.label),
                "object_name": self.identity.object_name,
                "volume_name": self.identity.volume_name,
            },
            "state": self.state.value,
            "classification": classification.value if classification is not None else None,
            "error": self.error.as_dict() if self.error is not None else None,
            "cleanup_error": (
                self.cleanup_error.as_dict() if self.cleanup_error is not None else None
            ),
            "cleanup_complete": self.cleanup_complete,
            "intent_persisted": self.intent_persisted,
            "events": [event.as_dict() for event in self.events],
        }
