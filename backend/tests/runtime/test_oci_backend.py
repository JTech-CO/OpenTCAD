from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from backend.app.product import M3_GATE_IDS, M3ProductGate
from backend.app.broker.orchestrator import SandboxBroker
from backend.app.broker.state import InMemoryJobStateStore
from backend.app.service.product_composition import ProductDurableBrokerComposition
from backend.app.runtime.errors import ErrorCode, RuntimeBackendError, RuntimePhase
from backend.app.runtime.fence_authority import InMemoryRuntimeFenceAuthority
from backend.app.runtime.fencing import (
    RUNTIME_FENCING_TOKEN_LABEL,
    RuntimeFencingContext,
)
from backend.app.runtime.models import (
    JobIdentity,
    RuntimeHealth,
    RuntimeKind,
)
from backend.app.runtime.oci_backend import (
    OciAdapterConfiguration,
    OciCommandResult,
    OciEntrypoint,
    OciRuntimeBackend,
)
from backend.app.runtime.protocol import RuntimeBackend, RuntimeJobBackend
from backend.tests.runtime.support import (
    ARCHIVE,
    ARCHIVE_LIMITS,
    ARTIFACT,
    ARTIFACT_ARCHIVE,
    IMAGE,
    POLICY,
    make_spec,
)


def command_result(
    stdout: bytes = b"",
    stderr: bytes = b"",
    *,
    returncode: int = 0,
) -> OciCommandResult:
    return OciCommandResult(
        returncode,
        stdout,
        stderr,
        len(stdout),
        len(stderr),
        sha256(stdout).hexdigest(),
        sha256(stderr).hexdigest(),
        1,
    )


def activation_token():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        evidence = root / "evidence.json"
        evidence.write_bytes(b"qualified")
        image = {
            "reference": IMAGE.reference,
            "index_digest": IMAGE.index_digest,
            "platform_manifest_digest": IMAGE.platform_manifest_digest,
            "platform": IMAGE.platform,
        }
        reviewer = "runtime-reviewer"
        approved_at = "2026-08-31T00:00:00Z"
        record = {
            "path": "evidence.json",
            "sha256": sha256(b"qualified").hexdigest(),
        }
        manifest = {
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
                    "evidence": [record],
                }
                for gate in M3_GATE_IDS
            ],
            "runtime": {
                "grants": [
                    {
                        "backend": backend,
                        "image": image,
                        "entrypoint": entrypoint,
                    }
                    for backend in ("docker", "podman")
                    for entrypoint in (
                        "test-entrypoint",
                        "archive-import",
                        "archive-export",
                    )
                ],
            },
        }
        path = root / "manifest.json"
        path.write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        return M3ProductGate.load(path, repository_root=root).require_activation()


