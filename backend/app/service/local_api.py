"""Authenticated loopback-only HTTP API connected to the local worker."""

from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
import ipaddress
import json
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from backend.app.broker.backup_control import (
    BackupControlError,
    MaintenanceLease,
    MaintenancePhase,
    MaintenanceRequest,
)
from backend.app.broker.backup_service import AuthenticatedBackupError
from backend.app.broker.cancellation import CancellationRequest
from backend.app.broker.models import BrokerRequest, BrokerOutcome
from backend.app.broker.state_composition import (
    BrokerStartupReport,
    BrokerStartupRequest,
    StateCompositionError,
    StateOperationContext,
)
from backend.app.runtime.errors import ErrorCode, RuntimeBackendError
from backend.app.runtime.models import (
    ImageIdentity,
    InputFile,
    JobIdentity,
    JobKind,
    ResourceLimits,
    SandboxSpec,
)

from .worker import (
    CancelWork,
    ExecuteWork,
    LocalBrokerWorker,
    ScheduledBackupWork,
    WorkerEnvelope,
    WorkerError,
    WorkerOperation,
)


LOCALHOST_BROKER_API_PRODUCT_ENABLED = True
_JOB_CANCEL = re.compile(
    r"^/v1/jobs/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})/cancel$",
)
_SCHEDULE_RUN = re.compile(
    r"^/v1/backups/schedules/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})/run$",
)


class LocalApiError(Exception):
    def __init__(self, status: int, code: str) -> None:
        self.status = status
        self.code = code
        super().__init__(code)

    def as_dict(self) -> dict[str, dict[str, str]]:
        return {"error": {"code": self.code}}


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _json_object(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs)
    except (UnicodeError, json.JSONDecodeError, ValueError):
        raise LocalApiError(400, "invalid-json") from None
    if not isinstance(value, dict):
        raise LocalApiError(400, "json-object-required")
    return value


