"""Subprocess helper that commits a fence generation and hard-exits."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys

from backend.app.runtime import (
    JobIdentity,
    RuntimeFencingContext,
    RuntimeKind,
    RuntimePhase,
    SQLiteRuntimeFenceAuthority,
)


HARD_EXIT_CODE = 92


async def _run(
    database: Path,
    job_id: str,
    owner_id: str,
    fencing_token: int,
) -> None:
    authority = SQLiteRuntimeFenceAuthority(database)
    await authority.activate(
        RuntimeFencingContext(
            JobIdentity(job_id),
            owner_id,
            fencing_token,
        ),
        phase=RuntimePhase.QUERY,
        backend=RuntimeKind.MOCK,
    )
    os._exit(HARD_EXIT_CODE)


def main() -> int:
    if len(sys.argv) != 5:
        return 64
    asyncio.run(
        _run(
            Path(sys.argv[1]),
            sys.argv[2],
            sys.argv[3],
            int(sys.argv[4]),
        ),
    )
    return 70


if __name__ == "__main__":
    raise SystemExit(main())
