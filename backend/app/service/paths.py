"""Cross-platform, per-user filesystem layout for the local product."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Mapping


def _absolute(value: str | None, fallback: Path) -> Path:
    if value:
        candidate = Path(value)
        if candidate.is_absolute() or value.startswith("/"):
            return candidate
    return fallback


def _link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    checker = getattr(path, "is_junction", None)
    return bool(checker()) if checker is not None else False


def _ensure_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir() or _link_like(path):
        raise OSError("OpenTCAD local directory is not a regular directory.")
    if os.name != "nt":
        path.chmod(0o700)


@dataclass(frozen=True, slots=True)
class LocalProductPaths:
    config_root: Path
    state_root: Path
    runtime_root: Path

    @classmethod
    def for_platform(
        cls,
        *,
        platform: str = sys.platform,
        environment: Mapping[str, str] | None = None,
        home: Path | None = None,
    ) -> LocalProductPaths:
        env = os.environ if environment is None else environment
        home_path = Path.home() if home is None else Path(home)
        if platform == "win32":
            base = _absolute(env.get("LOCALAPPDATA"), home_path / "AppData" / "Local") / "OpenTCAD"
            return cls(base / "config", base / "state", base / "run")
        if platform == "darwin":
            base = home_path / "Library" / "Application Support" / "OpenTCAD"
            return cls(base / "config", base / "state", base / "run")
        if platform.startswith("linux"):
            config = _absolute(env.get("XDG_CONFIG_HOME"), home_path / ".config") / "opentcad"
            state = _absolute(env.get("XDG_STATE_HOME"), home_path / ".local" / "state") / "opentcad"
            runtime = _absolute(env.get("XDG_RUNTIME_DIR"), state / "run") / "opentcad"
            return cls(config, state, runtime)
        raise OSError("OpenTCAD local service does not support this platform.")

    @classmethod
    def at_root(cls, root: str | Path) -> LocalProductPaths:
        base = Path(root)
        if not base.is_absolute():
            raise TypeError("Local data root must be absolute.")
        return cls(base / "config", base / "state", base / "run")

    def prepare(self) -> None:
        for path in (
            self.config_root,
            self.state_root,
            self.runtime_root,
            self.backup_root,
            self.lock_root,
        ):
            _ensure_directory(path)

    @property
    def configuration_file(self) -> Path:
        return self.config_root / "local-service.json"

    @property
    def installation_file(self) -> Path:
        return self.state_root / "installation.json"

    @property
    def state_database(self) -> Path:
        return self.state_root / "broker-state.sqlite3"

    @property
    def fence_database(self) -> Path:
        return self.state_root / "runtime-fence.sqlite3"

    @property
    def control_database(self) -> Path:
        return self.state_root / "backup-control.sqlite3"

    @property
    def backup_root(self) -> Path:
        return self.state_root / "backups"

    @property
    def lock_root(self) -> Path:
        return self.runtime_root / "locks"

    @property
    def instance_lock(self) -> Path:
        return self.runtime_root / "service.lock"

    @property
    def endpoint_file(self) -> Path:
        return self.runtime_root / "endpoint.json"
