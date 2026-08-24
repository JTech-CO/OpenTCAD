"""Durable job-state interface and a non-durable contract test double."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from backend.app.runtime.errors import (
    ErrorCode,
    RetryDisposition,
    RuntimePhase,
)
from backend.app.runtime.models import (
    JobIdentity,
    RuntimeKind,
    TerminalClassification,
)

from .models import BrokerState


TERMINAL_STATES = frozenset(
    {BrokerState.SUCCEEDED, BrokerState.CANCELLED, BrokerState.FAILED},
)


class StateStoreErrorCode(StrEnum):
    INVALID_EVENT = "invalid-event"
    REVISION_CONFLICT = "revision-conflict"
    EVENT_CONFLICT = "event-conflict"
    INVALID_TRANSITION = "invalid-transition"
    STORE_UNAVAILABLE = "store-unavailable"


class StateStoreError(Exception):
    """Stable state-store failure with no raw database detail."""

    def __init__(self, code: StateStoreErrorCode) -> None:
        if not isinstance(code, StateStoreErrorCode):
            raise TypeError("StateStoreError requires StateStoreErrorCode.")
        self.code = code
        super().__init__(code.value)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code.value}


def _invalid_event() -> None:
    raise StateStoreError(StateStoreErrorCode.INVALID_EVENT)


def _require_uuid(value: str) -> None:
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError):
        _invalid_event()
    if str(parsed) != value:
        _invalid_event()


@dataclass(frozen=True, slots=True)
class DurableJobEvent:
    """Redacted, idempotent event accepted by a durable state adapter."""

    identity: JobIdentity
    event_id: str
    operation_id: str
    operation_sequence: int
    state: BrokerState
    phase: RuntimePhase
    code: ErrorCode | None = None
    retry: RetryDisposition | None = None
    backend: RuntimeKind | None = None
    classification: TerminalClassification | None = None
    cleanup_complete: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.identity, JobIdentity):
            _invalid_event()
        _require_uuid(self.event_id)
        _require_uuid(self.operation_id)
        if (
            not isinstance(self.operation_sequence, int)
            or isinstance(self.operation_sequence, bool)
            or self.operation_sequence < 1
        ):
            _invalid_event()
        if not isinstance(self.state, BrokerState):
            _invalid_event()
        if not isinstance(self.phase, RuntimePhase):
            _invalid_event()
        if self.code is not None and not isinstance(self.code, ErrorCode):
            _invalid_event()
        if self.retry is not None and not isinstance(self.retry, RetryDisposition):
            _invalid_event()
        if (self.code is None) != (self.retry is None):
            _invalid_event()
        if self.backend is not None and not isinstance(self.backend, RuntimeKind):
            _invalid_event()
        if self.classification is not None and not isinstance(
            self.classification,
            TerminalClassification,
        ):
            _invalid_event()
        if self.state in {
            BrokerState.VALIDATING,
            BrokerState.PREPARING,
            BrokerState.RUNNING,
            BrokerState.CANCELLING,
        } and self.classification is not None:
            _invalid_event()
        if (
            self.state is BrokerState.COLLECTING
            and self.classification is not TerminalClassification.SUCCEEDED
        ):
            _invalid_event()
        if (
            self.state is BrokerState.SUCCEEDED
            and (
                self.classification is not TerminalClassification.SUCCEEDED
                or self.code is not None
            )
        ):
            _invalid_event()
        if (
            self.state is BrokerState.CANCELLED
            and (
                self.classification
                not in {None, TerminalClassification.CANCELLED}
                or self.code is not None
            )
        ):
            _invalid_event()
        if not isinstance(self.cleanup_complete, bool):
            _invalid_event()
        if self.cleanup_complete != (self.state in TERMINAL_STATES):
            _invalid_event()

    def as_dict(self) -> dict[str, str | int | bool | None]:
        return {
            "job_id": self.identity.job_id,
            "event_id": self.event_id,
            "operation_id": self.operation_id,
            "operation_sequence": self.operation_sequence,
            "state": self.state.value,
            "phase": self.phase.value,
            "code": self.code.value if self.code is not None else None,
            "retry": self.retry.value if self.retry is not None else None,
            "backend": self.backend.value if self.backend is not None else None,
            "classification": (
                self.classification.value if self.classification is not None else None
            ),
            "cleanup_complete": self.cleanup_complete,
        }


@dataclass(frozen=True, slots=True)
class JobStateSnapshot:
    identity: JobIdentity
    revision: int
    last_event: DurableJobEvent

    def __post_init__(self) -> None:
        if not isinstance(self.identity, JobIdentity):
            _invalid_event()
        if (
            not isinstance(self.revision, int)
            or isinstance(self.revision, bool)
            or self.revision < 1
        ):
            _invalid_event()
        if not isinstance(self.last_event, DurableJobEvent):
            _invalid_event()
        if self.last_event.identity != self.identity:
            _invalid_event()

    @property
    def state(self) -> BrokerState:
        return self.last_event.state

    @property
    def recoverable(self) -> bool:
        return self.state not in TERMINAL_STATES

    def as_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            **self.last_event.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class RecoverableStatePage:
    items: tuple[JobStateSnapshot, ...]
    next_cursor: str | None

    def __post_init__(self) -> None:
        items = tuple(self.items)
        if any(not isinstance(item, JobStateSnapshot) or not item.recoverable for item in items):
            _invalid_event()
        job_ids = [item.identity.job_id for item in items]
        if job_ids != sorted(job_ids) or len(set(job_ids)) != len(job_ids):
            _invalid_event()
        if self.next_cursor is not None:
            _require_uuid(self.next_cursor)
            if not items or self.next_cursor != items[-1].identity.job_id:
                _invalid_event()
        object.__setattr__(self, "items", items)


@runtime_checkable
class DurableJobStateStore(Protocol):
    """Adapter boundary requiring atomic CAS, idempotent append, and recovery scan."""

    async def load(self, identity: JobIdentity) -> JobStateSnapshot | None: ...

    async def append(
        self,
        event: DurableJobEvent,
        *,
        expected_revision: int,
    ) -> JobStateSnapshot: ...

    async def scan_recoverable(
        self,
        *,
        after: str | None = None,
        limit: int = 100,
    ) -> RecoverableStatePage: ...


_TRANSITIONS: dict[BrokerState | None, frozenset[BrokerState]] = {
    None: frozenset({BrokerState.VALIDATING}),
    BrokerState.VALIDATING: frozenset(
        {
            BrokerState.VALIDATING,
            BrokerState.PREPARING,
            BrokerState.CANCELLING,
            BrokerState.CLEANING,
        },
    ),
    BrokerState.PREPARING: frozenset(
        {
            BrokerState.PREPARING,
            BrokerState.RUNNING,
            BrokerState.CANCELLING,
            BrokerState.CLEANING,
        },
    ),
    BrokerState.RUNNING: frozenset(
        {
            BrokerState.RUNNING,
            BrokerState.COLLECTING,
            BrokerState.CANCELLING,
            BrokerState.CLEANING,
        },
    ),
    BrokerState.COLLECTING: frozenset(
        {
            BrokerState.COLLECTING,
            BrokerState.CANCELLING,
            BrokerState.CLEANING,
        },
    ),
    BrokerState.CANCELLING: frozenset(
        {BrokerState.CANCELLING, BrokerState.CLEANING},
    ),
    BrokerState.CLEANING: frozenset(
        {
            BrokerState.CLEANING,
            BrokerState.SUCCEEDED,
            BrokerState.CANCELLED,
            BrokerState.FAILED,
        },
    ),
    BrokerState.SUCCEEDED: frozenset(),
    BrokerState.CANCELLED: frozenset(),
    BrokerState.FAILED: frozenset(),
}


class InMemoryStateStoreBacking:
    """Shared process-local backing for adapter conformance tests only."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._snapshots: dict[str, JobStateSnapshot] = {}
        self._events: dict[str, tuple[DurableJobEvent, JobStateSnapshot]] = {}
        self._operation_slots: dict[
            tuple[str, str, int],
            tuple[DurableJobEvent, JobStateSnapshot],
        ] = {}


