# M2 SQLite durable-state 후보

[English](../../en/m2/sqlite-durable-state.md) | [M2 상태](README.md)

- 상태: 후보 adapter 및 recovery 계약 test 완료, 제품 활성화 안 됨
- 작업 항목: RUN-007, BRK-006, BRK-007, BRK-008 확장
- Runtime, solver, service 권한: 변경 없이 비활성
- 비활성 phase-time composition: mock execution 계약 test 완료

## 결정

`SQLiteJobStateStore`는 기존 `DurableJobStateStore` 경계를 구현하는 첫 file-backed 후보입니다. SQLite는 Windows, macOS, Linux의 Python 표준 library에서 사용할 수 있고 단일 장비 local-server 목표에 적합합니다. 이 결정은 multi-host queue를 선택하지 않습니다. 명시적인 mock 전용 composition은 계약 test에서 후보를 열 수 있지만 broker 직접 실행과 모든 제품 경로는 계속 비활성입니다.

Constructor는 local file path만 받습니다. Memory database와 SQLite URI 형식은 거부합니다. Database 위치는 관리자가 소유하는 내부 설정이며 project archive field, request field, host mount 또는 sandbox 입력이 아닙니다.

## Transaction 및 schema 계약

Schema version 3은 append-only `job_events` table을 유지하고 mutable `job_leases` control table을 추가합니다. 모든 event row에는 redacted durable field, `owner_id`, `fencing_token`, 제한된 `lease_duration_ms`, commit된 revision이 들어갑니다. Current lease row에는 정확한 job, operation, owner, token, revision, 절대 expiry가 들어갑니다. Database는 event ID, job-operation-sequence slot, job revision의 고유성과 job별 current lease 하나를 강제합니다. Raw diagnostic, payload, command, secret, runtime 고유 identifier, host path는 저장하지 않습니다.

각 append는 `BEGIN IMMEDIATE`를 사용하고 revision CAS보다 먼저 동일 event replay를 확인하며 transition, owner-generation, lease 규칙을 검증한 뒤 새 revision 하나를 insert하고 current lease를 갱신한 다음 commit합니다. 따라서 concurrent writer는 database 경계에서 직렬화되고 주어진 expected revision은 writer 하나만 충족할 수 있습니다. `renew_ownership()`은 별도 `BEGIN IMMEDIATE` transaction으로 정확한 unexpired lease만 연장하고 event log와 job revision을 바꾸지 않습니다. `verify_ownership()`은 정확한 live owner tuple과 선택적 revision 일치를 요구합니다. 이 read와 이어지는 runtime 호출을 하나의 원자적 동작으로 주장하지 않습니다. WAL mode와 `synchronous=FULL`이 필수입니다. SQLite 및 filesystem message는 stable `store-unavailable` code로 변환하며 공개 exception에 노출하지 않습니다.

`PRAGMA user_version`은 forward-only migration marker입니다.

1. 새 version 0 database는 transaction 하나에서 정확한 version 3 schema로 생성합니다.
2. 정확한 version 1 database는 durable event를 삭제하지 않고 transaction 하나에서 version 2를 거쳐 version 3으로 migration합니다. 과거 operation은 첫 revision 순서에 따라 owner generation이 되고 기존 operation UUID를 migration된 owner UUID로 사용합니다.
3. 정확한 version 2 database는 transaction 하나에서 version 3으로 migration합니다. 기존 event에는 기본 lease duration을 추가하고 각 최신 owner에는 보수적으로 expired lease row를 만듭니다.
4. 정확한 version 3 database는 두 table 정의가 모두 일치할 때만 허용합니다.
5. 알 수 없는 상위 version이나 일치하지 않는 table 정의는 fail closed 처리합니다.
6. 파괴적 migration, downgrade, best-effort migration은 자동 실행하지 않습니다.

## 공통 conformance 및 hard-exit 증거

SQLite 후보는 변경하지 않은 공통 adapter conformance case 10개를 실행합니다. Empty read, 새 adapter handle의 commit 가시성, idempotent replay, event 및 operation slot conflict, concurrent CAS, bounded recovery pagination, owner takeover 및 재개방 뒤 stale token 거부, 재개방 뒤에도 보이는 revision-neutral lease renewal, expired-owner 거부, live-owner recovery 거부, cancellation 선점, expiry 뒤 recovery takeover를 검증합니다.

별도 Python process가 file을 열고 `CrashRecoveryCoordinator`로 token 2의 `cleaning` claim을 revision 4에 commit한 뒤 `after-claim` checkpoint에서 `os._exit(91)`을 호출합니다. Parent process의 새 adapter가 commit된 revision을 확인합니다. 의도적으로 짧게 설정한 child lease가 만료된 뒤 새로운 recovery owner는 token 3으로 revision 5에서 takeover하고 정확한 job을 reconcile한 뒤 성공을 만들어 내지 않고 revision 6에서 `failed:stale-state`로 닫습니다.

이는 process hard-exit, 저장된 lease expiry, store 재개방 뒤 ownership 이전 증거입니다. 별도 [조정된 offline snapshot 계약](sqlite-offline-snapshot-restore.md)은 후보 pair backup, 신규 target restore, recovery 재개를 검증합니다. 두 계약 모두 host 전원 손실 내성, filesystem 손상 repair, 제품 backup operation, 제품 runtime의 native fencing, bounded clock skew, multi-host operation을 주장하지 않습니다.

## Retention 및 recovery 정책

Version 3은 자동 삭제나 compaction을 수행하지 않습니다. Lease renewal은 current control row만 변경하고 commit된 job event는 append-only 상태를 유지합니다. 과거 row를 제거하면 event-ID 및 operation-slot idempotency 증거와 audit sequence가 사라집니다. 향후 retention 설계는 삭제를 활성화하기 전에 latest snapshot, event-ID tombstone, operation-slot tombstone, revision 단조 증가, backup 및 restore 동작, recovery scan 의미를 보존해야 합니다.

Database는 후보 test artifact로 남습니다. 명시적인 mock 전용 composition은 startup recovery 뒤 execution, 외부 cancellation, recovery, owner-generation event를 여기에 쓰지만 broker 직접 호출과 service는 database를 열지 않습니다. 제품 runtime 또는 solver operation도 이에 의존하지 않습니다.

## 다음 게이트

구현된 store ownership 규칙은 [durable operation ownership 및 fencing](durable-operation-ownership.md)과 [owner lease, liveness, runtime fencing](owner-lease-runtime-fencing.md)에 설명합니다. 제품 runtime의 native token 저장과 강제, distributed coordination, clock-skew policy, 제품 backup scheduling 및 인증된 restore, power-loss 자격 검증, 제품 Docker 및 Podman adapter, runtime socket, solver 실행은 별도 gate 작업으로 남습니다.
