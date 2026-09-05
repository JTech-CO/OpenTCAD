# M3 네이티브 어댑터 적합성

이 관측은 실제 `OciRuntimeBackend`를 Docker 또는 rootless Podman에 연결합니다. M0 직접 CLI fault collector와 의도적으로 분리되어 있습니다. M0 기록은 동결 상태를 유지하며 제품 어댑터 또는 host 자격을 주장하지 않습니다.

관측 결과는 항상 비승격 상태입니다. 통과 기록에서도 `qualified`, `approvalGranted`, `baselinePromotionAllowed`, `releaseImageApproved`, `solverApprovalGranted`, `platformApprovalGranted`는 모두 `false`입니다. 제품 entry gate manifest와 코드 소유 release profile은 수정하지 않습니다.

## Fixture 경계

`validation/fixtures/m3-runtime`은 엔진이 없는 Debian fixture입니다. Canonical archive import와 export, 결정적 성공, 선언된 비정상 종료, sleep, 지속 출력 부하를 위한 고정 entrypoint만 포함합니다. 출력 부하 entrypoint는 검토된 상한보다 많은 내용을 보낸 뒤에도 실행 상태를 유지합니다. 따라서 자연스러운 process 종료로 streaming 종료 case를 통과할 수 없습니다. SUPREM-IV.GS, DEVSIM, solver license, network client, 사용자가 선택하는 command 경로는 포함하지 않습니다.

Observer는 이 image를 build, publish, pull, remove하지 않습니다. 별도 통제 setup에서 검토된 source를 정확히 `localhost:5001/opentcad-m3-runtime-fixture`에 publish하고 OCI index 및 platform manifest digest를 확인한 다음 선택한 runtime에 같은 digest를 미리 load해야 합니다. Observer는 이후 adapter의 pull-never 경로만 사용합니다. Image 사전 검사는 local `image inspect`를 한 번 이상 포함하고 `image pull`은 포함하지 않으며 `manifest inspect` command 수는 정확히 0이어야 합니다. 이미 존재하던 fixture image는 삭제하지 않습니다.

## 실행

Python 3.12 이상을 사용합니다. Output directory는 절대 경로여야 하며 repository 외부에 새 경로로 지정해야 합니다.

현재 host의 Docker:

```text
python tools/observe-m3-native-adapter.py \
  --runtime docker \
  --image-reference localhost:5001/opentcad-m3-runtime-fixture@sha256:<index-hex> \
  --index-digest sha256:<index-hex> \
  --platform-manifest-digest sha256:<platform-manifest-hex> \
  --platform linux/amd64 \
  --output <absolute-external-directory>
```

검토된 Windows WSL transport의 rootless Podman:

```text
python tools/observe-m3-native-adapter.py \
  --runtime podman \
  --wsl-distribution Debian \
  --image-reference localhost:5001/opentcad-m3-runtime-fixture@sha256:<index-hex> \
  --index-digest sha256:<index-hex> \
  --platform-manifest-digest sha256:<platform-manifest-hex> \
  --platform linux/amd64 \
  --output <absolute-external-directory>
```

Linux 또는 macOS에서는 Podman을 직접 호출하며 `--wsl-distribution`을 허용하지 않습니다. Windows에서는 `wsl.exe -d Debian -- podman --cgroup-manager=cgroupfs`라는 고정 shell-free prefix만 허용합니다.

## 보호된 수동 workflow

`M3 native qualification` workflow는 보호된 self-hosted runner에서 같은 observer를 실행합니다. 정확한 후보 revision과 불변 image identity 값 4개를 입력해야 합니다. 선택한 platform과 backend는 runner label로도 사용하며 workflow는 관측 전에 실제 host를 확인합니다. Windows Podman에서는 검토된 `--wsl-distribution Debian` 인자를 자동으로 추가합니다.

Output path는 checkout 외부인 `runner.temp` 아래의 새 디렉터리입니다. 관측이 끝나면 artifact에 `manifest.json`이 들어가며 차단 또는 실패 시에는 `failure.json`이 들어갑니다. 마지막 workflow 단계는 `observedConformancePassed`가 `true`인지, runtime과 image identity가 정확히 일치하는지, managed container와 volume이 0개인지, 권한과 관련된 모든 필드가 `false`인지 검사합니다. 따라서 성공한 workflow run도 adapter 동작만 기록하며 자격이나 제품 권한을 부여하지 않습니다.

## 시나리오

Plan은 다음 case를 순서대로 실행합니다.

1. canonical input, 결정적 workload, canonical artifact export, exact cleanup
2. 선언된 비정상 종료
3. 외부 취소
4. timeout 분류
5. fixture가 실행 상태를 유지하는 중 streaming 출력 상한 종료
6. native call이 없는 stale fencing 거부
7. concurrent cleanup 멱등성

모든 native object는 managed label과 job label로 찾은 뒤 inspect합니다. 해당 run에 기록된 fence pair와 일치하는 경우에만 exact name으로 제거합니다. 전체 container, volume, image prune은 금지합니다. 최종 결과는 일치하는 container 0개와 volume 0개를 요구합니다. 외부 `state/cleanup-journal.json`에는 observer가 비정상 종료된 뒤 복구할 수 있도록 정확한 identity가 남습니다.

## 증거

전체 관측이 끝나면 `manifest.json`을 기록합니다. Preflight가 차단되거나 예상하지 못한 실패가 발생하면 `failure.json`을 기록합니다. Command stdout과 stderr는 저장하지 않으며 제한된 byte 수와 SHA-256 hash만 기록합니다. Scenario 실패는 그대로 실패로 남습니다. 특히 timeout, 출력 부하, fencing, cleanup 결함을 통과 결과로 바꾸지 않습니다. 전체 적합성은 추가로 `streamingOutputTerminationProven`과 `offlineLocalImageInspectionProven`이 `true`이고 `manifestInspectCommands`가 0이며 각 scenario cleanup에 adapter error가 없어야 합니다.

Raw evidence는 repository 외부에만 남으며 release image, solver, baseline, platform, 제품 승인의 입력이 아닙니다. 모든 관측 case가 통과해도 별도의 검토된 승격 절차가 필요합니다.
