"""Engine-independent crash/restart recovery contract for durable job state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID, uuid4, uuid5

from backend.app.runtime.errors import (
    ErrorCode,
    RetryDisposition,
    RuntimeBackendError,
    RuntimePhase,
)
from backend.app.runtime.models import JobIdentity, RuntimeKind, TerminalClassification

from .models import BrokerError, BrokerState, ReconciliationReport
from .state import (
    DurableJobEvent,
    DurableJobStateStore,
    DurableOperationGuard,
    JobStateSnapshot,
    OperationOwnershipError,
    OperationOwnershipGuard,
    StateStoreError,
    StateStoreErrorCode,
)


class RecoveryCheckpoint(StrEnum):
    BEFORE_CLAIM = "before-claim"
    AFTER_CLAIM = "after-claim"
    AFTER_RECONCILE = "after-reconcile"
    AFTER_TERMINAL_APPEND = "after-terminal-append"


class RecoveryStatus(StrEnum):
    RECOVERED_FAILED = "recovered-failed"
    RECOVERED_CANCELLED = "recovered-cancelled"
    CLEANUP_PENDING = "cleanup-pending"
    REVISION_CONFLICT = "revision-conflict"
    OWNERSHIP_CONFLICT = "ownership-conflict"


class RecoveryInterrupted(Exception):
    """Deterministic process-crash surrogate used only by contract tests."""

    def __init__(self, checkpoint: RecoveryCheckpoint) -> None:
        if not isinstance(checkpoint, RecoveryCheckpoint):
            raise TypeError("RecoveryInterrupted requires RecoveryCheckpoint.")
        self.checkpoint = checkpoint
        super().__init__(checkpoint.value)


@runtime_checkable
class RecoveryCrashSignal(Protocol):
    def requested(
        self,
        checkpoint: RecoveryCheckpoint,
        identity: JobIdentity,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class RecoveryCrashInjection:
    checkpoint: RecoveryCheckpoint
    job_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.checkpoint, RecoveryCheckpoint):
            raise TypeError("RecoveryCrashInjection requires RecoveryCheckpoint.")
        if self.job_id is not None:
            JobIdentity(self.job_id)

    def requested(
        self,
        checkpoint: RecoveryCheckpoint,
        identity: JobIdentity,
    ) -> bool:
        return checkpoint is self.checkpoint and (
            self.job_id is None or identity.job_id == self.job_id
        )


@dataclass(frozen=True, slots=True)
class RecoveryRequest:
    recovery_id: str
    after: str | None = None
    limit: int = 100

    def __post_init__(self) -> None:
        try:
            parsed = UUID(self.recovery_id)
        except (AttributeError, TypeError, ValueError) as error:
            raise TypeError("RecoveryRequest recovery_id must be a canonical UUID.") from error
        if str(parsed) != self.recovery_id:
            raise TypeError("RecoveryRequest recovery_id must be a canonical UUID.")
        if self.after is not None:
            JobIdentity(self.after)
        if (
            not isinstance(self.limit, int)
            or isinstance(self.limit, bool)
            or self.limit < 1
            or self.limit > 1_000
        ):
            raise TypeError("RecoveryRequest limit must be between 1 and 1000.")


@dataclass(frozen=True, slots=True)
class RecoveryItem:
    identity: JobIdentity
    status: RecoveryStatus
    revision: int
    code: ErrorCode | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, JobIdentity):
            raise TypeError("RecoveryItem requires JobIdentity.")
        if not isinstance(self.status, RecoveryStatus):
            raise TypeError("RecoveryItem requires RecoveryStatus.")
        if (
            not isinstance(self.revision, int)
            or isinstance(self.revision, bool)
            or self.revision < 1
        ):
            raise TypeError("RecoveryItem revision must be positive.")
        if self.code is not None and not isinstance(self.code, ErrorCode):
            raise TypeError("RecoveryItem code must be ErrorCode or None.")

    def as_dict(self) -> dict[str, str | int | None]:
        return {
            "job_id": self.identity.job_id,
            "status": self.status.value,
            "revision": self.revision,
            "code": self.code.value if self.code is not None else None,
        }


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    recovery_id: str
    items: tuple[RecoveryItem, ...]
    next_cursor: str | None

    def __post_init__(self) -> None:
        try:
            parsed = UUID(self.recovery_id)
        except (AttributeError, TypeError, ValueError) as error:
            raise TypeError("RecoveryReport recovery_id must be a canonical UUID.") from error
        if str(parsed) != self.recovery_id:
            raise TypeError("RecoveryReport recovery_id must be a canonical UUID.")
        items = tuple(self.items)
        if any(not isinstance(item, RecoveryItem) for item in items):
            raise TypeError("RecoveryReport requires RecoveryItem records.")
        object.__setattr__(self, "items", items)
        if self.next_cursor is not None:
            JobIdentity(self.next_cursor)

    def as_dict(self) -> dict[str, Any]:
        return {
            "recovery_id": self.recovery_id,
            "items": [item.as_dict() for item in self.items],
            "next_cursor": self.next_cursor,
        }


@runtime_checkable
class RecoveryReconciler(Protocol):
    async def reconcile(
        self,
        job_id: str | None = None,
        *,
        ownership_guard: OperationOwnershipGuard | None = None,
    ) -> ReconciliationReport: ...


class CrashRecoveryCoordinator:
    """Claims recoverable revisions, reconciles objects, and closes state fail-safe."""

    def __init__(
        self,
        store: DurableJobStateStore,
        reconciler: RecoveryReconciler,
        backend: RuntimeKind,
    ) -> None:
        if not isinstance(store, DurableJobStateStore):
            raise TypeError("CrashRecoveryCoordinator requires DurableJobStateStore.")
        if not isinstance(reconciler, RecoveryReconciler):
            raise TypeError("CrashRecoveryCoordinator requires RecoveryReconciler.")
        if not isinstance(backend, RuntimeKind):
            raise TypeError("CrashRecoveryCoordinator requires RuntimeKind.")
        self._store = store
        self._reconciler = reconciler
        self._backend = backend

    @staticmethod
    def _checkpoint(
        signal: RecoveryCrashSignal | None,
        checkpoint: RecoveryCheckpoint,
        identity: JobIdentity,
    ) -> None:
        if signal is None:
            return
        if not isinstance(signal, RecoveryCrashSignal):
            raise TypeError("Recovery crash signal has the wrong type.")
        requested = signal.requested(checkpoint, identity)
        if not isinstance(requested, bool):
            raise TypeError("Recovery crash signal must return bool.")
        if requested:
            raise RecoveryInterrupted(checkpoint)

    @staticmethod
    def _event_id(owner_id: str, identity: JobIdentity, suffix: str) -> str:
        return str(uuid5(UUID(owner_id), f"{identity.job_id}:{suffix}"))

    def _claim_event(
        self,
        snapshot: JobStateSnapshot,
        owner_id: str,
    ) -> DurableJobEvent:
        return DurableJobEvent(
            identity=snapshot.identity,
            event_id=self._event_id(owner_id, snapshot.identity, "claim"),
            operation_id=owner_id,
            operation_sequence=1,
            owner_id=owner_id,
            fencing_token=snapshot.ownership.fencing_token + 1,
            state=BrokerState.CLEANING,
            phase=RuntimePhase.CLEANUP,
            backend=self._backend,
            classification=(
                TerminalClassification.CANCELLED
                if snapshot.state is BrokerState.CANCELLING
                else snapshot.last_event.classification
            ),
        )

    def _result_event(
        self,
        claimed: JobStateSnapshot,
        *,
        cancellation_intent: bool,
        cleanup_error: BrokerError | None,
    ) -> DurableJobEvent:
        if cleanup_error is not None:
            return DurableJobEvent(
                identity=claimed.identity,
                event_id=self._event_id(
                    claimed.ownership.owner_id,
                    claimed.identity,
                    "pending",
                ),
                operation_id=claimed.ownership.operation_id,
                operation_sequence=2,
                owner_id=claimed.ownership.owner_id,
                fencing_token=claimed.ownership.fencing_token,
                state=BrokerState.CLEANING,
                phase=cleanup_error.phase,
                code=cleanup_error.code,
                retry=cleanup_error.retry,
                backend=self._backend,
                classification=claimed.last_event.classification,
            )
        if cancellation_intent:
            return DurableJobEvent(
                identity=claimed.identity,
                event_id=self._event_id(
                    claimed.ownership.owner_id,
                    claimed.identity,
                    "terminal",
                ),
                operation_id=claimed.ownership.operation_id,
                operation_sequence=2,
                owner_id=claimed.ownership.owner_id,
                fencing_token=claimed.ownership.fencing_token,
                state=BrokerState.CANCELLED,
                phase=RuntimePhase.CLEANUP,
                backend=self._backend,
                classification=TerminalClassification.CANCELLED,
                cleanup_complete=True,
            )
        return DurableJobEvent(
            identity=claimed.identity,
            event_id=self._event_id(
                claimed.ownership.owner_id,
                claimed.identity,
                "terminal",
            ),
            operation_id=claimed.ownership.operation_id,
            operation_sequence=2,
            owner_id=claimed.ownership.owner_id,
            fencing_token=claimed.ownership.fencing_token,
            state=BrokerState.FAILED,
            phase=RuntimePhase.CLEANUP,
            code=ErrorCode.STALE_STATE,
            retry=RetryDisposition.INFRASTRUCTURE,
            backend=self._backend,
            classification=claimed.last_event.classification,
            cleanup_complete=True,
        )

    async def recover(
        self,
        request: RecoveryRequest,
        crash_signal: RecoveryCrashSignal | None = None,
    ) -> RecoveryReport:
        if not isinstance(request, RecoveryRequest):
            raise TypeError("CrashRecoveryCoordinator requires RecoveryRequest.")
        page = await self._store.scan_recoverable(
            after=request.after,
            limit=request.limit,
        )
        recovered: list[RecoveryItem] = []
        for snapshot in page.items:
            identity = snapshot.identity
            self._checkpoint(
                crash_signal,
                RecoveryCheckpoint.BEFORE_CLAIM,
                identity,
            )
            cancellation_intent = (
                snapshot.state is BrokerState.CANCELLING
                or snapshot.last_event.classification
                is TerminalClassification.CANCELLED
            )
            owner_id = str(uuid4())
            try:
                claimed = await self._store.append(
                    self._claim_event(snapshot, owner_id),
                    expected_revision=snapshot.revision,
                )
            except StateStoreError as error:
                if error.code is not StateStoreErrorCode.REVISION_CONFLICT:
                    raise
                recovered.append(
                    RecoveryItem(
                        identity,
                        RecoveryStatus.REVISION_CONFLICT,
                        snapshot.revision,
                        ErrorCode.STALE_STATE,
                    ),
                )
                continue

            self._checkpoint(
                crash_signal,
                RecoveryCheckpoint.AFTER_CLAIM,
                identity,
            )
            cleanup_error: BrokerError | None = None
            guard = DurableOperationGuard(
                self._store,
                claimed.ownership,
                claimed.revision,
            )
            try:
                await guard.assert_owned(RuntimePhase.QUERY)
                reconciliation = await self._reconciler.reconcile(
                    identity.job_id,
                    ownership_guard=guard,
                )
                await guard.assert_owned(RuntimePhase.QUERY)
                if not isinstance(reconciliation, ReconciliationReport):
                    raise TypeError("Recovery reconciler returned the wrong type.")
                if not reconciliation.complete:
                    cleanup_error = reconciliation.errors[0] if reconciliation.errors else BrokerError(
                        ErrorCode.CLEANUP_FAILED,
                        RuntimePhase.CLEANUP,
                        RetryDisposition.INFRASTRUCTURE,
                        self._backend.value,
                    )
            except OperationOwnershipError as error:
                if error.code not in {
                    StateStoreErrorCode.OWNERSHIP_CONFLICT,
                    StateStoreErrorCode.REVISION_CONFLICT,
                    StateStoreErrorCode.EVENT_CONFLICT,
                }:
                    raise StateStoreError(error.code) from None
                recovered.append(
                    RecoveryItem(
                        identity,
                        RecoveryStatus.OWNERSHIP_CONFLICT,
                        claimed.revision,
                        ErrorCode.OPERATION_FENCED,
                    ),
                )
                continue
            except RuntimeBackendError as error:
                cleanup_error = BrokerError.from_exception(error)

            self._checkpoint(
                crash_signal,
                RecoveryCheckpoint.AFTER_RECONCILE,
                identity,
            )
            result_event = self._result_event(
                claimed,
                cancellation_intent=cancellation_intent,
                cleanup_error=cleanup_error,
            )
            try:
                terminal = await self._store.append(
                    result_event,
                    expected_revision=claimed.revision,
                )
            except StateStoreError as error:
                if error.code not in {
                    StateStoreErrorCode.REVISION_CONFLICT,
                    StateStoreErrorCode.OWNERSHIP_CONFLICT,
                }:
                    raise
                ownership_conflict = (
                    error.code is StateStoreErrorCode.OWNERSHIP_CONFLICT
                )
                recovered.append(
                    RecoveryItem(
                        identity,
                        RecoveryStatus.OWNERSHIP_CONFLICT
                        if ownership_conflict
                        else RecoveryStatus.REVISION_CONFLICT,
                        claimed.revision,
                        ErrorCode.OPERATION_FENCED
                        if ownership_conflict
                        else ErrorCode.STALE_STATE,
                    ),
                )
                continue

            if cleanup_error is not None:
                recovered.append(
                    RecoveryItem(
                        identity,
                        RecoveryStatus.CLEANUP_PENDING,
                        terminal.revision,
                        cleanup_error.code,
                    ),
                )
                continue

            self._checkpoint(
                crash_signal,
                RecoveryCheckpoint.AFTER_TERMINAL_APPEND,
                identity,
            )
            status = (
                RecoveryStatus.RECOVERED_CANCELLED
                if cancellation_intent
                else RecoveryStatus.RECOVERED_FAILED
            )
            recovered.append(
                RecoveryItem(
                    identity,
                    status,
                    terminal.revision,
                    None if cancellation_intent else ErrorCode.STALE_STATE,
                ),
            )
        return RecoveryReport(request.recovery_id, tuple(recovered), page.next_cursor)
