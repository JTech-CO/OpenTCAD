# PN 반복 재현성 조사

[English](../en/pn-repeatability.md) · [Windows MVP](windows-mvp.md)

9월 8일 PN 사건은 사용자 보고에 따른 외부 로그 손상 사건으로 종결했으며,
솔버 결함을 재현한 것으로 분류하지 않습니다.
[9월 12일 종결 기록](../../validation/experimental/pn-incident-disposition-20260912.json)을
참고하세요. 당시 원본 결과 쌍이 없어 원인을 독립적으로 재구성할 수 없습니다.
기존 관측은 수정하지 않으며 후속 실행 일치만으로 종결한 것이 아닙니다.
새로 발생하는 실패는 계속 조사합니다.

## 새로운 관측 수집

### 새 실패 원본과 수정

9월 12일 전용 Windows 인수 시험에서 서브에이전트 없이 과거 해시 쌍이 재현되었습니다.
[원본 쌍과 비교 기록](../../validation/experimental/pn-metadata-20260912/comparison.json)에서
수치 배열과 검사는 모두 같고 `environment.machine`만 `AMD64`와 빈 문자열로
달랐습니다. 두 결과의 무결성 해시도 검증했습니다. Python 3.14의 Windows 장비
조회는 WMI 실패 시 프로세서 환경변수로 대체하지만 제한된 솔버 환경에는 해당
변수가 없습니다. 이번에 확인한 것은 수치 오차가 아닌 메타데이터 불안정입니다.
과거 사용자 보고는 보존하되, 재현된 해시 쌍의 설명은 이 새 증거로 갱신합니다.
PN과 MOS 모두 Windows `GetNativeSystemInfo`를 사용하도록 수정했고 알 수 없는
아키텍처는 빈 값 대신 실패로 처리합니다. 해시 검사, 물리식과 수치 허용오차는
변경하지 않았습니다. 소스 지문이 바뀌므로 수정 전후 결과 재실행에는 각 결과와
일치하는 소스 리비전이 필요합니다.

근거: [Python platform.machine](https://docs.python.org/3.14/library/platform.html#platform.machine),
[Windows GetNativeSystemInfo](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-getnativesysteminfo).

이미 설치한 버전 고정 DEVSIM 환경과 새로운 절대 경로 출력 폴더를 사용합니다.
솔버 다운로드, 임의 스크립트 실행 또는 승인 플래그 변경은 하지 않습니다.

```powershell
.\.venv-mvp\Scripts\python.exe -m backend.app.experimental.repeatability --output C:\absolute\new-pn-observation --cycles 12
```

다른 호스트에서는 `.venv-mvp/bin/python`과 절대 출력 경로를 사용합니다.
이는 진단 도구이며 다른 운영체제의 자격 승인을 추가하는 기능은 아닙니다.

각 주기는 기존 실패 테스트와 같은 100, 200, 400, 200 interval 순서로 새 솔버
프로세스를 실행합니다. 최대 50주기까지 허용하며 모든 원본 결과를 저장합니다.
각 입력의 첫 결과와 후속 결과를 비교하고 기존 재실행 파일 검증기로 저장된
결과의 무결성을 검사합니다. 실행 전후 소스 파일 해시도 기록합니다.

`report.json`은 바이트 일치와 기존 수치 재실행 허용오차를 구분합니다. 변경 항목,
차이가 난 좌표의 예, 최대 절대·상대 차이, 소스 변경, 파일·결과 해시를 포함합니다.
부호 있는 0과 정수·실수 인코딩 차이도 감추지 않습니다. 반올림, 허용오차 변경,
기존 출력 덮어쓰기나 과거 이슈 해제는 하지 않습니다. 해석이 실패하면
`failure.json`에 완료한 파일 목록을 남깁니다. 요약 보고서만으로는 원본 수치
증거를 대체할 수 없으므로 전체 출력 폴더를 보존하세요.

종료 코드 0은 이번 관측에서 일치했다는 의미뿐입니다. 코드 1은 차이 관측,
잘못된 인자 또는 미완료를 뜻합니다. 모든 비교가 일치해도 릴리스 승인과 과거
이슈 해제 값은 false로 남습니다.

## 실패 시 자동 보존

기존 네이티브 PN 회귀 테스트는 정확한 결과 해시와 I-V 일치 검사를 유지합니다.
해시 불일치로 실패하기 전에 `before.json`, `after.json`, `comparison.json`을
고유 폴더에 저장합니다. `OPENTCAD_NUMERICAL_EVIDENCE_DIR`로 상위 경로를
지정할 수 있고 기본값은 OS 임시 폴더입니다. 저장에 실패해도 원래 검사를 건너뛰지 않습니다.

네이티브 CI는 실패 시 리비전·플랫폼별 산출물로 해당 폴더를 업로드하고 30일간
보관합니다. 만료 전에 내려받아 보존하세요. 합성 결과로 수행하는 관측 도구
단위 테스트는 진단 동작만 검증하며 솔버 실행 증거가 아닙니다.

[9월 12일 관측](../../validation/experimental/pn-repeatability-20260912.json)에서는
48회씩 두 묶음을 실행했지만 불일치가 재현되지 않았습니다. 현재 200-interval
결과는 과거의 두 번째 해시와 일치합니다. 조사 범위를 좁히는 단서일 뿐 첫 번째
해시가 만들어진 원인을 입증한 것은 아닙니다. 별도의 사용자 보고 기반 종결
기록으로 과거 차단을 해제했으며, 전용 호스트 인수 시험과 릴리스 검토는 남아 있습니다.
진단 도구는 사건 종결이나 릴리스 승인을 부여하지 않으므로 보고서의 과거 이슈
해제 값은 계속 false입니다.
