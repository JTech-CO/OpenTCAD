"""Bounded same-origin serving for the compiled OpenTCAD web artifact."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat


_ASSET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")
_MAX_ASSET_BYTES = 16 * 1024 * 1024
_WINDOWS_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".ico": "image/x-icon",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".woff2": "font/woff2",
}


@dataclass(frozen=True, slots=True)
class LocalStaticAsset:
    body: bytes
    content_type: str
    cache_control: str
    is_index: bool = False


def _is_link_like(path: Path) -> bool:
    """Treat every symlink, junction, or Windows reparse point as unsafe."""

    try:
        metadata = path.lstat()
        junction = getattr(path, "is_junction", None)
        return (
            path.is_symlink()
            or bool(junction and junction())
            or bool(
                getattr(metadata, "st_file_attributes", 0)
                & _WINDOWS_REPARSE_POINT
            )
        )
    except OSError:
        return True


def _regular_asset_path(root: Path, relative: Path) -> Path:
    """Resolve one allowlisted asset without traversing a link-like component."""

    current = root
    if _is_link_like(current) or not current.is_dir():
        raise OSError("asset root is unsafe")
    for index, part in enumerate(relative.parts):
        current = current / part
        if _is_link_like(current):
            raise OSError("asset path is link-like")
        if index < len(relative.parts) - 1 and not current.is_dir():
            raise OSError("asset parent is not a directory")
    resolved = current.resolve(strict=True)
    if (
        resolved == root
        or root not in resolved.parents
        or _is_link_like(resolved)
        or not resolved.is_file()
    ):
        raise OSError("asset escaped its build root")
    return resolved


class LocalStaticAssets:
    """Maps a deliberately small URL space into one immutable build root."""

    def __init__(self, root: str | Path) -> None:
        try:
            source = Path(root)
            if _is_link_like(source) or not source.is_dir():
                raise OSError("asset root is link-like")
            resolved = source.resolve(strict=True)
            index = _regular_asset_path(resolved, Path("index.html"))
        except (OSError, RuntimeError):
            raise TypeError("Local static asset root is unavailable.") from None
        if (
            not resolved.is_dir()
            or _is_link_like(resolved)
            or not index.is_file()
            or _is_link_like(index)
            or index.parent != resolved
        ):
            raise TypeError("Local static asset root is invalid.")
        self._root = resolved

    @property
    def root(self) -> Path:
        return self._root

    @staticmethod
    def _relative(path: str) -> Path | None:
        if path in {"/", "/index.html"}:
            return Path("index.html")
        if path == "/og.png":
            return Path("og.png")
        parts = path.split("/")
        if (
            len(parts) == 3
            and parts[0] == ""
            and parts[1] == "assets"
            and _ASSET_NAME.fullmatch(parts[2]) is not None
        ):
            return Path("assets") / parts[2]
        return None

    def matches(self, path: str) -> bool:
        return isinstance(path, str) and self._relative(path) is not None

    def read(self, path: str) -> LocalStaticAsset:
        relative = self._relative(path)
        if relative is None:
            raise FileNotFoundError
        try:
            candidate = _regular_asset_path(self._root, relative)
            before = candidate.stat()
            size = before.st_size
            if size < 1 or size > _MAX_ASSET_BYTES:
                raise OSError
            content_type = _CONTENT_TYPES.get(candidate.suffix.casefold())
            if content_type is None:
                raise OSError
            with candidate.open("rb") as stream:
                opened_before = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened_before.st_mode) or not os.path.samestat(
                    before,
                    opened_before,
                ):
                    raise OSError
                body = stream.read(_MAX_ASSET_BYTES + 1)
                opened_after = os.fstat(stream.fileno())
            current = _regular_asset_path(self._root, relative)
            current_metadata = current.stat()
            if (
                current != candidate
                or not os.path.samestat(opened_after, current_metadata)
                or opened_before.st_size != opened_after.st_size
                or opened_before.st_mtime_ns != opened_after.st_mtime_ns
                or len(body) != size
            ):
                raise OSError
        except (OSError, RuntimeError):
            raise FileNotFoundError from None
        is_index = relative == Path("index.html")
        return LocalStaticAsset(
            body,
            content_type,
            "no-store" if is_index else "public, max-age=31536000, immutable",
            is_index,
        )
