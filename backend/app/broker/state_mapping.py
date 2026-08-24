"""Deterministic mapping from redacted broker outcomes to durable state events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid5

from backend.app.runtime.errors import RuntimeBackendError, RuntimePhase
from backend.app.runtime.models import JobIdentity, RuntimeKind, TerminalClassification

from .cancellation import CancellationOutcome
from .models import BrokerError, BrokerEvent, BrokerOutcome, BrokerState
from .state import DurableJobEvent, DurableJobStateStore, JobStateSnapshot


class StateMappingErrorCode(StrEnum):
    INVALID_CONTEXT = "invalid-context"
    INVALID_SEQUENCE = "invalid-sequence"
    IDENTITY_MISMATCH = "identity-mismatch"
    OUTCOME_MISMATCH = "outcome-mismatch"
    ERROR_MAPPING_MISSING = "error-mapping-missing"
    BACKEND_MISMATCH = "backend-mismatch"
    CLEANUP_INCOMPLETE = "cleanup-incomplete"


class StateMappingError(Exception):
    """Stable mapping failure that never includes runtime or database detail."""

    def __init__(self, code: StateMappingErrorCode) -> None:
        if not isinstance(code, StateMappingErrorCode):
            raise TypeError("StateMappingError requires StateMappingErrorCode.")
        self.code = code
        super().__init__(code.value)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code.value}


def _canonical_uuid(value: str, code: StateMappingErrorCode) -> UUID:
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise StateMappingError(code) from error
    if str(parsed) != value:
        raise StateMappingError(code)
    return parsed


@dataclass(frozen=True, slots=True)
class StateMappingContext:
    operation_id: str
    backend: RuntimeKind

    def __post_init__(self) -> None:
        _canonical_uuid(self.operation_id, StateMappingErrorCode.INVALID_CONTEXT)
        if not isinstance(self.backend, RuntimeKind):
            raise StateMappingError(StateMappingErrorCode.INVALID_CONTEXT)


@dataclass(frozen=True, slots=True)
class MappedStateBatch:
    identity: JobIdentity
    operation_id: str
    events: tuple[DurableJobEvent, ...]

    def __post_init__(self) -> None:
        events = tuple(self.events)
        object.__setattr__(self, "events", events)
        if not isinstance(self.identity, JobIdentity) or not events:
            raise StateMappingError(StateMappingErrorCode.OUTCOME_MISMATCH)
        _canonical_uuid(self.operation_id, StateMappingErrorCode.INVALID_CONTEXT)
        if any(
            not isinstance(event, DurableJobEvent)
            or event.identity != self.identity
            or event.operation_id != self.operation_id
            for event in events
        ):
            raise StateMappingError(StateMappingErrorCode.OUTCOME_MISMATCH)
        if tuple(event.operation_sequence for event in events) != tuple(
            range(1, len(events) + 1),
        ):
            raise StateMappingError(StateMappingErrorCode.INVALID_SEQUENCE)
        if len({event.event_id for event in events}) != len(events):
            raise StateMappingError(StateMappingErrorCode.INVALID_SEQUENCE)

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.identity.job_id,
            "operation_id": self.operation_id,
            "events": [event.as_dict() for event in self.events],
        }


class BrokerStateMapper:
    """Maps one complete broker operation without wiring the broker to storage."""

    @staticmethod
    def _identity(outcome: BrokerOutcome | CancellationOutcome) -> JobIdentity:
        if isinstance(outcome, CancellationOutcome):
            return outcome.identity
        try:
            return JobIdentity(outcome.job_id)
        except RuntimeBackendError as error:
            raise StateMappingError(StateMappingErrorCode.IDENTITY_MISMATCH) from error

    @staticmethod
    def _error_for_event(
        source: BrokerEvent,
        errors: tuple[BrokerError, ...],
    ) -> BrokerError | None:
        if source.code is None:
            return None
        for error in errors:
            if error.code is source.code and error.phase is source.phase:
                return error
        raise StateMappingError(StateMappingErrorCode.ERROR_MAPPING_MISSING)

    def map_outcome(
        self,
        outcome: BrokerOutcome | CancellationOutcome,
        context: StateMappingContext,
    ) -> MappedStateBatch:
        if not isinstance(outcome, (BrokerOutcome, CancellationOutcome)):
            raise StateMappingError(StateMappingErrorCode.OUTCOME_MISMATCH)
        if not isinstance(context, StateMappingContext):
            raise StateMappingError(StateMappingErrorCode.INVALID_CONTEXT)

        identity = self._identity(outcome)
        source_events = tuple(outcome.events)
        if tuple(event.sequence for event in source_events) != tuple(
            range(1, len(source_events) + 1),
        ):
            raise StateMappingError(StateMappingErrorCode.INVALID_SEQUENCE)
        if source_events[-1].state is not outcome.state:
            raise StateMappingError(StateMappingErrorCode.OUTCOME_MISMATCH)
        if isinstance(outcome, BrokerOutcome) and outcome.job_id != identity.job_id:
            raise StateMappingError(StateMappingErrorCode.IDENTITY_MISMATCH)
        if outcome.cleanup_complete != (outcome.cleanup_error is None):
            raise StateMappingError(StateMappingErrorCode.CLEANUP_INCOMPLETE)

        errors = tuple(
            error
            for error in (outcome.error, outcome.cleanup_error)
            if error is not None
        )
        if any(
            error.backend is not None and error.backend != context.backend.value
            for error in errors
        ):
            raise StateMappingError(StateMappingErrorCode.BACKEND_MISMATCH)

        incomplete_cleanup = not outcome.cleanup_complete
        if incomplete_cleanup and outcome.cleanup_error is None:
            raise StateMappingError(StateMappingErrorCode.CLEANUP_INCOMPLETE)
        result_classification = (
            outcome.result.classification if outcome.result is not None else None
        )
        cancellation_intent = (
            outcome.error is None
            and (
                isinstance(outcome, CancellationOutcome)
                or (
                    isinstance(outcome, BrokerOutcome)
                    and outcome.cancellation_checkpoint is not None
                )
            )
        )
        operation_namespace = _canonical_uuid(
            context.operation_id,
            StateMappingErrorCode.INVALID_CONTEXT,
        )
        mapped: list[DurableJobEvent] = []
        for source in source_events:
            source_error = self._error_for_event(source, errors)
            is_final = source.sequence == len(source_events)
            if incomplete_cleanup and is_final:
                state = BrokerState.CLEANING
                phase = RuntimePhase.CLEANUP
                mapped_error = outcome.cleanup_error
            else:
                state = source.state
                phase = source.phase
                mapped_error = source_error

            classification = None
            if state in {
                BrokerState.COLLECTING,
                BrokerState.CLEANING,
                BrokerState.SUCCEEDED,
                BrokerState.CANCELLED,
                BrokerState.FAILED,
            }:
                classification = result_classification
            if (
                state in {BrokerState.CLEANING, BrokerState.CANCELLED}
                and classification is None
                and cancellation_intent
            ):
                classification = TerminalClassification.CANCELLED

            mapped.append(
                DurableJobEvent(
                    identity=identity,
                    event_id=str(
                        uuid5(
                            operation_namespace,
                            f"{identity.job_id}:{source.sequence}",
                        ),
                    ),
                    operation_id=context.operation_id,
                    operation_sequence=source.sequence,
                    state=state,
                    phase=phase,
                    code=mapped_error.code if mapped_error is not None else None,
                    retry=mapped_error.retry if mapped_error is not None else None,
                    backend=context.backend,
                    classification=classification,
                    cleanup_complete=state
                    in {
                        BrokerState.SUCCEEDED,
                        BrokerState.CANCELLED,
                        BrokerState.FAILED,
                    },
                ),
            )
        return MappedStateBatch(identity, context.operation_id, tuple(mapped))


class StateEventRecorder:
    """Records a mapped batch with CAS and deterministic partial-replay semantics."""

    def __init__(self, store: DurableJobStateStore) -> None:
        if not isinstance(store, DurableJobStateStore):
            raise TypeError("StateEventRecorder requires DurableJobStateStore.")
        self._store = store

    async def record(
        self,
        batch: MappedStateBatch,
        *,
        expected_revision: int,
    ) -> JobStateSnapshot:
        if not isinstance(batch, MappedStateBatch):
            raise TypeError("StateEventRecorder requires MappedStateBatch.")
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 0
        ):
            raise TypeError("StateEventRecorder expected_revision is invalid.")
        revision = expected_revision
        snapshot: JobStateSnapshot | None = None
        for event in batch.events:
            snapshot = await self._store.append(event, expected_revision=revision)
            revision = snapshot.revision
        if snapshot is None:
            raise RuntimeError("MappedStateBatch unexpectedly contained no events.")
        return snapshot
