"""Fail-closed product activation and local-service boundaries."""

from .gates import (
    M3_GATE_IDS,
    M3_MANIFEST_SCHEMA_VERSION,
    EvidenceRecord,
    GateAttestation,
    M3ProductGate,
    ProductActivationToken,
    ProductGateError,
    ProductGateErrorCode,
    ProductGateReport,
    ProductRuntimeGrant,
)
from .release_profile import (
    PRODUCT_RELEASE_PROFILES,
    ProductReleaseProfile,
    release_profile_for,
)

__all__ = [
    "EvidenceRecord",
    "GateAttestation",
    "M3_GATE_IDS",
    "M3_MANIFEST_SCHEMA_VERSION",
    "M3ProductGate",
    "ProductActivationToken",
    "ProductGateError",
    "ProductGateErrorCode",
    "ProductGateReport",
    "ProductRuntimeGrant",
    "PRODUCT_RELEASE_PROFILES",
    "ProductReleaseProfile",
    "release_profile_for",
]
