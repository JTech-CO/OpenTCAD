# M2 조정된 SQLite offline snapshot 및 restore

[English](../../en/m2/sqlite-offline-snapshot-restore.md) | [M2 상태](README.md)

- 상태: local offline 후보 test 완료, 제품 비활성
- Payload: broker state schema v3 및 runtime fence authority schema v1
- 공개 방식: manifest를 마지막에 기록하는 snapshot directory와 restore record를 마지막에 기록하는 신규 directory
- Live backup: 미지원, 인증 application-service wrapper: 구현했으나 제품 비활성
- Durable publication barrier: 구현, abrupt power-loss 자격 검증: 미달성

## 경계

`SQLiteOfflineSnapshotManager`는 일반 실행 중 두 SQLite database의 commit이 원자적 동작이라고 주장하지 않고 두 database를 조정합니다. 호출자는 broker admission, runtime operation, database writer가 모두 중지됐다는 typed quiescence assertion을 제공해야 합니다. 후보는 이 assertion 형식을 검사하지만 다른 process의 종료를 발견하거나 강제할 수 없습니다. 따라서 `SQLITE_OFFLINE_SNAPSHOT_LIVE_WRITES_SUPPORTED`는 `False`로 유지됩니다.

Snapshot 생성은 `BEGIN IMMEDIATE`로 broker state write lock을 먼저 얻고 authority write lock을 다음에 얻습니다. 이 순서는 새 state write를 먼저 차단한 뒤 authority 변경을 고정하므로 authority는 commit된 state와 같거나 뒤에 있을 수 있지만 앞설 수 없다는 기존 규칙을 보존합니다. 두 lock을 유지한 동안 Python SQLite backup API가 독립 database payload를 생성합니다. WAL 및 shared-memory sidecar는 복사하지 않습니다.

Source는 이미 WAL mode와 `synchronous=FULL`을 사용하는 정확한 schema v3 state database 및 정확한 schema v1 authority database여야 합니다. 누락, lock, 손상, 알 수 없는 schema, 구조 불일치는 path가 노출되지 않는 stable error로 실패합니다. 이 component는 누락된 source를 초기화하지 않습니다.

## Canonical bundle

공개된 bundle은 다음 regular file 3개만 가진 directory이고 link는 허용하지 않습니다.

| File | 목적 |
|---|---|
| `broker-state.sqlite3` | Append-only event 및 current lease row의 SQLite backup |
| `runtime-fence.sqlite3` | Job별 최고 runtime generation의 SQLite backup |
| `snapshot.json` | 두 payload 뒤에 기록하는 canonical UTF-8 JSON manifest |

Schema v1 manifest는 고정 key, canonical JSON encoding, canonical snapshot UUID, 호출자가 제공한 source-instance UUID, 양의 signed 64-bit sequence, quiescence UUID, 정확한 schema version, byte 길이, SHA-256, state 및 authority job count를 가집니다. 중복 JSON key, noncanonical encoding, 추가 file, link, 누락 file, 1 GiB 초과 payload, 크기 또는 hash drift, integrity-check 실패, schema drift는 실패 폐쇄됩니다.

SHA-256만으로는 signature 또는 authenticity 증거가 되지 않습니다. 별도 [인증된 backup-control 계약](authenticated-backup-control.md)은 이 하위 3개 file format을 바꾸지 않고 canonical manifest를 HMAC-SHA256으로 감싸 서명합니다.

## Pair 일관성

검증은 모든 state row, job별 연속 revision, 허용 state transition, owner generation 연속성, current lease 일치, 모든 authority row, 정확한 job, owner, token identity를 검사합니다. 각 authority row는 같은 owner를 가진 기존 state generation을 참조해야 합니다. 최신 state token보다 앞선 authority는 `state-authority-conflict`로 거부됩니다. 누락되거나 오래된 authority row는 기존 activation-gap recovery 계약이 다음 generation을 안전하게 claim할 수 있으므로 허용됩니다.

이 semantic 규칙은 operator가 신뢰되지 않은 hash를 다시 작성해도 오래된 state database와 새로운 authority database의 조합을 탐지합니다. 독립적으로 위조한 두 file이 주장한 installation에서 생성됐다는 사실까지 증명하지는 않습니다.

## Restore 및 rollback policy

Restore에는 호출자가 보유한 trust anchor 3개가 필요합니다. 정확한 snapshot UUID, 정확한 source-instance UUID, 허용할 최소 snapshot sequence입니다. Identity 불일치와 floor보다 낮은 sequence는 실패 폐쇄됩니다. 하위 manager는 계속 caller floor를 받습니다. 별도 backup-control DB는 인증 import 전에 source별 floor를 저장하고 증가시키지만 권한을 가진 공격자의 외부 control DB rollback은 보장 밖에 있습니다.

Target은 새 directory여야 합니다. 기존 target은 덮어쓰지 않습니다. Manager는 복사 전에 bundle을 검사하고 두 database를 sibling staging directory에 restore한 뒤 복원된 pair를 다시 검사하며 canonical `restore.json`을 기록하고 모든 file을 flush한 뒤 platform durability barrier로 directory 전체를 공개합니다. 결과는 기존 adapter가 다시 열 수 있는 고정 state 및 authority path를 제공합니다. 이후 startup recovery는 만료된 lease와 허용된 state-ahead-of-authority gap을 다음 fencing token으로 처리합니다.

## Crash 경계 및 증거

결정론적 checkpoint 8곳은 생성 및 restore의 각 database copy, metadata write, directory 공개를 포함합니다. 별도 process 하나는 snapshot database 2개를 복사한 뒤 manifest 기록 전에 hard exit하며 최종 bundle path는 생성되지 않습니다. 다른 process는 첫 restore database를 복사한 뒤 hard exit하며 최종 restore path는 생성되지 않습니다. Hard exit 뒤 staging directory가 남을 수 있지만 validator는 이를 허용하지 않고 같은 identity의 재시도도 operator가 정확한 staging directory를 검사하고 제거할 때까지 실패 폐쇄됩니다.

집중 test 7개는 offline gate 및 redaction, canonical round trip, 복원 후 recovery generation 증가, torn, extra, tampered bundle 거부, hash를 다시 기록한 mixed-pair negative control, identity 및 rollback floor, 신규 target 강제, lock 및 알 수 없는 source, process hard-exit 경계 2곳을 검사합니다. 이 test는 임시 local SQLite file과 strict mock recovery 경로만 사용합니다.

## 제품 게이트

하위 manager는 계속 native runtime object를 capture하지 않고 실행 중 broker를 조정하지 않으며 transport caller 인증, corruption repair, live installation 덮어쓰기, multi-host coordination을 제공하지 않습니다. 별도 application-service 후보는 maintenance admission, 인증 export/import, durable floor 저장, interval schedule 상태, platform publication barrier를 추가하지만 현재 broker operation은 자동 등록되지 않고 실제 abrupt-power-loss evidence도 없습니다. 제품 Docker 및 Podman quiescence, local launcher 및 command 연결, OS key storage, 자동 wake-up, retention UX, native object reconciliation, platform power-cut matrix는 계속 gate 상태입니다. 사용자 대상 command와 lifecycle의 제품 연결은 M3 책임으로 남습니다.
