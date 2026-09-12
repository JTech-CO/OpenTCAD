# 로컬 OpenTCAD MCP

[English](../en/mcp.md) · [Windows 로컬 서비스](windows-mvp.md)

구현된 stdio 연결기는 이미 실행 중인 인증 로컬 실험실에 MCP 클라이언트를
연결합니다. 시작 시 솔버를 설치·실행하거나 공개 포트를 열거나 M3 승인을 부여하지
않습니다. 프로토콜 2025-11-25와 2025-06-18을 지원하며 별도 MCP SDK는 필요하지 않습니다.

## 연결

1. 버전 고정 솔버 환경을 설치하고 프런트엔드를 빌드한 뒤 Windows에서
   `npm run local:mvp -- serve`를 실행합니다. 실험용 `local:lab`도 연결할 수 있습니다.
2. 서비스의 개인용 주소에서 포트는 `OPENTCAD_MCP_PORT`, `#experiment=` 뒤 값은
   `OPENTCAD_MCP_TOKEN`으로 MCP 클라이언트의 비공개 환경 설정에 넣습니다.
   호스트는 항상 숫자 주소 `127.0.0.1`입니다.
3. 아래 개념적 설정의 경로와 비공개 값을 바꿔 stdio 서버를 등록합니다.
   구체적인 설정 형식은 클라이언트마다 다를 수 있습니다.

```json
{
  "command": "C:/absolute/path/to/node.exe",
  "args": ["C:/absolute/path/to/OpenTCAD/tools/run-mcp.mjs"],
  "env": {
    "OPENTCAD_MCP_PORT": "LOCAL_SERVICE_PORT",
    "OPENTCAD_MCP_TOKEN": "PRIVATE_CURRENT_SESSION_TOKEN"
  }
}
```

다른 운영체제에서는 해당 Node·저장소 경로를 사용합니다. 실행기는 저장소의
`.venv-mvp`를 사용하며 `OPENTCAD_LAB_PYTHON`으로 명시적으로 신뢰한 로컬 Python을
지정할 수 있습니다. MCP 클라이언트 명령으로 `npm run`을 사용하면 npm 안내문이
JSON-RPC 표준 출력에 섞이므로 위 Node 실행기를 직접 사용하세요. 토큰을 커밋,
프롬프트, 스크린샷이나 공유 로그에 넣지 마세요. 서비스를 재시작하면 포트·토큰이
바뀌므로 비공개 설정을 갱신하고 연결기를 다시 실행합니다. 토큰을 모델이나 원격
서비스에 도구 인자로 보내지 마세요.

## 도구와 권한

| 도구 | 기본 상태 | 동작 |
|---|---|---|
| `opentcad_capabilities` | 읽기 전용 | 연결 상태, 모델, 기본값, 입력 스키마와 제한 |
| `opentcad_list_jobs` | 읽기 전용 | 최대 32개 작업 요약 |
| `opentcad_get_job` | 읽기 전용 | 상태, 검증된 결과 해시, 입력과 출처 |
| `opentcad_plan_sweep` | 읽기 전용 | 최대 8개 입력 변형 검증, 실행 없음 |
| `opentcad_submit_job` | 비활성 | 지원되는 PN·MOS 고정 템플릿 1개 제출 |
| `opentcad_cancel_job` | 비활성 | 명시한 작업 취소 |

신뢰한 클라이언트의 실행·취소를 허용할 때만 실행기 경로 뒤에
`--allow-execution`을 추가하세요. 클라이언트의 사용자 승인 절차도 유지해야 하며,
도구 설명의 권한 표시는 실제 접근 제어를 대신하지 않습니다. UI에서 시작한 작업도
취소될 수 있습니다. 서버는 단일 실행, 입력 제한, 시간 제한, 인증과 설정된 공정
프로필을 계속 강제합니다. 도구 인자로 shell, Python 소스, 공정 덱, URL 또는 임의
파일 경로를 받지 않습니다.

SUPREM 연계는 기존 구조·접촉 CLI 옵션으로 로컬 서비스를 먼저 설정해야 합니다.
MCP가 SUPREM 공정 덱을 실행하지는 않습니다. 메시 형상과 가져온 도핑의 변경 제한은
스윕 계획에도 적용합니다.

스윕 계획은 결정론적인 작업 ID와 정규화된 입력을 반환합니다. 한 점을 제출하고
완료까지 조회한 뒤 다음 점의 실행을 결정하세요. 같은 계획은 ID를 재사용하므로
완료된 결과가 반환될 수 있습니다. 자동 스윕 큐는 아닙니다. 의도적인 재계산은 새
UUID를 사용합니다. 통신 실패 시 새 ID로 재시도하기 전에 원래 ID를 조회하세요.
응답을 받지 못했다는 사실은 접수 실패를 뜻하지 않습니다. MCP 클라이언트 종료만으로
서버 작업을 취소하지 않습니다.

결과에는 큰 배열이나 미공개 연구 입력이 포함될 수 있습니다. MCP 클라이언트가
도구 결과를 설정된 AI 제공자에게 전달할 수 있으므로 클라이언트와 데이터 공유
정책을 확인하세요. 연결기 자체는 로컬 서비스에만 접속하며 AI 제공자에게 직접
토큰이나 결과를 전송하지 않습니다.

## 검증과 한계

프로토콜, 읽기 전용 권한, 잘못된 입력, 메시지 크기, 실제 stdio, 인증 HTTP,
취소와 선택형 실제 DEVSIM 시험을 포함합니다. `npm run test:mvp:solver`에 실제 MCP
경로 검사도 포함합니다. 초기 로컬 MCP이며 호스팅 HTTP 엔드포인트, 임의 코드
에이전트, 자동 최적화, 범용 공정 편집기나 독립적인 수치 자격 인증은 아닙니다.

프로토콜 근거: [stdio 전송](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports),
[초기화](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle),
[도구](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).
