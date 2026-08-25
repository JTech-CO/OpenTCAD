"""Coordinated offline SQLite snapshot, restore, and crash-seam contracts."""

from __future__ import annotations

import asyncio
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from backend.app.broker import (
    BrokerState,
    CrashRecoveryCoordinator,
    DurableRuntimeFenceActivator,
    RecoveryRequest,
    RecoveryStatus,
    ReconciliationReport,
    SQLiteJobStateStore,
)
from backend.app.broker.sqlite_snapshot import (
    SQLITE_OFFLINE_SNAPSHOT_LIVE_WRITES_SUPPORTED,
    SQLITE_OFFLINE_SNAPSHOT_PRODUCT_ENABLED,
    SQLITE_OFFLINE_SNAPSHOT_SCHEMA_VERSION,
    SQLITE_RESTORE_RECORD_NAME,
    SQLITE_SNAPSHOT_AUTHORITY_NAME,
    SQLITE_SNAPSHOT_MANIFEST_NAME,
    SQLITE_SNAPSHOT_STATE_NAME,
    SQLiteOfflineSnapshotManager,
    SQLiteOfflineSnapshotRequest,
    SQLiteSnapshotError,
    SQLiteSnapshotErrorCode,
    SQLiteSnapshotQuiescence,
    SQLiteSnapshotRestorePolicy,
)
from backend.app.runtime import (
    RuntimeKind,
    RuntimePhase,
    SQLiteRuntimeFenceAuthority,
)
from backend.tests.broker.lease_support import ManualLeaseClock
from backend.tests.broker.sqlite_snapshot_child import HARD_EXIT_CODE
from backend.tests.broker.state_store_conformance import conformance_event, uuid_at


def canonical_json(value) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


class RestoredReconciler:
    def __init__(self, authority: SQLiteRuntimeFenceAuthority) -> None:
        self.authority = authority
        self.calls = 0

    async def reconcile(self, job_id=None, *, ownership_guard=None):
        self.calls += 1
        if job_id is None or ownership_guard is None:
            raise AssertionError("restored recovery must retain exact ownership")
        current = await self.authority.current(job_id)
        if current != ownership_guard.runtime_fence:
            raise AssertionError("restored authority must activate before cleanup")
        return ReconciliationReport(0, 0, 0, 0, 0, 0, ())


class SQLiteOfflineSnapshotContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self._root = Path(self._temporary.name)
        self._state = self._root / "source-state.sqlite3"
        self._authority = self._root / "source-authority.sqlite3"
        self._source_instance_id = uuid_at(710_001)
        self._snapshot_id = uuid_at(710_002)
        self._quiescence_id = uuid_at(710_003)
        self._job = 710

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def quiescence(self, *, stopped: bool = True, number: int = 710_003):
        return SQLiteSnapshotQuiescence(
            uuid_at(number),
            stopped,
            stopped,
            stopped,
        )

    def request(
        self,
        *,
        snapshot_id: str | None = None,
        sequence: int = 7,
        quiescence: SQLiteSnapshotQuiescence | None = None,
    ) -> SQLiteOfflineSnapshotRequest:
        return SQLiteOfflineSnapshotRequest(
            snapshot_id or self._snapshot_id,
            self._source_instance_id,
            sequence,
            quiescence or self.quiescence(),
        )

    def policy(
        self,
        *,
        snapshot_id: str | None = None,
        source_instance_id: str | None = None,
        minimum_sequence: int = 7,
    ) -> SQLiteSnapshotRestorePolicy:
        return SQLiteSnapshotRestorePolicy(
            snapshot_id or self._snapshot_id,
            source_instance_id or self._source_instance_id,
            minimum_sequence,
        )

    async def seed_pair(self):
        clock = ManualLeaseClock()
        store = SQLiteJobStateStore(self._state, clock=clock)
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
                    job=self._job,
                    event_number=710_100 + sequence,
                    operation=self._job,
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
        return store, authority, snapshot

    async def test_round_trip_restores_pair_and_recovery_advances_generation(self) -> None:
        _, _, seeded = await self.seed_pair()
        bundle = self._root / "snapshot-bundle"
        manager = SQLiteOfflineSnapshotManager(self._state, self._authority)
        manifest = manager.create_bundle(self.request(), bundle)
        self.assertEqual(
            tuple(path.name for path in sorted(bundle.iterdir())),
            (
                SQLITE_SNAPSHOT_STATE_NAME,
                SQLITE_SNAPSHOT_AUTHORITY_NAME,
                SQLITE_SNAPSHOT_MANIFEST_NAME,
            ),
        )
        self.assertEqual(
            manager.validate_bundle(bundle, self.policy()),
            manifest,
        )

        restored_root = self._root / "restored"
        result = manager.restore_bundle(
            bundle,
            restored_root,
            self.policy(),
            self.quiescence(number=710_004),
        )
        self.assertEqual(result.state_database.parent, restored_root)
        self.assertTrue(result.restore_record.is_file())
        self.assertEqual(
            frozenset(path.name for path in restored_root.iterdir()),
            {
                SQLITE_SNAPSHOT_STATE_NAME,
                SQLITE_SNAPSHOT_AUTHORITY_NAME,
                SQLITE_RESTORE_RECORD_NAME,
            },
        )

        restored_store = SQLiteJobStateStore(
            result.state_database,
            clock=ManualLeaseClock(2_000_000),
        )
        restored_authority = SQLiteRuntimeFenceAuthority(result.authority_database)
        self.assertEqual(await restored_store.load(seeded.identity), seeded)
        self.assertEqual(
            await restored_authority.current(seeded.identity.job_id),
            seeded.ownership.runtime_fence,
        )
        reconciler = RestoredReconciler(restored_authority)
        report = await CrashRecoveryCoordinator(
            restored_store,
            reconciler,
            RuntimeKind.MOCK,
            fence_activator=DurableRuntimeFenceActivator(
                restored_store,
                restored_authority,
                RuntimeKind.MOCK,
            ),
        ).recover(RecoveryRequest(uuid_at(710_005), limit=1))
        final = await restored_store.load(seeded.identity)
        self.assertEqual(reconciler.calls, 1)
        self.assertEqual(report.items[0].status, RecoveryStatus.RECOVERED_FAILED)
        self.assertEqual(final.ownership.fencing_token, 2)
        self.assertEqual(
            (await restored_authority.current(seeded.identity.job_id)).fencing_token,
            2,
        )

    async def test_contract_is_offline_product_disabled_and_path_redacted(self) -> None:
        await self.seed_pair()
        manager = SQLiteOfflineSnapshotManager(self._state, self._authority)
        self.assertFalse(SQLITE_OFFLINE_SNAPSHOT_PRODUCT_ENABLED)
        self.assertFalse(SQLITE_OFFLINE_SNAPSHOT_LIVE_WRITES_SUPPORTED)
        self.assertEqual(SQLITE_OFFLINE_SNAPSHOT_SCHEMA_VERSION, 1)
        self.assertNotIn(str(self._state), repr(manager))
        with self.assertRaises(SQLiteSnapshotError) as offline:
            manager.create_bundle(
                self.request(quiescence=self.quiescence(stopped=False)),
                self._root / "not-offline",
            )
        self.assertEqual(offline.exception.code, SQLiteSnapshotErrorCode.OFFLINE_REQUIRED)
        self.assertEqual(offline.exception.as_dict(), {"code": "offline-required"})
        self.assertNotIn(str(self._state), str(offline.exception))

    async def test_torn_extra_and_tampered_bundles_fail_closed(self) -> None:
        await self.seed_pair()
        manager = SQLiteOfflineSnapshotManager(self._state, self._authority)
        torn = self._root / "torn"
        torn.mkdir()
        shutil.copyfile(self._state, torn / SQLITE_SNAPSHOT_STATE_NAME)
        with self.assertRaises(SQLiteSnapshotError) as incomplete:
            manager.validate_bundle(torn)
        self.assertEqual(
            incomplete.exception.code,
            SQLiteSnapshotErrorCode.BUNDLE_INCOMPLETE,
        )

        bundle = self._root / "tampered"
        manager.create_bundle(self.request(), bundle)
        with (bundle / SQLITE_SNAPSHOT_STATE_NAME).open("r+b") as stream:
            stream.seek(-1, 2)
            final = stream.read(1)
            stream.seek(-1, 2)
            stream.write(bytes((final[0] ^ 1,)))
        with self.assertRaises(SQLiteSnapshotError) as tampered:
            manager.validate_bundle(bundle)
        self.assertEqual(
            tampered.exception.code,
            SQLiteSnapshotErrorCode.BUNDLE_INTEGRITY_FAILED,
        )

        extra_bundle = self._root / "extra"
        snapshot_id = uuid_at(710_006)
        manager.create_bundle(
            self.request(snapshot_id=snapshot_id, sequence=8),
            extra_bundle,
        )
        (extra_bundle / "unexpected.txt").write_text("unexpected", encoding="utf-8")
        with self.assertRaises(SQLiteSnapshotError) as extra:
            manager.validate_bundle(extra_bundle)
        self.assertEqual(extra.exception.code, SQLiteSnapshotErrorCode.BUNDLE_INCOMPLETE)

        corrupt_bundle = self._root / "corrupt-row"
        manager.create_bundle(
            self.request(snapshot_id=uuid_at(710_014), sequence=9),
            corrupt_bundle,
        )
        corrupt_authority = corrupt_bundle / SQLITE_SNAPSHOT_AUTHORITY_NAME
        with closing(sqlite3.connect(corrupt_authority)) as connection:
            connection.execute(
                "UPDATE runtime_fences SET owner_id = 'not-a-uuid'",
            )
            connection.commit()
        corrupt_manifest_path = corrupt_bundle / SQLITE_SNAPSHOT_MANIFEST_NAME
        corrupt_manifest = json.loads(
            corrupt_manifest_path.read_text(encoding="utf-8"),
        )
        corrupt_record = next(
            item
            for item in corrupt_manifest["files"]
            if item["role"] == "runtime-fence-authority"
        )
        corrupt_payload = corrupt_authority.read_bytes()
        corrupt_record["bytes"] = len(corrupt_payload)
        corrupt_record["sha256"] = sha256(corrupt_payload).hexdigest()
        corrupt_manifest_path.write_bytes(canonical_json(corrupt_manifest))
        with self.assertRaises(SQLiteSnapshotError) as corrupt:
            manager.validate_bundle(corrupt_bundle)
        self.assertEqual(
            corrupt.exception.code,
            SQLiteSnapshotErrorCode.BUNDLE_INTEGRITY_FAILED,
        )

    async def test_mixed_pair_with_authority_ahead_is_rejected_after_rehash(self) -> None:
        store, authority, running = await self.seed_pair()
        manager = SQLiteOfflineSnapshotManager(self._state, self._authority)
        older = self._root / "older"
        manager.create_bundle(self.request(), older)

        takeover = await store.append(
            conformance_event(
                job=self._job,
                event_number=710_200,
                operation=711,
                operation_sequence=1,
                state=BrokerState.CANCELLING,
                phase=RuntimePhase.QUERY,
                fencing_token=2,
            ),
            expected_revision=running.revision,
        )
        await authority.activate(
            takeover.ownership.runtime_fence,
            phase=RuntimePhase.QUERY,
            backend=RuntimeKind.MOCK,
        )
        newer = self._root / "newer"
        manager.create_bundle(
            self.request(snapshot_id=uuid_at(710_007), sequence=8),
            newer,
        )

        mixed_authority = older / SQLITE_SNAPSHOT_AUTHORITY_NAME
        shutil.copyfile(newer / SQLITE_SNAPSHOT_AUTHORITY_NAME, mixed_authority)
        manifest_path = older / SQLITE_SNAPSHOT_MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        record = next(
            item
            for item in manifest["files"]
            if item["role"] == "runtime-fence-authority"
        )
        payload = mixed_authority.read_bytes()
        record["bytes"] = len(payload)
        record["sha256"] = sha256(payload).hexdigest()
        manifest_path.write_bytes(canonical_json(manifest))

        with self.assertRaises(SQLiteSnapshotError) as mixed:
            manager.validate_bundle(older)
        self.assertEqual(
            mixed.exception.code,
            SQLiteSnapshotErrorCode.STATE_AUTHORITY_CONFLICT,
        )

    async def test_restore_requires_identity_floor_and_fresh_destination(self) -> None:
        await self.seed_pair()
        manager = SQLiteOfflineSnapshotManager(self._state, self._authority)
        bundle = self._root / "policy-bundle"
        manager.create_bundle(self.request(), bundle)
        with self.assertRaises(SQLiteSnapshotError) as identity:
            manager.validate_bundle(
                bundle,
                self.policy(snapshot_id=uuid_at(710_008)),
            )
        self.assertEqual(
            identity.exception.code,
            SQLiteSnapshotErrorCode.SNAPSHOT_IDENTITY_MISMATCH,
        )
        with self.assertRaises(SQLiteSnapshotError) as rollback:
            manager.validate_bundle(
                bundle,
                self.policy(minimum_sequence=8),
            )
        self.assertEqual(
            rollback.exception.code,
            SQLiteSnapshotErrorCode.SNAPSHOT_ROLLBACK_REJECTED,
        )

        destination = self._root / "fresh-only"
        manager.restore_bundle(
            bundle,
            destination,
            self.policy(),
            self.quiescence(number=710_009),
        )
        with self.assertRaises(SQLiteSnapshotError) as existing:
            manager.restore_bundle(
                bundle,
                destination,
                self.policy(),
                self.quiescence(number=710_010),
            )
        self.assertEqual(
            existing.exception.code,
            SQLiteSnapshotErrorCode.RESTORE_TARGET_EXISTS,
        )

    async def test_locked_and_unknown_sources_fail_with_redacted_codes(self) -> None:
        await self.seed_pair()
        manager = SQLiteOfflineSnapshotManager(
            self._state,
            self._authority,
            busy_timeout_ms=25,
        )
        lock = sqlite3.connect(self._state, timeout=0, isolation_level=None)
        try:
            lock.execute("BEGIN IMMEDIATE")
            with self.assertRaises(SQLiteSnapshotError) as unavailable:
                manager.create_bundle(self.request(), self._root / "locked")
        finally:
            lock.rollback()
            lock.close()
        self.assertEqual(
            unavailable.exception.code,
            SQLiteSnapshotErrorCode.SOURCE_UNAVAILABLE,
        )
        self.assertNotIn(str(self._state), str(unavailable.exception))

        invalid_state = self._root / "invalid-state.sqlite3"
        with closing(sqlite3.connect(invalid_state)) as connection:
            connection.execute("CREATE TABLE unexpected (value TEXT)")
            connection.execute("PRAGMA user_version = 99")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.commit()
        invalid = SQLiteOfflineSnapshotManager(invalid_state, self._authority)
        with self.assertRaises(SQLiteSnapshotError) as schema:
            invalid.create_bundle(
                self.request(snapshot_id=uuid_at(710_011), sequence=8),
                self._root / "bad-schema",
            )
        self.assertEqual(
            schema.exception.code,
            SQLiteSnapshotErrorCode.SOURCE_SCHEMA_MISMATCH,
        )

    async def test_hard_exit_never_publishes_partial_bundle_or_restore(self) -> None:
        await self.seed_pair()
        repository = Path(__file__).resolve().parents[3]
        create_target = self._root / "crashed-create"
        create = await asyncio.to_thread(
            subprocess.run,
            [
                sys.executable,
                "-m",
                "backend.tests.broker.sqlite_snapshot_child",
                "create",
                str(self._state),
                str(self._authority),
                str(create_target),
                self._snapshot_id,
                self._source_instance_id,
                "7",
                self._quiescence_id,
                "after-authority-backup",
            ],
            cwd=repository,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(
            create.returncode,
            HARD_EXIT_CODE,
            msg=f"stdout={create.stdout!r} stderr={create.stderr!r}",
        )
        self.assertFalse(create_target.exists())
        with self.assertRaises(SQLiteSnapshotError) as unpublished:
            SQLiteOfflineSnapshotManager.validate_bundle(create_target)
        self.assertEqual(
            unpublished.exception.code,
            SQLiteSnapshotErrorCode.BUNDLE_INCOMPLETE,
        )

        manager = SQLiteOfflineSnapshotManager(self._state, self._authority)
        good_bundle = self._root / "good-bundle"
        good_snapshot_id = uuid_at(710_012)
        manager.create_bundle(
            self.request(snapshot_id=good_snapshot_id, sequence=8),
            good_bundle,
        )
        restore_target = self._root / "crashed-restore"
        restore = await asyncio.to_thread(
            subprocess.run,
            [
                sys.executable,
                "-m",
                "backend.tests.broker.sqlite_snapshot_child",
                "restore",
                str(good_bundle),
                str(restore_target),
                good_snapshot_id,
                self._source_instance_id,
                "8",
                uuid_at(710_013),
                "after-state-restore",
            ],
            cwd=repository,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(
            restore.returncode,
            HARD_EXIT_CODE,
            msg=f"stdout={restore.stdout!r} stderr={restore.stderr!r}",
        )
        self.assertFalse(restore_target.exists())


if __name__ == "__main__":
    unittest.main()