class FakeOciRunner:
    def __init__(self, kind: RuntimeKind) -> None:
        self.kind = kind
        self.calls: list[tuple[tuple[str, ...], bytes | None]] = []
        self.labels: dict[str, dict[str, str]] = {}
        self.volumes: set[str] = set()
        self.containers: set[str] = set()

    @staticmethod
    def _labels(arguments: tuple[str, ...]) -> dict[str, str]:
        result: dict[str, str] = {}
        for index, value in enumerate(arguments):
            if value == "--label":
                key, label_value = arguments[index + 1].split("=", maxsplit=1)
                result[key] = label_value
        return result

    async def run(
        self,
        arguments,
        *,
        input_bytes=None,
        timeout_ms=30_000,
        output_limit=1_048_576,
    ) -> OciCommandResult:
        values = tuple(arguments)
        self.calls.append((values, input_bytes))
        if values[:2] == ("info", "--format"):
            if self.kind is RuntimeKind.DOCKER:
                payload = {
                    "OSType": "linux",
                    "Architecture": "x86_64",
                    "ServerVersion": "29.6.2",
                    "SecurityOptions": ["name=rootless"],
                }
            else:
                payload = {
                    "host": {
                        "os": "linux",
                        "arch": "amd64",
                        "security": {"rootless": True},
                    },
                    "version": {"version": "5.6.0"},
                }
            return command_result(json.dumps(payload).encode())
        if values[:2] == ("image", "inspect"):
            return command_result(
                json.dumps(
                    [{
                        "RepoDigests": [IMAGE.reference],
                        "Os": "linux",
                        "Architecture": "amd64",
                    }],
                ).encode(),
            )
        if values[:3] == ("manifest", "inspect", "--verbose"):
            return command_result(
                json.dumps(
                    {
                        "manifests": [{
                            "digest": IMAGE.platform_manifest_digest,
                            "platform": {
                                "os": "linux",
                                "architecture": "amd64",
                            },
                        }],
                    },
                ).encode(),
            )
        if values[:2] == ("volume", "create"):
            name = values[values.index("--name") + 1]
            self.volumes.add(name)
            self.labels[name] = self._labels(values)
            return command_result(name.encode())
        if values[:2] == ("container", "create"):
            name = values[values.index("--name") + 1]
            self.containers.add(name)
            self.labels[name] = self._labels(values)
            return command_result(name.encode())
        if values[:3] == ("volume", "inspect", "--format"):
            name = values[-1]
            if name not in self.volumes:
                return command_result(returncode=1)
            return command_result(json.dumps(self.labels[name]).encode())
        if values[:3] == ("container", "inspect", "--format"):
            name = values[-1]
            if name not in self.containers:
                return command_result(returncode=1)
            if values[3] == "{{json .State}}":
                return command_result(
                    json.dumps(
                        {
                            "OOMKilled": False,
                            "StartedAt": "2026-08-31T00:00:00Z",
                            "FinishedAt": "2026-08-31T00:00:01Z",
                        },
                    ).encode(),
                )
            return command_result(json.dumps(self.labels[name]).encode())
        if values[:2] == ("container", "start"):
            name = values[-1]
            if name.endswith("-output"):
                return command_result(ARTIFACT_ARCHIVE.payload)
            return command_result()
        if values[:2] == ("container", "wait"):
            return command_result(b"0\n")
        if values[:2] == ("container", "logs"):
            return command_result(b"solver output\n")
        if values[:2] == ("container", "rm"):
            name = values[-1]
            self.containers.discard(name)
            self.labels.pop(name, None)
            return command_result()
        if values[:2] == ("volume", "rm"):
            name = values[-1]
            self.volumes.discard(name)
            self.labels.pop(name, None)
            return command_result()
        if values[:2] == ("container", "ls"):
            return command_result(
                ("\n".join(sorted(self.containers)) + ("\n" if self.containers else "")).encode(),
            )
        if values[:2] == ("volume", "ls"):
            return command_result(
                ("\n".join(sorted(self.volumes)) + ("\n" if self.volumes else "")).encode(),
            )
        if values[:2] == ("container", "kill"):
            return command_result()
        raise AssertionError(f"Unexpected OCI command: {values!r}")


def configuration(kind: RuntimeKind) -> OciAdapterConfiguration:
    return OciAdapterConfiguration(
        kind,
        IMAGE,
        (
            OciEntrypoint("test-entrypoint", "/opentcad/bin/solver"),
            OciEntrypoint("archive-import", "/opentcad/bin/archive-import"),
            OciEntrypoint("archive-export", "/opentcad/bin/archive-export"),
        ),
        "archive-import",
        "archive-export",
    )


