# OpenTCAD 검증 기반

[English](README.md)

이 디렉터리는 엔진 독립 검증 계약과 런타임 기반 기록을 포함합니다. 솔버, 사용 권한이 확인된 fixture, 수치 기준선, golden result는 포함하지 않습니다.

- `baseline/`: 외부 관찰 hash, profile, log policy, timeout, repeatability 코드와 unit test
- `comparators/`: exact, topology, scalar, curve, repeatability, report 코드와 unit test
- `faults/`: 실제 자식 프로세스를 사용하는 엔진 독립 timeout, 취소, 합산 출력 상한, worker 초기화 supervisor와 test
- `corpus/`: baseline value가 null인 후보 coverage manifest
- `manifests/`: 고정 contract 증거와 격리된 image reference
- `plans/`: expected value가 없고 승격하지 않는 외부 참조 관찰 계획
- `schemas/`: corpus, report, 관찰 계획, 관찰 envelope의 JSON schema
- `evidence/m3/`: hash로 고정한 구현, host, platform, 전원 차단, solver release 상태 기록
- `power-loss/`: 외부 실제 전원 차단 자격 검증 절차

npm run test:validation, npm run test:runtime, npm run check:m3 또는 전체 npm run check를 실행합니다. 자격 host에서는 python tools/qualify-runtime.py --output validation/evidence/m3/runtime-host-local.json을 실행합니다. Runtime 관측 기록만으로 승인을 부여하지 않습니다. Baseline update command는 의도적으로 제공하지 않습니다.
