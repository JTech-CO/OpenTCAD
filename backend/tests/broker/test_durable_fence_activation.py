"""Durable store-to-runtime activation and restart recovery contracts."""

from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from backend.app.broker import (
    BrokerRequest,
    BrokerStartupRequest,
    BrokerState,
    CrashRecoveryCoordinator,
    DurableBrokerComposition,
    DurableRuntimeFenceActivator,
    InMemoryJobStateStore,
    RecoveryRequest,
    RecoveryStatus,
    ReconciliationReport,
    SQLiteJobStateStore,
    SandboxBroker,
    StateOperationContext,
    StateStoreError,
    StateStoreErrorCode,
)
from backend.app.runtime import (
    ErrorCode,
    InMemoryRuntimeFenceAuthority,
    JobIdentity,
    RuntimeBackendError,
    RuntimeFencingContext,
    RuntimeKind,
    RuntimePhase,
    SQLiteRuntimeFenceAuthority,
    TerminalClassification,
)
from backend.app.runtime.mock_backend import MockRuntimeBackend
from backend.tests.broker.lease_support import ManualLeaseClock
from backend.tests.broker.sqlite_recovery_child import HARD_EXIT_CODE
from backend.tests.broker.state_store_conformance import conformance_event, uuid_at
from backend.tests.runtime.support import (
    ARCHIVE_LIMITS,
    ARCHIVE_BYTES,
    ARTIFACT_ARCHIVE,
    IMAGE,
    POLICY,
    make_result,
    make_spec,
)


class TakeoverDuringActivationAuthority:
    def __init__(self, takeover) -> None:
        self.delegate = InMemoryRuntimeFenceAuthority()
        self._takeover = takeover
        self._triggered = False

    async def activate(self, fence, *, phase, backend) -> None:
        await self.delegate.activate(fence, phase=phase, backend=backend)
        if not self._triggered:
            self._triggered = True
            await self._takeover()

    async def verify(self, fence, *, phase, backend) -> None:
        await self.delegate.verify(fence, phase=phase, backend=backend)


class ActivationObservingReconciler:
    def __init__(
        self,
        authority: SQLiteRuntimeFenceAuthority,
        expected_job_id: str,
        expected_token: int,
    ) -> None:
        self.authority = authority
        self.expected_job_id = expected_job_id
        self.expected_token = expected_token
        self.calls = 0

    async def reconcile(self, job_id=None, *, ownership_guard=None):
        self.calls += 1
        if job_id != self.expected_job_id or ownership_guard is None:
            raise AssertionError("recovery must retain the exact job ownership")
        current = await self.authority.current(job_id)
        if current != ownership_guard.runtime_fence:
            raise AssertionError("authority must activate before reconciliation")
        if current.fencing_token != self.expected_token:
            raise AssertionError("recovery activated the wrong generation")
        return ReconciliationReport(0, 0, 0, 0, 0, 0, ())


class DurableFenceActivationContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._temporary.cleanup()

    @staticmethod
    async def seed_running(store, job: int, *, lease_duration_ms: int = 30_000):
        snapshot = None
        for sequence, (state, phase) in enumerate(
            (
                (BrokerState.VALIDATING, RuntimePhase.VALIDATE),
                (BrokerState.PREPARING, RuntimePhase.IMAGE),
                (BrokerState.RUNNING, RuntimePhase.WAIT),
            ),
            start=1,
        ):
            snapshot = await store.append(
                conformance_event(
                    job=job,
                    event_number=job * 10 + sequence,
                    operation=job,
                    operation_sequence=sequence,
                    state=state,
                    phase=phase,
                    lease_duration_ms=lease_duration_ms,
                ),
                expected_revision=sequence - 1,
            )
        return snapshot

    async def test_bridge_activates_only_exact_committed_ownership(self) -> None:
        store = InMemoryJobStateStore()
        snapshot = await store.append(
            conformance_event(
                job=901,
                event_number=901,
                operation=901,
                operation_sequence=1,
                state=BrokerState.VALIDATING,
                phase=RuntimePhase.VALIDATE,
            ),
            expected_revision=0,
        )
        authority = SQLiteRuntimeFenceAuthority(
            Path(self._temporary.name) / "bridge.sqlite3",
        )
        activator = DurableRuntimeFenceActivator(store, authority, RuntimeKind.MOCK)
        fence = await activator.activate_owned(
            snapshot.ownership,
            expected_revision=snapshot.revision,
            phase=RuntimePhase.PROBE,
        )
        self.assertEqual(fence, snapshot.ownership.runtime_fence)
        self.assertEqual(await authority.current(snapshot.identity.job_id), fence)

        takeover = await store.append(
            conformance_event(
                job=901,
                event_number=902,
                operation=902,
                operation_sequence=1,
                state=BrokerState.CANCELLING,
                phase=RuntimePhase.QUERY,
                fencing_token=2,
            ),
            expected_revision=1,
        )
        with self.assertRaises(StateStoreError) as stale:
            await activator.activate_owned(
                snapshot.ownership,
                expected_revision=snapshot.revision,
                phase=RuntimePhase.QUERY,
            )
        self.assertIn(
            stale.exception.code,
            {
                StateStoreErrorCode.OWNERSHIP_CONFLICT,
                StateStoreErrorCode.REVISION_CONFLICT,
            },
        )
        takeover_fence = await activator.activate_owned(
            takeover.ownership,
            expected_revision=takeover.revision,
            phase=RuntimePhase.QUERY,
        )
        self.assertEqual(await authority.current(snapshot.identity.job_id), takeover_fence)

    async def test_bridge_post_activation_check_closes_interleaved_takeover(self) -> None:
        store = InMemoryJobStateStore()
        first = await store.append(
            conformance_event(
                job=911,
                event_number=911,
                operation=911,
                operation_sequence=1,
                state=BrokerState.VALIDATING,
                phase=RuntimePhase.VALIDATE,
            ),
            expected_revision=0,
        )
        claimed = None

        async def takeover() -> None:
            nonlocal claimed
            claimed = await store.append(
                conformance_event(
                    job=911,
                    event_number=912,
                    operation=912,
                    operation_sequence=1,
                    state=BrokerState.CANCELLING,
                    phase=RuntimePhase.QUERY,
                    fencing_token=2,
                ),
                expected_revision=1,
            )

        authority = TakeoverDuringActivationAuthority(takeover)
        activator = DurableRuntimeFenceActivator(store, authority, RuntimeKind.MOCK)
        with self.assertRaises(StateStoreError) as rejected:
            await activator.activate_owned(
                first.ownership,
                expected_revision=first.revision,
                phase=RuntimePhase.QUERY,
            )
        self.assertIn(
            rejected.exception.code,
            {
                StateStoreErrorCode.OWNERSHIP_CONFLICT,
                StateStoreErrorCode.REVISION_CONFLICT,
            },
        )
        self.assertIsNotNone(claimed)
        current = await authority.delegate.current(first.identity.job_id)
        self.assertEqual(current.fencing_token, 1)

        takeover_fence = await activator.activate_owned(
            claimed.ownership,
            expected_revision=claimed.revision,
            phase=RuntimePhase.QUERY,
        )
        self.assertEqual(takeover_fence.fencing_token, 2)

    async def test_composition_activates_durable_authority_before_runtime(self) -> None:
        job_id = uuid_at(30_921)
        authority = SQLiteRuntimeFenceAuthority(
            Path(self._temporary.name) / "composition-fence.sqlite3",
        )
        backend = MockRuntimeBackend(
            images=(IMAGE,),
            fence_authority=authority,
        )
        backend.plan_result(
            job_id,
            make_result(
                TerminalClassification.SUCCEEDED,
                exit_code=0,
                include_artifact=True,
            ),
            ARTIFACT_ARCHIVE,
        )
        store = SQLiteJobStateStore(
            Path(self._temporary.name) / "composition-state.sqlite3",
        )
        composition = DurableBrokerComposition(
            SandboxBroker(backend, POLICY, ARCHIVE_LIMITS),
            store,
        )
        await composition.startup(BrokerStartupRequest(uuid_at(50_921)))
        outcome = await composition.execute(
            BrokerRequest(make_spec(job_id), ARCHIVE_BYTES),
            StateOperationContext(uuid_at(40_921)),
        )
        self.assertEqual(outcome.state, BrokerState.SUCCEEDED)
        current = await authority.current(job_id)
        snapshot = await store.load(JobIdentity(job_id))
        self.assertEqual(current, snapshot.ownership.runtime_fence)
        self.assertEqual(current.fencing_token, 1)

    async def test_claim_activation_gap_recovers_with_next_durable_generation(self) -> None:
        state_database = Path(self._temporary.name) / "recovery-state.sqlite3"
        authority_database = Path(self._temporary.name) / "recovery-fence.sqlite3"
        seed_store = SQLiteJobStateStore(
            state_database,
            clock=ManualLeaseClock(),
        )
        first = await self.seed_running(seed_store, 931, lease_duration_ms=2)
        authority = SQLiteRuntimeFenceAuthority(authority_database)
        first_activator = DurableRuntimeFenceActivator(
            seed_store,
            authority,
            RuntimeKind.MOCK,
        )
        await first_activator.activate_owned(
            first.ownership,
            expected_revision=first.revision,
            phase=RuntimePhase.WAIT,
        )

        recovery_id = uuid_at(900_931)
        repository = Path(__file__).resolve().parents[3]
        completed = await asyncio.to_thread(
            subprocess.run,
            [
                sys.executable,
                "-m",
                "backend.tests.broker.sqlite_recovery_child",
                str(state_database),
                recovery_id,
                first.identity.job_id,
            ],
            cwd=repository,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            HARD_EXIT_CODE,
            msg=f"stdout={completed.stdout!r} stderr={completed.stderr!r}",
        )

        reopened_store = SQLiteJobStateStore(state_database)
        gap = await reopened_store.load(first.identity)
        self.assertEqual(gap.ownership.fencing_token, 2)
        self.assertEqual(
            (await authority.current(first.identity.job_id)).fencing_token,
            1,
        )

        reconciler = ActivationObservingReconciler(
            authority,
            first.identity.job_id,
            3,
        )
        activator = DurableRuntimeFenceActivator(
            reopened_store,
            authority,
            RuntimeKind.MOCK,
        )
        report = await CrashRecoveryCoordinator(
            reopened_store,
            reconciler,
            RuntimeKind.MOCK,
            fence_activator=activator,
        ).recover(RecoveryRequest(recovery_id, limit=1))
        final = await reopened_store.load(first.identity)
        self.assertEqual(reconciler.calls, 1)
        self.assertEqual(report.items[0].status, RecoveryStatus.RECOVERED_FAILED)
        self.assertEqual(final.ownership.fencing_token, 3)
        self.assertEqual(
            (await authority.current(first.identity.job_id)).fencing_token,
            3,
        )

        gap_fence = RuntimeFencingContext(
            gap.identity,
            gap.ownership.owner_id,
            gap.ownership.fencing_token,
        )
        with self.assertRaises(RuntimeBackendError) as stale:
            await authority.activate(
                gap_fence,
                phase=RuntimePhase.CLEANUP,
                backend=RuntimeKind.MOCK,
            )
        self.assertEqual(stale.exception.code, ErrorCode.OPERATION_FENCED)


if __name__ == "__main__":
    unittest.main()
