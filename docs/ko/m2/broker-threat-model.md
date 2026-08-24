# M2 샌드박스 브로커 위협 모델

[English](../../en/m2/broker-threat-model.md) | [M2 상태](README.md)

- 상태: **초안, 승인 전**
- 범위: 계약 기반 검토 전용
- 기록일: 2026-08-24

이 문서는 OpenTCAD 샌드박스 브로커가 Docker 또는 Podman 접근 권한을 갖기 전에 해결해야 할 보안 질문을 정의합니다. 현재 저장소에는 브로커 서비스, 제품 런타임 어댑터, 소켓 접근, 솔버 실행 경로가 없습니다.

## 자산과 신뢰 경계

보호 대상은 호스트, 런타임 소켓, 엔진 이미지, 제출 덱, 생성 산출물, 잡 상태, provenance, 자격 증명, 다른 사용자의 잡입니다. 향후 경계는 다음과 같습니다.

`브라우저 -> loopback API -> 워커 -> 타입이 지정된 브로커 요청 -> 브로커 정책 -> RuntimeBackend -> OCI 런타임`

브라우저, API, 워커, 입력 아카이브, 솔버 덱, 컨테이너 출력, 런타임 응답, 남은 런타임 객체는 신뢰하지 않습니다. 검토된 브로커 코드, 승인된 정책 프로필, 불변 이미지 identity, 정확한 런타임 capability만 실행 요청에 참여할 수 있습니다.

## 위협과 필수 통제

| 위협 | 필수 실패 폐쇄 통제 | 현재 기반 |
|---|---|---|
| 셸 또는 명령 주입 | 워커가 제어하는 요청에 명령, 셸, entrypoint, 인자 배열, 런타임 옵션을 포함하지 않음 | `SandboxSpec` 형태로 강제 |
| 변경 가능하거나 바뀐 이미지 | 승인된 digest 고정 index와 platform manifest가 inspect 결과와 일치해야 함 | 모델과 정책이 identity를 강제하지만 실제 inspect는 없음 |
| 호스트 경로 또는 마운트 탈출 | 브로커만 관리 볼륨을 만들고 요청에는 호스트 경로, bind mount, device, 런타임 소켓이 없음 | 모델 형태로 강제 |
| 런타임 소켓 노출 | 별도 검토된 브로커 프로세스만 소켓을 받고 브라우저, API, 워커에는 전달하지 않음 | 아키텍처 규칙만 있으며 브로커는 없음 |
| capability 또는 정책 하향 | 모든 필수 capability를 명시적으로 보고하고 누락되거나 알 수 없는 capability가 있으면 요청 거부 | 정책 테스트로 강제 |
| 아카이브 경로 탈출 또는 특수 파일 | 압축 해제 전에 절대 경로, 상위 경로, 링크, device, 정규화 후 중복 이름, 파일 수 및 크기 초과, byte substitution을 거부 | Canonical 비압축 input/output USTAR stream을 memory에서 검증하며 제품 runtime transfer는 대기 |
| 리소스 또는 출력 서비스 거부 | CPU, 메모리, PID, 시간, 출력, 파일 수, 산출물, tmpfs 상한 고정 | 모델과 정책이 선언 상한을 강제하며 런타임 집행은 대기 |
| 잡 간 접근 | 서버 UUID label, opaque handle, 정확한 잡 소유권, 관리 볼륨 격리, 정확한 산출물 manifest | mock lifecycle이 소유권을 강제하며 런타임 격리는 대기 |
| 남은 상태 또는 orphan 재사용 | 기존 label 객체를 거부하고 생성한 정확한 identity를 사용하며 job별 cleanup을 직렬화하고 container 다음 volume 순서로 정리하며 이미 사라진 상태는 수렴으로 처리한 뒤 orphan 0을 조회 | Process-local lease, concurrent mock reconciliation, 정확한 cancellation query, 결정론적 restart 경계 4곳, SQLite 별도 process hard-exit 증거가 있으며 distributed ownership, runtime 기반 reconciliation, power-loss recovery는 대기 |
| 상태 혼동과 안전하지 않은 재시도 | 연속 broker event를 결정론적 event 및 operation slot으로 mapping하고 원자적 revision CAS, 허용 transition, terminal 불변성, 제한된 recovery scan으로 저장 | Complete-outcome 및 mock 전용 phase-time mapping, partial replay, memory 및 SQLite adapter 공통 conformance, startup admission, write 실패 cleanup, lock redaction, restart recovery test가 있으며 외부 cancellation persistence, retention compaction, backup, distributed fencing은 대기 |
| 진단 정보 노출 | secret과 호스트 경로를 제거하고 정규화된 capability와 error record만 노출 | 공개 event는 raw detail과 비정규 backend 값을 제외하며 raw detail은 repr에서 숨긴 내부 diagnostic에만 존재 |
| backend 의미 차이 | Docker와 Podman 정책을 각각 매핑하고 계약 및 장애 테스트로 동등한 통제를 입증 | capability 어휘는 있으며 adapter는 차단 |

## 보안 불변식

1. 호출자는 raw executable 또는 런타임 옵션을 선택할 수 없습니다.
2. 정책 validator만 `ValidatedSandboxSpec`을 만들 수 있습니다.
3. 실행 가능 프로필은 선언된 모든 capability를 요구하며 경고만 남기는 하향 동작은 없습니다.
4. 이미지 identity는 digest 고정 reference와 정확한 index, platform manifest, platform 값을 사용합니다.
5. 입력과 출력은 호스트 경로가 아닌 단일 파일 이름과 정확한 hash를 사용합니다.
6. 관리 런타임 객체는 정확한 잡 소유권을 가지며 opaque identity로 제거합니다.
7. GitHub Pages는 계속 실행 기능이 없고 브로커 endpoint 또는 자격 증명을 포함하지 않습니다.

## 승인 전에 필요한 오용 사례

- `..`, 절대 경로, 혼합 separator, Unicode normalization collision, 중복 이름, link, device, sparse 확장, 크기 및 개수 폭탄을 포함한 악성 아카이브
- 위조 이미지 응답, 누락 capability, 예상하지 않은 런타임 version, rootless drift, Docker와 Podman flag 차이
- lifecycle 각 단계의 취소, 브로커 재시작, 런타임 재시작, 호스트 재시작, 부분 정리, 남은 label, 동시 정리
- 출력 flood, 산출물 바꿔치기, 잡 간 handle 재사용, 중복 잡 제출, 진단 secret 주입
- 현재의 20회 혼합 반복, 결정론적 memory 기반 crash 경계, SQLite process hard-exit 증거와 별도로 label container 및 volume 0을 증명해야 하는 제품 runtime, host restart, power-loss, distributed-ownership 행렬

## 승인 게이트

승인하려면 M1 corpus green, runtime ADR 승인, 담당자가 명시된 보안 검토, runtime별 policy trace, durable crash reconciliation 증거, 현재 추가된 input/output archive, identity, cancellation, redaction, mock broker state machine test 검토가 필요합니다. 그전까지 RUN-004와 RUN-005는 차단되며 이 초안은 런타임 접근을 허가하지 않습니다.

## 롤백

`backend/app/runtime/`, M2 manifest, M2 문서를 제거하면 제품은 엔진 없는 정적 상태로 돌아갑니다. Contract test는 격리된 임시 SQLite file만 만들고 제거하며 제품은 runtime object, image, database, project, 수치 baseline을 만들지 않습니다.
