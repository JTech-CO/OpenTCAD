# M0 조사 및 기준선 상태

[English](../../en/m0/README.md)

M0 작업을 시작했습니다. 이 기록은 라이선스, 출처, 아키텍처, 기준선 작업의 시작점이며 솔버 기반 로컬 릴리스가 준비됐다고 주장하지 않습니다.

## 현재 배포 경계

| 표면 | 상태 | 이유 |
|---|---|---|
| OpenTCAD 고유 MIT 소스와 한·영 문서 | 승인 | 저장소의 MIT 라이선스 적용 |
| 엔진 없는 GitHub Pages 미리보기 | 승인 | 솔버 소스, 바이너리, 이미지를 포함하지 않음 |
| 엔진을 번들하지 않는 로컬 서버 셸 | 설계 허용 | 런타임 계약과 launcher는 아직 미구현 |
| SUPREM-IV.GS 소스, 패치, 바이너리, 이미지 | 차단 | 별도 고지와 패치 권리를 전문가가 검토해야 함 |
| DEVSIM, Gmsh 또는 통합 솔버 이미지 | 검토 필요 | 정확한 산출물, 고지, digest, 전이 라이선스가 아직 고정되지 않음 |

이는 공학적 배포 게이트이며 법률 자문이 아닙니다.

## 작업 현황

| 작업 | 상태 | 증거 또는 다음 게이트 |
|---|---|---|
| LIC-001 OpenTCAD 루트 라이선스 | 완료 | `LICENSE`, `NOTICE`, GitHub 라이선스 인식 |
| LIC-002 SUPREM 배포 결정 | 차단 | 전문가 검토 또는 서면 허가 필요 |
| LIC-003 제3자 및 이미지 인벤토리 | 진행 중 | Docker 및 Podman image identity와 외부 Docker SBOM 1개를 관찰했으나 Podman SBOM, license conclusion, 재현 build는 미완료 |
| LIC-004 릴리스 이미지 정책 | 시작 전 | 미승인 또는 고정되지 않은 이미지를 거부해야 함 |
| BASE-001 Linux 참조 기준선 | 진행 중, 미충족 | Rootless Podman이 선언 profile을 충족하고 Docker structure byte와 일치했으나 log, image 재빌드, SBOM, 권리, 검토 게이트는 미충족 |
| 현행 아키텍처 기록 | 초안 완료 | 목표 저장소와 참조 저장소 경계를 기록함 |
| 이식성 spike | 사전 관찰 | Windows Docker Desktop과 WSL2 rootless Podman에서 진단 증거를 얻었으나 지원을 주장하지 않음 |
| M0 종료 게이트 | 미충족 | 수치, 플랫폼, 지원 행렬 증거가 남아 있음 |

## M0 산출물

- [라이선스 전략](license-strategy.md)
- [기준선 및 clean-room 정책](baseline-and-clean-room.md)
- [BASE-001 참조 관찰 하네스](base001-reference-observation.md)
- [현행 아키텍처](current-architecture.md)
- [이식성 spike 보고서](portability-spike-report.md)
- [기계 판독 의존성 및 이미지 인벤토리](../../../m0/DEPENDENCY_AND_IMAGE_INVENTORY.json)
- [기계 판독 기준선 고정 기록](../../../m0/BASELINE_FREEZE.json)
- [기계 판독 ineligible Docker 관찰](../../../m0/BASE001_DOCKER_OBSERVATION.json)
- [기계 판독 ineligible rootless Podman 관찰](../../../m0/BASE001_ROOTLESS_PODMAN_OBSERVATION.json)
- [5회 1D 관찰 계획](../../../validation/plans/base001-process-1d-boron.json)

`npm run check:m0`는 두 관찰 기록, collector hash, 불변 commit 형식, 이미지 승인 규칙, 한·영 문서 쌍, 실패 폐쇄 상태를 검사합니다. Rootless Podman은 선언된 환경 profile을 충족하고 Docker structure를 정확히 재현했지만 선언된 solver log 오류, image drift, 누락된 Podman image SBOM, 권리, 수치 검토 때문에 BASE-001은 열린 상태입니다.

## 다음 게이트

1. SUPREM 소스, 패치, 바이너리, 이미지 배포에 대한 전문가 판단을 받습니다.
2. 선언된 input 오류를 수정하고 Podman image를 재현 가능하게 만든 뒤 로컬 image SBOM을 생성합니다.
3. 제안된 NMOS 공정·소자 및 CMOS 공정·소자 case를 실행합니다.
4. 검토된 입력, 출력, log, metric, image, 반복 실행 증거를 고정합니다.
5. 같은 기준선으로 native Linux, Windows, macOS, Podman Machine 이식성 spike를 수행합니다.

엔진 독립 M1 계약 작업은 `gated-active` 상태로 진행할 수 있습니다. 적용되는 M0 게이트를 통과하기 전에는 수치 코퍼스를 고정하거나 솔버 기반 제품 주장을 시작하지 않습니다.
