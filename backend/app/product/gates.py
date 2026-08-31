"""Evidence-bound activation gate for product runtime authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any
from uuid import UUID

from backend.app.runtime.models import ImageIdentity, RuntimeKind


M3_MANIFEST_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ENTRYPOINT_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
_APPROVAL_TIME_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$",
)
_TOKEN_MARKER = object()


class ProductGateId(StrEnum):
    RUNTIME_ADAPTERS = "runtime-adapters"
    NATIVE_FENCING = "native-fencing"
    LOCAL_TRANSPORT = "local-transport"
    LIFECYCLE_INTEGRATION = "lifecycle-integration"
    CREDENTIALS_AND_SCHEDULER = "credentials-and-scheduler"
    POWER_LOSS = "power-loss"
    PLATFORM_QUALIFICATION = "platform-qualification"
    SOLVER_RELEASE = "solver-release"


M3_GATE_IDS = tuple(ProductGateId)


class ProductGateErrorCode(StrEnum):
    MANIFEST_INVALID = "manifest-invalid"
    EVIDENCE_MISSING = "evidence-missing"
    EVIDENCE_DRIFT = "evidence-drift"
    APPROVAL_INCOMPLETE = "approval-incomplete"
    PRODUCT_DISABLED = "product-disabled"


class ProductGateError(Exception):
    """Stable gate failure without leaking local filesystem details."""

    def __init__(self, code: ProductGateErrorCode) -> None:
        if not isinstance(code, ProductGateErrorCode):
            raise TypeError("ProductGateError requires ProductGateErrorCode.")
        self.code = code
        super().__init__(code.value)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code.value}


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _exact(value: Any, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("object shape mismatch")
    return value


def _canonical_uuid(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("UUID required")
    parsed = UUID(value)
    if str(parsed) != value:
        raise ValueError("canonical UUID required")
    return value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError("bounded text required")
    return value


def _optional_approval_time(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _APPROVAL_TIME_PATTERN.fullmatch(value) is None:
        raise ValueError("canonical approval time required")
    datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    return value


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    path: str
    sha256: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.path, str)
            or not self.path
            or len(self.path) > 512
            or self.path.startswith(("/", "\\"))
            or "\\" in self.path
            or any(part in {"", ".", ".."} for part in self.path.split("/"))
        ):
            raise ValueError("Evidence path must be a canonical relative path.")
        if not isinstance(self.sha256, str) or _SHA256_PATTERN.fullmatch(self.sha256) is None:
            raise ValueError("Evidence SHA-256 is invalid.")


@dataclass(frozen=True, slots=True)
class GateAttestation:
    gate: ProductGateId
    approved: bool
    approved_by: str | None
    approved_at: str | None
    evidence: tuple[EvidenceRecord, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.gate, ProductGateId):
            raise ValueError("Unknown product gate.")
        if not isinstance(self.approved, bool):
            raise ValueError("Gate approval marker must be boolean.")
        records = tuple(self.evidence)
        if any(not isinstance(item, EvidenceRecord) for item in records):
            raise ValueError("Gate evidence record is invalid.")
        object.__setattr__(self, "evidence", records)
        if self.approved:
            if not self.approved_by or not self.approved_at or not records:
                raise ValueError("Approved gates require reviewer, time, and evidence.")
        elif self.approved_by is not None or self.approved_at is not None:
            raise ValueError("Blocked gates cannot carry approval metadata.")


@dataclass(frozen=True, slots=True)
class ProductRuntimeGrant:
    backend: RuntimeKind
    image: ImageIdentity
    entrypoint_id: str

    def __post_init__(self) -> None:
        if self.backend not in {RuntimeKind.DOCKER, RuntimeKind.PODMAN}:
            raise ValueError("Product runtime grant backend is invalid.")
        if not isinstance(self.image, ImageIdentity):
            raise ValueError("Product runtime grant image is invalid.")
        if (
            not isinstance(self.entrypoint_id, str)
            or _ENTRYPOINT_PATTERN.fullmatch(self.entrypoint_id) is None
        ):
            raise ValueError("Product runtime grant entrypoint is invalid.")


@dataclass(frozen=True, slots=True)
class ProductGateReport:
    manifest_sha256: str
    product_enabled: bool
    approval_id: str | None
    attestations: tuple[GateAttestation, ...]
    runtime_grants: tuple[ProductRuntimeGrant, ...]

    @property
    def approved_backends(self) -> tuple[RuntimeKind, ...]:
        return tuple(dict.fromkeys(item.backend for item in self.runtime_grants))

    @property
    def approved_images(self) -> tuple[ImageIdentity, ...]:
        return tuple(dict.fromkeys(item.image for item in self.runtime_grants))

    @property
    def entrypoints(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(item.entrypoint_id for item in self.runtime_grants)
        )

    @property
    def approved_gate_ids(self) -> tuple[ProductGateId, ...]:
        return tuple(item.gate for item in self.attestations if item.approved)

    @property
    def blocked_gate_ids(self) -> tuple[ProductGateId, ...]:
        return tuple(item.gate for item in self.attestations if not item.approved)

    @property
    def ready(self) -> bool:
        return (
            self.product_enabled
            and self.approval_id is not None
            and not self.blocked_gate_ids
            and set(self.approved_backends) == {RuntimeKind.DOCKER, RuntimeKind.PODMAN}
            and bool(self.approved_images)
            and bool(self.entrypoints)
        )


@dataclass(frozen=True, slots=True, init=False)
class ProductActivationToken:
    """Unforgeable-in-process marker created only by a complete evidence gate."""

    manifest_sha256: str
    approval_id: str
    approved_backends: tuple[RuntimeKind, ...]
    approved_images: tuple[ImageIdentity, ...]
    entrypoints: tuple[str, ...]
    runtime_grants: tuple[ProductRuntimeGrant, ...]

    def __init__(self, report: ProductGateReport, *, _marker: object) -> None:
        if _marker is not _TOKEN_MARKER or not report.ready or report.approval_id is None:
            raise ProductGateError(ProductGateErrorCode.APPROVAL_INCOMPLETE)
        object.__setattr__(self, "manifest_sha256", report.manifest_sha256)
        object.__setattr__(self, "approval_id", report.approval_id)
        object.__setattr__(self, "approved_backends", report.approved_backends)
        object.__setattr__(self, "approved_images", report.approved_images)
        object.__setattr__(self, "entrypoints", report.entrypoints)
        object.__setattr__(self, "runtime_grants", report.runtime_grants)

    def permits(
        self,
        backend: RuntimeKind,
        image: ImageIdentity,
        entrypoint_id: str,
    ) -> bool:
        if (
            backend not in {RuntimeKind.DOCKER, RuntimeKind.PODMAN}
            or not isinstance(image, ImageIdentity)
            or not isinstance(entrypoint_id, str)
            or _ENTRYPOINT_PATTERN.fullmatch(entrypoint_id) is None
        ):
            return False
        return ProductRuntimeGrant(backend, image, entrypoint_id) in self.runtime_grants

    def permits_image(
        self,
        backend: RuntimeKind,
        image: ImageIdentity,
    ) -> bool:
        return any(
            grant.backend is backend and grant.image == image
            for grant in self.runtime_grants
        )


class M3ProductGate:
    """Loads exact JSON, verifies evidence bytes, and mints activation authority."""

    def __init__(self, report: ProductGateReport) -> None:
        if not isinstance(report, ProductGateReport):
            raise TypeError("M3ProductGate requires ProductGateReport.")
        self._report = report

    @property
    def report(self) -> ProductGateReport:
        return self._report

    @classmethod
    def load(
        cls,
        manifest: str | Path,
        *,
        repository_root: str | Path,
    ) -> M3ProductGate:
        try:
            root = Path(repository_root).resolve(strict=True)
            path = Path(manifest).resolve(strict=True)
            if not path.is_file() or root not in path.parents:
                raise ValueError("manifest outside repository")
            raw = path.read_bytes()
            if not raw or len(raw) > 1_048_576:
                raise ValueError("manifest size invalid")
            parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs)
            top = _exact(
                parsed,
                {
                    "schemaVersion",
                    "productEnabled",
                    "approvalId",
                    "approvedBy",
                    "approvedAt",
                    "gates",
                    "runtime",
                },
            )
            if top["schemaVersion"] != M3_MANIFEST_SCHEMA_VERSION:
                raise ValueError("unsupported schema")
            if not isinstance(top["productEnabled"], bool):
                raise ValueError("product marker must be boolean")

            approval_id = (
                _canonical_uuid(top["approvalId"])
                if top["approvalId"] is not None
                else None
            )
            approved_by = _optional_text(top["approvedBy"])
            approved_at = _optional_approval_time(top["approvedAt"])
            if top["productEnabled"] and (
                approval_id is None or approved_by is None or approved_at is None
            ):
                raise ValueError("product approval metadata required")
            if not top["productEnabled"] and (
                approval_id is not None or approved_by is not None or approved_at is not None
            ):
                raise ValueError("disabled product cannot carry approval metadata")

            gate_values = top["gates"]
            if not isinstance(gate_values, list) or len(gate_values) != len(M3_GATE_IDS):
                raise ValueError("exact gate list required")
            attestations: list[GateAttestation] = []
            for item in gate_values:
                record = _exact(
                    item,
                    {"id", "approved", "approvedBy", "approvedAt", "evidence"},
                )
                gate_id = ProductGateId(record["id"])
                evidence_values = record["evidence"]
                if not isinstance(evidence_values, list):
                    raise ValueError("evidence list required")
                evidence = tuple(
                    EvidenceRecord(
                        _exact(value, {"path", "sha256"})["path"],
                        value["sha256"],
                    )
                    for value in evidence_values
                )
                attestations.append(
                    GateAttestation(
                        gate_id,
                        record["approved"],
                        _optional_text(record["approvedBy"]),
                        _optional_approval_time(record["approvedAt"]),
                        evidence,
                    ),
                )
            if {item.gate for item in attestations} != set(M3_GATE_IDS):
                raise ValueError("gate IDs must be unique and complete")

            runtime = _exact(
                top["runtime"],
                {"grants"},
            )
            grant_values = runtime["grants"]
            if not isinstance(grant_values, list):
                raise ValueError("runtime grants required")
            grants: list[ProductRuntimeGrant] = []
            for value in grant_values:
                grant = _exact(value, {"backend", "image", "entrypoint"})
                image_value = _exact(
                    grant["image"],
                    {
                        "reference",
                        "index_digest",
                        "platform_manifest_digest",
                        "platform",
                    },
                )
                grants.append(
                    ProductRuntimeGrant(
                        RuntimeKind(grant["backend"]),
                        ImageIdentity(
                            image_value["reference"],
                            image_value["index_digest"],
                            image_value["platform_manifest_digest"],
                            image_value["platform"],
                        ),
                        grant["entrypoint"],
                    ),
                )
            runtime_grants = tuple(grants)
            if len(set(runtime_grants)) != len(runtime_grants):
                raise ValueError("duplicate runtime grant")

            for attestation in attestations:
                for evidence in attestation.evidence:
                    evidence_path = (root / evidence.path).resolve(strict=True)
                    if root not in evidence_path.parents or not evidence_path.is_file():
                        raise FileNotFoundError
                    if sha256(evidence_path.read_bytes()).hexdigest() != evidence.sha256:
                        raise RuntimeError("evidence drift")

            report = ProductGateReport(
                sha256(raw).hexdigest(),
                top["productEnabled"],
                approval_id,
                tuple(attestations),
                runtime_grants,
            )
            if report.product_enabled and not report.ready:
                raise PermissionError("approval incomplete")
            if not report.product_enabled and (
                runtime_grants or report.approved_gate_ids
            ):
                raise ValueError("disabled manifest grants authority")
            return cls(report)
        except FileNotFoundError:
            raise ProductGateError(ProductGateErrorCode.EVIDENCE_MISSING) from None
        except RuntimeError:
            raise ProductGateError(ProductGateErrorCode.EVIDENCE_DRIFT) from None
        except PermissionError:
            raise ProductGateError(ProductGateErrorCode.APPROVAL_INCOMPLETE) from None
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            raise ProductGateError(ProductGateErrorCode.MANIFEST_INVALID) from None

    def require_activation(self) -> ProductActivationToken:
        if not self._report.product_enabled:
            raise ProductGateError(ProductGateErrorCode.PRODUCT_DISABLED)
        if not self._report.ready:
            raise ProductGateError(ProductGateErrorCode.APPROVAL_INCOMPLETE)
        return ProductActivationToken(self._report, _marker=_TOKEN_MARKER)
