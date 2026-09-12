# Windows 우선 로컬 MVP 후보

[English](../en/windows-mvp.md) · [솔버 설치](mvp-laboratory.md)

Windows 11 x64를 대상으로 하는 별도의 소스 배포 릴리스 트랙입니다. 기존 M3
승인 조건을 면제하지 않고 그대로 보존합니다.
[릴리스 기준](../../validation/manifests/windows-mvp-release.json)은 아직 검토 전
후보 상태입니다. 개발자가 이 트랙의 릴리스 검토를 맡을 수 있지만, 독립적인
M3 자격 검증은 아닙니다.

## 설치와 실행

Node.js 22/24와 64비트 Python 3.12-3.14를 설치한 뒤 저장소에서 실행합니다.

```powershell
npm ci
py -3.12 -m venv .venv-mvp
.\.venv-mvp\Scripts\python.exe -m pip install -r backend/app/experimental/requirements.txt
npm run build
npm run local:mvp -- doctor
npm run test:mvp:solver
npm run local:mvp -- serve
```

의존성 설치는 사용자가 선택한 제3자 패키지를 다운로드합니다. 저장소와 이
트랙은 솔버를 배포하거나 라이선스를 승인하지 않습니다. `doctor`는 버전 고정
의존성, Python, 호스트와 프런트엔드 빌드를 검사하며 솔버 실행이나 수치 승인을
대신하지 않습니다. `serve`는 시작할 때 실제 PN 해석도 확인합니다. Windows
프로세스 격리 기능을 사용할 수 없으면 시작하지 않습니다. 네이티브 DEVSIM에는
Docker나 Podman 서비스가 필요하지 않습니다.

서비스가 출력한 개인용 주소로 접속하고 주소 조각의 접근 토큰은 공유하지
마세요. 인증된 loopback 요청만 고정 수치 템플릿을 실행합니다. 정적 Pages에서는
즉시 계산기만 동작하고 네이티브 솔버는 실행되지 않습니다. 브라우저에는 계속
실험용 서비스로 표시합니다. M3 제품 활성화 토큰이나 런타임 권한을 발급하지 않습니다.

`serve`에 `--suprem-structure C:\absolute\process.str --suprem-contacts C:\absolute\contacts.json`을
추가하면 [원본 공정 메시](process-mesh.md)를 사용할 수 있습니다. SUPREM 공정은
사용자가 설치한 신뢰 가능한 솔버를 명시적으로 실행하는 별도 고정 덱 CLI입니다.
임의 덱 업로드 API나 솔버 이미지 배포 기능이 아닙니다.

## 작업 기록, 중단과 결과 조회

기본 저장 위치는 `%LOCALAPPDATA%\OpenTCAD\windows-mvp`입니다.
`--state-directory C:\absolute\project-state`로 다른 로컬 폴더를 지정할 수 있습니다.
링크·reparse 경로는 거부합니다. 공유·네트워크 폴더 대신 자신의 Windows 계정이
관리하는 신뢰 가능한 로컬 저장소를 사용하세요. 서버와 오프라인 명령 중 하나만
폴더 잠금을 보유할 수 있습니다. 같은 사용자 권한으로 파일을 공격적으로
수정하는 행위를 막는 보안 경계는 아닙니다.

폴더당 최대 32개 작업과 작업당 최대 1 MiB 기록을 저장하며 자동 삭제하지 않습니다.
한도에 도달하면 서버를 중지하고 백업·내보내기한 뒤 새 폴더를 사용하세요.
같은 작업 ID에 다른 입력을 보내면 충돌로 거부합니다. 브라우저를 새로고침해도
기록이 편집 화면에 자동으로 다시 열리지는 않습니다. 서버 중지 후 다음을 사용합니다.

```powershell
npm run local:mvp -- history
npm run local:mvp -- export --job-id ACTUAL_JOB_UUID --file C:\absolute\new-result.json
```

내보낸 파일은 기존 수치 결과 형식입니다. 실험실의 파일 흐름으로 가져오거나
일치하는 소스·솔버 버전으로 재실행할 수 있습니다. 인증 API의
`GET /v1/lab/jobs`로 요약을, `GET /v1/lab/jobs/{id}`로 상세를 조회할 수도 있습니다.
HTTP로 파일 경로를 받지 않습니다.

