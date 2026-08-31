"""Single-instance lifetime lock and secret-free endpoint publication."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import BinaryIO
from uuid import UUID


class LocalInstanceAlreadyRunning(Exception):
    pass


@dataclass(frozen=True, slots=True)
class LocalEndpointRecord:
    startup_id: str
    process_id: int
    port: int
    manifest_sha256: str
    mode: str

    def __post_init__(self) -> None:
        try:
            startup = UUID(self.startup_id)
        except (AttributeError, TypeError, ValueError) as error:
            raise TypeError("Endpoint startup ID is invalid.") from error
        if (
            str(startup) != self.startup_id
            or not isinstance(self.process_id, int)
            or isinstance(self.process_id, bool)
            or self.process_id < 1
            or not isinstance(self.port, int)
            or isinstance(self.port, bool)
            or not 1 <= self.port <= 65_535
            or len(self.manifest_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.manifest_sha256)
            or self.mode not in {"preview", "product"}
        ):
            raise TypeError("Endpoint record is invalid.")

    def as_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "startupId": self.startup_id,
            "processId": self.process_id,
            "port": self.port,
            "manifestSha256": self.manifest_sha256,
            "mode": self.mode,
        }


class LocalInstance:
    def __init__(self, lock_path: Path, endpoint_path: Path) -> None:
        self._lock_path = lock_path
        self._endpoint_path = endpoint_path
        self._stream: BinaryIO | None = None
        self._startup_id: str | None = None

    @staticmethod
    def _try_lock(stream: BinaryIO) -> bool:
        stream.seek(0)
        if sys.platform == "win32":
            import msvcrt

            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False
        import fcntl

        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False

    @staticmethod
    def _unlock(stream: BinaryIO) -> None:
        stream.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def acquire(self) -> None:
        if self._stream is not None:
            return
        stream = self._lock_path.open("a+b", buffering=0)
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            os.fsync(stream.fileno())
        if not self._try_lock(stream):
            stream.close()
            raise LocalInstanceAlreadyRunning
        self._stream = stream
        try:
            self._endpoint_path.unlink(missing_ok=True)
        except OSError:
            self.close()
            raise

    def publish(self, record: LocalEndpointRecord) -> None:
        if self._stream is None:
            raise RuntimeError("Local instance lock is not held.")
        raw = (
            json.dumps(record.as_dict(), sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("ascii")
        temporary = self._endpoint_path.with_name(
            f".{self._endpoint_path.name}.{record.startup_id}.tmp",
        )
        try:
            with temporary.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._endpoint_path)
            self._startup_id = record.startup_id
        finally:
            temporary.unlink(missing_ok=True)

    def close(self) -> None:
        stream = self._stream
        self._stream = None
        if self._startup_id is not None:
            try:
                value = json.loads(self._endpoint_path.read_text(encoding="ascii"))
                if value.get("startupId") == self._startup_id:
                    self._endpoint_path.unlink(missing_ok=True)
            except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
                pass
        self._startup_id = None
        if stream is not None:
            try:
                self._unlock(stream)
            finally:
                stream.close()

    def __enter__(self) -> LocalInstance:
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
