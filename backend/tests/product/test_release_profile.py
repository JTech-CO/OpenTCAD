from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from backend.app.broker.archive import ArchiveLimits
from backend.app.product import M3_GATE_IDS, M3ProductGate, ProductReleaseProfile
from backend.app.runtime.models import (
    ImageIdentity,
    JobKind,
    ResourceLimits,
    RuntimeKind,
)
from backend.app.runtime.oci_backend import OciAdapterConfiguration, OciEntrypoint
from backend.app.runtime.policy import EngineProfile, SandboxPolicy


def _image_record(image: ImageIdentity) -> dict[str, str]:
    return {
        "reference": image.reference,
        "index_digest": image.index_digest,
        "platform_manifest_digest": image.platform_manifest_digest,
        "platform": image.platform,
    }


class ProductReleaseProfileTests(unittest.TestCase):
    def test_distinct_transfer_and_engine_images_are_activated_by_exact_grants(
        self,
    ) -> None:
        transfer_image = ImageIdentity(
            "registry.invalid/opentcad/transfer@sha256:" + "1" * 64,
            "sha256:" + "1" * 64,
            "sha256:" + "2" * 64,
            "linux/amd64",
        )
        engine_image = ImageIdentity(
            "registry.invalid/opentcad/engine@sha256:" + "3" * 64,
            "sha256:" + "3" * 64,
            "sha256:" + "4" * 64,
            "linux/amd64",
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence.json"
            evidence.write_bytes(b"qualified")
            evidence_record = {
                "path": "evidence.json",
                "sha256": sha256(b"qualified").hexdigest(),
            }
            reviewer = "release-reviewer"
            approved_at = "2026-08-31T00:00:00Z"
            grants = []
            for backend in ("docker", "podman"):
                grants.extend(
                    (
                        {
                            "backend": backend,
                            "image": _image_record(transfer_image),
                            "entrypoint": "archive-import",
                        },
                        {
                            "backend": backend,
                            "image": _image_record(transfer_image),
                            "entrypoint": "archive-export",
                        },
                        {
                            "backend": backend,
                            "image": _image_record(engine_image),
                            "entrypoint": "suprem-reference",
                        },
                    ),
                )
            manifest = root / "m3-entry-gates.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "productEnabled": True,
                        "approvalId": str(uuid4()),
                        "approvedBy": reviewer,
                        "approvedAt": approved_at,
                        "gates": [
                            {
                                "id": gate.value,
                                "approved": True,
                                "approvedBy": reviewer,
                                "approvedAt": approved_at,
                                "evidence": [evidence_record],
                            }
                            for gate in M3_GATE_IDS
                        ],
                        "runtime": {"grants": grants},
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            activation = M3ProductGate.load(
                manifest,
                repository_root=root,
            ).require_activation()
            profile = ProductReleaseProfile(
                activation.manifest_sha256,
                RuntimeKind.DOCKER,
                OciAdapterConfiguration(
                    RuntimeKind.DOCKER,
                    transfer_image,
                    (
                        OciEntrypoint("archive-import", "/opentcad/archive-import"),
                        OciEntrypoint("archive-export", "/opentcad/archive-export"),
                        OciEntrypoint("suprem-reference", "/opentcad/suprem"),
                    ),
                    "archive-import",
                    "archive-export",
                ),
                SandboxPolicy(
                    "m3-release-v1",
                    (
                        EngineProfile(
                            "suprem-release",
                            JobKind.SUPREM,
                            engine_image,
                            "suprem-env-v1",
                            "suprem-reference",
                            ("input.in",),
                            ("result.str",),
                        ),
                    ),
                    ResourceLimits(
                        2_000,
                        268_435_456,
                        128,
                        60_000,
                        1_048_576,
                        64,
                        16_777_216,
                        67_108_864,
                    ),
                    1_048_576,
                ),
                ArchiveLimits(1_048_576, 64, 16_777_216),
            )

            profile.verify_activation(activation)

            self.assertNotEqual(transfer_image, engine_image)
            self.assertEqual(profile.images, (transfer_image, engine_image))


if __name__ == "__main__":
    unittest.main()
