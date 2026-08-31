# 개발

[English](../en/development.md)

## 요구사항

- Node.js 22 LTS 또는 24 LTS
- npm 10 이상
- 런타임 계약 테스트용 Python 3.12부터 3.14
- Git

정적 앱과 계약 test에는 컨테이너 런타임, 외부 database server 또는 solver가 필요하지 않습니다. 로컬 서비스와 SQLite store는 Python 표준 library를 사용합니다. 실제 Docker 및 Podman 관측은 승격 권한이 없는 별도 자격 검증 작업입니다.

## 설정과 명령

```bash
npm install
npm run dev
```

개발 서버는 Vite를 사용합니다. 배포 전 품질 게이트는 다음과 같습니다.

```bash
npm run check
npm run coverage
```

`npm run preview`는 배포 번들을 `127.0.0.1`에서 제공합니다. 빌드는 상대 자산 URL을 사용하므로 GitHub 저장소 하위 경로와 일반 로컬 정적 서버에서 같은 산출물을 실행할 수 있습니다.

## M3 로컬 호스트

`npm run build` 이후 제품 게이트를 확인하고 입력을 실행하지 않는 동일 출처 호스트를 시작할 수 있습니다.

```bash
npm run local:doctor
npm run local:preview
```

미리보기는 자격 증명 저장소, SQLite database 또는 OCI 런타임을 열지 않습니다. `npm run local:serve`는 제품 명령이며 커밋된 매니페스트에서는 차단 종료되어야 합니다. 설정, 경로, 종료 동작, 활성화 순서는 [M3 로컬 제품 서비스](m3-local-service.md)에서 확인합니다.

## 프런트엔드 규칙

- 사용자에게 보이는 문자열은 모두 `frontend/src/i18n.ts`에 두고 영어와 한국어를 함께 제공합니다.
- 사용자가 입력 중인 상태는 명시적 검증 전까지 문자열로 유지하며 숫자 중간 상태를 즉시 변환하지 않습니다.
- 편집 가능한 label에서 안정적인 내부 ID를 만들지 않습니다.
- loading, empty, running, complete, partial, skipped, failed 상태는 시각과 텍스트로 구분합니다.
- 색상은 보조 수단입니다. 상태는 텍스트·형태 또는 아이콘 없이도 이해할 수 있어야 합니다.
- 정적 참조 데이터에는 눈에 보이는 표기를 넣고 “검증됨”, “수렴”, “솔버 결과” 같은 표현을 사용하지 않습니다.
- 브라우저 저장소에는 언어와 같은 장치 로컬 환경설정만 보관합니다.

## 로컬 엔진 작업 변경

프런트엔드나 API에서 `docker`, `podman`, shell 또는 subprocess를 직접 호출하지 않습니다. 런타임에는 샌드박스 브로커와 활성화된 OCI adapter만 접근할 수 있습니다. 운영자 설정으로 command, image, entrypoint, mount, host path 또는 환경 값을 선택하게 해서는 안 됩니다.

활성화 또는 릴리스 프로필 변경에는 거부 및 성공 test, 검토된 증거 hash, 정확한 image 및 entrypoint grant, 3개 플랫폼 native 관측, license 및 수치 검토가 함께 필요합니다. Test fixture는 릴리스 프로필을 명시적으로 만들 수 있지만 production profile은 코드가 소유합니다.

## 문서 동등성

영어와 한국어 문서는 다음처럼 경로를 쌍으로 관리합니다.

```text
docs/en/<name>.md
docs/ko/<name>.md
```

기능 또는 운영 문서 변경은 두 파일이 같은 계약을 설명해야 완료됩니다. 관리되는 제품 문서는 한·영으로 제공합니다.