class InMemoryJobStateStore:
    """Contract test double. Data is lost with the process and is not durable."""

    def __init__(self, backing: InMemoryStateStoreBacking | None = None) -> None:
        if backing is not None and not isinstance(backing, InMemoryStateStoreBacking):
            raise TypeError("InMemoryJobStateStore backing has the wrong type.")
        self._backing = backing or InMemoryStateStoreBacking()

    async def load(self, identity: JobIdentity) -> JobStateSnapshot | None:
        if not isinstance(identity, JobIdentity):
            _invalid_event()
        async with self._backing._lock:
            return self._backing._snapshots.get(identity.job_id)

    async def append(
        self,
        event: DurableJobEvent,
        *,
        expected_revision: int,
    ) -> JobStateSnapshot:
        if not isinstance(event, DurableJobEvent):
            _invalid_event()
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
            or expected_revision < 0
        ):
            _invalid_event()
        async with self._backing._lock:
            replay = self._backing._events.get(event.event_id)
            if replay is not None:
                prior_event, prior_snapshot = replay
                if prior_event == event:
                    return prior_snapshot
                raise StateStoreError(StateStoreErrorCode.EVENT_CONFLICT)

            operation_slot = (
                event.identity.job_id,
                event.operation_id,
                event.operation_sequence,
            )
            if operation_slot in self._backing._operation_slots:
                raise StateStoreError(StateStoreErrorCode.EVENT_CONFLICT)

            current = self._backing._snapshots.get(event.identity.job_id)
            revision = current.revision if current is not None else 0
            if revision != expected_revision:
                raise StateStoreError(StateStoreErrorCode.REVISION_CONFLICT)
            prior_state = current.state if current is not None else None
            if event.state not in _TRANSITIONS[prior_state]:
                raise StateStoreError(StateStoreErrorCode.INVALID_TRANSITION)

            snapshot = JobStateSnapshot(event.identity, revision + 1, event)
            self._backing._snapshots[event.identity.job_id] = snapshot
            self._backing._events[event.event_id] = (event, snapshot)
            self._backing._operation_slots[operation_slot] = (event, snapshot)
            return snapshot

    async def scan_recoverable(
        self,
        *,
        after: str | None = None,
        limit: int = 100,
    ) -> RecoverableStatePage:
        if after is not None:
            _require_uuid(after)
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 1
            or limit > 1_000
        ):
            _invalid_event()
        async with self._backing._lock:
            candidates = sorted(
                (
                    snapshot
                    for job_id, snapshot in self._backing._snapshots.items()
                    if snapshot.recoverable and (after is None or job_id > after)
                ),
                key=lambda snapshot: snapshot.identity.job_id,
            )
            items = tuple(candidates[:limit])
            next_cursor = items[-1].identity.job_id if len(candidates) > limit else None
            return RecoverableStatePage(items, next_cursor)
