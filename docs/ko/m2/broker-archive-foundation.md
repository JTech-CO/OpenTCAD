# M2 broker 및 canonical archive 기반

[English](../../en/m2/broker-archive-foundation.md) | [M2 상태](README.md)

- 상태: `gated-active`, mock 전용
- 작업 항목: BRK-001, BRK-003, BRK-004, BRK-006 기반
- 제품 runtime 접근: 승인 없음

이번 범위는 broker 계약 테스트를 위한 내부 Python library를 추가합니다. HTTP, IPC, socket service를 노출하지 않고 subprocess를 호출하지 않으며 runtime에 접근하지 않습니다. Archive member를 host filesystem에 쓰거나 solver를 실행할 수도 없습니다. Docker가 실행 중이어도 이 경계는 바뀌지 않습니다.

## Canonical input archive

API에서 broker로 전달하는 형식은 결정론적인 비압축 USTAR byte stream 하나입니다. Builder와 broker 측 validator는 다음 항목을 모두 요구합니다.

- SHA-256 및 byte 길이가 있는 정확한 순서의 `InputFile` manifest
- USTAR 기준 최대 100 byte인 평면 ASCII 이름
- 절대 경로, separator, 상위 경로, case-fold collision, 중복 없음
- 고정 mode `0400`, UID/GID `65534`, time `0`, 빈 owner name을 사용하는 regular file만 허용
- 정확한 file-count, 전체 content, archive stream 상한
- gzip 등 압축, PAX metadata, sparse file, symlink, hardlink, directory, FIFO, device 금지
- canonical archive를 byte 단위로 다시 만들었을 때 완전히 일치해야 하며 다른 header와 trailing data는 거부

검증은 memory에서만 수행합니다. `tarfile.extract()`와 `extractall()`은 호출하지 않습니다. 검증이 성공해야 `ValidatedInputArchive`를 만들 수 있으며 이 policy 전용 타입만 `RuntimeBackend.stage_inputs` 경계를 통과합니다.

## Mock broker state machine

`SandboxBroker.execute()`의 계약 순서는 다음과 같습니다.

1. Backend를 probe하고 unavailable 또는 degraded health를 거부합니다.
2. Runtime object를 만들기 전에 `SandboxPolicy`와 canonical archive를 검증합니다.
3. 승인 image를 확인하고 관리 volume 하나를 만든 뒤 검증 archive를 stage하며 container 하나를 생성, 시작, 대기합니다.
4. 성공 terminal result에서만 신뢰되지 않은 output archive를 수집하고 정확한 canonical byte와 manifest 일치를 요구합니다.
5. 필요하면 실행 중 container를 kill하고 container 다음 volume 순서로 제거한 뒤 job identity를 다시 조회합니다.
6. Stable하고 redacted된 error, phase, retry, state, result, artifact, cleanup record만 반환합니다.

`reconcile()`은 job identity 하나의 기존 managed object를 제거합니다. 정확한 container 제거를 먼저 시도하고 state가 요구하면 실행 중 container를 kill한 뒤 volume을 제거하고 남은 개수를 보고합니다.

## 검증된 통제

의존성이 없는 suite는 input/output 악성 이름, link, device, 압축, metadata, trailing byte, 개수, 크기, hash, substitution, case collision을 검사합니다. Broker test는 성공, capability 하향, object 생성 전 invalid archive, wait 실패, 누락 artifact, 기존 running job reconciliation, 20회 혼합 반복, 의도적으로 정리를 누락하는 backend를 포함합니다. 누락 negative control은 managed object가 남으면 cleanup 성공으로 보고할 수 없음을 입증합니다.

## 남은 경계

함께 제공하는 [output, cancellation, redaction 기반](output-cancellation-redaction.md)은 artifact byte를 검증하고 cancellation identity와 공개 diagnostic을 고정합니다. [SQLite durable-state 후보](sqlite-durable-state.md)는 제품을 활성화하지 않고 file-backed state와 process hard-exit recovery를 증명합니다. 별도 비활성 mock 전용 composition은 startup recovery 뒤 execution과 외부 cancellation phase event를 저장하며 자세한 계약은 [durable external cancellation 중재](durable-cancellation-arbitration.md)에 있습니다. Docker 또는 Podman 제품 adapter, broker service transport, runtime detection, worker integration, 외부 cancellation transport는 아직 없습니다. 실제 runtime 작업은 M2 진입 조건과 승인된 immutable engine profile이 생길 때까지 차단합니다.
