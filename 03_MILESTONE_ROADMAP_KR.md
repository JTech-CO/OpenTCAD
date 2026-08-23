# TCAD Webapp Cross-Platform Porting - Milestone Roadmap

> **계획 기준:** 1명 전담 엔지니어 + 수치/라이선스 검토 지원  
> **예상 기간:** 순차 24–30주, 일부 병렬화 시 20–26주  
> **기준선:** 2026-08-23 현재 upstream `master`  
> **원칙:** 포팅, 수치 기준선, 보안 경계를 단계적으로 분리한다.

---

## 1. 전체 로드맵

| Milestone | 기간 | 핵심 결과 | 릴리스 상태 |
|---|---:|---|---|
| M0 | 1–2주 | 라이선스·현행 구조·플랫폼·수치 기준선과 Go/No-Go 결정 | Planning Baseline |
| M1 | 2–3주 | 골든 코퍼스, comparator, CI 기초, reproducible image lock | Validation Foundation |
| M2 | 4–5주 | Runtime abstraction, Docker/Podman adapters, Sandbox Broker | Runtime Alpha |
| M3 | 3–4주 | All-in-one Compose, local mode, launcher, doctor, managed job volumes | Local Alpha |
| M4 | 2–3주 | Windows 11 x64 정식 qualification | Windows Beta |
| M5 | 3–5주 | macOS Intel/Apple Silicon, multi-arch/native-vs-emulated 결정 | Cross-platform Beta |
| M6 | 3–4주 | P0/P1 correctness·수치·데이터·UX 결함 burn-down | Feature Complete |
| M7 | 3–4주 | `.tcadproj`, provenance, diagnostics, engine capability registry | RC Candidate |
| M8 | 2–3주 | 보안·라이선스·SBOM·업데이트·백업·문서·릴리스 hardening | 1.0 GA |

M4의 Windows 작업과 M5의 일부 이미지 빌드 연구는 M3 후반부터 병렬화할 수 있다. M7의 export schema 설계는 M1부터 시작할 수 있으나 구현은 런타임·manifest가 안정된 뒤 진행한다.

---

## 2. 공통 운영 규칙

### 2.1 각 Milestone 진입 조건

- 이전 milestone exit criteria 충족
- 열린 P0 없음
- 기준 branch green
- 문서와 실제 명령 일치
- 해당 단계의 위험·결정 owner 지정

### 2.2 각 Milestone 종료 조건

- 산출물 commit/PR 연결
- 자동 테스트와 수동 qualification evidence 저장
- 수치·보안·데이터 영향 보고
- 남은 issue가 다음 milestone로 명시적으로 이동
- rollback 또는 feature flag 확보
- README/Code map/Harness 갱신

### 2.3 Release branch 정책

- `main` 또는 fork default는 항상 배포 가능 상태 유지
- milestone 통합 branch를 장기간 유지하지 않음
- alpha/beta/RC tag는 signed annotated tag 권고
- image는 tag뿐 아니라 digest로 release manifest에 기록

---

# M0 - Discovery, Licensing, Baseline Freeze

**기간:** 1–2주  
**목표:** 구현 전에 배포 가능 범위, 현행 동작, 수치 기준, 포팅 경계를 확정한다.

## 진입 조건

- upstream clone 및 전체 history 접근
- Linux x86-64에서 현행 local run 가능
- 최소 한 명의 maintainer가 제품 범위 검토 가능

## 작업

### M0.1 저장소·의존성 inventory

- top-level, backend, frontend, Docker, deploy, SUPREM upstream/patches 맵 작성
- Python/Node/container/base image dependency lock 수집
- DB schema·volume·artifact 수명 정리
- 현재 테스트 종류와 실행 시간 기록
- `.github` 부재 및 CI gap 기록

### M0.2 라이선스 gate

- root license 부재 확인
- SUPREM upstream license 원문과 patch license 확인
- DEVSIM Apache-2.0 LICENSE/NOTICE 확인
- Gmsh GPL 의무와 별도 프로세스/이미지 배포 검토
- Docker Desktop은 번들 대상이 아님을 확정
- Option A/B/C 중 release 정책 선택

### M0.3 현행 실행 기준선

- Linux rootless Podman에서 fresh install 재현
- bundled examples 공정 실행
- NMOS DEVSIM Id–Vg/Id–Vd 실행
- run duration, artifact size, node/element counts, key metrics 수집
- cancellation, timeout, output limit, worker restart 관찰

### M0.4 플랫폼 spike

