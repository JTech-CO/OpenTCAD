# M0 이식성 spike 보고서

[English](../../en/m0/portability-spike-report.md) | [M0 상태](README.md)

## 상태

아직 host 지원 결과를 주장하지 않습니다. Windows Docker Desktop과 WSL2 Debian rootless Podman에서 solver 실행 진단과 통과한 비솔버 OCI 장애 특성 증거를 얻었고 별도 통제 Podman build도 정확히 재현됐습니다. Solver 실행 관찰 2건은 선언된 log 실패로 계속 ineligible이고 통제 image와 장애 image도 권리, SBOM 검토, corpus 증거, 승인이 끝날 때까지 non-baseline 및 배포 금지 상태입니다. 검토된 image identity를 사용하기 전에는 host 지원 결론을 낼 수 없습니다.

## 시험 행렬

| Host 및 runtime | 확인 질문 | 필수 증거 | 상태 |
|---|---|---|---|
| Linux x86-64, rootless Podman | 고정 참조본이 선정 공정 및 소자 case를 재현하는가? | Runtime version, image digest, 전체 transcript, metric, 장애 경로 | WSL2 비솔버 장애 행렬 통과, clean solver 기준선 대기 |
| Windows 11 x64, Docker Desktop WSL2 | Mount, UID, signal, networking, resource limit contract에서 무엇이 다른가? | 같은 입력과 이미지, 진단 bundle, 구조화된 failure | 비솔버 policy 및 장애 행렬 통과, 지원 미결정 |
| Windows 11 x64, Podman Machine | `--userns keep-id` 가정 없이 runtime-neutral contract가 동작하는가? | Capability probe 및 adapter trace | 대기 |
| macOS Apple Silicon, Docker Desktop | amd64 이미지를 명시적으로 emulation해 실행할 수 있고 수치 허용 범위를 지키는가? | Architecture identity, emulation flag, metric, runtime 관찰 | 대기 |
| macOS Apple Silicon, Podman Machine | VM mount와 signal 동작에서 무엇이 다른가? | Capability probe, adapter trace, metric | 대기 |
| Linux arm64 compile-only SUPREM | Native 실행을 검토하기 전에 legacy pointer model을 안전하게 compile할 수 있는가? | Compiler output 및 static diagnostic만 사용 | 대기, 릴리스 제외 |

## 관찰한 Windows 사전 실행

[BASE-001 관찰 보고서](base001-reference-observation.md)는 고정 1D boron deck을 강화된 Docker에서 5회, WSL2 rootless Podman에서 5회 실행한 결과를 기록합니다. 두 runtime은 정확히 같은 structure hash와 record count를 생성했고 Podman은 선언 profile 검사를 통과했습니다. 기존 cache 없는 image 재빌드는 drift했고 모든 solver 실행은 exit code 0과 함께 선언된 command input 오류를 기록했습니다. 이후 통제 build는 base, package snapshot, timestamp를 고정해 같은 image를 2회 생성하고 외부 로컬 전용 SBOM도 만들었습니다. Image 증거는 개선됐지만 실행 결과를 승격하거나 host 지원을 확정하지 않습니다. 별도의 [OCI 장애 행렬](oci-fault-matrix.md)은 같은 고정 비솔버 Debian image와 검토 policy를 두 runtime에 적용했습니다. 각 runtime에서 이름 있는 시나리오 6개와 혼합 반복 20건이 정확한 이름 제거와 최종 label container 0개로 통과했습니다. Podman은 Docker의 임시 filesystem 의미와 맞추기 위해 `--read-only-tmpfs=false`가 필요했습니다.

## 통과 조건

- 모든 실행은 host, runtime, engine architecture, image digest, emulation 활성 여부를 식별합니다.
- 지원하지 않는 sandbox capability는 실행을 차단하고 조치 가능한 diagnostic을 제공합니다.
- Host 전체에서 같은 정규화 입력과 golden comparator를 사용합니다.
- 공정 topology와 소자 curve gate를 process 종료 상태와 별도로 통과해야 합니다.
- Host path가 암묵적 engine contract가 되면 안 됩니다.

재현 가능한 증거가 있을 때만 결과를 추가합니다. 그 전까지 1.0 host 지원 행렬은 미결정입니다.
