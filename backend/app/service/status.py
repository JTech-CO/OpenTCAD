"""Versioned, redacted product status exposed to the local web client."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from backend.app.product.gates import ProductGateReport
from backend.app.runtime.models import RuntimeKind


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class LocalServiceState(StrEnum):
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"


class LocalExecutionState(StrEnum):
    BLOCKED = "blocked"
    AUTHORIZED = "authorized"


class LocalRecoveryState(StrEnum):
    NOT_APPLICABLE = "not-applicable"
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class LocalSchedulerState(StrEnum):
    NOT_STARTED = "not-started"
    RUNNING = "running"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class LocalProductStatus:
    """Small public status contract without paths, secrets, or native errors."""

    service_state: LocalServiceState
    execution_state: LocalExecutionState
    manifest_sha256: str
    backend: RuntimeKind | None
    blocked_gates: tuple[str, ...]
    recovery_state: LocalRecoveryState
    scheduler_state: LocalSchedulerState

    def __post_init__(self) -> None:
        if (
            not isinstance(self.service_state, LocalServiceState)
            or not isinstance(self.execution_state, LocalExecutionState)
            or _SHA256.fullmatch(self.manifest_sha256) is None
            or self.backend is RuntimeKind.MOCK
            or any(
                not isinstance(item, str) or not item or len(item) > 64
                for item in self.blocked_gates
            )
            or len(set(self.blocked_gates)) != len(self.blocked_gates)
            or not isinstance(self.recovery_state, LocalRecoveryState)
            or not isinstance(self.scheduler_state, LocalSchedulerState)
        ):
            raise TypeError("Local product status is invalid.")
        if self.execution_state is LocalExecutionState.BLOCKED:
            if not self.blocked_gates or self.backend is not None:
                raise TypeError("Blocked product status requires gate IDs only.")
        elif self.blocked_gates or self.backend not in {
            RuntimeKind.DOCKER,
            RuntimeKind.PODMAN,
        }:
            raise TypeError("Authorized product status requires one OCI backend.")
        object.__setattr__(self, "blocked_gates", tuple(self.blocked_gates))

    def as_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "serviceState": self.service_state.value,
            "executionState": self.execution_state.value,
            "manifestSha256": self.manifest_sha256,
            "backend": None if self.backend is None else self.backend.value,
            "blockedGates": list(self.blocked_gates),
            "recoveryState": self.recovery_state.value,
            "schedulerState": self.scheduler_state.value,
        }

    @classmethod
    def blocked(cls, report: ProductGateReport) -> LocalProductStatus:
        if not isinstance(report, ProductGateReport) or report.product_enabled:
            raise TypeError("Blocked status requires a disabled product report.")
        return cls(
            LocalServiceState.READY,
            LocalExecutionState.BLOCKED,
            report.manifest_sha256,
            None,
            tuple(item.value for item in report.blocked_gate_ids),
            LocalRecoveryState.NOT_APPLICABLE,
            LocalSchedulerState.NOT_STARTED,
        )

    @classmethod
    def activated(
        cls,
        report: ProductGateReport,
        backend: RuntimeKind,
        *,
        service_ready: bool,
        recovery_ready: bool,
        scheduler_running: bool,
        scheduler_degraded: bool = False,
    ) -> LocalProductStatus:
        if (
            not isinstance(report, ProductGateReport)
            or not report.ready
            or backend not in {RuntimeKind.DOCKER, RuntimeKind.PODMAN}
        ):
            raise TypeError("Activated status requires an approved product report.")
        service_state = (
            LocalServiceState.DEGRADED
            if scheduler_degraded
            else LocalServiceState.READY
            if service_ready and recovery_ready and scheduler_running
            else LocalServiceState.STARTING
        )
        scheduler_state = (
            LocalSchedulerState.DEGRADED
            if scheduler_degraded
            else LocalSchedulerState.RUNNING
            if scheduler_running
            else LocalSchedulerState.NOT_STARTED
        )
        return cls(
            service_state,
            LocalExecutionState.AUTHORIZED,
            report.manifest_sha256,
            backend,
            (),
            LocalRecoveryState.READY if recovery_ready else LocalRecoveryState.PENDING,
            scheduler_state,
        )
