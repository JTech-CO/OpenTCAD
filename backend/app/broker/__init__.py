"""Engine-independent broker library with no service transport or runtime socket."""

from .archive import (
    ArchiveLimits,
    InputPayload,
    build_canonical_input_archive,
    validate_canonical_input_archive,
)
from .cancellation import CancellationOutcome, CancellationRequest
from .cleanup import JobCleanupCoordinator
from .diagnostics import InternalDiagnostic
from .lifecycle import CancellationSignal, LifecycleCheckpoint, PhaseCancellation
from .models import (
    BrokerError,
    BrokerEvent,
    BrokerOutcome,
    BrokerRequest,
    BrokerState,
    ReconciliationReport,
)
from .orchestrator import SandboxBroker
from .output_archive import (
    ArtifactPayload,
    build_canonical_output_archive,
    output_archive_limits,
    validate_canonical_output_archive,
)
from .recovery import (
    CrashRecoveryCoordinator,
    RecoveryCheckpoint,
    RecoveryCrashInjection,
    RecoveryCrashSignal,
    RecoveryInterrupted,
    RecoveryItem,
    RecoveryReconciler,
    RecoveryReport,
    RecoveryRequest,
    RecoveryStatus,
)
from .state import (
    DurableJobEvent,
    DurableJobStateStore,
    InMemoryJobStateStore,
    InMemoryStateStoreBacking,
    JobStateSnapshot,
    RecoverableStatePage,
    StateStoreError,
    StateStoreErrorCode,
    validate_state_transition,
)
from .sqlite_state import (
    SQLITE_STATE_PRODUCT_ENABLED,
    SQLITE_STATE_RETENTION_POLICY,
    SQLITE_STATE_SCHEMA_VERSION,
    SQLiteJobStateStore,
)
from .state_mapping import (
    BrokerStateMapper,
    MappedStateBatch,
    StateEventRecorder,
    StateMappingContext,
    StateMappingError,
    StateMappingErrorCode,
)

__all__ = [
    "ArchiveLimits",
    "ArtifactPayload",
    "BrokerError",
    "BrokerEvent",
    "BrokerOutcome",
    "BrokerRequest",
    "BrokerState",
    "BrokerStateMapper",
    "CancellationOutcome",
    "CancellationRequest",
    "CancellationSignal",
    "CrashRecoveryCoordinator",
    "DurableJobEvent",
    "DurableJobStateStore",
    "InMemoryJobStateStore",
    "InMemoryStateStoreBacking",
    "InputPayload",
    "InternalDiagnostic",
    "JobCleanupCoordinator",
    "JobStateSnapshot",
    "LifecycleCheckpoint",
    "MappedStateBatch",
    "PhaseCancellation",
    "RecoverableStatePage",
    "ReconciliationReport",
    "RecoveryCheckpoint",
    "RecoveryCrashInjection",
    "RecoveryCrashSignal",
    "RecoveryInterrupted",
    "RecoveryItem",
    "RecoveryReconciler",
    "RecoveryReport",
    "RecoveryRequest",
    "RecoveryStatus",
    "SQLITE_STATE_PRODUCT_ENABLED",
    "SQLITE_STATE_RETENTION_POLICY",
    "SQLITE_STATE_SCHEMA_VERSION",
    "SQLiteJobStateStore",
    "SandboxBroker",
    "StateEventRecorder",
    "StateMappingContext",
    "StateMappingError",
    "StateMappingErrorCode",
    "StateStoreError",
    "StateStoreErrorCode",
    "build_canonical_input_archive",
    "build_canonical_output_archive",
    "output_archive_limits",
    "validate_canonical_input_archive",
    "validate_canonical_output_archive",
    "validate_state_transition",
]