- Windows Docker Desktop에서 기존 Compose/이미지의 실패 지점만 기록
- macOS Apple Silicon에서 `linux/amd64` image build/run 가능 여부 기록
- Podman Machine에서 `--userns keep-id`, bind mount, pause 관련 차이 기록
- native arm64 SUPREM build는 compile-only spike까지 허용

## 산출물

- `BASELINE_REPORT.md`
- `LICENSE_STRATEGY.md`
- `DEPENDENCY_AND_IMAGE_INVENTORY.json`
- `CURRENT_ARCHITECTURE.md`
- `PORTABILITY_SPIKE_REPORT.md`
- initial golden metric JSON
- 승인 ADR-001~ADR-007

## Exit criteria

- 라이선스 전략이 결정되거나 release가 명시적으로 blocked
- 현행 Linux 전체 test green
- 기준 example 3종 이상 결과·이미지 digest 고정
- Windows/macOS의 주요 blocker가 재현됨
- 1.0 지원 행렬 확정

## Go/No-Go

**No-Go:** SUPREM을 포함한 배포 권한을 확정할 수 없고 optional component 방식도 채택하지 않음.  
**Go:** mixed/optional/permission 중 하나를 문서로 승인.

---

# M1 - Reproducibility and Numerical Validation Foundation

**기간:** 2–3주  
**목표:** 포팅 전후 결과를 객관적으로 비교할 수 있는 자동 검증 체계를 만든다.

## 진입 조건

- M0 기준 이미지·commit·예제 metric 고정
- 라이선스 전략 최소한 source development 범위 승인

## 작업

### M1.1 골든 코퍼스

- 1D boron, oxidation, implant
- 2D NMOS, CMOS mask/interface
- `.str` parser fixture
- Gmsh remesh fixture
- DEVSIM diode, NMOS Id–Vg/Id–Vd, CMOS load line
- 각 fixture의 source, expected topology, scalar metric, warning policy

### M1.2 Comparator

- exact hash comparator
- topology comparator
- geometry/field scalar comparator
- I–V curve comparator
- repeated-run variance report
- HTML/JSON validation report

### M1.3 Reproducible images

- base image digest pinning
- build argument/architecture 기록
- SUPREM patchset hash
- DEVSIM/Gmsh version lock
- image labels와 OCI metadata

### M1.4 CI foundation

- `.github/workflows/pr.yml`
- backend/frontend lint/unit
- Linux integration
- image build smoke
- numerical subset gate
- artifact retention

## 산출물

- `validation/corpus/`
- `validation/comparators/`
- `validation/manifests/baseline-*`
- numerical report template
- CI workflows
- image lock manifest

## Exit criteria

- 코퍼스 모든 case가 현행 Linux 기준선에서 green
- 같은 이미지 5회 반복 분산 측정 완료
- 의도적으로 topology/curve를 바꾸면 CI가 실패함을 확인
- baseline 자동 갱신 경로 없음
- PR에서 최소 numerical smoke 실행

## 핵심 위험

- 기존 결과 자체가 잘못된 case가 발견될 수 있음. 이 경우 baseline을 바로 고정하지 않고 P0 correctness issue로 분리한다.

---

# M2 - Runtime Abstraction and Sandbox Broker

**기간:** 4–5주  
**목표:** Podman 결합을 제거하고 Docker/Podman에서 같은 보안·수명주기 계약을 실행한다.

## 진입 조건

- M1 corpus green
- runtime interface ADR 승인
- Broker threat model 승인

## 작업

### M2.1 Characterization

- 기존 `sandbox.py` argv snapshot과 실제 inspect
- run/kill/timeout/output-limit/repair 흐름 test
- worker state transition test
- current Podman behavior를 adapter contract로 캡처

### M2.2 Runtime protocol

- health/capability/image/volume/container/artifact/error 모델
- stable error taxonomy
- mock backend
- runtime auto-detect 우선순위와 명시 override

### M2.3 Podman adapter

- 기존 동작을 adapter로 이동
- rootless pause/systemd 복구를 Podman 내부로 격리
- Linux regression 유지
- Podman Machine capability 차이 처리

### M2.4 Docker adapter

- Docker Engine/Desktop 지원
- security option mapping
- CPU/memory/PID/timeout/kill
- label/orphan query
- image digest inspect

### M2.5 Sandbox Broker

- typed request allowlist
- managed job volume create/tar-in/run/tar-out/remove
- engine socket 단독 보유
- crash/restart cleanup
- redacted event log

### M2.6 Worker integration

