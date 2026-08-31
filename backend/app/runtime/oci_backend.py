"""Evidence-gated Docker and Podman adapters with native object fencing."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from io import BytesIO
import json
import os
import re
import shutil
import tarfile
from time import monotonic
from typing import Protocol, runtime_checkable

from backend.app.product.gates import ProductActivationToken

from .errors import (
    ErrorCode,
    RetryDisposition,
    RuntimeBackendError,
    RuntimePhase,
)
from .fence_authority import RuntimeFenceAuthority
from .fencing import RuntimeFencingContext, enforce_runtime_object_fence
from .product_fence_authority import ProductRuntimeFenceAuthority
from .models import (
    ArtifactRecord,
    ContainerHandle,
    ImageIdentity,
    ManagedObjects,
    RawArtifactArchive,
    RunResult,
    RuntimeCapabilities,
    RuntimeHealth,
    RuntimeKind,
    RuntimeProbe,
    TerminalClassification,
    TerminationReason,
    ValidatedInputArchive,
    ValidatedSandboxSpec,
    VolumeHandle,
)


OCI_RUNTIME_ADAPTER_PRODUCT_ENABLED = True
MANAGED_LABEL = "io.opentcad.managed"
OBJECT_TYPE_LABEL = "io.opentcad.object-type"
ENTRYPOINT_LABEL = "io.opentcad.entrypoint"
OUTPUT_LIMIT_LABEL = "io.opentcad.output-limit"
MANAGED_LABEL_VALUE = "true"
_CONTROL_OUTPUT_LIMIT = 1_048_576
_MIN_OUTPUT_LIMIT = 1_024
_MAX_OUTPUT_LIMIT = 1_073_741_824
_RECOVERY_WAIT_TIMEOUT_MS = 30_000
_ENTRYPOINT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
_ALLOWED_ENVIRONMENT = (
    "PATH",
    "HOME",
    "USERPROFILE",
    "SYSTEMROOT",
    "COMSPEC",
    "DOCKER_CONFIG",
    "XDG_RUNTIME_DIR",
    "XDG_CONFIG_HOME",
    "CONTAINERS_CONF",
    "CONTAINERS_STORAGE_CONF",
)


@dataclass(frozen=True, slots=True)
class OciCommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    observed_stdout_bytes: int
    observed_stderr_bytes: int
    stdout_sha256: str
    stderr_sha256: str
    duration_ms: int

    @property
    def observed_bytes(self) -> int:
        return self.observed_stdout_bytes + self.observed_stderr_bytes

    @property
    def captured_bytes(self) -> int:
        return len(self.stdout) + len(self.stderr)

    @property
    def truncated(self) -> bool:
        return self.captured_bytes < self.observed_bytes


@runtime_checkable
class OciCommandRunner(Protocol):
    async def run(
        self,
        arguments: Sequence[str],
        *,
        input_bytes: bytes | None = None,
        timeout_ms: int = 30_000,
        output_limit: int = _CONTROL_OUTPUT_LIMIT,
    ) -> OciCommandResult: ...


class SubprocessOciCommandRunner:
    """Shell-free bounded subprocess transport for a resolved OCI CLI."""

    def __init__(
        self,
        executable: str,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        if not isinstance(executable, str) or not executable:
            raise TypeError("OCI executable must be non-empty text.")
        resolved = shutil.which(executable)
        if resolved is None:
            raise FileNotFoundError(executable)
        self._executable = resolved
        source = os.environ if environment is None else environment
        self._environment = {
            key: source[key]
            for key in _ALLOWED_ENVIRONMENT
            if key in source and isinstance(source[key], str)
        }
        self._environment["LC_ALL"] = "C"
        self._environment["LANG"] = "C"

    async def run(
        self,
        arguments: Sequence[str],
        *,
        input_bytes: bytes | None = None,
        timeout_ms: int = 30_000,
        output_limit: int = _CONTROL_OUTPUT_LIMIT,
    ) -> OciCommandResult:
        values = tuple(arguments)
        if (
            not values
            or any(not isinstance(value, str) or "\x00" in value for value in values)
            or not isinstance(timeout_ms, int)
            or isinstance(timeout_ms, bool)
            or timeout_ms < 1
            or not isinstance(output_limit, int)
            or isinstance(output_limit, bool)
            or output_limit < 1
            or (input_bytes is not None and not isinstance(input_bytes, bytes))
        ):
            raise TypeError("OCI command request is invalid.")

        started = monotonic()
        process = await asyncio.create_subprocess_exec(
            self._executable,
            *values,
            stdin=asyncio.subprocess.PIPE if input_bytes is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._environment,
        )
        remaining = output_limit

        async def capture(stream: asyncio.StreamReader) -> tuple[bytes, int, str]:
            nonlocal remaining
            observed = 0
            digest = sha256()
            captured = bytearray()
            while True:
                block = await stream.read(65_536)
                if not block:
                    break
                observed += len(block)
                digest.update(block)
                accepted = min(remaining, len(block))
                if accepted:
                    captured.extend(block[:accepted])
                    remaining -= accepted
            return bytes(captured), observed, digest.hexdigest()

        async def send_input() -> None:
            if process.stdin is None or input_bytes is None:
                return
            try:
                process.stdin.write(input_bytes)
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.stdin.close()

        if process.stdout is None or process.stderr is None:
            process.kill()
            await process.wait()
            raise RuntimeError("OCI subprocess pipes unavailable.")
        stdout_task = asyncio.create_task(capture(process.stdout))
        stderr_task = asyncio.create_task(capture(process.stderr))
        input_task = asyncio.create_task(send_input())
        try:
            await asyncio.wait_for(
                asyncio.gather(process.wait(), input_task),
                timeout=timeout_ms / 1_000,
            )
            stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
        except BaseException:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await asyncio.shield(process.wait())
            input_task.cancel()
            await asyncio.shield(
                asyncio.gather(
                    stdout_task,
                    stderr_task,
                    input_task,
                    return_exceptions=True,
                ),
            )
            raise
        return OciCommandResult(
            process.returncode,
            stdout[0],
            stderr[0],
            stdout[1],
            stderr[1],
            stdout[2],
            stderr[2],
            int((monotonic() - started) * 1_000),
        )


@dataclass(frozen=True, slots=True)
class OciEntrypoint:
    entrypoint_id: str
    executable: str
    arguments: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.entrypoint_id, str)
            or _ENTRYPOINT_ID_PATTERN.fullmatch(self.entrypoint_id) is None
            or not isinstance(self.executable, str)
            or not self.executable.startswith("/")
            or "\x00" in self.executable
            or len(self.executable) > 4_096
            or len(self.arguments) > 64
            or any(
                not isinstance(value, str)
                or "\x00" in value
                or len(value) > 4_096
                for value in self.arguments
            )
        ):
            raise TypeError("OCI entrypoint configuration is invalid.")
        object.__setattr__(self, "arguments", tuple(self.arguments))


@dataclass(frozen=True, slots=True)
class OciAdapterConfiguration:
    kind: RuntimeKind
    transfer_image: ImageIdentity
    entrypoints: tuple[OciEntrypoint, ...]
    input_helper_id: str
    output_helper_id: str

    def __post_init__(self) -> None:
        if self.kind not in {RuntimeKind.DOCKER, RuntimeKind.PODMAN}:
            raise TypeError("OCI adapter kind must be docker or podman.")
        values = tuple(self.entrypoints)
        if not values or any(not isinstance(item, OciEntrypoint) for item in values):
            raise TypeError("OCI adapter requires configured entrypoints.")
        identifiers = tuple(item.entrypoint_id for item in values)
        if len(set(identifiers)) != len(identifiers):
            raise TypeError("OCI entrypoint IDs must be unique.")
        if self.input_helper_id not in identifiers or self.output_helper_id not in identifiers:
            raise TypeError("OCI transfer helper entrypoints are required.")
        object.__setattr__(self, "entrypoints", values)

    def entrypoint(self, entrypoint_id: str) -> OciEntrypoint:
        for candidate in self.entrypoints:
            if candidate.entrypoint_id == entrypoint_id:
                return candidate
        raise RuntimeBackendError(
            ErrorCode.IMAGE_NOT_APPROVED,
            RuntimePhase.CREATE,
            backend=self.kind.value,
            detail="entrypoint-not-configured",
        )


def _runtime_error(
    code: ErrorCode,
    phase: RuntimePhase,
    backend: RuntimeKind,
    detail: str,
) -> RuntimeBackendError:
    return RuntimeBackendError(
        code,
        phase,
        retry=RetryDisposition.INFRASTRUCTURE,
        backend=backend.value,
        detail=detail,
    )


def _recovery_output_limit(
    labels: Mapping[str, str],
    backend: RuntimeKind,
) -> int:
    raw_output_limit = labels.get(OUTPUT_LIMIT_LABEL)
    try:
        output_limit = int(raw_output_limit or "")
    except ValueError:
        output_limit = 0
    if not _MIN_OUTPUT_LIMIT <= output_limit <= _MAX_OUTPUT_LIMIT:
        raise _runtime_error(
            ErrorCode.OPERATION_FENCED,
            RuntimePhase.WAIT,
            backend,
            "runtime-output-limit-label-invalid",
        )
    return output_limit


def _decode_json(payload: bytes, phase: RuntimePhase, backend: RuntimeKind) -> object:
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise _runtime_error(
            ErrorCode.RUNTIME_UNAVAILABLE,
            phase,
            backend,
            "runtime-returned-invalid-json",
        ) from None


def _architecture(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.casefold()
    return {
        "x86_64": "amd64",
        "x86-64": "amd64",
        "aarch64": "arm64",
    }.get(normalized, normalized)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class OciRuntimeBackend:
    """Docker/Podman implementation authorized by an evidence-bound token."""

    def __init__(
        self,
        configuration: OciAdapterConfiguration,
        activation: ProductActivationToken,
        fence_authority: RuntimeFenceAuthority,
        *,
        runner: OciCommandRunner | None = None,
        executable: str | None = None,
    ) -> None:
        if not isinstance(configuration, OciAdapterConfiguration):
            raise TypeError("OCI backend requires OciAdapterConfiguration.")
        if not isinstance(activation, ProductActivationToken):
            raise TypeError("OCI backend requires ProductActivationToken.")
        if not isinstance(fence_authority, RuntimeFenceAuthority):
            raise TypeError("OCI backend requires RuntimeFenceAuthority.")
        if configuration.kind not in activation.approved_backends:
            raise PermissionError("OCI backend is not product-approved.")
        for helper_id in (
            configuration.input_helper_id,
            configuration.output_helper_id,
        ):
            if not activation.permits(
                configuration.kind,
                configuration.transfer_image,
                helper_id,
            ):
                raise PermissionError("OCI transfer helper is not product-approved.")
        if runner is None:
            runner = SubprocessOciCommandRunner(
                executable or configuration.kind.value,
            )
        if not isinstance(runner, OciCommandRunner):
            raise TypeError("OCI backend requires OciCommandRunner.")
        self._configuration = configuration
        self._activation = activation
        self._fence_authority = fence_authority
        self._runner = runner
        self._specs: dict[str, ValidatedSandboxSpec] = {}
        self._artifact_archives: dict[str, RawArtifactArchive] = {}

    @property
    def name(self) -> RuntimeKind:
        return self._configuration.kind

    @property
    def fence_authority(self) -> RuntimeFenceAuthority:
        return self._fence_authority

    @property
    def activation_manifest_sha256(self) -> str:
        return self._activation.manifest_sha256

    async def _command(
        self,
        arguments: Sequence[str],
        *,
        phase: RuntimePhase,
        input_bytes: bytes | None = None,
        timeout_ms: int = 30_000,
        output_limit: int = _CONTROL_OUTPUT_LIMIT,
        error_code: ErrorCode = ErrorCode.RUNTIME_UNAVAILABLE,
    ) -> OciCommandResult:
        try:
            result = await self._runner.run(
                arguments,
                input_bytes=input_bytes,
                timeout_ms=timeout_ms,
                output_limit=output_limit,
            )
        except (OSError, TimeoutError):
            raise _runtime_error(
                error_code,
                phase,
                self.name,
                "runtime-command-unavailable",
            ) from None
        if result.returncode != 0:
            raise _runtime_error(
                error_code,
                phase,
                self.name,
                "runtime-command-failed",
            )
        return result

    async def probe(self) -> RuntimeProbe:
        try:
            result = await self._command(
                ("info", "--format", "{{json .}}"),
                phase=RuntimePhase.PROBE,
            )
            value = _decode_json(result.stdout, RuntimePhase.PROBE, self.name)
            if not isinstance(value, dict):
                raise ValueError
            if self.name is RuntimeKind.DOCKER:
                operating_system = value.get("OSType")
                architecture = _architecture(value.get("Architecture"))
                version = value.get("ServerVersion")
                security = value.get("SecurityOptions", ())
                rootless = isinstance(security, list) and any(
                    "rootless" in str(item).casefold() for item in security
                )
            else:
                host = value.get("host")
                version_value = value.get("version")
                if not isinstance(host, dict):
                    raise ValueError
                security_value = host.get("security")
                operating_system = host.get("os")
                architecture = _architecture(host.get("arch"))
                version = (
                    version_value.get("version")
                    if isinstance(version_value, dict)
                    else version_value
                )
                rootless = (
                    bool(security_value.get("rootless"))
                    if isinstance(security_value, dict)
                    else False
                )
            if (
                str(operating_system).casefold() != "linux"
                or architecture not in {"amd64", "arm64"}
                or not isinstance(version, str)
                or not version
            ):
                return RuntimeProbe(RuntimeHealth.DEGRADED, None)
            capability_values = {
                field: True
                for field in RuntimeCapabilities.__dataclass_fields__
                if field
                not in {
                    "backend",
                    "version",
                    "operating_system",
                    "architecture",
                    "rootless",
                }
            }
            return RuntimeProbe(
                RuntimeHealth.AVAILABLE,
                RuntimeCapabilities(
                    backend=self.name,
                    version=version,
                    operating_system="linux",
                    architecture=architecture,
                    rootless=rootless,
                    **capability_values,
                ),
            )
        except (RuntimeBackendError, ValueError):
            return RuntimeProbe(RuntimeHealth.UNAVAILABLE, None)

    async def _local_image_record(self, image: ImageIdentity) -> dict[str, object]:
        result = await self._command(
            ("image", "inspect", image.reference),
            phase=RuntimePhase.IMAGE,
            error_code=ErrorCode.IMAGE_IDENTITY_MISMATCH,
        )
        parsed = _decode_json(result.stdout, RuntimePhase.IMAGE, self.name)
        if not isinstance(parsed, list) or len(parsed) != 1 or not isinstance(parsed[0], dict):
            raise _runtime_error(
                ErrorCode.IMAGE_IDENTITY_MISMATCH,
                RuntimePhase.IMAGE,
                self.name,
                "image-inspect-shape-mismatch",
            )
        return parsed[0]

    @staticmethod
    def _manifest_has_platform(
        value: object,
        image: ImageIdentity,
    ) -> bool:
        if not isinstance(value, dict):
            return False
        platform_os, platform_arch = image.platform.split("/", maxsplit=1)
        manifests = value.get("manifests")
        if isinstance(manifests, list):
            for item in manifests:
                if not isinstance(item, dict):
                    continue
                platform = item.get("platform")
                if (
                    item.get("digest") == image.platform_manifest_digest
                    and isinstance(platform, dict)
                    and platform.get("os") == platform_os
                    and _architecture(platform.get("architecture")) == platform_arch
                ):
                    return True
        descriptor = value.get("Descriptor")
        digest = (
            descriptor.get("digest")
            if isinstance(descriptor, dict)
            else value.get("Digest")
        )
        platform = value.get("OCIPlatform") or value.get("Platform")
        return (
            digest == image.platform_manifest_digest
            and isinstance(platform, dict)
            and platform.get("os") == platform_os
            and _architecture(platform.get("architecture")) == platform_arch
        )

    async def inspect_image(self, image: ImageIdentity) -> ImageIdentity:
        if not isinstance(image, ImageIdentity):
            raise TypeError("OCI image inspection requires ImageIdentity.")
        if not self._activation.permits_image(self.name, image):
            raise _runtime_error(
                ErrorCode.IMAGE_NOT_APPROVED,
                RuntimePhase.IMAGE,
                self.name,
                "image-not-product-approved",
            )
        local = await self._local_image_record(image)
        repo_digests = local.get("RepoDigests")
        operating_system = str(local.get("Os", "")).casefold()
        architecture = _architecture(local.get("Architecture"))
        expected_os, expected_arch = image.platform.split("/", maxsplit=1)
        if (
            not isinstance(repo_digests, list)
            or image.reference not in repo_digests
            or operating_system != expected_os
            or architecture != expected_arch
        ):
            raise _runtime_error(
                ErrorCode.IMAGE_IDENTITY_MISMATCH,
                RuntimePhase.IMAGE,
                self.name,
                "local-image-identity-mismatch",
            )
        manifest_arguments = (
            ("manifest", "inspect", "--verbose", image.reference)
            if self.name is RuntimeKind.DOCKER
            else ("manifest", "inspect", image.reference)
        )
        manifest = await self._command(
            manifest_arguments,
            phase=RuntimePhase.IMAGE,
            error_code=ErrorCode.IMAGE_IDENTITY_MISMATCH,
        )
        manifest_value = _decode_json(manifest.stdout, RuntimePhase.IMAGE, self.name)
        if not self._manifest_has_platform(manifest_value, image):
            raise _runtime_error(
                ErrorCode.IMAGE_IDENTITY_MISMATCH,
                RuntimePhase.IMAGE,
                self.name,
                "platform-manifest-digest-mismatch",
            )
        return image

    async def ensure_image(self, image: ImageIdentity) -> ImageIdentity:
        if not isinstance(image, ImageIdentity):
            raise TypeError("OCI image ensure requires ImageIdentity.")
        if not self._activation.permits_image(self.name, image):
            raise _runtime_error(
                ErrorCode.IMAGE_NOT_APPROVED,
                RuntimePhase.IMAGE,
                self.name,
                "image-not-product-approved",
            )
        try:
            probe = await self._runner.run(
                ("image", "inspect", image.reference),
                timeout_ms=30_000,
                output_limit=_CONTROL_OUTPUT_LIMIT,
            )
        except (OSError, TimeoutError):
            raise _runtime_error(
                ErrorCode.RUNTIME_UNAVAILABLE,
                RuntimePhase.IMAGE,
                self.name,
                "runtime-command-unavailable",
            ) from None
        if probe.returncode != 0:
            raise _runtime_error(
                ErrorCode.IMAGE_IDENTITY_MISMATCH,
                RuntimePhase.IMAGE,
                self.name,
                "approved-image-not-local",
            )
        return await self.inspect_image(image)

    def bind_job(self, fence: RuntimeFencingContext) -> _OciRuntimeJobBackend:
        if not isinstance(fence, RuntimeFencingContext):
            raise TypeError("OCI job binding requires RuntimeFencingContext.")
        return _OciRuntimeJobBackend(self, fence)

    async def list_managed(self) -> ManagedObjects:
        return await self._list_managed(None)

    async def _inspect_labels(
        self,
        handle: ContainerHandle | VolumeHandle,
        phase: RuntimePhase,
    ) -> dict[str, str]:
        if isinstance(handle, ContainerHandle):
            arguments = (
                "container",
                "inspect",
                "--format",
                "{{json .Config.Labels}}",
                handle.opaque_id,
            )
            missing_code = ErrorCode.CONTAINER_NOT_FOUND
        elif isinstance(handle, VolumeHandle):
            arguments = (
                "volume",
                "inspect",
                "--format",
                "{{json .Labels}}",
                handle.opaque_id,
            )
            missing_code = ErrorCode.VOLUME_NOT_FOUND
        else:
            raise TypeError("OCI fence inspection requires a runtime handle.")
        try:
            result = await self._runner.run(
                arguments,
                timeout_ms=30_000,
                output_limit=_CONTROL_OUTPUT_LIMIT,
            )
        except (OSError, TimeoutError):
            raise _runtime_error(
                ErrorCode.RUNTIME_UNAVAILABLE,
                phase,
                self.name,
                "runtime-inspect-unavailable",
            ) from None
        if result.returncode != 0:
            diagnostic = result.stderr.decode("utf-8", errors="replace").casefold()
            if any(
                marker in diagnostic
                for marker in ("no such", "not found", "does not exist")
            ):
                raise _runtime_error(
                    missing_code,
                    phase,
                    self.name,
                    "runtime-object-not-found",
                )
            raise _runtime_error(
                ErrorCode.RUNTIME_UNAVAILABLE,
                phase,
                self.name,
                "runtime-inspect-failed",
            )
        value = _decode_json(result.stdout, phase, self.name)
        if (
            not isinstance(value, dict)
            or any(
                not isinstance(key, str) or not isinstance(item, str)
                for key, item in value.items()
            )
        ):
            raise _runtime_error(
                ErrorCode.OPERATION_FENCED,
                phase,
                self.name,
                "runtime-object-labels-invalid",
            )
        return value

    async def _inspect_fence(
        self,
        handle: ContainerHandle | VolumeHandle,
        phase: RuntimePhase,
    ) -> RuntimeFencingContext:
        if handle.backend is not self.name:
            raise _runtime_error(
                ErrorCode.IDENTITY_MISMATCH,
                phase,
                self.name,
                "runtime-handle-backend-mismatch",
            )
        labels = await self._inspect_labels(handle, phase)
        try:
            observed = RuntimeFencingContext.from_labels(labels)
        except RuntimeBackendError:
            raise _runtime_error(
                ErrorCode.OPERATION_FENCED,
                phase,
                self.name,
                "runtime-object-fence-labels-invalid",
            ) from None
        if observed.identity.job_id != handle.job_id:
            raise _runtime_error(
                ErrorCode.IDENTITY_MISMATCH,
                phase,
                self.name,
                "runtime-handle-job-mismatch",
            )
        return observed

    async def _list_names(
        self,
        object_type: str,
        job_id: str | None = None,
    ) -> tuple[str, ...]:
        filters = [
            "--filter",
            f"label={MANAGED_LABEL}={MANAGED_LABEL_VALUE}",
        ]
        if job_id is not None:
            filters.extend(("--filter", f"label=tcad.job_id={job_id}"))
        if object_type == "volume":
            arguments = (
                "volume",
                "ls",
                *filters,
                "--format",
                "{{.Name}}",
            )
        else:
            arguments = (
                "container",
                "ls",
                "--all",
                *filters,
                "--format",
                "{{.Names}}",
            )
        result = await self._command(arguments, phase=RuntimePhase.QUERY)
        try:
            return tuple(
                line.decode("utf-8")
                for line in result.stdout.splitlines()
                if line
            )
        except UnicodeError:
            raise _runtime_error(
                ErrorCode.RUNTIME_UNAVAILABLE,
                RuntimePhase.QUERY,
                self.name,
                "runtime-object-name-invalid",
            ) from None

    async def _list_managed(self, job_id: str | None) -> ManagedObjects:
        volume_names = await self._list_names("volume", job_id)
        container_names = await self._list_names("container", job_id)
        volumes: list[VolumeHandle] = []
        containers: list[ContainerHandle] = []
        nil_job = "00000000-0000-0000-0000-000000000000"
        for name in volume_names:
            provisional = VolumeHandle(self.name, name, job_id or nil_job)
            labels = await self._inspect_labels(provisional, RuntimePhase.QUERY)
            if labels.get(OBJECT_TYPE_LABEL) != "volume":
                continue
            fence = RuntimeFencingContext.from_labels(labels)
            if job_id is None or fence.identity.job_id == job_id:
                volumes.append(VolumeHandle(self.name, name, fence.identity.job_id))
        for name in container_names:
            provisional = ContainerHandle(self.name, name, job_id or nil_job)
            labels = await self._inspect_labels(provisional, RuntimePhase.QUERY)
            if labels.get(OBJECT_TYPE_LABEL) not in {"container", "helper"}:
                continue
            fence = RuntimeFencingContext.from_labels(labels)
            if job_id is None or fence.identity.job_id == job_id:
                containers.append(ContainerHandle(self.name, name, fence.identity.job_id))
        return ManagedObjects(tuple(volumes), tuple(containers))

    @staticmethod
    def _labels(
        fence: RuntimeFencingContext,
        object_type: str,
        extra: Sequence[tuple[str, str]] = (),
    ) -> tuple[str, ...]:
        labels = (
            (MANAGED_LABEL, MANAGED_LABEL_VALUE),
            (OBJECT_TYPE_LABEL, object_type),
            *fence.labels,
            *extra,
        )
        flattened: list[str] = []
        for key, value in labels:
            flattened.extend(("--label", f"{key}={value}"))
        return tuple(flattened)

    @staticmethod
    def _security_arguments(
        spec: ValidatedSandboxSpec,
        *,
        read_only_volume: bool,
    ) -> tuple[str, ...]:
        limits = spec.spec.limits
        mount = (
            f"type=volume,src={spec.identity.volume_name},"
            f"dst=/opentcad/work,readonly={'true' if read_only_volume else 'false'}"
        )
        return (
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--user",
            "65534:65534",
            "--pids-limit",
            str(limits.pids),
            "--memory",
            str(limits.memory_bytes),
            "--memory-swap",
            str(limits.memory_bytes),
            "--cpus",
            format(limits.cpu_millis / 1_000, ".3f"),
            "--restart",
            "no",
            "--pull",
            "never",
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,nodev,size={limits.tmpfs_bytes}",
            "--mount",
            mount,
            "--workdir",
            "/opentcad/work",
        )

    async def _create_helper(
        self,
        fence: RuntimeFencingContext,
        spec: ValidatedSandboxSpec,
        helper_id: str,
        suffix: str,
        *,
        read_only_volume: bool,
        arguments: Sequence[str] = (),
    ) -> ContainerHandle:
        await self.ensure_image(self._configuration.transfer_image)
        entrypoint = self._configuration.entrypoint(helper_id)
        name = f"{fence.identity.object_name}-{suffix}"
        labels = self._labels(
            fence,
            "helper",
            ((ENTRYPOINT_LABEL, helper_id),),
        )
        command = (
            "container",
            "create",
            "--name",
            name,
            *labels,
            *self._security_arguments(spec, read_only_volume=read_only_volume),
            "--entrypoint",
            entrypoint.executable,
            self._configuration.transfer_image.reference,
            *entrypoint.arguments,
            *arguments,
        )
        result = await self._command(
            command,
            phase=RuntimePhase.INPUT if suffix == "input" else RuntimePhase.ARTIFACT,
            error_code=ErrorCode.START_FAILED,
        )
        try:
            opaque_id = result.stdout.decode("utf-8").strip() or name
        except UnicodeError:
            raise _runtime_error(
                ErrorCode.START_FAILED,
                RuntimePhase.CREATE,
                self.name,
                "runtime-helper-id-invalid",
            ) from None
        handle = ContainerHandle(self.name, opaque_id, fence.identity.job_id)
        observed = await self._inspect_fence(handle, RuntimePhase.QUERY)
        enforce_runtime_object_fence(fence, observed, RuntimePhase.QUERY, self.name)
        return handle

    async def _remove_helper(
        self,
        fence: RuntimeFencingContext,
        handle: ContainerHandle,
        phase: RuntimePhase,
    ) -> None:
        observed = await self._inspect_fence(handle, phase)
        enforce_runtime_object_fence(fence, observed, phase, self.name)
        await self._command(
            ("container", "rm", "--force", handle.opaque_id),
            phase=phase,
            error_code=ErrorCode.CLEANUP_FAILED,
        )

    @staticmethod
    def _artifact_records(
        payload: bytes,
        spec: ValidatedSandboxSpec,
    ) -> tuple[ArtifactRecord, ...]:
        records: list[ArtifactRecord] = []
        expected = spec.spec.expected_outputs
        total = 0
        try:
            with tarfile.open(fileobj=BytesIO(payload), mode="r:") as archive:
                for index, member in enumerate(archive):
                    if (
                        index >= len(expected)
                        or member.name != expected[index]
                        or not member.isreg()
                        or member.pax_headers
                        or "/" in member.name
                        or "\\" in member.name
                    ):
                        raise ValueError
                    source = archive.extractfile(member)
                    if source is None:
                        raise ValueError
                    content = source.read(spec.spec.limits.artifact_bytes + 1)
                    if len(content) != member.size:
                        raise ValueError
                    total += len(content)
                    if total > spec.spec.limits.artifact_bytes:
                        raise ValueError
                    records.append(
                        ArtifactRecord(
                            member.name,
                            sha256(content).hexdigest(),
                            len(content),
                        ),
                    )
        except (EOFError, OSError, tarfile.TarError, ValueError):
            raise RuntimeBackendError(
                ErrorCode.OUTPUT_ARCHIVE_REJECTED,
                RuntimePhase.ARTIFACT,
                detail="runtime-artifact-archive-invalid",
            ) from None
        if tuple(item.name for item in records) != expected:
            raise RuntimeBackendError(
                ErrorCode.OUTPUT_ARCHIVE_REJECTED,
                RuntimePhase.ARTIFACT,
                detail="runtime-artifact-manifest-mismatch",
            )
        return tuple(records)

    async def _export_artifacts(
        self,
        fence: RuntimeFencingContext,
        spec: ValidatedSandboxSpec,
    ) -> tuple[RawArtifactArchive, tuple[ArtifactRecord, ...]]:
        helper = await self._create_helper(
            fence,
            spec,
            self._configuration.output_helper_id,
            "output",
            read_only_volume=True,
            arguments=spec.spec.expected_outputs,
        )
        limit = (
            spec.spec.limits.artifact_bytes
            + spec.spec.limits.file_count * 1_024
            + 10_240
        )
        try:
            result = await self._command(
                ("container", "start", "--attach", helper.opaque_id),
                phase=RuntimePhase.ARTIFACT,
                timeout_ms=spec.spec.limits.timeout_ms,
                output_limit=limit,
                error_code=ErrorCode.OUTPUT_ARCHIVE_REJECTED,
            )
            if result.truncated:
                raise RuntimeBackendError(
                    ErrorCode.OUTPUT_ARCHIVE_REJECTED,
                    RuntimePhase.ARTIFACT,
                    backend=self.name.value,
                    detail="runtime-artifact-output-limit",
                )
            records = self._artifact_records(result.stdout, spec)
            return RawArtifactArchive(result.stdout), records
        finally:
            await self._remove_helper(fence, helper, RuntimePhase.CLEANUP)


class _OciRuntimeJobBackend:
    def __init__(
        self,
        backend: OciRuntimeBackend,
        fence: RuntimeFencingContext,
    ) -> None:
        self._backend = backend
        self._fence = fence

    @property
    def fence(self) -> RuntimeFencingContext:
        return self._fence

    async def _invoke(self, phase: RuntimePhase, operation):
        authority = self._backend.fence_authority
        if (
            isinstance(authority, ProductRuntimeFenceAuthority)
            and phase is not RuntimePhase.WAIT
        ):
            async with authority.operation_guard(
                self._fence,
                phase=phase,
                backend=self._backend.name,
            ):
                return await operation()
        await authority.verify(
            self._fence,
            phase=phase,
            backend=self._backend.name,
        )
        try:
            return await operation()
        finally:
            await asyncio.shield(
                authority.verify(
                    self._fence,
                    phase=phase,
                    backend=self._backend.name,
                ),
            )

    async def create_volume(self) -> VolumeHandle:
        async def operation() -> VolumeHandle:
            name = self._fence.identity.volume_name
            labels = self._backend._labels(self._fence, "volume")
            result = await self._backend._command(
                ("volume", "create", "--name", name, *labels),
                phase=RuntimePhase.VOLUME,
                error_code=ErrorCode.START_FAILED,
            )
            try:
                opaque_id = result.stdout.decode("utf-8").strip() or name
            except UnicodeError:
                raise _runtime_error(
                    ErrorCode.START_FAILED,
                    RuntimePhase.VOLUME,
                    self._backend.name,
                    "runtime-volume-id-invalid",
                ) from None
            handle = VolumeHandle(
                self._backend.name,
                opaque_id,
                self._fence.identity.job_id,
            )
            observed = await self._backend._inspect_fence(
                handle,
                RuntimePhase.VOLUME,
            )
            enforce_runtime_object_fence(
                self._fence,
                observed,
                RuntimePhase.VOLUME,
                self._backend.name,
            )
            return handle

        return await self._invoke(RuntimePhase.VOLUME, operation)

    async def stage_inputs(
        self,
        volume: VolumeHandle,
        spec: ValidatedSandboxSpec,
        archive: ValidatedInputArchive,
    ) -> None:
        async def operation() -> None:
            if (
                spec.identity != self._fence.identity
                or volume.job_id != self._fence.identity.job_id
            ):
                raise _runtime_error(
                    ErrorCode.IDENTITY_MISMATCH,
                    RuntimePhase.INPUT,
                    self._backend.name,
                    "input-job-identity-mismatch",
                )
            observed = await self._backend._inspect_fence(
                volume,
                RuntimePhase.INPUT,
            )
            enforce_runtime_object_fence(
                self._fence,
                observed,
                RuntimePhase.INPUT,
                self._backend.name,
            )
            helper = await self._backend._create_helper(
                self._fence,
                spec,
                self._backend._configuration.input_helper_id,
                "input",
                read_only_volume=False,
            )
            try:
                await self._backend._command(
                    (
                        "container",
                        "start",
                        "--attach",
                        "--interactive",
                        helper.opaque_id,
                    ),
                    phase=RuntimePhase.INPUT,
                    input_bytes=archive.payload,
                    timeout_ms=spec.spec.limits.timeout_ms,
                    output_limit=_CONTROL_OUTPUT_LIMIT,
                    error_code=ErrorCode.INPUT_ARCHIVE_REJECTED,
                )
            finally:
                await self._backend._remove_helper(
                    self._fence,
                    helper,
                    RuntimePhase.CLEANUP,
                )

        await self._invoke(RuntimePhase.INPUT, operation)

    async def create_container(
        self,
        spec: ValidatedSandboxSpec,
        volume: VolumeHandle,
    ) -> ContainerHandle:
        async def operation() -> ContainerHandle:
            if (
                spec.identity != self._fence.identity
                or volume.job_id != self._fence.identity.job_id
            ):
                raise _runtime_error(
                    ErrorCode.IDENTITY_MISMATCH,
                    RuntimePhase.CREATE,
                    self._backend.name,
                    "container-job-identity-mismatch",
                )
            if not self._backend._activation.permits(
                self._backend.name,
                spec.spec.image,
                spec.entrypoint_id,
            ):
                raise _runtime_error(
                    ErrorCode.IMAGE_NOT_APPROVED,
                    RuntimePhase.CREATE,
                    self._backend.name,
                    "workload-not-product-approved",
                )
            observed = await self._backend._inspect_fence(
                volume,
                RuntimePhase.CREATE,
            )
            enforce_runtime_object_fence(
                self._fence,
                observed,
                RuntimePhase.CREATE,
                self._backend.name,
            )
            entrypoint = self._backend._configuration.entrypoint(
                spec.entrypoint_id,
            )
            labels = self._backend._labels(
                self._fence,
                "container",
                (
                    *spec.labels,
                    (ENTRYPOINT_LABEL, spec.entrypoint_id),
                    (OUTPUT_LIMIT_LABEL, str(spec.spec.limits.output_bytes)),
                ),
            )
            command = (
                "container",
                "create",
                "--name",
                self._fence.identity.object_name,
                *labels,
                *self._backend._security_arguments(
                    spec,
                    read_only_volume=False,
                ),
                "--entrypoint",
                entrypoint.executable,
                spec.spec.image.reference,
                *entrypoint.arguments,
            )
            result = await self._backend._command(
                command,
                phase=RuntimePhase.CREATE,
                error_code=ErrorCode.START_FAILED,
            )
            try:
                opaque_id = (
                    result.stdout.decode("utf-8").strip()
                    or self._fence.identity.object_name
                )
            except UnicodeError:
                raise _runtime_error(
                    ErrorCode.START_FAILED,
                    RuntimePhase.CREATE,
                    self._backend.name,
                    "runtime-container-id-invalid",
                ) from None
            handle = ContainerHandle(
                self._backend.name,
                opaque_id,
                self._fence.identity.job_id,
            )
            object_fence = await self._backend._inspect_fence(
                handle,
                RuntimePhase.CREATE,
            )
            enforce_runtime_object_fence(
                self._fence,
                object_fence,
                RuntimePhase.CREATE,
                self._backend.name,
            )
            self._backend._specs[handle.opaque_id] = spec
            return handle

        return await self._invoke(RuntimePhase.CREATE, operation)

    async def start(self, container: ContainerHandle) -> None:
        async def operation() -> None:
            observed = await self._backend._inspect_fence(
                container,
                RuntimePhase.START,
            )
            enforce_runtime_object_fence(
                self._fence,
                observed,
                RuntimePhase.START,
                self._backend.name,
            )
            await self._backend._command(
                ("container", "start", container.opaque_id),
                phase=RuntimePhase.START,
                error_code=ErrorCode.START_FAILED,
            )

        await self._invoke(RuntimePhase.START, operation)

    async def _terminal_result(
        self,
        container: ContainerHandle,
        classification_override: TerminalClassification | None = None,
        *,
        export_artifacts: bool = True,
    ) -> RunResult:
        spec = self._backend._specs.get(container.opaque_id)
        if spec is None and classification_override is None:
            raise _runtime_error(
                ErrorCode.INVALID_STATE,
                RuntimePhase.WAIT,
                self._backend.name,
                "runtime-spec-not-resident",
            )
        if spec is None:
            labels = await self._backend._inspect_labels(
                container,
                RuntimePhase.WAIT,
            )
            output_limit = _recovery_output_limit(
                labels,
                self._backend.name,
            )
            wait_timeout_ms = _RECOVERY_WAIT_TIMEOUT_MS
        else:
            output_limit = spec.spec.limits.output_bytes
            wait_timeout_ms = spec.spec.limits.timeout_ms
        wait = await self._backend._command(
            ("container", "wait", container.opaque_id),
            phase=RuntimePhase.WAIT,
            timeout_ms=wait_timeout_ms,
            error_code=ErrorCode.WAIT_FAILED,
        )
        try:
            exit_code = int(wait.stdout.decode("ascii").strip())
        except (UnicodeError, ValueError):
            raise _runtime_error(
                ErrorCode.WAIT_FAILED,
                RuntimePhase.WAIT,
                self._backend.name,
                "runtime-exit-code-invalid",
            ) from None
        logs = await self._backend._command(
            ("container", "logs", container.opaque_id),
            phase=RuntimePhase.WAIT,
            output_limit=output_limit,
            error_code=ErrorCode.WAIT_FAILED,
        )
        inspect = await self._backend._command(
            (
                "container",
                "inspect",
                "--format",
                "{{json .State}}",
                container.opaque_id,
            ),
            phase=RuntimePhase.WAIT,
            error_code=ErrorCode.WAIT_FAILED,
        )
        state = _decode_json(
            inspect.stdout,
            RuntimePhase.WAIT,
            self._backend.name,
        )
        if not isinstance(state, dict):
            raise _runtime_error(
                ErrorCode.WAIT_FAILED,
                RuntimePhase.WAIT,
                self._backend.name,
                "runtime-state-invalid",
            )
        started = _parse_time(state.get("StartedAt"))
        finished = _parse_time(state.get("FinishedAt"))
        duration_ms = (
            max(0, int((finished - started).total_seconds() * 1_000))
            if started is not None and finished is not None
            else wait.duration_ms
        )
        if classification_override is not None:
            classification = classification_override
        elif bool(state.get("OOMKilled")):
            classification = TerminalClassification.OOM_KILLED
        elif logs.truncated:
            classification = TerminalClassification.OUTPUT_LIMIT_EXCEEDED
        elif exit_code == 0:
            classification = TerminalClassification.SUCCEEDED
        else:
            classification = TerminalClassification.NONZERO_EXIT

        artifacts: tuple[ArtifactRecord, ...] = ()
        if (
            classification is TerminalClassification.SUCCEEDED
            and export_artifacts
            and spec is not None
        ):
            archive, artifacts = await self._backend._export_artifacts(
                self._fence,
                spec,
            )
            self._backend._artifact_archives[container.opaque_id] = archive
        return RunResult(
            classification,
            exit_code,
            duration_ms,
            output_limit,
            logs.observed_bytes,
            logs.captured_bytes,
            logs.truncated,
            logs.stdout_sha256,
            logs.stderr_sha256,
            artifacts,
        )

    async def wait(self, container: ContainerHandle) -> RunResult:
        async def observe() -> RunResult:
            observed = await self._backend._inspect_fence(
                container,
                RuntimePhase.WAIT,
            )
            enforce_runtime_object_fence(
                self._fence,
                observed,
                RuntimePhase.WAIT,
                self._backend.name,
            )
            return await self._terminal_result(
                container,
                export_artifacts=False,
            )

        result = await self._invoke(RuntimePhase.WAIT, observe)
        if result.classification is not TerminalClassification.SUCCEEDED:
            return result

        async def export() -> RunResult:
            observed = await self._backend._inspect_fence(
                container,
                RuntimePhase.ARTIFACT,
            )
            enforce_runtime_object_fence(
                self._fence,
                observed,
                RuntimePhase.ARTIFACT,
                self._backend.name,
            )
            spec = self._backend._specs.get(container.opaque_id)
            if spec is None:
                raise _runtime_error(
                    ErrorCode.INVALID_STATE,
                    RuntimePhase.ARTIFACT,
                    self._backend.name,
                    "runtime-spec-not-resident",
                )
            archive, artifacts = await self._backend._export_artifacts(
                self._fence,
                spec,
            )
            self._backend._artifact_archives[container.opaque_id] = archive
            return replace(result, artifacts=artifacts)

        return await self._invoke(RuntimePhase.ARTIFACT, export)

    async def kill(
        self,
        container: ContainerHandle,
        reason: TerminationReason,
    ) -> RunResult:
        if not isinstance(reason, TerminationReason):
            raise TypeError("OCI kill requires TerminationReason.")

        async def operation() -> RunResult:
            observed = await self._backend._inspect_fence(
                container,
                RuntimePhase.KILL,
            )
            enforce_runtime_object_fence(
                self._fence,
                observed,
                RuntimePhase.KILL,
                self._backend.name,
            )
            if container.opaque_id not in self._backend._specs:
                labels = await self._backend._inspect_labels(
                    container,
                    RuntimePhase.WAIT,
                )
                _recovery_output_limit(labels, self._backend.name)
            await self._backend._command(
                ("container", "kill", container.opaque_id),
                phase=RuntimePhase.KILL,
                error_code=ErrorCode.KILL_FAILED,
            )
            classification = {
                TerminationReason.TIMEOUT: TerminalClassification.TIMED_OUT,
                TerminationReason.OUTPUT_LIMIT: (
                    TerminalClassification.OUTPUT_LIMIT_EXCEEDED
                ),
                TerminationReason.CANCELLATION: TerminalClassification.CANCELLED,
                TerminationReason.SHUTDOWN: TerminalClassification.CANCELLED,
            }[reason]
            return await self._terminal_result(container, classification)

        return await self._invoke(RuntimePhase.KILL, operation)

    async def collect_artifacts(
        self,
        container: ContainerHandle,
    ) -> RawArtifactArchive:
        async def operation() -> RawArtifactArchive:
            observed = await self._backend._inspect_fence(
                container,
                RuntimePhase.ARTIFACT,
            )
            enforce_runtime_object_fence(
                self._fence,
                observed,
                RuntimePhase.ARTIFACT,
                self._backend.name,
            )
            archive = self._backend._artifact_archives.get(container.opaque_id)
            if archive is None:
                raise RuntimeBackendError(
                    ErrorCode.OUTPUT_ARCHIVE_REJECTED,
                    RuntimePhase.ARTIFACT,
                    backend=self._backend.name.value,
                    detail="runtime-artifact-not-collected",
                )
            return archive

        return await self._invoke(RuntimePhase.ARTIFACT, operation)

    async def inspect_fence(
        self,
        handle: ContainerHandle | VolumeHandle,
    ) -> RuntimeFencingContext:
        return await self._invoke(
            RuntimePhase.QUERY,
            lambda: self._backend._inspect_fence(handle, RuntimePhase.QUERY),
        )

    async def remove_container(self, container: ContainerHandle) -> None:
        async def operation() -> None:
            try:
                observed = await self._backend._inspect_fence(
                    container,
                    RuntimePhase.CLEANUP,
                )
            except RuntimeBackendError as error:
                if error.code is ErrorCode.CONTAINER_NOT_FOUND:
                    return
                raise
            enforce_runtime_object_fence(
                self._fence,
                observed,
                RuntimePhase.CLEANUP,
                self._backend.name,
            )
            await self._backend._command(
                ("container", "rm", "--force", container.opaque_id),
                phase=RuntimePhase.CLEANUP,
                error_code=ErrorCode.CLEANUP_FAILED,
            )
            self._backend._specs.pop(container.opaque_id, None)
            self._backend._artifact_archives.pop(container.opaque_id, None)

        await self._invoke(RuntimePhase.CLEANUP, operation)

    async def remove_volume(self, volume: VolumeHandle) -> None:
        async def operation() -> None:
            try:
                observed = await self._backend._inspect_fence(
                    volume,
                    RuntimePhase.CLEANUP,
                )
            except RuntimeBackendError as error:
                if error.code is ErrorCode.VOLUME_NOT_FOUND:
                    return
                raise
            enforce_runtime_object_fence(
                self._fence,
                observed,
                RuntimePhase.CLEANUP,
                self._backend.name,
            )
            await self._backend._command(
                ("volume", "rm", volume.opaque_id),
                phase=RuntimePhase.CLEANUP,
                error_code=ErrorCode.CLEANUP_FAILED,
            )

        await self._invoke(RuntimePhase.CLEANUP, operation)

    async def list_managed(self) -> ManagedObjects:
        async def operation() -> ManagedObjects:
            managed = await self._backend._list_managed(
                self._fence.identity.job_id,
            )
            for handle in (*managed.volumes, *managed.containers):
                observed = await self._backend._inspect_fence(
                    handle,
                    RuntimePhase.QUERY,
                )
                enforce_runtime_object_fence(
                    self._fence,
                    observed,
                    RuntimePhase.QUERY,
                    self._backend.name,
                )
            return managed

        return await self._invoke(RuntimePhase.QUERY, operation)
