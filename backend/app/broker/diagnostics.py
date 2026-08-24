"""Internal raw diagnostics separated from public broker records."""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.app.runtime.errors import RuntimeBackendError
from backend.app.runtime.models import JobIdentity

from .models import BrokerError


@dataclass(frozen=True, slots=True)
class InternalDiagnostic:
    """Internal-only record whose repr never exposes backend diagnostic text."""

    identity: JobIdentity
    public_error: BrokerError
    _raw_backend: str | None = field(repr=False)
    _raw_detail: str | None = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, JobIdentity):
            raise TypeError("InternalDiagnostic requires JobIdentity.")
        if not isinstance(self.public_error, BrokerError):
            raise TypeError("InternalDiagnostic requires BrokerError.")

    @classmethod
    def from_exception(
        cls,
        identity: JobIdentity,
        error: RuntimeBackendError,
    ) -> InternalDiagnostic:
        if not isinstance(error, RuntimeBackendError):
            raise TypeError("InternalDiagnostic requires RuntimeBackendError.")
        return cls(
            identity=identity,
            public_error=BrokerError.from_exception(error),
            _raw_backend=error.record.backend,
            _raw_detail=error.record.detail,
        )

    @property
    def raw_backend(self) -> str | None:
        return self._raw_backend

    @property
    def raw_detail(self) -> str | None:
        return self._raw_detail
