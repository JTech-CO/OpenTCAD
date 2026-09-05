# External physical power-loss qualification

[한국어](README.ko.md)

This procedure is an external laboratory gate. Do not run it on a development workstation, a production machine, or storage containing unique data. OpenTCAD does not claim that process termination, a virtual-machine reset, or a normal shutdown is a physical power cut.

## Required setup

- one dedicated host and disposable storage configuration;
- an independently controlled power distribution unit or equivalent hardware cut mechanism;
- recorded operating system, filesystem, storage model, firmware, controller, and write-cache policy;
- one immutable OpenTCAD revision and exact runtime/image grants;
- a separate observer that records each boot, armed cut point, integrity result, and rollback-floor result.

## Matrix

Exercise the ten ordered cut points declared in backend/app/broker/durability.py. Run at least ten abrupt cuts at every point. One complete evidence record therefore contains at least 100 physical cuts. Repeat the record for every platform, filesystem, storage, and cache configuration submitted for approval.

After every reboot:

1. preserve the pre-cut marker and host logs outside the system under test;
2. run SQLite quick_check and integrity_check on the control, state, and fence databases;
3. verify that no partially published export or import is accepted;
4. verify that the OS-protected floor rejects every older authenticated snapshot;
5. start recovery and verify that it never synthesizes success;
6. query Docker and Podman labels and require zero unexplained managed objects;
7. append the result to the external evidence ledger.

The aggregate v1 schema remains the minimum summary format. The row format is
documented by `validation/schemas/m3-power-loss-ledger.schema.json`. Product gate review
also requires a v2 row ledger validated with:

    node tools/check-m3-power-loss.mjs <ledger.json>

The v2 validator requires one unique row for every cut point and repetition,
an independently controlled physical PDU, relay, or battery cut, distinct boot
identities, all three SQLite checks, rollback and publication results, exact
revision/runtime/image bindings, and a reviewer other than the observer.
Passing it only makes the record eligible for gate review; it never activates
the product.

An evidence record is eligible for review only when every reboot completed, partial publications are zero, SQLite integrity failures are zero, rollback violations are zero, and the record matches validation/schemas/m3-power-loss-evidence.schema.json.

The repository currently contains a blocked status record with zero physical cuts. Never edit that count based on unit tests or process hard exits.
