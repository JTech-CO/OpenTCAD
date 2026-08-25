"""SQLite conformance, migration, redaction, and hard-exit recovery tests."""

from __future__ import annotations

import asyncio
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from backend.app.broker import (
    BrokerState,
    CrashRecoveryCoordinator,
    RecoveryRequest,
    RecoveryStatus,
    ReconciliationReport,
    SQLITE_STATE_PRODUCT_ENABLED,
    SQLITE_STATE_RETENTION_POLICY,
    SQLITE_STATE_SCHEMA_VERSION,
    SQLiteJobStateStore,
    StateStoreError,
    StateStoreErrorCode,
)
from backend.app.runtime.errors import ErrorCode, RuntimePhase
from backend.app.runtime.models import RuntimeKind
from backend.tests.broker.lease_support import ManualLeaseClock
from backend.tests.broker.sqlite_recovery_child import HARD_EXIT_CODE
from backend.tests.broker.state_store_conformance import (
    DurableStateStoreConformanceMixin,
    conformance_event,
    uuid_at,
)


class SQLiteStateStoreConformanceTests(
    DurableStateStoreConformanceMixin,
    unittest.IsolatedAsyncioTestCase,
):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self._database = Path(self._temporary.name) / "state.sqlite3"
        self.clock = ManualLeaseClock()

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def new_store(self) -> SQLiteJobStateStore:
        return SQLiteJobStateStore(self._database, clock=self.clock)

    def reopen_store(self) -> SQLiteJobStateStore:
        return SQLiteJobStateStore(self._database, clock=self.clock)

    def advance_lease_clock(self, milliseconds: int) -> None:
        self.clock.advance(milliseconds)


class CompleteReconciler:
    def __init__(self, expected_job_id: str) -> None:
        self.expected_job_id = expected_job_id
        self.calls = 0

    async def reconcile(
        self,
        job_id: str | None = None,
        *,
        ownership_guard=None,
    ) -> ReconciliationReport:
        if job_id != self.expected_job_id:
            raise AssertionError("recovery must reconcile the exact durable job")
        self.calls += 1
        return ReconciliationReport(
            containers_found=1,
            containers_removed=1,
            volumes_found=1,
            volumes_removed=1,
            remaining_containers=0,
            remaining_volumes=0,
            errors=(),
        )


class SQLiteStateStoreContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self._database = Path(self._temporary.name) / "state.sqlite3"

    def tearDown(self) -> None:
        self._temporary.cleanup()

    async def test_schema_v3_is_wal_event_append_only_redacted_and_inactive(self) -> None:
        for invalid in (":memory:", "file:state.sqlite3?mode=memory", 7):
            with self.subTest(invalid=invalid):
                with self.assertRaises(TypeError):
                    SQLiteJobStateStore(invalid)

        store = SQLiteJobStateStore(self._database)
        await store.append(
            conformance_event(
                job=201,
                event_number=201,
                operation=201,
                operation_sequence=1,
                state=BrokerState.VALIDATING,
                phase=RuntimePhase.VALIDATE,
            ),
            expected_revision=0,
        )
        with closing(sqlite3.connect(self._database)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            columns = tuple(
                row[1]
                for row in connection.execute("PRAGMA table_info(job_events)")
            )
            rows = connection.execute("SELECT COUNT(*) FROM job_events").fetchone()[0]
            lease_columns = tuple(
                row[1]
                for row in connection.execute("PRAGMA table_info(job_leases)")
            )
            lease_rows = connection.execute("SELECT COUNT(*) FROM job_leases").fetchone()[0]
        self.assertEqual(version, SQLITE_STATE_SCHEMA_VERSION)
        self.assertEqual(str(mode).casefold(), "wal")
        self.assertEqual(rows, 1)
        self.assertNotIn("detail", columns)
        self.assertNotIn("payload", columns)
        self.assertNotIn("host_path", columns)
        self.assertIn("owner_id", columns)
        self.assertIn("fencing_token", columns)
        self.assertIn("lease_duration_ms", columns)
        self.assertIn("lease_expires_at_ms", columns)
        self.assertIn("job_revision", lease_columns)
        self.assertEqual(lease_rows, 1)
        self.assertEqual(
            SQLITE_STATE_RETENTION_POLICY,
            "append-only-events-explicit-lease-renewal",
        )
        self.assertFalse(SQLITE_STATE_PRODUCT_ENABLED)
        self.assertNotIn(str(self._database), repr(store))

    async def test_schema_v1_forward_migration_preserves_owner_generations(self) -> None:
        job_id = uuid_at(10_250)
        operation_one = uuid_at(20_250)
        operation_two = uuid_at(20_251)
        with closing(sqlite3.connect(self._database)) as connection:
            connection.execute(
                """
                CREATE TABLE job_events (
                    job_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    event_id TEXT NOT NULL UNIQUE,
                    operation_id TEXT NOT NULL,
                    operation_sequence INTEGER NOT NULL CHECK (operation_sequence >= 1),
                    state TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    code TEXT,
                    retry TEXT,
                    backend TEXT,
                    classification TEXT,
                    cleanup_complete INTEGER NOT NULL CHECK (cleanup_complete IN (0, 1)),
                    PRIMARY KEY (job_id, revision),
                    UNIQUE (job_id, operation_id, operation_sequence)
                )
                """,
            )
            connection.executemany(
                "INSERT INTO job_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    (
                        job_id, 1, uuid_at(30_250), operation_one, 1,
                        "validating", "validate", None, None, "mock", None, 0,
                    ),
                    (
                        job_id, 2, uuid_at(30_251), operation_one, 2,
                        "preparing", "image", None, None, "mock", None, 0,
                    ),
                    (
                        job_id, 3, uuid_at(30_252), operation_two, 1,
                        "cancelling", "query", None, None, "mock", None, 0,
                    ),
                ),
            )
            connection.execute("PRAGMA user_version = 1")
            connection.commit()

        store = SQLiteJobStateStore(self._database)
        page = await store.scan_recoverable(limit=1)
        migrated = page.items[0]
        self.assertEqual(
            (migrated.revision, migrated.state, migrated.ownership.operation_id),
            (3, BrokerState.CANCELLING, operation_two),
        )
        self.assertEqual(migrated.ownership.fencing_token, 2)
        with self.assertRaises(StateStoreError) as expired:
            await store.verify_ownership(
                migrated.ownership,
                expected_revision=3,
            )
        self.assertEqual(expired.exception.code, StateStoreErrorCode.LEASE_EXPIRED)
        with closing(sqlite3.connect(self._database)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            rows = tuple(
                connection.execute(
                    "SELECT operation_id, owner_id, fencing_token "
                    "FROM job_events ORDER BY revision",
                ),
            )
        self.assertEqual(version, SQLITE_STATE_SCHEMA_VERSION)
        self.assertEqual(
            rows,
            (
                (operation_one, operation_one, 1),
                (operation_one, operation_one, 1),
                (operation_two, operation_two, 2),
            ),
        )

    async def test_schema_v2_forward_migration_expires_legacy_lease(self) -> None:
        job_id = uuid_at(10_260)
        operation_id = uuid_at(20_260)
        owner_id = uuid_at(30_260)
        with closing(sqlite3.connect(self._database)) as connection:
            connection.execute(
                """
                CREATE TABLE job_events (
                    job_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    event_id TEXT NOT NULL UNIQUE,
                    operation_id TEXT NOT NULL,
                    operation_sequence INTEGER NOT NULL CHECK (operation_sequence >= 1),
                    owner_id TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL CHECK (fencing_token >= 1),
                    state TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    code TEXT,
                    retry TEXT,
                    backend TEXT,
                    classification TEXT,
                    cleanup_complete INTEGER NOT NULL CHECK (cleanup_complete IN (0, 1)),
                    PRIMARY KEY (job_id, revision),
                    UNIQUE (job_id, operation_id, operation_sequence)
                )
                """,
            )
            connection.execute(
                "INSERT INTO job_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id, 1, uuid_at(40_260), operation_id, 1,
                    owner_id, 1, "running", "wait", None, None,
                    "mock", None, 0,
                ),
            )
            connection.execute("PRAGMA user_version = 2")
            connection.commit()

        store = SQLiteJobStateStore(self._database)
        migrated = await store.load(
            conformance_event(
                job=260,
                event_number=260,
                operation=260,
                operation_sequence=1,
                state=BrokerState.VALIDATING,
                phase=RuntimePhase.VALIDATE,
            ).identity,
        )
        self.assertEqual(migrated.identity.job_id, job_id)
        self.assertEqual(migrated.ownership.owner_id, owner_id)
        self.assertEqual(migrated.ownership.fencing_token, 1)
        with self.assertRaises(StateStoreError) as expired:
            await store.verify_ownership(migrated.ownership, expected_revision=1)
        self.assertEqual(expired.exception.code, StateStoreErrorCode.LEASE_EXPIRED)

        claimed = await store.append(
            conformance_event(
                job=260,
                event_number=261,
                operation=261,
                operation_sequence=1,
                state=BrokerState.CLEANING,
                phase=RuntimePhase.CLEANUP,
                fencing_token=2,
            ),
            expected_revision=1,
        )
        self.assertEqual((claimed.revision, claimed.ownership.fencing_token), (2, 2))
        with closing(sqlite3.connect(self._database)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            lease = connection.execute(
                "SELECT owner_id, fencing_token, job_revision FROM job_leases WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        self.assertEqual(version, 3)
        self.assertEqual(lease, (claimed.ownership.owner_id, 2, 2))

    async def test_locked_writer_maps_to_redacted_store_unavailable(self) -> None:
        store = SQLiteJobStateStore(self._database, busy_timeout_ms=25)
        first = conformance_event(
            job=202,
            event_number=202,
            operation=202,
            operation_sequence=1,
            state=BrokerState.VALIDATING,
            phase=RuntimePhase.VALIDATE,
        )
        await store.append(first, expected_revision=0)
        lock = sqlite3.connect(self._database, timeout=0, isolation_level=None)
        try:
            lock.execute("BEGIN IMMEDIATE")
            with self.assertRaises(StateStoreError) as captured:
                await store.append(
                    conformance_event(
                        job=202,
                        event_number=203,
                        operation=203,
                        operation_sequence=1,
                        state=BrokerState.PREPARING,
                        phase=RuntimePhase.IMAGE,
                    ),
                    expected_revision=1,
                )
        finally:
            lock.rollback()
            lock.close()
        self.assertEqual(
            captured.exception.code,
            StateStoreErrorCode.STORE_UNAVAILABLE,
        )
        self.assertEqual(captured.exception.as_dict(), {"code": "store-unavailable"})
        self.assertNotIn(str(self._database), str(captured.exception))

    async def test_unknown_or_mismatched_schema_fails_closed(self) -> None:
        with closing(sqlite3.connect(self._database)) as connection:
            connection.execute("PRAGMA user_version = 3")
            connection.commit()
        mismatched = Path(self._temporary.name) / "mismatched.sqlite3"
        with closing(sqlite3.connect(mismatched)) as connection:
            connection.execute("CREATE TABLE job_events (job_id TEXT)")
            connection.execute("PRAGMA user_version = 2")
            connection.commit()

        for database in (self._database, mismatched):
            with self.subTest(database=database.name):
                with self.assertRaises(StateStoreError) as captured:
                    await SQLiteJobStateStore(database).scan_recoverable(limit=1)
                self.assertEqual(
                    captured.exception.code,
                    StateStoreErrorCode.STORE_UNAVAILABLE,
                )
                self.assertEqual(str(captured.exception), "store-unavailable")

    async def test_hard_exit_claim_survives_process_and_recovery_converges(self) -> None:
        store = SQLiteJobStateStore(
            self._database,
            clock=ManualLeaseClock(),
        )
        job = 203
        path = (
            (BrokerState.VALIDATING, RuntimePhase.VALIDATE),
            (BrokerState.PREPARING, RuntimePhase.IMAGE),
            (BrokerState.RUNNING, RuntimePhase.WAIT),
        )
        snapshot = None
        for sequence, (state, phase) in enumerate(path, start=1):
            snapshot = await store.append(
                conformance_event(
                    job=job,
                    event_number=300 + sequence,
                    operation=job,
                    operation_sequence=sequence,
                    state=state,
                    phase=phase,
                ),
                expected_revision=sequence - 1,
            )
        recovery_id = uuid_at(900_203)
        repository = Path(__file__).resolve().parents[3]
        completed = await asyncio.to_thread(
            subprocess.run,
            [
                sys.executable,
                "-m",
                "backend.tests.broker.sqlite_recovery_child",
                str(self._database),
                recovery_id,
                snapshot.identity.job_id,
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

        reopened = SQLiteJobStateStore(self._database)
        claimed = await reopened.load(snapshot.identity)
        self.assertEqual((claimed.state, claimed.revision), (BrokerState.CLEANING, 4))
        reconciler = CompleteReconciler(snapshot.identity.job_id)
        report = await CrashRecoveryCoordinator(
            reopened,
            reconciler,
            RuntimeKind.MOCK,
        ).recover(RecoveryRequest(recovery_id, limit=1))
        final = await reopened.load(snapshot.identity)
        self.assertEqual(reconciler.calls, 1)
        self.assertEqual(report.items[0].status, RecoveryStatus.RECOVERED_FAILED)
        self.assertEqual(report.items[0].code, ErrorCode.STALE_STATE)
        self.assertEqual((final.state, final.revision), (BrokerState.FAILED, 6))
        self.assertFalse(final.recoverable)


if __name__ == "__main__":
    unittest.main()
