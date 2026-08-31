from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit
from uuid import uuid4

from backend.app.broker.backup_control import (
    BackupScheduleDefinition,
    SQLiteBackupControlStore,
)
from backend.app.broker.orchestrator import SandboxBroker
from backend.app.broker.sqlite_snapshot import SQLiteOfflineSnapshotManager
from backend.app.broker.sqlite_state import SQLiteJobStateStore
from backend.app.product.gates import (
    EvidenceRecord,
    GateAttestation,
    M3_GATE_IDS,
    ProductGateReport,
)
from backend.app.runtime.oci_backend import OciRuntimeBackend
from backend.app.runtime.product_fence_authority import ProductRuntimeFenceAuthority
from backend.app.service.application import (
    LocalServiceConfiguration,
    OpenTcadLocalService,
)
from backend.app.service.credentials import InMemoryCredentialStore
from backend.app.service.local_api import LocalApiBind
from backend.app.service.product_composition import ProductDurableBrokerComposition
from backend.app.service.static_assets import LocalStaticAssets
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


def activated_report(activation) -> ProductGateReport:
    evidence = EvidenceRecord("tests/qualified.json", "a" * 64)
    return ProductGateReport(
        activation.manifest_sha256,
        True,
        activation.approval_id,
        tuple(
            GateAttestation(
                gate,
                True,
                "test-reviewer",
                "2026-08-31T00:00:00Z",
                (evidence,),
            )
            for gate in M3_GATE_IDS
        ),
        activation.runtime_grants,
    )


class LocalProductApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_recovery_precedes_loopback_admission(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            backup_root = root / "backups"
            backup_root.mkdir()
            lock_root = root / "locks"
            lock_root.mkdir()
            activation = activation_token()
            authority = ProductRuntimeFenceAuthority(
                root / "fences.sqlite3",
                lock_root,
            )
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
            assets_root = root / "assets"
            assets_root.mkdir()
            (assets_root / "index.html").write_text(
                "<!doctype html><title>OpenTCAD</title>",
                encoding="utf-8",
            )
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
                static_assets=LocalStaticAssets(assets_root),
                status_report=activated_report(activation),
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
            token = urlsplit(service.browser_url).fragment.removeprefix("local=")
            reader, writer = await asyncio.open_connection(
                "127.0.0.1",
                service.port,
            )
            writer.write(
                (
                    "GET /v1/status HTTP/1.1\r\n"
                    f"Host: 127.0.0.1:{service.port}\r\n"
                    f"Authorization: Bearer {token}\r\n"
                    "\r\n"
                ).encode("ascii"),
            )
            await writer.drain()
            response = await reader.read()
            writer.close()
            await writer.wait_closed()
            self.assertIn(b"200 OK", response)
            status = json.loads(response.split(b"\r\n\r\n", 1)[1])
            self.assertEqual(status["executionState"], "authorized")
            self.assertEqual(status["backend"], "docker")
            self.assertEqual(status["blockedGates"], [])
            self.assertEqual(status["recoveryState"], "ready")
            self.assertEqual(status["schedulerState"], "running")
            await service.close()
            self.assertFalse(service.started)


if __name__ == "__main__":
    unittest.main()
