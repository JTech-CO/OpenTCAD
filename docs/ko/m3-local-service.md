# M3 로컬 제품 서비스

[English](../en/m3-local-service.md)

M3는 기존 영속 브로커 계약을 실제로 실행할 수 있는 교차 플랫폼 로컬 호스트로 감쌉니다. 커밋된 릴리스는 솔버 실행이 비활성 상태입니다. 현재는 동일 출처 방식의 비실행 로컬 제품 미리보기를 사용할 수 있으며, 제품 명령은 모든 M3 게이트와 코드 소유 릴리스 프로필이 함께 승인될 때까지 실패 폐쇄 상태를 유지합니다.

## 사용할 수 있는 명령

로컬 웹 호스트를 시작하기 전에 정적 자산을 빌드합니다.

```bash
npm install
npm run build
```

로컬 제품 상태를 만들지 않고 커밋된 게이트 매니페스트를 검사합니다.

```bash
npm run local:doctor
```

임시 loopback 포트에서 차단형 로컬 미리보기를 시작합니다.

```bash
npm run local:preview
```

명령은 `browserUrl`이 포함된 JSON 객체 하나를 출력합니다. 같은 사용자 세션에서 해당 URL을 엽니다. URL fragment에는 해당 서비스 실행 동안 유효한 임시 bearer bootstrap이 있으므로 로그, 이슈 보고서, shell history 또는 공유 메시지에 복사하지 않습니다. 클라이언트는 즉시 bootstrap fragment를 제거하고 secret을 메모리에만 보관합니다.

제품 명령은 다음과 같습니다.

```bash
npm run local:serve
```

커밋된 매니페스트에서는 종료 코드 `3`과 `productStarted:false`를 반환합니다. 이것이 현재 릴리스의 정상 상태입니다. 자산을 읽거나 directory를 만들고 instance lock, 자격 증명 저장소, SQLite database를 열거나 Docker 또는 Podman을 확인하고 socket을 바인딩하기 전에 활성화부터 검사합니다.

## 미리보기와 제품 경계

| 속성 | GitHub Pages 정적 화면 | 로컬 차단형 미리보기 | 활성화된 제품 호스트 |
|---|---:|---:|---:|
| 소개 페이지와 작업공간 제공 | 제공 | 제공 | 제공 |
| 로컬 연결 자동 실행 | 실행 안 함 | 실행 안 함 | 실행 안 함 |
| 제거된 정보만 포함한 서비스 상태 제공 | 제공 안 함 | 제공 | 제공 |
| 영속 애플리케이션 상태 생성 | 생성 안 함 | 생성 안 함 | 생성 |
| OS 자격 증명 저장소 접근 | 접근 안 함 | 접근 안 함 | 접근 |
| Docker 또는 Podman 접근 | 접근 안 함 | 접근 안 함 | 접근 |
| 솔버 작업 제출 | 제출 불가 | 제출 불가 | 릴리스 활성화 후에만 가능 |

GitHub Pages에서는 로컬 서비스 fetch를 실행하지 않습니다. Loopback에서는 사용자가 명시적인 연결 버튼을 선택해야 UI가 `/v1/status`를 읽습니다. 전송 연결 상태와 솔버 실행 권한은 서로 다른 상태로 표시합니다.

## 운영자 설정

예제는 [config/local-service.example.json](../../config/local-service.example.json)에 있습니다.

```json
{
  "schemaVersion": 1,
  "runtimeBackend": "docker",
  "apiPort": 0,
  "backupIntervalMs": 86400000,
  "recoveryPageLimit": 100
}
```

Parser는 위 key만 허용하고 중복 key와 symbolic link를 거부하며 모든 숫자 범위를 제한합니다. `apiPort:0`은 임시 포트를 선택합니다. 운영자는 이 파일에서 image, digest, command, entrypoint, mount, 환경 변수, 자격 증명 식별자, database 경로 또는 host executable을 설정할 수 없습니다.

릴리스 빌드에서는 예제를 플랫폼별 설정 경로에 복사합니다.

| 호스트 | 설정 경로 | 상태 경로 |
|---|---|---|
| Windows | `%LOCALAPPDATA%\OpenTCAD\config\local-service.json` | `%LOCALAPPDATA%\OpenTCAD\state` |
| macOS | `~/Library/Application Support/OpenTCAD/config/local-service.json` | `~/Library/Application Support/OpenTCAD/state` |
| Linux | `$XDG_CONFIG_HOME/opentcad/local-service.json` 또는 `~/.config/opentcad/local-service.json` | `$XDG_STATE_HOME/opentcad` 또는 `~/.local/state/opentcad` |

