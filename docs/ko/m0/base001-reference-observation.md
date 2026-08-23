# BASE-001 참조 관찰 하네스

[English](../../en/m0/base001-reference-observation.md) | [M0 상태](README.md)

## 결과

OpenTCAD에 외부 참조 실행을 위한 실패 폐쇄형 엔진 독립 관찰 하네스를 추가했습니다. 이 하네스는 고정 Git commit과 정확한 입력 blob을 확인하고, OCI runtime과 image identity를 조사하며, shell 없이 실행합니다. 원본 증거는 저장소 밖에 저장하고 모든 입력, log, 산출물에 hash를 계산하며, 정확 반복성을 측정합니다. 기준선이나 image lock은 변경하지 않습니다.

두 차례의 5회 관찰과 통제 image build 후속 관찰은 유용한 증거지만 **BASE-001을 완료하지 않습니다**. Docker Desktop 실행은 필수 runtime 및 rootless profile을 충족하지 못했습니다. 이후 WSL2 Debian 실행은 선언된 Linux amd64 rootless Podman profile을 충족했고 같은 structure byte와 topology count를 재현했습니다. 기존 image 재빌드는 drift했고 모든 solver 실행은 exit code 0과 함께 선언된 command input 오류를 기록했습니다. 별도로 digest, snapshot, timestamp를 고정한 후속 build는 정확히 재현되고 로컬 전용 SBOM도 생성했지만 승인된 기준선이나 release image는 아닙니다.

## 구현한 통제

- [`observe-reference-run.mjs`](../../../tools/observe-reference-run.mjs)는 OpenTCAD 내부 출력 경로를 거부하며 shell command 문자열이 아닌 argument 배열만 받습니다.
- Source tree는 Git checkout과 분리할 수 있지만 각 입력 파일은 고정 Git blob과 일치해야 합니다. 이 방식으로 provenance를 약화하지 않고 원본 LF build context를 사용할 수 있습니다.
- 저장소의 [1D boron 계획](../../../validation/plans/base001-process-1d-boron.json)은 5회 실행, 읽기 전용 container root, network 차단, capability 제거, `no-new-privileges`, PID, memory, CPU, timeout 제한을 요구합니다.
- 선언한 stderr 또는 stdout 실패 문구는 exit code 0보다 우선합니다. 필수 산출물이 모든 실행에 존재하고 하나의 정확한 hash를 유지해야 반복 가능하다고 기록합니다.
- 생성 manifest는 항상 관찰 기록입니다. `baselinePromotionAllowed`는 `false`로 고정되며, 조건에 맞는 실행도 자동 승인이 아니라 `review-required`까지만 갈 수 있습니다.

## 2026-08-24 Docker Desktop 관찰

정규화한 기계 판독 기록은 [`m0/BASE001_DOCKER_OBSERVATION.json`](../../../m0/BASE001_DOCKER_OBSERVATION.json)에 있습니다. 원본 solver log, structure, plot, runtime probe, SBOM은 MIT 저장소 밖에 유지합니다.

| 증거 | 관찰 |
|---|---|
| 고정 참조 | `ypooh2042/tcad-webapp@13bce4a9daba5796ceee633fb8cd0c870465f766` |
| 필수 profile | Linux amd64, rootless Podman |
| 관찰 profile | Docker 29.6.2, Docker Desktop 4.84.0, Linux amd64, rootless 아님 |
| Image | `opentcad-reference/suprem@sha256:325fdd0f81712519764ceb78baf728afea899357728cc5e05a5bebc5c30bf865`, 로컬 전용 |
| 입력 | 고정 Git blob `c28fd878ccb9ac2cc687b0a882ec4a51d91a05d9`, SHA-256 `fab7228f...9684` |
| 필수 출력 | 5회 모두 5,784 byte `boron.str`, SHA-256 `971dfc50...b45b` |
| Topology record | 5회 모두 node 43, element 42, region 2, boundary record 0 |
| 참조 비교 | 생성 structure가 고정 fixture Git blob `ec08539c5a4e5070d04c197249c4b5956a1632df`와 일치 |
| 종료와 log | 5회 모두 exit code 0이지만 실행마다 미지원 parameter 2건과 command input error 1건 발견 |
| 선택 plot | 생성되지 않음 |
| Cache 없는 재빌드 | Digest `sha256:f8c5ee27...a0126`, config는 같지만 layer와 최종 digest는 다름 |
| SBOM | SPDX 2.3, package 130개, SHA-256 `5635a9af...27a2`, 모든 concluded license가 `NOASSERTION` |
| 기준선 결과 | `ineligible`, BASE-001은 대기 상태 유지 |

이 결과는 OpenTCAD이 process exit를 수치 성공과 같게 취급하지 않는 이유를 보여줍니다. 반복된 structure는 유용한 동작 관찰이지만 승인된 golden result는 아닙니다.

## 2026-08-24 WSL2 rootless Podman 관찰

두 번째 정규화 machine record는 [`m0/BASE001_ROOTLESS_PODMAN_OBSERVATION.json`](../../../m0/BASE001_ROOTLESS_PODMAN_OBSERVATION.json)입니다. 원본 log, structure, runtime probe, image, build 출력은 OpenTCAD 밖에 유지합니다.

