# M3 native credential conformance

[한국어](../ko/m3-native-credentials.md)

This opt-in suite exercises the product-selected OS store, not the in-memory
test store or the Windows DPAPI-file alternative. It uses Windows Credential
Manager, macOS Keychain, or Linux Secret Service on the current host.

## Run on a dedicated test account

The account needs an available, unlocked credential provider. Linux requires
`secret-tool` and a running Secret Service on the user's session bus. The adapter
preserves `DBUS_SESSION_BUS_ADDRESS`, `XDG_RUNTIME_DIR`, `HOME`, and `PATH`, but
does not forward unrelated secrets or loader overrides to `secret-tool`.
This suite does not install, start, unlock, or reconfigure a credential service.

PowerShell:

```powershell
$env:OPENTCAD_NATIVE_CREDENTIAL_TESTS = '1'
python -m unittest backend.tests.service.test_native_credentials -v
Remove-Item Env:OPENTCAD_NATIVE_CREDENTIAL_TESTS
```

Linux or macOS:

```sh
OPENTCAD_NATIVE_CREDENTIAL_TESTS=1 python -m unittest backend.tests.service.test_native_credentials -v
```

Without explicit opt-in, normal discovery skips these three tests. With opt-in,
an unavailable or locked provider is a failure. There is no provider fallback.
Use a dedicated account for unattended runs, especially when a keychain might
otherwise require user interaction.

## What is proved

1. A binary test secret survives reading from a fresh Python process.
2. Replacement in another process is visible to the original and a third reader.
3. An OS-backed restore floor survives a fresh process and rejects both a lower
   snapshot sequence and a different snapshot at the same sequence.

Each test first checks that its randomly generated `opentcad-m3-probe.<uuid>`
service and exact credential ID are absent. Cleanup is registered before any
write. It deletes only those owned identities, repeats deletion to test
idempotence, and verifies absence. The real `opentcad` service is never used.
Secrets travel through stdin, not command arguments or test output. Child
processes are bounded by a 45-second timeout. If the entire parent test process
is forcibly terminated, normal unittest cleanup cannot be guaranteed; remove
only the test account's identified probe entries after investigation, never
clear the credential store globally.

The protected manual M3 native workflow requires this suite before runtime
observation. Native credential results remain separate from runtime manifests.
Retain the job log together with the exact revision and runtime observation for
human review. A passing suite grants no product, platform, power-loss, or solver
approval. Process persistence is not evidence of physical power-loss durability.
