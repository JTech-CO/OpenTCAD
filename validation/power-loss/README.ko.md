# 외부 실제 전원 차단 자격 검증

[English](README.md)

이 절차는 외부 시험실 게이트입니다. 개발용 PC, 운영 장비 또는 유일한 데이터가 저장된 장치에서 실행하지 않습니다. OpenTCAD은 process 종료, VM reset 또는 정상 종료를 실제 전원 차단으로 간주하지 않습니다.

## 필요한 환경

- 전용 host와 폐기 가능한 저장장치 구성
- 독립적으로 제어하는 PDU 또는 동등한 물리 전원 차단 장치
- OS, filesystem, storage model, firmware, controller, write cache policy 기록
- 하나의 불변 OpenTCAD revision과 정확한 runtime 및 image grant
- boot, 준비된 cut point, 무결성 결과, rollback floor 결과를 기록하는 별도 관측 장치

## 검증 행렬

backend/app/broker/durability.py에 선언된 순서대로 cut point 10곳을 검사합니다. 각 지점에서 실제 전원 차단을 최소 10회 수행합니다. 따라서 완전한 증거 기록 하나에는 실제 차단 100회 이상이 필요합니다. 승인하려는 platform, filesystem, storage, cache 구성마다 기록을 별도로 반복합니다.

매번 다시 켠 뒤 다음을 확인합니다.

1. 차단 전 marker와 host log를 시험 대상 밖에 보존합니다.
2. control, state, fence database에서 SQLite quick_check와 integrity_check를 실행합니다.
3. 부분 공개된 export 또는 import가 허용되지 않는지 확인합니다.
4. OS 보호 floor가 더 오래된 인증 snapshot을 모두 거부하는지 확인합니다.
5. recovery를 시작하고 성공 상태를 임의로 만들지 않는지 확인합니다.
6. Docker 및 Podman label을 조회하고 설명되지 않은 managed object가 0개인지 확인합니다.
7. 결과를 외부 evidence ledger에 추가합니다.

모든 reboot가 완료되고 partial publication, SQLite integrity failure, rollback violation이 각각 0이어야 합니다. 또한 validation/schemas/m3-power-loss-evidence.schema.json과 일치해야 검토 대상이 됩니다.

현재 저장소에는 실제 전원 차단 0회인 blocked 상태 기록이 있습니다. Unit test나 process hard exit 결과로 이 수치를 변경하지 않습니다.
