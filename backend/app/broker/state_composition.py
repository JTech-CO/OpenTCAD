"""Inactive startup and admission boundary for live durable broker state."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid5

from backend.app.runtime.models import JobIdentity, RuntimeKind

from .lifecycle import CancellationSignal
from .live_state import LiveStateSession
from .models import BrokerOutcome, BrokerRequest
from .orchestrator import SandboxBroker
from .recovery import CrashRecoveryCoordinator, RecoveryReport, RecoveryRequest
from .state import DurableJobStateStore, StateStoreError


BROKER_STATE_COMPOSITION_PRODUCT_ENABLED = False


class StateCompositionErrorCode(StrEnum):
    STARTUP_REQUIRED = "startup-required"
    RECOVERY_INCOMPLETE = "recovery-incomplete"
    JOB_STATE_EXISTS = "job-state-exists"
    STORE_UNAVAILABLE = "store-unavailable"
    PRODUCT_RUNTIME_DISABLED = "product-runtime-disabled"


class StateCompositionError(Exception):
    """Stable composition failure with no raw store or runtime detail."""

    def __init__(self, code: StateCompositionErrorCode) -> None:
        if not isinstance(code, StateCompositionErrorCode):
            raise TypeError("StateCompositionError requires StateCompositionErrorCode.")
        self.code = code
        super().__init__(code.value)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code.value}


def _canonical_uuid(value: str, field: str) -> UUID:
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise TypeError(f"{field} must be a canonical UUID.") from error
    if str(parsed) != value:
        raise TypeError(f"{field} must be a canonical UUID.")
    return parsed


@dataclass(frozen=True, slots=True)
class StateOperationContext:
    operation_id: str

    def __post_init__(self) -> None:
        _canonical_uuid(self.operation_id, "StateOperationContext operation_id")


@dataclass(frozen=True, slots=True)
class BrokerStartupRequest:
    startup_id: str
    page_limit: int = 100

    def __post_init__(self) -> None:
        _canonical_uuid(self.startup_id, "BrokerStartupRequest startup_id")
        if (
            not isinstance(self.page_limit, int)
            or isinstance(self.page_limit, bool)
            or self.page_limit < 1
            or self.page_limit > 1_000
        ):
            raise TypeError("BrokerStartupRequest page limit must be 1 to 1000.")


@dataclass(frozen=True, slots=True)
class BrokerStartupReport:
    startup_id: str
    pages: tuple[RecoveryReport, ...]

    def __post_init__(self) -> None:
        _canonical_uuid(self.startup_id, "BrokerStartupReport startup_id")
        pages = tuple(self.pages)
        if not pages or any(not isinstance(page, RecoveryReport) for page in pages):
            raise TypeError("BrokerStartupReport requires recovery pages.")
        object.__setattr__(self, "pages", pages)

    @property
    def recovered_items(self) -> int:
        return sum(len(page.items) for page in self.pages)


class DurableBrokerComposition:
    """Runs startup recovery before admitting opt-in persisted mock execution."""

    def __init__(
        self,
        broker: SandboxBroker,
        store: DurableJobStateStore,
    ) -> None:
        if not isinstance(broker, SandboxBroker):
            raise TypeError("DurableBrokerComposition requires SandboxBroker.")
        if not isinstance(store, DurableJobStateStore):
            raise TypeError("DurableBrokerComposition requires DurableJobStateStore.")
        if broker.runtime_kind is not RuntimeKind.MOCK:
            raise StateCompositionError(
                StateCompositionErrorCode.PRODUCT_RUNTIME_DISABLED,
            )
        self._broker = broker
        self._store = store
        self._startup_lock = asyncio.Lock()
        self._startup_report: BrokerStartupReport | None = None

    @property
    def ready(self) -> bool:
        return self._startup_report is not None

    @staticmethod
    def _recovery_id(startup_id: str, after: str | None) -> str:
        return str(uuid5(UUID(startup_id), f"page:{after or 'start'}"))

    async def startup(self, request: BrokerStartupRequest) -> BrokerStartupReport:
        if not isinstance(request, BrokerStartupRequest):
            raise TypeError("DurableBrokerComposition requires BrokerStartupRequest.")
        async with self._startup_lock:
            if self._startup_report is not None:
                return self._startup_report
            coordinator = CrashRecoveryCoordinator(
                self._store,
                self._broker,
                self._broker.runtime_kind,
            )
            pages: list[RecoveryReport] = []
            after: str | None = None
            seen_cursors: set[str] = set()
            try:
                while True:
                    report = await coordinator.recover(
                        RecoveryRequest(
                            self._recovery_id(request.startup_id, after),
                            after=after,
                            limit=request.page_limit,
                        ),
                    )
                    pages.append(report)
                    if report.next_cursor is None:
                        break
                    if report.next_cursor in seen_cursors:
                        raise StateCompositionError(
                            StateCompositionErrorCode.RECOVERY_INCOMPLETE,
                        )
                    seen_cursors.add(report.next_cursor)
                    after = report.next_cursor
                remaining = await self._store.scan_recoverable(limit=1)
            except StateStoreError:
                raise StateCompositionError(
                    StateCompositionErrorCode.STORE_UNAVAILABLE,
                ) from None
            if remaining.items:
                raise StateCompositionError(
                    StateCompositionErrorCode.RECOVERY_INCOMPLETE,
                )
            self._startup_report = BrokerStartupReport(
                request.startup_id,
                tuple(pages),
            )
            return self._startup_report

    async def execute(
        self,
        request: BrokerRequest,
        context: StateOperationContext,
        cancellation: CancellationSignal | None = None,
    ) -> BrokerOutcome:
        if not isinstance(request, BrokerRequest):
            raise TypeError("DurableBrokerComposition requires BrokerRequest.")
        if not isinstance(context, StateOperationContext):
            raise TypeError("DurableBrokerComposition requires StateOperationContext.")
        if not self.ready:
            raise StateCompositionError(StateCompositionErrorCode.STARTUP_REQUIRED)
        identity = JobIdentity(request.spec.job_id)
        try:
            current = await self._store.load(identity)
        except StateStoreError:
            raise StateCompositionError(
                StateCompositionErrorCode.STORE_UNAVAILABLE,
            ) from None
        if current is not None:
            raise StateCompositionError(StateCompositionErrorCode.JOB_STATE_EXISTS)
        session = LiveStateSession(
            self._store,
            identity,
            context.operation_id,
            self._broker.runtime_kind,
        )
        return await self._broker._execute_with_state_session(
            request,
            cancellation,
            session,
        )
