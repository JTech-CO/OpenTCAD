"""SQLite runtime fence authority durability and process contract tests."""

from __future__ import annotations

import asyncio
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from backend.app.runtime import (
    ErrorCode,
    RUNTIME_FENCE_AUTHORITY_PRODUCT_ENABLED,
    RuntimeBackendError,
    RuntimeKind,
    RuntimePhase,
    SQLITE_RUNTIME_FENCE_PRODUCT_ENABLED,
    SQLITE_RUNTIME_FENCE_SCHEMA_VERSION,
    SQLiteRuntimeFenceAuthority,
)

from .fence_authority_conformance import RuntimeFenceAuthorityConformanceMixin
from .sqlite_fence_authority_child import HARD_EXIT_CODE


class SQLiteRuntimeFenceAuthorityConformanceTests(
    RuntimeFenceAuthorityConformanceMixin,
    unittest.IsolatedAsyncioTestCase,
):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self._database = Path(self._temporary.name) / "runtime-fence.sqlite3"

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def make_authority(self):
        return SQLiteRuntimeFenceAuthority(self._database)


class SQLiteRuntimeFenceAuthorityContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self._database = Path(self._temporary.name) / "runtime-fence.sqlite3"

    def tearDown(self) -> None:
        self._temporary.cleanup()

    async def test_schema_is_exact_wal_full_and_product_disabled(self) -> None:
        for invalid in (":memory:", "file:fence.sqlite3?mode=memory", 7):
            with self.subTest(invalid=invalid):
                with self.assertRaises(TypeError):
                    SQLiteRuntimeFenceAuthority(invalid)

        authority = SQLiteRuntimeFenceAuthority(self._database)
        fence = RuntimeFenceAuthorityConformanceMixin.context(850, 851, 1)
        await authority.activate(
            fence,
            phase=RuntimePhase.QUERY,
            backend=RuntimeKind.MOCK,
        )
        with closing(sqlite3.connect(self._database)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            columns = tuple(
                row[1]
                for row in connection.execute("PRAGMA table_info(runtime_fences)")
            )
            rows = tuple(connection.execute("SELECT * FROM runtime_fences"))
        self.assertEqual(version, SQLITE_RUNTIME_FENCE_SCHEMA_VERSION)
        self.assertEqual(str(mode).casefold(), "wal")
        self.assertEqual(columns, ("job_id", "owner_id", "fencing_token"))
        self.assertEqual(rows, ((fence.identity.job_id, fence.owner_id, 1),))
        self.assertFalse(SQLITE_RUNTIME_FENCE_PRODUCT_ENABLED)
        self.assertFalse(RUNTIME_FENCE_AUTHORITY_PRODUCT_ENABLED)
        self.assertNotIn(str(self._database), repr(authority))

    async def test_reopen_retains_highest_generation(self) -> None:
        first = RuntimeFenceAuthorityConformanceMixin.context(860, 861, 1)
        second = RuntimeFenceAuthorityConformanceMixin.context(860, 862, 2)
        authority = SQLiteRuntimeFenceAuthority(self._database)
        for fence in (first, second):
            await authority.activate(
                fence,
                phase=RuntimePhase.QUERY,
                backend=RuntimeKind.MOCK,
            )

        reopened = SQLiteRuntimeFenceAuthority(self._database)
        self.assertEqual(await reopened.current(first.identity.job_id), second)
        with self.assertRaises(RuntimeBackendError) as stale:
            await reopened.activate(
                first,
                phase=RuntimePhase.QUERY,
                backend=RuntimeKind.MOCK,
            )
        self.assertEqual(stale.exception.code, ErrorCode.OPERATION_FENCED)

    async def test_locked_or_unknown_schema_fails_with_redacted_error(self) -> None:
        authority = SQLiteRuntimeFenceAuthority(
            self._database,
            busy_timeout_ms=25,
        )
        fence = RuntimeFenceAuthorityConformanceMixin.context(870, 871, 1)
        await authority.activate(
            fence,
            phase=RuntimePhase.QUERY,
            backend=RuntimeKind.MOCK,
        )
        lock = sqlite3.connect(self._database, timeout=0, isolation_level=None)
        try:
            lock.execute("BEGIN IMMEDIATE")
            with self.assertRaises(RuntimeBackendError) as locked:
                await authority.activate(
                    RuntimeFenceAuthorityConformanceMixin.context(870, 872, 2),
                    phase=RuntimePhase.KILL,
                    backend=RuntimeKind.MOCK,
                )
        finally:
            lock.rollback()
            lock.close()
        self.assertEqual(locked.exception.code, ErrorCode.RUNTIME_UNAVAILABLE)
        self.assertEqual(
            locked.exception.record.detail,
            "runtime-fence-authority-unavailable",
        )
        self.assertNotIn(str(self._database), str(locked.exception))

        mismatched = Path(self._temporary.name) / "mismatched.sqlite3"
        with closing(sqlite3.connect(mismatched)) as connection:
            connection.execute("CREATE TABLE runtime_fences (job_id TEXT)")
            connection.execute("PRAGMA user_version = 1")
            connection.commit()
        with self.assertRaises(RuntimeBackendError) as invalid:
            await SQLiteRuntimeFenceAuthority(mismatched).current(
                fence.identity.job_id,
            )
        self.assertEqual(invalid.exception.code, ErrorCode.RUNTIME_UNAVAILABLE)

        corrupt = Path(self._temporary.name) / "corrupt.sqlite3"
        corrupt_authority = SQLiteRuntimeFenceAuthority(corrupt)
        await corrupt_authority.activate(
            fence,
            phase=RuntimePhase.QUERY,
            backend=RuntimeKind.MOCK,
        )
        with closing(sqlite3.connect(corrupt)) as connection:
            connection.execute(
                "UPDATE runtime_fences SET owner_id = 'not-a-uuid'",
            )
            connection.commit()
        with self.assertRaises(RuntimeBackendError) as invalid_row:
            await SQLiteRuntimeFenceAuthority(corrupt).current(
                fence.identity.job_id,
            )
        self.assertEqual(
            invalid_row.exception.code,
            ErrorCode.RUNTIME_UNAVAILABLE,
        )

    async def test_hard_exit_activation_survives_and_fences_parent(self) -> None:
        first = RuntimeFenceAuthorityConformanceMixin.context(880, 881, 1)
        second = RuntimeFenceAuthorityConformanceMixin.context(880, 882, 2)
        authority = SQLiteRuntimeFenceAuthority(self._database)
        await authority.activate(
            first,
            phase=RuntimePhase.QUERY,
            backend=RuntimeKind.MOCK,
        )

        repository = Path(__file__).resolve().parents[3]
        completed = await asyncio.to_thread(
            subprocess.run,
            [
                sys.executable,
                "-m",
                "backend.tests.runtime.sqlite_fence_authority_child",
                str(self._database),
                second.identity.job_id,
                second.owner_id,
                str(second.fencing_token),
            ],
            cwd=repository,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            HARD_EXIT_CODE,
            msg=f"stdout={completed.stdout!r} stderr={completed.stderr!r}",
        )
        reopened = SQLiteRuntimeFenceAuthority(self._database)
        self.assertEqual(await reopened.current(first.identity.job_id), second)
        with self.assertRaises(RuntimeBackendError) as stale:
            await authority.verify(
                first,
                phase=RuntimePhase.QUERY,
                backend=RuntimeKind.MOCK,
            )
        self.assertEqual(stale.exception.code, ErrorCode.OPERATION_FENCED)


if __name__ == "__main__":
    unittest.main()
