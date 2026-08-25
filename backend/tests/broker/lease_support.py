"""Deterministic owner-lease clock shared by broker contract tests."""

from __future__ import annotations


class ManualLeaseClock:
    def __init__(self, now_ms: int = 1_000_000) -> None:
        self._now_ms = now_ms

    def now_ms(self) -> int:
        return self._now_ms

    def advance(self, milliseconds: int) -> None:
        if (
            not isinstance(milliseconds, int)
            or isinstance(milliseconds, bool)
            or milliseconds < 1
        ):
            raise TypeError("Manual lease advance must be a positive integer.")
        self._now_ms += milliseconds
