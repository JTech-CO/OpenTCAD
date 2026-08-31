# OpenTCAD 아키텍처

[English](../en/architecture.md)

## 제품 모드

OpenTCAD은 안전한 정적 경험, 차단형 로컬 미리보기, 증거로 활성화되는 솔버 제품을 의도적으로 분리합니다.

| 모드 | 실행 위치 | 덱 실행 가능 | 목적 |
|---|---|---:|---|
| 정적 미리보기 | GitHub Pages 또는 일반 정적 호스트 | 아니요 | 워크플로, UI, 용어, 결정론적 참조 시각화 탐색 |
| 로컬 차단형 미리보기 | loopback 전용 동일 출처 웹 서버 | 아니요 | 상태, 자격 증명, 런타임을 만들지 않고 제품 연결 UI 확인 |
| 활성화된 로컬 제품 | loopback 전용 로컬 웹 서버와 OCI 런타임 | 릴리스 활성화 후에만 가능 | 단일 사용자 공정·소자 시뮬레이션 |
| 공유/서버 | 인증과 쿼터가 있는 관리 호스트 | 샌드박스 검증 후 가능 | 수업, 연구실 또는 관리형 서버 |

정적 빌드에는 런타임 자격 증명, 엔진 소켓, 하위 프로세스 브리지, 업로드 코드 실행 또는 숨겨진 솔버 endpoint가 없습니다. 정적 모드에서 덱을 편집하면 브라우저 메모리만 바뀝니다. 차단형 로컬 미리보기는 같은 자산과 제거된 정보만 포함한 상태 endpoint를 제공하지만 영속 상태를 만들거나 native service에 접근하지 않습니다.

## 목표 로컬 흐름

```text
브라우저
  │ 동일 출처 HTTP
  ▼
로컬 API 및 정적 호스트
  ├─ 엄격한 bearer HTTP codec
  ├─ 상한이 있는 실행 및 control lane
  └─ 제거된 정보만 포함한 제품 상태
             │ 타입이 지정된 요청
             ▼
       로컬 제품 서비스
  ├─ recovery 우선 시작
  ├─ maintenance 및 backup coordinator
  ├─ native credential store
  └─ 영속 SQLite 상태와 fencing
             │ SandboxSpec만 전달
             ▼
        샌드박스 브로커
             │ 검증된 OCI 작업
             ▼
 Docker 또는 rootless Podman 어댑터
             │
       잡별 관리 볼륨
      ├─ 승인된 공정 엔진
      ├─ 승인된 재메시 엔진
      └─ 승인된 소자 엔진
```

API는 시뮬레이터를 실행하지 않습니다. 워커는 raw 런타임 명령을 만들지 않습니다. 런타임에는 샌드박스 브로커만 접근하며, 브로커는 임의 이미지, 명령, 환경, 마운트가 아니라 타입과 allowlist로 검증된 요청만 받습니다. 로컬 서비스는 표준 library HTTP와 SQLite를 사용하며 FastAPI, PostgreSQL, Redis를 요구하지 않습니다.

## 제품 활성화 경계

제품 명령은 자산을 읽거나 로컬 directory를 만들고 자격 증명, database, OCI 런타임, socket에 접근하기 전에 증거 기반 M3 매니페스트를 검사합니다. 두 번째로 코드가 소유한 릴리스 프로필이 매니페스트 digest, backend, image, entrypoint와 정확히 일치해야 합니다. 커밋된 릴리스 프로필 집합은 비어 있으므로 운영자 설정이나 매니페스트만 바꿔서는 실행을 활성화할 수 없습니다.

활성화 후에는 사용자별 instance 하나만 실행합니다. API 요청을 받기 전에 영속 recovery를 마치고 예약 backup coordinator를 시작하며 secret이 없는 endpoint record만 기록합니다. 정적 자산과 API 응답은 숫자로 된 하나의 loopback 출처를 공유합니다. 브라우저는 URL fragment로 해당 서비스 실행 동안 유효한 임시 secret을 받고 fragment를 즉시 제거한 뒤 secret을 메모리에만 보관합니다.

## 완화할 수 없는 샌드박스 정책

실제 솔버 잡은 런타임이 다음 항목을 모두 강제하지 못하면 fail closed 해야 합니다.

- 네트워크 차단
- 모든 Linux capability 제거
- no-new-privileges
- 읽기 전용 root filesystem
- 고정 비루트 UID/GID
- 격리된 쓰기 가능 잡 볼륨 정확히 하나
- CPU, 메모리, PID, 시간, 파일 수, 출력량 상한
- host namespace, device, runtime socket, 임의 bind mount 미노출
- digest 고정 이미지와 고정 entrypoint allowlist

SUPREM 입력 덱은 무해한 DSL이 아니라 임의 셸 실행 능력이 있는 입력으로 취급합니다. 브라우저의 사용자 내용을 argv, 이미지 이름, 호스트 경로, 환경 변수 키 또는 entrypoint에 넣지 않습니다.

## 정적 참조 데이터 계약

현재 UI는 솔버 배포가 승인되기 전에 완성 제품의 형태를 검토할 수 있도록 코드가 소유한 결정론적 참조 미리보기 값을 사용합니다. 모든 참조 시각화에는 **솔버 출력이 아님**을 표시합니다. 이 값은 수치 기준선이 아니며 검증 결과로 export할 수 없고 수렴 데이터처럼 제시해서는 안 됩니다.

향후 로컬 엔진이 연결되면 모든 결과에 앱 revision, 런타임 backend와 architecture, 이미지 digest, 엔진 버전, 입력 hash, 수렴 경고, fallback 결정, skipped point를 기록합니다.

## 저장소 방향

```text
frontend/                 정적 호환 React 애플리케이션과 로컬 연결 UI
docs/en/ 및 docs/ko/      한·영 쌍으로 관리하는 제품·엔지니어링 문서
.github/workflows/        CI 및 GitHub Pages 배포

backend/app/product/      증거 게이트와 코드 소유 릴리스 프로필
backend/app/runtime/      Docker, Podman, 정책, stable error, native fencing
backend/app/broker/       영속 lifecycle, cancellation, recovery, archive, backup
backend/app/service/      Loopback host, worker, credentials, scheduler, CLI
config/                   엄격한 운영자 설정 예제
validation/               외부 관찰, comparator, schema, 계약 기록
```

런타임과 서비스 구현 및 계약 test는 들어 있지만 커밋된 제품은 비활성 상태입니다. 활성화된 제품 host만 Docker 또는 Podman에 접근할 수 있습니다. 이 저장소에는 제3자 solver binary, 승인된 solver image 또는 수치 릴리스 corpus가 없습니다.
