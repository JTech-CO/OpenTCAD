# M2 authenticated backup control and durability

[한국어](../../ko/m2/authenticated-backup-control.md) | [M2 status](README.md)

- Status: local application-service candidate tested, product disabled
- Payload authentication: canonical HMAC-SHA256 export and import records
- Coordination: durable maintenance admission drain and fenced maintenance lease
- Rollback protection: monotonic floor in a separate SQLite control database
- Scheduling: durable interval, occurrence, claim, and retry state with no automatic deletion
- Abrupt power-loss qualification: evidence contract implemented, qualifying evidence absent

## Trust boundary

`AuthenticatedSQLiteBackupService` is an application service for a future loopback-only local server. It is not an HTTP endpoint and does not authenticate a network session. Its authentication property applies to data at rest: an injected `HMACBackupKeyring` signs canonical export metadata that commits to the inner snapshot manifest, and the thereby authenticated inner manifest commits to both SQLite payload hashes. Import verifies the outer MAC before trusting the inner identity or restoring data. Unknown keys, malformed or noncanonical records, duplicate JSON keys, payload substitution, extra entries, and signed/inner identity disagreement fail closed with path-redacted errors.

The export format does not encrypt database content. Test keys are fixtures only. Product wiring must obtain keys from an OS credential facility, restrict key-file permissions, support rotation by retaining bounded verification keys, and authenticate and authorize the local transport separately. A caller with the HMAC secret or write access to both the control DB and configured secrets remains inside the trusted computing base.

## Durable control database

`SQLiteBackupControlStore` is a schema-v1 local SQLite database in WAL mode with `synchronous=FULL`, exact-schema validation, `BEGIN IMMEDIATE` mutations, and a fixed installation UUID. It is deliberately excluded from exported state-authority pairs. It stores:

- the singleton maintenance phase and monotonically increasing maintenance generation;
- leased operation admissions that must drain before offline state;
- monotonically allocated snapshot sequences and idempotent snapshot reservations;
- a restore floor per source installation;
- durable backup schedule, pending occurrence, claim lease, and completion state.

The maintenance state machine is `open -> draining -> offline -> open`. Beginning maintenance closes new admissions atomically. Existing registered operations may finish or expire, after which only the exact maintenance owner and generation can mark the installation offline. An expired maintenance owner cannot reopen the gate; a successor must take over with the next generation. Export and import recheck the exact offline lease before final publication.

This proves quiescence only for operations that participate in the control store. Direct SQLite writers, native runtime operations, and current broker calls that bypass admission are outside the guarantee. Product composition and transport wiring must register every state/runtime operation and maintain admission heartbeats before enabling the feature.

## Authenticated export and import

An authenticated export directory contains exactly `export.json` and `snapshot/`. `export.json` identifies the HMAC algorithm and key, snapshot UUID, protected source UUID, monotonic sequence, and SHA-256 of the canonical inner `snapshot.json`; its MAC uses a format-specific domain separator. The inner snapshot retains the exact three-file state-authority contract.

Export enters maintenance, drains admissions, durably reserves a sequence, creates the locked pair snapshot, writes and syncs `export.json`, and publishes the complete outer directory. A retry with the same snapshot UUID reuses the reservation. A retry after publication validates the existing authenticated export and marks it complete rather than overwriting it. A pre-existing staging collision fails without deleting caller-owned content. Because an abrupt process exit can leave owned staging without a trustworthy cleanup marker, that path must be reviewed and removed explicitly before retry.

Import authenticates and validates the export, enters maintenance, revalidates it, and advances the external restore floor before copying either database. It restores only into a fresh nested directory, writes a second authenticated record covering the export record and all restored files, and publishes one complete outer directory. Advancing the floor first may conservatively reject older backups after an interrupted restore, but it never publishes a restore and then leaves an older floor. The same authenticated snapshot remains retryable at an equal floor; another snapshot claiming the same source sequence is rejected.

The floor prevents rollback through an older exported bundle while the control DB is intact. It does not defeat privileged replacement or rollback of the control DB itself. Hardware-backed monotonic storage or an independently replicated control service is required against that stronger attacker.

## Scheduled backup

`ScheduledSQLiteBackupRunner` executes one due occurrence when invoked by the local server. The control DB persists a minimum 60-second interval, next due time, one leased runner claim, and a pending snapshot UUID and sequence. A claim retry reuses the pending reservation. Completion and release require the exact token, owner, scheduled occurrence, reservation, persisted expiry, and an unexpired claim; completion then advances from the stored scheduled occurrence without accumulating timer drift. Windows-safe directory names use the fixed-width sequence; the signed record carries the UUID.

Wake-up, user-facing commands, destination capacity checks, notifications, and retention deletion are not implemented. The retention policy is explicitly `monotonic-no-automatic-delete`, so the runner never removes user backups.

## Publication and power-loss evidence

Every database and metadata file is flushed before publication, and symbolic links and Windows junctions are rejected. POSIX publication uses a same-parent directory rename followed by parent-directory `fsync`; macOS also requests `F_FULLFSYNC` for regular files. Windows uses `MoveFileExW` with `MOVEFILE_WRITE_THROUGH`. The original offline manager now uses the same barrier.

Four new separate-process hard exits cover sequence reservation, export publication, restore-floor advancement, and import publication. Together with the earlier state, authority, and snapshot cases, they prove process-crash publication and restart behavior. They are not abrupt host-power-loss tests.

`PowerLossQualificationEvidence` requires all ten control, copy, record, and publication cut points, at least ten abrupt power cuts per cut point, recorded storage/write-cache configuration, a completed reboot for every cut, and zero partial publications, SQLite integrity failures, or rollback violations. No such Windows, macOS, or Linux evidence is committed, so `external_power_loss_qualified` and every product-enabled flag remain `False`.

The durability assumptions follow SQLite's documented dependence on working flush primitives and filesystem behavior, Python's `fsync` contract, and Microsoft's documented write-through directory move. Only a platform matrix that physically interrupts the tested storage stack can close this gate.

## Remaining product gates

The application service, control schema, authentication format, scheduler state machine, publication barriers, and process-crash recovery are implemented and tested. Broker admission wiring, local authenticated transport, OS credential-store integration, native Docker and Podman quiescence, atomic installation activation, retention UX, capacity policy, multi-host coordination, protected control-store rollback resistance, and real abrupt-power-loss evidence remain gated.

## References

- [SQLite atomic commit and hardware assumptions](https://www.sqlite.org/atomiccommit.html)
- [SQLite write-ahead logging](https://www.sqlite.org/wal.html)
- [Python `os.fsync`](https://docs.python.org/3/library/os.html#os.fsync)
- [Microsoft `MoveFileEx` and `MOVEFILE_WRITE_THROUGH`](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexa)