| 증거 | 관찰 |
|---|---|
| Host | WSL2, Debian 13 trixie, kernel `6.18.33.2-microsoft-standard-WSL2` |
| Runtime profile | Podman 5.4.2, Linux amd64, rootless, cgroup v2 및 cgroupfs fallback |
| Profile 평가 | 선언된 runtime, OS, architecture, rootless 검사 4개 모두 통과 |
| 첫 image | ID `bbfe2ae2...b1318`, digest `sha256:225eff7d...60b3b`, 로컬 전용 |
| Cache 없는 재빌드 | ID `37fc29a1...07d3`, digest `sha256:ad9afbb0...1407`, config와 base 이외 layer 4개가 다름 |
| Solver binary | 두 Podman build 모두 SHA-256 `9c6d7a0b...b7805` |
| 필수 출력 | 5회 및 Docker 관찰 모두 같은 5,784 byte structure SHA-256 `971dfc50...b45b` |
| Log | 모든 실행에서 미지원 parameter 2건과 command input error 1건이 동일하게 발견됨 |
| Podman image SBOM | 이 실행에서는 생성하지 않았으며 이후 통제 build에서 별도 로컬 전용 SBOM을 생성함 |
| 기준선 결과 | `ineligible`, runtime profile 게이트는 관찰했지만 BASE-001은 대기 상태 유지 |

Podman이 선택한 `pasta` rootless network command를 위해 Debian `passt` package가 필요했습니다. 비대화형 `wsl.exe` session에는 systemd user bus가 노출되지 않아 image build는 cgroupfs를 명시했고 관찰 실행은 Podman이 보고한 cgroupfs fallback을 사용했습니다. 이는 setup 관찰이며 host 지원 주장이 아닙니다.

## 통제된 재현 image 및 로컬 SBOM 후속 관찰

정규화한 기록은 [`m0/BASE001_REPRODUCIBLE_IMAGE_OBSERVATION.json`](../../../m0/BASE001_REPRODUCIBLE_IMAGE_OBSERVATION.json)에 있고 [검토된 build 계획](../../../validation/plans/base001-suprem-image-build.json)과 연결됩니다. 준비 도구는 외부 고정 Containerfile hash를 확인하고 source tree를 변경하지 않은 채 고정 recipe를 OpenTCAD 밖에만 생성했습니다.

| 증거 | 관찰 |
|---|---|
| 결정적 통제 | amd64 base manifest 2개, Debian 2026-08-03 snapshot, commit epoch `1787471368`, `SOURCE_DATE_EPOCH`, locale `C`, UTC, OCI format, `--pull=never`, `--no-cache` |
| Build 2회 | Image ID `b5007db9...ed735`, manifest digest `sha256:49320295...e1095`, 크기, 생성 시각, rootfs layer 5개가 모두 같음 |
| Solver binary | SHA-256 `9c6d7a0b...b7805`, 앞선 rootless 관찰과 같음 |
| 로컬 scan | Syft 1.51.0을 amd64 manifest digest로 고정하고 rootless, read-only, capability 전체 제거, no new privileges, network 차단 적용 |
| CycloneDX | Version 1.7, component 3,077개: package 88개, file 2,988개, operating system 1개, package 88개 모두 PURL과 license evidence 포함 |
| Archive 연결 | Export된 OCI manifest digest `sha256:d55a7174...d897`가 config `sha256:b5007db9...ed735`를 가리키며 재현 image ID와 일치 |
| 검토 결과 | 기술적 재현성과 로컬 SBOM 생성은 관찰했으나 배포, license conclusion, 기준선 승격, 지원은 미승인 |

첫 scan은 임시 공간을 64 MiB만 할당해 실패 폐쇄됐고 update 확인 통신은 `--network none`으로 차단됐습니다. 빈 출력은 제거했습니다. 성공한 scan은 update 확인을 명시적으로 끄고 512 MiB 임시 filesystem을 사용했으며 OCI archive와 CycloneDX 문서를 저장소 밖에 유지했습니다.

## Windows checkout에서 확인한 문제

일반 Windows checkout에서 처음 image를 빌드했을 때 `core.autocrlf=true`가 source와 patch를 CRLF로 변환해 patch 문맥이 맞지 않았습니다. OpenTCAD 밖에서 `core.autocrlf=false`, `core.eol=lf`로 별도 `git archive`를 만들었습니다. 로컬 image를 성공적으로 빌드하기 전에 build 핵심 파일 4개가 고정 Git blob ID와 일치하는지 확인했습니다. 참조 source, patch, binary, image, 원본 solver 산출물은 이 저장소에 추가하지 않았습니다.

## 관찰 실행

의도한 환경에서 로컬 사용이 허용되는지 확인한 후 로컬 참조 image를 빌드하고 다음과 같이 실행합니다.

```text
npm run observe:base001 -- \
  --plan validation/plans/base001-process-1d-boron.json \
  --reference-workspace <external-frozen-git-clone> \
  --source-root <external-raw-byte-source-tree> \
  --output <new-directory-outside-opentcad> \
  --runtime podman
```

Process 실패, 필수 산출물 누락, timeout, 선언한 log 실패가 있으면 command가 0이 아닌 code로 종료됩니다. 환경 profile 불일치는 `ineligible`로 기록하며 필수 profile을 조용히 바꾸지 않습니다.

## 남은 게이트

1. SUPREM과 참조 patch 권리를 전문가가 검토합니다.
2. SBOM license evidence를 검토하고 사용 권한이 있는 release image recipe를 승인하거나 거부합니다.
3. 사용 권한이 있고 독립 검토된 fixture에서 실패하는 plot command를 교체하거나 수정합니다.
4. NMOS와 CMOS 공정 및 소자 관찰을 추가하고 검증된 장애 계약을 실제 Docker 및 Podman adapter에서 실행합니다.
5. Maintainer와 반도체 수치 검토자가 명시적으로 검토한 증거만 승격합니다.