def _exact(value: object, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise LocalApiError(400, "object-shape-invalid")
    return value


def _uuid(value: object) -> str:
    if not isinstance(value, str):
        raise LocalApiError(400, "uuid-invalid")
    try:
        parsed = UUID(value)
    except ValueError:
        raise LocalApiError(400, "uuid-invalid") from None
    if str(parsed) != value:
        raise LocalApiError(400, "uuid-invalid")
    return value


def _positive_int(value: object, maximum: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
        or value > maximum
    ):
        raise LocalApiError(400, "integer-out-of-range")
    return value


def _sandbox_spec(value: object) -> SandboxSpec:
    record = _exact(
        value,
        {
            "jobId",
            "profileId",
            "kind",
            "image",
            "inputManifest",
            "limits",
            "environmentProfile",
            "expectedOutputs",
        },
    )
    image = _exact(
        record["image"],
        {
            "reference",
            "indexDigest",
            "platformManifestDigest",
            "platform",
        },
    )
    manifest_value = record["inputManifest"]
    output_value = record["expectedOutputs"]
    if not isinstance(manifest_value, list) or not isinstance(output_value, list):
        raise LocalApiError(400, "file-list-invalid")
    manifest: list[InputFile] = []
    for item in manifest_value:
        input_record = _exact(item, {"name", "sha256", "bytes"})
        manifest.append(
            InputFile(
                input_record["name"],
                input_record["sha256"],
                input_record["bytes"],
            ),
        )
    limits = _exact(
        record["limits"],
        {
            "cpuMillis",
            "memoryBytes",
            "pids",
            "timeoutMs",
            "outputBytes",
            "fileCount",
            "artifactBytes",
            "tmpfsBytes",
        },
    )
    if any(not isinstance(item, str) for item in output_value):
        raise LocalApiError(400, "output-list-invalid")
    try:
        return SandboxSpec(
            _uuid(record["jobId"]),
            record["profileId"],
            JobKind(record["kind"]),
            ImageIdentity(
                image["reference"],
                image["indexDigest"],
                image["platformManifestDigest"],
                image["platform"],
            ),
            tuple(manifest),
            ResourceLimits(
                limits["cpuMillis"],
                limits["memoryBytes"],
                limits["pids"],
                limits["timeoutMs"],
                limits["outputBytes"],
                limits["fileCount"],
                limits["artifactBytes"],
                limits["tmpfsBytes"],
            ),
            record["environmentProfile"],
            tuple(output_value),
        )
    except (RuntimeBackendError, TypeError, ValueError):
        raise LocalApiError(400, "sandbox-spec-invalid") from None


def _maintenance_lease(value: object) -> MaintenanceLease:
    record = _exact(
        value,
        {
            "maintenanceId",
            "ownerId",
            "quiescenceId",
            "generation",
            "phase",
            "leaseExpiresAtMs",
        },
    )
    try:
        return MaintenanceLease(
            _uuid(record["maintenanceId"]),
            _uuid(record["ownerId"]),
            _uuid(record["quiescenceId"]),
            _positive_int(record["generation"], (1 << 63) - 1),
            MaintenancePhase(record["phase"]),
            _positive_int(record["leaseExpiresAtMs"], (1 << 63) - 1),
        )
    except (TypeError, ValueError):
        raise LocalApiError(400, "maintenance-lease-invalid") from None


def _lease_dict(lease: MaintenanceLease) -> dict[str, object]:
    return {
        "maintenanceId": lease.maintenance_id,
        "ownerId": lease.owner_id,
        "quiescenceId": lease.quiescence_id,
        "generation": lease.generation,
        "phase": lease.phase.value,
        "leaseExpiresAtMs": lease.lease_expires_at_ms,
    }


def _result_dict(value: object) -> dict[str, Any]:
    if isinstance(value, BrokerOutcome):
        return value.as_dict()
    if isinstance(value, BrokerStartupReport):
        return {
            "startup_id": value.startup_id,
            "recovered_items": value.recovered_items,
            "pages": [page.as_dict() for page in value.pages],
        }
    if isinstance(value, MaintenanceLease):
        return _lease_dict(value)
    if value is None:
        return {"ok": True}
    as_dict = getattr(value, "as_dict", None)
    if callable(as_dict):
        result = as_dict()
        if isinstance(result, dict):
            return result
    schedule = getattr(value, "schedule", None)
    export = getattr(value, "export", None)
    if schedule is not None and export is not None:
        return {
            "snapshot_id": export.snapshot.snapshot_id,
            "snapshot_sequence": export.reservation.snapshot_sequence,
            "schedule_id": schedule.definition.schedule_id,
            "next_due_at_ms": schedule.definition.next_due_at_ms,
        }
    raise LocalApiError(500, "response-serialization-failed")


class LocalBrokerApi:
    """Strict JSON route codec; no runtime command or path crosses this boundary."""

    def __init__(self, worker: LocalBrokerWorker) -> None:
        if not isinstance(worker, LocalBrokerWorker):
            raise TypeError("Local API requires LocalBrokerWorker.")
        self._worker = worker

    @property
    def ready(self) -> bool:
        return self._worker.started

    async def handle(
        self,
        method: str,
        path: str,
        raw_body: bytes,
    ) -> tuple[int, dict[str, Any]]:
        try:
            if method == "GET" and path == "/v1/health":
                return 200, {"status": "ready" if self.ready else "starting"}
            if method != "POST":
                raise LocalApiError(405, "method-not-allowed")
            body = _json_object(raw_body)
            request_hash = sha256(raw_body).hexdigest()

            if path == "/v1/startup":
                record = _exact(body, {"requestId", "startupId", "pageLimit"})
                envelope = WorkerEnvelope(
                    _uuid(record["requestId"]),
                    request_hash,
                    WorkerOperation.STARTUP_RECOVERY,
                    BrokerStartupRequest(
                        _uuid(record["startupId"]),
                        _positive_int(record["pageLimit"], 1_000),
                    ),
                )
            elif path == "/v1/jobs":
                record = _exact(
                    body,
                    {
                        "requestId",
                        "operationId",
                        "ownerId",
                        "spec",
                        "inputArchiveBase64",
                    },
                )
                spec = _sandbox_spec(record["spec"])
                encoded = record["inputArchiveBase64"]
                if not isinstance(encoded, str):
                    raise LocalApiError(400, "input-archive-invalid")
                try:
                    archive = base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error):
                    raise LocalApiError(400, "input-archive-invalid") from None
                envelope = WorkerEnvelope(
                    _uuid(record["requestId"]),
                    request_hash,
                    WorkerOperation.EXECUTE,
                    ExecuteWork(
                        BrokerRequest(spec, archive),
                        StateOperationContext(_uuid(record["operationId"])),
                        _uuid(record["ownerId"]),
                        86_400_000,
                    ),
                )
            elif match := _JOB_CANCEL.fullmatch(path):
                record = _exact(body, {"requestId", "operationId"})
                job_id = _uuid(match.group(1))
                envelope = WorkerEnvelope(
                    _uuid(record["requestId"]),
                    request_hash,
                    WorkerOperation.CANCEL,
                    CancelWork(
                        CancellationRequest(JobIdentity(job_id)),
                        StateOperationContext(_uuid(record["operationId"])),
                    ),
                )
            elif path == "/v1/maintenance/begin":
                record = _exact(
                    body,
                    {
                        "requestId",
                        "maintenanceId",
                        "ownerId",
                        "quiescenceId",
                        "leaseDurationMs",
                    },
                )
                envelope = WorkerEnvelope(
                    _uuid(record["requestId"]),
                    request_hash,
                    WorkerOperation.MAINTENANCE_BEGIN,
                    MaintenanceRequest(
                        _uuid(record["maintenanceId"]),
                        _uuid(record["ownerId"]),
                        _uuid(record["quiescenceId"]),
                        _positive_int(record["leaseDurationMs"], 86_400_000),
                    ),
                )
            elif path in {"/v1/maintenance/offline", "/v1/maintenance/end"}:
                record = _exact(body, {"requestId", "lease"})
                operation = (
                    WorkerOperation.MAINTENANCE_OFFLINE
                    if path.endswith("/offline")
                    else WorkerOperation.MAINTENANCE_END
                )
                envelope = WorkerEnvelope(
                    _uuid(record["requestId"]),
                    request_hash,
                    operation,
                    _maintenance_lease(record["lease"]),
                )
            elif match := _SCHEDULE_RUN.fullmatch(path):
                record = _exact(
                    body,
                    {"requestId", "ownerId", "leaseDurationMs"},
                )
                envelope = WorkerEnvelope(
                    _uuid(record["requestId"]),
                    request_hash,
                    WorkerOperation.BACKUP_SCHEDULE_RUN,
                    ScheduledBackupWork(
                        _uuid(match.group(1)),
                        _uuid(record["ownerId"]),
                        _positive_int(record["leaseDurationMs"], 86_400_000),
                    ),
                )
            else:
                raise LocalApiError(404, "route-not-found")
            result = await self._worker.submit(envelope)
            return 200, _result_dict(result)
        except LocalApiError as error:
            return error.status, error.as_dict()
        except WorkerError as error:
            status = 409 if error.code.value.endswith("conflict") else 503
            return status, {"error": error.as_dict()}
        except RuntimeBackendError as error:
            status = 400 if error.code is ErrorCode.INVALID_SPEC else 409
            return status, {"error": error.as_dict()}
        except (StateCompositionError, BackupControlError, AuthenticatedBackupError) as error:
            return 409, {"error": error.as_dict()}
        except (KeyError, TypeError, ValueError):
            return 400, {"error": {"code": "request-invalid"}}


