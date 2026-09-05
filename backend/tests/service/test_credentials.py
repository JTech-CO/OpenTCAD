from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from backend.app.service.credentials import (
    CredentialStoreError,
    CredentialStoreErrorCode,
    InMemoryCredentialStore,
    SecretToolCredentialStore,
    WindowsDpapiCredentialStore,
    load_backup_keyring,
    load_or_create_secret,
)


class CredentialStoreTests(unittest.TestCase):
    def test_secret_provisioning_is_stable_and_keyring_is_redacted(self) -> None:
        store = InMemoryCredentialStore()
        first = load_or_create_secret(store, "opentcad", "local-api")
        second = load_or_create_secret(store, "opentcad", "local-api")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 32)
        keyring = load_backup_keyring(store)
        key_id, mac = keyring.sign(b"domain", b"record")
        self.assertTrue(keyring.verify(key_id, b"domain", b"record", mac))
        self.assertNotIn(first.hex(), repr(keyring))

    def test_missing_secret_uses_stable_error(self) -> None:
        with self.assertRaises(CredentialStoreError) as raised:
            InMemoryCredentialStore().get("opentcad", "missing")
        self.assertEqual(raised.exception.code, CredentialStoreErrorCode.NOT_FOUND)

    def test_secret_tool_round_trip_encodes_arbitrary_bytes(self) -> None:
        secret = b"\x00line\nvalue\r\xff"
        stored: bytes | None = None

        with (
            patch("backend.app.service.credentials.sys.platform", "linux"),
            patch(
                "backend.app.service.credentials.shutil.which",
                return_value="/usr/bin/secret-tool",
            ),
        ):
            store = SecretToolCredentialStore()

        def command(arguments, *, input_value=None):
            nonlocal stored
            if arguments[0] == "store":
                stored = input_value
                return subprocess.CompletedProcess(arguments, 0, b"", b"")
            if arguments[0] == "lookup" and stored is not None:
                return subprocess.CompletedProcess(arguments, 0, stored, b"")
            raise AssertionError(arguments)

        store._run = command
        store.set("opentcad", "backup-v1", secret)
        self.assertIsNotNone(stored)
        self.assertNotIn(secret, stored)
        self.assertEqual(store.get("opentcad", "backup-v1"), secret)

    def test_secret_tool_keeps_session_bus_but_not_unrelated_secrets(self) -> None:
        with (
            patch("backend.app.service.credentials.sys.platform", "linux"),
            patch("backend.app.service.credentials.shutil.which", return_value="/usr/bin/secret-tool"),
            patch.dict("os.environ", {
                "PATH": "/usr/bin", "HOME": "/home/probe",
                "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/123/bus",
                "XDG_RUNTIME_DIR": "/run/user/123",
                "UNRELATED_API_TOKEN": "not-in-child", "LD_PRELOAD": "not-in-child",
            }, clear=True),
            patch("backend.app.service.credentials.subprocess.run") as run,
        ):
            store = SecretToolCredentialStore()
            store._run(("lookup", "service", "opentcad", "credential", "probe"))
            environment = run.call_args.kwargs["env"]
            self.assertEqual(environment["DBUS_SESSION_BUS_ADDRESS"], "unix:path=/run/user/123/bus")
            self.assertEqual(environment["XDG_RUNTIME_DIR"], "/run/user/123")
            self.assertEqual(environment["HOME"], "/home/probe")
            self.assertNotIn("UNRELATED_API_TOKEN", environment)
            self.assertNotIn("LD_PRELOAD", environment)

    def test_secret_tool_failure_is_not_a_missing_credential(self) -> None:
        with (
            patch("backend.app.service.credentials.sys.platform", "linux"),
            patch("backend.app.service.credentials.shutil.which", return_value="/usr/bin/secret-tool"),
        ):
            store = SecretToolCredentialStore()
        for status, stderr, expected in (
            (0, b"", CredentialStoreErrorCode.UNAVAILABLE),
            (1, b"", CredentialStoreErrorCode.NOT_FOUND),
            (1, b"session service error", CredentialStoreErrorCode.UNAVAILABLE),
            (2, b"", CredentialStoreErrorCode.UNAVAILABLE),
        ):
            with self.subTest(status=status), patch.object(
                store, "_run", return_value=subprocess.CompletedProcess([], status, b"", stderr),
            ):
                with self.assertRaises(CredentialStoreError) as raised:
                    store.get("opentcad", "probe")
                self.assertEqual(raised.exception.code, expected)

    @unittest.skipUnless(sys.platform == "win32", "Windows DPAPI only")
    def test_windows_dpapi_round_trip_persists_ciphertext_only(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = WindowsDpapiCredentialStore(root)
            secret = b"not-plaintext-in-the-credential-file-" + b"x" * 32
            store.set("opentcad", "backup-v1", secret)
            files = tuple(root.iterdir())
            self.assertEqual(len(files), 1)
            self.assertNotIn(secret, files[0].read_bytes())
            self.assertEqual(store.get("opentcad", "backup-v1"), secret)
            store.delete("opentcad", "backup-v1")
            with self.assertRaises(CredentialStoreError) as raised:
                store.get("opentcad", "backup-v1")
            self.assertEqual(raised.exception.code, CredentialStoreErrorCode.NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
