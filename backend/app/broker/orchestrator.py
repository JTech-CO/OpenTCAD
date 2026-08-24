"""Mock-testable broker lifecycle orchestration with exact cleanup ownership."""

from __future__ import annotations

from backend.app.runtime.errors import (
    ErrorCode,
    RetryDisposition,
    RuntimeBackendError,
    RuntimePhase,
)
from backend.app.runtime.models import (
    ArtifactRecord,
    ContainerHandle,
    RunResult,
    RuntimeHealth,
    TerminalClassification,
    TerminationReason,
    VolumeHandle,
)
from backend.app.runtime.policy import SandboxPolicy
from backend.app.runtime.protocol import RuntimeBackend

from .archive import ArchiveLimits, validate_canonical_input_archive
from .models import (
    BrokerError,
    BrokerEvent,
    BrokerOutcome,
    BrokerRequest,
    BrokerState,
    ReconciliationReport,
)


class SandboxBroker:
    """Internal library only. It exposes no network service or runtime socket."""

    def __init__(
        self,
        backend: RuntimeBackend,
        policy: SandboxPolicy,
        archive_limits: ArchiveLimits,
    ) -> None:
        if not isinstance(backend, RuntimeBackend):
            raise TypeError("SandboxBroker requires RuntimeBackend.")
        if not isinstance(policy, SandboxPolicy):
            raise TypeError("SandboxBroker requires SandboxPolicy.")
        if not isinstance(archive_limits, ArchiveLimits):
            raise TypeError("SandboxBroker requires ArchiveLimits.")
        self._backend = backend
        self._policy = policy
        self._archive_limits = archive_limits

    @staticmethod
    def _event(
        events: list[BrokerEvent],
        state: BrokerState,
        phase: RuntimePhase,
        code: ErrorCode | None = None,
    ) -> None:
        events.append(BrokerEvent(len(events) + 1, state, phase, code))

    async def _cleanup(
        self,
        container: ContainerHandle | None,
        volume: VolumeHandle | None,
        *,
        started: bool,
        terminal: bool,
    ) -> BrokerError | None:
        first_error: BrokerError | None = None
        if container is not None:
            if started and not terminal:
                try:
                    await self._backend.kill(container, TerminationReason.SHUTDOWN)
                except RuntimeBackendError as error:
                    first_error = BrokerError.from_exception(error)
            try:
                await self._backend.remove_container(container)
            except RuntimeBackendError as error:
                if first_error is None:
                    first_error = BrokerError.from_exception(error)
        if volume is not None:
            try:
                await self._backend.remove_volume(volume)
            except RuntimeBackendError as error:
                if first_error is None:
                    first_error = BrokerError.from_exception(error)
        return first_error

    async def execute(self, request: BrokerRequest) -> BrokerOutcome:
        if not isinstance(request, BrokerRequest):
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.VALIDATE,
                detail="broker-request-required",
            )

        events: list[BrokerEvent] = []
        result: RunResult | None = None
        artifacts: tuple[ArtifactRecord, ...] = ()
        primary_error: BrokerError | None = None
        cleanup_error: BrokerError | None = None
        volume: VolumeHandle | None = None
        container: ContainerHandle | None = None
        started = False
        terminal = False

        self._event(events, BrokerState.VALIDATING, RuntimePhase.VALIDATE)
        try:
            probe = await self._backend.probe()
            if probe.health is not RuntimeHealth.AVAILABLE or probe.capabilities is None:
                raise RuntimeBackendError(
                    ErrorCode.RUNTIME_UNAVAILABLE,
                    RuntimePhase.PROBE,
                    retry=RetryDisposition.INFRASTRUCTURE,
                    backend=self._backend.name.value,
                )
            validated_spec = self._policy.validate(request.spec, probe.capabilities)
            validated_archive = validate_canonical_input_archive(
                request.input_archive,
                request.spec.input_manifest,
                self._archive_limits,
            )

            self._event(events, BrokerState.PREPARING, RuntimePhase.IMAGE)
            await self._backend.ensure_image(request.spec.image)
            volume = await self._backend.create_volume(request.spec.job_id)
            await self._backend.stage_inputs(volume, validated_spec, validated_archive)
            container = await self._backend.create_container(validated_spec, volume)
            await self._backend.start(container)
            started = True

            self._event(events, BrokerState.RUNNING, RuntimePhase.WAIT)
            result = await self._backend.wait(container)
            terminal = True
            if result.classification is TerminalClassification.SUCCEEDED:
                self._event(events, BrokerState.COLLECTING, RuntimePhase.ARTIFACT)
                artifacts = await self._backend.collect_artifacts(container)
        except RuntimeBackendError as error:
            primary_error = BrokerError.from_exception(error)
        finally:
            self._event(events, BrokerState.CLEANING, RuntimePhase.CLEANUP)
            cleanup_error = await self._cleanup(
                container,
                volume,
                started=started,
                terminal=terminal,
            )
            if cleanup_error is None and (container is not None or volume is not None):
                try:
                    remaining = await self._backend.list_managed(request.spec.job_id)
                    if remaining.containers or remaining.volumes:
                        cleanup_error = BrokerError(
                            ErrorCode.CLEANUP_FAILED,
                            RuntimePhase.CLEANUP,
                            RetryDisposition.INFRASTRUCTURE,
                            self._backend.name.value,
                        )
                except RuntimeBackendError as error:
                    cleanup_error = BrokerError.from_exception(error)

        succeeded = (
            result is not None
            and result.classification is TerminalClassification.SUCCEEDED
            and primary_error is None
            and cleanup_error is None
        )
        state = BrokerState.SUCCEEDED if succeeded else BrokerState.FAILED
        final_error = primary_error or cleanup_error
        final_phase = (
            cleanup_error.phase
            if cleanup_error is not None
            else primary_error.phase
            if primary_error is not None
            else RuntimePhase.WAIT
        )
        self._event(
            events,
            state,
            final_phase,
            final_error.code if final_error is not None else None,
        )
        return BrokerOutcome(
            job_id=request.spec.job_id,
            state=state,
            result=result,
            artifacts=artifacts,
            error=primary_error,
            cleanup_error=cleanup_error,
            cleanup_complete=cleanup_error is None,
            events=tuple(events),
        )

    async def reconcile(self, job_id: str | None = None) -> ReconciliationReport:
        managed = await self._backend.list_managed(job_id)
        errors: list[BrokerError] = []
        containers_removed = 0
        volumes_removed = 0

        for container in managed.containers:
            try:
                await self._backend.remove_container(container)
            except RuntimeBackendError as error:
                if error.code is not ErrorCode.INVALID_STATE:
                    errors.append(BrokerError.from_exception(error))
                    continue
                try:
                    await self._backend.kill(container, TerminationReason.SHUTDOWN)
                    await self._backend.remove_container(container)
                except RuntimeBackendError as retry_error:
                    errors.append(BrokerError.from_exception(retry_error))
                    continue
            containers_removed += 1

        for volume in managed.volumes:
            try:
                await self._backend.remove_volume(volume)
            except RuntimeBackendError as error:
                errors.append(BrokerError.from_exception(error))
                continue
            volumes_removed += 1

        remaining = await self._backend.list_managed(job_id)
        return ReconciliationReport(
            containers_found=len(managed.containers),
            containers_removed=containers_removed,
            volumes_found=len(managed.volumes),
            volumes_removed=volumes_removed,
            remaining_containers=len(remaining.containers),
            remaining_volumes=len(remaining.volumes),
            errors=tuple(errors),
        )
