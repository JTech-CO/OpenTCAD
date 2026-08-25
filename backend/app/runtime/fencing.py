"""Typed job fencing context crossing the broker/runtime adapter boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self
from uuid import UUID

from .errors import ErrorCode, RuntimeBackendError, RuntimePhase
from .models import JobIdentity, RuntimeKind


RUNTIME_JOB_ID_LABEL = "tcad.job_id"
RUNTIME_OWNER_ID_LABEL = "tcad.owner_id"
RUNTIME_FENCING_TOKEN_LABEL = "tcad.fencing_token"
RUNTIME_FENCE_LABEL_KEYS = (
    RUNTIME_JOB_ID_LABEL,
    RUNTIME_OWNER_ID_LABEL,
    RUNTIME_FENCING_TOKEN_LABEL,
)
TAKEOVER_OBJECT_PHASES = frozenset(
    {RuntimePhase.KILL, RuntimePhase.CLEANUP, RuntimePhase.QUERY},
)


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
            (RUNTIME_JOB_ID_LABEL, self.identity.job_id),
            (RUNTIME_OWNER_ID_LABEL, self.owner_id),
            (RUNTIME_FENCING_TOKEN_LABEL, str(self.fencing_token)),
        )

    @classmethod
    def from_labels(cls, labels: Mapping[str, str]) -> Self:
        if not isinstance(labels, Mapping):
            cls._invalid("runtime-fence:label-mapping-required")
        try:
            job_id = labels[RUNTIME_JOB_ID_LABEL]
            owner_id = labels[RUNTIME_OWNER_ID_LABEL]
            token_text = labels[RUNTIME_FENCING_TOKEN_LABEL]
        except (KeyError, TypeError):
            cls._invalid("runtime-fence:required-label-missing")
        if not all(isinstance(value, str) for value in (job_id, owner_id, token_text)):
            cls._invalid("runtime-fence:text-label-required")
        try:
            fencing_token = int(token_text)
        except ValueError:
            cls._invalid("runtime-fence:decimal-token-required")
        if str(fencing_token) != token_text:
            cls._invalid("runtime-fence:canonical-token-required")
        return cls(JobIdentity(job_id), owner_id, fencing_token)


def enforce_runtime_object_fence(
    requested: RuntimeFencingContext,
    observed: RuntimeFencingContext,
    phase: RuntimePhase,
    backend: RuntimeKind,
) -> None:
    """Authorize exact-generation work or takeover-only predecessor cleanup."""

    if not isinstance(requested, RuntimeFencingContext) or not isinstance(
        observed,
        RuntimeFencingContext,
    ):
        raise TypeError("Runtime object fencing requires fencing contexts.")
    if not isinstance(phase, RuntimePhase) or not isinstance(backend, RuntimeKind):
        raise TypeError("Runtime object fencing requires phase and backend.")
    if requested.identity != observed.identity:
        raise RuntimeBackendError(
            ErrorCode.IDENTITY_MISMATCH,
            phase,
            backend=backend.value,
            detail="runtime-object-fence-job-mismatch",
        )
    if requested == observed:
        return
    if (
        observed.fencing_token < requested.fencing_token
        and phase in TAKEOVER_OBJECT_PHASES
    ):
        return
    raise RuntimeBackendError(
        ErrorCode.OPERATION_FENCED,
        phase,
        backend=backend.value,
        detail="runtime-object-fence-rejected",
    )
