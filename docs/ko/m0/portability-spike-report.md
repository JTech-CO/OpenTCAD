# M0 이식성 spike 보고서

[English](../../en/m0/portability-spike-report.md) | [M0 상태](README.md)

## 상태

아직 이식성 결과를 주장하지 않습니다. Spike 행렬은 준비했지만 사용 권한과 재현성이 확인된 Linux 솔버 기준선이 없어 실행은 대기 상태입니다. Host마다 다른 가변 이미지를 실행하면 플랫폼 결론이 왜곡됩니다.

## 시험 행렬

| Host 및 runtime | 확인 질문 | 필수 증거 | 상태 |
|---|---|---|---|
| Linux x86-64, rootless Podman | 고정 참조본이 선정 공정 및 소자 case를 재현하는가? | Runtime version, image digest, 전체 transcript, metric, 장애 경로 | 기준선 대기 |
| Windows 11 x64, Docker Desktop WSL2 | Mount, UID, signal, networking, resource limit contract에서 무엇이 다른가? | 같은 입력과 이미지, 진단 bundle, 구조화된 failure | 대기 |
| Windows 11 x64, Podman Machine | `--userns keep-id` 가정 없이 runtime-neutral contract가 동작하는가? | Capability probe 및 adapter trace | 대기 |
| macOS Apple Silicon, Docker Desktop | amd64 이미지를 명시적으로 emulation해 실행할 수 있고 수치 허용 범위를 지키는가? | Architecture identity, emulation flag, metric, runtime 관찰 | 대기 |
| macOS Apple Silicon, Podman Machine | VM mount와 signal 동작에서 무엇이 다른가? | Capability probe, adapter trace, metric | 대기 |
| Linux arm64 compile-only SUPREM | Native 실행을 검토하기 전에 legacy pointer model을 안전하게 compile할 수 있는가? | Compiler output 및 static diagnostic만 사용 | 대기, 릴리스 제외 |

## 통과 조건

- 모든 실행은 host, runtime, engine architecture, image digest, emulation 활성 여부를 식별합니다.
- 지원하지 않는 sandbox capability는 실행을 차단하고 조치 가능한 diagnostic을 제공합니다.
- Host 전체에서 같은 정규화 입력과 golden comparator를 사용합니다.
- 공정 topology와 소자 curve gate를 process 종료 상태와 별도로 통과해야 합니다.
- Host path가 암묵적 engine contract가 되면 안 됩니다.

재현 가능한 증거가 있을 때만 결과를 추가합니다. 그 전까지 1.0 host 지원 행렬은 미결정입니다.
