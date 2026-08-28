# M2 coordinated SQLite offline snapshot and restore

[한국어](../../ko/m2/sqlite-offline-snapshot-restore.md) | [M2 status](README.md)

- Status: local offline candidate tested, product disabled
- Payloads: broker state schema v3 and runtime fence authority schema v1
- Publication: manifest-last snapshot directory and restore-record-last fresh directory
- Live backup: unsupported; authenticated application-service wrapper: implemented but product disabled
- Durable publication barriers: implemented; abrupt power-loss qualification: not achieved

## Boundary

`SQLiteOfflineSnapshotManager` coordinates the two independent SQLite databases without claiming that their normal commits are atomic. The caller must provide a typed quiescence assertion stating that broker admission, runtime operations, and database writers are stopped. The candidate validates this assertion but cannot discover or enforce shutdown across other processes. `SQLITE_OFFLINE_SNAPSHOT_LIVE_WRITES_SUPPORTED` therefore remains `False`.

Snapshot creation acquires the broker-state write lock first and the authority write lock second with `BEGIN IMMEDIATE`. This order closes new state writes before freezing authority changes and preserves the existing rule that authority may be equal to or behind committed state but may never be ahead of it. While both locks are held, the Python SQLite backup API creates standalone database payloads. WAL and shared-memory sidecars are never copied.

The source must already be an exact schema-v3 state database and exact schema-v1 authority database in WAL mode with `synchronous=FULL`. Missing, locked, corrupt, unknown, or structurally different sources fail with stable path-redacted errors. This component never initializes a missing source.

## Canonical bundle

A published bundle is one directory with exactly three regular, non-link files:

| File | Purpose |
|---|---|
| `broker-state.sqlite3` | SQLite backup of append-only events and current lease rows |
| `runtime-fence.sqlite3` | SQLite backup of the highest runtime generation per job |
| `snapshot.json` | Canonical UTF-8 JSON manifest written after both payloads |

The schema-v1 manifest has fixed keys, canonical JSON encoding, a canonical snapshot UUID, caller-supplied source-instance UUID, positive signed 64-bit sequence, quiescence UUID, exact schema versions, byte lengths, SHA-256 values, and state/authority job counts. Duplicate JSON keys, noncanonical encoding, extra files, links, missing files, payloads larger than 1 GiB, size or hash drift, integrity-check failure, and schema drift fail closed.

SHA-256 alone is not a signature or authenticity proof. The separate [authenticated backup-control contract](authenticated-backup-control.md) now wraps and signs the canonical manifest with HMAC-SHA256 while leaving this low-level three-file format unchanged.

## Pair coherence

Validation checks every state row, contiguous per-job revisions, legal state transitions, owner generation continuity, current lease agreement, every authority row, and exact job/owner/token identities. Each authority row must reference a state generation that exists with the same owner. Authority ahead of the latest state token is rejected as `state-authority-conflict`. A missing or older authority row is accepted because the existing activation-gap recovery contract can safely claim the next generation.

This semantic rule detects an older state database paired with a newer authority database even if an operator rewrites the untrusted hashes. It cannot prove that two independently forged files came from the claimed installation.

## Restore and rollback policy

Restore requires three caller-held trust anchors: the exact snapshot UUID, exact source-instance UUID, and a minimum accepted snapshot sequence. Identity mismatch and a sequence below the floor fail closed. The low-level manager still accepts a caller floor. The separate backup-control DB now persists and advances a per-source floor before authenticated import; privileged rollback of that external control DB remains outside the guarantee.

The target must be a new directory. Existing targets are never overwritten. The manager validates the bundle before copying, restores both databases into a sibling staging directory, validates the restored pair again, writes canonical `restore.json`, flushes all files, and publishes the whole directory with a platform durability barrier. The result exposes fixed state and authority paths that the existing adapters can reopen. Startup recovery then handles expired leases and any allowed state-ahead-of-authority gap with the next fencing token.

## Crash seams and evidence

Eight deterministic checkpoints cover each database copy, metadata write, and directory publication for creation and restore. A separate process hard-exits after both snapshot database copies but before the manifest, and the final bundle path remains absent. Another hard-exits after the first restore database copy, and the final restore path remains absent. Staging directories may remain after a hard exit, but validators never accept them and retry with the same identity fails closed until an operator inspects and removes the exact staging directory.

Seven focused tests cover offline gating and redaction, canonical round trip, restored recovery generation advance, torn/extra/tampered rejection, a rehashed mixed-pair negative control, identity and rollback-floor checks, fresh-target enforcement, locked and unknown sources, and the two process hard-exit seams. These tests use temporary local SQLite files and the strict mock recovery path only.

## Product gate

The low-level manager still does not capture native runtime objects, coordinate a running broker, authenticate transport callers, repair corruption, overwrite a live installation, or provide multi-host coordination. The separate application-service candidate adds maintenance admission, authenticated export/import, durable floor storage, interval schedule state, and platform publication barriers, but current broker operations do not auto-register and no actual abrupt-power-loss evidence exists. Product Docker and Podman quiescence, local launcher and command wiring, OS key storage, automatic wake-up, retention UX, native-object reconciliation, and platform power-cut matrices remain gated. M3 still owns product wiring for user-facing commands and lifecycle integration.
