"""Authenticated export/import, scheduled backup, and durability contracts."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from backend.app.broker import BrokerState, SQLiteJobStateStore
from backend.app.broker.backup_control import (
    BackupControlError,
    BackupControlErrorCode,
    BackupScheduleDefinition,
    SQLiteBackupControlStore,
)
from backend.app.broker.backup_service import (
    AUTHENTICATED_BACKUP_SERVICE_PRODUCT_ENABLED,
    AUTHENTICATED_EXPORT_RECORD_NAME,
    AUTHENTICATED_EXPORT_SNAPSHOT_DIRECTORY,
    AUTHENTICATED_IMPORT_RECORD_NAME,
    AUTHENTICATED_IMPORT_RESTORE_DIRECTORY,
    AuthenticatedBackupError,
    AuthenticatedBackupErrorCode,
    AuthenticatedExportRequest,
    AuthenticatedImportRequest,
    AuthenticatedSQLiteBackupService,
    BackupServiceCheckpoint,
    HMACBackupKeyring,
    ScheduledSQLiteBackupRunner,
)
from backend.app.broker.durability import (
    DURABLE_PUBLICATION_PRODUCT_ENABLED,
    POWER_LOSS_MIN_REPETITIONS_PER_CUT,
    POWER_LOSS_REQUIRED_CUT_POINTS,
    PowerLossQualificationEvidence,
    publication_profile,
)
from backend.app.broker.sqlite_snapshot import (
    SQLITE_SNAPSHOT_STATE_NAME,
    SQLiteOfflineSnapshotManager,
)
from backend.app.runtime import (
    RuntimeKind,
    RuntimePhase,
    SQLiteRuntimeFenceAuthority,
)
from backend.tests.broker.backup_service_child import (
    HARD_EXIT_CODE,
    TEST_KEY,
    TEST_KEY_ID,
)
from backend.tests.broker.lease_support import ManualLeaseClock
from backend.tests.broker.state_store_conformance import conformance_event, uuid_at


class AuthenticatedSQLiteBackupServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self._root = Path(self._temporary.name)
        self._state = self._root / "source-state.sqlite3"
        self._authority = self._root / "source-authority.sqlite3"
        self._control_path = self._root / "backup-control.sqlite3"
        self._instance = uuid_at(730_001)
        self._snapshot = uuid_at(730_002)
        self._clock = ManualLeaseClock()
        self._control = SQLiteBackupControlStore(
            self._control_path,
            self._instance,
            clock=self._clock,
        )
        self._keyring = HMACBackupKeyring(
            TEST_KEY_ID,
            {TEST_KEY_ID: TEST_KEY},
        )
        self._manager = SQLiteOfflineSnapshotManager(self._state, self._authority)
        self._service = AuthenticatedSQLiteBackupService(
            self._manager,
            self._control,
            self._keyring,
        )

    def tearDown(self) -> None:
        self._temporary.cleanup()

    async def seed_pair(self):
        store = SQLiteJobStateStore(self._state, clock=self._clock)
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
                    job=730,
                    event_number=730_100 + sequence,
                    operation=730,
                    operation_sequence=sequence,
                    state=state,
                    phase=phase,
                    lease_duration_ms=2,
                ),
                expected_revision=sequence - 1,
            )
        authority = SQLiteRuntimeFenceAuthority(self._authority)
        await authority.activate(
            snapshot.ownership.runtime_fence,
            phase=RuntimePhase.WAIT,
            backend=RuntimeKind.MOCK,
        )
        return snapshot

    def export_request(
        self,
        *,
        snapshot: int = 730_002,
        maintenance: int = 730_003,
        owner: int = 730_004,
        quiescence: int = 730_005,
    ) -> AuthenticatedExportRequest:
        return AuthenticatedExportRequest(
            uuid_at(snapshot),
            self._instance,
            uuid_at(maintenance),
            uuid_at(owner),
            uuid_at(quiescence),
            60_000,
        )

    def import_request(
        self,
        snapshot_id: str,
        *,
        minimum: int,
        maintenance: int = 730_006,
        owner: int = 730_007,
        quiescence: int = 730_008,
    ) -> AuthenticatedImportRequest:
        return AuthenticatedImportRequest(
            snapshot_id,
            self._instance,
            minimum,
            uuid_at(maintenance),
            uuid_at(owner),
            uuid_at(quiescence),
            60_000,
        )

    async def test_authenticated_round_trip_and_fresh_adapter_reopen(self) -> None:
        seeded = await self.seed_pair()
        export_path = self._root / "authenticated-export"
        exported = self._service.create_export(
            self.export_request(),
            export_path,
        )
        self.assertFalse(AUTHENTICATED_BACKUP_SERVICE_PRODUCT_ENABLED)
        self.assertEqual(exported.reservation.snapshot_sequence, 1)
        self.assertTrue(exported.reservation.exported)
        self.assertEqual(
            frozenset(path.name for path in export_path.iterdir()),
            {
                AUTHENTICATED_EXPORT_RECORD_NAME,
                AUTHENTICATED_EXPORT_SNAPSHOT_DIRECTORY,
            },
        )
        self.assertEqual(
            self._service.validate_export(export_path),
            (exported.record, exported.snapshot),
        )

        import_path = self._root / "authenticated-import"
        imported = self._service.import_export(
            export_path,
            import_path,
            self.import_request(exported.snapshot.snapshot_id, minimum=1),
        )
        self.assertEqual(imported.floor.minimum_snapshot_sequence, 1)
        self.assertEqual(
            frozenset(path.name for path in import_path.iterdir()),
            {
                AUTHENTICATED_IMPORT_RECORD_NAME,
                AUTHENTICATED_IMPORT_RESTORE_DIRECTORY,
            },
        )
        self.assertEqual(
            self._service.validate_import(
                import_path,
                expected_snapshot_id=exported.snapshot.snapshot_id,
                expected_source_instance_id=self._instance,
            ),
            imported.record,
        )
        restored_store = SQLiteJobStateStore(
            imported.restore.state_database,
            clock=self._clock,
        )
        restored_authority = SQLiteRuntimeFenceAuthority(
            imported.restore.authority_database,
        )
        self.assertEqual(await restored_store.load(seeded.identity), seeded)
        self.assertEqual(
            await restored_authority.current(seeded.identity.job_id),
            seeded.ownership.runtime_fence,
        )
        admission = self._control.admit_operation(
            uuid_at(730_009),
            uuid_at(730_010),
            lease_duration_ms=10_000,
        )
        self._control.release_operation(admission)

    async def test_tampering_unknown_key_and_extra_entry_fail_closed(self) -> None:
        await self.seed_pair()
        original = self._root / "original"
        self._service.create_export(self.export_request(), original)

        unknown = AuthenticatedSQLiteBackupService(
            self._manager,
            self._control,
            HMACBackupKeyring("other", {"other": b"x" * 32}),
        )
        with self.assertRaises(AuthenticatedBackupError) as wrong_key:
            unknown.validate_export(original)
        self.assertEqual(
            wrong_key.exception.code,
            AuthenticatedBackupErrorCode.AUTHENTICATION_FAILED,
        )

        payload_tamper = self._root / "payload-tamper"
        shutil.copytree(original, payload_tamper)
        with (
            payload_tamper
            / AUTHENTICATED_EXPORT_SNAPSHOT_DIRECTORY
            / SQLITE_SNAPSHOT_STATE_NAME
        ).open("ab") as stream:
            stream.write(b"tamper")
        with self.assertRaises(AuthenticatedBackupError) as payload:
            self._service.validate_export(payload_tamper)
        self.assertEqual(
            payload.exception.code,
            AuthenticatedBackupErrorCode.AUTHENTICATION_FAILED,
        )

        record_tamper = self._root / "record-tamper"
        shutil.copytree(original, record_tamper)
        record_path = record_tamper / AUTHENTICATED_EXPORT_RECORD_NAME
        value = json.loads(record_path.read_text(encoding="utf-8"))
        value["snapshot_sequence"] = 2
        record_path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(AuthenticatedBackupError) as record:
            self._service.validate_export(record_tamper)
        self.assertEqual(
            record.exception.code,
            AuthenticatedBackupErrorCode.AUTHENTICATION_FAILED,
        )

        extra = self._root / "extra"
        shutil.copytree(original, extra)
        (extra / "unexpected.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(AuthenticatedBackupError) as unexpected:
            self._service.validate_export(extra)
        self.assertEqual(
            unexpected.exception.code,
            AuthenticatedBackupErrorCode.EXPORT_INCOMPLETE,
        )
        for error in (wrong_key.exception, payload.exception, record.exception):
            self.assertNotIn(str(original), str(error))
            self.assertNotIn(TEST_KEY.decode("ascii"), repr(error))

        collision_request = self.export_request(
            snapshot=730_090,
            maintenance=730_091,
            owner=730_092,
            quiescence=730_093,
        )
        collision_destination = self._root / "owned-by-caller"
        collision_stage = self._root / (
            f".owned-by-caller.{collision_request.snapshot_id}.export-staging"
        )
        collision_stage.mkdir()
        sentinel = collision_stage / "do-not-delete.txt"
        sentinel.write_text("caller-owned", encoding="utf-8")
        with self.assertRaises(AuthenticatedBackupError) as collision:
            self._service.create_export(
                collision_request,
                collision_destination,
            )
        self.assertEqual(
            collision.exception.code,
            AuthenticatedBackupErrorCode.DESTINATION_EXISTS,
        )
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "caller-owned")

    async def test_durable_floor_rejects_older_valid_authenticated_export(self) -> None:
        await self.seed_pair()
        first = self._service.create_export(
            self.export_request(),
            self._root / "export-1",
        )
        second = self._service.create_export(
            self.export_request(
                snapshot=730_011,
                maintenance=730_012,
                owner=730_013,
                quiescence=730_014,
            ),
            self._root / "export-2",
        )
        self.assertEqual(
            (first.snapshot.snapshot_sequence, second.snapshot.snapshot_sequence),
            (1, 2),
        )
        self._service.import_export(
            self._root / "export-2",
            self._root / "restore-2",
            self.import_request(
                second.snapshot.snapshot_id,
                minimum=1,
                maintenance=730_015,
                owner=730_016,
                quiescence=730_017,
            ),
        )
        with self.assertRaises(AuthenticatedBackupError) as rollback:
            self._service.import_export(
                self._root / "export-1",
                self._root / "restore-1",
                self.import_request(
                    first.snapshot.snapshot_id,
                    minimum=1,
                    maintenance=730_018,
                    owner=730_019,
                    quiescence=730_020,
                ),
            )
        self.assertEqual(
            rollback.exception.code,
            AuthenticatedBackupErrorCode.ROLLBACK_REJECTED,
        )
        self.assertFalse((self._root / "restore-1").exists())

    async def test_active_admission_prevents_export_until_released(self) -> None:
        await self.seed_pair()
        admission = self._control.admit_operation(
            uuid_at(730_021),
            uuid_at(730_022),
            lease_duration_ms=60_000,
        )
        destination = self._root / "blocked-export"
        with self.assertRaises(AuthenticatedBackupError) as blocked:
            self._service.create_export(self.export_request(), destination)
        self.assertEqual(
            blocked.exception.code,
            AuthenticatedBackupErrorCode.MAINTENANCE_FAILED,
        )
        self.assertFalse(destination.exists())
        self._control.release_operation(admission)
        result = self._service.create_export(self.export_request(), destination)
        self.assertEqual(result.snapshot.snapshot_sequence, 1)

    async def test_scheduled_runner_persists_claim_and_completed_occurrence(self) -> None:
        await self.seed_pair()
        backup_root = self._root / "scheduled"
        backup_root.mkdir()
        definition = BackupScheduleDefinition(
            uuid_at(730_030),
            self._instance,
            60_000,
            self._clock.now_ms(),
        )
        self._control.configure_schedule(definition)
        result = ScheduledSQLiteBackupRunner(
            self._service,
            self._control,
            backup_root,
        ).run_due(
            definition.schedule_id,
            uuid_at(730_031),
            lease_duration_ms=60_000,
        )
        self.assertTrue(result.export.destination.is_dir())
        self.assertEqual(result.schedule.last_completed_sequence, 1)
        self.assertIsNone(result.schedule.pending_snapshot_id)
        reopened = SQLiteBackupControlStore(
            self._control_path,
            self._instance,
            clock=self._clock,
        )
        self.assertEqual(
            reopened.current_schedule(definition.schedule_id),
            result.schedule,
        )
        with self.assertRaises(BackupControlError) as not_due:
            ScheduledSQLiteBackupRunner(
                self._service,
                self._control,
                backup_root,
            ).run_due(
                definition.schedule_id,
                uuid_at(730_032),
                lease_duration_ms=60_000,
            )
        self.assertEqual(not_due.exception.code, BackupControlErrorCode.SCHEDULE_NOT_DUE)

    async def test_four_process_hard_exits_preserve_publication_and_floor_invariants(self) -> None:
        await self.seed_pair()

        async def child(*arguments: str):
            return await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-m", "backend.tests.broker.backup_service_child", *arguments],
                cwd=Path.cwd(),
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )

        first_request = self.export_request()
        before_publish = self._root / "crash-before-export"
        first = await child(
            "export",
            str(self._state),
            str(self._authority),
            str(self._control_path),
            str(before_publish),
            first_request.snapshot_id,
            self._instance,
            first_request.maintenance_id,
            first_request.owner_id,
            first_request.quiescence_id,
            BackupServiceCheckpoint.AFTER_SEQUENCE_RESERVED.value,
        )
        self.assertEqual(first.returncode, HARD_EXIT_CODE, msg=first.stderr)
        self.assertFalse(before_publish.exists())
        recovered_export = self._service.create_export(first_request, before_publish)
        self.assertEqual(recovered_export.snapshot.snapshot_sequence, 1)

        second_request = self.export_request(
            snapshot=730_040,
            maintenance=730_041,
            owner=730_042,
            quiescence=730_043,
        )
        after_publish = self._root / "crash-after-export"
        second = await child(
            "export",
            str(self._state),
            str(self._authority),
            str(self._control_path),
            str(after_publish),
            second_request.snapshot_id,
            self._instance,
            second_request.maintenance_id,
            second_request.owner_id,
            second_request.quiescence_id,
            BackupServiceCheckpoint.AFTER_EXPORT_PUBLISH.value,
        )
        self.assertEqual(second.returncode, HARD_EXIT_CODE, msg=second.stderr)
        self.assertTrue(after_publish.is_dir())
        recovered_after_publish = self._service.create_export(
            second_request,
            after_publish,
        )
        self.assertEqual(recovered_after_publish.snapshot.snapshot_sequence, 2)

        before_import = self._root / "crash-before-import"
        import_before_request = self.import_request(
            second_request.snapshot_id,
            minimum=2,
            maintenance=730_044,
            owner=730_045,
            quiescence=730_046,
        )
        third = await child(
            "import",
            str(self._state),
            str(self._authority),
            str(self._control_path),
            str(after_publish),
            str(before_import),
            second_request.snapshot_id,
            self._instance,
            import_before_request.maintenance_id,
            import_before_request.owner_id,
            import_before_request.quiescence_id,
            "2",
            BackupServiceCheckpoint.AFTER_RESTORE_FLOOR_ADVANCE.value,
        )
        self.assertEqual(third.returncode, HARD_EXIT_CODE, msg=third.stderr)
        self.assertFalse(before_import.exists())
        self.assertEqual(
            SQLiteBackupControlStore(
                self._control_path,
                self._instance,
            ).current_restore_floor(self._instance).minimum_snapshot_sequence,
            2,
        )
        recovered_import = self._service.import_export(
            after_publish,
            before_import,
            import_before_request,
        )
        self.assertEqual(recovered_import.floor.minimum_snapshot_sequence, 2)

        after_import = self._root / "crash-after-import"
        import_after_request = self.import_request(
            second_request.snapshot_id,
            minimum=2,
            maintenance=730_047,
            owner=730_048,
            quiescence=730_049,
        )
        fourth = await child(
            "import",
            str(self._state),
            str(self._authority),
            str(self._control_path),
            str(after_publish),
            str(after_import),
            second_request.snapshot_id,
            self._instance,
            import_after_request.maintenance_id,
            import_after_request.owner_id,
            import_after_request.quiescence_id,
            "2",
            BackupServiceCheckpoint.AFTER_IMPORT_PUBLISH.value,
        )
        self.assertEqual(fourth.returncode, HARD_EXIT_CODE, msg=fourth.stderr)
        self.assertTrue(after_import.is_dir())
        replayed = self._service.import_export(
            after_publish,
            after_import,
            import_after_request,
        )
        self.assertEqual(replayed.record.snapshot_sequence, 2)

    def test_power_loss_evidence_never_infers_qualification_from_process_exit(self) -> None:
        self.assertFalse(DURABLE_PUBLICATION_PRODUCT_ENABLED)
        self.assertFalse(publication_profile().external_power_loss_qualified)
        process_exit_only = PowerLossQualificationEvidence(
            uuid_at(730_060),
            sys.platform,
            "test-filesystem",
            "test-device",
            POWER_LOSS_REQUIRED_CUT_POINTS,
            POWER_LOSS_MIN_REPETITIONS_PER_CUT,
            abrupt_power_cut=False,
            write_cache_configuration_recorded=True,
            every_reboot_completed=True,
            partial_publications=0,
            sqlite_integrity_failures=0,
            rollback_violations=0,
        )
        self.assertFalse(process_exit_only.qualified)
        self.assertNotIn(TEST_KEY.decode("ascii"), repr(self._keyring))


if __name__ == "__main__":
    unittest.main()
