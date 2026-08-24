# OpenTCAD 검증 기반

[English](README.md) | [M1 상태](../docs/ko/m1/README.md) | [검증 계약](../docs/ko/m1/validation-contract.md)

이 디렉터리는 엔진 독립 M0 및 M1 검증 계약과 gate 상태 M2 런타임 기반 기록을 포함합니다. 솔버, 사용 권한이 확인된 fixture, 수치 기준선, golden result는 포함하지 않습니다.

- `baseline/`: 외부 관찰 hash, profile, log policy, timeout, repeatability 코드와 unit test
- `comparators/`: exact, topology, scalar, curve, repeatability, report 코드와 unit test
- `faults/`: 실제 자식 프로세스를 사용하는 엔진 독립 timeout, 취소, 합산 출력 상한, worker 초기화 supervisor와 test
- `corpus/`: baseline value가 null인 후보 coverage manifest
- `manifests/`: gate 상태의 M0/M1/M2 기록, 고정 contract 증거, 격리된 image reference
- `plans/`: expected value가 없고 승격하지 않는 외부 참조 관찰 계획
- `schemas/`: corpus, report, 관찰 계획, 관찰 envelope의 JSON schema

`npm run test:validation`, `npm run test:runtime`, `npm run check:m1`, `npm run check:m2`를 실행합니다. `npm run observe:base001 -- --help`로 외부 전용 관찰 interface를 확인할 수 있습니다. Baseline update command는 의도적으로 제공하지 않으며 observer는 OpenTCAD 내부에 증거를 쓸 수 없습니다.