- worker는 broker contract만 호출
- API cancel→DB state→broker kill 순서
- remesh와 DEVSIM이 동일 job identity 사용
- retry policy를 infra vs solver로 분리

## 산출물

- `backend/app/runtime/*`
- `backend/app/broker/*`
- Docker/Podman contract test
- sandbox threat-model test report
- fault injection suite
- code maps update

## Exit criteria

- Linux Podman에서 기존 corpus 100% green
- Linux Docker에서 동일 corpus green
- policy inspect가 두 backend에서 필수 제약 확인
- runtime unavailable, stale state, kill, timeout, output bomb 분류 일치
- worker/API에 raw engine socket 없음
- 20회 success/fail/cancel loop 후 orphan 0
- 기존 Podman server profile 회귀 없음

## Rollback

- feature flag `TCAD_RUNTIME_LAYER=legacy|broker`를 milestone 동안 유지
- M3 시작 전에 broker가 기본값으로 전환되고 legacy 제거 계획 확정

---

# M3 - Portable Local Stack, Launcher, Doctor

**기간:** 3–4주  
**목표:** host에 Python/Node/PostgreSQL/Redis를 직접 설치하지 않고 한 번에 로컬 서버를 실행한다.

## 진입 조건

- M2 Docker/Podman adapters green
- job managed volume 안정화

## 작업

### M3.1 Compose profiles

- web/API/worker/broker/PostgreSQL/Redis
- named persistent volumes
- healthcheck와 dependency ordering
- migration service
- local/shared/server config separation

### M3.2 Local mode

- loopback-only enforcement
- owner bootstrap 또는 one-time local token
- invite/seat UI 비활성
- secure random secret persistence
- local cookie defaults

### M3.3 Launcher

- PowerShell + shell entrypoint
- `doctor/up/status/down/backup/restore/update`
- runtime auto-detect
- image pull/build progress
- port conflict resolution
- browser open

### M3.4 Doctor

- runtime/VM/version/architecture
- CPU/RAM/disk recommendation
- required sandbox capabilities
- image platform/digest
- ports
- DB/Redis/worker/broker health
- stale objects
- platform-specific recovery text

### M3.5 Update/backup skeleton

- persistent volume inventory
- pre-update backup
- migration dry-run
- rollback metadata

## 산출물

- `packaging/compose/*`
- launcher scripts/module
- local mode config and UI
- doctor CLI/API/UI
- local install guide draft

## Exit criteria

- Linux fresh machine에서 runtime 외 host dependency 없이 `tcad up`
- 15분 내 UI 접근 목표 충족
- local mode 외부 bind가 fail closed
- NMOS 공정→DEVSIM→save→restart 후 결과 유지
- backup/restore smoke
- Docker와 Podman 모두 실행

## Release

- **Local Alpha 0.3**

---

# M4 - Windows 11 Qualification

**기간:** 2–3주  
**목표:** Windows 11 x64에서 설치·실행·업데이트·복구를 정식 지원한다.

## 진입 조건

- M3 Local Alpha
- Windows 11 x64 test host 또는 self-hosted runner

## 작업

### M4.1 Docker Desktop WSL2 primary

- fresh install prerequisite document
- PowerShell launcher encoding/path
- Docker Desktop stopped/restart/sleep fault
- VM memory/disk shortage
- Windows firewall/loopback
- port collision

### M4.2 File/data behavior

- named volume persistence
- backup export to Windows path
- Unicode/Korean project name
- case-insensitive collisions
- reserved names, long path, CRLF
- archive import/export

### M4.3 Podman Machine secondary

- machine init/start/stop doctor
- capability mapping
- volume transfer
- runtime recovery

### M4.4 Windows E2E

- fresh install
- first owner
- NMOS process/device
- cancel during SUPREM/remesh/DEVSIM
- runtime restart recovery
- backup/update/restore
- uninstall with and without data deletion

## 산출물

- Windows install/troubleshooting docs
- Windows self-hosted workflow or signed qualification report
- PowerShell tests
- platform issue fixes

## Exit criteria

- Docker Desktop path 전체 E2E green
- Podman Machine 핵심 workflow green 또는 명시적 preview 표시
- corpus 결과 승인 tolerance 내
- Windows-specific open P0/P1 0
- clean uninstall와 data preservation 확인

## Release

- **Windows Beta 0.5**

---

# M5 - macOS and Multi-Architecture Qualification

**기간:** 3–5주  
**목표:** macOS Intel/Apple Silicon을 지원하고 native arm64 또는 emulation 정책을 확정한다.

## 진입 조건

- M3 local stack 안정
- Apple Silicon test host
- M1 cross-architecture comparator 준비

