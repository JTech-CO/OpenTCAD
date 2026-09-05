# M3 product entry gates

[한국어](../ko/m3-entry-gates.md)

OpenTCAD now contains the product connection layer for a local service, but product activation remains disabled. Code completion does not substitute for runtime, license, numerical, platform, or physical power-loss evidence.

## Implemented product path

- Docker and Podman OCI adapters use shell-free bounded subprocess transport.
- Workload wait and log streaming run concurrently. Timeout and output overflow
  trigger a fenced native kill. Archive helpers keep stdin open for import and
  have a bounded transfer timeout independent of short workload timeouts.
- Preloaded images are verified locally against the approved index digest and
  platform without registry manifest requests. Docker and Podman command and
  version-response differences are covered explicitly.
- Every runtime object carries the exact job ID, owner ID, and fencing
  generation. Product operations hold a job-specific cross-process lock across
  durable authority verification and native mutation, verify native labels
  before mutation, and verify labels immediately after object creation.
- Restart cancellation recovers its bounded output contract from native
  labels. Missing or malformed recovery labels fence the request before kill.
- Runtime authority is an exact grant over backend, immutable image identity, and configured entrypoint. Approved lists are not combined as a Cartesian product.
- The API binds only to a numeric loopback address and validates the peer, Host, Origin, bearer secret, request size, JSON shape, and duplicate keys.
- A bounded execution lane and a separate control lane allow cancellation while a solver job is running.
- Startup recovery completes before API admission. Execution, cancellation, maintenance, authenticated export/import, scheduled backup, and shutdown share one lifecycle assembly.
- Windows Credential Manager, macOS Keychain, and Linux Secret Service adapters keep API and HMAC secrets outside application backups.
- A second monotonic restore floor is stored in the OS credential service and advances before an import.
- The executable `doctor`, blocked `preview`, and product `serve` commands use
  strict per-user paths, one instance lock, code-owned release profiles, and a
  same-origin static UI. The committed profile set is intentionally empty.

## Implementation map

| Path | Responsibility |
|---|---|
| `backend/app/product/gates.py` | Exact, evidence-hash-bound product activation and runtime grants |
| `backend/app/product/release_profile.py` | Code-owned backend, image, entrypoint, policy, and manifest-digest binding |
| `backend/app/runtime/oci_backend.py` | Docker and Podman command transport, hardening, image identity, and native object fencing |
| `backend/app/runtime/product_fence_authority.py` | Cross-process linearization of durable takeover and native mutation |
| `backend/app/service/product_composition.py` | M3-only bridge that preserves the frozen M2 composition and requires a matching activation token |
| `backend/app/service/worker.py` | Typed lifecycle queue, reserved cancellation lane, admission heartbeat, and offline import arbitration |
| `backend/app/service/local_api.py` | Authenticated loopback HTTP boundary and strict request codecs |
| `backend/app/service/credentials.py` | Windows, macOS, and Linux credential adapters |
| `backend/app/service/anti_rollback.py` | OS-protected monotonic restore floor |
| `backend/app/service/scheduler.py` | Restart-safe scheduled backup wake-up loop and retained failure state |
| `backend/app/service/application.py` | Recovery-first product service assembly and shutdown ordering |
| `backend/app/service/bootstrap.py` | Side-effect-free activation check and activated product composition |
| `backend/app/service/cli.py` | Cross-platform doctor, blocked preview, and product serve commands |
| `backend/app/service/static_assets.py` | Bounded same-origin static asset serving |
| `backend/app/service/status.py` | Versioned and redacted browser status contract |
| `tools/qualify-runtime.py` | Non-promoting host observation tool |
| `tools/observe-m3-native-adapter.py` | Seven real product-adapter scenarios with exact cleanup and external evidence |
| `tools/check-m3-promotion.mjs` | Atomic, revision-bound readiness check for all eight gates and six OS/runtime rows |
| `tools/check-m3-solver-release.mjs` | Rights, image, SBOM, provenance, and numerical corpus evidence validation |
| `tools/check-m3-power-loss.mjs` | Independently reviewed physical power-cut ledger validation |

## Gate status

| Gate | Implementation | Qualification or approval |
|---|---|---|
| Docker and Podman adapters | Implemented and fake-CLI tested | Blocked: no approved native three-platform evidence in the manifest |
| Native fencing | Implemented and tamper/stale-owner tested; native observer available | Blocked: reviewed platform qualification is incomplete |
| Local API and worker transport | Implemented, bounded, and loopback-socket tested | Blocked: product manifest and release profile disabled |
| Lifecycle integration | Implemented and SQLite assembly tested | Blocked: product manifest and release profile disabled |
| OS credentials and scheduled backup | Three host adapters, scheduler, and opt-in native cross-process tests implemented | Blocked: three-OS reviewed native evidence is incomplete |
| Power loss and abnormal termination | Eight process hard-exit seams pass | Blocked: physical abrupt-power runs are 0 of the required 100 per evidence record |
| Windows, macOS, and Linux qualification | CI host-contract matrix and manual self-hosted observation workflow implemented | Blocked: the six OS/runtime rows are not qualified |
| Solver release | Fail-closed gate implemented | Blocked: no approved solver license record, immutable image digest, SBOM, or numerical baseline |

The authoritative status is [the M3 gate manifest](../../validation/manifests/m3-entry-gates.json). Its evidence hashes are checked by npm run check:m3. The manifest grants no runtime authority while productEnabled is false.

## Verification

    npm run check:m3
    python -m unittest backend.tests.product.test_gates backend.tests.runtime.test_oci_backend backend.tests.service.test_credentials backend.tests.service.test_anti_rollback backend.tests.service.test_worker_scheduler backend.tests.service.test_local_api backend.tests.service.test_application backend.tests.service.test_local_product_bootstrap
    npm run local:doctor
    python tools/qualify-runtime.py --output validation/evidence/m3/runtime-host-local.json

The qualification command returns a nonzero blocked result until the runtime, approved image, contract suite, and native conformance evidence are all available. Its output is an observation, not an approval.

The [native adapter runbook](m3-native-adapter-conformance.md) exercises canonical
archive transfer, nonzero exit, cancellation, timeout, streaming output limits,
stale fencing, and concurrent cleanup against an engine-free fixture. Results
stay outside the repository. Follow the [promotion readiness contract](m3-promotion-readiness.md)
and [solver release contract](m3-solver-release-qualification.md) when preparing
reviewed evidence. Their fixture tests are included in `npm run check`.

## Activation rule

The [native credential suite](m3-native-credentials.md) tests the actual product
provider across fresh processes, including restore-floor rollback rejection.
Its explicit opt-in prevents routine tests from silently accessing OS stores.

Activation requires all eight gates to carry reviewed, hash-bound evidence; Docker and Podman grants for exact image and entrypoint tuples; and global approval metadata. A missing file, changed hash, duplicate JSON key, partial approval, or disabled product marker prevents token creation before any runtime socket is contacted.

Physical power-loss evidence must follow the [external power-loss runbook](../../validation/power-loss/README.md). Process exit, VM reset, and an ordinary operating-system shutdown do not satisfy that gate.
