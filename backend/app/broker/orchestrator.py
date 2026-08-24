"""Mock-testable broker execution, cancellation, and cleanup orchestration."""

from __future__ import annotations

from collections.abc import Callable

from backend.app.runtime.errors import (
    ErrorCode,
    RetryDisposition,
    RuntimeBackendError,
    RuntimePhase,
)
from backend.app.runtime.models import (
    ArtifactRecord,
    ContainerHandle,
    JobIdentity,
    RunResult,
    RuntimeHealth,
    TerminalClassification,
    TerminationReason,
    ValidatedArtifactArchive,
    VolumeHandle,
)
from backend.app.runtime.policy import SandboxPolicy
from backend.app.runtime.protocol import RuntimeBackend

from .archive import ArchiveLimits, validate_canonical_input_archive
from .cancellation import CancellationOutcome, CancellationRequest
from .diagnostics import InternalDiagnostic
from .models import (
    BrokerError,
    BrokerEvent,
    BrokerOutcome,
    BrokerRequest,
    BrokerState,
    ReconciliationReport,
)
from .output_archive import output_archive_limits, validate_canonical_output_archive


DiagnosticSink = Callable[[InternalDiagnostic], None]


class SandboxBroker:
    """Internal library only. It exposes no network service or runtime socket."""

    def __init__(
        self,
        backend: RuntimeBackend,
        policy: SandboxPolicy,
        archive_limits: ArchiveLimits,
        diagnostic_sink: DiagnosticSink | None = None,
    ) -> None:
        if not isinstance(backend, RuntimeBackend):
            raise TypeError("SandboxBroker requires RuntimeBackend.")
        if not isinstance(policy, SandboxPolicy):
            raise TypeError("SandboxBroker requires SandboxPolicy.")
        if not isinstance(archive_limits, ArchiveLimits):
            raise TypeError("SandboxBroker requires ArchiveLimits.")
        if diagnostic_sink is not None and not callable(diagnostic_sink):
            raise TypeError("SandboxBroker diagnostic sink must be callable.")
        self._backend = backend
        self._policy = policy
        self._archive_limits = archive_limits
        self._diagnostic_sink = diagnostic_sink

    @staticmethod
    def _event(
        events: list[BrokerEvent],
        state: BrokerState,
        phase: RuntimePhase,
        error: BrokerError | None = None,
    ) -> None:
        events.append(
            BrokerEvent(
                len(events) + 1,
                state,
                phase,
                error.code if error is not None else None,
            ),
        )

    def _capture_error(
        self,
        identity: JobIdentity,
        error: RuntimeBackendError,
    ) -> BrokerError:
        diagnostic = InternalDiagnostic.from_exception(identity, error)
        if self._diagnostic_sink is not None:
            self._diagnostic_sink(diagnostic)
        return diagnostic.public_error

    async def _cleanup(
        self,
        identity: JobIdentity,
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
                    first_error = self._capture_error(identity, error)
            try:
                await self._backend.remove_container(container)
            except RuntimeBackendError as error:
                captured = self._capture_error(identity, error)
                if first_error is None:
                    first_error = captured
        if volume is not None:
            try:
                await self._backend.remove_volume(volume)
            except RuntimeBackendError as error:
                captured = self._capture_error(identity, error)
                if first_error is None:
                    first_error = captured
        return first_error

    async def execute(self, request: BrokerRequest) -> BrokerOutcome:
        if not isinstance(request, BrokerRequest):
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.VALIDATE,
                detail="broker-request-required",
            )

        identity = JobIdentity(request.spec.job_id)
        events: list[BrokerEvent] = []
        result: RunResult | None = None
        artifacts: tuple[ArtifactRecord, ...] = ()
        artifact_archive: ValidatedArtifactArchive | None = None
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
            if validated_spec.identity != identity:
                raise RuntimeBackendError(
                    ErrorCode.IDENTITY_MISMATCH,
                    RuntimePhase.VALIDATE,
                    backend=self._backend.name.value,
                    detail="policy-job-identity-mismatch",
                )
            validated_archive = validate_canonical_input_archive(
                request.input_archive,
                request.spec.input_manifest,
                self._archive_limits,
            )

            self._event(events, BrokerState.PREPARING, RuntimePhase.IMAGE)
            await self._backend.ensure_image(request.spec.image)
            volume = await self._backend.create_volume(validated_spec.identity)
            await self._backend.stage_inputs(volume, validated_spec, validated_archive)
            container = await self._backend.create_container(validated_spec, volume)
            await self._backend.start(container)
            started = True

            self._event(events, BrokerState.RUNNING, RuntimePhase.WAIT)
            result = await self._backend.wait(container)
            terminal = True
            if result.classification is TerminalClassification.SUCCEEDED:
                self._event(events, BrokerState.COLLECTING, RuntimePhase.ARTIFACT)
                raw_archive = await self._backend.collect_artifacts(container)
                limits = output_archive_limits(
                    request.spec.limits.artifact_bytes,
                    request.spec.limits.file_count,
                )
                artifact_archive = validate_canonical_output_archive(
                    raw_archive,
                    request.spec.expected_outputs,
                    result.artifacts,
                    limits,
                )
                artifacts = artifact_archive.manifest
        except RuntimeBackendError as error:
            primary_error = self._capture_error(identity, error)
        finally:
            self._event(events, BrokerState.CLEANING, RuntimePhase.CLEANUP)
            cleanup_error = await self._cleanup(
                identity,
                container,
                volume,
                started=started,
                terminal=terminal,
            )
            if cleanup_error is None and (container is not None or volume is not None):
                try:
                    remaining = await self._backend.list_managed(identity.job_id)
                    if remaining.containers or remaining.volumes:
                        cleanup_error = BrokerError(
                            ErrorCode.CLEANUP_FAILED,
                            RuntimePhase.CLEANUP,
                            RetryDisposition.INFRASTRUCTURE,
                            self._backend.name.value,
                        )
                except RuntimeBackendError as error:
                    cleanup_error = self._capture_error(identity, error)

        succeeded = (
            result is not None
            and result.classification is TerminalClassification.SUCCEEDED
            and artifact_archive is not None
            and primary_error is None
            and cleanup_error is None
        )
        state = BrokerState.SUCCEEDED if succeeded else BrokerState.FAILED
        final_error = primary_error or cleanup_error
        final_phase = final_error.phase if final_error is not None else RuntimePhase.WAIT
        self._event(events, state, final_phase, final_error)
        return BrokerOutcome(
            job_id=identity.job_id,
            state=state,
            result=result,
            artifacts=artifacts,
            artifact_archive=artifact_archive,
            error=primary_error,
            cleanup_error=cleanup_error,
            cleanup_complete=cleanup_error is None,
            events=tuple(events),
        )

    async def cancel(self, request: CancellationRequest) -> CancellationOutcome:
        if not isinstance(request, CancellationRequest):
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.VALIDATE,
                detail="cancellation-request-required",
            )
        identity = request.identity
        events: list[BrokerEvent] = []
        result: RunResult | None = None
        primary_error: BrokerError | None = None
        cleanup_error: BrokerError | None = None
        container: ContainerHandle | None = None
        volume: VolumeHandle | None = None
        terminal = False
        cleanup_verified = False

        self._event(events, BrokerState.VALIDATING, RuntimePhase.QUERY)
        try:
            managed = await self._backend.list_managed(identity.job_id)
            handles = (*managed.containers, *managed.volumes)
            if any(handle.job_id != identity.job_id for handle in handles):
                raise RuntimeBackendError(
                    ErrorCode.IDENTITY_MISMATCH,
                    RuntimePhase.QUERY,
                    backend=self._backend.name.value,
                    detail="cancellation-filter-returned-cross-job-handle",
                )
            if not managed.containers:
                cleanup_verified = not managed.volumes
                raise RuntimeBackendError(
                    ErrorCode.CONTAINER_NOT_FOUND,
                    RuntimePhase.KILL,
                    backend=self._backend.name.value,
                )
            if len(managed.containers) != 1 or len(managed.volumes) > 1:
                raise RuntimeBackendError(
                    ErrorCode.STALE_STATE,
                    RuntimePhase.QUERY,
                    retry=RetryDisposition.INFRASTRUCTURE,
                    backend=self._backend.name.value,
                    detail="cancellation-requires-exact-job-objects",
                )
            container = managed.containers[0]
            volume = managed.volumes[0] if managed.volumes else None
            self._event(events, BrokerState.CANCELLING, RuntimePhase.KILL)
            result = await self._backend.kill(container, TerminationReason.CANCELLATION)
            terminal = True
            if result.classification is not TerminalClassification.CANCELLED:
                raise RuntimeBackendError(
                    ErrorCode.CANCELLATION_REJECTED,
                    RuntimePhase.KILL,
                    backend=self._backend.name.value,
                    detail="runtime-returned-noncancelled-result",
                )
        except RuntimeBackendError as error:
            primary_error = self._capture_error(identity, error)
        finally:
            self._event(events, BrokerState.CLEANING, RuntimePhase.CLEANUP)
            cleanup_error = await self._cleanup(
                identity,
                container,
                volume,
                started=container is not None,
                terminal=terminal,
            )
            if cleanup_error is None and (container is not None or volume is not None):
                try:
                    remaining = await self._backend.list_managed(identity.job_id)
                    if remaining.containers or remaining.volumes:
                        cleanup_error = BrokerError(
                            ErrorCode.CLEANUP_FAILED,
                            RuntimePhase.CLEANUP,
                            RetryDisposition.INFRASTRUCTURE,
                            self._backend.name.value,
                        )
                    else:
                        cleanup_verified = True
                except RuntimeBackendError as error:
                    cleanup_error = self._capture_error(identity, error)

        cancelled = (
            result is not None
            and result.classification is TerminalClassification.CANCELLED
            and primary_error is None
            and cleanup_error is None
            and cleanup_verified
        )
        state = BrokerState.CANCELLED if cancelled else BrokerState.FAILED
        final_error = primary_error or cleanup_error
        final_phase = final_error.phase if final_error is not None else RuntimePhase.KILL
        self._event(events, state, final_phase, final_error)
        return CancellationOutcome(
            identity=identity,
            state=state,
            result=result,
            error=primary_error,
            cleanup_error=cleanup_error,
            cleanup_complete=cleanup_verified and cleanup_error is None,
            events=tuple(events),
        )

    async def reconcile(self, job_id: str | None = None) -> ReconciliationReport:
        managed = await self._backend.list_managed(job_id)
        errors: list[BrokerError] = []
        containers_removed = 0
        volumes_removed = 0

        for container in managed.containers:
            identity = JobIdentity(container.job_id)
            try:
                await self._backend.remove_container(container)
            except RuntimeBackendError as error:
                if error.code is not ErrorCode.INVALID_STATE:
                    errors.append(self._capture_error(identity, error))
                    continue
                try:
                    await self._backend.kill(container, TerminationReason.SHUTDOWN)
                    await self._backend.remove_container(container)
                except RuntimeBackendError as retry_error:
                    errors.append(self._capture_error(identity, retry_error))
                    continue
            containers_removed += 1

        for volume in managed.volumes:
            identity = JobIdentity(volume.job_id)
            try:
                await self._backend.remove_volume(volume)
            except RuntimeBackendError as error:
                errors.append(self._capture_error(identity, error))
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
