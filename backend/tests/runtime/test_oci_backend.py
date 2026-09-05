from __future__ import annotations

import asyncio
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from backend.app.product import M3_GATE_IDS, M3ProductGate
from backend.app.broker.orchestrator import SandboxBroker
from backend.app.broker.state import InMemoryJobStateStore
from backend.app.service.product_composition import ProductDurableBrokerComposition
from backend.app.runtime.errors import ErrorCode, RuntimeBackendError, RuntimePhase
from backend.app.runtime.fence_authority import InMemoryRuntimeFenceAuthority
from backend.app.runtime.product_fence_authority import ProductRuntimeFenceAuthority
from backend.app.broker.sqlite_state import SQLiteJobStateStore
from backend.app.runtime.fencing import (
    RUNTIME_FENCING_TOKEN_LABEL,
    RuntimeFencingContext,
)
from backend.app.runtime.models import (
    JobIdentity,
    RuntimeHealth,
    RuntimeKind,
    TerminalClassification,
    TerminationReason,
)
from backend.app.runtime.oci_backend import (
    OUTPUT_LIMIT_LABEL,
    OciAdapterConfiguration,
    OciCommandOutputLimitExceeded,
    OciCommandResult,
    OciEntrypoint,
    OciRuntimeBackend,
    SubprocessOciCommandRunner,
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
        self.timeouts: list[tuple[tuple[str, ...], int]] = []
        self.labels: dict[str, dict[str, str]] = {}
        self.volumes: set[str] = set()
        self.containers: set[str] = set()
        self.image_index_digest = IMAGE.index_digest

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
        terminate_on_output_limit=False,
    ) -> OciCommandResult:
        values = tuple(arguments)
        self.calls.append((values, input_bytes))
        self.timeouts.append((values, timeout_ms))
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
                    "version": {"Version": "5.6.0"},
                }
            return command_result(json.dumps(payload).encode())
        if values[:2] == ("image", "inspect"):
            return command_result(
                json.dumps(
                    [{
                        "RepoDigests": [IMAGE.reference],
                        "Descriptor": {
                            "digest": self.image_index_digest,
                        },
                        "Digest": self.image_index_digest,
                        "Os": "linux",
                        "Architecture": "amd64",
                    }],
                ).encode(),
            )
        if values[:2] == ("volume", "create"):
            name = values[-1]
            assert "--name" not in values
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
                return command_result(stderr=b"No such volume", returncode=1)
            return command_result(json.dumps(self.labels[name]).encode())
        if values[:3] == ("container", "inspect", "--format"):
            name = values[-1]
            if name not in self.containers:
                return command_result(stderr=b"No such container", returncode=1)
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


class BlockingVolumeRunner(FakeOciRunner):
    def __init__(self, kind: RuntimeKind) -> None:
        super().__init__(kind)
        self.mutation_started = asyncio.Event()
        self.release_mutation = asyncio.Event()

    async def run(self, arguments, **kwargs):
        values = tuple(arguments)
        if values[:2] == ("volume", "create"):
            self.mutation_started.set()
            await self.release_mutation.wait()
        return await super().run(arguments, **kwargs)


class BlockingWaitRunner(FakeOciRunner):
    def __init__(self, kind: RuntimeKind) -> None:
        super().__init__(kind)
        self.wait_started = asyncio.Event()
        self.release_wait = asyncio.Event()

    async def run(self, arguments, **kwargs):
        values = tuple(arguments)
        if values[:2] == ("container", "wait"):
            self.wait_started.set()
            await self.release_wait.wait()
        return await super().run(arguments, **kwargs)


class TimeoutWaitRunner(FakeOciRunner):
    def __init__(self, kind: RuntimeKind) -> None:
        super().__init__(kind)
        self.killed = False
        self.wait_timeouts = []

    async def run(self, arguments, **kwargs):
        values = tuple(arguments)
        if values[:2] == ("container", "wait"):
            self.wait_timeouts.append(kwargs["timeout_ms"])
            self.calls.append((values, kwargs.get("input_bytes")))
            if not self.killed:
                raise TimeoutError
            return command_result(b"137\n")
        if values[:2] == ("container", "kill"):
            self.killed = True
        return await super().run(arguments, **kwargs)