개발 및 자격 검증에서는 절대 경로로 된 별도 data root를 사용할 수 있습니다.

```bash
python -m backend.app.service serve --data-root /absolute/test/root
```

이 옵션은 활성화를 우회하지 않습니다.

## 활성화와 시작 순서

릴리스 경계는 의도적으로 코드가 소유합니다.

1. 엄격한 증거 hash 기반 M3 매니페스트를 읽습니다.
2. 8개 게이트와 정확한 runtime grant를 모두 요구합니다.
3. 매니페스트 SHA-256 및 선택한 backend와 연결된 검토 완료 릴리스 프로필을 선택합니다.
4. 그다음에만 사용자별 경로를 준비하고 단일 instance lock을 획득합니다.
5. 승인된 런타임을 확인하고 digest로 고정한 모든 image가 로컬에 있는지 검사합니다. 시작 과정에서 image를 pull하지 않습니다.
6. Native credential을 준비하고 영속 SQLite store를 열고 recovery를 실행한 뒤 scheduler를 시작합니다.
7. 숫자로 된 `127.0.0.1` 주소를 바인딩하고 secret이 없는 endpoint record를 기록합니다.

커밋된 소스에서 `PRODUCT_RELEASE_PROFILES`는 비어 있습니다. 따라서 매니페스트만 수정해도 실행을 활성화할 수 없습니다.

## 런타임과 lifecycle 통합

- Docker 및 Podman 호출은 확인된 executable, allowlist 환경, shell을 거치지 않는 argv, 출력 상한, 시간 상한을 사용합니다.
- 런타임 객체는 job identity, owner identity, fencing generation, entrypoint identity, 출력 상한을 native label로 기록합니다.
- 제품 작업은 영속 fence 확인과 native mutation 전체를 job별 cross-process lock으로 감쌉니다. Takeover가 이전 owner의 런타임 명령 중간에 끼어들 수 없습니다.
- 재시작 후 취소는 검증된 native label에서 출력 상한을 복원합니다. Label이 없거나 잘못되면 native kill 명령 전에 작업을 fencing 처리합니다.
- 성공 산출물을 재시작 후 넘겨받으려면 메모리에 검증된 job metadata가 남아 있어야 합니다. 어댑터는 예상 산출물 manifest를 추측하지 않습니다.
- 실행, 취소, recovery, maintenance, 인증된 import와 export, 예약 backup, 종료는 같은 애플리케이션 lifecycle을 공유합니다.
- Worker는 대기 중 요청과 실행 중 요청의 총량을 제한하고 취소용 control lane을 별도로 둡니다.

## 로컬 HTTP 경계

로컬 서비스는 범용 외부 웹 framework 대신 작은 표준 library HTTP 서버를 사용합니다. 정적 자산과 API 응답은 숫자로 된 동일 loopback 출처에서 제공됩니다. 다음 항목을 강제합니다.

- loopback peer, Host, Origin 검사
- API route의 bearer 인증
- 엄격한 JSON 형태와 중복 key 거부
- 요청 크기, 연결 수, 요청 시간 상한
- redirect 및 CORS 미사용, 제한적인 Content Security Policy
- 경로, secret, command, native diagnostic, solver 내용을 제외한 상태 응답

Endpoint file에는 startup ID, process ID, port, manifest hash, mode만 들어갑니다. 브라우저 bearer secret은 기록하지 않습니다.

## 현재 차단 항목

권위 있는 상태는 [validation/manifests/m3-entry-gates.json](../../validation/manifests/m3-entry-gates.json)에 있습니다. 현재 revision의 상태는 다음과 같습니다.

- `productEnabled`는 false
- runtime grant는 모두 비어 있음
- 코드 소유 제품 릴리스 프로필 없음
- 3개 플랫폼 native runtime 증거 미승인
- 실제 비정상 전원 차단 증거 미완료
- solver license, 불변 image, SBOM, 수치 corpus 승인 미완료

따라서 현재 구현은 근거 없는 솔버, 보안, 플랫폼 또는 수치 성능 주장을 하지 않으면서 검토하고 실행 경계를 확인할 수 있습니다.

## 검증

```bash
npm run check:m3
npm run check
npm run local:doctor
npm run local:preview
```

`local:preview`는 계속 실행되는 명령입니다. Ctrl+C로 종료합니다. 커밋된 릴리스에서 `local:serve`가 차단되는 것도 필수 실패 폐쇄 검사입니다.
