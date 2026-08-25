"""Typed job fencing context crossing the broker/runtime adapter boundary."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .errors import ErrorCode, RuntimeBackendError, RuntimePhase
from .models import JobIdentity


@dataclass(frozen=True, slots=True)
class RuntimeFencingContext:
    """Exact owner generation that a job-scoped runtime call must carry."""

    identity: JobIdentity
    owner_id: str
    fencing_token: int

    def __post_init__(self) -> None:
        if not isinstance(self.identity, JobIdentity):
            self._invalid("runtime-fence:job-identity-required")
        try:
            parsed = UUID(self.owner_id)
        except (AttributeError, TypeError, ValueError):
            self._invalid("runtime-fence:owner-uuid-required")
        if str(parsed) != self.owner_id:
            self._invalid("runtime-fence:canonical-owner-uuid-required")
        if (
            not isinstance(self.fencing_token, int)
            or isinstance(self.fencing_token, bool)
            or self.fencing_token < 1
        ):
            self._invalid("runtime-fence:positive-token-required")

    @staticmethod
    def _invalid(detail: str) -> None:
        raise RuntimeBackendError(
            ErrorCode.INVALID_SPEC,
            RuntimePhase.VALIDATE,
            detail=detail,
        )

    @property
    def labels(self) -> tuple[tuple[str, str], ...]:
        return (
            ("tcad.job_id", self.identity.job_id),
            ("tcad.owner_id", self.owner_id),
            ("tcad.fencing_token", str(self.fencing_token)),
        )
