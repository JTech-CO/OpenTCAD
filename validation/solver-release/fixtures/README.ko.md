# 솔버 릴리스 계약 테스트 자료

> 테스트 자료 전용입니다. 이 디렉터리의 어떤 파일도 제품 릴리스 증거가 아닙니다.

이 파일들은 M3 솔버 릴리스 검증기를 시험하기 위한 합성 데이터입니다. 실제 솔버 바이너리, 소스 아카이브, 재배포 허가, 법률 검토 결론, 제품 이미지 증명, 승인된 SBOM 검토, 승인된 수치 기준선을 포함하지 않습니다.

제품용 CLI는 `evidenceClass: "contract-fixture"`를 항상 거부합니다. 문서가 `release-evidence`라고 주장하더라도 `validation/solver-release/fixtures/` 아래의 artifact 경로를 모두 거부합니다. 이 값을 이동하거나 복사하거나 이름을 바꾸어도 자격 증거가 되지 않습니다.

테스트 자료 모음은 다음 명령으로 검사합니다.

```console
node --test validation/solver-release/validator.test.mjs
```

제품 후보는 `docs/ko/m3-solver-release-qualification.md`에 설명된 대로 별도로 확보하고 검토한 artifact로 구성해야 합니다.