class OciRuntimeBackendTests(unittest.IsolatedAsyncioTestCase):
    def backend(self, kind: RuntimeKind = RuntimeKind.DOCKER):
        runner = FakeOciRunner(kind)
        authority = InMemoryRuntimeFenceAuthority()
        backend = OciRuntimeBackend(
            configuration(kind),
            activation_token(),
            authority,
            runner=runner,
        )
        return backend, runner, authority

    async def test_docker_and_podman_probe_are_product_protocols(self) -> None:
        for kind in (RuntimeKind.DOCKER, RuntimeKind.PODMAN):
            with self.subTest(kind=kind):
                backend, _, _ = self.backend(kind)
                self.assertIsInstance(backend, RuntimeBackend)
                probe = await backend.probe()
                self.assertEqual(probe.health, RuntimeHealth.AVAILABLE)
                self.assertEqual(probe.capabilities.backend, kind)
                self.assertTrue(probe.capabilities.runtime_fencing)

    async def test_matching_activation_opens_durable_composition(self) -> None:
        token = activation_token()
        runner = FakeOciRunner(RuntimeKind.DOCKER)
        backend = OciRuntimeBackend(
            configuration(RuntimeKind.DOCKER),
            token,
            InMemoryRuntimeFenceAuthority(),
            runner=runner,
        )
        composition = ProductDurableBrokerComposition(
            SandboxBroker(backend, POLICY, ARCHIVE_LIMITS),
            backend,
            InMemoryJobStateStore(),
            token,
        )
        self.assertFalse(composition.ready)

    async def test_mismatched_activation_cannot_open_product_composition(self) -> None:
        backend_token = activation_token()
        authority = InMemoryRuntimeFenceAuthority()
        backend = OciRuntimeBackend(
            configuration(RuntimeKind.DOCKER),
            backend_token,
            authority,
            runner=FakeOciRunner(RuntimeKind.DOCKER),
        )
        with self.assertRaises(PermissionError):
            ProductDurableBrokerComposition(
                SandboxBroker(backend, POLICY, ARCHIVE_LIMITS),
                backend,
                InMemoryJobStateStore(),
                activation_token(),
            )
        other = OciRuntimeBackend(
            configuration(RuntimeKind.DOCKER),
            backend_token,
            authority,
            runner=FakeOciRunner(RuntimeKind.DOCKER),
        )
        with self.assertRaises(PermissionError):
            ProductDurableBrokerComposition(
                SandboxBroker(backend, POLICY, ARCHIVE_LIMITS),
                other,
                InMemoryJobStateStore(),
                backend_token,
            )

    async def test_full_lifecycle_uses_hardened_argv_and_native_fence(self) -> None:
        backend, runner, _ = self.backend()
        job_id = str(uuid4())
        owner_id = str(uuid4())
        fence = RuntimeFencingContext(JobIdentity(job_id), owner_id, 1)
        bound = backend.bind_job(fence)
        self.assertIsInstance(bound, RuntimeJobBackend)
        probe = await backend.probe()
        spec = POLICY.validate(make_spec(job_id), probe.capabilities)
        await backend.ensure_image(IMAGE)
        volume = await bound.create_volume()
        await bound.stage_inputs(volume, spec, ARCHIVE)
        container = await bound.create_container(spec, volume)
        await bound.start(container)
        result = await bound.wait(container)
        archive = await bound.collect_artifacts(container)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.artifacts, (ARTIFACT,))
        self.assertEqual(archive.payload, ARTIFACT_ARCHIVE.payload)
        create = next(
            arguments
            for arguments, _ in runner.calls
            if arguments[:2] == ("container", "create")
            and arguments[arguments.index("--name") + 1] == fence.identity.object_name
        )
        for required in (
            "--network",
            "--cap-drop",
            "--security-opt",
            "--read-only",
            "--user",
            "--pids-limit",
            "--memory",
            "--cpus",
            "--tmpfs",
            "--mount",
            "--entrypoint",
        ):
            self.assertIn(required, create)
        self.assertIn(IMAGE.reference, create)
        self.assertNotIn("sh", create)
        self.assertNotIn("-c", create)
        await bound.remove_container(container)
        await bound.remove_container(container)
        await bound.remove_volume(volume)
        await bound.remove_volume(volume)
        self.assertEqual(await bound.list_managed(), await backend.list_managed())

    async def test_stale_owner_is_rejected_before_native_command(self) -> None:
        backend, runner, authority = self.backend()
        identity = JobIdentity(str(uuid4()))
        old = RuntimeFencingContext(identity, str(uuid4()), 1)
        current = RuntimeFencingContext(identity, str(uuid4()), 2)
        volume = await backend.bind_job(old).create_volume()
        await authority.activate(
            current,
            phase=RuntimePhase.QUERY,
            backend=backend.name,
        )
        count = len(runner.calls)
        with self.assertRaises(RuntimeBackendError) as raised:
            await backend.bind_job(old).remove_volume(volume)
        self.assertEqual(raised.exception.code, ErrorCode.OPERATION_FENCED)
        self.assertEqual(len(runner.calls), count)
        await backend.bind_job(current).remove_volume(volume)
        self.assertNotIn(volume.opaque_id, runner.volumes)

    async def test_tampered_native_fence_label_rejects_start(self) -> None:
        backend, runner, _ = self.backend()
        identity = JobIdentity(str(uuid4()))
        fence = RuntimeFencingContext(identity, str(uuid4()), 1)
        bound = backend.bind_job(fence)
        spec = POLICY.validate(
            make_spec(identity.job_id),
            (await backend.probe()).capabilities,
        )
        volume = await bound.create_volume()
        await bound.stage_inputs(volume, spec, ARCHIVE)
        container = await bound.create_container(spec, volume)
        runner.labels[container.opaque_id][RUNTIME_FENCING_TOKEN_LABEL] = "2"
        with self.assertRaises(RuntimeBackendError) as raised:
            await bound.start(container)
        self.assertEqual(raised.exception.code, ErrorCode.OPERATION_FENCED)


if __name__ == "__main__":
    unittest.main()
