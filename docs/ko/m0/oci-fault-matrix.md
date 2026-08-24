# M0 OCI 장애 행렬 관찰

[English](../../en/m0/oci-fault-matrix.md) | [M0 상태](README.md)

## 결과

Windows Docker Desktop와 WSL2 Debian rootless Podman에서 검토된 비솔버 장애 행렬을 관찰했습니다. 두 runtime 모두 이름이 있는 시나리오 6개와 성공, 실패, 취소를 섞은 20회 반복을 통과했습니다. 모든 관리 container를 정확한 이름으로 제거했고 사례마다 관찰 label을 조회했으며 두 최종 orphan 수는 0이었습니다.

이는 기준선을 승격하지 않는 runtime 특성 관찰입니다. Solver, 제품 runtime adapter, 운영체제 또는 release image를 검증하지 않습니다.

| Runtime | 관찰 profile | 이름이 있는 시나리오 | 혼합 반복 | 최종 label container |
|---|---|---:|---:|---:|
| Docker Desktop 29.6.2 | Linux amd64, cgroup v2, Docker 관리 WSL2 VM | 6/6 | 20/20 | 0 |
| Podman 5.4.2 | Linux amd64, rootless, cgroup v2, WSL2 Debian | 6/6 | 20/20 | 0 |

정규화한 사실과 증거 hash는 [`OCI_FAULT_MATRIX_OBSERVATION.json`](../../../m0/OCI_FAULT_MATRIX_OBSERVATION.json)에 있습니다. 원본 출력, inspect 기록, command metadata, 외부 manifest는 commit하지 않습니다.

## 검토된 실행 경계

Collector는 [`m0-oci-fault-matrix.json`](../../../validation/plans/m0-oci-fault-matrix.json)만 받습니다. 계획은 로컬에 이미 존재하는 Debian image를 OCI index digest로 고정하고 `pull=never`를 사용합니다. SUPREM-IV.GS, Gmsh, DEVSIM 또는 OpenTCAD solver payload는 포함하지 않습니다.

각 container에는 다음 통제를 적용했습니다.

- Network 차단
- 모든 capability 제거 및 `no-new-privileges` 활성화
- 쓰기 가능한 임시 filesystem이 없는 read-only root filesystem
- UID와 GID `65534:65534`
- Mount와 restart 비활성화, PID, memory, CPU, stop time, wall time, output limit 명시

Command는 작은 allowlist에 있는 고정 인자 배열이며 shell을 거치지 않습니다. 첫 사례 전에 runtime별 관찰 label을 가진 기존 container가 있으면 collector가 실행을 거부합니다. Container 생성 이후 cleanup은 생성된 정확한 이름만 대상으로 합니다.

## 이름이 있는 장애 결과

| 시나리오 | 기대값과 관찰값 | 추가 검증 |
|---|---|---|
| Process policy | Exit 0 | Effective capability가 0이고 `NoNewPrivs`가 1이며 모든 process UID가 65534임 |
| Read-only root | Exit 1 | 두 runtime에서 `/tmp` 쓰기가 거부됨 |
| 선언된 nonzero exit | Exit 1 | 일반 container 실패가 supervisor 장애와 분리됨 |
| Timeout | `timed-out` | 첫 cleanup inspect 전에 command worker가 교체됨 |
| 취소 | `cancelled` | 첫 cleanup inspect 전에 command worker가 교체됨 |
| Output 폭주 | `output-limit-exceeded` | 합산 보관량이 32 KiB에서 제한되고 출력이 절단되며 worker가 교체됨 |

혼합 반복은 성공, nonzero exit, 취소를 고정 순서로 수행했습니다. 성공 7건, nonzero exit 7건, 취소 6건이며 20건 모두 policy, 결과, 정확한 이름 제거, 부재 확인, orphan 0 검사를 통과했습니다.

## Runtime 간 발견 사항

첫 rootless Podman 시도에서 실제 기본값 차이를 발견했습니다. Podman은 root filesystem이 read-only여도 임시 directory를 쓰기 가능하게 만들 수 있습니다. 따라서 검토 계약에 `writableTemporaryFilesystems: false`를 명시했고 Podman 매핑에 `--read-only-tmpfs=false`를 추가했습니다. 같은 `/tmp` 동작을 위해 Docker에 추가 flag는 필요하지 않았습니다. 실패한 진단 시도에서도 정확한 container를 제거하고 label container 0개로 끝났지만 최종 기록에는 포함하지 않았습니다.

이 backend별 매핑은 향후 runtime capability contract에 포함해야 합니다. `--read-only`가 모든 runtime에서 같다고 가정하면 안전하지 않습니다.

## 비승격 collector 다시 실행

저장소 밖의 새로운 절대 directory를 사용합니다. 검토 image는 로컬에 미리 있어야 하며 collector는 pull하지 않습니다.

```sh
node tools/observe-oci-fault-matrix.mjs \
  --plan validation/plans/m0-oci-fault-matrix.json \
  --runtime docker \
  --output <absolute-external-output-directory>
```

Windows WSL의 Podman을 사용할 때는 다음과 같이 실행합니다.

```powershell
node tools/observe-oci-fault-matrix.mjs `
  --plan validation/plans/m0-oci-fault-matrix.json `
  --runtime podman `
  --wsl-distribution Debian `
  --output <absolute-external-output-directory>
```

출력 directory는 미리 존재하면 안 됩니다. Collector는 원본 증거를 해당 위치에만 쓰고 차이가 있으면 nonzero로 종료하며 기준선을 자동 승격하지 않습니다.

## 남은 게이트

- M2 `RuntimeBackend` contract와 제품 Docker 및 Podman adapter 구현
- API, worker, broker, 관리 job volume, 영속 job state 경로를 통한 같은 행렬 반복
- Command 장애 외에 worker, broker, runtime, host crash 주입
- 사용 권한이 확인된 solver fixture와 승인된 불변 engine image로 반복
- Native Linux, Windows, macOS, Podman Machine 개별 검증

권리, 오류 없는 solver log, SBOM license 검토, 수치 corpus, 이식성, release 승인이 미완료이므로 M0는 계속 열려 있습니다.