## 작업

### M5.1 Image architecture inventory

- web/API/DB/Redis/Gmsh/DEVSIM/SUPREM별 platform
- multi-arch base image availability
- buildx/QEMU build pipeline
- image manifest와 digest

### M5.2 SUPREM arm64 spike

- compile and sanitizer
- pointer/int/PIE assumptions 검토
- patch별 portability audit
- bundled examples
- full corpus comparison
- performance and memory

### M5.3 Native vs emulated policy

- native arm64가 tolerance 통과: 정식 multi-arch
- 실패: SUPREM `linux/amd64` 고정 + emulation 표시
- mixed-platform Compose와 image pull 검증

### M5.4 macOS lifecycle

- Docker Desktop/Podman Machine
- file sharing/volume backup
- sleep/wake
- low disk/memory
- launcher/Gatekeeper guidance
- Intel regression

## 산출물

- architecture qualification report
- multi-arch build workflow
- arm64 patch set 또는 explicit emulation policy
- macOS install/troubleshooting docs
- performance table

## Exit criteria

- macOS Apple Silicon fresh install E2E green
- architecture 상태가 UI/manifest/export에 기록
- native 또는 emulated corpus가 승인 tolerance 내
- macOS Intel smoke green
- open P0/P1 0

## Release

- **Cross-platform Beta 0.7**

---

# M6 - Correctness, Numerical Stability, Data Safety Burn-down

**기간:** 3–4주  
**목표:** 포팅 중 드러난 결함과 기존 silent correctness·state·data 문제를 기능 추가 전에 제거한다.

## 진입 조건

- Windows/macOS/Linux beta evidence
- M1 corpus와 fault suite 안정

## 작업 묶음

### M6.1 P0 correctness

- interface/electrode stable identity and uniqueness
- parser topology invariants
- source order/artifact order
- unit registry
- stale response/job switching

### M6.2 Numerical

- adaptive ramp policy 명문화
- fallback tolerance provenance
- skipped point semantics
- remesh contact preservation
- NaN/Inf and partial result handling

### M6.3 Data

- partial editing state vs executable state
- optimistic revision/ETag
- saved result/artifact lifecycle
- migration/backup restore stress
- quota/cleanup consistency

### M6.4 UX and performance

- number/text intermediate state
- status/log separation
- large mesh rendering cache
- accessibility
- diagnostics action text

## 산출물

- P0/P1 issue closure reports
- expanded regression corpus
- data recovery test report
- UX consistency checklist

## Exit criteria

- P0/P1 0
- corpus + platform matrix green
- no known silent correctness defect
- 100 simulated mixed success/fail/cancel jobs without queue/storage inconsistency
- backup/restore from previous beta release

## Release

- **Feature Complete 0.8**

---

# M7 - Project Portability, Provenance, Diagnostics, Extension Contracts

**기간:** 3–4주  
**목표:** 결과를 다른 OS에서 재현하고 향후 엔진을 안전하게 추가할 수 있는 계약을 제공한다.

## 진입 조건

- M6 data model 안정
- image/provenance schema 안정

## 작업

### M7.1 `.tcadproj`

- manifest schema
- streaming export/import
- zip-slip/bomb/symlink defense
- source/conditions/results optional selection
- schema migration

### M7.2 Provenance

- app commit/version
- runtime backend/version/platform
- image digest
- SUPREM upstream + patchset
- DEVSIM/Gmsh version
- input hashes
- warnings/fallback/skipped points

### M7.3 Diagnostics

- job diagnostics endpoint
- redacted support bundle
- doctor fault classification
- UI copy/download

### M7.4 Engine capability registry

- Process/Mesh/Device/PostProcessor/Validator manifest
- current engines registered
- arbitrary plugin loading은 비활성
- schema compatibility test

## 산출물

- project schema and JSON Schema
- export/import APIs and UI
- diagnostics bundle
- engine manifests
- cross-OS reproduction report

## Exit criteria

- Windows export → macOS import → Linux replay 성공
- path/archive security suite green
- provenance 누락 0
- current engines가 registry를 통해 실행
- 기존 프로젝트 migration green

## Release

- **RC Candidate 0.9**

---

# M8 - Release Hardening and 1.0 GA

**기간:** 2–3주  
**목표:** 보안·라이선스·운영·문서·릴리스 체계를 완결한다.

## 진입 조건

- M7 RC Candidate
- 라이선스 전략 최종 승인
- 모든 플랫폼 qualification 장비 확보

## 작업

### M8.1 Security hardening

