# M3 승격 준비 상태

[English](../en/m3-promotion-readiness.md)

기존 `check:m3` 명령은 저장소에 커밋된 차단 상태를 검증합니다. 제품 실행 권한을 부여하지 않으며 변경하지 않습니다.

별도 승격 검사기는 향후 검토가 끝난 릴리스 후보에 사용합니다. M3가 차단된 동안에는 승격 준비 manifest를 커밋하지 않습니다.

```sh
npm run check:m3:promotion -- \
  --manifest validation/manifests/m3-entry-gates.json \
  --readiness validation/manifests/m3-promotion-readiness.json \
  --revision <40자-커밋>
```

정확한 revision의 깨끗한 체크아웃, gate 8개 전체의 동시 승인, Windows와 macOS와 Linux에서 수행한 Docker 및 Podman 자격 증거, 정확한 런타임 권한, 버전 2 릴리스 이미지 잠금 파일, 불변 이미지 식별자, SBOM 해시, 라이선스 증거 해시, 일치하는 entrypoint가 모두 필요합니다. 검토된 runtime record 6개는 `validation/schemas/m3-native-qualification-evidence.schema.json`과 일치해야 하며 review 시각이 관측 시각보다 빠를 수 없습니다. 하나라도 없거나 충돌하면 후보 전체를 차단합니다.

`M3 native qualification`은 수동 self-hosted 관측 workflow입니다. 사용 전에 `m3-native-qualification` 환경에 필수 검토자를 설정하고 `opentcad-m3`, platform, backend label을 전용 runner로 제한해야 합니다. 입력은 정확한 40자 revision, fixture image reference, OCI index digest, platform manifest digest, image platform을 결합합니다. Observer는 image를 build, pull, publish, remove하지 않으므로 선택한 runtime에 미리 준비해야 합니다.

Workflow는 runner의 외부 임시 디렉터리 아래에 새 경로만 만듭니다. Windows Podman은 검토된 `Debian` WSL transport를 고정 사용하며, 다른 host와 backend 조합은 native transport를 사용합니다. 결과로 `manifest.json` 또는 `failure.json`을 업로드합니다. 모든 adapter scenario가 통과하고 managed object가 남지 않으며 선택한 runtime과 image identity가 일치하고 모든 승인, 자격, 배포, 승격 필드가 `false`일 때만 job이 성공합니다.

성공한 workflow artifact도 승격하지 않는 관측 자료이며 승격 검사기가 받는 검토 완료 runtime qualification record 6개 중 하나가 아닙니다. 해당 record를 만들려면 별도의 사람 검토와 revision 기반 증거 절차가 필요합니다. Workflow는 entry gate manifest, release profile, image lock, readiness record, repository를 수정하지 않습니다.

승격하지 않는 fixture 검사는 다음과 같이 실행합니다.

```sh
npm run test:m3:promotion
```

fixture 승인과 해시는 임시 테스트 디렉터리에만 존재합니다. 릴리스 증거가 아닙니다.
