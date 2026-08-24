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
- a runtime-neutral `RuntimeBackend` contract, fail-closed policy validator, canonical input/output archives, phase-addressable cancellation, process-local idempotent cleanup, a CAS durable-state interface, redacted public events, and strict in-memory test doubles that invoke no runtime or solver;
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

This repository stores no solver output or numerical baseline. The external [BASE-001 observation harness](docs/en/m0/base001-reference-observation.md) writes raw evidence outside OpenTCAD and cannot update a baseline. The engine-independent [fault-path supervisor](docs/en/m0/fault-path-foundation.md) tests timeout, cancellation, combined-output limits, and worker replacement. A separate non-promoting [OCI fault matrix](docs/en/m0/oci-fault-matrix.md) observed the same controls on Docker Desktop and WSL2 rootless Podman with 20-case mixed loops and zero labelled orphans. It uses a fixed non-solver image and does not qualify a product adapter, solver, release image, or host. The gated [M2 runtime and mock broker foundation](docs/en/m2/README.md) now freezes typed lifecycle, capability, error, policy, canonical input/output archives, eleven cancellation checkpoints, redaction, concurrent idempotent mock cleanup, reconciliation, and a non-durable CAS state-store contract without a broker service, durable database, product adapter, runtime detection, worker integration, or socket access. All visible curves remain deterministic reference-preview data and are marked as such in the interface.

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
| [Roadmap](docs/en/roadmap.md) | [로드맵](docs/ko/roadmap.md) |
| [Foundation work report](docs/en/project-foundation.md) | [기반 작업 보고서](docs/ko/project-foundation.md) |

The detailed Korean planning sources remain at the repository root: `01_PRODUCT_TECHNICAL_PLAN_KR.md`, `02_CODEX_HARNESS_KR.md`, `03_MILESTONE_ROADMAP_KR.md`, and `04_INITIAL_BACKLOG_KR.md`.

## License boundary

Original OpenTCAD application code and new documentation are released under the [MIT License](LICENSE). That does **not** relicense SUPREM-IV.GS, Gmsh, DEVSIM, their examples, or any upstream code. No third-party solver source or binary is included in this foundation release. See [Licensing](docs/en/licensing.md), the [third-party inventory](THIRD_PARTY_LICENSES.md), and [NOTICE](NOTICE).

Copyright ⓒ 2026 JTech-CO.
