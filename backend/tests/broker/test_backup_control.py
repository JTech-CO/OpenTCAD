"""Durable maintenance, sequence, restore-floor, and schedule contracts."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from backend.app.broker.backup_control import (
    SQLITE_BACKUP_CONTROL_PRODUCT_ENABLED,
    SQLITE_BACKUP_CONTROL_RETENTION_POLICY,
    SQLITE_BACKUP_CONTROL_SCHEMA_VERSION,
    BackupControlError,
    BackupControlErrorCode,
    BackupScheduleClaim,
    BackupScheduleDefinition,
    MaintenancePhase,
    MaintenanceRequest,
    SQLiteBackupControlStore,
)
from backend.tests.broker.lease_support import ManualLeaseClock
from backend.tests.broker.state_store_conformance import uuid_at


class SQLiteBackupControlContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self._root = Path(self._temporary.name)
        self._database = self._root / "backup-control.sqlite3"
        self._instance = uuid_at(720_001)
        self._clock = ManualLeaseClock()
        self._store = SQLiteBackupControlStore(
            self._database,
            self._instance,
            clock=self._clock,
        )

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def maintenance_request(
        self,
        *,
        maintenance: int = 720_010,
        owner: int = 720_011,
        quiescence: int = 720_012,
        duration: int = 10_000,
    ) -> MaintenanceRequest:
        return MaintenanceRequest(
            uuid_at(maintenance),
            uuid_at(owner),
            uuid_at(quiescence),
            duration,
        )

    def test_schema_identity_reopen_and_redaction(self) -> None:
        self.assertFalse(SQLITE_BACKUP_CONTROL_PRODUCT_ENABLED)
        self.assertEqual(SQLITE_BACKUP_CONTROL_SCHEMA_VERSION, 1)
        self.assertEqual(
            SQLITE_BACKUP_CONTROL_RETENTION_POLICY,
            "monotonic-no-automatic-delete",
        )
        self.assertNotIn(str(self._database), repr(self._store))
        reopened = SQLiteBackupControlStore(
            self._database,
            self._instance,
            clock=self._clock,
        )
        self.assertEqual(reopened.installation_id, self._instance)
        with self.assertRaises(BackupControlError) as mismatch:
            SQLiteBackupControlStore(
                self._database,
                uuid_at(720_099),
                clock=self._clock,
            )
        self.assertEqual(
            mismatch.exception.code,
            BackupControlErrorCode.INSTALLATION_ID_MISMATCH,
        )
        self.assertNotIn(str(self._database), str(mismatch.exception))

    def test_admission_drain_blocks_new_work_until_offline_lease_ends(self) -> None:
        admission = self._store.admit_operation(
            uuid_at(720_020),
            uuid_at(720_021),
            lease_duration_ms=2_000,
        )
        lease = self._store.begin_maintenance(self.maintenance_request())
        self.assertEqual(lease.phase, MaintenancePhase.DRAINING)
        with self.assertRaises(BackupControlError) as blocked:
            self._store.admit_operation(
                uuid_at(720_022),
                uuid_at(720_023),
                lease_duration_ms=2_000,
            )
        self.assertEqual(blocked.exception.code, BackupControlErrorCode.MAINTENANCE_ACTIVE)
        with self.assertRaises(BackupControlError) as active:
            self._store.mark_offline(lease)
        self.assertEqual(
            active.exception.code,
            BackupControlErrorCode.MAINTENANCE_NOT_QUIESCENT,
        )

        self._clock.advance(2_001)
        lease = self._store.mark_offline(lease)
        quiescence = self._store.verify_offline(lease)
        self.assertTrue(quiescence.asserted)
        with self.assertRaises(BackupControlError) as expired:
            self._store.renew_operation(admission, lease_duration_ms=2_000)
        self.assertIn(
            expired.exception.code,
            {
                BackupControlErrorCode.ADMISSION_CONFLICT,
                BackupControlErrorCode.ADMISSION_EXPIRED,
            },
        )
        self._store.release_operation(admission)
        self._store.end_maintenance(lease)
        next_admission = self._store.admit_operation(
            uuid_at(720_024),
            uuid_at(720_025),
            lease_duration_ms=2_000,
        )
        self.assertEqual(next_admission.maintenance_generation, lease.generation)

    def test_expired_maintenance_takeover_fences_stale_owner(self) -> None:
        stale = self._store.begin_maintenance(
            self.maintenance_request(duration=1_000),
        )
        self._clock.advance(1_001)
        with self.assertRaises(BackupControlError) as expired:
            self._store.end_maintenance(stale)
        self.assertEqual(
            expired.exception.code,
            BackupControlErrorCode.MAINTENANCE_NOT_OWNER,
        )
        replacement = self._store.begin_maintenance(
            self.maintenance_request(
                maintenance=720_013,
                owner=720_014,
                quiescence=720_015,
            ),
        )
        self.assertEqual(replacement.generation, stale.generation + 1)
        with self.assertRaises(BackupControlError) as fenced:
            self._store.end_maintenance(stale)
        self.assertEqual(
            fenced.exception.code,
            BackupControlErrorCode.MAINTENANCE_NOT_OWNER,
        )
        replacement = self._store.mark_offline(replacement)
        self._store.end_maintenance(replacement)

    def test_snapshot_sequence_is_monotonic_idempotent_and_durable(self) -> None:
        first_id = uuid_at(720_030)
        second_id = uuid_at(720_031)
        first = self._store.reserve_snapshot(self._instance, first_id)
        replay = self._store.reserve_snapshot(self._instance, first_id)
        second = self._store.reserve_snapshot(self._instance, second_id)
        self.assertEqual(first, replay)
        self.assertEqual((first.snapshot_sequence, second.snapshot_sequence), (1, 2))
        exported = self._store.mark_snapshot_exported(first)
        self.assertTrue(exported.exported)
        reopened = SQLiteBackupControlStore(
            self._database,
            self._instance,
            clock=self._clock,
        )
        self.assertEqual(
            reopened.reserve_snapshot(self._instance, second_id).snapshot_sequence,
            2,
        )

    def test_restore_floor_persists_and_rejects_rollback_or_same_sequence_swap(self) -> None:
        snapshot_two = uuid_at(720_040)
        floor, policy = self._store.advance_restore_floor(
            uuid_at(720_041),
            snapshot_two,
            2,
            requested_minimum_sequence=1,
        )
        self.assertEqual(floor.minimum_snapshot_sequence, 2)
        self.assertEqual(policy.minimum_snapshot_sequence, 2)
        reopened = SQLiteBackupControlStore(
            self._database,
            self._instance,
            clock=self._clock,
        )
        with self.assertRaises(BackupControlError) as rollback:
            reopened.advance_restore_floor(
                uuid_at(720_041),
                uuid_at(720_042),
                1,
                requested_minimum_sequence=1,
            )
        self.assertEqual(
            rollback.exception.code,
            BackupControlErrorCode.RESTORE_ROLLBACK_REJECTED,
        )
        with self.assertRaises(BackupControlError) as swap:
            reopened.advance_restore_floor(
                uuid_at(720_041),
                uuid_at(720_043),
                2,
                requested_minimum_sequence=1,
            )
        self.assertEqual(
            swap.exception.code,
            BackupControlErrorCode.SNAPSHOT_IDENTITY_CONFLICT,
        )
        advanced, _ = reopened.advance_restore_floor(
            uuid_at(720_041),
            uuid_at(720_044),
            3,
            requested_minimum_sequence=1,
        )
        self.assertEqual(advanced.minimum_snapshot_sequence, 3)

    def test_schedule_claim_reuses_pending_reservation_and_advances_without_drift(self) -> None:
        definition = BackupScheduleDefinition(
            uuid_at(720_050),
            self._instance,
            60_000,
            self._clock.now_ms(),
        )
        state = self._store.configure_schedule(definition)
        self.assertEqual(state.revision, 1)
        claim = self._store.claim_due_schedule(
            definition.schedule_id,
            uuid_at(720_051),
            lease_duration_ms=100_000,
        )
        with self.assertRaises(BackupControlError) as leased:
            self._store.claim_due_schedule(
                definition.schedule_id,
                uuid_at(720_052),
                lease_duration_ms=100_000,
            )
        self.assertEqual(leased.exception.code, BackupControlErrorCode.SCHEDULE_LEASED)
        self._store.release_schedule_claim(claim)
        replay = self._store.claim_due_schedule(
            definition.schedule_id,
            uuid_at(720_052),
            lease_duration_ms=100_000,
        )
        self.assertEqual(replay.reservation, claim.reservation)
        forged = BackupScheduleClaim(
            replay.schedule_id,
            replay.claim_token,
            replay.owner_id,
            replay.scheduled_for_ms + 1,
            replay.lease_expires_at_ms,
            replay.reservation,
        )
        with self.assertRaises(BackupControlError) as altered:
            self._store.complete_schedule(forged)
        self.assertEqual(
            altered.exception.code,
            BackupControlErrorCode.SCHEDULE_CONFLICT,
        )
        self._clock.advance(180_001)
        with self.assertRaises(BackupControlError) as expired:
            self._store.complete_schedule(replay)
        self.assertEqual(
            expired.exception.code,
            BackupControlErrorCode.SCHEDULE_CONFLICT,
        )
        replacement = self._store.claim_due_schedule(
            definition.schedule_id,
            uuid_at(720_053),
            lease_duration_ms=300_000,
        )
        self.assertEqual(replacement.reservation, replay.reservation)
        completed = self._store.complete_schedule(replacement)
        self.assertEqual(
            completed.definition.next_due_at_ms,
            definition.next_due_at_ms + 4 * definition.interval_ms,
        )
        self.assertEqual(
            completed.last_completed_snapshot_id,
            claim.reservation.snapshot_id,
        )
        with self.assertRaises(BackupControlError) as not_due:
            self._store.claim_due_schedule(
                definition.schedule_id,
                uuid_at(720_054),
                lease_duration_ms=100_000,
            )
        self.assertEqual(not_due.exception.code, BackupControlErrorCode.SCHEDULE_NOT_DUE)

    def test_schema_tampering_fails_closed_without_path_detail(self) -> None:
        with closing(sqlite3.connect(self._database)) as connection:
            connection.execute("ALTER TABLE restore_floors ADD COLUMN injected TEXT")
        with self.assertRaises(BackupControlError) as invalid:
            SQLiteBackupControlStore(
                self._database,
                self._instance,
                clock=self._clock,
            )
        self.assertEqual(
            invalid.exception.code,
            BackupControlErrorCode.CONTROL_UNAVAILABLE,
        )
        self.assertNotIn(str(self._database), str(invalid.exception))


if __name__ == "__main__":
    unittest.main()
