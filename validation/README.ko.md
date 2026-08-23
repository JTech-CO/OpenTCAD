# OpenTCAD 검증 기반

[English](README.md) | [M1 상태](../docs/ko/m1/README.md) | [검증 계약](../docs/ko/m1/validation-contract.md)

이 디렉터리는 엔진 독립 M1 검증 계약을 포함합니다. 솔버, 사용 권한이 확인된 fixture, 수치 기준선, golden result는 포함하지 않습니다.

- `comparators/`: exact, topology, scalar, curve, repeatability, report 코드와 unit test
- `corpus/`: baseline value가 null인 후보 coverage manifest
- `manifests/`: gate 상태의 M1 기록과 격리된 image reference
- `schemas/`: corpus 및 report envelope의 JSON schema

`npm run test:validation`과 `npm run check:m1`을 실행합니다. Baseline update command는 의도적으로 제공하지 않습니다.
