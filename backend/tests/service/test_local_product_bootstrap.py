from __future__ import annotations

import asyncio
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from backend.app.product.gates import ProductGateError
from backend.app.runtime.models import RuntimeKind
from backend.app.service.bootstrap import M3LocalProductBootstrap, _installation
from backend.app.service.cli import EXIT_BLOCKED, main
from backend.app.service.configuration import LocalUserConfiguration
from backend.app.service.instance import (
    LocalEndpointRecord,
    LocalInstance,
    LocalInstanceAlreadyRunning,
)
from backend.app.service.local_api import LocalApiBind
from backend.app.service.paths import LocalProductPaths
from backend.app.service.static_assets import LocalStaticAssets


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = REPOSITORY_ROOT / "validation" / "manifests" / "m3-entry-gates.json"


def _assets(root: Path) -> LocalStaticAssets:
    root.mkdir()
    (root / "index.html").write_text("<!doctype html><title>OpenTCAD</title>", encoding="utf-8")
    return LocalStaticAssets(root)


class LocalConfigurationAndPathsTests(unittest.TestCase):
    def test_configuration_is_exact_and_rejects_command_injection(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "local.json"
            valid = {
                "schemaVersion": 1,
                "runtimeBackend": "docker",
                "apiPort": 0,
                "backupIntervalMs": 86_400_000,
                "recoveryPageLimit": 100,
            }
            path.write_text(json.dumps(valid), encoding="utf-8")
            value = LocalUserConfiguration.load(path)
            self.assertEqual(value.runtime_backend, RuntimeKind.DOCKER)
            self.assertEqual(value.as_dict(), valid)

            injected = dict(valid, executable="cmd.exe")
            path.write_text(json.dumps(injected), encoding="utf-8")
            with self.assertRaises(ValueError):
                LocalUserConfiguration.load(path)
            path.write_text(
                '{"schemaVersion":1,"schemaVersion":1,"runtimeBackend":"docker",'
                '"apiPort":0,"backupIntervalMs":60000,"recoveryPageLimit":1}',
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                LocalUserConfiguration.load(path)

    def test_platform_layouts_are_per_user_and_explicit(self) -> None:
        home = Path("C:/Users/tester")
        windows = LocalProductPaths.for_platform(
            platform="win32",
            environment={"LOCALAPPDATA": "C:/Users/tester/AppData/Local"},
            home=home,
        )
        self.assertEqual(windows.state_root, Path("C:/Users/tester/AppData/Local/OpenTCAD/state"))
        mac = LocalProductPaths.for_platform(
            platform="darwin",
            environment={},
            home=Path("/Users/tester"),
        )
        self.assertEqual(mac.state_root, Path("/Users/tester/Library/Application Support/OpenTCAD/state"))
        linux = LocalProductPaths.for_platform(
            platform="linux",
            environment={
                "XDG_CONFIG_HOME": "/tmp/config",
                "XDG_STATE_HOME": "/tmp/state",
                "XDG_RUNTIME_DIR": "/tmp/run",
            },
            home=Path("/home/tester"),
        )
        self.assertEqual(linux.config_root, Path("/tmp/config/opentcad"))
        self.assertEqual(linux.runtime_root, Path("/tmp/run/opentcad"))

    def test_single_instance_publishes_no_secret_and_cleans_its_endpoint(self) -> None:
        with TemporaryDirectory() as directory:
            paths = LocalProductPaths.at_root(Path(directory).resolve() / "data")
            paths.prepare()
            first = LocalInstance(paths.instance_lock, paths.endpoint_file)
            second = LocalInstance(paths.instance_lock, paths.endpoint_file)
            first.acquire()
            with self.assertRaises(LocalInstanceAlreadyRunning):
                second.acquire()
            record = LocalEndpointRecord(
                str(uuid4()),
                100,
                8_741,
                "a" * 64,
                "product",
            )
            first.publish(record)
            persisted = json.loads(paths.endpoint_file.read_text(encoding="ascii"))
            self.assertNotIn("token", json.dumps(persisted).casefold())
            self.assertNotIn("browserUrl", persisted)
            first.close()
            self.assertFalse(paths.endpoint_file.exists())
            second.acquire()
            second.close()

    def test_missing_installation_identity_rejects_existing_durable_state(self) -> None:
        with TemporaryDirectory() as directory:
            paths = LocalProductPaths.at_root(Path(directory).resolve() / "data")
            paths.prepare()
            paths.state_database.write_bytes(b"orphaned-state")

            with self.assertRaises(RuntimeError):
                _installation(paths)

            self.assertFalse(paths.installation_file.exists())

    def test_fresh_windows_installation_identity_is_durable_and_stable(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            local_app_data = root / "LocalAppData"

            def windows_paths() -> LocalProductPaths:
                return LocalProductPaths.for_platform(
                    platform="win32",
                    environment={"LOCALAPPDATA": str(local_app_data)},
                    home=root / "home",
                )

            first_paths = windows_paths()
            first_paths.prepare()
            first = _installation(first_paths)
            first_bytes = first_paths.installation_file.read_bytes()
            persisted = json.loads(first_bytes.decode("ascii"))

            self.assertEqual(
                persisted,
                {
                    "credentialsProvisioned": False,
                    "installationId": first.installation_id,
                    "schemaVersion": 1,
                },
            )
            self.assertEqual(str(UUID(first.installation_id)), first.installation_id)
            self.assertTrue(first_bytes.endswith(b"\n"))

            second_paths = windows_paths()
            second = _installation(second_paths)

            self.assertEqual(second.installation_id, first.installation_id)
            self.assertEqual(second_paths.installation_file.read_bytes(), first_bytes)
            self.assertEqual(
                tuple(second_paths.state_root.glob(".installation.json.*.tmp")),
                (),
            )


class LocalBootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_activation_has_no_data_runtime_or_credential_side_effect(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assets = _assets(root / "assets")
            data_root = root / "data"
            called = False

            def credentials():
                nonlocal called
                called = True
                raise AssertionError("credentials must not be touched")

            bootstrap = M3LocalProductBootstrap(REPOSITORY_ROOT, MANIFEST)
            with self.assertRaises(ProductGateError):
                await bootstrap.build_activated(
                    LocalUserConfiguration(RuntimeKind.DOCKER, 0, 60_000, 10),
                    LocalProductPaths.at_root(data_root.resolve()),
                    assets,
                    credential_factory=credentials,
                )
            self.assertFalse(data_root.exists())
            self.assertFalse(called)

    async def test_blocked_preview_serves_assets_and_authenticated_status(self) -> None:
        with TemporaryDirectory() as directory:
            bootstrap = M3LocalProductBootstrap(REPOSITORY_ROOT, MANIFEST)
            host = bootstrap.preview(
                _assets(Path(directory) / "assets"),
                LocalApiBind("127.0.0.1", 0),
            )
            await host.start()
            try:
                token = urlsplit(host.browser_url).fragment.removeprefix("local=")

                async def request(path: str, authorization: str | None = None):
                    reader, writer = await asyncio.open_connection("127.0.0.1", host.port)
                    headers = [f"GET {path} HTTP/1.1", f"Host: localhost:{host.port}"]
                    if authorization is not None:
                        headers.append(f"Authorization: Bearer {authorization}")
                    writer.write(("\r\n".join(headers) + "\r\n\r\n").encode("ascii"))
                    await writer.drain()
                    raw = await reader.read()
                    writer.close()
                    await writer.wait_closed()
                    return raw

                index = await request("/")
                self.assertIn(b"200 OK", index)
                self.assertIn(b"connect-src 'self'", index)
                denied = await request("/v1/status")
                self.assertIn(b"401 Unauthorized", denied)
                status = await request("/v1/status", token)
                self.assertIn(b"200 OK", status)
                payload = json.loads(status.split(b"\r\n\r\n", 1)[1])
                self.assertEqual(payload["executionState"], "blocked")
                self.assertEqual(len(payload["blockedGates"]), 8)
                self.assertIsNone(payload["backend"])
            finally:
                await host.close()

    def test_cli_doctor_succeeds_and_serve_blocks_before_asset_lookup(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            result = main(["doctor"])
        self.assertEqual(result, 0)
        self.assertFalse(json.loads(output.getvalue())["productEnabled"])
        with TemporaryDirectory() as directory:
            output = StringIO()
            with redirect_stdout(output):
                result = main(
                    ["serve", "--assets", str(Path(directory) / "missing")],
                )
            self.assertEqual(result, EXIT_BLOCKED)
            self.assertEqual(json.loads(output.getvalue())["productStarted"], False)


if __name__ == "__main__":
    unittest.main()
