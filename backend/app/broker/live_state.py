"""Phase-time broker event persistence for an inactive durable composition."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid5

from backend.app.runtime.errors import RuntimePhase
from backend.app.runtime.models import JobIdentity, RuntimeKind, TerminalClassification

from .models import BrokerError, BrokerEvent, BrokerState
from .state import (
    DurableJobEvent,
    DurableJobStateStore,
    DurableOperationOwnership,
    JobStateSnapshot,
    OperationOwnershipError,
    StateStoreError,
    StateStoreErrorCode,
)


@dataclass(frozen=True, slots=True)
class LiveStateEmission:
    """One public event plus the exact redacted state written at that boundary."""

    source: BrokerEvent
    state: BrokerState
    phase: RuntimePhase
    error: BrokerError | None = None
    classification: TerminalClassification | None = None
    cleanup_complete: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.source, BrokerEvent):
            raise TypeError("LiveStateEmission requires BrokerEvent.")
        if not isinstance(self.state, BrokerState):
            raise TypeError("LiveStateEmission requires BrokerState.")
        if not isinstance(self.phase, RuntimePhase):
            raise TypeError("LiveStateEmission requires RuntimePhase.")
        if self.error is not None and not isinstance(self.error, BrokerError):
            raise TypeError("LiveStateEmission error has the wrong type.")
        if self.classification is not None and not isinstance(
            self.classification,
            TerminalClassification,
        ):
            raise TypeError("LiveStateEmission classification has the wrong type.")
        if not isinstance(self.cleanup_complete, bool):
            raise TypeError("LiveStateEmission cleanup marker must be boolean.")
        if self.state is self.source.state and self.source.code != (
            self.error.code if self.error is not None else None
        ):
            raise TypeError("LiveStateEmission source error does not match.")
        if self.state is not self.source.state and not (
            self.source.state is BrokerState.FAILED
            and self.state is BrokerState.CLEANING
            and not self.cleanup_complete
        ):
            raise TypeError("LiveStateEmission durable state override is invalid.")


class LiveStateWriteError(Exception):
    """Stable write interruption with no raw driver or filesystem detail."""

    def __init__(
        self,
        code: StateStoreErrorCode,
        sequence: int,
        phase: RuntimePhase,
    ) -> None:
        if not isinstance(code, StateStoreErrorCode):
            raise TypeError("LiveStateWriteError requires StateStoreErrorCode.")
        if (
            not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence < 1
        ):
            raise TypeError("LiveStateWriteError sequence must be positive.")
        if not isinstance(phase, RuntimePhase):
            raise TypeError("LiveStateWriteError requires RuntimePhase.")
        self.code = code
        self.sequence = sequence
        self.phase = phase
        super().__init__(code.value)

    def as_dict(self) -> dict[str, str | int]:
        return {
            "code": self.code.value,
            "sequence": self.sequence,
            "phase": self.phase.value,
        }


class LiveStateSession:
    """Binds one admitted broker operation to deterministic durable events."""

    def __init__(
        self,
        store: DurableJobStateStore,
        identity: JobIdentity,
        operation_id: str,
        owner_id: str,
        fencing_token: int,
        backend: RuntimeKind,
        *,
        expected_revision: int = 0,
    ) -> None:
        if not isinstance(store, DurableJobStateStore):
            raise TypeError("LiveStateSession requires DurableJobStateStore.")
        if not isinstance(identity, JobIdentity):
            raise TypeError("LiveStateSession requires JobIdentity.")
        try:
            parsed = UUID(operation_id)
        except (AttributeError, TypeError, ValueError) as error:
            raise TypeError("LiveStateSession operation ID must be a UUID.") from error
        if str(parsed) != operation_id:
            raise TypeError("LiveStateSession operation ID must be canonical.")
        if not isinstance(backend, RuntimeKind):
            raise TypeError("LiveStateSession requires RuntimeKind.")
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 0
        ):
            raise TypeError("LiveStateSession expected revision is invalid.")
        ownership = DurableOperationOwnership(
            identity,
            operation_id,
            owner_id,
            fencing_token,
        )
        self._store = store
        self._identity = identity
        self._ownership = ownership
        self._operation_id = operation_id
        self._operation_namespace = parsed
        self._backend = backend
        self._revision = expected_revision
        self._next_sequence = 1
        self._failed = False
        self._last_snapshot: JobStateSnapshot | None = None

    @property
    def identity(self) -> JobIdentity:
        return self._identity

    @property
    def backend(self) -> RuntimeKind:
        return self._backend

    @property
    def ownership(self) -> DurableOperationOwnership:
        return self._ownership

    @property
    def failed(self) -> bool:
        return self._failed

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def last_snapshot(self) -> JobStateSnapshot | None:
        return self._last_snapshot

    def _event(self, emission: LiveStateEmission) -> DurableJobEvent:
        source = emission.source
        return DurableJobEvent(
            identity=self._identity,
            event_id=str(
                uuid5(
                    self._operation_namespace,
                    f"{self._identity.job_id}:{source.sequence}",
                ),
            ),
            operation_id=self._operation_id,
            operation_sequence=source.sequence,
            owner_id=self._ownership.owner_id,
            fencing_token=self._ownership.fencing_token,
            state=emission.state,
            phase=emission.phase,
            code=emission.error.code if emission.error is not None else None,
            retry=emission.error.retry if emission.error is not None else None,
            backend=self._backend,
            classification=emission.classification,
            cleanup_complete=emission.cleanup_complete,
        )

    async def assert_owned(self, phase: RuntimePhase) -> None:
        if not isinstance(phase, RuntimePhase):
            raise TypeError("LiveStateSession ownership check requires RuntimePhase.")
        if self._last_snapshot is None:
            raise OperationOwnershipError(
                StateStoreErrorCode.OWNERSHIP_CONFLICT,
                phase,
            )
        try:
            await self._store.verify_ownership(
                self._ownership,
                expected_revision=self._revision,
            )
        except StateStoreError as error:
            self._failed = True
            raise OperationOwnershipError(error.code, phase) from None

    async def record(
        self,
        emission: LiveStateEmission,
    ) -> JobStateSnapshot | None:
        if not isinstance(emission, LiveStateEmission):
            raise TypeError("LiveStateSession requires LiveStateEmission.")
        if self._failed:
            return None
        source = emission.source
        if source.sequence != self._next_sequence:
            self._failed = True
            raise LiveStateWriteError(
                StateStoreErrorCode.INVALID_EVENT,
                source.sequence,
                emission.phase,
            )
        try:
            event = self._event(emission)
            snapshot = await self._store.append(
                event,
                expected_revision=self._revision,
            )
        except StateStoreError as error:
            self._failed = True
            raise LiveStateWriteError(
                error.code,
                source.sequence,
                emission.phase,
            ) from None
        self._revision = snapshot.revision
        self._next_sequence += 1
        self._last_snapshot = snapshot
        return snapshot