class OutputLimitRunner(FakeOciRunner):
    def __init__(self, kind: RuntimeKind) -> None:
        super().__init__(kind)
        self.killed = False

    async def run(self, arguments, **kwargs):
        values = tuple(arguments)
        if (
            values[:2] == ("container", "logs")
            and "--follow" in values
            and not self.killed
        ):
            self.calls.append((values, kwargs.get("input_bytes")))
            self.assert_bounded = kwargs.get("terminate_on_output_limit")
            limit = kwargs["output_limit"]
            observed = b"x" * (limit + 1)
            result = OciCommandResult(
                137,
                observed[:limit],
                b"",
                len(observed),
                0,
                sha256(observed).hexdigest(),
                sha256(b"").hexdigest(),
                1,
            )
            raise OciCommandOutputLimitExceeded(result)
        if values[:2] == ("container", "wait"):
            self.calls.append((values, kwargs.get("input_bytes")))
            return command_result(b"137\n" if self.killed else b"0\n")
        if values[:2] == ("container", "kill"):
            self.killed = True
        return await super().run(arguments, **kwargs)


class AlreadyStoppedKillRunner(FakeOciRunner):
    async def run(self, arguments, **kwargs):
        values = tuple(arguments)
        if values[:2] == ("container", "kill"):
            self.calls.append((values, kwargs.get("input_bytes")))
            return command_result(stderr=b"container is not running", returncode=1)
        if (
            values[:3] == ("container", "inspect", "--format")
            and values[3] == "{{json .State.Running}}"
        ):
            self.calls.append((values, kwargs.get("input_bytes")))
            return command_result(b"false")
        return await super().run(arguments, **kwargs)


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
    async def test_product_passive_wait_does_not_block_cancellation_takeover(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            locks = root / "locks"
            locks.mkdir()
            authority = ProductRuntimeFenceAuthority(root / "fence.sqlite3", locks)
            runner = BlockingWaitRunner(RuntimeKind.DOCKER)
            backend = OciRuntimeBackend(
                configuration(RuntimeKind.DOCKER),
                activation_token(),
                authority,
                runner=runner,
            )
            identity = JobIdentity(str(uuid4()))
            old = RuntimeFencingContext(identity, str(uuid4()), 1)
            current = RuntimeFencingContext(identity, str(uuid4()), 2)
            await authority.activate(
                old,
                phase=RuntimePhase.QUERY,
                backend=backend.name,
            )
            bound = backend.bind_job(old)
            spec = POLICY.validate(
                make_spec(identity.job_id),
                (await backend.probe()).capabilities,
            )
            volume = await bound.create_volume()
            await bound.stage_inputs(volume, spec, ARCHIVE)
            container = await bound.create_container(spec, volume)
            await bound.start(container)

            waiting = asyncio.create_task(bound.wait(container))
            await runner.wait_started.wait()
            await asyncio.wait_for(
                authority.activate(
                    current,
                    phase=RuntimePhase.KILL,
                    backend=backend.name,
                ),
                timeout=1,
            )
            runner.release_wait.set()
            with self.assertRaises(RuntimeBackendError) as raised:
                await waiting
            self.assertEqual(raised.exception.code, ErrorCode.OPERATION_FENCED)

    async def test_product_guard_linearizes_takeover_after_native_mutation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            locks = root / "locks"
            locks.mkdir()
            authority = ProductRuntimeFenceAuthority(root / "fence.sqlite3", locks)
            runner = BlockingVolumeRunner(RuntimeKind.DOCKER)
            backend = OciRuntimeBackend(
                configuration(RuntimeKind.DOCKER),
                activation_token(),
                authority,
                runner=runner,
            )
            identity = JobIdentity(str(uuid4()))
            old = RuntimeFencingContext(identity, str(uuid4()), 1)
            current = RuntimeFencingContext(identity, str(uuid4()), 2)
            await authority.activate(
                old,
                phase=RuntimePhase.QUERY,
                backend=backend.name,
            )
            mutation = asyncio.create_task(backend.bind_job(old).create_volume())
            await runner.mutation_started.wait()
            takeover = asyncio.create_task(
                authority.activate(
                    current,
                    phase=RuntimePhase.QUERY,
                    backend=backend.name,
                ),
            )
            await asyncio.sleep(0.05)
            self.assertFalse(takeover.done())
            runner.release_mutation.set()
            await mutation
            await takeover
            call_count = len(runner.calls)
            with self.assertRaises(RuntimeBackendError) as fenced:
                await backend.bind_job(old).list_managed()
            self.assertEqual(fenced.exception.code, ErrorCode.OPERATION_FENCED)
            self.assertEqual(len(runner.calls), call_count)

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

    async def test_image_identity_is_local_only_and_index_bound(self) -> None:
        backend, runner, _ = self.backend()
        self.assertEqual(await backend.ensure_image(IMAGE), IMAGE)
        self.assertFalse(
            any(call[:2] == ("manifest", "inspect") for call, _ in runner.calls),
        )
        runner.image_index_digest = f"sha256:{'f' * 64}"
        with self.assertRaises(RuntimeBackendError) as raised:
            await backend.ensure_image(IMAGE)
        self.assertEqual(
            raised.exception.code,
            ErrorCode.IMAGE_IDENTITY_MISMATCH,
        )

    async def test_podman_create_uses_explicit_read_only_tmpfs_dialect(self) -> None:
        backend, runner, authority = self.backend(RuntimeKind.PODMAN)
        identity = JobIdentity(str(uuid4()))
        fence = RuntimeFencingContext(identity, str(uuid4()), 1)
        await authority.activate(
            fence,
            phase=RuntimePhase.QUERY,
            backend=backend.name,
        )
        bound = backend.bind_job(fence)
        spec = POLICY.validate(
            make_spec(identity.job_id),
            (await backend.probe()).capabilities,
        )
        volume = await bound.create_volume()
        await bound.stage_inputs(volume, spec, ARCHIVE)
        await bound.create_container(spec, volume)
        create = next(
            arguments
            for arguments, _ in runner.calls
            if arguments[:2] == ("container", "create")
            and arguments[arguments.index("--name") + 1]
            == fence.identity.object_name
        )
        self.assertIn("--restart=no", create)
        self.assertIn("--pull=never", create)
        self.assertIn("--read-only-tmpfs=false", create)

    async def test_matching_activation_opens_durable_composition(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            locks = root / "locks"
            locks.mkdir()
            token = activation_token()
            runner = FakeOciRunner(RuntimeKind.DOCKER)
            authority = ProductRuntimeFenceAuthority(root / "fence.sqlite3", locks)
            backend = OciRuntimeBackend(
                configuration(RuntimeKind.DOCKER),
                token,
                authority,
                runner=runner,
            )
            composition = ProductDurableBrokerComposition(
                SandboxBroker(backend, POLICY, ARCHIVE_LIMITS),
                backend,
                SQLiteJobStateStore(root / "state.sqlite3"),
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
        with self.assertRaises(TypeError):
            ProductDurableBrokerComposition(
                SandboxBroker(backend, POLICY, ARCHIVE_LIMITS),
                backend,
                InMemoryJobStateStore(),
                activation_token(),
            )

    async def test_full_lifecycle_uses_hardened_argv_and_native_fence(self) -> None:
        backend, runner, authority = self.backend()
        job_id = str(uuid4())
        owner_id = str(uuid4())
        fence = RuntimeFencingContext(JobIdentity(job_id), owner_id, 1)
        await authority.activate(
            fence,
            phase=RuntimePhase.QUERY,
            backend=backend.name,
        )
        bound = backend.bind_job(fence)
        self.assertIsInstance(bound, RuntimeJobBackend)
        probe = await backend.probe()
        spec = POLICY.validate(make_spec(job_id), probe.capabilities)
        await backend.ensure_image(IMAGE)
        volume = await bound.create_volume()
        await bound.stage_inputs(volume, spec, ARCHIVE)
        input_helper_create = next(
            arguments
            for arguments, _ in runner.calls
            if arguments[:2] == ("container", "create")
            and arguments[arguments.index("--name") + 1]
            == f"{fence.identity.object_name}-input"
        )
        self.assertIn("--interactive", input_helper_create)
        input_helper_timeout = next(
            timeout_ms
            for arguments, timeout_ms in runner.timeouts
            if arguments[:3] == ("container", "start", "--attach")
            and "--interactive" in arguments
        )
        self.assertEqual(input_helper_timeout, 30_000)
        container = await bound.create_container(spec, volume)
        await bound.start(container)
        result = await bound.wait(container)
        archive = await bound.collect_artifacts(container)
        output_helper_timeout = next(
            timeout_ms
            for arguments, timeout_ms in runner.timeouts
            if arguments[:3] == ("container", "start", "--attach")
            and "--interactive" not in arguments
        )
        self.assertEqual(output_helper_timeout, 30_000)
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
            "--memory-swap",
            "--cpus",
            "--tmpfs",
            "--mount",
            "--pull",
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

    async def test_wait_enforces_timeout_and_output_limit_through_kill(self) -> None:
        cases = (
            (TimeoutWaitRunner, TerminalClassification.TIMED_OUT),
            (
                OutputLimitRunner,
                TerminalClassification.OUTPUT_LIMIT_EXCEEDED,
            ),
        )
        for runner_type, expected in cases:
            with self.subTest(expected=expected):
                runner = runner_type(RuntimeKind.DOCKER)
                authority = InMemoryRuntimeFenceAuthority()
                backend = OciRuntimeBackend(
                    configuration(RuntimeKind.DOCKER),
                    activation_token(),
                    authority,
                    runner=runner,
                )
                identity = JobIdentity(str(uuid4()))
                fence = RuntimeFencingContext(identity, str(uuid4()), 1)
                await authority.activate(
                    fence,
                    phase=RuntimePhase.QUERY,
                    backend=backend.name,
                )
                bound = backend.bind_job(fence)
                spec = POLICY.validate(
                    make_spec(identity.job_id),
                    (await backend.probe()).capabilities,
                )
                volume = await bound.create_volume()
                await bound.stage_inputs(volume, spec, ARCHIVE)
                container = await bound.create_container(spec, volume)
                await bound.start(container)

                result = await bound.wait(container)

                self.assertEqual(result.classification, expected)
                self.assertTrue(runner.killed)
                self.assertEqual(result.artifacts, ())
                if isinstance(runner, TimeoutWaitRunner):
                    self.assertEqual(
                        runner.wait_timeouts,
                        [spec.spec.limits.timeout_ms, 30_000],
                    )
                if isinstance(runner, OutputLimitRunner):
                    self.assertTrue(runner.assert_bounded)
                    self.assertTrue(result.output_truncated)
                    self.assertEqual(
                        result.captured_output_bytes,
                        spec.spec.limits.output_bytes,
                    )

    async def test_kill_race_accepts_a_native_already_stopped_state(self) -> None:
        runner = AlreadyStoppedKillRunner(RuntimeKind.DOCKER)
        authority = InMemoryRuntimeFenceAuthority()
        backend = OciRuntimeBackend(
            configuration(RuntimeKind.DOCKER),
            activation_token(),
            authority,
            runner=runner,
        )
        identity = JobIdentity(str(uuid4()))
        fence = RuntimeFencingContext(identity, str(uuid4()), 1)
        await authority.activate(
            fence,
            phase=RuntimePhase.QUERY,
            backend=backend.name,
        )
        bound = backend.bind_job(fence)
        spec = POLICY.validate(
            make_spec(identity.job_id),
            (await backend.probe()).capabilities,
        )
        volume = await bound.create_volume()
        await bound.stage_inputs(volume, spec, ARCHIVE)
        container = await bound.create_container(spec, volume)
        await bound.start(container)

        result = await bound.kill(container, TerminationReason.TIMEOUT)

        self.assertEqual(result.classification, TerminalClassification.TIMED_OUT)

    async def test_stale_owner_is_rejected_before_native_command(self) -> None:
        backend, runner, authority = self.backend()
        identity = JobIdentity(str(uuid4()))
        old = RuntimeFencingContext(identity, str(uuid4()), 1)
        current = RuntimeFencingContext(identity, str(uuid4()), 2)
        await authority.activate(
            old,
            phase=RuntimePhase.QUERY,
            backend=backend.name,
        )
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
        backend, runner, authority = self.backend()
        identity = JobIdentity(str(uuid4()))
        fence = RuntimeFencingContext(identity, str(uuid4()), 1)
        await authority.activate(
            fence,
            phase=RuntimePhase.QUERY,
            backend=backend.name,
        )
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

    async def test_restart_cancellation_recovers_limits_from_native_labels(self) -> None:
        backend, _, authority = self.backend()
        identity = JobIdentity(str(uuid4()))
        fence = RuntimeFencingContext(identity, str(uuid4()), 1)
        await authority.activate(
            fence,
            phase=RuntimePhase.QUERY,
            backend=backend.name,
        )
        bound = backend.bind_job(fence)
        spec = POLICY.validate(
            make_spec(identity.job_id),
            (await backend.probe()).capabilities,
        )
        volume = await bound.create_volume()
        await bound.stage_inputs(volume, spec, ARCHIVE)
        container = await bound.create_container(spec, volume)
        await bound.start(container)

        backend._specs.clear()
        result = await bound.kill(container, TerminationReason.CANCELLATION)

        self.assertEqual(result.classification, TerminalClassification.CANCELLED)
        self.assertEqual(result.output_limit_bytes, spec.spec.limits.output_bytes)
        self.assertEqual(result.artifacts, ())

    async def test_reopened_backend_takeover_cancels_and_cleans_predecessor(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            locks = root / "locks"
            locks.mkdir()
            runner = FakeOciRunner(RuntimeKind.DOCKER)
            token = activation_token()
            first_authority = ProductRuntimeFenceAuthority(
                root / "fence.sqlite3",
                locks,
            )
            first_backend = OciRuntimeBackend(
                configuration(RuntimeKind.DOCKER),
                token,
                first_authority,
                runner=runner,
            )
            identity = JobIdentity(str(uuid4()))
            predecessor = RuntimeFencingContext(identity, str(uuid4()), 1)
            await first_authority.activate(
                predecessor,
                phase=RuntimePhase.QUERY,
                backend=first_backend.name,
            )
            first = first_backend.bind_job(predecessor)
            spec = POLICY.validate(
                make_spec(identity.job_id),
                (await first_backend.probe()).capabilities,
            )
            volume = await first.create_volume()
            await first.stage_inputs(volume, spec, ARCHIVE)
            container = await first.create_container(spec, volume)
            await first.start(container)

            reopened_authority = ProductRuntimeFenceAuthority(
                root / "fence.sqlite3",
                locks,
            )
            reopened_backend = OciRuntimeBackend(
                configuration(RuntimeKind.DOCKER),
                token,
                reopened_authority,
                runner=runner,
            )
            takeover = RuntimeFencingContext(identity, str(uuid4()), 2)
            await reopened_authority.activate(
                takeover,
                phase=RuntimePhase.KILL,
                backend=reopened_backend.name,
            )
            recovered = reopened_backend.bind_job(takeover)

            result = await recovered.kill(
                container,
                TerminationReason.CANCELLATION,
            )
            self.assertEqual(
                result.classification,
                TerminalClassification.CANCELLED,
            )
            self.assertEqual(
                result.output_limit_bytes,
                spec.spec.limits.output_bytes,
            )
            self.assertEqual(
                await reopened_authority.current(identity.job_id),
                takeover,
            )

            await recovered.remove_container(container)
            await recovered.remove_container(container)
            await recovered.remove_volume(volume)
            await recovered.remove_volume(volume)
            managed = await recovered.list_managed()
            self.assertEqual(managed.containers, ())
            self.assertEqual(managed.volumes, ())

    async def test_restart_cancellation_rejects_tampered_output_limit(self) -> None:
        backend, runner, authority = self.backend()
        identity = JobIdentity(str(uuid4()))
        fence = RuntimeFencingContext(identity, str(uuid4()), 1)
        await authority.activate(
            fence,
            phase=RuntimePhase.QUERY,
            backend=backend.name,
        )
        bound = backend.bind_job(fence)
        spec = POLICY.validate(
            make_spec(identity.job_id),
            (await backend.probe()).capabilities,
        )
        volume = await bound.create_volume()
        await bound.stage_inputs(volume, spec, ARCHIVE)
        container = await bound.create_container(spec, volume)
        backend._specs.clear()
        runner.labels[container.opaque_id][OUTPUT_LIMIT_LABEL] = "unbounded"

        with self.assertRaises(RuntimeBackendError) as raised:
            await bound.kill(container, TerminationReason.CANCELLATION)
        self.assertEqual(raised.exception.code, ErrorCode.OPERATION_FENCED)


class SubprocessOciCommandRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_terminates_cli_when_combined_output_exceeds_limit(self) -> None:
        runner = SubprocessOciCommandRunner(sys.executable)
        with self.assertRaises(OciCommandOutputLimitExceeded) as raised:
            await runner.run(
                (
                    "-c",
                    "import sys; sys.stdout.buffer.write(b'x' * 1048576)",
                ),
                timeout_ms=5_000,
                output_limit=1_024,
                terminate_on_output_limit=True,
            )
        result = raised.exception.result
        self.assertEqual(result.captured_bytes, 1_024)
        self.assertGreater(result.observed_bytes, result.captured_bytes)
        self.assertTrue(result.truncated)


if __name__ == "__main__":
    unittest.main()
