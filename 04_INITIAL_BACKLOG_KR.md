# TCAD Webapp Cross-Platform Porting - Initial Epic & Issue Backlog

> 이 문서는 GitHub Issue로 옮기기 위한 초기 분해안이다. 실제 구현 전에 각 이슈는 `02_CODEX_HARNESS_KR.md`의 Issue Intake Contract로 보완한다.

## Priority 정의

- **P0:** 보안·침묵하는 수치 오류·데이터 손실·release blocker
- **P1:** 지원 플랫폼 핵심 흐름·수치 안정성·복구 실패
- **P2:** UX·성능·운영성·문서
- **P3:** 이후 확장

---

## EPIC LIC - 라이선스·출처·배포

### LIC-001 [P0/L5] 루트 라이선스 상태 확정

- 저장소 루트 `LICENSE` 부재와 GitHub metadata 확인
- 앱 코드 copyright owner와 intended license 확인
- **완료:** 승인된 root license와 README 표현

### LIC-002 [P0/L5] SUPREM 상류 라이선스 배포 검토

- commercial transaction 제한의 범위 검토
- source/image redistribution 선택지 비교
- **완료:** mixed/optional/permission 결정과 문서

### LIC-003 [P0/L5] Third-party inventory/NOTICE

- DEVSIM, Gmsh, base images, Python/Node dependencies
- **완료:** `THIRD_PARTY_LICENSES.md`, `NOTICE`, image inventory

### LIC-004 [P1/L5] Release image 정책

- 배포 가능/사용자 local build-only 이미지 구분
- **완료:** release pipeline가 정책 위반 이미지를 거부

---

## EPIC BASE - 기준선·코퍼스·CI

### BASE-001 [P0/L4] Linux 현행 baseline report

- 예제 공정/소자 결과, runtime, image digest, metric 기록

### BASE-002 [P0/L4] 공정 골든 코퍼스

- 1D boron/oxidation/implant, 2D NMOS/CMOS

### BASE-003 [P0/L4] `.str` parser topology corpus

- material/region/contact/element exact invariant

### BASE-004 [P0/L4] DEVSIM I–V corpus

- diode, NMOS Id–Vg/Id–Vd, CMOS load line

### BASE-005 [P1/L4] Numerical comparator/report

- exact/topology/geometry/field/curve/repeatability

### BASE-006 [P1/L3] GitHub Actions PR foundation

- backend/frontend lint/unit/integration/image smoke

### BASE-007 [P1/L4] Nightly numerical workflow

- artifact report와 baseline 무단 변경 감지

---

## EPIC RUNTIME - Runtime abstraction

### RUN-001 [P0/L3] 현행 Podman 실행 characterization

- argv, inspect, errors, cancellation, timeout, cleanup

### RUN-002 [P0/L3] `RuntimeBackend` contract

- capability, image, volume, run, kill, cleanup, stable errors

### RUN-003 [P0/L3] 공통 Sandbox policy validator

- 필수 정책 누락 시 fail closed

### RUN-004 [P1/L3] Podman adapter 추출

- pause/systemd repair를 adapter 내부로 이동

### RUN-005 [P0/L3] Docker adapter

- Desktop/Engine security/resource/lifecycle mapping

### RUN-006 [P1/L3] Runtime auto-detection/override

- deterministic priority와 doctor output

### RUN-007 [P1/L3] Runtime contract test suite

- mock + real Docker + real Podman

---

## EPIC BROKER - Sandbox Broker·잡 볼륨

### BRK-001 [P0/L3] Broker threat model and protocol

- typed request, allowlist, internal-only transport

### BRK-002 [P0/L3] Image digest/entrypoint allowlist

- raw image/command 거부

### BRK-003 [P0/L3] Per-job managed volume lifecycle

- create, tar-in, run, tar-out, remove

### BRK-004 [P0/L3] Archive/path/symlink defense

- traversal, hardlink, device, bomb, size/file-count

### BRK-005 [P0/L3] Container resource and security enforcement

- network/capabilities/read-only/user/tmpfs/limits

### BRK-006 [P1/L3] Fault recovery and orphan reaper

- worker/broker/runtime/host crash cases

### BRK-007 [P1/L3] Cancellation identity contract

- SUPREM/remesh/DEVSIM 모두 동일 job label/name

### BRK-008 [P1/L3] Structured runtime events/redaction

- stable error + internal raw details

---

## EPIC PKG - Local stack·launcher·운영

### PKG-001 [P0/L3] Compose local profile

- web/API/worker/broker/PG/Redis/volumes/health

### PKG-002 [P1/L2] Local mode security

- loopback enforcement, owner bootstrap, invite 비활성

### PKG-003 [P1/L2] Cross-platform launcher core

- doctor/up/status/down

### PKG-004 [P1/L2] Backup/restore/update/rollback

- DB + persistent storage + manifest

### PKG-005 [P1/L2] Port conflict and browser open

### PKG-006 [P1/L3] Runtime doctor capability checks

### PKG-007 [P2/L2] Uninstall/data retention UX

---

## EPIC WIN - Windows qualification

