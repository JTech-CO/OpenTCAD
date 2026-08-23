# M0 이식성 spike 보고서

[English](../../en/m0/portability-spike-report.md) | [M0 상태](README.md)

## 상태

아직 host 지원 결과를 주장하지 않습니다. Windows Docker Desktop 사전 관찰에서 진단 증거를 얻었지만 Linux rootless Podman 기준선에는 부적합하고 로컬 image도 byte 단위로 재현되지 않았습니다. Host마다 다른 가변 image를 실행하면 플랫폼 결론이 계속 왜곡됩니다.

## 시험 행렬

| Host 및 runtime | 확인 질문 | 필수 증거 | 상태 |
|---|---|---|---|
| Linux x86-64, rootless Podman | 고정 참조본이 선정 공정 및 소자 case를 재현하는가? | Runtime version, image digest, 전체 transcript, metric, 장애 경로 | 기준선 대기 |
| Windows 11 x64, Docker Desktop WSL2 | Mount, UID, signal, networking, resource limit contract에서 무엇이 다른가? | 같은 입력과 이미지, 진단 bundle, 구조화된 failure | 사전 관찰 완료, 지원 미결정 |
| Windows 11 x64, Podman Machine | `--userns keep-id` 가정 없이 runtime-neutral contract가 동작하는가? | Capability probe 및 adapter trace | 대기 |
| macOS Apple Silicon, Docker Desktop | amd64 이미지를 명시적으로 emulation해 실행할 수 있고 수치 허용 범위를 지키는가? | Architecture identity, emulation flag, metric, runtime 관찰 | 대기 |
| macOS Apple Silicon, Podman Machine | VM mount와 signal 동작에서 무엇이 다른가? | Capability probe, adapter trace, metric | 대기 |
| Linux arm64 compile-only SUPREM | Native 실행을 검토하기 전에 legacy pointer model을 안전하게 compile할 수 있는가? | Compiler output 및 static diagnostic만 사용 | 대기, 릴리스 제외 |

## 관찰한 Windows 사전 실행

[BASE-001 관찰 보고서](base001-reference-observation.md)는 고정 1D boron deck을 강화된 Docker 설정에서 5회 실행한 결과를 기록합니다. Structure와 record count는 모든 실행에서 정확히 같았고 고정 참조 fixture blob과도 일치했습니다. 그러나 모든 실행이 exit code 0과 함께 선언된 command input 오류를 기록했고, 필수 Podman 및 rootless profile을 충족하지 못했으며, cache 없는 image 재빌드에서 다른 digest와 layer가 생성됐습니다. 이 결과는 진단 전용이며 `ineligible` 상태입니다.

## 통과 조건

- 모든 실행은 host, runtime, engine architecture, image digest, emulation 활성 여부를 식별합니다.
- 지원하지 않는 sandbox capability는 실행을 차단하고 조치 가능한 diagnostic을 제공합니다.
- Host 전체에서 같은 정규화 입력과 golden comparator를 사용합니다.
- 공정 topology와 소자 curve gate를 process 종료 상태와 별도로 통과해야 합니다.
- Host path가 암묵적 engine contract가 되면 안 됩니다.

재현 가능한 증거가 있을 때만 결과를 추가합니다. 그 전까지 1.0 host 지원 행렬은 미결정입니다.
