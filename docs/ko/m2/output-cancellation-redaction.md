# M2 output, cancellation, redaction 기반

[English](../../en/m2/output-cancellation-redaction.md) | [M2 상태](README.md)

- 상태: `gated-active`, mock 전용
- 작업 항목: BRK-004 확장, BRK-007, BRK-008 기반
- 제품 runtime 접근: 허용하지 않음

이 범위는 service, runtime socket, subprocess, solver, host 압축 해제, Docker 및 Podman 제품 adapter를 추가하지 않고 내부 broker 계약을 강화합니다.

## Canonical output archive

성공한 mock 실행은 신뢰된 record 목록이 아니라 신뢰되지 않은 `RawArtifactArchive`를 반환합니다. Broker는 실제 byte를 승인된 output 이름과 runtime이 보고한 `ArtifactRecord` 값에 대조한 뒤에만 `ValidatedArtifactArchive`를 생성합니다.

Output archive는 input archive와 동일한 결정론적 비압축 USTAR metadata를 사용합니다. 검증은 memory에서만 수행하며 대체 metadata, 압축, traversal, separator, Unicode 이름, link, device, directory, FIFO, sparse entry, case-fold collision, 개수 또는 크기 초과, hash 치환, 누락 또는 추가 member, trailing byte를 거부합니다. 빈 regular output 파일은 허용하며 정확한 SHA-256 record를 생성합니다.

## Cancellation identity

`JobIdentity`는 canonical server job UUID로만 생성합니다. 다음 값이 고정됩니다.

- label: `tcad.job_id=<job UUID>`
- object 이름: `opentcad-job-<job UUID>`
- managed volume 이름: `opentcad-job-<job UUID>-data`

SUPREM, remesh, DEVSIM은 동일한 생성 규칙을 사용합니다. Kind, caller text, runtime-native ID, host path, raw object 이름은 cancellation ownership을 바꿀 수 없습니다.

`SandboxBroker.cancel()`은 정확한 job UUID로 조회하고 cross-job handle과 모호한 object 집합을 거부하며 `TerminationReason.CANCELLATION`을 전달합니다. Cancelled terminal classification을 요구하고 container 다음 volume 순서로 제거한 뒤 managed object 0개를 다시 확인합니다.

## Structured public record와 내부 diagnostic

공개 broker error에는 stable code, phase, retry disposition, 정규화된 backend ID만 포함합니다. 공개 event에는 sequence, state, phase, stable code만 포함합니다. Archive byte, raw backend 값, locale 의존 message, secret, host path는 repr과 공개 dictionary에 포함하지 않습니다.

`InternalDiagnostic`은 신뢰된 in-process diagnostic sink만을 위해 raw backend detail을 유지합니다. 이 객체의 repr도 raw field를 숨깁니다. 이 기능은 durable logging이 아니며 외부 diagnostic endpoint를 제공하지 않습니다.

## 검증된 통제

Dependency-free suite는 현재 test 121개를 포함합니다. 위 output, identity, redaction 통제에 더해 execution cancellation checkpoint 11곳 전체, 잘못된 identity 및 비정상 signal, concurrent cleanup 직렬화, 이미 사라진 object 수렴, durable-state revision CAS, event idempotency, transition 안전성, recovery scan, redacted owner UUID 및 fencing-token 저장, startup admission, phase-time persistence, stale-owner outcome, revision-neutral lease renewal, expiry 거부, strict runtime fencing, 부분 write cleanup을 검사합니다. 자세한 내용은 [lifecycle cancellation, cleanup, state 계약](lifecycle-cleanup-state.md)에 있습니다.

## 남은 경계

제품 runtime adapter, broker service transport, runtime detection, worker integration, 외부 cancellation transport, solver 실행, runtime socket 접근은 아직 없습니다. Phase 지정 주입, process-local cleanup idempotence, mock 전용 durable external cancellation 중재는 구현했습니다. 비활성 SQLite 후보는 정규화 intent와 restart-safe 수렴을 기록하지만 제품 활성화는 gate 상태로 남습니다.