### WIN-001 [P1/L2] PowerShell launcher encoding/path

### WIN-002 [P1/L3] Docker Desktop WSL2 fresh install E2E

### WIN-003 [P1/L2] Windows filesystem edge cases

- CRLF, Unicode, reserved names, case collision, long path

### WIN-004 [P1/L3] Desktop restart/sleep/low-resource recovery

### WIN-005 [P1/L3] Podman Machine preview path

### WIN-006 [P1/L4] Windows numerical qualification

### WIN-007 [P2/L0] Windows troubleshooting docs

---

## EPIC MAC - macOS·arm64

### MAC-001 [P0/L4] Image platform inventory

### MAC-002 [P1/L4] SUPREM arm64 compile/sanitizer spike

### MAC-003 [P0/L4] Native arm64 vs amd64 emulation numerical report

### MAC-004 [P1/L3] Mixed-platform Compose support

### MAC-005 [P1/L3] Docker Desktop macOS lifecycle E2E

### MAC-006 [P1/L3] Podman Machine macOS path

### MAC-007 [P1/L4] macOS Intel regression

### MAC-008 [P2/L0] macOS install/troubleshooting docs

---

## EPIC CORR - Correctness·수치 안정성

### CORR-001 [P0/L4] Interface stable identity/uniqueness

- 사용자 label과 internal key 분리, 중복 fail

### CORR-002 [P0/L4] Electrode/contact topology invariant

### CORR-003 [P0/L4] Source order→artifact order 보존

### CORR-004 [P0/L4] Unit registry 통합

### CORR-005 [P1/L4] Remesh contact/topology preservation

### CORR-006 [P1/L4] Adaptive bias ramp policy

- step halving, retry limit, rollback, provenance

### CORR-007 [P1/L4] Non-converged point semantics

- solved와 분리, UI/manifest 일치

### CORR-008 [P1/L4] NaN/Inf/partial artifact rejection

### CORR-009 [P1/L4] Cross-architecture tolerance calibration

---

## EPIC DATA - 데이터·프로젝트 재현성

### DATA-001 [P0/L2] Partial edit vs executable spec 분리

### DATA-002 [P1/L2] Revision/ETag save conflict

### DATA-003 [P1/L2] Artifact/saved result lifecycle contract

### DATA-004 [P1/L2] `.tcadproj` JSON Schema

### DATA-005 [P0/L3] Secure project import staging

### DATA-006 [P1/L2] Cross-OS export/import

### DATA-007 [P1/L2] Provenance manifest

### DATA-008 [P1/L2] Project schema migration/rollback

### DATA-009 [P1/L2] Backup/restore compatibility matrix

---

## EPIC UX - 상태·입력·진단·교육 표시

### UX-001 [P1/L2] Stale request identity/abort

### UX-002 [P1/L1] Numeric input intermediate-state component

### UX-003 [P1/L1] Runtime readiness/onboarding screen

### UX-004 [P1/L1] Stable error code + action UI

### UX-005 [P1/L1] Convergence/skipped point visualization

### UX-006 [P2/L1] Provenance panel

### UX-007 [P2/L1] Educational/non-sign-off banner and model card

### UX-008 [P2/L1] Accessibility/color-independent states

### UX-009 [P2/L1] Large mesh canvas cache/performance

---

## EPIC DIAG - 관측성·지원 번들

### DIAG-001 [P1/L2] Structured log schema

### DIAG-002 [P1/L2] Job diagnostics API

### DIAG-003 [P1/L2] Redacted diagnostics bundle

### DIAG-004 [P1/L3] Runtime fault classification suite

### DIAG-005 [P2/L2] Storage/runtime health dashboard

---

## EPIC EXT - 안전한 확장 계약

### EXT-001 [P2/L2] Engine capability manifest schema

### EXT-002 [P2/L3] Current engines registry migration

### EXT-003 [P2/L4] Validator engine registration

### EXT-004 [P3/L2] Parameter sweep RFC

### EXT-005 [P3/L4] DEVSIM version upgrade RFC

### EXT-006 [P3/L5] Signed extension package threat model

---

## EPIC REL - Release hardening

### REL-001 [P0/L3] Malicious deck/output/archive security suite

### REL-002 [P1/L5] SBOM/image signing/provenance

### REL-003 [P1/L5] Release manifest and digest lock

### REL-004 [P1/L2] Fresh install/update/rollback matrix

### REL-005 [P1/L2] 20-run orphan/leak qualification

### REL-006 [P1/L4] Full cross-platform numerical qualification

### REL-007 [P1/L0] Quickstart/tutorial/troubleshooting/error catalog

### REL-008 [P1/L5] 1.0 GA checklist

---

## 권장 첫 12개 Issue 순서

1. LIC-001
2. LIC-002
3. BASE-001
4. BASE-002
5. BASE-003
6. BASE-004
7. BASE-005
8. RUN-001
9. RUN-002
10. RUN-003
11. BRK-001
12. BASE-006

라이선스와 baseline이 없으면 포팅 결과를 배포하거나 수치적으로 판정할 수 없으므로 이 순서를 바꾸지 않는 것이 안전하다.
