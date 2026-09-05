# M3 네이티브 자격 증명 검증

[English](../en/m3-native-credentials.md)

명시적으로 실행하는 이 테스트는 메모리 저장소나 Windows DPAPI 파일 대체 경로가
아닌 제품용 OS 저장소를 사용합니다. 현재 호스트에 따라 Windows Credential
Manager, macOS Keychain 또는 Linux Secret Service를 선택합니다.

## 전용 테스트 계정에서 실행

사용 가능한 잠금 해제 상태의 자격 증명 저장소가 필요합니다. Linux에는
`secret-tool`과 사용자 세션 버스에서 실행 중인 Secret Service가 필요합니다.
어댑터는 `DBUS_SESSION_BUS_ADDRESS`, `XDG_RUNTIME_DIR`, `HOME`, `PATH`를
보존하며 무관한 비밀 값이나 로더 설정은 하위 프로세스로 전달하지 않습니다.
테스트는 저장소를 설치하거나 시작하거나 잠금을 해제하거나 재설정하지 않습니다.

PowerShell:

```powershell
$env:OPENTCAD_NATIVE_CREDENTIAL_TESTS = '1'
python -m unittest backend.tests.service.test_native_credentials -v
Remove-Item Env:OPENTCAD_NATIVE_CREDENTIAL_TESTS
```

Linux 또는 macOS:

```sh
OPENTCAD_NATIVE_CREDENTIAL_TESTS=1 python -m unittest backend.tests.service.test_native_credentials -v
```

명시적 실행 설정이 없으면 일반 테스트 탐색에서 세 테스트를 건너뜁니다. 설정을
켠 상태에서는 저장소가 없거나 잠겨 있으면 실패하며 다른 저장소로 대체하지 않습니다.
키체인 접근에 사용자 조작이 필요한 경우를 고려해 무인 실행에는 전용 계정을 사용합니다.

## 검증 범위

1. 바이너리 테스트 비밀 값을 새 Python 프로세스에서 읽을 수 있는지 확인합니다.
2. 다른 프로세스의 값 교체가 기존 프로세스와 세 번째 프로세스에 반영되는지 확인합니다.
3. OS 저장소의 복원 하한이 새 프로세스에서도 유지되고, 낮은 스냅샷 순번과 같은
   순번의 다른 스냅샷을 모두 거부하는지 확인합니다.

각 테스트는 무작위 `opentcad-m3-probe.<uuid>` 서비스의 정확한 자격 증명 ID가
없는지 먼저 확인합니다. 쓰기 전에 정리 작업을 등록하고 해당 테스트 소유 항목만
삭제합니다. 반복 삭제와 삭제 후 부재도 확인합니다. 실제 `opentcad` 서비스는
사용하지 않습니다. 비밀 값은 명령 인자나 테스트 출력이 아닌 표준 입력으로 전달하고,
하위 프로세스에는 45초 제한을 적용합니다. 부모 테스트 프로세스 전체가 강제 종료되면
정상 정리를 보장할 수 없습니다. 이 경우 확인된 테스트 항목만 조사 후 정리하며
자격 증명 저장소 전체를 비우면 안 됩니다.

보호된 M3 수동 네이티브 워크플로는 런타임 관찰 전에 이 테스트 통과를 요구합니다.
결과는 런타임 매니페스트와 별개입니다. 정확한 리비전, 런타임 관찰 자료와 함께
작업 로그를 보관해 검토합니다. 통과해도 제품, 플랫폼, 전원 장애 또는 솔버 승인은
부여되지 않습니다. 프로세스 간 영속성은 실제 전원 차단 내구성의 증거가 아닙니다.
