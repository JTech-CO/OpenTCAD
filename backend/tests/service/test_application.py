from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from backend.app.broker.backup_control import (
    BackupScheduleDefinition,
    SQLiteBackupControlStore,
)
from backend.app.broker.orchestrator import SandboxBroker
from backend.app.broker.sqlite_snapshot import SQLiteOfflineSnapshotManager
from backend.app.broker.sqlite_state import SQLiteJobStateStore
from backend.app.runtime.oci_backend import OciRuntimeBackend
from backend.app.runtime.sqlite_fence_authority import SQLiteRuntimeFenceAuthority
from backend.app.service.application import (
    LocalServiceConfiguration,
    OpenTcadLocalService,
)
from backend.app.service.credentials import InMemoryCredentialStore
from backend.app.service.local_api import LocalApiBind
from backend.app.service.product_composition import ProductDurableBrokerComposition
from backend.tests.runtime.support import ARCHIVE_LIMITS, POLICY
from backend.tests.runtime.test_oci_backend import (
    FakeOciRunner,
    activation_token,
    configuration,
)
from backend.app.runtime.models import RuntimeKind


class DummySnapshotManager(SQLiteOfflineSnapshotManager):
    def __init__(self) -> None:
        pass


class TestNativeCredentialStore(InMemoryCredentialStore):
    @property
    def provider(self) -> str:
        return "test-native"


class LocalProductApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_recovery_precedes_loopback_admission(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            backup_root = root / "backups"
            backup_root.mkdir()
            activation = activation_token()
            authority = SQLiteRuntimeFenceAuthority(root / "fences.sqlite3")
            backend = OciRuntimeBackend(
                configuration(RuntimeKind.DOCKER),
                activation,
                authority,
                runner=FakeOciRunner(RuntimeKind.DOCKER),
            )
            composition = ProductDurableBrokerComposition(
                SandboxBroker(backend, POLICY, ARCHIVE_LIMITS),
                backend,
                SQLiteJobStateStore(root / "state.sqlite3"),
                activation,
            )
            installation_id = str(uuid4())
            control = SQLiteBackupControlStore(
                root / "control.sqlite3",
                installation_id,
            )
            schedule_id = str(uuid4())
            control.configure_schedule(
                BackupScheduleDefinition(
                    schedule_id,
                    installation_id,
                    60_000,
                    9_000_000_000_000,
                ),
            )
            credentials = TestNativeCredentialStore()
            service = OpenTcadLocalService(
                LocalServiceConfiguration(
                    installation_id,
                    str(uuid4()),
                    backup_root,
                    (schedule_id,),
                    LocalApiBind("127.0.0.1", 0),
                ),
                activation,
                composition,
                control,
                DummySnapshotManager(),
                credentials,
            )
            self.assertFalse(service.started)
            await service.start()
            self.assertTrue(service.started)
            self.assertTrue(composition.ready)
            self.assertGreater(service.port, 0)
            self.assertEqual(
                len(credentials.get("opentcad", "local-api-v1")),
                32,
            )
            self.assertEqual(
                len(credentials.get("opentcad", "backup-v1")),
                32,
            )
            await service.close()
            self.assertFalse(service.started)


if __name__ == "__main__":
    unittest.main()
