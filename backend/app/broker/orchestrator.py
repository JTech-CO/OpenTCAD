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
from .cleanup import JobCleanupCoordinator
from .diagnostics import InternalDiagnostic
from .lifecycle import CancellationSignal, LifecycleCheckpoint
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


class _ExecutionCancelled(Exception):
    def __init__(self, checkpoint: LifecycleCheckpoint) -> None:
        self.checkpoint = checkpoint
        super().__init__(checkpoint.value)


class SandboxBroker:
    """Internal library only. It exposes no network service or runtime socket."""

    def __init__(
        self,
        backend: RuntimeBackend,
        policy: SandboxPolicy,
        archive_limits: ArchiveLimits,
        diagnostic_sink: DiagnosticSink | None = None,
        cleanup_coordinator: JobCleanupCoordinator | None = None,
    ) -> None:
        if not isinstance(backend, RuntimeBackend):
            raise TypeError("SandboxBroker requires RuntimeBackend.")
        if not isinstance(policy, SandboxPolicy):
            raise TypeError("SandboxBroker requires SandboxPolicy.")
        if not isinstance(archive_limits, ArchiveLimits):
            raise TypeError("SandboxBroker requires ArchiveLimits.")
        if diagnostic_sink is not None and not callable(diagnostic_sink):
            raise TypeError("SandboxBroker diagnostic sink must be callable.")
        if cleanup_coordinator is not None and not isinstance(
            cleanup_coordinator,
            JobCleanupCoordinator,
        ):
            raise TypeError("SandboxBroker cleanup coordinator has the wrong type.")
        self._backend = backend
        self._policy = policy
        self._archive_limits = archive_limits
        self._diagnostic_sink = diagnostic_sink
        self._cleanup_coordinator = cleanup_coordinator or JobCleanupCoordinator()

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

    @staticmethod
    def _validate_cancellation_signal(
        identity: JobIdentity,
        cancellation: CancellationSignal | None,
    ) -> None:
        if cancellation is None:
            return
        if not isinstance(cancellation, CancellationSignal):
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.VALIDATE,
                detail="cancellation-signal-required",
            )
        if cancellation.identity != identity:
            raise RuntimeBackendError(
                ErrorCode.IDENTITY_MISMATCH,
                RuntimePhase.VALIDATE,
                detail="cancellation-signal-job-identity-mismatch",
            )

    @staticmethod
    def _checkpoint(
        cancellation: CancellationSignal | None,
        checkpoint: LifecycleCheckpoint,
    ) -> None:
        if cancellation is None:
            return
        requested = cancellation.requested(checkpoint)
        if not isinstance(requested, bool):
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.VALIDATE,
                detail="cancellation-signal-must-return-boolean",
            )
        if requested:
            raise _ExecutionCancelled(checkpoint)

    async def _cleanup_unlocked(
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
                    if error.code is not ErrorCode.CONTAINER_NOT_FOUND:
                        first_error = self._capture_error(identity, error)
            try:
                await self._backend.remove_container(container)
            except RuntimeBackendError as error:
                if error.code is not ErrorCode.CONTAINER_NOT_FOUND:
                    captured = self._capture_error(identity, error)
                    if first_error is None:
                        first_error = captured
        if volume is not None:
            try:
                await self._backend.remove_volume(volume)
            except RuntimeBackendError as error:
                if error.code is not ErrorCode.VOLUME_NOT_FOUND:
                    captured = self._capture_error(identity, error)
                    if first_error is None:
                        first_error = captured
        return first_error

    async def _verify_no_managed(self, identity: JobIdentity) -> BrokerError | None:
        try:
            remaining = await self._backend.list_managed(identity.job_id)
            handles = (*remaining.containers, *remaining.volumes)
            if any(handle.job_id != identity.job_id for handle in handles):
                return BrokerError(
                    ErrorCode.IDENTITY_MISMATCH,
                    RuntimePhase.QUERY,
                    RetryDisposition.INFRASTRUCTURE,
                    self._backend.name.value,
                )
            if remaining.containers or remaining.volumes:
                return BrokerError(
                    ErrorCode.CLEANUP_FAILED,
                    RuntimePhase.CLEANUP,
                    RetryDisposition.INFRASTRUCTURE,
                    self._backend.name.value,
                )
        except RuntimeBackendError as error:
            return self._capture_error(identity, error)
        return None

    async def _cleanup(
        self,
        identity: JobIdentity,
        container: ContainerHandle | None,
        volume: VolumeHandle | None,
        *,
        started: bool,
        terminal: bool,
    ) -> BrokerError | None:
        async with self._cleanup_coordinator.lease(identity):
            first_error = await self._cleanup_unlocked(
                identity,
                container,
                volume,
                started=started,
                terminal=terminal,
            )
            verification_error = await self._verify_no_managed(identity)
            return first_error or verification_error

    async def execute(
        self,
        request: BrokerRequest,
        cancellation: CancellationSignal | None = None,
    ) -> BrokerOutcome:
        if not isinstance(request, BrokerRequest):
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.VALIDATE,
                detail="broker-request-required",
            )

        identity = JobIdentity(request.spec.job_id)
        self._validate_cancellation_signal(identity, cancellation)
        events: list[BrokerEvent] = []
        result: RunResult | None = None
        artifacts: tuple[ArtifactRecord, ...] = ()
        artifact_archive: ValidatedArtifactArchive | None = None
        primary_error: BrokerError | None = None
        cleanup_error: BrokerError | None = None
        cancellation_checkpoint: LifecycleCheckpoint | None = None
        volume: VolumeHandle | None = None
        container: ContainerHandle | None = None
        started = False
        terminal = False

        self._event(events, BrokerState.VALIDATING, RuntimePhase.VALIDATE)
        try:
            self._checkpoint(cancellation, LifecycleCheckpoint.PROBE)
            probe = await self._backend.probe()
            if probe.health is not RuntimeHealth.AVAILABLE or probe.capabilities is None:
                raise RuntimeBackendError(
                    ErrorCode.RUNTIME_UNAVAILABLE,
                    RuntimePhase.PROBE,
                    retry=RetryDisposition.INFRASTRUCTURE,
                    backend=self._backend.name.value,
                )
            self._checkpoint(cancellation, LifecycleCheckpoint.POLICY)
            validated_spec = self._policy.validate(request.spec, probe.capabilities)
            if validated_spec.identity != identity:
                raise RuntimeBackendError(
                    ErrorCode.IDENTITY_MISMATCH,
                    RuntimePhase.VALIDATE,
                    backend=self._backend.name.value,
                    detail="policy-job-identity-mismatch",
                )
            self._checkpoint(cancellation, LifecycleCheckpoint.INPUT_ARCHIVE)
            validated_archive = validate_canonical_input_archive(
                request.input_archive,
                request.spec.input_manifest,
                self._archive_limits,
            )

            self._event(events, BrokerState.PREPARING, RuntimePhase.IMAGE)
            self._checkpoint(cancellation, LifecycleCheckpoint.IMAGE)
            await self._backend.ensure_image(request.spec.image)
            self._checkpoint(cancellation, LifecycleCheckpoint.VOLUME)
            volume = await self._backend.create_volume(validated_spec.identity)
            self._checkpoint(cancellation, LifecycleCheckpoint.INPUT_STAGE)
            await self._backend.stage_inputs(volume, validated_spec, validated_archive)
            self._checkpoint(cancellation, LifecycleCheckpoint.CONTAINER_CREATE)
            container = await self._backend.create_container(validated_spec, volume)
            self._checkpoint(cancellation, LifecycleCheckpoint.START)
            await self._backend.start(container)
            started = True

            self._event(events, BrokerState.RUNNING, RuntimePhase.WAIT)
            self._checkpoint(cancellation, LifecycleCheckpoint.WAIT)
            result = await self._backend.wait(container)
            terminal = True
            if result.classification is TerminalClassification.SUCCEEDED:
                self._event(events, BrokerState.COLLECTING, RuntimePhase.ARTIFACT)
                self._checkpoint(cancellation, LifecycleCheckpoint.ARTIFACT_COLLECTION)
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
            self._checkpoint(cancellation, LifecycleCheckpoint.CLEANUP)
        except _ExecutionCancelled as interruption:
            cancellation_checkpoint = interruption.checkpoint
            artifacts = ()
            artifact_archive = None
            self._event(events, BrokerState.CANCELLING, interruption.checkpoint.phase)
            if started and not terminal and container is not None:
                try:
                    result = await self._backend.kill(
                        container,
                        TerminationReason.CANCELLATION,
                    )
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
            else:
                result = None
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

        succeeded = (
            result is not None
            and result.classification is TerminalClassification.SUCCEEDED
            and artifact_archive is not None
            and primary_error is None
            and cleanup_error is None
            and cancellation_checkpoint is None
        )
        cancelled = (
            cancellation_checkpoint is not None
            and primary_error is None
            and cleanup_error is None
        )
        state = (
            BrokerState.SUCCEEDED
            if succeeded
            else BrokerState.CANCELLED
            if cancelled
            else BrokerState.FAILED
        )
        final_error = primary_error or cleanup_error
        final_phase = (
            final_error.phase
            if final_error is not None
            else cancellation_checkpoint.phase
            if cancellation_checkpoint is not None
            else RuntimePhase.WAIT
        )
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
            cancellation_checkpoint=cancellation_checkpoint,
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
        async with self._cleanup_coordinator.lease(identity):
            return await self._cancel_locked(identity)

    async def _cancel_locked(self, identity: JobIdentity) -> CancellationOutcome:
        events: list[BrokerEvent] = []
        result: RunResult | None = None
        primary_error: BrokerError | None = None
        cleanup_error: BrokerError | None = None
        container: ContainerHandle | None = None
        volume: VolumeHandle | None = None
        terminal = False

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
            first_cleanup_error = await self._cleanup_unlocked(
                identity,
                container,
                volume,
                started=container is not None,
                terminal=terminal,
            )
            verification_error = await self._verify_no_managed(identity)
            cleanup_error = first_cleanup_error or verification_error

        cancelled = (
            result is not None
            and result.classification is TerminalClassification.CANCELLED
            and primary_error is None
            and cleanup_error is None
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
            cleanup_complete=cleanup_error is None,
            events=tuple(events),
        )

    async def _reconcile_locked(self, identity: JobIdentity) -> ReconciliationReport:
        managed = await self._backend.list_managed(identity.job_id)
        errors: list[BrokerError] = []
        containers_removed = 0
        volumes_removed = 0
        handles = (*managed.containers, *managed.volumes)
        if any(handle.job_id != identity.job_id for handle in handles):
            errors.append(
                BrokerError(
                    ErrorCode.IDENTITY_MISMATCH,
                    RuntimePhase.QUERY,
                    RetryDisposition.INFRASTRUCTURE,
                    self._backend.name.value,
                ),
            )
        else:
            for container in managed.containers:
                try:
                    await self._backend.remove_container(container)
                except RuntimeBackendError as error:
                    if error.code is ErrorCode.CONTAINER_NOT_FOUND:
                        containers_removed += 1
                        continue
                    if error.code is not ErrorCode.INVALID_STATE:
                        errors.append(self._capture_error(identity, error))
                        continue
                    try:
                        await self._backend.kill(container, TerminationReason.SHUTDOWN)
                    except RuntimeBackendError as kill_error:
                        if kill_error.code is ErrorCode.CONTAINER_NOT_FOUND:
                            containers_removed += 1
                            continue
                        errors.append(self._capture_error(identity, kill_error))
                        continue
                    try:
                        await self._backend.remove_container(container)
                    except RuntimeBackendError as retry_error:
                        if retry_error.code is not ErrorCode.CONTAINER_NOT_FOUND:
                            errors.append(self._capture_error(identity, retry_error))
                            continue
                containers_removed += 1

            for volume in managed.volumes:
                try:
                    await self._backend.remove_volume(volume)
                except RuntimeBackendError as error:
                    if error.code is not ErrorCode.VOLUME_NOT_FOUND:
                        errors.append(self._capture_error(identity, error))
                        continue
                volumes_removed += 1

        remaining = await self._backend.list_managed(identity.job_id)
        return ReconciliationReport(
            containers_found=len(managed.containers),
            containers_removed=containers_removed,
            volumes_found=len(managed.volumes),
            volumes_removed=volumes_removed,
            remaining_containers=len(remaining.containers),
            remaining_volumes=len(remaining.volumes),
            errors=tuple(errors),
        )

    async def reconcile(self, job_id: str | None = None) -> ReconciliationReport:
        if job_id is not None:
            identity = JobIdentity(job_id)
            async with self._cleanup_coordinator.lease(identity):
                return await self._reconcile_locked(identity)

        managed = await self._backend.list_managed()
        job_ids = sorted(
            {handle.job_id for handle in (*managed.containers, *managed.volumes)},
        )
        reports: list[ReconciliationReport] = []
        for managed_job_id in job_ids:
            identity = JobIdentity(managed_job_id)
            async with self._cleanup_coordinator.lease(identity):
                reports.append(await self._reconcile_locked(identity))
        remaining = await self._backend.list_managed()
        return ReconciliationReport(
            containers_found=sum(report.containers_found for report in reports),
            containers_removed=sum(report.containers_removed for report in reports),
            volumes_found=sum(report.volumes_found for report in reports),
            volumes_removed=sum(report.volumes_removed for report in reports),
            remaining_containers=len(remaining.containers),
            remaining_volumes=len(remaining.volumes),
            errors=tuple(error for report in reports for error in report.errors),
        )
