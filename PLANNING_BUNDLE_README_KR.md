# TCAD Webapp Cross-Platform Porting Planning Bundle

**작성 기준일:** 2026-08-23  
**대상 업스트림:** `ypooh2042/tcad-webapp` (`master`)  
**문서 성격:** 구현 기획·하네스·마일스톤·초기 백로그 및 M0 실행 기준

이 번들은 SUPREM-IV.GS 공정 시뮬레이션과 DEVSIM 소자 해석을 결합한 기존 TCAD 웹앱을 Windows·macOS·Linux에서 로컬 서버 형태로 재현 가능하게 만들기 위한 실행 계획이다. 1차 목표는 SUPREM-IV.GS를 Windows/macOS 네이티브 바이너리로 직접 이식하는 것이 아니라, Linux OCI 컨테이너 실행 계층을 Docker Desktop·WSL2·Podman Machine으로 감싸 동일한 웹앱 경험을 제공하는 것이다.

## 후속 편집 기록

- 2026-08-23: 한국어 기획 문서 5개의 Unicode em dash(`U+2014`) 125개를 ASCII 하이픈으로 정규화했다.
- 2026-08-23: 마일스톤에서 달력·인원 기반 개발 예측을 제거하고 기술 의존성, 검토 역할, 승인 게이트를 유지했다.
- 제품 결정, 수치, 코드 예시, 표의 의미는 바꾸지 않았으며 `PLANNING_BUNDLE_SHA256.txt`는 현재 파일을 기준으로 다시 생성한다.

## 문서 구성

| 파일 | 용도 |
|---|---|
| `01_PRODUCT_TECHNICAL_PLAN_KR.md` | 제품 범위, 현재 구조 분석, 목표 아키텍처, 보안·과학 검증·라이선스·QA 기획 |
| `02_CODEX_HARNESS_KR.md` | Codex/에이전트가 이 저장소를 안전하게 수정하도록 하는 작업 규약과 품질 게이트 |
| `03_MILESTONE_ROADMAP_KR.md` | 단계별 순서, 선행조건, 산출물, 진입·종료 기준, 릴리스 계획 |
| `04_INITIAL_BACKLOG_KR.md` | 실제 GitHub Issue로 분해하기 위한 초기 에픽·이슈 백로그 |
| `TCAD_CROSS_PLATFORM_MASTER_PLAN_KR.md` | 위 핵심 문서를 한 파일로 합친 버전 |
| `assets/` | 사용자가 제공한 현행 UI 스크린샷 |

## 핵심 결론

1. **컨테이너 우선 포팅이 정답이다.** Windows/macOS에서 컨테이너는 Linux VM을 통해 실행되므로, 기존 Linux 기반 시뮬레이터를 유지하면서 호스트 차이를 런타임 어댑터와 패키징 계층에서 흡수한다.
2. **현재의 Podman 전용 실행 코드를 런타임 중립 계층으로 분리해야 한다.** `podman run`, `--userns keep-id`, pause 프로세스 복구, systemd 사용자 유닛을 비즈니스 로직과 분리한다.
3. **패키지형 로컬 모드에서는 호스트 경로 bind mount를 최소화하고, 잡별 엔진 관리 볼륨을 사용한다.** Windows 경로·macOS 파일 공유·권한·성능 문제와 샌드박스 경계 약화를 동시에 줄인다.
4. **시뮬레이터 결과의 ‘실행 성공’과 ‘과학적으로 신뢰 가능한 결과’를 분리한다.** 골든 코퍼스, 토폴로지 불변식, 공정 지표, I–V 지표, 교차 아키텍처 허용오차를 별도 게이트로 둔다.
5. **라이선스가 첫 번째 Go/No-Go 항목이다.** OpenTCAD 목표 저장소의 고유 코드는 MIT이지만, 고정 참조 저장소의 루트 라이선스는 확인되지 않았고 SUPREM-IV.GS 상류 라이선스도 MIT가 아니다. 앱 코드와 번들된 시뮬레이터의 배포 정책을 분리하며, M0 검토가 끝날 때까지 솔버 번들은 차단한다.

## 문서 사용 순서

1. `01_PRODUCT_TECHNICAL_PLAN_KR.md`의 ADR과 Go/No-Go 결정을 확정한다.
2. 확정된 결정을 `02_CODEX_HARNESS_KR.md` 상단의 프로젝트 변수에 반영한다.
3. `03_MILESTONE_ROADMAP_KR.md`의 M0를 진행하고 현재 상태는 `docs/ko/m0/README.md`에 기록한다.
4. `04_INITIAL_BACKLOG_KR.md`를 GitHub Issue로 옮기되, 각 이슈는 하네스의 Definition of Done을 그대로 적용한다.

## 분석 범위와 제한

- 소스 저장소의 README, 코드맵, 실행 샌드박스, 설정, Containerfile, 테스트 구조와 최신 커밋 흐름을 검토했다.
- 인증이 필요한 라이브 배포본은 이 기획 단계에서 실제 가입·공정 실행까지 독립 검증하지 않았다. UI 평가는 사용자가 제공한 스크린샷과 저장소 코드·문서를 기준으로 했다.
- 수치 허용오차는 현재 결과 분산을 측정하기 전이므로 일부가 **잠정값**이다. M1에서 플랫폼별 반복 실행 데이터를 수집한 뒤 확정한다.
- 법률 자문 문서가 아니다. 배포 전에 라이선스 전문가 또는 권리자 확인이 필요하다.
