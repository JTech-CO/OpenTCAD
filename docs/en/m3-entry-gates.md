# M3 product entry gates

[한국어](../ko/m3-entry-gates.md)

OpenTCAD now contains the product connection layer for a local service, but product activation remains disabled. Code completion does not substitute for runtime, license, numerical, platform, or physical power-loss evidence.

## Implemented product path

- Docker and Podman OCI adapters use shell-free bounded subprocess transport.
- Every runtime object carries the exact job ID, owner ID, and fencing generation. The adapter checks durable authority before and after an operation, verifies native labels before mutation, and verifies labels immediately after object creation.
- Runtime authority is an exact grant over backend, immutable image identity, and configured entrypoint. Approved lists are not combined as a Cartesian product.
- The API binds only to a numeric loopback address and validates the peer, Host, Origin, bearer secret, request size, JSON shape, and duplicate keys.
- A bounded execution lane and a separate control lane allow cancellation while a solver job is running.
- Startup recovery completes before API admission. Execution, cancellation, maintenance, authenticated export/import, scheduled backup, and shutdown share one lifecycle assembly.
- Windows Credential Manager, macOS Keychain, and Linux Secret Service adapters keep API and HMAC secrets outside application backups.
- A second monotonic restore floor is stored in the OS credential service and advances before an import.

## Implementation map

| Path | Responsibility |
|---|---|
| `backend/app/product/gates.py` | Exact, evidence-hash-bound product activation and runtime grants |
| `backend/app/runtime/oci_backend.py` | Docker and Podman command transport, hardening, image identity, and native object fencing |
| `backend/app/service/product_composition.py` | M3-only bridge that preserves the frozen M2 composition and requires a matching activation token |
| `backend/app/service/worker.py` | Typed lifecycle queue, reserved cancellation lane, admission heartbeat, and offline import arbitration |
| `backend/app/service/local_api.py` | Authenticated loopback HTTP boundary and strict request codecs |
| `backend/app/service/credentials.py` | Windows, macOS, and Linux credential adapters |
| `backend/app/service/anti_rollback.py` | OS-protected monotonic restore floor |
| `backend/app/service/scheduler.py` | Restart-safe scheduled backup wake-up loop and retained failure state |
| `backend/app/service/application.py` | Recovery-first product service assembly and shutdown ordering |
| `tools/qualify-runtime.py` | Non-promoting host observation tool |

## Gate status

| Gate | Implementation | Qualification or approval |
|---|---|---|
| Docker and Podman adapters | Implemented and fake-CLI tested | Blocked: Docker daemon unavailable on the observed Windows host, Podman absent |
| Native fencing | Implemented and tamper/stale-owner tested | Blocked: no native Docker or Podman object evidence |
| Local API and worker transport | Implemented and loopback-socket tested | Awaiting release review |
| Lifecycle integration | Implemented and SQLite assembly tested | Awaiting release review |
| OS credentials and scheduled backup | Three host adapters and scheduler implemented | Blocked: only Windows DPAPI test evidence is present; three-OS native evidence is incomplete |
| Power loss and abnormal termination | Eight process hard-exit seams pass | Blocked: physical abrupt-power runs are 0 of the required 100 per evidence record |
| Windows, macOS, and Linux qualification | CI host-contract matrix and observation tool implemented | Blocked: the three native runtime rows are not qualified |
| Solver release | Fail-closed gate implemented | Blocked: no approved solver license record, immutable image digest, SBOM, or numerical baseline |

The authoritative status is [the M3 gate manifest](../../validation/manifests/m3-entry-gates.json). Its evidence hashes are checked by npm run check:m3. The manifest grants no runtime authority while productEnabled is false.

## Verification

    npm run check:m3
    python -m unittest backend.tests.product.test_gates backend.tests.runtime.test_oci_backend backend.tests.service.test_credentials backend.tests.service.test_anti_rollback backend.tests.service.test_worker_scheduler backend.tests.service.test_local_api backend.tests.service.test_application
    python tools/qualify-runtime.py --output validation/evidence/m3/runtime-host-local.json

The qualification command returns a nonzero blocked result until the runtime, approved image, contract suite, and native conformance evidence are all available. Its output is an observation, not an approval.

## Activation rule

Activation requires all eight gates to carry reviewed, hash-bound evidence; Docker and Podman grants for exact image and entrypoint tuples; and global approval metadata. A missing file, changed hash, duplicate JSON key, partial approval, or disabled product marker prevents token creation before any runtime socket is contacted.

Physical power-loss evidence must follow the [external power-loss runbook](../../validation/power-loss/README.md). Process exit, VM reset, and an ordinary operating-system shutdown do not satisfy that gate.
