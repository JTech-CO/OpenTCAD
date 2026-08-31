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
]
