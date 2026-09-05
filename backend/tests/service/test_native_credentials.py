"""Opt-in real OS-store conformance. Never uses product credential identities."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import unittest
from uuid import uuid4

from backend.app.service.anti_rollback import (
    AntiRollbackError, AntiRollbackErrorCode, NativeRestoreFloorStore,
)
from backend.app.service.credentials import (
    CredentialStoreError, CredentialStoreErrorCode, native_credential_store,
)


def _child() -> None:
    """Fresh process, redacted protocol; test secrets travel only through stdin."""
    request = json.loads(sys.stdin.read())
    service = request["service"]
    if not service.startswith("opentcad-m3-probe."):
        raise SystemExit(2)
    store = native_credential_store()
    if request["operation"] == "read-secret":
        value = store.get(service, "binary")
        result = {"digest": sha256(value).hexdigest(), "provider": store.provider}
    elif request["operation"] == "replace-secret":
        store.set(service, "binary", bytes.fromhex(request["value"]))
        result = {"updated": True}
    elif request["operation"] == "floor":
        floor = NativeRestoreFloorStore(store, service=service)
        current = floor.current(request["source"])
        if current is None:
            raise SystemExit(3)
        errors = []
        for sequence, snapshot in ((3, str(uuid4())), (4, str(uuid4()))):
            try:
                floor.advance(request["source"], snapshot, sequence, requested_minimum_sequence=1)
            except AntiRollbackError as error:
                errors.append(error.code.value)
        result = {"floor": current.as_dict(), "errors": errors}
    else:
        raise SystemExit(4)
    print(json.dumps(result))


@unittest.skipUnless(
    os.environ.get("OPENTCAD_NATIVE_CREDENTIAL_TESTS") == "1",
    "opt-in real OS credential store test",
)
class NativeCredentialConformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        # An enabled run must fail, not skip or fall back to DPAPI/memory,
        # when the selected product provider is unavailable or locked.
        self.store = native_credential_store()
        self.service = f"opentcad-m3-probe.{uuid4().hex}"
        self.assertEqual(self.store.provider, {
            "win32": "windows-credential-manager",
            "darwin": "macos-keychain",
            "linux": "linux-secret-service",
        }[sys.platform])

    def reserve(self, credential_id: str) -> None:
        with self.assertRaises(CredentialStoreError) as raised:
            self.store.get(self.service, credential_id)
        self.assertEqual(raised.exception.code, CredentialStoreErrorCode.NOT_FOUND)
        # Register cleanup before the first write. Never enumerate or clear
        # a provider globally, and never touch the real opentcad service.
        self.addCleanup(self.cleanup_owned, credential_id)

    def cleanup_owned(self, credential_id: str) -> None:
        self.store.delete(self.service, credential_id)
        self.store.delete(self.service, credential_id)
        with self.assertRaises(CredentialStoreError) as raised:
            self.store.get(self.service, credential_id)
        self.assertEqual(raised.exception.code, CredentialStoreErrorCode.NOT_FOUND)

    def child(self, operation: str, **values):
        environment = {
            key: os.environ[key]
            for key in ("PATH", "SYSTEMROOT", "WINDIR", "HOME", "USERPROFILE",
                        "TEMP", "TMP", "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR")
            if key in os.environ
        }
        environment.update({"PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        result = subprocess.run(
            (sys.executable, "-c", "from backend.tests.service.test_native_credentials import _child; _child()"),
            input=json.dumps({"service": self.service, "operation": operation, **values}),
            text=True, encoding="utf-8", capture_output=True, timeout=45,
            cwd=Path(__file__).resolve().parents[3], env=environment, check=False,
        )
        self.assertEqual(result.returncode, 0, "native child failed; raw output suppressed")
        return json.loads(result.stdout)

    def test_binary_secret_survives_fresh_process(self) -> None:
        self.reserve("binary")
        value = b"\x00\n\r\xff" + secrets.token_bytes(64)
        self.store.set(self.service, "binary", value)
        result = self.child("read-secret")
        self.assertEqual(result["provider"], self.store.provider)
        self.assertEqual(result["digest"], sha256(value).hexdigest())

    def test_replacement_is_visible_across_processes(self) -> None:
        self.reserve("binary")
        self.store.set(self.service, "binary", secrets.token_bytes(64))
        replacement = secrets.token_bytes(64)
        self.assertEqual(self.child("replace-secret", value=replacement.hex()), {"updated": True})
        self.assertTrue(self.store.get(self.service, "binary") == replacement)
        self.assertEqual(self.child("read-secret")["digest"], sha256(replacement).hexdigest())

    def test_restart_preserves_floor_and_rejects_rollback(self) -> None:
        source, snapshot = str(uuid4()), str(uuid4())
        self.reserve(f"restore-floor.{source}")
        floor = NativeRestoreFloorStore(self.store, service=self.service)
        expected = floor.advance(source, snapshot, 4, requested_minimum_sequence=1)
        result = self.child("floor", source=source)
        self.assertEqual(result["floor"], expected.as_dict())
        self.assertEqual(result["errors"], [
            AntiRollbackErrorCode.ROLLBACK_REJECTED.value,
            AntiRollbackErrorCode.FLOOR_CONFLICT.value,
        ])
        self.assertEqual(floor.current(source), expected)
