# OpenTCAD

[한국어](README.ko.md) · [Live static preview](https://jtech-co.github.io/OpenTCAD/) · [Architecture](docs/en/architecture.md) · [Roadmap](docs/en/roadmap.md)

OpenTCAD is an open-source, bilingual workspace for learning semiconductor process and device simulation. The product direction combines a sandboxed SUPREM-IV.GS process flow with DEVSIM device analysis and makes the experience reproducible from a local server on Windows, macOS, and Linux.

> OpenTCAD is for education, structure exploration, and numerical experiments. It is not a fabrication sign-off tool.

## What is available now

The project foundation is complete, **M0 is active**, and engine-independent M1 and M2 contract work is `gated-active`. The repository currently includes:

- a responsive English/Korean React workspace;
- a deterministic, clearly labelled reference workflow for process profiles, device cross-sections, and I–V curves;
- a static GitHub Pages build that never executes submitted input;
- local development and preview servers that work anywhere Node.js runs;
- CI, accessibility-oriented interaction states, and the architecture boundary for the future sandboxed local engine;
- a runtime-neutral `RuntimeBackend` contract, fail-closed policy validator, canonical input/output archives, phase-addressable cancellation, process-local idempotent cleanup, deterministic broker-event mapping, a reusable state-adapter conformance suite, a reusable native-object runtime-fence conformance suite, a CAS durable-state interface, a file-backed SQLite schema-v3 candidate with transactional version-1 and version-2 migration, revision-neutral owner leases, and separate-process hard-exit recovery proof, an inactive mock-only phase-time durable composition with startup recovery, partial-write cleanup, durable external cancellation intent, CAS single-winner arbitration, five cancellation crash checkpoints, heartbeat-based liveness, durable owner generations with monotonically increasing fencing tokens, redacted public events, and a strict token-enforcing mock runtime that invokes no product runtime or solver;
- MIT licensing for original OpenTCAD code, with third-party simulators kept outside that license boundary.

The static site is a product preview, not a browser-based solver. Real SUPREM-IV.GS and DEVSIM jobs will run only through the planned local API → worker → sandbox broker → OCI runtime path. The browser will never receive a Docker or Podman socket.

## Run the current app

Requirements: Node.js 22 LTS or 24 LTS and npm 10 or newer.

```bash
npm install
npm run dev
```

Open the loopback URL printed by Vite. For the production-static build:

```bash
npm run build
npm run preview
```

The preview server binds to `127.0.0.1`. The build output is `frontend/dist/` and uses relative asset paths so the same bundle works on GitHub Pages and ordinary static servers.

## Quality gates

```bash
npm run check
npm run coverage
```

This repository stores no solver output or numerical baseline. The external [BASE-001 observation harness](docs/en/m0/base001-reference-observation.md) writes raw evidence outside OpenTCAD and cannot update a baseline. The engine-independent [fault-path supervisor](docs/en/m0/fault-path-foundation.md) tests timeout, cancellation, combined-output limits, and worker replacement. A separate non-promoting [OCI fault matrix](docs/en/m0/oci-fault-matrix.md) observed the same controls on Docker Desktop and WSL2 rootless Podman with 20-case mixed loops and zero labelled orphans. It uses a fixed non-solver image and does not qualify a product adapter, solver, release image, or host. The gated [M2 runtime and mock broker foundation](docs/en/m2/README.md) now freezes typed lifecycle, capability, error, policy, canonical input/output archives, eleven execution cancellation checkpoints, redaction, concurrent idempotent mock cleanup, reconciliation, deterministic event-to-state mapping, a reusable adapter conformance suite, and a file-backed SQLite durable-state candidate with transaction, schema, retention, and separate-process hard-exit recovery contracts. An explicit mock-only composition persists execution and external-cancellation phase events, commits cancellation intent before runtime query, arbitrates competing operation IDs with CAS, and closes committed intent as cancelled on restart. Durable owner leases and heartbeats now prevent recovery from taking over a live owner, allow cancellation to preempt it, and fence expired execution, cancellation, and recovery attempts. Every guarded job lifecycle call carries the exact job, owner, and token into a strict bound mock runtime, which rejects lower tokens, ambiguous same-token owners, and cross-job handles. A shared process-local reference authority activates before and verifies after every bound call; managed mock objects persist exact job, owner, and token labels, and takeover can only query, kill, or clean predecessor objects. Five common adapter cases and three focused authority, parser, and post-mutation cases verify this boundary. This path remains product-disabled and does not make the store commit and runtime token activation atomic. Product Docker and Podman token persistence and enforcement, native in-flight call revocation, runtime detection, worker integration, runtime sockets, multi-host coordination, and solver execution remain disabled. All visible curves remain deterministic reference-preview data and are marked as such in the interface.

## Documentation

| English | 한국어 |
|---|---|
| [Architecture](docs/en/architecture.md) | [아키텍처](docs/ko/architecture.md) |
| [Development](docs/en/development.md) | [개발](docs/ko/development.md) |
| [Licensing](docs/en/licensing.md) | [라이선스](docs/ko/licensing.md) |
| [Implementation scope and comparison](docs/en/implementation-scope.md) | [구현 범위와 기존 사이트 비교](docs/ko/implementation-scope.md) |
| [M0 discovery and baseline status](docs/en/m0/README.md) | [M0 조사 및 기준선 상태](docs/ko/m0/README.md) |
| [BASE-001 reference observation](docs/en/m0/base001-reference-observation.md) | [BASE-001 참조 관찰](docs/ko/m0/base001-reference-observation.md) |
| [M0 fault-path contract](docs/en/m0/fault-path-foundation.md) | [M0 장애 경로 계약](docs/ko/m0/fault-path-foundation.md) |
| [M0 OCI fault matrix](docs/en/m0/oci-fault-matrix.md) | [M0 OCI 장애 행렬](docs/ko/m0/oci-fault-matrix.md) |
| [M1 reproducibility and validation status](docs/en/m1/README.md) | [M1 재현성 및 검증 상태](docs/ko/m1/README.md) |
| [M2 runtime contract foundation](docs/en/m2/README.md) | [M2 런타임 계약 기반](docs/ko/m2/README.md) |
| [M2 lifecycle, cleanup, and state contract](docs/en/m2/lifecycle-cleanup-state.md) | [M2 lifecycle, cleanup, state 계약](docs/ko/m2/lifecycle-cleanup-state.md) |
| [M2 event mapping, adapter conformance, and restart recovery](docs/en/m2/event-state-recovery.md) | [M2 event mapping, adapter conformance, restart recovery](docs/ko/m2/event-state-recovery.md) |
| [M2 SQLite durable-state candidate](docs/en/m2/sqlite-durable-state.md) | [M2 SQLite durable-state 후보](docs/ko/m2/sqlite-durable-state.md) |
| [M2 inactive live-state composition](docs/en/m2/live-state-composition.md) | [M2 비활성 live-state composition](docs/ko/m2/live-state-composition.md) |
| [M2 durable external cancellation arbitration](docs/en/m2/durable-cancellation-arbitration.md) | [M2 durable external cancellation 중재](docs/ko/m2/durable-cancellation-arbitration.md) |
| [M2 durable operation ownership and fencing](docs/en/m2/durable-operation-ownership.md) | [M2 durable operation ownership 및 fencing](docs/ko/m2/durable-operation-ownership.md) |
| [M2 owner lease and runtime fencing](docs/en/m2/owner-lease-runtime-fencing.md) | [M2 owner lease 및 runtime fencing](docs/ko/m2/owner-lease-runtime-fencing.md) |
| [M2 native-object runtime fencing conformance](docs/en/m2/native-runtime-fence-conformance.md) | [M2 native object runtime fencing conformance](docs/ko/m2/native-runtime-fence-conformance.md) |
| [Roadmap](docs/en/roadmap.md) | [로드맵](docs/ko/roadmap.md) |
| [Foundation work report](docs/en/project-foundation.md) | [기반 작업 보고서](docs/ko/project-foundation.md) |

The detailed Korean planning sources remain at the repository root: `01_PRODUCT_TECHNICAL_PLAN_KR.md`, `02_CODEX_HARNESS_KR.md`, `03_MILESTONE_ROADMAP_KR.md`, and `04_INITIAL_BACKLOG_KR.md`.

## License boundary

Original OpenTCAD application code and new documentation are released under the [MIT License](LICENSE). That does **not** relicense SUPREM-IV.GS, Gmsh, DEVSIM, their examples, or any upstream code. No third-party solver source or binary is included in this foundation release. See [Licensing](docs/en/licensing.md), the [third-party inventory](THIRD_PARTY_LICENSES.md), and [NOTICE](NOTICE).

Copyright ⓒ 2026 JTech-CO.
