"""Mock-testable broker execution, cancellation, and cleanup orchestration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from backend.app.runtime.errors import (
    ErrorCode,
    RetryDisposition,
    RuntimeBackendError,
    RuntimePhase,
)
from backend.app.runtime.fencing import RuntimeFencingContext
from backend.app.runtime.models import (
    ArtifactRecord,
    ContainerHandle,
    JobIdentity,
    RunResult,
    RuntimeHealth,
    RuntimeKind,
    TerminalClassification,
    TerminationReason,
    ValidatedArtifactArchive,
    VolumeHandle,
)
from backend.app.runtime.policy import SandboxPolicy
from backend.app.runtime.protocol import RuntimeBackend, RuntimeJobBackend

from .archive import ArchiveLimits, validate_canonical_input_archive
from .cancellation import CancellationOutcome, CancellationRequest
from .cancellation_arbitration import (
    DurableCancellationCheckpoint,
    DurableCancellationCrashSignal,
    cancellation_checkpoint,
)
from .cleanup import JobCleanupCoordinator
from .diagnostics import InternalDiagnostic
from .lifecycle import CancellationSignal, LifecycleCheckpoint
from .live_state import LiveStateEmission, LiveStateSession, LiveStateWriteError
from .models import (
    BrokerError,
    BrokerEvent,
    BrokerOutcome,
    BrokerRequest,
    BrokerState,
    ReconciliationReport,
)
from .output_archive import output_archive_limits, validate_canonical_output_archive
from .state import (
    OperationOwnershipError,
    OperationOwnershipGuard,
    StateStoreErrorCode,
)


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

    @property
    def runtime_kind(self) -> RuntimeKind:
        return self._backend.name

    @staticmethod
    async def _event(
        events: list[BrokerEvent],
        state: BrokerState,
        phase: RuntimePhase,
        error: BrokerError | None = None,
        *,
        state_session: LiveStateSession | None = None,
        durable_state: BrokerState | None = None,
        durable_phase: RuntimePhase | None = None,
        durable_error: BrokerError | None = None,
        classification: TerminalClassification | None = None,
        cleanup_complete: bool = False,
    ) -> None:
        source = BrokerEvent(
            len(events) + 1,
            state,
            phase,
            error.code if error is not None else None,
        )
        events.append(source)
        if state_session is None:
            return
        persisted_state = durable_state or state
        await state_session.record(
            LiveStateEmission(
                source,
                persisted_state,
                durable_phase or phase,
                durable_error if durable_state is not None else error,
                classification,
                cleanup_complete,
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
    def _is_fenced_store_code(code: StateStoreErrorCode) -> bool:
        return code in {
            StateStoreErrorCode.OWNERSHIP_CONFLICT,
            StateStoreErrorCode.REVISION_CONFLICT,
            StateStoreErrorCode.EVENT_CONFLICT,
            StateStoreErrorCode.LEASE_EXPIRED,
        }

    def _capture_state_write_error(
        self,
        error: LiveStateWriteError,
    ) -> BrokerError:
        return BrokerError(
            ErrorCode.OPERATION_FENCED
            if self._is_fenced_store_code(error.code)
            else ErrorCode.INVALID_STATE,
            error.phase,
            RetryDisposition.INFRASTRUCTURE,
            self._backend.name.value,
        )

    def _capture_ownership_error(
        self,
        error: OperationOwnershipError,
    ) -> BrokerError:
        return BrokerError(
            ErrorCode.OPERATION_FENCED
            if self._is_fenced_store_code(error.code)
            else ErrorCode.INVALID_STATE,
            error.phase,
            RetryDisposition.INFRASTRUCTURE,
            self._backend.name.value,
        )

    def _fenced_cleanup_error(self) -> BrokerError:
        return BrokerError(
            ErrorCode.OPERATION_FENCED,
            RuntimePhase.CLEANUP,
            RetryDisposition.INFRASTRUCTURE,
            self._backend.name.value,
        )

    @staticmethod
    async def _assert_owned(
        guard: OperationOwnershipGuard | None,
        phase: RuntimePhase,
    ) -> None:
        if guard is not None:
            await guard.assert_owned(phase)

    @staticmethod
    async def _run_owned(
        guard: OperationOwnershipGuard | None,
        phase: RuntimePhase,
        operation: Callable[[], Awaitable[Any]],
    ) -> Any:
        if guard is None:
            return await operation()
        return await guard.run_owned(phase, operation)

    @staticmethod
    def _runtime_fence(
        identity: JobIdentity,
        guard: OperationOwnershipGuard | None,
    ) -> RuntimeFencingContext:
        if guard is None:
            return RuntimeFencingContext(identity, identity.job_id, 1)
        fence = guard.runtime_fence
        if fence.identity != identity:
            raise RuntimeBackendError(
                ErrorCode.IDENTITY_MISMATCH,
                RuntimePhase.VALIDATE,
                detail="runtime-fence-job-identity-mismatch",
            )
        return fence

    def _job_runtime(
        self,
        identity: JobIdentity,
        guard: OperationOwnershipGuard | None,
    ) -> RuntimeJobBackend:
        runtime = self._backend.bind_job(self._runtime_fence(identity, guard))
        if not isinstance(runtime, RuntimeJobBackend):
            raise TypeError("Runtime backend returned an invalid job binding.")
        return runtime

    @staticmethod
    def _live_classification(
        result: RunResult | None,
        cancellation_checkpoint: LifecycleCheckpoint | None,
        primary_error: BrokerError | None,
    ) -> TerminalClassification | None:
        if cancellation_checkpoint is not None and primary_error is None:
            return TerminalClassification.CANCELLED
        return result.classification if result is not None else None

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
        ownership_guard: OperationOwnershipGuard | None = None,
    ) -> BrokerError | None:
        first_error: BrokerError | None = None
        runtime = self._job_runtime(identity, ownership_guard)
        if container is not None:
            if started and not terminal:
                try:
                    await self._run_owned(
                        ownership_guard,
                        RuntimePhase.KILL,
                        lambda: runtime.kill(container, TerminationReason.SHUTDOWN),
                    )
                except RuntimeBackendError as error:
                    if error.code is not ErrorCode.CONTAINER_NOT_FOUND:
                        first_error = self._capture_error(identity, error)
            try:
                await self._run_owned(
                    ownership_guard,
                    RuntimePhase.CLEANUP,
                    lambda: runtime.remove_container(container),
                )
            except RuntimeBackendError as error:
                if error.code is not ErrorCode.CONTAINER_NOT_FOUND:
                    captured = self._capture_error(identity, error)
                    if first_error is None:
                        first_error = captured
        if volume is not None:
            try:
                await self._run_owned(
                    ownership_guard,
                    RuntimePhase.CLEANUP,
                    lambda: runtime.remove_volume(volume),
                )
            except RuntimeBackendError as error:
                if error.code is not ErrorCode.VOLUME_NOT_FOUND:
                    captured = self._capture_error(identity, error)
                    if first_error is None:
                        first_error = captured
        return first_error

    async def _verify_no_managed(
        self,
        identity: JobIdentity,
        ownership_guard: OperationOwnershipGuard | None = None,
    ) -> BrokerError | None:
        try:
            runtime = self._job_runtime(identity, ownership_guard)
            remaining = await self._run_owned(
                ownership_guard,
                RuntimePhase.QUERY,
                runtime.list_managed,
            )
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
        ownership_guard: OperationOwnershipGuard | None = None,
    ) -> BrokerError | None:
        async with self._cleanup_coordinator.lease(identity):
            try:
                first_error = await self._cleanup_unlocked(
                    identity,
                    container,
                    volume,
                    started=started,
                    terminal=terminal,
                    ownership_guard=ownership_guard,
                )
                verification_error = await self._verify_no_managed(
                    identity,
                    ownership_guard,
                )
                return first_error or verification_error
            except OperationOwnershipError as error:
                return self._capture_ownership_error(error)

    async def execute(
        self,
        request: BrokerRequest,
        cancellation: CancellationSignal | None = None,
    ) -> BrokerOutcome:
        return await self._execute(request, cancellation, None)

    async def _execute_with_state_session(
        self,
        request: BrokerRequest,
        cancellation: CancellationSignal | None,
        state_session: LiveStateSession,
    ) -> BrokerOutcome:
        if not isinstance(state_session, LiveStateSession):
            raise TypeError("SandboxBroker state session has the wrong type.")
        return await self._execute(request, cancellation, state_session)

    async def _execute(
        self,
        request: BrokerRequest,
        cancellation: CancellationSignal | None,
        state_session: LiveStateSession | None,
    ) -> BrokerOutcome:
        if not isinstance(request, BrokerRequest):
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.VALIDATE,
                detail="broker-request-required",
            )

        identity = JobIdentity(request.spec.job_id)
        self._validate_cancellation_signal(identity, cancellation)
        if state_session is not None and (
            state_session.identity != identity
            or state_session.backend is not self._backend.name
        ):
            raise RuntimeBackendError(
                ErrorCode.IDENTITY_MISMATCH,
                RuntimePhase.VALIDATE,
                detail="state-session-context-mismatch",
            )
        runtime = self._job_runtime(identity, state_session)
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
        ownership_lost = False

        try:
            await self._event(
                events,
                BrokerState.VALIDATING,
                RuntimePhase.VALIDATE,
                state_session=state_session,
            )
            self._checkpoint(cancellation, LifecycleCheckpoint.PROBE)
            probe = await self._run_owned(
                state_session,
                RuntimePhase.PROBE,
                self._backend.probe,
            )
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

            await self._event(
                events,
                BrokerState.PREPARING,
                RuntimePhase.IMAGE,
                state_session=state_session,
            )
            self._checkpoint(cancellation, LifecycleCheckpoint.IMAGE)
            await self._run_owned(
                state_session,
                RuntimePhase.IMAGE,
                lambda: self._backend.ensure_image(request.spec.image),
            )
            self._checkpoint(cancellation, LifecycleCheckpoint.VOLUME)
            volume = await self._run_owned(
                state_session,
                RuntimePhase.VOLUME,
                runtime.create_volume,
            )
            self._checkpoint(cancellation, LifecycleCheckpoint.INPUT_STAGE)
            await self._run_owned(
                state_session,
                RuntimePhase.INPUT,
                lambda: runtime.stage_inputs(volume, validated_spec, validated_archive),
            )
            self._checkpoint(cancellation, LifecycleCheckpoint.CONTAINER_CREATE)
            container = await self._run_owned(
                state_session,
                RuntimePhase.CREATE,
                lambda: runtime.create_container(validated_spec, volume),
            )
            self._checkpoint(cancellation, LifecycleCheckpoint.START)
            await self._run_owned(
                state_session,
                RuntimePhase.START,
                lambda: runtime.start(container),
            )
            started = True

            await self._event(
                events,
                BrokerState.RUNNING,
                RuntimePhase.WAIT,
                state_session=state_session,
            )
            self._checkpoint(cancellation, LifecycleCheckpoint.WAIT)
            result = await self._run_owned(
                state_session,
                RuntimePhase.WAIT,
                lambda: runtime.wait(container),
            )
            terminal = True
            if result.classification is TerminalClassification.SUCCEEDED:
                await self._event(
                    events,
                    BrokerState.COLLECTING,
                    RuntimePhase.ARTIFACT,
                    state_session=state_session,
                    classification=result.classification,
                )
                self._checkpoint(cancellation, LifecycleCheckpoint.ARTIFACT_COLLECTION)
                raw_archive = await self._run_owned(
                    state_session,
                    RuntimePhase.ARTIFACT,
                    lambda: runtime.collect_artifacts(container),
                )
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
            try:
                await self._event(
                    events,
                    BrokerState.CANCELLING,
                    interruption.checkpoint.phase,
                    state_session=state_session,
                )
                if started and not terminal and container is not None:
                    result = await self._run_owned(
                        state_session,
                        RuntimePhase.KILL,
                        lambda: runtime.kill(
                            container,
                            TerminationReason.CANCELLATION,
                        ),
                    )
                    terminal = True
                    if result.classification is not TerminalClassification.CANCELLED:
                        raise RuntimeBackendError(
                            ErrorCode.CANCELLATION_REJECTED,
                            RuntimePhase.KILL,
                            backend=self._backend.name.value,
                            detail="runtime-returned-noncancelled-result",
                        )
                else:
                    result = None
            except LiveStateWriteError as error:
                primary_error = self._capture_state_write_error(error)
                ownership_lost = self._is_fenced_store_code(error.code)
            except OperationOwnershipError as error:
                primary_error = self._capture_ownership_error(error)
                ownership_lost = self._is_fenced_store_code(error.code)
            except RuntimeBackendError as error:
                primary_error = self._capture_error(identity, error)
        except LiveStateWriteError as error:
            primary_error = self._capture_state_write_error(error)
            ownership_lost = self._is_fenced_store_code(error.code)
        except OperationOwnershipError as error:
            primary_error = self._capture_ownership_error(error)
            ownership_lost = self._is_fenced_store_code(error.code)
        except RuntimeBackendError as error:
            primary_error = self._capture_error(identity, error)
        finally:
            if ownership_lost:
                cleanup_error = self._fenced_cleanup_error()
            else:
                try:
                    await self._event(
                        events,
                        BrokerState.CLEANING,
                        RuntimePhase.CLEANUP,
                        state_session=state_session,
                        classification=self._live_classification(
                            result,
                            cancellation_checkpoint,
                            primary_error,
                        ),
                    )
                except LiveStateWriteError as error:
                    if primary_error is None:
                        primary_error = self._capture_state_write_error(error)
                    ownership_lost = self._is_fenced_store_code(error.code)
                if ownership_lost:
                    cleanup_error = self._fenced_cleanup_error()
                else:
                    cleanup_error = await self._cleanup(
                        identity,
                        container,
                        volume,
                        started=started,
                        terminal=terminal,
                        ownership_guard=(
                            state_session
                            if state_session is not None
                            and state_session.last_snapshot is not None
                            else None
                        ),
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
        classification = self._live_classification(
            result,
            cancellation_checkpoint,
            primary_error,
        )
        durable_state = BrokerState.CLEANING if cleanup_error is not None else None
        try:
            await self._event(
                events,
                state,
                final_phase,
                final_error,
                state_session=state_session,
                durable_state=durable_state,
                durable_phase=(
                    RuntimePhase.CLEANUP if durable_state is not None else None
                ),
                durable_error=cleanup_error,
                classification=classification,
                cleanup_complete=cleanup_error is None,
            )
        except LiveStateWriteError as error:
            if primary_error is None:
                primary_error = self._capture_state_write_error(error)
            state = BrokerState.FAILED
            artifacts = ()
            artifact_archive = None
            final_error = primary_error or cleanup_error
            final_phase = (
                final_error.phase if final_error is not None else RuntimePhase.WAIT
            )
            events.pop()
            await self._event(
                events,
                state,
                final_phase,
                final_error,
                state_session=state_session,
                classification=self._live_classification(
                    result,
                    cancellation_checkpoint,
                    primary_error,
                ),
                cleanup_complete=cleanup_error is None,
            )
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

    def _cancellation_lease(self, identity: JobIdentity):
        return self._cleanup_coordinator.lease(identity)

    async def cancel(self, request: CancellationRequest) -> CancellationOutcome:
        if not isinstance(request, CancellationRequest):
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.VALIDATE,
                detail="cancellation-request-required",
            )
        identity = request.identity
        async with self._cancellation_lease(identity):
            return await self._cancel_locked(identity, None, None, None)

    async def _cancel_with_state_session_locked(
        self,
        request: CancellationRequest,
        state_session: LiveStateSession,
        intent_event: BrokerEvent,
        crash_signal: DurableCancellationCrashSignal | None,
    ) -> CancellationOutcome:
        if not isinstance(request, CancellationRequest):
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.VALIDATE,
                detail="cancellation-request-required",
            )
        identity = request.identity
        if (
            not isinstance(state_session, LiveStateSession)
            or state_session.identity != identity
            or state_session.backend is not self._backend.name
            or state_session.failed
            or state_session.last_snapshot is None
            or state_session.last_snapshot.state is not BrokerState.CANCELLING
        ):
            raise RuntimeBackendError(
                ErrorCode.IDENTITY_MISMATCH,
                RuntimePhase.VALIDATE,
                detail="cancellation-state-session-context-mismatch",
            )
        if (
            not isinstance(intent_event, BrokerEvent)
            or intent_event.sequence != 1
            or intent_event.state is not BrokerState.CANCELLING
            or intent_event.phase is not RuntimePhase.QUERY
            or intent_event.code is not None
        ):
            raise RuntimeBackendError(
                ErrorCode.INVALID_SPEC,
                RuntimePhase.VALIDATE,
                detail="cancellation-intent-event-mismatch",
            )
        return await self._cancel_locked(
            identity,
            state_session,
            intent_event,
            crash_signal,
        )

    async def _cancel_locked(
        self,
        identity: JobIdentity,
        state_session: LiveStateSession | None,
        intent_event: BrokerEvent | None,
        crash_signal: DurableCancellationCrashSignal | None,
    ) -> CancellationOutcome:
        runtime = self._job_runtime(identity, state_session)
        events: list[BrokerEvent] = [] if intent_event is None else [intent_event]
        result: RunResult | None = None
        primary_error: BrokerError | None = None
        cleanup_error: BrokerError | None = None
        container: ContainerHandle | None = None
        volume: VolumeHandle | None = None
        terminal = False
        converged_without_runtime = False
        ownership_lost = False

        if intent_event is None:
            await self._event(events, BrokerState.VALIDATING, RuntimePhase.QUERY)
        try:
            managed = await self._run_owned(
                state_session,
                RuntimePhase.QUERY,
                runtime.list_managed,
            )
            handles = (*managed.containers, *managed.volumes)
            if any(handle.job_id != identity.job_id for handle in handles):
                raise RuntimeBackendError(
                    ErrorCode.IDENTITY_MISMATCH,
                    RuntimePhase.QUERY,
                    backend=self._backend.name.value,
                    detail="cancellation-filter-returned-cross-job-handle",
                )
            if len(managed.containers) > 1 or len(managed.volumes) > 1:
                raise RuntimeBackendError(
                    ErrorCode.STALE_STATE,
                    RuntimePhase.QUERY,
                    retry=RetryDisposition.INFRASTRUCTURE,
                    backend=self._backend.name.value,
                    detail="cancellation-requires-exact-job-objects",
                )
            if not managed.containers:
                if state_session is None:
                    raise RuntimeBackendError(
                        ErrorCode.CONTAINER_NOT_FOUND,
                        RuntimePhase.KILL,
                        backend=self._backend.name.value,
                    )
                volume = managed.volumes[0] if managed.volumes else None
                converged_without_runtime = True
            else:
                container = managed.containers[0]
                volume = managed.volumes[0] if managed.volumes else None
                await self._event(
                    events,
                    BrokerState.CANCELLING,
                    RuntimePhase.KILL,
                    state_session=state_session,
                )
                result = await self._run_owned(
                    state_session,
                    RuntimePhase.KILL,
                    lambda: runtime.kill(
                        container,
                        TerminationReason.CANCELLATION,
                    ),
                )
                terminal = True
                if result.classification is not TerminalClassification.CANCELLED:
                    raise RuntimeBackendError(
                        ErrorCode.CANCELLATION_REJECTED,
                        RuntimePhase.KILL,
                        backend=self._backend.name.value,
                        detail="runtime-returned-noncancelled-result",
                    )
        except LiveStateWriteError as error:
            primary_error = self._capture_state_write_error(error)
            ownership_lost = self._is_fenced_store_code(error.code)
        except OperationOwnershipError as error:
            primary_error = self._capture_ownership_error(error)
            ownership_lost = self._is_fenced_store_code(error.code)
        except RuntimeBackendError as error:
            primary_error = self._capture_error(identity, error)
        finally:
            classification = (
                result.classification
                if result is not None
                else TerminalClassification.CANCELLED
                if state_session is not None
                else None
            )
            if ownership_lost:
                cleanup_error = self._fenced_cleanup_error()
            else:
                try:
                    await self._event(
                        events,
                        BrokerState.CLEANING,
                        RuntimePhase.CLEANUP,
                        state_session=state_session,
                        classification=classification,
                    )
                except LiveStateWriteError as error:
                    if primary_error is None:
                        primary_error = self._capture_state_write_error(error)
                    ownership_lost = self._is_fenced_store_code(error.code)
                if ownership_lost:
                    cleanup_error = self._fenced_cleanup_error()
                else:
                    if (
                        state_session is not None
                        and not state_session.failed
                        and state_session.last_snapshot is not None
                        and state_session.last_snapshot.state is BrokerState.CLEANING
                    ):
                        cancellation_checkpoint(
                            crash_signal,
                            DurableCancellationCheckpoint.AFTER_CLEANING_STATE,
                            identity,
                        )
                    try:
                        first_cleanup_error = await self._cleanup_unlocked(
                            identity,
                            container,
                            volume,
                            started=container is not None,
                            terminal=terminal,
                            ownership_guard=(
                                state_session
                                if state_session is not None
                                and state_session.last_snapshot is not None
                                else None
                            ),
                        )
                        verification_error = await self._verify_no_managed(
                            identity,
                            state_session
                            if state_session is not None
                            and state_session.last_snapshot is not None
                            else None,
                        )
                        cleanup_error = first_cleanup_error or verification_error
                    except OperationOwnershipError as error:
                        if primary_error is None:
                            primary_error = self._capture_ownership_error(error)
                        ownership_lost = self._is_fenced_store_code(error.code)
                        cleanup_error = self._fenced_cleanup_error()
                    if not ownership_lost:
                        cancellation_checkpoint(
                            crash_signal,
                            DurableCancellationCheckpoint.AFTER_CLEANUP,
                            identity,
                        )

        runtime_cancelled = (
            result is not None
            and result.classification is TerminalClassification.CANCELLED
        )
        cancelled = (
            (runtime_cancelled or converged_without_runtime)
            and primary_error is None
            and cleanup_error is None
        )
        state = BrokerState.CANCELLED if cancelled else BrokerState.FAILED
        final_error = primary_error or cleanup_error
        final_phase = final_error.phase if final_error is not None else RuntimePhase.KILL
        classification = (
            result.classification
            if result is not None
            else TerminalClassification.CANCELLED
            if state_session is not None
            else None
        )
        durable_state = BrokerState.CLEANING if cleanup_error is not None else None
        try:
            await self._event(
                events,
                state,
                final_phase,
                final_error,
                state_session=state_session,
                durable_state=durable_state,
                durable_phase=(
                    RuntimePhase.CLEANUP if durable_state is not None else None
                ),
                durable_error=cleanup_error,
                classification=classification,
                cleanup_complete=cleanup_error is None,
            )
        except LiveStateWriteError as error:
            if primary_error is None:
                primary_error = self._capture_state_write_error(error)
            state = BrokerState.FAILED
            final_error = primary_error or cleanup_error
            final_phase = (
                final_error.phase if final_error is not None else RuntimePhase.KILL
            )
            events.pop()
            await self._event(
                events,
                state,
                final_phase,
                final_error,
                state_session=state_session,
                classification=classification,
                cleanup_complete=cleanup_error is None,
            )
        else:
            if (
                state_session is not None
                and not state_session.failed
                and state_session.last_snapshot is not None
                and state_session.last_snapshot.state
                in {BrokerState.CANCELLED, BrokerState.FAILED}
            ):
                cancellation_checkpoint(
                    crash_signal,
                    DurableCancellationCheckpoint.AFTER_FINAL_STATE,
                    identity,
                )
        return CancellationOutcome(
            identity=identity,
            state=state,
            result=result,
            error=primary_error,
            cleanup_error=cleanup_error,
            cleanup_complete=cleanup_error is None,
            events=tuple(events),
            intent_persisted=state_session is not None,
        )

    async def _reconcile_locked(
        self,
        identity: JobIdentity,
        ownership_guard: OperationOwnershipGuard | None = None,
    ) -> ReconciliationReport:
        runtime = self._job_runtime(identity, ownership_guard)
        managed = await self._run_owned(
            ownership_guard,
            RuntimePhase.QUERY,
            runtime.list_managed,
        )
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
                    await self._run_owned(
                        ownership_guard,
                        RuntimePhase.CLEANUP,
                        lambda: runtime.remove_container(container),
                    )
                except RuntimeBackendError as error:
                    if error.code is ErrorCode.CONTAINER_NOT_FOUND:
                        containers_removed += 1
                        continue
                    if error.code is not ErrorCode.INVALID_STATE:
                        errors.append(self._capture_error(identity, error))
                        continue
                    try:
                        await self._run_owned(
                            ownership_guard,
                            RuntimePhase.KILL,
                            lambda: runtime.kill(container, TerminationReason.SHUTDOWN),
                        )
                    except RuntimeBackendError as kill_error:
                        if kill_error.code is ErrorCode.CONTAINER_NOT_FOUND:
                            containers_removed += 1
                            continue
                        errors.append(self._capture_error(identity, kill_error))
                        continue
                    try:
                        await self._run_owned(
                            ownership_guard,
                            RuntimePhase.CLEANUP,
                            lambda: runtime.remove_container(container),
                        )
                    except RuntimeBackendError as retry_error:
                        if retry_error.code is not ErrorCode.CONTAINER_NOT_FOUND:
                            errors.append(self._capture_error(identity, retry_error))
                            continue
                containers_removed += 1

            for volume in managed.volumes:
                try:
                    await self._run_owned(
                        ownership_guard,
                        RuntimePhase.CLEANUP,
                        lambda: runtime.remove_volume(volume),
                    )
                except RuntimeBackendError as error:
                    if error.code is not ErrorCode.VOLUME_NOT_FOUND:
                        errors.append(self._capture_error(identity, error))
                        continue
                volumes_removed += 1

        remaining = await self._run_owned(
            ownership_guard,
            RuntimePhase.QUERY,
            runtime.list_managed,
        )
        return ReconciliationReport(
            containers_found=len(managed.containers),
            containers_removed=containers_removed,
            volumes_found=len(managed.volumes),
            volumes_removed=volumes_removed,
            remaining_containers=len(remaining.containers),
            remaining_volumes=len(remaining.volumes),
            errors=tuple(errors),
        )

    async def reconcile(
        self,
        job_id: str | None = None,
        *,
        ownership_guard: OperationOwnershipGuard | None = None,
    ) -> ReconciliationReport:
        if ownership_guard is not None and not isinstance(
            ownership_guard,
            OperationOwnershipGuard,
        ):
            raise TypeError("Reconciliation ownership guard has the wrong type.")
        if job_id is not None:
            identity = JobIdentity(job_id)
            async with self._cleanup_coordinator.lease(identity):
                return await self._reconcile_locked(identity, ownership_guard)

        if ownership_guard is not None:
            raise TypeError("Global reconciliation cannot use one job ownership guard.")
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
