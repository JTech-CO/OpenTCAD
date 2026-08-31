"""Strict operator configuration with no command, image, or path injection surface."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from backend.app.runtime.models import RuntimeKind


_MAX_CONFIGURATION_BYTES = 64 * 1024


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


@dataclass(frozen=True, slots=True)
class LocalUserConfiguration:
    runtime_backend: RuntimeKind
    api_port: int
    backup_interval_ms: int
    recovery_page_limit: int

    def __post_init__(self) -> None:
        if self.runtime_backend not in {RuntimeKind.DOCKER, RuntimeKind.PODMAN}:
            raise TypeError("Local runtime backend must be docker or podman.")
        if (
            not isinstance(self.api_port, int)
            or isinstance(self.api_port, bool)
            or (self.api_port != 0 and not 1_024 <= self.api_port <= 65_535)
            or not isinstance(self.backup_interval_ms, int)
            or isinstance(self.backup_interval_ms, bool)
            or not 60_000 <= self.backup_interval_ms <= 31_536_000_000
            or not isinstance(self.recovery_page_limit, int)
            or isinstance(self.recovery_page_limit, bool)
            or not 1 <= self.recovery_page_limit <= 1_000
        ):
            raise TypeError("Local operator configuration is invalid.")

    @classmethod
    def load(cls, path: str | Path) -> LocalUserConfiguration:
        try:
            candidate = Path(path)
            if not candidate.is_file() or candidate.is_symlink():
                raise OSError
            raw = candidate.read_bytes()
            if not raw or len(raw) > _MAX_CONFIGURATION_BYTES:
                raise ValueError
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs)
            if not isinstance(value, dict) or set(value) != {
                "schemaVersion",
                "runtimeBackend",
                "apiPort",
                "backupIntervalMs",
                "recoveryPageLimit",
            }:
                raise ValueError
            if value["schemaVersion"] != 1:
                raise ValueError
            return cls(
                RuntimeKind(value["runtimeBackend"]),
                value["apiPort"],
                value["backupIntervalMs"],
                value["recoveryPageLimit"],
            )
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            raise ValueError("Local service configuration is invalid.") from None

    def as_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "runtimeBackend": self.runtime_backend.value,
            "apiPort": self.api_port,
            "backupIntervalMs": self.backup_interval_ms,
            "recoveryPageLimit": self.recovery_page_limit,
        }
