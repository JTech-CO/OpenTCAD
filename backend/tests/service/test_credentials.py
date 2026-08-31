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
