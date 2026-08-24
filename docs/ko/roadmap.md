# OpenTCAD 마일스톤 로드맵

[English](../en/roadmap.md)

상세 기획 원문은 `03_MILESTONE_ROADMAP_KR.md`입니다. 이 한·영 요약은 공개 제품 순서를 설명하며 마일스톤의 진입·종료 게이트를 대체하지 않습니다.

| 마일스톤 | 결과 | 필수 게이트 |
|---|---|---|
| 기반 | MIT 고유 한·영 정적 앱, Pages, CI, 아키텍처·라이선스 경계 | 정적 모드에서 입력 실행 불가 |
| M0 | 업스트림·의존성 목록, 배포 결정, Linux 기준선, 플랫폼 spike | 라이선스와 기준선 Go/No-Go |
| M1 | 공정·소자 골든 코퍼스, 수치 comparator, 재현 이미지 lock, CI 기반 | 반복 가능한 topology와 metric 증거 |
| M2 | 런타임 계약, Docker/Podman adapter, sandbox broker, 관리 잡 볼륨 | 두 런타임에서 정책 fail-closed |
| M3 | 이식 가능한 로컬 stack, loopback 전용 모드, launcher, doctor, backup 골격 | 단일 명령 local alpha |
| M4 | Windows 11 자격 검증 | Docker Desktop WSL2 E2E와 수치 증거 |
| M5 | macOS 및 multi-architecture 자격 검증 | Apple Silicon native 또는 명시적 amd64 emulation 정책 |
| M6 | correctness, 수치 안정성, 데이터 안전, UX 결함 해소 | 열린 P0/P1과 알려진 silent correctness 결함 0 |
| M7 | 이식 가능한 `.tcadproj`, provenance, 진단, engine registry | OS 간 replay와 안전한 import |
| M8 | 보안, 라이선스, 릴리스 운영, 문서, 전체 자격 검증 | 1.0 GA 게이트와 rollback 증거 |

## 현재 상태

프로젝트 기반 마일스톤은 완료되어 GitHub Pages에 배포되었습니다. M0는 진행 중이며 고정된 provenance, 라이선스, 아키텍처, 기준선 기록은 [M0 작업 현황](m0/README.md)에 있습니다. Windows Docker Desktop과 WSL2 rootless Podman에서 각각 정확히 같은 structure 출력 5개를 얻었고 별도 통제 Podman image는 같은 ID, digest, layer로 재빌드되어 로컬 전용 SBOM도 생성했습니다. 엔진 독립 supervisor는 timeout, 취소, 합산 출력 상한, 장애 후 worker 교체를 검사합니다. 비승격 OCI 행렬은 Docker Desktop과 WSL2 rootless Podman에서 20회 혼합 반복과 label orphan 0을 포함해 같은 경로를 관찰했지만 제품 adapter와 solver 장애 증거는 대기 상태입니다. Clean log, 권리, SBOM license conclusion, corpus 범위, 이식성, 수치 검토 게이트는 계속 미충족입니다. M1은 `gated-active` 상태입니다. [검증 기반](m1/README.md)에 후보 manifest와 unit test를 통과한 comparator를 구현했지만 fixture와 수치 기준선은 포함하지 않습니다. M2도 `gated-active` 상태입니다. [런타임 계약 기반](m2/README.md)은 typed model, stable error, fail-closed policy 검사, canonical input/output archive 방어, cancellation checkpoint 11곳, 공개 및 저장 shape redaction, concurrent process-local cleanup, reconciliation, 결정론적 broker-event mapping, 재사용 가능한 state-adapter conformance suite, non-durable CAS store 기반 mock crash/restart recovery 계약을 제공하지만 durable storage, 실제 adapter, broker service transport, detection, worker integration, runtime socket 접근은 차단 상태입니다. SUPREM 고지와 참조 패치가 목표 번들 배포에 대해 확인되지 않아 솔버 배포는 차단 상태입니다. 업스트림 애플리케이션은 읽기 전용 증거로만 사용하며 이 MIT 저장소에 복사하지 않습니다.

## 정적 배포와 로컬 배포

GitHub Pages는 로드맵 전체에서 안전한 제품 미리보기와 문서 표면으로 유지합니다. Pages를 샌드박스 우회 수단으로 사용하지 않습니다. 솔버 실행은 loopback 전용 로컬 stack 또는 인증된 관리 서버에서만 가능합니다.

프로세스 종료만으로 결과를 “성공” 처리하지 않습니다. topology 불변식, 공정 metric, I–V metric, 수렴 의미, provenance, 플랫폼 간 허용오차를 별도 release gate로 유지합니다.
