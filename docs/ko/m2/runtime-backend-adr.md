# ADR: RuntimeBackend contract 경계

[English](../../en/m2/runtime-backend-adr.md) | [M2 상태](README.md)

- 상태: 제안
- 결정 범위: RUN-002 contract 기반
- 제품 adapter 승인: 없음

## 배경

참조 시스템은 domain 작업을 Podman 전용 동작과 결합합니다. OpenTCAD은 host 또는 runtime 분기를 worker 곳곳에 퍼뜨리지 않고 Docker와 rootless Podman을 지원해야 합니다. SUPREM input은 shell 동작을 실행할 수 있으므로 runtime 편의를 위해 sandbox 경계를 약화할 수 없습니다.

M1 수치 및 권리 게이트는 계속 열려 있습니다. 따라서 이 ADR은 검토를 위해 엔진 독립 contract를 고정하지만 Docker 또는 Podman 접근을 소유하는 backend를 허가하지 않습니다.

## 제안 결정

1. `RuntimeBackend`는 향후 sandbox broker가 소유하는 비동기 Python protocol입니다.
2. Worker는 `SandboxSpec`만 제출하며 raw runtime operation을 제출할 수 없습니다.
3. `SandboxPolicy`는 profile, image, input, output, limit, capability 검사가 모두 통과한 뒤에만 spec을 `ValidatedSandboxSpec`으로 변환합니다.
4. Backend별 option mapping은 분리된 Docker 및 Podman module 내부에 둡니다.
5. Volume과 container ID는 opaque handle입니다. Domain code는 host path 또는 engine-native ID를 보지 않습니다.
6. 경계를 통과하는 모든 실패는 stable code, phase, retry disposition, backend ID를 사용합니다. Locale에 따라 달라지는 CLI text는 진단 자료이며 control flow가 아닙니다.
7. 필수 capability 누락은 validation 단계의 종료 오류입니다. 조용한 downgrade는 금지합니다.
8. Runtime image build는 job broker 범위 밖입니다. Job은 engine profile이 승인한 identity만 inspect하고 ensure할 수 있습니다.

## Contract operation

| 영역 | Operation | 경계 |
|---|---|---|
| Runtime | `probe` | 정규화한 health, version, OS, architecture, rootless 상태, capability |
| Image | `inspect_image`, `ensure_image` | Digest 고정 `ImageIdentity`만 사용 |
| Volume | `create_volume`, `stage_inputs`, `remove_volume` | Server UUID 및 validated spec 사용, host path 없음 |
| Container | `create_container`, `start`, `wait`, `kill`, `remove_container` | Validated spec 및 opaque handle만 사용 |
| Artifact | `collect_artifacts` | 예상 이름, hash, 개수, byte limit 적용 |
| Repair | `list_managed` | 정확한 cleanup을 위한 label 범위 관리 객체 |

## 필수 실행 capability

Image inspect 및 digest 검증, managed volume, 검증된 input 및 artifact transfer, container lifecycle, bounded output, CPU, memory, PID, time limit, network none, 전체 capability 제거, no-new-privileges, read-only root, writable tmpfs 통제, 고정 non-root user, label, orphan query는 필수입니다.

Image pull은 별도로 보고합니다. 승인 image가 이미 있을 때 pull capability가 없다고 실행 정책을 약화하지는 않습니다. Image를 inspect하고 identity를 맞출 수 없으면 거부합니다.

## Runtime별 매핑

같은 policy가 같은 flag를 의미하지는 않습니다. M0 OCI 관찰에서 검토된 임시 filesystem 동작을 맞추려면 Podman에 명시적인 read-only tmpfs 통제가 필요함을 확인했습니다. 향후 adapter는 이 capability를 보고하고 자체 매핑을 구현해야 합니다. Domain worker는 Docker, Podman, Windows, WSL 또는 Podman Machine으로 분기할 수 없습니다.

## 탐지 및 override

Runtime 자동 탐지는 RUN-006으로 미룹니다. 향후 결정은 결정론적 우선순위, 명시적 관리자 override, 정규화된 doctor output, stable unavailable error를 사용해야 합니다. Contract 기반은 host를 inspect하거나 runtime을 선택하지 않습니다.

## 결과

- Socket을 추가하기 전에 strict memory backend로 broker를 시험할 수 있습니다.
- 제품 adapter는 lifecycle 및 error test를 공유하지만 argument 또는 API 매핑은 분리합니다.
- 새 capability field에는 contract 및 policy 검토가 필요합니다.
- Canonical input/output archive byte 검증, 고정 job identity, typed cancellation, 공개/내부 diagnostic 분리를 mock broker 기반에 구현했으며 제품 runtime transfer와 durable state는 별도 gate 상태 책임으로 남습니다.
- 필수 검토와 M2 진입 증거가 생기기 전에는 이 제안을 승인 상태로 바꿀 수 없습니다.

## Rollback

`backend/app/runtime/`과 M2 manifest를 삭제하면 engine-free 제품 상태로 돌아갑니다. 이 기반은 database, 사용자 project, runtime object, image 또는 baseline을 만들지 않습니다.