Windows Job Object가 서비스와 자식 프로세스를 묶고 서비스 종료 시 정리합니다.
개별 솔버도 별도의 Job Object에 묶으며, 입력 전달 전에 실제 워커가 알린 PID에
연결합니다. 가상환경 런처를 실제 솔버로 잘못 취급하지 않도록 한 구조입니다.
[Windows Job Object 문서](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)를 참고하세요.
런처 핸들도 감시하여 npm 또는 가상환경 런처의 비정상 종료에 대응합니다.
일반 취소는 솔버를 종료하고 회수한 뒤 응답합니다. SQLite 트랜잭션으로 접수와
최종 결과를 저장합니다. 재시작 시 실행 중으로 남은 작업은 `error: interrupted`인
실패로 전환하며 성공 처리나 자동 재실행하지 않습니다. 저장 실패 시 새 접수를
차단하고 저장되지 않은 성공 결과를 응답하지 않습니다. 물리적 전원 차단 내구성을
보장하는 것은 아닙니다.

## 오프라인 백업과 복원

먼저 서버를 중지하세요. 출력은 새 파일이어야 하고 복원은 새 폴더만 허용합니다.

```powershell
npm run local:mvp -- backup --file C:\absolute\new-backup.json
npm run local:mvp -- verify-backup --file C:\absolute\new-backup.json
npm run local:mvp -- restore --file C:\absolute\new-backup.json --state-directory C:\absolute\new-restored-state
npm run local:mvp -- serve --state-directory C:\absolute\new-restored-state
```

백업은 크기가 제한된 JSON이며 각 기록·결과의 해시와 전체 SHA-256을 포함합니다.
중복 키·작업 ID, 변경된 해시와 잘못된 상태·결과 조합은 거부합니다. 복원은 검증된
기록을 단일 트랜잭션으로 넣으며 원시 SQLite 파일 가져오기, 기존 프로젝트 덮어쓰기,
솔버 실행이나 토큰 복원을 하지 않습니다. 쓰다 중단된 파일은 유효한 백업이 아니므로
보관 전에 검증 성공을 확인하세요.

체크섬은 인증이나 암호화가 아닙니다. 파일을 수정할 수 있는 사람은 해시도 다시
계산할 수 있습니다. 접근 비밀, 설치된 솔버, 소스 코드, STR·접촉 파일, OS 자격
증명 저장소는 백업에 포함하지 않습니다. 재실행에 필요한 소스와 공정 파일은
별도로 보존하세요. 오래된 정상 백업의 복원은 허용되며 MVP 롤백 방지 기준이나
자동 예약 백업은 제공하지 않습니다.

## Windows 릴리스 전 검토

전용 Windows 호스트에서 깨끗한 커밋의 정확한 해시, OS·Python·의존성 버전,
`doctor` 출력과 `npm run check`, `npm run test:mvp:solver` 로그를 기록합니다.
인증된 실제 PN·MOS 실행, 바이어스 변화, 취소, 서비스·런처 비정상 종료,
재시작 시 중단 판정, 기록 내보내기, 변조 백업 거부, 새 폴더 복원을 확인합니다.
SUPREM 연계를 주장한다면 공정 파일 해시도 포함합니다. 이 증거를 검토한 뒤에만
Windows 릴리스 승인·태그를 진행하며 CI 성공만으로 `releaseReview`를 채우지 않습니다.

[로컬 관측 기록](../../validation/experimental/windows-mvp-observation.json)에는 네이티브
테스트 35개 통과와 함께, 앞선 PN 반복 결과 해시 불일치 1건도 보존했습니다.
이후 동일 입력 12회 검사에서는 재현되지 않았지만 원인과 수치 차이 크기는 아직
확정하지 못했습니다. 기존 테스트를 완화하지 않았으며, 후속 성공으로 덮지 않고
조사가 필요한 릴리스 차단 항목으로 유지합니다.
[PN 조사 안내](pn-repeatability.md)의 도구로 원본 반복 결과와 항목별 차이를
보존할 수 있으며 승인 검사는 완화하지 않습니다.

물리적 전원 차단 내구성, macOS·Linux 제품 자격, 독립 외부 검토, 자동 백업,
OS 보호 롤백 방지, 솔버 재배포권과 보정된 수치 corpus 승인은 미검증·유보 상태입니다.
기존 M3 명령·프로필·승인 게이트는 유지합니다. OG 이미지와 공개 Pages 배포는
이 트랙 추가로 변경하지 않습니다.
