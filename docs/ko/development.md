# 개발

[English](../en/development.md)

## 요구사항

- Node.js 22 LTS 또는 24 LTS
- npm 10 이상
- M2 계약 테스트용 Python 3.12부터 3.14
- Git

컨테이너 런타임, Python service, 외부 database server 또는 solver는 필요하지 않습니다. Python은 의존성이 없는 M2 계약 test만 실행하며 SQLite 후보 test는 표준 library와 격리된 임시 file을 사용합니다.

## 설정과 명령

```bash
npm install
npm run dev
```

개발 서버는 Vite를 사용합니다. 배포 전 품질 게이트는 다음과 같습니다.

```bash
npm run lint
npm run test
npm run check:m2
npm run build
```

`npm run preview`는 배포 번들을 `127.0.0.1`에서 제공합니다. 빌드는 상대 자산 URL을 사용하므로 GitHub 저장소 하위 경로와 일반 로컬 정적 서버에서 같은 산출물을 실행할 수 있습니다.

## 프런트엔드 규칙

- 사용자에게 보이는 문자열은 모두 `frontend/src/i18n.ts`에 두고 영어와 한국어를 함께 제공합니다.
- 사용자가 입력 중인 상태는 명시적 검증 전까지 문자열로 유지하며 숫자 중간 상태를 즉시 변환하지 않습니다.
- 편집 가능한 label에서 안정적인 내부 ID를 만들지 않습니다.
- loading, empty, running, complete, partial, skipped, failed 상태는 시각과 텍스트로 구분합니다.
- 색상은 보조 수단입니다. 상태는 텍스트·형태 또는 아이콘 없이도 이해할 수 있어야 합니다.
- 정적 참조 데이터에는 눈에 보이는 표기를 넣고 “검증됨”, “수렴”, “솔버 결과” 같은 표현을 사용하지 않습니다.
- 브라우저 저장소에는 언어와 같은 장치 로컬 환경설정만 보관합니다.

## 로컬 엔진 작업 추가

프런트엔드나 API에서 `docker`, `podman`, shell 또는 subprocess를 직접 호출하지 않습니다. 런타임 구현은 타입이 지정된 `RuntimeBackend` 계약과 정책 테스트에서 시작하고 실제 Docker 및 rootless Podman 증거를 추가합니다. 엔진 소켓에는 샌드박스 브로커만 접근할 수 있습니다.

런타임, 수치, 데이터 migration 또는 배포 변경은 `02_CODEX_HARNESS_KR.md`의 이슈 접수 보고서, 위험 등급, tests-first 경계, 보안·수치 변화, rollback 증거를 따라야 합니다.

## 문서 동등성

영어와 한국어 문서는 다음처럼 경로를 쌍으로 관리합니다.

```text
docs/en/<name>.md
docs/ko/<name>.md
```

기능 또는 운영 문서 변경은 두 파일이 같은 계약을 설명해야 완료됩니다. 상세 기존 기획 번들은 한국어 원문으로 유지하고 새로 관리하는 제품 문서는 한·영으로 제공합니다.