- threat model final review
- malicious deck/archive/output suite
- dependency/container scan
- SBOM
- image signing/provenance
- secret scan
- broker API exposure review

### M8.2 License/release artifacts

- root LICENSE
- NOTICE/THIRD_PARTY_LICENSES
- source/provenance offer
- 이미지별 license inventory
- release notes and disclaimer

### M8.3 Operations

- update rollback
- backup/restore matrix
- disk cleanup and retention
- crash/reboot recovery
- uninstall
- support bundle privacy review

### M8.4 Documentation

- Windows/macOS/Linux quickstart
- local/shared/server deployment
- tutorial NMOS
- model limitations
- troubleshooting/error code catalog
- contributor guide using Harness

### M8.5 Final qualification

- fresh install on every support target
- numerical corpus
- 20-run cleanup
- update from beta/RC
- cross-OS project transfer
- accessibility and browser matrix

## 산출물

- signed release manifest
- images + digests 또는 local-build instructions per license strategy
- SBOM/provenance
- final docs
- 1.0 qualification report

## Exit criteria

- 릴리스 품질 게이트 전부 충족
- P0/P1 0, 승인되지 않은 P2 없음
- license/NOTICE complete
- support matrix와 known limitations 공개
- rollback-tested release artifacts

## Release

- **1.0 GA**

---

## 3. 병렬화 계획

| Workstream | 시작 가능 | 의존성 |
|---|---|---|
| License | M0 즉시 | 없음 |
| Numerical corpus | M0 후반 | baseline run |
| Runtime contract | M1 중반 | current characterization |
| Windows launcher UX | M2 후반 | command/config shape |
| macOS image spike | M1 후반 | image lock |
| Project schema 설계 | M1 | provenance field 합의 |
| Docs skeleton | M0 | support policy |
| Self-hosted CI provisioning | M1 | 장비 확보 |

2명이 투입되면 A는 runtime/broker/packaging, B는 validation/platform/UX를 담당할 수 있다. 다만 SUPREM/DEVSIM 수치 기준선과 라이선스는 공동 gate다.

---

## 4. 인력·장비·환경

### 4.1 최소 인력

- Lead engineer 1: backend/runtime/security
- Frontend/QA 0.5–1: UI/E2E/platform
- Semiconductor/numerical reviewer 0.2: corpus/tolerance
- License reviewer: M0/M8 집중

1명만 수행할 경우 frontend/QA를 순차 처리해 24–30주를 예상한다.

### 4.2 최소 테스트 장비

- Linux x86-64, 8 cores, 16GB+ RAM
- Windows 11 x64, WSL2/Docker Desktop 가능, 16GB+ RAM
- macOS Apple Silicon, 16GB+ RAM
- macOS Intel은 정식 지원을 유지한다면 별도 장비 또는 CI 서비스
- 빌드/qualification용 충분한 disk: 100GB 이상 권장

### 4.3 CI 운영

- GitHub-hosted: lint/unit/basic integration/build
- Self-hosted: Docker Desktop/Podman Machine/real solver/numerical
- nightly: full corpus and fault injection
- release: fresh-install/update/backup/restore manual evidence 포함

---

## 5. 일정 변동 요인

다음이면 일정이 늘어난다.

- SUPREM 배포 허가가 별도 협의 필요
- Apple Silicon native 포팅이 old C pointer model 재작성으로 확대
- 기존 baseline에서 새로운 silent correctness 결함 발견
- Docker/Podman 모두에서 동일한 sandbox 정책 구현이 불가능
- `.str` 포맷 parser의 미정의 영역이 추가 발견
- self-hosted runner 안정화 지연

다음이면 단축 가능하다.

- 1.0에서 macOS Intel을 maintenance-only로 낮춤
- SUPREM arm64를 1.1로 미루고 amd64 emulation을 승인
- Podman Machine을 preview로 두고 Docker Desktop을 정식 경로로 제한
- 프로젝트 export에서 대형 `.str` 결과를 기본 제외

---

## 6. 1.0 이후 제안

| Release | 후보 |
|---|---|
| 1.1 | native Linux arm64/Apple Silicon SUPREM, performance tuning |
| 1.2 | 교육 템플릿, assignment bundle, result report |
| 1.3 | parameter sweep/DOE, batch queue |
| 1.4 | DEVSIM 2.11.x validated upgrade, AC/transient workflow |
| 2.0 | signed extension packages, remote worker pool, restricted declarative models |

새 기능보다 1.0의 수치·보안·프로젝트 재현성 계약을 먼저 안정화한다.
