from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from backend.app.product import (
    M3_GATE_IDS,
    M3ProductGate,
    ProductGateError,
    ProductGateErrorCode,
)
from backend.app.runtime.models import ImageIdentity, RuntimeKind


class M3ProductGateTests(unittest.TestCase):
    def _manifest(self, *, enabled: bool, evidence: list[dict[str, str]]) -> dict:
        approval_id = str(uuid4()) if enabled else None
        reviewer = "release-reviewer" if enabled else None
        approved_at = "2026-08-31T00:00:00Z" if enabled else None
        image = {
            "reference": "registry.invalid/opentcad@sha256:" + "1" * 64,
            "index_digest": "sha256:" + "1" * 64,
            "platform_manifest_digest": "sha256:" + "2" * 64,
            "platform": "linux/amd64",
        }
        return {
            "schemaVersion": 1,
            "productEnabled": enabled,
            "approvalId": approval_id,
            "approvedBy": reviewer,
            "approvedAt": approved_at,
            "gates": [
                {
                    "id": gate.value,
                    "approved": enabled,
                    "approvedBy": reviewer,
                    "approvedAt": approved_at,
                    "evidence": evidence if enabled else [],
                }
                for gate in M3_GATE_IDS
            ],
            "runtime": {
                "grants": (
                    [
                        {
                            "backend": backend,
                            "image": image,
                            "entrypoint": "suprem-reference",
                        }
                        for backend in ("docker", "podman")
                    ]
                    if enabled
                    else []
                ),
            },
        }

    def _write(self, root: Path, value: dict) -> Path:
        path = root / "validation" / "manifests" / "m3-entry-gates.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        return path

    def test_disabled_manifest_is_valid_but_cannot_mint_authority(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            gate = M3ProductGate.load(
                self._write(root, self._manifest(enabled=False, evidence=[])),
                repository_root=root,
            )
            self.assertFalse(gate.report.ready)
            self.assertEqual(gate.report.blocked_gate_ids, M3_GATE_IDS)
            with self.assertRaises(ProductGateError) as raised:
                gate.require_activation()
            self.assertEqual(raised.exception.code, ProductGateErrorCode.PRODUCT_DISABLED)

    def test_complete_attestations_mint_scoped_authority(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            evidence_file = root / "evidence" / "qualification.json"
            evidence_file.parent.mkdir()
            evidence_file.write_bytes(b"qualified")
            evidence = [{
                "path": "evidence/qualification.json",
                "sha256": sha256(b"qualified").hexdigest(),
            }]
            gate = M3ProductGate.load(
                self._write(root, self._manifest(enabled=True, evidence=evidence)),
                repository_root=root,
            )
            token = gate.require_activation()
            image = ImageIdentity(
                "registry.invalid/opentcad@sha256:" + "1" * 64,
                "sha256:" + "1" * 64,
                "sha256:" + "2" * 64,
                "linux/amd64",
            )
            self.assertTrue(token.permits(RuntimeKind.DOCKER, image, "suprem-reference"))
            self.assertTrue(token.permits(RuntimeKind.PODMAN, image, "suprem-reference"))
            self.assertFalse(token.permits(RuntimeKind.MOCK, image, "suprem-reference"))

    def test_evidence_drift_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            evidence_file = root / "evidence.json"
            evidence_file.write_bytes(b"observed")
            evidence = [{"path": "evidence.json", "sha256": "0" * 64}]
            manifest = self._write(root, self._manifest(enabled=True, evidence=evidence))
            with self.assertRaises(ProductGateError) as raised:
                M3ProductGate.load(manifest, repository_root=root)
            self.assertEqual(raised.exception.code, ProductGateErrorCode.EVIDENCE_DRIFT)

    def test_enabled_manifest_cannot_omit_one_gate(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            evidence_file = root / "evidence.json"
            evidence_file.write_bytes(b"qualified")
            evidence = [{
                "path": "evidence.json",
                "sha256": sha256(b"qualified").hexdigest(),
            }]
            value = self._manifest(enabled=True, evidence=evidence)
            value["gates"].pop()
            manifest = self._write(root, value)
            with self.assertRaises(ProductGateError) as raised:
                M3ProductGate.load(manifest, repository_root=root)
            self.assertEqual(raised.exception.code, ProductGateErrorCode.MANIFEST_INVALID)

    def test_noncanonical_approval_time_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            evidence_file = root / "evidence.json"
            evidence_file.write_bytes(b"qualified")
            evidence = [{
                "path": "evidence.json",
                "sha256": sha256(b"qualified").hexdigest(),
            }]
            value = self._manifest(enabled=True, evidence=evidence)
            value["approvedAt"] = "tomorrow"
            manifest = self._write(root, value)
            with self.assertRaises(ProductGateError) as raised:
                M3ProductGate.load(manifest, repository_root=root)
            self.assertEqual(raised.exception.code, ProductGateErrorCode.MANIFEST_INVALID)


if __name__ == "__main__":
    unittest.main()