@dataclass(frozen=True, slots=True)
class LocalApiBind:
    host: str = "127.0.0.1"
    port: int = 0

    def __post_init__(self) -> None:
        try:
            address = ipaddress.ip_address(self.host)
        except ValueError as error:
            raise TypeError("Local API host must be a numeric loopback address.") from error
        if not address.is_loopback:
            raise TypeError("Local API host must be loopback-only.")
        if (
            not isinstance(self.port, int)
            or isinstance(self.port, bool)
            or self.port < 0
            or self.port > 65_535
        ):
            raise TypeError("Local API port is invalid.")


class LocalApiServer:
    """Minimal HTTP/1.1 server with loopback peer and origin enforcement."""

    _STATUS = {
        200: "OK",
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        409: "Conflict",
        413: "Content Too Large",
        415: "Unsupported Media Type",
        431: "Request Header Fields Too Large",
        500: "Internal Server Error",
        503: "Service Unavailable",
    }
    _HEADER_NAME = re.compile(r"^[A-Za-z0-9-]+$")

    def __init__(
        self,
        application: LocalBrokerApi,
        bearer_secret: bytes,
        bind: LocalApiBind = LocalApiBind(),
        *,
        maximum_header_bytes: int = 16_384,
        maximum_body_bytes: int = 16_777_216,
    ) -> None:
        if not isinstance(application, LocalBrokerApi):
            raise TypeError("Local server requires LocalBrokerApi.")
        if (
            not isinstance(bearer_secret, bytes)
            or not 32 <= len(bearer_secret) <= 128
        ):
            raise TypeError("Local server bearer secret must be 32 to 128 bytes.")
        if not isinstance(bind, LocalApiBind):
            raise TypeError("Local server requires LocalApiBind.")
        if (
            not isinstance(maximum_header_bytes, int)
            or isinstance(maximum_header_bytes, bool)
            or not 1_024 <= maximum_header_bytes <= 65_536
            or not isinstance(maximum_body_bytes, int)
            or isinstance(maximum_body_bytes, bool)
            or not 1_024 <= maximum_body_bytes <= 1_073_741_824
        ):
            raise TypeError("Local server request limits are invalid.")
        self._application = application
        self._bind = bind
        token = base64.urlsafe_b64encode(bearer_secret).rstrip(b"=")
        self._authorization = b"Bearer " + token
        self._maximum_header_bytes = maximum_header_bytes
        self._maximum_body_bytes = maximum_body_bytes
        self._server: asyncio.Server | None = None

    @property
    def port(self) -> int:
        if self._server is None or not self._server.sockets:
            raise RuntimeError("Local API server is not started.")
        return int(self._server.sockets[0].getsockname()[1])

    async def start(self) -> None:
        if self._server is not None:
            return
        self._server = await asyncio.start_server(
            self._handle_client,
            self._bind.host,
            self._bind.port,
            limit=self._maximum_header_bytes + 4,
            start_serving=True,
        )
        for socket in self._server.sockets or ():
            address = ipaddress.ip_address(socket.getsockname()[0])
            if not address.is_loopback:
                self._server.close()
                await self._server.wait_closed()
                self._server = None
                raise RuntimeError("Local API escaped loopback binding.")

    async def close(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            server.close()
            await server.wait_closed()

    @staticmethod
    def _host_value(value: str) -> tuple[str, int | None]:
        try:
            parsed = urlsplit(f"//{value}")
            if (
                parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.hostname is None
            ):
                raise ValueError
            return parsed.hostname, parsed.port
        except ValueError:
            raise LocalApiError(400, "host-invalid") from None

    def _validate_host(self, value: str) -> None:
        host, port = self._host_value(value)
        if host.casefold() != "localhost":
            try:
                if not ipaddress.ip_address(host).is_loopback:
                    raise ValueError
            except ValueError:
                raise LocalApiError(403, "host-not-loopback") from None
        if port is not None and port != self.port:
            raise LocalApiError(403, "host-port-mismatch")

    def _validate_origin(self, value: str | None) -> None:
        if value is None:
            return
        try:
            parsed = urlsplit(value)
            if (
                parsed.scheme != "http"
                or parsed.username is not None
                or parsed.password is not None
                or parsed.hostname is None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError
            host = parsed.hostname
            if host.casefold() != "localhost" and not ipaddress.ip_address(host).is_loopback:
                raise ValueError
            if parsed.port not in {None, self.port}:
                raise ValueError
        except ValueError:
            raise LocalApiError(403, "origin-not-allowed") from None

    async def _request(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> tuple[str, str, bytes]:
        peer = writer.get_extra_info("peername")
        if (
            not isinstance(peer, tuple)
            or not peer
            or not ipaddress.ip_address(peer[0]).is_loopback
        ):
            raise LocalApiError(403, "peer-not-loopback")
        try:
            raw_headers = await reader.readuntil(b"\r\n\r\n")
        except asyncio.LimitOverrunError:
            raise LocalApiError(431, "headers-too-large") from None
        except asyncio.IncompleteReadError:
            raise LocalApiError(400, "request-incomplete") from None
        if len(raw_headers) > self._maximum_header_bytes:
            raise LocalApiError(431, "headers-too-large")
        lines = raw_headers[:-4].split(b"\r\n")
        if not lines:
            raise LocalApiError(400, "request-line-invalid")
        try:
            request_line = lines[0].decode("ascii")
            method, target, version = request_line.split(" ")
        except (UnicodeError, ValueError):
            raise LocalApiError(400, "request-line-invalid") from None
        if method not in {"GET", "POST"} or version != "HTTP/1.1":
            raise LocalApiError(400, "request-line-invalid")
        target_value = urlsplit(target)
        if (
            not target.startswith("/")
            or target_value.scheme
            or target_value.netloc
            or target_value.query
            or target_value.fragment
        ):
            raise LocalApiError(400, "request-target-invalid")
        headers: dict[str, str] = {}
        for raw_line in lines[1:]:
            if b":" not in raw_line:
                raise LocalApiError(400, "header-invalid")
            raw_name, raw_value = raw_line.split(b":", maxsplit=1)
            try:
                name = raw_name.decode("ascii")
                value = raw_value.decode("ascii").strip()
            except UnicodeError:
                raise LocalApiError(400, "header-invalid") from None
            normalized = name.casefold()
            if (
                self._HEADER_NAME.fullmatch(name) is None
                or normalized in headers
                or "\r" in value
                or "\n" in value
            ):
                raise LocalApiError(400, "header-invalid")
            headers[normalized] = value
        if "host" not in headers:
            raise LocalApiError(400, "host-required")
        self._validate_host(headers["host"])
        self._validate_origin(headers.get("origin"))
        if "transfer-encoding" in headers:
            raise LocalApiError(400, "transfer-encoding-forbidden")
        authorization = headers.get("authorization", "").encode("ascii")
        if not compare_digest(authorization, self._authorization):
            raise LocalApiError(401, "authentication-required")
        try:
            content_length = int(headers.get("content-length", "0"))
        except ValueError:
            raise LocalApiError(400, "content-length-invalid") from None
        if content_length < 0:
            raise LocalApiError(400, "content-length-invalid")
        if content_length > self._maximum_body_bytes:
            raise LocalApiError(413, "body-too-large")
        if method == "POST":
            if headers.get("content-type") != "application/json":
                raise LocalApiError(415, "content-type-required")
            if content_length < 2:
                raise LocalApiError(400, "body-required")
        elif content_length:
            raise LocalApiError(400, "get-body-forbidden")
        try:
            body = await reader.readexactly(content_length)
        except asyncio.IncompleteReadError:
            raise LocalApiError(400, "body-incomplete") from None
        return method, target_value.path, body

    async def _write(
        self,
        writer: asyncio.StreamWriter,
        status: int,
        payload: dict[str, Any],
    ) -> None:
        body = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        reason = self._STATUS.get(status, "Error")
        headers = (
            f"HTTP/1.1 {status} {reason}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Cache-Control: no-store\r\n"
            "Content-Security-Policy: default-src 'none'\r\n"
            "X-Content-Type-Options: nosniff\r\n"
            "Referrer-Policy: no-referrer\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii")
        writer.write(headers + body)
        try:
            await writer.drain()
        except (ConnectionError, OSError):
            pass

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            method, path, body = await self._request(reader, writer)
            status, payload = await self._application.handle(method, path, body)
        except LocalApiError as error:
            status, payload = error.status, error.as_dict()
        except Exception:
            status, payload = 500, {"error": {"code": "internal-error"}}
        await self._write(writer, status, payload)
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass
