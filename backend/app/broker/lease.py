"""Bounded durable owner-lease policy and injectable UTC clock."""

from __future__ import annotations

from dataclasses import dataclass
from time import time_ns
from typing import Protocol, runtime_checkable


DEFAULT_OWNER_LEASE_DURATION_MS = 30_000
DEFAULT_OWNER_HEARTBEAT_INTERVAL_MS = 10_000
MAX_OWNER_LEASE_DURATION_MS = 300_000


@runtime_checkable
class LeaseClock(Protocol):
    """UTC epoch-millisecond source used by durable state adapters."""

    def now_ms(self) -> int: ...


@dataclass(frozen=True, slots=True)
class SystemLeaseClock:
    def now_ms(self) -> int:
        return time_ns() // 1_000_000


@dataclass(frozen=True, slots=True)
class OwnerLeasePolicy:
    """One bounded lease period and its proactive renewal cadence."""

    duration_ms: int = DEFAULT_OWNER_LEASE_DURATION_MS
    heartbeat_interval_ms: int = DEFAULT_OWNER_HEARTBEAT_INTERVAL_MS

    def __post_init__(self) -> None:
        if (
            not isinstance(self.duration_ms, int)
            or isinstance(self.duration_ms, bool)
            or self.duration_ms < 1
            or self.duration_ms > MAX_OWNER_LEASE_DURATION_MS
        ):
            raise TypeError("Owner lease duration is out of range.")
        if (
            not isinstance(self.heartbeat_interval_ms, int)
            or isinstance(self.heartbeat_interval_ms, bool)
            or self.heartbeat_interval_ms < 1
            or self.heartbeat_interval_ms >= self.duration_ms
        ):
            raise TypeError("Owner heartbeat interval must be shorter than the lease.")


def require_lease_clock(clock: LeaseClock | None) -> LeaseClock:
    candidate = clock or SystemLeaseClock()
    if not isinstance(candidate, LeaseClock):
        raise TypeError("Durable state store requires LeaseClock.")
    observed = candidate.now_ms()
    if not isinstance(observed, int) or isinstance(observed, bool) or observed < 0:
        raise TypeError("LeaseClock must return a non-negative integer.")
    return candidate
