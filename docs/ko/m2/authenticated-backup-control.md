# M2 인증된 backup control 및 durability

[English](../../en/m2/authenticated-backup-control.md) | [M2 상태](README.md)

- 상태: local application-service 후보 test 완료, 제품 비활성
- Payload 인증: canonical HMAC-SHA256 export 및 import record
- 조정: durable maintenance admission drain 및 fenced maintenance lease
- Rollback 방지: 별도 SQLite control database의 단조 증가 floor
- 예약 실행: durable interval, occurrence, claim, retry 상태 및 자동 삭제 없음
- 갑작스러운 전원 손실 자격 검증: evidence 계약 구현, 자격 evidence 없음

## 신뢰 경계

`AuthenticatedSQLiteBackupService`는 향후 loopback 전용 local server가 호출할 application service입니다. HTTP endpoint가 아니며 network session을 인증하지 않습니다. 여기서 인증은 저장 데이터에 적용됩니다. 주입된 `HMACBackupKeyring`은 내부 snapshot manifest를 commit하는 canonical export metadata에 서명하고, 그 결과 인증된 내부 manifest는 두 SQLite payload hash를 commit합니다. Import는 내부 identity를 신뢰하거나 데이터를 복원하기 전에 외부 MAC을 검사합니다. 알 수 없는 key, malformed 또는 noncanonical record, 중복 JSON key, payload 치환, extra entry, 서명 record와 내부 identity 불일치는 path를 노출하지 않는 error로 실패 폐쇄됩니다.

Export format은 database 내용을 암호화하지 않습니다. Test key는 fixture일 뿐입니다. 제품 연결은 OS credential facility에서 key를 얻고 key file permission을 제한하며 제한된 verification key를 유지해 rotation을 지원하고 local transport를 별도로 인증 및 권한 검사해야 합니다. HMAC secret 또는 control DB와 설정된 secret 양쪽의 write 권한을 가진 호출자는 trusted computing base 안에 있습니다.

## Durable control database

`SQLiteBackupControlStore`는 WAL mode, `synchronous=FULL`, 정확한 schema 검사, `BEGIN IMMEDIATE` mutation, 고정 installation UUID를 사용하는 schema v1 local SQLite database입니다. Export하는 state-authority pair에는 의도적으로 포함하지 않습니다. 다음 정보를 저장합니다.

- Singleton maintenance phase와 단조 증가 maintenance generation
- Offline 전 drain해야 하는 leased operation admission
- 단조 할당 snapshot sequence와 idempotent snapshot reservation
- Source installation별 restore floor
- Durable backup schedule, pending occurrence, claim lease, completion 상태

Maintenance state machine은 `open -> draining -> offline -> open`입니다. Maintenance 시작은 새 admission을 원자적으로 닫습니다. 기존 등록 operation이 종료되거나 만료된 뒤 정확한 maintenance owner와 generation만 installation을 offline으로 전환할 수 있습니다. 만료된 maintenance owner는 gate를 다시 열 수 없고 successor가 다음 generation으로 takeover해야 합니다. Export와 import는 최종 공개 전에 정확한 offline lease를 다시 검사합니다.

이 계약은 control store에 참여한 operation의 quiescence만 증명합니다. Admission을 우회한 직접 SQLite writer, native runtime operation, 현재 broker call은 보장 밖에 있습니다. 기능을 활성화하기 전에 제품 composition과 transport가 모든 state 및 runtime operation을 등록하고 admission heartbeat를 유지해야 합니다.

## 인증된 export 및 import

인증된 export directory는 정확히 `export.json`과 `snapshot/`만 포함합니다. `export.json`은 HMAC algorithm과 key, snapshot UUID, 보호된 source UUID, 단조 sequence, canonical 내부 `snapshot.json`의 SHA-256을 식별하며 format 전용 domain separator로 MAC을 계산합니다. 내부 snapshot은 기존의 정확한 3개 file state-authority 계약을 유지합니다.

Export는 maintenance에 진입해 admission을 drain하고 sequence를 durable하게 예약한 뒤 lock된 pair snapshot을 생성합니다. 그 다음 `export.json`을 기록하고 sync한 뒤 완전한 외부 directory를 공개합니다. 같은 snapshot UUID의 재시도는 같은 reservation을 재사용합니다. 공개 뒤 재시도는 기존 인증 export를 검사하고 덮어쓰지 않은 채 완료 상태로 기록합니다. 기존 staging 경로가 충돌하면 호출자 소유 내용을 삭제하지 않고 실패합니다. 갑작스러운 process 종료가 신뢰 가능한 cleanup marker 없이 staging을 남길 수 있으므로 재시도 전에 해당 경로를 검토하고 명시적으로 제거해야 합니다.

