"""Live, non-promoting Docker/Podman conformance for the M3 OCI adapter.

This module deliberately mints authority only from a temporary validation
manifest. It never reads or modifies the product entry-gate manifest and every
record it emits remains ineligible for product, solver, baseline, or platform
approval.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import sys
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Any
from uuid import uuid4

from backend.app.broker.archive import (
    ArchiveLimits,
    InputPayload,
    build_canonical_input_archive,
    validate_canonical_input_archive,
)
from backend.app.broker.output_archive import (
    ArtifactPayload,
    build_canonical_output_archive,
    output_archive_limits,
)
from backend.app.product import M3_GATE_IDS, M3ProductGate, ProductGateError
from backend.app.runtime.errors import ErrorCode, RuntimeBackendError, RuntimePhase
from backend.app.runtime.fencing import RuntimeFencingContext
from backend.app.runtime.models import (
    ContainerHandle,
    ImageIdentity,
    InputFile,
    JobIdentity,
    JobKind,
    ResourceLimits,
    RuntimeHealth,
    RuntimeKind,
    SandboxSpec,
    TerminalClassification,
    TerminationReason,
    VolumeHandle,
)
from backend.app.runtime.oci_backend import (
    MANAGED_LABEL,
    MANAGED_LABEL_VALUE,
    OBJECT_TYPE_LABEL,
    OciAdapterConfiguration,
    OciCommandOutputLimitExceeded,
    OciCommandResult,
    OciEntrypoint,
    OciRuntimeBackend,
)
from backend.app.runtime.policy import EngineProfile, SandboxPolicy
from backend.app.runtime.product_fence_authority import ProductRuntimeFenceAuthority


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REVIEWED_PLAN = REPOSITORY_ROOT / "validation" / "plans" / "m3-native-adapter-conformance.json"
FIXTURE_ROOT = REPOSITORY_ROOT / "validation" / "fixtures" / "m3-runtime"
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
WSL_DISTRIBUTION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
FIXTURE_FILES = (
    "Containerfile",
    "archive-export",
    "archive-import",
    "workload-nonzero",
    "workload-output-bomb",
    "workload-sleep",
    "workload-success",
)
ENTRYPOINTS = (
    OciEntrypoint("fixture-archive-import", "/opentcad/bin/archive-import"),
    OciEntrypoint("fixture-archive-export", "/opentcad/bin/archive-export"),
    OciEntrypoint("fixture-success", "/opentcad/bin/workload-success"),
    OciEntrypoint("fixture-nonzero", "/opentcad/bin/workload-nonzero"),
    OciEntrypoint("fixture-sleep", "/opentcad/bin/workload-sleep"),
    OciEntrypoint("fixture-output-bomb", "/opentcad/bin/workload-output-bomb"),
)
SCENARIO_IDS = (
    "success-lifecycle",
    "declared-nonzero",
    "external-cancellation",
    "timeout-classification",
    "output-bomb-classification",
    "stale-fence-no-native-call",
    "concurrent-cleanup-idempotence",
)
INPUT_CONTENT = b"OpenTCAD M3 fixture input\n"
OUTPUT_CONTENT = b"OpenTCAD M3 fixture result\n"
INPUT_FILE = InputFile("input.in", sha256(INPUT_CONTENT).hexdigest(), len(INPUT_CONTENT))
OUTPUT_NAME = "result.str"
SAFE_ENVIRONMENT = (
    "PATH",
    "HOME",
    "USERPROFILE",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "DOCKER_CONFIG",
    "XDG_RUNTIME_DIR",
    "XDG_CONFIG_HOME",
    "CONTAINERS_CONF",
    "CONTAINERS_STORAGE_CONF",
    "WSLENV",
    "WSL_INTEROP",
    "WSL_DISTRO_NAME",
)
NON_PROMOTION_FIELDS: dict[str, object] = {
    "qualified": False,
    "approvalGranted": False,
    "baselinePromotionAllowed": False,
    "releaseImageApproved": False,
    "solverApprovalGranted": False,
    "platformApprovalGranted": False,
    "distributionAllowed": False,
    "usesProductRuntimeAdapter": True,
    "usesSolver": False,
    "productEntryGateManifestModified": False,
    "productReleaseProfileModified": False,
}


class ContractError(ValueError):
    """Stable local validation error for the observation harness."""


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ContractError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def fixture_source_sha256(root: Path = FIXTURE_ROOT) -> str:
    """Hash the reviewed path, file size, and bytes in canonical name order."""

    digest = sha256()
    for relative_name in FIXTURE_FILES:
        path = root / relative_name
        _require(path.is_file() and not path.is_symlink(), f"fixture file invalid: {relative_name}")
        payload = path.read_bytes()
        digest.update(relative_name.encode("ascii"))
        digest.update(b"\0")
        digest.update(str(len(payload)).encode("ascii"))
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return digest.hexdigest()


def load_reviewed_plan(path: Path = REVIEWED_PLAN) -> dict[str, Any]:
    actual = path.resolve(strict=True)
    _require(actual == REVIEWED_PLAN.resolve(strict=True), "only the reviewed M3 plan may run")
    raw = actual.read_bytes()
    _require(0 < len(raw) <= 256 * 1024, "M3 plan size invalid")
    try:
        plan = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ContractError("M3 plan JSON invalid") from error
    _require(isinstance(plan, dict), "M3 plan must be an object")
    _require(plan.get("schemaVersion") == 1, "M3 plan schema invalid")
    _require(plan.get("milestone") == "M3", "M3 plan milestone invalid")
    _require(plan.get("observationId") == "M3-NATIVE-ADAPTER-001", "M3 observation id invalid")
    _require(
        plan.get("classification") == "non-promoting-native-adapter-conformance",
        "M3 classification invalid",
    )
    for field_name in (
        "qualified",
        "approvalGranted",
        "baselinePromotionAllowed",
        "releaseImageApproved",
        "solverApprovalGranted",
        "platformApprovalGranted",
    ):
        _require(plan.get(field_name) is False, f"{field_name} must remain false")
    fixture = plan.get("fixture")
    _require(isinstance(fixture, dict), "fixture plan invalid")
    _require(fixture.get("engineFree") is True, "fixture must remain engine-free")
    _require(fixture.get("sourcePath") == "validation/fixtures/m3-runtime", "fixture path invalid")
    _require(fixture.get("files") == list(FIXTURE_FILES), "fixture file inventory invalid")
    _require(
        fixture.get("sourceSha256") == fixture_source_sha256(),
        "fixture source hash drifted",
    )
    _require(
        fixture.get("referenceBase") == "localhost:5001/opentcad-m3-runtime-fixture",
        "fixture reference base invalid",
    )
    _require(fixture.get("provisioning") == "external-digest-preload", "fixture provisioning invalid")
    _require(fixture.get("observerPullsImage") is False, "observer must not pull images")
    _require(fixture.get("observerBuildsImage") is False, "observer must not build images")
    _require(fixture.get("observerRemovesImage") is False, "observer must not remove shared images")
    scenarios = plan.get("scenarios")
    _require(isinstance(scenarios, list), "scenario plan invalid")
    _require(tuple(item.get("id") for item in scenarios if isinstance(item, dict)) == SCENARIO_IDS, "scenario sequence invalid")
    _require(
        scenarios[4].get("streamingOutputTerminationProven") is True,
        "streaming output termination proof must be required",
    )
    cleanup = plan.get("cleanup")
    _require(isinstance(cleanup, dict), "cleanup plan invalid")
    _require(cleanup.get("exactObjectRemoval") is True, "exact cleanup required")
    _require(cleanup.get("globalPruneAllowed") is False, "global prune forbidden")
    _require(cleanup.get("expectedContainers") == 0, "container orphan floor invalid")
    _require(cleanup.get("expectedVolumes") == 0, "volume orphan floor invalid")
    required_proofs = plan.get("requiredProofs")
    _require(isinstance(required_proofs, dict), "required proof plan invalid")
    _require(
        required_proofs.get("streamingOutputTerminationProven") is True,
        "streaming output termination proof must be required",
    )
    _require(
        required_proofs.get("offlineLocalImageInspectionProven") is True,
        "offline local image inspection proof must be required",
    )
    _require(
        required_proofs.get("manifestInspectCommands") == 0,
        "manifest inspect command floor invalid",
    )
    evidence = plan.get("evidence")
    _require(isinstance(evidence, dict), "evidence plan invalid")
    _require(evidence.get("rawInsideRepository") is False, "raw evidence must remain external")
    _require(evidence.get("automaticPromotion") is False, "automatic promotion forbidden")
    return plan


@dataclass(frozen=True, slots=True)
class RuntimeTransport:
    runtime: RuntimeKind
    executable: str
    prefix: tuple[str, ...]
    launcher: str
    distribution: str | None

    @classmethod
    def select(
        cls,
        runtime: RuntimeKind,
        *,
        system_name: str | None = None,
        wsl_distribution: str | None = None,
    ) -> RuntimeTransport:
        system_value = (system_name or platform.system()).casefold()
        if runtime is RuntimeKind.DOCKER:
            _require(wsl_distribution is None, "Docker does not accept a WSL distribution")
            executable = "docker.exe" if system_value == "windows" else "docker"
            return cls(runtime, executable, (), "docker", None)
        if runtime is not RuntimeKind.PODMAN:
            raise ContractError("runtime must be docker or podman")
        if system_value == "windows":
            _require(wsl_distribution == "Debian", "Windows Podman requires the reviewed Debian WSL transport")
            _require(WSL_DISTRIBUTION_PATTERN.fullmatch(wsl_distribution) is not None, "WSL distribution invalid")
            return cls(
                runtime,
                "wsl.exe",
                ("-d", wsl_distribution, "--", "podman", "--cgroup-manager=cgroupfs"),
                "wsl",
                wsl_distribution,
            )
        _require(wsl_distribution is None, "WSL distribution is Windows-only")
        return cls(runtime, "podman", (), "podman", None)

    def as_record(self) -> dict[str, object]:
        return {
            "launcher": self.launcher,
            "runtimeExecutable": self.runtime.value,
            "distribution": self.distribution,
            "prefixApplied": bool(self.prefix),
        }


@dataclass(slots=True)
class CommandObservation:
    ordinal: int
    operation: str
    argv_sha256: str
    input_bytes: int
    input_sha256: str | None
    status: str
    return_code: int | None = None
    duration_ms: int | None = None
    observed_stdout_bytes: int = 0
    observed_stderr_bytes: int = 0
    captured_stdout_bytes: int = 0
    captured_stderr_bytes: int = 0
    stdout_sha256: str | None = None
    stderr_sha256: str | None = None

    def as_record(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "operation": self.operation,
            "argvSha256": self.argv_sha256,
            "inputBytes": self.input_bytes,
            "inputSha256": self.input_sha256,
            "status": self.status,
            "returnCode": self.return_code,
            "durationMs": self.duration_ms,
            "observedStdoutBytes": self.observed_stdout_bytes,
            "observedStderrBytes": self.observed_stderr_bytes,
            "capturedStdoutBytes": self.captured_stdout_bytes,
            "capturedStderrBytes": self.captured_stderr_bytes,
            "stdoutSha256": self.stdout_sha256,
            "stderrSha256": self.stderr_sha256,
        }


class ObservedPrefixedOciRunner:
    """Shell-free runner matching the product runner with a fixed WSL prefix."""

    def __init__(self, transport: RuntimeTransport, environment: Mapping[str, str] | None = None) -> None:
        resolved = shutil.which(transport.executable)
        if resolved is None:
            raise FileNotFoundError(transport.executable)
        self._executable = resolved
        self._prefix = transport.prefix
        source = os.environ if environment is None else environment
        self._environment = {
            key: source[key]
            for key in SAFE_ENVIRONMENT
            if key in source and isinstance(source[key], str)
        }
        self._environment["LANG"] = "C"
        self._environment["LC_ALL"] = "C"
        self.observations: list[CommandObservation] = []

    @property
    def command_count(self) -> int:
        return len(self.observations)

    async def run(
        self,
        arguments: Sequence[str],
        *,
        input_bytes: bytes | None = None,
        timeout_ms: int = 30_000,
        output_limit: int = 1_048_576,
        terminate_on_output_limit: bool = False,
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
            or not isinstance(terminate_on_output_limit, bool)
            or (input_bytes is not None and not isinstance(input_bytes, bytes))
        ):
            raise TypeError("OCI command request is invalid")
        encoded_argv = json.dumps(values, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        observation = CommandObservation(
            len(self.observations) + 1,
            " ".join(values[:2]),
            sha256(encoded_argv).hexdigest(),
            len(input_bytes or b""),
            sha256(input_bytes).hexdigest() if input_bytes is not None else None,
            "running",
        )
        self.observations.append(observation)
        started = monotonic()
        process = await asyncio.create_subprocess_exec(
            self._executable,
            *self._prefix,
            *values,
            stdin=asyncio.subprocess.PIPE if input_bytes is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._environment,
        )
        remaining = output_limit
        limit_exceeded = False

        async def capture(stream: asyncio.StreamReader) -> tuple[bytes, int, str]:
            nonlocal limit_exceeded, remaining
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
                if accepted < len(block):
                    limit_exceeded = True
                    if terminate_on_output_limit and process.returncode is None:
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
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
            raise RuntimeError("OCI subprocess pipes unavailable")
        stdout_task = asyncio.create_task(capture(process.stdout))
        stderr_task = asyncio.create_task(capture(process.stderr))
        input_task = asyncio.create_task(send_input())
        try:
            await asyncio.wait_for(
                asyncio.gather(process.wait(), input_task),
                timeout=timeout_ms / 1_000,
            )
            stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
        except BaseException as error:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await asyncio.shield(process.wait())
            input_task.cancel()
            await asyncio.shield(
                asyncio.gather(stdout_task, stderr_task, input_task, return_exceptions=True),
            )
            observation.status = "timed-out" if isinstance(error, TimeoutError) else "interrupted"
            observation.duration_ms = int((monotonic() - started) * 1_000)
            raise
        duration_ms = int((monotonic() - started) * 1_000)
        observation.status = "completed"
        observation.return_code = process.returncode
        observation.duration_ms = duration_ms
        observation.observed_stdout_bytes = stdout[1]
        observation.observed_stderr_bytes = stderr[1]
        observation.captured_stdout_bytes = len(stdout[0])
        observation.captured_stderr_bytes = len(stderr[0])
        observation.stdout_sha256 = stdout[2]
        observation.stderr_sha256 = stderr[2]
        result = OciCommandResult(
            process.returncode,
            stdout[0],
            stderr[0],
            stdout[1],
            stderr[1],
            stdout[2],
            stderr[2],
            duration_ms,
        )
        if terminate_on_output_limit and limit_exceeded:
            observation.status = "output-limit-exceeded"
            raise OciCommandOutputLimitExceeded(result)
        return result


@dataclass(frozen=True, slots=True)
class ObserverOptions:
    runtime: RuntimeKind
    transport: RuntimeTransport
    image: ImageIdentity
    output: Path
    recorded_at: str


@dataclass(slots=True)
class ScenarioResources:
    job_id: str | None = None
    fences: list[RuntimeFencingContext] = field(default_factory=list)
    bound: Any | None = None
    volume: VolumeHandle | None = None
    container: ContainerHandle | None = None
    started: bool = False
    terminal: bool = False


@dataclass(slots=True)
class ScenarioResult:
    scenario_id: str
    passed: bool
    expected: str
    observed: str
    error: dict[str, object] | None
    cleanup: dict[str, object]
    details: dict[str, object] = field(default_factory=dict)

    def as_record(self) -> dict[str, object]:
        return {
            "id": self.scenario_id,
            "pass": self.passed,
            "expected": self.expected,
            "observed": self.observed,
            "error": self.error,
            "cleanup": self.cleanup,
            "details": self.details,
        }


def stable_error(error: BaseException) -> dict[str, object]:
    if isinstance(error, RuntimeBackendError):
        return {
            "type": "runtime-backend-error",
            "code": error.code.value,
            "phase": error.phase.value,
            "detail": error.record.detail,
        }
    if isinstance(error, ContractError):
        return {"type": "contract-error", "code": "observation-contract-rejected"}
    if isinstance(error, ProductGateError):
        return {"type": "product-gate-error", "code": error.code.value}
    if isinstance(error, TimeoutError):
        return {"type": "timeout-error", "code": "observer-timeout"}
    return {"type": type(error).__name__, "code": "unexpected-observation-error"}


def local_image_inspection_proof(
    observations: Sequence[CommandObservation],
) -> dict[str, object]:
    """Summarize only the commands used by the image preflight."""

    image_inspects = sum(item.operation == "image inspect" for item in observations)
    manifest_inspects = sum(item.operation == "manifest inspect" for item in observations)
    image_pulls = sum(item.operation == "image pull" for item in observations)
    return {
        "offlineLocalImageInspectionProven": (
            image_inspects > 0
            and manifest_inspects == 0
            and image_pulls == 0
        ),
        "imageInspectCommands": image_inspects,
        "manifestInspectCommands": manifest_inspects,
        "imagePullCommands": image_pulls,
    }


def prepare_external_output(requested: Path, repository_root: Path = REPOSITORY_ROOT) -> Path:
    if not requested.is_absolute():
        raise ContractError("output must be absolute")
    repository = repository_root.resolve(strict=True)
    parent = requested.parent.resolve(strict=True)
    output = parent / requested.name
    try:
        output.relative_to(repository)
    except ValueError:
        pass
    else:
        raise ContractError("raw native evidence must remain outside the repository")
    if output.exists() or output.is_symlink():
        raise ContractError("output must not already exist")
    output.mkdir(mode=0o700)
    (output / "state").mkdir(mode=0o700)
    return output


def image_from_arguments(
    reference: str,
    index_digest: str,
    platform_manifest_digest: str,
    image_platform: str,
    plan: Mapping[str, Any],
) -> ImageIdentity:
    if not isinstance(reference, str) or reference.count("@") != 1:
        raise ContractError("fixture reference must be digest-pinned")
    reference_base, reference_digest = reference.split("@", maxsplit=1)
    fixture = plan["fixture"]
    if reference_base != fixture["referenceBase"]:
        raise ContractError("fixture reference base is not reviewed")
    if DIGEST_PATTERN.fullmatch(index_digest) is None:
        raise ContractError("fixture index digest invalid")
    if reference_digest != index_digest:
        raise ContractError("fixture reference and index digest differ")
    if DIGEST_PATTERN.fullmatch(platform_manifest_digest) is None:
        raise ContractError("fixture platform manifest digest invalid")
    try:
        return ImageIdentity(reference, index_digest, platform_manifest_digest, image_platform)
    except RuntimeBackendError as error:
        raise ContractError("fixture image identity invalid") from error


def parse_recorded_at(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ContractError("recorded-at must be ISO-compatible") from error
    if parsed.tzinfo is None:
        raise ContractError("recorded-at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _temporary_activation(image: ImageIdentity, runtime: RuntimeKind, recorded_at: str, root: Path):
    if runtime not in {RuntimeKind.DOCKER, RuntimeKind.PODMAN}:
        raise ContractError("validation activation runtime invalid")
    approval_at = (
        datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    evidence_payload = b"OpenTCAD M3 native adapter validation authority only\n"
    evidence = root / "validation-authority.txt"
    evidence.write_bytes(evidence_payload)
    evidence_record = {
        "path": evidence.name,
        "sha256": sha256(evidence_payload).hexdigest(),
    }
    image_record = {
        "reference": image.reference,
        "index_digest": image.index_digest,
        "platform_manifest_digest": image.platform_manifest_digest,
        "platform": image.platform,
    }
    reviewer = "m3-native-conformance-only"
    manifest = {
        "schemaVersion": 1,
        "productEnabled": True,
        "approvalId": str(uuid4()),
        "approvedBy": reviewer,
        "approvedAt": approval_at,
        "gates": [
            {
                "id": gate.value,
                "approved": True,
                "approvedBy": reviewer,
                "approvedAt": approval_at,
                "evidence": [evidence_record],
            }
            for gate in M3_GATE_IDS
        ],
        "runtime": {
            "grants": [
                {
                    "backend": grant_runtime.value,
                    "image": image_record,
                    "entrypoint": entrypoint.entrypoint_id,
                }
                for grant_runtime in (RuntimeKind.DOCKER, RuntimeKind.PODMAN)
                for entrypoint in ENTRYPOINTS
            ],
        },
    }
    path = root / "validation-manifest.json"
    path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
        newline="\n",
    )
    return M3ProductGate.load(path, repository_root=root).require_activation()


class NativeAdapterObserver:
    def __init__(self, plan: Mapping[str, Any], options: ObserverOptions) -> None:
        self.plan = plan
        self.options = options
        self.runner = ObservedPrefixedOciRunner(options.transport)
        lock_root = options.output / "state" / "locks"
        lock_root.mkdir(mode=0o700)
        self.authority = ProductRuntimeFenceAuthority(
            options.output / "state" / "fence.sqlite3",
            lock_root,
        )
        self.backend: OciRuntimeBackend | None = None
        self.capabilities = None
        self.known_fences: dict[str, set[tuple[str, int]]] = {}
        self.journal_path = options.output / "state" / "cleanup-journal.json"
        self.cleanup_events: list[dict[str, object]] = []
        archive_limits = ArchiveLimits(
            max_archive_bytes=1_048_576,
            max_file_count=8,
            max_total_bytes=1_048_576,
        )
        archive_payload = build_canonical_input_archive(
            (InputPayload(INPUT_FILE.name, INPUT_CONTENT),),
            (INPUT_FILE,),
            archive_limits,
        )
        self.input_archive = validate_canonical_input_archive(
            archive_payload,
            (INPUT_FILE,),
            archive_limits,
        )
        self.expected_output = build_canonical_output_archive(
            (ArtifactPayload(OUTPUT_NAME, OUTPUT_CONTENT),),
            (OUTPUT_NAME,),
            output_archive_limits(1_048_576, 8),
        )
        self._write_journal()

    def _write_journal(self) -> None:
        payload = {
            "schemaVersion": 1,
            "classification": "external-cleanup-journal-not-approval-evidence",
            "runtime": self.options.runtime.value,
            "transport": self.options.transport.as_record(),
            "jobs": [
                {
                    "jobId": job_id,
                    "fences": [
                        {"ownerId": owner_id, "fencingToken": token}
                        for owner_id, token in sorted(fences, key=lambda item: item[1])
                    ],
                }
                for job_id, fences in sorted(self.known_fences.items())
            ],
            "globalPruneAllowed": False,
        }
        temporary = self.journal_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, self.journal_path)

    def _register_fence(self, fence: RuntimeFencingContext) -> None:
        self.known_fences.setdefault(fence.identity.job_id, set()).add(
            (fence.owner_id, fence.fencing_token),
        )
        self._write_journal()

    def _resource_limits(self, timeout_ms: int) -> ResourceLimits:
        limits = self.plan["resourceLimits"]
        return ResourceLimits(
            cpu_millis=limits["cpuMillis"],
            memory_bytes=limits["memoryBytes"],
            pids=limits["pids"],
            timeout_ms=timeout_ms,
            output_bytes=limits["outputBytes"],
            file_count=limits["fileCount"],
            artifact_bytes=limits["artifactBytes"],
            tmpfs_bytes=limits["tmpfsBytes"],
        )

    def _policy(self) -> SandboxPolicy:
        maximum = self._resource_limits(self.plan["resourceLimits"]["maximumTimeoutMs"])
        profiles = tuple(
            EngineProfile(
                entrypoint.entrypoint_id,
                JobKind.SUPREM,
                self.options.image,
                "m3-fixture-env",
                entrypoint.entrypoint_id,
                (INPUT_FILE.name,),
                (OUTPUT_NAME,),
            )
            for entrypoint in ENTRYPOINTS
            if entrypoint.entrypoint_id not in {
                "fixture-archive-import",
                "fixture-archive-export",
            }
        )
        return SandboxPolicy(
            "m3-conformance-v1",
            profiles,
            maximum,
            1_048_576,
        )

    def _spec(self, job_id: str, entrypoint_id: str, timeout_ms: int):
        if self.capabilities is None:
            raise ContractError("runtime capabilities unavailable")
        spec = SandboxSpec(
            job_id,
            entrypoint_id,
            JobKind.SUPREM,
            self.options.image,
            (INPUT_FILE,),
            self._resource_limits(timeout_ms),
            "m3-fixture-env",
            (OUTPUT_NAME,),
        )
        return self._policy().validate(spec, self.capabilities)

    async def _activate(self, resources: ScenarioResources, token: int = 1):
        if self.backend is None:
            raise ContractError("runtime backend unavailable")
        identity = JobIdentity(resources.job_id or str(uuid4()))
        resources.job_id = identity.job_id
        fence = RuntimeFencingContext(identity, str(uuid4()), token)
        await self.authority.activate(
            fence,
            phase=RuntimePhase.QUERY,
            backend=self.backend.name,
        )
        self._register_fence(fence)
        resources.fences.append(fence)
        resources.bound = self.backend.bind_job(fence)
        return resources.bound, fence

    async def _prepare_workload(
        self,
        resources: ScenarioResources,
        entrypoint_id: str,
        *,
        timeout_ms: int,
        start: bool = True,
    ):
        bound, _ = await self._activate(resources)
        spec = self._spec(resources.job_id, entrypoint_id, timeout_ms)
        resources.volume = await bound.create_volume()
        await bound.stage_inputs(resources.volume, spec, self.input_archive)
        resources.container = await bound.create_container(spec, resources.volume)
        if start:
            await bound.start(resources.container)
            resources.started = True
        return bound, spec

    async def _success(self, resources: ScenarioResources) -> dict[str, object]:
        timeout_ms = self.plan["resourceLimits"]["normalTimeoutMs"]
        bound, _ = await self._prepare_workload(resources, "fixture-success", timeout_ms=timeout_ms)
        result = await bound.wait(resources.container)
        resources.terminal = True
        archive = await bound.collect_artifacts(resources.container)
        passed = (
            result.classification is TerminalClassification.SUCCEEDED
            and result.exit_code == 0
            and archive.payload == self.expected_output.payload
            and len(result.artifacts) == 1
            and result.artifacts[0].name == OUTPUT_NAME
            and result.artifacts[0].sha256 == sha256(OUTPUT_CONTENT).hexdigest()
        )
        return {
            "pass": passed,
            "observed": result.classification.value,
            "artifactCanonical": archive.payload == self.expected_output.payload,
        }

    async def _nonzero(self, resources: ScenarioResources) -> dict[str, object]:
        timeout_ms = self.plan["resourceLimits"]["normalTimeoutMs"]
        bound, _ = await self._prepare_workload(resources, "fixture-nonzero", timeout_ms=timeout_ms)
        result = await bound.wait(resources.container)
        resources.terminal = True
        return {
            "pass": result.classification is TerminalClassification.NONZERO_EXIT and result.exit_code == 23,
            "observed": result.classification.value,
            "exitCode": result.exit_code,
        }

    async def _cancellation(self, resources: ScenarioResources) -> dict[str, object]:
        timeout_ms = self.plan["resourceLimits"]["normalTimeoutMs"]
        bound, _ = await self._prepare_workload(resources, "fixture-sleep", timeout_ms=timeout_ms)
        await asyncio.sleep(self.plan["cancellationAfterMs"] / 1_000)
        result = await bound.kill(resources.container, TerminationReason.CANCELLATION)
        resources.terminal = True
        return {
            "pass": result.classification is TerminalClassification.CANCELLED,
            "observed": result.classification.value,
        }

    async def _timeout(self, resources: ScenarioResources) -> dict[str, object]:
        timeout_ms = self.plan["resourceLimits"]["faultTimeoutMs"]
        bound, _ = await self._prepare_workload(resources, "fixture-sleep", timeout_ms=timeout_ms)
        result = await bound.wait(resources.container)
        resources.terminal = result.classification in set(TerminalClassification)
        return {
            "pass": result.classification is TerminalClassification.TIMED_OUT,
            "observed": result.classification.value,
        }

    async def _output_bomb(self, resources: ScenarioResources) -> dict[str, object]:
        timeout_ms = self.plan["resourceLimits"]["normalTimeoutMs"]
        bound, _ = await self._prepare_workload(resources, "fixture-output-bomb", timeout_ms=timeout_ms)
        observation_start = self.runner.command_count
        result = await bound.wait(resources.container)
        resources.terminal = True
        output_limit_terminations = sum(
            item.operation == "container logs"
            and item.status == "output-limit-exceeded"
            for item in self.runner.observations[observation_start:]
        )
        streaming_termination_proven = (
            result.classification is TerminalClassification.OUTPUT_LIMIT_EXCEEDED
            and result.output_truncated
            and result.captured_output_bytes <= result.output_limit_bytes
            and result.observed_output_bytes > result.output_limit_bytes
            and output_limit_terminations > 0
        )
        return {
            "pass": streaming_termination_proven,
            "observed": result.classification.value,
            "capturedOutputBytes": result.captured_output_bytes,
            "observedOutputBytes": result.observed_output_bytes,
            "outputLimitTerminationCommands": output_limit_terminations,
            "streamingOutputTerminationProven": streaming_termination_proven,
        }

    async def _stale_fence(self, resources: ScenarioResources) -> dict[str, object]:
        bound, old = await self._activate(resources, 1)
        resources.volume = await bound.create_volume()
        if self.backend is None:
            raise ContractError("runtime backend unavailable")
        current = RuntimeFencingContext(old.identity, str(uuid4()), 2)
        await self.authority.activate(
            current,
            phase=RuntimePhase.QUERY,
            backend=self.backend.name,
        )
        self._register_fence(current)
        resources.fences.append(current)
        before = self.runner.command_count
        stale_error: RuntimeBackendError | None = None
        try:
            await bound.remove_volume(resources.volume)
        except RuntimeBackendError as error:
            stale_error = error
        after = self.runner.command_count
        resources.bound = self.backend.bind_job(current)
        await resources.bound.remove_volume(resources.volume)
        await resources.bound.remove_volume(resources.volume)
        resources.volume = None
        return {
            "pass": (
                stale_error is not None
                and stale_error.code is ErrorCode.OPERATION_FENCED
                and before == after
            ),
            "observed": "operation-fenced-no-native-call" if stale_error is not None else "stale-call-accepted",
            "nativeCallsBefore": before,
            "nativeCallsAfter": after,
        }

    async def _concurrent_cleanup(self, resources: ScenarioResources) -> dict[str, object]:
        timeout_ms = self.plan["resourceLimits"]["normalTimeoutMs"]
        bound, _ = await self._prepare_workload(
            resources,
            "fixture-success",
            timeout_ms=timeout_ms,
            start=False,
        )
        container_results = await asyncio.gather(
            bound.remove_container(resources.container),
            bound.remove_container(resources.container),
            return_exceptions=True,
        )
        volume_results = await asyncio.gather(
            bound.remove_volume(resources.volume),
            bound.remove_volume(resources.volume),
            return_exceptions=True,
        )
        errors = [
            item
            for item in (*container_results, *volume_results)
            if isinstance(item, BaseException)
        ]
        resources.container = None
        resources.volume = None
        return {
            "pass": not errors,
            "observed": "idempotent" if not errors else "concurrent-cleanup-error",
            "errorCount": len(errors),
            "errors": [stable_error(error) for error in errors],
        }

    async def _direct(self, arguments: Sequence[str], *, output_limit: int = 1_048_576) -> OciCommandResult:
        result = await self.runner.run(arguments, timeout_ms=30_000, output_limit=output_limit)
        if result.returncode != 0:
            raise ContractError("exact cleanup command failed")
        return result

    async def _managed_names(self, object_type: str, job_id: str) -> tuple[str, ...]:
        filters = (
            "--filter",
            f"label={MANAGED_LABEL}={MANAGED_LABEL_VALUE}",
            "--filter",
            f"label=tcad.job_id={job_id}",
        )
        if object_type == "container":
            arguments = (
                "container",
                "ls",
                "--all",
                *filters,
                "--format",
                "{{.Names}}",
            )
        elif object_type == "volume":
            arguments = (
                "volume",
                "ls",
                *filters,
                "--format",
                "{{.Name}}",
            )
        else:
            raise ContractError("cleanup object type invalid")
        result = await self._direct(arguments)
        try:
            names = tuple(line.decode("utf-8") for line in result.stdout.splitlines() if line)
        except UnicodeError as error:
            raise ContractError("cleanup object name invalid") from error
        if any(re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,127}", name) is None for name in names):
            raise ContractError("cleanup object name outside allowlist")
        return names

    async def _exact_labels(self, object_type: str, name: str) -> dict[str, str]:
        if object_type == "container":
            arguments = (
                "container",
                "inspect",
                "--format",
                "{{json .Config.Labels}}",
                name,
            )
        else:
            arguments = (
                "volume",
                "inspect",
                "--format",
                "{{json .Labels}}",
                name,
            )
        result = await self._direct(arguments)
        try:
            value = json.loads(result.stdout.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ContractError("cleanup labels invalid") from error
        if not isinstance(value, dict) or any(
            not isinstance(key, str) or not isinstance(item, str)
            for key, item in value.items()
        ):
            raise ContractError("cleanup labels invalid")
        return value

    def _authorize_cleanup_labels(self, object_type: str, job_id: str, labels: Mapping[str, str]) -> None:
        allowed_types = {"container", "helper"} if object_type == "container" else {"volume"}
        if (
            labels.get(MANAGED_LABEL) != MANAGED_LABEL_VALUE
            or labels.get(OBJECT_TYPE_LABEL) not in allowed_types
            or labels.get("tcad.job_id") != job_id
        ):
            raise ContractError("cleanup labels do not authorize removal")
        try:
            pair = (labels["tcad.owner_id"], int(labels["tcad.fencing_token"]))
        except (KeyError, TypeError, ValueError) as error:
            raise ContractError("cleanup fence labels invalid") from error
        if str(pair[1]) != labels["tcad.fencing_token"] or pair not in self.known_fences.get(job_id, set()):
            raise ContractError("cleanup fence is not in the run journal")

    async def _emergency_cleanup_job(self, job_id: str) -> dict[str, object]:
        removed_containers = 0
        removed_volumes = 0
        errors: list[dict[str, object]] = []
        try:
            containers = await self._managed_names("container", job_id)
            for name in containers:
                labels = await self._exact_labels("container", name)
                self._authorize_cleanup_labels("container", job_id, labels)
                await self._direct(("container", "rm", "--force", name))
                removed_containers += 1
            volumes = await self._managed_names("volume", job_id)
            for name in volumes:
                labels = await self._exact_labels("volume", name)
                self._authorize_cleanup_labels("volume", job_id, labels)
                await self._direct(("volume", "rm", name))
                removed_volumes += 1
            final_containers = await self._managed_names("container", job_id)
            final_volumes = await self._managed_names("volume", job_id)
        except BaseException as error:
            errors.append(stable_error(error))
            try:
                final_containers = await self._managed_names("container", job_id)
            except BaseException as query_error:
                errors.append(stable_error(query_error))
                final_containers = ("query-failed",)
            try:
                final_volumes = await self._managed_names("volume", job_id)
            except BaseException as query_error:
                errors.append(stable_error(query_error))
                final_volumes = ("query-failed",)
        record = {
            "jobIdentitySha256": sha256(job_id.encode("ascii")).hexdigest(),
            "containersRemoved": removed_containers,
            "volumesRemoved": removed_volumes,
            "finalContainers": len(final_containers),
            "finalVolumes": len(final_volumes),
            "errors": errors,
            "pass": not errors and not final_containers and not final_volumes,
        }
        self.cleanup_events.append(record)
        return record

    async def _shielded_emergency_cleanup(self, job_id: str) -> dict[str, object]:
        task = asyncio.create_task(self._emergency_cleanup_job(job_id))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def _cleanup_resources(self, resources: ScenarioResources) -> dict[str, object]:
        adapter_errors: list[dict[str, object]] = []
        if resources.bound is not None and resources.container is not None:
            if not resources.started or resources.terminal:
                for _ in range(2):
                    try:
                        await resources.bound.remove_container(resources.container)
                    except BaseException as error:
                        adapter_errors.append(stable_error(error))
            # A running non-terminal workload is removed through the exact,
            # label-authorized emergency path so recovery does not initiate a
            # second log read after an interrupted wait.
        if resources.bound is not None and resources.volume is not None and (
            resources.container is None or not resources.started or resources.terminal
        ):
            for _ in range(2):
                try:
                    await resources.bound.remove_volume(resources.volume)
                except BaseException as error:
                    adapter_errors.append(stable_error(error))
        if resources.job_id is None:
            return {
                "pass": not adapter_errors,
                "adapterErrors": adapter_errors,
                "finalContainers": 0,
                "finalVolumes": 0,
            }
        emergency = await self._shielded_emergency_cleanup(resources.job_id)
        return {
            "pass": not adapter_errors and emergency["pass"] is True,
            "adapterErrors": adapter_errors,
            "finalContainers": emergency["finalContainers"],
            "finalVolumes": emergency["finalVolumes"],
            "exactEmergencyCleanup": emergency,
        }

    async def _execute_scenario(
        self,
        scenario_id: str,
        expected: str,
        operation,
    ) -> ScenarioResult:
        resources = ScenarioResources()
        error_record: dict[str, object] | None = None
        details: dict[str, object] = {}
        observed = "not-observed"
        passed = False
        try:
            outcome = await operation(resources)
            passed = bool(outcome.pop("pass"))
            observed = str(outcome.pop("observed"))
            details = outcome
        except BaseException as error:
            error_record = stable_error(error)
            observed = str(error_record["code"])
        cleanup = await self._cleanup_resources(resources)
        passed = passed and cleanup["pass"] is True
        return ScenarioResult(
            scenario_id,
            passed,
            expected,
            observed,
            error_record,
            cleanup,
            details,
        )

    async def _final_cleanup(self) -> dict[str, object]:
        records = []
        for job_id in tuple(self.known_fences):
            records.append(await self._shielded_emergency_cleanup(job_id))
        return {
            "pass": all(record["pass"] for record in records),
            "jobs": len(records),
            "finalContainers": sum(int(record["finalContainers"]) for record in records),
            "finalVolumes": sum(int(record["finalVolumes"]) for record in records),
            "globalPruneUsed": False,
        }

    def _base_record(self, status: str) -> dict[str, object]:
        record = {
            "schemaVersion": 1,
            "milestone": "M3",
            "observationId": "M3-NATIVE-ADAPTER-001",
            "evidenceType": "native-adapter-observation",
            "classification": "non-promoting-native-adapter-conformance",
            "recordedAt": self.options.recorded_at,
            "status": status,
        }
        record.update(NON_PROMOTION_FIELDS)
        return record

    async def run(self, activation) -> dict[str, object]:
        configuration = OciAdapterConfiguration(
            self.options.runtime,
            self.options.image,
            ENTRYPOINTS,
            "fixture-archive-import",
            "fixture-archive-export",
        )
        self.backend = OciRuntimeBackend(
            configuration,
            activation,
            self.authority,
            runner=self.runner,
        )
        probe = await self.backend.probe()
        if probe.health is not RuntimeHealth.AVAILABLE or probe.capabilities is None:
            raise ContractError("native runtime probe unavailable")
        if self.options.runtime is RuntimeKind.PODMAN and self.plan["podmanRootlessRequired"]:
            if probe.capabilities.rootless is not True:
                raise ContractError("Podman conformance requires rootless mode")
        self.capabilities = probe.capabilities
        image_observation_start = self.runner.command_count
        await self.backend.ensure_image(self.options.image)
        image_inspection = local_image_inspection_proof(
            self.runner.observations[image_observation_start:],
        )
        methods = (
            ("success-lifecycle", "succeeded", self._success),
            ("declared-nonzero", "nonzero-exit", self._nonzero),
            ("external-cancellation", "cancelled", self._cancellation),
            ("timeout-classification", "timed-out", self._timeout),
            ("output-bomb-classification", "output-limit-exceeded", self._output_bomb),
            ("stale-fence-no-native-call", "operation-fenced-no-native-call", self._stale_fence),
            ("concurrent-cleanup-idempotence", "idempotent", self._concurrent_cleanup),
        )
        scenario_results: list[ScenarioResult] = []
        try:
            for scenario_id, expected, operation in methods:
                scenario_results.append(
                    await self._execute_scenario(scenario_id, expected, operation),
                )
        finally:
            final_cleanup = await self._final_cleanup()
        output_bomb = next(
            item for item in scenario_results
            if item.scenario_id == "output-bomb-classification"
        )
        proofs = {
            "streamingOutputTerminationProven": (
                output_bomb.passed
                and output_bomb.details.get("streamingOutputTerminationProven") is True
            ),
            **image_inspection,
        }
        required_proofs = self.plan["requiredProofs"]
        proofs_passed = (
            proofs["streamingOutputTerminationProven"]
            is required_proofs["streamingOutputTerminationProven"]
            and proofs["offlineLocalImageInspectionProven"]
            is required_proofs["offlineLocalImageInspectionProven"]
            and proofs["manifestInspectCommands"]
            == required_proofs["manifestInspectCommands"]
        )
        observed_pass = (
            all(item.passed for item in scenario_results)
            and final_cleanup["pass"] is True
            and proofs_passed
        )
        record = self._base_record("passed" if observed_pass else "failed")
        record.update(
            {
                "observedConformancePassed": observed_pass,
                "host": {
                    "system": platform.system().casefold(),
                    "machine": platform.machine().casefold(),
                    "python": platform.python_version(),
                },
                "runtime": {
                    "backend": self.options.runtime.value,
                    "transport": self.options.transport.as_record(),
                    "version": probe.capabilities.version,
                    "operatingSystem": probe.capabilities.operating_system,
                    "architecture": probe.capabilities.architecture,
                    "rootless": probe.capabilities.rootless,
                    "probeCapabilityClaimsPromoted": False,
                },
                "fixture": {
                    "engineFree": True,
                    "sourceSha256": fixture_source_sha256(),
                    "reference": self.options.image.reference,
                    "indexDigest": self.options.image.index_digest,
                    "platformManifestDigest": self.options.image.platform_manifest_digest,
                    "platform": self.options.image.platform,
                    "preloadedByOperator": True,
                    "pulledByObserver": False,
                    "builtByObserver": False,
                    "removedByObserver": False,
                    "releaseImageApproved": False,
                },
                "activation": {
                    "scope": "temporary-validation-only",
                    "manifestSha256": activation.manifest_sha256,
                    "productApprovalGranted": False,
                },
                "scenarios": [item.as_record() for item in scenario_results],
                "cleanup": final_cleanup,
                "commandObservations": [item.as_record() for item in self.runner.observations],
                "requiredProofsPassed": proofs_passed,
                "proofs": proofs,
                "probeCapabilityClaimsPromoted": False,
                "evidence": {
                    "location": "external-output-directory",
                    "rawInsideRepository": False,
                    "automaticPromotion": False,
                    "planSha256": sha256(REVIEWED_PLAN.read_bytes()).hexdigest(),
                    "cleanupJournal": "state/cleanup-journal.json",
                },
            },
        )
        return record


def write_record(path: Path, record: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(record, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


async def observe(plan: Mapping[str, Any], options: ObserverOptions) -> tuple[dict[str, object], int]:
    observer: NativeAdapterObserver | None = None
    try:
        observer = NativeAdapterObserver(plan, options)
        with TemporaryDirectory(prefix="opentcad-m3-native-") as directory:
            activation = _temporary_activation(
                options.image,
                options.runtime,
                options.recorded_at,
                Path(directory),
            )
            record = await observer.run(activation)
        write_record(options.output / "manifest.json", record)
        return record, 0 if record["status"] == "passed" else 1
    except BaseException as error:
        cleanup = {
            "pass": True,
            "jobs": 0,
            "finalContainers": 0,
            "finalVolumes": 0,
            "globalPruneUsed": False,
        }
        if observer is not None:
            try:
                cleanup = await observer._final_cleanup()
            except BaseException as cleanup_error:
                cleanup = {
                    "pass": False,
                    "jobs": len(observer.known_fences),
                    "finalContainers": None,
                    "finalVolumes": None,
                    "globalPruneUsed": False,
                    "error": stable_error(cleanup_error),
                }
        if observer is not None:
            base = observer._base_record("blocked")
        else:
            base = {
                "schemaVersion": 1,
                "milestone": "M3",
                "observationId": "M3-NATIVE-ADAPTER-001",
                "evidenceType": "native-adapter-observation",
                "classification": "non-promoting-native-adapter-conformance",
                "recordedAt": options.recorded_at,
                "status": "blocked",
                **NON_PROMOTION_FIELDS,
            }
        base.update(
            {
                "observedConformancePassed": False,
                "error": stable_error(error),
                "cleanup": cleanup,
                "commandObservations": (
                    [item.as_record() for item in observer.runner.observations]
                    if observer is not None
                    else []
                ),
                "evidence": {
                    "location": "external-output-directory",
                    "rawInsideRepository": False,
                    "automaticPromotion": False,
                },
            },
        )
        write_record(options.output / "failure.json", base)
        return base, 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Observe the real M3 OCI adapter without granting product approval.",
    )
    parser.add_argument("--plan", default=str(REVIEWED_PLAN))
    parser.add_argument("--runtime", required=True, choices=("docker", "podman"))
    parser.add_argument("--image-reference", required=True)
    parser.add_argument("--index-digest", required=True)
    parser.add_argument("--platform-manifest-digest", required=True)
    parser.add_argument("--platform", required=True, choices=("linux/amd64", "linux/arm64"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--wsl-distribution")
    parser.add_argument("--recorded-at")
    return parser


def options_from_arguments(arguments: argparse.Namespace, plan: Mapping[str, Any]) -> ObserverOptions:
    runtime = RuntimeKind(arguments.runtime)
    transport = RuntimeTransport.select(
        runtime,
        wsl_distribution=arguments.wsl_distribution,
    )
    image = image_from_arguments(
        arguments.image_reference,
        arguments.index_digest,
        arguments.platform_manifest_digest,
        arguments.platform,
        plan,
    )
    output = prepare_external_output(Path(arguments.output))
    return ObserverOptions(
        runtime,
        transport,
        image,
        output,
        parse_recorded_at(arguments.recorded_at),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        plan = load_reviewed_plan(Path(arguments.plan))
        options = options_from_arguments(arguments, plan)
    except (ContractError, OSError, RuntimeBackendError) as error:
        parser.error(str(error))
    record, exit_code = asyncio.run(observe(plan, options))
    print(
        json.dumps(
            {
                "status": record["status"],
                "qualified": False,
                "approvalGranted": False,
                "output": str(options.output),
            },
            sort_keys=True,
        ),
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
