"""Cross-platform publication barriers and external power-loss evidence contract."""

from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from uuid import UUID


DURABLE_PUBLICATION_PRODUCT_ENABLED = False
POWER_LOSS_MIN_REPETITIONS_PER_CUT = 10
POWER_LOSS_REQUIRED_CUT_POINTS = (
    "control-commit",
    "state-backup",
    "authority-backup",
    "authentication-record",
    "export-publication",
    "restore-floor-commit",
    "state-restore",
    "authority-restore",
    "import-record",
    "import-publication",
)


class DurablePublicationError(Exception):
    """Path-redacted durability failure."""

    def __init__(self) -> None:
        super().__init__("durable-publication-failed")

    def as_dict(self) -> dict[str, str]:
        return {"code": "durable-publication-failed"}


def _canonical_uuid(value: str, label: str) -> None:
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise TypeError(f"{label} must be a canonical UUID.") from error
    if str(parsed) != value:
        raise TypeError(f"{label} must be a canonical UUID.")


def _local_path(value: str | PathLike[str], label: str) -> Path:
    if not isinstance(value, (str, PathLike)):
        raise TypeError(f"{label} must be path-like.")
    path = Path(os.fspath(value))
    if not str(path) or "\x00" in str(path):
        raise TypeError(f"{label} must be a local path.")
    return path


def is_link_like(path: Path) -> bool:
    """Reject symbolic links and Windows junctions at publication boundaries."""

    try:
        is_junction = getattr(path, "is_junction", None)
        return path.is_symlink() or bool(is_junction and is_junction())
    except OSError:
        return True


@dataclass(frozen=True, slots=True)
class DurablePublicationProfile:
    platform: str
    file_barrier: str
    directory_publication_barrier: str
    external_power_loss_qualified: bool = False


def publication_profile() -> DurablePublicationProfile:
    if os.name == "nt":
        return DurablePublicationProfile(
            "windows",
            "flush-file-buffers-via-fsync",
            "movefileex-write-through",
        )
    if sys.platform == "darwin":
        return DurablePublicationProfile(
            "macos",
            "fsync-plus-f-fullfsync",
            "rename-plus-parent-directory-fsync",
        )
    return DurablePublicationProfile(
        "linux",
        "fsync",
        "rename-plus-parent-directory-fsync",
    )


def sync_file(path: str | PathLike[str]) -> None:
    target = _local_path(path, "Durable file")
    try:
        if not target.is_file() or is_link_like(target):
            raise OSError("not a regular file")
        with target.open("r+b") as stream:
            stream.flush()
            os.fsync(stream.fileno())
            if sys.platform == "darwin":
                import fcntl

                fcntl.fcntl(stream.fileno(), 51)
    except (OSError, ValueError):
        raise DurablePublicationError() from None


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        raise DurablePublicationError() from None


def _sync_tree(root: Path) -> None:
    directories: list[Path] = []
    try:
        for current, names, files in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)
            directories.append(current_path)
            for name in (*names, *files):
                child = current_path / name
                if is_link_like(child):
                    raise OSError("links are not durable publication inputs")
            for name in files:
                sync_file(current_path / name)
        for directory in reversed(directories):
            _sync_directory(directory)
    except (DurablePublicationError, OSError):
        raise DurablePublicationError() from None


def _windows_write_through_move(source: Path, destination: Path) -> None:
    move_file = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
    move_file.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32)
    move_file.restype = ctypes.c_int
    if not move_file(str(source), str(destination), 0x00000008):
        raise DurablePublicationError()


def publish_directory(
    staging: str | PathLike[str],
    destination: str | PathLike[str],
) -> None:
    """Publish a fully synced sibling directory without overwriting a target."""

    source = _local_path(staging, "Publication staging directory")
    target = _local_path(destination, "Publication destination")
    try:
        if (
            not source.is_dir()
            or is_link_like(source)
            or target.exists()
            or is_link_like(target)
            or not target.parent.is_dir()
            or is_link_like(target.parent)
            or not os.path.samefile(source.parent, target.parent)
        ):
            raise OSError("publication paths are invalid")
        _sync_tree(source)
        if os.name == "nt":
            _windows_write_through_move(source, target)
        else:
            source.rename(target)
            _sync_directory(target.parent)
    except DurablePublicationError:
        raise
    except (OSError, ValueError):
        raise DurablePublicationError() from None


@dataclass(frozen=True, slots=True)
class PowerLossQualificationEvidence:
    """Evidence supplied by an external abrupt-power-cut harness, never inferred."""

    evidence_id: str
    platform: str
    filesystem: str
    storage_device: str
    cut_points: tuple[str, ...]
    repetitions_per_cut: int
    abrupt_power_cut: bool
    write_cache_configuration_recorded: bool
    every_reboot_completed: bool
    partial_publications: int
    sqlite_integrity_failures: int
    rollback_violations: int

    def __post_init__(self) -> None:
        _canonical_uuid(self.evidence_id, "Power-loss evidence ID")
        for value, label in (
            (self.platform, "platform"),
            (self.filesystem, "filesystem"),
            (self.storage_device, "storage device"),
        ):
            if not isinstance(value, str) or not value or len(value) > 128:
                raise TypeError(f"Power-loss {label} is invalid.")
        points = tuple(self.cut_points)
        if points != POWER_LOSS_REQUIRED_CUT_POINTS:
            raise TypeError("Power-loss cut-point coverage is incomplete.")
        object.__setattr__(self, "cut_points", points)
        if (
            not isinstance(self.repetitions_per_cut, int)
            or isinstance(self.repetitions_per_cut, bool)
            or self.repetitions_per_cut < 1
        ):
            raise TypeError("Power-loss repetition count is invalid.")
        for value in (
            self.abrupt_power_cut,
            self.write_cache_configuration_recorded,
            self.every_reboot_completed,
        ):
            if not isinstance(value, bool):
                raise TypeError("Power-loss qualification markers must be bool.")
        for value in (
            self.partial_publications,
            self.sqlite_integrity_failures,
            self.rollback_violations,
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise TypeError("Power-loss failure counts must be non-negative.")

    @property
    def qualified(self) -> bool:
        return (
            self.repetitions_per_cut >= POWER_LOSS_MIN_REPETITIONS_PER_CUT
            and self.abrupt_power_cut
            and self.write_cache_configuration_recorded
            and self.every_reboot_completed
            and self.partial_publications == 0
            and self.sqlite_integrity_failures == 0
            and self.rollback_violations == 0
        )
