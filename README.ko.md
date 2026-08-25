# OpenTCAD

[English](README.md) · [정적 미리보기](https://jtech-co.github.io/OpenTCAD/) · [아키텍처](docs/ko/architecture.md) · [로드맵](docs/ko/roadmap.md)

OpenTCAD은 반도체 공정과 소자 시뮬레이션을 학습하기 위한 오픈 소스 한·영 지원 작업공간입니다. 제품 방향은 격리된 SUPREM-IV.GS 공정 흐름과 DEVSIM 소자 해석을 결합하고, Windows·macOS·Linux의 로컬 서버에서 같은 경험을 재현하는 것입니다.

> OpenTCAD은 교육·구조 이해·수치 실험용이며 반도체 제조 공정의 sign-off 도구가 아닙니다.

## 현재 제공 범위

프로젝트 기반은 완료됐고 **M0는 진행 중**이며 엔진 독립 M1 및 M2 계약 작업은 `gated-active` 상태입니다. 현재 저장소는 다음을 포함합니다.

- 반응형 영어/한국어 React 작업공간
- 공정 프로파일, 소자 단면, I–V 곡선을 보여 주는 결정론적 참조 워크플로
- 제출된 입력을 절대 실행하지 않는 GitHub Pages 정적 빌드
- Node.js가 동작하는 모든 OS에서 사용할 수 있는 로컬 개발·미리보기 서버
- CI, 접근성 중심 상호작용 상태, 향후 샌드박스 로컬 엔진을 위한 아키텍처 경계
- 제품 runtime이나 solver를 호출하지 않는 런타임 중립 `RuntimeBackend` 계약, 실패 폐쇄 policy validator, canonical input/output archive, phase 지정 cancellation, process-local idempotent cleanup, 결정론적 broker-event mapping, 재사용 가능한 state-adapter conformance suite, CAS durable-state interface, schema v1 migration과 별도 process hard-exit recovery를 검증한 file-backed SQLite schema-v2 후보, startup recovery, 부분 write cleanup, durable external cancellation intent, CAS 단일 승자 중재, cancellation crash checkpoint 5곳, 단조 증가 fencing token을 사용하는 durable owner generation을 갖춘 비활성 mock 전용 phase-time durable composition, redacted 공개 event, 엄격한 test double
- OpenTCAD 고유 코드의 MIT 라이선스와 제3자 시뮬레이터의 분리된 라이선스 경계

정적 사이트는 제품 미리보기이며 브라우저 기반 솔버가 아닙니다. 실제 SUPREM-IV.GS와 DEVSIM 잡은 향후 로컬 API → 워커 → 샌드박스 브로커 → OCI 런타임 경로에서만 실행합니다. 브라우저에는 Docker/Podman 소켓을 절대 노출하지 않습니다.

## 현재 앱 실행

요구사항은 Node.js 22 LTS 또는 24 LTS와 npm 10 이상입니다.

```bash
npm install
npm run dev
```

Vite가 출력한 loopback 주소를 엽니다. 배포용 정적 빌드는 다음과 같습니다.

```bash
npm run build
npm run preview
```

미리보기 서버는 `127.0.0.1`에만 바인딩됩니다. 빌드 결과는 `frontend/dist/`에 생성되며 상대 자산 경로를 사용하므로 GitHub Pages와 일반 정적 서버에서 같은 번들을 실행할 수 있습니다.

## 품질 게이트

```bash
npm run check
npm run coverage
```

이 저장소는 솔버 출력이나 수치 기준선을 저장하지 않습니다. 외부 [BASE-001 관찰 하네스](docs/ko/m0/base001-reference-observation.md)는 원본 증거를 OpenTCAD 밖에 쓰며 기준선을 갱신할 수 없습니다. 엔진 독립 [장애 경로 supervisor](docs/ko/m0/fault-path-foundation.md)는 timeout, 취소, 합산 출력 제한, worker 교체를 검사합니다. 별도의 비승격 [OCI 장애 행렬](docs/ko/m0/oci-fault-matrix.md)은 Docker Desktop과 WSL2 rootless Podman에서 같은 통제를 관찰했고 20회 혼합 반복 뒤 label orphan이 0임을 확인했습니다. 이 관찰은 고정 비솔버 image를 사용하며 제품 adapter, solver, release image 또는 host를 검증하지 않습니다. Gate 상태의 [M2 런타임 및 mock broker 기반](docs/ko/m2/README.md)은 typed lifecycle, capability, error, policy, canonical input/output archive, execution cancellation checkpoint 11곳, redaction, concurrent idempotent mock cleanup, reconciliation, 결정론적 event-to-state mapping, 재사용 가능한 adapter conformance suite, transaction, schema, retention, 별도 process hard-exit recovery 계약을 갖춘 file-backed SQLite durable-state 후보를 고정했습니다. 명시적인 mock 전용 composition은 execution과 외부 cancellation phase event를 저장하고, runtime query 전에 cancellation intent를 commit하며, 경쟁 operation ID를 CAS로 중재하고, restart 때 commit된 intent를 cancelled로 닫습니다. Store가 강제하는 owner generation은 검사된 broker 경계에서 stale execution, cancellation, recovery 시도를 fence 처리합니다. 이 협력형 경로는 제품 비활성 상태이며 ownership 검사와 runtime 호출을 원자화하지 않습니다. 제품 adapter, runtime 강제형 fencing, owner liveness 및 lease expiry, runtime detection, worker integration, runtime socket, solver 실행은 계속 비활성입니다. 화면의 모든 곡선은 결정론적 참조 미리보기 데이터이며 UI에서 이를 명확히 표시합니다.

## 문서

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
| [Roadmap](docs/en/roadmap.md) | [로드맵](docs/ko/roadmap.md) |
| [Foundation work report](docs/en/project-foundation.md) | [기반 작업 보고서](docs/ko/project-foundation.md) |

상세 한국어 기획 원문은 저장소 루트의 `01_PRODUCT_TECHNICAL_PLAN_KR.md`, `02_CODEX_HARNESS_KR.md`, `03_MILESTONE_ROADMAP_KR.md`, `04_INITIAL_BACKLOG_KR.md`에 유지합니다.

## 라이선스 경계

OpenTCAD 고유 애플리케이션 코드와 새 문서는 [MIT 라이선스](LICENSE)로 배포합니다. 이 라이선스는 SUPREM-IV.GS, Gmsh, DEVSIM, 각 예제 또는 업스트림 코드를 MIT로 다시 허가하지 않습니다. 이번 기반 릴리스에는 제3자 솔버 소스나 바이너리를 포함하지 않습니다. 자세한 내용은 [라이선스 문서](docs/ko/licensing.md), [제3자 목록](THIRD_PARTY_LICENSES.md), [NOTICE](NOTICE)를 확인하십시오.

Copyright ⓒ 2026 JTech-CO.
