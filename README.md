# OpenTCAD

[한국어](README.ko.md) · [Live static preview](https://jtech-co.github.io/OpenTCAD/) · [Architecture](docs/en/architecture.md) · [Roadmap](docs/en/roadmap.md)

OpenTCAD is an open-source, bilingual workspace for learning semiconductor process and device simulation. The product direction combines a sandboxed SUPREM-IV.GS process flow with DEVSIM device analysis and makes the experience reproducible from a local server on Windows, macOS, and Linux.

> OpenTCAD is for education, structure exploration, and numerical experiments. It is not a fabrication sign-off tool.

## What is available now

This repository is at the **project foundation milestone**. It includes:

- a responsive English/Korean React workspace;
- a deterministic, clearly labelled reference workflow for process profiles, device cross-sections, and I–V curves;
- a static GitHub Pages build that never executes submitted input;
- local development and preview servers that work anywhere Node.js runs;
- CI, accessibility-oriented interaction states, and the architecture boundary for the future sandboxed local engine;
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

No solver output or numerical baseline is changed by this foundation milestone. All visible curves are deterministic reference-preview data and are marked as such in the interface.

## Documentation

| English | 한국어 |
|---|---|
| [Architecture](docs/en/architecture.md) | [아키텍처](docs/ko/architecture.md) |
| [Development](docs/en/development.md) | [개발](docs/ko/development.md) |
| [Licensing](docs/en/licensing.md) | [라이선스](docs/ko/licensing.md) |
| [Implementation scope and comparison](docs/en/implementation-scope.md) | [구현 범위와 기존 사이트 비교](docs/ko/implementation-scope.md) |
| [M0 discovery and baseline status](docs/en/m0/README.md) | [M0 조사 및 기준선 상태](docs/ko/m0/README.md) |
| [Roadmap](docs/en/roadmap.md) | [로드맵](docs/ko/roadmap.md) |
| [Foundation work report](docs/en/project-foundation.md) | [기반 작업 보고서](docs/ko/project-foundation.md) |

The detailed Korean planning sources remain at the repository root: `01_PRODUCT_TECHNICAL_PLAN_KR.md`, `02_CODEX_HARNESS_KR.md`, `03_MILESTONE_ROADMAP_KR.md`, and `04_INITIAL_BACKLOG_KR.md`.

## License boundary

Original OpenTCAD application code and new documentation are released under the [MIT License](LICENSE). That does **not** relicense SUPREM-IV.GS, Gmsh, DEVSIM, their examples, or any upstream code. No third-party solver source or binary is included in this foundation release. See [Licensing](docs/en/licensing.md), the [third-party inventory](THIRD_PARTY_LICENSES.md), and [NOTICE](NOTICE).

Copyright ⓒ 2026 JTech-CO.
