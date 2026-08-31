"""Product-only native operation guard layered over the durable M2 authority."""

from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
from pathlib import Path
import os
import sys
import time
from typing import AsyncIterator, BinaryIO

from .errors import ErrorCode, RetryDisposition, RuntimeBackendError, RuntimePhase
from .fencing import RuntimeFencingContext
from .models import RuntimeKind
from .sqlite_fence_authority import SQLiteRuntimeFenceAuthority


class _NativeFileLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._stream: BinaryIO | None = None

    def _open(self) -> BinaryIO:
        stream = self._path.open("a+b", buffering=0)
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            os.fsync(stream.fileno())
        stream.seek(0)
        return stream

    @staticmethod
    def _try(stream: BinaryIO) -> bool:
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
    def _release(stream: BinaryIO) -> None:
        stream.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    async def acquire(self, timeout_seconds: float) -> None:
        if self._stream is not None:
            raise RuntimeError("Native operation lock is already held.")
        stream = self._open()
        deadline = time.monotonic() + timeout_seconds
        try:
            while not self._try(stream):
                if time.monotonic() >= deadline:
                    raise TimeoutError
                await asyncio.sleep(0.025)
        except BaseException:
            stream.close()
            raise
        self._stream = stream

    def release(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                self._release(stream)
            finally:
                stream.close()


class ProductRuntimeFenceAuthority:
    """Serializes activation and native mutation for each durable job ID."""

    def __init__(
        self,
        database: str | os.PathLike[str],
        lock_root: str | os.PathLike[str],
        *,
        operation_timeout_seconds: float = 120.0,
    ) -> None:
        root = Path(lock_root)
        if (
            not root.is_dir()
            or root.is_symlink()
            or not isinstance(operation_timeout_seconds, (int, float))
            or isinstance(operation_timeout_seconds, bool)
            or not 1.0 <= operation_timeout_seconds <= 3_600.0
        ):
            raise TypeError("Product fence lock configuration is invalid.")
        self._database = Path(database)
        self._authority = SQLiteRuntimeFenceAuthority(self._database)
        self._lock_root = root.resolve(strict=True)
        self._operation_timeout_seconds = float(operation_timeout_seconds)

    @property
    def database(self) -> Path:
        return self._database

    def _lock(self, fence: RuntimeFencingContext) -> _NativeFileLock:
        return _NativeFileLock(
            self._lock_root / f"runtime-{fence.identity.job_id}.lock",
        )

    @staticmethod
    def _unavailable(phase: RuntimePhase, backend: RuntimeKind) -> RuntimeBackendError:
        return RuntimeBackendError(
            ErrorCode.RUNTIME_UNAVAILABLE,
            phase,
            retry=RetryDisposition.INFRASTRUCTURE,
            backend=backend.value,
            detail="native-operation-lock-unavailable",
        )

    async def activate(
        self,
        fence: RuntimeFencingContext,
        *,
        phase: RuntimePhase,
        backend: RuntimeKind,
    ) -> None:
        lock = self._lock(fence)
        try:
            await lock.acquire(self._operation_timeout_seconds)
            await self._authority.activate(fence, phase=phase, backend=backend)
        except TimeoutError:
            raise self._unavailable(phase, backend) from None
        finally:
            lock.release()

    async def verify(
        self,
        fence: RuntimeFencingContext,
        *,
        phase: RuntimePhase,
        backend: RuntimeKind,
    ) -> None:
        await self._authority.verify(fence, phase=phase, backend=backend)

    async def current(self, job_id: str) -> RuntimeFencingContext | None:
        return await self._authority.current(job_id)

    @asynccontextmanager
    async def operation_guard(
        self,
        fence: RuntimeFencingContext,
        *,
        phase: RuntimePhase,
        backend: RuntimeKind,
    ) -> AsyncIterator[None]:
        lock = self._lock(fence)
        try:
            await lock.acquire(self._operation_timeout_seconds)
            await self._authority.verify(fence, phase=phase, backend=backend)
            try:
                yield
            finally:
                await asyncio.shield(
                    self._authority.verify(fence, phase=phase, backend=backend),
                )
        except TimeoutError:
            raise self._unavailable(phase, backend) from None
        finally:
            lock.release()