Import는 export를 인증 및 검사하고 maintenance에 진입한 뒤 다시 검사하며 어느 database도 복사하기 전에 외부 restore floor를 증가시킵니다. 신규 nested directory에만 restore하고 export record 및 모든 restored file을 포함하는 두 번째 인증 record를 기록한 뒤 완전한 외부 directory 하나를 공개합니다. Floor를 먼저 올리면 중단된 restore 뒤 과거 backup이 보수적으로 거부될 수 있지만 restore를 공개한 뒤 더 오래된 floor가 남지는 않습니다. 같은 인증 snapshot은 같은 floor에서 재시도할 수 있고 같은 source sequence를 주장하는 다른 snapshot은 거부됩니다.

Control DB가 온전하면 floor는 과거 export bundle을 통한 rollback을 방지합니다. 권한을 가진 공격자가 control DB 자체를 교체하거나 rollback하는 상황은 막지 못합니다. 더 강한 공격자를 방어하려면 hardware 기반 monotonic storage 또는 독립 복제된 control service가 필요합니다.

## 예약 backup

`ScheduledSQLiteBackupRunner`는 local server가 호출할 때 due occurrence 하나를 실행합니다. Control DB는 최소 60초 interval, 다음 due time, leased runner claim 하나, pending snapshot UUID 및 sequence를 저장합니다. Claim 재시도는 pending reservation을 재사용합니다. 완료와 release에는 정확한 token, owner, 예정 occurrence, reservation, 저장 expiry, 미만료 claim이 필요하며 완료 시 저장된 예정 occurrence를 기준으로 다음 due를 계산해 timer drift 누적을 막습니다. Windows-safe directory 이름에는 고정 폭 sequence를 사용하며 서명 record가 UUID를 보존합니다.

Wake-up, 사용자 대상 command, destination capacity 검사, notification, retention 삭제는 구현하지 않았습니다. Retention policy는 `monotonic-no-automatic-delete`로 명시되어 runner가 사용자 backup을 삭제하지 않습니다.

## 공개 및 전원 손실 evidence

공개 전에 모든 database 및 metadata file을 flush하고 symbolic link와 Windows junction을 거부합니다. POSIX는 같은 parent 안에서 directory를 rename한 뒤 parent directory에 `fsync`를 수행합니다. macOS는 regular file에 `F_FULLFSYNC`도 요청합니다. Windows는 `MOVEFILE_WRITE_THROUGH`를 지정한 `MoveFileExW`를 사용합니다. 기존 offline manager도 같은 barrier를 사용합니다.

새 별도 process hard exit 4곳은 sequence reservation, export 공개, restore floor 증가, import 공개를 검사합니다. 기존 state, authority, snapshot case와 함께 process crash 공개 및 restart 동작을 증명합니다. 이는 갑작스러운 host 전원 손실 test가 아닙니다.

`PowerLossQualificationEvidence`는 control, copy, record, publication cut point 10곳 전체, cut point별 최소 10회의 실제 abrupt power cut, 기록된 storage 및 write-cache 설정, 모든 cut 뒤 완료된 reboot, partial publication과 SQLite integrity failure 및 rollback violation 0건을 요구합니다. Windows, macOS, Linux에 대한 이런 evidence는 아직 commit되지 않았으므로 `external_power_loss_qualified`와 모든 제품 활성화 flag는 `False`입니다.

Durability 가정은 정상 동작하는 flush primitive와 filesystem 동작에 의존한다는 SQLite 문서, Python `fsync` 계약, Microsoft의 write-through directory move 문서를 따릅니다. 실제 시험 storage stack의 전원을 물리적으로 차단하는 platform matrix만 이 gate를 닫을 수 있습니다.

## 남은 제품 gate

Application service, control schema, 인증 format, scheduler state machine, publication barrier, process-crash recovery는 구현 및 test했습니다. Broker admission 연결, local 인증 transport, OS credential store 통합, native Docker 및 Podman quiescence, 원자적 installation 활성화, retention UX, capacity policy, multi-host coordination, 보호된 control store rollback 저항성, 실제 abrupt-power-loss evidence는 계속 gate 상태입니다.

## 참고 자료

- [SQLite atomic commit 및 hardware 가정](https://www.sqlite.org/atomiccommit.html)
- [SQLite write-ahead logging](https://www.sqlite.org/wal.html)
- [Python `os.fsync`](https://docs.python.org/3/library/os.html#os.fsync)
- [Microsoft `MoveFileEx` 및 `MOVEFILE_WRITE_THROUGH`](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexa)
